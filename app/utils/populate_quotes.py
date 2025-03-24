
import csv
from datetime import datetime, timedelta
import random
from app.models import db, Quote

def count_unique_letters(text):
    return len(set(char.lower() for char in text if char.isalpha()))

def populate_quotes():
    # Clear existing quotes
    Quote.query.delete()
    
    # Read quotes from CSV
    with open('quotes.csv', 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        quotes = list(reader)
        
    # Get today's date
    today = datetime.utcnow().date()
    
    # Create a list of dates starting from tomorrow
    future_dates = [today + timedelta(days=i) for i in range(1, len(quotes) + 1)]
    random.shuffle(future_dates)
    
    # Current timestamp for created_at and updated_at
    now = datetime.utcnow()
    
    for i, row in enumerate(quotes):
        quote_text = row['quote'].strip()
        difficulty = count_unique_letters(quote_text)
        
        # Set daily_date to None if quote is over 65 chars
        daily_date = None if len(quote_text) > 65 else future_dates[i]
        
        quote = Quote(
            text=quote_text,
            author=row['author'].strip(),
            minor_attribution=row['minor_attribution'].strip(),
            difficulty=difficulty,
            daily_date=daily_date,
            times_used=0,
            active=True,
            created_at=now,
            updated_at=now
        )
        db.session.add(quote)
    
    db.session.commit()
