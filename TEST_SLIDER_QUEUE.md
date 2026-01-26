# Queue Slider Testing Guide

## Test User Account

- **Username**: `testuser123`
- **Password**: `ComicPileTest123!`
- **Email**: `testuser123@example.com`
- **User ID**: 250
- **Thread count**: 20 threads (positions 1–20)

## Access Details

- Use these credentials to log into the application for testing the queue position slider.
- The account has a mix of threads to enable thorough testing of repositioning via the slider.

## Testing Steps with Playwright MCP

1. Launch the application in your test environment.
2. Log in with the credentials above.
3. Navigate to the queue page.
4. For each thread:
   - Open the position slider.
   - Move the slider to different positions.
   - Verify UI updates and backend persistence.
5. Verify that queue positions update correctly and no duplicate positions exist.
6. Test edge cases (first position, last position, middle positions).

## Notes

- This account is specifically for testing slider functionality.
- Do not use these credentials in production environments.
- After testing is complete, consider rotating or disabling this test account.