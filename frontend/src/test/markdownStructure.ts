/**
 * Test-only: parse Markdown with a real CommonMark parser (micromark via
 * mdast-util-from-markdown — strict CommonMark, no GFM) and read its STRUCTURE, so the
 * deck-spec Markdown tests assert what a reader's renderer will build, not escape strings.
 */
import { fromMarkdown } from 'mdast-util-from-markdown';

export interface MdNode { type: string; depth?: number; ordered?: boolean | null; value?: string; children?: MdNode[] }
export type Skeleton = { type: string; depth?: number; ordered?: boolean | null; children: Skeleton[] };

export const ALLOWED_NODE_TYPES: ReadonlySet<string> =
  new Set(['root', 'heading', 'paragraph', 'text', 'list', 'listItem', 'strong']);

export function parseMarkdown(markdown: string): MdNode { return fromMarkdown(markdown) as unknown as MdNode; }
/**
 * D4's normalisation, restated INDEPENDENTLY of the renderer (explicit code points), so an expectation
 * normalised here cannot inherit a production drift: controls removed, whitespace runs
 * (ECMAScript whitespace plus NEL) collapsed to one space, trimmed.
 */
// eslint-disable-next-line no-control-regex -- the control set is the point
const CONTROL = /[\u0000-\u0008\u000E-\u001F\u007F-\u0084\u0086-\u009F]/g;
const WHITESPACE = /[\t\n\v\f\r \u0085\u00A0\u1680\u2000-\u200A\u2028\u2029\u202F\u205F\u3000\uFEFF]+/g;
export function normaliseText(text: string): string { return text.replace(CONTROL, '').replace(WHITESPACE, ' ').trim(); }
export function plainText(node: MdNode): string {
  return typeof node.value === 'string' ? node.value : (node.children ?? []).map(plainText).join('');
}
function walk(node: MdNode, visit: (n: MdNode) => void): void { visit(node); (node.children ?? []).forEach((c) => walk(c, visit)); }
export function nodeTypes(root: MdNode): Set<string> { const s = new Set<string>(); walk(root, (n) => s.add(n.type)); return s; }
export function headings(root: MdNode): Array<[number, string]> {
  const out: Array<[number, string]> = [];
  walk(root, (n) => { if (n.type === 'heading') out.push([n.depth ?? 0, normaliseText(plainText(n))]); });
  return out;
}
export function strongTexts(root: MdNode): string[] {
  const out: string[] = []; walk(root, (n) => { if (n.type === 'strong') out.push(plainText(n)); }); return out;
}
/** Whitespace-normalised text of every heading and paragraph, document order. */
export function blockTexts(root: MdNode): string[] {
  const out: string[] = [];
  walk(root, (n) => { if (n.type === 'heading' || n.type === 'paragraph') out.push(normaliseText(plainText(n))); });
  return out;
}
/** Block structure with the expected inline content (text, strong) dropped; anything injected shows up. */
export function blockSkeleton(node: MdNode): Skeleton | null {
  if (node.type === 'text' || node.type === 'strong') return null;
  return {
    type: node.type, depth: node.depth, ordered: node.ordered,
    children: (node.children ?? []).map(blockSkeleton).filter((c): c is Skeleton => c !== null),
  };
}
