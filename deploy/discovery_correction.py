"""Narrow code-only correction: exclude editorial-only child ranking candidates."""
import json
import os
from pathlib import Path
import sys
import time

import discovery_release as release

BASE = 'sha256:af8668a0b802d1e014da4decaaca1569389f180ad4bfe12dd8456198bb5a3610'
ROOT = Path('/home/alvin/services/melos/releases/discovery-20261006b')
CANARY = 'melos-api-discovery-correction-canary'


def focused_smoke(image):
    common = release.release
    old, routes = common.baseline()
    candidate = release.inspect(CANARY)
    release.validate_candidate(candidate, old, image, 8792)
    release.require(common.routes() == routes, 'Canary route changed')
    output = release.capture('python3', str(ROOT / 'discovery_smoke.py'),
                             '--origin', 'http://127.0.0.1:8792')
    with os.fdopen(os.open(ROOT / 'discovery_smoke.py.result.txt',
                          os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), 'w') as stream:
        stream.write(output)
    common.save('canary-pass.json', {'passed': True, 'image': image,
                'canary_id': candidate['Id'], 'completed_at': time.time()})


if __name__ == '__main__':
    if len(sys.argv) > 1 and sys.argv[1] == 'build':
        import build_discovery as build
        build.ROOT = ROOT
        build.BASE = BASE
        build.FILES = {'Dockerfile', 'backend/discovery.py', 'manifest.json'}
        del sys.argv[1]
        build.main()
    else:
        release.BASE = BASE
        release.RELEASE = ROOT
        release.CANARY = CANARY
        release.OLD = 'melos-api-before-discovery-correction'
        release.smoke = focused_smoke
        release.main()
