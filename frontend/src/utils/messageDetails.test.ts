/**
 * `readMessageDetails` turns whatever the backend sent as `metadata.details` into the
 * string-to-string map the chat's Details disclosure renders — or `undefined`, which means
 * "render no disclosure". Old rows, tool rows and malformed payloads must all land on
 * `undefined`, never on an empty map or on the raw input.
 */
import { describe, it, expect } from 'vitest';
import { readMessageDetails } from './messageDetails';

describe('readMessageDetails', () => {
  it.each([
    ['null', null],
    ['undefined', undefined],
    ['a string', 'x'],
    ['an empty array', []],
    ['a non-empty array', ['stage']],
    ['an empty object', {}],
    ['an object with no string values', { a: 1 }],
    ['an object whose only string is empty', { error: '' }],
  ])('returns undefined for %s', (_label, value) => {
    expect(readMessageDetails(value)).toBeUndefined();
  });

  it('keeps only the non-empty string values', () => {
    const value = {
      stage: 'builder',
      error: '',
      request_id: 'req-1',
      count: 3,
      nested: { stage: 'reviewer' },
      missing: null,
      flag: true,
    };

    expect(readMessageDetails(value)).toEqual({ stage: 'builder', request_id: 'req-1' });
  });

  it('returns a copy, so mutating the result leaves the input unchanged', () => {
    const value = { stage: 'builder', error: 'RuntimeError', request_id: 'req-1' };

    const result = readMessageDetails(value);

    expect(result).toEqual(value);
    expect(result).not.toBe(value);
    result!.stage = 'mutated';
    result!.extra = 'added';
    expect(value).toEqual({ stage: 'builder', error: 'RuntimeError', request_id: 'req-1' });
  });
});
