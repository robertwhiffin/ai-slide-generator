/**
 * Chat image generation, Unit I (Task 6): `readGeneratedImages(value: unknown): GeneratedImageRef[]`.
 *
 * Contract: docs/superpowers/plans/2026-11-09-chat-image-generation-CORRECTIONS.md, "Shared metadata
 * shape" and "Unit I interface". The same rules as the backend sanitiser:
 *   - the value must be an array, otherwise [];
 *   - `token` matches ^[A-Za-z0-9_-]+$, `kind` is one of illustration | background | icon | vector_icon,
 *     `option` is an integer >= 1; an entry failing any of these is DROPPED;
 *   - `for_slide` is an integer >= 1 or null; `slides` is a list of integers >= 1 ([] when unplaced);
 *   - unknown keys are dropped;
 *   - it never throws.
 *
 * Choices this test makes where CORRECTIONS is silent (the implementer must match them):
 *   - an entry with no `slides` (or a non-array `slides`) is kept with `slides: []`;
 *   - non-integer / < 1 members of `slides` are filtered out, the entry is kept;
 *   - an invalid `for_slide` (0, "3", 2.5, true) is read as "no slide" (null/absent), the entry is kept;
 *   - a non-string `prompt` is left out, the entry is kept;
 *   - booleans are never numbers (Python's bool-is-int trap).
 */
import { describe, it, expect } from 'vitest';
import { readGeneratedImages } from './generatedImages';

const VALID = [
  { token: 'abc_DEF-1', kind: 'illustration', option: 1, prompt: 'A calm lake at dawn', for_slide: 3, slides: [] },
  { token: 'tok2', kind: 'icon', option: 2, prompt: 'A shield', for_slide: null, slides: [2] },
  { token: 'TOK_3', kind: 'background', option: 3, prompt: 'Soft blue gradient', for_slide: 1, slides: [1, 4] },
  { token: 'v-4', kind: 'vector_icon', option: 4, prompt: 'A lock', for_slide: 2, slides: [] },
];

const base = { token: 'okTok', kind: 'illustration', option: 1, prompt: 'p', for_slide: 2, slides: [] as number[] };

