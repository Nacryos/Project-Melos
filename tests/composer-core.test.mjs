import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { createRequire } from 'node:module';

// Release W composer front end (W2/W3): the page's logic without the DOM (js/composer-core.js).
const require = createRequire(import.meta.url);
const C = require('../js/composer-core.js');
const read = path => readFileSync(new URL(`../${path}`, import.meta.url), 'utf8');

test('fold: accents, breathings, iota subscript, case, final sigma and elision fold away', () => {
  assert.equal(C.fold('Ἄφροδίτας'), 'αφροδιτασ');
  assert.equal(C.fold('ᾄδω'), 'αδω');
  assert.equal(C.fold('φαίνεταί'), 'φαινεται');
  assert.equal(C.fold('ποικιλόθρον’'), 'ποικιλοθρον');
});

test('prefix matching is accent-insensitive and returns where the typed part ends in the candidate', () => {
  assert.equal(C.matchPrefix('φαίνεταί μοι κῆνος', ''), 0);
  assert.equal(C.matchPrefix('φαίνεταί μοι κῆνος', 'φαι'), 3);
  assert.equal(C.matchPrefix('φαίνεταί μοι κῆνος', 'φαινεται μ'), 'φαίνεταί μ'.length);
  assert.equal(C.matchPrefix('φαίνεταί μοι κῆνος', 'φαίνεταί  μ'), 'φαίνεταί μ'.length, 'runs of spaces count as one');
  assert.equal(C.matchPrefix('Ἄφροδιτα', 'αφ'), 2);
  assert.equal(C.matchPrefix('ᾄδω', 'α'), 1, 'the mark on the last matched letter stays with it');
  assert.equal(C.matchPrefix('φαίνεταί', 'φε'), -1);
  assert.equal(C.matchPrefix('φαί', 'φαίνεται'), -1, 'typed past the candidate');
  assert.equal(C.matchPrefix('κῆνος', 'κηνοσ'), 5, 'σ typed before ς is converted');
});

test('slotAt: base = the line up to the word being typed', () => {
  assert.deepEqual(C.slotAt('φαίνεταί μοι κῆ', 15), { before: 'φαίνεταί μοι κῆ', base: 'φαίνεταί μοι ', typed: 'κῆ' });
  assert.deepEqual(C.slotAt('φαίνεταί μοι ', 13), { before: 'φαίνεταί μοι ', base: 'φαίνεταί μοι ', typed: '' });
  assert.equal(C.slotAt('ἀ σελάννα', 4).typed, 'σε');
});

test('templates mirror the scanner and patterns fit by prefix (D, R, X resolve)', () => {
  const metre = read('backend/scansion/metre.py');
  for (const [name, list] of Object.entries(C.TEMPLATES)) {
    assert.ok(metre.includes(`"${name}": [${list.map(t => `"${t}"`).join(', ')}]`), name);
  }
  assert.equal(C.templateFor('sapphic', 3), '-uu-F');
  assert.equal(C.templateFor('sapphic', 4), '-u-x-uu-u-F');
  assert.equal(C.templateFor('auto', 0), null);
  assert.equal(C.remainingTemplate('–⏑–', '-u-x-uu-u-F'), 'x-uu-u-F');
  assert.equal(C.remainingTemplate('–⏑⏑', '-D-D-D-D-D-F'), '-D-D-D-D-F');
  assert.equal(C.remainingTemplate('––', '-D-D-D-D-D-F'), '-D-D-D-D-F', 'spondee in the biceps');
  assert.equal(C.remainingTemplate('–⏑–?', '-u-x-uu-u-F'), '-uu-u-F', '? fills an anceps');
  assert.equal(C.remainingTemplate('⏑⏑', '-u-x-uu-u-F'), null);
  assert.equal(C.fitsPrefix('–⏑⏑–', '-uu-F'), true);
  assert.equal(C.fitsPrefix('⏑', '-uu-F'), false);
  assert.equal(C.fitsPrefix('', '-uu-F'), true);
  assert.equal(C.remainingTemplate('–⏑⏑–⏑', '-uu-F'), '');
});

const ENTRIES = [
  { base: '', source: 'corpus', template: '-u-x-uu-u-F', candidates: [
    { greek: 'φαίνεταί μοι κῆνος ἴσος θέοισιν', pattern: '–⏑–––⏑⏑–⏑–⏑', verdict: 'pass', source: { author: 'Sappho', citation: '31.1' } },
    { greek: 'ἄλλα μὰν ἔρως', pattern: '⏑⏑⏑⏑', verdict: 'pass' },                      // does not fit the template
    { greek: 'φαίνεται χθών', verdict: 'fail' }] },
  { base: 'φαίνεταί μοι ', source: 'agent', template: '-uu-u-F', candidates: [
    { greek: 'κῆνος ἴσος θέοισιν', english_span: 'that man equal to the gods', evidence: ['Sappho 31.1'] },
    { greek: 'κάλα σελάννα', english_span: 'the lovely moon' },
    { greek: 'ἀ σελάννα', english_span: 'the moon' }] },
];

