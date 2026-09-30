"""Transfer only the locally configured Jev key over existing SSH; never print it."""
import argparse
import os
import re
import shlex
import subprocess
from pathlib import Path
from dotenv import dotenv_values

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--identity', required=True)
parser.add_argument('--host', required=True)
parser.add_argument('--port', default='2222')
args = parser.parse_args()
root = Path(__file__).resolve().parents[1]
values = dotenv_values(root / '.env')
key = os.environ.get('TYPESAFE_API_KEY') or values.get('TYPESAFE_API_KEY') or values.get('JEV_API_KEY')
if not key or not re.fullmatch(r'[A-Za-z0-9_.-]{20,256}', key):
    raise SystemExit('No valid local Jev key found; nothing transferred.')
remote = '''import os,sys
from pathlib import Path
root=Path('/home/alvin/services/melos/secrets')
root.mkdir(mode=0o700,exist_ok=True)
os.chown(root,1000,1000)
os.chmod(root,0o700)
data=sys.stdin.buffer.read(1024)
if not data.startswith(b'TYPESAFE_API_KEY=') or len(data)>512: raise SystemExit('Invalid secret payload')
temp=root/'jev.env.new'
fd=os.open(temp,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
with os.fdopen(fd,'wb') as handle: handle.write(data)
os.chown(temp,1000,1000)
os.replace(temp,root/'jev.env')
print('Jev credential installed in private, owner-only secret file.')
'''
result = subprocess.run(['ssh','-i',args.identity,'-p',args.port,'-o','IdentitiesOnly=yes',
                         '-o','BatchMode=yes',args.host,'python3 -c '+shlex.quote(remote)],
                        input=('TYPESAFE_API_KEY='+key+'\n').encode(),capture_output=True)
if result.returncode:
    raise SystemExit('Secret transfer failed; no credential content is printed.')
print('Jev credential installed privately on the API host; value not printed.')
