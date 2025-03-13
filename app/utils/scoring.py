import math
from datetime import datetime
from app.models import db, GameScore, ActiveGameState

def score_game(difficulty, mistakes, time_taken):
    """
    Calculate game score based on difficulty, mistakes and time taken.
    Uses exponential scoring for more dramatic differences.

    Args:
        difficulty (str): 'easy', 'medium', or 'hard'
        mistakes (int): Number of wrong guesses
        time_taken (int): Time taken in seconds
    """
    # Base difficulty multipliers
    difficulty_multipliers = {
        'easy': 1,
        'medium': 2,
        'hard': 4
    }

    # Base score calculation
    base_score = 1000 * difficulty_multipliers.get(difficulty, 1)

    # Mistake penalty (exponential)
    mistake_factor = math.exp(-0.2 * mistakes)  # Each mistake reduces score exponentially

    # Time factor (faster = higher score, with diminishing returns)
    time_factor = math.exp(-0.001 * time_taken)  # Longer time reduces score exponentially

    final_score = int(base_score * mistake_factor * time_factor)
    return max(final_score, 1)  # Ensure minimum score of 1

def record_game_score(user_id, game_id, score, mistakes, time_taken, completed=True):
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
    difficulty = game_id.split('-')[0] if '-' in game_id else 'medium'

    # Get today's date for challenge tracking
    challenge_date = datetime.utcnow().strftime('%Y-%m-%d')

    game_score = GameScore(
        user_id=user_id,
        game_id=game_id,
        score=score,
        mistakes=mistakes,
        time_taken=time_taken,
        game_type='regular',
        challenge_date=challenge_date,
        completed=completed,
        created_at=datetime.utcnow()
    )

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
            original_letters=game_state.get('original_letters', []),  # Save original letters
            created_at=game_state.get('start_time', datetime.utcnow()),
            last_updated=datetime.utcnow()
        )

        db.session.add(active_game)
        db.session.commit()

    except Exception as e:
        db.session.rollback()
        raise