/**
 * ToolPicker — category buttons for adding tools to the agent config.
 *
 * Renders a button per tool type. Clicking a button opens the corresponding
 * discovery panel inline.
 */

import React, { useState } from 'react';
import type { AvailableTool, GenieTool, VectorIndexTool, MCPTool, ModelEndpointTool, AgentBricksTool, ToolEntry, ToolType } from '../../types/agentConfig';
import { GenieDiscovery } from './tools/GenieDiscovery';
import { VectorIndexDiscovery } from './tools/VectorIndexDiscovery';
import { MCPDiscovery } from './tools/MCPDiscovery';
import { ModelEndpointDiscovery } from './tools/ModelEndpointDiscovery';
import { AgentBricksDiscovery } from './tools/AgentBricksDiscovery';

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const TOOL_CATEGORIES: { type: ToolType; label: string }[] = [
  { type: 'genie', label: '+ Genie Space' },
  { type: 'agent_bricks', label: '+ Agent Bricks' },
  { type: 'vector_index', label: '+ Vector Index' },
  { type: 'mcp', label: '+ MCP Server' },
  { type: 'model_endpoint', label: '+ Model Endpoint' },
];

// ---------------------------------------------------------------------------
// Props
// ---------------------------------------------------------------------------

interface ToolPickerProps {
  onSelect: (tool: ToolEntry) => void;
  onPreview: (tool: AvailableTool) => void;
  existingTools: ToolEntry[];
}

// ---------------------------------------------------------------------------
// Main component
// ---------------------------------------------------------------------------

export const ToolPicker: React.FC<ToolPickerProps> = ({
  onSelect,
  onPreview,
  existingTools,
}) => {
  const [activeCategory, setActiveCategory] = useState<ToolType | null>(null);

  const handleButtonClick = (type: ToolType) => {
    setActiveCategory(prev => (prev === type ? null : type));
  };

  const handleClose = () => {
    setActiveCategory(null);
  };

  return (
    <div className="relative flex flex-wrap items-center gap-1.5">
      {TOOL_CATEGORIES.map(({ type, label }) => (
        <button
          key={type}
          onClick={() => handleButtonClick(type)}
          className={`inline-flex items-center gap-0.5 px-2 py-0.5 rounded-full text-xs border border-dashed transition-colors ${
            activeCategory === type
              ? 'border-blue-400 text-blue-600 bg-blue-50'
              : 'border-gray-300 text-gray-500 hover:border-gray-400 hover:text-gray-700'
          }`}
          data-testid={`add-tool-${type}`}
        >
          {label}
        </button>
      ))}

      {/* Discovery panels */}
      {activeCategory === 'genie' && (
        <GenieDiscovery
          onSelect={onSelect as (tool: GenieTool) => void}
          onPreview={onPreview}
          onClose={handleClose}
          existingTools={existingTools}
        />
      )}
      {activeCategory === 'vector_index' && (
        <VectorIndexDiscovery
          onSelect={onSelect as (tool: VectorIndexTool) => void}
          onClose={handleClose}
          existingTools={existingTools}
        />
      )}
      {activeCategory === 'mcp' && (
        <MCPDiscovery
          onSelect={onSelect as (tool: MCPTool) => void}
          onClose={handleClose}
          existingTools={existingTools}
        />
      )}
      {activeCategory === 'model_endpoint' && (
        <ModelEndpointDiscovery
          onSelect={onSelect as (tool: ModelEndpointTool) => void}
          onClose={handleClose}
          existingTools={existingTools}
        />
      )}
      {activeCategory === 'agent_bricks' && (
        <AgentBricksDiscovery
          onSelect={onSelect as (tool: AgentBricksTool) => void}
          onClose={handleClose}
          existingTools={existingTools}
        />
      )}
    </div>
  );
};
