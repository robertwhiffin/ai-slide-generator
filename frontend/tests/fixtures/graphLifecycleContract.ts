/**
 * The recorded HTTP contract of #271's Graph Configuration lifecycle (Task 10, AC9).
 *
 * `graphLifecycleContract.json` is RECORDED from Task 6's journey over real PostgreSQL
 * and the shipped routers (`python -m tests.integration.graph_lifecycle_journey
 * --write-contract frontend/tests/fixtures/graphLifecycleContract.json`), never
 * hand-written. `tests/unit/test_graph_lifecycle_playwright_contract.py` validates
 * every recorded body against its named Pydantic model, and the PostgreSQL journey
 * compares a fresh recording's shape with the file, so a spec replaying it cannot
 * drift from the real API.
 *
 * Replay (C1):
 * - The served exchanges' PUT and POST requests are a queue, consumed strictly in
 *   recorded order. A mutation is matched on method and path only (Task 6 concern 4:
 *   ids inside bodies are the recording's), and its request body is kept so the spec
 *   can deep-equal it with the recorded `request`.
 * - A GET is served the LAST recorded body for its method and path that precedes the
 *   next unconsumed mutation: the server's state at that point of the journey. A GET
 *   the UI makes before the journey first recorded it is served the first later
 *   recording and listed in `lookahead`; a GET whose latest recording precedes a
 *   mutation the page has already sent (the journey never re-read it afterwards) is
 *   listed in `carried`. The spec pins both lists exactly, so every read the recording
 *   cannot answer from the page's own point in the journey is named.
 * - App-shell boot reads are served from the named, fixed `APP_SHELL_RESPONSES`.
 * - Any other `/api/**` request is answered 500 and listed in `unmatched`.
 */
import { readFileSync } from 'node:fs';
import type { BrowserContext, Page, Route } from '@playwright/test';
import { mockProfileSummaries, mockSlideStyles } from './mocks';

export interface ContractExchange {
  id: string;
  method: string;
  path: string;
  request: unknown;
  status: number;
  body: unknown;
  response_model: string | null;
  request_model: string | null;
}

export interface LifecycleContract {
  contract_version: 1;
  recorded_at_commit: string;
  exchanges: ContractExchange[];
}

export interface ServedRequest {
  /** The contract exchange (or app-shell response) that answered it. */
  id: string;
  method: string;
  path: string;
  /** The page's JSON request body, or `null` when it sent none. */
  body: unknown;
}

export interface RecordedRequests {
  /** Every served PUT/POST, in the order the page sent them. */
  readonly mutations: ServedRequest[];
  /** Every served contract GET, in order. */
  readonly reads: ServedRequest[];
  /** GETs served ahead of the point the journey recorded them (see the module doc). */
  readonly lookahead: string[];
  /** GETs served from a recording made before a mutation the page already sent. */
  readonly carried: string[];
  /** App-shell responses served, by name. */
  readonly shell: string[];
  /** Any `/api/**` request outside the contract and the app shell. */
  readonly unmatched: string[];
  /** The page's request body for the mutation served as `id`. */
  requestBody(id: string): unknown;
}

const CONTRACT_URL = new URL('./graphLifecycleContract.json', import.meta.url);

/** The recorded contract, read from disk (no `resolveJsonModule` needed). */
export function loadContract(): LifecycleContract {
  return JSON.parse(readFileSync(CONTRACT_URL, 'utf8')) as LifecycleContract;
}

/** The contract's exchange `id`; throws on an unknown id. */
export function exchange(contract: LifecycleContract, id: string): ContractExchange {
  const found = contract.exchanges.find((candidate) => candidate.id === id);
  if (found === undefined) throw new Error(`no recorded exchange ${id}`);
  return found;
}

/** The recorded exchanges the admin journey replays: every `/api/admin/**` one, in order. */
export function adminExchangeIds(contract: LifecycleContract): string[] {
  return contract.exchanges
    .filter((candidate) => candidate.path.startsWith('/api/admin/'))
    .map((candidate) => candidate.id);
}

const MUTATING = new Set(['PUT', 'POST', 'PATCH', 'DELETE']);

/**
 * Query parameters the UI adds that the recorded journey did not send. `limit` is
 * `listTestCaseRuns(id, 100)`'s page size; the journey's lists hold at most two runs.
 */
const UI_ONLY_QUERY_PARAMETERS = new Set(['limit']);

/**
 * App-shell boot reads (C1.3): fixed, named responses, never contract exchanges. The
 * profile, design-system and slide-style lists are `setupMocks`'s answers.
 * `admin-sibling-panel` answers the /admin page's other tabs (usage, feedback, Google
 * Slides, design system, slide style, judge), which mount hidden beside the Agent
 * Definitions panel. They 500 exactly as `admin-route-gate.spec.ts` stubs them: those
 * panels contain their own load errors, and none of them is under test here.
 */
interface ShellResponse {
  name: string;
  matches: (method: string, url: URL) => boolean;
  status: number;
  body: unknown;
}

