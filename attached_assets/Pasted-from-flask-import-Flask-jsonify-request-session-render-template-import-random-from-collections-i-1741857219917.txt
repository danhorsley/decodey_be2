from flask import Flask, jsonify, request, session, render_template
import random
from collections import Counter
import csv
import os
from flask_cors import CORS
import uuid
import logging
import sys
import sqlite3
from .init_db import init_db, get_db_connection
from .login import login_bp
from .login import validate_token
from .stats import stats_bp
from .scoring import scoring_bp
from .game_state import (get_active_game_state, save_game_state,
                         delete_game_state, sync_game_state_with_session,
                         init_game_state_cache)
import threading
import time
from .token_routes import token_bp

ENV = os.environ.get('FLASK_ENV', 'development')
# Database path - using different files for dev and prod
if ENV == 'production':
    DATABASE_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)),
                                 'game.db')  # Production database
else:
    DATABASE_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)),
                                 'dev_game.db')  # Development database

# Import configuration
try:
    from .config import DATABASE_PATH, ENV
except ImportError:
    # Fallback for direct execution
    from config import DATABASE_PATH, ENV

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('app.log'),
        logging.StreamHandler(sys.stdout)
    ])

game_states = {}

# Initialize the database on startup
init_db()
init_game_state_cache()


# Set up periodic cleanup task
def periodic_cleanup():
    """
    Run cleanup tasks periodically 
    """
    while True:
        try:
            # Run cleanup every hour
            time.sleep(3600)  # 1 hour
            logging.info("Running periodic cleanup tasks")

            # Cleanup old game states
            deleted_count = cleanup_old_game_states()
            logging.info(f"Cleaned up {deleted_count} old game states")

        except Exception as e:
            logging.error(f"Error in periodic cleanup: {e}")
            # Sleep a bit even if there was an error
            time.sleep(60)


# Start the cleanup thread
cleanup_thread = threading.Thread(target=periodic_cleanup, daemon=True)
cleanup_thread.start()

app = Flask(__name__)
# Improved CORS settings with explicit Replit domains
CORS(
    app,
    supports_credentials=True,  # This is important for cookies
    resources={
        r"/*": {
            "origins": [
                "https://*.replit.app",
                "https://*.repl.co",
                "https://*.replit.dev",
                "https://replit.com",
                "https://*.replit.com",
                "https://staging.replit.com",
                "https://firewalledreplit.com",
                "http://localhost:3000",
                "http://127.0.0.1:3000",
                "*"  # Allow all origins (you can restrict this for production)
            ]
        }
    },
    allow_headers=[
        "Authorization", "Content-Type", "X-Requested-With", "Accept",
        "X-Game-Id", "X-User-ID", "X-Session-ID"
    ],
    expose_headers=["Access-Control-Allow-Origin", "X-Game-Id"],
    allow_credentials=True  # Make sure this is True
)

app.secret_key = TOKEN_SECRET = os.environ.get("TOKEN_SECRET")
# Make sure session is permanent
app.config['SESSION_TYPE'] = 'filesystem'
app.config['PERMANENT_SESSION_LIFETIME'] = 3600  # 1 hour in seconds
app.config['SESSION_COOKIE_SECURE'] = True
app.config['SESSION_COOKIE_PATH'] = '/'
app.config['SESSION_COOKIE_DOMAIN'] = None  # Allow any domain
app.config[
    'SESSION_COOKIE_SAMESITE'] = None  # Required for cross-origin requests
#app.config['SESSION_COOKIE_SECURE'] = True  # Set to True if using HTTPS
app.config['SESSION_COOKIE_HTTPONLY'] = True
# Register the login blueprint
app.register_blueprint(login_bp)
app.register_blueprint(stats_bp)
app.register_blueprint(scoring_bp)
app.register_blueprint(token_bp)

TOKEN_SECRET = "your-secret-key-change-this-in-production"


