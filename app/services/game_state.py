from datetime import datetime
import logging
from app.models import db, ActiveGameState, AnonymousGameState, GameScore, UserStats
import json

# Set up logging
logger = logging.getLogger(__name__)


def get_unified_game_state(identifier, is_anonymous=False):
    """
    Get game state from the appropriate model based on user type.

    Args:
        identifier (str): User ID for authenticated users, game_id_anon for anonymous users
        is_anonymous (bool): Whether this is an anonymous user

    Returns:
        dict: Standardized game state dictionary or None if not found
    """
    try:
        if is_anonymous:
            # For anonymous users, look up by anon_id
            anon_id = identifier
            game = AnonymousGameState.query.filter_by(anon_id=anon_id).first()
            if not game:
                logger.debug(f"No anonymous game found with ID: {anon_id}")
                return None

            # Convert database model to standardized game state dict
            game_state = {
                'game_id': game.game_id,
                'original_paragraph': game.original_paragraph,
                'encrypted_paragraph': game.encrypted_paragraph,
                'mapping': game.mapping,
                'reverse_mapping': game.reverse_mapping,
                'correctly_guessed': game.correctly_guessed
                or [],  # Handle None case
                'incorrect_guesses': game.incorrect_guesses
                or {},  # Add this line
                'mistakes': game.mistakes,
                'max_mistakes': get_max_mistakes_from_game_id(game.game_id),
                'major_attribution': game.major_attribution,
                'minor_attribution': game.minor_attribution,
                'start_time': game.created_at,
                'difficulty':
                game.game_id.split('-')[0] if game.game_id else 'medium',
                'game_complete': game.completed,
                'has_won': game.won
            }
        else:
            # For authenticated users, look up by user_id and game_id
            try:
                user_id, game_id = identifier.split('_', 1)
                if not game_id:
                    logger.error("No game_id provided in identifier for authenticated user")
                    return None
                    
                game = ActiveGameState.query.filter_by(
                    user_id=user_id,
                    game_id=game_id
                ).first()
            except ValueError:
                logger.error(f"Invalid identifier format (no game_id): {identifier}")
                return None
            if not game:
                logger.debug(f"No active game found for user: {user_id}")
                return None

            # Convert database model to standardized game state dict
            game_state = {
                'game_id':
                game.game_id,
                'original_paragraph':
                game.original_paragraph,
                'encrypted_paragraph':
                game.encrypted_paragraph,
                'mapping':
                game.mapping,
                'reverse_mapping':
                game.reverse_mapping,
                'correctly_guessed':
                game.correctly_guessed or [],  # Handle None case
                'incorrect_guesses':
                game.incorrect_guesses or {},  # Add this line
                'mistakes':
                game.mistakes,
                'max_mistakes':
                get_max_mistakes_from_game_id(game.game_id),
                'major_attribution':
                game.major_attribution,
                'minor_attribution':
                game.minor_attribution,
                'start_time':
                game.created_at,
                'difficulty':
                game.game_id.split('-')[0] if game.game_id else 'medium'
            }
            # print(game_state)
            # Check game status dynamically
            status = check_game_status(game_state)
            game_state['game_complete'] = status['game_complete']
            game_state['has_won'] = status['has_won']

        return game_state
    except Exception as e:
        logger.error(f"Error getting game state: {str(e)}", exc_info=True)
        return None


