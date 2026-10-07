"""Source-bound structured ABI projection. No morphology requests or authored rows."""
import argparse
import ast
from collections import Counter
import hashlib
import json
from pathlib import Path
import re
import unicodedata
from lxml import etree

ROOT = Path(__file__).resolve().parents[1]
D = ROOT / 'runtime/libmorpheus-offline-eval'
OLD = ROOT / 'runtime/morpheus-offline-eval'
HEADER = ROOT / 'runtime/libmorpheus-source-research/raw/include/morpheus/morpheus.h'
INPUT_SHA = '9fc46d45b5970eb49ee160d62661245b624ffc79113248762127bb66cbbbab46'
HEADER_SHA = '6652a58d12746d6713aa17546c78034a4de1c704ee11dc7e91c980fdf9ebdf25'
sha = lambda raw: hashlib.sha256(raw).hexdigest()


def immutable(path, raw):
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if path.read_bytes() != raw:
            raise ValueError('Different existing artifact: ' + str(path))
        return
    with path.open('xb') as output:
        output.write(raw)


def save(path, value):
    immutable(path, (json.dumps(value, ensure_ascii=False, indent=2) + '\n').encode())


def prepare():
    raw = (OLD / 'input-plan.json').read_bytes()
    if sha(raw) != INPUT_SHA:
        raise ValueError('Previously audited input plan changed')
    plan = json.loads(raw)
    for name, meta in plan['map_provenance'].items():
        body = (OLD / 'adapter-sources' / name).read_bytes()
        if sha(body) != meta['sha256']:
            raise ValueError('Previously audited mapping changed')
        immutable(D / 'adapter-sources' / name, body)
    for item in plan['inputs']:
        body = (item['beta'] + '\n').encode('ascii')
        if body != (OLD / 'inputs' / f"{item['id']:04}.txt").read_bytes():
            raise ValueError('Input bytes changed')
        immutable(D / 'inputs' / f"{item['id']:04}.txt", body)
    immutable(D / 'input-plan.json', raw)
    save(D / 'input-reuse.json', {'source_plan': str((OLD/'input-plan.json').relative_to(ROOT)),
        'source_plan_sha256': INPUT_SHA, 'copied_byte_exact': True,
        'inputs': len(plan['inputs']), 'script_sha256': sha(Path(__file__).read_bytes())})
    print(json.dumps({'inputs': len(plan['inputs']), 'copied_byte_exact': True}))


def constants():
    # Decode only published numeric definitions, not linguistic knowledge.
    if sha(HEADER.read_bytes()) != HEADER_SHA: raise ValueError('Pinned public header changed')
    source = HEADER.read_text(encoding='utf-8').replace('\\\n', '')
    values = {name: int(value) for name, value in
              re.findall(r'\b(MORPHEUS_[A-Z_]+)\s*=\s*(\d+)', source)}
    pending = dict(re.findall(r'^#define\s+(MORPHEUS_[A-Z_]+)\s+([^\n]+)', source, re.M))

    def evaluate(node):
        if isinstance(node, ast.Constant) and isinstance(node.value, int): return node.value
        if isinstance(node, ast.Name): return values[node.id]
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.BitOr): return evaluate(node.left) | evaluate(node.right)
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.LShift): return evaluate(node.left) << evaluate(node.right)
        raise ValueError('Non-numeric or unsupported source macro')

    for _ in range(len(pending)):
        progressed = False
        for name, raw in list(pending.items()):
            expression = re.sub(r'UINT(?:32|64)_C\((\d+)\)', r'\1', raw)
            expression = re.sub(r'\b(\d+)[uU]\b', r'\1', expression).strip()
            try:
                value = evaluate(ast.parse(expression, mode='eval').body)
            except (KeyError, ValueError, SyntaxError):
                continue
            values[name] = value
            del pending[name]
            progressed = True
        if not progressed: break
    return values


FIELDS = {
    'part_of_speech': ('PART_OF_SPEECH', False), 'person': ('PERSON', False),
    'number': ('NUMBER', False), 'gender': ('GENDER', True),
    'grammatical_case': ('CASE', True), 'tense': ('TENSE', False),
    'mood': ('MOOD', False), 'voice': ('VOICE', True),
    'degree': ('DEGREE', False), 'dialect': ('DIALECT', True),
    'geographic_region': ('REGION', True),
}
TEXT_FIELDS = ('raw', 'workword', 'lemma', 'preverb', 'augment', 'stem', 'suffix',
               'ending', 'crasis', 'dictionary_form', 'english_form', 'raw_preverb', 'domains')
SHARED_FEATURES = {'pofs': 'part_of_speech', 'pers': 'person', 'num': 'number',
                   'gend': 'gender', 'case': 'grammatical_case', 'tense': 'tense',
                   'mood': 'mood', 'voice': 'voice', 'comp': 'degree'}


