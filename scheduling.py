"""Fila persistente. Execute com um runner externo; não inicia junto ao site."""
import secrets
import time
from datetime import datetime
from zoneinfo import ZoneInfo
import publishing

ZONE=ZoneInfo('America/Sao_Paulo')


def initialize(conn):
    conn.executescript('''
    CREATE TABLE IF NOT EXISTS post_schedule (
      post_id INTEGER PRIMARY KEY, revision INTEGER NOT NULL, due_at INTEGER NOT NULL,
      state TEXT NOT NULL, claim TEXT NOT NULL DEFAULT '', claimed_at INTEGER,
      error TEXT NOT NULL DEFAULT '');
    CREATE TABLE IF NOT EXISTS scheduler_runtime (
      id INTEGER PRIMARY KEY CHECK(id=1), last_tick INTEGER NOT NULL, mode TEXT NOT NULL);
    ''')


def runtime(conn):
    row=conn.execute('SELECT * FROM scheduler_runtime WHERE id=1').fetchone()
    active=bool(row and row['mode'] in ['loop','cron','http'] and time.time()-row['last_tick']<150)
    return {'active':active,'timezone':'America/Sao_Paulo','last_tick':row['last_tick'] if row else None}


def save(conn,directory,data):
    if data.get('confirmed') is not True:
        raise ValueError('Confirme o canal, a conta, o conteúdo e o horário do envio automático.')
    if not runtime(conn)['active']:
        raise ValueError('O executor de agendamentos não está ativo. Ative-o antes de agendar; deixar o site aberto não substitui esse processo.')
    if any(type(data.get(k)) is not int for k in ['id','revision']):
        raise ValueError('Identificação inválida.')
    try:
        when=datetime.fromisoformat(data.get('when',''))
        if when.tzinfo is not None:
            raise ValueError()
        due=int(when.replace(tzinfo=ZONE).timestamp())
    except (ValueError,TypeError):
        raise ValueError('Informe uma data e hora válidas no fuso de São Paulo.') from None
    if not time.time()+120<=due<=time.time()+90*86400:
        raise ValueError('Agende com pelo menos 2 minutos de antecedência e até 90 dias.')
    row=conn.execute('SELECT * FROM posts WHERE id=?',(data['id'],)).fetchone()
    if not row or row['publish_status']!='draft' or row['revision']!=data['revision']:
        raise ValueError('O rascunho mudou ou não está disponível. Atualize a página.')
    if not row['account_id'] or not row['caption'].strip():
        raise ValueError('Escolha a conta e revise a legenda antes de agendar.')
    if row['channel']=='Instagram' and not row['image_name']:
        raise ValueError('Instagram exige uma imagem JPEG.')
    if row['image_name']:
        width,height=publishing.jpeg_size(publishing.image_file(directory,row['image_name']).read_bytes())
        if row['channel']=='Instagram' and not (320<=width<=1440 and .8<=width/height<=1.91):
            raise ValueError('Use imagem compatível com Instagram, por exemplo 1080 × 1080 px.')
    updated=conn.execute("UPDATE posts SET publish_status='scheduled' WHERE id=? AND revision=? AND publish_status='draft'",(data['id'],data['revision']))
    if updated.rowcount!=1:
        raise ValueError('O rascunho mudou durante o agendamento.')
    conn.execute('INSERT OR REPLACE INTO post_schedule(post_id,revision,due_at,state) VALUES(?,?,?,?)',(data['id'],data['revision'],due,'queued'))
    return {'due_at':due}


def cancel(conn,data):
    if type(data.get('id')) is not int:
        raise ValueError('Identificação inválida.')
    conn.execute('BEGIN IMMEDIATE')
    result=conn.execute("UPDATE post_schedule SET state='cancelled' WHERE post_id=? AND state='queued'",(data['id'],))
    if result.rowcount!=1:
        raise ValueError('O envio já começou ou este agendamento não pode ser cancelado.')
    conn.execute("UPDATE posts SET publish_status='draft',revision=revision+1 WHERE id=? AND publish_status='scheduled'",(data['id'],))


