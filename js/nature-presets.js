/* Shared, static aesthetic presets. Not a classification of a poem's subject. */
(() => {
  'use strict';
  const data = window.MelosNaturePresetData;
  if (!data) return;
  const presets = data.presets;
  const fallback = data.defaultPresetId;
  const card = document.getElementById('passage');
  let current = fallback, sequence = 0, assignmentsPromise, artworkVisible = false;
  const owns = (object, key) => Object.prototype.hasOwnProperty.call(object, key);
  const loaded = new Map();
  const constrained = () => navigator.connection?.saveData || /(^|-)2g$/.test(navigator.connection?.effectiveType || '');
  const imageUrl = id => {
    const preset = presets[id] || presets[fallback];
    return (matchMedia('(max-width: 640px)').matches || constrained()) ? preset.smallUrl : preset.url;
  };
  function apply(id, matched = false) {
    current = owns(presets, id) ? id : fallback;
    if (!card) return;
    card.dataset.naturePreset = current;
    card.dataset.natureMatch = matched ? 'annotated' : 'decorative-default';
    card.style.setProperty('--poem-header-image', `url("${imageUrl(current)}")`);
    if (artworkVisible) showArtwork();
  }
  // An actual image avoids relying on inherited custom-property/background
  // repainting when the reader is reparented into a mobile modal.
  function showArtwork() {
    artworkVisible = true;
    const heading = card?.querySelector('.passage-heading');
    if (!heading) return;
    let image = heading.querySelector('.poem-header-art');
    if (!image) {
      image = document.createElement('img');
      image.className = 'poem-header-art'; image.alt = '';
      image.setAttribute('aria-hidden', 'true'); image.decoding = 'async';
      heading.insertBefore(image, heading.firstChild);
    }
    const preset = presets[current] || presets[fallback];
    const url = imageUrl(current);
    if (image.getAttribute('src') === url) return;
    image.onerror = () => {
      image.onerror = null;
      // A failed small derivative may still have an available full-size asset.
      if (url !== preset.url) image.src = preset.url;
    };
    image.loading = 'eager'; image.fetchPriority = 'high'; image.src = url;
  }
  function warm(id) {
    const url = imageUrl(id);
    if (loaded.has(url)) return loaded.get(url);
    const promise = new Promise(resolve => {
      const img = new Image();
      img.decoding = 'async'; img.fetchPriority = 'low';
      img.onload = () => resolve(true);
      img.onerror = () => { loaded.delete(url); resolve(false); };
      img.src = url;
    });
    loaded.set(url, promise);
    return promise;
  }
  const idle = () => new Promise(resolve => {
    if (window.requestIdleCallback) window.requestIdleCallback(resolve, { timeout: 2000 });
    else setTimeout(resolve, 80);
  });
  function assignments() {
    return assignmentsPromise ??= fetch(data.assignmentsUrl, { priority: 'low' })
      .then(response => { if (!response.ok) throw new Error('Preset map unavailable'); return response.json(); })
      .catch(() => ({}));
  }
  async function select(passage) {
    const ticket = ++sequence;
    apply(fallback);
    if (!passage?.id || !passage.text || typeof crypto === 'undefined' || !crypto.subtle) return;
    try {
      const map = await assignments();
      const entry = map[passage.id];
      if (!entry || !owns(presets, entry.theme)) return;
      const bytes = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(passage.text));
      const hash = Array.from(new Uint8Array(bytes), byte => byte.toString(16).padStart(2, '0')).join('');
      if (ticket === sequence && hash === entry.hash) apply(entry.theme, true);
    } catch { /* Decoration must never interrupt reading or invent a match. */ }
  }
  let preloading = false;
  async function preloadAll() {
    if (preloading || constrained()) return;
    preloading = true;
    // Hero's complete warm queue has priority. Only one small nature image at a time.
    for (const id of new Set([current, ...Object.keys(presets)])) {
      await idle();
      if (constrained()) break;
      await warm(id);
    }
  }
  window.MelosNaturePresets = Object.freeze({ select, showArtwork, warmCurrent: () => { showArtwork(); return warm(current); },
    preloadAll, presets, assignments });
  apply(fallback);
  if (window.MelosHeroAssetsReady) void preloadAll();
  else window.addEventListener('melos:hero-assets-ready', preloadAll, { once: true });
  if (!document.querySelector('.reader-hero')) {
    if (document.readyState === 'complete') void preloadAll();
    else window.addEventListener('load', preloadAll, { once: true });
  }
})();
