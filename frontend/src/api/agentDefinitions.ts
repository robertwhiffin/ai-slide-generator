const API_BASE_URL = import.meta.env.VITE_API_URL || (
  import.meta.env.MODE === 'production' ? '' : 'http://127.0.0.1:8000'
);

const WORKBENCH_URL = `${API_BASE_URL}/api/admin/agent-definitions/workbench`;

export type AgentKey =
  | 'architect'
  | 'data_analyst'
  | 'builder'
  | 'build_reviewer'
  | 'fixer'
  | 'fix_reviewer'
  | 'deck_reviewer';

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

export class AgentDefinitionApiError extends Error {
  readonly status: number;
  readonly detail: string;

  constructor(status: number, detail: string) {
    super(detail);
    this.name = 'AgentDefinitionApiError';
    this.status = status;
    this.detail = detail;
  }
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
      const detail = (
        typeof payload === 'object'
        && payload !== null
        && 'detail' in payload
        && typeof payload.detail === 'string'
      ) ? payload.detail : (response.statusText || 'Request failed');
      throw new AgentDefinitionApiError(response.status, detail);
    }
    return response.json() as Promise<AgentDefinitionWorkbenchResponse>;
  }).finally(() => {
    workbenchRequest = null;
  });

  return workbenchRequest;
}
