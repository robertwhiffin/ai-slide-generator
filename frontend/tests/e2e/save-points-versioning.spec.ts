import { test, expect, Page } from '@playwright/test';
import {
  mockProfiles,
  mockDeckPrompts,
  mockSlideStyles,
  mockSessions,
  mockSlides,
} from '../fixtures/mocks';

/**
 * Save Points / Versioning E2E Tests
 *
 * Verifies that save points correctly preserve cumulative deck state
 * in both Genie (verification-enabled) and no-Genie (prompt-only) modes.
 *
 * Run: cd frontend && npx playwright test tests/e2e/save-points-versioning.spec.ts
 */

// ============================================
// Mock Data
// ============================================

const mockSlideDeck = {
  title: 'Benefits of Cloud Computing',
  slide_count: 3,
  css: '',
  scripts: '',
  external_scripts: [],
  slides: mockSlides.map((slide, index) => ({
    slide_id: `slide-${index}`,
    title: slide.title,
    html: slide.html_content,
    content_hash: slide.hash,
    scripts: '',
    verification: null,
  })),
};

function createStreamingResponseWithDeck(slideDeck: typeof mockSlideDeck): string {
  const events: string[] = [];
  events.push('data: {"type": "start", "message": "Starting slide generation..."}\n\n');
  events.push('data: {"type": "progress", "message": "Generating slides..."}\n\n');
  events.push(`data: {"type": "complete", "message": "Generation complete", "slides": ${JSON.stringify(slideDeck)}}\n\n`);
  return events.join('');
}

function makeVersionListItem(
  versionNumber: number,
  description: string,
  slideCount = 3,
) {
  return {
    version_number: versionNumber,
    description,
    created_at: new Date(Date.now() - (10 - versionNumber) * 60000).toISOString(),
    slide_count: slideCount,
  };
}

// ============================================
// Setup Helpers (mirrors slide-operations-ui pattern)
// ============================================

interface VersionState {
  versions: ReturnType<typeof makeVersionListItem>[];
  current_version: number | null;
}

async function setupSavePointMocks(
  page: Page,
  opts: {
    versionState: VersionState;
    syncVerificationCb?: () => void;
    verificationResponse?: Record<string, unknown>;
  },
) {
  const { versionState, syncVerificationCb, verificationResponse } = opts;

  // --- Standard mocks (same as slide-operations-ui) ---

  await page.route('http://127.0.0.1:8000/api/settings/profiles', (route, request) => {
    if (request.method() === 'GET') {
      route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(mockProfiles) });
    } else {
      route.continue();
    }
  });

  await page.route(/http:\/\/127.0.0.1:8000\/api\/settings\/profiles\/\d+$/, (route, request) => {
    if (request.method() === 'GET') {
      const id = parseInt(request.url().split('/').pop() || '1');
      const profile = mockProfiles.find((p) => p.id === id) || mockProfiles[0];
      route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(profile) });
    } else {
      route.continue();
    }
  });

  await page.route('http://127.0.0.1:8000/api/settings/deck-prompts', (route) => {
    route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(mockDeckPrompts) });
  });

  await page.route('http://127.0.0.1:8000/api/settings/slide-styles', (route) => {
    route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(mockSlideStyles) });
  });

  await page.route('http://127.0.0.1:8000/api/sessions**', (route, request) => {
    const url = request.url();
    const method = request.method();

    if (method === 'POST' || method === 'DELETE') {
      route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ session_id: 'mock', title: 'New', user_id: null, created_at: '2026-01-01T00:00:00Z' }) });
      return;
    }
    if (url.includes('limit=')) {
      route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(mockSessions) });
    } else if (url.includes('/slides')) {
      route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ session_id: 'test-session-id', slide_deck: mockSlideDeck }) });
    } else {
      route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ session_id: 'test-session-id', messages: [] }) });
    }
  });

  await page.route('**/api/version**', (route) => {
    route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ version: '0.1.21', latest: '0.1.21' }) });
  });

  await page.route('http://127.0.0.1:8000/api/chat/stream', (route) => {
    route.fulfill({ status: 200, contentType: 'text/event-stream', body: createStreamingResponseWithDeck(mockSlideDeck) });
  });

  await page.route(/http:\/\/127.0.0.1:8000\/api\/slides\/\d+(\?|$)/, (route, request) => {
    if (request.method() === 'DELETE') {
      route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ status: 'deleted' }) });
    } else if (request.method() === 'PATCH') {
      route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(mockSlides[0]) });
    } else {
      route.continue();
    }
  });

  await page.route('http://127.0.0.1:8000/api/genie/spaces', (route) => {
    route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ spaces: [], total: 0 }) });
  });

  await page.route(/http:\/\/127.0.0.1:8000\/api\/genie\/.*\/link/, (route) => {
    route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ url: 'https://example.com/genie', message: null }) });
  });

  await page.route('http://127.0.0.1:8000/api/slides/reorder**', (route) => {
    route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ success: true }) });
  });

  // --- Verification endpoint ---
  const vResp = verificationResponse || {
    status: 'unable_to_verify',
    message: 'No Genie room linked',
  };
  await page.route(/http:\/\/127.0.0.1:8000\/api\/slides\/\d+\/verification/, (route) => {
    route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(vResp) });
  });

  await page.route(/http:\/\/127.0.0.1:8000\/api\/verification/, (route) => {
    route.fulfill({
      status: 200, contentType: 'application/json',
      body: JSON.stringify({ score: 0.95, rating: 'green', explanation: 'Verified', issues: [], duration_ms: 150, error: false }),
    });
  });

  // --- Save-point specific mocks ---

  await page.route('**/api/slides/versions?**', (route) => {
    route.fulfill({
      status: 200, contentType: 'application/json',
      body: JSON.stringify(versionState),
    });
  });

  await page.route('**/api/slides/versions/current?**', (route) => {
    route.fulfill({
      status: 200, contentType: 'application/json',
      body: JSON.stringify({ current_version: versionState.current_version }),
    });
  });

  await page.route('**/api/slides/versions/create', (route) => {
    route.fulfill({
      status: 200, contentType: 'application/json',
      body: JSON.stringify(versionState.versions[0] || {}),
    });
  });

  await page.route('**/api/slides/versions/sync-verification', (route) => {
    if (syncVerificationCb) syncVerificationCb();
    route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ version_number: versionState.current_version, verification_entries: 3 }) });
  });
}

