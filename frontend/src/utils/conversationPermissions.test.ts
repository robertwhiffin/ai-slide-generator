/**
 * #323 Task 4: who may change their own conversation on a deck (Clear chat; #317 delete a message).
 *
 * Only editors: CAN_EDIT and CAN_MANAGE. Viewers, profile-only levels, missing values and
 * wrongly-cased strings are refused.
 *
 * SABOTAGE: make canEditConversation also accept CAN_VIEW -> the CAN_VIEW case goes RED.
 */
import { describe, expect, it } from 'vitest';
import { canEditConversation } from './conversationPermissions';

describe('canEditConversation', () => {
  it.each([['CAN_EDIT'], ['CAN_MANAGE']])('returns true for %s', (permission) => {
    expect(canEditConversation(permission)).toBe(true);
  });

  it.each<[string, string | null | undefined]>([
    ['CAN_VIEW', 'CAN_VIEW'],
    ['CAN_USE', 'CAN_USE'],
    ['null', null],
    ['undefined', undefined],
    ['the empty string', ''],
    ["lower-case 'can_edit'", 'can_edit'],
  ])('returns false for %s', (_label, permission) => {
    expect(canEditConversation(permission)).toBe(false);
  });
});
