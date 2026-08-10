import { expect, test } from './fixtures';
import { SELECTORS } from './helpers';

type CurrentSession = {
  id: number;
  pending_thread_id: number | null;
  pending_issue_id?: number | null;
  current_die?: number;
  active_thread?: { title?: string; issue_number?: string | null } | null;
};

async function readCurrentSession(
  page: import('@playwright/test').Page,
  token: string,
): Promise<CurrentSession> {
  const response = await page.request.get('/api/sessions/current/', {
    headers: { Authorization: `Bearer ${token}` },
  });
  expect(response.ok()).toBeTruthy();
  return await response.json() as CurrentSession;
}

async function readAccessToken(page: import('@playwright/test').Page): Promise<string> {
  return await page.evaluate(() =>
    localStorage.getItem('auth_token')
    ?? (window as Window & { __COMIC_PILE_ACCESS_TOKEN?: string }).__COMIC_PILE_ACCESS_TOKEN
    ?? '',
  );
}

test('issue #984/#987: reload and auth recovery preserve one authoritative pending session', async ({
  authenticatedWithThreadsPage,
}) => {
  const page = authenticatedWithThreadsPage;

  await page.goto('/', { waitUntil: 'domcontentloaded' });
  await expect(page.locator('#root')).toBeVisible();

  const firstThreadCard = page.locator('[role="button"]').filter({
    has: page.locator('p.font-black'),
  }).first();
  await expect(firstThreadCard).toBeVisible({ timeout: 10000 });
  await firstThreadCard.click();
  await page.getByRole('button', { name: 'Read Now' }).click();
  await expect(page.locator(SELECTORS.rate.ratingInput)).toBeVisible({ timeout: 10000 });

  const tokenBeforeRecovery = await readAccessToken(page);
  expect(tokenBeforeRecovery).toBeTruthy();

  const initialSession = await readCurrentSession(page, tokenBeforeRecovery);
  expect(initialSession.pending_thread_id).not.toBeNull();
  expect(initialSession.active_thread?.title).toBeTruthy();

  for (let reload = 0; reload < 3; reload += 1) {
    await page.reload({ waitUntil: 'domcontentloaded' });
    await expect(page.locator(SELECTORS.rate.ratingInput)).toBeVisible({ timeout: 15000 });

    const token = await readAccessToken(page);
    expect(token).toBeTruthy();
    const reloadedSession = await readCurrentSession(page, token);

    expect(reloadedSession.id).toBe(initialSession.id);
    expect(reloadedSession.pending_thread_id).toBe(initialSession.pending_thread_id);
    expect(reloadedSession.pending_issue_id ?? null).toBe(initialSession.pending_issue_id ?? null);
    expect(reloadedSession.current_die).toBe(initialSession.current_die);
    expect(reloadedSession.active_thread?.title).toBe(initialSession.active_thread?.title);
    expect(reloadedSession.active_thread?.issue_number).toBe(initialSession.active_thread?.issue_number);
  }

  await page.evaluate(() => {
    const expiredToken = 'expired.access.token';
    localStorage.setItem('auth_token', expiredToken);
    (window as Window & { __COMIC_PILE_ACCESS_TOKEN?: string }).__COMIC_PILE_ACCESS_TOKEN = expiredToken;
  });

  await page.reload({ waitUntil: 'domcontentloaded' });

  await expect(page).toHaveURL('/');
  await expect(page.locator(SELECTORS.rate.ratingInput)).toBeVisible({ timeout: 15000 });
  await expect(page.locator('#thread-info h2')).toContainText(initialSession.active_thread!.title!);

  const tokenAfterRecovery = await readAccessToken(page);
  expect(tokenAfterRecovery).toBeTruthy();
  expect(tokenAfterRecovery).not.toBe('expired.access.token');

  const recoveredSession = await readCurrentSession(page, tokenAfterRecovery);

  expect(recoveredSession.id).toBe(initialSession.id);
  expect(recoveredSession.pending_thread_id).toBe(initialSession.pending_thread_id);
  expect(recoveredSession.pending_issue_id ?? null).toBe(initialSession.pending_issue_id ?? null);
  expect(recoveredSession.current_die).toBe(initialSession.current_die);
  expect(recoveredSession.active_thread?.title).toBe(initialSession.active_thread?.title);
  expect(recoveredSession.active_thread?.issue_number).toBe(initialSession.active_thread?.issue_number);
});