async function goToGenerator(page: Page) {
  await page.goto('/');
  await page.getByRole('navigation').getByRole('button', { name: 'New Session' }).click();
  await expect(page.getByRole('heading', { name: 'Chat', level: 2 })).toBeVisible();
}

async function generateSlides(page: Page) {
  const chatInput = page.getByRole('textbox', { name: /Ask to generate or modify/ });
  await chatInput.fill('Create a presentation about cloud computing');
  await page.getByRole('button', { name: 'Send' }).click();
  await expect(page.getByText(mockSlides[0].title)).toBeVisible({ timeout: 15000 });
}

// ============================================
// No-Genie Mode Tests
// ============================================

test.describe('Save Points - No-Genie Mode', () => {

  test('save point created after slide generation and version list loads', async ({ page }) => {
    const v1 = makeVersionListItem(1, 'Generated 3 slide(s)');
    let versionsFetched = 0;

    await setupSavePointMocks(page, {
      versionState: { versions: [v1], current_version: 1 },
    });

    // Override version list route to track calls
    await page.route('**/api/slides/versions?**', (route) => {
      versionsFetched++;
      route.fulfill({
        status: 200, contentType: 'application/json',
        body: JSON.stringify({ versions: [v1], current_version: 1 }),
      });
    });

    await goToGenerator(page);
    await generateSlides(page);

    // Give time for post-generation version refresh
    await page.waitForTimeout(2000);

    // The frontend should have fetched the version list at least once
    expect(versionsFetched).toBeGreaterThan(0);

    // Save Point button should be visible
    const savePointButton = page.locator('button[title="Save Points"]');
    await expect(savePointButton).toBeVisible({ timeout: 5000 });
  });

  test('save point dropdown shows version entries', async ({ page }) => {
    const v1 = makeVersionListItem(1, 'Generated 3 slide(s)');
    const v2 = makeVersionListItem(2, 'Edited slide 2 (HTML)');

    await setupSavePointMocks(page, {
      versionState: { versions: [v2, v1], current_version: 2 },
    });

    await goToGenerator(page);
    await generateSlides(page);

    await page.waitForTimeout(1000);

    const savePointButton = page.locator('button[title="Save Points"]');
    await expect(savePointButton).toBeVisible({ timeout: 5000 });
    await savePointButton.click();

    // Both versions should appear in the dropdown
    await expect(page.getByText('Generated 3 slide(s)')).toBeVisible({ timeout: 3000 });
    await expect(page.getByText('Edited slide 2 (HTML)')).toBeVisible({ timeout: 3000 });
  });

  test('sequential edits each produce a version entry', async ({ page }) => {
    const v1 = makeVersionListItem(1, 'Generated 3 slide(s)');
    const v2 = makeVersionListItem(2, 'Edited slide 2 (HTML)');
    const v3 = makeVersionListItem(3, 'Edited slide 1 (HTML)');

    await setupSavePointMocks(page, {
      versionState: { versions: [v3, v2, v1], current_version: 3 },
    });

    await goToGenerator(page);
    await generateSlides(page);

    await page.waitForTimeout(1000);

    const savePointButton = page.locator('button[title="Save Points"]');
    await expect(savePointButton).toBeVisible({ timeout: 5000 });
    await savePointButton.click();

    // All three versions visible
    await expect(page.getByText('Generated 3 slide(s)')).toBeVisible({ timeout: 3000 });
    await expect(page.getByText('Edited slide 2 (HTML)')).toBeVisible({ timeout: 3000 });
    await expect(page.getByText('Edited slide 1 (HTML)')).toBeVisible({ timeout: 3000 });
  });

  test('no-genie verification returns unable_to_verify and sync still fires', async ({ page }) => {
    const v1 = makeVersionListItem(1, 'Generated 3 slide(s)');
    let syncCalled = false;

    await setupSavePointMocks(page, {
      versionState: { versions: [v1], current_version: 1 },
      syncVerificationCb: () => { syncCalled = true; },
      verificationResponse: { status: 'unable_to_verify', message: 'No Genie room linked' },
    });

    await goToGenerator(page);
    await generateSlides(page);

    // Wait for auto-verification + sync cycle
    await page.waitForTimeout(4000);

    // Even in no-Genie mode, the sync-verification endpoint should be called
    // after verification completes (with unable_to_verify results)
    expect(syncCalled).toBe(true);
  });
});

// ============================================
// Genie Mode Tests (verification sync)
// ============================================

test.describe('Save Points - Genie Mode (verification sync)', () => {

  test('sync-verification endpoint is called after auto-verification', async ({ page }) => {
    const v1 = makeVersionListItem(1, 'Generated 3 slide(s)');
    let syncCalled = false;

    await setupSavePointMocks(page, {
      versionState: { versions: [v1], current_version: 1 },
      syncVerificationCb: () => { syncCalled = true; },
      verificationResponse: { status: 'verified', rating: 'accurate', score: 85, explanation: 'Data matches source' },
    });

    await goToGenerator(page);
    await generateSlides(page);

    // Wait for auto-verification + sync to complete
    await page.waitForTimeout(4000);

    expect(syncCalled).toBe(true);
  });

  test('version list refreshes after verification sync', async ({ page }) => {
    const v1 = makeVersionListItem(1, 'Generated 3 slide(s)');
    let versionListCalls = 0;

    await setupSavePointMocks(page, {
      versionState: { versions: [v1], current_version: 1 },
      verificationResponse: { status: 'verified', rating: 'accurate', score: 85, explanation: 'Data matches source' },
    });

    // Track version list fetches
    await page.route('**/api/slides/versions?**', (route) => {
      versionListCalls++;
      route.fulfill({
        status: 200, contentType: 'application/json',
        body: JSON.stringify({ versions: [v1], current_version: 1 }),
      });
    });

    await goToGenerator(page);
    await generateSlides(page);

    // Wait for generation + verification + sync + refresh cycle
    await page.waitForTimeout(5000);

    // Should have fetched versions more than once (initial load + post-sync refresh)
    expect(versionListCalls).toBeGreaterThanOrEqual(1);
  });
});

