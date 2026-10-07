"""Literal, pointer-traceable offline XML projection and observed parity only."""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import re
import sys
import unicodedata
from lxml import etree

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
from morpheus_offline_adapter import D, immutable, transformer, save

sha=lambda b:hashlib.sha256(b).hexdigest()
nfc=lambda value:unicodedata.normalize('NFC',value)


def candidate_key(lemma,features):
    # The hosted wrapper removes # before numeric headword sense suffixes.
    # Apply only in the explicit comparison key; retain both raw headwords.
    compatible=re.sub(r'#(\d+)$',r'\1',lemma)
    return json.dumps({'lemma':nfc(compatible),'features':features},sort_keys=True,ensure_ascii=False)


def xml_object(node):
    """Literal XML representation using the hosted adapter's legacy field names.

    Reference: pinned morphsvc/lib/xmljson/__init__.py, XMLData.data/Legacy.
    No phonological transformations; source XML is retained independently.
    """
    value={etree.QName(key).localname:val for key,val in node.attrib.items()}
    if node.text and node.text.strip():
        value['$']=node.text.strip()
    for child in node:
        key=etree.QName(child).localname
        item=xml_object(child)
        if key not in value:
            value[key]=item
        elif isinstance(value[key],list):
            value[key].append(item)
        else:
            value[key]=[value[key],item]
    return value


def full_key(dictionary,inflection):
    # Preserve all nested term/quantity/dictionary data, unlike scalar-only key.
    value=json.loads(json.dumps({'dictionary':dictionary,'inflection':inflection}))
    hdwd=value['dictionary']['hdwd']['$']
    value['dictionary']['hdwd']['$']=re.sub(r'#(\d+)$',r'\1',hdwd)
    def normalized(obj):
        if isinstance(obj,str): return nfc(obj)
        if isinstance(obj,list): return [normalized(x) for x in obj]
        if isinstance(obj,dict): return {k:normalized(v) for k,v in obj.items()}
        return obj
    return json.dumps(normalized(value),ensure_ascii=False,sort_keys=True)


