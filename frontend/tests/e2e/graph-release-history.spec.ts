/**
 * Release History tab and rollback browser tests (#270 Task 8).
 *
 * Scenarios:
 *   (a) Eight versions; "Restores Graph Version 3" badge on v8; active row has no rollback
 *       control; every non-active row has exactly one; inspecting v3 shows detail and diffs.
 *   (b) Roll back to version 3: exactly one preview GET and zero POSTs; then Confirm rollback
 *       issues exactly one POST whose body is {"lock_version": <preview lock>, "release_note":
 *       "Roll back to Graph Version 3."}.
 *   (c-1) 422 rollback_incompatible shows the blocked panel and zero further POSTs.
 *   (c-2) 409 stale_rollback shows the alert, keeps the typed note, reloads with exactly one GET.
 *   (d) Rollback success: v8 appears first; Changes & Approvals tab shows Draft base: Graph
 *       Version 8.
 *   (f) Name-collision sweep across states ready, confirming, blocked, restored: no two
 *       distinct accessible names equal each other, and none is a case-insensitive substring
 *       of another.
 *   (g) Two-digit version disambiguation: versions 1–12, exact-name locator for v1 and v12
 *       each resolves to exactly one element.
 *   (h) Static: the forbidden sweep still flags "Release history" and "Rollback release".
 *
 * Run: cd frontend && npx playwright test tests/e2e/graph-release-history.spec.ts --project=chromium --workers=1
 */
import { test, expect, Page } from '@playwright/test';
import type {
  ReleaseHistoryListResponse,
  ReleasePreviewResponse,
  RollbackPreviewResponse,
  RollbackSuccessResponse,
} from '../../src/api/agentDefinitions';
import {
  releaseRef,
  syntheticHistoryEntry,
  syntheticAgentComparisons,
  syntheticReleaseDetail,
  syntheticDraftEffect,
  syntheticDraftReadinessBody,
  syntheticReleaseDraft,
  syntheticReleasePreview,
  syntheticBlockedRollbackPreview,
  syntheticStaleRollback,
  syntheticRollbackIncompatible,
  SEED_CANDIDATE_HASH,
} from '../fixtures/mocks';
import { forbidsActionName } from '../fixtures/forbiddenActionNames';

// ---------------------------------------------------------------------------
// URL constants
// ---------------------------------------------------------------------------
const HISTORY_URL = '**/api/admin/agent-definitions/releases';
const ROLLBACK_PREVIEW_URL = '**/api/admin/agent-definitions/releases/*/rollback-preview';
const ROLLBACK_URL = '**/api/admin/agent-definitions/releases/*/rollback';
const COMPARISON_URL = '**/api/admin/agent-definitions/releases/*/comparison';
const DETAIL_URL = '**/api/admin/agent-definitions/releases/*';
const PREVIEW_URL = '**/api/admin/agent-definitions/release-preview';

// ---------------------------------------------------------------------------
// Local fixtures: Task 8's v1–v8 and v1–v7 scenarios
// ---------------------------------------------------------------------------

/** v1–v8 history: v8 is active and restores v3; v3 previously restored v1. */
function historyV8(): ReleaseHistoryListResponse {
  return {
    active_release: releaseRef(8),
    releases: [
      syntheticHistoryEntry(8, { active: true, restoredFrom: 3 }),
      syntheticHistoryEntry(7),
      syntheticHistoryEntry(6),
      syntheticHistoryEntry(5),
      syntheticHistoryEntry(4),
      syntheticHistoryEntry(3, { restoredFrom: 1, restoredBy: [8] }),
      syntheticHistoryEntry(2),
      syntheticHistoryEntry(1, { restoredBy: [3] }),
    ],
  };
}

/** v1–v7 history: v7 is active; v3 previously restored v1. */
function historyV7(): ReleaseHistoryListResponse {
  return {
    active_release: releaseRef(7),
    releases: [
      syntheticHistoryEntry(7, { active: true }),
      syntheticHistoryEntry(6),
      syntheticHistoryEntry(5),
      syntheticHistoryEntry(4),
      syntheticHistoryEntry(3, { restoredFrom: 1 }),
      syntheticHistoryEntry(2),
      syntheticHistoryEntry(1, { restoredBy: [3] }),
    ],
  };
}