class QuoteLoader:

    def __init__(self, csv_path):
        """Load quotes from CSV into memory once."""
        self.quotes = []
        with open(csv_path, 'r', encoding='latin-1') as csvfile:
            reader = csv.DictReader(csvfile)
            self.quotes = [row for row in reader]  # Store the full row

    def get_random_quote(self):
        """Return a random quote with attributions from the loaded list."""
        quote_data = random.choice(self.quotes)
        return {
            "Quote": quote_data["Quote"],
            "Major Attribution": quote_data["Major Attribution"],
            "Minor Attribution": quote_data["Minor Attribution"]
        }


def generate_mapping():
    alphabet = list("ABCDEFGHIJKLMNOPQRSTUVWXYZ")
    shuffled = alphabet.copy()
    random.shuffle(shuffled)
    return dict(zip(alphabet, shuffled))


def encrypt_paragraph(paragraph, mapping):
    return ''.join(mapping.get(char, char) for char in paragraph.upper())


def get_display(encrypted_paragraph, correctly_guessed, reverse_mapping):
    return ''.join(reverse_mapping[char] if char in
                   correctly_guessed else '█' if char.isalpha() else char
                   for char in encrypted_paragraph)


def get_letter_frequency(text):
    """Calculate frequency of each letter in a text."""
    return Counter(c for c in text.upper() if c.isalpha())


def get_unique_letters(text):
    return sorted(set(c for c in text.upper() if c.isalpha()))


# start_game function moved above and modified

recent_logs = []


def log_message(message):
    recent_logs.append(message)
    # Keep only the last 100 logs
    if len(recent_logs) > 100:
        recent_logs.pop(0)
    print(message)  # Also print to console


@app.route('/privacy')
def privacy_policy():
    return render_template('privacy.html')


@app.route('/health', methods=['GET'])
def health_check():
    logging.info("Health check endpoint accessed")
    return jsonify({"status": "ok", "message": "Service is running"})


@app.route('/debug_logs', methods=['GET'])
def get_logs():
    return jsonify(recent_logs)


@app.route('/debug_client', methods=['POST'])
def debug_client():
    data = request.get_json()
    log_message(f"Debug from client: {data}")
    return jsonify({"status": "logged"})


def start_game(max_length=None):
    # Initialize the quote loader
    current_dir = os.path.dirname(os.path.abspath(__file__))
    csv_path = os.path.join(current_dir, 'curated.csv')
    quote_loader = QuoteLoader(csv_path)

    # Get a quote that matches the length criteria if specified
    if max_length:
        # Try to find a quote under the maximum length (with a reasonable number of attempts)
        for _ in range(20):  # Try 20 times to find a suitable quote
            quote_data = quote_loader.get_random_quote()
            if len(quote_data["Quote"]) <= max_length:
                break
    else:
        # Get any random quote if no length constraint
        quote_data = quote_loader.get_random_quote()

    paragraph = quote_data["Quote"]

    mapping = generate_mapping()
    reverse_mapping = {v: k for k, v in mapping.items()}
    encrypted = encrypt_paragraph(paragraph, mapping)
    encrypted_frequency = get_letter_frequency(encrypted)
    unique_original_letters = get_unique_letters(paragraph)

    session['game_state'] = {
        'original_paragraph': paragraph,
        'encrypted_paragraph': encrypted,
        'mapping': mapping,
        'reverse_mapping': reverse_mapping,
        'correctly_guessed': [],
        'mistakes': 0,
        'major_attribution': quote_data["Major Attribution"],
        'minor_attribution': quote_data["Minor Attribution"]
    }
    return encrypted, encrypted_frequency, unique_original_letters