describe('readGeneratedImages', () => {
  it('keeps a valid list exactly, in order, covering every kind', () => {
    const input = structuredClone(VALID);
    expect(readGeneratedImages(input)).toStrictEqual(VALID);
  });

  it('does not mutate its input', () => {
    const input = structuredClone(VALID);
    readGeneratedImages(input);
    expect(input).toStrictEqual(VALID);
  });

  it.each([
    ['undefined', undefined],
    ['null', null],
    ['a string', 'generated_images'],
    ['a number', 3],
    ['a boolean', true],
    ['an object', { token: 'tok1', kind: 'icon', option: 1, slides: [] }],
    ['an object wrapping the list', { generated_images: VALID }],
  ])('returns [] for %s', (_label, value) => {
    expect(readGeneratedImages(value)).toEqual([]);
  });

  it('returns [] for an empty array', () => {
    expect(readGeneratedImages([])).toEqual([]);
  });

  it('drops entries that are not objects, keeping the valid ones around them', () => {
    const out = readGeneratedImages([null, 'tok1', 7, ['tok1'], VALID[0], undefined, VALID[1]]);
    expect(out).toStrictEqual([VALID[0], VALID[1]]);
  });

  it.each([
    ['missing', undefined],
    ['empty', ''],
    ['with a space', 'bad token'],
    ['with a slash', 'a/b'],
    ['with a dot', 'a.b'],
    ['with a brace (a {{image:..}} injection)', 'tok}}'],
    ['a number', 12],
    ['null', null],
  ])('drops an entry whose token is %s', (_label, token) => {
    expect(readGeneratedImages([{ ...base, token }, VALID[1]])).toStrictEqual([VALID[1]]);
  });

  it.each([
    ['missing', undefined],
    ['unknown', 'photo'],
    ['wrong case', 'Icon'],
    ['the preset id, not the kind', 'icon_png'],
    ['a number', 1],
  ])('drops an entry whose kind is %s', (_label, kind) => {
    expect(readGeneratedImages([{ ...base, kind }, VALID[1]])).toStrictEqual([VALID[1]]);
  });

  it.each([
    ['missing', undefined],
    ['zero', 0],
    ['negative', -1],
    ['fractional', 1.5],
    ['a numeric string', '2'],
    ['NaN', Number.NaN],
    ['Infinity', Number.POSITIVE_INFINITY],
    ['a boolean', true],
    ['null', null],
  ])('drops an entry whose option is %s', (_label, option) => {
    expect(readGeneratedImages([{ ...base, option }, VALID[1]])).toStrictEqual([VALID[1]]);
  });

  it('drops unknown keys', () => {
    const out = readGeneratedImages([
      { ...VALID[0], data_uri: 'data:image/png;base64,AAAA', model: 'gpt-image', extra: { nested: true } },
    ]);
    expect(out).toStrictEqual([VALID[0]]);
    expect(Object.keys(out[0]).sort()).toEqual(['for_slide', 'kind', 'option', 'prompt', 'slides', 'token']);
  });

  it('reads a missing or non-array slides as [] and keeps the entry', () => {
    const noSlides: Record<string, unknown> = { ...base };
    delete noSlides.slides;
    const out = readGeneratedImages([noSlides, { ...base, token: 'tokB', slides: '2' }, { ...base, token: 'tokC', slides: null }]);
    expect(out.map((r) => r.token)).toEqual(['okTok', 'tokB', 'tokC']);
    for (const ref of out) expect(ref.slides).toEqual([]);
  });

  it('keeps only integer slide numbers >= 1', () => {
    const out = readGeneratedImages([{ ...base, slides: [2, 0, -1, 'x', 2.5, true, null, 4] }]);
    expect(out).toHaveLength(1);
    expect(out[0].slides).toEqual([2, 4]);
  });

  it.each([
    ['zero', 0],
    ['negative', -2],
    ['a numeric string', '3'],
    ['fractional', 2.5],
    ['a boolean', true],
    ['an object', { n: 3 }],
  ])('reads an invalid for_slide (%s) as no slide and keeps the entry', (_label, forSlide) => {
    const out = readGeneratedImages([{ ...base, for_slide: forSlide }]);
    expect(out).toHaveLength(1);
    expect(out[0].token).toBe('okTok');
    expect(out[0].for_slide ?? null).toBeNull();
  });

  it('keeps an entry with no for_slide and no prompt', () => {
    const out = readGeneratedImages([{ token: 'bare', kind: 'icon', option: 1, slides: [] }]);
    expect(out).toHaveLength(1);
    expect(out[0]).toMatchObject({ token: 'bare', kind: 'icon', option: 1, slides: [] });
    expect(out[0].for_slide ?? null).toBeNull();
    expect(out[0].prompt).toBeUndefined();
  });

  it('leaves out a non-string prompt and keeps the entry', () => {
    const out = readGeneratedImages([{ ...base, prompt: { text: 'x' } }]);
    expect(out).toHaveLength(1);
    expect(out[0].token).toBe('okTok');
    expect(out[0].prompt).toBeUndefined();
  });

  it('never throws, even on an entry whose properties throw when read', () => {
    const hostile = Object.defineProperty({ kind: 'icon', option: 1, slides: [] }, 'token', {
      enumerable: true,
      get() {
        throw new Error('boom');
      },
    });
    const revoked = Proxy.revocable({}, {});
    revoked.revoke();
    let out: unknown;
    expect(() => {
      out = readGeneratedImages([hostile, revoked.proxy, VALID[1]]);
    }).not.toThrow();
    // Whatever survives is well-formed; a valid entry next to the junk is never invented.
    expect(Array.isArray(out)).toBe(true);
    for (const ref of out as Array<{ token: unknown }>) expect(ref.token).toBe('tok2');
  });
});
