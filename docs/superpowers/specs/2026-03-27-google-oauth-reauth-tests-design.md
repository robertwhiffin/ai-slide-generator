# Google OAuth Re-Auth Regression Tests

## Problem

Commit `c3942b6` moved export buttons from `SlidePanel` to `PageHeader` but dropped the auth-check-before-export flow. Users who lacked a valid token saw a generic error toast instead of the OAuth popup. The backend also had no mechanism to invalidate user tokens when admin credentials changed. Neither gap was caught by existing tests.

## Tests to Add

### 1. Backend: credential upload clears user tokens

**File:** `tests/unit/config/test_admin_routes.py`

Add one test to the existing module. Uses the same fixtures (`test_client`, `session_factory`, `_clean_data`).

**Test:** `test_upload_credentials_clears_existing_user_tokens`

Steps:
1. Seed a `GoogleOAuthToken` row for a user (encrypted dummy token).
2. `POST /api/admin/google-credentials` with valid credentials.
3. Query `google_oauth_tokens` — assert zero rows remain.

This directly validates the `db.query(GoogleOAuthToken).delete()` line added in the fix.

### 2. Frontend: export triggers OAuth popup when unauthorized

**File:** `frontend/tests/e2e/export-ui.spec.ts`

Add one test to the existing export E2E suite. Uses the same mock setup patterns (route interception).

**Test:** `triggers OAuth flow when user is not authorized for Google Slides`

Steps:
1. Mock `/api/export/google-slides/auth/status` → `{ authorized: false }`.
2. Mock `/api/export/google-slides/auth/url` → `{ url: "https://accounts.google.com/fake" }`.
3. Stub `window.open` via `page.addInitScript` to capture calls without opening a real popup.
4. Open the export dropdown, click "Export to Google Slides".
5. Assert that `/api/export/google-slides/auth/url` was requested (the OAuth flow was initiated, not a silent failure).

### What these tests would have caught

- **Backend test:** Would fail if credential upload doesn't clear `google_oauth_tokens` — the exact backend gap.
- **Frontend test:** Would fail if the export handler calls the export endpoint directly without checking auth status first — the exact frontend regression from `c3942b6`.
