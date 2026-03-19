import { test, expect } from './fixtures';
import { createThread, setupAuthenticatedPage, getAuthToken } from './helpers';

test.describe('Issue 297: Completed Thread Active Slot', () => {
  test('should remove completed thread from active slot after rating last issue', async ({ page }) => {
    await setupAuthenticatedPage(page);

    const thread = await createThread(page, {
      title: 'Test Thread - Last Issue',
      format: 'comic',
      issues_remaining: 1,
      total_issues: 10,
      issue_range: '1-10',
    });

    const token = await getAuthToken(page);

    const issuesResponse = await page.request.get(`/api/v1/threads/${thread.id}/issues`, {
      headers: { Authorization: `Bearer ${token}` },
    });
    expect(issuesResponse.ok()).toBeTruthy();
    const issuesData = await issuesResponse.json();
    const issues = issuesData.issues;

    for (let i = 0; i < issues.length - 1; i++) {
      const markReadResponse = await page.request.post(`/api/v1/issues/${issues[i].id}:markRead`, {
        headers: { Authorization: `Bearer ${token}` },
      });
      expect(markReadResponse.ok()).toBeTruthy();
    }

    const beforeRateResponse = await page.request.get('/api/sessions/current/', {
      headers: { Authorization: `Bearer ${token}` },
    });
    expect(beforeRateResponse.ok()).toBeTruthy();
    const beforeSession = await beforeRateResponse.json();
    expect(beforeSession.active_thread).toBeNull();

    await page.request.post(`/api/threads/${thread.id}/set-pending`, {
      headers: { Authorization: `Bearer ${token}` },
    });

    await page.waitForTimeout(500);

    const pendingResponse = await page.request.get('/api/sessions/current/', {
      headers: { Authorization: `Bearer ${token}` },
    });
    const pendingSession = await pendingResponse.json();
    expect(pendingSession.active_thread?.id).toBe(thread.id);
    expect(pendingSession.active_thread?.issues_remaining).toBe(1);

    const threadBeforeRateResponse = await page.request.get(`/api/threads/${thread.id}`, {
      headers: { Authorization: `Bearer ${token}` },
    });
    const threadBeforeRate = await threadBeforeRateResponse.json();
    console.log('Thread before rate:', JSON.stringify(threadBeforeRate, null, 2));

    const issuesBeforeRateResponse = await page.request.get(`/api/v1/threads/${thread.id}/issues`, {
      headers: { Authorization: `Bearer ${token}` },
    });
    const issuesBeforeRate = await issuesBeforeRateResponse.json();
    console.log('Issues before rate:', JSON.stringify(issuesBeforeRate.issues.filter((i: any) => i.status === 'unread'), null, 2));

    const rateResponse = await page.request.post('/api/rate/', {
      headers: { Authorization: `Bearer ${token}` },
      data: {
        rating: 4.5,
        finish_session: false,
      },
    });
    expect(rateResponse.ok()).toBeTruthy();
    const rateData = await rateResponse.json();
    console.log('Rate response:', JSON.stringify(rateData, null, 2));

    const issuesAfterRateResponse = await page.request.get(`/api/v1/threads/${thread.id}/issues`, {
      headers: { Authorization: `Bearer ${token}` },
    });
    const issuesAfterRate = await issuesAfterRateResponse.json();
    console.log('Issues after rate:', JSON.stringify(issuesAfterRate.issues.filter((i: any) => i.status === 'unread'), null, 2));

    const threadAfterRateResponse = await page.request.get(`/api/threads/${thread.id}`, {
      headers: { Authorization: `Bearer ${token}` },
    });
    const threadAfterRate = await threadAfterRateResponse.json();
    console.log('Thread after rate:', JSON.stringify(threadAfterRate, null, 2));
    console.log('Thread status:', threadAfterRate.status);
    console.log('Thread reading_progress:', threadAfterRate.reading_progress);

    await page.waitForTimeout(500);

    const afterRateResponse = await page.request.get('/api/sessions/current/', {
      headers: { Authorization: `Bearer ${token}` },
    });
    expect(afterRateResponse.ok()).toBeTruthy();
    const afterSession = await afterRateResponse.json();
    console.log('After rate session:', JSON.stringify(afterSession.active_thread, null, 2));
    console.log('Thread status:', threadAfterRate.status);
    console.log('Thread reading_progress:', threadAfterRate.reading_progress);

    expect(threadAfterRate.status).toBe('completed');
    expect(threadAfterRate.reading_progress).toBe('completed');
    expect(afterSession.active_thread).toBeNull();
  });
});
