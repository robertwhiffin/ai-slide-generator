import type {
  AvailableTool,
  GenieTool,
  MCPTool,
  VectorIndexTool,
  ModelEndpointTool,
  AgentBricksTool,
  ToolEntry,
} from '../../types/agentConfig';

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
    connection_name: tool.connection_name!,
    server_name: tool.server_name ?? tool.connection_name!,
    config: undefined,
  };
}

export function toVectorIndexToolEntry(tool: AvailableTool): VectorIndexTool {
  return {
    type: 'vector_index',
    endpoint_name: tool.endpoint_name!,
    index_name: tool.index_name!,
    description: tool.description,
  };
}

export function toModelEndpointToolEntry(tool: AvailableTool): ModelEndpointTool {
  return {
    type: 'model_endpoint',
    endpoint_name: tool.endpoint_name!,
    description: tool.description,
  };
}

export function toAgentBricksToolEntry(tool: AvailableTool): AgentBricksTool {
  return {
    type: 'agent_bricks',
    endpoint_name: tool.endpoint_name!,
    description: tool.description,
  };
}

export function toToolEntry(tool: AvailableTool): ToolEntry {
  switch (tool.type) {
    case 'genie':
      return toGenieToolEntry(tool);
    case 'mcp':
      return toMcpToolEntry(tool);
    case 'vector_index':
      return toVectorIndexToolEntry(tool);
    case 'model_endpoint':
      return toModelEndpointToolEntry(tool);
    case 'agent_bricks':
      return toAgentBricksToolEntry(tool);
  }
}
