import hashlib
import json
import secrets
import sqlite3
import threading
import time
from pathlib import Path


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


class Problem(Exception):
    def __init__(self, status, message):
        self.status, self.message = status, message
        super().__init__(message)


class Store:
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.lock = threading.RLock()
        self.db = sqlite3.connect(path, check_same_thread=False, isolation_level=None)
        self.path.chmod(0o600)
        self.db.row_factory = sqlite3.Row
        self.db.executescript('''
        PRAGMA journal_mode=WAL;
        CREATE TABLE IF NOT EXISTS clients (token TEXT PRIMARY KEY, role TEXT, name TEXT, created REAL);
        CREATE TABLE IF NOT EXISTS pairing (code TEXT PRIMARY KEY, expires REAL, attempts INTEGER, role TEXT);
        CREATE TABLE IF NOT EXISTS requests (id TEXT PRIMARY KEY, producer TEXT, payload TEXT,
          state TEXT, created REAL, expires REAL, lease REAL, decided REAL, delivered INTEGER DEFAULT 0);
        CREATE TABLE IF NOT EXISTS devices (token TEXT PRIMARY KEY, owner TEXT);
        CREATE TABLE IF NOT EXISTS pushes (request TEXT, device TEXT, state TEXT, attempts INTEGER,
          retry REAL, error TEXT, PRIMARY KEY(request,device));
        ''')
        # A restarted broker cannot prove the original blocking hook still exists.
        self.db.execute("UPDATE requests SET state='cancelled' WHERE state='pending'")
        self.db.execute("DELETE FROM pairing")
        if 'parent' not in [row[1] for row in self.db.execute('PRAGMA table_info(clients)')]:
            self.db.execute('ALTER TABLE clients ADD COLUMN parent TEXT')

    def credential(self, role, name, parent=None):
        token = secrets.token_urlsafe(32)
        with self.lock:
            self.db.execute("INSERT INTO clients (token,role,name,created,parent) VALUES (?,?,?,?,?)", (digest(token), role, name[:80], time.time(),parent))
        return token

    def auth(self, token, role=None):
        with self.lock:
            row = self.db.execute("SELECT * FROM clients WHERE token=?", (digest(token),)).fetchone()
        if not row or (role and row['role'] != role and not (role=='consumer' and row['role']=='watch')):
            raise Problem(401, '認証が必要です')
        return dict(row)

    def pair_code(self, role='consumer'):
        code = f'{secrets.randbelow(100000000):08d}'
        with self.lock:
            self.db.execute('DELETE FROM pairing')
            self.db.execute('INSERT INTO pairing VALUES (?,?,0,?)', (digest(code), time.time()+300,role))
        return code

    def pair(self, code, name):
        # Global attempt budget: concurrent guesses cannot bypass the limit.
        with self.lock:
            row = self.db.execute('SELECT * FROM pairing').fetchone()
            if not row or row['expires'] < time.time() or row['attempts'] >= 5:
                raise Problem(403, '接続コードが無効です。新しく発行してください')
            self.db.execute('UPDATE pairing SET attempts=attempts+1')
            if not secrets.compare_digest(row['code'], digest(str(code))):
                raise Problem(403, '接続コードが違います')
            self.db.execute('DELETE FROM pairing')
            return self.credential(row['role'], name)

    def expire(self):
        self.db.execute("UPDATE requests SET state='expired' WHERE state IN ('pending','notice') AND expires<=?", (time.time(),))

    def create(self, producer, data):
        if not isinstance(data, dict):
            raise Problem(400, 'Invalid request')
        required = {'task':160, 'operation':16000, 'source':20, 'host':100, 'session':200}
        for key, size in required.items():
            if not isinstance(data.get(key), str) or not data[key].strip() or len(data[key]) > size:
                raise Problem(400, f'Invalid {key}')
        if data['source'] not in ('codex', 'claude'):
            raise Problem(400, 'Invalid source')
        kind = data.get('kind', 'unknown')
        # Only a verified, exact, short read/test command can be tapped from Watch.
        from .policy import watch_safe
        phone = not watch_safe(kind, data['operation'])
        info = bool(data.get('informational', False))
        payload = {k:data[k] for k in required}
        reason = data.get('reason','')
        if not isinstance(reason,str) or len(reason)>32000:
            raise Problem(400,'Approval context too large')
        payload.update(kind=kind, phone_required=phone, informational=info, reason=reason)
        payload['payload_hash'] = digest(json.dumps(payload, sort_keys=True, ensure_ascii=False))
        now = time.time()
        request_id = secrets.token_urlsafe(18)
        with self.lock:
            self.expire()
            if self.db.execute("SELECT COUNT(*) FROM requests WHERE state='pending'").fetchone()[0]>=100:
                raise Problem(429,'Too many pending requests')
            self.db.execute('INSERT INTO requests VALUES (?,?,?,?,?,?,?,NULL,0)',
                            (request_id, producer, json.dumps(payload, ensure_ascii=False), 'notice' if info else 'pending', now, now+600, now+20))
            for row in self.db.execute('SELECT token FROM devices').fetchall():
                self.db.execute('INSERT INTO pushes VALUES (?,?,?,0,?,NULL)', (request_id,row[0],'queued',now))
        return self.get(request_id)

    def unpack(self, row):
        return dict(json.loads(row['payload']), id=row['id'], state=row['state'],
                    created=row['created'], expires=row['expires'], version=1,
                    live=row['lease']>time.time(), delivered=bool(row['delivered']))

    def get(self, request_id, producer=None):
        with self.lock:
            self.expire()
            row = self.db.execute('SELECT * FROM requests WHERE id=?', (request_id,)).fetchone()
            if not row or (producer and row['producer'] != producer):
                raise Problem(404, 'Request not found')
            if producer and row['state']=='pending':
                self.db.execute('UPDATE requests SET lease=? WHERE id=?', (time.time()+20, request_id))
                row = self.db.execute('SELECT * FROM requests WHERE id=?', (request_id,)).fetchone()
            return self.unpack(row)

    def listing(self):
        with self.lock:
            self.expire()
            return [self.unpack(x) for x in self.db.execute("SELECT * FROM requests ORDER BY CASE WHEN state='pending' THEN 0 WHEN state='notice' THEN 1 ELSE 2 END, created DESC LIMIT 200")]

    def decide(self, request_id, decision, surface, version, payload_hash):
        if decision not in ('approved','denied') or surface not in ('watch','phone','browser') or version != 1:
            raise Problem(400, 'Invalid decision')
        with self.lock:
            self.db.execute('BEGIN IMMEDIATE')
            try:
                self.expire()
                row = self.db.execute('SELECT * FROM requests WHERE id=?', (request_id,)).fetchone()
                if not row:
                    raise Problem(404, 'Request not found')
                item = self.unpack(row)
                if not secrets.compare_digest(item['payload_hash'], str(payload_hash)):
                    raise Problem(409, '承認内容が一致しません')
                if item['state'] == decision:
                    self.db.execute('COMMIT')
                    return item
                if item['state'] != 'pending':
                    raise Problem(409, 'この承認は終了しています')
                if not item['live']:
                    raise Problem(409, '実行元との接続が切れています')
                if item['informational']:
                    raise Problem(409, '元のターミナルで対応してください')
                if decision=='approved' and surface=='watch' and item['phone_required']:
                    raise Problem(403, 'iPhoneで全文を確認してください')
                self.db.execute('UPDATE requests SET state=?,decided=? WHERE id=? AND state=?',
                                (decision,time.time(),request_id,'pending'))
                self.db.execute('COMMIT')
            except Exception:
                self.db.execute('ROLLBACK')
                raise
            return self.get(request_id)

    def cancel(self, request_id, producer):
        with self.lock:
            self.get(request_id, producer)
            self.db.execute("UPDATE requests SET state='cancelled' WHERE id=? AND state='pending'", (request_id,))
        return self.get(request_id)

    def acknowledge(self, request_id, producer):
        with self.lock:
            item = self.get(request_id, producer)
            if item['state'] not in ('approved','denied'):
                raise Problem(409, 'No decision')
            self.db.execute('UPDATE requests SET delivered=1 WHERE id=?', (request_id,))
        return self.get(request_id)

    def register_device(self, owner, token):
        if not isinstance(token,str) or not 32<=len(token)<=200 or any(c not in '0123456789abcdef' for c in token):
            raise Problem(400,'Invalid APNs token')
        with self.lock:
            existing = self.db.execute('SELECT owner FROM devices WHERE token=?',(token,)).fetchone()
            if existing and existing[0] != owner:
                raise Problem(409, 'Device already paired')
            self.db.execute('INSERT OR REPLACE INTO devices VALUES (?,?)',(token,owner))
            self.expire()
            for row in self.db.execute("SELECT id FROM requests WHERE state IN ('pending','notice')").fetchall():
                self.db.execute("INSERT OR IGNORE INTO pushes VALUES (?,?,'queued',0,?,NULL)",(row[0],token,time.time()))

    def revoke(self, token_hash):
        with self.lock:
            tokens = [row[0] for row in self.db.execute('SELECT token FROM clients WHERE token=? OR parent=?',(token_hash,token_hash))]
            for token in tokens:
                self.db.execute('DELETE FROM pushes WHERE device IN (SELECT token FROM devices WHERE owner=?)',(token,))
                self.db.execute('DELETE FROM devices WHERE owner=?',(token,))
                self.db.execute('DELETE FROM clients WHERE token=?',(token,))
