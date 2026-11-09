/**
 * @vitest-environment jsdom
 *
 * Admin -> Connections, "Let users generate images with AI".
 * Contract: docs/superpowers/plans/2026-11-08-ai-image-generation-CORRECTIONS.md,
 * "Unit D interface (admin toggle)". Pattern: AdminGenieOneDefault.
 *
 *   adminApi.getImageGeneration(): Promise<{ available: boolean; enabled: boolean }>
 *   adminApi.setImageGeneration(enabled): Promise<{ available: boolean; enabled: boolean }>
 *
 * - available === false (the deployment does not offer the capability): renders NOTHING.
 * - otherwise a checkbox named "Let users generate images with AI", checked from `enabled`,
 *   whose accessible description (aria-describedby, as in AdminGenieOneDefault) is the help
 *   text: adds Generate / Edit with prompt to the Image Library, each image is a paid model
 *   call made as the app's service principal, on by default.
 * - a click saves !enabled and shows what the server returned; disabled while saving.
 * - a save failure toasts "Failed to save: <message>" (error) and keeps the previous state.
 * - a load failure shows "Failed to load: <message>".
 */
import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { AdminImageGeneration } from './AdminImageGeneration';

type Setting = { available: boolean; enabled: boolean };

const getImageGeneration = vi.fn();
const setImageGeneration = vi.fn();
const showToast = vi.fn();

vi.mock('../../api/admin', () => ({
  adminApi: {
    getImageGeneration: (...args: unknown[]) => getImageGeneration(...args),
    setImageGeneration: (...args: unknown[]) => setImageGeneration(...args),
  },
}));

vi.mock('../../contexts/ToastContext', () => ({
  useToast: () => ({ showToast }),
}));

const NAME = 'Let users generate images with AI';
const toggle = () => screen.findByRole('checkbox', { name: NAME });

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason: unknown) => void;
  const promise = new Promise<T>((res, rej) => {
    resolve = res;
    reject = rej;
  });
  return { promise, resolve, reject };
}

