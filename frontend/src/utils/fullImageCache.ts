/**
 * Recently shown full-size images by token. A token's image never changes, so stepping back to
 * an option in the preview does not fetch it again. Small, because each entry can be a few MB
 * of base64.
 */
const CACHE = new Map<string, string>();
const CACHE_SIZE = 8;

export function cachedFullImage(token: string): string | undefined {
  return CACHE.get(token);
}

export function rememberFullImage(token: string, src: string): void {
  CACHE.delete(token);
  CACHE.set(token, src);
  while (CACHE.size > CACHE_SIZE) {
    const oldest = CACHE.keys().next().value;
    if (oldest === undefined) break;
    CACHE.delete(oldest);
  }
}

export function __clearFullImageCacheForTests(): void {
  CACHE.clear();
}
