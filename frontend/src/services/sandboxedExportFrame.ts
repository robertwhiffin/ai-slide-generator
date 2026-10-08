/**
 * Parent controller for opaque (`sandbox="allow-scripts"`) export frames.
 *
 * Slide documents run in a unique origin. Capture work happens inside the
 * frame; this module only creates the frame, authenticates postMessage
 * responses, and tears everything down.
 */
import html2canvasSource from 'html2canvas/dist/html2canvas.min.js?raw';
import {
  EXPORT_FRAME_CHANNEL_PLACEHOLDER,
  HTML2CANVAS_SOURCE_PLACEHOLDER,
  TELLR_EXPORT_FRAME_TYPE,
} from './exportFrameRuntime';

export { EXPORT_FRAME_CHANNEL_PLACEHOLDER, TELLR_EXPORT_FRAME_TYPE };

function escapeEmbeddedScript(source: string): string {
  return source.replace(/<\/script/gi, '<\\/script');
}

function fillExportSrcdoc(srcdoc: string, channelId: string): string {
  return srcdoc
    .split(HTML2CANVAS_SOURCE_PLACEHOLDER)
    .join(escapeEmbeddedScript(html2canvasSource))
    .split(EXPORT_FRAME_CHANNEL_PLACEHOLDER)
    .join(channelId);
}

const SLIDE_WIDTH = 1280;
const SLIDE_HEIGHT = 720;
const DEFAULT_TIMEOUT_MS = 60000;

export type ExportFrameCommand =
  | {
      kind: 'capture-image';
      requestId: string;
      format: 'image/png' | 'image/jpeg';
      quality?: number;
      scale: number;
      width: number;
      height: number;
      rootMode: 'slide-root';
      applyPdfSubtitleFixes: boolean;
      waitForChartsMs?: number;
    }
  | {
      kind: 'capture-canvases';
      requestId: string;
      waitForChartsMs: number;
    }
  | {
      kind: 'extract-records';
      requestId: string;
      fontMode: 'universal' | 'google_slides' | 'preserve';
    };

export type CaptureImageResult = {
  kind: 'capture-image-result';
  requestId: string;
  dataUrl: string;
  width: number;
  height: number;
};

export type CaptureCanvasesResult = {
  kind: 'capture-canvases-result';
  requestId: string;
  canvases: Record<string, string>;
};

export type ExtractRecordsResult = {
  kind: 'extract-records-result';
  requestId: string;
  records: unknown;
};

export type ExportFrameResult =
  | CaptureImageResult
  | CaptureCanvasesResult
  | ExtractRecordsResult;

type ExportFrameError = {
  type: typeof TELLR_EXPORT_FRAME_TYPE;
  channelId: string;
  requestId: string;
  kind: 'error';
  code: 'LOAD_FAILED' | 'CAPTURE_FAILED' | 'INVALID_COMMAND';
  message: string;
};

function expectedResultKind(command: ExportFrameCommand): ExportFrameResult['kind'] {
  switch (command.kind) {
    case 'capture-image':
      return 'capture-image-result';
    case 'capture-canvases':
      return 'capture-canvases-result';
    case 'extract-records':
      return 'extract-records-result';
  }
}

function isObject(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null;
}

function sanitizeResult(
  data: Record<string, unknown>,
  expectedKind: ExportFrameResult['kind'],
): ExportFrameResult | null {
  const requestId = data.requestId;
  if (typeof requestId !== 'string') return null;
  if (expectedKind === 'capture-image-result') {
    if (typeof data.dataUrl !== 'string') return null;
    return {
      kind: 'capture-image-result',
      requestId,
      dataUrl: data.dataUrl,
      width: typeof data.width === 'number' ? data.width : 0,
      height: typeof data.height === 'number' ? data.height : 0,
    };
  }
  if (expectedKind === 'capture-canvases-result') {
    if (!isObject(data.canvases)) return null;
    const canvases: Record<string, string> = {};
    for (const [key, value] of Object.entries(data.canvases)) {
      if (typeof value === 'string') canvases[key] = value;
    }
    return { kind: 'capture-canvases-result', requestId, canvases };
  }
  return { kind: 'extract-records-result', requestId, records: data.records };
}

