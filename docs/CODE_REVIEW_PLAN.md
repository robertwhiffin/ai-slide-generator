# Code Review Plan: config-pane Branch
## Comprehensive Review for Legacy, Redundant, and Poorly Implemented Code

**Created:** 2025-11-20  
**Branch:** config-pane  
**Context:** After extensive iterations implementing database-backed configuration system

---

## Executive Summary

This branch (`config-pane`) has undergone **70+ commits** over the past month, implementing a major architectural shift from YAML-based configuration to a database-backed profile system. The extensive iteration has likely left behind:

1. **Legacy code** from the old YAML-based system
2. **Duplicate implementations** created during rapid development
3. **Import inconsistencies** (old vs new settings)
4. **Unused configuration files** (YAML files no longer needed)
5. **Test files** still using old patterns
6. **Documentation drift** from implementation changes

### High-Churn Files (Most Modified)
These files have been modified most frequently and warrant careful review:

| File | Changes | Review Priority |
|------|---------|-----------------|
| `README.md` | 15 | High - May contain outdated info |
| `src/services/agent.py` | 13 | Critical - Core logic |
| `config/prompts.yaml` | 11 | High - May be legacy |
| `src/api/services/chat_service.py` | 9 | High - Core service |
| `src/services/tools.py` | 8 | High - Recently fixed import |
| `src/config/settings.py` | 8 | Critical - Legacy vs new |
| `frontend/src/components/Layout/AppLayout.tsx` | 8 | High - Multiple refactors |

---

## Branch Evolution Timeline

### Phase 1: Initial Setup (Nov 5-7)
- Fresh start with minimal setup
- Databricks client creation and testing
- MLflow 3.0 tracing implementation
- Genie tool implementation

### Phase 2: Agent Architecture (Nov 11-14)
- Multi-turn conversation support
- Slide parser implementation
- Chat interface and slide rendering
- HTML deck manipulation

### Phase 3: Database Migration (Nov 19)
- Database-backed configuration system (Phases 1-6)
- Profile management UI
- Settings migration from YAML to database

### Phase 4: Genie Refactoring (Nov 20)
- Multiple Genie spaces → Single space per profile
- Removed "is_default" concept
- Fixed profile switching and state management
- **7 commits in one day** addressing bugs from rapid changes

### Phase 5: Bug Fixes and Cleanup (Nov 20, latest)
- Import fixes (`settings.py` → `settings_db.py`)
- Profile state synchronization
- Genie conversation initialization fixes
- Chat state reset on profile switch

---

## Critical Issues Identified

### 1. Dual Settings Systems (CONFIRMED ISSUE)

**Problem:** Two complete settings systems coexist:
- **Old (YAML-based):** `src/config/settings.py` (378 lines)
- **New (Database-backed):** `src/config/settings_db.py` (420 lines)

**Evidence:**
- Recent bug: `tools.py` was importing from wrong settings file
- Both define `AppSettings` class
- `settings.py` referenced in tests and docs

**Files Using Old Settings:**
```
tests/integration/test_genie_integration.py
tests/unit/test_settings.py
tests/conftest.py
docs/backend-database-implementation/PHASE_4_COMPLETE.md
docs/technical/databricks-app-deployment.md
```

**Review Actions:**
1. ✅ Audit all imports: `from src.config.settings import`
2. ✅ Determine if `settings.py` can be deleted or marked as legacy
3. ✅ Update all tests to use `settings_db.py`
4. ✅ Check if `config/loader.py` is still needed (YAML loader)
5. ✅ Review `config/defaults.py` usage

---

### 2. Legacy YAML Configuration Files

**Files in `config/` directory:**
```
config.example.yaml       # 1,536 bytes
config.yaml              # 1,409 bytes
deployment.example.yaml  # 1,965 bytes
deployment.yaml          # 2,027 bytes
mlflow.yaml              # 2,007 bytes
prompts.yaml             # 11,089 bytes (11 modifications)
```