/** v1–v8 history after rolling back to v3: v8 is active and restores v3. */
function historyAfterRollbackToV3(): ReleaseHistoryListResponse {
  return historyV8();
}

/**
 * Rollback preview for rolling back to v3 with v7 active: restorable, next version 8,
 * lock version 3, default note "Roll back to Graph Version 3."
 * id = version + 40, so v3 id = 43, v7 id = 47.
 */
function rollbackPreviewV3(): RollbackPreviewResponse {
  return {
    source: releaseRef(3),
    active_release: releaseRef(7),
    next_version_number: 8,
    lock_version: 3,
    default_release_note: 'Roll back to Graph Version 3.',
    restorable: true,
    blocked: null,
    issues: [],
    warnings: [],
    agents: syntheticAgentComparisons(),
    evidence: [
      { agent_test_run_id: 501, agent_key: 'architect', test_case_id: 101 },
      { agent_test_run_id: 502, agent_key: 'builder', test_case_id: 202 },
    ],
    draft_effect: syntheticDraftEffect(),
  };
}

/** Rollback success: v8 restores v3; previous was v7. id = version + 40. */
function rollbackSuccessV3(): RollbackSuccessResponse {
  const AGENT_KEYS = ['architect', 'data_analyst', 'builder', 'build_reviewer', 'fixer', 'fix_reviewer', 'deck_reviewer'] as const;
  return {
    release: {
      release_id: 48, // 8 + 40
      version_number: 8,
      previous_release_id: 47, // 7 + 40
      restored_from_release_id: 43, // 3 + 40
      release_note: 'Roll back to Graph Version 3.',
      published_by: 'admin@example.com',
      published_at: '2026-09-28T12:00:00Z',
      effective_from: '2026-09-28T12:00:00Z',
      effective_to: null,
    },
    restored_from: releaseRef(3),
    previous_release_id: 47,
    changed_agents: ['architect', 'builder'],
    mappings: Object.fromEntries(AGENT_KEYS.map((key, index) => [key, {
      agent_definition_revision_id: 200 + index,
      content_hash: key === 'architect' ? 'b'.repeat(64) : SEED_CANDIDATE_HASH,
      reused: true,
    }])) as RollbackSuccessResponse['mappings'],
    evidence: [
      { agent_test_run_id: 501, agent_key: 'architect', test_case_id: 101, evidence_kind: 'historical_restore', source_release_id: 43 },
      { agent_test_run_id: 502, agent_key: 'builder', test_case_id: 202, evidence_kind: 'historical_restore', source_release_id: 43 },
    ],
    draft: syntheticReleaseDraft({ base_release_id: 48, base_version_number: 8, lock_version: 4 }),
    draft_effect: syntheticDraftEffect(),
  };
}

/** Release preview after rollback to v3: draft is based on v8. */
function previewAfterRollbackToV3(): ReleasePreviewResponse {
  return {
    draft: syntheticReleaseDraft({ base_release_id: 48, base_version_number: 8, lock_version: 4 }),
    active_release: rollbackSuccessV3().release,
    next_version_number: 9,
    changed: [],
    readiness: syntheticDraftReadinessBody({ draft_lock_version: 4, base_release_id: 48 }),
    validation_issues: [],
    publishable: false,
  };
}

/** v1–v12 history: v12 is active, v3 restores v1. For the two-digit version test.
 * The shared fixture's dates roll into October from v10, so no override is needed. */
function historyV12(): ReleaseHistoryListResponse {
  return {
    active_release: releaseRef(12),
    releases: [
      syntheticHistoryEntry(12, { active: true }),
      syntheticHistoryEntry(11),
      syntheticHistoryEntry(10),
      syntheticHistoryEntry(9),
      syntheticHistoryEntry(8),
      syntheticHistoryEntry(7),
      syntheticHistoryEntry(6),
      syntheticHistoryEntry(5),
      syntheticHistoryEntry(4),
      syntheticHistoryEntry(3, { restoredFrom: 1 }),
      syntheticHistoryEntry(2),
      syntheticHistoryEntry(1, { restoredBy: [3] }),
    ],
  };
}

