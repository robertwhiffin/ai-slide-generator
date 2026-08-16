# Google Slides Integration

**One-Line Summary:** Global, user-scoped Google OAuth2 flow with encrypted credential storage; export renders the deck HTML to a PPTX and uploads it to Drive, which auto-converts it to native editable Google Slides.

---

## 1. Overview

The Google Slides integration allows users to export their AI-generated slide decks directly to Google Slides presentations. It shares the deck's rendered HTML with the PPTX export path and produces editable Google Slides via a Drive round-trip.

Key design decisions:
- **Global credentials** — A single `credentials.json` is stored app-wide in the `google_global_credentials` table, encrypted at rest. Admins upload via the `/admin` page.
- **Per-user tokens** — OAuth tokens are scoped to `user_identity` only. Each user authorizes once; tokens are stored in `google_oauth_tokens`.
- **DB-backed storage** — No files on disk; all secrets live in PostgreSQL/Lakebase, encrypted with Fernet symmetric encryption.
- **HTML → PPTX → Drive auto-convert** — The export does **not** call the Google Slides API to build slides object-by-object. It renders the deck's HTML to a `.pptx` and uploads that file to Drive with `mimeType=application/vnd.google-apps.presentation`, so Google converts it to a native Slides presentation. This gives coordinate-faithful layout (positions come straight from the rendered DOM) for free.

> **Historical note.** An earlier design used an LLM to generate Python that
> called `slides.batchUpdate()` object-by-object (`src/services/html_to_google_slides.py`,
> `google_slides_prompts_defaults.py`, and the `POST /api/export/google-slides`
> + `/poll/{job_id}` async-job routes). That path is **superseded** by the
> HTML→PPTX→Drive pipeline below and is no longer the route the UI calls. The
> code still exists but should be treated as legacy.

---

## 2. Architecture

```
Frontend (Admin page → GoogleSlidesAuthForm)   ← one-time setup
  │
  ├─ Upload credentials.json ──► POST /api/admin/google-credentials
  │                                 └─ validates → encrypts → stores in google_global_credentials
  │
  ├─ Authorize (popup) ────────► GET /api/export/google-slides/auth/url
  │                                 └─ builds Flow from decrypted creds → returns consent URL
  │   Google consent ──────────► GET /api/export/google-slides/auth/callback
  │                                 └─ exchanges code → encrypts token → stores in google_oauth_tokens

Frontend (SlidePanel → "Export to Google Slides")   ← the export
  │
  ├─ POST /api/export/google-slides/from-huashu     (primary path)
  │      └─ backend fetches deck HTML from session storage
  │      └─ build_pptx_huashu() → spawns Node sidecar (emit_deck.mjs)
  │            └─ per slide: Playwright renders HTML in Chromium (1280×720)
  │                          → preprocess.mjs mutates DOM → html2pptx.js walks
  │                            the rendered DOM → pptxgenjs assembles one .pptx
  │      └─ upload_pptx_as_slides()  → Drive upload, mimeType=…google-apps.presentation
  │                          → Google auto-converts PPTX → native Slides
  │      └─ returns { presentation_id, presentation_url }   (synchronous, no polling)
  │
  └─ POST /api/export/google-slides/from-records    (fallback, only on 503)
         └─ client-side DOM walker (domWalker.ts) → records → pptxgenjs → same Drive upload
```

### Data Flow

1. **Admin** uploads `credentials.json` via the Google Slides tab on the `/admin` page.
2. **Each user** clicks "Authorize" to complete the OAuth consent flow in a popup. The resulting token is encrypted and stored per-user (by `user_identity`).
3. **Export** (`exportToGoogleSlides` in `frontend/src/services/api.ts`) POSTs to `/from-huashu`. The backend builds the PPTX server-side and uploads it to Drive in a single synchronous round-trip — there is **no** job/poll cycle on this path.
4. If the huashu pipeline is unavailable on the deployment (HTTP 503 — e.g. Chromium not bootstrapped), the frontend transparently falls back to `/from-records`, walking the deck DOM client-side and POSTing the extracted records.

---

## 3. Database Schema

### Table: `google_global_credentials`

```sql
CREATE TABLE google_global_credentials (
    id                   SERIAL PRIMARY KEY,
    credentials_encrypted TEXT NOT NULL,
    uploaded_by          VARCHAR(255),
    created_at           TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at           TIMESTAMP NOT NULL DEFAULT NOW()
);
```

Stores the Fernet-encrypted contents of `credentials.json` app-wide. Single-row table; upsert on upload.

### Table: `google_oauth_tokens`

```sql
CREATE TABLE google_oauth_tokens (
    id              SERIAL PRIMARY KEY,
    user_identity   VARCHAR(255) NOT NULL,
    token_encrypted TEXT NOT NULL,
    created_at      TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMP NOT NULL DEFAULT NOW(),
    UNIQUE (user_identity)
);
```