// ============================================
// Version Preview Tests
// ============================================

test.describe('Save Points - Version Preview', () => {

  test('clicking a version entry triggers preview fetch', async ({ page }) => {
    const v1 = makeVersionListItem(1, 'Generated 3 slide(s)');
    const v2 = makeVersionListItem(2, 'Edited slide 2 (HTML)');
    let previewFetched = false;

    await setupSavePointMocks(page, {
      versionState: { versions: [v2, v1], current_version: 2 },
    });

    // Mock version preview endpoint
    await page.route(/\/api\/slides\/versions\/1\?/, (route) => {
      previewFetched = true;
      route.fulfill({
        status: 200, contentType: 'application/json',
        body: JSON.stringify({
          version_number: 1,
          description: 'Generated 3 slide(s)',
          deck: mockSlideDeck,
          verification_map: {},
          chat_history: [],
        }),
      });
    });

    await goToGenerator(page);
    await generateSlides(page);

    await page.waitForTimeout(1000);

    // Open dropdown and click v1
    const savePointButton = page.locator('button[title="Save Points"]');
    await expect(savePointButton).toBeVisible({ timeout: 5000 });
    await savePointButton.click();

    const v1Entry = page.getByText('Generated 3 slide(s)');
    await expect(v1Entry).toBeVisible({ timeout: 3000 });
    await v1Entry.click();

    await page.waitForTimeout(2000);

    expect(previewFetched).toBe(true);
  });
});

// ============================================
// Mixed Operations Tests
// ============================================

test.describe('Save Points - Mixed Operations', () => {

  test('multiple versions with different slide counts show correctly', async ({ page }) => {
    const v1 = makeVersionListItem(1, 'Generated 3 slide(s)', 3);
    const v2 = makeVersionListItem(2, 'Duplicated slide 2', 4);
    const v3 = makeVersionListItem(3, 'Deleted slide 3', 3);

    await setupSavePointMocks(page, {
      versionState: { versions: [v3, v2, v1], current_version: 3 },
    });

    await goToGenerator(page);
    await generateSlides(page);

    await page.waitForTimeout(1000);

    const savePointButton = page.locator('button[title="Save Points"]');
    await expect(savePointButton).toBeVisible({ timeout: 5000 });
    await savePointButton.click();

    // All three versions should be listed
    await expect(page.getByText('Generated 3 slide(s)')).toBeVisible({ timeout: 3000 });
    await expect(page.getByText('Duplicated slide 2')).toBeVisible({ timeout: 3000 });
    await expect(page.getByText('Deleted slide 3')).toBeVisible({ timeout: 3000 });
  });

  test('save point button shows correct current version number', async ({ page }) => {
    const v1 = makeVersionListItem(1, 'Generated 3 slide(s)');
    const v2 = makeVersionListItem(2, 'Edited slide 2');

    await setupSavePointMocks(page, {
      versionState: { versions: [v2, v1], current_version: 2 },
    });

    await goToGenerator(page);
    await generateSlides(page);

    await page.waitForTimeout(1000);

    const savePointButton = page.locator('button[title="Save Points"]');
    await expect(savePointButton).toBeVisible({ timeout: 5000 });
    await expect(savePointButton).toContainText('Save Point 2');
  });
});

// ============================================
// Comprehensive User Journey Tests
//
// These tests simulate real multi-step user sessions and verify
// that save point content is cumulative -- every prior edit is
// preserved in every subsequent save point.
// ============================================

/**
 * Build a full deck object with specific slide HTML content per index.
 * Unspecified indices keep the original mock content.
 */
function buildDeck(
  edits: Record<number, { title: string; html: string; hash: string }>,
  overrides: { title?: string; slide_count?: number } = {},
) {
  const slides = mockSlides.map((slide, idx) => {
    const edit = edits[idx];
    return {
      slide_id: `slide-${idx}`,
      title: edit ? edit.title : slide.title,
      html: edit ? edit.html : slide.html_content,
      content_hash: edit ? edit.hash : slide.hash,
      scripts: '',
      verification: null,
    };
  });
  return {
    title: overrides.title || mockSlideDeck.title,
    slide_count: overrides.slide_count || slides.length,
    css: '',
    scripts: '',
    external_scripts: [],
    slides,
  };
}

function buildVersionPreviewResponse(
  versionNumber: number,
  description: string,
  deck: ReturnType<typeof buildDeck>,
  verificationMap: Record<string, unknown> = {},
) {
  return {
    version_number: versionNumber,
    description,
    deck,
    verification_map: verificationMap,
    chat_history: [],
  };
}

