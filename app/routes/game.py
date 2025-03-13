from flask import Blueprint, jsonify, request
from flask_jwt_extended import jwt_required, get_jwt_identity
from app.services.game_logic import start_game, make_guess, get_hint
from app.utils.db import get_game_state, save_game_state
import logging

# Set up logging
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

bp = Blueprint('game', __name__, url_prefix='/api/game')

@bp.route('/start', methods=['POST'])
@jwt_required()
def start():
    username = get_jwt_identity()
    logger.debug(f"Starting new game for user: {username}")

    game_data = start_game()
    save_game_state(username, game_data['game_state'])

    logger.debug(f"Game state saved with encrypted text: {game_data['encrypted']}")
    return jsonify({
        "encrypted_text": game_data['encrypted'],
        "letter_frequencies": game_data['encrypted_frequency'],
        "available_letters": game_data['unique_letters']
    }), 200

@bp.route('/guess', methods=['POST'])
@jwt_required()
def guess():
    username = get_jwt_identity()
    data = request.get_json()
    encrypted_letter = data.get('encrypted_letter')
    guessed_letter = data.get('guessed_letter')

    logger.debug(f"Guess from {username}: {encrypted_letter} -> {guessed_letter}")

    game_state = get_game_state(username)
    if not game_state:
        logger.error(f"No active game found for user: {username}")
        return jsonify({"msg": "No active game"}), 400

    result = make_guess(game_state, encrypted_letter, guessed_letter)
    if not result['valid']:
        return jsonify({"msg": result['message']}), 400

    save_game_state(username, game_state)
    logger.debug(f"Guess result: {result}")

    return jsonify({
        "correct": result['correct'],
        "game_complete": result['complete'],
        "mistakes_remaining": result['max_mistakes'] - result['mistakes'],
        "revealed_pairs": result['revealed_pairs']
    }), 200

@bp.route('/hint', methods=['GET'])
@jwt_required()
def hint():
    username = get_jwt_identity()
    logger.debug(f"Hint requested by user: {username}")

    game_state = get_game_state(username)
    if not game_state:
        logger.error(f"No active game found for user: {username}")
        return jsonify({"msg": "No active game"}), 400

    hint_result = get_hint(game_state)
    if not hint_result:
        return jsonify({"msg": "No more hints available"}), 400

    save_game_state(username, game_state)
    logger.debug(f"Providing hint: {hint_result}")

    return jsonify({
        "encrypted_letter": hint_result['encrypted'],
        "original_letter": hint_result['original']
    }), 200