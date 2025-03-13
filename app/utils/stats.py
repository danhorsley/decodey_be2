from datetime import datetime, timedelta
from app.models import db, UserStats, GameScore
import logging

def initialize_or_update_user_stats(user_id):
    """Initialize or update user stats from GameScore data"""
    try:
        # Get or create UserStats
        user_stats = UserStats.query.get(user_id)
        if not user_stats:
            user_stats = UserStats(user_id=user_id)
            db.session.add(user_stats)

        # Get all completed games for the user
        games = GameScore.query.filter_by(
            user_id=user_id,
            completed=True
        ).order_by(GameScore.created_at).all()

        if not games:
            return

        # Calculate stats
        total_games = len(games)
        total_score = sum(game.score for game in games)
        games_won = sum(1 for game in games if game.mistakes < 5)  # Consider games with < 5 mistakes as won
        
        # Calculate current streak
        current_streak = 0
        max_streak = 0
        current_noloss_streak = 0
        max_noloss_streak = 0
        
        # Sort games by date to calculate streaks
        sorted_games = sorted(games, key=lambda x: x.created_at, reverse=True)
        
        # Calculate streaks
        for game in sorted_games:
            if game.mistakes < 5:  # Won game
                current_streak += 1
                current_noloss_streak += 1
            else:  # Lost game
                current_streak = 0
                current_noloss_streak = 0
            
            max_streak = max(max_streak, current_streak)
            max_noloss_streak = max(max_noloss_streak, current_noloss_streak)

        # Calculate weekly score
        week_start = datetime.utcnow() - timedelta(days=datetime.utcnow().weekday())
        weekly_score = sum(
            game.score for game in games 
            if game.created_at >= week_start
        )

        # Update user stats
        user_stats.total_games_played = total_games
        user_stats.games_won = games_won
        user_stats.cumulative_score = total_score
        user_stats.current_streak = current_streak
        user_stats.max_streak = max_streak
        user_stats.current_noloss_streak = current_noloss_streak
        user_stats.max_noloss_streak = max_noloss_streak
        user_stats.highest_weekly_score = max(weekly_score, user_stats.highest_weekly_score or 0)
        user_stats.last_played_date = sorted_games[0].created_at if sorted_games else None

        db.session.commit()
        logging.info(f"Successfully updated stats for user {user_id}")
        
    except Exception as e:
        db.session.rollback()
        logging.error(f"Error updating user stats: {e}")
        raise
