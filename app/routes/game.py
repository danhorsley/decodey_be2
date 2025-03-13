from flask import Blueprint, jsonify, request, render_template
from flask_jwt_extended import jwt_required, get_jwt_identity
from app.services.game_logic import start_game, make_guess, get_hint
from app.utils.db import get_game_state, save_game_state
from app.utils.scoring import score_game, record_game_score, update_active_game_state
from app.models import db, ActiveGameState
from app.utils.stats import initialize_or_update_user_stats  # Added ActiveGameState import
from datetime import datetime
import logging
import uuid
import random

# Set up logging
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

bp = Blueprint('game', __name__)

DIFFICULTY_SETTINGS = {
    'easy': {
        'max_mistakes': 8,
        'hint_penalty': 1
    },
    'medium': {
        'max_mistakes': 6,
        'hint_penalty': 1
    },
    'hard': {
        'max_mistakes': 4,
        'hint_penalty': 2
    }
}


def generate_game_id(difficulty='medium'):
    """Generate a game ID that includes the difficulty"""
    return f"{difficulty}-{str(uuid.uuid4())}"


def check_game_status(game_state):
    """Check if the game is won or lost based on difficulty settings"""
    difficulty = game_state.get('difficulty', 'medium')
    max_mistakes = DIFFICULTY_SETTINGS[difficulty]['max_mistakes']

    # Calculate time taken if game is ending
    start_time = game_state.get('start_time')
    time_taken = int(
        (datetime.utcnow() - start_time).total_seconds()) if start_time else 0

    # Game is lost if mistakes exceed max allowed
    if game_state['mistakes'] >= max_mistakes:
        if not game_state.get('game_complete', False):  # Only score once
            score = score_game(difficulty, game_state['mistakes'], time_taken)
            record_game_score(get_jwt_identity(),
                              game_state['game_id'],
                              score,
                              game_state['mistakes'],
                              time_taken,
                              completed=True)
            game_state['game_complete'] = True
            update_active_game_state(get_jwt_identity(), game_state)
            initialize_or_update_user_stats(get_jwt_identity())
        return {'game_complete': True, 'hasWon': False}

    # Game is won if all letters are correctly guessed
    all_letters_guessed = len(game_state['correctly_guessed']) == len(
        set(c for c in game_state['encrypted_paragraph'] if c.isalpha()))
    if all_letters_guessed:
        if not game_state.get('game_complete', False):  # Only score once
            score = score_game(difficulty, game_state['mistakes'], time_taken)
            record_game_score(get_jwt_identity(),
                              game_state['game_id'],
                              score,
                              game_state['mistakes'],
                              time_taken,
                              completed=True)
            game_state['game_complete'] = True
            update_active_game_state(get_jwt_identity(), game_state)
            initialize_or_update_user_stats(get_jwt_identity())
        return {'game_complete': True, 'hasWon': True}

    # Game is still in progress
    return {'game_complete': False, 'hasWon': False}


@bp.route('/start', methods=['GET'])
@jwt_required()
def start():
    username = get_jwt_identity()
    difficulty = request.args.get('difficulty', 'medium')
    if difficulty not in DIFFICULTY_SETTINGS:
        difficulty = 'medium'

    logger.debug(
        f"Starting new game for user: {username} with difficulty: {difficulty}"
    )

    game_data = start_game()
    game_state = game_data['game_state']
    game_state['game_id'] = generate_game_id(difficulty)
    game_state['difficulty'] = difficulty
    game_state['max_mistakes'] = DIFFICULTY_SETTINGS[difficulty][
        'max_mistakes']
    game_state['start_time'] = datetime.utcnow()  # Track start time
    game_state['game_complete'] = False  # Track if game has been completed

    save_game_state(username, game_state)
    update_active_game_state(username, game_state)  # Save to ActiveGameState

    status = check_game_status(game_state)
    logger.debug(
        f"Game state saved with encrypted text: {game_data['encrypted_paragraph']}"
    )

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

    logger.debug(
        f"Guess from {username}: {encrypted_letter} -> {guessed_letter}")

    game_state = get_game_state(username)
    if not game_state:
        logger.error(f"No active game found for user: {username}")
        return jsonify({"msg": "No active game"}), 400

    if not validate_guess(encrypted_letter, guessed_letter,
                          game_state['reverse_mapping'],
                          game_state['correctly_guessed']):
        game_state['mistakes'] += 1

    display = get_display(game_state['encrypted_paragraph'],
                          game_state['correctly_guessed'],
                          game_state['reverse_mapping'])

    save_game_state(username, game_state)
    update_active_game_state(username, game_state)  # Update ActiveGameState
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
    unmapped = [
        letter for letter in all_encrypted
        if letter not in game_state['correctly_guessed']
    ]

    if not unmapped:
        return jsonify({"msg": "No more hints available"}), 400

    used_unmapped = [
        x for x in unmapped if x in game_state['encrypted_paragraph']
    ]
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
    update_active_game_state(username, game_state)  # Update ActiveGameState
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
    return ''.join(reverse_mapping[char] if char in
                   correctly_guessed else '█' if char.isalpha() else char
                   for char in encrypted_paragraph)


