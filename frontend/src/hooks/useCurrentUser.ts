/**
 * Hook for the current user's identity, including the admin UX flag.
 *
 * Reads the existing GET /api/user/current endpoint (no new endpoint). The
 * `isAdmin` flag is a UX signal ONLY — used to hide admin surfaces a caller
 * cannot use. Every admin API route enforces its own server-side admin check
 * and answers 403 regardless of what this hook reports, so a tampered flag
 * buys nothing but a page whose requests all fail.
 *
 * `loading` is load-bearing for the /admin gate: until identity resolves the
 * answer is genuinely unknown, and callers must render neither the admin page
 * (flash) nor a redirect (which would bounce a real admin).
 */

import { useState, useEffect } from 'react';

interface CurrentUser {
  username: string | null;
  displayName: string | null;
  isAdmin: boolean;
}

interface UseCurrentUserReturn extends CurrentUser {
  loading: boolean;
}

export const useCurrentUser = (): UseCurrentUserReturn => {
  const [user, setUser] = useState<CurrentUser>({
    username: null,
    displayName: null,
    // Fail closed: not an admin until the backend says so.
    isAdmin: false,
  });
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;

    fetch('/api/user/current')
      .then((response) => {
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        return response.json();
      })
      .then((data) => {
        if (cancelled) return;
        setUser({
          username: data.username ?? null,
          displayName: data.display_name ?? data.username ?? null,
          isAdmin: data.is_admin === true,
        });
      })
      .catch(() => {
        // Unreachable identity endpoint: stay non-admin (fail closed).
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });

    return () => {
      cancelled = true;
    };
  }, []);

  return { ...user, loading };
};
