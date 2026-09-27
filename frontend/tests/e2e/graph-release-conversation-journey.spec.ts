/**
 * The conversation-user journey across three Graph Versions (Task 11, AC9).
 *
 * A non-admin user exercises three sessions with different Graph Version pins,
 * replayed over Task 10's recorded HTTP contract.  The journey proves:
 * - graph-version-status shows the pinned version and the "Start latest" upgrade path
 * - Start latest creates exactly one new session and leaves the original immutable
 * - mixed-release-warning is visible on a deck with v1 and v2 contributor evidence
 * - a non-admin is redirected from /admin with no admin API calls and no admin
 *   fields leaked in the conversation exchanges (AC6 user side)
 * - the graph-mode chat request carries no release id
 *
 * Contract cursor:
 *   CONVERSATION_IDS has one mutation (S16-post-post-rollback-root, position 4).
 *   Old-root and new-root session GETs are served via the cursor and therefore
 *   tracked in served.reads, served.lookahead and served.carried.
 *   Collaboration-history GETs are served from named, explicit stubs so they
 *   do not reach the contract (no route.fallback() is used anywhere).
 *
 * Route discipline (Concern 4):
 *   Every response outside the recorded contract is named, minimal and asserted.
 *   Old-root collaboration-history is served from OLD_ROOT_COLLAB_BODY (the
 *   recorded exchange body).  New-root and post-rollback-root get named empty
 *   stubs.  There are no silent route.fallback() paths.
 *
 * Run:
 *   cd frontend && npx playwright test \
 *     tests/e2e/graph-release-conversation-journey.spec.ts \
 *     --project=chromium --workers=1
 */
import { expect, test, type BrowserContext, type Page } from '@playwright/test';
import {
  exchange,
  installContract,
  loadContract,
  type RecordedRequests,
} from '../fixtures/graphLifecycleContract';
import {
  mockAvailableTools,
  mockDeckPrompts,
  mockDefaultAgentConfig,
} from '../fixtures/mocks';
import { ALLOWED_ACTION_NAMES } from '../fixtures/forbiddenActionNames';

const contract = loadContract();

/**
 * The exchanges the conversation journey installs in the cursor.
 *
 * Positions in `served`:
 *   0 S12-get-old-root              GET /api/sessions/old-root  (v1 active=2; never
 *                                    served — S16-get-old-root is more recent)
 *   1 S12b-get-old-root-...         GET .../collaboration-history (mixed=true; served
 *                                    via OLD_ROOT_COLLAB_BODY, not the cursor)
 *   2 S16-get-old-root              GET /api/sessions/old-root  (v1 active=3)
 *   3 S16-get-new-root              GET /api/sessions/new-root  (v2 active=3)
 *   4 S16-post-post-rollback-root   POST /api/sessions → v3    (THE ONLY MUTATION)
 *
 * The mutation is at position 4.  Before it fires, horizon=4: old-root GET selects
 * position 2 (the last old-root recording before the horizon); new-root GET selects
 * position 3.  After the mutation, horizon=5 (served.length), and every subsequent
 * session GET is classified as `carried` because its recording precedes the mutation.
 */
const CONVERSATION_IDS = [
  'S12-get-old-root',                          // pos 0 — present but never served
  'S12b-get-old-root-collaboration-history',   // pos 1 — body used by OLD_ROOT_COLLAB_BODY
  'S16-get-old-root',                          // pos 2 — old-root session GET
  'S16-get-new-root',                          // pos 3 — new-root session GET
  'S16-post-post-rollback-root',               // pos 4 — Start-latest mutation
] as const;

// ---------------------------------------------------------------------------
// Named bodies derived from recorded exchanges (Concern 4: no silent stubs)
// ---------------------------------------------------------------------------

/** The v3 session body from the POST — echoed for the subsequent GET. */
const POST_ROLLBACK_SESSION_BODY =
  exchange(contract, 'S16-post-post-rollback-root').body as Record<string, unknown>;

/**
 * Old-root's collaboration history, taken directly from the recorded exchange
 * (mixed_release_warning=true, Contributor 1 v2 + Contributor 2 v1).
 * Served explicitly so no route.fallback() is needed.
 */
