# Phase 8: Production Rollout Checklist

This document provides a comprehensive checklist for deploying Phase 8 (user authentication, data isolation, session management) to production.

## Pre-Deployment Checklist

Before deploying to production, verify all of the following:

- [ ] **Environment variables configured in Railway**
  - `DATABASE_URL` - PostgreSQL connection string
  - `SECRET_KEY` - Minimum 32-character secret for JWT signing
  - `ALGORITHM` - HS256 (default)
  - `ACCESS_TOKEN_EXPIRE_MINUTES` - 30 (recommended)
  - `JWT_SECRET_KEY` - Same as SECRET_KEY for consistency

- [ ] **Database backup taken**
  - Run: `make db-dump` or create manual pg_dump
  - Verify backup contains all tables: users, threads, messages, sessions, dice_rolls, queue_items
  - Store backup in safe location before migration

- [ ] **All tests passing locally**
  - Run: `pytest` (full test suite)
  - Verify all 90+ tests pass
  - Pay attention to: auth tests, session tests, thread isolation tests

- [ ] **Linting clean**
  - Run: `make lint` or `bash scripts/lint.sh`
  - No ruff errors or warnings
  - No pyright type errors
  - No ESLint errors for static JS
  - No htmlhint errors for templates

- [ ] **Coverage meets threshold (96%)**
  - Run: `pytest --cov=comic_pile --cov-fail-under=96`
  - Review any coverage gaps in new authentication code
  - Ensure all auth paths are tested: login, logout, token refresh, session resume

## Deployment Steps

### 1. Apply Alembic Migrations

```bash
# Activate virtual environment
source .venv/bin/activate

# Run migrations
make migrate
# Or directly: alembic upgrade head
```

**Migration summary for Phase 8:**
- `a1b2c3d4_add_users_id_1_claim.py` - Handles the special users.id=1 claim behavior
- `e5f6g7h8_add_session_tracking.py` - Adds session_id column to track active sessions
- No breaking schema changes to existing tables

**If migration fails:**
- Check database connection: `railway logs` or `alembic current`
- Verify migration file exists: `ls alembic/versions/`
- Run migration manually: `alembic upgrade head --sql` to see what would run

### 2. Deploy Backend

**Railway deployment:**
- Ensure `railway.json` or `Procfile` references correct entry point
- Push to GitHub (triggers Railway deployment)
- Monitor deployment: `railway status`
- Check logs: `railway logs --tail`

**Expected during first deployment:**
- Database tables created if not exists
- No data loss for existing users
- users.id=1 claim behavior activates on first login

**Health check endpoint:**
```bash
curl https://your-app.railway.app/health
# Expected: {"status":"healthy"}
```

### 3. Deploy Frontend

**Build and deploy:**
- Static assets built during backend deploy (if using same repo)
- Or: `npm run build` then deploy static/ directory

**Verify frontend loads:**
```bash
curl https://your-app.railway.app/
# Should return HTML with React app
```

### 4. Verify Deployment

**Immediate checks:**
1. Health endpoint responds: `/health`
2. API docs accessible: `/docs`
3. No 500 errors on simple requests
4. Static assets loading correctly

**Monitor Railway logs for:**
- Database connection successful
- No import errors in app startup
- Alembic migration completion message

## Post-Deployment Verification

Run through this checklist within the first hour of deployment.

### Authentication Flow

- [ ] **First registration claims `users.id=1`**
  1. Create first user account via `/api/v1/auth/register`
  2. Check database: `SELECT id, username FROM users ORDER BY id LIMIT 5;`
  3. First user should have `id=1`
  4. This is expected - the claim mechanism ensures first user gets id=1
  5. Subsequent users get normal auto-increment IDs

- [ ] **Existing threads show up for claimed user**
  1. Login as first user (users.id=1)
  2. Call `GET /api/v1/threads/`
  3. Verify any existing threads are visible
  4. If no existing threads, create a new one and verify it saves
  5. Check database: `SELECT * FROM threads WHERE user_id=1;`

- [ ] **Session resume behavior works**
  1. Login and get access_token
  2. Call `GET /api/v1/sessions/current` with token
  3. Should return session with `selected_thread_id` or null
  4. Set a thread as active: `PUT /api/v1/sessions/current` with thread_id
  5. Call again and verify `selected_thread_id` persists
  6. Logout and verify session tracking ends

- [ ] **New users see isolated data (test with second account)**
  1. Register second user: `POST /api/v1/auth/register` (different email)
  2. Login as second user
  3. Call `GET /api/v1/threads/` - should be empty
  4. Create a new thread: `POST /api/v1/threads/`
  5. Verify thread is visible only to this user
  6. Login as first user again - original threads still visible
  7. Second user's thread NOT visible to first user

- [ ] **Login/logout works**
  1. Login: `POST /api/v1/auth/login` with correct credentials
     - Returns 200 with access_token
  2. Login with wrong password: `POST /api/v1/auth/login`
     - Returns 401 with error detail
  3. Logout: `POST /api/v1/auth/logout`
     - Returns 200
     - Token is now revoked
  4. Use same token after logout: `GET /api/v1/users/me`
     - Returns 401 (token revoked)

