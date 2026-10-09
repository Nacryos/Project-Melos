import test from 'node:test';
import assert from 'node:assert/strict';
import vm from 'node:vm';
import { readFileSync } from 'node:fs';

// Release P frontend: compact dictionaries, calibrated probability, variant
// groups, n-gram phrases, citation lookup, rate intervals and the period
// filter. Synthetic fixtures shaped like the API contract; no network.
const read = path => readFileSync(new URL(`../${path}`, import.meta.url), 'utf8');
function load(...files) {
  const context = vm.createContext({ window: {}, URL, URLSearchParams, console, setTimeout, clearTimeout });
  for (const file of files) vm.runInContext(read(file), context);
  return context.window;
}
const plain = value => JSON.parse(JSON.stringify(value));

class Element {
  constructor(tag = 'div', cls = '', text = '') {
    Object.assign(this, { tag, className: cls, text, children: [], attrs: {}, parent: null, title: '' });
    this.classList = { add: name => { this.className = `${this.className} ${name}`.trim(); } };
  }
  append(...items) { for (const item of items) { if (item instanceof Element) item.parent = this; this.children.push(item); } }
  after(item) { const list = this.parent.children; item.parent = this.parent; list.splice(list.indexOf(this) + 1, 0, item); }
  setAttribute(key, value) { this.attrs[key] = value; }
  all() { return this.children.flatMap(child => child instanceof Element ? [child, ...child.all()] : []); }
  querySelectorAll(selector) { const name = selector.replace(/^\./, ''); return this.all().filter(item => item.className.split(/\s+/).includes(name)); }
  querySelector(selector) { return this.querySelectorAll(selector)[0] || null; }
  get textContent() { return this.text + this.children.map(item => typeof item === 'string' ? item : item.textContent).join(''); }
  set textContent(value) { this.text = String(value); this.children = []; }
  get lastChild() { return this.children.at(-1); }
}
const node = (tag, cls, text) => new Element(tag, cls, text ?? '');

test('a calibrated probability is put in plain words, and low ones are flagged', () => {
  const { MelosWordPanel: panel } = load('js/word-panel.js');
  assert.equal(panel.probabilityText(0.94), 'about 94% likely');
  assert.equal(panel.probabilityText(0.997), 'over 99% likely');
  assert.equal(panel.probabilityText(0.004), 'about 1% likely');
  assert.equal(panel.probabilityText(null), '');
  assert.equal(panel.probabilityText(undefined), '');
  assert.equal(panel.probabilityText(1.4), '', 'out of range is not shown');
  assert.equal(panel.lowProbability(0.62), true);
  assert.equal(panel.lowProbability(0.94), false);
  assert.equal(panel.lowProbability(null), false, 'no calibration is not "low"');
});

test('the word panel headline says how likely the headword is, and marks a less certain one', () => {
  const { MelosWordPanel: panel } = load('js/word-panel.js');
  const head = node('div', 'word-headline'); head.append(node('p', 'word-headline-parse', 'acc. fem. sg.'));
  panel.decorateHeadline(head, { lemma: 'σελήνη', parse: 'acc. fem. sg.', probability: 0.94 }, node);
  const line = head.querySelector('.word-headline-probability');
  assert.equal(line.textContent, 'Headword about 94% likely');
  assert.equal(head.children.indexOf(line), 1, 'right under the parse');
  assert.doesNotMatch(head.className, /uncertain/);
  const low = node('div', 'word-headline'); low.append(node('p', 'word-headline-parse', ''));
  panel.decorateHeadline(low, { lemma: 'σύ', parse: '', probability: 0.28 }, node);
  assert.match(low.querySelector('.word-headline-probability').textContent, /about 28% likely — another headword is possible/);
  assert.match(low.className, /word-headline-uncertain/);
  const none = node('div', 'word-headline');
  panel.decorateHeadline(none, { lemma: 'σύ', parse: '' }, node);
  assert.equal(none.querySelector('.word-headline-probability'), null, 'nothing shown without a calibration');
});

