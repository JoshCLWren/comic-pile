export const AUDIT_FIXED_NOW = '2026-08-30T12:00:00.000Z'
export const AUDIT_FIXED_USERNAME = 'ui_audit_reader_2043'

type JsonRecord = Record<string, unknown>

function isJsonRecord(value: unknown): value is JsonRecord {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}

function stableIso(offsetMinutes: number): string {
  return new Date(Date.parse(AUDIT_FIXED_NOW) + offsetMinutes * 60_000).toISOString()
}

function normalizeSessionRecord(record: JsonRecord, index: number): JsonRecord {
  const normalized: JsonRecord = {
    ...record,
    started_at: stableIso(index),
  }

  if ('ended_at' in record) {
    normalized.ended_at = record.ended_at == null ? record.ended_at : stableIso(index + 15)
  }
  if ('created_at' in record) {
    normalized.created_at = stableIso(index)
  }
  if ('updated_at' in record) {
    normalized.updated_at = stableIso(index + 15)
  }

  return normalized
}

/**
 * Replace only volatile, user-visible fixture fields used by audit screenshots.
 * Authentication identity and persisted test data remain untouched on the server.
 */
export function stabilizeAuditApiPayload(pathname: string, payload: unknown): unknown {
  if (pathname === '/api/v1/auth/me' && isJsonRecord(payload)) {
    return { ...payload, username: AUDIT_FIXED_USERNAME }
  }

  if (pathname === '/api/v1/sessions/' && isJsonRecord(payload) && Array.isArray(payload.sessions)) {
    return {
      ...payload,
      sessions: payload.sessions.map((session, index) =>
        isJsonRecord(session) ? normalizeSessionRecord(session, index) : session,
      ),
    }
  }

  if (pathname === '/api/v1/sessions/current/' && isJsonRecord(payload)) {
    return normalizeSessionRecord(payload, 0)
  }

  return payload
}