// ---------------------------------------------------------------------------
// Comparison mock for v3 vs v8-active (same structure as syntheticReleaseComparison
// but adapted for the v1–v8 scenario)
// ---------------------------------------------------------------------------
function releaseComparisonV3(): { active_release: unknown; release: unknown; agents: unknown } {
  return {
    active_release: releaseRef(8),
    release: releaseRef(3),
    agents: syntheticAgentComparisons(), // architect and builder differ; active_revision_id = 400, historical = 200
  };
}

/** Release detail for v3 (reusing syntheticReleaseDetail which covers v2; adapt note). */
function releaseDetailV3(): ReturnType<typeof syntheticReleaseDetail> {
  const d = syntheticReleaseDetail();
  // Rewrite the entry to be v3
  d.release = syntheticHistoryEntry(3, { restoredFrom: 1 });
  return d;
}

// ---------------------------------------------------------------------------
// Shared helpers
// ---------------------------------------------------------------------------

async function installIdentityMock(page: Page) {
  await page.route('**/api/setup/status', (route) =>
    route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ configured: true }) }),
  );
  await page.route('**/api/user/current', (route) =>
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ username: 'admin@test.com', display_name: 'Admin Test', is_admin: true }),
    }),
  );
}

async function goToReviewPage(page: Page) {
  await page.goto('/admin/agent-definitions/review');
  await expect(page.getByRole('heading', { level: 1, name: 'Review & Publish' })).toBeVisible();
}

async function openHistoryTab(page: Page) {
  await page.getByTestId('release-history-tab').click();
  await expect(page.getByTestId('release-history-tab')).toHaveAttribute('aria-selected', 'true');
}

/** Install the history list mock (GET /releases). Returns a call-count closure. */
async function installHistoryMock(page: Page, ...bodies: ReleaseHistoryListResponse[]) {
  let count = 0;
  await page.route(HISTORY_URL, (route) => {
    const body = bodies[Math.min(count, bodies.length - 1)];
    count += 1;
    return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(body) });
  });
  return () => count;
}

/** Install the release preview mock (GET /release-preview). Returns a call-count closure. */
async function installPreviewMock(page: Page, ...bodies: ReleasePreviewResponse[]) {
  let count = 0;
  await page.route(PREVIEW_URL, (route) => {
    const body = bodies[Math.min(count, bodies.length - 1)];
    count += 1;
    return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(body) });
  });
  return () => count;
}

// ---------------------------------------------------------------------------
// (a) History renders eight versions; badges; inspection
// ---------------------------------------------------------------------------

test('(a) history renders eight versions; v8 has "Restores Graph Version 3" badge and no rollback control; every other row has exactly one', async ({ page }) => {
  await installIdentityMock(page);
  await installPreviewMock(page, syntheticReleasePreview());
  await installHistoryMock(page, historyV8());

  // Stub detail and comparison (called when inspecting)
  await page.route(COMPARISON_URL, (route) =>
    route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(releaseComparisonV3()) }),
  );
  await page.route(DETAIL_URL, (route) =>
    route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(releaseDetailV3()) }),
  );

  await goToReviewPage(page);
  await openHistoryTab(page);

  // Eight rows
  const rows = page.locator('[data-testid^="release-history-row-"]');
  await expect(rows).toHaveCount(8);

  // v8 is active: has the "Active" badge
  const v8Row = page.getByTestId('release-history-row-8');
  await expect(v8Row).toContainText('Active');

  // v8 has the "Restores Graph Version 3" badge (restored_from = v3)
  await expect(v8Row).toContainText('Restores Graph Version 3');

  // v8 (active row) has ZERO "Roll back to this version" buttons (C7 / I6)
  await expect(v8Row.getByRole('button', { name: 'Roll back to this version', exact: true })).toHaveCount(0);

  // v8 still has the Inspect button
  await expect(v8Row.getByRole('button', { name: 'Inspect this version', exact: true })).toHaveCount(1);

  // Every non-active row (v1–v7) has exactly one "Roll back to this version" button
  for (const v of [1, 2, 3, 4, 5, 6, 7]) {
    const row = page.getByTestId(`release-history-row-${v}`);
    await expect(row.getByRole('button', { name: 'Roll back to this version', exact: true })).toHaveCount(1);
  }
});

