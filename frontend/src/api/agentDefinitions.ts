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

export const ASSEMBLY_CONDITIONS = [
  'always',
  'design_system_active',
  'design_system_inactive',
  'payload_has_deck_brief',
] as const;

export type AssemblyCondition = typeof ASSEMBLY_CONDITIONS[number];

export const CUSTOM_ANCHORS = [
  'after_authored_prompt',
  'after_deck_brief',
  'after_environment_constraints',
] as const;

export type CustomAnchor = typeof CUSTOM_ANCHORS[number];

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

/**
 * Code-owned descriptor for one selectable optional output field.
 * Every property except `name` is read-only on the client; the client sends
 * only the field name (in `additional_optional_fields`) and optionally
 * overrides `description`/`examples` via `field_overrides`.
 */
export interface FieldDescriptorItemSchema {
  type: string;
  strip_whitespace: boolean;
  min_length: number;
  max_length: number;
}

export interface FieldDescriptorSchema {
  type: string[];
  default: null;
  max_items: number;
  items: FieldDescriptorItemSchema;
}

export interface FieldDescriptor {
  name: string;
  description: string;
  examples: unknown[];
  schema: FieldDescriptorSchema;
}

/** Any JSON value, as the server serializes it. */
export type JsonValue =
  | null
  | boolean
  | number
  | string
  | JsonValue[]
  | { [key: string]: JsonValue };

/**
 * Code-owned, read-only display data for one canonical output field of the role's
 * Pydantic output schema. Never a request field: the client shows it as protected
 * labels and may only attach description/examples guidance under `field_overrides`.
 * `default` is present exactly when `required` is false.
 */
export interface CanonicalFieldDescriptor {
  name: string;
  type: string;
  required: boolean;
  enum: string[] | null;
  default?: JsonValue;
}

/**
 * The editable schema overlay included in a save candidate.
 * `field_overrides` keys are canonical or selectable optional field names.
 * Only `description` and `examples` within each value reach the domain
 * validator; any other property is rejected with `overlay_guidance_property_forbidden`.
 */
