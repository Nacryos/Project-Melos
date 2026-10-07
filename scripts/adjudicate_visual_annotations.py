"""Retained bounded adjudication of reviewer errors, against frozen source lines.

These are model interpretation revisions, not extracted source facts. Source
quotations are selected by observed line positions; no Greek text is invented
or normalized. The initial proposal is retained before any revision.
"""
import json
from pathlib import Path
import shutil

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / 'data/annotations/visual-themes/raw'
sources = {r['id']: r for p in (ROOT / '.benchmarks/visual-themes/packets').glob('*.json')
           for r in json.loads(p.read_text(encoding='utf-8')) if r['kind'] == 'text'}
target = RAW / 'packet-04.proposals.json'
backup = RAW / 'packet-04.proposals.initial.json'
if not backup.exists():
    shutil.copyfile(target, backup)
raw = json.loads(target.read_text(encoding='utf-8'))
decisions = {r['id']: r for r in raw['decisions']}
O = 'ogc:pindarus.olympia.jsonl:'
P = 'perseus:tlg0033.tlg001.perseus-grc2:'
Y = 'perseus:tlg0033.tlg002.perseus-grc2:'


def span(record_id, start=0, stop=None):
    text = sources[record_id]['text']
    quote = ''.join(text.splitlines(keepends=True)[start:stop]).rstrip('\r\n')
    assert quote and quote in text, record_id
    return {'id': record_id, 'quote': quote}


def label(record_id, theme, evidence, reason, kind='scene', modifiers=()):
    decisions[record_id] = {'id': record_id, 'status': 'label', 'reason': reason,
        'labels': [{'theme': theme, 'kind': kind, 'strength': 'strong',
                    'evidence': evidence, 'modifiers': list(modifiers)}]}


def abstain(record_id, reason):
    decisions[record_id] = {'id': record_id, 'status': 'abstain', 'reason': reason, 'labels': []}


for record_id in (O+'420', P+'7.1–7.19:1'):
    abstain(record_id, 'The vine-dew expression describes wine in a cup, not a developed garden or grove scene.')
for record_id in (O+'522', P+'8.1–8.19:1'):
    abstain(record_id, 'Conventional leafy-grove invocation beside a named river; insufficient developed nature imagery.')
abstain(O+'425', 'Muse-given nectar is a poetic gift; the proposed island evidence belonged to another record.')
abstain(Y+'12.1–12.19:1', 'Sheep-grazed hillside is a brief topographical epithet, not a developed pastoral scene.')
abstain(Y+'5.20–5.39:1', 'Castalia identifies a victory location; cypress describes a made object/structure, not a developed grove.')

for record_id in (O+'487', O+'488'):
    label(record_id, 'sea_coast', [span(record_id), span(O+('488' if record_id.endswith(':487') else '487'))],
          'The island rises from the wet salt sea into sunlight, completing the extended emergence scene.')

record_id = P+'5.1–5.19:1'
label(record_id, 'garden_grove', [span(record_id, 9, 13)],
      'The landscape combines sacred grove, local river and lake, and channels irrigating the settlement.')
decisions[record_id]['labels'].append({'theme': 'river_spring', 'kind': 'scene', 'strength': 'strong',
    'evidence': [span(record_id, 9, 13)], 'modifiers': []})
for record_id, other, own_lines, other_lines in (
        (P+'7.40–7.59:1', P+'7.60–7.79:1', (14, 18), (1, 11)),
        (P+'7.60–7.79:1', P+'7.40–7.59:1', (1, 11), (14, 18))):
    label(record_id, 'sea_coast', [span(record_id, *own_lines), span(other, *other_lines)],
          'The continuous scene develops the island hidden in briny depths and rising from the sea floor into sunlight.')

for record_id, start, stop, reason, kind, modifiers in (
        (Y+'4.180–4.199:1', 14, 19, 'Waves, winds, night sea routes, clouds, thunder and lightning receive sustained scenic attention.', 'scene', ('storm',)),
        (Y+'4.200–4.219:1', 3, 11, 'Sea passage driven by south winds leads into moving, crashing rocks, developed as a dangerous seascape.', 'scene', ()),
        (Y+'4.20–4.39:1', 0, 8, 'The voyage foregrounds the lake outlet, anchored ship and the passage from ocean across deserted land.', 'scene', ())):
    label(record_id, 'sea_coast', [span(record_id, start, stop)], reason, kind, modifiers)
record_id = Y+'4.260–4.279:1'
label(record_id, 'mountain_woodland', [span(record_id, 3, 10)],
      'The oak with hacked branches, lost fruitfulness, winter fire and emptied place is an extended tree simile.', 'simile')

# Confirmed counterparts were read in full during the cross-record audit. These
# own-source passages qualify independently; no parent or edition is guessed.
record_id = P+'1.60–1.79:1'
label(record_id, 'sea_coast', [span(record_id, 11, 15)],
      'The solitary approach to the grey sea in darkness gives a focused coastal encounter setting.')
record_id = P+'3.1–3.19:1'
label(record_id, 'garden_grove', [span(record_id, 12, 18)],
      'The olive brought from shaded springs becomes shade-giving planting in the shared sacred grove.')
record_id = P+'6.40–6.59:1'
label(record_id, 'meadow_pasture', [span(record_id, 14, 17)],
      'The infant is hidden among reeds and bramble with gold and purple violets bathing his body: a concentrated flowering-ground scene.')
record_id = Y+'3.20–3.39:1'
label(record_id, 'mountain_woodland', [span(record_id, 16, 18)],
      'The spreading calamity is rendered as a spark destroying a great mountain forest, a focused extended fire comparison.', 'simile')

raw['decisions'] = [decisions[row['id']] for row in raw['decisions']]
raw['adjudication'] = {'reviewer': 'backend-lead', 'method': 'Full-source reread; exact observed line spans; semantic exclusions; no guessed editions.'}
target.write_text(json.dumps(raw, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')

# These three lines are mythological lead-in and place-name genealogy, rather
# than the following developed Etna landscape. Retain the actual Etna rows.
target = RAW / 'packet-05.proposals.json'
backup = RAW / 'packet-05.proposals.pre-boundary-audit.json'
if not backup.exists():
    shutil.copyfile(target, backup)
raw = json.loads(target.read_text(encoding='utf-8'))
for row in raw['decisions']:
    if row['id'] in {f'ogc:pindarus.pythia.jsonl:{n}' for n in (16, 17, 18)}:
        row.update(status='abstain', labels=[], reason='Mythological lead-in and geographical names precede the developed Etna landscape; no strong nature scene in this row.')
target.write_text(json.dumps(raw, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
