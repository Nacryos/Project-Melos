#!/usr/bin/env python3
"""Select Greek lyric / elegiac / iambic papyri from DCLP (papyri.info idp.data) and write JSONL.

Reproduce:
    git clone --depth 1 --filter=blob:none --sparse https://github.com/papyri/idp.data.git <dir>
    git -C <dir> sparse-checkout set DCLP HGV_meta_EpiDoc
    python scripts/ingest_open_papyri_lyric.py --checkout <dir>
Outputs data/open/papyri-lyric/{papyri.jsonl,manifest.json,selection_log.json}.
Every string in the records is a literal span / deterministic rendering of the DCLP/HGV TEI XML
(Leiden-style plain text rendering rules: see render_edition()). Nothing is authored by hand.
HTTP User-Agent (if any network is used): Melos/1.0 (+https://greeklyric.com)  [this script is offline]
"""
import argparse, glob, hashlib, json, os, re, subprocess, sys, collections
import xml.etree.ElementTree as ET

NS = {'t': 'http://www.tei-c.org/ns/1.0'}
T = '{http://www.tei-c.org/ns/1.0}'
XML_LANG = '{http://www.w3.org/XML/1998/namespace}lang'
HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, '..', 'data', 'open', 'papyri-lyric')
USER_AGENT = 'Melos/1.0 (+https://greeklyric.com)'

# ---- selection rules -------------------------------------------------------------------------
# Rule A: any <bibl subtype="ancientEdition"><author> (DCLP's TLG/LDAB author field) names one of these poets.
POETS = [  # (canonical key, regex on author string)
    ('Sappho', r'^Sappho\b'), ('Alcaeus', r'^(Pseudo-\s*)?Alcaeus$|^Alcaeus\b(?! of Messene)'),
    ('Alcman', r'^Alcman'), ('Anacreon', r'Anacreon'), ('Archilochus', r'^Archilochus'),
    ('Hipponax', r'^Hipponax'), ('Semonides', r'^Semonides'), ('Mimnermus', r'^Mimnermus'),
    ('Tyrtaeus', r'^Tyrtaeus'), ('Solon', r'^Solon\b'), ('Theognis', r'^Theognis'),
    ('Simonides', r'^Simonides'), ('Pindar', r'^Pindar'), ('Bacchylides', r'^Bacchylides'),
    ('Stesichorus', r'^Stesichorus'), ('Ibycus', r'^Ibycus'), ('Corinna', r'^Corinna'),
    ('Callinus', r'^Callinus'), ('Xenophanes', r'^Xenophanes'), ('Ananius', r'^Ananius'),
    # extras beyond the brief, same genres (archaic melic / elegy):
    ('Phocylides', r'^Phocylides'), ('Terpander', r'^Terpander'), ('Telesilla', r'^Telesilla'),
    ('Praxilla', r'^Praxilla'), ('Lasus', r'^Lasus'),
]
POET_RE = [(k, re.compile(r)) for k, r in POETS]
# Rule B (no poet named / other author): Greek edition AND a DCLP keyword or the title contains a genre word,
# AND no biblical/Christian/Egyptian-religion/magic/Latin keyword.
GENRE_RE = re.compile(r'\b(lyric|lyrics|melic|elegy|elegiac|elegies|iambic|iambics|iambus|choliamb\w*|epode|epodes|'
                      r'dithyramb\w*|paean|partheneion|skolion|scolion)\b', re.I)
BARE_TAGS = {'lyric', 'lyrics', 'poetry lyric'}
EXCLUDE_KW = re.compile(r'christian|bible|psalm|manichae|gnostic|coptic|magic|amulet|phylakterion|liturg|hymn\b|hymns\b|jewish|septuagint|testament', re.I)
EXCLUDE_AUTH = re.compile(r'Testamentum|Messene', re.I)
PRE_RE = re.compile(rb'Sappho|Alcae|Alcman|Anacreon|Archilochus|Hipponax|Semonides|Mimnermus|Tyrtaeus|Solon|Theognis|Simonides|'
                    rb'Pindar|Bacchylides|Stesichorus|Ibycus|Corinna|Callinus|Xenophanes|Ananius|Phocylides|Terpander|'
                    rb'Telesilla|Praxilla|Lasus|lyric|melic|eleg|iamb|choliamb|epode|dithyramb|paean|partheneion|skolion|scolion', re.I)



