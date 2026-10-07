import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

const svg = readFileSync(new URL('../assets/branding/melos-loading.svg', import.meta.url), 'utf8');
const css = readFileSync(new URL('../css/loading.css', import.meta.url), 'utf8');

test('lyre rotates clockwise in 24 discrete poses over 2.4 seconds', () => {
  assert.match(svg, /animation:turn 2\.4s steps\(24,end\) infinite/);
  assert.match(svg, /from\{transform:rotate\(0deg\)\}to\{transform:rotate\(360deg\)\}/);
  assert.doesNotMatch(svg, /scaleX|rotateY|perspective/);
});
test('five staggered notes accompany the rotation', () => {
  assert.equal((svg.match(/class="note note-/g) || []).length, 5);
  assert.match(svg, /animation-delay:-1\.92s/);
});
test('reduced-motion users keep a still lyre and cached images get a new URL', () => {
  assert.match(svg, /prefers-reduced-motion:reduce/);
  assert.match(css, /prefers-reduced-motion: reduce/);
  assert.match(css, /melos-loading-still\.svg/);
  assert.match(css, /melos-loading\.svg\?v=clockwise-24/);
});
