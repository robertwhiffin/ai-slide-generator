/**
 * The administrator's Graph Configuration journey over the RECORDED HTTP contract
 * (#271 Task 10, AC9).
 *
 * Every `/api/admin/agent-definitions/**` answer below is a real response recorded by
 * Task 6's journey over PostgreSQL and the shipped routers
 * (`fixtures/graphLifecycleContract.json`); `tests/unit/test_graph_lifecycle_playwright
 * _contract.py` validates each against its Pydantic model. The page must drive that
 * recording exactly: its PUT and POST requests are served strictly in recorded order,
 * their bodies deep-equal the recorded requests, and any request outside the contract
 * fails the journey. So neither the page nor the backend can drift from the other.
 *
 * One browser context carries the whole journey (one replay cursor); a second page in
 * it plays the other admin whose save goes stale (S03).
 *
 * Run: cd frontend && npx playwright test tests/e2e/graph-release-admin-journey.spec.ts --project=chromium --workers=1
 */
import { expect, test, type Browser, type BrowserContext, type Locator, type Page } from '@playwright/test';
import {
  adminExchangeIds,
  exchange,
  installContract,
  loadContract,
  type ContractExchange,
  type RecordedRequests,
} from '../fixtures/graphLifecycleContract';
import { sweepForbiddenActionNames } from '../fixtures/forbiddenActionHelpers';
import { ALLOWED_ACTION_NAMES } from '../fixtures/forbiddenActionNames';

const contract = loadContract();
const ADMIN_IDS = adminExchangeIds(contract);
const recorded = (id: string): ContractExchange => exchange(contract, id);

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
const SONNET = 'system.ai.claude-sonnet-4-5';
/** AC5: no control of the workbench offers tools. */
const TOOLS = /\btools?\b/i;

interface SaveRequest {
  lock_version: number;
  candidate: {
    prompt_text: string;
    model: { endpoint_name: string; temperature: number; max_tokens: number; top_p: number };
    assembly_rules?: { format_version: 2; custom_blocks: { block_id: string; text: string }[] };
  };
}

const request = (id: string) => recorded(id).request as SaveRequest;

let context: BrowserContext;
let page: Page;
let other: Page; // the second admin, whose fixer save is stale
let served: RecordedRequests;

async function openWorkbench(target: Page) {
  await target.goto('/admin');
  await target.getByRole('tab', { name: 'Agent Definitions', exact: true }).click();
  await expect(target.getByRole('heading', { name: 'Graph Version 1', exact: true })).toBeVisible();
}

const nav = (target: Page) => target.getByRole('navigation', { name: 'Graph nodes', exact: true });
const panel = (target: Page) => target.getByRole('tabpanel', { name: 'Agent Definitions', exact: true });
const lock = (target: Page) => target.getByText('Lock version', { exact: true }).locator('..');

async function selectRole(target: Page, displayName: string) {
  await nav(target).getByRole('button', { name: displayName, exact: true }).click();
  await expect(target.getByRole('heading', { level: 3, name: displayName, exact: true })).toBeVisible();
}

async function openTab(target: Page, name: 'Prompt' | 'Model' | 'Output Schema' | 'Assembly') {
  await target.getByRole('tab', { name, exact: true }).click();
}

async function expectStatus(displayName: string, status: string) {
  await expect(nav(page).getByRole('button', { name: displayName, exact: true }))
    .toHaveAccessibleDescription(status);
}

async function expectLock(target: Page, value: number) {
  await expect(lock(target)).toContainText(`Lock version${value}`);
}

async function saveDraft(target: Page) {
  await target.getByRole('button', { name: 'Save Draft', exact: true }).click();
}

/** Every control name the panel shows: no forbidden action (#260) and no tools (AC5). */
async function sweep(target: Page) {
  const names = await sweepForbiddenActionNames(panel(target));
  expect(names.filter((name) => TOOLS.test(name))).toEqual([]);
  return names;
}

function testing(): Locator {
  return page.getByRole('complementary', { name: 'Isolated testing', exact: true });
}

/** The selected role's candidate-run verdict controls (the Compare view). */
async function verdict(displayName: string): Promise<Locator> {
  await selectRole(page, displayName);
  await testing().getByRole('tab', { name: 'Compare', exact: true }).click();
  return testing().getByRole('region', { name: 'Candidate run verdict', exact: true });
}

async function runRequiredCase(displayName: string, agentKey: string) {
  await selectRole(page, displayName);
  const aside = testing();
  const load = aside.getByRole('button', { name: 'Load Agent Test Cases', exact: true });
  if (await load.count() > 0) await load.click();
  const caseId = (recorded(`S07-post-run-${agentKey}`).request as { test_case_id: number }).test_case_id;
  await aside.getByRole('combobox', { name: 'Agent Test Cases', exact: true }).selectOption(String(caseId));
  await aside.getByRole('button', { name: 'Run test case', exact: true }).click();
}

