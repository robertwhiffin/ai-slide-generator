/**
 * @vitest-environment jsdom
 *
 * Admin -> Connections: the "Add Genie One to new decks" switch. It shows the stored setting,
 * saves on click, and puts the switch back (with a toast) when the save fails.
 */
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { AdminGenieOneDefault } from './AdminGenieOneDefault';

const getGenieOneDefault = vi.fn();
const setGenieOneDefault = vi.fn();
const showToast = vi.fn();

vi.mock('../../api/admin', () => ({
  adminApi: {
    getGenieOneDefault: (...args: unknown[]) => getGenieOneDefault(...args),
    setGenieOneDefault: (...args: unknown[]) => setGenieOneDefault(...args),
  },
}));

vi.mock('../../contexts/ToastContext', () => ({
  useToast: () => ({ showToast }),
}));

const toggle = () => screen.findByRole('checkbox', { name: 'Add Genie One to new decks' });

describe('AdminGenieOneDefault', () => {
  afterEach(() => {
    cleanup();
  });

  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('shows the switch off when the setting is off', async () => {
    getGenieOneDefault.mockResolvedValue({ enabled: false });
    render(<AdminGenieOneDefault />);
    expect(await toggle()).not.toBeChecked();
  });

  it('shows the switch on when the setting is on', async () => {
    getGenieOneDefault.mockResolvedValue({ enabled: true });
    render(<AdminGenieOneDefault />);
    expect(await toggle()).toBeChecked();
  });

  it('saves the new value when clicked', async () => {
    getGenieOneDefault.mockResolvedValue({ enabled: false });
    setGenieOneDefault.mockResolvedValue({ enabled: true });
    render(<AdminGenieOneDefault />);
    fireEvent.click(await toggle());
    await waitFor(() => expect(setGenieOneDefault).toHaveBeenCalledWith(true));
    await waitFor(async () => expect(await toggle()).toBeChecked());
  });

  it('puts the switch back and says so when the save fails', async () => {
    getGenieOneDefault.mockResolvedValue({ enabled: true });
    setGenieOneDefault.mockRejectedValue(new Error('boom'));
    render(<AdminGenieOneDefault />);
    fireEvent.click(await toggle());
    await waitFor(() => expect(showToast).toHaveBeenCalledWith(expect.stringContaining('boom'), 'error'));
    expect(await toggle()).toBeChecked();
  });

  it('says so when the setting cannot be loaded', async () => {
    getGenieOneDefault.mockRejectedValue(new Error('no access'));
    render(<AdminGenieOneDefault />);
    expect(await screen.findByText(/no access/)).toBeInTheDocument();
  });
});