NL = chr(10)
BS = chr(92)


class Repo:
    """Read blobs from the pinned commit (git object store; falls back to plain files if no .git).
    Reading through git avoids tens of thousands of slow file opens and is independent of autocrlf."""
    def __init__(self, checkout):
        self.co = checkout
        self.git = os.path.isdir(os.path.join(checkout, '.git'))
        self.commit = subprocess.run(['git', '-C', checkout, 'rev-parse', 'HEAD'], capture_output=True, text=True).stdout.strip() if self.git else None

    def ls(self, prefix, rx):
        if self.git:
            out = subprocess.run(['git', '-C', self.co, 'ls-tree', '-r', '--name-only', 'HEAD', prefix + '/'],
                                 capture_output=True, text=True, encoding='utf-8').stdout.split(NL)
            return [x for x in out if x and re.search(rx, x)]
        return [os.path.relpath(p, self.co).replace(BS, '/') for p in glob.glob(os.path.join(self.co, prefix, '*', '*.xml'))]

    def blobs(self, paths, chunk=4000):
        """yield (path, bytes, blob_sha)"""
        for i in range(0, len(paths), chunk):
            part = paths[i:i + chunk]
            if not self.git:
                for p in part:
                    with open(os.path.join(self.co, p), 'rb') as f:
                        b = f.read()
                    yield p, b, None
                continue
            inp = ''.join('HEAD:%s%s' % (p, NL) for p in part).encode()
            data = subprocess.run(['git', '-C', self.co, 'cat-file', '--batch'], input=inp, capture_output=True).stdout
            pos = 0
            for p in part:
                nl = data.index(NL.encode(), pos)
                sha, typ, size = data[pos:nl].decode().split()
                size = int(size)
                yield p, data[nl + 1:nl + 1 + size], sha
                pos = nl + 1 + size + 1

    def read(self, path):
        return next(self.blobs([path]))


def sha256b(b):
    return hashlib.sha256(b).hexdigest()


def txt(el):
    return ''.join(el.itertext()).strip() if el is not None else ''


def sha256(path):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for b in iter(lambda: f.read(1 << 20), b''):
            h.update(b)
    return h.hexdigest()


def idnos(root):
    d = {}
    for i in root.findall('.//t:publicationStmt/t:idno', NS):
        d.setdefault(i.get('type'), []).append((i.text or '').strip())
    return d


def header_info(root):
    ids = idnos(root)
    title = txt(root.find('.//t:titleStmt/t:title', NS))
    authors = []
    for a in root.findall('.//t:div[@type="bibliography"][@subtype="ancientEdition"]//t:author', NS):
        authors.append({'name': txt(a), 'ref': a.get('ref', '')})
    kws = [{'type': k.get('type'), 'term': (k.text or '').strip()} for k in root.findall('.//t:keywords/t:term', NS)]
    ed = root.find('.//t:div[@type="edition"]', NS)
    lang = ed.get(XML_LANG) if ed is not None else None
    return ids, title, authors, kws, lang


def select(root):
    """return (rule, poets, reasons) or None"""
    ids, title, authors, kws, lang = header_info(root)
    poets, reasons = [], []
    for a in authors:
        for k, rx in POET_RE:
            if rx.search(a['name']):
                poets.append(k)
                reasons.append('author:%s' % a['name'])
    if poets:
        return 'A', sorted(set(poets)), reasons
    if lang != 'grc':
        return None
    if any(EXCLUDE_AUTH.search(a['name']) for a in authors):
        return None
    kwtext = [k['term'] for k in kws]
    if any(EXCLUDE_KW.search(k) for k in kwtext):
        return None
    hits = [k for k in kwtext + [title] if GENRE_RE.search(k)]
    if not hits:
        return None
    # B1: a descriptive keyword/title contains the genre word; B2: only DCLP's bare category tag ('lyric', 'poetry lyric').
    specific = [h for h in hits if h.strip().lower() not in BARE_TAGS]
    return ('B1' if specific else 'B2'), [], ['genre-word:%s' % h for h in hits]


# ---- Leiden-style rendering --------------------------------------------------------------------
DOT = '\u0323'