@app.route('/start', methods=['GET'])
def start():
    print("==== NEW SHORT GAME STARTING ====")
    # Make session permanent
    session.permanent = True

    # Try to get user_id from session or token
    user_id = session.get('user_id')

    # If no user_id in session, check for token in Authorization header
    if not user_id:
        auth_header = request.headers.get('Authorization')
        if auth_header and auth_header.startswith('Bearer '):
            token = auth_header.split(' ')[1]
            try:
                user_id = validate_token(token)
                print(f"Authenticated via token: user_id={user_id}")
            except Exception as e:
                print(f"Token validation failed: {e}")

    # Check for an existing game state if we have a user_id
    existing_game_state = None
    if user_id:
        print(f"Checking for existing game state for user {user_id}")
        existing_game_state = get_active_game_state(user_id)

        # If there's an existing game state, use it
        if existing_game_state:
            print(
                f"Found existing game state with ID {existing_game_state['game_id']}"
            )

            # Set the game state in the session
            session['game_state'] = existing_game_state

            # Generate response from the existing state
            encrypted = existing_game_state['encrypted_paragraph']

            # Get unique letters in the original text
            unique_original_letters = sorted(
                set(c
                    for c in existing_game_state['original_paragraph'].upper()
                    if c.isalpha()))

            # Calculate letter frequency for the encrypted text
            encrypted_frequency = {}
            for c in encrypted:
                if c.isalpha():
                    encrypted_frequency[c] = encrypted_frequency.get(c, 0) + 1

            # Add 0 frequency for unused letters
            full_frequency = {
                chr(65 + i): encrypted_frequency.get(chr(65 + i), 0)
                for i in range(26)
            }

            # Generate display text
            display = get_display(encrypted,
                                  existing_game_state['correctly_guessed'],
                                  existing_game_state['reverse_mapping'])

            # Return the existing game state
            return jsonify({
                'encrypted_paragraph':
                encrypted,
                'mistakes':
                existing_game_state['mistakes'],
                'letter_frequency':
                full_frequency,
                'display':
                display,
                'original_letters':
                unique_original_letters,
                'major_attribution':
                existing_game_state['major_attribution'],
                'minor_attribution':
                existing_game_state['minor_attribution'],
                'game_id':
                existing_game_state['game_id'],
                'is_restored':
                True  # Flag to indicate this is a restored game
            })

    # If we reach here, we need to start a new game
    # Clear any existing session data for a fresh start
    if 'game_state' in session:
        session.pop('game_state')

    # Start a new game with shorter quotes (80 chars should fit on most mobile screens in landscape)
    encrypted, encrypted_frequency, unique_original_letters = start_game(
        max_length=65)

    # Generate a unique game ID
    import uuid
    game_id = str(uuid.uuid4())

    # Get the game state from the session
    game_state = session.get('game_state')

    # Update with game_id
    game_state['game_id'] = game_id

    # Store the game state in the in-memory dictionary
    game_states[game_id] = game_state

    # NEW: If user is authenticated, save the game state to the database
    if user_id:
        save_game_state(user_id, game_id, game_state)
        print(f"Saved new game state for user {user_id}, game {game_id}")

    display = get_display(encrypted, [], {})
    # Extend frequency with 0 for unused letters
    full_frequency = {
        chr(65 + i): encrypted_frequency.get(chr(65 + i), 0)
        for i in range(26)
    }

    ret = {
        'encrypted_paragraph': encrypted,
        'mistakes': 0,
        'letter_frequency':
        full_frequency,  # This should be the frequency of encrypted letters
        'display': display,
        'original_letters': unique_original_letters,
        'major_attribution': '',
        'minor_attribution': '',
        'game_id': game_id
    }

    return jsonify(ret)


