import { expect, type APIRequestContext, type Page } from '@playwright/test'
import { test } from './fixtures'
import { authHeaders, createThread, getFirstIssueId } from './helpers'
import type { CustomCBL, ReadingListReader } from '../services/api-custom-cbl'
import type {
  CreateDependencyResponse,
  GetIssueDependenciesResponse,
  IssueCardsResponse,
  IssueReadRateResponse,
  ListActivityResponse,
} from '../generated/nativeV2Client'

async function createReadingList(
  page: Page,
  name: string,
  issueIds: number[],
): Promise<CustomCBL> {
  const response = await page.request.post('/api/v2/reading-lists', {
    headers: await authHeaders(page),
    data: {
      name,
      description: 'MQA-LIST-004 deletion fixture',
      mode: 'loose',
      issue_ids: issueIds,
      entry_intents: Object.fromEntries(
        issueIds.map((issueId) => [issueId, { gate: 'none', skipped: false }]),
      ),
      checkpoint_issue_ids: [],
    },
  })
  expect(response.status(), await response.text()).toBe(201)
  // SAFETY: the canonical create endpoint returns the created Reading List contract.
  const list = (await response.json()) as CustomCBL
  expect(list.entries.map((entry) => entry.issue_id)).toEqual(issueIds)
  return list
}

async function getReadingList(page: Page, listId: number): Promise<CustomCBL> {
  const response = await page.request.get(`/api/v2/reading-lists/${listId}`, {
    headers: await authHeaders(page),
  })
  expect(response.ok(), await response.text()).toBeTruthy()
  // SAFETY: the canonical detail endpoint returns the Reading List contract.
  return (await response.json()) as CustomCBL
}

async function getReadingListReader(page: Page, listId: number): Promise<ReadingListReader> {
  const response = await page.request.get(`/api/v2/reading-lists/${listId}/reader`, {
    headers: await authHeaders(page),
  })
  expect(response.ok(), await response.text()).toBeTruthy()
  // SAFETY: the canonical reader endpoint returns the generated ReadingListReader contract.
  return (await response.json()) as ReadingListReader
}

async function getIssueCard(page: Page, issueId: number): Promise<IssueCardsResponse['items'][number]> {
  const response = await page.request.post('/api/v2/issues/cards', {
    headers: await authHeaders(page),
    data: { issue_ids: [issueId] },
  })
  expect(response.ok(), await response.text()).toBeTruthy()
  // SAFETY: the cards endpoint returns the generated IssueCardsResponse contract.
  const body = (await response.json()) as IssueCardsResponse
  const card = body.items.find((item) => item.issue_id === issueId)
  expect(card).toBeDefined()
  if (!card) throw new Error(`Issue card ${issueId} was not returned`)
  return card
}

async function getIssueHistory(
  page: Page,
  issueId: number,
): Promise<ListActivityResponse['items']> {
  const response = await page.request.get('/api/v2/activity', {
    headers: await authHeaders(page),
    params: { limit: 100 },
  })
  expect(response.ok(), await response.text()).toBeTruthy()
  // SAFETY: the activity endpoint returns the generated ActivityResponse contract.
  const body = (await response.json()) as ListActivityResponse
  return body.items.filter((item) => item.issue_id === issueId)
}

async function getIssueDependencies(
  page: Page,
  issueId: number,
): Promise<GetIssueDependenciesResponse> {
  const response = await page.request.get(`/api/v2/issues/${issueId}/dependencies`, {
    headers: await authHeaders(page),
  })
  expect(response.ok(), await response.text()).toBeTruthy()
  // SAFETY: the dependency endpoint returns its generated owner-scoped response contract.
  return (await response.json()) as GetIssueDependenciesResponse
}

async function registerForeignHeaders(
  request: APIRequestContext,
  suffix: string,
): Promise<Record<string, string>> {
  const credentials = {
    username: `cbl_foreign_${suffix}`,
    email: `cbl_foreign_${suffix}@example.com`,
    password: 'CblPrereqTest123!',
  }
  const registered = await request.post('/api/v2/auth/register', { data: credentials })
  expect(registered.ok(), await registered.text()).toBeTruthy()
  const loggedIn = await request.post('/api/v2/auth/login', {
    data: { username: credentials.username, password: credentials.password },
  })
  expect(loggedIn.ok(), await loggedIn.text()).toBeTruthy()
  // SAFETY: a successful login returns the bearer token used by this isolated request context.
  const auth = (await loggedIn.json()) as { access_token: string }
  const csrfResponse = await request.get('/api/v2/auth/csrf', {
    headers: { Authorization: `Bearer ${auth.access_token}` },
  })
  expect(csrfResponse.ok(), await csrfResponse.text()).toBeTruthy()
  // SAFETY: the CSRF endpoint returns the token required for the foreign DELETE attempt.
  const csrf = (await csrfResponse.json()) as { csrf_token: string }
  return {
    Authorization: `Bearer ${auth.access_token}`,
    'Content-Type': 'application/json',
    'X-CSRF-Token': csrf.csrf_token,
  }
}

