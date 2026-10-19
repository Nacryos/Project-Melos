/* Scansion page: paste Greek or Latin verse. The language is told from the script (Greek letters: Greek; Latin
   letters: Latin; the person can override it), the text goes to POST /api/scan with that language, and every
   syllable is printed with – ⏑ above its vowel, coloured by how sure the scanner is, with | between syllables
   (the server's display spans: a single consonant opens the next syllable, of a cluster the first closes the one
   before). A metre can be chosen or detected (metre=auto, then a second request fits the best one); with
   "Settle by metre" the marks follow the metre's best parse: elided syllables (Latin) get a dot, a synizesis a
   tie. Clicking a syllable lists the rules that decided it, with their citations. */
(() => {
  'use strict';
  const $ = id => document.getElementById(id);
  const input = $('scan-text'), out = $('scan-out'), status = $('scan-status'), detail = $('scan-detail');
  const languageSelect = $('scan-language'), metreSelect = $('scan-metre'), dialectLabel = $('scan-dialect-label'), dialectSelect = $('scan-dialect');
  const barsButton = $('scan-bars'), settleButton = $('scan-settle');
  const KEY = 'melos-scan-page';
  const EXAMPLES = {
    grc: 'ποικιλόθρον’ ἀθανάτ’ Ἀφρόδιτα,\nπαῖ Δίος δολόπλοκε, λίσσομαί σε,\nμή μ’ ἄσαισι μηδ’ ὀνίαισι δάμνα,\nπότνια, θῦμον,',
    la: 'Vivamus, mea Lesbia, atque amemus,\nrumoresque senum severiorum\nomnes unius aestimemus assis!',
  };
  const prefs = { bars: true, settle: true, language: 'auto', metre: 'auto', dialect: 'none' };
  try { Object.assign(prefs, JSON.parse(localStorage.getItem(KEY) || '{}')); } catch (e) { /* storage blocked */ }
  const save = () => { try { localStorage.setItem(KEY, JSON.stringify(prefs)); } catch (e) { /* storage blocked */ } };
  const api = (path, options) => (window.melosApiFetch || fetch)(path, options);
  let metres = null, seq = 0, timer = 0, current = null;

  const GREEK = /\p{Script=Greek}/gu, LATIN = /\p{Script=Latin}/gu;
  function detect(text) {
    const greek = (text.match(GREEK) || []).length, latin = (text.match(LATIN) || []).length;
    if (!greek && !latin) return null;
    return greek >= latin ? 'grc' : 'la';
  }
  const language = () => (prefs.language === 'auto' ? detect(input.value) : prefs.language);
  const LABEL = { grc: 'Greek', la: 'Latin' };

  function fillLanguage() {
    const detected = detect(input.value);
    languageSelect.options[0].textContent = detected ? `Auto (${LABEL[detected]})` : 'Auto';
    languageSelect.value = prefs.language;
    const lang = language();
    input.lang = lang || '';
    dialectLabel.hidden = lang !== 'grc';
  }
  async function loadMetres() {
    if (metres) return metres;
    try { metres = await api('/api/scan/metres').then(r => (r.ok ? r.json() : Promise.reject(new Error(`metres ${r.status}`)))); }
    catch (e) { metres = {}; }
    return metres;
  }
  function fillMetres(lang) {
    const rows = (metres && metres[lang] && metres[lang].metres) || [];
    const keep = prefs.metre;
    metreSelect.replaceChildren(
      new Option('Detect', 'auto'),
      new Option('None (scanner only)', ''),
      ...rows.map(m => new Option(m.label, m.name)));
    metreSelect.value = [...metreSelect.options].some(o => o.value === keep) ? keep : 'auto';
    prefs.metre = metreSelect.value;
  }

  const rgb = p => {
    const css = getComputedStyle(document.documentElement);
    const c = n => css.getPropertyValue(n).split(',').map(Number);
    const [a, b, t] = p < 0.5 ? [c('--scan-short'), c('--scan-mid'), p / 0.5] : [c('--scan-mid'), c('--scan-long'), (p - 0.5) / 0.5];
    return a.map((x, i) => Math.round(x + (b[i] - x) * t)).join(',');
  };
  const combining = ch => /\p{M}/u.test(ch);
  const letter = ch => /[\p{L}\p{M}\[\]⟨⟩〈〉’'ʼ]/u.test(ch || '');

  async function scan() {
    const my = ++seq;
    const text = input.value;
    fillLanguage();
    const lang = language();
    detail.hidden = true;
    if (!text.trim() || !lang) { out.replaceChildren(); status.textContent = text.trim() ? 'No Greek or Latin letters found.' : ''; status.classList.remove('error'); return; }
    await loadMetres();
    if (my !== seq) return;
    fillMetres(lang);
    status.textContent = 'Scanning…'; status.classList.remove('error');
    const body = { text, language: lang, lexicon: true, dialect: lang === 'grc' ? prefs.dialect : 'none', metre: prefs.metre || null, stanzas: true };
    try {
      let res = await post(body);
      if (my !== seq) return;
      let detected = null;
      if (prefs.metre === 'auto') {
        detected = (res.auto || []).filter(a => a.lines_fitting > 0)[0] || null;
        if (detected) { const fitted = await post({ ...body, metre: detected.metre }); if (my !== seq) return; res = { ...fitted, auto: res.auto }; }
      }
      current = { res, text, lang, detected };
      render();
      const n = res.units.length, lines = res.lines.length;
      status.textContent = `${n} syllable${n === 1 ? '' : 's'} in ${lines} line${lines === 1 ? '' : 's'} · ${LABEL[lang]}` + (res.lexicon ? '' : ' · without the vowel-length lexicon');
    } catch (e) {
      if (my !== seq) return;
      status.textContent = `Scansion is unavailable right now (${e.message}).`; status.classList.add('error');
    }
  }
  async function post(body) {
    const r = await api('/api/scan', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
    const data = await r.json().catch(() => ({}));
    if (!r.ok) throw new Error(typeof data.detail === 'string' ? data.detail : `scan ${r.status}`);
    return data;
  }

  function render() {
    if (!current) return;
    const { res, text, lang, detected } = current;
    const settle = prefs.settle && Array.isArray(res.fit);
    out.classList.add('scan-marks');
    out.classList.toggle('scan-bars', prefs.bars);
    out.replaceChildren();
    const byLine = new Map();
    for (const u of res.units) { if (!byLine.has(u.line)) byLine.set(u.line, []); byLine.get(u.line).push(u); }
    const lineNumbers = res.lines.map(l => l.line);
    const lines = text.split('\n');
    let offset = 0;
    lines.forEach((lineText, li) => {
      const start = offset, end = offset + lineText.length; offset = end + 1;
      const units = (byLine.get(li) || []).slice().sort((a, b) => a.nucleus[0] - b.nucleus[0]);
      if (!units.length) { if (lineText.trim()) out.append(plainLine(lineText, lang)); return; }
      const fit = settle ? res.fit[lineNumbers.indexOf(li)] : null;
      const parsed = fit && fit.log_likelihood !== null;
      // Per unit: the mark's probability, and whether the metre's parse elides it or ties it to the one before.
      const weight = new Map(), elided = new Set(), tied = new Set();
      if (parsed) {
        const idx = new Map(units.map((u, k) => [u.i, k]));
        for (const entry of fit.assignment) {
          if (entry.elided) { elided.add(entry.syllables[0]); continue; }
          entry.syllables.forEach((i, k) => { if (k) tied.add(i); });
        }
        units.forEach((u, k) => weight.set(u.i, fit.posterior_p_long[k]));
      }
      const block = document.createElement('div'); block.className = 'scan-line';
      const verse = document.createElement('p'); verse.className = 'scan-verse'; verse.lang = lang;
      let pos = start;
      units.forEach((u, k) => {
        const [s0, s1] = u.syllable, [n0, n1] = u.nucleus;
        const a = Math.max(s0, pos), e = Math.max(s1, n1);
        if (a > pos) verse.append(text.slice(pos, a));
        const syl = document.createElement('span');
        syl.className = 'sy' + (k && a > start && letter(text[a - 1]) && pos === a ? ' b' : '');
        syl.dataset.i = String(u.i);
        let z = Math.min(Math.max(n1, n0 + 1), e);
        while (z < e && combining(text[z])) z++;
        if (n0 > a) syl.append(text.slice(a, n0));
        const n = document.createElement('span');
        const p = parsed && weight.has(u.i) ? weight.get(u.i) : u.p_long;
        const isElided = parsed ? elided.has(u.i) : u.label === 'E';
        n.className = 'sy-n' + (p >= 0.3 && p <= 0.7 && !isElided ? ' unsure' : '') + (isElided ? ' elided' : tied.has(u.i) ? ' tie' : '');
        n.dataset.m = p >= 0.5 ? '–' : '⏑';
        n.style.setProperty('--sc', rgb(isElided ? 0.5 : p));
        n.title = isElided ? 'elided before the next vowel' : tied.has(u.i) ? 'synizesis: read with the vowel before' : `${Math.round(p * 100)}% long`;
        n.textContent = text.slice(n0, z);
        syl.append(n);
        if (z < e) syl.append(text.slice(z, e));
        verse.append(syl);
        pos = e;
      });
      if (pos < end) verse.append(text.slice(pos, end));
      block.append(verse);
      const line = res.lines.find(l => l.line === li);
      const meta = document.createElement('div'); meta.className = 'scan-pattern';
      meta.textContent = parsed ? fit.pattern : (line ? line.pattern : '');
      block.append(meta);
      if (fit) {
        const f = document.createElement('div');
        f.className = 'scan-fit ' + (fit.ok ? 'ok' : 'bad');
        const name = metreLabel(fit.metre, lang);
        f.textContent = fit.ok ? `fits ${name}` : `${name}: ${fit.message}` + (fit.violations && fit.violations.length
          ? ' — ' + fit.violations.map(v => `${v.text.trim()} needs ${v.needs}`).join('; ') : '');
        block.append(f);
      }
      out.append(block);
    });
    if (prefs.metre === 'auto' && res.auto) {
      const d = document.createElement('p'); d.className = 'scan-detected';
      d.textContent = detected
        ? `Detected: ${metreLabel(detected.metre, lang)} (${detected.lines_fitting} of ${detected.lines} line${detected.lines === 1 ? '' : 's'} fit)`
          + (res.auto.filter(a => a !== detected && a.lines_fitting > 0).length ? ` · also ${res.auto.filter(a => a !== detected && a.lines_fitting > 0).slice(0, 3).map(a => `${metreLabel(a.metre, lang)} (${a.lines_fitting} of ${a.lines})`).join(', ')}` : '')
        : 'No metre detected: the marks are the scanner’s own.';
      out.append(d);
    }
  }
  function plainLine(lineText, lang) {
    const block = document.createElement('div'); block.className = 'scan-line';
    const verse = document.createElement('p'); verse.className = 'scan-verse'; verse.lang = lang; verse.textContent = lineText;
    block.append(verse);
    return block;
  }
  function metreLabel(name, lang) {
    const rows = (metres && metres[lang] && metres[lang].metres) || [];
    const row = rows.find(m => m.name === name) || (metres && Object.values(metres).flatMap(l => l.metres).find(m => m.name === name));
    return row ? row.label : name.replace(/_/g, ' ');
  }

  function showDetail(index) {
    const u = current && current.res.units.find(x => x.i === index);
    if (!u) { detail.hidden = true; return; }
    out.querySelectorAll('.sy.sel').forEach(x => x.classList.remove('sel'));
    out.querySelector(`.sy[data-i="${index}"]`)?.classList.add('sel');
    detail.replaceChildren();
    const h = document.createElement('h2'); h.lang = current.lang; h.textContent = u.text.trim();
    const p = document.createElement('div');
    p.textContent = `${Math.round(u.p_long * 100)}% long` + (u.vowel ? ` · vowel ${Math.round(u.vowel.p_long * 100)}% long` : '')
      + (u.elision ? ` · elided ${Math.round(u.elision * 100)}%` : '');
    const list = document.createElement('ul');
    for (const r of u.reasons || []) {
      const li = document.createElement('li');
      li.append(Object.assign(document.createElement('b'), { textContent: r.text }), r.detail ? ` (${r.detail})` : '', ' ',
        Object.assign(document.createElement('span'), { className: 'rid', textContent: r.id }));
      if (r.cite) li.append(document.createElement('br'), Object.assign(document.createElement('span'), { className: 'cite', textContent: r.cite }));
      list.append(li);
    }
    detail.append(h, p, list);
    if (u.flags && u.flags.length) {
      const flags = document.createElement('ul');
      for (const f of u.flags) flags.append(Object.assign(document.createElement('li'), { textContent: `${f.text}${f.p !== undefined ? ` (${Math.round(f.p * 100)}%)` : ''}` }));
      detail.append(Object.assign(document.createElement('div'), { textContent: 'Possible:' }), flags);
    }
    detail.hidden = false;
  }

  out.addEventListener('click', event => {
    const syl = event.target.closest('.sy');
    if (syl) showDetail(Number(syl.dataset.i));
  });
  input.addEventListener('input', () => { clearTimeout(timer); timer = setTimeout(scan, 200); fillLanguage(); });
  languageSelect.addEventListener('change', () => { prefs.language = languageSelect.value; save(); scan(); });
  metreSelect.addEventListener('change', () => { prefs.metre = metreSelect.value; save(); scan(); });
  dialectSelect.addEventListener('change', () => { prefs.dialect = dialectSelect.value; save(); scan(); });
  for (const [button, key] of [[barsButton, 'bars'], [settleButton, 'settle']]) {
    button.setAttribute('aria-pressed', String(prefs[key]));
    button.addEventListener('click', () => { prefs[key] = !prefs[key]; button.setAttribute('aria-pressed', String(prefs[key])); save(); render(); });
  }
  document.querySelectorAll('[data-example]').forEach(b => b.addEventListener('click', () => { input.value = EXAMPLES[b.dataset.example]; scan(); }));
  dialectSelect.value = prefs.dialect;
  languageSelect.value = prefs.language;
  const shared = new URLSearchParams(location.search).get('text');
  if (shared) input.value = shared;
  fillLanguage();
  if (input.value.trim()) scan();
})();
