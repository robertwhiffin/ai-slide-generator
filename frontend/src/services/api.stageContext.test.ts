/**
 * Architect stage awareness, Task 1: both chat transports carry the staged slide as `stage_slide`.
 *
 * Contract (task brief + PLAN-CORRECTIONS C3): `stageSlide?: { slide_number, slide_id? }` is APPENDED
 * after `deckMode` on sendChatMessage, streamChat, startPolling and submitChatAsync, and serialised as
 * the optional `stage_slide` JSON field. Without a stage the field is absent. Existing parameter
 * positions are unchanged, so slide_context / image_ids / agent_config / deck_mode still land.
 *
 * Behavioural only: the real `api` with a stubbed `fetch`, asserting the JSON body each transport
 * POSTs (precedent: services/__tests__/chatDeckMode.test.ts). The sendChatMessage cases assert the
 * URL too, so a green result cannot come from the other transport.
 *
 * Mutations each guards:
 *   - streamChat body lacks stage_slide                       -> the streamChat and SSE threading tests.
 *   - submitChatAsync body lacks stage_slide                  -> submitChatAsync and polling threading tests.
 *   - sendChatMessage drops stageSlide for either transport   -> that transport's threading test.
 *   - startPolling drops stageSlide before submitChatAsync    -> the polling threading test.
 *   - stageSlide inserted BEFORE an existing parameter (positions shifted) -> "the rest of the body".
 *   - stage_slide reshaped (e.g. a bare number, an invented id) -> the id-less case.
 *   - stage_slide sent as null/{} when no stage                 -> the omission controls.
 */

import { api, type DeckMode } from './api';

interface Posted { url: string; body: Record<string, unknown> }

/** Structural mirror of the StageSlideContext the task adds to types/slide.ts. */
interface StageSlide { slide_number: number; slide_id?: string }

/** Answers every POST with an empty 200 SSE/JSON body and records the URL and parsed JSON body. */
function stubFetch(posted: Posted[]) {
  const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    if (init?.method === 'POST' && typeof init.body === 'string') {
      posted.push({ url, body: JSON.parse(init.body) as Record<string, unknown> });
    }
    if (url.includes('/api/chat/async')) {
      return new Response(JSON.stringify({ request_id: 'req-stage' }), { status: 200 });
    }
    return new Response('data: {"type":"complete"}\n\n', { status: 200 });
  });
  vi.stubGlobal('fetch', fetchMock);
  return fetchMock;
}

// The transport functions as the task extends them: one more trailing argument. Typed loosely so this
// file compiles before and after the change; the runtime call is what is under test.
type Loose = (...args: unknown[]) => unknown;
const streamChat = (...a: unknown[]) => (api.streamChat as unknown as Loose).apply(api, a) as () => void;
const submitChatAsync = (...a: unknown[]) =>
  (api.submitChatAsync as unknown as Loose).apply(api, a) as Promise<{ request_id: string }>;
const sendChatMessage = (...a: unknown[]) => (api.sendChatMessage as unknown as Loose).apply(api, a) as () => void;

const STAGE: StageSlide = { slide_number: 3, slide_id: 'slide-uuid-c' };
const SLIDE_CONTEXT = { indices: [1], slide_htmls: ['<div class="slide">two</div>'] };
const AGENT_CONFIG = { tools: [] };
const MODE: DeckMode = 'agent';

