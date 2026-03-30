# Opus 4.6 Upgrade & Legacy LLM Config Removal — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Upgrade the slide generation LLM to Opus 4.6 and remove all legacy per-profile LLM configuration code, making `DEFAULT_CONFIG` the single source of truth.

**Architecture:** The LLM is managed infrastructure — not user-configurable. `DEFAULT_CONFIG["llm"]` in `src/core/defaults.py` is the single source of truth. All code that previously read LLM settings from the database (`ConfigAIInfra`, `LLMSettings`, `self.settings.llm`) is replaced with direct reads from `DEFAULT_CONFIG`. The `config_ai_infra` table is dropped idempotently.

**Tech Stack:** Python/FastAPI backend, React/TypeScript frontend, SQLAlchemy ORM, PostgreSQL/Lakebase, MLflow tracing

**Spec:** `docs/superpowers/specs/2026-03-30-opus-upgrade-design.md`

---

## Task ordering rationale

Tasks are ordered to keep the codebase buildable and testable at every commit. We start with the source-of-truth change (defaults), then work outward: core settings → agent → services → schemas → frontend → scripts → docs → tests. Each task is independently committable.

**IMPORTANT — Atomic group:** Tasks 3–7 form an atomic group. Task 3 removes `LLMSettings` and `AppSettings.llm`, which breaks `agent.py`, `chat_service.py`, and `config_validator.py` until Tasks 4, 5, and 7 fix them. Do NOT run tests between Tasks 3 and 7 — apply all five as a batch before verifying.

---

### Task 1: Update DEFAULT_CONFIG — new endpoint + missing keys

**Files:**
- Modify: `src/core/defaults.py:29-34`

- [ ] **Step 1: Update DEFAULT_CONFIG**

Change the `"llm"` dict in `DEFAULT_CONFIG` to:

```python
"llm": {
    "endpoint": "databricks-claude-opus-4-6",
    "temperature": 0.7,
    "max_tokens": 60000,
    "top_p": 0.95,
    "timeout": 600,
},
```

This adds `top_p` and `timeout` (previously only in `LLMSettings` defaults) and changes the endpoint from `databricks-claude-sonnet-4-5` to `databricks-claude-opus-4-6`.

- [ ] **Step 2: Verify no import errors**

Run: `python -c "from src.core.defaults import DEFAULT_CONFIG; print(DEFAULT_CONFIG['llm'])"`
Expected: Dict with all 5 keys and new endpoint.

- [ ] **Step 3: Commit**

```bash
git add src/core/defaults.py
git commit -m "feat: upgrade LLM default to Opus 4.6 and add top_p/timeout to DEFAULT_CONFIG"
```

---

### Task 2: Delete ConfigAIInfra model and ORM relationship

**Files:**
- Delete: `src/database/models/ai_infra.py`
- Modify: `src/database/models/__init__.py:3,35`
- Modify: `src/database/models/profile.py:31`

- [ ] **Step 1: Delete `src/database/models/ai_infra.py`**

Remove the file entirely.

- [ ] **Step 2: Remove from `__init__.py`**

In `src/database/models/__init__.py`:
- Remove line 3: `from src.database.models.ai_infra import ConfigAIInfra`
- Remove `"ConfigAIInfra",` from the `__all__` list

- [ ] **Step 3: Remove ORM relationship from profile model**

In `src/database/models/profile.py`, remove line 31:
```python
    ai_infra = relationship("ConfigAIInfra", back_populates="profile", uselist=False, cascade="all, delete-orphan")
```

- [ ] **Step 4: Verify import**

Run: `python -c "from src.database.models import ConfigProfile; print('OK')"`
Expected: `OK` (no import error about ConfigAIInfra)

- [ ] **Step 5: Commit**

```bash
git add -u src/database/models/
git commit -m "refactor: remove ConfigAIInfra model and ORM relationship"
```

---

### Task 3: Remove LLMSettings from settings_db.py

**Files:**
- Modify: `src/core/settings_db.py`

- [ ] **Step 1: Remove LLMSettings class and AppSettings.llm field**

In `src/core/settings_db.py`:
- Remove the `LLMSettings` class (lines 32-55)
- Remove `ConfigAIInfra` from the imports at line 19
- Remove `llm: LLMSettings` field from `AppSettings` (line 135)

- [ ] **Step 2: Remove LLM loading from `load_settings_from_database()`**

