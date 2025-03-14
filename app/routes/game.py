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
        difficulty = request.args.get('difficulty', 'medium')
        if difficulty not in DIFFICULTY_SETTINGS:
            difficulty = 'medium'

        logger.debug(
            f"Starting new game for user: {username} with difficulty: {difficulty}"
        )

        # Start a new game and get game data
        game_data = start_game()
        game_state = game_data['game_state']
        game_state['game_id'] = generate_game_id(difficulty)
        game_state['difficulty'] = difficulty
        game_state['max_mistakes'] = DIFFICULTY_SETTINGS[difficulty][
            'max_mistakes']
        game_state['start_time'] = datetime.utcnow()
        game_state['game_complete'] = False

        save_game_state(username, game_state)
        update_active_game_state(username, game_state)

        status = check_game_status(game_state)
        logger.debug(
            f"Game state saved with encrypted text: {game_data['encrypted_paragraph']}"
        )

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
            "difficulty": difficulty
        }

        return jsonify(response_data), 200
    except Exception as e:
        logger.error(f"Error starting game: {str(e)}")
        return jsonify({"error": "Failed to start game"}), 500


def generate_game_id(difficulty='medium'):
    """Generate a game ID that includes the difficulty"""
    return f"{difficulty}-{str(uuid.uuid4())}"


def check_game_status(game_state):
    """Check if the game is won or lost based on difficulty settings"""
    logger.debug(f"Checking game status with state: {game_state}")

    difficulty = game_state.get('difficulty', 'medium')
    max_mistakes = DIFFICULTY_SETTINGS[difficulty]['max_mistakes']

    # Calculate time taken if game is ending
    start_time = game_state.get('start_time')
    time_taken = int(
        (datetime.utcnow() - start_time).total_seconds()) if start_time else 0

    # Game is lost if mistakes exceed max allowed
    if game_state['mistakes'] >= max_mistakes:
        if not game_state.get('game_complete', False):  # Only score once
            logger.debug("Game lost condition met. Recording score.")
            score = score_game(difficulty, game_state['mistakes'], time_taken)
            record_game_score(get_jwt_identity(),
                              game_state['game_id'],
                              score,
                              game_state['mistakes'],
                              time_taken,
                              completed=True)
            game_state['game_complete'] = True
            game_state['hasWon'] = False  # Explicitly mark as not won
            update_active_game_state(get_jwt_identity(), game_state)
            initialize_or_update_user_stats(get_jwt_identity())
        logger.debug("Returning game status: game_complete=True, hasWon=False")
        return {'game_complete': True, 'hasWon': False}

    # Game is won if all letters are correctly guessed
    all_letters = set(c for c in game_state['encrypted_paragraph']
                      if c.isalpha())
    logger.debug(
        f"Win check: correctly_guessed={len(game_state['correctly_guessed'])}, unique_letters={len(all_letters)}"
    )

    all_letters_guessed = len(
        game_state['correctly_guessed']) == len(all_letters)
    if all_letters_guessed:
        logger.debug("All letters guessed! Win condition met.")

        if not game_state.get('game_complete', False):  # Only score once
            logger.debug(
                f"Game not yet marked as complete. Updating state. Time taken: {time_taken}s"
            )
            score = score_game(difficulty, game_state['mistakes'], time_taken)
            record_game_score(get_jwt_identity(),
                              game_state['game_id'],
                              score,
                              game_state['mistakes'],
                              time_taken,
                              completed=True)
            game_state['game_complete'] = True
            game_state['hasWon'] = True  # Explicitly mark as won
            game_state[
                'win_notified'] = False  # Ensure this is set to False to trigger notification
            update_active_game_state(get_jwt_identity(), game_state)
            initialize_or_update_user_stats(get_jwt_identity())
            logger.debug(
                "Game state updated: game_complete=True, hasWon=True, win_notified=False"
            )
        else:
            logger.debug("Game already marked as complete.")

        logger.debug("Returning game status: game_complete=True, hasWon=True")
        return {'game_complete': True, 'hasWon': True}

    # Game is still in progress
    logger.debug(
        "Game still in progress. Returning: game_complete=False, hasWon=False")
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


