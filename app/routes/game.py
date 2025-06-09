from flask import Blueprint, jsonify, request, Response, stream_with_context, current_app
from flask_jwt_extended import jwt_required, get_jwt_identity, decode_token
from app.services.game_logic import start_game
from app.services.game_state import (get_unified_game_state,
                                     save_unified_game_state,
                                     check_game_status, get_display,
                                     process_guess, process_hint, abandon_game,
                                     get_attribution_from_quotes)
from app.models import db, ActiveGameState, AnonymousGameState, GameScore, UserStats, DailyCompletion, AnonymousGameScore, User, Quote, Promo, PromoRedemption
from app.services.game_state import get_max_mistakes_from_game_id
from datetime import datetime, date, timedelta
import logging
import uuid
import json
import time
from sqlalchemy import and_, or_
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
        # Check for backdoor mode
        use_backdoor = request.args.get('backdoor', 'false').lower() == 'true'
        print("use_backdoor: ", use_backdoor)
        # If backdoor mode is requested, check user permissions
        if use_backdoor:
            # Check if user is authenticated and has subadmin privileges
            if is_anonymous:
                return jsonify(
                    {"error":
                     "Authentication required for backdoor mode"}), 403

            # Verify user is a subadmin
            user = User.query.filter_by(user_id=user_id).first()
            if not user or not user.subadmin:
                return jsonify(
                    {"error":
                     "Insufficient permissions for backdoor mode"}), 403
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
        game_data = start_game(long_text=long_text, is_backdoor=use_backdoor)
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
                result, game_state, user_id, identifier, game_id, is_anonymous,
                is_daily)
            return jsonify(response_data), status_code

        # Return normal response for incomplete games
        return jsonify({
            'display':
            result['display'],
            'mistakes':
            result['game_state']['mistakes'],
            'correctly_guessed':
            result['game_state']['correctly_guessed'],
            'incorrect_guesses':
            result['game_state']['incorrect_guesses'],
            'game_complete':
            result['complete'],
            'hasWon':
            result['has_won'],
            'is_correct':
            result['is_correct'],
            'max_mistakes':
            result['game_state']['max_mistakes']
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
                result, game_state, user_id, identifier, game_id, is_anonymous,
                is_daily)
            return jsonify(response_data), status_code

        # Return normal response for incomplete games
        return jsonify({
            'display':
            result['display'],
            'mistakes':
            result['game_state']['mistakes'],
            'correctly_guessed':
            result['game_state']['correctly_guessed'],
            'incorrect_guesses':
            result['game_state']['incorrect_guesses'],
            'game_complete':
            result['complete'],
            'hasWon':
            result['has_won'],
            'is_correct':
            True,
            'max_mistakes':
            result['game_state']['max_mistakes']
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
            if active_game.mistakes > 0 or len(
                    active_game.correctly_guessed) > 0:
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
                    'score': completed_game.score,
                    'mistakes': completed_game.mistakes,
                    'maxMistakes': get_max_mistakes_from_game_id(game_id),
                    'gameTimeSeconds': completed_game.time_taken,
                    'attribution': attribution,
                    'current_daily_streak': current_streak
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


def handle_game_completion(result, game_state, user_id, identifier, game_id,
                           is_anonymous, is_daily):
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
            'current_streak':
            current_streak + my_increment,  # +1 for visual feedback
            'streak_continued': True
        }
    elif not is_anonymous and not result['has_won']:
        streak_info = {'current_streak': 0, 'streak_continued': False}

    score = 0
    time_taken = int(
        (datetime.utcnow() -
         game_state.get('start_time', datetime.utcnow())).total_seconds())

    # Prepare response data
    response_data = {
        'display': result['display'],
        'mistakes': result['game_state']['mistakes'],
        'correctly_guessed': result['game_state']['correctly_guessed'],
        'incorrect_guesses': result['game_state']['incorrect_guesses'],
        'game_complete': result['complete'],
        'hasWon': result['has_won'],
        'is_correct': result.get('is_correct',
                                 True),  # Default to True for hint
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
                'major_attribution': game_state.get('major_attribution',
                                                    'Unknown'),
                'minor_attribution': game_state.get('minor_attribution', '')
            }
        }

        # Add streak info for authenticated users on daily challenges
        if not is_anonymous and streak_info:
            response_data['winData']['current_daily_streak'] = streak_info[
                'current_streak']

    # Queue the async task for database updates
    process_game_completion.delay(
        user_id=user_id if not is_anonymous else None,
        anon_id=identifier if is_anonymous else None,
        game_id=game_id,
        is_daily=is_daily,
        won=result['has_won'],
        score=score,
        mistakes=game_state.get('mistakes', 0),
        time_taken=time_taken)

    # Return response data and status code
    return response_data, 200


@bp.route('/get_daily', methods=['GET'])
@jwt_required()
def get_daily_quote():
    try:
        today = datetime.utcnow().date()

        # Find quote for today
        daily_quote = Quote.query.filter_by(daily_date=today,
                                            active=True).first()

        if not daily_quote:
            return jsonify({"error":
                            "No daily quote available for today"}), 404

        # Format the response
        response = {
            "id": daily_quote.id,
            "text": daily_quote.text,
            "author": daily_quote.author,
            "minor_attribution": daily_quote.minor_attribution,
            "difficulty": daily_quote.difficulty,
            "date": daily_quote.daily_date.isoformat(),
            "unique_letters": daily_quote.unique_letters
        }

        # Record that user has seen this daily quote (optional)
        # user_id = get_jwt_identity()
        # existing_completion = DailyCompletion.query.filter_by(
        #     user_id=user_id, quote_id=daily_quote.id).first()

        # if not existing_completion:
        #     # Record that user has seen this, but not completed it yet
        #     completion = DailyCompletion(user_id=user_id,
        #                                  quote_id=daily_quote.id,
        #                                  challenge_date=datetime.utcnow(),
        #                                  completed=False)
        #     db.session.add(completion)
        #     db.session.commit()

        return jsonify(response)

    except Exception as e:
        logging.error(f"Error getting daily quote: {e}")
        return jsonify({"error": "Failed to retrieve daily quote"}), 500


@bp.route('/get_all_quotes', methods=['GET'])
@jwt_required()
def get_all_quotes():
    # Optional: Check if user has permission to access all quotes
    # current_user = get_jwt_identity()

    try:
        # Get all active quotes from the database
        quotes = Quote.query.filter_by(active=True).all()

        # Convert to JSON serializable format
        quotes_list = []
        for quote in quotes:
            quotes_list.append({
                'id':
                quote.id,
                'text':
                quote.text,
                'author':
                quote.author,
                'minor_attribution':
                quote.minor_attribution,
                'difficulty':
                float(quote.difficulty),  # Ensure it's a float for JSON
                'daily_date':
                quote.daily_date.isoformat() if quote.daily_date else None,
                'times_used':
                quote.times_used,
                'unique_letters':
                quote.unique_letters,
                'created_at':
                quote.created_at.isoformat() if quote.created_at else None,
                'updated_at':
                quote.updated_at.isoformat() if quote.updated_at else None
            })

        # Return success response with quotes
        return jsonify({
            'success': True,
            'quotes_count': len(quotes_list),
            'quotes': quotes_list
        }), 200

    except Exception as e:
        # Log the error
        app.logger.error(f"Error fetching quotes: {str(e)}")

        # Return error response
        return jsonify({
            'success': False,
            'error': 'Failed to retrieve quotes',
            'message': str(e)
        }), 500


@bp.route('/games/reconcile', methods=['POST'])
@jwt_required()
def reconcile_games():
    """
    Smart game reconciliation endpoint that handles both full and incremental sync
    """
    try:
        data = request.get_json()

        user_id = get_jwt_identity()
        sync_type = data.get('type', 'incremental')
        since_timestamp = data.get('sinceTimestamp')
        local_summary = data.get('localSummary')
        local_changes = data.get('localChanges')

        if sync_type == 'full':
            return handle_full_reconciliation(user_id, local_summary)
        else:
            return handle_incremental_reconciliation(user_id, since_timestamp,
                                                     local_changes)

    except Exception as e:
        return jsonify({
            'success': False,
            'error': f'Reconciliation failed: {str(e)}'
        }), 500


def handle_full_reconciliation(user_id, local_summary):
    """
    Handle full reconciliation - compare all games
    """
    # Get all server games for this user
    server_games = GameScore.query.filter_by(user_id=user_id).all()

    # Convert to lookup dictionaries
    server_game_dict = {game.game_id: game for game in server_games}
    local_game_dict = {
        game['gameId']: game
        for game in local_summary.get('games', [])
    }

    plan = {
        'summary':
        f'Full sync: {len(server_games)} server games, {len(local_game_dict)} local games',
        'downloadFromServer': [],
        'uploadToServer': [],
        'conflicts': [],
        'deleteFromLocal': []
    }

    # Find games that exist on server but not locally
    for game_id, server_game in server_game_dict.items():
        if game_id not in local_game_dict:
            plan['downloadFromServer'].append(game_id)

    # Find games that exist locally but not on server
    for game_id, local_game in local_game_dict.items():
        if game_id not in server_game_dict:
            if local_game.get('isCompleted', False):
                plan['uploadToServer'].append(game_id)

    # Find conflicts (games exist in both but with different timestamps)
    for game_id in set(server_game_dict.keys()) & set(local_game_dict.keys()):
        server_game = server_game_dict[game_id]
        local_game = local_game_dict[game_id]

        server_timestamp = server_game.created_at
        local_timestamp = datetime.fromtimestamp(local_game['lastModified'])

        # Check if they're significantly different (more than 1 minute)
        if abs((server_timestamp - local_timestamp).total_seconds()) > 60:
            plan['conflicts'].append({
                'gameId':
                game_id,
                'reason':
                'Timestamp mismatch',
                'localTimestamp':
                local_timestamp.isoformat(),
                'serverTimestamp':
                server_timestamp.isoformat()
            })

    return jsonify(plan)


def handle_incremental_reconciliation(user_id, since_timestamp, local_changes):
    """
    Handle incremental reconciliation - only process changes since last sync
    """
    if not since_timestamp:
        return jsonify({
            'success': False,
            'error': 'Since timestamp required for incremental sync'
        }), 400

    since_date = datetime.fromtimestamp(since_timestamp)

    # Get server games modified since the timestamp
    server_games = GameScore.query.filter(
        and_(GameScore.user_id == user_id, GameScore.created_at
             > since_date)).all()

    plan = {
        'summary':
        f'Incremental sync since {since_date}: {len(server_games)} server changes, {len(local_changes or [])} local changes',
        'downloadFromServer': [],
        'uploadToServer': [],
        'conflicts': [],
        'deleteFromLocal': []
    }

    # Process server changes
    server_game_ids = set()
    for game in server_games:
        plan['downloadFromServer'].append(game.game_id)
        server_game_ids.add(game.game_id)

    # Process local changes
    for change in (local_changes or []):
        game_id = change['gameId']
        change_type = change['changeType']

        if game_id in server_game_ids:
            # Conflict - both server and local have changes
            plan['conflicts'].append({
                'gameId':
                game_id,
                'reason':
                'Both server and local modified',
                'localTimestamp':
                change['lastModified'],
                'serverTimestamp':
                next(g.created_at.isoformat() for g in server_games
                     if g.game_id == game_id)
            })
        else:
            # Only local change
            if change_type in ['created', 'updated'] and change.get('data'):
                # Only upload completed games
                if change['data'].get('hasWon') or change['data'].get(
                        'hasLost'):
                    plan['uploadToServer'].append(game_id)

    return jsonify(plan)


@bp.route('/games/<game_id>', methods=['GET'])
@jwt_required()
def get_game(game_id):
    """
    Get a specific game by ID - returns format compatible with Swift ServerGameData
    """
    try:
        user_id = get_jwt_identity()

        # First check GameScore table
        game_score = GameScore.query.filter_by(game_id=game_id,
                                               user_id=user_id).first()

        if not game_score:
            return jsonify({'success': False, 'error': 'Game not found'}), 404

        # Also check if there's an active game state
        active_game = ActiveGameState.query.filter_by(game_id=game_id,
                                                      user_id=user_id).first()

        # Create the exact format expected by Swift ServerGameData
        game_data = {
            'gameId': game_score.game_id,
            'userId': game_score.user_id,
            'encrypted': '',  # Will be filled from active_game if available
            'solution': '',  # Will be filled from active_game if available
            'currentDisplay':
            '',  # Will be filled from active_game if available
            'mistakes': game_score.mistakes,
            'maxMistakes': 5,  # Default value
            'hasWon': game_score.completed and game_score.score > 0,
            'hasLost': game_score.completed and game_score.score == 0,
            'difficulty': 'medium',  # Default, could be derived from game_type
            'isDaily': game_score.game_type == 'daily',
            'score': game_score.score,
            'timeTaken': game_score.time_taken,
            'startTime':
            game_score.created_at.isoformat() + 'Z',  # Add Z for ISO format
            'lastUpdateTime':
            game_score.created_at.isoformat() + 'Z',  # Add Z for ISO format
            'mapping': {},
            'correctMappings': {},
            'guessedMappings': {}
        }

        # Add active game data if available
        if active_game:
            game_data.update({
                'encrypted':
                active_game.encrypted_paragraph or '',
                'solution':
                active_game.original_paragraph or '',
                'currentDisplay':
                generate_current_display(active_game),
                'mapping':
                active_game.mapping or {},
                'correctMappings':
                active_game.reverse_mapping or {},
                'guessedMappings':
                get_guessed_mappings(active_game),
                'lastUpdateTime':
                active_game.last_updated.isoformat() + 'Z'
                if active_game.last_updated else game_data['lastUpdateTime']
            })

        # Ensure all required fields are present and correct type
        # Swift expects these exact field names and types
        required_fields = {
            'gameId': str,
            'userId': str,
            'encrypted': str,
            'solution': str,
            'currentDisplay': str,
            'mistakes': int,
            'maxMistakes': int,
            'hasWon': bool,
            'hasLost': bool,
            'difficulty': str,
            'isDaily': bool,
            'score': int,
            'timeTaken': int,
            'startTime': str,
            'lastUpdateTime': str,
            'mapping': dict,
            'correctMappings': dict,
            'guessedMappings': dict
        }

        # Validate and convert types
        for field, expected_type in required_fields.items():
            if field not in game_data:
                if expected_type == str:
                    game_data[field] = ''
                elif expected_type == int:
                    game_data[field] = 0
                elif expected_type == bool:
                    game_data[field] = False
                elif expected_type == dict:
                    game_data[field] = {}
            else:
                # Ensure correct type
                if expected_type == int:
                    game_data[field] = int(game_data[field] or 0)
                elif expected_type == bool:
                    game_data[field] = bool(game_data[field])
                elif expected_type == str:
                    game_data[field] = str(game_data[field] or '')
                elif expected_type == dict:
                    game_data[field] = dict(game_data[field] or {})

        return jsonify(game_data)

    except Exception as e:
        logging.error(f"Error getting game {game_id}: {str(e)}")
        return jsonify({'success': False, 'error': str(e)}), 500


@bp.route('/games', methods=['POST'])
@jwt_required()
def save_game():
    """
    Save/update a game from the client - expects ServerGameData format with proper constructed game IDs
    Now includes cleanup of improperly constructed duplicates
    """
    try:
        game_data = request.get_json()

        # Validate required fields
        if not game_data or 'gameId' not in game_data:
            return jsonify({
                'success': False,
                'error': 'Game ID required'
            }), 400

        game_id = game_data[
            'gameId']  # Should now be properly constructed by frontend
        user_id = get_jwt_identity()

        # Extract UUID from the properly constructed game ID for duplicate detection
        uuid_part = extract_uuid_from_constructed_id(game_id)

        if not uuid_part:
            return jsonify({
                'success': False,
                'error': 'Invalid game ID format'
            }), 400

        # Check for existing game with proper constructed ID
        existing_game = GameScore.query.filter_by(game_id=game_id,
                                                  user_id=user_id).first()

        # Check for duplicates with just the raw UUID (improper format)
        duplicate_games = GameScore.query.filter_by(game_id=uuid_part,
                                                    user_id=user_id).all()

        # Also check for other potential duplicates with different constructed formats
        other_duplicates = GameScore.query.filter(
            GameScore.user_id == user_id,
            GameScore.game_id.like(f'%{uuid_part}')).filter(
                GameScore.game_id != game_id).all()

        all_duplicates = duplicate_games + other_duplicates

        if all_duplicates:
            logging.info(
                f"Found {len(all_duplicates)} duplicate games for UUID {uuid_part}"
            )

            # If we don't have the proper game yet, migrate the oldest duplicate
            if not existing_game and all_duplicates:
                # Sort by creation date (oldest first) - we favor older entries
                oldest_duplicate = min(all_duplicates,
                                       key=lambda g: g.created_at)

                logging.info(
                    f"Migrating oldest duplicate {oldest_duplicate.game_id} -> {game_id}"
                )

                # Update the oldest duplicate to use the proper game ID
                oldest_duplicate.game_id = game_id
                existing_game = oldest_duplicate

                # Remove it from the duplicates list so we don't delete it
                all_duplicates.remove(oldest_duplicate)

            # Delete all remaining duplicates (they're either newer or we already have the proper game)
            for duplicate in all_duplicates:
                logging.info(
                    f"Deleting duplicate game: {duplicate.game_id} (created: {duplicate.created_at})"
                )

                # Also clean up any related active game state
                ActiveGameState.query.filter_by(game_id=duplicate.game_id,
                                                user_id=user_id).delete()

                db.session.delete(duplicate)

        # Parse timestamps - handle both formats (with and without Z)
        start_time = game_data.get('startTime', datetime.utcnow().isoformat())
        last_update_time = game_data.get('lastUpdateTime',
                                         datetime.utcnow().isoformat())

        # Remove Z suffix if present for parsing
        if start_time.endswith('Z'):
            start_time = start_time[:-1]
        if last_update_time.endswith('Z'):
            last_update_time = last_update_time[:-1]

        try:
            start_datetime = datetime.fromisoformat(start_time)
            update_datetime = datetime.fromisoformat(last_update_time)
        except ValueError as e:
            logging.warning(
                f"Failed to parse timestamps for game {game_id}: {e}")
            # Fallback to current time if parsing fails
            start_datetime = datetime.utcnow()
            update_datetime = datetime.utcnow()

        if existing_game:
            # Update existing game - only if the new data is newer
            if update_datetime > existing_game.created_at:
                logging.info(
                    f"Updating existing game {game_id} with newer data")
                existing_game.score = int(game_data.get('score', 0))
                existing_game.mistakes = int(game_data.get('mistakes', 0))
                existing_game.time_taken = int(game_data.get('timeTaken', 0))
                existing_game.completed = bool(
                    game_data.get('hasWon', False)
                    or game_data.get('hasLost', False))
                existing_game.game_type = 'daily' if game_data.get(
                    'isDaily', False) else 'regular'
                # Update the timestamp to reflect the newer data
                existing_game.created_at = max(existing_game.created_at,
                                               start_datetime)
            else:
                logging.info(
                    f"Keeping existing game {game_id} - incoming data is older"
                )
        else:
            # Create new game
            logging.info(f"Creating new game with ID: {game_id}")
            new_game = GameScore(user_id=user_id,
                                 game_id=game_id,
                                 score=int(game_data.get('score', 0)),
                                 mistakes=int(game_data.get('mistakes', 0)),
                                 time_taken=int(game_data.get('timeTaken', 0)),
                                 game_type='daily' if game_data.get(
                                     'isDaily', False) else 'regular',
                                 completed=bool(
                                     game_data.get('hasWon', False)
                                     or game_data.get('hasLost', False)),
                                 created_at=start_datetime)
            db.session.add(new_game)

        # Handle active game state for incomplete games
        is_completed = game_data.get('hasWon', False) or game_data.get(
            'hasLost', False)

        if not is_completed:
            # Save/update active game state
            active_game = ActiveGameState.query.filter_by(
                game_id=game_id, user_id=user_id).first()

            if not active_game:
                active_game = ActiveGameState(user_id=user_id, game_id=game_id)
                db.session.add(active_game)

            # Update active game state with data from ServerGameData
            active_game.original_paragraph = game_data.get('solution', '')
            active_game.encrypted_paragraph = game_data.get('encrypted', '')
            active_game.mapping = game_data.get('mapping', {})
            active_game.reverse_mapping = game_data.get('correctMappings', {})
            active_game.correctly_guessed = list(
                game_data.get('guessedMappings', {}).keys())
            active_game.mistakes = int(game_data.get('mistakes', 0))
            active_game.last_updated = update_datetime
        else:
            # Game is completed, remove from active games (clean up any duplicates too)
            ActiveGameState.query.filter(
                ActiveGameState.user_id == user_id,
                or_(ActiveGameState.game_id == game_id,
                    ActiveGameState.game_id == uuid_part,
                    ActiveGameState.game_id.like(f'%{uuid_part}'))).delete(
                        synchronize_session=False)

        db.session.commit()

        cleanup_count = len(all_duplicates)
        response_data = {'success': True, 'gameId': game_id}
        if cleanup_count > 0:
            response_data['duplicatesRemoved'] = cleanup_count

        return jsonify(response_data), 200

    except Exception as e:
        db.session.rollback()
        logging.error(f"Error saving game: {str(e)}")
        return jsonify({'success': False, 'error': str(e)}), 500


def extract_uuid_from_constructed_id(game_id):
    """
    Extract the UUID part from a properly constructed game ID
    Handles formats like:
    - easy-daily-2025-04-19-[UUID]
    - medium-hardcore-[UUID] 
    - hard-[UUID]
    - [UUID] (fallback)
    """
    import re

    # Pattern to match UUID at the end of the string
    uuid_pattern = r'([0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})$'
    match = re.search(uuid_pattern, game_id, re.IGNORECASE)

    if match:
        return match.group(1).upper(
        )  # Return uppercase for consistency with existing bad data

    # If the entire string is just a UUID, return it
    if re.match(
            r'^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$',
            game_id, re.IGNORECASE):
        return game_id.upper()

    return None


def is_properly_constructed_game_id(game_id):
    """
    Check if a game ID follows the proper construction format
    """
    # Valid formats:
    # - difficulty-UUID (easy-[UUID], medium-[UUID], hard-[UUID])
    # - difficulty-hardcore-UUID
    # - easy-daily-YYYY-MM-DD-UUID

    valid_patterns = [
        r'^(easy|medium|hard)-[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$',
        r'^(easy|medium|hard)-hardcore-[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$',
        r'^easy-daily-\d{4}-\d{2}-\d{2}-[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$'
    ]

    import re
    for pattern in valid_patterns:
        if re.match(pattern, game_id, re.IGNORECASE):
            return True

    return False


def generate_current_display(active_game):
    """
    Generate the current display text based on correctly guessed letters
    """
    if not active_game.original_paragraph or not active_game.correctly_guessed:
        return active_game.original_paragraph or ''

    # Create display with blocks for unguessed letters
    display = list(active_game.original_paragraph)

    # Replace unguessed letters with blocks
    for i, char in enumerate(display):
        if char.isalpha():
            # Check if this letter has been guessed
            encrypted_char = get_encrypted_char_for_position(active_game, i)
            if encrypted_char not in active_game.correctly_guessed:
                display[i] = '█'

    return ''.join(display)


def get_encrypted_char_for_position(active_game, position):
    """
    Get the encrypted character for a given position in the original text
    """
    if not active_game.encrypted_paragraph or position >= len(
            active_game.encrypted_paragraph):
        return ''
    return active_game.encrypted_paragraph[position]


def get_guessed_mappings(active_game):
    """
    Convert the correctly_guessed list to a mapping dictionary
    """
    if not active_game.correctly_guessed or not active_game.reverse_mapping:
        return {}

    guessed_mappings = {}
    for encrypted_char in active_game.correctly_guessed:
        if encrypted_char in active_game.reverse_mapping:
            guessed_mappings[encrypted_char] = active_game.reverse_mapping[
                encrypted_char]

    return guessed_mappings


# Batch operations for efficiency


@bp.route('/games/batch', methods=['POST'])
@jwt_required()
def batch_upload_games():
    """
    Upload multiple games in a single request for efficiency
    """
    try:
        games_data = request.get_json()
        user_id = get_jwt_identity()

        success_count = 0
        error_count = 0
        errors = []

        for game_data in games_data.get('games', []):
            try:
                game_id = game_data['gameId']

                # Check if game already exists
                existing_game = GameScore.query.filter_by(
                    game_id=game_id, user_id=user_id).first()

                if not existing_game:
                    new_game = GameScore(
                        user_id=user_id,
                        game_id=game_id,
                        score=game_data.get('score', 0),
                        mistakes=game_data.get('mistakes', 0),
                        time_taken=game_data.get('timeTaken', 0),
                        game_type='daily'
                        if game_data.get('isDaily', False) else 'regular',
                        completed=game_data.get('hasWon', False)
                        or game_data.get('hasLost', False),
                        created_at=datetime.fromisoformat(
                            game_data.get('lastUpdateTime',
                                          datetime.utcnow().isoformat())))
                    db.session.add(new_game)
                    success_count += 1

            except Exception as e:
                error_count += 1
                errors.append(
                    f"Game {game_data.get('gameId', 'unknown')}: {str(e)}")

        db.session.commit()

        return jsonify({
            'success': True,
            'uploaded': success_count,
            'errors': error_count,
            'errorDetails': errors
        })

    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'error': str(e)}), 500


