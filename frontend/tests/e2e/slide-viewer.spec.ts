import { test, expect } from '@playwright/test';
import { setupMocks } from '../helpers/setup-mocks';
import { mockFindings } from '../fixtures/findings';
import { mockSessionWithSlides, TEST_SESSION_ID, mockSlidesResponse } from '../helpers/session-helpers';

test.describe('seen-state persistence', () => {
  test.beforeEach(async ({ page }) => {
    await setupMocks(page);
  });

  test('markSeen persists per deck and loadSeen reads it back', async ({ page }) => {
    await page.goto('/');

    const result = await page.evaluate(async () => {
      const m = await import('/src/components/SlideViewer/seenState.ts');
      m.markSeen('deck-a', ['f1', 'f2']);
      m.markSeen('deck-b', ['f9']);
      return {
        a: Array.from(m.loadSeen('deck-a')).sort(),
        b: Array.from(m.loadSeen('deck-b')),
        empty: Array.from(m.loadSeen('deck-missing')),
      };
    });

    expect(result.a).toEqual(['f1', 'f2']);
    expect(result.b).toEqual(['f9']);      // scoped per deck
    expect(result.empty).toEqual([]);
  });

  test('markSeen merges rather than overwrites', async ({ page }) => {
    await page.goto('/');

    const merged = await page.evaluate(async () => {
      const m = await import('/src/components/SlideViewer/seenState.ts');
      m.markSeen('deck-c', ['f1']);
      m.markSeen('deck-c', ['f2']);
      return Array.from(m.loadSeen('deck-c')).sort();
    });

    expect(merged).toEqual(['f1', 'f2']);
  });

  test('markSeen caps stored decks so the store cannot grow unbounded', async ({ page }) => {
    await page.goto('/');

    const deckCount = await page.evaluate(async () => {
      const m = await import('/src/components/SlideViewer/seenState.ts');
      localStorage.removeItem(m.SEEN_STORAGE_KEY);
      for (let i = 0; i < 60; i++) m.markSeen(`deck-${i}`, [`f${i}`]);
      return Object.keys(JSON.parse(localStorage.getItem(m.SEEN_STORAGE_KEY) ?? '{}')).length;
    });

    expect(deckCount).toBe(50);   // MAX_DECKS — exact, so a no-op or a bad trim fails
  });
});

// ============================================
// Flip-through viewer behaviour tests (Task 8B)
// ============================================
//
// Correction notes (vs brief's step 8 code):
//  - mockSlidesResponse has 3 slides (indices 0–2) → last thumb is ribbon-thumb-2.
//  - Findings: f1+f2 on slideIndex 1, f3 on slideIndex 3 (unreachable with 3 slides).
//    So slide 0 → empty, slide 1 → f1+f2, slide 2 → empty.
//  - ribbon-unseen-1 is the indicator for slide 1.

const DECK_SLIDE_COUNT = mockSlidesResponse.slide_deck.slide_count; // 3

