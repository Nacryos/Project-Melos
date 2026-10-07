import test from 'node:test';
import assert from 'node:assert/strict';
import vm from 'node:vm';
import { readFileSync } from 'node:fs';

const context = vm.createContext({ window: {}, URL });
vm.runInContext(readFileSync(new URL('../js/dictionary-preview.js', import.meta.url), 'utf8'), context);
vm.runInContext(readFileSync(new URL('../js/word-context.js', import.meta.url), 'utf8'), context);
const { linkedDictionaryCandidates: candidates, linkedDictionaryGroups: groups } = context.window.MelosDictionaryPreview;
// Synthetic source fixtures exercise transport/identity, not Greek scholarship.
function fixture() {
  const path = { source_entry_id: 'source:1', source_headword: 'α', target_entry_id: 'target:1',
    target_headword: 'β', target_etymology_number: 1, relation_id: 'relation:1',
    query_anchor: { source_form: { form: 'α' }, claim_id: 'claim:1' }, claim_ids: ['claim:1'],
    match_method: 'exact_source_form_crossreference', source_dictionary_pos: 'noun', target_dictionary_pos: 'noun', literal_pos_agreement: true };
  const sense = { id: 'linked-sense:' + '1'.repeat(64), entry_id: 'target:1', text: 'Synthetic meaning',
    language: 'eng', evidence_type: 'dictionary_sense', source: 'Synthetic source', source_url: 'https://example.test/source',
    source_locator: 'sense:0', raw_sha256: 'a'.repeat(64), linked_path: { ...path, sense_claim_id: 'target:1:sense:0' } };
  const candidate = { id: 'linked-path:' + '2'.repeat(64), candidate_id: 'linked-path:' + '2'.repeat(64),
    lemma: 'α', features: { POS: 'NOUN', Case: 'Gen' }, parse_short: 'gen.', basis: 'source_linked_dictionary_path',
    linked_path: path, gloss_entry_id: 'target:1', senses: [sense] };
  return { form: 'α', method: 'source-linked-dictionary-inventory-v1', inventory_sha256: 'b'.repeat(64),
    scope: 'source_linked_candidates_not_exact_surface_or_contextual_attestation', candidates: [candidate] };
}
test('literal target senses require complete query, path and source binding', () => {
  assert.equal(candidates('α', fixture()).length, 1);
  for (const mutate of [x => x.form = 'ά', x => x.candidates[0].gloss_entry_id = 'other',
    x => x.candidates[0].senses[0].linked_path.target_entry_id = 'other',
    x => x.candidates[0].senses[0].source_url = 'javascript:bad()',
    x => x.candidates[0].senses[0].raw_sha256 = '',
    x => x.candidates[0].linked_path.query_anchor.source_form.form = 'ά']) {
    const data = fixture(); mutate(data); assert.equal(candidates('α', data).length, 0);
  }
});
test('audited linked inventory v1 and v2 share strict lexical source binding; unknown versions fail', () => {
  for (const method of ['source-linked-dictionary-inventory-v1','source-linked-dictionary-inventory-v2']) {
    const data=fixture();data.method=method;assert.equal(candidates('α',data).length,1);
    data.candidates[0].senses[0].linked_path.target_entry_id='other';assert.equal(candidates('α',data).length,0);
  }
  const data=fixture();data.method='source-linked-dictionary-inventory-v3';assert.equal(candidates('α',data).length,0);
});
test('v2 noun gender metadata binds to the anchor entry, never a target homonym or contextual prediction', () => {
  const make=()=>{const data=fixture(),c=data.candidates[0];data.method='source-linked-dictionary-inventory-v2';c.features.Gender='Masc';
    c.linked_path.source_noun_metadata={entry_id:'source:1',entry_headword:'α',dictionary_pos:'noun',
      method:'same-entry-noun-gender-v1',scope:'same_source_noun_entry_metadata_not_occurrence_disambiguation',
      contextually_selected:false,source_record_proof:{record_id:'source:1',raw_sha256:'a'.repeat(64),parent_sha256:'b'.repeat(64),source_url:'https://example.test/raw'},
      supporting_claim_ids:['source:1:morphology:entry'],evidence_groups:[{claim_id:'source:1:morphology:entry',source_locator:'/entry/forms/0/tags'}],
      applied_to_candidate:true,gender_status:'single_source_gender',explicit_form_gender:null,application_basis:'same_anchor_noun_metadata',
      dictionary_gender_options:['masculine'],unambiguous_entry_gender:'masculine'};return data;};
  assert.equal(candidates('α',make()).length,1);
  for(const change of [n=>n.entry_id='target:1',n=>n.contextually_selected=true,n=>n.dictionary_gender_options.push('feminine'),
    n=>n.source_record_proof.parent_sha256='',n=>n.evidence_groups[0].claim_id='target:1:morphology:entry']){
    const data=make();change(data.candidates[0].linked_path.source_noun_metadata);assert.equal(candidates('α',data).length,0);
  }
  const missing=make();delete missing.candidates[0].linked_path.source_noun_metadata;
  assert.equal(candidates('α',missing).length,0);
  const conflicting=make();conflicting.candidates[0].linked_path.query_anchor.source_form.tags=['feminine'];
  assert.equal(candidates('α',conflicting).length,0);
  const explicit=make();delete explicit.candidates[0].linked_path.source_noun_metadata;
  explicit.candidates[0].linked_path.query_anchor.source_form.tags=['masculine'];
  assert.equal(candidates('α',explicit).length,1);
});
test('printed spelling aliases require the literal hyperlink destination, not accent folding', () => {
  const data = fixture(), path = data.candidates[0].linked_path;
  Object.assign(path, { match_method: 'literal_source_form_link', alias_id: 'alias:1', printed_form: 'ά', source_link: ['ά', 'α#Ancient_Greek'] });
  path.query_anchor.source_form.form = 'ά';
  assert.equal(candidates('α', data).length, 1);
  path.source_link[1] = 'ά#Ancient_Greek'; assert.equal(candidates('α', data).length, 0);
});
test('six repeated paradigms become two analyses retaining every path, while homonyms stay separate', () => {
  const data = fixture(), original = data.candidates[0];
  data.candidates = Array.from({ length: 6 }, (_, index) => {
    const c = structuredClone(original); c.id = c.candidate_id = 'linked-path:' + String(index).repeat(64);
    c.features.Number = index % 2 ? 'Sing' : 'Plur'; return c;
  });
  const grouped = groups('α', data);
  assert.equal(grouped.length, 2); assert.equal(grouped.reduce((n, g) => n + g.candidates.length, 0), 6);
  assert.equal(grouped[0].meanings.length, 1); assert.equal(grouped[0].meanings[0].supporting_candidate_ids.length, 3);
  const homonym = structuredClone(original); homonym.id = homonym.candidate_id = 'linked-path:' + '9'.repeat(64);
  homonym.gloss_entry_id = homonym.linked_path.target_entry_id = 'target:2';
  homonym.senses[0].entry_id = homonym.senses[0].linked_path.target_entry_id = 'target:2';
  homonym.senses[0].linked_path.sense_claim_id = 'target:2:sense:0';
  data.candidates.push(homonym); assert.equal(groups('α', data).length, 3);
});
function contextual() {
  const inventory = fixture(), c = inventory.candidates[0], sense = c.senses[0];
  const body = { passage_id: 'p', selected_text: 'α', start: 0, end: 1 };
  const token = { id: 't', kind: 'word', text: 'α', start_utf16: 0, end_utf16: 1, linked_dictionary: inventory };
  const row = { ...token, token_id: 't', status: 'ambiguous', candidate_id: null, source_candidate: null,
    gloss: { status: 'available', selection_basis: 'jev_contextual_sense_proposal', sense_id: sense.id,
      entry_id: sense.entry_id, text: sense.text, alternatives: [structuredClone(sense)], supporting_candidate_ids: [c.id] } };
  return { body, data: { passage: { id: 'p' }, selection: { text: 'α', start_utf16: 0, end_utf16: 1 },
    tokens: [token], interlinear: { readings: [{ tokens: [row] }] }, sense_ranking: { items: [{ token_id: 't', status: 'proposed', selected_sense_id: sense.id }] } } };
}
test('Jev linked sense remains visible without fabricating a selected parse', () => {
  const { body, data } = contextual(), proposal = context.window.MelosWordContext.checkedProposal(data, body);
  assert.equal(proposal.text, 'Synthetic meaning'); assert.equal(proposal.parse, ''); assert.equal(proposal.lemma, '');
});
test('changed target text and wrong homonym cannot pass contextual linked validation', () => {
  for (const change of [row => { row.gloss.entry_id = 'wrong'; row.gloss.alternatives[0].entry_id = 'wrong'; },
    row => { row.gloss.text = row.gloss.alternatives[0].text = 'Invented meaning'; }]) {
    const { body, data } = contextual(); change(data.interlinear.readings[0].tokens[0]);
    assert.equal(context.window.MelosWordContext.checkedProposal(data, body), null);
  }
});
test('incompatible source/target parts of speech never supply a contextual parse', () => {
  const { body, data } = contextual(), c = data.tokens[0].linked_dictionary.candidates[0], row = data.interlinear.readings[0].tokens[0];
  c.linked_path.literal_pos_agreement = false; c.linked_path.target_dictionary_pos = 'adj';
  Object.assign(row, { status: 'selected', candidate_id: c.id, source_candidate: c, parse_short: 'incorrect contextual parse' });
  assert.equal(context.window.MelosWordContext.checkedProposal(data, body).parse, '');
});
test('linked contextual citation and scope must be the original inventory sense metadata', () => {
  for (const change of [sense => { sense.source_url = 'https://example.test/invented'; },
    sense => { sense.raw_sha256 = 'f'.repeat(64); }, sense => { sense.source_locator = 'invented'; },
    sense => { sense.linked_path.target_headword = 'invented'; }, sense => { sense.scope_text = ['Invented scope']; }]) {
    const { body, data } = contextual(); change(data.interlinear.readings[0].tokens[0].gloss.alternatives[0]);
    assert.equal(context.window.MelosWordContext.checkedProposal(data, body), null);
  }
});
test('ordinary inspector exposes meanings compactly, with proof collapsed and text safely escaped', () => {
  class Element { constructor(tag, cls='', text='') { Object.assign(this, {tag, cls, text, children: []}); }
    append(...children) { this.children.push(...children); } get textContent() { return this.text + this.children.map(c => c.textContent).join(''); } }
  const node = (...args) => new Element(...args), scope = vm.createContext({ window: context.window, node,
    safeLink: (url, label) => Object.assign(node('a','',label), {href:url}) });
  const source = readFileSync(new URL('../js/reader.js', import.meta.url), 'utf8');
  vm.runInContext(source.slice(source.indexOf('  function renderDictionaryPreview('), source.indexOf('  async function loadDictionaryPreview(')), scope);
  const data = {form:'α', linked_dictionary:fixture()}, host=node('div');
  data.linked_dictionary.candidates[0].senses[0].text='<img onerror=bad()> Literal source text';
  assert.equal(scope.renderDictionaryPreview(host,data),true);
  const flatten = e => [e,...e.children.flatMap(flatten)], elements=flatten(host);
  assert.ok(host.textContent.includes('Possible meanings')); assert.ok(host.textContent.includes('<img onerror=bad()>'));
  assert.equal(elements.some(e=>e.tag==='img'),false); assert.equal(elements.find(e=>e.tag==='details').open,undefined);
  assert.equal(elements.filter(e=>e.cls==='dictionary-glimpse-entry').length,1);
});