test('compact and batch dictionary entries become dictionary blocks; full entries win for the same id', () => {
  const { MelosWordPanel: panel, MelosWordPrefetch: tools } = load('js/word-panel.js');
  const compact = [{ id: 'ml:1', lemma: 'φαίνω', dictionary: 'Middle Liddell', source: 'Perseus Middle Liddell TEI (Hopper open-source texts)',
    gloss: 'to bring to light', senses: [{ label: 'A', text: 'to bring to light' }, { label: null, text: 'to exhibit' }], sense_count: 17,
    entry_excerpt: 'φαίνω φάω Act. to bring to light …', entry_url: 'https://example.org/ml' }];
  const blocks = plain(panel.dictionaryBlocks('φαίνω', compact));
  assert.equal(blocks.length, 1); assert.equal(blocks[0].title, 'Middle Liddell');
  assert.deepEqual(blocks[0].entries[0].senses, [{ label: 'A', text: 'to bring to light' }, { label: '', text: 'to exhibit' }]);
  assert.equal(blocks[0].entries[0].excerpt, true); assert.equal(blocks[0].entries[0].moreSenses, 15);
  const full = [{ id: 'ml:1', lemma: 'φαίνω', source: 'Perseus Middle Liddell TEI', dictionary_senses: [{ text: 'full sense', sense_path: [{ n: 'A' }] }],
    rendered_entry_text: 'the whole entry' }];
  const merged = plain(panel.dictionaryBlocks('φαίνω', full, compact));
  assert.equal(merged[0].entries.length, 1); assert.equal(merged[0].entries[0].text, 'the whole entry');
  assert.equal(merged[0].entries[0].excerpt, false); assert.equal(merged[0].entries[0].moreSenses, 0);
  // The batch payload's one dictionary per headline headword.
  const batch = tools.batchDictionaries({ dictionaries: { 'ἐγώ': { id: 'autenrieth:n2644', lemma: 'ἐγώ', dictionary: 'Autenrieth', gloss: 'I, me.',
    senses: [{ label: null, text: 'I, me.' }], sense_count: 1 }, 'κῆνος': null } });
  assert.deepEqual([...batch.keys()], ['ἐγώ']);
  const fromBatch = plain(panel.dictionaryBlocks('ἐγώ', batch.get('ἐγώ')));
  assert.equal(fromBatch[0].title, 'Autenrieth'); assert.equal(fromBatch[0].entries[0].senses[0].text, 'I, me.');
  assert.equal(tools.batchDictionaries({}).size, 0);
  // Rendering: "Start of the entry" for an excerpt, and the senses left in the full entry.
  const host = node('div');
  panel.renderDictionaryBlocks(host, panel.dictionaryBlocks('φαίνω', compact), node, () => null);
  assert.match(host.textContent, /15 more senses in the full entry\./);
  assert.match(host.textContent, /Start of the entry/);
});

test('batch headlines keep the calibrated probability', () => {
  const { MelosWordPrefetch: tools } = load('js/word-panel.js');
  const values = tools.batchHeadlines({ tokens: [{ start: 0, end: 3, printed: 'μοι', lemma: 'ἐγώ', parses: ['dat. 1st sg.'], probability: 0.989 },
    { start: 4, end: 7, printed: 'τοι', lemma: 'σύ', parses: [], probability: null }] }, 'μοι τοι');
  assert.equal(values.get('0:3').probability, 0.989);
  assert.equal('probability' in values.get('4:7'), false);
});

