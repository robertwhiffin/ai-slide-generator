/**
 * Presenter view, Task 6: the editor's onboarding overlays never mount over the presenter window.
 *
 * App renders the tour, the welcome modal and the "What's new" modal beside its routes. The presenter window
 * (/sessions/:sessionId/present) is a small private pop-up, so none of the three may appear there, while the
 * editor routes keep all three.
 *
 * Every heavy module is stubbed: the providers pass children through, and each page or overlay renders a marker.
 *
 * SABOTAGE target: render the three overlays on every route again -> "presenter route" RED.
 */
import type { ReactNode } from 'react';
import { render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

const { passThrough } = vi.hoisted(() => ({
  passThrough: ({ children }: { children: ReactNode }) => children,
}));

vi.mock('./components/Layout/AppLayout', () => ({ AppLayout: () => <div>EDITOR PAGE</div> }));
vi.mock('./components/Admin/AdminPage', () => ({ AdminPage: () => null }));
vi.mock('./components/Admin/GraphRelease', () => ({ ReviewAndPublishPage: () => null }));
vi.mock('./components/Presenter', () => ({ PresenterPage: () => <div>PRESENTER PAGE</div> }));
vi.mock('./hooks/useCurrentUser', () => ({ useCurrentUser: () => ({ isAdmin: false, loading: false }) }));
vi.mock('./components/Setup', () => ({ WelcomeSetup: () => null }));
vi.mock('./contexts/AgentConfigContext', () => ({ AgentConfigProvider: passThrough }));
vi.mock('./contexts/SessionContext', () => ({ SessionProvider: passThrough }));
vi.mock('./contexts/GenerationContext', () => ({ GenerationProvider: passThrough }));
vi.mock('./contexts/ToastContext', () => ({ ToastProvider: passThrough }));
vi.mock('./contexts/TourContext', () => ({ TourProvider: passThrough }));
vi.mock('./contexts/WhatsNewContext', () => ({ WhatsNewProvider: passThrough }));
vi.mock('./components/Tour/AppTour', () => ({ AppTour: () => <div>TOUR OVERLAY</div> }));
vi.mock('./components/Tour/WelcomeModal', () => ({ WelcomeModal: () => <div>WELCOME OVERLAY</div> }));
vi.mock('./components/WhatsNew/WhatsNewModal', () => ({ WhatsNewModal: () => <div>WHATS NEW OVERLAY</div> }));

import App from './App';

const OVERLAYS = ['TOUR OVERLAY', 'WELCOME OVERLAY', 'WHATS NEW OVERLAY'];

beforeEach(() => {
  // The setup check: the app is configured.
  vi.stubGlobal(
    'fetch',
    vi.fn(async () => new Response(JSON.stringify({ configured: true }), { status: 200 })),
  );
});

afterEach(() => {
  vi.unstubAllGlobals();
});

function renderAt(path: string) {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <App />
    </MemoryRouter>,
  );
}

describe('App overlays and the presenter window', () => {
  it('the presenter route shows the presenter page and none of the editor overlays', async () => {
    renderAt('/sessions/s1/present');
    await waitFor(() => expect(screen.getByText('PRESENTER PAGE')).toBeInTheDocument());

    for (const overlay of OVERLAYS) expect(screen.queryByText(overlay)).toBeNull();
  });

  it('the editor routes keep all three overlays', async () => {
    for (const path of ['/sessions/s1/edit', '/sessions/s1/view', '/']) {
      const view = renderAt(path);
      await waitFor(() => expect(screen.getByText('EDITOR PAGE')).toBeInTheDocument());
      for (const overlay of OVERLAYS) expect(screen.getByText(overlay)).toBeInTheDocument();
      view.unmount();
    }
  });
});
