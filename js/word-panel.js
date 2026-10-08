// Word panel helpers: the dictionary-style reading order a classicist expects
// (headword, gloss, form + parse in words, dictionaries, notes, then sources).
// Pure functions take server fields only; nothing here invents a parse or gloss.
(() => {
  'use strict';

  // Abbreviated parse tokens (backend interlinear.compact_parse) -> category, words.
  const TOKENS = {
    'nom.': ['case', 'nominative'], 'gen.': ['case', 'genitive'], 'dat.': ['case', 'dative'],
    'acc.': ['case', 'accusative'], 'voc.': ['case', 'vocative'], 'loc.': ['case', 'locative'],
    'masc.': ['gender', 'masculine'], 'fem.': ['gender', 'feminine'], 'neut.': ['gender', 'neuter'],
    '1st': ['person', 'first person'], '2nd': ['person', 'second person'], '3rd': ['person', 'third person'],
    'sg.': ['number', 'singular'], 'pl.': ['number', 'plural'], 'du.': ['number', 'dual'],
    'pres.': ['tense', 'present'], 'impf.': ['tense', 'imperfect'], 'aor.': ['tense', 'aorist'],
    'perf.': ['tense', 'perfect'], 'plup.': ['tense', 'pluperfect'], 'fut.': ['tense', 'future'],
    'futperf': ['tense', 'future perfect'], 'past': ['tense', 'past'],
    'ind.': ['mood', 'indicative'], 'subj.': ['mood', 'subjunctive'], 'opt.': ['mood', 'optative'], 'imper.': ['mood', 'imperative'],
    'act.': ['voice', 'active'], 'mid.': ['voice', 'middle'], 'pass.': ['voice', 'passive'], 'mid./pass.': ['voice', 'middle or passive'],
    'inf.': ['verbform', 'infinitive'], 'ptcp.': ['verbform', 'participle'],
    'n.': ['pos', 'noun'], 'adj.': ['pos', 'adjective'], 'art.': ['pos', 'article'], 'pron.': ['pos', 'pronoun'],
    'v.': ['pos', 'verb'], 'adv.': ['pos', 'adverb'], 'prep.': ['pos', 'preposition'], 'conj.': ['pos', 'conjunction'],
    'part.': ['pos', 'particle'], 'interj.': ['pos', 'interjection'],
  };
  // "accusative singular feminine"; "third person singular aorist indicative active";
  // "present active participle, dative singular feminine".
  function plainParse(short) {
    if (typeof short !== 'string' || !short.trim()) return '';
    const tokens = short.trim().replace(/\bfut\. perf\./g, 'futperf').split(/\s+/);
    const found = {};
    for (const token of tokens) {
      const hit = TOKENS[token];
      if (!hit || found[hit[0]]) return short.trim();
      found[hit[0]] = hit[1];
    }
    const verb = [found.person, found.case ? '' : found.number, found.tense,
      found.verbform ? '' : found.mood, found.voice, found.verbform].filter(Boolean).join(' ');
    const nominal = [found.case, found.case ? found.number : '', found.gender].filter(Boolean).join(' ');
    const words = [verb, nominal].filter(Boolean).join(', ');
    return words || found.pos || short.trim();
  }

  const BASIS = {
    morphology_ranked_by_syntax: 'chosen by fit to the sentence',
    morphology_ranked_by_neighbour_parse: 'chosen by agreement with a neighbouring word',
    morphology_ranked_parse_consensus: 'every analysis agrees',
    morphology_top_ranked_proposal: 'best-ranked of several analyses',
    unique_compatible_candidate: 'the only analysis that fits the sentence',
    unique_candidate: 'the only analysis found',
    jev_syntax_compatible: 'fits the sentence',
    syntax_prediction: 'predicted from the sentence only; no parser analysis',
    parser_syntax_conflict: 'the parser and the sentence model disagree',
    lexical_source_syntax_conflict: 'the dictionary form and the sentence model disagree',
    conditional_lacuna_boundary: 'letters beside a gap; conditional',
    source_morphology_consensus: 'the recorded analyses agree',
  };
  function sourceName(candidate) {
    const kind = candidate?.basis || candidate?.candidate_kind;
    if (kind === 'machine_analysis') return 'Morpheus parser (Perseus)';
    if (kind === 'machine_analysis_normalised') return 'Morpheus parser, after spelling normalisation';
    if (typeof candidate?.source === 'string' && candidate.source) return plainSource(candidate.source);
    return kind ? 'an analysis recorded in the sources' : '';
  }
  // The server's `parse_source` label in reader-facing words: dictionary and
  // treebank names shortened, build commits cut to seven characters.
  function readableSourceLabel(label) {
    if (typeof label !== 'string' || !label.trim()) return '';
    const parts = label.split(/;\s*/).map(part => part.trim()).filter(Boolean)
      .map(part => /morpheus/i.test(part) ? part : plainSource(part))
      .map(part => part.replace(/\b([0-9a-f]{7})[0-9a-f]{33}\b/g, '$1'));
    return [...new Set(parts)].join('; ');
  }
  // One plain sentence: where the headline parse comes from and how it was chosen.
  function parseSource(row) {
    if (!row || typeof row !== 'object') return '';
    const given = row.parse_source && typeof row.parse_source === 'object' ? row.parse_source : null;
    const from = given?.label ? (given.kind === 'contextual_model' && row.selection_basis ? '' : readableSourceLabel(given.label))
      : sourceName(row.source_candidate);
    const how = BASIS[row.selection_basis] || '';
    if (!from && !how) return '';
    if (!from) return `${how.charAt(0).toUpperCase()}${how.slice(1)}.`;
    return `Parse from ${from}${how ? `; ${how}` : ''}.`;
  }
  // Ranked alternatives below the chosen parse (server order kept). The chosen
  // parse is not repeated, whatever the capitalisation of its headword.
  function alternatives(row) {
    const ranking = Array.isArray(row?.morphology_ranking) ? row.morphology_ranking : [];
    // Accents and breathings are ignored here: the ranking can list the chosen
    // analysis again under a mis-breathed headword (ὀ for ὁ).
    const keyOf = (lemma, parse) => `${bare(lemma)}|${parse || ''}`;
    const seen = new Set([keyOf(row?.lemma, row?.parse_short)]), out = [];
    for (const item of ranking) {
      if (!item || typeof item.parse_short !== 'string') continue;
      const key = keyOf(item.lemma, item.parse_short);
      if (seen.has(key)) continue;
      seen.add(key);
      out.push({ lemma: item.lemma || '', parse: plainParse(item.parse_short), short: item.parse_short });
    }
    return out;
  }
  function headlineDetail(row) {
    return { source: parseSource(row), alternatives: alternatives(row), ranked: true };
  }

  // Dictionary names in reader-facing form and the order a classicist reads them.
  const DICTIONARIES = [
    [/middle liddell/i, 'Middle Liddell', 'Liddell & Scott, Intermediate Greek-English Lexicon'],
    [/autenrieth/i, 'Autenrieth', 'Homeric dictionary'],
    [/\bLSJ\b|liddell.*scott.*jones/i, 'LSJ', 'Liddell, Scott & Jones, Greek-English Lexicon'],
    [/cunliffe/i, 'Cunliffe', 'Lexicon of the Homeric Dialect'],
    [/slater/i, 'Slater', 'Lexicon to Pindar'],
    [/dodson/i, 'Dodson', 'New Testament lexicon'],
    [/wiktionary|kaikki/i, 'Wiktionary', 'community dictionary'],
  ];
  function dictionaryName(source) {
    const hit = DICTIONARIES.findIndex(([pattern]) => pattern.test(String(source || '')));
    return hit < 0 ? { rank: DICTIONARIES.length, title: String(source || 'Dictionary'), subtitle: '' }
      : { rank: hit, title: DICTIONARIES[hit][1], subtitle: DICTIONARIES[hit][2] };
  }
  function plainSource(source) {
    const name = dictionaryName(source);
    if (name.rank < DICTIONARIES.length) return name.title;
    return String(source).replace(/\s*\b(?:TEI|v\d[\w.]*)\b.*$/, '').replace(/PerseusDL Greek Dependency Treebank/i, 'Perseus treebank') || String(source);
  }
  const identity = value => String(value || '').normalize('NFC').toLowerCase().replace(/\d+$/, '');
  const bare = value => identity(value).normalize('NFD').replace(/\p{M}/gu, '');
  const hash = value => /^[0-9a-f]{40,}$/i.test(String(value));
  // Only real sense numbers (A, II, 3, b), never stray markup text.
  function senseLabel(sense) {
    const path = Array.isArray(sense?.sense_path) ? sense.sense_path : [];
    return path.map(step => step?.n).filter(value => typeof value === 'string' && /^(?:[A-Za-z]|[IVXivx]{1,6}|\d{1,3})$/.test(value.trim())).join('.');
  }
  // One block per dictionary for the given headword, from the lexicon entries
  // the API already returned (several payloads may be merged).
  function dictionaryBlocks(lemma, ...entryLists) {
    const want = identity(lemma), seen = new Set(), bySource = new Map();
    if (!want) return [];
    for (const entry of entryLists.flat()) {
      if (!entry || identity(entry.lemma) !== want || seen.has(entry.id)) continue;
      seen.add(entry.id);
      const name = dictionaryName(entry.source), key = name.title;
      if (!bySource.has(key)) bySource.set(key, { ...name, source: entry.source, lemma: entry.lemma, entries: [] });
      const senses = (Array.isArray(entry.dictionary_senses) ? entry.dictionary_senses : [])
        .filter(sense => typeof sense?.text === 'string' && sense.text.trim())
        .map(sense => ({ label: senseLabel(sense), text: sense.text.trim() }));
      if (!senses.length && typeof entry.gloss === 'string' && entry.gloss.trim()) senses.push({ label: '', text: entry.gloss.trim() });
      bySource.get(key).entries.push({ senses, text: entry.rendered_entry_text || '', url: entry.entry_url || entry.source_url || '' });
    }
    return [...bySource.values()].filter(block => block.entries.some(entry => entry.senses.length || entry.text))
      .sort((a, b) => a.rank - b.rank);
  }
  const SENSES_SHOWN = 4, ENTRY_CHARS = 5000;
  function renderDictionaryBlocks(host, blocks, node, safeLink) {
    if (!blocks.length) return false;
    const section = node('section', 'word-zone word-dictionaries');
    section.append(node('h3', 'word-zone-title', blocks.length === 1 ? 'Dictionary' : `Dictionaries · ${blocks.length}`));
    blocks.forEach((block, index) => {
      const box = node('details', 'word-dictionary');
      if (index === 0) box.open = true;
      const senseCount = block.entries.reduce((sum, entry) => sum + entry.senses.length, 0);
      const summary = node('summary', 'word-dictionary-title');
      summary.append(node('span', 'word-dictionary-name', block.title));
      if (block.subtitle) summary.append(node('span', 'word-dictionary-sub', block.subtitle));
      if (senseCount > 1) summary.append(node('span', 'word-dictionary-count', `${senseCount} senses`));
      box.append(summary);
      for (const entry of block.entries) {
        const list = node('ol', 'word-dictionary-senses'), more = node('details', 'word-more');
        const moreList = node('ol', 'word-dictionary-senses');
        entry.senses.forEach((sense, i) => {
          const item = node('li', '');
          // A sense number is printed where it changes, as in the dictionary itself.
          const label = sense.label && sense.label !== entry.senses[i - 1]?.label ? sense.label : '';
          item.append(node('span', 'word-sense-label', label));
          item.append(node('span', 'word-sense-text', sense.text));
          (i < SENSES_SHOWN ? list : moreList).append(item);
        });
        if (entry.senses.length) box.append(list);
        if (moreList.children.length) {
          more.append(node('summary', '', `${entry.senses.length - SENSES_SHOWN} more senses`), moreList); box.append(more);
        }
        if (entry.text) {
          const full = node('details', 'word-more');
          const text = entry.text.length > ENTRY_CHARS ? `${entry.text.slice(0, ENTRY_CHARS).replace(/\s+\S*$/, '')} …` : entry.text;
          full.append(node('summary', '', 'Full entry'), node('p', 'word-dictionary-entry', text));
          full.lastChild.setAttribute?.('lang', 'en');
          box.append(full);
        }
        const link = safeLink?.(entry.url, `Open in ${block.title} ↗`);
        if (link) { link.className = 'word-dictionary-link'; box.append(link); }
      }
      section.append(box);
    });
    host.append(section);
    return true;
  }

  // Adds the parse in words, its source and the ranked alternatives under the
  // headline the passage-analysis module already drew.
  function decorateHeadline(head, value, node) {
    if (!head || !value || value.pending) return head;
    const parse = head.querySelector?.('.word-headline-parse');
    const short = typeof value.parse === 'string' ? value.parse : '';
    const words = plainParse(short);
    if (parse && words && words !== short) { parse.textContent = words; parse.title = short; }
    if (value.source) head.append(node('p', 'word-headline-source', value.source));
    const alts = Array.isArray(value.alternatives) ? value.alternatives : [];
    if (alts.length) {
      const box = node('div', 'word-headline-alternatives');
      box.append(node('p', 'word-headline-alt-title', value.ranked === false ? 'Possible parses (no context to rank them)' : 'Other possible parses, most likely first'));
      const list = node('ol', 'word-headline-alt-list'), rest = node('ol', 'word-headline-alt-list');
      alts.forEach((alt, i) => {
        const item = node('li', '');
        if (alt.lemma && bare(alt.lemma) !== bare(value.lemma)) { const lemma = node('span', 'word-alt-lemma', alt.lemma); lemma.setAttribute('lang', 'grc'); item.append(lemma, ' '); }
        item.append(node('span', 'word-alt-parse', alt.parse || alt.short || ''));
        (i < 3 ? list : rest).append(item);
      });
      box.append(list);
      if (rest.children.length) {
        const more = node('details', 'word-more');
        more.append(node('summary', '', `${rest.children.length} more`), rest);
        box.append(more);
      }
      head.append(box);
    }
    return head;
  }

  // Raw JSON receipts become a readable list: plain keys, no hashes.
  const KEY_WORDS = { id: 'ID', url: 'link', utf16: '', pofs: 'part of speech', gend: 'gender', num: 'number', pers: 'person', hdwd: 'headword', dial: 'dialect', stemtype: 'stem type' };
  function plainKey(key) {
    return String(key).split('_').map(part => KEY_WORDS[part] ?? part).filter(Boolean).join(' ').replace(/^./, c => c.toUpperCase());
  }
  function readableValue(value, node, depth = 0) {
    if (value == null || value === '' || hash(value)) return null;
    if (typeof value === 'string' && /^[a-z0-9]+(?:_[a-z0-9]+)+$/.test(value)) return node('span', '', value.replaceAll('_', ' '));
    if (typeof value !== 'object') return node('span', '', typeof value === 'boolean' ? (value ? 'yes' : 'no') : String(value));
    if (Array.isArray(value)) {
      if (value.every(item => item == null || typeof item !== 'object')) {
        const text = value.filter(item => item != null && !hash(item)).join(', ');
        return text ? node('span', '', text) : null;
      }
      const list = node('ol', 'readable-record-list');
      for (const item of value.slice(0, 20)) { const v = readableValue(item, node, depth + 1); if (v) { const li = node('li', ''); li.append(v); list.append(li); } }
      return list.children.length ? list : null;
    }
    if (Object.hasOwn(value, '$') && Object.keys(value).length <= 3) return readableValue(value.$, node, depth);
    if (depth > 4) return null;
    const dl = node('dl', 'readable-record');
    for (const [key, raw] of Object.entries(value)) {
      if (/(^|_)(sha256|hash|receipt_id|raw_path)$/.test(key)) continue;
      const v = readableValue(raw, node, depth + 1);
      if (!v) continue;
      dl.append(node('dt', '', plainKey(key)));
      const dd = node('dd', ''); dd.append(v); dl.append(dd);
    }
    return dl.children.length ? dl : null;
  }
  function humanizeReceipt(pre, node) {
    if (!pre || pre.dataset?.readable) return false;
    let data;
    try { data = JSON.parse(pre.textContent); } catch { return false; }
    if (!data || typeof data !== 'object') return false;
    const view = readableValue(data, node) || node('p', 'candidate-reason', 'No further details.');
    view.classList?.add('readable-receipt');
    pre.dataset.readable = '1';
    pre.replaceWith(view);
    return true;
  }
  function watchReceipts(root, node) {
    if (!root || typeof MutationObserver !== 'function') return;
    const sweep = scope => scope.querySelectorAll?.('pre').forEach(pre => humanizeReceipt(pre, node));
    sweep(root);
    new MutationObserver(records => {
      for (const record of records) for (const added of record.addedNodes) {
        if (added.nodeType !== 1) continue;
        if (added.tagName === 'PRE') humanizeReceipt(added, node); else sweep(added);
      }
    }).observe(root, { childList: true, subtree: true });
  }

  // Touch hit areas overlap their neighbours (see reader.css); a tap belongs to
  // the word whose printed box is nearest the finger, not to whichever enlarged
  // area happens to be painted on top.
  function nearestWord(root, x, y) {
    let best = null, distance = Infinity;
    for (const word of root.querySelectorAll('button.word')) {
      const r = word.getBoundingClientRect();
      if (r.bottom < y - 40 || r.top > y + 40) continue;
      const dx = Math.max(r.left - x, 0, x - r.right), dy = Math.max(r.top - y, 0, y - r.bottom), d = dx * dx + dy * dy;
      if (d < distance) { distance = d; best = word; }
    }
    return best;
  }
  function retargetTaps(root) {
    root.addEventListener('click', event => {
      const word = event.isTrusted && event.target?.closest?.('button.word');
      if (!word || (!event.clientX && !event.clientY)) return;
      const r = word.getBoundingClientRect(), x = event.clientX, y = event.clientY;
      if (x >= r.left && x <= r.right && y >= r.top && y <= r.bottom) return;
      const near = nearestWord(root, x, y);
      if (!near || near === word) return;
      event.stopImmediatePropagation(); event.preventDefault();
      near.dispatchEvent(new MouseEvent('click', { bubbles: true, cancelable: true, detail: event.detail, clientX: x, clientY: y }));
    }, true);
  }
  // Every JSON receipt the reader draws (word panel, phrase analysis, translation
  // source notes) is shown as a readable list instead of raw JSON.
  if (typeof document !== 'undefined' && document.addEventListener) {
    const make = (tag, cls, text) => { const el = document.createElement(tag); if (cls) el.className = cls; if (text != null) el.textContent = String(text); return el; };
    const start = () => { watchReceipts(document.body, make); const text = document.getElementById('passage-text'); if (text) retargetTaps(text); };
    if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', start); else start();
  }
  window.MelosWordPanel = Object.freeze({ plainParse, parseSource, readableSourceLabel, alternatives, headlineDetail, dictionaryName, plainSource,
    dictionaryBlocks, renderDictionaryBlocks, decorateHeadline, nearestWord, retargetTaps, plainKey, readableValue, humanizeReceipt, watchReceipts });
})();
