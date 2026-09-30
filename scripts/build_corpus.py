"""Build a disposable SQLite search index from preserved collector outputs.

Run from the project root: python scripts/build_corpus.py
The previous index is replaced atomically only after successful validation.
"""
from pathlib import Path
import argparse
import collections
import hashlib
import json
import sqlite3
import sys
import time
import unicodedata

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from backend.textutils import normalize, tokenize

SCHEMA = '''
CREATE TABLE passages (
 id TEXT PRIMARY KEY, work_id TEXT NOT NULL, source TEXT, author TEXT, work TEXT,
 edition TEXT, citation TEXT, language TEXT, kind TEXT, quality TEXT,
 text TEXT NOT NULL, normalized TEXT NOT NULL, data TEXT NOT NULL, sequence INTEGER);
CREATE TABLE works (id TEXT PRIMARY KEY, author TEXT, work TEXT, edition TEXT,
 source TEXT, language TEXT, count INTEGER);
CREATE TABLE tokens (passage_id TEXT, form TEXT, normalized TEXT, count INTEGER);
CREATE TABLE vocabulary (normalized TEXT PRIMARY KEY, form TEXT, count INTEGER);
CREATE TABLE metadata (key TEXT PRIMARY KEY, value TEXT);
CREATE VIRTUAL TABLE passage_fts USING fts5(id UNINDEXED, normalized, citation, author, work,
 tokenize='unicode61 remove_diacritics 0');
'''


def ogc_policy(approval):
    """Load independently checked heuristic labels without turning them into truth."""
    report_path=ROOT/'data/reports/ogc-manual.json'
    if not report_path.exists():
        return {},'quality annotation review missing; reference-only index'
    report=json.loads(report_path.read_text(encoding='utf-8'))
    if report.get('verdict')!='PASS_FOR_LABELED_STAGING' or report.get('input_sha256')!=approval.get('sha256'):
        return {},'quality annotation review stale; reference-only index'
    annotation=report['quality_annotation']
    path=ROOT/annotation['path']
    if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest()!=annotation.get('sha256'):
        return {},'quality annotation file changed; reference-only index'
    policy={}
    with path.open(encoding='utf-8') as stream:
        for line in stream:
            row=json.loads(line)
            policy[row['parent_id']]={
                'eligible':bool(row.get('primary_search_eligible')),
                'block_label':row.get('block_label'),
                'bibliographic_scope':row.get('bibliographic_scope'),
                'flags':row.get('flags',[]),
                'parent_text_sha256':row['parent_text_sha256']}
    return policy,'source reproduction with heuristic quality screening; not passage-level attribution review'


