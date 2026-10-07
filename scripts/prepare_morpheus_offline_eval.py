"""Source acquisition and source-bound offline inputs, never live mutations."""
import argparse
import hashlib
import io
import json
from pathlib import Path, PurePosixPath
import subprocess
import tarfile
import urllib.request

ROOT=Path(__file__).resolve().parents[1]
D=ROOT/'runtime/morpheus-offline-eval'
REVISION='2f1a30d65ed7ae9c6120dbf64d730b863be412e4'
ARCHIVE_SHA='bdb3d653e5236850bc66b61f27b4102b6f46b9f163f876f72d0f5053e50daee0'
URL='https://codeload.github.com/alpheios-project/morpheus/tar.gz/'+REVISION
sha=lambda b:hashlib.sha256(b).hexdigest()


def save(path,value):
    path.parent.mkdir(parents=True,exist_ok=True)
    data=json.dumps(value,ensure_ascii=False,indent=2).encode()
    if path.exists() and path.read_bytes()!=data:
        raise ValueError('Refusing to overwrite differing artifact: '+str(path))
    path.write_bytes(data)


def acquire():
    gate=json.loads((D/'audit/source-discovery.json').read_text(encoding='utf-8'))
    assert gate['verdict']=='PASS'
    target=D/'raw/morpheus.tar.gz'
    target.parent.mkdir(parents=True,exist_ok=True)
    if target.exists():
        data=target.read_bytes()
    else:
        with urllib.request.urlopen(URL,timeout=30) as response:
            assert response.status==200
            data=response.read(20*1024*1024+1)
        assert len(data)<=20*1024*1024 and sha(data)==ARCHIVE_SHA
        with target.open('xb') as handle:
            handle.write(data)
    assert sha(data)==ARCHIVE_SHA
    rows=[]
    with tarfile.open(fileobj=io.BytesIO(data),mode='r:gz') as archive:
        members=archive.getmembers()
        assert sum(m.size for m in members)<=80*1024*1024
        for member in members:
            assert member.isdir() or member.isfile(), 'Special archive member forbidden'
            path=PurePosixPath(member.name)
            assert not path.is_absolute() and '..' not in path.parts
            assert path.parts[0]=='morpheus-'+REVISION
            if not member.isfile():
                continue
            relative=PurePosixPath(*path.parts[1:])
            content=archive.extractfile(member).read()
            rows.append({'path':str(relative),'size':len(content),'sha256':sha(content)})
            # Preserve source notices as raw bytes; no parser source is executed.
            if relative.name.lower().startswith(('license','copying')) or str(relative)=='README.md':
                out=D/'notices'/relative
                out.parent.mkdir(parents=True,exist_ok=True)
                if out.exists() and out.read_bytes()!=content:
                    raise ValueError('Notice conflict')
                out.write_bytes(content)
    rows.sort(key=lambda r:r['path'])
    def manifest(prefix):
        values=[r for r in rows if r['path'].startswith(prefix)]
        return {'files':len(values),'bytes':sum(r['size'] for r in values),
                'sha256':sha(json.dumps(values,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode())}
    save(D/'archive-manifest.json',{'url':URL,'revision':REVISION,'archive_sha256':sha(data),
         'archive_bytes':len(data),'source_manifest':manifest('src/'),'stemlib_manifest':manifest('dist/stemlib/'),
         'members':rows,'script_sha256':sha(Path(__file__).read_bytes())})
    print(json.dumps({'archive':str(target),'sha256':sha(data),'files':len(rows)}))


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode',choices=('acquire',))
    args=parser.parse_args()
    if args.mode=='acquire':
        acquire()