def save_unified_game_state(identifier, game_state, is_anonymous=False, is_daily=None):
    """
    Save game state to the appropriate model based on user type.

    Args:
        identifier (str): User ID for authenticated users, game_id_anon for anonymous users
        game_state (dict): Game state dictionary to save
        is_anonymous (bool): Whether this is an anonymous user
        is_daily (bool, optional): Whether to handle this as a daily challenge. 
                                 If None, will be determined from game_id.
                                 Affects which previous games are deleted.

    Returns:
        bool: Success or failure
    """
    try:
        if is_anonymous:
            # For anonymous users, save to AnonymousGameState
            anon_id = identifier
            anon_game = AnonymousGameState.query.filter_by(
                anon_id=anon_id).first()

            if anon_game:
                # Update existing anonymous game
                anon_game.mapping = game_state.get('mapping', {})
                anon_game.reverse_mapping = game_state.get(
                    'reverse_mapping', {})
                anon_game.correctly_guessed = game_state.get(
                    'correctly_guessed', [])
                anon_game.incorrect_guesses = game_state.get(
                    'incorrect_guesses', {})  # Add this line
                anon_game.mistakes = game_state.get('mistakes', 0)
                anon_game.last_updated = datetime.utcnow()

                # Check if game is complete
                if game_state.get('game_complete', False):
                    anon_game.completed = True
                    anon_game.won = game_state.get('has_won', False)
            else:
                # Create new anonymous game entry
                anon_game = AnonymousGameState(
                    anon_id=anon_id,
                    game_id=game_state.get('game_id', ''),
                    original_paragraph=game_state.get('original_paragraph',
                                                      ''),
                    encrypted_paragraph=game_state.get('encrypted_paragraph',
                                                       ''),
                    mapping=game_state.get('mapping', {}),
                    reverse_mapping=game_state.get('reverse_mapping', {}),
                    correctly_guessed=game_state.get('correctly_guessed', []),
                    incorrect_guesses=game_state.get('incorrect_guesses',
                                                     {}),  # Add this line
                    mistakes=game_state.get('mistakes', 0),
                    major_attribution=game_state.get('major_attribution', ''),
                    minor_attribution=game_state.get('minor_attribution', ''))
                db.session.add(anon_game)
        else:
            # For authenticated users, save to ActiveGameState
            user_id, game_id = identifier.split('_', 1) if '_' in identifier else (identifier, None)

            # Determine if this is a daily challenge if not explicitly specified
            if is_daily is None and game_id:
                is_daily = 'daily' in game_id

            # Delete previous games based on type
            if is_daily:
                # Only delete previous daily games
                ActiveGameState.query.filter(
                    ActiveGameState.user_id == user_id,
                    ActiveGameState.game_id.like('%daily%')
                ).delete()
            else:
                # Delete previous non-daily games
                ActiveGameState.query.filter(
                    ActiveGameState.user_id == user_id,
                    ~ActiveGameState.game_id.like('%daily%')
                ).delete()
            
            db.session.commit()

            # For completed games, we need to keep the ActiveGameState until
            # the win is acknowledged through the game-status endpoint
            if game_id:
                active_game = ActiveGameState.query.filter_by(user_id=user_id, game_id=game_id).first()
            else:
                active_game = ActiveGameState.query.filter_by(user_id=user_id).first()

            if active_game:
                # Update existing game state
                active_game.mapping = game_state.get('mapping', {})
                active_game.reverse_mapping = game_state.get(
                    'reverse_mapping', {})
                active_game.correctly_guessed = game_state.get(
                    'correctly_guessed', [])
                active_game.incorrect_guesses = game_state.get(
                    'incorrect_guesses', {})
                active_game.mistakes = game_state.get('mistakes', 0)
                active_game.last_updated = datetime.utcnow()

                # Check if this is a win that's been acknowledged
                if game_state.get('game_complete', False) and game_state.get(
                        'has_won', False) and game_state.get(
                            'win_notified', False):
                    # Once the win has been acknowledged, record the score and delete the active game
                    time_taken = int((datetime.utcnow() -
                                      active_game.created_at).total_seconds())

                    # Record score
                    if not game_state.get('is_abandoned', False):
                        record_game_score(user_id=user_id,
                                          game_id=active_game.game_id,
                                          score=calculate_game_score(
                                              game_state, time_taken),
                                          mistakes=active_game.mistakes,
                                          time_taken=time_taken,
                                          completed=True)

                    # Now delete the active game
                    db.session.delete(active_game)
            else:
                # Create new active game state
                active_game = ActiveGameState(
                    user_id=user_id,
                    game_id=game_state.get('game_id', ''),
                    original_paragraph=game_state.get('original_paragraph',
                                                      ''),
                    encrypted_paragraph=game_state.get('encrypted_paragraph',
                                                       ''),
                    mapping=game_state.get('mapping', {}),
                    reverse_mapping=game_state.get('reverse_mapping', {}),
                    correctly_guessed=game_state.get('correctly_guessed', []),
                    incorrect_guesses=game_state.get('incorrect_guesses',
                                                     {}),  # Add this line
                    mistakes=game_state.get('mistakes', 0),
                    major_attribution=game_state.get('major_attribution', ''),
                    minor_attribution=game_state.get('minor_attribution', ''),
                    created_at=game_state.get('start_time', datetime.utcnow()),
                    last_updated=datetime.utcnow())
                db.session.add(active_game)

        # Commit changes
        db.session.commit()
        logger.debug(
            f"Game state saved successfully for {'anonymous' if is_anonymous else 'user'} {identifier}"
        )
        return True
    except Exception as e:
        logger.error(f"Error saving game state: {str(e)}", exc_info=True)
        db.session.rollback()
        return False