@bp.route('/games/sync-status', methods=['GET'])
@jwt_required()
def get_sync_status():
    """
    Get information about the user's sync status
    """
    try:
        user_id = get_jwt_identity()

        # Count games
        total_games = GameScore.query.filter_by(user_id=user_id).count()
        completed_games = GameScore.query.filter_by(user_id=user_id,
                                                    completed=True).count()
        active_games = ActiveGameState.query.filter_by(user_id=user_id).count()

        # Get last activity
        last_game = GameScore.query.filter_by(user_id=user_id).order_by(
            GameScore.created_at.desc()).first()
        last_activity = last_game.created_at if last_game else None

        return jsonify({
            'success': True,
            'stats': {
                'totalGames':
                total_games,
                'completedGames':
                completed_games,
                'activeGames':
                active_games,
                'lastActivity':
                last_activity.isoformat() if last_activity else None
            }
        })

    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@bp.route('/promo', methods=['POST'])
@jwt_required()
def redeem_promo():
    """
    Unified promo redemption endpoint.
    Checks both unsubscribe tokens (for legacy import) and promo table.
    """

    current_user_id = get_jwt_identity()
    current_user = User.query.get(current_user_id)

    if not current_user:
        return jsonify({'success': False, 'error': 'User not found'}), 404

    data = request.get_json()
    code = data.get('code', '').upper().strip()

    if not code or len(code) < 6:
        return jsonify({'success': False, 'error': 'Invalid code format'}), 400

    try:
        # First, check if it's a legacy import (unsubscribe token)
        legacy_result = check_legacy_import(code, current_user)
        if legacy_result:
            return legacy_result

        # If not legacy, check promo table
        promo_result = check_promo_code(code, current_user)
        if promo_result:
            return promo_result

        # Code not found anywhere
        return jsonify({'success': False, 'error': 'Invalid promo code'}), 404

    except Exception as e:
        logging.error(f"Promo redemption error: {str(e)}")
        db.session.rollback()
        return jsonify({
            'success': False,
            'error': 'Redemption failed. Please try again.'
        }), 500


