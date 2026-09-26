import { expect, Page, Route, test } from '@playwright/test';
import type {
  AgentDefinitionWorkbenchResponse,
  AgentKey,
  DraftDefinition,
  DraftSaveRequest,
} from '../../src/api/agentDefinitions';
import {
  ALREADY_CURRENT_REJECTION,
  DIAGNOSTIC_NOTES_DESCRIPTOR,
  DIRTY_LEGACY_PROMPT,
  EMPTY_V2_ASSEMBLY_RULES,
  LEGACY_COMPOSITE_ROLES,
  MANUAL_RESOLUTION_REJECTION,
  MODEL_ENDPOINT_DISCOVERY_UNAVAILABLE,
  PUBLISHED_V1_PROMPT_SOURCE,
  SCHEMA_ALREADY_CURRENT_REJECTION,
  SEED_CANDIDATE_HASH,
  SEED_MODEL_ENDPOINT_NAME,
  STRUCTURED_OUTPUT_PROBE_FAILURES,
  V2_AUTHORED_PROMPT,
  syntheticAgentDefinitionWorkbench,
  syntheticAgentTestCase,
  syntheticAgentTestCaseList,
  syntheticDraftDefinitions,
  syntheticDraftSaveConflict,
  syntheticDraftSaveSuccess,
  syntheticLegacyPromptSource,
  syntheticModelEndpointDiscovery,
  syntheticNewerModelEndpoint,
  syntheticNullCandidateConflict,
  syntheticProbeFailure,
  syntheticProbeSuccess,
  syntheticSchemaUpgradeSuccess,
  syntheticSchemaV2DraftDefinition,
  syntheticSystemModelEndpoints,
  syntheticTestRunEvidence,
  syntheticTestRunUnavailable,
  syntheticUpgradeSuccess,
  syntheticV2DraftDefinition,
  v2ProtectedStageView,
} from '../fixtures/mocks';
import { ALLOWED_ACTION_NAMES, forbidsActionName } from '../fixtures/forbiddenActionNames';

const WORKBENCH_ENDPOINT = '**/api/admin/agent-definitions/workbench';
const MODEL_ENDPOINTS_ENDPOINT = '**/api/admin/agent-definitions/model-endpoints';
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

/**
 * #267 tripwire (C38; #266's deferred m2): every Agent Test Case or test run request a
 * test did not route itself lands here, is aborted, and fails the test in `afterEach`,
 * so no unrouted run can reach a real server or be answered as another route.
 */
const unroutedAgentTestRequests: string[] = [];

function isAgentTestPath(url: URL) {
  return url.pathname.includes('/api/admin/agent-definitions/')
    && (url.pathname.includes('/test-case') || url.pathname.includes('/test-run'));
}

test.afterEach(() => {
  const unrouted = unroutedAgentTestRequests.splice(0);
  expect(unrouted).toEqual([]);
});

async function installWorkbenchMock(page: Page, status = 200, body: unknown = syntheticAgentDefinitionWorkbench) {
  let requestCount = 0;
  await page.route(isAgentTestPath, (route) => {
    unroutedAgentTestRequests.push(`${route.request().method()} ${route.request().url()}`);
    return route.abort();
  });
  // The one shared default discovery answer (#266 correction 17): the first Model-tab
  // opening reads the catalog, and there is no catch-all route to absorb it. A test
  // that needs another catalog answer registers its own route later, which wins.
  await page.route(MODEL_ENDPOINTS_ENDPOINT, (route) => route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify(syntheticModelEndpointDiscovery()),
  }));
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
  await page.getByRole('textbox', { name: 'Custom endpoint name' }).fill('endpoint-a2');
  await page.getByRole('spinbutton', { name: 'Temperature' }).fill('0.4');
  await page.getByRole('spinbutton', { name: 'Maximum tokens' }).fill('8192');
  await page.getByRole('spinbutton', { name: 'Top-p' }).fill('0.8');
}

async function expectArchitectFiveFields(page: Page) {
  await page.getByRole('tab', { name: 'Prompt' }).click();
  await expect(page.getByRole('textbox', { name: 'Prompt text' })).toHaveValue('Architect A2');
  await page.getByRole('tab', { name: 'Model' }).click();
  await expect(page.getByRole('textbox', { name: 'Custom endpoint name' })).toHaveValue('endpoint-a2');
  await expect(page.getByRole('spinbutton', { name: 'Temperature' })).toHaveValue('0.4');
  await expect(page.getByRole('spinbutton', { name: 'Maximum tokens' })).toHaveValue('8192');
  await expect(page.getByRole('spinbutton', { name: 'Top-p' })).toHaveValue('0.8');
}