| Column | Description |
|--------|-------------|
| `user_identity` | Databricks username (email) or `"local_dev"` |
| `token_encrypted` | Fernet-encrypted JSON token (access, refresh, expiry) |

Unique on `user_identity` only — one token per user across the app.

### Migration

`run_migrations()` in `src/core/database.py` migrates any existing `config_profiles.google_credentials_encrypted` data into `google_global_credentials` on startup, then nulls out the profile column. See [Database Configuration](./database-configuration.md).

---

## 4. Encryption

**Module:** `src/core/encryption.py`

Uses Fernet symmetric encryption from the `cryptography` library.

| Function | Purpose |
|----------|---------|
| `get_encryption_key()` | Returns the 32-byte Fernet key (cached). Reads from `GOOGLE_OAUTH_ENCRYPTION_KEY` env var, falls back to `.encryption_key` file, or generates and persists a new key. |
| `encrypt_data(plaintext)` | Encrypts a string and returns a base64-encoded ciphertext string. |
| `decrypt_data(ciphertext)` | Decrypts. Raises `InvalidToken` if the key doesn't match. |

**Key management:**
- **Production:** Set `GOOGLE_OAUTH_ENCRYPTION_KEY` environment variable (base64-encoded 32-byte key generated by `Fernet.generate_key()`). If this variable is missing in production (`ENVIRONMENT=production`), a `RuntimeError` is raised at first use of `encrypt_data`/`decrypt_data` — not at startup.
- **Local dev:** The key is auto-generated and persisted to `.encryption_key` (gitignored).

Generate a production key:
```bash
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

**Stale key handling:** If a token or credential cannot be decrypted (e.g., after key rotation), the system silently deletes the stale record and prompts the user to re-authorize.

---

## 5. API Endpoints

### Credential Management (`src/api/routes/admin.py`)

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/api/admin/google-credentials` | Upload `credentials.json` file. Validates structure, encrypts, upserts into `google_global_credentials`. |
| `GET` | `/api/admin/google-credentials/status` | Returns `{"has_credentials": bool}`. Attempts decryption; clears stale data on failure. |
| `DELETE` | `/api/admin/google-credentials` | Removes stored credentials. Returns 204. |

**Validation:** The uploaded JSON must contain either an `"installed"` or `"web"` top-level key with `client_id` and `client_secret`.

### OAuth Flow (`/api/export/google-slides/auth`)

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/auth/status` | Returns `{"authorized": bool}`. Gracefully returns `false` on any error. |
| `GET` | `/auth/url` | Generates and returns the Google OAuth consent URL. |
| `GET` | `/auth/callback?code=...` | Exchanges auth code for tokens, encrypts, stores. Returns HTML that notifies the opener window. |

### Export (`/api/export/google-slides`)

All export routes live in `src/api/routes/google_slides.py`.

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/api/export/google-slides/from-huashu` | **Primary.** Backend fetches the deck HTML from session storage, renders it to a PPTX via the huashu (Playwright + Chromium) pipeline, and uploads it to Drive. Synchronous — returns `{presentation_id, presentation_url}` directly. |
| `POST` | `/api/export/google-slides/from-records` | **Fallback** (frontend uses it only when `/from-huashu` returns 503). Accepts DOM-walker records extracted client-side, builds a PPTX with pptxgenjs, and uploads it the same way. |
| `POST` | `/api/export/google-slides` | **Legacy** async LLM-batchUpdate job. Returns `{job_id, status, total_slides}`. Not called by the current UI — see the historical note in §1. |
| `GET` | `/api/export/google-slides/poll/{job_id}` | **Legacy** poll for the async job above. |

Both live paths are **synchronous** — a single request builds the PPTX and completes the Drive upload before responding, so there is no job/poll cycle.

The `/from-huashu` route sets `bypass_validation=True` so every slide ships even if it violates huashu's design-rule checks (overflow, text-near-bottom-edge, etc.) — otherwise a failing slide would be silently dropped and slide numbering would shift on Drive.

**Re-export:** If a session already has a presentation, the route looks up the `existing_presentation_id` via the session manager and calls `replace_presentation()` (delete + re-upload) instead of creating a new one.

**Request body (`/from-huashu`):**
```json
{ "session_id": "abc123" }
```
No client-side images or records are needed — the backend assembles complete slide HTML server-side (`_build_slide_html`, which delegates to `export.py::build_slide_html`) and substitutes `{{image:ID}}` placeholders with base64 data URIs.

**Request body (`/from-records`):**
```json
{
  "session_id": "abc123",
  "title": "Presentation",
  "slides": [ /* SlideExtract[] from domWalker.ts */ ],
  "font_mode": "google_slides"
}
```

