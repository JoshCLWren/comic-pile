import test from 'node:test';
import assert from 'node:assert/strict';
import {
  BOT_OWNED_PATHS,
  agentsChangedOnlyInBlock,
  botPrViolations,
  featurePrViolations,
} from './check_generated_files_guard.mjs';

const agents = (block, outside = 'guide') =>
  `# Agents\n${outside}\n<!-- route-burndown:begin -->\n${block}\n<!-- route-burndown:end -->\ntail\n`;

test('feature PRs may not edit any generated contract or route output', () => {
  for (const file of BOT_OWNED_PATHS) {
    assert.deepEqual(featurePrViolations([file, 'native/roll-service/src/comicvine_v2.rs'], null), [file]);
  }
});

test('feature PRs may change area sources, fragments and AGENTS guidance outside the block', () => {
  const changed = [
    'native/roll-service/src/comicvine_v2.rs',
    'docs/api/route-fragments/comicvine.json',
    'frontend/src/services/api-comicvine.ts',
    'AGENTS.md',
  ];
  assert.deepEqual(featurePrViolations(changed, {base: agents('a'), head: agents('a', 'new guide')}), []);
});

test('feature PRs may not edit the generated AGENTS block', () => {
  assert.deepEqual(
    featurePrViolations(['AGENTS.md'], {base: agents('a'), head: agents('b')}),
    ['AGENTS.md (route-burndown block)'],
  );
});

test('the bot PR may change only generated files', () => {
  assert.deepEqual(botPrViolations([...BOT_OWNED_PATHS], null), []);
  assert.deepEqual(
    botPrViolations(['native/contracts/v2-runtime.openapi.json', 'native/roll-service/src/lib.rs'], null),
    ['native/roll-service/src/lib.rs'],
  );
  assert.deepEqual(botPrViolations([], null), ['regeneration PR has no changed artifacts']);
});

test('the bot PR may change AGENTS.md only inside the generated block', () => {
  assert.equal(agentsChangedOnlyInBlock(agents('a'), agents('b')), true);
  assert.equal(agentsChangedOnlyInBlock(agents('a'), agents('b', 'edited')), false);
  assert.deepEqual(
    botPrViolations(['AGENTS.md'], {base: agents('a'), head: agents('a', 'edited')}),
    ['AGENTS.md (changes outside route-burndown block)'],
  );
});
