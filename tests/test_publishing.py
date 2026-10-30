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

    def test_http_error_has_codes_without_secret_provider_text(self):
        import urllib.error
        response={'error':{'code':100,'error_subcode':2207052,'message':'Cannot fetch image from https://private.example?access_token=secret-value test-secret'}}
        error=urllib.error.HTTPError('https://graph.facebook.com',400,'Bad Request',{},io.BytesIO(json.dumps(response).encode()))
        with patch('urllib.request.build_opener') as opener:
            opener.return_value.open.side_effect=error
            with self.assertRaises(publishing.Uncertain) as caught:
                publishing.graph_post(meta.config(app.DB.parent),'999/media','test-token',{'caption':'Texto'})
        text=str(caught.exception)
        self.assertIn('código 100',text)
        self.assertIn('subcódigo 2207052',text)
        self.assertIn('imagem',text)
        self.assertNotIn('secret-value',text)
        self.assertNotIn('private.example',text)
        self.assertNotIn('app-secret',text)
        self.assertNotIn('test-secret',text)

    def test_preparation_test_creates_container_without_publishing(self):
        self.account['channel']='Instagram'
        name=publishing.upload(app.DB.parent,base64.b64encode(jpeg()).decode())['name']
        with app.connect() as c:
            c.execute("UPDATE posts SET channel='Instagram',publish_status='review',image_name=?",(name,))
        with patch('publishing.graph_post',return_value={'id':'1234'}) as send:
            data={'id':1,'revision':0,'confirmed':True,'confirmed_absent':True}
            result=publishing.publish(app.connect,app.DB.parent,data,prepare_only=True)
            self.assertEqual(result['status'],'processing')
            self.assertEqual(send.call_count,1)
            self.assertEqual(send.call_args.args[1],'999/media')
            self.assertNotIn('media_publish',str(send.call_args))
            self.assertEqual(self.row()['remote_id'],'')
            self.assertEqual(self.row()['container_id'],'1234')
            with self.assertRaises(ValueError):
                publishing.publish(app.connect,app.DB.parent,data,prepare_only=True)
            self.assertEqual(send.call_count,1)

    def test_preparation_test_requires_absence_confirmation(self):
        with patch('publishing.graph_post') as send:
            with self.assertRaises(ValueError):
                publishing.publish(app.connect,app.DB.parent,{'id':1,'revision':0,'confirmed':True},prepare_only=True)
            send.assert_not_called()

    def test_meta_file_preparation_only_uses_unpublished_linked_page_photo(self):
        self.account['channel']='Instagram'
        name=publishing.upload(app.DB.parent,base64.b64encode(jpeg()).decode())['name']
        with app.connect() as c:
            c.execute("UPDATE posts SET channel='Instagram',publish_status='review',image_name=?",(name,))
        reads=[{'data':[{'id':'777','access_token':'page-token','instagram_business_account':{'id':'999'}}]},
            {'images':[{'source':'https://scontent.example.fbcdn.net/art.jpg'}]}]
        with patch('meta.graph_read',side_effect=reads),patch('publishing.graph_post',side_effect=[{'id':'555'},{'id':'888'}]) as send:
            result=publishing.publish(app.connect,app.DB.parent,{'id':1,'revision':0,'confirmed':True,'confirmed_absent':True},prepare_only=True,via_meta=True)
            self.assertEqual(result['status'],'processing')
            self.assertEqual([c.args[1] for c in send.call_args_list],['777/photos','999/media'])
            self.assertEqual(send.call_args_list[0].args[3],{'published':'false'})
            self.assertEqual(send.call_args_list[0].kwargs['file_bytes'],jpeg())
            self.assertEqual(send.call_args_list[1].args[3]['image_url'],'https://scontent.example.fbcdn.net/art.jpg')
            self.assertEqual(self.row()['remote_id'],'')
        with app.connect() as c:
            self.assertEqual(c.execute('SELECT photo_id FROM publication_staged_media').fetchone()[0],'555')

    def test_meta_file_preparation_refuses_unrelated_page(self):
        row={'id':1,'account_id':'999','image_name':'irrelevant'}
        with patch('meta.graph_read',return_value={'data':[{'id':'777','instagram_business_account':{'id':'different'}}]}),patch('publishing.graph_post') as send:
            with self.assertRaises(ValueError):
                publishing.stage_on_meta(app.connect,app.DB.parent,meta.config(app.DB.parent),'test-token',row)
            send.assert_not_called()

    def test_existing_unpublished_photo_is_reused_without_reupload(self):
        with app.connect() as c:
            c.execute("INSERT INTO publication_staged_media VALUES(1,'image.jpg','555')")
        reads=[{'data':[{'id':'777','access_token':'page-token','instagram_business_account':{'id':'999'}}]},
            {'images':[{'source':'https://scontent.example.fbcdn.net/fresh.jpg'}]}]
        with patch('meta.graph_read',side_effect=reads),patch('publishing.graph_post') as send:
            url=publishing.stage_on_meta(app.connect,app.DB.parent,meta.config(app.DB.parent),'test-token',{'id':1,'account_id':'999','image_name':'image.jpg'})
            self.assertEqual(url,'https://scontent.example.fbcdn.net/fresh.jpg')
            send.assert_not_called()

    def test_multipart_upload_keeps_photo_unpublished(self):
        with patch('urllib.request.build_opener') as factory:
            factory.return_value.open.return_value=io.BytesIO(b'{"id":"555"}')
            publishing.graph_post(meta.config(app.DB.parent),'777/photos','page-token',{'published':'false'},file_bytes=jpeg())
            request=factory.return_value.open.call_args.args[0]
            self.assertTrue(request.get_header('Content-type').startswith('multipart/form-data; boundary='))
            self.assertIn(b'name="published"\r\n\r\nfalse',request.data)
            self.assertIn(b'name="source"; filename="arte.jpg"',request.data)
            self.assertIn(jpeg(),request.data)

    def test_meta_user_message_is_preserved_with_credentials_removed(self):
        import urllib.error
        response={'error':{'code':9004,'error_subcode':2207052,
            'error_user_title':'Media download failed',
            'error_user_msg':'The image could not be fetched from this URI: https://private.example/file.jpg',
            'message':'token test-token secret test-secret authorization=abc123'}}
        error=urllib.error.HTTPError('https://graph.facebook.com',400,'Bad Request',{},io.BytesIO(json.dumps(response).encode()))
        text=meta.error_summary(error,['test-token','test-secret'])
        self.assertIn('Media download failed',text)
        self.assertIn('The image could not be fetched',text)
        for private in ['test-token','test-secret','private.example','abc123']:
            self.assertNotIn(private,text)

    def test_diagnosis_does_not_publish_reset_or_claim_absence(self):
        with app.connect() as c:c.execute("UPDATE posts SET channel='Instagram',publish_status='review',publish_error='Erro anterior'")
        with patch('publishing.graph_post') as send,patch('meta.graph_read',return_value={'data':[{'id':'999111','caption':'Legenda revisada'}]}) as read:
            result=publishing.diagnose(app.connect,app.DB.parent,{'id':1})
            send.assert_not_called()
            self.assertEqual(read.call_args.args[1],'999/media')
            self.assertEqual(result['matching_ids'],['999111'])
            self.assertEqual(self.row()['publish_status'],'review')
        with patch('meta.graph_read',return_value={'data':[]}):
            result=publishing.diagnose(app.connect,app.DB.parent,{'id':1})
            self.assertTrue(any('não prova' in message for message in result['messages']))