/**
 * MQA-LIST-004 / #4186: canonical list deletion is owner-scoped and removes only
 * that list. A real reader prerequisite, durable read/rating history, and a
 * second list sharing the same issues must all survive byte-for-byte.
 */
test('MQA-LIST-004 explicit prerequisite and history survive canonical Reading List deletion', async ({
  authenticatedPage: page,
  allowExpectedBrowserFailures,
  browser,
}, testInfo) => {
  await page.setViewportSize({ width: 1280, height: 900 })
  const suffix = `${Date.now()}`
  const source = await createThread(page, {
    title: `Prerequisite Source ${suffix}`,
    format: 'Comics',
    issues_remaining: 1,
    total_issues: 1,
  })
  const target = await createThread(page, {
    title: `Prerequisite Target ${suffix}`,
    format: 'Comics',
    issues_remaining: 1,
    total_issues: 1,
  })
  const blockedTarget = await createThread(page, {
    title: `Prerequisite Blocked Target ${suffix}`,
    format: 'Comics',
    issues_remaining: 1,
    total_issues: 1,
  })
  const sourceIssueId = await getFirstIssueId(page, source.id)
  const targetIssueId = await getFirstIssueId(page, target.id)
  const blockedTargetIssueId = await getFirstIssueId(page, blockedTarget.id)
  const headers = await authHeaders(page)

  const dependencyResponse = await page.request.post('/api/v2/dependencies/', {
    headers,
    data: {
      source_type: 'issue',
      source_id: sourceIssueId,
      target_type: 'issue',
      target_id: targetIssueId,
    },
  })
  expect(dependencyResponse.status(), await dependencyResponse.text()).toBe(201)
  // SAFETY: dependency creation returns the generated DependencyResponse contract.
  const dependency = (await dependencyResponse.json()) as CreateDependencyResponse
  expect(dependency.source_issue_id).toBe(sourceIssueId)
  expect(dependency.target_issue_id).toBe(targetIssueId)

  const blockedDependencyResponse = await page.request.post('/api/v2/dependencies/', {
    headers,
    data: {
      source_type: 'issue',
      source_id: sourceIssueId,
      target_type: 'issue',
      target_id: blockedTargetIssueId,
    },
  })
  expect(blockedDependencyResponse.status(), await blockedDependencyResponse.text()).toBe(201)
  // SAFETY: the second dependency creates an unread target whose authoritative blocker can be observed.
  const blockedDependency = (await blockedDependencyResponse.json()) as CreateDependencyResponse
  expect(blockedDependency.target_issue_id).toBe(blockedTargetIssueId)

  const deletedList = await createReadingList(
    page,
    `Delete List ${suffix}`,
    [sourceIssueId, targetIssueId, blockedTargetIssueId],
  )
  const survivingList = await createReadingList(
    page,
    `Surviving List ${suffix}`,
    [sourceIssueId, targetIssueId, blockedTargetIssueId],
  )

  const ratingResponse = await page.request.patch(`/api/v2/issues/${targetIssueId}`, {
    headers,
    data: {
      status: 'read',
      rating: 4.5,
      idempotency_key: `mqa-list-delete-${targetIssueId}-${suffix}`,
      source: 'direct',
    },
  })
  expect(ratingResponse.ok(), await ratingResponse.text()).toBeTruthy()
  // SAFETY: the native issue mutation returns the generated read/rate receipt.
  const rating = (await ratingResponse.json()) as IssueReadRateResponse
  expect(rating.read_event_created).toBe(true)
  expect(rating.rating_event_created).toBe(true)
  expect(rating.issue).toMatchObject({ issue_id: targetIssueId, status: 'read', rating: 4.5 })
  expect(rating.issue.read_at).not.toBeNull()

  const beforeCard = await getIssueCard(page, targetIssueId)
  const beforeHistory = await getIssueHistory(page, targetIssueId)
  const beforeDependencies = await getIssueDependencies(page, targetIssueId)
  const beforeDeletedList = await getReadingList(page, deletedList.id)
  const beforeSurvivingList = await getReadingList(page, survivingList.id)
  expect(beforeCard).toEqual(rating.issue)
  expect(beforeHistory).toHaveLength(1)
  expect(beforeHistory[0]).toMatchObject({
    type: 'rate',
    issue_id: targetIssueId,
    rating: 4.5,
  })
  expect(beforeDependencies.incoming).toContainEqual(expect.objectContaining({
    dependency_id: dependency.id,
    source_issue_id: sourceIssueId,
  }))

  // A foreign owner's failed delete must not partially delete the owner's list.
  const foreignContext = await browser.newContext({ baseURL: testInfo.project.use.baseURL })
  try {
    const foreignHeaders = await registerForeignHeaders(foreignContext.request, suffix)
    const foreignDelete = await foreignContext.request.delete(
      `/api/v2/reading-lists/${deletedList.id}`,
      { headers: foreignHeaders },
    )
    expect(foreignDelete.status(), await foreignDelete.text()).toBe(404)
  } finally {
    await foreignContext.close()
  }
  expect(await getReadingList(page, deletedList.id)).toEqual(beforeDeletedList)

  // A real owner-side rejection must also leave the authoritative list untouched.
  const guardedList = await createReadingList(page, `Plan Linked List ${suffix}`, [sourceIssueId])
  const planResponse = await page.request.post('/api/v2/continuity-plans/', {
    headers,
    data: {
      name: `Linked Plan ${suffix}`,
      ordering_mode: 'informational',
      lanes: [{ id: 'main', name: 'Main', order: 0 }],
      nodes: [],
    },
  })
  expect(planResponse.ok(), await planResponse.text()).toBeTruthy()
  // SAFETY: successful plan creation returns its numeric ID.
  const linkedPlan = (await planResponse.json()) as { id: number }
  const applyResponse = await page.request.post(
    `/api/v2/reading-lists/${guardedList.id}/reading-plans/${linkedPlan.id}/applications`,
    { headers, data: { lane_id: 'main' } },
  )
  expect(applyResponse.ok(), await applyResponse.text()).toBeTruthy()
  const beforeGuardedList = await getReadingList(page, guardedList.id)
  const rejectedDelete = await page.request.delete(`/api/v2/reading-lists/${guardedList.id}`, { headers })
  const rejectedDeleteBody = await rejectedDelete.text()
  expect(rejectedDelete.status(), rejectedDeleteBody).toBe(409)
  expect(rejectedDeleteBody).toContain('nothing was changed')
  expect(await getReadingList(page, guardedList.id)).toEqual(beforeGuardedList)

  const beforeSurvivingReader = await getReadingListReader(page, survivingList.id)
  expect(beforeSurvivingReader.execution_mode).toBe('option_e')
  const blockedEntry = beforeSurvivingReader.entries.find(
    (entry) => entry.issue_id === blockedTargetIssueId,
  )
  expect(blockedEntry).toMatchObject({
    availability: 'blocked',
    explanation: { is_blocked: true },
  })
  expect(blockedEntry?.explanation?.blocking_dependencies).toContainEqual(expect.objectContaining({
    issue_id: sourceIssueId,
    thread_id: source.id,
    label: expect.stringContaining('Reader prerequisite'),
  }))

  await page.goto(`/reading-lists/${deletedList.id}`)
  await expect(page.getByRole('textbox', { name: 'Name', exact: true })).toHaveValue(deletedList.name)
  // Invalidating the deleted detail can produce one handled 404 after the 204.
  // Allow only that exact resource/status; the API assertion below requires it.
  const deletedApiUrl = new URL(`/api/v2/reading-lists/${deletedList.id}`, page.url()).toString()
  allowExpectedBrowserFailures.allow(
    {
      category: 'console',
      message: `Failed to load resource: the server responded with a status of 404 (Not Found) @ ${deletedApiUrl}`,
    },
    {
      category: 'console',
      message: `API Error: /v2/reading-lists/${deletedList.id} AxiosError: Request failed with status code 404`,
    },
  )
  await page.getByRole('button', { name: 'Delete', exact: true }).click()
  const dialog = page.getByRole('dialog', { name: 'Delete custom CBL' })
  await expect(dialog).toBeVisible()
  await expect(dialog).toContainText(deletedList.name)
  await expect(dialog).toContainText('Read history and ratings for those comics are not changed.')

  const deleteResponsePromise = page.waitForResponse((response) => (
    response.request().method() === 'DELETE'
    && new URL(response.url()).pathname === `/api/v2/reading-lists/${deletedList.id}`
  ))
  const confirm = dialog.getByRole('button', { name: 'Delete custom CBL' })
  await confirm.focus()
  await confirm.press('Enter')
  const deleteResponse = await deleteResponsePromise
  expect(deleteResponse.status()).toBe(204)
  await expect(dialog).toBeHidden()
  await expect(page.getByRole('status').filter({ hasText: 'Custom CBL deleted.' })).toBeVisible()

  const deletedDetail = await page.request.get(`/api/v2/reading-lists/${deletedList.id}`, { headers })
  expect(deletedDetail.status()).toBe(404)
  expect(await getReadingList(page, survivingList.id)).toEqual(beforeSurvivingList)
  expect(await getIssueCard(page, targetIssueId)).toEqual(beforeCard)
  expect(await getIssueHistory(page, targetIssueId)).toEqual(beforeHistory)
  expect(await getIssueDependencies(page, targetIssueId)).toEqual(beforeDependencies)
  expect(await getReadingListReader(page, survivingList.id)).toEqual(beforeSurvivingReader)

  await page.screenshot({
    path: testInfo.outputPath('cbl-delete-prerequisite-survival.png'),
    fullPage: true,
  })
})
