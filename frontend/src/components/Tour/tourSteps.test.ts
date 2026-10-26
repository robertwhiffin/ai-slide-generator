/**
 * Contract for the tour's step list. Targets are checked against NON-TEST source,
 * because a Joyride step whose target never mounts is silently skipped as
 * `target_not_found`, and the tour then quietly drops a feature.
 *
 * Source corpus: Vite `?raw` glob (repo idiom, PLAN-CORRECTIONS C2), excluding
 * test files and the Tour directory itself (so the tour cannot "find" its own
 * selector strings).
 *
 * Note on hook stringification: under vitest, `() => runStage('plan')` stringifies
 * as `() => (0,__vite_ssr_import_0__.runStage)("plan")`, so the string checks below
 * allow an optional `)` and either quote style. The behavioural walk at the bottom
 * pins the same contract without relying on source text.
 */
import { describe, it, expect, beforeEach, afterEach } from 'vitest';
import type { Step } from 'react-joyride';

const apiMock = vi.hoisted(() => ({
  createTourDemoDeck: vi.fn(),
  runTourDemoStage: vi.fn(),
  deleteSession: vi.fn(),
}));
vi.mock('../../services/api', () => ({ api: apiMock }));

import { TOUR_STEPS, DEMO_DECK_SLIDE_COUNT } from './tourSteps';
import { _resetDemoForTests } from './tourDemo';

const modules = import.meta.glob('/src/**/*.{ts,tsx}', {
  query: '?raw',
  import: 'default',
  eager: true,
}) as Record<string, string>;
const nonTestSources = Object.entries(modules).filter(
  ([p]) => !p.includes('.test.') && !p.includes('/components/Tour/'),
);
const corpus = nonTestSources.map(([, src]) => src).join('\n');

const sidebarSource = modules['/src/components/Layout/app-sidebar.tsx'] ?? '';
const secondaryBlock = sidebarSource.match(/const navSecondaryItems = \[([\s\S]*?)\n\]/)?.[1] ?? '';
/** viewIds of the items NavSecondary renders as `data-tour={`nav-${item.viewId}`}`. */
const navViewIds = [...secondaryBlock.matchAll(/viewId:\s*"([a-z_]+)"/g)].map(m => m[1]);

const titles = TOUR_STEPS.map(s => s.title as string);
const text = TOUR_STEPS.map(s => `${s.title} ${s.content}`).join('\n');

function selectorIsRendered(target: string): boolean {
  const m = target.match(/^\[data-(tour|testid)="([^"]+)"\]$/);
  if (!m) return false;
  const [, kind, value] = m;
  if (kind === 'tour' && value.startsWith('nav-')) return /data-tour=\{`nav-\$\{item\.viewId\}`\}/.test(corpus);
  return corpus.includes(`data-${kind}="${value}"`);
}

