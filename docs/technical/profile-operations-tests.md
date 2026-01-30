# Profile Operations Test Suite

**One-Line Summary:** Comprehensive Playwright test coverage for profile CRUD, switching, validation, and session association with hybrid mocked/integration approach.

---

## 1. Overview

The profile operations test suite validates that profile-related UI operations correctly interact with the database. Unlike slide generation tests (which mock LLM responses and validate HTML manipulation), profile tests must verify that UI operations correctly persist to the database.

### Test Files

| File | Test Count | Purpose |
|------|------------|---------|
| `frontend/tests/e2e/profile-ui.spec.ts` | 26 | Mocked UI behavior tests |
| `frontend/tests/e2e/profile-integration.spec.ts` | 21 | Real backend persistence tests |

### Testing Approach

- **Mocked UI tests**: Fast tests validating UI behavior without backend
- **Integration tests**: Real backend tests validating database persistence

---

## 2. Mocked UI Tests (profile-ui.spec.ts)

These tests use mocked API responses for fast execution. They validate UI behavior without hitting the backend.

### 2.1 ProfileSelector Tests

```
tests/e2e/profile-ui.spec.ts::ProfileSelector
```

| Test | Validation |
|------|------------|
| `displays current profile name in button` | Button shows "Profile: {name}" |
| `shows "Default" badge when current profile is default` | Blue badge visible |
| `opens dropdown on click` | Dropdown menu appears |
| `closes dropdown when clicking outside` | Dropdown disappears |
| `shows checkmark on currently loaded profile` | Green checkmark icon |
| `shows "Manage Profiles" link` | Link navigates to ProfileList |

---

### 2.2 ProfileList Tests

```
tests/e2e/profile-ui.spec.ts::ProfileList
```

| Test | Validation |
|------|------------|
| `renders all profiles in table` | All profiles visible |
| `shows correct status badges` | Default/Loaded badges |
| `shows action buttons per profile` | View, Load, Set Default, Duplicate, Delete |
| `hides "Set Default" for default profile` | Button hidden for default |
| `hides "Load" for currently loaded profile` | Button hidden for loaded |
| `opens confirm dialog on Delete click` | Confirmation required |
| `opens confirm dialog on Set Default click` | Confirmation required |
| `shows inline duplicate form on Duplicate click` | Input form appears |
| `Create Profile button opens wizard` | Wizard modal opens |

---

### 2.3 ProfileCreationWizard Tests

```
tests/e2e/profile-ui.spec.ts::ProfileCreationWizard
```

| Test | Validation |
|------|------------|
| `opens when "+ Create Profile" clicked` | Wizard modal visible |
| `shows 5-step progress indicator` | Steps 1-5 displayed |
| `Next button disabled when name empty` | Validation enforced |
| `shows character counter for name field` | Counter updates |
| `can skip Genie space step` | Step 2 optional |
| `requires slide style selection to proceed` | Step 3 required |
| `shows review summary on final step` | All selections shown |
| `closes on Cancel button` | Modal closes |
| `closes on X button` | Modal closes |

---

### 2.4 Form Validation Tests

```
tests/e2e/profile-ui.spec.ts::Profile Form Validation
```

| Test | Validation |
|------|------------|
| `shows error for duplicate name on create` | Error message displayed |
| `enforces maximum character limit for name` | Input truncated at 100 chars |

---

## 3. Integration Tests (profile-integration.spec.ts)

These tests hit the real backend to validate database persistence. Each test creates its own test data and cleans up after itself.

### Test Data Strategy

- **Naming**: `E2E Test {operation} {timestamp}`
- **Isolation**: Each test creates unique profile
- **Cleanup**: Profile deleted in finally block

### 3.1 Profile CRUD Operations

```
tests/e2e/profile-integration.spec.ts::Profile CRUD Operations
```

| Test | Database Validation |
|------|---------------------|
| `create profile via wizard saves to database` | API returns new profile |
| `created profile appears in profile list` | UI shows new row |
| `edit profile name persists to database` | Re-fetch shows new name |
| `edit profile description persists to database` | Re-fetch shows new description |
| `delete profile removes from database` | API 404 on fetch |
| `deleted profile no longer appears in list` | UI removes row |
| `duplicate profile creates copy with new name` | New profile in API |

---

### 3.2 Validation Tests

```
tests/e2e/profile-integration.spec.ts::Profile Validation
```

| Test | Expected Behavior |
|------|-------------------|
| `cannot create profile with duplicate name` | Error message shown |
| `cannot rename profile to existing name` | Error message shown |
| `wizard requires name to proceed past step 1` | Next button disabled |
| `wizard requires slide style selection` | Next button disabled on step 3 |

---

### 3.3 Profile Switching Tests

```
tests/e2e/profile-integration.spec.ts::Profile Switching
```

