// Reproducible raw diagnostic capture; no corpus rows or glosses are authored.
import { writeFile, mkdir } from 'node:fs/promises';
import { createHash } from 'node:crypto';
const url = 'https://greeklyric.com/api/wiktionary?form=%E1%BC%A6%CE%BB%CE%B8%CE%B5%CF%82&limit=8';
const output = new URL('../tests/fixtures/wiktionary-elthes-live.json', import.meta.url);
const response = await fetch(url, { signal: AbortSignal.timeout(50000) });
if (!response.ok) throw new Error(`Fixture download failed: HTTP ${response.status}`);
const raw = Buffer.from(await response.arrayBuffer());
const body = JSON.parse(raw.toString('utf8'));
if (!body.ready || body.query !== new URL(url).searchParams.get('form') || !Array.isArray(body.results)) throw new Error('Unexpected fixture response');
await mkdir(new URL('../tests/fixtures/', import.meta.url), { recursive: true });
await writeFile(output, raw);
await writeFile(new URL('../tests/fixtures/wiktionary-elthes-live.receipt.json', import.meta.url), JSON.stringify({
  url, captured_at: new Date().toISOString(), http_status: response.status,
  sha256: createHash('sha256').update(raw).digest('hex'), bytes: raw.length,
  purpose: 'Raw API regression fixture, not scholarly gold or corpus additions'
}, null, 2) + '\n');
console.log(`Captured ${raw.length} bytes; ${body.results.length} source entries`);