export interface EditableSchemaOverlay {
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

export interface AssemblyRulesV1 {
  format_version: 1;
  separator: '\n\n';
  blocks: AssemblyBlock[];
}

export interface CustomTextBlock {
  kind: 'custom_text';
  block_id: string;
  anchor: CustomAnchor;
  condition: AssemblyCondition;
  text: string;
}

export interface AssemblyRulesV2 {
  format_version: 2;
  custom_blocks: CustomTextBlock[];
}

/** The frozen server-owned discriminated union; the client never repairs either arm. */
export type AssemblyRules = AssemblyRulesV1 | AssemblyRulesV2;

/** One locked, server-derived protected stage row. It is never a request field. */
export interface ProtectedStageView {
  stage_id: string;
  label: string;
  condition: AssemblyCondition;
  locked: true;
  display_text: string;
  bundle_version: number;
  bundle_digest: string;
  legal_adjacent_custom_anchors: CustomAnchor[];
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
  protected_stage_view: ProtectedStageView[];
  /**
   * Read-only server-computed list of selectable optional output fields for
   * this schema contract version. Empty for v1; one entry (diagnostic_notes)
   * for v2. Never a request field — the client displays and selects from it
   * but the server always derives it from the registry.
   */
  selectable_optional_fields: FieldDescriptor[];
  /**
   * Read-only server-derived display data for every canonical output field, in model
   * field order. Never a request field and never stored.
   */
  canonical_fields: CanonicalFieldDescriptor[];
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
  /**
   * Present only for a v2 candidate. A v1 candidate omits the key entirely, which
   * keeps #263's model/prompt save body byte-identical. The server echoes the key
   * as `null` on a 409, so both exact shapes are accepted on the way back in.
   */
  assembly_rules?: AssemblyRulesV2 | null;
  /**
   * Present only when the client has explicit overlay edits (non-empty
   * additional_optional_fields or non-empty field_overrides). Omitting the key
   * preserves the stored overlay on the server unchanged, keeping the five-field
   * save body byte-identical when no overlay edits have been made.
   */
  schema_overlay?: EditableSchemaOverlay | null;
}

export interface DraftSaveRequest {
  lock_version: number;
  candidate: EditableModelDraft;
}

/** The only accepted body for the upgrade and legacy-source POST routes. */
export interface DraftLockRequest {
  lock_version: number;
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
  /**
   * An ordinary save echoes its submitted candidate. The protected-assembly upgrade
   * and legacy-source routes carry no candidate at all, so this is exactly `null`
   * and the client must never hydrate a candidate from it.
   */
  client_candidate: EditableModelDraft | null;
  server: {
    draft: DraftMetadata;
    definitions: Record<AgentKey, DraftDefinition>;
  };
}

export interface LegacyPromptSourceRecord {
  prompt_text: string;
  revision_id: number;
  content_hash: string;
}

export interface LegacyPromptSourceResponse {
  draft: DraftMetadata;
  agent_key: AgentKey;
  lock_version: number;
  source: LegacyPromptSourceRecord;
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

/**
 * Accepts all four valid candidate shapes:
 *   - {prompt_text, model}                               — v1, no overlay
 *   - {prompt_text, model, assembly_rules}               — v2 assembly, no overlay
 *   - {prompt_text, model, schema_overlay}               — v1 assembly, with overlay
 *   - {prompt_text, model, assembly_rules, schema_overlay} — v2 assembly + overlay
 * Extra or missing keys are still rejected. The server echoes back exactly what the
 * client sent in a 409 client_candidate, so all sent shapes must be parseable.
 */
function isEditableModelDraft(value: unknown): value is EditableModelDraft {
  if (!isPlainRecord(value)) return false;
  if (typeof value.prompt_text !== 'string' || !isWorkbenchModel(value.model)) return false;
  const hasAssembly = 'assembly_rules' in value;
  const hasOverlay = 'schema_overlay' in value;
  const expectedKeys: readonly string[] = hasAssembly && hasOverlay
    ? ['prompt_text', 'model', 'assembly_rules', 'schema_overlay']
    : hasAssembly
      ? ['prompt_text', 'model', 'assembly_rules']
      : hasOverlay
        ? ['prompt_text', 'model', 'schema_overlay']
        : ['prompt_text', 'model'];
  if (!hasExactKeys(value, expectedKeys)) return false;
  if (hasAssembly && value.assembly_rules !== null && !isAssemblyRulesV2(value.assembly_rules)) return false;
  if (hasOverlay && value.schema_overlay !== null && !isEditableSchemaOverlay(value.schema_overlay)) return false;
  return true;
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

function isEditableSchemaOverlay(value: unknown): value is EditableSchemaOverlay {
  return isPlainRecord(value)
    && hasExactKeys(value, ['field_overrides', 'additional_optional_fields'])
    && isPlainRecord(value.field_overrides)
    && Array.isArray(value.additional_optional_fields)
    && value.additional_optional_fields.every((f) => typeof f === 'string');
}

function isFieldDescriptorItemSchema(value: unknown): value is FieldDescriptorItemSchema {
  return isPlainRecord(value)
    && hasExactKeys(value, ['type', 'strip_whitespace', 'min_length', 'max_length'])
    && typeof value.type === 'string'
    && typeof value.strip_whitespace === 'boolean'
    && isNonnegativeInteger(value.min_length)
    && isNonnegativeInteger(value.max_length);
}

function isFieldDescriptorSchema(value: unknown): value is FieldDescriptorSchema {
  return isPlainRecord(value)
    && hasExactKeys(value, ['type', 'default', 'max_items', 'items'])
    && Array.isArray(value.type)
    && value.type.every((t) => typeof t === 'string')
    && value.default === null
    && isPositiveInteger(value.max_items)
    && isFieldDescriptorItemSchema(value.items);
}

function isFieldDescriptor(value: unknown): value is FieldDescriptor {
  return isPlainRecord(value)
    && hasExactKeys(value, ['name', 'description', 'examples', 'schema'])
    && typeof value.name === 'string'
    && typeof value.description === 'string'
    && Array.isArray(value.examples)
    && isFieldDescriptorSchema(value.schema);
}

function isJsonValue(value: unknown): value is JsonValue {
  if (value === null || typeof value === 'boolean' || typeof value === 'string') return true;
  if (typeof value === 'number') return Number.isFinite(value);
  if (Array.isArray(value)) return value.every(isJsonValue);
  return isPlainRecord(value) && Object.values(value).every(isJsonValue);
}

function isCanonicalFieldDescriptor(value: unknown): value is CanonicalFieldDescriptor {
  if (!isPlainRecord(value) || typeof value.required !== 'boolean') return false;
  const keys = value.required
    ? ['name', 'type', 'required', 'enum']
    : ['name', 'type', 'required', 'enum', 'default'];
  return hasExactKeys(value, keys)
    && typeof value.name === 'string' && value.name.length > 0
    && typeof value.type === 'string' && value.type.length > 0
    && (value.enum === null || (
      Array.isArray(value.enum)
      && value.enum.length > 0
      && value.enum.every((item) => typeof item === 'string')
    ))
    && (value.required || isJsonValue(value.default));
}

function isCanonicalFieldList(value: unknown): value is CanonicalFieldDescriptor[] {
  if (!Array.isArray(value) || !value.every(isCanonicalFieldDescriptor)) return false;
  return new Set(value.map((field) => field.name)).size === value.length;
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

const UUID_PATTERN = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/;

function isAssemblyCondition(value: unknown): value is AssemblyCondition {
  return typeof value === 'string'
    && (ASSEMBLY_CONDITIONS as readonly string[]).includes(value);
}

function isCustomAnchor(value: unknown): value is CustomAnchor {
  return typeof value === 'string' && (CUSTOM_ANCHORS as readonly string[]).includes(value);
}

function isCustomTextBlock(value: unknown): value is CustomTextBlock {
  return isPlainRecord(value)
    && hasExactKeys(value, ['kind', 'block_id', 'anchor', 'condition', 'text'])
    && value.kind === 'custom_text'
    && typeof value.block_id === 'string'
    && UUID_PATTERN.test(value.block_id)
    && isCustomAnchor(value.anchor)
    && isAssemblyCondition(value.condition)
    && typeof value.text === 'string';
}

function isAssemblyRulesV1(value: Record<string, unknown>): value is Record<string, unknown> & AssemblyRulesV1 {
  return hasExactKeys(value, ['format_version', 'separator', 'blocks'])
    && value.separator === '\n\n'
    && Array.isArray(value.blocks)
    && value.blocks.every(isAssemblyBlock);
}

function isAssemblyRulesV2(value: unknown): value is AssemblyRulesV2 {
  return isPlainRecord(value)
    && hasExactKeys(value, ['format_version', 'custom_blocks'])
    && value.format_version === 2
    && Array.isArray(value.custom_blocks)
    && value.custom_blocks.every(isCustomTextBlock);
}

/**
 * Discriminates the frozen server union on `format_version` and applies the exact
 * key set of the selected arm. Neither arm's keys are accepted on the other.
 */
function isAssemblyRules(value: unknown): value is AssemblyRules {
  if (!isPlainRecord(value)) return false;
  if (value.format_version === 1) return isAssemblyRulesV1(value);
  if (value.format_version === 2) return isAssemblyRulesV2(value);
  return false;
}

function isProtectedStageView(value: unknown): value is ProtectedStageView {
  return isPlainRecord(value)
    && hasExactKeys(value, [
      'stage_id', 'label', 'condition', 'locked', 'display_text',
      'bundle_version', 'bundle_digest', 'legal_adjacent_custom_anchors',
    ])
    && typeof value.stage_id === 'string'
    && typeof value.label === 'string'
    && isAssemblyCondition(value.condition)
    && value.locked === true
    && typeof value.display_text === 'string'
    && isPositiveInteger(value.bundle_version)
    && typeof value.bundle_digest === 'string'
    && /^[0-9a-f]{64}$/.test(value.bundle_digest)
    && Array.isArray(value.legal_adjacent_custom_anchors)
    && value.legal_adjacent_custom_anchors.every(isCustomAnchor);
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
      'protected_stage_view', 'selectable_optional_fields', 'canonical_fields',
    ])
    && isPositiveInteger(value.base_revision_id)
    && typeof value.candidate_hash === 'string' && /^[0-9a-f]{64}$/.test(value.candidate_hash)
    && isPositiveInteger(value.definition_version)
    && typeof value.prompt_text === 'string'
    && isWorkbenchModel(value.model)
    && isSchemaOverlay(value.schema_overlay)
    && isAssemblyRules(value.assembly_rules)
    && isContentIdentity(value.protected_assembly)
    && isContentIdentity(value.schema_contract)
    && Array.isArray(value.protected_stage_view)
    && value.protected_stage_view.every(isProtectedStageView)
    && Array.isArray(value.selectable_optional_fields)
    && value.selectable_optional_fields.every(isFieldDescriptor)
    && isCanonicalFieldList(value.canonical_fields);
}

export function parseDraftSaveSuccessResponse(value: unknown): DraftSaveSuccessResponse | null {
  if (!isPlainRecord(value) || !hasExactKeys(value, ['draft', 'definition', 'changed'])) return null;
  if (!isDraftMetadata(value.draft) || !isDraftDefinition(value.definition) || typeof value.changed !== 'boolean') return null;
  return value as unknown as DraftSaveSuccessResponse;
}

/**
 * `clientCandidate: 'editable'` is the ordinary save contract and requires a
 * non-null candidate. `clientCandidate: 'null'` is the upgrade and legacy-source
 * contract and requires the field to be exactly `null`, so no code path can ever
 * hydrate an editable candidate from an operation that never submitted one.
 */
export function parseDraftSaveConflictResponse(
  value: unknown,
  clientCandidate: 'editable' | 'null' = 'editable',
): DraftSaveConflictResponse | null {
  if (!isPlainRecord(value) || !hasExactKeys(value, [
    'code', 'expected_lock_version', 'current_lock_version', 'client_candidate', 'server',
  ])) return null;
  const candidateOk = clientCandidate === 'null'
    ? value.client_candidate === null
    : isEditableModelDraft(value.client_candidate);
  if (value.code !== 'stale_draft'
    || !isNonnegativeInteger(value.expected_lock_version)
    || !isNonnegativeInteger(value.current_lock_version)
    || !candidateOk
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

function isLegacyPromptSourceRecord(value: unknown): value is LegacyPromptSourceRecord {
  return isPlainRecord(value)
    && hasExactKeys(value, ['prompt_text', 'revision_id', 'content_hash'])
    && typeof value.prompt_text === 'string'
    && isPositiveInteger(value.revision_id)
    && typeof value.content_hash === 'string'
    && /^[0-9a-f]{64}$/.test(value.content_hash);
}

export function parseLegacyPromptSourceResponse(
  value: unknown,
): LegacyPromptSourceResponse | null {
  if (!isPlainRecord(value)
    || !hasExactKeys(value, ['draft', 'agent_key', 'lock_version', 'source'])
    || !isDraftMetadata(value.draft)
    || typeof value.agent_key !== 'string'
    || !(AGENT_KEYS as readonly string[]).includes(value.agent_key)
    || !isNonnegativeInteger(value.lock_version)
    || !isLegacyPromptSourceRecord(value.source)) return null;
  if (value.lock_version !== value.draft.lock_version) return null;
  return value as unknown as LegacyPromptSourceResponse;
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

async function postDraftOperation(
  agentKey: AgentKey,
  operation: 'protected-assembly-upgrade' | 'schema-contract-upgrade' | 'legacy-prompt-source',
  request: DraftLockRequest,
): Promise<{ status: number; payload: unknown; statusText: string }> {
  const response = await fetch(
    `${API_BASE_URL}/api/admin/agent-definitions/draft/${agentKey}/${operation}`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(request),
    },
  );
  const payload: unknown = await response.json().catch(() => null);
  return { status: response.status, payload, statusText: response.statusText };
}

/**
 * Applies the server-owned protected-assembly upgrade. The body is exactly
 * `{ lock_version }`; the client supplies no prompt, no rules, and no candidate.
 */
export async function upgradeDraftProtectedAssembly(
  agentKey: AgentKey,
  request: DraftLockRequest,
): Promise<DraftSaveSuccessResponse> {
  const { status, payload, statusText } = await postDraftOperation(
    agentKey,
    'protected-assembly-upgrade',
    request,
  );

  if (status === 200) {
    const parsed = parseDraftSaveSuccessResponse(payload);
    if (parsed === null) throw new InvalidDraftSaveResponseError();
    return parsed;
  }
  if (status === 409) {
    const parsed = parseDraftSaveConflictResponse(payload, 'null');
    if (parsed === null) throw new InvalidDraftSaveResponseError();
    throw new AgentDefinitionApiError(status, parsed, statusText, true);
  }
  if (status === 422) {
    const parsed = parseDraftValidationErrorResponse(payload);
    if (parsed === null) throw new InvalidDraftSaveResponseError();
    throw new AgentDefinitionApiError(status, parsed, statusText, true);
  }
  throw new AgentDefinitionApiError(status, payload, statusText, true);
}

/**
 * Reads the retained published Graph Version 1 prompt source. This route never
 * writes, so its success carries no definition and no draft mutation.
 *
 * CLIENT-ONLY CONTRACT, not enforced by the backend: the reducer additionally treats a
 * 200 as invalid unless its `agent_key` and `lock_version` match the operation the
 * client started, on the reasoning that a route which never writes cannot have moved
 * the lock. The backend schema does not require that correspondence, so a future
 * backend change (for example returning the latest lock rather than the requested one)
 * would surface here as "the server response was invalid" rather than as a parse error.
 * See `sourceRecoverySucceeded` in `draftEditorState.ts`.
 */

/**
 * Applies the server-owned schema-contract upgrade. The body is exactly
 * `{ lock_version }`; the client supplies no prompt, no rules, and no candidate.
 */
export async function upgradeDraftSchemaContract(
  agentKey: AgentKey,
  request: DraftLockRequest,
): Promise<DraftSaveSuccessResponse> {
  const { status, payload, statusText } = await postDraftOperation(
    agentKey,
    'schema-contract-upgrade',
    request,
  );

  if (status === 200) {
    const parsed = parseDraftSaveSuccessResponse(payload);
    if (parsed === null) throw new InvalidDraftSaveResponseError();
    return parsed;
  }
  if (status === 409) {
    const parsed = parseDraftSaveConflictResponse(payload, 'null');
    if (parsed === null) throw new InvalidDraftSaveResponseError();
    throw new AgentDefinitionApiError(status, parsed, statusText, true);
  }
  if (status === 422) {
    const parsed = parseDraftValidationErrorResponse(payload);
    if (parsed === null) throw new InvalidDraftSaveResponseError();
    throw new AgentDefinitionApiError(status, parsed, statusText, true);
  }
  throw new AgentDefinitionApiError(status, payload, statusText, true);
}

export async function readDraftLegacyPromptSource(
  agentKey: AgentKey,
  request: DraftLockRequest,
): Promise<LegacyPromptSourceResponse> {
  const { status, payload, statusText } = await postDraftOperation(
    agentKey,
    'legacy-prompt-source',
    request,
  );

  if (status === 200) {
    const parsed = parseLegacyPromptSourceResponse(payload);
    if (parsed === null) throw new InvalidDraftSaveResponseError();
    return parsed;
  }
  if (status === 409) {
    const parsed = parseDraftSaveConflictResponse(payload, 'null');
    if (parsed === null) throw new InvalidDraftSaveResponseError();
    throw new AgentDefinitionApiError(status, parsed, statusText, true);
  }
  if (status === 422) {
    const parsed = parseDraftValidationErrorResponse(payload);
    if (parsed === null) throw new InvalidDraftSaveResponseError();
    throw new AgentDefinitionApiError(status, parsed, statusText, true);
  }
  throw new AgentDefinitionApiError(status, payload, statusText, true);
}

// ============================================================
// #266 model endpoint discovery: GET /api/admin/agent-definitions/model-endpoints
// ============================================================

const MODEL_ENDPOINTS_URL = `${API_BASE_URL}/api/admin/agent-definitions/model-endpoints`;

/** One discovered Databricks foundation-model endpoint. Only `name` is ever saved. */
export interface SystemModelEndpoint {
  name: string;
  display_name: string | null;
  description: string | null;
  docs: string | null;
}

export type ModelEndpointCatalogFailureCode = 'catalog_forbidden' | 'catalog_unavailable';

/** A valid, typed 403 or 503 discovery envelope. The message is the server's own text. */
export class ModelEndpointCatalogApiError extends Error {
  readonly status: 403 | 503;
  readonly code: ModelEndpointCatalogFailureCode;
  readonly retryable: boolean;

  constructor(
    status: 403 | 503,
    code: ModelEndpointCatalogFailureCode,
    message: string,
    retryable: boolean,
  ) {
    super(message);
    this.name = 'ModelEndpointCatalogApiError';
    this.status = status;
    this.code = code;
    this.retryable = retryable;
  }
}

/** A 2xx discovery response that does not match the exact contract. */
export class InvalidModelEndpointCatalogResponseError extends Error {
  constructor() {
    super('Model endpoint discovery response did not match the expected contract.');
    this.name = 'InvalidModelEndpointCatalogResponseError';
  }
}

function isNullableString(value: unknown): value is string | null {
  return value === null || typeof value === 'string';
}

function isSystemModelEndpoint(value: unknown): value is SystemModelEndpoint {
  return isPlainRecord(value)
    && hasExactKeys(value, ['name', 'display_name', 'description', 'docs'])
    && typeof value.name === 'string' && value.name.length > 0
    && isNullableString(value.display_name)
    && isNullableString(value.description)
    && isNullableString(value.docs);
}

function parseSystemModelDiscovery(value: unknown): SystemModelEndpoint[] | null {
  if (!isPlainRecord(value) || !hasExactKeys(value, ['items'])) return null;
  const { items } = value;
  if (!Array.isArray(items) || !items.every(isSystemModelEndpoint)) return null;
  if (new Set(items.map((item) => item.name)).size !== items.length) return null;
  return items.map((item) => ({
    name: item.name,
    display_name: item.display_name,
    description: item.description,
    docs: item.docs,
  }));
}

const CATALOG_FAILURE_CONTRACT = {
  403: { code: 'catalog_forbidden', retryable: false },
  503: { code: 'catalog_unavailable', retryable: true },
} as const;

function parseModelEndpointCatalogFailure(
  status: number,
  value: unknown,
): ModelEndpointCatalogApiError | null {
  if (status !== 403 && status !== 503) return null;
  const contract = CATALOG_FAILURE_CONTRACT[status];
  if (!isPlainRecord(value)
    || !hasExactKeys(value, ['code', 'message', 'retryable'])
    || value.code !== contract.code
    || value.retryable !== contract.retryable
    || typeof value.message !== 'string') return null;
  return new ModelEndpointCatalogApiError(status, contract.code, value.message, contract.retryable);
}

/**
 * Reads the identity-scoped discovery list. Every call is its own GET: nothing is
 * cached or coalesced, so each explicit Refresh reaches the server. The body is read
 * once. A malformed 200 is `InvalidModelEndpointCatalogResponseError`; a valid 403/503
 * envelope is `ModelEndpointCatalogApiError`; any other status is
 * `AgentDefinitionApiError`; a transport failure propagates unchanged.
 */
export async function getSystemModelEndpoints(): Promise<SystemModelEndpoint[]> {
  const response = await fetch(MODEL_ENDPOINTS_URL, {
    method: 'GET',
    headers: { Accept: 'application/json' },
  });
  const payload: unknown = await response.json().catch(() => undefined);

  if (response.status === 200) {
    const items = parseSystemModelDiscovery(payload);
    if (items === null) throw new InvalidModelEndpointCatalogResponseError();
    return items;
  }
  if (response.ok) throw new InvalidModelEndpointCatalogResponseError();
  const failure = parseModelEndpointCatalogFailure(response.status, payload);
  if (failure !== null) throw failure;
  throw new AgentDefinitionApiError(response.status, payload ?? null, response.statusText);
}

// ============================================================
// #266 saved-candidate structured-output probe:
// POST /api/admin/agent-definitions/draft/{agent_key}/model-endpoint-probe
// ============================================================

/** The exact saved candidate the server probed; it copies it before the model call. */
export interface StructuredOutputProbeIdentity {
  endpoint_name: string;
  candidate_hash: string;
  lock_version: number;
}

export interface StructuredOutputProbeSuccessResponse extends StructuredOutputProbeIdentity {
  code: 'structured_output_probe_succeeded';
}

export type StructuredOutputProbeFailureCode =
  | 'unsupported_structured_output'
  | 'endpoint_probe_forbidden'
  | 'structured_output_probe_failed';

export interface StructuredOutputProbeFailureResponse extends StructuredOutputProbeIdentity {
  code: StructuredOutputProbeFailureCode;
  message: string;
  retryable: boolean;
}

/**
 * The route's exact status table (#266 Task 5 ruling): forbidden and unsupported are
 * never retryable; only the ambiguous provider or transport failure is.
 */
const PROBE_FAILURE_CONTRACT = {
  403: { code: 'endpoint_probe_forbidden', retryable: false },
  422: { code: 'unsupported_structured_output', retryable: false },
  503: { code: 'structured_output_probe_failed', retryable: true },
} as const;

/** A valid, typed probe failure. Its message is the server's code-owned, sanitized text. */
export class StructuredOutputProbeApiError extends Error {
  readonly status: 403 | 422 | 503;
  readonly failure: StructuredOutputProbeFailureResponse;

  constructor(status: 403 | 422 | 503, failure: StructuredOutputProbeFailureResponse) {
    super(failure.message);
    this.name = 'StructuredOutputProbeApiError';
    this.status = status;
    this.failure = failure;
  }
}

function probeIdentityFrom(value: Record<string, unknown>): StructuredOutputProbeIdentity | null {
  if (typeof value.endpoint_name !== 'string' || value.endpoint_name.length === 0) return null;
  if (typeof value.candidate_hash !== 'string' || !/^[0-9a-f]{64}$/.test(value.candidate_hash)) return null;
  if (!isNonnegativeInteger(value.lock_version)) return null;
  return {
    endpoint_name: value.endpoint_name,
    candidate_hash: value.candidate_hash,
    lock_version: value.lock_version,
  };
}

export function parseStructuredOutputProbeSuccess(
  value: unknown,
): StructuredOutputProbeSuccessResponse | null {
  if (!isPlainRecord(value)
    || !hasExactKeys(value, ['code', 'endpoint_name', 'candidate_hash', 'lock_version'])
    || value.code !== 'structured_output_probe_succeeded') return null;
  const identity = probeIdentityFrom(value);
  return identity === null ? null : { code: 'structured_output_probe_succeeded', ...identity };
}

export function parseStructuredOutputProbeFailure(
  status: number,
  value: unknown,
): StructuredOutputProbeApiError | null {
  if (status !== 403 && status !== 422 && status !== 503) return null;
  const contract = PROBE_FAILURE_CONTRACT[status];
  if (!isPlainRecord(value)
    || !hasExactKeys(value, [
      'code', 'message', 'retryable', 'endpoint_name', 'candidate_hash', 'lock_version',
    ])
    || value.code !== contract.code
    || value.retryable !== contract.retryable
    || typeof value.message !== 'string') return null;
  const identity = probeIdentityFrom(value);
  if (identity === null) return null;
  return new StructuredOutputProbeApiError(status, {
    code: contract.code,
    message: value.message,
    retryable: contract.retryable,
    ...identity,
  });
}

/**
 * Probes the role's **saved** candidate once. The body is exactly `{ lock_version }`:
 * the endpoint, sampling values, prompt and schema are all server-owned, and nothing
 * here saves, approves or aliases anything.
 *
 * - 200: the exact success, or `InvalidDraftSaveResponseError`.
 * - 403/503: the exact typed failure (`StructuredOutputProbeApiError`); any other body
 *   at those statuses (an authorization or proxy error) is a plain
 *   `AgentDefinitionApiError`, so it can never be offered as a typed retry.
 * - 422: the typed unsupported failure, or the existing draft rejection envelope (the
 *   saved-name policy re-check) as `AgentDefinitionApiError`; anything else is invalid.
 * - 409: the existing null-candidate conflict as `AgentDefinitionApiError`.
 * - Any other status is `AgentDefinitionApiError`; a transport failure propagates.
 */
export async function probeDraftStructuredOutput(
  agentKey: AgentKey,
  request: DraftLockRequest,
): Promise<StructuredOutputProbeSuccessResponse> {
  const response = await fetch(
    `${API_BASE_URL}/api/admin/agent-definitions/draft/${agentKey}/model-endpoint-probe`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ lock_version: request.lock_version }),
    },
  );
  const payload: unknown = await response.json().catch(() => null);
  const { status, statusText } = response;