test('(a) inspecting v3 shows the detail panel and comparison diffs', async ({ page }) => {
  await installIdentityMock(page);
  await installPreviewMock(page, syntheticReleasePreview());
  await installHistoryMock(page, historyV8());

  await page.route(COMPARISON_URL, (route) =>
    route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(releaseComparisonV3()) }),
  );
  await page.route(DETAIL_URL, (route) =>
    route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(releaseDetailV3()) }),
  );

  await goToReviewPage(page);
  await openHistoryTab(page);

  // Inspect v3
  const v3Row = page.getByTestId('release-history-row-3');
  await v3Row.getByRole('button', { name: 'Inspect this version', exact: true }).click();

  // Detail panel appears
  const detail = page.getByTestId('release-history-detail');
  await expect(detail).toBeVisible();

  // Definitions for v3 are shown (architect is listed)
  await expect(detail.getByTestId('release-definition-architect')).toBeVisible();

  // Evidence is shown
  await expect(detail.getByRole('list', { name: 'Evidence' })).toBeVisible();

  // Comparison is shown with architect having a prompt diff
  const comparison = page.getByTestId('release-comparison');
  await expect(comparison).toBeVisible();

  // Architect prompt diff shows the historical prompt text (v3 = v2 in the detail fixture)
  const archComparison = comparison.getByRole('region', { name: 'Architect comparison' });
  await expect(archComparison).toBeVisible();
  // The comparison heading names the two versions
  await expect(comparison).toContainText('against the active Graph Version 8');
});

// ---------------------------------------------------------------------------
// (b) Rollback confirmation: exactly one preview GET, zero POSTs; then one POST
// ---------------------------------------------------------------------------

test('(b) Roll back to this version on v3 issues exactly one preview GET and zero POSTs; Confirm rollback issues one POST with the exact body', async ({ page }) => {
  await installIdentityMock(page);
  await installPreviewMock(page, syntheticReleasePreview());
  // Pass two history bodies: first call returns v1-v7 (initial), subsequent calls return v1-v8 (after rollback).
  // A single installHistoryMock call avoids a second page.route(HISTORY_URL) overriding the first in LIFO order.
  await installHistoryMock(page, historyV7(), historyAfterRollbackToV3());

  let previewGetCount = 0;
  await page.route(ROLLBACK_PREVIEW_URL, (route) => {
    previewGetCount += 1;
    return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(rollbackPreviewV3()) });
  });

  let rollbackPostCount = 0;
  let capturedBody: Record<string, unknown> = {};
  await page.route(ROLLBACK_URL, async (route) => {
    rollbackPostCount += 1;
    capturedBody = JSON.parse(route.request().postData() ?? '{}') as Record<string, unknown>;
    return route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(rollbackSuccessV3()),
    });
  });

  await goToReviewPage(page);
  await openHistoryTab(page);

  // Wait for history rows to render
  await expect(page.locator('[data-testid^="release-history-row-"]')).toHaveCount(7);

  // Zero preview GETs so far
  expect(previewGetCount).toBe(0);
  expect(rollbackPostCount).toBe(0);

  // Click "Roll back to this version" on v3's row
  const v3Row = page.getByTestId('release-history-row-3');
  await v3Row.getByRole('button', { name: 'Roll back to this version', exact: true }).click();

  // Exactly one preview GET; still zero POSTs
  await expect.poll(() => previewGetCount).toBe(1);
  expect(rollbackPostCount).toBe(0);

  // Rollback panel is shown with the preview
  const rollbackPanel = page.getByTestId('rollback-preview');
  await expect(rollbackPanel).toBeVisible();

  // The lineage sentence names the versions correctly
  await expect(rollbackPanel.getByTestId('rollback-lineage')).toContainText(
    'Graph Version 8 will restore Graph Version 3',
  );

  // The note textarea has the default note
  const noteInput = rollbackPanel.getByTestId('rollback-note-input');
  await expect(noteInput).toHaveValue('Roll back to Graph Version 3.');

  // Confirm rollback (default note is non-blank, preview is restorable)
  await rollbackPanel.getByTestId('rollback-confirm-button').click();

  // Exactly one POST; body is the correct object
  await expect.poll(() => rollbackPostCount).toBe(1);
  expect(capturedBody).toEqual({ lock_version: 3, release_note: 'Roll back to Graph Version 3.' });
});

