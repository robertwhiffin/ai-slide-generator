import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { readBlobText } from '../test/readBlobText';
import { REVOKE_DELAY_MS, downloadTextFile } from './downloadFile';

const MARKDOWN_MIME = 'text/markdown;charset=utf-8';
const CONTENT = 'héllo — wörld\n';
const FILENAME = 'a-spec.md';
const OBJECT_URL = 'blob:http://localhost/tellr-test-object-url';

// FileReader.readAsText decodes as UTF-8 and silently strips a leading BOM, so a text read cannot
// see one. Compare raw bytes to pin "no BOM" (RFC 7763 text/markdown;charset=utf-8).
function readBlobBytes(blob: Blob): Promise<number[]> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(Array.from(new Uint8Array(reader.result as ArrayBuffer)));
    reader.onerror = () => reject(reader.error);
    reader.readAsArrayBuffer(blob);
  });
}

interface RecordedClick {
  download: string;
  href: string | null;
  isConnected: boolean;
}

describe('downloadTextFile', () => {
  // Ordered log across the three browser entry points the helper must use.
  let callLog: string[];
  let createdBlobs: Blob[];
  let revokedUrls: string[];
  let clicks: RecordedClick[];
  let createObjectURL: ReturnType<typeof vi.fn>;
  let revokeObjectURL: ReturnType<typeof vi.fn>;

  beforeEach(() => {
    // Fake ONLY these two. The default vi.useFakeTimers() also fakes setImmediate, which
    // jsdom's FileReader uses, so readBlobText would never settle.
    vi.useFakeTimers({ toFake: ['setTimeout', 'clearTimeout'] });

    callLog = [];
    createdBlobs = [];
    revokedUrls = [];
    clicks = [];

    // jsdom implements neither URL.createObjectURL nor URL.revokeObjectURL.
    createObjectURL = vi.fn((blob: Blob) => {
      callLog.push('createObjectURL');
      createdBlobs.push(blob);
      return OBJECT_URL;
    });
    revokeObjectURL = vi.fn((url: string) => {
      callLog.push('revokeObjectURL');
      revokedUrls.push(url);
    });
    Object.defineProperty(URL, 'createObjectURL', {
      configurable: true,
      writable: true,
      value: createObjectURL,
    });
    Object.defineProperty(URL, 'revokeObjectURL', {
      configurable: true,
      writable: true,
      value: revokeObjectURL,
    });

    // Without this stub jsdom logs "not implemented: navigation" on an <a download> click.
    vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(function (
      this: HTMLAnchorElement,
    ) {
      callLog.push('click');
      clicks.push({
        download: this.download,
        href: this.getAttribute('href'),
        isConnected: this.isConnected,
      });
    });
  });

  afterEach(() => {
    vi.useRealTimers();
    vi.restoreAllMocks();
    Reflect.deleteProperty(URL, 'createObjectURL');
    Reflect.deleteProperty(URL, 'revokeObjectURL');
    // Keep a leftover anchor from one test from leaking into the next.
    document.body.replaceChildren();
  });

  it('wraps the text, byte for byte, in a single markdown Blob with a utf-8 charset', async () => {
    downloadTextFile(CONTENT, FILENAME, MARKDOWN_MIME);

    expect(createObjectURL).toHaveBeenCalledTimes(1);
    expect(createdBlobs).toHaveLength(1);
    const blob = createdBlobs[0];
    expect(blob).toBeInstanceOf(Blob);
    expect(blob.type).toBe('text/markdown;charset=utf-8');
    expect(await readBlobText(blob)).toBe('héllo — wörld\n');
    // Exactly the UTF-8 bytes of the text: no BOM, no re-encoding.
    expect(await readBlobBytes(blob)).toEqual(Array.from(new TextEncoder().encode('héllo — wörld\n')));
  });

  it('clicks exactly one anchor, named for the file, pointing at the object URL, while attached to the document', () => {
    downloadTextFile(CONTENT, FILENAME, MARKDOWN_MIME);

    expect(clicks).toHaveLength(1);
    expect(clicks[0].download).toBe('a-spec.md');
    expect(clicks[0].href).toBe(OBJECT_URL);
    // A detached anchor's click() is ignored by Firefox, so it must be in the document.
    expect(clicks[0].isConnected).toBe(true);
  });

  it('takes the text, file name and MIME type from its arguments, not from fixed values', async () => {
    // A different triple from the other tests, so a helper that hardcodes any of the three fails.
    // The trailing whitespace and CRLF also pin that the text is not trimmed or re-lined.
    const text = 'plain tèxt, no markdown\r\n  ';
    downloadTextFile(text, 'notes-2.txt', 'text/plain;charset=utf-8');

    expect(createdBlobs).toHaveLength(1);
    expect(createdBlobs[0].type).toBe('text/plain;charset=utf-8');
    expect(await readBlobText(createdBlobs[0])).toBe(text);
    expect(clicks).toHaveLength(1);
    expect(clicks[0].download).toBe('notes-2.txt');
  });

  it('creates the object URL before it clicks', () => {
    downloadTextFile(CONTENT, FILENAME, MARKDOWN_MIME);

    expect(callLog.slice(0, 2)).toEqual(['createObjectURL', 'click']);
  });

  it('defers the revoke: not at click time, not one ms before the delay, once with the same URL on the last ms', async () => {
    downloadTextFile(CONTENT, FILENAME, MARKDOWN_MIME);

    // Not synchronously, i.e. not while the browser may still be reading the blob.
    expect(revokeObjectURL).not.toHaveBeenCalled();
    // Nor on the microtask queue (queueMicrotask / Promise.then), which drains before the
    // browser has even started the download. Only the faked setTimeout may release it.
    await Promise.resolve();
    expect(revokeObjectURL).not.toHaveBeenCalled();

    vi.advanceTimersByTime(REVOKE_DELAY_MS - 1);
    expect(revokeObjectURL).not.toHaveBeenCalled();

    vi.advanceTimersByTime(1);
    expect(revokeObjectURL).toHaveBeenCalledTimes(1);
    expect(revokedUrls).toEqual([OBJECT_URL]);
    expect(revokeObjectURL).toHaveBeenCalledWith(createObjectURL.mock.results[0].value);

    // Revoke is a one-shot, and it comes after the click.
    vi.advanceTimersByTime(REVOKE_DELAY_MS * 3);
    expect(revokeObjectURL).toHaveBeenCalledTimes(1);
    expect(callLog).toEqual(['createObjectURL', 'click', 'revokeObjectURL']);
  });

  it('holds the object URL for ten seconds', () => {
    expect(REVOKE_DELAY_MS).toBe(10_000);
  });

  it('leaves no download anchor in the document, during or after the revoke delay', () => {
    downloadTextFile(CONTENT, FILENAME, MARKDOWN_MIME);
    expect(document.querySelectorAll('a[download]')).toHaveLength(0);

    vi.advanceTimersByTime(REVOKE_DELAY_MS);
    expect(document.querySelectorAll('a[download]')).toHaveLength(0);
  });
});
