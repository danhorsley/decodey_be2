
from app import create_app
from app.utils.populate_quotes import populate_quotes

app = create_app()
with app.app_context():
    populate_quotes()
    print("Quotes populated successfully!")
