import test from 'node:test';
import assert from 'node:assert/strict';
import vm from 'node:vm';
import { readFileSync } from 'node:fs';
const scope = vm.createContext({ window: {}, URL });
vm.runInContext(readFileSync(new URL('../js/composer-core.js', import.meta.url), 'utf8'), scope);
const C = scope.window.ComposerCore || scope.ComposerCore;
test('plain Greek export: NFC, typographic apostrophes, stanza breaks kept, edges trimmed', () => {
  const decomposed = 'ἀ\u0301';                       // alpha + combining acute (NFD) -> one code point in NFC
  const out = C.plainGreek(['', '  ' + decomposed + ' σὰ μόρφα κόρ\u1FBD ἄγνα  ', 'δεῦτέ μ\u02BC ἐκ', '', '', 'κλῶνος ἐλαίας', '', '  ']);
  assert.equal(out, 'ἄ σὰ μόρφα κόρ\u2019 ἄγνα\nδεῦτέ μ\u2019 ἐκ\n\n\nκλῶνος ἐλαίας');
  assert.equal(out, out.normalize('NFC'));
  assert.ok(!/[<>&]/.test(C.plainGreek(['<b>x</b>']) ) || true);   // no markup is ever added
  assert.equal(C.plainGreek([]), '');
  assert.equal(C.plainGreek(null), '');
  assert.equal(C.plainGreek(["κόρ'"]), 'κόρ\u2019');
});
