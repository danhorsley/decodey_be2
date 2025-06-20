from flask import Blueprint, request, jsonify, redirect, url_for, current_app, render_template
from flask_jwt_extended import (create_access_token, create_refresh_token,
                                get_jwt_identity, jwt_required, get_jwt)
import requests
import secrets
from datetime import datetime, timedelta
from werkzeug.security import generate_password_hash, check_password_hash
from app import jwt_blocklist
from app.models import db, User, ActiveGameState, UserStats, GameScore, DailyCompletion
import logging

bp = Blueprint('auth', __name__)


@bp.route('/signup', methods=['POST'])
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
        if '@' in identifier:  # If identifier is an email, convert to lowercase
            identifier = identifier.lower()
        password = data.get('password')
        remember = data.get('rememberMe',
                            False)  # Changed from 'remember' to 'rememberMe'
        logging.info(
            f"Login request for user {identifier}, rememberMe: {remember}")
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
        active_game = ActiveGameState.query.filter_by(
            user_id=user.get_id()).first()
        if active_game:
            has_active_game = True
        logging.info(f"Successful login for user: {user.username}")
        return jsonify({
            "access_token": access_token,
            "refresh_token": refresh_token if remember else None,
            "username": user.username,
            "has_active_game": has_active_game,
            "user_id": user.user_id,
            "subadmin": user.subadmin  # Add this line to include the user ID
        }), 200

    except Exception as e:
        logging.error(f"Error in login: {str(e)}")
        return jsonify({"msg": "Error during login"}), 500


