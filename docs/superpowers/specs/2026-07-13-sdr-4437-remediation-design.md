# SDR-4437 Security Remediation — Design

**SDR:** [SDR-4437](https://databricks.atlassian.net/browse/SDR-4437)
**App:** Tellr — AI Slide Generator (FastAPI backend + React 19 SPA)
**Design date:** 2026-07-13
**Status against code:** All findings below re-verified present on `main@61cf231` (review was `2026-07-10`).

## Goal

Clear the BLOCKED status on SDR-4437 by remediating the 3 CRITICAL, 8 HIGH, and 7 MEDIUM
findings. The 4 LOW findings are recorded as advisories, not planned work here. Two findings
are process items (ESI ticket, HIGH-7 proxy confirmation) handled outside the code but drafted
in this plan.

## Distribution context (shapes several fixes)

Tellr is distributed as a **pip package** installed into each customer's Databricks workspace,
not deployed via `deploy_local.sh`. Any remediation that would require each installer to perform
manual setup (e.g. provision a secret scope) is therefore per-install friction and is avoided.
Fixes must work with zero additional operator setup on a fresh pip install.

## Delivery

Six clustered PRs, each closing a coherent theme. Recommended land order: **PR-1a → PR-1b → PR-3 → PR-2 → PR-4 → PR-5**
(PR-1a/1b/PR-3 clear CRITICAL status fastest; PR-2 introduces the shared admin primitive that five
findings depend on; PR-5 is the largest and is independent of the others). PR-1a and PR-1b are
split so the CSP change (the one piece with rendering blast radius) can be reverted independently
of CSRF protection. Commit per logical unit; do not push/merge unless asked.

| PR | Theme | Findings |
|----|-------|----------|
| PR-1a | Security headers / CSP | CRITICAL-1 |
| PR-1b | CSRF / origin validation | CRITICAL-2 |
| PR-2 | Authorization / IDOR + admin role | HIGH-1, HIGH-2, HIGH-3, HIGH-4, HIGH-6, MEDIUM-1, MEDIUM-6 |
| PR-3 | Secrets & runtime hardening | CRITICAL-3, MEDIUM-4, MEDIUM-5, MEDIUM-7 |
| PR-4 | OAuth & error hardening | HIGH-7, MEDIUM-2, MEDIUM-3 |
| PR-5 | Converter sandbox (both export services) | HIGH-5 |

HIGH-6 (`get_user_client` fail-closed) ships in PR-2, not PR-4: PR-2's `uploaded_by == caller`
ownership checks depend on `_get_current_user()` not falling back to `"system"` on OBO-build
failure, so landing HIGH-6 later would leave a window where those checks compare against the
fallback string. Landing them together closes that window.

---

## PR-1a — Security headers / CSP (CRITICAL-1)

**Root cause:** `src/api/main.py` registers only `normalize_mcp_path`, `user_auth_middleware`,
`RequestLoggingMiddleware`, and dev-only CORS. No response carries security headers.
`serve_spa` returns a bare `FileResponse`. The existing `SLIDE_CSP`
(`src/utils/html_safety.py`) governs rendered slide documents and is **not modified** here — but it
*interacts* with the new header via `srcdoc` CSP inheritance (see below).

### CRITICAL-1: App-origin security headers

New middleware `src/api/middleware/security_headers.py`, registered in `main.py`.

**On every response:**

- `X-Frame-Options: DENY`
- `X-Content-Type-Options: nosniff`
- `Referrer-Policy: same-origin`
- `Strict-Transport-Security: max-age=31536000; includeSubDomains`

(`frame-ancestors 'none'`/`X-Frame-Options: DENY` is safe here: all in-app slide iframes use
`srcdoc` — never a backend-served `src` — and the only HTML endpoint, the Google OAuth callback,
opens as a popup, not an iframe.)

**CSP, differentiated by response type.** Two constraints rule out one strict policy everywhere:

1. **`srcdoc` inheritance:** slides render in `srcdoc` iframes, and `srcdoc` documents **inherit
   the embedding document's CSP** in addition to their own `SLIDE_CSP` meta tag (both policies
   enforce; most restrictive wins). A `default-src 'self'` header on the SPA document would
   therefore block every slide's inline `<script>`, Chart.js/Tailwind CDN loads, and Google Fonts
   — breaking slide rendering app-wide.
2. **Inline styles:** the React app uses `style={{...}}` attributes (~22 sites) and Radix UI
   injects inline styles at runtime. Hashed exceptions cannot fix this — CSP hashes apply to
   `<style>`/`<script>` *elements*, not style *attributes* — so `style-src` needs
   `'unsafe-inline'`.

Policies:

- **SPA document responses** (`serve_spa` + index fallback): the union of app needs and
  `SLIDE_CSP` allowances (`src/utils/html_safety.py`):
  `default-src 'self'; script-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net https://cdn.tailwindcss.com; style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; img-src 'self' data:; font-src 'self' data: https://cdn.jsdelivr.net https://fonts.gstatic.com; connect-src 'self'; frame-src 'self'; frame-ancestors 'none'; object-src 'none'; base-uri 'none'`.
  `script-src 'unsafe-inline'` + CDNs here is a **deliberate, documented trade-off** forced by
  `srcdoc` inheritance: slides remain confined by the stricter `SLIDE_CSP` meta policy
  (`connect-src 'none'`, `form-action 'none'`, no eval) plus the `html_safety.py` scanner, and any
  header at all is a strict improvement over today's no-CSP. Keep the directive sets in sync with
  `SLIDE_CSP` (extend `tests/unit/test_export_csp.py`'s sync assertion to cover the header's
  slide-facing allowances).
- **All other responses** (API/JSON, assets): strict
  `default-src 'none'; frame-ancestors 'none'` — nothing executes in a JSON response.

**Validation:** frontend E2E before merge must include rendering a real deck (charts + fonts) under
the new header — this catches both the inheritance interaction and any browser-specific `frame-src`
handling of `about:srcdoc`.

### Tests

- `tests/unit/test_security_headers.py`: assert each header on a representative API response and on
  the SPA response, including the two distinct CSPs. (Fills the gap:
  `frontend/tests/export-csp.spec.ts` covers only slide-document CSP.)

---

