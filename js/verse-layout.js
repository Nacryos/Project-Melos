// Stanza layout for verse in the reader (2026-10-14). Editions print the Sapphic stanza as three
// hendecasyllables and an indented adonic, the Alcaic stanza with its third and fourth lines stepped
// in, and a space between stanzas (Lobel–Page, Voigt, Campbell). The corpus stores one source line
// per row and, outside the Campbell transcription, no layout; this module recovers the stanza from
// the lines themselves. It never changes the text: the result is only classes on the rows.
//
//   window.MelosVerseLayout.plan(lines, metadata) -> [{ stanzaStart, indent }] per line
//
// The stanza form is recognised from syllable counts of the complete lines (no brackets or gaps),
// with the line position taken from numeric line labels when the source has them; a fragment whose
// surviving lines do not fit either form keeps the edition's own layout metadata, if any, else nothing.
(() => {
  'use strict';
  const GREEK = /(?=\p{L})\p{Script=Greek}/u;
  const VOWELS = new Set('αεηιουω');
  const DIPHTHONGS = new Set(['αι', 'ει', 'οι', 'υι', 'αυ', 'ευ', 'ου', 'ηυ', 'ωυ']);
  const INCOMPLETE = /[\[\]⟨⟩〈〉⟦⟧…]|\.\s*\.|\*\*\*/u;
  const PRINTED_NUMBER = /^[ \t ]*(\d+)[ \t ]*\./u;

  // Nuclei of a line: vowels, with diphthongs counted once unless a diaeresis separates them.
  function syllables(text) {
    const chars = [...String(text).normalize('NFD').toLowerCase()];
    let count = 0, previous = '', previousVowel = false;
    for (let i = 0; i < chars.length; i++) {
      const ch = chars[i];
      if (/\p{M}/u.test(ch)) continue;
      const vowel = VOWELS.has(ch);
      if (vowel) {
        let diaeresis = false;
        for (let j = i + 1; j < chars.length && /\p{M}/u.test(chars[j]); j++) if (chars[j] === '̈') diaeresis = true;
        if (!(previousVowel && !diaeresis && DIPHTHONGS.has(previous + ch))) count++;
        else { previousVowel = false; previous = ''; continue; } // a diphthong closes the nucleus
      }
      previousVowel = vowel; previous = vowel ? ch : '';
    }
    return count;
  }

  // Expected syllable range by position in the stanza (1-based) for each form, and the indent.
  const FORMS = {
    sapphic: { range: { 1: [10, 12], 2: [10, 12], 3: [10, 12], 4: [4, 6] }, indent: { 4: 1 }, distinctive: [4] },
    // The distinctive slot is the one a hendecasyllable can never fill: the adonic, the enneasyllable.
    alcaic: { range: { 1: [10, 12], 2: [10, 12], 3: [8, 10], 4: [9, 11] }, indent: { 3: 1, 4: 2 }, distinctive: [3] }
  };

  function plan(lines, metadata) {
    const rows = Array.isArray(lines) ? lines : [];
    const result = rows.map(() => ({ stanzaStart: false, indent: 0 }));
    // Verse rows: lines with a numeric label, Greek letters, or a bracketed lacuna standing for a lost
    // line ("[     ]", "] . . [") keep their place in the stanza; blank rows and the editors' "lines
    // missing" marks (". . . . .", "***") do not count.
    const verse = [];
    rows.forEach((line, index) => {
      const text = String(line?.text ?? ''), label = String(line?.label ?? '');
      let number = /^\d+$/.test(label) ? Number(label) : null;
      if (number === null) { const printed = text.match(PRINTED_NUMBER); if (printed) number = Number(printed[1]); }
      const lostLine = /[\[\]⟨⟩〈〉⟦⟧]/u.test(text) && !/\*\*\*/.test(text);
      if (number !== null || GREEK.test(text) || lostLine) verse.push({ index, number, complete: GREEK.test(text) && !INCOMPLETE.test(text), count: syllables(text) });
    });
    const labelled = verse.some(row => row.number !== null);
    const numbers = phase => verse.map((row, k) => {
      if (!labelled) return k + 1 + phase;
      let anchor = null;
      for (let j = k; j >= 0; j--) if (verse[j].number !== null) { anchor = j; break; }
      if (anchor === null) for (let j = k; j < verse.length; j++) if (verse[j].number !== null) { anchor = j; break; }
      return verse[anchor].number + (k - anchor);
    });
    let best = null;
    for (const phase of labelled ? [0] : [0, 1, 2, 3]) {
      const positions = numbers(phase).map(n => ((n - 1) % 4 + 4) % 4 + 1);
      for (const [name, form] of Object.entries(FORMS)) {
        // A complete line is a hit or a miss. A bracketed line counts only when it fits (the editor's
        // supplement restores it); when it does not, letters may simply be lost, so it is no evidence.
        let checked = 0, hits = 0, distinctive = 0;
        verse.forEach((row, k) => {
          const [low, high] = form.range[positions[k]];
          const fits = row.count >= low && row.count <= high;
          if (!row.complete && !fits) return;
          checked++;
          if (fits) { hits++; if (form.distinctive.includes(positions[k])) distinctive++; }
        });
        // Three of four lines suffice: a complete-looking line may still be cut short (Sappho 34 "γᾶν").
        if (checked < 3 || !distinctive || hits / checked < 0.75) continue;
        const score = hits / checked + distinctive / 100;
        if (!best || score > best.score) best = { name, form, positions, score };
      }
    }
    if (best) {
      verse.forEach((row, k) => {
        const position = best.positions[k];
        result[row.index].indent = best.form.indent[position] || 0;
        if (position === 1 && k > 0) result[row.index].stanzaStart = true;
      });
      return Object.assign(result, { form: best.name });
    }
    const layout = metadata && typeof metadata === 'object' && metadata.layout && typeof metadata.layout === 'object' ? metadata.layout : null;
    if (layout) {
      for (const index of Array.isArray(layout.stanza_breaks) ? layout.stanza_breaks : []) if (result[index] && index > 0) result[index].stanzaStart = true;
      for (const index of Array.isArray(layout.indented) ? layout.indented : []) if (result[index]) result[index].indent = 1;
      return Object.assign(result, { form: 'edition' });
    }
    return Object.assign(result, { form: null });
  }

  window.MelosVerseLayout = { plan, syllables, PRINTED_NUMBER };
})();
