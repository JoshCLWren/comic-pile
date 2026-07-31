import { expect, test, type BrowserContext, type Page, type TestInfo } from '@playwright/test'
import {
  type WorkloadScope,
  type ActionGroup,
  type ApiRecord,
  type ActionTimelineEntry,
  type BrowserApiResult,
  type Thread,
  type ThreadListResponse,
  type Issue,
  type IssueListResponse,
  type SessionCurrent,
  type SessionListResponse,
  type AnalyticsMetrics,
  type RollResponse,
  type Dependency,
  type ThreadDependenciesResponse,
  type FixtureState,
  type AccountComplexitySnapshot,
  type RatingOutcome,
  type CleanupReport,
  type NetworkProfile,
  BrowserApiError,
  manifest,
  actionById,
  expectedActionIds,
  fixturePrefix,
  defaultUsername,
  requestTimeoutMs,
  numericEnvironmentValue,
  percentile,
  normalizeRoute,
  safeBodyShape,
  shapeOf,
  parseDatabaseQueryCount,
  errorText,
  isApiRequest,
  loadHarCookies,
  installCredentialSource,
  installNetworkProfile,
  waitForCapturedAuth,
  workloadRoutes,
  browserApi,
  ensureCsrfCookie,
  createThread,
  listIssues,
  setupFixture,
  unrelatedThreadFingerprint,
  compareThreadFingerprints,
  captureAccountComplexity,
  rateWithReconciliation,
  cleanupFixture,
  routeSummary,
  duplicateGetBursts,
  attachJson,
} from './production-profile-real-user-support'

