from flask import Flask
from flask_jwt_extended import JWTManager
from flask_cors import CORS
from config import Config

jwt = JWTManager()
# Store revoked tokens in memory
jwt_blocklist = set()

def create_app(config_class=Config):
    app = Flask(__name__)
    app.config.from_object(config_class)

    # Initialize extensions
    CORS(app)
    jwt.init_app(app)

    # Register token blocklist loader
    @jwt.token_in_blocklist_loader
    def check_if_token_in_blocklist(jwt_header, jwt_payload):
        jti = jwt_payload["jti"]
        return jti in jwt_blocklist

    # Register blueprints
    from app.routes import auth, game, stats, leaderboard, main
    app.register_blueprint(main.bp)
    app.register_blueprint(auth.bp)
    app.register_blueprint(game.bp)
    app.register_blueprint(stats.bp)
    app.register_blueprint(leaderboard.bp)

    return app