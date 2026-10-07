"""Bind root's explicit promotion decision to the tested E, F, G or H canary.

Read-only remote identity checks; this writes an approval receipt, not a
deployment. Operational context checks do not establish philological accuracy.
"""
from datetime import datetime, timezone
import argparse
import hashlib
import importlib
import json
from pathlib import Path
import re
import sys

from discovery_transport import connect, run
from lexical_release_e import BASE, BASE_CONTAINER, CANARY, MODULES, RELEASE

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def verify_tense_report(path, runtime):
    from scripts.check_source_tense_live import verify_dictionary, verify_interlinear
    path = Path(path).resolve()
    require(path.is_relative_to(runtime), 'Unexpected tense probe location')
    report = json.loads(path.read_text(encoding='utf8'))
    require(report['verdict'] == 'PASS' and report['origin'] == 'http://127.0.0.1:8892', 'Tense probe failed')
    source = ROOT / 'runtime/campbell-assignment/campbell_assignment.jsonl'
    fixture = ROOT / 'tests/fixtures/word-elthes-tense-preview.json'
    require(report['source_sha256'] == sha(source) and report['fixture_sha256'] == sha(fixture), 'Tense source/fixture changed')
    require(len(report['receipts']) == 2, 'Two actual tense HTTP responses required')
    responses = {}
    for filename in report['receipts']:
        saved_path = path.parent / 'receipts' / filename
        require(saved_path.resolve().is_relative_to(path.parent / 'receipts'), 'Invalid tense receipt path')
        saved = json.loads(saved_path.read_text(encoding='utf8'))
        body_path = saved_path.with_suffix('.body')
        require(saved['http_status'] == 200 and sha(body_path) == saved['raw_body_sha256'], 'Tense raw response changed')
        require(saved['request']['base'] == report['origin'], 'Wrong tense request origin')
        route = saved['request']['route']
        require(route not in responses, 'Duplicate tense response route')
        if route == '/api/analyze-passage':
            require(saved['request']['payload']['rerank'] is False and saved['request']['payload']['fetch_machine'] is False,
                    'Tense probe requested ranking/fetch')
        responses[route] = json.loads(body_path.read_bytes())
    require(set(responses) == {'/api/word', '/api/analyze-passage'}, 'Wrong tense route pair')
    expected = json.loads(fixture.read_text(encoding='utf8'))
    entry, restricted = verify_dictionary(responses['/api/word'], expected)
    actual = verify_interlinear(responses['/api/analyze-passage'], expected['form'], entry, restricted)
    require(actual == report['interlinear'] and actual['parse_short'] == '2nd sg. aor. ind. act.', 'Tense projection differs')
    require(set(report['restricted_sense_ids']) == restricted and len(restricted) == 2, 'Source restriction set changed')
    require(report['compact_meanings'] and all(row['sense_id'] not in restricted for row in report['compact_meanings']),
            'Restricted sense in compact headline')
    return path.parent