const OLD_ROOT_COLLAB_BODY =
  exchange(contract, 'S12b-get-old-root-collaboration-history').body;

/**
 * Stubs for sessions whose collaboration history is not in the recording.
 * Each is minimal, named and checked against the correct request below.
 */
const EMPTY_COLLAB_STUB = {
  mixed_release_warning: false,
  has_legacy_evidence: false,
  groups: [],
};
const NEW_ROOT_COLLAB_STUB = EMPTY_COLLAB_STUB;
const POST_ROLLBACK_COLLAB_STUB = EMPTY_COLLAB_STUB;

// ---------------------------------------------------------------------------
// Shared journey state (serial describe)
// ---------------------------------------------------------------------------
let context: BrowserContext;
let page: Page;
let served: RecordedRequests;

/** Non-GET requests to old-root, recorded at the wire for the immutability assertion. */
const oldRootNonGets: string[] = [];

/** Chat request bodies captured for step 5. */
const chatBodies: Array<Record<string, unknown>> = [];

async function newConversationContext(
  browser: import('@playwright/test').Browser,
): Promise<BrowserContext> {
  return browser.newContext({
    baseURL: 'http://localhost:3000',
    storageState: {
      cookies: [],
      origins: [
        {
          origin: 'http://localhost:3000',
          localStorage: [{ name: 'tellr-app-tour-completed', value: 'true' }],
        },
      ],
    },
  });
}

