/**
 * Chat image generation, Unit I (Task 7/8): the chat messages the image buttons send.
 *
 * Contract: docs/superpowers/plans/2026-11-09-chat-image-generation-CORRECTIONS.md, "Unit I interface",
 * `utils/imageChatMessages.ts` (exact strings) and R1 (the "use" builder is `pickImageMessage`, never
 * `useImageMessage`: ESLint rules-of-hooks would treat a `use*` function as a hook).
 *
 * The graph engine ignores `slide_context`, so every message that targets a slide names it in its text.
 *
 *   pickImageMessage(img)
 *     for_slide set -> `Use option ${img.option} on slide ${img.for_slide}.`
 *     otherwise     -> `Use option ${img.option} where it fits best.`
 *   regenerateMessage(images)        (kind / for_slide / prompt of the set; the cards are one set)
 *     `Generate 3 new ${singular(kind)} options${for_slide ? ` for slide ${n}` : ''}.`
 *     (R15: never the prompt. The stored prompt is the model's, cut to 300 characters; in the
 *     user's bubble it read as the user's own words, cut off mid-word.)
 *   generateImageMessage({prompt, kind, options, forSlide})
 *     options: `Generate 3 ${singular(kind)} options${forSlide ? ` for slide ${n}` : ''}: ${prompt}`
 *     single:  `Generate ${a(kind)} and add it to slide ${n}: ${prompt}` when forSlide is set,
 *              else `Generate ${a(kind)}: ${prompt}`
 *     An empty prompt drops the ": ..." part and ends with ".".
 *   kind labels: illustration/illustrations, icon/icons, background/backgrounds, vector icon/vector icons;
 *   a(kind) = "an illustration" | "an icon" | "a background" | "a vector icon".
 *
 * Choice this test adds where CORRECTIONS is silent: the prompt is trimmed, so a whitespace-only
 * prompt counts as empty (the chat trims what it sends anyway; "Generate an icon:   " would arrive as
 * "Generate an icon:").
 */
import { describe, it, expect } from 'vitest';
import * as messages from './imageChatMessages';
import { generateImageMessage, pickImageMessage, regenerateMessage } from './imageChatMessages';
import type { GeneratedImageRef } from '../types/message';

type Kind = GeneratedImageRef['kind'];

const ref = (over: Partial<GeneratedImageRef> = {}): GeneratedImageRef => ({
  token: 'tok1',
  kind: 'illustration',
  option: 1,
  prompt: 'A calm lake at dawn',
  for_slide: null,
  slides: [],
  ...over,
});

const set = (kind: Kind, for_slide: number | null, prompt: string | undefined): GeneratedImageRef[] =>
  [1, 2, 3].map((option) => ref({ token: `tok${option}`, option, kind, for_slide, prompt }));

describe('module surface (R1)', () => {
  it('exports pickImageMessage and no use* builder', () => {
    expect(typeof messages.pickImageMessage).toBe('function');
    expect(Object.keys(messages).filter((k) => /^use[A-Z]/.test(k))).toEqual([]);
  });
});

describe('pickImageMessage', () => {
  it('names the option and the slide when the image was made for a slide', () => {
    expect(pickImageMessage(ref({ option: 2, for_slide: 3 }))).toBe('Use option 2 on slide 3.');
  });

  it('asks for the best fit when the image was made for no slide (null)', () => {
    expect(pickImageMessage(ref({ option: 2, for_slide: null }))).toBe('Use option 2 where it fits best.');
  });

  it('asks for the best fit when for_slide is absent', () => {
    const noSlide: Partial<GeneratedImageRef> = ref({ option: 1 });
    delete noSlide.for_slide;
    expect(pickImageMessage(noSlide as GeneratedImageRef)).toBe('Use option 1 where it fits best.');
  });

  it('never puts the token in the text (the token travels as image_ids)', () => {
    const text = pickImageMessage(ref({ token: 'secretTok_9', option: 3, for_slide: 1 }));
    expect(text).toBe('Use option 3 on slide 1.');
    expect(text).not.toContain('secretTok_9');
  });
});

describe('regenerateMessage', () => {
  it.each<[Kind, number | null, string | undefined, string]>([
    ['illustration', 3, 'A calm lake at dawn', 'Generate 3 new illustration options for slide 3.'],
    ['icon', null, 'A shield', 'Generate 3 new icon options.'],
    ['background', 1, '', 'Generate 3 new background options for slide 1.'],
    ['vector_icon', null, undefined, 'Generate 3 new vector icon options.'],
    ['vector_icon', 2, 'A padlock', 'Generate 3 new vector icon options for slide 2.'],
  ])('%s, slide %s, prompt %j', (kind, forSlide, prompt, expected) => {
    expect(regenerateMessage(set(kind, forSlide, prompt))).toBe(expected);
  });

  it('works from a single image too (count stays 3)', () => {
    expect(regenerateMessage([ref({ kind: 'icon', for_slide: 4, prompt: 'A rocket' })])).toBe(
      'Generate 3 new icon options for slide 4.',
    );
  });
});

