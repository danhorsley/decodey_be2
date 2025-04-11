import os


class Config:
    SECRET_KEY = os.environ.get('SECRET_KEY', 'dev-secret-key')
    JWT_SECRET_KEY = os.environ.get('JWT_SECRET_KEY', 'jwt-secret-key')
    JWT_ACCESS_TOKEN_EXPIRES = 3600  # 1 hour
    JWT_REFRESH_TOKEN_EXPIRES = 2592000  # 30 days
    FLASK_ENV = os.environ.get('FLASK_ENV', 'development')
    
    if FLASK_ENV == 'development':
        DATABASE_URL = os.environ.get('DEV_DATABASE_URL', os.environ.get('DATABASE_URL'))
    else:
        DATABASE_URL = os.environ.get('PROD_DATABASE_URL', os.environ.get('DATABASE_URL'))
    
    MAILGUN_API_KEY = os.environ.get('MAILGUN_API_KEY')
    MAILGUN_DOMAIN = os.environ.get('MAILGUN_DOMAIN')
    if not DATABASE_URL:
        raise ValueError("DATABASE_URL environment variable is not set")
