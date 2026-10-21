import json
import os
import socket
import time
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.parse import urlsplit


def state_dir():
    return Path(os.environ.get('TAPGATE_STATE',Path.home()/'.local/state/tapgate')).expanduser()


def api(url, path, token=None, body=None):
    parsed = urlsplit(url)
    if parsed.scheme!='https' and not (parsed.scheme=='http' and parsed.hostname in ('localhost','127.0.0.1')):
        raise ValueError('HTTPS is required outside localhost')
    headers = {'Content-Type':'application/json','X-TapGate':'1'}
    if token:
        headers['Authorization'] = 'Bearer '+token
    request = Request(url.rstrip('/')+path,data=None if body is None else json.dumps(body).encode(),headers=headers)
    with urlopen(request,timeout=12) as response:
        return json.load(response)


class Producer:
    def __init__(self):
        config = json.loads((state_dir()/'producer.json').read_text())
        self.url, self.token = config['url'], config['token']
    def create(self, data):
        return api(self.url,'/api/requests',self.token,data)
    def wait(self, item, timeout=570, cancelled=None):
        deadline = time.monotonic()+timeout
        failures = 0
        try:
            while time.monotonic()<deadline and not (cancelled and cancelled.is_set()):
                try:
                    item = api(self.url,'/api/requests/'+item['id'],self.token)
                    failures = 0
                except Exception:
                    failures += 1
                    if failures>=3:
                        raise
                    time.sleep(.8)
                    continue
                if item['state']!='pending':
                    return item['state']
                time.sleep(.8)
            return 'cancelled'
        finally:
            if item['state']=='pending':
                self.cancel(item)
    def ack(self, item):
        api(self.url,'/api/requests/'+item['id']+'/ack',self.token,{})
    def cancel(self,item):
        try:
            api(self.url,'/api/requests/'+item['id']+'/cancel',self.token,{})
        except Exception:
            pass


def admin(command):
    with socket.socket(socket.AF_UNIX,socket.SOCK_STREAM) as sock:
        sock.connect(str(state_dir()/'admin.sock'))
        sock.sendall((command+'\n').encode())
        return json.loads(sock.makefile().readline())
