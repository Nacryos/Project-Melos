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
from typing import Literal

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
from .translation_languages import is_english_language
from .large_json_gzip import LargeJSONGZipMiddleware

ROOT = Path(__file__).resolve().parents[1]
DB = ROOT / 'data/corpus.sqlite'
app = FastAPI(title='Melos Greek Lyric Lexicon',version='0.4.0')
# Keep this inner to CORS and @app.middleware('http'): a policy wrapper emits
# ordinary JSON in streaming frames, which must not be buffered/compressed.
# Live since release I (2026-10-07); it was patched into the release artifact only.
app.add_middleware(LargeJSONGZipMiddleware, minimum_size=4096, compresslevel=1)
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

# A convenience throttle identity, not authentication. The machine service's
# durable global budget remains authoritative across cookie resets/workers.
_machine_cookie_key = secrets.token_bytes(32)


@app.middleware('http')
async def request_policy(request,call_next):
    from .jev_gateway import public_enabled
    visitor_cookie = None
    machine_cookie = None
    passage_action = request.url.path in ('/api/analyze-passage', '/api/passage-analysis')
    if (request.url.path == '/api/machine-analysis' or passage_action) and request.method == 'POST':
        max_body = 16384 if passage_action else 2048
        try:
            size = int(request.headers.get('content-length', '-1'))
        except ValueError:
            size = -1
        if size < 0 or size > max_body:
            return JSONResponse(status_code=413,content={'detail':f'A JSON request of at most {max_body} bytes is required.'})
        if request.headers.get('content-type','').split(';')[0].strip() != 'application/json':
            return JSONResponse(status_code=415,content={'detail':'Use application/json.'})
        token, _, signature = request.cookies.get('melos_morph_visitor','').partition('.')
        valid = (bool(re.fullmatch(r'[0-9a-f]{32}', token)) and
                 bool(re.fullmatch(r'[0-9a-f]{64}', signature))) and hmac.compare_digest(
            signature, hmac.new(_machine_cookie_key, token.encode(), hashlib.sha256).hexdigest())
        if not valid:
            token = secrets.token_hex(16)
            machine_cookie = token + '.' + hmac.new(_machine_cookie_key, token.encode(), hashlib.sha256).hexdigest()
        request.state.machine_visitor = hashlib.sha256(token.encode()).hexdigest()
        if passage_action:
            # The same convenience identity bounds span-level paid requests;
            # the durable gateway's global quota remains authoritative.
            request.state.classifier_visitor = request.state.machine_visitor
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
            valid = (bool(re.fullmatch(r'[0-9a-f]{32}', token)) and
                     bool(re.fullmatch(r'[0-9a-f]{64}', signature))) and hmac.compare_digest(
                signature, hmac.new(key, token.encode(), hashlib.sha256).hexdigest())
            if not valid:
                token = secrets.token_hex(16)
                visitor_cookie = token + '.' + hmac.new(key, token.encode(), hashlib.sha256).hexdigest()
            request.state.classifier_visitor = hashlib.sha256(token.encode()).hexdigest()
    response=await call_next(request)
    if visitor_cookie:
        response.set_cookie('melos_visitor',visitor_cookie,max_age=2592000,
                            httponly=True,secure=public_deployment(),samesite='lax',path='/api')
    if machine_cookie:
        response.set_cookie('melos_morph_visitor',machine_cookie,max_age=2592000,
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
    con.create_function('is_english_language',1,is_english_language,deterministic=True)
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


def with_visual_themes(record, con):
    """Attach optional source-bound aesthetic labels through this visibility view."""
    from .visual_themes import attach_visual_themes
    def lookup(passage_id):
        row = con.execute('SELECT data FROM passages WHERE id=?', (passage_id,)).fetchone()
        return json.loads(row['data']) if row else None
    from .source_labels import with_source_label
    return with_source_label(attach_visual_themes(record, lookup=lookup))


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
    if not language and not edition:
        clauses.append(f"({alias}.kind<>'translation' OR is_english_language({alias}.language))")
    if not include_reference:
        clauses += [f"{alias}.quality IN {QUALITY_SQL}",f"{alias}.kind IN ('text','translation','commentary')"]
    return (' AND '+ ' AND '.join(clauses) if clauses else ''), values


@lru_cache(maxsize=8)
def file_digest(path,stamp,size):
    with open(path,'rb') as stream:
        return hashlib.file_digest(stream,'sha256').hexdigest()


SUPPLEMENT_ENTRIES = ROOT/'data/lexica/supplement-entries.jsonl'
SUPPLEMENT_AUDIT = ROOT/'data/reports/audit-lexica-supplement.json'


@lru_cache(maxsize=1)
def _morph_service(entries_stamp,forms_stamp,public=False,supplement_stamp=None):
    from .morphology import Morphology
    return Morphology(entries_path=ROOT/'data/lexica/entries.jsonl',forms_path=ROOT/'data/lexica/forms.jsonl',
                      supplement_paths=[SUPPLEMENT_ENTRIES] if supplement_stamp else [])


def _supplement_stamp():
    """Optional open-lexica supplement (Middle Liddell, Logeion LSJ, Cunliffe,
    Dodson). Absent: lookups run on the core files only. Present: it must
    match its independent audit (scripts/audit_lexica_supplement.py)."""
    # Unlike the core files, an unaudited supplement does not take lookups
    # down: it is simply not loaded (fail closed for the supplement only).
    if not SUPPLEMENT_ENTRIES.exists() or not SUPPLEMENT_AUDIT.exists():
        return None
    try:
        audit=json.loads(SUPPLEMENT_AUDIT.read_text(encoding='utf-8'))
        info=SUPPLEMENT_ENTRIES.stat()
        digest=file_digest(str(SUPPLEMENT_ENTRIES),info.st_mtime_ns,info.st_size)
    except (OSError,ValueError):
        return None
    if audit.get('verdict')!='PASS' or digest!=audit.get('sha256'):
        return None
    return info.st_mtime_ns


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
        service=_morph_service(*stamps,publication_restricted(),_supplement_stamp())
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
    from .source_labels import source_label
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
            'sources':[{**item,'label':source_label(item.get('source'))} if isinstance(item,dict) else item
                       for item in sources],'languages':langs,'embeddings':embedding,'quality':quality,
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
        item['author_chronology']=author_chronology(item['author'])
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
        results = [with_visual_themes(unpack(r), con) for r in rows]
    return {'results':results,'total':total}


@app.get('/api/passage')
def passage(id: str):
    with connect() as con:
        row = con.execute('SELECT * FROM passages WHERE id=?',(id,)).fetchone()
        if not row:
            raise HTTPException(404,'Passage not found')
        result = with_visual_themes(unpack(row), con)
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
    from .translation_previews import project as translation_previews
    result.update(translation_previews(result,result.get('related',[]),full_text=True))
    from .edition_commentary import for_passage as edition_commentary_for_passage
    if (published_commentary := edition_commentary_for_passage(result)) is not None:
        result['published_commentary'] = published_commentary
        if published_commentary.get('status') == 'available':
            from .editorial_readings import editorial_readings
            try:
                result['editorial_readings'] = editorial_readings(result)
            except (ValueError,TypeError,KeyError):
                result['editorial_readings'] = {'version':1,'status':'unavailable','rows':[],
                    'reason':'Approved source editorial spans could not be verified.'}
        else:
            result['editorial_readings'] = {'version':1,'status':'unavailable','rows':[],
                'reason':'Approved Campbell source identity is unavailable.'}
    from .translation_comparisons import for_passage as translation_comparisons_for_passage
    if (translation_comparisons := translation_comparisons_for_passage(result)) is not None:
        result['translation_comparisons'] = translation_comparisons
    return result


def occurrences(keys,author='',limit=30,con=None):
    if not keys:
        return []
    own = con is None
    con = con or connect()
    marks = ','.join('?' for _ in keys)
    # De-duplicate by passage id in a subquery: DISTINCT over whole passage blobs
    # spilled a temporary b-tree past the container's /tmp for frequent words (καὶ, δ’).
    sql = f'SELECT p.data FROM passages p WHERE p.id IN (SELECT t.passage_id FROM tokens t WHERE t.normalized IN ({marks}))'
    params = list(keys)
    if author:
        labels=author_filter_keys(author)
        sql += ' AND '+author_member_clause(labels)('p')
        params.extend(labels)
    sql += " ORDER BY CASE WHEN p.language='grc' THEN 0 ELSE 1 END,p.author,p.work,p.sequence,p.id LIMIT ?"
    try:
        return [unpack(r) for r in con.execute(sql,params+[limit])]
    finally:
        if own:
            con.close()


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
    from .occurrence_preview import group_preview
    result['occurrence_preview_groups'] = group_preview(result['occurrences'])
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
        service=evidence_service()
        source_candidates=service.candidate_analyses(form,passage_id=passage_id or None,limit=100)
        result['contextual_candidates'] = source_candidates.get('candidates',[])
        preview_ids={claim['id'] for claim in result['structured_evidence'].get('claims',[])}
        selected_ids=list(dict.fromkeys(claim_id for candidate in result['contextual_candidates']
            for claim_id in [*candidate.get('claim_ids',[]), *candidate.get('entry_sense_claim_ids',[])]))
        supporting={claim['id']:claim for claim in source_candidates.get('supporting_claims',[])
                    if claim.get('id') in selected_ids}
        # The raw /api/word evidence preview is capped at 100 claims, while
        # candidate projection filters metadata before its own limit. Close
        # only selected source-claim proofs missing from the ACTUAL preview.
        # Added records retain their source subject and general scope; they
        # never become a claim about the requested passage.
        if result['structured_evidence'].get('ready'):
            for claim_id in selected_ids:
                if claim_id in preview_ids or claim_id in supporting:
                    continue
                proof=service.get_claim(claim_id)
                subject=(proof or {}).get('subject') or {}
                if (not proof or proof.get('status')!='source_claim' or
                    proof.get('assertion_type')=='model_inference' or
                    not isinstance(subject,dict) or subject.get('passage_id')):
                    continue
                proof['strength']='general_source_record'
                proof['match_reason']=('Accepted general source record supports a selected candidate; '
                    'its original subject is retained and no passage attestation is asserted.')
                supporting[claim_id]=proof
        result['contextual_supporting_claims'] = list(supporting.values())
        result['contextual_unresolved_claim_ids'] = [claim_id for claim_id in selected_ids
            if claim_id not in preview_ids and claim_id not in supporting]
        result['contextual_candidate_method'] = source_candidates.get('method')
    except (ImportError,AttributeError,OSError,RuntimeError,sqlite3.Error):
        result['contextual_candidates'] = []
        result['contextual_supporting_claims'] = []
        result['contextual_unresolved_claim_ids'] = []
    # Lexical variants can supply an entry meaning without supplying a parse.
    # Keep them out of both morphological candidate inventories and rankings.
    try:
        from .lexical_variants import lookup_variants
        lexical=lookup_variants(form,evidence_service())
        result['lexical_variants']=lexical['lexical_variants']
        result['dictionary_crossreferences']=lexical['dictionary_crossreferences']
        result['lexical_variant_supporting_claims']=lexical['supporting_claims']
        result['lexical_variant_status']='available'
    except (ImportError,AttributeError,OSError,RuntimeError,ValueError,sqlite3.Error):
        result['lexical_variants']=[]
        result['dictionary_crossreferences']=[]
        result['lexical_variant_supporting_claims']=[]
        result['lexical_variant_status']='unavailable'
    # Source-linked dictionary paths are a separate inventory, never ordinary
    # morphology candidates or contextual source claims.
    try:
        from .linked_dictionary import lookup_linked_dictionary
        result['linked_dictionary']=lookup_linked_dictionary(form,evidence_service())
        result['linked_dictionary_status']='available'
    except (ImportError,AttributeError,OSError,RuntimeError,ValueError,TypeError,KeyError,sqlite3.Error):
        result['linked_dictionary']=None
        result['linked_dictionary_status']='unavailable'
        result['warnings'].append('Source-linked dictionary paths are unavailable; ordinary source alternatives remain separate.')
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


@app.get('/api/word')
def word_request(form: str, passage_id: str='', lemma: str=''):
    # Keep internal word/headword lookups source-only. Cached machine evidence
    # is added only at the ordinary user-facing HTTP boundary.
    from .passage_analysis import editorial_lookup_form
    printed, form = form, editorial_lookup_form(form)
    result = word(form, passage_id)
    if printed != form:
        result['printed_form'] = printed
    # No indexed source analysis of the exact form: the same local Morpheus and
    # generated-spelling path as in-poem analysis (backend.word_parser_candidates).
    from .machine_morphology import get_service
    from .word_parser_candidates import enrich_word_result
    enrich_word_result(result, form, machine_service=get_service(),
                       headword_lookup=lambda value: morph_service().headword_entries(value),
                       form_lemmas=lambda value: morph_service().form_lemmas(value), lemma=lemma)
    if os.environ.get('MELOS_MACHINE_SUBENTRIES_ENABLED') == '1':
        from .passage_analysis import machine_dictionary_lookup
        from .machine_morphology import get_service
        result['machine_dictionary'] = machine_dictionary_lookup(form,
            machine_lookup=lambda value: get_service().analyze(value, visitor_id=None, fetch=False),
            subentry_lookup=_passage_machine_subentries)
    return result


class MachineAnalysisRequest(BaseModel):
    model_config = {'extra': 'forbid'}
    form: str = Field(min_length=1,max_length=80)
    passage_id: str | None = Field(default=None,min_length=1,max_length=500)


def _machine_response_status(result):
    return {'ok':200, 'no_analyses':200, 'invalid_form':422,
            'rate_limited':429, 'busy':409, 'cache_full':503,
            'disabled':503, 'upstream_error':502, 'invalid_response':502,
            'invalid_receipt':422, 'cache_miss':404}.get(result.get('status'),503)


@app.post('/api/machine-analysis')
def machine_analysis_request(request:MachineAnalysisRequest,http_request:Request):
    """Explicit computational lookup; it never writes corpus/source evidence."""
    from .machine_morphology import get_service
    if request.passage_id:
        with connect() as con:
            found = con.execute('SELECT 1 FROM passages WHERE id=?',(request.passage_id,)).fetchone()
        if not found:
            raise HTTPException(404,'Passage not found')
    from .passage_analysis import editorial_lookup_form
    result = get_service().analyze(editorial_lookup_form(request.form),http_request.state.machine_visitor,fetch=True)
    code = _machine_response_status(result)
    headers = {'Retry-After':'60'} if code in (409,429) else None
    return JSONResponse(status_code=code,content=result,headers=headers)


class ContextRequest(BaseModel):
    model_config = {'extra': 'forbid'}
    form: str = Field(min_length=1,max_length=200)
    passage_id: str = Field(min_length=1,max_length=500)
    candidate_basis: Literal['source','machine'] = 'source'
    machine_receipt_id: str | None = Field(default=None,min_length=1,max_length=200)


@app.post('/api/classify-context')
def classify_context_request(request:ContextRequest,http_request:Request):
    """Explicit, bounded inference action; it never modifies source evidence."""
    return _classify_context_request(request,http_request)


def _classify_context_request(request:ContextRequest,http_request:Request,*,provider_override=None):
    """Shared proof checks; provider overrides are internal, never HTTP input."""
    from .classifier import classify_context
    if (request.candidate_basis == 'machine') != bool(request.machine_receipt_id):
        raise HTTPException(422,'Machine comparison requires a machine receipt; source comparison must not supply one.')
    from .passage_analysis import editorial_lookup_form
    request=request.model_copy(update={'form':editorial_lookup_form(request.form)})
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
    selected_ids={identifier for candidate in candidates
                  for identifier in [*candidate.get('claim_ids',[]), *candidate.get('entry_sense_claim_ids',[])]}
    all_claims=analysis.get('structured_evidence',{}).get('claims',[])
    sibling_proof=[claim for claim in analysis.get('contextual_supporting_claims',[])
                   if claim.get('id') in selected_ids]
    all_claims=list({claim['id']:claim for claim in [*all_claims,*sibling_proof,
        *[claim for item in parallel for claim in item.get('claims',[])]]}.values())
    proven_ids={claim['id'] for claim in all_claims
        if claim.get('status')=='source_claim' and claim.get('assertion_type')!='model_inference'
        and any(isinstance(evidence,dict) and evidence.get('source_url') and evidence.get('quote')
                for evidence in claim.get('evidence',[]))}
    # Machine comparisons must retain inventory-level safety warnings even
    # from a source candidate later excluded for missing bounded proof.
    original_source_guard_candidates = list(candidates)
    unproven=[candidate['id'] for candidate in candidates if candidate.get('candidate_kind')
        and any(claim_id not in proven_ids for claim_id in candidate.get('claim_ids',[]))]
    if unproven:
        candidates=[candidate for candidate in candidates if candidate.get('id') not in unproven]
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
    machine_kwargs = {}
    if request.candidate_basis == 'machine':
        from .machine_morphology import get_service
        machine = get_service().load_receipt(request.machine_receipt_id,form=request.form)
        code = _machine_response_status(machine)
        if code != 200:
            return JSONResponse(status_code=code,content=machine)
        # This receipt is read/reparsed again at the classifier boundary.
        # Client-supplied candidates, URLs and purported proof are never used.
        machine_kwargs = {'machine_validation':machine,
                          'source_guard_candidates':original_source_guard_candidates}
        candidates = machine['machine_candidates']
        candidate_origin = 'machine_analysis_receipt'
    from .jev_gateway import CachedJevProvider, GatewayLimit, GatewayUnavailable, public_enabled
    from .classifier import configured_provider
    provider = provider_override
    if provider is None and public_enabled():
        try:
            provider = CachedJevProvider(configured_provider(), http_request.state.classifier_visitor)
        except (GatewayUnavailable, OSError, ValueError):
            raise HTTPException(503,'Classifier cache is unavailable; no paid request was made.')
    try:
        result=classify_context(request.form,analysis['context'],candidates=candidates,
                                claims=claims,author_profile=profile_claims,provider=provider,
                                **machine_kwargs)
    except GatewayLimit as exc:
        raise HTTPException(429,str(exc),headers={'Retry-After':str(exc.retry_after)})
    except GatewayUnavailable:
        raise HTTPException(503,'Classifier state is unavailable. Please try again later.')
    result['candidate_origin']=candidate_origin
    if unproven:
        result['warnings'].append(
            f'{len(unproven)} structured candidate(s) excluded from Jev: accepted source proof was not in the bounded word preview or available as general source evidence.'
        )
        result['unproven_candidate_ids']=unproven
    return result


class _PassageMachineAdapter:
    def analyze(self, *args, **kwargs):
        from .machine_morphology import get_service
        return get_service().analyze(*args, **kwargs)


def _passage_classify(form, passage_id, *, provider, candidate_basis='source', machine_receipt_id=None):
    from types import SimpleNamespace
    payload = ContextRequest(form=form, passage_id=passage_id,
                             candidate_basis=candidate_basis, machine_receipt_id=machine_receipt_id)
    return _classify_context_request(payload, SimpleNamespace(state=SimpleNamespace()),
                                     provider_override=provider)


def _passage_provider(visitor_id):
    from .classifier import configured_provider, JevProvider
    from .jev_gateway import CachedJevProvider, GatewayUnavailable
    provider = configured_provider()
    if not isinstance(provider, JevProvider):
        raise GatewayUnavailable('Jev is not configured on this server.')
    return CachedJevProvider(provider, visitor_id)


def _passage_rerank_allowed(request):
    from .jev_gateway import public_enabled
    client = request.client.host if request.client else ''
    return public_enabled() or (not public_deployment() and client in ('127.0.0.1', '::1', 'testclient'))


@lru_cache(maxsize=1)
def _passage_subentry_resolver():
    from .machine_subentries import MachineSubentryResolver
    required = ('MELOS_SUBENTRY_INDEX', 'MELOS_SUBENTRY_MANIFEST', 'MELOS_SUBENTRY_INDEX_SHA256')
    configured = [os.environ.get(name, '').strip() for name in required]
    if not all(configured):
        raise RuntimeError('Enabled machine subentries require an explicit audited index, manifest and SHA-256.')
    return MachineSubentryResolver(configured[0], configured[1], expected_index_sha256=configured[2])


def _passage_machine_subentries(token):
    from .machine_morphology import get_service
    return _passage_subentry_resolver().resolve(token, receipt_loader=get_service().load_receipt)


# Providers are lazy: importing the API never downloads or loads model weights.
from . import syntax_provider as _passage_syntax
from .passage_ranker import PassageRanker
from .sense_ranker import PassageSenseRanker
from .passage_routes import create_router as _passage_router

app.include_router(_passage_router(
    lambda identifier: passage(identifier), lambda form, identifier: word(form, identifier),
    machine_service=_PassageMachineAdapter(), syntax_provider=_passage_syntax,
    ranker=PassageRanker(lambda identifier: passage(identifier), _passage_classify, _passage_provider),
    sense_ranker=PassageSenseRanker(lambda identifier: passage(identifier), _passage_provider),
    rerank_allowed=_passage_rerank_allowed,
    machine_subentry_lookup=(_passage_machine_subentries
                            if os.environ.get('MELOS_MACHINE_SUBENTRIES_ENABLED') == '1' else None),
    headword_lookup=lambda lemma: morph_service().headword_entries(lemma),
    form_lemma_lookup=lambda form: morph_service().form_lemmas(form),
    lemma_attestation_lookup=lambda lemma: len(morph_service().forms_for_lemma(lemma)),
))


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
def search_response(q:str='',mode:str='words',author:str='',language:str='',edition:str='',
                    include_reference:bool=False,match:str='fuzzy',limit:int=Query(30,ge=1,le=100),order:str='relevance',offset:int=0,
                    commentary_assisted:bool=True,forms_relation:str='ordered',slop:int=0):
    # Enrich only the final, paginated API response. Internal lexical/form
    # ranking pools continue to call search() without any translation queries.
    result=search(q=q,mode=mode,author=author,language=language,edition=edition,
                  include_reference=include_reference,match=match,limit=limit,order=order,
                  offset=offset,commentary_assisted=commentary_assisted,forms_relation=forms_relation,slop=slop)
    from .translation_previews import enrich_results
    if result.get('results'):
        try:
            with connect() as con:
                result['results']=enrich_results(con,result['results'])
        except (sqlite3.Error,ValueError,OSError):
            result['warnings']=[*result.get('warnings',[]),
                'Published translation previews are unavailable; passage search results are unchanged.']
    from .source_labels import with_source_label
    for record in result.get('results') or []:
        with_source_label(record)
    return result


def search(q:str='',mode:str='words',author:str='',language:str='',edition:str='',
           include_reference:bool=False,match:str='fuzzy',limit:int=Query(30,ge=1,le=100),order:str='relevance',offset:int=0,
           commentary_assisted:bool=True,forms_relation:str='ordered',slop:int=0,_legacy_multiword_forms:bool=False):
    if offset<0 or offset>100000:
        raise HTTPException(422,'offset must be between 0 and 100000')
    q = q.strip()
    if len(q) > 1000:
        raise HTTPException(422,'Search accepts at most 1000 Unicode characters; the query was not shortened or searched.')
    if forms_relation not in {'ordered','proximity','all_terms'} or not isinstance(slop,int) or not 0<=slop<=50:
        raise HTTPException(422,'Forms relation must be ordered, proximity, or all_terms; slop must be an integer from 0 to 50.')
    if forms_relation=='all_terms' and slop:
        raise HTTPException(422,'All words anywhere has no gap limit; set slop to 0.')
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
    from .sequence_search import query_terms
    query_words=query_terms(q)
    if mode=='forms' and len(query_words)>1 and not _legacy_multiword_forms:
        from .expansion import build_groups,SequenceLimit
        from .sequence_search import find_matches,MAX_CANDIDATES,MAX_SOURCE_CHARACTERS
        try:
            if match=='exact':
                groups=[{'query_index':i,'query_term':word,'alternatives':{
                    key:[{'kind':'literal_query','form':word}] for key in variants(word)}}
                    for i,word in enumerate(query_words)]
            else:
                groups=build_groups(query_words,morph_service(),evidence_service())
            with connect() as con:
                proofs,checked=find_matches(con,groups,extra,params,forms_relation,slop)
                chronology=''
                if order=='chronological':
                    con.create_function('author_year',1,lambda name:
                        ((author_chronology(name) or {}).get('sort_year')
                         if (author_chronology(name) or {}).get('sort_year') is not None else 99999))
                    chronology=f'author_year(author),{canonical_expr()},'
                    warnings.append('Retrieved matches are ordered by sourced author biography, not secure composition dates. Undated authors appear last.')
                ordinary=f"CASE WHEN language='grc' THEN 0 ELSE 1 END,{canonical_expr()},author,work,sequence,id"
                grouped=('WITH matched AS (SELECT '+search_row_columns()+
                         ' FROM passages p WHERE p.id IN (SELECT value FROM json_each(?))), '
                         'grouped AS (SELECT matched.*,'+grouping('mirror_pref(source,quality),sequence,id')+' FROM matched) ')
                values=[json.dumps(list(proofs))]
                total=count_search_groups(con,grouped,values)
                rows=fetch_search_page(con,grouped,chronology+ordinary,values,limit,offset)
                results=[]
                for row in rows:
                    item=with_mirrors(unpack(row),row)
                    # This exact selected primary's proof, never a mirror's
                    # offsets or a canonicalized substitute text.
                    item.update(sequence_match=proofs[item['id']],match_reason='Every query word has a distinct source-token witness',score=None)
                    results.append(mark_author_scope(item))
            warnings.append('Source-listed form alternatives are retrieval links, not a complete historical paradigm or a contextual parsing decision. No semantic or one-word fallback is used.')
            warnings.append('Strict witnesses exclude bracketed/restored, underdotted, and broken line-division tokens. Editorial gaps block ordered/proximity matches. Unmatched brackets are bounded to their printed line without resolving the source editorial scope; exclusion is not evidence of absence.')
            if any(item.get('mirror_count',1)>1 for item in results):
                warnings.append('Identical copies are grouped; each displayed positional proof belongs to the returned primary text only.')
            return {'results':results,'total':total,'mode':'forms','method':'Verified multiword source-token '+forms_relation,
                    'warnings':warnings,'search_contract':{
                        'version':1,'relation':forms_relation,'slop':slop,'query_term_count':len(groups),
                        'complete':True,'expansion_complete':True,'candidate_passages_checked':checked,
                        'scope':'single_stored_passage','offset_basis':'Unicode codepoints in original passage.text',
                        'expansion_policy':'literal_only' if match=='exact' else 'accepted_source_links_no_generated_paradigms',
                        'limits':{'candidate_passages':MAX_CANDIDATES,'source_characters':MAX_SOURCE_CHARACTERS},
                        'punctuation_policy':'Ordinary punctuation separates words; editorial damage blocks ordered/proximity matching.',
                        'editorial_policy':'Bracketed/restored spans, unbalanced bracket regions, underdotted tokens, and broken divisions are ineligible as intact-form witnesses.',
                        'witness_policy':'One complete witness per passage; not all occurrences.'}}
        except SequenceLimit as exc:
            raise HTTPException(422,str(exc)) from exc
        except (ImportError,OSError,RuntimeError,sqlite3.Error) as exc:
            raise HTTPException(503,'Strict form search is unavailable because its source indexes could not be read; no partial or approximate fallback was searched.') from exc
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
        from .retrieval import evidence_hit, fuse
        with connect() as con:
            def fetch_record(identifier):
                return unpack(con.execute('SELECT data FROM passages WHERE id=?',(identifier,)).fetchone())
            # One dense list means reciprocal rank preserves its order while
            # grouping all hits attached by an explicit parent_id under their
            # Greek passage. No shared-page or citation-based parent guesses.
            fused=fuse(q,(),(),hits,fetch_record,author=author,
                       author_labels=author_labels(author) if author else (),
                       language=language,edition=edition,include_reference=include_reference,
                       limit=window,offset=0,commentary_assisted=commentary_assisted,
                       author_key=canonical_key,author_keys=component_keys)
            results=fused['results']
            if not include_reference:
                # With the ordinary all-language/Greek reading, show source
                # texts, not orphan notes and individual vocabulary snippets.
                # An explicit English language filter may show linked English
                # material, but page-only commentary remains reference opt-in.
                if language in ('','grc'):
                    results=[item for item in results if item.get('kind')=='text']
                else:
                    results=[item for item in results if item.get('kind')!='commentary'
                             or item.get('parent_id')]
            elif author and commentary_assisted:
                # Author-scoped page/source-section notes have no unique Greek
                # parent. Keep them as separate opt-in references, never
                # project them to a passage based on URL or citation alone.
                known={item['id'] for item in results}
                for hit in hits:
                    row=con.execute('''SELECT p.data FROM passages p WHERE p.id=?
                        AND p.kind='commentary'
                        AND json_extract(p.data,'$.metadata.scope') IN ('page','source_section')
                        AND COALESCE(json_extract(p.data,'$.parent_id'),'')=''
                        '''+extra,[hit['id']]+params).fetchone()
                    if not row or hit['id'] in known:
                        continue
                    item=unpack(row)
                    item['score']=None
                    item['retrieval_score_kind']='unprojected_reference'
                    item['match_reason']='Dense similarity in unprojected source-page commentary; no unique Greek parent is asserted.'
                    item['matched_evidence']=[evidence_hit(item,hit,'semantic','unprojected_page_scope')]
                    item['mirrored_ids']=[]
                    item['mirror_count']=1
                    results.append(mark_author_scope(item))
                    known.add(item['id'])
        for item in results:
            if item.get('retrieval_score_kind')=='reciprocal_rank_fusion':
                item['retrieval_score_kind']='reciprocal_rank'
        if order=='relevance' and language in ('','grc'):
            results=[item for item in results if item.get('kind')=='text' and item.get('language')=='grc']+[
                item for item in results if item.get('kind')!='text' or item.get('language')!='grc']
        if len(hits)==window:
            warnings.append('Semantic total counts only the first 1,000 ranked candidates; more indexed hits may exist.')
        warnings.extend(message for message in fused['warnings']
                        if not message.startswith('RRF scores rank'))
        warnings.append('Scores are a one-list reciprocal-rank transform of the bounded dense order, not cosine similarities, probabilities, or confidence.')
        warnings.append('Dense candidates are ranked and grouped by explicit Greek parent IDs; linked commentary/translation remains separately attributed evidence, not a word-level alignment or verified sense equivalence.')
        if include_reference:
            warnings.append('Unlinked page/source-section notes may appear as separate reference results; a shared URL is never used to assign one Greek passage.')
        total=len(results)
        return {'results':order_results(results,order)[offset:offset+limit],'total':total,'mode':mode,
            'method':'Local multilingual dense rank grouped by explicit parent IDs; rank is not confidence or influence evidence.','warnings':warnings}
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
        transliteration_matches={}
        if exact_count==0 and mode=='words':
            from .query_expansion import (phrase_token_options,indexed_phrase_plan,
                                         confirm_source_phrases,MAX_PHRASE_PASSAGES)
            options=phrase_token_options(q)
            possible=list(dict.fromkeys(word for group in options for word,_ in group))
            if possible:
                marks=','.join('?' for _ in possible)
                vocabulary=dict(con.execute('SELECT normalized,count FROM vocabulary WHERE normalized IN ('+marks+')',possible))
                phrase_plan=indexed_phrase_plan(options,vocabulary)
                if phrase_plan:
                    anchors=phrase_plan['anchor_tokens']
                    marks=','.join('?' for _ in anchors)
                    # Token index -> passage IDs, not a scan of corpus text.
                    anchored=con.execute('SELECT p.id,p.text FROM passages p WHERE p.id IN '
                        '(SELECT passage_id FROM tokens WHERE normalized IN ('+marks+')) '
                        "AND p.language='grc' AND p.kind='text'"+extra+' ORDER BY p.id LIMIT ?',
                        [*anchors,*params,MAX_PHRASE_PASSAGES+1]).fetchall()
                    if phrase_plan['phrases_truncated'] or len(anchored)>MAX_PHRASE_PASSAGES:
                        warnings.append('Source-confirmed transliteration checked a bounded candidate window; additional phrase interpretations or indexed passages may exist.')
                    for row in anchored[:MAX_PHRASE_PASSAGES]:
                        confirmed=confirm_source_phrases(row['text'],phrase_plan['phrases'])
                        if confirmed:
                            transliteration_matches[row['id']]=confirmed
                    if transliteration_matches:
                        exactparams=list(transliteration_matches)
                        exact_where='p.id IN ('+','.join('?' for _ in exactparams)+')'+extra
                        exact_count=len(exactparams)
                        method='Source-confirmed transliteration phrase'
                        fallback_provenance['transliteration_phrase']={
                            'original_query':q,
                            'matched_greek_phrases':sorted({phrase for phrases in transliteration_matches.values() for phrase in phrases}),
                            'candidate_phrases_checked':len(phrase_plan['phrases']),
                            'phrase_limit':phrase_plan['phrase_limit'],'phrases_truncated':phrase_plan['phrases_truncated'],
                            'candidate_passages_checked':min(len(anchored),MAX_PHRASE_PASSAGES),
                            'passage_limit':MAX_PHRASE_PASSAGES,'passages_truncated':len(anchored)>MAX_PHRASE_PASSAGES,
                            'max_vowel_ambiguities':2,
                            'scope':'Indexed romanization interpretation confirmed as a complete source phrase; not a morphological identification.'}
                        warnings.append('Latin input matched a source-confirmed Greek phrase after bounded vowel-identity interpretation; the matched Greek wording is disclosed separately. No source text was corrected.')
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
                        # Lexical equivalent-form relations aid retrieval but
                        # are not grammatical/Jev parse candidates.
                        for equivalent in evidence_index.equivalent_forms_for_form(token,limit=500):
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
        if transliteration_matches:
            for item in results:
                item['match_reason']='Source-confirmed transliteration phrase'
                item['matched_transliteration_phrases']=sorted({phrase for identifier in [item['id'],*item.get('mirrored_ids',[])]
                                                               for phrase in transliteration_matches.get(identifier,[])})
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
    # An explicitly selected translation language is a source lookup. Preserve
    # it in the candidate pool, whose default otherwise excludes non-English
    # translations; Greek output can still use English parent-linked evidence.
    candidate_language=(language if language and language != 'grc' else '') if commentary_assisted else (language or 'grc')
    common=dict(author=author,language=candidate_language,edition='',
                include_reference=include_reference,match=match,limit=pool,
                order='relevance',offset=0)
    lexical=search(q=q,mode='words',**common)
    # Long descriptions are not sequences of Greek morphological queries.
    greek=any(c.isalpha() and ('\u0370'<=c<='\u03ff' or '\u1f00'<=c<='\u1fff') for c in q)
    forms=search(q=q,mode='forms',_legacy_multiword_forms=True,**common) if greek or len(tokenize(q))<=2 else {'results':[],'warnings':[]}
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
        # A Latin-script query that the exact wording path already matched is a
        # transliteration of Greek, not an English description.
        exact_lexical=lexical.get('total',0)>0 and (str(lexical.get('method','')).startswith('Accent-insensitive')
                                                 or bool(lexical.get('transliteration_phrase')))
        if not greek and not exact_lexical and commentary_assisted:
            # English queries: Greek vectors alone find the judged passage about
            # one time in ten (retrieval lab, 2026-09-30). Linked English
            # records supply one additional rank list. Rare-word feedback
            # remains a lab experiment, not a production signal.
            from .bridges import ENGLISH_QUERY_WEIGHTS, bm25_bridge_hits
            extra['bm25_bridge']=bm25_bridge_hits(con,q,limit=pool)
            weights=ENGLISH_QUERY_WEIGHTS
            warnings.append('English query: linked translations and commentary (BM25 over English records) are fused with the word, form and Greek-vector signals and projected to their Greek passages.')
        fused=fuse(q,lexical['results'],forms['results'],dense,fetch_record,
                   author=author,language=language,edition=edition,
                   include_reference=include_reference,limit=2*pool+1000,offset=0,
                   commentary_assisted=commentary_assisted,author_labels=author_labels(author) if author else (),
                   author_key=canonical_key,author_keys=component_keys,weights=weights,extra=extra)
    ranked=order_results(fused['results'],order)
    if lexical.get('transliteration_phrase') and order=='relevance':
        # A proved complete source phrase outranks an unrelated dense-only hit.
        # Preserve RRF ordering inside each tier; scores remain RRF, not a
        # fabricated probability or an amended similarity measurement.
        ranked.sort(key=lambda item: not any(
            evidence.get('signal')=='lexical'
            and evidence.get('match_reason')=='Source-confirmed transliteration phrase'
            for evidence in item.get('matched_evidence',[])))
    warnings+=fused['warnings']
    warnings.append('Counts cover a bounded pool of up to 400 word, 400 form and 1,000 dense candidates'+(', 400 English-bridge candidates' if extra else '')+', not every possible match.')
    if order=='chronological':
        warnings.append('Author biography dates order these candidates; they are not secure passage composition dates.')
    excluded={} if include_reference else excluded_exact_matches(q,author,language,edition)
    fallbacks={channel:payload['fallback_terms'] for channel,payload in
               (('lexical',lexical),('forms',forms)) if payload.get('fallback_terms')}
    provenance={'fallback_terms':fallbacks} if fallbacks else {}
    if lexical.get('transliteration_phrase'):
        provenance['transliteration_phrase']=dict(lexical['transliteration_phrase'],
            ranking_policy=('Confirmed source phrases first; reciprocal-rank-fusion order within each tier.'
                            if order=='relevance' else 'Requested chronology retained; no phrase-priority override.'))
    return {**fused,'results':ranked[offset:offset+limit],'mode':'hybrid',
            'commentary_assisted':commentary_assisted,'warnings':list(dict.fromkeys(warnings)),**excluded,**provenance}


@app.get('/api/usage-space')
def usage_space(q:str='',author:str='',limit:int=Query(80,ge=3,le=150),
                mode:str='forms',match:str='fuzzy',language:str='',edition:str='',
                include_reference:bool=False,order:str='relevance',commentary_assisted:bool=True,
                forms_relation:str='ordered',slop:int=0):
    # Exactly one retrieval under the supplied scope. Sparse exact/form results
    # are not permission to add unrelated thematic candidates.
    scope=dict(q=q,mode=mode,match=match,author=author,language=language,edition=edition,
               include_reference=include_reference,order=order,commentary_assisted=commentary_assisted,
               forms_relation=forms_relation,slop=slop)
    found=search(**scope,limit=limit,offset=0)
    results=list(found['results'])
    retrieved_count=len(results)
    retrieval=found.get('method','Requested search candidates')
    warnings=list(found.get('warnings',[]))
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
        point={key:record.get(key) for key in ('id','text','author','work','citation','source','source_url','license','edition','language','kind','quality','date_start','date_end','date_source','author_chronology','match_reason','sequence_match')}
        # Display/color identity only. Retain the source author label, and do
        # not substitute a linked parent or split a joint attribution.
        point['author_canonical']=canonical_author(record.get('author',''))
        point.update(zip(('x','y','z'),[float(v) for v in coord]))
        points.append(point)
    omitted_count=retrieved_count-len(points)
    if omitted_count:
        warnings.append(f'{omitted_count} retrieved records omitted from the embedding projection because vectors were unavailable; the search scope was not broadened.')
    warnings.extend(['Distances are a lossy similarity projection, not calibrated semantic change or evidence of influence.',
                     'Author and passage dates are omitted unless supplied by a cited source.',
                     f'This projection retrieves at most {limit} results from the requested search; it is not the complete corpus or a frozen list of previously displayed IDs.'])
    return {'points':points,'method':retrieval+'. '+method,'retrieval_method':retrieval,
        'scope':scope,'retrieved_count':retrieved_count,'plotted_count':len(points),'omitted_count':omitted_count,
        'search_total':found.get('total'), 'candidate_limit':limit,'search_contract':found.get('search_contract'),
        'warnings':list(dict.fromkeys(warnings))}


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


from .discovery import router as discovery_router
app.include_router(discovery_router)

for directory in ('js','css'):
    app.mount('/'+directory,StaticFiles(directory=ROOT/directory),name=directory)
app.mount('/assets/paintings',StaticFiles(directory=ROOT/'assets/paintings'),name='paintings')
app.mount('/assets/branding',StaticFiles(directory=ROOT/'assets/branding',check_dir=False),name='branding')
