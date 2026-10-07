import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

const read = name => readFileSync(new URL(`../${name}`, import.meta.url), 'utf8');
const svg = read('assets/branding/melos-favicon-white.svg');
const original = read('assets/branding/melos-lyre-white.svg');

test('favicon preserves the supplied lyre mask with only white masked paint', () => {
  assert.equal(svg.match(/<image\b[^>]*\/>/)[0], original.match(/<image\b[^>]*\/>/)[0]);
  assert.equal(svg.match(/<filter\b[\s\S]*?<\/filter>/)[0], original.match(/<filter\b[\s\S]*?<\/filter>/)[0]);
  assert.doesNotMatch(svg, /<(?:circle|rect|ellipse|polygon|polyline|line)\b|\bstroke=/);
  assert.deepEqual(svg.match(/<path\b[^>]*\/>/g), [
    '<path fill="#fff" mask="url(#lyre)" d="M232 228h789v789H232z"/>',
  ]);
  assert.match(svg, /style="mask-type:luminance"/);
});

test('square favicon tightly contains the measured silhouette without clipping', () => {
  const [x, y, width, height] = svg.match(/viewBox="([^"]+)"/)[1].split(' ').map(Number);
  // Inclusive pixel bounds of the supplied PNG at the mask's 50% luminance cutoff.
  const bounds = { left: 312, top: 238, right: 942, bottom: 1007 };
  assert.equal(width, height);
  assert.equal(bounds.top - y, 10);
  assert.equal(y + height - bounds.bottom, 10);
  assert.ok(bounds.left > x && bounds.right < x + width);
  assert.ok((bounds.bottom - bounds.top) / height > 0.97);
  assert.match(svg, /maskUnits="userSpaceOnUse" x="232" y="228" width="789" height="789"/);
});

test('both pages reference the new cache-busted favicon and the build ships it', () => {
  for (const page of ['index.html', 'reader.html']) {
    assert.match(read(page), /<link rel="icon" type="image\/svg\+xml" href="assets\/branding\/melos-favicon-white\.svg\?v=white-1">/);
  }
  assert.ok(read('scripts/build_frontend.mjs').includes(
    "await copy('assets/branding/melos-favicon-white.svg', 'assets/branding/melos-favicon-white.svg');",
  ));
});
