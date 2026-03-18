/**
 * ToolPicker — popover that lists available tools for adding to the agent config.
 *
 * Fetches from api.getAvailableTools() on open, shows loading / error / list states.
 */

import React, { useEffect, useState, useRef } from 'react';
import { Loader2, RefreshCw, X } from 'lucide-react';
import { api } from '../../services/api';
import type { AvailableTool, ToolEntry } from '../../types/agentConfig';

interface ToolPickerProps {
  isOpen: boolean;
  onClose: () => void;
  onSelect: (tool: ToolEntry) => void;
  /** Tools already in the config — used to grey-out duplicates. */
  existingTools: ToolEntry[];
}

/** Check whether a candidate tool is already present in the active list. */
function isAlreadyAdded(candidate: AvailableTool, existing: ToolEntry[]): boolean {
  return existing.some(t => {
    if (t.type !== candidate.type) return false;
    if (t.type === 'genie' && candidate.type === 'genie') {
      return t.space_id === candidate.space_id;
    }
    if (t.type === 'mcp' && candidate.type === 'mcp') {
      return t.server_uri === candidate.server_uri;
    }
    return false;
  });
}

/** Convert an AvailableTool into the ToolEntry shape expected by addTool(). */
function toToolEntry(tool: AvailableTool): ToolEntry {
  if (tool.type === 'genie') {
    return {
      type: 'genie',
      space_id: tool.space_id!,
      space_name: tool.space_name ?? tool.space_id!,
      description: tool.description,
    };
  }
  return {
    type: 'mcp',
    server_uri: tool.server_uri!,
    server_name: tool.server_name ?? tool.server_uri!,
    config: undefined,
  };
}

export const ToolPicker: React.FC<ToolPickerProps> = ({
  isOpen,
  onClose,
  onSelect,
  existingTools,
}) => {
  const [tools, setTools] = useState<AvailableTool[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const panelRef = useRef<HTMLDivElement>(null);

  const fetchTools = async () => {
    setLoading(true);
    setError(null);
    try {
      const result = await api.getAvailableTools();
      setTools(result);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load tools');
    } finally {
      setLoading(false);
    }
  };

  // Fetch tools every time the picker opens
  useEffect(() => {
    if (isOpen) {
      fetchTools();
    }
  }, [isOpen]);

  // Close on outside click
  useEffect(() => {
    if (!isOpen) return;
    const handler = (e: MouseEvent) => {
      if (panelRef.current && !panelRef.current.contains(e.target as Node)) {
        onClose();
      }
    };
    document.addEventListener('mousedown', handler);
    return () => document.removeEventListener('mousedown', handler);
  }, [isOpen, onClose]);

  if (!isOpen) return null;

  const displayName = (tool: AvailableTool): string => {
    if (tool.type === 'genie') return tool.space_name ?? tool.space_id ?? 'Genie Space';
    return tool.server_name ?? tool.server_uri ?? 'MCP Server';
  };

  return (
    <div
      ref={panelRef}
      className="absolute bottom-full left-0 mb-2 w-72 bg-white border border-gray-200 rounded-lg shadow-lg z-20"
      data-testid="tool-picker"
    >
      {/* Header */}
      <div className="flex items-center justify-between px-3 py-2 border-b border-gray-100">
        <span className="text-sm font-medium text-gray-700">Add Tool</span>
        <button
          onClick={onClose}
          className="p-0.5 text-gray-400 hover:text-gray-600 rounded transition-colors"
          aria-label="Close tool picker"
        >
          <X size={14} />
        </button>
      </div>

      {/* Body */}
      <div className="max-h-56 overflow-y-auto p-2">
        {loading && (
          <div className="flex items-center justify-center py-6 text-gray-500 text-sm gap-2">
            <Loader2 size={16} className="animate-spin" />
            Loading tools...
          </div>
        )}

        {error && (
          <div className="py-4 px-2 text-center">
            <p className="text-sm text-red-600 mb-2">{error}</p>
            <button
              onClick={fetchTools}
              className="inline-flex items-center gap-1 text-sm text-gray-600 hover:text-gray-800 transition-colors"
            >
              <RefreshCw size={14} />
              Retry
            </button>
          </div>
        )}

        {!loading && !error && tools.length === 0 && (
          <p className="text-sm text-gray-500 py-4 text-center">No tools available.</p>
        )}

        {!loading && !error && tools.map((tool, idx) => {
          const added = isAlreadyAdded(tool, existingTools);
          return (
            <button
              key={`${tool.type}-${tool.space_id ?? tool.server_uri ?? idx}`}
              disabled={added}
              onClick={() => {
                console.log('[ToolPicker] Tool clicked:', tool.type, tool.space_name || tool.server_name);
                const entry = toToolEntry(tool);
                console.log('[ToolPicker] Calling onSelect with:', JSON.stringify(entry));
                onSelect(entry);
                onClose();
              }}
              className={`w-full text-left px-3 py-2 rounded text-sm transition-colors ${
                added
                  ? 'text-gray-400 cursor-not-allowed'
                  : 'text-gray-700 hover:bg-gray-100'
              }`}
            >
              <div className="flex items-center gap-2">
                <span className="font-medium">{displayName(tool)}</span>
                <span className="text-xs text-gray-400 uppercase">{tool.type}</span>
                {added && <span className="text-xs text-gray-400 ml-auto">added</span>}
              </div>
              {tool.description && (
                <p className="text-xs text-gray-500 mt-0.5 line-clamp-2">{tool.description}</p>
              )}
            </button>
          );
        })}
      </div>
    </div>
  );
};
