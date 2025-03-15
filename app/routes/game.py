from flask import Blueprint, jsonify, request, Response, stream_with_context
from flask_jwt_extended import jwt_required, get_jwt_identity, decode_token
from jwt.exceptions import PyJWTError
from app.services.game_logic import start_game, make_guess, get_hint
from app.utils.db import get_game_state, save_game_state
from app.utils.scoring import score_game, record_game_score, update_active_game_state
from app.models import db, ActiveGameState
from app.utils.stats import initialize_or_update_user_stats
from datetime import datetime
import logging
import json
import time
import sys
import uuid
import random

# Set up logging
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

bp = Blueprint('game', __name__)

# @bp.errorhandler(NoAuthorizationError)
# def handle_auth_error(e):
#     return jsonify({"error": "Authentication required"}), 401


@bp.route('/start', methods=['GET', 'OPTIONS'])
@jwt_required()
def start():
    """Start a new game"""
    if request.method == 'OPTIONS':
        return jsonify({}), 200

    try:
        username = get_jwt_identity()

        # Get skip_active_game_check parameter from request
        # skip_active_game_check = request.args.get('skipActiveGameCheck',
        #                                           'false').lower() == 'true'

        # Check for active game only if we're not skipping the check
        active_game_info = {"has_active_game": False}
        # if not skip_active_game_check:
        # Check for active game first
        active_game = ActiveGameState.query.filter_by(user_id=username).first()

        # Create active game info if one exists
        if active_game:
            # Calculate completion percentage
            encrypted_letters = set(c for c in active_game.encrypted_paragraph
                                    if c.isalpha())
            completion_percentage = (len(active_game.correctly_guessed) /
                                     len(encrypted_letters) *
                                     100) if encrypted_letters else 0

            # Extract difficulty from game_id
            difficulty = active_game.game_id.split(
                '-')[0] if active_game.game_id else 'medium'

            # Calculate time spent
            time_spent = int(
                (datetime.utcnow() - active_game.created_at).total_seconds())

            # Build active game info
            active_game_info = {
                "has_active_game": True,
                "game_id": active_game.game_id,
                "difficulty": difficulty,
                "mistakes": active_game.mistakes,
                "completion_percentage": round(completion_percentage, 1),
                "time_spent": time_spent,
                "max_mistakes": DIFFICULTY_SETTINGS[difficulty]['max_mistakes']
            }

        # Get difficulty from query params - map frontend values to backend values
        frontend_difficulty = request.args.get('difficulty', 'normal')

        # Map frontend difficulty names to backend difficulty settings
        difficulty_mapping = {
            'easy': 'easy',
            'normal': 'medium',
            'hard': 'hard'
        }

        # Use the mapped difficulty or default to 'medium'
        backend_difficulty = difficulty_mapping.get(frontend_difficulty,
                                                    'medium')

        if backend_difficulty not in DIFFICULTY_SETTINGS:
            logger.warning(
                f"Invalid difficulty value: {backend_difficulty}, defaulting to medium"
            )
            backend_difficulty = 'medium'

        logger.debug(
            f"Starting new game for user: {username} with difficulty: {backend_difficulty} (from frontend: {frontend_difficulty})"
        )

        # Start a new game and get game data
        game_data = start_game()
        game_state = game_data['game_state']
        game_state['game_id'] = generate_game_id(backend_difficulty)
        game_state['difficulty'] = backend_difficulty
        game_state['max_mistakes'] = DIFFICULTY_SETTINGS[backend_difficulty][
            'max_mistakes']
        game_state['start_time'] = datetime.utcnow()
        game_state['game_complete'] = False

        save_game_state(username, game_state)
        update_active_game_state(username, game_state)

        status = check_game_status(game_state)
        logger.debug(
            f"Game state saved with encrypted text: {game_data['encrypted_paragraph'][:20]}..."
        )

        # Create the response data
        response_data = {
            "display": game_data['display'],
            "encrypted_paragraph": game_data['encrypted_paragraph'],
            "game_id": game_state['game_id'],
            "letter_frequency": game_data['letter_frequency'],
            "mistakes": game_data['mistakes'],
            "original_letters": game_data['original_letters'],
            "game_complete": status['game_complete'],
            "hasWon": status['hasWon'],
            "max_mistakes": game_state['max_mistakes'],
            "difficulty":
            frontend_difficulty  # Return the frontend difficulty value
        }

        # Add active game info to the response
        response_data["active_game_info"] = active_game_info

        return jsonify(response_data), 200
    except Exception as e:
        logger.error(f"Error starting game: {str(e)}")
        return jsonify({"error": "Failed to start game"}), 500


def generate_game_id(difficulty='medium'):
    """Generate a game ID that includes the difficulty"""
    return f"{difficulty}-{str(uuid.uuid4())}"


