import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { SessionProvider, useSession, type OptionalSessionInfo } from '@/contexts/SessionContext';
import {
  api,
  ApiError,
  type CollaborationHistory,
  type CollaborationReleaseGroup,
} from '@/services/api';
import { GraphVersionStatus } from './GraphVersionStatus';
import {
  MixedReleaseWarning,
  type MixedReleaseWarningProps,
} from './MixedReleaseWarning';

/**
 * The mandated display vocabulary, written out LITERALLY rather than imported
 * from the component.
 *
 * Importing the component's own constants was the first version of this file and
 * it was not a guard: renaming `PROVENANCE_LIST_LABEL` to a string that NESTS
 * inside the disclosure's name — the exact strict-mode hazard this epic has paid
 * for twice — left every assertion here green, and only the Playwright spec
 * (which uses literals) caught it. Literals here mean a wording change has to be
 * made deliberately in two places.
 */
const WARNING_TEXT = 'This shared deck has changes from multiple Graph Versions.';
const DISCLOSURE_LABEL = 'Change provenance';
const PROVENANCE_LIST_LABEL = 'Contributor releases';
const HISTORY_UNAVAILABLE_TEXT = 'Collaboration history unavailable';

const NEWEST = '2026-09-20T10:15:00Z';
const MIDDLE = '2026-09-19T09:05:00Z';
const OLDEST = '2026-09-18T08:00:00Z';

/** A real UUID shape, used only as a needle the UI must never render. */
const LEAKED_UUID = '3f1c9b6e-8a4d-4f2b-9c77-0d5e1a2b3c4d';
const LEAKED_PRINCIPAL = 'alice@example.com';

function group(
  overrides: Partial<CollaborationReleaseGroup> = {},
): CollaborationReleaseGroup {
  return {
    actor_label: 'Contributor 1',
    graph_version: 2,
    mutation_count: 3,
    last_mutation_at: NEWEST,
    ...overrides,
  };
}

function history(overrides: Partial<CollaborationHistory> = {}): CollaborationHistory {
  return {
    mixed_release_warning: false,
    has_legacy_evidence: false,
    groups: [group()],
    ...overrides,
  };
}

/**
 * Newest-first evidence for ONE deck with TWO releases and ONE actor spanning
 * both — the shape the backend genuinely produces, and the shape that makes
 * `actor_label` a non-unique key.
 *
 * The three row names are mutually non-substring, which is the property
 * Playwright's case-insensitive substring name matching requires and which
 * `keeps every row name distinct under substring matching` pins.
 */
const MIXED_HISTORY: CollaborationHistory = {
  mixed_release_warning: true,
  has_legacy_evidence: false,
  groups: [
    group({ actor_label: 'Contributor 1', graph_version: 2, mutation_count: 3, last_mutation_at: NEWEST }),
    group({ actor_label: 'Contributor 2', graph_version: 1, mutation_count: 2, last_mutation_at: MIDDLE }),
    group({ actor_label: 'Contributor 1', graph_version: 1, mutation_count: 5, last_mutation_at: OLDEST }),
  ],
};

function renderWarning(props: Partial<MixedReleaseWarningProps> = {}) {
  return render(
    <MixedReleaseWarning
      history={history()}
      loadFailed={false}
      isSessionPersisted
      {...props}
    />,
  );
}

async function expand() {
  await act(async () => {
    fireEvent.click(screen.getByRole('button', { name: DISCLOSURE_LABEL }));
  });
}

