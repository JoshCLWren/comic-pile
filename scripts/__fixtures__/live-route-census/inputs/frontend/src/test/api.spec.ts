test('legacy helper', async ({page}) => {
  await page.request.post('/api/v1/threads/7/restore')
})