def check_game_status(game_state):
    """Simplified version to debug the 500 error"""
    logger.debug(
        f"Checking game status with state: mistakes={game_state.get('mistakes', 0)}"
    )

    difficulty = game_state.get('difficulty', 'medium')
    max_mistakes = DIFFICULTY_SETTINGS[difficulty]['max_mistakes']

    # Game is lost if mistakes exceed max allowed
    if game_state.get('mistakes', 0) >= max_mistakes:
        return {'game_complete': True, 'hasWon': False}

    # Game is won if all letters are correctly guessed
    encrypted_letters = set(c
                            for c in game_state.get('encrypted_paragraph', '')
                            if c.isalpha())
    correctly_guessed = game_state.get('correctly_guessed', [])

    all_letters_guessed = len(correctly_guessed) == len(encrypted_letters)
    if all_letters_guessed:
        return {'game_complete': True, 'hasWon': True}

    # Game is still in progress
    return {'game_complete': False, 'hasWon': False}


@bp.route('/guess', methods=['POST', 'OPTIONS'])
@jwt_required()
def guess():
    if request.method == 'OPTIONS':
        return jsonify({}), 200
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


@bp.route('/hint', methods=['POST', 'OPTIONS'])
@jwt_required()
def hint():
    if request.method == 'OPTIONS':
        return jsonify({}), 200
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


@bp.route('/check-active-game', methods=['GET', 'OPTIONS'])
@jwt_required()
def check_active_game():
    if request.method == 'OPTIONS':
        return jsonify({}), 200
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


@bp.route('/continue-game', methods=['GET', 'OPTIONS'])
@jwt_required()
def continue_game():
    if request.method == 'OPTIONS':
        return jsonify({}), 200
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


@bp.route('/abandon-game', methods=['DELETE', 'OPTIONS'])
@jwt_required()
def abandon_game():
    if request.method == 'OPTIONS':
        return jsonify({}), 200
    """Abandon current game without recording score"""
    user_id = get_jwt_identity()
    ActiveGameState.query.filter_by(user_id=user_id).delete()
    db.session.commit()
    return jsonify({"msg": "Game abandoned successfully"}), 200


# Optional helper function for the endpoint
def get_attribution(game_id):
    """Get attribution data for a game"""
    try:
        # Implement logic to retrieve attribution for the given game_id
        # This is a placeholder - replace with your actual implementation
        return {
            'major_attribution': 'Famous Author',
            'minor_attribution': 'Source Book'
        }
    except Exception as e:
        logger.error(f"Error fetching attribution: {str(e)}")
        return {'major_attribution': '', 'minor_attribution': ''}


def get_rating_from_score(score):
    """Determine rating based on score"""
    if score >= 900:
        return "Perfect"
    elif score >= 800:
        return "Ace of Spies"
    elif score >= 700:
        return "Bletchley Park"
    elif score >= 500:
        return "Cabinet Noir"
    else:
        return "Cryptanalyst"


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


@bp.route('/game-status', methods=['GET', 'OPTIONS'])
@jwt_required()
def game_status():
    """Return the current game status for polling"""
    if request.method == 'OPTIONS':
        return jsonify({}), 200

    user_id = get_jwt_identity()
    game_state = get_game_state(user_id)

    logger.debug(f"Game status check for user {user_id}")

    if not game_state:
        logger.debug(f"No active game found for user {user_id}")
        return jsonify({"hasActiveGame": False}), 200

    # Calculate basic information about game state
    status = check_game_status(game_state)
    logger.debug(f"Game status: {status}")

    # If game is won but not yet notified, prepare win data
    win_data = None
    if status['hasWon'] and not game_state.get('win_notified', False):
        logger.info(f"Win detected for user {user_id} - preparing win data")

        # Mark as notified to prevent duplicate notifications
        game_state['win_notified'] = True
        save_game_state(user_id, game_state)

        # Get attribution data
        attribution = get_attribution(game_state.get('game_id', ''))

        # Calculate time and score
        time_taken = (
            datetime.utcnow() -
            game_state.get('start_time', datetime.utcnow())).total_seconds()
        score = score_game(game_state.get('difficulty', 'medium'),
                           game_state.get('mistakes', 0), time_taken)

        # Determine rating
        rating = get_rating_from_score(score)

        win_data = {
            'score': score,
            'mistakes': game_state.get('mistakes', 0),
            'maxMistakes': game_state.get('max_mistakes', 6),
            'gameTimeSeconds': int(time_taken),
            'rating': rating,
            'attribution': attribution
        }

        logger.debug(f"Win data prepared: {win_data}")

        # Record score if this is the first time notifying win
        try:
            record_game_score(user_id,
                              game_state.get('game_id'),
                              score,
                              game_state.get('mistakes'),
                              time_taken,
                              completed=True)
            logger.debug("Score recorded via polling")
        except Exception as e:
            logger.error(f"Error recording score via polling: {str(e)}")

    response_data = {
        "hasActiveGame": True,
        "gameComplete": status['game_complete'],
        "hasWon": status['hasWon'],
        "winData": win_data,
        "mistakes": game_state.get('mistakes', 0),
        "maxMistakes": game_state.get('max_mistakes', 6),
    }

    logger.debug(f"Returning game status: {response_data}")
    return jsonify(response_data), 200
