import { act, fireEvent, render, renderHook, screen, waitFor, within } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import {
  HISTORY_ACTIVE_ARCHITECT_PROMPT,
  syntheticBlockedRollbackPreview,
  syntheticHistoryEntry,
  syntheticPublishSuccess,
  syntheticPublishedReleasePreview,
  syntheticReleaseComparison,
  syntheticReleaseDetail,
  syntheticReleaseHistory,
  syntheticReleasePreview,
  syntheticRestoredReleaseHistory,
  syntheticRollbackIncompatible,
  syntheticRollbackInvalid,
  syntheticRollbackPreview,
  syntheticRollbackSuccess,
  syntheticRolledBackReleasePreview,
  syntheticStaleRollback,
} from '../../../../tests/fixtures/mocks';
import { ReviewAndPublishPage } from './ReviewAndPublishPage';
import { canConfirmRollback } from './reviewAndPublishState';
import { useReviewAndPublish } from './useReviewAndPublish';
import { formatInstant } from './releaseText';

const PREVIEW_URL = /\/api\/admin\/agent-definitions\/release-preview$/;
const RELEASES_URL = /\/api\/admin\/agent-definitions\/releases$/;
const DETAIL_URL = /\/api\/admin\/agent-definitions\/releases\/(\d+)$/;
const COMPARISON_URL = /\/api\/admin\/agent-definitions\/releases\/(\d+)\/comparison$/;
const ROLLBACK_PREVIEW_URL = /\/api\/admin\/agent-definitions\/releases\/(\d+)\/rollback-preview$/;
const ROLLBACK_URL = /\/api\/admin\/agent-definitions\/releases\/(\d+)\/rollback$/;

function apiResponse(status: number, body: unknown) {
  return { ok: status >= 200 && status < 300, status, statusText: '', json: vi.fn().mockResolvedValue(body) };
}

type Responder = () => Promise<unknown> | unknown;

const ok = (body: unknown): Responder => () => apiResponse(200, body);

interface Routes {
  previews?: Responder[];
  histories?: Responder[];
  details?: Responder[];
  comparisons?: Responder[];
  rollbackPreviews?: Responder[];
  rollbacks?: Responder[];
  publishes?: Responder[];
}

/**
 * Routes by URL and method. Each queue answers in order and repeats its last answer; a
 * request with no queue throws, so nothing is answered with the wrong body.
 */
function mockHistoryApi(routes: Routes) {
  const {
    previews = [ok(syntheticReleasePreview())],
    histories = [ok(syntheticReleaseHistory())],
    details = [ok(syntheticReleaseDetail())],
    comparisons = [ok(syntheticReleaseComparison())],
    rollbackPreviews = [ok(syntheticRollbackPreview())],
    rollbacks = [],
    publishes = [],
  } = routes;
  const counters = new Map<Responder[], number>();
  const answer = (queue: Responder[], what: string) => {
    if (queue.length === 0) throw new Error(`unexpected ${what}`);
    const index = counters.get(queue) ?? 0;
    counters.set(queue, index + 1);
    return queue[Math.min(index, queue.length - 1)]();
  };
  const fetchMock = vi.fn().mockImplementation(async (url: string, init?: RequestInit) => {
    const method = init?.method;
    if (method === 'GET' && PREVIEW_URL.test(url)) return answer(previews, 'preview GET');
    if (method === 'GET' && RELEASES_URL.test(url)) return answer(histories, 'history GET');
    if (method === 'GET' && DETAIL_URL.test(url)) return answer(details, 'detail GET');
    if (method === 'GET' && COMPARISON_URL.test(url)) return answer(comparisons, 'comparison GET');
    if (method === 'GET' && ROLLBACK_PREVIEW_URL.test(url)) return answer(rollbackPreviews, 'rollback preview GET');
    if (method === 'POST' && ROLLBACK_URL.test(url)) return answer(rollbacks, 'rollback POST');
    if (method === 'POST' && RELEASES_URL.test(url)) return answer(publishes, 'publish POST');
    throw new Error(`unexpected request ${method} ${url}`);
  });
  vi.stubGlobal('fetch', fetchMock);
  return fetchMock;
}

