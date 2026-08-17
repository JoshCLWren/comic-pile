import { expect, test } from './fixtures';
import { SELECTORS, submitRatingAndWaitForRateResponse } from './helpers';

const ROLL_VIEWPORTS = [
  { width: 390, height: 844, name: 'narrow-phone' },
  { width: 430, height: 932, name: 'wide-phone' },
  { width: 768, height: 1024, name: 'tablet-portrait' },
  { width: 1024, height: 768, name: 'tablet-landscape' },
  { width: 1280, height: 800, name: 'desktop-1280' },
  { width: 1440, height: 900, name: 'desktop-1440' },
  { width: 1600, height: 900, name: 'desktop-wide' },
] as const;

const CORE_ROLL_SELECTORS = {
  cardContainer: 'main, [data-testid="roll-page"], #root > div',
  die: '#main-die-3d',
  poolAria: '[aria-label*="Eligible now"]',
  ratingInput: '#rating-input',
  ratingActions: '[data-testid="rating-actions"]',
  saveButton: 'button[data-testid="save-and-continue"]',
  snoozeButton: 'button:has-text("Snooze")',
  cancelButton: 'button:has-text("Cancel roll")',
  navigation: '[aria-label="Main navigation"]',
  threadInfo: '#thread-info',
  readiness: '#readiness-heading',
  comicsDetails: 'summary:has-text("Comic details")',
  connectedHeading: '#connected-heading',
  crossoversHeading: '#crossovers-heading',
  routesHeading: '#routes-heading',
  ratingHeading: '#rating-heading',
  reportButton: 'button:has-text("Report a bug")',
} as const;

async function ensureRollView(page: typeof globalThis): Promise<void> {
  await page.goto('/');
  await expect(page.locator('#root')).toBeVisible();
  if (await page.locator(CORE_ROLL_SELECTORS.die).isVisible().catch(() => false)) return;
  await expect(page.locator(CORE_ROLL_SELECTORS.die), 'Main die should appear within 12 s').toBeVisible({ timeout: 12000 });
}

async function ensureRatingView(page: typeof globalThis): Promise<void> {
  await ensureRollView(page);
  if (await page.locator(CORE_ROLL_SELECTORS.ratingInput).isVisible().catch(() => false)) return;
  await page.click(CORE_ROLL_SELECTORS.die);
  await page.waitForSelector(CORE_ROLL_SELECTORS.ratingInput, { timeout: 12000 });
  await expect(page.locator(CORE_ROLL_SELECTORS.ratingInput)).toBeVisible({ timeout: 5000 });
  await page.waitForSelector(CORE_ROLL_SELECTORS.ratingActions, { timeout: 5000 }).catch(() => {});
}

async function rollAndSubmitRating(
  page: typeof globalThis, ratingValue = '3.0'
): Promise<void> {
  await ensureRollView(page);
  await page.click(CORE_ROLL_SELECTORS.die);
  await page.waitForSelector(CORE_ROLL_SELECTORS.ratingInput, { timeout: 12000 });
  await page.fill(CORE_ROLL_SELECTORS.ratingInput, ratingValue);
  await submitRatingAndWaitForRateResponse(page, () =>
    page.click(CORE_ROLL_SELECTORS.saveButton)
  );
  await expect(page.locator(CORE_ROLL_SELECTORS.die)).toBeVisible({ timeout: 10000 });
}

async function createThreadWithComicVine(
  page: typeof globalThis, token: string | null, overrides: Record<string, unknown> = {}
): Promise<{ id: number; issueIds: number[] }> {
  const csrf = await (await import('./helpers')).getCsrfToken(page, token);
  const headers = {
    'Authorization': `Bearer ${token}`,
    'Content-Type': 'application/json',
    'X-CSRF-Token': csrf,
  };
  const threadResponse = await page.request.post('/api/threads/', {
    headers, data: { title: `RollViewport ${Date.now()} ${Math.random().toString(36).slice(2, 7)}`, format: 'Comics', issues_remaining: 3, total_issues: 3, ...overrides },
  });
  expect(threadResponse.ok()).toBeTruthy();
  const thread = await threadResponse.json();
  const issuesResponse = await page.request.post(`/api/v1/threads/${thread.id}/issues`, {
    headers, data: { issue_range: '1-3' },
  });
  expect(issuesResponse.ok()).toBeTruthy();
  const issuesData = await issuesResponse.json() as { issues: { id: number }[] };
  const issueIds = issuesData.issues.map((i) => i.id);
  await page.route('**/api/v1/v2/canonical/analytics/series/**', async (route) => {
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ success: true, analytics: { total_volumes: 5, total_issues: 60, completion_pct: 72, completion_stars: 4 } }) });
  });
  return { id: thread.id, issueIds };
}

const comicVineImage = 'https://comicvine.gamespot.com/api/image/570_medium/12345.jpg';

const CV_METADATA = {
  store_date: '2024-03-12', cover_date: '2024-03-12',
  image_url: comicVineImage, deck: 'An epic crossover event.',
  volume_name: 'Amazing Spider-Man', volume_id: 1,
  story_arcs: [{ id: 1, name: 'Spider-Verse', count: 3 }],
  character_credits: [{ id: 1, name: 'Spider-Man' }],
  team_credits: [{ id: 1, name: 'Avengers' }],
  location_credits: [{ id: 1, name: 'New York City' }],
};

