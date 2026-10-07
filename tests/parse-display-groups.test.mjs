import test from 'node:test';
import assert from 'node:assert/strict';
import vm from 'node:vm';
import {readFileSync} from 'node:fs';
const context=vm.createContext({window:{},AbortController});
vm.runInContext(readFileSync(new URL('../js/passage-analysis.js',import.meta.url),'utf8'),context);
const {groupCandidateDisplays:group,dedupeCandidates:dedupe,renderPartialCandidateEvidence:render}=context.window.MelosPassageAnalysis;
const actual=()=>JSON.parse(readFileSync(new URL('./fixtures/elthes-parse-display.json',import.meta.url),'utf8'));
const reader=readFileSync(new URL('../js/reader.js',import.meta.url),'utf8');
vm.runInContext(reader.slice(reader.indexOf('  function groupWiktionaryMatches('),reader.indexOf('  function renderWiktionary(')),context);
const wikiGroups=vm.runInContext('groupWiktionaryMatches',context);
const synthetic=(features,extra={})=>({id:'synthetic',lemma:'fixture',matched_form:'α',status:'source_claim',assertion_type:'extracted_annotation',
  claim_ids:['fixture:claim'],evidence_refs:['fixture'],features,...extra});

test('actual source records reduce display repetition without changing morphology or losing source IDs',()=>{
  const data=actual(),raw=[...data.source_candidates,...data.contextual_candidates],before=JSON.stringify(raw);
  const unique=dedupe(raw),display=group(unique);
  assert.equal(raw.length,6);assert.equal(unique.length,4);assert.equal(display.length,3);
  const full=display.find(row=>row.partial_evidence_rows?.length);
  assert.equal(full.partial_evidence_rows.length,3);
  assert.ok(full.analysis.includes('aorist'));
  assert.ok(full.partial_evidence_rows.every(row=>!row.analysis.includes('aorist')));
  assert.ok(display.some(row=>row.lemma==='ἦλθον' && !row.partial_evidence_rows));
  const sourceIds=raw.map(row=>row.id).filter(Boolean).sort();
  const displayIds=display.flatMap(row=>[...(row.evidence_rows||[row]),...(row.partial_evidence_rows||[])]).map(row=>row.id).filter(Boolean).sort();
  assert.deepEqual(Array.from(displayIds),sourceIds);assert.equal(JSON.stringify(raw),before);
});

test('conflicts, different homographs and unverified source/machine records stay separate',()=>{
  const partial=synthetic({Person:'2',Number:'Sing'});
  for(const extra of [{features:{Person:'3',Number:'Sing',Tense:'Aor'}},{homograph_id:'2'},{homograph_id:2},{lemma_identity:'different'},
    {lemma_raw:'fixture1'},{matched_form:'ά'},{lemma:'other'}, {candidate_kind:'machine_analysis'},
    {assertion_type:'model_inference'},{status:'proposed'},{source_raw_tags:['Aeolic']},{edit_distance:1},{match_kind:'normalized'},
    {source_tags:['unknown source abbreviation']},{features:{Person:'2',Number:'Sing',Tense:'unknown'}}]){
    const full=synthetic({Person:'2',Number:'Sing',Tense:'Aor'},extra);
    assert.equal(group([partial,full]).length,2,JSON.stringify(extra));
  }
  assert.equal(group([synthetic({Case:'Acc'}),synthetic({Case:'Nom',Number:'Sing'})]).length,2);
  assert.equal(group([synthetic({Tense:'Pres'}),synthetic({Tense:'Aor',Person:'2'})]).length,2);
  assert.equal(group([synthetic({}),synthetic({Person:'2',Number:'Sing'})]).length,2);
});

test('multiple fuller readings do not assign a partial record to one by source order',()=>{
  const rows=[synthetic({Person:'2'}),synthetic({Person:'2',Tense:'Pres'}),synthetic({Person:'2',Tense:'Aor'})];
  assert.equal(group(rows).length,3);assert.equal(group(rows.reverse()).length,3);
});

test('exact dedupe cannot hide model, normalized or conflicting-dialect scope before partial grouping',()=>{
  const partial=synthetic({Person:'2'},{id:'source-partial'}),full=synthetic({Person:'2',Tense:'Aor'},{id:'source-full'});
  for(const mutation of [{candidate_kind:'machine_analysis',assertion_type:'model_inference'},
    {match_kind:'normalized',edit_distance:1},{dialect:'Doric'},{source_raw_tags:['Doric']}]){
    const other={...partial,id:'different-scope',...mutation},groups=group(dedupe([partial,other,full]));
    assert.equal(groups.length,2);
    const nested=groups.find(row=>row.id==='source-full').partial_evidence_rows;
    assert.deepEqual(Array.from(nested,row=>row.id),['source-partial']);
    assert.ok(groups.some(row=>row.id==='different-scope'));
    // Even a malformed pre-deduplicated payload cannot smuggle this member in.
    assert.equal(group([{...partial,evidence_rows:[partial,other]},full]).length,2);
  }
});

test('same-entry actual identical table matches collapse while all original table indices remain available',()=>{
  const data=JSON.parse(readFileSync(new URL('./fixtures/wiktionary-elthes-live.json',import.meta.url),'utf8'));
  const source=data.results.find(row=>row.headword==='ἔρχομαι'),before=JSON.stringify(source),groups=wikiGroups(source.matches);
  assert.equal(groups.length,1);assert.deepEqual(Array.from(groups[0].records,row=>row.match.form_index),[240,279,335]);
  assert.equal(JSON.stringify(source),before);
  for(const change of [row=>row.form.tags.push('aorist'),row=>row.form.form='ἤλθες',row=>row.form.source='other',row=>row.form.raw_tags=['Doric']]){
    const other=structuredClone(source.matches[0]);change(other);assert.equal(wikiGroups([source.matches[0],other]).length,2);
  }
  assert.match(reader,/for \(const \{match,records\} of groupWiktionaryMatches\(matches\)\)/);
});

test('partial evidence is closed by default and preserves literal source data as text',()=>{
  class Element {constructor(tag,cls='',text=''){Object.assign(this,{tag,cls,text,children:[]});}append(...items){this.children.push(...items);}}
  const row=synthetic({Person:'2'}, {analysis:'<b>source</b>'}),host=new Element('div');
  render(host,{partial_evidence_rows:[row]},(...args)=>new Element(...args));
  const panel=host.children[0];assert.equal(panel.tag,'details');assert.equal(panel.open,undefined);
  assert.match(panel.children[1].text,/not a combined or contextually verified parse/);
  assert.equal(panel.children[2].children[0].text,'<b>source</b>');
  assert.deepEqual(JSON.parse(panel.children[2].children[2].text),row);
});
