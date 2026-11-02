/**
 * @vitest-environment jsdom
 *
 * Task 6 (admin permissions): the Admins tab on the admin page.
 *
 * The Admins panel must mount only once its tab is first opened (the
 * `hasVisitedAgentDefinitions` pattern). The other admin e2e specs do not mock
 * /api/admin/admins, so an eager mount would make every one of them fire an
 * unmocked request. Every panel is stubbed here so only AdminPage's own wiring runs.
 *
 * SABOTAGE (each should turn the named test RED):
 *   - mount <AdminAdmins /> unconditionally                 -> "does not mount the Admins panel ..."
 *   - mount it only while the tab is active (unmount on leave) -> "... stays mounted ..."
 *   - put the tab anywhere but last / change its ids         -> "adds an Admins tab last ..."
 */
import { cleanup, fireEvent, render, screen, within } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { AdminPage } from './AdminPage';

vi.mock('./AdminAdmins', () => ({
  AdminAdmins: () => <div data-testid="admin-admins-stub" />,
}));
vi.mock('../Feedback/FeedbackDashboard', () => ({ FeedbackDashboard: () => null }));
vi.mock('../config/GoogleSlidesAuthForm', () => ({ GoogleSlidesAuthForm: () => null }));
vi.mock('./AdminDesignSystemDefault', () => ({ AdminDesignSystemDefault: () => null }));
vi.mock('./AdminJudgeSettings', () => ({ AdminJudgeSettings: () => null }));
vi.mock('./AdminSlideStyleDefault', () => ({ AdminSlideStyleDefault: () => null }));
vi.mock('./UsageDashboard', () => ({ UsageDashboard: () => null }));
vi.mock('./AgentDefinitionWorkbench', () => ({ AgentDefinitionWorkbench: () => null }));

describe('AdminPage — Admins tab', () => {
  afterEach(() => {
    cleanup();
  });

  it('adds an Admins tab last in the tab row, controlling admins-panel', () => {
    render(<AdminPage />);

    const tabs = within(screen.getByRole('tablist')).getAllByRole('tab');
    const last = tabs[tabs.length - 1];
    expect(last).toHaveTextContent(/^Admins$/);
    expect(last).toHaveAttribute('id', 'admins-tab');
    expect(last).toHaveAttribute('aria-controls', 'admins-panel');
    expect(last).toHaveAttribute('aria-selected', 'false');
    expect(document.getElementById('admins-panel')).not.toBeNull();
  });

  it('does not mount the Admins panel until its tab is opened', () => {
    render(<AdminPage />);

    expect(screen.queryByTestId('admin-admins-stub')).toBeNull();

    // Visiting the other (eager) tabs does not mount it either.
    for (const name of ['Feedback', 'Google Slides', 'Design System', 'Slide Style', 'Judge']) {
      fireEvent.click(screen.getByRole('tab', { name }));
    }
    expect(screen.queryByTestId('admin-admins-stub')).toBeNull();

    fireEvent.click(screen.getByRole('tab', { name: 'Admins' }));

    const panel = document.getElementById('admins-panel')!;
    expect(within(panel).getByTestId('admin-admins-stub')).toBeInTheDocument();
    expect(screen.getByRole('tab', { name: 'Admins' })).toHaveAttribute('aria-selected', 'true');
    expect(panel).not.toHaveAttribute('hidden');
  });

  it('keeps the Admins panel mounted (hidden) after switching to another tab', () => {
    render(<AdminPage />);

    fireEvent.click(screen.getByRole('tab', { name: 'Admins' }));
    fireEvent.click(screen.getByRole('tab', { name: 'Usage' }));

    const panel = document.getElementById('admins-panel')!;
    expect(panel).toHaveAttribute('hidden');
    expect(within(panel).getByTestId('admin-admins-stub')).toBeInTheDocument();
  });
});