def tick(connect,directory,mode='once'):
    now=int(time.time())
    with connect() as conn:
        conn.execute('BEGIN IMMEDIATE')
        conn.execute('INSERT OR REPLACE INTO scheduler_runtime VALUES(1,?,?)',(now,mode))
        # Não repetir uma operação cujo resultado se perdeu com o processo.
        stale=conn.execute("SELECT post_id FROM post_schedule WHERE state='running' AND claimed_at<?",(now-600,)).fetchall()
        for item in stale:
            conn.execute("UPDATE post_schedule SET state='failed',error='Executor interrompido. Confira a rede antes de reenviar.' WHERE post_id=?",(item[0],))
            conn.execute("UPDATE posts SET publish_status='review',publish_error='Executor interrompido. Confira a rede antes de reenviar.' WHERE id=? AND publish_status!='published'",(item[0],))
        row=conn.execute("SELECT s.*,p.channel FROM post_schedule s JOIN posts p ON p.id=s.post_id WHERE s.state IN ('queued','processing') AND s.due_at<=? ORDER BY s.due_at LIMIT 1",(now,)).fetchone()
        if not row:
            return {'status':'idle'}
        row=dict(row)
        if now-row['due_at']>1800:
            message='Horário vencido há mais de 30 minutos. Revise antes de reagendar.'
            conn.execute("UPDATE post_schedule SET state='failed',error=? WHERE post_id=?",(message,row['post_id']))
            conn.execute("UPDATE posts SET publish_status='review',publish_error=? WHERE id=? AND publish_status!='published'",(message,row['post_id']))
            return {'status':'expired'}
        claim=secrets.token_hex(16)
        conn.execute("UPDATE post_schedule SET state='running',claim=?,claimed_at=? WHERE post_id=?",(claim,now,row['post_id']))
    try:
        result=publishing.publish(connect,directory,{'id':row['post_id'],'revision':row['revision'],'confirmed':True},
            finish=row['state']=='processing',via_meta=row['channel']=='Instagram' and row['state']!='processing',scheduled=True)
        outcome='done' if result['status']=='published' else 'processing'
        error=''
    except Exception as exc:
        outcome='failed'
        error=str(exc) if isinstance(exc,ValueError) else 'Falha no executor. Confira a rede antes de reenviar.'
        with connect() as conn:
            conn.execute("UPDATE posts SET publish_status='review',publish_error=? WHERE id=? AND publish_status!='published'",(error,row['post_id']))
    with connect() as conn:
        conn.execute('UPDATE post_schedule SET state=?,error=? WHERE post_id=? AND claim=?',(outcome,error,row['post_id'],claim))
    return {'status':outcome}


def main():
    import argparse
    import app
    parser=argparse.ArgumentParser(description='Executor dos agendamentos da Arte no Altar')
    group=parser.add_mutually_exclusive_group()
    group.add_argument('--loop',action='store_true',help='Conferir a fila a cada 30 segundos')
    group.add_argument('--cron',action='store_true',help='Execução acionada por cron a cada minuto')
    args=parser.parse_args()
    app.initialize()
    mode='loop' if args.loop else 'cron' if args.cron else 'once'
    if mode!='once':
        import meta
        # O ambiente WSGI não é herdado automaticamente pelo processo da fila.
        meta.callback_url()
        meta.config(app.DB.parent)
    try:
        while True:
            print(tick(app.connect,app.DB.parent,mode),flush=True)
            if not args.loop:
                break
            time.sleep(30)
    finally:
        if args.loop:
            with app.connect() as conn:
                conn.execute("UPDATE scheduler_runtime SET mode='stopped' WHERE id=1")


if __name__=='__main__':
    main()
