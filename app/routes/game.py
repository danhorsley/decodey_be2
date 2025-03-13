from flask import Blueprint, jsonify, request
from flask_jwt_extended import jwt_required, get_jwt_identity
from app.services.game_logic import start_game, make_guess, get_hint
from app.utils.db import get_game_state, save_game_state
import logging
import uuid
import random

# Set up logging
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

bp = Blueprint('game', __name__)

@bp.route('/start', methods=['POST'])
@jwt_required()
def start():
    username = get_jwt_identity()
    logger.debug(f"Starting new game for user: {username}")

    game_data = start_game()
    game_state = game_data['game_state']
    game_state['game_id'] = str(uuid.uuid4())
    save_game_state(username, game_state)

    logger.debug(f"Game state saved with encrypted text: {game_data['encrypted_paragraph']}")
    return jsonify({
        "display": game_data['display'],
        "encrypted_paragraph": game_data['encrypted_paragraph'],
        "game_id": game_state['game_id'],
        "letter_frequency": game_data['letter_frequency'],
        "major_attribution": game_data['major_attribution'],
        "minor_attribution": game_data['minor_attribution'],
        "mistakes": game_data['mistakes'],
        "original_letters": game_data['original_letters']
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

    if not validate_guess(encrypted_letter, guessed_letter, game_state['reverse_mapping'], game_state['correctly_guessed']):
        game_state['mistakes'] += 1

    display = get_display(game_state['encrypted_paragraph'], 
                         game_state['correctly_guessed'],
                         game_state['reverse_mapping'])

    game_complete = (
        len(game_state['correctly_guessed']) == len(set(game_state['mapping'].values())) or 
        game_state['mistakes'] >= game_state.get('max_mistakes', 5)
    )

    save_game_state(username, game_state)
    logger.debug(f"Updated game state saved for user {username}")

    return jsonify({
        'display': display,
        'mistakes': game_state['mistakes'],
        'correctly_guessed': game_state['correctly_guessed'],
        'game_complete': game_complete
    }), 200

@bp.route('/hint', methods=['POST'])
@jwt_required()
def hint():
    username = get_jwt_identity()
    logger.debug(f"Hint requested by user: {username}")

    game_state = get_game_state(username)
    if not game_state:
        logger.error(f"No active game found for user: {username}")
        return jsonify({"msg": "No active game"}), 400

    all_encrypted = list(game_state['mapping'].values())
    unmapped = [letter for letter in all_encrypted 
                if letter not in game_state['correctly_guessed']]

    if not unmapped:
        return jsonify({"msg": "No more hints available"}), 400

    used_unmapped = [x for x in unmapped if x in game_state['encrypted_paragraph']]
    if not used_unmapped:
        return jsonify({"msg": "No more hints available"}), 400

    letter = random.choice(used_unmapped)
    game_state['correctly_guessed'].append(letter)
    game_state['mistakes'] += 1

    display = get_display(game_state['encrypted_paragraph'],
                         game_state['correctly_guessed'],
                         game_state['reverse_mapping'])

    save_game_state(username, game_state)
    logger.debug(f"Updated game state saved after hint for user {username}")

    return jsonify({
        'display': display,
        'mistakes': game_state['mistakes'],
        'correctly_guessed': game_state['correctly_guessed']
    }), 200

def get_display(encrypted_paragraph, correctly_guessed, reverse_mapping):
    return ''.join(reverse_mapping[char] if char in correctly_guessed
                  else '█' if char.isalpha() else char
                  for char in encrypted_paragraph)

def validate_guess(encrypted_letter, guessed_letter, reverse_mapping, correctly_guessed):
    if reverse_mapping[encrypted_letter] == guessed_letter.upper():
        if encrypted_letter not in correctly_guessed:
            correctly_guessed.append(encrypted_letter)
        return True
    return False