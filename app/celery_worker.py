# app/celery_worker.py
from celery import Celery
from flask import Flask
import os
import subprocess
import logging
from pathlib import Path
from urllib.parse import urlparse
from datetime import datetime, timedelta
import shutil

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def make_celery(app=None):
    """Create a Celery instance with Flask app context"""
    # Configure Redis as message broker
    # For production, use a real Redis server
    redis_url = os.environ.get('REDIS_URL', 'redis://localhost:6379/0')

    celery = Celery(
        'app',
        broker=redis_url,
        backend=redis_url,
        include=['app.celery_worker']
    )

    # Configure Celery
    celery.conf.update(
        task_serializer='json',
        accept_content=['json'],
        result_serializer='json',
        timezone='UTC',
        enable_utc=True,
        task_always_eager=False,  # Set to True for development/debugging
        worker_hijack_root_logger=False,
        broker_connection_retry_on_startup=True
    )

    if app:
        class ContextTask(celery.Task):
            def __call__(self, *args, **kwargs):
                with app.app_context():
                    return self.run(*args, **kwargs)

        celery.Task = ContextTask

    return celery

# Create Celery instance
celery = make_celery()

# Set up scheduled tasks
@celery.on_after_configure.connect
def setup_periodic_tasks(sender, **kwargs):
    """Set up scheduled backup tasks"""
    # Daily backup at 2:00 AM UTC
    sender.add_periodic_task(
        crontab(hour=2, minute=0),
        backup_database.s(backup_type='daily'),
        name='daily-backup'
    )

    # Weekly backup on Sunday at 3:00 AM UTC
    sender.add_periodic_task(
        crontab(hour=3, minute=0, day_of_week=0),
        backup_database.s(backup_type='weekly'),
        name='weekly-backup'
    )

    # Cleanup old backups daily at 4:00 AM UTC
    sender.add_periodic_task(
        crontab(hour=4, minute=0),
        cleanup_old_backups.s(),
        name='cleanup-backups'
    )

@celery.task(bind=True, max_retries=3)
def backup_database(self, backup_type='manual'):
    """Task to create a database backup"""
    try:
        # Import Flask app - this is needed to get the app config
        from app import create_app
        app = create_app()

        with app.app_context():
            # Create timestamp for filename
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            backup_dir = Path(app.root_path) / 'backups'

            # Create backup directory if it doesn't exist
            if not backup_dir.exists():
                backup_dir.mkdir(parents=True)

            backup_file = backup_dir / f"backup_{backup_type}_{timestamp}.sql"

            # Get database URL from app config
            db_url = app.config.get('SQLALCHEMY_DATABASE_URI')

            if 'sqlite' in db_url:
                # SQLite backup command
                db_path = db_url.replace('sqlite:///', '')
                result = subprocess.run(
                    f"sqlite3 {db_path} .dump > {backup_file}",
                    shell=True,
                    capture_output=True,
                    text=True
                )

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
                env["PGPASSWORD"] = password

                # Create pg_dump command
                cmd = [
                    "pg_dump", 
                    "-h", host, 
                    "-p", str(port), 
                    "-U", user, 
                    "-F", "c",  # Custom format
                    "-b",  # Include blobs
                    "-v",  # Verbose
                    "-f", str(backup_file),
                    dbname
                ]

                result = subprocess.run(
                    cmd,
                    env=env,
                    capture_output=True,
                    text=True
                )

                if result.returncode != 0:
                    raise Exception(f"PostgreSQL backup failed: {result.stderr}")

            # Create a record in the database (optional)
            # You could add a BackupRecord model to track backups

            logger.info(f"Backup created successfully: {backup_file.name}")
            return {
                "status": "success",
                "file": backup_file.name,
                "size": os.path.getsize(backup_file),
                "timestamp": timestamp
            }

    except Exception as e:
        logger.error(f"Backup failed: {str(e)}")
        # Retry the task with exponential backoff
        # This is useful for temporary network issues with PostgreSQL
        retry_in = 60 * (2 ** self.request.retries)  # 60s, 120s, 240s
        raise self.retry(exc=e, countdown=retry_in)

@celery.task
def cleanup_old_backups():
    """Task to delete old backups based on retention policy"""
    try:
        # Import Flask app
        from app import create_app
        app = create_app()

        with app.app_context():
            # Get retention settings from database or config
            # Here we use hardcoded values as examples
            daily_retention_days = 14
            weekly_retention_days = 90

            backup_dir = Path(app.root_path) / 'backups'
            if not backup_dir.exists():
                return

            now = datetime.now()
            daily_cutoff = now - timedelta(days=daily_retention_days)
            weekly_cutoff = now - timedelta(days=weekly_retention_days)
            deleted_count = 0

            # Process all backup files
            for backup_file in backup_dir.glob('backup_*.sql'):
                try:
                    # Extract backup type and timestamp from filename
                    # Expected format: backup_TYPE_YYYYMMDD_HHMMSS.sql
                    name_parts = backup_file.stem.split('_')
                    if len(name_parts) < 3:
                        continue

                    backup_type = name_parts[1]
                    timestamp_str = "_".join(name_parts[2:])

                    try:
                        file_date = datetime.strptime(timestamp_str, "%Y%m%d_%H%M%S")
                    except ValueError:
                        # Skip files with invalid timestamp format
                        continue

                    # Apply retention policy based on backup type
                    delete_file = False
                    if backup_type == 'daily' and file_date < daily_cutoff:
                        delete_file = True
                    elif backup_type == 'weekly' and file_date < weekly_cutoff:
                        delete_file = True

                    if delete_file:
                        backup_file.unlink()
                        deleted_count += 1
                        logger.info(f"Deleted old backup: {backup_file.name}")

                except Exception as file_err:
                    logger.error(f"Error processing backup file {backup_file}: {str(file_err)}")

            logger.info(f"Backup cleanup completed: {deleted_count} files deleted")
            return {
                "status": "success",
                "deleted_count": deleted_count
            }

    except Exception as e:
        logger.error(f"Backup cleanup failed: {str(e)}")
        return {
            "status": "error",
            "message": str(e)
        }