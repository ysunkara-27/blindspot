import { expect, test } from '@playwright/test';

test('shell loads and reaches the API', async ({ page }) => {
  await page.goto('/');
  await expect(page.getByText('For education. Not for clinical use.')).toBeVisible();
  await expect(page.getByTestId('health')).toContainText(/Library: [\d,]+ chest films|synthetic practice shapes/, { timeout: 15_000 });
});