@app.route('/longstart', methods=['GET'])
def longstart():
    print("==== NEW LONG GAME STARTING ====")
    # Make session permanent
    session.permanent = True

    # Clear any existing session data to ensure a fresh start
    session.clear()

    # Start a new game with no length restriction
    encrypted, encrypted_frequency, unique_original_letters = start_game()

    # Generate a unique game ID
    import uuid
    game_id = str(uuid.uuid4())

    # Store the game state in the in-memory dictionary
    game_states[game_id] = session.get('game_state')

    display = get_display(encrypted, [], {})
    # Extend frequency with 0 for unused letters
    full_frequency = {
        chr(65 + i): encrypted_frequency.get(chr(65 + i), 0)
        for i in range(26)
    }

    ret = {
        'encrypted_paragraph': encrypted,
        'mistakes': 0,
        'letter_frequency':
        full_frequency,  # This should be the frequency of encrypted letters
        'display': display,
        'original_letters': unique_original_letters,
        'major_attribution': '',
        'minor_attribution': '',
        'game_id': game_id
    }

    return jsonify(ret)


# Then update the guess endpoint to use the game ID
# Update these parts of your app.py


# 1. Modify the guess endpoint to prioritize game_id and prevent session restarts
@app.route('/guess', methods=['POST'])
def guess():
    data = request.get_json()
    logging.debug(f"Received request data for /guess: {data}")

    # Extract game_id from the request body
    game_id = data.get('game_id')
    logging.debug(f"Game ID from request: {game_id}")

    # Also check headers for game_id (this is for the proxy setup)
    if not game_id and request.headers.get('X-Game-Id'):
        game_id = request.headers.get('X-Game-Id')
        logging.debug(f"Game ID from headers: {game_id}")

    # Get user_id from session or token
    user_id = session.get('user_id')
    if not user_id:
        auth_header = request.headers.get('Authorization')
        if auth_header and auth_header.startswith('Bearer '):
            token = auth_header.split(' ')[1]
            try:
                user_id = validate_token(token)
                logging.debug(f"Authenticated via token: user_id={user_id}")
            except Exception as e:
                logging.debug(f"Token validation failed: {e}")

    # First try to get game state from the game_states dictionary
    game_state = None
    if game_id and game_id in game_states:
        logging.debug(f"Found game state for game_id: {game_id}")
        game_state = game_states[game_id]

    # If not found in dictionary, try the session
    if not game_state:
        game_state = session.get('game_state')
        logging.debug(
            f"Game state from session: {'Found' if game_state else 'Not found'}"
        )

    # If still no game state, we need to create a new game
    if not game_state:
        logging.debug("No game state found - starting new game")
        encrypted, encrypted_frequency, unique_original_letters = start_game()

        # Generate a new game_id
        new_game_id = str(uuid.uuid4())
        game_state = session.get('game_state')
        game_state['game_id'] = new_game_id
        game_states[new_game_id] = game_state

        # If user is authenticated, save the new game state
        if user_id:
            save_game_state(user_id, new_game_id, game_state)

        return jsonify({
            'display': get_display(encrypted, [], {}),
            'mistakes': 0,
            'correctly_guessed': [],
            'error': 'Session expired, a new game was started',
            'game_id': new_game_id  # Send the new game_id to the client
        })

    # Process the guess
    encrypted_letter = data['encrypted_letter']
    guessed_letter = data['guessed_letter']

    # Process the guess
    if validate_guess(encrypted_letter, guessed_letter,
                      game_state['reverse_mapping'],
                      game_state['correctly_guessed'], game_state['mistakes']):
        # Correct guess
        game_state['mistakes'] = game_state['mistakes']
    else:
        # Incorrect guess
        game_state['mistakes'] += 1

    display = get_display(game_state['encrypted_paragraph'],
                          game_state['correctly_guessed'],
                          game_state['reverse_mapping'])

    # Save state in both session and game_states
    session['game_state'] = game_state
    if game_id:
        game_states[game_id] = game_state

        # NEW: If user is authenticated, update the game state in the database
        if user_id:
            sync_game_state_with_session(game_id, user_id)
            logging.debug(
                f"Synced game state to DB for user {user_id}, game {game_id}")

    response_data = {
        'display': display,
        'mistakes': game_state['mistakes'],
        'correctly_guessed': game_state['correctly_guessed']
    }

    logging.debug(f"Returning response: {response_data}")
    return jsonify(response_data)