def check_legacy_import(code, current_user):
    """Check if code matches any unsubscribe token for legacy import"""

    # Only check first 6 chars of unsubscribe tokens
    all_users = User.query.filter(User.unsubscribe_token.isnot(None),
                                  User.unsubscribe_token != '').all()

    legacy_user = None
    for user in all_users:
        if user.unsubscribe_token and user.unsubscribe_token[:6].upper() == code:
            legacy_user = user
            break

    if not legacy_user:
        return None  # Not a legacy code

    # Check if already redeemed by this user
    existing_redemption = PromoRedemption.query.filter_by(
        user_id=current_user.user_id, code=code, type='legacy_import').first()

    if existing_redemption:
        return jsonify({
            'success': False,
            'error': 'You have already imported these stats',
            'type': 'legacy_import'
        }), 409

    # Check if someone else imported this account
    other_redemption = PromoRedemption.query.filter(
        PromoRedemption.code == code, PromoRedemption.type == 'legacy_import',
        PromoRedemption.user_id != current_user.user_id).first()

    if other_redemption:
        return jsonify({
            'success': False,
            'error': 'These stats have already been imported'
        }), 409

    # Get legacy stats
    legacy_stats = UserStats.query.filter_by(user_id=legacy_user.user_id).first()
    if not legacy_stats or legacy_stats.total_games_played == 0:
        return jsonify({
            'success': False,
            'error': 'No stats found for this account'
        }), 404

    # Prepare import data - just send what the legacy user had
    import_data = {
        'legacy_username': legacy_user.username,
        'games_played': legacy_stats.total_games_played,
        'games_won': legacy_stats.games_won,
        'daily_streak': legacy_stats.current_daily_streak,
        'cumulative_score': legacy_stats.cumulative_score,
        'last_played': legacy_stats.last_played_date.isoformat() if legacy_stats.last_played_date else None
    }

    # Check if streak should be preserved (for the app to handle)
    streak_preserved = False
    if legacy_stats.current_daily_streak > 0 and legacy_stats.last_played_date:
        days_since = (datetime.utcnow().date() - legacy_stats.last_played_date.date()).days
        if days_since <= 1:
            streak_preserved = True

    # Record redemption - just track that it happened
    redemption = PromoRedemption(
        user_id=current_user.user_id,
        code=code,
        type='legacy_import',
        value=legacy_stats.total_games_played  # Store games count as value for record keeping
    )
    db.session.add(redemption)
    db.session.commit()

    logging.info(f"User {current_user.username} redeemed import code from {legacy_user.username}")

    # Return the legacy stats for the app to handle
    return jsonify({
        'success': True,
        'type': 'legacy_import',
        'message': f'Successfully imported {legacy_stats.total_games_played} games!',
        'data': {
            'imported': import_data,
            'streak_preserved': streak_preserved
        }
    }), 200


