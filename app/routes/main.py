from flask import Blueprint, render_template
from flask_jwt_extended import jwt_required, get_jwt_identity

bp = Blueprint('main', __name__)

@bp.route('/')
def index():
    return render_template('login.html')

@bp.route('/register')
def register():
    return render_template('register.html')

@bp.route('/game')
@jwt_required()
def game():
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