def render_edition(ed):
    """Deterministic plain-text rendering of <div type=edition>. Conventions:
    [..] lost (dots = quantity; [...] unknown); [text] supplied lost; <text> supplied omitted; (text) expansion/explanatory;
    t̩ underdot = <unclear>; . = illegible char; [[text]] deleted; \\text/ added; {g:..} = <g>; line starts "N. "; "§ ..." textpart."""
    out = []

    def gap(el):
        reason, unit = el.get('reason'), el.get('unit')
        q, ext = el.get('quantity'), el.get('extent')
        if unit == 'line':
            return '[--- %s %s ---]' % ((q + ' lines') if q else 'lines', reason or '')
        if reason == 'illegible':
            return '.' * int(q) if q and q.isdigit() else '.'
        n = int(q) if q and q.isdigit() else None
        return '[' + ('.' * n if n else '...') + ']' if reason == 'lost' else '[' + ('.' * n if n else '..') + ']'

    def walk(el):
        tag = el.tag.replace(T, '')
        s = ''
        if tag == 'lb':
            s = '\n%s. ' % el.get('n', '')
        elif tag == 'l':
            s = '\n%s. ' % el.get('n', '')
        elif tag == 'gap':
            s = gap(el)
        elif tag == 'supplied':
            inner = inner_text(el)
            r = el.get('reason')
            s = {'lost': '[%s]', 'omitted': '<%s>', 'subaudible': '(%s)', 'explanatory': '(%s)'}.get(r, '[%s]') % inner
        elif tag == 'unclear':
            s = ''.join(c + DOT if not c.isspace() else c for c in inner_text(el))
        elif tag == 'g':
            s = '{g:%s}' % (el.get('type') or el.get('rend') or '')
        elif tag == 'space':
            s = '(vac.)'
        elif tag == 'ex':
            s = '(%s)' % inner_text(el)
        elif tag == 'abbr':
            s = inner_text(el)
        elif tag == 'del':
            s = '[[%s]]' % inner_text(el)
        elif tag == 'add':
            s = '\\%s/' % inner_text(el)
        elif tag == 'app':
            lem = el.find('t:lem', NS)
            s = inner_text(lem) if lem is not None else ''
        elif tag in ('note', 'head', 'rdg'):
            s = ''
        elif tag == 'div':
            s = '\n§ %s %s' % (el.get('subtype') or el.get('type') or '', el.get('n') or '')
            for c in el:
                s += walk(c) + (c.tail or '')
            return s + (el.text or '' if False else '')
        else:  # ab, hi, w, num, choice, expan, orig, reg, foreign, persName ...
            s = inner_text(el)
        return s

    def inner_text(el):
        s = el.text or ''
        for c in el:
            s += walk(c) + (c.tail or '')
        return s

    body = (ed.text or '')
    for c in ed:
        body += walk(c) + (c.tail or '')
    body = re.sub(r'[ \t]+\n', '\n', body)
    body = re.sub(r'\n\s*\n+', '\n', body)
    return body.strip('\n')


def apparatus(root, ed):
    items = []
    for a in ed.iter(T + 'app'):
        lem = a.find('t:lem', NS)
        items.append({'kind': 'app', 'type': a.get('type'), 'lem': txt(lem) if lem is not None else None,
                      'readings': [{'text': txt(r), 'resp': r.get('resp'), 'source': r.get('source'), 'wit': r.get('wit')}
                                   for r in a.findall('t:rdg', NS)]})
    for n in ed.iter(T + 'note'):
        items.append({'kind': 'note', 'text': txt(n), 'lang': n.get(XML_LANG)})
    for it in root.findall('.//t:div[@type="commentary"]//t:item', NS):
        ref = it.find('t:ref', NS)
        items.append({'kind': 'commentary', 'subtype': 'linebyline', 'corresp': it.get('corresp'),
                      'line': txt(ref), 'text': txt(it.find('t:p', NS))})
    return items