def abandon_game(user_id, is_daily=False):
    """
    Abandon a game for an authenticated user, recording it as incomplete.

    Args:
        user_id (str): User ID
        is_daily (bool): Whether to abandon daily game (True) or regular game (False)

    Returns:
        bool: Success or failure
    """
    try:
        # Get the active game based on type
        if is_daily:
            active_game = ActiveGameState.query.filter(
                ActiveGameState.user_id == user_id,
                ActiveGameState.game_id.like('%daily%')
            ).first()
        else:
            active_game = ActiveGameState.query.filter(
                ActiveGameState.user_id == user_id,
                ~ActiveGameState.game_id.like('%daily%')
            ).first()

        if not active_game:
            logger.warning(
                f"No active game found to abandon for user {user_id}")
            return True  # Nothing to abandon is still a success

        # Record the abandoned game
        game_score = GameScore(
            user_id=user_id,
            game_id=active_game.game_id,
            score=0,  # Zero score for abandoned games
            mistakes=active_game.mistakes,
            time_taken=int(
                (datetime.utcnow() - active_game.created_at).total_seconds()),
            game_type='regular',
            challenge_date=datetime.utcnow().strftime('%Y-%m-%d'),
            completed=False,  # Mark as incomplete
            created_at=datetime.utcnow())

        # Delete the active game
        db.session.add(game_score)
        db.session.delete(active_game)
        db.session.commit()

        # Update user stats to reflect the broken streak
        from app.utils.stats import initialize_or_update_user_stats
        initialize_or_update_user_stats(user_id, game_score)

        logger.info(f"Game abandoned successfully for user {user_id}")
        return True
    except Exception as e:
        logger.error(f"Error abandoning game: {str(e)}", exc_info=True)
        db.session.rollback()
        return False


def get_max_mistakes_from_game_id(game_id):
    """
    Extract difficulty from game_id and return the maximum mistakes allowed.

    Args:
        game_id (str): Game ID string (format: "difficulty-uuid")

    Returns:
        int: Maximum number of mistakes allowed
    """
    # Default to medium difficulty
    difficulty = 'medium'

    # Extract difficulty from game_id if possible
    if game_id and '-' in game_id:
        parts = game_id.split('-')
        if parts[0] in ['easy', 'medium', 'hard']:
            difficulty = parts[0]

    # Difficulty settings
    difficulty_settings = {'easy': 8, 'medium': 5, 'hard': 3}

    return difficulty_settings.get(difficulty, 5)  # Default to medium (6)


def calculate_game_score(game_state, time_taken):
    """
    Calculate score based on difficulty, mistakes, and time taken.

    Args:
        game_state (dict): Game state dictionary
        time_taken (int): Time taken in seconds

    Returns:
        int: Calculated score
    """
    # Only calculate score for completed games that were won
    if not game_state.get('game_complete', False) or not game_state.get(
            'has_won', False):
        return 0

    # Import scoring function from utils
    from app.utils.scoring import score_game

    # Calculate score
    difficulty = game_state.get('difficulty', 'medium')
    mistakes = game_state.get('mistakes', 0)

    return score_game(difficulty, mistakes, time_taken)


def get_attribution_from_quotes(original_paragraph):
    """
    Get attribution information from database for a given paragraph.

    Args:
        original_paragraph (str): The original paragraph text

    Returns:
        dict: Attribution information with major_attribution (author) and minor_attribution
    """
    try:
        from app.models import Quote

        # Default values in case we can't find a match
        attribution = {'major_attribution': 'Unknown', 'minor_attribution': ''}

        # Normalize the paragraph for matching (remove extra whitespace, lowercase)
        normalized_paragraph = ' '.join(
            original_paragraph.strip().split()).lower()

        # Look up quote in database
        quote = Quote.query.filter(
            func.lower(Quote.text) == normalized_paragraph).first()

        if quote:
            attribution = {
                'major_attribution': quote.author,
                'minor_attribution': quote.minor_attribution or ''
            }
            logger.debug(f"Found attribution: {attribution}")
            return attribution

        # If we get here, no match was found
        logger.warning(
            f"No attribution found for paragraph: {normalized_paragraph[:50]}..."
        )
        return attribution

    except Exception as e:
        logger.error(f"Error getting attribution: {str(e)}", exc_info=True)
        return {'major_attribution': 'Unknown', 'minor_attribution': ''}


