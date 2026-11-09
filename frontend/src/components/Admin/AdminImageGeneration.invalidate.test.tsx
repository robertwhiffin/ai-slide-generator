/**
 * @vitest-environment jsdom
 *
 * Chat image generation, Unit I (Task 6): "AdminImageGeneration invalidates [the options cache] after
 * a save" (plan Task 6; CORRECTIONS "Unit I interface", hooks/useImageGenerationOptions.ts).
 *
 * An admin who turns the feature on or off must not wait 5 minutes for the chat button, the slide
 * stage action and the Image Library to notice: a SUCCESSFUL save drops the cached probe, so the next
 * read asks the server again.
 */
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { ImageGenerationOptions } from '../../types/image';
import { AdminImageGeneration } from './AdminImageGeneration';
import {
  __resetImageGenerationOptionsCacheForTests,
  getImageGenerationOptions,
} from '../../hooks/useImageGenerationOptions';

const h = vi.hoisted(() => ({
  getImageGeneration: vi.fn(),
  setImageGeneration: vi.fn(),
  imageGenerationOptions: vi.fn(),
  showToast: vi.fn(),
}));

vi.mock('../../api/admin', () => ({
  adminApi: {
    getImageGeneration: (...args: unknown[]) => h.getImageGeneration(...args),
    setImageGeneration: (...args: unknown[]) => h.setImageGeneration(...args),
  },
}));
vi.mock('../../contexts/ToastContext', () => ({ useToast: () => ({ showToast: h.showToast }) }));
vi.mock('../../services/api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../../services/api')>();
  return {
    ...actual,
    api: { imageGenerationOptions: (...args: unknown[]) => h.imageGenerationOptions(...args) },
  };
});

const OPTIONS = (available: boolean): ImageGenerationOptions => ({
  available,
  max_prompt_chars: available ? 2000 : 0,
  default_preset: null,
  presets: [],
  edit: null,
});

const NAME = 'Let users generate images with AI';

describe('AdminImageGeneration drops the cached availability after a save', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    __resetImageGenerationOptionsCacheForTests();
  });
  afterEach(() => cleanup());

  it('a successful save makes the next options read ask the server again', async () => {
    h.imageGenerationOptions.mockResolvedValueOnce(OPTIONS(false)).mockResolvedValueOnce(OPTIONS(true));
    // Cache "off" first, as the chat would have.
    expect((await getImageGenerationOptions()).available).toBe(false);
    expect(h.imageGenerationOptions).toHaveBeenCalledTimes(1);

    h.getImageGeneration.mockResolvedValue({ available: true, enabled: false });
    h.setImageGeneration.mockResolvedValue({ available: true, enabled: true });
    render(<AdminImageGeneration />);
    fireEvent.click(await screen.findByRole('checkbox', { name: NAME }));
    await waitFor(() => expect(screen.getByRole('checkbox', { name: NAME })).toBeChecked());

    expect((await getImageGenerationOptions()).available).toBe(true);
    expect(h.imageGenerationOptions).toHaveBeenCalledTimes(2);
  });
});
