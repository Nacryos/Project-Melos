import test from 'node:test';
import assert from 'node:assert/strict';
import vm from 'node:vm';
import { readFileSync } from 'node:fs';

const script = readFileSync(new URL('../js/reader.js', import.meta.url), 'utf8');
const select = { value: '', children: [], append(child) { this.children.push(child); } };
const context = vm.createContext({
  ui: { language: select }, clear(element) { element.children = []; element.value = ''; },
  node: (tag, cls, text) => ({ tag, text, value: '' }),
});
vm.runInContext(script.slice(script.indexOf('  function updateLanguageOptions('), script.indexOf('  function renderStatus(')), context);
const update = vm.runInContext('updateLanguageOptions', context);

test('language picker distinguishes Ancient Greek from Modern Greek and keeps the selection', () => {
  select.value = 'ell';
  update([{ language: 'grc' }, { language: 'ell' }, { language: 'ell' }, { language: 'eng' }]);
  assert.deepEqual(select.children.map(option => [option.value, option.text]), [
    ['', 'Any'], ['grc', 'Ancient Greek'], ['ell', 'Modern Greek'], ['eng', 'English'],
  ]);
  assert.equal(select.value, 'ell');
});

test('unknown language codes stay visible and absent languages are not fabricated', () => {
  update([{ language: 'xyz' }, { language: '' }]);
  assert.deepEqual(select.children.map(option => [option.value, option.text]), [['', 'Any'], ['xyz', 'xyz']]);
});
