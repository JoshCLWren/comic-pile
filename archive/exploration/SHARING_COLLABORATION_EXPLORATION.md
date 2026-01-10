# Sharing and Collaboration Features - Exploration Document

**Task ID:** feat-011
**Created:** 2026-01-07
**Status:** Exploration Complete

## Executive Summary

Comic-pile is currently a single-user application with no authentication or multi-user support. Adding sharing/collaboration features would enable use cases like book clubs, shared households, and social reading progress sharing. This document explores what it would take to implement these features.

---

## Current State Analysis

### Architecture Overview

**Single-User Design:**
- User model exists but has minimal fields (id, username, created_at)
- No authentication system (all endpoints are public)
- No authorization layer (anyone can access any data)
- Hardcoded `user_id=1` throughout codebase (main.py:341, 394, etc.)

**Data Ownership Model:**
- Thread.user_id - owns threads and reading lists
- Session.user_id - owns reading sessions
- Event linked to Session (indirect user ownership)
- Settings are global (not user-scoped)

**Existing Data Export/Import:**
- CSV export for threads (title, format, issues_remaining)
- JSON export for full database backup
- CSV import for threads
- JSON import (wipe and restore)
- CSV import for review timestamps
- Markdown export for session summaries

**No Sharing Infrastructure:**
- No user accounts/registration
- No login/authentication
- No shared resources or groups
- No permissions system
- No sharing UI or workflows

---

## Use Cases

### 1. Book Clubs (Reading Groups)

**Scenario:** A group of 5-10 people read the same comics together and discuss.

**What They Want to Share:**
- Reading lists (which comics to read together)
- Reading progress (where everyone is in the reading list)
- Ratings and reviews (what everyone thought)
- Discussion notes (annotations on issues)
- Session summaries (what was read in each meeting)

**Desired Features:**
- Create a "book club" group
- Invite members to the group
- Shared reading queue visible to all members
- Each member tracks their own progress
- See other members' progress in shared view
- Compare ratings side-by-side
- Group chat/discussion for each issue
- Meeting scheduler with assigned readings

### 2. Shared Households

**Scenario:** Family members with separate devices but shared comic collection.