def check_promo_code(code, current_user):
    """Check general promo codes table"""

    promo = Promo.query.filter_by(code=code, active=True).first()

    if not promo:
        return None

    # Check expiry
    if promo.expires_at and promo.expires_at < datetime.utcnow():
        return jsonify({
            'success': False,
            'error': 'This promo code has expired'
        }), 410

    # Check usage limit
    if promo.max_uses and promo.current_uses >= promo.max_uses:
        return jsonify({
            'success': False,
            'error': 'This promo code has reached its usage limit'
        }), 410

    # Check if user already redeemed
    existing = PromoRedemption.query.filter_by(user_id=current_user.user_id,
                                               code=code).first()

    if existing:
        return jsonify({
            'success': False,
            'error': 'You have already redeemed this code'
        }), 409

    # Apply the promo based on type
    result = apply_promo(promo, current_user)

    if result['success']:
        # Record redemption
        redemption = PromoRedemption(user_id=current_user.user_id,
                                     code=code,
                                     type=promo.type,
                                     value=promo.value,
                                     expires_at=result.get('expires_at'))
        db.session.add(redemption)

        # Increment usage
        promo.current_uses += 1

        db.session.commit()

        logging.info(
            f"User {current_user.username} redeemed promo {code} ({promo.type})"
        )

    return jsonify(result), 200 if result['success'] else 400


