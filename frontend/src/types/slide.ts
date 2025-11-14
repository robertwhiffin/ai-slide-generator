export interface Slide {
  index: number;
  slide_id: string;
  html: string;
}

export interface SlideDeck {
  title: string;
  slide_count: number;
  css: string;
  external_scripts: string[];
  scripts: string;
  slides: Slide[];
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
  replacement_slides?: string[];
  replacement_scripts?: string;
  success?: boolean;
  error?: string | null;
  canvas_ids?: string[];
  script_canvas_ids?: string[];
}
