/**
 * F-CR-25 — opaque sandbox for browser-side export frames.
 *
 * Protocol tests drive a fake in-frame bootstrap that speaks the same
 * postMessage contract as the production runtime. Exploit and structural
 * tests pin the four export consumers to that controller.
 */
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { test, expect } from '@playwright/test';
import { SLIDE_CSP } from '../src/services/slideDocument';
import { buildSlideHTML as buildPdfSlideHTML } from '../src/services/pdf_client';
import { buildSlideHTML as buildPptxSlideHTML } from '../src/services/pptx_client';
import { buildSlideHtml } from '../src/services/screenshotCapture';
import { buildCompositeHtml } from '../src/services/domWalker';
import { EXPORT_FRAME_CHANNEL_PLACEHOLDER } from '../src/services/exportFrameRuntime';

const AFFECTED_FILES = [
  'pdf_client.ts',
  'screenshotCapture.ts',
  'pptx_client.ts',
  'domWalker.ts',
] as const;

function readService(name: string): string {
  return readFileSync(
    fileURLToPath(new URL(`../src/services/${name}`, import.meta.url)),
    'utf8',
  );
}

function protocolSrcdoc(bodyScript: string): string {
  return `<!DOCTYPE html>
<html>
<head>
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; script-src 'unsafe-inline'">
</head>
<body>
<script>
var CHANNEL_ID = "${EXPORT_FRAME_CHANNEL_PLACEHOLDER}";
${bodyScript}
</script>
</body>
</html>`;
}

const READY_AND_ECHO_IMAGE = `
window.addEventListener('message', function (e) {
  if (e.source !== window.parent) return;
  if (!e.data || e.data.type !== 'tellr-export-frame' || e.data.channelId !== CHANNEL_ID) return;
  if (e.data.kind === 'capture-image') {
    parent.postMessage({
      type: 'tellr-export-frame',
      channelId: CHANNEL_ID,
      requestId: e.data.requestId,
      kind: 'capture-image-result',
      dataUrl: 'data:image/png;base64,REAL',
      width: 1280,
      height: 720
    }, '*');
  }
});
parent.postMessage({ type: 'tellr-export-frame', channelId: CHANNEL_ID, kind: 'ready' }, '*');
`;

