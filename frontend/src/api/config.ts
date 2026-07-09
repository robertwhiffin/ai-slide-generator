/**
 * Configuration API client for profile and settings management.
 * 
 * Provides methods to interact with the database-backed configuration system.
 */

// Use relative URLs in production, explicit IPv4 in development
// Note: Using 127.0.0.1 instead of localhost to avoid IPv6 resolution issues in CI
const API_BASE_URL = import.meta.env.VITE_API_URL || (
  import.meta.env.MODE === 'production' ? '' : 'http://127.0.0.1:8000'
);

const API_BASE = `${API_BASE_URL}/api/settings`;
const PROFILES_API_BASE = `${API_BASE_URL}/api/profiles`;
const SESSIONS_API_BASE = `${API_BASE_URL}/api/sessions`;

/**
 * Resolve a server-relative API path (e.g. a design-system asset URL) to an
 * absolute URL, honoring VITE_API_URL in dev. Absolute URLs pass through.
 */
export function resolveApiUrl(path: string): string {
  return /^https?:\/\//.test(path) ? path : `${API_BASE_URL}${path}`;
}

// Types

export type PermissionLevel = 'CAN_MANAGE' | 'CAN_EDIT' | 'CAN_VIEW' | 'CAN_USE';

/** Workspace-wide deck sharing — CAN_MANAGE is not allowed */
export type DeckWorkspacePermission = 'CAN_VIEW' | 'CAN_EDIT';

export interface Profile {
  id: number;
  name: string;
  description: string | null;
  is_default: boolean;
  global_permission: PermissionLevel | null;
  agent_config: Record<string, unknown> | null;
  created_at: string;
  created_by: string | null;
  updated_at: string | null;
  updated_by: string | null;
  my_permission?: PermissionLevel;
  /** True if this is the current user's personal default profile */
  is_my_default?: boolean;
}

export interface ProfileUpdate {
  name?: string;
  description?: string | null;
}

/**
 * Genie space configuration.
 * Each profile has exactly one Genie space.
 */
export interface GenieSpace {
  id: number;
  profile_id: number;
  space_id: string;
  space_name: string;
  description: string | null;
  created_at: string;
  updated_at: string;
}

export interface GenieSpaceCreate {
  space_id: string;
  space_name: string;
  description?: string | null;
}

export interface GenieSpaceUpdate {
  space_name?: string;
  description?: string | null;
}

export interface PromptsConfig {
  id: number;
  profile_id: number;
  selected_deck_prompt_id: number | null;
  selected_slide_style_id: number | null;
  system_prompt: string;
  slide_editing_instructions: string;
  created_at: string;
  updated_at: string;
}

export interface PromptsConfigUpdate {
  selected_deck_prompt_id?: number | null;
  selected_slide_style_id?: number | null;
  system_prompt?: string;
  slide_editing_instructions?: string;
}

// Deck Prompt Library types

export interface DeckPrompt {
  id: number;
  name: string;
  description: string | null;
  category: string | null;
  prompt_content: string;
  is_active: boolean;
  created_by: string | null;
  created_at: string;
  updated_by: string | null;
  updated_at: string;
}

export interface DeckPromptCreate {
  name: string;
  description?: string | null;
  category?: string | null;
  prompt_content: string;
}

export interface DeckPromptUpdate {
  name?: string;
  description?: string | null;
  category?: string | null;
  prompt_content?: string;
}

export interface DeckPromptListResponse {
  prompts: DeckPrompt[];
  total: number;
}

// Slide Style Library types

export interface SlideStyle {
  id: number;
  name: string;
  description: string | null;
  category: string | null;
  style_content: string;
  image_guidelines: string | null;
  is_active: boolean;
  is_system: boolean;  // Protected system styles cannot be edited/deleted
  is_default: boolean;
  created_by: string | null;
  created_at: string;
  updated_by: string | null;
  updated_at: string;
}

export interface SlideStyleCreate {
  name: string;
  description?: string | null;
  category?: string | null;
  style_content: string;
  image_guidelines?: string | null;
}

