import test from 'node:test';
import assert from 'node:assert/strict';
import {luxar} from './operator-ui/explorer/app.js';

test('LUXAR rendering preserves six-decimal units above JavaScript safe integers', () => {
  assert.equal(luxar('1'), '0.000001');
  assert.equal(luxar('87499000'), '87.499');
  assert.equal(luxar('1000000000000'), '1,000,000');
  assert.equal(luxar('9007199254740993'), '9,007,199,254.740993');
});
