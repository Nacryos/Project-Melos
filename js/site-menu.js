/* Site menu: one hamburger button at the top of every page opens a panel with every Melos destination. */
(() => {
  'use strict';
  // Private mode (/owner) is not released yet. Set to true once it ships; until then Log in
  // checks that /owner answers 200 and otherwise says owner login is not available yet.
  const OWNER_LOGIN_LIVE = false;
  const button = document.getElementById('site-menu-button');
  if (!button) return;

  const FEATURES = [
    ['Reader', '/', 'Read the poems and click any word'],
    ['Poets & works', '/#collection', 'Browse the collection by poet'],
    ['Lexicon', '/lexicon', 'One headword: dictionaries, counts, every use'],
    ['Concepts', '/concepts', 'Follow a meaning through time'],
    ['Search', '/#search', 'Greek, English, or a passage reference'],
    ['Scansion', null, 'Coming soon'],
    ['Composer', null, 'Coming soon'],
  ];
  const ALIASES = { '/index': '/', '/reader': '/', '/lemma': '/lexicon', '/concept': '/concepts', '/design-studio': '/legacy' };
  const path = location.pathname.replace(/\.html$/, '').replace(/\/$/, '') || '/';
  const here = ALIASES[path] || path;

  const el = (tag, props = {}, ...children) => {
    const node = document.createElement(tag);
    for (const [key, value] of Object.entries(props)) {
      if (/^(?:aria[A-Z]|role$)/.test(key)) node.setAttribute(key.replace(/^aria([A-Z])/, (_, c) => `aria-${c.toLowerCase()}`), value);
      else node[key] = value;
    }
    node.append(...children.filter(Boolean));
    return node;
  };
  const section = (title, ...children) => el('section', { className: 'site-menu-section' }, el('h3', { textContent: title }), ...children);
  const item = (label, href, note) => {
    const link = el('a', { className: 'site-menu-item', href }, el('span', { textContent: label }), note && el('small', { textContent: note }));
    if (href.split('#')[0] === here && !href.includes('#')) link.setAttribute('aria-current', 'page');
    return link;
  };

  const menu = el('div', { className: 'site-menu', id: 'site-menu', hidden: true });
  const scrim = el('div', { className: 'site-menu-scrim' });
  const close = el('button', { type: 'button', className: 'site-menu-close', ariaLabel: 'Close menu' });
  close.append(button.querySelector('svg')?.cloneNode(true) || '');
  close.querySelector('path')?.setAttribute('d', 'M6 6l12 12M18 6 6 18');
  const visuals = el('div', { className: 'site-menu-visuals' });
  const loginStatus = el('p', { className: 'site-menu-status', role: 'status' });
  const login = el('a', { className: 'site-menu-login', href: '/owner', textContent: 'Log in' });
  const features = el('ul', { className: 'site-menu-list' }, ...FEATURES.map(([label, href, note]) => el('li', {},
    href ? item(label, href, note)
      : el('span', { className: 'site-menu-item is-soon', ariaDisabled: 'true' }, el('span', { textContent: label }), el('small', { textContent: note })))));
  const panel = el('div', { className: 'site-menu-panel', role: 'dialog', ariaModal: 'true', ariaLabel: 'Site menu' },
    el('div', { className: 'site-menu-head' }, el('span', { className: 'site-menu-brand', lang: 'grc', textContent: 'Μέλος' }), close),
    el('nav', { ariaLabel: 'Site' },
      section('Create design decks', item('Design studio', '/legacy', 'Paintings, dither and the original search')),
      section('Visuals', visuals),
      section('About', item('What Melos does', '/about', 'Sources, licences and accuracy')),
      section('Features', features)),
    el('div', { className: 'site-menu-foot' }, login, loginStatus));
  menu.append(scrim, panel);
  document.body.append(menu);
  button.setAttribute('aria-controls', menu.id);
  button.setAttribute('aria-expanded', 'false');
  // Pages fold their own in-page links (e.g. the design studio's sections) into the panel.
  const local = document.querySelector('[data-site-menu-local]');
  if (local) panel.querySelector('nav').prepend(section('On this page', ...[...local.querySelectorAll('a')].map(a => item(a.textContent, a.getAttribute('href')))));

  function renderVisuals() {
    const tuneToggle = document.getElementById('tune-toggle');
    const thumbs = [...document.querySelectorAll('#thumbs button')];
    if (!tuneToggle && !thumbs.length) {
      visuals.replaceChildren(el('p', { className: 'site-menu-note' }, 'Painting and dither settings are on the ', el('a', { href: '/', textContent: 'Reader' }), ' page.'));
      return;
    }
    const children = [];
    if (tuneToggle) {
      const adjust = el('button', { type: 'button', className: 'site-menu-item site-menu-action' }, el('span', { textContent: 'Adjust dither' }), el('small', { textContent: 'Palette, pixel size, depth' }));
      adjust.addEventListener('click', () => {
        hide(false);
        document.getElementById('top')?.scrollIntoView({ block: 'start' });
        if (document.getElementById('tune')?.hidden) tuneToggle.click();
        document.querySelector('#tune input, #tune select, #tune button')?.focus({ preventScroll: true });
      });
      children.push(adjust);
    }
    if (thumbs.length) {
      children.push(el('p', { className: 'site-menu-note', id: 'site-menu-paintings-label', textContent: 'Background painting' }));
      const row = el('div', { className: 'site-menu-paintings', role: 'group' });
      row.setAttribute('aria-labelledby', 'site-menu-paintings-label');
      thumbs.forEach(thumb => {
        const choice = el('button', { type: 'button', ariaLabel: thumb.getAttribute('aria-label'), title: thumb.getAttribute('aria-label') });
        choice.style.backgroundImage = thumb.style.backgroundImage;
        choice.setAttribute('aria-pressed', String(thumb.getAttribute('aria-selected') === 'true'));
        choice.addEventListener('click', () => {
          thumb.click();
          row.querySelectorAll('button').forEach(b => b.setAttribute('aria-pressed', String(b === choice)));
        });
        row.append(choice);
      });
      children.push(row);
    }
    visuals.replaceChildren(...children);
  }

  const focusables = () => [...panel.querySelectorAll('a[href], button:not([disabled])')].filter(node => node.offsetParent !== null);
  function show() {
    renderVisuals();
    menu.hidden = false;
    button.setAttribute('aria-expanded', 'true');
    document.documentElement.classList.add('site-menu-open');
    close.focus();
  }
  function hide(returnFocus = true) {
    if (menu.hidden) return;
    menu.hidden = true;
    button.setAttribute('aria-expanded', 'false');
    document.documentElement.classList.remove('site-menu-open');
    if (returnFocus) button.focus({ preventScroll: true });
  }
  button.addEventListener('click', () => (menu.hidden ? show() : hide()));
  close.addEventListener('click', () => hide());
  scrim.addEventListener('click', () => hide());
  document.addEventListener('keydown', event => {
    if (menu.hidden) return;
    if (event.key === 'Escape') { event.preventDefault(); hide(); return; }
    if (event.key !== 'Tab') return;
    const nodes = focusables(), first = nodes[0], last = nodes[nodes.length - 1];
    if (!panel.contains(document.activeElement)) { event.preventDefault(); first.focus(); }
    else if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus(); }
    else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus(); }
  });

  function focusSearch() {
    const input = document.getElementById('search-input');
    if (!input) return false;
    input.scrollIntoView({ block: 'center' });
    input.focus({ preventScroll: true });
    return true;
  }
  panel.addEventListener('click', event => {
    const link = event.target.closest('a.site-menu-item');
    if (!link) return;
    if (link.getAttribute('href') === '/#search' && document.getElementById('search-input')) {
      event.preventDefault(); hide(false); focusSearch();
    } else hide(false);
  });
  if (location.hash === '#search') addEventListener('load', focusSearch, { once: true });

  async function ownerAvailable() {
    if (OWNER_LOGIN_LIVE) return true;
    try {
      const response = await fetch('/owner', { method: 'HEAD', cache: 'no-store' });
      return response.ok && /^\/owner(?:\.html)?$/.test(new URL(response.url).pathname);
    } catch { return false; }
  }
  login.addEventListener('click', async event => {
    event.preventDefault();
    loginStatus.textContent = '';
    if (await ownerAvailable()) location.assign('/owner');
    else loginStatus.textContent = 'Owner login is not available yet.';
  });
})();