@bp.route('/events')
def events():
    """SSE endpoint for real-time game updates with flexible authentication"""
    logger.info("SSE connection attempt received")
    print("events triggered")
    # Get token from either Authorization header or query parameter
    token = None

    # Try to get token from Authorization header first
    auth_header = request.headers.get('Authorization')
    if auth_header and auth_header.startswith('Bearer '):
        token = auth_header.split(' ')[1]
        logger.info("Using token from Authorization header")

    # If not in header, try query parameter (for standard EventSource)
    if not token:
        token = request.args.get('token')
        logger.info("Using token from query parameter")

    # Verify we have a token
    if not token:
        logger.error("No valid token found in request")
        return jsonify({"error": "Authentication required"}), 401

    try:
        # Verify token using JWT
        from flask_jwt_extended import decode_token
        from jwt.exceptions import PyJWTError

        try:
            # Decode the token
            decoded_token = decode_token(token)

            # Check if token is in blocklist (use your app's jwt_blocklist set)
            from app import jwt_blocklist
            jti = decoded_token['jti']
            if jti in jwt_blocklist:
                logger.error("Token has been revoked")
                return jsonify({"error": "Token has been revoked"}), 401

            user_id = decoded_token['sub']
            logger.info(f"SSE connection authenticated for user: {user_id}")

        except PyJWTError as e:
            logger.error(f"JWT error: {str(e)}")
            return jsonify({"error": "Invalid token"}), 401

    except Exception as e:
        logger.error(f"Error validating token: {str(e)}")
        return jsonify({"error": "Authentication error"}), 401

    def generate():
        """Generate SSE data stream for authenticated user"""
        # Client connection tracking
        client_id = str(uuid.uuid4())
        logger.info(f"New SSE connection: {client_id} for user: {user_id}")
        ping_interval = 15  # Send ping every 15 seconds to keep connection alive
        last_ping = time.time()

        try:
            # Send initial connection success event
            yield f"event: connected\ndata: {json.dumps({'user_id': user_id, 'client_id': client_id})}\n\n"
            logger.debug(
                f"Sent initial connection event to client {client_id}")

            while True:
                current_time = time.time()

                # Send periodic pings to keep connection alive
                if current_time - last_ping > ping_interval:
                    yield f"event: ping\ndata: {current_time}\n\n"
                    last_ping = current_time
                    logger.debug(f"Ping sent to client {client_id}")

                try:
                    # Get current game state
                    game_state = get_game_state(user_id)

                    if game_state:
                        logger.debug(
                            f"Game state for user {user_id}: game_complete={game_state.get('game_complete')}, win_notified={game_state.get('win_notified')}, mistakes={game_state.get('mistakes')}/{game_state.get('max_mistakes')}"
                        )

                        # Only send updates if there's meaningful state
                        # Prepare game state data
                        state_data = {
                            'type':
                            'game_state',
                            'game_id':
                            game_state.get('game_id'),
                            'mistakes':
                            game_state.get('mistakes', 0),
                            'completed':
                            game_state.get('game_complete', False),
                            'remaining_attempts':
                            (game_state.get('max_mistakes', 6) -
                             game_state.get('mistakes', 0)),
                            'timestamp':
                            int(current_time * 1000)
                        }

                        # Send game state update
                        logger.debug("Preparing to send gameState event")