export interface SlideStyleUpdate {
  name?: string;
  description?: string | null;
  category?: string | null;
  style_content?: string;
  image_guidelines?: string | null;
}

export interface SlideStyleListResponse {
  styles: SlideStyle[];
  total: number;
}

// Design System Library types (Phase 4).
// Mirrors the backend schemas in src/api/routes/settings/design_systems.py.

/** A normalized design token (color/type/spacing). */
export interface DesignSystemToken {
  id: number;
  group: string;
  name: string;
  value: string;
}

/** A stored brand asset (logo, icon, background, font, …). */
export interface DesignSystemAsset {
  id: number;
  kind: string;
  filename: string;
  mime: string;
  size_bytes: number;
  width: number | null;
  height: number | null;
  /** Served-asset endpoint; bytes are never inlined in listings. */
  url: string;
  /** Downscaled-variant endpoint for raster formats; null for SVG/fonts/etc. */
  thumbnail_url: string | null;
}

/** List/picker view — counts only, no binary payloads. */
export interface DesignSystemSummary {
  id: number;
  name: string;
  description: string | null;
  created_by: string | null;
  published: boolean;
  is_default: boolean;
  is_active: boolean;
  version: number;
  token_count: number;
  asset_count: number;
  template_count: number;
  created_at: string;
  updated_at: string;
}

/** Detail view — adds manifest, compiled artifact, tokens and assets. */
export interface DesignSystemDetail extends DesignSystemSummary {
  manifest_json: Record<string, unknown> | null;
  compiled_style_content: string | null;
  tokens: DesignSystemToken[];
  assets: DesignSystemAsset[];
}

export interface DesignSystemListResponse {
  design_systems: DesignSystemSummary[];
  total: number;
}

/** An addressable slide template of a design system (picker view). */
export interface DesignSystemTemplate {
  id: number;
  name: string;
  description: string | null;
  entry_path: string;
  /** Template-scoped thumbnail endpoint, or null when no preview was retained. */
  thumbnail_url: string | null;
}

export interface DesignSystemTemplateListResponse {
  templates: DesignSystemTemplate[];
  total: number;
}

/**
 * One template's stored sources for CLIENT-SIDE preview rendering (JSON —
 * the server never serves user markup renderable from the app origin).
 * Only ever rendered inside a fully-sandboxed iframe (sandbox="").
 */
export interface DesignSystemTemplateSource {
  id: number;
  name: string;
  layout_html: string;
  token_css: string | null;
}

/** One node of a design system's retained source-file tree — metadata only. */
export interface DesignSystemFileEntry {
  path: string;
  kind: string;
  mime: string;
  size_bytes: number;
}

export interface DesignSystemFileListResponse {
  files: DesignSystemFileEntry[];
  total: number;
}

export interface DesignSystemTokenInput {
  group: string;
  name: string;
  value: string;
}

export interface DesignSystemCreate {
  name: string;
  description?: string | null;
  tokens?: DesignSystemTokenInput[] | null;
  manifest_json?: Record<string, unknown> | null;
}

export interface DesignSystemUpdate {
  name?: string;
  description?: string | null;
  tokens?: DesignSystemTokenInput[] | null;
  manifest_json?: Record<string, unknown> | null;
}

export interface GenieSpaceDetail {
  title: string;
  description: string;
}

export interface AvailableGenieSpaces {
  spaces: {
    [spaceId: string]: GenieSpaceDetail;
  };
  sorted_titles: string[];
}

export interface ValidationComponentResult {
  component: string;
  success: boolean;
  message: string;
  details?: string;
}

export interface ValidationResponse {
  success: boolean;
  profile_id: number;
  profile_name: string;
  results: ValidationComponentResult[];
  error?: string;
}

export interface ReloadResponse {
  status: string;
  profile_id: number;
  profile_name: string;
  sessions_preserved: number;
}

// Databricks Identities (Users/Groups)

export type IdentityType = 'USER' | 'GROUP';

