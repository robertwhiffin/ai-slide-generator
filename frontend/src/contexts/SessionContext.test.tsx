/**
 * Deck Mode toggle, Task 7: SessionContext tracks the deck's stored mode and the user's selection.
 *
 *   storedDeckMode    the server's value for the current deck; null = unlocked (no first message yet)
 *   selectedDeckMode  the user's pick for an unlocked deck; default 'agent'
 *   setSelectedDeckMode / setStoredDeckMode   plain setters (ChatPanel locks optimistically and
 *                                             reconciles through setStoredDeckMode)
 *
 * Rules pinned here (task brief + PLAN-CORRECTIONS Task 7):
 *   - createNewSession resets both (null / 'agent').
 *   - switchSession takes storedDeckMode from `deck_mode ?? null` on BOTH whitelist branches: the
 *     existingSessionInfo branch (no getSession call: MixedReleaseWarning.test.tsx's SessionContext test
 *     throws on any non-collaboration fetch) and the api.getSession branch (C1).
 *   - Switching to a DIFFERENT deck resets the selection to 'agent' (Review Focus 2).
 *   - A same-session re-restore (C2: landing deck -> ensureGraphCapableRoot -> navigate to the same id
 *     -> loadSessionFromServer -> switchSession(sameId, {deck_mode: null})) leaves the selection alone and
 *     never replaces a non-null local storedDeckMode with null; a server null there only means the
 *     first message's lock has not committed yet. A non-null server value is still the truth.
 *   - The mode state commits inside the atomic `if (!isCancelled?.())` block (C3): a superseded switch
 *     changes neither.
 *   - AppLayout's loadSessionFromServer literal carries `deck_mode: sessionInfo.deck_mode` (C5; source pin,
 *     because rendering AppLayout needs the whole app shell).
 *
 * Harness: the real SessionProvider with a probe component (as MixedReleaseWarning.test.tsx's
 * "collaboration state in SessionContext"). The api calls switchSession makes are spied on the real
 * `api` object, and any real fetch throws, so a stray request is a failure rather than a silent pass.
 *
 * SABOTAGE (measured against a throwaway implementation outside the worktree; each turned at least one
 * test red):
 *   - deck_mode missing from the existingSessionInfo whitelist   -> "existingSessionInfo branch".
 *   - deck_mode missing from the api.getSession whitelist         -> "api.getSession branch".
 *   - the existingSessionInfo branch fetches getSession           -> "existingSessionInfo branch" (no call).
 *   - switchSession never resets the selection                    -> "switching decks resets".
 *   - switchSession resets the selection on every call            -> the same-session tests.
 *   - switchSession always writes deck_mode ?? null               -> the same-session lock tests.
 *   - the same-id check uses only ids seen by switchSession (the
 *     provider's initial local id counts as "changed")            -> "the landing deck's own id".
 *   - the same-id guard also ignores a non-null server value      -> "a non-null server value".
 *   - the mode setters run before the isCancelled check           -> "a superseded switch".
 *   - createNewSession does not reset one of them                 -> "new session".
 *   - setStoredDeckMode refuses null                              -> "plain setter".
 *   - AppLayout's literal omits deck_mode                         -> the AppLayout pin.
 */
import { act, render, screen } from '@testing-library/react';
import type { MockInstance } from 'vitest';
import ts from 'typescript';
import appLayoutSource from '../components/Layout/AppLayout.tsx?raw';
import { api, type CollaborationHistory, type DeckMode, type Session } from '../services/api';
import { SessionProvider, useSession, type OptionalSessionInfo } from './SessionContext';

type Ctx = ReturnType<typeof useSession>;

let ctx: Ctx;

function Probe() {
  ctx = useSession();
  return (
    <>
      <output data-testid="session-id">{String(ctx.sessionId)}</output>
      <output data-testid="persisted">{String(ctx.isSessionPersisted)}</output>
      <output data-testid="stored-mode">{String(ctx.storedDeckMode)}</output>
      <output data-testid="selected-mode">{String(ctx.selectedDeckMode)}</output>
    </>
  );
}

const stored = () => screen.getByTestId('stored-mode').textContent;
const selected = () => screen.getByTestId('selected-mode').textContent;
const shownSessionId = () => screen.getByTestId('session-id').textContent;

const EMPTY_HISTORY: CollaborationHistory = { mixed_release_warning: false, has_legacy_evidence: false, groups: [] };

function fullSession(id: string, deck_mode: DeckMode | null): Session {
  return {
    session_id: id,
    user_id: 'u',
    created_by: 'u',
    title: 'From the server',
    created_at: '2026-10-26T00:00:00Z',
    has_slide_deck: false,
    graph_version: 1,
    active_graph_version: 1,
    is_older_than_active: false,
    deck_mode,
  };
}

let getSession: MockInstance<typeof api.getSession>;
let getSlides: MockInstance<typeof api.getSlides>;

