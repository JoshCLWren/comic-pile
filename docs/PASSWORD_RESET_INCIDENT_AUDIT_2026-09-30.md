# ComicPile password-reset incident audit

Date: September 30, 2026

Status: Email transport fix deployed. Password-reset completion and routing fixes are local, tested in part, and not yet committed or deployed. This document is an incident audit, not a declaration that recovery works end to end or that the entire repository has been audited.

## Summary

Password recovery had three separate failures: an outbound HTTP request rejected before normal Resend authentication, an authenticated-browser route redirect that hid the reset form, and a password-completion implementation that attempted to delete reading history as if it were authentication sessions. Production database constraints blocked the deletion and produced HTTP 500.

The dangerous deletion came from the original factory-generated recovery implementation. Factory repair later moved it into a repository helper without correcting its meaning. Automated checks passed because the acceptance tests did not assert several behaviors named in their titles and used no populated reading history. The subsequent email investigation verified delivery but did not verify password completion. That was an additional verification failure by the investigating agent.

## Confirmed findings

### 1. Default urllib User-Agent caused the observed provider HTTP 403

ComicPile sent email using the Python standard library. A local comparison held the endpoint, diagnostic credential, and request payload constant while changing the User-Agent:

- Default urllib User-Agent: HTTP 403 with the safe response text `error code: 1010`.
- Explicit `User-Agent: ComicPile/1.0`: HTTP 401 for the deliberately invalid diagnostic credential, reaching normal provider authentication.
- Official Resend CLI: the expected HTTP 401 with the diagnostic credential.

This isolates the request header as the cause of the reproduced rejection. The response is consistent with an upstream firewall rejection rather than a normal Resend credential-validation response. A production request after the header fix successfully sent the reset email to the authorized recipient, and delivery was confirmed.

There was no evidence that the copied deployment API key was wrong. It was not replaced. No SDK or new required secret was introduced.

### 2. Production mail settings could drift through optional overrides

The deployment needed deterministic application-owned values. The deployed fix uses:

- Sender: `Comic Pile <onboarding@resend.dev>`.
- Origin: `https://comic-pile.vercel.app`.
- Path: `/reset-password`.

Production ignores `PASSWORD_RESET_SENDER`, `PASSWORD_RESET_ORIGIN`, and `PASSWORD_RESET_PATH`. `RESEND_API_KEY` is the only required secret for the email integration; existing database/authentication secrets are outside that statement. Non-production can still use harmless local values. Removing obsolete production overrides is configuration cleanup, not a prerequisite for the corrected code.

### 3. The reset page redirected authenticated users away

The recovery routes were wrapped in `PublicRoute`, which redirects an authenticated user to the application root. A signed-in browser opening a reset link therefore could not reliably reach the recovery form. This explains the reported apparent immediate login; it is not evidence that opening the reset link itself issued a login token.

The local fix makes both recovery routes accessible regardless of authentication state, while retaining their existing layout. Successful reset also clears cached frontend authentication state so the user can sign in with the new password.

### 4. Password completion attempted to delete reading history

`complete_reset` called `delete_all_sessions_for_user`. That helper deleted rows from `sessions`, whose model represents reading sessions, not login sessions.

Production `events` and `snapshots` foreign keys reference these sessions without `ON DELETE CASCADE`. Deleting a reading session with dependent history violates those constraints. The transaction failed and rolled back, producing the reported HTTP 500. A read-only production check found 418 reading sessions for the affected account. No history loss was established by that check; it was not a complete historical reconciliation.

On a schema with cascading deletion, this same code could delete dependent history instead of raising the production error. The wrong operation must be removed, not made to succeed by changing foreign keys.

Login and refresh JWT revocation already uses `password_changed_at` and the password-change claim. The local fix removes the reading-session deletion and its now-unused helper, retaining that authentication mechanism.

### 5. Reset-token consumption lacked a concurrency lock

Two transactions could both read an unused token before either committed. The local fix adds `SELECT ... FOR UPDATE` to token lookup so competing reset attempts serialize and only one can consume the token. A concurrent-transaction regression test expects exactly one success and one rejection.

## How factory inspection missed this

