"""MCP social restrito: rascunhos e agendamento, sem publicação imediata ou acesso comercial.

Implantação e entrega de anexos pelo cliente precisam de validação externa.
"""
import hashlib
import hmac
import json
import os
import re
import secrets
import sqlite3
import time
from datetime import datetime
from zoneinfo import ZoneInfo

import meta
import publishing
import scheduling

ZONE = ZoneInfo('America/Sao_Paulo')
VERSION = '2025-06-18'
MAX_BODY = 8 * 1024 * 1024


def initialize(c):
    c.execute('''CREATE TABLE IF NOT EXISTS social_mcp_operations (
      id TEXT PRIMARY KEY, idempotency_key TEXT UNIQUE NOT NULL,
      content_hash TEXT NOT NULL, post_id INTEGER NOT NULL,
      desired_at TEXT, created_at INTEGER NOT NULL)''')
    c.execute('''CREATE TABLE IF NOT EXISTS social_mcp_connections (
      id INTEGER PRIMARY KEY, created_at INTEGER NOT NULL,
      http_status INTEGER NOT NULL, reason TEXT NOT NULL,
      protocol TEXT NOT NULL, origin_present INTEGER NOT NULL)''')
    c.execute('''CREATE TABLE IF NOT EXISTS social_mcp_schedule_operations (
      id TEXT PRIMARY KEY, idempotency_key TEXT UNIQUE NOT NULL,
      content_hash TEXT NOT NULL, post_id INTEGER NOT NULL,
      revision INTEGER NOT NULL, account_id TEXT NOT NULL, channel TEXT NOT NULL,
      desired_at TEXT NOT NULL, due_at INTEGER NOT NULL, created_at INTEGER NOT NULL)''')


def connection_event(connect, request, status, reason):
    """Diagnóstico limitado: nunca copiar cabeçalhos, argumentos ou credenciais."""
    version=request.headers.get('MCP-Protocol-Version','')
    version=version if re.fullmatch(r'20\d\d-\d\d-\d\d',version) else 'ausente/outra'
    try:
        with connect() as c:
            c.execute('INSERT INTO social_mcp_connections(created_at,http_status,reason,protocol,origin_present) VALUES(?,?,?,?,?)',
                (int(time.time()),status,reason,version,int(request.headers.get('Origin') is not None)))
            c.execute('DELETE FROM social_mcp_connections WHERE id NOT IN (SELECT id FROM social_mcp_connections ORDER BY id DESC LIMIT 30)')
    except sqlite3.Error:
        # O diagnóstico não deve bloquear o MCP se o disco estiver ocupado.
        pass


def schema(properties=None, required=()):
    return {'type': 'object', 'properties': properties or {},
            'required': list(required), 'additionalProperties': False}


STRING = {'type': 'string', 'minLength': 1, 'maxLength': 200}
POST_ID = {'type': 'integer', 'minimum': 1, 'maximum': 9007199254740991}
REVISION = {'type': 'integer', 'minimum': 0, 'maximum': 2147483647}
CHANNEL = {'type': 'string', 'enum': ['Instagram', 'Facebook']}
IDEMPOTENCY = {'type': 'string', 'minLength': 16, 'maxLength': 128}
CONFIRMED = {'type': 'boolean', 'const': True}
TOOLS = [
    ('social_list_accounts', 'Consultar contas verificadas em cache; não atualiza a Meta.', schema()),
    ('social_list_agenda', 'Consultar fila local em intervalo de até 90 dias e estado do executor.',
     schema({'start': STRING, 'end': STRING}, ('start', 'end'))),
    ('social_list_recent_content', 'Consultar histórico LOCAL; não representa todas as publicações das redes.',
     schema({'account_id': STRING, 'limit': {'type': 'integer', 'minimum': 1, 'maximum': 50}}, ('account_id',))),
    ('social_import_draft', 'Após mostrar conta, imagem, legenda, formato e horário e receber confirmação, criar somente rascunho. JPEG base64 deve vir dos bytes reais do arquivo aprovado. Verifique se o cliente atual permite ler e transportar o arquivo; nunca inventar base64. O servidor não lê caminhos locais do computador.',
     schema({'account_id': STRING, 'channel': {'type': 'string', 'enum': ['Instagram', 'Facebook']},
             'format': {'type': 'string', 'enum': ['feed_photo']},
             'caption': {'type': 'string', 'minLength': 1, 'maxLength': 2200},
             'image_base64': {'type': 'string', 'minLength': 1, 'maxLength': 7 * 1024 * 1024},
             'idempotency_key': {'type': 'string', 'minLength': 16, 'maxLength': 128},
             'confirmed': {'type': 'boolean', 'const': True}, 'desired_at': STRING},
            ('account_id', 'channel', 'format', 'caption', 'image_base64', 'idempotency_key', 'confirmed'))),
    ('social_get_draft', 'Consultar conta, imagem, legenda, revisão e estado atual de um rascunho social autorizado antes de confirmar agendamento. Sem alterar ou publicar.',
     schema({'post_id': POST_ID}, ('post_id',))),
    ('social_schedule_draft', 'Autorizar publicação automática futura de uma foto de feed já salva. Exige revisão de conta, imagem, legenda e data/hora de São Paulo com confirmação explícita. Não publica agora. Recusa executor inativo, revisão alterada e conflito no mesmo minuto/conta. Repetir com a mesma chave e dados em caso de dúvida.',
     schema({'post_id': POST_ID, 'revision': REVISION, 'account_id': STRING,
             'channel': CHANNEL, 'desired_at': STRING, 'idempotency_key': IDEMPOTENCY,
             'confirmed': CONFIRMED},
            ('post_id', 'revision', 'account_id', 'channel', 'desired_at', 'idempotency_key', 'confirmed'))),
    ('social_get_operation', 'Consultar recibo de importação ou aceite de agendamento pelo identificador. O recibo não comprova publicação; consulte social_get_draft para o estado atual local.',
     schema({'operation_id': STRING}, ('operation_id',))),
]


