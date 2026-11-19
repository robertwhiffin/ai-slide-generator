/**
 * Presenter window end to end: P opens it from presentation mode, and the two
 * windows step together both ways.
 *
 * The body lives in tests/helpers/presenter-flow.ts so a local runner that
 * attaches to an existing browser can run the same steps (Playwright does not
 * allow one test file to import another).
 *
 * Run: cd frontend && npx playwright test tests/e2e/presenter-view.spec.ts
 */
import { test } from '@playwright/test';
import { presenterFlow } from '../helpers/presenter-flow';

export { presenterFlow };

test('presenter window steps both ways with presentation mode', async ({ context, baseURL }) =>
  presenterFlow(context, baseURL!));