async function newJourneyContext(browser: Browser): Promise<BrowserContext> {
  return browser.newContext({
    baseURL: 'http://localhost:3000',
    storageState: {
      cookies: [],
      origins: [{
        origin: 'http://localhost:3000',
        localStorage: [{ name: 'tellr-app-tour-completed', value: 'true' }],
      }],
    },
  });
}

test.describe.serial('the administrator journey over the recorded lifecycle contract', () => {
  test.beforeAll(async ({ browser }) => {
    context = await newJourneyContext(browser);
    served = await installContract(context, ADMIN_IDS);
    page = await context.newPage();
    other = await context.newPage();
  });

  test.afterAll(async () => {
    await context.close();
  });

  test('1. the workbench shows seven roles and a read-only Foreman, and offers no forbidden action', async () => {
    await openWorkbench(page);
    await expect(nav(page).getByRole('button')).toHaveText(NODE_ORDER);
    await expect(lock(page)).toContainText('Lock version0');
    for (const name of ['Architect', 'Builder', 'Fixer']) await expectStatus(name, 'Clean');

    await selectRole(page, 'Foreman');
    await expect(page.getByTestId('definition-pane')).toContainText('Deterministic');
    await expect(testing()).toContainText('Foreman is deterministic and has no Agent Test Cases.');
    await expect(page.getByRole('button', { name: 'Save Draft', exact: true })).toHaveCount(0);
    await sweep(page);

    await selectRole(page, 'Architect');
    for (const tab of ['Prompt', 'Model', 'Output Schema', 'Assembly'] as const) {
      await openTab(page, tab);
      await sweep(page);
    }
    // #268 C35 and the controller ruling: the exemption list is still exactly eight.
    expect(ALLOWED_ACTION_NAMES).toHaveLength(8);

    // The other admin opens the same draft at lock 0.
    await openWorkbench(other);
    await selectRole(other, 'Fixer');
  });

  test('2. prompt and temperature edits save at the recorded lock, and a stale save offers recovery', async () => {
    const architect = request('S03-put-architect');
    await selectRole(page, 'Architect');
    await openTab(page, 'Prompt');
    await page.getByRole('textbox', { name: 'Prompt text', exact: true }).fill(architect.candidate.prompt_text);
    await openTab(page, 'Model');
    await page.getByRole('spinbutton', { name: 'Temperature', exact: true })
      .fill(String(architect.candidate.model.temperature));
    await saveDraft(page);
    await expectLock(page, 1);
    expect(served.requestBody('S03-put-architect')).toEqual(architect);
    await expectStatus('Architect', 'Needs test');

    const builder = request('S03-put-builder');
    await selectRole(page, 'Builder');
    await openTab(page, 'Prompt');
    await page.getByRole('textbox', { name: 'Prompt text', exact: true }).fill(builder.candidate.prompt_text);
    await saveDraft(page);
    await expectLock(page, 2);
    expect(served.requestBody('S03-put-builder')).toEqual(builder);

    // The other admin still holds lock 0: its fixer save is refused as stale.
    const stale = request('S03-put-fixer-stale');
    await openTab(other, 'Prompt');
    await other.getByRole('textbox', { name: 'Prompt text', exact: true }).fill(stale.candidate.prompt_text);
    await saveDraft(other);
    const conflict = other.getByRole('region', { name: 'Draft changed on the server', exact: true });
    await expect(conflict).toContainText('Expected lock 0; Current lock 2');
    await expect(conflict.getByRole('button', { name: 'Reload server', exact: true })).toBeVisible();
    await expect(conflict.getByRole('button', { name: 'Keep local', exact: true })).toBeVisible();
    expect(served.requestBody('S03-put-fixer-stale')).toEqual(stale);
    await conflict.getByRole('button', { name: 'Reload server', exact: true }).click();
    await expect(conflict).toHaveCount(0);
    await expectLock(other, 2);
    await other.close();
  });

  test('3. the builder schema is upgraded with diagnostic_notes, and the architect assembly gains a custom block', async () => {
    await selectRole(page, 'Builder');
    await openTab(page, 'Output Schema');
    const schema = page.getByRole('tabpanel', { name: 'Output Schema', exact: true });
    await schema.getByRole('button', { name: 'Schema Upgrade', exact: true }).click();
    await expectLock(page, 3);
    expect(served.requestBody('S04-post-builder-schema-contract-upgrade'))
      .toEqual(recorded('S04-post-builder-schema-contract-upgrade').request);
    await schema.getByRole('checkbox', { name: 'Select diagnostic_notes', exact: true }).click();
    await saveDraft(page);
    await expectLock(page, 4);
    expect(served.requestBody('S04-put-builder-overlay')).toEqual(recorded('S04-put-builder-overlay').request);

    await selectRole(page, 'Architect');
    await openTab(page, 'Assembly');
    const assembly = page.getByRole('tabpanel', { name: 'Assembly', exact: true });
    await assembly.getByRole('button', { name: 'Upgrade protected assembly', exact: true }).click();
    await expectLock(page, 5);
    expect(served.requestBody('S05-post-architect-protected-assembly-upgrade'))
      .toEqual(recorded('S05-post-architect-protected-assembly-upgrade').request);
    const block = request('S05-put-architect-custom-block').candidate.assembly_rules!.custom_blocks[0];
    await assembly.getByRole('button', { name: 'Add custom block After authored prompt', exact: true }).click();
    await assembly.getByRole('group', { name: 'Custom block 1 at After authored prompt', exact: true })
      .getByRole('textbox', { name: 'Block text', exact: true }).fill(block.text);
    await saveDraft(page);
    await expectLock(page, 6);
    // The page mints its own block id; every other byte is the recorded request.
    const sent = served.requestBody('S05-put-architect-custom-block') as SaveRequest;
    const sentBlocks = sent.candidate.assembly_rules!.custom_blocks;
    expect(sentBlocks).toHaveLength(1);
    expect(sentBlocks[0].block_id).toMatch(/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/);
    const withRecordedId = {
      ...sent,
      candidate: {
        ...sent.candidate,
        assembly_rules: { format_version: 2, custom_blocks: [{ ...sentBlocks[0], block_id: block.block_id }] },
      },
    };
    expect(withRecordedId).toEqual(request('S05-put-architect-custom-block'));
  });

  test('4. the fixer endpoint is chosen from the refreshed model catalog', async () => {
    await selectRole(page, 'Fixer');
    await openTab(page, 'Model');
    await page.getByRole('button', { name: 'Refresh models', exact: true }).click();
    await page.getByRole('radiogroup', { name: 'Discovered models', exact: true })
      .getByRole('radio', { name: SONNET, exact: true }).check();
    await saveDraft(page);
    await expectLock(page, 7);
    expect(served.requestBody('S06-put-fixer-endpoint')).toEqual(recorded('S06-put-fixer-endpoint').request);
  });

  test('5. each changed role runs its required case; builder is rejected, rerun and approved', async () => {
    for (const [name, key] of [['Architect', 'architect'], ['Builder', 'builder'], ['Fixer', 'fixer']] as const) {
      await expectStatus(name, 'Needs test');
      await runRequiredCase(name, key);
      await expectStatus(name, 'Awaiting review');
      expect(served.requestBody(`S07-post-run-${key}`)).toEqual(recorded(`S07-post-run-${key}`).request);
    }

    const rejected = await verdict('Builder');
    await rejected.getByRole('textbox', { name: 'Candidate run verdict notes', exact: true })
      .fill((recorded('S08-reject-builder').request as { notes: string }).notes);
    await rejected.getByRole('button', { name: 'Reject run', exact: true }).click();
    await expect(rejected).toContainText('Rejected by lifecycle-admin@example.com');
    expect(served.requestBody('S08-reject-builder')).toEqual(recorded('S08-reject-builder').request);
    // The recorded readiness after the rejection names builder's case `rejected`.
    await expectStatus('Builder', 'Test failed');

    for (const [name, key] of [['Architect', 'architect'], ['Fixer', 'fixer']] as const) {
      const approved = await verdict(name);
      await approved.getByRole('button', { name: 'Approve run', exact: true }).click();
      await expect(approved).toContainText('Approved by lifecycle-admin@example.com');
      await expectStatus(name, 'Approved');
      expect(served.requestBody(`S08-approve-${key}`)).toEqual(recorded(`S08-approve-${key}`).request);
    }

    await selectRole(page, 'Builder');
    await testing().getByRole('button', { name: 'Run test case', exact: true }).click();
    await expectStatus('Builder', 'Awaiting review');
    expect(served.requestBody('S08-post-rerun-builder')).toEqual(recorded('S08-post-rerun-builder').request);
    const rerun = await verdict('Builder');
    await expect(rerun).toContainText('No verdict recorded');
    await rerun.getByRole('button', { name: 'Approve run', exact: true }).click();
    await expectStatus('Builder', 'Approved');
    expect(served.requestBody('S09-approve-builder-rerun')).toEqual(recorded('S09-approve-builder-rerun').request);
  });

  test('6. Review & Publish shows Graph Version 2, recovers from a stale publish, and publishes', async () => {
    await page.getByRole('link', { name: 'Review & Publish', exact: true }).click();
    await expect(page).toHaveURL(/\/admin\/agent-definitions\/review$/);
    await expect(page.getByRole('heading', { level: 1, name: 'Review & Publish', exact: true })).toBeVisible();
    await expect(page.getByTestId('release-next-version')).toContainText('Next Graph Version: 2');

    await page.getByTestId('release-diff-tab').click();
    await expect(page.getByRole('region', { name: 'Architect diff', exact: true })
      .getByRole('list', { name: 'prompt_text', exact: true })).toBeVisible();

    const publish = recorded('S11-post-release').request as { lock_version: number; release_note: string };
    await page.getByTestId('release-note-input').fill(publish.release_note);
    const button = page.getByRole('button', { name: 'Publish Graph Version 2', exact: true });
    await button.click();
    const stale = page.getByTestId('release-stale-alert');
    await expect(stale).toBeVisible();
    await stale.getByRole('button', { name: 'Reload preview', exact: true }).click();
    await expect(stale).toHaveCount(0);

    await page.getByRole('button', { name: 'Publish Graph Version 2', exact: true }).click();
    await expect(page.getByTestId('release-success-panel')).toBeVisible();
    expect(served.requestBody('S11-post-release')).toEqual(publish);
  });

  test('7. Release History inspects Graph Version 1 and rolls back to it', async () => {
    await page.getByTestId('release-history-tab').click();
    const row = page.getByTestId('release-history-row-1');
    await row.getByRole('button', { name: 'Inspect this version', exact: true }).click();
    await expect(page.getByTestId('release-history-detail')).toBeVisible();
    await expect(page.getByTestId('release-comparison')).toBeVisible();

    await row.getByRole('button', { name: 'Roll back to this version', exact: true }).click();
    const preview = page.getByTestId('rollback-preview');
    await expect(preview.getByTestId('rollback-lineage')).toContainText('Graph Version 3 will restore Graph Version 1');
    const rollback = recorded('S15-post-rollback-1').request as { lock_version: number; release_note: string };
    await expect(preview.getByTestId('rollback-note-input')).toHaveValue(rollback.release_note);

    await preview.getByRole('button', { name: 'Confirm rollback', exact: true }).click();
    const stale = preview.getByTestId('rollback-stale-alert');
    await expect(stale).toBeVisible();
    await stale.getByRole('button', { name: 'Reload rollback preview', exact: true }).click();
    await expect(stale).toHaveCount(0);

    await page.getByTestId('rollback-preview').getByRole('button', { name: 'Confirm rollback', exact: true }).click();
    const success = page.getByTestId('rollback-success-panel');
    await expect(success).toContainText('Graph Version 3 restores Graph Version 1');
    expect(served.requestBody('S15-post-rollback-1')).toEqual(rollback);
  });

  test('8. the page sent exactly the recorded mutations, in order, and nothing outside the contract', async () => {
    expect(served.unmatched).toEqual([]);
    const recordedMutations = ADMIN_IDS.filter((id) => recorded(id).method !== 'GET');
    expect(served.mutations.map((mutation) => mutation.id)).toEqual(recordedMutations);
    // Reads the recording cannot answer from the page's own point in the journey, each
    // pinned (C1). Ahead of their first recording: each page's boot readiness (twice,
    // StrictMode) is served lock 1's, which the reducer drops as another lock's; the
    // Model tab's first catalog read (step 1) is S06's; and each role's stored-run
    // list, read when its case is selected, is served the list recorded after its run.
    expect(served.lookahead).toEqual([
      'S03-readiness-after-architect',
      'S03-readiness-after-architect',
      'S06-get-model-endpoints',
      'S03-readiness-after-architect',
      'S03-readiness-after-architect',
      'S07-get-runs-architect',
      'S07-get-runs-builder',
      'S07-get-runs-fixer',
    ]);
    // Behind a mutation already sent (the journey never re-read them): the other
    // admin's readiness re-read after its stale save, the preview reloaded after the stale publish and refetched after the publish, the rollback
    // preview reloaded after the stale rollback, and the history and preview refetched
    // after the rollback. The steps assert only the POST responses' panels there.
    expect(served.carried).toEqual([
      'S03-readiness-after-builder',
      'S10-get-release-preview',
      'S10-get-release-preview',
      'S15-get-rollback-preview-1',
      'S14-get-releases',
      'S10-get-release-preview',
    ]);
  });
});
