import { test, expect } from './fixtures';

test.describe('CollectionDialog Success Feedback', () => {
  test('should show success toast after creating collection', async ({ authenticatedWithThreadsPage }) => {
    await authenticatedWithThreadsPage.goto('/');
    await authenticatedWithThreadsPage.waitForLoadState('networkidle');

    const newButton = authenticatedWithThreadsPage.getByRole('button', { name: /new collection/i });
    await newButton.click();

    const dialog = authenticatedWithThreadsPage.getByRole('dialog');
    await expect(dialog).toBeVisible();

    const collectionName = `Success Test ${Date.now()}`;
    const nameInput = authenticatedWithThreadsPage.getByPlaceholder('Enter collection name');
    await nameInput.fill(collectionName);

    const createButton = dialog.getByRole('button', { name: 'Create' });
    await createButton.click();

    const toast = authenticatedWithThreadsPage.getByTestId('toast-notification');
    await expect(toast).toBeVisible();
    await expect(toast).toContainText(`Collection "${collectionName}" created successfully`);
  });

  test('should auto-dismiss success toast', async ({ authenticatedWithThreadsPage }) => {
    await authenticatedWithThreadsPage.goto('/');
    await authenticatedWithThreadsPage.waitForLoadState('networkidle');

    const newButton = authenticatedWithThreadsPage.getByRole('button', { name: /new collection/i });
    await newButton.click();

    const dialog = authenticatedWithThreadsPage.getByRole('dialog');
    await expect(dialog).toBeVisible();

    const collectionName = `Auto-Dismiss ${Date.now()}`;
    const nameInput = authenticatedWithThreadsPage.getByPlaceholder('Enter collection name');
    await nameInput.fill(collectionName);

    const createButton = dialog.getByRole('button', { name: 'Create' });
    await createButton.click();

    const toast = authenticatedWithThreadsPage.getByTestId('toast-notification');
    await expect(toast).toBeVisible();

    await expect(toast).toBeHidden({ timeout: 6000 });
  });

  test('should not show success toast on validation error', async ({ authenticatedWithThreadsPage }) => {
    await authenticatedWithThreadsPage.goto('/');
    await authenticatedWithThreadsPage.waitForLoadState('networkidle');

    const newButton = authenticatedWithThreadsPage.getByRole('button', { name: /new collection/i });
    await newButton.click();

    const dialog = authenticatedWithThreadsPage.getByRole('dialog');
    await expect(dialog).toBeVisible();

    const createButton = dialog.getByRole('button', { name: 'Create' });
    await createButton.click();

    const errorMessage = authenticatedWithThreadsPage.getByRole('alert');
    await expect(errorMessage).toContainText('Collection name is required');

    const toast = authenticatedWithThreadsPage.getByTestId('toast-notification');
    await expect(toast).not.toBeVisible();
  });

  test('should not show success toast on network error', async ({ authenticatedWithThreadsPage, context }) => {
    await authenticatedWithThreadsPage.goto('/');
    await authenticatedWithThreadsPage.waitForLoadState('networkidle');

    const newButton = authenticatedWithThreadsPage.getByRole('button', { name: /new collection/i });
    await newButton.click();

    const dialog = authenticatedWithThreadsPage.getByRole('dialog');
    await expect(dialog).toBeVisible();

    const collectionName = `Network Error ${Date.now()}`;
    const nameInput = authenticatedWithThreadsPage.getByPlaceholder('Enter collection name');
    await nameInput.fill(collectionName);

    await context.route('/api/v1/collections/', route => route.abort());

    const createButton = dialog.getByRole('button', { name: 'Create' });
    await createButton.click();

    const toast = authenticatedWithThreadsPage.getByTestId('toast-notification');
    await expect(toast).not.toBeVisible();

    const errorMessage = authenticatedWithThreadsPage.getByRole('alert');
    await expect(errorMessage).toBeVisible();
  });

  test('should close dialog cleanly after successful creation', async ({ authenticatedWithThreadsPage }) => {
    await authenticatedWithThreadsPage.goto('/');
    await authenticatedWithThreadsPage.waitForLoadState('networkidle');

    const newButton = authenticatedWithThreadsPage.getByRole('button', { name: /new collection/i });
    await newButton.click();

    const dialog = authenticatedWithThreadsPage.getByRole('dialog');
    await expect(dialog).toBeVisible();

    const collectionName = `Clean Close ${Date.now()}`;
    const nameInput = authenticatedWithThreadsPage.getByPlaceholder('Enter collection name');
    await nameInput.fill(collectionName);

    const createButton = dialog.getByRole('button', { name: 'Create' });
    await createButton.click();

    await expect(dialog).toBeHidden();

    const toast = authenticatedWithThreadsPage.getByTestId('toast-notification');
    await expect(toast).toBeVisible();
  });

  test('should show success toast after updating collection', async ({ authenticatedWithThreadsPage, request }) => {
    await authenticatedWithThreadsPage.goto('/');
    await authenticatedWithThreadsPage.waitForLoadState('networkidle');

    const collectionName = `Update Test ${Date.now()}`;
    const updatedName = `${collectionName} - Updated`;

    const newButton = authenticatedWithThreadsPage.getByRole('button', { name: /new collection/i });
    await newButton.click();

    const dialog = authenticatedWithThreadsPage.getByRole('dialog');
    await expect(dialog).toBeVisible();

    const nameInput = authenticatedWithThreadsPage.getByPlaceholder('Enter collection name');
    await nameInput.fill(collectionName);

    const createButton = dialog.getByRole('button', { name: 'Create' });
    await createButton.click();

    const toast = authenticatedWithThreadsPage.getByTestId('toast-notification');
    await expect(toast).toBeVisible();
    await expect(toast).toContainText(`Collection "${collectionName}" created successfully`);

    await toast.waitFor({ state: 'hidden', timeout: 6000 });

    const authToken = await authenticatedWithThreadsPage.evaluate(() => localStorage.getItem('auth_token'));

    const collectionsResponse = await request.get('/api/v1/collections/', {
      headers: {
        'Authorization': `Bearer ${authToken}`,
      },
    });

    const collections = await collectionsResponse.json();
    const collection = collections.collections.find((c: { name: string }) => c.name === collectionName);

    await authenticatedWithThreadsPage.evaluate((col) => {
      window.dispatchEvent(new CustomEvent('test-edit-collection', { detail: col }));
    }, collection);

    // Dialog should reappear for editing
    await expect(dialog).toBeVisible();

    const editNameInput = authenticatedWithThreadsPage.getByPlaceholder('Enter collection name');
    await editNameInput.fill(updatedName);

    const updateButton = dialog.getByRole('button', { name: 'Update' });
    await updateButton.click();

    const updateToast = authenticatedWithThreadsPage.getByTestId('toast-notification');
    await expect(updateToast).toBeVisible();
    await expect(updateToast).toContainText(`Collection "${updatedName}" updated successfully`);
  });
});