**Questions:**
- Are these still loaded at startup?
- Are they used for defaults when creating database profiles?
- Can they be archived or deleted?
- Is `prompts.yaml` still the source of truth?

**Review Actions:**
1. ✅ Check if `config/loader.py` loads any YAML files
2. ✅ Verify `init_default_profile.py` dependencies
3. ✅ Determine if `prompts.yaml` should migrate to database
4. ✅ Archive or delete unused YAML files
5. ✅ Update `.gitignore` if files are kept for local dev only

---

### 3. Duplicate Validator Files

**Problem:** Two validator implementations exist:

```
src/services/config/validator.py          # 143 lines
src/services/config/config_validator.py   # 415 lines
```

**Context from git diff:**
- `config_validator.py` was recently deleted in uncommitted work (415 lines removed)
- But still exists in current branch
- Validation API routes also deleted: `src/api/routes/config/validation.py` (184 lines)
- Frontend `ValidationButton.tsx` deleted (142 lines)

**Review Actions:**
1. ✅ Confirm which validator is active
2. ✅ Check if `validator.py` is used anywhere
3. ✅ Delete unused validator file
4. ✅ Ensure validation still works without deleted files
5. ✅ Update imports if needed

---

### 4. Frontend State Management Inconsistencies

**Recent Changes:**
- Created `ProfileContext.tsx` (241 lines) - then deleted in uncommitted work?
- Refactored `useProfiles.ts` multiple times
- `useConfig.ts` modified to handle single genie_space

**Git diff shows:**
- `ProfileContext.tsx` deleted (-241 lines)
- `useProfiles.ts` grew significantly (+207 lines)
- State management moved back to hooks?

**Review Actions:**
1. ✅ Verify current state management pattern
2. ✅ Check if Context API is still used
3. ✅ Ensure no duplicate state management
4. ✅ Review profile synchronization logic
5. ✅ Check for race conditions in state updates

---

### 5. Deleted Components Still Referenced?

**Recently Deleted (per git diff):**
```
frontend/src/components/config/GenieSpacesManager.tsx  # -339 lines
frontend/src/components/config/ValidationButton.tsx    # -142 lines
src/api/routes/config/validation.py                   # -184 lines
src/services/config/config_validator.py               # -415 lines
docs/features/configuration-validation.md             # -170 lines
```

**Review Actions:**
1. ✅ Search for imports of deleted components
2. ✅ Check if any routes reference deleted validation endpoints
3. ✅ Verify frontend still compiles and runs
4. ✅ Update documentation referencing deleted features
5. ✅ Remove from exports in `index.ts` files

---

### 6. Database Migration Status

**Migration Files:**
```
alembic/versions/001_initial_schema.py
alembic/versions/002_remove_genie_default.py  # -126 lines in diff (deleted?)
```

**Questions:**
- Why is `002_remove_genie_default.py` showing as deleted in uncommitted changes?
- Is the migration already applied?
- Are there more migrations needed?

**Review Actions:**
1. ✅ Check alembic current head: `alembic current`
2. ✅ Verify migration history: `alembic history`
3. ✅ Confirm database schema matches models
4. ✅ Check for any pending migrations
5. ✅ Review migration safety (downgrade paths)

---

### 7. Test Suite Inconsistencies

**High-churn test files:**
```
test_agent_live.py           # 9 modifications
tests/unit/test_tools.py     # 6 modifications
tests/unit/test_agent.py     # 4 modifications
tests/integration/test_genie_integration.py  # 4 modifications
```

**Known Issues:**
- Tests may still import from `settings.py` instead of `settings_db.py`
- Tests may reference deleted validation functionality
- Tests may not cover new profile switching logic

**Review Actions:**
1. ✅ Run full test suite and document failures
2. ✅ Update test imports to use `settings_db`
3. ✅ Remove tests for deleted features (validation)
4. ✅ Add tests for profile switching with Genie
5. ✅ Ensure database fixtures work correctly

---

### 8. Documentation Drift

**Documentation that needs review:**

