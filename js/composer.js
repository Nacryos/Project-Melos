/* Composer canvas (composer.html, release V). One textarea (TypeGreek input, js/typegreek.js) over a rendered copy
   of the same text that carries the scansion: syllables coloured by longness (css/scansion.css tokens), bold bars
   between syllables, an optional % view, metre violations underlined. Hover a syllable for its word's analysis
   (/api/analyze-text, per line, cached); click it for the reason. "Suggest next line" asks /api/compose/suggest
   and shows the chosen candidate as ghost text: Tab or a tap on it accepts, Esc dismisses.
   The composer always shows the scanner's own probabilities: no metre ever adjusts them here. */
(() => {
  'use strict';
  const $ = id => document.getElementById(id);
  const input = $('canvas-input'), backdrop = $('backdrop'), canvas = $('canvas'), tip = $('tip');
  const POET_DIALECT = { Sappho: 'aeolic', Alcaeus: 'aeolic', Alcman: 'doric', Pindar: 'doric', Bacchylides: 'doric', Simonides: 'doric', Ibycus: 'doric' };
  const ANALYSIS_DIALECT = { aeolic: 'lesbian', doric: 'doric', ionic: 'ionic', attic: 'attic' };
  const METRES = ['hexameter', 'pentameter', 'elegiac', 'iambic_trimeter', 'trochaic_tetrameter', 'sapphic', 'sapphic_hendecasyllable',
    'adonean', 'alcaic', 'glyconic', 'pherecratean', 'hipponactean', 'telesillean', 'reizianum', 'aristophanean', 'lesser_asclepiad', 'greater_asclepiad'];
  const PREFS = 'melos-composer-prefs';
  const api = (path, body) => (window.melosApiFetch || fetch)(path, body ? { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) } : undefined);
  const esc = s => String(s).replace(/[&<>"]/g, ch => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[ch]));

  const state = { scan: null, scanSeq: 0, analysis: new Map(), pending: new Set(), suggestions: [], ghost: -1, selected: null };
  let scanTimer = 0, analysisTimer = 0;

  for (const m of METRES) $('metre').append(new Option(m.replace(/_/g, ' '), m));
  try {
    const saved = JSON.parse(localStorage.getItem(PREFS) || '{}');
    for (const id of ['author', 'metre', 'dialect', 'theme']) if (typeof saved[id] === 'string') $(id).value = saved[id];
    for (const id of ['bars', 'pct']) if (typeof saved[id] === 'boolean') $(id).checked = saved[id];
    if (typeof saved.text === 'string') input.value = saved.text;
  } catch (e) { /* storage blocked */ }
  function savePrefs() {
    try {
      localStorage.setItem(PREFS, JSON.stringify({ author: $('author').value, metre: $('metre').value, dialect: $('dialect').value,
        theme: $('theme').value, bars: $('bars').checked, pct: $('pct').checked, text: input.value }));
      if ($('theme').value) localStorage.setItem('melos-composer-theme', $('theme').value); else localStorage.removeItem('melos-composer-theme');
    } catch (e) { /* storage blocked */ }
  }
  const scanDialect = () => $('dialect').value || POET_DIALECT[$('author').value] || 'none';

  const ime = window.TypeGreek.attach(input, {
    toggle: $('mode'), storageKey: 'melos-typegreek-mode',
    onChange: () => changed(),
  });
  input.addEventListener('compositionupdate', e => { $('status').querySelector('.preview')?.remove(); const p = document.createElement('span'); p.className = 'preview'; p.lang = 'grc'; p.textContent = ime.mode === 'greek' ? window.TypeGreek.convert(e.data || '') : ''; if (p.textContent) $('status').prepend(p); });
  input.addEventListener('compositionend', () => $('status').querySelector('.preview')?.remove());

  function changed() {
    render();
    savePrefs();
    clearTimeout(scanTimer); scanTimer = setTimeout(scan, 200);
    clearTimeout(analysisTimer); analysisTimer = setTimeout(analyse, 900);
  }

  // ---- scansion -------------------------------------------------------------------------------------------
  async function scan() {
    const text = input.value, seq = ++state.scanSeq;
    if (!text.trim()) { state.scan = null; render(); return; }
    const metre = $('metre').value || null;
    try {
      const r = await api('/api/scan', { text, lexicon: true, dialect: scanDialect(), metre });
      const body = await r.json();
      if (seq !== state.scanSeq) return;
      if (!r.ok) throw new Error(r.status === 429 ? 'Too many requests; scansion paused for a moment.' : 'Scansion is unavailable.');
      state.scan = { text, res: body };
      status(`${body.units.length} syllables · ${body.ms} ms${body.lexicon ? '' : ' · without the vowel-length lexicon'}`);
    } catch (e) {
      if (seq === state.scanSeq) status(e.message || 'Scansion is unavailable.');
    }
    render();
  }
  function rgb(p) {
    const css = getComputedStyle(document.documentElement);
    const c = n => css.getPropertyValue(n).split(',').map(Number);
    const [a, b, t] = p < 0.5 ? [c('--scan-short'), c('--scan-mid'), p / 0.5] : [c('--scan-mid'), c('--scan-long'), (p - 0.5) / 0.5];
    return a.map((x, i) => Math.round(x + (b[i] - x) * t)).join(',');
  }
  // Units of the last scan, re-based per line text, so unchanged lines keep their colours while one is edited.
  function unitsByLine() {
    const out = new Map();
    if (!state.scan) return out;
    const { text, res } = state.scan;
    const starts = [0];
    for (let i = 0; i < text.length; i++) if (text[i] === '\n') starts.push(i + 1);
    const lines = text.split('\n');
    const bad = new Set();
    (res.fit || []).forEach((f, k) => (f.violations || []).forEach(v => bad.add(v.syllable)));
    for (const u of res.units) {
      const lineText = lines[u.line];
      if (!out.has(lineText)) out.set(lineText, []);
      const list = out.get(lineText);
      if (list.owner === undefined) list.owner = u.line;
      if (list.owner !== u.line) continue;
      list.push({ ...u, rs: u.start - starts[u.line], re: u.end - starts[u.line], ns: u.nucleus[0] - starts[u.line], violation: bad.has(u.i) });
    }
    return out;
  }
  function render() {
    const text = input.value;
    const byLine = unitsByLine();
    let html = '';
    text.split('\n').forEach((line, li) => {
      const units = byLine.get(line) || [];
      let pos = 0, first = true;
      for (const u of units) {
        if (u.rs < pos || u.re > line.length) continue;
        if (u.rs > pos) html += esc(line.slice(pos, u.rs));
        const p = u.p_long, c = rgb(p);
        html += `<span class="u${first ? '' : ' b'}${u.violation ? ' violation' : ''}${state.selected === `${li}:${u.rs}` ? ' sel' : ''}" data-line="${li}" data-rs="${u.rs}" data-ns="${u.ns}" data-i="${u.i}" style="color:rgb(${c});background:rgba(${c},.06)">${esc(line.slice(u.rs, u.re))}<span class="pct">${Math.round(p * 100)}%</span></span>`;
        pos = u.re; first = false;
      }
      html += esc(line.slice(pos));
      html += '\n';
    });
    const ghost = state.suggestions[state.ghost];
    if (ghost) html += `${text && !text.endsWith('\n') ? '' : ''}<span class="ghost" lang="grc">${esc(ghost.greek)}</span><span class="ghost-hint">Tab or tap to accept · Esc to dismiss</span>\n`;
    backdrop.innerHTML = html.replace(/\n$/, '\n​');
    canvas.classList.toggle('bars', $('bars').checked);
    canvas.classList.toggle('pct', $('pct').checked);
    renderLines();
  }
  function renderLines() {
    const list = $('lines');
    list.replaceChildren();
    if (!state.scan || state.scan.text !== input.value) return;
    const res = state.scan.res;
    res.lines.forEach((line, k) => {
      const li = document.createElement('li');
      const f = res.fit?.[k];
      li.innerHTML = `<span class="n">${line.line + 1}</span><span class="pattern">${esc(line.pattern)}</span>` + (f
        ? (f.ok ? `<span class="ok">fits ${esc(f.metre.replace(/_/g, ' '))}</span>`
          : `<span class="bad">${esc(f.metre.replace(/_/g, ' '))}: ${esc(f.message)}${(f.violations || []).map(v => ` · ${esc(v.text)} needs ${esc(v.needs)}`).join('')}</span>`) : '');
      list.append(li);
    });
    if (res.auto?.length) {
      const li = document.createElement('li');
      li.textContent = 'Detected: ' + res.auto.slice(0, 3).map(a => `${a.metre.replace(/_/g, ' ')} (${a.lines_fitting}/${a.lines} lines)`).join(' · ');
      list.append(li);
    }
  }
  function status(message) {
    const s = $('status');
    const preview = s.querySelector('.preview');
    s.textContent = message;
    if (preview) s.prepend(preview);
  }

  // ---- word analysis (per line, cached) ------------------------------------------------------------------
  const analysisKey = line => `${$('author').value}|${$('dialect').value}|${line}`;
  async function analyse() {
    const lines = [...new Set(input.value.split('\n').map(l => l.trim() ? l : null).filter(Boolean))];
    for (const line of lines) {
      const key = analysisKey(line);
      if (state.analysis.has(key) || state.pending.has(key)) continue;
      if (state.pending.size >= 2) { clearTimeout(analysisTimer); analysisTimer = setTimeout(analyse, 600); return; }
      state.pending.add(key);
      const body = { text: line, author: $('author').value || undefined };
      const d = ANALYSIS_DIALECT[$('dialect').value];
      if (d) body.dialect = d;
      api('/api/analyze-text', body).then(r => (r.ok ? r.json() : null)).then(res => {
        if (res) state.analysis.set(key, res.words || []);
      }).catch(() => {}).finally(() => { state.pending.delete(key); if (state.analysis.size > 200) state.analysis.delete(state.analysis.keys().next().value); });
    }
  }
  function wordAt(line, offset) {
    const words = state.analysis.get(analysisKey(input.value.split('\n')[line] || ''));
    return words?.find(w => w.start <= offset && offset < w.end) || null;
  }
  const wordHtml = w => w ? `<strong lang="grc">${esc(w.text)}</strong> — ${w.lemma ? `<span lang="grc">${esc(w.lemma)}</span>` : 'no headword'}${w.gloss ? ` “${esc(w.gloss)}”` : ''}${w.parse ? `<br>${esc(w.parse)}` : ''}` : '';

  // ---- pointer: hover → word, click → syllable reason, tap on ghost → accept ------------------------------
  const under = e => document.elementsFromPoint(e.clientX, e.clientY);
  input.addEventListener('pointermove', e => {
    if (e.pointerType === 'touch') return;
    const u = under(e).find(el => el.classList?.contains('u'));
    const w = u && wordAt(+u.dataset.line, +u.dataset.ns);
    if (!w) { tip.hidden = true; return; }
    tip.innerHTML = wordHtml(w);
    tip.hidden = false;
    tip.style.left = Math.min(innerWidth - tip.offsetWidth - 16, e.clientX + 12) + 'px';
    tip.style.top = Math.min(innerHeight - tip.offsetHeight - 8, e.clientY + 18) + 'px';
  });
  input.addEventListener('pointerleave', () => { tip.hidden = true; });
  input.addEventListener('pointerup', e => {
    const hits = under(e);
    if (hits.some(el => el.classList?.contains('ghost'))) { accept(); return; }
    const u = hits.find(el => el.classList?.contains('u'));
    if (u) inspect(u);
  });
  function inspect(el) {
    const unit = state.scan?.res.units.find(x => x.i === +el.dataset.i);
    if (!unit) return;
    state.selected = `${el.dataset.line}:${el.dataset.rs}`;
    const w = wordAt(+el.dataset.line, +el.dataset.ns);
    const reasons = (unit.reasons || []).map(r => `<li>${esc(r.text)}${r.detail ? ` (${esc(r.detail)})` : ''} <span class="rid">${esc(r.id)}</span></li>`).join('');
    const flags = (unit.flags || []).map(f => `<li>${esc(f.text)}${f.p !== undefined ? ` (${Math.round(f.p * 100)}%)` : ''}</li>`).join('');
    $('inspector').innerHTML = `<h3 lang="grc">${esc(unit.text.trim())}</h3><div><span class="big">${Math.round(unit.p_long * 100)}%</span> long</div>
      <ul>${reasons}</ul>${flags ? `<div>Possible:</div><ul>${flags}</ul>` : ''}${w ? `<div class="word">${wordHtml(w)}</div>` : ''}`;
    $('inspector').hidden = false;
    render();
  }

  // ---- suggestions ----------------------------------------------------------------------------------------
  async function suggest() {
    const text = input.value;
    if (!text.trim()) { status('Type a line first.'); return; }
    const button = $('suggest');
    button.disabled = true; button.textContent = 'Looking…';
    try {
      const body = { text, author: $('author').value || null, metre: $('metre').value || 'auto', k: 3 };
      if ($('dialect').value) body.dialect = $('dialect').value;
      const r = await api('/api/compose/suggest', body);
      const res = await r.json();
      if (!r.ok) throw new Error(r.status === 429 ? 'Too many suggestion requests; wait a minute.' : (res.detail?.message || 'Suggestions are unavailable.'));
      state.suggestions = res.candidates || [];
      state.ghost = state.suggestions.length ? 0 : -1;
      const llm = res.generator?.llm;
      const note = $('suggest-note');
      note.hidden = false;
      note.textContent = (llm && !llm.configured ? 'Writing new lines is not configured on the server (no text-writing model). These are lines quoted from the poets, nearest to your draft, each checked and cited. ' : '')
        + (res.target?.metre ? `Target: line ${res.target.line} of ${res.target.metre.replace(/_/g, ' ')}${res.target.template ? ` (${res.target.template})` : ''}.` : 'No metre chosen or detected.')
        + (state.suggestions.length ? '' : ' Nothing suitable was found.');
      renderTray(); render();
    } catch (e) {
      $('suggest-note').hidden = false; $('suggest-note').textContent = e.message;
    } finally {
      button.disabled = false; button.textContent = 'Suggest next line';
    }
  }
  function renderTray() {
    const tray = $('tray');
    tray.replaceChildren();
    state.suggestions.forEach((c, k) => {
      const card = document.createElement('div');
      card.className = 'card' + (k === state.ghost ? ' active' : '');
      card.innerHTML = `<div class="greek" lang="grc">${esc(c.greek)}</div>
        <div class="source"><span class="verdict ${esc(c.verdict)}">${esc(c.verdict)}</span> ${esc(c.source.author || '')}, ${esc(c.source.citation || '')} · ${esc(c.basis)}${c.pattern ? ` · <span class="pattern">${esc(c.pattern)}</span>` : ''}</div>
        <ul class="checks">${c.checks.map(x => `<li><span class="id">${esc(x.id)}</span><span class="verdict ${esc(x.verdict)}">${esc(x.verdict)}</span><span>${esc(x.message)}</span></li>`).join('')}</ul>
        <div class="actions"><button type="button" class="primary" data-act="accept">Accept</button><button type="button" class="quiet" data-act="show">Show on canvas</button><button type="button" class="quiet" data-act="reject">Reject</button></div>`;
      card.addEventListener('click', e => {
        const act = e.target.closest('button')?.dataset.act;
        if (act === 'accept') { state.ghost = k; accept(); }
        else if (act === 'show') { state.ghost = k; renderTray(); render(); }
        else if (act === 'reject') { state.suggestions.splice(k, 1); state.ghost = state.suggestions.length ? Math.min(state.ghost, state.suggestions.length - 1) : -1; renderTray(); render(); }
      });
      tray.append(card);
    });
  }
  function accept() {
    const c = state.suggestions[state.ghost];
    if (!c) return;
    const base = input.value.replace(/\s+$/, '');
    input.value = (base ? base + '\n' : '') + c.greek;
    ime.sync();
    state.suggestions = []; state.ghost = -1;
    renderTray();
    input.focus();
    input.setSelectionRange(input.value.length, input.value.length);   // edit it from here
    changed();
  }
  input.addEventListener('keydown', e => {
    if (state.ghost < 0) return;
    if (e.key === 'Tab' && !e.shiftKey) { e.preventDefault(); accept(); }
    else if (e.key === 'Escape') { state.ghost = -1; renderTray(); render(); }
  });
  $('suggest').addEventListener('click', suggest);

  for (const id of ['author', 'dialect', 'metre']) $(id).addEventListener('change', () => { state.scan = null; changed(); });
  for (const id of ['bars', 'pct']) $(id).addEventListener('change', () => { savePrefs(); render(); });
  $('theme').addEventListener('change', () => {
    const t = $('theme').value;
    if (t) document.documentElement.dataset.theme = t; else delete document.documentElement.dataset.theme;
    savePrefs(); render();
  });
  matchMedia('(prefers-color-scheme: dark)').addEventListener?.('change', render);
  addEventListener('resize', render);
  changed();
})();
