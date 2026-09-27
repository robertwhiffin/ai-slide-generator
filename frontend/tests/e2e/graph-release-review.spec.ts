/**
 * Review & Publish page browser tests (#269 Task 7).
 *
 * Scenarios:
 *   (a) Two changed roles, all approved; diff tab shows added/removed prompt lines.
 *   (b) 409 not-ready disables Publish and names the gap (including no_required_case mock).
 *   (c) 409 stale keeps the note; Reload preview issues exactly 1 GET and 0 POSTs.
 *   (d) 200 success shows panel, exactly one preview refetch shows rebased draft;
 *       workbench Review & Publish link from /admin navigates to this page.
 *   (e) 422 blank-note response renders beside the note input.
 *   (f) Forbidden-action sweep still flags Publish draft, Release history, Rollback release.
 *
 * Run: cd frontend && npx playwright test tests/e2e/graph-release-review.spec.ts --project=chromium --workers=1
 */
import { test, expect, Page } from '@playwright/test';
import type { ReleasePreviewResponse } from '../../src/api/agentDefinitions';
import {
  RELEASE_ARCHITECT_CANDIDATE_HASH,
  RELEASE_NOTE_BLANK_ERROR,
  syntheticAgentDefinitionWorkbench,
  syntheticAgentReadiness,
  syntheticChangedDefinition,
  syntheticDraftReadinessBody,
  syntheticPublicationInvalid,
  syntheticPublicationNotReady,
  syntheticPublishSuccess,
  syntheticPublishedReleasePreview,
  syntheticReleasePreview,
  syntheticStalePublication,
  syntheticTestCaseReadiness,
} from '../fixtures/mocks';
import { forbidsActionName } from '../fixtures/forbiddenActionNames';

const PREVIEW_URL = '**/api/admin/agent-definitions/release-preview';
const PUBLISH_URL = '**/api/admin/agent-definitions/releases';
const WORKBENCH_URL = '**/api/admin/agent-definitions/workbench';
const READINESS_URL = '**/api/admin/agent-definitions/readiness';

// ---------------------------------------------------------------------------
// Shared helpers
// ---------------------------------------------------------------------------

/** Install setup/status and admin identity mocks. */
async function installIdentityMock(page: Page) {
  await page.route('**/api/setup/status', (route) =>
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ configured: true }),
    }),
  );
  await page.route('**/api/user/current', (route) =>
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        username: 'admin@test.com',
        display_name: 'Admin Test',
        is_admin: true,
      }),
    }),
  );
}

/**
 * Install the GET /release-preview mock. Successive calls cycle through `bodies`; the
 * last body is repeated when the list is exhausted. Returns a closure that reads the
 * running call count.
 */
async function installPreviewMock(page: Page, ...bodies: ReleasePreviewResponse[]) {
  let callCount = 0;
  await page.route(PREVIEW_URL, (route) => {
    const body = bodies[Math.min(callCount, bodies.length - 1)];
    callCount += 1;
    return route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(body),
    });
  });
  return () => callCount;
}

/** Navigate to the review page and wait for the heading. */
async function goToReviewPage(page: Page) {
  await page.goto('/admin/agent-definitions/review');
  await expect(page.getByRole('heading', { level: 1, name: 'Review & Publish' })).toBeVisible();
}

// ---------------------------------------------------------------------------
// Shared fixture: a preview with two changed roles (architect + data_analyst), both approved
// ---------------------------------------------------------------------------

const TWO_ROLE_PREVIEW: ReleasePreviewResponse = {
  ...syntheticReleasePreview(),
  changed: [
    syntheticChangedDefinition('architect'),
    syntheticChangedDefinition('data_analyst', {
      candidate_hash: 'd'.repeat(64),
      field_diffs: [
        {
          field: 'prompt_text',
          published: 'Analyse the data.\nFilter by quarter.',
          candidate: 'Analyse the data.\nFilter by quarter and year.',
        },
      ],
    }),
  ],
  readiness: syntheticDraftReadinessBody({
    draft_lock_version: 3,
    all_ready: true,
    agents: {
      architect: syntheticAgentReadiness('architect', {
        candidate_hash: RELEASE_ARCHITECT_CANDIDATE_HASH,
        is_changed_from_base: true,
        ready: true,
        cases: [
          syntheticTestCaseReadiness({
            status: 'approved',
            run_id: 501,
            run_verdict: 'approved',
            run_checks_passed: true,
          }),
        ],
      }),
      data_analyst: syntheticAgentReadiness('data_analyst', {
        candidate_hash: 'd'.repeat(64),
        is_changed_from_base: true,
        ready: true,
        cases: [
          syntheticTestCaseReadiness({
            agent_key: 'data_analyst',
            test_case_id: 102,
            test_case_name: 'Data analyst quarterly query',
            status: 'approved',
            run_id: 502,
            run_verdict: 'approved',
            run_checks_passed: true,
          }),
        ],
      }),
    },
  }),
  publishable: true,
};

