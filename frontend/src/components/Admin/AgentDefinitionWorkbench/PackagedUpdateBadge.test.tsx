import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { syntheticRollbackSuccess } from '../../../../tests/fixtures/mocks';
import { PackagedUpdateBadge } from './PackagedUpdateBadge';

const STATUS_SUFFIX = '/api/admin/graph-shipping/packaged-update';
const ADOPT_SUFFIX = '/api/admin/graph-shipping/packaged-update/adopt';
const TITLE = 'A newer shipped version is available';
const CONFIRM = 'Publish the shipped version as the next Graph Version? Pending draft edits are kept.';
const STALE = 'The draft changed since you loaded it. Reload and try again.';

const ALL_UNCHANGED = Object.fromEntries(
  ['architect', 'data_analyst', 'builder', 'build_reviewer', 'fixer', 'fix_reviewer', 'deck_reviewer']
    .map((key) => [key, 'unchanged']),
);

function status(overrides: Record<string, unknown> = {}) {
  return {
    available: true,
    differing_agents: ['architect', 'builder'],
    blocked_reason: null,
    hand_edited_agents: [],
    validation_issues: [],
    diffs: [
      { agent_key: 'architect', field_diffs: [{ field: 'model.temperature', published: 0.1, candidate: 0.2 }] },
      { agent_key: 'builder', field_diffs: [{ field: 'model.max_tokens', published: 100, candidate: 200 }] },
    ],
    active_version_number: 3,
    lock_version: 7,
    ...overrides,
  };
}

function adoptSuccess() {
  return {
    release: syntheticRollbackSuccess().release,
    changed_agent_keys: ['architect', 'builder'],
    draft_effect: ALL_UNCHANGED,
  };
}

function reply(statusCode: number, body: unknown) {
  return {
    ok: statusCode >= 200 && statusCode < 300,
    status: statusCode,
    statusText: statusCode === 409 ? 'Conflict' : 'OK',
    json: vi.fn().mockResolvedValue(body),
  };
}

function stubFetch(statusReply: unknown, adoptReply?: unknown) {
  const mock = vi.fn().mockImplementation(async (url: string) => {
    if (String(url).endsWith(ADOPT_SUFFIX)) return adoptReply ?? reply(200, adoptSuccess());
    if (String(url).endsWith(STATUS_SUFFIX)) {
      if (statusReply instanceof Error) throw statusReply;
      return statusReply;
    }
    throw new Error(`unexpected request ${url}`);
  });
  vi.stubGlobal('fetch', mock);
  return mock;
}

function adoptCalls(mock: ReturnType<typeof vi.fn>) {
  return mock.mock.calls.filter(([url]) => String(url).endsWith(ADOPT_SUFFIX));
}

afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

