# app/celery_worker.py
from celery import Celery
from celery.schedules import crontab
from sqlalchemy import case, func
from flask import Flask
import os
import subprocess
import logging
from pathlib import Path
from urllib.parse import urlparse
from datetime import datetime, timedelta
from app.models import db
import shutil
from app.models import (
    db, User, GameScore, AnonymousGameScore, ActiveGameState, 
    AnonymousGameState, DailyCompletion, UserStats
)
from datetime import datetime, timedelta
from app.utils.stats import initialize_or_update_user_stats

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def make_celery(app=None):
    """Create a Celery instance with Flask app context"""
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    # Configure Redis as message broker with production fallback
    redis_url = os.environ.get('REDIS_URL', 'redis://0.0.0.0:6379/0')

    # Additional production settings
    broker_use_ssl = os.environ.get('FLASK_ENV') == 'production'

    celery = Celery('app',
                    broker=redis_url,
                    backend=redis_url,
                    broker_use_ssl=broker_use_ssl,
                    include=['app.celery_worker'])

    # Production-specific configurations
    if os.environ.get('FLASK_ENV') == 'production':
        celery.conf.update(
            broker_pool_limit=None,  # Remove broker pool limit
            worker_max_tasks_per_child=1000,  # Restart workers after 1000 tasks
            worker_prefetch_multiplier=1,  # Don't prefetch more tasks than workers
            task_time_limit=1800,  # 30 minute hard time limit
            task_soft_time_limit=1200,  # 20 minute soft time limit
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
        broker_connection_retry_on_startup=True)

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
    sender.add_periodic_task(crontab(hour=2, minute=0),
                             backup_database.s(backup_type='daily'),
                             name='daily-backup')

    # Weekly backup on Sunday at 3:00 AM UTC
    sender.add_periodic_task(crontab(hour=3, minute=0, day_of_week=0),
                             backup_database.s(backup_type='weekly'),
                             name='weekly-backup')

    # Cleanup old backups daily at 4:00 AM UTC
    sender.add_periodic_task(crontab(hour=4, minute=0),
                             cleanup_old_backups.s(),
                             name='cleanup-backups')


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
                    raise Exception(
                        f"PostgreSQL backup failed: {result.stderr}")

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
        retry_in = 60 * (2**self.request.retries)  # 60s, 120s, 240s
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
                        file_date = datetime.strptime(timestamp_str,
                                                      "%Y%m%d_%H%M%S")
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
                    logger.error(
                        f"Error processing backup file {backup_file}: {str(file_err)}"
                    )

            logger.info(
                f"Backup cleanup completed: {deleted_count} files deleted")
            return {"status": "success", "deleted_count": deleted_count}

    except Exception as e:
        logger.error(f"Backup cleanup failed: {str(e)}")
        return {"status": "error", "message": str(e)}

