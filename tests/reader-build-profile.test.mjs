import test from 'node:test';
import assert from 'node:assert/strict';
import { cp, mkdir, mkdtemp, readFile, readdir, rm, writeFile } from 'node:fs/promises';
import { spawnSync } from 'node:child_process';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const root = fileURLToPath(new URL('..', import.meta.url));

test('reader-only release excludes discovery without changing the full local build', async t => {
  // Build a real isolated copy so parallel frontend tests and release staging can
  // use the repository dist directory without racing this profile test.
  const fixture = await mkdtemp(path.join(tmpdir(), 'melos-reader-profile-'));
  t.after(async () => {
    assert.equal(path.dirname(fixture), path.resolve(tmpdir()));
    assert.ok(path.basename(fixture).startsWith('melos-reader-profile-'));
    await rm(fixture, { recursive: true, force: true });
  });
  await mkdir(path.join(fixture, 'scripts'));
  await cp(path.join(root, 'scripts/build_frontend.mjs'), path.join(fixture, 'scripts/build_frontend.mjs'));
  for (const entry of ['reader.html', 'index.html', 'lemma.html', 'concept.html', 'about.html', 'owner.html', 'lexicon.html', 'authors.html', 'themes.html', 'js', 'css', 'assets/branding', 'assets/authors', 'assets/nature-presets', 'assets/paintings']) {
    await cp(path.join(root, entry), path.join(fixture, entry), { recursive: true });
  }
  const originalReader = await readFile(path.join(fixture, 'reader.html'), 'utf8');
  const run = (args = [], extraEnv = {}) => spawnSync(process.execPath, ['scripts/build_frontend.mjs', ...args], {
    cwd: fixture, encoding: 'utf8', env: {
      ...process.env, MELOS_API_ORIGIN: 'https://api.example.com', MELOS_FRONTEND_ONLY: '', MELOS_READER_ONLY: '', VERCEL: '', ...extraEnv,
    },
  });
  const readOutput = name => readFile(path.join(fixture, 'dist', name), 'utf8');
  const checkReader = async () => {
    const html = await readOutput('index.html');
    assert.doesNotMatch(html, /discovery-(?:nav|door|number)|href="\/(?:lexicon|authors|themes)/);
    assert.ok(html.includes('id="reader"'));
    assert.ok(html.includes('id="passage"'));
    assert.ok(html.includes('js/reader.js'));
    assert.match(await readOutput('js/config.js'), /MELOS_FRONTEND_ONLY = false/);
    const paths = (await readdir(path.join(fixture, 'dist'), { recursive: true })).map(name => name.replaceAll('\\', '/'));
    for (const name of ['lexicon', 'authors', 'themes']) {
      assert.ok(!paths.includes(`${name}.html`));
      assert.ok(!paths.includes(`js/${name}-page.js`));
      assert.ok(!paths.includes(`css/${name}-page.css`));
    }
    assert.ok(!paths.some(name => name === 'assets/authors' || name.startsWith('assets/authors/')));
    assert.ok(!paths.includes('css/discovery-nav.css'));
    // The Lexicon (headword) and Concepts pages ship in the reader-only release.
    for (const name of ['lemma.html', 'concept.html', 'js/lemma-common.js', 'js/lemma-page.js', 'js/concept-page.js', 'css/lemma-page.css', 'owner.html', 'js/owner.js', 'js/owner-loader.js']) assert.ok(paths.includes(name), name);
    assert.equal(await readFile(path.join(fixture, 'reader.html'), 'utf8'), originalReader);
  };

  await t.test('default build retains all discovery pages and unmodified reader HTML', async () => {
    const result = run();
    assert.equal(result.status, 0, result.stderr);
    assert.equal(await readOutput('index.html'), originalReader);
    for (const page of ['lexicon', 'authors', 'themes']) assert.ok((await readOutput(`${page}.html`)).includes('<html'));
    assert.ok((await readdir(path.join(fixture, 'dist/assets/authors'))).length > 0);
  });

  await t.test('flag removes discovery and clears assets left by a full build', async () => {
    const result = run(['--reader-only']);
    assert.equal(result.status, 0, result.stderr);
    assert.match(result.stdout, /reader-only profile/);
    await checkReader();
    assert.match(await readOutput('js/config.js'), /MELOS_API_ORIGIN = "https:\/\/api.example.com"/);
  });

  await t.test('environment profile preserves same-origin API on Vercel', async () => {
    const result = run([], { MELOS_READER_ONLY: '1', VERCEL: '1' });
    assert.equal(result.status, 0, result.stderr);
    await checkReader();
    assert.match(await readOutput('js/config.js'), /MELOS_API_ORIGIN = ""/);
  });

  await t.test('unknown nav markup fails closed', async () => {
    await writeFile(path.join(fixture, 'reader.html'), originalReader.replace('class="discovery-nav"', 'class="discovery-nav changed"'));
    const result = run(['--reader-only']);
    assert.notEqual(result.status, 0);
    assert.match(result.stderr, /expected exactly one discovery stylesheet and navigation block/);
  });

  await t.test('discovery links outside the removed block fail closed', async () => {
    await writeFile(path.join(fixture, 'reader.html'), originalReader.replace('</body>', '<a href="/authors">Authors</a></body>'));
    const result = run(['--reader-only']);
    assert.notEqual(result.status, 0);
    assert.match(result.stderr, /Discovery navigation appeared/);
  });
});
