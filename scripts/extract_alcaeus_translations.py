"""Source-backed translation staging; no corpus integration or authored translations.

Download originals, extract CHS HTML, or image-grounded OCR of Edmonds's scan.
Every output retains source hashes. All candidates require independent audit.
"""
from __future__ import annotations

import argparse
import base64
import concurrent.futures
import hashlib
import json
import difflib
import re
from pathlib import Path

import requests
from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'runtime/alcaeus-translations'
CHS = 'https://chs.harvard.edu/lowell-edmunds-deixis-and-everyday-expressions-in-alcaeus-frs-129-v-and-130b-v/'
LICENSE = 'https://chs.harvard.edu/introduction-to-online-publications-2/'
LEAVES = [350,351,352,353,366,367,424,425,426,427]
CROP_BOXES = {350:(180,1900,1610,2670),352:(160,285,1590,660),366:(270,590,1550,1380),
              424:(270,1990,1600,2180),426:(170,265,1610,930)}

def sha(data):
    return hashlib.sha256(data).hexdigest()

def save(name, data):
    path = OUT / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf8')

def fetch(name, url):
    path = OUT / name
    if path.exists():
        receipt = json.loads(path.with_suffix(path.suffix+'.receipt.json').read_text(encoding='utf8'))
        if sha(path.read_bytes()) != receipt['sha256']:
            raise ValueError('cached download hash mismatch: '+name)
        return receipt
    try:
        response = requests.get(url, timeout=90)
        response.raise_for_status()
        if not response.content:
            raise ValueError('empty download')
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(response.content)
        receipt = {'url':url, 'final_url':response.url, 'status':response.status_code,
                   'sha256':sha(response.content), 'bytes':len(response.content),
                   'path':str(path.relative_to(ROOT)).replace('\\','/')}
        save(name+'.receipt.json',receipt)
        return receipt
    except Exception as exc:
        save(name+'.error.json',{'url':url,'error_type':type(exc).__name__,'error':str(exc)})
        raise

def download():
    receipts = [fetch('chs-edmunds.html',CHS),fetch('chs-license.html',LICENSE)]
    rows = [json.loads(x) for x in (ROOT/'data/processed/lyra.jsonl').read_text(encoding='utf8').splitlines()]
    for leaf in LEAVES:
        row = next(r for r in rows if r['id']==f'lyra:lyragraecabeingr01edmouoft:leaf:{leaf}')
        receipt = fetch(f'edmonds-leaf-{leaf}.jpg', row['metadata']['page_image_url'])
        receipt.update({'printed_page':row['metadata']['printed_page'],'scan_leaf':leaf,'page_url':row['metadata']['page_url']})
        receipts.append(receipt)
    save('download-manifest.json',receipts)

def inspect_html():
    soup = BeautifulSoup((OUT/'chs-edmunds.html').read_bytes(),'html.parser')
    for tag in soup(['script','style','nav','header','footer']):tag.decompose()
    # Indexed source blocks are a diagnostic intermediate, not published rows.
    blocks = [{'tag':x.name,'text':x.get_text('\n',strip=True),'html':str(x)} for x in soup.select('p,pre,blockquote')]
    save('chs-blocks.json',blocks)
    for i,block in enumerate(blocks):
        if any(s in block['text'] for s in ['Lesbians','ἀγνοι','ὀ τάλαις','Fr. 129','Fr. 130','I live','Mother of all']):
            print(i,block['tag'],block['text'][:450])

