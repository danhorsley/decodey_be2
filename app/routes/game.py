from flask import Blueprint, jsonify, request
from flask_jwt_extended import jwt_required, get_jwt_identity
from app.services.game_logic import start_game, make_guess, get_hint
from app.utils.db import get_game_state, save_game_state

bp = Blueprint('game', __name__, url_prefix='/api/game')

@bp.route('/start', methods=['POST'])
@jwt_required()
def start():
    username = get_jwt_identity()
    word = start_game()
    game_state = {
        'word': word,
        'attempts': 0,
        'guesses': []
    }
    save_game_state(username, game_state)
    return jsonify({"msg": "New game started"}), 200

@bp.route('/guess', methods=['POST'])
@jwt_required()
def guess():
    username = get_jwt_identity()
    data = request.get_json()
    guess = data.get('guess')

    game_state = get_game_state(username)
    if not game_state:
        return jsonify({"msg": "No active game"}), 400

    result = make_guess(game_state['word'], guess)
    game_state['attempts'] += 1
    game_state['guesses'].append(guess)
    save_game_state(username, game_state)

    return jsonify({
        "correct": result['correct'],
        "position": result['position']
    }), 200

@bp.route('/hint', methods=['GET'])
@jwt_required()
def hint():
    username = get_jwt_identity()
    game_state = get_game_state(username)
    if not game_state:
        return jsonify({"msg": "No active game"}), 400

    hint_text = get_hint(game_state['word'])
    return jsonify({"hint": hint_text}), 200