**Backend Database Implementation Docs:**
```
docs/backend-database-implementation/
├── PHASE_1_COMPLETE.md
├── PHASE_2_COMPLETE.md
├── PHASE_3_COMPLETE.md
├── PHASE_4_COMPLETE.md
├── PHASE_5_COMPLETE.md
├── PHASE_6_COMPLETE.md
├── PHASE_7_HISTORY_POLISH.md
├── PHASE_8_DOCUMENTATION_DEPLOYMENT.md
└── README.md
```

**Technical Docs:**
```
docs/technical/
├── backend-overview.md
├── database-configuration.md        # Updated recently
├── databricks-app-deployment.md
├── frontend-overview.md
├── profile-switch-genie-flow.md     # Just added
└── slide-parser-and-script-management.md
```

**Other Docs:**
```
docs/CONFIG_MANAGEMENT_UI_PLAN.md    # 1,806 lines - still relevant?
docs/features/configuration-validation.md  # Deleted per diff
```

**Review Actions:**
1. ✅ Archive completed phase docs to `docs/archive/`
2. ✅ Verify technical docs match current implementation
3. ✅ Update `README.md` with current architecture
4. ✅ Remove references to deleted features
5. ✅ Consolidate redundant documentation

---

## Detailed Review Checklist

### A. Configuration System Cleanup

#### A1. Settings Files Review
- [ ] **Audit `src/config/settings.py`**
  - [ ] List all imports of this file
  - [ ] Determine if it's still used by any production code
  - [ ] Check if it's needed for backward compatibility
  - [ ] Decision: Delete, deprecate, or keep?

- [ ] **Audit `src/config/settings_db.py`**
  - [ ] Verify it's the canonical source of settings
  - [ ] Check cache invalidation logic works correctly
  - [ ] Review `reload_settings()` implementation
  - [ ] Confirm `get_settings()` cache behavior

- [ ] **Audit `src/config/loader.py`**
  - [ ] Check if YAML loading is still used
  - [ ] Verify it's not called during startup
  - [ ] Decision: Delete or keep for dev/testing?

- [ ] **Audit `src/config/defaults.py`**
  - [ ] Check if used for database initialization
  - [ ] Verify default values match database schema
  - [ ] Update if needed, delete if unused

#### A2. YAML Configuration Files
- [ ] **Review `config/config.yaml`**
  - [ ] Check if loaded anywhere in code
  - [ ] Verify if needed for default profile creation
  - [ ] Decision: Archive to `config/legacy/`?

- [ ] **Review `config/prompts.yaml`**
  - [ ] Confirm it's still loaded into database
  - [ ] Check if changes here update database
  - [ ] Consider migrating to database-only storage

- [ ] **Review `config/mlflow.yaml`**
  - [ ] Verify if still referenced
  - [ ] Check if superseded by database config
  - [ ] Decision: Keep or delete?

- [ ] **Review `config/deployment.yaml`**
  - [ ] Confirm usage in deployment scripts
  - [ ] Check if Databricks Apps config file
  - [ ] Keep if needed for deployment

#### A3. Client and Database Files
- [ ] **Review `src/config/client.py`**
  - [ ] Verify Databricks client initialization
  - [ ] Check for any legacy patterns
  - [ ] Ensure proper error handling

- [ ] **Review `src/config/database.py`**
  - [ ] Check session management
  - [ ] Verify connection pooling settings
  - [ ] Review transaction handling

- [ ] **Review `src/config/init_default_profile.py`**
  - [ ] Verify default profile creation logic
  - [ ] Check dependency on YAML files
  - [ ] Ensure proper Genie space initialization

---

### B. Service Layer Review

#### B1. Agent Service
- [ ] **Review `src/services/agent.py` (783 lines, 13 changes)**
  - [ ] Check for commented-out code
  - [ ] Verify Genie conversation initialization
  - [ ] Review session management logic
  - [ ] Confirm proper use of `get_settings()`
  - [ ] Check for any YAML-based config references
  - [ ] Verify MLflow integration still works
  - [ ] Review error handling completeness

