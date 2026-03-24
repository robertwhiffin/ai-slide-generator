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

  const loadProfiles = useCallback(async () => {
    try {
      setLoading(true);
      setError(null);
      const data = await configApi.listProfiles();
      setProfiles(data);
    } catch (err) {
      const message = err instanceof ConfigApiError
        ? err.message
        : 'Failed to load profiles';
      setError(message);
      console.error('Error loading profiles:', err);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    loadProfiles();
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
