import type { TurnProgress } from '../../types/turnProgress';

/** Stop-generation UI copy (interrupt generation). Exact strings; tests pin them. */

export const STOP_TOOLTIP = 'Stop generating (Esc)';
export const STOP_ARIA_LABEL = 'Stop generating';
export const GENERATING_HINT = 'Esc to cancel · Enter to send · Shift+Enter new line';
export const STOP_DIALOG_TITLE = 'Stop generating?';
export const STOP_KEEP_LABEL = 'Keep generating';
export const STOP_CONFIRM_LABEL = 'Stop and discard';
export const CANCELLED_NOTICE = 'Generation cancelled. Nothing was changed.';
export const FAILED_NOTICE = 'Generation failed. Nothing was changed.';
export const REFUSED_STOP_NOTICE =
  "Someone else has edited this deck since you sent this, so it can't be rolled back.";
export const FAILED_KEPT_NOTICE =
  "Generation failed, and it couldn't be undone because someone else has edited this deck since you sent your message.";
export const RESTORE_PENDING_NOTICE =
  'This deck is still being restored after a failed generation. Try again in a minute.';
export const STOP_FAILED_ERROR = "Couldn't stop the generation. It is still running.";

const DIALOG_TAIL =
  'If you stop now, every slide built so far is thrown away and the deck goes back to how it was before you sent this message.';

export function stopDialogMessage(done: number, total: number): string {
  const progress = total > 0 ? ` (${done} of ${total} done)` : '';
  return `Your slides are being built${progress}. ${DIALOG_TAIL}`;
}

/** Stopping while slides are being built (or the finished deck reviewed) throws work away: ask first. */
export function stopNeedsConfirmation(progress: TurnProgress | null): boolean {
  return progress?.phase === 'building' || progress?.phase === 'reviewing_deck';
}
