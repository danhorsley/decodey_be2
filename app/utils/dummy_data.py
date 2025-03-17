from datetime import datetime, timedelta
import random
import uuid
import logging
import sys
import os
import string
import math
from pathlib import Path
import csv

# Add the parent directory to sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))
from app.models import db, User, UserStats, GameScore, ActiveGameState
from werkzeug.security import generate_password_hash

# Configure logging
logging.basicConfig(level=logging.INFO, 
                   format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

def generate_username():
    """Generate a random username"""
    adjectives = [
        "Happy", "Clever", "Quick", "Calm", "Brave", "Smart", "Kind", "Wise",
        "Swift", "Bold", "Bright", "Sharp", "Keen", "Witty", "Agile", "Strong"
    ]
    nouns = [
        "Player", "Gamer", "Champion", "Hero", "Winner", "Master", "Ninja",
        "Wizard", "Warrior", "Knight", "Solver", "Sleuth", "Coder", "Hacker"
    ]
    return f"{random.choice(adjectives)}{random.choice(nouns)}{random.randint(1, 999)}"


def generate_email(username):
    """Generate a random email based on username"""
    domains = [
        "gmail.com", "yahoo.com", "hotmail.com", "outlook.com", "example.com",
        "mail.com", "icloud.com", "protonmail.com", "tutanota.com"
    ]
    return f"{username.lower()}@{random.choice(domains)}"


def create_dummy_user(username=None, email=None):
    """Create a dummy user and return user_id"""
    if not username:
        username = generate_username()
    if not email:
        email = generate_email(username)

    password = f"dummy_password_{random.randint(1000, 9999)}"

    # Create user with only the parameters the constructor expects
    user = User(
        email=email,
        username=username,
        password=password,  # This will be hashed by User.__init__
        email_consent=random.choice([True, False])
    )

    # The user_id will be generated automatically by the default lambda
    # Set created_at directly on the instance after creation
    user.created_at = datetime.utcnow() - timedelta(days=random.randint(0, 120))

    db.session.add(user)
    try:
        db.session.commit()
        logger.info(f"Created user: {username} (ID: {user.user_id})")
        return user.user_id, username
    except Exception as e:
        db.session.rollback()
        logger.error(f"Error creating user: {e}")
        return None, None


def load_quotes():
    """Load quotes from quotes.csv file"""
    quotes = []
    quotes_file = Path('quotes.csv')

    if not quotes_file.exists():
        logger.warning("quotes.csv not found, generating random content")
        # Generate some random quotes if file not found
        for _ in range(5):
            quote = ''.join(random.choice(string.ascii_letters + ' ') for _ in range(50))
            quotes.append({
                'quote': quote,
                'author': f"Author {random.randint(1, 100)}",
                'minor_attribution': f"Book {random.randint(1, 20)}"
            })
        return quotes

    try:
        with open(quotes_file, 'r') as f:
            reader = csv.DictReader(f)
            for row in reader:
                quotes.append(row)
        return quotes
    except Exception as e:
        logger.error(f"Error loading quotes: {e}")
        return []


def generate_game_id(difficulty='medium'):
    """Generate a game ID with the specified difficulty"""
    return f"{difficulty}-{str(uuid.uuid4())}"


def get_max_mistakes(difficulty):
    """Get maximum mistakes allowed for the given difficulty"""
    difficulty_settings = {
        'easy': 8,
        'medium': 6,
        'hard': 4
    }
    return difficulty_settings.get(difficulty, 6)


def calculate_score(difficulty, mistakes, time_taken):
    """Calculate game score based on difficulty, mistakes and time taken"""
    # Base difficulty multipliers
    difficulty_multipliers = {'easy': 1, 'medium': 2, 'hard': 4}

    # Base score calculation
    base_score = 1000 * difficulty_multipliers.get(difficulty, 1)

    # Mistake penalty (exponential)
    mistake_factor = math.exp(-0.2 * mistakes)

    # Time factor (faster = higher score, with diminishing returns)
    time_factor = math.exp(-0.001 * time_taken)

    final_score = int(base_score * mistake_factor * time_factor)
    return max(final_score, 1)  # Ensure minimum score of 1


def simulate_game(user_id, game_number, total_games, quotes):
    """Simulate a game with realistic progression"""
    # Get a random quote
    quote_data = random.choice(quotes)
    quote = quote_data['quote'].replace('"', '')  # Remove quotation marks

    # Choose difficulty with weighted distribution
    difficulties = ["easy", "medium", "hard"]
    difficulty_weights = [0.2, 0.6, 0.2]
    difficulty = random.choices(difficulties, weights=difficulty_weights)[0]

    # Create game_id with difficulty encoded
    game_id = generate_game_id(difficulty)

    # Game type - most are regular, some are daily challenges
    game_types = ["regular", "daily", "speedrun"]
    game_type_weights = [0.7, 0.2, 0.1]
    game_type = random.choices(game_types, weights=game_type_weights)[0]

    # Calculate difficulty and progress-based parameters
    max_mistakes = get_max_mistakes(difficulty)
    progress_factor = game_number / total_games  # User gets better over time

    # Mistakes (fewer mistakes as they progress)
    mistake_chance = max(0.1, 0.8 - (0.5 * progress_factor))
    mistakes = random.randint(0, int(max_mistakes * mistake_chance))

    # Game completed or abandoned?
    completed = not (random.random() < 0.1)  # 10% chance of abandoning game
    won = completed and mistakes < max_mistakes  # Won if completed and mistakes within limit

    # Time taken (faster as they progress)
    min_time = 30  # Minimum 30 seconds
    max_time = 300  # Maximum 5 minutes
    time_taken = int(max_time - ((max_time - min_time) * progress_factor * random.uniform(0.7, 1.0)))

    # Score
    score = calculate_score(difficulty, mistakes, time_taken) if won else 0

    # Randomly distribute game dates within the last 90 days
    end_date = datetime.utcnow()
    start_date = end_date - timedelta(days=90)
    days_between = (end_date - start_date).days
    random_days = random.randint(0, days_between)
    game_date = start_date + timedelta(days=random_days)

    # Create GameScore entry without the difficulty parameter
    game = GameScore(
        game_id=game_id,  # The difficulty is encoded in the game_id
        user_id=user_id,
        score=score,
        mistakes=mistakes,
        time_taken=time_taken,
        game_type=game_type,
        challenge_date=game_date.strftime('%Y-%m-%d') if game_type == "daily" else None,
        completed=won,  # Only won games are marked as completed
        created_at=game_date
    )

    return game


def update_stats_for_user(user_id):
    """Update UserStats based on GameScore entries for a user"""
    try:
        # Get all games for the user
        games = GameScore.query.filter_by(user_id=user_id).order_by(GameScore.created_at).all()

        if not games:
            return

        # Get or create user stats
        user_stats = UserStats.query.get(user_id)
        if not user_stats:
            user_stats = UserStats(user_id=user_id)
            db.session.add(user_stats)

        # Calculate stats
        total_games = len(games)
        total_score = sum(game.score for game in games)
        games_won = sum(1 for game in games if game.completed)

        # Calculate streaks
        current_streak = 0
        max_streak = 0
        current_noloss_streak = 0
        max_noloss_streak = 0

        # Sort games by date
        sorted_games = sorted(games, key=lambda x: x.created_at)

        for game in sorted_games:
            if game.completed:  # Won
                current_streak += 1
                current_noloss_streak += 1
            else:  # Lost or abandoned
                current_streak = 0
                if not game.completed:  # Only reset noloss streak on completed but lost games
                    current_noloss_streak = 0

            max_streak = max(max_streak, current_streak)
            max_noloss_streak = max(max_noloss_streak, current_noloss_streak)

        # Calculate weekly score
        week_start = datetime.utcnow() - timedelta(days=datetime.utcnow().weekday())
        weekly_score = sum(game.score for game in games if game.created_at >= week_start)

        # Update UserStats
        user_stats.total_games_played = total_games
        user_stats.games_won = games_won
        user_stats.cumulative_score = total_score
        user_stats.current_streak = current_streak
        user_stats.max_streak = max_streak
        user_stats.current_noloss_streak = current_noloss_streak
        user_stats.max_noloss_streak = max_noloss_streak
        user_stats.highest_weekly_score = max(weekly_score, user_stats.highest_weekly_score or 0)
        user_stats.last_played_date = sorted_games[-1].created_at if sorted_games else None

        db.session.commit()
        logger.info(f"Updated stats for user {user_id}")

    except Exception as e:
        db.session.rollback()
        logger.error(f"Error updating stats for user {user_id}: {e}")


def generate_dummy_data(num_users=25, min_games=10, max_games=50):
    """Generate dummy data for users, games, and stats"""
    logger.info(f"Starting to generate dummy data for {num_users} users")

    # Load quotes for generating games
    quotes = load_quotes()
    if not quotes:
        logger.error("Failed to load quotes, aborting")
        return []

    user_data = []

    # Create users and their games
    for i in range(num_users):
        # Create user
        user_id, username = create_dummy_user()
        if not user_id:
            continue

        user_data.append((user_id, username))

        # Generate random number of games for this user
        num_games = random.randint(min_games, max_games)
        logger.info(f"Generating {num_games} games for user {username}")

        # Simulate games with increasing skill over time
        for game_num in range(1, num_games + 1):
            game = simulate_game(user_id, game_num, num_games, quotes)
            db.session.add(game)

            # Commit every 10 games to avoid large transactions
            if game_num % 10 == 0:
                db.session.commit()
                logger.info(f"Generated {game_num}/{num_games} games for user {username}")

        # Commit remaining games
        db.session.commit()

        # Update user stats after games are created
        update_stats_for_user(user_id)

        # Occasionally create an active game for a user (20% chance)
        if random.random() < 0.2:
            create_active_game(user_id, quotes)

    logger.info(f"Dummy data generation complete. Created {len(user_data)} users with games.")
    return user_data


def create_active_game(user_id, quotes):
    """Create an active game for a user"""
    try:
        # Pick a random quote
        quote_data = random.choice(quotes)
        quote = quote_data['quote'].replace('"', '')
        author = quote_data['author']
        minor_attribution = quote_data['minor_attribution']

        # Choose difficulty
        difficulty = random.choice(['easy', 'medium', 'hard'])
        game_id = generate_game_id(difficulty)

        # Generate some random encrypted text and mapping
        alphabet = string.ascii_uppercase
        shuffled = list(alphabet)
        random.shuffle(shuffled)
        mapping = dict(zip(alphabet, shuffled))
        reverse_mapping = {v: k for k, v in mapping.items()}

        # Encrypt the quote
        encrypted_paragraph = ''
        for char in quote.upper():
            if char in mapping:
                encrypted_paragraph += mapping[char]
            else:
                encrypted_paragraph += char

        # Random progress in the game (between 20-80% complete)
        unique_encrypted_letters = set(c for c in encrypted_paragraph if c.isalpha())
        num_to_guess = random.randint(int(len(unique_encrypted_letters) * 0.2), 
                                     int(len(unique_encrypted_letters) * 0.8))

        # Random selection of letters already guessed
        correctly_guessed = random.sample(list(unique_encrypted_letters), num_to_guess)

        # Random number of mistakes
        max_mistakes = get_max_mistakes(difficulty)
        mistakes = random.randint(0, max_mistakes - 1)  # Ensure game isn't already lost

        # Create the active game state
        active_game = ActiveGameState(
            user_id=user_id,
            game_id=game_id,
            original_paragraph=quote,
            encrypted_paragraph=encrypted_paragraph,
            mapping=mapping,
            reverse_mapping=reverse_mapping,
            correctly_guessed=correctly_guessed,
            mistakes=mistakes,
            major_attribution=author,
            minor_attribution=minor_attribution,
            created_at=datetime.utcnow() - timedelta(minutes=random.randint(5, 60)),
            last_updated=datetime.utcnow()
        )

        db.session.add(active_game)
        db.session.commit()
        logger.info(f"Created active game for user {user_id}")
        return True
    except Exception as e:
        db.session.rollback()
        logger.error(f"Error creating active game: {e}")
        return False


def main():
    """Entry point for dummy data generation"""
    print("Starting dummy data generation...")
    try:
        users = generate_dummy_data()
        if users:
            print(f"Successfully created {len(users)} dummy users with game data")
            print("Sample usernames:")
            for _, username in users[:5]:
                print(f"- {username}")
        else:
            print("No users were created")
    except Exception as e:
        logging.error(f"Error generating dummy data: {e}")
        print(f"Error: {e}")


if __name__ == "__main__":
    main()