// Citation lookup under the reader's search box (release P `/api/cite`):
// "Il. 1.1", "Hes. Th. 116", "Sappho fr. 31" or a CTS URN offers "Go to Iliad
// 1.1" first, and Enter opens that passage. Nothing is guessed here: the
// suggestion is the service's own parse and its first (edited-text) result.
(() => {
  'use strict';

  // A citation has letters, then a space or full stop, then a number (a word
  // with digits such as "a123b" is not one), optionally a range and an edition
  // abbreviation ("31 V", "168A LP"); or it is a CTS URN.
  const CITATION = /^(?:urn:cts:[a-z]+Lit:\S+|\p{L}[\p{L}\p{M}.'’ -]{0,60}?[ .]\s*(?:fr\.\s*)?\d{1,5}[a-z]?(?:[.,:]\d{1,5}[a-z]?){0,3}(?:\s*[-–]\s*\d{1,5}[a-z]?(?:[.,:]\d{1,5})*)?(?:\s+[\p{L}.&-]{1,14}){0,2})$/iu;
  function looksLikeCitation(query) {
    const text = String(query || '').normalize('NFC').trim().replace(/\s+/g, ' ');
    return text.length >= 3 && text.length <= 120 && CITATION.test(text);
  }
  // [[1, ""], [1, ""]] -> "1.1"; [[130, "b"]] -> "130b".
  function locusText(locus) {
    if (!Array.isArray(locus)) return locus == null ? '' : String(locus);
    return locus.map(part => Array.isArray(part) ? `${part[0] ?? ''}${part[1] || ''}` : String(part ?? '')).filter(Boolean).join('.');
  }
  const cap = value => String(value || '').replace(/^\p{Ll}/u, c => c.toUpperCase());
  // The place in words: "Iliad 1.1", "Sappho fr. 31", "Iliad 1.1–1.5".
  function citationLabel(data) {
    const parsed = data?.parsed, first = Array.isArray(data?.results) ? data.results[0] : null;
    if (!parsed) return '';
    const start = locusText(parsed.locus), end = locusText(parsed.locus_end);
    const span = end && end !== start ? `${start}–${end}` : start;
    if (parsed.kind === 'fragment') return `${cap(parsed.author || first?.author || '')} fr. ${span}${parsed.scheme ? ` ${parsed.scheme}` : ''}`.trim();
    if (parsed.kind === 'urn' && !parsed.work && first) return [first.display_work || first.work, first.citation].filter(Boolean).join(' ');
    return [parsed.work || parsed.author || first?.display_work || first?.work || '', span].filter(Boolean).join(' ');
  }
  // One result in words: "Homer · Iliad 1.1–1.20".
  function resultLabel(result) {
    const work = result?.display_work || result?.work || '';
    return [cap(result?.display_author || result?.author || ''), [work, result?.citation && result.citation !== work ? result.citation : ''].filter(Boolean).join(' ')]
      .filter(Boolean).join(' · ');
  }
  function preview(result) {
    const text = String(result?.text_preview || result?.text || '').replace(/\s+/g, ' ').trim();
    return text.length > 90 ? `${text.slice(0, 90).replace(/\s+\S*$/u, '')} …` : text;
  }

  // The suggestion list under the search box. `lookup(q)` returns the
  // `/api/cite` payload; `go(id)` opens a passage; `search(q)` runs the
  // ordinary search.
  function mount({ form, input, lookup, go, search, delay = 250 }) {
    if (!form || !input || typeof lookup !== 'function') return null;
    const box = document.createElement('div');
    box.className = 'cite-suggest'; box.id = 'cite-suggest'; box.hidden = true;
    box.setAttribute('role', 'listbox'); box.setAttribute('aria-label', 'Go to a cited passage');
    form.after(box);
    input.setAttribute('aria-controls', box.id);
    let timer = 0, sequence = 0, pending = { query: '', promise: null };
    const text = () => input.value.normalize('NFC').trim().replace(/\s+/g, ' ');
    const resolve = query => {
      if (pending.query === query && pending.promise) return pending.promise;
      pending = { query, promise: Promise.resolve(lookup(query)).then(data => data?.parsed && Array.isArray(data.results) && data.results.length ? data : null, () => null) };
      return pending.promise;
    };
    const hide = () => { box.hidden = true; box.replaceChildren(); input.setAttribute('aria-expanded', 'false'); };
    const item = (className, label, sub, onChoose) => {
      const button = document.createElement('button');
      button.type = 'button'; button.className = `cite-option ${className}`; button.setAttribute('role', 'option');
      const main = document.createElement('span'); main.className = 'cite-option-label'; main.textContent = label; button.append(main);
      if (sub) { const small = document.createElement('span'); small.className = 'cite-option-sub'; small.textContent = sub; small.lang = 'grc'; button.append(small); }
      button.addEventListener('click', () => { hide(); onChoose(); });
      button.addEventListener('keydown', event => {
        const options = [...box.querySelectorAll('.cite-option')], at = options.indexOf(button);
        if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
          event.preventDefault();
          const next = at + (event.key === 'ArrowDown' ? 1 : -1);
          if (next < 0) input.focus(); else options[Math.min(next, options.length - 1)].focus();
        } else if (event.key === 'Escape') { hide(); input.focus(); }
      });
      return button;
    };
    const show = (query, data) => {
      box.replaceChildren();
      if (!data) { hide(); return; }
      const [first, ...rest] = data.results;
      const go1 = item('cite-go', `Go to ${citationLabel(data) || resultLabel(first)}`, [resultLabel(first), preview(first)].filter(Boolean).join(' — '), () => go(first.id, data));
      go1.setAttribute('aria-selected', 'true');
      box.append(go1);
      for (const other of rest.slice(0, 2)) box.append(item('cite-edition', `Another edition: ${resultLabel(other)}`, preview(other), () => go(other.id, data)));
      box.append(item('cite-search', `Search the texts for “${query}”`, '', () => search(query)));
      box.hidden = false; input.setAttribute('aria-expanded', 'true');
    };
    input.addEventListener('input', () => {
      clearTimeout(timer);
      const query = text(), mine = ++sequence;
      if (!looksLikeCitation(query)) { hide(); return; }
      timer = setTimeout(() => resolve(query).then(data => { if (mine === sequence && text() === query) show(query, data); }), delay);
    });
    input.addEventListener('keydown', event => {
      if (event.key === 'ArrowDown' && !box.hidden) { event.preventDefault(); box.querySelector('.cite-option')?.focus(); }
      else if (event.key === 'Escape' && !box.hidden) { event.preventDefault(); hide(); }
    });
    document.addEventListener('click', event => { if (!form.contains(event.target) && !box.contains(event.target)) hide(); });
    return {
      looksLikeCitation, hide,
      // Enter: a citation the service resolves opens its passage (true);
      // anything else is left to the ordinary search (false).
      async jump(query) {
        const q = String(query || '').normalize('NFC').trim().replace(/\s+/g, ' ');
        if (!looksLikeCitation(q)) return false;
        ++sequence; clearTimeout(timer);
        const wait = document.createElement('p');
        wait.className = 'cite-wait melos-loading'; wait.textContent = `Finding ${q}…`;
        box.replaceChildren(wait); box.hidden = false;
        const data = await resolve(q);
        hide();
        if (!data) return false;
        go(data.results[0].id, data);
        return true;
      },
    };
  }

  window.MelosCitation = Object.freeze({ looksLikeCitation, locusText, citationLabel, resultLabel, preview, mount });
})();