describe('stage_slide on the chat request bodies', () => {
  let cancel: (() => void) | null = null;

  afterEach(() => {
    cancel?.();
    cancel = null;
    vi.unstubAllGlobals();
    vi.unstubAllEnvs();
  });

  it('streamChat POSTs stage_slide to /api/chat/stream, beside every existing field', async () => {
    const posted: Posted[] = [];
    const fetchMock = stubFetch(posted);

    cancel = streamChat('sess-1', 'make the title bigger', SLIDE_CONTEXT, () => {}, () => {}, ['img-1'], AGENT_CONFIG, MODE, STAGE);
    await vi.waitFor(() => expect(fetchMock).toHaveBeenCalled());

    expect(posted).toHaveLength(1);
    expect(posted[0].url).toContain('/api/chat/stream');
    expect(posted[0].body.stage_slide).toEqual({ slide_number: 3, slide_id: 'slide-uuid-c' });
    // The rest of the body is unchanged: no existing parameter moved.
    expect(posted[0].body).toMatchObject({
      session_id: 'sess-1',
      message: 'make the title bigger',
      slide_context: { indices: [1], slide_htmls: ['<div class="slide">two</div>'] },
      image_ids: ['img-1'],
      agent_config: { tools: [] },
      deck_mode: 'agent',
    });
  });

  it('submitChatAsync POSTs stage_slide to /api/chat/async, beside every existing field', async () => {
    const posted: Posted[] = [];
    stubFetch(posted);

    await expect(submitChatAsync('sess-1', 'make the title bigger', SLIDE_CONTEXT, ['img-1'], AGENT_CONFIG, MODE, STAGE))
      .resolves.toEqual({ request_id: 'req-stage' });

    expect(posted).toHaveLength(1);
    expect(posted[0].url).toContain('/api/chat/async');
    expect(posted[0].body.stage_slide).toEqual({ slide_number: 3, slide_id: 'slide-uuid-c' });
    expect(posted[0].body).toMatchObject({
      session_id: 'sess-1',
      message: 'make the title bigger',
      slide_context: { indices: [1], slide_htmls: ['<div class="slide">two</div>'] },
      image_ids: ['img-1'],
      agent_config: { tools: [] },
      deck_mode: 'agent',
    });
  });

  it('an id-less stage (older slide data) is sent as just its number', async () => {
    const posted: Posted[] = [];
    stubFetch(posted);

    await submitChatAsync('sess-1', 'hello', undefined, undefined, undefined, MODE, { slide_number: 2 });

    expect(posted[0].body.stage_slide).toEqual({ slide_number: 2 });
  });

  it('sendChatMessage threads stage_slide to the SSE transport', async () => {
    const posted: Posted[] = [];
    const fetchMock = stubFetch(posted);

    cancel = sendChatMessage('sess-1', 'hello', undefined, () => {}, () => {}, undefined, undefined, MODE, STAGE);
    await vi.waitFor(() => expect(fetchMock).toHaveBeenCalled());

    expect(posted).toHaveLength(1);
    expect(posted[0].url).toContain('/api/chat/stream');
    expect(posted[0].body.stage_slide).toEqual({ slide_number: 3, slide_id: 'slide-uuid-c' });
    expect(posted[0].body.deck_mode).toBe('agent');
  });

  it('sendChatMessage threads stage_slide through startPolling to the async submit (polling, the production transport)', async () => {
    vi.stubEnv('VITE_USE_POLLING', 'true');
    const posted: Posted[] = [];
    const fetchMock = stubFetch(posted);

    cancel = sendChatMessage('sess-1', 'hello', undefined, () => {}, () => {}, undefined, undefined, MODE, STAGE);
    await vi.waitFor(() => expect(fetchMock).toHaveBeenCalled());

    expect(posted).toHaveLength(1);
    expect(posted[0].url).toContain('/api/chat/async');
    expect(posted[0].body.stage_slide).toEqual({ slide_number: 3, slide_id: 'slide-uuid-c' });
    expect(posted[0].body.deck_mode).toBe('agent');
  });
});

describe('no stage: the field is absent (controls; these pass before the change too)', () => {
  let cancel: (() => void) | null = null;

  afterEach(() => {
    cancel?.();
    cancel = null;
    vi.unstubAllGlobals();
    vi.unstubAllEnvs();
  });

  it.each<{ transport: string; polling: boolean; url: string }>([
    { transport: 'SSE', polling: false, url: '/api/chat/stream' },
    { transport: 'polling', polling: true, url: '/api/chat/async' },
  ])('sendChatMessage over $transport with no stage sends no stage_slide key', async ({ polling, url }) => {
    if (polling) vi.stubEnv('VITE_USE_POLLING', 'true');
    const posted: Posted[] = [];
    const fetchMock = stubFetch(posted);

    // Legacy callers stop at deckMode: the stage argument is simply not passed.
    cancel = sendChatMessage('sess-1', 'hello', undefined, () => {}, () => {}, undefined, undefined, 'legacy');
    await vi.waitFor(() => expect(fetchMock).toHaveBeenCalled());

    expect(posted).toHaveLength(1);
    expect(posted[0].url).toContain(url);
    expect(posted[0].body).not.toHaveProperty('stage_slide');
    expect(posted[0].body.deck_mode).toBe('legacy');
  });

  it('an explicit undefined stage is omitted as well', async () => {
    const posted: Posted[] = [];
    stubFetch(posted);

    await submitChatAsync('sess-1', 'hello', undefined, undefined, undefined, MODE, undefined);

    expect(posted[0].body).not.toHaveProperty('stage_slide');
  });
});
