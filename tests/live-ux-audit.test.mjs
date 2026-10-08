import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

// Guards for the 2026-10-08 live UX audit (docs/audits/live-ux-audit-2026-10-08.md).
const read = path => readFileSync(new URL(`../${path}`, import.meta.url), 'utf8');
const css = read('css/reader.css'), touch = read('css/touch-selection.css');
const reader = read('js/reader.js'), html = read('reader.html');

test('verse line numbers do not make numbered lines taller than the verse', () => {
  assert.match(css, /\.greek-text \.line-label\{line-height:1;vertical-align:baseline\}/);
});

test('disclosure rows, menus and links show that they can be clicked', () => {
  assert.match(css, /\.reader-layout summary,\.reader-layout select,\.utility-bar select,\.mode-picker label\{cursor:pointer\}/);
  assert.match(css, /\.reader-layout summary:hover\{color:var\(--sea\)\}/);
  assert.match(css, /\.reader-layout a\[href\]:hover\{/);
  assert.match(css, /\.selection-start:not\(:disabled\):hover\{/);
});

test('mouse drags across word buttons do not start a native selection, and the mouse toolbar is compact', () => {
  assert.match(css, /\.greek-text\.word-dragging,\.greek-text\.word-dragging \.word\{-webkit-user-select:none;user-select:none\}/);
  assert.match(touch, /@media\(pointer:fine\)\{\.selection-actions\{[^}]*\}\.selection-actions button\{min-height:34px/);
  assert.match(reader, /if \(!state\.passageAnalysis\?\.isDragging\?\.\(\)\) updateSelection\(\)/);
});

test('clicking a word keeps it in place when the selection toolbar appears', () => {
  const click = reader.slice(reader.indexOf("button.addEventListener('click', event => {"), reader.indexOf('      host.append(button);'));
  assert.match(click, /const top = button\.getBoundingClientRect\?\.\(\)\.top;/);
  assert.equal(click.split('holdInView?.(button, top, ui.selectionActions)').length - 1, 2);
});

test('Back and Forward reopen the passage named in the address', () => {
  assert.match(reader, /window\.addEventListener\('popstate', \(\) => \{[\s\S]{0,200}openPassage\(id, false\)/);
});

test('plain labels replace internal identifiers and jargon', () => {
  assert.doesNotMatch(reader, /Ranked by reciprocal rank fusion|ranking is not certainty or influence|Themes: partial/);
  assert.doesNotMatch(reader, /`Open \$\{member\.id\}`/);
  assert.match(html, /title="Look up the word typed in the search box">Look up searched word/);
});

test('comma-joined parse labels from sources are spaced for reading', () => {
  assert.ok(reader.includes("String(candidate.analysis_text).replace(/,(?=\\S)/g, ', ')"));
  assert.ok(reader.includes("String(candidate.analysis).replace(/,(?=\\S)/g, ', ')"));
  assert.equal(String('accusative,dual,feminine').replace(/,(?=\S)/g, ', '), 'accusative, dual, feminine');
});
