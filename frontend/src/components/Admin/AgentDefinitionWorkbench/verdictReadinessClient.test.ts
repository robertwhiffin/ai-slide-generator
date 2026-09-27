import { afterEach, describe, expect, it, vi } from 'vitest';
import {
  syntheticAgentReadiness,
  syntheticDraftReadinessBody,
  syntheticTestCaseReadiness,
  syntheticTestRunEvidence,
  syntheticVerdictIneligible,
} from '../../../../tests/fixtures/mocks';
import {
  AgentDefinitionApiError,
  InvalidReadinessResponseError,
  InvalidTestRunResponseError,
  TestRunVerdictApiError,
  getDraftReadiness,
  parseDraftReadinessResponse,
  recordTestRunVerdict,
  type TestRunEvidence,
} from '../../../api/agentDefinitions';
import { testOperationFailure } from './draftEditorState';

// ============================================================
// #268: the verdict and readiness clients #269 consumes (C22)
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

function verdictEvidence(overrides: Partial<TestRunEvidence> = {}): TestRunEvidence {
  return syntheticTestRunEvidence({
    candidate_is_current: null,
    base_release_is_current: null,
    verdict: 'approved',
    verdict_reviewer: 'admin@test.com',
    verdict_at: '2026-09-26T10:05:00Z',
    verdict_notes: null,
    ...overrides,
  });
}

afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

describe('the verdict client', () => {
  it('posts exactly {verdict, notes} to the run and returns the evidence', async () => {
    const body = verdictEvidence({ verdict_notes: 'Looks right.' });
    const fetchMock = stubFetch(200, body);

    const evidence = await recordTestRunVerdict(501, { verdict: 'approved', notes: 'Looks right.' });

    const [url, init] = onlyCall(fetchMock);
    expect(url).toMatch(/\/api\/admin\/agent-definitions\/test-runs\/501\/verdict$/);
    expect(init.method).toBe('POST');
    expect(init.body).toBe('{"verdict":"approved","notes":"Looks right."}');
    expect(evidence).toEqual(body);
  });

  it('always sends notes, as null when there are none (the body is exact-key)', async () => {
    const fetchMock = stubFetch(200, verdictEvidence({ verdict: 'rejected' }));

    await recordTestRunVerdict(501, { verdict: 'rejected', notes: null });

    const [, init] = onlyCall(fetchMock);
    expect(init.body).toBe('{"verdict":"rejected","notes":null}');
    // A caller that forgets the field still sends it: `undefined` would drop the key.
    const looseFetch = stubFetch(200, verdictEvidence({ verdict: 'rejected' }));
    const loose = { verdict: 'rejected' } as unknown as Parameters<typeof recordTestRunVerdict>[1];
    await recordTestRunVerdict(501, loose);
    const [, looseInit] = onlyCall(looseFetch);
    expect(JSON.parse(String(looseInit.body))).toEqual({ verdict: 'rejected', notes: null });
  });

  it.each([
    ['a malformed body', { ...verdictEvidence(), extra: true }],
    ['evidence for another run', verdictEvidence({ run_id: 502 })],
    ['evidence carrying another verdict', verdictEvidence({ verdict: 'rejected' })],
    ['evidence with no verdict', syntheticTestRunEvidence()],
  ])('contains %s as an invalid response', async (_label, body) => {
    stubFetch(200, body);

    expect(await rejection(recordTestRunVerdict(501, { verdict: 'approved', notes: null })))
      .toBeInstanceOf(InvalidTestRunResponseError);
  });

  it('types the exact 404 as test_run_not_found', async () => {
    stubFetch(404, { detail: 'Test run not found' });

    const error = await rejection(recordTestRunVerdict(501, { verdict: 'approved', notes: null }));

    expect(error).toBeInstanceOf(TestRunVerdictApiError);
    expect((error as TestRunVerdictApiError).status).toBe(404);
    expect((error as TestRunVerdictApiError).failure).toEqual({ code: 'test_run_not_found' });
  });

  it('leaves any other 404 body a plain API error', async () => {
    stubFetch(404, { detail: 'Not Found' });

    const error = await rejection(recordTestRunVerdict(501, { verdict: 'approved', notes: null }));

    expect(error).toBeInstanceOf(AgentDefinitionApiError);
    expect(error).not.toBeInstanceOf(TestRunVerdictApiError);
  });

  it.each(['not_completed', 'checks_failed', 'linked_to_release'] as const)('types the exact %s 422 as ineligible_for_approval', async (reason) => {
    stubFetch(422, syntheticVerdictIneligible(reason));

    const error = await rejection(recordTestRunVerdict(501, { verdict: 'approved', notes: null }));

    expect(error).toBeInstanceOf(TestRunVerdictApiError);
    expect((error as TestRunVerdictApiError).failure).toEqual(syntheticVerdictIneligible(reason));
  });

  it('types the ordered invalid_verdict 422 with its exact issues', async () => {
    const errors = [
      { field: 'verdict', code: 'invalid_choice', message: 'Verdict must be approved or rejected.' },
      { field: 'notes', code: 'too_long', message: 'Notes must be at most 2000 characters.' },
    ];
    stubFetch(422, { code: 'invalid_verdict', errors });

    const error = await rejection(recordTestRunVerdict(501, { verdict: 'approved', notes: null }));

    expect(error).toBeInstanceOf(TestRunVerdictApiError);
    expect((error as TestRunVerdictApiError).failure).toEqual({ code: 'invalid_verdict', errors });
  });

  it.each([
    ['an unknown reason', { ...syntheticVerdictIneligible(), reason: 'withdrawn' }],
    ['an extra key', { ...syntheticVerdictIneligible(), retryable: false }],
    ['a missing message', { code: 'ineligible_for_approval', reason: 'checks_failed' }],
    ['an empty issue list', { code: 'invalid_verdict', errors: [] }],
    ['the draft envelope', { code: 'invalid_draft', errors: [{ field: 'verdict', code: 'x', message: 'y' }] }],
    ['no body', null],
  ])('contains a 422 with %s as an invalid response', async (_label, body) => {
    stubFetch(422, body);

    expect(await rejection(recordTestRunVerdict(501, { verdict: 'approved', notes: null })))
      .toBeInstanceOf(InvalidTestRunResponseError);
  });

  it('types a 403 detail as verdict_forbidden', async () => {
    stubFetch(403, { detail: 'Authenticated principal required' });

    const error = await rejection(recordTestRunVerdict(501, { verdict: 'approved', notes: null }));

    expect(error).toBeInstanceOf(TestRunVerdictApiError);
    expect((error as TestRunVerdictApiError).failure)
      .toEqual({ code: 'verdict_forbidden', detail: 'Authenticated principal required' });
  });

  it('leaves a 500 a plain API error', async () => {
    stubFetch(500, { detail: 'Internal Server Error' });

    const error = await rejection(recordTestRunVerdict(501, { verdict: 'approved', notes: null }));

    expect(error).toBeInstanceOf(AgentDefinitionApiError);
    expect((error as AgentDefinitionApiError).status).toBe(500);
  });
});

