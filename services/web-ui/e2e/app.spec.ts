import AxeBuilder from '@axe-core/playwright';
import { expect, test } from '@playwright/test';
import { EV_AFR, QUESTION, mockApi } from './mockApi';

test('investigation streams steps, renders the report and opens evidence (FR-UI-5/6)', async ({
  page,
}) => {
  const log = await mockApi(page);
  await page.goto('/#/');
  await page.getByLabel('Question').fill(QUESTION);
  await page.getByRole('button', { name: 'Run investigation' }).click();

  await expect(page.getByRole('heading', { name: 'Steps' })).toBeVisible();
  await expect(page.getByRole('region', { name: 'Report' })).toBeVisible();
  expect(log.posts).toHaveLength(1);

  await page.locator(`button.num-link[data-evidence-id="${EV_AFR}"]`).first().click();
  const drawer = page.getByRole('dialog');
  await expect(drawer).toBeVisible();
  await expect(drawer).toContainText('fleet.cohort_afr');
  await expect(drawer).toContainText('1.3712');
});

test('fleet table sorts by AFR (FR-UI-1)', async ({ page }) => {
  await mockApi(page);
  await page.goto('/#/fleet');
  const firstModel = page.locator('table tbody tr').first().locator('td, th').first();
  await page.getByRole('button', { name: /^AFR/ }).click();
  const a = await firstModel.textContent();
  await page.getByRole('button', { name: /^AFR/ }).click();
  const b = await firstModel.textContent();
  expect(new Set([a?.trim(), b?.trim()])).toEqual(new Set(['MODEL-A', 'MODEL-D']));
});

for (const path of ['/#/', '/#/fleet']) {
  test(`no serious axe violations on ${path} (FR-UI-8)`, async ({ page }) => {
    await mockApi(page);
    await page.goto(path);
    await page.waitForLoadState('networkidle');
    const results = await new AxeBuilder({ page: page as never }).analyze();
    const serious = results.violations.filter((v) =>
      ['serious', 'critical'].includes(v.impact ?? ''),
    );
    expect(serious.map((v) => v.id)).toEqual([]);
  });
}
