from datetime import datetime
from flask_sqlalchemy import SQLAlchemy
from flask_login import UserMixin
from sqlalchemy.ext.hybrid import hybrid_property
from sqlalchemy.dialects import postgresql
from werkzeug.security import generate_password_hash, check_password_hash
import uuid

db = SQLAlchemy()


class User(UserMixin, db.Model):
    user_id = db.Column(db.String,
                        primary_key=True,
                        default=lambda: str(uuid.uuid4()))
    email = db.Column(db.String, unique=True, nullable=False)
    apple_user_id = db.Column(db.String, unique=True,
                              nullable=True)  #added for apple auth
    username = db.Column(db.String, unique=True, nullable=False)
    password_hash = db.Column(db.String(256), nullable=False)
    auth_type = db.Column(db.String, default='local')
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    settings = db.Column(db.JSON, default=dict)
    # Add this new column:
    email_consent = db.Column(db.Boolean,
                              default=False)  # GDPR email marketing consent
    consent_date = db.Column(db.DateTime)  # When consent was given
    xp_boost_multiplier = db.Column(db.Float, default=1.0)
    xp_boost_expires = db.Column(db.DateTime, nullable=True)
    is_admin = db.Column(db.Boolean, default=False)
    subadmin = db.Column(db.Boolean, default=False)
    admin_password_hash = db.Column(db.String(256), nullable=True)
    reset_token = db.Column(db.String(100), unique=True, nullable=True)
    reset_token_expires = db.Column(db.DateTime, nullable=True)
    unsubscribe_token = db.Column(db.String(100), unique=True, nullable=True)

    def __init__(self, email, username, password, email_consent=False):
        self.email = email
        self.username = username
        self.set_password(password)
        self.email_consent = email_consent
        self.reset_token = None
        self.reset_token_expires = None
        if email_consent:
            self.consent_date = datetime.utcnow()

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

    def get_id(self):
        return str(self.user_id)

    def set_admin_password(self, password):
        """Set a separate admin password hash for admin users"""
        self.admin_password_hash = generate_password_hash(password)

    def generate_unsubscribe_token(self):
        """Generate a unique unsubscribe token for the user"""
        self.unsubscribe_token = secrets.token_urlsafe(32)
        db.session.commit()
        return self.unsubscribe_token


class UserStats(db.Model):
    user_id = db.Column(db.String,
                        db.ForeignKey('user.user_id'),
                        primary_key=True)
    current_streak = db.Column(db.Integer, default=0)
    max_streak = db.Column(db.Integer, default=0)
    current_noloss_streak = db.Column(db.Integer, default=0)
    max_noloss_streak = db.Column(db.Integer, default=0)
    total_games_played = db.Column(db.Integer, default=0)
    games_won = db.Column(db.Integer, default=0)  # Added games_won column
    cumulative_score = db.Column(db.Integer, default=0)
    highest_weekly_score = db.Column(db.Integer, default=0)
    last_played_date = db.Column(db.DateTime)
    current_daily_streak = db.Column(db.Integer, default=0)
    max_daily_streak = db.Column(db.Integer, default=0)
    total_daily_completed = db.Column(db.Integer, default=0)
    last_daily_completed_date = db.Column(db.Date, nullable=True)
    current_daily_streak = db.Column(db.Integer, default=0)
    max_daily_streak = db.Column(db.Integer, default=0)
    total_daily_completed = db.Column(db.Integer, default=0)
    last_daily_completed_date = db.Column(db.Date, nullable=True)


class GameScore(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.String, db.ForeignKey('user.user_id'))
    game_id = db.Column(db.String, unique=True)
    score = db.Column(db.Integer)
    mistakes = db.Column(db.Integer)
    time_taken = db.Column(db.Integer)  # Time in seconds
    game_type = db.Column(db.String, default='regular')
    challenge_date = db.Column(db.String)
    completed = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class ActiveGameState(db.Model):
    id = db.Column(db.Integer,
                   db.Sequence('active_game_state_id_seq'),
                   primary_key=True)
    user_id = db.Column(db.String,
                        db.ForeignKey('user.user_id'),
                        nullable=False)
    game_id = db.Column(db.String, unique=True)
    original_paragraph = db.Column(db.Text)
    encrypted_paragraph = db.Column(db.Text)
    mapping = db.Column(db.JSON)
    reverse_mapping = db.Column(db.JSON)
    correctly_guessed = db.Column(db.JSON, default=lambda: [])
    incorrect_guesses = db.Column(db.JSON, default=lambda: {})
    mistakes = db.Column(db.Integer, default=0)
    major_attribution = db.Column(db.String)
    minor_attribution = db.Column(db.String)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    last_updated = db.Column(db.DateTime,
                             default=datetime.utcnow,
                             onupdate=datetime.utcnow)
    __table_args__ = (db.Index('idx_active_game_userid', 'user_id'), )


