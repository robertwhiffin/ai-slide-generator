/**
 * #317 Task 6: the copy for deleting a chat message (plan decision D14).
 *
 * A failed delete maps to its message by HTTP status only (duck-typed on `status`, so a module
 * mock's error maps too). The dialog promises what D9 decides: the deck is not rolled back.
 *
 * SABOTAGE:
 *   - map 404 to FAILED                              -> "maps a failed delete ... (404 ...)" RED.
 *   - check `instanceof ApiError` instead of `status` -> the plain-object cases RED.
 *   - reword any string, or add/drop an exported one  -> "uses the agreed copy" RED.
 */
import { describe, expect, it } from 'vitest';
import * as copy from './deleteMessageCopy';
import { ApiError } from '../../services/api';

const {
  DELETE_MESSAGE_BUSY,
  DELETE_MESSAGE_DIALOG_MESSAGE,
  DELETE_MESSAGE_FAILED,
  DELETE_MESSAGE_FORBIDDEN,
  DELETE_MESSAGE_GONE,
  deleteMessageErrorMessage,
} = copy;

describe('deleteMessageErrorMessage', () => {
  it.each<[string, unknown, string]>([
    ['409 (a turn or another change is running)', new ApiError(409, 'Conversation is busy'), DELETE_MESSAGE_BUSY],
    ['403 (not an editor, or not the creator)', new ApiError(403, 'Conversations are private.'), DELETE_MESSAGE_FORBIDDEN],
    ['404 (the message is gone)', new ApiError(404, 'Message not found'), DELETE_MESSAGE_GONE],
    ['500', new ApiError(500, 'Internal Server Error'), DELETE_MESSAGE_FAILED],
    ['{} (no status)', {}, DELETE_MESSAGE_FAILED],
    ['a plain { status: 409 }', { status: 409 }, DELETE_MESSAGE_BUSY],
    ['a plain { status: 403 }', { status: 403 }, DELETE_MESSAGE_FORBIDDEN],
    ['a plain { status: 404 }', { status: 404 }, DELETE_MESSAGE_GONE],
    ['a network Error', new TypeError('Failed to fetch'), DELETE_MESSAGE_FAILED],
    ['null', null, DELETE_MESSAGE_FAILED],
    ['a string', 'boom', DELETE_MESSAGE_FAILED],
  ])('maps a failed delete to its message (%s)', (_label, err, expected) => {
    expect(deleteMessageErrorMessage(err)).toBe(expected);
  });

  it("never uses the server's detail text", () => {
    // A 500 whose detail happens to read like a busy message is still a plain failure.
    expect(deleteMessageErrorMessage(new ApiError(500, DELETE_MESSAGE_BUSY))).toBe(DELETE_MESSAGE_FAILED);
  });
});

describe('DELETE_MESSAGE_DIALOG_MESSAGE', () => {
  it('says the slides and the Spec are not rolled back, and that the delete cannot be undone (D9)', () => {
    expect(DELETE_MESSAGE_DIALOG_MESSAGE).toContain('slides');
    expect(DELETE_MESSAGE_DIALOG_MESSAGE).toContain('Spec');
    expect(DELETE_MESSAGE_DIALOG_MESSAGE).toContain('not rolled back');
    expect(DELETE_MESSAGE_DIALOG_MESSAGE).toContain("can't be undone");
    expect(DELETE_MESSAGE_DIALOG_MESSAGE).not.toMatch(/turn/i);
  });
});

describe('deleteMessageCopy', () => {
  it('uses the agreed copy (D14), and exports no other string', () => {
    const strings = Object.fromEntries(Object.entries(copy).filter(([, value]) => typeof value === 'string'));

    expect(strings).toEqual({
      DELETE_MESSAGE_TOOLTIP: 'Delete this message and the replies to it',
      DELETE_MESSAGE_DIALOG_TITLE: 'Delete this message?',
      DELETE_MESSAGE_DIALOG_MESSAGE:
        "This deletes your message and the assistant's replies to it, so the assistant won't see them "
        + 'again. Anything it changed in your slides or the Spec stays as it is; it is not rolled back. '
        + "This can't be undone.",
      DELETE_MESSAGE_CONFIRM_LABEL: 'Delete',
      DELETE_MESSAGE_BUSY:
        'Something is still running on this deck. Wait for it to finish, then delete the message.',
      DELETE_MESSAGE_FORBIDDEN: 'Only editors can delete messages, and only in their own conversation.',
      DELETE_MESSAGE_GONE:
        'That message is no longer in this conversation. Reload the page to see the current conversation.',
      DELETE_MESSAGE_FAILED:
        "Couldn't delete the message. Reload the page to see the current conversation, then try again.",
    });
  });
});