// ---------------------------------------------------------------------------
// (a) Two changed roles; diff tab; publishable=false gate
// ---------------------------------------------------------------------------

test('(a) Publish is disabled when the server says the draft is not publishable', async ({ page }) => {
  await installIdentityMock(page);
  // A preview where publishable=false (no changed roles, so the draft is already current).
  await installPreviewMock(page, syntheticPublishedReleasePreview());
  await goToReviewPage(page);

  // Even with a non-blank note, Publish must be disabled when the server says not publishable.
  await page.getByTestId('release-note-input').fill('Some note');
  await expect(page.getByTestId('release-publish-button')).toBeDisabled();
});

test('(a) preview with two changed roles shows both sections; diff tab shows added and removed prompt lines', async ({ page }) => {
  await installIdentityMock(page);
  await installPreviewMock(page, TWO_ROLE_PREVIEW);
  await goToReviewPage(page);

  // Summary
  await expect(page.getByTestId('release-next-version')).toContainText('Next Graph Version: 2');

  // Changes & Approvals tab selected by default
  await expect(page.getByTestId('release-changes-tab')).toHaveAttribute('aria-selected', 'true');

  // Both changed-role sections are visible (ARIA region)
  await expect(page.getByRole('region', { name: 'Architect' })).toBeVisible();
  await expect(page.getByRole('region', { name: 'Data Analyst' })).toBeVisible();

  // Architect required-case list shows Approved
  const archCaseList = page
    .getByRole('region', { name: 'Architect' })
    .getByRole('list', { name: 'Required test cases' });
  await expect(archCaseList).toContainText('Approved');

  // Data Analyst required-case list shows Approved
  const daCaseList = page
    .getByRole('region', { name: 'Data Analyst' })
    .getByRole('list', { name: 'Required test cases' });
  await expect(daCaseList).toContainText('Approved');

  // Switch to Definition Diff tab
  await page.getByTestId('release-diff-tab').click();
  await expect(page.getByTestId('release-diff-tab')).toHaveAttribute('aria-selected', 'true');

  // Architect diff section is visible
  const archDiff = page.getByRole('region', { name: 'Architect diff' });
  await expect(archDiff).toBeVisible();

  // prompt_text list shows the changed lines (syntheticArchitectFieldDiffs)
  const promptList = archDiff.getByRole('list', { name: 'prompt_text' });
  await expect(promptList.locator('[data-kind="removed"]')).toContainText('- Use three sections.');
  await expect(promptList.locator('[data-kind="added"]')).toContainText('+ Use four sections.');

  // Data Analyst diff section also present
  await expect(page.getByRole('region', { name: 'Data Analyst diff' })).toBeVisible();
});

// ---------------------------------------------------------------------------
// (b) 409 not-ready disables Publish and names the gap; no_required_case mock
// ---------------------------------------------------------------------------

test('(b) 409 not-ready with no_eligible_approval disables Publish and names the role and case', async ({ page }) => {
  await installIdentityMock(page);
  await installPreviewMock(page, syntheticReleasePreview({ publishable: true }));

  let postCount = 0;
  await page.route(PUBLISH_URL, (route) => {
    postCount += 1;
    return route.fulfill({
      status: 409,
      contentType: 'application/json',
      body: JSON.stringify(syntheticPublicationNotReady()),
    });
  });

  await goToReviewPage(page);

  // Enter a valid note and publish
  await page.getByTestId('release-note-input').fill('Publish now');
  await page.getByTestId('release-publish-button').click();

  // Not-ready panel appears
  const notReadyPanel = page.getByTestId('release-not-ready-panel');
  await expect(notReadyPanel).toBeVisible();

  // Gap label: case name from the 409 readiness
  await expect(notReadyPanel).toContainText(
    'Architect: Architect quarterly revenue outline has no eligible approval',
  );

  // Publish is disabled (state is notReady, not ready)
  await expect(page.getByTestId('release-publish-button')).toBeDisabled();

  expect(postCount).toBe(1);
});