def validate(value, spec):
    kind = spec['type']
    valid = {'object': type(value) is dict, 'string': type(value) is str,
             'integer': type(value) is int, 'boolean': type(value) is bool}[kind]
    if not valid:
        raise ValueError('Tipo de argumento inválido.')
    if kind == 'object':
        if set(value) - set(spec['properties']) or set(spec['required']) - set(value):
            raise ValueError('Argumentos desconhecidos ou obrigatórios ausentes.')
        for key, item in value.items():
            validate(item, spec['properties'][key])
    if kind == 'string' and not spec.get('minLength', 0) <= len(value) <= spec.get('maxLength', MAX_BODY):
        raise ValueError('Comprimento de argumento inválido.')
    if kind == 'integer' and not spec['minimum'] <= value <= spec['maximum']:
        raise ValueError('Limite inválido.')
    if 'enum' in spec and value not in spec['enum'] or 'const' in spec and value != spec['const']:
        raise ValueError('Valor de argumento não permitido.')


def instant(value):
    try:
        parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
        if parsed.tzinfo is None or parsed.utcoffset() != parsed.astimezone(ZONE).utcoffset():
            raise ValueError()
        return parsed
    except (ValueError, TypeError, OverflowError):
        raise ValueError('Use RFC 3339 com o deslocamento de America/Sao_Paulo.') from None


def accounts(directory):
    state = meta.status(directory)
    return {'accounts': [{k: a.get(k) for k in ('id', 'name', 'channel')}
                         for a in state.get('accounts', [])],
            'checked_at': state.get('checked_at'), 'source': 'verified_cache',
            'capabilities': {'feed_photo_draft': True, 'schedule_feed_photo': True, 'publish': False,
                             'stories': False, 'carousel': False, 'drive': False,
                             'jpeg_base64_import': True,
                             'file_transfer_requires_client_access': True}}


def allowed_account(directory, account_id, channel=None):
    for account in accounts(directory)['accounts']:
        if account['id'] == account_id and (channel is None or account['channel'] == channel):
            return account
    raise ValueError('Conta não autorizada ou conexão expirada. Verifique as contas no sistema.')


def operation(c, operation_id):
    row = c.execute('SELECT id,post_id,desired_at,created_at FROM social_mcp_operations WHERE id=?',
                    (operation_id,)).fetchone()
    if not row:
        scheduled = c.execute('''SELECT id,post_id,revision,account_id,channel,
            desired_at,due_at,created_at FROM social_mcp_schedule_operations WHERE id=?''',
            (operation_id,)).fetchone()
        if not scheduled:
            raise ValueError('Operação não encontrada.')
        return dict(scheduled) | {'status': 'schedule_accepted', 'published_by_operation': False,
                                  'scheduled_by_operation': True, 'timezone': str(ZONE),
                                  'review_path': '/#conteudo'}
    return dict(row) | {'status': 'draft_imported', 'published_by_operation': False,
                        'scheduled_by_operation': False, 'timezone': str(ZONE),
                        'review_path': '/#conteudo'}