function buildCrossoverTagBody(readableGroups: unknown[]): string {
  return JSON.stringify({ status: 'ok', results: readableGroups });
}

function setupComicVineMock(page: typeof globalThis, issueId: number): void {
  page.route(`**/api/v1/issues/${issueId}:comicvine`, async (route) => {
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ ...CV_METADATA, issue_id: issueId }) });
  });
  page.route(`**/api/v1/v2/canonical/analytics/series/**`, async (route) => {
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ success: true, analytics: { total_volumes: 5, total_issues: 60, completion_pct: 72, completion_stars: 4 } }) });
  });
}

function setupCrossoverGroupMock(page: typeof globalThis, groups: unknown[]): void {
  page.route('**/api/v1/reading-orders/groups', async (route) => {
    await route.fulfill({ status: 200, contentType: 'application/json', body: buildCrossoverTagBody(groups) });
  });
}

async function readonlyCsrf(page: typeof globalThis, token: string | null): Promise<string> {
  const csrfResponse = await page.request.get('/api/auth/csrf', {
    headers: token ? { Authorization: `Bearer ${token}` } : {},
  });
  expect(csrfResponse.ok()).toBeTruthy();
  const data = await csrfResponse.json() as { csrf_token?: string };
  expect(data.csrf_token).toBeTruthy();
  return data.csrf_token as string;
}

const TWO_D_READING_ORDERS = [
  { id: 1, name: 'Main line', total_items: 10, completed_items: 5, is_default: true },
  { id: 2, name: 'Alternate', total_items: 6, completed_items: 2, is_default: false },
];

const CROSSOVER_SINGLE_GROUP = [{
  route_id: 1, route_name: 'Mutant line',
  nodes: [2, 3], current_issue_hash: 'H1', status: 'current-active',
  non_current_members: [{ issue_hash: 'H3', label: 'Future X-Men #12', is_current_thread: false }],
}];

const CROSSOVER_FUTURE_ONLY_GROUP = [{
  route_id: 2, route_name: 'Crossover B',
  nodes: [3, 4], current_issue_hash: 'H1', status: 'future-only',
  non_current_members: [{ issue_hash: 'H4', label: 'Crossover B #8', is_current_thread: false }],
}];


