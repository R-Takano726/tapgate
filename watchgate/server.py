import json
import os
import secrets
import socket
import threading
import time
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit
from .store import Problem, Store, digest

WEB = Path(__file__).parent / 'web'


class Server(ThreadingHTTPServer):
    daemon_threads = True
    def __init__(self, address, store, *, demo=False, hostnames=(), secure=False):
        self.store, self.demo, self.secure = store, demo, secure
        self.hosts = {'localhost', '127.0.0.1', *hostnames}
        self.origins = {'https://'+host for host in hostnames}
        self.slots = threading.BoundedSemaphore(32)
        super().__init__(address, Handler)
    def process_request(self, request, address):
        if not self.slots.acquire(False):
            request.close()
            return
        super().process_request(request, address)
    def process_request_thread(self, request, address):
        try:
            super().process_request_thread(request, address)
        finally:
            self.slots.release()


class Handler(BaseHTTPRequestHandler):
    server_version = 'TapGate'
    def setup(self):
        super().setup()
        self.connection.settimeout(10)
    def log_message(self, *_):
        pass  # Do not log raw paths, commands, credentials or notification data.
    def reply(self, status, data, content='application/json; charset=utf-8', cookie=None):
        raw = data if isinstance(data, bytes) else json.dumps(data, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header('Content-Type',content)
        self.send_header('Content-Length',str(len(raw)))
        self.send_header('Cache-Control','no-store')
        self.send_header('X-Content-Type-Options','nosniff')
        self.send_header('Referrer-Policy','no-referrer')
        self.send_header('Content-Security-Policy',"default-src 'self'; style-src 'self'; script-src 'self'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'")
        if cookie:
            self.send_header('Set-Cookie',cookie)
        self.end_headers()
        self.wfile.write(raw)
    def body(self):
        if self.headers.get('Transfer-Encoding'):
            raise Problem(400,'Chunked requests not supported')
        try:
            length = int(self.headers.get('Content-Length','0'))
            if not 0 < length <= 65536:
                raise ValueError()
            if self.headers.get_content_type() != 'application/json':
                raise ValueError()
            value = json.loads(self.rfile.read(length))
            if not isinstance(value,dict):
                raise ValueError()
            return value
        except (ValueError, json.JSONDecodeError):
            raise Problem(400,'Invalid JSON body')
    def client(self, role=None):
        token = self.headers.get('Authorization','')
        if token.startswith('Bearer '):
            token = token[7:]
        else:
            cookies = SimpleCookie(self.headers.get('Cookie',''))
            key = '__Host-tapgate' if self.server.secure else 'tapgate'
            token = cookies[key].value if key in cookies else ''
            if self.command=='POST' and self.headers.get('X-TapGate') != '1':
                raise Problem(403,'CSRF check failed')
        return self.server.store.auth(token,role)
    def route(self):
        raw_host = self.headers.get('Host','')
        host = urlsplit('//'+raw_host).hostname
        if host not in self.server.hosts or '@' in raw_host:
            raise Problem(403,'Invalid Host')
        origin = self.headers.get('Origin')
        if origin and origin not in {'http://'+raw_host,'https://'+raw_host,*self.server.origins}:
            raise Problem(403,'Foreign Origin')
        path = urlsplit(self.path).path
        method = self.command
        store = self.server.store
        if method=='GET' and path in ('/','/app.js','/style.css','/copy.json'):
            name = 'index.html' if path=='/' else path[1:]
            content = {'html':'text/html','js':'text/javascript','css':'text/css','json':'application/json'}[name.split('.')[-1]]
            return self.reply(200,(WEB/name).read_bytes(),content+'; charset=utf-8')
        if method=='GET' and path=='/health':
            return self.reply(200,{'ok':True,'demo':self.server.demo})
        if method=='POST' and path=='/api/pair':
            if self.headers.get('X-TapGate')!='1':
                raise Problem(403,'CSRF check failed')
            body = self.body()
            token = store.pair(body.get('code',''),str(body.get('name','Device')))
            key = '__Host-tapgate' if self.server.secure else 'tapgate'
            cookie = f'{key}={token}; HttpOnly; SameSite=Strict; Path=/' + ('; Secure' if self.server.secure else '')
            # Browsers keep the token only in an HttpOnly cookie.
            result = {'ok':True}
            if body.get('native') is True:
                result['token'] = token
                result['role'] = store.auth(token)['role']
            return self.reply(200,result,cookie=cookie)
        if method=='GET' and path=='/api/inbox':
            self.client('consumer')
            with store.lock:
                pushes = [dict(x) for x in store.db.execute('SELECT state,count(*) AS count FROM pushes GROUP BY state')]
            return self.reply(200,{'requests':store.listing(),'demo':self.server.demo,'push':pushes})
        if method=='POST' and path=='/api/watch-token':
            client = self.client('consumer')
            if client['role']!='consumer':
                raise Problem(403,'Only iPhone can provision a Watch')
            return self.reply(200,{'token':store.credential('watch','Apple Watch',client['token'])})
        if method=='POST' and path=='/api/logout':
            client = self.client('consumer')
            store.revoke(client['token'])
            return self.reply(200,{'ok':True})
        if method=='POST' and path=='/api/device':
            client = self.client('consumer')
            store.register_device(client['token'],self.body().get('token'))
            return self.reply(200,{'ok':True})
        if method=='POST' and path=='/api/requests':
            client = self.client('producer')
            return self.reply(201,store.create(client['token'],self.body()))
        if path.startswith('/api/requests/'):
            parts = path.split('/')
            request_id = parts[3]
            if method=='GET' and len(parts)==4:
                client = self.client('producer')
                return self.reply(200,store.get(request_id,client['token']))
            if method=='POST' and len(parts)==5:
                if parts[4]=='decision':
                    client = self.client('consumer')
                    body = self.body()
                    surface = 'watch' if client['role']=='watch' else body.get('surface')
                    item = store.decide(request_id, body.get('decision'),surface,body.get('version'),body.get('payload_hash'))
                    return self.reply(200,item)
                if parts[4] in ('cancel','ack'):
                    client = self.client('producer')
                    self.body()
                    fn = store.cancel if parts[4]=='cancel' else store.acknowledge
                    return self.reply(200,fn(request_id,client['token']))
        raise Problem(404,'Not found')
    def handle_route(self):
        try:
            self.route()
        except Problem as exc:
            self.reply(exc.status,{'error':exc.message})
        except (socket.timeout, BrokenPipeError, ConnectionResetError):
            pass
        except Exception:
            self.reply(500,{'error':'サーバーでエラーが発生しました'})
    do_GET = handle_route
    do_POST = handle_route
    do_OPTIONS = handle_route


def seed_demo(store):
    producer = digest(store.credential('producer','Synthetic demo'))
    examples = [
        ('codex','通知画面の仕上げ','pwd','MacBook Pro','command'),
        ('claude','音声メモの同期','git -c core.fsmonitor=false status --short','WSL · SSH','command'),
        ('claude','アプリの公開準備','git push origin main','WSL · SSH','command'),
    ]
    ids = []
    for source,task,operation,host,kind in examples:
        item = store.create(producer,dict(source=source,task=task,operation=operation,host=host,kind=kind,session='synthetic'))
        ids.append(item['id'])
    def heartbeat():
        while True:
            for request_id in ids:
                store.get(request_id,producer)
            time.sleep(3)
    threading.Thread(target=heartbeat,daemon=True).start()
