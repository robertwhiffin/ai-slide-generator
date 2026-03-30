/**
 * VectorIndexDiscovery — progressive 3-step inline panel for selecting a
 * Vector Search endpoint, index, and columns.
 *
 * Step 1: Pick endpoint
 * Step 2: Pick index
 * Step 3: Configure columns & description, then Save & Add
 */

import React, { useEffect, useState, useRef } from 'react';
import { ChevronLeft, Loader2, RefreshCw, Search, X } from 'lucide-react';
import { api } from '../../../services/api';
import type { DiscoveryItem, ColumnInfo, VectorIndexTool, ToolEntry } from '../../../types/agentConfig';

interface VectorIndexDiscoveryProps {
  onSelect: (tool: VectorIndexTool) => void;
  onClose: () => void;
  existingTools: ToolEntry[];
}

type Step = 'endpoint' | 'index' | 'columns';

export const VectorIndexDiscovery: React.FC<VectorIndexDiscoveryProps> = ({
  onSelect,
  onClose,
  existingTools,
}) => {
  const panelRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  // Step tracking
  const [step, setStep] = useState<Step>('endpoint');

  // Endpoint step
  const [endpoints, setEndpoints] = useState<DiscoveryItem[]>([]);
  const [endpointQuery, setEndpointQuery] = useState('');
  const [selectedEndpoint, setSelectedEndpoint] = useState<DiscoveryItem | null>(null);

  // Index step
  const [indexes, setIndexes] = useState<DiscoveryItem[]>([]);
  const [indexQuery, setIndexQuery] = useState('');
  const [selectedIndex, setSelectedIndex] = useState<DiscoveryItem | null>(null);

  // Columns step
  const [columns, setColumns] = useState<ColumnInfo[]>([]);
  const [selectedColumns, setSelectedColumns] = useState<Set<string>>(new Set());
  const [description, setDescription] = useState('');

  // Shared state
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Fetch endpoints on mount
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
      const result = await api.discoverVectorEndpoints();
      // Only show ONLINE endpoints (metadata.status === 'ONLINE' if provided)
      const online = result.items.filter(
        ep => !ep.metadata?.status || ep.metadata.status === 'ONLINE',
      );
      setEndpoints(online);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load endpoints');
    } finally {
      setLoading(false);
    }
  };

  const fetchIndexes = async (endpointName: string) => {
    setLoading(true);
    setError(null);
    try {
      const result = await api.discoverVectorIndexes(endpointName);
      setIndexes(result.items);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load indexes');
    } finally {
      setLoading(false);
    }
  };

  const fetchColumns = async (endpointName: string, indexName: string) => {
    setLoading(true);
    setError(null);
    try {
      const result = await api.discoverVectorColumns(endpointName, indexName);
      setColumns(result.columns);
      setSelectedColumns(new Set(result.columns.map(c => c.name)));
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load columns');
    } finally {
      setLoading(false);
    }
  };

  const handleEndpointSelect = (ep: DiscoveryItem) => {
    setSelectedEndpoint(ep);
    setStep('index');
    setIndexQuery('');
    fetchIndexes(ep.name);
  };

  const handleIndexSelect = (idx: DiscoveryItem) => {
    setSelectedIndex(idx);
    setStep('columns');
    if (selectedEndpoint) {
      fetchColumns(selectedEndpoint.name, idx.name);
    }
  };

  const handleBack = () => {
    if (step === 'columns') {
      setStep('index');
      setSelectedIndex(null);
      setColumns([]);
      setSelectedColumns(new Set());
      setDescription('');
    } else if (step === 'index') {
      setStep('endpoint');
      setSelectedEndpoint(null);
      setIndexes([]);
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

  const isAlreadyAdded = (endpointName: string, indexName: string): boolean => {
    return existingTools.some(
      t => t.type === 'vector_index' && t.endpoint_name === endpointName && t.index_name === indexName,
    );
  };

  const handleSave = () => {
    if (!selectedEndpoint || !selectedIndex) return;

    const allSelected = selectedColumns.size === columns.length;
    const tool: VectorIndexTool = {
      type: 'vector_index',
      endpoint_name: selectedEndpoint.name,
      index_name: selectedIndex.name,
      columns: allSelected ? undefined : Array.from(selectedColumns),
      description: description || undefined,
    };
    onSelect(tool);
    onClose();
  };

  // Filter helpers
  const filteredEndpoints = endpoints.filter(ep =>
    ep.name.toLowerCase().includes(endpointQuery.toLowerCase()) ||
    (ep.description ?? '').toLowerCase().includes(endpointQuery.toLowerCase()),
  );

  const filteredIndexes = indexes.filter(idx =>
    idx.name.toLowerCase().includes(indexQuery.toLowerCase()) ||
    (idx.description ?? '').toLowerCase().includes(indexQuery.toLowerCase()),
  );

  const stepTitle =
    step === 'endpoint'
      ? 'Select Endpoint'
      : step === 'index'
        ? 'Select Index'
        : 'Configure Columns';

  return (
    <div
      ref={panelRef}
      className="absolute top-full left-0 mt-1 w-80 bg-white border border-gray-200 rounded-lg shadow-lg z-20"
      data-testid="vector-index-discovery"
    >
      {/* Header */}
      <div className="px-3 pt-3 pb-2">
        <div className="flex items-center justify-between mb-2">
          <div className="flex items-center gap-1.5">
            {step !== 'endpoint' && (
              <button
                onClick={handleBack}
                className="p-0.5 text-gray-400 hover:text-gray-600 rounded transition-colors"
                aria-label="Back"
              >
                <ChevronLeft size={14} />
              </button>
            )}
            <span className="text-sm font-medium text-gray-700">{stepTitle}</span>
          </div>
          <button
            onClick={onClose}
            className="p-0.5 text-gray-400 hover:text-gray-600 rounded transition-colors"
            aria-label="Close"
          >
            <X size={14} />
          </button>
        </div>

        {/* Breadcrumb */}
        <div className="text-xs text-gray-400 mb-2">
          <span className={step === 'endpoint' ? 'text-gray-700 font-medium' : ''}>Endpoint</span>
          <span className="mx-1">&rsaquo;</span>
          <span className={step === 'index' ? 'text-gray-700 font-medium' : ''}>Index</span>
          <span className="mx-1">&rsaquo;</span>
          <span className={step === 'columns' ? 'text-gray-700 font-medium' : ''}>Columns</span>
        </div>

        {/* Search input (endpoint & index steps) */}
        {step !== 'columns' && (
          <div className="relative">
            <Search size={14} className="absolute left-2.5 top-1/2 -translate-y-1/2 text-gray-400" />
            <input
              ref={inputRef}
              type="text"
              placeholder={step === 'endpoint' ? 'Search endpoints...' : 'Search indexes...'}
              value={step === 'endpoint' ? endpointQuery : indexQuery}
              onChange={e =>
                step === 'endpoint'
                  ? setEndpointQuery(e.target.value)
                  : setIndexQuery(e.target.value)
              }
              className="w-full pl-8 pr-3 py-1.5 border border-gray-300 rounded text-sm focus:outline-none focus:ring-1 focus:ring-blue-500 bg-white"
            />
          </div>
        )}
      </div>

      {/* Content area */}
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
              onClick={() => {
                if (step === 'endpoint') fetchEndpoints();
                else if (step === 'index' && selectedEndpoint) fetchIndexes(selectedEndpoint.name);
                else if (step === 'columns' && selectedEndpoint && selectedIndex) fetchColumns(selectedEndpoint.name, selectedIndex.name);
              }}
              className="inline-flex items-center gap-1 text-sm text-gray-600 hover:text-gray-800 transition-colors"
            >
              <RefreshCw size={14} />
              Retry
            </button>
          </div>
        )}

        {/* Step 1: Endpoints */}
        {!loading && !error && step === 'endpoint' && (
          <>
            {filteredEndpoints.length === 0 && (
              <p className="text-sm text-gray-500 py-4 text-center">
                {endpointQuery ? 'No matching endpoints.' : 'No vector endpoints available.'}
              </p>
            )}
            {filteredEndpoints.map((ep, idx) => (
              <button
                key={`ep-${ep.id ?? idx}`}
                onClick={() => handleEndpointSelect(ep)}
                className="w-full text-left px-3 py-2 rounded text-sm transition-colors text-gray-700 hover:bg-gray-100"
              >
                <span className="font-medium">{ep.name}</span>
                {ep.description && (
                  <p className="text-xs text-gray-500 mt-0.5 line-clamp-2">{ep.description}</p>
                )}
              </button>
            ))}
          </>
        )}

        {/* Step 2: Indexes */}
        {!loading && !error && step === 'index' && (
          <>
            {filteredIndexes.length === 0 && (
              <p className="text-sm text-gray-500 py-4 text-center">
                {indexQuery ? 'No matching indexes.' : 'No indexes found on this endpoint.'}
              </p>
            )}
            {filteredIndexes.map((idx, i) => {
              const added = isAlreadyAdded(selectedEndpoint!.name, idx.name);
              return (
                <button
                  key={`idx-${idx.id ?? i}`}
                  disabled={added}
                  onClick={() => handleIndexSelect(idx)}
                  className={`w-full text-left px-3 py-2 rounded text-sm transition-colors ${
                    added
                      ? 'text-gray-400 cursor-not-allowed'
                      : 'text-gray-700 hover:bg-gray-100'
                  }`}
                >
                  <div className="flex items-center gap-2">
                    <span className="font-medium">{idx.name}</span>
                    {added && <span className="text-xs text-gray-400 ml-auto">added</span>}
                  </div>
                  {idx.description && (
                    <p className="text-xs text-gray-500 mt-0.5 line-clamp-2">{idx.description}</p>
                  )}
                </button>
              );
            })}
          </>
        )}

        {/* Step 3: Columns & Description */}
        {!loading && !error && step === 'columns' && (
          <div className="px-2 pb-1">
            {columns.length > 0 && (
              <>
                <p className="text-xs text-gray-500 mb-1.5">Select columns to include:</p>
                <div className="max-h-40 overflow-y-auto border border-gray-200 rounded p-2 mb-3">
                  {columns.map(col => (
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
              </>
            )}

            <label className="block text-xs text-gray-500 mb-1">Description (optional)</label>
            <textarea
              value={description}
              onChange={e => setDescription(e.target.value)}
              placeholder="Describe what this vector index provides..."
              className="w-full border border-gray-300 rounded text-sm p-2 focus:outline-none focus:ring-1 focus:ring-blue-500 resize-none"
              rows={2}
            />

            <button
              onClick={handleSave}
              disabled={selectedColumns.size === 0}
              className="mt-2 w-full px-3 py-1.5 rounded text-sm bg-blue-600 text-white hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
            >
              Save & Add
            </button>
          </div>
        )}
      </div>
    </div>
  );
};
