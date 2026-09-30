import test from 'node:test';
import assert from 'node:assert/strict';
import vm from 'node:vm';
import { readFileSync } from 'node:fs';

// Minimal DOM fixture runs the real decorator for both initial and dynamic UI.
class Element {
  constructor(tag, text = null, namespaceURI = null) {
    Object.assign(this, { tag, nodeType: tag === '#text' ? 3 : 1, nodeValue: text, namespaceURI, childNodes: [], attributes: {}, parentNode: null });
  }
  append(...children) {
    for (const child of children) { child.parentNode = this; this.childNodes.push(child); }
  }
  setAttribute(name, value) { this.attributes[name] = value; }
  replaceWith(fragment) {
    const siblings = this.parentNode.childNodes;
    const index = siblings.indexOf(this);
    for (const child of fragment.childNodes) child.parentNode = this.parentNode;
    siblings.splice(index, 1, ...fragment.childNodes);
  }
  get textContent() { return this.nodeType === 3 ? this.nodeValue : this.childNodes.map(child => child.textContent).join(''); }
}
const text = value => new Element('#text', value);
function walk(root) { return root.childNodes.flatMap(child => [child, ...walk(child)]); }
function setup(initial = []) {
  const window = {};
  const document = {
    createElementNS: (ns, tag) => new Element(tag, null, ns),
    createTextNode: text,
    createDocumentFragment: () => new Element('#fragment'),
    querySelectorAll: () => initial,
    createTreeWalker(root) {
      const texts = walk(root).filter(node => node.nodeType === 3);
      let index = -1;
      return { currentNode: null, nextNode() { this.currentNode = texts[++index]; return Boolean(this.currentNode); } };
    },
  };
  const context = vm.createContext({ window, document, NodeFilter: { SHOW_TEXT: 4 } });
  vm.runInContext(readFileSync(new URL('../js/ui-icons.js', import.meta.url), 'utf8'), context);
  return window.MelosIcons;
}

test('initial nested navigation arrows become hidden-from-AT local SVG paths', () => {
  const button = new Element('button'), span = new Element('span');
  span.append(text('↗')); button.append(text('Open source '), span);
  setup([button]);
  const svg = walk(button).find(node => node.tag === 'svg');
  assert.equal(button.textContent, 'Open source ');
  assert.equal(svg.namespaceURI, 'http://www.w3.org/2000/svg');
  assert.equal(svg.attributes['aria-hidden'], 'true');
  assert.equal(svg.attributes.focusable, 'false');
  assert.equal(svg.attributes.class, 'melos-icon');
  assert.equal(svg.childNodes[0].attributes.d, 'M5 19 19 5M6 5h13v13');
});

test('dynamically created reader controls get SVG icons exactly once without altering label words', () => {
  const icons = setup();
  for (const symbol of ['→', '←', '↗', '↓', '⌄', '×', '✳']) {
    const link = new Element('a'); link.append(text(`Fixture action ${symbol}`));
    icons.decorate(link); icons.decorate(link);
    assert.equal(link.textContent, 'Fixture action ');
    assert.equal(walk(link).filter(node => node.tag === 'svg').length, 1);
    assert.ok(walk(link).find(node => node.tag === 'path').attributes.d);
  }
});

test('reader and usage-space factories decorate dynamic links/buttons and icons inherit theme ink', () => {
  for (const script of ['reader.js', 'usage-space.js']) {
    const source = readFileSync(new URL(`../js/${script}`, import.meta.url), 'utf8');
    assert.match(source, /if \(tag === 'a' \|\| tag === 'button'\) window\.MelosIcons\?\.decorate\(/);
  }
  const css = readFileSync(new URL('../css/reader.css', import.meta.url), 'utf8');
  const icons = readFileSync(new URL('../css/icons.css', import.meta.url), 'utf8');
  assert.match(css, /\.reader-layout \.melos-icon,\.utility-bar \.melos-icon\{color:var\(--ink\)\}/);
  assert.match(icons, /stroke: currentColor/);
});