  if (status === 200) {
    const parsed = parseStructuredOutputProbeSuccess(payload);
    if (parsed === null) throw new InvalidDraftSaveResponseError();
    return parsed;
  }
  if (status === 409) {
    const parsed = parseDraftSaveConflictResponse(payload, 'null');
    if (parsed === null) throw new InvalidDraftSaveResponseError();
    throw new AgentDefinitionApiError(status, parsed, statusText);
  }
  const typed = parseStructuredOutputProbeFailure(status, payload);
  if (typed !== null) throw typed;
  if (status === 422) {
    const parsed = parseDraftValidationErrorResponse(payload);
    if (parsed === null) throw new InvalidDraftSaveResponseError();
    throw new AgentDefinitionApiError(status, parsed, statusText);
  }
  throw new AgentDefinitionApiError(status, payload, statusText);
}

// ============================================================
// #267 Agent Test Cases: /api/admin/agent-definitions/test-cases
// #267 Agent Test Runs: /api/admin/agent-definitions/{draft|published}/{agent_key}/test-runs
// ============================================================

const AGENT_DEFINITIONS_URL = `${API_BASE_URL}/api/admin/agent-definitions`;

/** Exactly the one field the server's assembler reads for a case (#267 C22). */
export interface TestCaseAssemblyContext {
  design_system_active: boolean;
}

/** One Agent Test Case version exactly as the case routes serialize it. */
export interface TestCaseListEntry {
  id: number;
  agent_key: AgentKey;
  name: string;
  version: number;
  is_active: boolean;
  is_required: boolean;
  synthetic_payload: Record<string, JsonValue>;
  assembly_context: TestCaseAssemblyContext;
  created_by: string;
  created_at: string;
  updated_by: string;
  updated_at: string;
  /** Display-only reminder that payloads must be synthetic (P7); always `true`. */
  is_synthetic_data_warning: true;
}

/** `POST /test-cases`: a new case lineage at version 1. */
export interface CreateTestCaseRequest {
  agent_key: AgentKey;
  name: string;
  synthetic_payload: Record<string, JsonValue>;
  assembly_context: TestCaseAssemblyContext;
  is_required: boolean;
}

/** `PUT /test-cases/{id}`: supersede an active version. `name` is echoed, never changed. */
export interface UpdateTestCaseRequest {
  name: string;
  synthetic_payload: Record<string, JsonValue>;
  assembly_context: TestCaseAssemblyContext;
  is_required: boolean;
}

/** `POST /draft/{agent_key}/test-runs`: the case and the lock of the saved candidate. */
export interface CandidateTestRunRequest {
  test_case_id: number;
  lock_version: number;
}

/** `POST /published/{agent_key}/test-runs`: the case only; no draft is read. */
export interface PublishedBaselineTestRunRequest {
  test_case_id: number;
}

export type TestRunKind = 'candidate' | 'published_baseline';
export type TestRunExecutionStatus = 'completed' | 'model_error' | 'assembly_error' | 'incomplete';
export type TestRunVerdict = 'approved' | 'rejected';

export interface DeterministicCheckIssue {
  code: string;
  field: string | null;
}

export interface DeterministicCheckResult {
  name: 'output_contract' | 'execution';
  passed: boolean;
  message: string | null;
  issues: DeterministicCheckIssue[];
}

/**
 * One immutable run, as evidence. Execute responses carry boolean currency flags and
 * reads carry `null`. The four verdict fields are always present: all `null` until a
 * verdict is recorded, then `verdict`, `verdict_reviewer` and `verdict_at` together,
 * with `verdict_notes` optional (#268).
 */
export interface TestRunEvidence {
  run_id: number;
  run_kind: TestRunKind;
  test_case_id: number;
  test_case_version: number;
  agent_key: AgentKey;
  candidate_hash: string;
  compared_release_id: number;
  compared_definition_revision_id: number;
  synthetic_payload: Record<string, JsonValue>;
  model_payload: Record<string, JsonValue>;
  assembled_prompt: string | null;
  execution_status: TestRunExecutionStatus;
  error_detail: string | null;
  deterministic_checks_passed: boolean;
  deterministic_check_results: DeterministicCheckResult[];
  candidate_raw_output: Record<string, JsonValue> | null;
  candidate_structured_output: Record<string, JsonValue> | null;
  baseline_raw_output: Record<string, JsonValue> | null;
  baseline_structured_output: Record<string, JsonValue> | null;
  latency_ms: number | null;
  input_tokens: number | null;
  output_tokens: number | null;
  run_by: string;
  run_at: string;
  verdict: TestRunVerdict | null;
  verdict_reviewer: string | null;
  verdict_at: string | null;
  verdict_notes: string | null;
  candidate_is_current: boolean | null;
  base_release_is_current: boolean | null;
}

/**
 * The typed refusals of the case and run routes that are not draft refusals. A
 * `stale_draft` 409 and an `invalid_draft` 422 stay the existing draft envelopes on
 * `AgentDefinitionApiError`, so the reducer reconciles them exactly as it does a probe.
 */
export type AgentTestFailure =
  | { code: 'stale_test_case'; test_case_id: number; message: string }
  | { code: 'invalid_test_case'; issues: DraftFieldError[] }
  | { code: 'test_case_not_found' }
  | { code: 'test_run_unavailable'; message: string; retryable: true };

/** A valid, typed case or run refusal. */
export class AgentTestApiError extends Error {
  readonly status: number;
  readonly failure: AgentTestFailure;

