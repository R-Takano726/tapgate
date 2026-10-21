import argparse
import json
import os
import socketserver
import sys
import threading
from pathlib import Path
from .client import state_dir, admin, api
from .store import Store


def main():
    parser = argparse.ArgumentParser(prog='tapgate')
    sub = parser.add_subparsers(dest='command',required=True)
    serve = sub.add_parser('serve')
    serve.add_argument('--port',type=int,default=8787)
    serve.add_argument('--demo',action='store_true')
    serve.add_argument('--public-host',help='Exact HTTPS hostname used by Tailscale Serve')
    sub.add_parser('pair')
    sub.add_parser('host-pair')
    sub.add_parser('claude-hook')
    sub.add_parser('claude-settings')
    connect = sub.add_parser('connect')
    connect.add_argument('--url',required=True)
    connect.add_argument('--code',required=True)
    codex = sub.add_parser('codex')
    codex.add_argument('--task',required=True)
    codex.add_argument('--resume')
    codex.add_argument('prompt')
    args = parser.parse_args()
    if args.command=='claude-hook':
        from .claude_hook import run
        run()
        return
    if args.command=='codex':
        from .codex_runner import run
        sys.exit(run(args.task,args.prompt,args.resume))
    if args.command=='claude-settings':
        import shlex
        cmd = shlex.join([sys.executable,'-m','watchgate.cli','claude-hook'])
        # Include TAPGATE_STATE if a non-default installation is in use.
        if os.environ.get('TAPGATE_STATE'):
            cmd = 'TAPGATE_STATE='+shlex.quote(os.environ['TAPGATE_STATE'])+' '+cmd
        print(json.dumps({'hooks':{
            'PermissionRequest':[{'matcher':'','hooks':[{'type':'command','command':cmd,'timeout':620}]}],
            'Notification':[{'matcher':'permission_prompt','hooks':[{'type':'command','command':cmd,'timeout':15}]}]
        }},ensure_ascii=False,indent=2))
        return
    root = state_dir()
    if args.command=='connect':
        result = api(args.url,'/api/pair',body={'code':args.code,'name':os.uname().nodename,'native':True})
        # Refuse consumer pairing codes for a host.
        if result.get('role')!='producer':
            raise SystemExit('Use a host-pair code, not an iPhone pairing code.')
        root.mkdir(parents=True,exist_ok=True,mode=0o700)
        root.chmod(0o700)
        config = root/'producer.json'
        config.write_text(json.dumps({'url':args.url,'token':result['token']}))
        config.chmod(0o600)
        print('TapGate: 接続しました')
        return
    if args.command in ('pair','host-pair'):
        result = admin(args.command)
        print('TapGate 接続コード: '+result['code']+'（5分・1回限り）')
        print('iPhone／ブラウザでサーバーURLとコードを入力してください。' if args.command=='pair' else '接続先ホストで tapgate connect --url https://YOUR-HOST --code '+result['code'])
        return
    if args.command=='serve':
        from .server import Server, seed_demo
        from .push import work
        if args.demo:
            root = root/'demo'
        root.mkdir(parents=True,exist_ok=True,mode=0o700)
        root.chmod(0o700)
        if (root/'admin.sock').exists():
            raise SystemExit('TapGate is already running, or admin.sock is stale.')
        store = Store(root/'queue.sqlite3')
        local_config = root/'producer.json'
        try:
            token = json.loads(local_config.read_text())['token']
            store.auth(token,'producer')
        except Exception:
            token = store.credential('producer','Local host')
        local_config.write_text(json.dumps({'url':f'http://127.0.0.1:{args.port}','token':token}))
        local_config.chmod(0o600)
        # Pairing-code creation is local IPC, never a public HTTP endpoint.
        class Admin(socketserver.StreamRequestHandler):
            def handle(self):
                command = self.rfile.readline(100).decode().strip()
                if command in ('pair','host-pair'):
                    result = {'code':store.pair_code('producer' if command=='host-pair' else 'consumer')}
                    self.wfile.write((json.dumps(result)+'\n').encode())
        sock = root/'admin.sock'
        if sock.exists():
            # Do not delete an active server's socket or rotate its credentials.
            raise SystemExit('TapGate admin.sock exists. Stop the previous server; remove only a stale socket.')
        local = socketserver.ThreadingUnixStreamServer(str(sock),Admin)
        sock.chmod(0o600)
        threading.Thread(target=local.serve_forever,daemon=True).start()
        server = Server(('127.0.0.1',args.port),store,demo=args.demo,
                        hostnames=[args.public_host] if args.public_host else [],secure=bool(args.public_host))
        if args.demo:
            seed_demo(store)
        threading.Thread(target=work,args=(store,),daemon=True).start()
        print(f'TapGate {"DEMO " if args.demo else ""}http://localhost:{args.port}',flush=True)
        print('接続コード: '+store.pair_code()+'（5分・1回限り）',flush=True)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass
        finally:
            server.server_close()
            local.shutdown()
            sock.unlink(missing_ok=True)


if __name__=='__main__':
    main()