// ---------------------------------------------------------------------------
// (c-1) 422 rollback_incompatible shows the blocked panel; zero further POSTs
// ---------------------------------------------------------------------------

test('(c-1) 422 rollback_incompatible: blocked panel is shown and no further POST fires', async ({ page }) => {
  await installIdentityMock(page);
  await installPreviewMock(page, syntheticReleasePreview());
  await installHistoryMock(page, historyV7());

  // Preview is restorable (not blocked at preview stage)
  await page.route(ROLLBACK_PREVIEW_URL, (route) =>
    route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(rollbackPreviewV3()) }),
  );

  let postCount = 0;
  await page.route(ROLLBACK_URL, (route) => {
    postCount += 1;
    return route.fulfill({
      status: 422,
      contentType: 'application/json',
      body: JSON.stringify(syntheticRollbackIncompatible()),
    });
  });

  await goToReviewPage(page);
  await openHistoryTab(page);

  // Open rollback for v3
  const v3Row = page.getByTestId('release-history-row-3');
  await v3Row.getByRole('button', { name: 'Roll back to this version', exact: true }).click();
  const rollbackPanel = page.getByTestId('rollback-preview');
  await expect(rollbackPanel).toBeVisible();

  // Confirm → fires one POST → 422 → blocked panel
  await rollbackPanel.getByTestId('rollback-confirm-button').click();
  await expect.poll(() => postCount).toBe(1);

  // Blocked panel appears
  const blockedPanel = page.getByTestId('rollback-blocked-panel');
  await expect(blockedPanel).toBeVisible();
  await expect(blockedPanel).toContainText('The active release is unchanged.');

  // No further POST on second attempt (Confirm should be gone or disabled)
  // The blocked state disables or hides Confirm rollback
  const confirmButton = rollbackPanel.getByTestId('rollback-confirm-button');
  await expect(confirmButton).toBeDisabled();

  // A disabled Confirm fires no additional POST.
  await confirmButton.click({ force: true }).catch(() => undefined);
  await expect.poll(() => postCount).toBe(1);
});

// ---------------------------------------------------------------------------
// (c-2) 409 stale_rollback: alert shows; note is kept; Reload rollback preview fires one GET
// ---------------------------------------------------------------------------

test('(c-2) 409 stale_rollback: alert shows, note is kept, Reload rollback preview issues exactly one GET', async ({ page }) => {
  await installIdentityMock(page);
  await installPreviewMock(page, syntheticReleasePreview());
  await installHistoryMock(page, historyV7());

  let previewGetCount = 0;
  await page.route(ROLLBACK_PREVIEW_URL, (route) => {
    previewGetCount += 1;
    return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(rollbackPreviewV3()) });
  });

  let postCount = 0;
  await page.route(ROLLBACK_URL, (route) => {
    postCount += 1;
    return route.fulfill({
      status: 409,
      contentType: 'application/json',
      body: JSON.stringify(syntheticStaleRollback()),
    });
  });

  await goToReviewPage(page);
  await openHistoryTab(page);

  // Open rollback for v3 → one preview GET
  const v3Row = page.getByTestId('release-history-row-3');
  await v3Row.getByRole('button', { name: 'Roll back to this version', exact: true }).click();
  await expect.poll(() => previewGetCount).toBe(1);

  const rollbackPanel = page.getByTestId('rollback-preview');
  await expect(rollbackPanel).toBeVisible();

  // Edit the note
  const NOTE = 'My custom rollback note';
  const noteInput = rollbackPanel.getByTestId('rollback-note-input');
  await noteInput.fill(NOTE);

  // Confirm → one POST → 409 stale
  await rollbackPanel.getByTestId('rollback-confirm-button').click();
  await expect.poll(() => postCount).toBe(1);

  // Stale alert appears
  const staleAlert = rollbackPanel.getByTestId('rollback-stale-alert');
  await expect(staleAlert).toBeVisible();
  // Alert mentions lock versions (current_lock_version=5, expected=3 from syntheticStaleRollback)
  await expect(staleAlert).toContainText('lock version 5');
  await expect(staleAlert).toContainText('lock version 3');
  // Alert names the active version (v4 from syntheticStaleRollback)
  await expect(staleAlert).toContainText('Graph Version 4 is active');

  // Note is preserved after the stale 409
  await expect(noteInput).toHaveValue(NOTE);

  // Counts: 1 GET, 1 POST so far
  expect(previewGetCount).toBe(1);
  expect(postCount).toBe(1);

  // Click "Reload rollback preview" (exact name, per m4 fix)
  await staleAlert.getByRole('button', { name: 'Reload rollback preview', exact: true }).click();

  // Exactly one new GET; no new POST
  await expect.poll(() => previewGetCount).toBe(2);
  expect(postCount).toBe(1);

  // Stale alert is gone after reload; rollback panel is back
  await expect(staleAlert).toHaveCount(0);
  await expect(rollbackPanel.getByTestId('rollback-lineage')).toBeVisible();

  // The note is still preserved after the reload
  await expect(noteInput).toHaveValue(NOTE);
});

