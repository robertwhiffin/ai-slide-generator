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
  /**
   * Apply a full config. Resolves true on success and false when the backend
   * sync failed (the update is reverted and an error toast is shown here) —
   * callers that report success themselves must check the flag.
   */
  updateConfig: (config: AgentConfig) => Promise<boolean>;
  addTool: (tool: ToolEntry) => Promise<void>;
  removeTool: (tool: ToolEntry) => Promise<void>;
  updateTool: (spaceId: string, updates: { description?: string }) => Promise<void>;
  updateToolEntry: (tool: ToolEntry) => Promise<void>;
  setStyle: (styleId: number | null) => Promise<void>;
  setDesignSystem: (designSystemId: number | null) => Promise<void>;
  setTemplate: (templateId: number | null) => Promise<void>;
  setDeckPrompt: (promptId: number | null) => Promise<void>;
  saveAsProfile: (name: string, description?: string) => Promise<void>;
  loadProfile: (profileId: number) => Promise<void>;
  refreshConfig: () => Promise<void>;
  isPreSession: boolean;
  /**
   * The session id the in-memory config is VALID FOR: the session it was
   * loaded-for (its GET resolved) or explicitly edited-in. Null while a
   * session's config load is still pending after a switch — in that window
   * the in-memory config is another surface's leftovers and must never be
   * sent (a chat request carrying it would overwrite the session's own
   * persisted config server-side).
   */
  configOwnerSessionId: string | null;
}

const AgentConfigContext = createContext<AgentConfigContextValue | undefined>(undefined);

// ---------------------------------------------------------------------------
// localStorage helpers
// ---------------------------------------------------------------------------

const STORAGE_KEY = 'pendingAgentConfig';

/**
 * template_id is SESSION-SCOPED state: a template choice belongs to one
 * session only, so it must never travel through cross-session stores (this
 * localStorage mirror, profiles — the backend strips it there too). A new
 * session therefore always starts with template = None, while everything
 * else (design system, style, tools) carries over as configured.
 */
function withoutSessionScopedState(config: AgentConfig): AgentConfig {
  if (config.template_id == null) return config;
  return { ...config, template_id: null };
}

function readStoredConfig(): AgentConfig | null {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return null;
    // Strip on read as well as write, so values stored before the
    // session-scoped rule existed can never seed a new session.
    return withoutSessionScopedState(JSON.parse(raw) as AgentConfig);
  } catch {
    return null;
  }
}

/**
 * Resolve the default slide style ID from user preference or system default.
 * Priority: user localStorage > server is_default > server is_system.
 * Returns null if no default can be determined (caller should leave style as-is).
 */
async function resolveDefaultStyleId(): Promise<number | null> {
  const userStyleId = localStorage.getItem('userDefaultSlideStyleId');
  if (userStyleId) return Number(userStyleId);

  try {
    const { styles } = await configApi.listSlideStyles();
    const defaultStyle = styles.find(s => s.is_default) ?? styles.find(s => s.is_system);
    return defaultStyle?.id ?? null;
  } catch {
    return null;
  }
}

/**
 * Resolve the default deck prompt ID from user preference.
 * Priority: user localStorage only (no server-side default for deck prompts).
 */