def social_post(c, directory, post_id):
    row = c.execute('''SELECT id,revision,account_id,channel,caption,image_name,
        publish_status,remote_id FROM posts WHERE id=?''', (post_id,)).fetchone()
    if not row:
        raise ValueError('Rascunho não encontrado.')
    post = dict(row)
    account = allowed_account(directory, post['account_id'], post['channel'])
    return post, account


def get_draft(connect, directory, post_id):
    with connect() as c:
        post, account = social_post(c, directory, post_id)
        scheduled = c.execute('SELECT due_at,state FROM post_schedule WHERE post_id=?', (post_id,)).fetchone()
        executor = scheduling.runtime(c)
    image_url = None
    if post['image_name']:
        publishing.image_file(directory, post['image_name'])
        image_url = meta.callback_url().removesuffix(meta.CALLBACK) + '/media/' + post['image_name']
    return {key: post[key] for key in ('id', 'revision', 'account_id', 'channel', 'caption', 'publish_status', 'remote_id')} | {
        'account_name': account.get('name'), 'format': 'feed_photo' if image_url else 'text',
        'image_url': image_url, 'schedule': dict(scheduled) if scheduled else None,
        'scheduler': executor, 'timezone': str(ZONE)}


def schedule_draft(connect, directory, data):
    when = instant(data['desired_at']).astimezone(ZONE).replace(microsecond=0)
    desired = when.isoformat()
    canonical = data | {'desired_at': desired}
    digest = hashlib.sha256(json.dumps({k: v for k, v in canonical.items()
        if k not in ('idempotency_key', 'confirmed')}, sort_keys=True).encode()).hexdigest()
    with connect() as c:
        c.execute('BEGIN IMMEDIATE')
        post, _ = social_post(c, directory, data['post_id'])
        if (post['account_id'], post['channel']) != (data['account_id'], data['channel']):
            raise ValueError('A conta ou canal do rascunho não corresponde à confirmação. Revise novamente.')
        old = c.execute('SELECT id,content_hash FROM social_mcp_schedule_operations WHERE idempotency_key=?',
                        (data['idempotency_key'],)).fetchone()
        if old:
            if old['content_hash'] != digest:
                raise ValueError('Chave de idempotência reutilizada com conteúdo diferente.')
            return operation(c, old['id'])
        if c.execute('SELECT 1 FROM social_mcp_operations WHERE idempotency_key=?', (data['idempotency_key'],)).fetchone():
            raise ValueError('Use uma chave de idempotência própria para o agendamento, diferente da importação.')
        if post['revision'] != data['revision'] or post['publish_status'] != 'draft':
            raise ValueError('O rascunho mudou ou não está disponível. Consulte-o e revise novamente.')
        if not post['image_name']:
            raise ValueError('O agendamento pelo plugin exige uma foto JPEG de feed.')
        due = int(when.timestamp())
        minute = due // 60 * 60
        conflict = c.execute('''SELECT 1 FROM post_schedule s JOIN posts p ON p.id=s.post_id
            WHERE p.account_id=? AND p.channel=? AND s.state IN ('queued','running','processing')
            AND s.due_at>=? AND s.due_at<?''',
            (post['account_id'], post['channel'], minute, minute + 60)).fetchone()
        if conflict:
            raise ValueError('Já existe uma publicação nessa conta e minuto. Escolha outro horário e confirme novamente.')
        result = scheduling.save(c, directory, {'id': data['post_id'], 'revision': data['revision'],
            'when': when.replace(tzinfo=None).isoformat(), 'confirmed': True})
        ident = secrets.token_hex(16)
        c.execute('INSERT INTO social_mcp_schedule_operations VALUES(?,?,?,?,?,?,?,?,?,?)',
            (ident, data['idempotency_key'], digest, data['post_id'], data['revision'],
             data['account_id'], data['channel'], desired, result['due_at'], int(time.time())))
        return operation(c, ident)


