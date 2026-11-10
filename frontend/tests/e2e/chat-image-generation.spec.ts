/**
 * Chat image generation (Unit I, plan Task 8): the "Generate image" entry points and the options card,
 * in a real browser on the SSE transport.
 *
 * Contract: docs/superpowers/plans/2026-11-09-chat-image-generation-CORRECTIONS.md, "Unit I interface".
 *
 *   1. The chat input's "Generate image" opens the request dialog; Icon + "Show me 3 options" + no
 *      slide sends the message "Generate 3 icon options: <prompt>" with no image ids. The architect's
 *      reply carries `metadata.generated_images` (3 options); the card under it shows 3 thumbnails,
 *      fetched from GET /api/images/{token}. "Use this" on option 2 sends the next turn with
 *      `image_ids: ["tok2"]` and "Use option 2 where it fits best.".
 *   2. AppLayout wiring the vitest suites cannot reach (no vitest suite renders AppLayout): the stage's
 *      "Generate image for this slide" appears on an agent deck when generation is available, opens
 *      the dialog on the current slide and sends a message naming it; ChatPanel gets the deck's slide
 *      count (the For-slide choices).
 *   3. Gating: a legacy deck, or generation unavailable, shows neither entry point.
 *
 * No backend runs: every API call is mocked with page.route. The image routes are registered AFTER
 * setupMocks, whose `/api/images**` catch-all would otherwise answer them (Playwright tries the
 * last-registered route first).
 */
import { test, expect } from '../fixtures/base-test';
import type { Page } from '@playwright/test';
import { setupMocks } from '../helpers/setup-mocks';
import { apiPath, apiPathMatching } from '../helpers/api-route';
import { mockSessionDetail, mockSessionWithSlides, TEST_SESSION_ID } from '../helpers/session-helpers';

// ── fixtures ──────────────────────────────────────────────────────────────────

/** A real 1x1 PNG, so a rendered thumbnail has a natural width. */
const PNG =
  'data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==';

const PROMPT = 'A shield for data security';
const IMAGES = [1, 2, 3].map((option) => ({
  token: `tok${option}`,
  kind: 'icon',
  option,
  prompt: PROMPT,
  for_slide: null,
  slides: [],
}));
const REPLY = 'Here are three shield icons. Pick one, or ask for new ones.';

const AVAILABLE = {
  available: true,
  max_prompt_chars: 2000,
  default_preset: 'illustration',
  presets: [],
  edit: null,
};

function imageAsset(token: string) {
  return {
    id: token,
    filename: `${token}.png`,
    original_filename: `${token}.png`,
    mime_type: 'image/png',
    size_bytes: 68,
    thumbnail_base64: PNG,
    tags: ['ai_generated', 'gpt-image-2.6-flare', 'icon_png', 'chat', 'chat_option'],
    description: PROMPT,
    category: 'content',
    uploaded_by: 'test@example.com',
    is_active: true,
    created_at: '2026-11-09T10:00:00Z',
    updated_at: '2026-11-09T10:00:00Z',
  };
}

const sse = (events: unknown[]) => events.map((e) => `data: ${JSON.stringify(e)}\n\n`).join('');

/** The architect's options reply, then the end of the turn. */
const OPTIONS_TURN = sse([
  { type: 'tool_call', content: 'Generating 3 icons', tool_name: 'image_generation', tool_input: { kind: 'icon', count: 3 }, metadata: { node: 'architect' } },
  { type: 'assistant', content: REPLY, metadata: { node: 'architect', intent: 'discuss', generated_images: IMAGES } },
  { type: 'complete', metadata: { engine_mode: 'graph' } },
]);
const PLAIN_TURN = sse([
  { type: 'assistant', content: 'Done.', metadata: { node: 'architect', intent: 'edit' } },
  { type: 'complete', metadata: { engine_mode: 'graph' } },
]);

// ── mocks ─────────────────────────────────────────────────────────────────────

interface Mocks {
  chatBodies: Array<Record<string, unknown>>;
  imageReads: string[];
  /** How many times the availability probe was answered. */
  probes: () => number;
}

