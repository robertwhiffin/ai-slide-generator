/**
 * ToolPicker — dropdown with search for adding Genie spaces to the agent config.
 *
 * Fetches all available tools on open, then filters client-side as the user types.
 * Positioned below the trigger button (not above) to avoid going off-screen.
 */

import React, { useEffect, useState, useRef } from 'react';
import { Loader2, RefreshCw, Search, X } from 'lucide-react';
import { api } from '../../services/api';
import type { AvailableTool, ToolEntry } from '../../types/agentConfig';

interface ToolPickerProps {
  isOpen: boolean;
  onClose: () => void;
  onSelect: (tool: ToolEntry) => void;
  existingTools: ToolEntry[];
}

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
  const [allTools, setAllTools] = useState<AvailableTool[]>([]);
  const [query, setQuery] = useState('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const panelRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  const fetchTools = async () => {
    setLoading(true);
    setError(null);
    try {
      const result = await api.getAvailableTools();
      setAllTools(result);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load Genie spaces');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    if (isOpen) {
      setQuery('');
      fetchTools();
      // Focus the search input after a tick
      setTimeout(() => inputRef.current?.focus(), 50);
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

  // Client-side filter
  const lowerQuery = query.toLowerCase();
  const filtered = allTools.filter(tool => {
    const name = displayName(tool).toLowerCase();
    const desc = (tool.description ?? '').toLowerCase();
    return name.includes(lowerQuery) || desc.includes(lowerQuery);
  });

  return (
    <div
      ref={panelRef}
      className="absolute top-full left-0 mt-1 w-80 bg-white border border-gray-200 rounded-lg shadow-lg z-20"
      data-testid="tool-picker"
    >
      {/* Header with search */}
      <div className="px-3 pt-3 pb-2">
        <div className="flex items-center justify-between mb-2">
          <span className="text-sm font-medium text-gray-700">Add Genie Space</span>
          <button
            onClick={onClose}
            className="p-0.5 text-gray-400 hover:text-gray-600 rounded transition-colors"
            aria-label="Close"
          >
            <X size={14} />
          </button>
        </div>
        <div className="relative">
          <Search size={14} className="absolute left-2.5 top-1/2 -translate-y-1/2 text-gray-400" />
          <input
            ref={inputRef}
            type="text"
            placeholder="Search Genie spaces..."
            value={query}
            onChange={e => setQuery(e.target.value)}
            className="w-full pl-8 pr-3 py-1.5 border border-gray-300 rounded text-sm focus:outline-none focus:ring-1 focus:ring-blue-500 bg-white"
          />
        </div>
      </div>

      {/* Results */}
      <div className="max-h-48 overflow-y-auto px-2 pb-2">
        {loading && (
          <div className="flex items-center justify-center py-6 text-gray-500 text-sm gap-2">
            <Loader2 size={16} className="animate-spin" />
            Loading...
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

        {!loading && !error && filtered.length === 0 && (
          <p className="text-sm text-gray-500 py-4 text-center">
            {query ? 'No matching Genie spaces.' : 'No Genie spaces available.'}
          </p>
        )}

        {!loading && !error && filtered.map((tool, idx) => {
          const added = isAlreadyAdded(tool, existingTools);
          return (
            <button
              key={`${tool.type}-${tool.space_id ?? tool.server_uri ?? idx}`}
              disabled={added}
              onClick={() => {
                onSelect(toToolEntry(tool));
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
