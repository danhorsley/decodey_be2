
import sqlite3
import uuid
import random
import datetime
import time
import logging
import os
import sys
from contextlib import contextmanager

# Add the parent directory to sys.path to import local modules
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from be.init_db import DATABASE_PATH

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

@contextmanager
def get_db_connection():
    conn = sqlite3.connect(DATABASE_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
    finally:
        conn.close()

def generate_username():
    """Generate a random username"""
    adjectives = ["Happy", "Clever", "Quick", "Calm", "Brave", "Smart", "Kind", "Wise", "Swift", "Bold"]
    nouns = ["Player", "Gamer", "Champion", "Hero", "Winner", "Master", "Ninja", "Wizard", "Warrior", "Knight"]
    return f"{random.choice(adjectives)}{random.choice(nouns)}{random.randint(1, 999)}"

def generate_email(username):
    """Generate a random email based on username"""
    domains = ["gmail.com", "yahoo.com", "hotmail.com", "outlook.com", "example.com"]
    return f"{username.lower()}@{random.choice(domains)}"

def generate_password():
    """Generate a simple password hash (for dummy data only)"""
    return f"dummy_password_{random.randint(1000, 9999)}"

def create_dummy_user():
    """Create a dummy user and return user_id"""
    user_id = str(uuid.uuid4())
    username = generate_username()
    email = generate_email(username)
    password = generate_password()
    
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO users (user_id, email, username, password_hash, auth_type) VALUES (?, ?, ?, ?, ?)",
            (user_id, email, username, password, "emailauth")
        )
        conn.commit()
    
    logging.info(f"Created user: {username} (ID: {user_id})")
    return user_id, username

def initialize_user_stats(user_id):
    """Initialize empty stats for a user"""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO user_stats (user_id, current_streak, max_streak, current_noloss_streak, max_noloss_streak, total_games_played, cumulative_score, highest_weekly_score) VALUES (?, 0, 0, 0, 0, 0, 0, 0)",
            (user_id,)
        )
        conn.commit()
    
    logging.info(f"Initialized stats for user: {user_id}")

def generate_game_id():
    """Generate a unique game ID"""
    return str(uuid.uuid4())

def random_date(start_date, end_date):
    """Generate a random date between start_date and end_date"""
    time_between_dates = end_date - start_date
    days_between_dates = time_between_dates.days
    random_number_of_days = random.randrange(days_between_dates)
    return start_date + datetime.timedelta(days=random_number_of_days)

def simulate_game(user_id, game_number, total_games):
    """Simulate a game with realistic progression"""
    # Game parameters
    difficulties = ["easy", "normal", "hard"]
    difficulty_weights = [0.2, 0.6, 0.2]  # 20% easy, 60% normal, 20% hard
    game_types = ["regular", "daily", "speedrun"]
    game_type_weights = [0.7, 0.2, 0.1]  # 70% regular, 20% daily, 10% speedrun
    
    # Generate game details
    game_id = generate_game_id()
    difficulty = random.choices(difficulties, weights=difficulty_weights)[0]
    game_type = random.choices(game_types, weights=game_type_weights)[0]
    
    # Score parameters - give better scores to later games to simulate improvement
    progress_factor = game_number / total_games  # 0.0 to 1.0
    
    # Base score ranges by difficulty
    score_ranges = {
        "easy": (50, 200),
        "normal": (100, 400),
        "hard": (200, 800)
    }
    
    # Calculate score with improvement over time
    min_score, max_score = score_ranges[difficulty]
    base_score = random.randint(min_score, max_score)
    improvement_bonus = int(progress_factor * max_score * 0.5)  # Up to 50% bonus for improvement
    score = base_score + improvement_bonus
    
    # Mistakes (fewer mistakes as they progress)
    max_mistakes_possible = 5
    mistake_chance = max(0.1, 0.8 - (0.5 * progress_factor))  # From 80% to 30% chance
    mistakes = random.randint(0, int(max_mistakes_possible * mistake_chance))
    
    # Time taken (faster as they progress)
    min_time = 30  # seconds
    max_time = 300  # seconds
    time_taken = int(max_time - ((max_time - min_time) * progress_factor * random.uniform(0.7, 1.0)))
    
    # Is the game completed successfully?
    completed = mistakes < max_mistakes_possible
    
    # Generate a random date within the last 90 days
    end_date = datetime.datetime.now()
    start_date = end_date - datetime.timedelta(days=90)
    game_date = random_date(start_date, end_date)
    
    # For daily challenges, ensure the format is YYYY-MM-DD
    challenge_date = None
    if game_type == "daily":
        challenge_date = game_date.strftime('%Y-%m-%d')
    
    return {
        "game_id": game_id,
        "score": score,
        "mistakes": mistakes,
        "time_taken": time_taken,
        "difficulty": difficulty,
        "game_type": game_type,
        "challenge_date": challenge_date,
        "completed": completed,
        "created_at": game_date.strftime('%Y-%m-%d %H:%M:%S')
    }

