// Stanza layout for verse in the reader (2026-10-14). Editions print the Sapphic stanza as three
// hendecasyllables and an indented adonic, the Alcaic stanza with its third and fourth lines stepped
// in, and a space between stanzas (Lobel–Page, Voigt, Campbell). The corpus stores one source line
// per row and, outside the Campbell transcription, no layout; this module recovers the stanza from
// the lines themselves. It never changes the text: the result is only classes on the rows.
//
//   window.MelosVerseLayout.plan(lines, metadata, { author }) -> [{ stanzaStart, indent }] per line
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
  // Letters actually lost, as against a supplement that restores them: a line that opens at a bracket
  // or whose first or last word is cut by one ("]δώσην", "λί]μενος", "ἔχη[", "μέγ[αν"), an empty gap,
  // or the editors' dots. Its syllable count is only a lower bound. "Κύπρι καὶ] Νηρήιδες" and
  // "εἰς] ἔρον ἦλθε" restore whole words and count in full.
  const TRUNCATED = /^[\s.·]*(\S*\]\S|\])|\[\S*[\s.·]*$|\[[\s.·]*\]|\.[\s.·]*\.|…/u;
  const DOTTED = /(^|[\s\[\]])\.(\s|$)|\.[\s.·]*\.|…/u;
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
    sapphic: { range: { 1: [10, 12], 2: [10, 12], 3: [10, 12], 4: [4, 6] }, indent: { 4: 1 }, distinctive: { 4: [4, 6] }, required: [4], short: true },
    // The distinctive slot is the one a hendecasyllable can never fill: the adonic, the enneasyllable
    // (a ten-syllable count there is as likely a hendecasyllable with synizesis, so it proves nothing).
    // The Alcaic decasyllable must be seen as well, or glyconic stanzas pass on their eight-syllable lines.
    alcaic: { range: { 1: [10, 12], 2: [10, 12], 3: [8, 10], 4: [9, 11] }, indent: { 3: 1, 4: 2 }, distinctive: { 3: [8, 9] }, required: [3, 4] }
  };

  function plan(lines, metadata, hint) {
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
      // A line with illegible letters (the editors' dots) has no reliable count: it can be too long,
      // or short enough for the adonic, but never reach a long slot on the strength of its traces.
      if (number !== null || GREEK.test(text) || lostLine) verse.push({ index, number, complete: GREEK.test(text) && !INCOMPLETE.test(text), truncated: TRUNCATED.test(text), dotted: DOTTED.test(text), count: syllables(text) });
    });
    // Line numbers fix the order of the rows across gaps, not where the stanza begins: a papyrus
    // fragment's numbering starts at its first surviving line (Sappho 23.3-6 ends in an adonic), so
    // the stanza phase is searched in every case.
    const labelled = verse.some(row => row.number !== null);
    const numbers = phase => verse.map((row, k) => {
      if (!labelled) return k + 1 + phase;
      let anchor = null;
      for (let j = k; j >= 0; j--) if (verse[j].number !== null) { anchor = j; break; }
      if (anchor === null) for (let j = k; j < verse.length; j++) if (verse[j].number !== null) { anchor = j; break; }
      return verse[anchor].number + (k - anchor) + phase;
    });
    // On a tie between the forms (four bracketed lines can fit both), the poet decides.
    const author = String(hint?.author ?? '').toLowerCase();
    const preferred = /sappho|σαπφ/.test(author) ? 'sapphic' : /alcaeus|ἀλκαῖ|αλκαι/.test(author) ? 'alcaic' : null;
    let best = null;
    for (const phase of [0, 1, 2, 3]) {
      const positions = numbers(phase).map(n => ((n - 1) % 4 + 4) % 4 + 1);
      for (const [name, form] of Object.entries(FORMS)) {
        // A complete or restored line is a hit or a miss. A truncated line can only miss (more
        // syllables survive than the slot holds); fewer is no evidence, the rest may be lost. The
        // verdict rests on the complete lines: supplements may not outvote them (Sappho 94's
        // glyconics would otherwise pass as Alcaics on the strength of the lines that happen to fit).
        // A truncated line that already reaches its slot is a hit, one too long is a miss, and one
        // too short for the adonic (the form's one short slot) is half a hit: line-end fragments
        // (Sappho 20) show their adonics only this way. Distinctive evidence from a truncated line
        // counts half for the adonic and nothing for the enneasyllable, so bracketed eight-syllable
        // lines cannot make a glyconic fragment Alcaic (Sappho 95, 98).
        let checked = 0, hits = 0, distinctive = 0, complete = 0, completeHits = 0;
        const slotHits = {};
        verse.forEach((row, k) => {
          const position = positions[k], [low, high] = form.range[position], mark = form.distinctive[position];
          const fits = row.count >= low && row.count <= high;
          const marked = mark && row.count >= mark[0] && row.count <= mark[1];
          if ((row.truncated && row.count < low) || row.dotted) {
            if (row.dotted && row.count > high) { checked++; return; }
            if (form.short && mark && row.count <= mark[1] && GREEK.test(String(rows[row.index]?.text ?? ''))) { checked += 0.5; hits += 0.5; distinctive += 0.5; slotHits[position] = true; }
            return;
          }
          checked++;
          if (row.complete) complete++;
          if (fits) {
            hits++; slotHits[position] = true;
            if (row.complete) completeHits++;
            if (marked) distinctive += !row.truncated ? 1 : form.short ? 0.5 : 0;
          }
        });
        // Three of four lines suffice: a complete-looking line may still be cut short (Sappho 34 "γᾶν").
        if (checked < 3 || distinctive < 1 || hits / checked < 0.75 || form.required.some(slot => !slotHits[slot])) continue;
        if (complete >= 2 && completeHits / complete < 0.75) continue;
        const score = hits / checked + distinctive / 100 + (name === preferred ? 0.001 : 0);
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
