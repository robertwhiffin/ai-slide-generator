/**
 * ToolDetailPanel — full-width detail/configuration panel for non-Genie tool types.
 *
 * Renders above the Tools row (at the AgentConfigBar level) when a user selects
 * an item from any discovery dropdown. Mirrors the layout and styling of
 * GenieDetailPanel for a consistent UX.
 */

import React, { useState, useEffect, useRef } from 'react';
import { X } from 'lucide-react';
import { TOOL_TYPE_BADGE_LABELS, TOOL_TYPE_COLORS } from '../../types/agentConfig';
import type {
  ToolType,
  ToolEntry,
  AgentBricksTool,
  MCPTool,
  ModelEndpointTool,
  VectorIndexTool,
  ColumnInfo,
} from '../../types/agentConfig';

// ---------------------------------------------------------------------------
// Preview data — discriminated union that carries all info needed to render
// the detail panel and produce a ToolEntry on save.
// ---------------------------------------------------------------------------

export interface AgentBricksPreview {
  toolType: 'agent_bricks';
  name: string;
  endpointName: string;
  description?: string;
}

export interface MCPPreview {
  toolType: 'mcp';
  name: string;
  connectionName: string;
  serverName: string;
  description?: string;
}

export interface ModelEndpointPreview {
  toolType: 'model_endpoint';
  name: string;
  endpointName: string;
  endpointType?: string;
  description?: string;
}

export interface VectorIndexPreview {
  toolType: 'vector_index';
  name: string;
  endpointName: string;
  indexName: string;
  columns: ColumnInfo[];
  description?: string;
}

export type ToolPreviewData =
  | AgentBricksPreview
  | MCPPreview
  | ModelEndpointPreview
  | VectorIndexPreview;

// ---------------------------------------------------------------------------
// Props
// ---------------------------------------------------------------------------

