/**
 * Image generation API client:
 * - `imageGenerationOptions()` GETs /api/images/generate/available and NEVER throws: any failure
 *   resolves to the "unavailable" fallback, so the UI simply hides the feature;
 * - `generateImage(req, onProgress)` POSTs JSON to /api/images/generate (202 + job), polls
 *   /api/images/generate/jobs/<job_id> through the shared export-job poller until `completed`, and
 *   resolves the job's `image`; a job `error` rejects with the job's message, a non-2xx POST
 *   rejects with the response `detail`;
 * - `editImageWithPrompt(id, req, onProgress)` POSTs JSON to /api/images/<id>/edit and polls the
 *   same job route.
 *
 * Contract: docs/superpowers/plans/2026-11-08-ai-image-generation-CORRECTIONS.md (Units B, C).
 * `fetch` is stubbed with a tiny fake server; fake timers skip the poller's 2 s waits.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { api, ApiError } from './api';
import type { ImageAsset, ImageGenerationOptions } from '../types/image';

const FALLBACK: ImageGenerationOptions = {
  available: false,
  max_prompt_chars: 0,
  default_preset: null,
  presets: [],
  edit: null,
};

const IMAGE: ImageAsset = {
  id: 'tok_new_rocket',
  filename: 'ai-a-rocket-icon-20261108T100000Z-1a2b3c4d.png',
  original_filename: 'ai-a-rocket-icon-20261108T100000Z-1a2b3c4d.png',
  mime_type: 'image/png',
  size_bytes: 812345,
  thumbnail_base64: 'data:image/png;base64,iVBORw0KGgo=',
  tags: ['ai_generated', 'gpt-image-2.6-flare', 'icon_png'],
  description: 'A rocket icon',
  category: 'content',
  uploaded_by: 'alice@example.com',
  is_active: true,
  created_at: '2026-11-08T10:00:00Z',
  updated_at: '2026-11-08T10:00:00Z',
};

const OPTIONS: ImageGenerationOptions = {
  available: true,
  max_prompt_chars: 2000,
  default_preset: 'icon_png',
  presets: [
    {
      id: 'icon_png',
      label: 'Transparent icon',
      description: 'Flat icon on a see-through PNG',
      output_format: 'png',
      category: 'content',
      transparent: true,
      models: [{ id: 'gpt-image-2.6-flare', label: 'GPT Image 2.6 Flare', description: 'Newest' }],
      default_model: 'gpt-image-2.6-flare',
      qualities: ['low', 'medium', 'high'],
      default_quality: 'low',
    },
  ],
  edit: {
    models: [{ id: 'gpt-image-2.6-flare', label: 'GPT Image 2.6 Flare', description: 'Newest' }],
    default_model: 'gpt-image-2.6-flare',
    qualities: ['low', 'medium', 'high'],
    default_quality: 'low',
  },
};

// ---------------------------------------------------------------------------------------------
// Fake server
// ---------------------------------------------------------------------------------------------

type FakeResponse = {
  ok: boolean;
  status: number;
  statusText: string;
  headers: Headers;
  json: () => Promise<unknown>;
  text: () => Promise<string>;
};

function respond(status: number, body?: unknown, { badJson = false } = {}): FakeResponse {
  const text = badJson ? '<html>Bad gateway</html>' : JSON.stringify(body ?? null);
  return {
    ok: status >= 200 && status < 300,
    status,
    statusText: String(status),
    headers: new Headers({ 'content-type': badJson ? 'text/html' : 'application/json' }),
    json: async () => {
      if (badJson) throw new SyntaxError('Unexpected token < in JSON');
      return JSON.parse(text);
    },
    text: async () => text,
  };
}

type Call = { url: string; method: string; headers: Record<string, string>; body: unknown };

/**
 * Answers the start POST with `post`, then each poll of the job route with the next entry of
 * `polls` (the last one repeats). Records every request.
 */
function fakeServer({ post, polls = [] }: { post: FakeResponse; polls?: Array<Record<string, unknown>> }) {
  const calls: Call[] = [];
  let pollIndex = 0;
  const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    const method = (init?.method ?? 'GET').toUpperCase();
    const headers: Record<string, string> = {};
    new Headers(init?.headers).forEach((value, key) => {
      headers[key] = value;
    });
    let body: unknown = init?.body;
    if (typeof body === 'string') {
      try {
        body = JSON.parse(body);
      } catch {
        /* leave as string */
      }
    }
    calls.push({ url, method, headers, body });

    if (method === 'POST') return post;
    if (/\/api\/images\/generate\/jobs\/[^/]+$/.test(new URL(url, 'http://x').pathname)) {
      const answer = polls[Math.min(pollIndex, polls.length - 1)];
      pollIndex += 1;
      return respond(200, answer);
    }
    return respond(404, { detail: 'Not Found' });
  });
  vi.stubGlobal('fetch', fetchMock);
  return { calls, fetchMock };
}

