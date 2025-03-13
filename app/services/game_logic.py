import random
from app.utils.helpers import load_word_list

def start_game():
    words = load_word_list()
    return random.choice(words)

def make_guess(target_word, guess):
    if len(guess) != len(target_word):
        return {'correct': False, 'position': []}
    
    position = []
    for i, (t, g) in enumerate(zip(target_word, guess)):
        if t == g:
            position.append(i)
    
    return {
        'correct': len(position) == len(target_word),
        'position': position
    }

def get_hint(word):
    # Simple hint: reveal a random unrevealed letter
    return f"Try a word with '{random.choice(word)}'"
