"""Local-only Melos API. Run: python -m uvicorn backend.server:app --port 8791"""
from pathlib import Path
from functools import lru_cache
from contextlib import closing
import collections
import difflib
import hashlib
import hmac
import json
import os
import re
import secrets
import sqlite3
import threading
import unicodedata

import numpy as np
from fastapi import FastAPI, HTTPException, Query, Request
from pydantic import BaseModel, Field
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware

from .textutils import normalize as basic_normalize, tokenize
from .publication import publication_restricted, public_deployment, corpus_views, EVIDENCE_HOLD, WIKTIONARY_HOLD
from .author_aliases import (canonical as canonical_author, canonical_key, component_keys,
                             merged_labels, is_mixed as mixed_author_label, fold as fold_author,
                             profile as alias_record)
from .textutils import text_key as passage_text_key

ROOT = Path(__file__).resolve().parents[1]
DB = ROOT / 'data/corpus.sqlite'
app = FastAPI(title='Melos Greek Lyric Lexicon',version='0.4.0')
# Quality labels searched by default; the reference toggle adds the rest.
SEARCHABLE_QUALITIES = ('source_text','machine_corrected_ocr')
QUALITY_SQL = "('source_text','machine_corrected_ocr')"
MIRROR_SEPARATOR = '\x1f'


def legacy_schema():
    """True while the index predates author_canonical, text_key and passage_authors.

    The API keeps working on such an index: authors still merge through SQL
    functions over the raw label, but identical copies are not grouped until
    the index is rebuilt or upgraded (scripts/migrate_corpus_schema.py).
    """
    try:
        info=DB.stat()
    except OSError:
        return False
    return not schema_ready(info.st_mtime_ns,info.st_size)


def group_columns():
    """Columns that identify one text copy group; each row is its own group on an old index.

    Copies group only within one quality label, so an OCR duplicate of an
    edited text stays a separate, labelled record when reference material is
    included.
    """
    return 'id' if legacy_schema() else 'author_canonical,text_key,quality'


def text_columns():
    """Columns that identify one text regardless of quality label.

    Relevance ranks are shared at this level so an edited copy and an OCR copy
    of the same words sit together, ordered by preference, instead of being
    separated by full-text length effects of unrelated columns.
    """
    return 'id' if legacy_schema() else 'author_canonical,text_key'


def canonical_expr():
    """SQL expression for the merged author name of a passages row."""
    return 'author_canonical_key(author)' if legacy_schema() else 'author_canonical'


def grouping(representative):
    """Window expression that groups identical copies of one text (same canonical
    author, language, kind and words) and keeps the collapsed IDs visible."""
    cols=group_columns()
    return (f'ROW_NUMBER() OVER (PARTITION BY {cols} ORDER BY {representative}) rn,'
            f'COUNT(*) OVER (PARTITION BY {cols}) copies,'
            f'group_concat(id,char(31)) OVER (PARTITION BY {cols}) copy_ids')


def search_row_columns(alias='p'):
    """Carry only ranking/identity columns through grouping, never source JSON.

    Source records can contain large commentary/apparatus payloads. Sorting
    p.* for every window and again for a count can exhaust bounded SQLite
    temporary storage even when the requested result page is small.
    """
    columns=['id','source','author','work','language','quality','sequence']
    if not legacy_schema():
        columns+=['author_canonical','text_key']
    return ','.join(f'{alias}.{column}' for column in columns)


def count_search_groups(con,cte,params):
    """Count mirror groups without executing representative/ranking windows."""
    columns=group_columns()
    return con.execute(cte+f'SELECT count(*) FROM (SELECT {columns} FROM matched GROUP BY {columns})',params).fetchone()[0]


def fetch_search_page(con,cte,ordering,params,limit,offset):
    """Hydrate the complete source record only after grouping and pagination."""
    return con.execute(cte+'SELECT (SELECT payload.data FROM passages payload WHERE payload.id=selected.id) data,selected.* '
                       'FROM (SELECT * FROM grouped WHERE rn=1 ORDER BY '+ordering+' LIMIT ? OFFSET ?) selected '
                       'ORDER BY '+ordering,params+[limit,offset]).fetchall()
# The static Vercel frontend may use a separately hosted read-only corpus API.
# An empty list keeps the local same-origin default. Never allow credentialed
# wildcard origins, and keep hosted classifier secrets exclusively server-side.
cors_origins=[origin.strip().rstrip('/') for origin in os.environ.get('MELOS_CORS_ORIGINS','').split(',') if origin.strip()]
if cors_origins:
    app.add_middleware(CORSMiddleware,allow_origins=cors_origins,
                       allow_credentials=False,allow_methods=['GET','POST'],
                       allow_headers=['Content-Type','Accept'])


@app.middleware('http')
async def request_policy(request,call_next):
    from .jev_gateway import public_enabled
    visitor_cookie = None
    if request.url.path=='/api/classify-context' and request.method=='POST':
        client=request.client.host if request.client else ''
        if (public_deployment() or client not in ('127.0.0.1','::1','testclient')) and not public_enabled():
            return JSONResponse(status_code=403,content={'detail':'Contextual classification is local-only unless public Jev is explicitly enabled.'})
        if public_enabled():
            if not (os.environ.get('TYPESAFE_API_KEY') or os.environ.get('JEV_API_KEY')):
                return JSONResponse(status_code=503,content={'detail':'Jev is not configured on this server.'})
            try:
                size = int(request.headers.get('content-length', '-1'))
            except ValueError:
                size = -1
            if size < 0 or size > 2048:
                return JSONResponse(status_code=413,content={'detail':'A JSON request of at most 2048 bytes is required.'})
            if request.headers.get('content-type','').split(';')[0].strip() != 'application/json':
                return JSONResponse(status_code=415,content={'detail':'Use application/json.'})
            # Browser sessions are convenience throttles, not authenticated users.
            # Never trust spoofable forwarding headers; the durable global quota
            # bounds spending even if visitors reset cookies or bypass Vercel.
            key = (os.environ.get('TYPESAFE_API_KEY') or os.environ['JEV_API_KEY']).encode()
            cookie = request.cookies.get('melos_visitor','')
            token, _, signature = cookie.partition('.')
            valid = bool(re.fullmatch(r'[0-9a-f]{32}', token)) and hmac.compare_digest(
                signature, hmac.new(key, token.encode(), hashlib.sha256).hexdigest())
            if not valid:
                token = secrets.token_hex(16)
                visitor_cookie = token + '.' + hmac.new(key, token.encode(), hashlib.sha256).hexdigest()
            request.state.classifier_visitor = hashlib.sha256(token.encode()).hexdigest()
    response=await call_next(request)
    if visitor_cookie:
        response.set_cookie('melos_visitor',visitor_cookie,max_age=2592000,
                            httponly=True,secure=public_deployment(),samesite='lax',path='/api')
    if response.status_code==200 and re.fullmatch(r'/assets/paintings/[^/]+\.[0-9a-f]{8}\.(?:avif|webp)',request.url.path):
        response.headers['Cache-Control']='public, max-age=31536000, immutable'
    elif request.url.path.startswith('/api/'):
        response.headers['Cache-Control']='no-store'
    elif request.url.path.startswith(('/js/','/css/')) or request.url.path in ('/','/reader.html','/index.html','/legacy'):
        response.headers['Cache-Control']='no-cache'
    return response


_service_lock = threading.Lock()


class ReadConnection(sqlite3.Connection):
    """Release Windows file handles after each request, not merely transactions."""
    def __exit__(self,*args):
        try:
            return super().__exit__(*args)
        finally:
            self.close()


