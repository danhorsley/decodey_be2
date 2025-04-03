
from app.models import db, Quote
from datetime import datetime, timedelta

def update_daily_dates():
    """Update daily_date values for quotes without affecting other fields"""
    
    # Get all quotes with populated daily_date
    quotes_with_dates = Quote.query.filter(Quote.daily_date.isnot(None)).all()
    
    if not quotes_with_dates:
        print("No quotes found with daily dates")
        return
        
    n = len(quotes_with_dates)
    print(f"Found {n} quotes with daily dates")
    
    # Clear existing daily_dates
    for quote in quotes_with_dates:
        quote.daily_date = None
    db.session.commit()
    print("Cleared existing daily dates")
    
    # Get tomorrow's date
    tomorrow = datetime.utcnow().date() + timedelta(days=1)
    
    # Reassign dates sequentially from tomorrow
    for i, quote in enumerate(quotes_with_dates):
        quote.daily_date = tomorrow + timedelta(days=i)
    
    # Commit changes
    db.session.commit()
    print(f"Successfully reassigned dates for {n} quotes")
