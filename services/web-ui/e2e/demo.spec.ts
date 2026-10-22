import { expect, test } from '@playwright/test';

test('static demo mode replays a recorded investigation without a backend', async ({ page }) => {
  await page.goto('./');
  await expect(page.getByRole('note')).toContainText('Demo');
  await page.getByLabel('Question').fill('Why did the fleet AFR rise?');
  await page.getByRole('button', { name: 'Run investigation' }).click();
  await expect(page.getByRole('region', { name: 'Report' })).toBeVisible({ timeout: 20_000 });
});
