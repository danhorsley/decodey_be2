
from app.models import db, Quote
from datetime import datetime, timedelta
import random

def update_daily_dates():
    # Get all quotes with populated daily_date
    quotes_with_dates = Quote.query.filter(Quote.daily_date.isnot(None)).all()
    
    if not quotes_with_dates:
        print("No quotes found with daily dates")
        return
        
    # Get count of quotes with dates
    n = len(quotes_with_dates)
    print(f"Found {n} quotes with daily dates")
    
    # Get today's date
    today = datetime.utcnow().date()
    
    # Create list of next N consecutive days
    future_dates = [today + timedelta(days=i) for i in range(1, n+1)]
    
    # Update each quote with a new consecutive date
    for quote, new_date in zip(quotes_with_dates, future_dates):
        quote.daily_date = new_date
    
    # Commit changes
    db.session.commit()
    print(f"Successfully reassigned dates for {n} quotes")