describe('PackagedUpdateBadge', () => {
  it('renders nothing when no shipped update is available', async () => {
    const mock = stubFetch(reply(200, status({
      available: false, differing_agents: [], diffs: [],
    })));
    const { container } = render(<PackagedUpdateBadge onAdopted={vi.fn()} />);

    await waitFor(() => expect(mock).toHaveBeenCalled());
    expect(mock.mock.calls[0][0]).toMatch(/\/api\/admin\/graph-shipping\/packaged-update$/);
    expect(screen.queryByText(TITLE)).not.toBeInTheDocument();
    expect(container).toBeEmptyDOMElement();
  });

  it.each([
    ['a 500', () => reply(500, null)],
    ['a network error', () => new Error('network down')],
    ['an unparseable body', () => reply(200, { nonsense: true })],
    ['a body that is not JSON', () => ({ ...reply(200, null), json: vi.fn().mockRejectedValue(new Error('bad json')) })],
  ])('renders nothing and no error banner on %s', async (_label, make) => {
    const mock = stubFetch(make());
    const { container } = render(<PackagedUpdateBadge onAdopted={vi.fn()} />);

    await waitFor(() => expect(mock).toHaveBeenCalled());
    await new Promise((resolve) => setTimeout(resolve, 0));
    expect(screen.queryByText(TITLE)).not.toBeInTheDocument();
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
    expect(container).toBeEmptyDOMElement();
  });

  it('shows the title and the retried-on-restart copy when nothing blocks the update', async () => {
    stubFetch(reply(200, status()));
    render(<PackagedUpdateBadge onAdopted={vi.fn()} />);

    expect(await screen.findByText(TITLE)).toBeInTheDocument();
    expect(screen.getByText('It was not applied at startup; it will be retried on the next restart.')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Adopt shipped version' })).toBeEnabled();
  });

  it('lists the hand-edited agents by display name, comma separated', async () => {
    stubFetch(reply(200, status({
      blocked_reason: 'hand_edited',
      hand_edited_agents: ['architect', 'build_reviewer'],
    })));
    render(<PackagedUpdateBadge onAdopted={vi.fn()} />);

    expect(await screen.findByText(
      'Not applied automatically because these agents were edited here: Architect, Build Reviewer.',
    )).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Adopt shipped version' })).toBeEnabled();
  });

  it('explains a rollback block', async () => {
    stubFetch(reply(200, status({ blocked_reason: 'rollback' })));
    render(<PackagedUpdateBadge onAdopted={vi.fn()} />);

    expect(await screen.findByText(
      'Not applied automatically because the live release is a rollback.',
    )).toBeInTheDocument();
  });

  it('explains an invalid shipped version and disables Adopt', async () => {
    stubFetch(reply(200, status({
      blocked_reason: 'invalid',
      validation_issues: [{ field: 'architect.prompt_text', code: 'x', message: 'bad' }],
    })));
    render(<PackagedUpdateBadge onAdopted={vi.fn()} />);

    expect(await screen.findByText(
      'The shipped version failed validation and was not applied.',
    )).toBeInTheDocument();
    const adopt = screen.getByRole('button', { name: 'Adopt shipped version' });
    expect(adopt).toBeDisabled();
    const confirm = vi.spyOn(window, 'confirm').mockReturnValue(true);
    fireEvent.click(adopt);
    expect(confirm).not.toHaveBeenCalled();
  });

  it('toggles one field diff per differing agent under Review changes', async () => {
    stubFetch(reply(200, status()));
    render(<PackagedUpdateBadge onAdopted={vi.fn()} />);
    await screen.findByText(TITLE);

    expect(screen.queryByTestId('packaged-diff-model.temperature')).not.toBeInTheDocument();
    expect(screen.queryByTestId('packaged-diff-model.max_tokens')).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: 'Review changes' }));
    expect(screen.getByTestId('packaged-diff-model.temperature')).toHaveTextContent('0.1 → 0.2');
    expect(screen.getByTestId('packaged-diff-model.max_tokens')).toHaveTextContent('100 → 200');
    expect(screen.getByText('Architect')).toBeInTheDocument();
    expect(screen.getByText('Builder')).toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: 'Review changes' }));
    expect(screen.queryByTestId('packaged-diff-model.temperature')).not.toBeInTheDocument();
    expect(screen.queryByTestId('packaged-diff-model.max_tokens')).not.toBeInTheDocument();
  });

  it('confirms, posts the status lock_version, and calls onAdopted on 200', async () => {
    const mock = stubFetch(reply(200, status()));
    const onAdopted = vi.fn();
    const confirm = vi.spyOn(window, 'confirm').mockReturnValue(true);
    render(<PackagedUpdateBadge onAdopted={onAdopted} />);
    await screen.findByText(TITLE);

    fireEvent.click(screen.getByRole('button', { name: 'Adopt shipped version' }));

    expect(confirm).toHaveBeenCalledWith(CONFIRM);
    await waitFor(() => expect(onAdopted).toHaveBeenCalledTimes(1));
    expect(adoptCalls(mock)).toHaveLength(1);
    const [url, init] = adoptCalls(mock)[0] as [string, RequestInit];
    expect(url).toMatch(/\/api\/admin\/graph-shipping\/packaged-update\/adopt$/);
    expect(init.method).toBe('POST');
    expect(JSON.parse(String(init.body))).toEqual({ lock_version: 7 });
  });

  it('does not post when the confirmation is declined', async () => {
    const mock = stubFetch(reply(200, status()));
    const onAdopted = vi.fn();
    vi.spyOn(window, 'confirm').mockReturnValue(false);
    render(<PackagedUpdateBadge onAdopted={onAdopted} />);
    await screen.findByText(TITLE);

    fireEvent.click(screen.getByRole('button', { name: 'Adopt shipped version' }));

    expect(adoptCalls(mock)).toHaveLength(0);
    expect(onAdopted).not.toHaveBeenCalled();
  });

  it('shows the invalid-response message on a malformed adopt 200 and reloads through onAdopted', async () => {
    stubFetch(reply(200, status()), reply(200, { ...adoptSuccess(), draft_effect: { architect: 'kept' } }));
    const onAdopted = vi.fn();
    vi.spyOn(window, 'confirm').mockReturnValue(true);
    render(<PackagedUpdateBadge onAdopted={onAdopted} />);
    await screen.findByText(TITLE);

    fireEvent.click(screen.getByRole('button', { name: 'Adopt shipped version' }));

    expect(await screen.findByText(
      'The adopt response was invalid. Reloading the workbench to show the current Graph Version.',
    )).toBeInTheDocument();
    expect(onAdopted).toHaveBeenCalledTimes(1);
  });

  it('shows the stale-draft message on a 409 stale_publication and does not call onAdopted', async () => {
    stubFetch(reply(200, status()), reply(409, {
      code: 'stale_publication',
      expected_lock_version: 7,
      current_lock_version: 8,
      active_release: { release_id: 45, version_number: 5 },
      draft: {
        draft_id: 1, base_release_id: 45, base_version_number: 5, lock_version: 8,
        updated_by: 'admin@example.com', updated_at: '2026-09-25T12:00:00Z',
      },
    }));
    const onAdopted = vi.fn();
    vi.spyOn(window, 'confirm').mockReturnValue(true);
    render(<PackagedUpdateBadge onAdopted={onAdopted} />);
    await screen.findByText(TITLE);

    fireEvent.click(screen.getByRole('button', { name: 'Adopt shipped version' }));

    expect(await screen.findByText(STALE)).toBeInTheDocument();
    expect(onAdopted).not.toHaveBeenCalled();
  });
});
