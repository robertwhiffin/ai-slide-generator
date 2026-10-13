/**
 * Task 6 — walk the rebuilt app tour end to end against a mocked, STATEFUL
 * staged-demo backend.
 *
 * This is the only test that proves every one of the 35 steps' targets actually
 * mounts at step time.  react-joyride skips a step whose target never becomes
 * visible (targetWaitTimeout) and moves on, so asserting each step's title in
 * order catches a target that is missing, hidden, or late.
 *
 * The mock mirrors the real backend contract (src/api/routes/tour.py
 * `_run_stage`, src/api/routes/sessions.py `get_session` / `get_session_slides`,
 * session_manager `get_messages` / `get_slide_deck`):
 *   - POST /api/tour/demo-deck                     -> {session_id, title}; stage 'prompt'
 *   - POST /api/tour/demo-deck/:id/stages/:stage   -> {session_id, stage, applied, slide_count};
 *       already-applied -> applied:false and NO writes; previous stage missing -> 409
 *   - GET  /api/sessions/tour-demo                 -> session dict + messages + slide_deck
 *   - GET  /api/sessions/tour-demo/slides          -> {session_id, slide_deck|null}
 *   - DELETE /api/sessions/tour-demo               -> recorded; afterwards GET is 404
 * Messages carry the role / message_type / metadata {tour_stage, node} of
 * Task 2's stage table, built from the real fixture JSON.
 *
 * Sabotage (verified, see task-6-test-report.md): deleting the `focusViewer`
 * hook from the "Review Feedback" step turns test 1 red at "Review Feedback".
 */
import { readFileSync } from 'node:fs';
import type { Page, Request } from '@playwright/test';
import { test, expect } from '../fixtures/base-test';
import { setupMocks } from '../helpers/setup-mocks';
import { apiPath, apiPathMatching } from '../helpers/api-route';
import { mockDefaultAgentConfig } from '../fixtures/mocks';

// ── fixture ───────────────────────────────────────────────────────────────────

interface FixtureSlide { index: number; slide_id: string; html: string; scripts: string }
interface FixtureFinding { criterion: string; category: string; objective: boolean; message: string }
interface TourFixture {
  title: string;
  css: string;
  external_scripts: string[];
  scripts: string;
  slides: FixtureSlide[];
  chat_prompt: string;
  deck_spec: { slides: Array<Record<string, unknown>> } & Record<string, unknown>;
  stages: {
    plan: { architect_reply: string };
    build: {
      foreman_line: string;
      review_lines: string[];
      findings: Record<string, FixtureFinding[]>;
      verification: { rating: string; score: number; explanation: string };
    };
    review: { advisory: string };
    edit: {
      user_prompt: string;
      architect_reply: string;
      position: number;
      slide: FixtureSlide;
      content_brief: string;
      review_line: string;
    };
  };
}

const fixture: TourFixture = JSON.parse(
  readFileSync(new URL('../../../src/api/fixtures/tour_demo_deck.json', import.meta.url), 'utf8'),
);
const fx = fixture.stages;

const SID = 'tour-demo';
const STAGES = ['prompt', 'plan', 'build', 'review', 'edit'] as const;
type Stage = (typeof STAGES)[number];

// Titles are read from tourSteps.ts SOURCE: importing the module would pull in
// services/api.ts, whose import.meta.env does not exist under Node.  Each step
// literal has exactly one `title: '...'` (single-quoted, \' escapes).
const TOUR_STEPS_SRC = readFileSync(
  new URL('../../src/components/Tour/tourSteps.ts', import.meta.url),
  'utf8',
);
const TITLES = [...TOUR_STEPS_SRC.matchAll(/^\s*title: '((?:[^'\\]|\\.)*)',$/gm)].map((m) =>
  m[1].replace(/\\'/g, "'"),
);

// Opaque stand-ins for compute_slide_hash(html): the frontend never recomputes
// the hash, it only keys verification/findings by it.  The edited slide gets a
// NEW hash, exactly as the real backend's would.
const hashFor = (html: string) => {
  const i = fixture.slides.findIndex((s) => s.html === html);
  return i >= 0 ? `tourhash${i}` : 'tourhash1edited';
};