  constructor(status: number, failure: AgentTestFailure) {
    super(failure.code);
    this.name = 'AgentTestApiError';
    this.status = status;
    this.failure = failure;
  }
}

/** A case or run response body that does not match the exact contract. */
export class InvalidTestRunResponseError extends Error {
  constructor() {
    super('Agent test response did not match the expected contract.');
    this.name = 'InvalidTestRunResponseError';
  }
}

/** The route's exact 404 detail for an unknown case id. */
export const TEST_CASE_NOT_FOUND_DETAIL = 'Test case not found';

/** The route's exact 503 body: no row was written and the request may be retried. */
export const TEST_RUN_UNAVAILABLE = {
  code: 'test_run_unavailable',
  message: 'Test run storage is temporarily unavailable. Retry the request.',
  retryable: true,
} as const;

const TEST_RUN_KINDS: readonly TestRunKind[] = ['candidate', 'published_baseline'];
const TEST_RUN_STATUSES: readonly TestRunExecutionStatus[] = [
  'completed', 'model_error', 'assembly_error', 'incomplete',
];
const TEST_RUN_VERDICTS: readonly TestRunVerdict[] = ['approved', 'rejected'];
const DETERMINISTIC_CHECK_NAMES: readonly DeterministicCheckResult['name'][] = ['output_contract', 'execution'];
const LOWERCASE_SHA256 = /^[0-9a-f]{64}$/;

const TEST_CASE_KEYS = [
  'id', 'agent_key', 'name', 'version', 'is_active', 'is_required', 'synthetic_payload',
  'assembly_context', 'created_by', 'created_at', 'updated_by', 'updated_at',
  'is_synthetic_data_warning',
] as const;

const TEST_RUN_KEYS = [
  'run_id', 'run_kind', 'test_case_id', 'test_case_version', 'agent_key', 'candidate_hash',
  'compared_release_id', 'compared_definition_revision_id', 'synthetic_payload', 'model_payload',
  'assembled_prompt', 'execution_status', 'error_detail', 'deterministic_checks_passed',
  'deterministic_check_results', 'candidate_raw_output', 'candidate_structured_output',
  'baseline_raw_output', 'baseline_structured_output', 'latency_ms', 'input_tokens',
  'output_tokens', 'run_by', 'run_at', 'verdict', 'verdict_reviewer', 'verdict_at',
  'verdict_notes', 'candidate_is_current', 'base_release_is_current',
] as const;

function isAgentKey(value: unknown): value is AgentKey {
  return typeof value === 'string' && (AGENT_KEYS as readonly string[]).includes(value);
}

function isJsonObject(value: unknown): value is Record<string, JsonValue> {
  return isPlainRecord(value) && isJsonValue(value);
}

function isNullableJsonObject(value: unknown): value is Record<string, JsonValue> | null {
  return value === null || isJsonObject(value);
}

function isNullableNonnegativeInteger(value: unknown): value is number | null {
  return value === null || isNonnegativeInteger(value);
}

function isNullableBoolean(value: unknown): value is boolean | null {
  return value === null || typeof value === 'boolean';
}

/**
 * The verdict fields' types and pairing: `verdict`, `verdict_reviewer` and `verdict_at`
 * are all null or all set, and notes exist only beside a verdict.
 */
function isVerdictRecord(value: Record<string, unknown>): boolean {
  if (value.verdict === null) {
    return value.verdict_reviewer === null && value.verdict_at === null && value.verdict_notes === null;
  }
  return typeof value.verdict === 'string'
    && (TEST_RUN_VERDICTS as readonly string[]).includes(value.verdict)
    && typeof value.verdict_reviewer === 'string'
    && typeof value.verdict_at === 'string'
    && isNullableString(value.verdict_notes);
}

function isTestCaseListEntry(value: unknown): value is TestCaseListEntry {
  return isPlainRecord(value)
    && hasExactKeys(value, TEST_CASE_KEYS)
    && isPositiveInteger(value.id)
    && isAgentKey(value.agent_key)
    && typeof value.name === 'string' && value.name.length > 0
    && isPositiveInteger(value.version)
    && typeof value.is_active === 'boolean'
    && typeof value.is_required === 'boolean'
    && isJsonObject(value.synthetic_payload)
    && isPlainRecord(value.assembly_context)
    && hasExactKeys(value.assembly_context, ['design_system_active'])
    && typeof value.assembly_context.design_system_active === 'boolean'
    && typeof value.created_by === 'string'
    && typeof value.created_at === 'string'
    && typeof value.updated_by === 'string'
    && typeof value.updated_at === 'string'
    && value.is_synthetic_data_warning === true;
}

function isDeterministicCheckIssue(value: unknown): value is DeterministicCheckIssue {
  return isPlainRecord(value)
    && hasExactKeys(value, ['code', 'field'])
    && typeof value.code === 'string'
    && isNullableString(value.field);
}

function isDeterministicCheckResult(value: unknown): value is DeterministicCheckResult {
  return isPlainRecord(value)
    && hasExactKeys(value, ['name', 'passed', 'message', 'issues'])
    && typeof value.name === 'string'
    && (DETERMINISTIC_CHECK_NAMES as readonly string[]).includes(value.name)
    && typeof value.passed === 'boolean'
    && isNullableString(value.message)
    && Array.isArray(value.issues)
    && value.issues.every(isDeterministicCheckIssue);
}

/** The strict evidence parser: every field, exact keys, and no `-1` sentinel id. */
export function parseTestRunEvidence(value: unknown): TestRunEvidence | null {
  if (!isPlainRecord(value) || !hasExactKeys(value, TEST_RUN_KEYS)) return null;
  const valid = isPositiveInteger(value.run_id)
    && typeof value.run_kind === 'string'
    && (TEST_RUN_KINDS as readonly string[]).includes(value.run_kind)
    && isPositiveInteger(value.test_case_id)
    && isPositiveInteger(value.test_case_version)
    && isAgentKey(value.agent_key)
    && typeof value.candidate_hash === 'string' && LOWERCASE_SHA256.test(value.candidate_hash)
    && isPositiveInteger(value.compared_release_id)
    && isPositiveInteger(value.compared_definition_revision_id)
    && isJsonObject(value.synthetic_payload)
    && isJsonObject(value.model_payload)
    && isNullableString(value.assembled_prompt)
    && typeof value.execution_status === 'string'
    && (TEST_RUN_STATUSES as readonly string[]).includes(value.execution_status)
    && isNullableString(value.error_detail)
    && typeof value.deterministic_checks_passed === 'boolean'
    && Array.isArray(value.deterministic_check_results)
    && value.deterministic_check_results.every(isDeterministicCheckResult)
    && isNullableJsonObject(value.candidate_raw_output)
    && isNullableJsonObject(value.candidate_structured_output)
    && isNullableJsonObject(value.baseline_raw_output)
    && isNullableJsonObject(value.baseline_structured_output)
    && (value.latency_ms === null || (isFiniteNumber(value.latency_ms) && value.latency_ms >= 0))
    && isNullableNonnegativeInteger(value.input_tokens)
    && isNullableNonnegativeInteger(value.output_tokens)
    && typeof value.run_by === 'string'
    && typeof value.run_at === 'string'
    && isVerdictRecord(value)
    && isNullableBoolean(value.candidate_is_current)
    && isNullableBoolean(value.base_release_is_current);
  return valid ? value as unknown as TestRunEvidence : null;
}

function parseTestCaseList(value: unknown): TestCaseListEntry[] | null {
  if (!isPlainRecord(value) || !hasExactKeys(value, ['items'])) return null;
  const { items } = value;
  if (!Array.isArray(items) || !items.every(isTestCaseListEntry)) return null;
  return items;
}

function parseTestRunList(value: unknown): TestRunEvidence[] | null {
  if (!isPlainRecord(value) || !hasExactKeys(value, ['items']) || !Array.isArray(value.items)) return null;
  const parsed = value.items.map(parseTestRunEvidence);
  return parsed.every((item): item is TestRunEvidence => item !== null) ? parsed : null;
}

function parseStaleTestCase(value: unknown): AgentTestFailure | null {
  if (!isPlainRecord(value)
    || !hasExactKeys(value, ['code', 'test_case_id', 'message'])
    || value.code !== 'stale_test_case'
    || !isPositiveInteger(value.test_case_id)
    || typeof value.message !== 'string') return null;
  return { code: 'stale_test_case', test_case_id: value.test_case_id, message: value.message };
}

function parseInvalidTestCase(value: unknown): AgentTestFailure | null {
  if (!isPlainRecord(value)
    || !hasExactKeys(value, ['code', 'issues'])
    || value.code !== 'invalid_test_case'
    || !Array.isArray(value.issues)
    || value.issues.length === 0
    || !value.issues.every(isDraftFieldError)) return null;
  return { code: 'invalid_test_case', issues: value.issues };
}

function isTestCaseNotFound(value: unknown): boolean {
  return isPlainRecord(value)
    && hasExactKeys(value, ['detail'])
    && value.detail === TEST_CASE_NOT_FOUND_DETAIL;
}

function isTestRunUnavailable(value: unknown): boolean {
  return isPlainRecord(value)
    && hasExactKeys(value, ['code', 'message', 'retryable'])
    && value.code === TEST_RUN_UNAVAILABLE.code
    && value.message === TEST_RUN_UNAVAILABLE.message
    && value.retryable === TEST_RUN_UNAVAILABLE.retryable;
}

async function agentTestRequest(
  path: string,
  method: 'GET' | 'POST' | 'DELETE',
  body?: object,
): Promise<{ status: number; payload: unknown; statusText: string }> {
  const response = await fetch(`${AGENT_DEFINITIONS_URL}${path}`, {
    method,
    headers: body === undefined ? { Accept: 'application/json' } : { 'Content-Type': 'application/json' },
    ...(body === undefined ? {} : { body: JSON.stringify(body) }),
  });
  const payload: unknown = await response.json().catch(() => null);
  return { status: response.status, payload, statusText: response.statusText };
}

/**
 * The case routes' refusals: an ordered `invalid_test_case` 422, a `stale_test_case`
 * 409 and the exact 404. A malformed 422 or 409 is invalid; any other status is a plain
 * `AgentDefinitionApiError`.
 */
function testCaseRefusal(status: number, payload: unknown, statusText: string): Error {
  if (status === 422) {
    const failure = parseInvalidTestCase(payload);
    return failure === null ? new InvalidTestRunResponseError() : new AgentTestApiError(status, failure);
  }
  if (status === 409) {
    const failure = parseStaleTestCase(payload);
    return failure === null ? new InvalidTestRunResponseError() : new AgentTestApiError(status, failure);
  }
  if (status === 404 && isTestCaseNotFound(payload)) {
    return new AgentTestApiError(status, { code: 'test_case_not_found' });
  }
  return new AgentDefinitionApiError(status, payload, statusText);
}

/** Lists one role's **active** case versions (P5: only active versions can be run). */
export async function listTestCases(agentKey: AgentKey): Promise<TestCaseListEntry[]> {
  const { status, payload, statusText } = await agentTestRequest(
    `/test-cases?agent_key=${encodeURIComponent(agentKey)}`,
    'GET',
  );
  if (status === 200) {
    const items = parseTestCaseList(payload);
    if (items === null || items.some((item) => item.agent_key !== agentKey || !item.is_active)) {
      throw new InvalidTestRunResponseError();
    }
    return items;
  }
  throw testCaseRefusal(status, payload, statusText);
}

/** Adds a new case lineage. The body is exactly the five typed fields. */
export async function createTestCase(request: CreateTestCaseRequest): Promise<TestCaseListEntry> {
  const { status, payload, statusText } = await agentTestRequest('/test-cases', 'POST', {
    agent_key: request.agent_key,
    name: request.name,
    synthetic_payload: request.synthetic_payload,
    assembly_context: { design_system_active: request.assembly_context.design_system_active },
    is_required: request.is_required,
  });
  if (status === 201) {
    if (!isTestCaseListEntry(payload)) throw new InvalidTestRunResponseError();
    return payload;
  }
  throw testCaseRefusal(status, payload, statusText);
}

/**
 * Supersedes one **active** version: the server retires it and returns `version + 1`
 * with the same name, or returns the current version unchanged when the content is
 * identical. The old row is kept as history.
 */
export async function updateTestCase(
  testCaseId: number,
  request: UpdateTestCaseRequest,
): Promise<TestCaseListEntry> {
  const response = await fetch(`${AGENT_DEFINITIONS_URL}/test-cases/${testCaseId}`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      name: request.name,
      synthetic_payload: request.synthetic_payload,
      assembly_context: { design_system_active: request.assembly_context.design_system_active },
      is_required: request.is_required,
    }),
  });
  const payload: unknown = await response.json().catch(() => null);
  if (response.status === 200) {
    if (!isTestCaseListEntry(payload) || !payload.is_active) throw new InvalidTestRunResponseError();
    return payload;
  }
  throw testCaseRefusal(response.status, payload, response.statusText);
}

