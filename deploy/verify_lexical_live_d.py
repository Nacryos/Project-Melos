"""Read-only D release verification and five preapproved no-paid public probes."""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from urllib.parse import quote

from discovery_transport import connect, run
from lexical_release_d import BASE, BASE_CONTAINER, MODULES, OLD, CANARY, RELEASE
from verify_lexical_live import get, require, sha

ROOT = Path(__file__).resolve().parents[1]
REMOTE = RELEASE.as_posix()


def main():
    output = ROOT / 'runtime/lexical-release-d/live-verify.json'
    require(not output.exists(), 'Do not overwrite previous D verification')
    approval_path = ROOT / 'docs/audits/lexical-context-backend-d.json'
    approval = json.loads(approval_path.read_text(encoding='utf-8'))
    client = connect()
    try:
        live = json.loads(run(client, 'docker inspect melos-api'))[0]
        old = json.loads(run(client, 'docker inspect ' + OLD))[0]
        retained = json.loads(run(client, 'docker inspect melos-api-lexical-canary-c ' + CANARY))
        require(live['Image'] == BASE and live['State']['Running'], 'Wrong live image/state')
        require(old['Id'] == BASE_CONTAINER and not old['State']['Running'], 'Exact B rollback not retained')
        require(all(not row['State']['Running'] for row in retained), 'C or D private canary still running')
        hashes = run(client, 'docker exec melos-api sha256sum ' + ' '.join('/app/backend/' + name for name in sorted(MODULES))).decode()
        actual = {Path(path).name: digest for digest, path in (line.split(None, 1) for line in hashes.splitlines())}
        require(actual == {name: row['sha256'] for name, row in approval['files'].items()}, 'Live module hashes differ')
        routes = json.loads(run(client, 'tailscale serve status --json'))
        prior_routes = json.loads(run(client, 'cat ' + REMOTE + '/routes-before.private.json'))
        require(routes == prior_routes, 'Private/public routes changed')
        promotion = json.loads(run(client, 'cat ' + REMOTE + '/promotion-receipt.json'))
        require(promotion['container_id'] == live['Id'] and promotion['retained_container_id'] == BASE_CONTAINER,
                'Promotion receipt identity differs')
    finally:
        client.close()
    status = get('/api/status')
    require(status['passages'] == 288589 and status['embeddings']['ready'] and status['embeddings']['count'] == 116191,
            'Public corpus or semantic status differs')
    corpus = ROOT / 'runtime/campbell-assignment/campbell_assignment.jsonl'
    texts = {}
    for line in corpus.read_text(encoding='utf-8').splitlines():
        if not line.strip():
            continue
        record = json.loads(line)
        passage = get('/api/passage?id=' + quote(record['id'], safe=''))
        require(passage['text'] == record['text'], 'Public Campbell source text differs')
        texts[record['id']] = hashlib.sha256(passage['text'].encode()).hexdigest()
    require(len(texts) == 5, 'Exactly five Campbell records required')
    operational = ROOT / 'runtime/lexical-release-d/operational'
    reference = json.loads((operational / 'report.json').read_text(encoding='utf-8'))
    requests = sorted(operational.glob('*.request.json'))
    require(len(requests) == 5, 'Exactly five approved operational requests required')
    probes = []
    for request_path in requests:
        payload = json.loads(request_path.read_text(encoding='utf-8'))
        require(payload.get('rerank') is False and payload.get('fetch_machine') is False, 'Paid/fetch probe prohibited')
        expected = next(row for row in reference['results'] if row['form'] == payload['selected_text'] and row['passage_id'] == payload['passage_id'])
        result = get('/api/analyze-passage', payload)
        require(result['selection']['text'] == payload['selected_text'], 'Live probe source differs')
        token = next(row for row in result['interlinear']['readings'][0]['tokens'] if row['kind'] == 'word')
        require(token['parse_short'] == expected['parse_short'], 'Live default parse differs from approved D probe')
        require(token.get('features', {}) == expected['features'], 'Live default features differ')
        require(token.get('selection_basis') == expected['selection_basis'], 'Live parse provenance differs')
        target = output.parent / ('live-' + request_path.name.replace('.request.', '.response.'))
        with target.open('x', encoding='utf-8') as stream:
            json.dump(result, stream, ensure_ascii=False)
        probes.append({'request_sha256': sha(request_path), 'response_sha256': sha(target),
                       'response_path': str(target.relative_to(ROOT)), 'form': payload['selected_text'],
                       'parse_short': token['parse_short'], 'selection_basis': token.get('selection_basis')})
    receipt = {'passed': True, 'verified_at': datetime.now(timezone.utc).isoformat(),
        'live_container_id': live['Id'], 'image': BASE, 'retained_b_id': old['Id'],
        'retained_stopped_canaries': [row['Id'] for row in retained],
        'module_sha256': actual, 'module_approval_sha256': sha(approval_path),
        'promotion_receipt': promotion, 'routes_equal_to_baseline': True,
        'public_corpus_count': status['passages'], 'semantic_ready': True, 'semantic_count': 116191,
        'source_artifact_sha256': sha(corpus), 'public_text_sha256': texts, 'operational_probes': probes,
        'paid_model_calls': 0, 'philological_accuracy_claim': False}
    with output.open('x', encoding='utf-8') as stream:
        json.dump(receipt, stream, ensure_ascii=False, indent=2)
    print(json.dumps({'path': str(output), 'sha256': sha(output), 'live_container_id': live['Id'], 'passed': True}))


if __name__ == '__main__':
    main()