def validate_guess(encrypted_letter, guessed_letter, reverse_mapping,
                   correctly_guessed):
    if reverse_mapping[encrypted_letter] == guessed_letter.upper():
        if encrypted_letter not in correctly_guessed:
            correctly_guessed.append(encrypted_letter)
        return True
    return False


@bp.route('/check-active-game')
@jwt_required()
def check_active_game():
    """Check if user has an active game and return minimal game info"""
    user_id = get_jwt_identity()
    active_game = ActiveGameState.query.filter_by(user_id=user_id).first()

    if not active_game:
        return jsonify({"has_active_game": False}), 200

    # Calculate basic stats
    completion_percentage = len(active_game.correctly_guessed) / len(
        set(c for c in active_game.encrypted_paragraph if c.isalpha())) * 100
    time_spent = int(
        (datetime.utcnow() - active_game.created_at).total_seconds())
    difficulty = active_game.game_id.split('-')[0]

    return jsonify({
        "has_active_game": True,
        "game_stats": {
            "difficulty": difficulty,
            "mistakes": active_game.mistakes,
            "completion_percentage": round(completion_percentage, 1),
            "time_spent": time_spent,
            "max_mistakes": DIFFICULTY_SETTINGS[difficulty]['max_mistakes']
        }
    }), 200


@bp.route('/continue-game')
@jwt_required()
def continue_game():
    """Return full game state for continuing"""
    user_id = get_jwt_identity()
    active_game = ActiveGameState.query.filter_by(user_id=user_id).first()

    if not active_game:
        return jsonify({"msg": "No active game found"}), 404

    # Generate original letters by getting unique values from reverse_mapping
    # original_letters = sorted(set(active_game.reverse_mapping.values()))
    original_letters = sorted(
        set(''.join(x for x in active_game.original_paragraph.upper()
                    if x.isalpha())))

    # Convert SQLAlchemy model to dict for response
    game_state = {
        "display":
        get_display(active_game.encrypted_paragraph,
                    active_game.correctly_guessed,
                    active_game.reverse_mapping),
        "encrypted_paragraph":
        active_game.encrypted_paragraph,
        "game_id":
        active_game.game_id,
        "letter_frequency": {
            letter: active_game.encrypted_paragraph.count(letter)
            for letter in set(active_game.encrypted_paragraph)
            if letter.isalpha()
        },
        "mistakes":
        active_game.mistakes,
        "correctly_guessed":
        active_game.correctly_guessed,
        "game_complete":
        False,
        "hasWon":
        False,
        "max_mistakes":
        DIFFICULTY_SETTINGS[active_game.game_id.split('-')[0]]['max_mistakes'],
        "difficulty":
        active_game.game_id.split('-')[0],
        "original_letters":
        original_letters,  # Use derived original letters
        "mapping":
        active_game.mapping,
        "reverse_mapping":
        active_game.reverse_mapping
    }

    return jsonify(game_state), 200


@bp.route('/abandon-game')
@jwt_required()
def abandon_game():
    """Abandon current game without recording score"""
    user_id = get_jwt_identity()
    ActiveGameState.query.filter_by(user_id=user_id).delete()
    db.session.commit()
    return jsonify({"msg": "Game abandoned successfully"}), 200
