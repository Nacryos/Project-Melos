/* Composer (composer.html, release W: W2 + W3; docs/composer/ui.md, PRD docs/prd/composer-agent.md §3-4).
   A board of TypeGreek line editors over the scansion backdrop of release V (syllables coloured by longness,
   bars, %, metre violations), saved on the server (/api/composer/*): Enter commits a line as a new version, the
   agent back-translates it, and every version of a line sits in a horizontally scrolling row under it.
   The autocomplete pop-up under the caret reads a client-side pool per (poem, line, slot), filled ahead of time by
   the agent (SSE) and, at once, by the corpus proposer; filtering is local (js/composer-core.js).
   The chat panel streams the agent's answers, its tool calls and its candidates.
   The composer always shows the scanner's own probabilities: no metre ever adjusts them here. */
(() => {
  'use strict';
  const C = window.ComposerCore;
  const $ = id => document.getElementById(id);
  const board = $('board'), tip = $('tip'), popup = $('popup');
  const POET_DIALECT = { Sappho: 'aeolic', Alcaeus: 'aeolic', Alcman: 'doric', Pindar: 'doric', Bacchylides: 'doric', Simonides: 'doric', Ibycus: 'doric' };
  const ANALYSIS_DIALECT = { aeolic: 'lesbian', doric: 'doric', ionic: 'ionic', attic: 'attic' };
  const METRES = ['hexameter', 'pentameter', 'elegiac', 'iambic_trimeter', 'trochaic_tetrameter', 'sapphic', 'sapphic_hendecasyllable',
    'adonean', 'alcaic', 'glyconic', 'pherecratean', 'hipponactean', 'telesillean', 'reizianum', 'aristophanean', 'lesser_asclepiad', 'greater_asclepiad'];
  const PREFS = 'melos-composer-prefs', POOL_N = 12, WORDS_N = 8, IDLE_MS = 600, AGENT_DOWN_MS = 60_000, STORED_MS = 3000, WARM_POLL_MS = 6 * 60_000;
  const esc = s => String(s ?? '').replace(/[&<>"]/g, ch => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[ch]));
  const store = (() => { try { return window.localStorage; } catch (e) { return null; } })();
  const local = { getItem: k => { try { return store && store.getItem(k); } catch (e) { return null; } },
    setItem: (k, v) => { try { store && store.setItem(k, v); } catch (e) { /* storage blocked */ } } };

  // ---- API ------------------------------------------------------------------------------------------------------
  class ApiError extends Error {
    constructor(status, body, message) { super(message); this.status = status; this.body = body; }
  }
  const fetchApi = (path, options = {}) => (window.melosApiFetch || fetch)(path, { credentials: 'same-origin', ...options });
  function describe(status, body) {
    const detail = body && (typeof body.detail === 'string' ? body.detail : body.detail?.message || (body.detail ? JSON.stringify(body.detail) : ''));
    if (status === 0) return 'The server could not be reached.';
    if (status === 404) return 'Not found. The composer is for the signed-in owner only: sign in from the menu (Log in) and reload.';
    if (status === 503 && body?.agent === 'unavailable') return `The agent is not running (503${detail ? `: ${detail}` : ''}). Typing, scansion and saving still work; suggestions come from the corpus only.`;
    if (status === 502) return `The agent failed (502)${detail ? `: ${String(detail).slice(0, 300)}` : ''}.`;
    if (status === 429) return 'Too many requests; wait a moment.';
    if (status === 422) return `The server refused the request: ${detail || 'invalid input'}.`;
    return `Server error ${status}${detail ? `: ${String(detail).slice(0, 300)}` : ''}.`;
  }
  async function request(method, path, body, signal, extra = {}) {
    let r;
    try {
      r = await fetchApi(path, { method, signal, headers: body ? { 'Content-Type': 'application/json' } : undefined, body: body ? JSON.stringify(body) : undefined, ...extra });
    } catch (e) {
      if (e.name === 'AbortError') throw e;
      throw new ApiError(0, null, describe(0) + (e.message ? ` (${e.message})` : ''));
    }
    if (!r.ok) {
      const data = await r.json().catch(() => null);
      if (r.status === 503 && data?.agent === 'unavailable') agentDown();
      throw new ApiError(r.status, data, describe(r.status, data));
    }
    return r;
  }
  const call = async (method, path, body, signal, extra) => (await request(method, path, body, signal, extra)).json();

  // ---- banner (every error is shown; nothing is swallowed) ------------------------------------------------------
  const banners = new Map();
  function banner(key, message, kind = 'error') {
    if (!message) { banners.delete(key); } else banners.set(key, { message, kind });
    const el = $('banner');
    el.replaceChildren(...[...banners].map(([k, b]) => {
      const p = document.createElement('p');
      p.className = 'banner-item ' + b.kind;
      p.textContent = b.message;
      const close = document.createElement('button');
      close.type = 'button'; close.className = 'banner-close'; close.textContent = 'Dismiss';
      close.addEventListener('click', () => banner(k, null));
      p.append(close);
      return p;
    }));
    el.hidden = !banners.size;
  }
  const failed = (key, e) => { if (e?.name !== 'AbortError') { banner(key, e.message || String(e)); console.error(e); } };
  let agentDownUntil = 0;
  function agentDown() {
    agentDownUntil = Date.now() + AGENT_DOWN_MS;
    banner('agent', describe(503, { agent: 'unavailable' }), 'warn');
  }

  // ---- state ----------------------------------------------------------------------------------------------------
  const S = {
    poems: [], poem: null, rows: [], active: null, uid: 0,
    scan: { seq: 0, text: null, res: null, byIndex: new Map() },
    pools: new Map(), fills: new Map(), prefixScans: new Map(),
    popup: { open: false, row: null, index: 0, options: [], auto: false, dismissed: null },
    analysis: new Map(), pending: new Set(), selected: null, chatStream: null, showArchived: new Set(),
    attest: new Map(), attestPending: new Set(),
  };
  const settings = () => ({ author: $('author').value, metre: $('metre').value, dialect: $('dialect').value });
  const scanDialect = () => { const d = $('dialect').value; return d && d !== 'none' ? d : d === 'none' ? 'none' : (POET_DIALECT[$('author').value] || 'none'); };
  const realMetre = () => { const m = $('metre').value; return m && m !== 'auto' && m !== 'none' ? m : null; };
  const rowIndex = row => S.rows.indexOf(row);
  const current = row => row.line?.versions?.find(v => v.id === row.line.current_version_id) || null;

  for (const m of METRES) $('metre').append(new Option(m.replace(/_/g, ' '), m));
  try {
    const saved = JSON.parse(local.getItem(PREFS) || '{}');
    if (typeof saved.theme === 'string') $('theme').value = saved.theme;
    for (const id of ['bars', 'pct', 'auto-ask']) if (typeof saved[id] === 'boolean') $(id).checked = saved[id];
    for (const id of ['english', 'chat']) if (saved[id + 'Collapsed']) collapse(id, true);
  } catch (e) { /* bad prefs */ }
  function savePrefs() {
    local.setItem(PREFS, JSON.stringify({ theme: $('theme').value, bars: $('bars').checked, pct: $('pct').checked, 'auto-ask': $('auto-ask').checked,
      englishCollapsed: $('english-panel').classList.contains('collapsed'), chatCollapsed: $('workspace').classList.contains('chat-collapsed') }));
    if ($('theme').value) local.setItem('melos-composer-theme', $('theme').value); else try { store?.removeItem('melos-composer-theme'); } catch (e) { /* blocked */ }
  }
  function collapse(which, value) {
    if (which === 'english') { $('english-panel').classList.toggle('collapsed', value); $('english-toggle').setAttribute('aria-expanded', String(!value)); }
    else { $('workspace').classList.toggle('chat-collapsed', value); $('chat-toggle').setAttribute('aria-expanded', String(!value)); }
  }

  // ---- TypeGreek mode, shared by every line editor --------------------------------------------------------------
  let mode = 'greek', syncingMode = false;
  try { const m = local.getItem('melos-typegreek-mode'); if (m === 'english') mode = 'english'; } catch (e) { /* blocked */ }
  function setMode(next) {
    if (syncingMode) return;
    syncingMode = true;
    mode = next;
    for (const r of S.rows) if (r.ime && r.ime.mode !== next) r.ime.setMode(next);
    const b = $('mode');
    b.setAttribute('aria-pressed', String(mode === 'greek'));
    b.textContent = mode === 'greek' ? 'Αα Greek' : 'Aa English';
    b.title = `Typing ${mode === 'greek' ? 'Greek (TypeGreek rules)' : 'English'} — Ctrl+\` to switch`;
    syncingMode = false;
  }
  $('mode').addEventListener('mousedown', e => e.preventDefault());
  $('mode').addEventListener('click', () => { setMode(mode === 'greek' ? 'english' : 'greek'); S.active?.el.ta.focus({ preventScroll: true }); });

  // ---- poems -------------------------------------------------------------------------------------------------------
  let saveTimer = 0, pendingPatch = {};
  function savePoem(fields) {
    if (!S.poem) return;
    Object.assign(pendingPatch, fields);
    $('save-state').textContent = 'Editing…';
    clearTimeout(saveTimer);
    saveTimer = setTimeout(flushSave, 700);
  }
  async function flushSave() {
    clearTimeout(saveTimer);
    if (!S.poem || !Object.keys(pendingPatch).length) return;
    const patch = pendingPatch, id = S.poem.id;
    pendingPatch = {};
    $('save-state').textContent = 'Saving…';
    try {
      // keepalive lets the save finish when the tab is closed; browsers cap keepalive bodies at 64 KB.
      const payload = JSON.stringify(patch);
      const poem = await call('PATCH', `/api/composer/poems/${id}`, patch, undefined, payload.length < 60000 ? { keepalive: true } : {});
      if (S.poem?.id === id) Object.assign(S.poem, poem);
      const listed = S.poems.find(p => p.id === id);
      if (listed) Object.assign(listed, poem);
      renderPoemSelect();
      $('save-state').textContent = 'Saved';
      banner('save', null);
    } catch (e) {
      Object.assign(pendingPatch, patch, pendingPatch);
      $('save-state').textContent = 'Not saved · retrying';
      failed('save', e);
      clearTimeout(saveTimer);
      saveTimer = setTimeout(flushSave, 5000);                            // keep trying until it lands
    }
  }
  function renderPoemSelect() {
    const sel = $('poem-select');
    sel.replaceChildren(...S.poems.map(p => new Option(p.title || `Untitled ${p.id}`, p.id)));
    if (S.poem) sel.value = String(S.poem.id);
  }
  async function newPoem() {
    await flushSave();
    try {
      const poem = await call('POST', '/api/composer/poems', { title: '', settings: settings(), english: '' });
      S.poems.unshift(poem);
      await openPoem(poem.id);
      $('poem-title').focus();
    } catch (e) { failed('poem', e); }
  }
  async function openPoem(id) {
    abortFill();
    closePopup();
    S.pools.clear();
    let full;
    try { full = await call('GET', `/api/composer/poems/${id}/full`); } catch (e) { failed('poem', e); return; }
    banner('poem', null);
    S.poem = full.poem;
    const s = S.poem.settings || {};
    if (typeof s.author === 'string') $('author').value = s.author;
    if (typeof s.metre === 'string') $('metre').value = s.metre;
    if (typeof s.dialect === 'string') $('dialect').value = s.dialect;
    $('poem-title').value = S.poem.title || '';
    $('english').value = S.poem.english || '';
    for (const r of S.rows) r.ime?.detach();
    S.rows = full.lines.map(line => makeRow(line, current({ line })?.greek || ''));
    restoreDrafts();
    ensureTrailingRow();
    S.scan = { seq: S.scan.seq + 1, text: null, res: null, byIndex: new Map() };
    renderBoard();
    renderThread(full.chat || []);
    renderPoemSelect();
    local.setItem('melos-composer-poem', String(id));
    const url = new URL(location.href);
    url.searchParams.set('poem', id);
    history.replaceState(null, '', url);
    scan();
    const target = S.rows.find(r => !r.draft.trim()) || S.rows.at(-1);
    focusRow(target, target.draft.length);
    warm(rowIndex(target));
  }

  // ---- rows ----------------------------------------------------------------------------------------------------------
  function makeRow(line, draft) {
    return { uid: line ? `l${line.id}` : `n${++S.uid}`, line, draft, acceptedFrom: null, bt: {}, saving: null, el: null, ime: null };
  }
  function ensureTrailingRow() {
    if (!S.rows.length || S.rows.at(-1).draft.trim() || S.rows.at(-1).line) S.rows.push(makeRow(null, ''));
  }
  const draftsKey = () => `melos-composer-drafts-${S.poem?.id}`;
  function saveDrafts() {
    if (!S.poem) return;
    const list = S.rows.filter(r => r.draft.trim() && r.draft.trim() !== (current(r)?.greek || '')).map(r => ({ id: r.line?.id ?? null, at: rowIndex(r), draft: r.draft }));
    local.setItem(draftsKey(), JSON.stringify(list));
    if (JSON.stringify(list) !== JSON.stringify(S.poem.drafts || [])) savePoem({ drafts: list });   // and on the server (release X.1)
  }
  function restoreDrafts() {
    // The server copy wins (it is what another browser or the agent sees); this browser's copy covers a save that failed.
    let list = Array.isArray(S.poem?.drafts) && S.poem.drafts.length ? S.poem.drafts : [];
    if (!list.length) try { list = JSON.parse(local.getItem(draftsKey()) || '[]'); } catch (e) { list = []; }
    for (const d of list) {
      if (typeof d?.draft !== 'string') continue;
      const row = d.id != null ? S.rows.find(r => r.line?.id === d.id) : null;
      if (row) row.draft = d.draft;
      else if (d.id == null) S.rows.push(makeRow(null, d.draft));
    }
  }

  function buildRow(row) {
    const root = document.createElement('section');
    root.className = 'line';
    root.innerHTML = `<div class="line-main"><span class="n"></span><div class="canvas line-canvas"><div class="backdrop" aria-hidden="true"></div>
      <textarea rows="1" wrap="off" aria-label="Line"></textarea></div></div>
      <div class="line-info"></div><p class="bt" hidden></p><div class="versions" role="list" aria-label="Versions of this line" hidden></div>`;
    const el = { root, n: root.querySelector('.n'), canvas: root.querySelector('.canvas'), backdrop: root.querySelector('.backdrop'),
      ta: root.querySelector('textarea'), info: root.querySelector('.line-info'), bt: root.querySelector('.bt'), versions: root.querySelector('.versions') };
    row.el = el;
    el.ta.value = row.draft;
    row.ime = window.TypeGreek.attach(el.ta, { storageKey: 'melos-typegreek-mode', onChange: value => edited(row, value), onModeChange: m => setMode(m) });
    if (row.ime.mode !== mode) row.ime.setMode(mode);
    el.ta.addEventListener('keydown', e => keydown(row, e));
    el.ta.addEventListener('focus', () => { if (S.popup.row !== row) closePopup(); S.active = row; root.classList.add('active'); });
    el.ta.addEventListener('blur', () => { root.classList.remove('active'); setTimeout(() => { if (!popup.contains(document.activeElement) && document.activeElement !== S.popup.row?.el.ta) closePopup(); }, 0); });
    el.ta.addEventListener('scroll', () => { el.backdrop.scrollLeft = el.ta.scrollLeft; positionPopup(); });
    for (const type of ['click', 'keyup']) el.ta.addEventListener(type, e => { if (type === 'keyup' && /^Arrow|Home|End/.test(e.key) === false) return; caretMoved(row); });
    el.versions.addEventListener('click', e => versionClick(row, e));
    el.bt.addEventListener('click', e => { if (e.target.closest('[data-retry]')) backTranslate(row, current(row)); });
    return el;
  }
  function renderBoard() {
    board.replaceChildren(...S.rows.map(row => (row.el || buildRow(row)).root));
    S.rows.forEach(updateRow);
  }
  function updateRow(row) {
    if (!row.el) return;
    row.el.n.textContent = rowIndex(row) + 1;
    if (row.el.ta.value !== row.draft) { row.el.ta.value = row.draft; row.ime.sync(); }
    renderBackdrop(row);
    renderInfo(row);
    renderBT(row);
    renderVersions(row);
  }
  function focusRow(row, caret) {
    if (!row?.el) return;
    row.el.ta.focus({ preventScroll: false });
    const at = Math.max(0, Math.min(caret ?? row.draft.length, row.draft.length));
    row.el.ta.setSelectionRange(at, at);
    row.el.backdrop.scrollLeft = row.el.ta.scrollLeft;
    S.active = row;
  }

  // ---- editing ---------------------------------------------------------------------------------------------------------
  let idleTimer = 0, scanTimer = 0, analysisTimer = 0;
  function edited(row, value) {
    if (value.includes('\n')) { pasteLines(row, value); return; }
    row.draft = value;
    renderBackdrop(row);
    renderInfo(row);
    saveDrafts();
    clearTimeout(scanTimer); scanTimer = setTimeout(scan, 150);
    clearTimeout(analysisTimer); analysisTimer = setTimeout(analyse, 900);
    caretMoved(row);
    clearTimeout(idleTimer);
    idleTimer = setTimeout(() => openPopup({ auto: true }), IDLE_MS);
  }
  function pasteLines(row, value) {
    const parts = value.split(/\r?\n/);
    const at = rowIndex(row);
    row.draft = parts[0];
    const added = parts.slice(1).map(text => makeRow(null, text));
    S.rows.splice(at + 1, 0, ...added);
    ensureTrailingRow();
    renderBoard();
    saveDrafts();
    scan();
    const last = added.at(-1) || row;
    focusRow(last, last.draft.length);
  }
  function keydown(row, e) {
    if (e.isComposing) return;
    const pop = S.popup;
    if (pop.open && pop.row === row) {
      if (e.key === 'Escape') { e.preventDefault(); pop.dismissed = slotKeyOf(row); closePopup(); return; }
      if (pop.options.length) {
        if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
          e.preventDefault();
          pop.index = (pop.index + (e.key === 'ArrowDown' ? 1 : -1) + pop.options.length) % pop.options.length;
          renderPopup();
          return;
        }
        if ((e.key === 'Enter' || e.key === 'Tab') && !e.shiftKey) { e.preventDefault(); accept(pop.options[pop.index]); return; }
      }
    }
    if (e.key === 'Tab' && !e.shiftKey && !e.ctrlKey && !e.altKey && !e.metaKey) { e.preventDefault(); openPopup({ auto: false }); return; }
    if (e.key === 'Enter' && !e.shiftKey && !e.ctrlKey && !e.altKey && !e.metaKey) { e.preventDefault(); commit(row); return; }
    if ((e.key === 'ArrowUp' || e.key === 'ArrowDown') && !e.shiftKey && !e.altKey) {
      const next = S.rows[rowIndex(row) + (e.key === 'ArrowUp' ? -1 : 1)];
      if (next) { e.preventDefault(); closePopup(); focusRow(next, row.el.ta.selectionStart); }
    }
  }
  function caretMoved(row) {
    const here = slotKeyOf(row);
    for (const f of S.fills.values()) if (f.row === row && f.slot !== here) abortFill(f.key);   // the owner left that slot
    if (S.popup.open) renderPopup();
  }

  // ---- commit: a new version on the server ---------------------------------------------------------------------------------
  async function commit(row, { move = true } = {}) {
    const text = row.draft.trim();
    const at = rowIndex(row);
    closePopup();
    if (!text) { const next = S.rows[at + 1]; if (move && next) focusRow(next, next.draft.length); return; }
    const cur = current(row);
    if (cur && cur.greek === text && !cur.archived) { if (move) moveOn(row); return; }
    const source = row.acceptedFrom && row.acceptedFrom.text === text ? row.acceptedFrom.source : 'owner';
    if (move) moveOn(row);
    const job = (row.saving || Promise.resolve()).then(async () => {
      row.state = 'saving'; renderInfo(row);
      try {
        let version;
        if (!row.line) {
          const position = S.rows.slice(0, at).filter(r => r.line).length;
          const line = await call('POST', `/api/composer/poems/${S.poem.id}/lines`, { position, greek: text, source });
          version = line.version;
          row.line = { id: line.id, poem_id: line.poem_id, position: line.position, current_version_id: line.current_version_id, versions: [version] };
          // Lines saved after this one moved down one on the server.
          for (const r of S.rows) if (r !== row && r.line && r.line.position >= line.position) r.line.position += 1;
        } else {
          version = await call('POST', `/api/composer/lines/${row.line.id}/versions`, { greek: text, source });
          row.line.versions.push(version);
          row.line.current_version_id = version.id;
        }
        row.state = '';
        banner('commit', null);
        saveDrafts();
        updateRow(row);
        backTranslate(row, version);
      } catch (e) {
        row.state = 'failed';
        renderInfo(row);
        failed('commit', e);
      }
    });
    row.saving = job;
    return job;
  }
  function moveOn(row) {
    ensureTrailingRow();
    renderBoard();
    const next = S.rows[rowIndex(row) + 1];
    focusRow(next, next.draft.length);
    if (!next.draft.trim()) warm(rowIndex(next));
    prefetch(next, C.slotAt(next.draft, next.draft.length).base);
  }

  // ---- back-translation ---------------------------------------------------------------------------------------------------
  async function backTranslate(row, version) {
    if (!version || version.back_translation || row.bt[version.id] === 'pending') return;
    row.bt[version.id] = 'pending';
    renderBT(row);
    try {
      const dialect = scanDialect();
      const res = await call('POST', '/api/composer/backtranslate', { greek: version.greek, dialect: dialect === 'none' ? null : dialect });
      if (res.cost_usd) cost(res.cost_usd);
      version.back_translation = res.english;
      delete row.bt[version.id];
      renderBT(row);
      renderVersions(row);
      const saved = await call('PATCH', `/api/composer/versions/${version.id}`, { back_translation: res.english });
      Object.assign(version, saved);
    } catch (e) {
      row.bt[version.id] = e.message || 'failed';
      renderBT(row);
      if (e.status !== 503) failed('backtranslate', e);
    }
  }
  function renderBT(row) {
    const el = row.el?.bt;
    if (!el) return;
    const v = current(row);
    const state = v && row.bt[v.id];
    el.hidden = !v;
    if (!v) return;
    el.classList.toggle('pending', state === 'pending');
    if (state === 'pending') el.textContent = 'translating…';
    else if (state) el.innerHTML = `<span class="bad">Back-translation failed: ${esc(state)}</span> <button type="button" class="link" data-retry>retry</button>`;
    else el.textContent = v.back_translation || '';
    el.hidden = !el.textContent.trim();
  }

  // ---- versions row ---------------------------------------------------------------------------------------------------------
  const when = t => (t ? new Intl.DateTimeFormat('en-US', { timeZone: 'America/Los_Angeles', month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit' }).format(new Date(t * 1000)) : '');
  const badgesHtml = badges => badges.map(b => `<span class="badge ${esc(b.state)}" title="${esc(b.title)}">${esc(b.id)}</span>`).join('');
  function renderVersions(row) {
    const el = row.el?.versions;
    if (!el) return;
    if (!row.line) { el.hidden = true; el.replaceChildren(); return; }
    const show = S.showArchived.has(row.line.id);
    const { cards, archivedCount } = C.versionsRow(row.line, { showArchived: show });
    el.hidden = cards.length < 2 && !archivedCount;
    if (el.hidden) { el.replaceChildren(); return; }
    el.innerHTML = cards.map(c => `<div class="vcard${c.current ? ' current' : ''}${c.archived ? ' archived' : ''}" role="listitem">
        <button type="button" class="vpick" data-pick="${c.id}" ${c.current ? 'aria-current="true"' : ''} title="${c.current ? 'Current version' : 'Make this version current'}">
          <span class="vgreek" lang="grc">${esc(c.greek)}</span>
          <span class="vmeta">${c.pattern ? `<span class="pattern">${esc(c.pattern)}</span>` : ''}${badgesHtml(c.badges)}</span>
          ${c.back_translation ? `<span class="vbt">${esc(c.back_translation)}</span>` : ''}
          <span class="vfoot">${esc(c.source)} · ${esc(when(c.created_at))}</span>
        </button>
        <button type="button" class="link vact" data-${c.archived ? 'restore' : 'archive'}="${c.id}">${c.archived ? 'restore' : 'archive'}</button>
      </div>`).join('')
      + (archivedCount ? `<button type="button" class="link vtoggle" data-toggle>${show ? 'hide archived' : `archived (${archivedCount})`}</button>` : '');
    const cur = el.querySelector('.vcard.current');
    if (cur && !el.matches(':hover')) el.scrollLeft = Math.max(0, cur.offsetLeft - el.clientWidth / 2 + cur.offsetWidth / 2);
  }
  async function versionClick(row, e) {
    const b = e.target.closest('button');
    if (!b || !row.line) return;
    if (b.dataset.toggle !== undefined) {
      if (S.showArchived.has(row.line.id)) S.showArchived.delete(row.line.id); else S.showArchived.add(row.line.id);
      renderVersions(row);
      return;
    }
    const id = Number(b.dataset.pick || b.dataset.archive || b.dataset.restore);
    if (!id) return;
    try {
      if (b.dataset.pick) {
        if (id === row.line.current_version_id) return;
        const v = await call('PATCH', `/api/composer/versions/${id}`, { make_current: true });
        row.line = { ...row.line, current_version_id: v.id, versions: row.line.versions.map(x => (x.id === v.id ? v : x)) };
        row.draft = v.greek;
        row.acceptedFrom = null;
        saveDrafts();
        updateRow(row);
        scan();
        backTranslate(row, current(row));
      } else {
        const archived = !!b.dataset.archive;
        const v = await call('PATCH', `/api/composer/versions/${id}`, { archived });
        const was = row.line.current_version_id;
        row.line = C.archiveVersion(row.line, v.id, archived);
        if (row.line.current_version_id !== was) { row.draft = current(row)?.greek || ''; scan(); }
        updateRow(row);
      }
      banner('version', null);
    } catch (err) { failed('version', err); }
  }

  // ---- line info: live scansion + the saved version's checks ------------------------------------------------------------
  function renderInfo(row) {
    const el = row.el?.info;
    if (!el) return;
    const live = liveScan(row);
    const v = current(row);
    const saved = v && v.greek === row.draft.trim();
    const parts = [];
    if (live?.pattern) parts.push(`<span class="pattern">${esc(live.pattern)}</span>`);
    if (live?.fit) parts.push(live.fit.ok ? `<span class="ok">fits ${esc(live.fit.metre.replace(/_/g, ' '))}</span>`
      : `<span class="bad">${esc(live.fit.metre.replace(/_/g, ' '))}: ${esc(live.fit.message)}${(live.fit.violations || []).map(x => ` · ${esc(x.text)} needs ${esc(x.needs)}`).join('')}</span>`);
    const att = attestOf(row);
    if (att && att.spans.length) {
      const flagged = att.spans.filter(s => s.level === 'warn' || s.level === 'bad');
      const unknown = att.spans.filter(s => s.level === 'unknown').length;
      parts.push(`<span class="attest">${flagged.map(s => `<span class="${s.level}" lang="grc">${s.level === 'bad' ? '✗' : '△'} ${esc(s.form)}</span> <span class="note">${esc(s.note)}</span>`).join(' · ')
        }${flagged.length ? '' : unknown ? 'attestation: checking…' : '<span class="ok">every spelling attested</span>'}</span>`);
    } else if (row.draft.trim() && S.attestPending.has(attestKey(row.draft.trim()))) parts.push('<span class="attest">attestation: checking…</span>');
    if (saved && v.checks) parts.push(`<span class="badges">${badgesHtml(C.checkBadges(v.checks))}</span>`);
    const state = row.state === 'saving' ? 'saving…' : row.state === 'failed' ? 'not saved' : saved ? `saved · ${esc(v.source)}`
      : row.draft.trim() ? (v ? 'edited · Enter saves a new version' : 'Enter saves') : '';
    if (state) parts.push(`<span class="state${row.state === 'failed' ? ' bad' : ''}">${state}</span>`);
    el.innerHTML = parts.join('');
  }

  // ---- scansion (the whole poem, so each line is fitted at its place in the stanza) ------------------------------------
  function rgb(p) {
    const css = getComputedStyle(document.documentElement);
    const c = n => css.getPropertyValue(n).split(',').map(Number);
    const [a, b, t] = p < 0.5 ? [c('--scan-short'), c('--scan-mid'), p / 0.5] : [c('--scan-mid'), c('--scan-long'), (p - 0.5) / 0.5];
    return a.map((x, i) => Math.round(x + (b[i] - x) * t)).join(',');
  }
  async function scan() {
    clearTimeout(scanTimer);
    const lines = S.rows.map(r => r.draft), text = lines.join('\n'), seq = ++S.scan.seq;
    if (!text.trim()) { S.scan = { seq, text, res: null, byIndex: new Map() }; S.rows.forEach(r => { renderBackdrop(r); renderInfo(r); }); return; }
    const m = $('metre').value || null;
    try {
      const r = await request('POST', '/api/scan', { text, lexicon: true, dialect: scanDialect(), metre: m === 'none' ? null : m });
      const res = await r.json();
      if (seq !== S.scan.seq) return;
      const starts = [0];
      for (let i = 0; i < text.length; i++) if (text[i] === '\n') starts.push(i + 1);
      const byIndex = new Map(), bad = new Set();
      (res.lines || []).forEach((l, k) => {
        const fit = res.fit?.[k];
        (fit?.violations || []).forEach(v => bad.add(v.syllable));
        byIndex.set(l.line, { text: lines[l.line], pattern: l.pattern, fit, units: [] });
      });
      for (const u of res.units || []) {
        const entry = byIndex.get(u.line);
        if (!entry) continue;
        const s = starts[u.line];
        entry.units.push({ ...u, rs: u.start - s, re: u.end - s, ns: u.nucleus[0] - s, violation: bad.has(u.i) });
      }
      S.scan = { seq, text, res, byIndex };
      scheduleAttest();
      status(`${(res.units || []).length} syllables · ${res.ms} ms${res.lexicon ? '' : ' · without the vowel-length lexicon'}${res.auto?.length ? ' · detected: ' + res.auto.slice(0, 3).map(a => `${a.metre.replace(/_/g, ' ')} (${a.lines_fitting}/${a.lines})`).join(', ') : ''}`);
    } catch (e) {
      if (seq === S.scan.seq) status(`Scansion: ${e.message}`, true);
    }
    S.rows.forEach(r => { renderBackdrop(r); renderInfo(r); });
  }
  const liveScan = row => { const e = S.scan.byIndex.get(rowIndex(row)); return e && e.text === row.draft ? e : null; };
  function renderBackdrop(row) {
    if (!row.el) return;
    const line = row.draft, units = liveScan(row)?.units || [], li = rowIndex(row);
    let html = '', pos = 0, first = true;
    for (const u of units) {
      if (u.rs < pos || u.re > line.length) continue;
      if (u.rs > pos) html += esc(line.slice(pos, u.rs));
      const p = u.p_long, c = rgb(p);
      html += `<span class="u${first ? '' : ' b'}${u.violation ? ' violation' : ''}${attClass(row, u.rs)}${S.selected === `${li}:${u.rs}` ? ' sel' : ''}" data-line="${li}" data-rs="${u.rs}" data-ns="${u.ns}" data-i="${u.i}" style="color:rgb(${c});background:rgba(${c},.06)">${esc(line.slice(u.rs, u.re))}<span class="pct">${Math.round(p * 100)}%</span></span>`;
      pos = u.re; first = false;
    }
    row.el.backdrop.innerHTML = html + esc(line.slice(pos)) + '​';
    row.el.backdrop.scrollLeft = row.el.ta.scrollLeft;
  }
  function status(message, bad = false) {
    const s = $('status');
    s.textContent = message;
    s.classList.toggle('bad', bad);
  }

  // ---- attestation of every typed word against the corpus (release X.3) -------------------------------------------------
  // Each distinct line goes once through the lint bank (POST /api/composer/check, no metre: L1 forms, L2 dialect, L4
  // attestation; a few ms per line on a warm server). Words are marked in the backdrop and summarised in the line info:
  // △ a spelling printed nowhere in the corpus (or only outside the dialect), ✗ the dialect's poets print another
  // spelling or no reading exists. Nothing here asks the model.
  const DIALECT_LABEL = { aeolic: 'Lesbian', doric: 'Doric', ionic: 'Ionic', attic: 'Attic' };
  const attestKey = line => `${$('author').value}|${scanDialect()}|${line}`;
  const WORD_RE = /[\u0370-\u03FF\u1F00-\u1FFF\u0300-\u036F\u1FBD\u1FBF’'ʼ]+/g;
  const normForm = s => s.normalize('NFC').replace(/[’'ʼ\u1FBD]/g, '’');
  let attestTimer = null;
  function scheduleAttest() { clearTimeout(attestTimer); attestTimer = setTimeout(attest, 350); }
  async function attest() {
    for (const line of [...new Set(S.rows.map(r => r.draft.trim()).filter(Boolean))]) {
      const key = attestKey(line);
      if (S.attest.has(key) || S.attestPending.has(key)) continue;
      if (S.attestPending.size >= 2) { scheduleAttest(); return; }
      S.attestPending.add(key);
      const d = scanDialect();
      const body = { greek: line, author: $('author').value || undefined, ...(d && d !== 'none' ? { dialect: d } : {}) };
      call('POST', '/api/composer/check', body).then(res => {
        const verdicts = C.attestWords(res.checks, { author: $('author').value, dialect: DIALECT_LABEL[d] || d });
        const byNorm = new Map([...verdicts.values()].map(v => [normForm(v.form), v]));
        const spans = [];
        for (const m of line.matchAll(WORD_RE)) {
          if (!/[\u0370-\u03FF\u1F00-\u1FFF]/.test(m[0])) continue;
          const v = verdicts.get(m[0]) || byNorm.get(normForm(m[0]));
          if (v) spans.push({ start: m.index, end: m.index + m[0].length, ...v });
        }
        S.attest.set(key, { spans });
        if (S.attest.size > 300) S.attest.delete(S.attest.keys().next().value);
      }).catch(e => status(`Attestation: ${e.message}`, true))
        .finally(() => { S.attestPending.delete(key); S.rows.forEach(r => { if (r.draft.trim() === line) { renderBackdrop(r); renderInfo(r); } }); });
    }
  }
  const attestOf = row => S.attest.get(attestKey(row.draft.trim())) || null;
  function attestAt(row, offset) {
    const lead = row.draft.length - row.draft.trimStart().length;
    return attestOf(row)?.spans.find(s => s.start <= offset - lead && offset - lead < s.end) || null;
  }
  const attClass = (row, offset) => { const a = attestAt(row, offset); return a && (a.level === 'warn' || a.level === 'bad') ? ` att-${a.level}` : ''; };
  const attestHtml = a => a ? `<div class="att-note ${a.level}">${a.level === 'bad' ? '✗' : a.level === 'warn' ? '△' : '✓'} ${esc(a.note)}</div>` : '';

  // ---- word analysis on hover, syllable reasons on click (release V) -----------------------------------------------------
  const analysisKey = line => `${$('author').value}|${$('dialect').value}|${line}`;
  async function analyse() {
    for (const line of [...new Set(S.rows.map(r => r.draft).filter(l => l.trim()))]) {
      const key = analysisKey(line);
      if (S.analysis.has(key) || S.pending.has(key)) continue;
      if (S.pending.size >= 2) { clearTimeout(analysisTimer); analysisTimer = setTimeout(analyse, 600); return; }
      S.pending.add(key);
      const body = { text: line, author: $('author').value || undefined };
      const d = ANALYSIS_DIALECT[$('dialect').value];
      if (d) body.dialect = d;
      call('POST', '/api/analyze-text', body).then(res => S.analysis.set(key, res.words || []))
        .catch(e => status(`Word analysis: ${e.message}`, true))
        .finally(() => { S.pending.delete(key); if (S.analysis.size > 200) S.analysis.delete(S.analysis.keys().next().value); });
    }
  }
  const wordAt = (line, offset) => S.analysis.get(analysisKey(S.rows[line]?.draft || ''))?.find(w => w.start <= offset && offset < w.end) || null;
  const wordHtml = w => w ? `<strong lang="grc">${esc(w.text)}</strong> — ${w.lemma ? `<span lang="grc">${esc(w.lemma)}</span>` : 'no headword'}${w.gloss ? ` “${esc(w.gloss)}”` : ''}${w.parse ? `<br>${esc(w.parse)}` : ''}` : '';
  const under = e => document.elementsFromPoint(e.clientX, e.clientY);
  function showTip(html, x, y) {
    tip.innerHTML = html;
    tip.hidden = false;
    tip.style.left = Math.max(8, Math.min(innerWidth - tip.offsetWidth - 16, x + 12)) + 'px';
    tip.style.top = Math.min(innerHeight - tip.offsetHeight - 8, y + 18) + 'px';
  }
  board.addEventListener('pointermove', e => {
    if (e.pointerType === 'touch' || e.target.tagName !== 'TEXTAREA') return;
    const u = under(e).find(el => el.classList?.contains('u'));
    const w = u && wordAt(+u.dataset.line, +u.dataset.ns);
    const a = u && S.rows[+u.dataset.line] ? attestAt(S.rows[+u.dataset.line], +u.dataset.rs) : null;
    if (!w && !a) { tip.hidden = true; return; }
    showTip((w ? wordHtml(w) : `<strong lang="grc">${esc(a.form)}</strong>`) + attestHtml(a), e.clientX, e.clientY);
  });
  board.addEventListener('pointerleave', () => { tip.hidden = true; });
  board.addEventListener('pointerup', e => {
    if (e.target.tagName !== 'TEXTAREA') return;
    const u = under(e).find(el => el.classList?.contains('u'));
    if (u) inspect(u);
  });
  function inspect(el) {
    const unit = S.scan.res?.units.find(x => x.i === +el.dataset.i);
    if (!unit) return;
    S.selected = `${el.dataset.line}:${el.dataset.rs}`;
    const w = wordAt(+el.dataset.line, +el.dataset.ns);
    const reasons = (unit.reasons || []).map(r => `<li>${esc(r.text)}${r.detail ? ` (${esc(r.detail)})` : ''} <span class="rid">${esc(r.id)}</span></li>`).join('');
    const flags = (unit.flags || []).map(f => `<li>${esc(f.text)}${f.p !== undefined ? ` (${Math.round(f.p * 100)}%)` : ''}</li>`).join('');
    $('inspector').innerHTML = `<h3 lang="grc">${esc(unit.text.trim())}</h3><div><span class="big">${Math.round(unit.p_long * 100)}%</span> long</div>
      <ul>${reasons}</ul>${flags ? `<div>Possible:</div><ul>${flags}</ul>` : ''}${w ? `<div class="word">${wordHtml(w)}</div>` : ''}`;
    $('inspector').hidden = false;
    S.rows.forEach(renderBackdrop);
  }

  // ---- the pool: agent continuations per slot (SSE) + corpus fillers ----------------------------------------------------
  const sig = () => C.settingsSig(settings());
  const slotKeyOf = row => {
    const ta = row.el?.ta, caret = ta ? ta.selectionStart : row.draft.length;
    return C.poolKey(S.poem?.id, row.uid, C.slotAt(row.draft, caret).base, settings());
  };
  const entriesFor = row => [...S.pools.values()].filter(e => e.lineKey === row.uid && e.sig === sig());
  /* Stop one running pool request (by its pool key), or all of them. The streamed candidates are kept. */
  function abortFill(key) {
    for (const [k, f] of [...S.fills]) {
      if (key && k !== key) continue;
      f.controller.abort();
      S.fills.delete(k);
    }
  }
  /* The metrical slots still open at `base` on this row's line: the line's template less the syllables already typed.
     null = no metre set; '' = the line is full; undefined = the text so far does not fit the metre. */
  async function templateAt(row, base) {
    const metre = realMetre();
    if (!metre) return null;
    const tpl = C.templateFor(metre, rowIndex(row));
    const head = base.trim();
    if (!head) return tpl;
    let labels = null;
    const live = liveScan(row);
    if (live) labels = live.units.filter(u => u.re <= head.length).map(u => u.label);
    else if (S.prefixScans.has(head)) labels = S.prefixScans.get(head);
    else {
      const res = await call('POST', '/api/scan', { text: head, lexicon: true, dialect: scanDialect() });
      labels = (res.units || []).map(u => u.label);
      S.prefixScans.set(head, labels);
      if (S.prefixScans.size > 200) S.prefixScans.delete(S.prefixScans.keys().next().value);
    }
    const left = C.remainingTemplate(labels, tpl);
    return left === null ? undefined : left;
  }
  /* Candidates the server already holds for this slot (stored by earlier stanza batches and by warm-ups), as a pool
     entry next to the live one. Reloaded at most every STORED_MS unless forced. */
  async function loadStored(row, base, { force = false } = {}) {
    if (!S.poem || !realMetre() || !row) return null;
    const pkey = C.poolKey(S.poem.id, row.uid, base, settings()) + '|stored';
    let entry = S.pools.get(pkey);
    if (entry && (entry.loading || (!force && Date.now() - entry.loadedAt < STORED_MS))) return entry;
    if (!entry) {
      entry = { key: pkey, lineKey: row.uid, sig: sig(), base, source: 'agent', template: null, candidates: [], status: 'stored', tools: [], rejected: 0, error: '', loadedAt: 0 };
      S.pools.set(pkey, entry);
    }
    entry.loading = true;
    try {
      const slotKey = await C.slotKey(rowIndex(row), base, settings());
      const res = await call('GET', `/api/composer/poems/${S.poem.id}/pool?slot_key=${slotKey}`);
      for (const p of res.pool || []) if (p.candidate?.greek && !entry.candidates.some(c => c.greek === p.candidate.greek)) entry.candidates.push(p.candidate);
      entry.loadedAt = Date.now();
    } catch (e) { entry.loadedAt = Date.now(); if (e.status !== 404) status(`Stored suggestions: ${e.message}`, true); }
    finally { entry.loading = false; }
    if (S.popup.open && S.popup.row === row) renderPopup();
    return entry;
  }
  /* Candidates the agent streams for a later slot of the stanza batch go to that line's stored entry at once. */
  function routeToSlot(data) {
    const row = S.rows[data.line_position];
    if (!row) return;                                              // that line is not on the board yet: stored on the server
    const base = data.prefix ? data.prefix + ' ' : '';
    const pkey = C.poolKey(S.poem.id, row.uid, base, settings()) + '|stored';
    if (!S.pools.has(pkey)) S.pools.set(pkey, { key: pkey, lineKey: row.uid, sig: sig(), base, source: 'agent', template: null, candidates: [], status: 'stored', tools: [], rejected: 0, error: '', loadedAt: 0 });
    const entry = S.pools.get(pkey);
    if (!entry.candidates.some(c => c.greek === data.greek)) entry.candidates.push(data);
    if (S.popup.open && S.popup.row === row) renderPopup();
  }
  /* Prefetch (POST .../warm): the agent researches the poem once and fills the stanza from line `position` in the
     background; while it works, the active line's stored candidates are re-read every STORED_MS. */
  let warmTimer = 0, warmUntil = 0;
  async function warm(position) {
    if (!S.poem || !$('auto-ask').checked || !realMetre() || Date.now() < agentDownUntil) return;
    const id = S.poem.id;
    try {
      const r = await call('POST', `/api/composer/poems/${id}/warm`, { line_position: position, n: POOL_N });
      if (!r.started || S.poem?.id !== id) return;
    } catch (e) { if (e.status !== 503 && e.status !== 422) failed('pool', e); return; }
    warmUntil = Date.now() + WARM_POLL_MS;
    if (warmTimer) return;
    warmTimer = setInterval(() => {
      const row = S.active;
      if (Date.now() > warmUntil || !S.poem) { clearInterval(warmTimer); warmTimer = 0; return; }
      if (row?.el && document.hasFocus()) loadStored(row, C.slotAt(row.draft, row.el.ta.selectionStart).base);
    }, STORED_MS);
  }
  /* Background prefetch: whole-line continuations for the slot (next words are asked for on Tab or a pause). */
  function prefetch(row, base) {
    if (!$('auto-ask').checked || !row) return;
    ensureCorpus(row);
    fill(row, base, { auto: true, mode: 'line' });
  }
  /* One pool request for a slot in one mode: 'words' = next words (1-3 words, fast, no stanza batch), 'line' =
     whole-line continuations plus the rest of the stanza. The two run side by side; each has its own pool entry. */
  async function fill(row, base, { auto, mode = 'line' }) {
    if (!S.poem || Date.now() < agentDownUntil) return;
    const slot = C.poolKey(S.poem.id, row.uid, base, settings());
    const key = mode === 'words' ? slot + '|words' : slot;
    const old = S.pools.get(key);
    if (old && (old.status === 'filling' || old.status === 'done' || old.status === 'full' || old.status === 'nofit' || (auto && old.status === 'error'))) return;
    const before = S.active === row ? row.draft.slice(0, row.el.ta.selectionStart) : base;
    const poemId = S.poem.id;
    await loadStored(row, base);                                         // what earlier stanza batches left for this slot
    if (S.poem?.id !== poemId || S.pools.get(key)?.status === 'filling') return;
    // Earlier pools on this line, or stored candidates, still cover this tier: no model request (Tab too; typing filters).
    if (C.reusable(entriesFor(row), before, mode) >= 3) { if (S.popup.open && S.popup.row === row) renderPopup(); return; }
    for (const f of S.fills.values()) if (f.row === row && f.slot !== slot) abortFill(f.key);     // requests for a slot left behind
    const controller = new AbortController();
    const entry = { key, lineKey: row.uid, sig: sig(), base, source: 'agent', mode, template: null, candidates: old?.candidates || [],
      status: 'filling', tools: [], rejected: 0, error: '', startedAt: Date.now() };
    S.pools.set(key, entry);
    S.fills.set(key, { key, slot, row, controller });
    renderPopup();
    try {
      const template = await templateAt(row, base);
      if (template === null) { entry.status = 'nofit'; entry.error = 'Model continuations need a metre: choose one in the toolbar (corpus lines still come).'; return; }
      if (template === '') { entry.status = 'full'; entry.error = 'The line is complete: Enter saves it.'; return; }
      if (template === undefined) { entry.status = 'nofit'; entry.error = `The line so far does not fit ${$('metre').value.replace(/_/g, ' ')}; fix it to get continuations.`; return; }
      entry.template = template;
      if (controller.signal.aborted) throw new DOMException('aborted', 'AbortError');
      const at = rowIndex(row);
      const body = { line_id: row.line?.id ?? null, caret: { line_position: at, char_offset: base.length, prefix: base }, prefix: base.trimEnd(),
        remaining_template: template, n: mode === 'words' ? WORDS_N : POOL_N, mode, ...(mode === 'words' ? { ahead_lines: 0 } : {}) };
      const mine = await C.slotKey(at, body.prefix, settings());
      await flushSave();                                                  // the agent reads the English and drafts from the server
      const r = await request('POST', `/api/composer/poems/${S.poem.id}/pool`, body, controller.signal);
      await C.readSSE(r, ({ event, data }) => {
        if (event === 'candidate' && data?.greek && data.slot_key && data.slot_key !== mine) routeToSlot(data);
        else if (event === 'candidate' && data?.greek) {
          if (!entry.candidates.some(c => c.greek === data.greek)) entry.candidates.push(data);
        } else if (event === 'tool') entry.tools.push(data?.name || 'tool');
        else if (event === 'rejected') entry.rejected = data?.count || 0;
        else if (event === 'error') { entry.error = data?.message || String(data); status(`Agent: ${entry.error}`, true); }
        else if (event === 'done' && data?.cost_usd) cost(data.cost_usd);
        if (S.popup.open && S.popup.row === row) renderPopup();
      });
      entry.status = 'done';
    } catch (e) {
      if (e.name === 'AbortError') { entry.status = 'aborted'; }
      else { entry.status = 'error'; entry.error = e.message; if (e.status !== 503) failed('pool', e); }
    } finally {
      if (S.fills.get(key)?.controller === controller) S.fills.delete(key);
      if (S.popup.open && S.popup.row === row) renderPopup();
    }
  }
  async function ensureCorpus(row) {
    if (!S.poem) return;
    const key = C.poolKey(S.poem.id, row.uid, '', settings()) + '|corpus';
    if (S.pools.has(key)) return;
    const above = S.rows.slice(0, rowIndex(row)).map(r => r.draft.trim()).filter(Boolean);
    if (!above.length) return;                                          // the corpus proposer continues a draft
    const entry = { key, lineKey: row.uid, sig: sig(), base: '', source: 'corpus', template: null, candidates: [], status: 'filling', tools: [], rejected: 0, error: '' };
    S.pools.set(key, entry);
    try {
      const s = settings();
      const body = { text: above.slice(-6).join('\n'), author: s.author || null, metre: s.metre || 'auto', k: 5 };
      if (s.dialect) body.dialect = s.dialect;
      const res = await call('POST', '/api/compose/suggest', body);
      entry.template = res.target?.template || null;
      entry.candidates = res.candidates || [];
      entry.status = 'done';
    } catch (e) {
      entry.status = 'error';
      entry.error = `Corpus: ${e.message}`;
      if (e.status !== 429) status(entry.error, true);
    }
    if (S.popup.open && S.popup.row === row) renderPopup();
  }

  // ---- the pop-up --------------------------------------------------------------------------------------------------------
  function openPopup({ auto }) {
    const row = S.active;
    if (!row?.el || document.activeElement !== row.el.ta || row.el.ta.selectionStart !== row.el.ta.selectionEnd) return;
    const key = slotKeyOf(row);
    if (auto && S.popup.dismissed === key) return;
    if (!auto) S.popup.dismissed = null;
    Object.assign(S.popup, { open: true, row, index: 0, auto });
    ensureCorpus(row);
    if (!auto || $('auto-ask').checked) {
      const base = C.slotAt(row.draft, row.el.ta.selectionStart).base;
      fill(row, base, { auto, mode: 'words' });          // next words first: short, fast
      fill(row, base, { auto, mode: 'line' });           // whole lines (and the rest of the stanza) in the background
    }
    renderPopup();
  }
  function closePopup() {
    S.popup.open = false;
    S.popup.options = [];
    popup.hidden = true;
    tip.hidden = true;
  }
  function renderPopup() {
    const pop = S.popup, row = pop.row;
    if (!pop.open || !row?.el) { popup.hidden = true; return; }
    const ta = row.el.ta, caret = ta.selectionStart;
    const before = row.draft.slice(0, caret);
    const tiered = C.tiered(entriesFor(row), before);
    pop.options = tiered.options;
    pop.index = Math.min(pop.index, Math.max(0, pop.options.length - 1));
    const slotKey = slotKeyOf(row), slot = S.pools.get(slotKey), words = S.pools.get(slotKey + '|words');
    const mine = [words, slot].filter(Boolean);
    const filling = entriesFor(row).some(e => e.status === 'filling');
    const error = mine.map(e => e.error).find(Boolean);
    if (pop.auto && !pop.options.length && !filling && !error) { popup.hidden = true; return; }
    const option = (o, k) => `<li role="option" id="opt-${k}" class="opt ${esc(o.source)} ${esc(o.mode)}" aria-selected="${k === pop.index}" data-k="${k}">
        <div class="opt-greek" lang="grc"><span class="typed">${esc(o.typed)}</span>${esc(o.rest)}</div>
        <div class="opt-meta">${o.pattern ? `<span class="pattern">${esc(o.pattern)}</span>` : ''}${o.english ? `<span class="span">“${esc(o.english)}”</span>` : ''}<span class="src">${esc(o.source)}${o.citation ? ` · ${esc(o.citation)}` : ''}</span></div>
      </li>`;
    const items = tiered.tiers.map(t => `<li class="tier" role="presentation">${esc(t.label)}</li>`
      + pop.options.slice(t.from, t.from + t.count).map((o, i) => option(o, t.from + i)).join('')).join('');
    const notes = [];
    if (filling) {
      const busy = mine.filter(e => e.status === 'filling').map(e => e.mode === 'words' ? 'words' : 'lines').join(' + ');
      const tools = mine.flatMap(e => e.tools || []).slice(-2).join(', ');
      notes.push(`<span class="thinking"><span class="dot"></span>thinking${busy ? ` · ${esc(busy)}` : ''}${tools ? ` · ${esc(tools)}` : ''}</span>`);
    }
    const rejected = mine.reduce((n, e) => n + (e.rejected || 0), 0);
    if (rejected) notes.push(`<span>${rejected} rejected by the checks</span>`);
    if (error) notes.push(`<span class="bad">${esc(error)}</span>`);
    if (!pop.options.length && !filling && !error) notes.push('<span>No continuations for this slot yet. Tab asks the model.</span>');
    popup.innerHTML = `<ul role="listbox" aria-label="Continuations">${items}</ul><div class="popup-foot">${notes.join('')}<span class="keys-hint">↑↓ · Enter · Esc</span></div>`;
    popup.hidden = false;
    ta.setAttribute('aria-activedescendant', pop.options.length ? `opt-${pop.index}` : '');
    positionPopup();
    const active = popup.querySelector('[aria-selected="true"]');
    active?.scrollIntoView({ block: 'nearest' });
    showEvidence(pop.options[pop.index], active);
  }
  const measure = document.createElement('canvas');
  function positionPopup() {
    if (popup.hidden || !S.popup.row?.el) return;
    const ta = S.popup.row.el.ta, cs = getComputedStyle(ta), ctx = measure.getContext('2d');
    ctx.font = `${cs.fontStyle} ${cs.fontWeight} ${cs.fontSize} ${cs.fontFamily}`;
    const r = ta.getBoundingClientRect();
    const x = r.left + parseFloat(cs.paddingLeft) + ctx.measureText(ta.value.slice(0, ta.selectionStart)).width - ta.scrollLeft;
    const w = popup.offsetWidth, h = popup.offsetHeight;
    popup.style.left = Math.max(8, Math.min(innerWidth - w - 8, x - 14)) + 'px';
    popup.style.top = (r.bottom + h + 8 > innerHeight && r.top - h - 4 > 0 ? r.top - h - 4 : r.bottom + 2) + 'px';
  }
  function showEvidence(o, el) {
    if (!o || !el || (!o.evidence.length && !o.checks.length)) { tip.hidden = true; return; }
    const checks = C.checkBadges(o.checks).map(b => `<li><span class="badge ${esc(b.state)}">${esc(b.id)}</span> ${esc(b.title)}</li>`).join('');
    const rect = el.getBoundingClientRect();
    showTip(`${o.evidence.length ? `<div class="ev-head">Evidence</div><ul>${o.evidence.map(x => `<li>${esc(x)}</li>`).join('')}</ul>` : ''}${checks ? `<ul class="ev-checks">${checks}</ul>` : ''}`,
      rect.right + 4 + 300 > innerWidth ? rect.left - 330 : rect.right - 8, rect.top - 18);
  }
  popup.addEventListener('mousedown', e => e.preventDefault());                     // keep the caret in the line
  popup.addEventListener('click', e => { const li = e.target.closest('.opt'); if (li) accept(S.popup.options[+li.dataset.k]); });
  popup.addEventListener('mousemove', e => {
    const li = e.target.closest('.opt');
    if (li && +li.dataset.k !== S.popup.index) { S.popup.index = +li.dataset.k; popup.querySelectorAll('.opt').forEach(x => x.setAttribute('aria-selected', String(x === li))); showEvidence(S.popup.options[S.popup.index], li); }
  });

  /* Insert `text` into `row` replacing [from, to); a continuation that runs past the line end continues on the next
     line(s). Lines it completes are saved. */
  function insertInto(row, from, to, text, source) {
    const at = rowIndex(row);
    const r = C.spillInsert(S.rows.map(x => x.draft), at, from, to, text);
    for (const i of r.inserted) S.rows.splice(i, 0, makeRow(null, ''));
    S.rows.forEach((x, i) => { x.draft = r.drafts[i]; });
    if (from === 0) row.acceptedFrom = { text: row.draft.trim(), source };
    ensureTrailingRow();
    renderBoard();
    saveDrafts();
    scan();
    for (const i of r.completed) commit(S.rows[i], { move: false });
    const target = S.rows[r.line];
    if (target !== row) target.acceptedFrom = { text: target.draft.trim(), source };
    focusRow(target, r.caret);
    return target;
  }
  function accept(option) {
    const row = S.popup.row;
    if (!option || !row) return;
    closePopup();
    const target = insertInto(row, option.from, row.el.ta.selectionStart, option.greek, option.source === 'corpus' ? 'corpus' : 'agent');
    // Prefetch the next slot: the next line when the continuation filled this one, else the slot after it.
    const fits = option.scansion?.fit;
    const full = Array.isArray(fits) && fits.length && fits.at(-1).remaining_template === '';
    if (full) {
      if (rowIndex(target) === S.rows.length - 1) { S.rows.push(makeRow(null, '')); renderBoard(); }
      prefetch(S.rows[rowIndex(target) + 1], '');
    } else prefetch(target, C.slotAt(target.draft, target.el.ta.selectionStart).base);
  }

  // ---- chat --------------------------------------------------------------------------------------------------------------
  const thread = $('thread');
  function message(role) {
    const li = document.createElement('li');
    li.className = 'msg ' + role;
    li.innerHTML = `<div class="who">${role === 'user' ? 'You' : 'Agent'}</div><div class="content"></div><div class="tools"></div><div class="cands"></div><div class="meta"></div>`;
    thread.append(li);
    return { li, content: li.querySelector('.content'), tools: li.querySelector('.tools'), cands: li.querySelector('.cands'), meta: li.querySelector('.meta'), toolCounts: new Map() };
  }
  function addTool(m, data) {
    const name = data?.name || 'tool';
    const n = (m.toolCounts.get(name) || 0) + 1;
    m.toolCounts.set(name, n);
    let chip = m.tools.querySelector(`[data-tool="${CSS.escape(name)}"]`);
    if (!chip) { chip = document.createElement('span'); chip.className = 'tool'; chip.dataset.tool = name; m.tools.append(chip); }
    chip.textContent = n > 1 ? `${name.replace(/^mcp__melos__/, '')} ×${n}` : name.replace(/^mcp__melos__/, '');
    if (data?.summary) chip.title = (chip.title ? chip.title + '\n' : '') + data.summary;
  }
  function addCandidate(m, cand) {
    const chip = document.createElement('span');
    chip.className = 'cand';
    chip.title = [cand.english_span && `“${cand.english_span}”`, ...(cand.evidence || [])].filter(Boolean).join('\n');
    chip.innerHTML = `<button type="button" class="cand-insert" lang="grc" title="Insert at the caret">${esc(cand.greek)}</button><button type="button" class="cand-add" title="Add as a version of the current line">+ version</button>`;
    chip.querySelector('.cand-insert').addEventListener('click', () => insertCandidate(cand));
    chip.querySelector('.cand-add').addEventListener('click', () => addVersionFrom(cand));
    m.cands.append(chip);
  }
  function applyEvent(m, event, data, live) {
    if (event === 'text' || event === 'delta' || event === 'token') m.content.textContent += data?.delta ?? data?.text ?? data?.content ?? (typeof data === 'string' ? data : '');
    else if (event === 'tool') addTool(m, data);
    else if (event === 'candidate' && data?.greek) addCandidate(m, data);
    else if (event === 'rejected' && data?.count) m.meta.append(`${data.count} candidates rejected by the checks. `);
    else if (event === 'error') { const e = document.createElement('div'); e.className = 'bad'; e.textContent = `Error: ${data?.message || data}`; m.li.insertBefore(e, m.meta); }
    else if (event === 'interrupted') m.meta.append('Interrupted. ');
    else if (event === 'done') {
      m.done = true;
      const u = data?.usage || {};
      if (data?.cost_usd != null) m.meta.append(`${C.money(data.cost_usd)} · ${Math.round((u.input_tokens || 0) / 100) / 10}k in / ${Math.round((u.output_tokens || 0) / 100) / 10}k out`);
      if (live && data?.cost_usd) cost(data.cost_usd);
    }
  }
  function renderThread(rows) {
    thread.replaceChildren();
    for (const r of rows) {
      const m = message(r.role === 'user' ? 'user' : 'agent');
      m.content.textContent = r.content || '';
      for (const t of Array.isArray(r.trace) ? r.trace : []) if (t && t.event) applyEvent(m, t.event, t.data, false);
    }
    if (!rows.length) thread.innerHTML = '<li class="empty">Ask anything about this poem: a form, a word in Sappho, how two words could join in the metre.</li>';
    thread.scrollTop = thread.scrollHeight;
  }
  async function sendChat(text) {
    if (!S.poem || S.chatStream || !text.trim()) return;
    thread.querySelector('.empty')?.remove();
    message('user').content.textContent = text;
    const m = message('agent');
    m.li.classList.add('streaming');
    const controller = new AbortController();
    S.chatStream = controller;
    $('chat-stop').hidden = false; $('chat-send').disabled = true;
    const row = S.active, ta = row?.el?.ta;
    const caret = row ? { line_position: rowIndex(row), char_offset: ta ? ta.selectionStart : 0, prefix: row.draft.slice(0, ta ? ta.selectionStart : 0) } : undefined;
    const sentAt = Date.now() / 1000 - 5;
    let streamed = false;
    try {
      await flushSave();                                                  // the agent reads the English and drafts from the server
      const r = await request('POST', `/api/composer/poems/${S.poem.id}/chat`, { message: text, caret }, controller.signal);
      streamed = true;
      await C.readSSE(r, ({ event, data }) => { applyEvent(m, event, data, true); thread.scrollTop = thread.scrollHeight; });
      banner('chat', null);
      if (!m.done) await awaitStoredReply(m, sentAt);                    // the stream ended early; the server keeps reading the agent
    } catch (e) {
      const err = document.createElement('div');
      err.className = 'bad';
      err.textContent = e.name === 'AbortError' ? 'Stopped.' : e.message;
      m.li.insertBefore(err, m.meta);
      if (e.name !== 'AbortError' && e.status !== 503) failed('chat', e);
      if (streamed && e.name !== 'AbortError') await awaitStoredReply(m, sentAt);
    } finally {
      m.li.classList.remove('streaming');
      S.chatStream = null;
      $('chat-stop').hidden = true; $('chat-send').disabled = false;
      thread.scrollTop = thread.scrollHeight;
    }
  }
  // After a dropped connection the agent keeps working and the server stores its reply when it ends (release X.2):
  // poll the thread until a reply newer than the question is there, then show the stored thread.
  async function awaitStoredReply(m, sentAt) {
    const id = S.poem?.id;
    if (!id) return;
    m.meta.append('Connection dropped; the agent is still working and its reply will appear here when it is stored… ');
    const until = Date.now() + 15 * 60000;
    while (Date.now() < until && S.poem?.id === id) {
      await new Promise(resolve => setTimeout(resolve, 8000));
      try {
        const full = await call('GET', `/api/composer/poems/${id}/full`);
        const last = (full.chat || []).at(-1);
        if (last?.role === 'assistant' && last.created_at >= sentAt && !(Array.isArray(last.trace) && last.trace.some(t => t?.event === 'interrupted'))) {
          renderThread(full.chat);
          return;
        }
      } catch (e) { /* keep waiting */ }
    }
    m.meta.append('No stored reply after 15 minutes; reload the page to check the thread. ');
  }
  function insertCandidate(cand) {
    const row = S.active || S.rows.at(-1);
    const caret = row.el.ta.selectionStart;
    const slot = C.slotAt(row.draft, caret);
    let from = caret, text = cand.greek;
    if (slot.typed && C.matchPrefix(cand.greek, slot.typed) >= 0) from = slot.base.length;
    else if (caret > 0 && !/\s$/.test(row.draft.slice(0, caret))) text = ' ' + text;
    insertInto(row, from, caret, text, 'agent');
  }
  async function addVersionFrom(cand) {
    const row = S.active || S.rows.at(-1);
    try {
      if (!row.line) {
        const at = rowIndex(row);
        const position = S.rows.slice(0, at).filter(r => r.line).length;
        const line = await call('POST', `/api/composer/poems/${S.poem.id}/lines`, { position, greek: cand.greek, source: 'agent' });
        row.line = { id: line.id, poem_id: line.poem_id, position: line.position, current_version_id: line.current_version_id, versions: [line.version] };
        row.draft = cand.greek;
        for (const r of S.rows) if (r !== row && r.line && r.line.position >= line.position) r.line.position += 1;
        ensureTrailingRow();
        renderBoard();
        scan();
        backTranslate(row, line.version);
      } else {
        const v = await call('POST', `/api/composer/lines/${row.line.id}/versions`, { greek: cand.greek, source: 'agent', make_current: false });
        row.line.versions.push(v);
        updateRow(row);
      }
      banner('version', null);
    } catch (e) { failed('version', e); }
  }
  $('chat-form').addEventListener('submit', e => {
    e.preventDefault();
    const text = $('chat-input').value;
    if (!text.trim()) return;
    $('chat-input').value = '';
    sendChat(text);
  });
  $('chat-input').addEventListener('keydown', e => {
    if (e.key === 'Enter' && !e.shiftKey && !e.isComposing) { e.preventDefault(); $('chat-form').requestSubmit(); }
  });
  $('chat-stop').addEventListener('click', () => S.chatStream?.abort());

  // ---- cost ----------------------------------------------------------------------------------------------------------
  function cost(usd) {
    if (usd) C.addCost(local, usd);
    $('cost').textContent = `today ${C.money(C.todayCost(local))}`;
  }

  // ---- controls ----------------------------------------------------------------------------------------------------------
  for (const id of ['author', 'dialect', 'metre']) $(id).addEventListener('change', () => {
    savePoem({ settings: { ...(S.poem?.settings || {}), ...settings() } });
    abortFill();
    closePopup();
    S.prefixScans.clear();
    scan();
  });
  for (const id of ['bars', 'pct']) $(id).addEventListener('change', () => { savePrefs(); applyView(); });
  $('auto-ask').addEventListener('change', savePrefs);
  $('theme').addEventListener('change', () => {
    const t = $('theme').value;
    if (t) document.documentElement.dataset.theme = t; else delete document.documentElement.dataset.theme;
    savePrefs(); S.rows.forEach(renderBackdrop);
  });
  function applyView() { board.classList.toggle('bars', $('bars').checked); board.classList.toggle('pct', $('pct').checked); }
  $('poem-title').addEventListener('input', () => savePoem({ title: $('poem-title').value }));
  $('english').addEventListener('input', () => savePoem({ english: $('english').value }));
  // Text put in by other means (dictation, a paste manager, a browser extension) may fire only `change`; save on blur too.
  for (const type of ['change', 'blur']) $('english').addEventListener(type, () => {
    if (S.poem && $('english').value !== (pendingPatch.english ?? S.poem.english ?? '')) savePoem({ english: $('english').value });
    flushSave();
  });
  for (const type of ['change', 'blur']) $('poem-title').addEventListener(type, () => {
    if (S.poem && $('poem-title').value !== (pendingPatch.title ?? S.poem.title ?? '')) savePoem({ title: $('poem-title').value });
    flushSave();
  });
  document.addEventListener('visibilitychange', () => { if (document.visibilityState === 'hidden') flushSave(); });
  addEventListener('pagehide', () => flushSave());
  $('poem-select').addEventListener('change', async () => { await flushSave(); openPoem(Number($('poem-select').value)); });
  $('new-poem').addEventListener('click', newPoem);
  $('english-toggle').addEventListener('click', () => { collapse('english', !$('english-panel').classList.contains('collapsed')); savePrefs(); });
  $('chat-toggle').addEventListener('click', () => { collapse('chat', !$('workspace').classList.contains('chat-collapsed')); savePrefs(); });
  matchMedia('(prefers-color-scheme: dark)').addEventListener?.('change', () => S.rows.forEach(renderBackdrop));
  addEventListener('resize', positionPopup);
  addEventListener('scroll', positionPopup, { passive: true });
  addEventListener('beforeunload', () => { if (Object.keys(pendingPatch).length) flushSave(); });

  async function init() {
    applyView();
    setMode(mode);
    cost(0);
    let poems;
    try { poems = (await call('GET', '/api/composer/poems')).poems || []; } catch (e) { failed('poem', e); return; }
    S.poems = poems;
    const want = Number(new URL(location.href).searchParams.get('poem')) || Number(local.getItem('melos-composer-poem'));
    let id = (poems.find(p => p.id === want) || poems[0])?.id;
    if (!id) {
      try {
        const poem = await call('POST', '/api/composer/poems', { title: '', settings: settings(), english: '' });
        S.poems = [poem];
        id = poem.id;
      } catch (e) { failed('poem', e); return; }
    }
    await openPoem(id);
  }
  init();
})();