const pathOf = (url: string) => new URL(url, 'http://x').pathname;
const pollCalls = (calls: Call[]) => calls.filter((c) => c.method === 'GET');

const job = (status: string, extra: Record<string, unknown> = {}) => ({
  job_id: 'job-123',
  status,
  progress: 0,
  total_slides: 0,
  status_message: null,
  error: null,
  image: null,
  ...extra,
});

/** Settle a promise while advancing fake time, without leaving a rejection unhandled. */
async function run<T>(promise: Promise<T>, ms = 30_000) {
  const settled = promise.then(
    (value) => ({ ok: true as const, value }),
    (error: unknown) => ({ ok: false as const, error }),
  );
  await vi.advanceTimersByTimeAsync(ms);
  return settled;
}

describe('image generation API client', () => {
  beforeEach(() => {
    vi.useFakeTimers();
    vi.spyOn(console, 'log').mockImplementation(() => {}); // the poller logs each poll
  });

  afterEach(() => {
    vi.useRealTimers();
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  describe('imageGenerationOptions', () => {
    it('GETs /api/images/generate/available and resolves the server options', async () => {
      const fetchMock = vi.fn(async () => respond(200, OPTIONS));
      vi.stubGlobal('fetch', fetchMock);

      await expect(api.imageGenerationOptions()).resolves.toEqual(OPTIONS);
      expect(fetchMock).toHaveBeenCalledTimes(1);
      const [url, init] = fetchMock.mock.calls[0] as unknown as [string, RequestInit | undefined];
      expect(pathOf(String(url))).toBe('/api/images/generate/available');
      expect((init?.method ?? 'GET').toUpperCase()).toBe('GET');
    });

    it('resolves the unavailable fallback on a network error', async () => {
      vi.stubGlobal('fetch', vi.fn(async () => Promise.reject(new TypeError('Failed to fetch'))));
      await expect(api.imageGenerationOptions()).resolves.toStrictEqual(FALLBACK);
    });

    it('resolves the unavailable fallback on a 500', async () => {
      vi.stubGlobal('fetch', vi.fn(async () => respond(500, { detail: 'Internal Server Error' })));
      await expect(api.imageGenerationOptions()).resolves.toStrictEqual(FALLBACK);
    });

    it('resolves the unavailable fallback on a 404 (older server without the route)', async () => {
      vi.stubGlobal('fetch', vi.fn(async () => respond(404, { detail: 'Not Found' })));
      await expect(api.imageGenerationOptions()).resolves.toStrictEqual(FALLBACK);
    });

    it('resolves the unavailable fallback when a 200 body is not JSON', async () => {
      vi.stubGlobal('fetch', vi.fn(async () => respond(200, undefined, { badJson: true })));
      await expect(api.imageGenerationOptions()).resolves.toStrictEqual(FALLBACK);
    });
  });

  describe('generateImage', () => {
    const REQ = { prompt: 'A rocket icon', preset: 'icon_png', model: 'gpt-image-2.6-flare', quality: 'low' };

    it('POSTs JSON to /api/images/generate, polls the job until completed and resolves job.image', async () => {
      const { calls } = fakeServer({
        post: respond(202, job('pending', { status_message: 'Queued' })),
        polls: [
          job('pending', { status_message: 'Queued' }),
          job('running', { status_message: 'Generating image...' }),
          job('running', { status_message: 'Saving...' }),
          job('completed', { status_message: 'Done', image: IMAGE }),
        ],
      });
      const onProgress = vi.fn();

      const result = await run(api.generateImage(REQ, onProgress));

      expect(result).toEqual({ ok: true, value: IMAGE });

      const post = calls[0];
      expect(post.method).toBe('POST');
      expect(pathOf(post.url)).toBe('/api/images/generate');
      expect(post.headers['content-type']).toBe('application/json');
      expect(post.body).toStrictEqual(REQ);

      const polls = pollCalls(calls);
      expect(polls).toHaveLength(4);
      for (const poll of polls) {
        expect(poll.url).toBe(`${post.url}/jobs/job-123`); // same base URL as the POST
      }
      // Polling stops at the terminal state.
      expect(calls).toHaveLength(5);

      const statuses = onProgress.mock.calls.map((c) => c[2]);
      expect(statuses).toContain('Generating image...');
      expect(statuses).toContain('Saving...');
    });

    it('rejects with the job error message when the job ends in error', async () => {
      fakeServer({
        post: respond(202, job('pending')),
        polls: [
          job('running', { status_message: 'Generating image...' }),
          job('error', { error: 'The image model is rate limited (429). Try again shortly.' }),
        ],
      });

      const result = await run(api.generateImage(REQ));

      expect(result.ok).toBe(false);
      const error = (result as { error: unknown }).error;
      expect(error).toBeInstanceOf(ApiError);
      expect((error as Error).message).toBe('The image model is rate limited (429). Try again shortly.');
    });

    it('rejects when a completed job carries no image', async () => {
      fakeServer({ post: respond(202, job('pending')), polls: [job('completed', { image: null })] });

      const result = await run(api.generateImage(REQ));

      expect(result.ok).toBe(false);
      expect((result as { error: unknown }).error).toBeInstanceOf(ApiError);
      expect(((result as { error: Error }).error).message).toBe('No image returned');
    });

    it('rejects a non-2xx POST with its detail and status, without polling', async () => {
      const { calls } = fakeServer({ post: respond(400, { detail: "Model 'gpt-image-2.5-flare' does not support svg" }) });

      const result = await run(api.generateImage({ ...REQ, preset: 'icon_svg', model: 'gpt-image-2.5-flare' }));

      expect(result.ok).toBe(false);
      const error = (result as { error: unknown }).error as ApiError;
      expect(error).toBeInstanceOf(ApiError);
      expect(error.status).toBe(400);
      expect(error.message).toBe("Model 'gpt-image-2.5-flare' does not support svg");
      expect(pollCalls(calls)).toHaveLength(0);
    });

    it('rejects a 429 POST with its detail', async () => {
      fakeServer({ post: respond(429, { detail: 'Too many image generations in flight. Try again shortly.' }) });

      const result = await run(api.generateImage(REQ));

      const error = (result as { error: unknown }).error as ApiError;
      expect(error).toBeInstanceOf(ApiError);
      expect(error.status).toBe(429);
      expect(error.message).toBe('Too many image generations in flight. Try again shortly.');
    });

    it('falls back to "Image generation failed" when the error body has no detail', async () => {
      fakeServer({ post: respond(502, undefined, { badJson: true }) });

      const result = await run(api.generateImage(REQ));

      const error = (result as { error: unknown }).error as ApiError;
      expect(error).toBeInstanceOf(ApiError);
      expect(error.status).toBe(502);
      expect(error.message).toBe('Image generation failed');
    });
  });

  describe('editImageWithPrompt', () => {
    const EDIT = { prompt: 'Make the sky orange', model: 'gpt-image-2.6-flare', quality: 'medium' };

    it('POSTs JSON to /api/images/<id>/edit, polls the generation job route and resolves job.image', async () => {
      const edited = { ...IMAGE, id: 'tok_edited', tags: ['ai_generated', 'ai_edit', 'gpt-image-2.6-flare'] };
      const { calls } = fakeServer({
        post: respond(202, job('pending', { job_id: 'job-edit-9' })),
        polls: [
          job('running', { job_id: 'job-edit-9', status_message: 'Generating image...' }),
          job('completed', { job_id: 'job-edit-9', image: edited }),
        ],
      });
      const onProgress = vi.fn();

      const result = await run(api.editImageWithPrompt('tok_team_photo', EDIT, onProgress));

      expect(result).toEqual({ ok: true, value: edited });

      const post = calls[0];
      expect(post.method).toBe('POST');
      expect(pathOf(post.url)).toBe('/api/images/tok_team_photo/edit');
      expect(post.headers['content-type']).toBe('application/json');
      expect(post.body).toStrictEqual(EDIT);

      const polls = pollCalls(calls);
      expect(polls).toHaveLength(2);
      expect(polls.map((p) => pathOf(p.url))).toEqual([
        '/api/images/generate/jobs/job-edit-9',
        '/api/images/generate/jobs/job-edit-9',
      ]);
      // Same origin/base as the POST.
      expect(polls[0].url.slice(0, polls[0].url.indexOf('/api/'))).toBe(post.url.slice(0, post.url.indexOf('/api/')));
      expect(onProgress.mock.calls.map((c) => c[2])).toContain('Generating image...');
    });

    it('rejects a non-2xx POST with its detail', async () => {
      const { calls } = fakeServer({ post: respond(400, { detail: 'SVG images cannot be edited' }) });

      const result = await run(api.editImageWithPrompt('tok_svg', EDIT));

      const error = (result as { error: unknown }).error as ApiError;
      expect(error).toBeInstanceOf(ApiError);
      expect(error.status).toBe(400);
      expect(error.message).toBe('SVG images cannot be edited');
      expect(pollCalls(calls)).toHaveLength(0);
    });

    it('rejects with the job error message when the edit job fails', async () => {
      fakeServer({
        post: respond(202, job('pending')),
        polls: [job('error', { error: 'The app identity cannot use the image model (403).' })],
      });

      const result = await run(api.editImageWithPrompt('tok_team_photo', EDIT));

      expect(result.ok).toBe(false);
      expect(((result as { error: Error }).error).message).toBe('The app identity cannot use the image model (403).');
    });
  });
});
