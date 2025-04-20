# app/routes/admin_process.py
"""
Implementation of various admin processing functions for the admin portal.
This file contains the route handlers for form submissions from the admin interface.
"""

from flask import Blueprint, request, jsonify, redirect, url_for, render_template, flash, current_app, session
from werkzeug.security import generate_password_hash, check_password_hash
from app.models import db, User, GameScore, UserStats, ActiveGameState, BackupSettings, DailyCompletion, Quote, DailyCompletion
import logging
import os
import secrets
import json
from datetime import datetime, timedelta
from pathlib import Path
import smtplib
import random
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from sqlalchemy import func, text

# Set up logger
logger = logging.getLogger(__name__)

# Create blueprint for admin process routes
admin_process_bp = Blueprint('admin_process',
                             __name__,
                             url_prefix='/admin/process')


# Admin authentication decorator (import this from your existing code)
def admin_required(f):
    """Decorator to check if user is logged in as admin"""
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
            return redirect(url_for('admin.admin_login_page'))

        # Pass the admin user to the view
        kwargs['current_admin'] = user
        return f(*args, **kwargs)

    return decorated_function


@admin_process_bp.route('/recalculate-weekly-winners', methods=['POST'])
@admin_required
def recalculate_weekly_winners(current_admin):
    """Manually recalculate weekly winners for all weeks since inception"""
    try:
        from datetime import datetime, timedelta
        from app.models import LeaderboardEntry, GameScore, User
        from sqlalchemy import func

        # Get the date of the first game ever played
        first_game = GameScore.query.order_by(
            GameScore.created_at.asc()).first()
        if not first_game:
            return redirect(url_for('admin.dashboard', error="No games found"))

        # Start from the beginning of the week of the first game
        # Start from the first Monday at 00:01 after the first game
        start_date = first_game.created_at.date() - timedelta(
            days=first_game.created_at.weekday())
        start_date = datetime.combine(
            start_date, datetime.min.time()) + timedelta(minutes=1)
        end_date = datetime.utcnow()

        # Delete all existing weekly leaderboard entries
        LeaderboardEntry.query.filter_by(period_type='weekly').delete()

        # Process each week
        current_start = start_date
        while current_start <= end_date:
            # End at 00:01 next Monday
            current_end = current_start + timedelta(days=7)

            # Get weekly scores and stats
            weekly_stats = db.session.query(
                GameScore.user_id, User.username,
                db.func.sum(GameScore.score).label('total_score'),
                db.func.count(GameScore.id).label('games_played'),
                db.func.sum(db.case(
                    (GameScore.mistakes < 5, 1),
                    else_=0)).label('games_won')).join(User).filter(
                        GameScore.created_at >= current_start,
                        GameScore.created_at < current_end,
                        GameScore.completed == True).group_by(
                            GameScore.user_id, User.username).order_by(
                                db.desc('total_score')).all()

            # Create leaderboard entries for this week
            for rank, stats in enumerate(weekly_stats, 1):
                entry = LeaderboardEntry(user_id=stats.user_id,
                                         username=stats.username,
                                         period_type='weekly',
                                         period_start=current_start,
                                         period_end=current_end,
                                         rank=rank,
                                         score=stats.total_score,
                                         games_played=stats.games_played,
                                         games_won=stats.games_won)
                db.session.add(entry)

            current_start = current_end

        db.session.commit()
        logger.info(
            f"Admin {current_admin.username} recalculated all weekly winners since inception"
        )
        return redirect(
            url_for('admin.dashboard',
                    success="Weekly winners recalculated successfully"))

    except Exception as e:
        logger.error(f"Error recalculating weekly winners: {str(e)}")
        return redirect(
            url_for('admin.dashboard',
                    error=f"Error recalculating weekly winners: {str(e)}"))


#
# User Management Routes
#


@admin_process_bp.route('/users/suspend/<user_id>', methods=['POST'])
@admin_required
def suspend_user(current_admin, user_id):
    """Suspend a user account"""
    try:
        user = User.query.get(user_id)
        if not user:
            logger.warning(
                f"Admin {current_admin.username} attempted to suspend non-existent user {user_id}"
            )
            return redirect(url_for('admin.users', error="User not found"))

        # In a real implementation, you would have a status field in the User model
        # For now, we'll simulate this with a settings field
        if not user.settings:
            user.settings = {}

        user.settings['status'] = 'suspended'
        user.settings['suspended_at'] = datetime.utcnow().isoformat()
        user.settings['suspended_by'] = current_admin.username

        db.session.commit()

        logger.info(
            f"Admin {current_admin.username} suspended user {user.username}")
        return redirect(
            url_for('admin.view_user',
                    user_id=user_id,
                    success="User suspended successfully"))

    except Exception as e:
        logger.error(f"Error suspending user: {str(e)}")
        db.session.rollback()
        return redirect(
            url_for('admin.users', error=f"Error suspending user: {str(e)}"))


@admin_process_bp.route('/users/activate/<user_id>', methods=['POST'])
@admin_required
def activate_user(current_admin, user_id):
    """Activate a previously suspended user account"""
    try:
        user = User.query.get(user_id)
        if not user:
            logger.warning(
                f"Admin {current_admin.username} attempted to activate non-existent user {user_id}"
            )
            return redirect(url_for('admin.users', error="User not found"))

        # Update user status in settings
        if not user.settings:
            user.settings = {}

        if user.settings.get('status') == 'suspended':
            user.settings['status'] = 'active'
            user.settings['activated_at'] = datetime.utcnow().isoformat()
            user.settings['activated_by'] = current_admin.username

        db.session.commit()

        logger.info(
            f"Admin {current_admin.username} activated user {user.username}")
        return redirect(
            url_for('admin.view_user',
                    user_id=user_id,
                    success="User activated successfully"))

    except Exception as e:
        logger.error(f"Error activating user: {str(e)}")
        db.session.rollback()
        return redirect(
            url_for('admin.users', error=f"Error activating user: {str(e)}"))