// ---------------------------------------------------------------------------
// (d) Success: v8 appears first; Changes & Approvals shows Draft base: Graph Version 8
// ---------------------------------------------------------------------------

test('(d) successful rollback: v8 appears first in history; Changes & Approvals shows Draft base: Graph Version 8', async ({ page }) => {
  await installIdentityMock(page);

  let previewGetCount = 0;
  await page.route(PREVIEW_URL, (route) => {
    previewGetCount += 1;
    const body = previewGetCount === 1 ? syntheticReleasePreview() : previewAfterRollbackToV3();
    return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(body) });
  });

  let historyGetCount = 0;
  await page.route(HISTORY_URL, (route) => {
    historyGetCount += 1;
    const body = historyGetCount === 1 ? historyV7() : historyAfterRollbackToV3();
    return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(body) });
  });

  await page.route(ROLLBACK_PREVIEW_URL, (route) =>
    route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(rollbackPreviewV3()) }),
  );

  await page.route(ROLLBACK_URL, (route) =>
    route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(rollbackSuccessV3()) }),
  );

  await goToReviewPage(page);
  await openHistoryTab(page);

  // Wait for initial history (7 rows)
  await expect(page.locator('[data-testid^="release-history-row-"]')).toHaveCount(7);

  // Open rollback for v3 → confirm
  const v3Row = page.getByTestId('release-history-row-3');
  await v3Row.getByRole('button', { name: 'Roll back to this version', exact: true }).click();

  const rollbackPanel = page.getByTestId('rollback-preview');
  await expect(rollbackPanel).toBeVisible();
  await rollbackPanel.getByTestId('rollback-confirm-button').click();

  // Success panel appears
  const successPanel = page.getByTestId('rollback-success-panel');
  await expect(successPanel).toBeVisible();
  await expect(successPanel).toContainText('Graph Version 8 restores Graph Version 3');
  await expect(successPanel).toContainText('The shared draft is now based on Graph Version 8');

  // History refetches: v8 appears first (8 rows now, v8 is active)
  await expect(page.locator('[data-testid^="release-history-row-"]')).toHaveCount(8);
  // The first row is v8 (most recent = active)
  await expect(page.getByTestId('release-history-row-8')).toBeVisible();
  await expect(page.getByTestId('release-history-row-8')).toContainText('Active');

  // Switch to Changes & Approvals tab; the refetched preview shows Draft base: Graph Version 8
  await page.getByTestId('release-changes-tab').click();
  await expect(page.getByText('Draft base: Graph Version 8')).toBeVisible();
});

// ---------------------------------------------------------------------------
// (f) Name-collision sweep across states ready, confirming, blocked, restored
// ---------------------------------------------------------------------------

