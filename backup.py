"""Backup consistente do SQLite, incluindo durante uso do sistema."""
import argparse
import sqlite3
from pathlib import Path
import app


def backup(destination):
    target = Path(destination)
    if target.resolve() == app.DB.resolve():
        raise ValueError('Escolha um arquivo diferente do banco principal.')
    target.parent.mkdir(parents=True, exist_ok=True)
    # Não sobrescrever arquivos existentes, inclusive backups anteriores.
    with target.open('xb'):
        pass
    target.chmod(0o600)
    try:
        with sqlite3.connect(f'{app.DB.resolve().as_uri()}?mode=ro', uri=True) as source:
            with sqlite3.connect(target) as dest:
                source.backup(dest)
                if dest.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
                    raise ValueError('O backup não passou na verificação de integridade.')
    except Exception:
        target.unlink()
        raise


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Backup do banco da Arte no Altar')
    parser.add_argument('destination')
    backup(parser.parse_args().destination)
    print('Backup concluído e verificado.')
