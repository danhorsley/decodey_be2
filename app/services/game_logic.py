import random
import string
import csv
from pathlib import Path
from collections import Counter

# def load_quotes():
#     quotes_file = Path('quotes.csv')
#     quotes = []
#     with open(quotes_file, 'r') as f:
#         reader = csv.DictReader(f)
#         for row in reader:
#             quotes.append({
#                 'quote': row['quote'],
#                 'author': row['author'],
#                 'minor_attribution': row['minor_attribution']
#             })
#     return quotes

def generate_mapping():
    # Create a substitution mapping for uppercase letters only
    alphabet = string.ascii_uppercase
    shuffled = list(alphabet)
    random.shuffle(shuffled)
    return dict(zip(alphabet, shuffled))

def encrypt_paragraph(text, mapping):
    encrypted = ''
    for char in text.upper():
        if char in mapping:
            encrypted += mapping[char]
        else:
            encrypted += char
    return encrypted

def get_letter_frequency(text):
    # Initialize frequency counter for all letters
    frequency = {letter: 0 for letter in string.ascii_uppercase}
    # Update counts for letters that appear
    frequency.update(Counter(c for c in text if c in string.ascii_uppercase))
    return frequency

def get_unique_letters(text):
    # Get unique uppercase letters
    return sorted(set(c for c in text.upper() if c in string.ascii_uppercase))

def generate_display_blocks(text):
    display = ''
    for char in text.upper():
        if char in string.ascii_uppercase:
            display += '█'
        else:
            display += char
    return display

def start_game(long_text=False):
    """
    Start a new game by selecting a random quote and creating the game state

    Args:
        long_text (bool): If True, select quotes longer than 65 characters.
                         If False, select quotes of 65 characters or shorter.
    """
    from app.models import Quote
    from sqlalchemy.sql import func

    # Initialize these variables with defaults - this prevents the UnboundLocalError
    paragraph = "The database appears to be empty. Please add quotes."
    author = "System"
    minor_attribution = "Error"

    # Determine length filtering criteria - use func.length() instead of text.length()
    length_filter = func.length(Quote.text) > 65 if long_text else func.length(Quote.text) <= 65

    # Get a random quote directly from the database with length constraint
    random_quote = Quote.query.filter_by(active=True)\
                             .filter(length_filter)\
                             .order_by(func.random())\
                             .first()

    # If no quotes found with the length criteria, try without length filtering
    if not random_quote:
        import logging
        logger = logging.getLogger(__name__)
        logger.warning(f"No quotes found matching length criteria (long_text={long_text}). Trying without length filter.")

        random_quote = Quote.query.filter_by(active=True)\
                                 .filter(Quote.daily_date.is_(None))\
                                 .order_by(func.random())\
                                 .first()

    # Handle case where a quote was found
    if random_quote:
        print("length filter : ", length_filter)
        paragraph = random_quote.text
        author = random_quote.author
        minor_attribution = random_quote.minor_attribution

        # Update usage count for this quote
        random_quote.times_used += 1
        from app.models import db
        db.session.commit()
    else:
        # Log the error - we'll use the default values set earlier
        import logging
        logger = logging.getLogger(__name__)
        logger.error("No quotes found in database. Make sure quotes are loaded and active.")

    mapping = generate_mapping()
    reverse_mapping = {v: k for k, v in mapping.items()}
    encrypted = encrypt_paragraph(paragraph, mapping)
    encrypted_frequency = get_letter_frequency(encrypted)
    unique_original_letters = get_unique_letters(paragraph)
    display_blocks = generate_display_blocks(paragraph)

    game_state = {
        'original_paragraph': paragraph,
        'encrypted_paragraph': encrypted,
        'mapping': mapping,
        'reverse_mapping': reverse_mapping,
        'correctly_guessed': [],
        'mistakes': 0,
        'author': author,
        'max_mistakes': 5,  # Allow 5 mistakes
        'major_attribution': author,
        'minor_attribution': minor_attribution
    }

    return {
        'game_state': game_state,
        'display': display_blocks,
        'encrypted_paragraph': encrypted,
        'letter_frequency': encrypted_frequency,
        'original_letters': unique_original_letters,
        'mistakes': 0,
        'major_attribution': author,
        'minor_attribution': minor_attribution
    }
    
def make_guess(game_state, encrypted_letter, guessed_letter):
    if encrypted_letter not in game_state['reverse_mapping']:
        return {'valid': False, 'message': 'Invalid encrypted letter'}

    correct_letter = game_state['reverse_mapping'][encrypted_letter]
    is_correct = guessed_letter.upper() == correct_letter

    if is_correct:
        if encrypted_letter not in game_state['correctly_guessed']:
            game_state['correctly_guessed'].append(encrypted_letter)
    else:
        game_state['mistakes'] += 1

    game_complete = (
        len(game_state['correctly_guessed']) == len(set(game_state['mapping'].values())) or 
        game_state['mistakes'] >= game_state['max_mistakes']
    )

    return {
        'valid': True,
        'correct': is_correct,
        'complete': game_complete,
        'mistakes': game_state['mistakes'],
        'max_mistakes': game_state['max_mistakes'],
        'revealed_pairs': [(l, game_state['reverse_mapping'][l]) for l in game_state['correctly_guessed']]
    }

def get_hint(game_state):
    # Get an unguessed letter pair
    available_encrypted = [
        k for k in game_state['reverse_mapping'].keys()
        if k not in game_state['correctly_guessed']
    ]

    if not available_encrypted:
        return None

    hint_encrypted = random.choice(available_encrypted)
    hint_original = game_state['reverse_mapping'][hint_encrypted]
    game_state['correctly_guessed'].append(hint_encrypted)

    return {
        'encrypted': hint_encrypted,
        'original': hint_original
    }