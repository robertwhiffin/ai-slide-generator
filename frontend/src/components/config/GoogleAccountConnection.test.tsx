/**
 * @vitest-environment jsdom
 */
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { GoogleAccountConnection } from './GoogleAccountConnection';

const checkGoogleSlidesAuth = vi.fn();
const revokeGoogleSlidesAuth = vi.fn();
const openOAuthPopup = vi.fn();

vi.mock('../../services/api', () => ({
  ApiError: class ApiError extends Error {
    status: number;
    constructor(status: number, message: string) {
      super(message);
      this.status = status;
    }
  },
  api: {
    checkGoogleSlidesAuth: (...args: unknown[]) => checkGoogleSlidesAuth(...args),
    revokeGoogleSlidesAuth: (...args: unknown[]) => revokeGoogleSlidesAuth(...args),
  },
}));

vi.mock('../../hooks/useGoogleOAuthPopup', () => ({
  useGoogleOAuthPopup: () => ({ openOAuthPopup }),
}));

vi.mock('../../api/config', () => ({
  configApi: {
    getGoogleCredentialsStatus: vi.fn(() => {
      throw new Error('admin credentials API must not be called from Settings');
    }),
    uploadGoogleCredentials: vi.fn(),
    deleteGoogleCredentials: vi.fn(),
  },
}));

describe('GoogleAccountConnection', () => {
  afterEach(() => {
    cleanup();
  });

  beforeEach(() => {
    vi.clearAllMocks();
    vi.spyOn(window, 'confirm').mockReturnValue(true);
  });

  it('shows an admin-needed message when client credentials are missing', async () => {
    checkGoogleSlidesAuth.mockResolvedValue({ authorized: false, has_credentials: false });
    render(<GoogleAccountConnection />);
    expect(await screen.findByText(/Google Slides export is not configured/i)).toBeTruthy();
    expect(screen.queryByRole('button', { name: /Authorize with Google/i })).toBeNull();
    expect(screen.queryByRole('heading', { name: /OAuth Client Credentials/i })).toBeNull();
  });

  it('shows connect when credentials exist but the user is not authorized', async () => {
    checkGoogleSlidesAuth.mockResolvedValue({ authorized: false, has_credentials: true });
    render(<GoogleAccountConnection />);
    expect(await screen.findByRole('button', { name: /Authorize with Google/i })).toBeTruthy();
    expect(screen.queryByRole('button', { name: /^Disconnect$/i })).toBeNull();
  });

  it('disconnects the current user without calling admin credential APIs', async () => {
    checkGoogleSlidesAuth.mockResolvedValue({ authorized: true, has_credentials: true });
    revokeGoogleSlidesAuth.mockResolvedValue(undefined);
    render(<GoogleAccountConnection />);
    const disconnect = await screen.findByRole('button', { name: /^Disconnect$/i });
    fireEvent.click(disconnect);
    await waitFor(() => {
      expect(revokeGoogleSlidesAuth).toHaveBeenCalledTimes(1);
    });
    expect(await screen.findByRole('button', { name: /Authorize with Google/i })).toBeTruthy();
  });
});
