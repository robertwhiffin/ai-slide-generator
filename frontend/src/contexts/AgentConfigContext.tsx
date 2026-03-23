/**
 * AgentConfigContext — manages the agent configuration state.
 *
 * Two modes:
 *  1. Pre-session (no active session in the URL): config held in React state,
 *     mirrored to localStorage so it survives navigation.
 *  2. Active session (/sessions/:id/edit): config loaded from the backend and
 *     changes are synced via PUT with optimistic updates.
 */

import React, {
  createContext,
  useContext,
  useState,
  useEffect,
  useCallback,
  useRef,
} from 'react';
import { useLocation } from 'react-router-dom';
import { api } from '../services/api';
import { configApi } from '../api/config';
import { useToast } from './ToastContext';
import type { AgentConfig, ToolEntry, ProfileSummary } from '../types/agentConfig';
import { DEFAULT_AGENT_CONFIG } from '../types/agentConfig';

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface AgentConfigContextValue {
  agentConfig: AgentConfig;
  updateConfig: (config: AgentConfig) => Promise<void>;
  addTool: (tool: ToolEntry) => Promise<void>;
  removeTool: (tool: ToolEntry) => Promise<void>;
  updateTool: (spaceId: string, updates: { description?: string }) => Promise<void>;
  setStyle: (styleId: number | null) => Promise<void>;
  setDeckPrompt: (promptId: number | null) => Promise<void>;
  saveAsProfile: (name: string, description?: string) => Promise<void>;
  loadProfile: (profileId: number) => Promise<void>;
  refreshConfig: () => Promise<void>;
  isPreSession: boolean;
}

const AgentConfigContext = createContext<AgentConfigContextValue | undefined>(undefined);

// ---------------------------------------------------------------------------
// localStorage helpers
// ---------------------------------------------------------------------------

const STORAGE_KEY = 'pendingAgentConfig';

function readStoredConfig(): AgentConfig | null {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return null;
    return JSON.parse(raw) as AgentConfig;
  } catch {
    return null;
  }
}

// ---------------------------------------------------------------------------
// Provider
// ---------------------------------------------------------------------------

