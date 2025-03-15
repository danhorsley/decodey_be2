from flask import Blueprint, request, jsonify, redirect, url_for
from flask_jwt_extended import (create_access_token, create_refresh_token,
                                get_jwt_identity, jwt_required, get_jwt)
from werkzeug.security import generate_password_hash, check_password_hash
from app import jwt_blocklist
from app.models import db, User, ActiveGameState
import logging


bp = Blueprint('auth', __name__)


@bp.route('/register', methods=['POST'])
def register():
    try:
        data = request.get_json()
        username = data.get('username')
        password = data.get('password')
        email = data.get('email')
        email_consent = data.get('emailConsent',
                                 False)  # Get consent value with default

        if not username or not password or not email:
            return jsonify(
                {"msg": "Username, email and password are required"}), 400

        # Check if user already exists
        if User.query.filter_by(username=username).first():
            return jsonify({"msg": "Username already exists"}), 409
        if User.query.filter_by(email=email).first():
            return jsonify({"msg": "Email already exists"}), 409

        # Create new user with SQLAlchemy model
        user = User(username=username,
                    email=email,
                    password=password,
                    email_consent=email_consent)

        db.session.add(user)
        db.session.commit()

        logging.info(
            f"Created new user: {username}, email consent: {email_consent}")
        return jsonify({
            "msg": "User created successfully",
            "email_consent": email_consent
        }), 201

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
        user = User.query.filter((User.username == identifier)
                                 | (User.email == identifier)).first()

        if not user or not user.check_password(password):
            return jsonify({"msg": "Invalid credentials"}), 401

        access_token = create_access_token(identity=user.get_id(),
                                           fresh=True,
                                           additional_claims={
                                               "username": user.username,
                                               "email": user.email
                                           })
        refresh_token = create_refresh_token(
            identity=user.get_id()) if remember else None
        # After successful authentication, check for active game
        has_active_game = False
        active_game = ActiveGameState.query.filter_by(user_id=user.get_id()).first()
        if active_game:
            has_active_game = True
        logging.info(f"Successful login for user: {user.username}")
        return jsonify({
            "access_token": access_token,
            "refresh_token": refresh_token,
            "username": user.username,
            "has_active_game": has_active_game
        }), 200

    except Exception as e:
        logging.error(f"Error in login: {str(e)}")
        return jsonify({"msg": "Error during login"}), 500


@bp.route('/logout', methods=['POST'])
@jwt_required()  # Remove optional=True for consistency
def logout():
    token = get_jwt()
    jti = token["jti"]
    jwt_blocklist.add(jti)
    return jsonify({"msg": "Successfully logged out"}), 200


@bp.route('/refresh', methods=['POST'])
@jwt_required(refresh=True)
def refresh():
    """Refresh access token using refresh token"""
    current_user = get_jwt_identity()
    user = User.query.get(current_user)

    if not user:
        return jsonify({"msg": "User not found"}), 404

    new_access_token = create_access_token(identity=user.get_id(),
                                           fresh=False,
                                           additional_claims={
                                               "username": user.username,
                                               "email": user.email
                                           })

    return jsonify({"access_token": new_access_token}), 200


@bp.route('/verify_token', methods=['GET'])
@jwt_required()
def verify_token():
    """Endpoint to verify if a token is valid"""
    current_user = get_jwt_identity()
    claims = get_jwt()
    return jsonify({
        "valid": True,
        "user_id": current_user,
        "username": claims.get("username")
    }), 200


@bp.route('/update_email_consent', methods=['POST'])
@jwt_required()
def update_email_consent():
    user_id = get_jwt_identity()
    data = request.get_json()
    consent = data.get('consent', False)

    try:
        user = User.query.get(user_id)
        if not user:
            return jsonify({"msg": "User not found"}), 404

        user.email_consent = consent
        if consent:
            user.consent_date = datetime.utcnow()
        else:
            user.consent_date = None

        db.session.commit()

        return jsonify({
            "msg": "Email consent updated successfully",
            "email_consent": user.email_consent
        }), 200

    except Exception as e:
        logging.error(f"Error updating email consent: {str(e)}")
        db.session.rollback()
        return jsonify({"msg": "Error updating email consent"}), 500
