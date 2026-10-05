import test from 'node:test';
import assert from 'node:assert/strict';
import vm from 'node:vm';
import { readFileSync } from 'node:fs';
const script = readFileSync(new URL('../js/reader.js', import.meta.url), 'utf8');

test('search API errors preserve literal string limits and fall back safely for nonstring or malformed details', async () => {
  let response;
  const context = vm.createContext({ window: { melosApiUrl: path => new URL(path, 'https://example.test') },
    fetch: async () => response });
  vm.runInContext(script.slice(script.indexOf('  async function api('), script.indexOf('  async function apiPost(')), context);
  const api = vm.runInContext('api', context);
  response = { ok: false, status: 422, json: async () => ({ detail: 'Fixture sequence limit: <b>reduce query</b>.' }) };
  await assert.rejects(api('/api/search'), /422: Fixture sequence limit: <b>reduce query<\/b>\./);
  for (const body of [null, { detail: [{ message: 'field validation' }] }, {}]) {
    response = { ok: false, status: 422, json: async () => body };
    await assert.rejects(api('/api/search'), /The corpus service returned 422\./);
  }
  response = { ok: false, status: 503, json: async () => { throw Error('Malformed'); } };
  await assert.rejects(api('/api/search'), /The corpus service returned 503\./);
});