def bibliography(root):
    out = []
    for d in root.findall('.//t:div[@type="bibliography"]', NS):
        for b in d.iter(T + 'bibl'):
            if b.find('t:bibl', NS) is not None:
                continue
            out.append({'section': d.get('subtype'), 'type': b.get('type'), 'subtype': b.get('subtype'), 'n': b.get('n'),
                        'title': [{'level': x.get('level'), 'type': x.get('type'), 'text': txt(x)} for x in b.findall('t:title', NS)],
                        'author': [{'text': txt(x), 'ref': x.get('ref')} for x in b.findall('t:author', NS)],
                        'scopes': [{'unit': x.get('unit'), 'text': txt(x)} for x in b.findall('t:biblScope', NS) if txt(x)],
                        'ptr': [x.get('target') for x in b.findall('t:ptr', NS)],
                        'text': txt(b)})
    return out


POET_ABBR = r'(Sappho|Alc(?:aeus)?|Alcm(?:an)?|Anacr(?:eon)?|Stesich(?:orus)?|Ibyc(?:us)?|Simon(?:ides)?|Pind(?:ar)?|Bacchyl(?:ides)?|Corinn(?:a)?|Archil(?:ochus)?|Hippon(?:ax)?|Tyrt(?:aeus)?|Theogn(?:is)?|Callin(?:us)?|Mimn(?:ermus)?|Solon|Semon(?:ides)?)'
FR_POET_RE = re.compile(r'\b' + POET_ABBR + r'\.?,? +(?:fr(?:r)?\.?|fragm\.?|fragments?) *(\d+[a-z]?(?:[-–,] *\d+[a-z]?)*)')
FR_SCHEME_RE = re.compile(r'\b(PMG|PLF|L-P|LP|Lobel-Page|Voigt|SLG|Diehl|IEG|West|Snell|Maehler|Page|Bergk|Edmonds|Campbell)b[ ,.]*(?:fr(?:r)?\.? *|no\. *|n\. *)?(\d+[a-z]?(?:[-–] *\d+[a-z]?)?)')
FR_BARE_RE = re.compile(r'(?<![\w.])fr(?:r)?\. *(\d+[a-z]?(?:[-–,] *\d+[a-z]?)*)')


def fragment_mentions(fields):
    """Explicit fragment-number statements in DCLP metadata text. fields: list of (field_name, text)."""
    out = []
    for fld, t in fields:
        if not t:
            continue
        for m in FR_POET_RE.finditer(t):
            out.append({'field': fld, 'kind': 'poet_fr', 'poet_abbr': m.group(1), 'number': m.group(2), 'context': t[max(0, m.start() - 30):m.end() + 30]})
        for m in FR_SCHEME_RE.finditer(t):
            out.append({'field': fld, 'kind': 'scheme', 'scheme': m.group(1), 'number': m.group(2), 'context': t[max(0, m.start() - 30):m.end() + 30]})
        for m in FR_BARE_RE.finditer(t):
            out.append({'field': fld, 'kind': 'bare_fr', 'number': m.group(1), 'context': t[max(0, m.start() - 40):m.end() + 30]})
    return out


SCHEME_WORD = re.compile(r'(Lobel-Page|Lobel/Page|L-P|LP|PLF|Voigt|PMG|SLG|Diehl|IEG|West|Snell|Maehler|Page)')
ABBR_KEY = {'Sappho': 'Sappho', 'Alc': 'Alcaeus', 'Alcaeus': 'Alcaeus', 'Alcm': 'Alcman', 'Alcman': 'Alcman', 'Anacr': 'Anacreon',
            'Anacreon': 'Anacreon', 'Stesich': 'Stesichorus', 'Stesichorus': 'Stesichorus', 'Ibyc': 'Ibycus', 'Ibycus': 'Ibycus',
            'Simon': 'Simonides', 'Simonides': 'Simonides', 'Pind': 'Pindar', 'Pindar': 'Pindar', 'Bacchyl': 'Bacchylides',
            'Bacchylides': 'Bacchylides', 'Corinn': 'Corinna', 'Corinna': 'Corinna', 'Archil': 'Archilochus', 'Archilochus': 'Archilochus',
            'Hippon': 'Hipponax', 'Hipponax': 'Hipponax', 'Tyrt': 'Tyrtaeus', 'Tyrtaeus': 'Tyrtaeus', 'Theogn': 'Theognis',
            'Theognis': 'Theognis', 'Callin': 'Callinus', 'Callinus': 'Callinus', 'Mimn': 'Mimnermus', 'Mimnermus': 'Mimnermus',
            'Solon': 'Solon', 'Semon': 'Semonides', 'Semonides': 'Semonides'}