@lru_cache(maxsize=256)
def phrase_pattern(query):
    literal = r'\s+'.join(re.escape(t) for t in query.split())
    greek = any(c.isalpha() and ('\u0370' <= c <= '\u03ff' or '\u1f00' <= c <= '\u1fff') for c in query)
    if not greek:
        # Preserve ordinary English/Latin wording and quoted descriptions.
        # Romanized Greek also supplies Greek query variants below this layer.
        return re.compile(r'(?<!\w)' + literal + r'(?!\w)')
    # Callers supply folded keys (all recognized apostrophes become ASCII).
    # Do not match a bare stem inside an elided form or the second half of an
    # internal-apostrophe word. An orphan leading quote remains punctuation.
    # Attached terminal signs are literal: we do not guess quote vs. elision.
    ending = r'(?!\w)' if query.endswith(("'", '᾿')) else r"(?![\w'᾿])"
    return re.compile(r"(?<!\w)(?<!\w['᾿])" + literal + ending)


def author_key(label):
    """Canonical Unicode plus case equivalence, never an inferred identity."""
    return unicodedata.normalize('NFC',unicodedata.normalize('NFC',str(label or '')).casefold())


def author_labels(label):
    """Every spelling merged with this label: the owner alias table plus audited profile aliases."""
    try:
        from .authors import equivalent_labels
        labels=equivalent_labels(label,path=ROOT/'data/metadata/p2-author-profiles.json',
                                 claim_path=ROOT/'data/claims/p2_authors.jsonl',
                                 acceptance_path=ROOT/'data/reports/p2-claim-acceptance.json')
    except (ImportError,OSError,ValueError,RuntimeError):
        labels=[]
    return list(dict.fromkeys([label,*merged_labels(label),*labels]))


def author_filter_keys(label):
    """Keys in passage_authors that an author filter should match.

    A single poet's label matches its canonical key (so every merged spelling
    answers). A joint label such as ``Sappho / Alcaeus`` used as a filter
    matches only records carrying that exact joint label.
    """
    if not label:
        return []
    if mixed_author_label(label):
        return [fold_author(label)]
    keys=[]
    for item in author_labels(label):
        for key in component_keys(item):
            if key not in keys:
                keys.append(key)
    return keys


def author_member_clause(keys):
    """SQL test that a passages row (by table alias) belongs to one of the author keys.

    On the current schema this is an indexed membership test in passage_authors;
    on an older index it evaluates the alias table over the raw label per row.
    Both bind exactly len(keys) parameters.
    """
    if legacy_schema():
        return lambda alias: '('+' OR '.join(f'author_has_key({alias}.author,?)' for _ in keys)+')'
    marks=','.join('?' for _ in keys)
    return lambda alias: f'{alias}.id IN (SELECT passage_id FROM passage_authors WHERE author_key IN ({marks}))'


def mirror_pref(source,quality):
    """Lower is shown first among identical copies: edited text over OCR, a direct collector over an aggregator mirror."""
    return {'source_text':0,'machine_corrected_ocr':1}.get(quality,3)*10+{'ogc':2,'p2_ogc':2,'ogc_derived':3}.get(source,0)


