/**
 * Profile context for managing configuration profiles across the application.
 * 
 * Provides shared state for profiles and the currently loaded profile,
 * ensuring all components see the same profile state.
 */

import React, { createContext, useContext, useState, useEffect, useCallback, useRef } from 'react';
import type { 
  Profile, 
  ProfileCreate, 
  ProfileUpdate,
  ProfileDuplicate,
} from '../api/config';
import { configApi, ConfigApiError } from '../api/config';

interface ProfileContextValue {
  profiles: Profile[];
  currentProfile: Profile | null;
  loading: boolean;
  error: string | null;
  reload: () => Promise<void>;
  createProfile: (data: ProfileCreate) => Promise<Profile>;
  updateProfile: (id: number, data: ProfileUpdate) => Promise<Profile>;
  deleteProfile: (id: number) => Promise<void>;
  duplicateProfile: (id: number, newName: string) => Promise<Profile>;
  setDefaultProfile: (id: number) => Promise<void>;
  loadProfile: (id: number) => Promise<void>;
}

const ProfileContext = createContext<ProfileContextValue | undefined>(undefined);

const LOADED_PROFILE_KEY = 'loadedProfileId';

function readStoredProfileId(): number | null {
  const raw = localStorage.getItem(LOADED_PROFILE_KEY);
  if (!raw) return null;
  const parsed = Number(raw);
  return Number.isFinite(parsed) ? parsed : null;
}

export const ProfileProvider: React.FC<React.PropsWithChildren> = ({ children }) => {
  const [profiles, setProfiles] = useState<Profile[]>([]);
  const [currentProfile, setCurrentProfile] = useState<Profile | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  // Track the last loaded profile ID (may differ from is_default)
  const [loadedProfileId, setLoadedProfileId] = useState<number | null>(readStoredProfileId);

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
   * Load all profiles and determine the current profile
   */
  const loadProfiles = useCallback(async () => {
    try {
      setLoading(true);
      setError(null);

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
      const message = err instanceof ConfigApiError
        ? err.message
        : 'Failed to load profiles';
      setError(message);
      console.error('Error loading profiles:', err);
    } finally {
      setLoading(false);
    }
  }, []);

  /**
   * Load profiles on mount
   */
  useEffect(() => {
    loadProfiles();
  }, [loadProfiles]);

  /**
   * Create a new profile
   */
  const createProfile = useCallback(async (data: ProfileCreate): Promise<Profile> => {
    try {
      setError(null);
      const newProfile = await configApi.createProfile(data);
      await loadProfiles();
      return newProfile;
    } catch (err) {
      const message = err instanceof ConfigApiError 
        ? err.message 
        : 'Failed to create profile';
      setError(message);
      throw err;
    }
  }, [loadProfiles]);

  /**
   * Update profile metadata
   */
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

  /**
   * Delete a profile
   */
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

  /**
   * Duplicate a profile with a new name
   */
  const duplicateProfile = useCallback(async (
    id: number, 
    newName: string
  ): Promise<Profile> => {
    try {
      setError(null);
      const data: ProfileDuplicate = { new_name: newName };
      const duplicated = await configApi.duplicateProfile(id, data);
      await loadProfiles();
      return duplicated;
    } catch (err) {
      const message = err instanceof ConfigApiError 
        ? err.message 
        : 'Failed to duplicate profile';
      setError(message);
      throw err;
    }
  }, [loadProfiles]);

  /**
   * Set a profile as the default
   */
  const setDefaultProfile = useCallback(async (id: number): Promise<void> => {
    try {
      setError(null);
      await configApi.setDefaultProfile(id);
      await loadProfiles();
    } catch (err) {
      const message = err instanceof ConfigApiError 
        ? err.message 
        : 'Failed to set default profile';
      setError(message);
      throw err;
    }
  }, [loadProfiles]);

  /**
   * Load a profile and hot-reload the application configuration
   */
  const loadProfile = useCallback(async (id: number): Promise<void> => {
    try {
      setError(null);
      
      // Call load profile endpoint (triggers hot-reload on backend)
      await configApi.loadProfile(id);
      
      // Profile loaded successfully
      
      // Track this as the loaded profile
      setLoadedProfileId(id);
      
      // Update current profile
      const profile = profiles.find(p => p.id === id);
      if (profile) {
        setCurrentProfile(profile);
      } else {
        // Reload profiles to ensure we have the latest
        await loadProfiles();
      }
    } catch (err) {
      // Profile was deleted: clear stored id, fall back to default, show friendly message
      if (err instanceof ConfigApiError && err.status === 404 && err.message.includes('deleted')) {
        setLoadedProfileId(null);
        await loadProfiles();
        setError('That profile was deleted. Switched to default profile.');
        return;
      }
      const message = err instanceof ConfigApiError 
        ? err.message 
        : 'Failed to load profile';
      setError(message);
      throw err;
    }
  }, [profiles, loadProfiles]);

  const value: ProfileContextValue = {
    profiles,
    currentProfile,
    loading,
    error,
    reload: loadProfiles,
    createProfile,
    updateProfile,
    deleteProfile,
    duplicateProfile,
    setDefaultProfile,
    loadProfile,
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