describe('MixedReleaseWarning', () => {
  it('warns when one deck carries changes from two persisted Graph Versions', () => {
    renderWarning({ history: MIXED_HISTORY });

    expect(screen.getByRole('status')).toHaveTextContent(WARNING_TEXT);
  });

  it('shows no warning when every change is on the same release', () => {
    renderWarning({
      history: {
        mixed_release_warning: false,
        has_legacy_evidence: false,
        groups: [
          group({ actor_label: 'Contributor 1', graph_version: 2, mutation_count: 3 }),
          group({ actor_label: 'Contributor 2', graph_version: 2, mutation_count: 1, last_mutation_at: MIDDLE }),
        ],
      },
    });

    // The provenance disclosure is still offered — only the WARNING is absent.
    expect(screen.getByRole('button', { name: DISCLOSURE_LABEL })).toBeInTheDocument();
    expect(screen.queryByText(WARNING_TEXT)).not.toBeInTheDocument();
    expect(screen.queryByRole('status')).not.toBeInTheDocument();
  });

  it('calls a null graph release Legacy and never active', async () => {
    renderWarning({
      history: {
        mixed_release_warning: false,
        has_legacy_evidence: true,
        groups: [group({ actor_label: 'Contributor 1', graph_version: null, mutation_count: 2 })],
      },
    });
    await expand();

    expect(
      screen.getByRole('listitem', { name: 'Contributor 1, Legacy (no graph release), 2 changes' }),
    ).toBeInTheDocument();
    // Ruling F6: the API emits no display vocabulary, and a legacy row must
    // never be described as "active".
    expect(screen.getByTestId('mixed-release-warning').textContent).not.toMatch(/active/i);
  });

  it('shows a visible failure state without erasing the pinned-version badge', () => {
    render(
      <>
        <GraphVersionStatus
          graphVersion={1}
          activeGraphVersion={2}
          isOlder
          onStartLatest={async () => {}}
          isStartingLatest={false}
        />
        <MixedReleaseWarning history={null} loadFailed isSessionPersisted />
      </>,
    );

    expect(screen.getByRole('status')).toHaveTextContent(HISTORY_UNAVAILABLE_TEXT);
    // The #261 badge survives a failed collaboration load.
    expect(screen.getByTestId('graph-version-status')).toHaveTextContent(
      'Pinned Graph Version 1; latest is 2',
    );
    expect(screen.getByRole('button', { name: 'Start latest' })).toBeInTheDocument();
  });

  it('keeps the unavailable state generic — no contributor, release or session', () => {
    renderWarning({ history: null, loadFailed: true });

    const region = screen.getByTestId('mixed-release-warning');
    expect(region.textContent).toBe(HISTORY_UNAVAILABLE_TEXT);
    expect(region.innerHTML).not.toMatch(/Contributor|Graph Version|Legacy/);
    expect(screen.queryByRole('button', { name: DISCLOSURE_LABEL })).not.toBeInTheDocument();
  });

  it('discloses provenance behind a focusable button and labels each row', async () => {
    renderWarning({ history: MIXED_HISTORY });

    const disclosure = screen.getByRole('button', { name: DISCLOSURE_LABEL });
    // A real <button>, so Enter and Space activate it without extra handlers.
    expect(disclosure.tagName).toBe('BUTTON');
    disclosure.focus();
    expect(disclosure).toHaveFocus();
    expect(disclosure).toHaveAttribute('aria-expanded', 'false');
    expect(screen.queryByRole('list', { name: PROVENANCE_LIST_LABEL })).not.toBeInTheDocument();

    await expand();

    expect(disclosure).toHaveAttribute('aria-expanded', 'true');
    expect(disclosure).toHaveAttribute(
      'aria-controls',
      screen.getByRole('list', { name: PROVENANCE_LIST_LABEL }).id,
    );
    expect(
      screen.getByRole('listitem', { name: 'Contributor 1, Graph Version 2, 3 changes' }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole('listitem', { name: 'Contributor 2, Graph Version 1, 2 changes' }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole('listitem', { name: 'Contributor 1, Graph Version 1, 5 changes' }),
    ).toBeInTheDocument();
  });

  it('labels each row from its OWN returned release, not one release for the deck', async () => {
    render(
      <>
        <GraphVersionStatus
          graphVersion={1}
          activeGraphVersion={2}
          isOlder
          onStartLatest={async () => {}}
          isStartingLatest={false}
        />
        <MixedReleaseWarning history={MIXED_HISTORY} loadFailed={false} isSessionPersisted />
      </>,
    );
    await expand();

    // The conversation's own badge says 1; the newest group says 2. A row that
    // borrowed the root badge's version, or reused the first group's version for
    // every row, cannot satisfy both of these at once.
    expect(screen.getByTestId('graph-version-status')).toHaveTextContent('Pinned Graph Version 1');
    expect(
      screen.getByRole('listitem', { name: 'Contributor 1, Graph Version 2, 3 changes' }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole('listitem', { name: 'Contributor 2, Graph Version 1, 2 changes' }),
    ).toBeInTheDocument();
  });

  it('keeps every row name distinct under substring matching', async () => {
    renderWarning({ history: MIXED_HISTORY });
    await expand();

    const names = screen
      .getAllByTestId('mixed-release-row')
      .map((row) => row.getAttribute('aria-label') ?? '');

    // Cardinality joined to the fixture, so a narrowed fixture cannot silently
    // shrink this check to a vacuous pass.
    expect(names).toHaveLength(MIXED_HISTORY.groups.length);
    expect(new Set(names).size).toBe(MIXED_HISTORY.groups.length);
    // Two rows share ONE actor label, which is why the label alone is not a key.
    expect(new Set(MIXED_HISTORY.groups.map((g) => g.actor_label)).size).toBe(2);

    // Playwright matches accessible names by case-insensitive SUBSTRING, so a
    // row name nested inside another row name would resolve to two elements and
    // fail only in the browser. Assert the property Vitest cannot otherwise see.
    for (const outer of names) {
      for (const inner of names) {
        if (outer === inner) continue;
        expect(outer.toLowerCase()).not.toContain(inner.toLowerCase());
      }
    }
    // The disclosure's own name must not nest inside a row name either.
    for (const name of names) {
      expect(name.toLowerCase()).not.toContain(DISCLOSURE_LABEL.toLowerCase());
    }
  });

  it('lets no server-added field reach the DOM or the accessibility tree', async () => {
    const leaky = {
      ...group(),
      actor_session_id: LEAKED_UUID,
      actor_session_identity: LEAKED_UUID,
      root_session_id: LEAKED_UUID,
      user_name: LEAKED_PRINCIPAL,
      principal: LEAKED_PRINCIPAL,
      session_name: 'Alice quarterly review',
    } as unknown as CollaborationReleaseGroup;

    renderWarning({
      history: { mixed_release_warning: true, has_legacy_evidence: false, groups: [leaky] },
    });
    await expand();

    const region = screen.getByTestId('mixed-release-warning');
    for (const needle of [LEAKED_UUID, LEAKED_PRINCIPAL, 'Alice quarterly review']) {
      expect(region.textContent).not.toContain(needle);
      // innerHTML, not textContent, so an aria-label or title leak is caught too.
      expect(region.innerHTML).not.toContain(needle);
    }
    expect(region.innerHTML).not.toMatch(
      /[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}/i,
    );
    expect(region.innerHTML).not.toContain('@');
  });

  it('renders nothing for a session that is not persisted', () => {
    const { container } = render(
      <MixedReleaseWarning
        history={MIXED_HISTORY}
        loadFailed={false}
        isSessionPersisted={false}
      />,
    );

    expect(container).toBeEmptyDOMElement();
    expect(screen.queryByText(WARNING_TEXT)).not.toBeInTheDocument();
  });

  it('renders nothing when a persisted deck has no collaboration evidence', () => {
    const { container } = renderWarning({
      history: { mixed_release_warning: false, has_legacy_evidence: false, groups: [] },
    });

    expect(container).toBeEmptyDOMElement();
  });
});

describe('api.getCollaborationHistory', () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it('narrows the response to the four safe group fields', async () => {
    const fetchMock = vi.spyOn(globalThis, 'fetch').mockResolvedValue(
      new Response(
        JSON.stringify({
          mixed_release_warning: true,
          has_legacy_evidence: true,
          groups: [
            {
              actor_label: 'Contributor 1',
              graph_version: 2,
              mutation_count: 3,
              last_mutation_at: NEWEST,
              actor_session_id: LEAKED_UUID,
              user_name: LEAKED_PRINCIPAL,
            },
          ],
          root_session_id: LEAKED_UUID,
        }),
        { status: 200 },
      ),
    );

    const result = await api.getCollaborationHistory('root-session');

    expect(Object.keys(result)).toEqual([
      'mixed_release_warning',
      'has_legacy_evidence',
      'groups',
    ]);
    expect(Object.keys(result.groups[0])).toEqual([
      'actor_label',
      'graph_version',
      'mutation_count',
      'last_mutation_at',
    ]);
    expect(JSON.stringify(result)).not.toContain(LEAKED_UUID);
    expect(JSON.stringify(result)).not.toContain(LEAKED_PRINCIPAL);
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it('sends a bare authenticated GET carrying no identity of its own', async () => {
    const fetchMock = vi.spyOn(globalThis, 'fetch').mockResolvedValue(
      new Response(
        JSON.stringify({ mixed_release_warning: false, has_legacy_evidence: false, groups: [] }),
        { status: 200 },
      ),
    );

    await api.getCollaborationHistory('root-session');

    const [url, init] = fetchMock.mock.calls[0];
    expect(String(url)).toMatch(
      /\/api\/sessions\/root-session\/collaboration-history$/,
    );
    // No init at all: default GET, no body, no query string, no hand-rolled
    // user/principal header. The requested session id is the only identifier
    // that crosses the wire, and it is the caller's own.
    expect(init).toBeUndefined();
  });

  it('treats every denied response as one generic failure and never retries', async () => {
    // The endpoint's 404 is byte-identical for an unauthorized REAL id and a
    // fabricated one. A client that surfaced the detail — or retried to see
    // whether the id exists — would turn that into an existence oracle.
    const bodies = [
      { status: 404, detail: 'Session not found: 3f1c9b6e-real-but-unauthorized' },
      { status: 404, detail: 'Session not found: 00000000-fabricated' },
      { status: 500, detail: 'Failed to get collaboration history' },
    ];
    const messages: string[] = [];
    const statuses: number[] = [];

    for (const { status, detail } of bodies) {
      // A FRESH Response per call, from mockImplementation rather than
      // mockResolvedValue. A single shared Response would have its body consumed
      // by the first call, so a client that DID read the detail would silently
      // fall back to the generic message on every later call — which is exactly
      // how this assertion was vacuous when first written.
      const fetchMock = vi.spyOn(globalThis, 'fetch').mockImplementation(
        async () => new Response(JSON.stringify({ detail }), { status }),
      );
      try {
        await api.getCollaborationHistory('probe-session');
        messages.push('NO REJECTION');
        statuses.push(-1);
      } catch (err) {
        expect(err).toBeInstanceOf(ApiError);
        messages.push((err as ApiError).message);
        statuses.push((err as ApiError).status);
      }
      // Exactly one request: no retry, no second probe for existence.
      expect(fetchMock).toHaveBeenCalledTimes(1);
      fetchMock.mockRestore();
    }

    expect(new Set(messages).size).toBe(1);
    expect(messages[0]).toBe('Failed to get collaboration history');
    for (const message of messages) {
      expect(message).not.toContain('3f1c9b6e');
      expect(message).not.toContain('fabricated');
    }
    expect(statuses).toEqual([404, 404, 500]);
  });
});

/**
 * Compile-time half of the privacy contract.
 *
 * `npm run typecheck` (tsc -b) covers `src/**`, so if either interface ever
 * grows a field, `Extra*Keys` stops being `never`, the `never[]` assignment
 * below stops compiling, and the typecheck gate fails. The runtime expectations
 * exist so `noUnusedLocals` does not strip the guard.
 */
type ExtraGroupKeys = Exclude<
  keyof CollaborationReleaseGroup,
  'actor_label' | 'graph_version' | 'mutation_count' | 'last_mutation_at'
>;
type ExtraHistoryKeys = Exclude<
  keyof CollaborationHistory,
  'mixed_release_warning' | 'has_legacy_evidence' | 'groups'
>;

describe('collaboration client types', () => {
  it('declares no field beyond the documented safe set', () => {
    const extraGroupKeys: ExtraGroupKeys[] = [];
    const extraHistoryKeys: ExtraHistoryKeys[] = [];
    const noExtraGroupKeys: never[] = extraGroupKeys;
    const noExtraHistoryKeys: never[] = extraHistoryKeys;

    expect(noExtraGroupKeys).toHaveLength(0);
    expect(noExtraHistoryKeys).toHaveLength(0);
  });
});

type CollaborationSessionContext = ReturnType<typeof useSession>;

function CollaborationProbe({ isCancelled }: { isCancelled?: () => boolean }) {
  const session: CollaborationSessionContext = useSession();
  const restore = async () => {
    const info: OptionalSessionInfo = {
      title: 'Shared deck',
      has_slide_deck: false,
      graph_version: 1,
      active_graph_version: 2,
      is_older_than_active: true,
    };
    await session.switchSession('root-session', info, isCancelled);
  };

  return (
    <>
      <output data-testid="collab">{JSON.stringify(session.collaborationHistory)}</output>
      <output data-testid="collab-failed">{String(session.collaborationHistoryFailed)}</output>
      <output data-testid="persisted">{String(session.isSessionPersisted)}</output>
      <button onClick={() => void restore()}>Restore shared session</button>
      <button onClick={() => session.createNewSession()}>New local session</button>
    </>
  );
}

/** Flush a real macrotask, so a mocked fetch's continuation has certainly run. */
async function settle() {
  await act(async () => {
    await new Promise((resolve) => setTimeout(resolve, 0));
  });
}

describe('collaboration state in SessionContext', () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  /** Mock only the history endpoint; any other fetch is a test-design error. */
  function mockHistoryFetch(respond: (url: string) => Promise<Response>) {
    return vi.spyOn(globalThis, 'fetch').mockImplementation(async (input) => {
      const url = String(input);
      if (url.includes('/collaboration-history')) {
        return respond(url);
      }
      throw new Error(`unexpected fetch: ${url}`);
    });
  }

  function respondWith(body: unknown, status = 200) {
    return async () => new Response(JSON.stringify(body), { status });
  }

  it('loads collaboration evidence on a successful switch and clears it for a fresh session', async () => {
    const fetchMock = mockHistoryFetch(respondWith(MIXED_HISTORY));

    render(
      <SessionProvider>
        <CollaborationProbe />
      </SessionProvider>,
    );

    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: 'Restore shared session' }));
    });

    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(screen.getByTestId('persisted').textContent).toBe('true');
    await waitFor(() => {
      expect(JSON.parse(screen.getByTestId('collab').textContent ?? 'null')).toEqual(MIXED_HISTORY);
    });
    expect(screen.getByTestId('collab-failed').textContent).toBe('false');

    fireEvent.click(screen.getByRole('button', { name: 'New local session' }));

    expect(screen.getByTestId('collab').textContent).toBe('null');
    expect(screen.getByTestId('collab-failed').textContent).toBe('false');
    expect(screen.getByTestId('persisted').textContent).toBe('false');
  });

  it('records one generic failure when the history load is denied', async () => {
    mockHistoryFetch(respondWith({ detail: 'Session not found: root-session' }, 404));

    render(
      <SessionProvider>
        <CollaborationProbe />
      </SessionProvider>,
    );

    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: 'Restore shared session' }));
    });
    await waitFor(() => {
      expect(screen.getByTestId('collab-failed').textContent).toBe('true');
    });

    expect(screen.getByTestId('collab').textContent).toBe('null');
    // A denied history load must not fail the restore itself.
    expect(screen.getByTestId('persisted').textContent).toBe('true');
  });

  it('commits nothing at all for a switch that was already superseded', async () => {
    const fetchMock = mockHistoryFetch(respondWith(MIXED_HISTORY));

    render(
      <SessionProvider>
        <CollaborationProbe isCancelled={() => true} />
      </SessionProvider>,
    );

    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: 'Restore shared session' }));
    });
    await settle();

    // The load really ran, so a green result here is not the vacuous
    // "nothing happened" case.
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(screen.getByTestId('collab').textContent).toBe('null');
    expect(screen.getByTestId('collab-failed').textContent).toBe('false');
    expect(screen.getByTestId('persisted').textContent).toBe('false');
  });

  it('discards evidence for a switch superseded while its load was in flight', async () => {
    // Cancellation that flips AFTER the session state commits and BEFORE the
    // history lands — the only ordering that reaches the landing guard, which a
    // predicate fixed at `true` never does.
    let cancelled = false;
    let releaseHistory: (() => void) | undefined;
    const pending = new Promise<Response>((resolve) => {
      releaseHistory = () => resolve(new Response(JSON.stringify(MIXED_HISTORY), { status: 200 }));
    });
    mockHistoryFetch(async () => pending);

    render(
      <SessionProvider>
        <CollaborationProbe isCancelled={() => cancelled} />
      </SessionProvider>,
    );

    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: 'Restore shared session' }));
    });
    expect(screen.getByTestId('persisted').textContent).toBe('true');

    cancelled = true;
    releaseHistory?.();
    await settle();

    expect(screen.getByTestId('collab').textContent).toBe('null');
  });

  it('discards evidence that lands after the session has already changed', async () => {
    let releaseHistory: (() => void) | undefined;
    const pending = new Promise<Response>((resolve) => {
      releaseHistory = () => resolve(new Response(JSON.stringify(MIXED_HISTORY), { status: 200 }));
    });
    mockHistoryFetch(async () => pending);

    render(
      <SessionProvider>
        <CollaborationProbe />
      </SessionProvider>,
    );

    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: 'Restore shared session' }));
    });
    expect(screen.getByTestId('persisted').textContent).toBe('true');

    // The user starts a fresh local session while the load is still in flight.
    fireEvent.click(screen.getByRole('button', { name: 'New local session' }));
    releaseHistory?.();
    await settle();

    // The shared deck's evidence must not attach itself to the new session.
    expect(screen.getByTestId('collab').textContent).toBe('null');
    expect(screen.getByTestId('collab-failed').textContent).toBe('false');
  });
});
