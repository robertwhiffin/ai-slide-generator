export interface ImageAsset {
  id: string; // Opaque token (SDR-4437 F-TM-7) — never the internal int PK.
  filename: string;
  original_filename: string;
  mime_type: string;
  size_bytes: number;
  thumbnail_base64: string | null;
  tags: string[];
  description: string | null;
  category: string | null;
  uploaded_by: string | null;
  is_active: boolean;
  created_at: string;
  updated_at: string;
}

export interface ImageListResponse {
  images: ImageAsset[];
  total: number;
}

export interface ImageDataResponse {
  id: string; // Opaque token (SDR-4437 F-TM-7).
  mime_type: string;
  base64_data: string;
  data_uri: string;
}

export interface ImageModelOption {
  id: string;
  label: string;
  description: string;
}

export interface ImagePresetOption {
  id: string;
  label: string;
  description: string;
  output_format: 'jpeg' | 'png' | 'svg';
  category: string;
  transparent: boolean;
  models: ImageModelOption[];
  default_model: string;
  qualities: string[];
  default_quality: string;
}

export interface ImageEditOptions {
  models: ImageModelOption[];
  default_model: string;
  qualities: string[];
  default_quality: string;
}

export interface ImageGenerationOptions {
  available: boolean;
  max_prompt_chars: number;
  default_preset: string | null;
  presets: ImagePresetOption[];
  edit: ImageEditOptions | null;
  /** What each quality is for, keyed by quality id; shown under the Quality picker. */
  quality_descriptions?: Record<string, string>;
}

export interface ImageGenerationRequest {
  prompt: string;
  preset: string;
  model?: string;
  quality?: string;
}

export interface ImageEditRequest {
  prompt: string;
  model?: string;
  quality?: string;
}

export interface ImageGenerationJob {
  job_id: string;
  status: 'pending' | 'running' | 'completed' | 'error';
  progress: number;
  total_slides: number;
  status_message?: string | null;
  error?: string | null;
  image?: ImageAsset | null;
}
