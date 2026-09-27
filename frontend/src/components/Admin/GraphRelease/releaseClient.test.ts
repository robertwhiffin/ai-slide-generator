import { afterEach, describe, expect, it, vi } from 'vitest';
import {
  RELEASE_NOTE_BLANK_ERROR,
  syntheticNothingToPublish,
  syntheticPublicationInvalid,
  syntheticPublicationNotReady,
  syntheticPublishSuccess,
  syntheticReleasePreview,
  syntheticStalePublication,
} from '../../../../tests/fixtures/mocks';
import {
  AGENT_KEYS,
  AgentDefinitionApiError,
  InvalidReleaseResponseError,
  RELEASE_DIFF_FIELDS,
  getReleasePreview,
  parsePublishReleaseFailure,
  parsePublishReleaseSuccessResponse,
  parseReleasePreviewResponse,
  publishRelease,
} from '../../../api/agentDefinitions';

// ============================================================
// #269 Task 6: the strict release preview and publication clients
// ============================================================

function stubFetch(status: number, body: unknown) {
  const fetchMock = vi.fn().mockResolvedValue({
    ok: status >= 200 && status < 300,
    status,
    statusText: '',
    json: vi.fn().mockResolvedValue(body),
  });
  vi.stubGlobal('fetch', fetchMock);
  return fetchMock;
}

function onlyCall(fetchMock: ReturnType<typeof vi.fn>) {
  expect(fetchMock).toHaveBeenCalledTimes(1);
  return fetchMock.mock.calls[0] as [string, RequestInit];
}

async function rejection(promise: Promise<unknown>): Promise<unknown> {
  try {
    await promise;
  } catch (error) {
    return error;
  }
  throw new Error('expected a rejection');
}

type Mutable = Record<string, unknown>;

function withoutKey<T extends object>(value: T, key: string): Mutable {
  const copy = structuredClone(value) as Mutable;
  delete copy[key];
  return copy;
}

afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