async function expectBuilderFormUnchanged(page: Page) {
  await page.getByRole('tab', { name: 'Prompt' }).click();
  await expect(page.getByRole('textbox', { name: 'Prompt text' })).toHaveValue('Builder retained B2');
  await page.getByRole('tab', { name: 'Model' }).click();
  await expect(page.getByRole('textbox', { name: 'Custom endpoint name' })).toHaveValue('databricks-claude-opus-4-6');
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
  await expect(page.getByRole('textbox', { name: 'Custom endpoint name' })).toHaveValue('databricks-claude-opus-4-6');
  await expect(page.getByRole('spinbutton', { name: 'Temperature' })).toHaveValue('0.7');
  await expect(page.getByRole('spinbutton', { name: 'Maximum tokens' })).toHaveValue('60000');
  await expect(page.getByRole('spinbutton', { name: 'Top-p' })).toHaveValue('0.95');

  await page.getByRole('tab', { name: 'Output Schema' }).click();
  // The OutputSchemaEditor shows field override descriptions (not raw JSON).
  // Architect fixture has a field override for `title` with this description.
  await expect(page.getByRole('tabpanel', { name: 'Output Schema' })).toContainText('Synthetic title override');
  // v1 contract: Schema Upgrade button shown; picker hidden.
  await expect(page.getByRole('tabpanel', { name: 'Output Schema' })
    .getByRole('button', { name: 'Schema Upgrade' })).toBeVisible();

  await page.getByRole('tab', { name: 'Assembly' }).click();
  // Task 5 replaced the read-only assembly JSON with server-derived locked rows, so the
  // stage is asserted by its accessible group name rather than by its raw stage_id.
  await expect(page.getByRole('tabpanel', { name: 'Assembly' })
    .getByRole('group', { name: 'Protected stage: Slide frame constraints' })).toBeVisible();
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
  await expect(page.getByText('Lock version').locator('..')).toContainText('Lock version1');
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

// ===========================================================================
// #265 declarative prompt assembly in the browser.
//
// Everything below drives the real client against mocked GET / PUT / upgrade
// POST / legacy-source POST routes. The protected `display_text` values in the
// fixtures are synthetic on purpose — that is what proves the client renders the
// bytes the server sent instead of reconstructing protected text. The real bytes
// are joined to these fixtures by the PostgreSQL route suite, which is the only
// place the Python and TypeScript literals meet.
// ===========================================================================

const UPGRADE_ENDPOINT = '**/api/admin/agent-definitions/draft/*/protected-assembly-upgrade';
const SCHEMA_UPGRADE_ENDPOINT = '**/api/admin/agent-definitions/draft/*/schema-contract-upgrade';
const SOURCE_ENDPOINT = '**/api/admin/agent-definitions/draft/*/legacy-prompt-source';

/**
 * The affected-role matrix, fixed by this file rather than read from the shared
 * fixture. Narrowing `LEGACY_COMPOSITE_ROLES` in `mocks.ts` used to shrink every loop
 * below and still report all-green; now the cardinality is owned here and the
 * agreement test asserts the fixture, the production constant and the server's
 * canonical transition list all still say the same thing.
 */
const AFFECTED_ROLES = ['data_analyst', 'build_reviewer'] as const;

interface CapturedPost {
  agentKey: AgentKey;
  body: Record<string, unknown>;
}

async function installPostMock(
  page: Page,
  endpoint: string,
  respond: (route: Route, post: CapturedPost, call: number) => Promise<void> | void,
) {
  const posts: CapturedPost[] = [];
  await page.route(endpoint, async (route) => {
    const segments = route.request().url().split('/');
    const post: CapturedPost = {
      agentKey: segments.at(-2) as AgentKey,
      body: route.request().postDataJSON() as Record<string, unknown>,
    };
    posts.push(post);
    await respond(route, post, posts.length - 1);
  });
  return posts;
}

function cloneWorkbench(): AgentDefinitionWorkbenchResponse {
  return structuredClone(syntheticAgentDefinitionWorkbench) as AgentDefinitionWorkbenchResponse;
}

/** A workbench whose named roles carry the supplied persisted draft definition. */
function workbenchWith(drafts: Partial<Record<AgentKey, DraftDefinition>>) {
  const body = cloneWorkbench();
  for (const node of body.nodes) {
    if (node.execution_kind !== 'model') continue;
    const replacement = drafts[node.agent_key];
    if (replacement !== undefined) node.draft = structuredClone(replacement);
  }
  return body;
}

function v1DraftWithPrompt(agentKey: AgentKey, promptText: string): DraftDefinition {
  return { ...structuredClone(syntheticDraftDefinitions[agentKey]), prompt_text: promptText };
}

/** A save 200 that echoes a v2 candidate, including its custom blocks. */
function v2SaveSuccess(agentKey: AgentKey, request: DraftSaveRequest, lockVersion: number) {
  return {
    ...syntheticDraftSaveSuccess(agentKey, request, lockVersion),
    definition: syntheticV2DraftDefinition(agentKey, {
      prompt_text: request.candidate.prompt_text,
      model: structuredClone(request.candidate.model),
      assembly_rules: structuredClone(
        request.candidate.assembly_rules ?? EMPTY_V2_ASSEMBLY_RULES,
      ),
      candidate_hash: 'd'.repeat(64),
    }),
  };
}

/** The coherent 200 for whichever candidate shape a save actually submitted. */
function saveSuccessFor(save: CapturedSave) {
  const lockVersion = save.body.lock_version + 1;
  return save.body.candidate.assembly_rules
    ? v2SaveSuccess(save.agentKey, save.body, lockVersion)
    : syntheticDraftSaveSuccess(save.agentKey, save.body, lockVersion);
}

/** An ordinary save 409 whose coherent server snapshot has moved roles to v2. */
function crossVersionSaveConflict(
  request: DraftSaveRequest,
  v2Roles: readonly AgentKey[],
  currentLockVersion = 1,
) {
  const conflict = syntheticDraftSaveConflict(request, {}, currentLockVersion);
  for (const agentKey of v2Roles) {
    conflict.server.definitions[agentKey] = syntheticV2DraftDefinition(agentKey);
  }
  return conflict;
}

/** The exact edited-by-one-code-point persisted Graph Version 1 composite. */
function oneCodePointEdit(agentKey: 'data_analyst' | 'build_reviewer'): string {
  const published = PUBLISHED_V1_PROMPT_SOURCE[agentKey];
  return `${published.slice(0, -1)}é`;
}

async function openAssemblyTab(page: Page, displayName: string) {
  await page.getByRole('navigation', { name: 'Graph nodes' })
    .getByRole('button', { name: displayName }).click();
  await page.getByRole('tab', { name: 'Assembly' }).click();
}

function assemblyPanel(page: Page) {
  return page.getByRole('tabpanel', { name: 'Assembly' });
}

function protectedRows(page: Page) {
  return assemblyPanel(page).getByRole('group', { name: /^Protected stage: / });
}

async function protectedStageIds(page: Page): Promise<string[]> {
  return protectedRows(page).evaluateAll(
    (rows) => rows.map((row) => row.getAttribute('data-stage-id') ?? ''),
  );
}

function retainedRegion(page: Page) {
  return page.getByRole('region', { name: 'Values retained for recovery' });
}

function retainedAlternative(page: Page, index: number) {
  return retainedRegion(page).getByRole('group', { name: `Retained alternative ${index}` });
}

const DISPLAY_NAMES: Record<AgentKey, string> = {
  architect: 'Architect',
  data_analyst: 'Data Analyst',
  builder: 'Builder',
  build_reviewer: 'Build Reviewer',
  fixer: 'Fixer',
  fix_reviewer: 'Fix Reviewer',
  deck_reviewer: 'Deck Reviewer',
};

test('a Graph Version 1 role offers Upgrade, the exact locked protected text, and no custom or protected controls', async ({ page }) => {
  await installExactIdentityMock(page);
  await installWorkbenchMock(page);
  const saves = await installSaveMock(page, (route) => fulfillJson(route, 500, {}));
  const upgrades = await installPostMock(page, UPGRADE_ENDPOINT, (route) => fulfillJson(route, 500, {}));
  await openWorkbench(page);
  await openAssemblyTab(page, 'Build Reviewer');

  await expect(assemblyPanel(page).getByRole('button', { name: 'Upgrade protected assembly' }))
    .toBeEnabled();
  await expect(assemblyPanel(page)).toContainText(
    'Custom text blocks require the Graph Version 2 protected assembly.',
  );
  await expect(assemblyPanel(page).getByRole('group', { name: /^Custom blocks: / })).toHaveCount(0);
  await expect(assemblyPanel(page).getByRole('button', { name: /^Add custom block / })).toHaveCount(0);

  const expected = syntheticDraftDefinitions.build_reviewer.protected_stage_view;
  await expect(protectedRows(page)).toHaveCount(expected.length);
  expect(await protectedStageIds(page)).toEqual(expected.map((row) => row.stage_id));
  for (const row of expected) {
    const group = assemblyPanel(page).getByRole('group', { name: `Protected stage: ${row.label}` });
    await expect(group).toContainText(row.display_text);
    await expect(group).toContainText('Locked');
    // A locked row is display only: it contributes no control of any kind.
    await expect(group.getByRole('button')).toHaveCount(0);
    await expect(group.getByRole('textbox')).toHaveCount(0);
    await expect(group.getByRole('combobox')).toHaveCount(0);
    // And no protected label may become a heading that collides by name substring.
    await expect(group.getByRole('heading')).toHaveCount(0);
  }
  await expect(assemblyPanel(page)).toContainText('Protected assembly version 1');
  expect(saves).toHaveLength(0);
  expect(upgrades).toHaveLength(0);
});

test('a Graph Version 2 role offers custom blocks at legal anchors, exactly-once protected rows, and no Upgrade', async ({ page }) => {
  await installExactIdentityMock(page);
  await installWorkbenchMock(page, 200, workbenchWith({
    build_reviewer: syntheticV2DraftDefinition('build_reviewer'),
  }));
  await openWorkbench(page);
  await openAssemblyTab(page, 'Build Reviewer');

  await expect(assemblyPanel(page).getByRole('button', { name: 'Upgrade protected assembly' }))
    .toHaveCount(0);
  await expect(assemblyPanel(page)).toContainText('Protected assembly version 2');

  const expected = v2ProtectedStageView('build_reviewer');
  const stageIds = await protectedStageIds(page);
  expect(stageIds).toEqual(expected.map((row) => row.stage_id));
  expect(new Set(stageIds).size).toBe(stageIds.length);
  for (const row of expected) {
    await expect(
      assemblyPanel(page).getByRole('group', { name: `Protected stage: ${row.label}` }),
    ).toContainText(row.display_text);
  }

  // The client offers exactly the anchors the server view declares, plus the one
  // pre-protected authored-prompt anchor.
  const declared = new Set(expected.flatMap((row) => row.legal_adjacent_custom_anchors));
  const anchorGroups = await assemblyPanel(page)
    .getByRole('group', { name: /^Custom blocks: / })
    .evaluateAll((groups) => groups.map((group) => group.getAttribute('aria-label') ?? ''));
  expect(anchorGroups).toEqual([
    'Custom blocks: After authored prompt',
    'Custom blocks: After deck-brief re-review',
    'Custom blocks: After environment constraints',
  ]);
  expect(declared).toEqual(new Set(['after_deck_brief', 'after_environment_constraints']));
});

test('custom blocks are added, edited, reordered and deleted locally, and only an explicit Save writes them', async ({ page }) => {
  await installExactIdentityMock(page);
  await installWorkbenchMock(page, 200, workbenchWith({
    architect: syntheticV2DraftDefinition('architect'),
  }));
  const saves = await installSaveMock(page, (route, save) => fulfillJson(
    route,
    200,
    v2SaveSuccess(save.agentKey, save.body, 1),
  ));
  await openWorkbench(page);
  await page.getByRole('tab', { name: 'Assembly' }).click();

  const authored = assemblyPanel(page).getByRole('group', { name: 'Custom blocks: After authored prompt' });
  const environment = assemblyPanel(page).getByRole('group', { name: 'Custom blocks: After environment constraints' });
  await authored.getByRole('button', { name: 'Add custom block After authored prompt' }).click();
  await authored.getByRole('button', { name: 'Add custom block After authored prompt' }).click();
  await environment.getByRole('button', { name: 'Add custom block After environment constraints' }).click();

  const first = assemblyPanel(page).getByRole('group', { name: 'Custom block 1 at After authored prompt' });
  const second = assemblyPanel(page).getByRole('group', { name: 'Custom block 2 at After authored prompt' });
  const lone = assemblyPanel(page).getByRole('group', { name: 'Custom block 1 at After environment constraints' });
  await first.getByRole('textbox', { name: 'Block text' }).fill('Authored sibling one');
  await second.getByRole('textbox', { name: 'Block text' }).fill('Authored sibling two');
  await lone.getByRole('textbox', { name: 'Block text' }).fill('Environment sibling');
  await lone.getByRole('combobox', { name: 'Condition' }).selectOption('design_system_active');

  // Movement is offered only inside an anchor group, so no arrow can cross an anchor.
  await expect(first.getByRole('button', { name: 'Move up' })).toHaveCount(0);
  await expect(first.getByRole('button', { name: 'Move down' })).toHaveCount(1);
  await expect(second.getByRole('button', { name: 'Move up' })).toHaveCount(1);
  await expect(second.getByRole('button', { name: 'Move down' })).toHaveCount(0);
  await expect(lone.getByRole('button', { name: 'Move up' })).toHaveCount(0);
  await expect(lone.getByRole('button', { name: 'Move down' })).toHaveCount(0);

  const idsBefore = await assemblyPanel(page).getByRole('group', { name: /^Custom block / })
    .evaluateAll((groups) => groups.map((group) => group.getAttribute('data-block-id') ?? ''));
  await first.getByRole('button', { name: 'Move down' }).click();
  const idsAfter = await assemblyPanel(page).getByRole('group', { name: /^Custom block / })
    .evaluateAll((groups) => groups.map((group) => group.getAttribute('data-block-id') ?? ''));
  expect(idsAfter).toEqual([idsBefore[1], idsBefore[0], idsBefore[2]]);
  await expect(
    assemblyPanel(page).getByRole('group', { name: 'Custom block 1 at After authored prompt' })
      .getByRole('textbox', { name: 'Block text' }),
  ).toHaveValue('Authored sibling two');

  await assemblyPanel(page).getByRole('group', { name: 'Custom block 2 at After authored prompt' })
    .getByRole('button', { name: 'Delete' }).click();
  await expect(assemblyPanel(page).getByRole('group', { name: /^Custom block / })).toHaveCount(2);

  expect(saves).toHaveLength(0);
  await page.getByRole('button', { name: 'Save Draft' }).click();
  await expect.poll(() => saves.length).toBe(1);
  expect(saves[0].body).toEqual({
    lock_version: 0,
    candidate: {
      prompt_text: V2_AUTHORED_PROMPT.architect,
      model: {
        endpoint_name: 'databricks-claude-opus-4-6',
        temperature: 0.7,
        max_tokens: 60000,
        top_p: 0.95,
      },
      assembly_rules: {
        format_version: 2,
        custom_blocks: [
          {
            kind: 'custom_text',
            block_id: idsBefore[1],
            anchor: 'after_authored_prompt',
            condition: 'always',
            text: 'Authored sibling two',
          },
          {
            kind: 'custom_text',
            block_id: idsBefore[2],
            anchor: 'after_environment_constraints',
            condition: 'design_system_active',
            text: 'Environment sibling',
          },
        ],
      },
    },
  });
  await expect(page.getByText('Lock version').locator('..')).toContainText('Lock version1');
  await expect(page.getByRole('navigation', { name: 'Graph nodes' })
    .getByRole('button', { name: 'Architect' })).toContainText('Needs test');
});

test('an ordered three-issue 422 renders inline beside its field and keeps every other issue in exact server order', async ({ page }) => {
  await installExactIdentityMock(page);
  await installWorkbenchMock(page, 200, workbenchWith({
    architect: syntheticV2DraftDefinition('architect'),
  }));
  const saves = await installSaveMock(page, (route) => fulfillJson(route, 422, {
    code: 'invalid_draft',
    errors: [
      {
        field: 'candidate.assembly_rules.custom_blocks.*.text',
        code: 'blank',
        message: 'Custom block text must not be blank.',
      },
      {
        field: 'candidate.prompt_text',
        code: 'rejected',
        message: 'Prompt blocked by policy.',
      },
      {
        field: 'candidate.assembly_rules.custom_blocks.*.anchor',
        code: 'invalid_anchor_order',
        message: 'Custom blocks must be ordered by protected anchor.',
      },
    ],
  }));
  await openWorkbench(page);
  await page.getByRole('button', { name: 'Save Draft' }).click();

  await expect(page.getByRole('textbox', { name: 'Prompt text' })).toHaveAttribute(
    'aria-describedby',
    'architect-prompt-error',
  );
  await expect(page.locator('#architect-prompt-error')).toHaveText('Prompt blocked by policy.');

  const issues = page.getByRole('region', { name: 'Server rejected this request' });
  // The inline owner is not repeated in the ordered region; the other two keep order.
  await expect(issues.getByRole('listitem')).toHaveCount(2);
  await expect(issues.getByRole('listitem').nth(0)).toContainText(
    'candidate.assembly_rules.custom_blocks.*.text — blank',
  );
  await expect(issues.getByRole('listitem').nth(1)).toContainText(
    'candidate.assembly_rules.custom_blocks.*.anchor — invalid_anchor_order',
  );
  await expect(issues.getByRole('button', { name: 'Go to Assembly tab' })).toHaveCount(2);
  expect(saves).toHaveLength(1);
});

test('an upgrade 409 carries client_candidate null, reconciles the crossed snapshot, and sends no retry', async ({ page }) => {
  await installExactIdentityMock(page);
  const workbenchRequestCount = await installWorkbenchMock(page);
  const saves = await installSaveMock(page, (route) => fulfillJson(route, 500, {}));
  const upgrades = await installPostMock(page, UPGRADE_ENDPOINT, (route) => fulfillJson(
    route,
    409,
    syntheticNullCandidateConflict(0, 1, ['data_analyst']),
  ));
  await openWorkbench(page);
  await openAssemblyTab(page, 'Data Analyst');
  await assemblyPanel(page).getByRole('button', { name: 'Upgrade protected assembly' }).click();

  const conflict = page.getByRole('region', { name: 'Draft changed on the server' });
  await expect(conflict.getByRole('group', { name: 'Server values' })).toBeVisible();
  // An operation that submitted no candidate must never render one.
  await expect(conflict.getByRole('group', { name: 'Submitted values' })).toHaveCount(0);
  await expect(conflict).toContainText('Expected lock 0');
  await expect(conflict).toContainText('Current lock 1');
  await expect(page.getByText('Lock version').locator('..')).toContainText('Lock version1');

  await page.getByRole('tab', { name: 'Prompt' }).click();
  await expect(page.getByRole('textbox', { name: 'Prompt text' }))
    .toHaveValue(V2_AUTHORED_PROMPT.data_analyst);
  await conflict.getByRole('button', { name: 'Keep local' }).click();
  await expect(page.getByRole('region', { name: 'Draft changed on the server' })).toHaveCount(0);

  expect(upgrades).toHaveLength(1);
  expect(saves).toHaveLength(0);
  await expect.poll(workbenchRequestCount).toBe(1);
});

for (const agentKey of AFFECTED_ROLES) {
  test(`${DISPLAY_NAMES[agentKey]}: a locally edited legacy prompt refuses the Upgrade with zero POST and a local restore`, async ({ page }) => {
    await installExactIdentityMock(page);
    await installWorkbenchMock(page);
    const saves = await installSaveMock(page, (route) => fulfillJson(route, 500, {}));
    const upgrades = await installPostMock(page, UPGRADE_ENDPOINT, (route) => fulfillJson(route, 500, {}));
    await openWorkbench(page);
    const navigation = page.getByRole('navigation', { name: 'Graph nodes' });
    await navigation.getByRole('button', { name: DISPLAY_NAMES[agentKey] }).click();
    const prompt = page.getByRole('textbox', { name: 'Prompt text' });
    const saved = syntheticDraftDefinitions[agentKey].prompt_text;
    await prompt.fill(DIRTY_LEGACY_PROMPT);

    await page.getByRole('tab', { name: 'Assembly' }).click();
    await assemblyPanel(page).getByRole('button', { name: 'Upgrade protected assembly' }).click();

    // No request ID is allocated and no POST is sent.
    expect(upgrades).toHaveLength(0);
    expect(saves).toHaveLength(0);
    await expect(retainedAlternative(page, 1)).toContainText(
      'Upgrade needs the exact Graph Version 1 prompt.',
    );
    await expect(retainedAlternative(page, 1).getByRole('textbox', { name: 'Manual-only prompt bytes' }))
      .toHaveValue(DIRTY_LEGACY_PROMPT);
    await expect(retainedAlternative(page, 1).getByRole('textbox', { name: 'Manual-only prompt bytes' }))
      .toHaveAttribute('aria-readonly', 'true');

    await page.getByRole('tab', { name: 'Prompt' }).click();
    await expect(prompt).toHaveValue(DIRTY_LEGACY_PROMPT);
    await page.getByRole('button', { name: 'Restore saved prompt' }).click();
    await expect(prompt).toHaveValue(saved);
    expect(upgrades).toHaveLength(0);
    expect(saves).toHaveLength(0);
  });
}

for (const agentKey of AFFECTED_ROLES) {
  test(`${DISPLAY_NAMES[agentKey]}: the server's manual-resolution 422 is shown against Prompt with no automatic rewrite, save or retry`, async ({ page }) => {
    const edited = oneCodePointEdit(agentKey);
    await installExactIdentityMock(page);
    await installWorkbenchMock(page, 200, workbenchWith({
      [agentKey]: v1DraftWithPrompt(agentKey, edited),
    }));
    const saves = await installSaveMock(page, (route) => fulfillJson(route, 500, {}));
    const upgrades = await installPostMock(page, UPGRADE_ENDPOINT, (route) => fulfillJson(
      route,
      422,
      MANUAL_RESOLUTION_REJECTION,
    ));
    await openWorkbench(page);
    await openAssemblyTab(page, DISPLAY_NAMES[agentKey]);
    const stageIdsBefore = await protectedStageIds(page);
    await assemblyPanel(page).getByRole('button', { name: 'Upgrade protected assembly' }).click();

    const issues = page.getByRole('region', { name: 'Server rejected this request' });
    await expect(issues.getByRole('listitem')).toHaveCount(1);
    await expect(issues).toContainText(
      `${MANUAL_RESOLUTION_REJECTION.errors[0].field} — ${MANUAL_RESOLUTION_REJECTION.errors[0].code}`,
    );
    await expect(issues).toContainText(MANUAL_RESOLUTION_REJECTION.errors[0].message);
    await expect(issues.getByRole('button', { name: 'Go to Prompt tab' })).toHaveCount(1);

    // The v1 and custom-control state is untouched, and the edited bytes survive.
    expect(await protectedStageIds(page)).toEqual(stageIdsBefore);
    await expect(assemblyPanel(page).getByRole('button', { name: /^Add custom block / })).toHaveCount(0);
    await expect(assemblyPanel(page).getByRole('button', { name: 'Upgrade protected assembly' }))
      .toBeEnabled();
    await page.getByRole('tab', { name: 'Prompt' }).click();
    await expect(page.getByRole('textbox', { name: 'Prompt text' })).toHaveValue(edited);
    await expect(page.getByRole('button', { name: 'Restore published Graph Version 1 prompt' }))
      .toBeEnabled();
    expect(upgrades).toHaveLength(1);
    expect(saves).toHaveLength(0);
  });
}

for (const agentKey of AFFECTED_ROLES) {
  test(`${DISPLAY_NAMES[agentKey]}: the whole route-backed 422 to authored-only v2 sequence loses no bytes and never writes on its own`, async ({ page }) => {
    const edited = oneCodePointEdit(agentKey);
    const published = PUBLISHED_V1_PROMPT_SOURCE[agentKey];
    await installExactIdentityMock(page);
    const workbenchRequestCount = await installWorkbenchMock(page, 200, workbenchWith({
      [agentKey]: v1DraftWithPrompt(agentKey, edited),
    }));
    const saves = await installSaveMock(page, (route, save) => fulfillJson(
      route,
      200,
      saveSuccessFor(save),
    ));
    const upgrades = await installPostMock(page, UPGRADE_ENDPOINT, (route, _post, call) => (call === 0
      ? fulfillJson(route, 422, MANUAL_RESOLUTION_REJECTION)
      : fulfillJson(route, 200, syntheticUpgradeSuccess(agentKey, 2))));
    const sources = await installPostMock(page, SOURCE_ENDPOINT, (route) => fulfillJson(
      route,
      200,
      syntheticLegacyPromptSource(agentKey, 0),
    ));
    await openWorkbench(page);
    const prompt = page.getByRole('textbox', { name: 'Prompt text' });

    // 1. Upgrade is refused by the server for the persisted one-code-point edit.
    await openAssemblyTab(page, DISPLAY_NAMES[agentKey]);
    await assemblyPanel(page).getByRole('button', { name: 'Upgrade protected assembly' }).click();
    await expect(page.getByRole('region', { name: 'Server rejected this request' })).toBeVisible();
    expect(upgrades[0].body).toEqual({ lock_version: 0 });
    expect(Object.keys(upgrades[0].body)).toEqual(['lock_version']);
    expect(saves).toHaveLength(0);

    // 2. The strict source POST installs the exact published prompt and writes nothing.
    await page.getByRole('tab', { name: 'Prompt' }).click();
    await page.getByRole('button', { name: 'Restore published Graph Version 1 prompt' }).click();
    await expect(prompt).toHaveValue(published);
    expect(sources[0].body).toEqual({ lock_version: 0 });
    expect(Object.keys(sources[0].body)).toEqual(['lock_version']);
    expect(saves).toHaveLength(0);
    await expect(page.getByText('Lock version').locator('..')).toContainText('0');

    // Both displaced alternatives are retained byte-exactly and stay copyable.
    await expect(retainedAlternative(page, 1).getByRole('textbox', { name: 'Manual-only prompt bytes' }))
      .toHaveValue(edited);
    await expect(retainedAlternative(page, 2).getByRole('textbox', { name: 'Manual-only prompt bytes' }))
      .toHaveValue(edited);
    // No substring of the composite was stripped on the way in.
    await expect(prompt).not.toHaveValue(edited);
    expect(published.includes(edited)).toBe(false);

    // 3. An explicit ordinary v1 Save is the only thing that writes.
    await page.getByRole('button', { name: 'Save Draft' }).click();
    await expect.poll(() => saves.length).toBe(1);
    expect(saves[0].body).toEqual({
      lock_version: 0,
      candidate: {
        prompt_text: published,
        model: {
          endpoint_name: 'databricks-claude-opus-4-6',
          temperature: 0.7,
          max_tokens: 60000,
          top_p: 0.95,
        },
      },
    });
    await expect(page.getByText('Lock version').locator('..')).toContainText('Lock version1');

    // 4. Only an explicit Upgrade produces the authored-only v2 definition.
    await page.getByRole('tab', { name: 'Assembly' }).click();
    await assemblyPanel(page).getByRole('button', { name: 'Upgrade protected assembly' }).click();
    await expect.poll(() => upgrades.length).toBe(2);
    expect(upgrades[1].body).toEqual({ lock_version: 1 });
    await expect(assemblyPanel(page)).toContainText('Protected assembly version 2');
    expect(await protectedStageIds(page)).toEqual(
      v2ProtectedStageView(agentKey).map((row) => row.stage_id),
    );
    await expect(assemblyPanel(page).getByRole('button', { name: 'Upgrade protected assembly' }))
      .toHaveCount(0);
    await page.getByRole('tab', { name: 'Prompt' }).click();
    await expect(prompt).toHaveValue(V2_AUTHORED_PROMPT[agentKey]);

    // Every displaced byte is still retained, and none of it is savable.
    await expect(retainedAlternative(page, 1).getByRole('textbox', { name: 'Manual-only prompt bytes' }))
      .toHaveValue(edited);
    await expect(retainedAlternative(page, 2).getByRole('textbox', { name: 'Manual-only prompt bytes' }))
      .toHaveValue(edited);
    await expect(retainedAlternative(page, 3).getByRole('textbox', { name: 'Manual-only prompt bytes' }))
      .toHaveValue(published);
    await expect(retainedAlternative(page, 1).getByRole('group', { name: 'Retained values 1' }))
      .toContainText(V2_AUTHORED_PROMPT[agentKey]);

    // 5. The next PUT can contain no legacy or manual-only prompt at all.
    await page.getByRole('button', { name: 'Save Draft' }).click();
    await expect.poll(() => saves.length).toBe(2);
    const body = JSON.stringify(saves[1].body);
    expect(body).toContain(V2_AUTHORED_PROMPT[agentKey]);
    expect(body).not.toContain(published);
    expect(body).not.toContain(edited);
    expect(saves[1].body.candidate.assembly_rules).toEqual({ format_version: 2, custom_blocks: [] });

    // 6. Nothing automatic happened anywhere in the sequence.
    expect(sources).toHaveLength(1);
    expect(upgrades).toHaveLength(2);
    expect(saves).toHaveLength(2);
    await expect.poll(workbenchRequestCount).toBe(1);
  });
}

test('while an Upgrade is in flight the prompt is frozen, safe fields stay editable, and a queued prompt action is retained', async ({ page }) => {
  await installExactIdentityMock(page);
  await installWorkbenchMock(page);
  const saves = await installSaveMock(page, (route) => fulfillJson(route, 500, {}));
  let heldRoute: Route | null = null;
  const upgrades = await installPostMock(page, UPGRADE_ENDPOINT, (route) => { heldRoute = route; });
  await openWorkbench(page);
  const navigation = page.getByRole('navigation', { name: 'Graph nodes' });
  await navigation.getByRole('button', { name: 'Data Analyst' }).click();
  const prompt = page.getByRole('textbox', { name: 'Prompt text' });
  const saved = syntheticDraftDefinitions.data_analyst.prompt_text;

  // A refused dirty Upgrade leaves one pre-existing alternative to queue later.
  await prompt.fill(DIRTY_LEGACY_PROMPT);
  await page.getByRole('tab', { name: 'Model' }).click();
  await page.getByRole('textbox', { name: 'Custom endpoint name' }).fill('endpoint-retained-A');
  await page.getByRole('tab', { name: 'Assembly' }).click();
  await assemblyPanel(page).getByRole('button', { name: 'Upgrade protected assembly' }).click();
  expect(upgrades).toHaveLength(0);
  await page.getByRole('tab', { name: 'Prompt' }).click();
  await page.getByRole('button', { name: 'Restore saved prompt' }).click();
  await expect(prompt).toHaveValue(saved);

  // Now a clean Upgrade really starts and is held open.
  await page.getByRole('tab', { name: 'Assembly' }).click();
  await assemblyPanel(page).getByRole('button', { name: 'Upgrade protected assembly' }).click();
  await expect.poll(() => heldRoute !== null).toBe(true);
  await expect(assemblyPanel(page).getByRole('button', { name: 'Upgrade protected assembly' }))
    .toBeDisabled();
  await expect(page.getByRole('button', { name: 'Save Draft' })).toBeDisabled();

  await page.getByRole('tab', { name: 'Prompt' }).click();
  await expect(prompt).toBeDisabled();
  await page.getByRole('tab', { name: 'Model' }).click();
  const endpoint = page.getByRole('textbox', { name: 'Custom endpoint name' });
  await expect(endpoint).toBeEnabled();
  await endpoint.fill('endpoint-local-B');
  await expect(page.getByRole('spinbutton', { name: 'Temperature' })).toBeEnabled();

  // Restoring an alternative mid-flight is a prompt action: it is queued, not applied.
  await retainedAlternative(page, 1).getByRole('button', { name: 'Restore retained values' }).click();
  await expect(endpoint).toHaveValue('endpoint-retained-A');
  await expect(retainedAlternative(page, 2)).toContainText(
    'Prompt edits are not accepted while this Upgrade is in flight.',
  );
  await expect(retainedAlternative(page, 2).getByRole('textbox', { name: 'Manual-only prompt bytes' }))
    .toHaveValue(DIRTY_LEGACY_PROMPT);
  await page.getByRole('tab', { name: 'Prompt' }).click();
  await expect(prompt).toHaveValue(saved);

  await fulfillJson(heldRoute!, 200, syntheticUpgradeSuccess('data_analyst', 1));
  await expect(prompt).toHaveValue(V2_AUTHORED_PROMPT.data_analyst);
  await page.getByRole('tab', { name: 'Model' }).click();
  // Safe edits made while pending survive the authoritative adoption.
  await expect(page.getByRole('textbox', { name: 'Custom endpoint name' })).toHaveValue('endpoint-retained-A');
  expect(upgrades).toHaveLength(1);
  expect(saves).toHaveLength(0);
});

test('one aggregate gate holds Save, Upgrade and source recovery across roles until the first settles', async ({ page }) => {
  const edited = oneCodePointEdit('data_analyst');
  await installExactIdentityMock(page);
  await installWorkbenchMock(page, 200, workbenchWith({
    data_analyst: v1DraftWithPrompt('data_analyst', edited),
  }));
  let heldRoute: Route | null = null;
  const saves = await installSaveMock(page, (route, save, call) => {
    if (call === 0) heldRoute = route;
    else return fulfillJson(route, 200, syntheticDraftSaveSuccess(save.agentKey, save.body, 2));
  });
  const upgrades = await installPostMock(page, UPGRADE_ENDPOINT, (route) => fulfillJson(
    route,
    422,
    MANUAL_RESOLUTION_REJECTION,
  ));
  const sources = await installPostMock(page, SOURCE_ENDPOINT, (route) => fulfillJson(
    route,
    200,
    syntheticLegacyPromptSource('data_analyst', 0),
  ));
  await openWorkbench(page);
  const navigation = page.getByRole('navigation', { name: 'Graph nodes' });

  // Provoke the 422 first so the source-recovery control exists at all.
  await openAssemblyTab(page, 'Data Analyst');
  await assemblyPanel(page).getByRole('button', { name: 'Upgrade protected assembly' }).click();
  await expect(page.getByRole('region', { name: 'Server rejected this request' })).toBeVisible();

  // Hold an unrelated role's Save open.
  await navigation.getByRole('button', { name: 'Architect' }).click();
  await page.getByRole('textbox', { name: 'Prompt text' }).fill('Architect A2');
  await page.getByRole('button', { name: 'Save Draft' }).click();
  await expect.poll(() => heldRoute !== null).toBe(true);

  await navigation.getByRole('button', { name: 'Data Analyst' }).click();
  await expect(assemblyPanel(page).getByRole('button', { name: 'Upgrade protected assembly' }))
    .toBeDisabled();
  await expect(page.getByRole('button', { name: 'Save Draft' })).toBeDisabled();
  await page.getByRole('tab', { name: 'Prompt' }).click();
  await expect(page.getByRole('button', { name: 'Restore published Graph Version 1 prompt' }))
    .toBeDisabled();
  expect(upgrades).toHaveLength(1);
  expect(sources).toHaveLength(0);
  expect(saves).toHaveLength(1);

  await fulfillJson(heldRoute!, 200, syntheticDraftSaveSuccess('architect', saves[0].body, 1));
  await expect(page.getByRole('button', { name: 'Restore published Graph Version 1 prompt' }))
    .toBeEnabled();
  await expect(page.getByRole('button', { name: 'Save Draft' })).toBeEnabled();
  await page.getByRole('tab', { name: 'Assembly' }).click();
  await expect(assemblyPanel(page).getByRole('button', { name: 'Upgrade protected assembly' }))
    .toBeEnabled();
});

for (const agentKey of AFFECTED_ROLES) {
  for (const operation of ['save', 'upgrade'] as const) {
    test(`${DISPLAY_NAMES[agentKey]}: a selected ${operation} 409 crossing to Graph Version 2 appends, restores by ID, and never resubmits v1 bytes`, async ({ page }) => {
      await installExactIdentityMock(page);
      await installWorkbenchMock(page);
      const saves = await installSaveMock(page, (route, save, call) => (
        operation === 'save' && call === 0
          ? fulfillJson(route, 409, crossVersionSaveConflict(save.body, [agentKey]))
          : fulfillJson(route, 200, saveSuccessFor(save))));
      const upgrades = await installPostMock(page, UPGRADE_ENDPOINT, (route) => fulfillJson(
        route,
        409,
        syntheticNullCandidateConflict(0, 1, [agentKey]),
      ));
      await openWorkbench(page);
      const navigation = page.getByRole('navigation', { name: 'Graph nodes' });
      await navigation.getByRole('button', { name: DISPLAY_NAMES[agentKey] }).click();
      const prompt = page.getByRole('textbox', { name: 'Prompt text' });
      const saved = syntheticDraftDefinitions[agentKey].prompt_text;

      // A pre-existing retained v1 alternative carrying its own sentinels.
      await prompt.fill(DIRTY_LEGACY_PROMPT);
      await page.getByRole('tab', { name: 'Model' }).click();
      await page.getByRole('textbox', { name: 'Custom endpoint name' }).fill('endpoint-retained-A');
      await page.getByRole('spinbutton', { name: 'Temperature' }).fill('0.11');
      await page.getByRole('spinbutton', { name: 'Maximum tokens' }).fill('1111');
      await page.getByRole('spinbutton', { name: 'Top-p' }).fill('0.11');
      await page.getByRole('tab', { name: 'Assembly' }).click();
      await assemblyPanel(page).getByRole('button', { name: 'Upgrade protected assembly' }).click();
      expect(upgrades).toHaveLength(0);
      await expect(retainedAlternative(page, 1)).toBeVisible();

      // Current local carries distinct sentinels; the prompt is dirty only when an
      // ordinary Save is what crosses the version, because the reducer refuses to
      // start an Upgrade from a dirty affected prompt at all.
      await page.getByRole('tab', { name: 'Model' }).click();
      await page.getByRole('textbox', { name: 'Custom endpoint name' }).fill('endpoint-local-B');
      await page.getByRole('spinbutton', { name: 'Temperature' }).fill('0.22');
      await page.getByRole('spinbutton', { name: 'Maximum tokens' }).fill('2222');
      await page.getByRole('spinbutton', { name: 'Top-p' }).fill('0.22');
      await page.getByRole('tab', { name: 'Prompt' }).click();
      if (operation === 'upgrade') {
        await page.getByRole('button', { name: 'Restore saved prompt' }).click();
        await expect(prompt).toHaveValue(saved);
        await page.getByRole('tab', { name: 'Assembly' }).click();
        await assemblyPanel(page).getByRole('button', { name: 'Upgrade protected assembly' }).click();
        await expect.poll(() => upgrades.length).toBe(1);
      } else {
        await expect(prompt).toHaveValue(DIRTY_LEGACY_PROMPT);
        await page.getByRole('button', { name: 'Save Draft' }).click();
        await expect.poll(() => saves.length).toBe(1);
      }

      // The crossed snapshot installs the server's v2 prompt and rules.
      await page.getByRole('tab', { name: 'Prompt' }).click();
      await expect(prompt).toHaveValue(V2_AUTHORED_PROMPT[agentKey]);
      await page.getByRole('tab', { name: 'Model' }).click();
      await expect(page.getByRole('textbox', { name: 'Custom endpoint name' })).toHaveValue('endpoint-local-B');
      await expect(page.getByRole('spinbutton', { name: 'Temperature' })).toHaveValue('0.22');

      // Reload appends a further alternative rather than overwriting either one.
      const conflict = page.getByRole('region', { name: 'Draft changed on the server' });
      await expect(retainedAlternative(page, 2)).toBeVisible();
      await conflict.getByRole('button', { name: 'Reload server' }).click();
      await expect(retainedAlternative(page, 3)).toBeVisible();
      const retainedIds = await retainedRegion(page).getByRole('group', { name: /^Retained alternative / })
        .evaluateAll((groups) => groups.map((group) => group.getAttribute('data-retained-id') ?? ''));
      expect(retainedIds).toHaveLength(3);
      expect(new Set(retainedIds).size).toBe(3);

      // Every manual-only record stays copyable, and every sanitized form is v2.
      for (let index = 1; index <= 3; index += 1) {
        const alternative = retainedAlternative(page, index);
        await expect(alternative.getByRole('textbox', { name: 'Manual-only prompt bytes' }))
          .toHaveAttribute('aria-readonly', 'true');
        await expect(alternative.getByRole('group', { name: `Retained values ${index}` }))
          .toContainText(V2_AUTHORED_PROMPT[agentKey]);
        await expect(alternative.getByRole('group', { name: `Retained values ${index}` }))
          .toContainText('Custom blocks');
      }
      await expect(retainedAlternative(page, 1).getByRole('textbox', { name: 'Manual-only prompt bytes' }))
        .toHaveValue(DIRTY_LEGACY_PROMPT);

      // Each stable ID restores its own safe fields and never its prompt.
      await retainedAlternative(page, 1).getByRole('button', { name: 'Restore retained values' }).click();
      await page.getByRole('tab', { name: 'Model' }).click();
      await expect(page.getByRole('textbox', { name: 'Custom endpoint name' })).toHaveValue('endpoint-retained-A');
      await expect(page.getByRole('spinbutton', { name: 'Maximum tokens' })).toHaveValue('1111');
      await page.getByRole('tab', { name: 'Prompt' }).click();
      await expect(prompt).toHaveValue(V2_AUTHORED_PROMPT[agentKey]);

      await retainedAlternative(page, 2).getByRole('button', { name: 'Restore retained values' }).click();
      await page.getByRole('tab', { name: 'Model' }).click();
      await expect(page.getByRole('textbox', { name: 'Custom endpoint name' })).toHaveValue('endpoint-local-B');
      await expect(page.getByRole('spinbutton', { name: 'Maximum tokens' })).toHaveValue('2222');

      // The immediate PUT can contain none of the v1 or manual-only strings.
      const before = saves.length;
      await page.getByRole('button', { name: 'Save Draft' }).click();
      await expect.poll(() => saves.length).toBe(before + 1);
      const body = JSON.stringify(saves[before].body);
      expect(body).toContain(V2_AUTHORED_PROMPT[agentKey]);
      expect(body).not.toContain(saved);
      expect(body).not.toContain('Edited');
      expect(body).not.toContain('nonce');
    });
  }
}

for (const agentKey of AFFECTED_ROLES) {
  for (const operation of ['save', 'upgrade'] as const) {
    test(`${DISPLAY_NAMES[agentKey]}: an unselected affected entry in an ${operation} 409 is quarantined and restorable by ID`, async ({ page }) => {
      await installExactIdentityMock(page);
      await installWorkbenchMock(page);
      const saves = await installSaveMock(page, (route, save, call) => (
        operation === 'save' && call === 0
          ? fulfillJson(route, 409, crossVersionSaveConflict(save.body, [agentKey]))
          : fulfillJson(route, 200, saveSuccessFor(save))));
      const upgrades = await installPostMock(page, UPGRADE_ENDPOINT, (route) => fulfillJson(
        route,
        409,
        syntheticNullCandidateConflict(0, 1, [agentKey]),
      ));
      await openWorkbench(page);
      const navigation = page.getByRole('navigation', { name: 'Graph nodes' });

      // Dirty the affected role, then leave it while Architect drives the conflict.
      await navigation.getByRole('button', { name: DISPLAY_NAMES[agentKey] }).click();
      await page.getByRole('textbox', { name: 'Prompt text' }).fill(DIRTY_LEGACY_PROMPT);
      await page.getByRole('tab', { name: 'Model' }).click();
      await page.getByRole('textbox', { name: 'Custom endpoint name' }).fill('endpoint-unselected-A');
      await navigation.getByRole('button', { name: 'Architect' }).click();
      if (operation === 'save') {
        await page.getByRole('textbox', { name: 'Prompt text' }).fill('Architect A2');
        await page.getByRole('button', { name: 'Save Draft' }).click();
        await expect.poll(() => saves.length).toBe(1);
      } else {
        await page.getByRole('tab', { name: 'Assembly' }).click();
        await assemblyPanel(page).getByRole('button', { name: 'Upgrade protected assembly' }).click();
        await expect.poll(() => upgrades.length).toBe(1);
      }

      // The unselected affected entry crossed to v2 and quarantined its v1 bytes.
      await navigation.getByRole('button', { name: DISPLAY_NAMES[agentKey] }).click();
      await page.getByRole('tab', { name: 'Prompt' }).click();
      await expect(page.getByRole('textbox', { name: 'Prompt text' }))
        .toHaveValue(V2_AUTHORED_PROMPT[agentKey]);
      // Selection never decides whether a conflict region appears.
      await expect(page.getByRole('region', { name: 'Draft changed on the server' })).toHaveCount(0);
      await expect(retainedAlternative(page, 1).getByRole('textbox', { name: 'Manual-only prompt bytes' }))
        .toHaveValue(DIRTY_LEGACY_PROMPT);
      await expect(retainedAlternative(page, 1).getByRole('group', { name: 'Retained values 1' }))
        .toContainText(V2_AUTHORED_PROMPT[agentKey]);
      await page.getByRole('tab', { name: 'Assembly' }).click();
      await expect(assemblyPanel(page)).toContainText('Protected assembly version 2');
      expect(await protectedStageIds(page)).toEqual(
        v2ProtectedStageView(agentKey).map((row) => row.stage_id),
      );

      await retainedAlternative(page, 1).getByRole('button', { name: 'Restore retained values' }).click();
      await page.getByRole('tab', { name: 'Model' }).click();
      await expect(page.getByRole('textbox', { name: 'Custom endpoint name' })).toHaveValue('endpoint-unselected-A');
      await page.getByRole('tab', { name: 'Prompt' }).click();
      await expect(page.getByRole('textbox', { name: 'Prompt text' }))
        .toHaveValue(V2_AUTHORED_PROMPT[agentKey]);

      const before = saves.length;
      await page.getByRole('button', { name: 'Save Draft' }).click();
      await expect.poll(() => saves.length).toBe(before + 1);
      const body = JSON.stringify(saves[before].body);
      expect(body).toContain(V2_AUTHORED_PROMPT[agentKey]);
      expect(body).not.toContain('Edited');
      expect(body).not.toContain(syntheticDraftDefinitions[agentKey].prompt_text);
    });
  }
}

test('the exact already_current 422 links to Assembly, leaves the form untouched, and is unreachable once v2 is installed', async ({ page }) => {
  await installExactIdentityMock(page);
  await installWorkbenchMock(page);
  const saves = await installSaveMock(page, (route) => fulfillJson(route, 500, {}));
  const upgrades = await installPostMock(page, UPGRADE_ENDPOINT, (route, _post, call) => (call === 0
    ? fulfillJson(route, 422, ALREADY_CURRENT_REJECTION)
    : fulfillJson(route, 200, syntheticUpgradeSuccess('architect', 1))));
  await openWorkbench(page);
  await page.getByRole('tab', { name: 'Assembly' }).click();
  const stageIdsBefore = await protectedStageIds(page);
  await assemblyPanel(page).getByRole('button', { name: 'Upgrade protected assembly' }).click();

  const issues = page.getByRole('region', { name: 'Server rejected this request' });
  await expect(issues.getByRole('listitem')).toHaveCount(1);
  await expect(issues).toContainText(
    `${ALREADY_CURRENT_REJECTION.errors[0].field} — ${ALREADY_CURRENT_REJECTION.errors[0].code}`,
  );
  await expect(issues).toContainText(ALREADY_CURRENT_REJECTION.errors[0].message);
  await expect(issues.getByRole('button', { name: 'Go to Assembly tab' })).toHaveCount(1);
  expect(await protectedStageIds(page)).toEqual(stageIdsBefore);
  await expect(page.getByText('Lock version').locator('..')).toContainText('0');
  expect(upgrades).toHaveLength(1);

  // A successful upgrade removes the only control that can issue the request, so
  // an already-current v2 form structurally cannot retry it.
  await assemblyPanel(page).getByRole('button', { name: 'Upgrade protected assembly' }).click();
  await expect.poll(() => upgrades.length).toBe(2);
  await expect(assemblyPanel(page)).toContainText('Protected assembly version 2');
  await expect(assemblyPanel(page).getByRole('button', { name: 'Upgrade protected assembly' }))
    .toHaveCount(0);
  await expect(page.getByRole('region', { name: 'Server rejected this request' })).toHaveCount(0);
  expect(upgrades).toHaveLength(2);
  expect(saves).toHaveLength(0);
});

for (const agentKey of ['architect', 'data_analyst', 'build_reviewer'] as const) {
  test(`${DISPLAY_NAMES[agentKey]}: a pristine upgrade returns the authored-only prompt and exactly-once protected rows`, async ({ page }) => {
    await installExactIdentityMock(page);
    await installWorkbenchMock(page);
    const upgrades = await installPostMock(page, UPGRADE_ENDPOINT, (route) => fulfillJson(
      route,
      200,
      syntheticUpgradeSuccess(agentKey, 1),
    ));
    await openWorkbench(page);
    await openAssemblyTab(page, DISPLAY_NAMES[agentKey]);
    await assemblyPanel(page).getByRole('button', { name: 'Upgrade protected assembly' }).click();
    await expect.poll(() => upgrades.length).toBe(1);

    const expected = v2ProtectedStageView(agentKey);
    const stageIds = await protectedStageIds(page);
    expect(stageIds).toEqual(expected.map((row) => row.stage_id));
    expect(new Set(stageIds).size).toBe(stageIds.length);
    for (const row of expected) {
      const group = assemblyPanel(page).getByRole('group', { name: `Protected stage: ${row.label}` });
      await expect(group).toHaveCount(1);
      await expect(group).toContainText(row.display_text);
    }
    await page.getByRole('tab', { name: 'Prompt' }).click();
    await expect(page.getByRole('textbox', { name: 'Prompt text' }))
      .toHaveValue(V2_AUTHORED_PROMPT[agentKey]);
    // Even a pristine upgrade displaces the Graph Version 1 prompt, which is the
    // only local copy left once the authored-only prompt is installed, so exactly
    // one alternative is retained and its savable form is already v2.
    await expect(retainedRegion(page).getByRole('group', { name: /^Retained alternative / }))
      .toHaveCount(1);
    await expect(retainedAlternative(page, 1)).toContainText(
      'The server moved this role to Graph Version 2.',
    );
    await expect(retainedAlternative(page, 1).getByRole('textbox', { name: 'Manual-only prompt bytes' }))
      .toHaveValue(syntheticDraftDefinitions[agentKey].prompt_text);
    await expect(retainedAlternative(page, 1).getByRole('group', { name: 'Retained values 1' }))
      .toContainText(V2_AUTHORED_PROMPT[agentKey]);
  });
}

test('a repeated same-content save is accepted with changed false and still advances the server lock', async ({ page }) => {
  await installExactIdentityMock(page);
  await installWorkbenchMock(page);
  const saves = await installSaveMock(page, (route, save, call) => fulfillJson(route, 200, {
    ...syntheticDraftSaveSuccess(save.agentKey, save.body, call + 1),
    changed: call === 0,
  }));
  await openWorkbench(page);
  await page.getByRole('textbox', { name: 'Prompt text' }).fill('Architect A2');
  await page.getByRole('button', { name: 'Save Draft' }).click();
  await expect.poll(() => saves.length).toBe(1);
  await expect(page.getByText('Lock version').locator('..')).toContainText('Lock version1');

  await page.getByRole('button', { name: 'Save Draft' }).click();
  await expect.poll(() => saves.length).toBe(2);
  expect(saves[1].body).toEqual({ ...saves[0].body, lock_version: 1 });
  await expect(page.getByText('Lock version').locator('..')).toContainText('2');
  await expect(page.getByRole('alert')).toHaveCount(0);
  await expect(page.getByRole('navigation', { name: 'Graph nodes' })
    .getByRole('button', { name: 'Architect' })).toContainText('Needs test');
});

test('a legacy source response whose role or lock disagrees is contained without a write', async ({ page }) => {
  const edited = oneCodePointEdit('data_analyst');
  await installExactIdentityMock(page);
  await installWorkbenchMock(page, 200, workbenchWith({
    data_analyst: v1DraftWithPrompt('data_analyst', edited),
  }));
  const saves = await installSaveMock(page, (route) => fulfillJson(route, 500, {}));
  await installPostMock(page, UPGRADE_ENDPOINT, (route) => fulfillJson(
    route,
    422,
    MANUAL_RESOLUTION_REJECTION,
  ));
  const sources = await installPostMock(page, SOURCE_ENDPOINT, (route) => fulfillJson(
    route,
    200,
    // The lock the route reports has moved, which this client-only contract refuses.
    syntheticLegacyPromptSource('data_analyst', 4),
  ));
  await openWorkbench(page);
  await openAssemblyTab(page, 'Data Analyst');
  await assemblyPanel(page).getByRole('button', { name: 'Upgrade protected assembly' }).click();
  await expect(page.getByRole('region', { name: 'Server rejected this request' })).toBeVisible();

  await page.getByRole('tab', { name: 'Prompt' }).click();
  await page.getByRole('button', { name: 'Restore published Graph Version 1 prompt' }).click();
  await expect(page.getByRole('alert')).toContainText(
    'Unable to save draft because the server response was invalid.',
  );
  await expect(page.getByRole('textbox', { name: 'Prompt text' })).toHaveValue(edited);
  await expect(retainedRegion(page)).toHaveCount(0);
  expect(sources).toHaveLength(1);
  expect(saves).toHaveLength(0);
});

test('the forbidden-action rule fires on every banned name and spares the legitimate restore controls', () => {
  // Asserted separately from the sweep so the sweep cannot pass merely because a
  // matching control happened to be absent from the state it walked.
  for (const forbidden of [
    'Run isolated test', 'Approve draft', 'Reject draft', 'Review & publish',
    'Publish draft', 'Publishes the release', 'Publishing', 'Release history', 'Rollback release',
    // All four were missed while the stem was word-bounded, which is the wrong trade for
    // one legitimate name and wrong toward #264's and #266's own publish-adjacent work.
    'Republish release', 'Unpublish draft', 'Publisher settings', 'Published versions',
  ]) {
    expect(forbidsActionName(forbidden)).toBe(true);
  }
  for (const allowed of ALLOWED_ACTION_NAMES) expect(forbidsActionName(allowed)).toBe(false);
  expect(ALLOWED_ACTION_NAMES).toHaveLength(5);
  // An exempt name is removed from the string, not read as a licence for the rest of it.
  expect(forbidsActionName('Restore saved prompt and publish')).toBe(true);
  // #267's two run controls are exempt by exact name only (C25/C38).
  expect(forbidsActionName('Run test case and publish')).toBe(true);
  expect(forbidsActionName('Run published baseline, then approve')).toBe(true);
  expect(forbidsActionName('View run 12')).toBe(true);
});

test('no control in the panel ever offers execution, review, publication, history, or rollback', async ({ page }) => {
  const edited = oneCodePointEdit('data_analyst');
  await installExactIdentityMock(page);
  await installWorkbenchMock(page, 200, workbenchWith({
    build_reviewer: syntheticV2DraftDefinition('build_reviewer'),
    data_analyst: v1DraftWithPrompt('data_analyst', edited),
  }));
  await installPostMock(page, UPGRADE_ENDPOINT, (route) => fulfillJson(
    route,
    422,
    MANUAL_RESOLUTION_REJECTION,
  ));
  await openWorkbench(page);
  const panel = page.getByRole('tabpanel', { name: 'Agent Definitions' });
  await expect(panel.getByRole('button', { name: 'Save Draft' })).toBeEnabled();
  // #267 replaced the "not available" notice with the Agent Test Case panel.
  await expect(page.getByRole('complementary', { name: 'Isolated testing' })
    .getByRole('button', { name: 'Load Agent Test Cases' })).toBeEnabled();
  await expect(panel).not.toContainText('Isolated testing is not available in this release.');

  // Put the legitimate `Restore published Graph Version 1 prompt` control on screen,
  // so the sweep below is exercised in the state that used to be one away from a
  // false alarm rather than only in the states where it is absent.
  await openAssemblyTab(page, 'Data Analyst');
  await assemblyPanel(page).getByRole('button', { name: 'Upgrade protected assembly' }).click();
  await page.getByRole('tab', { name: 'Prompt' }).click();
  await expect(page.getByRole('button', { name: 'Restore published Graph Version 1 prompt' }))
    .toBeVisible();

  const sweep = async () => {
    const names = await panel.locator('button, a')
      .evaluateAll((controls) => controls.map((control) => (
        `${control.getAttribute('aria-label') ?? ''} ${control.textContent ?? ''} ${control.getAttribute('title') ?? ''}`
      )));
    expect(names.length).toBeGreaterThan(0);
    for (const name of names) expect(forbidsActionName(name)).toBe(false);
    return names;
  };

  // v1 with the recovery control live, v1 plain, and v2 with custom-block controls.
  const withRecovery = await sweep();
  expect(withRecovery.some((name) => name.includes('Restore published Graph Version 1 prompt')))
    .toBe(true);
  for (const displayName of ['Architect', 'Build Reviewer']) {
    await page.getByRole('navigation', { name: 'Graph nodes' })
      .getByRole('button', { name: displayName }).click();
    for (const tab of ['Prompt', 'Model', 'Output Schema', 'Assembly']) {
      await page.getByRole('tab', { name: tab }).click();
      await sweep();
    }
  }
});

test('a safe-field edit hides the published-source recovery until the rejection is provoked again', async ({ page }) => {
  // M-8, characterized rather than fixed: clearing `responseIssues` on any edit
  // withdraws the only route back to the published composite. Nothing is lost, but
  // the admin has to re-provoke the 422. Pinned here so a future change is visible.
  const edited = oneCodePointEdit('build_reviewer');
  await installExactIdentityMock(page);
  await installWorkbenchMock(page, 200, workbenchWith({
    build_reviewer: v1DraftWithPrompt('build_reviewer', edited),
  }));
  const saves = await installSaveMock(page, (route) => fulfillJson(route, 500, {}));
  const upgrades = await installPostMock(page, UPGRADE_ENDPOINT, (route) => fulfillJson(
    route,
    422,
    MANUAL_RESOLUTION_REJECTION,
  ));
  await openWorkbench(page);
  await openAssemblyTab(page, 'Build Reviewer');
  await assemblyPanel(page).getByRole('button', { name: 'Upgrade protected assembly' }).click();

  const restore = page.getByRole('button', { name: 'Restore published Graph Version 1 prompt' });
  await page.getByRole('tab', { name: 'Prompt' }).click();
  await expect(restore).toBeVisible();

  await page.getByRole('tab', { name: 'Model' }).click();
  await page.getByRole('spinbutton', { name: 'Temperature' }).fill('0.42');
  await page.getByRole('tab', { name: 'Prompt' }).click();
  await expect(restore).toHaveCount(0);
  await expect(page.getByRole('region', { name: 'Server rejected this request' })).toHaveCount(0);
  // No bytes were lost: the persisted composite is still exactly what it was.
  await expect(page.getByRole('textbox', { name: 'Prompt text' })).toHaveValue(edited);

  await page.getByRole('tab', { name: 'Assembly' }).click();
  await assemblyPanel(page).getByRole('button', { name: 'Upgrade protected assembly' }).click();
  await expect.poll(() => upgrades.length).toBe(2);
  await page.getByRole('tab', { name: 'Prompt' }).click();
  await expect(restore).toBeVisible();
  expect(saves).toHaveLength(0);
});

// ── Output Schema tab: editor controls ───────────────────────────────────────

function outputSchemaPanel(page: Page) {
  return page.getByRole('tabpanel', { name: 'Output Schema' });
}

async function openOutputSchemaTab(page: Page, displayName = 'Architect') {
  await page.getByRole('navigation', { name: 'Graph nodes' })
    .getByRole('button', { name: displayName }).click();
  await page.getByRole('tab', { name: 'Output Schema' }).click();
}

/** A workbench with architect's draft replaced by a schema-v2 definition. */
function workbenchWithSchemaV2(agentKey: AgentKey = 'architect') {
  const body = cloneWorkbench();
  for (const node of body.nodes) {
    if (node.execution_kind !== 'model' || node.agent_key !== agentKey) continue;
    node.draft = syntheticSchemaV2DraftDefinition(agentKey);
  }
  return body;
}

test('output schema tab: v1 shows Schema Upgrade button and no picker; no protected type/default inputs', async ({ page }) => {
  await installExactIdentityMock(page);
  await installWorkbenchMock(page);
  await openWorkbench(page);
  await openOutputSchemaTab(page);

  const panel = outputSchemaPanel(page);
  // Schema Upgrade button present for v1
  await expect(panel.getByRole('button', { name: 'Schema Upgrade' })).toBeVisible();

  // No optional-field checkbox rows for v1 (selectable_optional_fields is empty)
  await expect(panel.getByRole('checkbox')).toHaveCount(0);

  // No editable input named after protected properties
  for (const label of ['Type', 'Default', 'Max items', 'Min length', 'Max length']) {
    await expect(panel.getByRole('textbox', { name: label })).toHaveCount(0);
    await expect(panel.getByRole('spinbutton', { name: label })).toHaveCount(0);
  }

  // #264 I1: under v1 the canonical fields are protected labels only. Accessible names
  // match by substring here, so these two queries cover every canonical field's input.
  const intent = panel.getByRole('group', { name: 'Canonical field: intent' });
  await expect(intent.getByRole('group', { name: 'Protected properties of intent' })).toBeVisible();
  await expect(intent.getByRole('textbox')).toHaveCount(0);
  await expect(panel.getByRole('textbox', { name: 'Description guidance for ' })).toHaveCount(0);
  await expect(panel.getByRole('textbox', { name: 'Examples guidance for ' })).toHaveCount(0);
});

test('output schema tab: v2 shows diagnostic_notes picker with protected labels, no type/default inputs', async ({ page }) => {
  await installExactIdentityMock(page);
  await installWorkbenchMock(page, 200, workbenchWithSchemaV2());
  await openWorkbench(page);
  await openOutputSchemaTab(page);

  const panel = outputSchemaPanel(page);
  // Schema Upgrade button absent for v2
  await expect(panel.getByRole('button', { name: 'Schema Upgrade' })).toHaveCount(0);

  // Optional field row for diagnostic_notes
  const row = panel.getByRole('group', { name: 'Optional field: diagnostic_notes' });
  await expect(row).toBeVisible();

  // Protected label text visible
  await expect(row).toContainText('array');
  await expect(row).toContainText(DIAGNOSTIC_NOTES_DESCRIPTOR.description);

  // No editable input for the protected schema properties
  for (const label of ['type', 'default', 'max_items', 'strip_whitespace']) {
    await expect(panel.getByRole('textbox', { name: new RegExp(label, 'i') })).toHaveCount(0);
    await expect(panel.getByRole('spinbutton', { name: new RegExp(label, 'i') })).toHaveCount(0);
  }

  // #264 I2: the descriptor's description and example are code-owned text, never
  // inputs; the server rejects any field_overrides entry for an optional name.
  await expect(row.getByRole('textbox')).toHaveCount(0);
  const codeOwned = row.getByRole('group', { name: 'Code-owned guidance of diagnostic_notes' });
  await expect(codeOwned).toContainText(DIAGNOSTIC_NOTES_DESCRIPTOR.description);
  await expect(codeOwned).toContainText(`Example: ${String(DIAGNOSTIC_NOTES_DESCRIPTOR.examples[0])}`);
});

test('v2 selection: selecting diagnostic_notes sends it in the save candidate', async ({ page }) => {
  await installExactIdentityMock(page);
  await installWorkbenchMock(page, 200, workbenchWithSchemaV2());
  const saves = await installSaveMock(page, (route, save) => fulfillJson(
    route,
    200,
    syntheticDraftSaveSuccess(save.agentKey, save.body, 1),
  ));
  await openWorkbench(page);
  await openOutputSchemaTab(page);

  const panel = outputSchemaPanel(page);
  // Select diagnostic_notes
  await panel.getByRole('checkbox', { name: 'Select diagnostic_notes' }).click();
  // Navigate away and back to verify persistence
  await page.getByRole('tab', { name: 'Prompt' }).click();
  await page.getByRole('tab', { name: 'Output Schema' }).click();
  await expect(panel.getByRole('checkbox', { name: 'Select diagnostic_notes' })).toBeChecked();

  // Save and check the body includes schema_overlay
  await page.getByRole('button', { name: 'Save Draft' }).click();
  await expect.poll(() => saves.length).toBe(1);
  const schemaOverlay = saves[0].body.candidate.schema_overlay;
  expect(schemaOverlay).toBeDefined();
  expect(schemaOverlay?.additional_optional_fields).toContain('diagnostic_notes');
});

test('v2 removal: deselecting diagnostic_notes sends empty additional_optional_fields', async ({ page }) => {
  // Start with diagnostic_notes already selected
  const body = workbenchWithSchemaV2();
  for (const node of body.nodes) {
    if (node.execution_kind !== 'model' || node.agent_key !== 'architect') continue;
    node.draft = syntheticSchemaV2DraftDefinition('architect', {
      schema_overlay: { field_overrides: {}, additional_optional_fields: ['diagnostic_notes'] },
    });
  }
  await installExactIdentityMock(page);
  await installWorkbenchMock(page, 200, body);
  const saves = await installSaveMock(page, (route, save) => fulfillJson(
    route,
    200,
    syntheticDraftSaveSuccess(save.agentKey, save.body, 1),
  ));
  await openWorkbench(page);
  await openOutputSchemaTab(page);

  const panel = outputSchemaPanel(page);
  // Should be pre-checked because saved definition has it
  await expect(panel.getByRole('checkbox', { name: 'Select diagnostic_notes' })).toBeChecked();

  // Deselect it
  await panel.getByRole('checkbox', { name: 'Select diagnostic_notes' }).click();
  await expect(panel.getByRole('checkbox', { name: 'Select diagnostic_notes' })).not.toBeChecked();

  await page.getByRole('button', { name: 'Save Draft' }).click();
  await expect.poll(() => saves.length).toBe(1);
  const schemaOverlay = saves[0].body.candidate.schema_overlay;
  expect(schemaOverlay?.additional_optional_fields).toEqual([]);
});

test('schema upgrade sends a lock-only POST and installs the v2 descriptor', async ({ page }) => {
  await installExactIdentityMock(page);
  await installWorkbenchMock(page);
  const schemaUpgrades = await installPostMock(page, SCHEMA_UPGRADE_ENDPOINT, (route) => fulfillJson(
    route,
    200,
    syntheticSchemaUpgradeSuccess('architect', 1),
  ));
  await openWorkbench(page);
  await openOutputSchemaTab(page);

  await outputSchemaPanel(page).getByRole('button', { name: 'Schema Upgrade' }).click();
  await expect.poll(() => schemaUpgrades.length).toBe(1);

  // Body is exactly { lock_version: 0 } with no candidate
  expect(schemaUpgrades[0].body).toEqual({ lock_version: 0 });

  // Wait for Save Draft button to be enabled: this signals the operation settled and
  // the new definition (with v2 schema contract) is installed in the state machine.
  await expect(page.getByRole('button', { name: 'Save Draft' })).toBeEnabled();

  // After upgrade: upgrade button gone, picker visible
  await expect(outputSchemaPanel(page).getByRole('button', { name: 'Schema Upgrade' })).toHaveCount(0);
  await expect(outputSchemaPanel(page)
    .getByRole('group', { name: 'Optional field: diagnostic_notes' })).toBeVisible();
});

test('schema upgrade already_current 422 links to Output Schema tab', async ({ page }) => {
  await installExactIdentityMock(page);
  await installWorkbenchMock(page);
  await installPostMock(page, SCHEMA_UPGRADE_ENDPOINT, (route) => fulfillJson(
    route,
    422,
    SCHEMA_ALREADY_CURRENT_REJECTION,
  ));
  await openWorkbench(page);
  await openOutputSchemaTab(page);

  await outputSchemaPanel(page).getByRole('button', { name: 'Schema Upgrade' }).click();

  // Rejection shown in the issues list
  const issues = page.getByRole('region', { name: 'Server rejected this request' });
  await expect(issues).toBeVisible();
  await expect(issues).toContainText('already_current');

  // "Go to Output Schema tab" link present (issue field starts with schema_contract)
  await expect(issues.getByRole('button', { name: 'Go to Output Schema tab' })).toBeVisible();
});

test('schema upgrade gate: Schema Upgrade is blocked while Save is in flight', async ({ page }) => {
  let releaseSave!: () => void;
  const holdSave = new Promise<void>((resolve) => { releaseSave = resolve; });
  await installExactIdentityMock(page);
  await installWorkbenchMock(page);
  await installSaveMock(page, (route) => {
    return holdSave.then(() => fulfillJson(route, 200, {}));
  });
  const schemaUpgrades = await installPostMock(page, SCHEMA_UPGRADE_ENDPOINT, (route) => fulfillJson(
    route,
    200,
    syntheticSchemaUpgradeSuccess('architect', 1),
  ));
  await openWorkbench(page);

  // Start a save (it's held)
  await page.getByRole('textbox', { name: 'Prompt text' }).fill('Edited');
  await page.getByRole('button', { name: 'Save Draft' }).click();

  // Navigate to Output Schema tab and try to upgrade while save is pending
  await page.getByRole('tab', { name: 'Output Schema' }).click();
  const upgradeButton = outputSchemaPanel(page).getByRole('button', { name: 'Schema Upgrade' });
  await expect(upgradeButton).toBeDisabled();
  expect(schemaUpgrades).toHaveLength(0);

  // Release the save so the test cleans up
  releaseSave();
});

test('direct malformed-API 422 on schema overlay is stable and not a 500', async ({ page }) => {
  // Tests that a type error in schema_overlay.field_overrides reaches the API and comes
  // back as a stable 422 (not a 500). This is the guard the brief requires for the
  // controller's sabotage of candidate.schema_overlay.field_overrides.intent.type.
  const body = workbenchWithSchemaV2();
  await installExactIdentityMock(page);
  await installWorkbenchMock(page, 200, body);
  const saves = await installSaveMock(page, (route) => fulfillJson(
    route,
    422,
    {
      code: 'invalid_draft',
      errors: [
        {
          field: 'candidate.schema_overlay.field_overrides.intent',
          code: 'overlay_guidance_property_forbidden',
          message: 'Only description and examples are editable.',
        },
      ],
    },
  ));
  await openWorkbench(page);
  await openOutputSchemaTab(page);

  // User selects optional field and saves
  await outputSchemaPanel(page).getByRole('checkbox', { name: 'Select diagnostic_notes' }).click();
  await page.getByRole('button', { name: 'Save Draft' }).click();
  await expect.poll(() => saves.length).toBe(1);

  // Response is a stable 422, not a 500
  const issues = page.getByRole('region', { name: 'Server rejected this request' });
  await expect(issues).toBeVisible();
  await expect(issues).toContainText('overlay_guidance_property_forbidden');
  // The issue links to the Output Schema tab
  await expect(issues.getByRole('button', { name: 'Go to Output Schema tab' })).toBeVisible();
});

test('canonical fields: protected labels, guidance edit, blocked malformed examples, save and reload', async ({ page }) => {
  // Canonical guidance is editable only under a v2 schema contract (#264 I1).
  const body = workbenchWithSchemaV2();
  await installExactIdentityMock(page);
  await installWorkbenchMock(page, 200, body);
  const saves = await installSaveMock(page, (route, save) => {
    const success = syntheticDraftSaveSuccess(save.agentKey, save.body, 1);
    const overlay = save.body.candidate.schema_overlay;
    if (overlay) success.definition.schema_overlay = structuredClone(overlay);
    return fulfillJson(route, 200, success);
  });
  await openWorkbench(page);
  await openOutputSchemaTab(page);

  const panel = outputSchemaPanel(page);
  await expect(panel.getByRole('region', { name: 'Canonical output fields' })).toBeVisible();
  const intent = panel.getByRole('group', { name: 'Canonical field: intent' });
  const protectedProperties = intent.getByRole('group', { name: 'Protected properties of intent' });
  await expect(protectedProperties).toContainText('string');
  await expect(protectedProperties).toContainText('yes');
  await expect(protectedProperties).toContainText('discuss, ask_data, build, edit, confirm_design_contract');
  // Only the two guidance textareas are editable; no control exists for a protected property.
  await expect(intent.getByRole('textbox')).toHaveCount(2);
  for (const role of ['checkbox', 'spinbutton', 'combobox'] as const) {
    await expect(intent.getByRole(role)).toHaveCount(0);
  }
  const deckSpec = panel.getByRole('group', { name: 'Protected properties of deck_spec' });
  await expect(deckSpec).toContainText('DeckSpec | null');
  await expect(deckSpec).toContainText('no');

  await intent.getByRole('textbox', { name: 'Description guidance for intent' })
    .fill('Prefer build for new decks.');
  const examples = intent.getByRole('textbox', { name: 'Examples guidance for intent (JSON array)' });
  await examples.fill('["build"');
  await expect(intent.getByRole('alert')).toHaveText('Examples must be a JSON array.');
  await expect(page.getByRole('button', { name: 'Save Draft' })).toBeDisabled();
  expect(saves).toHaveLength(0);

  await examples.fill('["build"]');
  await expect(intent.getByRole('alert')).toHaveCount(0);
  await page.getByRole('button', { name: 'Save Draft' }).click();
  await expect.poll(() => saves.length).toBe(1);
  expect(saves[0].body.candidate.schema_overlay?.field_overrides.intent).toEqual({
    description: 'Prefer build for new decks.',
    examples: ['build'],
  });
  await expect(page.getByRole('button', { name: 'Save Draft' })).toBeEnabled();

  // A real page reload re-reads the server's stored overlay.
  for (const node of body.nodes) {
    if (node.execution_kind !== 'model' || node.agent_key !== 'architect') continue;
    node.draft.schema_overlay = structuredClone(saves[0].body.candidate.schema_overlay!);
  }
  await page.reload();
  await page.getByRole('tab', { name: 'Agent Definitions' }).click();
  await openOutputSchemaTab(page);
  const reloaded = outputSchemaPanel(page).getByRole('group', { name: 'Canonical field: intent' });
  await expect(reloaded.getByRole('textbox', { name: 'Description guidance for intent' }))
    .toHaveValue('Prefer build for new decks.');
  await expect(reloaded.getByRole('textbox', { name: 'Examples guidance for intent (JSON array)' }))
    .toHaveValue('["build"]');
});

test('the affected-role browser matrix cannot silently narrow', () => {
  // Task 6's first round keyed every affected-role loop off the shared fixture copy
  // of LEGACY_COMPOSITE_ROLES. Narrowing that copy removed seven tests from this file
  // and still reported all-green, which is worse than a missing test because it looks
  // like coverage. The loops now run off AFFECTED_ROLES above, and this asserts the
  // fixture still agrees; the server's canonical transition list is joined to both by
  // `test_every_affected_role_copy_matches_the_canonical_transition_list`.
  expect([...AFFECTED_ROLES]).toEqual([...LEGACY_COMPOSITE_ROLES]);
  expect(AFFECTED_ROLES).toHaveLength(2);
  expect(new Set(AFFECTED_ROLES).size).toBe(AFFECTED_ROLES.length);
  for (const agentKey of AFFECTED_ROLES) {
    // Each role must really be a legacy composite in the fixture world, or the
    // matrix would be running its sequences against a role with no published source.
    expect(PUBLISHED_V1_PROMPT_SOURCE[agentKey]).toBeTruthy();
    expect(V2_AUTHORED_PROMPT[agentKey]).toBeTruthy();
    expect(PUBLISHED_V1_PROMPT_SOURCE[agentKey]).not.toEqual(V2_AUTHORED_PROMPT[agentKey]);
  }
});

for (const agentKey of AFFECTED_ROLES) {
  for (const operation of ['save', 'upgrade'] as const) {
    test(`${DISPLAY_NAMES[agentKey]}: Keep local after a ${operation} 409 crossing to Graph Version 2 retains every alternative and resubmits no v1 bytes`, async ({ page }) => {
      await installExactIdentityMock(page);
      const workbenchRequestCount = await installWorkbenchMock(page);
      const saves = await installSaveMock(page, (route, save, call) => (
        operation === 'save' && call === 0
          ? fulfillJson(route, 409, crossVersionSaveConflict(save.body, [agentKey]))
          : fulfillJson(route, 200, saveSuccessFor(save))));
      const upgrades = await installPostMock(page, UPGRADE_ENDPOINT, (route) => fulfillJson(
        route,
        409,
        syntheticNullCandidateConflict(0, 1, [agentKey]),
      ));
      await openWorkbench(page);
      const navigation = page.getByRole('navigation', { name: 'Graph nodes' });
      await navigation.getByRole('button', { name: DISPLAY_NAMES[agentKey] }).click();
      const prompt = page.getByRole('textbox', { name: 'Prompt text' });
      const saved = syntheticDraftDefinitions[agentKey].prompt_text;

      // A pre-existing retained v1 alternative with its own safe sentinels.
      await prompt.fill(DIRTY_LEGACY_PROMPT);
      await page.getByRole('tab', { name: 'Model' }).click();
      await page.getByRole('textbox', { name: 'Custom endpoint name' }).fill('endpoint-keep-A');
      await page.getByRole('spinbutton', { name: 'Temperature' }).fill('0.33');
      await page.getByRole('spinbutton', { name: 'Maximum tokens' }).fill('3333');
      await page.getByRole('spinbutton', { name: 'Top-p' }).fill('0.33');
      await page.getByRole('tab', { name: 'Assembly' }).click();
      await assemblyPanel(page).getByRole('button', { name: 'Upgrade protected assembly' }).click();
      expect(upgrades).toHaveLength(0);
      await expect(retainedAlternative(page, 1)).toBeVisible();

      // Distinct current-local sentinels, and a dirty prompt only where the reducer
      // permits the operation to start at all.
      await page.getByRole('tab', { name: 'Model' }).click();
      await page.getByRole('textbox', { name: 'Custom endpoint name' }).fill('endpoint-keep-B');
      await page.getByRole('spinbutton', { name: 'Temperature' }).fill('0.44');
      await page.getByRole('spinbutton', { name: 'Maximum tokens' }).fill('4444');
      await page.getByRole('spinbutton', { name: 'Top-p' }).fill('0.44');
      await page.getByRole('tab', { name: 'Prompt' }).click();
      if (operation === 'upgrade') {
        await page.getByRole('button', { name: 'Restore saved prompt' }).click();
        await expect(prompt).toHaveValue(saved);
        await page.getByRole('tab', { name: 'Assembly' }).click();
        await assemblyPanel(page).getByRole('button', { name: 'Upgrade protected assembly' }).click();
        await expect.poll(() => upgrades.length).toBe(1);
      } else {
        await page.getByRole('button', { name: 'Save Draft' }).click();
        await expect.poll(() => saves.length).toBe(1);
      }

      const conflict = page.getByRole('region', { name: 'Draft changed on the server' });
      await expect(conflict).toBeVisible();
      await expect(retainedAlternative(page, 2)).toBeVisible();
      const idsBeforeKeep = await retainedRegion(page)
        .getByRole('group', { name: /^Retained alternative / })
        .evaluateAll((groups) => groups.map((group) => group.getAttribute('data-retained-id') ?? ''));
      expect(idsBeforeKeep).toHaveLength(2);

      // Keep local closes the conflict WITHOUT discarding anything that was displaced.
      await conflict.getByRole('button', { name: 'Keep local' }).click();
      await expect(page.getByRole('region', { name: 'Draft changed on the server' })).toHaveCount(0);
      const idsAfterKeep = await retainedRegion(page)
        .getByRole('group', { name: /^Retained alternative / })
        .evaluateAll((groups) => groups.map((group) => group.getAttribute('data-retained-id') ?? ''));
      expect(idsAfterKeep).toEqual(idsBeforeKeep);
      await expect(retainedAlternative(page, 1).getByRole('textbox', { name: 'Manual-only prompt bytes' }))
        .toHaveValue(DIRTY_LEGACY_PROMPT);
      for (let index = 1; index <= 2; index += 1) {
        const alternative = retainedAlternative(page, index);
        await expect(alternative.getByRole('textbox', { name: 'Manual-only prompt bytes' }))
          .toHaveAttribute('aria-readonly', 'true');
        // Every sanitized savable form is already on the server's Graph Version 2.
        await expect(alternative.getByRole('group', { name: `Retained values ${index}` }))
          .toContainText(V2_AUTHORED_PROMPT[agentKey]);
        await expect(alternative.getByRole('group', { name: `Retained values ${index}` }))
          .toContainText('Custom blocks');
      }

      // Keeping local keeps the safe fields, never the displaced v1 prompt or rules.
      await page.getByRole('tab', { name: 'Prompt' }).click();
      await expect(prompt).toHaveValue(V2_AUTHORED_PROMPT[agentKey]);
      await page.getByRole('tab', { name: 'Model' }).click();
      await expect(page.getByRole('textbox', { name: 'Custom endpoint name' })).toHaveValue('endpoint-keep-B');
      await expect(page.getByRole('spinbutton', { name: 'Maximum tokens' })).toHaveValue('4444');
      await page.getByRole('tab', { name: 'Assembly' }).click();
      await expect(assemblyPanel(page)).toContainText('Protected assembly version 2');

      // Each retained ID still restores its own safe tuple independently after Keep local.
      await retainedAlternative(page, 1).getByRole('button', { name: 'Restore retained values' }).click();
      await page.getByRole('tab', { name: 'Model' }).click();
      await expect(page.getByRole('textbox', { name: 'Custom endpoint name' })).toHaveValue('endpoint-keep-A');
      await expect(page.getByRole('spinbutton', { name: 'Maximum tokens' })).toHaveValue('3333');
      await retainedAlternative(page, 2).getByRole('button', { name: 'Restore retained values' }).click();
      await expect(page.getByRole('textbox', { name: 'Custom endpoint name' })).toHaveValue('endpoint-keep-B');
      await page.getByRole('tab', { name: 'Prompt' }).click();
      await expect(prompt).toHaveValue(V2_AUTHORED_PROMPT[agentKey]);

      // The immediate PUT after Keep local carries none of the v1 or manual-only bytes.
      const before = saves.length;
      await page.getByRole('button', { name: 'Save Draft' }).click();
      await expect.poll(() => saves.length).toBe(before + 1);
      const body = JSON.stringify(saves[before].body);
      expect(body).toContain(V2_AUTHORED_PROMPT[agentKey]);
      expect(body).not.toContain(saved);
      expect(body).not.toContain('Edited');
      expect(body).not.toContain('nonce');
      expect(saves[before].body.candidate.assembly_rules)
        .toEqual({ format_version: 2, custom_blocks: [] });
      await expect.poll(workbenchRequestCount).toBe(1);
    });
  }
}

// ============================================================
// #266 Task 6 — model endpoint discovery, manual entry and the saved-candidate probe
// ============================================================

const PROBE_ENDPOINT = '**/api/admin/agent-definitions/draft/*/model-endpoint-probe';
const PROBE_BUTTON = 'Test structured output';
const PROBE_RETRY_BUTTON = 'Retry structured output test';
const PROBE_RESULT_REGION = 'Structured output test result';
const PROBE_SUCCEEDED_TEXT = 'Structured output test succeeded for the saved candidate.';
const URL_NOT_ALLOWED = 'Endpoint must be a Databricks endpoint name, not a URL.';
const EMPTY_DISCOVERY = 'No Databricks foundation-model endpoints are available to this identity.';
const SEED_MODEL = { temperature: 0.7, max_tokens: 60000, top_p: 0.95 };

function probeIdentityText(endpoint: string, hash: string, lock: number) {
  return `Endpoint ${endpoint} · Candidate hash ${hash} · Draft lock ${lock}`;
}

interface CapturedCatalogRead {
  url: string;
  method: string;
  postData: string | null;
  headers: Record<string, string>;
}

/** Registered after `installWorkbenchMock`, so it wins over the shared default. */
async function installCatalogMock(
  page: Page,
  respond: (route: Route, call: number) => Promise<void> | void,
) {
  const reads: CapturedCatalogRead[] = [];
  await page.route(MODEL_ENDPOINTS_ENDPOINT, async (route) => {
    const request = route.request();
    reads.push({
      url: request.url(),
      method: request.method(),
      postData: request.postData(),
      headers: request.headers(),
    });
    await respond(route, reads.length - 1);
  });
  return reads;
}

/** Every discovery read is a bare GET: no query, no body, no endpoint/token/host. */
function expectBareCatalogReads(reads: CapturedCatalogRead[]) {
  expect(reads.length).toBeGreaterThan(0);
  for (const read of reads) {
    expect(read.method).toBe('GET');
    expect(new URL(read.url).search).toBe('');
    expect(read.url).toMatch(/\/api\/admin\/agent-definitions\/model-endpoints$/);
    expect(read.postData).toBeNull();
    expect(read.headers).not.toHaveProperty('authorization');
  }
}

/** The probe body is exactly the current lock, byte for byte. */
async function installProbeMock(
  page: Page,
  respond: (route: Route, post: CapturedPost, call: number) => Promise<void> | void,
) {
  const raw: string[] = [];
  const posts = await installPostMock(page, PROBE_ENDPOINT, async (route, post, call) => {
    raw.push(route.request().postData() ?? '');
    await respond(route, post, call);
  });
  return { posts, raw };
}

function modelTabPanel(page: Page) {
  return page.getByRole('tabpanel', { name: 'Model' });
}

function probeResultRegion(page: Page) {
  return page.getByRole('region', { name: PROBE_RESULT_REGION });
}

function architectNavStatus(page: Page) {
  return page.getByRole('navigation', { name: 'Graph nodes' }).getByRole('button', { name: 'Architect' });
}

test('model endpoint discovery: first Model-tab read, local search, a refresh exposing a newer entry, explicit exact save, then an explicit probe of the saved candidate', async ({ page }) => {
  await installExactIdentityMock(page);
  const workbenchRequestCount = await installWorkbenchMock(page);
  const reads = await installCatalogMock(page, (route, call) => fulfillJson(route, 200, call === 0
    ? syntheticModelEndpointDiscovery()
    : syntheticModelEndpointDiscovery([syntheticNewerModelEndpoint, ...syntheticSystemModelEndpoints])));
  const saves = await installSaveMock(page, (route, save) => fulfillJson(route, 200, saveSuccessFor(save)));
  const probes = await installProbeMock(page, (route) => fulfillJson(route, 200, syntheticProbeSuccess({
    endpoint_name: syntheticNewerModelEndpoint.name,
    candidate_hash: 'd'.repeat(64),
    lock_version: 1,
  })));
  await openWorkbench(page);
  await expect(page.getByRole('heading', { name: 'Graph Version 1' })).toBeVisible();
  expect(reads).toHaveLength(0);
  await page.getByRole('tab', { name: 'Assembly' }).click();
  expect(reads).toHaveLength(0);

  await page.getByRole('tab', { name: 'Model' }).click();
  const panel = modelTabPanel(page);
  const group = panel.getByRole('radiogroup', { name: 'Discovered models' });
  await expect(group.getByRole('radio')).toHaveCount(syntheticSystemModelEndpoints.length);
  expect(reads).toHaveLength(1);
  await expect(group.getByRole('radio', { name: SEED_MODEL_ENDPOINT_NAME, exact: true })).toBeChecked();

  const search = panel.getByRole('searchbox', { name: 'Search discovered models' });
  await search.fill('gpt oss');
  await expect(group.getByRole('radio')).toHaveCount(1);
  await expect(group.getByRole('radio', { name: 'databricks-gpt-oss-120b' })).toBeVisible();
  await search.fill('');
  await expect(group.getByRole('radio')).toHaveCount(syntheticSystemModelEndpoints.length);
  expect(reads).toHaveLength(1);

  await panel.getByRole('button', { name: 'Refresh models' }).click();
  const newer = group.getByRole('radio', { name: syntheticNewerModelEndpoint.name, exact: true });
  await expect(newer).toBeVisible();
  expect(reads).toHaveLength(2);
  // The seed stays exact: a newer family member never moves it on its own.
  await expect(newer).not.toBeChecked();
  await expect(group.getByRole('radio', { name: SEED_MODEL_ENDPOINT_NAME, exact: true })).toBeChecked();
  await expect(page.getByRole('textbox', { name: 'Custom endpoint name' })).toHaveValue(SEED_MODEL_ENDPOINT_NAME);
  await expect(architectNavStatus(page)).not.toContainText('Unsaved');
  expect(saves).toHaveLength(0);
  expect(probes.posts).toHaveLength(0);

  await newer.check();
  await expect(page.getByRole('textbox', { name: 'Custom endpoint name' })).toHaveValue(syntheticNewerModelEndpoint.name);
  await expect(panel.getByRole('button', { name: PROBE_BUTTON })).toBeDisabled();
  expect(saves).toHaveLength(0);
  await page.getByRole('button', { name: 'Save Draft' }).click();
  await expect.poll(() => saves.length).toBe(1);
  expect(saves[0].body).toEqual({
    lock_version: 0,
    candidate: {
      prompt_text: syntheticDraftDefinitions.architect.prompt_text,
      model: { endpoint_name: syntheticNewerModelEndpoint.name, ...SEED_MODEL },
    },
  });
  await expect(architectNavStatus(page)).toContainText('Needs test');

  const probe = panel.getByRole('button', { name: PROBE_BUTTON });
  await expect(probe).toBeEnabled();
  await probe.click();
  await expect(probeResultRegion(page)).toContainText(PROBE_SUCCEEDED_TEXT);
  await expect(probeResultRegion(page))
    .toContainText(probeIdentityText(syntheticNewerModelEndpoint.name, 'd'.repeat(64), 1));
  expect(probes.raw).toEqual(['{"lock_version":1}']);
  expect(probes.posts.map((post) => post.agentKey)).toEqual(['architect']);
  expect(saves).toHaveLength(1);
  expect(reads).toHaveLength(2);
  expectBareCatalogReads(reads);
  await expect(architectNavStatus(page)).toContainText('Needs test');
  await expect.poll(workbenchRequestCount).toBe(1);
});

test('model endpoint manual custom name: an exact name absent from discovery saves only the five leaves, is retained, then probes', async ({ page }) => {
  const manual = 'Team Exact Endpoint 9';
  await installExactIdentityMock(page);
  const workbenchRequestCount = await installWorkbenchMock(page);
  const reads = await installCatalogMock(page, (route) => fulfillJson(route, 200, syntheticModelEndpointDiscovery()));
  const saves = await installSaveMock(page, (route, save) => fulfillJson(route, 200, saveSuccessFor(save)));
  const rawSaves: string[] = [];
  page.on('request', (request) => {
    if (request.method() === 'PUT') rawSaves.push(request.postData() ?? '');
  });
  const probes = await installProbeMock(page, (route) => fulfillJson(route, 200, syntheticProbeSuccess({
    endpoint_name: manual,
    candidate_hash: 'd'.repeat(64),
    lock_version: 1,
  })));
  await openWorkbench(page);
  await page.getByRole('tab', { name: 'Model' }).click();
  const panel = modelTabPanel(page);
  await expect(panel.getByRole('radio')).toHaveCount(syntheticSystemModelEndpoints.length);
  await expect(panel.getByRole('radio', { name: manual })).toHaveCount(0);

  await page.getByRole('textbox', { name: 'Custom endpoint name' }).fill(manual);
  await expect(panel.getByRole('radio', { checked: true })).toHaveCount(0);
  await page.getByRole('button', { name: 'Save Draft' }).click();
  await expect.poll(() => saves.length).toBe(1);

  const body = saves[0].body;
  expect(Object.keys(body).sort()).toEqual(['candidate', 'lock_version']);
  expect(Object.keys(body.candidate).sort()).toEqual(['model', 'prompt_text']);
  expect(Object.keys(body.candidate.model).sort()).toEqual(['endpoint_name', 'max_tokens', 'temperature', 'top_p']);
  expect(body).toEqual({
    lock_version: 0,
    candidate: {
      prompt_text: syntheticDraftDefinitions.architect.prompt_text,
      model: { endpoint_name: manual, ...SEED_MODEL },
    },
  });
  await expect.poll(() => rawSaves.length).toBe(1);
  for (const forbidden of [
    '"display_name"', '"docs"', '"description"', '"items"', '"name"', '"host"', '"token"',
    '"task"', '"provider"', '"url"', 'http', '://',
    ...syntheticSystemModelEndpoints.flatMap((item) => [item.display_name, item.description, item.docs])
      .filter((value): value is string => value !== null),
  ]) {
    expect(rawSaves[0]).not.toContain(forbidden);
  }

  // Exact retention after success: the name, the lock and the status.
  await expect(architectNavStatus(page)).toContainText('Needs test');
  await expect(page.getByRole('textbox', { name: 'Custom endpoint name' })).toHaveValue(manual);
  await expect(page.getByText('Lock version').locator('..')).toContainText('Lock version1');

  await panel.getByRole('button', { name: PROBE_BUTTON }).click();
  await expect(probeResultRegion(page)).toContainText(probeIdentityText(manual, 'd'.repeat(64), 1));
  expect(probes.raw).toEqual(['{"lock_version":1}']);
  expect(saves).toHaveLength(1);
  expectBareCatalogReads(reads);
  await expect.poll(workbenchRequestCount).toBe(1);
});

test('model endpoint manual server-validation failure: a typed endpoint issue keeps the whole unsaved form, and the corrected name retries through the same PUT without remount', async ({ page }) => {
  const missing = 'Team Missing Endpoint';
  const corrected = 'Team Found Endpoint';
  await installExactIdentityMock(page);
  const workbenchRequestCount = await installWorkbenchMock(page);
  const saves = await installSaveMock(page, (route, save, call) => (call === 0
    ? fulfillJson(route, 422, {
      code: 'invalid_draft',
      errors: [{
        field: 'candidate.model.endpoint_name',
        code: 'endpoint_unknown',
        message: 'Endpoint name was not found.',
      }],
    })
    : fulfillJson(route, 200, saveSuccessFor(save))));
  const probes = await installProbeMock(page, (route) => fulfillJson(route, 200, syntheticProbeSuccess({
    endpoint_name: corrected,
    candidate_hash: 'd'.repeat(64),
    lock_version: 1,
  })));
  await openWorkbench(page);
  await page.getByRole('textbox', { name: 'Prompt text' }).fill('Architect unsaved prompt');
  await page.getByRole('tab', { name: 'Model' }).click();
  const panel = modelTabPanel(page);
  const endpoint = page.getByRole('textbox', { name: 'Custom endpoint name' });
  await endpoint.fill(missing);
  await page.getByRole('spinbutton', { name: 'Temperature' }).fill('0.3');
  await page.getByRole('spinbutton', { name: 'Top-p' }).fill('0.5');
  // A DOM marker proves the same element survives: no remount, no reload.
  await endpoint.evaluate((element) => { element.setAttribute('data-remount-marker', 'kept'); });
  await page.getByRole('button', { name: 'Save Draft' }).click();
  await expect.poll(() => saves.length).toBe(1);

  await expect(endpoint).toHaveAccessibleDescription('Endpoint name was not found.');
  const alerts = panel.getByRole('alert');
  await expect(alerts).toHaveCount(1);
  await expect(alerts).toHaveText('Endpoint name was not found.');
  await expect(alerts).not.toContainText(missing);
  await expect(page.getByRole('region', { name: 'Server rejected this request' })).toHaveCount(0);
  await expect(endpoint).toHaveValue(missing);
  await expect(page.getByRole('spinbutton', { name: 'Temperature' })).toHaveValue('0.3');
  await expect(page.getByRole('spinbutton', { name: 'Maximum tokens' })).toHaveValue('60000');
  await expect(page.getByRole('spinbutton', { name: 'Top-p' })).toHaveValue('0.5');
  await expect(architectNavStatus(page)).toContainText('Unsaved');
  await expect(panel.getByRole('button', { name: PROBE_BUTTON })).toBeDisabled();
  await page.getByRole('tab', { name: 'Prompt' }).click();
  await expect(page.getByRole('textbox', { name: 'Prompt text' })).toHaveValue('Architect unsaved prompt');
  await page.getByRole('tab', { name: 'Model' }).click();

  await endpoint.fill(corrected);
  await expect(endpoint).not.toHaveAccessibleDescription('Endpoint name was not found.');
  await page.getByRole('button', { name: 'Save Draft' }).click();
  await expect.poll(() => saves.length).toBe(2);
  expect(saves[1].agentKey).toBe('architect');
  expect(saves[1].body).toEqual({
    lock_version: 0,
    candidate: {
      prompt_text: 'Architect unsaved prompt',
      model: { endpoint_name: corrected, temperature: 0.3, max_tokens: 60000, top_p: 0.5 },
    },
  });
  await expect(architectNavStatus(page)).toContainText('Needs test');
  await expect(endpoint).toHaveValue(corrected);
  await expect(endpoint).toHaveAttribute('data-remount-marker', 'kept');
  await expect(panel.getByRole('alert')).toHaveCount(0);

  await panel.getByRole('button', { name: PROBE_BUTTON }).click();
  await expect(probeResultRegion(page)).toContainText(probeIdentityText(corrected, 'd'.repeat(64), 1));
  expect(probes.raw).toEqual(['{"lock_version":1}']);
  await expect.poll(workbenchRequestCount).toBe(1);
});

for (const code of ['unsupported_structured_output', 'endpoint_probe_forbidden', 'structured_output_probe_failed'] as const) {
  test(`model endpoint probe ${code}: the sanitized result names the saved identity and offers Retry only when retryable`, async ({ page }) => {
    const { status, message, retryable } = STRUCTURED_OUTPUT_PROBE_FAILURES[code];
    await installExactIdentityMock(page);
    const workbenchRequestCount = await installWorkbenchMock(page);
    const saves = await installSaveMock(page, (route) => fulfillJson(route, 500, null));
    const probes = await installProbeMock(page, (route, _post, call) => (call === 0
      ? fulfillJson(route, status, syntheticProbeFailure(code))
      : fulfillJson(route, 200, syntheticProbeSuccess())));
    await openWorkbench(page);
    await page.getByRole('tab', { name: 'Model' }).click();
    const panel = modelTabPanel(page);
    await expect(panel.getByRole('radio')).toHaveCount(syntheticSystemModelEndpoints.length);
    const statusBefore = await architectNavStatus(page).textContent();

    await panel.getByRole('button', { name: PROBE_BUTTON }).click();
    const region = probeResultRegion(page);
    await expect(region.getByRole('alert')).toHaveText(message);
    await expect(region).toContainText(probeIdentityText(SEED_MODEL_ENDPOINT_NAME, SEED_CANDIDATE_HASH, 0));
    await expect(region).not.toContainText(PROBE_SUCCEEDED_TEXT);
    expect(await architectNavStatus(page).textContent()).toBe(statusBefore);
    await expect(page.getByRole('textbox', { name: 'Custom endpoint name' })).toHaveValue(SEED_MODEL_ENDPOINT_NAME);
    expect(probes.raw).toEqual(['{"lock_version":0}']);

    const retry = region.getByRole('button', { name: PROBE_RETRY_BUTTON });
    if (!retryable) {
      await expect(retry).toHaveCount(0);
      await expect(page.getByRole('button', { name: /retry/i })).toHaveCount(0);
      await expect(panel.getByRole('button', { name: PROBE_BUTTON })).toBeEnabled();
      expect(probes.posts).toHaveLength(1);
    } else {
      await retry.click();
      await expect(region).toContainText(PROBE_SUCCEEDED_TEXT);
      await expect(region.getByRole('alert')).toHaveCount(0);
      expect(probes.raw).toEqual(['{"lock_version":0}', '{"lock_version":0}']);
    }
    expect(saves).toHaveLength(0);
    await expect.poll(workbenchRequestCount).toBe(1);
  });
}

test('model endpoint empty discovery says so, keeps the saved seed, and still probes it', async ({ page }) => {
  await installExactIdentityMock(page);
  await installWorkbenchMock(page);
  const reads = await installCatalogMock(page, (route) => fulfillJson(route, 200, { items: [] }));
  const probes = await installProbeMock(page, (route) => fulfillJson(route, 200, syntheticProbeSuccess()));
  await openWorkbench(page);
  await page.getByRole('tab', { name: 'Model' }).click();
  const panel = modelTabPanel(page);
  await expect(panel).toContainText(EMPTY_DISCOVERY);
  await expect(panel.getByRole('radiogroup')).toHaveCount(0);
  await expect(panel.getByRole('alert')).toHaveCount(0);
  await expect(page.getByRole('textbox', { name: 'Custom endpoint name' })).toHaveValue(SEED_MODEL_ENDPOINT_NAME);

  await panel.getByRole('button', { name: PROBE_BUTTON }).click();
  await expect(probeResultRegion(page))
    .toContainText(probeIdentityText(SEED_MODEL_ENDPOINT_NAME, SEED_CANDIDATE_HASH, 0));
  expect(probes.raw).toEqual(['{"lock_version":0}']);
  expectBareCatalogReads(reads);
});

test('model endpoint URL rejection shows the table message and sends zero PUT and zero probe', async ({ page }) => {
  await installExactIdentityMock(page);
  await installWorkbenchMock(page);
  const saves = await installSaveMock(page, (route) => fulfillJson(route, 500, null));
  const probes = await installProbeMock(page, (route) => fulfillJson(route, 200, syntheticProbeSuccess()));
  await openWorkbench(page);
  await page.getByRole('tab', { name: 'Model' }).click();
  const panel = modelTabPanel(page);
  await expect(panel.getByRole('radio')).toHaveCount(syntheticSystemModelEndpoints.length);

  for (const value of [
    'https://example.cloud.databricks.com/serving-endpoints/x/invocations',
    'serving-endpoints/../secrets',
    'x?token=abc',
  ]) {
    const endpoint = page.getByRole('textbox', { name: 'Custom endpoint name' });
    await endpoint.fill(value);
    await expect(endpoint).toHaveAccessibleDescription(URL_NOT_ALLOWED);
    await expect(panel.getByRole('alert')).toHaveText(URL_NOT_ALLOWED);
    await expect(endpoint).toHaveValue(value);
    await expect(page.getByRole('button', { name: 'Save Draft' })).toBeDisabled();
    await expect(panel.getByRole('button', { name: PROBE_BUTTON })).toBeDisabled();
    await page.getByRole('button', { name: 'Save Draft' }).click({ force: true });
    await panel.getByRole('button', { name: PROBE_BUTTON }).click({ force: true });
  }
  await page.waitForTimeout(200);
  expect(saves).toHaveLength(0);
  expect(probes.posts).toHaveLength(0);
});

test('model endpoint catalogue 503 is an alert that recovers through Refresh models without remount', async ({ page }) => {
  await installExactIdentityMock(page);
  const workbenchRequestCount = await installWorkbenchMock(page);
  const reads = await installCatalogMock(page, (route, call) => (call === 0
    ? fulfillJson(route, 503, MODEL_ENDPOINT_DISCOVERY_UNAVAILABLE)
    : fulfillJson(route, 200, syntheticModelEndpointDiscovery())));
  const saves = await installSaveMock(page, (route) => fulfillJson(route, 500, null));
  await openWorkbench(page);
  await page.getByRole('tab', { name: 'Model' }).click();
  const panel = modelTabPanel(page);
  await expect(panel.getByRole('alert')).toContainText(MODEL_ENDPOINT_DISCOVERY_UNAVAILABLE.message);
  await expect(panel.getByRole('radiogroup')).toHaveCount(0);
  await expect(panel).not.toContainText(EMPTY_DISCOVERY);
  await expect(page.getByRole('textbox', { name: 'Custom endpoint name' })).toHaveValue(SEED_MODEL_ENDPOINT_NAME);
  const search = panel.getByRole('searchbox', { name: 'Search discovered models' });
  await search.fill('opus');
  await search.evaluate((element) => { element.setAttribute('data-remount-marker', 'kept'); });

  await panel.getByRole('button', { name: 'Refresh models' }).click();
  await expect(panel.getByRole('radio', { name: SEED_MODEL_ENDPOINT_NAME, exact: true })).toBeChecked();
  await expect(panel.getByRole('alert')).toHaveCount(0);
  await expect(search).toHaveAttribute('data-remount-marker', 'kept');
  await expect(search).toHaveValue('opus');
  expect(reads).toHaveLength(2);
  expectBareCatalogReads(reads);
  expect(saves).toHaveLength(0);
  await expect.poll(workbenchRequestCount).toBe(1);
});

// ============================================================
// #267 Task 6 — Agent Test Cases, test runs, and the Input/Compare/Checks views
// ============================================================

const RUN_TEST_CASE = 'Run test case';
const RUN_BASELINE = 'Run published baseline';

interface CapturedAgentTestRequest {
  method: string;
  path: string;
  raw: string | null;
}

/**
 * Routes every #267 request by URL and method (C38), registered after the tripwire so
 * it wins. A request no responder answers is recorded as unrouted and aborted.
 */
async function installAgentTestMock(
  page: Page,
  responders: {
    listCases?: (route: Route, call: number) => Promise<void> | void;
    createCase?: (route: Route, call: number) => Promise<void> | void;
    retireCase?: (route: Route, call: number) => Promise<void> | void;
    candidateRun?: (route: Route, call: number) => Promise<void> | void;
    baselineRun?: (route: Route, call: number) => Promise<void> | void;
  },
) {
  const requests: CapturedAgentTestRequest[] = [];
  const counts: Record<string, number> = {};
  await page.route(isAgentTestPath, async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    const method = request.method();
    requests.push({ method, path: `${url.pathname}${url.search}`, raw: request.postData() });
    const key = method === 'GET' && /\/test-cases$/.test(url.pathname) ? 'listCases'
      : method === 'POST' && /\/test-cases$/.test(url.pathname) ? 'createCase'
        : method === 'DELETE' && /\/test-cases\/\d+$/.test(url.pathname) ? 'retireCase'
          : method === 'POST' && /\/draft\/[a-z_]+\/test-runs$/.test(url.pathname) ? 'candidateRun'
            : method === 'POST' && /\/published\/[a-z_]+\/test-runs$/.test(url.pathname) ? 'baselineRun'
              : null;
    const respond = key === null ? undefined : responders[key as keyof typeof responders];
    if (!respond || key === null) {
      unroutedAgentTestRequests.push(`${method} ${request.url()}`);
      await route.abort();
      return;
    }
    const call = counts[key] ?? 0;
    counts[key] = call + 1;
    await respond(route, call);
  });
  return requests;
}

