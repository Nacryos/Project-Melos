/* Reader scansion overlay (release V): "Scansion" puts – ⏑ × above each syllable of a Greek poem, "Syllable
   breaks" shows bold | between syllables. Scanned on demand (GET /api/scan/passage, once per passage, cached).
   Marks and bars are generated content inside each word's button: clicks still select the whole word, and
   selection and copy never include them. Brackets round a supplement are read through (the server scans the
   editor's text like any other); only a syllable at a gap, letters lost or illegible, gets no mark. Each mark
   is centred over its vowel or diphthong. The bars divide syllables as the marks scan them: one consonant
   opens the next syllable, of a cluster the first consonant closes the syllable before. A poem whose metre is
   recorded has its uncertain syllables settled by the metre (the server's metre lock; the composer never does
   this). Turning both toggles off restores the reader's DOM exactly. */
(() => {
  'use strict';
  const text = document.getElementById('passage-text');
  const frame = text?.closest('.text-frame');
  if (!text || !frame) return;
  const KEY = 'melos-reader-scansion';
  let prefs = { marks: false, bars: false };
  try { Object.assign(prefs, JSON.parse(localStorage.getItem(KEY) || '{}')); } catch (e) { /* storage blocked */ }
  const cache = new Map();
  const originals = new Map();
  let applying = false, current = null, timer = 0;

  const tools = document.createElement('div');
  tools.className = 'scansion-tools';
  tools.hidden = true;
  const marksButton = button('Scansion', 'Show long – and short ⏑ marks above each syllable');
  const barsButton = button('Syllable breaks', 'Show | between syllables');
  const note = document.createElement('span');
  note.className = 'scansion-note';
  note.setAttribute('role', 'status');
  tools.append(marksButton, barsButton, note);
  frame.before(tools);
  const detail = document.createElement('div');
  detail.className = 'scansion-detail';
  detail.hidden = true;
  frame.after(detail);

  function button(label, title) {
    const b = document.createElement('button');
    b.type = 'button'; b.textContent = label; b.title = title;
    b.addEventListener('click', () => {
      prefs[b === marksButton ? 'marks' : 'bars'] = b.getAttribute('aria-pressed') !== 'true';
      try { localStorage.setItem(KEY, JSON.stringify(prefs)); } catch (e) { /* storage blocked */ }
      apply();
    });
    return b;
  }
  const passageId = () => new URL(location.href).searchParams.get('id');
  const readerText = () => {
    const lines = [...text.querySelectorAll('.line .line-content')];
    return lines.length ? lines.map(line => line.textContent).join('\n') : [...text.querySelectorAll(':scope > p')].map(p => p.textContent).join('\n');
  };
  const rgb = p => {
    const css = getComputedStyle(document.documentElement);
    const c = n => css.getPropertyValue(n).split(',').map(Number);
    const [a, b, t] = p < 0.5 ? [c('--scan-short'), c('--scan-mid'), p / 0.5] : [c('--scan-mid'), c('--scan-long'), (p - 0.5) / 0.5];
    return a.map((x, i) => Math.round(x + (b[i] - x) * t)).join(',');
  };
  const combining = ch => /\p{M}/u.test(ch);
  const CONSONANT = /[βγδζθκλμνξπρστφχψϝ]/;
  const consonant = ch => CONSONANT.test(String(ch ?? '').normalize('NFD')[0]?.toLowerCase() ?? '');
  // Syllable breaks inside one word button [start, end): between two nuclei, a single consonant opens the
  // next syllable; of a cluster the first consonant closes the syllable before (what the marks scan: the
  // syllable before two consonants is long); no consonant, the break falls before the vowel. Brackets and
  // apostrophes are transparent, and a break never falls inside a bracket pair.
  function breaks(text, nuclei, start, end) {
    const cuts = [];
    for (let k = 1; k < nuclei.length; k++) {
      const cluster = [];
      for (let i = nuclei[k - 1].nucleus[1]; i < nuclei[k].nucleus[0]; i++) if (consonant(text[i])) cluster.push(i);
      let cut = cluster.length ? cluster[Math.min(1, cluster.length - 1)] : nuclei[k].nucleus[0];
      while (cut > start && /[\[⟨〈]/.test(text[cut - 1])) cut--;
      if (cut > start && cut < end) cuts.push(cut);
    }
    return cuts;
  }

  function undecorate() {
    applying = true;
    for (const [node, original] of originals) if (node.isConnected) node.textContent = original;
    originals.clear();
    applying = false;
  }
  function decorate(scan) {
    applying = true;
    const units = scan.units;
    for (const word of text.querySelectorAll('button.word')) {
      const start = Number(word.dataset.sourceStart), end = Number(word.dataset.sourceEnd);
      const original = word.textContent;
      if (!Number.isFinite(start) || scan.text.slice(start, end) !== original) continue;
      const nuclei = units.filter(u => u.nucleus[0] >= start && u.nucleus[0] < end).sort((a, b) => a.nucleus[0] - b.nucleus[0]);
      const cuts = breaks(scan.text, nuclei, start, end);
      // The mark sits over the whole nucleus (vowel or diphthong), anchored at its first letter.
      const anchors = new Map();
      for (const u of nuclei) if (!u.editorial) anchors.set(u.nucleus[0], u);
      if (!anchors.size && !cuts.length) continue;
      originals.set(word, original);
      word.textContent = '';
      const bounds = [start, ...cuts, end];
      for (let k = 0; k + 1 < bounds.length; k++) {
        const s = bounds[k], e = bounds[k + 1];
        const syl = document.createElement('span');
        syl.className = k ? 'sy b' : 'sy';
        let pos = s;
        for (const [a, u] of [...anchors].filter(([a]) => a >= s && a < e)) {
          let z = Math.min(Math.max(u.nucleus[1], a + 1), e);
          while (z < e && combining(scan.text[z])) z++;
          if (a > pos) syl.append(scan.text.slice(pos, a));
          const n = document.createElement('span');
          const m = u.metre;
          const p = m ? m.p_after : u.p_long;
          n.className = 'sy-n' + (p >= 0.3 && p <= 0.7 ? ' unsure' : '') + (m?.conflict ? ' conflict' : '');
          n.dataset.m = m?.requires === 'anceps' ? '×' : p >= 0.5 ? '–' : '⏑';
          n.style.setProperty('--sc', rgb(p));
          n.title = `${Math.round(p * 100)}% long` + (m?.adjusted ? ` (${m.reason}; scanner ${Math.round(m.p_before * 100)}%)` : m?.reason ? ` (${m.reason})` : '');
          n.textContent = scan.text.slice(a, z);
          syl.append(n);
          pos = z;
        }
        if (pos < e) syl.append(scan.text.slice(pos, e));
        word.append(syl);
      }
    }
    applying = false;
    window.MelosVerseFit?.refit?.(text);
  }
  function showDetail(word) {
    const scan = current;
    if (!scan || !prefs.marks) { detail.hidden = true; return; }
    const start = Number(word.dataset.sourceStart), end = Number(word.dataset.sourceEnd);
    const units = scan.units.filter(u => u.nucleus[0] >= start && u.nucleus[0] < end);
    if (!units.length) { detail.hidden = true; return; }
    detail.replaceChildren();
    const head = document.createElement('div');
    head.textContent = `${word.textContent}: syllables`;
    const list = document.createElement('ul');
    for (const u of units) {
      const li = document.createElement('li');
      const m = u.metre;
      const p = m ? m.p_after : u.p_long;
      const reason = u.reasons?.length ? u.reasons[u.reasons.length - 1].text : '';
      li.textContent = u.editorial ? `${u.text.trim()}: editorial gap, not marked`
        : `${u.text.trim()}: ${Math.round(p * 100)}% long${reason ? ` (${reason})` : ''}`
          + (m?.adjusted ? `; ${m.reason} (scanner ${Math.round(m.p_before * 100)}%)` : m?.conflict ? `; ${m.reason}` : '');
      list.append(li);
    }
    const meta = document.createElement('div');
    meta.className = 'meta';
    meta.textContent = scan.metre ? `Recorded metre: ${scan.metre.label}. Source: ${scan.metre.source}.` : 'No recorded metre: the scanner’s own probabilities.';
    detail.append(head, list, meta);
    detail.hidden = false;
  }
  text.addEventListener('click', event => {
    const word = event.target.closest?.('button.word');
    if (word) showDetail(word);
  }, true);

  async function load(id) {
    if (cache.has(id)) return cache.get(id);
    const request = (window.melosApiFetch || fetch)(`/api/scan/passage?id=${encodeURIComponent(id)}`)
      .then(r => (r.ok ? r.json() : Promise.reject(new Error(`scan ${r.status}`))));
    cache.set(id, request);
    request.catch(() => cache.delete(id));
    return request;
  }
  async function apply() {
    marksButton.setAttribute('aria-pressed', String(prefs.marks));
    barsButton.setAttribute('aria-pressed', String(prefs.bars));
    const greek = text.lang === 'grc' && text.querySelector('button.word');
    tools.hidden = !greek;
    undecorate();
    text.classList.toggle('scan-marks', Boolean(prefs.marks && greek));
    text.classList.toggle('scan-bars', Boolean(prefs.bars && greek));
    if (!prefs.marks) detail.hidden = true;
    current = null;
    if (!greek || (!prefs.marks && !prefs.bars)) { note.textContent = ''; return; }
    const id = passageId();
    if (!id) return;
    note.textContent = 'Scanning…';
    try {
      const scan = await load(id);
      if (passageId() !== id) return;
      if (scan.text !== readerText()) { note.textContent = 'Scansion is not available for this layout.'; return; }
      current = scan;
      undecorate();
      decorate(scan);
      note.replaceChildren(document.createTextNode(scan.metre ? `${scan.metre.label} (recorded) · short ` : 'short '),
        Object.assign(document.createElement('span'), { className: 'legend-bar' }), document.createTextNode(' long'));
    } catch (e) {
      note.textContent = 'Scansion is unavailable right now.';
    }
  }
  // The reader replaces the passage's DOM on navigation: re-apply after each new passage.
  new MutationObserver(() => {
    if (applying) return;
    clearTimeout(timer);
    timer = setTimeout(() => { originals.clear(); detail.hidden = true; apply(); }, 60);
  }).observe(text, { childList: true });
  apply();
})();
