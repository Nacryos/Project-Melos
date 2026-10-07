import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
const read = file => readFileSync(new URL(`../${file}`, import.meta.url), 'utf8');
const css = read('css/theme.css');

test('shared theme is loaded after reader styles and included in production build', () => {
  for (const page of ['reader.html', 'index.html']) {
    const html = read(page);
    assert.ok(html.indexOf('css/theme.css') > html.indexOf('css/styles.css'));
  }
  assert.ok(read('reader.html').indexOf('css/theme.css') > read('reader.html').indexOf('css/fullscreen.css'));
  assert.match(read('scripts/build_frontend.mjs'), /const cssFiles = .*'theme.css'/);
});

test('controls use square blue and white glass with accessible focus and fallback', () => {
  assert.match(read('js/word-context.js'), /context-action classifier-action/);
  assert.match(css, /--gold: var\(--sea\)/);
  assert.match(css, /--saffron: var\(--sea\)/);
  assert.match(css, /border-radius: 0/);
  assert.match(css, /-webkit-backdrop-filter: blur\(16px\)/);
  assert.match(css, /body :focus-visible \{ outline-color: var\(--sea\)/);
  assert.match(css, /@supports not \(backdrop-filter: blur\(1px\)\)/);
  assert.doesNotMatch(css, /outline:\s*(none|0)|pointer-events:\s*none/);
});

test('theme keeps dark hero controls legible without overriding Greek text or agreement palettes', () => {
  assert.match(css, /body \.hero \.mode-picker input:checked\+span/);
  assert.match(css, /body \.tune input \{ accent-color: #fff/);
  assert.doesNotMatch(css, /interlinear-agreement-\d|\.greek-text \.word\s*\{/);
});

test('original reader is local default and timeline stays preserved as a separate option', () => {
  assert.match(read('tools/serve_timeline_preview.py'), /if path == "\/":\s+path = "\/reader.html"/);
  assert.match(read('local-preview/index.html'), /id="poet-timeline"/);
  assert.match(read('local-preview/index.html'), /id="painting-hero"/);
  assert.match(read('.vercelignore'), /local-preview\//);
});
