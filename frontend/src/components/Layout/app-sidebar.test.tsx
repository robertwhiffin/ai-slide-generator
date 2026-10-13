import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import { MemoryRouter, Routes, Route } from 'react-router-dom';
import { SidebarProvider } from '@/ui/sidebar';
import { AppSidebar } from './app-sidebar';

const currentUser = { username: 'u', displayName: 'u', isAdmin: false, loading: false };

vi.mock('@/hooks/useCurrentUser', () => ({
  useCurrentUser: () => currentUser,
}));
vi.mock('@/contexts/TourContext', () => ({
  useTour: () => ({ startTour: vi.fn() }),
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
