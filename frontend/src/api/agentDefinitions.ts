const API_BASE_URL = import.meta.env.VITE_API_URL || (
  import.meta.env.MODE === 'production' ? '' : 'http://127.0.0.1:8000'
);

const WORKBENCH_URL = `${API_BASE_URL}/api/admin/agent-definitions/workbench`;

export const AGENT_KEYS = [
  'architect',
  'data_analyst',
  'builder',
  'build_reviewer',
  'fixer',
  'fix_reviewer',
  'deck_reviewer',
] as const;

export type AgentKey = typeof AGENT_KEYS[number];

export type AssemblyCondition =
  | 'always'
  | 'design_system_active'
  | 'design_system_inactive'
  | 'payload_has_deck_brief';

export interface WorkbenchModel {
  endpoint_name: string;
  temperature: number;
  max_tokens: number;
  top_p: number;
}

export interface SchemaOverlay {
  field_overrides: Record<string, unknown>;
  additional_optional_fields: string[];
}

export type AssemblyBlock =
  | { kind: 'authored_prompt'; condition: 'always' }
  | {
      kind: 'protected';
      name: 'build_reviewer_deck_brief' | 'slide_frame_constraints' | 'design_system_precedence';
      condition: AssemblyCondition;
    }
  | { kind: 'payload_json'; condition: 'always'; indent: 2; default: 'str' }
  | {
      kind: 'structured_output_binding';
      condition: 'always';
      binding: 'langchain.with_structured_output';
      terminal: true;
    };

export interface AssemblyRules {
  format_version: 1;
  separator: '\n\n';
  blocks: AssemblyBlock[];
}

export interface ContentIdentity {
  version: number;
  digest: string;
}

interface DefinitionContent {
  definition_version: number;
  prompt_text: string;
  model: WorkbenchModel;
  schema_overlay: SchemaOverlay;
  assembly_rules: AssemblyRules;
  protected_assembly: ContentIdentity;
  schema_contract: ContentIdentity;
}

export interface PublishedDefinition extends DefinitionContent {
  revision_id: number;
  content_hash: string;
}

export interface DraftDefinition extends DefinitionContent {
  base_revision_id: number;
  candidate_hash: string;
}

export interface ModelAgentNode {
  agent_key: AgentKey;
  display_name: string;
  execution_kind: 'model';
  editable: true;
  changed: boolean;
  published: PublishedDefinition;
  draft: DraftDefinition;
  read_only_reason: null;
}

export interface DeterministicAgentNode {
  agent_key: 'foreman';
  display_name: 'Foreman';
  execution_kind: 'deterministic';
  editable: false;
  changed: false;
  published: null;
  draft: null;
  read_only_reason: string;
}

export type AgentNode = ModelAgentNode | DeterministicAgentNode;

export interface ActiveRelease {
  release_id: number;
  version_number: number;
  previous_release_id: number | null;
  restored_from_release_id: number | null;
  release_note: string;
  published_by: string;
  published_at: string;
  effective_from: string;
  effective_to: string | null;
}

export interface DraftMetadata {
  draft_id: number;
  base_release_id: number;
  base_version_number: number;
  lock_version: number;
  updated_by: string;
  updated_at: string;
}

export interface AgentDefinitionWorkbenchResponse {
  active_release: ActiveRelease;
  draft: DraftMetadata;
  nodes: AgentNode[];
}

export interface EditableModelDraft {
  prompt_text: string;
  model: WorkbenchModel;
}

export interface DraftSaveRequest {
  lock_version: number;
  candidate: EditableModelDraft;
}

export interface DraftSaveSuccessResponse {
  draft: DraftMetadata;
  definition: DraftDefinition;
  changed: boolean;
}

export interface DraftFieldError {
  field: string;
  code: string;
  message: string;
}

export interface DraftValidationErrorResponse {
  code: 'invalid_draft';
  errors: DraftFieldError[];
}

export interface DraftSaveConflictResponse {
  code: 'stale_draft';
  expected_lock_version: number;
  current_lock_version: number;
  client_candidate: EditableModelDraft;
  server: {
    draft: DraftMetadata;
    definitions: Record<AgentKey, DraftDefinition>;
  };
}

export class InvalidDraftSaveResponseError extends Error {
  constructor() {
    super('Draft save response did not match the expected contract.');
    this.name = 'InvalidDraftSaveResponseError';
  }
}

export class AgentDefinitionApiError extends Error {
  readonly status: number;
  readonly detail: string;
  readonly payload: unknown;

  constructor(status: number, payload: unknown, statusText = '', draftSave = false) {
    const detail = (
      typeof payload === 'object'
      && payload !== null
      && 'detail' in payload
      && typeof payload.detail === 'string'
    ) ? payload.detail : draftSave
      ? `Unable to save draft (${status}${statusText ? ` ${statusText}` : ''}).`
      : typeof payload === 'string'
        ? payload
        : (statusText || 'Request failed');
    super(detail);
    this.name = 'AgentDefinitionApiError';
    this.status = status;
    this.detail = detail;
    this.payload = payload;
  }
}

