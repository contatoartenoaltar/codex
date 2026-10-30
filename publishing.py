"""Publicação manual com confirmação, histórico e bloqueio de reenvio."""
import base64
import binascii
import hashlib
import hmac
import json
import re
import secrets
import struct
import time
import urllib.error
import urllib.parse
import urllib.request
import meta

MAX_IMAGE = 5 * 1024 * 1024


def initialize(conn):
    columns = {row[1] for row in conn.execute('PRAGMA table_info(posts)')}
    for name, definition in {
        'account_id': "TEXT NOT NULL DEFAULT ''", 'image_name': "TEXT NOT NULL DEFAULT ''",
        'publish_status': "TEXT NOT NULL DEFAULT 'draft'", 'remote_id': "TEXT NOT NULL DEFAULT ''",
        'container_id': "TEXT NOT NULL DEFAULT ''", 'publish_error': "TEXT NOT NULL DEFAULT ''",
        'revision': 'INTEGER NOT NULL DEFAULT 0', 'attempt_id': 'INTEGER'
    }.items():
        if name not in columns:
            conn.execute(f'ALTER TABLE posts ADD COLUMN {name} {definition}')
    conn.execute('''CREATE TABLE IF NOT EXISTS publication_attempts (
        id INTEGER PRIMARY KEY, post_id INTEGER NOT NULL, created_at INTEGER NOT NULL,
        status TEXT NOT NULL, account_id TEXT NOT NULL, caption TEXT NOT NULL,
        image_name TEXT NOT NULL, remote_id TEXT NOT NULL DEFAULT '')''')
    conn.execute('''CREATE TABLE IF NOT EXISTS publication_staged_media (
        post_id INTEGER NOT NULL, image_name TEXT NOT NULL, photo_id TEXT NOT NULL,
        PRIMARY KEY(post_id,image_name))''')


def jpeg_size(data):
    if not data.startswith(b'\xff\xd8') or not data.endswith(b'\xff\xd9'):
        raise ValueError('Envie uma imagem JPEG válida (.jpg).')
    position = 2
    while position + 4 <= len(data):
        if data[position] != 255:
            break
        while position < len(data) and data[position] == 255:
            position += 1
        if position >= len(data):
            break
        marker = data[position]
        position += 1
        if marker in (0xDA, 0xD9):
            break
        length = int.from_bytes(data[position:position+2], 'big')
        if length < 2 or position + length > len(data):
            break
        if marker in (0xC0, 0xC1, 0xC2) and length >= 8:
            height, width = struct.unpack('>HH', data[position+3:position+7])
            if width > 0 and height > 0:
                return width, height
        position += length
    raise ValueError('Não foi possível ler o tamanho do JPEG. Exporte a imagem novamente.')


def upload(directory, encoded):
    if not isinstance(encoded, str) or len(encoded) > 7 * 1024 * 1024:
        raise ValueError('A imagem deve ter até 5 MB.')
    try:
        data = base64.b64decode(encoded, validate=True)
    except (ValueError, binascii.Error):
        raise ValueError('Arquivo de imagem inválido.') from None
    if len(data) > MAX_IMAGE:
        raise ValueError('A imagem deve ter até 5 MB.')
    width, height = jpeg_size(data)
    if width>12000 or height>12000 or width*height>40000000:
        raise ValueError('Reduza as dimensões da imagem antes de enviar.')
    folder = directory/'media'
    folder.mkdir(parents=True, exist_ok=True)
    if sum(f.stat().st_size for f in folder.glob('*.jpg'))+len(data)>100*1024*1024:
        raise ValueError('O limite local de 100 MB para imagens foi atingido. Faça backup e revise o armazenamento antes de continuar.')
    name = secrets.token_hex(16) + '.jpg'
    with (folder/name).open('xb') as stream:
        stream.write(data)
    (folder/name).chmod(0o600)
    return {'name': name, 'url': '/media/'+name, 'width': width, 'height': height}


