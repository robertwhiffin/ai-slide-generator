/** One line of a prompt diff. Rendered as text only, never as markup. */
export type DiffLine = { kind: 'same' | 'removed' | 'added'; text: string };

/**
 * A longest-common-subsequence line diff of `before` → `after`. Ties prefer the removal,
 * so a replaced line reads as `removed` then `added`. An empty input is one empty line.
 */
export function lineDiff(before: string, after: string): DiffLine[] {
  const a = before.split('\n');
  const b = after.split('\n');
  const lcs: number[][] = Array.from({ length: a.length + 1 }, () => Array<number>(b.length + 1).fill(0));
  for (let i = a.length - 1; i >= 0; i -= 1) {
    for (let j = b.length - 1; j >= 0; j -= 1) {
      lcs[i][j] = a[i] === b[j] ? lcs[i + 1][j + 1] + 1 : Math.max(lcs[i + 1][j], lcs[i][j + 1]);
    }
  }
  const out: DiffLine[] = [];
  let i = 0;
  let j = 0;
  while (i < a.length && j < b.length) {
    if (a[i] === b[j]) {
      out.push({ kind: 'same', text: a[i] });
      i += 1;
      j += 1;
    } else if (lcs[i + 1][j] >= lcs[i][j + 1]) {
      out.push({ kind: 'removed', text: a[i] });
      i += 1;
    } else {
      out.push({ kind: 'added', text: b[j] });
      j += 1;
    }
  }
  while (i < a.length) {
    out.push({ kind: 'removed', text: a[i] });
    i += 1;
  }
  while (j < b.length) {
    out.push({ kind: 'added', text: b[j] });
    j += 1;
  }
  return out;
}