#### B2. Tools Service
- [ ] **Review `src/services/tools.py` (8 changes)**
  - [ ] ✅ Verify imports from `settings_db` (FIXED)
  - [ ] Check Genie conversation lazy initialization
  - [ ] Review error handling in Genie queries
  - [ ] Verify logging includes correct space_id
  - [ ] Check for any legacy patterns

#### B3. Chat Service
- [ ] **Review `src/api/services/chat_service.py` (9 changes)**
  - [ ] Review `reload_agent()` implementation
  - [ ] Check session state preservation logic
  - [ ] Verify Genie conversation ID clearing
  - [ ] Review thread safety (reload lock)
  - [ ] Check for race conditions

#### B4. Config Services
- [ ] **Review `src/services/config/` directory**
  - [ ] **`profile_service.py`**: Profile CRUD operations
  - [ ] **`genie_service.py`**: Single space per profile logic
  - [ ] **`config_service.py`**: General config management
  - [ ] **`validator.py`**: Still used? (143 lines)
  - [ ] **`config_validator.py`**: Deleted? (415 lines)
  - [ ] Check for duplicate functionality
  - [ ] Verify error handling consistency
  - [ ] Review transaction management

---

### C. API Layer Review

#### C1. Config API Routes
- [ ] **Review `src/api/routes/config/` directory**
  - [ ] **`profiles.py`**: Profile management endpoints
  - [ ] **`genie.py`**: Genie space endpoints (recently refactored)
  - [ ] **`ai_infra.py`**: LLM config endpoints
  - [ ] **`mlflow.py`**: MLflow config endpoints
  - [ ] **`prompts.py`**: Prompts config endpoints
  - [ ] **`validation.py`**: Deleted? (184 lines)

- [ ] **Check for:**
  - [ ] Deleted endpoints still registered in `__init__.py`
  - [ ] Proper error responses (4xx, 5xx)
  - [ ] Consistent response models
  - [ ] Missing validation
  - [ ] Duplicate endpoint definitions

#### C2. Main API Configuration
- [ ] **Review `src/api/main.py`**
  - [ ] Check registered routes
  - [ ] Verify CORS settings
  - [ ] Review middleware configuration
  - [ ] Check startup/shutdown events
  - [ ] Verify settings initialization

---

### D. Database Layer Review

#### D1. Models Review
- [ ] **Review `src/models/config/` directory**
  - [ ] **`profile.py`**: Profile model
  - [ ] **`genie_space.py`**: Genie space model (unique constraint)
  - [ ] **`ai_infra.py`**: LLM config model
  - [ ] **`mlflow.py`**: MLflow config model
  - [ ] **`prompts.py`**: Prompts config model
  - [ ] **`history.py`**: Config history model

- [ ] **Check for:**
  - [ ] Proper indexes
  - [ ] Foreign key constraints
  - [ ] Default values
  - [ ] Nullable fields
  - [ ] Unique constraints
  - [ ] Cascade delete behavior

#### D2. Migrations Review
- [ ] **Review Alembic migrations**
  - [ ] Run `alembic current` to check head
  - [ ] Run `alembic history` to see all migrations
  - [ ] Verify `001_initial_schema.py` is applied
  - [ ] Check status of `002_remove_genie_default.py`
  - [ ] Test downgrade paths
  - [ ] Verify data integrity after migrations

#### D3. Database Configuration
- [ ] **Review `alembic.ini`**
  - [ ] Check SQLite vs PostgreSQL settings
  - [ ] Verify database URL configuration
  - [ ] Review logging settings

- [ ] **Review database file**
  - [ ] Check `ai_slide_generator.db` size and integrity
  - [ ] Verify not committed to git (in `.gitignore`)
  - [ ] Consider backup strategy

---

### E. Frontend Review

#### E1. State Management
- [ ] **Review state management architecture**
  - [ ] ✅ `ProfileContext.tsx` deleted? Verify
  - [ ] `useProfiles.ts` - recent refactor (+207 lines)
  - [ ] `useConfig.ts` - modified for single genie_space
  - [ ] Check for duplicate state
  - [ ] Verify synchronization between components

