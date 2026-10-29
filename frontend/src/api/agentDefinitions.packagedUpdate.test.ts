import { afterEach, describe, expect, it, vi } from 'vitest';
import { syntheticRollbackSuccess } from '../../tests/fixtures/mocks';
import {
  AgentDefinitionApiError,
  InvalidReleaseResponseError,
  adoptPackagedUpdate,
  getPackagedUpdate,
} from './agentDefinitions';

const KEYS = ['architect', 'data_analyst', 'builder', 'build_reviewer', 'fixer', 'fix_reviewer', 'deck_reviewer'];

function validStatus(): Record<string, unknown> {
  return {
    available: true,
    differing_agents: ['architect'],
    blocked_reason: 'hand_edited',
    hand_edited_agents: ['architect'],
    validation_issues: [],
    diffs: [{
      agent_key: 'architect',
      field_diffs: [{ field: 'model.temperature', published: 0.1, candidate: 0.2 }],
    }],
    active_version_number: 3,
    lock_version: 7,
  };
}

function validAdopt(): Record<string, unknown> {
  return {
    release: syntheticRollbackSuccess().release,
    changed_agent_keys: ['architect'],
    draft_effect: Object.fromEntries(KEYS.map((key) => [key, 'kept'])),
  };
}

function stub(status: number, body: unknown) {
  const mock = vi.fn().mockResolvedValue({
    ok: status >= 200 && status < 300,
    status,
    statusText: '',
    json: vi.fn().mockResolvedValue(body),
  });
  vi.stubGlobal('fetch', mock);
  return mock;
}

afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

describe('getPackagedUpdate', () => {
  it('GETs the graph-shipping path and returns a valid body', async () => {
    const mock = stub(200, validStatus());

    await expect(getPackagedUpdate()).resolves.toEqual(validStatus());
    const [url, init] = mock.mock.calls[0] as [string, RequestInit];
    expect(url).toMatch(/\/api\/admin\/graph-shipping\/packaged-update$/);
    expect(init.method).toBe('GET');
  });

  it('accepts a null blocked_reason', async () => {
    stub(200, { ...validStatus(), blocked_reason: null, hand_edited_agents: [] });
    await expect(getPackagedUpdate()).resolves.toMatchObject({ blocked_reason: null });
  });

  it.each([
    ['a missing lock_version', (() => { const b = validStatus(); delete b.lock_version; return b; })()],
    ['an unknown blocked_reason', { ...validStatus(), blocked_reason: 'surprise' }],
    ['an extra key', { ...validStatus(), extra: 1 }],
    ['an unknown agent key', { ...validStatus(), differing_agents: ['nobody'] }],
  ])('rejects %s with InvalidReleaseResponseError', async (_label, body) => {
    stub(200, body);
    await expect(getPackagedUpdate()).rejects.toBeInstanceOf(InvalidReleaseResponseError);
  });

  it('raises AgentDefinitionApiError for a non-200 status', async () => {
    stub(500, null);
    await expect(getPackagedUpdate()).rejects.toMatchObject({
      name: 'AgentDefinitionApiError', status: 500,
    });
  });
});

describe('adoptPackagedUpdate', () => {
  it('POSTs exactly {lock_version} to the adopt path and returns a valid body', async () => {
    const mock = stub(200, validAdopt());

    await expect(adoptPackagedUpdate(7)).resolves.toEqual(validAdopt());
    const [url, init] = mock.mock.calls[0] as [string, RequestInit];
    expect(url).toMatch(/\/api\/admin\/graph-shipping\/packaged-update\/adopt$/);
    expect(init.method).toBe('POST');
    expect(JSON.parse(String(init.body))).toEqual({ lock_version: 7 });
  });

  it('rejects a 200 missing a field with InvalidReleaseResponseError', async () => {
    const body = validAdopt();
    delete body.changed_agent_keys;
    stub(200, body);
    await expect(adoptPackagedUpdate(7)).rejects.toBeInstanceOf(InvalidReleaseResponseError);
  });

  it('rejects a draft_effect that is not the seven roles', async () => {
    stub(200, { ...validAdopt(), draft_effect: { architect: 'kept' } });
    await expect(adoptPackagedUpdate(7)).rejects.toBeInstanceOf(InvalidReleaseResponseError);
  });

  it.each([
    [409, { code: 'nothing_to_adopt' }],
    [422, { code: 'packaged_invalid', errors: [{ field: 'architect.prompt_text', code: 'x', message: 'bad' }] }],
    [422, { code: 'invalid_adopt_request', errors: [{ field: 'lock_version', code: 'x', message: 'bad' }] }],
  ])('throws AgentDefinitionApiError carrying the typed %s body', async (statusCode, body) => {
    stub(statusCode, body);
    const error = await adoptPackagedUpdate(7).catch((e: unknown) => e);
    expect(error).toBeInstanceOf(AgentDefinitionApiError);
    expect(error).toMatchObject({ status: statusCode, payload: body });
  });

  it('throws AgentDefinitionApiError with the stale body on 409 stale_publication', async () => {
    const body = {
      code: 'stale_publication',
      expected_lock_version: 7,
      current_lock_version: 8,
      active_release: { release_id: 45, version_number: 5 },
      draft: {
        draft_id: 1, base_release_id: 45, base_version_number: 5, lock_version: 8,
        updated_by: 'a', updated_at: '2026-09-25T12:00:00Z',
      },
    };
    stub(409, body);
    const error = await adoptPackagedUpdate(7).catch((e: unknown) => e);
    expect(error).toBeInstanceOf(AgentDefinitionApiError);
    expect(error).toMatchObject({ status: 409, payload: body });
  });

  it('rejects a malformed 409 with InvalidReleaseResponseError', async () => {
    stub(409, { code: 'stale_publication' });
    await expect(adoptPackagedUpdate(7)).rejects.toBeInstanceOf(InvalidReleaseResponseError);
  });
});
