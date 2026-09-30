/* Melos line icons: local SVG paths, never platform-dependent emoji glyphs. */
(() => {
  'use strict';
  const paths = {
    '→': 'M3 12h17M14 5l7 7-7 7',
    '←': 'M21 12H4M10 5l-7 7 7 7',
    '↗': 'M5 19 19 5M6 5h13v13',
    '↓': 'M12 3v17M5 14l7 7 7-7',
    '⌄': 'm5 9 7 7 7-7',
    '×': 'm6 6 12 12M18 6 6 18',
    '✳': 'M12 3v18M3 12h18M6 6l12 12M18 6 6 18'
  };
  function icon(symbol) {
    const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
    svg.setAttribute('viewBox', '0 0 24 24');
    svg.setAttribute('class', 'melos-icon');
    svg.setAttribute('aria-hidden', 'true');
    svg.setAttribute('focusable', 'false');
    const path = document.createElementNS(svg.namespaceURI, 'path');
    path.setAttribute('d', paths[symbol]);
    svg.append(path);
    return svg;
  }
  function decorate(root) {
    const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
    const nodes = [];
    while (walker.nextNode()) {
      if (/[→←↗↓⌄×✳]/u.test(walker.currentNode.nodeValue)) nodes.push(walker.currentNode);
    }
    for (const text of nodes) {
      const fragment = document.createDocumentFragment();
      for (const part of text.nodeValue.split(/([→←↗↓⌄×✳])/u)) {
        fragment.append(paths[part] ? icon(part) : document.createTextNode(part));
      }
      text.replaceWith(fragment);
    }
    return root;
  }
  window.MelosIcons = { decorate };
  document.querySelectorAll('a,button,.tiny-asterisk').forEach(decorate);
})();
