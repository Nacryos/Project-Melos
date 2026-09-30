// Shared API URL resolution for the live corpus reader and the painting studio.
// An empty origin keeps local development on the same host as FastAPI.
(() => {
  'use strict';
  const configured = String(window.MELOS_API_ORIGIN || '').trim();
  let base = location.origin;
  if (configured) {
    try {
      const parsed = new URL(configured);
      if (!['https:', 'http:'].includes(parsed.protocol) || parsed.pathname !== '/' || parsed.search || parsed.hash) throw new Error('Expected an API origin without a path.');
      base = parsed.origin;
    } catch (error) {
      console.error('Melos API origin is invalid:', error);
      base = null;
    }
  }
  window.melosApiUrl = path => {
    if (!base) throw new Error('The Melos corpus API origin is not configured correctly.');
    if (!String(path).startsWith('/api/')) throw new Error('Only Melos API paths are allowed.');
    return new URL(path, `${base}/`);
  };
  window.melosApiFetch = (path, options) => fetch(window.melosApiUrl(path), options);
})();
