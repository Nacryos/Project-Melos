import { copyFile, mkdir, readdir, readFile, rm, writeFile } from 'node:fs/promises';
import { fileURLToPath } from 'node:url';
import path from 'node:path';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const output = path.join(root, 'dist');
const localPreview = process.argv.includes('--local-preview');
const jsFiles = [
  'api.js', 'app.js', 'dither.js', 'images.js', 'reader-hero.js',
  'reader.js', 'studio-live.js', 'usage-space.js'
];
const cssFiles = ['styles.css', 'reader.css'];

function apiOrigin() {
  const raw = (process.env.MELOS_API_ORIGIN || '').trim();
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
  const pages = ['index.html', 'design-studio.html'];
  for (const page of pages) {
    const html = await readFile(path.join(output, page), 'utf8');
    for (const [, ref] of html.matchAll(/(?:src|href)="([^"]+)"/g)) {
      if (/^(?:https?:|#|mailto:|data:)/i.test(ref)) continue;
      if (ref === 'legacy' || ref === './' || ref.startsWith('#')) continue;
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
  const origin = apiOrigin();
  if (path.dirname(output) !== root || path.basename(output) !== 'dist') {
    throw new Error('Refusing to clean an unexpected output path.');
  }
  await rm(output, { recursive: true, force: true });
  await mkdir(output, { recursive: true });
  await copy('reader.html', 'index.html');
  await copy('index.html', 'design-studio.html');
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
    `window.MELOS_API_ORIGIN = ${JSON.stringify(origin)};\n`, 'utf8');
  await verifyLocalAssets();
  const files = await readdir(output, { recursive: true });
  if (files.some(name => /(?:^|[/\\])(?:data|backend|source|reports)(?:[/\\]|$)|\.(?:py|sqlite|jsonl|env)$/i.test(name))) {
    throw new Error('Private corpus or backend file appeared in the frontend artifact.');
  }
  for (const name of files.filter(file => /\.(?:html|css|js)$/.test(file))) {
    const content = await readFile(path.join(output, name), 'utf8');
    if (/\b(?:127\.0\.0\.1|localhost|data\/lexicon\.json|TYPESAFE_API_KEY|JEV_API_KEY)\b/i.test(content)) {
      throw new Error(`Local endpoint, sample-data path, or credential name appeared in frontend file: ${name}`);
    }
  }
  console.log(`Built ${files.length} static paths in dist/ with API origin ${origin || '(same origin local preview)'}.`);
}

main().catch(error => { console.error(error.message); process.exitCode = 1; });
