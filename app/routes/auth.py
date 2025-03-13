from flask import Blueprint, request, jsonify, redirect, url_for
from flask_jwt_extended import (
    create_access_token, create_refresh_token,
    get_jwt_identity, jwt_required, get_jwt
)
from werkzeug.security import generate_password_hash, check_password_hash
from app import jwt_blocklist
from app.models import db, User
import logging

bp = Blueprint('auth', __name__)

@bp.route('/register', methods=['POST'])
def register():
    try:
        data = request.get_json()
        username = data.get('username')
        password = data.get('password')
        email = data.get('email')

        if not username or not password or not email:
            return jsonify({"msg": "Username, email and password are required"}), 400

        # Check if user already exists
        if User.query.filter_by(username=username).first():
            return jsonify({"msg": "Username already exists"}), 409
        if User.query.filter_by(email=email).first():
            return jsonify({"msg": "Email already exists"}), 409

        # Create new user with SQLAlchemy model
        user = User(username=username, email=email, password=password)

        db.session.add(user)
        db.session.commit()

        logging.info(f"Created new user: {username}")
        return jsonify({"msg": "User created successfully"}), 201

    except Exception as e:
        logging.error(f"Error in registration: {str(e)}")
        db.session.rollback()
        return jsonify({"msg": "Error creating user"}), 500

@bp.route('/login', methods=['POST'])
def login():
    try:
        data = request.get_json()
        identifier = data.get('username')  # Can be username or email
        password = data.get('password')
        remember = data.get('remember', False)

        # Try to find user by username or email
        user = User.query.filter(
            (User.username == identifier) | (User.email == identifier)
        ).first()

        if not user or not user.check_password(password):
            return jsonify({"msg": "Invalid credentials"}), 401

        access_token = create_access_token(
            identity=user.get_id(),
            fresh=True,
            additional_claims={"username": user.username}
        )
        refresh_token = create_refresh_token(identity=user.get_id()) if remember else None

        logging.info(f"Successful login for user: {user.username}")
        return jsonify({
            "access_token": access_token,
            "refresh_token": refresh_token,
            "username": user.username
        }), 200

    except Exception as e:
        logging.error(f"Error in login: {str(e)}")
        return jsonify({"msg": "Error during login"}), 500

@bp.route('/logout')
@jwt_required(optional=True)
def logout():
    token = get_jwt()
    if token:
        jti = token["jti"]
        jwt_blocklist.add(jti)
    return redirect(url_for('main.index'))