test('pool filtering: most specific pool first, typed prefix, metrical fit, failed lint dropped, deduplicated', () => {
  const at = C.optionsFor(ENTRIES, 'φαίνεταί μοι ');
  assert.deepEqual(at.map(o => [o.source, o.greek]), [
    ['agent', 'κῆνος ἴσος θέοισιν'], ['agent', 'κάλα σελάννα'], ['agent', 'ἀ σελάννα'],
    ['corpus', 'φαίνεταί μοι κῆνος ἴσος θέοισιν']]);
  const typed = C.optionsFor(ENTRIES, 'φαίνεταί μοι κα');
  assert.deepEqual(typed.map(o => o.greek), ['κάλα σελάννα']);
  assert.equal(typed[0].from, 'φαίνεταί μοι '.length);
  assert.equal(typed[0].rest, 'λα σελάννα');
  assert.equal(typed[0].english, 'the lovely moon');
  // Empty line: only the corpus pool applies; the line that does not fit and the failed line are not offered.
  assert.deepEqual(C.optionsFor(ENTRIES, '').map(o => o.greek), ['φαίνεταί μοι κῆνος ἴσος θέοισιν']);
  assert.equal(C.optionsFor(ENTRIES, '')[0].citation, 'Sappho 31.1');
  // The corpus line keeps matching as the owner types it, accents or not.
  assert.equal(C.optionsFor(ENTRIES, 'φαινεται μοι κην').at(-1).rest, 'ος ἴσος θέοισιν');
  // A typed word that matches nothing empties the list; a fully typed candidate offers nothing more.
  assert.equal(C.optionsFor(ENTRIES, 'φαίνεταί μοι ξ').length, 0);
  assert.equal(C.optionsFor(ENTRIES, 'φαίνεταί μοι ἀ σελάννα').length, 0);
  assert.equal(C.optionsFor(ENTRIES, 'φαίνεταί μοι ', { limit: 2 }).length, 2);
  assert.equal(C.reusable(ENTRIES, 'φαίνεταί μοι '), 3, 'reuse counts model candidates only');
  // Pools whose base the line no longer begins with do not apply.
  assert.deepEqual(C.optionsFor(ENTRIES, 'ἄλλα ').map(o => o.greek), []);
});

test('pool keys separate poem, line, slot and settings', () => {
  const s = { author: 'Sappho', metre: 'sapphic', dialect: 'aeolic' };
  assert.equal(C.poolKey(3, 7, 'φαίνεταί  μοι ', s), '3|7|φαίνεταί μοι|Sappho/sapphic/aeolic');
  assert.notEqual(C.poolKey(3, 7, 'a', s), C.poolKey(3, 7, 'a', { ...s, metre: 'alcaic' }));
});

test('spill-over: one segment stays on the line; more continue on the next lines without overwriting', () => {
  let r = C.spillInsert(['φαίνεταί μοι κα'], 0, 13, 15, 'κάλα σελάννα');
  assert.deepEqual(r.drafts, ['φαίνεταί μοι κάλα σελάννα ']);
  assert.equal(r.caret, r.drafts[0].length);
  assert.deepEqual([r.line, r.inserted, r.completed], [0, [], []]);
  // Text after the caret follows the insertion.
  r = C.spillInsert(['αβ γδ'], 0, 3, 3, 'εζ');
  assert.deepEqual(r.drafts, ['αβ εζγδ']);
  // Two lines: the first is completed, the next empty line is filled.
  r = C.spillInsert(['ἄστερες μὲν ', ''], 0, 12, 12, 'ἀμφὶ κάλαν / σελάνναν');
  assert.deepEqual(r.drafts, ['ἄστερες μὲν ἀμφὶ κάλαν', 'σελάνναν ']);
  assert.deepEqual([r.line, r.caret, r.inserted, r.completed], [1, 'σελάνναν '.length, [], [0]]);
  // A written next line is kept: the spill is inserted before it, with the old tail after the last segment.
  r = C.spillInsert(['ἄστερες μὲν', 'ἂψ ἀπυκρύπτοισι'], 0, 11, 11, ' ἀμφὶ\nκάλαν\nσελάνναν');
  assert.deepEqual(r.drafts, ['ἄστερες μὲν ἀμφὶ', 'κάλαν', 'σελάνναν ', 'ἂψ ἀπυκρύπτοισι']);
  assert.deepEqual([r.line, r.inserted, r.completed], [2, [1, 2], [0, 1]]);
  assert.deepEqual(C.splitSpill('α / β\nγ'), ['α', 'β', 'γ']);
  assert.deepEqual(C.splitSpill('α/β'), ['α/β'], 'a slash inside a word is not a break');
});