def apply_promo(promo, user):
    """Apply promo effects based on type"""

    if promo.type == 'xp_boost':
        # Calculate new boost
        new_boost = max(user.xp_boost_multiplier or 1.0, promo.value)
        expires_at = datetime.utcnow() + timedelta(hours=promo.duration_hours)

        # Update user
        user.xp_boost_multiplier = new_boost
        user.xp_boost_expires = expires_at

        return {
            'success': True,
            'type': 'xp_boost',
            'message':
            f'{promo.value}x XP boost activated for {promo.duration_hours} hours!',
            'data': {
                'multiplier': new_boost,
                'expires_at': expires_at.isoformat(),
                'duration_hours': promo.duration_hours
            },
            'expires_at': expires_at
        }

    # Add more promo types here as needed
    # elif promo.type == 'coins':
    #     user.coins += int(promo.value)
    #     return {...}

    return {'success': False, 'error': f'Unknown promo type: {promo.type}'}


# Utility endpoint to check active boosts
@bp.route('/active_boosts', methods=['GET'])
@jwt_required()
def get_active_boosts():
    """Get user's active boosts and their expiry"""

    user_id = get_jwt_identity()
    user = User.query.get(user_id)

    if not user:
        return jsonify({'error': 'User not found'}), 404

    boosts = []

    # Check XP boost
    if user.xp_boost_multiplier and user.xp_boost_multiplier > 1.0:
        if user.xp_boost_expires and user.xp_boost_expires > datetime.utcnow():
            boosts.append({
                'type':
                'xp_boost',
                'multiplier':
                user.xp_boost_multiplier,
                'expires_at':
                user.xp_boost_expires.isoformat(),
                'remaining_seconds':
                int((user.xp_boost_expires -
                     datetime.utcnow()).total_seconds())
            })
        else:
            # Expired, clean up
            user.xp_boost_multiplier = 1.0
            user.xp_boost_expires = None
            db.session.commit()

    return jsonify({'boosts': boosts, 'has_active_boosts': len(boosts) > 0})