/** Retires one case version with a bodyless DELETE; the row is kept as history. */
export async function retireTestCase(testCaseId: number): Promise<TestCaseListEntry> {
  const { status, payload, statusText } = await agentTestRequest(`/test-cases/${testCaseId}`, 'DELETE');
  if (status === 200) {
    if (!isTestCaseListEntry(payload) || payload.is_active) throw new InvalidTestRunResponseError();
    return payload;
  }
  throw testCaseRefusal(status, payload, statusText);
}

/**
 * The two execute routes' refusals, in the server's order:
 * - 201 is evidence, including a persisted `model_error` run; a malformed 201 is invalid.
 * - 409 is the probe-style null-candidate `stale_draft` conflict on
 *   `AgentDefinitionApiError`, or a typed `stale_test_case`; anything else is invalid.
 * - 422 is the `invalid_draft` rejection on `AgentDefinitionApiError`, or a typed
 *   `invalid_test_case`; anything else is invalid.
 * - The exact 404 and the exact retryable 503 are typed; any other body at those
 *   statuses (a proxy or router error) is a plain `AgentDefinitionApiError`.
 */
function testRunRefusal(status: number, payload: unknown, statusText: string): Error {
  if (status === 409) {
    if (isPlainRecord(payload) && payload.code === 'stale_draft') {
      const conflict = parseDraftSaveConflictResponse(payload, 'null');
      return conflict === null ? new InvalidTestRunResponseError() : new AgentDefinitionApiError(status, conflict, statusText);
    }
    return testCaseRefusal(status, payload, statusText);
  }
  if (status === 422) {
    if (isPlainRecord(payload) && payload.code === 'invalid_draft') {
      const rejection = parseDraftValidationErrorResponse(payload);
      return rejection === null ? new InvalidTestRunResponseError() : new AgentDefinitionApiError(status, rejection, statusText);
    }
    return testCaseRefusal(status, payload, statusText);
  }
  if (status === 503 && isTestRunUnavailable(payload)) {
    return new AgentTestApiError(status, { ...TEST_RUN_UNAVAILABLE });
  }
  return testCaseRefusal(status, payload, statusText);
}

