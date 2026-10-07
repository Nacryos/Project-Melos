"""Private pinned-host transport for the discovery release (no credential output)."""
import argparse
import hashlib
import json
from pathlib import Path
import shlex
import paramiko

ROOT = Path(__file__).resolve().parents[1]
REMOTE = '/home/alvin/services/melos/releases/discovery-20261006'
CORRECTION_REMOTE = '/home/alvin/services/melos/releases/discovery-20261006b'


def connect():
    client = paramiko.SSHClient()
    client.load_host_keys(str(Path.home() / '.ssh/known_hosts'))
    key = client.get_host_keys()['100.64.176.44']['ssh-ed25519']
    client.get_host_keys().add('[100.64.176.44]:2222', 'ssh-ed25519', key)
    client.connect('100.64.176.44', port=2222, username='root',
                   key_filename=str(Path.home() / '.ssh/id_ed25519'),
                   look_for_keys=False, allow_agent=False, timeout=15)
    return client


def run(client, command):
    _, out, err = client.exec_command(command)
    content = out.read()
    errors = err.read()
    code = out.channel.recv_exit_status()
    if code:
        raise RuntimeError(f'Remote command failed ({code}); stderr suppressed')
    return content


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=('inspect', 'source', 'exec', 'upload'))
    parser.add_argument('value', nargs='?')
    parser.add_argument('destination', nargs='?')
    args = parser.parse_args()
    client = connect()
    try:
        if args.command == 'inspect':
            obj = json.loads(run(client, 'docker inspect melos-api'))[0]
            print(json.dumps({
                'id': obj['Id'], 'image': obj['Image'], 'running': obj['State']['Running'],
                'mounts': obj['Mounts'],
                'limits': {k: obj['HostConfig'][k] for k in (
                    'NanoCpus', 'CpuShares', 'Memory', 'MemorySwap', 'PidsLimit',
                    'ReadonlyRootfs', 'CapDrop', 'SecurityOpt', 'PortBindings', 'LogConfig')},
                'environment_keys': sorted(v.split('=', 1)[0] for v in obj['Config']['Env']),
                'user': obj['Config']['User'], 'cmd': obj['Config']['Cmd'],
                'routes': json.loads(run(client, 'tailscale serve status --json')),
            }, indent=2))
            candidates = json.loads(run(client, 'docker inspect melos-api-discovery-canary 2>/dev/null || true'))
            if candidates:
                candidate = candidates[0]
                print(json.dumps({'candidate_running': candidate['State']['Running'],
                    'host_config_changed_keys': [key for key in obj['HostConfig']
                        if obj['HostConfig'][key] != candidate['HostConfig'].get(key)],
                    'environment_equal': obj['Config']['Env'] == candidate['Config']['Env']}))
        elif args.command == 'source':
            name = args.value
            if not name or not name.startswith('backend/') or '..' in name:
                raise ValueError('Backend source path required')
            data = run(client, 'docker exec melos-api cat ' + shlex.quote('/app/' + name))
            target = ROOT / '.benchmarks/discovery-baseline' / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
            print(json.dumps({'path': str(target), 'sha256': hashlib.sha256(data).hexdigest()}))
        elif args.command == 'exec':
            print(run(client, args.value).decode())
        elif args.command == 'upload':
            destination = args.destination
            if not destination or not any(destination.startswith(root + '/') for root in (REMOTE, CORRECTION_REMOTE)) or '..' in destination:
                raise ValueError('Release-scoped destination required')
            with client.open_sftp() as sftp:
                sftp.put(str(ROOT / args.value), destination)
                sftp.chmod(destination, 0o600)
            print('Release file uploaded.')
    finally:
        client.close()


if __name__ == '__main__':
    main()