function testingAside(page: Page) {
  return page.getByRole('complementary', { name: 'Isolated testing' });
}

async function loadAgentTestCases(page: Page) {
  await testingAside(page).getByRole('button', { name: 'Load Agent Test Cases' }).click();
  await expect(testingAside(page).getByRole('combobox', { name: 'Agent Test Cases' })).toBeVisible();
}

async function openTestView(page: Page, name: 'Input' | 'Compare' | 'Checks') {
  await testingAside(page).getByRole('tab', { name, exact: true }).click();
  return testingAside(page).getByRole('tabpanel', { name, exact: true });
}

function runBodies(requests: CapturedAgentTestRequest[], kind: 'draft' | 'published') {
  return requests
    .filter((request) => request.method === 'POST' && request.path.includes(`/${kind}/`))
    .map((request) => request.raw);
}

test('Agent Test Cases: add a case, run it against the saved candidate, then read Compare and Checks', async ({ page }) => {
  await installExactIdentityMock(page);
  const workbenchRequests = await installWorkbenchMock(page);
  const created = syntheticAgentTestCase({ id: 202, name: 'Architect board summary', is_required: false });
  const requests = await installAgentTestMock(page, {
    listCases: (route) => fulfillJson(route, 200, syntheticAgentTestCaseList()),
    createCase: (route) => fulfillJson(route, 201, created),
    candidateRun: (route) => fulfillJson(route, 201, syntheticTestRunEvidence({
      test_case_id: 202,
      assembled_prompt: 'Assembled <b>prompt</b> for the board summary.',
      execution_status: 'incomplete',
      deterministic_checks_passed: false,
      deterministic_check_results: [
        { name: 'execution', passed: true, message: null, issues: [] },
        { name: 'output_contract', passed: false, message: 'The output omitted a required field.', issues: [{ code: 'missing', field: 'title' }] },
      ],
    })),
  });
  const saves = await installSaveMock(page, (route) => fulfillJson(route, 500, null));
  await openWorkbench(page);
  await expect(page.getByRole('heading', { name: 'Graph Version 1' })).toBeVisible();
  // Mounting reads nothing for Agent Test Cases.
  expect(requests).toHaveLength(0);

  await loadAgentTestCases(page);
  const aside = testingAside(page);
  await expect(aside).toContainText('Synthetic data only: never enter real customer, personal or confidential data.');
  await expect(aside).toContainText('add the new case first and then retire the old one');
  await aside.getByRole('button', { name: 'Add test case' }).click();
  await aside.getByRole('textbox', { name: 'Test case name' }).fill('Architect board summary');
  await aside.getByRole('textbox', { name: 'Synthetic payload (JSON)' })
    .fill('{"user_request": "Summarise a fictional board meeting."}');
  await aside.getByRole('button', { name: 'Save test case' }).click();
  await expect(aside.getByRole('combobox', { name: 'Agent Test Cases' })).toHaveValue('202');

  await aside.getByRole('button', { name: RUN_TEST_CASE }).click();
  const compare = await openTestView(page, 'Compare');
  const evidence = compare.getByRole('region', { name: 'Test case evidence' });
  await expect(evidence).toContainText('Synthetic candidate structured title');
  await expect(evidence).toContainText('Baseline not recorded');
  await expect(evidence).toContainText('Input tokens: not reported');
  const input = await openTestView(page, 'Input');
  await expect(input).toContainText('Assembled <b>prompt</b> for the board summary.');
  await expect(input.locator('b')).toHaveCount(0);
  await expect(input.getByRole('region', { name: 'Model payload sent' })).not.toContainText('synthetic-session-0001');
  const checks = await openTestView(page, 'Checks');
  await expect(checks).toContainText('Deterministic checks failed');
  await expect(checks.locator('tr[data-check-state="failed"]')).toContainText('output_contract');
  await expect(checks.locator('tr[data-check-state="failed"]')).toContainText('Failed');

  expect(requests.map((request) => `${request.method} ${request.path}`)).toEqual([
    'GET /api/admin/agent-definitions/test-cases?agent_key=architect',
    'POST /api/admin/agent-definitions/test-cases',
    'POST /api/admin/agent-definitions/draft/architect/test-runs',
  ]);
  expect(JSON.parse(requests[1].raw ?? '')).toEqual({
    agent_key: 'architect',
    name: 'Architect board summary',
    synthetic_payload: { user_request: 'Summarise a fictional board meeting.' },
    assembly_context: { design_system_active: false },
    is_required: false,
  });
  expect(runBodies(requests, 'draft')).toEqual(['{"test_case_id":202,"lock_version":0}']);
  expect(saves).toHaveLength(0);
  await expect(page.getByText('Lock version').locator('..')).toContainText('Lock version0');
  await expect.poll(workbenchRequests).toBe(1);
});