function calls(fetchMock: ReturnType<typeof vi.fn>, method: string, url: RegExp) {
  return fetchMock.mock.calls.filter(([calledUrl, init]) => url.test(String(calledUrl)) && (init as RequestInit).method === method);
}

async function openHistory() {
  await screen.findByTestId('release-next-version');
  fireEvent.click(screen.getByTestId('release-history-tab'));
  return screen.findByTestId('release-history-row-4');
}

function row(version: number) {
  return screen.getByTestId(`release-history-row-${version}`);
}

function rollBackButton(version: number) {
  return within(row(version)).getByRole('button', { name: 'Roll back to this version' });
}

async function openRollbackTo(version: number) {
  await openHistory();
  fireEvent.click(rollBackButton(version));
  return screen.findByTestId('rollback-lineage');
}

function confirmButton() {
  return screen.getByTestId('rollback-confirm-button');
}

function typeRollbackNote(note: string) {
  fireEvent.change(screen.getByTestId('rollback-note-input'), { target: { value: note } });
}

afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

describe('Release History: the list', () => {
  it('reads the history once when the tab opens and lists rows newest first with their lineage', async () => {
    const fetchMock = mockHistoryApi({});
    render(<ReviewAndPublishPage />);
    await screen.findByTestId('release-next-version');
    expect(calls(fetchMock, 'GET', RELEASES_URL)).toHaveLength(0);

    await openHistory();

    expect(screen.getByTestId('release-history-tab')).toHaveAttribute('aria-selected', 'true');
    expect(calls(fetchMock, 'GET', RELEASES_URL)).toHaveLength(1);
    const rows = screen.getAllByTestId(/^release-history-row-\d+$/);
    expect(rows.map((item) => item.dataset.testid)).toEqual([
      'release-history-row-4', 'release-history-row-3', 'release-history-row-2', 'release-history-row-1',
    ]);
    const v3 = row(3);
    expect(within(v3).getByRole('heading', { name: 'Graph Version 3' })).toBeInTheDocument();
    expect(v3).toHaveTextContent('Published by admin@example.com at 2026-09-23 12:00:00 UTC');
    expect(v3).toHaveTextContent('Effective from 2026-09-23 12:00:00 UTC to 2026-09-24 12:00:00 UTC');
    expect(v3).toHaveTextContent('Predecessor: Graph Version 2');
    expect(v3).toHaveTextContent('Changed roles: Architect, Builder');
    expect(v3).toHaveTextContent('Note: Release note for Graph Version 3');
    expect(within(v3).getByText('Restores Graph Version 1')).toBeInTheDocument();
    expect(row(1)).toHaveTextContent('Predecessor: none');
    expect(row(1)).toHaveTextContent('Restored as Graph Version 3');
    expect(row(4)).toHaveTextContent('to now');
  });

  it('marks the active row Active, with no rollback control; every other row has exactly one (C3)', async () => {
    mockHistoryApi({});
    render(<ReviewAndPublishPage />);
    await openHistory();

    expect(within(row(4)).getByText('Active')).toBeInTheDocument();
    expect(within(row(4)).queryByRole('button', { name: 'Roll back to this version' })).not.toBeInTheDocument();
    for (const version of [1, 2, 3]) {
      expect(within(row(version)).getAllByRole('button', { name: 'Roll back to this version' })).toHaveLength(1);
      expect(within(row(version)).queryByText('Active')).not.toBeInTheDocument();
    }
    expect(screen.getAllByRole('button', { name: 'Roll back to this version' })).toHaveLength(3);
    expect(screen.getAllByRole('button', { name: 'Inspect this version' })).toHaveLength(4);
    // The version is in the row's description, never in the accessible name.
    expect(rollBackButton(2)).toHaveAccessibleDescription('Graph Version 2');
  });

  it('renders history text as text, never as markup', async () => {
    const history = syntheticReleaseHistory();
    history.releases[1] = syntheticHistoryEntry(3, { restoredFrom: 1 }, { release_note: '<img src=x onerror="alert(1)">' });
    mockHistoryApi({ histories: [ok(history)] });
    const { container } = render(<ReviewAndPublishPage />);
    await openHistory();

    expect(row(3)).toHaveTextContent('Note: <img src=x onerror="alert(1)">');
    expect(container.querySelector('img')).toBeNull();
  });

  it('is reachable when the release preview fails (Correction 39)', async () => {
    mockHistoryApi({ previews: [() => apiResponse(500, { detail: 'boom' })] });
    render(<ReviewAndPublishPage />);
    await screen.findByText('Unable to load the release preview (500).');

    fireEvent.click(screen.getByTestId('release-history-tab'));

    expect(await screen.findByTestId('release-history-row-4')).toBeInTheDocument();
  });

  it('formats a zoneless and a Z spelling of one instant identically', () => {
    expect(formatInstant('2026-09-27T10:00:00')).toBe(formatInstant('2026-09-27T10:00:00Z'));
    expect(formatInstant('2026-09-27T10:00:00.5+02:00')).toBe('2026-09-27 08:00:00 UTC');
  });
});