test('faithful real-user HAR workload profiles the existing production account', async (
  { page, context }: { page: Page; context: BrowserContext },
  testInfo: TestInfo,
) => {
  test.skip(
    testInfo.config.metadata.productionRealUserProfile !== true,
    'Run with playwright.prod-profile.config.ts against an explicit production URL.',
  )

  const baseUrl = String(testInfo.project.use.baseURL ?? '')
  if (!baseUrl) throw new Error('Production profile requires a baseURL.')

  const pauseScale = numericEnvironmentValue('PROD_PROFILE_PAUSE_SCALE', 1, 0)
  const maximumApiMs = numericEnvironmentValue('PROD_PROFILE_MAX_API_MS', 5_000, 1)
  const duplicateWindowMs = numericEnvironmentValue('PROD_PROFILE_DUPLICATE_WINDOW_MS', 250, 1)
  const invocationClassification = process.env.PROD_PROFILE_INVOCATION_CLASSIFICATION ?? 'unconfirmed'
  const expectedUsername = process.env.PROD_PROFILE_EXPECTED_USERNAME ?? defaultUsername
  const runId = new Date().toISOString().replace(/\D/g, '').slice(0, 14)

  let currentActionId = 'not-started'
  let currentScope: WorkloadScope = 'workload'
  const timeline: ActionTimelineEntry[] = []
  const ratingOutcomes: RatingOutcome[] = []
  let fixture: FixtureState | null = null
  let beforeFingerprint = new Map<number, string>()
  let cleanupReport: CleanupReport = {
    attempted: false,
    dependencyIdsDeleted: [],
    threadIdsDeleted: [],
    fixtureThreadsRemaining: [],
    unrelatedThreadStateChanged: [],
    verified: false,
    errors: [],
  }

  const profile = installNetworkProfile(page, () => ({ actionId: currentActionId, scope: currentScope }))
  const credentialSource = await installCredentialSource(context, baseUrl)

  await page.addInitScript(() => {
    localStorage.removeItem('auth_token')
    delete (window as Window & { __COMIC_PILE_ACCESS_TOKEN?: string }).__COMIC_PILE_ACCESS_TOKEN
  })

  const runAction = async <T>(id: string, callback: () => Promise<T>): Promise<T> => {
    const action = actionById.get(id)
    if (!action) throw new Error(`Unknown workload action: ${id}`)
    const pauseMs = Math.round(action.pauseAfterPreviousActionMs * pauseScale)
    if (pauseMs > 0) await page.waitForTimeout(pauseMs)

    currentActionId = id
    currentScope = 'workload'
    const recordStart = profile.records.length
    const startedAt = Date.now()
    try {
      const result = await callback()
      await profile.settle()
      timeline.push({
        id,
        phase: action.phase,
        label: action.label,
        startedAt: new Date(startedAt).toISOString(),
        finishedAt: new Date().toISOString(),
        durationMs: Date.now() - startedAt,
        pauseMs,
        requestCount: profile.records.length - recordStart,
        status: 'completed',
      })
      return result
    } catch (error) {
      await profile.settle()
      timeline.push({
        id,
        phase: action.phase,
        label: action.label,
        startedAt: new Date(startedAt).toISOString(),
        finishedAt: new Date().toISOString(),
        durationMs: Date.now() - startedAt,
        pauseMs,
        requestCount: profile.records.length - recordStart,
        status: 'failed',
        note: errorText(error),
      })
      throw error
    }
  }

  let accessToken = ''
  let accountComplexity: AccountComplexitySnapshot | null = null
  let bugReportConstruction: unknown = null

  try {
    await runAction('cold-authenticated-start', async () => {
      await page.goto('/', { waitUntil: 'domcontentloaded' })
      await waitForCapturedAuth(profile, page)
      accessToken = profile.getCapturedAccessToken() ?? ''
      expect(profile.getAuthenticatedUsername()).toBe(expectedUsername)
    })

    currentActionId = 'fixture-setup'
    currentScope = 'fixture-setup'
    await ensureCsrfCookie(page, accessToken)
    accountComplexity = await captureAccountComplexity(page, accessToken)
    const beforeThreads = (await browserApi<ThreadListResponse>(
      page,
      accessToken,
      '/api/threads/?page_size=200',
    )).body.threads
    beforeFingerprint = unrelatedThreadFingerprint(beforeThreads)
    fixture = await setupFixture(page, accessToken, runId)

    await runAction('home-revisit', async () => {
      await Promise.all([
        browserApi<ThreadListResponse>(page, accessToken, '/api/threads/?page_size=200'),
        browserApi<SessionCurrent>(page, accessToken, '/api/sessions/current/'),
      ])
    })

    await runAction('session-history', async () => {
      await browserApi<SessionListResponse>(page, accessToken, '/api/sessions/')
    })

    await runAction('analytics-first', async () => {
      await browserApi<AnalyticsMetrics>(page, accessToken, '/api/analytics/metrics')
    })

    await runAction('rating-first', async () => {
      const unread = (await listIssues(page, accessToken, fixture!.primary.id))
        .find((issue) => issue.status === 'unread')
      if (!unread) throw new Error('Primary fixture has no unread issue for rating.')
      await browserApi(page, accessToken, `/api/threads/${fixture!.primary.id}/set-pending`, { method: 'POST' })
      ratingOutcomes.push(await rateWithReconciliation(
        page,
        accessToken,
        'rating-first',
        fixture!.primary.id,
        unread.issue_number,
        3.5,
      ))
      await Promise.all([
        browserApi<SessionCurrent>(page, accessToken, '/api/sessions/current/'),
        browserApi<ThreadListResponse>(page, accessToken, '/api/threads/?page_size=200'),
        browserApi<Thread[]>(page, accessToken, '/api/threads/stale?days=7'),
      ])
    })

    await runAction('roll-rate', async () => {
      const roll = (await browserApi<RollResponse>(page, accessToken, '/api/roll/', { method: 'POST' })).body
      await Promise.all([
        browserApi(page, accessToken, `/api/v1/threads/${roll.thread_id}/reading-orders`),
        browserApi(page, accessToken, `/api/v1/threads/${roll.thread_id}/connected`),
      ])
      await browserApi(page, accessToken, '/api/roll/dismiss-pending', { method: 'POST' })
      const unread = (await listIssues(page, accessToken, fixture!.primary.id))
        .find((issue) => issue.status === 'unread')
      if (!unread) throw new Error('Primary fixture has no unread issue for roll-rate.')
      await browserApi(page, accessToken, `/api/threads/${fixture!.primary.id}/set-pending`, { method: 'POST' })
      ratingOutcomes.push(await rateWithReconciliation(
        page,
        accessToken,
        'roll-rate',
        fixture!.primary.id,
        unread.issue_number,
        4,
      ))
      await Promise.all([
        browserApi<SessionCurrent>(page, accessToken, '/api/sessions/current/'),
        browserApi<ThreadListResponse>(page, accessToken, '/api/threads/?page_size=200'),
        browserApi<Thread[]>(page, accessToken, '/api/threads/stale?days=7'),
      ])
    })

    await runAction('roll-snooze', async () => {
      const roll = (await browserApi<RollResponse>(page, accessToken, '/api/roll/', { method: 'POST' })).body
      await Promise.all([
        browserApi(page, accessToken, `/api/v1/threads/${roll.thread_id}/reading-orders`),
        browserApi(page, accessToken, `/api/v1/threads/${roll.thread_id}/connected`),
      ])
      await browserApi(page, accessToken, '/api/roll/dismiss-pending', { method: 'POST' })
      await browserApi(page, accessToken, `/api/threads/${fixture!.primary.id}/set-pending`, { method: 'POST' })
      await browserApi(page, accessToken, '/api/snooze/', { method: 'POST' })
      await Promise.all([
        browserApi<SessionCurrent>(page, accessToken, '/api/sessions/current/'),
        browserApi<ThreadListResponse>(page, accessToken, '/api/threads/?page_size=200'),
      ])
      await browserApi(page, accessToken, `/api/snooze/${fixture!.primary.id}/unsnooze`, { method: 'POST' })
    })

    await runAction('roll-dismiss-pending', async () => {
      const roll = (await browserApi<RollResponse>(page, accessToken, '/api/roll/', { method: 'POST' })).body
      await Promise.all([
        browserApi(page, accessToken, `/api/v1/threads/${roll.thread_id}/reading-orders`),
        browserApi(page, accessToken, `/api/v1/threads/${roll.thread_id}/connected`),
      ])
      await browserApi(page, accessToken, '/api/roll/dismiss-pending', { method: 'POST' })
      await Promise.all([
        browserApi<SessionCurrent>(page, accessToken, '/api/sessions/current/'),
        browserApi<ThreadListResponse>(page, accessToken, '/api/threads/?page_size=200'),
      ])
    })

    await runAction('roll-set-pending', async () => {
      const roll = (await browserApi<RollResponse>(page, accessToken, '/api/roll/', { method: 'POST' })).body
      await Promise.all([
        browserApi(page, accessToken, `/api/v1/threads/${roll.thread_id}/reading-orders`),
        browserApi(page, accessToken, `/api/v1/threads/${roll.thread_id}/connected`),
      ])
      await browserApi(page, accessToken, '/api/roll/dismiss-pending', { method: 'POST' })
      await browserApi(page, accessToken, `/api/threads/${fixture!.primary.id}/set-pending`, { method: 'POST' })
      await Promise.all([
        browserApi(page, accessToken, `/api/v1/threads/${fixture!.primary.id}/reading-orders`),
        browserApi(page, accessToken, `/api/v1/threads/${fixture!.primary.id}/connected`),
      ])
      await browserApi(page, accessToken, '/api/roll/dismiss-pending', { method: 'POST' })
    })

    await runAction('queue-front', async () => {
      await browserApi(page, accessToken, `/api/queue/threads/${fixture!.primary.id}/front/`, { method: 'PUT' })
      await Promise.all([
        browserApi<SessionCurrent>(page, accessToken, '/api/sessions/current/'),
        browserApi<ThreadListResponse>(page, accessToken, '/api/threads/?page_size=200'),
      ])
    })

    await runAction('open-large-thread', async () => {
      await Promise.all([
        browserApi<IssueListResponse>(
          page,
          accessToken,
          `/api/v1/threads/${fixture!.primary.id}/issues?page_size=100`,
        ),
        browserApi(
          page,
          accessToken,
          `/api/v1/threads/${fixture!.primary.id}/issue-dependencies`,
        ),
      ])
    })

    await runAction('mark-read', async () => {
      const unread = (await listIssues(page, accessToken, fixture!.primary.id))
        .find((issue) => issue.status === 'unread')
      if (!unread) throw new Error('Primary fixture has no unread issue to mark read.')
      await browserApi(page, accessToken, `/api/v1/issues/${unread.id}:markRead`, { method: 'POST' })
    })

    let addedIssueId: number | null = null
    await runAction('add-issue', async () => {
      await browserApi(page, accessToken, `/api/v1/threads/${fixture!.primary.id}/issues`, {
        method: 'POST',
        body: { issue_range: '41' },
      })
      const issues = await listIssues(page, accessToken, fixture!.primary.id)
      addedIssueId = issues.find((issue) => issue.issue_number === '41')?.id ?? null
      if (!addedIssueId) throw new Error('Added issue was not returned by the issue list.')
      await browserApi(page, accessToken, `/api/v1/threads/${fixture!.primary.id}/issue-dependencies`)
    })

    await runAction('reorder-issues', async () => {
      const issues = await listIssues(page, accessToken, fixture!.primary.id)
      if (!addedIssueId) throw new Error('No added issue is available for reordering.')
      const issueIds = [addedIssueId, ...issues.filter((issue) => issue.id !== addedIssueId).map((issue) => issue.id)]
      await browserApi(page, accessToken, `/api/v1/threads/${fixture!.primary.id}/issues:reorder`, {
        method: 'POST',
        body: { issue_ids: issueIds },
      })
    })

    await runAction('delete-issue', async () => {
      if (!addedIssueId) throw new Error('No added issue is available for deletion.')
      await browserApi(page, accessToken, `/api/v1/issues/${addedIssueId}`, { method: 'DELETE' })
    })

    await runAction('edit-thread', async () => {
      await browserApi(page, accessToken, `/api/threads/${fixture!.primary.id}`, {
        method: 'PUT',
        body: {
          title: fixture!.primary.title,
          format: 'Comics',
          notes: 'Faithful profile fixture, edited reversibly during the workload.',
        },
      })
      await browserApi<ThreadListResponse>(page, accessToken, '/api/threads/?page_size=200')
    })

    await runAction('queue-back-dependencies', async () => {
      await browserApi(page, accessToken, `/api/queue/threads/${fixture!.primary.id}/back/`, { method: 'PUT' })
      await Promise.all([
        browserApi<ThreadListResponse>(page, accessToken, '/api/threads/?page_size=200'),
        browserApi<ThreadDependenciesResponse>(
          page,
          accessToken,
          `/api/v1/threads/${fixture!.primary.id}/dependencies`,
        ),
      ])
    })

    await runAction('progressive-search', async () => {
      for (const search of ['AAS', 'AA', 'SP', 'sp']) {
        await browserApi<ThreadListResponse>(
          page,
          accessToken,
          `/api/threads/?search=${encodeURIComponent(search)}`,
        )
      }
    })

    let dependencyId: number | null = null
    await runAction('create-dependency', async () => {
      await Promise.all([
        browserApi<IssueListResponse>(
          page,
          accessToken,
          `/api/v1/threads/${fixture!.primary.id}/issues?page_size=100&status=unread`,
        ),
        browserApi<IssueListResponse>(
          page,
          accessToken,
          `/api/v1/threads/${fixture!.dependencyTarget.id}/issues?page_size=100&status=unread`,
        ),
      ])
      const dependency = (await browserApi<Dependency>(page, accessToken, '/api/v1/dependencies/', {
        method: 'POST',
        body: {
          source_type: 'thread',
          source_id: fixture!.primary.id,
          target_type: 'thread',
          target_id: fixture!.dependencyTarget.id,
        },
      })).body
      dependencyId = dependency.id
      fixture!.createdDependencyIds.add(dependency.id)
      await Promise.all([
        browserApi<ThreadDependenciesResponse>(
          page,
          accessToken,
          `/api/v1/threads/${fixture!.primary.id}/dependencies`,
        ),
        browserApi<ThreadListResponse>(page, accessToken, '/api/threads/?page_size=200'),
      ])
    })

    await runAction('dependency-management', async () => {
      await Promise.all([
        browserApi<ThreadDependenciesResponse>(
          page,
          accessToken,
          `/api/v1/threads/${fixture!.primary.id}/dependencies`,
        ),
        browserApi<ThreadDependenciesResponse>(
          page,
          accessToken,
          `/api/v1/threads/${fixture!.dependencyTarget.id}/dependencies`,
        ),
        browserApi<number[]>(page, accessToken, '/api/v1/dependencies/blocked'),
        browserApi<ThreadListResponse>(page, accessToken, '/api/threads/'),
      ])
      if (!dependencyId) throw new Error('Dependency was not created.')
      await browserApi(page, accessToken, `/api/v1/dependencies/${dependencyId}`, { method: 'DELETE' })
      fixture!.createdDependencyIds.delete(dependencyId)
      dependencyId = null
      await Promise.all([
        browserApi<ThreadDependenciesResponse>(
          page,
          accessToken,
          `/api/v1/threads/${fixture!.primary.id}/dependencies`,
        ),
        browserApi<number[]>(page, accessToken, '/api/v1/dependencies/blocked'),
        browserApi<ThreadListResponse>(page, accessToken, '/api/threads/?page_size=200'),
      ])
    })

    await runAction('bug-report', async () => {
      bugReportConstruction = {
        route: '/api/bug-reports/',
        method: 'POST',
        requestBodyShape: shapeOf({
          title: 'Production profile diagnostic',
          description: 'Construction-only request. It is not sent because production has no cleanup path.',
          diagnostics: {
            timestamp: new Date().toISOString(),
            url: page.url(),
            userAgent: 'redacted',
            viewport: { width: 0, height: 0 },
            screen: { width: 0, height: 0, pixelRatio: 0 },
            scroll: { x: 0, y: 0 },
            performance: { domContentLoaded: 0, loadComplete: 0 },
            errors: [],
          },
        }),
        sent: false,
        reason: 'No supported production cleanup path exists for generated bug reports.',
      }
    })
    const bugReportTimelineEntry = timeline.at(-1)
    if (bugReportTimelineEntry?.id === 'bug-report') {
      bugReportTimelineEntry.status = 'excluded'
      bugReportTimelineEntry.note = 'Request construction verified without sending to production.'
    }

    await runAction('analytics-second', async () => {
      await browserApi<AnalyticsMetrics>(page, accessToken, '/api/analytics/metrics')
    })

    await runAction('reactivation', async () => {
      await Promise.all([
        browserApi<ThreadListResponse>(page, accessToken, '/api/threads/?page_size=200'),
        browserApi<SessionCurrent>(page, accessToken, '/api/sessions/current/'),
      ])
      await browserApi(page, accessToken, '/api/threads/reactivate', {
        method: 'POST',
        body: { thread_id: fixture!.completed.id, issues_to_add: 1 },
      })
      await Promise.all([
        browserApi<ThreadListResponse>(page, accessToken, '/api/threads/?page_size=200'),
        browserApi<Thread>(page, accessToken, `/api/threads/${fixture!.completed.id}`),
        browserApi<SessionCurrent>(page, accessToken, '/api/sessions/current/'),
        browserApi<Thread[]>(page, accessToken, '/api/threads/stale?days=7'),
      ])
    })

    await runAction('mark-unread', async () => {
      const issues = await listIssues(page, accessToken, fixture!.primary.id)
      const readIssue = issues.find((issue) => issue.status === 'read')
      if (!readIssue) throw new Error('Primary fixture has no read issue to mark unread.')
      await browserApi(page, accessToken, `/api/v1/issues/${readIssue.id}:markUnread`, { method: 'POST' })
      await Promise.all([
        browserApi<SessionCurrent>(page, accessToken, '/api/sessions/current/'),
        browserApi<ThreadListResponse>(page, accessToken, '/api/threads/?page_size=200'),
      ])
    })

    await runAction('rating-second', async () => {
      const unread = (await listIssues(page, accessToken, fixture!.primary.id))
        .find((issue) => issue.status === 'unread')
      if (!unread) throw new Error('Primary fixture has no unread issue for second rating.')
      await browserApi(page, accessToken, `/api/threads/${fixture!.primary.id}/set-pending`, { method: 'POST' })
      ratingOutcomes.push(await rateWithReconciliation(
        page,
        accessToken,
        'rating-second',
        fixture!.primary.id,
        unread.issue_number,
        4.5,
      ))
      await Promise.all([
        browserApi<SessionCurrent>(page, accessToken, '/api/sessions/current/'),
        browserApi<ThreadListResponse>(page, accessToken, '/api/threads/?page_size=200'),
        browserApi<Thread[]>(page, accessToken, '/api/threads/stale?days=7'),
      ])
    })

    await runAction('dice-changes', async () => {
      for (const die of [50, 100, 4, 20]) {
        await browserApi(page, accessToken, `/api/roll/set-die?die=${die}`, { method: 'POST' })
      }
    })

    await runAction('roll-dismiss-second', async () => {
      const roll = (await browserApi<RollResponse>(page, accessToken, '/api/roll/', { method: 'POST' })).body
      await Promise.all([
        browserApi(page, accessToken, `/api/v1/threads/${roll.thread_id}/reading-orders`),
        browserApi(page, accessToken, `/api/v1/threads/${roll.thread_id}/connected`),
      ])
      await browserApi(page, accessToken, '/api/roll/dismiss-pending', { method: 'POST' })
      await Promise.all([
        browserApi<SessionCurrent>(page, accessToken, '/api/sessions/current/'),
        browserApi<ThreadListResponse>(page, accessToken, '/api/threads/?page_size=200'),
      ])
    })

    await runAction('final-roll-rate', async () => {
      await browserApi(page, accessToken, '/api/roll/set-die?die=100', { method: 'POST' })
      const roll = (await browserApi<RollResponse>(page, accessToken, '/api/roll/', { method: 'POST' })).body
      await Promise.all([
        browserApi(page, accessToken, `/api/v1/threads/${roll.thread_id}/reading-orders`),
        browserApi(page, accessToken, `/api/v1/threads/${roll.thread_id}/connected`),
      ])
      await browserApi(page, accessToken, '/api/roll/dismiss-pending', { method: 'POST' })
      const unread = (await listIssues(page, accessToken, fixture!.primary.id))
        .find((issue) => issue.status === 'unread')
      if (!unread) throw new Error('Primary fixture has no unread issue for final rating.')
      await browserApi(page, accessToken, `/api/threads/${fixture!.primary.id}/set-pending`, { method: 'POST' })
      ratingOutcomes.push(await rateWithReconciliation(
        page,
        accessToken,
        'final-roll-rate',
        fixture!.primary.id,
        unread.issue_number,
        5,
      ))
      await Promise.all([
        browserApi<SessionCurrent>(page, accessToken, '/api/sessions/current/'),
        browserApi<ThreadListResponse>(page, accessToken, '/api/threads/?page_size=200'),
        browserApi<Thread[]>(page, accessToken, '/api/threads/stale?days=7'),
      ])
    })
  } finally {
    if (accessToken) {
      currentActionId = 'cleanup'
      currentScope = 'cleanup'
      cleanupReport = await cleanupFixture(page, accessToken, fixture, beforeFingerprint)
    }
    await profile.finish()
  }

  const workloadRecords = profile.records.filter((record) => record.scope === 'workload')
  const durations = workloadRecords.map((record) => record.durationMs)
  const failedResponses = workloadRecords.filter((record) =>
    record.status !== null
    && record.status >= 400
    && !(record.route === '/api/auth/me' && record.status === 401),
  )
  const transportFailures = workloadRecords.filter((record) => record.transportFailure !== null)
  const slowResponses = workloadRecords.filter((record) => record.durationMs > maximumApiMs)
  const legacyDependencyRequests = workloadRecords.filter((record) =>
    /^\/api\/v1\/issues\/:id\/dependencies$/.test(record.route),
  )
  const batchDependencyRequests = workloadRecords.filter((record) =>
    record.route === '/api/v1/threads/:id/issue-dependencies',
  )
  const duplicates = duplicateGetBursts(workloadRecords, duplicateWindowMs)
  const ambiguousMutations = ratingOutcomes.filter((outcome) => outcome.classification === 'unknown-outcome')
  const completedActionIds = timeline.filter((action) => action.status !== 'failed').map((action) => action.id)
  const actionDivergence = expectedActionIds.filter((id) => !completedActionIds.includes(id))
  const [minimumRequests, maximumRequests] = manifest.baseline.expectedEquivalentWorkloadRequestCountRange

  const report = {
    generatedAt: new Date().toISOString(),
    baseUrl,
    workloadManifestVersion: manifest.manifestVersion,
    sourceHar: manifest.source,
    credentialSourceFingerprint: credentialSource,
    invocationClassification,
    invocationClassificationEvidence: invocationClassification === 'unconfirmed'
      ? 'No Vercel cold-start evidence was supplied; elapsed time is not used as a proxy.'
      : process.env.PROD_PROFILE_INVOCATION_EVIDENCE ?? 'Classification supplied by the runner.',
    pauseScale,
    sourceAccountBaseline: manifest.sourceAccountBaseline,
    currentAccountComplexity: accountComplexity,
    thresholds: {
      maximumApiMs,
      expectedEquivalentRequestRange: [minimumRequests, maximumRequests],
      duplicateWindowMs,
    },
    summary: {
      workloadRequests: workloadRecords.length,
      setupRequests: profile.records.filter((record) => record.scope === 'fixture-setup').length,
      cleanupRequests: profile.records.filter((record) => record.scope === 'cleanup').length,
      failedResponses: failedResponses.length,
      transportFailures: transportFailures.length,
      slowResponses: slowResponses.length,
      ambiguousMutationOutcomes: ambiguousMutations.length,
      duplicateGetBursts: duplicates.length,
      legacyDependencyRequests: legacyDependencyRequests.length,
      batchedDependencyRequests: batchDependencyRequests.length,
      p50Ms: percentile(durations, 0.5),
      p90Ms: percentile(durations, 0.9),
      p95Ms: percentile(durations, 0.95),
      p99Ms: percentile(durations, 0.99),
      maxMs: Math.max(0, ...durations),
      cacheStatuses: workloadRecords.reduce<Record<string, number>>((counts, record) => {
        const cache = record.cacheStatus ?? 'not-reported'
        counts[cache] = (counts[cache] ?? 0) + 1
        return counts
      }, {}),
      databaseQueries: workloadRecords.reduce((total, record) => total + (record.databaseQueries ?? 0), 0),
      requestsWithServerTiming: workloadRecords.filter((record) => record.serverTiming !== null).length,
      requestsWithRequestId: workloadRecords.filter((record) => record.requestId !== null).length,
    },
    ratingOutcomes,
    duplicateGetBursts: duplicates,
    cleanup: cleanupReport,
    actionDivergence,
    coverage: manifest.coverage,
    deliberateExclusions: [bugReportConstruction],
    timeline,
    routeSummary: routeSummary(workloadRecords),
    records: profile.records,
  }

  const sanitizedHar = {
    log: {
      version: '1.2-sanitized',
      creator: { name: 'ComicPile real-user production profiler', version: manifest.manifestVersion },
      entries: workloadRecords.map((record) => ({
        startedDateTime: new Date(record.startedAt).toISOString(),
        time: record.durationMs,
        request: {
          method: record.method,
          url: record.route,
          headers: [],
          cookies: [],
          postData: record.requestBodyShape === null ? undefined : { shape: record.requestBodyShape },
        },
        response: {
          status: record.status,
          headers: [
            ...(record.requestId ? [{ name: 'X-Request-ID', value: record.requestId }] : []),
            ...(record.cacheStatus ? [{ name: 'X-App-Cache', value: record.cacheStatus }] : []),
            ...(record.databaseQueries !== null
              ? [{ name: 'X-App-DB-Queries', value: String(record.databaseQueries) }]
              : []),
            ...(record.serverTiming ? [{ name: 'Server-Timing', value: record.serverTiming }] : []),
          ],
          cookies: [],
          content: { size: 0, mimeType: 'application/json', text: '[redacted]' },
        },
        _actionId: record.actionId,
        _transportFailure: record.transportFailure,
      })),
    },
  }

  await Promise.all([
    attachJson(testInfo, 'production-profile.json', report),
    attachJson(testInfo, 'production-profile.sanitized.har.json', sanitizedHar),
    attachJson(testInfo, 'production-profile.action-timeline.json', timeline),
    attachJson(testInfo, 'production-profile.route-summary.json', report.routeSummary),
    attachJson(testInfo, 'production-profile.source-comparison.json', {
      source: manifest.source,
      sourceLatencyMs: manifest.baseline.latencyMs,
      sourceRouteBaselines: workloadRoutes.routeSummaries,
      currentLatencyMs: {
        p50: report.summary.p50Ms,
        p90: report.summary.p90Ms,
        p95: report.summary.p95Ms,
        p99: report.summary.p99Ms,
        max: report.summary.maxMs,
      },
      sourceApiRequests: manifest.source.apiRequestCount,
      equivalentWorkloadRequests: workloadRecords.length,
      actionDivergence,
      requestCountWithinEquivalentRange:
        workloadRecords.length >= minimumRequests && workloadRecords.length <= maximumRequests,
    }),
    attachJson(testInfo, 'production-profile.bug-report-construction.json', bugReportConstruction),
  ])

  expect(actionDivergence, 'Every source-HAR action group must execute').toEqual([])
  expect(cleanupReport, 'Fixture cleanup must be verified').toMatchObject({ verified: true })
  expect(ambiguousMutations, 'Mutation outcomes must not remain unknown').toEqual([])
  expect(failedResponses, 'Unexpected HTTP responses with status >= 400').toEqual([])
  expect(transportFailures, 'Transport failures').toEqual([])
  expect(slowResponses, `API responses slower than ${maximumApiMs} ms`).toEqual([])
  expect(workloadRecords.length, 'Equivalent workload request count')
    .toBeGreaterThanOrEqual(minimumRequests)
  expect(workloadRecords.length, 'Equivalent workload request count')
    .toBeLessThanOrEqual(maximumRequests)
  expect(legacyDependencyRequests, 'Legacy one-request-per-issue dependency calls').toEqual([])
  expect(batchDependencyRequests.length, 'Batched issue dependency requests').toBeGreaterThanOrEqual(1)
})