/**
 * The 3-slide deck at TEST_SESSION_ID, editable, plus the image routes. `deckMode` is the session's
 * stored mode; `available` whether GET /api/images/generate/available says the feature is on.
 */
async function setupDeck(
  page: Page,
  { deckMode = 'agent', available = true }: { deckMode?: 'agent' | 'legacy'; available?: boolean } = {},
): Promise<Mocks> {
  await setupMocks(page);
  await mockSessionWithSlides(page);
  await page.route(apiPath(`/api/sessions/${TEST_SESSION_ID}`), (route, request) => {
    if (request.method() !== 'GET') return route.fallback();
    return route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ ...mockSessionDetail, deck_mode: deckMode, my_permission: 'CAN_MANAGE', messages: [] }),
    });
  });
  // Empty contributors: AppLayout grants the editing lock at once, so the deck is editable.
  await page.route(apiPath(`/api/sessions/${TEST_SESSION_ID}/contributors`), (route) =>
    route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ contributors: [] }) }),
  );
  await page.route('**/api/user/current', (route) =>
    route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ username: 'test@example.com' }) }),
  );

  // After setupMocks: these must win over its `/api/images**` catch-all.
  let probes = 0;
  await page.route(apiPath('/api/images/generate/available'), (route) => {
    probes += 1;
    return route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(available ? AVAILABLE : { ...AVAILABLE, available: false, max_prompt_chars: 0 }),
    });
  });
  const imageReads: string[] = [];
  await page.route(apiPathMatching(/^\/api\/images\/tok\d+$/), (route, request) => {
    if (request.method() !== 'GET') return route.fallback();
    const token = new URL(request.url()).pathname.split('/').pop() as string;
    imageReads.push(token);
    return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(imageAsset(token)) });
  });

  const chatBodies: Array<Record<string, unknown>> = [];
  await page.route(apiPath('/api/chat/stream'), (route, request) => {
    chatBodies.push(request.postDataJSON() as Record<string, unknown>);
    return route.fulfill({
      status: 200,
      contentType: 'text/event-stream',
      body: chatBodies.length === 1 ? OPTIONS_TURN : PLAIN_TURN,
    });
  });

  return { chatBodies, imageReads, probes: () => probes };
}

async function openDeck(page: Page) {
  await page.goto(`/sessions/${TEST_SESSION_ID}/edit`);
  await expect(page.getByTestId('ribbon-thumb-0')).toBeVisible();
  await expect(page.getByTestId('chat-input')).toBeEnabled({ timeout: 15000 });
}

const generateImageButton = (page: Page) => page.getByRole('button', { name: 'Generate image', exact: true });
const stageAction = (page: Page) => page.getByRole('button', { name: 'Generate image for this slide', exact: true });
const dialog = (page: Page) => page.getByRole('dialog');
const optionTile = (page: Page, n: number) =>
  page.getByRole('listitem').filter({ has: page.getByText(`Option ${n}`, { exact: true }) });

// ── tests ─────────────────────────────────────────────────────────────────────

