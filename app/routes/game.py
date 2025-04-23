from flask import Blueprint, jsonify, request, Response, stream_with_context, current_app
from flask_jwt_extended import jwt_required, get_jwt_identity, decode_token
from app.services.game_logic import start_game
from app.services.game_state import (get_unified_game_state,
                                     save_unified_game_state,
                                     check_game_status, get_display,
                                     process_guess, process_hint, abandon_game,
                                     get_attribution_from_quotes)
from app.models import db, ActiveGameState, AnonymousGameState, GameScore, UserStats, DailyCompletion, AnonymousGameScore
from app.services.game_state import get_max_mistakes_from_game_id
from datetime import datetime, date, timedelta
import logging
import uuid
import json
import time
from app.utils.stats import initialize_or_update_user_stats
from app.celery_worker import process_game_completion, verify_daily_streak

# Set up logging
logger = logging.getLogger(__name__)

bp = Blueprint('game', __name__)

game_creation_timestamps = {}
GAME_CREATION_COOLDOWN = 2  # 2 seconds cooldown


@bp.route('/start', methods=['GET', 'OPTIONS'])
@jwt_required(optional=True)
def start():
    """Start a new game"""
    if request.method == 'OPTIONS':
        return jsonify({}), 200

    try:
        # Get user identification
        user_id = get_jwt_identity()
        is_anonymous = user_id is None

        # For anonymous users, use IP address as identifier
        identifier = user_id if not is_anonymous else request.remote_addr

        # Check if we're creating games too quickly
        current_time = time.time()
        last_creation_time = game_creation_timestamps.get(identifier, 0)
        time_since_last_creation = current_time - last_creation_time

        if time_since_last_creation < GAME_CREATION_COOLDOWN:
            logger.warning(
                f"Game creation request rejected - cooldown period not elapsed for {'anonymous' if is_anonymous else user_id}"
            )
            return jsonify({
                "error":
                "Please wait a moment before starting a new game",
                "cooldown_remaining":
                round(GAME_CREATION_COOLDOWN - time_since_last_creation, 1)
            }), 429  # 429 Too Many Requests

        # Update the timestamp before proceeding
        game_creation_timestamps[identifier] = current_time

        # Extract longText parameter
        long_text = request.args.get('longText', 'false').lower() == 'true'

        # For authenticated users, check and clean up any existing active games
        if not is_anonymous:
            try:
                # Only find and abandon regular (non-daily) games
                active_game = ActiveGameState.query.filter(
                    ActiveGameState.user_id == user_id,
                    ~ActiveGameState.game_id.like(
                        '%daily%')  # Only regular games
                ).first()

                if active_game:
                    logger.info(
                        f"Found existing regular game for user {user_id} - abandoning"
                    )

                    # Record the abandoned game
                    game_score = GameScore(
                        user_id=user_id,
                        game_id=active_game.game_id,
                        score=0,  # Zero score for abandoned games
                        mistakes=active_game.mistakes,
                        time_taken=int(
                            (datetime.utcnow() -
                             active_game.created_at).total_seconds()),
                        game_type='regular',
                        challenge_date=datetime.utcnow().strftime('%Y-%m-%d'),
                        completed=False,  # Mark as incomplete
                        created_at=datetime.utcnow())

                    # Add game score and delete active game
                    db.session.add(game_score)
                    db.session.delete(active_game)
                    db.session.commit()

                    # Update stats for this abandoned game
                    from app.utils.stats import initialize_or_update_user_stats
                    initialize_or_update_user_stats(user_id)

                    logger.info(
                        f"Successfully abandoned regular game for user {user_id}"
                    )
            except Exception as abandon_err:
                logger.error(
                    f"Error abandoning existing game for user {user_id}: {str(abandon_err)}"
                )
                # Continue with new game creation anyway
                db.session.rollback()

        # Get difficulty from query params
        frontend_difficulty = request.args.get('difficulty', 'medium')

        backend_difficulty = frontend_difficulty  #find cleaner way to do this later
        print("backend difficulty on start: ", backend_difficulty)
        # Generate the game ID
        # Extract hardcore mode from query params
        hardcore_mode = request.args.get('hardcore', 'false').lower() == 'true'
        hardcore_flag = 'hardcore-' if hardcore_mode else ''
        print("hardcore mode on start: ", hardcore_mode, hardcore_flag)
        game_id = f"{backend_difficulty}-{hardcore_flag}{str(uuid.uuid4())}"

        # For authenticated users, check for active games
        active_game_info = {"has_active_game": False}
        if not is_anonymous:
            active_game = get_unified_game_state(user_id, is_anonymous=False)
            if active_game:
                # Calculate completion percentage
                encrypted_letters = set(
                    c for c in active_game['encrypted_paragraph']
                    if c.isalpha())
                completion_percentage = (
                    len(active_game['correctly_guessed']) /
                    len(encrypted_letters) * 100) if encrypted_letters else 0

                # Build active game info
                active_game_info = {
                    "has_active_game":
                    True,
                    "game_id":
                    active_game['game_id'],
                    "difficulty":
                    active_game['difficulty'],
                    "mistakes":
                    active_game['mistakes'],
                    "completion_percentage":
                    round(completion_percentage, 1),
                    "time_spent":
                    int((datetime.utcnow() -
                         active_game['start_time']).total_seconds()),
                    "max_mistakes":
                    active_game['max_mistakes']
                }

        logger.debug(
            f"Starting new game for {'anonymous' if is_anonymous else user_id} with difficulty: {backend_difficulty}"
        )

        # Start a new game and get game data
        game_data = start_game(long_text=long_text)
        game_state = game_data['game_state']

        # Add additional info to game state
        game_state['game_id'] = game_id
        game_state['difficulty'] = backend_difficulty
        game_state['start_time'] = datetime.utcnow()
        game_state['game_complete'] = False
        game_state['has_won'] = False
        game_state['hardcore_mode'] = hardcore_mode

        # Generate identifier for storage
        identifier = game_id + "_anon" if is_anonymous else f"{user_id}_{game_id}"

        # Save game state using unified function
        save_unified_game_state(identifier,
                                game_state,
                                is_anonymous=is_anonymous)

        # Check game status for consistency
        status = check_game_status(game_state)

        # Create response data
        response_data = {
            "display": game_data['display'],
            "encrypted_paragraph": game_data['encrypted_paragraph'],
            "game_id": game_id,
            "letter_frequency": game_data['letter_frequency'],
            "mistakes": game_data['mistakes'],
            "original_letters": game_data['original_letters'],
            "game_complete": status['game_complete'],
            "hasWon": status['has_won'],
            "max_mistakes": game_state['max_mistakes'],
            "difficulty": frontend_difficulty,
            "is_anonymous": is_anonymous
        }

        # Add active game info for authenticated users
        if not is_anonymous:
            response_data["active_game_info"] = active_game_info
            from app.celery_worker import verify_daily_streak
            verify_daily_streak.delay(user_id)

        return jsonify(response_data), 200
    except Exception as e:
        logger.error(f"Error starting game: {str(e)}", exc_info=True)
        return jsonify({"error": "Failed to start game"}), 500