const FINDING_POSITION = 2;
const findingId = (hash: string, ordinal: number, criterion: string) =>
  `${criterion}:${hash}:${ordinal}`; // make_finding_id format
const SURFACED_FINDING_ID = findingId(
  `tourhash${FINDING_POSITION}`,
  0,
  fx.build.findings[String(FINDING_POSITION)][0].criterion,
);

// A phrase that exists only in the edit stage's rewritten slide 2.
const EDITED_SLIDE_MARKER = 'spotting disease on scans sooner';
if (!fx.edit.slide.html.includes(EDITED_SLIDE_MARKER) || fixture.slides.some((s) => s.html.includes(EDITED_SLIDE_MARKER))) {
  throw new Error('EDITED_SLIDE_MARKER must appear only in stages.edit.slide.html');
}

// ── stateful staged backend ───────────────────────────────────────────────────

interface DemoBackend {
  applied: Set<Stage>;
  stagePosts: string[];
  stageResults: Array<{ stage: string; status: number; applied?: boolean }>;
  deletes: number;
  createPosts: number;
  forbidden: string[];
}

type Msg = {
  id: number;
  role: 'user' | 'assistant';
  content: string;
  message_type: string;
  created_at: string;
  metadata: { tour_stage: Stage; node: string };
};

function buildMessages(applied: Set<Stage>): Msg[] {
  const rows: Array<Omit<Msg, 'id' | 'created_at'>> = [];
  const say = (stage: Stage, node: string, content: string, message_type: string, role: Msg['role'] = 'assistant') =>
    rows.push({ role, content, message_type, metadata: { tour_stage: stage, node } });

  if (applied.has('prompt')) say('prompt', 'user', fixture.chat_prompt, 'chat', 'user');
  if (applied.has('plan')) say('plan', 'architect', fx.plan.architect_reply, 'llm_response');
  if (applied.has('build')) {
    say('build', 'foreman', fx.build.foreman_line, 'info');
    for (const line of fx.build.review_lines) say('build', 'build_reviewer', line, 'info');
  }
  if (applied.has('review')) say('review', 'deck_reviewer', fx.review.advisory, 'info');
  if (applied.has('edit')) {
    say('edit', 'user', fx.edit.user_prompt, 'chat', 'user');
    say('edit', 'architect', fx.edit.architect_reply, 'llm_response');
    say('edit', 'build_reviewer', fx.edit.review_line, 'info');
  }
  return rows.map((r, i) => ({ ...r, id: i + 1, created_at: `2026-10-13T10:00:${String(i).padStart(2, '0')}` }));
}

function buildDeck(applied: Set<Stage>) {
  if (!applied.has('build')) return null;
  const edited = applied.has('edit');
  const slides = fixture.slides.map((s) => ({ ...s }));
  const spec = JSON.parse(JSON.stringify(fixture.deck_spec));
  if (edited) {
    slides[fx.edit.position] = { ...fx.edit.slide };
    spec.slides[fx.edit.position].content_brief = fx.edit.content_brief;
  }
  const judge = {
    score: fx.build.verification.score,
    rating: fx.build.verification.rating,
    explanation: fx.build.verification.explanation,
    issues: [],
    duration_ms: 0,
    error: false,
  };
  const flatFindings: Array<Record<string, unknown>> = [];
  const outSlides = slides.map((s, position) => {
    const hash = hashFor(s.html);
    const findings = (fx.build.findings[String(position)] ?? []).map((f, i) => ({
      id: findingId(hash, i, f.criterion),
      slide_index: position,
      category: f.category,
      criterion: f.criterion,
      message: f.message,
      objective: f.objective,
      status: 'open',
      seen: false,
    }));
    for (const f of findings) {
      flatFindings.push({
        id: f.id, slideIndex: f.slide_index, category: f.category, criterion: f.criterion,
        message: f.message, objective: f.objective, status: f.status, seen: f.seen,
      });
    }
    return {
      index: position,
      html: s.html,
      slide_id: s.slide_id,
      scripts: s.scripts ?? '',
      created_by: 'dev@local.dev',
      created_at: '2026-10-13T10:00:00Z',
      modified_by: 'dev@local.dev',
      modified_at: '2026-10-13T10:00:00Z',
      content_hash: hash,
      verification: {
        ...judge,
        tellr_review: { verdict: findings.length ? 'surfaced' : 'clean', findings },
      },
    };
  });
  return {
    title: fixture.title,
    slide_count: outSlides.length,
    css: fixture.css,
    external_scripts: fixture.external_scripts,
    head_meta: {},
    scripts: fixture.scripts,
    slides: outSlides,
    created_by: 'dev@local.dev',
    created_at: '2026-10-13T10:00:00Z',
    modified_by: 'dev@local.dev',
    modified_at: '2026-10-13T10:00:00Z',
    version: edited ? 4 : 2,
    deck_spec: spec,
    findings: flatFindings,
  };
}

