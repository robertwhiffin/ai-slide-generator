/**
 * Copy for the chat panel's "Clear chat" action (#323, plan decision D8).
 * One message serves the owner and a contributor: "your conversation" is true for both.
 */
export const CLEAR_CHAT_LABEL = 'Clear chat';
export const CLEAR_CHAT_DIALOG_TITLE = 'Clear chat?';
export const CLEAR_CHAT_DIALOG_MESSAGE =
  'This deletes your conversation on this deck. Your slides, the Spec and save points stay as they '
  + "are, and the assistant carries on from the Spec and the current slides. This can't be undone.";
export const CLEAR_CHAT_TOOLTIP = 'Delete this conversation and keep the deck, its Spec and save points';
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