@lru_cache(maxsize=4)
def schema_ready(stamp,size):
    with closing(sqlite3.connect(f'file:{DB.as_posix()}?mode=ro',uri=True)) as probe:
        columns={row[1] for row in probe.execute('PRAGMA table_info(passages)')}
        tables={row[0] for row in probe.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    return 'text_key' in columns and 'author_canonical' in columns and 'passage_authors' in tables


def connect():
    if not DB.exists():
        raise HTTPException(503,'Corpus index is not built yet. Run python scripts/build_corpus.py after collection.')
    con = sqlite3.connect(f'file:{DB.as_posix()}?mode=ro',uri=True,factory=ReadConnection)
    con.row_factory = sqlite3.Row
    con.create_function('phrase_match',2,lambda text,query: bool(query and phrase_pattern(query).search(text or '')),deterministic=True)
    con.create_function('author_key',1,author_key,deterministic=True)
    con.create_function('mirror_pref',2,mirror_pref,deterministic=True)
    con.create_function('author_canonical_key',1,canonical_key,deterministic=True)
    con.create_function('author_has_key',2,lambda label,key: key in component_keys(label),deterministic=True)
    if publication_restricted():
        corpus_views(con, DB)
    return con


def with_mirrors(record,row):
    """Attach the collapsed copies of a grouped search row to its representative record."""
    ids=[value for value in str(row['copy_ids'] or '').split(MIRROR_SEPARATOR) if value and value!=record['id']]
    record['mirror_count']=int(row['copies'] or 1)
    record['mirrored_ids']=sorted(ids)
    return record


def unpack(row):
    if not row:
        return None
    record=json.loads(row['data'])
    chronology=author_chronology(record.get('author',''))
    if chronology:
        record['author_chronology']=chronology
    return record


@lru_cache(maxsize=4)
def chronology_map(stamp):
    path=ROOT/'data/metadata/chronology.json'
    if not path.exists():
        return {}
    records=json.loads(path.read_text(encoding='utf-8')).get('authors',[])
    lookup={}
    for row in records:
        value=row.get('author_chronology')
        if not value:
            continue
        aliases=[row.get(k) for k in ('site_author','source_author','source_native_label')]+row.get('source_aliases_en',[])
        for alias in aliases:
            if alias:
                lookup[basic_normalize(alias)]=value
    return lookup


def author_chronology(author):
    path=ROOT/'data/metadata/chronology.json'
    return chronology_map(path.stat().st_mtime_ns if path.exists() else 0).get(basic_normalize(author))


def order_results(results,order):
    if order=='chronological':
        return sorted(results,key=lambda r:((r.get('author_chronology') or {}).get('sort_year') if (r.get('author_chronology') or {}).get('sort_year') is not None else 99999,r.get('author','')))
    return results


def variants(q):
    try:
        from .morphology import query_variants
        return [key for key in dict.fromkeys([basic_normalize(q)]+query_variants(q)) if key][:12]
    except ImportError:
        return [basic_normalize(q)]


def filters(author='',language='',edition='',include_reference=False, alias='p'):
    clauses, values = [], []
    if author:
        keys=author_filter_keys(author)
        member=author_member_clause(keys)
        # Keep translator/commentator authorship. A translation answers to a
        # poet only through an explicit Greek parent, never a shared page.
        clauses.append(f'''({member(alias)} OR ({alias}.kind IN ('commentary','translation') AND (
            EXISTS (SELECT 1 FROM passages parent
                    WHERE parent.id=json_extract({alias}.data,'$.parent_id')
                      AND parent.kind='text' AND parent.language='grc'
                      {'' if include_reference else 'AND parent.quality IN '+QUALITY_SQL} AND {member('parent')})
            OR ({alias}.kind='commentary' AND json_extract({alias}.data,'$.metadata.scope') IN ('page','source_section') AND
                EXISTS (SELECT 1 FROM passages page_text
                        WHERE json_extract(page_text.data,'$.source_url')=json_extract({alias}.data,'$.source_url')
                          AND page_text.source={alias}.source AND page_text.kind='text'
                          AND {member('page_text')})))))''')
        values.extend(keys*3)
    for col,value in [('language',language),('edition',edition)]:
        if value:
            clauses.append(f'{alias}.{col}=?')
            values.append(value)
    if not include_reference:
        clauses += [f"{alias}.quality IN {QUALITY_SQL}",f"{alias}.kind IN ('text','translation','commentary')"]
    return (' AND '+ ' AND '.join(clauses) if clauses else ''), values


@lru_cache(maxsize=8)
def file_digest(path,stamp,size):
    with open(path,'rb') as stream:
        return hashlib.file_digest(stream,'sha256').hexdigest()


@lru_cache(maxsize=1)
def _morph_service(entries_stamp,forms_stamp,public=False):
    from .morphology import Morphology
    return Morphology(entries_path=ROOT/'data/lexica/entries.jsonl',forms_path=ROOT/'data/lexica/forms.jsonl')


def morph_service():
    report=ROOT/'data/reports/audit-lexica.json'
    if not report.exists():
        raise RuntimeError('Dictionary extraction is awaiting independent source checks.')
    audit=json.loads(report.read_text(encoding='utf-8'))
    stamps=[]
    for name in ('entries.jsonl','forms.jsonl'):
        path=ROOT/'data/lexica'/name
        accepted=audit.get('files',{}).get(name,{})
        if accepted.get('verdict')!='PASS' or not path.exists():
            raise RuntimeError('Dictionary extraction is awaiting independent source checks.')
        info=path.stat()
        digest=file_digest(str(path),info.st_mtime_ns,info.st_size)
        if digest!=accepted.get('sha256'):
            raise RuntimeError('Dictionary source files changed since their audit; revalidation is required.')
        stamps.append(info.st_mtime_ns)
    with _service_lock:
        service=_morph_service(*stamps,publication_restricted())
        service.counts()  # complete the one-time lazy load before concurrent lookups
        return service


@lru_cache(maxsize=1)
def semantic_service():
    from .semantic import SemanticIndex
    return SemanticIndex(ROOT/'data/embeddings')


def safe_error(exc):
    return str(exc).replace(str(ROOT),'[project]').replace(ROOT.as_posix(),'[project]')


@lru_cache(maxsize=2)
def _evidence_index(path,stamp,size):
    from .evidence import EvidenceIndex
    service=EvidenceIndex(path)
    return service,service.provenance()


def evidence_service():
    if publication_restricted():
        raise RuntimeError(EVIDENCE_HOLD)
    path=ROOT/'data/evidence.sqlite'
    info=path.stat()
    service,provenance=_evidence_index(str(path),info.st_mtime_ns,info.st_size)
    audit=json.loads((ROOT/'data/reports/p2-claim-acceptance.json').read_text(encoding='utf-8'))
    for row in provenance['files']:
        approval=audit.get('files',{}).get(row['name'],{})
        source=ROOT/'data/claims'/row['name']
        source_info=source.stat()
        digest=file_digest(str(source),source_info.st_mtime_ns,source_info.st_size)
        if (approval.get('verdict')!='PASS' or approval.get('sha256')!=row['sha256']
                or digest!=row['sha256']):
            raise RuntimeError('Structured evidence changed since its audited index snapshot; revalidation/rebuild is required.')
    return service


def evidence_lookup(form='',passage_id='',claim_id='',limit=30):
    try:
        service=evidence_service()
        if claim_id:
            result=service.related_claims(claim_id,limit=limit)
        elif form:
            result=service.lookup(form,passage_id=passage_id or None,limit=limit)
        else:
            result=service.get_passage_claims(passage_id,limit=limit)
        return {'ready':True,**result}
    except (ImportError,OSError,RuntimeError,sqlite3.Error) as exc:
        return {'ready':False,'claims':[],'total':0,'warnings':[safe_error(exc)]}


@app.get('/api/evidence')
def evidence(form:str='',passage_id:str='',claim_id:str='',limit:int=Query(30,ge=1,le=100)):
    return evidence_lookup(form[:200],passage_id[:500],claim_id[:500],limit)


@app.get('/api/claim')
def claim(id:str):
    try:
        result=evidence_service().get_claim(id[:500])
    except (ImportError,AttributeError,OSError,RuntimeError,sqlite3.Error) as exc:
        raise HTTPException(503,safe_error(exc)) from None
    if not result:
        raise HTTPException(404,'Claim not found')
    return result


def classifier_status():
    try:
        from .classifier import provider_status
        from .jev_gateway import public_enabled
        if public_deployment() and not public_enabled():
            return {'configured':False,'reason':'Public Jev comparison is disabled by the server operator.'}
        return provider_status()
    except (ImportError,OSError,RuntimeError) as exc:
        return {'configured':False,'reason':safe_error(exc)}


def author_profile(label):
    if publication_restricted():
        return None
    try:
        from .authors import lookup_author
        return lookup_author(label,path=ROOT/'data/metadata/p2-author-profiles.json',
                             claim_path=ROOT/'data/claims/p2_authors.jsonl',
                             acceptance_path=ROOT/'data/reports/p2-claim-acceptance.json')
    except (ImportError,OSError,ValueError):
        return None


@lru_cache(maxsize=1)
def _wiktionary_service(stamps):
    from .wiktionary import WiktionaryLookup
    return WiktionaryLookup()


@app.get('/api/wiktionary')
def wiktionary(form:str='',limit:int=Query(8,ge=1,le=20)):
    """Separate listed-form references; never promoted to corpus attestations."""
    query=form.strip()[:200]
    if publication_restricted():
        return {'ready':False,'query':query,'results':[],'total':0,'warnings':[WIKTIONARY_HOLD]}
    if not query:
        return {'ready':False,'query':query,'results':[],'total':0,'warnings':['Enter a Greek form or transliteration.']}
    paths=[ROOT/'data/lexica/wiktionary-entries.jsonl',
           ROOT/'data/reports/wiktionary-audit.json',ROOT/'data/wiktionary.sqlite']
    stamps=tuple((path.stat().st_mtime_ns,path.stat().st_size) if path.exists() else (0,0) for path in paths)
    try:
        with _service_lock:
            service=_wiktionary_service(stamps)
            result=service.lookup(query,limit=limit)
        return {'ready':True,**result}
    except (ImportError,RuntimeError,OSError) as exc:
        return {'ready':False,'query':query,'results':[],'total':0,
                'warnings':['Wiktionary references are not yet available for this audited snapshot.',
                            str(exc).replace(str(ROOT),'[project]').replace(ROOT.as_posix(),'[project]')]}


@app.get('/api/status')
def status():
    if not DB.exists():
        return {'passages':0,'authors':0,'author_labels':0,'works':0,'sources':[],'languages':[],
                'embeddings':{'ready':False},'warnings':['Collectors are running; the corpus index has not yet been built.']}
    info=DB.stat()
    manifest,langs,sources,authors,labels_count,quality=corpus_statistics(str(DB),info.st_mtime_ns,info.st_size,publication_restricted())
    embedding = {'ready':False}
    try:
        embedding=semantic_service().status
        if publication_restricted():
            embedding={**embedding,'count_scope':'Private index size; public results are filtered by publication policy.'}
    except (ImportError,OSError,ValueError):
        pass
    try:
        evidence_status={'ready':True,**evidence_service().provenance()}
    except (ImportError,OSError,RuntimeError,sqlite3.Error) as exc:
        evidence_status={'ready':False,'claims':0,'warning':safe_error(exc)}
    return {'passages':manifest['passages'],'authors':authors,'author_labels':labels_count,'works':manifest['works'],
            'sources':sources,'languages':langs,'embeddings':embedding,'quality':quality,
            'evidence':evidence_status,'classifier':classifier_status(),
            'publication_policy':('restricted' if publication_restricted() else 'source-labels') if public_deployment() else 'local',
            'searchable_qualities':list(SEARCHABLE_QUALITIES),'schema':manifest.get('schema',1),
            'mirror_grouping':not legacy_schema(),
            'built_at':manifest.get('built_at'),'warnings':[
                'Edition text is not a claim of manuscript certainty. Editorial supplements remain in the source text.',
                'Machine-corrected OCR is searchable and labelled as such; raw OCR, mixed and review-needed material needs the reference toggle.',
                'Author labels are merged by the owner alias table; each record keeps its original source label.',
                'Similarity retrieves candidates for comparison, not proof of literary influence.']
                + (['Index predates mirror grouping; identical copies are listed separately until the index is upgraded.'] if legacy_schema() else [])
                + ([EVIDENCE_HOLD,WIKTIONARY_HOLD] if publication_restricted() else [])}


@lru_cache(maxsize=2)
def corpus_statistics(path,stamp,size,public=False):
    """Large corpus scans run once per published index, never on every UI load."""
    with connect() as con:
        manifest=json.loads(con.execute("SELECT value FROM metadata WHERE key='manifest'").fetchone()[0])
        summary=manifest.get('statistics')
        if summary and not publication_restricted():
            return (manifest,summary['languages'],summary['sources'],summary['authors'],
                    summary['author_labels'],summary['quality'])
        if publication_restricted():
            manifest = dict(manifest,passages=con.execute('SELECT count(*) FROM passages').fetchone()[0],
                            works=con.execute('SELECT count(*) FROM works').fetchone()[0])
        langs=[dict(r) for r in con.execute('SELECT language,count(*) count FROM passages GROUP BY language ORDER BY count DESC')]
        sources=[dict(r) for r in con.execute('SELECT source,count(*) count FROM passages GROUP BY source')]
        authors=con.execute(f'SELECT count(DISTINCT author_key({canonical_expr()})) FROM passages').fetchone()[0]
        labels_count=con.execute('SELECT count(DISTINCT author) FROM passages').fetchone()[0]
        quality=[dict(r) for r in con.execute('SELECT quality,count(*) count FROM passages GROUP BY quality')]
        return manifest,langs,sources,authors,labels_count,quality


@app.get('/api/authors')
def authors():
    with connect() as con:
        rows = con.execute('SELECT author,count(*) count FROM passages GROUP BY author ORDER BY author COLLATE NOCASE,author').fetchall()
    merged={}
    for row in rows:
        label=row['author']
        alias=alias_record(label)
        identity=author_profile(label)
        # The owner alias table decides grouping and display for every label it
        # knows; an audited identity profile merges only labels the table does
        # not cover, and is reported alongside either way.
        if alias:
            key,display='alias:'+canonical_key(label),alias['canonical']
        elif identity:
            key,display='identity:'+identity['id'],identity.get('display_name',label)
        else:
            key,display='label:'+author_key(label),label
        if key not in merged:
            merged[key]={'author':display,'count':0,'labels':[],'identity_id':None}
        merged[key]['count']+=row['count']
        merged[key]['labels'].append(label)
        if identity and not merged[key]['identity_id']:
            merged[key]['identity_id']=identity['id']
    for item in merged.values():
        item['merged']=len(item['labels'])>1
    return {'authors':sorted(merged.values(),key=lambda item:fold_author(item['author'])),
            'method':'Author labels merged by the owner alias table (backend/author_aliases.json) and audited identity profiles; joint labels stay separate.'}


@app.get('/api/works')
def works(author: str=''):
    keys=author_filter_keys(author) if author else []
    with connect() as con:
        if author and legacy_schema():
            where=' WHERE ('+' OR '.join('author_has_key(author,?)' for _ in keys)+')'
        elif author:
            where=' WHERE id IN (SELECT DISTINCT work_id FROM passages WHERE '+author_member_clause(keys)('passages')+')'
        else:
            where=''
        # Ordered through the SQL function so the publication-policy view of
        # works (which lacks the stored column) sorts the same way.
        rows = con.execute('SELECT * FROM works'+where+' ORDER BY author_canonical_key(author),author,work,edition,language',keys).fetchall()
    return {'works':[dict(r)|{'author_canonical':canonical_author(r['author'])} for r in rows]}


@app.get('/api/passages')
def passages(work_id: str='',offset:int=0,limit:int=Query(20,ge=1,le=100)):
    with connect() as con:
        where = ' WHERE work_id=?' if work_id else f" WHERE kind='text' AND language='grc' AND quality IN {QUALITY_SQL}"
        args = [work_id] if work_id else []
        total = con.execute('SELECT count(*) FROM passages'+where,args).fetchone()[0]
        rows = con.execute('SELECT data FROM passages'+where+' ORDER BY sequence,id LIMIT ? OFFSET ?',args+[limit,max(offset,0)]).fetchall()
    return {'results':[unpack(r) for r in rows],'total':total}


@app.get('/api/passage')
def passage(id: str):
    with connect() as con:
        row = con.execute('SELECT * FROM passages WHERE id=?',(id,)).fetchone()
        if not row:
            raise HTTPException(404,'Passage not found')
        result = unpack(row)
        for label,operator,ordering in [('previous_id','<','DESC'),('next_id','>','ASC')]:
            neighbor = con.execute(f'SELECT id FROM passages WHERE work_id=? AND sequence{operator}? ORDER BY sequence {ordering} LIMIT 1',(row['work_id'],row['sequence'])).fetchone()
            result[label] = neighbor[0] if neighbor else None
        # Explicit collector links take priority; citation equality is only a related
        # edition candidate, not a claim that two fragment numbering systems agree.
        related = con.execute("SELECT data FROM passages WHERE id<>? AND (json_extract(data,'$.parent_id')=? OR id=? OR (source=? AND json_extract(data,'$.source_url')=? AND json_extract(data,'$.metadata.scope') IN ('page','source_section'))) LIMIT 50",(id,id,result.get('parent_id',''),result.get('source',''),result.get('source_url',''))).fetchall()
        result['related'] = [unpack(r) for r in related]
        # Other indexed copies of exactly this text (aggregator mirrors or
        # editions printing the same words), listed so none is hidden.
        if legacy_schema():
            copies=[]
        else:
            copies = con.execute('SELECT data FROM passages WHERE author_canonical=? AND text_key=? AND quality=? AND id<>? ORDER BY mirror_pref(source,quality),id LIMIT 25',(row['author_canonical'],row['text_key'],row['quality'],id)).fetchall()
        result['mirrors'] = [{key:record.get(key) for key in ('id','source','author','work','edition','citation','language','kind','quality','license','source_url')}
                             for record in (json.loads(r['data']) for r in copies)]
    result['author_canonical']=canonical_author(row['author'])
    result['structured_evidence']=evidence_lookup(passage_id=id)
    result['author_profile']=author_profile(result.get('author',''))
    return result


def occurrences(keys,author='',limit=30,con=None):
    if not keys:
        return []
    own = con is None
    con = con or connect()
    marks = ','.join('?' for _ in keys)
    sql = f'SELECT DISTINCT p.data FROM passages p JOIN tokens t ON t.passage_id=p.id WHERE t.normalized IN ({marks})'
    params = list(keys)
    if author:
        labels=author_filter_keys(author)
        sql += ' AND '+author_member_clause(labels)('p')
        params.extend(labels)
    sql += " ORDER BY CASE WHEN p.language='grc' THEN 0 ELSE 1 END,p.author,p.work,p.sequence LIMIT ?"
    try:
        return [unpack(r) for r in con.execute(sql,params+[limit])]
    finally:
        if own:
            con.close()


@app.get('/api/word')
def word(form: str, passage_id: str=''):
    context = None
    if passage_id:
        with connect() as con:
            context = unpack(con.execute('SELECT data FROM passages WHERE id=?',(passage_id,)).fetchone())
    try:
        service = morph_service()
        result = service.analyze(form,passage=context,occurrence_lookup=lambda key,limit=30:occurrences([key],limit=limit))
    except (ImportError,RuntimeError) as exc:
        result = {'form':form,'normalized':basic_normalize(form),'candidates':[],
                  'method':'Exact source occurrences only','warnings':[str(exc)]}
    result['context'] = context
    result['author_profile'] = author_profile(context.get('author','')) if context else None
    result['occurrences'] = occurrences(variants(form),limit=30)
    result['structured_evidence'] = evidence_lookup(form,passage_id,limit=100)
    occurrence_parses=[claim for claim in result['structured_evidence'].get('claims',[])
                       if claim.get('predicate')=='morphology' and claim.get('status')=='source_claim'
                       and claim.get('strength') in ('explicit_passage_span','explicit_passage_link')]
    result['context_analysis_status']='source_statement_available' if occurrence_parses else 'unresolved'
    result['generic_lookup_warnings']=list(result.get('warnings',[]))
    if occurrence_parses:
        result['warnings']=[
            'A source-stated grammatical analysis is linked to this passage. General lexicon/treebank alternatives below remain separate.'
        ]
    try:
        source_candidates=evidence_service().candidate_analyses(form,passage_id=passage_id or None,limit=100)
        result['contextual_candidates'] = source_candidates.get('candidates',[])
        result['contextual_candidate_method'] = source_candidates.get('method')
    except (ImportError,AttributeError,OSError,RuntimeError,sqlite3.Error):
        result['contextual_candidates'] = []
    result['parallel_contexts'] = []
    if context and context.get('author'):
        from .parallel_context import matching_texts, source_claim_matches
        pool=occurrences(variants(form),author=context['author'],limit=1000)
        matched=matching_texts(form,context,pool,author_labels(context['author']))
        try:
            evidence=evidence_service()
            for match in matched:
                parallel=match['passage']
                found=evidence.lookup(form,passage_id=parallel['id'],limit=100)
                linked=[claim for claim in found['claims'] if claim.get('strength') in
                        ('explicit_passage_span','explicit_passage_link') and source_claim_matches(claim,parallel,form)]
                if not linked:
                    continue
                identifiers={claim['id'] for claim in linked}
                projected=evidence.candidate_analyses(form,passage_id=parallel['id'],limit=100)
                candidates=[]
                for candidate in projected['candidates']:
                    if not identifiers.intersection(candidate.get('claim_ids',[])):
                        continue
                    candidates.append({**candidate,'original_source_strength':candidate['strength'],
                        'strength':'parallel_matching_text','source_passage_id':parallel['id'],
                        'comparison_scope':match['alignment']['scope'],
                        'comparison_context':match['alignment'],
                        'match_reason':'Source analysis belongs to another indexed reading text with an identical complete word sequence; compare its edition and editorial signs.'})
                result['parallel_contexts'].append({
                    'passage':{key:parallel.get(key) for key in ('id','author','work','citation','edition','source_url')},
                    'alignment':match['alignment'],'claims':linked,'candidates':candidates})
                if len(result['parallel_contexts']) >= 10:
                    break
        except (ImportError,AttributeError,OSError,RuntimeError,sqlite3.Error):
            result['warnings'].append('Parallel-text evidence comparison is unavailable; direct source evidence remains separate.')
    return result


class ContextRequest(BaseModel):
    model_config = {'extra': 'forbid'}
    form: str = Field(min_length=1,max_length=200)
    passage_id: str = Field(min_length=1,max_length=500)


@app.post('/api/classify-context')
def classify_context_request(request:ContextRequest,http_request:Request):
    """Explicit, bounded inference action; it never modifies source evidence."""
    from .classifier import classify_context
    analysis=word(request.form,request.passage_id)
    if not analysis.get('context'):
        raise HTTPException(404,'Passage not found')
    candidates=analysis.get('contextual_candidates') or []
    # Source-scoped context candidates take precedence. Generic lookup remains
    # an explicitly separate fallback, never a fabricated occurrence analysis.
    candidate_origin='structured_source_claims' if candidates else 'lexicon_and_treebank_candidates'
    if not candidates:
        candidates=analysis.get('candidates',[])
    parallel=analysis.get('parallel_contexts') or []
    comparison_candidates=[candidate for item in parallel for candidate in item.get('candidates',[])]
    if comparison_candidates:
        # Retain exact general alternatives, but nearby spelling suggestions
        # cannot compete as parses when matching-wording source analyses exist.
        candidates=[candidate for candidate in candidates if not candidate.get('edit_distance',0)]
        # General morphology rows intentionally have no ID: the packet builder
        # assigns stable per-request IDs and rejects duplicate explicit IDs.
        candidates=[*candidates,*comparison_candidates]
        candidate_origin += '_with_parallel_text_comparison'
    all_claims=analysis.get('structured_evidence',{}).get('claims',[])
    all_claims=list({claim['id']:claim for claim in [*all_claims,*[claim for item in parallel for claim in item.get('claims',[])]]}.values())
    selected_ids={identifier for candidate in candidates for identifier in candidate.get('claim_ids',[])}
    # Preserve retrieved alternatives; the classifier rejects oversized sets
    # rather than silently removing hypotheses to meet its request budget.
    claims=sorted(all_claims,key=lambda item:item['id'] not in selected_ids)
    profile_claims=[]
    profile=analysis.get('author_profile') or {}
    for identifier in profile.get('literary_dialect_claim_ids',[]):
        try:
            found=evidence_service().get_claim(identifier)
            if found:
                profile_claims.append(found)
        except (OSError,RuntimeError,sqlite3.Error):
            pass
    from .jev_gateway import CachedJevProvider, GatewayLimit, GatewayUnavailable, public_enabled
    from .classifier import configured_provider
    provider = None
    if public_enabled():
        try:
            provider = CachedJevProvider(configured_provider(), http_request.state.classifier_visitor)
        except (GatewayUnavailable, OSError, ValueError):
            raise HTTPException(503,'Classifier cache is unavailable; no paid request was made.')
    try:
        result=classify_context(request.form,analysis['context'],candidates=candidates,
                                claims=claims,author_profile=profile_claims,provider=provider)
    except GatewayLimit as exc:
        raise HTTPException(429,str(exc),headers={'Retry-After':str(exc.retry_after)})
    except GatewayUnavailable:
        raise HTTPException(503,'Classifier state is unavailable. Please try again later.')
    result['candidate_origin']=candidate_origin
    return result


def wording_condition(keys):
    """Shared literal predicate for results and excluded-record notices."""
    cond=' OR '.join(['phrase_match(p.normalized,?) OR phrase_match(lower(p.citation),?) OR phrase_match(lower(p.work),?)']*len(keys))
    values=[value for key in keys for value in (key,key,key)]
    fts_keys=[key for key in keys if any(c.isalnum() for c in key)]
    if fts_keys:
        expression=' OR '.join('"'+key.replace('"','""')+'"' for key in fts_keys)
        cond='p.id IN (SELECT id FROM passage_fts WHERE passage_fts MATCH ?) AND ('+cond+')'
        values=[expression]+values
    return cond,values


def excluded_exact_matches(q,author='',language='',edition=''):
    """Count only indexed literal matches hidden by the default quality gate.

    Uses the publication-filtered connection and every caller scope filter.
    It is neither a semantic search nor an estimate of missing literary text.
    """
    keys=variants(q)
    if not keys or not any(any(c.isalnum() for c in key) for key in keys):
        return {}
    condition,values=wording_condition(keys)
    extra,params=filters(author,language,edition,True)
    excluded=f" AND (p.quality NOT IN {QUALITY_SQL} OR p.kind NOT IN ('text','translation','commentary'))"
    with connect() as con:
        groups=[dict(row) for row in con.execute(
            'SELECT p.quality,p.kind,count(*) count FROM passages p WHERE ('+condition+')'+extra+excluded+
            ' GROUP BY p.quality,p.kind ORDER BY p.quality,p.kind',values+params)]
    total=sum(row['count'] for row in groups)
    return {'excluded_exact_matches':{'total':total,'groups':groups,
        'method':'Exact normalized wording/citation only; excludes fuzzy, morphological and semantic matches.'}} if total else {}


@app.get('/api/search')
def search(q:str='',mode:str='words',author:str='',language:str='',edition:str='',
           include_reference:bool=False,match:str='fuzzy',limit:int=Query(30,ge=1,le=100),order:str='relevance',offset:int=0,
           commentary_assisted:bool=True):
    if offset<0 or offset>100000:
        raise HTTPException(422,'offset must be between 0 and 100000')
    q = q.strip()[:1000]
    if not q:
        return {'results':[],'total':0,'mode':mode,'method':'Enter a word, citation, or description.','warnings':[]}
    if mode not in ('words','forms','themes','hybrid'):
        raise HTTPException(400,'Search mode must be words, forms, themes, or hybrid')
    # Explicit references are navigation intent, not a bag of vocabulary.
    # Keep catalogue-only coverage visible without pretending it is poem text.
    if re.search(r'\d', q):
        from .reference_lookup import parse_reference_query, rank_reference_records
        with connect() as con:
            labels=[row[0] for row in con.execute('SELECT DISTINCT author FROM works')]
            intent=parse_reference_query(q,labels,selected_author=author,alias_resolver=author_labels)
            if intent:
                author_keys=list(dict.fromkeys(author_key(label) for label in intent.author_labels))
                marks=','.join('?' for _ in author_keys)
                records=[unpack(row) for row in con.execute(f'''
                    SELECT p.data FROM passages p WHERE author_key(p.author) IN ({marks})
                    OR (p.kind IN ('translation','commentary') AND EXISTS (
                        SELECT 1 FROM passages parent
                        WHERE parent.id=json_extract(p.data,'$.parent_id')
                          AND parent.kind='text' AND parent.language='grc'
                          {'' if include_reference else 'AND parent.quality IN '+QUALITY_SQL}
                          AND author_key(parent.author) IN ({marks})))''',author_keys*2)]
                return rank_reference_records(intent,records,language=language,edition=edition,
                                              limit=limit,offset=offset,include_reference=include_reference)
    if mode=='hybrid':
        return hybrid_search(q,author=author,language=language,edition=edition,
                             include_reference=include_reference,match=match,limit=limit,
                             order=order,offset=offset,commentary_assisted=commentary_assisted)
    warnings=[]
    fallback_provenance={}
    extra,params=filters(author,language,edition,include_reference)
    def mark_author_scope(item):
        if author and item.get('kind') in {'commentary','translation'} and not (set(component_keys(item.get('author')))&set(author_filter_keys(author))):
            reason=('Translation linked to the selected author by an explicit Greek parent passage; translator authorship is retained.'
                    if item.get('kind')=='translation' else
                    'Commentary linked to the selected author by an explicit parent passage or shared source page; commentary authorship is retained.')
            item['author_scope_reason']=reason
            item['match_reason']=item.get('match_reason','')+'; '+reason
        return item
    if mode=='themes':
        try:
            semantic=semantic_service()
            # A fixed retrieval pool keeps totals and chronological ordering
            # stable across pages. It is an explicitly bounded candidate set,
            # not a claim about the whole semantic index.
            window=1000
            hits=semantic.search(q,limit=window,author=author_labels(author) if author else None,
                                 language=language or None,include_reference=include_reference)
        except (ImportError,FileNotFoundError,RuntimeError) as exc:
            return {'results':[],'total':0,'mode':mode,'method':'Semantic index unavailable',
                'warnings':[str(exc),'Use word search while the local encoder index is being built.']}
        results=[]
        groups={}
        with connect() as con:
            for hit in hits:
                columns=("p.data,author_canonical_key(p.author) AS author_canonical,'' AS text_key,p.quality" if legacy_schema()
                         else 'p.data,p.author_canonical,p.text_key,p.quality')
                row=con.execute('SELECT '+columns+' FROM passages p WHERE p.id=?'+extra,[hit['id']]+params).fetchone()
                if row:
                    group_key=(row['author_canonical'],row['text_key'] or hit['id'],row['quality'])
                    if group_key in groups:
                        groups[group_key]['mirrored_ids'].append(hit['id'])
                        groups[group_key]['mirror_count']+=1
                        continue
                    item=unpack(row)
                    item['score']=hit.get('score')
                    item['match_reason']=hit.get('match_reason','Dense embedding similarity; inspect the passage to evaluate the parallel.')
                    item['mirrored_ids']=[]
                    item['mirror_count']=1
                    groups[group_key]=item
                    results.append(mark_author_scope(item))
        if len(hits)==window:
            warnings.append('Semantic total counts only the first 1,000 ranked candidates; more indexed hits may exist.')
        warnings.append('Translations/commentary are separate retrieval evidence; no automatic equivalence of senses is asserted.')
        total=len(results)
        return {'results':order_results(results,order)[offset:offset+limit],'total':total,'mode':mode,
            'method':'Local multilingual dense embeddings; similarity is not an influence claim.','warnings':warnings}
    keys=variants(q)
    if not keys:
        keys=[basic_normalize(q)]
    with connect() as con:
        if order=='chronological':
            con.create_function('author_year',1,lambda name:
                ((author_chronology(name) or {}).get('sort_year')
                 if (author_chronology(name) or {}).get('sort_year') is not None else 99999))
            warnings.append('Retrieved matches are ordered by sourced author biography, not by secure composition dates. Undated authors appear last.')
        # Ordering applies to grouped rows (one representative per identical
        # text), so the columns carry no table alias here.
        chronology=f'author_year(author),{canonical_expr()},' if order=='chronological' else ''
        ordinary=f"CASE WHEN language='grc' THEN 0 ELSE 1 END,{canonical_expr()},author,work,sequence,id"
        # Token boundaries prevent a queried word from matching inside a
        # different inflection. Citations and titles use the same literal test.
        cond,exactparams=wording_condition(keys)
        exact_where='('+cond+')'+extra
        exact_count=con.execute('SELECT count(*) FROM passages p WHERE '+exact_where,exactparams+params).fetchone()[0]
        method='Accent-insensitive wording and citation search'
        token_keys=[]
        if mode=='forms':
            try:
                analyses=[morph_service().analyze(token,limit=6) for token in tokenize(q)[:12]]
                lemmas=[lemma for analysis in analyses for lemma in analysis.get('expansion_lemmas',[])]
                expansion=set(key for token in tokenize(q)[:12] for key in variants(token))
                service=morph_service()
                source_forms=[]
                try:
                    evidence_index=evidence_service()
                    for token in tokenize(q)[:12]:
                        source_forms.extend(evidence_index.forms_for_lemma(token,limit=500))
                        candidate_rows=evidence_index.candidate_analyses(token,limit=12).get('candidates',[])
                        lemmas.extend(candidate['lemma'] for candidate in candidate_rows if candidate.get('lemma'))
                        for candidate in candidate_rows:
                            equivalent=candidate.get('equivalent_form')
                            if isinstance(equivalent,str) and equivalent:
                                expansion.update(variants(equivalent))
                    for lemma in dict.fromkeys(lemmas):
                        source_forms.extend(evidence_index.forms_for_lemma(lemma,limit=500))
                    expansion.update(basic_normalize(value) for value in source_forms)
                except (ImportError,AttributeError,OSError,RuntimeError,sqlite3.Error):
                    warnings.append('Structured dictionary-form expansion is unavailable; using the existing lexicon/treebank index.')
                if hasattr(service,'expansion_forms_for_lemma'):
                    for lemma in lemmas:
                        expansion.update(basic_normalize(f) for f in service.expansion_forms_for_lemma(lemma))
                else:
                    for lemma in lemmas:
                        expansion.update(variants(lemma))
                token_keys=sorted(expansion)[:500] if match!='exact' else []
                method='Source-backed lemma/form expansion; dictionary-listed forms are matched against actual corpus tokens, not treated as attestations themselves'
                warnings.extend(w for analysis in analyses for w in analysis.get('warnings',[]))
            except (ImportError,RuntimeError) as exc:
                warnings.append('Lemma/form data not yet available; returning literal matches only.')
                warnings.append(str(exc))
        elif exact_count==0 and match!='exact':
            token_keys=list(keys)
            if len(tokenize(q))==1:
                vocab=[r[0] for r in con.execute('SELECT normalized FROM vocabulary WHERE length(normalized) BETWEEN ? AND ?',(max(1,len(keys[0])-2),len(keys[0])+2))]
                near=difflib.get_close_matches(keys[0],vocab,n=8,cutoff=.72)
                token_keys=list(dict.fromkeys(token_keys+near))
                if near:
                    warnings.append('Approximate spelling matches are suggestions, not morphological identifications.')
                    method='Nearest indexed word forms by spelling similarity'
        if token_keys:
            marks=','.join('?' for _ in token_keys)
            candidates=('WITH candidates AS ('
                'SELECT p.id,0 priority,0 matched FROM passages p WHERE '+exact_where+
                ' UNION ALL SELECT p.id,1 priority,COUNT(DISTINCT t.normalized) matched '
                'FROM passages p JOIN tokens t ON t.passage_id=p.id '
                'WHERE t.normalized IN ('+marks+')'+extra+' GROUP BY p.id), '
                'ranked AS (SELECT id,MIN(priority) priority,MAX(matched) matched '
                'FROM candidates GROUP BY id), '
                'matched AS (SELECT '+search_row_columns()+',ranked.priority,ranked.matched FROM ranked JOIN passages p ON p.id=ranked.id), '
                'grouped AS (SELECT matched.*,'
                f'MIN(priority) OVER (PARTITION BY {text_columns()}) gpriority,'
                f'MAX(matched) OVER (PARTITION BY {text_columns()}) gmatched,'
                +grouping('priority,mirror_pref(source,quality),matched DESC,sequence,id')+' FROM matched) ')
            values=exactparams+params+token_keys+params
            total=count_search_groups(con,candidates,values)
            ordering=chronology+'gpriority,gmatched DESC,mirror_pref(source,quality),'+ordinary
            rows=fetch_search_page(con,candidates,ordering,values,limit,offset)
            results=[mark_author_scope(with_mirrors(unpack(row)|{'match_reason':'Normalized wording / citation match' if row['priority']==0 else method,
                                                   'score':None},row)) for row in rows]
        else:
            grouped=('WITH matched AS (SELECT '+search_row_columns()+' FROM passages p WHERE '+exact_where+'), '
                     'grouped AS (SELECT matched.*,'+grouping('mirror_pref(source,quality),sequence,id')+' FROM matched) ')
            total=count_search_groups(con,grouped,exactparams+params)
            rows=fetch_search_page(con,grouped,chronology+ordinary,exactparams+params,limit,offset)
            results=[mark_author_scope(with_mirrors(unpack(row)|{'match_reason':'Normalized wording / citation match','score':None},row)) for row in rows]
        if total==0 and match!='exact':
            terms=tokenize(basic_normalize(q))[:16]
            from .query_expansion import fallback_plan
            coverage_groups=[]
            if 2<=len(tokenize(q))<=8:
                vocabulary={row[0] for row in con.execute('SELECT normalized FROM vocabulary')}
                plan=fallback_plan(q,keys,vocabulary)
                greek_terms=plan.get('tokens',[])
                if greek_terms:
                    coverage_groups=plan['groups']
                    fallback_provenance={'fallback_terms':{'original':list(terms),'transliterated':greek_terms,
                        'groups':coverage_groups,'covered_words':plan['covered_words'],
                        'substantial_words':plan['substantial_words'],'exact_anchors':plan['exact_anchors']}}
                    terms=list(dict.fromkeys([*terms,*greek_terms]))
                    warnings.append('Latin-script input also searched as indexed Greek spelling candidates; original query words are retained. These are retrieval suggestions, not morphological identifications.')
            if terms:
                expression=' OR '.join('"'+t.replace('"','""')+'"' for t in terms)
                coverage_sql=[]
                coverage_params=[]
                for group in coverage_groups:
                    group_terms=list(dict.fromkeys([group['original'],*group['transliterated']]))
                    coverage_sql.append('CASE WHEN '+' OR '.join(
                        '(phrase_match(p.normalized,?) OR phrase_match(lower(p.citation),?) OR phrase_match(lower(p.work),?))'
                        for _ in group_terms)+' THEN 1 ELSE 0 END')
                    coverage_params.extend(value for term in group_terms for value in (term,term,term))
                coverage_select=','+'+'.join(coverage_sql)+' query_term_coverage' if coverage_sql else ',0 query_term_coverage'
                # Identical copies group here too; a group ranks by its best
                # word-group coverage, then its best full-text rank.
                cols=text_columns()
                fts_sql=('WITH matched AS (SELECT '+search_row_columns()+',bm25(passage_fts) rank'+coverage_select+
                         ' FROM passage_fts JOIN passages p ON p.id=passage_fts.id WHERE passage_fts MATCH ?'+extra+'), '
                         'grouped AS (SELECT matched.*,MIN(rank) OVER (PARTITION BY '+cols+') grank,'
                         'MAX(query_term_coverage) OVER (PARTITION BY '+cols+') gcoverage,'
                         +grouping('mirror_pref(source,quality),query_term_coverage DESC,rank,id')+' FROM matched) ')
                fts_values=coverage_params+[expression]+params
                total=count_search_groups(con,fts_sql,fts_values)
                coverage_order='gcoverage DESC,' if coverage_sql else ''
                fetched=fetch_search_page(con,fts_sql,chronology+coverage_order+'grank,mirror_pref(source,quality),id',fts_values,limit,offset)
                results=[]
                for row in fetched:
                    item=with_mirrors(unpack(row)|{'match_reason':'Shared search words (not necessarily an exact phrase)','score':-row['rank']},row)
                    if coverage_sql:
                        item['query_term_coverage']=row['query_term_coverage']
                        item['match_reason']=f"Matches {row['query_term_coverage']} of {len(coverage_groups)} original query word groups; spelling alternatives count once, not as separate evidence."
                    results.append(mark_author_scope(item))
                method=('Original-word-group coverage, then full-text rank; native and transliterated terms retained'
                        if coverage_sql else 'Full-text shared-word retrieval')
    if any(item.get('mirror_count',1)>1 for item in results):
        warnings.append('Identical copies of a text (same author, language, quality label and words) are shown once; mirrored_ids lists the collapsed copies.')
    excluded={} if include_reference else excluded_exact_matches(q,author,language,edition)
    return {'results':results,'total':total,'mode':mode,'method':method,'warnings':list(dict.fromkeys(warnings)),**excluded,**fallback_provenance}


def hybrid_search(q,*,author='',language='',edition='',include_reference=False,
                  match='fuzzy',limit=30,order='relevance',offset=0,commentary_assisted=True):
    """Rank fusion, not arithmetic on unrelated cosine and lexical scores.

    Fetch translation/commentary evidence before applying output-language and
    edition filters, so their explicit Greek parents can be returned.
    """
    from .retrieval import fuse
    pool=400
    candidate_language='' if commentary_assisted else (language or 'grc')
    common=dict(author=author,language=candidate_language,edition='',
                include_reference=include_reference,match=match,limit=pool,
                order='relevance',offset=0)
    lexical=search(q=q,mode='words',**common)
    # Long descriptions are not sequences of Greek morphological queries.
    greek=any(c.isalpha() and ('\u0370'<=c<='\u03ff' or '\u1f00'<=c<='\u1fff') for c in q)
    forms=search(q=q,mode='forms',**common) if greek or len(tokenize(q))<=2 else {'results':[],'warnings':[]}
    warnings=lexical.get('warnings',[])+forms.get('warnings',[])
    try:
        dense=semantic_service().search(q,limit=1000,author=author_labels(author) if author else None,
                                        language=candidate_language or None,
                                        include_reference=include_reference)
    except (ImportError,OSError,RuntimeError,ValueError) as exc:
        dense=[]
        warnings.append('Dense retrieval unavailable; hybrid results currently use lexical/form signals only: '+safe_error(exc))
    extra={}
    weights=None
    with connect() as con:
        def fetch_record(identifier):
            return unpack(con.execute('SELECT data FROM passages WHERE id=?',(identifier,)).fetchone())
        if not greek and commentary_assisted:
            # English queries: Greek vectors alone find the judged passage about
            # one time in ten (retrieval lab, 2026-09-30). Linked English
            # records and rare-word feedback from the top Greek hits carry the
            # ranking; the Greek-vector signal stays as weak evidence.
            from .bridges import ENGLISH_QUERY_WEIGHTS, bm25_bridge_hits, prf_hits
            extra['bm25_bridge']=bm25_bridge_hits(con,q,limit=pool)
            extra['dense_english']=[hit for hit in dense if hit.get('indexed_language')=='eng'][:pool]
            seeds=[hit['id'] for hit in dense if hit.get('indexed_language')=='grc' and hit.get('indexed_kind')=='text']
            extra['prf']=prf_hits(con,seeds,limit=pool)
            weights=ENGLISH_QUERY_WEIGHTS
            warnings.append('English query: linked translations and commentary (BM25 and dense over English records) and rare-word feedback from the top Greek candidates are fused with the Greek-vector signal, which is down-weighted.')
        fused=fuse(q,lexical['results'],forms['results'],dense,fetch_record,
                   author=author,language=language,edition=edition,
                   include_reference=include_reference,limit=2*pool+1000,offset=0,
                   commentary_assisted=commentary_assisted,author_labels=author_labels(author) if author else (),
                   author_key=canonical_key,author_keys=component_keys,weights=weights,extra=extra)
    ranked=order_results(fused['results'],order)
    warnings+=fused['warnings']
    warnings.append('Counts cover a bounded pool of up to 400 word, 400 form and 1,000 dense candidates'+(', 400 English-bridge and 400 feedback candidates' if extra else '')+', not every possible match.')
    if order=='chronological':
        warnings.append('Author biography dates order these candidates; they are not secure passage composition dates.')
    excluded={} if include_reference else excluded_exact_matches(q,author,language,edition)
    fallbacks={channel:payload['fallback_terms'] for channel,payload in
               (('lexical',lexical),('forms',forms)) if payload.get('fallback_terms')}
    provenance={'fallback_terms':fallbacks} if fallbacks else {}
    return {**fused,'results':ranked[offset:offset+limit],'mode':'hybrid',
            'commentary_assisted':commentary_assisted,'warnings':list(dict.fromkeys(warnings)),**excluded,**provenance}


@app.get('/api/usage-space')
def usage_space(q:str='',author:str='',limit:int=Query(80,ge=3,le=150)):
    found=search(q=q,mode='forms',author=author,language='',edition='',include_reference=False,match='fuzzy',limit=limit)
    results=found['results']
    retrieval='Source-backed form/word search candidates'
    if len(results)<3:
        try:
            sem=search(q=q,mode='themes',author=author,language='',edition='',include_reference=False,match='fuzzy',limit=limit)
            ids={r['id'] for r in results}
            results.extend(r for r in sem['results'] if r['id'] not in ids)
            if sem['results']:
                retrieval='Word/form hits plus thematic candidates; thematic candidates need not contain the queried form'
        except Exception:
            pass
    matrix=None
    method='TF-IDF surface-vocabulary similarity, centered SVD projection to three dimensions.'
    try:
        found_ids,embedded=semantic_service().vectors_for([r['id'] for r in results])
        if len(found_ids)>=3:
            by_id={r['id']:r for r in results}
            results=[by_id[id] for id in found_ids]
            matrix=np.asarray(embedded,dtype=np.float32)
            method='Local BGE-M3 passage embeddings, centered SVD projection to three dimensions; only embedded hits shown.'
    except (ImportError,FileNotFoundError,RuntimeError):
        pass
    # Transparent local TF-IDF fallback without an encoder. This visualizes shared
    # surface vocabulary, not a model of historical meaning.
    if matrix is None:
        documents=[collections.Counter(tokenize(basic_normalize(r['text']))) for r in results]
        df=collections.Counter(t for doc in documents for t in doc)
        features=[t for t,_ in df.most_common(2500)]
        matrix=np.zeros((len(documents),len(features)),dtype=np.float32)
        for i,doc in enumerate(documents):
            for j,t in enumerate(features):
                if doc[t]:
                    matrix[i,j]=(1+np.log(doc[t]))*np.log(1+len(documents)/(1+df[t]))
    coords=np.zeros((len(results),3),dtype=float)
    if len(results)>1 and matrix.shape[1]:
        matrix/=np.maximum(np.linalg.norm(matrix,axis=1,keepdims=True),1e-8)
        centered=matrix-matrix.mean(axis=0)
        u,s,_=np.linalg.svd(centered,full_matrices=False)
        dimensions=min(3,u.shape[1])
        coords[:,:dimensions]=u[:,:dimensions]*s[:dimensions]
        coords/=max(float(np.abs(coords).max()),1e-8)
    points=[]
    for record,coord in zip(results,coords):
        point={key:record.get(key) for key in ('id','text','author','work','citation','source','source_url','license','edition','date_start','date_end','date_source','author_chronology','match_reason')}
        point.update(zip(('x','y','z'),[float(v) for v in coord]))
        points.append(point)
    return {'points':points,'method':retrieval+'. '+method,'retrieval_method':retrieval,
        'warnings':['Distances are a lossy similarity projection, not calibrated semantic change or evidence of influence.','Author and passage dates are omitted unless supplied by a cited source.']}


@app.get('/api/sources')
def sources():
    if public_deployment():
        return {'reports':[],'status':status(),'publication_note':
                ('Only source records with allowlisted redistribution terms are served.' if publication_restricted()
                 else 'The owner-selected source-labels publication policy serves the accepted corpus with its original rights notices, including unknown or qualified terms.')
                + ' Source attribution and license labels remain attached to each record.'}
    reports=[]
    accepted={}
    audit_path=ROOT/'data/reports/audit-acceptance.json'
    if audit_path.exists():
        accepted=json.loads(audit_path.read_text(encoding='utf-8')).get('files',{})
    for file in sorted((ROOT/'data/reports').glob('*.json')):
        if file.name.startswith(('audit','index')):
            continue
        if file.stat().st_size<2_000_000:
            try:
                raw=file.read_text(encoding='utf-8-sig')
                raw=raw.replace(str(ROOT).replace('\\','\\\\'),'[project]').replace(ROOT.as_posix(),'[project]')
                reports.append({'name':file.stem,'report':json.loads(raw),
                    'collection_audit':accepted.get(file.stem+'.jsonl',{}).get('verdict','not a text-index source / pending'),
                    'note':'Downloaded coverage is not the same as accepted searchable coverage; see status.sources.'})
            except ValueError:
                continue
    return {'reports':reports,'status':status()}


@app.get('/')
@app.get('/reader.html')
def home():
    path=ROOT/'reader.html'
    return FileResponse(path if path.exists() else ROOT/'index.html')


@app.get('/legacy')
@app.get('/index.html')
def legacy():
    return FileResponse(ROOT/'index.html')


@app.get('/data/lexicon.json')
def legacy_sample():
    """Only the explicitly labelled original prototype's fixture, not live evidence."""
    return FileResponse(ROOT/'data/lexicon.json')


for directory in ('js','css'):
    app.mount('/'+directory,StaticFiles(directory=ROOT/directory),name=directory)
app.mount('/assets/paintings',StaticFiles(directory=ROOT/'assets/paintings'),name='paintings')
