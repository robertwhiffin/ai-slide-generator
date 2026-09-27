import { afterEach, describe, expect, it, vi } from 'vitest';
import {
  RELEASE_NOTE_BLANK_ERROR,
  syntheticNothingToPublish,
  syntheticPublicationInvalid,
  syntheticPublicationNotReady,
  syntheticPublishSuccess,
  syntheticReleasePreview,
  syntheticStalePublication,
  syntheticBlockedRollbackPreview,
  syntheticReleaseComparison,
  syntheticReleaseDetail,
  syntheticReleaseHistory,
  syntheticHistoryEntry,
  syntheticRollbackIncompatible,
  syntheticRollbackInvalid,
  syntheticRollbackPreview,
  syntheticRollbackSuccess,
  syntheticStaleRollback,
  releaseRef,
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
  compareGraphRelease,
  getGraphRelease,
  getRollbackPreview,
  listGraphReleases,
  parseInstant,
  parseReleaseComparisonResponse,
  parseReleaseDetailResponse,
  parseReleaseHistoryListResponse,
  parseRollbackFailure,
  parseRollbackPreviewResponse,
  parseRollbackSuccessResponse,
  rollbackGraphRelease,
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

// ============================================================
// #270 Task 7: the strict history, comparison and rollback clients
// ============================================================

describe('parseInstant: instants, never strings (Task 6 concern 3)', () => {
  it('reads a zoneless SQLite timestamp as UTC, the same instant as its Z spelling', () => {
    expect(parseInstant('2026-09-27T10:00:00')).toBe(parseInstant('2026-09-27T10:00:00Z'));
    expect(parseInstant('2026-09-27T10:00:00.123456Z')).toBe(Date.UTC(2026, 8, 27, 10, 0, 0, 123));
    expect(parseInstant('2026-09-27T11:00:00+01:00')).toBe(parseInstant('2026-09-27T10:00:00Z'));
  });

  it('reads a zoneless value as UTC even on a non-UTC host (fix round 1: TZ-independent pin)', () => {
    const saved = process.env.TZ;
    try {
      process.env.TZ = 'Asia/Kolkata';
      // The switch took effect: local midnight is 05:30 ahead of UTC here.
      expect(new Date(2026, 0, 1).getTimezoneOffset()).toBe(-330);
      expect(parseInstant('2026-09-27T10:00:00')).toBe(Date.UTC(2026, 8, 27, 10, 0, 0));
      expect(parseInstant('2026-09-27T10:00:00.250')).toBe(Date.UTC(2026, 8, 27, 10, 0, 0, 250));
    } finally {
      if (saved === undefined) delete process.env.TZ;
      else process.env.TZ = saved;
    }
    expect(process.env.TZ).toBe(saved);
  });

  it.each(['', 'yesterday', '2026-09-27', '2026-13-40T99:00:00Z'])('refuses %j', (value) => {
    expect(parseInstant(value)).toBeNull();
  });
});

describe('parseReleaseHistoryListResponse', () => {
  it('accepts the exact list body unchanged', () => {
    const body = syntheticReleaseHistory();
    expect(parseReleaseHistoryListResponse(structuredClone(body))).toEqual(body);
  });

  it.each(['active_release', 'releases'])('rejects a list missing %s', (key) => {
    expect(parseReleaseHistoryListResponse(withoutKey(syntheticReleaseHistory(), key))).toBeNull();
  });

  it.each([
    'release_id', 'version_number', 'is_active', 'release_note', 'published_by', 'published_at',
    'effective_from', 'effective_to', 'previous', 'restored_from', 'restored_by', 'changed_agents',
  ])('rejects an entry missing %s', (key) => {
    const body = syntheticReleaseHistory() as unknown as { releases: Mutable[] };
    delete body.releases[1][key];
    expect(parseReleaseHistoryListResponse(body)).toBeNull();
  });

  it.each([
    ['an extra top-level key', (body: Mutable) => { body.total = 4; }],
    ['an extra entry key', (body: Mutable) => { (body.releases as Mutable[])[0].status = 'active'; }],
    ['an extra ref key', (body: Mutable) => { ((body.releases as Mutable[])[0].previous as Mutable).note = 'x'; }],
    ['no releases', (body: Mutable) => { body.releases = []; }],
    ['oldest first', (body: Mutable) => { (body.releases as Mutable[]).reverse(); }],
    ['two active rows', (body: Mutable) => { (body.releases as Mutable[])[1].is_active = true; }],
    ['an active ref naming another row', (body: Mutable) => { body.active_release = releaseRef(3); }],
    ['an active ref with a swapped id', (body: Mutable) => { body.active_release = { release_id: 4, version_number: 4 }; }],
    ['a zero version', (body: Mutable) => { (body.releases as Mutable[])[3].version_number = 0; }],
    ['a non-instant publish time', (body: Mutable) => { (body.releases as Mutable[])[0].published_at = 'today'; }],
    ['no changed roles', (body: Mutable) => { (body.releases as Mutable[])[0].changed_agents = []; }],
    ['changed roles out of Graph order', (body: Mutable) => { (body.releases as Mutable[])[0].changed_agents = ['builder', 'architect']; }],
    ['restored_by descending', (body: Mutable) => { (body.releases as Mutable[])[3].restored_by = [releaseRef(3), releaseRef(2)]; }],
  ])('rejects %s', (_label, mutate) => {
    const body = syntheticReleaseHistory() as unknown as Mutable;
    mutate(body);
    expect(parseReleaseHistoryListResponse(body)).toBeNull();
  });
});

describe('syntheticHistoryEntry: always valid instants (#270 Task 8 fixture)', () => {
  const ISO = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$/;
  const valid = (value: string | null) =>
    value === null || (ISO.test(value) && new Date(value).toISOString().replace('.000Z', 'Z') === value);

  it.each([1, 9, 10, 11, 12, 20, 45])('v%i has real, round-tripping ISO timestamps', (v) => {
    const entry = syntheticHistoryEntry(v);
    expect([entry.published_at, entry.effective_from, entry.effective_to].every(valid)).toBe(true);
  });

  it('keeps the existing v1-v9 strings and rolls v10 onward into October', () => {
    expect(syntheticHistoryEntry(4).published_at).toBe('2026-09-24T12:00:00Z');
    expect(syntheticHistoryEntry(9).effective_to).toBe('2026-09-30T12:00:00Z');
    expect(syntheticHistoryEntry(10).effective_from).toBe('2026-09-30T12:00:00Z');
    expect(syntheticHistoryEntry(10).effective_to).toBe('2026-10-01T12:00:00Z');
    expect(syntheticHistoryEntry(12, { active: true }).published_at).toBe('2026-10-02T12:00:00Z');
  });

  it('a v1-v12 history built from it parses', () => {
    const releases = [
      syntheticHistoryEntry(12, { active: true }),
      ...[11, 10, 9, 8, 7, 6, 5, 4].map((v) => syntheticHistoryEntry(v)),
      syntheticHistoryEntry(3, { restoredFrom: 1 }),
      syntheticHistoryEntry(2),
      syntheticHistoryEntry(1, { restoredBy: [3] }),
    ];
    const body = { active_release: releaseRef(12), releases };
    expect(parseReleaseHistoryListResponse(structuredClone(body))).toEqual(body);
  });
});

describe('parseReleaseDetailResponse', () => {
  it('accepts the exact detail body unchanged', () => {
    const body = syntheticReleaseDetail();
    expect(parseReleaseDetailResponse(structuredClone(body))).toEqual(body);
  });

  it.each(['release', 'definitions', 'evidence'])('rejects a detail missing %s', (key) => {
    expect(parseReleaseDetailResponse(withoutKey(syntheticReleaseDetail(), key))).toBeNull();
  });

  it.each([
    'agent_test_run_id', 'agent_key', 'test_case_id', 'test_case_version', 'evidence_kind', 'source',
    'verdict', 'verdict_reviewer', 'verdict_at', 'execution_status', 'deterministic_checks_passed', 'run_at',
  ])('rejects evidence missing %s', (key) => {
    const body = syntheticReleaseDetail() as unknown as { evidence: Mutable[] };
    delete body.evidence[0][key];
    expect(parseReleaseDetailResponse(body)).toBeNull();
  });

  it.each([
    ['six definitions', (body: Mutable) => { delete (body.definitions as Mutable).deck_reviewer; }],
    ['definitions out of Graph order', (body: Mutable) => {
      body.definitions = Object.fromEntries(Object.entries(body.definitions as Mutable).reverse());
    }],
    ['an extra definition key', (body: Mutable) => { ((body.definitions as Record<string, Mutable>).architect).note = 'x'; }],
    ['a non-object content', (body: Mutable) => { ((body.definitions as Record<string, Mutable>).architect).content = 'prompt'; }],
    ['a non-sha256 content hash', (body: Mutable) => { ((body.definitions as Record<string, Mutable>).builder).content_hash = 'x'; }],
    ['an extra evidence key', (body: Mutable) => { (body.evidence as Mutable[])[0].note = 'x'; }],
    ['an approval with a source', (body: Mutable) => { (body.evidence as Mutable[])[0].source = releaseRef(1); }],
    ['a restore without a source', (body: Mutable) => { (body.evidence as Mutable[])[1].source = null; }],
    ['an unknown evidence kind', (body: Mutable) => { (body.evidence as Mutable[])[0].evidence_kind = 'baseline'; }],
    ['an unknown verdict', (body: Mutable) => { (body.evidence as Mutable[])[0].verdict = 'Approved'; }],
    ['an unknown execution status', (body: Mutable) => { (body.evidence as Mutable[])[0].execution_status = 'ok'; }],
    ['a zero test case version', (body: Mutable) => { (body.evidence as Mutable[])[0].test_case_version = 0; }],
  ])('rejects %s', (_label, mutate) => {
    const body = syntheticReleaseDetail() as unknown as Mutable;
    mutate(body);
    expect(parseReleaseDetailResponse(body)).toBeNull();
  });
});

describe('parseReleaseComparisonResponse', () => {
  it('accepts the exact comparison body unchanged', () => {
    const body = syntheticReleaseComparison();
    expect(parseReleaseComparisonResponse(structuredClone(body))).toEqual(body);
  });

  it.each([
    ['a missing agent', (body: Mutable) => { (body.agents as Mutable[]).pop(); }],
    ['agents out of Graph order', (body: Mutable) => { (body.agents as Mutable[]).reverse(); }],
    ['an extra agent key', (body: Mutable) => { (body.agents as Mutable[])[0].note = 'x'; }],
    ['a #269 published/candidate diff', (body: Mutable) => {
      (body.agents as Mutable[])[0].field_diffs = [{ field: 'prompt_text', published: 'a', candidate: 'b' }];
    }],
    ['diff fields out of order', (body: Mutable) => { ((body.agents as Mutable[])[0].field_diffs as Mutable[]).reverse(); }],
    ['an extra top-level key', (body: Mutable) => { body.changed = []; }],
  ])('rejects %s', (_label, mutate) => {
    const body = syntheticReleaseComparison() as unknown as Mutable;
    mutate(body);
    expect(parseReleaseComparisonResponse(body)).toBeNull();
  });
});

describe('parseRollbackPreviewResponse', () => {
  it('accepts the exact restorable and blocked bodies unchanged', () => {
    for (const body of [syntheticRollbackPreview(), syntheticBlockedRollbackPreview()]) {
      expect(parseRollbackPreviewResponse(structuredClone(body))).toEqual(body);
    }
  });

  it.each([
    'source', 'active_release', 'next_version_number', 'lock_version', 'default_release_note', 'restorable',
    'blocked', 'issues', 'warnings', 'agents', 'evidence', 'draft_effect',
  ])('rejects a preview missing %s', (key) => {
    expect(parseRollbackPreviewResponse(withoutKey(syntheticRollbackPreview(), key))).toBeNull();
  });

  it.each([
    ['an extra top-level key', (body: Mutable) => { body.publishable = true; }],
    ['six draft effects', (body: Mutable) => { delete (body.draft_effect as Mutable).fixer; }],
    ['eight draft effects', (body: Mutable) => { (body.draft_effect as Mutable).foreman = 'unchanged'; }],
    ['draft effects out of Graph order', (body: Mutable) => {
      body.draft_effect = Object.fromEntries(Object.entries(body.draft_effect as Mutable).reverse());
    }],
    ['a draft effect label', (body: Mutable) => { (body.draft_effect as Mutable).architect = 'Pending edit kept'; }],
    ['a draft effect outside reset|kept|unchanged', (body: Mutable) => { (body.draft_effect as Mutable).builder = 'discarded'; }],
    ['blocked outside its three values', (body: Mutable) => { body.blocked = 'stale'; body.restorable = false; }],
    ['blocked but restorable', (body: Mutable) => { body.blocked = 'incompatible'; }],
    ['not blocked but not restorable', (body: Mutable) => { body.restorable = false; }],
    ['an extra evidence key', (body: Mutable) => { (body.evidence as Mutable[])[0].evidence_kind = 'historical_restore'; }],
    ['an extra warning key', (body: Mutable) => { body.warnings = [{ field: 'f', code: 'c', message: 'm', url: 'u' }]; }],
    ['a negative lock version', (body: Mutable) => { body.lock_version = -1; }],
    ['a next version below 2', (body: Mutable) => { body.next_version_number = 1; }],
    ['six agents', (body: Mutable) => { (body.agents as Mutable[]).pop(); }],
  ])('rejects %s', (_label, mutate) => {
    const body = syntheticRollbackPreview() as unknown as Mutable;
    mutate(body);
    expect(parseRollbackPreviewResponse(body)).toBeNull();
  });

  it('rejects a null blocked on a blocked preview (blocked is null exactly when restorable)', () => {
    const body = syntheticBlockedRollbackPreview() as unknown as Mutable;
    body.blocked = null;
    expect(parseRollbackPreviewResponse(body)).toBeNull();
  });
});

describe('parseRollbackSuccessResponse', () => {
  it('accepts the exact 200 body unchanged', () => {
    const body = syntheticRollbackSuccess();
    expect(parseRollbackSuccessResponse(structuredClone(body))).toEqual(body);
  });

  it.each(['release', 'restored_from', 'previous_release_id', 'changed_agents', 'mappings', 'evidence', 'draft', 'draft_effect'])(
    'rejects a 200 missing %s',
    (key) => {
      expect(parseRollbackSuccessResponse(withoutKey(syntheticRollbackSuccess(), key))).toBeNull();
    },
  );

  it.each([
    ['an extra top-level key', (body: Mutable) => { body.status = 'ok'; }],
    ['a mapping that is not reused', (body: Mutable) => { (body.mappings as Record<string, Mutable>).fixer.reused = false; }],
    ['six mappings', (body: Mutable) => { delete (body.mappings as Mutable).deck_reviewer; }],
    ['approval evidence', (body: Mutable) => {
      const item = (body.evidence as Mutable[])[0];
      item.evidence_kind = 'approval';
      item.source_release_id = null;
    }],
    ['a restore evidence item without a source', (body: Mutable) => { (body.evidence as Mutable[])[0].source_release_id = null; }],
    ['an extra evidence key', (body: Mutable) => { (body.evidence as Mutable[])[0].note = 'x'; }],
    ['a draft effect outside reset|kept|unchanged', (body: Mutable) => { (body.draft_effect as Mutable).architect = 'Reset'; }],
    ['no changed agents', (body: Mutable) => { body.changed_agents = []; }],
    ['a restored_from with an extra key', (body: Mutable) => { (body.restored_from as Mutable).note = 'x'; }],
  ])('rejects a 200 with %s', (_label, mutate) => {
    const body = syntheticRollbackSuccess() as unknown as Mutable;
    mutate(body);
    expect(parseRollbackSuccessResponse(body)).toBeNull();
  });
});

describe('parseRollbackFailure', () => {
  it.each([
    ['stale', 409, syntheticStaleRollback()],
    ['source active', 409, { code: 'rollback_source_active', active_release: releaseRef(4) }],
    ['matches active', 409, { code: 'rollback_matches_active', active_release: releaseRef(4), source: releaseRef(2) }],
    ['incompatible', 422, syntheticRollbackIncompatible()],
    ['invalid', 422, syntheticRollbackInvalid()],
  ])('accepts the exact %s body', (_label, status, body) => {
    expect(parseRollbackFailure(status, structuredClone(body))).toEqual(body);
  });

  it.each([
    ['the publish stale code', 409, syntheticStalePublication()],
    ['a 409 code on a 422', 422, syntheticStaleRollback()],
    ['a 422 code on a 409', 409, syntheticRollbackInvalid()],
    ['the publish 422 envelope', 422, syntheticPublicationInvalid()],
    ['a stale extra key', 409, { ...syntheticStaleRollback(), source: releaseRef(2) }],
    ['a stale negative current lock', 409, { ...syntheticStaleRollback(), current_lock_version: -1 }],
    ['an incompatible without errors', 422, { ...syntheticRollbackIncompatible(), errors: [] }],
    ['an incompatible without a source', 422, withoutKey(syntheticRollbackIncompatible(), 'source')],
    ['an invalid without errors', 422, syntheticRollbackInvalid([])],
    ['a source-active extra key', 409, { code: 'rollback_source_active', active_release: releaseRef(4), source: releaseRef(4) }],
    ['a matches-active without a source', 409, { code: 'rollback_matches_active', active_release: releaseRef(4) }],
    ['an unknown code', 409, { code: 'rollback_refused', active_release: releaseRef(4) }],
    ['no body', 422, null],
  ])('rejects %s', (_label, status, body) => {
    expect(parseRollbackFailure(status, body)).toBeNull();
  });
});

describe('the history and rollback reads', () => {
  it.each([
    ['listGraphReleases', () => listGraphReleases(), /\/api\/admin\/agent-definitions\/releases$/, syntheticReleaseHistory()],
    ['getGraphRelease', () => getGraphRelease(2), /\/api\/admin\/agent-definitions\/releases\/2$/, syntheticReleaseDetail()],
    ['compareGraphRelease', () => compareGraphRelease(2), /\/releases\/2\/comparison$/, syntheticReleaseComparison()],
    ['getRollbackPreview', () => getRollbackPreview(2), /\/releases\/2\/rollback-preview$/, syntheticRollbackPreview()],
  ] as const)('%s GETs its route by version and returns the strictly parsed body', async (_label, read, url, body) => {
    const fetchMock = stubFetch(200, body);

    await expect(read()).resolves.toEqual(body);

    const [calledUrl, init] = onlyCall(fetchMock);
    expect(calledUrl).toMatch(url);
    expect(init.method).toBe('GET');
    expect(init.body).toBeUndefined();
  });

  it('refuses a malformed 200 and leaves a 404 a plain API error', async () => {
    stubFetch(200, { ...syntheticRollbackPreview(), extra: 1 });
    expect(await rejection(getRollbackPreview(2))).toBeInstanceOf(InvalidReleaseResponseError);

    stubFetch(404, { detail: 'Graph Version not found' });
    const error = await rejection(getGraphRelease(99));
    expect(error).toBeInstanceOf(AgentDefinitionApiError);
    expect(error).not.toBeInstanceOf(InvalidReleaseResponseError);
    expect((error as AgentDefinitionApiError).status).toBe(404);
  });

  it('addresses releases by a positive integer version, never anything else', async () => {
    const fetchMock = stubFetch(200, syntheticReleaseDetail());
    expect(await rejection(getGraphRelease(0))).toBeInstanceOf(RangeError);
    expect(await rejection(getGraphRelease(2.5))).toBeInstanceOf(RangeError);
    expect(fetchMock).not.toHaveBeenCalled();
  });
});

describe('rollbackGraphRelease', () => {
  it('POSTs exactly { lock_version, release_note } to the version and returns the parsed 200', async () => {
    const fetchMock = stubFetch(200, syntheticRollbackSuccess());
    const smuggled = { lock_version: 3, release_note: 'Roll back to Graph Version 2.', actor: 'x@example.com' };

    await expect(rollbackGraphRelease(2, smuggled)).resolves.toEqual(syntheticRollbackSuccess());

    const [url, init] = onlyCall(fetchMock);
    expect(url).toMatch(/\/api\/admin\/agent-definitions\/releases\/2\/rollback$/);
    expect(init.method).toBe('POST');
    expect(init.body).toBe('{"lock_version":3,"release_note":"Roll back to Graph Version 2."}');
  });

  it.each([
    ['stale', 409, syntheticStaleRollback()],
    ['incompatible', 422, syntheticRollbackIncompatible()],
    ['invalid', 422, syntheticRollbackInvalid()],
  ])('throws the %s refusal with its strictly parsed payload', async (_label, status, body) => {
    stubFetch(status, body);

    const error = await rejection(rollbackGraphRelease(2, { lock_version: 3, release_note: 'n' }));

    expect(error).toBeInstanceOf(AgentDefinitionApiError);
    expect((error as AgentDefinitionApiError).status).toBe(status);
    expect((error as AgentDefinitionApiError).payload).toEqual(body);
  });

  it.each([
    ['a malformed 200', 200, { ...syntheticRollbackSuccess(), extra: 1 }],
    ['a publish success body', 200, syntheticPublishSuccess()],
    ['a malformed 409', 409, { code: 'stale_rollback' }],
    ['a malformed 422', 422, { code: 'invalid_rollback', errors: [] }],
  ])('refuses %s as an invalid response', async (_label, status, body) => {
    stubFetch(status, body);
    expect(await rejection(rollbackGraphRelease(2, { lock_version: 3, release_note: 'n' }))).toBeInstanceOf(InvalidReleaseResponseError);
  });

  it('leaves a 403 and a 500 plain API errors', async () => {
    for (const status of [403, 500]) {
      stubFetch(status, { detail: 'x' });
      const error = await rejection(rollbackGraphRelease(2, { lock_version: 3, release_note: 'n' }));
      expect(error).toBeInstanceOf(AgentDefinitionApiError);
      expect(error).not.toBeInstanceOf(InvalidReleaseResponseError);
    }
  });
});
