# CI Workflow Enhancement Plan

**Date:** 2026-02-02
**Status:** Ready for Implementation
**Priority:** High

---

## 1. Current State

The existing `.github/workflows/test.yml` has these jobs:

| Job | Purpose | Tests Run |
|-----|---------|-----------|
| `unit-tests` | Fast unit tests | `tests/unit/*` |
| `integration-tests` | API tests with Postgres | `tests/integration/*` (excluding `live`) |
| `e2e-tests` | Playwright browser tests | `frontend/playwright` |
| `validation-tests` | Deck integrity | `test_deck_integrity.py`, `test_llm_edit_responses.py` |
| `persistence-tests` | Database persistence | `test_deck_persistence.py`, `test_chat_persistence.py` |
| `test-summary` | Final status gate | (none) |

---

## 2. New Test Suites to Integrate

| Suite | File | Type | Special Requirements |
|-------|------|------|---------------------|
| API Routes | `tests/integration/test_api_routes.py` | Integration | SQLite in-memory |
| Streaming | `tests/integration/test_streaming.py` | Integration | SSE parsing |
| Export | `tests/integration/test_export.py` | Integration | python-pptx |
| Error Recovery | `tests/unit/test_error_recovery.py` | Unit | Heavy mocking |

**Not yet implemented (future):**
| Suite | File | Type | Special Requirements |
|-------|------|------|---------------------|
| Concurrency | `tests/unit/test_concurrency.py` | Unit | Threading tests, may be flaky |
| Performance | `tests/unit/test_performance.py` | Unit | `@pytest.mark.slow`, memory profiling |
| Security | `tests/unit/test_security.py` | Unit | HTML sanitization |

---

## 3. Proposed Workflow Structure

### 3.1 Job Dependency Graph

```
unit-tests (fast)
    │
    ├──► integration-tests (API + Streaming + Export)
    │
    ├──► e2e-tests (Playwright)
    │
    ├──► validation-tests (deck integrity)
    │
    └──► persistence-tests (database)
            │
            └──► test-summary (gate)
```

### 3.2 Updated Jobs

#### A. Rename/Expand `unit-tests`
Keep as-is but will now include `test_error_recovery.py` automatically.

#### B. Rename `integration-tests` → `api-integration-tests`
More specific name, runs all integration tests together:
- `test_api_routes.py` (70 tests)
- `test_streaming.py` (27 tests)
- `test_export.py` (27 tests)
- `test_config_api.py` (existing)

#### C. Add `slow-tests` job (optional, future)
For performance tests when implemented:
```yaml
slow-tests:
  name: Performance Tests
  runs-on: ubuntu-latest
  if: github.event_name == 'push' && github.ref == 'refs/heads/main'
  steps:
    - run: pytest tests/unit/test_performance.py -v -m slow
```

#### D. Add `security-tests` job (future)
When security tests are implemented:
```yaml
security-tests:
  name: Security Tests
  runs-on: ubuntu-latest
  steps:
    - run: pytest tests/unit/test_security.py -v
```

---

## 4. Implementation Steps

### Step 1: Update unit-tests job
No changes needed - `tests/unit/*` already includes `test_error_recovery.py`.

### Step 2: Update integration-tests job
Rename and verify it runs all new integration tests.

**Before:**
```yaml
- name: Run integration tests
  run: |
    pytest tests/integration -v --tb=short \
      --junitxml=test-results/integration-results.xml \
      -m "not live"
```

**After:** (same command, but add descriptive comment)
```yaml
- name: Run integration tests
  run: |
    # Includes: test_api_routes.py, test_streaming.py, test_export.py, test_config_api.py
    pytest tests/integration -v --tb=short \
      --junitxml=test-results/integration-results.xml \
      -m "not live"
```

### Step 3: Add markers for test categories
Create/update `pytest.ini` or `pyproject.toml`:

```ini
[pytest]
markers =
    slow: marks tests as slow (deselect with '-m "not slow"')
    live: marks tests requiring live services
    security: marks security-related tests
    concurrency: marks concurrency tests (may be flaky)
```

### Step 4: Add concurrency tests job (when implemented)
```yaml
concurrency-tests:
  name: Concurrency Tests
  runs-on: ubuntu-latest
  needs: unit-tests
  steps:
    - uses: actions/checkout@v4
    - name: Set up Python
      uses: actions/setup-python@v5
      with:
        python-version: ${{ env.PYTHON_VERSION }}
        cache: 'pip'
    - name: Install dependencies
      run: |
        python -m pip install --upgrade pip
        pip install -e ".[dev]"
    - name: Run concurrency tests
      run: |
        # Run multiple times to check for flakiness
        pytest tests/unit/test_concurrency.py -v --tb=short -x
    - name: Upload results
      uses: actions/upload-artifact@v4
      if: always()
      with:
        name: concurrency-test-results
        path: test-results/
```

### Step 5: Add performance tests job (when implemented)
```yaml
performance-tests:
  name: Performance Tests
  runs-on: ubuntu-latest
  needs: unit-tests
  # Only run on main branch merges (not PRs) to avoid slowdown
  if: github.event_name == 'push' && github.ref == 'refs/heads/main'
  steps:
    - uses: actions/checkout@v4
    - name: Set up Python
      uses: actions/setup-python@v5
      with:
        python-version: ${{ env.PYTHON_VERSION }}
        cache: 'pip'
    - name: Install dependencies
      run: |
        python -m pip install --upgrade pip
        pip install -e ".[dev]"
    - name: Run performance tests
      run: |
        pytest tests/unit/test_performance.py -v --tb=short
      timeout-minutes: 15
    - name: Upload results
      uses: actions/upload-artifact@v4
      if: always()
      with:
        name: performance-test-results
        path: test-results/
```