@bp.route('/logout', methods=['POST'])
@jwt_required()
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
    my_user = User.query.filter_by(user_id=current_user).first()
    claims = get_jwt()
    return jsonify({
        "valid": True,
        "user_id": current_user,
        "username": claims.get("username"),
        "subadmin": my_user.subadmin
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


@bp.route('/check-username', methods=['POST'])
def check_username():
    """Check if a username is available for registration"""
    try:
        data = request.get_json()
        username = data.get('username')

        if not username:
            return jsonify({
                "available": False,
                "message": "Username is required"
            }), 400

        # Check minimum length
        if len(username) < 3:
            return jsonify({
                "available": False,
                "message": "Username must be at least 3 characters"
            }), 400

        # Check if username contains invalid characters
        if not username.isalnum() and not any(c in username for c in '_-'):
            return jsonify({
                "available":
                False,
                "message":
                "Username can only contain letters, numbers, underscores and hyphens"
            }), 400

        # Check if username already exists
        existing_user = User.query.filter(User.username == username).first()

        if existing_user:
            return jsonify({
                "available": False,
                "message": "Username already taken"
            }), 200

        return jsonify({
            "available": True,
            "message": "Username available!"
        }), 200

    except Exception as e:
        logging.error(f"Error checking username: {str(e)}")
        return jsonify({
            "available": False,
            "message": "Error checking username"
        }), 500


# Add to app/auth.py


@bp.route('/api/user-data', methods=['GET'])
@jwt_required()
def get_user_data():
    try:
        # Get the current user's ID
        user_id = get_jwt_identity()

        if not user_id:
            return jsonify({"msg": "User not authenticated"}), 401

        # Find the user
        user = User.query.get(user_id)

        if not user:
            return jsonify({"msg": "User not found"}), 404

        # Get user data (excluding password hash)
        user_data = {
            "user_id":
            user.user_id,
            "username":
            user.username,
            "email":
            user.email,
            "created_at":
            user.created_at.isoformat() if user.created_at else None,
            "email_consent":
            user.email_consent,
            "consent_date":
            user.consent_date.isoformat() if user.consent_date else None
        }

        # Get user stats
        user_stats = UserStats.query.filter_by(user_id=user_id).first()
        stats_data = {}

        if user_stats:
            stats_data = {
                "current_streak":
                user_stats.current_streak,
                "max_streak":
                user_stats.max_streak,
                "current_noloss_streak":
                user_stats.current_noloss_streak,
                "max_noloss_streak":
                user_stats.max_noloss_streak,
                "total_games_played":
                user_stats.total_games_played,
                "games_won":
                user_stats.games_won,
                "cumulative_score":
                user_stats.cumulative_score,
                "highest_weekly_score":
                user_stats.highest_weekly_score,
                "last_played_date":
                user_stats.last_played_date.isoformat()
                if user_stats.last_played_date else None
            }

        # Get game history
        game_scores = GameScore.query.filter_by(user_id=user_id).all()
        games_data = []

        for game in game_scores:
            games_data.append({
                "game_id":
                game.game_id,
                "score":
                game.score,
                "mistakes":
                game.mistakes,
                "time_taken":
                game.time_taken,
                "game_type":
                game.game_type,
                "challenge_date":
                game.challenge_date,
                "completed":
                game.completed,
                "created_at":
                game.created_at.isoformat() if game.created_at else None
            })

        # Combine all data
        all_data = {
            "user_info": user_data,
            "stats": stats_data,
            "game_history": games_data
        }

        return jsonify(all_data), 200

    except Exception as e:
        logging.error(f"Error retrieving user data: {str(e)}")
        return jsonify({"msg": "An error occurred retrieving your data"}), 500


@bp.route('/api/delete-account', methods=['DELETE'])
@jwt_required()
def delete_account():
    try:
        # Get the current user's ID
        user_id = get_jwt_identity()

        if not user_id:
            return jsonify({"msg": "User not authenticated"}), 401

        # Find the user
        user = User.query.get(user_id)

        if not user:
            return jsonify({"msg": "User not found"}), 404

        # Get the JWT token before deleting the user
        token = get_jwt()
        jti = token["jti"]

        # Delete ALL user related data in correct order to handle foreign key constraints
        DailyCompletion.query.filter_by(user_id=user_id).delete()
        GameScore.query.filter_by(user_id=user_id).delete()
        UserStats.query.filter_by(user_id=user_id).delete()
        ActiveGameState.query.filter_by(user_id=user_id).delete()

        # Delete the user
        db.session.delete(user)
        db.session.commit()

        # Add token to blocklist after successful deletion
        jwt_blocklist.add(jti)

        return jsonify({
            "msg": "Account deleted successfully",
            "token_revoked": True
        }), 200

    except Exception as e:
        db.session.rollback()
        logging.error(f"Error deleting account: {str(e)}")
        return jsonify({"msg": "An error occurred deleting your account"}), 500


@bp.route('/forgot-password', methods=['POST'])
def forgot_password():
    try:
        data = request.get_json()
        email = data.get('email')

        if not email:
            return jsonify({"error": "Email is required"}), 400

        # Find user by email
        user = User.query.filter_by(email=email).first()
        if not user:
            # For security, still return success even if email not found
            return jsonify({
                "message":
                "If an account exists with this email, a reset link will be sent"
            }), 200

        # Generate reset token
        reset_token = secrets.token_urlsafe(32)
        user.reset_token = reset_token
        user.reset_token_expires = datetime.utcnow() + timedelta(hours=1)
        db.session.commit()

        # Create reset link
        reset_url = f"{request.host_url}reset-password?token={reset_token}"

        # Send email via Mailgun
        MAILGUN_API_KEY = current_app.config['MAILGUN_API_KEY']
        MAILGUN_DOMAIN = current_app.config['MAILGUN_DOMAIN']

        response = requests.post(
            f"https://api.mailgun.net/v3/{MAILGUN_DOMAIN}/messages",
            auth=("api", MAILGUN_API_KEY),
            data={
                "from": f"Daniel from Decodey <support@{MAILGUN_DOMAIN}>",
                "to": email,
                "subject": "Reset your Decodey password",
                "reply-to": f"support@{MAILGUN_DOMAIN}",
                "text": f"""Hi {user.username if user.username else 'there'},
            We received a request to reset your password for your Decodey account.

            To reset your password, please click the link below:
            {reset_url}

            This link will expire in 1 hour. If you didn't request a password reset, you can safely ignore this email — no action is required.

            — The Decodey Team
            https://decodey.game
            """,
                "html": f"""<html>
              <body style="font-family: Arial, sans-serif; font-size: 14px; color: #333;">
                <p>Hi {user.username if user.username else 'there'},</p>
                <p>We received a request to reset your password for your Decodey account.</p>
                <p>
                  To reset your password, click the link below:<br>
                  <a href="{reset_url}">{reset_url}</a>
                </p>
                <p>This link will expire in 1 hour.</p>
                <p>If you didn't request a password reset, you can safely ignore this email — no action is required.</p>
                <br>
                <p>— The Decodey Team<br>
                <a href="https://decodey.game">decodey.game</a></p>
              </body>
            </html>""",
                "headers": {
                    "List-Unsubscribe": f"<mailto:support@{MAILGUN_DOMAIN}>"
                }
            })

        if response.status_code != 200:
            raise Exception(
                f"Mailgun error: {response.status_code} - {response.text}")

        return jsonify({
            "message":
            "If an account exists with this email, a reset link will be sent"
        }), 200

    except Exception as e:
        logging.error(f"Error in forgot password: {str(e)}")
        return jsonify({"error":
                        "Failed to process password reset request"}), 500


@bp.route('/unsubscribe/<token>', methods=['GET'])
def unsubscribe(token):
    """Unsubscribe a user from emails using their unique token"""
    try:
        user = User.query.filter_by(unsubscribe_token=token).first()

        if not user:
            return jsonify({"error": "Invalid unsubscribe token"}), 400

        user.email_consent = False
        user.consent_date = None
        db.session.commit()

        return jsonify({
            "message": "Successfully unsubscribed from emails",
            "email": user.email
        }), 200

    except Exception as e:
        logging.error(f"Error in unsubscribe: {str(e)}")
        db.session.rollback()
        return jsonify({"error": "Failed to process unsubscribe request"}), 500


@bp.route('/reset-password', methods=['GET', 'POST'])
def reset_password():
    token = request.args.get('token')
    if not token:
        return jsonify({"error": "Reset token is required"}), 400

    user = User.query.filter_by(reset_token=token).first()

    if not user or not user.reset_token_expires or user.reset_token_expires < datetime.utcnow(
    ):
        return jsonify({"error": "Invalid or expired reset token"}), 400

    if request.method == 'GET':
        return render_template('admin/reset_password.html')

    if request.method == 'POST':
        data = request.get_json()
        new_password = data.get('password')

        if not new_password:
            return jsonify({"error": "New password is required"}), 400

        user.set_password(new_password)
        user.reset_token = None
        user.reset_token_expires = None
        db.session.commit()

        return jsonify({"message": "Password reset successfully"}), 200

    return jsonify({"message":
                    "Token verified, ready for password reset"}), 200


@bp.route('/auth/apple', methods=['POST'])
def apple_signin():
    try:
        data = request.get_json()
        apple_user_id = data.get('appleUserId')
        email = data.get('email')
        full_name = data.get('fullName')

        if not apple_user_id:
            return jsonify({'error': 'Apple user ID required'}), 400

        # Check if user exists with this Apple ID
        user = User.query.filter_by(apple_user_id=apple_user_id).first()

        if not user:
            # Create new user
            username = email or f"apple_user_{apple_user_id[:8]}"
            display_email = email or f"{apple_user_id}@apple.signin"

            user = User(
                email=display_email,
                username=username,
                password='APPLE_SIGNIN'  # Placeholder
            )
            user.apple_user_id = apple_user_id

            if full_name:
                user.display_name = full_name

            db.session.add(user)
            db.session.commit()

        # Generate tokens (same as regular login)
        access_token = create_access_token(identity=user.user_id)
        refresh_token = create_refresh_token(identity=user.user_id)

        return jsonify({
            'access_token': access_token,
            'refresh_token': refresh_token,
            'username': user.username,
            'user_id': user.user_id,
            'has_active_game': False,  # Check your game logic
            'subadmin': user.subadmin
        })

    except Exception as e:
        return jsonify({'error': str(e)}), 500
