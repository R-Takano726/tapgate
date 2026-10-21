"""Conservative Watch policy. Repository-controlled scripts need phone review."""


def watch_safe(kind, operation):
    if kind != 'command':
        return False
    return operation in {
        'pwd',
        '/bin/pwd',
        'git -c core.fsmonitor=false status --short',
        'git -c core.fsmonitor=false --no-pager diff --stat --no-ext-diff --no-textconv',
    }
