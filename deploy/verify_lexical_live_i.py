"""Persist bounded post-I identity and actual raw-HTTP equality evidence."""
import json
from pathlib import Path
from discovery_transport import connect, run
from lexical_release_i import BASE, BASE_CONTAINER, CANARY, MODULES, OLD, RELEASE
from verify_lexical_live import require, sha

ROOT = Path(__file__).resolve().parents[1]


def main():
    folder = ROOT / 'runtime/lexical-release-i'
    output = folder / 'live-verify.json'
    require(not output.exists(), 'Never overwrite verification')
    audit_path = ROOT / 'docs/audits/lexical-context-backend-i.json'
    audit = json.loads(audit_path.read_text(encoding='utf-8'))
    reports = {}
    for name, origin in [('root-gzip', 'http://127.0.0.1:8892'), ('live-root-gzip', 'https://basecamp.taila44c41.ts.net:8443')]:
        path = folder / name / 'report.json'
        report = json.loads(path.read_text(encoding='utf-8'))
        require(report['status'] == 'PASS' and report['origin'] == origin, 'Transport report is not approved origin/PASS')
        require(len(report['receipts']) == 9 and report['paid_calls'] == report['parser_fetches'] == 0, 'Probe scope differs')
        for receipt in report['receipts']:
            body = path.parent / (receipt['label'] + '.body')
            require(sha(body) == receipt['sha256'] and body.stat().st_size == receipt['bytes'], 'Raw HTTP body changed')
        reports[name] = {'sha256': sha(path), 'origin': origin, 'passage': report['passage'], 'word': report['word']}
    require(reports['root-gzip']['passage'] == reports['live-root-gzip']['passage'] and
            reports['root-gzip']['word'] == reports['live-root-gzip']['word'], 'Public decoded source differs from private')
    client = connect()
    try:
        live = json.loads(run(client, 'docker inspect melos-api'))[0]
        old = json.loads(run(client, 'docker inspect ' + OLD))[0]
        canary = json.loads(run(client, 'docker inspect ' + CANARY))[0]
        require(live['Image'] == BASE and live['State']['Running'], 'Wrong live image/state')
        require(old['Id'] == BASE_CONTAINER and not old['State']['Running'], 'Exact H rollback not retained stopped')
        require(not canary['State']['Running'], 'Private I not stopped')
        raw = run(client, 'docker exec melos-api sha256sum ' + ' '.join('/app/backend/' + n for n in sorted(MODULES))).decode()
        hashes = {Path(path).name: value for value, path in (line.split(None, 1) for line in raw.splitlines())}
        require(hashes == {name: row['sha256'] for name, row in audit['files'].items()}, 'Published code differs')
        routes = json.loads(run(client, 'tailscale serve status --json'))
        require(routes == json.loads(run(client, 'cat ' + (RELEASE / 'routes-before.private.json').as_posix())), 'Routes differ')
        promotion = json.loads(run(client, 'cat ' + (RELEASE / 'promotion-receipt.json').as_posix()))
        require(promotion['container_id'] == live['Id'] and promotion['retained_container_id'] == old['Id'], 'Promotion differs')
        keys = ('NanoCpus', 'CpuShares', 'Memory', 'MemorySwap', 'PidsLimit', 'ReadonlyRootfs', 'CapDrop', 'SecurityOpt', 'LogConfig')
        require(all(live['HostConfig'][k] == old['HostConfig'][k] for k in keys), 'Resource/security changed')
        require(live['Config']['Env'] == old['Config']['Env'], 'Environment changed')
    finally:
        client.close()
    result = {'verdict': 'PASS', 'live_id': live['Id'], 'image': BASE, 'retained_id': old['Id'],
              'private_canary_stopped': True, 'modules_sha256': hashes, 'module_audit_sha256': sha(audit_path),
              'promotion': promotion, 'routes_resources_environment_preserved': True, 'raw_http_reports': reports,
              'data_scope': 'No corpus/vector/source database or cache import in I; promotion guard verifies unchanged mounts/artifacts.',
              'limits': 'Transfer compression only; no CPU latency or semantic accuracy claim.'}
    with output.open('x', encoding='utf-8') as stream:
        json.dump(result, stream, indent=2)
    print(json.dumps({'path': str(output), 'sha256': sha(output), 'live_id': live['Id']}))


if __name__ == '__main__':
    main()
