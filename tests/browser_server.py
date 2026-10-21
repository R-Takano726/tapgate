import json
import os
import sys
import tempfile
import threading
import time
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from watchgate.store import Store,digest
from watchgate.server import Server,seed_demo
root=Path(tempfile.mkdtemp(prefix='tapgate-browser-'))
store=Store(root/'test.sqlite')
producer=store.credential('producer','Synthetic test host')
consumer=store.credential('consumer','Synthetic browser')
Path('/private/tmp/tapgate-browser-fixture.json' if sys.platform=='darwin' else '/tmp/tapgate-browser-fixture.json').write_text(json.dumps({'db':str(root/'test.sqlite'),'producer':producer,'consumer':consumer,'consumers':[store.credential('consumer','Synthetic browser') for _ in range(128)]}))
seed_demo(store)
def heartbeat():
    while True:
        with store.lock:
            store.db.execute("UPDATE requests SET lease=? WHERE state='pending'",(time.time()+20,))
        time.sleep(1)
threading.Thread(target=heartbeat,daemon=True).start()
Server(('127.0.0.1',8799),store,demo=True).serve_forever()