def feature_names(value, prefix, mask, defined):
    base = 'MORPHEUS_' + prefix + '_'
    options = {k[len(base):]: v for k, v in defined.items() if k.startswith(base)}
    if value == 0: return []
    if not mask:
        result = [k.lower() for k, v in options.items() if v == value]
        if len(result) != 1: raise ValueError('Unmapped scalar source value')
        return result
    result = sorted(k.lower() for k, v in options.items() if v > 0 and v & (v-1) == 0 and value & v)
    known = 0
    for v in options.values():
        if v > 0 and v & (v-1) == 0: known |= v
    if value & ~known: raise ValueError('Unmapped source mask bits')
    return result


def transform():
    raw = (D / 'adapter-sources/morph-beta2unicode.xsl').read_bytes()
    parser = etree.XMLParser(resolve_entities=False, no_network=True)
    return etree.XSLT(etree.fromstring(raw, parser), access_control=etree.XSLTAccessControl.DENY_ALL)


def lemma_unicode(beta, convert):
    element = etree.Element('text', {'{http://www.w3.org/XML/1998/namespace}lang': 'grc-x-beta'})
    element.text = beta
    return unicodedata.normalize('NFC', ''.join(convert(element).getroot().itertext()))


def key(lemma):
    return re.sub(r'#(\d+)$', r'\1', unicodedata.normalize('NFC', lemma))