#### E2. Component Review
- [ ] **Review `frontend/src/components/config/`**
  - [ ] ✅ `GenieSpacesManager.tsx` - Deleted (confirmed)
  - [ ] ✅ `ValidationButton.tsx` - Deleted (confirmed)
  - [ ] `ProfileSelector.tsx` - Multiple changes
  - [ ] `ProfileList.tsx` - State management changes
  - [ ] `ProfileDetail.tsx` - Layout fixes
  - [ ] `GenieForm.tsx` - Logic fixes
  - [ ] `ConfigTabs.tsx` - Tab management
  - [ ] Check for unused imports
  - [ ] Verify proper cleanup (useEffect returns)

#### E3. API Client
- [ ] **Review `frontend/src/api/config.ts`**
  - [ ] Check for removed API calls (validation, default genie)
  - [ ] Verify error handling
  - [ ] Check request/response types match backend
  - [ ] Review authentication handling

#### E4. Layout Components
- [ ] **Review `frontend/src/components/Layout/`**
  - [ ] `AppLayout.tsx` (8 changes) - Chat reset logic
  - [ ] Check for state management issues
  - [ ] Verify proper prop drilling or context usage

---

### F. Testing Review

#### F1. Unit Tests
- [ ] **Review `tests/unit/`**
  - [ ] Update imports from `settings` to `settings_db`
  - [ ] Remove tests for deleted validation feature
  - [ ] Add tests for profile switching
  - [ ] Add tests for Genie conversation initialization
  - [ ] Check test coverage with `pytest --cov`

#### F2. Integration Tests
- [ ] **Review `tests/integration/`**
  - [ ] `test_config_api.py` - Updated for single Genie space
  - [ ] `test_genie_integration.py` - Check settings import
  - [ ] Add tests for profile reload scenarios
  - [ ] Test database transactions
  - [ ] Test concurrent profile switches

#### F3. Test Configuration
- [ ] **Review `tests/conftest.py`**
  - [ ] Update settings import if using old one
  - [ ] Verify database fixtures
  - [ ] Check test database isolation
  - [ ] Review cleanup logic

#### F4. Live Test Scripts
- [ ] **Review `test_agent_live.py`**
  - [ ] 9 modifications - check for legacy patterns
  - [ ] Verify it uses current API
  - [ ] Update if using old settings
  - [ ] Consider moving to proper test suite

---

### G. Documentation Review

#### G1. Technical Documentation
- [ ] **Review `docs/technical/`**
  - [ ] ✅ `profile-switch-genie-flow.md` - Just added, keep
  - [ ] `database-configuration.md` - Recently updated
  - [ ] `backend-overview.md` - May need updates
  - [ ] `frontend-overview.md` - May need updates
  - [ ] `databricks-app-deployment.md` - Check for old settings refs
  - [ ] `slide-parser-and-script-management.md` - Verify current

#### G2. Implementation Docs
- [ ] **Review `docs/backend-database-implementation/`**
  - [ ] Archive completed phases to `docs/archive/`
  - [ ] Keep summary in `README.md`
  - [ ] Update with actual implementation deviations
  - [ ] Note any skipped or deferred features

#### G3. Configuration Plan
- [ ] **Review `docs/CONFIG_MANAGEMENT_UI_PLAN.md`**
  - [ ] 1,806 lines - massive planning doc
  - [ ] Check if all features implemented
  - [ ] Archive if completed
  - [ ] Extract any still-relevant future work

#### G4. Feature Documentation
- [ ] **Review `docs/features/`**
  - [ ] ✅ `configuration-validation.md` - Deleted feature
  - [ ] Check for other outdated features
  - [ ] Add documentation for new features

#### G5. README
- [ ] **Review root `README.md`**
  - [ ] 15 modifications - likely outdated sections
  - [ ] Update architecture diagram if exists
  - [ ] Update getting started instructions
  - [ ] Remove references to YAML config if appropriate
  - [ ] Update environment variables section
  - [ ] Verify deployment instructions

---

### H. Build and Deployment Review