describe('parseReleasePreviewResponse', () => {
  it('accepts the exact preview body unchanged', () => {
    const body = syntheticReleasePreview();
    expect(parseReleasePreviewResponse(structuredClone(body))).toEqual(body);
  });

  it('accepts an empty changed list, validation issues and every diff field in order', () => {
    const body = syntheticReleasePreview({
      changed: [],
      publishable: false,
      validation_issues: [{ field: 'definitions.architect.prompt_text', code: 'blank', message: 'Prompt text must not be blank.' }],
    });
    expect(parseReleasePreviewResponse(body)).toEqual(body);
    const every = syntheticReleasePreview();
    every.changed[0].field_diffs = RELEASE_DIFF_FIELDS.map((field) => ({ field, published: null, candidate: { v: 1 } }));
    expect(parseReleasePreviewResponse(every)).toEqual(every);
  });

  it.each(['draft', 'active_release', 'next_version_number', 'changed', 'readiness', 'validation_issues', 'publishable'])(
    'rejects a preview missing %s',
    (key) => {
      expect(parseReleasePreviewResponse(withoutKey(syntheticReleasePreview(), key))).toBeNull();
    },
  );

  it('rejects extra keys at every level', () => {
    expect(parseReleasePreviewResponse({ ...syntheticReleasePreview(), gate: 'open' })).toBeNull();
    const changed = syntheticReleasePreview();
    (changed.changed[0] as unknown as Mutable).diff = 'x';
    expect(parseReleasePreviewResponse(changed)).toBeNull();
    const diff = syntheticReleasePreview();
    (diff.changed[0].field_diffs[0] as unknown as Mutable).kind = 'x';
    expect(parseReleasePreviewResponse(diff)).toBeNull();
    const release = syntheticReleasePreview();
    (release.active_release as unknown as Mutable).status = 'active';
    expect(parseReleasePreviewResponse(release)).toBeNull();
    const issue = syntheticReleasePreview({ validation_issues: [{ field: 'x', code: 'y', message: 'z' }] });
    (issue.validation_issues[0] as unknown as Mutable).hint = 'h';
    expect(parseReleasePreviewResponse(issue)).toBeNull();
  });

  it.each([
    ['an uppercase published hash', { published_content_hash: 'A'.repeat(64) }],
    ['a short candidate hash', { candidate_hash: 'c'.repeat(63) }],
    ['a non-hex candidate hash', { candidate_hash: 'g'.repeat(64) }],
    ['a zero revision id', { published_revision_id: 0 }],
    ['an unknown role', { agent_key: 'foreman' }],
    ['no field diffs', { field_diffs: [] }],
    ['an unknown diff field', { field_diffs: [{ field: 'model', published: 1, candidate: 2 }] }],
    ['diff fields out of order', { field_diffs: [
      { field: 'model.temperature', published: 0.2, candidate: 0.4 },
      { field: 'prompt_text', published: 'a', candidate: 'b' },
    ] }],
    ['a repeated diff field', { field_diffs: [
      { field: 'prompt_text', published: 'a', candidate: 'b' },
      { field: 'prompt_text', published: 'a', candidate: 'c' },
    ] }],
    ['a non-JSON diff value', { field_diffs: [{ field: 'model.top_p', published: Number.NaN, candidate: 1 }] }],
  ])('rejects a changed role with %s', (_label, override) => {
    const body = syntheticReleasePreview();
    Object.assign(body.changed[0], override);
    expect(parseReleasePreviewResponse(body)).toBeNull();
  });

  it('rejects changed roles out of Graph order or repeated', () => {
    const builder = { ...syntheticReleasePreview().changed[0], agent_key: 'builder' as const };
    const architect = syntheticReleasePreview().changed[0];
    expect(parseReleasePreviewResponse(syntheticReleasePreview({ changed: [architect, builder] }))).not.toBeNull();
    expect(parseReleasePreviewResponse(syntheticReleasePreview({ changed: [builder, architect] }))).toBeNull();
    expect(parseReleasePreviewResponse(syntheticReleasePreview({ changed: [architect, architect] }))).toBeNull();
  });

  it.each([
    ['a next version below 2', { next_version_number: 1 }],
    ['a fractional next version', { next_version_number: 2.5 }],
    ['a string publishable', { publishable: 'true' }],
    ['a malformed readiness', { readiness: { all_ready: true } }],
    ['a readiness status label', { readiness: { ...syntheticReleasePreview().readiness, agents: [{
      ...syntheticReleasePreview().readiness.agents[0],
      cases: [{ ...syntheticReleasePreview().readiness.agents[0].cases[0], status: 'Approved' }],
    }] } }],
    ['a malformed draft', { draft: { ...syntheticReleasePreview().draft, lock_version: -1 } }],
  ])('rejects a preview with %s', (_label, override) => {
    expect(parseReleasePreviewResponse({ ...syntheticReleasePreview(), ...override })).toBeNull();
  });
});

describe('parsePublishReleaseSuccessResponse', () => {
  it('accepts the exact 200 body unchanged', () => {
    const body = syntheticPublishSuccess();
    expect(parsePublishReleaseSuccessResponse(structuredClone(body))).toEqual(body);
  });

  it.each(['release', 'previous_release_id', 'changed_agents', 'mappings', 'evidence', 'draft'])(
    'rejects a 200 missing %s',
    (key) => {
      expect(parsePublishReleaseSuccessResponse(withoutKey(syntheticPublishSuccess(), key))).toBeNull();
    },
  );

  it('requires exactly the seven mappings, in Graph order', () => {
    const six = syntheticPublishSuccess();
    delete (six.mappings as Partial<typeof six.mappings>).deck_reviewer;
    expect(parsePublishReleaseSuccessResponse(six)).toBeNull();
    const eight = syntheticPublishSuccess();
    (eight.mappings as unknown as Mutable).foreman = eight.mappings.architect;
    expect(parsePublishReleaseSuccessResponse(eight)).toBeNull();
    const reordered = syntheticPublishSuccess();
    reordered.mappings = Object.fromEntries([...AGENT_KEYS].reverse().map((key) => [key, reordered.mappings[key]])) as typeof reordered.mappings;
    expect(parsePublishReleaseSuccessResponse(reordered)).toBeNull();
  });

  it.each([
    ['an extra top-level key', (body: Mutable) => { body.status = 'ok'; }],
    ['an extra mapping key', (body: Mutable) => { (body.mappings as Record<string, Mutable>).architect.note = 'x'; }],
    ['a non-sha256 mapping hash', (body: Mutable) => { (body.mappings as Record<string, Mutable>).builder.content_hash = 'B'.repeat(64); }],
    ['a string reused flag', (body: Mutable) => { (body.mappings as Record<string, Mutable>).builder.reused = 'yes'; }],
    ['no changed agents', (body: Mutable) => { body.changed_agents = []; }],
    ['an unknown changed agent', (body: Mutable) => { body.changed_agents = ['foreman']; }],
    ['a well-formed restore evidence item', (body: Mutable) => {
      const item = (body.evidence as Mutable[])[0];
      item.evidence_kind = 'historical_restore';
      item.source_release_id = 41;
    }],
    ['a restore evidence kind without a source', (body: Mutable) => { (body.evidence as Mutable[])[0].evidence_kind = 'historical_restore'; }],
    ['an approval with a source', (body: Mutable) => { (body.evidence as Mutable[])[0].source_release_id = 41; }],
    ['an extra evidence key', (body: Mutable) => { (body.evidence as Mutable[])[0].note = 'x'; }],
    ['a missing release key', (body: Mutable) => { delete (body.release as Mutable).effective_to; }],
  ])('rejects a 200 with %s', (_label, mutate) => {
    const body = syntheticPublishSuccess() as unknown as Mutable;
    mutate(body);
    expect(parsePublishReleaseSuccessResponse(body)).toBeNull();
  });
});