test('Agent Test Cases: a published-baseline rerun is shown not approved, and the next candidate run compares against it', async ({ page }) => {
  await installExactIdentityMock(page);
  await installWorkbenchMock(page);
  const requests = await installAgentTestMock(page, {
    listCases: (route) => fulfillJson(route, 200, syntheticAgentTestCaseList()),
    baselineRun: (route) => fulfillJson(route, 201, syntheticTestRunEvidence({
      run_id: 777,
      run_kind: 'published_baseline',
      candidate_structured_output: { title: 'Published rerun title' },
    })),
    candidateRun: (route) => fulfillJson(route, 201, syntheticTestRunEvidence({
      run_id: 778,
      baseline_raw_output: { title: 'Published rerun raw title' },
      baseline_structured_output: { title: 'Published rerun title' },
    })),
  });
  await openWorkbench(page);
  await loadAgentTestCases(page);
  const aside = testingAside(page);

  await aside.getByRole('button', { name: RUN_BASELINE }).click();
  const compare = await openTestView(page, 'Compare');
  const baseline = compare.getByRole('region', { name: 'Published baseline evidence' });
  await expect(baseline).toContainText('Published rerun title');
  await expect(baseline).toContainText('not approved');
  await expect(compare.getByRole('region', { name: 'Test case evidence' })).toContainText('No run yet');

  await aside.getByRole('button', { name: RUN_TEST_CASE }).click();
  const evidence = compare.getByRole('region', { name: 'Test case evidence' });
  await expect(evidence).toContainText('Run 778');
  await expect(evidence).toContainText('Published baseline (not approved)');
  await expect(evidence).toContainText('Published rerun raw title');
  await expect(evidence).not.toContainText('Baseline not recorded');
  expect(runBodies(requests, 'published')).toEqual(['{"test_case_id":101}']);
  expect(runBodies(requests, 'draft')).toEqual(['{"test_case_id":101,"lock_version":0}']);
});

