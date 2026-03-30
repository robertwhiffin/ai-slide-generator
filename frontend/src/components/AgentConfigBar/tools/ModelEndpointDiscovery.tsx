/**
 * ModelEndpointDiscovery — inline panel for searching and selecting
 * non-agent Model Serving endpoints.
 */

import React, { useEffect, useState, useRef } from 'react';
import { ChevronLeft, Loader2, RefreshCw, Search, X } from 'lucide-react';
import { api } from '../../../services/api';
import type { DiscoveryItem, ModelEndpointTool, ToolEntry } from '../../../types/agentConfig';

interface ModelEndpointDiscoveryProps {
  onSelect: (tool: ModelEndpointTool) => void;
  onClose: () => void;
  existingTools: ToolEntry[];
}

export const ModelEndpointDiscovery: React.FC<ModelEndpointDiscoveryProps> = ({
  onSelect,
  onClose,
  existingTools,
}) => {
  const panelRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  const [endpoints, setEndpoints] = useState<DiscoveryItem[]>([]);
  const [query, setQuery] = useState('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Detail panel state
  const [selected, setSelected] = useState<DiscoveryItem | null>(null);
  const [description, setDescription] = useState('');

  useEffect(() => {
    fetchEndpoints();
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

  const fetchEndpoints = async () => {
    setLoading(true);
    setError(null);
    try {
      const result = await api.discoverModelEndpoints();
      setEndpoints(result.items);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load model endpoints');
    } finally {
      setLoading(false);
    }
  };

  const isAlreadyAdded = (endpointId: string): boolean => {
    return existingTools.some(
      t => t.type === 'model_endpoint' && t.endpoint_name === endpointId,
    );
  };

  const handleSelect = (item: DiscoveryItem) => {
    setSelected(item);
    setDescription(item.description ?? '');
  };

  const handleBack = () => {
    setSelected(null);
    setDescription('');
  };

  const handleSave = () => {
    if (!selected) return;
    const tool: ModelEndpointTool = {
      type: 'model_endpoint',
      endpoint_name: selected.id,
      endpoint_type: (selected.metadata?.endpoint_type as string) ?? undefined,
      description: description || undefined,
    };
    onSelect(tool);
    onClose();
  };

  const getTypeBadge = (item: DiscoveryItem): { label: string; className: string } | null => {
    const epType = item.metadata?.endpoint_type as string | undefined;
    if (!epType) return null;
    if (epType.toLowerCase().includes('foundation')) {
      return { label: 'Foundation', className: 'bg-purple-100 text-purple-700' };
    }
    return { label: 'Custom', className: 'bg-gray-100 text-gray-600' };
  };

  const lowerQuery = query.toLowerCase();
  const filtered = endpoints.filter(ep =>
    ep.name.toLowerCase().includes(lowerQuery) ||
    (ep.description ?? '').toLowerCase().includes(lowerQuery),
  );

  return (
    <div
      ref={panelRef}
      className="absolute top-full left-0 mt-1 w-80 bg-white border border-gray-200 rounded-lg shadow-lg z-20"
      data-testid="model-endpoint-discovery"
    >
      {/* Header */}
      <div className="px-3 pt-3 pb-2">
        <div className="flex items-center justify-between mb-2">
          <div className="flex items-center gap-1.5">
            {selected && (
              <button
                onClick={handleBack}
                className="p-0.5 text-gray-400 hover:text-gray-600 rounded transition-colors"
                aria-label="Back"
              >
                <ChevronLeft size={14} />
              </button>
            )}
            <span className="text-sm font-medium text-gray-700">
              {selected ? 'Configure Model Endpoint' : 'Add Model Endpoint'}
            </span>
          </div>
          <button
            onClick={onClose}
            className="p-0.5 text-gray-400 hover:text-gray-600 rounded transition-colors"
            aria-label="Close"
          >
            <X size={14} />
          </button>
        </div>

        {/* Search input (list view only) */}
        {!selected && (
          <div className="relative">
            <Search size={14} className="absolute left-2.5 top-1/2 -translate-y-1/2 text-gray-400" />
            <input
              ref={inputRef}
              type="text"
              placeholder="Search model endpoints..."
              value={query}
              onChange={e => setQuery(e.target.value)}
              className="w-full pl-8 pr-3 py-1.5 border border-gray-300 rounded text-sm focus:outline-none focus:ring-1 focus:ring-blue-500 bg-white"
            />
          </div>
        )}
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
              onClick={fetchEndpoints}
              className="inline-flex items-center gap-1 text-sm text-gray-600 hover:text-gray-800 transition-colors"
            >
              <RefreshCw size={14} />
              Retry
            </button>
          </div>
        )}

        {/* List view */}
        {!loading && !error && !selected && (
          <>
            {filtered.length === 0 && (
              <p className="text-sm text-gray-500 py-4 text-center">
                {query ? 'No matching endpoints.' : 'No model endpoints available.'}
              </p>
            )}
            {filtered.map((item, idx) => {
              const added = isAlreadyAdded(item.id);
              const badge = getTypeBadge(item);
              return (
                <button
                  key={`model-${item.id ?? idx}`}
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
                    {badge && (
                      <span className={`text-xs px-1.5 py-0.5 rounded ${badge.className}`}>
                        {badge.label}
                      </span>
                    )}
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

        {/* Detail view */}
        {!loading && !error && selected && (
          <div className="px-2 pb-1">
            <div className="mb-3">
              <label className="block text-xs text-gray-500 mb-1">Endpoint</label>
              <div className="flex items-center gap-2">
                <span className="text-sm text-gray-700 bg-gray-50 rounded px-2 py-1.5 border border-gray-200 flex-1">
                  {selected.name}
                </span>
                {(() => {
                  const badge = getTypeBadge(selected);
                  return badge ? (
                    <span className={`text-xs px-1.5 py-0.5 rounded ${badge.className}`}>
                      {badge.label}
                    </span>
                  ) : null;
                })()}
              </div>
            </div>

            <div className="mb-3">
              <label className="block text-xs text-gray-500 mb-1">Description (optional)</label>
              <textarea
                value={description}
                onChange={e => setDescription(e.target.value)}
                placeholder="Describe what this model endpoint does..."
                className="w-full border border-gray-300 rounded text-sm p-2 focus:outline-none focus:ring-1 focus:ring-blue-500 resize-none"
                rows={2}
              />
            </div>

            <button
              onClick={handleSave}
              className="w-full px-3 py-1.5 rounded text-sm bg-blue-600 text-white hover:bg-blue-700 transition-colors"
            >
              Save & Add
            </button>
          </div>
        )}
      </div>
    </div>
  );
};
