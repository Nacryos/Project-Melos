"""Bind the root-approved bounded B evaluation to its exact promotion candidate.

Records operational/source-binding checks, never general philological accuracy.
No paid call, container action, route mutation, or receipt overwrite occurs here.
"""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from urllib.request import urlopen

from discovery_transport import connect, run
from lexical_release import BASE, BASE_CONTAINER, CANARY, MODULES

ROOT = Path(__file__).resolve().parents[1]
EXPECTED = '835376f20b3374a11ebb5e2f3ce5e8fb5d21d443f24fde6c7280772b664a8e69'
REMOTE = '/home/alvin/services/melos/releases/lexical-20261007b'


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def require(value, message):
    if not value:
        raise RuntimeError(message)


def main():
    output = ROOT / 'runtime/lyric-context-eval/canary-b-promotion-pass.json'
    require(not output.exists(), 'Do not overwrite a promotion approval')
    approved_path = ROOT / 'docs/audits/lexical-context-backend-b.json'
    approval = read(approved_path)
    artifacts, summaries = {}, []
    for folder in ('canary-b-326', 'canary-b-350'):
        directory = ROOT / 'runtime/lyric-context-eval' / folder
        receipt_path = directory / 'receipt.json'
        receipt = read(receipt_path)
        require(receipt['origin'] == 'http://127.0.0.1:8892', 'Unexpected evaluation origin')
        require(receipt.get('philological_accuracy_claim') is False, 'Evaluation must not claim general accuracy')
        artifacts[str(receipt_path.relative_to(ROOT))] = sha(receipt_path)
        for index, attempt in enumerate(receipt['attempts']):
            request_path, response_path = directory / f'{index}.request.json', directory / f'{index}.response.json'
            require(attempt['status'] == 'completed', 'Recorded evaluation incomplete')
            require(sha(request_path) == attempt['request_sha256'] and sha(response_path) == attempt['response_sha256'],
                    'Recorded request/response bytes differ')
            request, response = read(request_path), read(response_path)
            require(response['status'] == 'ok', 'Recorded response failed')
            require(response['selection']['text'] == request['selected_text'], 'Selected source text changed')
            for path in (request_path, response_path):
                artifacts[str(path.relative_to(ROOT))] = sha(path)
            summaries.append({'form': attempt['form'], 'parse': attempt['parse'],
                'gloss': attempt['gloss'].get('text'), 'status': attempt['status'],
                'sense_statuses': [item.get('status') for item in attempt.get('sense_items', [])]})
    require(len(summaries) == 4, 'Exactly four bounded word cases required')
    unresolved = [row for row in summaries if 'uncertain' in row['sense_statuses']]
    require(len(unresolved) == 1 and unresolved[0]['gloss'] is None, 'Uncertain sense must remain unforced')
    phrase_paths = list((ROOT / 'runtime/lyric-context-eval/canary-b-phrase').glob('*.json'))
    require(len(phrase_paths) == 1, 'One bounded phrase receipt required')
    phrase_path = phrase_paths[0]
    phrase = read(phrase_path)
    require(phrase['http_status'] == 200 and phrase['body']['status'] == 'ok', 'Phrase request failed')
    require(phrase['body']['selection']['text'] == phrase['request']['payload']['selected_text'], 'Phrase source changed')
    tokens = phrase['body']['interlinear']['readings'][0]['tokens']
    first = next(token for token in tokens if token['kind'] == 'word')
    require(first['parse_short'] == '2nd sg. aor. ind. act.', 'Full source-backed verb parse missing')
    artifacts[str(phrase_path.relative_to(ROOT))] = sha(phrase_path)
    client = connect()
    try:
        candidate = json.loads(run(client, 'docker inspect ' + CANARY))[0]
        production = json.loads(run(client, 'docker inspect melos-api'))[0]
        require(candidate['Id'] == EXPECTED and candidate['Image'] == BASE and candidate['State']['Running'], 'Wrong canary')
        require(production['Id'] == BASE_CONTAINER and production['State']['Running'], 'Production baseline changed')
        start = json.loads(run(client, 'cat ' + REMOTE + '/canary-start.json'))
        require(start['canary_id'] == EXPECTED and start['modules_pass_sha256'] == sha(approved_path), 'Start receipt differs')
        hashes = run(client, 'docker exec ' + CANARY + ' sha256sum ' +
                     ' '.join('/app/backend/' + name for name in sorted(MODULES))).decode()
        actual = {Path(path).name: digest for digest, path in (line.split(None, 1) for line in hashes.splitlines())}
        require(actual == {name: row['sha256'] for name, row in approval['files'].items()}, 'Effective modules differ')
    finally:
        client.close()
    with urlopen('http://127.0.0.1:8892/api/status', timeout=30) as stream:
        status = json.load(stream)
    require(status['passages'] == 288589 and status['embeddings']['ready'] and status['embeddings']['count'] == 116191,
            'Canary corpus/semantic readiness differs')
    result = {'passed': True, 'image': BASE, 'canary_id': EXPECTED,
        'modules_pass_sha256': sha(approved_path), 'root_public_promotion_approved': True,
        'promotion_authority': 'Explicit root instruction after bounded B operational evaluation; independent module review remains canary-only.',
        'checked_at': datetime.now(timezone.utc).isoformat(), 'actual_module_sha256': actual,
        'actual_evaluation_artifact_sha256': artifacts, 'word_cases': summaries,
        'phrase': {'http_status': phrase['http_status'], 'source_preserved': True, 'first_word_parse': first['parse_short']},
        'status_checks': {'passages': status['passages'], 'semantic_ready': status['embeddings']['ready'],
                          'semantic_count': status['embeddings']['count']},
        'stasis_uncertain': True, 'philological_accuracy_claim': False,
        'limits': ['Four bounded word cases and one phrase do not establish general parsing or semantic accuracy.',
                   'The uncertain stasis sense remains unselected; no forced interpretation.',
                   'No new dictionary/corpus records or subentry index are included.']}
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open('x', encoding='utf-8') as stream:
        json.dump(result, stream, ensure_ascii=False, indent=2)
    print(json.dumps({'path': str(output), 'sha256': sha(output), 'passed': True}))


if __name__ == '__main__':
    main()
