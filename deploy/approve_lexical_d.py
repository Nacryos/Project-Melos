"""Bind explicit root promotion approval to tested immutable D bytes.

No deployment, credentials output or provider calls. This is an operational
receipt, never a claim of general linguistic accuracy.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re

from discovery_transport import connect, run
from lexical_release_d import BASE, BASE_CONTAINER, CANARY, MODULES, RELEASE

ROOT = Path(__file__).resolve().parents[1]


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def require(value, message):
    if not value:
        raise RuntimeError(message)


def main(expected):
    require(bool(re.fullmatch('[a-f0-9]{64}', expected)), 'Exact container ID required')
    directory = ROOT / 'runtime/lexical-release-d/operational'
    output = ROOT / 'runtime/lexical-release-d/canary-promotion-pass.json'
    require(not output.exists(), 'Approval already exists; do not overwrite')
    report = json.loads((directory / 'report.json').read_text(encoding='utf-8'))
    require(report['origin'] == 'http://127.0.0.1:8892' and len(report['results']) == 5,
            'Unexpected operational evaluation')
    require(report['paid_ranking_requested'] is False, 'Unexpected paid evaluation')
    by_form = {row['form']: row for row in report['results']}
    require(by_form['ἦλθες']['parse_short'] == '2nd sg. aor. ind. act.', 'Full parse missing')
    require(by_form['δᾶμον']['features'].get('Case') == 'Acc'
            and by_form['δᾶμον']['features'].get('Number') == 'Sing'
            and by_form['δᾶμον']['syntax_conflict'] is True, 'Source consensus missing')
    for form in ('ὄππᾳ', 'τάλαις'):
        row = by_form[form]
        require(row['features'] == {} and row['selection_basis'] == 'lexical_source_syntax_conflict'
                and row['lexical_variants'], 'Contradictory prediction still displayed')
    raw_hashes = {sha(path) for path in directory.glob('*.response.json')}
    require(raw_hashes == {row['response_sha256'] for row in report['results']}, 'Response bytes changed')
    audit_path = ROOT / 'docs/audits/lexical-context-backend-d.json'
    audit = json.loads(audit_path.read_text(encoding='utf-8'))
    require(audit['verdict'] == 'PASS' and audit['base_container_id'] == BASE_CONTAINER, 'Wrong module audit')
    client = connect()
    try:
        candidate = json.loads(run(client, 'docker inspect ' + CANARY))[0]
        production = json.loads(run(client, 'docker inspect melos-api'))[0]
        require(candidate['Id'] == expected and candidate['Image'] == BASE and candidate['State']['Running'],
                'Canary identity changed')
        require(production['Id'] == BASE_CONTAINER and production['State']['Running'], 'Live baseline changed')
        start = json.loads(run(client, 'cat ' + RELEASE.as_posix() + '/canary-start.json'))
        require(start['canary_id'] == expected and start['modules_pass_sha256'] == sha(audit_path),
                'Canary receipt changed')
        hashes = run(client, 'docker exec ' + CANARY + ' sha256sum ' +
                     ' '.join('/app/backend/' + name for name in sorted(MODULES))).decode()
        actual = {Path(path).name: value for value, path in (line.split(None, 1) for line in hashes.splitlines())}
        require(actual == {name: row['sha256'] for name, row in audit['files'].items()}, 'Module bytes changed')
    finally:
        client.close()
    result = {'passed': True, 'image': BASE, 'canary_id': expected,
              'modules_pass_sha256': sha(audit_path), 'root_public_promotion_approved': True,
              'promotion_authority': 'Explicit root approval after five bounded source-priority operational checks.',
              'checked_at': datetime.now(timezone.utc).isoformat(), 'actual_module_sha256': actual,
              'actual_evaluation_artifact_sha256': {str(path.relative_to(ROOT)): sha(path)
                                                  for path in directory.glob('*.json')},
              'philological_accuracy_claim': False,
              'limits': ['No universal parsing or contextual meaning accuracy claimed.',
                         'Commentary, translations and surrounding syntax window remain separate unfinished work.',
                         'No corpus, embeddings, or dictionary database changes.']}
    with output.open('x', encoding='utf-8') as handle:
        json.dump(result, handle, ensure_ascii=False, indent=2)
    print(json.dumps({'path': str(output), 'sha256': sha(output)}))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--approve-canary', required=True)
    main(parser.parse_args().approve_canary)
