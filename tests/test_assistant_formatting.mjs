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

test('hosted Build/Buy sections separate bold fields on soft lines and the same line', () => {
  const body = '### Build\n\n[Build an open-hardware Jubilee platform](https://github.com/machineagency/jubilee/tree/0123456789abcdef)\n**Cost:** ~$1,400 historical upstream base-parts estimate, checked 2026-11-03. Reviewed reference only, not a quote.\n**Scope:** Source the pinned BOM and fabricate specified parts; pipette tools and fixtures need review.\n**Tradeoff:** More assembly and calibration work, but flexible for custom tube racks.\n\n### Buy\n\n[Buy an assembled Opentrons OT-2 platform](https://opentrons.com/) **Cost:** Starting at $15,950 vendor price, checked 2026-11-03. Reviewed reference only, verify configuration separately. **Scope:** Request official configuration/quote for robot, compatible pipettes and labware, then manufacturer setup. **Tradeoff:** Less building, but needs compatible instrument pipettes and confirmed labware.\n\nDo you already own compatible pipettes or labware you want this to fit?';
  const result = formatAssistantText(body);
  for (const field of ['Cost', 'Scope', 'Tradeoff']) {
    assert.equal((result.match(new RegExp(`\\n\\n\\*\\*${field}:\\*\\*`, 'g')) || []).length, 2);
  }
  assert.equal(formatAssistantText(result), result);
  assert.ok(result.endsWith('Do you already own compatible pipettes or labware you want this to fit?'));
  const generic = 'Project help:\n**Cost:** Keep this generic GFM. **Scope:** No route comparison.';
  assert.equal(formatAssistantText(generic), generic);
  const fresh = '### Build\n**Cost:** ~$1,400 historical estimate; [Jubilee project](https://github.com/machineagency/jubilee/) and [Science Jubilee tools](https://github.com/science-jubilee/science-jubilee/).\n**Scope:** Source and fabricate the parts.\n**Tradeoff:** Assembly work remains.\n\n### Buy\n**Cost:** Starting at $15,950; [Opentrons catalogue](https://opentrons.com/).\n**Scope:** Request a quote.\n**Tradeoff:** Compatible instruments required.';
  const formattedFresh = formatAssistantText(fresh);
  assert.equal((formattedFresh.match(/\n\n\*\*(?:Cost|Scope|Tradeoff):\*\*/g) || []).length, 6);
  assert.ok(formattedFresh.includes('[Science Jubilee tools](https://github.com/science-jubilee/science-jubilee/)'));
  assert.equal(formatAssistantText(formattedFresh), formattedFresh);
});