### Game Flow Verification

- [ ] **Rate/roll/queue flows work**
  1. Login and select a thread
  2. Create a roll: `POST /api/v1/rolls/` with dice configuration
  3. Verify roll is created in database
  4. Check queue: `GET /api/v1/queue/` shows pending rolls
  5. Process queue (if auto-processing enabled)
  6. Verify roll status changes to completed
  7. Retrieve completed roll: `GET /api/v1/rolls/{id}`
  8. Verify dice results are visible

### Security Verification

- [ ] **No unauthenticated HTML endpoints accessible**
  1. Access root `/` without auth token
     - Should return HTML (React app is public)
  2. Access `/docs` without auth token
     - Should return Swagger UI (acceptable)
  3. Access `/api/v1/users/me` without token
     - Returns 401 (correct)
  4. Access `/api/v1/threads/` without token
     - Returns 401 (correct)
  5. Access `/api/v1/rolls/` without token
     - Returns 401 (correct)
  6. Try to access admin endpoints without admin flag
     - Returns 403 (correct)

## Rollback Plan

If critical issues occur after deployment, follow these steps.

### Frontend Rollback

**Railway:**
```bash
# View deployment history
railway status

# Rollback to previous deployment
railway rollback
```

**Git-based rollback:**
```bash
# If using automatic deployments
git revert <commit-hash>
git push origin main
# Railway auto-deploys on push
```

### Backend Rollback

#### Option 1: Railway rollback (fastest)
```bash
railway rollback
# Reverts to previous deployed version
```

#### Option 2: Revert code and redeploy
```bash
git checkout <previous-commit-hash>
git push --force origin main  # Only if safe!
# Wait for Railway to redeploy
```

### Database Rollback

**Alembic downgrade:**
```bash
# Check current revision
alembic current

# Downgrade one step
alembic downgrade -1

# Or downgrade to specific revision
alembic downgrade <revision-hash>
```

**Manual rollback (if migration corrupted data):**
```bash
# Restore from backup
psql $DATABASE_URL < backup_$(date +%Y%m%d).sql
```

**Phase 8 specific rollbacks:**
- `a1b2c3d4_add_users_id_1_claim.py` - Downgrade removes claim table
- `e5f6g7h8_add_session_tracking.py` - Downgrade removes session_id columns
- These migrations are designed to be safely reversible

### Emergency Data Recovery

If data is corrupted:
1. Stop application: `railway down`
2. Restore from backup: `psql $DATABASE_URL < backup_file.sql`
3. Verify data integrity
4. Restart application: `railway up`
5. Monitor logs for errors

## Data Migration Notes

### The `users.id=1` Claim Behavior

**What it is:**
The first user to register in the system "claims" the database ID 1. This ensures that early/administrative users have predictable, low-numbered IDs.

**Why it exists:**
- Prevents ID collision with any pre-existing data
- Makes admin user identification easier (id=1 is often admin)
- First-user gets special status for system management

**What happens:**
1. First user registers → `INSERT INTO users ... RETURNING id`
2. If no users exist, claim mechanism assigns id=1
3. Subsequent users get normal auto-increment (2, 3, 4, ...)

**Verification:**
```sql
-- Check who has id=1
SELECT id, username, email, created_at FROM users WHERE id = 1;

-- List all users by ID
SELECT id, username, created_at FROM users ORDER BY id;
```

### Existing Data Handling

**Pre-deployment data:**
- Existing users without emails continue to work
- They can login with username/password after setting up auth
- No automatic data modification

**New registrations:**
- All new users must provide email and password
- Email must be unique
- Password is hashed with PBKDF2 before storage

**Thread ownership:**
- Existing threads keep their original user_id
- No thread reassignment occurs
- Access control respects user_id relationships

**Session data:**
- New session tracking tables created
- No migration of old session data (sessions were stateless before)
- New sessions use session_id tracking

**Rollback safety:**
- All migrations are reversible
- Downgrade commands restore original schema
- No data destruction in normal rollback
- Manual backup restoration only needed for corruption scenarios

## Verification Commands

```bash
# Check deployment health
curl https://your-app.railway.app/health

# Verify database connection
alembic current

# Check migration status
alembic history --verbose

# View recent logs
railway logs --tail --limit 100

# Database queries for verification
psql $DATABASE_URL -c "SELECT COUNT(*) FROM users;"
psql $DATABASE_URL -c "SELECT COUNT(*) FROM threads;"
psql $DATABASE_URL -c "SELECT COUNT(*) FROM sessions;"
```

## Support Contacts

If issues occur during deployment:
- Check Railway status dashboard
- Review application logs: `railway logs`
- Verify database is responsive: `psql $DATABASE_URL`
- Check Alembic migration status: `alembic current`

## Post-Rollout Tasks

After successful deployment and verification:
- [ ] Notify stakeholders of successful deployment
- [ ] Update monitoring dashboards
- [ ] Document any issues encountered
- [ ] Schedule follow-up verification in 24 hours
- [ ] Archive deployment checklist with completion date