test('(b) 409 not-ready with no_required_case shows "no active required test case" label', async ({ page }) => {
  await installIdentityMock(page);
  await installPreviewMock(page, syntheticReleasePreview({ publishable: true }));

  await page.route(PUBLISH_URL, (route) =>
    route.fulfill({
      status: 409,
      contentType: 'application/json',
      body: JSON.stringify(
        syntheticPublicationNotReady([
          { agent_key: 'architect', test_case_id: null, code: 'no_required_case' },
        ]),
      ),
    }),
  );

  await goToReviewPage(page);
  await page.getByTestId('release-note-input').fill('Publish now');
  await page.getByTestId('release-publish-button').click();

  const notReadyPanel = page.getByTestId('release-not-ready-panel');
  await expect(notReadyPanel).toBeVisible();
  await expect(notReadyPanel).toContainText('Architect: no active required test case');

  await expect(page.getByTestId('release-publish-button')).toBeDisabled();
});

// ---------------------------------------------------------------------------
// (c) Stale 409 keeps the note; Reload preview issues exactly 1 GET, 0 POSTs
// ---------------------------------------------------------------------------

test('(c) stale 409 keeps the note; Reload preview issues exactly one GET and zero POSTs', async ({ page }) => {
  await installIdentityMock(page);

  let getCount = 0;
  await page.route(PREVIEW_URL, (route) => {
    getCount += 1;
    return route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(syntheticReleasePreview()),
    });
  });

  let postCount = 0;
  await page.route(PUBLISH_URL, (route) => {
    postCount += 1;
    return route.fulfill({
      status: 409,
      contentType: 'application/json',
      body: JSON.stringify(syntheticStalePublication()),
    });
  });

  await goToReviewPage(page);
  // Initial load issued 1 GET
  await expect.poll(() => getCount).toBe(1);

  // Fill a note
  const NOTE = 'Tighten the outline';
  await page.getByTestId('release-note-input').fill(NOTE);

  // Attempt to publish
  await page.getByTestId('release-publish-button').click();

  // Stale alert appears
  const staleAlert = page.getByTestId('release-stale-alert');
  await expect(staleAlert).toBeVisible();
  await expect(staleAlert).toContainText('lock version 5');
  await expect(staleAlert).toContainText('lock version 3');
  await expect(staleAlert).toContainText('Graph Version 1 is active');

  // Note is retained
  await expect(page.getByTestId('release-note-input')).toHaveValue(NOTE);

  // Counts after stale: 1 GET, 1 POST
  expect(getCount).toBe(1);
  expect(postCount).toBe(1);

  // Click Reload preview
  await staleAlert.getByRole('button', { name: 'Reload preview' }).click();

  // Exactly one new GET; no new POST
  await expect.poll(() => getCount).toBe(2);
  expect(postCount).toBe(1);

  // Preview is back (stale alert gone)
  await expect(staleAlert).toHaveCount(0);
  await expect(page.getByTestId('release-next-version')).toBeVisible();
});

// ---------------------------------------------------------------------------
// (d) Success 200 → success panel + exactly one refetch; workbench link
// ---------------------------------------------------------------------------

