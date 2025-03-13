from flask import Blueprint, request, jsonify, redirect, url_for
from flask_jwt_extended import (
    create_access_token, create_refresh_token,
    get_jwt_identity, jwt_required, get_jwt
)
from werkzeug.security import generate_password_hash, check_password_hash
from app import jwt_blocklist
from app.utils.db import get_user, save_user

bp = Blueprint('auth', __name__)

@bp.route('/register', methods=['POST'])
def register():
    data = request.get_json()
    username = data.get('username')
    password = data.get('password')

    if not username or not password:
        return jsonify({"msg": "Username and password are required"}), 400

    if get_user(username):
        return jsonify({"msg": "Username already exists"}), 409

    # Hash the password using Werkzeug's default method (pbkdf2:sha256)
    password_hash = generate_password_hash(password)

    user = {
        'username': username,
        'password': password_hash
    }
    save_user(user)

    return jsonify({"msg": "User created successfully"}), 201

@bp.route('/login', methods=['POST'])
def login():
    data = request.get_json()
    username = data.get('username')
    password = data.get('password')
    remember = data.get('remember', False)

    user = get_user(username)
    if not user or not check_password_hash(user['password'], password):
        return jsonify({"msg": "Invalid credentials"}), 401

    access_token = create_access_token(
        identity=username,
        fresh=True,
        additional_claims={"username": username}
    )
    refresh_token = create_refresh_token(identity=username) if remember else None

    return jsonify({
        "access_token": access_token,
        "refresh_token": refresh_token
    }), 200

@bp.route('/logout')
@jwt_required(optional=True)
def logout():
    token = get_jwt()
    if token:
        jti = token["jti"]
        jwt_blocklist.add(jti)
    return redirect(url_for('main.index'))