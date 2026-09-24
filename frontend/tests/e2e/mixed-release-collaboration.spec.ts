import { test, expect } from '../fixtures/base-test';
import type { Page } from '@playwright/test';
import { setupMocks } from '../helpers/setup-mocks';
import { mockSlidesResponse } from '../helpers/session-helpers';

/**
 * Mixed-release collaboration on ONE shared deck: the warning, the change-
 * provenance disclosure, the immutable Start-latest action, and the single
 * generic unavailable state that every 404 collapses into.
 *
 * Every string asserted here is written out LITERALLY rather than imported from
 * the component. A spec that imports the constant it asserts cannot catch a
 * wording change, which is the whole point of pinning the plan's required
 * vocabulary.
 *
 * PLAYWRIGHT MATCHES ACCESSIBLE NAMES BY CASE-INSENSITIVE SUBSTRING, unlike
 * Testing Library's exact `name`. `provenance rows stay individually
 * addressable` asserts that property directly: the bare actor label resolves to
 * TWO rows (one actor, two releases) while each full row name resolves to
 * exactly one, so a future nesting regression fails here rather than as a
 * mystery strict-mode violation in an unrelated spec.
 */

const SESSION_A = '11111111-1111-4111-8111-111111111111';
const SESSION_B = '22222222-2222-4222-8222-222222222222';
/** A contributor id the caller guessed. Must never be echoed back to the UI. */
const GUESSED_CONTRIBUTOR = '33333333-3333-4333-8333-333333333333';

const NEWEST = '2026-09-20T10:15:00Z';
const MIDDLE = '2026-09-19T09:05:00Z';
const OLDEST = '2026-09-18T08:00:00Z';

/** R1 owner + R2 contributor on one deck, newest first, one actor on both. */
const MIXED_HISTORY = {
  mixed_release_warning: true,
  has_legacy_evidence: false,
  groups: [
    { actor_label: 'Contributor 1', graph_version: 2, mutation_count: 3, last_mutation_at: NEWEST },
    { actor_label: 'Contributor 2', graph_version: 1, mutation_count: 2, last_mutation_at: MIDDLE },
    { actor_label: 'Contributor 1', graph_version: 1, mutation_count: 5, last_mutation_at: OLDEST },
  ],
};

const CONVERSATION_DISCLOSURE = 'Change provenance';
const CONVERSATION_LIST = 'Contributor releases';
const COLLABORATION_DISCLOSURE = 'Who changed this deck';
const COLLABORATION_LIST = 'Release history by contributor';
const WARNING_TEXT = 'This shared deck has changes from multiple Graph Versions.';

const MIXED_ROW_NAMES = [
  'Contributor 1, Graph Version 2, 3 changes',
  'Contributor 2, Graph Version 1, 2 changes',
  'Contributor 1, Graph Version 1, 5 changes',
];

const EMPTY_HISTORY = {
  mixed_release_warning: false,
  has_legacy_evidence: false,
  groups: [],
};

const UUID_PATTERN = /[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}/i;

function sessionResponse(
  sessionId: string,
  graphVersion: number | null,
  activeGraphVersion: number,
  isOlder: boolean,
  hasSlideDeck = false,
) {
  return {
    session_id: sessionId,
    title: 'Shared deck',
    created_at: new Date().toISOString(),
    has_slide_deck: hasSlideDeck,
    graph_version: graphVersion,
    active_graph_version: activeGraphVersion,
    is_older_than_active: isOlder,
  };
}

async function allowEditing(page: Page) {
  await page.route('**/api/user/current', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ username: 'test@example.com' }),
    });
  });
  await page.route(/\/api\/sessions\/[^/]+\/contributors$/, async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ contributors: [] }),
    });
  });
}

/** GET for one session id; every other method falls through to be recorded. */
async function mockSessionDetail(
  page: Page,
  sessionId: string,
  graphVersion: number | null,
  activeGraphVersion: number,
  isOlder: boolean,
  hasSlideDeck = false,
) {
  await page.route(`http://127.0.0.1:8000/api/sessions/${sessionId}`, async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(
        sessionResponse(sessionId, graphVersion, activeGraphVersion, isOlder, hasSlideDeck),
      ),
    });
  });
}

