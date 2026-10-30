"""Aplicação local da Arte no Altar. Python 3.12+, biblioteca padrão."""
import json
import os
import re
import sqlite3
import auth
import meta
import publishing
import scheduling
import scheduler_http
import social_mcp
import feed_composer
import html
import urllib.error
import urllib.request
from datetime import date
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit, parse_qs
from http.cookies import SimpleCookie, CookieError

ROOT = Path(__file__).parent
DB = Path(os.environ.get('ARTENOALTAR_DB', ROOT / '.local/arte-no-altar.db'))
PRICES = {100: 9900, 200: 14900, 500: 22900, 1000: 39900}
PRODUCTS = [
    {'id': 'envelopes', 'name': 'Envelopes personalizados', 'description': 'Dízimos, ofertas, primícias, missões e campanhas. C6 (16,2 × 11,4 cm), com logotipo e QR Code Pix. Pedido mínimo: 100 unidades.', 'prices': PRICES},
    {'id': 'projetos', 'name': 'Projetos de Vida', 'description': 'Kits com cartilha, calendário, marca-página e envelope. Versões Premium e Básica.'},
    {'id': 'marcadores', 'name': 'Marca-páginas', 'description': 'Simples, plastificados, magnéticos e com tassel.'},
    {'id': 'calendarios', 'name': 'Calendários personalizados', 'description': 'Calendários anuais para igrejas, ministérios e organizações.'},
    {'id': 'certificados', 'name': 'Certificados', 'description': 'Batismo, apresentação de crianças, cursos, consagrações e diaconato.'},
    {'id': 'crachas', 'name': 'Crachás personalizados', 'description': 'Equipes, ministérios, liderança, voluntários e eventos.'},
    {'id': 'diversos', 'name': 'Materiais gráficos diversos', 'description': 'Cartões, adesivos, panfletos, flyers, convites e lembrancinhas.'},
    {'id': 'artes', 'name': 'Criação e personalização de artes', 'description': 'Adaptação de modelos, logotipos, informações, QR Codes e artes para impressão.'},
]
STAGES = ['Novo', 'Aguardando arte', 'Em produção', 'Enviado', 'Concluído', 'Cancelado']


def connect():
    DB.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    return conn


def initialize():
    with connect() as c:
        auth.initialize(c)
        meta.initialize(c)
        c.executescript('''
        CREATE TABLE IF NOT EXISTS transactions (id INTEGER PRIMARY KEY, description TEXT NOT NULL, kind TEXT NOT NULL, amount INTEGER NOT NULL, date TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS inventory (id INTEGER PRIMARY KEY, name TEXT NOT NULL, unit TEXT NOT NULL, quantity REAL NOT NULL, minimum REAL NOT NULL);
        CREATE TABLE IF NOT EXISTS orders (id INTEGER PRIMARY KEY, customer TEXT NOT NULL, product TEXT NOT NULL, quantity INTEGER NOT NULL, total INTEGER NOT NULL, status TEXT NOT NULL, notes TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS posts (id INTEGER PRIMARY KEY, product TEXT NOT NULL, channel TEXT NOT NULL, caption TEXT NOT NULL, source TEXT NOT NULL);
        ''')
        publishing.initialize(c)
        scheduling.initialize(c)
        scheduler_http.initialize(c)
        social_mcp.initialize(c)
        feed_composer.initialize(c)


def required(data, key, limit=200):
    value = data.get(key)
    if not isinstance(value, str) or not value.strip() or len(value) > limit:
        raise ValueError(f'Preencha {key} (até {limit} caracteres).')
    return value.strip()


def number(data, key, integer=False, positive=False):
    value = data.get(key)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f'Valor inválido: {key}.')
    import math
    if not math.isfinite(value) or value < 0 or value > 1e12 or (integer and value != int(value)) or (positive and value == 0):
        raise ValueError(f'Valor inválido: {key}.')
    return int(value) if integer else value


