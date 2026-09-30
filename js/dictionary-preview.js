/* Source-backed display projection only. No generated senses or parsing. */
(() => {
  'use strict';
  const MAX_ENTRIES = 6;
  const MAX_MEANINGS = 3;
  const MAX_ANALYSES = 4;
  const MAX_EXCERPT = 200;
  const list = (value) => Array.isArray(value) ? value : [];
  const text = (value) => typeof value === 'string' ? value.trim() : '';
  const identity = (value) => text(value).normalize('NFC'); // Never fold distinct accented lemmas.
  const rejected = (row) => !row || row.quarantined === true || row.source_consistent === false ||
    row.source_inconsistent === true || row.assertion_type === 'model_inference' ||
    [row.status, row.quality, row.link_status, row.lemma_link_status].some(value =>
      /(?:quarantin|inconsisten|rejected|needs_review|machine_proposed)/i.test(text(value)));
  function sourceUrl(value) {
    try {
      const url = new URL(text(value));
      return ['https:', 'http:'].includes(url.protocol) && !url.username && !url.password ? url.href : '';
    } catch { return ''; }
  }
  function greekFormKey(value) {
    // Fold accents, breathing/quantity marks, case and final sigma only.
    // In particular, a suffix's hyphen and an elision mark are significant.
    return text(value).normalize('NFD').replace(/\p{M}/gu, '').toLowerCase()
      .replace(/ς/g, 'σ').replace(/[’ʼ᾽᾿]/g, "'").normalize('NFC');
  }
  function eligibleWikiMatch(match, row, query) {
    const matched = match?.kind === 'headword' ? text(match.word) || text(row.headword) :
      match?.kind === 'listed_form' ? text(match.form?.form) : '';
    // No local transliteration guesses: /api/word remains responsible for
    // transliterated lookup. Wiki previews require comparable Greek forms.
    return /\p{Script=Greek}/u.test(query) && !!matched && greekFormKey(matched) === greekFormKey(query);
  }
  function excerpt(value) {
    const original = text(value);
    if (!original) return null;
    if (original.length <= MAX_EXCERPT) return { text: original, truncated: false };
    let end = MAX_EXCERPT;
    // A literal prefix with explicit ellipsis, not a rewritten definition.
    const space = original.slice(0, end).search(/\s+\S*$/u);
    if (space > MAX_EXCERPT / 2) end = space;
    if (/[\uD800-\uDBFF]/u.test(original[end - 1])) end--;
    return { text: original.slice(0, end).trimEnd() + '…', truncated: true };
  }
  function isCandidateQuery(query) {
    const value = text(query);
    // Phrases/descriptions need an explicitly indexed multiword entry; do not
    // infer one by decomposing a query. Beta Code punctuation is accepted.
    return value.length > 0 && value.length <= 80 && /\p{L}/u.test(value) &&
      !/\s/u.test(value) && /^[\p{L}\p{M}\d*()\/\\=+|'’ʼ᾽᾿.,-]+$/u.test(value);
  }
  function entryId(entry) {
    return text(entry.id) || `${text(entry.source_url)}#${text(entry.entry_id)}`;
  }
  function exactCandidate(candidate) {
    return !rejected(candidate) && candidate.edit_distance === 0 &&
      ['indexed_form', 'lexicon_headword'].includes(candidate.match_kind) && !!identity(candidate.lemma);
  }
  function readableAnalysis(candidate) {
    const description = text(candidate.analysis_text);
    if (description) return description;
    const raw = text(candidate.analysis);
    // Compact source postags stay in the full inspector. A missing decoder
    // does not turn an opaque code into another human-readable parse choice.
    if (/\bpostag\b|\bpos[- ]?tag\b/i.test(text(candidate.analysis_format)) ||
        /^(?:[a-z-][123-][spd-]|[a-z][0-9])[a-z0-9-]{4,}$/i.test(raw)) return '';
    return raw;
  }
  function meaning(value, source, url, extra = {}) {
    const shortened = excerpt(value);
    return shortened && url ? { ...shortened, source, source_url: url, ...extra } : null;
  }
  function unique(rows, key) {
    const seen = new Set();
    return rows.filter(row => { const value = key(row); if (seen.has(value)) return false; seen.add(value); return true; });
  }
  function buildPreview(data, wiktionary = null) {
    const query = text(data?.form) || text(wiktionary?.query);
    const empty = { query, entries: [], ambiguous: false, truncated: false, label: 'Dictionary preview' };
    if (!data || data.ready === false) return empty;
    const candidates = list(data.candidates).filter(exactCandidate);
    const dictionary = list(data.lexicon_entries).filter(row => !rejected(row) && identity(row.lemma));
    const entries = [];
    for (const entry of dictionary) {
      const id = entryId(entry), lemma = text(entry.lemma), source = text(entry.source);
      const url = sourceUrl(entry.source_url);
      const matches = candidates.filter(candidate => identity(candidate.lemma) === identity(lemma) &&
        (list(candidate.lexicon_entry_ids).includes(id) || candidate.gloss_entry_id === id));
      if (!url || !matches.length) continue;
      // A prose LSJ/Autenrieth gloss is one excerpt. Never split commas or
      // semicolons into supposed senses that the source did not distinguish.
      const meanings = [meaning(entry.gloss, source, url)].filter(Boolean);
      if (!meanings.length) continue;
      const unresolvedEntry = matches.some(candidate => {
        const alternatives = dictionary.filter(other => identity(other.lemma) === identity(lemma) &&
          text(other.source) === source && list(candidate.lexicon_entry_ids).includes(entryId(other)));
        return alternatives.length > 1;
      });
      const analyses = unresolvedEntry ? [] : unique(matches.flatMap(candidate => {
        const parse = readableAnalysis(candidate);
        const parseUrl = sourceUrl(candidate.source_url);
        return parse && parseUrl ? [{ text: parse, matched_form: text(candidate.matched_form),
          source: text(candidate.source), source_url: parseUrl,
          label: 'Indexed form analysis (not a resolved passage parse)' }] : [];
      }), row => `${row.text}\0${row.source_url}\0${row.matched_form}`);
      const ambiguous = unresolvedEntry || matches.some(candidate =>
        candidate.lemma_link_status === 'ambiguous_source_lemmas') ||
        new Set(analyses.map(row => row.text)).size > 1;
      entries.push({ id, lemma, source, source_url: url,
        entry_url: sourceUrl(entry.entry_url) || url, meanings,
        analyses: analyses.slice(0, MAX_ANALYSES), ambiguous,
        label: unresolvedEntry ? 'Dictionary entry alternative; form-to-entry link unresolved' :
          ambiguous ? 'Dictionary entry; parsing alternatives remain' : 'Dictionary entry excerpt',
        truncated: meanings.some(row => row.truncated) || analyses.length > MAX_ANALYSES });
    }
    if (wiktionary?.ready === true && identity(wiktionary.query) === identity(query) && !rejected(wiktionary)) {
      for (const row of list(wiktionary.results)) {
        if (rejected(row) || !text(row.id) || !identity(row.headword)) continue;
        const url = sourceUrl(row.source_url), source = text(row.source) || 'Wiktionary / Kaikki';
        const matches = list(row.matches).filter(match => eligibleWikiMatch(match, row, query));
        if (!url || !matches.length) continue;
        const meanings = [];
        for (const sense of list(row.senses)) {
          if (rejected(sense)) continue;
          for (const gloss of list(sense.glosses)) {
            const item = meaning(gloss, source, url, { sense_index: sense.sense_index });
            if (item) meanings.push(item);
          }
        }
        const distinctMeanings = unique(meanings, item => `${item.sense_index}\0${item.text}`);
        if (!distinctMeanings.length) continue;
        const analyses = unique(matches.flatMap(match => {
          if (match.kind !== 'listed_form' || rejected(match.form)) return [];
          const metadataTags = new Set(['canonical', 'alternative', 'romanization', 'transliteration']);
          const tags = list(match.form.tags).filter(tag => typeof tag === 'string' && !metadataTags.has(tag.toLowerCase()));
          return tags.length ? [{ text: tags.join(', '), matched_form: text(match.form.form),
            source, source_url: url, label: 'Dictionary-listed form tags (not a corpus attestation)' }] : [];
        }), item => `${item.text}\0${item.matched_form}`);
        entries.push({ id: row.id, lemma: text(row.headword), source, source_url: url,
          entry_url: sourceUrl(row.live_entry_url) || url, meanings: distinctMeanings.slice(0, MAX_MEANINGS),
          analyses: analyses.slice(0, MAX_ANALYSES), ambiguous: new Set(analyses.map(item => item.text)).size > 1,
          label: 'Wiktionary snapshot excerpts; live entry may differ',
          truncated: distinctMeanings.length > MAX_MEANINGS || analyses.length > MAX_ANALYSES ||
            distinctMeanings.some(item => item.truncated) || Number(row.total_senses) > list(row.senses).length });
      }
    }
    const distinct = unique(entries, entry => `${entry.source}\0${entry.id}`);
    const sourceLemmas = new Map();
    for (const entry of distinct) {
      const key = `${entry.source}\0${identity(entry.lemma)}`;
      sourceLemmas.set(key, (sourceLemmas.get(key) || 0) + 1);
    }
    const ambiguous = new Set(distinct.map(entry => identity(entry.lemma))).size > 1 ||
      [...sourceLemmas.values()].some(count => count > 1) || distinct.some(entry => entry.ambiguous);
    return { query, entries: distinct.slice(0, MAX_ENTRIES), ambiguous,
      truncated: distinct.length > MAX_ENTRIES || distinct.some(entry => entry.truncated),
      label: ambiguous ? 'Dictionary alternatives — no contextual sense selected' : 'Dictionary preview — source excerpts' };
  }
  window.MelosDictionaryPreview = Object.freeze({ isCandidateQuery, buildPreview });
})();