def explicit_refs(fields):
    """Poet + numbering scheme + number, all stated in the same DCLP phrase (e.g. 'Sappho; 01 (fr. 31 Lobel-Page)',
    'Alcaeus fr. 34 (Voigt)'). Anything less explicit is left in fragment_mentions only."""
    out = []
    for fld, t in fields:
        if not t:
            continue
        for m in FR_POET_RE.finditer(t):
            sch = SCHEME_WORD.search(t[m.end():m.end() + 25])
            if sch:
                out.append({'poet': ABBR_KEY.get(m.group(1)), 'scheme': sch.group(1), 'number': m.group(2), 'field': fld, 'context': t[max(0, m.start() - 20):m.end() + 30]})
        if fld == 'keyword':
            lead = re.match(r'\s*([A-Z][a-z]+)[;?]', t)
            for m in FR_BARE_RE.finditer(t):
                sch = SCHEME_WORD.search(t[m.end():m.end() + 25])
                if sch and lead and ABBR_KEY.get(lead.group(1)):
                    out.append({'poet': ABBR_KEY[lead.group(1)], 'scheme': sch.group(1), 'number': m.group(1), 'field': fld, 'context': t})
    return out


def hgv_index(repo):
    """ddb-hybrid -> [hgv paths] (only <idno type=ddb-hybrid> is read from each HGV_meta_EpiDoc file)."""
    idx = {}
    for path, b, _ in repo.blobs(repo.ls('HGV_meta_EpiDoc', r'\.xml$')):
        m = re.search(rb'<idno type="ddb-hybrid">([^<]*)<', b[:8000])
        if m:
            idx.setdefault(m.group(1).decode(), []).append(path)
    return idx


def hgv_record(repo, path):
    _, b, blob = repo.read(path)
    root = ET.fromstring(b)
    fid = (idnos(root).get('filename') or [''])[0]
    return {'hgv_file': path, 'git_blob': blob, 'sha256': sha256b(b), 'hgv_id': fid,
            'origDates': [{'attrs': dict(d.attrib), 'text': txt(d)} for d in root.findall('.//t:origin/t:origDate', NS)],
            'url': 'https://papyri.info/hgv/%s' % fid}


def build_record(repo, path, raw, blob, sel, hgv):
    root = ET.fromstring(raw)
    ids, title, authors, kws, lang = header_info(root)
    ed = root.find('.//t:div[@type="edition"]', NS)
    rel = path
    od = root.find('.//t:origin/t:origDate', NS)
    pubs = [x for x in bibliography(root) if x['section'] == 'principalEdition']
    head_ref = root.find('.//t:body/t:head/t:ref', NS)
    prov = []
    for pv in root.findall('.//t:history/t:provenance', NS):
        prov.append({'type': pv.get('type'), 'n': pv.get('n'),
                     'places': [{'text': txt(pl), 'type': pl.get('type'), 'subtype': pl.get('subtype'), 'ref': pl.get('ref')} for pl in pv.iter(T + 'placeName')]})
    one = lambda k: (ids.get(k) or [None])[0]
    text = render_edition(ed) if ed is not None else ''
    rec = {
        'id': 'dclp:%s' % one('dclp'),
        'ids': {'dclp': one('dclp'), 'tm': one('TM'), 'ldab': one('LDAB'), 'mp3': one('MP3'), 'dclp_hybrid': one('dclp-hybrid')},
        'title': title,
        'inventory': [txt(i) for i in root.findall('.//t:msIdentifier/t:idno', NS)],
        'publication_head': {'title': txt(head_ref.find('t:title', NS)) if head_ref is not None else None,
                             'date': txt(head_ref.find('t:date', NS)) if head_ref is not None else None,
                             'target': head_ref.get('target') if head_ref is not None else None},
        'principal_publications': pubs,
        'author_attribution': authors,
        'keywords': kws,
        'selection': {'rule': sel[0], 'poets': sel[1], 'reasons': sel[2]},
        'work': [k['term'] for k in kws if k['type'] in (None, 'description') and k['term'] not in ('literature', 'classical', 'poetry')],
        'manuscript_date': {'notBefore': od.get('notBefore') if od is not None else None, 'notAfter': od.get('notAfter') if od is not None else None,
                            'when': od.get('when') if od is not None else None, 'text': txt(od),
                            'note': 'date of the physical manuscript copy, not of composition'},
        'orig_place': txt(root.find('.//t:history/t:origin/t:origPlace', NS)),
        'provenance': prov,
        'edition_lang': lang,
        'edition_text': text,
        'edition_empty': not re.search(r'\w', text),
        'apparatus': apparatus(root, ed) if ed is not None else [],
        'bibliography': bibliography(root),
        'revision_log': sorted({re.sub(r'\s+', ' ', txt(c)) for c in root.findall('.//t:revisionDesc/t:change', NS)}),
        'layout': txt(root.find('.//t:layout', NS)),
        'licence': txt(root.find('.//t:availability', NS)),
        'raw_path': rel,
        'raw_sha256': sha256b(raw), 'git_blob': blob,
        'url': 'https://papyri.info/dclp/%s' % one('dclp'),
        'hgv': None,
    }
    flds = [('title', title)] + [('keyword', k['term']) for k in kws] + [('bibliography', b['text']) for b in rec['bibliography']] +            [('apparatus_' + x['kind'], x.get('text') or ' '.join(r['text'] for r in x.get('readings', []))) for x in rec['apparatus']] +            [('revision_log', x) for x in rec['revision_log']]
    rec['fragment_mentions'] = fragment_mentions(flds)
    rec['explicit_fragment_refs'] = explicit_refs(flds)
    h = one('dclp-hybrid')
    if hgv is not None and h and h in hgv:
        rec['hgv'] = [hgv_record(repo, p) for p in hgv[h]]
    return rec


