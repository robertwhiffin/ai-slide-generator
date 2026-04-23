# Tellr MCP Test Client Design Spec

**Date:** 2026-04-23
**Branch:** `ty/feat/tellr-mcp-server` (for the spec + plan; test-app code itself lives only in the Databricks workspace, see decision #9)
**Status:** Draft

## Overview

A minimal Databricks App whose sole purpose is to verify that tellr's MCP server, introduced on `ty/feat/tellr-mcp-server`, correctly accepts proxy-injected `x-forwarded-access-token` on app-to-app calls within a Databricks workspace — the one verification item in the tellr MCP design spec that no existing test surface can exercise.

The app is a single Streamlit page: a user pastes a tellr app URL, types a prompt, clicks Generate, and the app forwards the inbound OBO token to tellr's `/mcp/` endpoint, polls `get_deck_status`, and renders the returned `html_document` in an iframe. The resulting deck shows up in the tellr UI attributed to the end user (not the test app's service principal), which is the definitive proof that OBO forwarding works end-to-end.

This is a **throwaway verification harness** with the option to promote to a permanent reference example (`examples/mcp-test-client/` in the tellr repo) if other teams show demand. It is explicitly not productised: no tests, no CI, no long-term API stability, no permission model of its own.

## Goals

- Verify that the Databricks Apps proxy injects `x-forwarded-access-token` on app-to-app calls (open verification item #2 in `2026-04-22-tellr-mcp-server-design.md`).
- Verify that tellr accepts that token, resolves it via `current_user.me()`, and attributes the resulting deck to the end user — not the test app's service principal.
- Exercise the `html_document` standalone-HTML rendering recipe (section 8.1 of `docs/technical/mcp-server.md`) in a real iframe.
- Provide a minimal, readable implementation a Databricks SA can deploy in under an hour. Becoming the basis for other MCP integrations is a nice-to-have; a productised reference example is explicitly a non-goal (see below and the v1.1 roadmap).

## Non-Goals

- **Productised reference example.** If promoted to `examples/` this spec will be superseded; v1 targets verification only.
- **Edit flow.** `edit_deck` is out of scope — it reuses the same OBO forwarding and polling plumbing as `create_deck`, so verifying one verifies the other.
- **Multi-user support.** Single-user, single-session, blocking polling loop. No `st.session_state` isolation beyond the current browser session.
- **Local development path.** No Bearer fallback when the OBO header is missing. Running the app outside Databricks Apps is expected to fail loudly — this is by design, because only the proxy-injected path is worth verifying.
- **Authentication error UX.** A red banner is sufficient; no refresh, no retry, no reauth flow.
- **Structured deck rendering.** Only `html_document` iframe rendering. Rendering `deck.slides` in a custom grid is section 8.2 of the tellr MCP doc and adds no new verification value.
- **Persistence.** The test app has no database. State is per-browser-session only.
- **Observability.** Streamlit's default `print`/logging is sufficient. No MLflow, no structured logs.
- **Tests.** No unit or integration tests. The manual verification checklist is the test.
- **Production deployment.** v1 deploys to the same dev workspace tellr is deployed to; no prod path.

## Design Decisions

| # | Decision | Choice | Rationale |
|---|---|---|---|
| 1 | Framework | Streamlit | Canonical "textbox + button" Databricks App pattern; single file; `st.components.v1.html` for iframe rendering; `st.context.headers` for OBO extraction. |
| 2 | Tellr URL config | User input box, persisted in `st.session_state` | Avoids a redeploy when pointing at a different tellr deployment; trivially simpler than env-var plumbing for a throwaway. |
| 3 | Auth path | OBO only — `x-forwarded-access-token` → forwarded as `Authorization: Bearer` on outbound | Verifying the OBO path *is* the goal; any Bearer fallback dilutes the signal ("was the OBO header actually used?"). |
| 4 | Workspace client | None | Test app never calls Databricks APIs directly. It is a pure HTTP forwarder. Drops the `databricks-sdk` dependency. |
| 5 | Polling model | Synchronous blocking loop inside the button handler, with `st.empty()` updates between iterations | Simple; Streamlit's single-user, single-session assumption holds for a test harness. No `st.rerun()`. |
| 6 | Poll cadence | 2-second sleep, 10-minute total deadline | Matches the guidance and timeout window in `docs/technical/mcp-server.md` section 9. |
| 7 | Result rendering | `st.components.v1.html(html_document, height=600, scrolling=True)` | Matches the iframe recipe in tellr MCP doc section 8.1. |
| 8 | Correlation IDs | Each `create_deck` call generates a fresh `mcp-test-client-<uuid8>` and displays it in the status panel | Enables grepping tellr's server logs if generation fails. |
| 9 | Code location | Authored in the Databricks workspace IDE, not committed to this repo | Matches the throwaway-now-promote-later decision. Promotion to `examples/mcp-test-client/` is a follow-on task if demand materialises. |
| 10 | Dependencies | `streamlit`, `httpx` only | `databricks-sdk` explicitly excluded; no workspace client is built. |

## Architecture

### Runtime topology

```
Browser (end user, logged into Databricks workspace)
   │
   │  HTTPS (browser cookie / Databricks SSO)
   ▼
Databricks Apps proxy
   │  adds x-forwarded-access-token: <user's OBO>
   │
   ▼
mcp-test-client (Streamlit, this design)
   │  reads x-forwarded-access-token from st.context.headers
   │  re-sends as Authorization: Bearer on outbound
   ▼
tellr /mcp/ (Streamable HTTP MCP server)
   │  current_user.me() resolves the Bearer token to the end user
   │  deck is created under end user's identity
   ▼
tellr worker → deck saved → response returned
```

### File layout

Authored in the Databricks workspace IDE. Exact paths depend on workspace convention; the canonical minimal layout is:

```
mcp-test-client/
├── app.py             # Streamlit page (~90 lines)
├── app.yaml           # Databricks App config (no env vars required)
└── requirements.txt   # streamlit, httpx
```

No other files. No tests. No README.

### Registration order

`app.yaml` declares a `command` that launches Streamlit on the port Databricks Apps expects. This is standard Streamlit-on-Databricks-Apps boilerplate and is not design-bearing; the plan document will pin exact contents.

---

## Page Layout

Top to bottom, single column:

1. **Title.** `st.title("Tellr MCP test client")`.
2. **Tellr URL.** `st.text_input("Tellr app URL", value=st.session_state.get("tellr_url", ""), placeholder="https://tellr-....databricksapps.com")`. Stored back into `st.session_state["tellr_url"]` on change.
3. **Identity panel.** A single caption:
   - If `x-forwarded-access-token` is present in `st.context.headers`: `st.caption("x-forwarded-access-token: ✓ present")`.
   - If absent: `st.error("Not behind the Databricks Apps proxy. Deploy this app to validate the OBO path. Local runs cannot test OBO.")` and early-return before rendering any further inputs.
4. **Prompt.** `st.text_area("Prompt", height=120, placeholder="e.g., a three-slide briefing on Q3 renewals")`.
5. **Generate button.** Disabled when prompt is empty or Tellr URL is empty.
6. **Status panel.** Empty until Generate is clicked. Then a single `st.empty()` slot updated with the current poll state (`pending`, `running`, `ready`, `failed`) plus the correlation ID and the elapsed time.
7. **Result panel.** Empty until `status == "ready"`. Then:
   - `st.link_button("Open in tellr", deck_url)` — bounces to tellr's UI.
   - `st.components.v1.html(html_document, height=600, scrolling=True)` — renders the standalone HTML in-app.

No side navigation, no tabs, no multipage. One surface.

---

## Data Flow

### `create_deck → poll → render`

1. Read `token = st.context.headers.get("x-forwarded-access-token")`. Absent → error banner per above.
2. Build a `httpx.Client` with timeout 60s and default headers:
   - `Authorization: Bearer {token}`
   - `Content-Type: application/json`
   - `Accept: application/json, text/event-stream`
3. **Initialize.** POST `{tellr_url}/mcp/` with body `{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-03-26","capabilities":{},"clientInfo":{"name":"tellr-mcp-test-client","version":"0.1.0"}}}`. Capture `mcp-session-id` from response headers.
4. **Handshake.** POST `{"jsonrpc":"2.0","method":"notifications/initialized"}` with `mcp-session-id` header.
5. **Submit.** POST `{"jsonrpc":"2.0","id":2,"method":"tools/call","params":{"name":"create_deck","arguments":{"prompt":"<user text>","correlation_id":"mcp-test-client-<uuid8>"}}}`. Parse returned `session_id` and `request_id`.
6. **Poll loop.** Deadline = `time.time() + 600`. Every iteration:
   - Sleep 2s.
   - POST `tools/call get_deck_status` with `{session_id, request_id}`.
   - Decode (handling SSE `data:` frames).
   - If `status in ("pending","running")`: update status panel, continue.
   - If `status == "ready"`: break and render.
   - If `status == "failed"`: break and show error.
7. **Render.** On ready, set result panel content; on failed or timeout, red error box. Do not clear status panel — leave correlation ID visible for log grepping.

### SSE decoding

Same `decode(resp)` helper as `scripts/mcp_smoke/mcp_smoke_httpx.py`: if `content-type` includes `event-stream`, scan the body for the first `data:` line and JSON-parse the remainder. Otherwise `resp.json()` directly.

---

## Error Handling

Failure modes and UI treatments:

| Trigger | UI |
|---|---|
| `x-forwarded-access-token` absent | Red banner: *"Not behind the Databricks Apps proxy — deploy this app to validate the OBO path. Local runs cannot test OBO."* Inputs hidden. |
| Tellr URL empty | Caption: *"Enter your tellr app URL to begin."* Generate button disabled. |
| HTTP 4xx / 5xx on any call | Red box: `HTTP {status_code}: {response.text}`. No retry. |
| JSON-RPC error envelope (`result.isError == true`) | Red box with the text from `result.content[0].text`. |
| Polling deadline exceeded | Red box: *"Generation did not complete within 10 minutes (matches tellr's `JOB_HARD_TIMEOUT_SECONDS`). Check tellr server logs for correlation_id `<id>`."* |
| `status == "failed"` | Red box with `payload["error"]`. |

All error states leave the correlation ID visible so the user can cross-reference with tellr's logs.

---

## Verification Plan

This harness exists to execute a checklist against a running tellr deployment. v1 is considered shipped when every item on the checklist passes.

1. [ ] Deploy `mcp-test-client` to a Databricks workspace that also has tellr deployed (same workspace).
2. [ ] Open the test app in a browser. Identity panel shows `x-forwarded-access-token: ✓ present`.
3. [ ] Paste the tellr URL. Enter a prompt (*"a three-slide briefing on Q3 renewals"*). Click Generate.
4. [ ] Status panel transitions `pending → running → ready` within a few minutes.
5. [ ] Result panel iframe renders the deck. `deck_url` link is clickable.
6. [ ] Open `deck_url` in a new tab — deck opens in tellr's UI, attributed to the signed-in user (**not** the test app's service principal).
7. [ ] Grep tellr's server logs for the correlation ID. Confirm the MCP tool log line shows `token_source: x-forwarded-access-token` (not `authorization-bearer`).