**What They Want to Share:**
- Single database of comics (thread list)
- Who has read what
- Current queue (what's next to read)
- Who has which physical copy
- Family reading goals

**Desired Features:**
- Family account with sub-accounts
- Shared thread library
- Individual reading progress per user
- "Who is reading this now?" status
- Family dashboard showing everyone's progress
- Check-out/check-in system for physical comics

### 3. Social Sharing (Public Profile)

**Scenario:** Individual users want to share their reading lists and progress publicly.

**What They Want to Share:**
- Public reading list
- Reading progress stats
- Ratings and reviews
- Session summaries
- Achievement badges

**Desired Features:**
- Public profile URL
- Shareable reading list link
- Social media integration (share progress)
- Opt-in visibility controls
- Anonymous mode for privacy

### 4. Data Portability (Personal Backup)

**Scenario:** Users want to backup and restore their data across devices.

**What They Want:**
- Export all data to a file
- Import data to new device
- Merge data from multiple sources
- Version history of backups

**Desired Features:**
- One-click full backup
- Selective backup (threads only, sessions only)
- Cloud backup integration (Dropbox, Google Drive)
- Sync across devices automatically

---

## Technical Options

### Option A: Manual File-Based Sharing

**Approach:** Extend existing export/import functionality with sharing-oriented formats.

**Implementation:**
- Create shareable JSON schema (subset of full export)
- Add "Share" button to export reading list
- Add "Import Shared List" button to import
- No server-side changes needed
- No authentication required

**Pros:**
- Minimal development effort (4-6 hours)
- Works immediately with existing codebase
- No security/privacy concerns
- Simple to understand and use

**Cons:**
- Manual process (email files, upload to cloud)
- No real-time synchronization
- No collaboration features (discussions, shared progress)
- Version conflicts when multiple people edit
- No access control

**Best For:** Book clubs with one organizer, simple sharing scenarios

---

### Option B: Multi-User Single Database

**Approach:** Add authentication and user accounts to existing database.

**Implementation:**

**Phase 1: Authentication (8-12 hours)**
- Add password field to User model
- Add email field to User model
- Implement password hashing (bcrypt)
- Create login endpoint (`POST /auth/login`)
- Create registration endpoint (`POST /auth/register`)
- Add JWT token generation/validation
- Add authentication middleware to protect endpoints
- Update all hardcoded `user_id=1` to use authenticated user

**Phase 2: User-Scoped Data (4-6 hours)**
- Make Settings model user-scoped (add user_id)
- Update all queries to filter by user_id
- Update cache keys to include user_id
- Add user context to all responses

**Phase 3: Sharing Groups (12-16 hours)**
- Create Group model (id, name, created_by, created_at)
- Create GroupMember model (group_id, user_id, role, joined_at)
- Create SharedThread model (group_id, thread_id, shared_by, shared_at)
- Add group management endpoints (create, invite, leave)
- Add thread sharing endpoints (share with group, unshare)
- Update thread queries to show shared threads
- Add group dashboard UI

**Phase 4: Collaboration Features (16-20 hours)**
- Add permissions system (admin, member, viewer)
- Add per-user progress tracking on shared threads
- Add comments/discussion on threads
- Add group activity feed
- Add read status indicators (who read what)
- Add notification system (optional)

**Total Effort:** 40-54 hours

**Pros:**
- Full collaboration features
- Real-time synchronization
- Access control and permissions
- Scalable to many users
- Professional multi-user application

**Cons:**
- Large development effort
- Requires authentication system overhaul
- Database migration complexity
- Security and privacy concerns
- Requires significant testing

**Best For:** Production application with professional collaboration features

---

### Option C: Shared Collections (Read-Only Sharing)

**Approach:** Allow users to share their reading lists as read-only collections.

**Implementation:**

**Phase 1: Share Links (6-8 hours)**
- Create ShareToken model (id, user_id, thread_ids, created_at, expires_at)
- Add "Generate Share Link" button
- Create public view endpoint (`/share/{token}`)
- Show shared threads in read-only format
- No authentication required for viewing

**Phase 2: Shareable Reading Lists (8-10 hours)**
- Create ReadingList model (id, user_id, name, description, created_at)
- Create ReadingListItem model (list_id, thread_id, position)
- Allow users to create multiple reading lists
- Share reading lists instead of full library
- Add public list viewing

**Phase 3: Import Shared Lists (4-6 hours)**
- Add "Import to My Queue" button on shared lists
- Copy shared threads to user's library
- Preserve ratings and notes (if desired)
- Merge with existing threads by title/format

**Total Effort:** 18-24 hours

**Pros:**
- Moderate development effort
- No authentication required
- No security/privacy concerns (read-only)
- Works for book clubs and social sharing
- Can be extended later

**Cons:**
- Read-only (no collaboration)
- No real-time synchronization
- Manual import/export workflow
- Limited access control

**Best For:** Social sharing, book club reading lists, public profiles

---

### Option D: Family Mode (Single Household)

**Approach:** Add family account mode with sub-users.

**Implementation:**

**Phase 1: Family Accounts (8-10 hours)**
- Add family_account_id to User model
- Create FamilyAccount model (id, name, settings)
- Add account owner role
- Add family member role
- Create family management UI

**Phase 2: Shared Library (6-8 hours)**
- Create FamilyThread model (family_id, thread data)
- Threads belong to family, not individual users
- Individual progress tracked in FamilyProgress model
- Show shared library to all family members

**Phase 3: Per-User Progress (6-8 hours)**
- Create FamilyProgress model (user_id, thread_id, issues_read, last_read_at)
- Track each family member's progress independently
- Show progress comparison in family dashboard
- Add "Who is reading this now?" indicator

**Total Effort:** 20-26 hours

**Pros:**
- Focused on household use case
- Shared library with individual progress
- Easier than full multi-user system
- Can add simple authentication later

**Cons:**
- Limited to single household
- Not suitable for book clubs or public sharing
- Still requires account management
- Data model complexity

**Best For:** Shared households, families

---

## Recommended Approach

### Short-Term (Immediate Value): Option A + C Hybrid

**Implementation Plan (20-24 hours):**

**1. Enhanced Sharing Export (4-6 hours)**
- Add "Export for Sharing" button
- Export subset of data (threads + ratings + settings)
- Clean JSON schema focused on sharing
- Include share metadata (created_by, description)

**2. Share Links for Collections (6-8 hours)**
- Create ShareToken model
- Generate unique shareable URLs
- Public read-only view of shared data
- Optional password protection
- Expiration date support

**3. Import Shared Lists (6-8 hours)**
- Add "Import Shared List" endpoint
- Parse share token and display shared data
- One-click import to user's queue
- Merge conflicts resolution (ask user)
- Preserve attribution (original creator)

**4. UI Updates (4-6 hours)**
- Add "Share" button to queue page
- Add "Browse Shared Lists" page
- Add import confirmation modal
- Add sharing options (password, expiration)

**Value Delivered:**
- Book clubs can share reading lists via links
- Users can import curated lists from others
- Public profiles for sharing reading lists
- Simple sharing workflow without authentication

**Limitations:**
- Read-only sharing
- No real-time collaboration
- Manual import/export
- No discussion features

**Next Steps:**
1. Evaluate user adoption of sharing features
2. Gather feedback on use cases
3. Consider authentication (Option B) if collaboration needed

---

### Long-Term (Full Collaboration): Option B

**When to Consider:**
- Users request real-time collaboration
- Book clubs want group discussion features
- Growing demand for multi-user support
- Business case for professional features

**Implementation Phases:**

**Phase 1: Foundation (12-16 hours)**
- Authentication system
- User accounts
- Database migrations

**Phase 2: User Isolation (6-8 hours)**
- User-scoped data
- Query filtering
- Testing multi-user scenarios

**Phase 3: Groups (16-20 hours)**
- Group model
- Sharing permissions
- Group management

**Phase 4: Collaboration (20-24 hours)**
- Real-time features
- Discussion system
- Activity feed

**Total Investment:** 54-68 hours

---

## Implementation Details

### Database Schema Changes

**For Option A (File-Based Sharing):**
- No schema changes needed
- ShareToken model (optional, for link sharing)

**For Option C (Read-Only Sharing):**
```python
class ShareToken(Base):
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    token: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    threads_json: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    password_hash: Mapped[str | None] = mapped_column(String(255), nullable=True)
```

**For Option B (Full Multi-User):**
```python
class User(Base):
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    username: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))

class Group(Base):
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))

class GroupMember(Base):
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    group_id: Mapped[int] = mapped_column(ForeignKey("groups.id"), nullable=False)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    role: Mapped[str] = mapped_column(String(20), nullable=False)  # admin, member, viewer
    joined_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))

class SharedThread(Base):
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    group_id: Mapped[int] = mapped_column(ForeignKey("groups.id"), nullable=False)
    thread_id: Mapped[int] = mapped_column(ForeignKey("threads.id"), nullable=False)
    shared_by: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    shared_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))

class ThreadProgress(Base):
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    thread_id: Mapped[int] = mapped_column(ForeignKey("threads.id"), nullable=False)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    issues_read: Mapped[int] = mapped_column(Integer, default=0)
    last_read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    rating: Mapped[float | None] = mapped_column(Float, nullable=True)

class ThreadComment(Base):
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    thread_id: Mapped[int] = mapped_column(ForeignKey("threads.id"), nullable=False)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    comment: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
```

### API Endpoints

**For Option C (Read-Only Sharing):**
```
POST   /share/create                    - Create shareable link
GET    /share/{token}                   - View shared list (public)
GET    /share/{token}/info              - Get share metadata
POST   /share/{token}/import            - Import shared list
DELETE /share/{token}                   - Delete share link (owner only)
GET    /shares/                         - List user's shares (authenticated)
```

**For Option B (Full Multi-User):**
```
# Authentication
POST   /auth/register                   - Register new user
POST   /auth/login                      - Login (returns JWT)
POST   /auth/logout                     - Logout (optional)

# Groups
POST   /groups/                         - Create group
GET    /groups/                         - List user's groups
GET    /groups/{group_id}               - Get group details
PUT    /groups/{group_id}               - Update group (admin only)
DELETE /groups/{group_id}               - Delete group (admin only)
POST   /groups/{group_id}/join          - Join group (by invite code)
POST   /groups/{group_id}/leave         - Leave group
POST   /groups/{group_id}/invite        - Invite user (email)
GET    /groups/{group_id}/members       - List members
PUT    /groups/{group_id}/members/{user_id}  - Update member role
DELETE /groups/{group_id}/members/{user_id} - Remove member

# Shared Threads
POST   /groups/{group_id}/threads       - Share thread to group
GET    /groups/{group_id}/threads       - List shared threads
DELETE /groups/{group_id}/threads/{thread_id} - Unshare thread

# Progress Tracking
GET    /threads/{thread_id}/progress    - Get progress for all users
POST   /threads/{thread_id}/progress    - Update user progress

# Comments
GET    /threads/{thread_id}/comments    - List comments
POST   /threads/{thread_id}/comments    - Add comment
DELETE /threads/{thread_id}/comments/{comment_id} - Delete comment
```

### Security Considerations

**Option A (File-Based):**
- No security concerns (manual file sharing)
- Users control what they share
- No authentication needed

**Option C (Read-Only Links):**
- Share tokens should be cryptographically secure (UUID v4)
- Optional password protection (bcrypt hash)
- Expiration dates to limit exposure
- Rate limiting on share endpoints
- CORS restrictions for public endpoints
- No sensitive data in share URLs

**Option B (Full Multi-User):**
- **Authentication:** JWT tokens with short expiration
- **Password Security:** bcrypt with salt rounds >= 12
- **Input Validation:** All user inputs validated
- **SQL Injection:** Use SQLAlchemy ORM (already implemented)
- **XSS Prevention:** Escape user-generated content in comments
- **CSRF Protection:** SameSite cookies, CSRF tokens
- **Rate Limiting:** Prevent brute force attacks on auth
- **Authorization:** Check permissions on every protected endpoint
- **Data Isolation:** Ensure users only see their own data
- **Audit Logging:** Log all group management actions
- **Privacy:** Opt-in sharing, explicit consent

### Privacy Features

**Required:**
- Explicit consent for sharing
- Easy opt-out/unshare
- Private profile by default
- Export all personal data (GDPR compliance)
- Delete account with all associated data

**Nice-to-Have:**
- Anonymous profiles (username only)
- Hide email from other members
- Visibility controls (public/friends-only/private)
- Read receipts (who viewed your shared list)
- Block/mute other users

---

## Migration Path

### From Current State to Option C

**Step 1: ShareToken Migration**
```sql
CREATE TABLE share_tokens (
    id INTEGER PRIMARY KEY,
    token VARCHAR(64) UNIQUE NOT NULL,
    user_id INTEGER NOT NULL REFERENCES users(id),
    name VARCHAR(200) NOT NULL,
    description TEXT,
    threads_json TEXT NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    expires_at TIMESTAMP WITH TIME ZONE,
    password_hash VARCHAR(255)
);
```

**Step 2: Update Caching**
- Cache share tokens by token
- Add user_id to cache keys for thread queries
- Invalidate share token cache on expiration

**Step 3: Add API Endpoints**
- Create share endpoint
- Public view endpoint (no auth required)
- Import endpoint (merge with existing import logic)

**Step 4: UI Updates**
- Add share button to queue
- Add public view template
- Add import modal
- Update settings page to show shares

**Step 5: Testing**
- Unit tests for share token generation/validation
- Integration tests for sharing workflow
- E2E tests with Playwright
- Test expiration and password protection

---

## Effort Summary

| Option | Development Effort | Testing Effort | Total Effort | Risk |
|--------|-------------------|----------------|--------------|------|
| A: File-Based | 4-6 hours | 2-3 hours | 6-9 hours | Low |
| C: Read-Only Sharing | 18-24 hours | 6-8 hours | 24-32 hours | Medium |
| D: Family Mode | 20-26 hours | 8-10 hours | 28-36 hours | Medium |
| B: Full Multi-User | 54-68 hours | 16-20 hours | 70-88 hours | High |

---

## Recommendations

### Immediate Action (This Sprint)

**Implement Option A + C Hybrid (20-24 hours):**

1. **Week 1: Foundation (8-10 hours)**
   - Create ShareToken model and migration
   - Add "Export for Sharing" functionality
   - Create share link generation
   - Add public view endpoint

2. **Week 2: Import Flow (8-10 hours)**
   - Add import shared list endpoint
   - Create import UI with merge options
   - Add share management UI
   - Test end-to-end workflow

3. **Week 3: Polish (4-6 hours)**
   - Add password protection
   - Add expiration dates
   - Improve error handling
   - Add documentation

**Value Delivered:**
- Book clubs can share reading lists via links
- Users can discover new comics from curated lists
- Public profiles for sharing reading progress
- Foundation for future collaboration features

### Future Considerations

**If sharing features are popular:**
1. Gather user feedback on use cases
2. Evaluate need for real-time collaboration
3. Consider implementing Option B (full multi-user)
4. Add discussion features
5. Implement notification system

**If security concerns arise:**
1. Add authentication to protect share links
2. Implement access logging
3. Add rate limiting
4. Review and audit sharing permissions

---

## Conclusion

Comic-pile is currently well-suited for **Option C (Read-Only Sharing)** as a first step toward collaboration features. This approach:

- Requires moderate development effort (24-32 hours total)
- Delivers immediate value for book clubs and social sharing
- Builds on existing export/import functionality
- Avoids authentication complexity initially
- Provides a foundation for future enhancement

The full multi-user system (Option B) is a significant undertaking (70-88 hours) and should be deferred until user demand justifies the investment.

**Recommended Next Steps:**
1. Share this document with stakeholders
2. Confirm priority for sharing features
3. Allocate resources for Option C implementation
4. Create implementation tasks and timeline
5. Proceed with development

---

**Document Version:** 1.0
**Last Updated:** 2026-01-07
**Author:** Ralph Mode Exploration
