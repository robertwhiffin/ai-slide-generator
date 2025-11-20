/**
 * Hook for managing configuration for a specific profile.
 * 
 * Handles loading, updating, and dirty state tracking for all config domains.
 * Each profile has exactly one Genie space.
 */

import { useState, useEffect, useCallback } from 'react';
import type {
  AIInfraConfig,
  AIInfraConfigUpdate,
  GenieSpace,
  GenieSpaceCreate,
  GenieSpaceUpdate,
  MLflowConfig,
  MLflowConfigUpdate,
  PromptsConfig,
  PromptsConfigUpdate,
} from '../api/config';
import { configApi, ConfigApiError } from '../api/config';

interface ConfigState {
  ai_infra: AIInfraConfig | null;
  genie_space: GenieSpace | null;
  mlflow: MLflowConfig | null;
  prompts: PromptsConfig | null;
}

interface UseConfigReturn {
  config: ConfigState;
  loading: boolean;
  error: string | null;
  dirty: boolean;
  saving: boolean;
  reload: () => Promise<void>;
  updateAIInfra: (data: AIInfraConfigUpdate) => Promise<void>;
  addGenieSpace: (data: GenieSpaceCreate) => Promise<void>;
  updateGenieSpace: (spaceId: number, data: GenieSpaceUpdate) => Promise<void>;
  deleteGenieSpace: (spaceId: number) => Promise<void>;
  updateMLflow: (data: MLflowConfigUpdate) => Promise<void>;
  updatePrompts: (data: PromptsConfigUpdate) => Promise<void>;
}

export const useConfig = (profileId: number): UseConfigReturn => {
  const [config, setConfig] = useState<ConfigState>({
    ai_infra: null,
    genie_space: null,
    mlflow: null,
    prompts: null,
  });
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [dirty, setDirty] = useState(false);
  const [saving, setSaving] = useState(false);

  /**
   * Load all configuration for the profile
   */
  const loadConfig = useCallback(async () => {
    try {
      setLoading(true);
      setError(null);

      // Load all configs in parallel
      const results = await Promise.allSettled([
        configApi.getAIInfraConfig(profileId),
        configApi.getGenieSpace(profileId),
        configApi.getMLflowConfig(profileId),
        configApi.getPromptsConfig(profileId),
      ]);

      setConfig({
        ai_infra: results[0].status === 'fulfilled' ? results[0].value : null,
        genie_space: results[1].status === 'fulfilled' ? results[1].value : null,
        mlflow: results[2].status === 'fulfilled' ? results[2].value : null,
        prompts: results[3].status === 'fulfilled' ? results[3].value : null,
      });
      setDirty(false);
    } catch (err) {
      const message = err instanceof ConfigApiError 
        ? err.message 
        : 'Failed to load configuration';
      setError(message);
      console.error('Error loading config:', err);
    } finally {
      setLoading(false);
    }
  }, [profileId]);

  /**
   * Load config on mount and when profileId changes
   */
  useEffect(() => {
    loadConfig();
  }, [loadConfig]);

  /**
   * Update AI Infrastructure configuration
   */
  const updateAIInfra = useCallback(async (data: AIInfraConfigUpdate) => {
    try {
      setSaving(true);
      setError(null);
      const updated = await configApi.updateAIInfraConfig(profileId, data);
      setConfig(prev => ({ ...prev, ai_infra: updated }));
      setDirty(false);
    } catch (err) {
      const message = err instanceof ConfigApiError 
        ? err.message 
        : 'Failed to update AI Infrastructure';
      setError(message);
      throw err;
    } finally {
      setSaving(false);
    }
  }, [profileId]);

  /**
   * Add a Genie space to the profile.
   * Each profile can have exactly one Genie space.
   */
  const addGenieSpace = useCallback(async (data: GenieSpaceCreate) => {
    try {
      setSaving(true);
      setError(null);
      const newSpace = await configApi.addGenieSpace(profileId, data);
      setConfig(prev => ({
        ...prev,
        genie_space: newSpace,
      }));
      setDirty(false);
    } catch (err) {
      const message = err instanceof ConfigApiError 
        ? err.message 
        : 'Failed to add Genie space';
      setError(message);
      throw err;
    } finally {
      setSaving(false);
    }
  }, [profileId]);

  /**
   * Update the Genie space for the profile
   */
  const updateGenieSpace = useCallback(async (spaceId: number, data: GenieSpaceUpdate) => {
    try {
      setSaving(true);
      setError(null);
      const updated = await configApi.updateGenieSpace(spaceId, data);
      setConfig(prev => ({
        ...prev,
        genie_space: updated,
      }));
      setDirty(false);
    } catch (err) {
      const message = err instanceof ConfigApiError 
        ? err.message 
        : 'Failed to update Genie space';
      setError(message);
      throw err;
    } finally {
      setSaving(false);
    }
  }, []);

  /**
   * Delete the Genie space for the profile
   */
  const deleteGenieSpace = useCallback(async (spaceId: number) => {
    try {
      setSaving(true);
      setError(null);
      await configApi.deleteGenieSpace(spaceId);
      setConfig(prev => ({
        ...prev,
        genie_space: null,
      }));
      setDirty(false);
    } catch (err) {
      const message = err instanceof ConfigApiError 
        ? err.message 
        : 'Failed to delete Genie space';
      setError(message);
      throw err;
    } finally {
      setSaving(false);
    }
  }, []);

  /**
   * Update MLflow configuration
   */
  const updateMLflow = useCallback(async (data: MLflowConfigUpdate) => {
    try {
      setSaving(true);
      setError(null);
      const updated = await configApi.updateMLflowConfig(profileId, data);
      setConfig(prev => ({ ...prev, mlflow: updated }));
      setDirty(false);
    } catch (err) {
      const message = err instanceof ConfigApiError 
        ? err.message 
        : 'Failed to update MLflow configuration';
      setError(message);
      throw err;
    } finally {
      setSaving(false);
    }
  }, [profileId]);

  /**
   * Update Prompts configuration
   */
  const updatePrompts = useCallback(async (data: PromptsConfigUpdate) => {
    try {
      setSaving(true);
      setError(null);
      const updated = await configApi.updatePromptsConfig(profileId, data);
      setConfig(prev => ({ ...prev, prompts: updated }));
      setDirty(false);
    } catch (err) {
      const message = err instanceof ConfigApiError 
        ? err.message 
        : 'Failed to update prompts';
      setError(message);
      throw err;
    } finally {
      setSaving(false);
    }
  }, [profileId]);

  return {
    config,
    loading,
    error,
    dirty,
    saving,
    reload: loadConfig,
    updateAIInfra,
    addGenieSpace,
    updateGenieSpace,
    deleteGenieSpace,
    updateMLflow,
    updatePrompts,
  };
};