## PR-1b — CSRF / origin validation (CRITICAL-2)

**Root cause:** no request is origin-checked.

**Threat model (documented inline in the middleware):** the app sets no cookies of its own — auth
arrives via proxy-attested `x-forwarded-*` headers. The CSRF-relevant ambient credential is the
**platform SSO cookie at the Databricks Apps proxy**: a cross-site browser request to the app URL
rides that cookie, the proxy authenticates it and forwards it with the victim's identity. Origin
validation at the app layer closes this.

New middleware `src/api/middleware/csrf.py`. For `POST/PUT/PATCH/DELETE`:

- If the request carries an `Origin` (falling back to `Referer`), it must match the expected app
  origin; **mismatch → 403**.
- **Neither header present → allow.** Cross-origin browser POSTs always send `Origin`, so the
  realistic attack always presents a mismatch; header-less mutating requests are non-browser
  clients (scripts/curl via the proxy), which rejecting would break for no security gain.
  Documented as a deliberate choice; a strict mode can be revisited if security review requires it.
- **Expected origin:** `DATABRICKS_APP_URL` (platform-injected on Databricks Apps deploys — same
  assumption as `src/api/mcp_server.py:137-147`). If unset in production, fall back to the origin
  reconstructed from `x-forwarded-proto`/`x-forwarded-host` (the proxy always sends these; the
  pattern `google_slides.py:104-105` already uses for redirect URIs), so a missing var degrades to
  a self-referential check instead of blocking all writes.
- **Local dev:** middleware inactive when not production — consistent with the dev-only CORS gate
  in `main.py`.
- Safe methods (`GET/HEAD/OPTIONS`) exempt.
- The `/mcp` mount is exempt — it authenticates with bearer tokens, not cookies, so it is not a
  CSRF target. Documented inline. Note the mounted sub-app **is** wrapped by the parent app's
  middleware (that is how `normalize_mcp_path` works), so the exemption must be an explicit path
  check in the middleware, not an assumption that mounts bypass it — and conversely PR-1a's
  headers cover `/mcp` responses for free.

### Tests

- `tests/unit/test_csrf_middleware.py`: mutating request with mismatched Origin → 403; mismatched
  Referer (no Origin) → 403; matching Origin → passes; **no Origin and no Referer → passes**;
  safe method → passes; `/mcp` → exempt; env-var absent → falls back to `x-forwarded-*`
  comparison; non-production → inactive.

---

## PR-2 — Authorization / IDOR + admin role (HIGH-1, 2, 3, 4, 6, MEDIUM-1, 6)

**Approach A (chosen):** reuse the permission pattern that already passes review, applied explicitly
per handler, plus a route-table coverage test so a future ungated route fails CI.

**Existing helpers to consolidate** into a shared `src/api/routes/_authz.py` (import site for all
routers; keep names/signatures):

- `_check_deck_permission_for_session(session_id, min_permission=CAN_VIEW) -> None` (opens its own
  DB session; ideal where a handler only has a `session_id`).
- `_require_session_access(session_info, db, min_permission=CAN_VIEW) -> PermissionLevel`
- `_require_slide_permission(session_id, db, min_permission=CAN_VIEW) -> PermissionLevel`

### HIGH-1 / HIGH-4: IDOR — add ownership checks to ungated handlers

Currently gated (leave as-is): `sessions.py` CRUD, `slides.py` element CRUD (get/reorder/patch/
duplicate/delete), and `chat.py`'s send/stream/async endpoints (all call `_check_chat_permission`,
CAN_EDIT). `profiles.py` `save-from-session` and both contributors routers are also already gated.

Add a permission check at the top of every ungated session-scoped handler:

- `src/api/routes/export.py` — the session-scoped endpoints (`export_to_pptx` 382, async 641,
  `editable` 957, huashu `from-html` 1169; `from-records` 867 / `from-images` 912 when their
  optional `session_id` is present): `_check_deck_permission_for_session(session_id, CAN_VIEW)`
  before `chat_service.get_slides(...)`. (Not "all 12" — the file's other endpoints are job-scoped,
  capability probes, or diagnostics; each is dispositioned below.)
- **Job-ID IDOR (not in the original review):** `poll_pptx_export` (754) and
  `download_pptx_export` (775) in `export.py`, and `poll_google_slides_export` (334) in
  `google_slides.py`, are gated only by possession of a `job_id` — anyone holding a job id can
  poll or download another user's export. Every job is session-bound: the only two enqueue sites
  (`/pptx/async` at export.py:725, Google Slides export at google_slides.py:320) both require a
  `session_id`, which is persisted on the `ExportJob` row (`from-records`/`from-images` are
  synchronous and never create jobs). Fix: resolve the job's `session_id` and require `CAN_VIEW`.
  No schema change — the row does **not** capture the requesting user, and doesn't need to.
- **Chat-poll IDOR (not in the original review; same class as the job-ID one):**
  `GET /api/chat/poll/{request_id}` (`chat.py:555`) has no permission check — anyone holding a
  `request_id` receives every assistant/tool event and the completed `result_json` (slide-deck
  content included) of another user's chat. Identical fix shape: `ChatRequest` rows are
  session-bound (`session.py:36`; indexed via `__table_args__`, `session.py:52`) and `session_manager.get_session_id_for_request`
  already exists — resolve the request's `session_id` and require `CAN_VIEW`.
- `export.py` `editable/available` (842) returns a capability boolean, no deck data — left ungated
  by design (recorded in the coverage-test allowlist below). The huashu diagnostics
  (1004/1084/1127) are handled under MEDIUM-1.
- `src/api/routes/google_slides.py` — export endpoints (237, 371, 458): `CAN_VIEW` before fetching
  the deck.
- `src/api/routes/verification.py` — the two POSTs write state and must be `CAN_EDIT`, matching
  the treatment of the analogous `slides.py` verification writes below: `verify_slide` (80)
  persists results by content hash (`session_manager.save_verification`) **and** kicks off a
  billable LLM-judge run; `/{slide_index}/feedback` (271) logs feedback to MLflow. Only the
  `genie-link` GET (389) is a true read: `CAN_VIEW`. (Consequence, intended: a read-only viewer
  of a shared deck can no longer trigger verification runs or file feedback.)