describe('parsePublishReleaseFailure', () => {
  it.each([
    ['stale', 409, syntheticStalePublication()],
    ['nothing to publish', 409, syntheticNothingToPublish()],
    ['not ready', 409, syntheticPublicationNotReady()],
    ['no required case', 409, syntheticPublicationNotReady([
      { agent_key: 'architect', test_case_id: null, code: 'no_required_case' },
      { agent_key: 'builder', test_case_id: 202, code: 'no_eligible_approval' },
    ])],
    ['invalid', 422, syntheticPublicationInvalid()],
  ])('accepts the exact %s body', (_label, status, body) => {
    expect(parsePublishReleaseFailure(status, structuredClone(body))).toEqual(body);
  });

  it.each([
    ['an unknown 409 code', 409, { ...syntheticNothingToPublish(), code: 'stale_draft' }],
    ['a 409 code on a 422', 422, syntheticStalePublication()],
    ['a 422 code on a 409', 409, syntheticPublicationInvalid()],
    ['a stale extra key', 409, { ...syntheticStalePublication(), client_candidate: null }],
    ['a stale missing current lock', 409, withoutKey(syntheticStalePublication(), 'current_lock_version')],
    ['a stale negative current lock', 409, { ...syntheticStalePublication(), current_lock_version: -1 }],
    ['a stale full release', 409, { ...syntheticStalePublication(), active_release: syntheticPublishSuccess().release }],
    ['nothing-to-publish extra key', 409, { ...syntheticNothingToPublish(), changed: [] }],
    ['not-ready no gaps', 409, syntheticPublicationNotReady([])],
    ['a gap code this client does not know', 409, syntheticPublicationNotReady([
      { agent_key: 'architect', test_case_id: 101, code: 'no_approval' as 'no_eligible_approval' },
    ])],
    ['a no_required_case gap with a case id', 409, syntheticPublicationNotReady([
      { agent_key: 'architect', test_case_id: 101, code: 'no_required_case' },
    ])],
    ['a no_eligible_approval gap without a case id', 409, syntheticPublicationNotReady([
      { agent_key: 'architect', test_case_id: null, code: 'no_eligible_approval' },
    ])],
    ['a gap extra key', 409, syntheticPublicationNotReady([
      { agent_key: 'architect', test_case_id: 101, code: 'no_eligible_approval', message: 'x' } as never,
    ])],
    ['a not-ready malformed readiness', 409, { ...syntheticPublicationNotReady(), readiness: {} }],
    ['an empty 422 issue list', 422, syntheticPublicationInvalid([])],
    ['a 422 issue extra key', 422, syntheticPublicationInvalid([{ ...RELEASE_NOTE_BLANK_ERROR, hint: 'h' } as never])],
    ['the draft envelope', 422, { code: 'invalid_draft', errors: [RELEASE_NOTE_BLANK_ERROR] }],
    ['no body', 409, null],
  ])('rejects %s', (_label, status, body) => {
    expect(parsePublishReleaseFailure(status, body)).toBeNull();
  });
});