beforeEach(() => {
  getSession = vi.spyOn(api, 'getSession').mockImplementation(async (id: string) => fullSession(id, null));
  getSlides = vi.spyOn(api, 'getSlides').mockImplementation(async (id: string) => ({ session_id: id, slide_deck: null }));
  vi.spyOn(api, 'getCollaborationHistory').mockResolvedValue(EMPTY_HISTORY);
  vi.spyOn(globalThis, 'fetch').mockImplementation(async (input) => {
    throw new Error(`unexpected fetch: ${String(input)}`);
  });
});

afterEach(() => {
  vi.restoreAllMocks();
});

/** Let promise continuations (the collaboration load, a mocked fetch) run. */
const settle = () => act(async () => { await new Promise((r) => setTimeout(r, 0)); });

function mount() {
  render(
    <SessionProvider>
      <Probe />
    </SessionProvider>,
  );
}

function info(deck_mode: DeckMode | null | undefined, extra: Partial<OptionalSessionInfo> = {}): OptionalSessionInfo {
  const base: OptionalSessionInfo = { title: 'Deck', has_slide_deck: false, ...extra };
  return deck_mode === undefined ? base : { ...base, deck_mode };
}

async function switchTo(id: string, sessionInfo?: OptionalSessionInfo, isCancelled?: () => boolean) {
  await act(async () => { await ctx.switchSession(id, sessionInfo, isCancelled); });
  await settle();
}

async function select(mode: DeckMode) {
  expect(typeof ctx.setSelectedDeckMode, 'SessionContext has no setSelectedDeckMode').toBe('function');
  await act(async () => { ctx.setSelectedDeckMode(mode); });
}

/** What ChatPanel does on the first send of an unlocked deck. */
async function lockLocally(mode: DeckMode | null) {
  expect(typeof ctx.setStoredDeckMode, 'SessionContext has no setStoredDeckMode').toBe('function');
  await act(async () => { ctx.setStoredDeckMode(mode); });
}

describe('deck mode in SessionContext', () => {
  it('a fresh provider is unlocked on Agent mode, and exposes both setters', () => {
    mount();
    expect(stored()).toBe('null');
    expect(selected()).toBe('agent');
    expect(typeof ctx.setSelectedDeckMode).toBe('function');
    expect(typeof ctx.setStoredDeckMode).toBe('function');
  });

  it('setSelectedDeckMode and setStoredDeckMode are plain setters (null unlocks again)', async () => {
    mount();
    await select('legacy');
    expect(selected()).toBe('legacy');
    await select('agent');
    expect(selected()).toBe('agent');

    await lockLocally('legacy');
    expect(stored()).toBe('legacy');
    // ChatPanel's reconcile after a failed send sets the server's null: the deck is unlocked again.
    await lockLocally(null);
    expect(stored()).toBe('null');
  });

  it.each<DeckMode>(['legacy', 'agent'])(
    'restores the stored mode %j through the existingSessionInfo branch, with no getSession call',
    async (mode) => {
      mount();
      await switchTo('deck-S', { title: 't', deck_mode: mode });

      expect(shownSessionId()).toBe('deck-S'); // the restore committed
      expect(stored()).toBe(mode);
      expect(getSession).not.toHaveBeenCalled();
    },
  );

  it.each<DeckMode>(['legacy', 'agent'])(
    'restores the stored mode %j through the api.getSession branch (no existingSessionInfo)',
    async (mode) => {
      getSession.mockImplementation(async (id: string) => fullSession(id, mode));
      mount();
      await switchTo('deck-S');

      expect(getSession).toHaveBeenCalledTimes(1);
      expect(getSession).toHaveBeenCalledWith('deck-S');
      expect(shownSessionId()).toBe('deck-S');
      expect(stored()).toBe(mode);
    },
  );

  it('switching decks resets the selection to Agent mode, and an unlocked deck reads as unlocked', async () => {
    mount();
    await select('legacy');
    expect(selected()).toBe('legacy');

    await switchTo('deck-T', info(null));
    expect(shownSessionId()).toBe('deck-T');
    expect(selected()).toBe('agent');
    expect(stored()).toBe('null');

    // From a locked deck to one whose info carries no deck_mode at all: still unlocked, not the old lock.
    await switchTo('deck-L', info('legacy'));
    expect(stored()).toBe('legacy');
    await select('legacy');
    await switchTo('deck-U', info(undefined));
    expect(shownSessionId()).toBe('deck-U');
    expect(stored()).toBe('null');
    expect(selected()).toBe('agent');
  });

  it('new session starts unlocked on Agent mode', async () => {
    mount();
    await switchTo('deck-L', info('legacy'));
    await select('legacy');
    expect(stored()).toBe('legacy');
    expect(selected()).toBe('legacy');

    let newId = '';
    await act(async () => { newId = ctx.createNewSession(); });

    expect(shownSessionId()).toBe(newId);
    expect(newId).not.toBe('deck-L');
    expect(stored()).toBe('null');
    expect(selected()).toBe('agent');
  });
});