LP_SCHEMES = {'Lobel-Page', 'Lobel/Page', 'L-P', 'LP', 'PLF'}
CAMPBELL_SCHEME = {'Sappho': LP_SCHEMES, 'Alcaeus': LP_SCHEMES, 'Alcman': {'PMG', 'Page'}, 'Stesichorus': {'PMG', 'Page'},
                   'Ibycus': {'PMG', 'Page'}, 'Anacreon': {'PMG', 'Page'}, 'Simonides': {'PMG', 'Page'}, 'Corinna': {'PMG', 'Page'},
                   'Bacchylides': {'Snell', 'Maehler'}}  # elegiac/iambic poets: Diehl
for _p in ('Archilochus', 'Hipponax', 'Semonides', 'Mimnermus', 'Tyrtaeus', 'Solon', 'Theognis', 'Callinus', 'Xenophanes', 'Phocylides'):
    CAMPBELL_SCHEME[_p] = {'Diehl'}


def campbell_coverage(melos, recs):
    """Match only explicit (poet, scheme, number) statements in DCLP metadata to Campbell GLP citations."""
    cg = os.path.join(melos, 'data', 'campbell_glp', 'campbell_glp.jsonl')
    cc = os.path.join(melos, 'data', 'fragment_concordance.json')
    if not (os.path.exists(cg) and os.path.exists(cc)):
        return None
    camp = [json.loads(l) for l in open(cg, encoding='utf-8')]
    conc = json.load(open(cc, encoding='utf-8'))
    cmap = {}
    for r in camp:
        m = re.match(r'Fragment (\d+[A-Za-z]?)$', r.get('citation', ''))
        cmap[(r['author'], m.group(1) if m else r.get('citation'))] = r['id']
    voigt2lp = {(e['author'], e['a'][1]): e['b'][1] for e in conc['equivalences']
                if e['a'][0] == 'Voigt' and e['b'][0] == 'Lobel-Page'}
    matches, unmatched = [], []
    for r in recs:
        for ref in r.get('explicit_fragment_refs', []):
            poet, sch, num = ref['poet'], ref['scheme'], ref['number']
            row = {'dclp': r['ids']['dclp'], 'poet': poet, 'stated_scheme': sch, 'stated_number': num, 'context': ref['context']}
            if sch in CAMPBELL_SCHEME.get(poet, set()) and (poet, num) in cmap:
                matches.append(dict(row, campbell_id=cmap[(poet, num)], basis='same numbering scheme as Campbell, number stated explicitly'))
            elif sch == 'Voigt' and (poet, num) in voigt2lp and (poet, voigt2lp[(poet, num)]) in cmap:
                matches.append(dict(row, campbell_id=cmap[(poet, voigt2lp[(poet, num)])], basis='explicit Voigt->Lobel-Page equivalence in fragment_concordance.json'))
            else:
                unmatched.append(dict(row, reason='no Campbell poem with that number in that scheme, or no explicit equivalence'))
    return {'campbell_records': len(camp), 'dclp_explicit_refs': sum(len(r.get('explicit_fragment_refs', [])) for r in recs),
            'matches': matches, 'unmatched_explicit_refs': unmatched,
            'campbell_poems_with_papyrus_witness': sorted({m['campbell_id'] for m in matches})}