In the main loading path (~lines 226-279):
- Remove the `ai_infra` DB query: `ai_infra = db.query(ConfigAIInfra).filter_by(profile_id=profile.id).first()`
- Remove the check: `if not ai_infra: raise ValueError(...)`
- Remove the `LLMSettings` construction (`llm_settings = LLMSettings(...)`)
- Remove `llm=llm_settings` from the `AppSettings(...)` constructor call

In the no-default-profile fallback (~lines 197-213):
- Remove the `LLMSettings` construction and `llm=LLMSettings(...)` from the fallback `AppSettings`

- [ ] **Step 3: Remove LLM from reload logging**

In `reload_settings()` (~line 382), remove `"llm_endpoint": settings.llm.endpoint` from the logging extra dict.

Also in `load_settings_from_database()` (~line 310), remove `"llm_endpoint": ai_infra.llm_endpoint` from the logging extra dict.

- [ ] **Step 4: Verify import**

Run: `python -c "from src.core.settings_db import AppSettings; print('OK')"`
Expected: `OK`

- [ ] **Step 5: Commit**

```bash
git add src/core/settings_db.py
git commit -m "refactor: remove LLMSettings and ConfigAIInfra from settings_db"
```

---

### Task 4: Fix agent.py — remove all self.settings.llm references

**Files:**
- Modify: `src/services/agent.py`

- [ ] **Step 1: Fix fallback AppSettings construction (lines 120-140)**

Replace the fallback block that imports `LLMSettings` and constructs a fallback `AppSettings`. The agent no longer needs `self.settings.llm`. Change lines ~120-142 to:

```python
        if pre_built_prompts is not None:
            try:
                self.settings = get_settings()
            except Exception:
                # Factory path: settings only needed for non-LLM fields (profile info, genie)
                # LLM config comes from DEFAULT_CONFIG directly
                from src.core.settings_db import AppSettings
                self.settings = AppSettings(
                    profile_id=0,
                    profile_name="default",
                    genie=None,
                    prompts={},
                )
        else:
            self.settings = get_settings()
```

- [ ] **Step 2: Fix `_create_model()` (lines 325-355)**

Add `from src.core.defaults import DEFAULT_CONFIG` at the top of the method (or at module level). Replace `self.settings.llm.*` references:

```python
    def _create_model(self) -> ChatDatabricks:
        """Create LangChain Databricks model with user context."""
        try:
            from src.core.defaults import DEFAULT_CONFIG
            user_client = get_user_client()
            llm_config = DEFAULT_CONFIG["llm"]

            model = ChatDatabricks(
                endpoint=llm_config["endpoint"],
                temperature=llm_config["temperature"],
                max_tokens=llm_config["max_tokens"],
                top_p=llm_config["top_p"],
                workspace_client=user_client,
            )

            logger.info(
                "ChatDatabricks model created with user context",
                extra={
                    "endpoint": llm_config["endpoint"],
                    "temperature": llm_config["temperature"],
                    "max_tokens": llm_config["max_tokens"],
                },
            )

            return model
        except Exception as e:
            raise AgentError(f"Failed to create ChatDatabricks model: {e}") from e
```

- [ ] **Step 3: Fix executor timeouts (lines 598 and ~1645)**

Replace `max_execution_time=self.settings.llm.timeout` with:

```python
            from src.core.defaults import DEFAULT_CONFIG
            ...
            max_execution_time=DEFAULT_CONFIG["llm"]["timeout"],
```

Do this in both `_create_agent_executor()` (~line 598) and `_create_agent_executor_streaming()` (~line 1645).

- [ ] **Step 4: Fix MLflow spans (lines ~1257 and ~1481)**

Replace `self.settings.llm.endpoint` with `DEFAULT_CONFIG["llm"]["endpoint"]` in both span attributes. Add the import if not already present in scope.

```python
                span.set_attribute("model_endpoint", DEFAULT_CONFIG["llm"]["endpoint"])
```

- [ ] **Step 5: Verify no remaining self.settings.llm references**

Run: `grep -n "self.settings.llm" src/services/agent.py`
Expected: No matches

- [ ] **Step 6: Commit**

```bash
git add src/services/agent.py
git commit -m "refactor: agent.py uses DEFAULT_CONFIG for all LLM settings"
```

---

### Task 5: Fix chat_service.py title generation

**Files:**
- Modify: `src/api/services/chat_service.py:~984`

- [ ] **Step 1: Fix `run_title_gen()`**

In `run_title_gen()`, replace `settings.llm.endpoint` with `DEFAULT_CONFIG["llm"]["endpoint"]`. Add the import:

```python
                from src.core.defaults import DEFAULT_CONFIG
                ...
                naming_model = ChatDatabricks(
                    endpoint=DEFAULT_CONFIG["llm"]["endpoint"],
                    max_tokens=50,
                    temperature=0.3,
                    workspace_client=get_user_client(),
                )
```

- [ ] **Step 2: Verify no remaining settings.llm references**

Run: `grep -n "settings.llm" src/api/services/chat_service.py`
Expected: No matches

- [ ] **Step 3: Commit**

```bash
git add src/api/services/chat_service.py
git commit -m "refactor: chat_service title gen uses DEFAULT_CONFIG for LLM endpoint"
```

---

### Task 6: Update LLM Judge default

**Files:**
- Modify: `src/services/evaluation/llm_judge.py:105`

- [ ] **Step 1: Update default parameter**

Change the function signature default from hardcoded string to `DEFAULT_CONFIG`:

```python
from src.core.defaults import DEFAULT_CONFIG

async def evaluate_with_judge(
    genie_data: str,
    slide_content: str,
    model: str = DEFAULT_CONFIG["llm"]["endpoint"],
    trace_id: Optional[str] = None,
    experiment_id: Optional[str] = None,
) -> LLMJudgeResult:
```

Note: Using `DEFAULT_CONFIG` as a default arg value is safe because it's a module-level dict evaluated at import time.

- [ ] **Step 2: Commit**

```bash
git add src/services/evaluation/llm_judge.py
git commit -m "refactor: LLM judge uses DEFAULT_CONFIG for model endpoint"
```

---

### Task 7: Simplify config validators

**Files:**
- Modify: `src/services/config_validator.py`
- Modify: `src/services/validator.py`

- [ ] **Step 1: Fix config_validator.py**

In `_validate_llm()`, replace `self.settings.llm.endpoint` (and temperature, top_p) with `DEFAULT_CONFIG` values:

```python
    def _validate_llm(self) -> None:
        """Test LLM endpoint with a simple message."""
        from src.core.defaults import DEFAULT_CONFIG
        logger.info("Validating LLM endpoint")
        llm_config = DEFAULT_CONFIG["llm"]

        try:
            model = ChatDatabricks(
                endpoint=llm_config["endpoint"],
                temperature=llm_config["temperature"],
                max_tokens=100,  # Small for test
                top_p=llm_config["top_p"],
            )
            ...
```

Update the error/success messages to use `llm_config["endpoint"]` instead of `self.settings.llm.endpoint`.

Remove the `validate_llm_endpoint()` method entirely (lines 223-273).

- [ ] **Step 2: Remove `validate_ai_infra()` from validator.py**

In `src/services/validator.py`, remove only the `validate_ai_infra()` method. The class also has `validate_genie_space()` and `validate_prompts()` — keep those.

- [ ] **Step 3: Commit**

```bash
git add src/services/config_validator.py src/services/validator.py
git commit -m "refactor: config validators use DEFAULT_CONFIG, remove legacy AI infra validation"
```

---

### Task 8: Clean up profile service

**Files:**
- Modify: `src/services/profile_service.py`

- [ ] **Step 1: Remove ConfigAIInfra import**

Remove `ConfigAIInfra` from the imports at line 10.

- [ ] **Step 2: Remove joinedload references**

Remove `joinedload(ConfigProfile.ai_infra)` from profile queries at ~lines 76, 103, 120.

- [ ] **Step 3: Remove AI infra creation from `create_profile()` (~line 200)**

Remove the block that creates `ConfigAIInfra` record (~lines 203-209).

- [ ] **Step 4: Remove AI infra from `create_profile_with_config()` (~line 347)**

Remove the `ai_infra` parameter from the function signature. **Caller safety:** This is a positional parameter — removing it shifts `prompts` and `user` positions. Check all callers (grep for `create_profile_with_config`) and ensure they use keyword arguments, or update them. Also remove the block that creates `ConfigAIInfra` (~lines 413-420).

- [ ] **Step 5: Remove AI infra from `duplicate_profile()` (~lines 503-510)**

Remove the block that copies `ConfigAIInfra` from the source profile.

- [ ] **Step 6: Verify no remaining ConfigAIInfra references**

Run: `grep -n "ConfigAIInfra\|ai_infra" src/services/profile_service.py`
Expected: No matches (or only in unrelated comments)

- [ ] **Step 7: Commit**

