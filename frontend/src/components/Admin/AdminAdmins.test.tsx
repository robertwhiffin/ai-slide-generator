/**
 * @vitest-environment jsdom
 *
 * Task 6 (admin permissions): the Admins tab.
 *
 * One line per identity (user or group), a badge per source (`CAN_MANAGE on app`,
 * `Added in Tellr`), a lock instead of Remove for CAN_MANAGE-only identities, a
 * green/amber sync status line, and a debounced user/group picker that adds a
 * `manual` admin. Contract as built: task-6-addendum.md; copy: global-constraints.md.
 *
 * SABOTAGE (each should turn the named test RED):
 *   - render one line per (identity, source) instead of per identity  -> "renders one line ..."
 *   - show Remove for every row / drop the lock title                  -> "renders one line ..."
 *   - show "added by" whenever added_by is set (CAN_MANAGE-only has
 *     added_by = "can_manage_sync")                                    -> "renders one line ..."
 *   - state = last_error ? warn : ok (ignore a null last_success_at)   -> "amber ... never succeeded" (null error case)
 *   - state = last_success_at ? ok : warn (ignore last_error)          -> "amber ... after earlier successes"
 *   - round/miscompute the age, or drop "just now" / "N h ago"         -> the age cases
 *   - search on every keystroke (no debounce) / debounce != 300 ms     -> "search then Add admin ..."
 *   - post display_name for USER rows                                  -> "search then Add admin ..."
 *   - post user_name ?? display_name for GROUP rows with a user_name   -> "adding a group ..."
 *   - leave Add admin enabled before a pick                            -> "Add admin is disabled ..."
 *   - remove by identity_id / row index instead of manual_permission_id -> "Remove calls removeAdmin ..."
 *   - skip the reload after add / remove                               -> those tests
 *   - swallow the remove error, or drop the line optimistically        -> "a failed remove ..."
 *   - toast String(err.detail) / the raw JSON body for a 422 list      -> "a 422 with a list detail ..."
 */
