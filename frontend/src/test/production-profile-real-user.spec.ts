import {
  expect,
  test,
  type BrowserContext,
  type Dialog,
  type Locator,
  type Page,
  type Response,
  type TestInfo,
} from '@playwright/test'
import { setRangeInput } from './helpers'
import {
  type WorkloadScope,
  type ActionTimelineEntry,
  type Thread,
  type ThreadListResponse,
  type SessionCurrent,
  type AccountComplexitySnapshot,
  type RatingOutcome,
  type CleanupReport,
  manifest,
  actionById,
  expectedActionIds,
  defaultUsername,
  numericEnvironmentValue,
  percentile,
  errorText,
  installCredentialSource,
  installNetworkProfile,
  waitForCapturedAuth,
  workloadRoutes,
  browserApi,
  ensureCsrfCookie,
  setupFixture,
  unrelatedThreadFingerprint,
  captureAccountComplexity,
  cleanupFixture,
  routeSummary,
  duplicateGetBursts,
  shapeOf,
  attachJson,
} from './production-profile-real-user-support'

const MAIN_DIE = '#main-die-3d'
const RATING_INPUT = '#rating-input'
const RATING_ERROR = '#error-message'
const QUEUE_SEARCH = 'input[placeholder="Search..."]'

async function waitForRollView(page: Page): Promise<void> {
  await expect(page.locator(MAIN_DIE)).toBeVisible({ timeout: 20_000 })
}

async function waitForRatingView(page: Page, expectedTitle?: string): Promise<void> {
  await expect(page.locator(RATING_INPUT)).toBeVisible({ timeout: 20_000 })
  if (expectedTitle) {
    await expect(page.locator('#thread-info')).toContainText(expectedTitle, { timeout: 10_000 })
  }
}

async function selectPoolThread(page: Page, title: string): Promise<void> {
  await waitForRollView(page)
  const pool = page.locator('[data-roll-pool]')
  const thread = pool.locator('[role="button"]').filter({ hasText: title }).first()
  await expect(thread, `Fixture ${title} must be in the visible roll pool`).toBeVisible({ timeout: 15_000 })
  await thread.click()
  await expect(page.getByRole('dialog')).toContainText(title)
  await page.getByRole('button', { name: 'Read Now' }).click()
  await waitForRatingView(page, title)
}

async function cancelRatingView(page: Page): Promise<void> {
  await page.getByRole('button', { name: 'Cancel' }).click()
  await waitForRollView(page)
}

async function rollAndCancel(page: Page): Promise<void> {
  await waitForRollView(page)
  await page.locator(MAIN_DIE).click()
  await waitForRatingView(page)
  await cancelRatingView(page)
}

async function gotoQueue(page: Page): Promise<void> {
  await page.goto('/queue', { waitUntil: 'domcontentloaded' })
  await expect(page.getByRole('heading', { name: 'Read Queue' })).toBeVisible({ timeout: 20_000 })
}

async function filteredQueueCard(page: Page, title: string): Promise<Locator> {
  await gotoQueue(page)
  const search = page.locator(QUEUE_SEARCH)
  await search.fill(title)
  const card = page.getByTestId('queue-thread-item').filter({ hasText: title }).first()
  await expect(card).toBeVisible({ timeout: 15_000 })
  return card
}

async function openQueueAction(page: Page, title: string, actionName: string): Promise<void> {
  const card = await filteredQueueCard(page, title)
  await card.getByRole('button', { name: 'Thread actions' }).click()
  const menu = page.getByRole('menu', { name: 'Thread actions' })
  await expect(menu).toBeVisible()
  await menu.getByRole('menuitem', { name: actionName }).click()
}

async function openPrimaryEditModal(page: Page, title: string): Promise<Locator> {
  const card = await filteredQueueCard(page, title)
  await card.getByRole('button', { name: 'Thread actions' }).click()
  await page.getByRole('menuitem', { name: 'Edit thread' }).click()
  const dialog = page.getByRole('dialog').filter({ hasText: 'Edit Thread' })
  await expect(dialog).toBeVisible({ timeout: 15_000 })
  return dialog
}

