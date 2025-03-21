# app/models/backup.py
from app.models import db
from datetime import datetime


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