class AnonymousGameState(db.Model):
    anon_id = db.Column(db.String,
                        primary_key=True)  # Will be game_id + suffix
    game_id = db.Column(db.String, unique=True)
    original_paragraph = db.Column(db.Text)
    encrypted_paragraph = db.Column(db.Text)
    mapping = db.Column(db.JSON)
    reverse_mapping = db.Column(db.JSON)
    correctly_guessed = db.Column(db.JSON, default=lambda: [])
    incorrect_guesses = db.Column(db.JSON, default=lambda: {})
    mistakes = db.Column(db.Integer, default=0)
    major_attribution = db.Column(db.String)
    minor_attribution = db.Column(db.String)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    last_updated = db.Column(db.DateTime,
                             default=datetime.utcnow,
                             onupdate=datetime.utcnow)
    completed = db.Column(db.Boolean, default=False)
    won = db.Column(db.Boolean, default=False)
    conversion_status = db.Column(db.String, default="anonymous")


class BackupRecord(db.Model):
    """Model to track database backups"""
    id = db.Column(db.Integer, primary_key=True)
    filename = db.Column(db.String, unique=True, nullable=False)
    backup_type = db.Column(db.String,
                            default='manual')  # 'manual', 'daily', 'weekly'
    size_bytes = db.Column(db.Integer, default=0)
    status = db.Column(db.String, default='success')  # 'success', 'failed'
    error_message = db.Column(db.Text, nullable=True)
    created_by = db.Column(db.String,
                           db.ForeignKey('user.user_id'),
                           nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def __init__(self,
                 filename,
                 backup_type='manual',
                 size_bytes=0,
                 status='success',
                 error_message=None,
                 created_by=None):
        self.filename = filename
        self.backup_type = backup_type
        self.size_bytes = size_bytes
        self.status = status
        self.error_message = error_message
        self.created_by = created_by

    def get_size_display(self):
        """Return a human-readable file size"""
        size = self.size_bytes
        for unit in ["B", "KB", "MB", "GB", "TB"]:
            if size < 1024 or unit == "TB":
                return f"{size:.2f} {unit}"
            size /= 1024


class BackupSettings(db.Model):
    """Model to store backup configuration settings"""
    id = db.Column(db.Integer, primary_key=True)
    daily_backup_enabled = db.Column(db.Boolean, default=True)
    daily_backup_time = db.Column(db.String, default="02:00")  # HH:MM format
    weekly_backup_enabled = db.Column(db.Boolean, default=True)
    weekly_backup_day = db.Column(db.Integer, default=0)  # 0=Monday, 6=Sunday
    weekly_backup_time = db.Column(db.String, default="03:00")  # HH:MM format
    daily_retention_days = db.Column(db.Integer, default=14)
    weekly_retention_days = db.Column(db.Integer, default=90)
    backup_location = db.Column(db.String,
                                default="default")  # 'default', 's3', etc.
    s3_bucket = db.Column(db.String, nullable=True)
    s3_prefix = db.Column(db.String, nullable=True)
    aws_access_key = db.Column(db.String, nullable=True)
    aws_secret_key = db.Column(db.String, nullable=True)
    updated_by = db.Column(db.String,
                           db.ForeignKey('user.user_id'),
                           nullable=True)
    updated_at = db.Column(db.DateTime,
                           default=datetime.utcnow,
                           onupdate=datetime.utcnow)

    @classmethod
    def get_settings(cls):
        """Get the backup settings or create default if not exists"""
        settings = cls.query.first()
        if not settings:
            settings = cls()
            db.session.add(settings)
            db.session.commit()
        return settings


from sqlalchemy import event


class Quote(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    text = db.Column(db.Text, nullable=False)
    author = db.Column(db.String(255), nullable=False)
    minor_attribution = db.Column(db.String(255))
    difficulty = db.Column(db.Float, default=0.0)
    daily_date = db.Column(db.Date().with_variant(postgresql.DATE(),
                                                  'postgresql'),
                           unique=True,
                           nullable=True)
    times_used = db.Column(db.Integer, default=0)
    unique_letters = db.Column(db.Integer)
    active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime,
                           default=datetime.utcnow,
                           onupdate=datetime.utcnow)

    @staticmethod
    def _count_unique_letters(text):
        return len(set(char.upper() for char in text if char.isalpha()))

    def _update_unique_letters(self):
        self.unique_letters = self._count_unique_letters(self.text)


@event.listens_for(Quote, 'before_insert')
@event.listens_for(Quote, 'before_update')
def set_unique_letters(mapper, connection, target):
    target._update_unique_letters()


class Backdoor(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    text = db.Column(db.Text, nullable=False)
    author = db.Column(db.String(255), nullable=False)
    minor_attribution = db.Column(db.String(255))
    difficulty = db.Column(db.Float, default=0.0)
    daily_date = db.Column(db.Date().with_variant(postgresql.DATE(),
                                                  'postgresql'),
                           unique=True,
                           nullable=True)
    times_used = db.Column(db.Integer, default=0)
    unique_letters = db.Column(db.Integer)
    active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime,
                           default=datetime.utcnow,
                           onupdate=datetime.utcnow)

    @staticmethod
    def _count_unique_letters(text):
        return len(set(char.upper() for char in text if char.isalpha()))

    def _update_unique_letters(self):
        self.unique_letters = self._count_unique_letters(self.text)


@event.listens_for(Backdoor, 'before_insert')
@event.listens_for(Backdoor, 'before_update')
def set_backdoor_unique_letters(mapper, connection, target):
    target._update_unique_letters()


class DailyCompletion(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.String,
                        db.ForeignKey('user.user_id'),
                        nullable=False)
    quote_id = db.Column(db.Integer, db.ForeignKey('quote.id'), nullable=False)
    challenge_date = db.Column(db.Date, nullable=False)
    completed_at = db.Column(db.DateTime, default=datetime.utcnow)
    score = db.Column(db.Integer, default=0)
    mistakes = db.Column(db.Integer, default=0)
    time_taken = db.Column(db.Integer, default=0)  # Time in seconds

    # Define a unique constraint to ensure one completion per user per day
    __table_args__ = (db.UniqueConstraint(
        'user_id', 'challenge_date',
        name='user_daily_completion_constraint'), )

    # Relationships
    user = db.relationship('User',
                           backref=db.backref('daily_completions', lazy=True))
    quote = db.relationship('Quote',
                            backref=db.backref('completions', lazy=True))


class LeaderboardEntry(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.String,
                        db.ForeignKey('user.user_id'),
                        nullable=False)
    username = db.Column(db.String)  # Denormalized for historical accuracy
    period_type = db.Column(db.String, nullable=False)  # 'weekly' or 'yearly'
    period_start = db.Column(db.DateTime, nullable=False)
    period_end = db.Column(db.DateTime, nullable=False)
    rank = db.Column(db.Integer, nullable=False)
    score = db.Column(db.Integer, default=0)
    games_played = db.Column(db.Integer, default=0)
    games_won = db.Column(db.Integer, default=0)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    # Define unique constraint
    __table_args__ = (db.UniqueConstraint('user_id',
                                          'period_type',
                                          'period_start',
                                          name='unique_user_period'), )


class AnonymousGameScore(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    anon_id = db.Column(db.String)  # Identifier for anonymous user
    game_id = db.Column(db.String)
    score = db.Column(db.Integer, default=0)
    mistakes = db.Column(db.Integer, default=0)
    time_taken = db.Column(db.Integer)  # Time in seconds
    game_type = db.Column(db.String, default='regular')
    difficulty = db.Column(db.String, default='medium')
    completed = db.Column(db.Boolean, default=True)
    won = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class Promo(db.Model):
    """General promo codes table"""
    __tablename__ = 'promos'

    code = db.Column(db.String(20), primary_key=True)
    type = db.Column(db.String(50), nullable=False)  # 'xp_boost', 'coins', etc
    value = db.Column(db.Float,
                      nullable=False)  # 2.0 for 2x boost, 500 for coins
    duration_hours = db.Column(db.Integer,
                               default=24)  # For time-based rewards
    max_uses = db.Column(db.Integer, default=None)  # None = unlimited
    current_uses = db.Column(db.Integer, default=0)
    expires_at = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    active = db.Column(db.Boolean, default=True)
    description = db.Column(db.String(200))


class PromoRedemption(db.Model):
    """Track who redeemed what"""
    __tablename__ = 'promo_redemptions'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.String,
                        db.ForeignKey('user.user_id'),
                        nullable=False)
    code = db.Column(db.String(20),
                     nullable=False)  # Not FK since could be unsubscribe token
    type = db.Column(db.String(50), nullable=False)
    redeemed_at = db.Column(db.DateTime, default=datetime.utcnow)
    expires_at = db.Column(db.DateTime, nullable=True)  # For XP boosts
    value = db.Column(db.Float)

    user = db.relationship('User', backref='promo_redemptions')