def parse_chs():
    raw=(OUT/'chs-edmunds.html').read_bytes()
    soup=BeautifulSoup(raw,'html.parser')
    nodes=soup.select('.inlineCitation')
    if len(nodes)!=8:raise ValueError('CHS citation structure changed')
    assignments={r['metadata']['assignment_fragment']:r for r in
                 map(json.loads,(ROOT/'runtime/campbell-assignment/campbell_assignment.jsonl').read_text(encoding='utf8').splitlines())}
    rows=[]
    for fragment,gi,ei in [('129',0,1),('130b',2,3)]:
        greek='\n\n'.join(x.get_text().strip() for x in nodes[gi].find_all('pre'))
        source_html=str(nodes[ei])
        english_node=BeautifulSoup(source_html,'html.parser')
        notes=[x.get_text(' ',strip=True) for x in english_node.select('.noteref')]
        for x in english_node.select('.noteref,a[name]'):x.decompose()
        for x in list(english_node.find_all(string=True)):
            x.replace_with(str(x).replace('\r','').replace('\n',' '))
        for x in english_node.select('br'):x.replace_with('\n')
        for x in english_node.select('p'):x.insert_before('\n\n')
        english=english_node.get_text()
        english=re.sub(r'[ \t]+',' ',english)
        english=re.sub(r' *\n *','\n',english)
        english=re.sub(r'\n{3,}','\n\n',english).strip()
        campbell=assignments[fragment]
        # Exact token diff only: neither edition's Greek is silently normalized.
        ca=campbell['text'].split();other=greek.split()
        differences=[{'operation':tag,'campbell_tokens':ca[a:b],'other_edition_tokens':other[c:d],
                      'campbell_token_range':[a,b],'other_token_range':[c,d]}
                     for tag,a,b,c,d in difflib.SequenceMatcher(None,ca,other,autojunk=False).get_opcodes() if tag!='equal']
        rows.append({'id':f'alcaeus-translation:edmunds-chs:{fragment}',
            'author':'Alcaeus','work':'Fragments','kind':'translation','source':'alcaeus_translations_chs',
            'assignment_fragment':fragment,'source_url':CHS,'source_name':soup.title.get_text(strip=True),
            'translator':'Lowell Edmunds','edition':'Greek text and English translation as printed in Lowell Edmunds, Deixis and Everyday Expressions in Alcaeus frs. 129 V and 130b V',
            'citation':f'Fr. {fragment} V','language':'eng','text':english,'paired_greek':greek,
            'source_translation_html':source_html,'source_note_markers':notes,
            'license':'CC BY-NC-ND 3.0 (CHS default publication terms)', 'license_url':LICENSE,
            'reuse_status':'staging_only_noncommercial_unadapted_reuse_required',
            'quality':'source_html_extraction','raw_path':'runtime/alcaeus-translations/chs-edmunds.html',
            'raw_sha256':sha(raw),'source_selectors':{'greek':f'.inlineCitation[{gi}] pre','english':f'.inlineCitation[{ei}]'},
            'campbell_comparison':{'campbell_id':campbell['id'],'campbell_text':campbell['text'],'other_greek_exactly_equal':campbell['text']==greek,'exact_token_differences':differences},
            'alignment_status':'different_edition_do_not_assign_translation_of','translation_of':None})
    save('chs-translation-candidates.json',rows)
    print('Extracted',len(rows),'paired source records; staging only')

OCR_PROMPT = '''Transcribe this scanned page exactly from visible pixels. This is OCR, not translation.
Preserve all polytonic Greek accents, brackets, conjectures, dots, and line breaks.
Do not infer, restore, rewrite, or translate anything. Return JSON with
blocks:[{kind:"verse"|"translation"|"source_prose"|"note"|"heading", text:string}], uncertainty:[string].
Separate the typographic blocks and keep their page order. For English translation,
keep each printed line as a newline; preserve footnote markers as printed.
For unreadable characters use U+FFFD and explain in uncertainty. Do not silently guess.'''

def crop():
    from PIL import Image
    for leaf,box in CROP_BOXES.items():
        original=OUT/f'edmonds-leaf-{leaf}.jpg'
        target=OUT/f'edmonds-leaf-{leaf}.verse-only.png'
        Image.open(original).crop(box).save(target)
        save(target.name+'.receipt.json',{'source_path':original.name,'source_sha256':sha(original.read_bytes()),
            'crop_box_pixels':box,'image_path':target.name,'image_sha256':sha(target.read_bytes())})

