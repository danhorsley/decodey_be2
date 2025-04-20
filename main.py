
from flask import Flask
from app import create_app
import secrets

app = create_app()
app.secret_key = secrets.token_hex(16)  # Generate a secure secret key

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)

from app import create_app
from gevent.pywsgi import WSGIServer
import logging

app = create_app()

if __name__ == '__main__':
    # Configure gunicorn logging
    gunicorn_logger = logging.getLogger('gunicorn.error')
    app.logger.handlers = gunicorn_logger.handlers
    app.logger.setLevel(gunicorn_logger.level)
    
    # Using gevent server for better SSE support
    http_server = WSGIServer(('0.0.0.0', 5000), app, log=app.logger)
    http_server.serve_forever()