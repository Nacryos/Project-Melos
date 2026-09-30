import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

test('collection note scrolls with the authors instead of reserving a bottom shelf', () => {
  const html = readFileSync(new URL('../reader.html', import.meta.url), 'utf8');
  assert.match(html, /id="browse-body"[^]*?id="author-list"[^]*?<\/div><div class="browse-foot"[^]*?<\/div><\/div><\/aside>/);
  const css = readFileSync(new URL('../css/reader.css', import.meta.url), 'utf8');
  assert.match(css, /height:calc\(100dvh - 24px - env\(safe-area-inset-bottom,0px\)\)/);
  assert.match(css, /\.corpus-panel \.browse-body\{flex:1;min-height:0;max-height:none\}/);
});

test('reader links have themed visited states and use local SVG line icons', () => {
  const html = readFileSync(new URL('../reader.html', import.meta.url), 'utf8');
  const css = readFileSync(new URL('../css/reader.css', import.meta.url), 'utf8');
  const icons = readFileSync(new URL('../js/ui-icons.js', import.meta.url), 'utf8');
  assert.match(html, /src="js\/ui-icons.js"/);
  assert.match(css, /\.reader-layout a:visited[^}]*color:var\(--ink\)/);
  assert.match(icons, /createElementNS\('http:\/\/www.w3.org\/2000\/svg', 'svg'\)/);
  assert.doesNotMatch(html, /[\u{1F300}-\u{1FAFF}]/u);
});
