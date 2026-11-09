/**
 * Chat image generation, Unit I (Task 6): one cached availability probe for the whole app.
 *
 * Contract: docs/superpowers/plans/2026-11-09-chat-image-generation-CORRECTIONS.md, "Unit I interface":
 *
 *   // hooks/useImageGenerationOptions.ts
 *   getImageGenerationOptions(): Promise<ImageGenerationOptions>  // module-cached, 5-min TTL, failure resolves "unavailable"
 *   useImageGenerationOptions(): ImageGenerationOptions | null     // null until the probe answers
 *   invalidateImageGenerationOptions(): void
 *   __resetImageGenerationOptionsCacheForTests(): void
 *
 * The probe is `api.imageGenerationOptions()` (GET /api/images/generate/available); the hook never
 * fetches by itself. The Image Library, the chat input and the slide stage all read it, so the
 * request is made once per 5 minutes, not once per consumer.
 *
 * Choices this test pins (CORRECTIONS is silent):
 *   - concurrent callers share ONE in-flight request;
 *   - a probe that throws synchronously (a test's api mock without the method) is a failure too;
 *   - a rejected probe resolves to an object with `available: false` (never rejects), and it is not
 *     cached for good: invalidation, or the TTL running out, makes the next call ask again;
 *   - the TTL is 5 minutes (300 000 ms): 4:59 later the answer is still served, 5:01 later it is not.
 *
 * The admin toggle invalidating the cache after a save is pinned in
 * components/Admin/AdminImageGeneration.invalidate.test.tsx.
 */
import { act, renderHook, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { ImageGenerationOptions } from '../types/image';
import {
  __resetImageGenerationOptionsCacheForTests,
  getImageGenerationOptions,
  invalidateImageGenerationOptions,
  useImageGenerationOptions,
} from './useImageGenerationOptions';

const h = vi.hoisted(() => ({ imageGenerationOptions: vi.fn() }));

vi.mock('../services/api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../services/api')>();
  return {
    ...actual,
    api: { imageGenerationOptions: (...args: unknown[]) => h.imageGenerationOptions(...args) },
  };
});

const AVAILABLE: ImageGenerationOptions = {
  available: true,
  max_prompt_chars: 2000,
  default_preset: 'illustration',
  presets: [],
  edit: null,
};
const UNAVAILABLE: ImageGenerationOptions = {
  available: false,
  max_prompt_chars: 0,
  default_preset: null,
  presets: [],
  edit: null,
};

const TTL_MS = 5 * 60 * 1000;

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason: unknown) => void;
  const promise = new Promise<T>((res, rej) => {
    resolve = res;
    reject = rej;
  });
  return { promise, resolve, reject };
}

beforeEach(() => {
  __resetImageGenerationOptionsCacheForTests();
  h.imageGenerationOptions.mockReset();
});

afterEach(() => {
  vi.useRealTimers();
});

describe('getImageGenerationOptions', () => {
  it('asks the server once for concurrent callers and hands them the same answer', async () => {
    const probe = deferred<ImageGenerationOptions>();
    h.imageGenerationOptions.mockReturnValue(probe.promise);

    const a = getImageGenerationOptions();
    const b = getImageGenerationOptions();
    probe.resolve(AVAILABLE);

    expect(await a).toEqual(AVAILABLE);
    expect(await b).toEqual(AVAILABLE);
    expect(h.imageGenerationOptions).toHaveBeenCalledTimes(1);
  });

  it('serves a later call from the cache', async () => {
    h.imageGenerationOptions.mockResolvedValue(AVAILABLE);

    expect(await getImageGenerationOptions()).toEqual(AVAILABLE);
    expect(await getImageGenerationOptions()).toEqual(AVAILABLE);
    expect(await getImageGenerationOptions()).toEqual(AVAILABLE);
    expect(h.imageGenerationOptions).toHaveBeenCalledTimes(1);
  });

  it('invalidateImageGenerationOptions makes the next call ask again and return the new answer', async () => {
    h.imageGenerationOptions.mockResolvedValueOnce(AVAILABLE).mockResolvedValueOnce(UNAVAILABLE);

    expect((await getImageGenerationOptions()).available).toBe(true);
    invalidateImageGenerationOptions();
    expect((await getImageGenerationOptions()).available).toBe(false);
    expect(h.imageGenerationOptions).toHaveBeenCalledTimes(2);

    // And the new answer is cached in turn.
    expect((await getImageGenerationOptions()).available).toBe(false);
    expect(h.imageGenerationOptions).toHaveBeenCalledTimes(2);
  });

  it('a rejected probe resolves "unavailable" instead of rejecting', async () => {
    h.imageGenerationOptions.mockRejectedValue(new TypeError('Failed to fetch'));

    const result = await getImageGenerationOptions();
    expect(result.available).toBe(false);
  });

  // Load-bearing for the existing suites: eight ChatPanel test files mock `api` without
  // `imageGenerationOptions`, so there the call throws synchronously ("is not a function"). An
  // unguarded call would crash every one of them once ChatPanel uses the hook.
  it('a probe that throws synchronously resolves "unavailable" instead of throwing', async () => {
    h.imageGenerationOptions.mockImplementation(() => {
      throw new TypeError('api.imageGenerationOptions is not a function');
    });

    let pending: Promise<ImageGenerationOptions> | undefined;
    expect(() => {
      pending = getImageGenerationOptions();
    }).not.toThrow();
    expect((await pending!).available).toBe(false);
  });

  it('a failure is not cached for good: after invalidation the next call asks again', async () => {
    h.imageGenerationOptions
      .mockRejectedValueOnce(new TypeError('Failed to fetch'))
      .mockResolvedValueOnce(AVAILABLE);

    expect((await getImageGenerationOptions()).available).toBe(false);
    invalidateImageGenerationOptions();
    expect(await getImageGenerationOptions()).toEqual(AVAILABLE);
    expect(h.imageGenerationOptions).toHaveBeenCalledTimes(2);
  });

  it('the answer expires after 5 minutes', async () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date('2026-11-09T10:00:00Z'));
    h.imageGenerationOptions.mockResolvedValueOnce(AVAILABLE).mockResolvedValueOnce(UNAVAILABLE);

    expect((await getImageGenerationOptions()).available).toBe(true);
    expect(h.imageGenerationOptions).toHaveBeenCalledTimes(1);

    vi.advanceTimersByTime(TTL_MS - 1000);
    expect((await getImageGenerationOptions()).available).toBe(true);
    expect(h.imageGenerationOptions).toHaveBeenCalledTimes(1);

    vi.advanceTimersByTime(2000);
    expect((await getImageGenerationOptions()).available).toBe(false);
    expect(h.imageGenerationOptions).toHaveBeenCalledTimes(2);
  });

  it('a failed answer expires after 5 minutes too', async () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date('2026-11-09T10:00:00Z'));
    h.imageGenerationOptions
      .mockRejectedValueOnce(new Error('503'))
      .mockResolvedValueOnce(AVAILABLE);

    expect((await getImageGenerationOptions()).available).toBe(false);
    vi.advanceTimersByTime(TTL_MS + 1000);
    expect(await getImageGenerationOptions()).toEqual(AVAILABLE);
    expect(h.imageGenerationOptions).toHaveBeenCalledTimes(2);
  });

  it('__resetImageGenerationOptionsCacheForTests forgets the answer', async () => {
    h.imageGenerationOptions.mockResolvedValue(AVAILABLE);
    await getImageGenerationOptions();
    __resetImageGenerationOptionsCacheForTests();
    await getImageGenerationOptions();
    expect(h.imageGenerationOptions).toHaveBeenCalledTimes(2);
  });
});

