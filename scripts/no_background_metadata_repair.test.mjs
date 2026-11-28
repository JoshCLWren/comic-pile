import assert from 'node:assert/strict';
import {existsSync, readFileSync, readdirSync} from 'node:fs';
import {test} from 'node:test';
import {fileURLToPath} from 'node:url';
import {generateVercel, loadFragmentFiles} from './generate_vercel_routes.mjs';

const ROOT = new URL('../', import.meta.url);

function read(relative) {
  return readFileSync(new URL(relative, ROOT), 'utf8');
}

// vercel.json is bot-owned: assert the document the fragment-derived generator
// will publish, not the previous generated artifact committed on main.
function generatedVercel() {
  const previous = JSON.parse(read('vercel.json'));
  const fragments = loadFragmentFiles(
    fileURLToPath(new URL('docs/api/route-fragments', ROOT)),
  );
  return generateVercel(previous, fragments);
}

function rustSources() {
  const dir = new URL('native/roll-service/src/', ROOT);
  return readdirSync(dir)
    .filter(name => name.endsWith('.rs'))
    .map(name => {
      const full = read(`native/roll-service/src/${name}`);
      // Negative assertions in unit tests are guards, not legacy callers.
      const testModule = full.indexOf('#[cfg(test)]');
      return {name, source: testModule === -1 ? full : full.slice(0, testModule)};
    });
}

test('no scheduled ComicVine metadata repair invocation remains', () => {
  assert.equal(
    existsSync(new URL('.github/workflows/comicvine-metadata-repair.yml', ROOT)),
    false,
    'the repair drain workflow must be deleted',
  );
  const generated = generatedVercel();
  assert.deepEqual(
    generated.crons,
    [{path: '/api/v2/cron/release-sync', schedule: '0 9 * * *'}],
    'only the canonical v2 release-sync cron may remain in generated ingress',
  );
  const api = JSON.stringify(generated.routes);
  assert.ok(!api.includes('comicvine-metadata-repairs'));
  assert.ok(!api.includes('comicvine-metadata-backfill'));
  assert.deepEqual(generateVercel(generated, loadFragmentFiles(
    fileURLToPath(new URL('docs/api/route-fragments', ROOT)),
  )), generated, 'regeneration must be idempotent');
});

test('no background repair ledger, dispatch or drain code remains in Rust', () => {
  const forbidden = [
    'comicvine_metadata_refresh_requests',
    'notify_repair_enqueued',
    'comicvine-metadata-repair-enqueued',
    'COMICVINE_REPAIR_DISPATCH_TOKEN',
    'queue_empty',
    'fn drain(',
    'fn backfill(',
  ];
  for (const {name, source} of rustSources()) {
    for (const token of forbidden) {
      assert.ok(!source.includes(token), `${name} still references ${token}`);
    }
  }
  const provider = read('native/roll-service/src/comicvine_provider.rs');
  assert.ok(provider.includes('needs_provider_fetch'));
  assert.ok(provider.includes('hydrate_confirmed_identity_inline'));
  assert.ok(!provider.includes('CRON_SECRET'));
  assert.equal(existsSync(new URL('native/roll-service/src/comicvine_repair.rs', ROOT)), false);
});

test('the ledger retirement migration drops the table', () => {
  const migrations = readdirSync(new URL('native/migrate/migrations/', ROOT));
  const retirement = migrations.find(name => name.includes('retire_comicvine_metadata_refresh_requests'));
  assert.ok(retirement, 'a forward migration must retire the ledger');
  assert.ok(retirement.startsWith('V8__'), 'the ledger retirement must not collide with main V7');
  const sql = read(`native/migrate/migrations/${retirement}`);
  assert.match(sql, /DROP TABLE IF EXISTS public\.comicvine_metadata_refresh_requests/);
});

test('active docs do not advertise the retired background architecture', () => {
  for (const path of [
    'docs/COMICVINE_RUNTIME_FALLBACK.md',
    'docs/VERCEL_DEPLOYMENT.md',
    'docs/COMICVINE_HYDRATOR.md',
  ]) {
    const doc = read(path);
    assert.ok(!doc.includes('GET /api/v2/maintenance/comicvine-metadata-repairs'), path);
    assert.ok(!doc.includes('repository_dispatch'), path);
  }
  const hydrator = read('docs/COMICVINE_HYDRATOR.md');
  assert.ok(!hydrator.includes('refreshes use the durable repair queue'));
  assert.ok(hydrator.includes('there is no durable repair queue or maintenance worker'));

  const anchors = new Set(
    read('docs/VERCEL_DEPLOYMENT.md')
      .split('\n')
      .filter(line => /^#{1,6}\s/.test(line))
      .map(line =>
        line
          .replace(/^#{1,6}\s*/, '')
          .trim()
          .toLowerCase()
          .replace(/[^\w\s-]/g, '')
          .replace(/\s+/g, '-'),
      ),
  );
  for (const [, anchor] of hydrator.matchAll(/VERCEL_DEPLOYMENT\.md#([\w-]+)/g)) {
    assert.ok(anchors.has(anchor), `broken VERCEL_DEPLOYMENT.md anchor: ${anchor}`);
  }
});
