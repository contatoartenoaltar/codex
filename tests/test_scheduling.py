import tempfile
import time
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch
import app
import meta
import scheduling
import publishing


class SchedulingTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.old_db=app.DB
        app.DB=Path(self.tmp.name)/'test.db'
        app.initialize()
        with app.connect() as c:
            c.execute("INSERT INTO posts(product,channel,caption,source,account_id) VALUES('Envelopes','Facebook','Legenda aprovada','Modelo local','999')")
            c.execute("INSERT INTO scheduler_runtime VALUES(1,?,'loop')",(int(time.time()),))
        self.when=datetime.fromtimestamp(time.time()+600,scheduling.ZONE).replace(tzinfo=None,second=0,microsecond=0)
        self.data={'id':1,'revision':0,'when':self.when.isoformat(timespec='minutes'),'confirmed':True}

    def tearDown(self):
        app.DB=self.old_db
        self.tmp.cleanup()

    def save(self):
        with app.connect() as c:return scheduling.save(c,app.DB.parent,self.data)

    def row(self):
        with app.connect() as c:return dict(c.execute('SELECT * FROM posts WHERE id=1').fetchone())

    def test_timezone_cancellation_and_revision(self):
        result=self.save()
        self.assertEqual(result['due_at'],int(self.when.replace(tzinfo=scheduling.ZONE).timestamp()))
        self.assertEqual(self.row()['publish_status'],'scheduled')
        with app.connect() as c:scheduling.cancel(c,{'id':1})
        self.assertEqual(self.row()['publish_status'],'draft')
        self.assertEqual(self.row()['revision'],1)
        with patch('publishing.publish') as send,patch('scheduling.time.time',return_value=result['due_at']):
            self.assertEqual(scheduling.tick(app.connect,app.DB.parent)['status'],'idle')
            send.assert_not_called()

    def test_no_executor_or_confirmation_or_past_date(self):
        with app.connect() as c:
            c.execute("UPDATE scheduler_runtime SET mode='stopped'")
        with self.assertRaises(ValueError):self.save()
        with app.connect() as c:c.execute("UPDATE scheduler_runtime SET mode='loop'")
        self.data['confirmed']=False
        with self.assertRaises(ValueError):self.save()
        self.data['confirmed']=True;self.data['when']='2020-01-01T00:00'
        with self.assertRaises(ValueError):self.save()

    def test_not_early_and_exactly_once_after_due(self):
        due=self.save()['due_at']
        with patch('publishing.publish',return_value={'status':'published'}) as send:
            with patch('scheduling.time.time',return_value=due-1):
                self.assertEqual(scheduling.tick(app.connect,app.DB.parent)['status'],'idle')
            send.assert_not_called()
            with patch('scheduling.time.time',return_value=due):
                self.assertEqual(scheduling.tick(app.connect,app.DB.parent)['status'],'done')
                self.assertEqual(scheduling.tick(app.connect,app.DB.parent)['status'],'idle')
            self.assertEqual(send.call_count,1)

    def test_expired_and_ambiguous_operations_never_repeat(self):
        due=self.save()['due_at']
        with patch('scheduling.time.time',return_value=due+1801),patch('publishing.publish') as send:
            self.assertEqual(scheduling.tick(app.connect,app.DB.parent)['status'],'expired')
            send.assert_not_called()
        self.assertEqual(self.row()['publish_status'],'review')

    def test_failed_operation_stops_automatic_retries(self):
        due=self.save()['due_at']
        with patch('scheduling.time.time',return_value=due),patch('publishing.publish',side_effect=publishing.Uncertain('Resultado desconhecido')) as send:
            self.assertEqual(scheduling.tick(app.connect,app.DB.parent)['status'],'failed')
            self.assertEqual(scheduling.tick(app.connect,app.DB.parent)['status'],'idle')
            self.assertEqual(send.call_count,1)
        self.assertEqual(self.row()['publish_error'],'Resultado desconhecido')

    def test_real_publish_engine_with_fake_meta(self):
        meta.write_private(app.DB.parent/'meta-config.json',{'app_id':'123','config_id':'456','app_secret':'test-secret'})
        meta.write_private(app.DB.parent/'meta-connection.json',{'app_id':'123','access_token':'test-token'})
        due=self.save()['due_at']
        with patch('scheduling.time.time',return_value=due),patch('meta.verify_accounts',return_value={'accounts':[{'id':'999','channel':'Facebook','publishing_scope_granted':True}]}),patch('meta.graph_read',return_value={'access_token':'page-token'}),patch('publishing.graph_post',return_value={'id':'999_123'}) as send:
            self.assertEqual(scheduling.tick(app.connect,app.DB.parent)['status'],'done')
            self.assertEqual(scheduling.tick(app.connect,app.DB.parent)['status'],'idle')
            self.assertEqual(send.call_count,1)
        self.assertEqual(self.row()['publish_status'],'published')

    def test_running_job_cannot_be_cancelled_or_reclaimed(self):
        due=self.save()['due_at']
        with app.connect() as c:
            c.execute("UPDATE post_schedule SET state='running',claimed_at=?",(due,))
        with app.connect() as c:
            with self.assertRaises(ValueError):scheduling.cancel(c,{'id':1})
        with patch('scheduling.time.time',return_value=due+601),patch('publishing.publish') as send:
            scheduling.tick(app.connect,app.DB.parent)
            send.assert_not_called()
        self.assertEqual(self.row()['publish_status'],'review')

    def test_instagram_runner_uses_meta_file_path_then_finishes(self):
        import base64
        from test_publishing import jpeg
        image=publishing.upload(app.DB.parent,base64.b64encode(jpeg()).decode())
        with app.connect() as c:c.execute("UPDATE posts SET channel='Instagram',image_name=?",(image['name'],))
        meta.write_private(app.DB.parent/'meta-config.json',{'app_id':'123','config_id':'456','app_secret':'test-secret'})
        meta.write_private(app.DB.parent/'meta-connection.json',{'app_id':'123','access_token':'test-token'})
        due=self.save()['due_at']
        reads=[{'data':[{'id':'777','access_token':'page-token','instagram_business_account':{'id':'999'}}]},
            {'images':[{'source':'https://scontent.example.fbcdn.net/art.jpg'}]}, {'status_code':'FINISHED'}]
        with patch('scheduling.time.time',return_value=due),patch('meta.callback_url',return_value='https://gestao.example/auth/meta/callback'),patch('meta.verify_accounts',return_value={'accounts':[{'id':'999','channel':'Instagram','publishing_scope_granted':True}]}),patch('meta.graph_read',side_effect=reads),patch('publishing.graph_post',side_effect=[{'id':'111'},{'id':'222'},{'id':'333'}]) as send:
            self.assertEqual(scheduling.tick(app.connect,app.DB.parent)['status'],'processing')
            self.assertEqual(scheduling.tick(app.connect,app.DB.parent)['status'],'done')
            self.assertEqual(scheduling.tick(app.connect,app.DB.parent)['status'],'idle')
            self.assertEqual([c.args[1] for c in send.call_args_list],['777/photos','999/media','999/media_publish'])
            self.assertEqual(send.call_args_list[0].args[3]['published'],'false')
        self.assertEqual(self.row()['remote_id'],'333')