@bp.route('/guess', methods=['POST', 'OPTIONS'])
@jwt_required(optional=True)
def guess():
    """Process a letter guess"""
    if request.method == 'OPTIONS':
        return jsonify({}), 200

    try:
        # Get user identification
        user_id = get_jwt_identity()
        is_anonymous = user_id is None

        # Get request data
        data = request.get_json()
        encrypted_letter = data.get('encrypted_letter')
        guessed_letter = data.get('guessed_letter')
        game_id = data.get('game_id')
        is_daily = 'daily' in game_id if game_id else False

        if not encrypted_letter or not guessed_letter:
            return jsonify({"error": "Missing required fields"}), 400

        logger.debug(
            f"Guess from {'anonymous' if is_anonymous else user_id}: {encrypted_letter} -> {guessed_letter}"
        )

        # Get identifier based on user type
        identifier = f"{game_id}_anon" if is_anonymous else f"{user_id}_{game_id}"

        # Get current game state
        game_state = get_unified_game_state(identifier,
                                            is_anonymous=is_anonymous)
        if not game_state:
            logger.error(
                f"No active game found for {'anonymous' if is_anonymous else 'user'}: {identifier}"
            )
            return jsonify({"error": "No active game"}), 400

        # Process the guess
        result = process_guess(game_state, encrypted_letter, guessed_letter)
        if not result['valid']:
            return jsonify({"error": result['message']}), 400

        # Save updated game state
        save_unified_game_state(identifier,
                                result['game_state'],
                                is_anonymous=is_anonymous)

        # Check if game is complete
        if result['complete']:
            # Handle game completion using the helper function
            response_data, status_code = handle_game_completion(
                result, 
                game_state, 
                user_id, 
                identifier, 
                game_id, 
                is_anonymous, 
                is_daily
            )
            return jsonify(response_data), status_code

        # Return normal response for incomplete games
        return jsonify({
            'display': result['display'],
            'mistakes': result['game_state']['mistakes'],
            'correctly_guessed': result['game_state']['correctly_guessed'],
            'incorrect_guesses': result['game_state']['incorrect_guesses'],
            'game_complete': result['complete'],
            'hasWon': result['has_won'],
            'is_correct': result['is_correct'],
            'max_mistakes': result['game_state']['max_mistakes']
        }), 200
    except Exception as e:
        logger.error(f"Error processing guess: {str(e)}", exc_info=True)
        db.session.rollback()
        return jsonify({"error": "Error processing guess"}), 500


