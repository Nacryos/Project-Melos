import test from 'node:test';
import assert from 'node:assert/strict';
import vm from 'node:vm';
import { readFileSync } from 'node:fs';
const scope = vm.createContext({ window: {}, URL });
vm.runInContext(readFileSync(new URL('../js/composer-core.js', import.meta.url), 'utf8'), scope);
const C = scope.window.ComposerCore || scope.ComposerCore;
test('a blank row separates stanzas: the fourth row after it is the adonic', () => {
  const drafts = ['a', 'b', 'c', 'd', '', 'e', 'f', 'g', ''];
  assert.deepEqual(drafts.map((_, i) => C.stanzaIndex(drafts, i)), [0, 1, 2, 3, 4, 0, 1, 2, 3]);
  assert.equal(C.templateFor('sapphic', C.stanzaIndex(drafts, 8)), '-uu-F');
  assert.equal(C.templateFor('sapphic', C.stanzaIndex(drafts, 5)), '-u-x-uu-u-F');
  assert.equal(C.stanzaIndex(['x', '  ', 'y'], 2), 0);
});
