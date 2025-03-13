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
    game_state = start_game()
    save_game_state(username, game_state)
    logger.debug(f"Game state saved: {game_state['encrypted_quote']}")
    return jsonify({
        "encrypted_quote": game_state['encrypted_quote'],
        "length": len(game_state['original_quote'])
    }), 200

@bp.route('/guess', methods=['POST'])
@jwt_required()
def guess():
    username = get_jwt_identity()
    data = request.get_json()
    guess = data.get('guess')
    logger.debug(f"Received guess from {username}: {guess}")

    game_state = get_game_state(username)
    if not game_state:
        logger.error(f"No active game found for user: {username}")
        return jsonify({"msg": "No active game"}), 400

    result = make_guess(game_state, guess)
    logger.debug(f"Guess result: {result}")

    # Update game state with the attempt
    game_state.setdefault('attempts', []).append({
        'guess': guess,
        'result': result
    })
    save_game_state(username, game_state)

    return jsonify(result), 200

@bp.route('/hint', methods=['GET'])
@jwt_required()
def hint():
    username = get_jwt_identity()
    logger.debug(f"Hint requested by user: {username}")

    game_state = get_game_state(username)
    if not game_state:
        logger.error(f"No active game found for user: {username}")
        return jsonify({"msg": "No active game"}), 400

    hint_text = get_hint(game_state)
    logger.debug(f"Providing hint: {hint_text}")
    return jsonify({"hint": hint_text}), 200