function isPlainRecord(value: unknown): value is Record<string, unknown> {
  if (typeof value !== 'object' || value === null || Array.isArray(value)) return false;
  const prototype = Object.getPrototypeOf(value);
  return prototype === Object.prototype || prototype === null;
}

function hasExactKeys(value: Record<string, unknown>, keys: readonly string[]): boolean {
  const actual = Object.keys(value);
  return actual.length === keys.length && keys.every((key) => key in value);
}

function isFiniteNumber(value: unknown): value is number {
  return typeof value === 'number' && Number.isFinite(value);
}

function isInteger(value: unknown): value is number {
  return isFiniteNumber(value) && Number.isInteger(value);
}

function isPositiveInteger(value: unknown): value is number {
  return isInteger(value) && value > 0;
}

function isNonnegativeInteger(value: unknown): value is number {
  return isInteger(value) && value >= 0;
}

function isWorkbenchModel(value: unknown): value is WorkbenchModel {
  return isPlainRecord(value)
    && hasExactKeys(value, ['endpoint_name', 'temperature', 'max_tokens', 'top_p'])
    && typeof value.endpoint_name === 'string'
    && isFiniteNumber(value.temperature) && value.temperature >= 0 && value.temperature <= 1
    && isPositiveInteger(value.max_tokens)
    && isFiniteNumber(value.top_p) && value.top_p >= 0 && value.top_p <= 1;
}

function isEditableModelDraft(value: unknown): value is EditableModelDraft {
  return isPlainRecord(value)
    && hasExactKeys(value, ['prompt_text', 'model'])
    && typeof value.prompt_text === 'string'
    && isWorkbenchModel(value.model);
}

function isDraftMetadata(value: unknown): value is DraftMetadata {
  return isPlainRecord(value)
    && hasExactKeys(value, [
      'draft_id', 'base_release_id', 'base_version_number', 'lock_version', 'updated_by', 'updated_at',
    ])
    && isPositiveInteger(value.draft_id)
    && isPositiveInteger(value.base_release_id)
    && isPositiveInteger(value.base_version_number)
    && isNonnegativeInteger(value.lock_version)
    && typeof value.updated_by === 'string'
    && typeof value.updated_at === 'string';
}

function isSchemaOverlay(value: unknown): value is SchemaOverlay {
  return isPlainRecord(value)
    && hasExactKeys(value, ['field_overrides', 'additional_optional_fields'])
    && isPlainRecord(value.field_overrides)
    && Array.isArray(value.additional_optional_fields)
    && value.additional_optional_fields.every((field) => typeof field === 'string');
}

function isAssemblyBlock(value: unknown): value is AssemblyBlock {
  if (!isPlainRecord(value) || typeof value.kind !== 'string') return false;
  if (value.kind === 'authored_prompt') {
    return hasExactKeys(value, ['kind', 'condition']) && value.condition === 'always';
  }
  if (value.kind === 'protected') {
    return hasExactKeys(value, ['kind', 'name', 'condition'])
      && ['build_reviewer_deck_brief', 'slide_frame_constraints', 'design_system_precedence'].includes(String(value.name))
      && ['always', 'design_system_active', 'design_system_inactive', 'payload_has_deck_brief'].includes(String(value.condition));
  }
  if (value.kind === 'payload_json') {
    return hasExactKeys(value, ['kind', 'condition', 'indent', 'default'])
      && value.condition === 'always' && value.indent === 2 && value.default === 'str';
  }
  if (value.kind === 'structured_output_binding') {
    return hasExactKeys(value, ['kind', 'condition', 'binding', 'terminal'])
      && value.condition === 'always'
      && value.binding === 'langchain.with_structured_output'
      && value.terminal === true;
  }
  return false;
}

function isAssemblyRules(value: unknown): value is AssemblyRules {
  return isPlainRecord(value)
    && hasExactKeys(value, ['format_version', 'separator', 'blocks'])
    && value.format_version === 1
    && value.separator === '\n\n'
    && Array.isArray(value.blocks)
    && value.blocks.every(isAssemblyBlock);
}

function isContentIdentity(value: unknown): value is ContentIdentity {
  return isPlainRecord(value)
    && hasExactKeys(value, ['version', 'digest'])
    && isPositiveInteger(value.version)
    && typeof value.digest === 'string'
    && /^[0-9a-f]{64}$/.test(value.digest);
}

