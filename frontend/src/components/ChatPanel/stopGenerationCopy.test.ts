/**
 * Interrupt generation, Task 9: the stop-generation copy (plan Global Constraints, "Copy, exact").
 *
 * `stopGenerationCopy.ts` holds the UI copy strings from Global Constraints, plus
 * `stopDialogMessage(done, total)`. The backend-only 409 details (arc-review-busy, engine-race,
 * not-stoppable) are not UI strings and are not required here (controller ruling, Task 9). The
 * restore-pending detail is required, because the UI shows it.
 *
 * The plan does not name the constants, so the module is checked by value: every string it exports,
 * at any depth (a flat `export const`, or grouped in an object). The strings are literals here, so a
 * reworded constant cannot pass.
 *
 * SABOTAGE (for the reviewer):
 *   - reword or drop any string                       -> test_copy_module_holds_every_copy_string RED.
 *   - keep ` ({done} of {total} done)` when total is 0 -> test_stop_dialog_message_with_and_without_total RED.
 *   - key the short form on done === 0, not total === 0 -> the (0, 3) case RED.
 */
import { describe, expect, it } from 'vitest';
import * as copy from './stopGenerationCopy';

const DIALOG_TAIL =
  'If you stop now, every slide built so far is thrown away and the deck goes back to how it was before you sent this message.';

/** Every UI copy string in Global Constraints except the dialog message, which is the function below. */
const COPY = [
  'Stop generating (Esc)',
  'Stop generating',
  'Esc to cancel · Enter to send · Shift+Enter new line',
  'Stop generating?',
  'Keep generating',
  'Stop and discard',
  'Generation cancelled. Nothing was changed.',
  'Generation failed. Nothing was changed.',
  "Someone else has edited this deck since you sent this, so it can't be rolled back.",
  "Generation failed, and it couldn't be undone because someone else has edited this deck since you sent your message.",
  'This deck is still being restored after a failed generation. Try again in a minute.',
  "Couldn't stop the generation. It is still running.",
];

function stringsIn(value: unknown, seen = new Set<unknown>()): string[] {
  if (typeof value === 'string') return [value];
  if (value === null || typeof value !== 'object' || seen.has(value)) return [];
  seen.add(value);
  return Object.values(value as Record<string, unknown>).flatMap((v) => stringsIn(v, seen));
}

describe('stopGenerationCopy', () => {
  it('test_copy_module_holds_every_copy_string', () => {
    const exported = stringsIn({ ...copy });

    for (const text of COPY) expect(exported).toContain(text);
  });

  it('test_stop_dialog_message_with_and_without_total', () => {
    expect(copy.stopDialogMessage(2, 5)).toBe(
      'Your slides are being built (2 of 5 done). If you stop now, every slide built so far is thrown away and the deck goes back to how it was before you sent this message.',
    );
    expect(copy.stopDialogMessage(0, 3)).toBe(`Your slides are being built (0 of 3 done). ${DIALOG_TAIL}`);
    expect(copy.stopDialogMessage(0, 0)).toBe(
      'Your slides are being built. If you stop now, every slide built so far is thrown away and the deck goes back to how it was before you sent this message.',
    );
  });
});
