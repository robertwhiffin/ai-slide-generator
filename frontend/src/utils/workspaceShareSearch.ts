/** True when the share-panel search should surface the "All workspace users" action. */
export function matchesWorkspaceShareSearch(query: string): boolean {
  const q = query.toLowerCase().trim();
  if (!q) {
    return false;
  }
  return q.includes('workspace') || q.includes('all');
}