def image_file(directory, name):
    if not isinstance(name, str) or not re.fullmatch(r'[a-f0-9]{32}\.jpg', name):
        raise ValueError('Selecione uma imagem enviada ao sistema.')
    path = directory/'media'/name
    if not path.is_file() or path.is_symlink():
        raise ValueError('A imagem não foi encontrada no servidor.')
    return path


def update(conn, directory, data):
    caption, account = data.get('caption'), data.get('account_id')
    if not isinstance(caption, str) or not caption.strip() or len(caption) > 2200:
        raise ValueError('A legenda precisa ter entre 1 e 2.200 caracteres.')
    if not isinstance(account, str) or not account.isdecimal():
        raise ValueError('Selecione uma conta de destino.')
    name = data.get('image_name', '')
    if not isinstance(name,str) or isinstance(data.get('id'),bool) or not isinstance(data.get('id'),int):
        raise ValueError('Identificação ou imagem inválida.')
    if name:
        image_file(directory, name)
    revision = data.get('revision')
    if isinstance(revision, bool) or not isinstance(revision, int):
        raise ValueError('Reabra o rascunho para atualizar sua revisão.')
    cursor = conn.execute('''UPDATE posts SET caption=?,account_id=?,image_name=?,revision=revision+1
        WHERE id=? AND revision=? AND publish_status='draft' ''',
        (caption.strip(), account, name, data.get('id'), revision))
    if cursor.rowcount != 1:
        raise ValueError('O rascunho mudou ou já foi enviado. Atualize a página.')
    return {'revision': revision+1}


class Uncertain(ValueError):
    pass


def graph_post(settings, path, token, data, file_bytes=None):
    if not re.fullmatch(r'\d+/(feed|photos|media|media_publish)', path):
        raise ValueError('Destino de publicação inválido.')
    proof = hmac.new(settings['app_secret'].encode(), token.encode(), hashlib.sha256).hexdigest()
    content_type='application/x-www-form-urlencoded'
    if file_bytes is None:
        body = urllib.parse.urlencode({**data, 'appsecret_proof': proof}).encode()
    else:
        if not path.endswith('/photos') or len(file_bytes)>MAX_IMAGE:
            raise ValueError('Upload de imagem inválido.')
        boundary='ArteNoAltar'+secrets.token_hex(16)
        parts=[]
        for name,value in {**data,'appsecret_proof':proof}.items():
            if not re.fullmatch(r'[a-z_]+',name):
                raise ValueError('Campo de upload inválido.')
            parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"\r\n\r\n{value}\r\n'.encode())
        parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="source"; filename="arte.jpg"\r\nContent-Type: image/jpeg\r\n\r\n'.encode()+file_bytes+b'\r\n')
        parts.append(f'--{boundary}--\r\n'.encode())
        body=b''.join(parts)
        content_type='multipart/form-data; boundary='+boundary
    request = urllib.request.Request(f'https://graph.facebook.com/{settings["version"]}/{path}', data=body,
        headers={'Authorization': f'Bearer {token}', 'Content-Type':content_type})
    try:
        with urllib.request.build_opener(meta.NoRedirect).open(request, timeout=25) as response:
            result = json.loads(response.read(65536))
        if not isinstance(result, dict) or result.get('error') or not re.fullmatch(r'[0-9_]+', str(result.get('id', ''))):
            raise Uncertain('A resposta não confirmou o resultado. Confira a rede social antes de qualquer nova tentativa.')
        return result
    except urllib.error.HTTPError as error:
        detail=meta.error_summary(error,[token,settings['app_secret'],proof,*data.values()])
        raise Uncertain('A Meta recusou o envio ou não confirmou o resultado'+detail+' Confira a rede social antes de tentar novamente.') from None
    except (urllib.error.URLError, OSError, TimeoutError, json.JSONDecodeError):
        raise Uncertain('A conexão terminou sem confirmar o resultado. Confira a rede social antes de tentar novamente, para evitar duplicações.') from None


def set_status(connect, post_id, status, error='', remote_id='', container_id=''):
    with connect() as conn:
        conn.execute('UPDATE posts SET publish_status=?,publish_error=?,remote_id=?,container_id=? WHERE id=?',
                     (status,error,remote_id,container_id,post_id))
        conn.execute('UPDATE publication_attempts SET status=?,remote_id=? WHERE id=(SELECT attempt_id FROM posts WHERE id=?)',
                     (status,remote_id,post_id))


