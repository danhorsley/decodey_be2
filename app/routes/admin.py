# app/admin.py
from flask import Blueprint, request, jsonify, current_app
from flask_jwt_extended import jwt_required, get_jwt_identity, create_access_token
from werkzeug.security import check_password_hash
from app.models import db, User
import os
import datetime
import logging

# Create blueprint
admin_bp = Blueprint('admin', __name__, url_prefix='/admin')


# Simple admin authentication middleware
def admin_required(fn):

    @jwt_required()
    def wrapper(*args, **kwargs):
        # Get current user
        user_id = get_jwt_identity()
        user = User.query.get(user_id)

        # Check if user exists and is an admin
        if not user or not user.is_admin:
            return jsonify({"error": "Admin access required"}), 403

        return fn(*args, **kwargs)

    # Preserve the original function's name and docstring
    wrapper.__name__ = fn.__name__
    wrapper.__doc__ = fn.__doc__

    return wrapper


# Admin login endpoint
@admin_bp.route('/login', methods=['POST'])
@jwt_required()  # Require existing user authentication first
def admin_login():
    # Get username from token
    user_id = get_jwt_identity()
    user = User.query.get(user_id)

    if not user:
        return jsonify({"error": "User not found"}), 404

    # Get admin password from request
    data = request.get_json()
    admin_password = data.get('admin_password')

    if not admin_password:
        return jsonify({"error": "Admin password required"}), 400

    # Check if user is admin and verify password
    if user.is_admin and check_password_hash(user.admin_password_hash,
                                             admin_password):
        # Create admin token with extended expiration
        admin_token = create_access_token(
            identity=user_id,
            additional_claims={"is_admin": True},
            expires_delta=datetime.timedelta(
                hours=2)  # Short expiry for security
        )

        return jsonify({
            "message": "Admin login successful",
            "admin_token": admin_token
        }), 200

    # Log failed admin login attempts
    logging.warning(f"Failed admin login attempt for user: {user.username}")
    return jsonify({"error": "Invalid admin credentials"}), 401


# Database backup endpoint
@admin_bp.route('/backup', methods=['POST'])
@admin_required
def create_backup():
    try:
        # Create timestamp for filename
        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_dir = os.path.join(current_app.root_path, 'backups')

        # Create backup directory if it doesn't exist
        if not os.path.exists(backup_dir):
            os.makedirs(backup_dir)

        backup_file = os.path.join(backup_dir, f"backup_{timestamp}.sql")

        # Get database URL from app config
        db_url = current_app.config.get('SQLALCHEMY_DATABASE_URI')

        if 'sqlite' in db_url:
            # SQLite backup command
            db_path = db_url.replace('sqlite:///', '')
            os.system(f"sqlite3 {db_path} .dump > {backup_file}")
        else:
            # PostgreSQL backup command (assuming PostgreSQL)
            # Extract connection details from URL
            from urllib.parse import urlparse

            url = urlparse(db_url)
            dbname = url.path[1:]  # Remove leading slash
            user = url.username
            password = url.password
            host = url.hostname
            port = url.port or 5432

            # Create pg_dump command
            cmd = f"PGPASSWORD={password} pg_dump -h {host} -p {port} -U {user} -F c -b -v -f {backup_file} {dbname}"
            os.system(cmd)

        return jsonify({
            "message": "Backup created successfully",
            "filename": f"backup_{timestamp}.sql",
            "path": backup_file
        }), 200

    except Exception as e:
        logging.error(f"Backup failed: {str(e)}")
        return jsonify({"error": f"Backup failed: {str(e)}"}), 500


# List backups endpoint
@admin_bp.route('/backups', methods=['GET'])
@admin_required
def list_backups():
    try:
        backup_dir = os.path.join(current_app.root_path, 'backups')

        if not os.path.exists(backup_dir):
            return jsonify({"backups": []}), 200

        # Get all backup files
        backups = []
        for filename in os.listdir(backup_dir):
            if filename.startswith('backup_') and filename.endswith('.sql'):
                file_path = os.path.join(backup_dir, filename)
                file_size = os.path.getsize(file_path)
                file_date = datetime.datetime.fromtimestamp(
                    os.path.getctime(file_path)).strftime("%Y-%m-%d %H:%M:%S")

                backups.append({
                    "filename": filename,
                    "size": file_size,
                    "created_at": file_date
                })

        # Sort by creation date (newest first)
        backups.sort(key=lambda x: x["created_at"], reverse=True)

        return jsonify({"backups": backups}), 200

    except Exception as e:
        logging.error(f"Error listing backups: {str(e)}")
        return jsonify({"error": f"Error listing backups: {str(e)}"}), 500


# Get basic stats endpoint
@admin_bp.route('/stats', methods=['GET'])
@admin_required
def get_stats():
    try:
        # User stats
        total_users = User.query.count()
        recent_users = User.query.filter(
            User.created_at >= datetime.datetime.utcnow() -
            datetime.timedelta(days=7)).count()

        # Game stats
        from app.models import GameScore, ActiveGameState

        total_games = GameScore.query.count()
        completed_games = GameScore.query.filter_by(completed=True).count()
        active_games = ActiveGameState.query.count()

        # Get recent logins using SQL for efficiency
        recent_logins_sql = """
        SELECT COUNT(DISTINCT user_id) 
        FROM game_score 
        WHERE created_at >= (NOW() - INTERVAL '7 days')
        """

        result = db.session.execute(recent_logins_sql)
        active_players = result.scalar() or 0

        return jsonify({
            "user_stats": {
                "total_users": total_users,
                "new_users_7d": recent_users,
                "active_players_7d": active_players
            },
            "game_stats": {
                "total_games":
                total_games,
                "completed_games":
                completed_games,
                "active_games":
                active_games,
                "completion_rate":
                round(completed_games / total_games *
                      100, 1) if total_games > 0 else 0
            }
        }), 200

    except Exception as e:
        logging.error(f"Error fetching admin stats: {str(e)}")
        return jsonify({"error": f"Error fetching stats: {str(e)}"}), 500