def catalog_product(data):
    key = required(data, 'product')
    product = next((p for p in PRODUCTS if p['id'] == key), None)
    if not product:
        raise ValueError('Selecione um produto do catálogo.')
    return product


def brl(cents):
    return f'R$ {cents / 100:.2f}'.replace('.', ',')


def commercial_reply(message):
    text = message.casefold()
    if 'envelope' in text and any(w in text for w in ['preço', 'preco', 'valor', 'custa', 'orçamento', 'orcamento', 'quanto']):
        quantities = [int(x.replace('.', '')) for x in re.findall(r'\b\d{1,3}(?:\.\d{3})\b|\b\d+\b', text)]
        if quantities and any(q not in PRICES for q in quantities):
            return 'Olá! O pedido mínimo de envelopes é de 100 unidades. Para essa quantidade ou condição específica, vou encaminhar seu orçamento para confirmação com o responsável. Não tenho um preço cadastrado para informar.'
        prices = '; '.join(f'{q:,} unidades: {brl(v)}'.replace(',', '.', 1) if q == 1000 else f'{q} unidades: {brl(v)}' for q, v in PRICES.items())
        return f'Olá! Nossos envelopes C6 (16,2 × 11,4 cm) podem incluir o logotipo da igreja e QR Code Pix. Valores cadastrados: {prices}. Qual quantidade você precisa? Envie também o nome da igreja, logotipo e dados para personalização. Frete e prazo precisam de confirmação com o responsável.'
    if any(w in text for w in ['prazo', 'frete', 'desconto', 'estoque', 'disponível', 'disponivel', 'entrega']):
        return 'Enviamos para todo o Brasil por Correios e transportadoras. Para confirmar prazo, disponibilidade, frete ou uma condição especial, preciso encaminhar ao responsável. Pode informar o produto, a quantidade e o CEP?'
    if any(w in text for w in ['pagamento', 'pix', 'cartão', 'cartao', 'parcel']):
        return 'Aceitamos Pix ou cartão de crédito em até 12 vezes com juros pelo site www.artenoaltar.com.br. As condições finais devem ser conferidas no site. Qual produto e quantidade você procura?'
    return 'Olá! Seja bem-vindo à Arte no Altar – Ideias que Edificam, de Poços de Caldas/MG. Criamos envelopes, Projetos de Vida, marca-páginas, calendários, certificados, crachás e outros materiais personalizados. Qual produto e quantidade você procura? Para preços não cadastrados e condições específicas, vou encaminhar ao responsável.'


def caption(product, use_ai):
    draft = f'{product["name"]} para transformar suas ideias em materiais cheios de propósito. ✨\n\n{product["description"]}\n\nNa Arte no Altar, personalizamos materiais para igrejas, ministérios e eventos. Enviamos para todo o Brasil por Correios e transportadoras.\n\nConheça em www.artenoaltar.com.br ou fale com a gente pelo WhatsApp disponível no site.\n\n#ArteNoAltar #GráficaCristã #Personalizados #Igrejas'
    if not use_ai:
        return draft, 'Modelo local'
    key = os.environ.get('ARTENOALTAR_AI_KEY')
    if not key:
        raise ValueError('A IA ainda não está configurada. Use o modelo local ou configure a chave com segurança no servidor.')
    body = {'model': os.environ.get('ARTENOALTAR_AI_MODEL', 'gpt-4.1-mini'), 'instructions': 'Escreva uma legenda cordial, profissional e natural em português brasileiro para Instagram/Facebook da Arte no Altar – Ideias que Edificam, Poços de Caldas/MG, @arte.no.altar. Use somente os fatos fornecidos. Nunca invente preços, prazos, disponibilidade, descontos ou condições. Não prometa resultados. Termine convidando para orçamento no site www.artenoaltar.com.br. Não inclua preços. Retorne somente a legenda, com até 1500 caracteres. Todo resultado será revisado por uma pessoa.', 'input': draft, 'max_output_tokens': 600, 'store': False}
    request = urllib.request.Request('https://api.openai.com/v1/responses', data=json.dumps(body).encode(), headers={'Authorization': f'Bearer {key}', 'Content-Type': 'application/json'})
    try:
        with urllib.request.urlopen(request, timeout=40) as response:
            result = json.load(response)
        output = '\n'.join(part['text'] for item in result.get('output', []) for part in item.get('content', []) if part.get('type') == 'output_text').strip()
        if not output:
            raise ValueError('A IA não retornou uma legenda. Tente novamente.')
        return output, 'IA · revisão necessária'
    except (urllib.error.URLError, TimeoutError):
        raise ValueError('Não foi possível acessar a IA. Verifique a chave, o saldo e a permissão de rede do servidor.') from None