test('Agent Test Cases: a stale_draft 409 reconciles through Reload server, and the explicit rerun sends the adopted lock', async ({ page }) => {
  const conflict = syntheticNullCandidateConflict(0, 1);
  conflict.server.definitions.architect = {
    ...conflict.server.definitions.architect,
    prompt_text: 'Architect changed on the server',
    candidate_hash: 'd'.repeat(64),
  };
  await installExactIdentityMock(page);
  await installWorkbenchMock(page);
  const requests = await installAgentTestMock(page, {
    listCases: (route) => fulfillJson(route, 200, syntheticAgentTestCaseList()),
    candidateRun: (route, call) => (call === 0
      ? fulfillJson(route, 409, conflict)
      : fulfillJson(route, 201, syntheticTestRunEvidence({ candidate_hash: 'd'.repeat(64) }))),
  });
  const saves = await installSaveMock(page, (route) => fulfillJson(route, 500, null));
  await openWorkbench(page);
  await loadAgentTestCases(page);
  const aside = testingAside(page);

  await aside.getByRole('button', { name: RUN_TEST_CASE }).click();
  const region = page.getByRole('region', { name: 'Draft changed on the server' });
  await expect(region).toContainText('Expected lock 0; Current lock 1');
  await expect(aside.getByRole('alert')).toContainText('The draft changed on the server.');
  await expect(aside.getByRole('button', { name: RUN_TEST_CASE })).toBeDisabled();
  await expect(aside).toContainText("Save this role's edits before running a test case.");

  await region.getByRole('button', { name: 'Reload server' }).click();
  await expect(page.getByRole('textbox', { name: 'Prompt text' })).toHaveValue('Architect changed on the server');
  await aside.getByRole('button', { name: RUN_TEST_CASE }).click();
  const compare = await openTestView(page, 'Compare');
  await expect(compare.getByRole('region', { name: 'Test case evidence' })).toContainText('Synthetic candidate structured title');
  await expect(aside.getByRole('alert')).toHaveCount(0);
  expect(runBodies(requests, 'draft')).toEqual([
    '{"test_case_id":101,"lock_version":0}',
    '{"test_case_id":101,"lock_version":1}',
  ]);
  expect(saves).toHaveLength(0);
});