interface ToolDetailPanelProps {
  preview: ToolPreviewData;
  mode: 'add' | 'edit';
  onSave: (tool: ToolEntry) => void;
  onCancel: () => void;
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export default function ToolDetailPanel({ preview, mode, onSave, onCancel }: ToolDetailPanelProps) {
  const [description, setDescription] = useState(preview.description ?? '');
  const [serverName, setServerName] = useState(
    preview.toolType === 'mcp' ? preview.serverName : '',
  );
  const [selectedColumns, setSelectedColumns] = useState<Set<string>>(
    preview.toolType === 'vector_index'
      ? new Set(preview.columns.map(c => c.name))
      : new Set(),
  );
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    textareaRef.current?.focus();
  }, []);

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Escape') {
      e.stopPropagation();
      onCancel();
    }
  };

  const toggleColumn = (colName: string) => {
    setSelectedColumns(prev => {
      const next = new Set(prev);
      if (next.has(colName)) {
        next.delete(colName);
      } else {
        next.add(colName);
      }
      return next;
    });
  };

  const handleSave = () => {
    let tool: ToolEntry;

    switch (preview.toolType) {
      case 'agent_bricks': {
        const t: AgentBricksTool = {
          type: 'agent_bricks',
          endpoint_name: preview.endpointName,
          description: description || undefined,
        };
        tool = t;
        break;
      }
      case 'mcp': {
        const t: MCPTool = {
          type: 'mcp',
          connection_name: preview.connectionName,
          server_name: serverName || preview.name,
          description: description || undefined,
        };
        tool = t;
        break;
      }
      case 'model_endpoint': {
        const t: ModelEndpointTool = {
          type: 'model_endpoint',
          endpoint_name: preview.endpointName,
          endpoint_type: preview.endpointType,
          description: description || undefined,
        };
        tool = t;
        break;
      }
      case 'vector_index': {
        const allSelected = selectedColumns.size === preview.columns.length;
        const t: VectorIndexTool = {
          type: 'vector_index',
          endpoint_name: preview.endpointName,
          index_name: preview.indexName,
          columns: allSelected ? undefined : Array.from(selectedColumns),
          description: description || undefined,
        };
        tool = t;
        break;
      }
    }

    onSave(tool);
  };

  const colorClasses = TOOL_TYPE_COLORS[preview.toolType as ToolType];
  const badgeLabel = TOOL_TYPE_BADGE_LABELS[preview.toolType as ToolType];

  // Build read-only info rows based on tool type
  const infoRows: { label: string; value: string }[] = [];
  switch (preview.toolType) {
    case 'agent_bricks':
      infoRows.push({ label: 'Endpoint', value: preview.endpointName });
      break;
    case 'mcp':
      infoRows.push({ label: 'Connection', value: preview.connectionName });
      break;
    case 'model_endpoint':
      infoRows.push({ label: 'Endpoint', value: preview.endpointName });
      if (preview.endpointType) {
        infoRows.push({ label: 'Type', value: preview.endpointType });
      }
      break;
    case 'vector_index':
      infoRows.push({ label: 'Endpoint', value: preview.endpointName });
      infoRows.push({ label: 'Index', value: preview.indexName });
      break;
  }

  // For model endpoints, show a Foundation/Custom badge
  const endpointTypeBadge =
    preview.toolType === 'model_endpoint' && preview.endpointType
      ? preview.endpointType.toLowerCase().includes('foundation')
        ? { label: 'Foundation', className: 'bg-purple-100 text-purple-700' }
        : { label: 'Custom', className: 'bg-gray-100 text-gray-600' }
      : null;

  const isSaveDisabled =
    preview.toolType === 'vector_index' && selectedColumns.size === 0;

  return (
    <div
      data-testid="tool-detail-panel"
      className="border rounded bg-gray-50 p-4"
      onKeyDown={handleKeyDown}
    >
      {/* Header */}
      <div className="flex items-center justify-between mb-3">
        <div className="flex items-center gap-2">
          <span className={`uppercase text-[10px] font-bold px-1.5 py-0.5 rounded ${colorClasses}`}>
            {badgeLabel}
          </span>
          <span className="font-semibold text-sm">{preview.name}</span>
          {endpointTypeBadge && (
            <span className={`text-xs px-1.5 py-0.5 rounded ${endpointTypeBadge.className}`}>
              {endpointTypeBadge.label}
            </span>
          )}
        </div>
        <button
          onClick={onCancel}
          className="text-gray-400 hover:text-gray-600"
          aria-label="Close"
        >
          <X size={16} />
        </button>
      </div>

      {/* Read-only identity fields */}
      {infoRows.map(({ label, value }) => (
        <div key={label} className="mb-3">
          <label className="block text-sm text-gray-500 mb-1">{label}</label>
          <div className="font-mono text-sm text-gray-700">{value}</div>
        </div>
      ))}

      {/* MCP: editable display name */}
      {preview.toolType === 'mcp' && (
        <div className="mb-3">
          <label className="block text-sm text-gray-500 mb-1">Display Name</label>
          <input
            type="text"
            value={serverName}
            onChange={e => setServerName(e.target.value)}
            className="w-full border rounded px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-400"
          />
        </div>
      )}

      {/* Vector Index: column checkboxes */}
      {preview.toolType === 'vector_index' && preview.columns.length > 0 && (
        <div className="mb-3">
          <p className="text-sm text-gray-500 mb-1.5">Select columns to include:</p>
          <div className="max-h-40 overflow-y-auto border border-gray-200 rounded p-2">
            {preview.columns.map(col => (
              <label
                key={col.name}
                className="flex items-center gap-2 py-0.5 text-sm text-gray-700 cursor-pointer hover:bg-gray-50 rounded px-1"
              >
                <input
                  type="checkbox"
                  checked={selectedColumns.has(col.name)}
                  onChange={() => toggleColumn(col.name)}
                  className="rounded border-gray-300 text-blue-600 focus:ring-blue-500"
                />
                <span>{col.name}</span>
                {col.type && (
                  <span className="text-xs text-gray-400 ml-auto">{col.type}</span>
                )}
              </label>
            ))}
          </div>
        </div>
      )}

      {/* Editable description */}
      <div className="mb-4">
        <div className="flex items-baseline justify-between mb-1">
          <label className="text-sm text-gray-500">Description</label>
          <span className="text-xs text-gray-400">
            Used by the agent to decide when to use this tool
          </span>
        </div>
        <textarea
          ref={textareaRef}
          value={description}
          onChange={e => setDescription(e.target.value)}
          placeholder="Describe when the agent should use this tool..."
          className="w-full border rounded px-3 py-2 text-sm resize-y min-h-[80px] focus:outline-none focus:ring-2 focus:ring-blue-400"
        />
      </div>

      {/* Buttons */}
      <div className="flex items-center justify-end gap-2">
        <button
          onClick={onCancel}
          className="px-3 py-1.5 text-sm text-gray-600 hover:text-gray-800"
        >
          Cancel
        </button>
        <button
          onClick={handleSave}
          disabled={isSaveDisabled}
          className="px-3 py-1.5 text-sm bg-blue-500 text-white rounded hover:bg-blue-600 disabled:opacity-50 disabled:cursor-not-allowed"
        >
          {mode === 'add' ? 'Save & Add' : 'Save'}
        </button>
      </div>
    </div>
  );
}