def record_game_score(user_id,
                      game_id,
                      score,
                      mistakes,
                      time_taken,
                      completed=True):
    """
    Record a game score in the database.

    Args:
        user_id (str): User ID
        game_id (str): Game ID
        score (int): Calculated score
        mistakes (int): Number of mistakes made
        time_taken (int): Time taken in seconds
        completed (bool): Whether the game was completed successfully

    Returns:
        bool: Success or failure
    """
    try:
        # Get today's date for challenge tracking
        from datetime import datetime
        challenge_date = datetime.utcnow().strftime('%Y-%m-%d')

        # Create GameScore record
        from app.models import db, GameScore
        game_score = GameScore(user_id=user_id,
                               game_id=game_id,
                               score=score,
                               mistakes=mistakes,
                               time_taken=time_taken,
                               game_type='regular',
                               challenge_date=challenge_date,
                               completed=completed,
                               created_at=datetime.utcnow())

        # Add and commit
        db.session.add(game_score)
        db.session.commit()

        # Update user stats
        from app.utils.stats import initialize_or_update_user_stats
        initialize_or_update_user_stats(user_id, game_score)
        print("pre- daily win detector")
        # Check if this is a daily challenge and record completion
        if 'daily' in game_id and completed:
            print("***daily win detected***")
            record_daily_completion(user_id, game_id, score, mistakes,
                                    time_taken)

        return True
    except Exception as e:
        import logging
        logger = logging.getLogger(__name__)
        logger.error(f"Error recording game score: {str(e)}", exc_info=True)

        from app.models import db
        db.session.rollback()
        return False


def check_game_status(game_state):
    """
    Check if a game is complete (won or lost).

    Args:
        game_state (dict): Game state dictionary

    Returns:
        dict: Status information with game_complete and has_won flags
    """
    # Get difficulty and max mistakes
    difficulty = game_state.get('difficulty', 'medium')
    max_mistakes = get_max_mistakes_from_game_id(
        game_state.get('game_id', f"{difficulty}-default"))

    # Game is lost if mistakes exceed max allowed
    if game_state.get('mistakes', 0) >= max_mistakes:
        return {'game_complete': True, 'has_won': False}

    # Game is won if all letters are correctly guessed
    encrypted_letters = set(c
                            for c in game_state.get('encrypted_paragraph', '')
                            if c.isalpha())
    correctly_guessed = game_state.get('correctly_guessed', [])

    # Use set intersection to check if all letters are guessed
    # Instead of length comparison which could have edge cases
    encrypted_set = set(encrypted_letters)
    guessed_set = set(correctly_guessed)

    unique_letters_in_paragraph = len(encrypted_set)
    unique_correctly_guessed = len(encrypted_set.intersection(guessed_set))

    if unique_correctly_guessed == unique_letters_in_paragraph and unique_letters_in_paragraph > 0:
        return {'game_complete': True, 'has_won': True}

    # Game is still in progress
    return {'game_complete': False, 'has_won': False}


def get_display(encrypted_paragraph, correctly_guessed, reverse_mapping):
    """
    Generate a display version of the encrypted paragraph with correctly guessed letters revealed.

    Args:
        encrypted_paragraph (str): The encrypted paragraph
        correctly_guessed (list): List of correctly guessed letters
        reverse_mapping (dict): Mapping from encrypted to original letters

    Returns:
        str: Display string with blocks for unguessed letters
    """
    return ''.join(reverse_mapping[char] if char in
                   correctly_guessed else '█' if char.isalpha() else char
                   for char in encrypted_paragraph)