def project(item,raw):
    if len(raw)>1048576:
        raise ValueError('Raw XML exceeds authorized bound')
    root=etree.fromstring(raw,etree.XMLParser(resolve_entities=False,no_network=True))
    if root.tag!='words' or len(root)!=1:
        raise ValueError('Expected exactly one word/unknown per literal input')
    child=root[0]
    if child.tag=='unknown':
        if child.text!=item['beta'] or len(child):
            raise ValueError('Unknown result does not bind literal input')
        return {'status':'no_analyses','raw_sha256':sha(raw),'candidates':[],'xml_pointer':'/words/unknown'}
    if child.tag!='word' or child.findtext('form')!=item['beta']:
        raise ValueError('Output form mismatch')
    converted=transformer('morph-beta2unicode.xsl')(root)
    tree=converted.getroot()
    output=etree.tostring(tree,encoding='utf-8',pretty_print=True)
    candidates=[]
    beta_entries=child.findall('entry')
    entries=tree.find('word').findall('entry')
    if not entries or len(entries)!=len(beta_entries):
        raise ValueError('Missing or changed output entries')
    for index,(entry,beta_entry) in enumerate(zip(entries,beta_entries),1):
        lemma=entry.findtext('dict/hdwd')
        if not lemma:
            raise ValueError('Missing source headword')
        inflections=entry.findall('infl')
        if not inflections or len(inflections)!=len(beta_entry.findall('infl')):
            raise ValueError('Missing or transformed-away source inflections')
        for number,infl in enumerate(inflections,1):
            if not infl.findtext('pofs'):
                raise ValueError('Missing source POS')
            features={element.tag:element.text for element in infl if len(element)==0 and element.text is not None}
            if len(features)!=len([element for element in infl if len(element)==0 and element.text is not None]):
                raise ValueError('Duplicate source feature tags')
            pointer=f'/words/word/entry[{index}]/infl[{number}]'
            candidates.append({'kind':'offline_machine_analysis','occurrence_attested':False,
                'lemma':lemma,'beta_headword':beta_entry.findtext('dict/hdwd'),'features':features,
                'dictionary_fields':xml_object(entry.find('dict')),'inflection':xml_object(infl),
                'entry_pointer':f'/words/word/entry[{index}]','inflection_pointer':pointer,
                'raw_inflection_xml':etree.tostring(beta_entry.findall('infl')[number-1],encoding='unicode'),
                'unicode_inflection_xml':etree.tostring(infl,encoding='unicode'),
                'comparison_key':candidate_key(lemma,features),
                'full_comparison_key':full_key(xml_object(entry.find('dict')),xml_object(infl))})
    return {'status':'ok','raw_sha256':sha(raw),'candidates':candidates,'unicode_xml':output.decode()}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('stage',choices=('reference','corpus'))
    args=parser.parse_args()
    plan=json.loads((D/'input-plan.json').read_text(encoding='utf-8'))
    build=json.loads((D/'result.json').read_text(encoding='utf-8'))
    for name, provenance in plan['map_provenance'].items():
        if sha((D/'adapter-sources'/name).read_bytes())!=provenance['sha256']:
            raise ValueError('Adapter map changed after input audit')
    inputs=[r for r in plan['inputs'] if bool(r['reference'])==(args.stage=='reference')]
    results=[]
    for item in inputs:
        path=D/'runs'/args.stage/f"{item['id']:04}.xml"
        raw=path.read_bytes()
        execution=json.loads(path.with_suffix('.json').read_text(encoding='utf-8'))
        if (execution['stdout_sha256']!=sha(raw) or execution['status']!='completed'
                or execution['exit_code']!=0 or execution['oom_killed']
                or execution['stdin_sha256']!=sha((item['beta']+'\n').encode('ascii'))
                or execution['image_id']!=build['runtime_image_id']):
            raise ValueError('Raw execution provenance mismatch')
        row=project(item,raw)
        converted=row.pop('unicode_xml',None)
        if converted is not None:
            immutable(path.with_suffix('.unicode.xml'),converted.encode())
        row.update({'id':item['id'],'form':item['form'],'beta':item['beta'],
                    'source_occurrences':item['occurrences'],'raw_path':str(path.relative_to(ROOT)),
                    'execution_metadata_sha256':sha(path.with_suffix('.json').read_bytes()),
                    'runtime_image_id':execution['image_id']})
        if item['reference']:
            reference=item['reference']['result']
            expected=Counter(candidate_key(c['lemma'],c['features']) for c in reference['machine_candidates'])
            observed=Counter(c['comparison_key'] for c in row['candidates'])
            expected_full=Counter(full_key(c['dictionary_fields'],c['inflection']) for c in reference['machine_candidates'])
            observed_full=Counter(c['full_comparison_key'] for c in row['candidates'])
            row['parity']={'same_status':reference['status']==row['status'],
                'same_multiset':expected==observed,'same_full_field_multiset':expected_full==observed_full,
                'missing_full_fields':list((expected_full-observed_full).elements()),
                'additional_full_fields':list((observed_full-expected_full).elements()),
                'missing':list((expected-observed).elements()),
                'additional':list((observed-expected).elements()),
                'hosted_receipt':reference['receipt']['id'],'hosted_revision':'unknown',
                'interpretation':'Candidate parity only, not contextual correctness'}
        results.append(row)
    save(D/f'{args.stage}-projection.json',{'input_plan_sha256':sha((D/'input-plan.json').read_bytes()),
        'build_result_sha256':sha((D/'result.json').read_bytes()),
        'script_sha256':sha(Path(__file__).read_bytes()),'comparison_policy':'ExactNFC lemma andliteralfeatures; documentedhosted#sense-suffixcompatibility only in comparisonkey; noletter/dialect/sense inference',
        'results':results})
    print(json.dumps({'forms':len(results),'recognized':sum(r['status']=='ok' for r in results),
        'candidates':sum(len(r['candidates']) for r in results),
        'parity':sum(r.get('parity',{}).get('same_multiset',False) for r in results)}))


if __name__=='__main__':
    main()