```bash
git add src/services/profile_service.py
git commit -m "refactor: remove AI infra from profile service CRUD operations"
```

---

### Task 9: Clean up config service

**Files:**
- Modify: `src/services/config_service.py`

- [ ] **Step 1: Remove AI infra methods and imports**

Remove `ConfigAIInfra` from imports (line 8). Remove these methods entirely:
- `get_ai_infra_config()` (lines 21-26)
- `update_ai_infra_config()` (lines 28-56)
- `get_available_endpoints()` (lines 58-76)
- The `# AI Infrastructure` comment (line 19)

Keep the `# Prompts` section and all prompt-related methods intact.

- [ ] **Step 2: Verify**

Run: `python -c "from src.services.config_service import ConfigService; print('OK')"`
Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add src/services/config_service.py
git commit -m "refactor: remove AI infra methods from config service"
```

---

### Task 10: Clean up API schemas

**Files:**
- Modify: `src/api/schemas/settings/requests.py`
- Modify: `src/api/schemas/settings/responses.py`
- Modify: `src/api/schemas/settings/__init__.py`

- [ ] **Step 1: Clean up requests.py**

Remove `AIInfraCreateInline` class (lines 30-35).
Remove `AIInfraConfigUpdate` class (lines 102-107).
Remove `ai_infra` field from `ProfileCreateWithConfig` (line 61).

- [ ] **Step 2: Clean up responses.py**

Remove `AIInfraConfig` class (lines 26-37).
Remove `EndpointsList` class (lines 94-97).
Change `ProfileDetail.ai_infra: AIInfraConfig` (line 87) — remove this field entirely.

- [ ] **Step 3: Clean up __init__.py**

Remove these imports and `__all__` entries:
- `AIInfraConfigUpdate` (from requests)
- `AIInfraConfig` (from responses)
- `EndpointsList` (from responses)

Also remove the now-deleted `AIInfraCreateInline` if it was exported (check — it may not be in `__all__`).

- [ ] **Step 4: Verify**

Run: `python -c "from src.api.schemas.settings import ProfileDetail, ProfileCreateWithConfig; print('OK')"`
Expected: `OK`

- [ ] **Step 5: Commit**

```bash
git add src/api/schemas/settings/
git commit -m "refactor: remove AI infra from API schemas"
```

---

### Task 11: Clean up frontend

**Files:**
- Modify: `frontend/src/api/config.ts`
- Modify: `frontend/src/components/Help/HelpPage.tsx`

- [ ] **Step 1: Remove dead code from config.ts**

Remove these interfaces:
- `AIInfraConfig` (~line 42)
- `AIInfraConfigUpdate` (~line 52)
- `EndpointsList` (find it near the interfaces)

Remove `llm_endpoint` from `ReloadResponse` (~line 209).

Remove these methods from the `configApi` object:
- `getAIInfraConfig`
- `updateAIInfraConfig`
- `getAvailableEndpoints`
- `validateLLM`

**Keep** `validateProfile`, `validateGenie`, `reloadConfiguration`.

- [ ] **Step 2: Update HelpPage.tsx**

At ~line 365, change text that says profiles configure "LLM settings, Genie space connections, and custom prompts" to "Genie space connections and custom prompts" (or equivalent that removes LLM reference).

At ~line 372, remove the `<li>` for "AI Infrastructure: LLM endpoint, temperature, and token limits".

- [ ] **Step 3: Verify frontend compiles**

Run: `cd frontend && npx tsc --noEmit`
Expected: No errors (or only pre-existing errors unrelated to this change)

- [ ] **Step 4: Commit**

```bash
git add frontend/src/api/config.ts frontend/src/components/Help/HelpPage.tsx
git commit -m "refactor: remove AI infra dead code from frontend"
```

---

### Task 12: Update config files and seed profiles

**Files:**
- Modify: `config/config.yaml:7`
- Modify: `config/seed_profiles.yaml`

- [ ] **Step 1: Update config.yaml**

Change line 7 endpoint and line 11 timeout:
```yaml
  endpoint: "databricks-claude-opus-4-6"  # Model serving endpoint name (documentation only — app reads from DEFAULT_CONFIG)
  ...
  timeout: 600  # seconds (matches DEFAULT_CONFIG)
```

- [ ] **Step 2: Remove ai_infra from seed_profiles.yaml**

Remove the entire `ai_infra:` block from each profile. For the first profile, remove lines 13-16:
```yaml
    ai_infra:
      llm_endpoint: "databricks-claude-sonnet-4-5"
      llm_temperature: 0.70
      llm_max_tokens: 60000