describe('a same-session re-restore keeps the optimistic lock (C2)', () => {
  it('optimistic legacy on S, then switchSession(S, {deck_mode: null}): the lock and the selection stay; switching to T resets both', async () => {
    mount();
    await switchTo('deck-S', info(null));
    await select('legacy');
    await lockLocally('legacy'); // the first send locked optimistically

    // loadSessionFromServer re-restores the SAME id while the first message is in flight; the server
    // has not committed the lock yet, so its deck_mode is still null.
    await switchTo('deck-S', info(null));
    expect(shownSessionId()).toBe('deck-S');
    expect(stored()).toBe('legacy');
    expect(selected()).toBe('legacy');

    // A different deck: both reset.
    await switchTo('deck-T', info(null));
    expect(shownSessionId()).toBe('deck-T');
    expect(stored()).toBe('null');
    expect(selected()).toBe('agent');
  });

  it("the landing deck's own id (never passed to switchSession before) counts as the same session", async () => {
    // The production first-send path: the provider's initial browser-local id is persisted by
    // ensureGraphCapableRoot and then re-restored under that same id.
    mount();
    const landingId = ctx.sessionId!;
    expect(landingId).toBeTruthy();
    await select('legacy');
    await lockLocally('legacy');

    await switchTo(landingId, { title: null, has_slide_deck: false, deck_mode: null });

    expect(shownSessionId()).toBe(landingId);
    expect(screen.getByTestId('persisted').textContent).toBe('true'); // the re-restore committed
    expect(stored()).toBe('legacy');
    expect(selected()).toBe('legacy');
  });

  it('an unlocked same-session re-restore keeps the selection', async () => {
    mount();
    await switchTo('deck-S', info(null));
    await select('legacy');

    await switchTo('deck-S', info(null));
    expect(stored()).toBe('null');
    expect(selected()).toBe('legacy');
  });

  it("a non-null server value on a same-session re-restore replaces the local one (the server's lock is the truth)", async () => {
    mount();
    await switchTo('deck-S', info(null));
    await select('legacy');
    await lockLocally('legacy');

    // e.g. another tab's first message locked the deck as Agent mode first.
    await switchTo('deck-S', info('agent'));
    expect(stored()).toBe('agent');
    expect(selected()).toBe('legacy'); // same session: the selection is still untouched
  });
});

describe('the mode state commits with the rest of the restore (C3)', () => {
  it('a superseded switch changes neither the stored mode nor the selection; the same switch uncancelled does', async () => {
    mount();
    await switchTo('deck-S', info('legacy'));
    await select('legacy');
    expect(stored()).toBe('legacy');

    await switchTo('deck-T', info(null, { has_slide_deck: true }), () => true);
    expect(getSlides).toHaveBeenCalledWith('deck-T'); // the restore really ran up to the commit
    expect(shownSessionId()).toBe('deck-S');
    expect(stored()).toBe('legacy');
    expect(selected()).toBe('legacy');

    // Positive half: not cancelled, the same switch commits and resets both.
    await switchTo('deck-T', info(null, { has_slide_deck: true }), () => false);
    expect(shownSessionId()).toBe('deck-T');
    expect(stored()).toBe('null');
    expect(selected()).toBe('agent');
  });
});

// ── AppLayout's URL-restore literal carries deck_mode (C5; source pin) ─────────
//
// loadSessionFromServer fetches the session and hands switchSession a field-by-field literal as
// existingSessionInfo; a field missing there is dropped on every reload and URL restore. Read through
// the TypeScript parser, so a comment cannot satisfy it.

const appLayout = ts.createSourceFile('AppLayout.tsx', appLayoutSource, ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX);

function findAll<T extends ts.Node>(root: ts.Node, test: (n: ts.Node) => n is T): T[] {
  const out: T[] = [];
  const visit = (n: ts.Node) => {
    if (test(n)) out.push(n);
    ts.forEachChild(n, visit);
  };
  visit(root);
  return out;
}

describe("AppLayout's loadSessionFromServer", () => {
  it('passes deck_mode from the fetched session to switchSession, beside title', () => {
    const decl = findAll(appLayout, ts.isVariableDeclaration).find(
      (d) => ts.isIdentifier(d.name) && d.name.text === 'loadSessionFromServer',
    );
    expect(decl, 'loadSessionFromServer not found in AppLayout.tsx').toBeDefined();

    const switchCalls = findAll(decl!, ts.isCallExpression).filter(
      (c) => c.expression.getText(appLayout) === 'switchSession',
    );
    expect(switchCalls).toHaveLength(1);
    const literal = switchCalls[0].arguments[1];
    expect(literal && ts.isObjectLiteralExpression(literal), 'switchSession arg 2 is not an object literal').toBe(true);

    const props = new Map(
      (literal as ts.ObjectLiteralExpression).properties
        .filter(ts.isPropertyAssignment)
        .map((p) => [p.name.getText(appLayout), p.initializer.getText(appLayout).replace(/\s+/g, '')]),
    );
    // Vacuity guard: the literal is the one that reads the fetched session's fields.
    const title = props.get('title');
    expect(title).toMatch(/^\w+\.title$/);
    expect(props.get('deck_mode')).toBe(title!.replace(/\.title$/, '.deck_mode'));
  });
});
