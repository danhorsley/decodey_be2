# app/routes/admin.py
from flask import Blueprint, request, jsonify, redirect, url_for, render_template, current_app, send_file
from flask_jwt_extended import jwt_required, get_jwt_identity, create_access_token
from werkzeug.security import check_password_hash
from app.models import db, User, GameScore, UserStats, ActiveGameState, BackupRecord, BackupSettings
import logging
import os
import datetime
import subprocess
from pathlib import Path
import csv
import io
import tempfile
from urllib.parse import urlparse
from functools import wraps
from datetime import datetime, timedelta

admin_bp = Blueprint('admin', __name__, url_prefix='/admin')
logger = logging.getLogger(__name__)


# Admin authentication decorator
def admin_required(f):
    from functools import wraps

    @wraps(f)
    def decorated_function(*args, **kwargs):
        # Check if user is logged in as admin using session
        admin_id = session.get('admin_id')

        if not admin_id:
            return redirect(
                url_for('admin.admin_login_page',
                        error="Please log in to access the admin area"))

        # Get the user
        user = User.query.get(admin_id)

        if not user or not user.is_admin:
            # Clear session and redirect
            session.pop('admin_id', None)
            return redirect(
                url_for('admin.admin_login_page',
                        error="Invalid admin credentials"))

        # Pass the admin user to the view
        kwargs['current_admin'] = user
        return f(*args, **kwargs)

    return decorated_function


# Helper function to format time ago
def get_time_ago(timestamp):
    """Format timestamp as relative time (e.g., '2 hours ago')"""
    now = datetime.datetime.utcnow()
    diff = now - timestamp

    if diff.days > 0:
        return f"{diff.days} days ago"
    hours = diff.seconds // 3600
    if hours > 0:
        return f"{hours} hours ago"
    minutes = (diff.seconds % 3600) // 60
    if minutes > 0:
        return f"{minutes} mins ago"
    return "Just now"


# Helper function to format file size
def get_size_format(b, factor=1024, suffix="B"):
    """Scale bytes to its proper byte format (e.g., KB, MB, GB, TB)"""
    for unit in ["", "K", "M", "G", "T", "P", "E", "Z"]:
        if b < factor:
            return f"{b:.2f} {unit}{suffix}"
        b /= factor
    return f"{b:.2f} Y{suffix}"


#
# Admin Authentication Routes
#


# Admin login page
@admin_bp.route('/login', methods=['GET', 'POST'])
def admin_login_page():
    """Admin login page and form processing"""
    error = request.args.get('error')

    if request.method == 'GET':
        return render_template('admin/login.html', error=error)

    # Handle POST (form submission)
    username = request.form.get('username')
    password = request.form.get('password')
    admin_password = request.form.get('admin_password')

    # Validate inputs
    if not username or not password or not admin_password:
        return render_template('admin/login.html',
                               error="All fields are required")

    # Find user by username
    user = User.query.filter_by(username=username).first()

    # Check if user exists, is admin, and both passwords are correct
    if not user:
        return render_template('admin/login.html', error="User not found")

    if not user.is_admin:
        return render_template('admin/login.html',
                               error="You don't have admin privileges")

    if not user.check_password(password):
        return render_template('admin/login.html', error="Invalid password")

    if not user.admin_password_hash or not check_password_hash(
            user.admin_password_hash, admin_password):
        return render_template('admin/login.html',
                               error="Invalid admin password")

    # Store admin ID in session
    session['admin_id'] = user.get_id()

    # Redirect to dashboard
    return redirect(url_for('admin.dashboard'))


# Admin API login (for AJAX requests)
@admin_bp.route('/api/login', methods=['POST'])
@jwt_required()  # Require existing user authentication first
def admin_login():
    """Admin login API endpoint (for AJAX)"""
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


# Admin logout
# Add admin logout route
@admin_bp.route('/logout')
def admin_logout():
    """Log out admin user"""
    session.pop('admin_id', None)
    return redirect(url_for('admin.admin_login_page'))


#
# Dashboard Routes
#


