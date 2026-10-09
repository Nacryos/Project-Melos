// Owner private mode loader (release T). Does nothing for visitors: it only asks the API when the
// owner's sign-in marker cookie is present, and loads the owner panels from the URL the API names.
(() => {
  'use strict';
  if (!/(?:^|;\s*)melos_owner_ui=1(?:;|$)/.test(document.cookie)) return;
  const get = path => (window.melosApiFetch ? window.melosApiFetch(path, { credentials: 'same-origin' })
    : fetch(path, { credentials: 'same-origin' }));
  get('/api/owner/session').then(r => (r.ok ? r.json() : null)).then(session => {
    if (!session || !session.signed_in || !/^\/api\/[a-z/]+\.js$/.test(session.ui_script || '')) return;
    const script = document.createElement('script');
    script.src = session.ui_script;
    script.defer = true;
    document.head.append(script);
  }).catch(() => {});
})();
