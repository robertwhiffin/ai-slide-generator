# Chat & Message Flow Test Suite Plan

**Date:** 2026-01-31
**Status:** Ready for Implementation
**Estimated Tests:** ~20 UI tests

---

## Prerequisites

**Working directory:** `/Users/robert.whiffin/Documents/slide-generator/ai-slide-generator`

**Run tests from:** `frontend/` directory

```bash
cd frontend
npx playwright test tests/e2e/chat-ui.spec.ts
```

---

## Critical: Read These Files First

Before implementing, read these files completely:

1. **Working test example:** `frontend/tests/e2e/profile-ui.spec.ts`
2. **Mock patterns:** `frontend/tests/fixtures/mocks.ts` (especially `createStreamingResponse`)
3. **Existing deck tests:** `frontend/tests/e2e/deck-integrity.spec.ts`

---

## Discovery: Read These Component Files

```
frontend/src/components/chat/ChatPanel.tsx       # Main chat container
frontend/src/components/chat/ChatInput.tsx       # Message input field
frontend/src/components/chat/MessageList.tsx     # Message display
frontend/src/components/chat/LoadingIndicator.tsx # Loading states
frontend/src/components/slides/SlidePanel.tsx    # Slide display area
frontend/src/App.tsx                             # Main layout
```

---

## Navigation

| Nav Button | Page Heading | Component |
|------------|--------------|-----------|
| `Generator` | `Chat` | ChatPanel + SlidePanel |

```typescript
async function goToGenerator(page: Page) {
  await page.goto('/');
  await page.getByRole('navigation').getByRole('button', { name: 'Generator' }).click();
  await expect(page.getByRole('heading', { name: 'Chat', level: 2 })).toBeVisible();
}
```

---

## API Endpoints

**POST `/api/chat/stream`** - Send message (SSE streaming response)
```
Request: { message: "Create slides about...", session_id?: string, slide_context?: {...} }
Response: Server-Sent Events stream with slide data
```

**GET `/api/sessions/{id}`** - Get session details

---

## Mock Data

The streaming response mock already exists in `mocks.ts`:

```typescript
export function createStreamingResponse(slides: typeof mockSlides): string {
  const events: string[] = [];
  events.push('data: {"type": "start", "message": "Starting slide generation..."}\n\n');
  events.push('data: {"type": "progress", "message": "Generating slide 1..."}\n\n');
  for (const slide of slides) {
    events.push(`data: {"type": "slide", "slide": ${JSON.stringify(slide)}}\n\n`);
  }
  events.push('data: {"type": "complete", "message": "Generation complete"}\n\n');
  return events.join('');
}
```

---

## File to Create

**`frontend/tests/e2e/chat-ui.spec.ts`**

---

## Test Categories

### 1. Chat Input Tests

```typescript
test.describe('ChatInput', () => {
  test('displays chat input field', async ({ page }) => {
    await goToGenerator(page);
    await expect(page.getByRole('textbox', { name: /Ask to generate/i })).toBeVisible();
  });

  test('Send button is disabled when input is empty', async ({ page }) => {
    await goToGenerator(page);
    await expect(page.getByRole('button', { name: 'Send' })).toBeDisabled();
  });

  test('Send button is enabled when input has text', async ({ page }) => {
    await goToGenerator(page);
    await page.getByRole('textbox', { name: /Ask to generate/i }).fill('Create a presentation');
    await expect(page.getByRole('button', { name: 'Send' })).toBeEnabled();
  });

  test('input clears after sending message', async ({ page }) => {
    // Mock the stream endpoint
    await page.route('http://localhost:8000/api/chat/stream', (route) => {
      route.fulfill({
        status: 200,
        contentType: 'text/event-stream',
        body: createStreamingResponse(mockSlides),
      });
    });

    await goToGenerator(page);
    const input = page.getByRole('textbox', { name: /Ask to generate/i });
    await input.fill('Create a presentation');
    await page.getByRole('button', { name: 'Send' }).click();

    // Input should clear after send
    await expect(input).toHaveValue('');
  });

  test('can submit with Enter key', async ({ page }) => {
    // Test keyboard submission
  });
});
```

### 2. Message Display Tests

```typescript
test.describe('MessageList', () => {
  test('displays user message after sending', async ({ page }) => {
    // Send a message and verify it appears in the message list
  });

  test('displays assistant response', async ({ page }) => {
    // Verify AI response appears after streaming completes
  });

  test('messages appear in chronological order', async ({ page }) => {
    // Verify message ordering
  });

  test('shows message timestamps', async ({ page }) => {
    // If timestamps are displayed
  });
});
```

### 3. Loading State Tests

```typescript
test.describe('LoadingStates', () => {
  test('shows loading indicator while generating', async ({ page }) => {
    // Mock a slow response to observe loading state
    await page.route('http://localhost:8000/api/chat/stream', async (route) => {
      await new Promise(resolve => setTimeout(resolve, 1000));
      route.fulfill({
        status: 200,
        contentType: 'text/event-stream',
        body: createStreamingResponse(mockSlides),
      });
    });

    await goToGenerator(page);
    await page.getByRole('textbox', { name: /Ask to generate/i }).fill('Create slides');
    await page.getByRole('button', { name: 'Send' }).click();

    // Should show loading indicator
    await expect(page.getByText(/generating|loading/i)).toBeVisible();
  });

  test('Send button is disabled while generating', async ({ page }) => {
    // Verify button disabled during generation
  });

  test('loading indicator disappears when complete', async ({ page }) => {
    // Verify loading state clears
  });
});
```

### 4. Slide Generation Tests