def ocr(model, only, verse_only=False):
    from dotenv import load_dotenv
    from openai import OpenAI
    load_dotenv(ROOT/'.env')
    load_dotenv(ROOT/'secrets/nature-gallery.env',encoding='utf-8-sig')
    client = OpenAI(timeout=180,max_retries=0)
    def one(leaf):
        stem=f'edmonds-leaf-{leaf}'+('.verse-only' if verse_only else '')
        raw=OUT/(stem+'.ocr.raw.json')
        if raw.exists():
            if not (OUT/(stem+'.ocr.parsed.json')).exists():
                raise ValueError(stem+' previous response failed; explicit new attempt required')
            return stem+' cached'
        data=(OUT/(stem+('.png' if verse_only else '.jpg'))).read_bytes()
        prompt=OCR_PROMPT if not verse_only else OCR_PROMPT+'\nThis is a tightly bounded crop: transcribe ONLY these printed verse lines, in one verse block; no surrounding notes.'
        save(stem+'.ocr.request.json',{'model':model,'prompt':prompt,'image_sha256':sha(data)})
        response=client.responses.create(model=model,reasoning={'effort':'high'},store=False,
            input=[{'role':'user','content':[{'type':'input_text','text':prompt},
                {'type':'input_image','image_url':'data:image/'+('png' if verse_only else 'jpeg')+';base64,'+base64.b64encode(data).decode(),'detail':'original'}]}],
            text={'format':{'type':'json_object'}},max_output_tokens=6500)
        raw.write_text(response.model_dump_json(indent=2),encoding='utf8')
        if response.status!='completed':
            save(stem+'.ocr.error.json',{'status':response.status,'incomplete_details':response.incomplete_details.model_dump() if response.incomplete_details else None})
            raise ValueError(stem+' incomplete response; see raw receipt')
        parsed=json.loads(response.output_text)
        save(stem+'.ocr.parsed.json',parsed)
        save(stem+'.ocr.receipt.json',{'raw_sha256':sha(raw.read_bytes()),'image_sha256':sha(data),
                                      'parsed_sha256':sha((OUT/(stem+'.ocr.parsed.json')).read_bytes())})
        return stem
    errors=[]
    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
        futures={pool.submit(one,leaf):leaf for leaf in (only or LEAVES)}
        for future in concurrent.futures.as_completed(futures):
            leaf=futures[future]
            try:print(future.result(),flush=True)
            except Exception as exc:
                stem=f'edmonds-leaf-{leaf}'+('.verse-only' if verse_only else '')
                save(stem+'.ocr.error.json',{'error_type':type(exc).__name__,'error':str(exc),'automatic_retries':0})
                errors.append(leaf)
                print('OCR failure',leaf,type(exc).__name__,flush=True)
    if errors:raise RuntimeError('Failed OCR pages; inspect receipts: '+str(errors))

