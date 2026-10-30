import hashlib
import io
import json
import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit
import app
import auth
import meta
import wsgi


class MetaOAuthTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.old_db = app.DB
        app.DB = Path(self.tmp.name)/'db.sqlite'
        self.env = patch.dict(os.environ,{'ARTENOALTAR_ORIGIN':'https://gestao.example',
            'ARTENOALTAR_META_APP_ID':'','ARTENOALTAR_META_APP_SECRET':'','ARTENOALTAR_META_CONFIG_ID':''})
        self.env.start()
        app.initialize()
        meta.write_private(app.DB.parent/'meta-config.json',{'app_id':'123456','config_id':'654321','app_secret':'segredo-exclusivo-de-teste','version':meta.VERSION})
        with app.connect() as c:
            c.execute('INSERT INTO sessions VALUES(?,?)',(meta.digest('session-test'),int(time.time())+3600))
        self.session = 'arte_session=session-test'

    def tearDown(self):
        app.DB = self.old_db
        self.env.stop()
        self.tmp.cleanup()

    def request(self, path, method='GET', data=None, cookie='', origin='https://gestao.example'):
        parsed = urlsplit(path)
        body = json.dumps(data or {}).encode()
        environ = {'PATH_INFO':parsed.path,'QUERY_STRING':parsed.query,'REQUEST_METHOD':method,'HTTP_HOST':'gestao.example',
            'HTTP_ORIGIN':origin,'HTTP_COOKIE':cookie,'CONTENT_LENGTH':str(len(body)),'wsgi.input':io.BytesIO(body)}
        result = {}
        def start(status,headers):
            result['status']=int(status.split()[0]); result['headers']=dict(headers)
        result['body']=b''.join(wsgi.application(environ,start))
        return result

    def begin(self):
        result=self.request('/api/meta/start','POST',{},self.session)
        self.assertEqual(result['status'],200)
        query=parse_qs(urlsplit(json.loads(result['body'])['url']).query)
        self.assertEqual(query['redirect_uri'],['https://gestao.example/auth/meta/callback'])
        self.assertEqual(query['config_id'],['654321'])
        self.assertNotIn('segredo',json.loads(result['body'])['url'])
        cookie=result['headers']['Set-Cookie']
        self.assertIn('SameSite=Lax',cookie)
        self.assertIn('Secure',cookie)
        self.assertIn('HttpOnly',cookie)
        return query['state'][0],cookie.split(';')[0]

    def test_start_requires_login_origin_and_keeps_secret_off_browser(self):
        self.assertEqual(self.request('/api/meta/start','POST',{})['status'],401)
        self.assertEqual(self.request('/api/meta/start','POST',{},self.session,'https://outside.example')['status'],403)
        self.begin()
        result=self.request('/api/state',cookie=self.session)
        state=json.loads(result['body'])
        self.assertTrue(state['meta']['configured'])
        self.assertFalse(state['meta']['authorized'])
        self.assertNotIn('segredo-exclusivo',result['body'].decode())

    def test_callback_works_without_strict_session_cookie_and_blocks_replay(self):
        state,cookie=self.begin()
        callback=f'/auth/meta/callback?state={state}&code=one-use-code'
        # Um navegador diferente não pode consumir o state legítimo.
        with patch('meta.exchange') as exchange:
            self.assertEqual(self.request(callback,cookie='arte_meta=wrong')['status'],400)
            exchange.assert_not_called()
            result=self.request(callback,cookie=cookie)
            self.assertEqual(result['status'],200)
            exchange.assert_called_once_with(app.DB.parent,'one-use-code')
            self.assertNotIn(b'one-use-code',result['body'])
            self.assertIn(b'Nenhum conte',result['body'])
            self.assertEqual(self.request(callback,cookie=cookie)['status'],400)
            self.assertEqual(exchange.call_count,1)

    def test_expired_or_logged_out_session_is_rejected(self):
        state,cookie=self.begin()
        with app.connect() as c:
            c.execute('DELETE FROM sessions')
        with patch('meta.exchange') as exchange:
            self.assertEqual(self.request(f'/auth/meta/callback?state={state}&code=code',cookie=cookie)['status'],400)
            exchange.assert_not_called()

    def test_denial_does_not_exchange_or_render_provider_error(self):
        state,cookie=self.begin()
        with patch('meta.exchange') as exchange:
            response=self.request(f'/auth/meta/callback?state={state}&error=access_denied&error_description=private-data',cookie=cookie)
            self.assertEqual(response['status'],400)
            exchange.assert_not_called()
            self.assertNotIn(b'private-data',response['body'])

    def test_exchange_private_file_status_and_disconnect(self):
        response=io.BytesIO(json.dumps({'access_token':'token-exclusivo-teste','expires_in':3600}).encode())
        with patch('urllib.request.build_opener') as factory:
            factory.return_value.open.return_value=response
            meta.exchange(app.DB.parent,'single-code')
            request=factory.return_value.open.call_args.args[0]
            self.assertEqual(request.get_method(),'POST')
            self.assertNotIn('segredo',request.full_url)
            self.assertIn(b'client_secret=',request.data)
        path=app.DB.parent/'meta-connection.json'
        self.assertEqual(path.stat().st_mode & 0o777,0o600)
        status=meta.status(app.DB.parent)
        self.assertTrue(status['authorized'])
        self.assertFalse(status['accounts_verified'])
        result=self.request('/api/state',cookie=self.session)
        self.assertNotIn(b'token-exclusivo-teste',result['body'])
        self.assertEqual(self.request('/api/meta/disconnect','POST',{},self.session)['status'],200)
        self.assertFalse(path.exists())

    def test_missing_config_expired_state_and_public_callback(self):
        self.assertEqual(self.request('/auth/meta/callback')['status'],200)
        state,cookie=self.begin()
        with app.connect() as c:
            c.execute('UPDATE meta_oauth_states SET expires=0')
        with patch('meta.exchange') as exchange:
            self.assertEqual(self.request(f'/auth/meta/callback?state={state}&code=x',cookie=cookie)['status'],400)
            exchange.assert_not_called()
        (app.DB.parent/'meta-config.json').unlink()
        self.assertEqual(self.request('/api/meta/start','POST',{},self.session)['status'],400)
        self.assertFalse(meta.status(app.DB.parent)['configured'])

    def test_network_failure_preserves_previous_authorization(self):
        import urllib.error
        path=app.DB.parent/'meta-connection.json'
        meta.write_private(path,{'access_token':'old-token'})
        with patch('urllib.request.build_opener') as factory:
            factory.return_value.open.side_effect=urllib.error.URLError('secret-provider-detail')
            with self.assertRaises(ValueError) as error:
                meta.exchange(app.DB.parent,'code')
            self.assertNotIn('secret-provider-detail',str(error.exception))
        self.assertEqual(meta.read_private(path)['access_token'],'old-token')

    def authorized_token(self):
        meta.write_private(app.DB.parent/'meta-connection.json',{'access_token':'private-test-token','app_id':'123456'})

    def test_verifies_instagram_targets_without_assuming_facebook(self):
        self.authorized_token()
        def read(settings,path,token,params):
            if path=='debug_token':
                return {'data':{'is_valid':True,'app_id':'123456','scopes':['instagram_basic','instagram_content_publish'],
                    'granular_scopes':[{'scope':'instagram_basic','target_ids':['123999']} ]}}
            self.assertEqual(path,'123999')
            self.assertEqual(token,'private-test-token')
            self.assertIn('appsecret_proof',params)
            return {'id':'123999','username':'arte.no.altar'}
        with patch('meta.graph_read',side_effect=read):
            self.assertEqual(self.request('/api/meta/verify','POST',{},self.session)['status'],200)
        result=json.loads(self.request('/api/state',cookie=self.session)['body'])['meta']
        self.assertTrue(result['accounts_verified'])
        self.assertEqual(len(result['accounts']),1)
        self.assertEqual(result['accounts'][0]['channel'],'Instagram')
        self.assertTrue(result['accounts'][0]['publishing_scope_granted'])
        self.assertTrue(any('Facebook' in n for n in result['verification_notes']))
        self.assertNotIn('private-test-token',json.dumps(result))

    def test_pages_discovery_partial_permissions_and_no_publication(self):
        self.authorized_token()
        with patch('meta.graph_read') as read:
            read.side_effect=[{'data':{'is_valid':True,'app_id':'123456','scopes':['pages_show_list','pages_manage_posts']}},
                {'data':[{'id':'999','name':'Arte no Altar','instagram_business_account':{'id':'123999'}}]},
                {'id':'123999','username':'arte.no.altar'}]
            meta.verify_accounts(app.DB.parent)
            self.assertEqual([call.args[1] for call in read.call_args_list],['debug_token','me/accounts','123999'])
        status=meta.status(app.DB.parent)
        self.assertEqual(len(status['accounts']),2)
        self.assertTrue(status['accounts'][0]['publishing_scope_granted'])
        self.assertFalse(status['accounts'][1]['publishing_scope_granted'])

    def test_invalid_token_clears_old_verification_and_protects_endpoint(self):
        self.authorized_token()
        meta.write_private(app.DB.parent/'meta-verification.json',{'token_hash':meta.digest('private-test-token'),'accounts':[{'id':'1'}]})
        self.assertEqual(self.request('/api/meta/verify','POST',{})['status'],401)
        self.assertEqual(self.request('/api/meta/verify','POST',{},self.session,'https://outside.example')['status'],403)
        with patch('meta.graph_read',return_value={'data':{'is_valid':False,'app_id':'123456'}}):
            self.assertEqual(self.request('/api/meta/verify','POST',{},self.session)['status'],400)
        self.assertFalse(meta.status(app.DB.parent)['accounts_verified'])

    def test_valid_token_without_assets_is_not_marked_verified(self):
        self.authorized_token()
        with patch('meta.graph_read',return_value={'data':{'is_valid':True,'app_id':'123456','scopes':[]}}):
            meta.verify_accounts(app.DB.parent)
        self.assertFalse(meta.status(app.DB.parent)['accounts_verified'])
        self.assertTrue(meta.status(app.DB.parent)['verification_notes'])