async function executeTestRun(path: string, body: object): Promise<TestRunEvidence> {
  const { status, payload, statusText } = await agentTestRequest(path, 'POST', body);
  if (status === 201) {
    const evidence = parseTestRunEvidence(payload);
    if (evidence === null) throw new InvalidTestRunResponseError();
    return evidence;
  }
  throw testRunRefusal(status, payload, statusText);
}

/**
 * Runs one active case version against the role's **saved** draft candidate. The body
 * is exactly `{ test_case_id, lock_version }`; the prompt, payload, endpoint, sampling
 * values and baseline are all server-owned.
 */
export function executeCandidateTestRun(
  agentKey: AgentKey,
  request: CandidateTestRunRequest,
): Promise<TestRunEvidence> {
  return executeTestRun(`/draft/${agentKey}/test-runs`, {
    test_case_id: request.test_case_id,
    lock_version: request.lock_version,
  });
}

/** Reruns one active case version against the active published definition. No lock. */
export function executePublishedBaselineTestRun(
  agentKey: AgentKey,
  request: PublishedBaselineTestRunRequest,
): Promise<TestRunEvidence> {
  return executeTestRun(`/published/${agentKey}/test-runs`, { test_case_id: request.test_case_id });
}

/** Reads one stored run. Its currency flags are `null`: nothing recomputes them. */
export async function getTestRun(runId: number): Promise<TestRunEvidence> {
  const { status, payload, statusText } = await agentTestRequest(`/test-runs/${runId}`, 'GET');
  if (status === 200) {
    const evidence = parseTestRunEvidence(payload);
    if (evidence === null) throw new InvalidTestRunResponseError();
    return evidence;
  }
  throw new AgentDefinitionApiError(status, payload, statusText);
}

/** Reads one case version's own runs, newest first, at most `limit` (the server's 1-100). */
export async function listTestCaseRuns(testCaseId: number, limit?: number): Promise<TestRunEvidence[]> {
  const query = limit === undefined ? '' : `?limit=${limit}`;
  const { status, payload, statusText } = await agentTestRequest(`/test-cases/${testCaseId}/runs${query}`, 'GET');
  if (status === 200) {
    const items = parseTestRunList(payload);
    if (items === null) throw new InvalidTestRunResponseError();
    return items;
  }
  throw testCaseRefusal(status, payload, statusText);
}

// ============================================================
// #268: verdicts and draft readiness (C16, C17, C22)
// ============================================================
// #269 consumes these names; it must not define a second readiness type (C22).

/** `POST /test-runs/{run_id}/verdict`: exactly `{ verdict, notes }`; `notes` is always sent. */
export interface TestRunVerdictRequest {
  verdict: TestRunVerdict;
  notes: string | null;
}

export type TestRunIneligibilityReason = 'not_completed' | 'checks_failed' | 'linked_to_release';

/**
 * The verdict route's typed refusals. Nothing was written for any of them; the reviewer
 * is always the authenticated principal, so no refusal names one.
 */
export type TestRunVerdictFailure =
  | { code: 'test_run_not_found' }
  | { code: 'ineligible_for_approval'; reason: TestRunIneligibilityReason; message: string }
  | { code: 'invalid_verdict'; errors: DraftFieldError[] }
  | { code: 'verdict_forbidden'; detail: string };

/** A valid, typed verdict refusal. */
export class TestRunVerdictApiError extends Error {
  readonly status: number;
  readonly failure: TestRunVerdictFailure;

  constructor(status: number, failure: TestRunVerdictFailure) {
    super(failure.code);
    this.name = 'TestRunVerdictApiError';
    this.status = status;
    this.failure = failure;
  }
}

/** The route's exact 404 detail for an unknown (or cleaned-up) run id. */
export const TEST_RUN_NOT_FOUND_DETAIL = 'Test run not found';

const VERDICT_REQUEST_KEYS = ['verdict', 'notes'] as const;
const INELIGIBILITY_REASONS: readonly TestRunIneligibilityReason[] = ['not_completed', 'checks_failed', 'linked_to_release'];

function parseTestRunVerdictFailure(status: number, payload: unknown): TestRunVerdictFailure | null {
  if (!isPlainRecord(payload)) return null;
  if (status === 404) {
    return hasExactKeys(payload, ['detail']) && payload.detail === TEST_RUN_NOT_FOUND_DETAIL
      ? { code: 'test_run_not_found' }
      : null;
  }
  if (status === 403) {
    return hasExactKeys(payload, ['detail']) && typeof payload.detail === 'string'
      ? { code: 'verdict_forbidden', detail: payload.detail }
      : null;
  }
  if (status !== 422) return null;
  if (payload.code === 'ineligible_for_approval') {
    return hasExactKeys(payload, ['code', 'reason', 'message'])
      && typeof payload.reason === 'string'
      && (INELIGIBILITY_REASONS as readonly string[]).includes(payload.reason)
      && typeof payload.message === 'string'
      ? { code: 'ineligible_for_approval', reason: payload.reason as TestRunIneligibilityReason, message: payload.message }
      : null;
  }
  if (payload.code === 'invalid_verdict') {
    return hasExactKeys(payload, ['code', 'errors'])
      && Array.isArray(payload.errors)
      && payload.errors.length > 0
      && payload.errors.every(isDraftFieldError)
      ? { code: 'invalid_verdict', errors: payload.errors }
      : null;
  }
  return null;
}

/**
 * Records an admin's verdict on one stored run (candidate or published baseline, C9).
 * The body is exactly `{ verdict, notes }` with `notes` always present, null allowed:
 * the server's body is exact-key (`extra="forbid"`). The 200 is the run's evidence
 * with the verdict fields set, so the caller needs no separate run read (C26).
 *
 * Refusals: the exact 404, a typed 403, the `ineligible_for_approval` and
 * `invalid_verdict` 422s are `TestRunVerdictApiError`; a malformed 200 or 422 is
 * `InvalidTestRunResponseError`; anything else (a 500 from a linked-verdict trigger,
 * C7) is a plain `AgentDefinitionApiError`.
 */
export async function recordTestRunVerdict(
  runId: number,
  request: TestRunVerdictRequest,
): Promise<TestRunEvidence> {
  // Exactly the joined keys, in order; `?? null` keeps `notes` present when a caller omits it.
  const values = { verdict: request.verdict, notes: request.notes ?? null };
  const body = Object.fromEntries(VERDICT_REQUEST_KEYS.map((key) => [key, values[key]]));
  const { status, payload, statusText } = await agentTestRequest(`/test-runs/${runId}/verdict`, 'POST', body);
  if (status === 200) {
    const evidence = parseTestRunEvidence(payload);
    if (evidence === null || evidence.run_id !== runId || evidence.verdict !== request.verdict) {
      throw new InvalidTestRunResponseError();
    }
    return evidence;
  }
  const failure = parseTestRunVerdictFailure(status, payload);
  if (failure !== null) throw new TestRunVerdictApiError(status, failure);
  if (status === 422) throw new InvalidTestRunResponseError();
  throw new AgentDefinitionApiError(status, payload, statusText);
}

/** A case's readiness code on the wire; the client owns the display labels (C17). */
export type ReadinessStatus = 'needs_test' | 'test_failed' | 'awaiting_review' | 'approved';

/** One active required case row of a role (C11). `blocking` is changed-and-not-approved. */
export interface TestCaseReadiness {
  agent_key: AgentKey;
  test_case_id: number;
  test_case_name: string;
  test_case_version: number;
  status: ReadinessStatus;
  blocking: boolean;
  /** The newest eligible approval when `approved`, else the newest candidate run. */
  run_id: number | null;
  run_verdict: TestRunVerdict | null;
  run_checks_passed: boolean | null;
}

/** One editable role: its saved candidate hash and its active required cases. */
export interface AgentReadiness {
  agent_key: AgentKey;
  candidate_hash: string;
  is_changed_from_base: boolean;
  ready: boolean;
  /** A changed role with zero active required cases (#269 `no_required_case`). */
  missing_required_case: boolean;
  cases: TestCaseReadiness[];
}

/**
 * `GET /readiness`: the draft's publication readiness at `draft_lock_version`.
 * Informational only: #269's publication gate performs its own locked read.
 */
export interface DraftReadiness {
  draft_lock_version: number;
  base_release_id: number;
  all_ready: boolean;
  blocking_agents: AgentKey[];
  agents: AgentReadiness[];
}

const READINESS_URL = `${AGENT_DEFINITIONS_URL}/readiness`;

/** A readiness 200 whose body does not match the exact contract (#269 may catch it). */
export class InvalidReadinessResponseError extends Error {
  constructor() {
    super('Draft readiness response did not match the expected contract.');
    this.name = 'InvalidReadinessResponseError';
  }
}

const READINESS_STATUSES: readonly ReadinessStatus[] = [
  'needs_test', 'test_failed', 'awaiting_review', 'approved',
];

const DRAFT_READINESS_KEYS = [
  'draft_lock_version', 'base_release_id', 'all_ready', 'blocking_agents', 'agents',
] as const;

const AGENT_READINESS_KEYS = [
  'agent_key', 'candidate_hash', 'is_changed_from_base', 'ready', 'missing_required_case', 'cases',
] as const;

const TEST_CASE_READINESS_KEYS = [
  'agent_key', 'test_case_id', 'test_case_name', 'test_case_version', 'status', 'blocking',
  'run_id', 'run_verdict', 'run_checks_passed',
] as const;

