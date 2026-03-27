# Google OAuth Re-Auth Regression Tests — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add two tests that would have caught the Google OAuth re-auth regression — one backend, one frontend E2E.

**Architecture:** Backend test goes in the existing admin routes test module using the same SQLite/TestClient fixtures. Frontend test goes in the existing export E2E suite using Playwright route interception to mock auth endpoints and capture the OAuth popup trigger.

**Tech Stack:** pytest + FastAPI TestClient (backend), Playwright (frontend)

**Spec:** `docs/superpowers/specs/2026-03-27-google-oauth-reauth-tests-design.md`

---

### Task 1: Backend — test that credential upload clears user tokens

**Files:**
- Modify: `tests/unit/config/test_admin_routes.py`

- [ ] **Step 1: Write the failing test**

Add this test at the end of `tests/unit/config/test_admin_routes.py`. It uses the existing `test_client`, `session_factory` fixtures and `VALID_CREDENTIALS` constant. Import `GoogleOAuthToken` and `encrypt_data` at the top of the file.

Add to imports (top of file):

```python
from src.database.models.google_oauth_token import GoogleOAuthToken
from src.core.encryption import encrypt_data
```

Add the test:

```python
def test_upload_credentials_clears_existing_user_tokens(test_client, session_factory):
    """Uploading new credentials invalidates all existing user OAuth tokens."""
    # Seed a user token
    db = session_factory()
    db.add(GoogleOAuthToken(
        user_identity="user@example.com",
        token_encrypted=encrypt_data('{"access_token": "old"}'),
    ))
    db.commit()
    assert db.query(GoogleOAuthToken).count() == 1
    db.close()

    # Upload new credentials
    resp = test_client.post(
        "/api/admin/google-credentials",
        files={"file": ("credentials.json", VALID_CREDENTIALS, "application/json")},
    )
    assert resp.status_code == 200

    # All user tokens should be gone
    db = session_factory()
    assert db.query(GoogleOAuthToken).count() == 0
    db.close()
```

- [ ] **Step 2: Run the test to verify it passes**

```bash
cd /Users/robert.whiffin/Documents/slide-generator/ai-slide-generator
python -m pytest tests/unit/config/test_admin_routes.py::test_upload_credentials_clears_existing_user_tokens -v
```

Expected: PASS — the fix is already on `main`.

- [ ] **Step 3: Verify the test catches the regression**

Temporarily comment out the token deletion lines in `src/api/routes/admin.py` (lines 65-66):

```python
    # deleted = db.query(GoogleOAuthToken).delete()
```

Re-run the test:

```bash
python -m pytest tests/unit/config/test_admin_routes.py::test_upload_credentials_clears_existing_user_tokens -v
```

Expected: FAIL — `assert db.query(GoogleOAuthToken).count() == 0` fails because the token was not deleted.

**Restore the commented-out line immediately after confirming the failure.**

- [ ] **Step 4: Commit**

```bash
git add tests/unit/config/test_admin_routes.py
git commit -m "test: verify credential upload clears existing user OAuth tokens"
```

---

### Task 2: Frontend E2E — test that export triggers OAuth popup when unauthorized

**Files:**
- Modify: `frontend/tests/e2e/export-ui.spec.ts`

- [ ] **Step 1: Write the test**

Add a new `test.describe` block at the end of `frontend/tests/e2e/export-ui.spec.ts`, before the final closing of the file. This test uses the existing `setupMocks`, `setupStreamMock`, `goToGenerator`, and `generateSlides` helpers already defined in the file.

```typescript
// ============================================
// Google Slides OAuth Flow Tests
// ============================================

test.describe('GoogleSlidesOAuth', () => {
  test('triggers OAuth flow when user is not authorized', async ({ page }) => {
    await setupMocks(page);
    await setupStreamMock(page);

    // Mock auth status: user is NOT authorized
    await page.route('**/api/export/google-slides/auth/status', (route) => {
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ authorized: false }),
      });
    });

    // Mock auth URL endpoint — track whether it gets called
    let authUrlRequested = false;
    await page.route('**/api/export/google-slides/auth/url', (route) => {
      authUrlRequested = true;
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ url: 'https://accounts.google.com/o/oauth2/auth?fake=true' }),
      });
    });

    // Stub window.open so the popup doesn't actually open
    await page.addInitScript(() => {
      window.open = () => null;
    });

    await goToGenerator(page);
    await generateSlides(page);

    // Open export dropdown and click Google Slides
    await page.getByRole('button', { name: 'Export' }).click();
    await page.getByText('Export to Google Slides').click();

    // The app should have requested the auth URL to start the OAuth flow
    await expect(() => {
      if (!authUrlRequested) throw new Error('auth/url was not requested');
    }).toPass({ timeout: 5000 });
  });
});
```

- [ ] **Step 2: Run the test to verify it passes**

```bash
cd /Users/robert.whiffin/Documents/slide-generator/ai-slide-generator/frontend
npx playwright test tests/e2e/export-ui.spec.ts -g "triggers OAuth flow" --headed
```

Expected: PASS — the fix is already on `main`.

- [ ] **Step 3: Verify the test catches the regression**

Temporarily revert the auth check in `frontend/src/components/Layout/AppLayout.tsx` by commenting out lines 475-485 (the `checkGoogleSlidesAuth` + `openOAuthPopup` block).

Re-run:

```bash
npx playwright test tests/e2e/export-ui.spec.ts -g "triggers OAuth flow"
```

Expected: FAIL — `authUrlRequested` stays `false` because the export goes straight to the export endpoint without checking auth.

**Restore the commented-out lines immediately after confirming the failure.**

- [ ] **Step 4: Commit**

```bash
cd /Users/robert.whiffin/Documents/slide-generator/ai-slide-generator
git add frontend/tests/e2e/export-ui.spec.ts
git commit -m "test(e2e): verify Google Slides export triggers OAuth when unauthorized"
```

---

### Task 3: Final — run full test suites and push

- [ ] **Step 1: Run backend admin tests**

```bash
cd /Users/robert.whiffin/Documents/slide-generator/ai-slide-generator
python -m pytest tests/unit/config/test_admin_routes.py -v
```

Expected: All tests pass (existing + new).

- [ ] **Step 2: Run frontend export E2E tests**

```bash
cd /Users/robert.whiffin/Documents/slide-generator/ai-slide-generator/frontend
npx playwright test tests/e2e/export-ui.spec.ts
```

Expected: All tests pass (existing + new).

- [ ] **Step 3: Push branch**

```bash
cd /Users/robert.whiffin/Documents/slide-generator/ai-slide-generator
git push -u origin test/google-oauth-reauth-regression
```
