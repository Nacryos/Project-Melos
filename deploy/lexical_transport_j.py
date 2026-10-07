"""J immutable transport: seven audited modules and one pinned locator index."""
import importlib.util
import json
from pathlib import Path
import shlex
import sys
from lexical_release_j import BASE, BASE_CONTAINER, MODULES, NEW_MODULES, RELEASE, INDEX_SHA, CONFIG

spec = importlib.util.spec_from_file_location('_lexical_transport_for_j', Path(__file__).with_name('lexical_transport_g.py'))
transport = importlib.util.module_from_spec(spec)
spec.loader.exec_module(transport)
ROOT, REMOTE = transport.ROOT, RELEASE.as_posix()
for name in ('BASE', 'BASE_CONTAINER', 'MODULES', 'NEW_MODULES', 'REMOTE'):
    setattr(transport, name, globals()[name])
    setattr(transport.core, name, globals()[name])
transport.HELPERS = ('lexical_release_j.py', 'lexical_release_i.py', 'lexical_release_h.py',
                     'lexical_release_g.py', 'lexical_release_f.py', 'lexical_release_e.py',
                     'lexical_release_c.py', 'lexical_release.py', 'release_qa29.py')
original_upload = transport.upload_new


def upload_new(client, source, relative, mode=0o600):
    allowed = set(transport.HELPERS) | {'modules-pass.json', 'canary-pass.json', 'candidate-data/subentries.sqlite'} | {
        'candidate-code/' + name for name in MODULES}
    if relative not in allowed:
        raise ValueError('Outside seven-module/one-index J scope')
    custom = {'lexical_release_j.py', 'lexical_release_i.py', 'lexical_release_h.py', 'candidate-data/subentries.sqlite'}
    if relative not in custom:
        return original_upload(client, source, relative, mode)
    data = Path(source).read_bytes()
    if relative == 'candidate-data/subentries.sqlite' and (transport.core.digest(data) != INDEX_SHA or len(data) != 4837376):
        raise ValueError('Exact audited source locator index required')
    with client.open_sftp() as sftp:
        target = REMOTE + '/' + relative
        try:
            with sftp.file(target, 'rb') as stream:
                previous = stream.read()
        except FileNotFoundError:
            previous = None
        if previous is not None and previous != data:
            raise RuntimeError('Never replace J artifact')
        if previous is None:
            with sftp.file(target, 'wx') as stream:
                stream.write(data)
            sftp.chmod(target, mode)
        with sftp.file(target, 'rb') as stream:
            if stream.read() != data:
                raise RuntimeError('J artifact transfer differs')
    return {'path': relative, 'sha256': transport.core.digest(data), 'bytes': len(data)}


transport.upload_new = upload_new


def main():
    # Reuse the existing argument parser/upload guard for modules. Validate the
    # one new data artifact/config contract before making any remote changes.
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=('prepare',))
    parser.add_argument('--approval', type=Path, required=True)
    parser.add_argument('--candidate-dir', type=Path, required=True)
    args = parser.parse_args()
    receipt = transport.approval(args.approval, args.candidate_dir)
    expected = {'candidate-data/subentries.sqlite': {'sha256': INDEX_SHA, 'bytes': 4837376}}
    if receipt.get('data_artifacts') != expected or receipt.get('environment_changes') != CONFIG:
        raise ValueError('Audited J data/config scope differs')
    index = args.candidate_dir.parent / 'candidate-data/subentries.sqlite'
    if transport.core.digest(index.read_bytes()) != INDEX_SHA:
        raise ValueError('Staged index differs')
    client = transport.core.connect()
    try:
        transport.core.run(client, 'mkdir -p ' + shlex.quote(REMOTE + '/candidate-data') + ' && chmod 700 ' +
                           shlex.quote(REMOTE) + ' ' + shlex.quote(REMOTE + '/candidate-data'))
        print(json.dumps(upload_new(client, index, 'candidate-data/subentries.sqlite', 0o444)))
    finally:
        client.close()
    transport.main()


if __name__ == '__main__':
    main()