def call(name, data, connect, directory):
    spec = next((t[2] for t in TOOLS if t[0] == name), None)
    if spec is None:
        raise ValueError('Ferramenta desconhecida.')
    validate(data, spec)
    if name == 'social_list_accounts':
        return accounts(directory)
    if name == 'social_list_agenda':
        start, end = instant(data['start']).timestamp(), instant(data['end']).timestamp()
        if not 0 < end - start <= 90 * 86400:
            raise ValueError('O intervalo deve ser positivo e de até 90 dias.')
        granted = {a['id'] for a in accounts(directory)['accounts']}
        with connect() as c:
            placeholders = ','.join('?' for _ in granted) or 'NULL'
            rows = c.execute(f'''SELECT p.id,p.account_id,p.channel,p.caption,p.publish_status,
                s.due_at,s.state FROM post_schedule s JOIN posts p ON p.id=s.post_id
                WHERE s.due_at>=? AND s.due_at<? AND p.account_id IN ({placeholders})
                ORDER BY s.due_at LIMIT 201''', (start, end, *granted)).fetchall()
            rows = [dict(r) for r in rows]
            return {'items': rows[:200], 'truncated': len(rows) > 200,
                    'source': 'local_schedule_queue', 'scheduler': scheduling.runtime(c),
                    'timezone': str(ZONE)}
    if name == 'social_list_recent_content':
        allowed_account(directory, data['account_id'])
        with connect() as c:
            rows = c.execute('''SELECT id,channel,caption,publish_status,remote_id FROM posts
                WHERE account_id=? ORDER BY id DESC LIMIT ?''',
                (data['account_id'], data.get('limit', 20))).fetchall()
            return {'items': [dict(r) for r in rows], 'source': 'local_only',
                    'complete_remote_history': False, 'order': 'local_creation_id_desc'}
    if name == 'social_get_operation':
        with connect() as c:
            return operation(c, data['operation_id'])
    if name == 'social_get_draft':
        return get_draft(connect, directory, data['post_id'])
    if name == 'social_schedule_draft':
        return schedule_draft(connect, directory, data)
    allowed_account(directory, data['account_id'], data['channel'])
    if not data['caption'].strip():
        raise ValueError('A legenda não pode estar vazia.')
    desired = instant(data['desired_at']).isoformat() if 'desired_at' in data else None
    digest = hashlib.sha256(json.dumps({k: v for k, v in data.items()
                                      if k not in ('idempotency_key', 'confirmed')},
                                     sort_keys=True).encode()).hexdigest()
    uploaded = None
    try:
        with connect() as c:
            # Serializa importações para que retries concorrentes não dupliquem imagens/posts.
            c.execute('BEGIN IMMEDIATE')
            if c.execute('SELECT 1 FROM social_mcp_schedule_operations WHERE idempotency_key=?', (data['idempotency_key'],)).fetchone():
                raise ValueError('Use uma chave de idempotência própria para a importação, diferente do agendamento.')
            old = c.execute('SELECT id,content_hash FROM social_mcp_operations WHERE idempotency_key=?',
                            (data['idempotency_key'],)).fetchone()
            if old:
                if old['content_hash'] != digest:
                    raise ValueError('Chave de idempotência reutilizada com conteúdo diferente.')
                return operation(c, old['id'])
            uploaded = publishing.upload(directory, data['image_base64'])
            if data['channel'] == 'Instagram' and not (320 <= uploaded['width'] <= 1440 and
                    .8 <= uploaded['width'] / uploaded['height'] <= 1.91):
                raise ValueError('Imagem incompatível com feed Instagram. Use, por exemplo, 1080 × 1080.')
            post_id = c.execute('''INSERT INTO posts(product,channel,caption,source,account_id,image_name)
                VALUES(?,?,?,?,?,?)''', ('Conteúdo ChatGPT', data['channel'], data['caption'],
                                       'Importação MCP · revisão necessária', data['account_id'], uploaded['name'])).lastrowid
            op_id = secrets.token_hex(16)
            c.execute('INSERT INTO social_mcp_operations VALUES(?,?,?,?,?,?)',
                      (op_id, data['idempotency_key'], digest, post_id, desired, int(time.time())))
            result = operation(c, op_id)
        return result
    except Exception:
        if uploaded:
            (directory / 'media' / uploaded['name']).unlink(missing_ok=True)
        raise


def rpc(message, connect, directory):
    if not isinstance(message, dict) or message.get('jsonrpc') != '2.0' or not isinstance(message.get('method'), str):
        return {'jsonrpc': '2.0', 'id': None, 'error': {'code': -32600, 'message': 'Requisição inválida.'}}
    ident = message.get('id')
    if 'id' not in message:
        return None
    def error(code, text):
        return {'jsonrpc': '2.0', 'id': ident, 'error': {'code': code, 'message': text}}
    if type(ident) not in (str, int):
        return error(-32600, 'Identificador inválido.')
    params = message.get('params', {})
    if not isinstance(params, dict):
        return error(-32602, 'Parâmetros inválidos.')
    method = message['method']
    if method == 'initialize':
        result = {'protocolVersion': VERSION, 'capabilities': {'tools': {}},
                  'serverInfo': {'name': 'arte-no-altar', 'version': '0.2.0'}}
    elif method == 'ping':
        result = {}
    elif method == 'tools/list':
        result = {'tools': [{'name': name, 'description': desc, 'inputSchema': spec,
                   'annotations': {'readOnlyHint': name not in ('social_import_draft', 'social_schedule_draft'),
                                   'destructiveHint': False, 'idempotentHint': True,
                                   'openWorldHint': name == 'social_schedule_draft'}} for name, desc, spec in TOOLS]}
    elif method == 'tools/call':
        try:
            value = call(params.get('name'), params.get('arguments', {}), connect, directory)
            result = {'content': [{'type': 'text', 'text': json.dumps(value, ensure_ascii=False)}],
                      'structuredContent': value, 'isError': False}
        except ValueError as exc:
            result = {'content': [{'type': 'text', 'text': str(exc)}], 'isError': True}
        except (OSError, sqlite3.Error):
            result = {'content': [{'type': 'text', 'text': 'Falha interna. Consulte a operação antes de repetir.'}], 'isError': True}
    else:
        return error(-32601, 'Método não disponível.')
    return {'jsonrpc': '2.0', 'id': ident, 'result': result}