test('Agent Test Cases: a 503 test_run_unavailable is a contained retryable alert that recovers only through an explicit retry', async ({ page }) => {
  await installExactIdentityMock(page);
  await installWorkbenchMock(page);
  const requests = await installAgentTestMock(page, {
    listCases: (route) => fulfillJson(route, 200, syntheticAgentTestCaseList()),
    candidateRun: (route, call) => (call === 0
      ? fulfillJson(route, 503, syntheticTestRunUnavailable())
      : fulfillJson(route, 201, syntheticTestRunEvidence())),
  });
  await openWorkbench(page);
  await loadAgentTestCases(page);
  const aside = testingAside(page);

  await aside.getByRole('button', { name: RUN_TEST_CASE }).click();
  await expect(aside.getByRole('alert')).toContainText('Test run storage is temporarily unavailable. Retry the request.');
  await expect(aside.getByRole('button', { name: RUN_TEST_CASE })).toBeEnabled();
  const compare = await openTestView(page, 'Compare');
  await expect(compare).toContainText('No run yet');
  expect(runBodies(requests, 'draft')).toHaveLength(1);

  await aside.getByRole('button', { name: RUN_TEST_CASE }).click();
  await expect(compare.getByRole('region', { name: 'Test case evidence' })).toContainText('Synthetic candidate structured title');
  await expect(aside.getByRole('alert')).toHaveCount(0);
  expect(runBodies(requests, 'draft')).toEqual([
    '{"test_case_id":101,"lock_version":0}',
    '{"test_case_id":101,"lock_version":0}',
  ]);
});

