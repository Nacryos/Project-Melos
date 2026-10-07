import test from 'node:test';
import assert from 'node:assert/strict';
import vm from 'node:vm';
import {readFileSync} from 'node:fs';
const context=vm.createContext({window:{},URL});
vm.runInContext(readFileSync(new URL('../js/dictionary-preview.js',import.meta.url),'utf8'),context);
const {buildPreview,candidateDefinitionExcerpt,definitionExcerpt}=context.window.MelosDictionaryPreview;
const fixture=()=>JSON.parse(readFileSync(new URL('./fixtures/word-elthes-tense-preview.json',import.meta.url),'utf8'));
const lsj=data=>data.lexicon_entries.find(entry=>entry.id==='lsj:5:n42827');
const headline=preview=>preview.compact.entries.flatMap(entry=>entry.meanings.map(meaning=>meaning.text));
test('real source-known aorist headlines come/go but preserves every original dictionary sense',()=>{
  const data=fixture(),before=JSON.stringify(data),preview=buildPreview(data),entry=preview.entries.find(entry=>entry.id==='lsj:5:n42827');
  assert.equal(headline(preview)[0],'come or go');assert.equal(entry.form_restricted_sense_ids.length,2);
  assert.equal(entry.meanings[0].text,'start, set out');assert.equal(entry.meanings[1].text,'walk');
  assert.equal(entry.meanings.length,lsj(data).dictionary_senses.length);assert.ok(preview.compact.omitted_meaning_count>0);
  assert.equal(JSON.stringify(data),before);
});
test('tampered, incomplete and legacy restriction metadata cannot exclude source definitions',()=>{
  for(const change of [(restriction)=>restriction.raw_sha256='0'.repeat(64),r=>r.lexicon_entry_id='homonym:2',
    r=>r.entry_id='wrong',r=>r.source_url='https://example.test/not-source',r=>r.source_text='Invented restriction',
    r=>r.allowed_values=['Past'],r=>r.scope.target_source_sense_ids=['other:1','other:2'],
    r=>r.source_locator.rendered_end=r.source_locator.rendered_start-1,r=>r.tense_source_locator.offset_basis='other',
    r=>delete r.raw_path,r=>r.extraction_rule='guessed_scope']){
    const data=fixture();for(const sense of lsj(data).dictionary_senses)for(const restriction of sense.morphology_restrictions||[])change(restriction);
    assert.equal(headline(buildPreview(data))[0],'start, set out');
  }
  for(const change of [sense=>delete sense.morphology_restrictions,sense=>sense.extraction_method='tei-definition-spans-v3']){
    const data=fixture();lsj(data).dictionary_senses.forEach(change);assert.equal(headline(buildPreview(data))[0],'start, set out');
  }
});
test('a genuine competing present or unknown source analysis preserves compact alternatives',()=>{
  for(const tense of ['Pres',null]){
    const data=fixture(),alternative=structuredClone(data.candidates[0]);
    alternative.analysis='';alternative.analysis_text='';alternative.features=tense?{Tense:tense}:{};
    data.candidates.push(alternative);assert.equal(headline(buildPreview(data))[0],'start, set out');
  }
  const data=fixture();data.candidates[0].features={Tense:['Aor','unknown']};
  assert.equal(headline(buildPreview(data))[0],'start, set out');
});
test('syntax/model-only morphology and accent-normalized matches do not constrain dictionary headlines',()=>{
  for(const change of [candidate=>candidate.candidate_kind='machine_analysis',candidate=>candidate.basis='machine_analysis',
    candidate=>candidate.matched_form='ἤλθες']){
    const data=fixture();change(data.candidates[0]);assert.equal(headline(buildPreview(data))[0],'start, set out');
  }
});
test('explicit present source morphology retains both source-restricted meanings',()=>{
  const data=fixture();data.candidates[0].analysis_text='verb · present';data.candidates[0].features={Tense:'Pres'};
  assert.equal(headline(buildPreview(data))[0],'start, set out');
});
test('rule does not use matching English words to infer an unmarked restriction',()=>{
  const data=fixture();for(const sense of lsj(data).dictionary_senses)delete sense.morphology_restrictions;
  // The complete rendered entry still contains the genuine present-only note.
  assert.match(lsj(data).rendered_entry_text,/the two foreg\./);
  assert.equal(headline(buildPreview(data))[0],'start, set out');
});
test('ambiguous raw abbreviations do not become canonical tense evidence',()=>{
  for(const tag of ['imp','perf']){
    const data=fixture(),candidate=data.candidates[0];candidate.analysis_text='';candidate.source_tags=[tag];delete candidate.features;
    assert.equal(headline(buildPreview(data))[0],'start, set out');
  }
});

test('candidate excerpt uses the same source restriction while the full definition remains unchanged',()=>{
  const data=fixture(),entry=lsj(data),before=JSON.stringify(data);
  const result=candidateDefinitionExcerpt(entry,data.candidates[0],data.form);
  assert.equal(result.text,'come or go');
  assert.equal(result.provenance.id,entry.dictionary_senses[2].id);
  assert.equal(definitionExcerpt(entry).text,'start, set out');
  assert.equal(JSON.stringify(data),before);
});

test('candidate excerpt does not borrow a competing candidate tense or invent exact linkage',()=>{
  const data=fixture(),candidate=data.candidates[0],entry=lsj(data);
  for(const change of [row=>{row.features={Tense:'Pres'};row.analysis_text='verb · present';},
    row=>{row.features={};row.analysis_text='';},row=>row.candidate_kind='machine_analysis',
    row=>row.lemma='unrelated',row=>{row.gloss_entry_id='other';row.lexicon_entry_ids=[];},
    row=>row.lemma_link_status='ambiguous_source_lemmas',row=>row.matched_form='ἤλθες']){
    const other=structuredClone(candidate);change(other);
    assert.equal(candidateDefinitionExcerpt(entry,other,data.form).text,'start, set out');
    assert.equal(candidateDefinitionExcerpt(entry,candidate,data.form).text,'come or go');
  }
  assert.equal(candidateDefinitionExcerpt(entry,candidate,undefined).text,'start, set out');
});

test('candidate excerpt preserves source order when restriction provenance cannot be validated',()=>{
  for(const mutate of [row=>delete row.morphology_restrictions,
    row=>{for(const restriction of row.morphology_restrictions||[])restriction.raw_sha256='0'.repeat(64);},
    row=>row.extraction_method='tei-definition-spans-v3']){
    const data=fixture(),entry=lsj(data);entry.dictionary_senses.forEach(mutate);
    assert.equal(candidateDefinitionExcerpt(entry,data.candidates[0],data.form).text,'start, set out');
  }
});