function isTestCaseReadiness(value: unknown, agentKey: AgentKey): value is TestCaseReadiness {
  return isPlainRecord(value)
    && hasExactKeys(value, TEST_CASE_READINESS_KEYS)
    && value.agent_key === agentKey
    && isPositiveInteger(value.test_case_id)
    && typeof value.test_case_name === 'string'
    && isPositiveInteger(value.test_case_version)
    && typeof value.status === 'string'
    && (READINESS_STATUSES as readonly string[]).includes(value.status)
    && typeof value.blocking === 'boolean'
    && (value.run_id === null || isPositiveInteger(value.run_id))
    && (value.run_verdict === null
      || (typeof value.run_verdict === 'string' && (TEST_RUN_VERDICTS as readonly string[]).includes(value.run_verdict)))
    && isNullableBoolean(value.run_checks_passed);
}

function isAgentReadiness(value: unknown): value is AgentReadiness {
  return isPlainRecord(value)
    && hasExactKeys(value, AGENT_READINESS_KEYS)
    && isAgentKey(value.agent_key)
    && typeof value.candidate_hash === 'string' && LOWERCASE_SHA256.test(value.candidate_hash)
    && typeof value.is_changed_from_base === 'boolean'
    && typeof value.ready === 'boolean'
    && typeof value.missing_required_case === 'boolean'
    && Array.isArray(value.cases)
    && value.cases.every((item) => isTestCaseReadiness(item, value.agent_key as AgentKey));
}

/**
 * The strict readiness parser: exact snake_case keys at every level, the four status
 * codes (never labels), each case inside its own role, and each role at most once.
 */
export function parseDraftReadinessResponse(value: unknown): DraftReadiness | null {
  if (!isPlainRecord(value) || !hasExactKeys(value, DRAFT_READINESS_KEYS)) return null;
  const valid = isNonnegativeInteger(value.draft_lock_version)
    && isPositiveInteger(value.base_release_id)
    && typeof value.all_ready === 'boolean'
    && Array.isArray(value.blocking_agents)
    && value.blocking_agents.every(isAgentKey)
    && Array.isArray(value.agents)
    && value.agents.every(isAgentReadiness)
    && new Set(value.agents.map((agent: AgentReadiness) => agent.agent_key)).size === value.agents.length;
  return valid ? value as unknown as DraftReadiness : null;
}

/** Reads the draft's readiness. A malformed 200 is invalid; any other status is an API error. */
export async function getDraftReadiness(): Promise<DraftReadiness> {
  const response = await fetch(READINESS_URL, { method: 'GET', headers: { Accept: 'application/json' } });
  const payload: unknown = await response.json().catch(() => null);
  if (response.status === 200) {
    const readiness = parseDraftReadinessResponse(payload);
    if (readiness === null) throw new InvalidReadinessResponseError();
    return readiness;
  }
  throw new AgentDefinitionApiError(response.status, payload, response.statusText);
}

// ============================================================
// #269: Graph Release preview and publication (Task 6)
// ============================================================
// The wire is `src/api/schemas/graph_releases.py` (Task 5). Every parser below is
// exact-key at every level, and `tests/unit/test_graph_release_client_join.py` pins the
// key lists, the diff-field order, the gap codes and the note cap to the server. The
// embedded readiness is #268's `DraftReadiness`, parsed by `parseDraftReadinessResponse`;
// there is no second readiness type. Readiness is informational (C32): the page shows
// it, but only the server's `publishable` and the publication gate decide.

/** `graph_configuration_publication.RELEASE_NOTE_MAX_LENGTH`, in Python code points (C10). */
export const RELEASE_NOTE_MAX_LENGTH = 2000;

/** The field-diff vocabulary, in the server's order (`DIFF_FIELD_NAMES`). */
export const RELEASE_DIFF_FIELDS = [
  'definition_version',
  'prompt_text',
  'model.endpoint_name',
  'model.temperature',
  'model.max_tokens',
  'model.top_p',
  'schema_overlay',
  'assembly_rules',
  'protected_assembly.version',
  'protected_assembly.digest',
  'schema_contract.version',
  'schema_contract.digest',
] as const;

export type ReleaseDiffField = typeof RELEASE_DIFF_FIELDS[number];

/** One differing field; `schema_overlay` and `assembly_rules` are whole JSON documents. */
export interface ReleaseFieldDiff {
  field: ReleaseDiffField;
  published: JsonValue;
  candidate: JsonValue;
}

/** One role whose saved candidate differs from the active release. */
export interface ChangedDefinitionPreview {
  agent_key: AgentKey;
  published_revision_id: number;
  published_content_hash: string;
  candidate_hash: string;
  field_diffs: ReleaseFieldDiff[];
}

/**
 * `GET /release-preview` (200): what publishing the shared draft now would change. It
 * writes nothing. `publishable` is the server's one definition (C22) and is advisory:
 * the publication gate decides.
 */
export interface ReleasePreviewResponse {
  draft: DraftMetadata;
  active_release: ActiveRelease;
  next_version_number: number;
  changed: ChangedDefinitionPreview[];
  readiness: DraftReadiness;
  validation_issues: DraftFieldError[];
  publishable: boolean;
}

/** `POST /releases`: exactly `{ lock_version, release_note }`. The actor is the principal. */
export interface PublishReleaseRequest {
  lock_version: number;
  release_note: string;
}

export interface PublishedMapping {
  agent_definition_revision_id: number;
  content_hash: string;
  reused: boolean;
}

export interface ReleaseEvidence {
  agent_test_run_id: number;
  agent_key: AgentKey;
  test_case_id: number;
  evidence_kind: 'approval';
}

/** `POST /releases` (200, ruling Q6): the new active release and the rebased draft. */
export interface PublishReleaseSuccessResponse {
  release: ActiveRelease;
  previous_release_id: number;
  changed_agents: AgentKey[];
  /** Exactly the seven roles, in Graph order. */
  mappings: Record<AgentKey, PublishedMapping>;
  evidence: ReleaseEvidence[];
  draft: DraftMetadata;
}

export interface ReleaseIdentity {
  release_id: number;
  version_number: number;
}

/** 409: the draft moved on after the preview was read; nothing was written. */
export interface StalePublicationResponse {
  code: 'stale_publication';
  expected_lock_version: number;
  current_lock_version: number;
  active_release: ReleaseIdentity;
  draft: DraftMetadata;
}

/** 409: the draft matches the active release. */
export interface NothingToPublishResponse {
  code: 'nothing_to_publish';
  active_release: ReleaseIdentity;
  draft: DraftMetadata;
}

/** A gap code has no server message: the client labels it (C1). */
export type PublicationGapCode = 'no_required_case' | 'no_eligible_approval';

/** `test_case_id` is `null` exactly for a `no_required_case` gap. */
export interface PublicationGap {
  agent_key: AgentKey;
  test_case_id: number | null;
  code: PublicationGapCode;
}

/** 409: the gate's locked gaps (authoritative) and #268's informational readiness (C32). */
export interface PublicationNotReadyResponse {
  code: 'publication_not_ready';
  gaps: PublicationGap[];
  readiness: DraftReadiness;
}

/** 422: key on each issue's `code`; Pydantic messages can name Python classes. */
export interface PublicationValidationErrorResponse {
  code: 'invalid_publication';
  errors: DraftFieldError[];
}

export type PublishReleaseFailure =
  | StalePublicationResponse
  | NothingToPublishResponse
  | PublicationNotReadyResponse
  | PublicationValidationErrorResponse;

/** A release 200, 409 or 422 whose body does not match the exact contract. */
export class InvalidReleaseResponseError extends Error {
  constructor() {
    super('Graph Release response did not match the expected contract.');
    this.name = 'InvalidReleaseResponseError';
  }
}

const RELEASE_PREVIEW_URL = `${AGENT_DEFINITIONS_URL}/release-preview`;
const RELEASES_URL = `${AGENT_DEFINITIONS_URL}/releases`;

const ACTIVE_RELEASE_KEYS = [
  'release_id', 'version_number', 'previous_release_id', 'restored_from_release_id',
  'release_note', 'published_by', 'published_at', 'effective_from', 'effective_to',
] as const;

const RELEASE_PREVIEW_KEYS = [
  'draft', 'active_release', 'next_version_number', 'changed', 'readiness',
  'validation_issues', 'publishable',
] as const;

const CHANGED_DEFINITION_KEYS = [
  'agent_key', 'published_revision_id', 'published_content_hash', 'candidate_hash', 'field_diffs',
] as const;

const FIELD_DIFF_KEYS = ['field', 'published', 'candidate'] as const;

const PUBLISH_RELEASE_REQUEST_KEYS = ['lock_version', 'release_note'] as const;

const PUBLISH_RELEASE_SUCCESS_KEYS = [
  'release', 'previous_release_id', 'changed_agents', 'mappings', 'evidence', 'draft',
] as const;

const PUBLISHED_MAPPING_KEYS = ['agent_definition_revision_id', 'content_hash', 'reused'] as const;

const RELEASE_EVIDENCE_KEYS = ['agent_test_run_id', 'agent_key', 'test_case_id', 'evidence_kind'] as const;

const RELEASE_IDENTITY_KEYS = ['release_id', 'version_number'] as const;

const STALE_PUBLICATION_KEYS = [
  'code', 'expected_lock_version', 'current_lock_version', 'active_release', 'draft',
] as const;

const NOTHING_TO_PUBLISH_KEYS = ['code', 'active_release', 'draft'] as const;

const PUBLICATION_NOT_READY_KEYS = ['code', 'gaps', 'readiness'] as const;

const PUBLICATION_GAP_KEYS = ['agent_key', 'test_case_id', 'code'] as const;

const PUBLICATION_VALIDATION_KEYS = ['code', 'errors'] as const;

const PUBLICATION_GAP_CODES: readonly PublicationGapCode[] = ['no_required_case', 'no_eligible_approval'];

function isSha256(value: unknown): value is string {
  return typeof value === 'string' && LOWERCASE_SHA256.test(value);
}

