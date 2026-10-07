"""Public E checks: exact Greek/commentary bytes and five no-paid context probes."""
from datetime import datetime, timezone
import argparse
import hashlib
import json
from pathlib import Path
import sys
from urllib.parse import quote

from discovery_transport import connect, run
from lexical_release_e import BASE, BASE_CONTAINER, MODULES, OLD, CANARY, RELEASE
from verify_lexical_live import get, require, sha

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.evaluate_context_windows import run as context_run, verify as verify_context

REMOTE = RELEASE.as_posix()


def main(reuse_context_report=False):
    sys.stdout.reconfigure(encoding='utf-8')
    output = ROOT / 'runtime/lexical-release-e/live-verify.json'
    context_output = output.parent / 'live-context'
    require(not output.exists() and (not context_output.exists() or reuse_context_report), 'Never overwrite verification evidence')
    approval_path = ROOT / 'docs/audits/lexical-context-backend-e.json'
    approval = json.loads(approval_path.read_text(encoding='utf-8'))
    client = connect()
    try:
        live = json.loads(run(client, 'docker inspect melos-api'))[0]
        old = json.loads(run(client, 'docker inspect ' + OLD))[0]
        canary = json.loads(run(client, 'docker inspect ' + CANARY))[0]
        require(live['Image'] == BASE and live['State']['Running'], 'Wrong live image/state')
        require(old['Id'] == BASE_CONTAINER and not old['State']['Running'], 'Exact D rollback not retained')
        require(not canary['State']['Running'], 'E private canary still running')
        hashes = run(client, 'docker exec melos-api sha256sum ' + ' '.join('/app/backend/' + name for name in sorted(MODULES))).decode()
        actual = {Path(path).name: digest for digest, path in (line.split(None, 1) for line in hashes.splitlines())}
        require(actual == {name: row['sha256'] for name, row in approval['files'].items()}, 'Live artifact hashes differ')
        routes = json.loads(run(client, 'tailscale serve status --json'))
        original_routes = json.loads(run(client, 'cat ' + REMOTE + '/routes-before.private.json'))
        require(routes == original_routes, 'Public/private routes changed')
        promotion = json.loads(run(client, 'cat ' + REMOTE + '/promotion-receipt.json'))
        require(promotion['container_id'] == live['Id'] and promotion['retained_container_id'] == BASE_CONTAINER,
                'Promotion receipt identity differs')
        resource_keys = ('NanoCpus', 'CpuShares', 'Memory', 'MemorySwap', 'PidsLimit', 'ReadonlyRootfs', 'CapDrop', 'SecurityOpt', 'LogConfig')
        resources = {key: live['HostConfig'][key] for key in resource_keys}
        require(resources == {key: old['HostConfig'][key] for key in resource_keys}, 'Resources/security changed')
    finally:
        client.close()
    status = get('/api/status')
    require(status['passages'] == 288589 and status['embeddings']['ready'] and status['embeddings']['count'] == 116191,
            'Public corpus or semantic coverage differs')
    corpus = ROOT / 'runtime/campbell-assignment/campbell_assignment.jsonl'
    sidecar = ROOT / 'runtime/lexical-release-e/candidate-code/edition_commentary_data.json'
    comments = {row['parent_id']: row for row in json.loads(sidecar.read_text(encoding='utf-8'))['records']}
    texts, paragraphs, records = {}, {}, {}
    for line in corpus.read_text(encoding='utf-8').splitlines():
        if not line.strip():
            continue
        record = json.loads(line)
        records[record['id']] = record
        passage = get('/api/passage?id=' + quote(record['id'], safe=''))
        require(passage['text'] == record['text'], 'Public Campbell Greek differs')
        texts[record['id']] = hashlib.sha256(passage['text'].encode()).hexdigest()
        commentary = passage.get('published_commentary') or {}
        require(commentary.get('status') == 'available' and commentary.get('parent_id') == record['id'], 'Public commentary missing/binding wrong')
        require(commentary['paragraphs'] == comments[record['id']]['paragraphs'], 'Public commentary bytes/metadata differ')
        require(commentary['scope'] == 'whole_poem_commentary' and commentary['word_attestation'] is False,
                'Commentary incorrectly promoted to word annotation')
        paragraphs[record['id']] = commentary['paragraph_count']
    require(len(texts) == 5 and sum(paragraphs.values()) == 88, 'Source/commentary totals differ')
    if not reuse_context_report:
        context_run('https://greeklyric.com', ROOT / 'runtime/lexical-release-d/live-root', context_output, require_commentary=True)
    context_report = json.loads((context_output / 'report.json').read_text(encoding='utf-8'))
    require(context_report['origin'] == 'https://greeklyric.com' and context_report['request_count'] == 5
            and context_report['paid_ranking_requested'] is False, 'Context receipt origin/count differs')
    approved_context = json.loads((output.parent / 'operational-restored-tunnel/report.json').read_text(encoding='utf-8'))
    for row in context_report['results']:
        saved_path = context_output / 'receipts' / row['receipt']
        saved = json.loads(saved_path.read_text(encoding='utf-8'))
        body_path = saved_path.parent / saved['raw_body_file']
        require(body_path.resolve().parent == saved_path.parent.resolve(), 'Receipt body path escapes')
        require(saved['http_status'] == 200 and sha(body_path) == saved['raw_body_sha256'], 'Saved HTTP body differs')
        result = json.loads(body_path.read_bytes())
        require(result == saved['body'], 'Saved response projection differs')
        request = saved['request']
        require(request['base'] == 'https://greeklyric.com' and request['route'] == '/api/analyze-passage'
                and request['payload']['rerank'] is False and request['payload']['fetch_machine'] is False,
                'Saved probe request differs')
        verified = verify_context(result, request['payload'], records[row['passage_id']], require_commentary=True)
        require(all(row[key] == value for key, value in verified.items()), 'Context report differs from actual body')
        expected = next(item for item in approved_context['results'] if (item['passage_id'], item['form']) == (row['passage_id'], row['form']))
        for key in ('after_parse', 'after_selection_basis', 'context_scope', 'context_sha256', 'commentary_paragraph_count'):
            require(row[key] == expected[key], 'Public context probe differs from approved E: ' + key)
    receipt = {'passed': True, 'verified_at': datetime.now(timezone.utc).isoformat(),
        'live_container_id': live['Id'], 'image': BASE, 'retained_d_id': old['Id'],
        'stopped_private_canary_id': canary['Id'], 'artifact_sha256': actual,
        'module_approval_sha256': sha(approval_path), 'promotion_receipt': promotion,
        'resources': resources, 'routes_equal_to_baseline': True,
        'public_corpus_count': status['passages'], 'semantic_ready': True, 'semantic_count': 116191,
        'source_artifact_sha256': sha(corpus), 'public_text_sha256': texts,
        'commentary_artifact_sha256': sha(sidecar), 'public_commentary_paragraphs': paragraphs,
        'context_probe_report': str((context_output / 'report.json').relative_to(ROOT)),
        'context_probe_report_sha256': sha(context_output / 'report.json'),
        'paid_model_calls': 0, 'philological_accuracy_claim': False}
    with output.open('x', encoding='utf-8') as stream:
        json.dump(receipt, stream, ensure_ascii=False, indent=2)
    print(json.dumps({'path': str(output), 'sha256': sha(output), 'live_container_id': live['Id'], 'passed': True}))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--reuse-context-report', action='store_true')
    main(parser.parse_args().reuse_context_report)
