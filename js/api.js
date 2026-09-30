// Shared API URL resolution for the live corpus reader and the painting studio.
// An empty origin keeps local development on the same host as FastAPI.
(() => {
  'use strict';
  const configured = String(window.MELOS_API_ORIGIN || '').trim();
  const frontendOnly = window.MELOS_FRONTEND_ONLY === true;
  const previewMessage = 'Frontend preview — the corpus service is not connected yet. Search, passages, and contextual analysis are not available on this site yet.';
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
    if (frontendOnly) throw new Error(previewMessage);
    if (!base) throw new Error('The Melos corpus API origin is not configured correctly.');
    if (!String(path).startsWith('/api/')) throw new Error('Only Melos API paths are allowed.');
    return new URL(path, `${base}/`);
  };
  window.melosApiFetch = (path, options) => fetch(window.melosApiUrl(path), options);
  if (frontendOnly) {
    const showNotice = () => {
      const notice = document.createElement('p');
      notice.className = 'hosting-notice';
      notice.setAttribute('role', 'status');
      notice.textContent = previewMessage;
      const form = document.querySelector('.hero-copy form');
      if (form) {
        form.before(notice);
        form.querySelectorAll('input, button').forEach(control => { control.disabled = true; });
      }
    };
    if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', showNotice, { once: true });
    else showNotice();
  }
})();
