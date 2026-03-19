import type { AvailableTool, GenieTool, MCPTool, ToolEntry } from '../../types/agentConfig';

export function toGenieToolEntry(tool: AvailableTool): GenieTool {
  return {
    type: 'genie',
    space_id: tool.space_id!,
    space_name: tool.space_name ?? tool.space_id!,
    description: tool.description,
  };
}

export function toMcpToolEntry(tool: AvailableTool): MCPTool {
  return {
    type: 'mcp',
    server_uri: tool.server_uri!,
    server_name: tool.server_name ?? tool.server_uri!,
    config: undefined,
  };
}

export function toToolEntry(tool: AvailableTool): ToolEntry {
  if (tool.type === 'genie') {
    return toGenieToolEntry(tool);
  }
  return toMcpToolEntry(tool);
}
