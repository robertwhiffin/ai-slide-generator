const DOCS_BASE = 'https://robertwhiffin.github.io/ai-slide-generator/docs';

const userGuide = (slug: string) => `${DOCS_BASE}/user-guide/${slug}`;

export const DOCS_URLS = {
  home: 'https://robertwhiffin.github.io/ai-slide-generator/',

  generatingSlides: userGuide('generating-slides'),
  creatingProfiles: userGuide('creating-profiles'),
  advancedConfig: userGuide('advanced-configuration'),
  customStyles: userGuide('creating-custom-styles'),
  uploadingImages: userGuide('uploading-images'),
  exportingGoogleSlides: userGuide('exporting-to-google-slides'),
  retrievingFeedback: userGuide('retrieving-feedback'),

  customStylesCSS: userGuide('creating-custom-styles#raw-css'),
  customStylesCSSFeatures: userGuide('creating-custom-styles#css-features-that-work'),
  customStylesConstraints: userGuide('creating-custom-styles#fixed-constraints'),

  imageLibrary: userGuide('uploading-images#part-1-the-image-library'),
  pasteToChat: userGuide('uploading-images#part-2-paste-to-chat'),
  imageGuidelines: userGuide('uploading-images#part-3-image-guidelines-in-slide-styles'),

  advancedSlideStyles: userGuide('advanced-configuration#part-2-slide-styles'),
} as const;
