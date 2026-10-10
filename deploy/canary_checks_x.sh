#!/bin/sh
# Release X checks against an origin (canary 127.0.0.1:8792 or production). Prints one line per check; exits 1 on failure.
#   sh deploy/canary_checks_x.sh http://127.0.0.1:8792
set -eu
ORIGIN=${1:-http://127.0.0.1:8792}
python3 - "$ORIGIN" <<'EOF'
import json, sys, urllib.parse, urllib.request
origin = sys.argv[1].rstrip('/')
failures = []

def get(path, **params):
    url = origin + path + ('?' + urllib.parse.urlencode(params) if params else '')
    with urllib.request.urlopen(url, timeout=120) as r:
        return json.load(r)

def check(name, ok, detail=''):
    print(('PASS ' if ok else 'FAIL ') + name + (' — ' + detail if detail else ''))
    if not ok:
        failures.append(name)

status = get('/api/status')
check('status answers', isinstance(status, dict), str(status)[:120])
emb = status.get('embeddings') if isinstance(status, dict) else None
check('dense index ready with the 59 added rows', isinstance(emb, dict) and emb.get('ready') is True and emb.get('count') == 116487,
      json.dumps({k: (emb or {}).get(k) for k in ('ready', 'count')}))

p = get('/api/passage', id='campbell-glp:alcaeus:45')
lit = p.get('literal_translation') or {}
check('alcaeus 45: literal translation available', lit.get('status') == 'available', json.dumps({k: lit.get(k) for k in ('status', 'line_count', 'published_english_available')}))
check('alcaeus 45: fallback flags', lit.get('display_policy') == 'fallback_only' and lit.get('model_eligible') is False
      and lit.get('published_source') is False and lit.get('published_english_available') is False)
check('alcaeus 45: 9 line pairs with Greek equal to the stored lines', lit.get('line_count') == 9
      and [l['greek'] for l in lit.get('lines', [])] == [l['text'] for l in p.get('lines', [])])
check('alcaeus 45: no machine_translation row in related', all(r.get('quality') != 'machine_translation' for r in p.get('related', [])))

s = get('/api/passage', id='campbell-glp:sappho:31')
lit = s.get('literal_translation') or {}
check('sappho 31: literal present but published English available', lit.get('status') == 'available' and lit.get('published_english_available') is True)
check('sappho 31: other-edition comparison still served', (s.get('translation_comparisons') or {}).get('status') == 'available')
check('sappho 31: no machine_translation row in related', all(r.get('quality') != 'machine_translation' for r in s.get('related', [])))

for poem, n in (('campbell-glp:anacreon:417', 6), ('campbell-glp:alcaeus:350', 7), ('campbell-glp:sappho:fr-adesp-976-pmg', 4)):
    r = get('/api/passage', id=poem)
    lit = r.get('literal_translation') or {}
    check(f'{poem}: literal bound ({n} lines)', lit.get('status') == 'available' and lit.get('line_count') == n)

row = get('/api/passage', id='campbell-glp:anacreon:417:literal')
check('literal corpus row stored', row.get('quality') == 'machine_translation' and row.get('parent_id') == 'campbell-glp:anacreon:417'
      and row.get('kind') == 'translation' and row.get('language') == 'eng', json.dumps({k: row.get(k) for k in ('quality', 'parent_id', 'kind')}))

def top_ids(result, limit=10):
    items = result.get('results') or result.get('items') or []
    out = []
    for item in items[:limit]:
        out.append(item.get('id') or (item.get('passage') or {}).get('id'))
    return out

def search_hits(query, want, **params):
    # The literal row credits its poem; the poem may itself be folded under another edition's entry, so the
    # evidence list (which names the matched record) is the reliable signal.
    result = get('/api/search', q=query, limit=100, **params)
    items = result.get('results') or []
    for rank, item in enumerate(items, 1):
        folded = any(isinstance(e, dict) and e.get('id') == want for e in item.get('editions') or [])
        if item.get('id') == want or folded or any(str(e.get('id', '')) == want + ':literal' for e in item.get('matched_evidence', [])):
            return True, [f'rank {rank} as {item.get("id")}']
    return False, top_ids(result)[:6]

for query, want, params in (('Thracian filly bridle rider', 'campbell-glp:anacreon:417', {'mode': 'hybrid'}),
                            ('Hebrus most beautiful of rivers maidens thighs', 'campbell-glp:alcaeus:45', {'mode': 'hybrid'}),
                            ('dive from the Leucadian rock drunk with love', 'campbell-glp:anacreon:376', {'mode': 'hybrid'})):
    try:
        hit, ids = search_hits(query, want, **params)
        check(f'search "{query}" reaches {want}', hit, ', '.join(str(i) for i in ids[:6]))
    except Exception as error:  # noqa: BLE001
        check(f'search "{query}"', False, repr(error)[:160])

print('FAILURES:', len(failures))
sys.exit(1 if failures else 0)
EOF
