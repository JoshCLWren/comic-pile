import jwt from 'jsonwebtoken';
import { findAuthUser, isTokenRevoked } from './authRepository.js';
import type { UserResponse } from './authTypes.js';

const SECRET_KEY = process.env.SECRET_KEY || '';
if (!SECRET_KEY) throw new Error('SECRET_KEY environment variable must be set');

function verifyToken(token: string): {
  sub: string;
  jti: string;
  type: string;
  exp: number;
  pc?: number;
} {
  try {
    const payload = jwt.verify(token, SECRET_KEY) as any;
    
    // Validate required claims
    if (!payload.sub || typeof payload.sub !== 'string') {
      throw new Error('Invalid subject claim');
    }
    
    if (!payload.jti || typeof payload.jti !== 'string') {
      throw new Error('Invalid JTI claim');
    }
    
    if (payload.type !== 'access') {
      throw new Error('Invalid token type');
    }
    
    return {
      sub: payload.sub,
      jti: payload.jti,
      type: payload.type,
      exp: payload.exp,
      pc: payload.pc
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