# Admin dashboard
@admin_bp.route('/dashboard', methods=['GET'])
@admin_required
def dashboard(current_admin):
    """Admin dashboard home page"""
    # Get basic statistics
    try:
        # User stats
        total_users = User.query.count()
        week_ago = datetime.datetime.utcnow() - datetime.timedelta(days=7)
        new_users = User.query.filter(User.created_at >= week_ago).count()
        new_users_percentage = round(
            (new_users / total_users) * 100) if total_users > 0 else 0

        # Game stats
        total_games = GameScore.query.count()
        new_games = GameScore.query.filter(
            GameScore.created_at >= week_ago).count()
        new_games_percentage = round(
            (new_games / total_games) * 100) if total_games > 0 else 0

        # Active users (with games in the last 24 hours)
        day_ago = datetime.datetime.utcnow() - datetime.timedelta(days=1)
        active_users = db.session.query(GameScore.user_id).distinct().filter(
            GameScore.created_at >= day_ago).count()

        # Completion rate
        completed_games = GameScore.query.filter_by(completed=True).count()
        completion_rate = round(
            (completed_games / total_games) * 100) if total_games > 0 else 0

        # Last week's completion rate for comparison
        two_weeks_ago = datetime.datetime.utcnow() - datetime.timedelta(
            days=14)
        old_completed = GameScore.query.filter(
            GameScore.created_at >= two_weeks_ago, GameScore.created_at
            < week_ago, GameScore.completed == True).count()
        old_total = GameScore.query.filter(
            GameScore.created_at >= two_weeks_ago, GameScore.created_at
            < week_ago).count()
        old_completion_rate = round(
            (old_completed / old_total) * 100) if old_total > 0 else 0
        completion_rate_change = completion_rate - old_completion_rate

        # Recent activities
        recent_activities = []
        recent_games = GameScore.query.order_by(
            GameScore.created_at.desc()).limit(5).all()
        for game in recent_games:
            user = User.query.get(game.user_id)
            username = user.username if user else "Unknown"
            time_ago = get_time_ago(game.created_at)
            action = "Game Completed" if game.completed else "Game Started"
            details = f"Score: {game.score}" if game.completed else f"Difficulty: {game.game_id.split('-')[0].capitalize()}"

            recent_activities.append({
                "time_ago": time_ago,
                "username": username,
                "action": action,
                "details": details
            })

        # Add admin activities if available
        # For now, just add a placeholder if needed to fill the table
        if len(recent_activities) < 5:
            recent_activities.append({
                "time_ago": "Just now",
                "username": current_admin.username,
                "action": "Admin Login",
                "details": "Dashboard access"
            })

        # Prepare stats dictionary
        stats = {
            "total_users": total_users,
            "new_users_percentage": new_users_percentage,
            "total_games": total_games,
            "new_games_percentage": new_games_percentage,
            "active_users": active_users,
            "completion_rate": completion_rate,
            "completion_rate_change": completion_rate_change,
            "last_updated": "Just now"
        }

        return render_template('admin/dashboard_home.html',
                               active_tab='dashboard',
                               stats=stats,
                               recent_activities=recent_activities)

    except Exception as e:
        logger.error(f"Error loading admin dashboard: {str(e)}")
        return render_template('admin/dashboard_home.html',
                               active_tab='dashboard',
                               error=f"Error loading statistics: {str(e)}",
                               stats={
                                   "total_users": 0,
                                   "new_users_percentage": 0,
                                   "total_games": 0,
                                   "new_games_percentage": 0,
                                   "active_users": 0,
                                   "completion_rate": 0,
                                   "completion_rate_change": 0,
                                   "last_updated": "Error"
                               },
                               recent_activities=[])


#
# User Management Routes
#


# User management page
@admin_bp.route('/users', methods=['GET'])
@admin_required
def users(current_admin):
    """User management page"""
    page = request.args.get('page', 1, type=int)
    per_page = 10

    search_query = request.args.get('search', '')
    status_filter = request.args.get('status', '')

    # Base query
    query = User.query

    # Apply search filter
    if search_query:
        query = query.filter((User.username.ilike(f'%{search_query}%'))
                             | (User.email.ilike(f'%{search_query}%')))

    # Apply status filter (would need to add status column or logic)
    # For now, we'll leave this as a placeholder

    # Execute query with pagination
    pagination = query.paginate(page=page, per_page=per_page)
    users_list = pagination.items

    # Enhance user data with game count
    for user in users_list:
        user.games_count = GameScore.query.filter_by(
            user_id=user.user_id).count()
        # Add a placeholder for suspension status
        user.is_suspended = False  # This would need actual implementation

    return render_template('admin/users.html',
                           active_tab='users',
                           users=users_list,
                           pagination=pagination,
                           search_query=search_query,
                           status_filter=status_filter)


# View user details
@admin_bp.route('/users/<user_id>', methods=['GET'])
@admin_required
def view_user(current_admin, user_id):
    """View details for a specific user"""
    user = User.query.get(user_id)
    if not user:
        return redirect(url_for('admin.users'))

    # Get user statistics
    stats = UserStats.query.filter_by(user_id=user_id).first()

    # Get recent games
    recent_games = GameScore.query.filter_by(user_id=user_id).order_by(
        GameScore.created_at.desc()).limit(10).all()

    return render_template('admin/user_detail.html',
                           active_tab='users',
                           user=user,
                           stats=stats,
                           recent_games=recent_games)