# @app.route('/hint', methods=['OPTIONS'])
# def options_hint():
#     print("options hint")
#     # Handle preflight request for CORS
#     response = app.make_default_options_response()
#     headers = response.headers
#     headers['Access-Control-Allow-Origin'] = '*'
#     headers['Access-Control-Allow-Methods'] = 'POST, OPTIONS'
#     headers['Access-Control-Allow-Headers'] = 'Content-Type, Authorization, X-Game-Id'
#     headers['Access-Control-Allow-Credentials'] = 'true'
#     return response


@app.route('/hint', methods=['POST'])
def hint():
    print("hint triggered")
    try:
        # Extract game_id from the request body
        data = request.get_json() or {}
        game_id = data.get('game_id')
        print("hint request:", data, game_id)

        # Also check headers for game_id
        if not game_id and request.headers.get('X-Game-Id'):
            game_id = request.headers.get('X-Game-Id')

        # Get user_id from session or token
        user_id = session.get('user_id')
        if not user_id:
            auth_header = request.headers.get('Authorization')
            if auth_header and auth_header.startswith('Bearer '):
                token = auth_header.split(' ')[1]
                try:
                    user_id = validate_token(token)
                    print(f"Authenticated via token: user_id={user_id}")
                except Exception as e:
                    print(f"Token validation failed: {e}")

        # Initialize game_state as None
        game_state = None

        # First try to get game state from the game_states dictionary
        if game_id and game_id in game_states:
            game_state = game_states[game_id]

        # If not found in dictionary, try the session
        if not game_state:
            game_state = session.get('game_state')

        # If still no game state, start a new game
        if not game_state:
            encrypted, encrypted_frequency, unique_original_letters = start_game(
            )

            # Generate a new game_id
            new_game_id = str(uuid.uuid4())
            game_state = session.get('game_state')
            game_state['game_id'] = new_game_id
            game_states[new_game_id] = game_state

            # If user is authenticated, save the new game state
            if user_id:
                save_game_state(user_id, new_game_id, game_state)

            # Return the new game with session expired error
            return jsonify({
                'display': get_display(encrypted, [], {}),
                'mistakes': 0,
                'correctly_guessed': [],
                'error': 'Session expired, a new game was started',
                'game_id': new_game_id
            })

        # Process the hint request
        all_encrypted = list(game_state['mapping'].values())
        unmapped = [
            letter for letter in all_encrypted
            if letter not in game_state['correctly_guessed']
        ]

        if unmapped:
            # Find letters that are used in the encrypted text
            used_n_mapped = [
                x for x in unmapped if x in game_state['encrypted_paragraph']
            ]

            # Choose a random unmapped letter
            letter = random.choice(used_n_mapped)
            game_state['correctly_guessed'].append(letter)
            game_state['mistakes'] += 1

            # Get the updated display
            display = get_display(game_state['encrypted_paragraph'],
                                  game_state['correctly_guessed'],
                                  game_state['reverse_mapping'])

            # Save state in both session and game_states
            session['game_state'] = game_state
            if game_id:
                game_states[game_id] = game_state

                # NEW: If user is authenticated, update the game state in the database
                if user_id:
                    sync_game_state_with_session(game_id, user_id)
                    print(
                        f"Synced game state to DB after hint for user {user_id}, game {game_id}"
                    )

            # Return the results
            return jsonify({
                'display': display,
                'mistakes': game_state['mistakes'],
                'correctly_guessed': game_state['correctly_guessed']
            })
        else:
            # All letters are already mapped
            return jsonify({
                'display':
                get_display(game_state['encrypted_paragraph'],
                            game_state['correctly_guessed'],
                            game_state['reverse_mapping']),
                'mistakes':
                game_state['mistakes'],
                'correctly_guessed':
                game_state['correctly_guessed']
            })
    except Exception as e:
        # Log the error for debugging
        logging.error(f"Error in hint endpoint: {str(e)}")

        # Return a safe response
        return jsonify({
            'error': 'Server error processing hint',
            'display': '',
            'mistakes': 0,
            'correctly_guessed': []
        }), 500


