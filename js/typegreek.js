/* TypeGreek-exact Greek input method for a textarea (standalone; no other Melos code).
 *
 * Rules: typegreek.com (main page, /overview/, /alphabet.key/ and the site's own typegreek.js, read
 * 2026-10-09); the extracted rule table is docs/typegreek-rules.md. Behaviour:
 *   1. With Greek on, each typed character goes through KEYMAP (a → α, / → ´, ( → ῾, ; → ·, ? → ; ...).
 *   2. After every edit, TypeGreek's pass runs: precomposed Greek is broken back into letter + marks,
 *      marks are recombined onto the letter before them in any order when the result is a real
 *      character, and a lowercase sigma becomes final ς before a return, comma, ;, ., space, :, · .
 *   The pass runs on the edited word (the text between the whitespace around the edit). TypeGreek
 *   runs it on the whole box; the result for the edited word is identical, and text elsewhere
 *   (pasted Greek, English typed with Greek off) is left as it is.
 * Additions TypeGreek lacks: mobile keyboards (composition text is converted when the keyboard
 * commits it; autocorrect replacements and paste go through the same path), pasted Latin is
 * converted when Greek is on (pasted Greek is left alone), a Greek/English toggle with Ctrl+` and a
 * remembered choice, and NFC output.
 *
 *   const ime = TypeGreek.attach(textarea, {toggle: button, storageKey: 'melos-typegreek-mode'});
 *   ime.mode; ime.setMode('english'); ime.toggle(); ime.detach();
 *   TypeGreek.convert('mh=nin a)/eide') === 'μῆνιν ἄειδε'
 */
