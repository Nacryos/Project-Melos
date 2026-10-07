"""Private pinned-host staging transport; never switches production routes."""
import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import shlex
from discovery_transport import connect, run

ROOT = Path(__file__).resolve().parents[1]
REMOTE = '/home/alvin/services/melos/releases/campbell-20261007b'
CODE = ('scripts/integrate_campbell_assignment.py', 'scripts/stage_corpus_addition.py',
        'scripts/build_corpus.py', 'backend/textutils.py', 'backend/author_aliases.py',
        'backend/author_aliases.json')


def mkdir(client, path):
    if not (path == REMOTE or path.startswith(REMOTE + '/')) or '..' in PurePosixPath(path).parts:
        raise ValueError('Directory outside fixed release')
    run(client, 'mkdir -p ' + shlex.quote(path) + ' && chmod 700 ' + shlex.quote(path))


def upload(client, local, relative):
    relative = PurePosixPath(relative)
    if relative.is_absolute() or '..' in relative.parts or '\\' in str(relative):
        raise ValueError('Unsafe release-relative destination')
    destination = REMOTE + '/' + str(relative)
    mkdir(client, str(PurePosixPath(destination).parent))
    payload = Path(local).read_bytes()
    with client.open_sftp() as sftp:
        # Updating a staged code/input artifact is explicit; never a live mount.
        with sftp.file(destination, 'wb') as stream:
            stream.write(payload)
        sftp.chmod(destination, 0o600)
        with sftp.file(destination, 'rb') as stream:
            remote_hash = hashlib.sha256(stream.read()).hexdigest()
    digest = hashlib.sha256(payload).hexdigest()
    if digest != remote_hash:
        raise RuntimeError('Transfer hash mismatch')
    return {'path': str(relative), 'sha256': digest, 'bytes': len(payload)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=('prepare', 'upload', 'packet', 'stage'))
    parser.add_argument('local', nargs='?')
    parser.add_argument('relative', nargs='?')
    args = parser.parse_args()
    client = connect()
    try:
        if args.command == 'prepare':
            mkdir(client, REMOTE)
            results = [upload(client, ROOT / path, 'workspace/' + path) for path in CODE]
            results += [upload(client, ROOT / 'deploy' / name, name)
                        for name in ('campbell_release.py', 'release_qa29.py')]
            print(json.dumps(results, indent=2))
        elif args.command == 'upload':
            if not args.local or not args.relative:
                raise ValueError('Local file and release-relative destination required')
            print(json.dumps(upload(client, Path(args.local), args.relative)))
        elif args.command == 'packet':
            if not args.local or not args.relative:
                raise ValueError('Project-relative records and acceptance required')
            records, acceptance = (ROOT / args.local).resolve(), (ROOT / args.relative).resolve()
            if not records.is_relative_to(ROOT) or not acceptance.is_relative_to(ROOT):
                raise ValueError('Packet inputs outside workspace')
            approval = json.loads(acceptance.read_text(encoding='utf-8'))['files'][records.name]
            digest = hashlib.sha256(records.read_bytes()).hexdigest()
            if approval.get('verdict') != 'PASS' or approval.get('sha256') != digest:
                raise ValueError('Exact collector independent PASS required for transfer')
            rows = [json.loads(line) for line in records.read_text(encoding='utf-8').splitlines() if line.strip()]
            if len(rows) != approval.get('records') or len(rows) != 5:
                raise ValueError('Packet record count mismatch')
            paths = {records, acceptance}
            def provenance_paths(value):
                if isinstance(value, dict):
                    for key, item in value.items():
                        if key in ('image_path', 'ocr_path', 'candidate_path', 'audit_path') and isinstance(item, str):
                            paths.add((ROOT / item).resolve())
                        else:
                            provenance_paths(item)
                elif isinstance(value, list):
                    for item in value:
                        provenance_paths(item)
            for row in rows:
                paths.add((ROOT / row['raw_path']).resolve())
                metadata = row.get('metadata', {})
                provenance_paths(metadata)
                if metadata.get('audit_path'):
                    paths.add((ROOT / metadata['audit_path']).resolve())
                for chunk in metadata.get('source_excerpt_chunks', []):
                    for key in ('image_path', 'ocr_path'):
                        paths.add((ROOT / chunk[key]).resolve())
                    parsed = ROOT / chunk['ocr_path']
                    raw = parsed.with_name(parsed.name.replace('.parsed.json', '.raw.json'))
                    if raw.exists():
                        paths.add(raw.resolve())
            for path in paths:
                if not path.is_relative_to(ROOT) or not path.is_file():
                    raise ValueError('Missing or out-of-workspace packet artifact')
            results = [upload(client, path, 'workspace/' + path.relative_to(ROOT).as_posix())
                       for path in sorted(paths)]
            print(json.dumps(results, indent=2))
        elif args.command == 'stage':
            if not args.local or not args.relative:
                raise ValueError('Workspace-relative records and acceptance paths required')
            for path in (args.local, args.relative):
                if PurePosixPath(path).is_absolute() or '..' in PurePosixPath(path).parts or '\\' in path:
                    raise ValueError('Unsafe workspace-relative input')
            workspace = REMOTE + '/workspace'
            base = '/home/alvin/services/melos'
            cmd = ['python3', workspace + '/scripts/integrate_campbell_assignment.py',
                '--records', workspace + '/' + args.local, '--acceptance', workspace + '/' + args.relative,
                '--output', workspace + '/data/staging/candidate', '--root', workspace,
                '--corpus', base + '/releases/qa27/candidate-data/corpus.sqlite',
                '--evidence', base + '/data/evidence.sqlite',
                '--base-audit', workspace + '/runtime/campbell-assignment/base-audit.json',
                '--runtime-acceptance', base + '/data/reports/audit-acceptance.json',
                '--source', 'campbell_assignment',
                '--semantic-manifest', base + '/releases/qa27/candidate-data/manifest.json']
            print(run(client, 'umask 077; ' + shlex.join(cmd)).decode())
    finally:
        client.close()


if __name__ == '__main__':
    main()
