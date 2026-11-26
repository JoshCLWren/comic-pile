import assert from 'node:assert/strict';
import {existsSync, readFileSync, readdirSync} from 'node:fs';
import {test} from 'node:test';

const ROOT = new URL('../', import.meta.url);

function read(relative) {
  return readFileSync(new URL(relative, ROOT), 'utf8');
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
  const vercel = JSON.parse(read('vercel.json'));
  assert.deepEqual(
    vercel.crons,
    [{path: '/api/v1/cron/release-sync', schedule: '0 9 * * *'}],
    'only the unrelated release-sync cron may remain',
  );
  const api = JSON.stringify(vercel.routes);
  assert.ok(!api.includes('comicvine-metadata-repairs'));
  assert.ok(!api.includes('comicvine-metadata-backfill'));
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
  const sql = read(`native/migrate/migrations/${retirement}`);
  assert.match(sql, /DROP TABLE IF EXISTS public\.comicvine_metadata_refresh_requests/);
});

test('active docs do not advertise the retired background architecture', () => {
  for (const path of ['docs/COMICVINE_RUNTIME_FALLBACK.md', 'docs/VERCEL_DEPLOYMENT.md']) {
    const doc = read(path);
    assert.ok(!doc.includes('GET /api/v2/maintenance/comicvine-metadata-repairs'), path);
    assert.ok(!doc.includes('repository_dispatch'), path);
  }
});
