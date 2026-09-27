import { expect, type Locator } from '@playwright/test';
import { forbidsActionName } from './forbiddenActionNames';

/**
 * The browser half of #260's forbidden-action guard (C16/C40), shared by every spec
 * that walks the workbench: each `button` and `a` inside `scope` is read for its
 * aria-label, text and title, and no name source may offer a forbidden action.
 *
 * Each name source is checked on its own: exemptions are exact whole names (review
 * m-5), so a control naming itself twice is not concatenated. Returns the names read,
 * so a caller can prove the state it swept held the control it meant to exercise.
 */
export async function sweepForbiddenActionNames(scope: Locator): Promise<string[]> {
  const names = await scope.locator('button, a')
    .evaluateAll((controls) => controls.flatMap((control) => [
      control.getAttribute('aria-label') ?? '', control.textContent ?? '', control.getAttribute('title') ?? '',
    ].filter((source) => source.trim() !== '')));
  expect(names.length).toBeGreaterThan(0);
  for (const name of names) expect(forbidsActionName(name)).toBe(false);
  return names;
}
