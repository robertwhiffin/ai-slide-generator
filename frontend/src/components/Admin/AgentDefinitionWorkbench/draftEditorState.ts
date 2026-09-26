import {
  AGENT_KEYS,
  AgentDefinitionApiError,
  AgentTestApiError,
  CUSTOM_ANCHORS,
  InvalidDraftSaveResponseError,
  InvalidTestRunResponseError,
  TEST_RUN_UNAVAILABLE,
  parseDraftValidationErrorResponse,
  type AgentDefinitionWorkbenchResponse,
  type AgentKey,
  type AssemblyCondition,
  type AssemblyRulesV2,
  type CustomAnchor,
  type CustomTextBlock,
  type DraftDefinition,
  type DraftFieldError,
  type DraftMetadata,
  type DraftSaveConflictResponse,
  type DraftSaveSuccessResponse,
  type DraftValidationErrorResponse,
  type EditableModelDraft,
  type EditableSchemaOverlay,
  type LegacyPromptSourceResponse,
  type StructuredOutputProbeFailureResponse,
  type StructuredOutputProbeIdentity,
  type StructuredOutputProbeSuccessResponse,
  type TestCaseListEntry,
  type TestRunEvidence,
} from '../../../api/agentDefinitions';

export type DraftStatus = 'Clean' | 'Unsaved' | 'Needs test';
export type DraftNumberInput = number | '';
export type EditableDraftField =
  | 'prompt_text'
  | 'endpoint_name'
  | 'temperature'
  | 'max_tokens'
  | 'top_p';

/** The local error key for one field override's examples textarea. */
export type OverlayExamplesErrorKey = `schema_overlay.field_overrides.${string}.examples`;

/** Every key a local or server field error may be attached to. */
export type DraftFieldErrorKey = EditableDraftField | OverlayExamplesErrorKey;

export const OVERLAY_EXAMPLES_ERROR = 'Examples must be a JSON array.';

export function overlayExamplesErrorKey(fieldName: string): OverlayExamplesErrorKey {
  return `schema_overlay.field_overrides.${fieldName}.examples`;
}

/**
 * The local error for one examples textarea, or `null` when it may be sent. Blank means
 * "no examples" and is allowed; anything else must parse as a JSON array. Malformed text
 * is refused here rather than dropped from the candidate, so a Save can never silently
 * replace saved examples with none (#264 Task 6 review, I3).
 */
export function overlayExamplesError(examples: string): string | null {
  if (!examples.trim()) return null;
  try {
    return Array.isArray(JSON.parse(examples)) ? null : OVERLAY_EXAMPLES_ERROR;
  } catch {
    return OVERLAY_EXAMPLES_ERROR;
  }
}

/**
 * Local editable guidance for one canonical or optional output field.
 * Only `description` and `examples` are accepted by the domain validator;
 * other properties are stripped in `overlayFromForm` before sending.
 */
export interface EditableFieldGuidanceForm {
  description: string;
  /** JSON-serialized array string, e.g. `'["example"]'`. Empty string = not set. */
  examples: string;
}

/**
 * Local schema overlay edits. `null` means no explicit edits have been made since
 * the form was last initialized from the saved definition. `candidateFromForm`
 * omits `schema_overlay` from the wire candidate when this is `null`, keeping the
 * historic five-field save body byte-identical when no overlay edits are pending.
 */
export interface EditableSchemaOverlayForm {
  additional_optional_fields: string[];
  /** Keyed by field name. Only set for fields the user has explicitly edited. */
  field_overrides: Record<string, EditableFieldGuidanceForm>;
}

/** The two roles whose Graph Version 1 prompt is a protected legacy composite. */
export const LEGACY_COMPOSITE_ROLES: readonly AgentKey[] = ['data_analyst', 'build_reviewer'];

export interface EditableModelDraftForm {
  prompt_text: string;
  endpoint_name: string;
  temperature: DraftNumberInput;
  max_tokens: DraftNumberInput;
  top_p: DraftNumberInput;
  /** Local v2 custom blocks, or `null` while the role is still on v1. */
  assembly_rules: AssemblyRulesV2 | null;
  /**
   * Local schema overlay edits, or `null`/`undefined` while no overlay changes have
   * been made. Absent or null causes `candidateFromForm` to omit `schema_overlay` from
   * the save body entirely, preserving the server's stored overlay unchanged.
   */
  schema_overlay?: EditableSchemaOverlayForm | null;
}

export type RetainedFormSource =
  | 'reload_server'
  | 'dirty_legacy_prompt'
  | 'pending_prompt_quarantine'
  | 'version_adoption'
  | 'legacy_source_recovery';

/**
 * One displaced alternative, addressed by a stable deterministic reducer ID.
 *
 * `form` is savable and has already been sanitized against `sanitizedFormatVersion`.
 * `manualOnlyPrompt` holds the exact displaced prompt bytes and is never read by
 * candidate construction, never auto-stripped, and never auto-reapplied.
 */
export interface RetainedDraftForm {
  id: string;
  source: RetainedFormSource;
  reason: string;
  form: EditableModelDraftForm;
  manualOnlyPrompt: string;
  sanitizedFormatVersion: 1 | 2;
}

/**
 * The last explicit structured-output probe of this role's saved candidate (#266),
 * carrying the exact identity the server reported. It is informational only: it never
 * changes the lock, the saved entry, the form or the draft status.
 */
export type DraftProbeResult = StructuredOutputProbeIdentity & (
  | { outcome: 'succeeded' }
  | {
    outcome: 'failed';
    code: StructuredOutputProbeFailureResponse['code'];
    message: string;
    retryable: boolean;
  }
);

/**
 * One role's Agent Test Case panel state (#267). The case list is a read, never a
 * draft operation, so loading it takes no gate; its request ID comes from the one
 * counter and only drops out-of-order answers. Runs and case writes are operations on
 * the one gate (see `TestOperationKind`). Evidence is kept per role, and the panel shows
 * it only for the case it names.
 */
export interface AgentTestingState {
  casesStatus: 'idle' | 'loading' | 'ready' | 'error';
  cases: TestCaseListEntry[];
  /** The case-list read whose answer may still land, or `null`. */
  casesRequestId: number | null;
  /** The last candidate run of this role's saved draft in this session. */
  candidateEvidence: TestRunEvidence | null;
  /** The last published-baseline rerun of this role in this session. */
  baselineEvidence: TestRunEvidence | null;
  /** The contained message of the last failed test operation or case read. */
  error: string | null;
  /** The exact ordered server issues of the last refused test operation. */
  issues: DraftFieldError[];
  /** An informational outcome that is not an error, such as an edit that changed nothing. */
  notice: string | null;
}

export function emptyAgentTestingState(): AgentTestingState {
  return {
    casesStatus: 'idle',
    cases: [],
    casesRequestId: null,
    candidateEvidence: null,
    baselineEvidence: null,
    error: null,
    issues: [],
    notice: null,
  };
}

export interface DraftEditorEntry {
  publishedHash: string;
  saved: DraftDefinition;
  local: EditableModelDraftForm;
  fieldErrors: Partial<Record<DraftFieldErrorKey, string>>;
  conflict: DraftSaveConflictResponse | null;
  /** Ordered, append-only until an explicit discard. */
  retainedForms: RetainedDraftForm[];
  nextRetainedOrdinal: number;
  /** Exact ordered server issues that have no inline field owner. */
  responseIssues: DraftFieldError[];
  requestError: string | null;
  /** The last probe result for the saved candidate still on screen, or `null`. */
  probeResult: DraftProbeResult | null;
  /** The role's Agent Test Case panel (#267). */
  testing: AgentTestingState;
}

/**
 * #267's operations. Every one joins the one gate: a candidate run reads the saved draft
 * under the lock exactly as the probe does, and a baseline rerun and a case write are
 * the panel's other writes, so none needs a second in-flight flag.
 */
export type TestOperationKind = 'testRun' | 'baselineRun' | 'testCaseCreate' | 'testCaseRetire' | 'testCaseUpdate';

export const TEST_OPERATIONS: readonly TestOperationKind[] = [
  'testRun', 'baselineRun', 'testCaseCreate', 'testCaseRetire', 'testCaseUpdate',
];

export type DraftOperationKind =
  | 'save'
  | 'upgrade'
  | 'sourceRecovery'
  | 'schemaUpgrade'
  | 'probe'
  | TestOperationKind;

/**
 * The one aggregate pending slot, now discriminated by operation. Save, Upgrade,
 * SourceRecovery, SchemaUpgrade and the #266 structured-output Probe share this single
 * gate; there is no second gate.
 */
