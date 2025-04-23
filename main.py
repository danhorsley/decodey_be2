
from app import create_app
import secrets
from gevent.pywsgi import WSGIServer

app = create_app()
app.secret_key = secrets.token_hex(16)  # Generate a secure secret key

if __name__ == '__main__':
    # Using gevent server for better SSE support
    http_server = WSGIServer(('0.0.0.0', 5000), app)
    http_server.serve_forever()