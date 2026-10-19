#!/bin/sh
# Release X.11 checks (Latin scanner, scansion page endpoints, the restored vowel-length lexicons) against an origin.
#   sh deploy/scan_checks_x11.sh http://127.0.0.1:8798
set -eu
ORIGIN=${1:-http://127.0.0.1:8798}
python3 - "$ORIGIN" <<'PYEOF'
import json, sys, urllib.request
origin = sys.argv[1].rstrip('/')
failures = []

def post(path, body):
    req = urllib.request.Request(origin + path, data=json.dumps(body).encode(), headers={'Content-Type': 'application/json'})
    with urllib.request.urlopen(req, timeout=120) as r:
        return json.load(r)

def get(path):
    with urllib.request.urlopen(origin + path, timeout=120) as r:
        return json.load(r)

def check(name, ok, detail=''):
    print(('PASS ' if ok else 'FAIL ') + name + (' — ' + detail if detail else ''))
    if not ok:
        failures.append(name)

m = get('/api/scan/metres')
check('metres by language', set(m) == {'grc', 'la'} and any(r['name'] == 'phalaecian' for r in m['la']['metres'])
      and any(r['name'] == 'sapphic' for r in m['grc']['metres']), json.dumps({k: len(v['metres']) for k, v in m.items()}))

la = post('/api/scan', {'text': 'Vivamus, mea Lesbia, atque amemus,\nrumoresque senum severiorum', 'language': 'la', 'metre': 'auto', 'stanzas': True})
check('latin: lexicon on', la.get('lexicon') is True)
check('latin: phalaecian detected on Catullus 5', bool(la.get('auto')) and la['auto'][0]['metre'] == 'phalaecian' and la['auto'][0]['lines_fitting'] == 2,
      json.dumps(la.get('auto', [])[:2]))
check('latin: elision marked (Lesbia atque)', any(u.get('elision', 0) >= 0.5 for u in la['units']))
check('latin: display syllable spans', all(u['syllable'][1] > u['syllable'][0] for u in la['units']))

fit = post('/api/scan', {'text': 'Vivamus, mea Lesbia, atque amemus,', 'language': 'la', 'metre': 'phalaecian'})
check('latin: Catullus 5.1 fits the Phalaecian', fit['fit'][0]['ok'] and fit['fit'][0]['pattern'] == '–––⏑⏑–⏑–⏑–⏑', json.dumps(fit['fit'][0]['pattern']))

sappho = 'ποικιλόθρον’ ἀθανάτ’ Ἀφρόδιτα,\nπαῖ Δίος δολόπλοκε, λίσσομαί σε,\nμή μ’ ἄσαισι μηδ’ ὀνίαισι δάμνα,\nπότνια, θῦμον,'
gr = post('/api/scan', {'text': sappho, 'dialect': 'aeolic', 'metre': 'auto', 'stanzas': True})
check('greek: lexicon on (restored)', gr.get('lexicon') is True)
check('greek: Sapphic stanza detected on Sappho 1', bool(gr.get('auto')) and gr['auto'][0]['metre'] == 'sapphic' and gr['auto'][0]['lines_fitting'] == 4, json.dumps(gr.get('auto', [])[:2]))
check('greek: default language still Greek', gr.get('language') == 'grc')

p = get('/api/scan/passage?id=campbell-glp:sappho:16')
locked = sum(1 for l in p['lines'] if l['locked'])
check('reader scan: Sappho 16 still Sapphic with the metre lock', locked >= 15 and p['metre']['metre'] == 'sapphic',
      json.dumps({'locked': locked, 'unmarked': sum(1 for u in p['units'] if u['editorial'])}))

s = get('/api/status')
check('status answers', isinstance(s, dict))
print('FAILURES:', len(failures))
sys.exit(1 if failures else 0)
PYEOF