export interface PendingDraftSave {
  operation: DraftOperationKind;
  requestId: number;
  agentKey: AgentKey;
  expectedLockVersion: number;
  submittedCandidate: EditableModelDraft | null;
  /** The case a test run or case retire names; absent for every draft operation. */
  testCaseId?: number;
}

export interface DraftEditorState {
  draft: DraftMetadata;
  byAgent: Record<AgentKey, DraftEditorEntry>;
  pendingSave: PendingDraftSave | null;
}

export type DraftEditorAction =
  | { type: 'edit'; agentKey: AgentKey; field: EditableDraftField; value: string | number }
  | { type: 'assemblyBlockAdded'; agentKey: AgentKey; blockId: string; anchor: CustomAnchor }
  | { type: 'assemblyBlockTextChanged'; agentKey: AgentKey; blockId: string; text: string }
  | {
    type: 'assemblyBlockConditionChanged';
    agentKey: AgentKey;
    blockId: string;
    condition: AssemblyCondition;
  }
  | { type: 'assemblyBlockDeleted'; agentKey: AgentKey; blockId: string }
  | { type: 'assemblyBlockMoved'; agentKey: AgentKey; blockId: string; direction: 'up' | 'down' }
  | { type: 'saveStarted'; pending: PendingDraftSave }
  | { type: 'saveSucceeded'; requestId: number; result: DraftSaveSuccessResponse }
  | { type: 'saveInvalid'; agentKey: AgentKey; errors: Partial<Record<DraftFieldErrorKey, string>> }
  | { type: 'saveRejected'; requestId: number; error: DraftValidationErrorResponse }
  | { type: 'saveConflicted'; requestId: number; conflict: DraftSaveConflictResponse }
  | { type: 'saveFailed'; requestId: number; message: string }
  | { type: 'dirtyLegacyPromptRetained'; agentKey: AgentKey }
  | { type: 'upgradeStarted'; pending: PendingDraftSave }
  | { type: 'upgradeSucceeded'; requestId: number; result: DraftSaveSuccessResponse }
  | { type: 'upgradeRejected'; requestId: number; error: DraftValidationErrorResponse }
  | { type: 'upgradeConflicted'; requestId: number; conflict: DraftSaveConflictResponse }
  | { type: 'upgradeFailed'; requestId: number; message: string }
  | { type: 'sourceRecoveryStarted'; pending: PendingDraftSave }
  | { type: 'sourceRecoverySucceeded'; requestId: number; result: LegacyPromptSourceResponse }
  | { type: 'sourceRecoveryRejected'; requestId: number; error: DraftValidationErrorResponse }
  | { type: 'sourceRecoveryConflicted'; requestId: number; conflict: DraftSaveConflictResponse }
  | { type: 'sourceRecoveryFailed'; requestId: number; message: string }
  | { type: 'schemaUpgradeStarted'; pending: PendingDraftSave }
  | { type: 'schemaUpgradeSucceeded'; requestId: number; result: DraftSaveSuccessResponse }
  | { type: 'schemaUpgradeRejected'; requestId: number; error: DraftValidationErrorResponse }
  | { type: 'schemaUpgradeConflicted'; requestId: number; conflict: DraftSaveConflictResponse }
  | { type: 'schemaUpgradeFailed'; requestId: number; message: string }
  | { type: 'probeStarted'; pending: PendingDraftSave }
  | { type: 'probeSucceeded'; requestId: number; result: StructuredOutputProbeSuccessResponse }
  | { type: 'probeUnsuccessful'; requestId: number; failure: StructuredOutputProbeFailureResponse }
  | { type: 'probeRejected'; requestId: number; error: DraftValidationErrorResponse }
  | { type: 'probeConflicted'; requestId: number; conflict: DraftSaveConflictResponse }
  | { type: 'probeFailed'; requestId: number; message: string }
  | { type: 'testCasesLoadStarted'; agentKey: AgentKey; requestId: number }
  | { type: 'testCasesLoaded'; agentKey: AgentKey; requestId: number; items: TestCaseListEntry[] }
  | { type: 'testCasesLoadFailed'; agentKey: AgentKey; requestId: number; message: string }
  | { type: 'testOperationStarted'; pending: PendingDraftSave }
  | { type: 'testRunSucceeded'; requestId: number; evidence: TestRunEvidence }
  | { type: 'testRunRejected'; requestId: number; error: DraftValidationErrorResponse }
  | { type: 'testRunConflicted'; requestId: number; conflict: DraftSaveConflictResponse }
  | { type: 'testCaseCreated'; requestId: number; testCase: TestCaseListEntry }
  | { type: 'testCaseRetired'; requestId: number; testCase: TestCaseListEntry }
  | { type: 'testCaseUpdated'; requestId: number; testCase: TestCaseListEntry }
  | { type: 'testOperationFailed'; requestId: number; message: string; issues: DraftFieldError[] }
  | { type: 'schemaOverlayOptionalFieldToggled'; agentKey: AgentKey; fieldName: string }
  | { type: 'schemaOverlayFieldDescriptionChanged'; agentKey: AgentKey; fieldName: string; description: string }
  | { type: 'schemaOverlayFieldExamplesChanged'; agentKey: AgentKey; fieldName: string; examples: string }
  | { type: 'reloadServer'; agentKey: AgentKey }
  | { type: 'keepLocal'; agentKey: AgentKey }
  | { type: 'restoreSavedPrompt'; agentKey: AgentKey }
  | { type: 'restoreRetained'; agentKey: AgentKey; retainedId: string }
  | { type: 'discardRetained'; agentKey: AgentKey; retainedId: string };

const INVALID_RESPONSE_MESSAGE = 'Unable to save draft because the server response was invalid.';
const PROBE_INVALID_RESPONSE_MESSAGE =
  'Unable to test structured output because the server response was invalid.';

export const RETAINED_REASONS = {
  reload_server: 'Replaced by the server draft values.',
  dirty_legacy_prompt:
    'Upgrade needs the exact Graph Version 1 prompt. This edited prompt was retained for '
    + 'manual reapplication.',
  pending_prompt_quarantine:
    'Prompt edits are not accepted while this Upgrade is in flight. The proposed prompt was '
    + 'retained for manual reapplication.',
  version_adoption:
    'The server moved this role to Graph Version 2. The displaced Graph Version 1 prompt was '
    + 'retained for manual reapplication.',
  legacy_source_recovery_saved:
    'The edited saved Graph Version 1 prompt was retained before the published source was '
    + 'installed.',
  legacy_source_recovery_local:
    'The edited local Graph Version 1 prompt was retained before the published source was '
    + 'installed.',
} as const;

const INLINE_FIELD_OWNERS: Record<string, EditableDraftField> = {
  'candidate.prompt_text': 'prompt_text',
  'candidate.model.endpoint_name': 'endpoint_name',
  'candidate.model.temperature': 'temperature',
  'candidate.model.max_tokens': 'max_tokens',
  'candidate.model.top_p': 'top_p',
};

export function isLegacyCompositeRole(agentKey: AgentKey): boolean {
  return LEGACY_COMPOSITE_ROLES.includes(agentKey);
}

export function definitionFormatVersion(definition: DraftDefinition): 1 | 2 {
  return definition.assembly_rules.format_version;
}

/** Local editable rules exist only for a v2 definition; v1 has no editable rules. */
export function localRulesFor(definition: DraftDefinition): AssemblyRulesV2 | null {
  return definition.assembly_rules.format_version === 2
    ? structuredClone(definition.assembly_rules)
    : null;
}

export function formFromDefinition(definition: DraftDefinition): EditableModelDraftForm {
  return {
    prompt_text: definition.prompt_text,
    endpoint_name: definition.model.endpoint_name,
    temperature: definition.model.temperature,
    max_tokens: definition.model.max_tokens,
    top_p: definition.model.top_p,
    assembly_rules: localRulesFor(definition),
    // No local overlay edits on initialisation — candidateFromForm omits schema_overlay
    // from the wire body when this is null, keeping the five-field save body shape.
    schema_overlay: null,
  };
}

/**
 * Converts a server-echoed candidate back to form state.
 * When the candidate has `schema_overlay`, derive a form overlay from it;
 * when absent or null, the form has no overlay edits (schema_overlay = null).
 */
export function formFromCandidate(candidate: EditableModelDraft): EditableModelDraftForm {
  return {
    prompt_text: candidate.prompt_text,
    endpoint_name: candidate.model.endpoint_name,
    temperature: candidate.model.temperature,
    max_tokens: candidate.model.max_tokens,
    top_p: candidate.model.top_p,
    assembly_rules: candidate.assembly_rules ?? null,
    schema_overlay: candidate.schema_overlay != null
      ? schemaOverlayFormFromWire(candidate.schema_overlay)
      : null,
  };
}

