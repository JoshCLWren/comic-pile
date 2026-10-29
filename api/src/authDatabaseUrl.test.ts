import { test } from 'node:test';
import assert from 'node:assert/strict';
import { buildAuthPoolConfig, normalizePostgresUrl } from './authDatabaseUrl.js';

test('normalizePostgresUrl rewrites SQLAlchemy driver prefixes', () => {
  assert.equal(
    normalizePostgresUrl(
      'postgresql+asyncpg://comicpile:secret@localhost:5435/comicpile',
    ),
    'postgresql://comicpile:secret@localhost:5435/comicpile',
  );
  assert.equal(
    normalizePostgresUrl('postgresql+psycopg://u:p@db.example/app'),
    'postgresql://u:p@db.example/app',
  );
  assert.equal(
    normalizePostgresUrl('postgres://u:p@db.example/app'),
    'postgresql://u:p@db.example/app',
  );
});

test('buildAuthPoolConfig does not pass a raw connectionString to node-pg', () => {
  const config = buildAuthPoolConfig(
    'postgresql+asyncpg://reader:s3cret@ep-example.us-east-2.aws.neon.tech/neondb'
      + '?sslmode=require&channel_binding=require',
  );
  assert.equal(config.connectionString, undefined);
  assert.equal(config.host, 'ep-example.us-east-2.aws.neon.tech');
  assert.equal(config.port, 5432);
  assert.equal(config.user, 'reader');
  assert.equal(config.password, 's3cret');
  assert.equal(config.database, 'neondb');
  assert.deepEqual(config.ssl, { rejectUnauthorized: false });
  assert.equal(
    Object.prototype.hasOwnProperty.call(config, 'channel_binding'),
    false,
  );
});

test('buildAuthPoolConfig keeps local CI URLs on plaintext TCP', () => {
  const config = buildAuthPoolConfig(
    'postgresql+asyncpg://postgres:postgres@127.0.0.1:5432/comic_pile_test',
  );
  assert.equal(config.host, '127.0.0.1');
  assert.equal(config.port, 5432);
  assert.equal(config.ssl, undefined);
});

test('buildAuthPoolConfig enables TLS for Neon hosts even without sslmode', () => {
  const config = buildAuthPoolConfig(
    'postgresql://reader:s3cret@ep-example-pooler.us-east-2.aws.neon.tech/neondb',
  );
  assert.deepEqual(config.ssl, { rejectUnauthorized: false });
});
