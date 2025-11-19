/**
 * Configuration API client for profile and settings management.
 * 
 * Provides methods to interact with the database-backed configuration system.
 */

// Use relative URLs in production, localhost in development
const API_BASE_URL = import.meta.env.VITE_API_URL || (
  import.meta.env.MODE === 'production' ? '' : 'http://localhost:8000'
);

const API_BASE = `${API_BASE_URL}/api/config`;

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
  mlflow: MLflowConfig;
  prompts: PromptsConfig;
}

export interface ProfileCreate {
  name: string;
  description?: string | null;
  copy_from_profile_id?: number | null;
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

export interface GenieSpace {
  id: number;
  profile_id: number;
  space_id: string;
  space_name: string;
  description: string | null;
  is_default: boolean;
  created_at: string;
  updated_at: string;
}

export interface GenieSpaceCreate {
  space_id: string;
  space_name: string;
  description?: string | null;
  is_default?: boolean;
}

export interface GenieSpaceUpdate {
  space_name?: string;
  description?: string | null;
}

export interface MLflowConfig {
  id: number;
  profile_id: number;
  experiment_name: string;
  created_at: string;
  updated_at: string;
}

export interface MLflowConfigUpdate {
  experiment_name: string;
}

export interface PromptsConfig {
  id: number;
  profile_id: number;
  system_prompt: string;
  slide_editing_instructions: string;
  user_prompt_template: string;
  created_at: string;
  updated_at: string;
}

export interface PromptsConfigUpdate {
  system_prompt?: string;
  slide_editing_instructions?: string;
  user_prompt_template?: string;
}

export interface EndpointsList {
  endpoints: string[];
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
  
  listGenieSpaces: (profileId: number): Promise<GenieSpace[]> =>
    fetchJson(`${API_BASE}/genie/${profileId}`),
  
  getDefaultGenieSpace: (profileId: number): Promise<GenieSpace> =>
    fetchJson(`${API_BASE}/genie/${profileId}/default`),
  
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
  
  setDefaultGenieSpace: (spaceId: number): Promise<GenieSpace> =>
    fetchJson(`${API_BASE}/genie/space/${spaceId}/set-default`, {
      method: 'POST',
    }),
  
  // MLflow
  
  getMLflowConfig: (profileId: number): Promise<MLflowConfig> =>
    fetchJson(`${API_BASE}/mlflow/${profileId}`),
  
  updateMLflowConfig: (profileId: number, data: MLflowConfigUpdate): Promise<MLflowConfig> =>
    fetchJson(`${API_BASE}/mlflow/${profileId}`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(data),
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
};

