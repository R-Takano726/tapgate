import json
import os
import socket
import sys
from .client import Producer


def description(event):
    tool = event.get('tool_name','')
    args = event.get('tool_input',{})
    if tool=='Bash' and isinstance(args.get('command'),str):
        return ('command' if set(args).issubset({'command','description','timeout'}) else 'unknown'),args['command']
    return 'unknown', tool+'\n'+json.dumps(args,ensure_ascii=False,indent=2)


def decision_output(allowed):
    return {'hookSpecificOutput':{'hookEventName':'PermissionRequest','decision':{
        'behavior':'allow' if allowed else 'deny',
        **({} if allowed else {'message':'TapGateで拒否されました'})}}}


def run():
    item = None
    producer = None
    try:
        event = json.load(sys.stdin)
        name = event.get('hook_event_name')
        if name not in ('PermissionRequest','Notification'):
            return
        kind,operation = description(event)
        info = name=='Notification'
        if info:
            operation = str(event.get('message','元のターミナルで対応してください'))
            kind = 'notification'
        producer = Producer()
        item = producer.create(dict(source='claude',task=os.environ.get('TAPGATE_TASK') or 'Claude Code',
            operation=operation,kind=kind,reason=json.dumps({'tool_name':event.get('tool_name'), 'cwd':event.get('cwd'), 'tool_input':event.get('tool_input'), 'permission_mode':event.get('permission_mode')},ensure_ascii=False),
            host=socket.gethostname(),session=str(event.get('session_id','unknown')),informational=info))
        if info:
            # Notification hook must not block Claude. Informational items have no approval action.
            return
        outcome = producer.wait(item)
        if outcome in ('approved','denied'):
            # This acknowledges transport delivery, NOT execution of the underlying tool.
            print(json.dumps(decision_output(outcome=='approved')),flush=True)
            producer.ack(item)
    except (Exception,KeyboardInterrupt):
        # Empty output returns control to the original Claude permission prompt.
        if producer and item:
            producer.cancel(item)
        print('TapGate: 接続できません。元のターミナルで確認してください。',file=sys.stderr)
