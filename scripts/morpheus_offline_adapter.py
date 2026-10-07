"""Source-bound offline inputs and literal XML projections; no network calls."""
from collections import Counter, defaultdict
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys
import unicodedata
from lxml import etree

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from backend.machine_morphology import validate_form, transport_form

D=ROOT/'runtime/morpheus-offline-eval'
M=ROOT/'runtime/alcaeus-morpheus-maintenance'
MORPHSVC=ROOT/'runtime/elision-protocol/morphsvc'
MORPHSVC_REV='264ad78feae7efcb23255736f7ed624f673db1e4'
SOURCE=ROOT/'runtime/campbell-assignment/campbell_assignment.jsonl'
OCC=ROOT/'runtime/alcaeus-occurrences/release-f/occurrences.json'
SOURCE_SHA='afe89681c1641331f609120c6c3e81220d17280f87e31b3ee5f3aeda965a3e1b'
PREFIX='morphsvc/lib/transformers/xslt/'
sha=lambda b:hashlib.sha256(b).hexdigest()


def immutable(path,data):
    path.parent.mkdir(parents=True,exist_ok=True)
    if path.exists() and path.read_bytes()!=data:
        raise ValueError('Refusing differing existing artifact: '+str(path))
    path.write_bytes(data)


def save(path,obj):
    immutable(path,json.dumps(obj,ensure_ascii=False,indent=2).encode())


def maps():
    outputs={}
    for name in ('alpheios-uni2betacode.xsl','morph-beta2unicode.xsl'):
        rel=PREFIX+name
        published=subprocess.check_output(['git','-C',str(MORPHSVC),'show',MORPHSVC_REV+':'+rel])
        # Use exact Git blob bytes, not Windows worktree CRLF conversion.
        immutable(D/'adapter-sources'/name,published)
        outputs[name]={'url':'https://github.com/alpheios-project/morphsvc/blob/'+MORPHSVC_REV+'/'+rel,
                       'sha256':sha(published)}
    license_bytes=subprocess.check_output(['git','-C',str(MORPHSVC),'show',MORPHSVC_REV+':LICENSE'])
    immutable(D/'adapter-sources/LICENSE',license_bytes)
    outputs['LICENSE']={'url':'https://github.com/alpheios-project/morphsvc/blob/'+MORPHSVC_REV+'/LICENSE','sha256':sha(license_bytes)}
    return outputs


def transformer(name):
    parser=etree.XMLParser(resolve_entities=False,no_network=True)
    tree=etree.fromstring((D/'adapter-sources'/name).read_bytes(),parser)
    return etree.XSLT(tree,access_control=etree.XSLTAccessControl.DENY_ALL)


def prepare():
    assert sha(SOURCE.read_bytes())==SOURCE_SHA
    map_provenance=maps()
    records={r['id']:r for r in map(json.loads,SOURCE.read_text(encoding='utf-8').splitlines())}
    occurrences=json.loads(OCC.read_text(encoding='utf-8'))
    indexed=defaultdict(list)
    eligible=defaultdict(list)
    exclusions=Counter()
    for row in occurrences:
        text=records[row['passage_id']]['text']
        assert row['source_exact'] and text[row['start']:row['end']]==row['text']
        assert sha(text.encode())==row['source_text_sha256']
        indexed[row['text']].append(row)
        if any(row.get(k) for k in ('editorial_fragment','partial_word','editorial_barriers','source_line_editorial_barriers')):
            exclusions['editorial_token_or_line']+=1
            continue
        try:
            valid=validate_form(row['text'])
        except ValueError:
            exclusions['unsupported_source_spelling']+=1
            continue
        if valid!=row['text']:
            exclusions['normalization_required']+=1
            continue
        eligible[row['text']].append(row)
    refs=[]
    intact=json.loads((M/'intact-results.json').read_text(encoding='utf-8'))
    production=json.loads((M/'production-results.json').read_text(encoding='utf-8'))
    for row in intact['results']+production['journal']['rows']:
        refs.append({'form':row['form'],'result':row['result']})
    elision=json.loads((ROOT/'runtime/elision-protocol/report.json').read_text(encoding='utf-8'))
    from backend.machine_morphology import project
    for row in elision['samples']:
        raw=(ROOT/'runtime/elision-protocol'/row['raw_file']).read_bytes()
        refs.append({'form':row['text'],'result':project(raw,row['text'],row['receipt'])})
    assert len(refs)==20 and len({r['form'] for r in refs})==20
    refs_by_form={r['form']:r for r in refs}
    transform=transformer('alpheios-uni2betacode.xsl')
    dummy=etree.XML(b'<dummy/>')
    forms=list(refs_by_form)+sorted(set(eligible)-set(refs_by_form))
    inputs=[]
    for i,form in enumerate(forms):
        assert form in indexed and validate_form(form)==form
        transported=transport_form(form)
        beta=str(transform(dummy,e_in=etree.XSLT.strparam(transported)))
        assert beta and beta.isascii() and len(beta)<=160 and not re.search(r'\s',beta)
        assert re.fullmatch(r"[a-zA-Z*()/\\=+|_^']+",beta), 'Unexpected Beta Code'
        sources=eligible.get(form) or indexed[form]
        inputs.append({'id':i,'form':form,'transport_form':transported,'beta':beta,
            'reference':refs_by_form.get(form),'corpus_clean_line_eligible':form in eligible,
            'occurrences':[{k:r[k] for k in ('occurrence_id','passage_id','start','end','source_text_sha256','source_line')} for r in sources]})
    save(D/'input-plan.json',{'source_sha256':SOURCE_SHA,'occurrences_sha256':sha(OCC.read_bytes()),
        'script_sha256':sha(Path(__file__).read_bytes()),'map_provenance':map_provenance,
        'reference_forms':len(refs),'corpus_eligible_unique_forms':len(eligible),
        'corpus_eligible_occurrences':sum(map(len,eligible.values())),'exclusions':dict(exclusions),
        'inputs':inputs})
    for item in inputs:
        immutable(D/'inputs'/f"{item['id']:04}.txt",(item['beta']+'\n').encode('ascii'))
    print(json.dumps({'forms':len(inputs),'references':len(refs),'eligible_unique':len(eligible),
                      'eligible_occurrences':sum(map(len,eligible.values()))}))


if __name__=='__main__':
    assert sys.argv[1:]==['prepare']
    prepare()