/** [target, title, placement, content] — the brief's table, in table order. */
const TABLE: Array<[string, string, string, string]> = [
  ["[data-tour=\"sidebar\"]", "The App at a Glance", "right", "The sidebar on the left is for navigation: new decks, your deck history and configuration. The workspace on the right is where you chat with the AI and see your slides. Let's walk through both."], // 1
  ["[data-tour=\"new-deck\"]", "Navigation", "right", "\"New Deck\" starts a fresh deck with a new conversation. \"View All Decks\" lists every deck you have created or that has been shared with you."], // 2
  ["[data-tour=\"deck-history\"]", "Recent Decks", "right", "Your recent decks are listed here. Click one to pick up where you left off, with its conversation and slides intact."], // 3
  ["[data-tour=\"configure-section\"]", "Configuration", "right", "These pages control what the AI works with and how your decks look. Let's visit each one."], // 4
  ["[data-tour=\"page-profiles\"]", "Agent Profiles", "center", "A profile saves a combination of tools, design system or slide style, and deck prompt, so you can switch set-ups in one click, for example \"Sales Deck\" or \"Technical Review\"."], // 5
  ["[data-tour=\"page-deck-prompts\"]", "Deck Prompts", "center", "Deck prompts are reusable instructions for how a deck should be structured, such as a required narrative or a standard section order."], // 6
  ["[data-tour=\"page-design-systems\"]", "Design Systems", "center", "A design system packages your brand: colours, fonts, logos and slide templates. Decks built with one come out on-brand. When a deck uses a design system, it takes the place of any slide style."], // 7
  ["[data-tour=\"page-slide-styles\"]", "Slide Styles", "center", "Slide styles are lighter-weight visual themes. A slide style is used only when no design system is selected."], // 8
  ["[data-tour=\"page-images\"]", "Image Library", "center", "Upload logos, diagrams and photos here so the AI can place them on your slides."], // 9
  ["[data-tour=\"page-settings\"]", "Settings", "center", "Connect or disconnect your Google account here for Google Slides export. Admins upload the app-wide OAuth client credentials on the Admin page."], // 10
  ["[data-tour=\"chat-panel\"]", "The AI Workspace", "right", "You chat here and your deck appears on the right. Behind the chat is a team of AI agents: one plans the deck, others build the slides in parallel, and reviewers check each slide and the deck as a whole."], // 11
  ["[data-tour=\"agent-config\"]", "Agent Config Bar", "bottom", "This bar sets what the agents can use for this deck: tools, look and instructions. Your choices stay in place for every message in this deck until you change them."], // 12
  ["[data-tour=\"agent-tools\"]", "Tools", "bottom", "Tools give the agents access to your data and documents: Genie agents, vector search indexes, MCP servers and model endpoints. Each tool appears as a chip. Click it to edit, or click the X to remove it."], // 13
  ["[data-tour=\"agent-design-system-selector\"]", "Design System", "bottom", "Pick a design system for this deck. If it has templates, a Template picker appears next to it."], // 14
  ["[data-tour=\"agent-style-selector\"]", "Slide Style", "bottom", "Pick a slide style if you are not using a design system. Leave it as \"None\" for the default look."], // 15
  ["[data-tour=\"agent-prompt-selector\"]", "Deck Prompt", "bottom", "Choose a deck prompt to shape the deck's structure, for example a fixed narrative or a set number of slides."], // 16
  ["[data-tour=\"agent-profile-actions\"]", "Save & Load Profiles", "bottom", "Save this combination as a profile, or load one to restore a set-up instantly."], // 17
  ["[data-tour=\"chat-panel\"]", "Let's Try It", "right", "Let's watch the agents build a deck. We'll send an example request for you."], // 18
  ["[data-tour=\"chat-panel\"]", "Your Request", "right", "We asked for \"3 slides about the benefits of AI in modern healthcare, with a title slide, key advantages, and future outlook.\" Plain language is all you need."], // 19
  ["[data-tour=\"chat-panel\"]", "The Architect Plans", "right", "The architect agent replies first with its plan: who the deck is for, the argument it will make, and what each slide must do. If your request is unclear, it asks you a question instead of guessing."], // 20
  ["[data-tour=\"slide-viewer\"]", "Slides Arrive One by One", "left", "Builder agents now write the slides in parallel, and each one appears here as soon as it is ready, so you can start reading before the whole deck is done."], // 21
  ["[data-testid=\"thumbnail-ribbon\"]", "Every Slide Is Reviewed", "left", "A reviewer agent checks every slide as it lands. Mechanical problems such as overflowing text are fixed automatically before you see the slide. Anything that needs your judgement is flagged with a dot on its thumbnail, and the details are in the feedback drawer."], // 22
  ["[data-testid=\"thumbnail-ribbon\"]", "Browse Your Slides", "left", "Click a thumbnail to jump to that slide, or drag it to reorder the deck. A dot on a thumbnail means that slide has review feedback you haven't read yet."], // 23
  ["[data-testid=\"feedback-drawer\"]", "Review Feedback", "top", "The feedback drawer lists the reviewer's findings for the current slide. Apply asks the agents to make the change, Dismiss hides the finding, and Discuss moves it into the chat so you can talk it through first."], // 24
  ["[data-testid=\"stage-verification-badge\"]", "Data Check", "bottom", "This badge checks the slide's facts against the data your tools returned, shown as green, amber or red. This demo deck uses no data tools, so there is nothing to check yet."], // 25
  ["[data-tour=\"chat-panel\"]", "Whole-Deck Review", "right", "When every slide is in, a deck reviewer reads the deck as a whole for gaps in the argument, repeated points and a missing conclusion. Its verdict appears in the chat."], // 26
  ["[data-testid=\"spec-view\"]", "The Deck Spec", "left", "The Spec shows the plan the agents work from: audience, purpose, argument, narrative arc and a brief for every slide. To change it, ask in the chat, for example \"make this for a board audience\". The agents then update the spec and the slides it affects."], // 27
  ["[data-tour=\"slide-viewer\"]", "Edit by Asking", "left", "To change a slide, just ask. We sent \"Make slide 2 more concise\". The architect works out which slide you mean, and only that slide is rebuilt and re-reviewed. The rest of the deck is untouched."], // 28
  ["[data-tour=\"slide-viewer\"]", "Hands-On Changes", "left", "For direct changes, the toolbar above the slide lets you edit its HTML, delete it, or use Optimize layout to tidy spacing and text flow without changing the content."], // 29
  ["[data-testid=\"graph-version-status\"]", "Pinned Agent Version", "bottom", "Each deck stays on the version of the AI agents it started with, so updates an admin publishes never change a deck halfway through. This demo deck shows its version here. If a newer version exists, \"Start latest\" opens a new deck on it, and this deck is left as it is."], // 30
  ["[data-tour=\"header-title\"]", "Deck Title & Save Points", "bottom", "Click the title to rename your deck. The save point menu lets you browse earlier versions and revert to any of them."], // 31
  ["[data-tour=\"header-actions\"]", "Export & Share", "bottom", "When your deck is ready:\n• Export: PPTX, PDF, HTML or Google Slides\n• Copy Link: a read-only view link\n• Share: add viewers or editors\n• Present: full-screen in the browser"], // 32
  ["[data-tour=\"feedback-button\"]", "Feedback", "top", "Spotted a bug or have an idea? Send it to the team from here at any time."], // 33
  ["[data-tour=\"page-help\"]", "Help & Documentation", "center", "Guides for every feature live here."], // 34
  ["[data-tour=\"page-help\"]", "You're All Set", "center", "That's the tour. The example deck is removed when you finish.\n\nTo make your own, click \"New Deck\" and describe what you want in the chat.\n\nYou can replay this tour any time from \"App Tour\" at the bottom of the sidebar."], // 35
];