test('the reader asks the batch for dictionaries and uses the compact lemma lookup', () => {
  const reader = read('js/reader.js');
  assert.match(reader, /apiPost\('\/api\/words\/headlines', \{ passage_id: id, dictionary: true \}/);
  assert.match(reader, /const dictionaryParams = lemma => \(\{ form: lemma, lemma, compact: true, senses: 6 \}\)/);
  assert.match(reader, /wordLookup\(dictionaryParams\(lemma\)\)/);
  assert.match(reader, /panel\.dictionaryBlocks\(lemma, wordData\?\.lexicon_entries \|\| \[\], lemmaEntries\.get\(lemma\) \|\| \[\], batchEntries\)/,
    'full entries first, then compact, then the batch dictionary');
  assert.match(reader, /params\.compact \? '\|compact' : ''/, 'compact lookups have their own cache key');
  const { MelosWordPrefetch: tools } = load('js/word-panel.js');
  assert.equal(tools.VERSION, 'wp2', 'session cache shape changed');
});

test('citation lookup recognises citations, words them and opens the first passage', async () => {
  const { MelosCitation: C } = load('js/citation-lookup.js');
  for (const yes of ['Il. 1.1', 'Hom. Il. 6.146', 'Hes. Th. 116', 'Sappho fr. 31', 'Sappho 31', 'Sapph. fr. 31 V', 'Alc. 130b', 'Sappho fr. 168A LP',
    'Pind. O. 1.1', 'AP 7.1', 'Il. 1.1-1.5', 'urn:cts:greekLit:tlg0012.tlg001:1.1']) assert.equal(C.looksLikeCitation(yes), true, yes);
  for (const no of ['moon', 'λυσιμελής', 'a123b', '', '31', 'glukupikros']) assert.equal(C.looksLikeCitation(no), false, no);
  assert.equal(C.locusText([[1, ''], [1, '']]), '1.1');
  assert.equal(C.locusText([[130, 'b']]), '130b');
  const iliad = { parsed: { kind: 'locus', author: 'Homer', work: 'Iliad', locus: [[1, ''], [1, '']], locus_end: [[1, ''], [1, '']] },
    results: [{ id: 'ogc:homerus-epic.ilias.jsonl:1', author: 'Homer', work: 'Iliad', citation: '1.1', text_preview: 'μῆνιν ἄειδε θεὰ' }] };
  assert.equal(C.citationLabel(iliad), 'Iliad 1.1');
  assert.equal(C.citationLabel({ ...iliad, parsed: { ...iliad.parsed, locus_end: [[1, ''], [5, '']] } }), 'Iliad 1.1–1.5');
  assert.equal(C.citationLabel({ parsed: { kind: 'fragment', author: 'Sappho', work: null, locus: [[31, '']], locus_end: [[31, '']], scheme: null },
    results: [{ id: 'x', author: 'sappho', work: 'fragmenta', citation: '31' }] }), 'Sappho fr. 31');
  assert.equal(C.resultLabel(iliad.results[0]), 'Homer · Iliad 1.1');
  assert.equal(C.citationLabel({ parsed: null, results: [] }), '');
});

test('the search box offers "Go to …" first and Enter jumps; other words still search', () => {
  const reader = read('js/reader.js'), html = read('reader.html'), module = read('js/citation-lookup.js');
  assert.match(html, /<script src="js\/citation-lookup\.js\?v=[^"]+" defer><\/script>\s*<script src="js\/phrases\.js\?v=[^"]+" defer><\/script>\s*<script src="js\/reader\.js/);
  assert.match(html, /placeholder="[^"]*Il\. 1\.1[^"]*Sappho fr\. 31"/, 'the placeholder hints at citations');
  assert.match(read('js/reader-hero.js'), /placeholder = 'Greek, English, or Il\. 1\.1'/);
  assert.match(module, /`Go to \$\{citationLabel\(data\) \|\| resultLabel\(first\)\}`/);
  assert.match(module, /`Search the texts for “\$\{query\}”`/);
  assert.match(reader, /if \(!citations\?\.looksLikeCitation\(query\)\) \{ search\(query\); return; \}\s*citations\.jump\(query\)\.then\(opened => \{ if \(!opened\) search\(query\); \}\);/);
  assert.match(reader, /lookup: q => api\('\/api\/cite', \{ q, limit: 5 \}\)/);
  const build = read('scripts/build_frontend.mjs');
  assert.match(build, /'citation-lookup\.js', 'phrases\.js'/);
});

test('phrases: sub-phrases with the same count give way to the longer one; lists merge by strength', () => {
  const { MelosPhrases: P } = load('js/phrases.js');
  const items = [
    { n: 2, lemmas: ['πρόσθεν', 'ἄμβροτος'], count: 6, expected: 0.004, g2: 101 },
    { n: 4, lemmas: ['ὅσος', 'δέ', 'πρόσθεν', 'ἄμβροτος'], count: 6, expected: 0.006, g2: 95 },
    { n: 2, lemmas: ['γῆ', 'μέλας'], count: 10, expected: 0.03, g2: 111 },
    { n: 2, lemmas: ['καί', 'δέ'], count: 40, expected: 30, g2: 3, function_only: true }];
  assert.deepEqual(P.trim(items).map(item => item.lemmas.join(' ')), ['ὅσος δέ πρόσθεν ἄμβροτος', 'γῆ μέλας']);
  const merged = P.merge([{ label: 'Nonnus', items: [{ lemmas: ['ἐλάτειρα', 'σελήνη'], count: 7, expected: 0.1, g2: 60 }] },
    { label: 'Late antique', items: [{ lemmas: ['ἐλάτειρα', 'σελήνη'], count: 9, expected: 0.1, g2: 70 }, { lemmas: ['σελήνη', 'καί'], count: 5, expected: 1, g2: 8 }] }]);
  assert.deepEqual(plain(merged.map(item => [item.lemmas.join(' '), item.count, item.where])), [['ἐλάτειρα σελήνη', 9, 'Late antique'], ['σελήνη καί', 5, 'Late antique']]);
  assert.equal(P.timesChance({ count: 10, expected: 0.03 }), '333× more often than chance');
  assert.equal(P.timesChance({ count: 6, expected: 0.002 }), 'over 1,000× more often than chance');
  assert.equal(P.timesChance({ count: 3, expected: 2.5 }), '');
  assert.equal(P.searchHref(['γῆ', 'μέλας']), `/?q=${encodeURIComponent('γῆ μέλας')}&mode=lemma`);
});

test('phrases skip groups the service has no list for', async () => {
  const { MelosPhrases: P } = load('js/phrases.js');
  const asked = [];
  const lists = await P.listsFor([{ kind: 'author', name: 'Nonnus', label: 'Nonnus' }, { kind: 'author', name: 'Greek Anthology', label: 'Greek Anthology' }], {
    load: async () => ({ groups: [{ kind: 'author', name: 'Nonnus' }] }),
    fetchGroup: async group => { asked.push(group.name); return { ngrams: [{ lemmas: ['ἕδνον', 'ἔρως'], count: 12, expected: 0.1, g2: 90 }] }; } });
  assert.deepEqual(asked, ['Nonnus']);
  assert.equal(lists.length, 1);
});

test('variant groups are cross-linked in words from the page’s headword', () => {
  const { MelosLemmaPage: P } = load('js/word-panel.js', 'js/lemma-common.js', 'js/lemma-page.js');
  const group = { lemma_ids: [656, 3975], members: [
    { lemma_id: 656, lemma: 'ἔρως', gloss: 'love', tokens_all_records: 2265, links: [{ lemma_id: 3975, lemma: 'ἔρος', direction: 'has_variant', relation: 'poet.', dictionary: 'LSJ (Logeion edition, H. Dik) TEI', evidence: 'poet. form of ἔρως' }] },
    { lemma_id: 3975, lemma: 'ἔρος', gloss: 'love', tokens_all_records: 198, links: [
      { lemma_id: 656, lemma: 'ἔρως', direction: 'variant_of', relation: 'poet.', dictionary: 'LSJ (Logeion edition, H. Dik) TEI', evidence: 'poet. form of ἔρως' },
      { lemma_id: 656, lemma: 'ἔρως', direction: 'variant_of', relation: 'poet.', dictionary: 'Perseus Middle Liddell TEI (Hopper open-source texts)', evidence: 'ἔρος poet. form of ἔρως' }] }] };
  const fromEros = plain(P.variantLines('ἔρως', group));
  assert.equal(fromEros.length, 1);
  assert.equal(fromEros[0].lemma, 'ἔρος'); assert.equal(fromEros[0].text, 'ἔρος is a poetic form of ἔρως');
  assert.deepEqual(fromEros[0].dictionaries, ['LSJ', 'Middle Liddell']);
  const fromEros2 = plain(P.variantLines('ἔρος', group));
  assert.equal(fromEros2[0].lemma, 'ἔρως'); assert.equal(fromEros2[0].text, 'ἔρος is a poetic form of ἔρως');
  assert.deepEqual(plain(P.variantLines('θάλασσα', group)), [], 'a group that does not contain the page headword is not shown');
  assert.equal(P.relationText('πότνα', 'πότνια', 'shorter form'), 'πότνα is a shorter form of πότνια');
  assert.equal(P.relationText('ἅλιος', 'ἥλιος', 'Dor.'), 'ἅλιος is a Doric form of ἥλιος');
  assert.equal(P.relationText('ἠέλιος', 'ἥλιος', 'Ep.'), 'ἠέλιος is an epic form of ἥλιος');
  assert.equal(P.relationText('Δίιος', 'Ζεύς', '='), 'Δίιος is listed as another form of Ζεύς');
});

test('lexicon state keeps the period filter and the variants toggle; periods map to the API', () => {
  const { MelosLemmaPage: P } = load('js/lemma-common.js', 'js/lemma-page.js');
  const state = P.readState('https://greeklyric.com/lemma.html?lemma=ἔρως&period=Hellenistic%20(323%E2%80%9331%20BCE)&variants=1');
  assert.equal(state.period, 'Hellenistic (323–31 BCE)'); assert.equal(state.variants, true);
  const url = P.writeState('https://greeklyric.com/lemma.html', state);
  assert.equal(url.searchParams.get('period'), 'Hellenistic (323–31 BCE)'); assert.equal(url.searchParams.get('variants'), '1');
  assert.equal(P.writeState('https://x.test/lemma.html', { ...state, period: '', variants: false }).search, `?lemma=${encodeURIComponent('ἔρως')}`);
  assert.deepEqual(plain(P.periodParams('undated')), { undated: 'true' });
  assert.deepEqual(plain(P.periodParams('Archaic (to 480 BCE)')), { period: 'Archaic (to 480 BCE)' });
  assert.deepEqual(plain(P.periodParams('')), {});
  const page = read('js/lemma-page.js');
  assert.match(page, /\.\.\.periodParams\(state\.period\), limit: PAGE/);
  assert.match(page, /combine_variants: 'true'/);
});

test('rates carry 95% intervals and small-sample flags', () => {
  const { MelosLemma: L } = load('js/lemma-common.js');
  assert.deepEqual(plain(L.interval([1.23, 1.8])), [1.23, 1.8]);
  assert.equal(L.interval([2, 1]), null); assert.equal(L.interval(null), null); assert.equal(L.interval(['a', 1]), null);
  assert.equal(L.rangeText([0.85, 2.6]), '0.85–2.6');
  assert.equal(L.smallSample({ small_sample: true, tokens_in_group: 900000 }), true, 'the API flag wins');
  assert.equal(L.smallSample({ tokens_in_group: 4714 }), true);
  assert.equal(L.smallSample({ tokens_in_group: 720034 }), false);
  const common = read('js/lemma-common.js');
  assert.match(common, /className = 'bar-ci'|node\('span', 'bar-ci'\)/);
  assert.match(common, /class: 'chart-ci'/);
});

test('concept series read the undated row with its interval; variants counted together appear once', () => {
  const { MelosConceptPage: C } = load('js/lemma-common.js', 'js/concept-page.js');
  const item = { undated_count: 209, by_period: [
    { period: 'Archaic (to 480 BCE)', count: 107, tokens_in_period: 720034, per_10k: 1.49, per_10k_ci95: [1.23, 1.8], small_sample: false },
    { period: 'Late antique (300–600 CE)', count: 5, tokens_in_period: 4714, per_10k: 10.6, per_10k_ci95: [4.5, 24.8], small_sample: true },
    { period: 'undated', count: 209, tokens_in_period: 126745, per_10k: 16.49, per_10k_ci95: [14.4, 18.88], small_sample: false }] };
  const periods = C.periodsFrom([item]);
  assert.deepEqual(periods.map(p => p.label), ['Archaic (to 480 BCE)', 'Late antique (300–600 CE)'], 'the undated row is not a period');
  assert.deepEqual(periods.map(p => p.small), [false, true]);
  const series = C.seriesFor(item, periods, 126745);
  assert.deepEqual(plain(series.points[0].ci), [1.23, 1.8]);
  assert.equal(series.undated.value, 16.49); assert.deepEqual(plain(series.undated.ci), [14.4, 18.88]);
  const combined = C.collapseVariants([
    { lemma: 'ἔρως', counted_lemma_ids: [656, 47857, 3975], variant_group: { members: [{ lemma: 'ἔρως' }, { lemma: 'ἔρος' }] } },
    { lemma: 'φιλέω', counted_lemma_ids: [146] },
    { lemma: 'ἔρος', counted_lemma_ids: [3975, 656, 47857], variant_group: { members: [{ lemma: 'ἔρως' }, { lemma: 'ἔρος' }] } }]);
  assert.deepEqual(plain(combined.map(item => [item.lemma, item.together || []])), [['ἔρως', ['ἔρος']], ['φιλέω', []]]);
  assert.equal(C.readState('https://x.test/concept.html?q=love&variants=1').variants, true);
});

test('pages load the new modules with fresh cache tags, and the build ships them', () => {
  const build = read('scripts/build_frontend.mjs');
  for (const page of ['lemma.html', 'concept.html']) assert.match(read(page), /<script src="js\/phrases\.js\?v=[^"]+" defer><\/script>/, page);
  assert.match(build, /'phrases\.js'/);
  const tag = read('reader.html').match(/js\/reader\.js\?v=([^"]+)"/)[1];
  assert.notEqual(tag, 'lemma-20261009', 'reader.js cache tag bumped');
  assert.equal(read('reader.html').match(/js\/word-panel\.js\?v=([^"]+)"/)[1], tag);
  assert.equal(read('lemma.html').match(/js\/lemma-page\.js\?v=([^"]+)"/)[1], tag);
  assert.equal(read('concept.html').match(/js\/concept-page\.js\?v=([^"]+)"/)[1], tag);
});

test('concept words read through a dictionary head meaning say so in words', () => {
  const { MelosConceptPage: C } = load('js/lemma-common.js', 'js/concept-page.js');
  assert.equal(C.sourceText({ via: 'english_dictionary_head_meaning', gloss_source: 'Middle Liddell', matched_terms: ['love'] }, 'love'),
    'Dictionary meaning: a sense of its definition in Middle Liddell is “love”.');
  assert.match(read('js/reader.js'), /english_dictionary_head_meaning: `“\$\{query\}” is a meaning of/);
  assert.equal(load('js/lemma-common.js', 'js/lemma-page.js').MelosLemmaPage.viaText({ via: 'english_dictionary_head_meaning' }), 'an English meaning of');
});