def get_quote_id_for_date(challenge_date):
    """Helper function to get quote ID for a specific date"""
    from app.models import Quote
    quote = Quote.query.filter_by(daily_date=challenge_date).first()
    return quote.id if quote else None


def extract_challenge_date(game_id, is_daily):
    """Extract the challenge date from a game ID"""
    if not is_daily:
        return datetime.utcnow().date()

    try:
        # Format in game_id is typically: "difficulty-daily-YYYY-MM-DD-uuid"
        parts = game_id.split('-')
        if len(parts) >= 5:
            challenge_date_str = f"{parts[2]}-{parts[3]}-{parts[4]}"
            return datetime.strptime(challenge_date_str, '%Y-%m-%d').date()
        else:
            # Fallback to today's date
            return datetime.utcnow().date()
    except (ValueError, IndexError) as e:
        logger.error(f"Error parsing date from game_id: {str(e)}")
        return datetime.utcnow().date()


@bp.route('/hint', methods=['POST', 'OPTIONS'])
@jwt_required(optional=True)
def hint():
    """Get a hint"""
    if request.method == 'OPTIONS':
        return jsonify({}), 200

    try:
        # Get user identification
        user_id = get_jwt_identity()
        is_anonymous = user_id is None

        # Get request data
        data = request.get_json()
        game_id = data.get('game_id')
        is_daily = 'daily' in game_id if game_id else False
        logger.debug(
            f"Hint requested by {'anonymous' if is_anonymous else user_id}")

        # Get identifier based on user type
        identifier = f"{game_id}_anon" if is_anonymous else f"{user_id}_{game_id}"

        # Get current game state
        game_state = get_unified_game_state(identifier,
                                            is_anonymous=is_anonymous)
        if not game_state:
            logger.error(
                f"No active game found for {'anonymous' if is_anonymous else 'user'}: {identifier}"
            )
            return jsonify({"error": "No active game"}), 400

        # Process the hint
        result = process_hint(game_state)
        if not result['valid']:
            return jsonify({"error": result['message']}), 400

        # Save updated game state
        save_unified_game_state(identifier,
                                result['game_state'],
                                is_anonymous=is_anonymous)

        # Check if game is complete
        if result['complete']:
            # Handle game completion using the helper function
            response_data, status_code = handle_game_completion(
                result, 
                game_state, 
                user_id, 
                identifier, 
                game_id, 
                is_anonymous, 
                is_daily
            )
            return jsonify(response_data), status_code

        # Return normal response for incomplete games
        return jsonify({
            'display': result['display'],
            'mistakes': result['game_state']['mistakes'],
            'correctly_guessed': result['game_state']['correctly_guessed'],
            'incorrect_guesses': result['game_state']['incorrect_guesses'],
            'game_complete': result['complete'],
            'hasWon': result['has_won'],
            'is_correct': True,
            'max_mistakes': result['game_state']['max_mistakes']
        }), 200
    except Exception as e:
        logger.error(f"Error processing hint: {str(e)}", exc_info=True)
        db.session.rollback()
        return jsonify({"error": "Error processing hint"}), 500