describe('Release History: inspection', () => {
  it('shows the seven definitions, the evidence and the field diffs against active', async () => {
    const fetchMock = mockHistoryApi({});
    render(<ReviewAndPublishPage />);
    await openHistory();

    fireEvent.click(within(row(2)).getByRole('button', { name: 'Inspect this version' }));

    const detail = await screen.findByTestId('release-history-detail');
    expect(calls(fetchMock, 'GET', DETAIL_URL).map(([url]) => url)).toEqual([expect.stringMatching(/\/releases\/2$/)]);
    expect(calls(fetchMock, 'GET', COMPARISON_URL)).toHaveLength(1);
    expect(within(detail).getAllByTestId(/^release-definition-/)).toHaveLength(7);
    expect(within(detail).getByTestId('release-definition-architect')).toHaveTextContent('Architect: revision 200');
    expect(within(detail).getByTestId('release-evidence-501')).toHaveTextContent(
      'Architect, test case 101 (version 2) · Approval · no source · Approved',
    );
    expect(within(detail).getByTestId('release-evidence-502')).toHaveTextContent(
      'Builder, test case 202 (version 1) · Historical restore · from Graph Version 1 · Rejected',
    );
    const comparison = within(detail).getByTestId('release-comparison');
    const architect = within(comparison).getByRole('region', { name: 'Architect comparison' });
    const prompt = within(architect).getByRole('list', { name: 'prompt_text' });
    expect(within(prompt).getAllByRole('listitem').map((item) => [item.dataset.kind, item.textContent])).toEqual([
      ['same', '  Plan the deck.'],
      ['removed', '- Use four sections.'],
      ['added', '+ Use three sections.'],
      ['same', '  Cite sources.'],
    ]);
    expect(HISTORY_ACTIVE_ARCHITECT_PROMPT).toContain('four');
    expect(within(architect).getByTestId('release-comparison-diff-model.temperature')).toHaveTextContent('0.4 → 0.2');
    // Fix round 1 m6: every diff reads active → historical, not the other way.
    expect(within(comparison).getByRole('region', { name: 'Builder comparison' })).toHaveTextContent('model.max_tokens');
    expect(within(comparison).getByTestId('release-comparison-diff-model.max_tokens')).toHaveTextContent('8192 → 4096');
    expect(comparison).toHaveTextContent('Graph Version 2 against the active Graph Version 4');
    expect(within(comparison).getByRole('region', { name: 'Fixer comparison' })).toHaveTextContent('Same as active');
    expect(calls(fetchMock, 'POST', /./)).toHaveLength(0);
  });
});

