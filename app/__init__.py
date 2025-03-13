from flask import Flask
from flask_jwt_extended import JWTManager
from flask_cors import CORS
from config import Config
from app.models import db
import logging

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

    # Configure SQLAlchemy
    try:
        logger.info(f"Configuring database with URL: {app.config['DATABASE_URL']}")
        app.config['SQLALCHEMY_DATABASE_URI'] = app.config['DATABASE_URL']
        app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
        app.config['SQLALCHEMY_ENGINE_OPTIONS'] = {
            "pool_recycle": 300,
            "pool_pre_ping": True,
        }

        # Initialize extensions
        CORS(app)
        jwt.init_app(app)
        db.init_app(app)
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

        # Register blueprints
        from app.routes import auth, game, stats, leaderboard, main
        app.register_blueprint(main.bp)
        app.register_blueprint(auth.bp)
        app.register_blueprint(game.bp)
        app.register_blueprint(stats.bp)
        app.register_blueprint(leaderboard.bp)
        logger.info("Successfully registered all blueprints")

    except Exception as e:
        logger.error(f"Error during application initialization: {str(e)}")
        raise

    logger.info("Application initialization completed successfully")
    return app