import test from 'node:test';
import assert from 'node:assert/strict';
import vm from 'node:vm';
import {readFileSync} from 'node:fs';
import {webcrypto,createHash} from 'node:crypto';
const context=vm.createContext({window:{},URL,crypto:webcrypto,TextEncoder,AbortController});
vm.runInContext(readFileSync(new URL('../js/passage-analysis.js',import.meta.url),'utf8'),context);
const {machineSubentryMeanings:resolve,renderMachineSubentryMeanings:render,dedupeCandidates}=context.window.MelosPassageAnalysis;
const fixture=()=>JSON.parse(readFileSync(new URL('./fixtures/machine-subentry-actual.json',import.meta.url),'utf8'));
const raw=data=>data.tokens[0].machine.machine_candidates[0];
const ref=data=>data.interlinear.readings[0].tokens[0].candidate_meanings[0].machine_subentry_alternatives[0];
const source=data=>data.machine_subentry_evidence.subentries[ref(data).subentry_ref].source_subentry;
const stable=value=>value&&typeof value==='object'?Array.isArray(value)?value.map(stable):Object.fromEntries(Object.keys(value).sort().map(key=>[key,stable(value[key])])):value;
const digest=value=>createHash('sha256').update(JSON.stringify(stable(value))).digest('hex');
function rehash(data) {
  const catalog=data.machine_subentry_evidence,reference=data.tokens[0].machine_subentries,old=reference.inventory_ref,envelope=catalog.inventories[old];
  const body=Object.fromEntries(Object.entries(envelope).filter(([key])=>!['dependency_ref','candidates','supporting_subentries','supporting_receipts'].includes(key)));
  body.dependencies=catalog.dependencies[envelope.dependency_ref];
  for(const [field,pool] of [['candidates','bindings'],['supporting_subentries','subentries'],['supporting_receipts','receipts']])body[field]=envelope[field].map(id=>catalog[pool][id]);
  const id=digest(body);delete catalog.inventories[old];catalog.inventories[id]=envelope;
  reference.inventory_ref=id;ref(data).inventory_ref=id;
}
test('actual ἀσυννέτημμι shows the literal LSJ subentry definition only beneath its matching machine parse',async()=>{
  const data=fixture(),before=JSON.stringify(data),candidate=raw(data),meanings=await resolve(data,data.tokens[0],dedupeCandidates([candidate])[0]);
  assert.equal(meanings.length,1);assert.equal(meanings[0].sense.text,'to be without understanding');
  assert.equal(meanings[0].sense.form_scope.relation,'variant');
  assert.notEqual(meanings[0].sense.form_scope.text,data.tokens[0].text);
  assert.equal(data.interlinear.readings[0].tokens[0].candidate_meanings[0].gloss.text,null);
  assert.equal(JSON.stringify(data),before);
});
test('wrong candidate, lemma, receipt, source/catalog identity and missing crypto cannot produce meaning',async()=>{
  for(const change of [data=>raw(data).id='machine:wrong',data=>raw(data).lemma='ἄλλος',data=>raw(data).features={},
    data=>raw(data).receipt_id='0'.repeat(64),data=>ref(data).binding_ref='__proto__',data=>ref(data).subentry_ref='wrong',
    data=>ref(data).sense_refs=['wrong'],data=>source(data).dictionary_senses[0].text='tampered',
    data=>data.tokens[0].partial_word=true,data=>data.tokens[0].machine.form='wrong']){
    const data=fixture();change(data);assert.equal((await resolve(data,data.tokens[0],raw(data))).length,0);
  }
  const data=fixture(),previous=context.crypto;context.crypto=undefined;
  assert.equal((await resolve(data,data.tokens[0],raw(data))).length,0);context.crypto=previous;
});
test('rehashing cannot authorize wrong sense ownership, altered variant scope or Latin glossary equivalence',async()=>{
  for(const change of [row=>row.dictionary_senses[0].entry_id='wrong',row=>row.dictionary_senses[0].lexicon_entry_id='wrong',
    row=>row.dictionary_senses[0].source_url='https://example.test/not-source',row=>row.dictionary_senses[0].language='la',
    row=>row.dictionary_senses[0].raw_sha256='0'.repeat(64),row=>row.dictionary_senses[0].form_scope.relation='headword',
    row=>row.dictionary_senses[0].source_locator=null,row=>row.orthography='wrong',
    row=>row.citations=[{text:'Gloss.'}]]){
    const data=fixture();change(source(data));rehash(data);
    assert.equal((await resolve(data,data.tokens[0],raw(data))).length,0);
  }
  const data=fixture();data.machine_subentry_evidence.subentries[ref(data).subentry_ref].english_preview.eligible=false;rehash(data);
  assert.equal((await resolve(data,data.tokens[0],raw(data))).length,0);
});
test('render is concise, keeps proof closed, and suppresses late output after selection changes',async()=>{
  class Element {constructor(tag,cls='',text=''){Object.assign(this,{tag,cls,text,children:[]});}append(...items){this.children.push(...items);}}
  const node=(...args)=>new Element(...args),data=fixture(),host=node('div');
  const link=(url,label)=>node('a','',label);
  assert.equal(await render(host,data,data.tokens[0],raw(data),node,link),true);
  const box=host.children[0];assert.match(box.children[0].text,/Dictionary alternative for this machine parse/);
  assert.equal(box.children[1].children[0].text,'to be without understanding');
  const proof=box.children[1].children[1];assert.equal(proof.tag,'details');assert.equal(proof.open,undefined);
  assert.match(proof.children[1].text,/not a context-selected meaning/);
  const stale=node('div');assert.equal(await render(stale,data,data.tokens[0],raw(data),node,link,()=>false),false);assert.equal(stale.children.length,0);
});

test('conflicting shared receipt fields and in-place interlinear changes fail closed',async()=>{
  for(const [key,value] of [['id','wrong'],['raw_sha256','0'.repeat(64)],['url','https://example.test/wrong'],['request_form','wrong']]){
    const data=fixture();data.tokens[0].machine.receipt[key]=value;
    assert.equal((await resolve(data,data.tokens[0],raw(data))).length,0);
  }
  const data=fixture(),pending=resolve(data,data.tokens[0],raw(data));
  data.interlinear.readings[0].tokens[0].candidate_meanings[0].lemma='changed during hash';
  assert.equal((await pending).length,0);
});