describe('source corpus sanity', () => {
  it('the ?raw glob reads real source and excludes tests and the Tour directory', () => {
    const paths = nonTestSources.map(([p]) => p);
    expect(paths).toContain('/src/components/Layout/AppLayout.tsx');
    expect(paths.some(p => p.includes('.test.'))).toBe(false);
    expect(paths.some(p => p.includes('/components/Tour/'))).toBe(false);
  });

  it('parses the sidebar nav viewIds that NavSecondary renders as nav-* targets', () => {
    expect(navViewIds).toEqual(expect.arrayContaining(['settings', 'profiles', 'deck_prompts', 'design_systems', 'slide_styles', 'images', 'help']));
    expect(corpus).toMatch(/data-tour=\{`nav-\$\{item\.viewId\}`\}/);
  });
});

describe('TOUR_STEPS', () => {
  it('has exactly the 35 steps of the table, with unique titles', () => {
    expect(TOUR_STEPS).toHaveLength(35);
    expect(new Set(titles).size).toBe(titles.length);
  });

  it('matches the table row for row: target, title, placement and content', () => {
    const actual = TOUR_STEPS.map(s => [s.target, s.title, s.placement, s.content]);
    expect(actual).toEqual(TABLE);
  });

  it('exports the demo deck slide count', () => {
    expect(DEMO_DECK_SLIDE_COUNT).toBe(3);
  });

  it('every target is a data-tour/data-testid selector rendered by non-test source', () => {
    const missing = TOUR_STEPS.map(s => s.target as string).filter(t => !selectorIsRendered(t));
    expect(missing).toEqual([]);
  });

  it('teaches the graph flow in order', () => {
    const order = ['Your Request', 'The Architect Plans', 'Slides Arrive One by One', 'Every Slide Is Reviewed',
      'Review Feedback', 'Whole-Deck Review', 'The Deck Spec', 'Edit by Asking'];
    const idx = order.map(t => titles.indexOf(t));
    expect(idx.every(i => i >= 0)).toBe(true);
    expect([...idx].sort((a, b) => a - b)).toEqual(idx);
  });

  it('covers the features the old tour missed', () => {
    for (const t of ['Design Systems', 'Design System', 'Pinned Agent Version', 'Data Check', 'Review Feedback', 'The Deck Spec']) {
      expect(titles).toContain(t);
    }
  });

  it('runs each demo stage exactly once, in stage order', () => {
    const hooks = TOUR_STEPS.map(s => String(s.before ?? ''));
    const callsStage = (h: string, stage: string) => new RegExp(`runStage\\)?\\(\\s*['"]${stage}['"]`).test(h);
    const stageAt = (stage: string) => hooks.findIndex(h => callsStage(h, stage));
    const at = ['plan', 'build', 'review', 'edit'].map(stageAt);
    expect(at.every(i => i >= 0)).toBe(true);
    expect([...at].sort((a, b) => a - b)).toEqual(at);
    expect(hooks.filter(h => /runStage\)?\(/.test(h))).toHaveLength(4);
    const startAt = hooks.findIndex(h => h.includes('startDemo'));
    expect(startAt).toBeGreaterThanOrEqual(0);
    expect(startAt).toBeLessThan(at[0]);
  });

  it('no step makes a claim about retired behaviour', () => {
    expect(text).not.toMatch(/select multiple|selection ribbon|click (directly )?on any slide to edit|duplicate/i);
    expect(text).not.toMatch(/generates a full deck in response/i);
  });

  it('teaches editing by asking in chat', () => {
    const edit = TOUR_STEPS.find(s => s.title === 'Edit by Asking');
    expect(String(edit?.content)).toMatch(/make slide 2 more concise/i);
  });

  it('copy stays short and plain', () => {
    for (const s of TOUR_STEPS) {
      expect(String(s.content).split(/\s+/).length, String(s.title)).toBeLessThanOrEqual(60);
      expect(String(s.content)).not.toMatch(/\*\*/);
    }
  });

  it('every step skips the beacon', () => {
    expect(TOUR_STEPS.every(s => s.skipBeacon === true)).toBe(true);
  });
});

