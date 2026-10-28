import { PoolClient } from 'pg';
import { UserResponse } from './authTypes.js';

// Repository functions for auth
export async function isTokenRevoked(db: PoolClient, username: string, jti: string): Promise<boolean> {
  const result = await db.query(
    `SELECT 1 FROM revoked_tokens rt
     JOIN users u ON rt.user_id = u.id
     WHERE u.username = $1 AND rt.jti = $2`,
    [username, jti]
  );
  return result.rows.length > 0;
}

export async function getUserWithPasswordCheck(db: PoolClient, username: string, tokenPc?: number): Promise<{ user: UserResponse; isRevoked: boolean }> {
  const result = await db.query(
    `SELECT id, username, email, is_admin, password_changed_at
     FROM users
     WHERE username = $1 LIMIT 1`, [username]
  );
  if (result.rows.length === 0) {
    throw new Error('User not found');
  }
  const row = result.rows[0];
  const user: UserResponse = {
    id: row.id,
    username: row.username,
    email: row.email,
    is_admin: row.is_admin,
  };
  const userPc = row.password_changed_at
    ? Math.floor(new Date(row.password_changed_at).getTime() / 1000)
    : 0;
  const isRevoked = tokenPc !== undefined && tokenPc < userPc;
  return { user, isRevoked };
}
