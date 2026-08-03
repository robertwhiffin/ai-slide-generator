import { test, expect } from '@playwright/test';
import { setupMocks } from '../helpers/setup-mocks';

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