def publish(connect, directory, data, finish=False, prepare_only=False, via_meta=False):
    if via_meta and (not prepare_only or finish):
        raise ValueError('O envio por arquivo está disponível somente no teste de preparação.')
    if data.get('confirmed') is not True:
        raise ValueError('Confirme a publicação depois de revisar o conteúdo e a conta.')
    post_id, revision = data.get('id'), data.get('revision')
    if any(isinstance(v,bool) or not isinstance(v,int) for v in [post_id,revision]):
        raise ValueError('Identificação ou revisão inválida.')
    with connect() as conn:
        row = conn.execute('SELECT * FROM posts WHERE id=?',(post_id,)).fetchone()
    if not row:
        raise ValueError('Publicação não encontrada.')
    row = dict(row)
    if prepare_only and (finish or row['channel']!='Instagram' or data.get('confirmed_absent') is not True):
        raise ValueError('Este teste é somente para imagem do Instagram. Confira antes que o post não foi publicado.')
    expected = 'review' if prepare_only else 'processing' if finish else 'draft'
    if row['publish_status'] != expected or row['revision'] != revision:
        raise ValueError('O rascunho mudou, já está em envio ou já foi publicado. Atualize a página.')
    settings = meta.config(directory)
    stored = meta.read_private(directory/'meta-connection.json')
    token = stored.get('access_token')
    if not token or stored.get('app_id') != settings['app_id']:
        raise ValueError('Conecte novamente à Meta.')
    # Consulta atual, não apenas a lista antiga mostrada na tela.
    verified = meta.verify_accounts(directory)
    account = next((a for a in verified['accounts'] if a['id']==row['account_id'] and a['channel']==row['channel']),None)
    if not account or not account['publishing_scope_granted']:
        raise ValueError('A conta selecionada não tem acesso de publicação confirmado nesta consulta.')
    if not row['caption'].strip() or len(row['caption']) > 2200:
        raise ValueError('Revise a legenda antes de publicar.')
    image_url = ''
    if row['image_name']:
        width,height = jpeg_size(image_file(directory,row['image_name']).read_bytes())
        image_url = meta.callback_url().removesuffix(meta.CALLBACK)+'/media/'+row['image_name']
        if row['channel']=='Instagram' and not (320<=width<=1440 and .8<=width/height<=1.91):
            raise ValueError('Para Instagram, use JPEG com largura entre 320 e 1.440 px e proporção entre 4:5 e 1,91:1. Uma imagem 1080 × 1080 é uma boa opção.')
    if row['channel']=='Instagram' and not image_url:
        raise ValueError('Selecione uma imagem JPEG para publicar no Instagram.')
    # Obter token da página antes de iniciar uma operação que publique conteúdo.
    if row['channel']=='Facebook':
        proof=hmac.new(settings['app_secret'].encode(),token.encode(),hashlib.sha256).hexdigest()
        page=meta.graph_read(settings,row['account_id'],token,{'fields':'access_token','appsecret_proof':proof})
        token=page.get('access_token')
        if not isinstance(token,str) or not token:
            raise ValueError('A Meta não liberou o token da página. Confira as tarefas atribuídas e as permissões.')
    with connect() as conn:
        conn.execute('BEGIN IMMEDIATE')
        changed=conn.execute('UPDATE posts SET publish_status=? WHERE id=? AND revision=? AND publish_status=?',
                            ('sending',post_id,revision,expected))
        if changed.rowcount != 1:
            raise ValueError('Já existe um envio para este rascunho. Atualize a página.')
        if not finish:
            attempt=conn.execute('INSERT INTO publication_attempts(post_id,created_at,status,account_id,caption,image_name) VALUES(?,?,?,?,?,?)',
                (post_id,int(time.time()),'sending',row['account_id'],row['caption'],row['image_name']))
            conn.execute('UPDATE posts SET attempt_id=? WHERE id=?',(attempt.lastrowid,post_id))
    try:
        if row['channel']=='Facebook':
            edge='photos' if image_url else 'feed'
            payload={'url':image_url,'caption':row['caption'],'published':'true'} if image_url else {'message':row['caption']}
            result=graph_post(settings,row['account_id']+'/'+edge,token,payload)
            remote=str(result.get('post_id') or result['id'])
            set_status(connect,post_id,'published',remote_id=remote)
            return {'status':'published'}
        container=row['container_id']
        if not finish:
            if via_meta:
                image_url=stage_on_meta(connect,directory,settings,token,row)
            result=graph_post(settings,row['account_id']+'/media',token,{'image_url':image_url,'caption':row['caption']})
            container=str(result['id'])
            set_status(connect,post_id,'processing',container_id=container)
            return {'status':'processing'}
        proof=hmac.new(settings['app_secret'].encode(),token.encode(),hashlib.sha256).hexdigest()
        result=meta.graph_read(settings,container,token,{'fields':'status_code','appsecret_proof':proof})
        if result.get('status_code')=='IN_PROGRESS':
            set_status(connect,post_id,'processing',container_id=container)
            return {'status':'processing'}
        if result.get('status_code')!='FINISHED':
            raise Uncertain('O Instagram não confirmou que a imagem está pronta. Confira a rede antes de reenviar.')
        result=graph_post(settings,row['account_id']+'/media_publish',token,{'creation_id':container})
        set_status(connect,post_id,'published',remote_id=str(result['id']),container_id=container)
        return {'status':'published'}
    except (ValueError,OSError):
        import sys
        error=sys.exception()
        message=str(error) if isinstance(error,ValueError) else 'Não foi possível registrar o resultado. Confira a rede social antes de tentar novamente.'
        set_status(connect,post_id,'review',message,container_id=row['container_id'])
        raise ValueError(message) from None