def package_edmonds():
    approval=json.loads((OUT/'edmonds-ocr-audit.json').read_text(encoding='utf8'))
    manifest=json.loads((OUT/'download-manifest.json').read_text(encoding='utf8'))
    assignments={r['metadata']['assignment_fragment']:r for r in
                 map(json.loads,(ROOT/'runtime/campbell-assignment/campbell_assignment.jsonl').read_text(encoding='utf8').splitlines())}
    grouped={}
    for leaf in LEAVES:
        verdict=approval['pages'][str(leaf)]
        name=verdict.get('parsed_file',f'edmonds-leaf-{leaf}.ocr.parsed.json')
        payload=(OUT/name).read_bytes()
        if verdict['parsed_sha256']!=sha(payload):
            raise ValueError('No hash-bound OCR approval: '+name)
        if verdict['verdict']!='PASS':
            if leaf==366 and verdict['verdict']=='FAIL':
                # Vetoed OCR stays in evidence, never in accepted Greek text.
                continue
            raise ValueError('No OCR approval: '+name)
        parsed=json.loads(payload)
        receipt=next(r for r in manifest if r.get('scan_leaf')==leaf)
        for selection in verdict['selections']:
            if selection['verdict']!='PASS':raise ValueError('unapproved block')
            block=parsed['blocks'][selection['block_index']]
            if '\ufffd' in block['text']:raise ValueError('Unreadable target block')
            fragment=selection['fragment']
            grouped.setdefault(fragment,[]).append({'language':selection['language'],'text':block['text'],
                'block_index':selection['block_index'],'ocr_path':'runtime/alcaeus-translations/'+name,
                'ocr_sha256':sha(payload),'image_receipt':receipt,'audit_scope':selection.get('scope','visual comparison')})
    numbers={'34a':'14','326':'37','350':'133'}
    greek_pages={'34a':[350,352],'326':[366],'350':[424,426]}
    caveats={
        '34a':'Edmonds reconstructs a different opening and different wording of the appearance on the forestays. This is not an exact translation of Campbell\'s Greek.',
        '326':'Edmonds ends before the trailing rudder fragment printed in Campbell. Orthography and editorial presentation also differ.',
        '350':'Edmonds prints and translates a long bracketed reconstruction between the first two verses and the final quotation. Preserve brackets; this is not an exact translation of Campbell\'s arrangement.'}
    rows=[]
    for fragment in numbers:
        chunks=grouped[fragment]
        greek='\n'.join(x['text'] for x in chunks if x['language']=='grc')
        english='\n'.join(x['text'] for x in chunks if x['language']=='eng')
        if not english or (not greek and fragment!='326'):raise ValueError('missing paired language')
        greek=greek or None
        ca=assignments[fragment]['text'].split(); other=greek.split() if greek else []
        differences=[{'operation':tag,'campbell_tokens':ca[a:b],'other_edition_tokens':other[c:d],
                      'campbell_token_range':[a,b],'other_token_range':[c,d]}
                     for tag,a,b,c,d in difflib.SequenceMatcher(None,ca,other,autojunk=False).get_opcodes() if tag!='equal'] if greek else None
        rows.append({'id':f'alcaeus-translation:edmonds-1922:{fragment}','assignment_fragment':fragment,
            'author':'Alcaeus','work':'Fragments','kind':'translation','source':'alcaeus_translations_edmonds',
            'translator':'J. M. Edmonds','edition':'Lyra Graeca, vol. I (1922), Loeb Classical Library 28',
            'citation':f'Alcaeus, Edmonds fragment {numbers[fragment]}','source_url':'https://archive.org/details/lyragraecabeingr01edmouoft',
            'language':'eng','text':english,'paired_greek':greek,'source_chunks':chunks,
            'paired_greek_images':[r for r in manifest if r.get('scan_leaf') in greek_pages[fragment]],
            'paired_greek_transcription_status':'audited_source_OCR' if greek else 'withheld_failed_OCR_use_source_scan',
            'license':'Public domain in the United States (1922 edition; IA metadata NOT_IN_COPYRIGHT)',
            'quality':'source_scan_OCR_independently_visually_audited','source_note':caveats[fragment],
            'campbell_comparison':{'campbell_id':assignments[fragment]['id'],'campbell_text':assignments[fragment]['text'],
                'other_greek_exactly_equal':False if greek else None,'exact_token_differences':differences,
                'difference_status':'exact_token_diff' if greek else 'not_computed_unverified_Greek_transcription'},
            'alignment_status':'different_edition_do_not_assign_translation_of','translation_of':None})
    save('edmonds-translation-candidates.json',rows)
    print('Packaged',len(rows),'independently audited cross-edition translations')

