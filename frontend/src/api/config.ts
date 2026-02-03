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

// Types

export interface Profile {
  id: number;
  name: string;
  description: string | null;
  is_default: boolean;
  created_at: string;
  created_by: string | null;
  updated_at: string;
  updated_by: string | null;
}

export interface ProfileDetail extends Profile {
  ai_infra: AIInfraConfig;
  genie_spaces: GenieSpace[];
  prompts: PromptsConfig;
}

export interface ProfileCreate {
  name: string;
  description?: string | null;
}

/**
 * Extended profile creation with inline configurations.
 * Used by the creation wizard to create a complete profile in one request.
 */
export interface ProfileCreateWithConfig {
  name: string;
  description?: string | null;
  genie_space?: {
    space_id: string;
    space_name: string;
    description?: string | null;
  };
  ai_infra?: {
    llm_endpoint?: string;
    llm_temperature?: number;
    llm_max_tokens?: number;
  };
  prompts?: {
    selected_deck_prompt_id?: number | null;
    system_prompt?: string;
    slide_editing_instructions?: string;
  };
}

export interface ProfileUpdate {
  name?: string;
  description?: string | null;
}

export interface ProfileDuplicate {
  new_name: string;
}

export interface AIInfraConfig {
  id: number;
  profile_id: number;
  llm_endpoint: string;
  llm_temperature: number;
  llm_max_tokens: number;
  created_at: string;
  updated_at: string;
}

export interface AIInfraConfigUpdate {
  llm_endpoint?: string;
  llm_temperature?: number;
  llm_max_tokens?: number;
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
  is_active: boolean;
  is_system: boolean;  // Protected system styles cannot be edited/deleted
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
}

export interface SlideStyleUpdate {
  name?: string;
  description?: string | null;
  category?: string | null;
  style_content?: string;
}

export interface SlideStyleListResponse {
  styles: SlideStyle[];
  total: number;
}

export interface EndpointsList {
  endpoints: string[];
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
  llm_endpoint: string;
  sessions_preserved: number;
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
  // Profiles
  
  listProfiles: (): Promise<Profile[]> =>
    fetchJson(`${API_BASE}/profiles`),
  
  getProfile: (id: number): Promise<ProfileDetail> =>
    fetchJson(`${API_BASE}/profiles/${id}`),
  
  getDefaultProfile: (): Promise<ProfileDetail> =>
    fetchJson(`${API_BASE}/profiles/default`),
  
  createProfile: (data: ProfileCreate): Promise<ProfileDetail> =>
    fetchJson(`${API_BASE}/profiles`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(data),
    }),
  
  /**
   * Create a profile with all configurations in one request.
   * Used by the creation wizard for complete profile setup.
   */
  createProfileWithConfig: (data: ProfileCreateWithConfig): Promise<ProfileDetail> =>
    fetchJson(`${API_BASE}/profiles/with-config`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(data),
    }),
  
  updateProfile: (id: number, data: ProfileUpdate): Promise<ProfileDetail> =>
    fetchJson(`${API_BASE}/profiles/${id}`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(data),
    }),
  
  deleteProfile: (id: number): Promise<void> =>
    fetchJson(`${API_BASE}/profiles/${id}`, {
      method: 'DELETE',
    }),
  
  setDefaultProfile: (id: number): Promise<ProfileDetail> =>
    fetchJson(`${API_BASE}/profiles/${id}/set-default`, {
      method: 'POST',
    }),
  
  loadProfile: (id: number): Promise<ReloadResponse> =>
    fetchJson(`${API_BASE}/profiles/${id}/load`, {
      method: 'POST',
    }),
  
  duplicateProfile: (id: number, data: ProfileDuplicate): Promise<ProfileDetail> =>
    fetchJson(`${API_BASE}/profiles/${id}/duplicate`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(data),
    }),
  
  reloadConfiguration: (profileId?: number): Promise<ReloadResponse> => {
    const url = profileId 
      ? `${API_BASE}/profiles/reload?profile_id=${profileId}`
      : `${API_BASE}/profiles/reload`;
    return fetchJson(url, { method: 'POST' });
  },
  
  // AI Infrastructure
  
  getAIInfraConfig: (profileId: number): Promise<AIInfraConfig> =>
    fetchJson(`${API_BASE}/ai-infra/${profileId}`),
  
  updateAIInfraConfig: (profileId: number, data: AIInfraConfigUpdate): Promise<AIInfraConfig> =>
    fetchJson(`${API_BASE}/ai-infra/${profileId}`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(data),
    }),
  
  getAvailableEndpoints: (): Promise<EndpointsList> =>
    fetchJson(`${API_BASE}/ai-infra/endpoints/available`),
  
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
  
  // Validation
  
  validateProfile: (profileId: number): Promise<ValidationResponse> =>
    fetchJson(`${API_BASE}/validate/${profileId}`, {
      method: 'POST',
    }),

  validateLLM: (endpoint: string): Promise<{ success: boolean; message: string; details?: any }> =>
    fetchJson(`${API_BASE}/ai-infra/validate?endpoint=${encodeURIComponent(endpoint)}`, {
      method: 'POST',
    }),

  validateGenie: (spaceId: string): Promise<{ success: boolean; message: string; details?: any }> =>
    fetchJson(`${API_BASE}/genie/validate?space_id=${encodeURIComponent(spaceId)}`, {
      method: 'POST',
    }),
};