def stage_on_meta(connect,directory,settings,token,row):
    """Hospeda a arte na própria Meta sem criar post no feed do Facebook."""
    proof=hmac.new(settings['app_secret'].encode(),token.encode(),hashlib.sha256).hexdigest()
    result=meta.graph_read(settings,'me/accounts',token,{'fields':'id,instagram_business_account{id},access_token','limit':50,'appsecret_proof':proof})
    pages=result.get('data',[])
    if not isinstance(pages,list):
        raise ValueError('A Meta não retornou as páginas vinculadas para receber o arquivo.')
    page=next((p for p in pages if isinstance(p,dict) and isinstance(p.get('instagram_business_account'),dict)
        and str(p['instagram_business_account'].get('id'))==row['account_id'] and str(p.get('id','')).isdecimal()),None)
    if not page:
        raise ValueError('Não foi encontrada uma página Facebook vinculada a esse Instagram entre os ativos concedidos.')
    page_token=page.get('access_token')
    if not isinstance(page_token,str) or not page_token:
        page_token=meta.graph_read(settings,str(page['id']),token,{'fields':'access_token','appsecret_proof':proof}).get('access_token')
    if not isinstance(page_token,str) or not page_token:
        raise ValueError('Não foi possível obter a autorização de envio de arquivo para a página vinculada.')
    with connect() as conn:
        previous=conn.execute('SELECT photo_id FROM publication_staged_media WHERE post_id=? AND image_name=?',(row['id'],row['image_name'])).fetchone()
    if previous:
        photo_id=previous[0]
    else:
        image=image_file(directory,row['image_name']).read_bytes()
        result=graph_post(settings,str(page['id'])+'/photos',page_token,{'published':'false'},file_bytes=image)
        photo_id=str(result['id'])
        with connect() as conn:
            conn.execute('INSERT INTO publication_staged_media VALUES(?,?,?)',(row['id'],row['image_name'],photo_id))
    page_proof=hmac.new(settings['app_secret'].encode(),page_token.encode(),hashlib.sha256).hexdigest()
    photo=meta.graph_read(settings,photo_id,page_token,{'fields':'images','appsecret_proof':page_proof})
    images=photo.get('images',[])
    for image in images if isinstance(images,list) else []:
        source=image.get('source') if isinstance(image,dict) else None
        if not isinstance(source,str):
            continue
        parsed=urllib.parse.urlsplit(source)
        host=(parsed.hostname or '').lower()
        if parsed.scheme=='https' and not parsed.username and not parsed.password and (host.endswith('.fbcdn.net') or host.endswith('.fbsbx.com') or host.endswith('.facebook.com')):
            return source
    raise ValueError('A foto não publicada foi recebida, mas a Meta não retornou um endereço de imagem compatível.')


