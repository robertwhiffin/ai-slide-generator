/**
 * Query-agnostic route matchers for Playwright `page.route`.
 *
 * WHY: mocking an endpoint with an exact URL string couples the test to the
 * request's CURRENT query string. When production later adds or changes a
 * param, the pattern stops matching SILENTLY — the request falls through to
 * whatever broader mock is registered (for /api/sessions that is the
 * '**' glob in setup-mocks.ts, which returns a fixed two-session list) and the
 * spec fails somewhere far away, looking like a product bug rather than a dead
 * mock. That is exactly how four design-system-selector specs broke when
 * `listSessions` went from `?limit=5` to `?limit=10&deck_only=true`.
 *
 * Matching on PATHNAME ONLY removes that coupling: a future query-string change
 * cannot blind the mock. The pathname is still compared EXACTLY, so a
 * list-endpoint mock never creeps onto sibling sub-resources (e.g. an
 * `/agent-config` matcher must not swallow `/agent-config/tools`).
 *
 * Covered by tests/api-route-matcher.spec.ts.
 */

/**
 * Match any request whose pathname is exactly `pathname`, regardless of query
 * string or host.
 *
 * Host-agnostic on purpose: the dev server serves some calls same-origin
 * (localhost:3000) while others go straight to the API origin (127.0.0.1:8000),
 * and a pathname match covers both without a pattern per host.
 *
 *   await page.route(apiPath('/api/sessions'), handler);   // ?limit=5, ?limit=10&deck_only=true, ...
 */
export function apiPath(pathname: string): (url: URL) => boolean {
  return (url: URL) => url.pathname === pathname;
}

/**
 * Match any request whose pathname matches `pattern`, regardless of query
 * string or host. Use for parameterised paths.
 *
 * `pattern` is tested against the PATHNAME ALONE, so anchor it (`^...$`) to keep
 * it exact — against a full URL a trailing `$` is defeated by any query string,
 * which is the fragility this module exists to remove.
 *
 *   await page.route(apiPathMatching(/^\/api\/sessions\/[^/]+\/lock$/), handler);
 */
export function apiPathMatching(pattern: RegExp): (url: URL) => boolean {
  return (url: URL) => pattern.test(url.pathname);
}