def process_guess(game_state, encrypted_letter, guessed_letter):
    """
    Process a letter guess and update game state.

    Args:
        game_state (dict): Current game state
        encrypted_letter (str): The encrypted letter being guessed
        guessed_letter (str): The original letter guessed

    Returns:
        dict: Updated game state and result information
    """
    reverse_mapping = game_state.get('reverse_mapping', {})
    correctly_guessed = game_state.get('correctly_guessed', [])
    incorrect_guesses = game_state.get('incorrect_guesses', {})

    # Validate the guess
    if encrypted_letter not in reverse_mapping:
        return {'valid': False, 'message': 'Invalid encrypted letter'}

    # Check if guess is correct
    correct_letter = reverse_mapping.get(encrypted_letter, '')
    is_correct = guessed_letter.upper() == correct_letter

    # Update game state based on correctness
    if is_correct:
        if encrypted_letter not in correctly_guessed:
            correctly_guessed.append(encrypted_letter)
    else:
        game_state['mistakes'] = game_state.get('mistakes', 0) + 1

        # Add incorrect guess to tracking
        if encrypted_letter not in incorrect_guesses:
            incorrect_guesses[encrypted_letter] = []

        # Only add if this specific guess hasn't been tried before
        if guessed_letter.upper() not in incorrect_guesses[encrypted_letter]:
            incorrect_guesses[encrypted_letter].append(guessed_letter.upper())

    # Update correctly_guessed and incorrect_guesses in the game state
    game_state['correctly_guessed'] = correctly_guessed
    game_state['incorrect_guesses'] = incorrect_guesses

    # Check if game is complete
    status = check_game_status(game_state)
    game_state['game_complete'] = status['game_complete']
    game_state['has_won'] = status['has_won']

    # Generate the display
    display = get_display(game_state.get('encrypted_paragraph', ''),
                          correctly_guessed, reverse_mapping)

    return {
        'valid': True,
        'game_state': game_state,
        'display': display,
        'is_correct': is_correct,
        'complete': status['game_complete'],
        'has_won': status['has_won'],
        'incorrect_guesses': incorrect_guesses  # Add this line
    }


def process_hint(game_state):
    """
    Process a hint request and update game state.

    Args:
        game_state (dict): Current game state

    Returns:
        dict: Updated game state and hint information
    """
    import random

    mapping = game_state.get('mapping', {})
    reverse_mapping = game_state.get('reverse_mapping', {})
    correctly_guessed = game_state.get('correctly_guessed', [])
    encrypted_paragraph = game_state.get('encrypted_paragraph', '')

    # Get all encrypted letters that appear in the text
    all_encrypted = list(set(c for c in encrypted_paragraph if c.isalpha()))

    # Filter out already guessed letters
    unguessed = [
        letter for letter in all_encrypted if letter not in correctly_guessed
    ]

    if not unguessed:
        return {'valid': False, 'message': 'No more hints available'}

    # Select a random unguessed letter
    hint_letter = random.choice(unguessed)
    correctly_guessed.append(hint_letter)

    # Apply difficulty-specific hint penalty
    difficulty = game_state.get('difficulty', 'medium')
    hint_penalties = {'easy': 1, 'medium': 1, 'hard': 1}
    game_state['mistakes'] = game_state.get(
        'mistakes', 0) + hint_penalties.get(difficulty, 1)

    # Update game state
    game_state['correctly_guessed'] = correctly_guessed

    # Check if game is complete
    status = check_game_status(game_state)
    game_state['game_complete'] = status['game_complete']
    game_state['has_won'] = status['has_won']

    # Generate the display
    display = get_display(encrypted_paragraph, correctly_guessed,
                          reverse_mapping)

    return {
        'valid': True,
        'game_state': game_state,
        'display': display,
        'hint_letter': hint_letter,
        'hint_value': reverse_mapping.get(hint_letter, ''),
        'complete': status['game_complete'],
        'has_won': status['has_won'],
        'incorrect_guesses': game_state.get('incorrect_guesses', {})
    }


