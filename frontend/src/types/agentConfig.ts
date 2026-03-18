export interface GenieTool {
  type: 'genie';
  space_id: string;
  space_name: string;
  description?: string;
}

export interface MCPTool {
  type: 'mcp';
  server_uri: string;
  server_name: string;
  config?: Record<string, unknown>;
}

export type ToolEntry = GenieTool | MCPTool;

export interface AgentConfig {
  tools: ToolEntry[];
  slide_style_id: number | null;
  deck_prompt_id: number | null;
  system_prompt: string | null;
  slide_editing_instructions: string | null;
}

export interface AvailableTool {
  type: 'genie' | 'mcp';
  space_id?: string;
  space_name?: string;
  server_uri?: string;
  server_name?: string;
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
