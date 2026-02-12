export interface ImageAsset {
  id: number;
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
  id: number;
  mime_type: string;
  base64_data: string;
  data_uri: string;
}
