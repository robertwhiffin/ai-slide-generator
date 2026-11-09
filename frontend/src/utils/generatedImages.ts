import type { GeneratedImageKind, GeneratedImageRef } from '../types/message';

const KINDS: readonly string[] = ['illustration', 'background', 'icon', 'vector_icon'];
const TOKEN_RE = /^[A-Za-z0-9_-]+$/;

const isPosInt = (v: unknown): v is number =>
  typeof v === 'number' && Number.isInteger(v) && v >= 1;

function readOne(raw: unknown): GeneratedImageRef | null {
  if (typeof raw !== 'object' || raw === null || Array.isArray(raw)) return null;
  const r = raw as Record<string, unknown>;
  const { token, kind, option } = r;
  if (typeof token !== 'string' || !TOKEN_RE.test(token)) return null;
  if (typeof kind !== 'string' || !KINDS.includes(kind)) return null;
  if (!isPosInt(option)) return null;
  const slides = Array.isArray(r.slides) ? r.slides.filter(isPosInt) : [];
  const ref: GeneratedImageRef = {
    token,
    kind: kind as GeneratedImageKind,
    option,
    for_slide: isPosInt(r.for_slide) ? r.for_slide : null,
    slides,
  };
  if (typeof r.prompt === 'string') ref.prompt = r.prompt;
  return ref;
}

/** Read server `generated_images` metadata; drops junk, never throws. */
export function readGeneratedImages(value: unknown): GeneratedImageRef[] {
  if (!Array.isArray(value)) return [];
  const out: GeneratedImageRef[] = [];
  for (const raw of value) {
    try {
      const ref = readOne(raw);
      if (ref) out.push(ref);
    } catch {
      // A hostile entry is dropped, never fatal.
    }
  }
  return out;
}
