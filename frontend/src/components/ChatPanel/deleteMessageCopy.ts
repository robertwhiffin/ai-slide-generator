/**
 * Copy for the chat panel's per-message delete (#317, plan decision D14).
 * The dialog says the deck is not rolled back: deleting a message never undoes what it changed.
 */
export const DELETE_MESSAGE_TOOLTIP = 'Delete this message and the replies to it';
export const DELETE_MESSAGE_DIALOG_TITLE = 'Delete this message?';
export const DELETE_MESSAGE_DIALOG_MESSAGE =
  "This deletes your message and the assistant's replies to it, so the assistant won't see them "
  + 'again. Anything it changed in your slides or the Spec stays as it is; it is not rolled back. '
  + "This can't be undone.";
export const DELETE_MESSAGE_CONFIRM_LABEL = 'Delete';
export const DELETE_MESSAGE_BUSY =
  'Something is still running on this deck. Wait for it to finish, then delete the message.';
export const DELETE_MESSAGE_FORBIDDEN =
  'Only editors can delete messages, and only in their own conversation.';
export const DELETE_MESSAGE_GONE =
  'That message is no longer in this conversation. Reload the page to see the current conversation.';
export const DELETE_MESSAGE_FAILED =
  "Couldn't delete the message. Reload the page to see the current conversation, then try again.";

/** Maps a failed delete to its message, by HTTP status and never by the server's detail text. */
export function deleteMessageErrorMessage(err: unknown): string {
  // Duck-typed on `status`, not `instanceof`, so a test that mocks the API module still maps correctly.
  const status = typeof err === 'object' && err !== null && 'status' in err
    ? (err as { status: unknown }).status : undefined;
  if (status === 409) return DELETE_MESSAGE_BUSY;
  if (status === 403) return DELETE_MESSAGE_FORBIDDEN;
  if (status === 404) return DELETE_MESSAGE_GONE;
  return DELETE_MESSAGE_FAILED;
}