test.describe('chat image generation', () => {
  test('Generate image sends the request, the card shows 3 thumbnails, Use this sends image_ids ["tok2"]', async ({ page }) => {
    const mocks = await setupDeck(page);
    await openDeck(page);

    await generateImageButton(page).click();
    await expect(dialog(page)).toBeVisible();
    await dialog(page).getByRole('textbox', { name: 'Describe the image' }).fill(PROMPT);
    await dialog(page).getByRole('button', { name: 'Icon', exact: true }).click();
    await expect(dialog(page).getByRole('button', { name: 'Icon', exact: true })).toHaveAttribute('aria-pressed', 'true');
    await expect(dialog(page).getByRole('checkbox', { name: 'Show me 3 options' })).toBeChecked();
    // The deck has 3 slides; "None" stays selected.
    const forSlide = dialog(page).getByRole('combobox', { name: 'For slide' });
    await expect(forSlide.getByRole('option')).toHaveText(['None', '1', '2', '3']);
    await dialog(page).getByRole('button', { name: 'Send to chat' }).click();
    await expect(dialog(page)).toHaveCount(0);

    await expect.poll(() => mocks.chatBodies.length).toBe(1);
    expect(mocks.chatBodies[0].message).toBe(`Generate 3 icon options: ${PROMPT}`);
    expect(mocks.chatBodies[0].image_ids ?? null).toBeNull();
    expect(mocks.chatBodies[0]).toMatchObject({ session_id: TEST_SESSION_ID, deck_mode: 'agent' });

    // The reply and its card: 3 thumbnails, each read from GET /api/images/{token}.
    await expect(page.getByText(REPLY)).toBeVisible();
    await expect(page.getByText('Saved to your Image Library')).toBeVisible();
    const thumbs = page.getByRole('img', { name: /^Option [123]\b/ });
    await expect(thumbs).toHaveCount(3);
    for (const n of [1, 2, 3]) {
      const img = optionTile(page, n).getByRole('img');
      await expect(img).toHaveAttribute('src', PNG);
      await expect.poll(() => img.evaluate((el) => (el as HTMLImageElement).naturalWidth)).toBeGreaterThan(0);
    }
    expect([...new Set(mocks.imageReads)].sort()).toEqual(['tok1', 'tok2', 'tok3']);

    // The activity row for the tool call.
    await page.getByTestId('tool-activity-bar').getByRole('button').click();
    await expect(page.getByTestId('tool-activity-item')).toHaveText('Image generation · 3 icons');

    // Use option 2.
    const use2 = optionTile(page, 2).getByRole('button', { name: 'Use this' });
    await expect(use2).toBeEnabled();
    await use2.click();

    await expect.poll(() => mocks.chatBodies.length).toBe(2);
    expect(mocks.chatBodies[1].image_ids).toEqual(['tok2']);
    expect(mocks.chatBodies[1].message).toBe('Use option 2 where it fits best.');
    await expect(page.getByText('Use option 2 where it fits best.')).toBeVisible();
  });

  test('the stage action opens the dialog on the current slide and sends a message naming it', async ({ page }) => {
    const mocks = await setupDeck(page);
    await openDeck(page);

    await page.getByTestId('ribbon-thumb-1').click();
    await expect(page.getByTestId('ribbon-thumb-1')).toHaveAttribute('data-current', 'true');
    await stageAction(page).click();

    const forSlide = dialog(page).getByRole('combobox', { name: 'For slide' });
    await expect(forSlide.locator('option:checked')).toHaveText('2');
    await dialog(page).getByRole('textbox', { name: 'Describe the image' }).fill('A rising line motif');
    await dialog(page).getByRole('button', { name: 'Send to chat' }).click();

    await expect.poll(() => mocks.chatBodies.length).toBe(1);
    expect(mocks.chatBodies[0].message).toBe('Generate 3 illustration options for slide 2: A rising line motif');
    expect(mocks.chatBodies[0].image_ids ?? null).toBeNull();
  });

  test('a legacy deck shows neither entry point, even when generation is available', async ({ page }) => {
    await setupDeck(page, { deckMode: 'legacy', available: true });
    await openDeck(page);
    await expect(page.getByTestId('deck-mode-select')).toHaveValue('legacy');
    await page.waitForLoadState('networkidle');

    // Positive controls: the chat box and the stage's other actions are there.
    await expect(page.getByTestId('stage-optimize-layout')).toBeVisible();
    await expect(generateImageButton(page)).toHaveCount(0);
    await expect(stageAction(page)).toHaveCount(0);
  });

  test('neither entry point shows when generation is unavailable', async ({ page }) => {
    const mocks = await setupDeck(page, { deckMode: 'agent', available: false });
    await openDeck(page);
    await expect.poll(() => mocks.probes()).toBeGreaterThan(0);
    await page.waitForLoadState('networkidle');

    await expect(page.getByTestId('stage-optimize-layout')).toBeVisible();
    await expect(generateImageButton(page)).toHaveCount(0);
    await expect(stageAction(page)).toHaveCount(0);
  });
});
