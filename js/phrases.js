// "Common phrases" (release P `/api/lemma/ngrams`): two to four headwords that
// recur together, for an author (reader's author list), a headword (lexicon
// page) and a concept's chosen headword (concepts page). Counts and examples
// are the service's; this file only merges, trims and words them.
(() => {
  'use strict';

  const key = item => (Array.isArray(item?.lemmas) ? item.lemmas : []).join(' ');
  const contains = (long, short) => {
    if (long.length <= short.length) return false;
    for (let i = 0; i + short.length <= long.length; i++) if (short.every((word, j) => long[i + j] === word)) return true;
    return false;
  };
  // A phrase inside a longer listed phrase with the same count says nothing
  // new ("πρόσθεν ἄμβροτος" inside "ὅσος δέ πρόσθεν ἄμβροτος", both 6×).
  function trim(items) {
    const list = (Array.isArray(items) ? items : []).filter(item => Array.isArray(item?.lemmas) && item.lemmas.length > 1 && !item.function_only);
    return list.filter(item => !list.some(other => other !== item && Number(other.count) === Number(item.count) && contains(other.lemmas, item.lemmas)));
  }
  // Several groups' lists for one headword merged: one row per phrase, the
  // group where it is most frequent, strongest first.
  function merge(lists) {
    const best = new Map();
    for (const { label, items } of lists) for (const item of trim(items)) {
      const k = key(item), seen = best.get(k);
      if (!seen || Number(item.count) > Number(seen.count)) best.set(k, { ...item, where: label });
    }
    return [...best.values()].sort((a, b) => Number(b.g2) - Number(a.g2) || Number(b.count) - Number(a.count));
  }
  function timesChance(item) {
    const ratio = Number(item.count) / Number(item.expected);
    if (!Number.isFinite(ratio) || ratio < 1.5) return '';
    if (ratio >= 1000) return 'over 1,000× more often than chance';
    return ratio >= 100 ? `${Math.round(ratio).toLocaleString('en-US')}× more often than chance` : `${ratio >= 10 ? Math.round(ratio) : ratio.toFixed(1)}× more often than chance`;
  }
  // The groups that have a phrase list (`/api/lemma/ngrams/groups`), fetched
  // once per page as a Set of "kind|name"; null when unknown (then every
  // group is tried).
  let known = null;
  function knownGroups(load) {
    if (!known) known = Promise.resolve().then(load).then(data => Array.isArray(data?.groups) ? new Set(data.groups.map(group => `${group.kind}|${group.name}`)) : null,
      () => { known = null; return null; });
    return known;
  }
  async function listsFor(groups, { load, fetchGroup }) {
    const have = await knownGroups(load);
    const wanted = groups.filter(group => !have || have.has(`${group.kind}|${group.name}`));
    return Promise.all(wanted.map(group => Promise.resolve().then(() => fetchGroup(group))
      .then(data => ({ label: group.label, items: data?.ngrams || [] }), () => ({ label: group.label, items: [] }))));
  }
  const searchHref = lemmas => `/?q=${encodeURIComponent(lemmas.join(' '))}&mode=lemma`;
  const readerHref = id => `/?id=${encodeURIComponent(id)}`;

  // A list of phrases: each phrase searches for its headwords side by side;
  // "example" opens a passage where it occurs.
  function render(host, items, { node, shown = 8, empty = 'No phrase recurs often enough to list.', highlight = '' } = {}) {
    const make = node || ((tag, cls, text) => { const el = document.createElement(tag); if (cls) el.className = cls; if (text != null) el.textContent = String(text); return el; });
    if (!items.length) { host.append(make('p', 'phrases-empty', empty)); return; }
    const list = make('ol', 'phrases');
    items.forEach((item, index) => {
      const li = make('li', index >= shown ? 'phrase phrase-extra' : 'phrase');
      const a = make('a', 'phrase-words'); a.href = searchHref(item.lemmas); a.lang = 'grc';
      a.title = 'Find every passage with these headwords side by side, in any of their forms';
      item.lemmas.forEach((lemma, i) => {
        if (i) a.append(' ');
        a.append(lemma === highlight ? make('strong', '', lemma) : lemma);
      });
      li.append(a);
      const count = Number(item.count) || 0;
      const meta = [`${count.toLocaleString('en-US')} ${count === 1 ? 'time' : 'times'}${item.where ? ` in ${item.where}` : ''}`, timesChance(item)].filter(Boolean).join(' · ');
      li.append(make('span', 'phrase-meta', ` ${meta}`));
      if (item.example_passage) {
        const example = make('a', 'phrase-example', 'example'); example.href = readerHref(item.example_passage);
        example.title = 'Read a passage where this phrase occurs';
        li.append(' ', example);
      }
      list.append(li);
    });
    host.append(list);
    if (items.length > shown) {
      list.classList.add('collapsed');
      const more = make('button', 'quiet phrases-more', `Show all ${items.length}`); more.type = 'button';
      more.addEventListener('click', () => { const closed = list.classList.toggle('collapsed'); more.textContent = closed ? `Show all ${items.length}` : 'Show fewer'; });
      host.append(more);
    }
  }
  const NOTE = 'Phrases are runs of two to four headwords (any forms) that recur in the edited texts, counted once per text, ranked by how much more often they occur together than chance. Machine-read headwords, so an odd phrase can come from a misread word.';

  window.MelosPhrases = Object.freeze({ trim, merge, timesChance, searchHref, render, knownGroups, listsFor, NOTE });
})();