test.describe.serial(
  'conversation-user journey across three Graph Versions',
  () => {
    test.beforeAll(async ({ browser }) => {
      context = await newConversationContext(browser);

      // Install the contract's cursor for the five conversation exchanges.
      served = await installContract(context, [...CONVERSATION_IDS]);

      // All routes below are registered AFTER installContract (LIFO order) so
      // they run BEFORE the contract's catch-all.  None uses route.fallback():
      // every request is handled explicitly.

      // Override current-user: APP_SHELL_RESPONSES returns is_admin:true for
      // the admin journey; the conversation user is not an admin.
      await context.route('**/api/user/current', async (route) => {
        await route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({
            username: 'user@test.com',
            display_name: 'Test User',
            is_admin: false,
          }),
        });
      });

      // ---------- Collaboration history (Concern 4) ----------
      //
      // Old-root's history IS in the recording (OLD_ROOT_COLLAB_BODY).
      // New-root and post-rollback-root are NOT; they get explicit empty stubs.
      // Using specific path patterns avoids any catch-all / fallback.

      await context.route(
        '**/api/sessions/old-root/collaboration-history',
        async (route, request) => {
          expect(request.method()).toBe('GET');
          await route.fulfill({
            status: 200,
            contentType: 'application/json',
            body: JSON.stringify(OLD_ROOT_COLLAB_BODY),
          });
        },
      );
      await context.route(
        '**/api/sessions/new-root/collaboration-history',
        async (route, request) => {
          expect(request.method()).toBe('GET');
          await route.fulfill({
            status: 200,
            contentType: 'application/json',
            body: JSON.stringify(NEW_ROOT_COLLAB_STUB),
          });
        },
      );
      await context.route(
        '**/api/sessions/post-rollback-root/collaboration-history',
        async (route, request) => {
          expect(request.method()).toBe('GET');
          await route.fulfill({
            status: 200,
            contentType: 'application/json',
            body: JSON.stringify(POST_ROLLBACK_COLLAB_STUB),
          });
        },
      );

      // ---------- Named session stubs ----------

      // The v3 session's GET: the contract records the POST that creates it
      // but no subsequent GET.  Serve the POST response body (all graph fields
      // match: graph_version=3, active_graph_version=3, is_older_than_active=false).
      await context.route(
        '**/api/sessions/post-rollback-root',
        async (route, request) => {
          expect(request.method()).toBe('GET');
          await route.fulfill({
            status: 200,
            contentType: 'application/json',
            body: JSON.stringify(POST_ROLLBACK_SESSION_BODY),
          });
        },
      );

      // ---------- Endpoints not in contract or APP_SHELL ----------

      await context.route(
        /\/api\/sessions\/[^/]+\/contributors$/,
        async (route) => {
          await route.fulfill({
            status: 200,
            contentType: 'application/json',
            body: JSON.stringify({ contributors: [] }),
          });
        },
      );
      await context.route(
        /\/api\/sessions\/[^/]+\/slides$/,
        async (route) => {
          await route.fulfill({
            status: 200,
            contentType: 'application/json',
            body: JSON.stringify({
              session_id: 'mock',
              slide_deck: {
                title: 'Mock deck',
                slide_count: 0,
                css: '',
                external_scripts: [],
                head_meta: {},
                scripts: '',
                slides: [],
                created_by: 'mock',
                created_at: '2026-01-01T00:00:00Z',
                modified_by: 'mock',
                modified_at: '2026-01-01T00:00:00Z',
                version: 1,
                deck_spec: null,
                findings: [],
                html_content: '',
              },
            }),
          });
        },
      );
      await context.route(
        /\/api\/sessions\/[^/]+\/messages$/,
        async (route) => {
          await route.fulfill({
            status: 200,
            contentType: 'application/json',
            body: JSON.stringify({ messages: [] }),
          });
        },
      );
      await context.route(
        /\/api\/sessions\/[^/]+\/agent-config$/,
        async (route) => {
          await route.fulfill({
            status: 200,
            contentType: 'application/json',
            body: JSON.stringify(mockDefaultAgentConfig),
          });
        },
      );

      // Session list GETs (always carry query params; the mutation POST has no
      // query params, so it skips this route and reaches the contract directly).
      await context.route(
        (url) => url.pathname === '/api/sessions' && url.search.length > 0,
        async (route, request) => {
          expect(request.method()).toBe('GET');
          await route.fulfill({
            status: 200,
            contentType: 'application/json',
            body: JSON.stringify({ sessions: [], total: 0 }),
          });
        },
      );

      await context.route('**/api/tools/available', async (route) => {
        await route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify(mockAvailableTools),
        });
      });
      await context.route('**/api/settings/deck-prompts', async (route) => {
        await route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify(mockDeckPrompts),
        });
      });
      await context.route('**/api/version', async (route) => {
        await route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({ version: '0.0.0-test' }),
        });
      });
      await context.route('**/api/version/check', async (route) => {
        await route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({ up_to_date: true }),
        });
      });
      await context.route('**/api/slides/versions**', async (route) => {
        await route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({ versions: [], current_version: null }),
        });
      });
      await context.route('**/api/images**', async (route) => {
        await route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({ images: [], total: 0 }),
        });
      });
      await context.route('**/api/verification/**', async (route) => {
        await route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({ status: 'ok' }),
        });
      });
      // Session lock/unlock (POST): the contract treats all POST requests as
      // mutations.  Intercept these here so they never reach the mutation queue.
      await context.route(/\/api\/sessions\/[^/]+\/(lock|unlock)$/, async (route) => {
        await route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({ locked: true }),
        });
      });

      // Unknown (locally-generated) session detail GETs.  UUID pattern only:
      // named sessions (old-root, new-root, post-rollback-root) are not UUIDs
      // and therefore bypass this route, going directly to the contract or to
      // a dedicated handler above.
      await context.route(
        /\/api\/sessions\/[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/,
        async (route) => {
          await route.fulfill({ status: 404 });
        },
      );

      // Chat stream (step 5): capture request and return a minimal SSE response.
      await context.route('**/api/chat/stream', async (route) => {
        chatBodies.push(
          JSON.parse(route.request().postData() ?? '{}') as Record<string, unknown>,
        );
        await route.fulfill({
          status: 200,
          contentType: 'text/event-stream',
          body: 'data: {"type":"complete"}\n\n',
        });
      });

      page = await context.newPage();

      // Track non-GET requests to old-root at the network level for the
      // immutability assertion in step 1.
      page.on('request', (req) => {
        if (req.method() !== 'GET' && req.url().includes('/old-root')) {
          oldRootNonGets.push(`${req.method()} ${req.url()}`);
        }
      });
    });

    test.afterAll(async () => {
      await context.close();
    });

    // ------------------------------------------------------------------
    // Step 1 — old-root shows v1/latest=3; Start latest → v3 session
    // ------------------------------------------------------------------
    test(
      '1. old-root after rollback shows v1 pinned/latest-3; ' +
        'Start latest creates v3 and leaves old-root immutable',
      async () => {
        await page.goto('/sessions/old-root/edit');

        // S16-get-old-root: graph_version=1, active_graph_version=3, is_older=true
        await expect(page.getByTestId('graph-version-status')).toContainText(
          'Pinned Graph Version 1; latest is 3',
        );

        await page.getByRole('button', { name: 'Start latest', exact: true }).click();
        await expect(page).toHaveURL(/\/sessions\/post-rollback-root\/edit/);

        // S16-post-post-rollback-root: graph_version=3, is_older=false
        await expect(page.getByTestId('graph-version-status')).toContainText(
          'Pinned Graph Version 3',
        );
        await expect(page.getByTestId('graph-version-status')).not.toContainText(
          'latest is',
        );

        // Exactly one mutation: the Start-latest POST.
        expect(served.mutations).toHaveLength(1);
        expect(served.mutations[0].id).toBe('S16-post-post-rollback-root');

        // old-root was never mutated: no PATCH or PUT hit that path.
        expect(oldRootNonGets).toEqual([]);
      },
    );

    // ------------------------------------------------------------------
    // Step 2 — new-root (v2) shows the correct version and is immutable
    // ------------------------------------------------------------------
    test(
      '2. new-root shows v2 pinned/latest=3 and is not mutated',
      async () => {
        const newRootNonGets: string[] = [];
        page.on('request', (req) => {
          if (req.method() !== 'GET' && req.url().includes('/new-root')) {
            newRootNonGets.push(`${req.method()} ${req.url()}`);
          }
        });

        await page.goto('/sessions/new-root/edit');

        // S16-get-new-root: graph_version=2, active_graph_version=3, is_older=true
        await expect(page.getByTestId('graph-version-status')).toContainText(
          'Pinned Graph Version 2; latest is 3',
        );

        // The mutation list is still length 1 (the step-1 POST only).
        expect(served.mutations).toHaveLength(1);
        expect(newRootNonGets).toEqual([]);
      },
    );

    // ------------------------------------------------------------------
    // Step 3 — old-root collaboration history: mixed-release warning names
    //           both v1 and v2
    // ------------------------------------------------------------------
    test(
      '3. old-root shows mixed-release warning naming both Graph Versions',
      async () => {
        await page.goto('/sessions/old-root/edit');

        // OLD_ROOT_COLLAB_BODY: mixed_release_warning=true,
        // groups: Contributor 1 v2 + Contributor 2 v1.
        const warning = page.getByTestId('mixed-release-warning');
        await expect(warning.getByTestId('mixed-release-warning-text')).toBeVisible();
        await expect(warning.getByTestId('mixed-release-warning-text')).toHaveText(
          'This shared deck has changes from multiple Graph Versions.',
        );

        // Open the disclosure and verify both versions appear in the row text.
        await warning
          .getByRole('button', { name: 'Change provenance', exact: true })
          .click();
        await expect(warning.getByTestId('mixed-release-row')).toHaveCount(2);

        const rowTexts = await warning
          .getByTestId('mixed-release-row')
          .allTextContents();
        const combined = rowTexts.join(' ');
        expect(combined).toContain('Graph Version 1');
        expect(combined).toContain('Graph Version 2');
      },
    );

    // ------------------------------------------------------------------
    // Step 4 — non-admin redirect: no admin content flash, no admin API
    //           calls, no admin fields in the conversation exchange bodies
    // ------------------------------------------------------------------
    test(
      '4. non-admin navigating to /admin is redirected ' +
        'with no admin content flash, no admin API calls, and no admin ' +
        'fields in the served conversation exchange bodies (AC6 user side)',
      async () => {
        const adminRequestUrls: string[] = [];
        page.on('request', (req) => {
          if (req.url().includes('/api/admin/')) {
            adminRequestUrls.push(`${req.method()} ${req.url()}`);
          }
        });

        // Navigate to the admin page (wrapped in RequireAdmin in App.tsx).
        // /admin IS guarded by RequireAdmin; /admin/agent-definitions has no
        // explicit route and hits the catch-all regardless of admin status.
        await page.goto('/admin');

        // RequireAdmin redirects a non-admin user to / or /help.
        await expect(page).toHaveURL(/\/(help)?$/);
        // No admin page heading was mounted — no flash.
        await expect(
          page.getByRole('heading', { level: 1, name: 'Admin' }),
        ).toHaveCount(0);
        // The landing page rendered (not a blank redirect target).
        await expect(
          page.getByRole('heading', { level: 2, name: 'AI Assistant' }),
        ).toBeVisible();

        // AC6: no admin API requests were made.
        expect(adminRequestUrls).toEqual([]);

        // AC6: the response bodies of the conversation exchanges contain no
        // agent-definition fields (prompt_text, endpoint_name).
        // Note: content_hash is present as a short (16-char) slide hash in the
        // session responses — not as a 64-char agent-definition hash.
        const servedBodies = CONVERSATION_IDS.map((id) =>
          JSON.stringify(exchange(contract, id).body),
        ).join('\n');
        expect(servedBodies).not.toContain('"prompt_text"');
        expect(servedBodies).not.toContain('"endpoint_name"');
        // A 64-char hex content_hash would indicate an agent-definition field.
        expect(servedBodies).not.toMatch(/"content_hash"\s*:\s*"[0-9a-f]{64}"/);

        // The forbidden-action count stays 8 (no new exemption added by #271).
        expect(ALLOWED_ACTION_NAMES).toHaveLength(8);
      },
    );

    // ------------------------------------------------------------------
    // Step 5 — USE AGENT MODE in v3 conversation: no release id in body
    // ------------------------------------------------------------------
    test(
      '5. USE AGENT MODE in the v3 conversation sends no release id',
      async () => {
        await page.goto('/sessions/post-rollback-root/edit');
        await expect(page.getByTestId('graph-version-status')).toContainText(
          'Pinned Graph Version 3',
        );

        const priorChatCount = chatBodies.length;
        await page.getByTestId('chat-input').fill('USE AGENT MODE build the lifecycle deck');
        await page.getByTestId('chat-input').press('Enter');

        await expect.poll(() => chatBodies.length).toBe(priorChatCount + 1);

        const chatBody = chatBodies[chatBodies.length - 1] as Record<string, unknown>;

        // The request contains session_id and message (ChatRequest shape).
        expect(typeof chatBody.session_id).toBe('string');
        expect(chatBody.session_id).toBe('post-rollback-root');
        expect(typeof chatBody.message).toBe('string');

        // The pinned release is resolved server-side from session_id; the
        // client never supplies a release identifier.
        expect(Object.keys(chatBody)).not.toContain('release_id');
        expect(Object.keys(chatBody)).not.toContain('graph_release_id');
      },
    );

    // ------------------------------------------------------------------
    // Final — exact contract state: unmatched, mutations, lookahead, carried
    // ------------------------------------------------------------------
    test(
      'final: exact contract state — unmatched empty, one mutation, pinned gaps',
      async () => {
        expect(served.unmatched).toEqual([]);
        expect(served.mutations.map((m) => m.id)).toEqual([
          'S16-post-post-rollback-root',
        ]);

        // Lookahead: GETs the page makes before the journey first recorded them.
        // With S16-get-old-root at position 2 and S16-get-new-root at position 3
        // (both before the mutation at position 4), all session GETs have a
        // recording before the horizon.  No lookahead expected.
        expect(served.lookahead).toEqual([]);

        // Carried: GETs whose latest recording precedes a mutation already sent.
        // After the Start-latest POST (position 4), every subsequent session GET
        // is carried: S16-get-new-root (pos 3), S16-get-old-root (pos 2).
        // React StrictMode causes each page load to issue each GET twice.
        // The exact list is pinned below so a new read (e.g. an extra history GET
        // in a refactored page) makes this test fail.
        expect(served.carried).toEqual([
          // --- step 2: new-root page load (StrictMode ×3) ---
          'S16-get-new-root',
          'S16-get-new-root',
          'S16-get-new-root',
          // --- step 3: old-root page load (StrictMode ×3) ---
          'S16-get-old-root',
          'S16-get-old-root',
          'S16-get-old-root',
        ]);
      },
    );
  },
);