def handle(request, method, connect, directory):
    """Endpoint novo, independente do cookie/senha do proprietário."""
    expected = os.environ.get('ARTENOALTAR_MCP_KEY_SHA256', '')
    header = request.headers.get('Authorization', '')
    token = header[7:] if header.startswith('Bearer ') else ''
    def reject(text,status,reason):
        connection_event(connect,request,status,reason)
        return request.send_json({'error':text},status)
    if not re.fullmatch(r'[a-f0-9]{64}', expected) or len(token) < 32 or not hmac.compare_digest(
            hashlib.sha256(token.encode()).hexdigest(), expected):
        reason='integracao_desativada' if not re.fullmatch(r'[a-f0-9]{64}',expected) else 'bearer_ausente_ou_formato_invalido' if len(token)<32 else 'chave_nao_corresponde'
        return reject('Credencial da integração inválida ou integração desativada.',401,reason)
    origin = request.headers.get('Origin')
    allowed = os.environ.get('ARTENOALTAR_MCP_ALLOWED_ORIGINS', '').split(',')
    if origin is not None and origin not in [s.strip() for s in allowed if s.strip()]:
        return reject('Origem não permitida.',403,'origin_recusada')
    if method != 'POST':
        return reject('Use POST; este servidor não oferece SSE.',405,'metodo_http_nao_suportado')
    version = request.headers.get('MCP-Protocol-Version', VERSION)
    if version != VERSION:
        return reject('Versão MCP não suportada.',400,'versao_nao_suportada')
    accept = request.headers.get('Accept', '')
    if 'application/json' not in accept or 'text/event-stream' not in accept:
        return reject('Accept precisa incluir application/json e text/event-stream.',406,'accept_incompativel')
    try:
        size = int(request.headers.get('Content-Length', '0'))
        if not 0 < size <= MAX_BODY:
            return reject('Corpo vazio ou maior que 8 MiB.',413,'tamanho_invalido')
        if request.headers.get('Content-Type', '').split(';')[0].strip() != 'application/json':
            return reject('Use application/json.',415,'tipo_de_conteudo_invalido')
        raw = request.rfile.read(size)
        if len(raw) != size:
            raise ValueError()
        message = json.loads(raw)
    except (ValueError, UnicodeError):
        return reject('JSON inválido.',400,'json_invalido')
    result = rpc(message, connect, directory)
    if result is None:
        connection_event(connect,request,202,'notificacao_recebida')
        request.send_response(202)
        request.send_header('Content-Length', '0')
        request.end_headers()
        return
    phase=message.get('method') if isinstance(message,dict) else None
    phase=phase if isinstance(phase,str) else None
    reason={'initialize':'initialize_recebido','tools/list':'tools_list_recebido','tools/call':'tools_call_recebido','ping':'ping_recebido'}.get(phase,'rpc_recebido')
    connection_event(connect,request,200,reason)
    return request.send_json(result)


if __name__=='__main__':
    import sys
    import app
    if sys.argv[1:]!=['diagnose']:
        raise SystemExit('Uso: python3.12 social_mcp.py diagnose')
    app.initialize()
    with app.connect() as c:
        rows=c.execute('SELECT * FROM social_mcp_connections ORDER BY id DESC LIMIT 15').fetchall()
    if not rows:
        print('Nenhuma chamada ao MCP registrada após instalar o diagnóstico.')
    for row in reversed(rows):
        when=datetime.fromtimestamp(row['created_at'],ZONE).isoformat(timespec='seconds')
        print(f"{when} | HTTP {row['http_status']} | {row['reason']} | protocolo={row['protocol']} | Origin={'presente' if row['origin_present'] else 'ausente'}")
