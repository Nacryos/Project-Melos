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
  assert.equal(words[0].text, 'α\u0323β\u0301ʼ');
  assert.equal(fold(words[0].text), "αβ'");
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