### Step 6: Add security tests job (when implemented)
```yaml
security-tests:
  name: Security Tests
  runs-on: ubuntu-latest
  needs: unit-tests
  steps:
    - uses: actions/checkout@v4
    - name: Set up Python
      uses: actions/setup-python@v5
      with:
        python-version: ${{ env.PYTHON_VERSION }}
        cache: 'pip'
    - name: Install dependencies
      run: |
        python -m pip install --upgrade pip
        pip install -e ".[dev]"
    - name: Run security tests
      run: |
        pytest tests/unit/test_security.py -v --tb=short
    - name: Upload results
      uses: actions/upload-artifact@v4
      if: always()
      with:
        name: security-test-results
        path: test-results/
```

### Step 7: Update test-summary job
Add new jobs to the dependency list:

```yaml
test-summary:
  name: Test Summary
  runs-on: ubuntu-latest
  needs: [unit-tests, integration-tests, e2e-tests, validation-tests, persistence-tests]
  # Future: add concurrency-tests, security-tests when implemented
  if: always()
```

---

## 5. Recommended Final Workflow Structure

```yaml
name: Test Suite

on:
  push:
    branches: [main, develop]
  pull_request:
    branches: [main, develop]

env:
  PYTHON_VERSION: '3.11'
  NODE_VERSION: '20'

jobs:
  # ============================================
  # FAST TESTS - Run first for quick feedback
  # ============================================

  unit-tests:
    name: Unit Tests
    # Includes: test_error_recovery.py, test_deck_integrity.py, etc.
    # ~100 tests, runs in ~30 seconds
    ...

  # ============================================
  # INTEGRATION TESTS - API layer validation
  # ============================================

  api-integration-tests:
    name: API Integration Tests
    needs: unit-tests
    # Includes: test_api_routes.py, test_streaming.py, test_export.py
    # ~130 tests with mocked services
    ...

  # ============================================
  # E2E TESTS - Browser automation
  # ============================================

  e2e-tests:
    name: E2E Tests (Playwright)
    needs: unit-tests
    ...

  # ============================================
  # FOCUSED TESTS - Specific validation areas
  # ============================================

  validation-tests:
    name: Deck Integrity Validation
    ...

  persistence-tests:
    name: Deck Persistence Validation
    ...

  # ============================================
  # OPTIONAL TESTS - Slower or conditional
  # ============================================

  # concurrency-tests:  # Uncomment when implemented
  #   name: Concurrency Tests
  #   needs: unit-tests
  #   ...

  # performance-tests:  # Uncomment when implemented
  #   name: Performance Tests
  #   needs: unit-tests
  #   if: github.event_name == 'push' && github.ref == 'refs/heads/main'
  #   ...

  # security-tests:  # Uncomment when implemented
  #   name: Security Tests
  #   needs: unit-tests
  #   ...

  # ============================================
  # SUMMARY - Final gate
  # ============================================

  test-summary:
    name: Test Summary
    needs: [unit-tests, api-integration-tests, e2e-tests, validation-tests, persistence-tests]
    if: always()
    ...
```

---

## 6. Immediate Actions (Current Tests)

Since the new test files are already implemented, minimal workflow changes are needed:

1. **No changes required for unit-tests** - `test_error_recovery.py` is in `tests/unit/` and will run automatically

2. **No changes required for integration-tests** - `test_api_routes.py`, `test_streaming.py`, `test_export.py` are in `tests/integration/` and will run automatically

3. **Optional: Add explicit test file lists** - For clarity in CI logs, update job descriptions

---

## 7. Verification Checklist

After implementation:

- [ ] `unit-tests` job runs `test_error_recovery.py`
- [ ] `integration-tests` job runs `test_api_routes.py`, `test_streaming.py`, `test_export.py`
- [ ] All tests pass locally: `pytest tests/ -v`
- [ ] Workflow runs successfully on PR
- [ ] Test artifacts uploaded correctly
- [ ] `test-summary` job reports correct status

---

## 8. Future Considerations

### When implementing concurrency tests:
- Add `@pytest.mark.concurrency` marker
- Consider running multiple times to detect flakiness
- May need longer timeout

### When implementing performance tests:
- Add `@pytest.mark.slow` marker
- Only run on main branch (not PRs) to avoid slowdown
- Set timeout to 15 minutes

### When implementing security tests:
- No special requirements
- Should block PRs if failing (security is critical)

---

## 9. Cross-References

- [API Routes Tests](../technical/api-routes-tests.md)
- [Streaming Tests](../technical/streaming-tests.md)
- [Export Tests](../technical/export-tests.md)
- [Error Recovery Tests](../technical/error-recovery-tests.md)
- [Concurrency Tests Plan](./2026-02-01-concurrency-tests-plan.md)
- [Performance Tests Plan](./2026-02-01-performance-tests-plan.md)
- [Security Tests Plan](./2026-02-01-security-tests-plan.md)
