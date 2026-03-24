import { test, expect } from './fixtures';
import { SELECTORS, createThread } from './helpers';

test.describe('Issue #325: Correct Issue Number from Rating View', () => {
  test.beforeEach(async ({ authenticatedWithThreadsPage }) => {
    await authenticatedWithThreadsPage.goto('/');
    await authenticatedWithThreadsPage.waitForLoadState('networkidle');
  });

  test('should display edit icon next to issue number in rating view', async ({ authenticatedWithThreadsPage }) => {
    const thread = await createThread(authenticatedWithThreadsPage, {
      title: 'Test Comic',
      format: 'comic',
      issues_remaining: 10,
      total_issues: 20,
      issue_range: '1-20',
    });

    const firstThreadCard = authenticatedWithThreadsPage.locator('[role="button"]').filter({
      has: authenticatedWithThreadsPage.locator('p.font-black'),
    }).first();
    await firstThreadCard.click();
    await authenticatedWithThreadsPage.getByText('Read Now', { exact: true }).click();
    await authenticatedWithThreadsPage.waitForSelector(SELECTORS.rate.ratingInput, { timeout: 10000 });

    const editIcon = authenticatedWithThreadsPage.locator('button[aria-label="Correct issue number"]');
    await expect(editIcon).toBeVisible({ timeout: 5000 });
    await expect(editIcon).toBeEnabled();
  });

  test('should open issue correction dialog when edit icon is clicked', async ({ authenticatedWithThreadsPage }) => {
    await createThread(authenticatedWithThreadsPage, {
      title: 'Test Comic',
      format: 'comic',
      issues_remaining: 10,
      total_issues: 20,
      issue_range: '1-20',
    });

    const firstThreadCard = authenticatedWithThreadsPage.locator('[role="button"]').filter({
      has: authenticatedWithThreadsPage.locator('p.font-black'),
    }).first();
    await firstThreadCard.click();
    await authenticatedWithThreadsPage.getByText('Read Now', { exact: true }).click();
    await authenticatedWithThreadsPage.waitForSelector(SELECTORS.rate.ratingInput, { timeout: 10000 });

    const editIcon = authenticatedWithThreadsPage.locator('button[aria-label="Correct issue number"]');
    await editIcon.click();

    await expect(authenticatedWithThreadsPage.getByRole('dialog', { name: /Correct Issue Number/i })).toBeVisible();
    await expect(authenticatedWithThreadsPage.getByText('What issue are you currently on?')).toBeVisible();
  });

  test('should allow incrementing issue number with + button', async ({ authenticatedWithThreadsPage }) => {
    await createThread(authenticatedWithThreadsPage, {
      title: 'Test Comic',
      format: 'comic',
      issues_remaining: 10,
      total_issues: 20,
      issue_range: '1-20',
    });

    const firstThreadCard = authenticatedWithThreadsPage.locator('[role="button"]').filter({
      has: authenticatedWithThreadsPage.locator('p.font-black'),
    }).first();
    await firstThreadCard.click();
    await authenticatedWithThreadsPage.getByText('Read Now', { exact: true }).click();
    await authenticatedWithThreadsPage.waitForSelector(SELECTORS.rate.ratingInput, { timeout: 10000 });

    const editIcon = authenticatedWithThreadsPage.locator('button[aria-label="Correct issue number"]');
    await editIcon.click();

    const issueInput = authenticatedWithThreadsPage.locator('input#issue-number');
    const initialValue = await issueInput.inputValue();

    const incrementButton = authenticatedWithThreadsPage.locator('button[aria-label="Increase issue number"]');
    await incrementButton.click();

    const newValue = await issueInput.inputValue();
    expect(parseInt(newValue, 10)).toBe(parseInt(initialValue, 10) + 1);
  });

  test('should allow decrementing issue number with - button', async ({ authenticatedWithThreadsPage }) => {
    await createThread(authenticatedWithThreadsPage, {
      title: 'Test Comic',
      format: 'comic',
      issues_remaining: 10,
      total_issues: 20,
      issue_range: '1-20',
    });

    const firstThreadCard = authenticatedWithThreadsPage.locator('[role="button"]').filter({
      has: authenticatedWithThreadsPage.locator('p.font-black'),
    }).first();
    await firstThreadCard.click();
    await authenticatedWithThreadsPage.getByText('Read Now', { exact: true }).click();
    await authenticatedWithThreadsPage.waitForSelector(SELECTORS.rate.ratingInput, { timeout: 10000 });

    const editIcon = authenticatedWithThreadsPage.locator('button[aria-label="Correct issue number"]');
    await editIcon.click();

    const issueInput = authenticatedWithThreadsPage.locator('input#issue-number');
    const initialValue = await issueInput.inputValue();
    const initialNum = parseInt(initialValue, 10);

    if (initialNum > 1) {
      const decrementButton = authenticatedWithThreadsPage.locator('button[aria-label="Decrease issue number"]');
      await decrementButton.click();

      const decrementedValue = await issueInput.inputValue();
      expect(parseInt(decrementedValue, 10)).toBe(initialNum - 1);
    } else {
      const incrementButton = authenticatedWithThreadsPage.locator('button[aria-label="Increase issue number"]');
      await incrementButton.click();

      const incrementedValue = await issueInput.inputValue();

      const decrementButton = authenticatedWithThreadsPage.locator('button[aria-label="Decrease issue number"]');
      await decrementButton.click();

      const decrementedValue = await issueInput.inputValue();
      expect(decrementedValue).toBe(initialValue);
    }
  });

  test('should validate issue number cannot be less than 1', async ({ authenticatedWithThreadsPage }) => {
    await createThread(authenticatedWithThreadsPage, {
      title: 'Test Comic',
      format: 'comic',
      issues_remaining: 10,
      total_issues: 20,
      issue_range: '1-20',
    });

    const firstThreadCard = authenticatedWithThreadsPage.locator('[role="button"]').filter({
      has: authenticatedWithThreadsPage.locator('p.font-black'),
    }).first();
    await firstThreadCard.click();
    await authenticatedWithThreadsPage.getByText('Read Now', { exact: true }).click();
    await authenticatedWithThreadsPage.waitForSelector(SELECTORS.rate.ratingInput, { timeout: 10000 });

    const editIcon = authenticatedWithThreadsPage.locator('button[aria-label="Correct issue number"]');
    await editIcon.click();

    const issueInput = authenticatedWithThreadsPage.locator('input#issue-number');
    await issueInput.fill('1');

    const decrementButton = authenticatedWithThreadsPage.locator('button[aria-label="Decrease issue number"]');
    await decrementButton.click();

    const value = await issueInput.inputValue();
    expect(value).toBe('1');
  });

  test('should validate issue number cannot exceed total issues', async ({ authenticatedWithThreadsPage }) => {
    await createThread(authenticatedWithThreadsPage, {
      title: 'Test Comic',
      format: 'comic',
      issues_remaining: 10,
      total_issues: 20,
      issue_range: '1-20',
    });

    const firstThreadCard = authenticatedWithThreadsPage.locator('[role="button"]').filter({
      has: authenticatedWithThreadsPage.locator('p.font-black'),
    }).first();
    await firstThreadCard.click();
    await authenticatedWithThreadsPage.getByText('Read Now', { exact: true }).click();
    await authenticatedWithThreadsPage.waitForSelector(SELECTORS.rate.ratingInput, { timeout: 10000 });

    const editIcon = authenticatedWithThreadsPage.locator('button[aria-label="Correct issue number"]');
    await editIcon.click();

    const issueInput = authenticatedWithThreadsPage.locator('input#issue-number');
    await issueInput.fill('20');

    const incrementButton = authenticatedWithThreadsPage.locator('button[aria-label="Increase issue number"]');
    await incrementButton.click();

    const value = await issueInput.inputValue();
    expect(value).toBe('20');
  });

  test('should close dialog when cancel is clicked', async ({ authenticatedWithThreadsPage }) => {
    await createThread(authenticatedWithThreadsPage, {
      title: 'Test Comic',
      format: 'comic',
      issues_remaining: 10,
      total_issues: 20,
      issue_range: '1-20',
    });

    const firstThreadCard = authenticatedWithThreadsPage.locator('[role="button"]').filter({
      has: authenticatedWithThreadsPage.locator('p.font-black'),
    }).first();
    await firstThreadCard.click();
    await authenticatedWithThreadsPage.getByText('Read Now', { exact: true }).click();
    await authenticatedWithThreadsPage.waitForSelector(SELECTORS.rate.ratingInput, { timeout: 10000 });

    const editIcon = authenticatedWithThreadsPage.locator('button[aria-label="Correct issue number"]');
    await editIcon.click();

    await expect(authenticatedWithThreadsPage.getByRole('dialog', { name: /Correct Issue Number/i })).toBeVisible();

    const cancelButton = authenticatedWithThreadsPage.locator('.fixed.inset-0.z-50').getByRole('button', { name: 'Cancel', exact: true });
    await cancelButton.click();

    await expect(authenticatedWithThreadsPage.getByRole('dialog', { name: /Correct Issue Number/i })).not.toBeVisible();
  });

  test('should close dialog when backdrop is clicked', async ({ authenticatedWithThreadsPage }) => {
    await createThread(authenticatedWithThreadsPage, {
      title: 'Test Comic',
      format: 'comic',
      issues_remaining: 10,
      total_issues: 20,
      issue_range: '1-20',
    });

    const firstThreadCard = authenticatedWithThreadsPage.locator('[role="button"]').filter({
      has: authenticatedWithThreadsPage.locator('p.font-black'),
    }).first();
    await firstThreadCard.click();
    await authenticatedWithThreadsPage.getByText('Read Now', { exact: true }).click();
    await authenticatedWithThreadsPage.waitForSelector(SELECTORS.rate.ratingInput, { timeout: 10000 });

    const editIcon = authenticatedWithThreadsPage.locator('button[aria-label="Correct issue number"]');
    await editIcon.click();

    await expect(authenticatedWithThreadsPage.getByRole('dialog', { name: /Correct Issue Number/i })).toBeVisible();

    const backdrop = authenticatedWithThreadsPage.locator('.fixed.inset-0.z-50');
    await backdrop.click({ position: { x: 10, y: 10 } });

    await expect(authenticatedWithThreadsPage.getByRole('dialog', { name: /Correct Issue Number/i })).not.toBeVisible();
  });

  test('should update issue number when update button is clicked', async ({ authenticatedWithThreadsPage }) => {
    const thread = await createThread(authenticatedWithThreadsPage, {
      title: 'Test Comic',
      format: 'comic',
      issues_remaining: 10,
      total_issues: 20,
      issue_range: '1-20',
    });

    const firstThreadCard = authenticatedWithThreadsPage.locator('[role="button"]').filter({
      has: authenticatedWithThreadsPage.locator('p.font-black'),
    }).first();
    await firstThreadCard.click();
    await authenticatedWithThreadsPage.getByText('Read Now', { exact: true }).click();
    await authenticatedWithThreadsPage.waitForSelector(SELECTORS.rate.ratingInput, { timeout: 10000 });

    const editIcon = authenticatedWithThreadsPage.locator('button[aria-label="Correct issue number"]');
    await editIcon.click();

    const issueInput = authenticatedWithThreadsPage.locator('input#issue-number');
    await issueInput.fill('5');

    const updateButton = authenticatedWithThreadsPage.getByRole('button', { name: 'Update' });
    await updateButton.click();

    await authenticatedWithThreadsPage.waitForLoadState('networkidle');
    await authenticatedWithThreadsPage.waitForTimeout(1000);

    const token = await authenticatedWithThreadsPage.evaluate(() => localStorage.getItem('auth_token'));
    const response = await authenticatedWithThreadsPage.request.get(`/api/threads/${thread.id}`, {
      headers: { Authorization: `Bearer ${token}` },
    });

    expect(response.ok()).toBeTruthy();
    const threadData = await response.json();

    expect(threadData.next_unread_issue_id).toBeDefined();
    expect(threadData.issues_remaining).toBeGreaterThan(0);
  });
});