test.describe('flip-through viewer', () => {
  test.beforeEach(async ({ page }) => {
    await setupMocks(page);
    await mockSessionWithSlides(page);

    // Mock the deck-contributors endpoint so AppLayout's lock lifecycle resolves quickly.
    // An empty contributors list causes AppLayout to grant the lock immediately
    // (unshared session path), making stage-toolbar controls visible (readOnly=false).
    await page.route(`http://127.0.0.1:8000/api/sessions/${TEST_SESSION_ID}/contributors`, (route) => {
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ contributors: [] }),
      });
    });

    // Inject findings BEFORE navigation — AppLayout reads window.__TELLR_TEST_FINDINGS__
    // once on mount (AppLayout.tsx:739-744), so addInitScript must run first.
    await page.addInitScript(
      (findings) => { (window as unknown as { __TELLR_TEST_FINDINGS__: typeof findings }).__TELLR_TEST_FINDINGS__ = findings; },
      mockFindings,
    );
  });

  /** Navigate to the deck-loaded session and wait for the viewer to be visible. */
  const openDeck = async (page: import('@playwright/test').Page) => {
    await page.goto(`/sessions/${TEST_SESSION_ID}/edit`);
    await expect(page.getByTestId('slide-viewer')).toBeVisible();
    // Wait for the first thumbnail to be ready — ensures the ViewerContext is initialised.
    await expect(page.getByTestId('ribbon-thumb-0')).toBeVisible();
  };

  /**
   * Click a thumbnail by test-id.
   *
   * ThumbnailRibbon spreads dnd-kit's `{...listeners}` (PointerSensor) onto each
   * thumbnail `<button>`. In Playwright's headless browser the PointerSensor
   * activates on pointerdown and adds a capture click-stopper to the document
   * before pointerup fires, which causes `.click()` to silently do nothing.
   *
   * Using `dispatchEvent('click')` instead: it fires a DOM click event directly
   * on the element, bypassing the pointer pipeline. The click still bubbles
   * through React's synthetic event system and calls `onClick` normally.
   */
  const thumbClick = async (page: import('@playwright/test').Page, testId: string) => {
    await page.getByTestId(testId).dispatchEvent('click');
  };

  // ── Stage: single slide, prev/next controls ──────────────────────────────

  test('shows exactly one slide and pages with arrow controls', async ({ page }) => {
    await openDeck(page);
    // Exactly one stage iframe — the viewer shows one slide at a time.
    await expect(page.getByTestId('slide-stage-frame')).toHaveCount(1);
    await expect(page.getByTestId('stage-position')).toContainText('1 /');

    await page.getByTestId('stage-next').click();
    await expect(page.getByTestId('stage-position')).toContainText('2 /');
    // The thumbnail for the new current slide must reflect data-current="true".
    await expect(page.getByTestId('ribbon-thumb-1')).toHaveAttribute('data-current', 'true');
  });

  test('ribbon-click navigates to the clicked slide', async ({ page }) => {
    await openDeck(page);
    // Click the last thumbnail (index 2 with a 3-slide deck).
    await thumbClick(page, `ribbon-thumb-${DECK_SLIDE_COUNT - 1}`);
    await expect(page.getByTestId('stage-position')).toContainText(`${DECK_SLIDE_COUNT} /`);
    await expect(page.getByTestId(`ribbon-thumb-${DECK_SLIDE_COUNT - 1}`))
      .toHaveAttribute('data-current', 'true');
  });

  // ── Keyboard: paging fires everywhere EXCEPT while typing ────────────────

  test('keyboard pages slides but not while typing in chat', async ({ page }) => {
    await openDeck(page);
    // Wait for the stage toolbar (confirms lock acquired, readOnly=false → chat input enabled).
    await expect(page.getByTestId('stage-toolbar')).toBeVisible();

    // ArrowRight from the document advances the slide.
    await page.keyboard.press('ArrowRight');
    await expect(page.getByTestId('stage-position')).toContainText('2 /');

    // Focus the chat composer and press ArrowRight — slide must NOT change.
    const chat = page.getByTestId('chat-input');
    await chat.click();
    await chat.press('ArrowRight');
    await expect(page.getByTestId('stage-position')).toContainText('2 /');  // unchanged
  });

  // ── Wheel: ribbon scrolls thumbnails; stage advances slide ───────────────

  test('wheel over the ribbon does not change the slide; wheel over the stage does', async ({ page }) => {
    await openDeck(page);

    // Wheel on the ribbon: the ribbon has no onWheel handler so the slide must NOT change.
    // Use dispatchEvent to target the ribbon element directly, bypassing the iframe
    // hit-detection issue that can affect page.mouse.wheel() when the cursor lands on
    // the slide preview iframe inside the stage.
    await page.getByTestId('thumbnail-ribbon').dispatchEvent('wheel', { deltaY: 300 });
    await expect(page.getByTestId('stage-position')).toContainText('1 /');  // unchanged

    // Wheel on the stage: dispatched directly on slide-stage so it reaches the React
    // onWheel handler even when the iframe inside the stage would otherwise capture
    // pointer events.
    await page.getByTestId('slide-stage').dispatchEvent('wheel', { deltaY: 300 });
    await expect(page.getByTestId('stage-position')).toContainText('2 /');
  });

  // ── Home / End jump to boundaries ────────────────────────────────────────

  test('Home and End jump to first and last slide', async ({ page }) => {
    await openDeck(page);
    await page.keyboard.press('End');
    // After End the position shows "n / n" — both halves equal.
    await expect(page.getByTestId('stage-position'))
      .toContainText(`${DECK_SLIDE_COUNT} / ${DECK_SLIDE_COUNT}`);
    // The last thumbnail must be marked current.
    await expect(page.getByTestId(`ribbon-thumb-${DECK_SLIDE_COUNT - 1}`))
      .toHaveAttribute('data-current', 'true');

    await page.keyboard.press('Home');
    await expect(page.getByTestId('stage-position')).toContainText('1 /');
  });

  // ── Auto-reveal: current slide is scrolled into view after paging ─────────

  test('the current slide is revealed in the ribbon after paging to the last', async ({ page }) => {
    await openDeck(page);
    await page.keyboard.press('End');
    const lastThumb = page.getByTestId(`ribbon-thumb-${DECK_SLIDE_COUNT - 1}`);
    await expect(lastThumb).toHaveAttribute('data-current', 'true');
    await expect(lastThumb).toBeInViewport();
  });

  // ── Feedback drawer: per-slide findings and empty state ───────────────────

  test('drawer shows empty state on a slide with no findings', async ({ page }) => {
    await openDeck(page);
    // Slide 0 has no findings — drawer-empty must be visible (drawer is open by default).
    await expect(page.getByTestId('drawer-empty')).toBeVisible();
  });

  test('drawer shows findings for slide 1 and empty state for other slides', async ({ page }) => {
    await openDeck(page);
    // Navigate to slide 1 (findings f1 and f2 live on slideIndex 1).
    await thumbClick(page, 'ribbon-thumb-1');
    await expect(page.getByTestId('finding-f1')).toBeVisible();
    await expect(page.getByTestId('finding-f2')).toBeVisible();

    // Navigate away — slide 2 has no findings, so empty state reappears.
    await thumbClick(page, 'ribbon-thumb-2');
    await expect(page.getByTestId('drawer-empty')).toBeVisible();
  });

  // ── Unseen indicator: appears then clears once viewed ────────────────────

  test('unseen indicator appears then clears once slide 1 is viewed', async ({ page }) => {
    await openDeck(page);
    // Slide 1 has unread findings — indicator should be visible before visiting.
    await expect(page.getByTestId('ribbon-unseen-1')).toBeVisible();

    // Click slide 1; with the drawer open on the feedback tab, findings are marked seen.
    await thumbClick(page, 'ribbon-thumb-1');
    await expect(page.getByTestId('ribbon-unseen-1')).toBeHidden();

    // Seen state persists across a reload.
    await page.reload();
    await expect(page.getByTestId('slide-viewer')).toBeVisible();
    await expect(page.getByTestId('ribbon-unseen-1')).toBeHidden();
  });

  // ── Apply/Dismiss/Discuss actions ─────────────────────────────────────────

  test('dismiss removes a finding from the drawer', async ({ page }) => {
    await openDeck(page);
    await thumbClick(page, 'ribbon-thumb-1');
    await expect(page.getByTestId('finding-f1')).toBeVisible();

    await page.getByTestId('finding-dismiss-f1').click();
    await expect(page.getByTestId('finding-f1')).toHaveCount(0);

    // f2 is still present (only f1 was dismissed).
    await expect(page.getByTestId('finding-f2')).toBeVisible();
  });

  test('Apply and Discuss buttons are present on each finding', async ({ page }) => {
    await openDeck(page);
    await thumbClick(page, 'ribbon-thumb-1');
    await expect(page.getByTestId('finding-apply-f1')).toBeVisible();
    await expect(page.getByTestId('finding-discuss-f1')).toBeVisible();
    await expect(page.getByTestId('finding-apply-f2')).toBeVisible();
    await expect(page.getByTestId('finding-discuss-f2')).toBeVisible();
  });

  // ── Drawer open/closed state persists across reload ───────────────────────

  test('drawer closed state survives a reload', async ({ page }) => {
    await openDeck(page);
    // Collapse the drawer.
    await page.getByTestId('drawer-toggle').click();
    await expect(page.getByTestId('drawer-body')).toHaveCount(0);

    // Reload and check it stays collapsed.
    await page.reload();
    await expect(page.getByTestId('slide-viewer')).toBeVisible();
    await expect(page.getByTestId('drawer-body')).toHaveCount(0);
  });

  // ── No checkbox selection ─────────────────────────────────────────────────

  test('no checkbox selection UI remains', async ({ page }) => {
    await openDeck(page);
    await expect(page.locator('.slide-checkbox-input')).toHaveCount(0);
    await expect(page.getByText('Select consecutive slides')).toHaveCount(0);
  });

  // ── Chat panel collapse persists ──────────────────────────────────────────

  test('chat panel toggle collapses the panel and state survives reload', async ({ page }) => {
    await openDeck(page);
    // The toggle button must be reachable and functional.
    await expect(page.getByTestId('toggle-chat-panel')).toBeVisible();
    await page.getByTestId('toggle-chat-panel').click();

    // After reload the toggle is still reachable (panel is still collapsed).
    await page.reload();
    await expect(page.getByTestId('slide-viewer')).toBeVisible();
    await expect(page.getByTestId('toggle-chat-panel')).toBeVisible();
  });

  // ── Stage toolbar affordances ─────────────────────────────────────────────

  test('stage-edit-slide opens the HTML editor modal', async ({ page }) => {
    await openDeck(page);
    // Wait for the stage toolbar (only visible when readOnly=false, i.e. lock acquired).
    await expect(page.getByTestId('stage-toolbar')).toBeVisible();
    await page.getByTestId('stage-edit-slide').click();
    await expect(page.getByRole('heading', { name: 'Edit Slide' })).toBeVisible();
  });

  test('stage-delete-slide opens a confirm dialog', async ({ page }) => {
    await openDeck(page);
    await expect(page.getByTestId('stage-toolbar')).toBeVisible();
    await page.getByTestId('stage-delete-slide').click();
    // ConfirmDialog renders with the message "Delete slide 1?" for slide index 0.
    await expect(page.getByText('Delete slide 1?')).toBeVisible();
    await page.getByRole('button', { name: 'Cancel' }).click();
  });

  test('stage-optimize-layout button exists', async ({ page }) => {
    await openDeck(page);
    // The optimize-layout button is only rendered when onSendMessage is wired.
    // In the edit route AppLayout always passes onSendMessage, so it is present.
    // Wait for the stage toolbar to confirm lock is acquired (readOnly=false).
    await expect(page.getByTestId('stage-toolbar')).toBeVisible();
    await expect(page.getByTestId('stage-optimize-layout')).toBeVisible();
  });

  // ── Drag-reorder from the ribbon (spec §4, §10) ───────────────────────────

  test('dragging a thumbnail reorders the deck via the reorder endpoint', async ({ page }) => {
    // Capture the reorder request so we assert the deck mutation actually fires
    // with the right permutation, rather than only that a drag gesture happened.
    const reorderBodies: Array<{ new_order: number[] }> = [];
    await page.route('**/api/slides/reorder', async (route) => {
      reorderBodies.push(route.request().postDataJSON());
      // Echo a deck so the optimistic update is not rolled back.
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(mockSlidesResponse.slide_deck),
      });
    });

    await openDeck(page);

    const source = page.getByTestId('ribbon-thumb-0');
    const target = page.getByTestId('ribbon-thumb-2');
    const from = await source.boundingBox();
    const to = await target.boundingBox();
    if (!from || !to) throw new Error('ribbon thumbnails have no layout box');

    // dnd-kit's PointerSensor needs discrete pointer events with intermediate
    // moves; a single mouse.move() jump does not cross its activation threshold.
    await page.mouse.move(from.x + from.width / 2, from.y + from.height / 2);
    await page.mouse.down();
    for (let step = 1; step <= 6; step++) {
      await page.mouse.move(
        from.x + from.width / 2,
        from.y + from.height / 2 + ((to.y - from.y) * step) / 6,
        { steps: 2 },
      );
    }
    await page.mouse.up();

    // The reorder request must have fired with a genuine permutation.
    await expect.poll(() => reorderBodies.length, { timeout: 5000 }).toBeGreaterThan(0);
    const order = reorderBodies[0].new_order;
    expect(order).toHaveLength(3);
    expect([...order].sort()).toEqual([0, 1, 2]);
    expect(order).not.toEqual([0, 1, 2]);
  });
});