@bp.route('/check-active-game', methods=['GET', 'OPTIONS'])
@jwt_required()
def check_active_game():
    """Check if user has an active game and/or daily game"""
    if request.method == 'OPTIONS':
        return jsonify({}), 200

    try:
        user_id = get_jwt_identity()

        # Check for regular game (excluding daily games)
        regular_game = ActiveGameState.query.filter(
            ActiveGameState.user_id == user_id,
            ~ActiveGameState.game_id.like('%daily%')).first()

        game_state = get_unified_game_state(
            f"{user_id}_{regular_game.game_id}",
            is_anonymous=False) if regular_game else None

        response = {"has_active_game": False, "has_active_daily_game": False}

        if game_state:
            # Calculate regular game stats
            encrypted_letters = set(c
                                    for c in game_state['encrypted_paragraph']
                                    if c.isalpha())
            completion_percentage = (len(game_state['correctly_guessed']) /
                                     len(encrypted_letters) *
                                     100) if encrypted_letters else 0

            time_spent = int(
                (datetime.utcnow() - game_state['start_time']).total_seconds())

            response.update({
                "has_active_game": True,
                "game_stats": {
                    "difficulty": game_state['difficulty'],
                    "mistakes": game_state['mistakes'],
                    "completion_percentage": round(completion_percentage, 1),
                    "time_spent": time_spent,
                    "max_mistakes": game_state['max_mistakes']
                }
            })

        # Check for daily game - use game_id with daily in the query
        daily_game = ActiveGameState.query.filter(
            ActiveGameState.user_id == user_id,
            ActiveGameState.game_id.like('%daily%')).first()

        if daily_game:
            # Calculate daily game stats
            daily_state = get_unified_game_state(
                f"{user_id}_{daily_game.game_id}", is_anonymous=False)
            if daily_state:
                encrypted_letters = set(
                    c for c in daily_state['encrypted_paragraph']
                    if c.isalpha())
                completion_percentage = (
                    len(daily_state['correctly_guessed']) /
                    len(encrypted_letters) * 100) if encrypted_letters else 0

                time_spent = int((datetime.utcnow() -
                                  daily_state['start_time']).total_seconds())

                response.update({
                    "has_active_daily_game": True,
                    "daily_stats": {
                        "difficulty": daily_state['difficulty'],
                        "mistakes": daily_state['mistakes'],
                        "completion_percentage": round(completion_percentage,
                                                       1),
                        "time_spent": time_spent,
                        "max_mistakes": daily_state['max_mistakes'],
                        "start_time": daily_state['start_time']
                    }
                })
        print(response)
        return jsonify(response), 200
    except Exception as e:
        logger.error(f"Error checking active game: {str(e)}", exc_info=True)
        return jsonify({"error": "Error checking active game"}), 500


@bp.route('/continue-game', methods=['GET', 'OPTIONS'])
@jwt_required()
def continue_game():
    """Return full game state for continuing"""
    if request.method == 'OPTIONS':
        return jsonify({}), 200

    try:
        user_id = get_jwt_identity()
        is_daily = request.args.get('isDaily', 'false').lower() == 'true'

        # Get active game state based on game type
        if is_daily:
            # Find daily game ID first
            daily_game = ActiveGameState.query.filter(
                ActiveGameState.user_id == user_id,
                ActiveGameState.game_id.like('%daily%')).first()

            if daily_game:
                game_state = get_unified_game_state(
                    f"{user_id}_{daily_game.game_id}", is_anonymous=False)
            else:
                game_state = None
        else:
            # Get non-daily game
            regular_game = ActiveGameState.query.filter(
                ActiveGameState.user_id == user_id,
                ~ActiveGameState.game_id.like('%daily%')).first()
            game_state = get_unified_game_state(
                f"{user_id}_{regular_game.game_id}", is_anonymous=False)

        if not game_state:
            return jsonify({"error": "No active game found"}), 404

        # Generate original letters
        original_letters = sorted(
            set(''.join(x for x in game_state['original_paragraph'].upper()
                        if x.isalpha())))

        # Generate display
        display = get_display(game_state['encrypted_paragraph'],
                              game_state['correctly_guessed'],
                              game_state['reverse_mapping'])

        # Map encrypted correctly guessed letters to original letters
        display_guessed = [
            game_state['reverse_mapping'][letter]
            for letter in game_state['correctly_guessed']
        ]

        # Generate letter frequency
        letter_frequency = {
            letter: game_state['encrypted_paragraph'].count(letter)
            for letter in set(game_state['encrypted_paragraph'])
            if letter.isalpha()
        }

        ret = {
            "display": display,
            "encrypted_paragraph": game_state['encrypted_paragraph'],
            "game_id": game_state['game_id'],
            "letter_frequency": letter_frequency,
            "mistakes": game_state['mistakes'],
            "correctly_guessed": game_state['correctly_guessed'],
            "incorrect_guesses": game_state.get('incorrect_guesses',
                                                {}),  # Add this line
            "game_complete": game_state['game_complete'],
            "hasWon": game_state['has_won'],
            "max_mistakes": game_state['max_mistakes'],
            "difficulty": game_state['difficulty'],
            "original_letters": original_letters,
            "reverse_mapping": game_state['reverse_mapping'],
            "guessed_letters": display_guessed
        }
        print(ret)
        if not is_anonymous:
            response_data["active_game_info"] = active_game_info
            from app.celery_worker import verify_daily_streak
            verify_daily_streak.delay(user_id)
        return jsonify(ret), 200
    except Exception as e:
        logger.error(f"Error continuing game: {str(e)}", exc_info=True)
        return jsonify({"error": "Error continuing game"}), 500


