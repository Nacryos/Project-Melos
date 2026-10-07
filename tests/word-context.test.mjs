import test from 'node:test';
import assert from 'node:assert/strict';
import vm from 'node:vm';
import { readFileSync } from 'node:fs';
import { createHash, webcrypto } from 'node:crypto';

const context = vm.createContext({ window: {}, AbortController, crypto: webcrypto, TextEncoder });
vm.runInContext(readFileSync(new URL('../js/word-context.js', import.meta.url), 'utf8'), context);
const { selectionFor, checkedProposal, createSession, mount } = context.window.MelosWordContext;
// These synthetic strings and definitions test UI contracts, not Greek scholarship.
function request(form = 'α', start = 2) {
  return selectionFor({ passage: { id: 'synthetic:1', text: 'x '.padEnd(start, ' ') + form }, form, start, end: start + form.length });
}
function response(body = request(), source = 'x '.padEnd(body.start, ' ') + body.selected_text) {
  const sense = { id: 'sense:1', entry_id: 'entry:1', text: 'test definition', evidence_type: 'dictionary_sense', language: 'en', source: 'Synthetic fixture', source_url: 'https://example.test/entry/1' };
  const candidate = { id: 'candidate:1', lemma: 'α', gloss_entry_id: 'entry:1' };
  const token = { id: 'token:1', kind: 'word', text: body.selected_text, start_utf16: body.start, end_utf16: body.end, source_candidates: [candidate] };
  const row = { ...token, token_id: token.id, status: 'selected', candidate_id: candidate.id, source_candidate: candidate, parse_short: 'nom. sg.',
    gloss: { status: 'available', text: sense.text, sense_id: sense.id, entry_id: sense.entry_id, selection_basis: 'jev_contextual_sense_proposal', supporting_candidate_ids: [candidate.id], alternatives: [sense] } };
  return { passage: { id: body.passage_id, text_sha256: createHash('sha256').update(source).digest('hex') }, selection: { text: body.selected_text, start_utf16: body.start, end_utf16: body.end }, tokens: [token], interlinear: { readings: [{ tokens: [row] }] }, sense_ranking: { items: [{ token_id: token.id, status: 'proposed', selected_sense_id: sense.id }] } };
}
test('only exact clicked intact UTF-16 spans are eligible', () => {
  assert.ok(request());
  for (const extra of [{ joined: true }, { fragment: true }, { start: 0 }, { end: 9 }]) {
    assert.equal(selectionFor({ passage: { id: 'p', text: ' α' }, form: 'α', start: 1, end: 2, ...extra }), null);
  }
  assert.equal(request('α β'), null); assert.equal(request('α\u0323'), null);
  assert.equal(request('[α]'), null);
});
test('only a sourced, exact-ID contextual sense is projected', () => {
  const data = response(), proposal = checkedProposal(data, request());
  assert.equal(proposal.text, 'test definition'); assert.equal(proposal.parse, 'nom. sg.');
  data.interlinear.readings[0].tokens[0].gloss.text = 'invented';
  assert.equal(checkedProposal(data, request()), null);
});
test('a meaning proposal does not resolve ambiguous morphology', () => {
  const data = response(), row = data.interlinear.readings[0].tokens[0];
  row.status = 'ambiguous'; row.candidate_id = null; row.source_candidate = null;
  assert.equal(checkedProposal(data, request()).parse, '');
  assert.equal(checkedProposal(data, request()).text, 'test definition');
});
test('wrong homograph entry pointers and unknown support IDs fail closed', () => {
  for (const change of [data => { data.tokens[0].source_candidates[0].gloss_entry_id = 'homograph:2'; },
    data => { data.interlinear.readings[0].tokens[0].gloss.supporting_candidate_ids = ['unknown']; }]) {
    const data = response(); change(data); assert.equal(checkedProposal(data, request()), null);
  }
});
test('reject wrong selection identity and multiword responses', () => {
  for (const change of [data => { data.passage.id = 'other'; }, data => { data.selection.start_utf16 = 3; },
    data => { data.tokens.push({ ...data.tokens[0], id: 'token:2' }); }]) {
    const data = response(); change(data); assert.throws(() => checkedProposal(data, request()));
  }
});
test('missing, non-English, unsourced, and dictionary-order meanings are not contextual answers', () => {
  for (const change of [row => { row.gloss = {}; }, row => { row.gloss.alternatives[0].language = 'el'; },
    row => { delete row.gloss.alternatives[0].source_url; }, row => { row.gloss.selection_basis = 'first_dictionary_sense_not_contextual_sense'; }]) {
    const data = response(); change(data.interlinear.readings[0].tokens[0]); assert.equal(checkedProposal(data, request()), null);
  }
});
test('same-word requests deduplicate inflight and cache successful results', async () => {
  let calls = 0, finish, started;
  const posted = new Promise(resolve => { started = resolve; });
  const body = request(), session = createSession({ post: () => { calls++; started(); return new Promise(resolve => { finish = resolve; }); } });
  session.select(body); const one = session.run(body), two = session.run(body);
  await posted;
  assert.equal(calls, 1); finish(response()); await Promise.all([one, two]);
  await session.run(body); assert.equal(calls, 1);
});
test('word transition aborts and suppresses a late response even if fetch ignores abort', async () => {
  let finish, signal, started;
  const posted = new Promise(resolve => { started = resolve; });
  const body = request(), session = createSession({ post: (_, __, options) => { signal = options.signal; started(); return new Promise(resolve => { finish = resolve; }); } });
  session.select(body); const result = session.run(body); await posted; session.select(request('β'));
  assert.equal(signal.aborted, true); finish(response()); await assert.rejects(result, /changed/);
});
test('cache is bounded and expires', async () => {
  let time = 0, calls = 0;
  const session = createSession({ limit: 1, ttl: 10, now: () => time, post: async (_, body) => { calls++; return response(body); } });
  const one = request(), two = request('β');
  session.select(one); await session.run(one); session.select(two); await session.run(two);
  session.select(one); await session.run(one); assert.equal(calls, 3);
  time = 11; await session.run(one); assert.equal(calls, 4);
});
test('same ID and word with changed surrounding source text invalidates cached context', async () => {
  let calls = 0;
  const one = request(), two = selectionFor({ passage: { id: one.passage_id, text: 'y α' }, form: 'α', start: 2, end: 3 });
  const session = createSession({ post: async (_, body) => { calls++; return response(body, body === two ? 'y α' : 'x α'); } });
  session.select(one); await session.run(one); session.select(two); await session.run(two);
  assert.equal(calls, 2);
  assert.equal(JSON.stringify(two).includes('y α'), false, 'surrounding text stays client-side, not an extra API field');
});
test('changed server context with the same word and offsets fails full-passage hash validation', async () => {
  const body = request(), session = createSession({ post: async () => response(body, 'y α') });
  session.select(body);
  await assert.rejects(session.run(body), error => error.code === 'context_hash_mismatch');
});
test('selected morphology without the selected dictionary support is not displayed', () => {
  const data = response(), row = data.interlinear.readings[0].tokens[0];
  const unsupported = { id: 'candidate:wrong', gloss_entry_id: 'homograph:wrong' };
  data.tokens[0].source_candidates.push(unsupported);
  row.gloss.supporting_candidate_ids.push(unsupported.id);
  row.candidate_id = unsupported.id; row.source_candidate = unsupported;
  assert.equal(checkedProposal(data, request()).parse, '');
});
function consensusResponse() {
  const data = response(), row = data.interlinear.readings[0].tokens[0];
  row.status = 'ambiguous'; row.candidate_id = null; row.source_candidate = null;
  row.selection_basis = 'source_morphology_consensus'; row.supporting_parse_candidate_ids = ['candidate:1'];
  row.features = { POS: 'VERB', Person: '2', Number: 'Sing', Tense: 'Aor', Mood: 'Ind', Voice: 'Act' };
  row.parse_short = '2nd sg. aor. ind. act.';
  row.candidate_meanings = [{ candidate_id: 'candidate:1', lemma: 'α', basis: 'source_alternative',
    features: { ...row.features }, parse_short: row.parse_short }];
  return data;
}
test('explicit complete source morphology consensus displays parse without selecting lexical identity', () => {
  const proposal = checkedProposal(consensusResponse(), request());
  assert.equal(proposal.parse, '2nd sg. aor. ind. act.');
  assert.equal(proposal.lemma, ''); assert.equal(proposal.parse_basis, 'source_morphology_consensus');
});
test('consensus requires every referenced ID and exact existing full feature set', () => {
  for (const change of [row => { row.supporting_parse_candidate_ids.push('unknown'); },
    row => { row.supporting_parse_candidate_ids = []; },
    row => { row.candidate_meanings[0].features.Person = '3'; },
    row => { delete row.candidate_meanings[0].features.Tense; },
    row => { row.features.Case = 'Nom'; },
    row => { row.candidate_meanings[0].lemma = 'β'; },
    row => { row.parse_short = 'invented parse'; },
    row => { row.syntax_conflict = true; }]) {
    const data = consensusResponse(); change(data.interlinear.readings[0].tokens[0]);
    assert.equal(checkedProposal(data, request()).parse, '');
  }
});
test('a consensus candidate without the selected sense support cannot reintroduce another lemma parse', () => {
  const data = consensusResponse(), row = data.interlinear.readings[0].tokens[0];
  data.tokens[0].source_candidates.push({ id: 'other', lemma: 'β', gloss_entry_id: 'other-entry' });
  row.gloss.supporting_candidate_ids.push('other'); row.supporting_parse_candidate_ids = ['other'];
  row.candidate_meanings.push({ candidate_id: 'other', lemma: 'β', basis: 'source_alternative', features: { ...row.features }, parse_short: row.parse_short });
  assert.equal(checkedProposal(data, request()).parse, '');
});
test('missing secure hashing fails closed before any paid request', async () => {
  const noCrypto = vm.createContext({ window: {}, AbortController, TextEncoder });
  vm.runInContext(readFileSync(new URL('../js/word-context.js', import.meta.url), 'utf8'), noCrypto);
  const api = noCrypto.window.MelosWordContext;
  const body = api.selectionFor({ passage: { id: 'p', text: 'α' }, form: 'α', start: 0, end: 1 });
  let calls = 0;
  const session = api.createSession({ post: () => { calls++; } }); session.select(body);
  await assert.rejects(session.run(body), error => error.code === 'context_verification_unavailable');
  assert.equal(calls, 0);
});
test('unavailable sense is retryable, not cached as a successful contextual answer', async () => {
  let calls = 0;
  const session = createSession({ post: async (_, body) => { calls++; const data = response(body); data.sense_ranking.items = []; return data; } });
  const body = request(); session.select(body); assert.equal(await session.run(body), null);
  assert.equal(await session.run(body), null); assert.equal(calls, 2);
});
test('mount makes no request until explicit activation and hides action without classifier', () => {
  let calls = 0;
  const element = () => ({ append() {}, setAttribute() {}, addEventListener() {} });
  const session = createSession({ post: () => { calls++; } });
  mount({ host: element(), body: request(), session, current: () => true, classifierReady: () => true, node: element });
  mount({ host: element(), body: request(), session, current: () => true, classifierReady: () => false, node: element });
  assert.equal(calls, 0);
});
