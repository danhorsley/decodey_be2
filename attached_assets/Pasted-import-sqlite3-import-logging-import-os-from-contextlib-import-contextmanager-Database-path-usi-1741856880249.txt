import sqlite3
import logging
import os
from contextlib import contextmanager

# Database path - using different files for dev and prod
ENV = os.environ.get('FLASK_ENV', 'development')
if ENV == 'production':
    DATABASE_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)),
                                 'game.db')  # Production database
else:
    DATABASE_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)),
                                 'dev_game.db')  # Development database

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler()])


@contextmanager
def get_db_connection():
    conn = sqlite3.connect(DATABASE_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
    finally:
        conn.close()


def init_db():
    logging.info(f"Initializing SQLite database at {DATABASE_PATH}")
    with get_db_connection() as conn:
        cursor = conn.cursor()

        # Create users table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS users (
                user_id TEXT PRIMARY KEY,
                email TEXT UNIQUE,
                username TEXT UNIQUE, 
                password_hash TEXT,
                auth_type TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                settings JSON
            )
        ''')

        # Create user_stats table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS user_stats (
                user_id TEXT,
                current_streak INTEGER DEFAULT 0,         -- Original streak (games completed)
                max_streak INTEGER DEFAULT 0,             -- Max of original streak
                current_noloss_streak INTEGER DEFAULT 0,  -- Streak without any losses
                max_noloss_streak INTEGER DEFAULT 0,      -- Max of no-loss streak
                total_games_played INTEGER DEFAULT 0,
                cumulative_score INTEGER DEFAULT 0,
                highest_weekly_score INTEGER DEFAULT 0,   -- Changed from monthly to weekly
                last_played_date TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users (user_id)
            )
        ''')

        # Create enhanced game_scores table with game types
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS game_scores (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT,
                game_id TEXT,
                score INTEGER,
                mistakes INTEGER,
                time_taken INTEGER,
                difficulty TEXT,
                game_type TEXT DEFAULT 'regular',
                challenge_date TEXT,
                completed BOOLEAN DEFAULT 1,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users (user_id)
            )
        ''')

        # Create unique indexes
        cursor.execute('''
            CREATE UNIQUE INDEX IF NOT EXISTS idx_user_game 
            ON game_scores (user_id, game_id)
        ''')

        cursor.execute('''
            CREATE UNIQUE INDEX IF NOT EXISTS idx_user_daily 
            ON game_scores (user_id, challenge_date) 
            WHERE game_type = 'daily'
        ''')

        # Create daily challenges table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS daily_challenges (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                challenge_date TEXT UNIQUE,
                quote_text TEXT,
                major_attribution TEXT,
                minor_attribution TEXT,
                difficulty TEXT DEFAULT 'normal',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')

        # Create speedrun configs table for different speedrun modes
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS speedrun_configs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                config_name TEXT UNIQUE,
                description TEXT,
                time_limit INTEGER,
                difficulty TEXT,
                enabled BOOLEAN DEFAULT 1
            )
        ''')

        #create active game db
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS active_game_states (
                user_id TEXT PRIMARY KEY,  
                game_id TEXT UNIQUE,
                original_paragraph TEXT,
                encrypted_paragraph TEXT,
                mapping TEXT,              
                reverse_mapping TEXT,      -- Add reverse_mapping field
                correctly_guessed TEXT,    
                mistakes INTEGER DEFAULT 0,
                major_attribution TEXT,
                minor_attribution TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')

        # Add index for game_id
        cursor.execute('''
            CREATE INDEX IF NOT EXISTS idx_active_games_game_id 
            ON active_game_states (game_id)
        ''')
        conn.commit()
        logging.info("Database initialized successfully")


# Run initialization if script is executed directly
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    init_db()
