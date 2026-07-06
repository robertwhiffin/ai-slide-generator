/**
 * Dependency-free zip reader for pptx forensics in Node-side tests.
 *
 * pptxgenjs (via jszip) writes plain zip32 archives with STORE or DEFLATE
 * entries — nothing else — so a minimal central-directory walk plus
 * `zlib.inflateRawSync` covers everything the export tests need without
 * adding a zip dependency to the frontend package. Not a general-purpose
 * unzipper (no zip64, no encryption, no data-descriptor streaming).
 */
import { inflateRawSync } from 'node:zlib';

const EOCD_SIG = 0x06054b50;
const CENTRAL_SIG = 0x02014b50;
const LOCAL_SIG = 0x04034b50;

/** Read every entry of a zip buffer into name → uncompressed bytes. */
export function readZipEntries(buf: Buffer): Map<string, Buffer> {
  // EOCD is at the end, possibly preceded by a comment (max 65535 bytes).
  let eocd = -1;
  const scanStart = Math.max(0, buf.length - 22 - 65535);
  for (let i = buf.length - 22; i >= scanStart; i--) {
    if (buf.readUInt32LE(i) === EOCD_SIG) {
      eocd = i;
      break;
    }
  }
  if (eocd < 0) throw new Error('zip: end-of-central-directory not found');

  const entryCount = buf.readUInt16LE(eocd + 10);
  let offset = buf.readUInt32LE(eocd + 16);

  const entries = new Map<string, Buffer>();
  for (let i = 0; i < entryCount; i++) {
    if (buf.readUInt32LE(offset) !== CENTRAL_SIG) {
      throw new Error(`zip: bad central directory signature at ${offset}`);
    }
    const method = buf.readUInt16LE(offset + 10);
    const compressedSize = buf.readUInt32LE(offset + 20);
    const nameLength = buf.readUInt16LE(offset + 28);
    const extraLength = buf.readUInt16LE(offset + 30);
    const commentLength = buf.readUInt16LE(offset + 32);
    const localOffset = buf.readUInt32LE(offset + 42);
    const name = buf.subarray(offset + 46, offset + 46 + nameLength).toString('utf8');

    if (buf.readUInt32LE(localOffset) !== LOCAL_SIG) {
      throw new Error(`zip: bad local header for ${name}`);
    }
    // Local extra field length can differ from the central one — honor it.
    const localNameLength = buf.readUInt16LE(localOffset + 26);
    const localExtraLength = buf.readUInt16LE(localOffset + 28);
    const dataStart = localOffset + 30 + localNameLength + localExtraLength;
    const raw = buf.subarray(dataStart, dataStart + compressedSize);

    let data: Buffer;
    if (method === 0) data = Buffer.from(raw);
    else if (method === 8) data = inflateRawSync(raw);
    else throw new Error(`zip: unsupported compression method ${method} for ${name}`);
    entries.set(name, data);

    offset += 46 + nameLength + extraLength + commentLength;
  }
  return entries;
}

/** Width/height of a PNG buffer (IHDR is always the first chunk). */
export function pngDimensions(data: Buffer): { width: number; height: number } {
  const magic = Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a]);
  if (!data.subarray(0, 8).equals(magic)) {
    throw new Error(`not a PNG: ${data.subarray(0, 12).toString('hex')}`);
  }
  return { width: data.readUInt32BE(16), height: data.readUInt32BE(20) };
}
