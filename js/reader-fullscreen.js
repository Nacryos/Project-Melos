(() => {
  'use strict';
  const passage = document.getElementById('passage');
  const trigger = document.getElementById('passage-fullscreen-toggle');
  const column = passage?.closest('.reading-column');
  const inspector = document.querySelector('aside.inspector');
  if (!column || !trigger) return;

  const dialog = document.createElement('dialog');
  dialog.className = 'passage-fullscreen';
  dialog.setAttribute('aria-labelledby', 'passage-title');
  dialog.setAttribute('role', 'dialog');
  dialog.setAttribute('aria-modal', 'true');
  dialog.tabIndex = -1;
  const toolbar = document.createElement('div');
  toolbar.className = 'passage-fullscreen-toolbar';
  const exit = document.createElement('button');
  exit.type = 'button';
  exit.className = 'passage-fullscreen-exit';
  exit.innerHTML = '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="m6 6 12 12M18 6 6 18"/></svg><span>Exit fullscreen</span>';
  toolbar.append(exit);
  const layout = document.createElement('div');
  layout.className = 'passage-fullscreen-layout';
  dialog.append(toolbar, layout);
  document.body.append(dialog);
  let placeholders = [], returnFocus = null, savedOverflow = '', savedScroll = 0, opened = false, nativeModal = false;
  function sizeSelectionDock() {
    if (!opened || typeof toolbar.getBoundingClientRect !== 'function') return;
    dialog.style.setProperty('--selection-dock-top', `${Math.ceil(toolbar.getBoundingClientRect().height) + 8}px`);
  }
  window.addEventListener('resize', sizeSelectionDock);
  if (typeof ResizeObserver === 'function') new ResizeObserver(sizeSelectionDock).observe(toolbar);

  function restore() {
    if (!placeholders.length) return;
    for (const [element, placeholder] of placeholders) placeholder.replaceWith(element);
    placeholders = [];
    opened = false;
    document.body.style.overflow = savedOverflow;
    trigger.setAttribute('aria-expanded', 'false');
    window.scrollTo(0, savedScroll);
    returnFocus?.focus({ preventScroll: true });
    window.dispatchEvent(new Event('resize'));
  }
  function close() {
    if (!opened) return;
    if (nativeModal && typeof dialog.close === 'function') dialog.close();
    else dialog.removeAttribute('open');
    dialog.classList.remove('is-fallback');
    restore();
  }
  function open() {
    if (opened) return;
    returnFocus = document.activeElement;
    savedOverflow = document.body.style.overflow;
    savedScroll = window.scrollY;
    for (const element of [column, inspector].filter(Boolean)) {
      const placeholder = document.createComment('Melos fullscreen return position');
      element.before(placeholder);
      placeholders.push([element, placeholder]);
      layout.append(element);
    }
    nativeModal = false;
    if (typeof dialog.showModal === 'function') {
      try { dialog.showModal(); nativeModal = true; } catch { /* Use the fixed overlay below. */ }
    }
    if (!nativeModal) { dialog.classList.add('is-fallback'); dialog.setAttribute('open', ''); }
    opened = true;
    // Trigger real image loading only after the heading is inside its visible
    // modal. Do not wait for hero preloads or network idle on mobile devices.
    window.MelosNaturePresets?.warmCurrent();
    document.body.style.overflow = 'hidden';
    trigger.setAttribute('aria-expanded', 'true');
    dialog.scrollTop = 0;
    sizeSelectionDock();
    exit.focus({ preventScroll: true });
    window.dispatchEvent(new Event('resize'));
  }
  trigger.addEventListener('click', open);
  exit.addEventListener('click', close);
  dialog.addEventListener('cancel', event => { event.preventDefault(); close(); });
  dialog.addEventListener('close', restore);
  document.addEventListener('keydown', event => {
    if (!opened || nativeModal) return;
    if (event.key === 'Escape') { event.preventDefault(); close(); return; }
    if (event.key !== 'Tab') return;
    const nodes = [...dialog.querySelectorAll('button:not(:disabled),a[href],input:not(:disabled),select:not(:disabled),textarea:not(:disabled),summary,[tabindex]')].filter(node => node.tabIndex >= 0 && node.getClientRects().length);
    const first = nodes[0] || dialog, last = nodes[nodes.length - 1] || dialog;
    if (event.shiftKey && (document.activeElement === first || !dialog.contains(document.activeElement))) { event.preventDefault(); last.focus(); }
    else if (!event.shiftKey && (document.activeElement === last || !dialog.contains(document.activeElement))) { event.preventDefault(); first.focus(); }
  });
  document.addEventListener('focusin', event => {
    if (opened && !nativeModal && !dialog.contains(event.target)) exit.focus();
  });
})();