#### H1. Build Configuration
- [ ] **Review `pyproject.toml`**
  - [ ] 6 modifications - check for legacy deps
  - [ ] Verify all dependencies still needed
  - [ ] Check version pins
  - [ ] Review dev dependencies

- [ ] **Review `requirements.txt`**
  - [ ] 7 modifications - audit dependencies
  - [ ] Check for unused packages
  - [ ] Verify version compatibility
  - [ ] Consider using only `pyproject.toml`

#### H2. Build Artifacts
- [ ] **Review `build/` directory**
  - [ ] Check if should be in `.gitignore`
  - [ ] Contains duplicate config files
  - [ ] Clean if not needed

- [ ] **Review `src/ai_slide_generator.egg-info/`**
  - [ ] Check if in `.gitignore`
  - [ ] Verify not committed to git

#### H3. Deployment Configuration
- [ ] **Review `config/deployment.yaml`**
  - [ ] Verify Databricks Apps configuration
  - [ ] Check resource allocations
  - [ ] Review environment variables

---

### I. Code Quality Issues

#### I1. Import Patterns
- [ ] **Search for import issues:**
  ```bash
  # Find all settings imports
  grep -r "from src.config.settings import" src/
  grep -r "from src.config import settings" src/
  
  # Find all loader imports (YAML)
  grep -r "from src.config.loader import" src/
  
  # Find deleted component imports
  grep -r "GenieSpacesManager" frontend/src/
  grep -r "ValidationButton" frontend/src/
  grep -r "config_validator" src/
  ```

#### I2. Dead Code
- [ ] **Search for commented code:**
  ```bash
  # Find large blocks of commented Python code
  grep -r "# def " src/ | wc -l
  
  # Find TODO comments
  grep -r "# TODO" src/
  grep -r "// TODO" frontend/src/
  ```

- [ ] **Check for unused functions:**
  - Run `vulture` or similar tool
  - Check for functions never called
  - Check for unused imports

#### I3. Error Handling
- [ ] **Audit error handling patterns:**
  - [ ] Bare `except:` clauses
  - [ ] Missing error logging
  - [ ] Swallowed exceptions
  - [ ] Missing user-facing error messages

#### I4. Type Hints
- [ ] **Review type hint coverage:**
  - Run `mypy src/`
  - Check for `Any` overuse
  - Verify return type annotations
  - Check function parameter types

---

## Specific Code Smells to Look For

### Backend (Python)

1. **Settings Import Mismatches**
   ```python
   # BAD - Old settings
   from src.config.settings import get_settings
   
   # GOOD - New settings
   from src.config.settings_db import get_settings
   ```

2. **YAML File Loading**
   ```python
   # Search for YAML loading
   yaml.safe_load(...)
   yaml.load(...)
   ```

3. **Genie Default Logic**
   ```python
   # Old pattern - should be removed
   is_default=True
   .filter(is_default=True)
   set_default_genie_space(...)
   ```

4. **Multiple Settings Instances**
   ```python
   # Check for settings not using get_settings()
   settings = AppSettings(...)
   settings = load_settings_from_database(...)
   ```

5. **Database Session Issues**
   ```python
   # Missing commit or rollback
   db.add(...)
   # Missing: db.commit()
   
   # Not using context manager
   db = get_db_session()
   # Should be: with get_db_session() as db:
   ```

### Frontend (TypeScript/React)

1. **Deleted Component Imports**
   ```typescript
   // Should not exist
   import { GenieSpacesManager } from './config/GenieSpacesManager';
   import { ValidationButton } from './config/ValidationButton';
   ```

2. **Deleted API Calls**
   ```typescript
   // Old API calls that should be removed
   configApi.listGenieSpaces(...)  // Changed to getGenieSpace
   configApi.setDefaultGenieSpace(...)  // Removed
   configApi.getDefaultGenieSpace(...)  // Removed
   ```

3. **State Management Duplication**
   ```typescript
   // Check for duplicate profile state
   const [profiles, setProfiles] = useState(...);  // In multiple components?
   const [currentProfile, setCurrentProfile] = useState(...);  // Duplicated?
   ```

