import { useEffect, useState } from 'react';
import { api } from '../services/api';
import type { ImageGenerationOptions } from '../types/image';

const TTL_MS = 5 * 60 * 1000;

const UNAVAILABLE: ImageGenerationOptions = {
  available: false,
  max_prompt_chars: 0,
  default_preset: null,
  presets: [],
  edit: null,
};

let cached: { value: ImageGenerationOptions; at: number } | null = null;
let inflight: Promise<ImageGenerationOptions> | null = null;
let generation = 0;

/** One availability probe for the whole app: shared in flight, cached for 5 minutes. */
export function getImageGenerationOptions(): Promise<ImageGenerationOptions> {
  if (cached && Date.now() - cached.at < TTL_MS) return Promise.resolve(cached.value);
  if (inflight) return inflight;
  const gen = generation;
  const request: Promise<ImageGenerationOptions> = Promise.resolve()
    .then(() => api.imageGenerationOptions())
    .catch(() => UNAVAILABLE)
    .then((value) => {
      const result = value ?? UNAVAILABLE;
      if (gen === generation) {
        cached = { value: result, at: Date.now() };
        inflight = null;
      }
      return result;
    });
  inflight = request;
  return request;
}

export function invalidateImageGenerationOptions(): void {
  generation += 1;
  cached = null;
  inflight = null;
}

export function __resetImageGenerationOptionsCacheForTests(): void {
  invalidateImageGenerationOptions();
}

/** null until the probe answers. */
export function useImageGenerationOptions(): ImageGenerationOptions | null {
  const [options, setOptions] = useState<ImageGenerationOptions | null>(null);
  useEffect(() => {
    let cancelled = false;
    void getImageGenerationOptions().then((o) => {
      if (!cancelled) setOptions(o);
    });
    return () => {
      cancelled = true;
    };
  }, []);
  return options;
}