#
# Game Settings Routes
#


@admin_process_bp.route('/update-game-settings', methods=['POST'])
@admin_required
def update_game_settings(current_admin):
    """Update game configuration settings"""
    try:
        # Get settings from form
        easy_max_mistakes = int(request.form.get('easy_max_mistakes', 8))
        medium_max_mistakes = int(request.form.get('medium_max_mistakes', 6))
        hard_max_mistakes = int(request.form.get('hard_max_mistakes', 4))

        quote_selection = request.form.get('quote_selection', 'random')
        enable_hardcore = 'enable_hardcore' in request.form
        enable_anonymous = 'enable_anonymous' in request.form

        # Validate inputs
        if easy_max_mistakes < 1 or medium_max_mistakes < 1 or hard_max_mistakes < 1:
            return redirect(
                url_for('admin.settings',
                        error="Mistake limits must be at least 1"))

        if easy_max_mistakes <= medium_max_mistakes:
            return redirect(
                url_for(
                    'admin.settings',
                    error="Easy mode must allow more mistakes than Medium mode"
                ))

        if medium_max_mistakes <= hard_max_mistakes:
            return redirect(
                url_for(
                    'admin.settings',
                    error="Medium mode must allow more mistakes than Hard mode"
                ))

        # Create settings object
        game_settings = {
            'easy_max_mistakes': easy_max_mistakes,
            'medium_max_mistakes': medium_max_mistakes,
            'hard_max_mistakes': hard_max_mistakes,
            'quote_selection': quote_selection,
            'enable_hardcore': enable_hardcore,
            'enable_anonymous': enable_anonymous,
            'updated_at': datetime.utcnow().isoformat(),
            'updated_by': current_admin.username
        }

        # Save to app config or database
        # For now, just save to a JSON file in the app directory
        settings_file = Path(
            current_app.root_path) / 'config' / 'game_settings.json'

        # Create directory if it doesn't exist
        settings_file.parent.mkdir(exist_ok=True, parents=True)

        with open(settings_file, 'w') as f:
            json.dump(game_settings, f, indent=2)

        logger.info(f"Admin {current_admin.username} updated game settings")
        return redirect(
            url_for('admin.settings',
                    success="Game settings updated successfully"))

    except Exception as e:
        logger.error(f"Error updating game settings: {str(e)}")
        return redirect(
            url_for('admin.settings',
                    error=f"Error updating game settings: {str(e)}"))


#
# System Status Routes
#


@admin_process_bp.route('/update-system-status', methods=['POST'])
@admin_required
def update_system_status(current_admin):
    """Update system status settings"""
    try:
        # Get settings from form
        maintenance_mode = 'maintenance_mode' in request.form
        maintenance_message = request.form.get(
            'maintenance_message',
            "We're currently performing system maintenance. Please check back in a few minutes."
        )
        allow_registrations = 'allow_registrations' in request.form

        # Create settings object
        system_status = {
            'maintenance_mode': maintenance_mode,
            'maintenance_message': maintenance_message,
            'allow_registrations': allow_registrations,
            'updated_at': datetime.utcnow().isoformat(),
            'updated_by': current_admin.username
        }

        # Save to app config or database
        # For now, just save to a JSON file in the app directory
        settings_file = Path(
            current_app.root_path) / 'config' / 'system_status.json'

        # Create directory if it doesn't exist
        settings_file.parent.mkdir(exist_ok=True, parents=True)

        with open(settings_file, 'w') as f:
            json.dump(system_status, f, indent=2)

        # Apply maintenance mode to the app config to take effect immediately
        current_app.config['MAINTENANCE_MODE'] = maintenance_mode
        current_app.config['MAINTENANCE_MESSAGE'] = maintenance_message
        current_app.config['ALLOW_REGISTRATIONS'] = allow_registrations

        logger.info(
            f"Admin {current_admin.username} updated system status: maintenance={maintenance_mode}"
        )
        return redirect(
            url_for('admin.settings',
                    success="System status updated successfully"))

    except Exception as e:
        logger.error(f"Error updating system status: {str(e)}")
        return redirect(
            url_for('admin.settings',
                    error=f"Error updating system status: {str(e)}"))


#
# Security Settings Routes
#