def record_game_and_update_stats(user_id, game_data):
    """Record a game score and update user stats"""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        
        # Insert game score
        cursor.execute(
            '''
            INSERT INTO game_scores (
                user_id, game_id, score, mistakes, time_taken, 
                difficulty, game_type, challenge_date, completed, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''',
            (
                user_id, game_data["game_id"], game_data["score"], game_data["mistakes"], 
                game_data["time_taken"], game_data["difficulty"], game_data["game_type"], 
                game_data["challenge_date"], game_data["completed"], game_data["created_at"]
            )
        )
        
        # Get current user stats
        cursor.execute("SELECT * FROM user_stats WHERE user_id = ?", (user_id,))
        stats = cursor.fetchone()
        
        if not stats:
            # No stats exist, initialize
            current_streak = 1 if game_data["completed"] else 0
            max_streak = 1 if game_data["completed"] else 0
            current_noloss_streak = 1 if game_data["completed"] else 0
            max_noloss_streak = 1 if game_data["completed"] else 0
            total_games_played = 1
            cumulative_score = game_data["score"]
            highest_weekly_score = game_data["score"]
            
            cursor.execute(
                '''
                INSERT INTO user_stats (
                    user_id, current_streak, max_streak, current_noloss_streak, max_noloss_streak,
                    total_games_played, cumulative_score, highest_weekly_score, last_played_date
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''',
                (
                    user_id, current_streak, max_streak, current_noloss_streak, max_noloss_streak,
                    total_games_played, cumulative_score, highest_weekly_score, game_data["created_at"]
                )
            )
        else:
            # Convert to dictionary for easier access
            stats_dict = dict(stats)
            
            # Update stats
            current_streak = stats_dict.get('current_streak', 0)
            max_streak = stats_dict.get('max_streak', 0)
            current_noloss_streak = stats_dict.get('current_noloss_streak', 0)
            max_noloss_streak = stats_dict.get('max_noloss_streak', 0)
            total_games_played = stats_dict.get('total_games_played', 0) + 1
            cumulative_score = stats_dict.get('cumulative_score', 0) + game_data["score"]
            
            # Update streaks
            if game_data["completed"]:
                current_streak += 1
                if current_streak > max_streak:
                    max_streak = current_streak
            else:
                current_streak = 0
            
            # No-loss streak
            if game_data["mistakes"] < 5:  # Assuming 5 is max_mistakes
                current_noloss_streak += 1
                if current_noloss_streak > max_noloss_streak:
                    max_noloss_streak = current_noloss_streak
            else:
                current_noloss_streak = 0
            
            # Calculate weekly score
            game_date = datetime.datetime.strptime(game_data["created_at"], '%Y-%m-%d %H:%M:%S')
            start_of_week = game_date - datetime.timedelta(days=game_date.weekday())
            
            cursor.execute(
                '''
                SELECT SUM(score) as weekly_score
                FROM game_scores
                WHERE user_id = ? 
                AND date(created_at) >= date(?)
                ''',
                (user_id, start_of_week.strftime('%Y-%m-%d'))
            )
            
            weekly_data = cursor.fetchone()
            weekly_score = weekly_data['weekly_score'] if weekly_data and weekly_data['weekly_score'] else 0
            
            # Update highest weekly score if needed
            highest_weekly_score = max(stats_dict.get('highest_weekly_score', 0), weekly_score)
            
            # Update user stats
            cursor.execute(
                '''
                UPDATE user_stats 
                SET 
                    current_streak = ?,
                    max_streak = ?,
                    current_noloss_streak = ?,
                    max_noloss_streak = ?,
                    total_games_played = ?,
                    cumulative_score = ?,
                    highest_weekly_score = ?,
                    last_played_date = ?
                WHERE user_id = ?
                ''',
                (
                    current_streak, max_streak, current_noloss_streak, max_noloss_streak,
                    total_games_played, cumulative_score, highest_weekly_score, 
                    game_data["created_at"], user_id
                )
            )
        
        conn.commit()

def generate_dummy_data(num_users=25, min_games=50, max_games=100):
    """Generate dummy data for users, games, and stats"""
    logging.info(f"Starting to generate dummy data for {num_users} users")
    
    user_data = []
    for i in range(num_users):
        # Create user
        user_id, username = create_dummy_user()
        user_data.append((user_id, username))
        
        # Initialize user stats
        initialize_user_stats(user_id)
        
        # Generate random number of games for this user
        num_games = random.randint(min_games, max_games)
        logging.info(f"Generating {num_games} games for user {username}")
        
        # Simulate games
        for game_num in range(1, num_games + 1):
            game_data = simulate_game(user_id, game_num, num_games)
            record_game_and_update_stats(user_id, game_data)
            
            # Log progress every 10 games
            if game_num % 10 == 0:
                logging.info(f"Generated {game_num}/{num_games} games for user {username}")
    
    logging.info(f"Dummy data generation complete. Created {num_users} users with games.")
    return user_data

if __name__ == "__main__":
    # Run the script with default values
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
