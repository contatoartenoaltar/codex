"""Inicialização para hospedagem HTTPS, com persistência explícita."""
import os
from pathlib import Path
from urllib.parse import urlsplit


def main():
    origin = urlsplit(os.environ.get('ARTENOALTAR_ORIGIN', ''))
    if origin.scheme != 'https' or not origin.hostname or origin.username or origin.password or origin.path or origin.query or origin.fragment:
        raise SystemExit('Defina ARTENOALTAR_ORIGIN como https://seu-dominio, sem barra final.')
    db = os.environ.get('ARTENOALTAR_DB', '')
    if not db or not Path(db).is_absolute():
        raise SystemExit('Defina ARTENOALTAR_DB como um caminho absoluto em disco persistente.')
    from waitress import serve
    import app
    from wsgi import application
    app.initialize()
    serve(application, host='0.0.0.0', port=int(os.environ.get('PORT', '8000')), threads=4,
          max_request_body_size=8*1024*1024, clear_untrusted_proxy_headers=True,
          channel_timeout=60, expose_tracebacks=False)


if __name__ == '__main__':
    main()