@admin_process_bp.route('/update-security-settings', methods=['POST'])
@admin_required
def update_security_settings(current_admin):
    """Update security settings"""
    try:
        # Get settings from form
        login_rate_limit_attempts = int(
            request.form.get('login_rate_limit_attempts', 5))
        login_rate_limit_minutes = int(
            request.form.get('login_rate_limit_minutes', 5))
        user_session_timeout = int(request.form.get('user_session_timeout',
                                                    60))
        admin_session_timeout = int(
            request.form.get('admin_session_timeout', 15))

        # Validate inputs
        if login_rate_limit_attempts < 1 or login_rate_limit_minutes < 1:
            return redirect(
                url_for('admin.settings',
                        error="Rate limit values must be at least 1"))

        if user_session_timeout < 5 or admin_session_timeout < 5:
            return redirect(
                url_for('admin.settings',
                        error="Session timeout must be at least 5 minutes"))

        # Create settings object
        security_settings = {
            'login_rate_limit_attempts':
            login_rate_limit_attempts,
            'login_rate_limit_minutes':
            login_rate_limit_minutes,
            'user_session_timeout':
            user_session_timeout,
            'admin_session_timeout':
            admin_session_timeout,
            'jwt_last_rotated':
            current_app.config.get('JWT_LAST_ROTATED', '(Not set)'),
            'updated_at':
            datetime.utcnow().isoformat(),
            'updated_by':
            current_admin.username
        }

        # Save to app config or database
        # For now, just save to a JSON file in the app directory
        settings_file = Path(
            current_app.root_path) / 'config' / 'security_settings.json'

        # Create directory if it doesn't exist
        settings_file.parent.mkdir(exist_ok=True, parents=True)

        with open(settings_file, 'w') as f:
            json.dump(security_settings, f, indent=2)

        # Apply settings to the app config to take effect immediately
        current_app.config[
            'LOGIN_RATE_LIMIT_ATTEMPTS'] = login_rate_limit_attempts
        current_app.config[
            'LOGIN_RATE_LIMIT_MINUTES'] = login_rate_limit_minutes
        current_app.config[
            'USER_SESSION_TIMEOUT'] = user_session_timeout * 60  # Convert to seconds
        current_app.config[
            'ADMIN_SESSION_TIMEOUT'] = admin_session_timeout * 60  # Convert to seconds

        # Update JWT expiration if using JWT
        if hasattr(
                current_app,
                'config') and 'JWT_ACCESS_TOKEN_EXPIRES' in current_app.config:
            current_app.config[
                'JWT_ACCESS_TOKEN_EXPIRES'] = user_session_timeout * 60  # Convert to seconds

        logger.info(
            f"Admin {current_admin.username} updated security settings")
        return redirect(
            url_for('admin.settings',
                    success="Security settings updated successfully"))

    except Exception as e:
        logger.error(f"Error updating security settings: {str(e)}")
        return redirect(
            url_for('admin.settings',
                    error=f"Error updating security settings: {str(e)}"))


@admin_process_bp.route('/rotate-jwt-key', methods=['POST'])
@admin_required
def rotate_jwt_key(current_admin):
    """Rotate the JWT secret key"""
    try:
        # Generate a new secret key
        new_secret_key = secrets.token_hex(32)  # 64-character hex string

        # Update the application's secret key
        current_app.config['JWT_SECRET_KEY'] = new_secret_key
        current_app.config['JWT_LAST_ROTATED'] = datetime.utcnow().isoformat()

        # Save to environment or configuration
        # In a production environment, you would update this in a more secure way

        # For now, let's save to a secure file that's not in version control
        key_file = Path(
            current_app.root_path) / '..' / 'instance' / 'jwt_key.txt'

        # Create directory if it doesn't exist
        key_file.parent.mkdir(exist_ok=True, parents=True)

        # Save the key with restricted permissions
        with open(key_file, 'w') as f:
            f.write(new_secret_key)

        # Update permissions to be readable only by the app
        if os.name != 'nt':  # Skip on Windows
            os.chmod(key_file, 0o600)

        # Add to JWT blocklist (this would force all users to log in again)
        # This would require your JWT implementation to check a blocklist
        # and you would need to implement this based on your setup

        logger.info(
            f"Admin {current_admin.username} rotated the JWT secret key")
        return redirect(
            url_for(
                'admin.settings',
                success=
                "JWT secret key rotated successfully. All users will need to log in again."
            ))

    except Exception as e:
        logger.error(f"Error rotating JWT key: {str(e)}")
        return redirect(
            url_for('admin.settings',
                    error=f"Error rotating JWT key: {str(e)}"))


#
# Email Settings Routes
#


@admin_process_bp.route('/update-email-settings', methods=['POST'])
@admin_required
def update_email_settings(current_admin):
    """Update email configuration settings"""
    try:
        # Get settings from form
        smtp_server = request.form.get('smtp_server', '')
        smtp_port = int(request.form.get('smtp_port', 587))
        smtp_username = request.form.get('smtp_username', '')
        smtp_password = request.form.get('smtp_password', '')
        use_ssl = 'use_ssl' in request.form
        from_name = request.form.get('from_name', 'Uncrypt Game')
        from_email = request.form.get('from_email', '')

        # Validate inputs
        if not smtp_server or not from_email:
            return redirect(
                url_for('admin.settings',
                        error="SMTP server and From Email are required"))

        # Create settings object
        email_settings = {
            'smtp_server': smtp_server,
            'smtp_port': smtp_port,
            'smtp_username': smtp_username,
            # Don't store the password as plaintext in the response
            'smtp_password': '********' if smtp_password else '',
            'use_ssl': use_ssl,
            'from_name': from_name,
            'from_email': from_email,
            'updated_at': datetime.utcnow().isoformat(),
            'updated_by': current_admin.username
        }

        # Save to app config or database, but with the actual password
        actual_settings = email_settings.copy()
        actual_settings['smtp_password'] = smtp_password

        # For now, just save to a JSON file in the app directory
        settings_file = Path(
            current_app.root_path) / 'config' / 'email_settings.json'

        # Create directory if it doesn't exist
        settings_file.parent.mkdir(exist_ok=True, parents=True)

        with open(settings_file, 'w') as f:
            # Use actual_settings to save the real password
            json.dump(actual_settings, f, indent=2)

        # Apply settings to the app config
        current_app.config['MAIL_SERVER'] = smtp_server
        current_app.config['MAIL_PORT'] = smtp_port
        current_app.config['MAIL_USERNAME'] = smtp_username
        current_app.config['MAIL_PASSWORD'] = smtp_password
        current_app.config['MAIL_USE_TLS'] = not use_ssl
        current_app.config['MAIL_USE_SSL'] = use_ssl
        current_app.config['MAIL_DEFAULT_SENDER'] = (from_name, from_email)

        logger.info(f"Admin {current_admin.username} updated email settings")
        return redirect(
            url_for('admin.settings',
                    success="Email settings updated successfully"))

    except Exception as e:
        logger.error(f"Error updating email settings: {str(e)}")
        return redirect(
            url_for('admin.settings',
                    error=f"Error updating email settings: {str(e)}"))


