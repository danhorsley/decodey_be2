from datetime import datetime, timedelta
import random
import uuid
import logging
from app.models import db, User, UserStats, GameScore
from werkzeug.security import generate_password_hash


def generate_username():
    """Generate a random username"""
    adjectives = [
        "Happy", "Clever", "Quick", "Calm", "Brave", "Smart", "Kind", "Wise",
        "Swift", "Bold"
    ]
    nouns = [
        "Player", "Gamer", "Champion", "Hero", "Winner", "Master", "Ninja",
        "Wizard", "Warrior", "Knight"
    ]
    return f"{random.choice(adjectives)}{random.choice(nouns)}{random.randint(1, 999)}"


def generate_email(username):
    """Generate a random email based on username"""
    domains = [
        "gmail.com", "yahoo.com", "hotmail.com", "outlook.com", "example.com"
    ]
    return f"{username.lower()}@{random.choice(domains)}"


def create_dummy_user():
    """Create a dummy user and return user_id"""
    username = generate_username()
    email = generate_email(username)
    password = f"dummy_password_{random.randint(1000, 9999)}"

    user = User(user_id=str(uuid.uuid4()),
                email=email,
                username=username,
                password_hash=generate_password_hash(password))

    db.session.add(user)
    db.session.commit()

    logging.info(f"Created user: {username} (ID: {user.user_id})")
    return user.user_id, username


def simulate_game(user_id, game_number, total_games):
    """Simulate a game with realistic progression"""
    difficulties = ["easy", "normal", "hard"]
    difficulty_weights = [0.2, 0.6, 0.2]
    game_types = ["regular", "daily", "speedrun"]
    game_type_weights = [0.7, 0.2, 0.1]

    difficulty = random.choices(difficulties, weights=difficulty_weights)[0]
    game_type = random.choices(game_types, weights=game_type_weights)[0]

    # Score parameters with improvement over time
    progress_factor = game_number / total_games
    score_ranges = {
        "easy": (50, 200),
        "normal": (100, 400),
        "hard": (200, 800)
    }

    min_score, max_score = score_ranges[difficulty]
    base_score = random.randint(min_score, max_score)
    improvement_bonus = int(progress_factor * max_score * 0.5)
    score = base_score + improvement_bonus

    # Mistakes (fewer mistakes as they progress)
    max_mistakes_possible = 5
    mistake_chance = max(0.1, 0.8 - (0.5 * progress_factor))
    mistakes = random.randint(0, int(max_mistakes_possible * mistake_chance))

    # Time taken (faster as they progress)
    min_time = 30
    max_time = 300
    time_taken = int(max_time - (
        (max_time - min_time) * progress_factor * random.uniform(0.7, 1.0)))

    # Game completion status
    completed = mistakes < max_mistakes_possible

    # Random date within last 90 days
    end_date = datetime.utcnow()
    start_date = end_date - timedelta(days=90)
    days_between = (end_date - start_date).days
    random_days = random.randint(0, days_between)
    game_date = start_date + timedelta(days=random_days)

    game = GameScore(game_id=str(uuid.uuid4()),
                     user_id=user_id,
                     score=score,
                     mistakes=mistakes,
                     time_taken=time_taken,
                     difficulty=difficulty,
                     game_type=game_type,
                     challenge_date=game_date.strftime('%Y-%m-%d')
                     if game_type == "daily" else None,
                     completed=completed,
                     created_at=game_date)

    return game


def generate_dummy_data(num_users=25, min_games=50, max_games=100):
    """Generate dummy data for users and their games"""
    logging.info(f"Starting to generate dummy data for {num_users} users")

    user_data = []
    for i in range(num_users):
        # Create user
        user_id, username = create_dummy_user()
        user_data.append((user_id, username))

        # Generate random number of games
        num_games = random.randint(min_games, max_games)
        logging.info(f"Generating {num_games} games for user {username}")

        # Simulate games
        for game_num in range(1, num_games + 1):
            game = simulate_game(user_id, game_num, num_games)
            db.session.add(game)

            if game_num % 10 == 0:
                db.session.commit()
                logging.info(
                    f"Generated {game_num}/{num_games} games for user {username}"
                )

        db.session.commit()

        # Initialize user stats after games are created
        from app.utils.stats import initialize_or_update_user_stats
        initialize_or_update_user_stats(user_id)

    logging.info(
        f"Dummy data generation complete. Created {num_users} users with games."
    )
    return user_data


def main():
    """Entry point for dummy data generation"""
    print("Starting dummy data generation...")
    try:
        users = generate_dummy_data()
        print(f"Successfully created {len(users)} dummy users with game data")
        print("Sample usernames:")
        for _, username in users[:5]:
            print(f"- {username}")
    except Exception as e:
        logging.error(f"Error generating dummy data: {e}")
        print(f"Error: {e}")


if __name__ == "__main__":
    main()
