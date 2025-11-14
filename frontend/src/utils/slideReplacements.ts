import type { Slide, SlideDeck, ReplacementInfo } from '../types/slide';

const cloneDeck = (deck: SlideDeck): SlideDeck => ({
  ...deck,
  slides: deck.slides.map(slide => ({ ...slide })),
  external_scripts: [...deck.external_scripts],
  scripts: deck.scripts ?? '',
});

const buildSlidesFromHtml = (
  htmlSlides: string[],
  startIndex: number,
): Slide[] =>
  htmlSlides.map((html, offset) => ({
    html,
    index: startIndex + offset,
    slide_id: `slide_${startIndex + offset}_${Date.now()}_${offset}`,
  }));

export const applyReplacements = (
  currentDeck: SlideDeck,
  replacementInfo: ReplacementInfo,
): SlideDeck => {
  if (!currentDeck) {
    throw new Error('Cannot apply replacements without an existing slide deck');
  }

  const startIndex =
    replacementInfo.start_index ??
    replacementInfo.original_indices?.[0] ??
    0;
  const originalCount =
    replacementInfo.original_count ??
    replacementInfo.original_indices?.length ??
    0;
  const replacementSlidesHtml = replacementInfo.replacement_slides;

  if (!replacementSlidesHtml || replacementSlidesHtml.length === 0) {
    throw new Error('No replacement slides provided by the backend');
  }

  const nextDeck = cloneDeck(currentDeck);
  const replacementSlides = buildSlidesFromHtml(
    replacementSlidesHtml,
    startIndex,
  );

  nextDeck.slides.splice(startIndex, originalCount, ...replacementSlides);

  nextDeck.slides = nextDeck.slides.map((slide, idx) => ({
    ...slide,
    index: idx,
    slide_id: `slide_${idx}`,
  }));

  nextDeck.slide_count = nextDeck.slides.length;

  const replacementScripts = replacementInfo.replacement_scripts?.trim();
  if (replacementScripts) {
    const existingScripts = nextDeck.scripts?.trim();
    nextDeck.scripts = existingScripts
      ? `${existingScripts}\n\n${replacementScripts}`
      : replacementScripts;
  }

  return nextDeck;
};

export const getReplacementSummary = (info: ReplacementInfo): string => {
  const originalCount =
    info.original_count ?? info.original_indices?.length ?? 0;
  const replacementCount = info.replacement_count ?? 0;
  const netChange =
    info.net_change ?? replacementCount - originalCount;

  if (netChange === 0) {
    return `Replaced ${originalCount} slide${originalCount === 1 ? '' : 's'}`;
  }

  if (netChange > 0) {
    return `Expanded ${originalCount} slide${originalCount === 1 ? '' : 's'} into ${replacementCount} (+${netChange})`;
  }

  return `Condensed ${originalCount} slide${originalCount === 1 ? '' : 's'} into ${replacementCount} (${netChange})`;
};

export const isContiguous = (indices: number[]): boolean => {
  if (indices.length <= 1) {
    return true;
  }

  const sorted = [...indices].sort((a, b) => a - b);
  for (let i = 1; i < sorted.length; i += 1) {
    if (sorted[i] - sorted[i - 1] !== 1) {
      return false;
    }
  }

  return true;
};

