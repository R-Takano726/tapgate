import contextlib
import io
import json
import os
import socket
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch
from watchgate.server import Server
from watchgate.store import Store,digest
from watchgate.codex_runner import run
from watchgate import claude_hook


class AdapterTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)
        self.store=Store(self.root/'queue.sqlite');self.token=self.store.credential('producer','Host')
        self.server=Server(('127.0.0.1',0),self.store)
        self.thread=threading.Thread(target=self.server.serve_forever,daemon=True);self.thread.start()
        (self.root/'producer.json').write_text(json.dumps({'url':'http://127.0.0.1:'+str(self.server.server_port),'token':self.token}))
        self.env=patch.dict(os.environ,{'TAPGATE_STATE':str(self.root),'TAPGATE_TASK':'Adapter synthetic task'});self.env.start()
    def tearDown(self):
        self.env.stop();self.server.shutdown();self.server.server_close();self.thread.join();self.store.db.close();self.tmp.cleanup()
    def answer(self,decision='approved'):
        def work():
            deadline=time.monotonic()+10
            while time.monotonic()<deadline:
                values=self.store.listing()
                if values:
                    item=values[0]
                    self.store.decide(item['id'],decision,'phone',1,item['payload_hash'])
                    return
                time.sleep(.02)
        thread=threading.Thread(target=work);thread.start();return thread
    def test_claude_real_broker_allow_output(self):
        answer=self.answer();out=io.StringIO()
        event={'hook_event_name':'PermissionRequest','tool_name':'Bash','tool_input':{'command':'npm test'},'session_id':'synthetic','cwd':'/tmp/test'}
        with patch('sys.stdin',io.StringIO(json.dumps(event))),contextlib.redirect_stdout(out):claude_hook.run()
        answer.join();data=json.loads(out.getvalue())
        self.assertEqual(data['hookSpecificOutput']['decision']['behavior'],'allow')
        self.assertTrue(self.store.listing()[0]['delivered'])
    def test_claude_real_broker_deny_output(self):
        answer=self.answer('denied');out=io.StringIO()
        event={'hook_event_name':'PermissionRequest','tool_name':'Write','tool_input':{'file_path':'a.txt'},'session_id':'synthetic','cwd':'/tmp/test'}
        with patch('sys.stdin',io.StringIO(json.dumps(event))),contextlib.redirect_stdout(out):claude_hook.run()
        answer.join();self.assertEqual(json.loads(out.getvalue())['hookSpecificOutput']['decision']['behavior'],'deny')
    def test_claude_failure_returns_to_original_prompt(self):
        out=io.StringIO()
        with patch('watchgate.claude_hook.Producer',side_effect=OSError()),patch('sys.stdin',io.StringIO('{"hook_event_name":"PermissionRequest"}')),contextlib.redirect_stdout(out),contextlib.redirect_stderr(io.StringIO()):claude_hook.run()
        self.assertEqual(out.getvalue(),'')
    def test_codex_transport_real_broker_roundtrip(self):
        fake=self.root/'synthetic-codex'
        fake.write_text('''#!/usr/bin/env python3
import sys,json
for line in sys.stdin:
 m=json.loads(line)
 if m.get('method')=='initialize':print(json.dumps({'id':m['id'],'result':{}}),flush=True)
 elif m.get('method')=='thread/start':print(json.dumps({'id':m['id'],'result':{'thread':{'id':'synthetic-thread'}}}),flush=True)
 elif m.get('method')=='turn/start':
  print(json.dumps({'id':m['id'],'result':{}}),flush=True)
  print(json.dumps({'id':101,'method':'item/commandExecution/requestApproval','params':{'threadId':'synthetic-thread','itemId':'item-1','turnId':'turn-1','command':'npm test','cwd':'/tmp/synthetic'}}),flush=True)
 elif m.get('id')==101:
  if m.get('result')!={'decision':'accept'}:sys.exit(2)
  print(json.dumps({'method':'item/agentMessage/delta','params':{'delta':'SYNTHETIC APPROVAL DELIVERED'}}),flush=True)
  print(json.dumps({'method':'turn/completed','params':{'turn':{'status':'completed'}}}),flush=True)
''')
        fake.chmod(0o700);answer=self.answer();output=io.StringIO()
        with contextlib.redirect_stdout(output),contextlib.redirect_stderr(io.StringIO()):result=run('Synthetic task','Synthetic prompt',executable=str(fake))
        answer.join();self.assertEqual(result,0);self.assertIn('SYNTHETIC APPROVAL DELIVERED',output.getvalue())
        self.assertEqual(self.store.listing()[0]['state'],'approved')