function isDraftDefinition(value: unknown): value is DraftDefinition {
  return isPlainRecord(value)
    && hasExactKeys(value, [
      'base_revision_id', 'candidate_hash', 'definition_version', 'prompt_text', 'model',
      'schema_overlay', 'assembly_rules', 'protected_assembly', 'schema_contract',
    ])
    && isPositiveInteger(value.base_revision_id)
    && typeof value.candidate_hash === 'string' && /^[0-9a-f]{64}$/.test(value.candidate_hash)
    && isPositiveInteger(value.definition_version)
    && typeof value.prompt_text === 'string'
    && isWorkbenchModel(value.model)
    && isSchemaOverlay(value.schema_overlay)
    && isAssemblyRules(value.assembly_rules)
    && isContentIdentity(value.protected_assembly)
    && isContentIdentity(value.schema_contract);
}

export function parseDraftSaveSuccessResponse(value: unknown): DraftSaveSuccessResponse | null {
  if (!isPlainRecord(value) || !hasExactKeys(value, ['draft', 'definition', 'changed'])) return null;
  if (!isDraftMetadata(value.draft) || !isDraftDefinition(value.definition) || typeof value.changed !== 'boolean') return null;
  return value as unknown as DraftSaveSuccessResponse;
}

export function parseDraftSaveConflictResponse(value: unknown): DraftSaveConflictResponse | null {
  if (!isPlainRecord(value) || !hasExactKeys(value, [
    'code', 'expected_lock_version', 'current_lock_version', 'client_candidate', 'server',
  ])) return null;
  if (value.code !== 'stale_draft'
    || !isNonnegativeInteger(value.expected_lock_version)
    || !isNonnegativeInteger(value.current_lock_version)
    || !isEditableModelDraft(value.client_candidate)
    || !isPlainRecord(value.server)
    || !hasExactKeys(value.server, ['draft', 'definitions'])
    || !isDraftMetadata(value.server.draft)
    || !isPlainRecord(value.server.definitions)) return null;
  const definitions = value.server.definitions;
  if (!hasExactKeys(definitions, AGENT_KEYS)) return null;
  if (!AGENT_KEYS.every((key) => isDraftDefinition(definitions[key]))) return null;
  if (value.current_lock_version !== value.server.draft.lock_version) return null;
  return value as unknown as DraftSaveConflictResponse;
}

function isDraftFieldError(value: unknown): value is DraftFieldError {
  return isPlainRecord(value)
    && hasExactKeys(value, ['field', 'code', 'message'])
    && typeof value.field === 'string'
    && typeof value.code === 'string'
    && typeof value.message === 'string';
}

export function parseDraftValidationErrorResponse(value: unknown): DraftValidationErrorResponse | null {
  if (!isPlainRecord(value)
    || !hasExactKeys(value, ['code', 'errors'])
    || value.code !== 'invalid_draft'
    || !Array.isArray(value.errors)
    || value.errors.length === 0
    || !value.errors.every(isDraftFieldError)) return null;
  return value as unknown as DraftValidationErrorResponse;
}

let workbenchRequest: Promise<AgentDefinitionWorkbenchResponse> | null = null;

/**
 * Fetches the read-only aggregate. The in-flight request is shared so
 * React StrictMode's development remount does not double-read sensitive prompts.
 * The settled request is cleared, allowing a later explicit tab revisit to refresh.
 */
export function getAgentDefinitionWorkbench(): Promise<AgentDefinitionWorkbenchResponse> {
  if (workbenchRequest) return workbenchRequest;

  workbenchRequest = fetch(WORKBENCH_URL, {
    method: 'GET',
    headers: { Accept: 'application/json' },
  }).then(async (response) => {
    if (!response.ok) {
      const payload: unknown = await response.json().catch(() => null);
      throw new AgentDefinitionApiError(response.status, payload, response.statusText);
    }
    return response.json() as Promise<AgentDefinitionWorkbenchResponse>;
  }).finally(() => {
    workbenchRequest = null;
  });

  return workbenchRequest;
}

export async function saveDraftDefinition(
  agentKey: AgentKey,
  request: DraftSaveRequest,
): Promise<DraftSaveSuccessResponse> {
  const response = await fetch(
    `${API_BASE_URL}/api/admin/agent-definitions/draft/${agentKey}`,
    {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(request),
    },
  );
  const payload: unknown = await response.json().catch(() => null);

  if (response.status === 200) {
    const parsed = parseDraftSaveSuccessResponse(payload);
    if (parsed === null) throw new InvalidDraftSaveResponseError();
    return parsed;
  }
  if (response.status === 409) {
    const parsed = parseDraftSaveConflictResponse(payload);
    if (parsed === null) throw new InvalidDraftSaveResponseError();
    throw new AgentDefinitionApiError(response.status, parsed, response.statusText, true);
  }
  if (response.status === 422) {
    const parsed = parseDraftValidationErrorResponse(payload);
    if (parsed === null) throw new InvalidDraftSaveResponseError();
    throw new AgentDefinitionApiError(response.status, parsed, response.statusText, true);
  }
  throw new AgentDefinitionApiError(response.status, payload, response.statusText, true);
}
