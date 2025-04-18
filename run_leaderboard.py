from app import create_app
from app.tasks.leaderboard import reset_weekly_leaderboard

app = create_app()
with app.app_context():
    try:
        reset_weekly_leaderboard()
        print("Weekly leaderboard updated successfully")
    except Exception as e:
        print(f"Error updating leaderboard: {str(e)}")
