from datetime import datetime
from flask_sqlalchemy import SQLAlchemy
from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash
import json

db = SQLAlchemy()

class User(UserMixin, db.Model):
    user_id = db.Column(db.String, primary_key=True)
    email = db.Column(db.String, unique=True)
    username = db.Column(db.String, unique=True)
    password_hash = db.Column(db.String)
    auth_type = db.Column(db.String)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    settings = db.Column(db.JSON)

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

class UserStats(db.Model):
    user_id = db.Column(db.String, db.ForeignKey('user.user_id'), primary_key=True)
    current_streak = db.Column(db.Integer, default=0)
    max_streak = db.Column(db.Integer, default=0)
    current_noloss_streak = db.Column(db.Integer, default=0)
    max_noloss_streak = db.Column(db.Integer, default=0)
    total_games_played = db.Column(db.Integer, default=0)
    cumulative_score = db.Column(db.Integer, default=0)
    highest_weekly_score = db.Column(db.Integer, default=0)
    last_played_date = db.Column(db.DateTime)

class GameScore(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.String, db.ForeignKey('user.user_id'))
    game_id = db.Column(db.String, unique=True)
    score = db.Column(db.Integer)
    mistakes = db.Column(db.Integer)
    time_taken = db.Column(db.Integer)
    difficulty = db.Column(db.String)
    game_type = db.Column(db.String, default='regular')
    challenge_date = db.Column(db.String)
    completed = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

class ActiveGameState(db.Model):
    user_id = db.Column(db.String, db.ForeignKey('user.user_id'), primary_key=True)
    game_id = db.Column(db.String, unique=True)
    original_paragraph = db.Column(db.Text)
    encrypted_paragraph = db.Column(db.Text)
    mapping = db.Column(db.JSON)
    reverse_mapping = db.Column(db.JSON)
    correctly_guessed = db.Column(db.JSON)
    mistakes = db.Column(db.Integer, default=0)
    major_attribution = db.Column(db.String)
    minor_attribution = db.Column(db.String)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    last_updated = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)