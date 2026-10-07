"""Read-only post-promotion checks plus one non-paid source-bound phrase probe."""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from urllib.parse import quote
from urllib.request import Request, urlopen

from discovery_transport import connect, run
from lexical_release import BASE, BASE_CONTAINER, MODULES, OLD

ROOT = Path(__file__).resolve().parents[1]
REMOTE = '/home/alvin/services/melos/releases/lexical-20261007b'


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def require(value, message):
    if not value:
        raise RuntimeError(message)


def get(path, payload=None):
    data = None if payload is None else json.dumps(payload).encode()
    request = Request('https://greeklyric.com' + path, data=data,
                      headers={'Content-Type': 'application/json'})
    with urlopen(request, timeout=180) as response:
        require(response.status == 200, 'Public endpoint did not return 200')
        return json.load(response)


def main():
    output = ROOT / 'runtime/lyric-context-eval/live-b-verify.json'
    require(not output.exists(), 'Do not overwrite previous verification')
    approval_path = ROOT / 'docs/audits/lexical-context-backend-b.json'
    approval = json.loads(approval_path.read_text(encoding='utf-8'))
    client = connect()
    try:
        live = json.loads(run(client, 'docker inspect melos-api'))[0]
        old = json.loads(run(client, 'docker inspect ' + OLD))[0]
        require(live['Image'] == BASE and live['State']['Running'], 'Wrong live image/state')
        require(old['Id'] == BASE_CONTAINER and not old['State']['Running'], 'Exact prior container not retained')
        hashes = run(client, 'docker exec melos-api sha256sum ' +
                     ' '.join('/app/backend/' + name for name in sorted(MODULES))).decode()
        actual = {Path(path).name: digest for digest, path in (line.split(None, 1) for line in hashes.splitlines())}
        require(actual == {name: row['sha256'] for name, row in approval['files'].items()}, 'Live module hashes differ')
        routes = json.loads(run(client, 'tailscale serve status --json'))
        prior_routes = json.loads(run(client, 'cat ' + REMOTE + '/routes-before.private.json'))
        require(routes == prior_routes, 'Routes differ from original private/public configuration')
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
        require(passage['text'] == record['text'], 'Public Campbell text differs')
        texts[record['id']] = hashlib.sha256(passage['text'].encode()).hexdigest()
    require(len(texts) == 5, 'Five complete Campbell records required')
    phrase_paths = list((ROOT / 'runtime/lyric-context-eval/canary-b-phrase').glob('*.json'))
    require(len(phrase_paths) == 1, 'Ambiguous baseline phrase receipt')
    phrase = json.loads(phrase_paths[0].read_text(encoding='utf-8'))
    payload = phrase['request']['payload']
    require(payload['rerank'] is False and payload['fetch_machine'] is False, 'Paid or external fetch probe prohibited')
    result = get('/api/analyze-passage', payload)
    require(result['selection']['text'] == payload['selected_text'], 'Live phrase source differs')
    first = next(t for t in result['interlinear']['readings'][0]['tokens'] if t['kind'] == 'word')
    require(first['parse_short'] == '2nd sg. aor. ind. act.', 'Full live verb parse missing')
    record = {'passed': True, 'verified_at': datetime.now(timezone.utc).isoformat(),
        'live_container_id': live['Id'], 'image': live['Image'], 'retained_container_id': old['Id'],
        'module_sha256': actual, 'modules_approval_sha256': sha(approval_path),
        'promotion_receipt': promotion, 'public_corpus_count': status['passages'],
        'semantic_ready': status['embeddings']['ready'], 'semantic_count': status['embeddings']['count'],
        'source_artifact_sha256': sha(corpus), 'public_text_sha256': texts,
        'routes_equal_to_baseline': True, 'public_phrase_http_status': 200,
        'public_phrase_source_preserved': True, 'first_word_parse': first['parse_short'],
        'phrase_rerank': False, 'phrase_fetch_machine': False,
        'stasis_uncertain_in_bounded_approved_evaluation': True, 'philological_accuracy_claim': False}
    with output.open('x', encoding='utf-8') as stream:
        json.dump(record, stream, ensure_ascii=False, indent=2)
    print(json.dumps({'path': str(output), 'sha256': sha(output), 'live_container_id': live['Id'], 'passed': True}))


if __name__ == '__main__':
    main()
