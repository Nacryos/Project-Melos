"""Publish independently accepted phase-two text inputs, preserving old gates.

This does not issue audit verdicts. It copies PASS entries only after verifying
their exact artifact hash and record count. Run before build_corpus.py.
"""
from pathlib import Path
import hashlib
import json
import os
import tempfile

ROOT=Path(__file__).resolve().parents[1]


def merge(root=ROOT):
    root=Path(root)
    target=root/'data/reports/audit-acceptance.json'
    additions=root/'data/reports/p2-text-acceptance.json'
    original=json.loads(target.read_text(encoding='utf-8'))
    staged=json.loads(additions.read_text(encoding='utf-8'))
    accepted={}
    for name,entry in staged['files'].items():
        if entry.get('verdict')!='PASS':
            continue
        if Path(name).name!=name or not name.startswith('p2_') or not name.endswith('.jsonl'):
            raise ValueError(f'Unexpected staged text filename: {name}')
        path=root/'data/processed'/name
        with path.open('rb') as stream:
            digest=hashlib.file_digest(stream,'sha256').hexdigest()
        with path.open(encoding='utf-8-sig') as stream:
            count=sum(bool(line.strip()) for line in stream)
        if digest!=entry.get('sha256') or count!=entry.get('records'):
            raise ValueError(f'Staged text changed since its independent audit: {name}')
        accepted[name]=dict(entry,acceptance_origin='data/reports/p2-text-acceptance.json')
    # A revoked or pending phase-two verdict must not survive a later merge.
    # Legacy approvals remain untouched; phase-two admission has one authority.
    original['files']={name:entry for name,entry in original['files'].items()
                       if not name.startswith('p2_')}
    original['files'].update(accepted)
    with tempfile.NamedTemporaryFile('w',encoding='utf-8',dir=target.parent,
                                      prefix='acceptance-',suffix='.json',delete=False) as stream:
        json.dump(original,stream,ensure_ascii=False,indent=2)
        stream.write('\n')
        temporary=Path(stream.name)
    os.replace(temporary,target)
    return {name:entry['records'] for name,entry in accepted.items()}


if __name__=='__main__':
    print(json.dumps(merge(),ensure_ascii=False,indent=2))