describe('AdminImageGeneration', () => {
  afterEach(() => {
    cleanup();
  });

  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('loads the setting once on mount', async () => {
    getImageGeneration.mockResolvedValue({ available: true, enabled: false });
    render(<AdminImageGeneration />);
    await toggle();
    expect(getImageGeneration).toHaveBeenCalledTimes(1);
    expect(setImageGeneration).not.toHaveBeenCalled();
  });

  it.each([false, true])(
    'renders nothing when the deployment does not offer image generation (enabled=%s)',
    async (enabled) => {
      const load = deferred<Setting>();
      getImageGeneration.mockReturnValue(load.promise);
      const { container } = render(<AdminImageGeneration />);

      await act(async () => {
        load.resolve({ available: false, enabled });
      });

      expect(getImageGeneration).toHaveBeenCalledTimes(1);
      expect(screen.queryByRole('checkbox')).not.toBeInTheDocument();
      expect(container).toBeEmptyDOMElement();
    },
  );

  it('shows the switch off when the setting is off', async () => {
    getImageGeneration.mockResolvedValue({ available: true, enabled: false });
    render(<AdminImageGeneration />);
    const box = await toggle();
    expect(box).not.toBeChecked();
    expect(box).toBeEnabled();
  });

  it('shows the switch on when the setting is on', async () => {
    getImageGeneration.mockResolvedValue({ available: true, enabled: true });
    render(<AdminImageGeneration />);
    expect(await toggle()).toBeChecked();
  });

  it('explains what it does, that each image is paid for, and that it is on by default', async () => {
    getImageGeneration.mockResolvedValue({ available: true, enabled: false });
    render(<AdminImageGeneration />);
    const box = await toggle();
    expect(box).toHaveAccessibleDescription(/Generate/);
    expect(box).toHaveAccessibleDescription(/Edit with prompt/);
    expect(box).toHaveAccessibleDescription(/Image Library/i);
    expect(box).toHaveAccessibleDescription(/\bpaid\b/i);
    expect(box).toHaveAccessibleDescription(/service principal/i);
    expect(box).toHaveAccessibleDescription(/on by default/i);
  });

  it('turns it on when clicked while off, and shows the saved value', async () => {
    getImageGeneration.mockResolvedValue({ available: true, enabled: false });
    setImageGeneration.mockResolvedValue({ available: true, enabled: true });
    render(<AdminImageGeneration />);
    fireEvent.click(await toggle());
    await waitFor(() => expect(setImageGeneration).toHaveBeenCalledWith(true));
    expect(setImageGeneration).toHaveBeenCalledTimes(1);
    await waitFor(async () => expect(await toggle()).toBeChecked());
  });

  it('turns it off when clicked while on, and shows the saved value', async () => {
    getImageGeneration.mockResolvedValue({ available: true, enabled: true });
    setImageGeneration.mockResolvedValue({ available: true, enabled: false });
    render(<AdminImageGeneration />);
    fireEvent.click(await toggle());
    await waitFor(() => expect(setImageGeneration).toHaveBeenCalledWith(false));
    await waitFor(async () => expect(await toggle()).not.toBeChecked());
  });

  it('shows what the server stored, not what was clicked', async () => {
    getImageGeneration.mockResolvedValue({ available: true, enabled: false });
    setImageGeneration.mockResolvedValue({ available: true, enabled: false });
    render(<AdminImageGeneration />);
    fireEvent.click(await toggle());
    await waitFor(() => expect(setImageGeneration).toHaveBeenCalledWith(true));
    await waitFor(async () => expect(await toggle()).toBeEnabled());
    expect(await toggle()).not.toBeChecked();
  });

  it('disables the switch while the save is in flight', async () => {
    getImageGeneration.mockResolvedValue({ available: true, enabled: false });
    const save = deferred<Setting>();
    setImageGeneration.mockReturnValue(save.promise);
    render(<AdminImageGeneration />);
    fireEvent.click(await toggle());

    await waitFor(async () => expect(await toggle()).toBeDisabled());

    await act(async () => {
      save.resolve({ available: true, enabled: true });
    });
    const box = await toggle();
    expect(box).toBeEnabled();
    expect(box).toBeChecked();
  });

  it('puts the switch back and says so when the save fails', async () => {
    getImageGeneration.mockResolvedValue({ available: true, enabled: true });
    setImageGeneration.mockRejectedValue(new Error('boom'));
    render(<AdminImageGeneration />);
    fireEvent.click(await toggle());

    await waitFor(() => expect(showToast).toHaveBeenCalledTimes(1));
    const [message, type] = showToast.mock.calls[0];
    expect(message).toMatch(/^Failed to save: /);
    expect(message).toContain('boom');
    expect(type).toBe('error');
    await waitFor(async () => expect(await toggle()).toBeEnabled());
    expect(await toggle()).toBeChecked();
  });

  it('keeps an off switch off when turning it on fails', async () => {
    getImageGeneration.mockResolvedValue({ available: true, enabled: false });
    setImageGeneration.mockRejectedValue(new Error('Image generation is not available on this deployment'));
    render(<AdminImageGeneration />);
    fireEvent.click(await toggle());

    await waitFor(() =>
      expect(showToast).toHaveBeenCalledWith(
        expect.stringMatching(/^Failed to save: Image generation is not available/),
        'error',
      ),
    );
    await waitFor(async () => expect(await toggle()).toBeEnabled());
    expect(await toggle()).not.toBeChecked();
  });

  it('says so when the setting cannot be loaded', async () => {
    getImageGeneration.mockRejectedValue(new Error('no access'));
    render(<AdminImageGeneration />);
    expect(await screen.findByText(/Failed to load: no access/)).toBeInTheDocument();
    expect(screen.queryByRole('checkbox')).not.toBeInTheDocument();
  });
});
