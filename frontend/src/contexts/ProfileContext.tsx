/**
 * Profile context for managing saved agent profiles.
 *
 * Provides list, rename, and delete operations.
 * Profile saving and loading happen via AgentConfigContext on the generator page.
 */

import React, { createContext, useContext, useState, useEffect, useCallback } from 'react';
import type { Profile, ProfileUpdate } from '../api/config';
import { configApi, ConfigApiError } from '../api/config';

interface ProfileContextValue {
  profiles: Profile[];
  loading: boolean;
  error: string | null;
  reload: () => Promise<void>;
  updateProfile: (id: number, data: ProfileUpdate) => Promise<Profile>;
  deleteProfile: (id: number) => Promise<void>;
}

const ProfileContext = createContext<ProfileContextValue | undefined>(undefined);

export const ProfileProvider: React.FC<React.PropsWithChildren> = ({ children }) => {
  const [profiles, setProfiles] = useState<Profile[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Ref-tracked loadedProfileId so loadProfiles can read the latest value without
  // needing it in its dependency array (which would create a new identity on every
  // profile load and re-fire the mount effect unnecessarily).
  const loadedProfileIdRef = useRef(loadedProfileId);
  loadedProfileIdRef.current = loadedProfileId;

  // Persist loadedProfileId to localStorage so it survives page reloads
  useEffect(() => {
    if (loadedProfileId !== null) {
      localStorage.setItem(LOADED_PROFILE_KEY, String(loadedProfileId));
    } else {
      localStorage.removeItem(LOADED_PROFILE_KEY);
    }
  }, [loadedProfileId]);

  /**
   * Load all profiles and determine the current profile.
   * When silent=true, skips setting loading/error state (used by background polling).
   */
  const loadProfiles = useCallback(async (silent = false) => {
    try {
      if (!silent) {
        setLoading(true);
        setError(null);
      }

      const data = await configApi.listProfiles();
      setProfiles(data);

      // Read via ref so this callback stays stable (no loadedProfileId in deps).
      const currentLoadedId = loadedProfileIdRef.current;

      // Use loaded profile if we have one, otherwise fall back to default
      if (currentLoadedId) {
        const loadedProfile = data.find(p => p.id === currentLoadedId);
        if (loadedProfile) {
          setCurrentProfile(loadedProfile);
        } else {
          // Loaded profile no longer exists, fall back to user's default
          const defaultProfile = data.find(p => p.is_my_default) || data.find(p => p.is_default);
          setCurrentProfile(defaultProfile || null);
          setLoadedProfileId(null);
        }
      } else {
        // No loaded profile, use user's personal default (then system default)
        const defaultProfile = data.find(p => p.is_my_default) || data.find(p => p.is_default);
        setCurrentProfile(defaultProfile || null);
      }
    } catch (err) {
      if (!silent) {
        const message = err instanceof ConfigApiError
          ? err.message
          : 'Failed to load profiles';
        setError(message);
      }
      console.error('Error loading profiles:', err);
    } finally {
      if (!silent) setLoading(false);
    }
  }, []);

  /**
   * Load profiles on mount and poll for updates every 15 seconds
   */
  useEffect(() => {
    loadProfiles();
    const timer = setInterval(() => loadProfiles(true), 15_000);
    return () => clearInterval(timer);
  }, [loadProfiles]);

  const updateProfile = useCallback(async (
    id: number,
    data: ProfileUpdate
  ): Promise<Profile> => {
    try {
      setError(null);
      const updated = await configApi.updateProfile(id, data);
      await loadProfiles();
      return updated;
    } catch (err) {
      const message = err instanceof ConfigApiError
        ? err.message
        : 'Failed to update profile';
      setError(message);
      throw err;
    }
  }, [loadProfiles]);

  const deleteProfile = useCallback(async (id: number): Promise<void> => {
    try {
      setError(null);
      await configApi.deleteProfile(id);
      await loadProfiles();
    } catch (err) {
      const message = err instanceof ConfigApiError
        ? err.message
        : 'Failed to delete profile';
      setError(message);
      throw err;
    }
  }, [loadProfiles]);

  const value: ProfileContextValue = {
    profiles,
    loading,
    error,
    reload: loadProfiles,
    updateProfile,
    deleteProfile,
  };

  return (
    <ProfileContext.Provider value={value}>
      {children}
    </ProfileContext.Provider>
  );
};

export const useProfiles = (): ProfileContextValue => {
  const context = useContext(ProfileContext);
  if (!context) {
    throw new Error('useProfiles must be used within a ProfileProvider');
  }
  return context;
};
