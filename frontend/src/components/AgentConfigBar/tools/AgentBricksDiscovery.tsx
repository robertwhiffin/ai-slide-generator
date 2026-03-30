/**
 * AgentBricksDiscovery — inline dropdown panel for searching and selecting
 * agent-type serving endpoints (Agent Bricks).
 *
 * When the user selects an item, the dropdown closes and calls `onPreview`
 * so that AgentConfigBar can open the full-width ToolDetailPanel.
 */

import React, { useEffect, useState, useRef } from 'react';
import { Loader2, RefreshCw, Search, X } from 'lucide-react';
import { api } from '../../../services/api';
import type { DiscoveryItem, AgentBricksTool, ToolEntry } from '../../../types/agentConfig';
import type { AgentBricksPreview } from '../ToolDetailPanel';

interface AgentBricksDiscoveryProps {
  onSelect: (tool: AgentBricksTool) => void;
  onPreview: (preview: AgentBricksPreview) => void;
  onClose: () => void;
  existingTools: ToolEntry[];
}

export const AgentBricksDiscovery: React.FC<AgentBricksDiscoveryProps> = ({
  onPreview,
  onClose,
  existingTools,
}) => {
  const panelRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  const [agents, setAgents] = useState<DiscoveryItem[]>([]);
  const [query, setQuery] = useState('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetchAgents();
    setTimeout(() => inputRef.current?.focus(), 50);
  }, []);

  // Close on outside click
  useEffect(() => {
    const handler = (e: MouseEvent) => {
      if (panelRef.current && !panelRef.current.contains(e.target as Node)) {
        onClose();
      }
    };
    document.addEventListener('mousedown', handler);
    return () => document.removeEventListener('mousedown', handler);
  }, [onClose]);

  const fetchAgents = async () => {
    setLoading(true);
    setError(null);
    try {
      const result = await api.discoverAgentBricks();
      setAgents(result.items);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load agent bricks');
    } finally {
      setLoading(false);
    }
  };

  const isAlreadyAdded = (endpointId: string): boolean => {
    return existingTools.some(
      t => t.type === 'agent_bricks' && t.endpoint_name === endpointId,
    );
  };

  const handleSelect = (item: DiscoveryItem) => {
    onPreview({
      toolType: 'agent_bricks',
      name: item.name,
      endpointName: item.id,
      description: item.description,
    });
    onClose();
  };

  const lowerQuery = query.toLowerCase();
  const filtered = agents.filter(a =>
    a.name.toLowerCase().includes(lowerQuery) ||
    (a.description ?? '').toLowerCase().includes(lowerQuery),
  );

  return (
    <div
      ref={panelRef}
      className="absolute top-full left-0 mt-1 w-80 bg-white border border-gray-200 rounded-lg shadow-lg z-20"
      data-testid="agent-bricks-discovery"
    >
      {/* Header */}
      <div className="px-3 pt-3 pb-2">
        <div className="flex items-center justify-between mb-2">
          <span className="text-sm font-medium text-gray-700">Add Agent Brick</span>
          <button
            onClick={onClose}
            className="p-0.5 text-gray-400 hover:text-gray-600 rounded transition-colors"
            aria-label="Close"
          >
            <X size={14} />
          </button>
        </div>

        {/* Search input */}
        <div className="relative">
          <Search size={14} className="absolute left-2.5 top-1/2 -translate-y-1/2 text-gray-400" />
          <input
            ref={inputRef}
            type="text"
            placeholder="Search agent bricks..."
            value={query}
            onChange={e => setQuery(e.target.value)}
            className="w-full pl-8 pr-3 py-1.5 border border-gray-300 rounded text-sm focus:outline-none focus:ring-1 focus:ring-blue-500 bg-white"
          />
        </div>
      </div>

      {/* Content */}
      <div className="max-h-60 overflow-y-auto px-2 pb-2">
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
              onClick={fetchAgents}
              className="inline-flex items-center gap-1 text-sm text-gray-600 hover:text-gray-800 transition-colors"
            >
              <RefreshCw size={14} />
              Retry
            </button>
          </div>
        )}

        {!loading && !error && (
          <>
            {filtered.length === 0 && (
              <p className="text-sm text-gray-500 py-4 text-center">
                {query ? 'No matching agent bricks.' : 'No agent bricks available.'}
              </p>
            )}
            {filtered.map((item, idx) => {
              const added = isAlreadyAdded(item.id);
              return (
                <button
                  key={`agent-${item.id ?? idx}`}
                  disabled={added}
                  onClick={() => handleSelect(item)}
                  className={`w-full text-left px-3 py-2 rounded text-sm transition-colors ${
                    added
                      ? 'text-gray-400 cursor-not-allowed'
                      : 'text-gray-700 hover:bg-gray-100'
                  }`}
                >
                  <div className="flex items-center gap-2">
                    <span className="font-medium">{item.name}</span>
                    {added && <span className="text-xs text-gray-400 ml-auto">added</span>}
                  </div>
                  {item.description && (
                    <p className="text-xs text-gray-500 mt-0.5 line-clamp-2">{item.description}</p>
                  )}
                </button>
              );
            })}
          </>
        )}
      </div>
    </div>
  );
};
