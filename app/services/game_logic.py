import random
import string
import csv
from pathlib import Path
from collections import Counter

def load_quotes():
    quotes_file = Path('quotes.csv')
    quotes = []
    with open(quotes_file, 'r') as f:
        reader = csv.DictReader(f)
        for row in reader:
            quotes.append({
                'quote': row['quote'],
                'author': row['author']
            })
    return quotes

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
    # Count only uppercase letters
    return Counter(c for c in text if c in string.ascii_uppercase)

def get_unique_letters(text):
    # Get unique uppercase letters
    return sorted(set(c for c in text.upper() if c in string.ascii_uppercase))

def start_game():
    quotes = load_quotes()
    quote_data = random.choice(quotes)
    paragraph = quote_data['quote']
    author = quote_data['author']

    mapping = generate_mapping()
    reverse_mapping = {v: k for k, v in mapping.items()}
    encrypted = encrypt_paragraph(paragraph, mapping)
    encrypted_frequency = get_letter_frequency(encrypted)
    unique_original_letters = get_unique_letters(paragraph)

    game_state = {
        'original_paragraph': paragraph,
        'encrypted_paragraph': encrypted,
        'mapping': mapping,
        'reverse_mapping': reverse_mapping,
        'correctly_guessed': [],
        'mistakes': 0,
        'author': author,
        'max_mistakes': 5  # Allow 5 mistakes
    }

    return {
        'game_state': game_state,
        'encrypted': encrypted,
        'encrypted_frequency': dict(encrypted_frequency),
        'unique_letters': unique_original_letters
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