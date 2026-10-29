import { Pool } from 'pg';
import { buildAuthPoolConfig } from './authDatabaseUrl.js';

/** Persistence data, including the credential epoch used by the service. */
export interface AuthUserRecord {
  id: number;
  username: string;
  email: string | null;
  is_admin: boolean;
  password_changed_at: Date | string | null;
}

const DATABASE_URL = process.env.DATABASE_URL || '';
if (!DATABASE_URL) throw new Error('DATABASE_URL environment variable must be set');

const pool =
  (globalThis as typeof globalThis & { pool?: Pick<Pool, 'query'> }).pool ||
  new Pool(buildAuthPoolConfig(DATABASE_URL));

/** Read revocation state without making authorization decisions. */
export async function isTokenRevoked(username: string, jti: string): Promise<boolean> {
  const result = await pool.query(
    `SELECT 1 FROM revoked_tokens rt
     JOIN users u ON rt.user_id = u.id
     WHERE u.username = $1 AND rt.jti = $2`,
    [username, jti],
  );
  return result.rows.length > 0;
}

/** Return stored identity and credential epoch, without HTTP or credential decisions. */
export async function findAuthUser(username: string): Promise<AuthUserRecord | null> {
  const result = await pool.query<AuthUserRecord>(
    `SELECT id, username, email, is_admin, password_changed_at
     FROM users
     WHERE username = $1 LIMIT 1`,
    [username],
  );
  return result.rows[0] ?? null;
}
