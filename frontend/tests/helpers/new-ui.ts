/**
 * Selectors and helpers for the new frontend UI (v0 refresh).
 * Use these in e2e tests so updates only need to happen in one place.
 */
import type { Page } from '@playwright/test';

// --- Sidebar / nav labels (new UI) ---
export const NEW_DECK_BUTTON_LABEL = 'New Deck';
export const AGENT_PROFILES_LABEL = 'Agent profiles';
export const DECK_PROMPTS_LABEL = 'Deck prompts';
export const SLIDE_STYLES_LABEL = 'Slide styles';
export const IMAGES_LABEL = 'Images';
export const HELP_LABEL = 'Help';
export const VIEW_ALL_DECKS_LABEL = 'View All Decks';
export const OPEN_DECK_MENU_LABEL = 'Open Deck';

/**
 * Navigate to the generator view (chat + slides) in the new UI.
 * Goes to / or /help, clicks "New Deck", and waits until we're on a session edit URL
 * with the chat input visible.
 */
export async function goToGenerator(page: Page) {
  await page.goto('/');
  await page.getByRole('button', { name: NEW_DECK_BUTTON_LABEL }).click();
  await page.waitForURL(/\/sessions\/[^/]+\/edit/);
  await page.getByRole('textbox').waitFor({ state: 'visible', timeout: 10000 });
}

/**
 * Send button in chat is icon-only; use title for accessibility.
 * Prefer adding aria-label="Send" in ChatInput and then use getByRole('button', { name: 'Send' }).
 * Until then, this matches the title.
 */
export function getSendButton(page: Page) {
  return page.getByRole('button', { name: /Send message \(Enter\)/i });
}

/** Locator for the slide count text in the page header (e.g. "3 slides"). Works with both old and new UI. */
export function getSlideCountLocator(page: Page, count?: number) {
  const re = count != null ? new RegExp(`${count} slides?`) : /\d+ slides?/;
  return page.getByText(re);
}