# Admin endpoint to create promos
@bp.route('/admin/create_promo', methods=['POST'])
@jwt_required()
def create_promo():
    """Create a new promo code"""

    current_user = User.query.get(get_jwt_identity())
    if not current_user or not current_user.subadmin:
        return jsonify({'error': 'Unauthorized'}), 403

    data = request.get_json()

    # Validate required fields
    required = ['code', 'type', 'value']
    for field in required:
        if field not in data:
            return jsonify({'error': f'Missing field: {field}'}), 400

    # Check if code already exists
    if Promo.query.filter_by(code=data['code'].upper()).first():
        return jsonify({'error': 'Code already exists'}), 409

    # Create promo
    promo = Promo(code=data['code'].upper(),
                  type=data['type'],
                  value=float(data['value']),
                  duration_hours=data.get('duration_hours', 24),
                  max_uses=data.get('max_uses'),
                  expires_at=datetime.fromisoformat(data['expires_at'])
                  if data.get('expires_at') else None,
                  description=data.get('description', ''))

    db.session.add(promo)
    db.session.commit()

    return jsonify({
        'success': True,
        'promo': {
            'code':
            promo.code,
            'type':
            promo.type,
            'value':
            promo.value,
            'duration_hours':
            promo.duration_hours,
            'max_uses':
            promo.max_uses,
            'expires_at':
            promo.expires_at.isoformat() if promo.expires_at else None
        }
    }), 201
