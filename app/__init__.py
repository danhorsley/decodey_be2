from flask import Flask, jsonify
from flask_jwt_extended import JWTManager
from flask_cors import CORS
from config import Config
from app.models import db, User
import logging
from flask_jwt_extended import exceptions as jwt_exceptions
from flask_migrate import Migrate
import os

jwt = JWTManager()
# Store revoked tokens in memory
jwt_blocklist = set()


def create_app(config_class=Config):
    app = Flask(__name__)
    app.config.from_object(config_class)

    # Set up logging
    logging.basicConfig(level=logging.DEBUG)
    logger = logging.getLogger(__name__)
    logger.info("Starting application initialization")

    # Configure CORS
    if app.config['FLASK_ENV'] == 'development':
        CORS(
            app,
            resources={
                r"/*": {  # Apply CORS to all routes
                    "origins": "*",  # Allow all origins during development
                    "methods": ["GET", "POST", "PUT", "DELETE", "OPTIONS"],
                    "allow_headers":
                    ["Content-Type", "Authorization", "Accept"],
                    "expose_headers": ["Content-Type", "Authorization"],
                    "supports_credentials": True
                }
            })

        app.config['JWT_COOKIE_CSRF_PROTECT'] = False
        app.config['JWT_COOKIE_SECURE'] = False
        app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY',
                                                  'dev-secret-key')
    else:
        CORS(app,
             resources={
                 r"/*": {
                     "origins": "https://decodey.game",
                     "allow_credentials": True,
                     "expose_headers": ["Content-Type", "Authorization"],
                     "allow_headers":
                     ["Content-Type", "Authorization", "Accept"],
                     "methods": ["GET", "POST", "PUT", "DELETE", "OPTIONS"]
                 }
             })
        app.config['JWT_COOKIE_CSRF_PROTECT'] = True
        app.config['JWT_COOKIE_SECURE'] = True
        app.config['JWT_COOKIE_SAMESITE'] = 'None'
        app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY')
    # JWT Configuration
    app.config['JWT_TOKEN_LOCATION'] = ['headers', 'cookies']
    app.config['JWT_HEADER_NAME'] = 'Authorization'
    app.config['JWT_HEADER_TYPE'] = 'Bearer'
    app.config['JWT_ACCESS_COOKIE_NAME'] = 'access_token_cookie'
    app.config['JWT_REFRESH_COOKIE_NAME'] = 'refresh_token_cookie'
    app.config['JWT_COOKIE_DOMAIN'] = '.replit.dev' if app.config['FLASK_ENV'] != 'development' else None

    @jwt.expired_token_loader
    def expired_token_callback(jwt_header, jwt_payload):
        return jsonify({"error": "Token has expired"}), 401

    @jwt.invalid_token_loader
    def invalid_token_callback(error):
        return jsonify({"error": "Invalid token"}), 401

    @jwt.unauthorized_loader
    def missing_token_callback(error):
        return jsonify({"error": "Authorization token is missing"}), 401

    @jwt.revoked_token_loader
    def revoked_token_callback(jwt_header, jwt_payload):
        return jsonify({"msg": "Token has been revoked"}), 401

    # Configure SQLAlchemy
    try:
        logger.info(
            f"Configuring database with URL: {app.config['DATABASE_URL']}")
        app.config['SQLALCHEMY_DATABASE_URI'] = app.config['DATABASE_URL']
        app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
        app.config['SQLALCHEMY_ENGINE_OPTIONS'] = {
            "pool_recycle": 300,
            "pool_pre_ping": True,
        }

        # Initialize extensions
        jwt.init_app(app)
        db.init_app(app)
        migrate = Migrate(app, db)
        logger.info("Successfully initialized Flask extensions")

        # Register token blocklist loader
        @jwt.token_in_blocklist_loader
        def check_if_token_in_blocklist(jwt_header, jwt_payload):
            jti = jwt_payload["jti"]
            return jti in jwt_blocklist

        # Create database tables
        with app.app_context():
            db.create_all()
            logger.info("Database tables created successfully")

        # Register blueprints without API prefixes
        from app.routes import auth, game, stats, main, dev, daily
        from app.routes.admin import admin_bp
        from app.routes.admin_process import admin_process_bp
        app.register_blueprint(admin_bp)
        app.register_blueprint(main.bp)  # Main routes
        app.register_blueprint(
            auth.bp)  # Auth routes (/login, /register, etc.)
        app.register_blueprint(game.bp, url_prefix='/api')
        app.register_blueprint(stats.bp, url_prefix='/api')
        app.register_blueprint(daily.bp, url_prefix='/api')
        app.register_blueprint(dev.bp, url_prefix='/dev')  # dev routes
        app.register_blueprint(admin_process_bp)
        logger.info("Successfully registered all blueprints")

        # Initialize admin-specific features
        from app.admin_setup import init_admin
        init_admin(app)

    except Exception as e:
        logger.error(f"Error during application initialization: {str(e)}")
        raise

    # Setup admin user in production
    # if app.config['FLASK_ENV'] != 'development':
    # try:
    # admin_user = os.environ.get('ADMIN_USER')
    # admin_pass = os.environ.get('ADMIN_PASSWORD_1')
    # admin_pass2 = os.environ.get('ADMIN_PASSWORD_2')

    # if admin_user and admin_pass and admin_pass2:
    #     logger.info("Setting up admin user in production")
    #     with app.app_context():
    #         user = User.query.filter_by(username=admin_user).first()

    #         if not user:
    #             user = User(username=admin_user,
    #                         email=f"{admin_user}@decodey.game",
    #                         password=admin_pass)
    #             user.is_admin = True
    #             db.session.add(user)
    #         else:
    #             user.set_password(admin_pass)
    #             user.is_admin = True

    #         user.set_admin_password(admin_pass2)
    #         db.session.commit()
    #         logger.info("Admin user setup completed")
    # except Exception as e:
    #     logger.error(f"Failed to setup admin user: {str(e)}")

    logger.info("Application initialization completed successfully")
    return app