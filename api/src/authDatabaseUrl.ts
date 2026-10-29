import dns from 'node:dns';
import type { PoolConfig } from 'pg';

dns.setDefaultResultOrder('ipv4first');

const SQLALCHEMY_PREFIXES = [
  'postgresql+asyncpg://',
  'postgresql+psycopg2://',
  'postgresql+psycopg://',
] as const;

/** Rewrite SQLAlchemy/libpq URL schemes to the postgresql:// form node-pg accepts. */
export function normalizePostgresUrl(raw: string): string {
  const trimmed = raw.trim();
  for (const prefix of SQLALCHEMY_PREFIXES) {
    if (trimmed.startsWith(prefix)) {
      return `postgresql://${trimmed.slice(prefix.length)}`;
    }
  }
  if (trimmed.startsWith('postgres://')) {
    return `postgresql://${trimmed.slice('postgres://'.length)}`;
  }
  return trimmed;
}

function isNeonHost(hostname: string): boolean {
  return hostname === 'neon.tech' || hostname.endsWith('.neon.tech');
}

/**
 * Build a node-pg Pool config that matches how Python/asyncpg talks to Postgres.
 *
 * ComicPile DATABASE_URL values are SQLAlchemy asyncpg URLs, often with libpq
 * query params (`sslmode=require`, `channel_binding=require`). Passing that
 * string straight to `pg.Pool` makes node-pg treat `require` as verify-full
 * and forwards channel binding. The signed-in auth/me path then waits for
 * `connectionTimeoutMillis` (5s) and returns 500. Parse into discrete fields
 * instead, prefer IPv4, and use libpq-compatible TLS for `sslmode=require`.
 */
export function buildAuthPoolConfig(rawUrl: string): PoolConfig {
  const normalized = normalizePostgresUrl(rawUrl);
  let parsed: URL;
  try {
    parsed = new URL(normalized);
  } catch {
    throw new Error('DATABASE_URL is not a valid PostgreSQL URL');
  }

  const hostname = decodeURIComponent(parsed.hostname);
  if (!hostname) {
    throw new Error('DATABASE_URL is missing a host');
  }

  const sslmode = (parsed.searchParams.get('sslmode') || parsed.searchParams.get('ssl') || '')
    .trim()
    .toLowerCase();
  const wantsTls =
    sslmode !== 'disable' &&
    (sslmode === 'require' ||
      sslmode === 'prefer' ||
      sslmode === 'verify-ca' ||
      sslmode === 'verify-full' ||
      sslmode === 'true' ||
      sslmode === '1' ||
      isNeonHost(hostname));

  const config: PoolConfig = {
    host: hostname,
    port: parsed.port ? Number(parsed.port) : 5432,
    user: decodeURIComponent(parsed.username),
    password: decodeURIComponent(parsed.password),
    database: decodeURIComponent(parsed.pathname.replace(/^\//, '')),
    max: 2,
    idleTimeoutMillis: 30000,
    connectionTimeoutMillis: 5000,
    allowExitOnIdle: true,
  };

  if (wantsTls) {
    config.ssl = {
      rejectUnauthorized: sslmode === 'verify-full' || sslmode === 'verify-ca',
    };
  }

  return config;
}