# User and score tracking functions
def register_user(username):
    """Register a new user and return their ID"""
    user_id = str(uuid.uuid4())
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('INSERT INTO users (id, username) VALUES (?, ?)',
                           (user_id, username))
            conn.commit()
            return user_id
    except sqlite3.IntegrityError:
        # Username already exists
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT id FROM users WHERE username = ?',
                           (username, ))
            result = cursor.fetchone()
            return result['id'] if result else None


def save_game_score(user_id, score, mistakes, completed=True):
    """Save a game score for a user"""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            'INSERT INTO game_scores (user_id, score, mistakes, completed) VALUES (?, ?, ?, ?)',
            (user_id, score, mistakes, completed))
        conn.commit()
        return cursor.lastrowid


def get_user_scores(user_id, limit=10):
    """Get recent scores for a user"""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            'SELECT * FROM game_scores WHERE user_id = ? ORDER BY created_at DESC LIMIT ?',
            (user_id, limit))
        return [dict(row) for row in cursor.fetchall()]


def validate_guess(encrypted_letter, guessed_letter, reverse_mapping,
                   correctly_guessed, mistakes):
    if reverse_mapping[encrypted_letter] == guessed_letter:
        if encrypted_letter not in correctly_guessed:
            correctly_guessed.append(encrypted_letter)
        return True
    return False


def provide_hint(game_state):
    all_encrypted = list(game_state['mapping'].values())
    unmapped = [
        letter for letter in all_encrypted
        if letter not in game_state['correctly_guessed']
    ]
    if unmapped:
        used_n_mapped = [
            x for x in unmapped if x in game_state['encrypted_paragraph']
        ]
        letter = random.choice(used_n_mapped)
        game_state['correctly_guessed'].append(letter)
        game_state['mistakes'] += 1
        r1 = get_display(game_state['encrypted_paragraph'],
                         game_state['correctly_guessed'],
                         game_state['reverse_mapping'])
        r2 = game_state['mistakes']
        r3 = game_state['correctly_guessed']
        print(r1, r2, r3)
        return r1, r2, r3
    return None, game_state['mistakes']


# Add this function to handle OPTIONS requests for any endpoint


@app.route('/<path:path>', methods=['OPTIONS'])
def handle_options(path):
    response = app.make_default_options_response()
    headers = response.headers

    # Configure CORS headers for the preflight response
    headers['Access-Control-Allow-Origin'] = request.headers.get('Origin', '*')
    headers['Access-Control-Allow-Methods'] = 'GET, POST, PUT, DELETE, OPTIONS'
    # Add X-User-ID to the allowed headers list here too
    headers[
        'Access-Control-Allow-Headers'] = 'Content-Type, Authorization, X-Game-Id, X-User-ID, X-Session-ID, Accept'
    headers['Access-Control-Allow-Credentials'] = 'true'
    headers[
        'Access-Control-Max-Age'] = '3600'  # Cache preflight response for 1 hour

    return response


@app.route('/completed', methods=['POST'])
def mark_game_completed():
    data = request.get_json()
    game_id = data.get('game_id')

    if not game_id:
        return jsonify({"error": "Missing game_id"}), 400

    # Get user_id from session or token
    user_id = session.get('user_id')

    if not user_id:
        auth_header = request.headers.get('Authorization')
        if auth_header and auth_header.startswith('Bearer '):
            token = auth_header.split(' ')[1]
            try:
                user_id = validate_token(token)
            except Exception as e:
                print(f"Token validation failed: {e}")

    # Delete the game state since it's completed
    if user_id:
        delete_game_state(user_id=user_id)
    else:
        delete_game_state(game_id=game_id)

    return jsonify({"success": True, "message": "Game marked as completed"})


