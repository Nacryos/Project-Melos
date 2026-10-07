import test from 'node:test';
import assert from 'node:assert/strict';
import vm from 'node:vm';
import { readFileSync } from 'node:fs';
import { createHash, webcrypto } from 'node:crypto';
const context = vm.createContext({window:{}, URL, AbortController, crypto:webcrypto, TextEncoder});
vm.runInContext(readFileSync(new URL('../js/word-context.js',import.meta.url),'utf8'),context);
const {selectionFor,checkedRankedAlternatives,createSession,mount}=context.window.MelosWordContext;
// Synthetic source text/meanings exercise UI contracts, not Greek scholarship.
function fixture() {
  const body=selectionFor({passage:{id:'p',text:'α'},form:'α',start:0,end:1});
  const senses=Array.from({length:4},(_,index)=>({id:`s:${index}`,entry_id:'entry:1',text:`Synthetic literal ${index}`,
    source:'Fixture dictionary',source_url:'https://example.test/entry',source_locator:`/sense/${index}`,raw_sha256:'a'.repeat(64),
    language:'eng',evidence_type:'dictionary_sense',scope_text:[`Synthetic literal ${index}`]}));
  const candidate={id:'c:1',lemma:'α',gloss_entry_id:'entry:1'};
  const token={id:'t',kind:'word',text:'α',start_utf16:0,end_utf16:1,source_candidates:[candidate]};
  const scores={'s:0':.57,'s:1':.10,'s:2':.05,'s:3':.05,abstain:.23};
  const row={...token,token_id:'t',status:'ambiguous',gloss:{status:'unavailable'},
    candidate_meanings:[{candidate_id:'c:1',lemma:'α',gloss:{alternatives:senses}}],
    sense_ranking_status:'uncertain',sense_ranking_inventory_sha256:'b'.repeat(64),
    ranked_sense_alternatives:senses.map(s=>({...structuredClone(s),supporting_candidate_ids:['c:1'],score_uncalibrated:scores[s.id]}))};
  const decision={token_id:'t',status:'uncertain',selected_sense_id:null,inventory_sha256:'b'.repeat(64),
    model_probabilities_uncalibrated:scores,ranked_senses:senses.map(s=>({sense_id:s.id,score_uncalibrated:scores[s.id]}))};
  return {body,data:{passage:{id:'p',text_sha256:createHash('sha256').update('α').digest('hex')},
    selection:{text:'α',start_utf16:0,end_utf16:1},tokens:[token],interlinear:{readings:[{tokens:[row]}]},sense_ranking:{items:[decision]}},row,decision};
}
test('validated uncertain ranking preserves literal senses, scores and abstention without selected parse',()=>{
  const {body,data}=fixture(), result=checkedRankedAlternatives(data,body);
  assert.equal(result.kind,'ranked_alternatives'); assert.equal(result.alternatives.length,4);
  assert.equal(result.alternatives[0].text,'Synthetic literal 0'); assert.equal(result.abstain_score_uncalibrated,.23);
  assert.equal(result.parse,'');assert.equal(result.selected_sense_id,null);
});
test('every original sense and abstention must remain present with exact scores and support',()=>{
  for(const change of [f=>{f.row.ranked_sense_alternatives.pop();},f=>{delete f.decision.model_probabilities_uncalibrated.abstain;},
    f=>{f.row.ranked_sense_alternatives[0].supporting_candidate_ids=['missing'];},
    f=>{f.row.ranked_sense_alternatives[0].score_uncalibrated=.99;},f=>{f.decision.ranked_senses[0].score_uncalibrated=.99;},
    f=>{f.row.ranked_sense_alternatives.push(f.row.ranked_sense_alternatives[0]);},
    f=>{f.decision.model_probabilities_uncalibrated.abstain=NaN;},f=>{f.decision.model_probabilities_uncalibrated.unknown=.2;},
    f=>{f.row.sense_ranking_inventory_sha256='c'.repeat(64);},f=>{f.decision.status='abstained';}]){
    const f=fixture();change(f);assert.equal(checkedRankedAlternatives(f.data,f.body),null);
  }
});
test('wrong homonym, changed source attribution or generated wording cannot enter ranked output',()=>{
  for(const change of [s=>{s.text='Invented definition';},s=>{s.entry_id='homonym:2';},
    s=>{s.source_url='https://example.test/other';},s=>{s.raw_sha256='f'.repeat(64);},s=>{s.scope_text=['Invented context'];}]){
    const f=fixture();change(f.row.ranked_sense_alternatives[0]);assert.equal(checkedRankedAlternatives(f.data,f.body),null);
  }
  const f=fixture();f.data.tokens[0].source_candidates[0].gloss_entry_id='homonym:2';
  assert.equal(checkedRankedAlternatives(f.data,f.body),null);
});
test('wrong occurrence or competing decisions cannot reuse a ranking',()=>{
  const f=fixture();f.data.selection.start_utf16=1;assert.throws(()=>checkedRankedAlternatives(f.data,f.body));
  const g=fixture();g.data.sense_ranking.items.push(g.decision);assert.equal(checkedRankedAlternatives(g.data,g.body),null);
});
test('same-lemma secondary dictionary joins require literal token entry senses, not loose row claims',()=>{
  const make=()=>{const f=fixture();delete f.data.tokens[0].source_candidates[0].gloss_entry_id;
    f.data.tokens[0].lexicon_entries=[{id:'entry:1',lemma:'α',dictionary_senses:structuredClone(f.row.candidate_meanings[0].gloss.alternatives)}];return f;};
  const f=make();assert.equal(checkedRankedAlternatives(f.data,f.body).alternatives.length,4);
  for(const change of [x=>{x.data.tokens[0].lexicon_entries[0].lemma='ά';},
    x=>{x.data.tokens[0].lexicon_entries[0].dictionary_senses[0].source_url='https://example.test/other';},
    x=>{x.data.tokens[0].lexicon_entries[0].dictionary_senses[0].form_scope={relation:'other'};},
    x=>{x.row.candidate_meanings[0].lemma='other';}]){const x=make();change(x);assert.equal(checkedRankedAlternatives(x.data,x.body),null);}
});
test('validated uncertain responses are cached, while changed passage hashes fail closed',async()=>{
  const f=fixture();let calls=0;
  const session=createSession({post:async()=>{calls++;return f.data;}});session.select(f.body);
  assert.equal((await session.run(f.body)).kind,'ranked_alternatives');await session.run(f.body);assert.equal(calls,1);
  const bad=fixture();bad.data.passage.text_sha256='f'.repeat(64);
  const invalid=createSession({post:async()=>bad.data});invalid.select(bad.body);
  await assert.rejects(invalid.run(bad.body),error=>error.code==='context_hash_mismatch');
});
test('UI exposes three literal alternatives, keeps rest/scores collapsed and never prints parse',async()=>{
  class Element{constructor(tag,cls='',text=''){Object.assign(this,{tag,cls,text,children:[],handlers:{}});}
    append(...c){this.children.push(...c);}replaceChildren(...c){this.children=c;}setAttribute(){}
    addEventListener(name,fn){this.handlers[name]=fn;}get textContent(){return this.text+this.children.map(c=>c.textContent).join('');}
    set textContent(v){this.text=v;this.children=[];}}
  const node=(...args)=>new Element(...args),host=node('div'),f=fixture();
  f.row.parse_short='Must not appear';
  const session=createSession({post:async()=>f.data});
  mount({host,body:f.body,session,current:()=>true,classifierReady:()=>true,node,safeLink:(url,label)=>Object.assign(node('a','',label),{href:url})});
  const section=host.children[0];await section.children[1].handlers.click();
  assert.equal(section.children[0].textContent,'Possible meanings in this passage');
  const output=section.children[2], cards=output.children.filter(c=>c.cls==='dictionary-glimpse-entry');
  assert.equal(cards.length,3);assert.match(cards[0].textContent,/Synthetic literal 0/);
  const details=output.children.find(c=>c.tag==='details');assert.equal(details.open,undefined);
  assert.match(details.textContent,/Synthetic literal 3/);assert.match(details.textContent,/Abstention score: 0.23/);
  assert.doesNotMatch(cards.map(c=>c.textContent).join(''),/0.57|confidence|%/);
  assert.doesNotMatch(host.textContent,/Must not appear/);
});