response_data = f"event: gameState\ndata: {json.dumps(state_data)}\n\n"
logger.debug(f"Sending SSE data: {response_data}")
yield response_data
logger.debug("SSE data sent")
                        logger.debug(
                            f"Sent gameState event to client {client_id}")

                        # Check for win condition
                        win_condition_check = {
                            'game_complete':
                            game_state.get('game_complete', False),
                            'win_notified':
                            game_state.get('win_notified',
                                           True),  # Default to True if missing
                            'mistakes': game_state.get('mistakes', 0),
                            'max_mistakes': game_state.get('max_mistakes', 6),
                            'hasWon': game_state.get('hasWon', False)
                        }
                        logger.debug(
                            f"Win condition values for user {user_id}: {win_condition_check}"
                        )

                        win_condition = (
                            game_state.get('game_complete')
                            and not game_state.get('win_notified', False)
                            and game_state.get('mistakes', 0) < game_state.get(
                                'max_mistakes', 6)
                            and game_state.get(
                                'hasWon', False)  # Explicitly check for hasWon
                        )

                        logger.debug(
                            f"Win condition evaluation result: {win_condition}"
                        )

                        if win_condition:
                            logger.info(
                                f"Win condition met for user {user_id}. Preparing win notification."
                            )

                            # Get attribution data
                            attribution = get_attribution(
                                game_state.get('game_id', ''))
                            logger.debug(f"Got attribution: {attribution}")

                            # Calculate score
                            time_taken = (datetime.utcnow() - game_state.get(
                                'start_time',
                                datetime.utcnow())).total_seconds()
                            logger.debug(f"Time taken: {time_taken}s")

                            score = score_game(
                                game_state.get('difficulty', 'medium'),
                                game_state.get('mistakes', 0), time_taken)
                            logger.debug(f"Calculated score: {score}")

                            # Determine rating based on score
                            rating = get_rating_from_score(score)
                            logger.debug(f"Rating: {rating}")

                            # Mark as notified to prevent duplicate events
                            game_state['win_notified'] = True
                            save_game_state(user_id, game_state)
                            logger.debug(
                                "Set win_notified=True and saved game state")

                            win_data = {
                                'type': 'win',
                                'game_id': game_state.get('game_id'),
                                'score': score,
                                'mistakes': game_state.get('mistakes', 0),
                                'maxMistakes':
                                game_state.get('max_mistakes', 6),
                                'gameTimeSeconds': int(time_taken),
                                'rating': rating,
                                'timestamp': int(current_time * 1000),
                                'attribution': attribution
                            }
                            logger.debug(f"Win data prepared: {win_data}")

                            # Send win event twice to ensure delivery
                            yield f"event: gameWon\ndata: {json.dumps(win_data)}\n\n"
                            yield f"event: gameWon\ndata: {json.dumps(win_data)}\n\n"
                            logger.info(f"Win event sent to user {user_id}")

                            # Record score in leaderboard
                            try:
                                record_game_score(user_id,
                                                  game_state.get('game_id'),
                                                  score,
                                                  game_state.get('mistakes'),
                                                  time_taken,
                                                  completed=True)
                                logger.debug("Score recorded successfully")
                            except Exception as e:
                                logger.error(
                                    f"Error recording score: {str(e)}")
                    else:
                        logger.debug(
                            f"No active game state found for user {user_id}")

                    # Sleep to prevent CPU overuse
                    time.sleep(2)

                except Exception as e:
                    logger.error(f"Error in SSE data generation: {str(e)}")
                    yield f"event: error\ndata: {json.dumps({'message': str(e)})}\n\n"
                    time.sleep(5)  # Longer interval after error

        except GeneratorExit:
            logger.info(
                f"SSE connection closed for client {client_id}, user {user_id}"
            )
        except Exception as e:
            logger.error(f"SSE generator error: {str(e)}")
            yield f"event: error\ndata: {json.dumps({'message': 'Connection error'})}\n\n"

    # Set up response with appropriate headers
    response = Response(
        stream_with_context(generate()),
        mimetype='text/event-stream',
        headers={
            'Cache-Control': 'no-cache, no-transform',
            'Content-Type': 'text/event-stream',
            'Connection': 'keep-alive',
            'X-Accel-Buffering': 'no'  # Disable proxy buffering for Nginx
        })

    # Set CORS headers to allow cross-origin requests
    response.headers['Access-Control-Allow-Origin'] = '*'  # Or specific origin
    response.headers[
        'Access-Control-Allow-Headers'] = 'Authorization, Content-Type'
    response.headers['Access-Control-Allow-Methods'] = 'GET, OPTIONS'
    response.headers['Access-Control-Allow-Credentials'] = 'true'

    return response


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
