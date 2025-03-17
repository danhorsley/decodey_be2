from flask import Blueprint, jsonify, request
import logging
import os
from datetime import datetime

# Set up logging
logger = logging.getLogger(__name__)

bp = Blueprint('dev', __name__)

# Only enable these routes in development mode
DEV_MODE = os.environ.get('FLASK_ENV', 'development') == 'development'

@bp.route('/generate-dummy-data', methods=['GET'])
def generate_dummy_data_route():
    """Generate dummy data for development purposes"""
    # Security check - only allow in development mode
    if not DEV_MODE:
        return jsonify({"error": "This endpoint is only available in development mode"}), 403

    # Get parameters from query string
    num_users = request.args.get('users', default=25, type=int)
    min_games = request.args.get('min_games', default=10, type=int)
    max_games = request.args.get('max_games', default=50, type=int)
    secret = request.args.get('secret', default='')

    # Additional security - require a secret key (simple protection)
    if secret != 'dev-secret-key':
        return jsonify({"error": "Invalid secret key"}), 403

    try:
        # Import and run the dummy data generator
        from app.utils.dummy_data import generate_dummy_data

        # Record start time
        start_time = datetime.utcnow()

        # Generate the data
        users = generate_dummy_data(num_users, min_games, max_games)

        # Calculate elapsed time
        elapsed_time = (datetime.utcnow() - start_time).total_seconds()

        # Return results
        return jsonify({
            "success": True,
            "message": f"Generated dummy data for {len(users)} users with {min_games}-{max_games} games each",
            "users_created": len(users),
            "sample_users": [username for _, username in users[:5]] if users else [],
            "execution_time_seconds": elapsed_time
        }), 200

    except Exception as e:
        logger.error(f"Error generating dummy data: {e}", exc_info=True)
        return jsonify({
            "success": False,
            "error": str(e)
        }), 500

@bp.route('/clear-dummy-data', methods=['GET'])
def clear_dummy_data_route():
    """Clear all dummy data (for development purposes)"""
    # Security check - only allow in development mode
    if not DEV_MODE:
        return jsonify({"error": "This endpoint is only available in development mode"}), 403

    # Get secret from query string
    secret = request.args.get('secret', default='')

    # Additional security - require a secret key
    if secret != 'dev-secret-key':
        return jsonify({"error": "Invalid secret key"}), 403

    try:
        # Import required models
        from app.models import db, User, UserStats, GameScore, ActiveGameState, AnonymousGameState

        # Record counts before deletion
        users_count = User.query.count()
        games_count = GameScore.query.count()
        active_games_count = ActiveGameState.query.count()
        anon_games_count = AnonymousGameState.query.count()

        # Clear data in the correct order (respect foreign keys)
        ActiveGameState.query.delete()
        AnonymousGameState.query.delete()
        GameScore.query.delete()
        UserStats.query.delete()
        User.query.delete()

        # Commit the changes
        db.session.commit()

        return jsonify({
            "success": True,
            "message": "All dummy data cleared successfully",
            "deleted": {
                "users": users_count,
                "games": games_count,
                "active_games": active_games_count,
                "anonymous_games": anon_games_count
            }
        }), 200

    except Exception as e:
        logger.error(f"Error clearing dummy data: {e}", exc_info=True)
        db.session.rollback()
        return jsonify({
            "success": False,
            "error": str(e)
        }), 500