# Reset user password
@admin_bp.route('/users/<user_id>/reset-password', methods=['GET', 'POST'])
@admin_required
def reset_password(current_admin, user_id):
    """Reset password for a user"""
    user = User.query.get(user_id)
    if not user:
        return redirect(url_for('admin.users'))

    if request.method == 'GET':
        return render_template('admin/reset_password.html',
                               active_tab='users',
                               user=user)

    # Handle POST request
    new_password = request.form.get('new_password')
    if not new_password:
        return render_template('admin/reset_password.html',
                               active_tab='users',
                               user=user,
                               error="Password is required")

    # Update user's password
    user.set_password(new_password)
    db.session.commit()

    # Log the action
    logger.info(
        f"Admin {current_admin.username} reset password for user {user.username}"
    )

    # Redirect with success message
    return redirect(url_for('admin.view_user', user_id=user_id))


# Suspend/activate user
@admin_bp.route('/users/<user_id>/toggle-status', methods=['POST'])
@admin_required
def toggle_user_status(current_admin, user_id):
    """Suspend or activate a user account"""
    user = User.query.get(user_id)
    if not user:
        return redirect(url_for('admin.users'))

    # In a real implementation, you would have a status field in your User model
    # For now, we'll just redirect back
    return redirect(url_for('admin.view_user', user_id=user_id))


#
# Quote Management Routes
#


