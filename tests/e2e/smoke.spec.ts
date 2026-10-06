import { expect, test } from '@playwright/test';

test('shell loads and reaches the API', async ({ page }) => {
  await page.goto('/');
  await expect(page.getByText('For education. Not for clinical use.')).toBeVisible();
  await expect(page.getByTestId('health')).toContainText('ok', { timeout: 15_000 });
});
