// Word panel helpers: the dictionary-style reading order a classicist expects
// (headword, gloss, form + parse in words, dictionaries, notes, then sources).
// Pure functions take server fields only; nothing here invents a parse or gloss.
// The second block (window.MelosWordPrefetch) is the panel's loading layer.
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
    'comp.': ['degree', 'comparative'], 'sup.': ['degree', 'superlative'],
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
    const nominal = [found.case, found.case ? found.number : '', found.gender, found.degree].filter(Boolean).join(' ');
    const words = [verb, nominal].filter(Boolean).join(', ');
    // An adverb's degree alone: "adverb, superlative".
    if (!words.replace(found.degree || '', '').trim() && found.pos) return [found.pos, found.degree].filter(Boolean).join(', ');
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
  // parse is not repeated, whatever the capitalisation of its headword. When the
  // API lists `alternatives` (other headwords for the same spelling) they follow
  // the chosen headword's own other parses; otherwise the ranked parses are the
  // alternatives. A ranking entry that only repeats the printed spelling as a
  // headword, with no parse, is not a reading.
  const unelided = value => bare(String(value || '').replace(/[’'᾽ʼ]/gu, ''));
  function alternatives(row, chosen = row) {
    const ranking = Array.isArray(row?.morphology_ranking) ? row.morphology_ranking : [];
    // Accents and breathings are ignored here: the ranking can list the chosen
    // analysis again under a mis-breathed headword (ὀ for ὁ).
    const keyOf = (lemma, parse) => `${bare(lemma)}|${parse || ''}`;
    const printed = unelided(row?.text);
    const seen = new Set([keyOf(chosen?.lemma, chosen?.parse_short)]), out = [];
    const add = (lemma, short, extra = {}) => {
      const key = keyOf(lemma, short);
      if (seen.has(key) || (!short && (!lemma || unelided(lemma) === printed))) return;
      seen.add(key);
      out.push({ lemma: lemma || '', parse: plainParse(short), short: short || '', ...extra });
    };
    const given = Array.isArray(row?.alternatives) ? row.alternatives.filter(alt => typeof alt?.lemma === 'string' && alt.lemma.trim()) : [];
    for (const item of ranking) {
      if (!item || typeof item.parse_short !== 'string') continue;
      if (given.length && bare(item.lemma) !== bare(chosen?.lemma)) continue;
      add(item.lemma, item.parse_short);
    }
    for (const alt of given) {
      const parses = (Array.isArray(alt.parses) ? alt.parses : [alt.parse_short]).filter(item => typeof item === 'string');
      const gloss = typeof alt.gloss === 'string' ? alt.gloss : typeof alt.gloss?.short_text === 'string' ? alt.gloss.short_text : '';
      const form = [alt.restored, alt.reading, alt.restored_form].find(item => typeof item === 'string' && item.trim()) || '';
      add(alt.lemma.trim(), parses[0] || '', { gloss: gloss.trim(), form });
    }
    return out;
  }
  // A tie the server left open (no `lemma` on the row) still has a headline:
  // the top-ranked reading, with the others listed beside it.
  function headlineDetail(row) {
    const ranking = Array.isArray(row?.morphology_ranking) ? row.morphology_ranking : [];
    // A lemma spelt like the printed word is skipped only for an elided word (σ’ is not a
    // headword); δύο, πότνια, indeclinables are their own headwords.
    const elided = /[’'᾽ʼ]$/u.test(String(row?.text || ''));
    const usable = item => typeof item?.lemma === 'string' && item.lemma.trim() && typeof item.parse_short === 'string'
      && item.parse_short && !(elided && unelided(item.lemma) === unelided(row.text));
    // The backend's ranked headline (release O) leads; its own best-ranked parse goes with it.
    const head = row && !row.lemma && typeof row.headline_lemma === 'string' && row.headline_lemma.trim()
      ? ranking.find(item => usable(item) && bare(item.lemma) === bare(row.headline_lemma)) : null;
    let top = row && !row.lemma ? head || ranking.find(usable) : null;
    // A settled headword without a parse of its own takes its best-ranked parse; a headline headword with
    // no parsed reading at all (an indeclinable, a crasis) is still named.
    if (row && row.lemma && !row.parse_short) {
      const own = ranking.find(item => usable(item) && bare(item.lemma) === bare(row.lemma));
      if (own) top = own;
    }
    if (row && !row.lemma && !top && typeof row.headline_lemma === 'string' && row.headline_lemma.trim()
      && !(elided && unelided(row.headline_lemma) === unelided(row.text))) top = { lemma: row.headline_lemma, parse_short: '' };
    const chosen = top ? { lemma: top.lemma, parse_short: top.parse_short } : row;
    const alts = alternatives(row, chosen);
    const detail = { source: parseSource(row), alternatives: alts, ranked: true,
      tie: alts.some(alt => alt.lemma && bare(alt.lemma) !== bare(chosen?.lemma)) };
    if (top) Object.assign(detail, { lemma: top.lemma, parse: top.parse_short || row.parse_short, properName: /^\p{Lu}/u.test(top.lemma.normalize('NFD')) });
    return detail;
  }
  // A short gloss for a headword from dictionary entries already loaded: the
  // entry's own gloss or its first sense, up to the first clause.
  function entryGloss(lemma, entries) {
    const want = identity(lemma);
    for (const entry of Array.isArray(entries) ? entries : []) {
      if (!entry || !want || identity(entry.lemma) !== want) continue;
      const sense = (Array.isArray(entry.dictionary_senses) ? entry.dictionary_senses : []).find(item => typeof item?.text === 'string' && item.text.trim());
      const text = (typeof entry.gloss === 'string' && entry.gloss.trim()) || sense?.text.trim() || '';
      if (!text) continue;
      const cut = text.split(/[;:]/)[0].trim().replace(/[.,]$/, '');
      return { text: cut.length > 60 ? `${cut.slice(0, 60).replace(/\s+\S*$/, '')} …` : cut, source: plainSource(entry.source) };
    }
    return null;
  }
  // The other readings' missing short glosses, from entries already loaded.
  function withAlternativeGlosses(value, entries) {
    if (!value || !Array.isArray(value.alternatives)) return value;
    let changed = false;
    const alts = value.alternatives.map(alt => {
      if (alt.gloss || !alt.lemma || bare(alt.lemma) === bare(value.lemma)) return alt;
      const found = entryGloss(alt.lemma, entries);
      if (!found) return alt;
      changed = true;
      return { ...alt, gloss: found.text, glossSource: found.source };
    });
    return changed ? { ...value, alternatives: alts } : value;
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
    return path.map(step => step?.n).filter(value => typeof value === 'string' && /^(?:[A-Za-z]|[IVXivx]{1,6}|[1-9]\d{0,2})$/.test(value.trim())).join('.');
  }
  // A calibrated probability (release P) in words: "about 94% likely".
  function probabilityText(value) {
    const p = Number(value);
    if (value === null || value === undefined || value === '' || !Number.isFinite(p) || p < 0 || p > 1) return '';
    if (p >= 0.995) return 'over 99% likely';
    return `about ${Math.max(1, Math.round(p * 100))}% likely`;
  }
  // Headwords under this probability get a quiet "less certain" marker.
  const LOW_PROBABILITY = 0.8;
  const lowProbability = value => value !== null && value !== undefined && value !== '' && Number.isFinite(Number(value)) && Number(value) < LOW_PROBABILITY;
  // Compact entries (release P: batch `dictionaries`, `/api/word … compact=true`)
  // carry `senses: [{label, text}]` and a short `entry_excerpt`; full entries
  // carry `dictionary_senses` and the whole `rendered_entry_text`.
  function entrySenses(entry) {
    if (Array.isArray(entry.dictionary_senses)) return entry.dictionary_senses
      .filter(sense => typeof sense?.text === 'string' && sense.text.trim())
      .map(sense => ({ label: senseLabel(sense), text: sense.text.trim() }));
    return (Array.isArray(entry.senses) ? entry.senses : [])
      .filter(sense => typeof sense?.text === 'string' && sense.text.trim())
      .map(sense => ({ label: typeof sense.label === 'string' && /^(?:[A-Za-z]|[IVXivx]{1,6}|[1-9]\d{0,2})$/.test(sense.label.trim()) ? sense.label.trim() : '', text: sense.text.trim() }));
  }
  // One block per dictionary for the given headword, from the lexicon entries
  // the API already returned (several payloads may be merged; for one entry id
  // the first list that has it wins, so pass full entries before compact ones).
  function dictionaryBlocks(lemma, ...entryLists) {
    const want = identity(lemma), seen = new Set(), bySource = new Map();
    if (!want) return [];
    for (const entry of entryLists.flat()) {
      if (!entry || identity(entry.lemma) !== want || seen.has(entry.id)) continue;
      seen.add(entry.id);
      const name = dictionaryName(entry.source || entry.dictionary), key = name.title;
      if (!bySource.has(key)) bySource.set(key, { ...name, source: entry.source || entry.dictionary, lemma: entry.lemma, entries: [] });
      const senses = entrySenses(entry);
      if (!senses.length && typeof entry.gloss === 'string' && entry.gloss.trim()) senses.push({ label: '', text: entry.gloss.trim() });
      const full = typeof entry.rendered_entry_text === 'string' && entry.rendered_entry_text.trim();
      const excerpt = !full && typeof entry.entry_excerpt === 'string' ? entry.entry_excerpt.trim() : '';
      const total = Number(entry.sense_count);
      bySource.get(key).entries.push({ senses, text: full || excerpt, excerpt: Boolean(excerpt), url: entry.entry_url || entry.source_url || '',
        moreSenses: !Array.isArray(entry.dictionary_senses) && Number.isInteger(total) && total > senses.length ? total - senses.length : 0 });
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
        if (entry.moreSenses) box.append(node('p', 'word-dictionary-partial', `${entry.moreSenses} more ${entry.moreSenses === 1 ? 'sense' : 'senses'} in the full entry.`));
        if (entry.text) {
          const full = node('details', 'word-more');
          const text = entry.text.length > ENTRY_CHARS ? `${entry.text.slice(0, ENTRY_CHARS).replace(/\s+\S*$/, '')} …` : entry.text;
          full.append(node('summary', '', entry.excerpt ? 'Start of the entry' : 'Full entry'), node('p', 'word-dictionary-entry', text));
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
  // headline the passage-analysis module already drew. When another headword is
  // possible (σ’: σύ or σός) the readings come first, the top-ranked one first,
  // each with its restored form, parse and short gloss.
  function decorateHeadline(head, value, node) {
    if (!head || !value || value.pending) return head;
    // The headword opens its lexicon page (dictionaries, frequency, contexts).
    const title = head.querySelector?.('.word-headline-lemma');
    if (title && value.lemma && typeof document !== 'undefined' && !title.querySelector?.('a')) {
      const link = document.createElement('a');
      link.className = 'word-headline-link'; link.href = `lemma.html?lemma=${encodeURIComponent(value.lemma)}`;
      link.textContent = title.textContent; link.lang = 'grc';
      link.title = `Open ${value.lemma} in the lexicon: all its forms, how often it is used, every passage and its usual companions`;
      title.textContent = ''; title.append(link);
      const more = document.createElement('a');
      more.className = 'word-headline-lexicon'; more.href = link.href;
      more.textContent = 'All forms, frequency and passages in the lexicon →';
      head.append(more);
    }
    // How likely the machine reading is (calibrated against hand-checked
    // treebank lemmas), in words; a less certain headword gets a quiet marker.
    const likely = value.lemma ? probabilityText(value.probability) : '';
    if (likely) {
      const low = lowProbability(value.probability);
      const line = node('p', `word-headline-probability${low ? ' is-low' : ''}`,
        `Headword ${likely}${low ? ' — another headword is possible' : ''}`);
      line.title = 'How often a machine reading this sure was right when checked against hand-made treebank lemmas (Homer, Hesiod, Sophocles, Aeschylus).';
      if (low) head.classList?.add?.('word-headline-uncertain');
      const parseLine = head.querySelector?.('.word-headline-parse');
      if (parseLine?.after) parseLine.after(line); else head.append(line);
    }
    const parse = head.querySelector?.('.word-headline-parse');
    const short = typeof value.parse === 'string' ? value.parse : '';
    const words = plainParse(short);
    if (parse && words && words !== short) { parse.textContent = words; parse.title = short; }
    if (value.source) head.append(node('p', 'word-headline-source', value.source));
    const alts = Array.isArray(value.alternatives) ? value.alternatives : [];
    const others = [], lemmas = new Set([bare(value.lemma)]);
    const rest = alts.filter(alt => {
      if (!value.lemma || !alt.lemma || lemmas.has(bare(alt.lemma))) return true;
      lemmas.add(bare(alt.lemma)); others.push(alt); return false;
    });
    if (others.length) {
      const box = node('div', 'word-headline-readings'), count = others.length + 1, number = count === 2 ? 'Two' : String(count);
      box.append(node('p', 'word-headline-alt-title', value.ranked === false
        ? `${number} possible readings (no context to rank them)` : `${number} possible readings, most likely first`));
      const list = node('ol', 'word-headline-reading-list');
      const reading = (alt, top) => {
        const item = node('li', top ? 'word-reading word-reading-top' : 'word-reading');
        const lemma = node('span', 'word-reading-lemma', alt.lemma); lemma.setAttribute('lang', 'grc'); item.append(lemma);
        const restored = top ? value.reading : alt.form;
        if (restored && restored !== value.form) { const form = node('span', 'word-reading-form', ` (read ${restored})`); form.setAttribute('lang', 'grc'); item.append(form); }
        const parsed = top ? words || short : alt.parse || plainParse(alt.short);
        if (parsed) item.append(node('span', 'word-reading-parse', ` · ${parsed}`));
        const gloss = top ? value.gloss : alt.gloss;
        if (gloss) { const text = node('span', 'word-reading-gloss', ` · “${gloss}”`); text.setAttribute('lang', 'en'); if (alt.glossSource) text.title = `Short gloss from ${alt.glossSource}`; item.append(text); }
        list.append(item);
      };
      reading({ lemma: value.lemma }, true);
      for (const alt of others) reading(alt, false);
      box.append(list);
      head.append(box);
    }
    if (rest.length) {
      const box = node('div', 'word-headline-alternatives');
      box.append(node('p', 'word-headline-alt-title', value.ranked === false ? 'Possible parses (no context to rank them)' : 'Other possible parses, most likely first'));
      const list = node('ol', 'word-headline-alt-list'), more = node('ol', 'word-headline-alt-list');
      rest.forEach((alt, i) => {
        const item = node('li', '');
        if (alt.lemma && bare(alt.lemma) !== bare(value.lemma)) { const lemma = node('span', 'word-alt-lemma', alt.lemma); lemma.setAttribute('lang', 'grc'); item.append(lemma, ' '); }
        item.append(node('span', 'word-alt-parse', alt.parse || alt.short || ''));
        (i < 3 ? list : more).append(item);
      });
      box.append(list);
      if (more.children.length) {
        const details = node('details', 'word-more');
        details.append(node('summary', '', `${more.children.length} more`), more);
        box.append(details);
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
  window.MelosWordPanel = Object.freeze({ plainParse, parseSource, readableSourceLabel, alternatives, headlineDetail, entryGloss, withAlternativeGlosses, dictionaryName, plainSource,
    probabilityText, lowProbability, LOW_PROBABILITY, dictionaryBlocks, renderDictionaryBlocks, decorateHeadline, nearestWord, retargetTaps, plainKey, readableValue, humanizeReceipt, watchReceipts });
})();

// Word-panel loading: an in-memory LRU backed by sessionStorage, one request
// per key at a time, a small low-priority queue that a passage change cancels,
// and the rules for what to fetch ahead of a click. Nothing here builds a
// parse or a gloss; it only stores and orders what the API returned.
(() => {
  'use strict';

  // Bump when the cached shapes change; old session entries are then ignored.
  const VERSION = 'wp2';

  function createLru(max) {
    const map = new Map();
    return {
      get(key) { if (!map.has(key)) return undefined; const value = map.get(key); map.delete(key); map.set(key, value); return value; },
      set(key, value) { map.delete(key); map.set(key, value); while (map.size > max) map.delete(map.keys().next().value); },
      has: key => map.has(key),
      delete: key => map.delete(key),
      get size() { return map.size; },
    };
  }

  // sessionStorage with a character budget and oldest-first eviction. Every
  // access is guarded: private windows, previews and full quotas just miss.
  function createStore(storage, prefix, { budget = 1500000, maxItem = 400000 } = {}) {
    const orderKey = `${prefix}#order`;
    let order = [];
    try { order = JSON.parse(storage?.getItem(orderKey) || '[]'); if (!Array.isArray(order)) order = []; } catch { order = []; }
    const size = () => order.reduce((sum, item) => sum + (item[1] || 0), 0);
    const saveOrder = () => { try { storage.setItem(orderKey, JSON.stringify(order)); } catch { /* order is advisory */ } };
    const evict = () => {
      const oldest = order.shift();
      if (!oldest) return false;
      try { storage.removeItem(prefix + oldest[0]); } catch { /* ignore */ }
      return true;
    };
    return {
      get(key) {
        if (!storage) return undefined;
        try { const raw = storage.getItem(prefix + key); return raw == null ? undefined : JSON.parse(raw); } catch { return undefined; }
      },
      set(key, value) {
        if (!storage) return false;
        let raw;
        try { raw = JSON.stringify(value); } catch { return false; }
        if (typeof raw !== 'string' || raw.length > maxItem) return false;
        order = order.filter(item => item[0] !== key);
        while (order.length && size() + raw.length > budget) evict();
        for (let attempt = 0; attempt < 6; attempt++) {
          try { storage.setItem(prefix + key, raw); order.push([key, raw.length]); saveOrder(); return true; }
          catch { if (!evict()) return false; }
        }
        return false;
      },
    };
  }

  // What the connection allows ahead of a click. Data saver: nothing
  // speculative. 2G: only the word under the finger or pointer. 3G or a slow
  // downlink: a few idle words, one request at a time.
  function networkPolicy(connection) {
    const c = connection || {};
    if (c.saveData) return { batch: false, hover: false, idle: 0, maxLow: 0, reason: 'save-data' };
    const type = String(c.effectiveType || '');
    if (type === 'slow-2g' || type === '2g') return { batch: true, hover: true, idle: 0, maxLow: 1, reason: type };
    if (type === '3g' || (typeof c.downlink === 'number' && c.downlink > 0 && c.downlink < 1.5)) return { batch: true, hover: true, idle: 3, maxLow: 1, delay: 2500, reason: '3g' };
    return { batch: true, hover: true, idle: 6, maxLow: 2, delay: 0, reason: 'default' };
  }

  const fold = value => String(value || '').normalize('NFD').replace(/\p{M}/gu, '').toLowerCase()
    .replace(/[’'᾽ʼ᾿]/gu, '').replaceAll('ς', 'σ').replace(/[^\p{L}]/gu, '');
  // Articles, particles, conjunctions, prepositions and personal pronouns:
  // these come from the server's cache quickly and are rarely what a reader
  // needs explained, so idle prefetch leaves them to the click.
  const FREQUENT = new Set(`ο η το τον την τα του τησ τω τη οι αι τοι ται των τοισ ταισ τουσ τασ τοισι ταισι τασ
    δε δ τε τ γαρ μεν και κε κεν αν γε γ ου ουκ ουχ μη μηδε ουδε αλλα αλλ ωσ η ηδε εν ενι εσ εισ εκ εξ απο απ
    επι επ περι προσ ποτι παρα παρ κατα κατ μετα μετ υπο υπ συν ξυν ω αι ει οτι οττι οτε δη αρα ρα νυν νυ τοι
    μοι μοι σοι με σε μ σ μιν νιν εγω εγων συ αμμι αμμε υμμι υμμε κ οσ οσσ ουτοσ τισ τι τιν οππωσ ωσπερ ειτ
    ηκ ουτε μητε τε ου κουκ κου κηκ καμμ κ αυ αυτε δηυτε αυτ αυτοσ`.split(/\s+/).filter(Boolean));
  const CONTENT_POS = /noun|verb|adj|name|propn|participle/i;
  const FUNCTION_POS = /article|particle|conj|prep|pron|interj|adverb/i;

  // Words most likely to be clicked, best first: content words, longer
  // (rarer) spellings first; one entry per spelling.
  function rankWords(words, { headlines = null, limit = 6 } = {}) {
    const seen = new Set(), out = [];
    for (const word of words) {
      const folded = fold(word.form);
      if (!folded || folded.length < 3 || FREQUENT.has(folded) || seen.has(folded)) continue;
      const pos = headlines?.get?.(word.key)?.pos || '';
      if (FUNCTION_POS.test(pos)) continue;
      seen.add(folded);
      out.push({ ...word, score: folded.length + (CONTENT_POS.test(pos) ? 3 : 0) + (word.repeated ? -2 : 0) });
    }
    return out.sort((a, b) => b.score - a.score || a.index - b.index).slice(0, Math.max(0, limit));
  }

  // UTF-16 offsets of every code point boundary, so codepoint token offsets
  // from the server match the reader's button offsets.
  function utf16Offsets(text) {
    const at = [0];
    let offset = 0;
    for (const char of String(text || '')) { offset += char.length; at.push(offset); }
    return at;
  }
  const capitalised = value => typeof value === 'string' && /^\p{Lu}/u.test(value.normalize('NFD'));
  const firstText = value => typeof value === 'string' ? value.trim()
    : typeof value?.short_text === 'string' ? value.short_text.trim() : typeof value?.text === 'string' ? value.text.trim() : '';

  // POST /api/words/headlines (release O) as provisional headline values keyed
  // `start:end` in UTF-16 units. The contextual reading of the clicked word
  // replaces a provisional value when it arrives.
  function batchHeadlines(payload, text, plain = value => value) {
    const tokens = Array.isArray(payload?.tokens) ? payload.tokens : Array.isArray(payload?.headlines) ? payload.headlines : [];
    const offsets = typeof text === 'string' ? utf16Offsets(text) : null;
    const out = new Map();
    for (const token of tokens) {
      const start = Number(token?.start_utf16 ?? token?.start), end = Number(token?.end_utf16 ?? token?.end);
      if (!Number.isInteger(start) || !Number.isInteger(end) || end <= start) continue;
      const utf16 = token.start_utf16 != null || !offsets ? [start, end] : [offsets[start], offsets[end]];
      if (utf16.some(value => !Number.isInteger(value))) continue;
      const lemma = typeof token.lemma === 'string' ? token.lemma.trim() : '';
      const parses = (Array.isArray(token.parses) ? token.parses : [token.parse_short]).filter(item => typeof item === 'string' && item.trim());
      const printed = typeof token.printed === 'string' ? token.printed : offsets && typeof text === 'string' ? text.slice(utf16[0], utf16[1]) : '';
      const restored = [token.restored, token.reading, token.restored_form].find(item => typeof item === 'string' && item.trim()) || '';
      const alternatives = [
        ...parses.slice(1).map(parse => ({ lemma, parse: plain(parse), short: parse })),
        ...(Array.isArray(token.alternatives) ? token.alternatives : []).filter(alt => alt && typeof alt.lemma === 'string' && alt.lemma.trim())
          .map(alt => {
            const altParses = (Array.isArray(alt.parses) ? alt.parses : [alt.parse_short]).filter(item => typeof item === 'string' && item.trim());
            return { lemma: alt.lemma.trim(), parse: altParses[0] ? plain(altParses[0]) : '', short: altParses[0] || '', gloss: firstText(alt.gloss),
              form: [alt.restored, alt.reading, alt.restored_form, alt.form_restored].find(item => typeof item === 'string' && item.trim()) || '' };
          }),
      ];
      const probability = Number(token.probability);
      const value = { lemma, gloss: firstText(token.gloss), form: printed || restored || '', reading: restored && restored !== printed ? restored : '',
        parse: parses[0] || '', pos: typeof token.pos === 'string' ? token.pos : '', alternatives, ranked: true, tie: token.tie === true,
        properName: capitalised(lemma), provisional: true, source: lemma ? 'Headword from the corpus index; checking it against this passage.' : '',
        ...(token.probability != null && Number.isFinite(probability) ? { probability } : {}) };
      out.set(`${utf16[0]}:${utf16[1]}`, value);
    }
    return out;
  }
  // The batch payload's headline dictionaries (release P, `dictionary: true`):
  // headword -> [one compact entry], the first dictionary with a gloss or senses.
  function batchDictionaries(payload) {
    const out = new Map(), given = payload?.dictionaries;
    if (!given || typeof given !== 'object') return out;
    for (const [lemma, entry] of Object.entries(given)) {
      if (!entry || typeof entry !== 'object' || !lemma) continue;
      out.set(lemma, [{ ...entry, lemma: entry.lemma || lemma, id: entry.id || `batch:${lemma}:${entry.dictionary || ''}` }]);
    }
    return out;
  }

  function abortError() {
    try { return new DOMException('Prefetch cancelled', 'AbortError'); } catch { const error = new Error('Prefetch cancelled'); error.name = 'AbortError'; return error; }
  }

  // One loader per key: a cache hit resolves at once, a second caller joins the
  // request already running, and a high-priority caller starts a queued
  // low-priority request immediately. Low-priority work runs at most
  // `maxLow` at a time; cancel(group) drops it unless a click has claimed it.
  function create({ storage = null, version = '', maxEntries = 160, budget, maxItem, maxLow = 2 } = {}) {
    const memory = createLru(maxEntries);
    const store = createStore(storage, `melos:${VERSION}:${version}:`, { budget, maxItem });
    const inflight = new Map(), queue = [];
    const stats = { requests: 0, hits: 0, joined: 0, cancelled: 0, byKind: {} };
    let running = 0, urgent = 0, limit = maxLow;
    const kindOf = key => String(key).split('|')[0];

    function peek(key) {
      if (memory.has(key)) { stats.hits++; return memory.get(key); }
      const stored = store.get(key);
      if (stored !== undefined) { memory.set(key, stored); stats.hits++; return stored; }
      return undefined;
    }
    function put(key, value, persist = true) {
      if (value === undefined) return;
      memory.set(key, value);
      if (persist) store.set(key, value);
    }
    function finish(task) {
      if (inflight.get(task.key) === task) inflight.delete(task.key);
      if (task.low) { task.low = false; running--; }
      if (task.urgent) { task.urgent = false; urgent--; }
      pump();
    }
    function start(task) {
      task.started = true;
      if (task.priority !== 'high') { task.low = true; running++; } else { task.urgent = true; urgent++; }
      stats.requests++; stats.byKind[kindOf(task.key)] = (stats.byKind[kindOf(task.key)] || 0) + 1;
      Promise.resolve()
        .then(() => task.loader({ signal: task.controller.signal, priority: task.priority }))
        .then(value => { if (value !== undefined && value !== null) put(task.key, value, task.persist); finish(task); task.resolve(value); },
          error => { finish(task); task.reject(error); });
    }
    // Queued prefetch waits while a clicked or hovered word is loading, so on a
    // slow link it never shares the bandwidth with what the reader asked for.
    function pump() {
      while (running < limit && urgent === 0 && queue.length) {
        const task = queue.shift();
        if (!task.controller.signal.aborted) start(task);
      }
    }
    // `claim`: a click owns the request, so cancel() leaves it running; a
    // hover prefetch asks for high priority without claiming it.
    function load(key, loader, { priority = 'high', group = '', persist = true, claim = priority === 'high' } = {}) {
      const hit = peek(key);
      if (hit !== undefined) return Promise.resolve(hit);
      const active = inflight.get(key);
      if (active) {
        stats.joined++;
        if (claim) active.claimed = true;
        if (priority === 'high' && !active.started) { queue.splice(queue.indexOf(active), 1); active.priority = 'high'; start(active); }
        return active.promise;
      }
      if (priority !== 'high' && limit <= 0) return Promise.resolve(undefined);
      const task = { key, loader, priority, group, persist, claimed: claim, started: false, low: false, controller: new AbortController() };
      task.promise = new Promise((resolve, reject) => { task.resolve = resolve; task.reject = reject; });
      inflight.set(key, task);
      if (priority === 'high') start(task); else { queue.push(task); pump(); }
      return task.promise;
    }
    function cancel(group) {
      for (const task of [...inflight.values()]) {
        if (task.claimed || (group && task.group !== group)) continue;
        stats.cancelled++;
        task.controller.abort();
        inflight.delete(task.key);
        if (!task.started) { queue.splice(queue.indexOf(task), 1); task.reject(abortError()); }
      }
    }
    return {
      load, peek, put, cancel, stats,
      pending: key => inflight.has(key),
      setLimit(value) { limit = Math.max(0, value | 0); pump(); },
      get queued() { return queue.length; },
      get running() { return running; },
    };
  }

  // Low-priority scheduling that never competes with rendering.
  function whenIdle(fn, timeout = 2000) {
    if (typeof requestIdleCallback === 'function') return requestIdleCallback(fn, { timeout });
    return setTimeout(fn, 200);
  }

  window.MelosWordPrefetch = Object.freeze({ VERSION, createLru, createStore, networkPolicy, rankWords, fold, utf16Offsets, batchHeadlines, batchDictionaries, create, whenIdle });
})();