export interface Identity {
  id: string;
  display_name: string;
  user_name?: string;
  type: IdentityType;
}

export interface IdentityListResponse {
  identities: Identity[];
  total: number;
}

// Profile Contributors (Sharing)

export interface Contributor {
  id: number;
  identity_id: string;
  identity_type: IdentityType;
  identity_name: string;
  display_name?: string;
  user_name?: string;
  permission_level: PermissionLevel;
  created_at: string;
  created_by: string | null;
}

export interface ContributorCreate {
  identity_id: string;
  identity_type: IdentityType;
  identity_name: string;
  user_name?: string;
  permission_level: PermissionLevel;
}

export interface ContributorUpdate {
  permission_level: PermissionLevel;
}

export interface ContributorListResponse {
  contributors: Contributor[];
  total: number;
  global_permission?: DeckWorkspacePermission | null;
}

export class ConfigApiError extends Error {
  status: number;
  
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
    this.name = 'ConfigApiError';
  }
}

async function fetchJson<T>(url: string, options?: RequestInit): Promise<T> {
  const response = await fetch(url, options);
  
  if (!response.ok) {
    const error = await response.json().catch(() => ({ detail: 'Request failed' }));
    throw new ConfigApiError(
      response.status,
      error.detail || `HTTP ${response.status}`
    );
  }
  
  // Handle 204 No Content
  if (response.status === 204) {
    return undefined as T;
  }
  
  return response.json();
}

/**
 * Configuration API methods
 */
