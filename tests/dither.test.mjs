import test from 'node:test';
import assert from 'node:assert/strict';
import vm from 'node:vm';
import { readFileSync } from 'node:fs';

const source = readFileSync(new URL('../js/dither.js', import.meta.url), 'utf8');
function controls(width, height, coarse = false) {
  const screen = { width, height, coarse };
  const context = vm.createContext({ matchMedia(query) {
    return { get matches() {
      return query.split(',').some(clause => {
        const maxWidth = clause.match(/max-width: (\d+)px/);
        const maxHeight = clause.match(/max-height: (\d+)px/);
        return (!clause.includes('pointer: coarse') || screen.coarse)
          && (!maxWidth || screen.width <= Number(maxWidth[1]))
          && (!maxHeight || screen.height <= Number(maxHeight[1]));
      });
    } };
  } });
  vm.runInContext(source.replace(/^export /gm, ''), context);
  return { screen, constrain: vm.runInContext('constrainDither', context) };
}
const defaults = { cell: 3, bevel: .5, relief: .6 };

test('phone defaults are 2px in portrait and landscape', () => {
  for (const [width, height] of [[390, 844], [844, 390], [430, 932], [932, 430]]) {
    const result = controls(width, height, true).constrain(defaults);
    assert.equal(result.cell, 2);
    assert.equal(result.bevel, .1);
    assert.equal(result.relief, 0);
  }
});

test('tablet and desktop defaults are 3px, independent of bevel limits', () => {
  for (const [width, height, coarse] of [[1366, 768, false], [800, 450, false],
    [390, 844, false], [1024, 768, true], [1366, 1024, true], [768, 1024, true]]) {
    const result = controls(width, height, coarse).constrain(defaults);
    assert.equal(result.cell, 3, `${width}x${height}, coarse=${coarse}`);
    if (coarse) { assert.equal(result.bevel, .1); assert.equal(result.relief, 0); }
  }
});

test('old tablet defaults migrate; unusual custom settings survive', () => {
  const { constrain } = controls(1024, 768, true);
  assert.equal(constrain({ ...defaults, cell: 2, mobileDefaultsVersion: 1 }).cell, 3);
  assert.equal(constrain({ ...defaults, cell: 6, mobileDefaultsVersion: 1 }).cell, 6);
  assert.equal(constrain({ ...defaults, edge: .9 }).edge, undefined);
});

test('automatic pixels follow profile changes but explicit slider choices survive', () => {
  const { screen, constrain } = controls(390, 844, true);
  let result = constrain(defaults);
  screen.width = 844; screen.height = 390;
  result = constrain(result);
  assert.equal(result.cell, 2);
  screen.width = 1024; screen.height = 768;
  result = constrain(result);
  assert.equal(result.cell, 3);
  result = constrain({ ...result, cell: 2, cellUserSet: true });
  assert.equal(result.cell, 2);
  assert.equal(constrain({ ...result, ...defaults, cellUserSet: false }).cell, 3);
});

test('reader and studio listen to phone changes and retain explicit pixel selection', () => {
  for (const filename of ['reader-hero.js', 'app.js']) {
    const script = readFileSync(new URL(`../js/${filename}`, import.meta.url), 'utf8');
    assert.match(script, /phoneDither\.addEventListener\('change'/);
    assert.match(script, /cellUserSet: true/);
    assert.match(script, /DEFAULTS, cellUserSet: false/);
  }
});

test('dither panel hides scrollbars without disabling scroll or keyboard focus', () => {
  const css = readFileSync(new URL('../css/styles.css', import.meta.url), 'utf8');
  const panel = css.match(/\.tune \{([^}]+)\}/)[1];
  assert.match(panel, /overflow: auto/);
  assert.match(panel, /scrollbar-width: none/);
  assert.match(panel, /backdrop-filter: blur\(28px\)/);
  assert.match(css, /\.tune :focus-visible, \.tune-toggle:focus-visible \{ outline-color: #fff/);
  const controlsCss = css.split('/* Dither controls */')[1].split('/* Lexicon */')[0];
  assert.doesNotMatch(controlsCss, /--saffron/);
});