describe('useImageGenerationOptions', () => {
  it('is null until the probe answers, then the options', async () => {
    const probe = deferred<ImageGenerationOptions>();
    h.imageGenerationOptions.mockReturnValue(probe.promise);

    const { result } = renderHook(() => useImageGenerationOptions());
    expect(result.current).toBeNull();

    await act(async () => {
      probe.resolve(AVAILABLE);
      await probe.promise;
    });
    expect(result.current).toEqual(AVAILABLE);
  });

  it('two consumers mounted together make one request', async () => {
    h.imageGenerationOptions.mockResolvedValue(AVAILABLE);

    const first = renderHook(() => useImageGenerationOptions());
    const second = renderHook(() => useImageGenerationOptions());

    await waitFor(() => expect(first.result.current).toEqual(AVAILABLE));
    await waitFor(() => expect(second.result.current).toEqual(AVAILABLE));
    expect(h.imageGenerationOptions).toHaveBeenCalledTimes(1);
  });

  it('a consumer mounted later, within the TTL, is served from the cache', async () => {
    h.imageGenerationOptions.mockResolvedValue(AVAILABLE);

    const first = renderHook(() => useImageGenerationOptions());
    await waitFor(() => expect(first.result.current).toEqual(AVAILABLE));
    first.unmount();

    const later = renderHook(() => useImageGenerationOptions());
    await waitFor(() => expect(later.result.current).toEqual(AVAILABLE));
    expect(h.imageGenerationOptions).toHaveBeenCalledTimes(1);
  });

  it('shares the request with getImageGenerationOptions', async () => {
    h.imageGenerationOptions.mockResolvedValue(AVAILABLE);

    await getImageGenerationOptions();
    const { result } = renderHook(() => useImageGenerationOptions());
    await waitFor(() => expect(result.current).toEqual(AVAILABLE));
    expect(h.imageGenerationOptions).toHaveBeenCalledTimes(1);
  });

  it('a rejected probe gives "unavailable", not an error', async () => {
    h.imageGenerationOptions.mockRejectedValue(new TypeError('Failed to fetch'));

    const { result } = renderHook(() => useImageGenerationOptions());
    await waitFor(() => expect(result.current).not.toBeNull());
    expect(result.current?.available).toBe(false);
  });

  it('after invalidation a newly mounted consumer gets the new answer', async () => {
    h.imageGenerationOptions.mockResolvedValueOnce(UNAVAILABLE).mockResolvedValueOnce(AVAILABLE);

    const before = renderHook(() => useImageGenerationOptions());
    await waitFor(() => expect(before.result.current?.available).toBe(false));
    before.unmount();

    invalidateImageGenerationOptions();
    const after = renderHook(() => useImageGenerationOptions());
    await waitFor(() => expect(after.result.current?.available).toBe(true));
    expect(h.imageGenerationOptions).toHaveBeenCalledTimes(2);
  });
});
