import authMeHandler from './auth.js';
import jwt from 'jsonwebtoken';

// Mock database configuration
const SECRET_KEY = 'test-secret-key';

// Mock database pool
const mockPool = {
  query: async (query: string, params: any[]) => {
    console.log('Mock query:', query, params);
    
    if (query.includes('SELECT 1 FROM revoked_tokens')) {
      // Mock revoked tokens check
      if (params[1] === 'revoked-jti') {
        return { rows: [{ id: 1 }] };
      }
      return { rows: [] };
    }
    
    if (query.includes('SELECT id, username, email, is_admin, password_changed_at FROM users')) {
      // Mock user lookup
      if (params[0] === 'testuser') {
        return { 
          rows: [{
            id: 1,
            username: 'testuser',
            email: 'test@example.com',
            is_admin: false,
            password_changed_at: null
          }] 
        };
      }
      if (params[0] === 'nonexistentuser') {
        return { rows: [] };
      }
      if (params[0] === 'passwordchangeduser') {
        return { 
          rows: [{
            id: 2,
            username: 'passwordchangeduser',
            email: 'test2@example.com',
            is_admin: false,
            password_changed_at: new Date()
          }] 
        };
      }
      return { rows: [] };
    }
    
    return { rows: [] };
  },
  connect: async () => ({ release: () => {} }),
};

// Mock express request and response
function createMockRequest(authHeader?: string) {
  const req = {
    headers: {
      authorization: authHeader
    }
  };
  return req;
}

function createMockResponse() {
  const res = {
    setHeader: jest.fn(),
    status: jest.fn().mockReturnThis(),
    json: jest.fn(),
    end: jest.fn()
  };
  return res;
}

// Test suite
import { test } from 'node:test';

test('Auth/me API Handler Tests', async (t) => {
  // Override global pool for testing
  (globalThis as any).pool = mockPool;

  await t.test('should return user information for valid access token', async () => {
    const jti = 'valid-jti-123';
    const token = jwt.sign(
      { sub: 'testuser', jti, type: 'access', pc: 0 },
      SECRET_KEY,
      { expiresIn: '1h' }
    );

    const req = createMockRequest(`Bearer ${token}`);
    const res = createMockResponse();

    await authMeHandler(req as any, res as any);

    expect(res.status).toHaveBeenCalledWith(200);
    expect(res.json).toHaveBeenCalledWith({
      id: 1,
      username: 'testuser',
      email: 'test@example.com',
      is_admin: false
    });
  });

  await t.test('should return 401 for missing authorization header', async () => {
    const req = createMockRequest();
    const res = createMockResponse();

    await authMeHandler(req as any, res as any);

    expect(res.status).toHaveBeenCalledWith(401);
    expect(res.json).toHaveBeenCalledWith({ error: 'Missing or invalid authorization header' });
  });

  await t.test('should return 401 for invalid authorization header format', async () => {
    const req = createMockRequest('InvalidFormat');
    const res = createMockResponse();

    await authMeHandler(req as any, res as any);

    expect(res.status).toHaveBeenCalledWith(401);
    expect(res.json).toHaveBeenCalledWith({ error: 'Missing or invalid authorization header' });
  });

  await t.test('should return 401 for malformed token', async () => {
    const req = createMockRequest('Bearer malformed.token.here');
    const res = createMockResponse();

    await authMeHandler(req as any, res as any);

    expect(res.status).toHaveBeenCalledWith(401);
    expect(res.json).toHaveBeenCalledWith({ error: 'Invalid or expired token' });
  });

  await t.test('should return 401 for expired token', async () => {
    const jti = 'expired-jti';
    const token = jwt.sign(
      { sub: 'testuser', jti, type: 'access', pc: 0 },
      SECRET_KEY,
      { expiresIn: '-1h' } // Expired 1 hour ago
    );

    const req = createMockRequest(`Bearer ${token}`);
    const res = createMockResponse();

    await authMeHandler(req as any, res as any);

    expect(res.status).toHaveBeenCalledWith(401);
    expect(res.json).toHaveBeenCalledWith({ error: 'Invalid or expired token' });
  });

  await t.test('should return 401 for token with wrong type', async () => {
    const jti = 'wrong-type-jti';
    const token = jwt.sign(
      { sub: 'testuser', jti, type: 'refresh', pc: 0 },
      SECRET_KEY,
      { expiresIn: '1h' }
    );

    const req = createMockRequest(`Bearer ${token}`);
    const res = createMockResponse();

    await authMeHandler(req as any, res as any);

    expect(res.status).toHaveBeenCalledWith(401);
    expect(res.json).toHaveBeenCalledWith({ error: 'Invalid authentication credentials' });
  });

  await t.test('should return 401 for token with missing sub claim', async () => {
    const jti = 'no-sub-jti';
    const token = jwt.sign(
      { jti, type: 'access', pc: 0 },
      SECRET_KEY,
      { expiresIn: '1h' }
    );

    const req = createMockRequest(`Bearer ${token}`);
    const res = createMockResponse();

    await authMeHandler(req as any, res as any);

    expect(res.status).toHaveBeenCalledWith(401);
    expect(res.json).toHaveBeenCalledWith({ error: 'Invalid authentication credentials' });
  });

  await t.test('should return 401 for token with missing jti claim', async () => {
    const token = jwt.sign(
      { sub: 'testuser', type: 'access', pc: 0 },
      SECRET_KEY,
      { expiresIn: '1h' }
    );

    const req = createMockRequest(`Bearer ${token}`);
    const res = createMockResponse();

    await authMeHandler(req as any, res as any);

    expect(res.status).toHaveBeenCalledWith(401);
    expect(res.json).toHaveBeenCalledWith({ error: 'Token has been revoked' });
  });

  await t.test('should return 401 for revoked token', async () => {
    const jti = 'revoked-jti';
    const token = jwt.sign(
      { sub: 'testuser', jti, type: 'access', pc: 0 },
      SECRET_KEY,
      { expiresIn: '1h' }
    );

    const req = createMockRequest(`Bearer ${token}`);
    const res = createMockResponse();

    await authMeHandler(req as any, res as any);

    expect(res.status).toHaveBeenCalledWith(401);
    expect(res.json).toHaveBeenCalledWith({ error: 'Token has been revoked' });
  });

  await t.test('should return 401 for non-existent user', async () => {
    const jti = 'nonexistent-user-jti';
    const token = jwt.sign(
      { sub: 'nonexistentuser', jti, type: 'access', pc: 0 },
      SECRET_KEY,
      { expiresIn: '1h' }
    );

    const req = createMockRequest(`Bearer ${token}`);
    const res = createMockResponse();

    await authMeHandler(req as any, res as any);

    expect(res.status).toHaveBeenCalledWith(401);
    expect(res.json).toHaveBeenCalledWith({ error: 'User not found' });
  });

  await t.test('should return 401 for token issued before password change', async () => {
    const jti = 'password-change-jti';
    const token = jwt.sign(
      { sub: 'passwordchangeduser', jti, type: 'access', pc: 0 }, // pc=0 (old password)
      SECRET_KEY,
      { expiresIn: '1h' }
    );

    const req = createMockRequest(`Bearer ${token}`);
    const res = createMockResponse();

    await authMeHandler(req as any, res as any);

    expect(res.status).toHaveBeenCalledWith(401);
    expect(res.json).toHaveBeenCalledWith({ error: 'Password changed; please sign in again.' });
  });
});