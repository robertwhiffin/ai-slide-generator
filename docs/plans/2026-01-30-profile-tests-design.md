# Profile Operations Test Suite Design

**Date:** 2026-01-30
**Status:** Approved
**One-Line Summary:** Comprehensive Playwright test suite for profile CRUD, switching, and session association with hybrid mocked/integration approach.

---

## Overview

The profile page is an interface to the database. Unlike slide generation tests (which mock LLM responses and validate HTML manipulation), profile tests must verify that UI operations correctly persist to the database.

### Approach: Hybrid Testing

- **Mocked UI tests** (`profile-ui.spec.ts`): Fast tests validating UI behavior, button states, form validation, wizard navigation
- **Integration tests** (`profile-integration.spec.ts`): Real backend tests validating database persistence and state management

### Test Data Strategy

Each integration test:
1. Creates a profile with unique name: `E2E Test {operation} {timestamp}`
2. Performs the operation via UI
3. Verifies via UI state AND API re-fetch
4. Deletes the test profile in cleanup

---

## File Structure

```
frontend/tests/
├── e2e/
│   ├── profile-ui.spec.ts          # ~15 mocked UI tests
│   └── profile-integration.spec.ts  # ~20 real backend tests
└── fixtures/
    └── mocks.ts                     # Extended with profile mocks
```

---

## Test Coverage

### 1. Mocked UI Tests (profile-ui.spec.ts)

#### ProfileSelector Tests
| Test | Validation |
|------|------------|
| `displays current profile name in button` | Button shows "Profile: {name}" |
| `shows "Default" badge when current profile is default` | Blue badge visible |
| `opens dropdown on click` | Dropdown menu appears |
| `closes dropdown when clicking outside` | Dropdown disappears |
| `closes dropdown after selecting a profile` | Selection triggers close |
| `shows checkmark on currently loaded profile` | Green checkmark icon |
| `shows "Manage Profiles" link` | Link navigates to ProfileList |
| `is disabled when disabled prop is true` | Button non-interactive |

#### ProfileList Tests
| Test | Validation |
|------|------------|
| `renders all profiles in table` | All mock profiles visible |
| `shows correct status badges` | Default/Loaded badges |
| `shows action buttons per profile` | View, Load, Set Default, Duplicate, Delete |
| `hides Delete button when only one profile` | Prevents orphan state |
| `hides "Set Default" for default profile` | Already default |
| `hides "Load" for currently loaded profile` | Already loaded |
| `opens confirm dialog on Delete click` | Dialog appears |
| `opens confirm dialog on Set Default click` | Dialog appears |
| `shows inline duplicate form on Duplicate click` | Input row appears |

#### ProfileCreationWizard Tests
| Test | Validation |
|------|------------|
| `opens when "+ Create Profile" clicked` | Wizard modal appears |
| `shows 5-step progress indicator` | Steps 1-5 visible |
| `Next button disabled when name empty` | Validation enforced |
| `shows character counter for name/description` | Counter updates |
| `can skip Genie space step` | Step 2 optional |
| `requires slide style selection to proceed` | Step 3 required |
| `shows review summary on final step` | All selections shown |
| `closes on Cancel or X button` | Modal closes |

---

### 2. Integration Tests (profile-integration.spec.ts)

#### Profile CRUD Operations
| Test | Database Validation |
|------|---------------------|
| `create profile via wizard saves to database` | API returns new profile |
| `created profile appears in profile list` | UI shows new row |
| `edit profile name persists to database` | Re-fetch shows new name |
| `edit profile description persists to database` | Re-fetch shows new description |
| `delete profile removes from database` | API 404 on fetch |
| `deleted profile no longer appears in list` | UI removes row |
| `duplicate profile creates copy with new name` | New profile in API |
| `duplicated profile has same associations` | Style/prompt preserved |