@bp.route('/abandon-game', methods=['DELETE', 'OPTIONS'])
@jwt_required(optional=True)
def abandon_game_route():
    """Abandon current game and record it as incomplete"""
    if request.method == 'OPTIONS':
        return jsonify({}), 200

    try:
        # Get user identification
        user_id = get_jwt_identity()
        is_anonymous = user_id is None

        # Get game ID from query parameters
        game_id = request.args.get('game_id')
        is_daily = request.args.get('isDaily', 'false').lower() == 'true'

        if not game_id:
            return jsonify({"error": "Game ID is required"}), 400

        # Process based on user type
        if is_anonymous:
            # Handle anonymous user
            anon_id = f"{game_id}_anon"

            # Get the game state to record time spent
            game_state = get_unified_game_state(anon_id, is_anonymous=True)

            if not game_state:
                return jsonify({"error": "No active game found"}), 404

            # Record abandoned anonymous game
            time_taken = int((datetime.utcnow() - game_state.get(
                'start_time', datetime.utcnow())).total_seconds())

            anon_game_score = AnonymousGameScore(
                anon_id=anon_id,
                game_id=game_id,
                score=0,  # Zero score for abandoned games
                mistakes=game_state.get('mistakes', 0),
                time_taken=time_taken,
                game_type='daily' if is_daily else 'regular',
                difficulty=game_state.get('difficulty', 'medium'),
                completed=False,
                won=False,
                created_at=datetime.utcnow())
            db.session.add(anon_game_score)

            # Clean up the active game state
            anon_game = AnonymousGameState.query.filter_by(
                anon_id=anon_id).first()
            if anon_game:
                db.session.delete(anon_game)

            db.session.commit()
            logger.info(f"Anonymous game {anon_id} abandoned")

        else:
            # Handle authenticated user
            active_game = ActiveGameState.query.filter_by(
                user_id=user_id, game_id=game_id).first()

            if not active_game:
                return jsonify({"error": "No active game found"}), 404

            # Record abandoned game
            time_taken = int(
                (datetime.utcnow() - active_game.created_at).total_seconds())
            if active_game.mistakes > 0 or len(active_game.correctly_guessed) > 0:
                game_score = GameScore(
                    user_id=user_id,
                    game_id=game_id,
                    score=0,  # Zero score for abandoned games
                    mistakes=active_game.mistakes,
                    time_taken=time_taken,
                    game_type='daily' if is_daily else 'regular',
                    challenge_date=datetime.utcnow().strftime('%Y-%m-%d'),
                    completed=False,  # Mark as incomplete
                    created_at=datetime.utcnow())
                db.session.add(game_score)

            # Delete the active game
            db.session.delete(active_game)

            # Update user stats
            from app.utils.stats import initialize_or_update_user_stats
            initialize_or_update_user_stats(user_id, game_score)

            db.session.commit()
            logger.info(f"Game {game_id} abandoned by user {user_id}")

        return jsonify({"message": "Game abandoned successfully"}), 200
    except Exception as e:
        logger.error(f"Error abandoning game: {str(e)}", exc_info=True)
        db.session.rollback()
        return jsonify({"error": "Error abandoning game"}), 500


