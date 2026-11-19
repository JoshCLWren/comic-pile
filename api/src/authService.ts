import jwt from 'jsonwebtoken';
import { findAuthUser, isTokenRevoked } from './authRepository.js';
import type { UserResponse } from './authTypes.js';

const SECRET_KEY = process.env.SECRET_KEY || '';
if (!SECRET_KEY) throw new Error('SECRET_KEY environment variable must be set');

type VerifiedAccessClaims = {
  sub: string;
  jti: string;
  type: string;
  exp: number;
  pc?: number;
};

function isStringValue(value: unknown): value is string {
  return Object.prototype.toString.call(value) === '[object String]';
}

function isNumberValue(value: unknown): value is number {
  return Object.prototype.toString.call(value) === '[object Number]';
}

function verifyToken(token: string): VerifiedAccessClaims {
  try {
    // SAFETY: jwt.verify returns the decoded token payload for a valid HS256 token; fields are validated before use.
    const payload = jwt.verify(token, SECRET_KEY, { algorithms: ['HS256'] }) as {
      sub?: unknown;
      jti?: unknown;
      type?: unknown;
      exp?: unknown;
      pc?: unknown;
    };

    // Validate required claims
    if (!isStringValue(payload.sub)) {
      throw new Error('Invalid subject claim');
    }

    if (!isStringValue(payload.jti)) {
      throw new Error('Invalid JTI claim');
    }

    if (payload.type !== 'access') {
      throw new Error('Invalid token type');
    }

    const exp = isNumberValue(payload.exp) ? payload.exp : 0;
    if (isNumberValue(payload.pc)) {
      return {
        sub: payload.sub,
        jti: payload.jti,
        type: 'access',
        exp,
        pc: payload.pc,
      };
    }
    return {
      sub: payload.sub,
      jti: payload.jti,
      type: 'access',
      exp,
    };
  } catch (error) {
    throw new Error(`Token verification failed: ${error instanceof Error ? error.message : 'Unknown error'}`);
  }
}

/** Validate credentials and return the authenticated identity. */
export async function getAuthenticatedUser(authHeader: string | undefined): Promise<UserResponse> {
  if (!authHeader || !authHeader.startsWith('Bearer ')) {
    throw new Error('Missing or invalid authorization header');
  }
  const claims = verifyToken(authHeader.substring(7));
  if (await isTokenRevoked(claims.sub, claims.jti)) {
    throw new Error('Token has been revoked');
  }
  const row = await findAuthUser(claims.sub);
  if (!row) throw new Error('User not found');
  const userPc = row.password_changed_at
    ? Math.floor(new Date(row.password_changed_at).getTime() / 1000)
    : 0;
  if (claims.pc !== undefined && claims.pc < userPc) {
    throw new Error('Password changed; please sign in again.');
  }
  return { id: row.id, username: row.username, email: row.email, is_admin: row.is_admin };
}