describe('getReleasePreview', () => {
  it('GETs the preview route and returns the strictly parsed body', async () => {
    const fetchMock = stubFetch(200, syntheticReleasePreview());

    await expect(getReleasePreview()).resolves.toEqual(syntheticReleasePreview());

    const [url, init] = onlyCall(fetchMock);
    expect(url).toMatch(/\/api\/admin\/agent-definitions\/release-preview$/);
    expect(init.method).toBe('GET');
    expect(init.body).toBeUndefined();
  });

  it('shares one in-flight read, so a StrictMode remount does not read the prompts twice', async () => {
    const fetchMock = stubFetch(200, syntheticReleasePreview());

    const [first, second] = await Promise.all([getReleasePreview(), getReleasePreview()]);

    expect(first).toEqual(second);
    expect(fetchMock).toHaveBeenCalledTimes(1);
    await getReleasePreview();
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });

  it('refuses a malformed 200 and surfaces any other status as an API error', async () => {
    stubFetch(200, { ...syntheticReleasePreview(), extra: true });
    expect(await rejection(getReleasePreview())).toBeInstanceOf(InvalidReleaseResponseError);

    stubFetch(403, { detail: 'Admin access required' });
    const error = await rejection(getReleasePreview());
    expect(error).toBeInstanceOf(AgentDefinitionApiError);
    expect((error as AgentDefinitionApiError).status).toBe(403);
  });
});

describe('publishRelease', () => {
  it('POSTs exactly { lock_version, release_note } and returns the parsed 200', async () => {
    const fetchMock = stubFetch(200, syntheticPublishSuccess());

    await expect(publishRelease({ lock_version: 3, release_note: 'Tighten the outline' }))
      .resolves.toEqual(syntheticPublishSuccess());

    const [url, init] = onlyCall(fetchMock);
    expect(url).toMatch(/\/api\/admin\/agent-definitions\/releases$/);
    expect(init.method).toBe('POST');
    expect(init.body).toBe('{"lock_version":3,"release_note":"Tighten the outline"}');
  });

  it('sends no extra key a caller smuggles in (the server forbids an actor)', async () => {
    const fetchMock = stubFetch(200, syntheticPublishSuccess());
    const smuggled = { lock_version: 3, release_note: 'n', actor: 'someone@example.com' };

    await publishRelease(smuggled);

    expect(JSON.parse(String(onlyCall(fetchMock)[1].body))).toEqual({ lock_version: 3, release_note: 'n' });
  });

  it('treats a 201 as an invalid response: the route answers 200 (ruling Q6)', async () => {
    stubFetch(201, syntheticPublishSuccess());
    expect(await rejection(publishRelease({ lock_version: 3, release_note: 'n' }))).toBeInstanceOf(AgentDefinitionApiError);
  });

  it.each([
    ['stale', 409, syntheticStalePublication()],
    ['nothing to publish', 409, syntheticNothingToPublish()],
    ['not ready', 409, syntheticPublicationNotReady()],
    ['invalid', 422, syntheticPublicationInvalid()],
  ])('throws the %s refusal with its strictly parsed payload', async (_label, status, body) => {
    stubFetch(status, body);

    const error = await rejection(publishRelease({ lock_version: 3, release_note: 'n' }));

    expect(error).toBeInstanceOf(AgentDefinitionApiError);
    expect((error as AgentDefinitionApiError).status).toBe(status);
    expect((error as AgentDefinitionApiError).payload).toEqual(body);
  });

  it.each([
    ['a malformed 200', 200, { ...syntheticPublishSuccess(), extra: 1 }],
    ['a malformed 409', 409, { code: 'stale_publication' }],
    ['a malformed 422', 422, { code: 'invalid_publication', errors: [] }],
  ])('refuses %s as an invalid response', async (_label, status, body) => {
    stubFetch(status, body);
    expect(await rejection(publishRelease({ lock_version: 3, release_note: 'n' }))).toBeInstanceOf(InvalidReleaseResponseError);
  });

  it('leaves a 500 a plain API error', async () => {
    stubFetch(500, { detail: 'Graph configuration is incomplete' });
    const error = await rejection(publishRelease({ lock_version: 3, release_note: 'n' }));
    expect(error).toBeInstanceOf(AgentDefinitionApiError);
    expect(error).not.toBeInstanceOf(InvalidReleaseResponseError);
    expect((error as AgentDefinitionApiError).status).toBe(500);
  });
});
