from flask import Blueprint, jsonify, request, Response, stream_with_context, current_app
from flask_jwt_extended import jwt_required, get_jwt_identity, decode_token
from app.services.game_logic import start_game
from app.services.game_state import (get_unified_game_state,
                                     save_unified_game_state,
                                     check_game_status, get_display,
                                     process_guess, process_hint, abandon_game,
                                     get_attribution_from_quotes)
from app.models import db, ActiveGameState, AnonymousGameState, GameScore, UserStats, DailyCompletion
from datetime import datetime, date
import logging
import uuid
import json
import time

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
            logger.warning(f"Game creation request rejected - cooldown period not elapsed for {'anonymous' if is_anonymous else user_id}")
            return jsonify({
                "error": "Please wait a moment before starting a new game",
                "cooldown_remaining": round(GAME_CREATION_COOLDOWN - time_since_last_creation, 1)
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
                    ~ActiveGameState.game_id.like('%daily%')  # Only regular games
                ).first()

                if active_game:
                    logger.info(f"Found existing regular game for user {user_id} - abandoning")

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
                        challenge_date=datetime.utcnow().strftime(
                            '%Y-%m-%d'),
                        completed=False,  # Mark as incomplete
                        created_at=datetime.utcnow())

                    # Add game score and delete active game
                    db.session.add(game_score)
                    db.session.delete(active_game)
                    db.session.commit()

                    # Update stats for this abandoned game
                    from app.utils.stats import initialize_or_update_user_stats
                    initialize_or_update_user_stats(user_id)

                    logger.info(f"Successfully abandoned regular game for user {user_id}")
            except Exception as abandon_err:
                logger.error(f"Error abandoning existing game for user {user_id}: {str(abandon_err)}")
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

        # For debugging
        logger.debug(
            f"Game complete: {result['complete']}, HasWon: {result['has_won']}"
        )

        # Return result to client
        return jsonify({
            'display': result['display'],
            'mistakes': result['game_state']['mistakes'],
            'correctly_guessed': result['game_state']['correctly_guessed'],
            'incorrect_guesses': result['game_state']['incorrect_guesses'],  # Add this line
            'game_complete': result['complete'],
            'hasWon': result['has_won'],
            'is_correct': result['is_correct'],
            'max_mistakes': result['game_state']['max_mistakes']
        }), 200
    except Exception as e:
        logger.error(f"Error processing guess: {str(e)}", exc_info=True)
        return jsonify({"error": "Error processing guess"}), 500


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
        print("game_id on hint: ",game_id)
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

        # For debugging
        logger.debug(
            f"Game complete: {result['complete']}, HasWon: {result['has_won']}"
        )

        # Return result to client
        return jsonify({
            'display': result['display'],
            'mistakes': result['game_state']['mistakes'],
            'correctly_guessed': result['game_state']['correctly_guessed'],
            'incorrect_guesses': result['game_state'].get('incorrect_guesses', {}),  # Add this line
            'game_complete': result['complete'],
            'hasWon': result['has_won'],  # Use the front-end expected key
            'hint_letter': result['hint_letter'],
            'hint_value': result['hint_value'],
            'max_mistakes': result['game_state']['max_mistakes']
        }), 200
    except Exception as e:
        logger.error(f"Error processing hint: {str(e)}", exc_info=True)
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
            ~ActiveGameState.game_id.like('%daily%')
        ).first()
        
        game_state = get_unified_game_state(f"{user_id}_{regular_game.game_id}", is_anonymous=False) if regular_game else None
        
        response = {"has_active_game": False, "has_active_daily_game": False}
        
        if game_state:
            # Calculate regular game stats
            encrypted_letters = set(c for c in game_state['encrypted_paragraph']
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
            ActiveGameState.game_id.like('%daily%')
        ).first()

        if daily_game:
            # Calculate daily game stats
            daily_state = get_unified_game_state(f"{user_id}_{daily_game.game_id}", is_anonymous=False)
            if daily_state:
                encrypted_letters = set(c for c in daily_state['encrypted_paragraph']
                                        if c.isalpha())
                completion_percentage = (len(daily_state['correctly_guessed']) /
                                         len(encrypted_letters) *
                                         100) if encrypted_letters else 0

                time_spent = int(
                    (datetime.utcnow() - daily_state['start_time']).total_seconds())

                response.update({
                    "has_active_daily_game": True,
                    "daily_stats": {
                        "difficulty": daily_state['difficulty'],
                        "mistakes": daily_state['mistakes'],
                        "completion_percentage": round(completion_percentage, 1),
                        "time_spent": time_spent,
                        "max_mistakes": daily_state['max_mistakes']
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
                ActiveGameState.game_id.like('%daily%')
            ).first()
            
            if daily_game:
                game_state = get_unified_game_state(f"{user_id}_{daily_game.game_id}", is_anonymous=False)
            else:
                game_state = None
        else:
            # Get non-daily game
            game_state = get_unified_game_state(user_id, is_anonymous=False)

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
            "incorrect_guesses": game_state.get('incorrect_guesses', {}),  # Add this line
            "game_complete": game_state['game_complete'],
            "hasWon": game_state['has_won'],
            "max_mistakes": game_state['max_mistakes'],
            "difficulty": game_state['difficulty'],
            "original_letters": original_letters,
            "reverse_mapping": game_state['reverse_mapping'],
            "guessed_letters": display_guessed
        }
        print(ret)
        return jsonify(ret), 200
    except Exception as e:
        logger.error(f"Error continuing game: {str(e)}", exc_info=True)
        return jsonify({"error": "Error continuing game"}), 500


@bp.route('/abandon-game', methods=['DELETE', 'OPTIONS'])
@jwt_required()
def abandon_game_route():
    """Abandon current game and record it as incomplete"""
    if request.method == 'OPTIONS':
        return jsonify({}), 200

    try:
        user_id = get_jwt_identity()
        is_daily = request.args.get('isDaily', 'false').lower() == 'true'
        result = abandon_game(user_id, is_daily=is_daily)

        if result:
            return jsonify({"message": "Game abandoned successfully"}), 200
        else:
            return jsonify({"error": "Failed to abandon game"}), 500
    except Exception as e:
        logger.error(f"Error abandoning game: {str(e)}", exc_info=True)
        return jsonify({"error": "Error abandoning game"}), 500


@bp.route('/game-status', methods=['GET', 'OPTIONS'])
@jwt_required(optional=True)
def game_status():
    """Return the current game status for polling"""
    if request.method == 'OPTIONS':
        return jsonify({}), 200

    try:
        # Get user identification
        user_id = get_jwt_identity()
        is_anonymous = user_id is None

        # For anonymous users, we need the game_id
        game_id = request.args.get('game_id')

        if is_anonymous and not game_id:
            return jsonify({"error": "Game ID required for anonymous users"}), 400

        # Get identifier based on user type
        identifier = f"{game_id}_anon" if is_anonymous else f"{user_id}_{game_id}"
        print("identifier on game status: ", identifier)
        game_state = get_unified_game_state(identifier, is_anonymous=is_anonymous)

        logger.debug(f"Game status check for {'anonymous' if is_anonymous else user_id}")

        if not game_state:
            logger.debug(f"No active game found for {'anonymous' if is_anonymous else user_id}")
            return jsonify({"hasActiveGame": False}), 200

        # If game is won but not yet notified, mark for processing
        db_operations_needed = False
        completion_record = None
        daily_date = None
        if game_state['has_won']:
            active_game = ActiveGameState.query.filter_by(user_id=user_id,game_id=game_id).first()
            current_daily_streak = 0
            time_taken = int((datetime.utcnow() - active_game.created_at).total_seconds())
        # Check if the game is won
        if game_state['has_won'] and not is_anonymous:
            # Get the active game record
            

            if active_game:
                # Check if this is a daily challenge
                is_daily = 'daily' in active_game.game_id
                

                # For daily challenges, update the streak first
                if is_daily:
                    # Extract the date from the game_id or use today's date
                    # Format in game_id is typically: "difficulty-daily-YYYY-MM-DD-uuid"
                    try:
                        parts = active_game.game_id.split('-')
                        if len(parts) >= 5:
                            challenge_date_str = f"{parts[2]}-{parts[3]}-{parts[4]}"
                            challenge_date = datetime.strptime(challenge_date_str, '%Y-%m-%d').date()
                        else:
                            # Fallback to today's date
                            challenge_date = datetime.utcnow().date()
                    except (ValueError, IndexError):
                        challenge_date = datetime.utcnow().date()

                    # Update the streak
                    user_stats = UserStats.query.filter_by(user_id=user_id).first()

                    if not user_stats:
                        # Create user stats if they don't exist
                        user_stats = UserStats(user_id=user_id)
                        db.session.add(user_stats)

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

                    # Commit the streak update first
                    db.session.commit()

                
        if game_state['has_won']:
            # Now calculate score with the updated streak
            from app.utils.scoring import score_game
            if not is_anonymous:
                # Now get the updated streak for score calculation
                user_stats = UserStats(user_id=user_id)
                current_daily_streak = user_stats.current_daily_streak
                logger.info(f"Updated daily streak to {current_daily_streak} for user {user_id}")
            difficulty = game_state.get('difficulty', 'medium')
            mistakes = game_state.get('mistakes', 0)
            hardcore_mode = game_state.get('hardcore_mode', False)

            # Calculate final score
            score = score_game(
                difficulty,
                mistakes,
                time_taken,
                hardcore_mode=hardcore_mode,
                current_daily_streak=current_daily_streak
            )

            logger.info(f"Calculated score: {score} for user {user_id}")

            # Create and save the score record
            game_score = GameScore(
                user_id=user_id,
                game_id=active_game.game_id,
                score=score,
                mistakes=active_game.mistakes,
                time_taken=time_taken,
                game_type='daily' if is_daily else 'regular',
                challenge_date=datetime.utcnow().strftime('%Y-%m-%d'),
                completed=True,
                created_at=datetime.utcnow()
            )

            # Save the score 
            db.session.add(game_score)

            # Record daily completion
            if is_daily and not not is_anonymous:
                # Find the quote for this date
                from app.models import Quote, DailyCompletion
                daily_quote = Quote.query.filter_by(daily_date=challenge_date).first()

                if daily_quote:
                    # Create completion record
                    completion = DailyCompletion(
                        user_id=user_id,
                        quote_id=daily_quote.id,
                        challenge_date=challenge_date,
                        completed_at=datetime.utcnow(),
                        score=score,
                        mistakes=mistakes,
                        time_taken=time_taken
                    )
                    db.session.add(completion)

            # Delete the active game
            db.session.delete(active_game)

            # Final commit
            db.session.commit()

            logger.info(f"Score {score} saved to database for user {user_id}")

        # Prepare win data AFTER all database operations are complete
            win_data = None
        
            # Use attribution from game state
            attribution = {
                'major_attribution': game_state.get('major_attribution', 'Unknown'),
                'minor_attribution': game_state.get('minor_attribution', '')
            }

            # Update the completion record's score if we have one
            if completion_record:
                try:
                    # We need to re-fetch it since we've committed already
                    saved_completion = DailyCompletion.query.filter_by(
                        user_id=user_id, challenge_date=daily_date).first()
                    if saved_completion:
                        saved_completion.score = score
                        db.session.commit()
                        logger.info(f"Updated completion record with score {score}")
                except Exception as score_err:
                    logger.error(f"Error updating completion score: {str(score_err)}")
                    db.session.rollback()
                    # Not critical, continue

            win_data = {
                'score': score,
                'mistakes': game_state['mistakes'],
                'maxMistakes': game_state['max_mistakes'],
                'gameTimeSeconds': time_taken,
                'attribution': attribution,
                'current_daily_streak': current_daily_streak  # Updated streak value
            }

        response_data = {
            "hasActiveGame": True,
            "gameComplete": game_state['game_complete'],
            "hasWon": game_state['has_won'],
            "winData": win_data,
            "mistakes": game_state['mistakes'],
            "maxMistakes": game_state['max_mistakes'],
        }

        logger.debug(f"Returning game status: {response_data}")
        return jsonify(response_data), 200
    except Exception as e:
        logger.error(f"Error getting game status: {str(e)}", exc_info=True)
        return jsonify({"error": "Error getting game status"}), 500



