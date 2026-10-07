"""Audited, bounded maintenance through the unchanged production service.

Preflight is read-only. Run sends at most three frozen source forms per
invocation. A persistent intent journal prevents retries, including crashes.
"""
import argparse
import base64
import hashlib
import json
from pathlib import Path
from discovery_transport import connect, run

ROOT = Path(__file__).resolve().parents[1]
DIRECTORY = ROOT / 'runtime/alcaeus-morpheus-maintenance'
PLAN = DIRECTORY / 'next-batch-proposal.json'
PLAN_SHA = '9bc740fe577ed35c6b63976b34ee7c1a95e2ba9d8948fb085fbab24e9d9b9e39'
CONTAINER = 'e07b8119e854fd466222e5026759a9015d4dbad84ba4dccc4e46a4204b2d3d52'
WORKER = r'''
import base64, fcntl, hashlib, json, os, sqlite3, time
from pathlib import Path
from backend.machine_morphology import MachineMorphologyService, validate_form
sha=lambda b:hashlib.sha256(b).hexdigest()
payload=PAYLOAD
plan_bytes=base64.b64decode(payload['plan'])
assert sha(plan_bytes)==payload['plan_sha']
plan=json.loads(plan_bytes)
assert len(plan['proposed_next'])==12
service=MachineMorphologyService()
assert service.path.exists(), 'Existing production ledger required'
assert service.path.resolve()==Path('/app/runtime/machine_morphology.sqlite')
module=Path('/app/backend/machine_morphology.py').read_bytes()
quotas=[service.visitor_minute,service.visitor_day,service.global_minute,service.global_day]
assert all(0 < a <= b for a,b in zip(quotas,[3,20,10,200]))
visitor=sha(b'melos-alcaeus-maintenance-v1')
with sqlite3.connect('file:/app/data/corpus.sqlite?mode=ro',uri=True) as corpus:
    for item in plan['proposed_next']:
        assert not item['literal_elision'] and validate_form(item['form'])==item['form']
        for source in item['occurrences']:
            text=corpus.execute('SELECT text FROM passages WHERE id=?',(source['passage_id'],)).fetchone()[0]
            assert sha(text.encode())==source['source_text_sha256']
            a,b=source['start'],source['end']
            assert text[a:b]==item['form']
            line=text[text.rfind('\n',0,a)+1:text.find('\n',b) if '\n' in text[b:] else len(text)]
            assert line==source['source_line']
info={'module_sha256':sha(module),'database':str(service.path),'quotas':quotas,'fixed_visitor':visitor}
if payload['mode']=='preflight':
    info['module_base64']=base64.b64encode(module).decode()
    print(json.dumps(info))
else:
    assert sha(module)==payload['module_sha256']
    journal=service.path.parent/'alcaeus-maintenance-9bc740fe.json'
    lock=journal.with_suffix('.lock')
    with lock.open('a') as locked:
        fcntl.flock(locked,fcntl.LOCK_EX|fcntl.LOCK_NB)
        state=json.loads(journal.read_text()) if journal.exists() else {'plan_sha256':payload['plan_sha'],'prior_pilot_debit':8,'rows':[]}
        assert state['plan_sha256']==payload['plan_sha'] and state['prior_pilot_debit']==8
        assert all(r.get('status') in ('ok','no_analyses') for r in state['rows']), 'Unfinished/error intent: no retries'
        def save():
            temporary=journal.with_suffix('.tmp')
            with temporary.open('w') as handle:
                handle.write(json.dumps(state,ensure_ascii=False,indent=2))
                handle.flush()
                os.fsync(handle.fileno())
            temporary.replace(journal)
            descriptor=os.open(str(journal.parent),os.O_DIRECTORY)
            try:
                os.fsync(descriptor)
            finally:
                os.close(descriptor)
        done={r['form'] for r in state['rows']}
        attempted=sum(r['fetch_intent'] for r in state['rows'])
        assert attempted<=12
        new=0
        for item in plan['proposed_next']:
            if item['form'] in done or new>=3:
                continue
            before=service.analyze(item['form'],visitor,fetch=False)
            fetch=before['status']=='cache_miss'
            assert before['status'] in ('cache_miss','ok','no_analyses'), 'Unexpected cache state'
            if fetch:
                assert attempted<12
                now=time.time()
                with sqlite3.connect(service.path.resolve().as_uri()+'?mode=ro',uri=True) as con:
                    own=con.execute('SELECT count(*) FROM attempts WHERE visitor=? AND at>=?',(visitor,now-86400)).fetchone()[0]
                    active=con.execute('SELECT count(*) FROM inflight WHERE expires>?',(now,)).fetchone()[0]
                    assert own+8<min(20,service.visitor_day), 'Prior pilot debit plus production maintenance allowance reached'
                    assert active==0, 'Normal traffic in flight; defer maintenance'
            row={'form':item['form'],'source_occurrences':item['occurrences'],'fetch_intent':fetch,'started':time.time(),'status':'intent'}
            state['rows'].append(row)
            save() # durable before network; crash may consume budget, never retry
            started=time.monotonic()
            result=service.analyze(item['form'],visitor,fetch=True) if fetch else before
            row.update(status=result['status'],seconds=round(time.monotonic()-started,4),result=result)
            if result.get('receipt'):
                with sqlite3.connect(service.path.resolve().as_uri()+'?mode=ro',uri=True) as con:
                    metadata,raw=con.execute('SELECT metadata,raw FROM receipts WHERE id=?',(result['receipt']['id'],)).fetchone()
                assert sha(metadata.encode())==result['receipt']['id'] and sha(raw)==result['receipt']['raw_sha256']
                row.update(metadata=metadata,raw_base64=base64.b64encode(raw).decode())
            save()
            new+=int(fetch)
            attempted+=int(fetch)
            if result['status'] not in ('ok','no_analyses'):
                break
        print(json.dumps({'provenance':info,'journal':state},ensure_ascii=False))
'''