def update_streak(user_id, challenge_date, is_daily):
    """Update user's daily streak and return current streak value"""
    user_stats = UserStats.query.filter_by(user_id=user_id).first()

    if not user_stats:
        # Create user stats if they don't exist
        user_stats = UserStats(user_id=user_id)
        db.session.add(user_stats)
        db.session.commit()
        return 1  # First completion = streak of 1

    # For non-daily games, just return the current streak without updating it
    if not is_daily:
        return user_stats.current_daily_streak or 0

    # If this is their first completion
    if not user_stats.last_daily_completed_date:
        user_stats.current_daily_streak = 1
        user_stats.max_daily_streak = 1
        user_stats.total_daily_completed = 1
        user_stats.last_daily_completed_date = challenge_date
    else:
        # Check if this completion continues the streak
        last_date = user_stats.last_daily_completed_date
        delta = (challenge_date - last_date).days

        # Check if this is a one-day advancement (continuing streak)
        if delta == 1:
            user_stats.current_daily_streak += 1
            # Update max streak if current is now higher
            if user_stats.current_daily_streak > user_stats.max_daily_streak:
                user_stats.max_daily_streak = user_stats.current_daily_streak
        # If same day completion (shouldn't happen but handle it)
        elif delta == 0:
            # No change to streak
            pass
        # If streak is broken
        else:
            # Reset streak to 1 for this new completion
            user_stats.current_daily_streak = 1

        # Update total completed and last date
        user_stats.total_daily_completed += 1
        user_stats.last_daily_completed_date = challenge_date

    # Commit the streak update
    db.session.commit()
    return user_stats.current_daily_streak


def generate_win_data(game_state, time_taken, current_daily_streak):
    """Generate the win data including score calculation"""
    from app.utils.scoring import score_game

    # Extract game parameters
    difficulty = game_state.get('difficulty', 'medium')
    mistakes = game_state.get('mistakes', 0)
    hardcore_mode = game_state.get('hardcore_mode', False)

    # Calculate score
    score = score_game(difficulty,
                       mistakes,
                       time_taken,
                       hardcore_mode=hardcore_mode,
                       current_daily_streak=current_daily_streak)

    # Use attribution from game state
    attribution = {
        'major_attribution': game_state.get('major_attribution', 'Unknown'),
        'minor_attribution': game_state.get('minor_attribution', '')
    }

    # Return complete win data object
    return {
        'score': score,
        'mistakes': mistakes,
        'maxMistakes': game_state.get('max_mistakes', 5),
        'gameTimeSeconds': time_taken,
        'attribution': attribution,
        'current_daily_streak': current_daily_streak
    }


def record_game_score(user_id, game_id, score, mistakes, time_taken, is_daily):
    """Record a game score to the database"""
    game_score = GameScore(
        user_id=user_id,
        game_id=game_id,
        score=score,
        mistakes=mistakes,
        time_taken=time_taken,
        game_type='daily' if is_daily else 'regular',
        challenge_date=datetime.utcnow().strftime('%Y-%m-%d'),
        completed=True,
        created_at=datetime.utcnow())

    db.session.add(game_score)
    logger.info(f"Game score recorded for user {user_id}, score: {score}")
    return game_score


def record_daily_completion(user_id, challenge_date, score, mistakes,
                            time_taken):
    """Record a daily challenge completion"""
    from app.models import Quote, DailyCompletion

    # Find the quote for this date
    daily_quote = Quote.query.filter_by(daily_date=challenge_date).first()

    if not daily_quote:
        logger.error(f"No daily quote found for date {challenge_date}")
        return None

    logger.info(f"Found daily quote for {challenge_date}: ID {daily_quote.id}")

    # Create completion record
    completion = DailyCompletion(user_id=user_id,
                                 quote_id=daily_quote.id,
                                 challenge_date=challenge_date,
                                 completed_at=datetime.utcnow(),
                                 score=score,
                                 mistakes=mistakes,
                                 time_taken=time_taken)

    db.session.add(completion)
    logger.info(
        f"Daily completion recorded for user {user_id}, date {challenge_date}")
    return completion


