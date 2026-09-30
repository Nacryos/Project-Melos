import test from 'node:test';
import assert from 'node:assert/strict';
import vm from 'node:vm';
import { readFileSync } from 'node:fs';
import { spawnSync } from 'node:child_process';

const source = readFileSync(new URL('../js/api.js', import.meta.url), 'utf8');
function apiContext(config = {}) {
  const window = { ...config };
  const context = vm.createContext({ window, URL, location: { origin: 'https://greeklyric.com' }, console,
    document: { readyState: 'loading', addEventListener() {} },
    fetch() { throw new Error('Unexpected network request'); }
  });
  vm.runInContext(source, context);
  return window;
}
test('local default keeps same-origin API behavior', () => {
  assert.equal(apiContext().melosApiUrl('/api/status').href, 'https://greeklyric.com/api/status');
});
test('configured origin routes API requests to the separate host', () => {
  assert.equal(apiContext({ MELOS_API_ORIGIN: 'https://api.example.com' }).melosApiUrl('/api/status').href, 'https://api.example.com/api/status');
});

test('production API proxy targets only Melos and disables response caching', () => {
  const config = JSON.parse(readFileSync(new URL('../vercel.json', import.meta.url), 'utf8'));
  const apiRoutes = config.rewrites.filter(route => route.source.startsWith('/api'));
  assert.deepEqual(apiRoutes, [{ source: '/api/:path*', destination: 'https://basecamp.taila44c41.ts.net:8443/api/:path*' }]);
  const headers = config.headers.find(rule => rule.source === '/api/(.*)').headers;
  assert.ok(headers.some(header => header.key === 'Cache-Control' && header.value === 'no-store'));
  assert.equal(apiContext({ MELOS_API_ORIGIN: 'https://greeklyric.com' }).melosApiUrl('/api/status').href,
    'https://greeklyric.com/api/status');
});
test('frontend-only mode prevents all API network calls', () => {
  const api = apiContext({ MELOS_FRONTEND_ONLY: true });
  assert.throws(() => api.melosApiUrl('/api/status'), /corpus service is not connected/);
  assert.throws(() => api.melosApiFetch('/api/classify-context'), /corpus service is not connected/);
});
test('non-API paths are rejected', () => {
  assert.throws(() => apiContext().melosApiUrl('/data/private'), /Only Melos API paths/);
});
test('production build guards and explicit frontend-only artifact', () => {
  const build = (extra = {}) => spawnSync(process.execPath, ['scripts/build_frontend.mjs'], {
    cwd: new URL('..', import.meta.url), encoding: 'utf8',
    env: { ...process.env, MELOS_API_ORIGIN: '', MELOS_FRONTEND_ONLY: '', ...extra }
  });
  assert.notEqual(build().status, 0);
  assert.notEqual(build({ MELOS_API_ORIGIN: 'http://localhost:8791' }).status, 0);
  assert.notEqual(build({ MELOS_FRONTEND_ONLY: '1', MELOS_API_ORIGIN: 'https://api.example.com' }).status, 0);
  const result = build({ MELOS_FRONTEND_ONLY: '1' });
  assert.equal(result.status, 0, result.stderr);
  const config = readFileSync(new URL('../dist/js/config.js', import.meta.url), 'utf8');
  assert.match(config, /MELOS_FRONTEND_ONLY = true/);
  assert.match(config, /MELOS_API_ORIGIN = ""/);
});