def coverage():
    chs=json.loads((OUT/'chs-translation-candidates.json').read_text(encoding='utf8'))
    edmonds=json.loads((OUT/'edmonds-translation-candidates.json').read_text(encoding='utf8'))
    soup=BeautifulSoup((OUT/'chs-edmunds.html').read_bytes(),'html.parser')
    notes=[]
    for number in [27,28,29,30,48,49,50,51]:
        anchor=soup.find('a',attrs={'name':f'n.{number}'})
        if anchor is None:raise ValueError('CHS footnote missing')
        note=BeautifulSoup(str(anchor.parent.parent),'html.parser')
        for x in note.select('.noteref'):x.decompose()
        notes.append({'number':number,'text':note.get_text(' ',strip=True),'source_url':CHS+f'#n.{number}',
                      'raw_sha256':sha((OUT/'chs-edmunds.html').read_bytes())})
    save('chs-source-notes.json',notes)
    rows=edmonds+chs
    (OUT/'translation-candidates.jsonl').write_text(''.join(json.dumps(row,ensure_ascii=False)+'\n' for row in rows),encoding='utf8')
    report={'scope':'staging_only_no_core_corpus_changes',
        'coverage':[{'assignment_fragment':r['assignment_fragment'],'id':r['id'],'translator':r['translator'],
                     'edition':r['edition'],'source_url':r['source_url'],'license':r['license'],
                     'english_word_count':len(r['text'].split()),'paired_greek_present':bool(r['paired_greek']),
                     'paired_greek_scan_present':bool(r.get('paired_greek_images')),
                     'translation_of':r['translation_of'],'alignment_status':r['alignment_status']} for r in rows],
        'translation_count':len(rows),'exact_campbell_translation_count':sum(bool(r['translation_of']) for r in rows),
        'files':[{ 'path':str(p.relative_to(ROOT)).replace('\\','/'),'sha256':sha(p.read_bytes()),'bytes':p.stat().st_size}
                 for p in sorted(OUT.iterdir()) if p.is_file() and p.name!='coverage-manifest.json']}
    save('coverage-manifest.json',report)
    print('Coverage',len(rows),'different-edition translations; exact Campbell alignments',report['exact_campbell_translation_count'])

def ocr_status():
    statuses=[]
    for request in sorted(OUT.glob('*.ocr.request.json')):
        stem=request.name.removesuffix('.ocr.request.json')
        raw=OUT/(stem+'.ocr.raw.json')
        parsed=OUT/(stem+'.ocr.parsed.json')
        entry={'request':request.name,'request_sha256':sha(request.read_bytes()),'parsed_exists':parsed.exists()}
        if raw.exists():
            response=json.loads(raw.read_text(encoding='utf8'))
            entry.update({'response':raw.name,'response_sha256':sha(raw.read_bytes()),
                          'status':response.get('status'),'incomplete_details':response.get('incomplete_details'),
                          'usage':response.get('usage')})
        else:entry['status']='request_without_saved_response'
        statuses.append(entry)
    save('ocr-status.json',statuses)
    for row in statuses:print(row['request'],row['status'],row['parsed_exists'])

if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('phase',choices=['download','inspect-html','parse-chs','ocr','crop','ocr-verse','ocr-status','package-edmonds','coverage'])
    parser.add_argument('--model',default='gpt-5.4')
    parser.add_argument('--only',nargs='*',type=int)
    args=parser.parse_args()
    if args.phase=='download':download()
    elif args.phase=='inspect-html':inspect_html()
    elif args.phase=='parse-chs':parse_chs()
    elif args.phase=='ocr':ocr(args.model,args.only)
    elif args.phase=='crop':crop()
    elif args.phase=='ocr-verse':ocr(args.model,args.only,verse_only=True)
    elif args.phase=='package-edmonds':package_edmonds()
    elif args.phase=='coverage':coverage()
    elif args.phase=='ocr-status':ocr_status()