import { act, cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { AppAdminEntry, AppAdminsResponse, AdminSyncStatus } from '../../api/admin';
import { AdminAdmins } from './AdminAdmins';

const listAdmins = vi.fn();
const addAdmin = vi.fn();
const removeAdmin = vi.fn();
const searchIdentities = vi.fn();
const showToast = vi.fn();

vi.mock('../../api/admin', () => ({
  adminApi: {
    listAdmins: (...args: unknown[]) => listAdmins(...args),
    addAdmin: (...args: unknown[]) => addAdmin(...args),
    removeAdmin: (...args: unknown[]) => removeAdmin(...args),
    getJudgeBackend: vi.fn(),
    setJudgeBackend: vi.fn(),
  },
}));

vi.mock('../../api/config', () => ({
  configApi: {
    searchIdentities: (...args: unknown[]) => searchIdentities(...args),
  },
}));

vi.mock('../../contexts/ToastContext', () => ({
  useToast: () => ({ showToast }),
}));

// ---------------------------------------------------------------------------
// Fixtures
// ---------------------------------------------------------------------------

const NOW = new Date('2026-11-02T10:00:00Z');
const SEARCH_PLACEHOLDER = 'Search users or groups to make admin…';
const LOCK_TITLE = "Change this in the app's Permissions in Databricks";
const AMBER_COPY =
  "Tellr can't read this app's permissions. Run tellr.update to grant the app access.";
const PERMISSION_DENIED =
  'PermissionDenied: the caller does not have permission to call ruleSets/get';

const sam: AppAdminEntry = {
  identity_type: 'USER',
  identity_name: 'sam@x.com',
  identity_id: 'u-sam',
  sources: ['can_manage_sync', 'manual'],
  manual_permission_id: 42,
  added_by: 'priya',
  added_at: '2026-11-01T10:00:00Z',
};

// CAN_MANAGE-only: the backend sets added_by to the sync's marker. It must not be
// rendered as "added by can_manage_sync".
const robert: AppAdminEntry = {
  identity_type: 'USER',
  identity_name: 'robert@x.com',
  identity_id: null,
  sources: ['can_manage_sync'],
  manual_permission_id: null,
  added_by: 'can_manage_sync',
  added_at: '2026-11-02T09:00:00+00:00',
};

const team: AppAdminEntry = {
  identity_type: 'GROUP',
  identity_name: 'Team',
  identity_id: 'g-team',
  sources: ['manual'],
  manual_permission_id: 43,
  added_by: 'robert@x.com',
  added_at: '2026-11-02T08:00:00+00:00',
};

const minutesBefore = (minutes: number): string =>
  new Date(NOW.getTime() - minutes * 60_000).toISOString();

const greenSync: AdminSyncStatus = {
  last_attempt_at: minutesBefore(5),
  last_success_at: minutesBefore(5),
  last_error: null,
};

function response(
  admins: AppAdminEntry[] = [sam, robert, team],
  sync: AdminSyncStatus = greenSync,
): AppAdminsResponse {
  return { admins, sync };
}

const priyaIdentity = {
  id: 'u1',
  display_name: 'Priya P',
  user_name: 'priya@example.com',
  type: 'USER' as const,
};

// Fake only setTimeout/clearTimeout, and only around the debounce: RTL's findBy/waitFor
// drain on a real setTimeout. shouldClearNativeTimers lets the component's effect
// cleanup clear a timer it armed (on mount) before the fake clock was installed.
const DEBOUNCE_TIMERS = {
  toFake: ['setTimeout', 'clearTimeout'] as ('setTimeout' | 'clearTimeout')[],
  shouldClearNativeTimers: true,
};

const rowTestId = (entry: Pick<AppAdminEntry, 'identity_type' | 'identity_name'>) =>
  `admin-row-${entry.identity_type}-${entry.identity_name}`;

async function findRow(entry: Pick<AppAdminEntry, 'identity_type' | 'identity_name'>) {
  return screen.findByTestId(rowTestId(entry));
}

/**
 * Type into the picker, run the 300 ms debounce on fake timers, then return to real
 * timers so the rest of the test can use findBy/waitFor normally.
 */
async function typeAndRunDebounce(query: string) {
  const input = screen.getByPlaceholderText(SEARCH_PLACEHOLDER);
  vi.useFakeTimers(DEBOUNCE_TIMERS);
  try {
    fireEvent.change(input, { target: { value: query } });
    await act(async () => {
      await vi.advanceTimersByTimeAsync(300);
    });
  } finally {
    vi.useRealTimers();
  }
}

/** The calls to showToast whose type is 'error'. */
function errorToasts(): unknown[][] {
  return showToast.mock.calls.filter((call) => call[1] === 'error');
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe('AdminAdmins', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    listAdmins.mockResolvedValue(response());
    addAdmin.mockResolvedValue({ permission_id: 99 });
    removeAdmin.mockResolvedValue(undefined);
    searchIdentities.mockResolvedValue({ identities: [priyaIdentity], total: 1 });
  });

  afterEach(() => {
    cleanup();
    vi.useRealTimers();
    vi.unstubAllGlobals();
  });

  it('renders one line per identity with a badge per source', async () => {
    render(<AdminAdmins />);

    const samRow = await findRow(sam);
    const robertRow = await findRow(robert);
    const teamRow = await findRow(team);

    // One line per identity: Sam's two sources do not make two lines.
    expect(document.querySelectorAll('[data-testid^="admin-row-"]')).toHaveLength(3);

    // Sam: both sources -> both badges, and Remove (the manual part).
    expect(within(samRow).getByText('CAN_MANAGE on app')).toBeInTheDocument();
    expect(within(samRow).getByText('Added in Tellr')).toBeInTheDocument();
    expect(within(samRow).getByRole('button', { name: 'Remove sam@x.com' })).toBeInTheDocument();
    expect(samRow).toHaveTextContent(/added by priya · /);
    // Sam has a manual row, so Remove replaces the lock.
    expect(samRow.querySelector(`[title="${LOCK_TITLE}"]`)).toBeNull();

    // Robert: CAN_MANAGE only -> one badge, a lock with the tooltip, no Remove.
    expect(within(robertRow).getByText('CAN_MANAGE on app')).toBeInTheDocument();
    expect(within(robertRow).queryByText('Added in Tellr')).toBeNull();
    expect(within(robertRow).queryByRole('button', { name: /remove/i })).toBeNull();
    expect(robertRow.querySelector(`[title="${LOCK_TITLE}"]`)).not.toBeNull();
    // "added by …" is only for manual entries (manual_permission_id != null).
    expect(robertRow).not.toHaveTextContent(/added by/i);
    expect(robertRow).not.toHaveTextContent('can_manage_sync');

    // Team: a group, manual only.
    expect(within(teamRow).getByText(/\bgroup\b/)).toBeInTheDocument();
    expect(within(teamRow).getByText('Added in Tellr')).toBeInTheDocument();
    expect(within(teamRow).queryByText('CAN_MANAGE on app')).toBeNull();
    expect(within(teamRow).getByRole('button', { name: 'Remove Team' })).toBeInTheDocument();
    // A user line carries no "group" subtitle.
    expect(samRow).not.toHaveTextContent(/\bgroup\b/);
  });

  describe('sync status line', () => {
    beforeEach(() => {
      // Fake only Date: the age is computed from "now", and real timers keep
      // findBy/waitFor working.
      vi.useFakeTimers({ toFake: ['Date'] });
      vi.setSystemTime(NOW);
    });

    it('shows green status after a successful sync', async () => {
      render(<AdminAdmins />);

      const status = await screen.findByTestId('admin-sync-status');
      await waitFor(() => expect(status).toHaveAttribute('data-state', 'ok'));
      expect(status).toHaveTextContent('Synced from app permissions 5 min ago');
      expect(status).not.toHaveTextContent(AMBER_COPY);
    });

    it.each([
      { label: 'under one minute', ageMs: 30_000, text: 'Synced from app permissions just now' },
      { label: 'exactly one minute', ageMs: 60_000, text: 'Synced from app permissions 1 min ago' },
      { label: 'exactly 60 minutes', ageMs: 60 * 60_000, text: 'Synced from app permissions 1 h ago' },
      { label: '125 minutes', ageMs: 125 * 60_000, text: 'Synced from app permissions 2 h ago' },
    ])('formats the age $label as "$text"', async ({ ageMs, text }) => {
      const at = new Date(NOW.getTime() - ageMs).toISOString();
      listAdmins.mockResolvedValue(
        response(undefined, { last_attempt_at: at, last_success_at: at, last_error: null }),
      );
      render(<AdminAdmins />);

      const status = await screen.findByTestId('admin-sync-status');
      await waitFor(() => expect(status).toHaveAttribute('data-state', 'ok'));
      expect(status).toHaveTextContent(text);
    });

    it('shows amber status when no sync ever succeeded', async () => {
      listAdmins.mockResolvedValue(
        response([sam, team], {
          last_attempt_at: minutesBefore(1),
          last_success_at: null,
          last_error: PERMISSION_DENIED,
        }),
      );
      render(<AdminAdmins />);

      const status = await screen.findByTestId('admin-sync-status');
      await waitFor(() => expect(status).toHaveAttribute('data-state', 'warn'));
      expect(status).toHaveTextContent(AMBER_COPY);
      expect(status).toHaveTextContent(PERMISSION_DENIED);
    });

    it('shows amber status before the first sync has run (no success, no error)', async () => {
      // Spec §5: amber when "no sync has ever succeeded" — not only when an error is stored.
      listAdmins.mockResolvedValue(
        response([sam], { last_attempt_at: null, last_success_at: null, last_error: null }),
      );
      render(<AdminAdmins />);

      const status = await screen.findByTestId('admin-sync-status');
      await waitFor(() => expect(status).toHaveAttribute('data-state', 'warn'));
      expect(status).toHaveTextContent(AMBER_COPY);
    });

    it('shows amber status when the last read failed after earlier successes', async () => {
      listAdmins.mockResolvedValue(
        response(undefined, {
          last_attempt_at: minutesBefore(1),
          last_success_at: minutesBefore(60),
          last_error: PERMISSION_DENIED,
        }),
      );
      render(<AdminAdmins />);

      const status = await screen.findByTestId('admin-sync-status');
      await waitFor(() => expect(status).toHaveAttribute('data-state', 'warn'));
      expect(status).toHaveTextContent(AMBER_COPY);
      expect(status).toHaveTextContent(PERMISSION_DENIED);
    });
  });

  it('search then Add admin posts the USER email, not the display name', async () => {
    render(<AdminAdmins />);
    await findRow(sam);
    const input = screen.getByPlaceholderText(SEARCH_PLACEHOLDER);

    vi.useFakeTimers(DEBOUNCE_TIMERS);
    try {
      // Three quick keystrokes collapse into one debounced search.
      fireEvent.change(input, { target: { value: 'p' } });
      fireEvent.change(input, { target: { value: 'pr' } });
      fireEvent.change(input, { target: { value: 'pri' } });
      expect(searchIdentities).not.toHaveBeenCalled();

      await act(async () => {
        await vi.advanceTimersByTimeAsync(299);
      });
      expect(searchIdentities).not.toHaveBeenCalled();

      await act(async () => {
        await vi.advanceTimersByTimeAsync(1);
      });
      expect(searchIdentities).toHaveBeenCalledTimes(1);
      expect(searchIdentities.mock.calls[0][0]).toBe('pri');
    } finally {
      vi.useRealTimers();
    }

    fireEvent.click(await screen.findByText(/Priya P/));

    const listCallsBeforeAdd = listAdmins.mock.calls.length;
    listAdmins.mockResolvedValue(
      response([
        sam,
        robert,
        team,
        {
          identity_type: 'USER',
          identity_name: 'priya@example.com',
          identity_id: 'u1',
          sources: ['manual'],
          manual_permission_id: 99,
          added_by: 'admin@x.com',
          added_at: NOW.toISOString(),
        },
      ]),
    );

    const addButton = screen.getByRole('button', { name: 'Add admin' });
    await waitFor(() => expect(addButton).toBeEnabled());
    fireEvent.click(addButton);

    await waitFor(() => expect(addAdmin).toHaveBeenCalledTimes(1));
    expect(addAdmin).toHaveBeenCalledWith({
      identity_type: 'USER',
      identity_name: 'priya@example.com',
      identity_id: 'u1',
    });

    // Then the list reloads (after the add, not before it).
    await waitFor(() => expect(listAdmins.mock.calls.length).toBeGreaterThan(listCallsBeforeAdd));
    expect(listAdmins.mock.invocationCallOrder.at(-1)!).toBeGreaterThan(
      addAdmin.mock.invocationCallOrder[0],
    );
    expect(await screen.findByTestId('admin-row-USER-priya@example.com')).toBeInTheDocument();
  });

  it('Add admin is disabled until a result is picked', async () => {
    render(<AdminAdmins />);
    await findRow(sam);

    const addButton = screen.getByRole('button', { name: 'Add admin' });
    expect(addButton).toBeDisabled();

    await typeAndRunDebounce('pri');
    const result = await screen.findByText(/Priya P/);
    // Typing and seeing results is not a pick.
    expect(screen.getByRole('button', { name: 'Add admin' })).toBeDisabled();
    fireEvent.click(screen.getByRole('button', { name: 'Add admin' }));
    expect(addAdmin).not.toHaveBeenCalled();

    fireEvent.click(result);
    await waitFor(() => expect(screen.getByRole('button', { name: 'Add admin' })).toBeEnabled());
  });

  it('adding a group posts its display name', async () => {
    searchIdentities.mockResolvedValue({
      identities: [
        // A user_name on a GROUP result must not be used: groups are matched by
        // display name (the permission list holds group display names).
        { id: 'g1', display_name: 'Data Eng', user_name: 'data-eng-alias', type: 'GROUP' },
      ],
      total: 1,
    });
    render(<AdminAdmins />);
    await findRow(sam);

    await typeAndRunDebounce('data');
    expect(searchIdentities.mock.calls[0][0]).toBe('data');
    fireEvent.click(await screen.findByText(/Data Eng/));

    const addButton = screen.getByRole('button', { name: 'Add admin' });
    await waitFor(() => expect(addButton).toBeEnabled());
    fireEvent.click(addButton);

    await waitFor(() =>
      expect(addAdmin).toHaveBeenCalledWith({
        identity_type: 'GROUP',
        identity_name: 'Data Eng',
        identity_id: 'g1',
      }),
    );
  });

  it('Remove calls removeAdmin with the manual id and reloads', async () => {
    render(<AdminAdmins />);
    const samRow = await findRow(sam);
    const listCallsBeforeRemove = listAdmins.mock.calls.length;
    listAdmins.mockResolvedValue(
      response([
        { ...sam, sources: ['can_manage_sync'], manual_permission_id: null, added_by: 'can_manage_sync' },
        robert,
        team,
      ]),
    );

    fireEvent.click(within(samRow).getByRole('button', { name: 'Remove sam@x.com' }));

    await waitFor(() => expect(removeAdmin).toHaveBeenCalledTimes(1));
    expect(removeAdmin).toHaveBeenCalledWith(42);
    await waitFor(() =>
      expect(listAdmins.mock.calls.length).toBeGreaterThan(listCallsBeforeRemove),
    );
    expect(listAdmins.mock.invocationCallOrder.at(-1)!).toBeGreaterThan(
      removeAdmin.mock.invocationCallOrder[0],
    );
    // The reloaded list is what is shown: Sam keeps only the CAN_MANAGE badge.
    await waitFor(() =>
      expect(within(screen.getByTestId(rowTestId(sam))).queryByText('Added in Tellr')).toBeNull(),
    );
  });

  it('a failed remove shows an error toast and keeps the line', async () => {
    const detail =
      "This admin comes from CAN_MANAGE on the app. Change it in the app's Permissions in Databricks.";
    removeAdmin.mockRejectedValue(new Error(detail));
    render(<AdminAdmins />);
    const samRow = await findRow(sam);

    fireEvent.click(within(samRow).getByRole('button', { name: 'Remove sam@x.com' }));

    await waitFor(() => expect(errorToasts()).toHaveLength(1));
    expect(String(errorToasts()[0][0])).toContain(detail);
    const row = screen.getByTestId(rowTestId(sam));
    expect(within(row).getByText('Added in Tellr')).toBeInTheDocument();
    expect(within(row).getByRole('button', { name: 'Remove sam@x.com' })).toBeInTheDocument();
  });

  it('a 422 with a list detail from addAdmin surfaces a readable error toast', async () => {
    // Drive the REAL adminApi.addAdmin against a stubbed fetch, so this pins the
    // whole chain (admin.ts error parsing + the component's toast), not just a mock.
    const actual = await vi.importActual<typeof import('../../api/admin')>('../../api/admin');
    addAdmin.mockImplementation((body: unknown) =>
      actual.adminApi.addAdmin(body as Parameters<typeof actual.adminApi.addAdmin>[0]),
    );
    const fetchMock = vi.fn(
      async () =>
        new Response(
          JSON.stringify({
            detail: [
              {
                type: 'string_too_long',
                loc: ['body', 'identity_name'],
                msg: 'String should have at most 255 characters',
                input: 'x'.repeat(256),
                ctx: { max_length: 255 },
              },
            ],
          }),
          { status: 422, headers: { 'Content-Type': 'application/json' } },
        ),
    );
    vi.stubGlobal('fetch', fetchMock);

    render(<AdminAdmins />);
    await findRow(sam);
    await typeAndRunDebounce('pri');
    fireEvent.click(await screen.findByText(/Priya P/));
    const addButton = screen.getByRole('button', { name: 'Add admin' });
    await waitFor(() => expect(addButton).toBeEnabled());
    fireEvent.click(addButton);

    await waitFor(() => expect(errorToasts()).toHaveLength(1));
    expect(fetchMock).toHaveBeenCalled();
    const message = String(errorToasts()[0][0]);
    expect(message.trim()).not.toBe('');
    expect(message).not.toContain('[object Object]');
    // Not the raw JSON body either.
    expect(message).not.toContain('"detail"');
    expect(message).not.toContain('string_too_long');
    // Either Pydantic's message or a status fallback such as "Request rejected (422)".
    expect(message).toMatch(/String should have at most 255 characters|422/);
  });
});