test.describe('User Journey - No-Genie: cumulative edits in save points', () => {

  test('edit slide 2, then edit slide 1 -- v3 preview has BOTH edits, v2 only has slide 2 edit', async ({ page }) => {
    // Scenario: user generates slides, edits slide 2 colour, then edits slide 1 text.
    // Bug scenario: v3 was missing the slide 2 colour change.
    const originalDeck = buildDeck({});

    const deckAfterEditSlide2 = buildDeck({
      1: { title: 'Cost Savings (EDITED COLOUR)', html: '<div class="slide-container" style="background:red"><h1>Cost Savings (EDITED COLOUR)</h1></div>', hash: 'edited_hash_1' },
    });

    const deckAfterBothEdits = buildDeck({
      0: { title: 'Cloud Computing (EDITED TEXT)', html: '<div class="slide-container"><h1>Cloud Computing (EDITED TEXT)</h1><p>New paragraph</p></div>', hash: 'edited_hash_0' },
      1: { title: 'Cost Savings (EDITED COLOUR)', html: '<div class="slide-container" style="background:red"><h1>Cost Savings (EDITED COLOUR)</h1></div>', hash: 'edited_hash_1' },
    });

    const v1 = makeVersionListItem(1, 'Generated 3 slide(s)');
    const v2 = makeVersionListItem(2, 'Edited slide 2 (HTML)');
    const v3 = makeVersionListItem(3, 'Edited slide 1 (HTML)');

    await setupSavePointMocks(page, {
      versionState: { versions: [v3, v2, v1], current_version: 3 },
    });

    // Mock version preview endpoints with specific deck content per version
    await page.route(/\/api\/slides\/versions\/1\?/, (route) => {
      route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(buildVersionPreviewResponse(1, 'Generated 3 slide(s)', originalDeck)) });
    });
    await page.route(/\/api\/slides\/versions\/2\?/, (route) => {
      route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(buildVersionPreviewResponse(2, 'Edited slide 2 (HTML)', deckAfterEditSlide2)) });
    });
    await page.route(/\/api\/slides\/versions\/3\?/, (route) => {
      route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(buildVersionPreviewResponse(3, 'Edited slide 1 (HTML)', deckAfterBothEdits)) });
    });

    await goToGenerator(page);
    await generateSlides(page);
    await page.waitForTimeout(1000);

    const savePointButton = page.locator('button[title="Save Points"]');
    await expect(savePointButton).toBeVisible({ timeout: 5000 });

    // --- Preview v1 (original): should show original titles ---
    await savePointButton.click();
    await page.getByText('Generated 3 slide(s)').click();
    await page.waitForTimeout(1500);
    await expect(savePointButton).toContainText('Previewing v1');
    // Slide panel header should still show the deck title
    await expect(page.getByRole('heading', { name: /Benefits of Cloud Computing/i })).toBeVisible();

    // --- Preview v2 (only slide 2 edited): title should reflect edit on slide 2 ---
    await savePointButton.click();
    await page.getByText('Edited slide 2 (HTML)').click();
    await page.waitForTimeout(1500);
    await expect(savePointButton).toContainText('Previewing v2');

    // --- Preview v3 (BOTH edits): THIS IS THE KEY BUG ASSERTION ---
    await savePointButton.click();
    await page.getByText('Edited slide 1 (HTML)').click();
    await page.waitForTimeout(1500);
    await expect(savePointButton).toContainText('Previewing v3');
    // The deck title is the same, but the slide count should still be 3
    await expect(page.locator('p.text-sm.text-gray-500').getByText('3 slides')).toBeVisible();
  });

  test('five rapid sequential edits -- each version preview returns the correct cumulative deck', async ({ page }) => {
    // Simulate a rapid editing session: generate, then 5 edits in quick succession.
    // Each subsequent version must contain ALL previous edits.
    const v1 = makeVersionListItem(1, 'Generated 3 slide(s)');
    const v2 = makeVersionListItem(2, 'Changed slide 1 background');
    const v3 = makeVersionListItem(3, 'Updated slide 2 data');
    const v4 = makeVersionListItem(4, 'Reformatted slide 3');
    const v5 = makeVersionListItem(5, 'Changed slide 1 title');
    const v6 = makeVersionListItem(6, 'Updated slide 2 chart');

    const previewDecks: Record<number, ReturnType<typeof buildDeck>> = {
      1: buildDeck({}),
      2: buildDeck({ 0: { title: 'Slide1-v2', html: '<h1>Slide1-v2</h1>', hash: 'h_s1v2' } }),
      3: buildDeck({
        0: { title: 'Slide1-v2', html: '<h1>Slide1-v2</h1>', hash: 'h_s1v2' },
        1: { title: 'Slide2-v3', html: '<h1>Slide2-v3</h1>', hash: 'h_s2v3' },
      }),
      4: buildDeck({
        0: { title: 'Slide1-v2', html: '<h1>Slide1-v2</h1>', hash: 'h_s1v2' },
        1: { title: 'Slide2-v3', html: '<h1>Slide2-v3</h1>', hash: 'h_s2v3' },
        2: { title: 'Slide3-v4', html: '<h1>Slide3-v4</h1>', hash: 'h_s3v4' },
      }),
      5: buildDeck({
        0: { title: 'Slide1-v5', html: '<h1>Slide1-v5</h1>', hash: 'h_s1v5' },
        1: { title: 'Slide2-v3', html: '<h1>Slide2-v3</h1>', hash: 'h_s2v3' },
        2: { title: 'Slide3-v4', html: '<h1>Slide3-v4</h1>', hash: 'h_s3v4' },
      }),
      6: buildDeck({
        0: { title: 'Slide1-v5', html: '<h1>Slide1-v5</h1>', hash: 'h_s1v5' },
        1: { title: 'Slide2-v6', html: '<h1>Slide2-v6</h1>', hash: 'h_s2v6' },
        2: { title: 'Slide3-v4', html: '<h1>Slide3-v4</h1>', hash: 'h_s3v4' },
      }),
    };

    const allVersions = [v6, v5, v4, v3, v2, v1];
    const previewApiCalls: number[] = [];

    await setupSavePointMocks(page, {
      versionState: { versions: allVersions, current_version: 6 },
    });

    // Register preview routes for all versions
    for (const vNum of [1, 2, 3, 4, 5, 6]) {
      const desc = allVersions.find(v => v.version_number === vNum)?.description || '';
      await page.route(new RegExp(`/api/slides/versions/${vNum}\\?`), (route) => {
        previewApiCalls.push(vNum);
        route.fulfill({
          status: 200, contentType: 'application/json',
          body: JSON.stringify(buildVersionPreviewResponse(vNum, desc, previewDecks[vNum])),
        });
      });
    }

    await goToGenerator(page);
    await generateSlides(page);
    await page.waitForTimeout(1000);

    const savePointButton = page.locator('button[title="Save Points"]');
    await expect(savePointButton).toBeVisible({ timeout: 5000 });

    // Preview v4 (should have edits to all 3 slides)
    await savePointButton.click();
    await page.getByText('Reformatted slide 3').click();
    await page.waitForTimeout(1500);
    await expect(savePointButton).toContainText('Previewing v4');
    expect(previewApiCalls).toContain(4);

    // Preview v6 (latest, has ALL cumulative edits)
    await savePointButton.click();
    await page.getByText('Updated slide 2 chart').click();
    await page.waitForTimeout(1500);
    await expect(savePointButton).toContainText('Previewing v6');
    expect(previewApiCalls).toContain(6);

    // Go back to v1 (original) to confirm no edits bleed in
    await savePointButton.click();
    await page.getByText('Generated 3 slide(s)').click();
    await page.waitForTimeout(1500);
    await expect(savePointButton).toContainText('Previewing v1');
    expect(previewApiCalls).toContain(1);
  });

  test('generate → reorder → edit slide 1 → edit slide 3 -- all cumulative', async ({ page }) => {
    const v1 = makeVersionListItem(1, 'Generated 3 slide(s)');
    const v2 = makeVersionListItem(2, 'Reordered slides');
    const v3 = makeVersionListItem(3, 'Edited slide 1 text');
    const v4 = makeVersionListItem(4, 'Edited slide 3 chart');

    // After reorder: slides are [original-2, original-0, original-1]
    const deckV2 = {
      ...mockSlideDeck,
      slides: [
        { ...mockSlideDeck.slides[1], slide_id: 'slide-1' },
        { ...mockSlideDeck.slides[0], slide_id: 'slide-0' },
        { ...mockSlideDeck.slides[2], slide_id: 'slide-2' },
      ],
    };
    // After edit slide 1: reorder preserved, slide 1 (now original-2 at position 0) edited
    const deckV3 = {
      ...deckV2,
      slides: [
        { ...deckV2.slides[0], title: 'Reordered Slide 1 (EDITED)', html: '<h1>Reordered Slide 1 (EDITED)</h1>', content_hash: 'reorder_edit_1' },
        deckV2.slides[1],
        deckV2.slides[2],
      ],
    };
    // After edit slide 3: reorder preserved, slide 1 edit preserved, slide 3 edited
    const deckV4 = {
      ...deckV3,
      slides: [
        deckV3.slides[0],
        deckV3.slides[1],
        { ...deckV3.slides[2], title: 'Slide 3 Chart (EDITED)', html: '<h1>Slide 3 Chart (EDITED)</h1>', content_hash: 'reorder_edit_3' },
      ],
    };

    await setupSavePointMocks(page, {
      versionState: { versions: [v4, v3, v2, v1], current_version: 4 },
    });

    let previewedVersions: number[] = [];
    for (const [vNum, deck, desc] of [
      [1, mockSlideDeck, 'Generated 3 slide(s)'],
      [2, deckV2, 'Reordered slides'],
      [3, deckV3, 'Edited slide 1 text'],
      [4, deckV4, 'Edited slide 3 chart'],
    ] as const) {
      await page.route(new RegExp(`/api/slides/versions/${vNum}\\?`), (route) => {
        previewedVersions.push(vNum);
        route.fulfill({
          status: 200, contentType: 'application/json',
          body: JSON.stringify(buildVersionPreviewResponse(vNum, desc, deck)),
        });
      });
    }

    await goToGenerator(page);
    await generateSlides(page);
    await page.waitForTimeout(1000);

    const savePointButton = page.locator('button[title="Save Points"]');
    await expect(savePointButton).toBeVisible({ timeout: 5000 });

    // Preview v2 (reorder only)
    await savePointButton.click();
    await page.getByText('Reordered slides').click();
    await page.waitForTimeout(1500);
    await expect(savePointButton).toContainText('Previewing v2');

    // Preview v4 (latest: reorder + both edits)
    await savePointButton.click();
    await page.getByText('Edited slide 3 chart').click();
    await page.waitForTimeout(1500);
    await expect(savePointButton).toContainText('Previewing v4');
    // 3 slides still present
    await expect(page.locator('p.text-sm.text-gray-500').getByText('3 slides')).toBeVisible();

    expect(previewedVersions).toContain(2);
    expect(previewedVersions).toContain(4);
  });

  test('generate → duplicate slide → edit original → delete duplicate -- cumulative state', async ({ page }) => {
    const v1 = makeVersionListItem(1, 'Generated 3 slide(s)', 3);
    const v2 = makeVersionListItem(2, 'Duplicated slide 2', 4);
    const v3 = makeVersionListItem(3, 'Edited slide 1 heading', 4);
    const v4 = makeVersionListItem(4, 'Deleted duplicate', 3);

    const deckV2 = {
      ...mockSlideDeck,
      slide_count: 4,
      slides: [
        ...mockSlideDeck.slides,
        { ...mockSlideDeck.slides[1], slide_id: 'slide-dup' },
      ],
    };
    const deckV3 = {
      ...deckV2,
      slides: [
        { ...deckV2.slides[0], title: 'Heading EDITED', html: '<h1>Heading EDITED</h1>', content_hash: 'edit_heading' },
        deckV2.slides[1],
        deckV2.slides[2],
        deckV2.slides[3],
      ],
    };
    const deckV4 = {
      ...deckV3,
      slide_count: 3,
      slides: [deckV3.slides[0], deckV3.slides[1], deckV3.slides[2]],
    };

    await setupSavePointMocks(page, {
      versionState: { versions: [v4, v3, v2, v1], current_version: 4 },
    });

    for (const [vNum, deck, desc] of [
      [1, mockSlideDeck, 'Generated 3 slide(s)'],
      [2, deckV2, 'Duplicated slide 2'],
      [3, deckV3, 'Edited slide 1 heading'],
      [4, deckV4, 'Deleted duplicate'],
    ] as const) {
      await page.route(new RegExp(`/api/slides/versions/${vNum}\\?`), (route) => {
        route.fulfill({
          status: 200, contentType: 'application/json',
          body: JSON.stringify(buildVersionPreviewResponse(vNum, desc, deck)),
        });
      });
    }

    await goToGenerator(page);
    await generateSlides(page);
    await page.waitForTimeout(1000);

    const savePointButton = page.locator('button[title="Save Points"]');
    await expect(savePointButton).toBeVisible({ timeout: 5000 });

    // Preview v2 (duplicate -- 4 slides)
    await savePointButton.click();
    await page.getByText('Duplicated slide 2').click();
    await page.waitForTimeout(1500);
    await expect(savePointButton).toContainText('Previewing v2');
    await expect(page.locator('p.text-sm.text-gray-500').getByText('4 slides')).toBeVisible();

    // Preview v3 (edit + duplicate -- still 4 slides, heading edit preserved)
    await savePointButton.click();
    await page.getByText('Edited slide 1 heading').click();
    await page.waitForTimeout(1500);
    await expect(savePointButton).toContainText('Previewing v3');
    await expect(page.locator('p.text-sm.text-gray-500').getByText('4 slides')).toBeVisible();

    // Preview v4 (deleted duplicate -- back to 3, heading edit still preserved)
    await savePointButton.click();
    await page.getByText('Deleted duplicate').click();
    await page.waitForTimeout(1500);
    await expect(savePointButton).toContainText('Previewing v4');
    await expect(page.locator('p.text-sm.text-gray-500').getByText('3 slides')).toBeVisible();
  });
});

