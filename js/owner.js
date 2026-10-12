// Owner sign-in page (release T). The API enforces everything; this page only collects the
// name and password and sends them once over HTTPS with a one-use sign-in token.
// Release X.9: a successful sign-in goes straight to the site menu (/#menu, where the owner's entries now show);
// the page itself, when already signed in, offers the composer, the menu and sign-out.
(() => {
  'use strict';
  const $ = id => document.getElementById(id);
  const call = (path, options = {}) => (window.melosApiFetch ? window.melosApiFetch(path, options) : fetch(path, options));
  const status = (text, bad = false) => { $('status').textContent = text; $('status').classList.toggle('bad', bad); };
  let csrf = '';

  async function load() {
    let session = null;
    try {
      const response = await call('/api/owner/session', { credentials: 'same-origin' });
      session = response.ok ? await response.json() : null;
    } catch { session = null; }
    if (!session) { status('Sign-in is not available here.', true); return null; }
    $('login').hidden = session.signed_in;
    $('signed-in').hidden = !session.signed_in;
    if (session.signed_in) {
      csrf = session.csrf;
      $('who').textContent = `Signed in as ${session.username} until ${new Date(session.expires_at * 1000).toLocaleString()}.`;
    } else setTimeout(() => $('username').focus(), 0);
    return session;
  }

  $('login').addEventListener('submit', async event => {
    event.preventDefault();
    status('Signing in…');
    try {
      const tokenResponse = await call('/api/owner/login-token', { credentials: 'same-origin' });
      if (!tokenResponse.ok) throw new Error('Sign-in is not available here.');
      const { token } = await tokenResponse.json();
      const response = await call('/api/owner/login', {
        method: 'POST', credentials: 'same-origin',
        headers: { 'Content-Type': 'application/json', 'X-Melos-CSRF': token },
        body: JSON.stringify({ username: $('username').value, password: $('password').value })
      });
      $('password').value = '';
      const body = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(body.detail || 'Sign-in failed.');
      status('Signed in · opening the menu…');
      const session = await load();
      if (session?.signed_in) location.assign('/#menu');
    } catch (error) {
      status(error.message, true);
    }
  });

  $('logout').addEventListener('click', async () => {
    const response = await call('/api/owner/logout', {
      method: 'POST', credentials: 'same-origin', headers: { 'Content-Type': 'application/json', 'X-Melos-CSRF': csrf }, body: '{}'
    }).catch(() => null);
    status(response && response.ok ? 'Signed out.' : 'Sign-out failed; reload and try again.', !(response && response.ok));
    await load();
  });

  load();
})();
