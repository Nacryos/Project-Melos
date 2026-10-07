import test from 'node:test';
import assert from 'node:assert/strict';
import vm from 'node:vm';
import { readFileSync } from 'node:fs';
const scope = vm.createContext({ window: {}, URL });
vm.runInContext(readFileSync(new URL('../js/dictionary-preview.js', import.meta.url), 'utf8'), scope);
const project = scope.window.MelosDictionaryPreview.lexicalVariantPreview;
// Purely synthetic records exercise source-identity mechanics, not Greek gold.
function fixture() {
  const entry = 'wiktionary:kaikki:line:1', form = 'ά', lemma = 'β', source_family = 'enwiktionary-kaikki-ancient-greek-fixture';
  const relation = { id: `${entry}:dialect_form:0`, predicate: 'dialect_label', subject: { form }, object: { lemma, source_form: { form } } };
  const head = { id: `${entry}:lemma:entry`, predicate: 'lemma', subject: { form: lemma }, object: { lemma } };
  const morphology = { id: `${entry}:morphology:entry`, predicate: 'morphology', object: { lemma } };
  const sense = { claim_id: `${entry}:sense:0`, entry_id: entry, source_sense_id: 'en-fixture-0',
    scope: 'general_dictionary_entry_not_contextually_adjudicated', glosses: ['synthetic lexical meaning'],
    source_url: 'https://example.test/english-dictionary', locator: '/entry/senses/0/glosses', quote: '["synthetic lexical meaning"]' };
  const claim = { id: sense.claim_id, predicate: 'sense_gloss', subject: { form: lemma },
    source_family, object: { lemma, glosses: sense.glosses }, evidence: [{ locator: sense.locator, quote: sense.quote, source_url: sense.source_url }] };
  const variant = { id: relation.id + ':lexical-variant', candidate_kind: 'dictionary_variant', status: 'source_claim',
    assertion_type: 'extracted_annotation', scope: 'exact_source_listed_lexical_variant_not_morphological_parse',
    source_family, entry_id: entry, matched_form: form, matched_object_form: { form }, lemma, entry_headword: lemma,
    analysis: null, features: null, claim_ids: [relation.id, head.id, morphology.id], entry_sense_claim_ids: [sense.claim_id], entry_senses: [sense] };
  return { form, variants: [variant], claims: [relation, head, morphology, claim] };
}
test('exact sourced lexical variant supplies literal English meanings with no parse inference', () => {
  const f = fixture(), result = project(f.form, f.variants, f.claims);
  assert.equal(result.length, 1); assert.equal(result[0].meanings[0].text, 'synthetic lexical meaning');
  assert.equal(result[0].parse, undefined); assert.equal(result[0].features, undefined);
  assert.equal(result[0].meanings[0].claim_id, f.variants[0].entry_sense_claim_ids[0]);
});
test('wrong accents, entries, missing proof, and invented glosses fail closed', () => {
  for (const change of [f => { f.form = 'α'; }, f => { f.variants[0].entry_senses[0].entry_id = 'other'; },
    f => { f.claims.pop(); }, f => { f.variants[0].entry_senses[0].glosses = ['invented']; },
    f => { f.variants[0].entry_senses[0].source_url = 'javascript:alert(1)'; },
    f => { f.claims.push(f.claims[0]); }, f => { f.variants[0].lemma = 'γ'; }]) {
    const f = fixture(); change(f); assert.equal(project(f.form, f.variants, f.claims).length, 0);
  }
});
test('unresolved crossreferences or morphology are not lexical variant meaning proof', () => {
  for (const change of [f => { f.variants[0].candidate_kind = 'dictionary_crossreference'; },
    f => { f.variants[0].features = { Case: 'Nom' }; }, f => { f.variants[0].scope = 'unresolved_dictionary_crossreference'; }]) {
    const f = fixture(); change(f); assert.equal(project(f.form, f.variants, f.claims).length, 0);
  }
});
test('nested inherited glosses and non-English metadata cannot leak into variant English previews', () => {
  for (const change of [f => { f.variants[0].entry_senses[0].glosses.push('nested'); },
    f => { f.variants[0].entry_senses[0].source_sense_id = 'el-fixture-0'; },
    f => { f.variants[0].entry_senses[0].tags = ['form-of']; }]) {
    const f = fixture(); change(f); assert.equal(project(f.form, f.variants, f.claims).length, 0);
  }
});
