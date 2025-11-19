/**
 * Hook for managing configuration profiles.
 * 
 * Provides methods to list, create, update, delete, and switch between profiles.
 * Tracks the currently loaded profile and handles loading states.
 */

import { useState, useEffect, useCallback } from 'react';
import type { 
  Profile, 
  ProfileCreate, 
  ProfileUpdate,
  ProfileDuplicate,
} from '../api/config';
import { configApi, ConfigApiError } from '../api/config';

interface UseProfilesReturn {
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

export const useProfiles = (): UseProfilesReturn => {
  const [profiles, setProfiles] = useState<Profile[]>([]);
  const [currentProfile, setCurrentProfile] = useState<Profile | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  /**
   * Load all profiles and determine the current profile
   */
  const loadProfiles = useCallback(async () => {
    try {
      setLoading(true);
      setError(null);
      
      const data = await configApi.listProfiles();
      setProfiles(data);
      
      // Find default profile (this is the currently loaded one)
      const defaultProfile = data.find(p => p.is_default);
      setCurrentProfile(defaultProfile || null);
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
      await loadProfiles(); // Reload to get updated list
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
      await loadProfiles(); // Reload to get updated list
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
      await loadProfiles(); // Reload to get updated list
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
      await loadProfiles(); // Reload to get updated list
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
      await loadProfiles(); // Reload to get updated list
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
   * 
   * This switches the active configuration without restarting the server.
   * Session state is preserved during the reload.
   */
  const loadProfile = useCallback(async (id: number): Promise<void> => {
    try {
      setError(null);
      
      // Call load profile endpoint (triggers hot-reload on backend)
      const response = await configApi.loadProfile(id);
      
      console.log('Profile loaded:', response);
      
      // Update current profile
      const profile = profiles.find(p => p.id === id);
      if (profile) {
        setCurrentProfile(profile);
      } else {
        // Reload profiles to ensure we have the latest
        await loadProfiles();
      }
    } catch (err) {
      const message = err instanceof ConfigApiError 
        ? err.message 
        : 'Failed to load profile';
      setError(message);
      throw err;
    }
  }, [profiles, loadProfiles]);

  return {
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
};