export const configApi = {
  // Profiles (simplified — list, rename, delete only)

  listProfiles: (): Promise<Profile[]> =>
    fetchJson(`${PROFILES_API_BASE}`),

  updateProfile: (id: number, data: ProfileUpdate): Promise<Profile> =>
    fetchJson(`${PROFILES_API_BASE}/${id}`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(data),
    }),

  deleteProfile: (id: number): Promise<void> =>
    fetchJson(`${PROFILES_API_BASE}/${id}`, {
      method: 'DELETE',
    }),

  setDefaultProfile: (id: number): Promise<Profile> =>
    fetchJson(`${PROFILES_API_BASE}/${id}/set-default`, {
      method: 'POST',
    }),

  loadProfile: (id: number): Promise<ReloadResponse> =>
    fetchJson(`${PROFILES_API_BASE}/${id}/load`, {
      method: 'POST',
    }),

  setProfileGlobal: (id: number, permission: PermissionLevel | null): Promise<{ id: number; global_permission: PermissionLevel | null }> =>
    fetchJson(`${PROFILES_API_BASE}/${id}/global${permission ? `?permission=${permission}` : ''}`, {
      method: 'PATCH',
    }),

  reloadConfiguration: (profileId?: number): Promise<ReloadResponse> => {
    const url = profileId
      ? `${PROFILES_API_BASE}/reload?profile_id=${profileId}`
      : `${PROFILES_API_BASE}/reload`;
    return fetchJson(url, { method: 'POST' });
  },

  // Genie Spaces
  // Each profile has exactly one Genie space
  
  getAvailableGenieSpaces: (): Promise<AvailableGenieSpaces> =>
    fetchJson(`${API_BASE}/genie/available`),
  
  lookupGenieSpace: (spaceId: string): Promise<{ space_id: string; title: string; description: string }> =>
    fetchJson(`${API_BASE}/genie/lookup/${encodeURIComponent(spaceId)}`),
  
  getGenieSpace: (profileId: number): Promise<GenieSpace> =>
    fetchJson(`${API_BASE}/genie/${profileId}`),
  
  addGenieSpace: (profileId: number, data: GenieSpaceCreate): Promise<GenieSpace> =>
    fetchJson(`${API_BASE}/genie/${profileId}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(data),
    }),
  
  updateGenieSpace: (spaceId: number, data: GenieSpaceUpdate): Promise<GenieSpace> =>
    fetchJson(`${API_BASE}/genie/space/${spaceId}`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(data),
    }),
  
  deleteGenieSpace: (spaceId: number): Promise<void> =>
    fetchJson(`${API_BASE}/genie/space/${spaceId}`, {
      method: 'DELETE',
    }),
  
  // Prompts
  
  getPromptsConfig: (profileId: number): Promise<PromptsConfig> =>
    fetchJson(`${API_BASE}/prompts/${profileId}`),
  
  updatePromptsConfig: (profileId: number, data: PromptsConfigUpdate): Promise<PromptsConfig> =>
    fetchJson(`${API_BASE}/prompts/${profileId}`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(data),
    }),

  // Deck Prompts Library
  
  listDeckPrompts: (category?: string): Promise<DeckPromptListResponse> => {
    const params = category ? `?category=${encodeURIComponent(category)}` : '';
    return fetchJson(`${API_BASE}/deck-prompts${params}`);
  },
  
  getDeckPrompt: (promptId: number): Promise<DeckPrompt> =>
    fetchJson(`${API_BASE}/deck-prompts/${promptId}`),
  
  createDeckPrompt: (data: DeckPromptCreate): Promise<DeckPrompt> =>
    fetchJson(`${API_BASE}/deck-prompts`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(data),
    }),
  
  updateDeckPrompt: (promptId: number, data: DeckPromptUpdate): Promise<DeckPrompt> =>
    fetchJson(`${API_BASE}/deck-prompts/${promptId}`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(data),
    }),
  
  deleteDeckPrompt: (promptId: number): Promise<void> =>
    fetchJson(`${API_BASE}/deck-prompts/${promptId}`, {
      method: 'DELETE',
    }),
  
  // Slide Styles Library
  
  listSlideStyles: (category?: string): Promise<SlideStyleListResponse> => {
    const params = category ? `?category=${encodeURIComponent(category)}` : '';
    return fetchJson(`${API_BASE}/slide-styles${params}`);
  },
  
  getSlideStyle: (styleId: number): Promise<SlideStyle> =>
    fetchJson(`${API_BASE}/slide-styles/${styleId}`),
  
  createSlideStyle: (data: SlideStyleCreate): Promise<SlideStyle> =>
    fetchJson(`${API_BASE}/slide-styles`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(data),
    }),
  
  updateSlideStyle: (styleId: number, data: SlideStyleUpdate): Promise<SlideStyle> =>
    fetchJson(`${API_BASE}/slide-styles/${styleId}`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(data),
    }),
  
  deleteSlideStyle: (styleId: number): Promise<void> =>
    fetchJson(`${API_BASE}/slide-styles/${styleId}`, {
      method: 'DELETE',
    }),

  setSlideStyleSystemDefault: (styleId: number): Promise<SlideStyle> =>
    fetchJson(`${API_BASE}/slide-styles/${styleId}/set-default`, {
      method: 'POST',
    }),

  // Design Systems Library (Phase 4) — org-shared, mirrors slide styles.

  listDesignSystems: (includeInactive = false): Promise<DesignSystemListResponse> => {
    const params = includeInactive ? '?include_inactive=true' : '';
    return fetchJson(`${API_BASE}/design-systems${params}`);
  },

  getDesignSystem: (dsId: number): Promise<DesignSystemDetail> =>
    fetchJson(`${API_BASE}/design-systems/${dsId}`),

  listDesignSystemTemplates: (dsId: number): Promise<DesignSystemTemplateListResponse> =>
    fetchJson(`${API_BASE}/design-systems/${dsId}/templates`),

  getDesignSystemTemplateSource: (
    dsId: number,
    templateId: number,
  ): Promise<DesignSystemTemplateSource> =>
    fetchJson(`${API_BASE}/design-systems/${dsId}/templates/${templateId}/source`),

  listDesignSystemFiles: (dsId: number): Promise<DesignSystemFileListResponse> =>
    fetchJson(`${API_BASE}/design-systems/${dsId}/files`),

  /**
   * Fetch ONE retained bundle file's content as plain text (source view).
   * The server serves every text source as text/plain — never renderable
   * markup — so the result is only ever displayed via text nodes.
   */
  getDesignSystemFileText: async (dsId: number, path: string): Promise<string> => {
    const encoded = path.split('/').map(encodeURIComponent).join('/');
    const response = await fetch(`${API_BASE}/design-systems/${dsId}/files/${encoded}`);
    if (!response.ok) {
      const error = await response.json().catch(() => ({ detail: 'Request failed' }));
      throw new ConfigApiError(response.status, error.detail || `HTTP ${response.status}`);
    }
    return response.text();
  },

  createDesignSystem: (data: DesignSystemCreate): Promise<DesignSystemDetail> =>
    fetchJson(`${API_BASE}/design-systems`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(data),
    }),

  updateDesignSystem: (dsId: number, data: DesignSystemUpdate): Promise<DesignSystemDetail> =>
    fetchJson(`${API_BASE}/design-systems/${dsId}`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(data),
    }),

  deleteDesignSystem: (dsId: number, hardDelete = false): Promise<void> =>
    fetchJson(`${API_BASE}/design-systems/${dsId}${hardDelete ? '?hard_delete=true' : ''}`, {
      method: 'DELETE',
    }),

  setDesignSystemDefault: (dsId: number): Promise<DesignSystemDetail> =>
    fetchJson(`${API_BASE}/design-systems/${dsId}/set-default`, {
      method: 'POST',
    }),

  /**
   * Import a design-system bundle (.zip) via multipart upload.
   * The browser sets the multipart Content-Type/boundary — do not set it here.
   */
  importDesignSystem: async (file: File, name?: string): Promise<DesignSystemDetail> => {
    const formData = new FormData();
    formData.append('file', file);
    if (name && name.trim()) formData.append('name', name.trim());
    const response = await fetch(`${API_BASE}/design-systems/import`, {
      method: 'POST',
      body: formData,
    });
    if (!response.ok) {
      const error = await response.json().catch(() => ({ detail: 'Import failed' }));
      throw new ConfigApiError(response.status, error.detail || `HTTP ${response.status}`);
    }
    return response.json();
  },


  // Google OAuth Credentials (global, admin-only)

  /**
   * Upload a Google OAuth credentials.json file (app-wide).
   * Stored encrypted on the server.
   */
  uploadGoogleCredentials: async (file: File): Promise<{ success: boolean; has_credentials: boolean }> => {
    const formData = new FormData();
    formData.append('file', file);
    const adminBase = `${API_BASE_URL}/api/admin`;
    const response = await fetch(`${adminBase}/google-credentials`, {
      method: 'POST',
      body: formData,
    });
    if (!response.ok) {
      const error = await response.json().catch(() => ({ detail: 'Upload failed' }));
      throw new ConfigApiError(response.status, error.detail || `HTTP ${response.status}`);
    }
    return response.json();
  },

  /** Check whether app-wide Google OAuth credentials exist. */
  getGoogleCredentialsStatus: (): Promise<{ has_credentials: boolean }> => {
    const adminBase = `${API_BASE_URL}/api/admin`;
    return fetchJson(`${adminBase}/google-credentials/status`);
  },

  /** Remove stored app-wide Google OAuth credentials. */
  deleteGoogleCredentials: (): Promise<void> => {
    const adminBase = `${API_BASE_URL}/api/admin`;
    return fetchJson(`${adminBase}/google-credentials`, {
      method: 'DELETE',
    });
  },

  // Validation
  
  validateProfile: (profileId: number): Promise<ValidationResponse> =>
    fetchJson(`${API_BASE}/validate/${profileId}`, {
      method: 'POST',
    }),

  validateGenie: (spaceId: string): Promise<{ success: boolean; message: string; details?: any }> =>
    fetchJson(`${API_BASE}/genie/validate?space_id=${encodeURIComponent(spaceId)}`, {
      method: 'POST',
    }),

  // Databricks Identities (Users/Groups)

  /**
   * Search for Databricks workspace users and groups.
   */
  searchIdentities: (
    query: string,
    includeUsers = true,
    includeGroups = true,
    maxResults = 50
  ): Promise<IdentityListResponse> => {
    const params = new URLSearchParams({
      query,
      include_users: String(includeUsers),
      include_groups: String(includeGroups),
      max_results: String(maxResults),
    });
    return fetchJson(`${API_BASE}/identities/search?${params}`);
  },

  /**
   * List Databricks workspace users.
   */
  listUsers: (query?: string, maxResults = 100): Promise<IdentityListResponse> => {
    const params = new URLSearchParams({ max_results: String(maxResults) });
    if (query) params.set('query', query);
    return fetchJson(`${API_BASE}/identities/users?${params}`);
  },

  /**
   * List Databricks workspace groups.
   */
  listGroups: (query?: string, maxResults = 100): Promise<IdentityListResponse> => {
    const params = new URLSearchParams({ max_results: String(maxResults) });
    if (query) params.set('query', query);
    return fetchJson(`${API_BASE}/identities/groups?${params}`);
  },

  // Profile Contributors (Sharing)

  /**
   * List contributors for a profile.
   */
  listContributors: (profileId: number): Promise<ContributorListResponse> =>
    fetchJson(`${API_BASE}/profiles/${profileId}/contributors`),

  /**
   * Add a contributor to a profile.
   */
  addContributor: (profileId: number, data: ContributorCreate): Promise<Contributor> =>
    fetchJson(`${API_BASE}/profiles/${profileId}/contributors`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(data),
    }),

  /**
   * Add multiple contributors to a profile at once.
   */
  addContributorsBulk: (
    profileId: number,
    contributors: ContributorCreate[]
  ): Promise<ContributorListResponse> =>
    fetchJson(`${API_BASE}/profiles/${profileId}/contributors/bulk`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ contributors }),
    }),

  /**
   * Update a contributor's permission level.
   */
  updateContributor: (
    profileId: number,
    contributorId: number,
    data: ContributorUpdate
  ): Promise<Contributor> =>
    fetchJson(`${API_BASE}/profiles/${profileId}/contributors/${contributorId}`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(data),
    }),

  /**
   * Remove a contributor from a profile.
   */
  removeContributor: (profileId: number, contributorId: number): Promise<void> =>
    fetchJson(`${API_BASE}/profiles/${profileId}/contributors/${contributorId}`, {
      method: 'DELETE',
    }),

  // Deck Contributors (Sharing)

  /**
   * List contributors for a deck (session).
   */
  listDeckContributors: (sessionId: string): Promise<ContributorListResponse> =>
    fetchJson(`${SESSIONS_API_BASE}/${sessionId}/contributors`),

  /**
   * Add a contributor to a deck (session).
   */
  addDeckContributor: (sessionId: string, data: ContributorCreate): Promise<Contributor> =>
    fetchJson(`${SESSIONS_API_BASE}/${sessionId}/contributors`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(data),
    }),

  /**
   * Update a deck contributor's permission level.
   */
  updateDeckContributor: (
    sessionId: string,
    contributorId: number,
    data: { permission_level: string }
  ): Promise<Contributor> =>
    fetchJson(`${SESSIONS_API_BASE}/${sessionId}/contributors/${contributorId}`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(data),
    }),

  /**
   * Remove a contributor from a deck (session).
   */
  removeDeckContributor: (sessionId: string, contributorId: number): Promise<void> =>
    fetchJson(`${SESSIONS_API_BASE}/${sessionId}/contributors/${contributorId}`, {
      method: 'DELETE',
    }),

  /**
   * Set or clear workspace-wide sharing for a deck (All workspace users).
   */
  setDeckGlobal: (
    sessionId: string,
    permission: DeckWorkspacePermission | null,
  ): Promise<{ session_id: string; global_permission: DeckWorkspacePermission | null }> =>
    fetchJson(
      `${SESSIONS_API_BASE}/${sessionId}/global${permission ? `?permission=${permission}` : ''}`,
      { method: 'PATCH' },
    ),
};

