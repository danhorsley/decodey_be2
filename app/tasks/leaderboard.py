# app/tasks/leaderboard.py
from app.models import db, UserStats, LeaderboardEntry, User, GameScore
from datetime import datetime, timedelta
from sqlalchemy import func


def reset_weekly_leaderboard():
    """Save weekly leaderboard and reset scores"""
    try:
        # Calculate week boundaries
        now = datetime.utcnow()
        end_of_week = now.replace(hour=23, minute=59, second=59)
        start_of_week = end_of_week - timedelta(
            days=end_of_week.weekday(), hours=23, minutes=59, seconds=59)

        # Get top 100 users for the week
        top_users = db.session.query(
            GameScore.user_id,
            func.sum(GameScore.score).label('total_score'),
            func.count(GameScore.id).label('games_played'),
            func.sum(case(
                (GameScore.completed == True, 1),
                else_=0)).label('games_won')).filter(
                    GameScore.created_at.between(
                        start_of_week,
                        end_of_week)).group_by(GameScore.user_id).order_by(
                            func.sum(GameScore.score).desc()).limit(100).all()

        # Save leaderboard entries
        for rank, user_data in enumerate(top_users, 1):
            user = User.query.get(user_data.user_id)
            if not user:
                continue

            entry = LeaderboardEntry(user_id=user.user_id,
                                     username=user.username,
                                     period_type='weekly',
                                     period_start=start_of_week,
                                     period_end=end_of_week,
                                     rank=rank,
                                     score=user_data.total_score,
                                     games_played=user_data.games_played,
                                     games_won=user_data.games_won)
            db.session.add(entry)

        # Reset weekly scores for all users
        for stats in UserStats.query.all():
            stats.current_weekly_score = 0

        db.session.commit()
        print(f"Weekly leaderboard reset successful at {now}")

    except Exception as e:
        db.session.rollback()
        print(f"Error resetting weekly leaderboard: {str(e)}")
