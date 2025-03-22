# Uncrypt Game

A cryptogram puzzle game where players decrypt quotes by guessing letter substitutions. This web application includes both player-facing game features and an administrative backend for management.

## Features

### Game Features
- Multi-difficulty level cryptogram puzzles (Easy, Medium, Hard)
- Optional hardcore mode without spaces/punctuation
- User registration and authentication
- Anonymous play option
- Personal statistics tracking
- Leaderboards with various ranking options
- Persistent game state for logged-in users

### Admin Portal
- Secure admin authentication with two-factor approach
- User management (view, reset passwords, suspend/activate)
- Quote management (add, edit, delete, and import/export)
- Database backup and restore functionality
- System settings configuration
- Game settings management
- Security controls

## Installation

### Prerequisites
- Python 3.11 or higher
- PostgreSQL database (or SQLite for development)
- Redis (optional, for Celery background tasks)

### Setup

1. Clone the repository:
```bash
git clone https://github.com/yourusername/uncrypt-game.git
cd uncrypt-game
```

2. Create and activate a virtual environment:
```bash
python -m venv venv
source venv/bin/activate  # On Windows, use: venv\Scripts\activate
```

3. Install dependencies:
```bash
pip install -r requirements.txt
```

4. Set up environment variables:
```bash
# Linux/Mac
export FLASK_APP=run.py
export DATABASE_URL=postgresql://username:password@localhost/uncrypt
export SECRET_KEY=your_secret_key
export JWT_SECRET_KEY=your_jwt_secret_key

# Windows
set FLASK_APP=run.py
set DATABASE_URL=postgresql://username:password@localhost/uncrypt
set SECRET_KEY=your_secret_key
set JWT_SECRET_KEY=your_jwt_secret_key
```

5. Initialize the database:
```bash
flask db upgrade
```

6. Create an admin user:
```bash
flask create-admin admin_username
# Follow the prompts to set the password and admin password
```

7. Run the application:
```bash
flask run
```

## Using the Admin Portal

### Accessing the Admin Portal
1. Navigate to `/admin/login` in your browser
2. Enter your username, password, and admin password
3. You'll be redirected to the admin dashboard

### User Management
- View all users with search and filter options
- Reset user passwords
- Suspend or activate user accounts
- View detailed user statistics

### Quote Management
- Add new quotes with author attributions
- Edit existing quotes
- Delete quotes
- Import quotes from CSV files
- Export quotes to CSV

### Database Backup
- Create manual database backups
- Configure scheduled backups (daily/weekly)
- Restore from backups
- Set retention policy for automatic cleanup

### Settings Management
- Game settings: Configure difficulty levels, quote selection, etc.
- System status: Enable/disable maintenance mode, control registration
- Security settings: Configure session timeouts, rate limits, etc.
- Email settings: Set up SMTP for system emails

## Project Structure

```
uncrypt-game/
├── app/                        # Application package
│   ├── models.py               # Database models
│   ├── routes/                 # Route handlers
│   │   ├── admin.py            # Admin endpoints
│   │   ├── admin_process.py    # Admin form processing
│   │   ├── auth.py             # Authentication endpoints
│   │   ├── game.py             # Game endpoints
│   │   └── stats.py            # Statistics endpoints
│   ├── services/               # Business logic
│   │   └── game_logic.py       # Game mechanics
│   ├── templates/              # Jinja2 templates
│   │   ├── admin/              # Admin templates
│   │   └── ...                 # Game templates
│   └── utils/                  # Utility functions
│       ├── scoring.py          # Score calculation
│       └── ...                 # Other utilities
├── config.py                   # Application configuration
├── migrations/                 # Database migrations
├── quotes.csv                  # Source quotes for the game
├── run.py                      # Application entry point
└── README.md                   # This file
```

## Database Schema

The application uses the following main models:

- `User`: User accounts and authentication
- `UserStats`: Game statistics for each user
- `GameScore`: Individual game results
- `ActiveGameState`: Current in-progress games
- `AnonymousGameState`: Games in progress for non-logged-in users
- `BackupRecord`: Database backup metadata
- `BackupSettings`: Configuration for automated backups

## Background Tasks

For scheduled tasks like database backups, the application uses Celery with Redis as the message broker. To run the Celery worker:

```bash
celery -A app.celery_worker worker --loglevel=info
```

To run the Celery beat scheduler for periodic tasks:

```bash
celery -A app.celery_worker beat --loglevel=info
```

## Contributing

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/your-feature`)
3. Commit your changes (`git commit -am 'Add some feature'`)
4. Push to the branch (`git push origin feature/your-feature`)
5. Create a new Pull Request

## License

This project is licensed under the MIT License - see the LICENSE file for details.