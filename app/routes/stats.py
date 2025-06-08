from flask import Blueprint, jsonify, request, session
from flask_jwt_extended import jwt_required, get_jwt_identity
from datetime import datetime, timedelta
import logging
from sqlalchemy import text
from app.models import db, UserStats, GameScore, User
from app.utils.db import get_user_stats
from app.utils.stats import initialize_or_update_user_stats

bp = Blueprint('stats', __name__)


@bp.route('/stats', methods=['GET'])
@jwt_required()
def get_stats():
    username = get_jwt_identity()
    stats = get_user_stats(username)
    return jsonify(stats), 200


@bp.route('/leaderboard', methods=['GET'])
@jwt_required()
def get_leaderboard():
    # Extract parameters with defaults
    period = request.args.get('period', 'all-time')
    try:
        page = int(request.args.get('page', 1))
    except (ValueError, TypeError):
        page = 1
    try:
        per_page = min(int(request.args.get('per_page', 10)),
                       50)  # Limit to 50 max
    except (ValueError, TypeError):
        per_page = 10

    # Calculate pagination offset
    offset = (page - 1) * per_page

    try:
        # Get requesting user's ID
        user_id = get_jwt_identity()

        # Calculate total users BEFORE the main query
        if period == 'weekly':
            today = datetime.utcnow()
            today_start = datetime(today.year, today.month, today.day)
            start_of_week = today_start - timedelta(days=today.weekday())

            # Get total unique users who have played this week
            total_users = db.session.query(
                db.func.count(db.distinct(GameScore.user_id))).filter(
                    GameScore.completed == True, GameScore.created_at
                    >= start_of_week).scalar() or 0
        else:
            # All-time total users
            total_users = UserStats.query.count()

        # Query for top entries
        if period == 'weekly':
            # Weekly scores from game_scores
            top_entries = db.session.query(
                User.username,
                User.user_id,
                db.func.sum(GameScore.score).label('total_score'),
                db.func.count(GameScore.id).label('games_played'),
                db.func.avg(GameScore.score).label('avg_score')
            ).join(User).filter(
                GameScore.completed == True,
                GameScore.created_at >= start_of_week
            ).group_by(User.username, User.user_id)\
             .order_by(db.desc('total_score'))\
             .offset(offset).limit(per_page).all()
        else:
            # All-time stats from user_stats
            top_entries = db.session.query(
                User.username,
                User.user_id,
                UserStats.cumulative_score.label('total_score'),
                UserStats.total_games_played.label('games_played'),
                (db.func.cast(UserStats.cumulative_score, db.Float) /
                 db.func.nullif(db.func.coalesce(UserStats.total_games_played, 1), 0)).label('avg_score')
            ).join(UserStats, User.user_id == UserStats.user_id)\
             .order_by(db.desc(UserStats.cumulative_score))\
             .offset(offset).limit(per_page).all()

        # Format entries
        formatted_entries = []
        for idx, entry in enumerate(top_entries, start=offset + 1):
            formatted_entries.append({
                "rank":
                idx,
                "username":
                entry.username,
                "user_id":
                entry.user_id,
                "score":
                int(entry.total_score) if entry.total_score else 0,
                "games_played":
                entry.games_played,
                "avg_score":
                round(float(entry.avg_score), 1) if entry.avg_score else 0,
                "is_current_user":
                entry.user_id == user_id
            })

        # Get current user entry if not in top entries
        current_user_entry = None
        if not any(entry["is_current_user"] for entry in formatted_entries):
            user = User.query.get(user_id)
            if user:
                if period == 'weekly':
                    # For weekly, check if user has any games this week
                    user_weekly_stats = db.session.query(
                        db.func.sum(GameScore.score).label('total_score'),
                        db.func.count(GameScore.id).label('games_played'),
                        db.func.avg(
                            GameScore.score).label('avg_score')).filter(
                                GameScore.user_id == user_id,
                                GameScore.completed == True,
                                GameScore.created_at >= start_of_week).first()

                    if user_weekly_stats and user_weekly_stats.games_played and user_weekly_stats.games_played > 0:
                        # User has played this week, calculate their rank
                        user_score = user_weekly_stats.total_score or 0

                        # Count how many users have higher scores
                        rank_subquery = db.session.query(
                            GameScore.user_id,
                            db.func.sum(
                                GameScore.score).label('user_total')).filter(
                                    GameScore.completed == True,
                                    GameScore.created_at
                                    >= start_of_week).group_by(
                                        GameScore.user_id).subquery()

                        rank_query = db.session.query(
                            db.func.count()).select_from(rank_subquery).filter(
                                rank_subquery.c.user_total >
                                user_score).scalar()

                        user_rank = (rank_query or 0) + 1

                        current_user_entry = {
                            "username":
                            user.username,
                            "user_id":
                            user_id,
                            "score":
                            int(user_score),
                            "games_played":
                            user_weekly_stats.games_played,
                            "avg_score":
                            round(float(user_weekly_stats.avg_score), 1)
                            if user_weekly_stats.avg_score else 0,
                            "is_current_user":
                            True,
                            "rank":
                            user_rank
                        }
                    else:
                        # User hasn't played this week - they're unranked
                        current_user_entry = {
                            "username": user.username,
                            "user_id": user_id,
                            "score": 0,
                            "games_played": 0,
                            "avg_score": 0,
                            "is_current_user": True,
                            "rank": total_users + 1 if total_users > 0 else 1
                        }
                else:
                    # All-time logic
                    user_stats = UserStats.query.filter_by(
                        user_id=user_id).first()
                    if user_stats:
                        # Calculate user's actual rank
                        rank_query = db.session.query(
                            db.func.count(UserStats.user_id)).filter(
                                UserStats.cumulative_score >
                                user_stats.cumulative_score).scalar()

                        user_rank = (rank_query or 0) + 1

                        current_user_entry = {
                            "username":
                            user.username,
                            "user_id":
                            user_id,
                            "score":
                            user_stats.cumulative_score,
                            "games_played":
                            user_stats.total_games_played,
                            "avg_score":
                            round(
                                user_stats.cumulative_score /
                                user_stats.total_games_played, 1)
                            if user_stats.total_games_played > 0 else 0,
                            "is_current_user":
                            True,
                            "rank":
                            user_rank
                        }

        return jsonify({
            "entries": formatted_entries,
            "currentUserEntry": current_user_entry,
            "pagination": {
                "current_page":
                page,
                "total_pages": (total_users + per_page - 1) //
                per_page if total_users > 0 else 1,
                "total_entries":
                total_users,
                "per_page":
                per_page
            },
            "period": period
        })

    except Exception as e:
        logging.error(f"Error fetching leaderboard: {str(e)}")
        import traceback
        logging.error(traceback.format_exc())
        return jsonify(
            {"error": f"Failed to retrieve leaderboard data: {str(e)}"}), 500                                                                              