function isNullablePositiveInteger(value: unknown): value is number | null {
  return value === null || isPositiveInteger(value);
}

function isActiveRelease(value: unknown): value is ActiveRelease {
  return isPlainRecord(value)
    && hasExactKeys(value, ACTIVE_RELEASE_KEYS)
    && isPositiveInteger(value.release_id)
    && isPositiveInteger(value.version_number)
    && isNullablePositiveInteger(value.previous_release_id)
    && isNullablePositiveInteger(value.restored_from_release_id)
    && typeof value.release_note === 'string'
    && typeof value.published_by === 'string'
    && typeof value.published_at === 'string'
    && typeof value.effective_from === 'string'
    && (value.effective_to === null || typeof value.effective_to === 'string');
}

function isReleaseIdentity(value: unknown): value is ReleaseIdentity {
  return isPlainRecord(value)
    && hasExactKeys(value, RELEASE_IDENTITY_KEYS)
    && isPositiveInteger(value.release_id)
    && isPositiveInteger(value.version_number);
}

/** Each field at most once and in the server's vocabulary order; at least one. */
function isFieldDiffList(value: unknown): value is ReleaseFieldDiff[] {
  if (!Array.isArray(value) || value.length === 0) return false;
  let previous = -1;
  for (const item of value) {
    if (!isPlainRecord(item) || !hasExactKeys(item, FIELD_DIFF_KEYS)) return false;
    const index = (RELEASE_DIFF_FIELDS as readonly unknown[]).indexOf(item.field);
    if (index <= previous || !isJsonValue(item.published) || !isJsonValue(item.candidate)) return false;
    previous = index;
  }
  return true;
}

function isChangedDefinition(value: unknown): value is ChangedDefinitionPreview {
  return isPlainRecord(value)
    && hasExactKeys(value, CHANGED_DEFINITION_KEYS)
    && isAgentKey(value.agent_key)
    && isPositiveInteger(value.published_revision_id)
    && isSha256(value.published_content_hash)
    && isSha256(value.candidate_hash)
    && isFieldDiffList(value.field_diffs);
}

/** Changed roles: each at most once, in Graph order (`GRAPH_V1_AGENT_KEYS`). */
function isChangedDefinitionList(value: unknown): value is ChangedDefinitionPreview[] {
  if (!Array.isArray(value)) return false;
  let previous = -1;
  for (const item of value) {
    if (!isChangedDefinition(item)) return false;
    const index = AGENT_KEYS.indexOf(item.agent_key);
    if (index <= previous) return false;
    previous = index;
  }
  return true;
}

/** The strict preview parser: exact keys at every level; readiness via #268's parser. */
export function parseReleasePreviewResponse(value: unknown): ReleasePreviewResponse | null {
  if (!isPlainRecord(value) || !hasExactKeys(value, RELEASE_PREVIEW_KEYS)) return null;
  const valid = isDraftMetadata(value.draft)
    && isActiveRelease(value.active_release)
    && isInteger(value.next_version_number) && value.next_version_number >= 2
    && isChangedDefinitionList(value.changed)
    && parseDraftReadinessResponse(value.readiness) !== null
    && Array.isArray(value.validation_issues)
    && value.validation_issues.every(isDraftFieldError)
    && typeof value.publishable === 'boolean';
  return valid ? value as unknown as ReleasePreviewResponse : null;
}

function isPublishedMapping(value: unknown): value is PublishedMapping {
  return isPlainRecord(value)
    && hasExactKeys(value, PUBLISHED_MAPPING_KEYS)
    && isPositiveInteger(value.agent_definition_revision_id)
    && isSha256(value.content_hash)
    && typeof value.reused === 'boolean';
}

function isReleaseEvidence(value: unknown): value is ReleaseEvidence {
  return isPlainRecord(value)
    && hasExactKeys(value, RELEASE_EVIDENCE_KEYS)
    && isPositiveInteger(value.agent_test_run_id)
    && isAgentKey(value.agent_key)
    && isPositiveInteger(value.test_case_id)
    && value.evidence_kind === 'approval';
}

/** Exactly the seven roles, in Graph order, as the server's validator requires. */
function isSevenMappings(value: unknown): value is Record<AgentKey, PublishedMapping> {
  if (!isPlainRecord(value)) return false;
  const keys = Object.keys(value);
  return keys.length === AGENT_KEYS.length
    && AGENT_KEYS.every((key, index) => keys[index] === key)
    && Object.values(value).every(isPublishedMapping);
}

/** The strict publish 200 parser. */
export function parsePublishReleaseSuccessResponse(value: unknown): PublishReleaseSuccessResponse | null {
  if (!isPlainRecord(value) || !hasExactKeys(value, PUBLISH_RELEASE_SUCCESS_KEYS)) return null;
  const valid = isActiveRelease(value.release)
    && isPositiveInteger(value.previous_release_id)
    && Array.isArray(value.changed_agents)
    && value.changed_agents.length > 0
    && value.changed_agents.every(isAgentKey)
    && isSevenMappings(value.mappings)
    && Array.isArray(value.evidence)
    && value.evidence.every(isReleaseEvidence)
    && isDraftMetadata(value.draft);
  return valid ? value as unknown as PublishReleaseSuccessResponse : null;
}

function isPublicationGap(value: unknown): value is PublicationGap {
  return isPlainRecord(value)
    && hasExactKeys(value, PUBLICATION_GAP_KEYS)
    && isAgentKey(value.agent_key)
    && isNullablePositiveInteger(value.test_case_id)
    && typeof value.code === 'string'
    && (PUBLICATION_GAP_CODES as readonly string[]).includes(value.code)
    // `null` exactly for `no_required_case` (the server's gap validator, C1).
    && (value.code === 'no_required_case') === (value.test_case_id === null);
}

/**
 * The strict refusal parser for the publish route: a 409 is exactly one of the three
 * typed conflicts, a 422 exactly `invalid_publication`. It keys on `code` only.
 */
export function parsePublishReleaseFailure(status: number, value: unknown): PublishReleaseFailure | null {
  if (!isPlainRecord(value)) return null;
  if (status === 422) {
    return value.code === 'invalid_publication'
      && hasExactKeys(value, PUBLICATION_VALIDATION_KEYS)
      && Array.isArray(value.errors)
      && value.errors.length > 0
      && value.errors.every(isDraftFieldError)
      ? value as unknown as PublicationValidationErrorResponse
      : null;
  }
  if (status !== 409) return null;
  switch (value.code) {
    case 'stale_publication':
      return hasExactKeys(value, STALE_PUBLICATION_KEYS)
        && isInteger(value.expected_lock_version)
        && isNonnegativeInteger(value.current_lock_version)
        && isReleaseIdentity(value.active_release)
        && isDraftMetadata(value.draft)
        ? value as unknown as StalePublicationResponse
        : null;
    case 'nothing_to_publish':
      return hasExactKeys(value, NOTHING_TO_PUBLISH_KEYS)
        && isReleaseIdentity(value.active_release)
        && isDraftMetadata(value.draft)
        ? value as unknown as NothingToPublishResponse
        : null;
    case 'publication_not_ready':
      return hasExactKeys(value, PUBLICATION_NOT_READY_KEYS)
        && Array.isArray(value.gaps)
        && value.gaps.length > 0
        && value.gaps.every(isPublicationGap)
        && parseDraftReadinessResponse(value.readiness) !== null
        ? value as unknown as PublicationNotReadyResponse
        : null;
    default:
      return null;
  }
}

let releasePreviewRequest: Promise<ReleasePreviewResponse> | null = null;

/**
 * Reads the release preview. As with the workbench aggregate, one in-flight read is
 * shared, so React StrictMode's development remount does not read the prompts twice.
 * A malformed 200 is `InvalidReleaseResponseError`; any other status is an API error.
 */
export function getReleasePreview(): Promise<ReleasePreviewResponse> {
  if (releasePreviewRequest) return releasePreviewRequest;
  releasePreviewRequest = (async () => {
    const response = await fetch(RELEASE_PREVIEW_URL, { method: 'GET', headers: { Accept: 'application/json' } });
    const payload: unknown = await response.json().catch(() => null);
    if (response.status === 200) {
      const preview = parseReleasePreviewResponse(payload);
      if (preview === null) throw new InvalidReleaseResponseError();
      return preview;
    }
    throw new AgentDefinitionApiError(response.status, payload, response.statusText);
  })().finally(() => {
    releasePreviewRequest = null;
  });
  return releasePreviewRequest;
}

/**
 * Publishes the shared draft as the next Graph Version. The body is exactly
 * `{ lock_version, release_note }` (the server forbids any other key, `actor` included).
 *
 * The 200 is strictly parsed. A 409 or 422 throws `AgentDefinitionApiError` whose
 * `payload` is the strictly parsed `PublishReleaseFailure`; a malformed 200/409/422 is
 * `InvalidReleaseResponseError`; any other status (403, 500) is a plain
 * `AgentDefinitionApiError`. Nothing here retries.
 */
export async function publishRelease(request: PublishReleaseRequest): Promise<PublishReleaseSuccessResponse> {
  const values: PublishReleaseRequest = { lock_version: request.lock_version, release_note: request.release_note };
  const body = Object.fromEntries(PUBLISH_RELEASE_REQUEST_KEYS.map((key) => [key, values[key]]));
  const response = await fetch(RELEASES_URL, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  const payload: unknown = await response.json().catch(() => null);
  if (response.status === 200) {
    const published = parsePublishReleaseSuccessResponse(payload);
    if (published === null) throw new InvalidReleaseResponseError();
    return published;
  }
  if (response.status === 409 || response.status === 422) {
    const failure = parsePublishReleaseFailure(response.status, payload);
    if (failure === null) throw new InvalidReleaseResponseError();
    throw new AgentDefinitionApiError(response.status, failure, response.statusText);
  }
  throw new AgentDefinitionApiError(response.status, payload, response.statusText);
}
