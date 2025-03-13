from flask import Blueprint, jsonify, redirect, url_for, render_template, request
from flask_jwt_extended import jwt_required, get_jwt_identity
import logging

bp = Blueprint('main', __name__)

@bp.route('/')
def index():
    """Return login page for browser requests, API status for API requests"""
    if request.headers.get('Accept') == 'application/json':
        return jsonify({
            "status": "ok",
            "message": "Uncrypt Game API"
        })
    return render_template('login.html')

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
    """Return registration page for browser requests, API message for API requests"""
    if request.headers.get('Accept') == 'application/json':
        return jsonify({"message": "Registration endpoint"})
    return render_template('register.html')

@bp.route('/game')
@jwt_required()
def game():
    """Show the game page for browser requests, API data for API requests"""
    if request.headers.get('Accept') == 'application/json':
        return jsonify({
            "status": "ok",
            "message": "Game API endpoint"
        })

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

    return render_template('game.html',
                         sample_guess_json=sample_guess_json,
                         sample_hint_json=sample_hint_json)

@bp.route('/stats')
@jwt_required()
def stats():
    """Show user statistics page"""
    if request.headers.get('Accept') == 'application/json':
        return jsonify({"message": "Stats API endpoint"})
    return render_template('stats.html')

@bp.route('/leaderboard')
def leaderboard():
    """Show leaderboard page"""
    if request.headers.get('Accept') == 'application/json':
        return jsonify({"message": "Leaderboard API endpoint"})
    return render_template('leaderboard.html')