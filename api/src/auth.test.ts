import { test } from 'node:test';
import assert from 'node:assert/strict';
import jwt from 'jsonwebtoken';

process.env.SECRET_KEY = 'test-secret-key';
process.env.DATABASE_URL = 'postgresql://postgres:postgres@localhost:5432/comic_pile_test';

const mockPool = {
  query: async (query: string, params: any[]) => {
    if (query.includes('SELECT 1 FROM revoked_tokens')) {
      if (params[1] === 'revoked-jti') return { rows: [{ id: 1 }] };
      return { rows: [] };
    }
    if (query.includes('FROM users')) {
      if (params[0] === 'testuser') {
        return { rows: [{ id: 1, username: 'testuser', email: 'test@example.com', is_admin: false, password_changed_at: null }] };
      }
      if (params[0] === 'nonexistentuser') return { rows: [] };
      if (params[0] === 'passwordchangeduser') {
        return { rows: [{ id: 2, username: 'passwordchangeduser', email: 'test2@example.com', is_admin: false, password_changed_at: new Date() }] };
      }
      return { rows: [] };
    }
    return { rows: [] };
  },
  connect: async () => ({ query: mockPool.query, release: () => {} }),
};

(globalThis as any).pool = mockPool;

const SECRET_KEY = process.env.SECRET_KEY as string;

function createMockRequest(authHeader?: string) {
  return { headers: { authorization: authHeader } };
}

function createMockResponse() {
  const calls: any = { status: [], json: [] };
  const res: any = {
    setHeader: () => {},
    status: (code: number) => { calls.status.push(code); res._status = code; return res; },
    json: (body: any) => { calls.json.push(body); res._json = body; return res; },
    end: () => {},
  };
  res._status = 200; // default like browser
  res._calls = calls;
  return res;
}

const { default: authMeHandler } = await import('./auth.js');

test('Auth/me API Handler Tests', async (t) => {
  await t.test('should return user information for valid access token', async () => {
    const jti = 'valid-jti-123';
    const token = jwt.sign({ sub: 'testuser', jti, type: 'access', pc: 0 }, SECRET_KEY, { expiresIn: '1h' });
    const req = createMockRequest(`Bearer ${token}`);
    const res = createMockResponse();
    await authMeHandler(req as any, res as any);
    assert.equal(res._status, 200);
    assert.deepEqual(res._json, { id: 1, username: 'testuser', email: 'test@example.com', is_admin: false });
  });

  await t.test('should return 401 for missing authorization header', async () => {
    const req = createMockRequest();
    const res = createMockResponse();
    await authMeHandler(req as any, res as any);
    assert.equal(res._status, 401);
    assert.deepEqual(res._json, { error: 'Missing or invalid authorization header' });
  });

  await t.test('should return 401 for expired token', async () => {
    const token = jwt.sign({ sub: 'testuser', jti: 'valid-jti-123', type: 'access', pc: 0 }, SECRET_KEY, { expiresIn: '-1s' });
    const req = createMockRequest(`Bearer ${token}`);
    const res = createMockResponse();
    await authMeHandler(req as any, res as any);
    assert.equal(res._status, 401);
    assert.deepEqual(res._json, { error: 'Invalid or expired token' });
  });

  await t.test('should return 401 for malformed token', async () => {
    const req = createMockRequest('Bearer not-a-jwt');
    const res = createMockResponse();
    await authMeHandler(req as any, res as any);
    assert.equal(res._status, 401);
    assert.deepEqual(res._json, { error: 'Invalid or expired token' });
  });

  await t.test('should return 401 for revoked token', async () => {
    const token = jwt.sign({ sub: 'testuser', jti: 'revoked-jti', type: 'access', pc: 0 }, SECRET_KEY, { expiresIn: '1h' });
    const req = createMockRequest(`Bearer ${token}`);
    const res = createMockResponse();
    await authMeHandler(req as any, res as any);
    assert.equal(res._status, 401);
    assert.deepEqual(res._json, { error: 'Token has been revoked' });
  });

  await t.test('should return 401 for missing claims', async () => {
    const token = jwt.sign({ sub: 'testuser', type: 'access' }, SECRET_KEY, { expiresIn: '1h' });
    const req = createMockRequest(`Bearer ${token}`);
    const res = createMockResponse();
    await authMeHandler(req as any, res as any);
    assert.equal(res._status, 401);
    assert.deepEqual(res._json, { error: 'Invalid authentication credentials' });
  });

  await t.test('should return 401 for deleted user', async () => {
    const token = jwt.sign({ sub: 'nonexistentuser', jti: 'valid-jti-123', type: 'access', pc: 0 }, SECRET_KEY, { expiresIn: '1h' });
    const req = createMockRequest(`Bearer ${token}`);
    const res = createMockResponse();
    await authMeHandler(req as any, res as any);
    assert.equal(res._status, 401);
    assert.deepEqual(res._json, { error: 'User not found' });
  });

  await t.test('should return 401 for password change', async () => {
    const token = jwt.sign({ sub: 'passwordchangeduser', jti: 'valid-jti-123', type: 'access', pc: 0 }, SECRET_KEY, { expiresIn: '1h' });
    const req = createMockRequest(`Bearer ${token}`);
    const res = createMockResponse();
    await authMeHandler(req as any, res as any);
    assert.equal(res._status, 401);
    assert.deepEqual(res._json, { error: 'Password changed; please sign in again.' });
  });
});
