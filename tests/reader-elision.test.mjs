import test from 'node:test';
import assert from 'node:assert/strict';
import vm from 'node:vm';
import { readFileSync } from 'node:fs';

// Synthetic Greek letter sequences test mechanics only, not literary claims.
const source = readFileSync(new URL('../js/reader.js', import.meta.url), 'utf8');
class Element {
  constructor(tag, cls = '', text = '') { Object.assign(this, { tag, cls, text, children: [] }); }
  append(...children) { this.children.push(...children); }
  get textContent() { return this.text + this.children.map(child => child.textContent).join(''); }
}
const context = vm.createContext({
  node: (tag, cls, text) => new Element(tag, cls, text),
  addInspectorSection(title, host) { const section = new Element('section', '', title); host.append(section); return section; },
  safeLink() { return null; },
});
vm.runInContext(source.slice(source.indexOf('  function literalGreekWords('), source.indexOf('  function appendTextWithWords('))
  + source.slice(source.indexOf('  function foldGreekForm('), source.indexOf('  function formatFeatures(')), context);
const literal = vm.runInContext('literalGreekWords', context);
const reading = vm.runInContext('readingWords', context);
const fold = vm.runInContext('foldGreekForm', context);
const render = vm.runInContext('renderRelatedCommentary', context);
function mention(form, text) {
  const host = new Element('aside');
  render(form, [{ kind: 'commentary', text }], host);
  return host;
}

test('all four single terminal apostrophes match source commentary without changing its spelling', () => {
  for (const queryMark of ["'", '’', '᾽', 'ʼ']) {
    for (const sourceMark of ["'", '’', '᾽', 'ʼ']) {
      const text = `αβ${sourceMark} = αβγ`;
      const host = mention(`αβ${queryMark}`, text);
      assert.equal(host.children.length, 1, `${queryMark} / ${sourceMark}`);
      assert.ok(host.textContent.includes(text));
      assert.equal(literal(text)[0].form, `αβ${sourceMark}`);
    }
  }
});

test('unelided, extended and internal-apostrophe forms are not partial terminal matches', () => {
  for (const text of ['αβ', 'αβγ', 'αβ’γ', 'xαβ’', 'αβ’x', 'αxβ’']) {
    assert.equal(mention('αβ’', text).children.length, 0, text);
  }
  assert.equal(mention('αβ', 'αβ’').children.length, 0);
  assert.equal(mention('αβ’γ', 'αβʼγ').children.length, 1);
});

test('combining marks stay attached, source offsets remain exact, and sigma folds consistently', () => {
  const text = '🪶 [α\u0323β\u0301ʼ] · γς';
  const words = literal(text);
  assert.equal(words.length, 2);
  for (const word of words) assert.equal(text.slice(word.start, word.end), word.text);
  // The editorial brackets touch the letters, so they belong to the printed unit.
  assert.equal(words[0].text, '[α\u0323β\u0301ʼ]');
  assert.equal(fold(words[0].text.slice(1, -1)), "αβ'");
  assert.equal(fold('ΓΣ'), fold('γς'));
  assert.equal(mention('αβ’', text).children.length, 1);
  assert.equal(literal('\u0323 · ; ᾽ ʼ ’ \'').length, 0);
});

test('double apostrophes preserve the first terminal mark and never bridge the boundary', () => {
  for (const mark of ["'", '’', '᾽', 'ʼ']) {
    const words = literal(`αβ${mark}${mark}γδ`);
    assert.equal(words.map(word => word.form).join('|'), `αβ${mark}|γδ`);
    assert.equal(mention('αβ’γδ', `αβ${mark}${mark}γδ`).children.length, 0);
    assert.equal(mention('αβ’', `αβ${mark}${mark}γδ`).children.length, 1);
  }
});

test('commentary preview never joins across lacunae, spaces or line divisions', () => {
  for (const text of ['αβ γδ', 'αβ[.]γδ', 'αβ-\nγδ', 'αβ\nγδ']) {
    assert.equal(mention('αβγδ', text).children.length, 0, text);
  }
  assert.equal(reading('αβ-\nγδ')[0].form, 'αβγδ');
  assert.equal(reading('αβʼ-\nγδ')[0].form, 'αβʼ');
});

test('spacing psili remains a distinct attached printed sign, not an apostrophe alias', () => {
  const form = 'αβ\u1fbf';
  const text = `🪶 [${form}] = γδ`;
  const word = literal(text)[0];
  assert.equal(word.form, `[${form}]`);
  assert.equal(text.slice(word.start, word.end), `[${form}]`);
  assert.equal(mention(form, text).children.length, 1);
  assert.ok(mention(form, text).textContent.includes(text));
  assert.equal(fold(form), form);
  for (const other of ['αβ', "αβ'", 'αβ’', 'αβ᾽', 'αβʼ']) {
    assert.notEqual(fold(form), fold(other));
    assert.equal(mention(other, text).children.length, 0);
    assert.equal(mention(form, other).children.length, 0);
  }
});

test('internal spacing psili is preserved without matching a partial or unmarked word', () => {
  const form = 'αβ\u1fbfγδ';
  assert.equal(literal(form)[0].form, form);
  assert.equal(mention(form, form).children.length, 1);
  for (const other of ['αβ', 'γδ', 'αβ\u1fbf', 'αβγδ', 'αβ’γδ']) {
    assert.equal(mention(other, form).children.length, 0, other);
  }
});

test('orphan spacing signs create no word units and attached signs block line joining', () => {
  assert.equal(literal('\u1fbf · \u1fbf \u0323').length, 0);
  const leading = literal('\u1fbfαβ');
  assert.equal(leading.length, 1);
  assert.equal(leading[0].form, 'αβ');
  assert.equal(leading[0].start, 1);
  const doubled = literal('αβ\u1fbf\u1fbfγδ');
  assert.equal(doubled.map(word => word.form).join('|'), 'αβ\u1fbf|γδ');
  const divided = reading('αβ\u1fbf-\nγδ');
  assert.equal(divided[0].form, 'αβ\u1fbf');
  assert.ok(divided.every(word => !word.joined));
  assert.equal(mention('αβ\u1fbfγδ', 'αβ\u1fbf-\nγδ').children.length, 0);
});

test('literal form matches in source-section notes disclose nonalignment without changing the match', () => {
  const host = new Element('aside');
  render('αβ’', [{ kind: 'commentary', text: 'αβʼ = γδ', citation: 'Fixture citation', metadata: { scope: 'source_section', source_heading: 'Fixture heading', source_section: 'Column A' } }], host);
  assert.equal(host.children.length, 1);
  assert.match(host.textContent, /Source-section note; not aligned to the selected passage/);
  assert.match(host.textContent, /Source section \/ citation: Fixture heading · Column A · Fixture citation/);
  assert.match(host.textContent, /related source commentary; each note retains its source scope/);
  assert.ok(!host.textContent.includes('commentary linked to this passage'));
  assert.ok(host.textContent.includes('αβʼ = γδ'));
  const noMatch = new Element('aside');
  render('αβ', [{ kind: 'commentary', text: 'αβʼ = γδ', metadata: { scope: 'source_section' } }], noMatch);
  assert.equal(noMatch.children.length, 0);
});
