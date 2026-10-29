"""Modelo para copiar ao arquivo WSGI indicado no painel Web do PythonAnywhere.

Antes de usar, troque SEU_USUARIO e confira o domínio gratuito no painel.
Não há senha neste arquivo: cadastre-a com app.py set-password no console.
"""
import os
import sys
from pathlib import Path

project = Path('/home/SEU_USUARIO/arte-no-altar')
os.environ['ARTENOALTAR_ORIGIN'] = 'https://SEU_USUARIO.pythonanywhere.com'
os.environ['ARTENOALTAR_DB'] = str(project / '.local' / 'arte-no-altar.db')
sys.path.insert(0, str(project))
import app
app.initialize()
from wsgi import application
