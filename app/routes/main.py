from flask import Blueprint, jsonify, redirect, url_for
from flask_jwt_extended import jwt_required, get_jwt_identity
import logging

bp = Blueprint('main', __name__)

@bp.route('/')
def index():
    """Return API status for root endpoint"""
    return jsonify({
        "status": "ok",
        "message": "Uncrypt Game API"
    })

@bp.route('/api/status')
@jwt_required()
def api_status():
    """Protected endpoint to verify JWT auth"""
    current_user = get_jwt_identity()
    return jsonify({
        "status": "authenticated",
        "user": current_user
    })

@bp.route('/register')
def register():
    return jsonify({"message": "Registration page"}) # Changed to JSON response

@bp.route('/game')
@jwt_required() # Added JWT authentication
def game():
    """Show the game page - JWT check happens in frontend"""
    # Sample JSON for API documentation
    sample_guess_json = {
        "request": {
            "encrypted_letter": "X",
            "guessed_letter": "E"
        },
        "response": {
            "display": "█E██O █O███",
            "mistakes": 1,
            "correctly_guessed": ["E"],
            "game_complete": False
        }
    }

    sample_hint_json = {
        "response": {
            "display": "HE██O █O███",
            "mistakes": 2,
            "correctly_guessed": ["E", "H"]
        }
    }

    return jsonify({"sample_guess": sample_guess_json, "sample_hint": sample_hint_json}) # Changed to JSON response


@bp.route('/stats')
@jwt_required() # Added JWT authentication
def stats():
    """Show user statistics page"""
    return jsonify({"message": "User statistics page"}) # Changed to JSON response


@bp.route('/leaderboard')
def leaderboard():
    """Show leaderboard page"""
    return jsonify({"message": "Leaderboard page"}) # Changed to JSON response