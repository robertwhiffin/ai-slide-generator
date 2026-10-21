/** Whether the caller may change their own conversation on this deck (clear it; #317: delete a message). */
export function canEditConversation(permission: string | null | undefined): boolean {
  return permission === 'CAN_EDIT' || permission === 'CAN_MANAGE';
}