def build(output=ROOT / 'data/corpus.sqlite'):
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_suffix('.building.sqlite')
    if temporary.exists():
        temporary.unlink()  # precisely scoped disposable index from a prior failed run
    con = sqlite3.connect(temporary)
    con.executescript(SCHEMA)
    con.execute('PRAGMA journal_mode=OFF')
    con.execute('PRAGMA synchronous=OFF')
    vocabulary = collections.Counter()
    display_forms = {}
    works = {}
    counts = collections.Counter()
    language_counts=collections.Counter()
    quality_counts=collections.Counter()
    author_labels=set()
    failures = []
    seen = set()
    validated_raw_paths = set()
    started = time.time()
    acceptance_path = ROOT / 'data/reports/audit-acceptance.json'
    if not acceptance_path.exists():
        raise RuntimeError('Independent audit acceptance manifest missing; no data admitted.')
    acceptance = json.loads(acceptance_path.read_text(encoding='utf-8'))['files']
    files = []
    quarantined = []
    for path in sorted((ROOT / 'data/processed').glob('*.jsonl')):
        approval = acceptance.get(path.name,{})
        if approval.get('verdict') != 'PASS':
            quarantined.append({'file':path.name,'reason':'independent audit not PASS'})
        elif hashlib.sha256(path.read_bytes()).hexdigest() != approval.get('sha256'):
            quarantined.append({'file':path.name,'reason':'file changed after independent audit'})
        else:
            files.append(path)
    if not files:
        raise RuntimeError('No independently accepted collector outputs. Index not replaced.')
    ogc_labels,ogc_review=ogc_policy(acceptance.get('ogc.jsonl',{})) if any(p.name=='ogc.jsonl' for p in files) else ({},'not indexed')
    policy_demotions=0
    for path in files:
        file_count = 0
        with path.open(encoding='utf-8-sig') as stream:
            for line_no, line in enumerate(stream, 1):
                if not line.strip():
                    continue
                try:
                    row = json.loads(line)
                    for key in ('id','source','source_url','raw_path','raw_sha256','text'):
                        if not row.get(key):
                            raise ValueError(f'missing required {key}')
                    if row['id'] in seen:
                        raise ValueError(f'duplicate id {row["id"]}')
                    if row['raw_path'] not in validated_raw_paths:
                        raw = (ROOT / row['raw_path']).resolve()
                        if not raw.is_relative_to(ROOT.resolve()) or not raw.is_file():
                            raise ValueError('raw artifact missing or outside project')
                        validated_raw_paths.add(row['raw_path'])
                    if not isinstance(row['text'], str) or not row['text'].strip():
                        raise ValueError('empty/nonstring text')
                except Exception as exc:
                    failures.append({'file':str(path.relative_to(ROOT)),'line':line_no,'error':str(exc)})
                    continue
                seen.add(row['id'])
                # Missing metadata stays visibly unknown; it is never inferred as fact.
                for key in ('author','work','edition','citation','language','license'):
                    row.setdefault(key, 'unknown')
                row.setdefault('kind','reference')
                row.setdefault('quality','needs_review')
                if row['source']=='ogc':
                    screening=ogc_labels.get(row['id'],{})
                    row.setdefault('metadata',{})['index_review']=ogc_review
                    row['metadata']['quality_screening']=screening
                    valid=screening.get('parent_text_sha256')==hashlib.sha256(row['text'].encode('utf-8')).hexdigest()
                    eligible=valid and screening.get('eligible') and screening.get('block_label')=='clean_source_text' and screening.get('bibliographic_scope')=='poetry'
                    if row['kind']=='text' and row['quality']=='source_text' and not eligible:
                        row['metadata']['original_index_classification']={'kind':row['kind'],'quality':row['quality']}
                        row['kind']='reference'
                        row['quality']='needs_review'
                        policy_demotions+=1
                identity = [row.get(k) for k in ('source','author','work','edition','language')]
                work_id = hashlib.sha256(json.dumps(identity,ensure_ascii=False).encode()).hexdigest()[:20]
                row['work_id'] = work_id
                folded = normalize(row['text'])
                sequence = works.get(work_id, {}).get('count',0)
                con.execute('INSERT INTO passages VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
                    (row['id'],work_id,row['source'],row['author'],row['work'],row['edition'],row['citation'],row['language'],row['kind'],row['quality'],row['text'],folded,json.dumps(row,ensure_ascii=False),sequence))
                con.execute('INSERT INTO passage_fts VALUES (?,?,?,?,?)',
                    (row['id'],folded,normalize(row['citation']),normalize(row['author']),normalize(row['work'])))
                if row['quality'] not in ('mixed_content','machine_ocr','needs_review') and row['kind'] in ('text','translation'):
                    tokens = collections.Counter(tokenize(row['text']))
                    con.executemany('INSERT INTO tokens VALUES (?,?,?,?)',[(row['id'],word,normalize(word),n) for word,n in tokens.items()])
                    for word,n in tokens.items():
                        key = normalize(word)
                        vocabulary[key] += n
                        display_forms.setdefault(key,word)
                works.setdefault(work_id,dict(zip(('source','author','work','edition','language'),identity)) | {'count':0})['count'] += 1
                counts[row['source']] += 1
                language_counts[row['language']]+=1
                quality_counts[row['quality']]+=1
                author_labels.add(row['author'])
                file_count += 1
        con.commit()
        if file_count != acceptance[path.name].get('records'):
            con.close()
            raise RuntimeError(f'Accepted record count mismatch for {path.name}: expected {acceptance[path.name].get("records")}, indexed {file_count}; previous index retained.')
        print(f'{path.name}: {file_count:,} indexed',flush=True)
    if failures:
        con.close()
        raise RuntimeError(f'{len(failures)} accepted source rows failed validation; previous index retained.')
    for work_id,work in works.items():
        con.execute('INSERT INTO works VALUES (?,?,?,?,?,?,?)',(work_id,work['author'],work['work'],work['edition'],work['source'],work['language'],work['count']))
    con.executemany('INSERT INTO vocabulary VALUES (?,?,?)',[(key,display_forms[key],count) for key,count in vocabulary.items()])
    con.executescript('''CREATE INDEX idx_passage_work ON passages(work_id,sequence);
      CREATE INDEX idx_passage_author ON passages(author);
      CREATE INDEX idx_parent ON passages(json_extract(data,'$.parent_id'));
      CREATE INDEX idx_source_scope ON passages(json_extract(data,'$.source_url'),json_extract(data,'$.metadata.scope'));
      CREATE INDEX idx_token_normal ON tokens(normalized);
      CREATE INDEX idx_token_passage ON tokens(passage_id);''')
    manifest = {'passages':sum(counts.values()),'works':len(works),'sources':dict(counts),
        'vocabulary':len(vocabulary),'files':[str(p.relative_to(ROOT)) for p in files],
        'ogc_policy':ogc_review,'ogc_policy_demotions':policy_demotions,
        'rejected':failures,'quarantined':quarantined,'built_at':time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime()),
        'elapsed_seconds':round(time.time()-started,2)}
    manifest['statistics']={
        'languages':[{'language':key,'count':count} for key,count in language_counts.most_common()],
        'quality':[{'quality':key,'count':count} for key,count in sorted(quality_counts.items())],
        'sources':[{'source':key,'count':count} for key,count in sorted(counts.items())],
        'authors':len({unicodedata.normalize('NFC',unicodedata.normalize('NFC',label).casefold()) for label in author_labels}),
        'author_labels':len(author_labels)}
    con.execute('INSERT INTO metadata VALUES (?,?)',('manifest',json.dumps(manifest)))
    con.commit()
    con.close()
    if not manifest['passages']:
        raise RuntimeError('No valid passages. Previous index retained.')
    temporary.replace(output)
    report = ROOT / 'data/reports/index.json'
    report.parent.mkdir(parents=True,exist_ok=True)
    report.write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({k:v for k,v in manifest.items() if k != 'rejected'},ensure_ascii=False),flush=True)
    print(f'Rejected records: {len(failures)} (see data/reports/index.json)',flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--output',default=str(ROOT/'data/corpus.sqlite'))
    build(parser.parse_args().output)
