from datetime import datetime
from flask_sqlalchemy import SQLAlchemy
from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash
import uuid

db = SQLAlchemy()


class User(UserMixin, db.Model):
    user_id = db.Column(db.String,
                        primary_key=True,
                        default=lambda: str(uuid.uuid4()))
    email = db.Column(db.String, unique=True, nullable=False)
    username = db.Column(db.String, unique=True, nullable=False)
    password_hash = db.Column(db.String(256), nullable=False)
    auth_type = db.Column(db.String, default='local')
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    settings = db.Column(db.JSON, default=dict)
    # Add this new column:
    email_consent = db.Column(db.Boolean,
                              default=False)  # GDPR email marketing consent
    consent_date = db.Column(db.DateTime)  # When consent was given
    is_admin = db.Column(db.Boolean, default=False)
    admin_password_hash = db.Column(db.String(256), nullable=True)

    def __init__(self, email, username, password, email_consent=False):
        self.email = email
        self.username = username
        self.set_password(password)
        self.email_consent = email_consent
        if email_consent:
            self.consent_date = datetime.utcnow()

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

    def get_id(self):
        return str(self.user_id)

    def set_admin_password(self, password):
        self.admin_password_hash = generate_password_hash(password)


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
    user_id = db.Column(db.String,
                        db.ForeignKey('user.user_id'),
                        primary_key=True)
    game_id = db.Column(db.String, unique=True)
    original_paragraph = db.Column(db.Text)
    encrypted_paragraph = db.Column(db.Text)
    mapping = db.Column(db.JSON)
    reverse_mapping = db.Column(db.JSON)
    correctly_guessed = db.Column(db.JSON, default=lambda: [])
    mistakes = db.Column(db.Integer, default=0)
    major_attribution = db.Column(db.String)
    minor_attribution = db.Column(db.String)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    last_updated = db.Column(db.DateTime,
                             default=datetime.utcnow,
                             onupdate=datetime.utcnow)


class AnonymousGameState(db.Model):
    anon_id = db.Column(db.String,
                        primary_key=True)  # Will be game_id + suffix
    game_id = db.Column(db.String, unique=True)
    original_paragraph = db.Column(db.Text)
    encrypted_paragraph = db.Column(db.Text)
    mapping = db.Column(db.JSON)
    reverse_mapping = db.Column(db.JSON)
    correctly_guessed = db.Column(db.JSON, default=lambda: [])
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
