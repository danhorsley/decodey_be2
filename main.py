
from app import create_app
from gevent.pywsgi import WSGIServer
from gevent import monkey

# Patch stdlib for gevent compatibility
monkey.patch_all()

app = create_app()

if __name__ == '__main__':
    # Configure server with chunked transfer encoding support
    http_server = WSGIServer(('0.0.0.0', 5000), app, environ={'wsgi.multithread': True})
    print("Server starting on port 5000...")
    http_server.serve_forever()
