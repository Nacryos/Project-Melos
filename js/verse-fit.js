// Keeps every verse line on one visual line. Instead of wrapping a long line
// onto an indented continuation, the block's type is scaled down until its
// widest line fits the box; it grows back when the box widens. Below a small
// floor the box scrolls sideways rather than becoming unreadable.
(() => {
  'use strict';
  const FLOOR_PX = 9;
  const watched = new Map(); // host -> selector of the line elements ('' = the host itself)
  const pending = new Set();

  function fit(host, selector = watched.get(host) || '') {
    if (!host || !host.isConnected) return;
    host.style.fontSize = '';
    const rows = selector ? [...host.querySelectorAll(selector)] : [host];
    const available = host.clientWidth;
    if (!rows.length || !available) return;
    let size = parseFloat(getComputedStyle(host).fontSize) || 16;
    for (let pass = 0; pass < 3; pass++) {
      const widest = Math.max(...rows.map(row => row.scrollWidth));
      if (widest <= available) break;
      // Text width scales with font size; fixed-size labels do not, so a
      // second pass tightens the estimate.
      const next = Math.max(FLOOR_PX, Math.floor(size * (available / widest) * 100) / 100 - 0.05);
      if (next >= size) break;
      host.style.fontSize = `${next}px`;
      size = next;
      if (next <= FLOOR_PX) break;
    }
  }
  function schedule(host) {
    if (!host || pending.has(host)) return;
    pending.add(host);
    requestAnimationFrame(() => { pending.delete(host); fit(host); });
  }
  const observer = 'ResizeObserver' in window
    ? new ResizeObserver(entries => { for (const entry of entries) schedule(entry.target); })
    : null;
  function watch(host, selector = '') {
    if (!host) return;
    watched.set(host, selector);
    observer?.observe(host);
    schedule(host);
  }
  function unwatch(host) {
    if (!host) return;
    watched.delete(host);
    observer?.unobserve(host);
    host.style.fontSize = '';
  }
  const refitAll = () => watched.forEach((_, host) => schedule(host));
  if (document.fonts?.ready) document.fonts.ready.then(refitAll);
  addEventListener('resize', refitAll);
  addEventListener('orientationchange', refitAll);
  window.MelosVerseFit = { fit, watch, unwatch, refit: schedule, refitAll };
})();