describe('generateImageMessage: 3 options', () => {
  it.each<[Kind, string]>([
    ['illustration', 'Generate 3 illustration options for slide 2: A calm lake'],
    ['icon', 'Generate 3 icon options for slide 2: A calm lake'],
    ['background', 'Generate 3 background options for slide 2: A calm lake'],
    ['vector_icon', 'Generate 3 vector icon options for slide 2: A calm lake'],
  ])('%s for a slide', (kind, expected) => {
    expect(generateImageMessage({ prompt: 'A calm lake', kind, options: true, forSlide: 2 })).toBe(expected);
  });

  it('no slide (null)', () => {
    expect(generateImageMessage({ prompt: 'A shield', kind: 'icon', options: true, forSlide: null })).toBe(
      'Generate 3 icon options: A shield',
    );
  });

  it('no slide (absent)', () => {
    expect(generateImageMessage({ prompt: 'A shield', kind: 'icon', options: true })).toBe(
      'Generate 3 icon options: A shield',
    );
  });

  it('empty prompt with a slide ends with "."', () => {
    expect(generateImageMessage({ prompt: '', kind: 'background', options: true, forSlide: 5 })).toBe(
      'Generate 3 background options for slide 5.',
    );
  });

  it('empty prompt and no slide ends with "."', () => {
    expect(generateImageMessage({ prompt: '', kind: 'illustration', options: true, forSlide: null })).toBe(
      'Generate 3 illustration options.',
    );
  });
});

describe('generateImageMessage: a single image', () => {
  it.each<[Kind, string]>([
    ['illustration', 'Generate an illustration and add it to slide 3: A calm lake'],
    ['icon', 'Generate an icon and add it to slide 3: A calm lake'],
    ['background', 'Generate a background and add it to slide 3: A calm lake'],
    ['vector_icon', 'Generate a vector icon and add it to slide 3: A calm lake'],
  ])('%s for a slide: "a"/"an" and "add it to slide N"', (kind, expected) => {
    expect(generateImageMessage({ prompt: 'A calm lake', kind, options: false, forSlide: 3 })).toBe(expected);
  });

  it.each<[Kind, string]>([
    ['illustration', 'Generate an illustration: A calm lake'],
    ['icon', 'Generate an icon: A calm lake'],
    ['background', 'Generate a background: A calm lake'],
    ['vector_icon', 'Generate a vector icon: A calm lake'],
  ])('%s with no slide', (kind, expected) => {
    expect(generateImageMessage({ prompt: 'A calm lake', kind, options: false, forSlide: null })).toBe(expected);
  });

  it('empty prompt with a slide ends with "."', () => {
    expect(generateImageMessage({ prompt: '', kind: 'icon', options: false, forSlide: 2 })).toBe(
      'Generate an icon and add it to slide 2.',
    );
  });

  it('empty prompt and no slide ends with "."', () => {
    expect(generateImageMessage({ prompt: '', kind: 'background', options: false })).toBe('Generate a background.');
  });
});

describe('generateImageMessage: the prompt is trimmed', () => {
  it('surrounding whitespace is removed', () => {
    expect(generateImageMessage({ prompt: '  A shield \n', kind: 'icon', options: false, forSlide: 1 })).toBe(
      'Generate an icon and add it to slide 1: A shield',
    );
  });

  it('a whitespace-only prompt counts as empty', () => {
    expect(generateImageMessage({ prompt: '   ', kind: 'icon', options: true, forSlide: 4 })).toBe(
      'Generate 3 icon options for slide 4.',
    );
  });
});

// Controller addition (R15): a long stored prompt (the model's, cut to 300 characters) never
// reaches the message the user's bubble shows.
describe('regenerateMessage never carries the stored prompt', () => {
  it('drops a long, truncated prompt', () => {
    const long = 'Flat, modern vector-style illustration of data silos with broken connection lines be';
    const text = regenerateMessage([ref({ kind: 'illustration', for_slide: 2, prompt: long })]);
    expect(text).toBe('Generate 3 new illustration options for slide 2.');
    expect(text).not.toContain('broken');
  });
});
