import base64
import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import app
import meta
import publishing
import wsgi


def jpeg(width=1080, height=1080):
    # Cabeçalho mínimo para testar a leitura de dimensões, não uma foto real.
    return b'\xff\xd8\xff\xc0\x00\x0b\x08'+height.to_bytes(2,'big')+width.to_bytes(2,'big')+b'\x01\x01\x11\x00\xff\xd9'


class PublishingTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.old_db=app.DB
        app.DB=Path(self.tmp.name)/'test.db'
        self.env=patch.dict(os.environ,{'ARTENOALTAR_ORIGIN':'https://gestao.example',
            'ARTENOALTAR_META_APP_ID':'','ARTENOALTAR_META_APP_SECRET':'','ARTENOALTAR_META_CONFIG_ID':''})
        self.env.start()
        app.initialize()
        meta.write_private(app.DB.parent/'meta-config.json',{'app_id':'123','config_id':'456','app_secret':'test-secret'})
        meta.write_private(app.DB.parent/'meta-connection.json',{'app_id':'123','access_token':'test-token'})
        self.account={'id':'999','channel':'Facebook','name':'Página Teste','publishing_scope_granted':True}
        self.verify=patch('meta.verify_accounts',side_effect=lambda directory:{'accounts':[self.account]})
        self.verify.start()
        with app.connect() as c:
            c.execute("INSERT INTO posts(product,channel,caption,source,account_id) VALUES('Envelopes','Facebook','Legenda revisada','Modelo local','999')")

    def tearDown(self):
        self.verify.stop();self.env.stop();app.DB=self.old_db;self.tmp.cleanup()

    def row(self):
        with app.connect() as c:
            return dict(c.execute('SELECT * FROM posts WHERE id=1').fetchone())

    def send(self, finish=False):
        return publishing.publish(app.connect,app.DB.parent,{'id':1,'revision':0,'confirmed':True},finish)

    def test_facebook_text_confirmation_and_duplicate_block(self):
        with patch('publishing.graph_post',return_value={'id':'999_111'}) as send,patch('meta.graph_read',return_value={'access_token':'page-token'}):
            with self.assertRaises(ValueError):
                publishing.publish(app.connect,app.DB.parent,{'id':1,'revision':0,'confirmed':False})
            send.assert_not_called()
            self.assertEqual(self.send()['status'],'published')
            self.assertEqual(send.call_args.args[1:3],('999/feed','page-token'))
            self.assertEqual(send.call_args.args[3],{'message':'Legenda revisada'})
            with self.assertRaises(ValueError):
                self.send()
            self.assertEqual(send.call_count,1)
        self.assertEqual(self.row()['remote_id'],'999_111')
        with app.connect() as c:
            self.assertEqual(c.execute('SELECT status FROM publication_attempts').fetchone()[0],'published')

    def test_instagram_two_stage_preparation_and_finish(self):
        self.account['channel']='Instagram'
        name=publishing.upload(app.DB.parent,base64.b64encode(jpeg()).decode())['name']
        with app.connect() as c:
            c.execute("UPDATE posts SET channel='Instagram',image_name=?",(name,))
        with patch('publishing.graph_post',side_effect=[{'id':'1234'},{'id':'5678'}]) as send,patch('meta.graph_read',return_value={'status_code':'FINISHED'}):
            self.assertEqual(self.send()['status'],'processing')
            self.assertEqual(self.row()['container_id'],'1234')
            with self.assertRaises(ValueError):
                self.send()
            self.assertEqual(self.send(finish=True)['status'],'published')
            self.assertEqual([call.args[1] for call in send.call_args_list],['999/media','999/media_publish'])
            self.assertEqual(send.call_args.args[3],{'creation_id':'1234'})

    def test_unknown_result_blocks_retries_until_explicit_reconciliation(self):
        with patch('meta.graph_read',return_value={'access_token':'page-token'}),patch('publishing.graph_post',side_effect=publishing.Uncertain('Confira a rede social.')) as send:
            with self.assertRaises(ValueError):self.send()
            self.assertEqual(self.row()['publish_status'],'review')
            with self.assertRaises(ValueError):self.send()
            self.assertEqual(send.call_count,1)
        with app.connect() as c:
            with self.assertRaises(ValueError):publishing.reset(c,{'id':1})
            publishing.reset(c,{'id':1,'confirmed_absent':True})
        self.assertEqual(self.row()['publish_status'],'draft')
        self.assertEqual(self.row()['revision'],1)

    def test_permission_and_revision_changes_do_not_publish(self):
        with patch('publishing.graph_post') as send:
            self.account['publishing_scope_granted']=False
            with self.assertRaises(ValueError):self.send()
            self.assertEqual(self.row()['publish_status'],'draft')
            self.account['publishing_scope_granted']=True
            with app.connect() as c:
                publishing.update(c,app.DB.parent,{'id':1,'revision':0,'caption':'Nova legenda','account_id':'999','image_name':''})
            with self.assertRaises(ValueError):self.send()
            send.assert_not_called()

    def test_image_validation_and_instagram_requirements(self):
        with self.assertRaises(ValueError):publishing.upload(app.DB.parent,base64.b64encode(b'<svg></svg>').decode())
        with self.assertRaises(ValueError):publishing.image_file(app.DB.parent,'../test.db')
        self.account['channel']='Instagram'
        with app.connect() as c:c.execute("UPDATE posts SET channel='Instagram'")
        with patch('publishing.graph_post') as send:
            with self.assertRaises(ValueError):self.send()
            image=publishing.upload(app.DB.parent,base64.b64encode(jpeg(200,200)).decode())
            with app.connect() as c:c.execute('UPDATE posts SET image_name=?',(image['name'],))
            with self.assertRaises(ValueError):self.send()
            send.assert_not_called()

    def test_migration_preserves_old_posts_and_is_repeatable(self):
        app.initialize();app.initialize()
        self.assertEqual(self.row()['caption'],'Legenda revisada')
        self.assertEqual(self.row()['publish_status'],'draft')

    def test_transport_uses_post_and_no_redirects(self):
        settings=meta.config(app.DB.parent)
        with patch('urllib.request.build_opener') as factory:
            factory.return_value.open.return_value=io.BytesIO(b'{"id":"999_111"}')
            publishing.graph_post(settings,'999/feed','page-token',{'message':'Texto aprovado'})
            request=factory.return_value.open.call_args.args[0]
            self.assertEqual(request.get_method(),'POST')
            self.assertNotIn('page-token',request.full_url)
            self.assertIn(b'appsecret_proof=',request.data)

    def test_media_public_but_upload_and_publish_require_session(self):
        image=publishing.upload(app.DB.parent,base64.b64encode(jpeg()).decode())
        def call(path,method='GET'):
            body=b'{}';result={}
            def start(status,headers):result['code']=int(status.split()[0]);result['headers']=dict(headers)
            payload=b''.join(wsgi.application({'PATH_INFO':path,'REQUEST_METHOD':method,'HTTP_HOST':'gestao.example','HTTP_ORIGIN':'https://gestao.example','CONTENT_LENGTH':'2','wsgi.input':io.BytesIO(body)},start))
            return result,payload
        result,payload=call(image['url'])
        self.assertEqual(result['code'],200)
        self.assertEqual(result['headers']['Content-Type'],'image/jpeg')
        self.assertEqual(payload,jpeg())
        self.assertEqual(call('/api/media','POST')[0]['code'],401)
        self.assertEqual(call('/api/posts/publish','POST')[0]['code'],401)