test('(d) success 200 shows success panel; refetched preview shows Draft base: Graph Version 2 and no changes', async ({ page }) => {
  await installIdentityMock(page);

  let getCount = 0;
  await page.route(PREVIEW_URL, (route) => {
    getCount += 1;
    // First call: the publishable preview; second call (auto-refetch): the post-publish preview.
    const body = getCount === 1 ? syntheticReleasePreview() : syntheticPublishedReleasePreview();
    return route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(body),
    });
  });

  let postCount = 0;
  await page.route(PUBLISH_URL, (route) => {
    postCount += 1;
    return route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(syntheticPublishSuccess()),
    });
  });

  await goToReviewPage(page);
  // Initial GET
  await expect.poll(() => getCount).toBe(1);

  await page.getByTestId('release-note-input').fill('Tighten the architect outline');
  await page.getByTestId('release-publish-button').click();

  // Success panel appears
  const successPanel = page.getByTestId('release-success-panel');
  await expect(successPanel).toBeVisible();
  await expect(successPanel).toContainText('Published Graph Version 2');
  await expect(successPanel).toContainText('The shared draft is now based on Graph Version 2');

  // Exactly one auto-refetch: total 2 GETs, 1 POST
  await expect.poll(() => getCount).toBe(2);
  expect(postCount).toBe(1);

  // Refetched preview shows the rebased draft (base Graph Version 2, no changes)
  await expect(page.getByText('Draft base: Graph Version 2')).toBeVisible();
  await expect(page.getByText(/No Agent Definitions changed since Graph Version/)).toBeVisible();
});

test('(d) the Review & Publish link in the workbench navigates to the review page', async ({ page }) => {
  await installIdentityMock(page);

  // Workbench + readiness (needed for the Agent Definitions tab to load)
  await page.route(WORKBENCH_URL, (route) =>
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(syntheticAgentDefinitionWorkbench),
    }),
  );
  await page.route(READINESS_URL, (route) =>
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(syntheticDraftReadinessBody()),
    }),
  );

  // When the link is clicked the review page fetches the preview; fail fast so we only
  // need to check that we arrived at the right URL and the heading renders.
  await page.route(PREVIEW_URL, (route) =>
    route.fulfill({
      status: 500,
      contentType: 'application/json',
      body: JSON.stringify({ detail: 'stub' }),
    }),
  );

  await page.goto('/admin');
  await page.getByRole('tab', { name: 'Agent Definitions' }).click();
  await expect(page.getByRole('heading', { name: /Graph Version/ })).toBeVisible();

  // Click the workbench header link
  await page.getByRole('link', { name: 'Review & Publish' }).click();

  await expect(page).toHaveURL(/\/admin\/agent-definitions\/review$/);
  await expect(page.getByRole('heading', { level: 1, name: 'Review & Publish' })).toBeVisible();
});

// ---------------------------------------------------------------------------
// (e) 422 blank-note server response rendered beside the note input
// ---------------------------------------------------------------------------

test('(e) 422 blank-note response is rendered beside the note input; note is kept', async ({ page }) => {
  await installIdentityMock(page);
  await installPreviewMock(page, syntheticReleasePreview({ publishable: true }));

  await page.route(PUBLISH_URL, (route) =>
    route.fulfill({
      status: 422,
      contentType: 'application/json',
      body: JSON.stringify(syntheticPublicationInvalid([RELEASE_NOTE_BLANK_ERROR])),
    }),
  );

  await goToReviewPage(page);

  // Fill a note that passes client validation but the server refuses
  const NOTE = '\u001f'; // U+001F passes JS non-blank check but Python strips it
  await page.getByTestId('release-note-input').fill(NOTE);
  await page.getByTestId('release-publish-button').click();

  // Error rendered beside the textarea (id="release-note-error")
  await expect(page.locator('#release-note-error')).toBeVisible();
  // The error text is keyed on `code: 'blank'`, not the server's message text (C10)
  await expect(page.locator('#release-note-error')).toContainText('Enter a release note.');

  // The textarea is marked invalid
  await expect(page.getByTestId('release-note-input')).toHaveAttribute('aria-invalid', 'true');

  // The note value is retained, not cleared
  await expect(page.getByTestId('release-note-input')).toHaveValue(NOTE);
});

// ---------------------------------------------------------------------------
// (f) Forbidden-action sweep: Publish draft, Release history, Rollback release still flagged
// ---------------------------------------------------------------------------

test('(f) the forbidden sweep still flags Publish draft, Release history, and Rollback release', () => {
  // Names that task 7 must not accidentally exempt
  for (const name of ['Publish draft', 'Release history', 'Rollback release']) {
    expect(forbidsActionName(name), name).toBe(true);
  }
  // The workbench header link is still spared (C7/C44; added in Task 6)
  expect(forbidsActionName('Review & Publish')).toBe(false);
  // Near-misses stay forbidden
  expect(forbidsActionName('Review & Publish now')).toBe(true);
  expect(forbidsActionName('Review & publish')).toBe(true);
});
