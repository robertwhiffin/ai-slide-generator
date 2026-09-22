import { expect, Page, Route, test } from '@playwright/test';
import type { AgentKey, DraftSaveRequest } from '../../src/api/agentDefinitions';
import {
  syntheticAgentDefinitionWorkbench,
  syntheticDraftSaveConflict,
  syntheticDraftSaveSuccess,
} from '../fixtures/mocks';

const WORKBENCH_ENDPOINT = '**/api/admin/agent-definitions/workbench';
const SAVE_ENDPOINT = '**/api/admin/agent-definitions/draft/*';
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

async function installWorkbenchMock(page: Page, status = 200, body: unknown = syntheticAgentDefinitionWorkbench) {
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

interface CapturedSave {
  agentKey: AgentKey;
  body: DraftSaveRequest;
}

async function installSaveMock(
  page: Page,
  respond: (route: Route, save: CapturedSave, call: number) => Promise<void> | void,
) {
  const saves: CapturedSave[] = [];
  await page.route(SAVE_ENDPOINT, async (route) => {
    const save = {
      agentKey: route.request().url().split('/').at(-1) as AgentKey,
      body: route.request().postDataJSON() as DraftSaveRequest,
    };
    saves.push(save);
    await respond(route, save, saves.length - 1);
  });
  return saves;
}

async function fulfillJson(route: Route, status: number, body: unknown) {
  await route.fulfill({ status, contentType: 'application/json', body: JSON.stringify(body) });
}

async function editArchitectFiveFields(page: Page) {
  await page.getByRole('textbox', { name: 'Prompt text' }).fill('Architect A2');
  await page.getByRole('tab', { name: 'Model' }).click();
  await page.getByRole('textbox', { name: 'Endpoint' }).fill('endpoint-a2');
  await page.getByRole('spinbutton', { name: 'Temperature' }).fill('0.4');
  await page.getByRole('spinbutton', { name: 'Maximum tokens' }).fill('8192');
  await page.getByRole('spinbutton', { name: 'Top-p' }).fill('0.8');
}

async function expectArchitectFiveFields(page: Page) {
  await page.getByRole('tab', { name: 'Prompt' }).click();
  await expect(page.getByRole('textbox', { name: 'Prompt text' })).toHaveValue('Architect A2');
  await page.getByRole('tab', { name: 'Model' }).click();
  await expect(page.getByRole('textbox', { name: 'Endpoint' })).toHaveValue('endpoint-a2');
  await expect(page.getByRole('spinbutton', { name: 'Temperature' })).toHaveValue('0.4');
  await expect(page.getByRole('spinbutton', { name: 'Maximum tokens' })).toHaveValue('8192');
  await expect(page.getByRole('spinbutton', { name: 'Top-p' })).toHaveValue('0.8');
}

async function expectBuilderFormUnchanged(page: Page) {
  await page.getByRole('tab', { name: 'Prompt' }).click();
  await expect(page.getByRole('textbox', { name: 'Prompt text' })).toHaveValue('Builder retained B2');
  await page.getByRole('tab', { name: 'Model' }).click();
  await expect(page.getByRole('textbox', { name: 'Endpoint' })).toHaveValue('databricks-claude-opus-4-6');
  await expect(page.getByRole('spinbutton', { name: 'Temperature' })).toHaveValue('0.7');
  await expect(page.getByRole('spinbutton', { name: 'Maximum tokens' })).toHaveValue('60000');
  await expect(page.getByRole('spinbutton', { name: 'Top-p' })).toHaveValue('0.95');
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
  await expect.poll(() => navigation.getByRole('button').evaluateAll((buttons) =>
    buttons.map((button) => button.getAttribute('aria-label')))).toEqual(NODE_ORDER);
  await expect(page.getByRole('tabpanel', { name: 'Prompt' })).toContainText(
    'Synthetic Architect prompt — exact fixture value.',
  );

  await page.getByRole('tab', { name: 'Model' }).click();
  await expect(page.getByRole('textbox', { name: 'Endpoint' })).toHaveValue('databricks-claude-opus-4-6');
  await expect(page.getByRole('spinbutton', { name: 'Temperature' })).toHaveValue('0.7');
  await expect(page.getByRole('spinbutton', { name: 'Maximum tokens' })).toHaveValue('60000');
  await expect(page.getByRole('spinbutton', { name: 'Top-p' })).toHaveValue('0.95');

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

test('explicit Save is the only write and sends the exact five-field candidate with lock zero', async ({ page }) => {
  await installExactIdentityMock(page);
  await installWorkbenchMock(page);
  const saves = await installSaveMock(page, (route, save) => fulfillJson(
    route,
    200,
    syntheticDraftSaveSuccess(save.agentKey, save.body, 1),
  ));
  await openWorkbench(page);
  await expect(page.getByRole('heading', { name: 'Graph Version 1' })).toBeVisible();

  await editArchitectFiveFields(page);
  await page.getByRole('tab', { name: 'Output Schema' }).click();
  await page.getByRole('tab', { name: 'Assembly' }).click();
  await page.getByRole('navigation', { name: 'Graph nodes' }).getByRole('button', { name: 'Builder' }).click();
  expect(saves).toHaveLength(0);
  await page.getByRole('navigation', { name: 'Graph nodes' }).getByRole('button', { name: 'Architect' }).click();
  await page.getByRole('button', { name: 'Save Draft' }).click();

  await expect.poll(() => saves.length).toBe(1);
  expect(saves[0]).toEqual({
    agentKey: 'architect',
    body: {
      lock_version: 0,
      candidate: {
        prompt_text: 'Architect A2',
        model: { endpoint_name: 'endpoint-a2', temperature: 0.4, max_tokens: 8192, top_p: 0.8 },
      },
    },
  });
  await expect(page.getByText('Lock version').locator('..')).toContainText('1');
  await expect(page.getByRole('navigation', { name: 'Graph nodes' }).getByRole('button', { name: 'Architect' }))
    .toContainText('Needs test');
  await expect(page.getByRole('heading', { name: 'Graph Version 1' })).toBeVisible();
});

test('cross-agent conflict reconciles Builder and Keep local retries only on explicit Save', async ({ page }) => {
  await installExactIdentityMock(page);
  const workbenchRequestCount = await installWorkbenchMock(page);
  const saves = await installSaveMock(page, (route, save, call) => call === 0
    ? fulfillJson(route, 409, syntheticDraftSaveConflict(save.body, {
      architect: 'Architect server A1',
      builder: 'Builder server B1',
    }))
    : fulfillJson(route, 200, syntheticDraftSaveSuccess(save.agentKey, save.body, 2)));
  await openWorkbench(page);
  const navigation = page.getByRole('navigation', { name: 'Graph nodes' });
  await page.getByRole('textbox', { name: 'Prompt text' }).fill('Architect local A2');
  await page.getByRole('button', { name: 'Save Draft' }).click();

  const conflict = page.getByRole('region', { name: 'Draft changed on the server' });
  await expect(conflict.getByRole('group', { name: 'Server values' })).toContainText('Architect server A1');
  await expect(conflict.getByRole('group', { name: 'Submitted values' })).toContainText('Architect local A2');
  await expect.poll(workbenchRequestCount).toBe(1);
  await navigation.getByRole('button', { name: 'Builder' }).click();
  await expect(page.getByRole('textbox', { name: 'Prompt text' })).toHaveValue('Builder server B1');
  await expect(navigation.getByRole('button', { name: 'Builder' })).toContainText('Needs test');
  await navigation.getByRole('button', { name: 'Architect' }).click();
  await conflict.getByRole('button', { name: 'Keep local' }).click();
  expect(saves).toHaveLength(1);
  await expect.poll(workbenchRequestCount).toBe(1);
  await expect(page.getByRole('textbox', { name: 'Prompt text' })).toHaveValue('Architect local A2');
  await page.getByRole('button', { name: 'Save Draft' }).click();
  await expect.poll(() => saves.length).toBe(2);
  expect(saves[1].body.lock_version).toBe(1);
  await expect.poll(workbenchRequestCount).toBe(1);
});

test('Reload server is write-free and retains the latest local values for recovery', async ({ page }) => {
  await installExactIdentityMock(page);
  const workbenchRequestCount = await installWorkbenchMock(page);
  let heldRoute: Route | null = null;
  const saves = await installSaveMock(page, (route) => { heldRoute = route; });
  await openWorkbench(page);
  const prompt = page.getByRole('textbox', { name: 'Prompt text' });
  await prompt.fill('Architect A2');
  await page.getByRole('button', { name: 'Save Draft' }).click();
  await expect.poll(() => heldRoute !== null).toBe(true);
  await prompt.fill('Architect A3');
  await fulfillJson(
    heldRoute!,
    409,
    syntheticDraftSaveConflict(saves[0].body, { architect: 'Architect server A1' }),
  );

  const conflict = page.getByRole('region', { name: 'Draft changed on the server' });
  await expect(conflict.getByRole('group', { name: 'Current local values' })).toContainText('Architect A3');
  await expect.poll(workbenchRequestCount).toBe(1);
  await conflict.getByRole('button', { name: 'Reload server' }).click();
  await expect(prompt).toHaveValue('Architect server A1');
  await expect.poll(workbenchRequestCount).toBe(1);
  const recovery = page.getByRole('region', { name: 'Values retained for recovery' });
  await expect(recovery).toContainText('Architect A3');
  expect(saves).toHaveLength(1);
  await recovery.getByRole('button', { name: 'Restore retained values' }).click();
  await expect(prompt).toHaveValue('Architect A3');
  expect(saves).toHaveLength(1);
  await expect.poll(workbenchRequestCount).toBe(1);
});

test('422 field validation is rendered beside the labelled input', async ({ page }) => {
  await installExactIdentityMock(page);
  await installWorkbenchMock(page);
  const saves = await installSaveMock(page, (route) => fulfillJson(route, 422, {
    code: 'invalid_draft',
    errors: [{ field: 'candidate.prompt_text', code: 'rejected', message: 'Prompt blocked by policy.' }],
  }));
  await openWorkbench(page);
  await page.getByRole('button', { name: 'Save Draft' }).click();
  await expect(page.getByRole('textbox', { name: 'Prompt text' })).toHaveAttribute(
    'aria-describedby',
    'architect-prompt-error',
  );
  await expect(page.locator('#architect-prompt-error')).toHaveText('Prompt blocked by policy.');
  expect(saves).toHaveLength(1);
});

test('a pending Architect save globally blocks Builder while preserving A3', async ({ page }) => {
  await installExactIdentityMock(page);
  await installWorkbenchMock(page);
  let heldRoute: Route | null = null;
  const saves = await installSaveMock(page, (route, save, call) => {
    if (call === 0) heldRoute = route;
    else return fulfillJson(route, 200, syntheticDraftSaveSuccess(save.agentKey, save.body, 2));
  });
  await openWorkbench(page);
  const navigation = page.getByRole('navigation', { name: 'Graph nodes' });
  const prompt = page.getByRole('textbox', { name: 'Prompt text' });
  await prompt.fill('Architect A2');
  await page.getByRole('button', { name: 'Save Draft' }).click();
  await expect.poll(() => heldRoute !== null).toBe(true);
  await prompt.fill('Architect A3');
  await navigation.getByRole('button', { name: 'Builder' }).click();
  await expect(page.getByRole('button', { name: 'Save Draft' })).toBeDisabled();
  expect(saves).toHaveLength(1);
  await fulfillJson(heldRoute!, 200, syntheticDraftSaveSuccess('architect', saves[0].body, 1));
  await expect(page.getByRole('button', { name: 'Save Draft' })).toBeEnabled();
  await page.getByRole('button', { name: 'Save Draft' }).click();
  await expect.poll(() => saves.length).toBe(2);
  expect(saves[1].body.lock_version).toBe(1);
  await navigation.getByRole('button', { name: 'Architect' }).click();
  await expect(prompt).toHaveValue('Architect A3');
  await expect(navigation.getByRole('button', { name: 'Architect' })).toContainText('Unsaved');
});

const invalidSaveCases: Array<{
  name: string;
  expectedAlert: string;
  respond(route: Route, request: DraftSaveRequest): Promise<void>;
}> = [
  {
    name: 'malformed 200',
    expectedAlert: 'Unable to save draft because the server response was invalid.',
    respond: (route) => fulfillJson(route, 200, { changed: true }),
  },
  {
    name: 'six-role 409',
    expectedAlert: 'Unable to save draft because the server response was invalid.',
    respond: (route, request) => {
      const conflict = syntheticDraftSaveConflict(request);
      const definitions = { ...conflict.server.definitions } as Record<string, unknown>;
      delete definitions.builder;
      return fulfillJson(route, 409, { ...conflict, server: { ...conflict.server, definitions } });
    },
  },
  {
    name: 'eight-role 409',
    expectedAlert: 'Unable to save draft because the server response was invalid.',
    respond: (route, request) => {
      const conflict = syntheticDraftSaveConflict(request);
      return fulfillJson(route, 409, {
        ...conflict,
        server: {
          ...conflict.server,
          definitions: { ...conflict.server.definitions, foreman: conflict.server.definitions.architect },
        },
      });
    },
  },
  {
    name: 'mistyped 422',
    expectedAlert: 'Unable to save draft because the server response was invalid.',
    respond: (route) => fulfillJson(route, 422, {
      code: 'invalid_draft',
      errors: [{ field: 'candidate.prompt_text', code: 'rejected', message: 42 }],
    }),
  },
  {
    name: 'non-object JSON',
    expectedAlert: 'Unable to save draft because the server response was invalid.',
    respond: (route) => fulfillJson(route, 200, ['not', 'an', 'object']),
  },
  {
    name: 'network error',
    expectedAlert: 'Unable to save draft. Check your connection and try again.',
    respond: async (route) => { await route.abort('failed'); },
  },
  {
    name: 'non-JSON 500',
    expectedAlert: 'Unable to save draft (500 Internal Server Error).',
    respond: async (route) => {
      await route.fulfill({ status: 500, contentType: 'text/plain', body: 'not JSON' });
    },
  },
];

for (const invalidCase of invalidSaveCases) {
  test(`${invalidCase.name} is contained, write-stable, lossless, and explicitly retryable`, async ({ page }) => {
    await installExactIdentityMock(page);
    await installWorkbenchMock(page);
    const saves = await installSaveMock(page, (route, save, call) => call === 0
      ? invalidCase.respond(route, save.body)
      : fulfillJson(route, 200, syntheticDraftSaveSuccess(save.agentKey, save.body, 1)));
    await openWorkbench(page);
    const navigation = page.getByRole('navigation', { name: 'Graph nodes' });
    await editArchitectFiveFields(page);
    await navigation.getByRole('button', { name: 'Builder' }).click();
    await page.getByRole('textbox', { name: 'Prompt text' }).fill('Builder retained B2');
    await navigation.getByRole('button', { name: 'Architect' }).click();
    await page.getByRole('button', { name: 'Save Draft' }).click();

    await expect(page.getByRole('alert')).toContainText(invalidCase.expectedAlert);
    expect(saves).toHaveLength(1);
    await expectArchitectFiveFields(page);
    await navigation.getByRole('button', { name: 'Builder' }).click();
    await expect(page.getByRole('alert')).toHaveCount(0);
    await expectBuilderFormUnchanged(page);
    await navigation.getByRole('button', { name: 'Architect' }).click();
    await expect(page.getByRole('alert')).toContainText(invalidCase.expectedAlert);
    await page.getByRole('button', { name: 'Save Draft' }).click();
    await expect.poll(() => saves.length).toBe(2);
    await expect(page.getByRole('alert')).toHaveCount(0);
    await expectArchitectFiveFields(page);
    await navigation.getByRole('button', { name: 'Builder' }).click();
    await expect(page.getByRole('alert')).toHaveCount(0);
    await expectBuilderFormUnchanged(page);
  });
}

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