@celery.task
def process_game_completion(user_id, anon_id, game_id, is_daily, won, score, mistakes, time_taken):
    from app import create_app
    app = create_app()

    with app.app_context():
        try:
            logger.info(f"Starting game completion processing for {'user '+user_id if user_id else 'anonymous '+anon_id}")

            if user_id:  # Authenticated user
                logger.info(f"Processing authenticated game completion: user_id={user_id}, game_id={game_id}")

                # 1. Record GameScore
                logger.info(f"Creating GameScore record: score={score}, mistakes={mistakes}")
                game_score = GameScore(
                    user_id=user_id,
                    game_id=game_id,
                    score=score,
                    mistakes=mistakes,
                    time_taken=time_taken,
                    game_type='daily' if is_daily else 'regular',
                    challenge_date=datetime.utcnow().strftime('%Y-%m-%d'),
                    completed=True,
                    created_at=datetime.utcnow()
                )
                db.session.add(game_score)
                logger.info(f"Added GameScore to session")

                # 2. Record daily completion if applicable
                if is_daily:
                    logger.info(f"Processing daily challenge completion")
                    try:
                        # Import the function locally to avoid circular imports
                        from app.routes.game import extract_challenge_date, get_quote_id_for_date

                        challenge_date = extract_challenge_date(game_id, is_daily)
                        logger.info(f"Extracted challenge date: {challenge_date}")

                        quote_id = get_quote_id_for_date(challenge_date)
                        logger.info(f"Retrieved quote_id: {quote_id}")

                        if quote_id:
                            daily_completion = DailyCompletion(
                                user_id=user_id,
                                quote_id=quote_id,
                                challenge_date=challenge_date,
                                completed_at=datetime.utcnow(),
                                score=score,
                                mistakes=mistakes,
                                time_taken=time_taken
                            )
                            db.session.add(daily_completion)
                            logger.info(f"Added DailyCompletion to session")
                        else:
                            logger.warning(f"No quote found for date {challenge_date}, skipping DailyCompletion")
                    except Exception as daily_err:
                        logger.error(f"Error processing daily completion: {str(daily_err)}", exc_info=True)
                        # Continue processing even if daily completion fails

                # 3. Delete active game state
                logger.info(f"Looking for active game state to delete")
                active_game = ActiveGameState.query.filter_by(user_id=user_id, game_id=game_id).first()
                if active_game:
                    logger.info(f"Deleting active game state for user {user_id}")
                    db.session.delete(active_game)
                else:
                    logger.warning(f"No active game state found for user {user_id}, game {game_id}")

                # Commit these changes
                logger.info(f"Committing database changes")
                db.session.commit()
                logger.info(f"Database changes committed successfully")

                # 4. Update user stats (including daily streak)
                logger.info(f"Updating user stats")
                initialize_or_update_user_stats(user_id, game_score)
                logger.info(f"User stats updated successfully")

                return True

            except Exception as e:
                logger.error(f"Error processing game completion: {str(e)}", exc_info=True)
                db.session.rollback()
                return False

            else:  # Anonymous user
                logger.info(f"Processing anonymous game completion: anon_id={anon_id}, game_id={game_id}")

                # Record anonymous game
                anon_game_score = AnonymousGameScore(
                    anon_id=anon_id,
                    game_id=game_id,
                    score=score,
                    mistakes=mistakes,
                    time_taken=time_taken,
                    game_type='daily' if is_daily else 'regular',
                    difficulty=game_id.split('-')[0] if '-' in game_id else 'medium',
                    completed=True,
                    won=won,
                    created_at=datetime.utcnow()
                )
                db.session.add(anon_game_score)
                logger.info(f"Added AnonymousGameScore to session")

                # Clean up anonymous game state
                logger.info(f"Looking for anonymous game state to delete")
                anon_game = AnonymousGameState.query.filter_by(anon_id=anon_id).first()
                if anon_game:
                    logger.info(f"Deleting anonymous game state for {anon_id}")
                    db.session.delete(anon_game)
                else:
                    logger.warning(f"No anonymous game state found for {anon_id}")

                logger.info(f"Committing database changes")
                db.session.commit()
                logger.info(f"Database changes committed successfully")

                return True

        except Exception as e:
            logger.error(f"Error processing game completion: {str(e)}", exc_info=True)
            db.session.rollback()
            return False

@celery.task
def verify_daily_streak(user_id):
    """Verify and correct daily streak if needed"""
    from app import create_app
    app = create_app()

    with app.app_context():
        try:
            from app.models import UserStats, DailyCompletion

            user_stats = UserStats.query.filter_by(user_id=user_id).first()
            if not user_stats:
                return

            # Get all completions in chronological order
            completions = DailyCompletion.query.filter_by(user_id=user_id)\
                                             .order_by(DailyCompletion.challenge_date)\
                                             .all()

            if not completions:
                # No completions, streak should be 0
                if user_stats.current_daily_streak != 0:
                    user_stats.current_daily_streak = 0
                    db.session.commit()
                return

            # Get today and yesterday
            today = datetime.utcnow().date()
            yesterday = today - timedelta(days=1)

            # Get most recent completion
            latest = completions[-1].challenge_date

            # Calculate correct streak
            if latest < yesterday:
                # Streak broken - they missed yesterday
                if user_stats.current_daily_streak != 0:
                    user_stats.current_daily_streak = 0
                    db.session.commit()
            else:
                # Verify streak by counting consecutive days backward
                dates = [c.challenge_date for c in completions]
                current_streak = 1  # Start with most recent

                # Start from the most recent and work backwards
                for i in range(len(dates) - 1, 0, -1):
                    if (dates[i] - dates[i-1]).days == 1:
                        current_streak += 1
                    else:
                        break

                # Update if different
                if user_stats.current_daily_streak != current_streak:
                    user_stats.current_daily_streak = current_streak
                    if current_streak > user_stats.max_daily_streak:
                        user_stats.max_daily_streak = current_streak
                    db.session.commit()

        except Exception as e:
            logger.error(f"Error verifying daily streak: {str(e)}", exc_info=True)
            db.session.rollback()