@bp.route('/game-complete', methods=['GET', 'OPTIONS'])
@jwt_required(optional=True)
def game_complete():
    """Return the completed game details for a specific game"""
    if request.method == 'OPTIONS':
        return jsonify({}), 200

    try:
        # Get user identification
        user_id = get_jwt_identity()
        is_anonymous = user_id is None

        # For both user types, we need the game_id
        game_id = request.args.get('game_id')
        if not game_id:
            return jsonify({"error": "Game ID required"}), 400

        # Check if the game has already been recorded as complete
        if is_anonymous:
            anon_id = f"{game_id}_anon"
            completed_game = AnonymousGameScore.query.filter_by(
                anon_id=anon_id).first()
        else:
            completed_game = GameScore.query.filter_by(
                user_id=user_id, game_id=game_id).first()

        # If we found a completed game record, return it
        if completed_game:
            # Get attribution info
            attribution = {}
            if hasattr(completed_game,
                       'game_type') and completed_game.game_type == 'daily':
                # Try to get attribution from daily challenge
                challenge_date = extract_challenge_date(game_id, True)
                from app.models import Quote
                quote = Quote.query.filter_by(
                    daily_date=challenge_date).first()
                if quote:
                    attribution = {
                        'major_attribution': quote.author,
                        'minor_attribution': quote.minor_attribution or ''
                    }

            # Build response based on user type
            if is_anonymous:
                win_data = {
                    'score': completed_game.score,
                    'mistakes': completed_game.mistakes,
                    'maxMistakes': get_max_mistakes_from_game_id(game_id),
                    'gameTimeSeconds': completed_game.time_taken,
                    'attribution': attribution,
                    'difficulty': completed_game.difficulty
                }

                return jsonify({
                    "hasActiveGame":
                    False,
                    "gameComplete":
                    True,
                    "hasWon":
                    completed_game.won,
                    "winData":
                    win_data if completed_game.won else None
                }), 200
            else:
                # For authenticated users, include streak info
                user_stats = UserStats.query.filter_by(user_id=user_id).first()
                current_streak = get_current_daily_streak(user_id)

                win_data = {
                    'score':
                    completed_game.score,
                    'mistakes':
                    completed_game.mistakes,
                    'maxMistakes':
                    get_max_mistakes_from_game_id(game_id),
                    'gameTimeSeconds':
                    completed_game.time_taken,
                    'attribution':
                    attribution,
                    'current_daily_streak':
                    current_streak 
                }

                return jsonify({
                    "hasActiveGame":
                    False,
                    "gameComplete":
                    True,
                    "hasWon":
                    completed_game.score > 0,  # Wins have positive scores
                    "winData":
                    win_data if completed_game.score > 0 else None
                }), 200

        # If no completed game was found, check if there's an active game
        # Get identifier based on user type
        identifier = f"{game_id}_anon" if is_anonymous else f"{user_id}_{game_id}"

        # Check for active game state
        game_state = get_unified_game_state(identifier,
                                            is_anonymous=is_anonymous)

        if game_state:
            # Game exists but isn't complete yet
            return jsonify({
                "hasActiveGame":
                True,
                "gameComplete":
                game_state.get('game_complete', False),
                "hasWon":
                game_state.get('has_won', False),
                "mistakes":
                game_state.get('mistakes', 0),
                "maxMistakes":
                game_state.get('max_mistakes', 5)
            }), 200
        else:
            # No active or completed game found
            return jsonify({
                "hasActiveGame": False,
                "gameComplete": False,
                "error": "Game not found"
            }), 404

    except Exception as e:
        logger.error(f"Error getting game completion status: {str(e)}",
                     exc_info=True)
        return jsonify({"error": "Error retrieving game status"}), 500


