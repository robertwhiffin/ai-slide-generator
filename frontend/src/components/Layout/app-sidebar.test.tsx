import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, within } from '@testing-library/react';
import { MemoryRouter, Routes, Route } from 'react-router-dom';
import { SidebarProvider } from '@/ui/sidebar';
import { AppSidebar } from './app-sidebar';

const currentUser = { username: 'u', displayName: 'u', isAdmin: false, loading: false };
/** What the sidebar reads from useWhatsNew(). hasNotes defaults to false, as in this PR (no notes files). */
const whatsNew = { hasNotes: false, open: vi.fn() };

vi.mock('@/hooks/useCurrentUser', () => ({
  useCurrentUser: () => currentUser,
}));
vi.mock('@/contexts/TourContext', () => ({
  useTour: () => ({ startTour: vi.fn() }),
}));
vi.mock('@/contexts/WhatsNewContext', () => ({
  useWhatsNew: () => whatsNew,
}));
vi.mock('@/components/Layout/deck-history', () => ({
  DeckHistory: () => null,
}));
vi.mock('@/components/Layout/brand-header', () => ({
  BrandHeader: () => null,
}));

function renderSidebar() {
  const onViewChange = vi.fn();
  render(
    <MemoryRouter initialEntries={['/']}>
      <SidebarProvider>
        <Routes>
          <Route
            path="/"
            element={
              <AppSidebar
                currentView="main"
                onViewChange={onViewChange}
                onSessionSelect={vi.fn()}
                onNewSession={vi.fn()}
              />
            }
          />
          <Route path="/admin" element={<div>admin page</div>} />
        </Routes>
      </SidebarProvider>
    </MemoryRouter>,
  );
  return { onViewChange };
}

beforeEach(() => {
  whatsNew.hasNotes = false;
  whatsNew.open.mockReset();
});

describe('AppSidebar Configure section admin link', () => {
  beforeEach(() => {
    // SidebarProvider's mobile hook reads matchMedia, which jsdom lacks.
    window.matchMedia = vi.fn().mockReturnValue({
      matches: false,
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
    }) as unknown as typeof window.matchMedia;
    currentUser.isAdmin = false;
    currentUser.loading = false;
  });

  it('shows an Admin link to an admin and navigates to /admin', () => {
    currentUser.isAdmin = true;
    const { onViewChange } = renderSidebar();

    const configure = screen.getByText('Configure').closest('[data-tour="configure-section"]') as HTMLElement;
    const adminButton = configure.querySelector('[data-tour="nav-admin"] button') as HTMLElement;
    expect(adminButton).toHaveTextContent('Admin');

    fireEvent.click(adminButton);
    expect(screen.getByText('admin page')).toBeInTheDocument();
    expect(onViewChange).not.toHaveBeenCalled();
  });

  it('hides the Admin link from a non-admin', () => {
    renderSidebar();
    expect(screen.getByText('Agent profiles')).toBeInTheDocument();
    expect(screen.queryByText('Admin')).not.toBeInTheDocument();
  });

  it('hides the Admin link while identity is still loading', () => {
    currentUser.isAdmin = true;
    currentUser.loading = true;
    renderSidebar();
    expect(screen.queryByText('Admin')).not.toBeInTheDocument();
  });
});

/**
 * What's new popup, Task 3: the footer item that reopens the popup. It is shown only when hasNotes,
 * sits after "App Tour" in the footer, and calls useWhatsNew().open (an overlay, not a page).
 * SABOTAGE (each measured red against a throwaway copy of the sidebar, since deleted): the item is
 * always shown, never shown, wired to startTour, calls open twice, uses a curly apostrophe or "What's
 * New", sits before App Tour, is a Configure nav item, or reads `releases` instead of `hasNotes`.
 */
describe("AppSidebar footer What's new item", () => {
  beforeEach(() => {
    // SidebarProvider's mobile hook reads matchMedia, which jsdom lacks.
    window.matchMedia = vi.fn().mockReturnValue({
      matches: false,
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
    }) as unknown as typeof window.matchMedia;
  });

  it("shows a What's new button in the footer, after App Tour, that opens the popup", () => {
    whatsNew.hasNotes = true;
    const { onViewChange } = renderSidebar();

    const appTour = screen.getByRole('button', { name: 'App Tour' });
    const footer = appTour.closest('[data-sidebar="footer"]') as HTMLElement;
    const button = within(footer).getByRole('button', { name: "What's new" });
    expect(appTour.compareDocumentPosition(button) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();

    expect(whatsNew.open).not.toHaveBeenCalled();
    fireEvent.click(button);
    expect(whatsNew.open).toHaveBeenCalledTimes(1);
    expect(onViewChange).not.toHaveBeenCalled(); // it opens an overlay, not a page
  });

  it('hides it while no release has notes', () => {
    renderSidebar();

    expect(screen.getByRole('button', { name: 'App Tour' })).toBeInTheDocument(); // the footer rendered
    expect(screen.queryByText("What's new")).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: "What's new" })).not.toBeInTheDocument();
  });
});
