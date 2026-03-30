/**
 * VectorIndexDiscovery — progressive 2-step inline dropdown panel for
 * selecting a Vector Search endpoint and index.
 *
 * Step 1: Pick endpoint
 * Step 2: Pick index
 *
 * When the user selects an index, the dropdown fetches columns and then
 * closes, calling `onPreview` so that AgentConfigBar can open the
 * full-width ToolDetailPanel for column selection, description, and save.
 */

import React, { useEffect, useState, useRef } from 'react';
import { ChevronLeft, Loader2, RefreshCw, Search, X } from 'lucide-react';
import { api } from '../../../services/api';
import type { DiscoveryItem, VectorIndexTool, ToolEntry } from '../../../types/agentConfig';
import type { VectorIndexPreview } from '../ToolDetailPanel';

interface VectorIndexDiscoveryProps {
  onSelect: (tool: VectorIndexTool) => void;
  onPreview: (preview: VectorIndexPreview) => void;
  onClose: () => void;
  existingTools: ToolEntry[];
}

type Step = 'endpoint' | 'index';

export const VectorIndexDiscovery: React.FC<VectorIndexDiscoveryProps> = ({
  onPreview,
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

  const handleEndpointSelect = (ep: DiscoveryItem) => {
    setSelectedEndpoint(ep);
    setStep('index');
    setIndexQuery('');
    fetchIndexes(ep.name);
  };

  const handleIndexSelect = async (idx: DiscoveryItem) => {
    if (!selectedEndpoint) return;
    // Fetch columns, then open the full-width detail panel
    setLoading(true);
    setError(null);
    try {
      const result = await api.discoverVectorColumns(selectedEndpoint.name, idx.name);
      onPreview({
        toolType: 'vector_index',
        name: idx.name,
        endpointName: selectedEndpoint.name,
        indexName: idx.name,
        columns: result.columns,
        description: idx.description,
      });
      onClose();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load columns');
      setLoading(false);
    }
  };

  const handleBack = () => {
    if (step === 'index') {
      setStep('endpoint');
      setSelectedEndpoint(null);
      setIndexes([]);
    }
  };

  const isAlreadyAdded = (endpointName: string, indexName: string): boolean => {
    return existingTools.some(
      t => t.type === 'vector_index' && t.endpoint_name === endpointName && t.index_name === indexName,
    );
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
      : 'Select Index';

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
        </div>

        {/* Search input */}
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
      </div>
    </div>
  );
};
