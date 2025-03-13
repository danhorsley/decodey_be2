from flask import Blueprint, render_template, redirect, url_for, jsonify
from flask_jwt_extended import jwt_required, get_jwt_identity
import logging

bp = Blueprint('main', __name__)


@bp.route('/')
def index():
    return render_template('login.html')


@bp.route('/register')
def register():
    return render_template('register.html')


@bp.route('/game')
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

    return render_template('game.html',
                           sample_guess_json=sample_guess_json,
                           sample_hint_json=sample_hint_json)


@bp.route('/stats')
def stats():
    """Show user statistics page"""
    return render_template('stats.html')


@bp.route('/leaderboard')
def leaderboard():
    """Show leaderboard page"""
    return render_template('leaderboard.html')


# @bp.route('/debug-routes', methods=['GET'])
# def debug_routes():
#     routes = []
#     for rule in current_app.url_map.iter_rules():
#         routes.append({
#             'endpoint':
#             rule.endpoint,
#             'methods': [method for method in rule.methods if method != 'HEAD'],
#             'url':
#             str(rule)
#         })
#     return jsonify({'routes': routes})