Steps 6 and 7 together resolve open verification items #1 and #2 in `2026-04-22-tellr-mcp-server-design.md`. Steps 2 and 7 together confirm Databricks Apps injects OBO on app-to-app calls and that tellr's auth helper reads the correct header in priority order.

---

## Rollout

### Deployment order

1. Deploy `mcp-test-client` to the same workspace as tellr. Since the code lives in the Databricks workspace IDE (decision #9), deploy via the workspace UI's "Deploy app" action on that folder, or via `databricks apps deploy` pointing at the workspace path.
2. Run the verification checklist above.
3. If any step fails: diagnose via tellr's logs + `st.write` tracing in the test app; update `docs/superpowers/specs/2026-04-22-tellr-mcp-server-design.md` with findings; adjust tellr's `mcp_auth.py` if the proxy behavior differs from spec assumptions.
4. Record completion of the OBO verification in tellr's `docs/technical/mcp-server.md` changelog entry (currently marked as an open verification item).

### Promote-later path

If, after verification, other teams show demand for a reference example:

1. Create `examples/mcp-test-client/` in the tellr repo.
2. Port `app.py`, `app.yaml`, `requirements.txt`.
3. Add a `README.md` explaining deployment, expected behavior, and known limitations.
4. Add a link to the README from `docs/technical/mcp-server.md` section 7.
5. Do **not** add tests or CI — the example is illustrative, not a tested product.

If no demand materialises, the Databricks workspace copy is the only artifact and no promotion happens.

---

## Open Items

None at spec time. All design decisions above are final pending user review.

---

## v1.1 Roadmap

Explicitly out of v1 but captured in case the harness is promoted:

1. **Edit flow.** Second text area + Refine button that calls `edit_deck` against the current `session_id`.
2. **Bearer fallback for local iteration.** Environment-variable Bearer token when OBO is absent, so `streamlit run app.py` works locally.
3. **Structured deck rendering.** Render the `deck.slides` array in a custom grid (iframe-free), exercising section 8.2 of the tellr MCP doc.
4. **Streaming status.** Bridge MCP `notifications/progress` into the status panel once the tellr server emits them (v1.1 of the tellr MCP spec).
5. **Reference example promotion.** Full README, air-gapped CDN guidance, a simple Dockerfile for non-Databricks-Apps hosting.

---

## References

- [Tellr MCP Server Design Spec](./2026-04-22-tellr-mcp-server-design.md) — the server this client verifies.
- [Tellr MCP caller-facing reference](../../technical/mcp-server.md) — rendering recipes and auth recipes this app exercises.
- [`scripts/mcp_smoke/mcp_smoke_httpx.py`](../../../scripts/mcp_smoke/mcp_smoke_httpx.py) — the laptop-side smoke script this app mirrors for the in-workspace path.
