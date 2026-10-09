import { copyFile, mkdir, readdir, readFile, rm, writeFile } from 'node:fs/promises';
import { fileURLToPath } from 'node:url';
import path from 'node:path';
import { existsSync } from 'node:fs';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const output = path.join(root, 'dist');
const localPreview = process.argv.includes('--local-preview');
const frontendOnly = process.env.MELOS_FRONTEND_ONLY === '1';
const readerOnly = process.argv.includes('--reader-only') || process.env.MELOS_READER_ONLY === '1';
const discoveryPages = ['lexicon', 'authors', 'themes'];
const toolPages = ['lemma.html', 'concept.html', 'about.html', 'owner.html', 'composer.html'];
const pages = ['index.html', 'design-studio.html', ...toolPages, ...(readerOnly ? [] : discoveryPages.map(page => `${page}.html`))];
const excerptPages = ['34a', '129', '130b', '326', '350'].map(id => `sources/campbell-alcaeus/${id}.html`);
const includeExcerpts = existsSync(path.join(root, 'sources/campbell-alcaeus'));
if (includeExcerpts) pages.push(...excerptPages);
const jsFiles = [
  'api.js', 'app.js', 'dither.js', 'images.js', 'reader-hero.js', 'reader-fullscreen.js',
  'reader.js', 'word-panel.js', 'word-context.js', 'studio-live.js', 'usage-space.js', 'ui-icons.js', 'verse-fit.js', 'dictionary-preview.js', 'machine-morphology.js', 'passage-analysis.js', 'nature-preset-data.js', 'nature-presets.js',
  'lemma-common.js', 'lemma-page.js', 'concept-page.js', 'citation-lookup.js', 'phrases.js', 'site-menu.js', 'owner-loader.js', 'owner.js', 'typegreek.js', 'composer.js', 'reader-scansion.js'
];
if (!readerOnly) jsFiles.push('lexicon-page.js', 'authors-page.js', 'themes-page.js');
const cssFiles = ['styles.css', 'reader.css', 'icons.css', 'loading.css', 'fullscreen.css', 'touch-selection.css', 'theme.css', 'lemma-page.css', 'site-menu.css', 'scansion.css', 'composer.css'];
if (!readerOnly) cssFiles.push('discovery-nav.css', 'lexicon-page.css', 'authors-page.css', 'themes-page.css');