test('Agent Test Cases: every control stays inside the guard, and no #266 or #267 locator resolves two controls', async ({ page }) => {
  await installExactIdentityMock(page);
  await installWorkbenchMock(page);
  await installAgentTestMock(page, {
    listCases: (route) => fulfillJson(route, 200, syntheticAgentTestCaseList()),
    candidateRun: (route) => fulfillJson(route, 201, syntheticTestRunEvidence()),
  });
  await openWorkbench(page);
  await loadAgentTestCases(page);
  const aside = testingAside(page);
  await aside.getByRole('button', { name: RUN_TEST_CASE }).click();
  await openTestView(page, 'Compare');
  await expect(aside.getByRole('region', { name: 'Test case evidence' })).toContainText('Synthetic candidate structured title');
  await aside.getByRole('button', { name: 'Retire test case' }).click();
  await page.getByRole('tab', { name: 'Model' }).click();
  await expect(page.getByRole('radiogroup', { name: 'Discovered models' })).toBeVisible();

  const panel = page.getByRole('tabpanel', { name: 'Agent Definitions' });
  const names = await panel.locator('button, a').evaluateAll((controls) => controls.map((control) => (
    `${control.getAttribute('aria-label') ?? ''} ${control.textContent ?? ''} ${control.getAttribute('title') ?? ''}`
  )));
  for (const name of [RUN_TEST_CASE, RUN_BASELINE, 'Confirm retire', 'Keep test case', 'Refresh test cases']) {
    expect(names.some((candidate) => candidate.includes(name))).toBe(true);
  }
  for (const name of names) expect(forbidsActionName(name)).toBe(false);

  // Playwright names are case-insensitive substrings: each must still resolve one control.
  for (const name of [PROBE_BUTTON, 'Refresh models', RUN_TEST_CASE, RUN_BASELINE, 'Refresh test cases', 'Add test case']) {
    await expect(page.getByRole('button', { name })).toHaveCount(1);
  }
  await expect(page.getByRole('searchbox', { name: 'Search discovered models' })).toHaveCount(1);
  await expect(page.getByRole('textbox', { name: 'Custom endpoint name' })).toHaveCount(1);
  await expect(page.getByRole('region', { name: 'Test case evidence' })).toHaveCount(1);
  await expect(page.getByRole('region', { name: PROBE_RESULT_REGION })).toHaveCount(0);
});
