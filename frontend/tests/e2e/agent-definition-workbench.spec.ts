import { expect, Page, test } from '@playwright/test';
import { mockAgentDefinitionWorkbench } from '../fixtures/mocks';

const WORKBENCH_ENDPOINT = '**/api/admin/agent-definitions/workbench';
const NODE_ORDER = [
  'Architect',
  'Data Analyst',
  'Builder',
  'Build Reviewer',
  'Foreman',
  'Fixer',
  'Fix Reviewer',
  'Deck Reviewer',
];

async function installExactIdentityMock(page: Page) {
  await page.route('**/api/setup/status', (route) => route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify({ configured: true }),
  }));
  await page.route('**/api/user/current', (route) => route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify({
      username: 'admin@test.com',
      display_name: 'Admin Test',
      is_admin: true,
    }),
  }));
}

async function installWorkbenchMock(page: Page, status = 200, body: unknown = mockAgentDefinitionWorkbench) {
  let requestCount = 0;
  await page.route(WORKBENCH_ENDPOINT, (route) => {
    requestCount += 1;
    return route.fulfill({
      status,
      contentType: 'application/json',
      body: JSON.stringify(body),
    });
  });
  return () => requestCount;
}

async function openWorkbench(page: Page) {
  await page.goto('/admin');
  await page.getByRole('tab', { name: 'Agent Definitions' }).click();
}

test('loads lazily once, preserves exact topology, and exposes exact definition tabs', async ({ page }) => {
  await installExactIdentityMock(page);
  const requestCount = await installWorkbenchMock(page);

  await page.goto('/admin');
  await expect(page.getByRole('heading', { level: 1, name: 'Admin' })).toBeVisible();
  expect(requestCount()).toBe(0);

  await page.getByRole('tab', { name: 'Agent Definitions' }).click();
  await expect(page.getByRole('heading', { name: 'Graph Version 1' })).toBeVisible();
  await expect.poll(requestCount).toBe(1);

  const navigation = page.getByRole('navigation', { name: 'Graph nodes' });
  await expect(navigation.getByRole('button')).toHaveText(NODE_ORDER);
  await expect(page.getByRole('tabpanel', { name: 'Prompt' })).toContainText(
    'Synthetic Architect prompt — exact fixture value.',
  );

  await page.getByRole('tab', { name: 'Model' }).click();
  await expect(page.getByRole('tabpanel', { name: 'Model' })).toContainText('databricks-claude-opus-4-6');
  await expect(page.getByRole('tabpanel', { name: 'Model' })).toContainText('0.7');
  await expect(page.getByRole('tabpanel', { name: 'Model' })).toContainText('60000');
  await expect(page.getByRole('tabpanel', { name: 'Model' })).toContainText('0.95');

  await page.getByRole('tab', { name: 'Output Schema' }).click();
  await expect(page.getByRole('tabpanel', { name: 'Output Schema' })).toContainText('Synthetic title override');
  await expect(page.getByRole('tabpanel', { name: 'Output Schema' })).toContainText('speaker_notes');

  await page.getByRole('tab', { name: 'Assembly' }).click();
  await expect(page.getByRole('tabpanel', { name: 'Assembly' })).toContainText('slide_frame_constraints');
  await expect(page.getByRole('tabpanel', { name: 'Assembly' })).toContainText('langchain.with_structured_output');

  await navigation.getByRole('button', { name: 'Foreman' }).click();
  await expect(page.getByTestId('definition-pane')).toContainText(
    'Foreman is deterministic scheduling and routing code; it has no Agent Definition.',
  );
  await expect(page.getByTestId('definition-pane').getByRole('tablist')).toHaveCount(0);
});

for (const [status, detail] of [
  [403, 'Administrator access required'],
  [500, 'Graph configuration is incomplete'],
] as const) {
  test(`${status} stays inside the panel while admin chrome and another tab remain usable`, async ({ page }) => {
    await installExactIdentityMock(page);
    const requestCount = await installWorkbenchMock(page, status, { detail });

    await openWorkbench(page);

    const panel = page.getByRole('tabpanel', { name: 'Agent Definitions' });
    await expect(panel.getByRole('alert')).toContainText(`${status}`);
    await expect(panel.getByRole('alert')).toContainText(detail);
    await expect(page.getByRole('heading', { level: 1, name: 'Admin' })).toBeVisible();
    await expect.poll(requestCount).toBe(1);

    await page.getByRole('tab', { name: 'Usage' }).click();
    await expect(page.getByRole('tabpanel', { name: 'Usage' })).toBeVisible();
    await expect(page.getByRole('heading', { level: 1, name: 'Admin' })).toBeVisible();
  });
}

test('small viewports deliberately overflow the fixed three-pane canvas', async ({ page }) => {
  await page.setViewportSize({ width: 640, height: 800 });
  await installExactIdentityMock(page);
  await installWorkbenchMock(page);
  await openWorkbench(page);
  await expect(page.getByRole('heading', { name: 'Graph Version 1' })).toBeVisible();

  const dimensions = await page.getByTestId('workbench-overflow').evaluate((element) => ({
    clientWidth: element.clientWidth,
    scrollWidth: element.scrollWidth,
  }));
  expect(dimensions.scrollWidth).toBeGreaterThan(dimensions.clientWidth);
  await expect(page.getByTestId('workbench-grid')).toHaveCSS('grid-template-columns', /.+ .+ .+/);
});