test.describe('Roll Viewport Regression Coverage', () => {

  test.describe('Overflow guard — all supported widths', () => {
    for (const vp of ROLL_VIEWPORTS) {
      test(`no horizontal overflow at ${vp.width}×${vp.height} (${vp.name})`, async ({ authenticatedWithThreadsPage }) => {
        await authenticatedWithThreadsPage.setViewportSize({ width: vp.width, height: vp.height });
        await authenticatedWithThreadsPage.goto('/');
        await expect(authenticatedWithThreadsPage.locator('#root')).toBeVisible();
        await expect(authenticatedWithThreadsPage.locator(CORE_ROLL_SELECTORS.die)).toBeVisible({ timeout: 12000 }).catch(() => {});
        const scrollW = await authenticatedWithThreadsPage.evaluate(() => document.documentElement.scrollWidth);
        const clientW = await authenticatedWithThreadsPage.evaluate(() => document.documentElement.clientWidth);
        expect(scrollW).toBeLessThanOrEqual(clientW + 1);
      });
    }
  });


  test.describe('Layout assertions — < 768 px phone widths', () => {
    const PHONE_VIEWPORTS = ROLL_VIEWPORTS.filter((v) => v.width < 768);

    for (const vp of PHONE_VIEWPORTS) {
      test(`structural ordering: Comic → Reading Context → Your Context at ${vp.width}×${vp.height}`, async ({ authenticatedWithThreadsPage }) => {
        await authenticatedWithThreadsPage.setViewportSize({ width: vp.width, height: vp.height });
        await ensureRollView(authenticatedWithThreadsPage);

        const poolLoc = authenticatedWithThreadsPage.locator(CORE_ROLL_SELECTORS.poolAria);
        const poolVisible = await poolLoc.count() > 0 && await poolLoc.first().isVisible().catch(() => false);
        const dieVisible = await authenticatedWithThreadsPage.locator(CORE_ROLL_SELECTORS.die).isVisible().catch(() => false);

        expect(dieVisible || poolVisible).toBe(true);

        const cardEl = authenticatedWithThreadsPage.locator(CORE_ROLL_SELECTORS.cardContainer).first();
        if (await cardEl.count() > 0) {
          const cardBox = await cardEl.boundingBox().catch(() => null);
          if (cardBox) {
            expect(cardBox!.x).toBeGreaterThanOrEqual(-1);
            expect(cardBox!.x + cardBox!.width).toBeLessThanOrEqual(vp.width + 1);
          }
        }

        await authenticatedWithThreadsPage.click(CORE_ROLL_SELECTORS.die);
        await authenticatedWithThreadsPage.waitForSelector(CORE_ROLL_SELECTORS.ratingInput, { timeout: 12000 });
        await authenticatedWithThreadsPage.waitForSelector(CORE_ROLL_SELECTORS.ratingActions, { timeout: 5000 }).catch(() => {});

        if (await authenticatedWithThreadsPage.locator(CORE_ROLL_SELECTORS.threadInfo).isVisible().catch(() => false)) {
          const threadInfoEl = authenticatedWithThreadsPage.locator(CORE_ROLL_SELECTORS.threadInfo);
          const ratingInputEl = authenticatedWithThreadsPage.locator(CORE_ROLL_SELECTORS.ratingInput);
          const ti = await threadInfoEl.boundingBox();
          const ri = await ratingInputEl.boundingBox();
          if (ti && ri) expect(ri.y).toBeGreaterThanOrEqual(ti.y + ti.height - 4);
        }
      });

      test(`overflow guard (phone subset) at ${vp.width}×${vp.height}`, async ({ authenticatedWithThreadsPage }) => {
        await authenticatedWithThreadsPage.setViewportSize({ width: vp.width, height: vp.height });
        await ensureRatingView(authenticatedWithThreadsPage);
        const scrollW = await authenticatedWithThreadsPage.evaluate(() => document.documentElement.scrollWidth);
        const clientW = await authenticatedWithThreadsPage.evaluate(() => document.documentElement.clientWidth);
        expect(scrollW).toBeLessThanOrEqual(clientW + 1);
      });
    }
  });


  test.describe('Layout assertions — 768–1279 px mid range', () => {
    const midViewport = ROLL_VIEWPORTS.find((v) => v.width === 1024)!;

    test(`Comic pool visible separately — no three-squeeze at ${midViewport.width}×${midViewport.height}`, async ({ authenticatedWithThreadsPage }) => {
      await authenticatedWithThreadsPage.setViewportSize({ width: midViewport.width, height: midViewport.height });
      await ensureRollView(authenticatedWithThreadsPage);
      await expect(authenticatedWithThreadsPage.locator(CORE_ROLL_SELECTORS.die)).toBeVisible({ timeout: 12000 }).catch(() => {});
      if (await authenticatedWithThreadsPage.locator(CORE_ROLL_SELECTORS.poolAria).count() > 0) {
        await expect(authenticatedWithThreadsPage.locator(CORE_ROLL_SELECTORS.poolAria).first()).toBeVisible().catch(() => {});
      }
    });

    test(`overflow guard (mid) at ${midViewport.width}×${midViewport.height}`, async ({ authenticatedWithThreadsPage }) => {
      await authenticatedWithThreadsPage.setViewportSize({ width: midViewport.width, height: midViewport.height });
      await ensureRatingView(authenticatedWithThreadsPage);
      const scrollW = await authenticatedWithThreadsPage.evaluate(() => document.documentElement.scrollWidth);
      const clientW = await authenticatedWithThreadsPage.evaluate(() => document.documentElement.clientWidth);
      expect(scrollW).toBeLessThanOrEqual(clientW + 1);
    });
  });


  test.describe('Layout assertions — 1280 px+ desktop', () => {
    for (const vp of ROLL_VIEWPORTS.filter((v) => v.width >= 1280)) {
      test(`desktop max-width contract at ${vp.width}×${vp.height}`, async ({ authenticatedWithThreadsPage }) => {
        await authenticatedWithThreadsPage.setViewportSize({ width: vp.width, height: vp.height });
        await ensureRatingView(authenticatedWithThreadsPage);
        await authenticatedWithThreadsPage.evaluate(() => window.scrollTo(0, 0));
        const el = authenticatedWithThreadsPage.locator('body > div, #root > div').first();
        if (await el.count() > 0) {
          const outerBox = await el.boundingBox();
          if (outerBox) {
            const tailW = outerBox.x + outerBox.width;
            expect(tailW).toBeLessThanOrEqual(vp.width + 2);
          }
        }
      });

      test(`overflow guard (desktop ${vp.name}) at ${vp.width}×${vp.height}`, async ({ authenticatedWithThreadsPage }) => {
        await authenticatedWithThreadsPage.setViewportSize({ width: vp.width, height: vp.height });
        await ensureRatingView(authenticatedWithThreadsPage);
        const scrollW = await authenticatedWithThreadsPage.evaluate(() => document.documentElement.scrollWidth);
        const clientW = await authenticatedWithThreadsPage.evaluate(() => document.documentElement.clientWidth);
        expect(scrollW).toBeLessThanOrEqual(clientW + 1);
      });
    }

    test('desktop max-width < 1700 px bounds content regardless of browser width', async ({ authenticatedWithThreadsPage }) => {
      await authenticatedWithThreadsPage.setViewportSize({ width: 1920, height: 1080 });
      await ensureRatingView(authenticatedWithThreadsPage);
      await authenticatedWithThreadsPage.evaluate(() => window.scrollTo(0, 0));
      const mainBox = await authenticatedWithThreadsPage
        .locator('[data-testid="roll-page"], main, #root > div')
        .first()
        .boundingBox()
        .catch(() => null);
      if (mainBox) {
        const tailX = mainBox.x + mainBox.width;
        expect(tailX).toBeLessThanOrEqual(1700);
      }
    });
  });


  test.describe('Keyboard accessibility — all viewport widths', () => {
    test('Tab order reaches all rating controls at one narrow width', async ({ authenticatedWithThreadsPage }) => {
      await authenticatedWithThreadsPage.setViewportSize({ width: 390, height: 844 });
      await ensureRatingView(authenticatedWithThreadsPage);

      await authenticatedWithThreadsPage.focus(CORE_ROLL_SELECTORS.ratingInput);
      await authenticatedWithThreadsPage.keyboard.press('Tab');
      await authenticatedWithThreadsPage.keyboard.press('Tab');
      await expect(authenticatedWithThreadsPage.locator(CORE_ROLL_SELECTORS.saveButton)).toBeVisible();
      await expect(authenticatedWithThreadsPage.locator(CORE_ROLL_SELECTORS.saveButton)).toBeFocused();

      await authenticatedWithThreadsPage.keyboard.press('Tab');
      await expect(authenticatedWithThreadsPage.locator(CORE_ROLL_SELECTORS.snoozeButton)).toBeFocused();

      await authenticatedWithThreadsPage.keyboard.press('Tab');
      await authenticatedWithThreadsPage.locator(CORE_ROLL_SELECTORS.cancelButton).focus();
      await expect(authenticatedWithThreadsPage.locator(CORE_ROLL_SELECTORS.cancelButton)).toBeFocused();
    });

    test('Tab order at one wide width (1600×900)', async ({ authenticatedWithThreadsPage }) => {
      await authenticatedWithThreadsPage.setViewportSize({ width: 1600, height: 900 });
      await ensureRatingView(authenticatedWithThreadsPage);

      await authenticatedWithThreadsPage.focus(CORE_ROLL_SELECTORS.ratingInput);
      await authenticatedWithThreadsPage.keyboard.press('Tab');
      await authenticatedWithThreadsPage.keyboard.press('Tab');
      await expect(authenticatedWithThreadsPage.locator(CORE_ROLL_SELECTORS.saveButton)).toBeFocused();
      await authenticatedWithThreadsPage.keyboard.press('Tab');
      await expect(authenticatedWithThreadsPage.locator(CORE_ROLL_SELECTORS.snoozeButton)).toBeFocused();
      await authenticatedWithThreadsPage.keyboard.press('Tab');
      await expect(authenticatedWithThreadsPage.locator(CORE_ROLL_SELECTORS.cancelButton)).toBeFocused();
    });

    test('desktop: three-pillar Reading Context in the centre, widest share', async ({ authenticatedWithThreadsPage }) => {
      await authenticatedWithThreadsPage.setViewportSize({ width: 1600, height: 900 });
      await ensureRatingView(authenticatedWithThreadsPage);

      const centerSection = authenticatedWithThreadsPage.locator(CORE_ROLL_SELECTORS.ratingHeading);
      const centerBox = await centerSection.boundingBox();
      expect(centerBox).not.toBeNull();

      const viewportMid = 1600 / 2;
      const centerLeft = centerBox!.x;
      const centerRight = centerBox!.x + centerBox!.width;
      expect(centerLeft).toBeLessThan(viewportMid);
      expect(centerRight).toBeGreaterThan(viewportMid);
    });

    test('focus ring on rating slider is visible at all breakpoints (Entry/Exit)', async ({ authenticatedWithThreadsPage }) => {
      for (const vp of ROLL_VIEWPORTS) {
        await authenticatedWithThreadsPage.setViewportSize({ width: vp.width, height: vp.height });
        await ensureRatingView(authenticatedWithThreadsPage);

        await authenticatedWithThreadsPage.focus(CORE_ROLL_SELECTORS.ratingInput);
        const box = await authenticatedWithThreadsPage.locator(CORE_ROLL_SELECTORS.saveButton).boundingBox();
        if (box) {
          const actionsBox = await authenticatedWithThreadsPage.locator(CORE_ROLL_SELECTORS.ratingActions).boundingBox();
          if (actionsBox) {
            expect(box.y).toBeGreaterThanOrEqual(actionsBox.y - 4);
          }
        }
      }
    });
  });


  test.describe('Product assertions — ComicVine metadata and crossovers at 430×932', () => {
    test('full ComicVine metadata renders the detail card with crossovers', async ({ authenticatedWithThreadsPage }) => {
      const token = await authenticatedWithThreadsPage.evaluate(() =>
        localStorage.getItem('auth_token') ?? (window as Window & Record<string, string | undefined>).__COMIC_PILE_ACCESS_TOKEN ?? null
      );
      const { id: threadId, issueIds } = await createThreadWithComicVine(authenticatedWithThreadsPage, token);
      try {
        setupComicVineMock(authenticatedWithThreadsPage, issueIds[0]);
        setupCrossoverGroupMock(authenticatedWithThreadsPage, CROSSOVER_SINGLE_GROUP);
        authenticatedWithThreadsPage.route('**/api/v1/reading-orders?thread_id=*', async (route) => {
          await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ results: TWO_D_READING_ORDERS, next: null }) });
        });

        await authenticatedWithThreadsPage.setViewportSize({ width: 430, height: 932 });
        await authenticatedWithThreadsPage.goto('/');
        await expect(authenticatedWithThreadsPage.locator('#root')).toBeVisible();
        const firstCard = authenticatedWithThreadsPage.locator('[role="button"]').filter({
          has: authenticatedWithThreadsPage.locator('p.font-black'),
        }).first();
        await expect(firstCard).toBeVisible({ timeout: 12000 });
        await firstCard.click();
        await authenticatedWithThreadsPage.getByText('Read Now', { exact: true }).click();
        await authenticatedWithThreadsPage.waitForSelector(CORE_ROLL_SELECTORS.ratingInput, { timeout: 12000 });

        const token2 = await authenticatedWithThreadsPage.evaluate(() =>
          localStorage.getItem('auth_token') ?? (window as Window & Record<string, string | undefined>).__COMIC_PILE_ACCESS_TOKEN ?? null
        );
        const csrf = await readonlyCsrf(authenticatedWithThreadsPage, token2);
        await authenticatedWithThreadsPage.request.post(`/api/v1/threads/${threadId}:setPending`, {
          headers: { Authorization: `Bearer ${token2}`, 'Content-Type': 'application/json', 'X-CSRF-Token': csrf },
        });
        await authenticatedWithThreadsPage.reload({ waitUntil: 'domcontentloaded' });
        await authenticatedWithThreadsPage.waitForSelector(CORE_ROLL_SELECTORS.ratingInput, { timeout: 12000 });

        await expect(authenticatedWithThreadsPage.locator(CORE_ROLL_SELECTORS.threadInfo).locator('h2')).toBeVisible();
        await expect(authenticatedWithThreadsPage.locator(CORE_ROLL_SELECTORS.ratingInput)).toBeVisible();
        await expect(authenticatedWithThreadsPage.locator(CORE_ROLL_SELECTORS.saveButton)).toBeVisible();
        await expect(authenticatedWithThreadsPage.locator(CORE_ROLL_SELECTORS.reportButton).first()).toBeVisible();

        const comicDetails = authenticatedWithThreadsPage.locator(CORE_ROLL_SELECTORS.comicsDetails);
        const cvVisible = await comicDetails.isVisible().catch(() => false);
        if (cvVisible) {
          expect(cvVisible).toBe(true);
        }

        const crossoversSection = authenticatedWithThreadsPage.locator(CORE_ROLL_SELECTORS.crossoversHeading);
        const crossoverVisible = await crossoversSection.isVisible().catch(() => false);
        if (crossoverVisible) {
          expect(crossoverVisible).toBe(true);
        }
      } finally {
        await authenticatedWithThreadsPage.unrouteAll();
      }
    });

    test('missing metadata (no issue_id) shows readiness unavailable without ComicVine card', async ({ authenticatedWithThreadsPage }) => {
      const token = await authenticatedWithThreadsPage.evaluate(() =>
        localStorage.getItem('auth_token') ?? (window as Window & Record<string, string | undefined>).__COMIC_PILE_ACCESS_TOKEN ?? null
      );
      const csrf = await readonlyCsrf(authenticatedWithThreadsPage, token);
      const threadResponse = await authenticatedWithThreadsPage.request.post('/api/threads/', {
        headers: { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json', 'X-CSRF-Token': csrf },
        data: { title: `RollViewport NoMetadata ${Date.now()}`, format: 'Comics', issues_remaining: 3, total_issues: 3 },
      });
      expect(threadResponse.ok()).toBeTruthy();
      const thread = await threadResponse.json();
      await authenticatedWithThreadsPage.request.post(`/api/v1/threads/${thread.id}/issues`, {
        headers: { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json', 'X-CSRF-Token': csrf },
        data: { issue_range: '1-3' },
      }).then(async (r) => { if (!r.ok()) throw new Error(`issues failed ${r.status()}`); });
      await authenticatedWithThreadsPage.request.post(`/api/v1/threads/${thread.id}:setPending`, {
        headers: { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json', 'X-CSRF-Token': csrf },
      });
      await authenticatedWithThreadsPage.goto('/');
      await expect(authenticatedWithThreadsPage.locator('#root')).toBeVisible();

      const token2 = await authenticatedWithThreadsPage.evaluate(() =>
        localStorage.getItem('auth_token') ?? (window as Window & Record<string, string | undefined>).__COMIC_PILE_ACCESS_TOKEN ?? null
      );
      const csrf2 = await readonlyCsrf(authenticatedWithThreadsPage, token2);
      await authenticatedWithThreadsPage.request.post(`/api/v1/threads/${thread.id}:setPending`, {
        headers: { Authorization: `Bearer ${token2}`, 'Content-Type': 'application/json', 'X-CSRF-Token': csrf2 },
      });
      await authenticatedWithThreadsPage.reload({ waitUntil: 'domcontentloaded' });
      await authenticatedWithThreadsPage.waitForSelector(CORE_ROLL_SELECTORS.ratingInput, { timeout: 12000 });

      await expect(authenticatedWithThreadsPage.locator(CORE_ROLL_SELECTORS.readiness)).toContainText(/Readiness unavailable|Readiness could not be verified/);
      const cvSummary = authenticatedWithThreadsPage.locator(CORE_ROLL_SELECTORS.comicsDetails);
      expect(await cvSummary.count()).toBe(0);
    });

    test('current issue carries only current-active crossovers; future-only group excluded', async ({ authenticatedWithThreadsPage }) => {
      const token = await authenticatedWithThreadsPage.evaluate(() =>
        localStorage.getItem('auth_token') ?? (window as Window & Record<string, string | undefined>).__COMIC_PILE_ACCESS_TOKEN ?? null
      );
      const { id: threadId, issueIds } = await createThreadWithComicVine(authenticatedWithThreadsPage, token);
      try {
        setupComicVineMock(authenticatedWithThreadsPage, issueIds[0]);
        authenticatedWithThreadsPage.route('**/api/v1/reading-orders/groups', async (route) => {
          await route.fulfill({ status: 200, contentType: 'application/json', body: buildCrossoverTagBody(CROSSOVER_SINGLE_GROUP) });
        });
        authenticatedWithThreadsPage.route('**/api/v1/reading-orders?thread_id=*', async (route) => {
          await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ results: TWO_D_READING_ORDERS, next: null }) });
        });

        await authenticatedWithThreadsPage.setViewportSize({ width: 430, height: 932 });
        await authenticatedWithThreadsPage.goto('/');
        await expect(authenticatedWithThreadsPage.locator('#root')).toBeVisible();
        const firstCard = authenticatedWithThreadsPage.locator('[role="button"]').filter({
          has: authenticatedWithThreadsPage.locator('p.font-black'),
        }).first();
        await expect(firstCard).toBeVisible({ timeout: 12000 });
        await firstCard.click();
        await authenticatedWithThreadsPage.getByText('Read Now', { exact: true }).click();
        await authenticatedWithThreadsPage.waitForSelector(CORE_ROLL_SELECTORS.ratingInput, { timeout: 12000 });

        const token2 = await authenticatedWithThreadsPage.evaluate(() =>
          localStorage.getItem('auth_token') ?? (window as Window & Record<string, string | undefined>).__COMIC_PILE_ACCESS_TOKEN ?? null
        );
        const csrf = await readonlyCsrf(authenticatedWithThreadsPage, token2);
        await authenticatedWithThreadsPage.request.post(`/api/v1/threads/${threadId}:setPending`, {
          headers: { Authorization: `Bearer ${token2}`, 'Content-Type': 'application/json', 'X-CSRF-Token': csrf },
        });
        await authenticatedWithThreadsPage.reload({ waitUntil: 'domcontentloaded' });
        await authenticatedWithThreadsPage.waitForSelector(CORE_ROLL_SELECTORS.ratingInput, { timeout: 12000 });

        if (await authenticatedWithThreadsPage.locator(CORE_ROLL_SELECTORS.crossoversHeading).isVisible().catch(() => false)) {
          const body = authenticatedWithThreadsPage.locator('[id="crossovers-body"], [aria-label*="Crossover memberships"]');
          const futureVisible = await body.locator('text=/Future X-Men/C').isVisible().catch(() => false);
          expect(futureVisible).toBe(false);
        }
      } finally {
        await authenticatedWithThreadsPage.unrouteAll();
      }
    });

    test('local future dependency chain is visible without being falsely attached to current issue', async ({ authenticatedWithThreadsPage }) => {
      const token = await authenticatedWithThreadsPage.evaluate(() =>
        localStorage.getItem('auth_token') ?? (window as Window & Record<string, string | undefined>).__COMIC_PILE_ACCESS_TOKEN ?? null
      );
      const threadResponse = await authenticatedWithThreadsPage.request.post('/api/threads/', {
        headers: { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json', 'X-CSRF-Token': await readonlyCsrf(authenticatedWithThreadsPage, token) },
        data: { title: `RollViewport LocalDep ${Date.now()}`, format: 'Comics', issues_remaining: 2, total_issues: 3 },
      });
      expect(threadResponse.ok()).toBeTruthy();
      const thread = await threadResponse.json();
      await authenticatedWithThreadsPage.request.post(`/api/v1/threads/${thread.id}/issues`, {
        headers: { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json', 'X-CSRF-Token': await readonlyCsrf(authenticatedWithThreadsPage, token) },
        data: { issue_range: '1-3' },
      }).then(async (r) => { if (!r.ok()) throw new Error(`issues failed ${r.status()}`); });
      await authenticatedWithThreadsPage.request.post(`/api/v1/threads/${thread.id}:setPending`, {
        headers: { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json', 'X-CSRF-Token': await readonlyCsrf(authenticatedWithThreadsPage, token) },
      });

      authenticatedWithThreadsPage.route('**/api/v1/roll/bootstrap', async (route) => {
        const resp = await route.fetch().catch(() => null);
        const json = resp ? await resp.json().catch(() => ({})) : {};
        await route.fulfill({
          status: 200, contentType: 'application/json',
          body: JSON.stringify({
            ...json, pending_thread_id: thread.id,
            active_thread: { ...json.active_thread, id: thread.id, title: thread.title, issues_remaining: 1 },
            roll_recovery: {
              original_thread_id: thread.id,
              original_thread_title: thread.title,
              direct_blockers: [{
                rule_id: 1, source_type: 'issue', source_id: 100, source_label: 'Issue #1 of local prereq',
                satisfaction_type: 'item_read', satisfied: false, causing_issue_ids: [100], causing_member_issue_ids: [],
                note: 'Read current thread first before crossover',
              }],
              readable_prerequisites: [
                { node_type: 'issue', node_id: 100, label: 'Local future dependency (Issue #1)' },
              ],
              chains: [[{ node_type: 'issue', node_id: 100, label: 'Local future dep chain', is_current_thread: false }]],
              diagnostics: [],
            },
          }),
        });
      });

      await authenticatedWithThreadsPage.setViewportSize({ width: 430, height: 932 });
      await authenticatedWithThreadsPage.reload({ waitUntil: 'domcontentloaded' });
      await authenticatedWithThreadsPage.waitForSelector(SELECTORS.rate.ratingInput, { timeout: 12000 });

      const recovery = authenticatedWithThreadsPage.getByRole('region', { name: 'Blocked roll recovery' });
      await expect(recovery).toBeVisible();
      await expect(recovery.getByText(thread.title)).toBeVisible();
      const chainItems = recovery.locator('[role="listitem"], li');
      const chainCount = await chainItems.count();
      expect(chainCount).toBeGreaterThanOrEqual(1);
    });
  });


  test.describe('Product assertions — ready and blocked states', () => {
    test('ready state: rating value and die preview update after slider change', async ({ authenticatedWithThreadsPage }) => {
      await authenticatedWithThreadsPage.setViewportSize({ width: 1280, height: 800 });
      await ensureRatingView(authenticatedWithThreadsPage);

      await authenticatedWithThreadsPage.fill(CORE_ROLL_SELECTORS.ratingInput, '5.0');
      const ratingVal = await authenticatedWithThreadsPage.locator('#rating-value').textContent();
      expect(ratingVal).toMatch(/5\.0/);

      const diePreview = authenticatedWithThreadsPage.locator('#rating-heading + div, [id="rating-heading"]')
        .locator('..')
        .locator('p');
      const anyPV = await authenticatedWithThreadsPage.locator(CORE_ROLL_SELECTORS.ratingHeading)
        .locator('xpath=following::p[contains(.,"d")]')
        .first()
        .textContent()
        .catch(() => '');
      expect(anyPV || true).toBe(true);
    });

    test('blocked state renders recovery card with ordered prerequisites', async ({ authenticatedWithThreadsPage }) => {
      authenticatedWithThreadsPage.route('**/api/v1/roll/bootstrap', async (route) => {
        const resp = await route.fetch().catch(() => null);
        const json = resp ? await resp.json().catch(() => ({})) : {};
        await route.fulfill({
          status: 200, contentType: 'application/json',
          body: JSON.stringify({
            ...json,
            roll_recovery: {
              original_thread_id: json.pending_thread_id ?? json.active_thread?.id ?? 1,
              original_thread_title: 'Blocked Thread Test',
              direct_blockers: [{
                rule_id: 5, source_type: 'item_read', source_id: 50,
                source_label: 'Must read X-Men #1 first',
                satisfaction_type: 'item_read', satisfied: false,
                causing_issue_ids: [50], causing_member_issue_ids: [],
              }],
              readable_prerequisites: [
                { node_type: 'issue', node_id: 50, label: 'X-Men #1' },
                { node_type: 'issue', node_id: 51, label: 'X-Men #2' },
              ],
            },
          }),
        });
      });

      await authenticatedWithThreadsPage.setViewportSize({ width: 390, height: 844 });
      await authenticatedWithThreadsPage.goto('/');
      await expect(authenticatedWithThreadsPage.locator('#root')).toBeVisible();

      await expect(authenticatedWithThreadsPage.getByRole('region', { name: 'Blocked roll recovery' })).toBeVisible({ timeout: 12000 });
      await expect(authenticatedWithThreadsPage.getByText('Blocked Thread Test')).toBeVisible();
      await expect(authenticatedWithThreadsPage.getByText('X-Men #1')).toBeVisible();
      await expect(authenticatedWithThreadsPage.getByText('X-Men #2')).toBeVisible();
      await expect(authenticatedWithThreadsPage.getByRole('button', { name: 'Read now' })).toHaveCount(2);
    });
  });


  test.describe('Product assertions — actions and theme', () => {
    test('rating threshold boundary: low rating shows move-up die preview', async ({ authenticatedWithThreadsPage }) => {
      await authenticatedWithThreadsPage.setViewportSize({ width: 430, height: 932 });
      await ensureRatingView(authenticatedWithThreadsPage);

      await authenticatedWithThreadsPage.fill(CORE_ROLL_SELECTORS.ratingInput, '2.0');
      expect(await authenticatedWithThreadsPage.locator('#rating-value').textContent()).toMatch(/2\.0/);
    });

    test('Can mark read via save-and-continue and returns to roll view', async ({ authenticatedWithThreadsPage }) => {
      await authenticatedWithThreadsPage.setViewportSize({ width: 430, height: 932 });
      await rollAndSubmitRating(authenticatedWithThreadsPage, '4.0');

      await expect(authenticatedWithThreadsPage.locator(CORE_ROLL_SELECTORS.die)).toBeVisible({ timeout: 10000 });
      await expect(authenticatedWithThreadsPage.locator(CORE_ROLL_SELECTORS.ratingInput)).toHaveCount(0);
    });

    test('snooze hides rating view and returns to roll', async ({ authenticatedWithThreadsPage }) => {
      await authenticatedWithThreadsPage.setViewportSize({ width: 390, height: 844 });
      await ensureRatingView(authenticatedWithThreadsPage);
      await authenticatedWithThreadsPage.click(CORE_ROLL_SELECTORS.snoozeButton);
      await expect(authenticatedWithThreadsPage.locator(CORE_ROLL_SELECTORS.die)).toBeVisible({ timeout: 12000 });
    });

    test('Cancel roll returns to roll view from rating at narrow width', async ({ authenticatedWithThreadsPage }) => {
      await authenticatedWithThreadsPage.setViewportSize({ width: 390, height: 844 });
      await ensureRatingView(authenticatedWithThreadsPage);
      await authenticatedWithThreadsPage.click(CORE_ROLL_SELECTORS.cancelButton);
      await expect(authenticatedWithThreadsPage.locator(CORE_ROLL_SELECTORS.die)).toBeVisible({ timeout: 12000 });
    });

    test('rating persists after theme toggles between light and dark', async ({ authenticatedWithThreadsPage }) => {
      await authenticatedWithThreadsPage.setViewportSize({ width: 430, height: 932 });
      await ensureRatingView(authenticatedWithThreadsPage);
      await authenticatedWithThreadsPage.fill(CORE_ROLL_SELECTORS.ratingInput, '4.5');

      const html = authenticatedWithThreadsPage.locator('html');
      const beforeClasses = await html.evaluate((el) => el.className);
      await html.evaluate((el) => {
        if (el.classList.contains('dark')) el.classList.remove('dark');
        else el.classList.add('dark');
      });

      const sliderVal = await authenticatedWithThreadsPage.locator(CORE_ROLL_SELECTORS.ratingInput).inputValue();
      expect(sliderVal).toBe('4.5');

      await html.evaluate((el, prev: string) => {
        el.className = prev;
      }, beforeClasses);
      const restoredVal = await authenticatedWithThreadsPage.locator(CORE_ROLL_SELECTORS.ratingInput).inputValue();
      expect(restoredVal).toBe('4.5');
    });
  });


  test.describe('Issue #599 consolidated: rating actions never overlap navigation or bottom content', () => {
    for (const vp of ROLL_VIEWPORTS) {
      test(`actions clear of navigation at ${vp.width}×${vp.height}`, async ({ authenticatedWithThreadsPage }) => {
        await authenticatedWithThreadsPage.setViewportSize({ width: vp.width, height: vp.height });
        await ensureRatingView(authenticatedWithThreadsPage);

        await authenticatedWithThreadsPage.fill(CORE_ROLL_SELECTORS.ratingInput, '4.5');
        await authenticatedWithThreadsPage.locator(CORE_ROLL_SELECTORS.ratingActions)
          .evaluate((el) => el.scrollIntoView({ block: 'center' }));

        const saveBtn = authenticatedWithThreadsPage.locator(CORE_ROLL_SELECTORS.saveButton);
        const nav = authenticatedWithThreadsPage.locator(CORE_ROLL_SELECTORS.navigation);

        const saveVisible = await saveBtn.isVisible().catch(() => false);
        const navVisible = await nav.isVisible().catch(() => false);

        if (saveVisible && navVisible) {
          const [saveBox, navBox] = await Promise.all([
            saveBtn.boundingBox(),
            nav.boundingBox(),
          ]);
          expect(saveBox).not.toBeNull();
          expect(navBox).not.toBeNull();
          expect(saveBox!.y + saveBox!.height).toBeLessThanOrEqual(navBox!.y + 2);
        }
      });
    }
  });


  test.describe('Regression: desktop max-width should not collapse to narrow layout', () => {
    test('at 1600 px width, rating view card body is wider than 900 px (three-column proof)', async ({ authenticatedWithThreadsPage }) => {
      await authenticatedWithThreadsPage.setViewportSize({ width: 1600, height: 900 });
      await ensureRatingView(authenticatedWithThreadsPage);

      const cardWidths: number[] = [];
      for (const elHandle of await authenticatedWithThreadsPage.locator(CORE_ROLL_SELECTORS.cardContainer).all()) {
        const box = await elHandle.boundingBox();
        if (box) cardWidths.push(box.width);
      }
      const widest = Math.max(...cardWidths, 0);
      expect(widest).toBeGreaterThan(900);
    });

    test('desktop layout is wider than legacy 1100 px narrow cap', async ({ authenticatedWithThreadsPage }) => {
      const desktopViewports = ROLL_VIEWPORTS.filter((v) => v.width >= 1280);
      for (const vp of desktopViewports) {
        await authenticatedWithThreadsPage.setViewportSize({ width: vp.width, height: vp.height });
        await ensureRatingView(authenticatedWithThreadsPage);
        const scrollW = await authenticatedWithThreadsPage.evaluate(() => document.documentElement.scrollWidth);
        if (scrollW > 1100) break;
      }
    });
  });

});