/**
 * Derives the effective schema overlay form state from the saved definition.
 * Used by `OutputSchemaEditor` when the local form has no overlay edits (null).
 * Only `description` and `examples` are extracted from each field override;
 * other properties (type, default, etc.) are ignored (protected).
 * `examples` is serialized as a JSON array string for the textarea.
 */
export function schemaOverlayFormFromDefinition(definition: DraftDefinition): EditableSchemaOverlayForm {
  return schemaOverlayFormFromWire(definition.schema_overlay);
}

function schemaOverlayFormFromWire(overlay: {
  field_overrides: Record<string, unknown>;
  additional_optional_fields: string[];
}): EditableSchemaOverlayForm {
  const fieldOverrides: Record<string, EditableFieldGuidanceForm> = {};
  for (const [key, value] of Object.entries(overlay.field_overrides)) {
    if (typeof value === 'object' && value !== null) {
      const guidance = value as Record<string, unknown>;
      const description = typeof guidance.description === 'string' ? guidance.description : '';
      let examples = '';
      if (guidance.examples !== undefined) {
        try { examples = JSON.stringify(guidance.examples); } catch { /* skip */ }
      }
      fieldOverrides[key] = { description, examples };
    }
  }
  return {
    additional_optional_fields: [...overlay.additional_optional_fields],
    field_overrides: fieldOverrides,
  };
}

export function candidateFromForm(form: EditableModelDraftForm): EditableModelDraft | null {
  const validation = validateDraftForm(form);
  return validation.ok ? validation.candidate : null;
}

/**
 * Converts an editable schema overlay form to the wire format, filtering out
 * any properties other than `description` and `examples`. This is the guard
 * that prevents `type`, `default`, `enum`, and `validator` from ever reaching
 * the domain validator — sending them would produce `overlay_guidance_property_forbidden`.
 *
 * Only `validateDraftForm` calls this, after `overlayExamplesError` has refused every
 * unparseable examples value, so a parse failure here is a programming error: it throws
 * rather than silently dropping the admin's examples from the candidate.
 */
export function overlayFromForm(form: EditableSchemaOverlayForm): EditableSchemaOverlay {
  const fieldOverrides: Record<string, unknown> = {};
  for (const [key, guidance] of Object.entries(form.field_overrides)) {
    const result: Record<string, unknown> = {};
    // Only description and examples are accepted by the domain validator.
    if (guidance.description) result.description = guidance.description;
    if (guidance.examples.trim()) {
      result.examples = JSON.parse(guidance.examples) as unknown;
    }
    if (Object.keys(result).length > 0) {
      fieldOverrides[key] = result;
    }
  }
  return {
    field_overrides: fieldOverrides,
    additional_optional_fields: form.additional_optional_fields,
  };
}

function assemblyRulesEqual(
  left: AssemblyRulesV2 | null,
  right: AssemblyRulesV2 | null,
): boolean {
  if (left === null || right === null) return left === right;
  if (left.custom_blocks.length !== right.custom_blocks.length) return false;
  return left.custom_blocks.every((block, index) => {
    const other = right.custom_blocks[index];
    return block.kind === other.kind
      && block.block_id === other.block_id
      && block.anchor === other.anchor
      && block.condition === other.condition
      && block.text === other.text;
  });
}

function schemaOverlayFormsEqual(
  left: EditableSchemaOverlayForm | null | undefined,
  right: EditableSchemaOverlayForm | null | undefined,
): boolean {
  // null and undefined are both "no overlay edits" and compare equal.
  if (left == null || right == null) return left == null && right == null;
  if (left.additional_optional_fields.length !== right.additional_optional_fields.length) return false;
  if (!left.additional_optional_fields.every((f, i) => f === right.additional_optional_fields[i])) return false;
  const leftKeys = Object.keys(left.field_overrides).sort();
  const rightKeys = Object.keys(right.field_overrides).sort();
  if (leftKeys.length !== rightKeys.length) return false;
  return leftKeys.every((key, i) => {
    if (key !== rightKeys[i]) return false;
    const l = left.field_overrides[key];
    const r = right.field_overrides[key];
    return l.description === r.description && l.examples === r.examples;
  });
}

export function editableFormsEqual(
  left: EditableModelDraftForm,
  right: EditableModelDraftForm,
): boolean {
  return left.prompt_text === right.prompt_text
    && left.endpoint_name === right.endpoint_name
    && left.temperature === right.temperature
    && left.max_tokens === right.max_tokens
    && left.top_p === right.top_p
    && assemblyRulesEqual(left.assembly_rules, right.assembly_rules)
    && schemaOverlayFormsEqual(left.schema_overlay, right.schema_overlay);
}

function cloneDefinition(definition: DraftDefinition): DraftDefinition {
  return structuredClone(definition);
}

export function retainedFormId(agentKey: AgentKey, ordinal: number): string {
  return `retained:${agentKey}:${ordinal}`;
}

/**
 * A form built while the role was on one format version cannot keep its prompt or
 * rules beside an authoritative definition on the other. Sanitizing installs the
 * authoritative prompt and rules and leaves every safe non-prompt field alone.
 */
function sanitizeForm(
  form: EditableModelDraftForm,
  fromVersion: 1 | 2,
  definition: DraftDefinition,
): EditableModelDraftForm {
  if (fromVersion === definitionFormatVersion(definition)) return { ...form };
  return {
    ...form,
    prompt_text: definition.prompt_text,
    assembly_rules: localRulesFor(definition),
  };
}

function sanitizeRetained(
  record: RetainedDraftForm,
  definition: DraftDefinition,
): RetainedDraftForm {
  return {
    ...record,
    form: sanitizeForm(record.form, record.sanitizedFormatVersion, definition),
    sanitizedFormatVersion: definitionFormatVersion(definition),
  };
}

function appendRetained(
  entry: DraftEditorEntry,
  agentKey: AgentKey,
  options: {
    source: RetainedFormSource;
    reason: string;
    form: EditableModelDraftForm;
    manualOnlyPrompt: string;
    fromVersion: 1 | 2;
    definition: DraftDefinition;
  },
): DraftEditorEntry {
  const ordinal = entry.nextRetainedOrdinal;
  return {
    ...entry,
    retainedForms: [
      ...entry.retainedForms,
      {
        id: retainedFormId(agentKey, ordinal),
        source: options.source,
        reason: options.reason,
        form: sanitizeForm(options.form, options.fromVersion, options.definition),
        manualOnlyPrompt: options.manualOnlyPrompt,
        sanitizedFormatVersion: definitionFormatVersion(options.definition),
      },
    ],
    nextRetainedOrdinal: ordinal + 1,
  };
}

/**
 * The single version-aware authoritative-definition adoption rule. Save 200,
 * Save 409, Upgrade 200, Upgrade 409, Keep local, and Reload server all reach the
 * authoritative definition through here, for the selected entry and for every
 * unselected entry alike — selection never decides whether legacy bytes are
 * quarantined.
 */
function adoptAuthoritativeDefinition(
  entry: DraftEditorEntry,
  agentKey: AgentKey,
  definition: DraftDefinition,
  options: { keepLocal: boolean; source: RetainedFormSource; reason: string },
): DraftEditorEntry {
  const fromVersion = definitionFormatVersion(entry.saved);
  const toVersion = definitionFormatVersion(definition);
  const sanitizedRetained = fromVersion === toVersion
    ? entry.retainedForms
    : entry.retainedForms.map((record) => sanitizeRetained(record, definition));
  const base: DraftEditorEntry = { ...entry, saved: definition, retainedForms: sanitizedRetained };

  if (fromVersion === toVersion) {
    return { ...base, local: options.keepLocal ? entry.local : formFromDefinition(definition) };
  }

  const quarantined = appendRetained(base, agentKey, {
    source: options.source,
    reason: options.reason,
    form: entry.local,
    manualOnlyPrompt: entry.local.prompt_text,
    fromVersion,
    definition,
  });
  return {
    ...quarantined,
    local: {
      ...entry.local,
      prompt_text: definition.prompt_text,
      assembly_rules: localRulesFor(definition),
    },
  };
}

