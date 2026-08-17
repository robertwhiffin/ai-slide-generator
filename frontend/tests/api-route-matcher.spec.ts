import { test, expect } from '@playwright/test';
import { apiPath } from './helpers/api-route';

/**
 * Self-test for the query-agnostic route matcher.
 *
 * WHY THIS EXISTS: four tests in design-system-selector.spec.ts mocked the
 * sidebar session fetch with the exact string
 * 'http://127.0.0.1:8000/api/sessions?limit=5'. When main changed that call to
 * '?limit=10&deck_only=true' (frontend/src/services/api.ts listSessions), the
 * pattern silently stopped matching — the request fell through to the broad
 * '/api/sessions**' mock in helpers/setup-mocks.ts, which returns only two
 * sessions, and the specs timed out waiting for a third fixture that never
 * rendered. Nothing failed loudly at the mock layer; the specs just went red
 * for an unrelated-looking reason.
 *
 * apiPath matches on PATHNAME ONLY, so a future query-string change in main
 * cannot blind those specs again. These assertions pin the two properties that
 * make it safe: query strings are ignored, and the pathname is still matched
 * EXACTLY (no prefix creep onto sibling endpoints like .../agent-config/tools).
 */

const url = (u: string) => new URL(u);

test.describe('apiPath route matcher', () => {
  test('ignores the query string entirely', () => {
    const match = apiPath('/api/sessions');
    // The shape these mocks were originally written against.
    expect(match(url('http://127.0.0.1:8000/api/sessions?limit=5'))).toBe(true);
    // The shape main changed to — the regression that broke the four specs.
    expect(match(url('http://127.0.0.1:8000/api/sessions?limit=10&deck_only=true'))).toBe(true);
    // No query at all.
    expect(match(url('http://127.0.0.1:8000/api/sessions'))).toBe(true);
    // Any future param combination.
    expect(match(url('http://127.0.0.1:8000/api/sessions?anything=else&more=1'))).toBe(true);
  });

  test('matches the pathname exactly — no prefix creep onto sibling routes', () => {
    const match = apiPath('/api/sessions');
    // Sub-resources must NOT be swallowed by the list-endpoint mock.
    expect(match(url('http://127.0.0.1:8000/api/sessions/abc-123'))).toBe(false);
    expect(match(url('http://127.0.0.1:8000/api/sessions/abc-123/slides'))).toBe(false);
    // A longer sibling path that merely starts with the same characters.
    expect(match(url('http://127.0.0.1:8000/api/sessions-archive'))).toBe(false);
    expect(match(url('http://127.0.0.1:8000/api/other'))).toBe(false);
  });

  test('distinguishes agent-config from its /tools sub-resource', () => {
    // Production calls BOTH /agent-config and /agent-config/tools
    // (frontend/src/services/api.ts), so an over-broad matcher would hijack
    // the tools call and change what the app sees.
    const match = apiPath('/api/sessions/s-1/agent-config');
    expect(match(url('http://127.0.0.1:8000/api/sessions/s-1/agent-config'))).toBe(true);
    expect(match(url('http://127.0.0.1:8000/api/sessions/s-1/agent-config?x=1'))).toBe(true);
    expect(match(url('http://127.0.0.1:8000/api/sessions/s-1/agent-config/tools'))).toBe(false);
  });

  test('is host-agnostic so it works for same-origin and API-origin calls', () => {
    // The dev server proxies some calls same-origin (localhost:3000) while
    // others go direct to the API origin (127.0.0.1:8000). Matching on
    // pathname covers both without duplicating patterns per host.
    const match = apiPath('/api/sessions');
    expect(match(url('http://localhost:3000/api/sessions?limit=10'))).toBe(true);
    expect(match(url('http://127.0.0.1:8000/api/sessions?limit=10'))).toBe(true);
  });
});
