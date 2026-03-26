import { test, expect } from './fixtures';
import { AxeBuilder } from '@axe-core/playwright';
import { formatA11yViolations } from './helpers';

const SELECTORS = {
  glossary: {
    heading: 'h1:has-text("Glossary")',
    glossaryList: '[data-testid="glossary-list"]',
    glossaryTerm: '[data-testid="glossary-term"]',
    glossaryDefinition: '[data-testid="glossary-definition"]',
  },
};

test.describe('Glossary Page Tests', () => {
  test('should navigate to glossary page and load correctly', async ({ authenticatedPage }) => {
    await authenticatedPage.goto('/glossary');
    await expect(authenticatedPage.locator(SELECTORS.glossary.heading)).toBeVisible();
  });

  test('should have no accessibility violations on glossary page', async ({ authenticatedPage }) => {
    await authenticatedPage.goto('/glossary');

    const accessibilityScanResults = await new AxeBuilder({ page: authenticatedPage })
      .withTags(['wcag2a', 'wcag2aa', 'wcag21aa'])
      .analyze();

    expect(accessibilityScanResults.violations.length, `Accessibility violations found:\n${formatA11yViolations(accessibilityScanResults.violations)}`).toBe(0);
  });

  test('should render glossary page with expected DOM elements', async ({ authenticatedPage }) => {
    await authenticatedPage.goto('/glossary');

    await expect(authenticatedPage.locator(SELECTORS.glossary.heading)).toBeVisible();
    await expect(authenticatedPage.locator(SELECTORS.glossary.glossaryList)).toBeVisible();
    
    const terms = await authenticatedPage.locator(SELECTORS.glossary.glossaryTerm).count();
    const definitions = await authenticatedPage.locator(SELECTORS.glossary.glossaryDefinition).count();
    
    expect(terms).toBeGreaterThan(0);
    expect(definitions).toBeGreaterThan(0);
    expect(terms).toEqual(definitions);
  });

  test('should navigate to glossary page from help page link', async ({ authenticatedPage }) => {
    await authenticatedPage.goto('/help');
    
    // Click on the glossary link. Update selector if the actual one differs.
    await authenticatedPage.click('a[href="/glossary"]');
    await expect(authenticatedPage.locator(SELECTORS.glossary.heading)).toBeVisible();
  });
});