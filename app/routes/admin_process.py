# app/routes/admin_process.py
"""
Implementation of various admin processing functions for the admin portal.
This file contains the route handlers for form submissions from the admin interface.
"""

from flask import Blueprint, request, jsonify, redirect, url_for, render_template, flash, current_app, session
from werkzeug.security import generate_password_hash, check_password_hash
from app.models import db, User, GameScore, UserStats, ActiveGameState, BackupSettings
import logging
import os
import secrets
import json
from datetime import datetime, timedelta
from pathlib import Path
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from sqlalchemy import func

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
    """Manually recalculate weekly winners"""
    try:
        from app.tasks.leaderboard import reset_weekly_leaderboard
        reset_weekly_leaderboard()
        
        logger.info(f"Admin {current_admin.username} manually recalculated weekly winners")
        return redirect(url_for('admin.dashboard', success="Weekly winners recalculated successfully"))
        
    except Exception as e:
        logger.error(f"Error recalculating weekly winners: {str(e)}")
        return redirect(url_for('admin.dashboard', error=f"Error recalculating weekly winners: {str(e)}"))

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
    """Populate daily dates for appropriate quotes"""
    try:
        from datetime import datetime, timedelta
        from app.models import Quote

        # Clear existing daily dates in batches
        batch_size = 100
        while True:
            quotes_to_clear = Quote.query.filter(Quote.daily_date.isnot(None)).limit(batch_size).all()
            if not quotes_to_clear:
                break
            for quote in quotes_to_clear:
                quote.daily_date = None
            db.session.commit()

        # Get quotes that meet criteria (<=65 chars and <=18 unique letters)
        from sqlalchemy import and_
        length_filter = and_(func.length(Quote.text) <= 65, Quote.unique_letters <= 18)
        
        eligible_quotes = Quote.query.filter_by(active=True)\
                                   .filter(length_filter)\
                                   .all()

        # Get tomorrow's date as starting point
        tomorrow = datetime.utcnow().date() + timedelta(days=1)

        # Process quotes in batches
        total_processed = 0
        for i in range(0, len(eligible_quotes), batch_size):
            batch = eligible_quotes[i:i + batch_size]
            for j, quote in enumerate(batch):
                quote.daily_date = tomorrow + timedelta(days=i + j)
            db.session.commit()
            total_processed += len(batch)

        logger.info(f"Admin {current_admin.username} populated {total_processed} daily dates")
        return redirect(url_for('admin.quotes', success=f"Successfully populated {total_processed} daily dates"))

    except Exception as e:
        logger.error(f"Error populating daily dates: {str(e)}", exc_info=True)
        db.session.rollback()
        return redirect(url_for('admin.quotes', error=f"Error populating daily dates: {str(e)}"))
@admin_process_bp.route('/users/delete/<user_id>', methods=['GET'])
@admin_required
def delete_user(current_admin, user_id):
    """Delete a user account"""
    try:
        user = User.query.get(user_id)
        if not user:
            logger.warning(f"Admin {current_admin.username} attempted to delete non-existent user {user_id}")
            return redirect(url_for('admin.users', error="User not found"))

        # Delete user's related data
        GameScore.query.filter_by(user_id=user_id).delete()
        UserStats.query.filter_by(user_id=user_id).delete()
        ActiveGameState.query.filter_by(user_id=user_id).delete()
        DailyCompletion.query.filter_by(user_id=user_id).delete()

        # Delete the user
        db.session.delete(user)
        db.session.commit()

        logger.info(f"Admin {current_admin.username} deleted user {user.username}")
        return redirect(url_for('admin.users', success="User deleted successfully"))

    except Exception as e:
        logger.error(f"Error deleting user: {str(e)}")
        db.session.rollback()
        return redirect(url_for('admin.users', error=f"Error deleting user: {str(e)}"))