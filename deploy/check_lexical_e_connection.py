"""Read-only E container/host HTTP diagnostic; never emits server log content."""
import json
import shlex
from discovery_transport import connect, run

client = connect()
try:
    info = json.loads(run(client, 'docker inspect melos-api-lexical-canary-e'))[0]
    code = ('import json,urllib.request;'
            's=json.load(urllib.request.urlopen("http://127.0.0.1:8792/api/status",timeout=20));'
            'print(json.dumps({"passages":s["passages"],"semantic_ready":s["embeddings"]["ready"]}))')
    status = json.loads(run(client, 'python3 -c ' + shlex.quote(code)))
    logs = run(client, 'docker logs --tail 40 --timestamps melos-api-lexical-canary-e 2>&1').decode()
    print(json.dumps({'container_id': info['Id'], 'running': info['State']['Running'],
        'restart_count': info['RestartCount'], 'oom_killed': info['State']['OOMKilled'],
        'host_http_status': 200, 'status': status,
        'recent_log_summary': {'line_count': len(logs.splitlines()), 'traceback': 'Traceback' in logs,
                               'error': 'ERROR' in logs, 'startup_complete': 'Application startup complete' in logs}}))
finally:
    client.close()