4. **Missing Cleanup**
   ```typescript
   useEffect(() => {
     // Some subscription or timer
     // Missing return function for cleanup
   }, [deps]);
   ```

5. **Old API Response Types**
   ```typescript
   // Check for old response structures
   interface GenieSpace {
     is_default: boolean;  // Should be removed
   }
   ```

---

## Priority Matrix

### Critical (Fix Immediately)
1. ✅ Import mismatches causing runtime errors
2. Database migration status and data integrity
3. Settings cache invalidation bugs
4. Profile switching Genie conversation issues

### High Priority (Fix in This Branch)
1. Remove legacy `settings.py` or document coexistence
2. Delete unused validator files
3. Clean up YAML configuration files
4. Update all tests to use new patterns
5. Fix documentation drift in README

### Medium Priority (Separate PR/Issue)
1. Consolidate duplicate documentation
2. Archive completed implementation docs
3. Improve error handling consistency
4. Add missing test coverage
5. Type hint improvements

### Low Priority (Technical Debt Backlog)
1. Build artifact cleanup
2. Dependency audit and updates
3. Code style consistency improvements
4. Refactor high-churn files
5. Performance optimization

---

## Review Execution Plan

### Step 1: Quick Wins (1-2 hours)
1. Run test suite and document failures
2. Search for deleted component imports
3. Verify database migration status
4. Check for obvious import errors
5. Compile a list of files referencing `settings.py`

### Step 2: Configuration Cleanup (2-3 hours)
1. Audit all `src/config/` files
2. Decide fate of YAML files
3. Document settings system architecture
4. Update or remove `config/loader.py`
5. Clean up build artifacts

### Step 3: Service Layer Audit (3-4 hours)
1. Review `agent.py` for legacy patterns
2. Audit all config services
3. Check validator file usage
4. Review chat service for race conditions
5. Verify Genie tool implementation

### Step 4: API and Database (2-3 hours)
1. Review all API routes
2. Check for deleted endpoint registrations
3. Verify database models match schema
4. Test migration up/down paths
5. Check foreign key constraints

### Step 5: Frontend Review (3-4 hours)
1. Verify deleted components not imported
2. Review state management pattern
3. Update API client types
4. Check for unused code
5. Test profile switching flow

### Step 6: Testing (2-3 hours)
1. Update test imports
2. Remove deleted feature tests
3. Add missing test coverage
4. Run full suite and fix failures
5. Document any skipped tests

### Step 7: Documentation (2-3 hours)
1. Update README
2. Archive completed phase docs
3. Update technical docs
4. Remove validation feature docs
5. Add deprecation notices if needed

### Step 8: Final Cleanup (1-2 hours)
1. Remove commented code
2. Fix type hints
3. Run linters and formatters
4. Update `.gitignore`
5. Create summary document

**Total Estimated Time: 16-24 hours**

---

## Success Criteria

Before merging this branch, verify:

- [ ] ✅ All tests pass
- [ ] ✅ No imports of deleted files
- [ ] ✅ Settings system clearly documented
- [ ] ✅ No YAML files loaded unless explicitly needed
- [ ] ✅ Database migrations applied and tested
- [ ] ✅ Profile switching works correctly with Genie
- [ ] ✅ No duplicate validator files
- [ ] ✅ Frontend compiles without errors
- [ ] ✅ API endpoints match documentation
- [ ] ✅ README reflects current architecture
- [ ] ✅ Technical docs updated
- [ ] ✅ No commented-out code blocks
- [ ] ✅ Linters pass (ruff, mypy, eslint, prettier)
- [ ] ✅ Build artifacts not in git
- [ ] ✅ `.gitignore` updated

---

## Post-Review Actions

### Immediate (Before Merge)
1. Fix all critical and high-priority issues
2. Update documentation
3. Ensure test suite passes
4. Get code review from team member