test.describe('export frame message protocol', () => {
  test('creates a frame with exactly sandbox="allow-scripts"', async ({ page }) => {
    await page.goto('/');
    const sandboxes = await page.evaluate(async (srcdoc) => {
      const m = await import('/src/services/sandboxedExportFrame.ts');
      const seen: string[] = [];
      const obs = new MutationObserver(() => {
        document.querySelectorAll('iframe').forEach((frame) => {
          seen.push(frame.getAttribute('sandbox') ?? '');
        });
      });
      obs.observe(document.body, { childList: true, subtree: true, attributes: true });
      await m.runSandboxedExportFrame(srcdoc, {
        kind: 'capture-image',
        requestId: crypto.randomUUID(),
        format: 'image/png',
        scale: 1,
        width: 1280,
        height: 720,
        rootMode: 'slide-root',
        applyPdfSubtitleFixes: false,
      });
      obs.disconnect();
      return seen;
    }, protocolSrcdoc(READY_AND_ECHO_IMAGE));

    expect(sandboxes.length).toBeGreaterThan(0);
    for (const sandbox of sandboxes) {
      expect(sandbox).toBe('allow-scripts');
    }
  });

  test('ignores a result from another window', async ({ page }) => {
    await page.goto('/');
    const dataUrl = await page.evaluate(async (srcdoc) => {
      const m = await import('/src/services/sandboxedExportFrame.ts');
      const attacker = document.createElement('iframe');
      attacker.srcdoc = `<script>
        setInterval(function () {
          parent.postMessage({
            type: 'tellr-export-frame',
            channelId: 'guess',
            requestId: 'guess',
            kind: 'capture-image-result',
            dataUrl: 'data:image/png;base64,SPOOF',
            width: 1,
            height: 1
          }, '*');
        }, 10);
      </script>`;
      document.body.appendChild(attacker);
      const result = await m.runSandboxedExportFrame(srcdoc, {
        kind: 'capture-image',
        requestId: crypto.randomUUID(),
        format: 'image/png',
        scale: 1,
        width: 1280,
        height: 720,
        rootMode: 'slide-root',
        applyPdfSubtitleFixes: false,
      });
      attacker.remove();
      return result.dataUrl;
    }, protocolSrcdoc(READY_AND_ECHO_IMAGE));

    expect(dataUrl).toBe('data:image/png;base64,REAL');
  });

  test('ignores a stale request ID and a wrong result kind', async ({ page }) => {
    await page.goto('/');
    const srcdoc = protocolSrcdoc(`
window.addEventListener('message', function (e) {
  if (e.source !== window.parent) return;
  if (!e.data || e.data.channelId !== CHANNEL_ID) return;
  if (e.data.kind === 'capture-image') {
    parent.postMessage({
      type: 'tellr-export-frame',
      channelId: CHANNEL_ID,
      requestId: 'stale-id',
      kind: 'capture-image-result',
      dataUrl: 'data:image/png;base64,STALE',
      width: 1,
      height: 1
    }, '*');
    parent.postMessage({
      type: 'tellr-export-frame',
      channelId: CHANNEL_ID,
      requestId: e.data.requestId,
      kind: 'capture-canvases-result',
      canvases: { wrong: 'kind' }
    }, '*');
    parent.postMessage({
      type: 'tellr-export-frame',
      channelId: CHANNEL_ID,
      requestId: e.data.requestId,
      kind: 'capture-image-result',
      dataUrl: 'data:image/png;base64,REAL',
      width: 1280,
      height: 720
    }, '*');
  }
});
parent.postMessage({ type: 'tellr-export-frame', channelId: CHANNEL_ID, kind: 'ready' }, '*');
`);
    const dataUrl = await page.evaluate(async (doc) => {
      const m = await import('/src/services/sandboxedExportFrame.ts');
      const result = await m.runSandboxedExportFrame(doc, {
        kind: 'capture-image',
        requestId: crypto.randomUUID(),
        format: 'image/png',
        scale: 1,
        width: 1280,
        height: 720,
        rootMode: 'slide-root',
        applyPdfSubtitleFixes: false,
      });
      return result.dataUrl;
    }, srcdoc);

    expect(dataUrl).toBe('data:image/png;base64,REAL');
  });

  test('timeout rejects and removes the frame', async ({ page }) => {
    await page.goto('/');
    const leftover = await page.evaluate(async (srcdoc) => {
      const m = await import('/src/services/sandboxedExportFrame.ts');
      let failed = false;
      try {
        await m.runSandboxedExportFrame(
          srcdoc,
          {
            kind: 'capture-image',
            requestId: crypto.randomUUID(),
            format: 'image/png',
            scale: 1,
            width: 1280,
            height: 720,
            rootMode: 'slide-root',
            applyPdfSubtitleFixes: false,
          },
          { timeoutMs: 200 },
        );
      } catch {
        failed = true;
      }
      return {
        failed,
        frames: document.querySelectorAll('iframe').length,
      };
    }, protocolSrcdoc('/* never ready */'));

    expect(leftover.failed).toBe(true);
    expect(leftover.frames).toBe(0);
  });

  test('child error rejects and cleans up', async ({ page }) => {
    await page.goto('/');
    const srcdoc = protocolSrcdoc(`
window.addEventListener('message', function (e) {
  if (e.source !== window.parent) return;
  if (!e.data || e.data.channelId !== CHANNEL_ID) return;
  parent.postMessage({
    type: 'tellr-export-frame',
    channelId: CHANNEL_ID,
    requestId: e.data.requestId,
    kind: 'error',
    code: 'CAPTURE_FAILED',
    message: 'boom'
  }, '*');
});
parent.postMessage({ type: 'tellr-export-frame', channelId: CHANNEL_ID, kind: 'ready' }, '*');
`);
    const outcome = await page.evaluate(async (doc) => {
      const m = await import('/src/services/sandboxedExportFrame.ts');
      let message = '';
      try {
        await m.runSandboxedExportFrame(doc, {
          kind: 'capture-image',
          requestId: crypto.randomUUID(),
          format: 'image/png',
          scale: 1,
          width: 1280,
          height: 720,
          rootMode: 'slide-root',
          applyPdfSubtitleFixes: false,
        });
      } catch (err) {
        message = err instanceof Error ? err.message : String(err);
      }
      return { message, frames: document.querySelectorAll('iframe').length };
    }, srcdoc);

    expect(outcome.message).toContain('boom');
    expect(outcome.frames).toBe(0);
  });

  test('parent does not fetch, navigate, or write storage for child messages', async ({ page }) => {
    await page.goto('/');
    const srcdoc = protocolSrcdoc(`
window.addEventListener('message', function (e) {
  if (e.source !== window.parent) return;
  if (!e.data || e.data.channelId !== CHANNEL_ID) return;
  parent.postMessage({ type: 'tellr-export-frame', channelId: CHANNEL_ID, kind: 'fetch', url: '/api/sessions' }, '*');
  parent.postMessage({ type: 'tellr-export-frame', channelId: CHANNEL_ID, kind: 'navigate', href: '/' }, '*');
  parent.postMessage({ type: 'tellr-export-frame', channelId: CHANNEL_ID, kind: 'storage', key: 'x', value: 'y' }, '*');
  if (e.data.kind === 'capture-image') {
    parent.postMessage({
      type: 'tellr-export-frame',
      channelId: CHANNEL_ID,
      requestId: e.data.requestId,
      kind: 'capture-image-result',
      dataUrl: 'data:image/png;base64,REAL',
      width: 1,
      height: 1
    }, '*');
  }
});
parent.postMessage({ type: 'tellr-export-frame', channelId: CHANNEL_ID, kind: 'ready' }, '*');
`);
    const outcome = await page.evaluate(async (doc) => {
      const fetches: string[] = [];
      const origFetch = window.fetch.bind(window);
      window.fetch = ((input: RequestInfo | URL, init?: RequestInit) => {
        fetches.push(String(input));
        return origFetch(input, init);
      }) as typeof fetch;
      const hrefBefore = location.href;
      const storeBefore = sessionStorage.getItem('x');
      const m = await import('/src/services/sandboxedExportFrame.ts');
      await m.runSandboxedExportFrame(doc, {
        kind: 'capture-image',
        requestId: crypto.randomUUID(),
        format: 'image/png',
        scale: 1,
        width: 1280,
        height: 720,
        rootMode: 'slide-root',
        applyPdfSubtitleFixes: false,
      });
      return {
        fetches,
        hrefUnchanged: location.href === hrefBefore,
        storageUnchanged: sessionStorage.getItem('x') === storeBefore,
      };
    }, srcdoc);

    expect(outcome.fetches.filter((u) => u.includes('/api/sessions'))).toEqual([]);
    expect(outcome.hrefUnchanged).toBe(true);
    expect(outcome.storageUnchanged).toBe(true);

    const controllerSrc = readService('sandboxedExportFrame.ts');
    const code = controllerSrc.replace(/\/\/.*$/gm, '');
    expect(code).not.toMatch(/\bfetch\s*\(/);
    expect(code).not.toMatch(/location\.(href|assign|replace)/);
    expect(code).not.toMatch(/localStorage|sessionStorage/);
  });
});

test.describe('structural regression', () => {
  for (const name of AFFECTED_FILES) {
    test(`${name} does not read iframe documents or mint unsandboxed frames`, async () => {
      const src = readService(name).replace(/\/\/.*$/gm, '');
      expect(src).not.toMatch(/iframe\.contentDocument/);
      expect(src).not.toMatch(/iframe\.contentWindow\?\.document/);
      expect(src).not.toMatch(/iframe\.contentWindow\.document/);
      expect(src).toMatch(/runSandboxedExportFrame/);
      expect(src).not.toMatch(/createElement\(\s*['"]iframe['"]\s*\)/);
    });
  }

  test('export documents keep SLIDE_CSP first and embed the trusted runtime', async () => {
    const deck = {
      title: 'T',
      css: '',
      scripts: '',
      external_scripts: [],
      slides: [{ html: '<div class="slide">x</div>', scripts: '' }],
    } as never;
    const docs = [
      buildPdfSlideHTML(deck, 0),
      buildPptxSlideHTML(deck, 0),
      buildSlideHtml(deck, 0),
      buildCompositeHtml(deck),
    ];
    for (const doc of docs) {
      const cspAt = doc.indexOf(SLIDE_CSP);
      const runtimeAt = doc.indexOf(EXPORT_FRAME_CHANNEL_PLACEHOLDER);
      expect(cspAt).toBeGreaterThan(0);
      expect(runtimeAt).toBeGreaterThan(cspAt);
      expect(doc).not.toContain('unsafe-eval');
      expect(doc).toContain("connect-src 'none'");
    }
  });
});

test.describe('malicious slide exploit regression', () => {
  const maliciousHtml = `
<div class="slide" style="width:1280px;height:720px;background:#f8f7f3;">
  <h1>Safe</h1>
  <canvas id="chart" width="200" height="100"></canvas>
</div>
<script>
  try {
    parent.document.body.dataset.exportCompromised = 'true';
  } catch (e) {}
  try {
    parent.fetch('/api/sessions');
  } catch (e) {}
  try {
    var ctx = document.getElementById('chart').getContext('2d');
    ctx.fillStyle = '#1B3139';
    ctx.fillRect(0, 0, 200, 100);
    document.body.dataset.harmlessRan = 'true';
  } catch (e) {}
</script>
`;

  const deck = {
    title: 'Exploit',
    css: '.slide { width:1280px; height:720px; }',
    scripts: '',
    external_scripts: [],
    slides: [{ html: maliciousHtml, scripts: '' }],
  };

  test('image capture isolates the parent and still completes', async ({ page }) => {
    test.setTimeout(120000);
    await page.goto('/');

    const result = await page.evaluate(async (d) => {
      document.body.dataset.exportCompromised = '';
      const sessionFetches: string[] = [];
      const origFetch = window.fetch.bind(window);
      window.fetch = ((input: RequestInfo | URL, init?: RequestInit) => {
        try {
          const parsed = new URL(String(input), location.href);
          if (parsed.pathname === '/api/sessions' && parsed.search === '') {
            sessionFetches.push(parsed.href);
          }
        } catch {
          /* ignore */
        }
        return origFetch(input, init);
      }) as typeof fetch;
      const m = await import('/src/services/screenshotCapture.ts');
      const urls = await m.captureDeckAsPngDataUrls(d);
      window.fetch = origFetch;
      return {
        compromised: document.body.dataset.exportCompromised || '',
        dataUrl: urls[0] || '',
        frames: document.querySelectorAll('iframe').length,
        sessionFetches,
      };
    }, deck);

    expect(result.compromised).not.toBe('true');
    expect(result.sessionFetches).toEqual([]);
    expect(result.dataUrl.startsWith('data:image/png')).toBe(true);
    expect(result.dataUrl.length).toBeGreaterThan(1000);
    expect(result.frames).toBe(0);
  });

  test('DOM-record extraction isolates the parent and still completes', async ({ page }) => {
    test.setTimeout(120000);
    await page.goto('/');

    const result = await page.evaluate(async (d) => {
      document.body.dataset.exportCompromised = '';
      const sessionFetches: string[] = [];
      const origFetch = window.fetch.bind(window);
      window.fetch = ((input: RequestInfo | URL, init?: RequestInit) => {
        try {
          const parsed = new URL(String(input), location.href);
          if (parsed.pathname === '/api/sessions' && parsed.search === '') {
            sessionFetches.push(parsed.href);
          }
        } catch {
          /* ignore */
        }
        return origFetch(input, init);
      }) as typeof fetch;
      const m = await import('/src/services/domWalker.ts');
      const records = await m.extractSlideRecordsForExport(d, 'preserve');
      window.fetch = origFetch;
      return {
        compromised: document.body.dataset.exportCompromised || '',
        slideCount: records.length,
        recordCount: records[0]?.records.length ?? 0,
        sessionFetches,
      };
    }, deck);

    expect(result.compromised).not.toBe('true');
    expect(result.sessionFetches).toEqual([]);
    expect(result.slideCount).toBe(1);
    expect(result.recordCount).toBeGreaterThan(0);
  });
});

test.describe('export fidelity contracts', () => {
  test('DOM walker font modes return records in slide order', async ({ page }) => {
    test.setTimeout(120000);
    await page.goto('/');
    const deck = {
      title: 'Fonts',
      css: '.slide { font-family: Inter, sans-serif; }',
      scripts: '',
      external_scripts: [],
      slides: [
        { html: '<div class="slide"><p>One</p></div>', scripts: '', speaker_notes: 'n1' },
        { html: '<div class="slide"><p>Two</p></div>', scripts: '', speaker_notes: 'n2' },
      ],
    };
    const result = await page.evaluate(async (d) => {
      const m = await import('/src/services/domWalker.ts');
      const modes = ['universal', 'google_slides', 'custom'] as const;
      const out: Record<string, { count: number; notes: string[] }> = {};
      for (const mode of modes) {
        const records = await m.extractSlideRecordsForExport(d, mode);
        out[mode] = {
          count: records.length,
          notes: records.map((r) => r.notes),
        };
      }
      return out;
    }, deck);

    for (const mode of ['universal', 'google_slides', 'custom']) {
      expect(result[mode].count, mode).toBe(2);
      expect(result[mode].notes, mode).toEqual(['n1', 'n2']);
    }
  });

  test('editable PPTX canvas capture returns a PNG map', async ({ page }) => {
    test.setTimeout(120000);
    await page.goto('/');
    const deck = {
      title: 'Charts',
      css: '',
      scripts: '',
      external_scripts: [],
      slides: [
        {
          html: `<div class="slide"><canvas id="chart" width="640" height="360"></canvas></div>
<script>
  window.Chart = window.Chart || function ChartStub() {};
  var c = document.getElementById('chart');
  var ctx = c.getContext('2d');
  for (var i = 0; i < 640; i++) {
    ctx.fillStyle = 'rgb(' + (i % 255) + ',' + ((i * 3) % 255) + ',40)';
    ctx.fillRect(i, 0, 1, 360);
  }
</script>`,
          scripts: '',
        },
      ],
    };
    const canvases = await page.evaluate(async (d) => {
      const m = await import('/src/services/pptx_client.ts');
      const all = await m.captureSlideDeckCharts(d);
      return all[0];
    }, deck);

    expect(Object.keys(canvases).length).toBeGreaterThan(0);
    const first = Object.values(canvases)[0];
    expect(first.startsWith('data:image/png')).toBe(true);
    expect(first.length).toBeGreaterThan(2000);
  });
});
