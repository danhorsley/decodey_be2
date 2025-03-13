import random
import string
import csv
from pathlib import Path

def load_quotes():
    quotes_file = Path('quotes.csv')
    quotes = []
    with open(quotes_file, 'r') as f:
        reader = csv.DictReader(f)
        for row in reader:
            quotes.append(row['quote'])
    return quotes

def create_substitution_cipher():
    # Create a substitution mapping for letters
    alphabet = string.ascii_uppercase + string.punctuation + " "
    shuffled = list(alphabet)
    random.shuffle(shuffled)
    return dict(zip(alphabet, shuffled))

def encrypt_quote(quote, cipher):
    encrypted = ''
    for char in quote.upper():
        encrypted += cipher.get(char, char)
    return encrypted

def decrypt_char(encrypted_char, cipher):
    # Find the original character by looking up the encrypted char in the cipher
    for original, encrypted in cipher.items():
        if encrypted == encrypted_char:
            return original
    return encrypted_char

def start_game():
    quotes = load_quotes()
    quote = random.choice(quotes)
    cipher = create_substitution_cipher()
    encrypted_quote = encrypt_quote(quote, cipher)

    return {
        'encrypted_quote': encrypted_quote,
        'original_quote': quote,
        'cipher': cipher
    }

def make_guess(game_state, guess):
    encrypted_quote = game_state['encrypted_quote']
    original_quote = game_state['original_quote']

    # Convert both to uppercase for comparison
    guess = guess.upper()
    original_quote = original_quote.upper()

    correct = (guess == original_quote)

    # Calculate matching positions
    matching_positions = []
    for i, (g, o) in enumerate(zip(guess, original_quote)):
        if g == o:
            matching_positions.append(i)

    return {
        'correct': correct,
        'matching_positions': matching_positions,
        'length': len(original_quote)
    }

def get_hint(game_state):
    original_quote = game_state['original_quote']
    encrypted_quote = game_state['encrypted_quote']
    cipher = game_state['cipher']

    # Find an unmatched character to reveal
    revealed_char = random.choice(list(original_quote.upper()))
    encrypted_char = encrypt_quote(revealed_char, cipher)

    return f"The character '{encrypted_char}' represents '{revealed_char}'"