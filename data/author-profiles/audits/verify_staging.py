"""Independent read-only checks for author-profile extraction staging."""
import hashlib
import json
import re
from pathlib import Path
from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parents[3]
DATA = ROOT / 'data/author-profiles'
def read(p):
    return json.loads(p.read_text(encoding='utf-8'))
def sha(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()

receipts = sorted((DATA / 'raw').glob('*.receipt.json'))
for receipt_file in receipts:
    receipt = read(receipt_file)
    raw = receipt_file.with_name(receipt_file.name.removesuffix('.receipt.json'))
    assert receipt['status'] == 200
    assert receipt['fetched_at'] and receipt['url'].startswith('https://')
    assert sha(raw) == receipt['sha256'], raw
print('PASS raw receipts and byte hashes:', len(receipts))

catalog = read(DATA / 'staged.json')
profiles = catalog['authors']
legacy = {p['author']:p for p in read(ROOT / 'local-preview/portraits.json')['portraits']}
assert len(profiles) == 13 and len({p['author'] for p in profiles}) == 13
greek = dict(re.findall(r"en: '([^']+)', gr: '([^']+)'", (ROOT/'js/app.js').read_text(encoding='utf-8')))
dcc = BeautifulSoup((DATA/'raw/dcc-sappho-introduction.html').read_bytes(), 'html.parser')
dcc_paragraphs = [p.get_text('', strip=False).strip() for p in dcc.find_all('p')]
dcc_bylines = [p.get_text(' ', strip=True) for p in dcc.find_all('p')]
for profile in profiles:
    b = profile['biography']
    raw = read(ROOT/b['raw_file'])
    receipt = read((ROOT/b['raw_file']).with_suffix('.json.receipt.json'))
    assert all(b[k] == receipt[k] for k in receipt)
    assert raw['type'] == 'standard'
    text, actual = raw['extract'], b['text']
    assert actual and text.startswith(actual) and len(actual.split()) <= 150
    if len(text.split()) <= 150:
        assert actual == text
    else:
        candidates = [i+1 for i,c in enumerate(text) if c in '.!?' and (i+1 == len(text) or text[i+1].isspace()) and len(text[:i+1].split()) <= 150]
        assert actual == text[:max(candidates)]
    assert b['source_url'] == raw['content_urls']['desktop']['page']
    assert b['revision_url'] == 'https://en.wikipedia.org/w/index.php?oldid=' + raw['revision']
    assert b['source_title'] == raw['title'] + ' — Wikipedia'
    assert b['license'] == 'CC BY-SA 4.0'
    assert 'creativecommons.org/licenses/by-sa/4.0' in b['license_url']
    assert profile['greek'] == greek.get(profile['author'], '')
    p = profile['portrait']
    if p:
        original = legacy['Alcaeus' if profile['author']=='Sappho' else profile['author']]
        for field in ['source_url','title','description','source_categories','artist','license','license_url','credit','download_url','sha256','source_file','image_transform']:
            assert p[field] == original[field], (profile['author'], field)
        assert sha(ROOT/p['source_image']) == p['sha256']
        assert (ROOT/p['raw_metadata']).exists()
    else:
        assert profile['author'] in ['Homer','Hesiod','Theocritus']
    for r in profile['reading']:
        assert profile['author'] in ['Sappho','Alcaeus']
        assert r['text'] in dcc_paragraphs and r['author'] in dcc_bylines
        assert r['title'] == dcc.title.get_text(' ',strip=True)
        assert r['license'] == 'CC BY-SA' and r['license_url'] == 'https://dcc.dickinson.edu/terms-use'
        assert sha(ROOT/r['raw_file']) == r['sha256']
    print('PASS', profile['author'], 'words', len(actual.split()), 'source_words',len(text.split()), 'portrait',bool(p), 'reading',len(profile['reading']))
assert sum(bool(p['portrait']) for p in profiles) == 10
assert sum(len(p['reading']) for p in profiles) == 2
print('PASS all 13 biographies, ten portraits, two exact DCC paragraph instances')
