# Browser Export Frame Isolation — Design Spec

**Date:** 2026-10-08  
**Status:** Proposed  
**Security finding:** F-CR-25  
**Scope:** Browser-side PDF, screenshot-PPTX, chart capture, and DOM-record export

## Goal

Execute persisted slide HTML and JavaScript in an opaque sandbox during every
browser-side export while preserving current PDF, PPTX, Google Slides, and
visual-fidelity behavior.

After this change, slide code may render and modify its own export document, but
it must not:

- read or modify the Tellr SPA DOM;
- call Tellr APIs with the exporter's authenticated browser session;
- read parent storage or browser state;
- navigate or submit forms in the parent document.

## Why

Tellr slides contain executable JavaScript for charts. Normal preview and
presentation frames already use:

```html
<iframe sandbox="allow-scripts">
```

Omitting `allow-same-origin` gives the slide an opaque origin and prevents access
to the Tellr parent page.

The browser export paths currently create unsandboxed `srcdoc` frames because
the parent reaches into `iframe.contentDocument` to run html2canvas, copy chart
canvases, or walk the DOM. An unsandboxed `srcdoc` frame is same-origin with the
Tellr SPA. Persisted slide JavaScript can therefore reach `window.parent`, invoke
same-origin `/api` routes as the exporter, and act with the exporter's Tellr
permissions. The raw Databricks token is not exposed; the risk is misuse of the
exporter's authenticated session.

The child slide CSP remains useful but is not sufficient. It restricts requests
originating in the child document; same-origin slide code can move execution
into the parent document, where the parent CSP permits same-origin API calls.

## Affected Paths

The implementation must isolate all four browser capture paths:

| Path | Current parent-side operation | Required sandbox result |
| --- | --- | --- |
| `frontend/src/services/pdf_client.ts` | Mutates iframe DOM and calls html2canvas | Child returns rendered JPEG/PNG |
| `frontend/src/services/screenshotCapture.ts` | Mutates iframe DOM and calls html2canvas | Child returns PNG |
| `frontend/src/services/pptx_client.ts` | Reads Chart.js state and canvas pixels | Child returns chart canvas images |
| `frontend/src/services/domWalker.ts` | Injects walker scripts and reads extracted records | Child returns structured records |

Server-side Huashu/Playwright rendering is out of scope. It loads a generated
file in an isolated converter process and does not run in the user's Tellr
browser origin.

## Security Model

### Trusted

- Parent orchestration code shipped in the Tellr frontend.
- The export-frame bootstrap authored by Tellr.
- html2canvas 1.4.1 bundled from the existing npm dependency.
- The existing DOM walker authored by Tellr.

### Untrusted

- Slide HTML.
- Slide scripts and deck scripts.
- External slide libraries, including Chart.js and Tailwind CDN scripts.
- Messages emitted by the sandboxed frame.

### Boundary

Every export frame must have exactly:

```html
sandbox="allow-scripts"
```

It must never include `allow-same-origin`, `allow-top-navigation`,
`allow-forms`, `allow-popups`, or a sandbox escape fallback.

Because sandboxed `srcdoc` messages have an opaque (`"null"`) origin, the parent
must authenticate responses by checking:

```ts
event.source === iframe.contentWindow
```

The parent must also match a per-frame random channel ID and a per-request ID.
These IDs prevent unrelated frames and stale responses from being accepted.
They are correlation controls, not secrets: malicious code in the same frame
may inspect or spoof them. Spoofing can corrupt that deck's exported artifact,
which is already within the deck author's control; it must not grant parent
capabilities.

The message protocol is response-only from the parent's perspective. A child
message must never ask the parent to fetch a URL, call an API, navigate, write
storage, or perform any other privileged action.

Both directions use `postMessage(..., '*')` because an opaque sandbox has no
targetable origin. The parent relies on `event.source` plus correlation IDs.
The child must accept commands only when `event.source === window.parent` and
the message carries its embedded channel ID.

## Architecture

### 1. Shared parent controller

Create:

`frontend/src/services/sandboxedExportFrame.ts`

It owns frame creation, protocol validation, timeouts, and cleanup.

Required interface:

```ts
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

export type ExportFrameResult =
  | {
      kind: 'capture-image-result';
      requestId: string;
      dataUrl: string;
      width: number;
      height: number;
    }
  | {
      kind: 'capture-canvases-result';
      requestId: string;
      canvases: Record<string, string>;
    }
  | {
      kind: 'extract-records-result';
      requestId: string;
      records: unknown;
    };

export async function runSandboxedExportFrame<T extends ExportFrameResult>(
  srcdoc: string,
  command: ExportFrameCommand,
  options?: { timeoutMs?: number },
): Promise<T>;
```

