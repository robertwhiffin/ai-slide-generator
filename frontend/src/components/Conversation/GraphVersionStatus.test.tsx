import { act, fireEvent, render, screen } from '@testing-library/react';
import { SessionProvider, useSession, type OptionalSessionInfo } from '@/contexts/SessionContext';
import { api } from '@/services/api';
import { GraphVersionStatus } from './GraphVersionStatus';

type VersionedSessionContext = ReturnType<typeof useSession> & {
  graphVersion?: number | null;
  activeGraphVersion?: number | null;
  isGraphVersionOlder?: boolean;
};

function VersionProbe() {
  const session = useSession() as VersionedSessionContext;
  const restore = async () => {
    const info: OptionalSessionInfo = {
      title: 'Pinned conversation',
      graph_version: 1,
      active_graph_version: 2,
      is_older_than_active: true,
    } as OptionalSessionInfo;
    await session.switchSession('pinned-session', info);
  };

  return (
    <>
      <output data-testid="versions">
        {JSON.stringify([session.graphVersion, session.activeGraphVersion, session.isGraphVersionOlder])}
      </output>
      <button onClick={restore}>Restore pinned session</button>
      <button onClick={() => session.createNewSession()}>New local session</button>
    </>
  );
}

describe('conversation graph-version state', () => {
  it('serializes browser graph capability explicitly', async () => {
    const fetchMock = vi.spyOn(globalThis, 'fetch').mockResolvedValue(
      new Response(JSON.stringify({ session_id: 'browser-root' }), { status: 200 }),
    );

    await (api.createSession as (options: {
      sessionId?: string;
      title?: string;
      graphCapable?: boolean;
    }) => Promise<unknown>)({ sessionId: 'browser-root', graphCapable: true });

    expect(fetchMock).toHaveBeenCalledWith(
      expect.stringContaining('/api/sessions'),
      expect.objectContaining({
        body: JSON.stringify({
          session_id: 'browser-root',
          title: undefined,
          graph_capable: true,
        }),
      }),
    );
    fetchMock.mockRestore();
  });

  it('restores returned graph versions and clears them for a fresh local session', async () => {
    render(
      <SessionProvider>
        <VersionProbe />
      </SessionProvider>,
    );

    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: 'Restore pinned session' }));
    });
    expect(screen.getByTestId('versions')).toHaveTextContent('[1,2,true]');

    fireEvent.click(screen.getByRole('button', { name: 'New local session' }));
    expect(screen.getByTestId('versions')).toHaveTextContent('[null,null,false]');
  });
});

describe('GraphVersionStatus', () => {
  const onStartLatest = vi.fn().mockResolvedValue(undefined);

  beforeEach(() => {
    onStartLatest.mockClear();
  });

  it('labels a session pinned to the active graph version', () => {
    render(
      <GraphVersionStatus
        graphVersion={2}
        activeGraphVersion={2}
        isOlder={false}
        onStartLatest={onStartLatest}
        isStartingLatest={false}
      />,
    );

    expect(screen.getByTestId('graph-version-status')).toHaveTextContent('Agent version 2');
    expect(screen.queryByRole('button', { name: 'Start latest' })).not.toBeInTheDocument();
  });

  it('offers Start latest only when the pinned graph is older', () => {
    render(
      <GraphVersionStatus
        graphVersion={1}
        activeGraphVersion={2}
        isOlder
        onStartLatest={onStartLatest}
        isStartingLatest={false}
      />,
    );

    expect(screen.getByTestId('graph-version-status')).toHaveTextContent('Agent version 1; latest is 2');
    fireEvent.click(screen.getByRole('button', { name: 'Start latest' }));
    expect(onStartLatest).toHaveBeenCalledOnce();
  });

  it('does not invent a version before one is returned', () => {
    render(
      <GraphVersionStatus
        graphVersion={null}
        activeGraphVersion={2}
        isOlder={false}
        onStartLatest={onStartLatest}
        isStartingLatest={false}
      />,
    );

    expect(screen.getByTestId('graph-version-status')).toHaveTextContent('Agent version unavailable');
    expect(screen.queryByRole('button')).not.toBeInTheDocument();
  });
});
