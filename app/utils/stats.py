from sqlalchemy import func
from datetime import datetime, timedelta
from app.models import db, UserStats, GameScore
import logging


def get_max_mistakes_for_game(game):
    """Get the maximum mistakes allowed for a game based on its difficulty"""
    difficulty = game.game_id.split(
        '-')[0] if '-' in game.game_id else 'medium'
    max_mistakes = {
        'easy': 8,
        'medium': 5,
        'hard': 3
    }.get(difficulty, 5)  # Default to medium if unknown
    return max_mistakes


def initialize_or_update_user_stats(user_id, game=None):
    """
    Update user stats incrementally if a game is provided, or initialize stats from scratch if needed.
    Now also handles daily streaks properly.

    Args:
        user_id (str): User ID
        game (GameScore, optional): Recently completed game for incremental update
    """
    try:
        # Get or create UserStats
        user_stats = UserStats.query.filter_by(user_id=user_id).first()
        if not user_stats:
            # New user - create stats object
            user_stats = UserStats(user_id=user_id)
            db.session.add(user_stats)

            # For new users, we need to initialize from all games
            # This only happens once per user
            games = GameScore.query.filter_by(user_id=user_id).order_by(
                GameScore.created_at).all()

            if games:
                # Calculate initial stats
                user_stats.total_games_played = len(games)

                # Count wins correctly based on each game's difficulty
                wins = 0
                for g in games:
                    max_mistakes = get_max_mistakes_for_game(g)
                    if g.completed and g.mistakes < max_mistakes:
                        wins += 1
                user_stats.games_won = wins

                user_stats.cumulative_score = sum(game.score for game in games)
                user_stats.last_played_date = games[-1].created_at

                # Calculate streaks
                current_streak = 0
                max_streak = 0
                current_noloss_streak = 0
                max_noloss_streak = 0

                # Sort games by date (most recent first) for streak calculation
                for g in reversed(games):
                    max_mistakes = get_max_mistakes_for_game(g)
                    if g.completed and g.mistakes < max_mistakes:  # Won game
                        current_streak += 1
                        current_noloss_streak += 1
                    else:  # Lost or abandoned game
                        current_streak = 0
                        current_noloss_streak = 0

                    max_streak = max(max_streak, current_streak)
                    max_noloss_streak = max(max_noloss_streak,
                                            current_noloss_streak)

                user_stats.current_streak = current_streak
                user_stats.max_streak = max_streak
                user_stats.current_noloss_streak = current_noloss_streak
                user_stats.max_noloss_streak = max_noloss_streak

                # Calculate weekly score
                now = datetime.utcnow()
                week_start = now - timedelta(days=now.weekday())
                weekly_score = sum(g.score for g in games
                                   if g.created_at >= week_start)
                user_stats.highest_weekly_score = weekly_score

            db.session.commit()
            logging.info(f"Initialized stats for new user {user_id}")
            return user_stats

        # Existing user with a new game - incremental update
        if game:
            # Update basic counters
            user_stats.total_games_played += 1

            # Is the game won? Use correct max mistakes for this game's difficulty
            max_mistakes = get_max_mistakes_for_game(game)
            game_won = game.completed and game.mistakes < max_mistakes

            if game_won:
                user_stats.games_won += 1

            # Update cumulative score
            user_stats.cumulative_score += game.score

            # Update last played date if this game is more recent
            if not user_stats.last_played_date or game.created_at > user_stats.last_played_date:
                user_stats.last_played_date = game.created_at

            # Calculate weekly score contribution
            now = datetime.utcnow()
            week_start = now - timedelta(days=now.weekday())
            if game.created_at >= week_start:
                # Update highest weekly score if current week's total is now higher
                current_week_total = db.session.query(func.sum(
                    GameScore.score)).filter(
                        GameScore.user_id == user_id, GameScore.created_at
                        >= week_start).scalar() or 0

                if current_week_total > (user_stats.highest_weekly_score or 0):
                    user_stats.highest_weekly_score = current_week_total

            # Update streaks based on win/loss and chronological order
            # [existing streak update code...]

            # Handle daily challenge streaks if this is a daily challenge game
            if game.game_type == 'daily' and game.completed:
                # Get the challenge date from the game
                if game.challenge_date:
                    try:
                        # Parse the challenge date from the game
                        challenge_date = datetime.strptime(game.challenge_date, '%Y-%m-%d').date()
                    except (ValueError, TypeError):
                        # Fallback to created_at date if challenge_date is invalid
                        challenge_date = game.created_at.date()
                else:
                    # Default to the game creation date
                    challenge_date = game.created_at.date()

                # Update daily streak logic
                # If this is their first completion
                if not user_stats.last_daily_completed_date:
                    user_stats.current_daily_streak = 1
                    user_stats.max_daily_streak = 1
                    user_stats.total_daily_completed = 1
                    user_stats.last_daily_completed_date = challenge_date
                else:
                    # Check if this completion continues the streak
                    last_date = user_stats.last_daily_completed_date
                    delta = (challenge_date - last_date).days

                    # Check if this is a one-day advancement (continuing streak)
                    if delta == 1:
                        user_stats.current_daily_streak += 1
                        # Update max streak if current is now higher
                        if user_stats.current_daily_streak > user_stats.max_daily_streak:
                            user_stats.max_daily_streak = user_stats.current_daily_streak
                    # If same day completion (shouldn't happen but handle it)
                    elif delta == 0:
                        # No change to streak
                        pass
                    # If today is the next day after last_date (special case for overnight completion)
                    elif challenge_date == datetime.utcnow().date() and (datetime.utcnow().date() - last_date).days == 1:
                        user_stats.current_daily_streak += 1
                        # Update max streak if current is now higher
                        if user_stats.current_daily_streak > user_stats.max_daily_streak:
                            user_stats.max_daily_streak = user_stats.current_daily_streak
                    # If streak is broken
                    else:
                        # Reset streak to 1 for this new completion
                        user_stats.current_daily_streak = 1

                    # Update total completed and last date regardless of streak continuation
                    user_stats.total_daily_completed += 1
                    user_stats.last_daily_completed_date = challenge_date

                # Log the streak update
                logging.info(f"Updated daily streak for user {user_id} to {user_stats.current_daily_streak}")

        db.session.commit()
        logging.info(f"User stats updated for user {user_id}")
        return user_stats

    except Exception as e:
        db.session.rollback()
        logging.error(f"Error updating user stats: {e}")
        raise