export const APP_SHELL_RESPONSES: readonly ShellResponse[] = [
  {
    name: 'setup-status',
    matches: (method, url) => method === 'GET' && url.pathname === '/api/setup/status',
    status: 200,
    body: { configured: true },
  },
  {
    name: 'current-user',
    matches: (method, url) => method === 'GET' && url.pathname === '/api/user/current',
    status: 200,
    body: { username: 'lifecycle-admin@example.com', display_name: 'Lifecycle Admin', is_admin: true },
  },
  {
    name: 'profiles',
    matches: (method, url) => method === 'GET' && url.pathname === '/api/profiles',
    status: 200,
    body: mockProfileSummaries,
  },
  {
    name: 'design-systems',
    matches: (method, url) => method === 'GET' && url.pathname === '/api/settings/design-systems',
    status: 200,
    body: { design_systems: [], total: 0 },
  },
  {
    name: 'slide-styles',
    matches: (method, url) => method === 'GET' && url.pathname === '/api/settings/slide-styles',
    status: 200,
    body: mockSlideStyles,
  },
  {
    name: 'admin-sibling-panel',
    matches: (method, url) => method === 'GET'
      && (url.pathname.startsWith('/api/admin/') || url.pathname.startsWith('/api/feedback/'))
      && !url.pathname.startsWith('/api/admin/agent-definitions/'),
    status: 500,
    body: { detail: 'stubbed out in this spec' },
  },
];

function pathOf(recordedPath: string): { pathname: string; query: URLSearchParams } {
  const url = new URL(recordedPath, 'http://contract.invalid');
  return { pathname: url.pathname, query: url.searchParams };
}

function sameRequestTarget(recordedPath: string, url: URL): boolean {
  const recorded = pathOf(recordedPath);
  if (recorded.pathname !== url.pathname) return false;
  const sent = [...url.searchParams].filter(([key]) => !UI_ONLY_QUERY_PARAMETERS.has(key));
  const expected = [...recorded.query];
  return JSON.stringify(sent.sort()) === JSON.stringify(expected.sort());
}

function requestBody(route: Route): unknown {
  const raw = route.request().postData();
  if (raw === null || raw === '') return null;
  return JSON.parse(raw) as unknown;
}

async function fulfillJson(route: Route, status: number, body: unknown) {
  await route.fulfill({ status, contentType: 'application/json', body: JSON.stringify(body) });
}

/**
 * Serves exactly the exchanges named by `ids` (plus the app shell) to every page of
 * `target`, which shares one replay cursor, and returns what was served.
 */
export async function installContract(
  target: Page | BrowserContext,
  ids: readonly string[],
): Promise<RecordedRequests> {
  const contract = loadContract();
  const served = ids.map((id) => exchange(contract, id));
  const mutationPositions = served
    .map((candidate, position) => (MUTATING.has(candidate.method) ? position : -1))
    .filter((position) => position >= 0);
  let cursor = 0; // index into mutationPositions of the next unconsumed mutation

  const mutations: ServedRequest[] = [];
  const reads: ServedRequest[] = [];
  const lookahead: string[] = [];
  const carried: string[] = [];
  const shell: string[] = [];
  const unmatched: string[] = [];

  await target.route((url) => url.pathname.startsWith('/api/'), async (route) => {
    const request = route.request();
    const method = request.method();
    const url = new URL(request.url());
    const label = `${method} ${url.pathname}${url.search}`;

    const shellResponse = APP_SHELL_RESPONSES.find((candidate) => candidate.matches(method, url));
    if (shellResponse !== undefined) {
      shell.push(shellResponse.name);
      await fulfillJson(route, shellResponse.status, shellResponse.body);
      return;
    }

    if (MUTATING.has(method)) {
      const position = mutationPositions[cursor];
      const expected = position === undefined ? undefined : served[position];
      if (expected === undefined || expected.method !== method || !sameRequestTarget(expected.path, url)) {
        unmatched.push(`${label} (expected ${expected === undefined ? 'no further mutation' : expected.id})`);
        await fulfillJson(route, 500, { detail: 'request outside the recorded contract' });
        return;
      }
      cursor += 1;
      mutations.push({ id: expected.id, method, path: url.pathname, body: requestBody(route) });
      await fulfillJson(route, expected.status, expected.body);
      return;
    }

    const horizon = mutationPositions[cursor] ?? served.length;
    const candidates = served
      .map((candidate, position) => ({ candidate, position }))
      .filter(({ candidate }) => candidate.method === method && sameRequestTarget(candidate.path, url));
    const atOrBefore = candidates.filter(({ position }) => position < horizon).at(-1);
    const answer = atOrBefore ?? candidates[0];
    if (answer === undefined) {
      unmatched.push(label);
      await fulfillJson(route, 500, { detail: 'request outside the recorded contract' });
      return;
    }
    if (atOrBefore === undefined) lookahead.push(answer.candidate.id);
    const lastSent = cursor === 0 ? -1 : mutationPositions[cursor - 1];
    if (atOrBefore !== undefined && lastSent > atOrBefore.position) carried.push(answer.candidate.id);
    reads.push({ id: answer.candidate.id, method, path: url.pathname, body: null });
    await fulfillJson(route, answer.candidate.status, answer.candidate.body);
  });

  return {
    mutations,
    reads,
    lookahead,
    carried,
    shell,
    unmatched,
    requestBody(id: string) {
      const found = mutations.find((candidate) => candidate.id === id);
      if (found === undefined) throw new Error(`the page never sent ${id}`);
      return found.body;
    },
  };
}
