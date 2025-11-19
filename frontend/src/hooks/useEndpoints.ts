/**
 * Hook for fetching available LLM endpoints from Databricks.
 */

import { useState, useEffect } from 'react';
import { configApi, ConfigApiError } from '../api/config';

interface UseEndpointsReturn {
  endpoints: string[];
  loading: boolean;
  error: string | null;
  reload: () => Promise<void>;
}

export const useEndpoints = (): UseEndpointsReturn => {
  const [endpoints, setEndpoints] = useState<string[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const loadEndpoints = async () => {
    try {
      setLoading(true);
      setError(null);
      const data = await configApi.getAvailableEndpoints();
      setEndpoints(data.endpoints);
    } catch (err) {
      const message = err instanceof ConfigApiError 
        ? err.message 
        : 'Failed to load endpoints';
      setError(message);
      console.error('Error loading endpoints:', err);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadEndpoints();
  }, []);

  return {
    endpoints,
    loading,
    error,
    reload: loadEndpoints,
  };
};

