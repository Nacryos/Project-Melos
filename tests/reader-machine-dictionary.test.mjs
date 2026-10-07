import test from 'node:test';
import assert from 'node:assert/strict';
import vm from 'node:vm';
import {readFileSync} from 'node:fs';
import {webcrypto} from 'node:crypto';
class Element {constructor(tag,cls='',text=''){Object.assign(this,{tag,cls,text,children:[]});}append(...items){this.children.push(...items);}get textContent(){return this.text+this.children.map(child=>child.textContent).join('');}}
const node=(...args)=>new Element(...args),context=vm.createContext({window:{},URL,crypto:webcrypto,TextEncoder,AbortController,node,
  safeLink:(url,label)=>{const element=node('a','',label);element.href=url;return element;}});
vm.runInContext(readFileSync(new URL('../js/passage-analysis.js',import.meta.url),'utf8'),context);
const source=readFileSync(new URL('../js/reader.js',import.meta.url),'utf8');
vm.runInContext(source.slice(source.indexOf('  async function renderWordMachineDictionary('),source.indexOf('  async function inspectWord(')),context);
const render=vm.runInContext('renderWordMachineDictionary',context);
const fixture=()=>JSON.parse(readFileSync(new URL('./fixtures/machine-subentry-word-actual.json',import.meta.url),'utf8'));
const descendants=root=>root.children.flatMap(child=>[child,...descendants(child)]);

test('actual ordinary /api/word envelope shows literal English and all core machine parse fields without opening advanced UI',async()=>{
  const data=fixture(),before=JSON.stringify(data),host=node('div');
  assert.equal(await render(host,data,data.form),true);
  assert.equal(host.children[0].tag,'section');
  assert.match(host.textContent,/to be without understanding/);
  assert.match(host.textContent,/1st · singular · present · indicative · active · verb/);
  assert.match(host.textContent,/not a context-selected meaning/);
  assert.ok(descendants(host).filter(row=>row.tag==='details').every(row=>!row.open));
  assert.equal(JSON.stringify(data),before);
  assert.match(source,/await renderWordMachineDictionary\(morphologyHost,data,form/);
});

test('wrong query, malformed spans, candidate/catalog mismatch and disabled envelope cannot render ordinary definitions',async()=>{
  for(const mutate of [data=>data.form='wrong',data=>data.machine_dictionary.query_form='wrong',
    data=>data.machine_dictionary.scope='whole_poem',data=>data.machine_dictionary.tokens[0].start=1,
    data=>data.machine_dictionary.tokens[0].partial_word=true,data=>data.machine_dictionary.selection.text='wrong',
    data=>data.machine_dictionary.tokens[0].machine.machine_candidates[0].lemma='wrong',
    data=>data.machine_dictionary.interlinear.readings[0].tokens[0].candidate_meanings[0].machine_subentry_alternatives[0].sense_refs=['wrong'],
    data=>delete data.machine_dictionary]){
    const data=fixture(),form=data.form;mutate(data);const host=node('div');
    assert.equal(await render(host,data,form),false);assert.equal(host.children.length,0);
  }
});

test('late response and in-place envelope mutation cannot attach a stale meaning to another clicked word',async()=>{
  const data=fixture(),host=node('div');let active=true;
  const pending=render(host,data,data.form,()=>active);active=false;
  assert.equal(await pending,false);assert.equal(host.children.length,0);
  const next=fixture(),nextHost=node('div'),changed=render(nextHost,next,next.form);
  next.machine_dictionary.query_form='changed';
  assert.equal(await changed,false);assert.equal(nextHost.children.length,0);
});

test('an alternative without eligible dictionary proof stays accessible without acquiring another candidate meaning',async()=>{
  const data=fixture(),token=data.machine_dictionary.tokens[0],other=structuredClone(token.machine.machine_candidates[0]);
  other.id='machine:unlinked-test-alternative';other.lemma='synthetic alternate';token.machine.machine_candidates.push(other);
  const host=node('div');assert.equal(await render(host,data,data.form),true);
  const alternatives=descendants(host).find(row=>row.tag==='details' && row.textContent.startsWith('Other supplied machine alternatives'));
  assert.ok(alternatives);assert.match(alternatives.textContent,/synthetic alternate/);
  assert.doesNotMatch(alternatives.textContent,/to be without understanding/);
});
