import math
from datetime import datetime
from app.models import db, GameScore, ActiveGameState
import logging

logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)


def score_game(difficulty, mistakes, time_taken, hardcore_mode=False):
    """
    Calculate game score based on difficulty, mistakes, time taken, and hardcore mode.
    Uses an improved mathematical model to better reflect the actual difficulty differences.

    Args:
        difficulty (str): 'easy', 'medium', or 'hard'
        mistakes (int): Number of wrong guesses
        time_taken (int): Time taken in seconds
        hardcore_mode (bool): Whether the game was played in hardcore mode (no spaces/punctuation)

    Returns:
        int: The calculated score
    """
    # Base score
    base_score = 1000

    # More mathematically justified difficulty multipliers
    # Based on the non-linear increase in difficulty when reducing allowed mistakes
    difficulty_multipliers = {
        'easy': 1.0,  # Base difficulty
        'medium': 2.5,  # ~(8/5)^1.5 - non-linear increase in difficulty
        'hard': 6.25  # ~(8/3)^2 - exponential difficulty increase
    }

    # Additional multiplier for hardcore mode (no spaces/punctuation)
    # Removing spaces increases cognitive difficulty by ~80%
    hardcore_multiplier = 1.8 if hardcore_mode else 1.0

    # Get the appropriate difficulty multiplier (default to medium if not found)
    difficulty_multiplier = difficulty_multipliers.get(difficulty, 2.5)

    # Calculate mistake penalty - slightly gentler curve than before
    mistake_factor = math.exp(-0.15 * mistakes)

    # Calculate time factor - slightly reduced penalty for time
    time_factor = math.exp(-0.0008 * time_taken)

    # Calculate final score with all factors
    final_score = int(base_score * difficulty_multiplier *
                      hardcore_multiplier * mistake_factor * time_factor)

    # Ensure minimum score of 1
    return max(final_score, 1)


def record_game_score(user_id,
                      game_id,
                      score,
                      mistakes,
                      time_taken,
                      completed=True):
    """
    Record a completed game's score and details.

    Args:
        user_id (str): The user's ID
        game_id (str): The game ID (includes difficulty)
        score (int): Calculated game score
        mistakes (int): Number of mistakes made
        time_taken (int): Time taken in seconds
        completed (bool): Whether the game was completed (won or lost)
    """
    # Extract difficulty from game_id (format: "difficulty-uuid")
    # difficulty = game_id.split('-')[0] if '-' in game_id else 'medium'

    # Get today's date for challenge tracking
    challenge_date = datetime.utcnow().strftime('%Y-%m-%d')

    game_score = GameScore(user_id=user_id,
                           game_id=game_id,
                           score=score,
                           mistakes=mistakes,
                           time_taken=time_taken,
                           game_type='regular',
                           challenge_date=challenge_date,
                           completed=completed,
                           created_at=datetime.utcnow())
    #delete activegamestate record
    active_game = ActiveGameState.query.filter_by(user_id=user_id).first()
    if active_game:
        logger.info(
            f"Deleting active game for user {user_id} after completion")
        db.session.delete(active_game)

    db.session.add(game_score)
    db.session.commit()


def update_active_game_state(user_id, game_state):
    """
    Update or create active game state for a user, cleaning up old states.

    Args:
        user_id (str): The user's ID
        game_state (dict): Current game state including all necessary fields
    """
    try:
        # Delete any previous active game for this user
        ActiveGameState.query.filter_by(user_id=user_id).delete()

        # If game is completed, don't create new state
        if game_state.get('game_complete', False):
            db.session.commit()
            return

        # Create new active game state
        active_game = ActiveGameState(
            user_id=user_id,
            game_id=game_state['game_id'],
            original_paragraph=game_state.get('original_paragraph', ''),
            encrypted_paragraph=game_state['encrypted_paragraph'],
            mapping=game_state['mapping'],
            reverse_mapping=game_state['reverse_mapping'],
            correctly_guessed=game_state['correctly_guessed'],
            mistakes=game_state['mistakes'],
            major_attribution=game_state.get('major_attribution', ''),
            minor_attribution=game_state.get('minor_attribution', ''),
            created_at=game_state.get('start_time', datetime.utcnow()),
            last_updated=datetime.utcnow())

        db.session.add(active_game)
        db.session.commit()

    except Exception as e:
        db.session.rollback()
        raise