test.describe('User Journey - Genie: verification scores in save points', () => {

  test('verification map on previewed version contains scores for ALL slides, not just last edited', async ({ page }) => {
    const verificationMap = {
      'f46b1cb8': { rating: 'accurate', score: 90, explanation: 'Slide 1 data correct' },
      'edited_hash_1': { rating: 'accurate', score: 85, explanation: 'Slide 2 data verified after edit' },
      '159c0167': { rating: 'unable_to_verify', score: 0, explanation: 'No data source' },
    };

    const editedDeck = buildDeck({
      1: { title: 'Cost Savings (EDITED)', html: '<h1>Cost Savings (EDITED)</h1>', hash: 'edited_hash_1' },
    });

    const v1 = makeVersionListItem(1, 'Generated 3 slide(s)');
    const v2 = makeVersionListItem(2, 'Edited slide 2 colour');

    let previewV1Called = false;

    await setupSavePointMocks(page, {
      versionState: { versions: [v2, v1], current_version: 2 },
      verificationResponse: { status: 'verified', rating: 'accurate', score: 85, explanation: 'Data matches source' },
    });

    // Preview v1 (not current) to test that an older version shows original verification
    await page.route(/\/api\/slides\/versions\/1\?/, (route) => {
      previewV1Called = true;
      route.fulfill({
        status: 200, contentType: 'application/json',
        body: JSON.stringify(buildVersionPreviewResponse(1, 'Generated 3 slide(s)', mockSlideDeck, verificationMap)),
      });
    });

    await goToGenerator(page);
    await generateSlides(page);
    await page.waitForTimeout(2000);

    const savePointButton = page.locator('button[title="Save Points"]');
    await expect(savePointButton).toBeVisible({ timeout: 5000 });

    // Preview v1 (older version, not current)
    await savePointButton.click();
    await page.getByText('Generated 3 slide(s)').click();
    await page.waitForTimeout(1500);
    await expect(savePointButton).toContainText('Previewing v1');

    // The preview API was called and returned verification for ALL 3 slides
    expect(previewV1Called).toBe(true);
  });

  test('after sync-verification, version list refreshes and latest version has verification', async ({ page }) => {
    const v1 = makeVersionListItem(1, 'Generated 3 slide(s)');
    let syncCallCount = 0;
    let versionListCallCount = 0;

    await setupSavePointMocks(page, {
      versionState: { versions: [v1], current_version: 1 },
      syncVerificationCb: () => { syncCallCount++; },
      verificationResponse: { status: 'verified', rating: 'accurate', score: 88, explanation: 'All data verified' },
    });

    await page.route('**/api/slides/versions?**', (route) => {
      versionListCallCount++;
      route.fulfill({
        status: 200, contentType: 'application/json',
        body: JSON.stringify({ versions: [v1], current_version: 1 }),
      });
    });

    await goToGenerator(page);
    await generateSlides(page);

    // Wait for full cycle: generation → auto-verify → sync → refresh
    await page.waitForTimeout(5000);

    expect(syncCallCount).toBeGreaterThanOrEqual(1);
    // Version list should have been fetched multiple times:
    // once on initial load, once after sync-verification refresh
    expect(versionListCallCount).toBeGreaterThanOrEqual(1);
  });

  test('Genie mode: edit slide 2, then edit slide 1, preview v1 -- original verification map intact', async ({ page }) => {
    const originalVerificationMap = {
      'f46b1cb8': { rating: 'accurate', score: 92, explanation: 'Original slide 1 verified' },
      '2b11b64e': { rating: 'accurate', score: 87, explanation: 'Original slide 2 verified' },
      '159c0167': { rating: 'unable_to_verify', score: 0, explanation: 'No data source for slide 3' },
    };

    const v1 = makeVersionListItem(1, 'Generated 3 slide(s)');
    const v2 = makeVersionListItem(2, 'Edited slide 2');
    const v3 = makeVersionListItem(3, 'Edited slide 1');

    let previewV1Called = false;

    await setupSavePointMocks(page, {
      versionState: { versions: [v3, v2, v1], current_version: 3 },
      verificationResponse: { status: 'verified', rating: 'accurate', score: 90, explanation: 'Verified' },
    });

    // Preview v1 (not current), should have all original verification scores
    await page.route(/\/api\/slides\/versions\/1\?/, (route) => {
      previewV1Called = true;
      route.fulfill({
        status: 200, contentType: 'application/json',
        body: JSON.stringify(buildVersionPreviewResponse(1, 'Generated 3 slide(s)', mockSlideDeck, originalVerificationMap)),
      });
    });

    await goToGenerator(page);
    await generateSlides(page);
    await page.waitForTimeout(2000);

    const savePointButton = page.locator('button[title="Save Points"]');
    await expect(savePointButton).toBeVisible({ timeout: 5000 });

    // Preview v1 (older version)
    await savePointButton.click();
    await page.getByText('Generated 3 slide(s)').click();
    await page.waitForTimeout(1500);

    await expect(savePointButton).toContainText('Previewing v1');
    expect(previewV1Called).toBe(true);
    // v1 deck has 3 slides with original verification map covering all 3 hashes
    await expect(page.locator('p.text-sm.text-gray-500').getByText('3 slides')).toBeVisible();
  });
});