const json = (body: unknown, status = 200) => ({
  status,
  contentType: 'application/json',
  body: JSON.stringify(body),
});

async function mockStagedDemo(page: Page): Promise<DemoBackend> {
  const be: DemoBackend = {
    applied: new Set(),
    stagePosts: [],
    stageResults: [],
    deletes: 0,
    createPosts: 0,
    forbidden: [],
  };
  let deleted = false;

  // No LLM: any verification or chat POST is a test failure (asserted at the end).
  page.on('request', (req: Request) => {
    if (req.method() !== 'POST') return;
    const { pathname } = new URL(req.url());
    if (pathname.startsWith('/api/verification') || pathname.startsWith('/api/chat')) {
      be.forbidden.push(`${req.method()} ${pathname}`);
    }
  });

  await page.route(apiPath('/api/tour/demo-deck'), (route) => {
    if (route.request().method() !== 'POST') return route.fallback();
    be.createPosts += 1;
    be.applied = new Set(['prompt']);
    deleted = false;
    return route.fulfill(json({ session_id: SID, title: fixture.title }));
  });

  await page.route(apiPathMatching(/^\/api\/tour\/demo-deck\/[^/]+\/stages\/[^/]+$/), (route) => {
    if (route.request().method() !== 'POST') return route.fallback();
    const parts = new URL(route.request().url()).pathname.split('/');
    const stage = parts[parts.length - 1] as Stage;
    be.stagePosts.push(stage);
    if (!STAGES.includes(stage) || stage === 'prompt') {
      be.stageResults.push({ stage, status: 404 });
      return route.fulfill(json({ detail: 'Unknown tour stage' }, 404));
    }
    const slideCount = () => buildDeck(be.applied)?.slides.length ?? 0;
    if (be.applied.has(stage)) {
      be.stageResults.push({ stage, status: 200, applied: false });
      return route.fulfill(json({ session_id: SID, stage, applied: false, slide_count: slideCount() }));
    }
    const previous = STAGES[STAGES.indexOf(stage) - 1];
    if (!be.applied.has(previous)) {
      be.stageResults.push({ stage, status: 409 });
      return route.fulfill(json({ detail: `Stage '${stage}' requires '${previous}' to run first` }, 409));
    }
    be.applied.add(stage);
    be.stageResults.push({ stage, status: 200, applied: true });
    return route.fulfill(json({ session_id: SID, stage, applied: true, slide_count: slideCount() }));
  });

  const sessionDict = () => {
    const deck = buildDeck(be.applied);
    const messages = buildMessages(be.applied);
    return {
      id: 4242,
      session_id: SID,
      user_id: null,
      created_by: 'dev@local.dev',
      title: fixture.title,
      created_at: '2026-10-13T10:00:00',
      last_activity: '2026-10-13T10:00:30',
      genie_conversation_id: null,
      experiment_id: null,
      experiment_url: null,
      agent_config: null,
      message_count: messages.length,
      has_slide_deck: deck !== null,
      google_slides_url: null,
      google_slides_presentation_id: null,
      is_contributor_session: false,
      parent_session_id: null,
      parent_session_internal_id: null,
      global_permission: null,
      graph_version: 1,
      active_graph_version: 1,
      is_older_than_active: false,
      messages,
      slide_deck: deck,
      my_permission: 'CAN_MANAGE',
    };
  };

  await page.route(apiPath(`/api/sessions/${SID}`), (route) => {
    const method = route.request().method();
    if (method === 'DELETE') {
      be.deletes += 1;
      deleted = true;
      return route.fulfill(json({ status: 'deleted', session_id: SID }));
    }
    if (method !== 'GET') return route.fallback();
    if (deleted || be.applied.size === 0) {
      return route.fulfill(json({ detail: `Session not found: ${SID}` }, 404));
    }
    return route.fulfill(json(sessionDict()));
  });

  await page.route(apiPath(`/api/sessions/${SID}/slides`), (route) => {
    if (deleted || be.applied.size === 0) {
      return route.fulfill(json({ detail: `Session not found: ${SID}` }, 404));
    }
    return route.fulfill(json({ session_id: SID, slide_deck: buildDeck(be.applied) }));
  });

  await page.route(apiPath(`/api/sessions/${SID}/contributors`), (route) =>
    route.fulfill(json({ contributors: [] })));
  await page.route(apiPath(`/api/sessions/${SID}/versions`), (route) =>
    route.fulfill(json({ versions: [], current_version: null })));
  await page.route(apiPath(`/api/sessions/${SID}/agent-config`), (route) =>
    route.fulfill(json(mockDefaultAgentConfig)));
  await page.route(apiPath(`/api/sessions/${SID}/lock`), (route) => {
    const method = route.request().method();
    if (method === 'POST') return route.fulfill(json({ acquired: true, locked_by: null }));
    if (method === 'GET') return route.fulfill(json({ locked: false, locked_by: null }));
    return route.fulfill(json({ released: true }));
  });
  await page.route(apiPath(`/api/sessions/${SID}/lock/heartbeat`), (route) =>
    route.fulfill(json({ renewed: true })));

  return be;
}

