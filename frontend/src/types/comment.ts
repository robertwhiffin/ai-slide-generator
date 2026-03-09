export interface SlideComment {
  id: number;
  slide_id: string;
  user_name: string;
  content: string;
  mentions: string[];
  resolved: boolean;
  resolved_by: string | null;
  resolved_at: string | null;
  parent_comment_id: number | null;
  created_at: string;
  updated_at: string;
  replies: SlideComment[];
  session_id_str?: string;
}
