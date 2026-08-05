import { expect, test } from './fixtures';
import { SELECTORS, setRangeInput } from './helpers';

const CLIENT_TIMEOUT_MS = 50;
const RESPONSE_TAIL_DELAY_MS = 150;

type MutationCase = {
  name: 'rate' | 'snooze';
  endpoint: string;
  submit: (page: import('@playwright/test').Page) => Promise<void>;
};

async function installShortAxiosTimeout(page: import('@playwright/test').Page): Promise<void> {
  await page.addInitScript((timeoutMs: number) => {
    const descriptor = Object.getOwnPropertyDescriptor(XMLHttpRequest.prototype, 'timeout');
    if (!descriptor?.get || !descriptor.set) {
      throw new Error('XMLHttpRequest.timeout is not patchable in this browser');
    }

    const nativeTimeoutGetter = descriptor.get;
    const nativeTimeoutSetter = descriptor.set;
    Object.defineProperty(XMLHttpRequest.prototype, 'timeout', {
      configurable: true,
      enumerable: descriptor.enumerable,
      get: nativeTimeoutGetter,
      set(value: number) {
        nativeTimeoutSetter.call(this, Math.min(Number(value), timeoutMs));
      },
    });
  }, CLIENT_TIMEOUT_MS);
}

async function openRatingView(page: import('@playwright/test').Page): Promise<void> {
  await page.goto('/', { waitUntil: 'domcontentloaded' });
  await expect(page.locator('#root')).toBeVisible();

  const firstThreadCard = page.locator('[role="button"]').filter({
    has: page.locator('p.font-black'),
  }).first();
  await expect(firstThreadCard).toBeVisible({ timeout: 10000 });
  await firstThreadCard.click();
  await page.getByText('Read Now', { exact: true }).click();
  await expect(page.locator(SELECTORS.rate.ratingInput)).toBeVisible({ timeout: 10000 });
}

const mutationCases: MutationCase[] = [
  {
    name: 'rate',
    endpoint: '/api/rate/',
    submit: async (page) => {
      await setRangeInput(page, SELECTORS.rate.ratingInput, '4.5');
      await page.click(SELECTORS.rate.submitButton);
    },
  },
  {
    name: 'snooze',
    endpoint: '/api/snooze/',
    submit: async (page) => {
      await page.click(SELECTORS.rate.snoozeButton);
    },
  },
];

for (const mutationCase of mutationCases) {
  test(`recovers a committed ${mutationCase.name} after the browser times out`, async ({
    authenticatedWithThreadsPage,
    allowExpectedBrowserFailures,
  }) => {
    const page = authenticatedWithThreadsPage;
    let mutationRequests = 0;
    let reconciliationRequests = 0;

    allowExpectedBrowserFailures.allow(
      { category: 'requestfailed', message: mutationCase.endpoint },
      { category: 'console', message: `Failed to ${mutationCase.name} thread` },
      { category: 'console', message: 'Network Error' },
    );

    await installShortAxiosTimeout(page);
    await page.route(`**${mutationCase.endpoint}`, async (route) => {
      mutationRequests += 1;
      const committedResponse = await route.fetch();
      await new Promise((resolve) => setTimeout(resolve, RESPONSE_TAIL_DELAY_MS));
      try {
        await route.fulfill({ response: committedResponse });
      } catch {
        // The browser is expected to abandon the original XHR after 50 ms.
        // The backend fetch already completed, so reconciliation must observe
        // the committed authoritative state even when the late response cannot
        // be delivered to the timed-out client request.
      }
    });
    await page.route('**/api/sessions/current/**', async (route) => {
      reconciliationRequests += 1;
      await route.continue();
    });

    await openRatingView(page);
    const reconciliationBaseline = reconciliationRequests;

    await mutationCase.submit(page);

    await expect(page.locator(SELECTORS.rate.ratingInput)).toHaveCount(0, { timeout: 10000 });
    await expect(
      page.locator(SELECTORS.roll.mainDie).or(page.locator('[data-roll-pool]')).first(),
    ).toBeVisible({ timeout: 10000 });
    await expect.poll(() => reconciliationRequests).toBeGreaterThan(reconciliationBaseline);

    expect(mutationRequests).toBe(1);

    const token = await page.evaluate(() =>
      localStorage.getItem('auth_token')
      ?? (window as Window & { __COMIC_PILE_ACCESS_TOKEN?: string }).__COMIC_PILE_ACCESS_TOKEN
      ?? '',
    );
    const currentSession = await page.request.get('/api/sessions/current/', {
      headers: { Authorization: `Bearer ${token}` },
    });
    expect(currentSession.ok()).toBeTruthy();
    const authoritativeState = await currentSession.json() as { pending_thread_id?: number | null };
    expect(authoritativeState.pending_thread_id ?? null).toBeNull();
  });
}
