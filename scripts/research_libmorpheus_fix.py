"""Save pinned primary-source research receipts; never build or execute source."""
import hashlib
import json
from pathlib import Path
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'runtime/libmorpheus-source-research'
REV = '9005feb4dcd85c7898899ee3abc2782519f8f050'
FIX = '26dd8378450204c96e9ca32cbb5e9d0524f80985'
REPO = 'https://api.github.com/repos/defense-humanites/libmorpheus/'
RAW = f'https://raw.githubusercontent.com/defense-humanites/libmorpheus/{REV}/'
PATHS = (
    'README.md', 'LICENSE', 'LICENSE-AGPL-3.0-or-later', '.gitmodules',
    'CMakeLists.txt', 'CMakePresets.json', 'docs/c17-port.md',
    'docs/runtime-data.md', 'docs/stemlib-format.md', 'docs/licensing.md',
    'docs/provenance.md', 'docs/stem-libraries.md',
    'src/includes/morphflags.h', 'src/includes/gkstring.h',
    'src/morphlib/morphflags.c', 'src/morphlib/endio.c',
    'test/stemlib-abi.c', 'test/stemlib-io.c', 'test/morphflag-bounds.c',
    'include/morpheus/morpheus.h', 'src/bridge/legacy_values.c',
)


def main():
    gate = json.loads((OUT / 'audit/source-discovery.json').read_text())
    if gate.get('verdict') != 'PASS' or gate.get('revision') != REV:
        raise ValueError('Independent discovery gate missing')
    if gate.get('script_sha256') != hashlib.sha256(Path(__file__).read_bytes()).hexdigest():
        raise ValueError('Research script changed after audit')
    dest = OUT / 'raw'
    if dest.exists():
        raise ValueError('No overwrite or implicit retry')
    dest.mkdir(parents=True)
    targets = [(path, RAW + path) for path in PATHS]
    targets += [('fix-commit.json', REPO + 'commits/' + FIX),
                ('release.json', REPO + 'releases/tags/v0.4.2'),
                ('tree.json', REPO + 'git/trees/' + REV + '?recursive=1')]
    receipts = []
    for name, url in targets:
        with urllib.request.urlopen(url, timeout=30) as response:
            if response.status != 200:
                raise ValueError(f'Non-200 source: {url}')
            body = response.read(2 * 1024 * 1024 + 1)
        if len(body) > 2 * 1024 * 1024:
            raise ValueError('Source exceeds research bound')
        path = dest / name
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open('xb') as output:
            output.write(body)
        receipts.append({'url': url, 'path': str(path.relative_to(ROOT)),
                         'bytes': len(body), 'sha256': hashlib.sha256(body).hexdigest()})
    report = {'revision': REV, 'fix_revision': FIX, 'source_executed': False,
              'script_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
              'receipts': receipts}
    with (OUT / 'manifest.json').open('x', encoding='utf-8') as output:
        output.write(json.dumps(report, indent=2) + '\n')
    print(json.dumps({'saved_sources': len(receipts), 'source_executed': False}))


if __name__ == '__main__':
    main()