export function createDraftEditorState(
  workbench: AgentDefinitionWorkbenchResponse,
): DraftEditorState {
  const byAgent = {} as Record<AgentKey, DraftEditorEntry>;
  for (const agentKey of AGENT_KEYS) {
    const node = workbench.nodes.find((candidate) => candidate.agent_key === agentKey);
    if (!node || node.execution_kind !== 'model') {
      throw new Error(`Agent Definition workbench is missing model role ${agentKey}.`);
    }
    const saved = cloneDefinition(node.draft);
    byAgent[agentKey] = {
      publishedHash: node.published.content_hash,
      saved,
      local: formFromDefinition(saved),
      fieldErrors: {},
      conflict: null,
      retainedForms: [],
      nextRetainedOrdinal: 1,
      responseIssues: [],
      requestError: null,
      probeResult: null,
      testing: emptyAgentTestingState(),
    };
  }
  return { draft: structuredClone(workbench.draft), byAgent, pendingSave: null };
}

export function draftStatus(entry: DraftEditorEntry): DraftStatus {
  if (!editableFormsEqual(entry.local, formFromDefinition(entry.saved))) return 'Unsaved';
  if (entry.saved.candidate_hash === entry.publishedHash) return 'Clean';
  return 'Needs test';
}

/** The server's exact `endpoint_url_not_allowed` table message (#266). */
export const ENDPOINT_URL_NOT_ALLOWED_MESSAGE = 'Endpoint must be a Databricks endpoint name, not a URL.';