# Quote management page
@admin_bp.route('/quotes', methods=['GET'])
@admin_required
def quotes(current_admin):
    """Quote management page"""
    page = request.args.get('page', 1, type=int)
    per_page = 10

    search_query = request.args.get('search', '')
    author_filter = request.args.get('author', '')

    try:
        # Read quotes from CSV
        quotes_file = Path('quotes.csv')
        all_quotes = []
        authors = set()

        with open(quotes_file, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            for row in reader:
                all_quotes.append({
                    'quote': row['quote'],
                    'author': row['author'],
                    'minor_attribution': row['minor_attribution'],
                    'usage_count': 0  # Placeholder, would need actual tracking
                })
                authors.add(row['author'])

        # Apply filters
        filtered_quotes = all_quotes
        if search_query:
            filtered_quotes = [
                q for q in filtered_quotes
                if search_query.lower() in q['quote'].lower()
                or search_query.lower() in q['author'].lower()
            ]

        if author_filter:
            filtered_quotes = [
                q for q in filtered_quotes if q['author'] == author_filter
            ]

        # Paginate manually
        total_pages = (len(filtered_quotes) + per_page - 1) // per_page
        start_idx = (page - 1) * per_page
        end_idx = min(start_idx + per_page, len(filtered_quotes))
        paginated_quotes = filtered_quotes[start_idx:end_idx]

        # Create pagination object
        pagination = {
            'page': page,
            'per_page': per_page,
            'total': len(filtered_quotes),
            'pages': total_pages
        }

        return render_template('admin/quotes.html',
                               active_tab='quotes',
                               quotes=paginated_quotes,
                               authors=sorted(authors),
                               pagination=pagination,
                               search_query=search_query,
                               author_filter=author_filter)

    except Exception as e:
        logger.error(f"Error loading quotes: {str(e)}")
        return render_template('admin/quotes.html',
                               active_tab='quotes',
                               quotes=[],
                               authors=[],
                               error=f"Error loading quotes: {str(e)}")


# Add quote
@admin_bp.route('/quotes/add', methods=['POST'])
@admin_required
def add_quote(current_admin):
    """Add a new quote"""
    quote = request.form.get('quote', '')
    author = request.form.get('author', '')
    attribution = request.form.get('attribution', '')

    if not quote or not author:
        return redirect(
            url_for('admin.quotes', error="Quote and author are required"))

    try:
        # Read existing quotes
        quotes_file = Path('quotes.csv')
        quotes = []

        with open(quotes_file, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            for row in reader:
                quotes.append(row)

        # Add new quote
        quotes.append({
            'quote': quote,
            'author': author,
            'minor_attribution': attribution
        })

        # Write back to CSV
        with open(quotes_file, 'w', newline='', encoding='utf-8') as f:
            fieldnames = ['quote', 'author', 'minor_attribution']
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            for row in quotes:
                writer.writerow(row)

        logger.info(
            f"Admin {current_admin.username} created a database backup: {backup_file.name}"
        )
        return redirect(
            url_for('admin.backup', success="Backup created successfully"))

    except Exception as e:
        logger.error(f"Backup creation failed: {str(e)}")
        return redirect(
            url_for('admin.backup', error=f"Backup failed: {str(e)}"))


# Download backup
@admin_bp.route('/backup/download/<backup_id>', methods=['GET'])
@admin_required
def download_backup(current_admin, backup_id):
    """Download a backup file"""
    try:
        backup_dir = Path(current_app.root_path) / 'backups'
        backup_file = backup_dir / backup_id

        if not backup_file.exists():
            return redirect(
                url_for('admin.backup', error="Backup file not found"))

        return send_file(backup_file,
                         as_attachment=True,
                         download_name=backup_id)

    except Exception as e:
        logger.error(f"Error downloading backup: {str(e)}")
        return redirect(
            url_for('admin.backup',
                    error=f"Error downloading backup: {str(e)}"))


# Delete backup
@admin_bp.route('/backup/delete/<backup_id>', methods=['GET'])
@admin_required
def delete_backup(current_admin, backup_id):
    """Delete a backup file"""
    try:
        backup_dir = Path(current_app.root_path) / 'backups'
        backup_file = backup_dir / backup_id

        if not backup_file.exists():
            return redirect(
                url_for('admin.backup', error="Backup file not found"))

        backup_file.unlink()
        logger.info(
            f"Admin {current_admin.username} deleted backup: {backup_id}")
        return redirect(
            url_for('admin.backup', success="Backup deleted successfully"))

    except Exception as e:
        logger.error(f"Error deleting backup: {str(e)}")
        return redirect(
            url_for('admin.backup', error=f"Error deleting backup: {str(e)}"))


# Restore backup
@admin_bp.route('/backup/restore/<backup_id>', methods=['GET'])
@admin_required
def restore_backup(current_admin, backup_id):
    """Restore a database from backup"""
    try:
        backup_dir = Path(current_app.root_path) / 'backups'
        backup_file = backup_dir / backup_id

        if not backup_file.exists():
            return redirect(
                url_for('admin.backup', error="Backup file not found"))

        # Get database URL from app config
        db_url = current_app.config.get('SQLALCHEMY_DATABASE_URI')

        if 'sqlite' in db_url:
            # SQLite restore command
            db_path = db_url.replace('sqlite:///', '')

            # Create a temporary database first
            temp_db = f"{db_path}.temp"

            # Restore to temporary database
            result = subprocess.run(f"sqlite3 {temp_db} < {backup_file}",
                                    shell=True,
                                    capture_output=True,
                                    text=True)

            if result.returncode != 0:
                raise Exception(f"SQLite restore failed: {result.stderr}")

            # If successful, replace the original
            import shutil
            shutil.move(temp_db, db_path)

        else:
            # PostgreSQL restore command
            url = urlparse(db_url)
            dbname = url.path[1:]  # Remove leading slash
            user = url.username
            password = url.password
            host = url.hostname
            port = url.port or 5432

            # Set PGPASSWORD environment variable
            env = os.environ.copy()
            env["PGPASSWORD"] = password

            # Create pg_restore command
            cmd = [
                "pg_restore",
                "-h",
                host,
                "-p",
                str(port),
                "-U",
                user,
                "-d",
                dbname,
                "-c",  # Clean (drop) database objects before recreating
                "-v",  # Verbose
                str(backup_file)
            ]

            result = subprocess.run(cmd,
                                    env=env,
                                    capture_output=True,
                                    text=True)

            if result.returncode != 0:
                raise Exception(f"PostgreSQL restore failed: {result.stderr}")

        logger.info(
            f"Admin {current_admin.username} restored database from backup: {backup_id}"
        )

        # Force refresh database connections
        db.session.remove()
        db.engine.dispose()

        return redirect(
            url_for('admin.backup', success="Backup restored successfully"))

    except Exception as e:
        logger.error(f"Error restoring backup: {str(e)}")
        return redirect(
            url_for('admin.backup', error=f"Error restoring backup: {str(e)}"))


# Update backup settings
@admin_bp.route('/backup/settings', methods=['POST'])
@admin_required
def update_backup_settings(current_admin):
    """Update backup schedule settings"""
    daily_backup = request.form.get('daily_backup', 'off') == 'on'
    weekly_backup = request.form.get('weekly_backup', 'off') == 'on'
    retention_days = int(request.form.get('retention_days', 14))

    try:
        # In a real implementation, you would save these settings to the database
        # For now, we'll just redirect back with a success message
        logger.info(f"Admin {current_admin.username} updated backup settings")
        return redirect(
            url_for('admin.backup', success="Backup settings updated"))

    except Exception as e:
        logger.error(f"Error updating backup settings: {str(e)}")
        return redirect(
            url_for('admin.backup',
                    error=f"Error updating backup settings: {str(e)}"))


#
# System Settings Routes
#


# System settings page
@admin_bp.route('/settings', methods=['GET'])
@admin_required
def settings(current_admin):
    """System settings page"""
    # Default settings
    game_settings = {
        "easy_max_mistakes": 8,
        "medium_max_mistakes": 6,
        "hard_max_mistakes": 4,
        "quote_selection": "random"
    }

    system_status = {
        "maintenance_mode": False,
        "maintenance_message":
        "We're currently performing system maintenance. Please check back in a few minutes.",
        "allow_registrations": True
    }

    security_settings = {
        "jwt_last_rotated": "2023-05-15",
        "login_rate_limit_attempts": 5,
        "login_rate_limit_minutes": 5,
        "user_session_timeout": 60,
        "admin_session_timeout": 15
    }

    email_settings = {
        "smtp_server": "smtp.example.com",
        "smtp_port": 587,
        "smtp_username": "noreply@uncrypt.game",
        "smtp_password": "********",
        "use_ssl": True,
        "from_name": "Uncrypt Game",
        "from_email": "noreply@uncrypt.game"
    }

    return render_template('admin/settings.html',
                           active_tab='settings',
                           game_settings=game_settings,
                           system_status=system_status,
                           security_settings=security_settings,
                           email_settings=email_settings)


#
# Analytics Routes
#


# Analytics page
@admin_bp.route('/analytics', methods=['GET'])
@admin_required
def analytics(current_admin):
    """Analytics dashboard page"""
    # Get date range
    date_range = request.args.get('date_range', 'last_30_days')

    if date_range == 'last_7_days':
        start_date = datetime.datetime.utcnow() - datetime.timedelta(days=7)
    elif date_range == 'last_90_days':
        start_date = datetime.datetime.utcnow() - datetime.timedelta(days=90)
    elif date_range == 'last_year':
        start_date = datetime.datetime.utcnow() - datetime.timedelta(days=365)
    elif date_range == 'all_time':
        start_date = datetime.datetime(2000, 1, 1)  # A date far in the past
    else:  # default to 30 days
        start_date = datetime.datetime.utcnow() - datetime.timedelta(days=30)

    # Basic statistics for cards
    try:
        # New Users
        new_users = User.query.filter(User.created_at >= start_date).count()
        total_users = User.query.count()
        new_users_percentage = round(
            (new_users / total_users) * 100) if total_users > 0 else 0

        # Games Played
        games_played = GameScore.query.filter(
            GameScore.created_at >= start_date).count()
        total_games = GameScore.query.count()
        games_percentage = round(
            (games_played / total_games) * 100) if total_games > 0 else 0

        # Average Session Time
        game_times = db.session.query(GameScore.time_taken).filter(
            GameScore.created_at >= start_date,
            GameScore.completed == True).all()

        avg_session = 0
        if game_times:
            avg_seconds = sum(t[0] for t in game_times) / len(game_times)
            minutes = int(avg_seconds // 60)
            seconds = int(avg_seconds % 60)
            avg_session_display = f"{minutes}:{seconds:02d}"
        else:
            avg_session_display = "0:00"

        # Completion Rate
        completed_games = GameScore.query.filter(
            GameScore.created_at >= start_date,
            GameScore.completed == True).count()

        period_games = GameScore.query.filter(
            GameScore.created_at >= start_date).count()

        completion_rate = round(
            (completed_games / period_games) * 100) if period_games > 0 else 0

        # Previous period for comparison
        period_length = (datetime.datetime.utcnow() - start_date).days
        prev_start_date = start_date - datetime.timedelta(days=period_length)

        prev_completed = GameScore.query.filter(
            GameScore.created_at >= prev_start_date, GameScore.created_at
            < start_date, GameScore.completed == True).count()

        prev_total = GameScore.query.filter(
            GameScore.created_at >= prev_start_date, GameScore.created_at
            < start_date).count()

        prev_completion_rate = round(
            (prev_completed / prev_total) * 100) if prev_total > 0 else 0
        completion_rate_change = completion_rate - prev_completion_rate

        # Data for charts
        # User Growth
        user_growth_data = get_user_growth_data(start_date)

        # Difficulty Distribution
        difficulty_data = get_difficulty_distribution(start_date)

        # User Retention
        retention_data = get_user_retention_data(start_date)

        # Popular Quotes
        quotes_data = get_popular_quotes_data(start_date)

        return render_template('admin/analytics.html',
                               active_tab='analytics',
                               date_range=date_range,
                               stats={
                                   "new_users": new_users,
                                   "new_users_percentage":
                                   new_users_percentage,
                                   "games_played": games_played,
                                   "games_percentage": games_percentage,
                                   "avg_session": avg_session_display,
                                   "completion_rate": completion_rate,
                                   "completion_rate_change":
                                   completion_rate_change
                               },
                               user_growth_data=user_growth_data,
                               difficulty_data=difficulty_data,
                               retention_data=retention_data,
                               quotes_data=quotes_data)

    except Exception as e:
        logger.error(f"Error loading analytics: {str(e)}")
        return render_template('admin/analytics.html',
                               active_tab='analytics',
                               date_range=date_range,
                               error=f"Error loading analytics: {str(e)}")


# Helper functions for analytics
def get_user_growth_data(start_date):
    """Get user growth data for chart"""
    # This is a placeholder - in a real implementation,
    # you would query the database for actual user registration counts
    # grouped by day/week/month depending on the date range
    return [{
        "date": "2023-05-01",
        "count": 10
    }, {
        "date": "2023-05-08",
        "count": 15
    }, {
        "date": "2023-05-15",
        "count": 12
    }, {
        "date": "2023-05-22",
        "count": 20
    }, {
        "date": "2023-05-29",
        "count": 25
    }, {
        "date": "2023-06-05",
        "count": 30
    }, {
        "date": "2023-06-12",
        "count": 28
    }, {
        "date": "2023-06-19",
        "count": 35
    }, {
        "date": "2023-06-26",
        "count": 42
    }]


def get_difficulty_distribution(start_date):
    """Get game difficulty distribution data for chart"""
    # Placeholder data
    return [{
        "difficulty": "Easy",
        "count": 250
    }, {
        "difficulty": "Medium",
        "count": 450
    }, {
        "difficulty": "Hard",
        "count": 150
    }]


def get_user_retention_data(start_date):
    """Get user retention data for chart"""
    # Placeholder data
    return [{
        "cohort": "Week 1",
        "week1": 100,
        "week2": 80,
        "week3": 65,
        "week4": 55
    }, {
        "cohort": "Week 2",
        "week1": 100,
        "week2": 85,
        "week3": 70,
        "week4": 60
    }, {
        "cohort": "Week 3",
        "week1": 100,
        "week2": 75,
        "week3": 60,
        "week4": 50
    }, {
        "cohort": "Week 4",
        "week1": 100,
        "week2": 82,
        "week3": 68,
        "week4": 58
    }]


def get_popular_quotes_data(start_date):
    """Get popular quotes data for chart"""
    # Placeholder data
    return [{
        "quote": "Knowledge is power",
        "author": "Francis Bacon",
        "count": 45
    }, {
        "quote": "Time is money",
        "author": "Benjamin Franklin",
        "count": 38
    }, {
        "quote": "To be or not to be",
        "author": "William Shakespeare",
        "count": 32
    }, {
        "quote": "I think, therefore I am",
        "author": "René Descartes",
        "count": 29
    }, {
        "quote": "Science is organized knowledge",
        "author": "Herbert Spencer",
        "count": 26
    }]


# Edit quote
@admin_bp.route('/quotes/edit', methods=['POST'])
@admin_required
def edit_quote(current_admin):
    """Edit an existing quote"""
    quote_id = request.form.get('quote_id', '')
    quote = request.form.get('quote', '')
    author = request.form.get('author', '')
    attribution = request.form.get('attribution', '')

    if not quote_id or not quote or not author:
        return redirect(
            url_for('admin.quotes',
                    error="Quote ID, quote text, and author are required"))

    try:
        # Convert quote_id to integer index (1-based)
        index = int(quote_id) - 1

        # Read existing quotes
        quotes_file = Path('quotes.csv')
        quotes = []

        with open(quotes_file, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            for row in reader:
                quotes.append(row)

        # Check if index is valid
        if index < 0 or index >= len(quotes):
            return redirect(url_for('admin.quotes', error="Invalid quote ID"))

        # Update quote
        quotes[index] = {
            'quote': quote,
            'author': author,
            'minor_attribution': attribution
        }

        # Write back to CSV
        with open(quotes_file, 'w', newline='', encoding='utf-8') as f:
            fieldnames = ['quote', 'author', 'minor_attribution']
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            for row in quotes:
                writer.writerow(row)

        logger.info(f"Admin {current_admin.username} edited quote #{quote_id}")
        return redirect(
            url_for('admin.quotes', success="Quote updated successfully"))

    except Exception as e:
        logger.error(f"Error editing quote: {str(e)}")
        return redirect(
            url_for('admin.quotes', error=f"Error editing quote: {str(e)}"))


# Delete quote
@admin_bp.route('/quotes/delete/<int:quote_id>', methods=['GET'])
@admin_required
def delete_quote(current_admin, quote_id):
    """Delete a quote"""
    try:
        # Convert quote_id to zero-based index
        index = quote_id - 1

        # Read existing quotes
        quotes_file = Path('quotes.csv')
        quotes = []

        with open(quotes_file, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            for row in reader:
                quotes.append(row)

        # Check if index is valid
        if index < 0 or index >= len(quotes):
            return redirect(url_for('admin.quotes', error="Invalid quote ID"))

        # Remove quote
        deleted_quote = quotes.pop(index)

        # Write back to CSV
        with open(quotes_file, 'w', newline='', encoding='utf-8') as f:
            fieldnames = ['quote', 'author', 'minor_attribution']
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            for row in quotes:
                writer.writerow(row)

        logger.info(
            f"Admin {current_admin.username} deleted quote by {deleted_quote['author']}"
        )
        return redirect(
            url_for('admin.quotes', success="Quote deleted successfully"))

    except Exception as e:
        logger.error(f"Error deleting quote: {str(e)}")
        return redirect(
            url_for('admin.quotes', error=f"Error deleting quote: {str(e)}"))


# Export quotes
@admin_bp.route('/quotes/export', methods=['GET'])
@admin_required
def export_quotes(current_admin):
    """Export quotes as CSV"""
    try:
        quotes_file = Path('quotes.csv')
        return send_file(quotes_file,
                         as_attachment=True,
                         download_name='quotes.csv')

    except Exception as e:
        logger.error(f"Error exporting quotes: {str(e)}")
        return redirect(
            url_for('admin.quotes', error=f"Error exporting quotes: {str(e)}"))


# Import quotes
@admin_bp.route('/quotes/import', methods=['POST'])
@admin_required
def import_quotes(current_admin):
    """Import quotes from CSV"""
    if 'csv_file' not in request.files:
        return redirect(url_for('admin.quotes', error="No file provided"))

    file = request.files['csv_file']
    if file.filename == '':
        return redirect(url_for('admin.quotes', error="No file selected"))

    replace_existing = request.form.get('replace_existing', 'off') == 'on'

    try:
        # Read the uploaded file
        stream = io.StringIO(file.stream.read().decode("UTF8"), newline=None)
        csv_input = csv.DictReader(stream)

        # Validate CSV structure
        required_fields = ['quote', 'author', 'minor_attribution']
        for field in required_fields:
            if field not in csv_input.fieldnames:
                return redirect(
                    url_for('admin.quotes',
                            error=f"Missing required field: {field}"))

        # Process the uploaded CSV
        new_quotes = [row for row in csv_input]

        if replace_existing:
            # Replace all quotes
            quotes = new_quotes
        else:
            # Append to existing quotes
            quotes_file = Path('quotes.csv')
            existing_quotes = []

            with open(quotes_file, 'r', encoding='utf-8') as f:
                reader = csv.DictReader(f)
                for row in reader:
                    existing_quotes.append(row)

            quotes = existing_quotes + new_quotes

        # Write back to CSV
        quotes_file = Path('quotes.csv')
        with open(quotes_file, 'w', newline='', encoding='utf-8') as f:
            fieldnames = ['quote', 'author', 'minor_attribution']
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            for row in quotes:
                writer.writerow(
                    {field: row.get(field, '')
                     for field in fieldnames})

        logger.info(
            f"Admin {current_admin.username} imported {len(new_quotes)} quotes"
        )
        return redirect(
            url_for('admin.quotes',
                    success=f"Successfully imported {len(new_quotes)} quotes"))

    except Exception as e:
        logger.error(f"Error importing quotes: {str(e)}")
        return redirect(
            url_for('admin.quotes', error=f"Error importing quotes: {str(e)}"))


#
# Database Backup Routes
#


# Database backup page
@admin_bp.route('/backup', methods=['GET'])
@admin_required
def backup(current_admin):
    """Database backup management page"""
    # Default empty values in case of error
    backup_info = {
        "last_backup_time": "Never",
        "status": "Unknown",
        "size": "0 KB",
        "location": "/app/backups/"
    }

    backup_settings = {
        "daily_backup": True,
        "weekly_backup": True,
        "retention_days": 14
    }

    backups = []

    try:
        # Create backup directory if it doesn't exist
        backup_dir = Path(current_app.root_path) / 'backups'
        if not backup_dir.exists():
            backup_dir.mkdir(parents=True)

        # List existing backup files
        backup_files = list(backup_dir.glob('backup_*.sql'))
        for file in backup_files:
            file_stat = file.stat()
            file_size = get_size_format(file_stat.st_size)
            creation_time = datetime.datetime.fromtimestamp(file_stat.st_ctime)

            # Extract backup type from filename
            if 'daily' in file.name:
                backup_type = 'Scheduled (Daily)'
            elif 'weekly' in file.name:
                backup_type = 'Scheduled (Weekly)'
            else:
                backup_type = 'Manual'

            backups.append({
                'id':
                file.name,
                'created_at':
                creation_time.strftime('%Y-%m-%d %H:%M:%S'),
                'type':
                backup_type,
                'size':
                file_size,
                'status':
                'Success'  # Assume all existing files are successful
            })

        # Sort backups by creation time (newest first)
        backups.sort(key=lambda x: x['created_at'], reverse=True)

        # Update last backup info if available
        if backups:
            last_backup = backups[0]
            backup_info = {
                "last_backup_time": last_backup['created_at'],
                "status": last_backup['status'],
                "size": last_backup['size'],
                "location": str(backup_dir)
            }

        return render_template('admin/backup.html',
                               active_tab='backup',
                               backup_info=backup_info,
                               backup_settings=backup_settings,
                               backups=backups)

    except Exception as e:
        logger.error(f"Error loading backup page: {str(e)}")
        return render_template(
            'admin/backup.html',
            active_tab='backup',
            backup_info=backup_info,
            backup_settings=backup_settings,
            backups=[],
            error=f"Error loading backup information: {str(e)}")


# Create database backup
# Fixed create_backup function for app/routes/admin.py


@admin_bp.route('/backup/create', methods=['POST'])
@admin_required
def create_backup(current_admin):
    """Create a new database backup"""
    try:
        # Create timestamp for filename
        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_dir = Path(current_app.root_path) / 'backups'

        # Create backup directory if it doesn't exist
        if not backup_dir.exists():
            backup_dir.mkdir(parents=True)

        backup_file = backup_dir / f"backup_manual_{timestamp}.sql"

        # Get database URL from app config
        db_url = current_app.config.get('SQLALCHEMY_DATABASE_URI')

        if 'sqlite' in db_url:
            # SQLite backup command
            db_path = db_url.replace('sqlite:///', '')
            result = subprocess.run(f"sqlite3 {db_path} .dump > {backup_file}",
                                    shell=True,
                                    capture_output=True,
                                    text=True)

            if result.returncode != 0:
                raise Exception(f"SQLite backup failed: {result.stderr}")
        else:
            # PostgreSQL backup command (assuming PostgreSQL)
            # Extract connection details from URL
            url = urlparse(db_url)
            dbname = url.path[1:]  # Remove leading slash
            user = url.username
            password = url.password
            host = url.hostname
            port = url.port or 5432

            # Set PGPASSWORD environment variable
            env = os.environ.copy()
            if password:
                env["PGPASSWORD"] = password

            # Create pg_dump command
            cmd = [
                "pg_dump",
                "-h",
                host,
                "-p",
                str(port),
                "-U",
                user,
                "-F",
                "c",  # Custom format
                "-b",  # Include blobs
                "-v",  # Verbose
                "-f",
                str(backup_file),
                dbname
            ]

            result = subprocess.run(cmd,
                                    env=env,
                                    capture_output=True,
                                    text=True)

            if result.returncode != 0:
                raise Exception(f"PostgreSQL backup failed: {result.stderr}")

        # Record the backup in the database if BackupRecord is available
        try:
            # Get file size
            file_size = os.path.getsize(backup_file)

            # Create backup record
            backup_record = BackupRecord(filename=backup_file.name,
                                         backup_type='manual',
                                         size_bytes=file_size,
                                         status='success',
                                         created_by=current_admin.user_id)
            db.session.add(backup_record)
            db.session.commit()
            logger.info(f"Backup record created: {backup_record.id}")
        except Exception as record_error:
            logger.error(f"Error creating backup record: {str(record_error)}")
            # Continue even if record creation fails - we still have the backup file

        logger.info(
            f"Admin {current_admin.username} created a database backup: {backup_file.name}"
        )
        return redirect(
            url_for('admin.backup', success="Backup created successfully"))

    except Exception as e:
        logger.error(f"Backup creation failed: {str(e)}")
        return redirect(
            url_for('admin.backup', error=f"Backup failed: {str(e)}"))
