
from app.models import db, Quote
from datetime import datetime, timedelta

def update_daily_dates():
    # Get all quotes with populated daily_date
    quotes_with_dates = Quote.query.filter(Quote.daily_date.isnot(None)).all()
    
    if not quotes_with_dates:
        print("No quotes found with daily dates")
        return
        
    n = len(quotes_with_dates)
    print(f"Found {n} quotes with daily dates")
    
    # Store the quotes that had dates
    quotes_to_update = quotes_with_dates.copy()
    
    # First, set all daily_dates to NULL to avoid unique constraint conflicts
    for quote in quotes_with_dates:
        quote.daily_date = None
    db.session.commit()
    print("Cleared existing daily dates")
    
    # Get today's date
    today = datetime.utcnow().date()
    
    # Create list of next N consecutive days
    future_dates = [today + timedelta(days=i) for i in range(1, n+1)]
    
    # Now assign new dates
    for quote, new_date in zip(quotes_to_update, future_dates):
        quote.daily_date = new_date
    
    # Commit changes
    db.session.commit()
    print(f"Successfully reassigned dates for {n} quotes")
