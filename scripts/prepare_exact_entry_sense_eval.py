"""Freeze QA19 baseline/current Jev bodies from audited source-only cases; offline.

No Greek, sense gloss, or model prediction is authored here. Source selectors
come from a hash-bound admitted fixture; packet bodies are captured through the
production classifier against the current accepted local indexes. A separate
candidate-specific rubric must be independently approved before any paid run.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import sys
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend import classifier, server
from scripts import prepare_classifier_prompt_eval as qa16_prepare
from scripts import run_classifier_prompt_eval as receipt_io
from scripts import run_exact_entry_sense_eval as qa19


def source_fixture(path, expected_sha):
    target = path.resolve()
    if not target.is_relative_to(ROOT) or not target.is_file():
        raise ValueError('QA19 source fixture must be a local workspace file')
    raw = target.read_bytes()
    if receipt_io.sha(raw) != expected_sha:
        raise ValueError('Audited QA19 source fixture hash changed')
    data = json.loads(raw)
    if (data.get('schema_version') != 1
            or data.get('artifact_type') != 'qa19_homograph_source_evidence'
            or data.get('paid_calls') != 0 or data.get('active_data_changed') is not False):
        raise ValueError('Source fixture is not the admitted source-only artifact')
    return data, target.relative_to(ROOT).as_posix()


def input_manifest(fixture, fixture_relative):
    manifest = deepcopy(fixture.get('input_files') or {})
    names = set(manifest) | qa19.REQUIRED_INPUTS | {fixture_relative}
    for relative in sorted(names):
        target = (ROOT / relative).resolve()
        if not target.is_relative_to(ROOT) or not target.is_file():
            raise ValueError(f'Input missing or outside workspace: {relative}')
        if relative not in manifest:
            manifest[relative] = {'sha256': qa19._file_hash(target),
                                  'bytes': target.stat().st_size}
    # Recheck source-audited file receipts, not merely their filenames.
    qa19.verify_inputs({'input_files': manifest, 'source_fixture': fixture_relative}, ROOT)
    return manifest


def prepare(source_path, source_sha, baseline_revision, control_case_id):
    fixture, fixture_relative = source_fixture(source_path, source_sha)
    rows = fixture.get('cases')
    if (not isinstance(rows, list) or len(rows) != 3
            or control_case_id not in {row.get('id') for row in rows}):
        raise ValueError('Audited three-case source fixture or control selector is missing')
    manifest = input_manifest(fixture, fixture_relative)
    accepted_ids = {claim['id'] for claim in fixture.get('accepted_sense_claims', [])
                    if claim.get('status') == 'source_claim'
                    and claim.get('assertion_type') != 'model_inference'}
    old, old_sha = qa16_prepare.old_module(baseline_revision)
    model = classifier.JEV_MODEL
    original_builder = classifier.build_evidence_packet
    output = []

    class OfflineProvider:
        called = False

        def decide(self, packet):
            self.called = True
            return {'choice':'abstain', 'model':'offline-fixture-no-prediction'}

    def forbidden(*args, **kwargs):
        raise RuntimeError('Network is forbidden in QA19 offline preparation')

    with patch('backend.jev_gateway.public_enabled', return_value=False), \
            patch.object(classifier, 'urlopen', forbidden):
        for source_case in rows:
            case_id, form, passage_id = (source_case.get(key) for key in ('id','form','passage_id'))
            if not all(isinstance(value,str) and value for value in (case_id,form,passage_id)):
                raise ValueError('Audited case identity is incomplete')
            captured = []

            def capture_builder(*args, **kwargs):
                captured.append((deepcopy(args),deepcopy(kwargs)))
                return original_builder(*args, **kwargs)

            provider = OfflineProvider()
            with patch.object(classifier,'build_evidence_packet',capture_builder), \
                    patch.object(classifier,'configured_provider',return_value=provider):
                result = server.classify_context_request(
                    server.ContextRequest(form=form,passage_id=passage_id),None)
            if len(captured)!=1 or not provider.called or result.get('decision_stage')!='model_abstained':
                raise ValueError(f'Case is not model-eligible without a paid call: {case_id}')
            args, kwargs = captured[0]
            before = old.build_evidence_packet(*args, **kwargs)
            after = result['packet']
            sense_ids = set(qa19._sense_ids(after))
            if not sense_ids or not sense_ids.issubset(accepted_ids):
                raise ValueError(f'Unaccepted or missing exact-entry sense claim in {case_id}')
            qa19._validate_sense_payload(before,sense_ids,old=True)
            qa19._validate_sense_payload(after,sense_ids)
            if qa19._without_sense_enrichment(before,sense_ids) != \
                    qa19._without_sense_enrichment(after,sense_ids):
                raise ValueError(f'Non-sense evidence changed between arms: {case_id}')
            old_body = qa16_prepare.request_body(old,before,model)
            new_body = qa16_prepare.request_body(classifier,after,model)
            old_question = old_body['questions']['contextual_parse']
            new_question = new_body['questions']['contextual_parse']
            if (qa19._request_envelope(old_body)!=qa19._request_envelope(new_body)
                    or set(old_question['criteria'])!=set(new_question['criteria'])
                    or qa19._without_sense_descriptions(old_question['criteria'])!=
                       qa19._without_sense_descriptions(new_question['criteria'])):
                raise ValueError(f'Model, prompt, or grammar options changed: {case_id}')
            role = 'control' if case_id==control_case_id else 'homograph_context'
            output.append({'id':case_id,'role':role,'form':form,'passage_id':passage_id,
                           'entry_sense_claim_ids':sorted(sense_ids),
                           'old_request':old_body,'new_request':new_body})
    return {'schema_version':1,'artifact_type':qa19.ARTIFACT_TYPE,
            'purpose':'Source-bound, offline QA19 paired packet pilot; not a corpus dataset or model prediction',
            'source_fixture':fixture_relative,'source_fixture_sha256':source_sha,
            'input_files':manifest,'baseline_revision':baseline_revision,
            'classifier_sha256':{'old':old_sha,
                                 'new':qa19._file_hash(Path(classifier.__file__))},
            'model':model,'paid_calls':0,'review_status':'pending_independent_case_rubric',
            'cases':output}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-fixtures',type=Path,required=True)
    parser.add_argument('--source-sha256',required=True)
    parser.add_argument('--baseline',required=True)
    parser.add_argument('--control-case-id',required=True)
    parser.add_argument('--output',type=Path,required=True)
    args = parser.parse_args()
    target = args.output.resolve()
    if (not target.is_relative_to((ROOT/'data/staging').resolve())
            or 'qa19' not in target.as_posix().lower() or target.exists()):
        raise SystemExit('Choose a new, empty QA19 path under data/staging')
    artifact = prepare(args.source_fixtures,args.source_sha256,args.baseline,args.control_case_id)
    target.parent.mkdir(parents=True,exist_ok=True)
    target.write_text(json.dumps(artifact,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({'cases':len(artifact['cases']),'paid_calls':0,
                      'path':str(target),'sha256':qa19._file_hash(target),
                      'request_bytes':{case['id']:{arm:len(receipt_io.encode(case[f'{arm}_request']))
                                                  for arm in ('old','new')}
                                       for case in artifact['cases']}}))


if __name__=='__main__':
    main()