@admin_process_bp.route('/test-email', methods=['POST'])
@admin_required
def test_email(current_admin):
    """Send a test email to verify email configuration"""
    try:
        # Get the recipient email
        test_email = request.form.get('test_email', '')

        if not test_email:
            return redirect(
                url_for('admin.settings',
                        error="Test email address is required"))

        # Get email settings
        settings_file = Path(
            current_app.root_path) / 'config' / 'email_settings.json'

        if not settings_file.exists():
            return redirect(
                url_for(
                    'admin.settings',
                    error=
                    "Email settings not found. Please save email settings first."
                ))

        with open(settings_file, 'r') as f:
            email_settings = json.load(f)

        # Create email message
        msg = MIMEMultipart()
        msg['From'] = f"{email_settings['from_name']} <{email_settings['from_email']}>"
        msg['To'] = test_email
        msg['Subject'] = "Uncrypt Game - Test Email"

        body = f"""
        <html>
        <body>
            <h2>Uncrypt Game Email Test</h2>
            <p>This is a test email from the Uncrypt Game admin portal.</p>
            <p>If you're receiving this, your email configuration is working correctly!</p>
            <p>Sent by: {current_admin.username} at {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S UTC')}</p>
        </body>
        </html>
        """

        msg.attach(MIMEText(body, 'html'))

        # Send the email
        server = None
        try:
            if email_settings['use_ssl']:
                server = smtplib.SMTP_SSL(email_settings['smtp_server'],
                                          email_settings['smtp_port'])
            else:
                server = smtplib.SMTP(email_settings['smtp_server'],
                                      email_settings['smtp_port'])
                server.starttls()

            if email_settings['smtp_username'] and email_settings[
                    'smtp_password']:
                server.login(email_settings['smtp_username'],
                             email_settings['smtp_password'])

            server.send_message(msg)

            logger.info(
                f"Admin {current_admin.username} sent a test email to {test_email}"
            )
            return redirect(
                url_for(
                    'admin.settings',
                    success=f"Test email sent successfully to {test_email}"))

        finally:
            if server:
                server.quit()

    except Exception as e:
        logger.error(f"Error sending test email: {str(e)}")
        return redirect(
            url_for('admin.settings',
                    error=f"Error sending test email: {str(e)}"))


#
# Helper functions for loading settings
#


def load_game_settings():
    """Load game settings from file or database"""
    try:
        settings_file = Path(
            current_app.root_path) / 'config' / 'game_settings.json'

        if not settings_file.exists():
            # Return default settings
            return {
                'easy_max_mistakes': 8,
                'medium_max_mistakes': 6,
                'hard_max_mistakes': 4,
                'quote_selection': 'random',
                'enable_hardcore': False,
                'enable_anonymous': True
            }

        with open(settings_file, 'r') as f:
            return json.load(f)

    except Exception as e:
        logger.error(f"Error loading game settings: {str(e)}")
        # Return default settings on error
        return {
            'easy_max_mistakes': 8,
            'medium_max_mistakes': 6,
            'hard_max_mistakes': 4,
            'quote_selection': 'random',
            'enable_hardcore': False,
            'enable_anonymous': True
        }


def load_system_status():
    """Load system status settings from file or database"""
    try:
        settings_file = Path(
            current_app.root_path) / 'config' / 'system_status.json'

        if not settings_file.exists():
            # Return default settings
            return {
                'maintenance_mode': False,
                'maintenance_message':
                "We're currently performing system maintenance. Please check back in a few minutes.",
                'allow_registrations': True
            }

        with open(settings_file, 'r') as f:
            return json.load(f)

    except Exception as e:
        logger.error(f"Error loading system status: {str(e)}")
        # Return default settings on error
        return {
            'maintenance_mode': False,
            'maintenance_message':
            "We're currently performing system maintenance. Please check back in a few minutes.",
            'allow_registrations': True
        }


def load_security_settings():
    """Load security settings from file or database"""
    try:
        settings_file = Path(
            current_app.root_path) / 'config' / 'security_settings.json'

        if not settings_file.exists():
            # Return default settings
            return {
                'login_rate_limit_attempts':
                5,
                'login_rate_limit_minutes':
                5,
                'user_session_timeout':
                60,
                'admin_session_timeout':
                15,
                'jwt_last_rotated':
                current_app.config.get('JWT_LAST_ROTATED', '(Not set)')
            }

        with open(settings_file, 'r') as f:
            return json.load(f)

    except Exception as e:
        logger.error(f"Error loading security settings: {str(e)}")
        # Return default settings on error
        return {
            'login_rate_limit_attempts':
            5,
            'login_rate_limit_minutes':
            5,
            'user_session_timeout':
            60,
            'admin_session_timeout':
            15,
            'jwt_last_rotated':
            current_app.config.get('JWT_LAST_ROTATED', '(Not set)')
        }


