"""Read-only receipt export and live cache-only source occurrence checks."""
import argparse
import hashlib
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
sys.path.insert(0,str(ROOT/'scripts'))
from audit_alcaeus_occurrences import Receipts, occurrence
from deploy.sync_morphology_receipts import read_bundle

D=ROOT/'runtime/alcaeus-morpheus-maintenance'
sha=lambda b:hashlib.sha256(b).hexdigest()


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode',choices=('export','api'))
    parser.add_argument('--base',default='https://greeklyric.com')
    args=parser.parse_args()
    report=json.loads((D/'production-results.json').read_text(encoding='utf-8'))
    rows=report['journal']['rows']
    if args.mode=='export':
        entries=[]
        for row in rows:
            if row['status']!='ok':
                continue
            receipt=row['result']['receipt']
            key=sha((receipt['parser_version']+'\n'+row['form']).encode())
            entries.append({'key':key,'receipt_id':receipt['id'],'metadata':row['metadata'],'raw_base64':row['raw_base64']})
        bundle={'format':'melos-successful-morphology-receipts-v1','parser_version':'alpheios-literal-v1','entries':entries}
        path=D/'production-successful-receipts.json'
        with path.open('x',encoding='utf-8') as handle:
            json.dump(bundle,handle,ensure_ascii=False,indent=2)
        validated=read_bundle(path)
        print(json.dumps({'path':str(path),'sha256':sha(path.read_bytes()),'validated':len(validated)}))
        return
    records={r['id']:r for r in map(json.loads,(ROOT/'runtime/campbell-assignment/campbell_assignment.jsonl').read_text(encoding='utf-8').splitlines())}
    baseline={r['occurrence_id']:r for r in json.loads((ROOT/'runtime/alcaeus-occurrences/release-f/occurrences.json').read_text(encoding='utf-8'))}
    # Earlier batch source lines can contain words warmed in a later batch.
    # Freeze each batch separately rather than reusing its stale cache state.
    api=Receipts(args.base,D/('production-api-responses-'+str(len(rows))))
    results=[]
    for row in rows:
        source=row['source_occurrences'][0]
        record=records[source['passage_id']]
        text=record['text']
        a,b=source['start'],source['end']
        assert text[a:b]==row['form'] and sha(text.encode())==source['source_text_sha256']
        # Include the actual printed whole line: context without fabricated text.
        start=text.rfind('\n',0,a)+1
        end=text.find('\n',b) if '\n' in text[b:] else len(text)
        body,receipt=api.call('/api/analyze-passage',payload={'version':1,'passage_id':record['id'],
            'start':start,'end':end,'offset_unit':'codepoint','selected_text':text[start:end],
            'rerank':False,'fetch_machine':False})
        assert body['limits']['machine_fetches']==0 and body['ranking']['status']=='not_requested'
        assert body['sense_ranking']['status']=='not_requested' and body['selection']['text']==text[start:end]
        assert body['passage']['text_sha256']==source['source_text_sha256']
        tokens=[t for t in body['tokens'] if t['start']==a and t['end']==b and t['text']==row['form']]
        assert len(tokens)==1
        token=tokens[0]
        displays={t['id']:t for reading in body.get('interlinear',{}).get('readings',[]) for t in reading.get('tokens',[])}
        syntax={(t.get('absolute_start'),t.get('absolute_end')):t for t in body.get('syntax',{}).get('tokens',[])}
        output=occurrence(record,token,displays.get(token['id'],{}),syntax.get((a,b)),receipt,(start,end))
        results.append({'form':row['form'],'before':baseline[source['occurrence_id']],'after':output})
    path=D/'production-api-comparison.json'
    path.write_text(json.dumps({'source_result_sha256':sha((D/'production-results.json').read_bytes()),
        'script_sha256':sha(Path(__file__).read_bytes()),'semantic_accuracy':'not_verified',
        'results':results},ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({'forms':len(results),'cached_ok':sum(r['after']['machine_status']=='ok' for r in results),
        'preferred_gloss_before':sum(r['before']['display_gloss_available'] for r in results),
        'preferred_gloss_after':sum(r['after']['display_gloss_available'] for r in results),
        'sha256':sha(path.read_bytes())}))


if __name__=='__main__':
    main()