- `src/api/routes/tour.py` (not in the original review) — `add_demo_slides`
  (`POST /demo-deck/{session_id}/slides`, 115) writes an assistant reply and pre-built slides into
  an arbitrary `session_id` with no check: `CAN_EDIT`. (The legitimate caller just created the
  session in phase 1, so holds `CAN_MANAGE`; nothing breaks.)
- `src/api/routes/agent_config.py` — get (84) `CAN_VIEW`; put (100) / patch (115) `CAN_MANAGE`
  (writes repoint the victim's tools).
- `src/api/routes/slides.py` version endpoints — `list_versions` (728), `preview_version` (764),
  `get_current_version` (883): `CAN_VIEW`; `restore_version` (812): **`CAN_MANAGE`** (destructive).
  Also ungated (not in the original review): `patch/{index}/verification` (459), `versions/create`
  (575), `versions/{n}/verification` (617), `versions/sync-verification` (669) — all write
  slide/version state: `CAN_EDIT`.
- `src/api/routes/images.py` — images are not session-bound. **Writes** scope by owner:
  `update_image` (204), `delete_image` (241) enforce `uploaded_by == caller` (the field
  `search_images` already filters on — `created_by` is also populated at upload,
  `image_service.py:76`, but never filtered on or exposed); `list_images` (141) filters
  `search_images(...)` by the caller. **Reads stay open to any authenticated user** (`get_image`
  162, `get_image_data` 183): the editor fetches image bytes live
  (`SlidePanel/HTMLEditorModal.tsx` → `api.getImageData`, `api.ts:1026` →
  `GET /api/images/{id}/data`), so owner-filtering reads would break a `CAN_EDIT` collaborator
  opening the HTML editor on a shared deck that references the author's images. Be honest about
  what this leaves open: image IDs are **sequential integers**, not capability URLs
  (`image.py:23` is an autoincrement `Integer` PK and both read handlers take `image_id: int`;
  the UUID lives only in the stored `filename`, `image_service.py:62`, and is never the lookup
  key), so any authenticated workspace user can enumerate IDs and retrieve every user's image
  metadata (`uploaded_by`, tags, description) and raw bytes. Open reads are therefore an
  **explicitly accepted cross-user IDOR risk** — accepted because images are a shared library
  with no per-deck binding to authorize against — record that rationale, verbatim, next to the
  allowlist entry in the coverage test. Revisit if per-deck image binding ever lands; a cheaper
  interim hardening is switching the public identifier to a random UUID column, which restores
  unguessability without touching the collaborator flow. For the same functional reason the
  internal `image_service.get_image_base64` used by the substitution path
  (`substitute_image_placeholders`)
  must **not** be owner-filtered, or shared decks referencing `{{image:ID}}` placeholders break.
  `upload_image` (95) stays open to any authenticated user.

### HIGH-2: Admin role primitive

**Model: App CAN_MANAGE.** Admin = holds `CAN_MANAGE` on the Databricks App itself. Zero
per-install setup (the platform ACL that already controls who manages the deployment doubles as
the app's admin list) — consistent with the pip-distribution constraint.

**Mechanism: OBO self-test.** New `require_admin` FastAPI dependency in `_authz.py`. It calls the
app-permissions API (app name from `DATABRICKS_APP_NAME`) **with the caller's own OBO client** —
the one `user_auth_middleware` already builds per request. Reading an object's ACL in Databricks
requires `CAN_MANAGE` on it, so "can you read the app's ACL with your own token" *is* the admin
test — and group-held / inherited `CAN_MANAGE` resolves server-side for free, with no SCIM
group-expansion and no system-client privileges. Details:

- Caller identity for attribution/caching comes from `get_current_user()` (set by the auth
  middleware from `x-forwarded-access-token` → `me().user_name`). **Not** `x-forwarded-email` —
  that header is only read on the MCP path (verified: sole reader `mcp_auth.py:128`); it does not
  exist for browser/REST traffic.
- Cache the verdict with a short TTL (e.g. 60s) keyed by username. Fail closed (403) on non-admin,
  missing OBO client, or lookup error. In-memory and therefore **per-worker — deliberately fine
  here** (unlike the MEDIUM-3 nonce store): a cache miss on another worker just re-runs the ACL
  lookup; correctness never depends on which worker got the request.
- **Local dev:** bypass when not production (dev auth is `DEV_USER_ID` with no token or ACL behind
  it) — same pattern as the PR-1b CSRF middleware and the dev-only CORS gate.
- **Verification item (live probe before building):** confirm that Databricks Apps follow the
  platform convention that reading the app ACL requires `CAN_MANAGE` (i.e. a `CAN_USE`-only user's
  OBO call gets 403). If they don't, fall back to a system-client ACL read plus SCIM group
  expansion — more moving parts, same model.

Applied as **router-level** `dependencies=[Depends(require_admin)]` on:

- `src/api/routes/admin.py` (Google credential upload/delete, judge-backend).
- `src/api/routes/admin_usage.py` (MEDIUM-6 — workspace-wide usage analytics).
- The `src/api/routes/feedback.py` read endpoints (not in the original review) — `report/stats`
  (78), `list` (91), `report/summary` (118) return **all users'** feedback to any authenticated
  user; same class as MEDIUM-6. Endpoint-level `Depends(require_admin)` here, not router-level:
  the write endpoints (`chat` 23, `submit` 39, `survey` 59) are how regular users submit feedback
  and stay open.
- The huashu diagnostic endpoints in `export.py` (MEDIUM-1) — see below.

**Frontend impact: none (verified).** The only consumers of `admin.py`/`admin_usage.py` GETs and
the `feedback.py` read endpoints are components mounted inside `AdminPage` (`/admin` route —
including `FeedbackDashboard`, `Admin/AdminPage.tsx:116`); the per-user "is my Google account
connected" check regular users need is a separate non-admin endpoint
(`api.checkGoogleSlidesAuth()`). A non-admin manually opening `/admin` sees failed loads —
acceptable; an "am I admin" endpoint for hiding the route is optional polish, not remediation.

### HIGH-3: Global libraries behind admin

Gate the write endpoints behind `require_admin`:

- `src/api/routes/settings/deck_prompts.py`: create (170), update (249), delete (339). (There is
  **no set-default endpoint** in this router — the original plan listed one that doesn't exist.)
- `src/api/routes/settings/slide_styles.py`: create (182), update (264), delete (366),
  set-default (441). Today update/delete only reject `is_system` rows inside the handler (296/394)
  — insufficient — and **set-default has no `is_system` guard at all** (any caller can make any
  style the workspace default).

### MEDIUM-1: Huashu diagnostic endpoints

`export.py` `huashu/available` (1004), `install-chromium` (1084), `probe-launch` (1127): gate behind
`require_admin`, drop env/filesystem/log detail from responses, and stop returning raw subprocess
stdout/stderr.

### HIGH-6: `get_user_client()` fails closed

Authorization-adjacent and lands here rather than PR-4 because HIGH-1's ownership checks depend on
it (see the exception-swallowing callers below).

`src/core/databricks_client.py:492` currently returns the SP system client when the user ContextVar
is empty (logs at 509, returns at 511). Change to **raise** for user-scoped operations when no user
client is bound. The SP fallback is restricted to an explicit local-dev flag. Middleware
(`main.py:365-373`) continues to log build failures, but downstream user-scoped calls now fail closed
instead of silently running as the SP. **Blast radius (verified):** the async export workers never
call `get_user_client()` — they use `get_system_client()`/`get_databricks_client()` directly, and
the job payload carries only `user_identity`; Google creds are loaded and Fernet-decrypted from the
DB at execution time (`GoogleSlidesAuth.from_global`, `export_job_queue.py:427`) — and MCP tools
always have a client bound by `mcp_auth_scope` before they run, so neither breaks. The **largest
consumer** is the chat path: the agent thread and title-gen thread (plus every tool module —
genie/vector/model-endpoint/agent-bricks/mcp — running inside them) call `get_user_client()` off
the request thread and are safe **only because** `send_message_streaming` copies the request
context into both threads (`contextvars.copy_context()`, `chat_service.py:1041/1102`;
`context_utils.py` exists for exactly this). Document that dependency at the raise site and add a
regression test: a thread spawned *without* context propagation must raise, one spawned via
`copy_context` must resolve the user client. **Error surfacing:** when `user_auth_middleware`
fails to build the OBO client (`main.py:365-373`), today the request silently proceeds as SP;
after this change the first user-scoped call raises. Map that exception to a clean **401 with a
"re-authenticate" message** via an exception handler rather than letting it surface as a 500 from
deep inside a tool call.

**Exception-swallowing callers — must be fixed as part of HIGH-6 or the raise never lands:** two
request-path identity helpers wrap `get_user_client()` in a bare `except Exception` and return a
fallback identity string — `_get_user_identity()` (`google_slides.py:37-50`, falls back to
`"local_dev"`) and `_get_current_user()` (`images.py:64-72`, falls back to `"system"`). Left as-is
they silently absorb the new raise, so exactly the condition HIGH-6 fails closed on (missing/failed
OBO client in production) would instead (a) store/read Google OAuth tokens under identity
`"local_dev"` — misattribution in the very token-store path PR-4's MEDIUM-3 protects, since the
callback persists via `_get_auth(db)` → `_get_user_identity()` — and (b) turn HIGH-1's
`uploaded_by == caller` ownership checks on `update_image`/`delete_image` into comparisons against
`"system"`. Fix: keep the dev/test early-returns, delete the production `except Exception` fallback
in both helpers, and let the raise propagate to the 401 mapping above. The same swallow shape sets
`created_by`/`updated_by = "system"` in the settings routers (`deck_prompts.py:205/306/377`,
`slide_styles.py:216/330/422`) — lower stakes because HIGH-3 admin-gates those writes, but sweep
them in the same pass so audit attribution cannot silently degrade. (`/api/user/current`'s fallback
at `main.py:515` is display-only and gates nothing — acceptable as-is. The remaining callers —
`tools.py`, the tool modules, `config_validator.py` — either run inside the context-propagated chat
path covered above or let the exception propagate, which is the desired fail-closed behaviour.)

### Coverage test

`tests/unit/test_route_authz_coverage.py`: walk the FastAPI route table; a route must have either a
permission-helper call in its handler source or `require_admin` in its router dependencies if it
(line refs in this doc are mostly the `@router` decorator lines, but a minority — `agent_config.py`,
`slides.py` `preview_version`/`restore_version`, `slide_styles.py` create/set-default — are the
handler `def` line; treat refs as approximate and anchor the test on the route table, not source
lines):

- lives under `/api/admin`, the settings routers (`deck_prompts`, `slide_styles`), or the
  `feedback.py` read surface (`report/*`, `list`) — otherwise the HIGH-3 and feedback gates
  themselves would sit outside the heuristic — **or**
- takes a `session_id`, `image_id`, `job_id`, **or `request_id`** (the original heuristic missed
  `job_id` and `request_id`, which is exactly how the poll/download and chat-poll IDORs above
  escaped the review's endpoint list; `session_id` is also what catches `tour.py`).

**"Takes" must recurse into Pydantic body models, not just path/query parameters.** On the
primary IDOR surface these identifiers are fields on request-body models, and the handler
signature exposes only `request`: `ExportPPTXRequest.session_id` (`export.py:29`, handlers are
`async def export_to_pptx(request: ExportPPTXRequest)`), `VerifySlideRequest.session_id`
(`verification.py:53`), `ChatRequest.session_id` (`src/api/schemas/requests.py:57`). An
implementation that inspects only route path/query params or the endpoint function's direct
argument names would never flag these routes — a future ungated export/verification endpoint
would silently pass CI, the exact regression this test exists to prevent. So: for each route,
match the trigger names against path params, query params, **and** the fields of any parameter
whose annotation is a Pydantic model.

Deliberately-open routes (capability probes like `editable/available`, the OAuth callback, the
image reads/upload per the explicitly accepted IDOR risk above, the feedback write endpoints) go
on an **explicit allowlist inside the test** — exemptions must be visible in review, not implicit
in the heuristic; the image-read entries must carry the accepted-risk rationale, not a safety
claim. Two more surfaces get allowlisted with a recorded rationale rather than gated:
`tools.py` discovery endpoints (392-442 — enumerate Genie spaces, vector endpoints/indexes/columns,
model endpoints; any user configuring their own agent needs them, and results are already scoped
by the caller's OBO client) and `settings/identities.py` (54/75/116/156 — the `/provider` info
GET plus the workspace user/group lookups feeding the sharing picker). Neither returns deck data; both are authenticated-user
metadata by design. This makes the "forgot the check" class of bug a CI failure going forward.

Extend `tests/unit/test_security_permission_checks.py` with stranger/viewer/owner cases for the
newly-gated export, version-restore, agent-config, tour, and image-write endpoints, plus
job-poll/download and chat-poll cases (stranger with a leaked `job_id`/`request_id` → 403/404)
and non-admin → 403 on the feedback read endpoints.

---

## PR-3 — Secrets & runtime hardening (CRITICAL-3, MEDIUM-4, 5, 7)

### CRITICAL-3: Fernet key out of app.yaml, into a Lakebase table

**Decision:** the Fernet master key stops living in `app.yaml`. It moves to a new table in the
existing Lakebase data schema (e.g. `encryption_keys(id, key_value, created_at)`). Chosen over a
Databricks Secret scope because pip distribution makes per-install scope setup real friction, and over
deriving the key from the app SP secret because SP-secret rotation would permanently break decryption.
Moving the key out of `app.yaml` (readable by CAN_MANAGE-on-app users and deploy logs) into the
ACL-governed database is what closes the finding.

**Design:**

- New table `encryption_keys` in the existing data schema, defined as a model on `Base` so the
  pre-fork `init_db()` `create_all` creates it on fresh installs (the deploy-time migration below
  issues a matching `CREATE TABLE IF NOT EXISTS` for upgrades). No separate schema — with grants
  identical to the data schema (the deliberate choice below), a dedicated schema would add nothing.
- **Grants: the data schema's existing grants** (including the devloop shared-owner role). Deliberate —
  the devloop model uses prod data in dev by design, and keeping the key readable the same way as the
  data lets export changes (which must decrypt tokens to reach Google) be tested in dev against real
  tokens. See "Accepted risk" below.
- `src/core/encryption.py` fetches the key from `encryption_keys` at startup; if absent it generates
  one (`Fernet.generate_key()`) and inserts it — **dynamic, persistent across restarts/restores,
  unique per deployment**, zero operator setup. Local dev follows the same path against the local
  DB, replacing today's `.encryption_key`-file fallback — but seeds the table from an existing
  `.encryption_key` file first (so existing dev ciphertext stays decryptable); generate only when
  neither exists.
- **Race safety — and read-first:** the app runs multiple uvicorn workers (default 4 —
  `packages/databricks-tellr-app/databricks_tellr_app/run.py:66-71`), so generate-if-absent must be
  race-safe: seed the key in the **pre-fork `init_database` step** of the boot command. The seed
  logic is **SELECT-first; only when no row exists** does it `INSERT ... ON CONFLICT DO NOTHING` +
  read-back (concurrent workers/replicas converge on one key). Read-first is load-bearing, not
  style: on upgraded installs the table is created by the *deployer* role, and an unconditional
  `INSERT ... ON CONFLICT` requires INSERT privilege even when the row already exists — with a
  SELECT-only grant that would crash the `set -e` boot command.
- Remove `GOOGLE_OAUTH_ENCRYPTION_KEY` from the app.yaml template
  (`packages/databricks-tellr/databricks_tellr/_templates/app.yaml.template:30-31`) and remove the
  key auto-generation in `deploy.py::_write_app_yaml` (~1303-1307). The production guard in
  `encryption.py` that raised when the env var was unset is replaced by the Lakebase-backed load.
- **Migration (deploy-time, single release):** boot-time seeding from the env var cannot work —
  `_update_databricks` regenerates app.yaml wholesale from the *new* template, so the env var is
  already gone on the new code's first boot. Instead the migration runs in the deploy tool, which
  at update time holds both halves: it already downloads the old deployed app.yaml *before*
  overwriting it (`_read_existing_encryption_key`, 733-759 — retained for this) and already opens
  a Lakebase connection (`_get_lakebase_connection`). New step in `_update_databricks`: read the
  old key from the deployed app.yaml; `CREATE TABLE IF NOT EXISTS encryption_keys` +
  `INSERT ... ON CONFLICT DO NOTHING`; `GRANT SELECT, INSERT ON encryption_keys TO
  "<app client_id>"` (via `_get_app_client_id` — the deployer role creates the table, so the app SP
  needs the explicit grant; INSERT included so the boot seed's insert-when-missing branch can never
  be privilege-blocked). Note the original deployer's `ALTER DEFAULT PRIVILEGES` (deploy.py:1643-1644)
  often makes this grant redundant — but default privileges attach to the *creating role*, so when a
  different identity runs the upgrade the explicit grant is the only one that applies; keep it
  unconditional. Then write the new app.yaml with no key entry. Relocate, not rotate — **no
  re-encryption of existing rows**. Re-running is harmless (read-back finds no key in the new yaml;
  the insert is idempotent).
- **Explicitly rejected (YAGNI):** a boot-time fallback that seeds the table from a still-present
  env var. It would only matter when an *old* deploy tool installs the *new* app wheel; the pip
  distribution path upgrades tool and wheel together, so that skew is unsupported (residual risk:
  that combination would generate a fresh key and orphan existing ciphertext).
- **Migration test:** run the new `_update_databricks` step against a deployed app.yaml containing
  a key — `encryption_keys` ends up seeded with that exact value and the regenerated app.yaml is
  keyless; a second run is a no-op.

**Accepted risk (state explicitly in the SDR response for SE sign-off):** the key carries the same
ACLs as the ciphertext it protects, so encryption provides no cryptographic separation from a
DB-level reader — a common, defensible pattern for app-managed keys. Concretely, because Lakebase
branching is all-or-nothing, a dev fork of a prod branch carries both the key and the encrypted
tokens, so a developer with a fork can decrypt and use prod users' Google credentials (external Drive
impersonation, usable outside Tellr). This is **accepted as a deliberate consequence of the
prod-data-in-dev devloop model** — not mitigated — because it is what makes export changes testable in
dev. (Note: "user-scoped tokens" does not reduce this — a decrypted token is a working per-user Google
credential, and the table holds every connected user's token.)

### MEDIUM-4: SP auth via OAuth M2M, not DATABRICKS_TOKEN

Switch the app.yaml template to rely on the auto-injected `DATABRICKS_CLIENT_ID` /
`DATABRICKS_CLIENT_SECRET` (App SP OAuth M2M) and drop `DATABRICKS_TOKEN`
(`app.yaml.template:42-43`). The app code itself is safe: production builds `WorkspaceClient()`
with default auth, which resolves the injected OAuth creds, and no `src/` code reads
`DATABRICKS_TOKEN` in production paths. **The one dependency to verify: MLflow.** MLflow reads
`DATABRICKS_TOKEN` from the environment, and today the deployed app gets it from app.yaml's
`system.databricks_token` — the real-deploy verification before merge must explicitly confirm
MLflow tracing still works via the OAuth M2M creds after the var is dropped.

### MEDIUM-5: Identifier validation in Lakebase DDL

Validate before interpolating into `CREATE SCHEMA` / `GRANT` DDL; reject otherwise. Separate
patterns per input — `schema`: `^[A-Za-z_][A-Za-z0-9_]*$`; `client_id`: a UUID
(`^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$`). (The review's
single shared regex would have rejected every UUID client_id and broken schema setup outright.)
**Four candidate sites**, all currently unparameterized f-strings — but one, `src/core/lakebase.py::setup_lakebase_schema`
(350-383), turned out to be dead code (zero callers; a near-duplicate of `_grant_schema_permissions`),
so the PR-3 plan **deletes it** rather than hardening an unreachable path (2026-07-15 decision). That
leaves **three live sites**, all in `deploy.py`: `_setup_database_schema` (~1573, `CREATE SCHEMA`), `_reset_schema`
(~1604-1609, `DROP SCHEMA ... CASCADE` + recreate), and `_grant_schema_permissions` (1618, grants
at 1634-1649). Validate via one shared helper, not per-site — and the new DDL this plan itself adds
(PR-3's `CREATE TABLE encryption_keys` / `GRANT ... TO "<client_id>"` migration step) must go
through the same validators.
Both inputs are config/platform-derived today (`schema_name` from deploy config, `client_id` from
the app SP), so this is hardening against future user-derived values, not a live injection.

### MEDIUM-7: Dependency pinning

**Where production resolution actually happens:** the deployed app boot-installs a *generated*
`requirements.txt` containing only `databricks-tellr-app==<version>` (`deploy.py::_write_requirements`,
~1222-1264); the dependency closure comes from the **wheel's metadata** —
`packages/databricks-tellr-app/pyproject.toml`. This is the established "pins live in the wheel"
model from the 0.3.11 resolver-backtracking fix. The repo-root `requirements.txt` governs local/dev
installs only.

**Fix:**

- Pin the 7 remaining `>=` ranges in `packages/databricks-tellr-app/pyproject.toml` to exact
  known-good versions: `databricks-sql-connector`, `Pillow`, `google-api-python-client`,
  `google-auth-oauthlib`, `google-auth-httplib2`, `cryptography`, `sse-starlette`. Same refresh
  discipline as the resolver-speedup pins already in that file (verify on a devloop deploy).
- Mirror the pins in the repo-root `requirements.txt` for dev/prod parity (its `>=` list differs:
  `databricks-mcp`/`svgpathtools` exist only in the root file; `mcp` is pinned in the wheel and
  absent from the root file).

**Explicitly not doing hash-pinned installs:** full-closure locking (`uv.lock` /
`pip freeze` / `--generate-hashes`) was tried during the resolver work and fails against the
Databricks Apps BUILD phase — hard-pinning the whole closure fights the Apps base image, and the
build proxy mirror does not carry every locked version (documented in the pyproject comment block).
Leaf transitives stay ranged by design; direct deps get exact pins. Record this constraint in the
SDR response as the reason hash-verification is not part of the remediation.

---

## PR-4 — OAuth & error hardening (HIGH-7, MEDIUM-2, 3)

### HIGH-7: MCP priority-3 forwarded-identity does not run data-plane as SP

`src/api/mcp_auth.py` (~167): when `identity.token is None` (priority-3 header-only path, gated on
`TELLR_TRUST_FORWARDED_IDENTITY=true`), do **not** bind `get_system_client()` for resource-execution
MCP tools. Require the user OBO token for Genie/UC/model tool execution; header-only identity may be
used for attribution/non-resource operations only. Keep the trust-model docstring. This closes the
finding by defense-in-depth regardless of whether the proxy strips caller-supplied headers.

### MEDIUM-2: Generic error responses

Replace `detail=str(e)` / `detail=f"...{e}"` (**85** exception-interpolating sites across
`src/api/routes/` — the review's ~53 undercounts; `slides.py` 33, `sessions.py` 16,
`google_slides.py` 9, `export.py` 7, remainder spread across ten routers — plus the OAuth callback
HTML `{exc}` reflection at `google_slides.py:197`) with generic client messages; log the detail
server-side only. Start with the OAuth callback and the highest-count routers. Note the concrete
form varies — `sessions.py` wraps as `detail=f"...: {str(e)}"` — so the implementation sweep must
match the whole family (`str(e)`, `{e}`, `{exc}`, `{str(e)}`), not one literal pattern.

### MEDIUM-3: OAuth state nonce + explicit postMessage origin

`src/api/routes/google_slides.py` OAuth flow (auth_url 131, callback 160).

**The actual finding is OAuth login-CSRF.** There is no nonce binding the callback to a consent
flow this user initiated, and `/auth/callback` is a `GET` (so PR-1b's CSRF check, which exempts safe
methods, does not cover it). An attacker can complete their *own* Google consent, capture the
`code`, and cause a victim's browser to load `/auth/callback?code=<attacker code>&state=...`; the
callback exchanges it and stores the **attacker's** Google tokens under the **victim's** Tellr
identity — the victim then exports into the attacker's Drive. The state nonce is what closes this.

**Note (correction to the review):** the callback does *not* trust the `user` field in `state` to
choose whose token to persist — it checks the field exists (179-181) but persists via `_get_auth(db)`
→ `_get_user_identity()`, i.e. the **authenticated callback request's** identity (183, 189). So there
is no misattribution-via-state bug; the `user` field is dead weight and should be dropped.

Fix:

- **State nonce, server-bound — and the store MUST be cross-worker:** the app runs multiple uvicorn
  workers (default 4), and `/auth/url` and `/auth/callback` routinely land on different workers — an
  in-memory nonce dict fails most callbacks. This exact failure mode has bitten before (in-memory
  job state missing on the worker receiving the update), which is why `ExportJob` lives in the DB;
  the nonce follows the same pattern. New Lakebase table `oauth_states` in the data schema
  (`nonce` PK — 256-bit random, `user_identity`, `code_verifier`, `created_at`), model on `Base` so
  `create_all` creates it. On `/auth/url`: insert a row for the authenticated user, put only the
  nonce in `state`. On callback: consume atomically (`DELETE ... WHERE nonce = :n RETURNING *` —
  single-use even under concurrent callbacks), require the row to exist, belong to the request's
  authenticated user, and be younger than a short TTL (~10 min); expired rows are swept
  opportunistically on insert. Drop the `user` field from `state` — identity already comes from the
  authenticated request and must stay that way.
- **PKCE — the verifier currently travels in client-visible state (correction: the read is LIVE, not
  dead):** `GoogleSlidesAuth.get_auth_url` (`google_slides_auth.py:244-254`) injects the
  `code_verifier` into the `state` payload and sends the `code_challenge` to Google; the callback's
  `state_data.get("code_verifier")` read (185) is therefore live — removing it breaks token exchange,
  since Google enforces the challenge. (An earlier draft called this read dead after checking the
  `/auth/url` route handler instead of the service method that builds the state.) Exposing the
  verifier in client-visible state defeats PKCE's purpose, so the fix is PKCE proper: keep generating
  the verifier on `/auth/url`, stash it in the `oauth_states` row (add a `code_verifier` column —
  already in the table sketch above), make `state` a bare nonce, and have the callback fetch the
  verifier from the consumed row.
- **postMessage origin (both ends):** replace `window.opener.postMessage({...}, '*')` (callback HTML
  200, 216) with the app origin (reconstructed from `x-forwarded-*`, the `_build_redirect_uri`
  pattern at 104-116). In `frontend/src/hooks/useGoogleOAuthPopup.ts` (19-24), add an `event.origin`
  check before trusting the message. (Lower severity than the nonce — spoofs a fake "connected"
  state, not token theft — but closes the wildcard security review will flag.)
- The raw `{exc}` reflected into the failure HTML (197) is the MEDIUM-2 error-leak item; fix it in
  the same edit.

### Tests

- `tests/unit/test_google_oauth_state.py`: valid nonce → tokens stored for the request user; second
  consume of the same nonce → rejected (single-use); nonce belonging to a different user → rejected;
  expired nonce → rejected; callback with no/unknown nonce → rejected; two concurrent consumes of
  one nonce → exactly one winner (atomic `DELETE ... RETURNING`).

---

## PR-5 — Converter sandbox (HIGH-5)

> **Reachability note (2026-07-16, verified on deployed `sdr4437-pr5`):** the current frontend does
> NOT route PPTX export through the LLM converter — "Download PPTX" calls the deterministic huashu
> sidecar (`/api/export/pptx/editable/huashu/from-html`) with the `/from-records` DOM-walker as
> fallback. The jailed path (`api.exportToPPTX` → `/api/export/pptx/async`, `HtmlToPptxConverterV3`)
> is fully wired but has zero frontend callers today. **Decision (Robert, 2026-07-16): keep the jail
> anyway — do NOT delete the LLM converter.** The LLM PPTX path may become the live export route
> again in future, and the sandbox is the correct posture for it whenever it is re-wired. So HIGH-5
> is "sandbox the converter" (done), not "delete dead code" — deliberately unlike PR-3's dead
> `setup_lakebase_schema`, which had no such future use. Deploy validation confirmed real
> download/export works end-to-end on the instance; the jail's Linux-only netns/RLIMIT_AS
> enforcement remains covered by the unit suite (netns recorded as best-effort defense-in-depth,
> per the design) rather than exercised through the UI, since no client reaches the jailed path.

**Constraint (hard):** the LLM-generated Python converter is a required feature and stays. Today it
is written to a temp `.py` and run **in-process** via `spec.loader.exec_module`, inheriting
`DATABRICKS_TOKEN`, the Fernet key, and Lakebase credentials. This affects **both** export services
— three exec sites with different contracts:

- `src/services/html_to_pptx.py:1066-1071` — host calls the generated
  `convert_to_pptx(html_str, output_path, assets_dir)`. Already data-in/file-out, no network — but
  its only caller (`convert_html_to_pptx`) has **no production caller**; not a contract to build on.
- `src/services/html_to_pptx.py:1123-1124` — the production PPTX exec site, driven by **two
  distinct loops**: the sync route via `convert_slide_deck` (`export.py:552`) and the async worker
  via `convert_slides_with_progress` (`export_job_queue.py:251/290` — **not** `convert_slide_deck`;
  `export_job_queue.py:443` is the *Google Slides* converter), which additionally writes per-slide
  progress into the `ExportJob` row as it goes. Both loops: a **separate generated converter per
  slide**, each called as `add_slide_to_presentation(prs, html_str, assets_dir)` against one shared
  **live python-pptx `Presentation`**, with a deterministic per-slide fallback slide when a
  converter throws. Not subprocess-movable without a contract change — and the change must preserve
  the per-slide fault isolation **and** the async loop's per-slide progress reporting.
- `src/services/html_to_google_slides.py:1220-1228` — host calls the generated
  `add_slide_to_presentation(wrapped_service, drive_service, pres_id, page_id, html_str, assets_dir)`;
  the **generated code itself makes authenticated `batchUpdate().execute()` network calls** to
  Google. A scrubbed-env/no-network jail applied naively here would break Google Slides export.

### Step 1 — contract change: generated code becomes pure data-in/data-out

The LLM's creative work is deciding *what* to build from the HTML; the API/file I/O is mechanical.
Move all I/O to the trusted host:

- **Google Slides:** the generated converter takes HTML + assets and **emits a JSON list of
  `batchUpdate` requests** to an output file, referencing images by placeholder
  (`"url": "tellr-asset://<filename>"`, naming files in its assets dir) — batchUpdate alone cannot
  carry image bytes, and today the generated code itself uploads assets to Drive
  (`files().create` + `permissions().create`, html_to_google_slides.py:867-885). That upload moves
  to the host: schema-validate the JSON (well-defined Google API shapes plus the placeholder
  scheme), upload each referenced asset to Drive, substitute the real URLs, and execute the
  requests with the user's OAuth service — the same execution model the deterministic
  `from-records` path already uses. **The host executor must run through
  `_ChunkedSlidesService`** (html_to_google_slides.py:392) or equivalent — today's generated code
  gets 4-request chunking plus exponential 429 backoff with per-request retry from that wrapper,
  and a naive replay of the emitted JSON would lose it and rate-limit-fail large decks. (Bonus:
  today's Drive uploads bypass the wrapper entirely, so host-side upload *adds* retry there.)
  Host-side upload also allows cleaning up the Drive asset files afterwards and later tightening
  today's `anyone`-reader grant, neither of which generated code ever did. Generated code never
  touches the network or credentials; the feature is preserved intact.
- **PPTX:** keep per-slide codegen exactly as today, and move the **execution loop** into the
  subprocess: the host passes N HTML files plus the N generated converter snippets; a trusted,
  host-written runner script inside the jail builds the `Presentation`, runs each slide's converter
  in the same try/except-with-fallback loop, and writes the complete `.pptx` out. The live `prs`
  never crosses the process boundary (the whole loop lives inside the jail), per-slide fault
  isolation is preserved, and it stays one subprocess per deck. **Both production loops adopt the
  runner** — the sync route (`convert_slide_deck`) and the async worker
  (`convert_slides_with_progress`) — and the async loop's per-slide progress must cross the
  process boundary: the runner emits one machine-readable progress line per slide on stdout (a
  host-written trusted channel), which the host relays to `update_export_progress`; otherwise the
  async export UX degrades to a silent multi-minute wait. (An earlier draft proposed a single
  whole-deck generated converter reusing the `convert_to_pptx` contract — rejected: that contract
  has no production caller, and one bad slide's generated code would fail the entire deck.)

### Step 2 — subprocess jail (the security boundary)

- Run the generated converter in a `python -I` **subprocess**, one per deck (single interpreter
  spawn, ~200–400ms), not in-process.
- **Scrubbed environment:** whitelist only `PATH`, `LANG`, `HOME` (→ a temp dir). Strip all
  `DATABRICKS_*`, the Fernet key, and Lakebase credentials. After this the process holds nothing
  worth exfiltrating.
- **Resource limits** via `resource.setrlimit` in `preexec_fn` (CPU seconds, address space, file
  size, process count) plus a wall-clock timeout on the parent.
- **Filesystem:** temp-dir-only working directory; HTML/assets in, PPTX or batchUpdate-JSON out,
  as files.
- **Network:** with the Step-1 contract change the subprocess needs no network at all.
  Feature-detect `unshare`/network-namespace at startup and run with no network when the container
  permits; when netns is unavailable, egress is possible but the scrubbed env means there are no
  credentials to exfiltrate — recorded as documented residual risk in the SDR response.

### Defense-in-depth (explicitly not the boundary)

- **AST import allowlist** (`pptx`, `PIL`, `lxml`, stdlib basics) checked before launch.
- **Optional judge-LLM pass** over the generated code before execution (model access already exists
  in this code path). Adds one model call of latency per export and a false-reject failure mode.

Both are best-effort filters — bypassable by construction — and are framed in the SDR response as
hardening layers on top of the jail, never as the control that closes the finding.

Deterministic converters (`from-records`, `from-images`, huashu `from-html`) remain available as-is.

### Tests

- Jail unit tests: subprocess env contains only the whitelist; rlimits and wall-clock timeout
  enforced; converter output read back from files only.
- Google Slides contract tests: generated-converter output parses and schema-validates as a
  `batchUpdate` request list (including `tellr-asset://` placeholders); host-side executor uploads
  assets, substitutes URLs, and applies the requests (mock service).
- Regression: existing PPTX and Google Slides export E2E paths still produce correct artifacts; a
  deliberately-failing per-slide converter degrades only that slide to the fallback, not the deck.
- Async-path regression: the jailed runner's per-slide progress lines reach
  `update_export_progress` (job row advances during conversion); host executor chunks batchUpdate
  and retries a mocked 429.

---

## Process items (owner: engineer; content drafted here)

### HIGH-8: ESI ticket for Google Slides/Drive

File an ESI ticket registering the third-party Google integration. Must state: **Google Slides &
Drive API; outbound read + write; per-user delegated OAuth; token store is per-user, Fernet-encrypted
in Lakebase.** (Robert files; this plan records the required content.)

### HIGH-7 SDR response

Alongside the code fix, provide the engineer confirmation for the SDR that the Databricks Apps proxy
sets and strips `x-forwarded-*` headers (the load-bearing assumption). The code fix means the finding
is closed by defense-in-depth, not by the proxy assertion alone.

---

## LOW findings (advisories, not planned)

- **LOW-1** Fernet key auto-generation/rotation — partly addressed by the PR-3 Lakebase-backed key
  (auto-generate on boot); key rotation + re-encryption remains unimplemented.
- **LOW-2** OBO token prefix logged (computed `main.py:340`, emitted at 342 — DEBUG level only) —
  recommend removing entirely.
- **LOW-3** Session `/export` writes full session to `logs/sessions/*.json` at CAN_VIEW — ephemeral
  container storage; low priority.
- **LOW-4** Standing advisories (Lakebase policy, critical-app pen-test, MCP OBO re-verification).

---

## Testing summary

- Backend: pytest under `tests/unit`, `tests/integration`. New: `test_security_headers.py`,
  `test_csrf_middleware.py`, `test_route_authz_coverage.py`; extended
  `test_security_permission_checks.py`, `test_mcp_auth.py`. Remove `mlruns/` artifact after runs.
- Frontend E2E: Playwright from `frontend/`. Verify the SPA loads under the new app-origin CSP
  (extend beyond the slide-document coverage in `export-csp.spec.ts`).

## Out of scope

- Fernet key rotation + re-encryption tooling.
- Tightening `encryption_keys` grants below the data-schema level (accepted risk — see CRITICAL-3).
- Broader refactors not required by a finding.
