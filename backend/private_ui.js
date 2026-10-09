// Owner-only private panels (release T). Served by the API at /api/private/ui.js to a signed-in
// owner only; it is not part of the static site. Every panel says "Private — owner only" and
// names its source and page. Text is inserted with textContent only.
(() => {
  'use strict';
  if (window.melosPrivateUi) return;
  window.melosPrivateUi = true;
  const api = path => (window.melosApiFetch ? window.melosApiFetch(path, { credentials: 'same-origin' })
    : fetch(path, { credentials: 'same-origin' }));

  const style = document.createElement('style');
  style.textContent = `
    .melos-private { margin: 1.5rem 0; padding: 0.9rem 1rem; border: 1px dashed #b5651d; border-radius: 6px;
      background: rgba(181, 101, 29, 0.06); font-size: 0.95rem; }
    .melos-private h3 { margin: 0 0 0.5rem; font-size: 0.85rem; letter-spacing: 0.06em; text-transform: uppercase; color: #b5651d; }
    .melos-private article { margin: 0.7rem 0; }
    .melos-private .src { font-size: 0.82rem; opacity: 0.8; margin: 0 0 0.2rem; }
    .melos-private .txt { white-space: pre-wrap; max-height: 22rem; overflow: auto; margin: 0; }
    .melos-private details summary { cursor: pointer; }
    .melos-private .empty { opacity: 0.7; margin: 0; }`;
  document.head.append(style);

  function panel(id, heading) {
    let box = document.getElementById(id);
    if (!box) {
      box = document.createElement('section');
      box.id = id;
      box.className = 'melos-private';
      box.setAttribute('aria-label', 'Private — owner only');
    }
    box.replaceChildren();
    const h = document.createElement('h3');
    h.textContent = `Private — owner only · ${heading}`;
    box.append(h);
    return box;
  }

  function render(box, payload, emptyText) {
    const items = (payload && payload.results) || [];
    if (!items.length) {
      const p = document.createElement('p');
      p.className = 'empty';
      p.textContent = emptyText;
      box.append(p);
      return;
    }
    for (const item of items) {
      const article = document.createElement('article');
      const details = document.createElement('details');
      const summary = document.createElement('summary');
      summary.textContent = `${item.label} — ${item.source} (${item.kind}${item.method === 'ocr' ? ', OCR' : ''})`;
      const src = document.createElement('p');
      src.className = 'src';
      src.textContent = [item.author, item.title, item.year].filter(Boolean).join(', ') + ` · page ${item.page}` +
        (String(item.page) !== String(item.pdf_page) ? ` (file page ${item.pdf_page})` : '');
      const txt = document.createElement('p');
      txt.className = 'txt';
      txt.textContent = item.text;
      details.append(summary, src, txt);
      article.append(details);
      box.append(article);
    }
  }

  async function show(id, anchor, where, path, heading, emptyText) {
    if (!anchor) return;
    const box = panel(id, heading);
    if (where === 'after') anchor.after(box); else anchor.prepend(box);
    try {
      const response = await api(path);
      if (!response.ok) { box.remove(); return; }
      render(box, await response.json(), emptyText);
    } catch { box.remove(); }
  }

  let last = '';
  function refresh() {
    const url = new URL(location.href);
    const id = url.searchParams.get('id') || '';
    const q = url.searchParams.get('q') || '';
    const lemma = url.searchParams.get('lemma') || '';
    const key = [location.pathname, id, q, lemma].join('\u0001');
    if (key === last) return;
    last = key;
    const passage = document.getElementById('related-material') || document.getElementById('passage-text');
    if (id && passage) show('melos-private-passage', passage, 'after', `/api/private/passage?id=${encodeURIComponent(id)}`,
      'your library on this passage', 'No private pages are linked to this passage.');
    const results = document.getElementById('search-results');
    if (q && results) show('melos-private-search', results, 'prepend', `/api/private/search?q=${encodeURIComponent(q)}`,
      'your library for this search', 'No private pages match this search.');
    const entry = document.getElementById('entry');
    if (lemma && entry) show('melos-private-lemma', entry, 'after', `/api/private/lemma?lemma=${encodeURIComponent(lemma)}`,
      'your library on this headword', 'No private pages name this headword.');
  }
  for (const name of ['pushState', 'replaceState']) {
    const original = history[name];
    history[name] = function (...args) { const out = original.apply(this, args); setTimeout(refresh, 50); return out; };
  }
  addEventListener('popstate', () => setTimeout(refresh, 50));
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', refresh, { once: true });
  else refresh();
})();
