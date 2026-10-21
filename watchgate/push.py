"""APNs is optional. Failure remains visible and retries never auto-approve."""
import os
import time


def payload(item):
    # A user-assigned task label is intentionally visible; arbitrary commands never enter APNs.
    # Private mode also disables direct approval because its context is hidden.
    private = os.environ.get('TAPGATE_PRIVATE_NOTIFICATIONS') == '1'
    quick = not private and not item['phone_required'] and not item['informational']
    label = item['task'] if not private else 'TapGate'
    source = 'Codex' if item['source']=='codex' else 'Claude Code'
    body = item['operation'] if quick else '内容を確認してください'
    return {'aps':{'alert':{'title':label,'subtitle':source,'body':body},'sound':'default',
                   'category':'TAPGATE_QUICK' if quick else 'TAPGATE_REVIEW','thread-id':'tapgate'},
            'request_id':item['id'],'version':item['version'],'payload_hash':item['payload_hash']}


class APNs:
    def __init__(self):
        self.config = {k:os.environ.get('TAPGATE_APNS_'+k) for k in ('KEY_ID','TEAM_ID','KEY_PATH','TOPIC')}
        self.ready = all(self.config.values())
    def send(self, token, item):
        if not self.ready:
            return False, 'APNs未設定', False
        import httpx
        import jwt
        c = self.config
        with open(c['KEY_PATH']) as f:
            key = f.read()
        auth = jwt.encode({'iss':c['TEAM_ID'],'iat':int(time.time())},key,algorithm='ES256',headers={'kid':c['KEY_ID']})
        host = 'api.push.apple.com' if os.environ.get('TAPGATE_APNS_PRODUCTION')=='1' else 'api.sandbox.push.apple.com'
        with httpx.Client(http2=True,timeout=10) as client:
            r = client.post(f'https://{host}/3/device/{token}',json=payload(item),headers={
                'authorization':'bearer '+auth,'apns-topic':c['TOPIC'],'apns-push-type':'alert',
                'apns-priority':'10','apns-expiration':str(int(item['expires'])),'apns-collapse-id':item['id']})
        return r.status_code==200, f'APNs HTTP {r.status_code}', r.status_code==410


def work(store, sender=None, stop=None):
    sender = sender or APNs()
    while stop is None or not stop.is_set():
        with store.lock:
            rows = store.db.execute("SELECT * FROM pushes WHERE state IN ('queued','failed') AND retry<=? LIMIT 20",(time.time(),)).fetchall()
        for row in rows:
            item = store.get(row['request'])
            if item['state'] not in ('pending','notice'):
                with store.lock:
                    store.db.execute("UPDATE pushes SET state='cancelled' WHERE request=? AND device=?",(row['request'],row['device']))
                continue
            try:
                ok,error,remove = sender.send(row['device'],item)
            except Exception as exc:
                ok,error,remove = False,type(exc).__name__,False
            with store.lock:
                if remove:
                    store.db.execute('DELETE FROM devices WHERE token=?',(row['device'],))
                    store.db.execute("UPDATE pushes SET state='unregistered' WHERE device=?",(row['device'],))
                else:
                    store.db.execute('UPDATE pushes SET state=?,attempts=attempts+1,retry=?,error=? WHERE request=? AND device=?',
                        ('sent' if ok else 'failed',time.time()+min(60,2**min(row['attempts']+1,6)),None if ok else error,row['request'],row['device']))
        if stop is not None:
            stop.wait(1)
        else:
            time.sleep(1)
