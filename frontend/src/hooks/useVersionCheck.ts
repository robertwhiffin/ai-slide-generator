/**
 * Hook for checking if a new app version is available on PyPI.
 * 
 * Checks on app load and caches the result to avoid repeated API calls.
 * Returns update info including whether it's a patch (redeploy) or major (run tellr.update()).
 */

import { useState, useEffect, useCallback } from 'react';

const API_BASE_URL = import.meta.env.VITE_API_URL || (
  import.meta.env.MODE === 'production' ? '' : 'http://localhost:8000'
);

// Cache key for session storage
const CACHE_KEY = 'version_check_cache';
const CACHE_TTL_MS = 60 * 60 * 1000; // 1 hour
const DISMISSED_KEY = 'version_check_dismissed';

interface VersionCheckResponse {
  installed_version: string;
  latest_version: string | null;
  update_available: boolean;
  update_type: 'patch' | 'major' | null;
  package_name: string;
}

interface CachedVersionCheck {
  data: VersionCheckResponse;
  timestamp: number;
}

interface UseVersionCheckReturn {
  installedVersion: string | null;
  latestVersion: string | null;
  updateAvailable: boolean;
  updateType: 'patch' | 'major' | null;
  loading: boolean;
  error: string | null;
  dismissed: boolean;
  dismiss: () => void;
}

export const useVersionCheck = (): UseVersionCheckReturn => {
  const [data, setData] = useState<VersionCheckResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [dismissed, setDismissed] = useState(() => {
    // Check if user dismissed the banner this session
    return sessionStorage.getItem(DISMISSED_KEY) === 'true';
  });

  const dismiss = useCallback(() => {
    setDismissed(true);
    sessionStorage.setItem(DISMISSED_KEY, 'true');
  }, []);

  useEffect(() => {
    const checkVersion = async () => {
      // Check cache first
      try {
        const cached = localStorage.getItem(CACHE_KEY);
        if (cached) {
          const parsedCache: CachedVersionCheck = JSON.parse(cached);
          const age = Date.now() - parsedCache.timestamp;
          if (age < CACHE_TTL_MS) {
            setData(parsedCache.data);
            setLoading(false);
            return;
          }
        }
      } catch {
        // Ignore cache errors
      }

      // Fetch from API
      try {
        const response = await fetch(`${API_BASE_URL}/api/version/check`);
        if (!response.ok) {
          throw new Error('Failed to check version');
        }
        const result: VersionCheckResponse = await response.json();
        setData(result);

        // Cache the result
        try {
          localStorage.setItem(CACHE_KEY, JSON.stringify({
            data: result,
            timestamp: Date.now(),
          }));
        } catch {
          // Ignore cache errors
        }
      } catch (err) {
        // Fail silently - version check is non-critical
        console.warn('Version check failed:', err);
        setError(err instanceof Error ? err.message : 'Unknown error');
      } finally {
        setLoading(false);
      }
    };

    checkVersion();
  }, []);

  return {
    installedVersion: data?.installed_version ?? null,
    latestVersion: data?.latest_version ?? null,
    updateAvailable: data?.update_available ?? false,
    updateType: data?.update_type ?? null,
    loading,
    error,
    dismissed,
    dismiss,
  };
};