def sha(value):
    return hashlib.sha256(value).hexdigest()


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode',choices=('preflight','run'))
    args=parser.parse_args()
    encoded=PLAN.read_bytes()
    assert sha(encoded)==PLAN_SHA
    payload={'plan':base64.b64encode(encoded).decode(),'plan_sha':PLAN_SHA,'mode':args.mode}
    if args.mode=='run':
        audit=json.loads((DIRECTORY/'audit/production-pre-run.json').read_text())
        assert audit['verdict']=='PASS' and audit['script_sha256']==sha(Path(__file__).read_bytes()) and audit['plan_sha256']==PLAN_SHA
        payload['module_sha256']=audit['production_machine_module_sha256']
    client=connect()
    try:
        inspect=json.loads(run(client,'docker inspect melos-api'))[0]
        assert inspect['Id']==CONTAINER and inspect['State']['Running']
        script=WORKER.replace('PAYLOAD',repr(payload))
        stdin,stdout,stderr=client.exec_command('docker exec -i '+CONTAINER+' python -',timeout=45)
        stdin.write(script)
        stdin.channel.shutdown_write()
        output=stdout.read()
        errors=stderr.read()
        code=stdout.channel.recv_exit_status()
        if code:
            raise RuntimeError('Remote validation/execution stopped; no automatic retry. '+errors.decode()[-1500:])
        report=json.loads(output)
        report['container_id']=CONTAINER
        report['executor_sha256']=sha(Path(__file__).read_bytes())
        if args.mode=='preflight':
            module=base64.b64decode(report.pop('module_base64'))
            (DIRECTORY/'production-machine-morphology.py').write_bytes(module)
        target=DIRECTORY/('production-preflight.json' if args.mode=='preflight' else 'production-results.json')
        target.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
        print(json.dumps({'path':str(target),'sha256':sha(target.read_bytes()),'rows':len(report.get('journal',{}).get('rows',[]))}))
    finally:
        client.close()


if __name__=='__main__':
    main()
