import test from 'node:test';
import assert from 'node:assert/strict';
import vm from 'node:vm';
import { readFileSync } from 'node:fs';

const source = readFileSync(new URL('../js/reader-fullscreen.js', import.meta.url), 'utf8');

// Lightweight DOM mechanics: these tests exercise lifecycle and keyboard
// behavior; Safari rendering and actual top-layer behavior require browser QA.
function setup(modal = 'native') {
  let document, dialog, warmCount = 0;
  const closeEvents = [], observers = [];
  class Element {
    constructor(tag) {
      this.tag = tag; this.children = []; this.parentElement = null;
      this.listeners = {}; this.attributes = {}; this.style = { setProperty(name, value) { this[name] = value; } };
      this.tabIndex = ['button', 'summary'].includes(tag) ? 0 : -1;
      this.height = 57.25;
      const classes = new Set();
      this.classList = { add: value => classes.add(value), remove: value => classes.delete(value), contains: value => classes.has(value) };
    }
    detach() {
      if (this.parentElement) this.parentElement.children.splice(this.parentElement.children.indexOf(this), 1);
    }
    append(...nodes) { for (const node of nodes) { node.detach(); node.parentElement = this; this.children.push(node); } }
    before(node) { node.detach(); const parent = this.parentElement; node.parentElement = parent; parent.children.splice(parent.children.indexOf(this), 0, node); }
    replaceWith(node) { node.detach(); const parent = this.parentElement; parent.children.splice(parent.children.indexOf(this), 1, node); node.parentElement = parent; this.parentElement = null; }
    setAttribute(name, value) { this.attributes[name] = value; }
    removeAttribute(name) { delete this.attributes[name]; }
    getAttribute(name) { return this.attributes[name]; }
    addEventListener(name, handler) { (this.listeners[name] ||= []).push(handler); }
    fire(name, event = {}) { for (const handler of this.listeners[name] || []) handler(event); }
    focus(options) { document.activeElement = this; this.focusOptions = options; }
    contains(node) { return this === node || this.children.some(child => child.contains(node)); }
    closest() { return column; }
    getClientRects() { return [1]; }
    getBoundingClientRect() { return { height: this.height }; }
    querySelectorAll() { return this.children.flatMap(child => [ ...(child.tabIndex >= 0 ? [child] : []), ...child.querySelectorAll() ]); }
  }
  const body = new Element('body'), shell = new Element('main'), column = new Element('section'), inspector = new Element('aside');
  const before = new Element('header'), after = new Element('footer');
  const passage = new Element('article'), trigger = new Element('button'), outside = new Element('button');
  body.append(shell, outside); shell.append(before, column, inspector, after); column.append(passage); passage.append(trigger);
  body.style.overflow = 'clip';
  document = {
    body, activeElement: trigger, listeners: {},
    getElementById: id => id === 'passage' ? passage : trigger,
    querySelector: () => inspector,
    createComment: () => new Element('comment'),
    createElement(tag) {
      const element = new Element(tag);
      if (tag === 'dialog') {
        dialog = element;
        if (modal !== 'missing') element.showModal = () => {
          if (modal === 'throwing') throw new Error('Modal unsupported');
          element.setAttribute('open', '');
        };
        element.close = () => { element.removeAttribute('open'); closeEvents.push(() => element.fire('close')); };
      }
      return element;
    },
    addEventListener(name, handler) { (this.listeners[name] ||= []).push(handler); },
    fire(name, event) { for (const handler of this.listeners[name] || []) handler(event); }
  };
  const scrollCalls = [], window = {
    listeners: {}, scrollY: 417, scrollTo: (...args) => scrollCalls.push(args),
    addEventListener(name, handler) { (this.listeners[name] ||= []).push(handler); },
    dispatchEvent(event) { for (const handler of this.listeners[event.type] || []) handler(event); },
    MelosNaturePresets: { warmCurrent() { warmCount++; } }
  };
  class ResizeObserver {
    constructor(callback) { this.callback = callback; observers.push(this); }
    observe(element) { this.element = element; }
  }
  vm.runInNewContext(source, { document, window, ResizeObserver, Event: class { constructor(type) { this.type = type; } } });
  return { document, window, dialog, body, shell, column, inspector, trigger, outside, before, after, scrollCalls, closeEvents, observers,
    exit: dialog.children[0].children[0], open: () => trigger.fire('click'), warmCount: () => warmCount };
}

