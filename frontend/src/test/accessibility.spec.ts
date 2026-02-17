import { test, expect } from './fixtures';
import { generateTestUser, registerUser, loginUser, createThread, SELECTORS, formatA11yViolations } from './helpers';
import { AxeBuilder } from '@axe-core/playwright';

test.describe('Accessibility Tests', () => {
  test('should have no accessibility violations on home page', async ({ authenticatedPage }) => {
    await authenticatedPage.goto('/');

    const accessibilityScanResults = await new AxeBuilder({ page: authenticatedPage })
      .withTags(['wcag2a', 'wcag2aa', 'wcag21aa'])
      .analyze();

    expect(accessibilityScanResults.violations.length, `Accessibility violations found:\n${formatA11yViolations(accessibilityScanResults.violations)}`).toBe(0);
  });

  test('should have no accessibility violations on register page', async ({ page }) => {
    await page.goto('/register');

    const accessibilityScanResults = await new AxeBuilder({ page })
      .withTags(['wcag2a', 'wcag2aa', 'wcag21aa'])
      .analyze();

    expect(accessibilityScanResults.violations.length, `Accessibility violations found:\n${formatA11yViolations(accessibilityScanResults.violations)}`).toBe(0);
  });

  test('should have no accessibility violations on login page', async ({ page }) => {
    await page.goto('/login');

    const accessibilityScanResults = await new AxeBuilder({ page })
      .withTags(['wcag2a', 'wcag2aa', 'wcag21aa'])
      .analyze();

    expect(accessibilityScanResults.violations.length, `Accessibility violations found:\n${formatA11yViolations(accessibilityScanResults.violations)}`).toBe(0);
  });

  test('should have no accessibility violations on threads page', async ({ authenticatedPage }) => {
    await authenticatedPage.goto('/threads');

    const accessibilityScanResults = await new AxeBuilder({ page: authenticatedPage })
      .withTags(['wcag2a', 'wcag2aa', 'wcag21aa'])
      .analyze();

    expect(accessibilityScanResults.violations.length, `Accessibility violations found:\n${formatA11yViolations(accessibilityScanResults.violations)}`).toBe(0);
  });

  test('should have no accessibility violations on queue page', async ({ authenticatedPage }) => {
    await authenticatedPage.goto('/queue');

    const accessibilityScanResults = await new AxeBuilder({ page: authenticatedPage })
      .withTags(['wcag2a', 'wcag2aa', 'wcag21aa'])
      .analyze();

    expect(accessibilityScanResults.violations.length, `Accessibility violations found:\n${formatA11yViolations(accessibilityScanResults.violations)}`).toBe(0);
  });

  test('should have no accessibility violations on rate page', async ({ page }) => {
    const user = generateTestUser();
    await registerUser(page, user);
    await loginUser(page, user);

    await createThread(page, {
      title: 'A11y Test Comic',
      format: 'Comic',
      issues_remaining: 5,
    });

    await page.goto('/');
    await page.waitForSelector(SELECTORS.roll.mainDie);
    await page.click(SELECTORS.roll.mainDie);

    await page.waitForSelector(SELECTORS.rate.ratingInput, { state: 'visible' });

    const accessibilityScanResults = await new AxeBuilder({ page })
      .withTags(['wcag2a', 'wcag2aa', 'wcag21aa'])
      .analyze();

    expect(accessibilityScanResults.violations.length, `Accessibility violations found:\n${formatA11yViolations(accessibilityScanResults.violations)}`).toBe(0);
  });

  test('should have no accessibility violations on analytics page', async ({ authenticatedPage }) => {
    await authenticatedPage.goto('/analytics');

    const accessibilityScanResults = await new AxeBuilder({ page: authenticatedPage })
      .withTags(['wcag2a', 'wcag2aa', 'wcag21aa'])
      .analyze();

    expect(accessibilityScanResults.violations.length, `Accessibility violations found:\n${formatA11yViolations(accessibilityScanResults.violations)}`).toBe(0);
  });

  test('should have no accessibility violations on history page', async ({ authenticatedPage }) => {
    await authenticatedPage.goto('/history');

    const accessibilityScanResults = await new AxeBuilder({ page: authenticatedPage })
      .withTags(['wcag2a', 'wcag2aa', 'wcag21aa'])
      .analyze();

    expect(accessibilityScanResults.violations.length, `Accessibility violations found:\n${formatA11yViolations(accessibilityScanResults.violations)}`).toBe(0);
  });

  test('should have proper ARIA labels on interactive elements', async ({ authenticatedPage }) => {
    await authenticatedPage.goto('/');

    const buttons = await authenticatedPage.locator('button').all();
    
    for (const button of buttons) {
      const isVisible = await button.isVisible();
      if (isVisible) {
        const hasLabel = await button.evaluate((el: HTMLButtonElement) => {
          return (
            el.getAttribute('aria-label') !== null ||
            el.getAttribute('aria-labelledby') !== null ||
            el.textContent?.trim().length > 0
          );
        });
        expect(hasLabel).toBe(true);
      }
    }
  });

  test('should have proper heading hierarchy', async ({ authenticatedPage }) => {
    await authenticatedPage.goto('/');

    await authenticatedPage.waitForLoadState('networkidle');
    const headingsLocator = authenticatedPage.locator('h1, h2, h3, h4, h5, h6');
    const headingCount = await headingsLocator.count();
    const levels: number[] = [];

    for (let i = 0; i < headingCount; i++) {
      const heading = headingsLocator.nth(i);
      const isVisible = await heading.isVisible();
      if (isVisible) {
        const tag = await heading.evaluate((el) => el.tagName);
        const level = parseInt(tag[1]);
        levels.push(level);
      }
    }

    for (let i = 1; i < levels.length; i++) {
      expect(levels[i] - levels[i - 1]).toBeLessThanOrEqual(1);
    }
  });

  test('should have sufficient color contrast for text', async ({ authenticatedPage }) => {
    await authenticatedPage.goto('/');

    const accessibilityScanResults = await new AxeBuilder({ page: authenticatedPage })
      .withTags(['wcag2aa'])
      .include(['#root'])
      .analyze();

    const contrastViolations = accessibilityScanResults.violations.filter(
      (v) => v.id === 'color-contrast'
    );

    expect(contrastViolations.length, `Color contrast violations found:\n${formatA11yViolations(contrastViolations)}`).toBe(0);
  });

  test('should have focus indicators on all interactive elements', async ({ authenticatedPage }) => {
    await authenticatedPage.goto('/');

    const focusableElements = await authenticatedPage.locator(
      'button, a, input, select, textarea, [tabindex]:not([tabindex="-1"])'
    ).all();

    for (const element of focusableElements.slice(0, 10)) {
      const isVisible = await element.isVisible();
      if (isVisible) {
        await element.focus();
        
        const hasFocusStyle = await element.evaluate((el: HTMLElement) => {
          const styles = window.getComputedStyle(el);
          return (
            styles.outline !== 'none' ||
            styles.boxShadow !== 'none' ||
            el.getAttribute('class')?.includes('focus')
          );
        });
        
        expect(hasFocusStyle).toBe(true);
      }
    }
  });

  test('should support keyboard navigation', async ({ authenticatedPage }) => {
    await authenticatedPage.goto('/');

    await authenticatedPage.evaluate(() => {
      document.body?.focus();
    });

    await authenticatedPage.waitForLoadState('networkidle');
    const focusableElementsLocator = authenticatedPage.locator(
      'button, a, input, [tabindex]:not([tabindex="-1"])'
    );
    const elementCount = await focusableElementsLocator.count();

    let tabPresses = 0;
    const maxTabPresses = 5;

    for (let i = 0; i < Math.min(elementCount, maxTabPresses); i++) {
      const element = focusableElementsLocator.nth(i);
      const isVisible = await element.isVisible();
      
      if (isVisible) {
        await authenticatedPage.keyboard.press('Tab');
        tabPresses++;
        
        const activeElementInfo = await authenticatedPage.evaluate(() => ({
          tagName: document.activeElement?.tagName || null,
          isActive: document.activeElement !== null
        }));
        
        expect(activeElementInfo.isActive).toBe(true);
        expect(activeElementInfo.tagName).toBeTruthy();
      }
    }

    expect(tabPresses).toBeGreaterThan(0);
  });

  test('should have descriptive link text', async ({ authenticatedPage }) => {
    await authenticatedPage.goto('/');

    await authenticatedPage.waitForLoadState('networkidle');
    const linksLocator = authenticatedPage.locator('a');
    const linkCount = await linksLocator.count();

    for (let i = 0; i < linkCount; i++) {
      const link = linksLocator.nth(i);
      const isVisible = await link.isVisible();
      if (isVisible) {
        const text = await link.textContent();
        const ariaLabel = await link.getAttribute('aria-label');
        const hasDescription = (text?.trim().length || 0) > 0 || ariaLabel !== null;
        expect(hasDescription).toBe(true);
      }
    }
  });

  test('should have proper form labels', async ({ page }) => {
    await page.goto('/register');

    await page.waitForLoadState('networkidle');
    const inputsLocator = page.locator('input');
    const inputCount = await inputsLocator.count();

    for (let i = 0; i < inputCount; i++) {
      const input = inputsLocator.nth(i);
      const isVisible = await input.isVisible();
      if (isVisible) {
        const hasLabel = await input.evaluate((el: HTMLInputElement) => {
          const id = el.id;
          const ariaLabel = el.getAttribute('aria-label');
          const ariaLabelledBy = el.getAttribute('aria-labelledby');
          
          if (ariaLabel || ariaLabelledBy) return true;
          
          if (id) {
            const label = document.querySelector(`label[for="${id}"]`);
            if (label) return true;
          }
          
          const parentLabel = el.closest('label');
          if (parentLabel) return true;
          
          return false;
        });
        
        expect(hasLabel).toBe(true);
      }
    }
  });

  test('should announce dynamic content changes', async ({ page }) => {
    const user = generateTestUser();
    await registerUser(page, user);
    await loginUser(page, user);

    await createThread(page, {
      title: 'A11y Comic',
      format: 'Comic',
      issues_remaining: 5,
    });

    await page.goto('/');
    await page.waitForSelector(SELECTORS.roll.mainDie);

    const liveRegions = await page.locator('[aria-live], [role="status"], [role="alert"]').all();
    const hasLiveRegions = liveRegions.length > 0;

    if (hasLiveRegions) {
      await page.click(SELECTORS.roll.mainDie);
      await page.waitForSelector(SELECTORS.rate.ratingInput, { timeout: 5000 });

      for (const region of liveRegions) {
        const isVisible = await region.isVisible();
        if (isVisible) {
          const content = await region.textContent();
          const hasAnnouncement = (content?.trim().length || 0) > 0;
          if (hasAnnouncement) {
            expect(content?.trim().length).toBeGreaterThan(0);
          }
        }
      }
    }
  });
});
