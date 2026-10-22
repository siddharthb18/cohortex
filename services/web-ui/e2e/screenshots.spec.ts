import { test } from '@playwright/test';

// Run with SCREENSHOTS=1 to refresh the README images.
for (const scheme of ['light', 'dark'] as const) {
  test(`screenshots (${scheme})`, async ({ page }) => {
    await page.emulateMedia({ colorScheme: scheme });
    await page.goto('./');
    await page.getByLabel('Question').fill('Why did the fleet AFR rise in Q2 2026?');
    await page.getByRole('button', { name: 'Run investigation' }).click();
    await page.getByRole('region', { name: 'Report' }).waitFor({ timeout: 20_000 });
    await page.screenshot({ path: `docs/screenshots/investigate-${scheme}.png` });
    await page.goto('./#/fleet');
    await page.waitForLoadState('networkidle');
    await page.screenshot({ path: `docs/screenshots/fleet-${scheme}.png` });
  });
}
