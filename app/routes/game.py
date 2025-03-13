from flask import Blueprint, jsonify, request, render_template
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

DIFFICULTY_SETTINGS = {
    'easy': {'max_mistakes': 8, 'hint_penalty': 1},
    'medium': {'max_mistakes': 6, 'hint_penalty': 1},
    'hard': {'max_mistakes': 4, 'hint_penalty': 2}
}

def generate_game_id(difficulty='medium'):
    """Generate a game ID that includes the difficulty"""
    return f"{difficulty}-{str(uuid.uuid4())}"

def check_game_status(game_state):
    """Check if the game is won or lost based on difficulty settings"""
    difficulty = game_state.get('difficulty', 'medium')
    max_mistakes = DIFFICULTY_SETTINGS[difficulty]['max_mistakes']

    # Game is lost if mistakes exceed max allowed
    if game_state['mistakes'] >= max_mistakes:
        return {'game_complete': True, 'hasWon': False}

    # Game is won if all letters are correctly guessed
    all_letters_guessed = len(game_state['correctly_guessed']) == len(set(c for c in game_state['encrypted_paragraph'] if c.isalpha()))
    if all_letters_guessed:
        return {'game_complete': True, 'hasWon': True}

    # Game is still in progress
    return {'game_complete': False, 'hasWon': False}

@bp.route('/game')
def game_page():
    """Show the game page with API documentation"""
    sample_guess_json = {
        "request": {
            "encrypted_letter": "X",
            "guessed_letter": "E"
        },
        "response": {
            "display": "█E██O █O███",
            "mistakes": 1,
            "correctly_guessed": ["E"],
            "game_complete": False,
            "hasWon": False,
            "max_mistakes": 6
        }
    }

    sample_hint_json = {
        "response": {
            "display": "HE██O █O███",
            "mistakes": 2,
            "correctly_guessed": ["E", "H"],
            "game_complete": False,
            "hasWon": False,
            "max_mistakes": 6
        }
    }

    return render_template('game.html', 
                         sample_guess_json=sample_guess_json,
                         sample_hint_json=sample_hint_json)

@bp.route('/start', methods=['GET'])
@jwt_required()
def start():
    username = get_jwt_identity()
    difficulty = request.args.get('difficulty', 'medium')
    if difficulty not in DIFFICULTY_SETTINGS:
        difficulty = 'medium'

    logger.debug(f"Starting new game for user: {username} with difficulty: {difficulty}")

    game_data = start_game()
    game_state = game_data['game_state']
    game_state['game_id'] = generate_game_id(difficulty)
    game_state['difficulty'] = difficulty
    game_state['max_mistakes'] = DIFFICULTY_SETTINGS[difficulty]['max_mistakes']

    save_game_state(username, game_state)

    status = check_game_status(game_state)

    logger.debug(f"Game state saved with encrypted text: {game_data['encrypted_paragraph']}")
    return jsonify({
        "display": game_data['display'],
        "encrypted_paragraph": game_data['encrypted_paragraph'],
        "game_id": game_state['game_id'],
        "letter_frequency": game_data['letter_frequency'],
        "mistakes": game_data['mistakes'],
        "original_letters": game_data['original_letters'],
        "game_complete": status['game_complete'],
        "hasWon": status['hasWon'],
        "max_mistakes": game_state['max_mistakes'],
        "difficulty": difficulty
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

    save_game_state(username, game_state)
    status = check_game_status(game_state)
    logger.debug(f"Updated game state saved for user {username}")

    return jsonify({
        'display': display,
        'mistakes': game_state['mistakes'],
        'correctly_guessed': game_state['correctly_guessed'],
        'game_complete': status['game_complete'],
        'hasWon': status['hasWon'],
        'max_mistakes': game_state['max_mistakes'],
        'difficulty': game_state['difficulty']
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

    # Apply difficulty-specific hint penalty
    difficulty = game_state.get('difficulty', 'medium')
    hint_penalty = DIFFICULTY_SETTINGS[difficulty]['hint_penalty']
    game_state['mistakes'] += hint_penalty

    display = get_display(game_state['encrypted_paragraph'],
                         game_state['correctly_guessed'],
                         game_state['reverse_mapping'])

    save_game_state(username, game_state)
    status = check_game_status(game_state)
    logger.debug(f"Updated game state saved after hint for user {username}")

    return jsonify({
        'display': display,
        'mistakes': game_state['mistakes'],
        'correctly_guessed': game_state['correctly_guessed'],
        'game_complete': status['game_complete'],
        'hasWon': status['hasWon'],
        'max_mistakes': game_state['max_mistakes'],
        'difficulty': game_state['difficulty']
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