def reset(conn, data):
    if isinstance(data.get('id'),bool) or not isinstance(data.get('id'),int):
        raise ValueError('Identificação inválida.')
    if data.get('confirmed_absent') is not True:
        raise ValueError('Confira na rede social e confirme que a publicação não foi enviada.')
    cursor=conn.execute("UPDATE posts SET publish_status='draft',publish_error='',container_id='',revision=revision+1 WHERE id=? AND publish_status='review'",(data.get('id'),))
    if cursor.rowcount!=1:
        raise ValueError('Este registro não está aguardando revisão.')


def diagnose(connect, directory, data):
    """Consulta somente leitura. Não cria contêiner, não publica nem desbloqueia."""
    post_id=data.get('id')
    if type(post_id) is not int:
        raise ValueError('Identificação inválida.')
    with connect() as conn:
        row=conn.execute('SELECT * FROM posts WHERE id=?',(post_id,)).fetchone()
    if not row:
        raise ValueError('Publicação não encontrada.')
    row=dict(row)
    messages=['O diagnóstico não enviou nem repetiu nenhuma publicação.']
    if row['publish_error']:
        messages.append('Último resultado registrado: '+row['publish_error'])
    if row['image_name']:
        width,height=jpeg_size(image_file(directory,row['image_name']).read_bytes())
        messages.append(f'JPEG encontrado no servidor: {width} × {height} px.')
    settings=meta.config(directory)
    stored=meta.read_private(directory/'meta-connection.json')
    token=stored.get('access_token')
    if not token or stored.get('app_id')!=settings['app_id']:
        raise ValueError('Conecte novamente à Meta para executar o diagnóstico.')
    proof=hmac.new(settings['app_secret'].encode(),token.encode(),hashlib.sha256).hexdigest()
    matches=[]
    try:
        if row['channel']=='Instagram':
            path=row['account_id']+'/media'
            fields='id,caption,timestamp'
        else:
            page=meta.graph_read(settings,row['account_id'],token,{'fields':'access_token','appsecret_proof':proof})
            token=page.get('access_token')
            if not isinstance(token,str) or not token:
                raise ValueError('Não foi possível consultar o token da página.')
            proof=hmac.new(settings['app_secret'].encode(),token.encode(),hashlib.sha256).hexdigest()
            path=row['account_id']+'/posts'
            fields='id,message,created_time'
        result=meta.graph_read(settings,path,token,{'fields':fields,'limit':10,'appsecret_proof':proof})
        values=result.get('data')
        if not isinstance(values,list):
            raise ValueError('A Meta não retornou uma lista de publicações para conferir.')
        for item in values:
            text=(item.get('caption') or item.get('message') or '') if isinstance(item,dict) else ''
            if isinstance(text,str) and isinstance(item,dict) and text.strip()==row['caption'].strip():
                identifier=str(item.get('id',''))
                if re.fullmatch(r'[0-9_]+',identifier):
                    matches.append(identifier)
        messages.append('A consulta das 10 publicações mais recentes foi aceita pela Meta.')
        messages.append('Há conteúdo com a mesma legenda na rede. Confira antes de qualquer novo envio.' if matches else 'Não foi encontrada essa legenda entre os 10 resultados. Isso não prova que o envio não aconteceu; confira também no aplicativo da rede social.')
    except ValueError as error:
        messages.append(str(error))
    return {'messages':messages,'matching_ids':matches,'image_url':'/media/'+row['image_name'] if row['image_name'] else None}