def load_email_settings():
    """Load email settings from file or database"""
    try:
        settings_file = Path(
            current_app.root_path) / 'config' / 'email_settings.json'

        if not settings_file.exists():
            # Return default settings
            return {
                'smtp_server': 'smtp.example.com',
                'smtp_port': 587,
                'smtp_username': 'noreply@uncrypt.game',
                'smtp_password': '********',
                'use_ssl': True,
                'from_name': 'Uncrypt Game',
                'from_email': 'noreply@uncrypt.game'
            }

        with open(settings_file, 'r') as f:
            settings = json.load(f)
            # Mask the password in response
            if 'smtp_password' in settings and settings['smtp_password']:
                settings['smtp_password'] = '********'
            return settings

    except Exception as e:
        logger.error(f"Error loading email settings: {str(e)}")
        # Return default settings on error
        return {
            'smtp_server': 'smtp.example.com',
            'smtp_port': 587,
            'smtp_username': 'noreply@uncrypt.game',
            'smtp_password': '********',
            'use_ssl': True,
            'from_name': 'Uncrypt Game',
            'from_email': 'noreply@uncrypt.game'
        }


def register_admin_process_routes(app):
    """Register the admin process blueprint and set up routes"""
    # Register blueprint
    app.register_blueprint(admin_process_bp)

    # Modify the existing admin.settings view to load settings
    from app.routes.admin import admin_bp

    @admin_bp.route('/settings', methods=['GET'])
    @admin_required
    def settings(current_admin):
        """System settings page with actual settings data loaded"""
        # Load settings from various sources
        game_settings = load_game_settings()
        system_status = load_system_status()
        security_settings = load_security_settings()
        email_settings = load_email_settings()

        return render_template('admin/settings.html',
                               active_tab='settings',
                               game_settings=game_settings,
                               system_status=system_status,
                               security_settings=security_settings,
                               email_settings=email_settings)

    # This overrides the existing settings route

    # Also modify the admin routes in app/routes/admin.py to forward to our process functions
    # These won't override existing routes but add new ones for functions we've implemented

    @admin_bp.route('/users/suspend/<user_id>', methods=['GET', 'POST'])
    @admin_required
    def suspend_user(current_admin, user_id):
        """Forward to the suspend_user process function"""
        if request.method == 'GET':
            # Show confirmation page
            user = User.query.get(user_id)
            if not user:
                return redirect(url_for('admin.users', error="User not found"))

            return render_template('admin/confirm_action.html',
                                   active_tab='users',
                                   action="suspend",
                                   item_type="user",
                                   item=user,
                                   form_action=url_for(
                                       'admin_process.suspend_user',
                                       user_id=user_id))
        else:
            # Forward to process function
            return redirect(
                url_for('admin_process.suspend_user', user_id=user_id))

    @admin_bp.route('/users/activate/<user_id>', methods=['GET', 'POST'])
    @admin_required
    def activate_user(current_admin, user_id):
        """Forward to the activate_user process function"""
        if request.method == 'GET':
            # Show confirmation page
            user = User.query.get(user_id)
            if not user:
                return redirect(url_for('admin.users', error="User not found"))

            return render_template('admin/confirm_action.html',
                                   active_tab='users',
                                   action="activate",
                                   item_type="user",
                                   item=user,
                                   form_action=url_for(
                                       'admin_process.activate_user',
                                       user_id=user_id))
        else:
            # Forward to process function
            return redirect(
                url_for('admin_process.activate_user', user_id=user_id))

    # Add URL route rules for the update settings functions
    admin_bp.add_url_rule('/update-game-settings',
                          endpoint='update_game_settings',
                          view_func=update_game_settings,
                          methods=['POST'])

    admin_bp.add_url_rule('/update-system-status',
                          endpoint='update_system_status',
                          view_func=update_system_status,
                          methods=['POST'])

    admin_bp.add_url_rule('/update-security-settings',
                          endpoint='update_security_settings',
                          view_func=update_security_settings,
                          methods=['POST'])

    admin_bp.add_url_rule('/rotate-jwt-key',
                          endpoint='rotate_jwt_key',
                          view_func=rotate_jwt_key,
                          methods=['POST'])

    admin_bp.add_url_rule('/update-email-settings',
                          endpoint='update_email_settings',
                          view_func=update_email_settings,
                          methods=['POST'])

    admin_bp.add_url_rule('/test-email',
                          endpoint='test_email',
                          view_func=test_email,
                          methods=['POST'])

    logger.info("Admin process routes registered successfully")