describe('Release History: the rollback preview', () => {
  it('issues exactly one preview GET and zero POSTs, then shows lineage, mappings, draft effects and evidence', async () => {
    const fetchMock = mockHistoryApi({});
    render(<ReviewAndPublishPage />);

    const lineage = await openRollbackTo(2);

    expect(calls(fetchMock, 'GET', ROLLBACK_PREVIEW_URL).map(([url]) => url)).toEqual([expect.stringMatching(/\/releases\/2\/rollback-preview$/)]);
    expect(calls(fetchMock, 'POST', /./)).toHaveLength(0);
    expect(lineage).toHaveTextContent('Graph Version 5 will restore Graph Version 2 (predecessor Graph Version 4).');
    const preview = screen.getByTestId('rollback-preview');
    const mappings = within(preview).getByRole('list', { name: 'Mappings' });
    expect(within(mappings).getAllByRole('listitem').map((item) => item.textContent)).toEqual([
      'Architect: revision 200 (active: revision 400) · Draft: Reset to restored content',
      'Data Analyst: revision 201 (same as active) · Draft: Unchanged',
      'Builder: revision 202 (active: revision 402) · Draft: Pending edit kept',
      'Build Reviewer: revision 203 (same as active) · Draft: Unchanged',
      'Fixer: revision 204 (same as active) · Draft: Unchanged',
      'Fix Reviewer: revision 205 (same as active) · Draft: Unchanged',
      'Deck Reviewer: revision 206 (same as active) · Draft: Unchanged',
    ]);
    expect(preview).toHaveTextContent('Evidence links restored: 2');
    expect(screen.getByTestId('rollback-note-input')).toHaveValue('Roll back to Graph Version 2.');
    expect(screen.getByLabelText('Rollback note')).toBe(screen.getByTestId('rollback-note-input'));
    expect(confirmButton()).toHaveAccessibleName('Confirm rollback');
    expect(confirmButton()).toBeEnabled();
    expect(screen.getByTestId('rollback-cancel-button')).toHaveAccessibleName('Cancel rollback');
    expect(screen.queryByTestId('rollback-warnings')).not.toBeInTheDocument();
  });

  it('disables Confirm rollback on a blocked preview and lists its issues', async () => {
    mockHistoryApi({ rollbackPreviews: [ok(syntheticBlockedRollbackPreview())] });
    render(<ReviewAndPublishPage />);
    await openRollbackTo(2);

    const blocked = screen.getByTestId('rollback-blocked-panel');
    expect(blocked).toHaveTextContent("Graph Version 2 cannot be restored: it fails today's validation.");
    expect(within(blocked).getByRole('list', { name: 'Rollback issues' })).toHaveTextContent(
      'Builder: Endpoint name is not allowed by the current policy.',
    );
    expect(blocked).toHaveTextContent('The active release is unchanged.');
    expect(confirmButton()).toBeDisabled();
  });

  it('shows endpoint warnings without blocking (Correction 2)', async () => {
    mockHistoryApi({ rollbackPreviews: [ok(syntheticRollbackPreview({ warnings: [{
      field: 'definitions.fixer.candidate.model.endpoint_name',
      code: 'endpoint_unavailable',
      message: 'The serving endpoint is not available.',
    }] }))] });
    render(<ReviewAndPublishPage />);
    await openRollbackTo(2);

    expect(screen.getByTestId('rollback-warnings')).toHaveTextContent('Fixer: The serving endpoint is not available.');
    expect(screen.queryByTestId('rollback-blocked-panel')).not.toBeInTheDocument();
    expect(confirmButton()).toBeEnabled();
  });

  it.each(['', '   '])('disables Confirm rollback with the blank note %j', async (note) => {
    mockHistoryApi({});
    render(<ReviewAndPublishPage />);
    await openRollbackTo(2);

    typeRollbackNote(note);

    expect(confirmButton()).toBeDisabled();
  });

  it('cancels without any POST', async () => {
    const fetchMock = mockHistoryApi({});
    render(<ReviewAndPublishPage />);
    await openRollbackTo(2);

    fireEvent.click(screen.getByTestId('rollback-cancel-button'));

    expect(screen.queryByTestId('rollback-preview')).not.toBeInTheDocument();
    expect(calls(fetchMock, 'POST', /./)).toHaveLength(0);
  });
});