```

Do the same for the second profile (lines 37-40).

- [ ] **Step 3: Commit**

```bash
git add config/config.yaml config/seed_profiles.yaml
git commit -m "refactor: update config files for Opus 4.6, remove ai_infra from seeds"
```

---

### Task 13: DB migration — idempotent DROP TABLE + script cleanup

**Files:**
- Modify: `scripts/init_database.py`
- Modify: `scripts/run_e2e_local.sh`
- Modify: `src/core/init_default_profile.py`

- [ ] **Step 1: Update init_database.py**

Remove `ConfigAIInfra` from the import at line 32.

Add an idempotent table drop early in `initialize_database()`, right after `init_db()` / table creation but before seeding. Use raw SQL:

```python
    # Drop legacy config_ai_infra table (idempotent)
    from sqlalchemy import text
    from src.core.database import get_engine
    engine = get_engine()
    with engine.connect() as conn:
        conn.execute(text("DROP TABLE IF EXISTS config_ai_infra"))
        conn.commit()
    print("✓ Legacy config_ai_infra table dropped (if existed)")
```

In the profile creation loop (~lines 187-197), remove the block that creates `ConfigAIInfra` records. Also remove the `ai_config = seed.get('ai_infra', {})` and the `print(f"  ✓ AI settings: ...")` line.

- [ ] **Step 2: Update run_e2e_local.sh**

Find the `ConfigAIInfra` seeding (~lines 160-166) and remove it. This is inline Python in a shell script.

- [ ] **Step 3: Update init_default_profile.py**

Remove `ConfigAIInfra` from imports (line 21).

In `init_default_profile()`, remove lines 389-397 (the block creating `ConfigAIInfra`).

Also remove `"llm_endpoint": ai_infra.llm_endpoint` from the logging dict (~line 433) and `print(f"  LLM Endpoint: {ai_infra.llm_endpoint}")` (~line 441).

Update the docstring at line 344 to remove "config/config.yaml - LLM settings (optional)".

- [ ] **Step 4: Commit**

```bash
git add scripts/init_database.py scripts/run_e2e_local.sh src/core/init_default_profile.py
git commit -m "refactor: idempotent DROP TABLE config_ai_infra, remove AI infra seeding"
```

---

### Task 14: Fix feedback service docstring

**Files:**
- Modify: `src/api/services/feedback_service.py:50`

- [ ] **Step 1: Fix docstring**

Change line 50 from:
```python
    Priority: FEEDBACK_LLM_ENDPOINT env var > default (databricks-gpt-oss-20b).
```
to:
```python
    Priority: FEEDBACK_LLM_ENDPOINT env var > default (databricks-gemma-3-12b).
```

- [ ] **Step 2: Commit**

```bash
git add src/api/services/feedback_service.py
git commit -m "fix: correct feedback service docstring — actual default is gemma not gpt-oss"
```

---

### Task 15: Update documentation

**Files:**
- Modify: `quickstart/TROUBLESHOOTING.md`
- Modify: `scripts/README.md`
- Modify: `src/README.md`
- Modify: `quickstart/PREREQUISITES.md`

- [ ] **Step 1: Fix TROUBLESHOOTING.md**

At lines 429-431, remove or update the SQL example that JOINs `config_ai_infra ai` and references `ai.llm_endpoint`. Replace with a simpler query that doesn't reference the dropped table.

- [ ] **Step 2: Fix scripts/README.md**

At lines 37-38, remove the example YAML showing `ai_infra:` / `llm_endpoint:`.

- [ ] **Step 3: Fix src/README.md**

At line 53, remove `ai_infra.py # LLM endpoint settings` from the directory tree listing.

- [ ] **Step 4: Fix PREREQUISITES.md**

At lines 246 and 250, change `databricks-claude-sonnet-4-5` to `databricks-claude-opus-4-6`.

- [ ] **Step 5: Commit**

```bash
git add quickstart/TROUBLESHOOTING.md scripts/README.md src/README.md quickstart/PREREQUISITES.md
git commit -m "docs: update references for Opus 4.6, remove config_ai_infra from examples"
```

---

### Task 16: Fix tests — remove ConfigAIInfra and settings.llm mocks

This is the largest task. Work through each test file, removing `ConfigAIInfra` references and `settings.llm` mocks.

