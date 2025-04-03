
from app.models import db, Quote
from datetime import datetime, timedelta
import random

def update_daily_dates():
    # Get all quotes with populated daily_date
    quotes_with_dates = Quote.query.filter(Quote.daily_date.isnot(None)).all()
    
    # Get remaining quotes without daily_date
    quotes_without_dates = Quote.query.filter(Quote.daily_date.is_(None)).all()
    
    if not quotes_with_dates:
        print("No quotes found with daily dates")
        return
        
    # Get count of quotes with dates
    n = len(quotes_with_dates)
    print(f"Found {n} quotes with daily dates")
    
    # Get random quotes to assign dates to
    quotes_to_update = random.sample(quotes_with_dates, n)
    
    # Get the latest date from existing daily quotes
    latest_date = max(q.daily_date for q in quotes_with_dates)
    
    # Start assigning dates from the day after latest date
    current_date = latest_date + timedelta(days=1)
    
    # Assign dates to quotes
    for quote in quotes_to_update:
        quote.daily_date = current_date
        current_date += timedelta(days=1)
    
    # Commit changes
    db.session.commit()
    print(f"Successfully updated {n} quotes with new daily dates")