function errorMessage(value: unknown): string {
  if (!isObject(value)) return 'Export frame failed';
  const message = value.message;
  if (typeof message !== 'string' || message.length === 0) {
    return 'Export frame failed';
  }
  return message.slice(0, 500);
}

export async function runSandboxedExportFrame<T extends ExportFrameResult>(
  srcdoc: string,
  command: ExportFrameCommand,
  options?: { timeoutMs?: number },
): Promise<T> {
  const channelId = crypto.randomUUID();
  const timeoutMs = options?.timeoutMs ?? DEFAULT_TIMEOUT_MS;
  const filledSrcdoc = fillExportSrcdoc(srcdoc, channelId);
  const expectedKind = expectedResultKind(command);

  const container = document.createElement('div');
  container.style.cssText =
    `position:fixed;left:-99999px;top:0;width:${SLIDE_WIDTH}px;height:${SLIDE_HEIGHT}px;` +
    'visibility:hidden;opacity:0;pointer-events:none;z-index:-9999;overflow:hidden;';

  const iframe = document.createElement('iframe');
  iframe.setAttribute('sandbox', 'allow-scripts');
  iframe.style.cssText =
    `width:${SLIDE_WIDTH}px;height:${SLIDE_HEIGHT}px;border:none;display:block;margin:0;padding:0;`;
  container.appendChild(iframe);

  return new Promise<T>((resolve, reject) => {
    let settled = false;
    let commandSent = false;
    let timer = 0;

    const cleanup = () => {
      window.removeEventListener('message', onMessage);
      if (timer) window.clearTimeout(timer);
      try {
        iframe.onload = null;
        iframe.onerror = null;
        if (container.parentNode) {
          container.parentNode.removeChild(container);
        }
      } catch {
        /* Chromium can throw when tearing down an opaque framed window. */
      }
    };

    const settle = (fn: () => void) => {
      if (settled) return;
      settled = true;
      cleanup();
      fn();
    };

    let childSource: MessageEventSource | null = null;

    const isTrustedChildSource = (event: MessageEvent): boolean => {
      try {
        if (childSource) return event.source === childSource;
        return event.source === iframe.contentWindow;
      } catch {
        return false;
      }
    };

    const onMessage = (event: MessageEvent) => {
      if (!isTrustedChildSource(event)) return;
      const data = event.data;
      if (!isObject(data)) return;
      if (data.type !== TELLR_EXPORT_FRAME_TYPE) return;
      if (data.channelId !== channelId) return;

      if (data.kind === 'ready') {
        if (commandSent) return;
        if (!event.source) {
          settle(() => reject(new Error('Export frame window missing')));
          return;
        }
        childSource = event.source;
        commandSent = true;
        (childSource as Window).postMessage(
          {
            type: TELLR_EXPORT_FRAME_TYPE,
            channelId,
            ...command,
          },
          '*',
        );
        return;
      }

      if (!commandSent) return;
      if (data.requestId !== command.requestId) return;

      if (data.kind === 'error') {
        const err = data as ExportFrameError;
        settle(() => reject(new Error(errorMessage(err))));
        return;
      }

      if (data.kind !== expectedKind) return;
      let sanitized: ExportFrameResult | null = null;
      try {
        sanitized = sanitizeResult(data, expectedKind);
      } catch {
        return;
      }
      if (!sanitized) return;
      settle(() => resolve(sanitized as T));
    };

    timer = window.setTimeout(() => {
      settle(() => reject(new Error('Export frame timed out')));
    }, timeoutMs);

    iframe.onerror = () => {
      settle(() => reject(new Error('Export frame failed to load')));
    };

    window.addEventListener('message', onMessage);
    document.body.appendChild(container);
    iframe.srcdoc = filledSrcdoc;
  });
}