**Files:**
- Modify: `tests/unit/test_settings_db.py`
- Modify: `tests/unit/config/test_services.py`
- Modify: `tests/unit/config/test_models.py`
- Modify: `tests/unit/config/test_admin_routes.py`
- Modify: `tests/unit/config/test_global_credentials_model.py`
- Modify: `tests/unit/config/test_google_oauth.py`
- Modify: `tests/unit/test_google_slides_routes.py`
- Modify: `tests/unit/test_agent.py`
- Modify: `tests/unit/test_error_recovery.py`
- Modify: `tests/unit/test_session_naming.py`
- Modify: `tests/integration/test_api_routes.py`
- Modify: `.github/workflows/test.yml`

- [ ] **Step 1: Fix test_settings_db.py**

Remove tests for `LLMSettings`. Remove `ConfigAIInfra` from fixture creation. Remove assertions on `settings.llm.endpoint`. If tests create profiles, they no longer need to create `ConfigAIInfra` records.

- [ ] **Step 2: Fix test_services.py (config tests)**

Remove tests for `get_ai_infra_config`, `update_ai_infra_config`, `get_available_endpoints`. Remove `ConfigAIInfra` from fixtures.

- [ ] **Step 3: Fix test_models.py (config tests)**

Remove `ConfigAIInfra` model tests. Remove `ai_infra` from profile creation fixtures.

- [ ] **Step 4: Fix test_admin_routes.py, test_global_credentials_model.py, test_google_oauth.py**

These likely have `ConfigAIInfra` in profile creation fixtures. Remove the `ai_infra` records — profiles no longer need them.

- [ ] **Step 5: Fix test_google_slides_routes.py**

Same pattern — remove `ConfigAIInfra` from fixtures.

- [ ] **Step 6: Fix test_agent.py and test_error_recovery.py**

Remove `settings.llm` mocks. Since agent.py now reads from `DEFAULT_CONFIG`, tests that mock `settings.llm` should instead mock or patch `DEFAULT_CONFIG` if needed, or simply rely on the actual defaults.

For mock_settings fixtures, remove the `llm` attribute:
```python
# Before:
settings.llm.endpoint = "test-endpoint"
settings.llm.temperature = 0.7
# After: remove these lines — agent reads DEFAULT_CONFIG directly
```

- [ ] **Step 7: Fix test_session_naming.py**

At ~line 210, remove `llm=MagicMock(endpoint="test-endpoint")` from the mock_settings. The title generation now reads from `DEFAULT_CONFIG` directly, so patch `src.core.defaults.DEFAULT_CONFIG` if the test needs to control the endpoint.

- [ ] **Step 8: Fix test_api_routes.py (integration)**

Remove `ConfigAIInfra` from profile creation in integration test fixtures. Remove any `ai_infra`-related assertions.

- [ ] **Step 9: Fix .github/workflows/test.yml**

Find the inline Python test code that references `llm_endpoint` (~line 582). Remove the `ConfigAIInfra` import and record creation. Remove `llm_endpoint='databricks-claude-sonnet'` from inline test data.

- [ ] **Step 10: Run the full test suite**

Run: `python -m pytest tests/unit/ -x -q`
Expected: All tests pass (some tests may have been removed, count may decrease)

- [ ] **Step 11: Commit**

```bash
git add tests/ .github/workflows/test.yml
git commit -m "test: remove ConfigAIInfra and settings.llm mocks from all tests"
```

---

### Task 17: Final verification

- [ ] **Step 1: Grep for any remaining references to the old model or removed types**

```bash
grep -rn "databricks-claude-sonnet-4-5" --include="*.py" --include="*.ts" --include="*.tsx" --include="*.yaml" --include="*.yml" --include="*.md" --include="*.sh" .
```

Expected: Only hits in the explicitly excluded export converter files (`html_to_pptx.py`, `html_to_google_slides.py`) and the design spec itself.

```bash
grep -rn "ConfigAIInfra\|LLMSettings\|AIInfraConfig\|ai_infra" --include="*.py" --include="*.ts" --include="*.tsx" .
```

Expected: No hits in source code (may appear in spec/plan docs which is fine).

- [ ] **Step 2: Run full test suite one more time**

Run: `python -m pytest tests/unit/ -q`
Expected: All pass.

- [ ] **Step 3: Verify frontend compiles**

Run: `cd frontend && npx tsc --noEmit`
Expected: No new errors.

- [ ] **Step 4: Commit any stragglers, then done**

If any files were missed, fix and commit. Then this work is complete and ready for PR.
