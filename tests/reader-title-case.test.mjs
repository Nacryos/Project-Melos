import test from 'node:test';
import assert from 'node:assert/strict';
import vm from 'node:vm';
import { readFileSync } from 'node:fs';

const source = readFileSync(new URL('../js/reader.js', import.meta.url), 'utf8');
const start = source.indexOf('  function formatPassageTitlePart(');
const end = source.indexOf('  async function openPassage(', start);
const context = vm.createContext({});
vm.runInContext(source.slice(start, end), context);

test('Greek headings use sentence case, including final sigma', () => {
  assert.equal(context.formatPassageTitlePart('ΙΒΥΚΟΣ'), 'Ιβυκος');
  assert.equal(context.formatPassageTitlePart('ΜΕΛΙΚΟΙ ΠΟΙΗΤΕΣ (μονωδία και χορικό άσμα)'), 'Μελικοι ποιητες (μονωδία και χορικό άσμα)');
});
test('title presentation retains supplied accents without adding missing ones', () => {
  assert.equal(context.formatPassageTitlePart('ἜΡΩΣ'), 'Ἔρως');
  assert.equal(context.formatPassageTitlePart('ΣΑΠΦΩ'), 'Σαπφω');
  assert.equal(context.formatPassageTitlePart('Sappho · Collected Fragments'), 'Sappho · Collected Fragments');
});
test('formatting is restricted to the displayed passage heading', () => {
  assert.match(source, /\[passage\.display_author \|\| passage\.author, passage\.display_work \|\| passage\.work\]\.filter\(Boolean\)\.map\(formatPassageTitlePart\)/);
});