(function (root, factory) {
  const api = factory();
  if (typeof module === 'object' && module.exports) module.exports = api;
  else root.TypeGreek = api;
})(typeof self !== 'undefined' ? self : this, function () {
  'use strict';

  // Spacing marks TypeGreek inserts for the diacritic keys, and the combining marks they stand for.
  const ACUTE = '´', GRAVE = '`', CIRC = '῀', SMOOTH = '᾿', ROUGH = '῾';
  const DIAER = '¨', IOTA = 'ͺ', DOT = '̣';
  const COMBINING = { [SMOOTH]: '̓', [ROUGH]: '̔', [DIAER]: '̈', [ACUTE]: '́',
    [GRAVE]: '̀', [CIRC]: '͂', [IOTA]: 'ͅ' };
  const SPACING = Object.fromEntries(Object.entries(COMBINING).map(([k, v]) => [v, k]));

  const KEYMAP = {};
  const lower = 'abgdezhqiklmncoprstufxywjv', greekLower = 'αβγδεζηθικλμνξοπρστυφχψωςϝ';
  const upper = 'ABGDEZHQIKLMNCOPRSTUFXYWJV', greekUpper = 'ΑΒΓΔΕΖΗΘΙΚΛΜΝΞΟΠΡΣΤΥΦΧΨΩΣϜ';
  for (let i = 0; i < lower.length; i++) { KEYMAP[lower[i]] = greekLower[i]; KEYMAP[upper[i]] = greekUpper[i]; }
  Object.assign(KEYMAP, { '/': ACUTE, '\\': GRAVE, '&': GRAVE, '=': CIRC, '(': ROUGH, ')': SMOOTH, '+': DIAER,
    '|': IOTA, '!': IOTA, ':': '·', ';': '·', '?': ';', '@': DOT });

  const COMBINABLE = 'ΑαΗηΩωΕεΙιΟοΡρΥυ', VOWELS = 'ΑαΗηΩωΕεΙιΟοΥυ', CAPITALS = 'ΑΗΩΕΙΟΡΥ';
  const LONG_VOWELS = 'ΑαΗηΩωΙιΥυ', ROUGH_OK = 'ΑαΗηΩωΕεΙιΟοΡρΥυ', SMOOTH_OK = 'ΑαΗηΩωΕεΙιΟου';
  const IOTA_OK = 'ΑαΗηΩω', DIAER_OK = 'ΥυΙι';
  const TERMINAL = '\n\r,;. :·;';
  const terminal = ch => TERMINAL.indexOf(ch) > -1;          // as TypeGreek: '' (end of text) counts
  const GREEK_LETTER = /[Ͱ-Ͽἀ-῿]/;
  const isSpace = ch => /\s/.test(ch);

  // May mark `c` join the letter-with-marks `w`? `n1`, `n2`: the characters after `c`.
  function accepts(w, c, n1, n2) {
    const base = w[0], has = m => w.indexOf(m) > -1;
    const accent = has(ACUTE) || has(GRAVE) || has(CIRC), breathing = has(SMOOTH) || has(ROUGH);
    const capital = CAPITALS.indexOf(base) > -1, breathingNext = n1 === SMOOTH || n1 === ROUGH;
    if (c === ACUTE || c === GRAVE) {
      if (VOWELS.indexOf(base) < 0 || accent) return false;
      if (!capital) return true;
      if (DIAER_OK.indexOf(base) > -1) return !has(DIAER);
      if (IOTA_OK.indexOf(base) > -1) return !(has(IOTA) && !breathing);
      return true;
    }
    if (c === CIRC) {
      if (LONG_VOWELS.indexOf(base) < 0 || accent) return false;
      if (!capital) return true;
      if (DIAER_OK.indexOf(base) > -1) {
        if (!((breathing || breathingNext) && !has(DIAER))) return false;
        return SMOOTH_OK.indexOf(base) > -1 || has(ROUGH) || n1 === ROUGH;
      }
      if (IOTA_OK.indexOf(base) > -1) {
        return breathing || breathingNext || (n1 === IOTA && !has(IOTA) && (n2 === SMOOTH || n2 === ROUGH));
      }
      return false;
    }
    if (c === SMOOTH || c === ROUGH) {
      if (ROUGH_OK.indexOf(base) < 0 || breathing || has(DIAER)) return false;
      return c === ROUGH || SMOOTH_OK.indexOf(base) > -1;
    }
    if (c === IOTA) {
      if (IOTA_OK.indexOf(base) < 0 || has(IOTA)) return false;
      return !capital || !accent || breathing || breathingNext;
    }
    if (c === DIAER) {
      if (DIAER_OK.indexOf(base) < 0 || has(DIAER) || breathing) return false;
      return !capital || !accent;
    }
    return false;
  }

  // Letter + accepted marks → one precomposed character, or the marks left as typed when none exists.
  function compose(w) {
    const order = [SMOOTH, ROUGH, DIAER, ACUTE, GRAVE, CIRC, IOTA];
    const marks = w.slice(1).sort((a, b) => order.indexOf(a) - order.indexOf(b));
    const out = (w[0] + marks.map(m => COMBINING[m]).join('')).normalize('NFC');
    return out.length === 1 ? out : w.join('');
  }

  // A precomposed letter TypeGreek can rebuild → letter + spacing marks (breathing, accent, ι/¨); ς → σ.
  const brokenCache = new Map();
  function breakApart(ch) {
    if (ch === 'ς') return 'σ';
    if (ch.charCodeAt(0) < 0x370) return ch;
    let parts = brokenCache.get(ch);
    if (parts === undefined) {
      parts = ch;
      const d = ch.normalize('NFD');
      if (d !== ch && COMBINABLE.indexOf(d[0]) > -1 && [...d.slice(1)].every(m => SPACING[m])) {
        const rank = m => ([SMOOTH, ROUGH].includes(m) ? 0 : [ACUTE, GRAVE, CIRC].includes(m) ? 1 : 2);
        const marks = [...d.slice(1)].map(m => SPACING[m]).sort((a, b) => rank(a) - rank(b));
        const w = [d[0]];
        if (marks.every((m, i) => accepts(w, m, marks[i + 1] || '', marks[i + 2] || '') && w.push(m)) && compose(w) === ch) {
          parts = d[0] + marks.join('');
        }
      }
      brokenCache.set(ch, parts);
    }
    return parts;
  }

  /* TypeGreek's pass over `text`; `after` is the text that follows it (for final sigma; '' = end of
     the box). Returns {text, caret(i)}: caret(i) maps a caret before text[i] to the new text. */
  function pass(text, after = '') {
    const s = [], from = [];
    for (let i = 0; i < text.length; i++) for (const ch of breakApart(text[i])) { s.push(ch); from.push(i); }
    const n = s.length, at = j => (j < n ? s[j] : after.charAt(j - n));
    const firstOf = new Array(text.length + 1).fill(n);
    for (let j = n - 1; j >= 0; j--) firstOf[from[j]] = j;
    const outAt = new Array(n + 1);              // caret before s[j] → output offset
    let out = '', k = 0;
    while (k < n) {
      const start = k;
      let w = [s[k++]];
      if (k < n || after) {
        if (COMBINABLE.indexOf(w[0]) > -1) {
          while (k < n && accepts(w, s[k], at(k + 1), at(k + 2))) w.push(s[k++]);
          if (w.length > 1) w = [...compose(w)];
        } else if (w[0] === 'σ' && (terminal(at(k)) || (at(k) === DOT && terminal(at(k + 1))))) {
          w = ['ς'];
        }
      }
      const piece = w.join('');
      for (let j = start; j < k; j++) {
        outAt[j] = j === start ? out.length : piece.length === 1 ? out.length + 1 : out.length + (j - start);
      }
      out += piece;
    }
    outAt[n] = out.length;
    return { text: out, caret: i => outAt[firstOf[Math.max(0, Math.min(i, text.length))]] };
  }

  const mapLatin = text => Array.from(text, ch => KEYMAP[ch] || ch).join('');
  const normalize = text => pass(text).text.normalize('NFC');
  const convert = latin => normalize(mapLatin(latin));

  /* Apply one edit: `prev` was the value before, `value` after, caret/selection in `value`.
     Returns {value, start, end} (unchanged value when nothing converts). */
  function applyEdit(prev, value, start, end, greek) {
    let p = 0;
    const max = Math.min(prev.length, value.length);
    while (p < max && prev[p] === value[p]) p++;
    let q = 0;
    while (q < max - p && prev[prev.length - 1 - q] === value[value.length - 1 - q]) q++;
    const insEnd = value.length - q, inserted = value.slice(p, insEnd);
    if (inserted.length > 1 && GREEK_LETTER.test(inserted)) {
      // Pasted or replaced Greek is left alone (NFC only).
      const nfc = inserted.normalize('NFC'), shift = nfc.length - inserted.length;
      const move = c => (c >= insEnd ? c + shift : c > p ? Math.min(c, p + nfc.length) : c);
      return { value: value.slice(0, p) + nfc + value.slice(insEnd), start: move(start), end: move(end) };
    }
    if (greek && !GREEK_LETTER.test(inserted)) value = value.slice(0, p) + mapLatin(inserted) + value.slice(insEnd);
    let L = p, R = insEnd;
    while (L > 0 && !isSpace(value[L - 1])) L--;
    while (R < value.length && !isSpace(value[R])) R++;
    const done = pass(value.slice(L, R), value.slice(R, R + 3));
    const word = done.text.normalize('NFC') === done.text ? done.text : done.text.normalize('NFC');
    const shift = word.length - (R - L);
    const move = c => (c < L ? c : c >= R ? c + shift : L + Math.min(done.caret(c - L), word.length));
    return { value: value.slice(0, L) + word + value.slice(R), start: move(start), end: move(end) };
  }

  function attach(el, options = {}) {
    const key = options.storageKey || 'melos-typegreek-mode';
    let mode = options.mode || 'greek';
    try { const saved = localStorage.getItem(key); if (saved === 'greek' || saved === 'english') mode = saved; } catch (e) { /* storage blocked */ }
    let last = el.value, composing = false;
    for (const [name, value] of [['autocapitalize', 'off'], ['autocorrect', 'off'], ['autocomplete', 'off'], ['spellcheck', 'false']]) {
      el.setAttribute(name, value);
    }
    const toggleButton = options.toggle || null;

    function render() {
      el.setAttribute('lang', mode === 'greek' ? 'grc' : 'en');
      el.dataset.typegreek = mode;
      if (toggleButton) {
        toggleButton.setAttribute('aria-pressed', String(mode === 'greek'));
        toggleButton.textContent = mode === 'greek' ? 'Αα Greek' : 'Aa English';
        toggleButton.title = `Typing ${mode === 'greek' ? 'Greek (TypeGreek rules)' : 'English'} — Ctrl+\` to switch`;
      }
      if (options.onModeChange) options.onModeChange(mode);
    }
    function setMode(next) {
      mode = next === 'english' ? 'english' : 'greek';
      try { localStorage.setItem(key, mode); } catch (e) { /* storage blocked */ }
      render();
    }
    function sync() {
      // Re-read the value after a programmatic change (accepting a suggestion), without converting it.
      last = el.value;
    }
    function process() {
      const value = el.value;
      if (value === last) return;
      const r = applyEdit(last, value, el.selectionStart, el.selectionEnd, mode === 'greek');
      if (r.value !== value) {
        el.value = r.value;
        el.setSelectionRange(r.start, r.end);
      }
      last = el.value;
      if (options.onChange) options.onChange(el.value);
    }
    const onInput = e => { if (!composing && !e.isComposing) process(); };
    const onCompositionStart = () => { composing = true; };
    const onCompositionEnd = () => { composing = false; process(); };
    const onKeyDown = e => {
      if (e.ctrlKey && !e.altKey && !e.metaKey && (e.code === 'Backquote' || e.key === '`')) {
        e.preventDefault();
        setMode(mode === 'greek' ? 'english' : 'greek');
      }
    };
    const onToggle = e => { e.preventDefault(); setMode(mode === 'greek' ? 'english' : 'greek'); el.focus({ preventScroll: true }); };
    // Keep the caret in the textarea when the toggle is tapped (mobile keyboards stay open).
    const keepFocus = e => e.preventDefault();
    el.addEventListener('input', onInput);
    el.addEventListener('compositionstart', onCompositionStart);
    el.addEventListener('compositionend', onCompositionEnd);
    el.addEventListener('keydown', onKeyDown);
    if (toggleButton) { toggleButton.addEventListener('click', onToggle); toggleButton.addEventListener('mousedown', keepFocus); }
    render();
    return {
      get mode() { return mode; },
      setMode, sync,
      toggle: () => setMode(mode === 'greek' ? 'english' : 'greek'),
      detach() {
        el.removeEventListener('input', onInput);
        el.removeEventListener('compositionstart', onCompositionStart);
        el.removeEventListener('compositionend', onCompositionEnd);
        el.removeEventListener('keydown', onKeyDown);
        if (toggleButton) { toggleButton.removeEventListener('click', onToggle); toggleButton.removeEventListener('mousedown', keepFocus); }
      },
    };
  }

  return { attach, convert, normalize, applyEdit, KEYMAP, version: 'typegreek-2026-10-09' };
});
