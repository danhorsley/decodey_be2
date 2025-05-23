# Add to app/routes/game.py or create a new file app/routes/daily.py

from flask import Blueprint, jsonify, request
from flask_jwt_extended import jwt_required, get_jwt_identity, get_jwt
from datetime import datetime, date, timedelta
from app.models import db, Quote, DailyCompletion, UserStats, ActiveGameState
from app.services.game_logic import generate_mapping, encrypt_paragraph, get_letter_frequency, get_unique_letters, generate_display_blocks
from app.services.game_state import get_max_mistakes_from_game_id, save_unified_game_state
import logging
import uuid

# Set up logging
logger = logging.getLogger(__name__)

bp = Blueprint('daily', __name__)


@bp.route('/daily/<date_string>', methods=['GET', 'OPTIONS'])
@jwt_required(optional=True)
def get_daily_challenge(date_string=None):
    """Get the daily challenge for a specific date or today"""
    if request.method == 'OPTIONS':
        return jsonify({}), 200  # Handle OPTIONS request for CORS

    try:
        # Get user identification
        user_id = get_jwt_identity()
        is_anonymous = user_id is None

        # Get the requested date or use today
        if date_string:
            try:
                requested_date = datetime.strptime(date_string,
                                                   '%Y-%m-%d').date()
            except ValueError:
                return jsonify(
                    {"error": "Invalid date format. Use YYYY-MM-DD"}), 400
        else:
            requested_date = date.today()

        logger.debug(f"Looking for daily challenge on date: {requested_date}")

        # Find quote scheduled for exactly the requested date
        from sqlalchemy import func
        daily_quote = Quote.query.filter(
            func.date(Quote.daily_date) == requested_date).first()
        logger.debug(f"Found daily quote: {daily_quote.text}")

        if not daily_quote:
            # If no quote is scheduled for this date, return an error
            logger.error(f"No daily challenge found for {requested_date}")
            return jsonify(
                {"error": "No daily challenge available for this date"})

        # Check if authenticated user has already completed today's challenge
        if not is_anonymous:
            completion = DailyCompletion.query.filter_by(
                user_id=user_id, challenge_date=requested_date).first()

            if completion:
                return jsonify({
                    "error": "You have already completed today's challenge",
                    "already_completed": True,
                    "completion_data": {
                        "score": completion.score,
                        "mistakes": completion.mistakes,
                        "time_taken": completion.time_taken,
                        "completed_at": completion.completed_at.isoformat()
                    }
                }), 400

        # Generate cryptogram for the quote
        # We'll use easy difficulty for daily challenges
        difficulty = "easy"
        game_id = f"{difficulty}-daily-{requested_date}-{str(uuid.uuid4())}"

        mapping = generate_mapping()
        encrypted_paragraph = encrypt_paragraph(daily_quote.text, mapping)
        reverse_mapping = {v: k for k, v in mapping.items()}

        # Create game state similar to regular games but with daily metadata
        game_state = {
            'original_paragraph': daily_quote.text,
            'encrypted_paragraph': encrypted_paragraph,
            'mapping': mapping,
            'reverse_mapping': reverse_mapping,
            'correctly_guessed': [],
            'mistakes': 0,
            'max_mistakes': get_max_mistakes_from_game_id(game_id),
            'author': daily_quote.author,
            'major_attribution': daily_quote.author,
            'minor_attribution': daily_quote.minor_attribution,
            'game_id': game_id,
            'difficulty': difficulty,
            'is_daily': True,
            'daily_date': requested_date.isoformat(),
            'start_time': datetime.utcnow(),
            'game_complete': False,
            'has_won': False
        }

        # Generate display blocks
        display = generate_display_blocks(daily_quote.text)

        # Calculate letter frequency
        letter_frequency = get_letter_frequency(encrypted_paragraph)

        # Get unique original letters
        unique_original_letters = get_unique_letters(daily_quote.text)

        # For authenticated users, save game state
        if not is_anonymous:
            # Check and delete any existing daily game for this user
            existing_daily = ActiveGameState.query.filter(
                ActiveGameState.user_id == user_id,
                ActiveGameState.game_id.like('%daily%')
            ).first()
            if existing_daily:
                db.session.delete(existing_daily)
                db.session.commit()
            
            # Now save the new game state with proper identifier
            identifier = f"{user_id}_{game_id}"
            save_unified_game_state(identifier, game_state, is_anonymous=False)
        else:
            # For anonymous users, save with anon ID
            anon_id = f"{game_id}_anon"
            # print("***SUGS data***",anon_id,game_state)
            save_unified_game_state(anon_id, game_state, is_anonymous=True)

        # Create response data
        response_data = {
            "display": display,
            "encrypted_paragraph": encrypted_paragraph,
            "game_id": game_id,
            "letter_frequency": letter_frequency,
            "mistakes": 0,
            "original_letters": unique_original_letters,
            "game_complete": False,
            "hasWon": False,
            "max_mistakes": game_state['max_mistakes'],
            "difficulty": difficulty,
            "is_anonymous": is_anonymous,
            "is_daily": True,
            "daily_date": requested_date.isoformat()
        }

        return jsonify(response_data), 200

    except Exception as e:
        logger.error(f"Error starting daily challenge: {str(e)}",
                     exc_info=True)
        return jsonify({"error": "Failed to start daily challenge"}), 500


