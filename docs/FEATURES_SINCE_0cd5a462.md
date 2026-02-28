# New Features Guide (Since `0cd5a462ef405f96f591ec31abb66531a1e99a9e`)

This guide covers the major user-facing features added after commit `0cd5a462ef405f96f591ec31abb66531a1e99a9e`.

## What Was Added

1. Collections (create, select roll pool, assign threads).
2. Dependency management (block threads until prerequisites are read).
3. Dependency flowchart visualization.
4. Issue tracking and migration from old threads.
5. Issue-range thread creation (`1-25`, `1, 3, 5-7`).

## 1) Collections

### Create and switch collections

1. Open the Roll page (`/`).
2. In the roll pool controls, use the `Roll pool collection` dropdown.
3. Click `+ New` to open the collection dialog.
4. Enter a name, optionally set `Make this my default collection`, then save.
5. Select the collection in the dropdown to filter the roll pool.

Notes:
- `Roll Pool: All Collections` shows everything.
- Collection selection is persisted for the session in browser storage.

### How collections affect Queue

1. Select a collection on the Roll page.
2. Go to Queue (`/queue`).
3. Queue results are filtered to that active collection.
4. Threads with a collection show a collection badge on the thread card.

## 2) Dependencies (Blocking Rules)

Dependencies let you enforce reading order.

There are now two modes:
- Issue-level (recommended): blocks your thread's next unread issue.
- Thread-level (legacy): blocks the full thread until source thread is completed.

### Add a dependency

1. Go to Queue (`/queue`).
2. On a thread card, click the link icon (`Manage dependencies`).
3. In the modal, search for a prerequisite thread (minimum 2 characters).
4. Select the prerequisite.
5. Choose dependency type (`Issue Level` or `Thread Level`).
6. Click the block button.

Result:
- The target thread becomes blocked until prerequisite conditions are met.
- Blocked threads show a lock indicator (`🔒`) in Queue.

### Remove a dependency

1. Open `Manage dependencies` for the target thread.
2. In either dependency list, click `Remove` on the dependency row.

### Reading blocked threads

- If you try `Read Now` on a blocked thread, the app prevents entry and explains that the thread is blocked.

## 3) Dependency Flowchart

When a thread has dependencies, a visual graph is available in the dependency modal.

### Open and use the flowchart

1. Open `Manage dependencies`.
2. Click `View Flowchart`.
3. Use controls to:
   - Zoom in/out
   - Reset view
4. Hover nodes to see thread details.

Visual behavior:
- Nodes represent threads.
- Edges represent dependency direction.
- Blocked threads are visually marked as blocked.

## 4) Issue Tracking and Migration

Threads now support per-issue progress and next-issue context.

### For existing (old-system) threads

If a thread does not yet have `total_issues`, opening it for reading triggers migration.

1. From Roll or Queue, open thread actions.
2. Click `Read Now`.
3. In `Track Issues for "<thread>"`, enter:
   - `Last Issue Read`
   - `Total Issues`
4. Click `Start Tracking`.

What migration does:
- Creates issue records `#1..#total`.
- Marks `#1..#last_read` as read.
- Sets next unread issue and progress fields.

Validation rules:
- Both fields required.
- Values must be numeric and non-negative.
- `total_issues` must be greater than 0.
- `last_issue_read` cannot exceed `total_issues`.

### Skip migration

- You can click `Skip` and continue with legacy behavior.
- You can migrate the same thread later.

## 5) Creating Threads with Issue Ranges

Queue creation now accepts issue-range input.

### Create from issue range

1. Go to Queue (`/queue`) and click `Add Thread`.
2. Fill `Title` and `Format`.
3. In `Issues (optional)`, enter formats like:
   - `1-25`
   - `1`
   - `1, 3, 5-7`
4. Confirm the preview (`Will create X issues`).
5. Submit.

Behavior:
- The app parses and deduplicates issue numbers.
- Invalid ranges show inline parse errors.
- Successful creation initializes issue-tracking metadata for the thread.

## Roll Experience Changes

The Roll page now includes:

1. Collection control in the main roll view (`Roll pool collection` + `+ New`).
2. Issue-aware rating context when available:
   - Current issue number (`#N`)
   - Total issues context (`#N of M`)
   - Reading progress bar for tracked threads

## API Surface Added (for integrations)

New/expanded endpoints relevant to these features:

- Collections:
  - `POST /api/v1/collections/`
  - `GET /api/v1/collections/`
  - `PUT/PATCH/DELETE /api/v1/collections/{collection_id}`
- Dependencies:
  - `GET /api/v1/dependencies/blocked`
  - `POST /api/v1/dependencies/`
  - `DELETE /api/v1/dependencies/{dependency_id}`
  - `GET /api/v1/threads/{thread_id}/dependencies`
  - `POST /api/v1/threads/{thread_id}:getBlockingInfo`
- Issues:
  - `GET /api/v1/threads/{thread_id}/issues`
  - `POST /api/v1/threads/{thread_id}/issues`
  - `POST /api/v1/issues/{issue_id}:markRead`
  - `POST /api/v1/issues/{issue_id}:markUnread`
- Migration:
  - `POST /api/threads/{thread_id}:migrateToIssues`