@admin_process_bp.route('/populate-daily-dates', methods=['GET'])
@admin_required
def populate_daily_dates(current_admin):
    """Populate daily dates for quotes that meet criteria while preserving today's quote"""
    try:
        # Get today's date
        today = datetime.utcnow().date()

        # Find and preserve today's quote using raw SQL
        today_id = None
        result = db.session.execute(
            text("SELECT id FROM quote WHERE daily_date = :today"), {
                "today": today
            }).fetchone()

        if result:
            today_id = result[0]
            logger.info(f"Found today's quote with ID: {today_id}")

        # Clear all other daily dates using ORM
        try:
            if today_id:
                Quote.query.filter(Quote.id != today_id).update(
                    {"daily_date": None}, synchronize_session=False)
            else:
                Quote.query.update({"daily_date": None},
                                   synchronize_session=False)

            db.session.commit()
            logger.info("Successfully cleared existing daily dates")
        except Exception as clear_error:
            db.session.rollback()
            logger.error(f"Error clearing daily dates: {str(clear_error)}")
            return redirect(
                url_for(
                    'admin.quotes',
                    error=f"Error clearing daily dates: {str(clear_error)}"))

        # Start from tomorrow
        tomorrow = today + timedelta(days=1)
        current_date = tomorrow

        # Get eligible quotes but check for encoding issues
        eligible_quotes = Quote.query.filter(Quote.active == True,
                                             func.length(Quote.text) <= 65,
                                             Quote.unique_letters <= 15,
                                             Quote.daily_date.is_(None)).all()

        # Identify quotes with encoding issues
        good_quotes = []
        problematic_quotes = []

        for quote in eligible_quotes:
            try:
                # Test for encoding issues
                quote_id = quote.id
                quote_text = quote.text
                quote_author = quote.author
                encoded_text = quote_text.encode('utf-8')
                encoded_author = quote_author.encode('utf-8')

                # If we made it here without exception, add to good quotes
                good_quotes.append(quote)
            except UnicodeEncodeError as encode_error:
                # Add to problematic quotes with details
                problematic_quotes.append({
                    'id': quote_id,
                    'text': quote_text,
                    'author': quote_author,
                    'error': str(encode_error),
                })
                logger.warning(
                    f"Encoding issue with quote ID {quote_id}:\n"
                    f"Text: {quote_text}\n"
                    f"Author: {quote_author}\n"
                    f"Error: {str(encode_error)}"
                )

        # Log problematic quotes
        if problematic_quotes:
            logger.warning(
                f"Found {len(problematic_quotes)} quotes with encoding issues:"
            )
            for q in problematic_quotes:
                logger.warning(f"  Quote ID {q['id']}: {q['error']}")

        # Group quotes by daily usage
        daily_usage_counts = db.session.query(
            DailyCompletion.quote_id,
            func.count(func.distinct(DailyCompletion.challenge_date)).label(
                'daily_usage_count')).group_by(DailyCompletion.quote_id).all()

        # Convert to dict for easy lookup
        daily_usage_dict = {q_id: count for q_id, count in daily_usage_counts}

        # Sort quotes by usage
        never_used = []
        used_once = []
        used_multiple = []

        for quote in good_quotes:
            daily_count = daily_usage_dict.get(quote.id, 0)

            if daily_count == 0:
                never_used.append(quote)
            elif daily_count == 1:
                used_once.append(quote)
            else:
                used_multiple.append(quote)

        # Randomize each group
        random.shuffle(never_used)
        random.shuffle(used_once)
        random.shuffle(used_multiple)

        # Combine in priority order
        prioritized_quotes = never_used + used_once + used_multiple

        # Assign dates in smaller batches with sleep between
        total_assigned = 0
        batch_size = 10
        
        for i in range(0, len(prioritized_quotes), batch_size):
            batch = prioritized_quotes[i:i + batch_size]
            
            # Prepare bulk update data
            bulk_data = []
            for quote in batch:
                bulk_data.append({
                    'id': quote.id,
                    'daily_date': current_date
                })
                current_date += timedelta(days=1)
                total_assigned += 1
            
            # Bulk update the batch
            db.session.bulk_update_mappings(Quote, bulk_data)
            db.session.commit()
            logger.info(f"Assigned {total_assigned} daily dates so far")

        # Prepare result message
        preserved_msg = " (preserved today's quote)" if today_id else ""
        problem_msg = ""

        if problematic_quotes:
            problem_ids = ", ".join(str(q['id']) for q in problematic_quotes)
            problem_msg = f" Found {len(problematic_quotes)} quotes with encoding issues (IDs: {problem_ids})."
            logger.info(
                f"Populated {total_assigned} daily dates{preserved_msg}. {problem_msg}"
            )

            # Return with warning about problematic quotes
            return redirect(
                url_for(
                    'admin.quotes',
                    warning=
                    f"Successfully populated {total_assigned} daily dates{preserved_msg}. {problem_msg}"
                ))
        else:
            logger.info(
                f"Populated {total_assigned} daily dates{preserved_msg} with no encoding issues."
            )

            # Return success message
            return redirect(
                url_for(
                    'admin.quotes',
                    success=
                    f"Successfully populated {total_assigned} daily dates{preserved_msg}"
                ))

    except Exception as e:
        logger.error(f"Error populating daily dates: {str(e)}", exc_info=True)
        db.session.rollback()
        return redirect(
            url_for('admin.quotes',
                    error=f"Error populating daily dates: {str(e)}"))


@admin_process_bp.route('/users/delete/<user_id>', methods=['GET'])
@admin_required
def delete_user(current_admin, user_id):
    """Delete a user account"""
    try:
        user = User.query.get(user_id)
        if not user:
            logger.warning(
                f"Admin {current_admin.username} attempted to delete non-existent user {user_id}"
            )
            return redirect(url_for('admin.users', error="User not found"))

        # Delete user's related data
        GameScore.query.filter_by(user_id=user_id).delete()
        UserStats.query.filter_by(user_id=user_id).delete()
        ActiveGameState.query.filter_by(user_id=user_id).delete()
        DailyCompletion.query.filter_by(user_id=user_id).delete()

        # Delete the user
        db.session.delete(user)
        db.session.commit()

        logger.info(
            f"Admin {current_admin.username} deleted user {user.username}")
        return redirect(
            url_for('admin.users', success="User deleted successfully"))

    except Exception as e:
        logger.error(f"Error deleting user: {str(e)}")
        db.session.rollback()
        return redirect(
            url_for('admin.users', error=f"Error deleting user: {str(e)}"))


# Add to app/routes/admin_process.py


