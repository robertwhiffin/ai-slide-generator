export interface GenieTool {
  type: 'genie';
  space_id: string;
  space_name: string;
  description?: string;
  conversation_id?: string;
}

export interface MCPTool {
  type: 'mcp';
  connection_name: string;
  server_name: string;
  description?: string;
  config?: Record<string, unknown>;
}

export interface VectorIndexTool {
  type: 'vector_index';
  endpoint_name: string;
  index_name: string;
  description?: string;
  columns?: string[];
  num_results?: number;
}

export interface ModelEndpointTool {
  type: 'model_endpoint';
  endpoint_name: string;
  endpoint_type?: string;
  description?: string;
}

export interface AgentBricksTool {
  type: 'agent_bricks';
  endpoint_name: string;
  description?: string;
}

export type ToolType = 'genie' | 'mcp' | 'vector_index' | 'model_endpoint' | 'agent_bricks';

export type ToolEntry = GenieTool | MCPTool | VectorIndexTool | ModelEndpointTool | AgentBricksTool;

export interface AgentConfig {
  tools: ToolEntry[];
  slide_style_id: number | null;
  deck_prompt_id: number | null;
  system_prompt: string | null;
  slide_editing_instructions: string | null;
}

export interface DiscoveryItem {
  name: string;
  id: string;
  description?: string;
  metadata?: Record<string, unknown>;
}

export interface DiscoveryResponse {
  items: DiscoveryItem[];
}

export interface ColumnInfo {
  name: string;
  type?: string;
}

export interface ColumnDiscoveryResponse {
  columns: ColumnInfo[];
  source_table?: string;
  primary_key?: string;
}

export interface AvailableTool {
  type: ToolType;
  space_id?: string;
  space_name?: string;
  connection_name?: string;
  server_name?: string;
  endpoint_name?: string;
  index_name?: string;
  description?: string;
}

export interface ProfileSummary {
  id: number;
  name: string;
  description: string | null;
  is_default: boolean;
  agent_config: AgentConfig | null;
  created_at: string | null;
  created_by: string | null;
}

export const DEFAULT_AGENT_CONFIG: AgentConfig = {
  tools: [],
  slide_style_id: null,
  deck_prompt_id: null,
  system_prompt: null,
  slide_editing_instructions: null,
};

export const TOOL_TYPE_LABELS: Record<ToolType, string> = {
  genie: 'Genie Space',
  mcp: 'MCP Server',
  vector_index: 'Vector Index',
  model_endpoint: 'Model Endpoint',
  agent_bricks: 'Agent Bricks',
};

export const TOOL_TYPE_BADGE_LABELS: Record<ToolType, string> = {
  genie: 'GENIE',
  mcp: 'MCP',
  vector_index: 'VECTOR',
  model_endpoint: 'MODEL',
  agent_bricks: 'AGENT',
};

export const TOOL_TYPE_COLORS: Record<ToolType, string> = {
  genie: 'bg-blue-100 text-blue-800',
  mcp: 'bg-green-100 text-green-800',
  vector_index: 'bg-indigo-100 text-indigo-800',
  model_endpoint: 'bg-amber-100 text-amber-800',
  agent_bricks: 'bg-teal-100 text-teal-800',
};