// ── tour driving helpers ──────────────────────────────────────────────────────

const tooltip = (page: Page) => page.locator('.react-joyride__tooltip');

async function expectStep(page: Page, title: string) {
  await expect(
    tooltip(page).getByRole('heading', { name: title, exact: true }),
    `tour step "${title}" did not show (target missing at step time, or a step was skipped)`,
  ).toBeVisible({ timeout: 10_000 });
}

async function clickNext(page: Page) {
  await tooltip(page).getByTestId('button-primary').click();
}

async function clickBack(page: Page) {
  await tooltip(page).getByTestId('button-back').click();
}

async function startTour(page: Page) {
  await page.goto('/');
  const take = page.getByRole('button', { name: 'Take the Tour' });
  await expect(take).toBeVisible({ timeout: 10_000 });
  await take.click();
  await expectStep(page, TITLES[0]);
}

/** Walk from the current step (index `from`, already showing) up to step `to`
 *  (showing, not clicked). Calls `at(title)` at every step, before Next. */
async function walk(
  page: Page,
  from: number,
  to: number,
  at?: (title: string) => Promise<void>,
) {
  for (let i = from; i <= to; i++) {
    await expectStep(page, TITLES[i]);
    if (at) await at(TITLES[i]);
    if (i < to) await clickNext(page);
  }
}

const idx = (title: string) => {
  const i = TITLES.indexOf(title);
  if (i < 0) throw new Error(`no tour step titled ${title}`);
  return i;
};

const chat = (page: Page) => page.locator('[data-tour="chat-panel"]');

/** Exact-text count of a chat line (Message.tsx renders plain text). */
const chatLine = (page: Page, text: string) => chat(page).getByText(text, { exact: true });