/**
 * Behavioural walk: run every `before` hook in tour order against a jsdom stand-in
 * for the sidebar nav and the agent-config toggle, and record what each hook did
 * (nav clicks, window bridge events, API calls). Pins that each hook does exactly
 * what the table's `before` column says, without depending on source text.
 */
describe('TOUR_STEPS before hooks (behaviour)', () => {
  const BRIDGE_EVENTS = ['tour:navigate-main', 'tour:load-demo-deck', 'tour:refresh-session', 'tour:show-view', 'tour:viewer'];
  let log: string[];
  const onEvent = (e: Event) => {
    const detail = (e as CustomEvent).detail;
    log.push(detail === undefined || detail === null ? e.type : `${e.type} ${JSON.stringify(detail)}`);
  };

  beforeEach(() => {
    vi.useFakeTimers();
    _resetDemoForTests();
    log = [];
    apiMock.createTourDemoDeck.mockReset().mockImplementation(async () => {
      log.push('api:createTourDemoDeck');
      return { session_id: 'demo-1' };
    });
    apiMock.runTourDemoStage.mockReset().mockImplementation(async (sid: string, stage: string) => {
      log.push(`api:runTourDemoStage ${sid} ${stage}`);
      return {};
    });
    apiMock.deleteSession.mockReset().mockResolvedValue(undefined);

    document.body.innerHTML =
      navViewIds.map(id => `<li data-tour="nav-${id}"><button type="button">${id}</button></li>`).join('') +
      '<div data-testid="agent-config-bar"><button type="button" data-tour="agent-config-toggle">toggle</button></div>';
    document.querySelectorAll<HTMLElement>('[data-tour]').forEach(el => {
      const id = el.getAttribute('data-tour')!;
      const btn = el.tagName === 'BUTTON' ? el : el.querySelector('button')!;
      btn.addEventListener('click', () => log.push(`click:${id}`));
    });
    BRIDGE_EVENTS.forEach(t => window.addEventListener(t, onEvent));
  });

  afterEach(() => {
    BRIDGE_EVENTS.forEach(t => window.removeEventListener(t, onEvent));
    document.body.innerHTML = '';
    _resetDemoForTests();
    vi.useRealTimers();
  });

  async function runHook(step: Step): Promise<string[]> {
    log = [];
    const p = Promise.resolve((step.before as unknown as () => unknown)());
    await vi.runAllTimersAsync();
    await p;
    return log;
  }

  /** 1-indexed step number -> what its `before` hook must do. Every other step has no hook. */
  const EXPECTED: Record<number, string[]> = {
    5: ['click:nav-profiles'],
    6: ['click:nav-deck_prompts'],
    7: ['click:nav-design_systems'],
    8: ['click:nav-slide_styles'],
    9: ['click:nav-images'],
    10: ['click:nav-settings'],
    11: ['tour:navigate-main'],
    12: ['click:agent-config-toggle'],
    19: ['api:createTourDemoDeck', 'tour:load-demo-deck {"sessionId":"demo-1"}'],
    20: ['api:runTourDemoStage demo-1 plan', 'tour:refresh-session {"sessionId":"demo-1"}'],
    21: ['api:runTourDemoStage demo-1 build', 'tour:refresh-session {"sessionId":"demo-1"}'],
    24: ['tour:viewer {"index":2,"drawerOpen":true,"tab":"feedback"}'],
    26: ['api:runTourDemoStage demo-1 review', 'tour:refresh-session {"sessionId":"demo-1"}'],
    27: ['tour:show-view {"view":"spec"}'],
    28: [
      'tour:show-view {"view":"slides"}',
      'api:runTourDemoStage demo-1 edit',
      'tour:refresh-session {"sessionId":"demo-1"}',
      'tour:viewer {"index":1,"drawerOpen":false}',
    ],
    34: ['click:nav-help'],
  };

  it('only the steps the table gives a before hook have one', () => {
    const withHook = TOUR_STEPS.map((s, i) => (s.before ? i + 1 : null)).filter((n): n is number => n !== null);
    expect(withHook).toEqual(Object.keys(EXPECTED).map(Number));
  });

  it('walking the tour forwards, each hook does exactly what its step needs', async () => {
    const actual: Record<number, string[]> = {};
    for (const [i, step] of TOUR_STEPS.entries()) {
      if (step.before) actual[i + 1] = await runHook(step);
    }
    expect(actual).toEqual(EXPECTED);
  });

  it('every clickNav page step opens the sidebar item for the page it targets', async () => {
    // page-<x-y> target <-> sidebar viewId <x_y>, and that viewId must be a real NavSecondary item.
    for (const [i, step] of TOUR_STEPS.entries()) {
      const page = String(step.target).match(/^\[data-tour="page-([a-z-]+)"\]$/)?.[1];
      if (!page || !step.before) continue;
      const viewId = page.replace(/-/g, '_');
      expect(navViewIds, `step ${i + 1}`).toContain(viewId);
      expect(await runHook(step), `step ${i + 1}`).toEqual([`click:nav-${viewId}`]);
    }
  });

  it('re-entering a stage step via Back does not re-run the stage', async () => {
    const byNumber = (n: number) => TOUR_STEPS[n - 1];
    await runHook(byNumber(19));
    await runHook(byNumber(20));
    await runHook(byNumber(21));
    expect(await runHook(byNumber(21))).toEqual([]);
    expect(apiMock.runTourDemoStage.mock.calls.map(c => c[1])).toEqual(['plan', 'build']);
  });
});