for (const mode of ['native', 'missing', 'throwing']) {
  test(`${mode} dialog opens and restores the original reader, focus and scroll`, () => {
    const h = setup(mode);
    h.open(); h.open();
    assert.equal(h.warmCount(), 1, 'Repeated open is idempotent');
    assert.equal(h.dialog.getAttribute('open'), '');
    assert.equal(h.dialog.contains(h.column), true);
    assert.equal(h.dialog.contains(h.inspector), true);
    assert.equal(h.dialog.classList.contains('is-fallback'), mode !== 'native');
    assert.equal(h.document.activeElement, h.exit);
    assert.equal(h.body.style.overflow, 'hidden');
    assert.equal(h.trigger.getAttribute('aria-expanded'), 'true');
    h.exit.fire('click');
    assert.deepEqual(h.shell.children, [h.before, h.column, h.inspector, h.after]);
    assert.equal(h.dialog.getAttribute('open'), undefined);
    assert.equal(h.body.style.overflow, 'clip');
    assert.equal(h.document.activeElement, h.trigger);
    assert.equal(h.trigger.focusOptions.preventScroll, true);
    assert.equal(h.trigger.getAttribute('aria-expanded'), 'false');
    assert.deepEqual(h.scrollCalls, [[0, 417]]);
    for (const event of h.closeEvents.splice(0)) event();
    assert.deepEqual(h.scrollCalls, [[0, 417]], 'Native delayed close event does not restore twice');
    h.open(); h.exit.fire('click');
    assert.deepEqual(h.shell.children, [h.before, h.column, h.inspector, h.after]);
  });
}

test('native cancel uses the same close and restoration path', () => {
  const h = setup(); let prevented = false;
  h.open();
  h.dialog.fire('cancel', { preventDefault() { prevented = true; } });
  assert.equal(prevented, true);
  assert.equal(h.dialog.contains(h.column), false);
  assert.equal(h.document.activeElement, h.trigger);
});

test('fallback contains escaped focus and closes on Escape', () => {
  const h = setup('missing'); let prevented = false;
  h.open(); h.outside.focus();
  h.document.fire('focusin', { target: h.outside });
  assert.equal(h.document.activeElement, h.exit);
  h.document.fire('keydown', { key: 'Escape', preventDefault() { prevented = true; } });
  assert.equal(prevented, true);
  assert.equal(h.dialog.getAttribute('open'), undefined);
  assert.equal(h.document.activeElement, h.trigger);
});

test('selection dock follows measured toolbar height on open, resize and content resize', () => {
  const h = setup(), toolbar = h.dialog.children[0];
  h.open();
  assert.equal(h.dialog.style['--selection-dock-top'], '66px');
  toolbar.height = 96.2;
  h.window.dispatchEvent({ type: 'resize' });
  assert.equal(h.dialog.style['--selection-dock-top'], '105px');
  assert.equal(h.observers[0].element, toolbar);
  toolbar.height = 128;
  h.observers[0].callback();
  assert.equal(h.dialog.style['--selection-dock-top'], '136px');
  h.exit.fire('click');
  toolbar.height = 0;
  h.observers[0].callback();
  assert.equal(h.dialog.style['--selection-dock-top'], '136px', 'Hidden dialog measurements do not reset dock placement');
});

test('fallback wraps keyboard focus through summary controls', () => {
  const h = setup('missing'), summary = h.document.createElement('summary');
  h.inspector.append(summary); h.open();
  let prevented = 0;
  h.document.fire('keydown', { key: 'Tab', shiftKey: true, preventDefault() { prevented++; } });
  assert.equal(h.document.activeElement, summary);
  h.document.fire('keydown', { key: 'Tab', shiftKey: false, preventDefault() { prevented++; } });
  assert.equal(h.document.activeElement, h.exit);
  assert.equal(prevented, 2);
});