// The suite-wide storageState marks the tour completed; this file needs it fresh.
test.use({ storageState: { cookies: [], origins: [] } });

test.describe('app tour — staged graph demo', () => {
  test.describe.configure({ timeout: 180_000 });

  let be: DemoBackend;

  test.beforeEach(async ({ page }) => {
    await setupMocks(page);
    be = await mockStagedDemo(page);
  });

  test('walks all 35 steps; every target mounts; demo matches the graph turn', async ({ page }) => {
    expect(TITLES).toHaveLength(35);
    // Start with the drawer CLOSED so "Review Feedback" must open it itself.
    // Only seeded when absent so the app's own writes survive any reload.
    await page.addInitScript(() => {
      if (localStorage.getItem('tellr-viewer-view-state') === null) {
        localStorage.setItem(
          'tellr-viewer-view-state',
          JSON.stringify({ drawerOpen: false, drawerHeight: 180, activeTab: 'feedback' }),
        );
      }
    });

    await startTour(page);

    const seen: string[] = [];
    await walk(page, 0, TITLES.length - 1, async (title) => {
      seen.push(title);
      switch (title) {
        case 'Your Request':
          await expect(chatLine(page, fixture.chat_prompt)).toBeVisible();
          await expect(chatLine(page, fx.plan.architect_reply)).toHaveCount(0);
          break;
        case 'The Architect Plans':
          await expect(chatLine(page, fx.plan.architect_reply)).toBeVisible();
          expect(be.stagePosts).toEqual(['plan']);
          break;
        case 'Slides Arrive One by One':
          await expect(page.getByTestId('ribbon-thumb-2')).toBeVisible();
          await expect(chatLine(page, fx.build.foreman_line)).toBeVisible();
          for (const line of fx.build.review_lines) {
            await expect(chatLine(page, line)).toBeVisible();
          }
          break;
        case 'Review Feedback':
          await expect(page.getByTestId('ribbon-thumb-2')).toHaveAttribute('data-current', 'true');
          await expect(page.getByTestId(`finding-${SURFACED_FINDING_ID}`)).toBeVisible();
          break;
        case 'Whole-Deck Review':
          await expect(chatLine(page, fx.review.advisory)).toBeVisible();
          break;
        case 'The Deck Spec':
          await expect(page.getByTestId('spec-view')).toBeVisible();
          break;
        case 'Edit by Asking':
          await expect(page.getByTestId('spec-view')).toBeHidden();
          await expect(chatLine(page, fx.edit.user_prompt)).toBeVisible();
          await expect(chatLine(page, fx.edit.architect_reply)).toBeVisible();
          await expect(page.getByTestId('ribbon-thumb-1')).toHaveAttribute('data-current', 'true');
          // The rebuilt slide 2 (edit stage's HTML) is what the stage shows.
          await expect(page.getByTestId('slide-stage').locator('iframe')).toHaveAttribute(
            'srcdoc',
            new RegExp(EDITED_SLIDE_MARKER),
          );
          break;
      }
    });

    expect(seen).toEqual(TITLES);
    const last = tooltip(page).getByTestId('button-primary');
    await expect(last).toContainText('Get Started');

    // Each stage ran once, in order; nothing was rejected.
    expect(be.createPosts).toBe(1);
    expect(be.stagePosts).toEqual(['plan', 'build', 'review', 'edit']);
    expect(be.stageResults.every((r) => r.status === 200 && r.applied)).toBe(true);
    expect(be.deletes).toBe(0);

    await last.click();
    await expect(tooltip(page)).toHaveCount(0);
    await expect.poll(() => be.deletes).toBe(1);
    await page.waitForTimeout(500);
    expect(be.deletes).toBe(1);
    expect(be.forbidden).toEqual([]);
  });

  test('Back re-entry does not re-run stages or duplicate chat lines', async ({ page }) => {
    await startTour(page);
    const target = idx('Every Slide Is Reviewed');
    await walk(page, 0, target);
    await expect(chatLine(page, fx.build.foreman_line)).toHaveCount(1);

    await clickBack(page);
    await expectStep(page, TITLES[target - 1]); // Slides Arrive One by One (build hook re-entered)
    await clickBack(page);
    await expectStep(page, TITLES[target - 2]); // The Architect Plans (plan hook re-entered)
    await clickNext(page);
    await expectStep(page, TITLES[target - 1]);
    await clickNext(page);
    await expectStep(page, TITLES[target]);

    // A stage the client already applied is never re-requested; nothing was rejected.
    expect(be.stagePosts.filter((s) => s === 'plan')).toHaveLength(1);
    expect(be.stagePosts.filter((s) => s === 'build')).toHaveLength(1);
    expect(be.stagePosts).toEqual(['plan', 'build']);
    expect(be.stageResults.every((r) => r.status === 200)).toBe(true);

    await expect(chatLine(page, fx.build.foreman_line)).toHaveCount(1);
    await expect(chatLine(page, fx.plan.architect_reply)).toHaveCount(1);
    for (const line of new Set(fx.build.review_lines)) {
      await expect(chatLine(page, line)).toHaveCount(fx.build.review_lines.filter((l) => l === line).length);
    }
    expect(be.forbidden).toEqual([]);
  });

  test('Skip Tour mid-demo deletes the demo session and leaves an empty workspace', async ({ page }) => {
    await startTour(page);
    await walk(page, 0, idx('Review Feedback'));
    expect(be.stagePosts).toEqual(['plan', 'build']);
    expect(be.deletes).toBe(0);

    await tooltip(page).getByTestId('button-skip').click();
    await expect(tooltip(page)).toHaveCount(0);
    await expect.poll(() => be.deletes).toBe(1);
    await expect(page.getByTestId('slide-viewer-empty')).toBeVisible();
    await expect(page).not.toHaveURL(new RegExp(`/sessions/${SID}`));
    await page.waitForTimeout(500);
    expect(be.deletes).toBe(1);
    expect(be.forbidden).toEqual([]);
  });

  test('drawer already open from earlier use: Edit by Asking still shows the slide stage', async ({ page }) => {
    await page.addInitScript(() => {
      if (localStorage.getItem('tellr-viewer-view-state') === null) {
        localStorage.setItem(
          'tellr-viewer-view-state',
          JSON.stringify({ drawerOpen: true, drawerHeight: 200, activeTab: 'feedback' }),
        );
      }
    });
    await startTour(page);
    await walk(page, 0, idx('Edit by Asking'));
    await expect(page.getByTestId('spec-view')).toBeHidden();
    await expect(page.getByTestId('slide-stage')).toBeVisible();
    await expect(page.getByTestId('ribbon-thumb-1')).toHaveAttribute('data-current', 'true');
    expect(be.forbidden).toEqual([]);
  });

  test('user already on Spec before "The Deck Spec": spec shows, then Edit by Asking returns to slides', async ({ page }) => {
    await startTour(page);
    // Walk to the step before the spec step, then switch to Spec ourselves —
    // the bridge must SET the view, not toggle it.
    const before = idx('The Deck Spec') - 1;
    await walk(page, 0, before);
    // The Joyride overlay intercepts pointer events outside the spotlight (and
    // spotlightClicks is off), so a mouse click cannot reach the toggle while the
    // tour runs.  Dispatching the DOM click runs the button's real onClick.
    await page.getByTestId('view-toggle-spec').dispatchEvent('click');
    await expect(page.getByTestId('view-toggle-spec')).toHaveAttribute('aria-pressed', 'true');
    await expect(page.getByTestId('spec-view')).toBeVisible();

    await clickNext(page);
    await expectStep(page, 'The Deck Spec');
    await expect(page.getByTestId('spec-view')).toBeVisible();

    await clickNext(page);
    await expectStep(page, 'Edit by Asking');
    await expect(page.getByTestId('spec-view')).toBeHidden();
    await expect(page.getByTestId('slide-stage')).toBeVisible();
    expect(be.forbidden).toEqual([]);
  });
});
