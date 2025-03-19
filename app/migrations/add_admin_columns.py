
from flask import Flask
from app import create_app
from app.models import db, User
from sqlalchemy import Column, Boolean, String

def upgrade():
    # Add new columns
    with create_app().app_context():
        db.session.execute('ALTER TABLE "user" ADD COLUMN IF NOT EXISTS is_admin BOOLEAN DEFAULT FALSE')
        db.session.execute('ALTER TABLE "user" ADD COLUMN IF NOT EXISTS admin_password_hash VARCHAR(256)')
        db.session.commit()

if __name__ == '__main__':
    upgrade()