function resolveDefaultDeckPromptId(): number | null {
  const userPromptId = localStorage.getItem('userDefaultDeckPromptId');
  if (userPromptId) return Number(userPromptId);
  return null;
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
    () => {
      const stored = readStoredConfig();
      if (stored) return stored;
      // Apply user defaults synchronously so dropdowns show them immediately
      const config = { ...DEFAULT_AGENT_CONFIG };
      const userStyleId = localStorage.getItem('userDefaultSlideStyleId');
      if (userStyleId) {
        config.slide_style_id = Number(userStyleId);
      }
      const userDeckPromptId = resolveDefaultDeckPromptId();
      if (userDeckPromptId) {
        config.deck_prompt_id = userDeckPromptId;
      }
      return config;
    },
  );

  // Ownership: which session the in-memory config is valid for (loaded-for
  // or explicitly edited-in). State drives consumers (ChatPanel gates what a
  // chat request may carry); the ref mirror is for async closures.
  const [configOwnerSessionId, setConfigOwnerSessionId] = useState<string | null>(null);
  const configOwnerRef = useRef<string | null>(null);
  const claimOwnership = useCallback((sessionId: string | null) => {
    configOwnerRef.current = sessionId;
    setConfigOwnerSessionId(sessionId);
  }, []);

  // ------------------------------------------------------------------
  // THE settle invariant (structural — every async continuation goes
  // through here).
  //
  // Any async continuation in this context (GET resolve, PUT confirm,
  // PUT catch, refresh resolve, profile-load resolve, pre-session default
  // loads) captures the surface it was ISSUED FOR (a session id, or null
  // for pre-session) and, at settle time, may mutate VISIBLE state
  // (setAgentConfig / ownership / toasts) ONLY if that surface is still
  // the active one. A continuation settling after the user moved on may
  // at most update the per-session confirmed stash — which is keyed, so
  // it is safe by construction. This closes the whole class of stale-
  // closure holes (a late-failing B PUT poisoning C's screen, etc.), not
  // individual instances.
  // ------------------------------------------------------------------
  const activeSurfaceRef = useRef<string | null>(urlSessionId);
  // Render-time mirror: continuations settling between a navigation render
  // and its effects must already compare against the NEW surface.
  activeSurfaceRef.current = urlSessionId;

  const settleForSurface = useCallback(
    (issuedFor: string | null, mutateVisible: () => void): boolean => {
      if (activeSurfaceRef.current !== issuedFor) return false;
      mutateVisible();
      return true;
    },
    [],
  );

  // Last SERVER-CONFIRMED config PER SESSION (a keyed map — one session's
  // late-settling artifacts can never displace another's entry): updated
  // whenever a session's GET resolves — INCLUDING when the snapshot is
  // discarded because an in-flight edit claimed ownership, and including
  // late settles after the user moved on — and whenever a PUT/profile-load
  // confirms. Failure paths revert to THIS, never to pre-edit in-memory
  // residue: 'edits win over the in-flight GET' only holds when the edit
  // SUCCEEDS; a failed edit must restore the target session's OWN state.
  //
  // GENERATION axis (state moves FORWARD only). The surface guard stops a
  // continuation from a DIFFERENT session touching the screen, but two ops
  // for the SAME session can still settle out of issue order — a slow early
  // GET returning stale server state can land AFTER a newer edit's PUT
  // confirmed, and (repaint aside) regress the stash. So every stash-writing
  // op captures the session's monotonic generation AT ISSUE TIME
  // (``nextGeneration``); a settling write is accepted only if its
  // issue-generation is not older than the entry's recorded generation.
  // A confirmed PUT was issued after any GET/PUT before it, so it carries a
  // higher generation — older ops settling later are outdated and rejected.
  // The counter lives per session in the Map, so a B→C→B round trip keeps
  // B's history and a pre-round-trip B GET can't regress the post-return
  // stash.
  const generationBySessionRef = useRef<Map<string, number>>(new Map());
  const nextGeneration = useCallback((sessionId: string): number => {
    const next = (generationBySessionRef.current.get(sessionId) ?? 0) + 1;
    generationBySessionRef.current.set(sessionId, next);
    return next;
  }, []);
  const lastConfirmedBySessionRef = useRef<
    Map<string, { config: AgentConfig; generation: number }>
  >(new Map());
  const stashConfirmed = useCallback(
    (sessionId: string, config: AgentConfig, generation: number): boolean => {
      const existing = lastConfirmedBySessionRef.current.get(sessionId);
      if (existing && generation < existing.generation) return false; // outdated
      lastConfirmedBySessionRef.current.set(sessionId, { config, generation });
      return true;
    },
    [],
  );
  // updateConfig (declared before refreshConfig) triggers a fresh fetch on
  // the no-snapshot failure path via this forward ref.
  const refreshConfigRef = useRef<(() => Promise<void>) | null>(null);

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

    // If we have a stored config with tools already configured, it's a real
    // user-modified config — keep it as-is and just fill in missing defaults.
    if (storedConfig && storedConfig.tools.length > 0) {
      if (storedConfig.slide_style_id == null || storedConfig.deck_prompt_id == null) {
        resolveDefaultStyleId().then(styleId => {
          const updated = { ...storedConfig };
          if (updated.slide_style_id == null) updated.slide_style_id = styleId;
          if (updated.deck_prompt_id == null) updated.deck_prompt_id = resolveDefaultDeckPromptId();
          settleForSurface(null, () => setAgentConfig(updated));
        });
      }
      return;
    }

    // Otherwise, load default profile config and apply defaults
    api.listProfiles()
      .then(async (profiles: ProfileSummary[]) => {
        // Prefer user's localStorage profile default over server is_default
        const userProfileId = localStorage.getItem('userDefaultProfileId');
        const defaultProfile = userProfileId
          ? profiles.find(p => p.id === Number(userProfileId)) ?? profiles.find(p => p.is_default)
          : profiles.find(p => p.is_default);
        const config = defaultProfile?.agent_config
          ? { ...defaultProfile.agent_config }
          : { ...DEFAULT_AGENT_CONFIG };

        if (config.slide_style_id == null) {
          config.slide_style_id = await resolveDefaultStyleId();
        }
        if (config.deck_prompt_id == null) {
          config.deck_prompt_id = resolveDefaultDeckPromptId();
        }

        settleForSurface(null, () => setAgentConfig(config));
      })
      .catch(err => {
        console.error('Failed to load default profile for pre-session config:', err);
      });
  }, [isPreSession, settleForSurface]);

  // ------------------------------------------------------------------
  // Reset default-profile flag when entering an active session so
  // clicking "New Deck" later will re-load the default profile.
  // ------------------------------------------------------------------
  useEffect(() => {
    if (!isPreSession) {
      defaultProfileLoaded.current = false;
    }
  }, [isPreSession]);

  // ------------------------------------------------------------------
  // Active session: load config from backend whenever the session
  // changes.
  // ------------------------------------------------------------------
  useEffect(() => {
    if (isPreSession) return;

    // Entering a session (New Deck / session switch): the PREVIOUS surface's
    // config is still in memory until this session's GET resolves. It is
    // FOREIGN here — ownership is dropped synchronously so nothing sends it,
    // and the session-scoped template pin is stripped so the interim UI
    // never shows another session's pin. This session's own config arrives
    // with the GET below (which then claims ownership), and an explicit
    // user edit made in the meantime claims ownership for THIS session and
    // wins over the later-arriving GET.
    claimOwnership(null);
    setAgentConfig(prev => withoutSessionScopedState(prev));

    const issuedFor = urlSessionId;
    const issueGen = issuedFor ? nextGeneration(issuedFor) : 0;
    api.getAgentConfig(issuedFor)
      .then(async (config) => {
        // If the session has no explicitly-saved config, load the default profile
        const isConfigured = (config as AgentConfig & { is_configured?: boolean }).is_configured ?? true;

        if (!isConfigured) {
          try {
            const profiles = await api.listProfiles();
            const userProfileId = localStorage.getItem('userDefaultProfileId');
            const defaultProfile = userProfileId
              ? profiles.find((p: ProfileSummary) => p.id === Number(userProfileId)) ?? profiles.find((p: ProfileSummary) => p.is_default)
              : profiles.find((p: ProfileSummary) => p.is_default);
            if (defaultProfile?.agent_config) {
              config = { ...defaultProfile.agent_config };
            }
          } catch {
            // Non-critical — continue with defaults
          }
        }

        if (config.slide_style_id == null) {
          config.slide_style_id = await resolveDefaultStyleId();
        }
        if (config.deck_prompt_id == null) {
          config.deck_prompt_id = resolveDefaultDeckPromptId();
        }
        // The session's own loaded state — stash keyed by ITS id, but only
        // if this GET is not OLDER than what's recorded (a newer edit's PUT
        // may have already confirmed for this session). ``accepted`` gates
        // the display apply too: a stash-rejected GET is stale server truth
        // and must not repaint either.
        const accepted = issuedFor
          ? stashConfirmed(issuedFor, config, issueGen)
          : true;
        settleForSurface(issuedFor, () => {
          if (!accepted) return; // superseded by a newer confirmed write
          if (configOwnerRef.current === issuedFor) {
            // The user explicitly edited config for this session while the
            // GET was in flight: their intent is already persisted via the
            // PUT — this snapshot is stale FOR DISPLAY (a still-accepted
            // stash entry is the failure-revert target). Explicit edits win.
            return;
          }
          setAgentConfig(config);
          claimOwnership(issuedFor);
        });
      })
      .catch(err => {
        console.error('Failed to load agent config for session:', err);
        settleForSurface(issuedFor, () => {
          showToast('Failed to load agent configuration', 'error');
        });
      });
  }, [urlSessionId, isPreSession, showToast, claimOwnership, stashConfirmed, settleForSurface, nextGeneration]);

  // ------------------------------------------------------------------
  // localStorage persistence for pre-session mode
  // ------------------------------------------------------------------
  useEffect(() => {
    if (isPreSession) {
      localStorage.setItem(
        STORAGE_KEY,
        JSON.stringify(withoutSessionScopedState(agentConfig)),
      );
    } else {
      localStorage.removeItem(STORAGE_KEY);
    }
  }, [agentConfig, isPreSession]);

  // ------------------------------------------------------------------
  // updateConfig — optimistic update with revert on failure
  // ------------------------------------------------------------------
  const updateConfig = useCallback(async (config: AgentConfig): Promise<boolean> => {
    setAgentConfig(config);

    if (!isPreSession && urlSessionId) {
      const issuedFor = urlSessionId;
      // Issued AFTER any GET/PUT before it for this session, so it carries a
      // higher generation: when it confirms, older ops settling later are
      // outdated and can't regress the stash.
      const issueGen = nextGeneration(issuedFor);
      // An explicit edit is intent FOR THIS SESSION: it claims ownership, so
      // chat requests may carry the config again and a still-in-flight
      // config GET for this session is treated as stale (edits win).
      claimOwnership(issuedFor);
      console.log('[AgentConfigContext] Syncing to backend, session:', issuedFor, 'tools:', config.tools.length);
      try {
        const confirmed = await api.updateAgentConfig(issuedFor, config);
        console.log('[AgentConfigContext] Backend confirmed:', JSON.stringify(confirmed));
        // Server truth for ITS session — stash (keyed) unless a still-newer
        // write already landed; touch the screen only if still on it.
        stashConfirmed(issuedFor, confirmed, issueGen);
        settleForSurface(issuedFor, () => setAgentConfig(confirmed));
        return true;
      } catch (err) {
        console.error('[AgentConfigContext] Failed to update agent config:', err);
        // 'Edits win' only holds for edits that SUCCEED. A failed edit must
        // restore the target session's OWN state — never pre-edit in-memory
        // residue — and a failure settling AFTER the user moved on must not
        // touch the new surface at all (its own load already reset it).
        const applied = settleForSurface(issuedFor, () => {
          const ownConfirmed = lastConfirmedBySessionRef.current.get(issuedFor);
          if (ownConfirmed) {
            // The session's last server-confirmed state (its GET snapshot —
            // including one discarded-as-stale mid-edit — or an earlier
            // confirmed PUT), protected by the generation gate. It IS this
            // session's state, so it stays owned.
            setAgentConfig(ownConfirmed.config);
            claimOwnership(issuedFor);
          } else {
            // The edit fired before any snapshot for this session ever
            // existed: fall back to defaults with no owner (chat requests
            // omit config) and fetch the session's real config fresh.
            setAgentConfig({ ...DEFAULT_AGENT_CONFIG });
            claimOwnership(null);
            void refreshConfigRef.current?.();
          }
          showToast('Failed to update configuration', 'error');
        });
        if (!applied && configOwnerRef.current === issuedFor) {
          // Defensive: never leave a stale claim for a session that is no
          // longer active (a switch normally already dropped it).
          claimOwnership(null);
        }
        return false;
      }
    } else {
      console.log('[AgentConfigContext] Pre-session mode, config saved locally only. isPreSession:', isPreSession, 'urlSessionId:', urlSessionId);
      return true;
    }
  }, [isPreSession, urlSessionId, showToast, claimOwnership, stashConfirmed, settleForSurface, nextGeneration]);

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
          return t.connection_name !== tool.connection_name;
        }
        if (t.type === 'vector_index' && tool.type === 'vector_index') {
          return t.endpoint_name !== tool.endpoint_name || t.index_name !== tool.index_name;
        }
        if (t.type === 'model_endpoint' && tool.type === 'model_endpoint') {
          return t.endpoint_name !== tool.endpoint_name;
        }
        if (t.type === 'agent_bricks' && tool.type === 'agent_bricks') {
          return t.endpoint_name !== tool.endpoint_name;
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

  /** Replace a tool entry in-place, matched by type + primary key. */
  const updateToolEntry = useCallback(async (tool: ToolEntry) => {
    const updated: AgentConfig = {
      ...agentConfig,
      tools: agentConfig.tools.map(t => {
        if (t.type !== tool.type) return t;
        switch (tool.type) {
          case 'genie':
            return t.type === 'genie' && t.space_id === tool.space_id ? tool : t;
          case 'mcp':
            return t.type === 'mcp' && t.connection_name === tool.connection_name ? tool : t;
          case 'vector_index':
            return t.type === 'vector_index' && t.endpoint_name === tool.endpoint_name && t.index_name === tool.index_name ? tool : t;
          case 'model_endpoint':
            return t.type === 'model_endpoint' && t.endpoint_name === tool.endpoint_name ? tool : t;
          case 'agent_bricks':
            return t.type === 'agent_bricks' && t.endpoint_name === tool.endpoint_name ? tool : t;
          default:
            return t;
        }
      }),
    };
    await updateConfig(updated);
  }, [agentConfig, updateConfig]);

  const setStyle = useCallback(async (styleId: number | null) => {
    await updateConfig({ ...agentConfig, slide_style_id: styleId });
  }, [agentConfig, updateConfig]);

  const setDesignSystem = useCallback(async (designSystemId: number | null) => {
    // Templates belong to a design system: changing (or clearing) the design
    // system invalidates a pinned template, so reset it to None.
    const templateId =
      designSystemId === agentConfig.design_system_id
        ? agentConfig.template_id ?? null
        : null;
    await updateConfig({
      ...agentConfig,
      design_system_id: designSystemId,
      template_id: templateId,
    });
  }, [agentConfig, updateConfig]);

  const setTemplate = useCallback(async (templateId: number | null) => {
    await updateConfig({ ...agentConfig, template_id: templateId });
  }, [agentConfig, updateConfig]);

  const setDeckPrompt = useCallback(async (promptId: number | null) => {
    await updateConfig({ ...agentConfig, deck_prompt_id: promptId });
  }, [agentConfig, updateConfig]);

  // ------------------------------------------------------------------
  // Profile operations
  // ------------------------------------------------------------------

  const saveAsProfile = useCallback(async (name: string, description?: string) => {
    try {
      if (isPreSession || !urlSessionId) {
        await api.createProfile(name, description, agentConfig);
      } else {
        await api.saveAsProfile(urlSessionId, name, description, agentConfig);
      }
      showToast(`Profile "${name}" saved`, 'success');
    } catch (err) {
      console.error('Failed to save as profile:', err);
      const message = err instanceof Error ? err.message : 'Failed to save profile';
      showToast(message, 'error');
    }
  }, [isPreSession, urlSessionId, showToast, agentConfig]);

  const refreshConfig = useCallback(async () => {
    if (isPreSession || !urlSessionId) return;
    const issuedFor = urlSessionId;
    const issueGen = nextGeneration(issuedFor);
    try {
      const config = await api.getAgentConfig(issuedFor);
      const accepted = stashConfirmed(issuedFor, config, issueGen);
      settleForSurface(issuedFor, () => {
        if (!accepted) return; // superseded by a newer confirmed write
        setAgentConfig(config);
        claimOwnership(issuedFor); // freshly loaded FOR this session
      });
    } catch (err) {
      console.error('[AgentConfigContext] Failed to refresh config:', err);
    }
  }, [isPreSession, urlSessionId, claimOwnership, stashConfirmed, settleForSurface, nextGeneration]);

  useEffect(() => {
    refreshConfigRef.current = refreshConfig;
  }, [refreshConfig]);

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
      const issuedFor = urlSessionId;
      // A profile load is a server WRITE for this session — issued now, so
      // it takes a fresh (higher) generation like a PUT.
      const issueGen = nextGeneration(issuedFor);
      // Active session: call backend, then update local state
      try {
        const result = await api.loadProfile(issuedFor, profileId);
        // The profile DID apply to issuedFor server-side — stash reflects
        // that unless a still-newer write landed; screen updates only if
        // we're still there.
        const accepted = stashConfirmed(issuedFor, result.agent_config, issueGen);
        settleForSurface(issuedFor, () => {
          if (!accepted) return;
          setAgentConfig(result.agent_config);
          claimOwnership(issuedFor); // explicitly set IN this session
          showToast('Profile loaded', 'success');
        });
      } catch (err) {
        console.error('Failed to load profile into session:', err);
        settleForSurface(issuedFor, () => {
          showToast('Failed to load profile', 'error');
        });
      }
    } else {
      // Pre-session: fetch profiles and apply the matching one locally
      try {
        const profiles = await api.listProfiles();
        const profile = profiles.find(p => p.id === profileId);
        settleForSurface(null, () => {
          if (profile?.agent_config) {
            setAgentConfig(profile.agent_config);
            showToast('Profile loaded', 'success');
          } else {
            showToast('Profile not found or has no configuration', 'error');
          }
        });
      } catch (err) {
        console.error('Failed to load profile:', err);
        settleForSurface(null, () => {
          showToast('Failed to load profile', 'error');
        });
      }
    }
  }, [agentConfig, isPreSession, urlSessionId, showToast, claimOwnership, stashConfirmed, settleForSurface, nextGeneration]);

  // ------------------------------------------------------------------
  // Render
  // ------------------------------------------------------------------

  const value: AgentConfigContextValue = {
    agentConfig,
    updateConfig,
    addTool,
    removeTool,
    updateTool,
    updateToolEntry,
    setStyle,
    setDesignSystem,
    setTemplate,
    setDeckPrompt,
    saveAsProfile,
    loadProfile,
    refreshConfig,
    isPreSession,
    configOwnerSessionId,
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
