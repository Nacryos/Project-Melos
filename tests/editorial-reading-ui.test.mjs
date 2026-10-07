import test from 'node:test';
import assert from 'node:assert/strict';
import vm from 'node:vm';
import {readFileSync} from 'node:fs';
import {createHash,webcrypto} from 'node:crypto';
const hash=text=>createHash('sha256').update(text).digest('hex');
const context=vm.createContext({window:{},URL,AbortController,crypto:webcrypto,TextEncoder});
vm.runInContext(readFileSync(new URL('../js/passage-analysis.js',import.meta.url),'utf8'),context);
const {verifiedEditorialRows,renderEditorialAnalysis,renderEditorialWordActions}=context.window.MelosPassageAnalysis;
class Element{constructor(tag,cls='',text=''){Object.assign(this,{tag,cls,text,children:[],events:{}});}append(...children){this.children.push(...children);}
  addEventListener(name,fn){this.events[name]=fn;}get textContent(){return this.text+this.children.map(child=>child.textContent).join('');}}
const node=(...args)=>new Element(...args),safeLink=(url,label)=>Object.assign(node('a','',label),{href:url});
const flatten=e=>[e,...e.children.flatMap(flatten)];
// Entirely synthetic Greek/source fixtures test identity and UI, not restorations.
function fixture(){
  const text='𐀀 [α]β γ',passage={id:'fixture:p',text,edition:'Synthetic edition',source_url:'https://example.test/poem',metadata:{transcription_uncertainty:[]}};
  const chars=[...text],start=2,end=6,utf=i=>chars.slice(0,i).join('').length,original=chars.slice(start,end).join('');
  const row={id:`fixture:p@${start}:${end}:editorial`,passage_id:passage.id,start,end,start_utf16:utf(start),end_utf16:utf(end),
    original_text:original,original_text_sha256:hash(original),source_text_sha256:hash(text),source_url:passage.source_url,edition:passage.edition,
    projected_text:'αβ',character_source_map:[{projected_start:0,projected_end:1,source_start:3,source_end:4,source_start_utf16:utf(3),source_end_utf16:utf(4),printed_inside_square_brackets:true},
      {projected_start:1,projected_end:2,source_start:5,source_end:6,source_start_utf16:utf(5),source_end_utf16:utf(6),printed_inside_square_brackets:false}],square_bracket_pairs:[{open:2,close:4}],
    evidence_type:'printed_editorial_projection',status:'conditional_editorial_reading',lookup_eligible:true,word_attestation:false,line_attestation:false,
    occurrence_verified:false,raw_surface_match:false,analysis_basis:'conditional_on_printed_editorial_reading',structural_errors:[],uncertainty_reasons:[],source_uncertainty_notes:[],uncertainty_note_sha256:hash('[]'),
    selection_relation:'fully_contained',lookup_status:'complete'};
  const sense={id:'sense:1',entry_id:'entry:1',text:'Synthetic literal definition',language:'eng',evidence_type:'dictionary_sense',source:'Fixture dictionary',
    source_url:'https://example.test/dictionary',source_locator:'/entry/sense/1',raw_sha256:'a'.repeat(64)};
  row.analysis={status:'available',lookup_form:'αβ',lookup_scope:'general_form_no_passage',analysis_basis:'conditional_on_printed_editorial_reading',word_attestation:false,occurrence_verified:false,raw_surface_match:false,
    syntax_status:'not_requested',ranking_status:'not_requested',candidate_count:1,candidate_meanings:[{candidate_id:'candidate:1',lemma:'α',features:{Case:'Gen'},parse_short:'gen.',
      basis:'conditional_editorial_lookup',source_basis:'source_alternative',status:'conditional_alternative',word_attestation:false,occurrence_verified:false,raw_surface_match:false,
      source_provenance:{source:'Fixture parser',source_url:'https://example.test/parser',analysis_text:'source recorded genitive'},gloss:{entry_id:'entry:1',alternatives:[sense]}}]};
  passage.editorial_readings={version:1,passage_id:passage.id,source_text_sha256:hash(text),rows:[structuredClone(row)]};
  const data={passage:{id:passage.id,text_sha256:hash(text)},selection:{text:original,start_utf16:utf(start),end_utf16:utf(end)},editorial_analysis:{version:1,scope:'conditional_editorial_readings',passage_id:passage.id,
    source_text_sha256:hash(text),selection:{start,end,offset_unit:'codepoint',text_sha256:hash(original)},rows:[row],selection_expansion_hints:[],limits:{machine_fetches:0},ranking_status:'not_requested'}};
  return {passage,row,data};
}
test('exact source-bound projection retains original brackets and Unicode codepoint/UTF16 distinction',async()=>{
  const f=fixture(),before=JSON.stringify(f),rows=await verifiedEditorialRows(f.passage,f.passage.editorial_readings);
  assert.equal(rows.length,1);assert.equal(rows[0].original_text,'[α]β');assert.equal(rows[0].start_utf16,3);assert.equal(JSON.stringify(f),before);
});
test('changed passage, edition, uncertainty, character maps or hashes cannot render source projections',async()=>{
  for(const change of [f=>f.passage.text='changed',f=>f.passage.edition='other',f=>f.passage.metadata.transcription_uncertainty=['changed'],
    f=>f.passage.editorial_readings.rows[0].start_utf16=2,f=>f.passage.editorial_readings.rows[0].original_text='αβ',
    f=>f.passage.editorial_readings.rows[0].character_source_map[0].source_start=5,
    f=>f.passage.editorial_readings.rows[0].projected_text='αγ',f=>f.passage.editorial_readings.rows[0].word_attestation=true]){
    const f=fixture();change(f);assert.equal((await verifiedEditorialRows(f.passage,f.passage.editorial_readings)).length,0);
  }
});
test('conditional sourced meanings and parses are visible separately, original text unmodified',async()=>{
  const f=fixture(),host=node('div');assert.equal(await renderEditorialAnalysis(host,f.data,f.passage,node,safeLink),true);
  assert.match(host.textContent,/\[α\]β → αβ/);assert.match(host.textContent,/Synthetic literal definition/);assert.match(host.textContent,/gen\./);
  assert.match(host.textContent,/not attested readings or resolved meanings/);assert.equal(f.passage.text,'𐀀 [α]β γ');
});
test('partial selection offers exact whole-word offsets only after an explicit action',async()=>{
  const f=fixture(),host=node('div'),calls=[];f.row.selection_relation='partial_intersection';f.row.lookup_status='not_requested_partial_selection';delete f.row.analysis;
  f.data.editorial_analysis.rows=[];f.data.editorial_analysis.selection_expansion_hints=[f.row];
  f.data.selection={text:'α',start_utf16:4,end_utf16:5};f.data.editorial_analysis.selection={start:3,end:4,offset_unit:'codepoint',text_sha256:hash('α')};
  assert.equal(await renderEditorialAnalysis(host,f.data,f.passage,node,safeLink,(...args)=>calls.push(args)),true);assert.equal(calls.length,0);
  flatten(host).find(e=>e.tag==='button').events.click();assert.equal(calls.length,1);
  assert.equal(calls[0][0].start,3);assert.equal(calls[0][0].end,7);assert.equal(calls[0][0].selected_text,'[α]β');assert.equal(calls[0][1],true);
});
test('machine claims, missing parse proof and unsupported meanings remain unavailable rather than reconstructed',async()=>{
  const f=fixture(),host=node('div');f.row.analysis.candidate_meanings[0].source_basis='machine_analysis';
  assert.equal(await renderEditorialAnalysis(host,f.data,f.passage,node,safeLink),true);
  assert.doesNotMatch(host.textContent,/Synthetic literal definition|gen\./);assert.match(host.textContent,/No sourced conditional/);
  const details=flatten(host).find(e=>e.tag==='details'&&e.textContent.includes('Other marked words'));assert.equal(details.open,undefined);
});
test('unsafe source URLs, wrong target entries and stale async render cannot show preferred meanings',async()=>{
  for(const change of [f=>f.row.analysis.candidate_meanings[0].gloss.alternatives[0].source_url='javascript:bad()',
    f=>f.row.analysis.candidate_meanings[0].gloss.alternatives[0].entry_id='other']){
    const f=fixture(),host=node('div');change(f);await renderEditorialAnalysis(host,f.data,f.passage,node,safeLink);
    assert.equal(flatten(host).some(e=>e.cls==='candidate-gloss' && e.textContent.includes('Synthetic literal definition')),false);
  }
  const f=fixture(),host=node('div');assert.equal(await renderEditorialAnalysis(host,f.data,f.passage,node,safeLink,null,()=>false),false);assert.equal(host.children.length,0);
});
test('clicked marked segment offers whole-word action with stale-click guards and no initial request',async()=>{
  const f=fixture(),host=node('div'),calls=[];let current=true;
  assert.equal(await renderEditorialWordActions(host,f.passage,4,5,node,(...args)=>calls.push(args),()=>current),true);assert.equal(calls.length,0);
  const button=flatten(host).find(e=>e.tag==='button');current=false;button.events.click();assert.equal(calls.length,0);
  current=true;button.events.click();assert.equal(calls[0][0].selected_text,'[α]β');
});
test('reader offers editorial inspection for whole bracketed words, not only split fragments',async()=>{
  const reader=readFileSync(new URL('../js/reader.js',import.meta.url),'utf8');
  const hook=reader.slice(reader.indexOf('    const sequence = ++state.wordSequence;'),reader.indexOf('    if (window.MelosWordContext && state.wordContextSession)'));
  assert.match(hook,/if \(button && !joined && state\.passageAnalysis\?\.selectSourceSpan/);
  assert.doesNotMatch(hook,/button && fragmentSegment/);
  assert.match(hook,/renderEditorialWordActions/);
  const f=fixture(),row=f.passage.editorial_readings.rows[0],host=node('div'),calls=[];
  f.passage.text='𐀀 [αβ] γ';row.original_text='[αβ]';row.original_text_sha256=hash(row.original_text);
  row.source_text_sha256=f.passage.editorial_readings.source_text_sha256=hash(f.passage.text);
  row.square_bracket_pairs[0].close=5;
  Object.assign(row.character_source_map[1],{source_start:4,source_end:5,source_start_utf16:5,source_end_utf16:6,printed_inside_square_brackets:true});
  assert.equal(await renderEditorialWordActions(host,f.passage,4,6,node,(...args)=>calls.push(args)),true);
  flatten(host).find(e=>e.tag==='button').events.click();assert.equal(calls[0][0].selected_text,'[αβ]');
});