describe('the readiness client', () => {
  it('reads GET /readiness and returns the exact snake_case body', async () => {
    const body = syntheticDraftReadinessBody();
    const fetchMock = stubFetch(200, body);

    const readiness = await getDraftReadiness();

    const [url, init] = onlyCall(fetchMock);
    expect(url).toMatch(/\/api\/admin\/agent-definitions\/readiness$/);
    expect(init.method).toBe('GET');
    expect(readiness).toEqual(body);
  });

  it('accepts every status code on a blocking changed role', () => {
    const body = syntheticDraftReadinessBody({
      all_ready: false,
      blocking_agents: ['architect'],
      agents: {
        architect: syntheticAgentReadiness('architect', {
          candidate_hash: 'd'.repeat(64),
          is_changed_from_base: true,
          ready: false,
          cases: [
            syntheticTestCaseReadiness({ status: 'approved', run_id: 501, run_verdict: 'approved', run_checks_passed: true }),
            syntheticTestCaseReadiness({ test_case_id: 102, status: 'awaiting_review', blocking: true, run_id: 502, run_checks_passed: true }),
            syntheticTestCaseReadiness({ test_case_id: 103, status: 'test_failed', blocking: true, run_id: 503, run_verdict: 'rejected', run_checks_passed: true }),
            syntheticTestCaseReadiness({ test_case_id: 104, status: 'needs_test', blocking: true }),
          ],
        }),
      },
    });

    expect(parseDraftReadinessResponse(body)).toEqual(body);
  });

  it('accepts a changed role with no required case', () => {
    const body = syntheticDraftReadinessBody({
      all_ready: false,
      blocking_agents: ['builder'],
      agents: {
        builder: syntheticAgentReadiness('builder', {
          is_changed_from_base: true, ready: false, missing_required_case: true,
        }),
      },
    });

    expect(parseDraftReadinessResponse(body)).toEqual(body);
  });

  function withAgent(change: (agent: Record<string, unknown>) => void) {
    const body = syntheticDraftReadinessBody({
      agents: { architect: syntheticAgentReadiness('architect', { cases: [syntheticTestCaseReadiness()] }) },
    }) as unknown as { agents: Array<Record<string, unknown>> };
    change(body.agents[0]);
    return body;
  }

  function withCase(change: (item: Record<string, unknown>) => void) {
    return withAgent((agent) => change((agent.cases as Array<Record<string, unknown>>)[0]));
  }

  it.each([
    ['a missing top-level key', () => {
      const body: Partial<ReturnType<typeof syntheticDraftReadinessBody>> = syntheticDraftReadinessBody();
      delete body.draft_lock_version;
      return body;
    }],
    ['an extra top-level key', () => ({ ...syntheticDraftReadinessBody(), ready: true })],
    ['a camelCase alias', () => {
      const { all_ready: allReady, ...rest } = syntheticDraftReadinessBody();
      return { ...rest, allReady };
    }],
    ['a negative lock', () => syntheticDraftReadinessBody({ draft_lock_version: -1 })],
    ['a non-integer lock', () => syntheticDraftReadinessBody({ draft_lock_version: 1.5 })],
    ['a zero base release', () => syntheticDraftReadinessBody({ base_release_id: 0 })],
    ['a string all_ready', () => ({ ...syntheticDraftReadinessBody(), all_ready: 'true' })],
    ['an unknown blocking role', () => ({ ...syntheticDraftReadinessBody(), blocking_agents: ['foreman'] })],
    ['a missing agent key', () => withAgent((agent) => { delete agent.missing_required_case; })],
    ['an extra agent key', () => withAgent((agent) => { agent.blocking = true; })],
    ['an unknown agent', () => withAgent((agent) => { agent.agent_key = 'foreman'; })],
    ['an uppercase hash', () => withAgent((agent) => { agent.candidate_hash = 'A'.repeat(64); })],
    ['a duplicate role', () => {
      const body = syntheticDraftReadinessBody();
      return { ...body, agents: [...body.agents, body.agents[0]] };
    }],
    ['a missing case key', () => withCase((item) => { delete item.run_checks_passed; })],
    ['an extra case key', () => withCase((item) => { item.label = 'Needs test'; })],
    ['a display label for status', () => withCase((item) => { item.status = 'Needs test'; })],
    ['an unknown status', () => withCase((item) => { item.status = 'withdrawn'; })],
    ['an unknown run verdict', () => withCase((item) => { item.run_verdict = 'withdrawn'; })],
    ['a zero case id', () => withCase((item) => { item.test_case_id = 0; })],
    ['a zero case version', () => withCase((item) => { item.test_case_version = 0; })],
    ['a zero run id', () => withCase((item) => { item.run_id = 0; })],
    ['a string checks flag', () => withCase((item) => { item.run_checks_passed = 'true'; })],
    ['a case of another role', () => withCase((item) => { item.agent_key = 'builder'; })],
    ['an array body', () => [syntheticDraftReadinessBody()]],
    ['null', () => null],
  ])('rejects a body with %s', (_label, build) => {
    expect(parseDraftReadinessResponse(build())).toBeNull();
  });

  it('contains a malformed 200 as a readiness-specific invalid response, not a test-run one', async () => {
    stubFetch(200, { ...syntheticDraftReadinessBody(), extra: 1 });

    const error = await rejection(getDraftReadiness());
    expect(error).toBeInstanceOf(InvalidReadinessResponseError);
    expect(error).not.toBeInstanceOf(InvalidTestRunResponseError);
    expect((error as Error).message).toBe('Draft readiness response did not match the expected contract.');
  });

  it('leaves a 500 a plain API error', async () => {
    stubFetch(500, { detail: 'Graph configuration is incomplete' });

    const error = await rejection(getDraftReadiness());

    expect(error).toBeInstanceOf(AgentDefinitionApiError);
    expect((error as AgentDefinitionApiError).status).toBe(500);
  });
});

describe('the verdict refusal copy (#269 C48)', () => {
  it.each([
    ['not_completed', 'Only completed runs can be reviewed.'],
    ['checks_failed', 'Deterministic checks did not pass, so this run cannot be approved.'],
    ['linked_to_release', 'This run is evidence for a published Graph Version; its verdict cannot change.'],
  ] as const)('labels %s with its own client message', (reason, message) => {
    const error = new TestRunVerdictApiError(422, syntheticVerdictIneligible(reason));
    expect(testOperationFailure(error, 'verdict')).toEqual({ message, issues: [] });
  });
});
