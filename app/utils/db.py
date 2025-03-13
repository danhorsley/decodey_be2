# In-memory storage for MVP
users = {}
game_states = {}
stats = {}

def get_user(username):
    return users.get(username)

def save_user(user):
    users[user['username']] = user

def get_game_state(username):
    return game_states.get(username)

def save_game_state(username, state):
    game_states[username] = state

def get_user_stats(username):
    return stats.get(username, {
        'games_played': 0,
        'wins': 0,
        'average_attempts': 0
    })

def get_leaderboard():
    return sorted(
        [{'username': k, **v} for k, v in stats.items()],
        key=lambda x: x['wins'],
        reverse=True
    )[:10]