**Response body (both live paths):**
```json
{
  "presentation_id": "1A2B3C...",
  "presentation_url": "https://docs.google.com/presentation/d/1A2B3C.../edit"
}
```

Auth uses global credentials and the user-scoped token.

---

## 6. Backend Services

### GoogleSlidesAuth (`src/services/google_slides_auth.py`)

Manages OAuth2 credentials and token lifecycle. Supports two modes:

| Mode | Constructor | Persistence |
|------|-------------|-------------|
| **DB-backed** | `GoogleSlidesAuth.from_global(user_identity, db_session)` | Encrypted in PostgreSQL |
| **File-backed** | `GoogleSlidesAuth(credentials_path=..., token_path=...)` | JSON files on disk |

Key methods:
- `is_authorized()` — Checks for valid (or refreshable) token.
- `get_auth_url(redirect_uri)` — Generates consent URL.
- `authorize(code, redirect_uri)` — Exchanges code for tokens, persists.
- `build_slides_service()` / `build_drive_service()` — Returns authenticated Google API clients.

### Huashu PPTX pipeline (`src/services/pptx_from_html_huashu.py`)

The primary path. `build_pptx_huashu(title, slides_html, bypass_validation=…)`
JSON-encodes the deck and spawns the Node sidecar
`services/pptx-emit-huashu/emit_deck.mjs`, which for each slide:

1. Launches headless Chromium via Playwright and loads the slide's complete HTML doc (sized to 1280×720 px = 13.333"×7.5", `LAYOUT_WIDE`).
2. Runs `preprocess.mjs` (`PREPROCESS_SOURCE`) as an in-page `page.evaluate()` DOM-mutation pass to bring Tellr's HTML into compliance with huashu's rules — wrap bare `<div>` text in `<p>`, flatten `<table>`s to positioned divs, rasterize `<canvas>`, transfer slide-root backgrounds to `<body>`, promote inline-background pills, etc.
3. Walks the rendered DOM in `html2pptx.js`, reading each element's `getBoundingClientRect()` and converting px→inches at 96 px/in, and emits the corresponding pptxgenjs shapes/text/images.
4. `pptxgenjs` assembles all slides into a single `.pptx`, returned as bytes.

**Availability / local-only.** The sidecar needs Chromium (via Playwright),
which Databricks Apps containers lack by default. `is_available()` gates on
`HUASHU_PIPELINE_ENABLED=1` (or `ENVIRONMENT=development`) plus node,
`playwright`, `pptxgenjs`, and an installed Chromium. When it can't run, the
route returns 503 and the frontend falls back to `/from-records`.

**Positioning is coordinate-faithful.** Element positions are measured from the
rendered DOM, not inferred — an absolutely-positioned corner element lands in
that corner in the PPTX (and therefore in Slides). The one place this was
historically broken: `preprocess.mjs::emitInlineBackgrounds()` re-centers
inline-background pills (`span`/`mark`/`kbd`) so table-cell badges sit centered
in their cell. It now branches on `position` — author-positioned
(`absolute`/`fixed`) pills keep their measured position (fixing corner
"eyebrow"/"cadence" tags that used to drift to the slide center on export),
while normal-flow badges are still centered.

**Known limitation — normal-flow badges on a wide container.** Centering a
normal-flow pill uses the resolved positioned ancestor's width. Inside a table
cell that is correct. Inside a wide list — a numbered agenda, for example — the
centre of the *list* is not the position of the *item*, so every badge resolves
to roughly the same x and they overlap. It is layout-dependent rather than
intermittent: the same markup fails the same way every time, and a narrow
single-column list looks fine while a wide or two-column one does not.
Affects the exported artifact only; the on-screen deck is unaffected.

**Tables are not native tables.** The huashu emitter produces no records for
`<td>`/`<th>`, so cells are flattened to absolutely-positioned text boxes: the
layout is faithful but the result is not editable *as a table* in PowerPoint or
Slides. This is current behaviour of the flattening approach rather than a
stated product contract. See [Export Features](./export-features.md).

### Records PPTX pipeline (`src/services/pptx_from_records.py`)