describe('Release History: confirming a rollback', () => {
  it('sends exactly one POST per click, with the preview lock and the note', async () => {
    let settle: (value: unknown) => void = () => {};
    const fetchMock = mockHistoryApi({
      rollbacks: [() => new Promise((resolve) => { settle = resolve; })],
      previews: [ok(syntheticReleasePreview()), ok(syntheticRolledBackReleasePreview())],
      histories: [ok(syntheticReleaseHistory()), ok(syntheticRestoredReleaseHistory())],
    });
    render(<ReviewAndPublishPage />);
    await openRollbackTo(2);
    const button = confirmButton();

    // Two clicks inside one act share one render: only the write gate stops the second.
    act(() => {
      fireEvent.click(button);
      fireEvent.click(button);
    });
    fireEvent.click(button);

    const posts = calls(fetchMock, 'POST', ROLLBACK_URL);
    expect(posts).toHaveLength(1);
    expect(posts[0][0]).toMatch(/\/releases\/2\/rollback$/);
    expect(posts[0][1].body).toBe('{"lock_version":3,"release_note":"Roll back to Graph Version 2."}');
    expect(button).toBeDisabled();
    expect(screen.getByTestId('rollback-note-input')).toHaveAttribute('readonly');
    await act(async () => settle(apiResponse(200, syntheticRollbackSuccess())));
    await screen.findByTestId('rollback-success-panel');
    expect(calls(fetchMock, 'POST', ROLLBACK_URL)).toHaveLength(1);
  });

  it('sends no POST when the reducer refuses the start, though the last render allowed it (m4)', async () => {
    // A controlled textarea's change re-renders synchronously, so the page cannot hold a
    // stale enabled Confirm; the hook's calls from one render's closures can.
    const fetchMock = mockHistoryApi({ rollbacks: [ok(syntheticRollbackSuccess())] });
    const { result } = renderHook(() => useReviewAndPublish());
    await waitFor(() => expect(result.current.state.status).toBe('ready'));
    await act(async () => { await result.current.openRollback(2); });
    expect(canConfirmRollback(result.current.state)).toBe(true);

    const { setRollbackNote, confirmRollback } = result.current;
    await act(async () => {
      setRollbackNote('  ');
      await confirmRollback();
    });

    expect(result.current.state.rollback.status).toBe('confirming');
    expect(calls(fetchMock, 'POST', /./)).toHaveLength(0);

    // The same two calls with a real note do send (the test can see a POST).
    const later = result.current;
    await act(async () => {
      later.setRollbackNote('A real note');
      await later.confirmRollback();
    });
    expect(calls(fetchMock, 'POST', ROLLBACK_URL)).toHaveLength(1);
    expect(calls(fetchMock, 'POST', ROLLBACK_URL)[0][1].body).toBe('{"lock_version":3,"release_note":"A real note"}');
  });

  it('shows the success, then refetches the history and the release preview exactly once each', async () => {
    const fetchMock = mockHistoryApi({
      rollbacks: [ok(syntheticRollbackSuccess())],
      previews: [ok(syntheticReleasePreview()), ok(syntheticRolledBackReleasePreview())],
      histories: [ok(syntheticReleaseHistory()), ok(syntheticRestoredReleaseHistory())],
    });
    render(<ReviewAndPublishPage />);
    await openRollbackTo(2);

    fireEvent.click(confirmButton());

    const success = await screen.findByTestId('rollback-success-panel');
    expect(success).toHaveTextContent('Graph Version 5 restores Graph Version 2');
    expect(success).toHaveTextContent('The shared draft is now based on Graph Version 5');
    await screen.findByTestId('release-history-row-5');
    await screen.findByText('Draft base: Graph Version 5');
    expect(screen.getAllByTestId(/^release-history-row-\d+$/)[0].dataset.testid).toBe('release-history-row-5');
    expect(within(row(5)).getByText('Active')).toBeInTheDocument();
    expect(within(row(5)).getByText('Restores Graph Version 2')).toBeInTheDocument();
    expect(screen.queryByTestId('rollback-preview')).not.toBeInTheDocument();
    await act(async () => {});
    expect(calls(fetchMock, 'GET', RELEASES_URL)).toHaveLength(2);
    expect(calls(fetchMock, 'GET', PREVIEW_URL)).toHaveLength(2);
    expect(calls(fetchMock, 'POST', ROLLBACK_URL)).toHaveLength(1);
  });

  it('clears a shown inspection once the rollback restores (fix round 1 m5)', async () => {
    mockHistoryApi({
      rollbacks: [ok(syntheticRollbackSuccess())],
      previews: [ok(syntheticReleasePreview()), ok(syntheticRolledBackReleasePreview())],
      histories: [ok(syntheticReleaseHistory()), ok(syntheticRestoredReleaseHistory())],
    });
    render(<ReviewAndPublishPage />);
    await openHistory();
    fireEvent.click(within(row(2)).getByRole('button', { name: 'Inspect this version' }));
    expect(await screen.findByTestId('release-comparison')).toHaveTextContent('against the active Graph Version 4');
    fireEvent.click(rollBackButton(2));
    await screen.findByTestId('rollback-lineage');

    fireEvent.click(confirmButton());

    await screen.findByTestId('rollback-success-panel');
    await screen.findByTestId('release-history-row-5');
    expect(screen.queryByTestId('release-history-detail')).not.toBeInTheDocument();
    expect(screen.queryByTestId('release-comparison')).not.toBeInTheDocument();
  });

  it('on a stale 409 names the current lock and active version, keeps the note, and reloads only on request', async () => {
    const fetchMock = mockHistoryApi({
      rollbacks: [() => apiResponse(409, syntheticStaleRollback())],
      rollbackPreviews: [ok(syntheticRollbackPreview()), ok(syntheticRollbackPreview({ lock_version: 5 }))],
    });
    render(<ReviewAndPublishPage />);
    await openRollbackTo(2);
    typeRollbackNote('Emergency: v4 broke outlines');

    fireEvent.click(confirmButton());

    const alert = await screen.findByTestId('rollback-stale-alert');
    expect(alert).toHaveTextContent('it is now at lock version 5');
    expect(alert).toHaveTextContent('Graph Version 4 is active');
    expect(screen.getByTestId('rollback-note-input')).toHaveValue('Emergency: v4 broke outlines');
    expect(confirmButton()).toBeDisabled();
    await act(async () => {});
    expect(calls(fetchMock, 'POST', ROLLBACK_URL)).toHaveLength(1);
    expect(calls(fetchMock, 'GET', ROLLBACK_PREVIEW_URL)).toHaveLength(1);

    // Fix round 1 m4: its own name, never the page's `Reload preview`.
    expect(within(alert).queryByRole('button', { name: 'Reload preview' })).not.toBeInTheDocument();
    fireEvent.click(within(alert).getByRole('button', { name: 'Reload rollback preview' }));

    await screen.findByText('Graph Version 5 will restore Graph Version 2 (predecessor Graph Version 4).');
    await act(async () => {});
    expect(screen.queryByTestId('rollback-stale-alert')).not.toBeInTheDocument();
    expect(calls(fetchMock, 'GET', ROLLBACK_PREVIEW_URL)).toHaveLength(2);
    expect(calls(fetchMock, 'POST', ROLLBACK_URL)).toHaveLength(1);
    expect(screen.getByTestId('rollback-note-input')).toHaveValue('Emergency: v4 broke outlines');
    expect(confirmButton()).toBeEnabled();
  });

  it('lists the issues of a 422 rollback_incompatible and sends nothing further', async () => {
    const fetchMock = mockHistoryApi({ rollbacks: [() => apiResponse(422, syntheticRollbackIncompatible())] });
    render(<ReviewAndPublishPage />);
    await openRollbackTo(2);

    fireEvent.click(confirmButton());

    const blocked = await screen.findByTestId('rollback-blocked-panel');
    expect(blocked).toHaveTextContent('Builder: Endpoint name is not allowed by the current policy.');
    expect(blocked).toHaveTextContent('The active release is unchanged.');
    expect(confirmButton()).toBeDisabled();
    await act(async () => {});
    expect(calls(fetchMock, 'POST', ROLLBACK_URL)).toHaveLength(1);
  });

  it('shows a 422 invalid_rollback note error beside the textarea, by code', async () => {
    mockHistoryApi({ rollbacks: [() => apiResponse(422, syntheticRollbackInvalid())] });
    render(<ReviewAndPublishPage />);
    await openRollbackTo(2);
    // JavaScript trims this, Python's str.strip removes it: only the server sees it blank.
    typeRollbackNote('\u001f');

    fireEvent.click(confirmButton());

    const error = await screen.findByText('Enter a rollback note.');
    expect(error.id).toBe('rollback-note-error');
    const textarea = screen.getByTestId('rollback-note-input');
    expect(textarea).toHaveAttribute('aria-invalid', 'true');
    expect(textarea).toHaveAccessibleDescription(expect.stringContaining('Enter a rollback note.'));
    expect(confirmButton()).toBeDisabled();

    typeRollbackNote('A real note');
    expect(screen.queryByText('Enter a rollback note.')).not.toBeInTheDocument();
    expect(confirmButton()).toBeEnabled();
  });
});