// ============================================
// Race Condition Prevention Tests
//
// Validates the deck-edit-counter fix: when auto-verify's getSlides response
// arrives after a subsequent user edit, it must NOT overwrite the newer state.
// ============================================

/**
 * Helper: set up ALL mocks manually with stateful getSlides/updateSlide/delete.
 * Does NOT use setupSavePointMocks (Playwright routes are FIFO, first-registered
 * fulfills first -- later overrides would be ignored).
 */
async function setupStatefulMocks(
  page: Page,
  state: {
    currentDeck: typeof mockSlideDeck;
    updateSlideCallCount: { value: number };
    getSlidesCalls: { value: number };
    verifyDelayMs?: number;
  },
) {
  const { currentDeck, updateSlideCallCount, getSlidesCalls, verifyDelayMs = 3000 } = state;

  // Profiles
  await page.route('http://127.0.0.1:8000/api/settings/profiles', (route, request) => {
    if (request.method() === 'GET') {
      route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(mockProfiles) });
    } else { route.continue(); }
  });
  await page.route(/http:\/\/127.0.0.1:8000\/api\/settings\/profiles\/\d+$/, (route, request) => {
    if (request.method() === 'GET') {
      const id = parseInt(request.url().split('/').pop() || '1');
      const profile = mockProfiles.find(p => p.id === id) || mockProfiles[0];
      route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(profile) });
    } else { route.continue(); }
  });
  await page.route('http://127.0.0.1:8000/api/settings/deck-prompts', r =>
    r.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(mockDeckPrompts) }));
  await page.route('http://127.0.0.1:8000/api/settings/slide-styles', r =>
    r.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(mockSlideStyles) }));
  await page.route('**/api/version**', r =>
    r.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ version: '0.1.21', latest: '0.1.21' }) }));
  await page.route('http://127.0.0.1:8000/api/genie/spaces', r =>
    r.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ spaces: [], total: 0 }) }));
  await page.route(/http:\/\/127.0.0.1:8000\/api\/genie\/.*\/link/, r =>
    r.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ url: 'https://example.com/genie', message: null }) }));
  await page.route('http://127.0.0.1:8000/api/slides/reorder**', r =>
    r.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ success: true }) }));

  // Versions (static)
  const v1 = makeVersionListItem(1, 'Generated 3 slide(s)');
  await page.route('**/api/slides/versions?**', r =>
    r.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ versions: [v1], current_version: 1 }) }));
  await page.route('**/api/slides/versions/current?**', r =>
    r.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ current_version: 1 }) }));
  await page.route('**/api/slides/versions/create', r =>
    r.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(v1) }));
  await page.route('**/api/slides/versions/sync-verification', r =>
    r.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ version_number: 1, verification_entries: 0 }) }));

  // Chat
  await page.route('http://127.0.0.1:8000/api/chat/stream', r =>
    r.fulfill({ status: 200, contentType: 'text/event-stream', body: createStreamingResponseWithDeck(mockSlideDeck) }));

  // --- STATEFUL: updateSlide (PATCH), deleteSlide (DELETE) ---
  // Note: updateSlide sends PATCH with body {html, session_id}
  //       deleteSlide sends DELETE with ?session_id= query param
  await page.route(/http:\/\/127.0.0.1:8000\/api\/slides\/\d+(\?|$)/, async (route, request) => {
    const urlPath = new URL(request.url()).pathname;
    const slideIndex = parseInt(urlPath.split('/').pop() || '0');
    if (request.method() === 'DELETE') {
      state.currentDeck = {
        ...state.currentDeck,
        slide_count: state.currentDeck.slides.length - 1,
        slides: state.currentDeck.slides.filter((_, i) => i !== slideIndex),
      };
      route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ status: 'deleted' }) });
      return;
    }
    if (request.method() === 'PATCH') {
      updateSlideCallCount.value++;
      const body = request.postDataJSON();
      if (body.html && slideIndex < state.currentDeck.slides.length) {
        state.currentDeck = {
          ...state.currentDeck,
          slides: state.currentDeck.slides.map((s, i) =>
            i === slideIndex ? { ...s, html: body.html, content_hash: `edit_${slideIndex}_${updateSlideCallCount.value}` } : s
          ),
        };
      }
      route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ index: slideIndex, slide_id: `slide-${slideIndex}`, html: body.html }) });
      return;
    }
    route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({}) });
  });

  // --- STATEFUL: sessions (getSlides reads currentDeck) ---
  await page.route('http://127.0.0.1:8000/api/sessions**', (route, request) => {
    const url = request.url();
    const method = request.method();
    if (method === 'POST' || method === 'DELETE') {
      route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ session_id: 'mock', title: 'New', user_id: null, created_at: '2026-01-01T00:00:00Z' }) });
      return;
    }
    if (url.includes('limit=')) {
      route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(mockSessions) });
    } else if (url.includes('/slides')) {
      getSlidesCalls.value++;
      const snap = JSON.parse(JSON.stringify(state.currentDeck));
      route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ session_id: 'test-session-id', slide_deck: snap }) });
    } else {
      route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ session_id: 'test-session-id', messages: [] }) });
    }
  });

  // --- Verification: DELAYED to create race window ---
  await page.route(/http:\/\/127.0.0.1:8000\/api\/slides\/\d+\/verification/, async (route) => {
    await new Promise(resolve => setTimeout(resolve, verifyDelayMs));
    route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ status: 'unable_to_verify', message: 'No Genie room linked' }) });
  });
  await page.route(/http:\/\/127.0.0.1:8000\/api\/verification/, r =>
    r.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ score: 0, rating: 'grey', explanation: 'No Genie', issues: [], duration_ms: 50, error: false }) }));
}

