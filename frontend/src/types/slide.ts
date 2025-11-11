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