def record_daily_completion(user_id, game_id, score, mistakes, time_taken):
    """
    Record a daily challenge completion in the DailyCompletion model with enhanced debugging.
    """
    logger = logging.getLogger(__name__)

    logger.info(
        f"DAILY DEBUG: Starting daily completion recording for user={user_id}, game_id={game_id}"
    )

    # Only proceed if this is a daily challenge
    if 'daily' not in game_id:
        logger.info(
            f"DAILY DEBUG: Not a daily challenge (no 'daily' in game_id): {game_id}"
        )
        return True  # Not a daily challenge, so no need to record

    logger.info(f"DAILY DEBUG: Confirmed this is a daily challenge")

    try:
        from app.models import db, Quote, DailyCompletion
        from datetime import datetime

        # Extract date from game_id (format: "difficulty-daily-YYYY-MM-DD-uuid")
        logger.info(
            f"DAILY DEBUG: Attempting to extract date from game_id: {game_id}")
        date_parts = game_id.split('-')
        logger.info(f"DAILY DEBUG: Split game_id into parts: {date_parts}")

        if len(date_parts) < 5:
            logger.warning(
                f"DAILY DEBUG: Invalid daily game_id format (not enough parts): {game_id}"
            )
            return False

        # Parse the date components
        try:
            challenge_date_str = f"{date_parts[2]}-{date_parts[3]}-{date_parts[4]}"
            logger.info(
                f"DAILY DEBUG: Extracted date string: {challenge_date_str}")
            challenge_date = datetime.strptime(challenge_date_str,
                                               '%Y-%m-%d').date()
            logger.info(f"DAILY DEBUG: Parsed date object: {challenge_date}")
        except (ValueError, IndexError) as e:
            logger.error(
                f"DAILY DEBUG: Error parsing date from game_id {game_id}: {str(e)}"
            )
            return False

        # Find the quote for this date
        logger.info(
            f"DAILY DEBUG: Looking up quote for date: {challenge_date}")
        daily_quote = Quote.query.filter_by(daily_date=challenge_date).first()

        if not daily_quote:
            logger.warning(
                f"DAILY DEBUG: No daily quote found for date {challenge_date}")

            # Additional debugging for available quotes
            try:
                all_daily_quotes = Quote.query.filter(
                    Quote.daily_date is not None).all()
                logger.info(
                    f"DAILY DEBUG: Found {len(all_daily_quotes)} quotes with daily dates"
                )
                logger.info(
                    f"DAILY DEBUG: Sample daily dates: {[q.daily_date for q in all_daily_quotes[:5]]}"
                )
            except Exception as quote_err:
                logger.error(
                    f"DAILY DEBUG: Error querying available quotes: {str(quote_err)}"
                )

            return False

        logger.info(
            f"DAILY DEBUG: Found quote: id={daily_quote.id}, author={daily_quote.author}"
        )

        # Check if user already completed this daily challenge
        logger.info(
            f"DAILY DEBUG: Checking for existing completion for user={user_id}, date={challenge_date}"
        )
        existing_completion = DailyCompletion.query.filter_by(
            user_id=user_id, challenge_date=challenge_date).first()

        if existing_completion:
            logger.info(
                f"DAILY DEBUG: User {user_id} already completed daily challenge for {challenge_date}"
            )
            return True  # Already recorded

        logger.info(
            f"DAILY DEBUG: No existing completion found, creating new record")

        # Create new completion record
        completion = DailyCompletion(user_id=user_id,
                                     quote_id=daily_quote.id,
                                     challenge_date=challenge_date,
                                     completed_at=datetime.utcnow(),
                                     score=score,
                                     mistakes=mistakes,
                                     time_taken=time_taken)

        logger.info(
            f"DAILY DEBUG: Created completion object, adding to session")
        db.session.add(completion)

        # Update the user's daily streak
        logger.info(f"DAILY DEBUG: About to update user's daily streak")
        try:
            from app.routes.game import update_daily_streak
            update_daily_streak(user_id, challenge_date)
            logger.info(f"DAILY DEBUG: Daily streak updated successfully")
        except Exception as streak_err:
            logger.error(
                f"DAILY DEBUG: Error updating daily streak: {str(streak_err)}",
                exc_info=True)
            # Continue despite streak update error

        logger.info(f"DAILY DEBUG: Committing transaction")
        db.session.commit()
        logger.info(
            f"DAILY DEBUG: Successfully recorded daily completion for user {user_id} on {challenge_date}"
        )
        return True

    except Exception as e:
        from app.models import db
        logger.error(
            f"DAILY DEBUG: Error recording daily completion: {str(e)}",
            exc_info=True)

        # Additional error context
        logger.error(
            f"DAILY DEBUG: Error details - user_id: {user_id}, game_id: {game_id}"
        )

        try:
            db.session.rollback()
            logger.info("DAILY DEBUG: Session rolled back successfully")
        except Exception as rollback_err:
            logger.error(
                f"DAILY DEBUG: Error during rollback: {str(rollback_err)}")

        return False
