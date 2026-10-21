"""Own app-server sessions only; never inject keystrokes into another terminal."""
import json
import os
import socket
import subprocess
import sys
import threading
from .client import Producer

COMMAND = 'item/commandExecution/requestApproval'
FILE = 'item/fileChange/requestApproval'
PERMISSIONS = 'item/permissions/requestApproval'


def response_for(method, params, approved):
    if method==PERMISSIONS:
        # Permissions are turn-scoped by protocol. Require phone review of exact JSON.
        return {'permissions':params.get('permissions',{}) if approved else {},'scope':'turn'}
    decisions = params.get('availableDecisions')
    value = 'accept' if approved else 'decline'
    if decisions and value not in decisions:
        value = 'cancel'
    return {'decision':value}


def run(task, prompt, resume=None, executable='codex'):
    producer = Producer()
    process = subprocess.Popen([executable,'app-server','--stdio'],stdin=subprocess.PIPE,stdout=subprocess.PIPE,text=True,bufsize=1)
    lock = threading.Lock()
    pending = {}
    request_counter = 0
    errors = []
    threads = []
    file_changes = {}
    stopped = threading.Event()
    def send(value):
        with lock:
            if process.poll() is None:
                process.stdin.write(json.dumps(value)+'\n')
                process.stdin.flush()
    def call(method,params):
        nonlocal request_counter
        request_counter += 1
        send({'id':'client-'+str(request_counter),'method':method,'params':params})
        return 'client-'+str(request_counter)
    def handle_approval(message):
        p = message['params']
        method = message['method']
        cancel = threading.Event()
        pending[str(message['id'])] = cancel
        item = None
        try:
            if method==COMMAND:
                kind = 'network' if p.get('networkApprovalContext') else 'permissions' if p.get('additionalPermissions') else 'command'
                operation = json.dumps(p,ensure_ascii=False,indent=2) if kind in ('network','permissions') else p.get('command')
                operation = operation or json.dumps(p,ensure_ascii=False)
            else:
                kind = 'files' if method==FILE else 'permissions'
                if method==FILE and p.get('itemId') not in file_changes:
                    raise ValueError('File changes are missing; cannot approve unseen content')
                operation = json.dumps({'approval':p,'changes':file_changes[p['itemId']]},ensure_ascii=False,indent=2) if method==FILE else json.dumps(p,ensure_ascii=False,indent=2)
            # Entire canonical approval params remain visible in the larger-screen detail.
            item = producer.create(dict(source='codex',task=task,operation=operation,kind=kind,
                host=socket.gethostname(),session=p.get('threadId','unknown'),reason=json.dumps(p,ensure_ascii=False)))
            outcome = producer.wait(item,cancelled=cancel)
            if not cancel.is_set() and not stopped.is_set():
                send({'id':message['id'],'result':response_for(method,p,outcome=='approved')})
                if outcome in ('approved','denied'):
                    producer.ack(item)
        except Exception:
            if item:
                producer.cancel(item)
            if not cancel.is_set():
                send({'id':message['id'],'result':response_for(method,p,False)})
            print('TapGate: 承認を取得できず、操作を拒否しました。',file=sys.stderr)
        finally:
            pending.pop(str(message['id']),None)
    initialized = call('initialize',{'clientInfo':{'name':'tapgate','version':'0.1.0'},'capabilities':{'experimentalApi':True}})
    thread_request = None
    turn_request = None
    try:
        for line in process.stdout:
            message = json.loads(line)
            method = message.get('method')
            if message.get('error'):
                errors.append(message['error'])
                print(json.dumps(message['error'],ensure_ascii=False),file=sys.stderr)
                break
            if message.get('id')==initialized and 'result' in message:
                send({'method':'initialized'})
                params = {'approvalPolicy':'on-request','approvalsReviewer':'user','cwd':os.getcwd()}
                if resume:
                    params['threadId'] = resume
                else:
                    params['sandbox']='workspace-write'
                thread_request = call('thread/resume' if resume else 'thread/start',params)
            elif thread_request and message.get('id')==thread_request and 'result' in message:
                thread_id = message['result']['thread']['id']
                print('TapGate session: '+thread_id,file=sys.stderr)
                turn_request = call('turn/start',{'threadId':thread_id,'input':[{'type':'text','text':prompt}]})
            elif method in (COMMAND,FILE,PERMISSIONS) and 'id' in message:
                t = threading.Thread(target=handle_approval,args=(message,),daemon=True)
                threads.append(t)
                t.start()
            elif method=='serverRequest/resolved':
                event = pending.get(str(message['params'].get('requestId')))
                if event:
                    event.set()
            elif method=='item/started':
                item = message['params'].get('item',{})
                if item.get('type')=='fileChange':
                    file_changes[item['id']] = item.get('changes',[])
            elif method=='item/agentMessage/delta':
                print(message['params'].get('delta',''),end='',flush=True)
            elif method=='turn/completed':
                status = message['params'].get('turn',{}).get('status')
                if status != 'completed':
                    errors.append(status)
                break
            elif method and 'id' in message:
                # Unknown interactive protocols are never silently approved.
                send({'id':message['id'],'error':{'code':-32601,'message':'Unsupported interactive request; use the original Codex client'}})
                print('TapGate: 未対応の入力要求 '+method,file=sys.stderr)
    finally:
        stopped.set()
        for event in list(pending.values()):
            event.set()
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
        for thread in threads:
            thread.join(timeout=3)
    print()
    return 1 if errors else 0
