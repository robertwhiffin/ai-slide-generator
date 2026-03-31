# Upgrade LLM to Opus 4.6 & Remove Legacy Per-Profile LLM Config

## Context

The slide generator was originally designed with per-profile LLM configuration. That requirement has been removed — the LLM is now managed infrastructure, not user-configurable. However, the legacy `ConfigAIInfra` table, related models, API schemas, service methods, and frontend types still exist as dead code.

Additionally, multiple code paths read the model endpoint from `self.settings.llm` (the DB profile) rather than from `DEFAULT_CONFIG`, which is what `agent_factory` actually uses. This creates a disconnect where MLflow could log the wrong model, and the agent's fallback `_create_model()` could use a stale endpoint. Other files hardcode the old endpoint string directly.

## Goals

1. Upgrade the default LLM endpoint from `databricks-claude-sonnet-4-5` to `databricks-claude-opus-4-6`
2. Remove all legacy per-profile LLM configuration code
3. Ensure all code paths (MLflow, agent model creation, title generation, LLM judge) use `DEFAULT_CONFIG` as the single source of truth for LLM settings
4. Make the "managed LLM" architectural intent explicit in the codebase

## Design

### 1. Update default endpoint

**File: `src/core/defaults.py`**
- Change `DEFAULT_CONFIG["llm"]["endpoint"]` from `databricks-claude-sonnet-4-5` to `databricks-claude-opus-4-6`

### 2. Remove `ConfigAIInfra` DB model and ORM relationship

**File: `src/database/models/ai_infra.py`** — Delete file
**File: `src/database/models/__init__.py`** — Remove `ConfigAIInfra` import/export
**File: `src/database/models/profile.py`** — Remove `ai_infra` relationship from `ConfigProfile` (line 31)

### 3. Fix all `self.settings.llm` references in agent.py

**File: `src/services/agent.py`**

The agent has its own `_create_model()` (line 325) which is a fallback when `pre_built_model` is not provided (line 582: `self._pre_built_model or self._create_model()`). This method and all other `self.settings.llm` references must use `DEFAULT_CONFIG`:

- **Fallback `AppSettings` construction (lines 127-140)**: Remove the `LLMSettings` import and fallback `AppSettings` construction. Once `LLMSettings` is deleted this code will break. Replace with a simpler pattern — the agent no longer needs `self.settings.llm` at all since all LLM config comes from `DEFAULT_CONFIG` directly.
- **`_create_model()` (line 325-355)**: Change to read endpoint, temperature, max_tokens, top_p from `DEFAULT_CONFIG["llm"]` instead of `self.settings.llm`
- **`_create_agent_executor()` (line 598)**: Change `self.settings.llm.timeout` to `DEFAULT_CONFIG["llm"]["timeout"]`
- **`_create_agent_executor_streaming()` (line ~1645)**: Same timeout fix
- **MLflow spans (lines ~1257, ~1481)**: Change `self.settings.llm.endpoint` to `DEFAULT_CONFIG["llm"]["endpoint"]`
- **Logging (lines ~347-349)**: Update to log from `DEFAULT_CONFIG`

### 4. Fix title generation in chat_service.py

**File: `src/api/services/chat_service.py`**
- Line ~984: `run_title_gen()` creates a `ChatDatabricks` with `settings.llm.endpoint` — change to use `DEFAULT_CONFIG["llm"]["endpoint"]`

### 5. Update LLM Judge default

**File: `src/services/evaluation/llm_judge.py`**
- Line ~105: Change default parameter `model: str = "databricks-claude-sonnet-4-5"` to `model: str = "databricks-claude-opus-4-6"` (or refactor to read from `DEFAULT_CONFIG["llm"]["endpoint"]`)

### 6. Remove `LLMSettings` from settings

**File: `src/core/settings_db.py`**
- Remove `LLMSettings` class
- Remove `llm: LLMSettings` field from `AppSettings`
- Remove LLM loading logic from `load_settings_from_database()` (the `ai_infra` DB query, `LLMSettings` construction)
- Remove LLM endpoint from reload logging
- Remove `ConfigAIInfra` import
- Update the no-default-profile fallback (line ~201) to not construct `LLMSettings`

### 7. Simplify config validators

**File: `src/services/config_validator.py`**
- `_validate_llm()`: Use `DEFAULT_CONFIG["llm"]["endpoint"]` directly instead of `self.settings.llm.endpoint`
- Remove `validate_llm_endpoint()` method (validates arbitrary endpoints — no longer needed)

**File: `src/services/validator.py`**
- Remove `validate_ai_infra()` method — entirely legacy dead code

### 8. Clean up profile service

**File: `src/services/profile_service.py`**
- Remove AI infra creation from profile create flow
- Remove AI infra updates from profile update flow
- Remove AI infra copying from `duplicate_profile()` (~lines 503-510)
- Remove `joinedload(ConfigProfile.ai_infra)` from profile queries (~lines 76, 103, 120)
- Remove `ConfigAIInfra` imports

### 9. Clean up config service

**File: `src/services/config_service.py`**
- Remove any AI infra config methods
- Remove `ConfigAIInfra` imports

### 10. Clean up API schemas

**File: `src/api/schemas/settings/requests.py`**
- Remove `AIInfraConfigUpdate`, `AIInfraCreateInline` schemas
- Remove `ai_infra` field from `ProfileCreateWithConfig` (line ~61)

**File: `src/api/schemas/settings/responses.py`**
- Remove `AIInfraConfig` response schema
- Remove `ai_infra` field from `ProfileDetail` (line ~87 — currently required, not Optional)