@bp.route('/streak_leaderboard', methods=['GET'])
@jwt_required()
def get_streak_leaderboard():
    # Add debugging
    logging.info(
        f"Streak leaderboard request received with params: {request.args}")

    streak_type = request.args.get('type', 'win')  # 'win' or 'noloss'
    period = request.args.get('period', 'current')  # 'current' or 'best'

    try:
        page = int(request.args.get('page', 1))
    except (ValueError, TypeError):
        page = 1

    try:
        per_page = min(int(request.args.get('per_page', 10)), 50)
    except (ValueError, TypeError):
        per_page = 10

    offset = (page - 1) * per_page
    user_id = get_jwt_identity()

    try:
        # Determine which streak field to use
        streak_field = None
        if streak_type == 'win':
            streak_field = UserStats.current_streak if period == 'current' else UserStats.max_streak
        else:  # 'noloss'
            streak_field = UserStats.current_noloss_streak if period == 'current' else UserStats.max_noloss_streak

        # Query for top streak entries
        top_entries = db.session.query(
            User.username, User.user_id, streak_field.label('streak_length'),
            UserStats.last_played_date).join(
                User, User.user_id == UserStats.user_id).filter(
                    streak_field > 0).order_by(
                        db.desc('streak_length'),
                        db.desc(UserStats.last_played_date)).offset(
                            offset).limit(per_page).all()

        # Format entries
        formatted_entries = []
        for idx, entry in enumerate(top_entries, start=offset + 1):
            entry_dict = {
                "rank": idx,
                "username": entry.username,
                "user_id": entry.user_id,
                "streak_length": entry.streak_length,
                "is_current_user": entry.user_id == user_id
            }
            if period == 'current':
                entry_dict["last_active"] = entry.last_played_date
            formatted_entries.append(entry_dict)

        # Get current user entry if not in top entries
        current_user_entry = None
        if not any(entry["is_current_user"] for entry in formatted_entries):
            user_stats = UserStats.query.filter_by(user_id=user_id).first()
            if user_stats:
                user = User.query.get(user_id)

                # Get the correct streak field
                streak_field_name = 'current_streak' if period == 'current' and streak_type == 'win' else \
                                  'max_streak' if period == 'best' and streak_type == 'win' else \
                                  'current_noloss_streak' if period == 'current' else 'max_noloss_streak'

                user_streak = getattr(user_stats, streak_field_name, 0)

                # Calculate user's actual rank in streaks
                rank_query = UserStats.query.filter(
                    getattr(UserStats, streak_field_name) >
                    user_streak).count()

                # User's rank is the count of users with higher streaks + 1
                user_rank = rank_query + 1

                current_user_entry = {
                    "username": user.username,
                    "user_id": user_id,
                    "streak_length": user_streak,
                    "is_current_user": True,
                    "rank": user_rank  # Add the calculated rank
                }
                if period == 'current':
                    current_user_entry[
                        "last_active"] = user_stats.last_played_date

        # Get total users with streaks
        total_users = UserStats.query.filter(streak_field > 0).count()

        return jsonify({
            "entries": formatted_entries,
            "currentUserEntry": current_user_entry,
            "pagination": {
                "current_page":
                page,
                "total_pages": (total_users + per_page - 1) //
                per_page if total_users > 0 else 1,
                "total_entries":
                total_users,
                "per_page":
                per_page
            },
            "streak_type": streak_type,
            "period": period
        })

    except Exception as e:
        logging.error(f"Error fetching streak leaderboard: {e}")
        return jsonify(
            {"error":
             f"Failed to retrieve streak leaderboard data: {str(e)}"}), 500


