import assert from 'node:assert/strict';
import { after, test } from 'node:test';
import type { AddressInfo } from 'node:net';
import express from 'express';
import jwt, { type SignOptions } from 'jsonwebtoken';

process.env.SECRET_KEY = 'test-secret-key';
process.env.DATABASE_URL = 'postgresql://postgres:postgres@localhost:5432/comic_pile_test';

interface MockUser {
  id: number;
  username: string;
  email: string;
  is_admin: boolean;
  password_changed_at: Date | null;
}

interface MockQueryResult {
  rows: Array<{ id: number } | MockUser>;
}

const mockPool = {
  query: async (query: string, params: string[]): Promise<MockQueryResult> => {
    if (query.includes('SELECT 1 FROM revoked_tokens')) {
      return { rows: params[1] === 'revoked-jti' ? [{ id: 1 }] : [] };
    }
    if (query.includes('FROM users')) {
      const username = params[0];
      if (username === 'database-outage') throw new Error('database unavailable');
      if (username === 'testuser') {
        return {
          rows: [{
            id: 1,
            username,
            email: 'test@example.com',
            is_admin: false,
            password_changed_at: null,
          }],
        };
      }
      if (username === 'passwordchangeduser') {
        return {
          rows: [{
            id: 2,
            username,
            email: 'test2@example.com',
            is_admin: false,
            password_changed_at: new Date(),
          }],
        };
      }
    }
    return { rows: [] };
  },
};

Object.assign(globalThis, { pool: mockPool });

const secretKey = process.env.SECRET_KEY;
if (!secretKey) throw new Error('SECRET_KEY environment variable must be set');

const { default: authMeHandler } = await import('./auth.js');
const app = express();
app.get('/api/v1/auth/me', authMeHandler);
const server = app.listen(0, '127.0.0.1');
await new Promise<void>((resolve, reject) => {
  server.once('listening', resolve);
  server.once('error', reject);
});

const address = server.address();
assert.ok(address !== null && Object.prototype.toString.call(address) === '[object Object]');
// SAFETY: This server was bound to the TCP host 127.0.0.1 and is listening, so Node returns AddressInfo.
const port = (address as AddressInfo).port;
const endpoint = `http://127.0.0.1:${port}/api/v1/auth/me`;

after(async () => {
  await new Promise<void>((resolve, reject) => {
    server.close((error) => (error ? reject(error) : resolve()));
  });
});

async function requestAuthMe(token?: string): Promise<{ status: number; body: unknown }> {
  const response = await fetch(endpoint, {
    headers: token ? { authorization: `Bearer ${token}` } : {},
  });
  return { status: response.status, body: await response.json() };
}

function createToken(
  claims: Record<string, string | number>,
  expiresIn: SignOptions['expiresIn'] = '1h',
): string {
  return jwt.sign(claims, secretKey, { expiresIn });
}

test('returns user information for a valid access token', async () => {
  const result = await requestAuthMe(createToken({
    sub: 'testuser',
    jti: 'valid-jti-123',
    type: 'access',
    pc: 0,
  }));
  assert.equal(result.status, 200);
  assert.deepEqual(result.body, {
    id: 1,
    username: 'testuser',
    email: 'test@example.com',
    is_admin: false,
  });
});

test('returns 401 for a missing authorization header', async () => {
  const result = await requestAuthMe();
  assert.equal(result.status, 401);
  assert.deepEqual(result.body, { error: 'Missing or invalid authorization header' });
});

test('returns 401 for an expired token', async () => {
  const token = createToken({ sub: 'testuser', jti: 'valid-jti-123', type: 'access', pc: 0 }, '-1s');
  const result = await requestAuthMe(token);
  assert.equal(result.status, 401);
  assert.deepEqual(result.body, { error: 'Invalid or expired token' });
});

test('returns 401 for a malformed token', async () => {
  const result = await requestAuthMe('not-a-jwt');
  assert.equal(result.status, 401);
  assert.deepEqual(result.body, { error: 'Invalid or expired token' });
});

test('returns 401 for a revoked token', async () => {
  const result = await requestAuthMe(createToken({
    sub: 'testuser',
    jti: 'revoked-jti',
    type: 'access',
    pc: 0,
  }));
  assert.equal(result.status, 401);
  assert.deepEqual(result.body, { error: 'Token has been revoked' });
});

test('returns 401 for missing claims', async () => {
  const result = await requestAuthMe(createToken({ sub: 'testuser', type: 'access' }));
  assert.equal(result.status, 401);
  assert.deepEqual(result.body, { error: 'Invalid authentication credentials' });
});

test('returns 401 for a deleted user', async () => {
  const result = await requestAuthMe(createToken({
    sub: 'nonexistentuser',
    jti: 'valid-jti-123',
    type: 'access',
    pc: 0,
  }));
  assert.equal(result.status, 401);
  assert.deepEqual(result.body, { error: 'User not found' });
});

test('returns 401 when the user password changed after token issuance', async () => {
  const result = await requestAuthMe(createToken({
    sub: 'passwordchangeduser',
    jti: 'valid-jti-123',
    type: 'access',
    pc: 0,
  }));
  assert.equal(result.status, 401);
  assert.deepEqual(result.body, { error: 'Password changed; please sign in again.' });
});

test('rejects refresh credentials', async () => {
  const result = await requestAuthMe(createToken({
    sub: 'testuser',
    jti: 'refresh-jti',
    type: 'refresh',
    pc: 0,
  }));
  assert.equal(result.status, 401);
  assert.deepEqual(result.body, { error: 'Invalid authentication credentials' });
});

test('maps a database failure to 500', async () => {
  const result = await requestAuthMe(createToken({
    sub: 'database-outage',
    jti: 'valid-jti',
    type: 'access',
    pc: 0,
  }));
  assert.equal(result.status, 500);
  assert.deepEqual(result.body, { error: 'Internal server error' });
});