/** Registered AFTER setupMocks, so LIFO ordering gives it precedence. */
async function mockCollaborationHistory(
  page: Page,
  sessionId: string,
  body: unknown,
  status = 200,
): Promise<string[]> {
  const calls: string[] = [];
  await page.route(
    `http://127.0.0.1:8000/api/sessions/${sessionId}/collaboration-history`,
    async (route, request) => {
      calls.push(request.method());
      await route.fulfill({
        status,
        contentType: 'application/json',
        body: JSON.stringify(body),
      });
    },
  );
  return calls;
}

/** Every non-GET request touching a session id, recorded at the wire. */
function recordNonGetTo(page: Page, sessionId: string): string[] {
  const seen: string[] = [];
  page.on('request', (request) => {
    if (request.method() !== 'GET' && request.url().includes(sessionId)) {
      seen.push(`${request.method()} ${request.url()}`);
    }
  });
  return seen;
}

async function openProvenance(page: Page) {
  const disclosure = page.getByRole('button', { name: CONVERSATION_DISCLOSURE });
  await expect(disclosure).toHaveAttribute('aria-expanded', 'false');
  await disclosure.click();
  await expect(disclosure).toHaveAttribute('aria-expanded', 'true');
}

test.describe('mixed-release collaboration', () => {
  test('warns about two releases on one deck and discloses opaque provenance rows', async ({ page }) => {
    await setupMocks(page);
    await mockSessionDetail(page, SESSION_A, 1, 2, true);
    await mockCollaborationHistory(page, SESSION_A, MIXED_HISTORY);
    await allowEditing(page);

    await page.goto(`/sessions/${SESSION_A}/edit`);

    // The #261 badge and the new warning are siblings: both visible at once.
    await expect(page.getByTestId('graph-version-status')).toContainText(
      'Pinned Graph Version 1; latest is 2',
    );
    const warning = page.getByTestId('mixed-release-warning-text');
    await expect(warning).toHaveText('This shared deck has changes from multiple Graph Versions.');
    await expect(warning).toHaveAttribute('role', 'status');

    await openProvenance(page);

    const list = page.getByRole('list', { name: 'Contributor releases' });
    await expect(list).toHaveCount(1);
    // LITERAL 3, not MIXED_HISTORY.groups.length: a fixture-sourced count
    // shrinks with the fixture and so cannot fail.
    await expect(page.getByTestId('mixed-release-row')).toHaveCount(3);

    // Each FULL row name is individually addressable under substring matching.
    for (const name of MIXED_ROW_NAMES) {
      await expect(page.getByRole('listitem', { name })).toHaveCount(1);
    }
    // And the bare actor label deliberately is NOT: one actor, two releases.
    await expect(page.getByRole('listitem', { name: 'Contributor 1' })).toHaveCount(2);
    await expect(page.getByRole('listitem', { name: 'Contributor 2' })).toHaveCount(1);

    // No identity of any kind reaches the rendered surface. outerHTML, NOT
    // textContent: textContent excludes every attribute, including an
    // `aria-label` on the region root, which is where a leak would be
    // invisible to a text-only guard while still reaching the accessibility
    // tree as the region's computed name.
    const region = page.getByTestId('mixed-release-warning');
    const rendered = await region.evaluate((el) => el.outerHTML);
    expect(rendered).not.toMatch(UUID_PATTERN);
    expect(rendered).not.toContain('@');
    expect(rendered).not.toContain(SESSION_A);
  });

  test('Start latest creates a new graph-capable conversation and mutates neither the original nor its history', async ({ page }) => {
    await setupMocks(page);
    const nonGetToOriginal = recordNonGetTo(page, SESSION_A);
    const creationBodies: Array<Record<string, unknown>> = [];

    await mockSessionDetail(page, SESSION_A, 1, 2, true);
    await mockSessionDetail(page, SESSION_B, 2, 2, false);
    const originalHistoryCalls = await mockCollaborationHistory(page, SESSION_A, MIXED_HISTORY);
    await mockCollaborationHistory(page, SESSION_B, EMPTY_HISTORY);
    await page.route('http://127.0.0.1:8000/api/sessions', async (route, request) => {
      if (request.method() !== 'POST') {
        await route.fallback();
        return;
      }
      creationBodies.push(request.postDataJSON() as Record<string, unknown>);
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(sessionResponse(SESSION_B, 2, 2, false)),
      });
    });
    await allowEditing(page);

    await page.goto(`/sessions/${SESSION_A}/edit`);
    await expect(page.getByTestId('mixed-release-warning-text')).toBeVisible();

    await page.getByRole('button', { name: 'Start latest' }).click();
    await expect(page).toHaveURL(new RegExp(`/sessions/${SESSION_B}/edit`));

    // A brand-new graph-capable session, server-assigned id, nothing else sent.
    expect(creationBodies).toEqual([{ graph_capable: true }]);
    // The new conversation has no evidence of its own, so no warning.
    await expect(page.getByTestId('mixed-release-warning-text')).toHaveCount(0);
    await expect(page.getByTestId('graph-version-status')).toContainText('Pinned Graph Version 2');

    // Revisit the original: pin and evidence are byte-for-byte what they were.
    await page.goto(`/sessions/${SESSION_A}/edit`);
    await expect(page.getByTestId('graph-version-status')).toContainText(
      'Pinned Graph Version 1; latest is 2',
    );
    await expect(page.getByTestId('mixed-release-warning-text')).toBeVisible();
    await openProvenance(page);
    for (const name of MIXED_ROW_NAMES) {
      await expect(page.getByRole('listitem', { name })).toHaveCount(1);
    }

    // Immutability, asserted at the wire rather than from a disabled control:
    // no PATCH, no PUT, no DELETE, no duplicate, no repin ever touched the
    // original — only reads did.
    expect(nonGetToOriginal).toEqual([]);
    expect(originalHistoryCalls.every((method) => method === 'GET')).toBe(true);
    expect(originalHistoryCalls.length).toBeGreaterThan(0);
  });

  test('a legacy row is labelled Legacy and never described as active', async ({ page }) => {
    await setupMocks(page);
    await mockSessionDetail(page, SESSION_A, 1, 2, true);
    await mockCollaborationHistory(page, SESSION_A, {
      mixed_release_warning: false,
      has_legacy_evidence: true,
      groups: [
        { actor_label: 'Contributor 1', graph_version: null, mutation_count: 2, last_mutation_at: NEWEST },
      ],
    });
    await allowEditing(page);

    await page.goto(`/sessions/${SESSION_A}/edit`);
    // One release only, so no mixed-release warning — the disclosure still is offered.
    await expect(page.getByTestId('mixed-release-warning-text')).toHaveCount(0);
    await openProvenance(page);

    await expect(
      page.getByRole('listitem', { name: 'Contributor 1, Legacy (no graph release), 2 changes' }),
    ).toHaveCount(1);
    const rendered = (await page.getByTestId('mixed-release-warning').textContent()) ?? '';
    expect(rendered.toLowerCase()).not.toContain('active');
  });

  test('a denied history request becomes one generic unavailable state that discloses nothing', async ({ page }) => {
    await setupMocks(page);
    await mockSessionDetail(page, SESSION_A, 1, 2, true);
    // The byte-identical 404 the endpoint returns for a guessed contributor id,
    // an unauthorized real id, a deleted root and a deckless root alike. Its
    // detail names the id; the client must never read or surface that.
    const historyCalls = await mockCollaborationHistory(
      page,
      SESSION_A,
      { detail: `Session not found: ${GUESSED_CONTRIBUTOR}` },
      404,
    );
    await allowEditing(page);

    await page.goto(`/sessions/${SESSION_A}/edit`);

    const unavailable = page.getByTestId('mixed-release-unavailable');
    await expect(unavailable).toHaveText('Collaboration history unavailable');
    await expect(unavailable).toHaveAttribute('role', 'status');

    // No contributor, no version, no id — and no way to tell a real-but-denied
    // session from a fabricated one. outerHTML, so the root's own attributes
    // are covered too.
    const rendered = await page
      .getByTestId('mixed-release-warning')
      .evaluate((el) => el.outerHTML);
    expect(rendered).not.toContain(GUESSED_CONTRIBUTOR);
    expect(rendered).not.toMatch(UUID_PATTERN);
    expect(rendered).not.toMatch(/Contributor|Graph Version|Legacy/);
    await expect(page.getByRole('button', { name: CONVERSATION_DISCLOSURE })).toHaveCount(0);

    // The pinned-version badge is NOT erased by the failure.
    await expect(page.getByTestId('graph-version-status')).toContainText(
      'Pinned Graph Version 1; latest is 2',
    );

    // Exactly one request: the client never retries to probe whether the id exists.
    expect(historyCalls).toEqual(['GET']);
  });

  test('a duplicate gets the active release while the source deck stays on R1', async ({ page }) => {
    await setupMocks(page);
    const nonGetToOriginal = recordNonGetTo(page, SESSION_A);
    const duplicateBodies: Array<Record<string, unknown>> = [];

    await mockSessionDetail(page, SESSION_A, 1, 2, true, true);
    await mockSessionDetail(page, SESSION_B, 2, 2, false, true);
    await mockCollaborationHistory(page, SESSION_A, MIXED_HISTORY);
    await mockCollaborationHistory(page, SESSION_B, EMPTY_HISTORY);
    for (const sessionId of [SESSION_A, SESSION_B]) {
      await page.route(
        `http://127.0.0.1:8000/api/sessions/${sessionId}/slides`,
        async (route) => {
          await route.fulfill({
            status: 200,
            contentType: 'application/json',
            body: JSON.stringify({ session_id: sessionId, slide_deck: mockSlidesResponse.slide_deck }),
          });
        },
      );
    }
    await page.route(
      `http://127.0.0.1:8000/api/sessions/${SESSION_A}/duplicate`,
      async (route, request) => {
        duplicateBodies.push(request.postDataJSON() as Record<string, unknown>);
        await route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({
            session_id: SESSION_B,
            title: 'Shared deck (copy)',
            created_by: 'test@example.com',
            created_at: new Date().toISOString(),
            slide_count: mockSlidesResponse.slide_deck.slide_count,
            source_session_id: SESSION_A,
          }),
        });
      },
    );
    await allowEditing(page);

    await page.goto(`/sessions/${SESSION_A}/edit`);
    await expect(page.getByTestId('graph-version-status')).toContainText(
      'Pinned Graph Version 1; latest is 2',
    );

    await page.getByRole('button', { name: 'Duplicate' }).click();
    await expect(page).toHaveURL(new RegExp(`/sessions/${SESSION_B}/edit`));

    // The copy is pinned to the ACTIVE release the server chose — the client
    // never asks for a release, and never copies the source's pin.
    await expect(page.getByTestId('graph-version-status')).toContainText('Pinned Graph Version 2');
    await expect(page.getByTestId('graph-version-status')).not.toContainText('latest is');
    expect(duplicateBodies).toHaveLength(1);
    expect(Object.keys(duplicateBodies[0])).toEqual([]);

    // The source is unchanged: still R1, still older, still its own evidence.
    await page.goto(`/sessions/${SESSION_A}/edit`);
    await expect(page.getByTestId('graph-version-status')).toContainText(
      'Pinned Graph Version 1; latest is 2',
    );
    await expect(page.getByTestId('mixed-release-warning-text')).toBeVisible();

    const unexpected = nonGetToOriginal.filter(
      (entry) => !entry.endsWith(`/api/sessions/${SESSION_A}/duplicate`),
    );
    expect(unexpected).toEqual([]);
  });

  test('both AC5 surfaces stay independently addressable with the Share dialog open', async ({ page }) => {
    await setupMocks(page);
    await mockSessionDetail(page, SESSION_A, 1, 2, true);
    await mockCollaborationHistory(page, SESSION_A, MIXED_HISTORY);
    await allowEditing(page);

    await page.goto(`/sessions/${SESSION_A}/edit`);

    const conversation = page.getByTestId('mixed-release-warning');
    const collaboration = page.getByTestId('shared-deck-provenance');
    await expect(conversation).toBeVisible();
    await expect(collaboration).toHaveCount(0);

    // Expand the conversation copy BEFORE the overlay goes up. Afterwards it is
    // behind the dialog and fails a pointer-events check — asserted below.
    await conversation.getByRole('button', { name: CONVERSATION_DISCLOSURE }).click();

    // 'Share' with exact:true. The deck-title button is named 'Shared deck' in
    // this fixture, so Playwright's default substring matching resolves both and
    // the click would be a strict-mode violation.
    await page.getByRole('button', { name: 'Share', exact: true }).click();
    await expect(collaboration).toBeVisible();
    await expect(conversation).toBeVisible();

    // Coexistence is real and asserted rather than assumed: the same mandated
    // sentence is on screen twice, so any unscoped locator for it is ambiguous.
    await expect(page.getByTestId('mixed-release-warning-text')).toHaveCount(2);
    await expect(page.getByText(WARNING_TEXT)).toHaveCount(2);
    await expect(page.getByTestId('mixed-release-disclosure')).toHaveCount(2);

    // And yet every accessible NAME still resolves to exactly one element under
    // Playwright's DEFAULT substring matching — because the two surfaces use
    // wholly distinct wording rather than a suffix.
    await expect(page.getByRole('button', { name: CONVERSATION_DISCLOSURE })).toHaveCount(1);
    await expect(page.getByRole('button', { name: COLLABORATION_DISCLOSURE })).toHaveCount(1);
    await expect(page.getByRole('list', { name: CONVERSATION_LIST })).toHaveCount(1);

    // One live region, though the sentence appears twice: only the conversation
    // surface announces, so the same warning is not read out twice.
    await expect(page.getByRole('status')).toHaveCount(1);

    // THE REAL OBSTACLE: the conversation copy is visible but sits behind the
    // overlay, so it cannot receive pointer events. A trial click runs the full
    // actionability check without acting, and must fail.
    let blockedByOverlay = false;
    try {
      await conversation
        .getByRole('button', { name: CONVERSATION_DISCLOSURE })
        .click({ trial: true, timeout: 2000 });
    } catch {
      blockedByOverlay = true;
    }
    expect(blockedByOverlay).toBe(true);
    // Its expanded state survives regardless — reads are unaffected.
    await expect(
      conversation.getByRole('button', { name: CONVERSATION_DISCLOSURE }),
    ).toHaveAttribute('aria-expanded', 'true');

    // The dialog copy is on top, so a CONTAINER-SCOPED interaction works. This
    // is the fix for the overlay, not renaming.
    await collaboration.getByRole('button', { name: COLLABORATION_DISCLOSURE }).click();
    await expect(collaboration.getByRole('list', { name: COLLABORATION_LIST })).toHaveCount(1);
    await expect(collaboration.getByTestId('mixed-release-row')).toHaveCount(3);
    for (const name of MIXED_ROW_NAMES) {
      await expect(collaboration.getByRole('listitem', { name })).toHaveCount(1);
      await expect(conversation.getByRole('listitem', { name })).toHaveCount(1);
    }
    // Row names are shared vocabulary, so unscoped they are ambiguous BY
    // DESIGN once both surfaces are expanded. Recorded so nobody "fixes" it by
    // renaming rows per surface.
    await expect(page.getByTestId('mixed-release-row')).toHaveCount(6);

    // No identity leaks on the second surface either.
    const dialogHtml = await collaboration.evaluate((el) => el.outerHTML);
    expect(dialogHtml).not.toMatch(UUID_PATTERN);
    expect(dialogHtml).not.toContain('@');
    expect(dialogHtml).not.toContain(SESSION_A);
  });
});