function assertNoDiscovery(html, page) {
  if (/discovery-(?:nav|door|number)|(?:src|href)\s*=\s*["'](?:\.?\/)?(?:lexicon|authors|themes)(?:\.html)?(?:[/?#"'])/i.test(html)) {
    throw new Error(`Discovery navigation appeared in reader-only page: ${page}`);
  }
}

function readerOnlyHtml(html) {
  // Fail closed if the discovery markup changes: never silently ship new doors.
  const stylesheet = /^[ \t]*<link rel="stylesheet" href="css\/discovery-nav\.css">\r?\n/gm;
  const navigation = /^[ \t]*<nav class="discovery-nav" aria-label="Explore Melos">[\s\S]*?<\/nav>\r?\n/gm;
  if ([...html.matchAll(stylesheet)].length !== 1 || [...html.matchAll(navigation)].length !== 1) {
    throw new Error('Reader-only build expected exactly one discovery stylesheet and navigation block. Review reader.html before releasing.');
  }
  const reader = html.replace(stylesheet, '').replace(navigation, '');
  assertNoDiscovery(reader, 'index.html');
  return reader;
}

function apiOrigin() {
  const raw = (process.env.MELOS_API_ORIGIN || '').trim();
  if (frontendOnly) {
    if (raw || localPreview) throw new Error('MELOS_FRONTEND_ONLY cannot be combined with an API origin or local preview.');
    return '';
  }
  if (!raw) {
    if (localPreview) return '';
    throw new Error('MELOS_API_ORIGIN is required for the production frontend build. It must be the public HTTPS origin of the separate Melos API.');
  }
  let parsed;
  try { parsed = new URL(raw); } catch { throw new Error('MELOS_API_ORIGIN must be an absolute HTTPS origin.'); }
  if (parsed.protocol !== 'https:' || !parsed.hostname || parsed.username || parsed.password ||
      parsed.pathname !== '/' || parsed.search || parsed.hash ||
      ['localhost', '127.0.0.1', '::1', '[::1]'].includes(parsed.hostname.toLowerCase())) {
    throw new Error('MELOS_API_ORIGIN must be a public HTTPS origin without a path, credentials, query, or fragment.');
  }
  return parsed.origin;
}

async function copy(source, destination) {
  const dest = path.join(output, destination);
  await mkdir(path.dirname(dest), { recursive: true });
  await copyFile(path.join(root, source), dest);
}

async function verifyLocalAssets() {
  for (const page of pages) {
    const html = await readFile(path.join(output, page), 'utf8');
    if (readerOnly) assertNoDiscovery(html, page);
    for (const [, ref] of html.matchAll(/(?:src|href)="([^"]+)"/g)) {
      if (/^(?:https?:|#|mailto:|data:)/i.test(ref)) continue;
      if (ref === 'legacy' || ref === './' || ref.startsWith('#')) continue;
      if (/^\/(?:reader\.html)?(?:[?#].*)?$/.test(ref)) continue;
      if (!readerOnly && /^\/(?:lexicon|authors|themes)(?:[?#].*)?$/.test(ref)) continue;
      const file = path.join(output, ref.split(/[?#]/, 1)[0]);
      if (!file.startsWith(output + path.sep)) throw new Error(`Unsafe asset reference in ${page}: ${ref}`);
      try { await readFile(file); } catch { throw new Error(`Missing asset referenced by ${page}: ${ref}`); }
    }
  }
  for (const name of jsFiles) {
    const content = await readFile(path.join(output, 'js', name), 'utf8');
    for (const [, ref] of content.matchAll(/\bimport(?:\s+(?:[^'"`]*?\s+from\s*)?|\s*\()\s*['"`]([.][^'"`]+\.js)['"`]/g)) {
      const destination = path.resolve(output, 'js', ref);
      if (!destination.startsWith(path.join(output, 'js') + path.sep)) throw new Error(`Unsafe module import in ${name}: ${ref}`);
      try { await readFile(destination); } catch { throw new Error(`Missing module imported by ${name}: ${ref}`); }
    }
  }
  for (const name of ['reader.js', 'studio-live.js', 'usage-space.js']) {
    const content = await readFile(path.join(output, 'js', name), 'utf8');
    if (!/melosApi(?:Url|Fetch)/.test(content)) throw new Error(`API origin helper missing from ${name}.`);
  }
}

async function main() {
  const configuredOrigin = apiOrigin();
  // Every Vercel deployment has its own /api rewrite. Stay on that origin so
  // protected previews never make cross-origin requests to the production site.
  const origin = process.env.VERCEL === '1' && !frontendOnly ? '' : configuredOrigin;
  if (path.dirname(output) !== root || path.basename(output) !== 'dist') {
    throw new Error('Refusing to clean an unexpected output path.');
  }
  await rm(output, { recursive: true, force: true });
  await mkdir(output, { recursive: true });
  if (readerOnly) {
    await writeFile(path.join(output, 'index.html'), readerOnlyHtml(await readFile(path.join(root, 'reader.html'), 'utf8')), 'utf8');
  } else {
    await copy('reader.html', 'index.html');
  }
  await copy('index.html', 'design-studio.html');
  for (const page of toolPages) await copy(page, page);
  if (includeExcerpts) {
    for (const page of excerptPages) await copy(page, page);
    for (const item of await readdir(path.join(root, 'assets/edition-excerpts'), { withFileTypes: true })) {
      if (!item.isFile() || !/^alcaeus-(?:34a|129|130b|326|350)-p[0-9]+-[a-z-]+\.[a-f0-9]{12}\.png$/.test(item.name)) {
        throw new Error(`Unexpected edition excerpt asset: ${item.name}`);
      }
      await copy(`assets/edition-excerpts/${item.name}`, `assets/edition-excerpts/${item.name}`);
    }
  }
  if (!readerOnly) {
    for (const page of discoveryPages) await copy(`${page}.html`, `${page}.html`);
    for (const item of await readdir(path.join(root, 'assets/authors'), { withFileTypes: true })) {
      if (!item.isFile() || !/^[a-z0-9_.-]+\.(?:jpg|jpeg|png|webp|json)$/.test(item.name)) throw new Error(`Unexpected author asset: ${item.name}`);
      await copy(`assets/authors/${item.name}`, `assets/authors/${item.name}`);
    }
  }
  await copy('assets/branding/melos-lyre.png', 'assets/branding/melos-lyre.png');
  await copy('assets/branding/melos-lyre-circle.svg', 'assets/branding/melos-lyre-circle.svg');
  await copy('assets/branding/melos-loading.svg', 'assets/branding/melos-loading.svg');
  await copy('assets/branding/melos-loading-still.svg', 'assets/branding/melos-loading-still.svg');
  await copy('assets/branding/melos-lyre-white.svg', 'assets/branding/melos-lyre-white.svg');
  await copy('assets/branding/melos-favicon-white.svg', 'assets/branding/melos-favicon-white.svg');
  for (const item of await readdir(path.join(root, 'assets/nature-presets'), { withFileTypes: true })) {
    if (!item.isFile() || !/^[a-z0-9_-]+\.[a-f0-9]{8,64}\.(?:webp|json)$/.test(item.name)) {
      throw new Error(`Unexpected nature-preset asset: ${item.name}`);
    }
    await copy(`assets/nature-presets/${item.name}`, `assets/nature-presets/${item.name}`);
  }
  for (const name of cssFiles) await copy(`css/${name}`, `css/${name}`);
  for (const name of jsFiles) await copy(`js/${name}`, `js/${name}`);
  const imageDir = path.join(root, 'assets', 'paintings');
  for (const item of await readdir(imageDir, { withFileTypes: true })) {
    if (!item.isFile() || !/^[a-z0-9-]+\.[a-f0-9]{8}\.(?:avif|webp)$/.test(item.name)) {
      throw new Error(`Unexpected file in served painting assets: ${item.name}`);
    }
    await copy(`assets/paintings/${item.name}`, `assets/paintings/${item.name}`);
  }
  await writeFile(path.join(output, 'js', 'config.js'),
    `window.MELOS_API_ORIGIN = ${JSON.stringify(origin)};\nwindow.MELOS_FRONTEND_ONLY = ${frontendOnly};\n`, 'utf8');
  await verifyLocalAssets();
  const files = await readdir(output, { recursive: true });
  if (readerOnly && files.some(name => /^(?:(?:lexicon|authors|themes)\.html|assets[/\\]authors(?:[/\\]|$)|css[/\\](?:discovery-nav|(?:lexicon|authors|themes)-page)\.css|js[/\\](?:lexicon|authors|themes)-page\.js)$/.test(name))) {
    throw new Error('Discovery assets appeared in the reader-only frontend artifact.');
  }
  if (files.some(name => /(?:^|[/\\])(?:data|backend|source|reports)(?:[/\\]|$)|\.(?:py|sqlite|jsonl|env)$/i.test(name))) {
    throw new Error('Private corpus or backend file appeared in the frontend artifact.');
  }
  for (const name of files.filter(file => /\.(?:html|css|js)$/.test(file))) {
    const content = await readFile(path.join(output, name), 'utf8');
    if (/\b(?:127\.0\.0\.1|localhost|data\/lexicon\.json|TYPESAFE_API_KEY|JEV_API_KEY)\b/i.test(content)) {
      throw new Error(`Local endpoint, sample-data path, or credential name appeared in frontend file: ${name}`);
    }
  }
  console.log(`Built ${files.length} static paths in dist/ (${readerOnly ? 'reader-only' : 'full'} profile) with API origin ${origin || (frontendOnly ? '(frontend preview; corpus service not connected)' : '(same origin local preview)')}.`);
}

main().catch(error => { console.error(error.message); process.exitCode = 1; });