def approve(expected, operational, release='e', linked_reports=(), editorial_report=None, tense_report=None):
    require(release in ('e', 'f', 'g', 'h'), 'Unsupported reviewed release')
    config = importlib.import_module('lexical_release_' + release)
    base, baseline, canary_name = config.BASE, config.BASE_CONTAINER, config.CANARY
    modules, release_path = config.MODULES, config.RELEASE
    runtime = ROOT / ('runtime/lexical-release-' + release)
    require(bool(re.fullmatch('[a-f0-9]{64}', expected)), 'Exact canary ID required')
    directory = operational.resolve()
    require(directory.is_relative_to(runtime), 'Unexpected evidence directory')
    report_path = directory / 'report.json'
    report = json.loads(report_path.read_text(encoding='utf-8'))
    require(report['origin'] == 'http://127.0.0.1:8892' and report['request_count'] == 5,
            'Unexpected operational probe set')
    require(report['paid_ranking_requested'] is False, 'Unexpected provider calls in operational probes')
    require(len(report['results']) == 5, 'Incomplete results')
    require(any(row['after_parse'] == '2nd sg. aor. ind. act.' and row['form'] == 'ἦλθες'
                for row in report['results']), 'Complete source parse regressed')
    for row in report['results']:
        require(row['commentary_status'] == 'available' and row['commentary_paragraph_count'] > 0,
                'Commentary not available')
        require(row['context_characters'] > len(row['form']) and row['syntax_token_count'] > 1,
                'Neighboring syntax context not supplied')
        if release in ('f', 'g', 'h'):
            require(row.get('approved_translation_comparison_count') == 1,
                    'Source comparison not verified')
        receipt_path = directory / 'receipts' / row['receipt']
        require(receipt_path.resolve().is_relative_to(directory / 'receipts'), 'Invalid receipt path')
        receipt = json.loads(receipt_path.read_text(encoding='utf-8'))
        body_path = receipt_path.with_suffix('.body')
        require(receipt['http_status'] == 200 and sha(body_path) == receipt['raw_body_sha256'],
                'Actual response receipt changed')
    evidence_directories = [directory]
    if release in ('f', 'g', 'h'):
        require(len(linked_reports) == 2, 'Two source-linked operational probes required')
        forms = set()
        for linked_report in linked_reports:
            linked_report = Path(linked_report).resolve()
            require(linked_report.is_relative_to(runtime), 'Unexpected linked probe location')
            linked = json.loads(linked_report.read_text(encoding='utf8'))
            require(linked.get('paid_calls') == 0 and linked.get('linked_senses', 0) > 0,
                    'Linked inventory probe incomplete')
            require(linked['linked_senses'] <= linked['packet_senses']
                    and linked['packet_characters'] <= (64000 if release in ('g', 'h') else 32000),
                    'Linked packet bound failed')
            forms.add(linked['form'])
            for key in ('word_receipt', 'analysis_receipt'):
                receipt_path = linked_report.parent / 'receipts' / linked[key]
                require(receipt_path.resolve().is_relative_to(linked_report.parent / 'receipts'), 'Invalid linked receipt')
                receipt = json.loads(receipt_path.read_text(encoding='utf8'))
                require(receipt['http_status'] == 200 and sha(receipt_path.with_suffix('.body')) == receipt['raw_body_sha256'],
                        'Linked response changed')
            evidence_directories.append(linked_report.parent)
        require(forms == {'παχέων', 'δᾶμον'}, 'Wrong linked occurrence probe set')
    if release == 'g':
        require(editorial_report is not None, 'G requires source-bound editorial API probes')
        editorial_report = Path(editorial_report).resolve()
        require(editorial_report.is_relative_to(runtime), 'Unexpected editorial probe path')
        editorial = json.loads(editorial_report.read_text(encoding='utf8'))
        require(editorial.get('verdict') == 'PASS' and editorial.get('origin') == report['origin']
                and editorial.get('paid_calls') == 0 and editorial.get('machine_fetches_requested') == 0,
                'Editorial API verification failed')
        source = ROOT / 'runtime/campbell-assignment/campbell_assignment.jsonl'
        require(editorial.get('source_sha256') == sha(source), 'Editorial source artifact changed')
        source_ids = {json.loads(line)['id'] for line in source.read_text(encoding='utf8').splitlines()}
        require({row['passage_id'] for row in editorial['results']} == source_ids,
                'Editorial checks must cover all five source poems')
        require(editorial['totals']['eligible'] == 26 and editorial['totals']['available'] >= 10,
                'Editorial source coverage regressed')
        bundle = ROOT / 'runtime/alcaeus-morpheus-maintenance/successful-receipts.json'
        require(editorial.get('machine_bundle_sha256') == sha(bundle)
                and len(editorial.get('verified_cached_forms', [])) == 8,
                'Eight imported parser receipts were not verified through the API')
        for row in editorial['results']:
            receipt_path = editorial_report.parent / 'receipts' / row['receipt']
            require(receipt_path.resolve().is_relative_to(editorial_report.parent / 'receipts'),
                    'Invalid editorial receipt path')
            receipt = json.loads(receipt_path.read_text(encoding='utf8'))
            require(receipt['http_status'] == 200 and sha(receipt_path.with_suffix('.body')) == receipt['raw_body_sha256'],
                    'Editorial response changed')
        evidence_directories.append(editorial_report.parent)
    if release == 'h':
        require(tense_report is not None, 'H requires actual source-tense HTTP probes')
        evidence_directories.append(verify_tense_report(tense_report, runtime))
    audit_path = ROOT / ('docs/audits/lexical-context-backend-' + release + '.json')
    audit = json.loads(audit_path.read_text(encoding='utf-8'))
    require(audit['verdict'] == 'PASS' and audit['base_container_id'] == baseline, 'Wrong artifact audit')
    client = connect()
    try:
        canary = json.loads(run(client, 'docker inspect ' + canary_name))[0]
        live = json.loads(run(client, 'docker inspect melos-api'))[0]
        require(canary['Id'] == expected and canary['Image'] == base and canary['State']['Running'],
                'Canary identity changed')
        require(live['Id'] == baseline and live['State']['Running'], 'Production baseline changed')
        start = json.loads(run(client, 'cat ' + release_path.as_posix() + '/canary-start.json'))
        require(start['canary_id'] == expected and start['modules_pass_sha256'] == sha(audit_path),
                'Canary start receipt changed')
        hashes = run(client, 'docker exec ' + canary_name + ' sha256sum ' +
                     ' '.join('/app/backend/' + name for name in sorted(modules))).decode()
        actual = {Path(path).name: value for value, path in (line.split(None, 1) for line in hashes.splitlines())}
        require(actual == {name: row['sha256'] for name, row in audit['files'].items()}, 'Artifact bytes changed')
    finally:
        client.close()
    result = {'passed': True, 'image': base, 'canary_id': expected,
              'modules_pass_sha256': sha(audit_path), 'root_public_promotion_approved': True,
              'promotion_authority': 'Explicit root approval following source-bound context and commentary probes.',
              'checked_at': datetime.now(timezone.utc).isoformat(), 'actual_module_sha256': actual,
              'actual_evaluation_artifact_sha256': {str(path.relative_to(ROOT)): sha(path)
                  for folder in evidence_directories for path in folder.rglob('*') if path.is_file()},
              'philological_accuracy_claim': False,
              'limits': ['Model parsing and sense proposals remain fallible.',
                         'Commentary headings are not word-aligned grammatical attestations.',
                         ('Translation comparisons and one-hop dictionary resolver not included.' if release == 'e'
                          else 'Other-edition translations are reader comparisons, not aligned model evidence; linked meanings do not certify a parse.'),
                         'Corpus and vector indices unchanged.']}
    output = runtime / 'canary-promotion-pass.json'
    with output.open('x', encoding='utf-8') as handle:
        json.dump(result, handle, ensure_ascii=False, indent=2)
    print(json.dumps({'path': str(output), 'sha256': sha(output)}))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--approve-canary', required=True)
    parser.add_argument('--operational', type=Path, required=True)
    parser.add_argument('--release', choices=('e', 'f', 'g', 'h'), default='e')
    parser.add_argument('--linked-report', type=Path, action='append', default=[])
    parser.add_argument('--editorial-report', type=Path)
    parser.add_argument('--tense-report', type=Path)
    args = parser.parse_args()
    approve(args.approve_canary, args.operational, args.release, args.linked_report, args.editorial_report, args.tense_report)