test('SSE parsing: data-only agent events, named events, comments, CRLF, chunks split anywhere', () => {
  const p = new C.SSEParser();
  const stream = ': ping\r\n\r\ndata: {"type":"text","delta":"Ἀ"}\n\ndata: {"type":"candidate","greek":"ἀ σελάννα"}\n\nevent: note\ndata: plain\ndata: two\n\ndata: {"type":"done","cost_usd":0.12}\n\n';
  const events = [];
  for (let i = 0; i < stream.length; i += 7) events.push(...p.feed(stream.slice(i, i + 7)));
  assert.deepEqual(events.map(e => e.event), ['text', 'candidate', 'note', 'done']);
  assert.equal(events[0].data.delta, 'Ἀ');
  assert.equal(events[2].data, 'plain\ntwo');
  assert.equal(events[3].data.cost_usd, 0.12);
  assert.equal(p.buffer, '');
});

test('readSSE reads a fetch body to the end, including a last event without a blank line', async () => {
  const enc = new TextEncoder();
  const body = new ReadableStream({ start(c) {
    c.enqueue(enc.encode('data: {"type":"tool","name":"sc'));
    c.enqueue(enc.encode('an"}\n\ndata: {"type":"rejected","count":3}\n\ndata: {"type":"done"}'));
    c.close();
  } });
  const got = [];
  await C.readSSE(new Response(body), e => got.push(e));
  assert.deepEqual(got.map(e => e.event), ['tool', 'rejected', 'done']);
  assert.equal(got[0].data.name, 'scan');
  assert.equal(got[1].data.count, 3);
});

const LINE = { id: 4, current_version_id: 11, versions: [
  { id: 12, greek: 'β', source: 'agent', created_at: 300, archived: false, scansion: { pass: true, lines: [{ pattern: '–⏑' }] },
    checks: [{ id: 'L7', name: 'metre', ok: true, blocking: true, detail: 'fits' }, { id: 'L2', name: 'dialect', ok: false, blocking: false, detail: 'Attic' }] },
  { id: 10, greek: 'α', source: 'owner', created_at: 100, archived: true, scansion: null, checks: null },
  { id: 11, greek: 'γ', source: 'owner', created_at: 200, archived: false, back_translation: 'gamma',
    scansion: { pass: false, lines: [{ pattern: '––' }, { pattern: '⏑' }] }, checks: [{ id: 'L1', ok: null, blocking: true }] },
] };

test('versions row: oldest first, archived hidden unless asked, current marked, badges and patterns', () => {
  const row = C.versionsRow(LINE);
  assert.deepEqual(row.cards.map(c => c.id), [11, 12]);
  assert.equal(row.archivedCount, 1);
  assert.equal(row.currentIndex, 0);
  assert.equal(row.cards[0].pattern, '–– | ⏑');
  assert.equal(row.cards[0].pass, false);
  assert.equal(row.cards[0].back_translation, 'gamma');
  assert.deepEqual(row.cards[1].badges.map(b => [b.id, b.state]), [['L7', 'pass'], ['L2', 'warn']]);
  assert.deepEqual(row.cards[0].badges.map(b => b.state), ['info']);
  assert.deepEqual(C.versionsRow(LINE, { showArchived: true }).cards.map(c => [c.id, c.archived]), [[10, true], [11, false], [12, false]]);
  assert.deepEqual(C.checkBadges([{ id: 'L7', verdict: 'fail', message: 'no' }]), [{ id: 'L7', state: 'fail', title: 'L7: no' }]);
});

test('archiving the current version falls back to the newest live one, as the store does', () => {
  const after = C.archiveVersion(LINE, 11);
  assert.equal(after.current_version_id, 12);
  assert.equal(after.current.greek, 'β');
  assert.equal(C.archiveVersion(after, 12).current_version_id, null);
  assert.equal(C.archiveVersion(LINE, 12).current_version_id, 11, 'archiving another version keeps the current one');
  assert.equal(C.archiveVersion(C.archiveVersion(LINE, 10, false), 11).current_version_id, 12);
  assert.equal(LINE.current_version_id, 11, 'no mutation');
});

