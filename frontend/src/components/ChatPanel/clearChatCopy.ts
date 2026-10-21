/**
 * Copy for the chat panel's "Clear chat" action (#323, plan decision D8).
 * One message serves the owner and a contributor: "your conversation" is true for both.
 * The dialog message and tooltip have a Spec-less variant, chosen by hasDeckSpec (#317 D1).
 */
export const CLEAR_CHAT_LABEL = 'Clear chat';
export const CLEAR_CHAT_DIALOG_TITLE = 'Clear chat?';
export const CLEAR_CHAT_DIALOG_MESSAGE =
  'This deletes your conversation on this deck. Your slides, the Spec and save points stay as they '
  + "are, and the assistant carries on from the Spec and the current slides. This can't be undone.";
export const CLEAR_CHAT_TOOLTIP = 'Delete this conversation and keep the deck, its Spec and save points';
/**
 * On a deck without a Spec (#317 lifted #323's Spec gate). It promises no Spec and no "carries on":
 * the graph architect never sees slide HTML and refuses an edit with no persisted Spec
 * (edit_without_spec), and the legacy assistant has only the slides once its history is gone.
 */
export const CLEAR_CHAT_DIALOG_MESSAGE_NO_SPEC =
  'This deletes your conversation on this deck. Your slides and save points stay as they are, but '
  + "the assistant won't remember anything you discussed, so say what you want in full. This can't "
  + 'be undone.';
export const CLEAR_CHAT_TOOLTIP_NO_SPEC = 'Delete this conversation and keep the deck and its save points';
export const CLEAR_CHAT_BUSY =
  'Something is still running on this deck. Wait for it to finish, then clear the chat.';
export const CLEAR_CHAT_FORBIDDEN = 'Only editors can clear the chat, and only their own conversation.';
export const CLEAR_CHAT_FAILED =
  "Couldn't clear the chat. Reload the page to see its current state, then try again.";

/** Maps a failed clear to its message, by HTTP status and never by the server's detail text. */
export function clearChatErrorMessage(err: unknown): string {
  // Duck-typed on `status`, not `instanceof`, so a test that mocks the API module still maps correctly.
  const status = typeof err === 'object' && err !== null && 'status' in err
    ? (err as { status: unknown }).status : undefined;
  if (status === 409) return CLEAR_CHAT_BUSY;
  if (status === 403) return CLEAR_CHAT_FORBIDDEN;
  return CLEAR_CHAT_FAILED;
}
