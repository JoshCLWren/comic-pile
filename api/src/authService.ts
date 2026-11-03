import jwt, { type JwtPayload } from 'jsonwebtoken';
import { findAuthUser, isTokenRevoked } from './authRepository.js';
import type { UserResponse, VerifiedAccessTokenClaims } from './authTypes.js';

const SECRET_KEY = process.env.SECRET_KEY || '';
if (!SECRET_KEY) throw new Error('SECRET_KEY environment variable must be set');

/** The JWT library returns an object for signed JSON claims, or a string. */
function isJwtPayload(value: string | JwtPayload): value is JwtPayload {
  return Object.prototype.toString.call(value) === '[object Object]';
}

function verifyToken(token: string): VerifiedAccessTokenClaims {
  try {
    const payload = jwt.verify(token, SECRET_KEY, { algorithms: ['HS256'] });
    if (!isJwtPayload(payload) || !payload.sub || Object.prototype.toString.call(payload.sub) !== '[object String]') {
      throw new Error('Invalid subject claim');
    }
    if (!payload.jti || Object.prototype.toString.call(payload.jti) !== '[object String]') {
      throw new Error('Invalid JTI claim');
    }
    if (payload.type !== 'access') {
      throw new Error('Invalid token type');
    }

    const claims = {
      sub: payload.sub,
      jti: payload.jti,
      type: 'access',
      exp: payload.exp !== undefined && Number.isFinite(payload.exp) ? payload.exp : 0,
    } satisfies Omit<VerifiedAccessTokenClaims, 'pc'>;
    const passwordEpochClaim: unknown = payload.pc;
    if (
      Object.prototype.toString.call(passwordEpochClaim) === '[object Number]' &&
      Number.isFinite(Number(passwordEpochClaim))
    ) {
      return { ...claims, pc: Number(passwordEpochClaim) };
    }
    return claims;
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
