import type { GeneratedImageKind, GeneratedImageRef } from '../types/message';

const LABEL: Record<GeneratedImageKind, string> = {
  illustration: 'illustration',
  icon: 'icon',
  background: 'background',
  vector_icon: 'vector icon',
};

const label = (kind: GeneratedImageKind): string => LABEL[kind] ?? 'illustration';
const withArticle = (kind: GeneratedImageKind): string => {
  const l = label(kind);
  return `${/^[aeiou]/.test(l) ? 'an' : 'a'} ${l}`;
};

/** Not named use*: rules-of-hooks would treat it as a hook. */
export function pickImageMessage(img: GeneratedImageRef): string {
  return img.for_slide
    ? `Use option ${img.option} on slide ${img.for_slide}.`
    : `Use option ${img.option} where it fits best.`;
}

/**
 * Never the stored prompt (R15): it is the model's own, cut to 300 characters, and in the user's
 * bubble it read as the user's words, cut off mid-word. The reply above describes the images.
 */
export function regenerateMessage(images: GeneratedImageRef[]): string {
  const first = images[0];
  const kind = first ? label(first.kind) : 'illustration';
  const slide = first?.for_slide ? ` for slide ${first.for_slide}` : '';
  return `Generate 3 new ${kind} options${slide}.`;
}

export function generateImageMessage(args: {
  prompt: string;
  kind: GeneratedImageKind;
  options: boolean;
  forSlide?: number | null;
}): string {
  const prompt = args.prompt.trim();
  const tail = prompt ? `: ${prompt}` : '.';
  const n = args.forSlide || null;
  if (args.options) {
    return `Generate 3 ${label(args.kind)} options${n ? ` for slide ${n}` : ''}${tail}`;
  }
  return `Generate ${withArticle(args.kind)}${n ? ` and add it to slide ${n}` : ''}${tail}`;
}