| Test | State Validation |
|------|------------------|
| `loading profile updates ProfileSelector display` | New name in button |
| `loading profile shows "Loaded" badge in list` | Green badge appears |
| `set default profile updates "Default" badge` | Blue badge moves |
| `switching profiles preserves other profile data` | No data corruption |

---

### 3.4 Session-Profile Association Tests

```
tests/e2e/profile-integration.spec.ts::Session-Profile Association
```

| Test | Behavior Validation |
|------|---------------------|
| `session history shows profile name column` | Column header visible |
| `new session is associated with current profile` | Session has profile_id |
| `restoring session from different profile triggers auto-switch` | Profile changes |

---

### 3.5 Edge Case Tests

```
tests/e2e/profile-integration.spec.ts::Profile Edge Cases
```

| Test | Validation |
|------|------------|
| `cannot delete the only remaining profile` | Delete button hidden/disabled |
| `special characters in profile name are handled correctly` | Saved and retrieved |
| `unicode characters in profile name are handled correctly` | Preserved correctly |

---

## 4. Running the Tests

```bash
# Run only UI tests (fast, no backend needed)
npx playwright test tests/e2e/profile-ui.spec.ts

# Run only integration tests (requires backend at localhost:8000)
npx playwright test tests/e2e/profile-integration.spec.ts

# Run all profile tests
npx playwright test tests/e2e/profile-*.spec.ts

# Run with headed browser for debugging
npx playwright test tests/e2e/profile-integration.spec.ts --headed

# Run specific test
npx playwright test tests/e2e/profile-integration.spec.ts -g "create profile"
```

---

## 5. Test Utilities

### API Helpers

Located in `profile-integration.spec.ts`:

```typescript
// Generate unique test profile name
function testProfileName(operation: string): string

// Create profile via API (faster setup)
async function createTestProfileViaAPI(request, name, description?): Promise<Profile>

// Delete profile via API (cleanup)
async function deleteTestProfileViaAPI(request, profileId): Promise<void>

// Get profile by name via API (verification)
async function getProfileByName(request, name): Promise<Profile | null>
```

### Wizard Helpers

```typescript
async function completeWizardStep1(page, name, description?): Promise<void>
async function skipWizardStep2(page): Promise<void>  // Skip Genie
async function completeWizardStep3(page): Promise<void>  // Select first style
async function skipWizardStep4(page): Promise<void>  // Skip deck prompt
async function submitWizard(page): Promise<void>
```

---

## 6. Mock Data

Mock data for UI tests located in `frontend/tests/fixtures/mocks.ts`:

| Mock | Purpose |
|------|---------|
| `mockProfiles` | List of profiles |
| `mockProfileLoadResponse` | Profile load/switch response |
| `mockProfileCreateResponse` | Profile creation response |
| `mockProfileUpdateResponse` | Profile update response |
| `mockDuplicateNameError` | 409 error for duplicate name |
| `mockDeleteLastProfileError` | 400 error for last profile |
| `mockGenieSpaces` | Genie spaces for wizard |
| `mockProfileDetail` | Full profile with associations |

---

## 7. CI/CD Integration

```yaml
# Suggested workflow configuration
profile-ui-tests:
  name: Profile UI Tests (Mocked)
  steps:
    - run: npx playwright test tests/e2e/profile-ui.spec.ts

profile-integration-tests:
  name: Profile Integration Tests
  needs: [backend-ready]
  steps:
    - run: npx playwright test tests/e2e/profile-integration.spec.ts
```

---

## 8. Key Invariants

These invariants must NEVER be violated:

1. **CRUD persistence**: All profile operations must save to database
2. **Unique names**: No two profiles can have the same name
3. **Default protection**: Cannot delete the last/only profile
4. **Session tracking**: Sessions must track their profile_id
5. **Auto-switch**: Restoring a session should auto-switch to its profile

---

## 9. Debugging Test Failures

### Common Issues

| Symptom | Likely Cause | Fix |
|---------|--------------|-----|
| Integration tests fail to connect | Backend not running | Start backend at localhost:8000 |
| Duplicate name not detected | Race condition | Add wait after creation |
| Cleanup fails | Profile is default | Set another as default first |
| Session association test skipped | No sessions exist | Create sessions first |

### Useful Commands

```bash
# Run with debug logs
DEBUG=pw:api npx playwright test tests/e2e/profile-integration.spec.ts

# Generate trace on failure
npx playwright test --trace on

# View test report
npx playwright show-report
```

---

## 10. Cross-References

- [Profile Switch Genie Flow](./profile-switch-genie-flow.md) - Profile switching implementation details
- [Deck Operations Tests](./deck-operations-tests.md) - Related test suite patterns
- [Edit Operations Tests](./edit-operations-tests.md) - LLM response validation tests
- [Frontend Overview](./frontend-overview.md) - Component architecture