class Handler(BaseHTTPRequestHandler):
    def security_headers(self):
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('X-Frame-Options', 'DENY')
        self.send_header('Referrer-Policy', 'no-referrer')
        self.send_header('Content-Security-Policy', "default-src 'self'; style-src 'self' 'unsafe-inline'; script-src 'self'; img-src 'self' data:; frame-ancestors 'none'; base-uri 'none'; form-action 'self'")
        if os.environ.get('ARTENOALTAR_ORIGIN', '').startswith('https://'):
            self.send_header('Strict-Transport-Security', 'max-age=31536000')

    def end_headers(self):
        self.security_headers()
        super().end_headers()

    def signed_in(self):
        with connect() as c:
            return auth.authenticated(c, self.headers.get('Cookie'))

    def valid_origin(self):
        expected = os.environ.get('ARTENOALTAR_ORIGIN', '')
        host = self.headers.get('Host', '')
        if expected:
            if host != urlsplit(expected).netloc:
                return False
        else:
            if host.split(':')[0] not in ['localhost', '127.0.0.1']:
                return False
            expected = f'http://{host}'
        return self.headers.get('Origin') == expected

    def session_cookie(self, token='', clear=False):
        secure = '; Secure' if os.environ.get('ARTENOALTAR_ORIGIN', '').startswith('https://') else ''
        return f'arte_session={token}; Path=/; HttpOnly; SameSite=Strict; Max-Age={0 if clear else auth.SESSION_SECONDS}{secure}'

    def log_message(self, fmt, *args):
        # Não registrar conteúdos comerciais ou chaves.
        pass

    def send_json(self, value, status=200, cookie=None):
        payload = json.dumps(value, ensure_ascii=False).encode()
        self.send_response(status)
        if cookie:
            self.send_header('Set-Cookie', cookie)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(payload)))
        self.send_header('Cache-Control', 'no-store')
        self.end_headers()
        self.wfile.write(payload)

    def do_GET(self):
        if urlsplit(self.path).path == scheduler_http.PATH:
            return scheduler_http.handle(self, 'GET', connect, DB.parent)
        if urlsplit(self.path).path == '/mcp':
            return social_mcp.handle(self, 'GET', connect, DB.parent)
        if self.path.startswith('/media/'):
            try:
                payload=publishing.image_file(DB.parent,self.path.removeprefix('/media/')).read_bytes()
            except (ValueError,OSError):
                return self.send_json({'error':'Imagem não encontrada.'},404)
            self.send_response(200)
            self.send_header('Content-Type','image/jpeg')
            self.send_header('Content-Length',str(len(payload)))
            self.send_header('Cache-Control','public, max-age=86400')
            self.send_header('X-Arte-Media-Source','application')
            self.end_headers()
            self.wfile.write(payload)
            return
        if urlsplit(self.path).path == meta.CALLBACK:
            return self.meta_callback()
        if self.path == '/healthz':
            with connect() as c:
                c.execute('SELECT 1').fetchone()
            return self.send_json({'ok': True})
        if self.path == '/api/auth':
            with connect() as c:
                return self.send_json({'authenticated': auth.authenticated(c, self.headers.get('Cookie')), 'configured': auth.configured(c)})
        if self.path.startswith('/api/') and not self.signed_in():
            return self.send_json({'error': 'Entre para acessar o sistema.'}, 401)
        if self.path == '/api/state':
            with connect() as c:
                result = {table: [dict(r) for r in c.execute(f'SELECT * FROM {table} ORDER BY id DESC')] for table in ['transactions', 'inventory', 'orders', 'posts']}
                schedules={r['post_id']:dict(r) for r in c.execute('SELECT * FROM post_schedule')}
                for post in result['posts']:
                    schedule=schedules.get(post['id'])
                    post['schedule']={k:schedule[k] for k in ['due_at','state','error']} if schedule else None
                result['scheduler']=scheduling.runtime(c)
            try:
                social = meta.status(DB.parent)
            except ValueError as error:
                social = {'configured': False, 'authorized': False, 'accounts_verified': False, 'callback_url': None, 'message': str(error)}
            result.update(products=PRODUCTS, stages=STAGES, ai_configured=bool(os.environ.get('ARTENOALTAR_AI_KEY')), meta=social)
            return self.send_json(result)
        files = {'/': ('index.html' if self.signed_in() else 'login.html', 'text/html; charset=utf-8'), '/style.css': ('style.css', 'text/css'), '/app.js': ('app.js', 'text/javascript'), '/login.js': ('login.js', 'text/javascript')}
        if self.path not in files:
            return self.send_json({'error': 'Página não encontrada.'}, 404)
        name, mime = files[self.path]
        payload = (ROOT / 'static' / name).read_bytes()
        self.send_response(200)
        self.send_header('Content-Type', mime)
        self.send_header('Content-Length', str(len(payload)))
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.end_headers()
        self.wfile.write(payload)

    def do_POST(self):
        if urlsplit(self.path).path == scheduler_http.PATH:
            return scheduler_http.handle(self, 'POST', connect, DB.parent)
        if urlsplit(self.path).path == '/mcp':
            return social_mcp.handle(self, 'POST', connect, DB.parent)
        # Origem explícita obrigatória também para login (proteção CSRF).
        if not self.valid_origin():
            return self.send_json({'error': 'Origem não permitida.'}, 403)
        if self.path != '/api/login' and not self.signed_in():
            return self.send_json({'error': 'Entre para acessar o sistema.'}, 401)
        try:
            length = int(self.headers.get('Content-Length', 0))
            if length <= 0 or length > (8*1024*1024 if self.path=='/api/media' else 20000):
                raise ValueError('Tamanho de requisição inválido.')
            d = json.loads(self.rfile.read(length))
            if not isinstance(d, dict):
                raise ValueError('Dados inválidos.')
            if self.path == '/api/login':
                with connect() as c:
                    token, error, status = auth.login(c, d.get('password'))
                if error:
                    return self.send_json({'error': error}, status)
                return self.send_json({'ok': True}, cookie=self.session_cookie(token))
            if self.path == '/api/logout':
                with connect() as c:
                    c.execute('DELETE FROM sessions WHERE token_hash=?', (auth.token_hash(self.headers.get('Cookie')),))
                return self.send_json({'ok': True}, cookie=self.session_cookie(clear=True))
            if self.path == '/api/meta/start':
                with connect() as c:
                    url, browser = meta.start(c, DB.parent, auth.token_hash(self.headers.get('Cookie')))
                return self.send_json({'url': url}, cookie=f'arte_meta={browser}; Path={meta.CALLBACK}; HttpOnly; Secure; SameSite=Lax; Max-Age=600')
            if self.path == '/api/meta/disconnect':
                with connect() as c:
                    meta.disconnect(c, DB.parent)
                return self.send_json({'ok': True})
            if self.path == '/api/meta/verify':
                meta.verify_accounts(DB.parent)
                return self.send_json({'ok': True})
            if self.path == '/api/media':
                return self.send_json(publishing.upload(DB.parent,d.get('data')),201)
            if self.path == '/api/feed/models':
                return self.send_json(feed_composer.models(DB.parent))
            if self.path == '/api/feed/compose':
                return self.send_json(feed_composer.compose(connect, DB.parent, d), 201)
            if self.path == '/api/posts/update':
                with connect() as c:
                    result=publishing.update(c,DB.parent,d)
                return self.send_json(result)
            if self.path == '/api/posts/schedule':
                with connect() as c:
                    result=scheduling.save(c,DB.parent,d)
                return self.send_json(result)
            if self.path == '/api/posts/cancel-schedule':
                if any(type(d.get(key)) is not int for key in ('revision','expected_due_at')):
                    raise ValueError('Atualize a página e confira o agendamento antes de cancelar.')
                with connect() as c:
                    scheduling.cancel(c,d)
                return self.send_json({'ok':True})
            if self.path in ['/api/posts/publish','/api/posts/finish']:
                result=publishing.publish(connect,DB.parent,d,finish=self.path.endswith('/finish'))
                return self.send_json(result,202 if result['status']=='processing' else 200)
            if self.path in ['/api/posts/test-image','/api/posts/test-meta-image']:
                result=publishing.publish(connect,DB.parent,d,prepare_only=True,via_meta=self.path.endswith('/test-meta-image'))
                return self.send_json(result,202)
            if self.path == '/api/posts/reset':
                with connect() as c:
                    publishing.reset(c,d)
                return self.send_json({'ok':True})
            if self.path == '/api/posts/diagnose':
                return self.send_json(publishing.diagnose(connect,DB.parent,d))
            with connect() as c:
                if self.path == '/api/transactions':
                    kind = required(d, 'kind')
                    if kind not in ['income', 'expense']:
                        raise ValueError('Tipo de lançamento inválido.')
                    day = date.fromisoformat(required(d, 'date')).isoformat()
                    c.execute('INSERT INTO transactions(description,kind,amount,date) VALUES(?,?,?,?)', (required(d, 'description'), kind, number(d, 'amount', True, True), day))
                elif self.path == '/api/inventory':
                    c.execute('INSERT INTO inventory(name,unit,quantity,minimum) VALUES(?,?,?,?)', (required(d, 'name'), required(d, 'unit', 30), number(d, 'quantity'), number(d, 'minimum')))
                elif self.path == '/api/inventory/quantity':
                    cursor = c.execute('UPDATE inventory SET quantity=? WHERE id=?', (number(d, 'quantity'), number(d, 'id', True, True)))
                    if cursor.rowcount != 1:
                        raise ValueError('Material não encontrado.')
                elif self.path == '/api/orders':
                    p = catalog_product(d)
                    notes = d.get('notes', '')
                    if not isinstance(notes, str) or len(notes) > 3000:
                        raise ValueError('Observações inválidas.')
                    c.execute('INSERT INTO orders(customer,product,quantity,total,status,notes) VALUES(?,?,?,?,?,?)', (required(d, 'customer'), p['name'], number(d, 'quantity', True, True), number(d, 'total', True), 'Novo', notes))
                elif self.path == '/api/orders/status':
                    status = required(d, 'status')
                    if status not in STAGES:
                        raise ValueError('Etapa inválida.')
                    cursor = c.execute('UPDATE orders SET status=? WHERE id=?', (status, number(d, 'id', True, True)))
                    if cursor.rowcount != 1:
                        raise ValueError('Pedido não encontrado.')
                elif self.path == '/api/posts':
                    p = catalog_product(d)
                    channel = required(d, 'channel')
                    if channel not in ['Instagram', 'Facebook']:
                        raise ValueError('Canal inválido.')
                    body, source = caption(p, d.get('use_ai') is True)
                    c.execute('INSERT INTO posts(product,channel,caption,source) VALUES(?,?,?,?)', (p['name'], channel, body, source))
                elif self.path == '/api/reply':
                    return self.send_json({'reply': commercial_reply(required(d, 'message', 3000)), 'source': 'Resposta por regras · revisão necessária'})
                elif self.path == '/api/delete':
                    table = required(d, 'table')
                    if table not in ['transactions', 'inventory', 'orders', 'posts']:
                        raise ValueError('Registro inválido.')
                    if table=='posts':
                        row=c.execute('SELECT publish_status FROM posts WHERE id=?',(d.get('id'),)).fetchone()
                        if row and row[0] in ['sending','processing','review','scheduled']:
                            raise ValueError('Confira o resultado do envio antes de excluir este registro.')
                    c.execute(f'DELETE FROM {table} WHERE id=?', (number(d, 'id', True, True),))
                else:
                    return self.send_json({'error': 'Operação não encontrada.'}, 404)
            self.send_json({'ok': True}, 201)
        except (ValueError, TypeError, KeyError):
            import sys
            error = sys.exception()
            self.send_json({'error': str(error) if isinstance(error, ValueError) else 'Dados inválidos.'}, 400)
        except sqlite3.Error:
            self.send_json({'error': 'Não foi possível salvar os dados.'}, 500)
        except OSError:
            self.send_json({'error':'Não foi possível acessar o arquivo no servidor. Confira o espaço disponível.'},500)

    def meta_callback(self):
        query = parse_qs(urlsplit(self.path).query)
        message = 'O endereço de retorno está pronto. Entre no sistema e use Conectar à Meta para iniciar a autorização.'
        status = 200
        if query:
            try:
                cookie = SimpleCookie()
                cookie.load(self.headers.get('Cookie', ''))
                browser = cookie.get('arte_meta')
                with connect() as c:
                    valid = meta.consume(c, query, browser.value if browser else '')
                if not valid:
                    raise ValueError('A solicitação expirou ou não corresponde a este navegador. Entre novamente no sistema e reinicie a conexão.')
                if query.get('error'):
                    raise ValueError('A autorização foi cancelada ou recusada na Meta. Você pode tentar novamente pelo sistema.')
                meta.exchange(DB.parent, query.get('code',[''])[0])
                message = 'Autorização recebida. A identificação das contas e as permissões de publicação ainda precisam ser verificadas. Nenhum conteúdo foi publicado.'
            except (ValueError, CookieError) as error:
                message = str(error) if isinstance(error, ValueError) else 'Não foi possível validar este navegador. Reinicie a conexão pelo sistema.'
                status = 400
            except sqlite3.Error:
                message = 'Não foi possível concluir a conexão. Entre no sistema e tente novamente.'
                status = 503
        # Sem scripts ou dados da Meta no HTML. O clique retorna à mesma origem e
        # permite que o navegador envie novamente a sessão SameSite=Strict.
        payload = ('<!doctype html><html lang="pt-BR"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Conexão Meta · Arte no Altar</title><link rel="stylesheet" href="/style.css"></head><body><div class="login-form-area"><section class="card"><h1>Conexão com a Meta</h1><p class="help">'+html.escape(message)+'</p><a class="button" href="/#conteudo">Continuar no sistema</a></section></div></body></html>').encode()
        self.send_response(status)
        self.send_header('Set-Cookie',f'arte_meta=; Path={meta.CALLBACK}; HttpOnly; Secure; SameSite=Lax; Max-Age=0')
        self.send_header('Content-Type','text/html; charset=utf-8')
        self.send_header('Content-Length',str(len(payload)))
        self.send_header('Cache-Control','no-store')
        self.end_headers()
        self.wfile.write(payload)


if __name__ == '__main__':
    import sys
    initialize()
    if len(sys.argv) > 1 and sys.argv[1] == 'set-password':
        import getpass
        password = getpass.getpass('Nova senha (mínimo 12 caracteres): ')
        if password != getpass.getpass('Confirme a senha: '):
            raise SystemExit('As senhas não conferem.')
        with connect() as c:
            auth.set_password(c, password)
        raise SystemExit('Senha cadastrada. Sessões anteriores encerradas.')
    port = int(os.environ.get('PORT', '8000'))
    print(f'Arte no Altar: servidor local na porta {port}', flush=True)
    ThreadingHTTPServer(('127.0.0.1', port), Handler).serve_forever()

