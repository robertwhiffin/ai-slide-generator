import type { VerificationResult } from './verification';

export interface Slide {
  index: number;
  slide_id: string;
  html: string;
  scripts: string;  // JavaScript for this slide's charts (e.g., Chart.js initialization)
  verification?: VerificationResult;  // LLM as Judge verification result (merged from verification_map)
  content_hash?: string;  // Hash of slide content for verification lookup
}

export interface SlideDeck {
  title: string;
  slide_count: number;
  css: string;
  external_scripts: string[];
  scripts: string;
  slides: Slide[];
  html_content?: string; // Raw HTML for debug view (only present when restoring from history)
}

export interface SlideContext {
  indices: number[];
  slide_htmls: string[];
}

export interface ReplacementInfo {
  start_index?: number;
  original_count?: number;
  replacement_count?: number;
  net_change?: number;
  operation?: string;
  original_indices?: number[];
  success?: boolean;
  error?: string | null;
  canvas_ids?: string[];
  is_add_operation?: boolean;
}