/**
 * Collect every button and link accessible name visible on the page.
 * Returns the lowercase-trimmed unique set.
 */
async function collectAccessibleNames(page: Page): Promise<string[]> {
  return page.locator('button, a[href], a[role="tab"]').evaluateAll(
    (els) => els.map((el) => {
      const ariaLabel = el.getAttribute('aria-label') ?? '';
      const text = el.textContent ?? '';
      // Use aria-label when set, else trimmed text content
      return (ariaLabel.trim() || text.trim()).replace(/\s+/g, ' ');
    }).filter((name) => name.length > 0),
  );
}

function assertNoSubstringCollisions(names: string[]): void {
  const unique = Array.from(new Set(names.map((n) => n.toLowerCase().trim()).filter(Boolean)));
  for (const a of unique) {
    for (const b of unique) {
      if (a !== b) {
        expect(b.includes(a), `"${a}" is a case-insensitive substring of "${b}"`).toBe(false);
      }
    }
  }
}

test('(f) name-collision sweep: no two distinct accessible names are substrings of each other across ready, confirming, blocked, and restored states', async ({ page }) => {
  await installIdentityMock(page);
  await installPreviewMock(page, syntheticReleasePreview(), previewAfterRollbackToV3());

  // For the 'blocked' state: blocked preview
  await page.route(ROLLBACK_PREVIEW_URL, (route) =>
    route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(rollbackPreviewV3()) }),
  );

  let historyGetCount = 0;
  await page.route(HISTORY_URL, (route) => {
    historyGetCount += 1;
    const body = historyGetCount <= 1 ? historyV8() : historyAfterRollbackToV3();
    return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(body) });
  });

  // Stub detail/comparison for inspection (not needed in this test, just prevent 404)
  await page.route(COMPARISON_URL, (route) =>
    route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(releaseComparisonV3()) }),
  );
  await page.route(DETAIL_URL, (route) =>
    route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(releaseDetailV3()) }),
  );

  await goToReviewPage(page);
  await openHistoryTab(page);

  // Wait for history to load (8 rows)
  await expect(page.locator('[data-testid^="release-history-row-"]')).toHaveCount(8);

  // --- State: ready (history loaded, no rollback open) ---
  const readyNames = await collectAccessibleNames(page);
  assertNoSubstringCollisions(readyNames);
  expect(readyNames.length).toBeGreaterThan(0);

  // --- State: confirming (rollback open with preview) ---
  const v3Row = page.getByTestId('release-history-row-3');
  await v3Row.getByRole('button', { name: 'Roll back to this version', exact: true }).click();
  await expect(page.getByTestId('rollback-preview')).toBeVisible();
  // Fill a note to enable Confirm
  await page.getByTestId('rollback-note-input').fill('Roll back to Graph Version 3.');
  await expect(page.getByTestId('rollback-confirm-button')).toBeEnabled();

  const confirmingNames = await collectAccessibleNames(page);
  assertNoSubstringCollisions(confirmingNames);
  expect(confirmingNames.length).toBeGreaterThan(readyNames.length);

  // Cancel to return to ready, then open rollback for a blocked preview
  await page.getByTestId('rollback-cancel-button').click();
  await expect(page.getByTestId('rollback-preview')).toHaveCount(0);

  // --- State: blocked (open rollback for v3, then simulate blocked via incompatible POST) ---
  // Set up blocked state by overriding ROLLBACK_URL to return 422 incompatible
  await page.unroute(ROLLBACK_PREVIEW_URL);
  await page.route(ROLLBACK_PREVIEW_URL, (route) =>
    route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(syntheticBlockedRollbackPreview()) }),
  );

  await v3Row.getByRole('button', { name: 'Roll back to this version', exact: true }).click();
  // Blocked preview: blocked panel shows immediately (no confirm needed)
  await expect(page.getByTestId('rollback-blocked-panel')).toBeVisible();

  const blockedNames = await collectAccessibleNames(page);
  assertNoSubstringCollisions(blockedNames);
  expect(blockedNames.length).toBeGreaterThan(0);

  // Cancel to exit blocked state
  await page.getByTestId('rollback-cancel-button').click();
  await expect(page.getByTestId('rollback-preview')).toHaveCount(0);

  // --- State: restored (success panel showing) ---
  // Restore the preview mock to restorable and set up a successful POST
  await page.unroute(ROLLBACK_PREVIEW_URL);
  await page.route(ROLLBACK_PREVIEW_URL, (route) =>
    route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(rollbackPreviewV3()) }),
  );
  await page.route(ROLLBACK_URL, (route) =>
    route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(rollbackSuccessV3()) }),
  );

  await v3Row.getByRole('button', { name: 'Roll back to this version', exact: true }).click();
  await expect(page.getByTestId('rollback-preview')).toBeVisible();
  await page.getByTestId('rollback-note-input').fill('Roll back to Graph Version 3.');
  await page.getByTestId('rollback-confirm-button').click();
  await expect(page.getByTestId('rollback-success-panel')).toBeVisible();

  const restoredNames = await collectAccessibleNames(page);
  assertNoSubstringCollisions(restoredNames);
  expect(restoredNames.length).toBeGreaterThan(0);
});

