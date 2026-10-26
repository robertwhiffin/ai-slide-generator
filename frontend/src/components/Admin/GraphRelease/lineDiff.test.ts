import { describe, expect, it } from 'vitest';
import { lineDiff } from './lineDiff';

describe('lineDiff', () => {
  it('keeps shared lines and marks a replaced line as removed then added', () => {
    expect(lineDiff('Plan the deck.\nUse three sections.\nCite sources.', 'Plan the deck.\nUse four sections.\nCite sources.'))
      .toEqual([
        { kind: 'same', text: 'Plan the deck.' },
        { kind: 'removed', text: 'Use three sections.' },
        { kind: 'added', text: 'Use four sections.' },
        { kind: 'same', text: 'Cite sources.' },
      ]);
  });

  it('is a longest-common-subsequence diff, not a positional one', () => {
    // A positional diff would mark every line after the insertion as changed.
    expect(lineDiff('a\nb\nc', 'x\na\nb\nc')).toEqual([
      { kind: 'added', text: 'x' },
      { kind: 'same', text: 'a' },
      { kind: 'same', text: 'b' },
      { kind: 'same', text: 'c' },
    ]);
    expect(lineDiff('a\nb\nc\nd', 'a\nc\nd\ne')).toEqual([
      { kind: 'same', text: 'a' },
      { kind: 'removed', text: 'b' },
      { kind: 'same', text: 'c' },
      { kind: 'same', text: 'd' },
      { kind: 'added', text: 'e' },
    ]);
  });

  it('diffs empty inputs as a single empty line', () => {
    expect(lineDiff('', '')).toEqual([{ kind: 'same', text: '' }]);
    expect(lineDiff('', 'one\ntwo')).toEqual([
      { kind: 'removed', text: '' },
      { kind: 'added', text: 'one' },
      { kind: 'added', text: 'two' },
    ]);
    expect(lineDiff('one', '')).toEqual([
      { kind: 'removed', text: 'one' },
      { kind: 'added', text: '' },
    ]);
  });

  it('marks every line of identical inputs as the same', () => {
    const prompt = 'Line one\n\nLine three\n';
    expect(lineDiff(prompt, prompt)).toEqual([
      { kind: 'same', text: 'Line one' },
      { kind: 'same', text: '' },
      { kind: 'same', text: 'Line three' },
      { kind: 'same', text: '' },
    ]);
  });

  it('keeps markup-like lines as plain text', () => {
    expect(lineDiff('<b>old</b>', '<script>x</script>')).toEqual([
      { kind: 'removed', text: '<b>old</b>' },
      { kind: 'added', text: '<script>x</script>' },
    ]);
  });
});