```typescript
test.describe('SlideGeneration', () => {
  test('slides appear after generation completes', async ({ page }) => {
    await page.route('http://localhost:8000/api/chat/stream', (route) => {
      route.fulfill({
        status: 200,
        contentType: 'text/event-stream',
        body: createStreamingResponse(mockSlides),
      });
    });

    await goToGenerator(page);
    await page.getByRole('textbox', { name: /Ask to generate/i }).fill('Create slides about cloud computing');
    await page.getByRole('button', { name: 'Send' }).click();

    // Wait for slides to appear
    await expect(page.getByText('Benefits of Cloud Computing')).toBeVisible({ timeout: 10000 });
  });

  test('shows correct number of slides', async ({ page }) => {
    // mockSlides has 3 slides - verify count
  });

  test('slide titles are displayed', async ({ page }) => {
    // Verify slide title text
  });
});
```

### 5. Empty State Tests

```typescript
test.describe('EmptyState', () => {
  test('shows empty state message before any slides', async ({ page }) => {
    await goToGenerator(page);
    await expect(page.getByText('No slides yet')).toBeVisible();
  });

  test('shows prompt to send message', async ({ page }) => {
    await goToGenerator(page);
    await expect(page.getByText(/Send a message to generate/i)).toBeVisible();
  });

  test('empty state disappears after slides generated', async ({ page }) => {
    // Generate slides and verify empty state gone
  });
});
```

### 6. Error Handling Tests

```typescript
test.describe('ErrorHandling', () => {
  test('shows error message on stream failure', async ({ page }) => {
    await page.route('http://localhost:8000/api/chat/stream', (route) => {
      route.fulfill({
        status: 500,
        contentType: 'application/json',
        body: JSON.stringify({ detail: 'Internal server error' }),
      });
    });

    await goToGenerator(page);
    await page.getByRole('textbox', { name: /Ask to generate/i }).fill('Create slides');
    await page.getByRole('button', { name: 'Send' }).click();

    // Should show error
    await expect(page.getByText(/error|failed/i)).toBeVisible({ timeout: 5000 });
  });

  test('can retry after error', async ({ page }) => {
    // If retry button exists
  });
});
```

---

## Complete Test File Template

```typescript
import { test, expect, Page } from '@playwright/test';
import {
  mockProfiles,
  mockDeckPrompts,
  mockSlideStyles,
  mockSessions,
  mockSlides,
  createStreamingResponse,
} from '../fixtures/mocks';

/**
 * Chat UI Tests
 *
 * Tests chat input, message display, loading states, and slide generation.
 * Run: cd frontend && npx playwright test tests/e2e/chat-ui.spec.ts
 */

async function setupMocks(page: Page) {
  // Mock settings endpoints
  await page.route('http://localhost:8000/api/settings/profiles', (route) => {
    route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(mockProfiles) });
  });
  await page.route('http://localhost:8000/api/settings/deck-prompts', (route) => {
    route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(mockDeckPrompts) });
  });
  await page.route('http://localhost:8000/api/settings/slide-styles', (route) => {
    route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(mockSlideStyles) });
  });
  await page.route('http://localhost:8000/api/sessions**', (route) => {
    route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(mockSessions) });
  });
  await page.route('**/api/version**', (route) => {
    route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ version: '1.0.0' }) });
  });

  // Mock chat stream - default success response
  await page.route('http://localhost:8000/api/chat/stream', (route) => {
    route.fulfill({
      status: 200,
      contentType: 'text/event-stream',
      body: createStreamingResponse(mockSlides),
    });
  });
}

async function goToGenerator(page: Page) {
  await page.goto('/');
  await page.getByRole('navigation').getByRole('button', { name: 'Generator' }).click();
  await expect(page.getByRole('heading', { name: 'Chat', level: 2 })).toBeVisible();
}

test.describe('ChatInput', () => {
  test.beforeEach(async ({ page }) => {
    await setupMocks(page);
  });

  // Implement tests from section 1
});

test.describe('MessageList', () => {
  test.beforeEach(async ({ page }) => {
    await setupMocks(page);
  });

  // Implement tests from section 2
});

test.describe('LoadingStates', () => {
  test.beforeEach(async ({ page }) => {
    await setupMocks(page);
  });

  // Implement tests from section 3
});

test.describe('SlideGeneration', () => {
  test.beforeEach(async ({ page }) => {
    await setupMocks(page);
  });

  // Implement tests from section 4
});

test.describe('EmptyState', () => {
  test.beforeEach(async ({ page }) => {
    await setupMocks(page);
  });

  // Implement tests from section 5
});

test.describe('ErrorHandling', () => {
  test.beforeEach(async ({ page }) => {
    await setupMocks(page);
  });

  // Implement tests from section 6
});
```

---

## Verification Checklist

Before marking complete:

- [ ] All tests pass: `npx playwright test tests/e2e/chat-ui.spec.ts`
- [ ] No strict mode violations
- [ ] Tests cover: input, messages, loading, slides, empty state, errors
- [ ] File committed to git

---

## Selector Tips

| Element | Likely Selector |
|---------|-----------------|
| Chat input | `getByRole('textbox', { name: /Ask to generate/i })` |
| Send button | `getByRole('button', { name: 'Send' })` |
| Loading indicator | `getByText(/generating|loading/i)` or look for spinner class |
| Empty state | `getByText('No slides yet')` |
| Slide tiles | May need to explore component for exact structure |
| Error message | `getByText(/error|failed/i)` or `.text-red-*` class |

---

## Debug Commands

```bash
# Run with visible browser
npx playwright test tests/e2e/chat-ui.spec.ts --headed

# Run single test
npx playwright test tests/e2e/chat-ui.spec.ts -g "displays chat input"

# Debug mode
npx playwright test tests/e2e/chat-ui.spec.ts --debug
```