@app.route('/get_attribution', methods=['GET'])
def get_attribution():
    # Extract game_id from the request parameters
    game_id = request.args.get('game_id')
    logging.debug(f"Get attribution request for game_id: {game_id}")

    # Also check headers for game_id
    if not game_id and request.headers.get('X-Game-Id'):
        game_id = request.headers.get('X-Game-Id')
        logging.debug(f"Game ID from headers: {game_id}")

    # Initialize game_state as None
    game_state = None

    # First try to get game state from the game_states dictionary
    if game_id and game_id in game_states:
        logging.debug(f"Found game state for game_id: {game_id}")
        game_state = game_states[game_id]

    # If not found in dictionary, try the session
    if not game_state:
        game_state = session.get('game_state')
        logging.debug(
            f"Game state from session: {'Found' if game_state else 'Not found'}"
        )

    # If still no game state, return empty attribution
    if not game_state:
        logging.debug("No game state found for attribution request")
        return jsonify({
            'major_attribution': '',
            'minor_attribution': '',
            'error': 'Game not found or session expired'
        })

    # Return the attribution data
    return jsonify({
        'major_attribution': game_state.get('major_attribution', ''),
        'minor_attribution': game_state.get('minor_attribution', '')
    })


@app.route('/save_quote', methods=['POST'])
def save_quote():
    game_state = session.get('game_state')

    if not game_state:
        return jsonify({'error': 'No active game found'}), 400

    # Extract quote and attribution data
    quote = game_state.get('original_paragraph', '')
    major_attribution = game_state.get('major_attribution', '')
    minor_attribution = game_state.get('minor_attribution', '')

    if not quote:
        return jsonify({'error': 'No quote to save'}), 400

    # File to save to
    csv_path = 'curated.csv'
    file_exists = os.path.isfile(csv_path)

    # Check if quote already exists in the file
    if file_exists:
        with open(csv_path, 'r', encoding='utf-8') as csvfile:
            reader = csv.DictReader(csvfile)
            for row in reader:
                if row.get('Quote') == quote:
                    return jsonify(
                        {'message':
                         'Quote already saved in curated list'}), 200

    # Append the quote to the file
    with open(csv_path, 'a', newline='', encoding='utf-8') as csvfile:
        fieldnames = ['Quote', 'Major Attribution', 'Minor Attribution']
        writer = csv.DictWriter(csvfile, fieldnames=fieldnames)

        # Write header if file didn't exist
        if not file_exists:
            writer.writeheader()

        # Write the quote data
        writer.writerow({
            'Quote': quote,
            'Major Attribution': major_attribution,
            'Minor Attribution': minor_attribution
        })

    return jsonify({'message': 'Quote saved successfully'}), 200


@app.route('/check_active_game', methods=['GET'])
def check_active_game():
    """
    Check if the current user has an active game
    Returns game_id if one exists, or null if none
    """
    # Get user_id from session or token
    user_id = session.get('user_id')

    # If not in session, check for token in Authorization header
    if not user_id:
        auth_header = request.headers.get('Authorization')
        if auth_header and auth_header.startswith('Bearer '):
            token = auth_header.split(' ')[1]
            try:
                user_id = validate_token(token)
            except Exception as e:
                print(f"Token validation failed: {e}")

    # If we don't have a user_id, can't check for active games
    if not user_id:
        return jsonify({
            "authenticated": False,
            "message": "Authentication required to check for active games",
            "has_active_game": False
        }), 401

    # Check for an active game
    active_game = get_active_game_state(user_id)

    if active_game:
        # Return minimal information about the active game
        return jsonify({
            "authenticated":
            True,
            "has_active_game":
            True,
            "game_id":
            active_game['game_id'],
            "last_updated":
            active_game.get('last_updated'),
            "encrypted_length":
            len(active_game['encrypted_paragraph']),
            "mistakes":
            active_game['mistakes'],
            "progress_percentage":
            round((len(active_game['correctly_guessed']) / len(
                set(c for c in active_game['encrypted_paragraph']
                    if c.isalpha()))) *
                  100) if active_game['correctly_guessed'] else 0
        })
    else:
        # No active game
        return jsonify({"authenticated": True, "has_active_game": False})