async function ensureExpandedIssueList(dialog: Locator, issueCount: number): Promise<void> {
  const showAll = dialog.getByRole('button', { name: `Show all ${issueCount}` })
  if (await showAll.count()) await showAll.click()
}

async function waitForMutationResponse(
  page: Page,
  method: string,
  route: RegExp,
  action: () => Promise<void>,
  timeout = 15_000,
): Promise<Response | null> {
  const responsePromise = page.waitForResponse((response: Response) => {
    const url = new URL(response.url())
    return response.request().method() === method && route.test(url.pathname + url.search)
  }, { timeout }).catch(() => null)
  await action()
  return responsePromise
}

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
  let fixture: Awaited<ReturnType<typeof setupFixture>> | null = null
  let beforeFingerprint = new Map<number, string>()
  let initialSession: SessionCurrent | null = null
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
  let dependencyId: number | null = null
  let addedIssueId: number | null = null

  const rateThroughUi = async (
    actionId: string,
    threadId: number,
    threadTitle: string,
    rating: number,
  ): Promise<RatingOutcome> => {
    await selectPoolThread(page, threadTitle)
    await setRangeInput(page, RATING_INPUT, String(rating))

    const response = await waitForMutationResponse(
      page,
      'POST',
      /^\/api\/rate\/$/,
      async () => page.getByTestId('save-and-continue').click(),
      12_000,
    )

    let detail = 'Rating request did not produce an HTTP response before the client timeout.'
    let authoritativeStateChecked = false
    let authoritativeRating: number | null = null
    let classification: RatingOutcome['classification'] = 'unknown-outcome'

    if (response) {
      if (response.ok()) {
        classification = 'definite-success'
        detail = 'The actual frontend rating POST returned a successful HTTP response.'
      } else {
        classification = 'definite-failure'
        detail = `The actual frontend rating POST returned HTTP ${response.status()}.`
      }
    } else {
      currentScope = 'reconciliation'
      authoritativeStateChecked = true
      await page.waitForTimeout(750)
      try {
        const authoritative = (await browserApi<Thread>(
          page,
          accessToken,
          `/api/threads/${threadId}`,
        )).body
        authoritativeRating = typeof authoritative.last_rating === 'number'
          ? authoritative.last_rating
          : null
        if (authoritativeRating === rating) {
          classification = 'definite-success'
          detail = 'The client timed out, but authoritative thread state confirms the rating committed.'
        } else {
          detail = 'The client timed out and authoritative state could not prove whether the write committed.'
        }
      } catch (error) {
        detail = `Rating transport failed and reconciliation also failed: ${errorText(error)}`
      } finally {
        currentScope = 'workload'
      }
    }

    const mainDie = page.locator(MAIN_DIE)
    const errorMessage = page.locator(RATING_ERROR)
    await Promise.race([
      mainDie.waitFor({ state: 'visible', timeout: 15_000 }).catch(() => undefined),
      errorMessage.waitFor({ state: 'visible', timeout: 15_000 }).catch(() => undefined),
    ])
    if (await errorMessage.isVisible().catch(() => false)) {
      const uiError = (await errorMessage.textContent())?.trim()
      if (uiError) detail = `${detail} UI message: ${uiError}`
      await page.reload({ waitUntil: 'domcontentloaded' })
      await waitForRollView(page)
    }

    return {
      actionId,
      threadId,
      rating,
      requestStatus: response?.status() ?? null,
      classification,
      authoritativeStateChecked,
      authoritativeRating,
      detail,
    }
  }

  const restoreSessionState = async (): Promise<void> => {
    if (!initialSession || !accessToken) return
    currentActionId = 'cleanup-session-state'
    currentScope = 'cleanup'

    try {
      const current = (await browserApi<SessionCurrent>(page, accessToken, '/api/sessions/current/')).body
      if (current.pending_thread_id) {
        await browserApi(page, accessToken, '/api/roll/dismiss-pending', { method: 'POST' })
      }
    } catch (error) {
      cleanupReport.errors.push(`dismiss current pending state: ${errorText(error)}`)
    }

    try {
      if (initialSession.manual_die !== null && initialSession.manual_die !== undefined) {
        await browserApi(page, accessToken, `/api/roll/set-die?die=${initialSession.manual_die}`, { method: 'POST' })
      } else {
        await browserApi(page, accessToken, '/api/roll/clear-manual-die', { method: 'POST' })
      }
    } catch (error) {
      cleanupReport.errors.push(`restore manual die: ${errorText(error)}`)
    }

    if (initialSession.pending_thread_id) {
      try {
        await browserApi(
          page,
          accessToken,
          `/api/threads/${initialSession.pending_thread_id}/set-pending`,
          { method: 'POST' },
        )
      } catch (error) {
        cleanupReport.errors.push(`restore original pending thread: ${errorText(error)}`)
      }
    }
  }

  try {
    await runAction('cold-authenticated-start', async () => {
      await page.goto('/', { waitUntil: 'domcontentloaded' })
      await waitForCapturedAuth(profile, page)
      accessToken = profile.getCapturedAccessToken() ?? ''
      expect(profile.getAuthenticatedUsername()).toBe(expectedUsername)
      await expect(page.locator('#root')).toBeVisible()
    })

    currentActionId = 'fixture-setup'
    currentScope = 'fixture-setup'
    await ensureCsrfCookie(page, accessToken)
    accountComplexity = await captureAccountComplexity(page, accessToken)
    initialSession = (await browserApi<SessionCurrent>(page, accessToken, '/api/sessions/current/')).body
    if (initialSession.pending_thread_id) {
      await browserApi(page, accessToken, '/api/roll/dismiss-pending', { method: 'POST' })
    }
    const beforeThreads = (await browserApi<ThreadListResponse>(
      page,
      accessToken,
      '/api/threads/?page_size=200',
    )).body.threads
    beforeFingerprint = unrelatedThreadFingerprint(beforeThreads)
    fixture = await setupFixture(page, accessToken, runId)
    await browserApi(page, accessToken, `/api/queue/threads/${fixture.primary.id}/front/`, { method: 'PUT' })

    await runAction('home-revisit', async () => {
      await page.goto('/', { waitUntil: 'domcontentloaded' })
      await waitForRollView(page)
    })

    await runAction('session-history', async () => {
      await page.goto('/history', { waitUntil: 'domcontentloaded' })
      await expect(page.locator('#root')).toBeVisible()
    })

    await runAction('analytics-first', async () => {
      await page.goto('/analytics', { waitUntil: 'domcontentloaded' })
      await expect(page.locator('#root')).toBeVisible()
    })

    await runAction('rating-first', async () => {
      await page.goto('/', { waitUntil: 'domcontentloaded' })
      ratingOutcomes.push(await rateThroughUi(
        'rating-first',
        fixture!.primary.id,
        fixture!.primary.title,
        3.5,
      ))
    })

    await runAction('roll-rate', async () => {
      await rollAndCancel(page)
      ratingOutcomes.push(await rateThroughUi(
        'roll-rate',
        fixture!.primary.id,
        fixture!.primary.title,
        4,
      ))
    })

    await runAction('roll-snooze', async () => {
      await rollAndCancel(page)
      await selectPoolThread(page, fixture!.primary.title)
      await page.getByRole('button', { name: 'Snooze' }).click()
      await waitForRollView(page)
      await page.getByRole('button', { name: /Snoozed \(/ }).click()
      const snoozedRow = page.locator('div').filter({ hasText: fixture!.primary.title })
        .filter({ has: page.getByRole('button', { name: 'Unsnooze this comic' }) }).last()
      await expect(snoozedRow).toBeVisible()
      await snoozedRow.getByRole('button', { name: 'Unsnooze this comic' }).click()
      await expect(snoozedRow).toHaveCount(0)
    })

    await runAction('roll-dismiss-pending', async () => {
      await rollAndCancel(page)
    })

    await runAction('roll-set-pending', async () => {
      await rollAndCancel(page)
      await selectPoolThread(page, fixture!.primary.title)
      await cancelRatingView(page)
    })

    await runAction('queue-front', async () => {
      const response = await waitForMutationResponse(
        page,
        'PUT',
        new RegExp(`^/api/queue/threads/${fixture!.primary.id}/front/$`),
        async () => openQueueAction(page, fixture!.primary.title, 'Move to front'),
      )
      expect(response?.ok()).toBe(true)
    })

    await runAction('open-large-thread', async () => {
      const card = await filteredQueueCard(page, fixture!.primary.title)
      await card.locator('.queue-thread-card').click()
      await page.waitForURL(new RegExp(`/thread/${fixture!.primary.id}$`), { timeout: 15_000 })
      await expect(page.getByRole('heading', { name: fixture!.primary.title })).toBeVisible()
      await page.getByRole('button', { name: 'Expand' }).click()
      await expect(page.getByText('#40', { exact: true })).toBeVisible()
      await page.getByRole('button', { name: 'Edit', exact: true }).click()
      const dialog = page.getByRole('dialog').filter({ hasText: 'Edit Thread' })
      await expect(dialog).toBeVisible()
      await ensureExpandedIssueList(dialog, 40)
    })

    const initiallyUnread = fixture.primaryIssues.find((issue) => issue.status === 'unread')
    const initiallyRead = fixture.primaryIssues.find((issue) => issue.status === 'read')
    if (!initiallyUnread || !initiallyRead) {
      throw new Error('Fixture must contain both read and unread issues.')
    }

    await runAction('mark-read', async () => {
      const dialog = page.getByRole('dialog').filter({ hasText: 'Edit Thread' })
      const response = await waitForMutationResponse(
        page,
        'POST',
        new RegExp(`^/api/v1/issues/${initiallyUnread.id}:markRead$`),
        async () => dialog.getByTestId(`issue-toggle-${initiallyUnread.id}`).click(),
      )
      expect(response?.ok()).toBe(true)
    })

    await runAction('add-issue', async () => {
      const dialog = page.getByRole('dialog').filter({ hasText: 'Edit Thread' })
      await dialog.getByTestId('issue-add-input').fill('41')
      const response = await waitForMutationResponse(
        page,
        'POST',
        new RegExp(`^/api/v1/threads/${fixture!.primary.id}/issues$`),
        async () => dialog.getByTestId('issue-add-button').click(),
      )
      expect(response?.ok()).toBe(true)
      const pill = dialog.locator('[data-issue-number="41"]')
      await expect(pill).toBeVisible({ timeout: 15_000 })
      const testId = await pill.getAttribute('data-testid')
      const match = testId?.match(/^issue-pill-(\d+)$/)
      if (!match) throw new Error('Could not resolve the dynamically created issue ID from the UI.')
      addedIssueId = Number(match[1])
    })

    await runAction('reorder-issues', async () => {
      if (!addedIssueId) throw new Error('Added issue ID is unavailable for reorder.')
      const dialog = page.getByRole('dialog').filter({ hasText: 'Edit Thread' })
      const response = await waitForMutationResponse(
        page,
        'POST',
        new RegExp(`^/api/v1/threads/${fixture!.primary.id}/issues:reorder$`),
        async () => dialog.getByTestId(`issue-move-up-${addedIssueId}`).click(),
      )
      expect(response?.ok()).toBe(true)
    })

    await runAction('delete-issue', async () => {
      if (!addedIssueId) throw new Error('Added issue ID is unavailable for deletion.')
      page.once('dialog', (dialog: Dialog) => dialog.accept())
      const editDialog = page.getByRole('dialog').filter({ hasText: 'Edit Thread' })
      const response = await waitForMutationResponse(
        page,
        'DELETE',
        new RegExp(`^/api/v1/issues/${addedIssueId}$`),
        async () => editDialog.getByTestId(`issue-delete-${addedIssueId}`).click(),
      )
      expect(response?.ok()).toBe(true)
      addedIssueId = null
    })

    await runAction('edit-thread', async () => {
      const dialog = page.getByRole('dialog').filter({ hasText: 'Edit Thread' })
      await dialog.getByLabel('Notes').fill('Faithful real-user production profile fixture, edited through the production UI.')
      const response = await waitForMutationResponse(
        page,
        'PUT',
        new RegExp(`^/api/threads/${fixture!.primary.id}$`),
        async () => dialog.getByRole('button', { name: 'Save Changes' }).click(),
      )
      expect(response?.ok()).toBe(true)
      await expect(dialog).toHaveCount(0)
    })

    await runAction('queue-back-dependencies', async () => {
      const moveResponse = await waitForMutationResponse(
        page,
        'PUT',
        new RegExp(`^/api/queue/threads/${fixture!.primary.id}/back/$`),
        async () => openQueueAction(page, fixture!.primary.title, 'Move to back'),
      )
      expect(moveResponse?.ok()).toBe(true)
      await openQueueAction(page, fixture!.primary.title, 'Manage dependencies')
      await expect(page.getByRole('dialog')).toContainText(/Dependencies/)
    })

    await runAction('progressive-search', async () => {
      await page.getByRole('button', { name: 'Close' }).click()
      const search = page.locator(QUEUE_SEARCH)
      for (const query of ['AAS', 'AA', 'SP', 'sp']) {
        await search.fill(query)
        await page.waitForTimeout(350)
      }
      await search.fill(fixture!.primary.title)
    })

    await runAction('create-dependency', async () => {
      await openQueueAction(page, fixture!.primary.title, 'Manage dependencies')
      const dialog = page.getByRole('dialog').filter({ hasText: /Dependencies/ })
      const search = dialog.getByLabel('Search prerequisite thread')
      await search.fill(fixture!.dependencyTarget.title)
      const candidate = dialog.getByRole('button').filter({ hasText: fixture!.dependencyTarget.title }).first()
      await expect(candidate).toBeVisible({ timeout: 15_000 })
      await candidate.click()
      await expect(dialog.getByLabel('Prerequisite issue')).toBeEnabled({ timeout: 15_000 })
      await expect(dialog.getByLabel('Target issue')).toBeEnabled({ timeout: 15_000 })
      const response = await waitForMutationResponse(
        page,
        'POST',
        /^\/api\/v1\/dependencies\/$/,
        async () => dialog.getByRole('button', { name: /^Block issue/ }).click(),
      )
      expect(response?.ok()).toBe(true)
      const created = response ? await response.json() as { id?: number } : null
      dependencyId = created?.id ?? null
      if (!dependencyId) throw new Error('Dependency response did not include an ID.')
      fixture!.createdDependencyIds.add(dependencyId)
      await expect(dialog.getByRole('button', { name: 'Remove' }).first()).toBeVisible()
    })

    await runAction('dependency-management', async () => {
      if (!dependencyId) throw new Error('Dependency was not created.')
      const dialog = page.getByRole('dialog').filter({ hasText: /Dependencies/ })
      await dialog.getByRole('button', { name: 'Remove' }).first().click()
      await page.getByRole('button', { name: 'Close' }).click()
      await expect(dialog).toHaveCount(0)
      currentScope = 'reconciliation'
      try {
        const dependencies = (await browserApi<{ blocking: Array<{ id: number }>; blocked_by: Array<{ id: number }> }>(
          page,
          accessToken,
          `/api/v1/threads/${fixture!.primary.id}/dependencies`,
        )).body
        const remaining = [...dependencies.blocking, ...dependencies.blocked_by]
          .some((dependency) => dependency.id === dependencyId)
        expect(remaining).toBe(false)
        fixture!.createdDependencyIds.delete(dependencyId)
        dependencyId = null
      } finally {
        currentScope = 'workload'
      }
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
      await page.goto('/analytics', { waitUntil: 'domcontentloaded' })
      await expect(page.locator('#root')).toBeVisible()
    })

    await runAction('reactivation', async () => {
      await gotoQueue(page)
      const completedCard = page.locator('.glass-card').filter({ hasText: fixture!.completed.title }).last()
      await expect(completedCard).toBeVisible({ timeout: 15_000 })
      await completedCard.getByRole('button', { name: 'Reactivate' }).click()
      const dialog = page.getByRole('dialog').filter({ hasText: 'Reactivate Thread' })
      await expect(dialog).toBeVisible()
      const response = await waitForMutationResponse(
        page,
        'POST',
        /^\/api\/threads\/reactivate$/,
        async () => dialog.getByRole('button', { name: 'Reactivate' }).click(),
      )
      expect(response?.ok()).toBe(true)
    })

    await runAction('mark-unread', async () => {
      const dialog = await openPrimaryEditModal(page, fixture!.primary.title)
      await ensureExpandedIssueList(dialog, 40)
      const response = await waitForMutationResponse(
        page,
        'POST',
        new RegExp(`^/api/v1/issues/${initiallyRead.id}:markUnread$`),
        async () => dialog.getByTestId(`issue-toggle-${initiallyRead.id}`).click(),
      )
      expect(response?.ok()).toBe(true)
      await page.getByRole('button', { name: 'Close' }).click()
    })

    await runAction('rating-second', async () => {
      await page.goto('/', { waitUntil: 'domcontentloaded' })
      ratingOutcomes.push(await rateThroughUi(
        'rating-second',
        fixture!.primary.id,
        fixture!.primary.title,
        4.5,
      ))
    })

    await runAction('dice-changes', async () => {
      for (const die of [50, 100, 4, 20]) {
        const response = await waitForMutationResponse(
          page,
          'POST',
          new RegExp(`^/api/roll/set-die\\?die=${die}$`),
          async () => page.getByRole('button', { name: `d${die}`, exact: true }).click(),
        )
        expect(response?.ok()).toBe(true)
      }
    })

    await runAction('roll-dismiss-second', async () => {
      await rollAndCancel(page)
    })

    await runAction('final-roll-rate', async () => {
      const dieResponse = await waitForMutationResponse(
        page,
        'POST',
        /^\/api\/roll\/set-die\?die=100$/,
        async () => page.getByRole('button', { name: 'd100', exact: true }).click(),
      )
      expect(dieResponse?.ok()).toBe(true)
      await rollAndCancel(page)
      ratingOutcomes.push(await rateThroughUi(
        'final-roll-rate',
        fixture!.primary.id,
        fixture!.primary.title,
        5,
      ))
    })
  } finally {
    if (accessToken) {
      await restoreSessionState()
      currentActionId = 'cleanup'
      currentScope = 'cleanup'
      const fixtureCleanup = await cleanupFixture(page, accessToken, fixture, beforeFingerprint)
      cleanupReport = {
        ...fixtureCleanup,
        errors: [...cleanupReport.errors, ...fixtureCleanup.errors],
      }
      cleanupReport.verified = fixtureCleanup.verified && cleanupReport.errors.length === 0

      if (initialSession) {
        try {
          const restored = (await browserApi<SessionCurrent>(page, accessToken, '/api/sessions/current/')).body
          const expectedPending = initialSession.pending_thread_id ?? null
          const actualPending = restored.pending_thread_id ?? null
          if (actualPending !== expectedPending) {
            cleanupReport.errors.push(`pending thread was not restored: expected ${expectedPending}, found ${actualPending}`)
          }
          const expectedManualDie = initialSession.manual_die ?? null
          const actualManualDie = restored.manual_die ?? null
          if (actualManualDie !== expectedManualDie) {
            cleanupReport.errors.push(`manual die was not restored: expected ${expectedManualDie}, found ${actualManualDie}`)
          }
        } catch (error) {
          cleanupReport.errors.push(`session cleanup verification: ${errorText(error)}`)
        }
        cleanupReport.verified = cleanupReport.verified && cleanupReport.errors.length === 0
      }
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
      reconciliationRequests: profile.records.filter((record) => record.scope === 'reconciliation').length,
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
    workloadExecution: {
      measuredActionsUseProductionUi: true,
      directApiUse: ['fixture setup', 'state snapshot', 'cleanup', 'timeout reconciliation'],
      knownSourceDivergence: [
        'The current queue search filters the already-loaded thread list in the browser, so the source HAR search strings are reproduced through the UI without issuing the obsolete server-side search requests.',
      ],
    },
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
      knownRouteDivergence: report.workloadExecution.knownSourceDivergence,
    }),
    attachJson(testInfo, 'production-profile.bug-report-construction.json', bugReportConstruction),
  ])

  expect(actionDivergence, 'Every source-HAR action group must execute').toEqual([])
  expect(cleanupReport, 'Fixture and session cleanup must be verified').toMatchObject({ verified: true })
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
