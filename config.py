import os


class Config:
    SECRET_KEY = os.environ.get('SECRET_KEY', 'dev-secret-key')
    JWT_SECRET_KEY = os.environ.get('JWT_SECRET_KEY', 'jwt-secret-key')
    JWT_ACCESS_TOKEN_EXPIRES = 3600  # 1 hour
    JWT_REFRESH_TOKEN_EXPIRES = 2592000  # 30 days
    DATABASE_URL = os.environ.get('DATABASE_URL')
    # FLASK_ENV = os.environ.get('FLASK_ENV', 'production')
    FLASK_ENV = os.environ.get('FLASK_ENV', 'development')
    MAILGUN_API_KEY = os.environ.get('MAILGUN_API_KEY')
    MAILGUN_DOMAIN = os.environ.get('MAILGUN_DOMAIN')
    if not DATABASE_URL:
        raise ValueError("DATABASE_URL environment variable is not set")