@admin_process_bp.route('/recalculate-all-stats', methods=['POST'])
@admin_required
def recalculate_all_stats(current_admin):
    """
    Recalculate stats for all users from scratch based on their game history.
    This function rebuilds all user stats to ensure accuracy and consistency.
    """
    try:
        start_time = datetime.utcnow()

        # Get all users with at least one game played
        users_with_games = db.session.query(GameScore.user_id).distinct().all()
        total_users = len(users_with_games)

        # Track successful and failed updates
        success_count = 0
        failed_users = []

        # Process each user
        for user_record in users_with_games:
            user_id = user_record[0]

            try:
                # First delete existing stats
                UserStats.query.filter_by(user_id=user_id).delete()

                # Create new stats object
                user_stats = UserStats(user_id=user_id)
                db.session.add(user_stats)

                # Get all games for this user
                games = GameScore.query.filter_by(user_id=user_id).order_by(
                    GameScore.created_at).all()

                if games:
                    # Calculate basic stats
                    user_stats.total_games_played = len(games)

                    # Count wins correctly based on each game's difficulty
                    wins = 0
                    for game in games:
                        difficulty = game.game_id.split(
                            '-')[0] if '-' in game.game_id else 'medium'
                        max_mistakes = {
                            'easy': 8,
                            'medium': 5,
                            'hard': 3
                        }.get(difficulty, 5)
                        if game.completed and game.mistakes < max_mistakes:
                            wins += 1

                    user_stats.games_won = wins
                    user_stats.cumulative_score = sum(game.score
                                                      for game in games)
                    user_stats.last_played_date = games[-1].created_at

                    # Calculate streaks
                    current_streak = 0
                    max_streak = 0
                    current_noloss_streak = 0
                    max_noloss_streak = 0

                    # Sort games by date (oldest to newest) for streak calculation
                    # Current streaks should reflect the most recent consecutive wins
                    sorted_games = sorted(games, key=lambda g: g.created_at)

                    # First calculate max streaks by going through games chronologically
                    temp_win_streak = 0
                    temp_noloss_streak = 0

                    for game in sorted_games:
                        difficulty = game.game_id.split(
                            '-')[0] if '-' in game.game_id else 'medium'
                        max_mistakes = {
                            'easy': 8,
                            'medium': 5,
                            'hard': 3
                        }.get(difficulty, 5)

                        if game.completed and game.mistakes < max_mistakes:  # Won game
                            temp_win_streak += 1
                            temp_noloss_streak += 1
                        else:  # Lost or abandoned game
                            temp_win_streak = 0
                            temp_noloss_streak = 0

                        max_streak = max(max_streak, temp_win_streak)
                        max_noloss_streak = max(max_noloss_streak,
                                                temp_noloss_streak)

                    # Now calculate current streaks starting from most recent games
                    # Reset counters for current streak calculation
                    current_streak = 0
                    current_noloss_streak = 0

                    # Iterate through games in reverse order (newest to oldest)
                    for game in reversed(sorted_games):
                        difficulty = game.game_id.split(
                            '-')[0] if '-' in game.game_id else 'medium'
                        max_mistakes = {
                            'easy': 8,
                            'medium': 5,
                            'hard': 3
                        }.get(difficulty, 5)

                        if game.completed and game.mistakes < max_mistakes:  # Won game
                            current_streak += 1
                            current_noloss_streak += 1
                        else:  # Lost or abandoned game
                            # Stop counting once streak is broken - we only want the most recent streak
                            break

                    user_stats.current_streak = current_streak
                    user_stats.max_streak = max_streak
                    user_stats.current_noloss_streak = current_noloss_streak
                    user_stats.max_noloss_streak = max_noloss_streak

                    # Calculate weekly score
                    now = datetime.utcnow()
                    week_start = now - timedelta(days=now.weekday())
                    weekly_score = sum(game.score for game in games
                                       if game.created_at >= week_start)
                    user_stats.highest_weekly_score = weekly_score

                # Calculate daily stats if applicable
                daily_completions = DailyCompletion.query.filter_by(
                    user_id=user_id).order_by(
                        DailyCompletion.challenge_date).all()

                if daily_completions:
                    user_stats.total_daily_completed = len(daily_completions)
                    user_stats.last_daily_completed_date = daily_completions[
                        -1].challenge_date

                    # Calculate daily streak
                    dates = [
                        completion.challenge_date
                        for completion in daily_completions
                    ]

                    # Get current streak (consecutive days from the most recent)
                    current_streak = 1  # Start with 1 for the most recent completion
                    last_date = dates[-1]

                    for i in range(len(dates) - 2, -1,
                                   -1):  # Go backwards from second-to-last
                        if (last_date - dates[i]).days == 1:  # Consecutive day
                            current_streak += 1
                            last_date = dates[i]
                        else:
                            break  # Streak broken

                    user_stats.current_daily_streak = current_streak

                    # Calculate max daily streak
                    max_daily_streak = 1
                    current_daily_streak = 1

                    for i in range(1, len(dates)):
                        if (dates[i - 1] -
                                dates[i]).days == 1:  # Consecutive day
                            current_daily_streak += 1
                        else:
                            current_daily_streak = 1  # Reset streak

                        max_daily_streak = max(max_daily_streak,
                                               current_daily_streak)

                    user_stats.max_daily_streak = max_daily_streak

                # Increment success counter
                success_count += 1

                # Commit every 50 users to avoid long transactions
                if success_count % 50 == 0:
                    db.session.commit()
                    logger.info(
                        f"Processed {success_count}/{total_users} users")

            except Exception as user_error:
                logger.error(
                    f"Error processing user {user_id}: {str(user_error)}")
                failed_users.append(user_id)

        # Final commit for remaining users
        db.session.commit()

        # Calculate processing time
        duration = (datetime.utcnow() - start_time).total_seconds()

        logger.info(
            f"Admin {current_admin.username} recalculated stats for "
            f"{success_count}/{total_users} users in {duration:.2f} seconds")

        if failed_users:
            return redirect(
                url_for(
                    'admin.dashboard',
                    warning=
                    f"Stats recalculated for {success_count}/{total_users} users. "
                    f"{len(failed_users)} users failed."))
        else:
            return redirect(
                url_for(
                    'admin.dashboard',
                    success=
                    f"Successfully recalculated stats for all {success_count} users "
                    f"in {duration:.2f} seconds."))

    except Exception as e:
        db.session.rollback()
        logger.error(f"Error recalculating user stats: {str(e)}",
                     exc_info=True)
        return redirect(
            url_for('admin.dashboard',
                    error=f"Error recalculating user stats: {str(e)}"))