### Follow-Up (After Merge)
1. Create issues for medium-priority items
2. Plan refactoring of high-churn files
3. Schedule dependency audit
4. Consider performance profiling
5. Plan for monitoring and observability

### Technical Debt Register
Document identified but not fixed:
1. Legacy YAML configuration system
2. Dual settings implementations
3. High-churn files needing refactor
4. Missing test coverage areas
5. Documentation consolidation needs

---

## Context for New Reviewer

### What This Branch Does
- Migrates from YAML-based config to database-backed profiles
- Each profile contains: LLM config, Genie space, MLflow settings, prompts
- Users can switch profiles via UI (hot-reload)
- Profile switching reloads agent with new settings
- Genie conversations reset when profile switches

### What Changed Recently (Last 7 Commits)
1. Refactored Genie from multiple-with-default to one-per-profile
2. Removed "is_default" concept entirely
3. Added unique constraint on profile_id in genie_spaces table
4. Created ProfileContext for frontend state management (then deleted?)
5. Fixed profile switching to reset chat state
6. Fixed import bug: tools.py using wrong settings
7. Added comprehensive logging for debugging

### Known Working Features
- Profile creation, editing, deletion
- Profile switching with agent reload
- Genie space configuration per profile
- Database migrations
- Frontend profile management UI
- Chat state reset on profile switch

### Known Issues
- Settings system has two implementations
- YAML files status unclear
- Some tests still use old patterns
- Documentation drift
- Possible deleted components still referenced

### Key Files Modified Most
1. `src/services/agent.py` - Core agent logic
2. `src/api/services/chat_service.py` - Profile reloading
3. `src/config/settings_db.py` - Database settings
4. `frontend/src/components/Layout/AppLayout.tsx` - UI orchestration
5. `src/services/tools.py` - Genie tool integration

---

## Commands for Review

### Check Database State
```bash
# Check current migration
alembic current

# View migration history
alembic history --verbose

# Check database schema
sqlite3 ai_slide_generator.db ".schema config_genie_spaces"
```

### Check Code Quality
```bash
# Run linters
ruff check src/
mypy src/

# Frontend
cd frontend
npm run lint
npm run type-check
```

### Check Tests
```bash
# Run all tests
pytest -v

# Run with coverage
pytest --cov=src --cov-report=html

# Check for old settings imports
grep -r "from src.config.settings import" tests/
```

### Check Imports
```bash
# Find old settings imports
grep -r "from src.config.settings import" src/

# Find deleted component imports
grep -r "GenieSpacesManager\|ValidationButton\|config_validator" frontend/src/ src/

# Find YAML loading
grep -r "yaml.safe_load\|yaml.load" src/
```

### Check for Dead Code
```bash
# Find commented function definitions
grep -r "# def \|#def " src/

# Find TODO comments
grep -r "# TODO\|// TODO" src/ frontend/src/

# Find debug print statements
grep -r "console.log\|print(" src/ frontend/src/
```

---

## Appendix: Branch Commit Summary

### Nov 5-7: Initial Setup
- Fresh start, Databricks client, MLflow, Genie tool

### Nov 11-14: Agent Architecture
- Multi-turn conversations, slide parser, chat UI

### Nov 19: Database Migration
- Implemented Phases 1-6 of database-backed config
- Profile management UI complete
- Settings migrated to database

### Nov 20 AM: Genie Refactoring (commits 2-4)
- Removed Genie "is_default" concept
- Enforced one Genie space per profile
- Added validation and UX improvements

### Nov 20 PM: Bug Fixes (commits 5-7)
- Fixed profile reload bugs
- Fixed profile switching Genie conversation issues
- Fixed settings import bugs
- Added comprehensive logging

**Total:** 70+ commits over 4 weeks

---

## End of Document

**Next Steps:**
1. Use this document as a checklist during code review
2. Create GitHub issues for identified problems
3. Prioritize fixes before merge
4. Update this document with findings
5. Archive when complete

**Maintainer Notes:**
- Keep this document updated during review
- Add new sections if patterns emerge
- Link to created issues
- Document decisions made
- Preserve as reference for future refactors

