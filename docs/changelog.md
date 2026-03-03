# Changelog

## 2026-03-03

- Roll/rate sequencing fix: `Save & Continue` no longer auto-selects a new pending thread.
- After a successful rate with `finish_session=false`, the session returns to roll state with
  `pending_thread_id=null`.
- Users must perform a new roll (or explicitly set pending) before submitting another rating.