`runSandboxedExportFrame` must:

1. Generate a cryptographically random channel ID with `crypto.randomUUID()`.
2. Add `sandbox="allow-scripts"` before assigning `srcdoc`.
3. Register the parent `message` listener before appending the frame.
4. Require matching `event.source`, channel ID, request ID, and expected result
   kind.
5. Send the command only after the bootstrap emits `ready`.
6. Reject on timeout, frame load failure, bootstrap error, or malformed result.
7. Remove the listener, timer, frame, and hidden container on every exit path.
8. Return no reference to the iframe, child window, or child document.

There must be no fallback that recreates an unsandboxed frame.

### 2. In-frame runtime

Create:

`frontend/src/services/exportFrameRuntime.ts`

This module builds the trusted bootstrap inserted into each export document.
The bootstrap runs inside the sandbox and performs all DOM access.

Bundle html2canvas into the `srcdoc`; do not fetch it from a new CDN. Use Vite's
raw import support against the installed 1.4.1 distribution:

```ts
import html2canvasSource from 'html2canvas/dist/html2canvas.min.js?raw';
```

Escape any literal `</script` sequence before embedding the source in a script
element. The slide CSP already permits trusted inline scripts, so no new
`script-src`, `connect-src`, image, or form destination is required.

The bootstrap must be placed after the CSP meta element but before all untrusted
slide/deck markup and scripts. It must capture the browser intrinsics it relies
on before untrusted code runs (message registration, timers, DOM query methods,
canvas serialization, and `postMessage`) so prototype replacement by slide code
does not turn a frame response into a parent capability.

The runtime listens for one matching command from the parent and posts one
serializable result or one structured error:

```ts
type ExportFrameError = {
  type: 'tellr-export-frame';
  channelId: string;
  requestId: string;
  kind: 'error';
  code: 'LOAD_FAILED' | 'CAPTURE_FAILED' | 'INVALID_COMMAND';
  message: string;
};
```

Error messages must not include page HTML, credentials, storage, or arbitrary
object serialization.

### 3. Capture operations

#### Full-slide image

Move the existing operations from `pdf_client.ts` and
`screenshotCapture.ts` into the child:

- wait for document load, fonts, external scripts, and Chart.js canvases;
- locate the root using the current `findSlideRoot` behavior;
- force width, height, margin, and `box-sizing` exactly as today;
- optionally apply the PDF subtitle margin normalization;
- run html2canvas with the existing dimensions, scale, background, and taint
  settings;
- return a data URL in the requested image format and quality.

Do not consolidate away differences that currently affect PDF/screenshot
pixels. Express those differences through command options.

#### Chart canvases

Move Chart.js readiness checks and all canvas reads from `pptx_client.ts` into
the child. Return the existing ID/index-to-PNG map. The parent continues to send
that map to the editable-PPTX backend exactly as before.

#### DOM records

Move `WALKER_SOURCE`, font rewriting, fonts-ready waits, and
`__extractSlide` invocation into the child runtime. Return only the structured
records currently consumed by the Google Slides / editable-PPTX code.

The parent must not inject scripts into or read the sandboxed document.

## Source Integration

Modify the four affected consumers as follows:

### `pdf_client.ts`

- Keep `buildSlideHTML` and PDF page assembly.
- Have the builder include the trusted runtime.
- Replace all `contentDocument`, `contentWindow.document`, root mutation,
  subtitle mutation, chart polling, and parent-side html2canvas calls with
  `runSandboxedExportFrame(..., { kind: 'capture-image', ... })`.
- Preserve current JPEG quality, PDF sizing, progress, and filename behavior.

### `screenshotCapture.ts`

- Keep `buildSlideHtml` and its public return type.
- Replace frame DOM access and parent-side html2canvas with the shared
  controller.
- Preserve PNG output and existing backend contract.

### `pptx_client.ts`

- Preserve editable-PPTX request construction.
- Replace `captureSlideCharts` DOM access with the
  `capture-canvases` command.

### `domWalker.ts`

- Preserve composite document construction and record schemas.
- Replace script injection and document reads with `extract-records`.
- Preserve all font modes and output ordering.

## CSP and Document Construction

`SLIDE_CSP` remains the frame policy:

- `connect-src 'none'`;
- `img-src data:`;
- `form-action 'none'`;
- `base-uri 'none'`;
- no `unsafe-eval`.

The CSP meta element must remain the first security-relevant element in
`<head>`. The trusted export runtime follows it. Untrusted external scripts,
CSS, slide HTML, slide scripts, and deck scripts follow the runtime.

Do not add `blob:`, a new CDN host, `allow-same-origin`, `allow-forms`, or
`allow-top-navigation`.

## Tests

### Protocol tests

Create:

`frontend/tests/export-frame-isolation.spec.ts`

Cover:

1. The helper creates a frame with exactly `sandbox="allow-scripts"`.
2. A result from another window/frame is ignored.
3. A stale request ID or wrong result kind is ignored.
4. Timeout and child error reject and clean up frame/listener state.
5. No parent callback exists for fetch, navigation, storage, or arbitrary
   method invocation.

### Exploit regression

Use a malicious slide containing script that attempts:

```js
parent.document.body.dataset.exportCompromised = 'true';
parent.fetch('/api/sessions');
```

Run a real browser capture. Assert:

- the parent marker is absent;
- no `/api/sessions` request was observed;
- the capture still completes;
- harmless slide JavaScript and Chart.js still execute inside the frame.

Exercise at least full-slide image capture and DOM-record extraction. All four
consumers must use the same controller, so static assertions should pin the
other integrations.

### Structural regression

Add a source-level test that fails if any affected export file contains:

- `iframe.contentDocument`;
- `iframe.contentWindow?.document`;
- `iframe.contentWindow.document`;
- a dynamically created export iframe without `sandbox="allow-scripts"`.

The test must cover `pdf_client.ts`, `screenshotCapture.ts`,
`pptx_client.ts`, and `domWalker.ts`.

### Fidelity and feature regression

The existing tests remain mandatory:

```bash
cd frontend
npm run typecheck
npm run lint
npx playwright test tests/export-csp.spec.ts
npx playwright test tests/e2e/slide-surface-fidelity.spec.ts
npx playwright test tests/e2e/export-ui.spec.ts
```

Add or update cases to prove:

- wrapped and unwrapped slide backgrounds remain unchanged;
- padded roots retain the current border-box behavior;
- PDF subtitle spacing remains unchanged;
- Chart.js canvases appear in editable PPTX capture;
- all DOM walker font modes return the same records and ordering;
- multi-slide exports process sequentially and clean up each frame;
- a failed slide produces the existing user-visible export failure rather than
  silently falling back to an unsafe renderer.

Run the backend tests covering CSP parity because the frontend and backend
policies are mirrored:

```bash
uv run pytest tests/unit/test_export_csp.py tests/unit/test_html_safety.py -q
```

## Acceptance Criteria

The work is complete only when all of the following are true:

1. Every browser-side export iframe has `sandbox="allow-scripts"` and no other
   sandbox token.
2. No parent export module reads or mutates a slide iframe document.
3. Malicious slide code cannot access `parent.document` or issue a parent
   same-origin API request during export.
4. PDF, screenshot-PPTX, editable-PPTX chart capture, and DOM-record export all
   still work.
5. Existing pixel-fidelity and CSP tests pass without weakened assertions.
6. The frame CSP is not relaxed.
7. There is no unsafe fallback.
8. The implementation adds no network dependency and keeps the current pinned
   html2canvas version.
9. `docs/technical/export-features.md` and the relevant frontend/security
   overview document the opaque export frame and message protocol.

## Non-Goals

- Removing JavaScript support from slides.
- Sanitizing away Chart.js or deck scripts.
- Preventing a deck author from corrupting their own exported artifact.
- Changing server-side Huashu/Playwright isolation.
- Changing Tellr API authorization or Databricks OBO behavior.
- Exposing or moving Databricks tokens into the browser.
- Refactoring unrelated slide-document builders or visual styling.

## Implementation Sequence

1. Build and test the shared message protocol/controller.
2. Build the in-frame runtime with full-image capture.
3. Migrate screenshot capture and PDF capture; prove pixel parity.
4. Add canvas capture and migrate editable PPTX chart extraction.
5. Add record extraction and migrate the DOM walker.
6. Add the malicious-slide browser regression and structural guard.
7. Run the complete frontend and backend export suites.
8. Update technical documentation.

Each migration must remove the old parent-side DOM access in the same change.
Do not leave an unsafe compatibility branch behind.
