# Phase 3: Database Migrations for Auth

## Purpose
Introduce the minimum schema needed for email/pass auth and token revocation.

## Prerequisites
- ✅ Phase 2 complete (security hardening)
- ✅ Database migration discipline established (create_all disabled in production)
- ✅ Alembic configured and working

## Work Items

### 1. Extend `users` table

Add the following columns to the existing `users` table:

- `email` (unique, nullable initially)
  - Type: String (email)
  - Constraints: UNIQUE, nullable initially
  - Purpose: Email-based login instead of username-only

- `password_hash` (nullable)
  - Type: String (password hash)
  - Constraints: nullable initially
  - Purpose: Store hashed passwords using PBKDF2

- `is_admin` (default false)
  - Type: Boolean
  - Default: false
  - Purpose: Identify admin users for internal endpoint access

### 2. Add `revoked_tokens` table

Create a new table for JWT token revocation:

- `user_id` (foreign key)
  - Type: Integer
  - Foreign key: references users.id
  - Purpose: Associate tokens with user

- `jti` (unique)
  - Type: String (JWT ID)
  - Constraints: UNIQUE
  - Purpose: Unique identifier for each token to allow revocation

- `revoked_at` (timestamp)
  - Type: DateTime
  - Default: CURRENT_TIMESTAMP
  - Purpose: When token was revoked

- `expires_at` (timestamp)
  - Type: DateTime
  - Purpose: When token expires (for cleanup)

## Implementation Steps

1. **Review current database schema**
   - Check `app/models/__init__.py` for current User model
   - Understand existing columns: id, username, created_at

2. **Create Alembic migration**
   - Run: `alembic revision --autogenerate -m "Add auth fields to users table"`
   - Review generated migration
   - Manually add `revoked_tokens` table schema
   - Verify foreign key constraints

3. **Update SQLAlchemy models**
   - Add `email`, `password_hash`, `is_admin` to User model
   - Create RevokedToken model with all fields
   - Add relationships (RevokedToken.user → User)

4. **Test migration locally**
   - Apply migration to test database
   - Verify schema changes
   - Rollback and re-apply to ensure idempotency

5. **Add tests for new schema**
   - Test User model with new fields
   - Test RevokedToken model
   - Test migration up/down methods

## Go/No-Go Gates

- ✅ Alembic upgrade works on a fresh DB
- ✅ Alembic upgrade works on a prod-like dump
- ✅ All tests pass with new schema
- ✅ Migration can be rolled back cleanly

## Files to Modify

- `alembic/versions/` - New migration file
- `app/models/__init__.py` - Update User model, add RevokedToken model
- `tests/` - Add tests for new schema

## Notes

- **Initial nullability**: `email` and `password_hash` are nullable initially to allow existing users (who have username but no email/password) to continue working
- **Migration strategy**: Existing users won't be disrupted; new fields are optional until they migrate to auth system
- **JTI (JWT ID)**: Unique identifier included in JWT token claims to allow per-token revocation (not just user-based)