#### Validation Tests
| Test | Expected Behavior |
|------|-------------------|
| `cannot create profile with duplicate name` | Error message shown |
| `cannot rename profile to existing name` | Error message shown |
| `cannot delete the last remaining profile` | Delete button hidden or error |
| `wizard requires name to proceed past step 1` | Next disabled |
| `wizard requires slide style selection` | Next disabled on step 3 |

#### Profile Switching Tests
| Test | State Validation |
|------|------------------|
| `loading profile updates ProfileSelector display` | New name in button |
| `loading profile shows "Loaded" badge in list` | Green badge appears |
| `set default profile updates "Default" badge` | Blue badge moves |
| `switching profiles preserves other profile data` | No data corruption |

#### Session-Profile Association Tests
| Test | Behavior Validation |
|------|---------------------|
| `new session is associated with current profile` | Session has profile_id |
| `session history shows profile name column` | Column displays correctly |
| `restoring session from different profile triggers auto-switch` | Profile changes |
| `auto-switch loads correct profile before restoring` | Correct profile loaded |

---

## Test Utilities

### Test Data Helpers

```typescript
// Generate unique test profile name
function testProfileName(operation: string): string {
  return `E2E Test ${operation} ${Date.now()}`;
}

// Create profile via API (faster setup)
async function createTestProfile(page: Page, name: string): Promise<number>

// Delete profile via API (cleanup)
async function deleteTestProfile(page: Page, profileId: number): Promise<void>

// Get profile by name via API (verification)
async function getProfileByName(page: Page, name: string): Promise<Profile | null>
```

### Navigation Helpers

```typescript
async function goToProfiles(page: Page): Promise<void>
async function goToGenerator(page: Page): Promise<void>
async function goToHistory(page: Page): Promise<void>
```

### Wizard Helpers

```typescript
async function completeWizardStep1(page: Page, name: string, description?: string): Promise<void>
async function skipWizardStep2(page: Page): Promise<void>  // Skip Genie
async function completeWizardStep3(page: Page): Promise<void>  // Select first style
async function skipWizardStep4(page: Page): Promise<void>  // Skip deck prompt
async function submitWizard(page: Page): Promise<void>  // Click Create on review
```

### Console Error Collector

Reuse `ConsoleErrorCollector` from `deck-integrity.spec.ts` to catch unexpected browser errors.

---

## Mock Data Additions

Add to `fixtures/mocks.ts`:

```typescript
// Profile load response
export const mockProfileLoadResponse = {
  status: "reloaded",
  profile_id: 1
};

// Profile creation response
export const mockProfileCreateResponse = {
  id: 3,
  name: "New Profile",
  description: "Test description",
  is_default: false,
  created_at: "2026-01-30T10:00:00.000000",
  created_by: "test",
  updated_at: "2026-01-30T10:00:00.000000",
  updated_by: null
};

// Duplicate name error response
export const mockDuplicateNameError = {
  detail: "Profile with name 'Sales Analytics' already exists"
};

// Delete last profile error
export const mockDeleteLastProfileError = {
  detail: "Cannot delete the last profile"
};
```

---

## Test Execution

```bash
# Run only UI tests (fast, no backend needed)
npx playwright test e2e/profile-ui.spec.ts

# Run only integration tests (requires backend)
npx playwright test e2e/profile-integration.spec.ts

# Run all profile tests
npx playwright test e2e/profile-*.spec.ts

# Run with headed browser for debugging
npx playwright test e2e/profile-integration.spec.ts --headed
```

---

## CI/CD Integration

- **UI tests**: Run on every PR (fast, no dependencies)
- **Integration tests**: Run on merge to main or as separate workflow requiring backend

---

## Implementation Order

1. Add mock data to `fixtures/mocks.ts`
2. Create test utilities (helpers)
3. Implement `profile-ui.spec.ts`
4. Implement `profile-integration.spec.ts`
5. Add technical documentation to `docs/technical/profile-operations-tests.md`