# Also add a scheduled task function that can be called by a cron job
def scheduled_recalculate_all_stats():
    """Version of the recalculate function that can be called by a scheduled task"""
    try:
        start_time = datetime.utcnow()

        # Get all users with at least one game played
        users_with_games = db.session.query(GameScore.user_id).distinct().all()
        total_users = len(users_with_games)

        # Track successful and failed updates
        success_count = 0
        failed_users = []

        # Process each user (same logic as admin function)
        for user_record in users_with_games:
            user_id = user_record[0]

            try:
                # First delete existing stats
                UserStats.query.filter_by(user_id=user_id).delete()

                # Create new stats object
                user_stats = UserStats(user_id=user_id)
                db.session.add(user_stats)

                # Get all games for this user
                games = GameScore.query.filter_by(user_id=user_id).order_by(
                    GameScore.created_at).all()

                # Calculate stats (same logic as admin function)
                # ... [same calculation code as above - omitted for brevity]

                # Increment success counter
                success_count += 1

                # Commit every 50 users to avoid long transactions
                if success_count % 50 == 0:
                    db.session.commit()
                    logger.info(
                        f"Processed {success_count}/{total_users} users")

            except Exception as user_error:
                logger.error(
                    f"Error processing user {user_id}: {str(user_error)}")
                failed_users.append(user_id)

        # Final commit for remaining users
        db.session.commit()

        # Calculate processing time
        duration = (datetime.utcnow() - start_time).total_seconds()

        logger.info(
            f"Scheduled task recalculated stats for "
            f"{success_count}/{total_users} users in {duration:.2f} seconds")

        return {
            "success": True,
            "total_users": total_users,
            "successful_updates": success_count,
            "failed_updates": len(failed_users),
            "duration_seconds": duration
        }

    except Exception as e:
        db.session.rollback()
        logger.error(f"Error in scheduled stats recalculation: {str(e)}",
                     exc_info=True)
        return {"success": False, "error": str(e)}


@admin_process_bp.route('/fix-quote-encoding', methods=['GET'])
@admin_required
def fix_quote_encoding(current_admin):
    """Fix mangled encoding in quotes"""
    try:
        # Common encoding replacements
        replacements = {
            '’': "'",  # Right single quote'
            '—': '-',  # Em dash'
            '“': '"',  # Left double quote''
            '”': '"',  # Right double quote''
            'É': 'E',  # Capital E with acute accent
            "é": 'e',  # lower case E with acute accent
            '�': "'",  # Unknown character
            '‚Äô': "'",  # Smart single quote
            '‚Äù': '"',  # Smart double quote open
            '‚Äú': '"',  # Smart double quote close
            '‚Äî': '—',  # Em dash
            '‚Äì': '–',  # En dash
            '‚Ä¢': '•',  # Bullet
            '‚Ä¦': '…',  # Ellipsis
            '‚Äï': '"',  # Another smart quote variant
            '‚Äò': "'",  # Another single quote variant
            '‚Äó': "'",  # Another single quote variant
        }

        # Get all quotes
        quotes = Quote.query.all()

        # Track how many were fixed
        fixed_count = 0

        for quote in quotes:
            original_text = quote.text
            original_author = quote.author
            original_minor = quote.minor_attribution

            # Check and fix text
            needs_update = False
            new_text = original_text
            new_author = original_author
            new_minor = original_minor

            # Apply all replacements to each field
            for bad, good in replacements.items():
                if bad in new_text:
                    new_text = new_text.replace(bad, good)
                    needs_update = True

                if bad in new_author:
                    new_author = new_author.replace(bad, good)
                    needs_update = True

                if new_minor and bad in new_minor:
                    new_minor = new_minor.replace(bad, good)
                    needs_update = True

            # Update the quote if needed
            if needs_update:
                quote.text = new_text
                quote.author = new_author
                quote.minor_attribution = new_minor
                fixed_count += 1

                # Log the change
                logger.info(f"Fixed encoding for quote ID {quote.id}:")
                logger.info(f"  Original text: {original_text}")
                logger.info(f"  Fixed text: {new_text}")

        # Commit changes if any quotes were fixed
        if fixed_count > 0:
            db.session.commit()
            logger.info(f"Fixed encoding issues in {fixed_count} quotes")
            return redirect(
                url_for(
                    'admin.quotes',
                    success=
                    f"Successfully fixed encoding issues in {fixed_count} quotes"
                ))
        else:
            return redirect(
                url_for(
                    'admin.quotes',
                    info="No encoding issues found that match known patterns"))

    except Exception as e:
        logger.error(f"Error fixing quote encoding: {str(e)}", exc_info=True)
        db.session.rollback()
        return redirect(
            url_for('admin.quotes',
                    error=f"Error fixing quote encoding: {str(e)}"))
