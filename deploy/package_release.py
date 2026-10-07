"""Freeze allowlisted code and a verified syntax model; never package credentials/state."""
import argparse
import hashlib
import json
from pathlib import Path
import tarfile

ROOT = Path(__file__).resolve().parents[1]

def sha(path):
    with path.open('rb') as handle:
        return hashlib.file_digest(handle, 'sha256').hexdigest()

def package(output, pairs):
    records = []
    with tarfile.open(output, 'x:gz', compresslevel=1) as archive:
        for source, destination in sorted(pairs, key=lambda pair: pair[1]):
            before = source.stat()
            digest = sha(source)
            archive.add(source, arcname=destination, recursive=False)
            after = source.stat()
            if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
                raise RuntimeError(f'Input changed: {destination}')
            records.append({'path': destination, 'size': before.st_size, 'sha256': digest})
    return {'archive': output.name, 'sha256': sha(output), 'bytes': output.stat().st_size, 'files': records}

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('output', type=Path)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    paths = []
    for folder, endings in {
        'backend': {'.py', '.json'}, 'js': {'.js', '.mjs'}, 'css': {'.css'},
        'assets/branding': {'.svg', '.png'}, 'deploy': {'.py', '.sh', '.txt'},
        'scripts': {'.py', '.mjs'}, 'tests': {'.py', '.mjs'}, 'docs': {'.md'},
    }.items():
        paths += [p for p in (ROOT / folder).rglob('*') if p.is_file() and p.suffix in endings and '__pycache__' not in p.parts]
    paths += [ROOT / name for name in ['index.html', 'reader.html', 'requirements.txt', 'requirements-syntax.txt', 'deploy/Dockerfile.release']]
    code = package(args.output / 'code.tar.gz', [(p, p.relative_to(ROOT).as_posix()) for p in paths])
    model_root = ROOT / 'runtime/models/odycy/pipeline'
    provenance = json.loads((model_root / 'melos-provenance.json').read_text(encoding='utf-8'))
    # Check availability; archive manifests additionally bind every model byte.
    from backend.syntax_provider import SyntaxProvider
    status = SyntaxProvider(model_path=model_root).status()
    if status.get('state') not in {'available', 'ready'}:
        raise RuntimeError(f'Syntax model is not locally available: {status}')
    model = package(args.output / 'model.tar.gz', [(p, 'pipeline/' + p.relative_to(model_root).as_posix()) for p in model_root.rglob('*') if p.is_file()])
    receipt = {'code': code, 'model': model, 'model_revision': provenance.get('revision'), 'source_data_included': False, 'credentials_included': False}
    with (args.output / 'package.json').open('x', encoding='utf-8') as handle:
        json.dump(receipt, handle, indent=2)
    print(json.dumps({key: {k: v for k, v in value.items() if k != 'files'} for key, value in [('code', code), ('model', model)]}), flush=True)

if __name__ == '__main__':
    import sys
    sys.path.insert(0, str(ROOT))
    main()