@bp.route('/user_stats', methods=['GET'])
@jwt_required()
def get_user_stats():
    user_id = get_jwt_identity()

    try:
        # Initialize or update user stats
        initialize_or_update_user_stats(user_id)

        # Get user stats
        user_stats = UserStats.query.filter_by(user_id=user_id).first()
        if not user_stats:
            return jsonify({
                "user_id": user_id,
                "current_streak": 0,
                "max_streak": 0,
                "current_noloss_streak": 0,
                "max_noloss_streak": 0,
                "total_games_played": 0,
                "games_won": 0,
                "cumulative_score": 0,
                "highest_weekly_score": 0,
                "last_played_date": None,
                "weekly_stats": {
                    "score": 0,
                    "games_played": 0
                },
                "top_scores": []
            })

        # Calculate weekly stats
        today = datetime.utcnow().date()
        start_of_week = today - timedelta(days=today.weekday())

        weekly_games = GameScore.query.filter(
            GameScore.user_id == user_id, GameScore.created_at
            >= start_of_week).all()

        weekly_stats = {
            "score": sum(game.score for game in weekly_games),
            "games_played": len(weekly_games)
        }

        # Get top 5 scores
        top_scores = GameScore.query.filter_by(
            user_id=user_id,
            completed=True).order_by(GameScore.score.desc()).limit(5).all()

        formatted_top_scores = [{
            "score": game.score,
            "time_taken": game.time_taken,
            "date": game.created_at
        } for game in top_scores]

        return jsonify({
            "user_id":
            user_id,
            "current_streak":
            user_stats.current_streak,
            "max_streak":
            user_stats.max_streak,
            "current_noloss_streak":
            user_stats.current_noloss_streak,
            "max_noloss_streak":
            user_stats.max_noloss_streak,
            "total_games_played":
            user_stats.total_games_played,
            "games_won":
            user_stats.games_won,
            "win_percentage":
            round((user_stats.games_won / user_stats.total_games_played *
                   100) if user_stats.total_games_played > 0 else 0, 1),
            "cumulative_score":
            user_stats.cumulative_score,
            "highest_weekly_score":
            user_stats.highest_weekly_score,
            "last_played_date":
            user_stats.last_played_date,
            "weekly_stats":
            weekly_stats,
            "top_scores":
            formatted_top_scores
        })

    except Exception as e:
        logging.error(f"Error getting user stats: {e}")
        return jsonify({"error": "Failed to retrieve user statistics"}), 500


@bp.route('/api/games/record', methods=['POST'])
@jwt_required()
def record_games():
    """Record completed games from mobile app"""
    try:
        user_id = get_jwt_identity()
        data = request.get_json()
        games = data.get('games', [])

        # Process each game
        processed = 0
        for game_data in games[:20]:  # Cap at 20 per request
            # Check for duplicate
            existing = GameScore.query.filter_by(
                user_id=user_id,
                game_id=game_data['gameId']
            ).first()

            if not existing:
                game = GameScore(
                    user_id=user_id,
                    game_id=game_data['gameId'],
                    score=game_data['score'],
                    mistakes=game_data['mistakes'],
                    time_taken=game_data['timeSeconds'],
                    game_type='daily' if game_data['isDaily'] else 'regular',
                    completed=True,
                    created_at=datetime.fromisoformat(game_data['completedAt'].replace('Z', '+00:00'))
                )
                db.session.add(game)
                processed += 1

                # Update user stats
                update_user_stats_for_game(user_id, game_data)

        db.session.commit()

        return jsonify({
            "success": True,
            "processed": processed,
            "message": f"Recorded {processed} new games"
        }), 200

    except Exception as e:
        return jsonify({"error": str(e)}), 500

def update_user_stats_for_game(user_id, game_data):
    """Update aggregated stats after game recording"""
    stats = UserStats.query.filter_by(user_id=user_id).first()
    if not stats:
        stats = UserStats(user_id=user_id)
        db.session.add(stats)

    # Update totals
    stats.total_games_played += 1
    stats.total_score += game_data['score']

    if game_data['won']:
        stats.games_won += 1

    # Handle daily streak
    if game_data['isDaily']:
        game_date = datetime.fromisoformat(game_data['completedAt'].replace('Z', '+00:00')).date()

        if stats.last_daily_completed:
            days_diff = (game_date - stats.last_daily_completed).days

            if days_diff == 1:  # Consecutive day
                stats.current_daily_streak += 1
            elif days_diff > 1:  # Streak broken
                stats.current_daily_streak = 1
            # days_diff == 0 means same day, don't update
        else:
            stats.current_daily_streak = 1

        stats.last_daily_completed = game_date
        stats.best_daily_streak = max(stats.best_daily_streak, stats.current_daily_streak)