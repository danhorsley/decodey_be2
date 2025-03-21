# app/admin_setup.py
"""Setup function for configuring the admin portal within Flask app"""

from flask import current_app
from flask.cli import with_appcontext
import click
from app.models import db
from app.routes.admin import admin_bp
from app.models import BackupRecord, BackupSettings

# Update to app/admin_setup.py


def init_admin(app):
    """Initialize admin module in the app"""
    # Register CLI commands
    app.cli.add_command(create_admin_command)

    # Ensure backup directory exists
    from pathlib import Path
    backup_dir = Path(app.root_path) / 'backups'
    backup_dir.mkdir(exist_ok=True, parents=True)

    # Make sure the admin templates are accessible
    app.jinja_env.add_extension('jinja2.ext.loopcontrols')

    # Add admin-specific context processors if needed
    @app.context_processor
    def inject_admin_context():
        return {'app_name': 'Uncrypt Admin Portal', 'version': '1.0.0'}

    app.logger.info("Admin portal initialized successfully")


@click.command('create-admin')
@click.argument('username')
@click.option('--password',
              prompt=True,
              hide_input=True,
              confirmation_prompt=True)
@click.option('--admin-password',
              prompt=True,
              hide_input=True,
              confirmation_prompt=True)
@with_appcontext
def create_admin_command(username, password, admin_password):
    """Create an admin user."""
    from app.models import User

    user = User.query.filter_by(username=username).first()

    if not user:
        # Create new user with admin privileges
        user = User(username=username, 
                   email=f"{username}@example.com",
                   password=password)
        user.is_admin = True
        user.set_admin_password(admin_password)
        db.session.add(user)
    else:
        # Update existing user
        user.is_admin = True
        user.set_admin_password(admin_password)
        user.set_password(password)

    db.session.commit()
    click.echo(f"Admin user {username} created successfully.")


def init_celery_with_app(app, celery):
    """Initialize Celery with Flask context"""

    class ContextTask(celery.Task):

        def __call__(self, *args, **kwargs):
            with app.app_context():
                return self.run(*args, **kwargs)

    celery.Task = ContextTask

    # Optional: Configure Celery from app config
    celery.conf.update(broker_url=app.config.get('CELERY_BROKER_URL',
                                                 'redis://localhost:6379/0'),
                       result_backend=app.config.get(
                           'CELERY_RESULT_BACKEND',
                           'redis://localhost:6379/0'))


def configure_celery_tasks(app):
    """Configure Celery tasks based on app settings"""
    try:
        from app.celery_worker import celery, setup_periodic_tasks
        from celery.schedules import crontab

        # Get backup settings from database
        with app.app_context():
            settings = BackupSettings.get_settings()

            # Parse daily backup time
            daily_hour, daily_minute = map(
                int, settings.daily_backup_time.split(':'))

            # Parse weekly backup time
            weekly_hour, weekly_minute = map(
                int, settings.weekly_backup_time.split(':'))

            # Configure tasks based on settings
            if settings.daily_backup_enabled:
                celery.conf.beat_schedule['daily-backup'] = {
                    'task': 'app.celery_worker.backup_database',
                    'schedule': crontab(hour=daily_hour, minute=daily_minute),
                    'kwargs': {
                        'backup_type': 'daily'
                    }
                }

            if settings.weekly_backup_enabled:
                celery.conf.beat_schedule['weekly-backup'] = {
                    'task':
                    'app.celery_worker.backup_database',
                    'schedule':
                    crontab(hour=weekly_hour,
                            minute=weekly_minute,
                            day_of_week=settings.weekly_backup_day),
                    'kwargs': {
                        'backup_type': 'weekly'
                    }
                }

            # Configure cleanup task
            celery.conf.beat_schedule['cleanup-backups'] = {
                'task': 'app.celery_worker.cleanup_old_backups',
                'schedule': crontab(hour=4, minute=0),  # Run at 4:00 AM
                'kwargs': {
                    'daily_retention_days': settings.daily_retention_days,
                    'weekly_retention_days': settings.weekly_retention_days
                }
            }

            app.logger.info("Celery tasks configured successfully")

    except Exception as e:
        app.logger.error(f"Error configuring Celery tasks: {str(e)}")