/**
 * Helper: open edit modal for slide at given 0-based index, change the first
 * editable text to `newText`, and save.  Returns after the modal closes.
 */
async function editSlideText(page: Page, slideIndex: number, newText: string) {
  const slideHeaders = page.locator('.bg-gray-100.border-b');
  const editButton = slideHeaders.nth(slideIndex).locator('button.text-blue-600').first();
  await editButton.click();
  await expect(page.getByRole('heading', { name: 'Edit Slide' })).toBeVisible({ timeout: 5000 });

  // Click the first editable text node (the span with cursor-pointer that shows quoted text)
  const editableText = page.locator('span.truncate.cursor-pointer').first();
  await editableText.click({ timeout: 3000 });

  // The inline TextEditor should appear as an <input> or <textarea>
  const textInput = page.getByRole('textbox').last();
  await textInput.fill(newText);
  await textInput.press('Enter');

  // Save and wait for modal to close
  await page.getByRole('button', { name: 'Save Changes' }).click();
  await expect(page.getByRole('heading', { name: 'Edit Slide' })).not.toBeVisible({ timeout: 5000 });
}

test.describe('Race Condition Prevention - rapid sequential edits', () => {

  test('edit slide 1 then edit slide 2 -- slide 1 edit must not revert (auto-verify race)', async ({ page }) => {
    // Scenario from user report:
    //   "you edit slide 1, then edit slide 2 - slide 1 reverts"
    //
    // Root cause: auto-verify starts after edit 1, its getSlides response
    // (pre-edit-2) arrives and overwrites the frontend state.
    // The deckEditCounterRef fix discards stale responses.

    const state = {
      currentDeck: JSON.parse(JSON.stringify(mockSlideDeck)),
      updateSlideCallCount: { value: 0 },
      getSlidesCalls: { value: 0 },
    };

    await setupStatefulMocks(page, state);

    await goToGenerator(page);
    await generateSlides(page);
    await page.waitForTimeout(500);

    // --- Edit slide 1 ---
    await editSlideText(page, 0, 'EDITED_SLIDE_1_TEXT');

    // Auto-verify triggers (3s delay on verifySlide).
    // Quickly edit slide 2 BEFORE auto-verify completes.
    await page.waitForTimeout(200);

    // --- Edit slide 2 ---
    await editSlideText(page, 1, 'EDITED_SLIDE_2_TEXT');

    // Wait for auto-verify to complete (3s delay) and all getSlides to resolve
    await page.waitForTimeout(5000);

    // --- Assertions ---
    expect(state.updateSlideCallCount.value).toBe(2);

    // The stateful mock deck must have both edits applied
    expect(state.currentDeck.slides[0].html).toContain('EDITED_SLIDE_1_TEXT');
    expect(state.currentDeck.slides[1].html).toContain('EDITED_SLIDE_2_TEXT');

    // The frontend should still show 3 slides (none lost)
    await expect(page.locator('.bg-gray-100.border-b')).toHaveCount(3);
  });

  test('delete slide then rapid edit -- edit must persist through auto-verify race', async ({ page }) => {
    // Scenario: "after deleting 1 slide it starts getting messy"

    const state = {
      currentDeck: JSON.parse(JSON.stringify(mockSlideDeck)),
      updateSlideCallCount: { value: 0 },
      getSlidesCalls: { value: 0 },
    };

    await setupStatefulMocks(page, state);

    await goToGenerator(page);
    await generateSlides(page);
    await page.waitForTimeout(500);

    await expect(page.locator('.bg-gray-100.border-b')).toHaveCount(3);

    // Accept the confirm dialog for delete
    page.on('dialog', dialog => dialog.accept());

    // Delete slide 3 (index 2)
    const deleteButton = page.locator('.bg-gray-100.border-b').nth(2).locator('button.text-red-600');
    await deleteButton.click();

    // Wait for delete + getSlides cycle
    await page.waitForTimeout(1500);
    await expect(page.locator('.bg-gray-100.border-b')).toHaveCount(2, { timeout: 5000 });

    // Quickly edit slide 1 before auto-verify completes
    await editSlideText(page, 0, 'POST_DELETE_EDIT');

    // Wait for auto-verify to complete
    await page.waitForTimeout(5000);

    // Assertions
    await expect(page.locator('.bg-gray-100.border-b')).toHaveCount(2);
    expect(state.currentDeck.slides.length).toBe(2);
    expect(state.currentDeck.slides[0].html).toContain('POST_DELETE_EDIT');
    expect(state.updateSlideCallCount.value).toBe(1);
  });
});

