"""Read-only post-F identity, source comparison and no-paid receipt checks."""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys
from urllib.parse import quote

from discovery_transport import connect, run
from lexical_release_f import BASE, BASE_CONTAINER, MODULES, OLD, CANARY, RELEASE
from verify_lexical_live import get, require, sha

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from backend.translation_comparisons import for_passage


def main():
    output = ROOT / 'runtime/lexical-release-f/live-verify.json'
    require(not output.exists(), 'Never overwrite verification evidence')
    approval_path = ROOT / 'docs/audits/lexical-context-backend-f.json'
    approval = json.loads(approval_path.read_text(encoding='utf-8'))
    client = connect()
    try:
        live = json.loads(run(client, 'docker inspect melos-api'))[0]
        old = json.loads(run(client, 'docker inspect ' + OLD))[0]
        canary = json.loads(run(client, 'docker inspect ' + CANARY))[0]
        require(live['Image'] == BASE and live['State']['Running'], 'Wrong live image/state')
        require(old['Id'] == BASE_CONTAINER and not old['State']['Running'], 'Exact E rollback not retained')
        require(not canary['State']['Running'], 'Private F canary still running')
        hashes = run(client, 'docker exec melos-api sha256sum ' + ' '.join('/app/backend/' + name for name in sorted(MODULES))).decode()
        actual = {Path(path).name: digest for digest, path in (line.split(None, 1) for line in hashes.splitlines())}
        require(actual == {name: row['sha256'] for name, row in approval['files'].items()}, 'Live artifacts differ')
        routes = json.loads(run(client, 'tailscale serve status --json'))
        require(routes == json.loads(run(client, 'cat ' + (RELEASE / 'routes-before.private.json').as_posix())), 'Routes changed')
        promotion = json.loads(run(client, 'cat ' + (RELEASE / 'promotion-receipt.json').as_posix()))
        require(promotion['container_id'] == live['Id'] and promotion['retained_container_id'] == BASE_CONTAINER, 'Promotion identity differs')
        keys = ('NanoCpus', 'CpuShares', 'Memory', 'MemorySwap', 'PidsLimit', 'ReadonlyRootfs', 'CapDrop', 'SecurityOpt', 'LogConfig')
        resources = {key: live['HostConfig'][key] for key in keys}
        require(resources == {key: old['HostConfig'][key] for key in keys}, 'Resources/security changed')
        require(live['Config']['Env'] == old['Config']['Env'], 'Environment changed')
    finally:
        client.close()
    status = get('/api/status')
    require(status['passages'] == 288589 and status['embeddings']['ready'] and status['embeddings']['count'] == 116191, 'Corpus/semantic coverage differs')
    corpus = ROOT / 'runtime/campbell-assignment/campbell_assignment.jsonl'
    comments_path = ROOT / 'runtime/lexical-release-e/candidate-code/edition_commentary_data.json'
    comparisons_path = output.parent / 'candidate-code/translation_comparisons_data.json'
    comments = {row['parent_id']: row for row in json.loads(comments_path.read_text(encoding='utf-8'))['records']}
    sources = {}
    for line in corpus.read_text(encoding='utf-8').splitlines():
        if not line.strip():
            continue
        record = json.loads(line)
        passage = get('/api/passage?id=' + quote(record['id'], safe=''))
        require(passage['text'] == record['text'], 'Greek changed')
        commentary = passage.get('published_commentary') or {}
        require(commentary.get('paragraphs') == comments[record['id']]['paragraphs'], 'Commentary changed')
        expected = for_passage(record, path=comparisons_path)
        require(expected['status'] == 'available' and passage.get('translation_comparisons') == expected, 'Comparison binding/content changed')
        sources[record['id']] = {'text_sha256': hashlib.sha256(passage['text'].encode()).hexdigest(),
            'commentary_paragraphs': commentary['paragraph_count'], 'comparison_count': expected['comparison_count'],
            'comparison_sha256': hashlib.sha256(json.dumps(expected, sort_keys=True, ensure_ascii=False).encode()).hexdigest()}
    require(len(sources) == 5 and sum(row['commentary_paragraphs'] for row in sources.values()) == 88, 'Source totals differ')
    reports = {}
    for directory in ('live-context', 'live-linked-350', 'live-linked-129'):
        path = output.parent / directory / 'report.json'
        report = json.loads(path.read_text(encoding='utf-8'))
        receipts = path.parent / 'receipts'
        checked = 0
        for receipt_path in receipts.glob('*.json'):
            if receipt_path.name.endswith('.pending.json'):
                continue
            receipt = json.loads(receipt_path.read_text(encoding='utf-8'))
            body = receipts / receipt['raw_body_file']
            require(body.resolve().parent == receipts.resolve() and sha(body) == receipt['raw_body_sha256'], 'HTTP body hash differs')
            require(receipt['http_status'] == 200 and json.loads(body.read_bytes()) == receipt['body'], 'Response differs')
            request = receipt['request']
            require(request['base'] == 'https://greeklyric.com', 'Not a public probe')
            if request['route'] == '/api/analyze-passage':
                require(request['payload']['rerank'] is False and request['payload']['fetch_machine'] is False, 'Probe requested paid/fetch work')
            checked += 1
        require(checked == (5 if directory == 'live-context' else 2), 'Wrong probe receipt count')
        reports[directory] = {'sha256': sha(path), 'http_receipts': checked}
        if directory == 'live-context':
            approved = json.loads((output.parent / 'root-context/report.json').read_text(encoding='utf-8'))
            for row in report['results']:
                expected = next(r for r in approved['results'] if (r['passage_id'], r['form']) == (row['passage_id'], row['form']))
                for key in ('after_parse', 'after_selection_basis', 'context_scope', 'context_sha256', 'commentary_paragraph_count'):
                    require(row[key] == expected[key], 'Public context differs from approved F: ' + key)
        else:
            expected_count = 15 if directory.endswith('350') else 11
            require(report['linked_senses'] == report['packet_senses'] == expected_count and report['paid_calls'] == 0, 'Linked source coverage differs')
    result = {'passed': True, 'verified_at': datetime.now(timezone.utc).isoformat(),
        'live_container_id': live['Id'], 'image': BASE, 'retained_e_id': old['Id'],
        'stopped_private_canary_id': canary['Id'], 'artifact_sha256': actual,
        'module_approval_sha256': sha(approval_path), 'promotion_receipt': promotion,
        'resources': resources, 'routes_equal_to_baseline': True, 'environment_equal_to_baseline': True,
        'public_corpus_count': 288589, 'semantic_ready': True, 'semantic_count': 116191,
        'source_artifact_sha256': sha(corpus), 'public_sources': sources,
        'comparisons_artifact_sha256': sha(comparisons_path), 'probe_reports': reports,
        'paid_model_calls': 0, 'philological_accuracy_claim': False}
    with output.open('x', encoding='utf-8') as stream:
        json.dump(result, stream, ensure_ascii=False, indent=2)
    print(json.dumps({'path': str(output), 'sha256': sha(output), 'live_container_id': live['Id'], 'passed': True}))


if __name__ == '__main__':
    main()
