/**
 * ToolPicker — category buttons for adding tools to the agent config.
 *
 * Renders a button per tool type. Clicking a button opens the corresponding
 * discovery panel inline (currently only Genie is implemented; the rest show
 * a "Coming soon" placeholder until Task 7).
 */

import React, { useState, useRef, useEffect } from 'react';
import { X } from 'lucide-react';
import type { AvailableTool, GenieTool, ToolEntry, ToolType } from '../../types/agentConfig';
import { GenieDiscovery } from './tools/GenieDiscovery';

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
// Placeholder panel for types not yet implemented
// ---------------------------------------------------------------------------

const ComingSoonPanel: React.FC<{ label: string; onClose: () => void }> = ({ label, onClose }) => {
  const panelRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const handler = (e: MouseEvent) => {
      if (panelRef.current && !panelRef.current.contains(e.target as Node)) {
        onClose();
      }
    };
    document.addEventListener('mousedown', handler);
    return () => document.removeEventListener('mousedown', handler);
  }, [onClose]);

  return (
    <div
      ref={panelRef}
      className="absolute top-full left-0 mt-1 w-64 bg-white border border-gray-200 rounded-lg shadow-lg z-20 p-4"
      data-testid="coming-soon-panel"
    >
      <div className="flex items-center justify-between mb-2">
        <span className="text-sm font-medium text-gray-700">{label}</span>
        <button
          onClick={onClose}
          className="p-0.5 text-gray-400 hover:text-gray-600 rounded transition-colors"
          aria-label="Close"
        >
          <X size={14} />
        </button>
      </div>
      <p className="text-sm text-gray-500">Coming soon.</p>
    </div>
  );
};

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

      {activeCategory && activeCategory !== 'genie' && (
        <ComingSoonPanel
          label={TOOL_CATEGORIES.find(c => c.type === activeCategory)?.label ?? ''}
          onClose={handleClose}
        />
      )}
    </div>
  );
};