The fallback path. `build_pptx(...)` takes the `SlideExtract[]` records that
`frontend/src/services/domWalker.ts` produced by walking the deck DOM
client-side (in a hidden iframe in the user's browser) and emits a PPTX with
pptxgenjs — no server-side Chromium required. Lower fidelity than huashu but
works on any deployment.

### Drive uploader (`src/services/drive_uploader.py`)

- `upload_pptx_as_slides(auth, pptx_bytes, title)` — uploads the PPTX to Drive with `mimeType=application/vnd.google-apps.presentation`, which triggers Google's server-side conversion to a native editable Slides presentation. Returns `(presentation_id, web_view_url)`. The file is created with the requesting user's OAuth credentials, so it lives in *their* Drive with owner access (no extra sharing — the earlier "anyone-with-link" grant was removed after DoControl flagged it).
- `replace_presentation(auth, old_id, pptx_bytes, title)` — best-effort delete of the old file, then a fresh upload. Used on re-export.

### Legacy: HtmlToGoogleSlidesConverter (`src/services/html_to_google_slides.py`)

The superseded LLM code-gen converter (+ `google_slides_prompts_defaults.py`).
It creates a blank presentation via the API, prompts an LLM to emit Python that
returns `batchUpdate` request dicts, then validates/executes them host-side.
Retained for reference but not on the live export path — see §1.

---

## 7. Frontend Components

### GoogleSlidesAuthForm (`frontend/src/components/config/GoogleSlidesAuthForm.tsx`)

Rendered on the `/admin` page. Provides:
- Drag-and-drop file upload for `credentials.json`
- Status indicators (uploaded / not configured)
- Upload / replace / remove actions
- "Authorize with Google" button (opens popup)
- Authorization status (authorized / not authorized)
- Help text with instructions for obtaining credentials from Google Cloud Console

### SlidePanel (`frontend/src/components/SlidePanel/SlidePanel.tsx`)

`handleExportGoogleSlides` calls `exportToGoogleSlides(sessionId, slideDeck, onProgress)`, which POSTs to `/from-huashu` and, on 503, extracts records via `domWalker.ts` and retries against `/from-records`.

### API Services

- `frontend/src/api/config.ts` — `uploadGoogleCredentials()`, `getGoogleCredentialsStatus()`, `deleteGoogleCredentials()` (admin endpoints)
- `frontend/src/services/api.ts` — `checkGoogleSlidesAuth()`, `getGoogleSlidesAuthUrl()`, `exportToGoogleSlides(sessionId, slideDeck, onProgress)`
- `frontend/src/services/domWalker.ts` — `extractSlideRecordsForExport(deck, fontMode)`, the client-side DOM walker used only for the `/from-records` fallback

---

## 8. Test Coverage

| Test File | Tests | Coverage |
|-----------|-------|----------|
| `tests/unit/test_encryption.py` | 5 | Encrypt/decrypt roundtrip, wrong-key rejection, key sources |
| `tests/unit/config/test_google_oauth.py` | 16 | Models, credentials API, `from_global`, auth service, auth endpoint |
| `tests/unit/config/test_admin_routes.py` | — | Admin credential upload, status, delete |
| `tests/unit/test_database_migrations.py` | 4 | Migration from profile credentials to global |
| `tests/unit/test_google_slides_converter.py` | 19 | Static methods: extract, strip fences, chart notes, code prep, image save, SVG-to-PNG, content image extraction |
| `tests/unit/test_prompts_defaults.py` | 7 | PPTX + Google Slides prompt constant validation |
| `tests/unit/test_app_wiring.py` | 7 | Model registration, router exports, route registration |
| `tests/unit/test_google_slides_routes.py` | 12 | Auth endpoints, export endpoint, poll endpoint, helper functions |

Run all tests:
```bash
pytest tests/unit/ -v --ignore=tests/unit/test_chart_persistence.py \
  --ignore=tests/unit/test_deck_integrity.py \
  --ignore=tests/unit/test_llm_edit_responses.py
```

---

## 9. Configuration & Setup

### Google Cloud Console Setup

1. Go to [Google Cloud Console](https://console.cloud.google.com/).
2. Create a project (or use an existing one).
3. Enable the **Google Slides API** and **Google Drive API**.
4. Go to Credentials → Create OAuth 2.0 Client ID (Desktop app).
5. Download the `credentials.json` file.
6. Upload it on the admin page (Google Slides tab).

### Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `GOOGLE_OAUTH_ENCRYPTION_KEY` | **Yes** (production) | Fernet key for encrypting credentials/tokens. A `RuntimeError` is raised at first use of `encrypt_data`/`decrypt_data` if missing in production. |

### Dependencies

Added to `requirements.txt`:
```
google-api-python-client>=2.100.0
google-auth-oauthlib>=1.2.0
google-auth-httplib2>=0.2.0
cryptography>=42.0.0
svgpathtools>=1.6.0   # Pure-Python SVG-to-PNG conversion for image library assets
Pillow>=10.0.0         # Image rasterization (also used by PPTX export)
```

---

## 10. Cross-References

- [Export Features](./export-features.md) — PDF and PPTX export details
- [Backend Overview](./backend-overview.md) — FastAPI architecture and API surface
- [Database Configuration](./database-configuration.md) — Schema details
- [Frontend Overview](./frontend-overview.md) — React components and state management