def melos_overlap(melos, recs):
    base = os.path.join(melos, 'data', 'raw', 'commentary')
    if not os.path.isdir(base):
        return None
    have = {os.path.basename(p)[:-4] for p in glob.glob(os.path.join(base, '*', '*.xml'))}
    mine = {r['ids']['dclp'] for r in recs}
    return {'earlier_collector_files': len(have), 'selected_already_in_melos': len(mine & have), 'selected_new': len(mine - have),
            'earlier_not_selected_now': sorted(have - mine)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--checkout', required=True, help='idp.data checkout (DCLP/ and optionally HGV_meta_EpiDoc/)')
    ap.add_argument('--out', default=OUT)
    ap.add_argument('--no-hgv', action='store_true')
    a = ap.parse_args()
    repo = Repo(a.checkout)
    commit = repo.commit
    os.makedirs(a.out, exist_ok=True)
    paths = sorted(repo.ls('DCLP', r'\.xml$'), key=lambda p: int(os.path.basename(p)[:-4]))
    n_pre, sel_all = 0, []
    for path, raw, blob in repo.blobs(paths):
        if not PRE_RE.search(raw):
            continue
        n_pre += 1
        s = select(ET.fromstring(raw))
        if s:
            sel_all.append((path, raw, blob, s))
    files = paths
    hgv = None if a.no_hgv else hgv_index(repo)
    recs = [build_record(repo, p, raw, blob, s, hgv) for p, raw, blob, s in sel_all]
    pj = os.path.join(a.out, 'papyri.jsonl')
    with open(pj, 'w', encoding='utf-8', newline='\n') as f:
        for r in recs:
            f.write(json.dumps(r, ensure_ascii=False) + '\n')
    per_poet = collections.Counter(p for r in recs for p in r['selection']['poets'])
    ruleB = [{'dclp': r['ids']['dclp'], 'title': r['title'], 'authors': [x['name'] for x in r['author_attribution']],
              'rule': r['selection']['rule'], 'reasons': r['selection']['reasons']} for r in recs if r['selection']['rule'].startswith('B')]
    sel_log = {'ruleB_selected': ruleB}
    with open(os.path.join(a.out, 'selection_log.json'), 'w', encoding='utf-8') as f:
        json.dump(sel_log, f, ensure_ascii=False, indent=1)
    melos = os.path.abspath(os.path.join(HERE, '..'))
    coverage = {'per_poet_rule_A': dict(per_poet), 'overlap_with_earlier_melos_dclp': melos_overlap(melos, recs),
                'campbell': campbell_coverage(melos, recs),
                'rule_counts': {k: sum(r['selection']['rule'] == k for r in recs) for k in ('A', 'B1', 'B2')},
                'hgv_matches': sum(1 for r in recs if r['hgv'])}
    with open(os.path.join(a.out, 'coverage.json'), 'w', encoding='utf-8') as f:
        json.dump(coverage, f, ensure_ascii=False, indent=1)
    readme = repo.read('README.md')[1].decode('utf-8') if True else ''
    lic = re.search(r'This data is made available under[^' + chr(92) + 'n]*', readme)
    outs = {n: {'bytes': os.path.getsize(os.path.join(a.out, n)), 'sha256': sha256(os.path.join(a.out, n))}
            for n in ('papyri.jsonl', 'selection_log.json', 'coverage.json')}
    manifest = {
        'date': '2026-10-09', 'user_agent': USER_AGENT,
        'source': {'repo': 'https://github.com/papyri/idp.data', 'commit': commit, 'paths': ['DCLP/', 'HGV_meta_EpiDoc/'],
                   'basecamp_archive': '~/storagebox/archive/melos-open/idp.data/ (sparse checkout DCLP + HGV_meta_EpiDoc at the same commit; ssh to Basecamp 100.64.176.44)',
                   'local_checkout': 'data/cache/idp.data-git (gitignored)'},
        'licence': {'quote': lic.group(0) if lic else None, 'url': 'https://github.com/papyri/idp.data#license',
                    'licence_url': 'https://creativecommons.org/licenses/by/3.0/',
                    'per_file': 'each DCLP file repeats: (c) Digital Corpus of Literary Papyri and LDAB (Trismegistos) ... Creative Commons Attribution 3.0 License'},
        'attribution': 'papyri.info / Digital Corpus of Literary Papyri (DCLP) / LDAB (Trismegistos) and the respective contributing projects, '
                       'CC BY 3.0; texts are papyrus witnesses transcribed by DCLP editors; cite each record by its papyri.info URL.',
        'counts': {'dclp_files_scanned': len(files), 'prefilter_hits': n_pre, 'selected': len(recs), 'by_rule': coverage['rule_counts'],
                   'per_poet_rule_A': dict(per_poet), 'with_edition_text': sum(not r['edition_empty'] for r in recs),
                   'metadata_only': sum(r['edition_empty'] for r in recs), 'with_hgv': coverage['hgv_matches']},
        'selection_rules': {
            'A': 'DCLP bibliography/ancientEdition <author> (TLG/LDAB author field) matches one of the poet names in POETS (script) -- brief list plus Phocylides, Terpander, Telesilla, Praxilla, Lasus; "Alcaeus of Messene" excluded (Hellenistic epigrammatist); "Pseudo- Anacreon" included.',
            'B1': 'no listed poet; edition xml:lang=grc; a descriptive keyword or title contains lyric/melic/elegy/elegiac/iambic/iambus/choliamb/epode/dithyramb/paean/partheneion/skolion; no keyword for christian/bible/psalm/manichaean/gnostic/coptic/magic/amulet/liturgy/hymn/jewish/testament; no Testamentum author.',
            'B2': 'as B1 but the only genre word is the DCLP bare category tag ("lyric", "poetry lyric"). Many are Hellenistic/late poets (Callimachus, Lycophron, Dioscorus of Aphrodito, epigram anthologies) or drama; kept but flagged -- filter on selection.rule.'},
        'borderline_calls': ['Callimachus Iambi/Aetia papyri (B1/B2): Hellenistic imitations of iambus/elegy, selected only through genre words.',
                             'Timotheus, Cercidas (choliambi), Hermesianax (elegy), Euripidean/tragic lyric: appear in B only if genre words say so; not poets named in the brief.',
                             'Commentaries/lexica/scholia on a listed poet are selected under rule A (record shows them in title/keywords).',
                             'Simonides is not disambiguated in DCLP (Ceos vs Amorgos): kept as stated.',
                             'Records with a "?" author (e.g. 59081 "Alcaeus? Sappho?") keep every stated author and the title verbatim.'],
        'outputs': outs, 'script': 'scripts/ingest_open_papyri_lyric.py',
        'notes': ['manuscript_date is the date of the papyrus copy, not of composition.',
                  'edition_text is a deterministic Leiden-style rendering of <div type=edition>; most DCLP records are metadata-only (no transcription).',
                  'No DDbDP/HGV record matched any selected papyrus (by ddb-hybrid id or TM id); the hgv field is null for all.',
                  'Reads blobs from the git object store of the pinned commit; raw_sha256 is of the blob bytes.']}
    with open(os.path.join(a.out, 'manifest.json'), 'w', encoding='utf-8') as f:
        json.dump(manifest, f, ensure_ascii=False, indent=1)
    print(json.dumps({'commit': commit, 'dclp_files': len(files), 'prefilter_hits': n_pre, 'selected': len(recs),
                      'rule_A': sum(r['selection']['rule'] == 'A' for r in recs), 'rule_B1': sum(r['selection']['rule'] == 'B1' for r in recs), 'rule_B2': sum(r['selection']['rule'] == 'B2' for r in recs),
                      'per_poet': per_poet, 'with_hgv': sum(1 for r in recs if r['hgv']),
                      'jsonl_bytes': os.path.getsize(pj), 'jsonl_sha256': sha256(pj)}, ensure_ascii=False, indent=1))


if __name__ == '__main__':
    main()