describe('Release History: the one write gate across publish and rollback (Correction 39)', () => {
  it('refuses a publish while a rollback is in flight', async () => {
    const fetchMock = mockHistoryApi({
      rollbacks: [() => new Promise(() => {})],
      publishes: [ok(syntheticPublishSuccess())],
    });
    render(<ReviewAndPublishPage />);
    await openRollbackTo(2);
    fireEvent.change(screen.getByTestId('release-note-input'), { target: { value: 'Tighten the outline' } });
    expect(screen.getByTestId('release-publish-button')).toBeEnabled();

    act(() => {
      fireEvent.click(confirmButton());
      fireEvent.click(screen.getByTestId('release-publish-button'));
    });

    expect(calls(fetchMock, 'POST', ROLLBACK_URL)).toHaveLength(1);
    expect(calls(fetchMock, 'POST', RELEASES_URL)).toHaveLength(0);
    expect(screen.getByTestId('release-publish-button')).toBeDisabled();
  });

  it('refuses to open or confirm a rollback while a publish is in flight', async () => {
    const fetchMock = mockHistoryApi({ publishes: [() => new Promise(() => {})] });
    render(<ReviewAndPublishPage />);
    await openRollbackTo(3);
    expect(confirmButton()).toBeEnabled();
    fireEvent.change(screen.getByTestId('release-note-input'), { target: { value: 'Tighten the outline' } });

    act(() => {
      fireEvent.click(screen.getByTestId('release-publish-button'));
      fireEvent.click(confirmButton());
      fireEvent.click(rollBackButton(2));
    });

    expect(calls(fetchMock, 'POST', RELEASES_URL)).toHaveLength(1);
    expect(calls(fetchMock, 'POST', ROLLBACK_URL)).toHaveLength(0);
    expect(calls(fetchMock, 'GET', ROLLBACK_PREVIEW_URL)).toHaveLength(1);
    expect(confirmButton()).toBeDisabled();
  });

  it('refetches a loaded history once after a publish, so it lists the new Graph Version', async () => {
    const fetchMock = mockHistoryApi({
      publishes: [ok(syntheticPublishSuccess())],
      previews: [ok(syntheticReleasePreview()), ok(syntheticPublishedReleasePreview())],
    });
    render(<ReviewAndPublishPage />);
    await openHistory();
    fireEvent.change(screen.getByTestId('release-note-input'), { target: { value: 'Tighten the outline' } });

    fireEvent.click(screen.getByTestId('release-publish-button'));

    await screen.findByTestId('release-success-panel');
    await act(async () => {});
    expect(calls(fetchMock, 'GET', RELEASES_URL)).toHaveLength(2);
    expect(calls(fetchMock, 'GET', PREVIEW_URL)).toHaveLength(2);
  });
});