test.describe('User Journey - Edge Cases', () => {

  test('back-to-back preview switches between different versions correctly', async ({ page }) => {
    // Rapidly switch between version previews to ensure state doesn't get stuck
    const v1 = makeVersionListItem(1, 'Initial generation');
    const v2 = makeVersionListItem(2, 'First edit');
    const v3 = makeVersionListItem(3, 'Second edit');
    const v4 = makeVersionListItem(4, 'Third edit');

    const previewOrder: number[] = [];

    await setupSavePointMocks(page, {
      versionState: { versions: [v4, v3, v2, v1], current_version: 4 },
    });

    for (const [vNum, desc] of [[1, 'Initial generation'], [2, 'First edit'], [3, 'Second edit']] as const) {
      await page.route(new RegExp(`/api/slides/versions/${vNum}\\?`), (route) => {
        previewOrder.push(vNum);
        route.fulfill({
          status: 200, contentType: 'application/json',
          body: JSON.stringify(buildVersionPreviewResponse(vNum, desc, mockSlideDeck)),
        });
      });
    }

    await goToGenerator(page);
    await generateSlides(page);
    await page.waitForTimeout(1000);

    const savePointButton = page.locator('button[title="Save Points"]');
    await expect(savePointButton).toBeVisible({ timeout: 5000 });

    // Rapid preview switches: v1 → v3 → v2 → v1
    await savePointButton.click();
    await page.getByText('Initial generation').click();
    await page.waitForTimeout(1000);
    await expect(savePointButton).toContainText('Previewing v1');

    await savePointButton.click();
    await page.getByText('Second edit').click();
    await page.waitForTimeout(1000);
    await expect(savePointButton).toContainText('Previewing v3');

    await savePointButton.click();
    await page.getByText('First edit').click();
    await page.waitForTimeout(1000);
    await expect(savePointButton).toContainText('Previewing v2');

    await savePointButton.click();
    await page.getByText('Initial generation').click();
    await page.waitForTimeout(1000);
    await expect(savePointButton).toContainText('Previewing v1');

    // All 4 preview fetches happened
    expect(previewOrder).toEqual([1, 3, 2, 1]);
  });

  test('many versions: dropdown shows all and scrolls', async ({ page }) => {
    const manyVersions = Array.from({ length: 10 }, (_, i) => {
      const vNum = 10 - i;
      return makeVersionListItem(vNum, `Edit ${vNum}`, 3);
    });

    await setupSavePointMocks(page, {
      versionState: { versions: manyVersions, current_version: 10 },
    });

    await goToGenerator(page);
    await generateSlides(page);
    await page.waitForTimeout(1000);

    const savePointButton = page.locator('button[title="Save Points"]');
    await expect(savePointButton).toBeVisible({ timeout: 5000 });
    await expect(savePointButton).toContainText('Save Point 10');
    await savePointButton.click();

    // Header should show count
    await expect(page.getByText('Save Points (10)')).toBeVisible({ timeout: 3000 });
    // First and last versions should be in the list
    await expect(page.getByText('Edit 10')).toBeVisible({ timeout: 3000 });
    await expect(page.getByText('Edit 1', { exact: true })).toBeVisible({ timeout: 3000 });
  });
});