test('daily cost: summed per Pacific day in storage', () => {
  const store = new Map();
  const storage = { getItem: k => (store.has(k) ? store.get(k) : null), setItem: (k, v) => store.set(k, v) };
  const evening = new Date('2026-10-10T05:30:00Z');   // 22:30 on Oct 9 in Los Angeles
  assert.equal(C.pacificDay(evening), '2026-10-09');
  C.addCost(storage, 0.25, evening);
  assert.equal(C.addCost(storage, 0.1, evening), 0.35);
  assert.equal(C.todayCost(storage, new Date('2026-10-10T08:00:00Z')), 0, 'a new Pacific day starts at zero');
  assert.equal(C.money(0.35), '$0.35');
  const blocked = { getItem() { throw new Error('blocked'); }, setItem() { throw new Error('blocked'); } };
  assert.equal(C.addCost(blocked, 1), 1);
});

test('page wiring: the composer loads the core before the page, calls the composer API, aborts stale pools', () => {
  const html = read('composer.html'), js = read('js/composer.js');
  assert.ok(html.indexOf('js/composer-core.js') > 0 && html.indexOf('js/composer-core.js') < html.indexOf('js/composer.js?'));
  for (const id of ['poem-select', 'new-poem', 'poem-title', 'english', 'board', 'chat-form', 'chat-input', 'cost', 'banner', 'popup', 'auto-ask']) {
    assert.match(html, new RegExp(`id="${id}"`), id);
  }
  for (const route of ['/api/composer/poems', '/full', '/lines', '/versions', '/pool', '/chat', '/api/composer/backtranslate', '/api/compose/suggest', '/api/scan']) {
    assert.ok(js.includes(route), route);
  }
  assert.match(js, /if \(S\.fill && S\.fill\.row === row && S\.fill\.key !== slotKeyOf\(row\)\) abortFill\(\);/);
  assert.match(js, /back_translation: res\.english/);
  assert.match(js, /make_current: false/);
  assert.match(read('scripts/build_frontend.mjs'), /'composer-core\.js', 'composer\.js'/);
  // Release V rule: the composer never reaches the reader's metre lock.
  assert.doesNotMatch(js, /scansion\.lock|lock_line|recorded_metre|\/api\/scan\/passage|reader_scan/);
});

test('site menu lists the composer only while the owner sign-in marker is present', () => {
  const menu = read('js/site-menu.js');
  assert.match(menu, /const OWNER_SIGNED_IN = \/\(\?:\^\|;\\s\*\)melos_owner_ui=1\(\?:;\|\$\)\/\.test\(document\.cookie\);/);
  assert.match(menu, /FEATURES\.filter\(\(\[, href\]\) => OWNER_SIGNED_IN \|\| !OWNER_ONLY\.has\(href\)\)/);
  assert.match(menu, /const OWNER_ONLY = new Set\(\['\/composer'\]\);/);
  assert.match(read('js/owner-loader.js'), /melos_owner_ui=1/, 'the same marker the owner loader reads');
});

test('slotKey: the same key the server computes (backend/composer_routes.py slot_key, same vectors)', async () => {
  assert.equal(C.slotKeyText(2, '  ἄστερες  μὲν ', { metre: 'sapphic' }), 'v1|2|ἄστερες μὲν||sapphic|');
  assert.equal(await C.slotKey(0, '', { author: 'Sappho', metre: 'sapphic', dialect: 'aeolic' }), '3e5d5780d5992aabffe8ed380744d64a');
  assert.equal(await C.slotKey(2, '  ἄστερες  μὲν ', { metre: 'sapphic' }), 'ea66ae8e0ea3c660a5e7c0ef8dd45ecd');
  assert.equal(await C.slotKey(2, 'ἄστερες μὲν'.normalize('NFD'), { metre: 'sapphic', author: null }), 'ea66ae8e0ea3c660a5e7c0ef8dd45ecd');
});

test('page wiring: warm-up on open and after a commit, stored candidates per slot, stanza candidates routed', () => {
  const js = read('js/composer.js');
  assert.match(js, /\/warm`/);
  assert.match(js, /\/pool\?slot_key=\$\{slotKey\}/);
  assert.match(js, /warm\(rowIndex\(target\)\);/);
  assert.match(js, /if \(!next\.draft\.trim\(\)\) warm\(rowIndex\(next\)\);/);
  assert.match(js, /data\.slot_key && data\.slot_key !== mine\) routeToSlot\(data\)/);
  assert.match(js, /await loadStored\(row, base\);/);
});