def get_current_daily_streak(user_id):
    """
    Calculate the user's current daily streak, considering today's challenge as still valid

    A streak is considered active if either:
    1. The user completed yesterday's challenge (and potentially today's)
    2. The user completed today's challenge
    3. The user has a consistent streak and just hasn't completed today's yet

    Args:
        user_id (str): User ID to check streak for

    Returns:
        int: The current streak count
    """
    try:
        from app.models import UserStats, DailyCompletion

        # Get the user's stats
        user_stats = UserStats.query.filter_by(user_id=user_id).first()
        if not user_stats:
            return 0

        # If they don't have any completions yet, they have no streak
        if not user_stats.last_daily_completed_date:
            return 0

        # Get today's date and yesterday's date
        today = datetime.utcnow().date()
        yesterday = today - timedelta(days=1)
        # If they already did today's challenge, return the current streak
        # (this should already be up to date)
        if user_stats.last_daily_completed_date == today:
            return user_stats.current_daily_streak

        # If they did yesterday's challenge, their streak is still active
        # even if they haven't done today's challenge yet
        if user_stats.last_daily_completed_date == yesterday:
            return user_stats.current_daily_streak
        # If their last completion was before yesterday, check if they missed any days
        # Get all completions in reverse chronological order
        completions = DailyCompletion.query.filter_by(user_id=user_id)\
                                          .order_by(DailyCompletion.challenge_date.desc())\
                                          .all()

        if not completions:
            return 0

        # Get the dates of their most recent completions
        completion_dates = [c.challenge_date for c in completions]
        # Start with their last completion
        last_date = completion_dates[0]
        current_streak = 1

        # If last completion is neither today nor yesterday, streak is broken
        if last_date < yesterday:
            return 0

        # Count consecutive days backward from last completion
        for i in range(1, len(completion_dates)):
            if (completion_dates[i - 1] - completion_dates[i]).days == 1:
                current_streak += 1
            else:
                break
        return current_streak

    except Exception as e:
        logger.error(f"Error calculating daily streak: {str(e)}")
        return 0  # Default to 0 on error

def handle_game_completion(result, game_state, user_id, identifier, game_id, is_anonymous, is_daily):
    """
    Handle the common logic for game completion in both guess and hint endpoints.

    Args:
        result (dict): Result from process_guess or process_hint
        game_state (dict): Current game state
        user_id (str): User ID for authenticated users, None for anonymous
        identifier (str): Identifier used for game state storage
        game_id (str): Game ID
        is_anonymous (bool): Whether the user is anonymous
        is_daily (bool): Whether this is a daily challenge

    Returns:
        tuple: Response data dict and HTTP status code
    """
    # Get basic daily streak info for UI (without saving to DB yet)
    streak_info = None
    if not is_anonymous and result['has_won']:
        my_increment = 1 if is_daily else 0
        current_streak = get_current_daily_streak(user_id)
        streak_info = {
            'current_streak': current_streak + my_increment,  # +1 for visual feedback
            'streak_continued': True
        }
    elif not is_anonymous and not result['has_won']:
        streak_info = {
            'current_streak': 0,
            'streak_continued': False
        }

    score = 0
    time_taken = int((datetime.utcnow() - game_state.get(
        'start_time', datetime.utcnow())).total_seconds())

    # Prepare response data
    response_data = {
        'display': result['display'],
        'mistakes': result['game_state']['mistakes'],
        'correctly_guessed': result['game_state']['correctly_guessed'],
        'incorrect_guesses': result['game_state']['incorrect_guesses'],
        'game_complete': result['complete'],
        'hasWon': result['has_won'],
        'is_correct': result.get('is_correct', True),  # Default to True for hint
        'max_mistakes': result['game_state']['max_mistakes']
    }

    if result['has_won']:
        from app.utils.scoring import score_game
        difficulty = game_state.get('difficulty', 'medium')
        mistakes = game_state.get('mistakes', 0)
        hardcore_mode = game_state.get('hardcore_mode', False)

        # For authenticated users with daily challenges, get streak
        current_daily_streak = 0
        if not is_anonymous:
            current_daily_streak = get_current_daily_streak(user_id)

        score = score_game(difficulty,
                          mistakes,
                          time_taken,
                          hardcore_mode=hardcore_mode,
                          current_daily_streak=current_daily_streak)

        # Add win data to the response
        response_data['winData'] = {
            'score': score,
            'mistakes': game_state.get('mistakes', 0),
            'maxMistakes': game_state.get('max_mistakes', 5),
            'gameTimeSeconds': time_taken,
            'attribution': {
                'major_attribution': game_state.get('major_attribution', 'Unknown'),
                'minor_attribution': game_state.get('minor_attribution', '')
            }
        }

        # Add streak info for authenticated users on daily challenges
        if not is_anonymous and streak_info:
            response_data['winData']['current_daily_streak'] = streak_info['current_streak']

    # Queue the async task for database updates
    process_game_completion.delay(
        user_id=user_id if not is_anonymous else None,
        anon_id=identifier if is_anonymous else None,
        game_id=game_id,
        is_daily=is_daily,
        won=result['has_won'],
        score=score,
        mistakes=game_state.get('mistakes', 0),
        time_taken=time_taken
    )

    # Return response data and status code
    return response_data, 200