[PR #2793](https://github.com/JoshCLWren/comic-pile/pull/2793), “Password reset 1/3: secure token lifecycle and reset API,” merged on September 21, 2026. Its listed CI checks succeeded. The GitHub reviews collection returned no recorded reviews; a CodeRabbit success status existed, which alone does not establish the content or depth of review.

The original service implementation appears in commit `b48f3f9d0`. Commit `cc283a5e8` moved the direct reading-session deletion into a repository helper. This improved layering while preserving the dangerous domain mistake.

The acceptance tests in `tests/test_password_reset.py` had material gaps:

- `test_token_strong_digest_and_single_use` requested recovery but did not assert digest strength/storage or consume/replay the token.
- `test_forgot_password_rate_limit` made one request and checked the acknowledgement; it did not exercise a rate limit.
- `test_reset_atomic_and_revokes_sessions` created no reading-history records and did not assert authentication revocation, token consumption, or preservation of history.
- Its password assertion compared an existing hash with a newly salted hash. That inequality can hold even when the password remains unchanged.
- ORM-created test schemas used cascading foreign keys that differed from the production migration's restrictive keys.

These are concrete failures of test adequacy. Passing lint, type checks, coverage, generic UI checks, and these tests did not prove the recovery story. The evidence does not yet establish which individual factory review step should have stopped the merge; review comments and gate implementation need a separate inspection.

## Investigation and deployment mistakes

The investigating agent deployed and confirmed email delivery, but initially did not exercise the link, password submission, and subsequent login in a browser. Reporting recovery as handled from delivery evidence overstated what had been verified.

Three deployment attempts were also blocked by Git author identity checks. The worktree inherited `Factory Test <factory@example.com>`; retries preceded publication of a correctly attributed commit. After correcting and publishing the author identity, deployment succeeded. Those blocked attempts were caused by the agent's deployment procedure, not by Resend or the reset runtime bug.

## Changes and verification status

Deployed commit: `e847c3963505e3bbacbc64838c1740d6e604622a`, “Fix auth reset mail transport and production defaults.” Production deployment: `dpl_PxfDav7BAMTURWctbg5ZNNK1i5uX`.

The deployed change adds the explicit User-Agent, deterministic production mail settings, configuration/documentation updates, and regression coverage for the actual HTTP request, surrounding credential whitespace, override behavior, safe provider errors, and enumeration-safe acknowledgements. Focused email/configuration tests: 23 passed. Relevant backend tests at that stage: 109 passed. Mailer coverage reported 98.23%. Production delivery was confirmed after the authorized forgot-password request at 22:52:04 UTC.

Local, uncommitted corrections remove reading-history deletion, lock token consumption, expose recovery pages to signed-in users, and clear stale frontend authentication after completion.

New backend regression coverage exercises populated reading sessions, events, and snapshots under both ORM and production-style restrictive constraints; verifies the actual new password; rejects old passwords, old access tokens, old refresh tokens, expired/superseded tokens, and replay; and tests simultaneous consumption.

Focused backend tests including those lifecycle cases: 27 passed. Whole-repository Ruff and ty passed after the Python edits. Frontend lint, typecheck, and production build passed. The complete frontend unit suite passed: 238 files, 2,021 tests, plus four style-audit tests. Lint reported ten React-refresh warnings; these did not fail the command.

A Chromium browser regression and private database fixture helper have been authored for signed-in and signed-out recovery using disposable accounts with real reading history. They are not yet executed. No claim of production password-completion success is justified yet.

## Required follow-up

1. Run the new Chromium lifecycle coverage locally against the actual backend and built frontend; fix any failures.
2. Replace or strengthen the misleading original acceptance tests rather than relying on their names or salted-hash comparisons. Establish the intended rate-limit behavior and verify it meaningfully.
3. Commit and push the completion/routing corrections, then deploy the published commit with the correct Git author identity.
4. Run the browser lifecycle against production using disposable accounts, preserve their seeded history, verify old credentials fail and new credentials work, and remove the disposable records. Do not change the affected user's password as a diagnostic.
5. Recheck the affected account's reading-history count and send a fresh reset email after deployment. Let the account owner choose their password.
6. Inspect factory acceptance/review gates: require evidence that security-critical stories are actually exercised, including populated data, credential revocation, replay, and concurrent requests. Generic green CI must not be presented as full-story verification.
7. Audit adjacent authentication and destructive operations for the same domain confusion, broad deletion scope, missing ownership checks, and transaction behavior. Audit test claims against their assertions, and reconcile migration-built versus ORM-built database constraints. Findings outside recovery remain unverified; this incident does not establish that the entire repository is safe or unsafe.

## Handling constraints

Continue preserving enumeration-safe forgot-password responses. Never log API keys, raw reset tokens, full reset URLs, or token-bearing request/email bodies. Provider status codes and carefully selected non-secret error metadata are acceptable. Browser diagnostics for token-bearing pages must avoid traces, screenshots, and unsanitized URL output. Keep the fix scoped; no mail-system rewrite, SDK migration, or additional required email secrets are warranted by the evidence.
