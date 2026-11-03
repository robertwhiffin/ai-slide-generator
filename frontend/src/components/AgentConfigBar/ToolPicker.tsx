/**
 * ToolPicker — the Tools row's pills for adding tools to the agent config.
 *
 * The row is "+ Genie One", then one pill per enabled admin-registered AI Gateway
 * connection (both add in one click), then an "Other tools" toggle that reveals a
 * pill per remaining tool type. Clicking one of those opens its discovery panel inline.
 */

import React, { useEffect, useState } from 'react';
import { ChevronDown, ChevronUp } from 'lucide-react';
import { api } from '../../services/api';
import type { AvailableTool, GatewayItem, GenieTool, VectorIndexTool, MCPTool, ModelEndpointTool, AgentBricksTool, ToolEntry, ToolType } from '../../types/agentConfig';
import type { ToolPreviewData } from './ToolDetailPanel';
import { GenieDiscovery } from './tools/GenieDiscovery';
import { VectorIndexDiscovery } from './tools/VectorIndexDiscovery';
import { MCPDiscovery } from './tools/MCPDiscovery';
import { ModelEndpointDiscovery } from './tools/ModelEndpointDiscovery';
import { AgentBricksDiscovery } from './tools/AgentBricksDiscovery';

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

// Behind the "Other tools" toggle, in this order.
const OTHER_TOOL_CATEGORIES: { type: ToolType; label: string }[] = [
  { type: 'genie', label: '+ Genie Agent' },
  { type: 'agent_bricks', label: '+ Agent Bricks' },
  { type: 'vector_index', label: '+ Vector Index' },
  { type: 'mcp', label: '+ MCP Server' },
  { type: 'model_endpoint', label: '+ Model Endpoint' },
];

const PILL_CLASS = 'inline-flex items-center gap-0.5 px-2 py-0.5 rounded-full text-xs border border-dashed transition-colors';
const PILL_IDLE_CLASS = 'border-gray-300 text-gray-500 hover:border-gray-400 hover:text-gray-700';
const PILL_ACTIVE_CLASS = 'border-blue-400 text-blue-600 bg-blue-50';

// ---------------------------------------------------------------------------
// Props
// ---------------------------------------------------------------------------

interface ToolPickerProps {
  onSelect: (tool: ToolEntry) => void;
  onPreview: (tool: AvailableTool) => void;
  onToolPreview: (preview: ToolPreviewData) => void;
  existingTools: ToolEntry[];
}

// ---------------------------------------------------------------------------
// Main component
// ---------------------------------------------------------------------------

export const ToolPicker: React.FC<ToolPickerProps> = ({
  onSelect,
  onPreview,
  onToolPreview,
  existingTools,
}) => {
  const [activeCategory, setActiveCategory] = useState<ToolType | null>(null);
  const [gatewayItems, setGatewayItems] = useState<GatewayItem[]>([]);
  const [showOtherTools, setShowOtherTools] = useState(false);

  useEffect(() => {
    let cancelled = false;
    api.discoverGatewayConnections()
      .then(items => { if (!cancelled) setGatewayItems(items); })
      .catch(() => { /* No connection pills; the rest of the row still works. */ });
    return () => { cancelled = true; };
  }, []);

  const hasGenieOne = existingTools.some(t => t.type === 'genie_one');
  const gatewayPills = gatewayItems.filter(
    item => !existingTools.some(t => t.type === 'gateway_mcp' && t.service_name === item.service_name),
  );

  // Genie One and Gateway connections are one-click: no discovery panel.
  const handleSelectGenieOne = () => {
    setActiveCategory(null);
    onSelect({ type: 'genie_one' });
  };

  const handleSelectGateway = (item: GatewayItem) => {
    setActiveCategory(null);
    onSelect({ type: 'gateway_mcp', service_name: item.service_name, display_name: item.display_name });
  };

  const handleButtonClick = (type: ToolType) => {
    setActiveCategory(prev => (prev === type ? null : type));
  };

  const handleClose = () => {
    setActiveCategory(null);
  };

  return (
    <div className="relative flex flex-wrap items-center gap-1.5">
      {!hasGenieOne && (
        <button
          onClick={handleSelectGenieOne}
          className={`${PILL_CLASS} ${PILL_IDLE_CLASS}`}
          data-testid="add-tool-genie_one"
        >
          + Genie One
        </button>
      )}
      {gatewayPills.map(item => (
        <button
          key={item.service_name}
          onClick={() => handleSelectGateway(item)}
          title={item.description ?? undefined}
          className={`${PILL_CLASS} ${PILL_IDLE_CLASS}`}
          data-testid={`add-tool-gateway-${item.service_name}`}
        >
          {`+ ${item.display_name}`}
        </button>
      ))}
      <button
        onClick={() => setShowOtherTools(prev => !prev)}
        aria-expanded={showOtherTools}
        className={`${PILL_CLASS} ${showOtherTools ? PILL_ACTIVE_CLASS : PILL_IDLE_CLASS}`}
        data-testid="toggle-other-tools"
      >
        Other tools
        {showOtherTools ? <ChevronUp size={12} /> : <ChevronDown size={12} />}
      </button>
      {showOtherTools && OTHER_TOOL_CATEGORIES.map(({ type, label }) => (
        <button
          key={type}
          onClick={() => handleButtonClick(type)}
          className={`${PILL_CLASS} ${activeCategory === type ? PILL_ACTIVE_CLASS : PILL_IDLE_CLASS}`}
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
          onPreview={onToolPreview}
          onClose={handleClose}
          existingTools={existingTools}
        />
      )}
      {activeCategory === 'mcp' && (
        <MCPDiscovery
          onSelect={onSelect as (tool: MCPTool) => void}
          onPreview={onToolPreview}
          onClose={handleClose}
          existingTools={existingTools}
        />
      )}
      {activeCategory === 'model_endpoint' && (
        <ModelEndpointDiscovery
          onSelect={onSelect as (tool: ModelEndpointTool) => void}
          onPreview={onToolPreview}
          onClose={handleClose}
          existingTools={existingTools}
        />
      )}
      {activeCategory === 'agent_bricks' && (
        <AgentBricksDiscovery
          onSelect={onSelect as (tool: AgentBricksTool) => void}
          onPreview={onToolPreview}
          onClose={handleClose}
          existingTools={existingTools}
        />
      )}
    </div>
  );
};
