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
