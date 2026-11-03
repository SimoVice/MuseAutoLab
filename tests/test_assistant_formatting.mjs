import assert from 'node:assert/strict';
import test from 'node:test';
import { formatAssistantText, sourceLinkLabel } from '../web/src/assistantFormatting.ts';

test('restored route lists become sections while retaining evidence and the final question', () => {
  const input = 'Two routes:\n1. Build an open-hardware Jubilee platform — source: https://github.com/example/Jubilee/tree/abcdef Cost: $1,400 historical estimate. Tradeoff: Assembly required.\n2. Buy an assembled OT-2 platform — source: https://opentrons.com/ Cost: $15,950 starting price. Tradeoff: Compatible instruments required.\n\nWhich route suits your lab?';
  const result = formatAssistantText(input);
  assert.match(result, /### Build an open-hardware Jubilee platform/);
  assert.match(result, /### Buy an assembled OT-2 platform/);
  assert.match(result, /\*\*Cost:\*\* \$1,400 historical estimate/);
  assert.match(result, /\*\*Tradeoff:\*\* Assembly required/);
  assert.ok(result.includes('https://github.com/example/Jubilee/tree/abcdef'));
  assert.ok(result.endsWith('Which route suits your lab?'));
  assert.equal(formatAssistantText(result), result);
});

test('generic numbered instructions and code stay intact', () => {
  for (const text of ['1. Prepare tubes.\n2. Mix samples.', 'How can I help?', '```\n1. Build this\n2. Buy that\n```']) {
    assert.equal(formatAssistantText(text), text);
  }
});

test('literal historical ASCII-separated comparison exposes cost basis without a dangling hyphen', () => {
  const input = '1. Build an open-hardware Jubilee platform - source: https://github.com/machineagency/jubilee/tree/0123456789abcdef0123456789abcdef01234567 - reviewed reference historical base-parts estimate ~$1400 USD checked 2026-11-03, not a quote. Tradeoff: Assembly required.\n2. Buy an assembled Opentrons OT-2 platform - source: https://opentrons.com/products/categories/robots - reviewed reference vendor starting price $15,950 USD checked 2026-11-03, not a quote. Tradeoff: Compatible instruments required.';
  const result = formatAssistantText(input);
  assert.match(result, /### Build an open-hardware Jubilee platform\n/);
  assert.match(result, /### Buy an assembled Opentrons OT-2 platform\n/);
  assert.equal((result.match(/\*\*Source:\*\*/g) || []).length, 2);
  assert.equal((result.match(/\*\*Cost basis:\*\*/g) || []).length, 2);
  assert.ok(result.includes('historical base-parts estimate ~$1400 USD'));
  assert.ok(result.includes('vendor starting price $15,950 USD'));
  assert.equal(formatAssistantText(result), result);
});

test('bare links have descriptive labels without exposing long pinned hashes', () => {
  assert.equal(sourceLinkLabel('https://github.com/machineagency/jubilee/tree/abcdef'), 'machineagency/jubilee project reference');
  assert.equal(sourceLinkLabel('https://opentrons.com/products/categories/robots'), 'Opentrons reference');
  assert.equal(sourceLinkLabel('https://example.org/catalog'), 'example.org reference');
});