**File: `src/api/schemas/settings/__init__.py`**
- Remove re-exports of `AIInfraConfig`, `AIInfraConfigUpdate`, `AIInfraCreateInline`

### 11. Clean up frontend

**File: `frontend/src/api/config.ts`**
- Remove `AIInfraConfig` interface
- Remove `AIInfraConfigUpdate` interface
- Remove `EndpointsList` interface
- Remove `ReloadResponse.llm_endpoint` field (or remove `ReloadResponse` if unused)
- Remove `getAIInfraConfig()` method
- Remove `updateAIInfraConfig()` method
- Remove `getAvailableEndpoints()` method
- Remove `validateLLM()` method

**File: `frontend/src/components/HelpPage.tsx`**
- Line ~365: Remove or update text that says profiles configure "LLM settings" — profiles no longer configure LLM
- Line ~372: Remove the "AI Infrastructure: LLM endpoint, temperature, and token limits" list item

**Keep** `validateProfile()`, `validateGenie()`, and `reloadConfiguration()` — these serve purposes beyond LLM config (profile validation still checks Genie, reload is general-purpose).

### 12. Update config files

**File: `config/config.yaml`** — Update endpoint to `databricks-claude-opus-4-6`; the LLM section becomes documentation-only (app reads from `DEFAULT_CONFIG`)
**File: `config/seed_profiles.yaml`** — Remove `ai_infra` blocks from all profiles

### 13. DB migration (idempotent, no Alembic)

**File: `scripts/init_database.py`**
- Add idempotent `DROP TABLE IF EXISTS config_ai_infra` early in `initialize_database()`, before `init_db()`
- Remove `ConfigAIInfra` import and seeding logic from profile creation loop

**File: `scripts/run_e2e_local.sh`**
- Remove `ConfigAIInfra` seeding

**File: `src/core/init_default_profile.py`**
- Remove `ConfigAIInfra` import and AI infra record creation

**Lakebase path:** `src/core/lakebase.py` uses `Base.metadata.create_all()` — removing the model from SQLAlchemy means the table won't be created on new deployments. No changes needed.

### 14. Update defaults for removed settings

**File: `src/core/defaults.py`**
- Add `timeout: 600` to `DEFAULT_CONFIG["llm"]` (currently only exists as a default in `LLMSettings`, which is being removed)
- Add `top_p: 0.95` to `DEFAULT_CONFIG["llm"]` (currently only exists as a default in `LLMSettings` and hardcoded in `agent_factory`)

### 15. Update documentation

**File: `quickstart/TROUBLESHOOTING.md`** (lines 429-431)
- Remove SQL examples that JOIN `config_ai_infra` and reference `ai.llm_endpoint`

**File: `scripts/README.md`** (lines 37-38)
- Remove example YAML with `ai_infra:` / `llm_endpoint:`

**File: `src/README.md`** (line 53)
- Remove `ai_infra.py # LLM endpoint settings` from directory tree listing

**File: `quickstart/PREREQUISITES.md`** (lines 246, 250)
- Update `databricks-claude-sonnet-4-5` references to `databricks-claude-opus-4-6`

### 16. Fix feedback service docstring (opportunistic)

**File: `src/api/services/feedback_service.py`**
- Line ~50: Update docstring from `databricks-gpt-oss-20b` to `databricks-gemma-3-12b` to match the actual default on line 44

### 17. Update tests

- Remove `ConfigAIInfra` references from test fixtures and assertions
- Update mocks that reference `settings.llm.endpoint` to use `DEFAULT_CONFIG`
- Key test files:
  - `tests/unit/test_settings_db.py`
  - `tests/unit/config/test_services.py`
  - `tests/unit/config/test_models.py`
  - `tests/unit/config/test_admin_routes.py`
  - `tests/unit/config/test_global_credentials_model.py`
  - `tests/unit/config/test_google_oauth.py`
  - `tests/unit/test_google_slides_routes.py`
  - `tests/unit/test_agent.py`
  - `tests/unit/test_error_recovery.py`
  - `tests/unit/test_session_naming.py` (mocks `settings.llm`)
  - `tests/integration/test_api_routes.py`
  - `.github/workflows/test.yml` (inline test code references `llm_endpoint`)

## Explicitly excluded

- **`src/services/export/html_to_pptx.py`** (line 46: `DEFAULT_MODEL = "databricks-claude-sonnet-4-5"`) — export converter code is currently being revamped; do not touch
- **`src/services/export/html_to_google_slides.py`** (line 32: `DEFAULT_MODEL = "databricks-claude-sonnet-4-5"`) — same; export converter revamp in progress
- **`tests/unit/test_slide_editing_robustness.py`** — false positive from initial review; no `settings.llm` or `ConfigAIInfra` references

## What stays unchanged

- `agent_factory._create_model()` — already reads from `DEFAULT_CONFIG`, no change needed
- `config_validator._validate_genie()` — Genie is still per-profile, untouched
- All Genie, prompt, slide style, and deck prompt configuration — unrelated to this change
- Frontend `validateProfile()`, `validateGenie()`, `reloadConfiguration()` — still useful for non-LLM purposes
- Export converters (`html_to_pptx.py`, `html_to_google_slides.py`) — excluded, being revamped separately

## Risks

- **Existing deployments** with data in `config_ai_infra` table: the idempotent `DROP TABLE IF EXISTS` handles this safely
- **`AppSettings` consumers**: all code that accessed `settings.llm` must be migrated to `DEFAULT_CONFIG`. The main callers are `agent.py`, `chat_service.py`, `config_validator.py`, and `settings_db.py` reload logging — all addressed above
- **Test count**: many test files reference `ConfigAIInfra` or mock `settings.llm` — expect a moderate amount of test fixture cleanup