const ENDPOINT_URL_PREFIX = /^\s*(?:https?:\/\/|\/\/|[a-z][a-z0-9+.-]*:\/\/)/i;
const ENDPOINT_PATH_METACHARACTERS = /[/\\?#%]/;

function hasAsciiControlCharacter(value: string): boolean {
  for (let index = 0; index < value.length; index += 1) {
    const code = value.charCodeAt(index);
    if (code <= 0x1f || code === 0x7f) return true;
  }
  return false;
}

/**
 * Mirrors `validate_endpoint_name_policy` in `src/services/model_endpoint_catalog.py`
 * (#266 correction 4): a URL prefix, any of `/ \ ? # %`, an ASCII control character,
 * or a bare `.`/`..` dot segment is rejected; every other name is accepted verbatim and
 * never trimmed. Returns the table message, or null for an acceptable name.
 */
export function endpointNamePolicyError(name: string): string | null {
  if (ENDPOINT_URL_PREFIX.test(name)
    || ENDPOINT_PATH_METACHARACTERS.test(name)
    || hasAsciiControlCharacter(name)
    || name === '.'
    || name === '..') {
    return ENDPOINT_URL_NOT_ALLOWED_MESSAGE;
  }
  return null;
}

export function validateDraftForm(form: EditableModelDraftForm):
  | { ok: true; candidate: EditableModelDraft }
  | { ok: false; errors: Partial<Record<DraftFieldErrorKey, string>> } {
  const errors: Partial<Record<DraftFieldErrorKey, string>> = {};
  if (!form.prompt_text.trim()) errors.prompt_text = 'Prompt text must not be blank.';
  if (!form.endpoint_name.trim()) errors.endpoint_name = 'Endpoint name must not be blank.';
  else {
    const endpointPolicyError = endpointNamePolicyError(form.endpoint_name);
    if (endpointPolicyError !== null) errors.endpoint_name = endpointPolicyError;
  }
  if (typeof form.temperature !== 'number'
    || !Number.isFinite(form.temperature)
    || form.temperature < 0
    || form.temperature > 1) {
    errors.temperature = 'Temperature must be between 0 and 1.';
  }
  if (typeof form.max_tokens !== 'number'
    || !Number.isInteger(form.max_tokens)
    || form.max_tokens <= 0) {
    errors.max_tokens = 'Maximum tokens must be a positive integer.';
  }
  if (typeof form.top_p !== 'number'
    || !Number.isFinite(form.top_p)
    || form.top_p < 0
    || form.top_p > 1) {
    errors.top_p = 'Top-p must be between 0 and 1.';
  }
  for (const [fieldName, guidance] of Object.entries(form.schema_overlay?.field_overrides ?? {})) {
    const examplesError = overlayExamplesError(guidance.examples);
    if (examplesError !== null) errors[overlayExamplesErrorKey(fieldName)] = examplesError;
  }
  if (Object.keys(errors).length > 0) return { ok: false, errors };
  return {
    ok: true,
    candidate: {
      prompt_text: form.prompt_text,
      model: {
        endpoint_name: form.endpoint_name,
        temperature: form.temperature as number,
        max_tokens: form.max_tokens as number,
        top_p: form.top_p as number,
      },
      // A v1 candidate omits the key entirely, keeping #263's save body unchanged.
      ...(form.assembly_rules === null
        ? {}
        : { assembly_rules: structuredClone(form.assembly_rules) }),
      // Schema overlay is omitted when null/undefined (no local edits), preserving the
      // stored server overlay unchanged and keeping the five-field body format.
      ...(form.schema_overlay == null
        ? {}
        : { schema_overlay: overlayFromForm(form.schema_overlay) }),
    },
  };
}

export function draftSaveErrorMessage(error: unknown): string {
  if (error instanceof InvalidDraftSaveResponseError) return INVALID_RESPONSE_MESSAGE;
  if (error instanceof AgentDefinitionApiError) return error.detail;
  return 'Unable to save draft. Check your connection and try again.';
}

/**
 * The contained message for a probe that produced no typed result. It never reads the
 * server's detail text, so an untyped error body cannot leak into the panel.
 */
export function probeErrorMessage(error: unknown): string {
  if (error instanceof InvalidDraftSaveResponseError) return PROBE_INVALID_RESPONSE_MESSAGE;
  if (error instanceof AgentDefinitionApiError) return `Unable to test structured output (${error.status}).`;
  return 'Unable to test structured output. Check your connection and try again.';
}

export const TEST_RUN_INVALID_RESPONSE_MESSAGE =
  'Unable to run the test case because the server response was invalid.';
export const TEST_RUN_STALE_DRAFT_MESSAGE =
  'The draft changed on the server. Review the change, then run the test case again.';
export const TEST_RUN_REJECTED_MESSAGE = 'The saved candidate was refused.';
export const TEST_CASE_INVALID_RESPONSE_MESSAGE =
  'Unable to update the test case because the server response was invalid.';

export type TestOperationVerb = 'run' | 'create' | 'retire' | 'load' | 'update';

const TEST_OPERATION_SUBJECT: Record<TestOperationVerb, string> = {
  run: 'run the test case',
  create: 'save the test case',
  retire: 'retire the test case',
  update: 'save the new test case version',
  load: 'load Agent Test Cases',
};

/**
 * The contained panel message (and any ordered server issues) for a failed test
 * operation. Typed refusals map to fixed client copy; an untyped error body is never
 * read, so server or proxy text cannot leak into the panel.
 */
export function testOperationFailure(
  error: unknown,
  verb: TestOperationVerb,
): { message: string; issues: DraftFieldError[] } {
  const subject = TEST_OPERATION_SUBJECT[verb];
  if (error instanceof AgentTestApiError) {
    switch (error.failure.code) {
      case 'stale_test_case':
        return {
          message: 'This test case version is no longer active. Refresh test cases and run its current version.',
          issues: [],
        };
      case 'invalid_test_case':
        return { message: 'The test case was refused.', issues: error.failure.issues };
      case 'test_case_not_found':
        return { message: 'This test case no longer exists. Refresh test cases.', issues: [] };
      case 'test_run_unavailable':
        return { message: TEST_RUN_UNAVAILABLE.message, issues: [] };
    }
  }
  if (error instanceof InvalidTestRunResponseError) {
    return { message: `Unable to ${subject} because the server response was invalid.`, issues: [] };
  }
  if (error instanceof AgentDefinitionApiError) {
    const rejection = error.status === 422 ? parseDraftValidationErrorResponse(error.payload) : null;
    if (rejection !== null) return { message: 'The published definition was refused.', issues: rejection.errors };
    return { message: `Unable to ${subject} (${error.status}).`, issues: [] };
  }
  return { message: `Unable to ${subject}. Check your connection and try again.`, issues: [] };
}

/**
 * A candidate run tests the role's **saved** candidate, so it is refused while any
 * field of that role differs locally: the run would not test what is on screen.
 */
export function testRunCandidateUnsaved(entry: DraftEditorEntry): boolean {
  return !editableFormsEqual(entry.local, formFromDefinition(entry.saved));
}

/** A probe may only test the saved endpoint: it is refused while the local one differs. */
export function probeEndpointUnsaved(entry: DraftEditorEntry): boolean {
  return entry.local.endpoint_name !== entry.saved.model.endpoint_name;
}

/**
 * A probe result describes one saved candidate. It survives only while the saved
 * candidate it names is still the saved one.
 */
function probeResultAfterAdoption(before: DraftEditorEntry, after: DraftEditorEntry): DraftProbeResult | null {
  return after.saved.candidate_hash === before.saved.candidate_hash
    && after.saved.model.endpoint_name === before.saved.model.endpoint_name
    ? before.probeResult
    : null;
}

/** A result for an endpoint that is no longer the local one is dropped, never shown. */
function probeResultAfterLocalChange(before: DraftEditorEntry, local: EditableModelDraftForm): DraftProbeResult | null {
  return local.endpoint_name === before.local.endpoint_name ? before.probeResult : null;
}

function replaceEntry(
  state: DraftEditorState,
  agentKey: AgentKey,
  entry: DraftEditorEntry,
): DraftEditorState {
  return { ...state, byAgent: { ...state.byAgent, [agentKey]: entry } };
}

function invalidCompletion(state: DraftEditorState, pending: PendingDraftSave): DraftEditorState {
  return {
    ...state,
    pendingSave: null,
    byAgent: {
      ...state.byAgent,
      [pending.agentKey]: {
        ...state.byAgent[pending.agentKey],
        requestError: INVALID_RESPONSE_MESSAGE,
      },
    },
  };
}

/** The matching pending identity is the operation kind plus its request ID. */
function matchingPending(
  state: DraftEditorState,
  operation: DraftOperationKind,
  requestId: number,
): PendingDraftSave | null {
  if (state.pendingSave === null) return null;
  if (state.pendingSave.operation !== operation) return null;
  if (state.pendingSave.requestId !== requestId) return null;
  return state.pendingSave;
}

function fieldErrorsFromResponse(
  error: DraftValidationErrorResponse,
): Partial<Record<EditableDraftField, string>> {
  const result: Partial<Record<EditableDraftField, string>> = {};
  for (const item of error.errors) {
    const field = INLINE_FIELD_OWNERS[item.field];
    if (field) result[field] = item.message;
  }
  return result;
}

/** Issues without an inline field owner keep their exact server order. */
function nonInlineIssues(error: DraftValidationErrorResponse): DraftFieldError[] {
  return error.errors.filter((item) => INLINE_FIELD_OWNERS[item.field] === undefined);
}

function startOperation(
  state: DraftEditorState,
  pending: PendingDraftSave,
): DraftEditorState {
  const entry = state.byAgent[pending.agentKey];
  return {
    ...replaceEntry(state, pending.agentKey, {
      ...entry,
      fieldErrors: {},
      responseIssues: [],
      requestError: null,
    }),
    pendingSave: pending,
  };
}

function rejectOperation(
  state: DraftEditorState,
  operation: DraftOperationKind,
  requestId: number,
  error: DraftValidationErrorResponse,
): DraftEditorState {
  const pending = matchingPending(state, operation, requestId);
  if (pending === null) return state;
  const entry = state.byAgent[pending.agentKey];
  return {
    ...state,
    pendingSave: null,
    byAgent: {
      ...state.byAgent,
      [pending.agentKey]: {
        ...entry,
        // A probe's only draft rejection is the saved-name policy re-check, which is
        // owned by the endpoint field exactly as a save's is.
        fieldErrors: operation === 'save' || operation === 'probe' || operation === 'testRun'
          ? fieldErrorsFromResponse(error)
          : entry.fieldErrors,
        responseIssues: nonInlineIssues(error),
      },
    },
  };
}

function failOperation(
  state: DraftEditorState,
  operation: DraftOperationKind,
  requestId: number,
  message: string,
): DraftEditorState {
  const pending = matchingPending(state, operation, requestId);
  if (pending === null) return state;
  const entry = state.byAgent[pending.agentKey];
  return {
    ...state,
    pendingSave: null,
    byAgent: {
      ...state.byAgent,
      [pending.agentKey]: { ...entry, requestError: message },
    },
  };
}

function mergeConflict(
  state: DraftEditorState,
  operation: DraftOperationKind,
  requestId: number,
  conflict: DraftSaveConflictResponse,
): DraftEditorState {
  const pending = matchingPending(state, operation, requestId);
  if (pending === null) return state;
  if (conflict.current_lock_version !== conflict.server.draft.lock_version
    || conflict.current_lock_version <= pending.expectedLockVersion
    || conflict.current_lock_version < state.draft.lock_version) {
    return invalidCompletion(state, pending);
  }
  const serverDefinitions = conflict.server.definitions;
  const byAgent = {} as Record<AgentKey, DraftEditorEntry>;
  for (const agentKey of AGENT_KEYS) {
    const entry = state.byAgent[agentKey];
    const wasLocallyClean = editableFormsEqual(entry.local, formFromDefinition(entry.saved));
    const adopted = adoptAuthoritativeDefinition(entry, agentKey, serverDefinitions[agentKey], {
      keepLocal: agentKey === pending.agentKey || !wasLocallyClean,
      source: 'version_adoption',
      reason: RETAINED_REASONS.version_adoption,
    });
    byAgent[agentKey] = {
      ...adopted,
      fieldErrors: agentKey === pending.agentKey ? {} : entry.fieldErrors,
      conflict: agentKey === pending.agentKey ? conflict : null,
      requestError: agentKey === pending.agentKey ? null : entry.requestError,
      probeResult: agentKey === pending.agentKey && pending.operation === 'probe'
        ? null
        : probeResultAfterAdoption(entry, adopted),
    };
  }
  return { draft: conflict.server.draft, byAgent, pendingSave: null };
}

function succeedWrite(
  state: DraftEditorState,
  operation: DraftOperationKind,
  requestId: number,
  result: DraftSaveSuccessResponse,
  keepLocal: (entry: DraftEditorEntry, pending: PendingDraftSave) => boolean,
): DraftEditorState {
  const pending = matchingPending(state, operation, requestId);
  if (pending === null) return state;
  if (result.draft.lock_version !== pending.expectedLockVersion + 1
    || result.draft.lock_version < state.draft.lock_version) {
    return invalidCompletion(state, pending);
  }
  const entry = state.byAgent[pending.agentKey];
  const adopted = adoptAuthoritativeDefinition(entry, pending.agentKey, result.definition, {
    keepLocal: keepLocal(entry, pending),
    source: 'version_adoption',
    reason: RETAINED_REASONS.version_adoption,
  });
  return {
    draft: result.draft,
    pendingSave: null,
    byAgent: {
      ...state.byAgent,
      [pending.agentKey]: {
        ...adopted,
        fieldErrors: {},
        conflict: null,
        responseIssues: [],
        requestError: null,
        probeResult: probeResultAfterAdoption(entry, adopted),
      },
    },
  };
}

/**
 * Settles the pending probe. The route never writes, so the reported identity must be
 * exactly the saved candidate this client holds at the lock it sent; anything else is
 * contained as an invalid response. Nothing but the pending slot and this role's
 * probe result may change: not the lock, the saved entry, the form, or the status.
 */
function settleProbe(
  state: DraftEditorState,
  requestId: number,
  reported: StructuredOutputProbeIdentity,
  result: (identity: StructuredOutputProbeIdentity) => DraftProbeResult,
): DraftEditorState {
  const pending = matchingPending(state, 'probe', requestId);
  if (pending === null) return state;
  const entry = state.byAgent[pending.agentKey];
  const coherent = reported.lock_version === pending.expectedLockVersion
    && state.draft.lock_version === pending.expectedLockVersion
    && reported.endpoint_name === entry.saved.model.endpoint_name
    && reported.candidate_hash === entry.saved.candidate_hash;
  if (!coherent) {
    return {
      ...replaceEntry(state, pending.agentKey, {
        ...entry,
        probeResult: null,
        requestError: PROBE_INVALID_RESPONSE_MESSAGE,
      }),
      pendingSave: null,
    };
  }
  const identity: StructuredOutputProbeIdentity = {
    endpoint_name: reported.endpoint_name,
    candidate_hash: reported.candidate_hash,
    lock_version: reported.lock_version,
  };
  return {
    ...replaceEntry(state, pending.agentKey, {
      ...entry,
      // An endpoint edited while the probe was in flight is no longer the tested one.
      probeResult: entry.local.endpoint_name === identity.endpoint_name ? result(identity) : null,
    }),
    pendingSave: null,
  };
}

function withLocalRules(
  entry: DraftEditorEntry,
  update: (blocks: CustomTextBlock[]) => CustomTextBlock[],
): DraftEditorEntry {
  const rules = entry.local.assembly_rules;
  if (rules === null) return entry;
  return {
    ...entry,
    local: {
      ...entry.local,
      assembly_rules: { format_version: 2, custom_blocks: update(rules.custom_blocks) },
    },
    requestError: null,
  };
}

/**
 * True while this entry's own protected-assembly Upgrade is in flight for an affected
 * v1 role. Every action that could move the savable local prompt must consult this,
 * not just `edit`: the brief's backstop covers *any* prompt-change action during that
 * request, and restoring a retained alternative is one of them.
 */
function promptChangeIsQuarantined(state: DraftEditorState, agentKey: AgentKey): boolean {
  const pending = state.pendingSave;
  return pending !== null
    && pending.operation === 'upgrade'
    && pending.agentKey === agentKey
    && isLegacyCompositeRole(agentKey)
    && definitionFormatVersion(state.byAgent[agentKey].saved) === 1;
}

/**
 * Applies a proposed form while refusing its prompt: the savable local prompt stays at
 * the authoritative v1 value and the proposed bytes are appended as manual-only. Safe
 * non-prompt values in the proposal are kept, so a caller may still restore them.
 */
function quarantinePromptChange(
  state: DraftEditorState,
  agentKey: AgentKey,
  proposal: EditableModelDraftForm,
  proposedPrompt: string,
): DraftEditorState {
  const entry = state.byAgent[agentKey];
  const authoritative: EditableModelDraftForm = {
    ...proposal,
    prompt_text: entry.saved.prompt_text,
  };
  return replaceEntry(state, agentKey, appendRetained(
    { ...entry, local: authoritative },
    agentKey,
    {
      source: 'pending_prompt_quarantine',
      reason: RETAINED_REASONS.pending_prompt_quarantine,
      form: authoritative,
      manualOnlyPrompt: proposedPrompt,
      fromVersion: definitionFormatVersion(entry.saved),
      definition: entry.saved,
    },
  ));
}

function isTestOperation(operation: DraftOperationKind): operation is TestOperationKind {
  return (TEST_OPERATIONS as readonly DraftOperationKind[]).includes(operation);
}

/** The pending test operation this request ID started, of any #267 kind, or `null`. */
function matchingTestPending(state: DraftEditorState, requestId: number): PendingDraftSave | null {
  const pending = state.pendingSave;
  if (pending === null || !isTestOperation(pending.operation) || pending.requestId !== requestId) return null;
  return pending;
}

function withTesting(
  state: DraftEditorState,
  agentKey: AgentKey,
  update: (testing: AgentTestingState) => AgentTestingState,
): DraftEditorState {
  const entry = state.byAgent[agentKey];
  return replaceEntry(state, agentKey, { ...entry, testing: update(entry.testing) });
}

/** Settles the pending test operation, changing nothing but the pending slot and its panel. */
function settleTestOperation(
  state: DraftEditorState,
  pending: PendingDraftSave,
  update: (testing: AgentTestingState) => AgentTestingState,
): DraftEditorState {
  return { ...withTesting(state, pending.agentKey, update), pendingSave: null };
}

/**
 * A run response must be evidence for exactly the run the client started: this role,
 * this case, this kind, and for a candidate the saved candidate this client holds at
 * the lock it sent. Anything else is contained as an invalid response.
 */
function runEvidenceIsCoherent(
  state: DraftEditorState,
  pending: PendingDraftSave,
  evidence: TestRunEvidence,
): boolean {
  if (evidence.agent_key !== pending.agentKey || evidence.test_case_id !== pending.testCaseId) return false;
  if (pending.operation === 'baselineRun') return evidence.run_kind === 'published_baseline';
  return pending.operation === 'testRun'
    && evidence.run_kind === 'candidate'
    && state.draft.lock_version === pending.expectedLockVersion
    && evidence.candidate_hash === state.byAgent[pending.agentKey].saved.candidate_hash;
}

function settledTesting(testing: AgentTestingState): AgentTestingState {
  return { ...testing, error: null, issues: [], notice: null };
}

export function draftEditorReducer(
  state: DraftEditorState,
  action: DraftEditorAction,
): DraftEditorState {
  switch (action.type) {
    case 'edit': {
      const entry = state.byAgent[action.agentKey];
      if (action.field === 'prompt_text' && promptChangeIsQuarantined(state, action.agentKey)) {
        return quarantinePromptChange(state, action.agentKey, entry.local, String(action.value));
      }
      const local = { ...entry.local, [action.field]: action.value };
      return replaceEntry(state, action.agentKey, {
        ...entry,
        local,
        fieldErrors: { ...entry.fieldErrors, [action.field]: undefined },
        responseIssues: [],
        requestError: null,
        // Any endpoint edit clears the old result, even one that returns to the saved name.
        probeResult: action.field === 'endpoint_name' ? null : entry.probeResult,
      });
    }
    case 'assemblyBlockAdded': {
      const entry = state.byAgent[action.agentKey];
      return replaceEntry(state, action.agentKey, withLocalRules(entry, (blocks) => {
        const block: CustomTextBlock = {
          kind: 'custom_text',
          block_id: action.blockId,
          anchor: action.anchor,
          condition: 'always',
          text: '',
        };
        // The server requires `custom_blocks` in non-decreasing anchor rank and refuses
        // anything else with `invalid_anchor_order`. Appending when the chosen anchor had
        // no sibling yet made the array's order depend on click order, so adding at a
        // later anchor first built a draft every save rejected — at an anchor the panel
        // itself offered. Inserting after the last block whose rank is at most the new
        // block's keeps the array ordered whatever order the admin clicks in, and leaves
        // same-anchor order theirs: rank equality keeps the new block last in its group.
        // `CUSTOM_ANCHORS` is declared in the server's own rank order and is joined to it
        // by `test_client_condition_and_anchor_vocabularies_match_the_server`, so this
        // introduces no second rank table for that order to drift against.
        const rankOf = (anchor: CustomAnchor) => CUSTOM_ANCHORS.indexOf(anchor);
        const insertAfter = blocks.reduce(
          (found, candidate, index) => (
            rankOf(candidate.anchor) <= rankOf(action.anchor) ? index : found
          ),
          -1,
        );
        return [...blocks.slice(0, insertAfter + 1), block, ...blocks.slice(insertAfter + 1)];
      }));
    }
    case 'assemblyBlockTextChanged': {
      const entry = state.byAgent[action.agentKey];
      return replaceEntry(state, action.agentKey, withLocalRules(entry, (blocks) => blocks.map(
        (block) => (block.block_id === action.blockId ? { ...block, text: action.text } : block),
      )));
    }
    case 'assemblyBlockConditionChanged': {
      const entry = state.byAgent[action.agentKey];
      return replaceEntry(state, action.agentKey, withLocalRules(entry, (blocks) => blocks.map(
        (block) => (
          block.block_id === action.blockId ? { ...block, condition: action.condition } : block
        ),
      )));
    }
    case 'assemblyBlockDeleted': {
      const entry = state.byAgent[action.agentKey];
      return replaceEntry(state, action.agentKey, withLocalRules(
        entry,
        (blocks) => blocks.filter((block) => block.block_id !== action.blockId),
      ));
    }
    case 'assemblyBlockMoved': {
      const entry = state.byAgent[action.agentKey];
      return replaceEntry(state, action.agentKey, withLocalRules(entry, (blocks) => {
        const index = blocks.findIndex((block) => block.block_id === action.blockId);
        if (index === -1) return blocks;
        const anchor = blocks[index].anchor;
        const siblings = blocks
          .map((block, position) => ({ block, position }))
          .filter((item) => item.block.anchor === anchor);
        const offset = siblings.findIndex((item) => item.position === index);
        const target = action.direction === 'up' ? offset - 1 : offset + 1;
        // An arrow can never cross an anchor boundary.
        if (target < 0 || target >= siblings.length) return blocks;
        const next = [...blocks];
        const swapIndex = siblings[target].position;
        next[index] = blocks[swapIndex];
        next[swapIndex] = blocks[index];
        return next;
      }));
    }
    case 'saveInvalid': {
      const entry = state.byAgent[action.agentKey];
      return replaceEntry(state, action.agentKey, { ...entry, fieldErrors: action.errors });
    }
    case 'saveStarted': {
      if (state.pendingSave !== null) return state;
      return startOperation(state, action.pending);
    }
    case 'upgradeStarted': {
      if (state.pendingSave !== null) return state;
      const entry = state.byAgent[action.pending.agentKey];
      // Reducer backstop: an affected v1 role may not start an Upgrade while its
      // local prompt differs from the authoritative saved prompt.
      if (isLegacyCompositeRole(action.pending.agentKey)
        && definitionFormatVersion(entry.saved) === 1
        && entry.local.prompt_text !== entry.saved.prompt_text) {
        return state;
      }
      return startOperation(state, action.pending);
    }
    case 'sourceRecoveryStarted': {
      if (state.pendingSave !== null) return state;
      return startOperation(state, action.pending);
    }
    case 'schemaUpgradeStarted': {
      if (state.pendingSave !== null) return state;
      return startOperation(state, action.pending);
    }
    case 'probeStarted': {
      if (state.pendingSave !== null) return state;
      const entry = state.byAgent[action.pending.agentKey];
      // Reducer backstop: only the saved endpoint may be probed.
      if (probeEndpointUnsaved(entry)) return state;
      // A probe reads and never writes, so it keeps the role's local field errors.
      return {
        ...replaceEntry(state, action.pending.agentKey, { ...entry, requestError: null, probeResult: null }),
        pendingSave: action.pending,
      };
    }
    case 'probeSucceeded':
      return settleProbe(state, action.requestId, action.result, (identity) => ({
        outcome: 'succeeded',
        ...identity,
      }));
    case 'probeUnsuccessful':
      return settleProbe(state, action.requestId, action.failure, (identity) => ({
        outcome: 'failed',
        code: action.failure.code,
        message: action.failure.message,
        retryable: action.failure.retryable,
        ...identity,
      }));
    case 'testCasesLoadStarted':
      return withTesting(state, action.agentKey, (testing) => ({
        ...testing,
        casesStatus: 'loading',
        casesRequestId: action.requestId,
        error: null,
        issues: [],
      }));
    case 'testCasesLoaded': {
      if (state.byAgent[action.agentKey].testing.casesRequestId !== action.requestId) return state;
      return withTesting(state, action.agentKey, (testing) => ({
        ...testing,
        casesStatus: 'ready',
        cases: action.items,
        casesRequestId: null,
      }));
    }
    case 'testCasesLoadFailed': {
      if (state.byAgent[action.agentKey].testing.casesRequestId !== action.requestId) return state;
      return withTesting(state, action.agentKey, (testing) => ({
        ...testing,
        casesStatus: testing.cases.length > 0 ? 'ready' : 'error',
        casesRequestId: null,
        error: action.message,
        issues: [],
      }));
    }
    case 'testOperationStarted': {
      if (state.pendingSave !== null) return state;
      if (!isTestOperation(action.pending.operation)) return state;
      const entry = state.byAgent[action.pending.agentKey];
      // Reducer backstop: only the saved candidate may be run.
      if (action.pending.operation === 'testRun' && testRunCandidateUnsaved(entry)) return state;
      // A test operation never touches the draft editor's own field errors or messages.
      return {
        ...replaceEntry(state, action.pending.agentKey, { ...entry, testing: settledTesting(entry.testing) }),
        pendingSave: action.pending,
      };
    }
    case 'testRunSucceeded': {
      const pending = matchingTestPending(state, action.requestId);
      if (pending === null || (pending.operation !== 'testRun' && pending.operation !== 'baselineRun')) return state;
      if (!runEvidenceIsCoherent(state, pending, action.evidence)) {
        return settleTestOperation(state, pending, (testing) => ({
          ...testing,
          error: TEST_RUN_INVALID_RESPONSE_MESSAGE,
          issues: [],
        }));
      }
      return settleTestOperation(state, pending, (testing) => (pending.operation === 'testRun'
        ? { ...settledTesting(testing), candidateEvidence: action.evidence }
        : { ...settledTesting(testing), baselineEvidence: action.evidence }));
    }
    case 'testRunRejected': {
      const pending = matchingPending(state, 'testRun', action.requestId);
      if (pending === null) return state;
      return withTesting(rejectOperation(state, 'testRun', action.requestId, action.error), pending.agentKey, (testing) => ({
        ...testing,
        error: TEST_RUN_REJECTED_MESSAGE,
        issues: action.error.errors,
      }));
    }
    case 'testRunConflicted': {
      const pending = matchingPending(state, 'testRun', action.requestId);
      if (pending === null) return state;
      return withTesting(mergeConflict(state, 'testRun', action.requestId, action.conflict), pending.agentKey, (testing) => ({
        ...testing,
        error: TEST_RUN_STALE_DRAFT_MESSAGE,
        issues: [],
      }));
    }
    case 'testCaseCreated': {
      const pending = matchingTestPending(state, action.requestId);
      if (pending === null || pending.operation !== 'testCaseCreate') return state;
      if (action.testCase.agent_key !== pending.agentKey || !action.testCase.is_active) {
        return settleTestOperation(state, pending, (testing) => ({
          ...testing, error: TEST_CASE_INVALID_RESPONSE_MESSAGE, issues: [],
        }));
      }
      // The write settles the list; a read that started before it can no longer land.
      return settleTestOperation(state, pending, (testing) => ({
        ...settledTesting(testing),
        casesStatus: 'ready',
        casesRequestId: null,
        cases: [...testing.cases.filter((item) => item.id !== action.testCase.id), action.testCase],
      }));
    }
    case 'testCaseRetired': {
      const pending = matchingTestPending(state, action.requestId);
      if (pending === null || pending.operation !== 'testCaseRetire') return state;
      if (action.testCase.id !== pending.testCaseId || action.testCase.agent_key !== pending.agentKey) {
        return settleTestOperation(state, pending, (testing) => ({
          ...testing, error: TEST_CASE_INVALID_RESPONSE_MESSAGE, issues: [],
        }));
      }
      return settleTestOperation(state, pending, (testing) => ({
        ...settledTesting(testing),
        casesStatus: 'ready',
        casesRequestId: null,
        cases: testing.cases.filter((item) => item.id !== action.testCase.id),
      }));
    }
    case 'testCaseUpdated': {
      const pending = matchingTestPending(state, action.requestId);
      if (pending === null || pending.operation !== 'testCaseUpdate') return state;
      const edited = state.byAgent[pending.agentKey].testing.cases.find((item) => item.id === pending.testCaseId);
      if (action.testCase.agent_key !== pending.agentKey
        || !action.testCase.is_active
        || (edited !== undefined && action.testCase.name !== edited.name)) {
        return settleTestOperation(state, pending, (testing) => ({
          ...testing, error: TEST_CASE_INVALID_RESPONSE_MESSAGE, issues: [],
        }));
      }
      // The server's identical-content no-op returns the version it was asked to edit.
      if (action.testCase.id === pending.testCaseId) {
        return settleTestOperation(state, pending, (testing) => ({
          ...settledTesting(testing),
          notice: `No change: this content matches version ${action.testCase.version}, so no new version was created.`,
        }));
      }
      return settleTestOperation(state, pending, (testing) => ({
        ...settledTesting(testing),
        casesStatus: 'ready',
        casesRequestId: null,
        cases: [
          ...testing.cases.filter((item) => item.id !== pending.testCaseId && item.id !== action.testCase.id),
          action.testCase,
        ],
      }));
    }
    case 'testOperationFailed': {
      const pending = matchingTestPending(state, action.requestId);
      if (pending === null) return state;
      return settleTestOperation(state, pending, (testing) => ({
        ...testing,
        error: action.message,
        issues: action.issues,
      }));
    }
    case 'probeRejected':
      return rejectOperation(state, 'probe', action.requestId, action.error);
    case 'probeConflicted':
      return mergeConflict(state, 'probe', action.requestId, action.conflict);
    case 'probeFailed':
      return failOperation(state, 'probe', action.requestId, action.message);
    case 'saveSucceeded':
      return succeedWrite(state, 'save', action.requestId, action.result, (entry, pending) => (
        pending.submittedCandidate === null
        || !editableFormsEqual(entry.local, formFromCandidate(pending.submittedCandidate))
      ));
    case 'upgradeSucceeded':
      // Safe non-prompt edits made while pending survive; prompt and rules come
      // only from the server-authored v2 definition.
      return succeedWrite(state, 'upgrade', action.requestId, action.result, () => true);
    case 'schemaUpgradeSucceeded':
      // Schema contract upgrade: the server installs the new contract and optional
      // field catalog and changes nothing else (`upgrade_content_to_v2` keeps the
      // stored overlay verbatim). So every local edit survives, overlay edits included:
      // prompt, model and overlay edits made while the request was in flight (A2 to A3)
      // are kept, and the next Save re-validates the overlay against the v2 contract.
      // Pinned by 'keeps prompt, model and overlay edits made while the Schema Upgrade
      // was pending (A2 to A3)' in draftEditorState.test.ts.
      return succeedWrite(state, 'schemaUpgrade', action.requestId, action.result, () => true);
    case 'saveRejected':
      return rejectOperation(state, 'save', action.requestId, action.error);
    case 'upgradeRejected':
      return rejectOperation(state, 'upgrade', action.requestId, action.error);
    case 'sourceRecoveryRejected':
      return rejectOperation(state, 'sourceRecovery', action.requestId, action.error);
    case 'schemaUpgradeRejected':
      return rejectOperation(state, 'schemaUpgrade', action.requestId, action.error);
    case 'saveConflicted':
      return mergeConflict(state, 'save', action.requestId, action.conflict);
    case 'upgradeConflicted':
      return mergeConflict(state, 'upgrade', action.requestId, action.conflict);
    case 'sourceRecoveryConflicted':
      return mergeConflict(state, 'sourceRecovery', action.requestId, action.conflict);
    case 'schemaUpgradeConflicted':
      return mergeConflict(state, 'schemaUpgrade', action.requestId, action.conflict);
    case 'saveFailed':
      return failOperation(state, 'save', action.requestId, action.message);
    case 'upgradeFailed':
      return failOperation(state, 'upgrade', action.requestId, action.message);
    case 'sourceRecoveryFailed':
      return failOperation(state, 'sourceRecovery', action.requestId, action.message);
    case 'schemaUpgradeFailed':
      return failOperation(state, 'schemaUpgrade', action.requestId, action.message);
    case 'sourceRecoverySucceeded': {
      const pending = matchingPending(state, 'sourceRecovery', action.requestId);
      if (pending === null) return state;
      // This route never writes, so the lock must not have moved and the record must
      // describe the role that asked for it. This is a client-only assumption; see the
      // note on `readDraftLegacyPromptSource` in `agentDefinitions.ts`.
      if (action.result.agent_key !== pending.agentKey
        || action.result.lock_version !== pending.expectedLockVersion
        || action.result.draft.lock_version !== pending.expectedLockVersion) {
        return invalidCompletion(state, pending);
      }
      const entry = state.byAgent[pending.agentKey];
      const fromVersion = definitionFormatVersion(entry.saved);
      let next = appendRetained(entry, pending.agentKey, {
        source: 'legacy_source_recovery',
        reason: RETAINED_REASONS.legacy_source_recovery_saved,
        form: formFromDefinition(entry.saved),
        manualOnlyPrompt: entry.saved.prompt_text,
        fromVersion,
        definition: entry.saved,
      });
      next = appendRetained(next, pending.agentKey, {
        source: 'legacy_source_recovery',
        reason: RETAINED_REASONS.legacy_source_recovery_local,
        form: entry.local,
        manualOnlyPrompt: entry.local.prompt_text,
        fromVersion,
        definition: entry.saved,
      });
      return {
        ...state,
        pendingSave: null,
        byAgent: {
          ...state.byAgent,
          [pending.agentKey]: {
            ...next,
            local: { ...entry.local, prompt_text: action.result.source.prompt_text },
            responseIssues: [],
            requestError: null,
          },
        },
      };
    }
    case 'dirtyLegacyPromptRetained': {
      const entry = state.byAgent[action.agentKey];
      return replaceEntry(state, action.agentKey, appendRetained(entry, action.agentKey, {
        source: 'dirty_legacy_prompt',
        reason: RETAINED_REASONS.dirty_legacy_prompt,
        form: entry.local,
        manualOnlyPrompt: entry.local.prompt_text,
        fromVersion: definitionFormatVersion(entry.saved),
        definition: entry.saved,
      }));
    }
    case 'reloadServer': {
      const entry = state.byAgent[action.agentKey];
      const appended = appendRetained(entry, action.agentKey, {
        source: 'reload_server',
        reason: RETAINED_REASONS.reload_server,
        form: entry.local,
        manualOnlyPrompt: entry.local.prompt_text,
        fromVersion: definitionFormatVersion(entry.saved),
        definition: entry.saved,
      });
      const local = formFromDefinition(entry.saved);
      return replaceEntry(state, action.agentKey, {
        ...appended,
        local,
        conflict: null,
        fieldErrors: {},
        probeResult: probeResultAfterLocalChange(entry, local),
      });
    }
    case 'keepLocal': {
      const entry = state.byAgent[action.agentKey];
      return replaceEntry(state, action.agentKey, { ...entry, conflict: null });
    }
    case 'restoreSavedPrompt': {
      const entry = state.byAgent[action.agentKey];
      return replaceEntry(state, action.agentKey, {
        ...entry,
        local: { ...entry.local, prompt_text: entry.saved.prompt_text },
        fieldErrors: { ...entry.fieldErrors, prompt_text: undefined },
      });
    }
    case 'restoreRetained': {
      const entry = state.byAgent[action.agentKey];
      const record = entry.retainedForms.find((item) => item.id === action.retainedId);
      if (record === undefined) return state;
      // Re-apply the version invariant against whatever is authoritative now, so a
      // record sanitized against an older format version can never reintroduce its
      // prompt or rules beside the current saved definition.
      const restored = sanitizeForm(record.form, record.sanitizedFormatVersion, entry.saved);
      // Restoring is itself a prompt-change action, so it meets the same backstop as
      // `edit`: the safe fields are restored, the prompt is not.
      if (restored.prompt_text !== entry.saved.prompt_text
        && promptChangeIsQuarantined(state, action.agentKey)) {
        const quarantined = quarantinePromptChange(
          state,
          action.agentKey,
          restored,
          restored.prompt_text,
        );
        const quarantinedEntry = quarantined.byAgent[action.agentKey];
        return replaceEntry(quarantined, action.agentKey, {
          ...quarantinedEntry,
          fieldErrors: {},
          probeResult: probeResultAfterLocalChange(entry, restored),
        });
      }
      return replaceEntry(state, action.agentKey, {
        ...entry,
        local: restored,
        fieldErrors: {},
        probeResult: probeResultAfterLocalChange(entry, restored),
      });
    }
    case 'discardRetained': {
      // No pending guard is needed: discarding never writes to `local`, so it cannot
      // move the savable prompt. It only drops bytes the admin explicitly discarded.
      const entry = state.byAgent[action.agentKey];
      if (!entry.retainedForms.some((item) => item.id === action.retainedId)) return state;
      return replaceEntry(state, action.agentKey, {
        ...entry,
        retainedForms: entry.retainedForms.filter((item) => item.id !== action.retainedId),
      });
    }
    case 'schemaOverlayOptionalFieldToggled': {
      const entry = state.byAgent[action.agentKey];
      // Initialise from saved definition when no local overlay edits exist yet.
      const current: EditableSchemaOverlayForm = entry.local.schema_overlay
        ?? schemaOverlayFormFromDefinition(entry.saved);
      const has = current.additional_optional_fields.includes(action.fieldName);
      const next: EditableSchemaOverlayForm = {
        ...current,
        additional_optional_fields: has
          ? current.additional_optional_fields.filter((f) => f !== action.fieldName)
          : [...current.additional_optional_fields, action.fieldName],
      };
      return replaceEntry(state, action.agentKey, {
        ...entry,
        local: { ...entry.local, schema_overlay: next },
        responseIssues: [],
        requestError: null,
      });
    }
    case 'schemaOverlayFieldDescriptionChanged': {
      const entry = state.byAgent[action.agentKey];
      const current: EditableSchemaOverlayForm = entry.local.schema_overlay
        ?? schemaOverlayFormFromDefinition(entry.saved);
      const existing = current.field_overrides[action.fieldName] ?? { description: '', examples: '' };
      const next: EditableSchemaOverlayForm = {
        ...current,
        field_overrides: {
          ...current.field_overrides,
          [action.fieldName]: { ...existing, description: action.description },
        },
      };
      return replaceEntry(state, action.agentKey, {
        ...entry,
        local: { ...entry.local, schema_overlay: next },
        responseIssues: [],
        requestError: null,
      });
    }
    case 'schemaOverlayFieldExamplesChanged': {
      const entry = state.byAgent[action.agentKey];
      const current: EditableSchemaOverlayForm = entry.local.schema_overlay
        ?? schemaOverlayFormFromDefinition(entry.saved);
      const existing = current.field_overrides[action.fieldName] ?? { description: '', examples: '' };
      const next: EditableSchemaOverlayForm = {
        ...current,
        field_overrides: {
          ...current.field_overrides,
          [action.fieldName]: { ...existing, examples: action.examples },
        },
      };
      return replaceEntry(state, action.agentKey, {
        ...entry,
        local: { ...entry.local, schema_overlay: next },
        fieldErrors: { ...entry.fieldErrors, [overlayExamplesErrorKey(action.fieldName)]: undefined },
        responseIssues: [],
        requestError: null,
      });
    }
  }
}