@bp.route('/daily-stats', methods=['GET', 'OPTIONS'])
@jwt_required()
def get_daily_stats():
    """Get daily challenge statistics for the current user"""
    if request.method == 'OPTIONS':
        return jsonify({}), 200  # Handle OPTIONS request for CORS
    try:
        user_id = get_jwt_identity()

        # Get user stats
        user_stats = UserStats.query.filter_by(user_id=user_id).first()

        if not user_stats:
            # Initialize stats if they don't exist
            user_stats = UserStats(user_id=user_id)
            db.session.add(user_stats)
            db.session.commit()

        # Get daily completion history
        completions = DailyCompletion.query.filter_by(
            user_id=user_id).order_by(
                DailyCompletion.challenge_date.desc()).all()

        # Calculate completion rate
        today = date.today()
        # Get the first daily we ever offered
        first_daily = Quote.query.filter(
            Quote.daily_date.isnot(None)).order_by(Quote.daily_date).first()

        total_possible = 0
        if first_daily and first_daily.daily_date:
            # Count days between first daily and today
            first_date = first_daily.daily_date
            delta = today - first_date
            total_possible = delta.days + 1  # Include today

        completion_rate = 0
        if total_possible > 0:
            completion_rate = (len(completions) / total_possible) * 100

        # Get recent completions (last 30 days)
        recent_completions = []
        for completion in completions[:30]:  # Limit to most recent 30
            recent_completions.append({
                "date":
                completion.challenge_date.isoformat(),
                "score":
                completion.score,
                "mistakes":
                completion.mistakes,
                "time_taken":
                completion.time_taken
            })

        # Get top 5 highest scoring daily completions
        top_scores = DailyCompletion.query.filter_by(user_id=user_id).order_by(
            DailyCompletion.score.desc()).limit(5).all()

        top_scores_data = []
        for score in top_scores:
            top_scores_data.append({
                "date": score.challenge_date.isoformat(),
                "score": score.score,
                "mistakes": score.mistakes,
                "time_taken": score.time_taken
            })

        # Format response data
        stats_data = {
            "current_streak":
            user_stats.current_daily_streak,
            "max_streak":
            user_stats.max_daily_streak,
            "total_completed":
            user_stats.total_daily_completed,
            "last_completed_date":
            user_stats.last_daily_completed_date.isoformat()
            if user_stats.last_daily_completed_date else None,
            "completion_rate":
            round(completion_rate, 1),
            "recent_completions":
            recent_completions,
            "top_scores":
            top_scores_data
        }

        return jsonify(stats_data), 200

    except Exception as e:
        logger.error(f"Error getting daily stats: {str(e)}", exc_info=True)
        return jsonify(
            {"error": "Failed to retrieve daily challenge statistics"}), 500


@bp.route('/daily-completion', methods=['GET', 'OPTIONS'])
@jwt_required()
def check_daily_completion():
    """Check if user has completed a specific daily challenge"""
    if request.method == 'OPTIONS':
        return jsonify({}), 200  # Handle OPTIONS request for CORS

    try:
        user_id = get_jwt_identity()

        # Get date from query parameter instead of URL parameter
        date_string = request.args.get('date')
        if not date_string:
            return jsonify({"error": "Date parameter is required"}), 400

        # Parse date string (expected format: YYYY-MM-DD)
        try:
            challenge_date = datetime.strptime(date_string, '%Y-%m-%d').date()
        except ValueError:
            return jsonify({"error":
                            "Invalid date format. Use YYYY-MM-DD"}), 400

        # Check if challenge exists for this date
        daily_quote = Quote.query.filter_by(daily_date=challenge_date).first()
        if not daily_quote:
            return jsonify({
                "error": "No daily challenge found for this date",
                "is_completed": False
            }), 404

        # Check if user has completed this challenge
        completion = DailyCompletion.query.filter_by(
            user_id=user_id, challenge_date=challenge_date).first()

        if not completion:
            return jsonify({
                "is_completed": False,
                "message": "Daily challenge not yet completed"
            }), 200

        # Return completion details
        return jsonify({
            "is_completed": True,
            "completion_data": {
                "date": completion.challenge_date.isoformat(),
                "score": completion.score,
                "mistakes": completion.mistakes,
                "time_taken": completion.time_taken,
                "completed_at": completion.completed_at.isoformat()
            }
        }), 200

    except Exception as e:
        logger.error(f"Error checking daily completion: {str(e)}",
                     exc_info=True)
        return jsonify({"error":
                        "Failed to check daily challenge completion"}), 500


