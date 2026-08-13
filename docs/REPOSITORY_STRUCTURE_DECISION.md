# Repository Structure Decision: Monorepo vs Split Repo

## Date: 2026-08-13

## Context
Issue #640 asks to evaluate whether ComicPile should keep a frontend/API monorepo or split into separate repositories.

## Analysis

### Frontend/Backend Change Coupling

Analysis of recent commits shows significant coupling between frontend and backend:

When backend API changes are made (e.g., adding/modifying endpoints in `app/api/` or `app/services/`):
- Frontend OpenAPI types must be regenerated (`frontend/src/generated/openapi.json` and `.ts`)
- Sometimes frontend services or components that use those APIs need updates

Examples:
- Commit 6ea15ee6: Added database-backed release ledger API → Updated frontend OpenAPI types
- Commit ace01dd1: Surface ComicVine intelligence → Updated frontend OpenAPI types + added frontend hooks/components
- Commit afba1ae8: Allow blocked rolls to switch → Updated backend API only (less coupling)

This indicates **moderate to high coupling** - backend API changes frequently require frontend updates.

### Complexity Comparison

#### Keep Monorepo (Current Approach):

**CI Complexity:**
- Single CI pipeline that builds, tests, and validates both frontend and backend together
- Atomic validation of frontend-backend compatibility
- Shared Docker image build for consistent environment
- Simplified dependency management between frontend and backend

**Release Complexity:**
- Single coordinated version/deployment
- Atomic rollback capability (both frontend and backend roll back together)
- Simple deployment process (single Vercel deployment that handles both static frontend and API function)

**Rollback Complexity:**
- Simple - revert to previous deployment which contains both frontend and backend
- No risk of frontend/backend version mismatch

**Observability:**
- Unified logging and monitoring
- Single source of truth for version/deployment
- Easy to correlate frontend issues with backend changes

**Local Development:**
- Unified development environment with `make dev`
- Shared database and services
- Instant feedback when making changes that span frontend/backend

**Contract Management:**
- Strong coupling ensures contract consistency
- OpenAPI types generated from source of truth (backend)
- Immediate feedback when breaking changes are made

#### Split Repositories:

**CI Complexity:**
- Two separate CI pipelines (frontend and backend)
- Need for integration testing pipeline to validate contract
- Potential for frontend CI to pass but be incompatible with latest backend
- More complex dependency versioning between repos

**Release Complexity:**
- Two separate versioning systems
- Need for coordinated releases or version compatibility matrix
- Risk of deploying incompatible frontend/backend versions
- More complex rollback procedures (may need to roll back only one repo)

**Rollback Complexity:**
- More complex - need to determine which repo(s) to roll back
- Risk of inconsistency if only one repo is rolled back
- Need for version pinning or compatibility tracking

**Observability:**
- More complex to correlate issues across repos
- Need to track versions of both frontend and backend in error reports
- Potential for "works on my machine" issues due to version mismatches

**Local Development:**
- More complex setup (need to run both repos separately)
- Need to configure API endpoints to point to local backend
- Potential for environment drift between frontend and backend developers

**Contract Management:**
- Increased risk of contract drift
- Need for explicit versioning/OpenAPI publishing
- Potential for breaking changes to go undetected until integration
- Extra work to maintain and version OpenAPI spec

## Decision: KEEP THE MONOREPO

### Rationale
1. **High coupling**: Backend API changes frequently require frontend updates due to the OpenAPI-generated type system
2. **Simplified development**: Unified local development experience with `make dev`
3. **Atomic deployments and rollbacks**: Reduced risk of version mismatch issues
4. **Simplified CI**: Single pipeline that validates the entire system
5. **Strong contract consistency**: Immediate feedback when API changes affect frontend

The coupling observed is not accidental - it's inherent to the architecture where the frontend consumes a strongly-typed API generated from the backend. Splitting would increase complexity without solving the fundamental coupling.

### Vercel Preview Environments
As specified in issue #640, Vercel Preview environments are out of scope and intentionally unsupported.

### Impact
This decision means:
- No repository splitting will be performed
- Frontend and backend will continue to live in the same repository
- Existing CI, deployment, and development workflows remain unchanged
- Architecture documentation will reflect this decision

## Related Issues
- Blocks: #640 (this issue)
- Related to: #641 (frontend server-state and bounded-data work)
- Related to: #639 (OpenAPI-generated type work)

## Acceptance Criteria Met
- [x] Measure frontend/backend change coupling after #641 is substantially complete
- [x] Compare CI, release, rollback, observability, local-development, and contract-management complexity for each option
- [x] Explicitly document that Vercel Preview environments are out of scope
- [x] Make one explicit repository-boundary decision (keep monorepo)
- [ ] If a split is selected, open a staged implementation issue with rollback criteria (not applicable)
- [x] Update architecture documentation with the decision (this file)