export const AgentConfigProvider: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const location = useLocation();
  const { showToast } = useToast();

  // Determine session ID from the URL path (reliable — not the local-only ID from SessionContext).
  // SessionContext always generates a local ID on mount, even before backend persistence,
  // so we can't rely on it to know if a real session exists.
  const urlMatch = location.pathname.match(/\/sessions\/([^/]+)\//);
  const urlSessionId = urlMatch ? urlMatch[1] : null;
  const isPreSession = !urlSessionId;

  const [agentConfig, setAgentConfig] = useState<AgentConfig>(
    () => readStoredConfig() ?? DEFAULT_AGENT_CONFIG,
  );

  // Track whether we've already loaded the default profile for pre-session mode
  // so we only do it once (on first mount with no stored config).
  const defaultProfileLoaded = useRef(false);

  // ------------------------------------------------------------------
  // Pre-session: load default profile's config on first mount if no
  // stored config exists.
  // ------------------------------------------------------------------
  useEffect(() => {
    if (!isPreSession) return;
    if (defaultProfileLoaded.current) return;
    defaultProfileLoaded.current = true;

    const storedConfig = readStoredConfig();
    console.log('[AgentConfigContext] Pre-session default load: storedConfig=', storedConfig, 'isPreSession=', isPreSession);

    // If we have a stored config with a style already set, use it as-is
    if (storedConfig?.slide_style_id != null) {
      console.log('[AgentConfigContext] Stored config has style, skipping default load:', storedConfig.slide_style_id);
      return;
    }

    // Otherwise, load profile config and apply default style
    api.listProfiles()
      .then(async (profiles: ProfileSummary[]) => {
        const defaultProfile = profiles.find(p => p.is_default);
        const config = storedConfig
          ?? (defaultProfile?.agent_config ? { ...defaultProfile.agent_config } : { ...DEFAULT_AGENT_CONFIG });
        console.log('[AgentConfigContext] After profile load, config.slide_style_id=', config.slide_style_id);

        // User default overrides profile's style
        const userStyleId = localStorage.getItem('userDefaultSlideStyleId');
        console.log('[AgentConfigContext] userDefaultSlideStyleId from localStorage=', userStyleId);
        if (userStyleId) {
          config.slide_style_id = Number(userStyleId);
        }

        // If still no style, fetch the system default from slide styles
        if (config.slide_style_id == null) {
          try {
            const { styles } = await configApi.listSlideStyles();
            const defaultStyle = styles.find(s => s.is_default) ?? styles.find(s => s.is_system);
            if (defaultStyle) {
              config.slide_style_id = defaultStyle.id;
            }
          } catch {
            // Non-critical — backend will apply system default on session creation
          }
        }

        console.log('[AgentConfigContext] Final config.slide_style_id=', config.slide_style_id);
        setAgentConfig(config);
      })
      .catch(err => {
        console.error('Failed to load default profile for pre-session config:', err);
      });
  }, [isPreSession]);

  // ------------------------------------------------------------------
  // Active session: load config from backend whenever the session
  // changes.
  // ------------------------------------------------------------------
  useEffect(() => {
    if (isPreSession) return;

    let cancelled = false;
    api.getAgentConfig(urlSessionId)
      .then(config => {
        if (!cancelled) setAgentConfig(config);
      })
      .catch(err => {
        console.error('Failed to load agent config for session:', err);
        if (!cancelled) {
          showToast('Failed to load agent configuration', 'error');
        }
      });

    return () => { cancelled = true; };
  }, [urlSessionId, isPreSession, showToast]);

  // ------------------------------------------------------------------
  // localStorage persistence for pre-session mode
  // ------------------------------------------------------------------
  useEffect(() => {
    if (isPreSession) {
      localStorage.setItem(STORAGE_KEY, JSON.stringify(agentConfig));
    } else {
      localStorage.removeItem(STORAGE_KEY);
    }
  }, [agentConfig, isPreSession]);

  // ------------------------------------------------------------------
  // updateConfig — optimistic update with revert on failure
  // ------------------------------------------------------------------
  const updateConfig = useCallback(async (config: AgentConfig) => {
    const previous = agentConfig;
    setAgentConfig(config);

    if (!isPreSession && urlSessionId) {
      console.log('[AgentConfigContext] Syncing to backend, session:', urlSessionId, 'tools:', config.tools.length);
      try {
        const confirmed = await api.updateAgentConfig(urlSessionId, config);
        console.log('[AgentConfigContext] Backend confirmed:', JSON.stringify(confirmed));
        setAgentConfig(confirmed);
      } catch (err) {
        console.error('[AgentConfigContext] Failed to update agent config:', err);
        setAgentConfig(previous);
        showToast('Failed to update configuration', 'error');
      }
    } else {
      console.log('[AgentConfigContext] Pre-session mode, config saved locally only. isPreSession:', isPreSession, 'urlSessionId:', urlSessionId);
    }
  }, [agentConfig, isPreSession, urlSessionId, showToast]);

  // ------------------------------------------------------------------
  // Convenience mutators
  // ------------------------------------------------------------------

  const addTool = useCallback(async (tool: ToolEntry) => {
    console.log('[AgentConfigContext] addTool called:', JSON.stringify(tool));
    const updated: AgentConfig = {
      ...agentConfig,
      tools: [...agentConfig.tools, tool],
    };
    console.log('[AgentConfigContext] calling updateConfig with tools:', updated.tools.length);
    await updateConfig(updated);
  }, [agentConfig, updateConfig]);

  const removeTool = useCallback(async (tool: ToolEntry) => {
    const updated: AgentConfig = {
      ...agentConfig,
      tools: agentConfig.tools.filter(t => {
        if (t.type !== tool.type) return true;
        if (t.type === 'genie' && tool.type === 'genie') {
          return t.space_id !== tool.space_id;
        }
        if (t.type === 'mcp' && tool.type === 'mcp') {
          return t.server_uri !== tool.server_uri;
        }
        return true;
      }),
    };
    await updateConfig(updated);
  }, [agentConfig, updateConfig]);

  const updateTool = useCallback(async (spaceId: string, updates: { description?: string }) => {
    const updated: AgentConfig = {
      ...agentConfig,
      tools: agentConfig.tools.map(t => {
        if (t.type === 'genie' && t.space_id === spaceId) {
          return { ...t, ...updates };
        }
        return t;
      }),
    };
    await updateConfig(updated);
  }, [agentConfig, updateConfig]);

  const setStyle = useCallback(async (styleId: number | null) => {
    await updateConfig({ ...agentConfig, slide_style_id: styleId });
  }, [agentConfig, updateConfig]);

  const setDeckPrompt = useCallback(async (promptId: number | null) => {
    await updateConfig({ ...agentConfig, deck_prompt_id: promptId });
  }, [agentConfig, updateConfig]);

  // ------------------------------------------------------------------
  // Profile operations
  // ------------------------------------------------------------------

  const saveAsProfile = useCallback(async (name: string, description?: string) => {
    if (isPreSession || !urlSessionId) {
      showToast('Save as profile requires an active session', 'error');
      return;
    }

    try {
      await api.saveAsProfile(urlSessionId, name, description);
      showToast(`Profile "${name}" saved`, 'success');
    } catch (err) {
      console.error('Failed to save as profile:', err);
      showToast('Failed to save profile', 'error');
    }
  }, [isPreSession, urlSessionId, showToast]);

  const refreshConfig = useCallback(async () => {
    if (isPreSession || !urlSessionId) return;
    try {
      const config = await api.getAgentConfig(urlSessionId);
      setAgentConfig(config);
    } catch (err) {
      console.error('[AgentConfigContext] Failed to refresh config:', err);
    }
  }, [isPreSession, urlSessionId]);

  const loadProfile = useCallback(async (profileId: number) => {
    // If the session already has non-default config, confirm before overwriting
    const hasConfig =
      agentConfig.tools.length > 0 ||
      agentConfig.slide_style_id !== null ||
      agentConfig.deck_prompt_id !== null ||
      agentConfig.system_prompt !== null ||
      agentConfig.slide_editing_instructions !== null;
    if (hasConfig) {
      const confirmed = window.confirm(
        'Loading a profile will replace your current configuration. Continue?',
      );
      if (!confirmed) return;
    }

    if (!isPreSession && urlSessionId) {
      // Active session: call backend, then update local state
      try {
        const result = await api.loadProfile(urlSessionId, profileId);
        setAgentConfig(result.agent_config);
        showToast('Profile loaded', 'success');
      } catch (err) {
        console.error('Failed to load profile into session:', err);
        showToast('Failed to load profile', 'error');
      }
    } else {
      // Pre-session: fetch profiles and apply the matching one locally
      try {
        const profiles = await api.listProfiles();
        const profile = profiles.find(p => p.id === profileId);
        if (profile?.agent_config) {
          setAgentConfig(profile.agent_config);
          showToast('Profile loaded', 'success');
        } else {
          showToast('Profile not found or has no configuration', 'error');
        }
      } catch (err) {
        console.error('Failed to load profile:', err);
        showToast('Failed to load profile', 'error');
      }
    }
  }, [agentConfig, isPreSession, urlSessionId, showToast]);

  // ------------------------------------------------------------------
  // Render
  // ------------------------------------------------------------------

  const value: AgentConfigContextValue = {
    agentConfig,
    updateConfig,
    addTool,
    removeTool,
    updateTool,
    setStyle,
    setDeckPrompt,
    saveAsProfile,
    loadProfile,
    refreshConfig,
    isPreSession,
  };

  return (
    <AgentConfigContext.Provider value={value}>
      {children}
    </AgentConfigContext.Provider>
  );
};

// ---------------------------------------------------------------------------
// Hook
// ---------------------------------------------------------------------------

export const useAgentConfig = (): AgentConfigContextValue => {
  const context = useContext(AgentConfigContext);
  if (context === undefined) {
    throw new Error('useAgentConfig must be used within an AgentConfigProvider');
  }
  return context;
};