@app.route('/debug/game_states', methods=['GET'])
def debug_game_states():
    """
    Debug endpoint to view all active game states in the database
    """
    # Only allow in development mode
    if ENV != 'development':
        return jsonify(
            {"error":
             "Debug endpoints only available in development mode"}), 403

    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT * FROM active_game_states')
            rows = cursor.fetchall()

            # Convert rows to dictionaries
            game_states_list = []
            for row in rows:
                game_state_dict = dict(row)

                # Parse JSON fields
                try:
                    game_state_dict['mapping'] = json.loads(
                        game_state_dict['mapping'])
                    game_state_dict['correctly_guessed'] = json.loads(
                        game_state_dict['correctly_guessed'])
                    if 'reverse_mapping' in game_state_dict and game_state_dict[
                            'reverse_mapping']:
                        game_state_dict['reverse_mapping'] = json.loads(
                            game_state_dict['reverse_mapping'])
                except Exception as e:
                    logging.error(f"Error parsing JSON fields: {e}")

                game_states_list.append(game_state_dict)

            return jsonify({
                "count": len(game_states_list),
                "game_states": game_states_list
            })

    except Exception as e:
        logging.error(f"Error in debug endpoint: {e}")
        return jsonify({"error": str(e)}), 500


@app.route('/debug/save_game_state', methods=['POST'])
def debug_save_game_state():
    """
    Debug endpoint to manually save the current session game state to the database
    """
    # Only allow in development mode
    if ENV != 'development':
        return jsonify(
            {"error":
             "Debug endpoints only available in development mode"}), 403

    # Get user_id and game_id
    user_id = session.get('user_id')
    game_state = session.get('game_state')

    if not user_id:
        return jsonify({"error": "No user_id in session"}), 400

    if not game_state:
        return jsonify({"error": "No game_state in session"}), 400

    game_id = game_state.get('game_id')
    if not game_id:
        # Generate a game_id if none exists
        game_id = str(uuid.uuid4())
        game_state['game_id'] = game_id

    # Try to save to database
    success = save_game_state(user_id, game_id, game_state)

    if success:
        return jsonify({
            "success":
            True,
            "message":
            f"Game state saved for user {user_id}, game {game_id}"
        })
    else:
        return jsonify({
            "success": False,
            "error": "Failed to save game state"
        }), 500


@app.route('/debug/load_game_state', methods=['GET'])
def debug_load_game_state():
    """
    Debug endpoint to manually load a game state from the database into the session
    """
    # Only allow in development mode
    if ENV != 'development':
        return jsonify(
            {"error":
             "Debug endpoints only available in development mode"}), 403

    # Get user_id
    user_id = session.get('user_id')

    if not user_id:
        return jsonify({"error": "No user_id in session"}), 400

    # Try to load from database
    success = load_game_state_to_session(user_id)

    if success:
        game_state = session.get('game_state')
        return jsonify({
            "success": True,
            "message": f"Game state loaded for user {user_id}",
            "game_id": game_state.get('game_id'),
            "game_state": {
                "encrypted_paragraph": game_state.get('encrypted_paragraph'),
                "correctly_guessed": game_state.get('correctly_guessed'),
                "mistakes": game_state.get('mistakes')
            }
        })
    else:
        return jsonify({
            "success": False,
            "error": "No active game found for user"
        }), 404


if __name__ == '__main__':
    logging.info("Starting application server")
    # In production, debug should be False
    debug_mode = os.environ.get('FLASK_DEBUG', 'False').lower() == 'true'
    logging.info(f"Debug mode: {debug_mode}")
    logging.info("Running on host: 0.0.0.0, port: 8000")
    app.run(debug=debug_mode, host='0.0.0.0', port=8000)
