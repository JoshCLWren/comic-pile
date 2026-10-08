frontend: Fix creator navigation auth state race condition

- Add `skipAuthRedirect: true` to creator detail and list API requests to prevent
  independent login redirects during recoverable auth transitions
- Creator navigation no longer briefly shows logged-out state when session refresh
  is in progress
- Both `creatorsApi.getDetail()` and `creatorsApi.getList()` now use recovery config
  to defer to central auth recovery authority
- Resolves issue #3212