def project(item, raw, defined, convert):
    if len(raw) > 1048576: raise ValueError('Output exceeded authorized bound')
    obj = json.loads(raw)
    if obj['abi_version'] != defined['MORPHEUS_ABI_VERSION'] or obj['options'] != 0 or obj['input_beta'] != item['beta']:
        raise ValueError('Structured output provenance mismatch')
    if obj['candidate_count'] != len(obj['candidates']): raise ValueError('Count mismatch')
    candidates = []
    for index, source in enumerate(obj['candidates']):
        expected_keys = set(FIELDS) | {name+'_hex' for name in TEXT_FIELDS} | {
            'index', 'truncated_fields', 'struct_size', 'morph_flags_hex'}
        if set(source) != expected_keys: raise ValueError('Unsupported public record shape')
        for field in set(FIELDS) | {'index', 'truncated_fields', 'struct_size'}:
            if type(source[field]) is not int or not 0 <= source[field] <= 0xffffffff:
                raise ValueError('Invalid numeric public record')
        if source['index'] != index or source['truncated_fields']:
            raise ValueError('Truncated or reordered candidate')
        strings = {}
        for name, value in source.items():
            if name.endswith('_hex') and name != 'morph_flags_hex':
                body = bytes.fromhex(value)
                if b'\0' in body: raise ValueError('Embedded NUL in text projection')
                try: strings[name[:-4]] = body.decode('ascii')
                except UnicodeDecodeError:
                    if name[:-4] not in ('english_form', 'domains'):
                        raise ValueError('Non-ASCII Beta Code output')
                    strings[name[:-4]] = None
        if not strings.get('lemma') or strings.get('raw') != item['beta']:
            raise ValueError('Missing lemma or mismatched literal source word')
        flags = bytes.fromhex(source['morph_flags_hex'])
        if len(flags) != defined['MORPHEUS_MORPH_FLAG_CAPACITY']:
            raise ValueError('Incomplete public flag vector')
        for bit in range(defined['MORPHEUS_MORPH_FLAG_COUNT'], len(flags)*8):
            if flags[bit//8] & (1 << (bit%8)): raise ValueError('Unknown nonzero public flag')
        names = []
        for name, bit in defined.items():
            if name.startswith('MORPHEUS_MORPH_FLAG_') and name not in ('MORPHEUS_MORPH_FLAG_COUNT', 'MORPHEUS_MORPH_FLAG_CAPACITY'):
                if flags[bit//8] & (1 << (bit%8)): names.append(name.removeprefix('MORPHEUS_MORPH_FLAG_').lower())
        candidates.append({'kind': 'offline_machine_analysis', 'occurrence_attested': False,
            'lemma': lemma_unicode(strings['lemma'], convert), 'source_public_record': source,
            'ascii_text_fields': strings, 'features': {field: feature_names(source[field], prefix, mask, defined)
                for field, (prefix, mask) in FIELDS.items()}, 'morph_flag_names': sorted(names),
            'source_pointer': f'/candidates/{index}'})
    return {'status': 'ok' if candidates else 'no_analyses', 'candidates': candidates}


def shared_compatible(hosted, candidate, defined):
    """Compare only shared declared traits; mask membership permits packed gender/case.

    This does not expand an analysis or assert contextual correctness. Header names
    supply the English symbolic labels; ordinal person labels are compared by their
    explicit 1/2/3 values. Source-specific dialect/stemtype/declension are excluded.
    """
    if key(hosted['lemma']) != key(candidate['lemma']): return False
    for host_field, field in SHARED_FEATURES.items():
        wanted = hosted['features'].get(host_field)
        if not wanted: continue
        prefix, mask = FIELDS[field]
        if field == 'person' and re.fullmatch(r'[123](?:st|nd|rd)', wanted):
            numeric = int(wanted[0])
        else:
            normalized = re.sub('[^a-z]', '', wanted.lower())
            base = 'MORPHEUS_'+prefix+'_'
            matches = {value for name, value in defined.items() if name.startswith(base)
                and re.sub('[^a-z]', '', name[len(base):].lower()) == normalized}
            if len(matches) != 1: return False
            numeric = next(iter(matches))
        actual = candidate['source_public_record'][field]
        mismatch = (actual & numeric != numeric) if mask else (actual != numeric)
        if mismatch: return False
    return True


def main(stage):
    plan = json.loads((D / 'input-plan.json').read_text(encoding='utf-8'))
    if sha((D/'input-plan.json').read_bytes()) != INPUT_SHA: raise ValueError('Input plan changed')
    for name, meta in plan['map_provenance'].items():
        if sha((D/'adapter-sources'/name).read_bytes()) != meta['sha256']: raise ValueError('Mapping changed')
    build = json.loads((D/'runtime-image.json').read_text(encoding='utf-8'))
    if build['status'] != 'built_not_executed': raise ValueError('Unaccepted runtime image')
    defined, convert, rows = constants(), transform(), []
    for item in plan['inputs']:
        if bool(item['reference']) != (stage == 'reference'): continue
        path = D/'runs'/stage/f"{item['id']:04}.stdout"
        raw = path.read_bytes()
        execution = json.loads(path.with_suffix('.json').read_text(encoding='utf-8'))
        if (execution['stdout_sha256'] != sha(raw) or execution['status'] != 'completed'
            or execution['exit_code'] != 0 or execution['oom_killed']
            or execution['stdin_sha256'] != sha((item['beta']+'\n').encode('ascii'))
            or execution['image_id'] != build['runtime_image_id']):
            raise ValueError('Execution receipt mismatch')
        row = project(item, raw, defined, convert)
        row.update({'id': item['id'], 'form': item['form'], 'beta': item['beta'],
                    'source_occurrences': item['occurrences'], 'raw_path': str(path.relative_to(ROOT)),
                    'raw_sha256': sha(raw), 'execution_sha256': sha(path.with_suffix('.json').read_bytes())})
        if item['reference']:
            old = item['reference']['result']
            wanted = Counter(key(c['lemma']) for c in old['machine_candidates'])
            observed = Counter(key(c['lemma']) for c in row['candidates'])
            row['regression'] = {'hosted_receipt': old['receipt']['id'],
                'same_status': old['status'] == row['status'],
                'same_lemma_set': set(wanted) == set(observed),
                'same_lemma_multiset': wanted == observed,
                'missing_lemmas': sorted(set(wanted)-set(observed)),
                'additional_lemmas': sorted(set(observed)-set(wanted)),
                'hosted_candidate_count': sum(wanted.values()),
                'offline_candidate_count': sum(observed.values()),
                'shared_trait_matches': [
                    {'hosted_candidate_index': index, 'offline_candidate_indices': [i for i,c in enumerate(row['candidates'])
                         if shared_compatible(hosted,c,defined)]}
                    for index,hosted in enumerate(old['machine_candidates'])],
                'interpretation': 'Observed lemma inventory/count and shared pofs/person/number/gender/case/tense/mood/voice/degree comparison only, NOT full morphology or contextual correctness. Packed mask membership is allowed; public ABI omits historical stemtype/declension and quantities, and dialect conventions differ. Raw public fields retained for review.'}
            row['regression']['all_hosted_shared_traits_represented'] = all(
                entry['offline_candidate_indices'] for entry in row['regression']['shared_trait_matches'])
        rows.append(row)
    save(D/f'{stage}-projection.json', {'input_plan_sha256': INPUT_SHA,
        'script_sha256': sha(Path(__file__).read_bytes()), 'header_sha256': sha(HEADER.read_bytes()),
        'build_result_sha256': sha((D/'result.json').read_bytes()),
        'runtime_image_receipt_sha256': sha((D/'runtime-image.json').read_bytes()),
        'comparison_scope': 'Literal input, source-preserved public records and observed hosted lemma inventories; no sense/parse selection',
        'results': rows})
    print(json.dumps({'forms': len(rows), 'recognized': sum(r['status']=='ok' for r in rows),
        'candidates': sum(len(r['candidates']) for r in rows),
        'same_lemma_sets': sum(r.get('regression',{}).get('same_lemma_set',False) for r in rows)}))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('stage', choices=('prepare', 'reference', 'corpus'))
    args = parser.parse_args()
    prepare() if args.stage == 'prepare' else main(args.stage)
