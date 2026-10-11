/* Composer logic without the page (release W, W2/W3): pool filtering, accent-insensitive prefix matching, metrical
 * fit against the scanner's templates, spill-over insertion across lines, server-sent-events parsing, the versions
 * row and the daily cost counter. Pure functions, no DOM: js/composer.js uses them in the page and
 * tests/composer-core.test.mjs in node.
 *
 *   ComposerCore.matchPrefix('φαίνεταί μοι', 'φαινεται μ') === 11
 *   ComposerCore.optionsFor(entries, beforeCaret, {template})   → options for the pop-up
 *   ComposerCore.spillInsert(drafts, line, from, to, 'ἀ σελάννα / φαίνεται')
 */
(function (root, factory) {
  const api = factory();
  if (typeof module === 'object' && module.exports) module.exports = api;
  else root.ComposerCore = api;
})(typeof self !== 'undefined' ? self : this, function () {
  'use strict';

  // ---- accent-insensitive folding -----------------------------------------------------------------------------
  // Combining marks (accents, breathings, diaeresis, iota subscript), TypeGreek's spacing marks while a letter is being
  // built, and elision marks all fold away; final sigma folds to σ; case folds.
  const MARKS = /[̀-ͯͅ´`῀᾿῾¨ͺ΄΅᾽᾿῀῁῍῎῏῝῞῟῭΅`´῾’'ʼ]/g;
  const fold = text => String(text || '').normalize('NFD').replace(MARKS, '').toLowerCase().replace(/ς/g, 'σ').normalize('NFC');

  /* Index in `candidate` just after the part `typed` stands for (accents, case and spacing ignored), or -1 when the
     candidate does not begin with it. An empty `typed` matches at 0. */
  function matchPrefix(candidate, typed) {
    const t = fold(typed).replace(/\s+/g, ' ').replace(/^ /, '');
    const c = String(candidate || '');
    let i = 0, j = 0;
    while (j < t.length) {
      if (i >= c.length) return -1;
      if (/\s/.test(c[i])) {
        if (t[j] !== ' ') return -1;
        while (i < c.length && /\s/.test(c[i])) i++;
        j++;
        continue;
      }
      const f = fold(c[i]);
      i++;
      if (!f) continue;
      for (const ch of f) {
        if (t[j] !== ch) return -1;
        j++;
        if (j >= t.length) break;
      }
    }
    while (i < c.length && fold(c[i]) === '' && !/\s/.test(c[i])) i++;   // a trailing mark belongs to the last letter
    return i;
  }

  /* The slot at the caret: `base` = the line up to the start of the word being typed, `typed` = that word so far. */
  function slotAt(lineText, caret) {
    const before = String(lineText || '').slice(0, caret);
    const typed = before.match(/\S*$/)[0];
    return { before, base: before.slice(0, before.length - typed.length), typed };
  }
  const squash = text => String(text || '').replace(/\s+/g, ' ').trim();

  // ---- metre ------------------------------------------------------------------------------------------------------
  // Same table as backend/scansion/metre.py TEMPLATES: - long, u short, x/F anceps, D biceps (– or ⏑⏑),
  // R long or resolved (⏑⏑), X anceps or resolved.
  const TEMPLATES = {
    hexameter: ['-D-D-D-D-D-F'], pentameter: ['-D-D--uu-uuF'], elegiac: ['-D-D-D-D-D-F', '-D-D--uu-uuF'],
    iambic_trimeter: ['XRuRXRuRXRuF'], trochaic_tetrameter: ['RuRXRuRXRuRXRuF'],
    sapphic_hendecasyllable: ['-u-x-uu-u-F'], adonean: ['-uu-F'],
    sapphic: ['-u-x-uu-u-F', '-u-x-uu-u-F', '-u-x-uu-u-F', '-uu-F'],
    alcaic_hendecasyllable: ['x-u-x-uu-uF'], alcaic_enneasyllable: ['x-u-x-u-F'], alcaic_decasyllable: ['-uu-uu-u-F'],
    alcaic: ['x-u-x-uu-uF', 'x-u-x-uu-uF', 'x-u-x-u-F', '-uu-uu-u-F'],
    glyconic: ['xx-uu-uF'], pherecratean: ['xx-uu-F'], hipponactean: ['xx-uu-u-F'], telesillean: ['x-uu-uF'],
    reizianum: ['x-uu-F'], aristophanean: ['-uu-u-F'], lesser_asclepiad: ['xx-uu--uu-uF'],
    greater_asclepiad: ['xx-uu--uu--uu-uF'],
  };
  /* Place of row i in its stanza: rows since the last blank row before it (a blank row separates stanzas, so the
     fourth line after a blank row is a Sapphic stanza's adonic). Same rule as the server's scan route. */
  const stanzaIndex = (drafts, i) => {
    let n = 0;
    for (let k = i - 1; k >= 0 && String(drafts[k] || '').trim(); k--) n++;
    return n;
  };
  const templateFor = (metre, lineIndex) => {
    const list = TEMPLATES[metre];
    return list ? list[((lineIndex % list.length) + list.length) % list.length] : null;
  };
  // Scanner patterns use – ⏑ ?; labels L S A (A = either).
  const labels = pattern => Array.from(String(pattern || '').replace(/[\s|]/g, ''), ch => (ch === '–' || ch === '-' || ch === 'L' ? 'L' : ch === '⏑' || ch === 'u' || ch === 'S' ? 'S' : 'A'));

  /* Every way the syllables of `pattern` can fill the start of `template`: the slots left after each, longest fill
     first. Empty list = the syllables do not fit. */
  function remainders(pattern, template) {
    const pat = Array.isArray(pattern) ? pattern : labels(pattern), tpl = String(template || '');
    const out = new Set();
    const go = (i, j) => {
      if (i === pat.length) { out.add(tpl.slice(j)); return; }
      if (j >= tpl.length) return;
      const L = pat[i] !== 'S', S = pat[i] !== 'L', S2 = S && i + 1 < pat.length && pat[i + 1] !== 'L';
      const s = tpl[j];
      if (s === '-') { if (L) go(i + 1, j + 1); }
      else if (s === 'u') { if (S) go(i + 1, j + 1); }
      else if (s === 'x' || s === 'F') go(i + 1, j + 1);
      else if (s === 'D' || s === 'R') { if (L) go(i + 1, j + 1); if (S2) go(i + 2, j + 1); }
      else if (s === 'X') { go(i + 1, j + 1); if (S2) go(i + 2, j + 1); }
    };
    go(0, 0);
    return [...out].sort((a, b) => a.length - b.length);
  }
  const remainingTemplate = (pattern, template) => {
    if (!template) return null;
    const r = remainders(pattern, template);
    return r.length ? r[0] : null;
  };
  const fitsPrefix = (pattern, template) => !template || !pattern || remainders(pattern, template).length > 0;

  // ---- slot keys (shared with the server) -------------------------------------------------------------------------
  /* The server's pool slot key (backend/composer_routes.py slot_key; docs/composer/ui.md): sha256 of
     "v1|<line position>|<prefix>|<author>|<metre>|<dialect>" (UTF-8), first 32 hex digits. The prefix is the line
     before the slot, NFC, whitespace runs collapsed to one space, trimmed; a missing setting is "". */
  const slotKeyText = (linePosition, prefix, s) => ['v1', String(Math.trunc(Number(linePosition) || 0)),
    squash(String(prefix || '').normalize('NFC')), ...['author', 'metre', 'dialect'].map(k => String((s && s[k]) || ''))].join('|');
  async function slotKey(linePosition, prefix, s) {
    const digest = await globalThis.crypto.subtle.digest('SHA-256', new TextEncoder().encode(slotKeyText(linePosition, prefix, s)));
    return Array.from(new Uint8Array(digest), b => b.toString(16).padStart(2, '0')).join('').slice(0, 32);
  }

  // ---- pool → pop-up options -----------------------------------------------------------------------------------
  const poolKey = (poemId, lineKey, base, settings) => [poemId, lineKey, squash(base), settingsSig(settings)].join('|');
  const settingsSig = s => s ? [s.author || '', s.metre || '', s.dialect || ''].join('/') : '';
  const patternOf = cand => {
    if (!cand) return '';
    if (cand.pattern) return cand.pattern;
    if (cand.fit && cand.fit.pattern) return cand.fit.pattern;
    const lines = cand.scansion && cand.scansion.lines;
    return Array.isArray(lines) ? lines.map(l => l.pattern || '').join(' | ') : '';
  };

  /* Options for the pop-up. `entries`: pools [{base, template?, source, candidates: [{greek, ...}]}] for this line;
     `before`: the line up to the caret. A pool applies when the line still begins with its base; its candidates are
     matched against what was typed since (accent-insensitive), and a candidate with a pattern must fit the slots that
     were open at its base. Most specific pool first, the model's before the corpus's; one option per continuation. */
  function optionsFor(entries, before, { limit = 8, mode } = {}) {
    const out = [], seen = new Set();
    const pools = (entries || []).filter(e => e && String(before).startsWith(e.base || ''))
      .sort((a, b) => (b.base || '').length - (a.base || '').length || (a.source === 'corpus') - (b.source === 'corpus'));
    for (const entry of pools) {
      const base = entry.base || '', typed = String(before).slice(base.length);
      for (const cand of entry.candidates || []) {
        const greek = String(cand.greek || '');
        const end = matchPrefix(greek, typed);
        if (end < 0 || !greek.slice(end).trim()) continue;          // no match, or nothing left to insert
        if (cand.verdict === 'fail') continue;                         // corpus lines that failed the lint
        const candMode = cand.mode || entry.mode || 'line';
        if (mode && candMode !== mode) continue;
        const pattern = patternOf(cand);
        if (entry.template && pattern && !fitsPrefix(pattern.split(' | ')[0], entry.template)) continue;
        const key = fold(greek).replace(/\s+/g, ' ');
        if (seen.has(key)) continue;
        seen.add(key);
        out.push({ greek, from: base.length, typed: greek.slice(0, end), rest: greek.slice(end), pattern, mode: candMode,
          english: cand.english_span || '', evidence: cand.evidence || [], checks: cand.checks || [],
          source: entry.source || cand.source_kind || 'agent', citation: cand.source && cand.source.citation
            ? `${cand.source.author || ''} ${cand.source.citation}`.trim() : '', scansion: cand.scansion || null });
        if (out.length >= limit) return out;
      }
    }
    return out;
  }
  /* How many continuations earlier pools on this line still offer (used to skip a new model request); `mode`
     counts one tier only (words | line). */
  const reusable = (entries, before, mode) => optionsFor((entries || []).filter(e => e.source !== 'corpus'), before, { limit: 99, mode }).length;

  /* The two-tier pop-up: next words (short, fast) first, then whole-line continuations (model and corpus). Returns
     the flat option list (one keyboard index) and the tiers [{name, from, count}] for the headers. */
  function tiered(entries, before, { words = 6, lines = 8 } = {}) {
    const w = optionsFor(entries, before, { limit: words, mode: 'words' });
    const l = optionsFor(entries, before, { limit: lines, mode: 'line' });
    const tiers = [];
    if (w.length) tiers.push({ name: 'words', label: 'next words', from: 0, count: w.length });
    if (l.length) tiers.push({ name: 'line', label: 'whole lines', from: w.length, count: l.length });
    return { options: [...w, ...l], tiers };
  }

  // ---- spill-over insertion ---------------------------------------------------------------------------------------
  // A continuation may carry line breaks: a newline, or " / " between lines.
  const splitSpill = text => String(text || '').split(/\s*\n\s*|\s+\/\s+/).filter((s, i, all) => s || i === 0 || i === all.length - 1);

  /* Replace drafts[line][from, to) with `text`; segments past the first go to the following lines: an empty next
     line is filled, otherwise a new line is inserted (written lines are never overwritten). The rest of the original
     line after `to` follows the last segment. Returns {drafts, line, caret, inserted: [indices], completed: [indices]}
     (completed = lines the continuation finished, which the page saves). */
  function spillInsert(drafts, line, from, to, text) {
    const out = drafts.slice();
    const segs = splitSpill(text);
    const head = (out[line] || '').slice(0, from), tail = (out[line] || '').slice(to);
    const inserted = [], completed = [];
    if (segs.length === 1) {
      const value = head + segs[0] + (tail || ' ');
      out[line] = value;
      return { drafts: out, line, caret: head.length + segs[0].length + (tail && /^\s/.test(tail) ? 1 : tail ? 0 : 1), inserted, completed };
    }
    out[line] = (head + segs[0]).replace(/\s+$/, '');
    completed.push(line);
    let at = line;
    segs.slice(1).forEach((seg, k) => {
      at += 1;
      const last = k === segs.length - 2;
      const value = last ? seg + (tail ? (/^\s/.test(tail) ? tail : ' ' + tail) : ' ') : seg;
      if (at < out.length && !out[at].trim() && !inserted.includes(at)) out[at] = value;
      else { out.splice(at, 0, value); inserted.push(at); }
      if (!last) completed.push(at);
    });
    return { drafts: out, line: at, caret: segs[segs.length - 1].length + 1, inserted, completed };
  }

  // ---- server-sent events ---------------------------------------------------------------------------------------
  /* Incremental parser (the same rules as backend/composer_routes.py SSEParser): feed text, get [{event, data}];
     data is JSON-decoded when it can be, and a data object's `type` names the event (the agent sends data-only). */
  class SSEParser {
    constructor() { this.buffer = ''; }
    feed(chunk) {
      this.buffer += String(chunk).replace(/\r\n/g, '\n');
      const out = [];
      let at;
      while ((at = this.buffer.indexOf('\n\n')) > -1) {
        const block = this.buffer.slice(0, at);
        this.buffer = this.buffer.slice(at + 2);
        let event = 'message';
        const data = [];
        for (const line of block.split('\n')) {
          if (!line || line.startsWith(':')) continue;
          const colon = line.indexOf(':');
          const name = colon < 0 ? line : line.slice(0, colon);
          let value = colon < 0 ? '' : line.slice(colon + 1);
          if (value.startsWith(' ')) value = value.slice(1);
          if (name === 'event') event = value;
          else if (name === 'data') data.push(value);
        }
        if (!data.length) continue;
        const text = data.join('\n');
        let parsed = text;
        try { parsed = JSON.parse(text); } catch (e) { /* plain text data */ }
        if (parsed && typeof parsed === 'object' && typeof parsed.type === 'string') event = parsed.type;
        out.push({ event, data: parsed });
      }
      return out;
    }
  }
  /* Read a fetch Response body as SSE, calling onEvent({event, data}) for each; resolves when the stream ends. */
  async function readSSE(response, onEvent) {
    const reader = response.body.getReader(), decoder = new TextDecoder(), parser = new SSEParser();
    for (;;) {
      const { value, done } = await reader.read();
      if (done) break;
      for (const ev of parser.feed(decoder.decode(value, { stream: true }))) onEvent(ev);
    }
    for (const ev of parser.feed(decoder.decode() + '\n\n')) onEvent(ev);
  }

  // ---- versions row ---------------------------------------------------------------------------------------------
  function checkBadges(checks) {
    return (checks || []).map(c => {
      const state = c.verdict || (c.ok === true ? 'pass' : c.ok === false ? (c.blocking ? 'fail' : 'warn') : 'info');
      return { id: c.id || '?', state, title: `${c.name || c.id || ''}: ${c.detail || c.message || ''}`.trim() };
    });
  }
  /* Cards for one line, oldest first (left to right). Archived versions are hidden unless asked for. */
  function versionsRow(line, { showArchived = false } = {}) {
    const all = (line && line.versions || []).slice().sort((a, b) => (a.created_at || 0) - (b.created_at || 0) || a.id - b.id);
    const cards = all.filter(v => showArchived || !v.archived).map(v => ({
      id: v.id, greek: v.greek, source: v.source || 'owner', created_at: v.created_at, archived: !!v.archived,
      current: v.id === line.current_version_id, pass: v.scansion ? v.scansion.pass !== false : null,
      pattern: v.scansion && Array.isArray(v.scansion.lines) ? v.scansion.lines.map(l => l.pattern).join(' | ') : '',
      badges: checkBadges(v.checks), back_translation: v.back_translation || '',
    }));
    return { cards, archivedCount: all.filter(v => v.archived).length, currentIndex: cards.findIndex(c => c.current) };
  }
  /* The line after a version is archived (the store's rule): the newest version not archived becomes current. */
  function archiveVersion(line, versionId, archived = true) {
    const versions = line.versions.map(v => (v.id === versionId ? { ...v, archived } : v));
    let current = line.current_version_id;
    if (archived && current === versionId) {
      const live = versions.filter(v => !v.archived).sort((a, b) => b.id - a.id)[0];
      current = live ? live.id : null;
    }
    return { ...line, versions, current_version_id: current, current: versions.find(v => v.id === current) || null };
  }

  // ---- cost ----------------------------------------------------------------------------------------------------------
  const pacificDay = (date = new Date()) => new Intl.DateTimeFormat('en-CA', { timeZone: 'America/Los_Angeles', year: 'numeric', month: '2-digit', day: '2-digit' }).format(date);
  /* Add `usd` to today's total (Pacific day) in `storage` (localStorage-like); returns the new total. */
  function addCost(storage, usd, date = new Date()) {
    const key = 'melos-composer-cost-' + pacificDay(date);
    let total = 0;
    try { total = Number(storage.getItem(key)) || 0; } catch (e) { /* storage blocked */ }
    total += Number(usd) || 0;
    try { storage.setItem(key, String(Math.round(total * 1e6) / 1e6)); } catch (e) { /* storage blocked */ }
    return total;
  }
  const todayCost = (storage, date = new Date()) => {
    try { return Number(storage.getItem('melos-composer-cost-' + pacificDay(date))) || 0; } catch (e) { return 0; }
  };
  const money = usd => (usd >= 10 ? `$${usd.toFixed(1)}` : `$${(Number(usd) || 0).toFixed(2)}`);

  /* Release X.3: per-word attestation verdicts from the lint bank (POST /api/composer/check: L1 forms, L2 dialect,
     L4 attestation). Map form -> {form, level: ok | warn | bad | unknown, note}.
       ok      the spelling is printed by the poet, or by poets of the dialect (or anywhere, when no dialect is set)
       warn    printed nowhere in the corpus (a reading exists: a plausible but unattested form), or printed only
               outside the dialect with no dialect spelling known
       bad     no reading at all, or the dialect's poets print another spelling of the word (σελήνη -> σελάννα)
       unknown the lookup missed the budget */
  const ATT_RANK = { unknown: 0, ok: 1, warn: 2, bad: 3 };
  function attestWords(checks, { author = '', dialect = '' } = {}) {
    const by = id => (Array.isArray(checks) ? checks : []).find(c => c && c.id === id) || {};
    const out = new Map();
    const put = (form, level, note) => {
      if (typeof form !== 'string' || !form) return;
      const cur = out.get(form);
      if (!cur || ATT_RANK[level] > ATT_RANK[cur.level]) out.set(form, { form, level, note });
      else if (ATT_RANK[level] === ATT_RANK[cur.level] && note && !cur.note.includes(note)) cur.note += ' · ' + note;
    };
    const l1 = by('L1'), l2 = by('L2'), l4 = by('L4');
    const morph = new Map();
    for (const e of l1.evidence || []) {
      if (!e || typeof e.form !== 'string') continue;
      if (e.reading === 'morpheus') morph.set(e.form, Array.isArray(e.lemmas) ? e.lemmas : []);
      else if (e.reading === 'timeout') put(e.form, 'unknown', 'not checked in time');
      else if (e.reading == null) put(e.form, 'bad', 'no reading in the corpus index or Morpheus');
    }
    const cite = ex => ex && typeof ex === 'object' ? [ex.author, ex.citation].filter(Boolean).join(' ') : '';
    for (const e of l4.evidence || []) {
      if (!e || typeof e.form !== 'string') continue;
      const ex = cite(e.example) ? ` (${cite(e.example)})` : '';
      if (!e.tokens) {
        const lemmas = morph.get(e.form) || [];
        put(e.form, 'warn', `this spelling is printed nowhere in the corpus${lemmas.length ? `; reads as ${lemmas.join(' / ')}` : ''}`);
      } else if (e.author_tokens) put(e.form, 'ok', `printed ${e.author_tokens}× by ${author || 'the poet'}${ex}`);
      else if (e.dialect_tokens) put(e.form, 'ok', `printed ${e.dialect_tokens}× by ${dialect || 'dialect'} poets${ex}`);
      else if (e.dialect_tokens === 0) put(e.form, 'warn', `printed ${e.tokens}× in the corpus, never by a ${dialect || 'dialect'} poet${ex}`);
      else put(e.form, 'ok', `printed ${e.tokens}× in the corpus${ex}`);
    }
    for (const e of l2.evidence || []) {
      if (!e || typeof e.form !== 'string') continue;
      if (e.reading === 'timeout') put(e.form, 'unknown', 'not checked in time');
      else if (Array.isArray(e.dialect_spellings) && e.dialect_spellings.length) {
        put(e.form, 'bad', `${dialect || 'the dialect\'s'} poets print ${e.dialect_spellings.map(s => s.form + (s.example ? ` (${s.example})` : '')).join(', ')}`);
      } else if (e.dialects && typeof e.dialects === 'object') put(e.form, 'warn', `printed only by ${Object.keys(e.dialects).join(' / ')} poets`);
    }
    return out;
  }

  return { fold, matchPrefix, slotAt, squash, TEMPLATES, templateFor, labels, remainders, remainingTemplate, fitsPrefix,
    slotKeyText, slotKey, poolKey, settingsSig, patternOf, optionsFor, reusable, tiered, splitSpill, spillInsert, SSEParser, readSSE, checkBadges,
    versionsRow, archiveVersion, pacificDay, addCost, todayCost, money, attestWords, stanzaIndex };
});