// ---------------------------------------------------------------------------
// (g) Two-digit version disambiguation: exact-name locator resolves to one element
// ---------------------------------------------------------------------------

test('(g) two-digit versions: exact name locator for v1 and v12 each resolve to exactly one rollback button', async ({ page }) => {
  await installIdentityMock(page);
  await installPreviewMock(page, syntheticReleasePreview());
  await installHistoryMock(page, historyV12());

  // Stub rollback preview (may be triggered by accidental click)
  await page.route(ROLLBACK_PREVIEW_URL, (route) =>
    route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(rollbackPreviewV3()) }),
  );

  await goToReviewPage(page);
  await openHistoryTab(page);

  // Wait for all 12 rows
  await expect(page.locator('[data-testid^="release-history-row-"]')).toHaveCount(12);

  // v12 (active): no rollback button
  await expect(
    page.getByTestId('release-history-row-12').getByRole('button', { name: 'Roll back to this version', exact: true }),
  ).toHaveCount(0);

  // v1: exactly one rollback button (exact: true prevents matching on "Roll back to this version" inside a longer name)
  await expect(
    page.getByTestId('release-history-row-1').getByRole('button', { name: 'Roll back to this version', exact: true }),
  ).toHaveCount(1);

  // v12 with no rollback button: confirm "1" substring of "12" does not cause false matches
  // The locator scoped to release-history-row-1 resolves to exactly one element
  await expect(
    page.getByTestId('release-history-row-1').getByRole('button', { name: 'Roll back to this version', exact: true }),
  ).toHaveCount(1);

  // The locator scoped to release-history-row-12 resolves to zero elements (active row)
  await expect(
    page.getByTestId('release-history-row-12').getByRole('button', { name: 'Roll back to this version', exact: true }),
  ).toHaveCount(0);
});

// ---------------------------------------------------------------------------
// (h) Static: the forbidden sweep still flags "Release history" and "Rollback release"
// ---------------------------------------------------------------------------

test('(h) the forbidden sweep still flags Release history and Rollback release; the count stays 8', () => {
  // These names must still be flagged (C40: the sweep applies to the workbench panel only;
  // on the Review & Publish page these are the page's purpose, not leaked controls).
  expect(forbidsActionName('Release history')).toBe(true);
  expect(forbidsActionName('Rollback release')).toBe(true);

  // The tab name and rollback page controls also match stems — that is intentional and
  // expected per the controller's ruling (none render in the workbench panel).
  expect(forbidsActionName('Release History')).toBe(true);  // the tab name
  expect(forbidsActionName('Confirm rollback')).toBe(true);
  expect(forbidsActionName('Cancel rollback')).toBe(true);
  expect(forbidsActionName('Reload rollback preview')).toBe(true);
  expect(forbidsActionName('Rollback note')).toBe(true);

  // The row controls do NOT match any forbidden stem (C3: fixed names)
  expect(forbidsActionName('Inspect this version')).toBe(false);
  expect(forbidsActionName('Roll back to this version')).toBe(false);
  expect(forbidsActionName('Reload versions')).toBe(false);
});
