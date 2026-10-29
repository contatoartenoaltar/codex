"""Adaptador WSGI para executar as mesmas rotas com um servidor de produção."""
import io
from email.message import Message
from http import HTTPStatus
import app


class Request(app.Handler):
    def __init__(self, environ):
        self.path = environ['PATH_INFO']
        self.headers = Message()
        for name, value in environ.items():
            if name.startswith('HTTP_'):
                self.headers[name[5:].replace('_', '-')] = value
        self.headers['Content-Length'] = environ.get('CONTENT_LENGTH') or '0'
        self.rfile = environ['wsgi.input']
        self.wfile = io.BytesIO()
        self.response_headers = []
        self.status = 200

    def send_response(self, code, message=None):
        self.status = code

    def send_header(self, name, value):
        self.response_headers.append((name, value))

    def end_headers(self):
        self.security_headers()


def application(environ, start_response):
    request = Request(environ)
    method = environ.get('REQUEST_METHOD')
    if method == 'GET':
        request.do_GET()
    elif method == 'POST':
        request.do_POST()
    else:
        request.send_json({'error': 'Método não permitido.'}, 405)
    start_response(f'{request.status} {HTTPStatus(request.status).phrase}', request.response_headers)
    return [request.wfile.getvalue()]
