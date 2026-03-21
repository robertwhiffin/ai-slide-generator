# Profile Rebuild: Session-Bound Agent Configuration — Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the pre-defined profile system with session-bound agent configuration so users land directly on the generator and configure the agent on the fly.

**Architecture:** Agent config is a JSON blob stored per-session. Profiles become optional named snapshots. The agent is built per-request from the session's config, eliminating the singleton agent and hot-reload machinery. ChatService stays as a stateless orchestrator with a deck cache.

**Tech Stack:** FastAPI, SQLAlchemy, Pydantic v2, LangChain, React 19, TypeScript, React Router 7, Playwright

**Spec:** `docs/superpowers/specs/2026-03-18-profile-rebuild-design.md`

---

## File Structure

### New Files
| File | Responsibility |
|------|---------------|
| `src/api/schemas/agent_config.py` | Pydantic models for agent_config JSON (tools, validation) |
| `src/services/agent_factory.py` | Per-request agent construction from agent_config JSON |
| `src/api/routes/agent_config.py` | GET/PUT session agent config, PATCH tools |
| `src/api/routes/profiles.py` | Simplified profile routes (save-from-session, load, list, delete) |
| `src/api/routes/tools.py` | GET /api/tools/available |
| `tests/unit/test_agent_config_schema.py` | Agent config validation tests |
| `tests/unit/test_agent_factory.py` | Agent factory tests |
| `tests/unit/test_agent_config_routes.py` | Agent config API route tests |
| `tests/unit/test_profiles_routes.py` | Simplified profile route tests |
| `tests/unit/test_tools_routes.py` | Tool discovery route tests |
| `tests/unit/test_migration.py` | Migration script tests |
| `frontend/src/contexts/AgentConfigContext.tsx` | React context for agent config state |
| `frontend/src/components/AgentConfigBar/AgentConfigBar.tsx` | UI component for inline config |
| `frontend/src/components/AgentConfigBar/ToolPicker.tsx` | Tool selection popover |
| `frontend/src/types/agentConfig.ts` | TypeScript types for agent config |

### Modified Files
| File | Change |
|------|--------|
| `src/database/models/session.py` | Add `agent_config` JSON column to `UserSession` |
| `src/database/models/profile.py` | Add `agent_config` JSON column, keep existing columns |
| `src/database/models/__init__.py` | Remove `ConfigHistory` export |
| `src/core/database.py` | Add migration for new columns, drop `config_history` |
| `src/api/services/chat_service.py` | Remove `self.agent`, `_reload_lock`, `reload_agent()`, `_ensure_agent_session()`; build agent per-request |
| `src/api/routes/chat.py` | Accept optional `agent_config` in request; handle missing `session_id` |
| `src/api/routes/sessions.py` | Remove `profile_id` requirement from `CreateSessionRequest` |
| `src/api/schemas/requests.py` | Add `agent_config` field to `ChatRequest`; simplify `CreateSessionRequest` |
| `src/api/main.py` | Register new route modules, remove old settings routes |
| `src/services/agent.py` | Extract agent construction logic into `agent_factory.py` |
| `frontend/src/App.tsx` | Change `/` from help to pre-session generator |
| `frontend/src/services/api.ts` | Add agent config API calls, simplify session creation |
| `frontend/src/components/Layout/AppLayout.tsx` | Remove ProfileSelector, add AgentConfigBar, support pre-session mode |
| `frontend/src/components/Layout/page-header.tsx` | Remove `profileSelector` prop |
| `frontend/src/contexts/SessionContext.tsx` | Remove profile ID from session creation |

### Deleted Files
| File | Reason |
|------|--------|
| `src/database/models/history.py` | `config_history` table dropped |
| `src/api/routes/settings/profiles.py` | Replaced by `src/api/routes/profiles.py` |
| `src/api/routes/settings/ai_infra.py` | LLM not user-configurable |
| `src/api/routes/settings/genie.py` | Genie managed through agent-config tools |
| `src/api/routes/settings/prompts.py` | Prompts in agent_config JSON |
| `frontend/src/contexts/ProfileContext.tsx` | Replaced by `AgentConfigContext` |
| `frontend/src/components/config/ProfileCreationWizard.tsx` | No wizard needed |
| `frontend/src/components/config/ProfileSelector.tsx` | Replaced by AgentConfigBar |

---

## Chunk 1: Data Model & Schemas

### Task 1: Agent Config Pydantic Schema

**Files:**
- Create: `src/api/schemas/agent_config.py`
- Test: `tests/unit/test_agent_config_schema.py`

- [ ] **Step 1: Write failing tests for agent config schema**

```python
# tests/unit/test_agent_config_schema.py
import pytest
from pydantic import ValidationError


def test_empty_config_is_valid():
    """Null/empty config means defaults."""
    from src.api.schemas.agent_config import AgentConfig
    config = AgentConfig()
    assert config.tools == []
    assert config.slide_style_id is None
    assert config.deck_prompt_id is None
    assert config.system_prompt is None
    assert config.slide_editing_instructions is None


def test_genie_tool_requires_space_id_and_name():
    from src.api.schemas.agent_config import AgentConfig, GenieTool
    with pytest.raises(ValidationError):
        GenieTool(type="genie")  # missing space_id, space_name


def test_genie_tool_valid():
    from src.api.schemas.agent_config import GenieTool
    tool = GenieTool(type="genie", space_id="abc", space_name="Sales", description="Revenue data")
    assert tool.space_id == "abc"
    assert tool.type == "genie"


def test_mcp_tool_requires_server_uri_and_name():
    from src.api.schemas.agent_config import MCPTool
    with pytest.raises(ValidationError):
        MCPTool(type="mcp")  # missing server_uri, server_name


def test_mcp_tool_valid():
    from src.api.schemas.agent_config import MCPTool
    tool = MCPTool(type="mcp", server_uri="https://example.com", server_name="Search")
    assert tool.server_uri == "https://example.com"


def test_duplicate_genie_tools_rejected():
    from src.api.schemas.agent_config import AgentConfig, GenieTool
    tool = GenieTool(type="genie", space_id="abc", space_name="Sales")
    with pytest.raises(ValidationError, match="[Dd]uplicate"):
        AgentConfig(tools=[tool, tool])


def test_duplicate_mcp_tools_rejected():
    from src.api.schemas.agent_config import AgentConfig, MCPTool
    tool = MCPTool(type="mcp", server_uri="https://example.com", server_name="Search")
    with pytest.raises(ValidationError, match="[Dd]uplicate"):
        AgentConfig(tools=[tool, tool])


def test_mixed_tools_no_duplicates():
    from src.api.schemas.agent_config import AgentConfig, GenieTool, MCPTool
    g = GenieTool(type="genie", space_id="abc", space_name="Sales")
    m = MCPTool(type="mcp", server_uri="https://example.com", server_name="Search")
    config = AgentConfig(tools=[g, m])
    assert len(config.tools) == 2


def test_system_prompt_must_be_nonempty_if_set():
    from src.api.schemas.agent_config import AgentConfig
    with pytest.raises(ValidationError):
        AgentConfig(system_prompt="")


def test_slide_editing_instructions_must_be_nonempty_if_set():
    from src.api.schemas.agent_config import AgentConfig
    with pytest.raises(ValidationError):
        AgentConfig(slide_editing_instructions="")


def test_config_serializes_to_dict():
    from src.api.schemas.agent_config import AgentConfig, GenieTool
    tool = GenieTool(type="genie", space_id="abc", space_name="Sales")
    config = AgentConfig(tools=[tool], slide_style_id=3, deck_prompt_id=7)
    d = config.model_dump()
    assert d["tools"][0]["type"] == "genie"
    assert d["slide_style_id"] == 3


def test_config_from_dict():
    from src.api.schemas.agent_config import AgentConfig
    data = {
        "tools": [{"type": "genie", "space_id": "abc", "space_name": "Sales"}],
        "slide_style_id": 3,
    }
    config = AgentConfig.model_validate(data)
    assert config.tools[0].space_id == "abc"


def test_config_from_none_returns_defaults():
    from src.api.schemas.agent_config import AgentConfig, resolve_agent_config
    config = resolve_agent_config(None)
    assert config.tools == []
    assert config.slide_style_id is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/unit/test_agent_config_schema.py -v`
Expected: FAIL — `src.api.schemas.agent_config` does not exist

- [ ] **Step 3: Implement the schema**

```python
# src/api/schemas/agent_config.py
"""Pydantic models for agent_config JSON stored on sessions and profiles."""
from __future__ import annotations

from typing import Annotated, Literal, Optional, Union

from pydantic import BaseModel, Field, field_validator, model_validator


class GenieTool(BaseModel):
    """Native Genie space tool — registered directly as a LangChain tool."""
    type: Literal["genie"]
    space_id: str = Field(..., min_length=1)
    space_name: str = Field(..., min_length=1)
    description: Optional[str] = None


class MCPTool(BaseModel):
    """MCP server tool — tools discovered via MCP protocol."""
    type: Literal["mcp"]
    server_uri: str = Field(..., min_length=1)
    server_name: str = Field(..., min_length=1)
    config: dict = Field(default_factory=dict)


ToolEntry = Annotated[Union[GenieTool, MCPTool], Field(discriminator="type")]


class AgentConfig(BaseModel):
    """Agent configuration stored as JSON on sessions and profiles.

    When all fields are None/empty, the system uses backend defaults.
    """
    tools: list[ToolEntry] = Field(default_factory=list)
    slide_style_id: Optional[int] = None
    deck_prompt_id: Optional[int] = None
    system_prompt: Optional[str] = None
    slide_editing_instructions: Optional[str] = None

    @field_validator("system_prompt", "slide_editing_instructions")
    @classmethod
    def must_be_nonempty_if_set(cls, v: Optional[str]) -> Optional[str]:
        if v is not None and v.strip() == "":
            raise ValueError("Must be non-empty if provided")
        return v

    @model_validator(mode="after")
    def no_duplicate_tools(self) -> "AgentConfig":
        seen: set[str] = set()
        for tool in self.tools:
            if isinstance(tool, GenieTool):
                key = f"genie:{tool.space_id}"
            elif isinstance(tool, MCPTool):
                key = f"mcp:{tool.server_uri}"
            else:
                continue
            if key in seen:
                raise ValueError(f"Duplicate tool: {key}")
            seen.add(key)
        return self


def resolve_agent_config(raw: Optional[dict]) -> AgentConfig:
    """Parse agent_config JSON from DB, returning defaults if None."""
    if raw is None:
        return AgentConfig()
    return AgentConfig.model_validate(raw)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/unit/test_agent_config_schema.py -v`
Expected: All PASS

- [ ] **Step 5: Commit**

```bash
git add src/api/schemas/agent_config.py tests/unit/test_agent_config_schema.py
git commit -m "feat: add AgentConfig Pydantic schema with validation"
```

---

### Task 2: Add agent_config Column to Database Models

**Files:**
- Modify: `src/database/models/session.py:83-147`
- Modify: `src/database/models/profile.py:1-37`
- Modify: `src/core/database.py` (migration logic)

- [ ] **Step 1: Add agent_config column to UserSession**

In `src/database/models/session.py`, add after `google_slides_presentation_id` (around line 106):

```python
    agent_config = Column(JSON, nullable=True, default=None)
```

Import `JSON` from sqlalchemy if not already imported.

- [ ] **Step 2: Add agent_config column to ConfigProfile**

In `src/database/models/profile.py`, add after `updated_by`:

```python
    agent_config = Column(JSON, nullable=True, default=None)
```

- [ ] **Step 3: Add migration in database.py**

Locate the migration section in `src/core/database.py` (where other `ALTER TABLE ADD COLUMN` statements are). Add:

```python
# Migration: add agent_config JSON column to user_sessions
_add_column_if_not_exists(engine, "user_sessions", "agent_config", "JSON")

# Migration: add agent_config JSON column to config_profiles
_add_column_if_not_exists(engine, "config_profiles", "agent_config", "JSON")
```

Use the existing `_add_column_if_not_exists` helper pattern already in the file.

- [ ] **Step 4: Verify migration runs without error**

Run: `pytest tests/unit/ -k "database or migration" -v`
Expected: Existing tests pass; new columns don't break anything.

- [ ] **Step 5: Commit**

```bash
git add src/database/models/session.py src/database/models/profile.py src/core/database.py
git commit -m "feat: add agent_config JSON column to sessions and profiles"
```

---

### Task 3: Drop config_history Table

**Files:**
- Delete: `src/database/models/history.py`
- Modify: `src/database/models/__init__.py`
- Modify: `src/database/models/profile.py` (remove relationship)
- Modify: `src/core/database.py` (remove history writes)

- [ ] **Step 1: Find all references to ConfigHistory**

Run: `grep -rn "ConfigHistory\|config_history" src/ --include="*.py"`

This identifies every import, relationship, and write path that needs updating.

- [ ] **Step 2: Remove ConfigHistory from models/__init__.py**

In `src/database/models/__init__.py`, remove `ConfigHistory` from imports and `__all__`.

- [ ] **Step 3: Remove history relationship from ConfigProfile**

In `src/database/models/profile.py`, remove the `history` relationship line:
```python
    history = relationship("ConfigHistory", back_populates="profile", cascade="all, delete-orphan")
```

- [ ] **Step 4: Remove all config_history write paths**

Search results from Step 1 will show where `ConfigHistory` objects are created. Remove those create/add calls. These are typically in `src/services/profile_service.py` or `src/core/settings_db.py`.

- [ ] **Step 5: Delete src/database/models/history.py**

```bash
rm src/database/models/history.py
```

- [ ] **Step 6: Run tests to verify nothing breaks**

Run: `pytest tests/ -v --timeout=30 -x`
Expected: All pass (config_history was unused in the app).

- [ ] **Step 7: Commit**

```bash
git add -A
git commit -m "feat: drop config_history table and remove all write paths"
```

---

### Task 4: Data Migration Script

**Files:**
- Create: `src/core/migrate_profiles_to_agent_config.py`
- Test: `tests/unit/test_migration.py`

- [ ] **Step 1: Write failing tests for migration logic**

```python
# tests/unit/test_migration.py
import pytest


def test_profile_with_genie_space_migrates():
    from src.core.migrate_profiles_to_agent_config import build_agent_config_from_profile

    profile_data = {
        "prompts": {
            "selected_slide_style_id": 3,
            "selected_deck_prompt_id": 7,
            "system_prompt": None,  # default
            "slide_editing_instructions": None,  # default
        },
        "genie_spaces": [
            {"space_id": "abc", "space_name": "Sales", "description": "Revenue data"}
        ],
    }
    config = build_agent_config_from_profile(profile_data)
    assert len(config["tools"]) == 1
    assert config["tools"][0]["type"] == "genie"
    assert config["tools"][0]["space_id"] == "abc"
    assert config["slide_style_id"] == 3
    assert config["deck_prompt_id"] == 7


def test_profile_without_genie_space_migrates():
    from src.core.migrate_profiles_to_agent_config import build_agent_config_from_profile

    profile_data = {
        "prompts": {
            "selected_slide_style_id": None,
            "selected_deck_prompt_id": None,
            "system_prompt": None,
            "slide_editing_instructions": None,
        },
        "genie_spaces": [],
    }
    config = build_agent_config_from_profile(profile_data)
    assert config["tools"] == []
    assert config["slide_style_id"] is None


def test_custom_prompts_preserved():
    from src.core.migrate_profiles_to_agent_config import build_agent_config_from_profile

    profile_data = {
        "prompts": {
            "selected_slide_style_id": None,
            "selected_deck_prompt_id": None,
            "system_prompt": "Custom system prompt",
            "slide_editing_instructions": "Custom editing instructions",
        },
        "genie_spaces": [],
    }
    config = build_agent_config_from_profile(profile_data)
    assert config["system_prompt"] == "Custom system prompt"
    assert config["slide_editing_instructions"] == "Custom editing instructions"


def test_default_prompts_become_none():
    from src.core.defaults import DEFAULT_CONFIG
    from src.core.migrate_profiles_to_agent_config import build_agent_config_from_profile

    default_system = DEFAULT_CONFIG["prompts"]["system_prompt"]
    profile_data = {
        "prompts": {
            "selected_slide_style_id": None,
            "selected_deck_prompt_id": None,
            "system_prompt": default_system,
            "slide_editing_instructions": None,
        },
        "genie_spaces": [],
    }
    config = build_agent_config_from_profile(profile_data)
    assert config["system_prompt"] is None  # matches default, so null
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/unit/test_migration.py -v`
Expected: FAIL — module does not exist

- [ ] **Step 3: Implement migration logic**

```python
# src/core/migrate_profiles_to_agent_config.py
"""One-time migration: convert relational profile data to agent_config JSON.

Called during database startup migration. Populates agent_config on
config_profiles and backfills user_sessions from their profile_id.
"""
from __future__ import annotations

import logging
from typing import Any, Optional

from src.core.defaults import DEFAULT_CONFIG

logger = logging.getLogger(__name__)

# Extract default prompt values for comparison
_DEFAULT_SYSTEM_PROMPT = DEFAULT_CONFIG.get("prompts", {}).get("system_prompt")
_DEFAULT_EDITING_INSTRUCTIONS = DEFAULT_CONFIG.get("prompts", {}).get(
    "slide_editing_instructions"
)


def _differs_from_default(value: Optional[str], default: Optional[str]) -> bool:
    """Return True if value is set and differs from the default."""
    if value is None:
        return False
    if default is None:
        return True
    return value.strip() != default.strip()


def build_agent_config_from_profile(profile_data: dict[str, Any]) -> dict[str, Any]:
    """Build an agent_config dict from relational profile data.

    Args:
        profile_data: dict with keys "prompts" and "genie_spaces"

    Returns:
        agent_config dict ready for JSON storage
    """
    prompts = profile_data.get("prompts", {})
    genie_spaces = profile_data.get("genie_spaces", [])

    tools = []
    for gs in genie_spaces:
        tools.append(
            {
                "type": "genie",
                "space_id": gs["space_id"],
                "space_name": gs["space_name"],
                "description": gs.get("description"),
            }
        )

    system_prompt = prompts.get("system_prompt")
    editing_instructions = prompts.get("slide_editing_instructions")

    return {
        "tools": tools,
        "slide_style_id": prompts.get("selected_slide_style_id"),
        "deck_prompt_id": prompts.get("selected_deck_prompt_id"),
        "system_prompt": system_prompt
        if _differs_from_default(system_prompt, _DEFAULT_SYSTEM_PROMPT)
        else None,
        "slide_editing_instructions": editing_instructions
        if _differs_from_default(editing_instructions, _DEFAULT_EDITING_INSTRUCTIONS)
        else None,
    }


def migrate_profiles(session_factory) -> int:
    """Migrate all profiles to agent_config JSON. Returns count migrated."""
    from src.database.models.profile import ConfigProfile

    db = session_factory()
    try:
        profiles = db.query(ConfigProfile).filter(
            ConfigProfile.agent_config.is_(None)
        ).all()

        count = 0
        for profile in profiles:
            profile_data = {
                "prompts": {
                    "selected_slide_style_id": getattr(profile.prompts, "selected_slide_style_id", None) if profile.prompts else None,
                    "selected_deck_prompt_id": getattr(profile.prompts, "selected_deck_prompt_id", None) if profile.prompts else None,
                    "system_prompt": getattr(profile.prompts, "system_prompt", None) if profile.prompts else None,
                    "slide_editing_instructions": getattr(profile.prompts, "slide_editing_instructions", None) if profile.prompts else None,
                },
                "genie_spaces": [
                    {
                        "space_id": gs.space_id,
                        "space_name": gs.space_name,
                        "description": gs.description,
                    }
                    for gs in (profile.genie_spaces or [])
                ],
            }
            profile.agent_config = build_agent_config_from_profile(profile_data)
            count += 1
            logger.info(f"Migrated profile '{profile.name}' (id={profile.id}) to agent_config")

        db.commit()
        return count
    finally:
        db.close()


def backfill_sessions(session_factory) -> int:
    """Backfill agent_config on existing sessions from their profile_id. Returns count."""
    from src.database.models.profile import ConfigProfile
    from src.database.models.session import UserSession

    db = session_factory()
    try:
        sessions = (
            db.query(UserSession)
            .filter(
                UserSession.agent_config.is_(None),
                UserSession.profile_id.isnot(None),
            )
            .all()
        )

        count = 0
        for session in sessions:
            profile = db.query(ConfigProfile).filter(
                ConfigProfile.id == session.profile_id
            ).first()
            if profile and profile.agent_config:
                session.agent_config = profile.agent_config
                count += 1

        db.commit()
        logger.info(f"Backfilled agent_config on {count} sessions")
        return count
    finally:
        db.close()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/unit/test_migration.py -v`
Expected: All PASS

- [ ] **Step 5: Wire migration into database startup**

In `src/core/database.py`, after the column migrations, add:

```python
from src.core.migrate_profiles_to_agent_config import migrate_profiles, backfill_sessions

# Migrate profile data to agent_config JSON (idempotent — skips already-migrated)
profiles_migrated = migrate_profiles(SessionLocal)
if profiles_migrated:
    logger.info(f"Migrated {profiles_migrated} profiles to agent_config")

sessions_backfilled = backfill_sessions(SessionLocal)
if sessions_backfilled:
    logger.info(f"Backfilled {sessions_backfilled} sessions with agent_config")
```

- [ ] **Step 6: Commit**

```bash
git add src/core/migrate_profiles_to_agent_config.py tests/unit/test_migration.py src/core/database.py
git commit -m "feat: add migration script for profiles and sessions to agent_config"
```

---

## Chunk 2: Agent Factory & ChatService Refactor

### Task 5: Agent Factory — Per-Request Agent Construction

**Files:**
- Create: `src/services/agent_factory.py`
- Test: `tests/unit/test_agent_factory.py`

- [ ] **Step 1: Write failing tests for agent factory**

```python
# tests/unit/test_agent_factory.py
import pytest
from unittest.mock import MagicMock, patch


def test_build_agent_with_no_tools():
    """Default config produces agent with no Genie tool, just search_images."""
    from src.api.schemas.agent_config import AgentConfig
    from src.services.agent_factory import build_agent_for_request

    config = AgentConfig()
    session_data = {"session_id": "test-123", "genie_conversation_id": None}

    with patch("src.services.agent_factory._create_model") as mock_model, \
         patch("src.services.agent_factory._get_prompt_content") as mock_prompts:
        mock_model.return_value = MagicMock()
        mock_prompts.return_value = {
            "system_prompt": "default prompt",
            "slide_editing_instructions": "default editing",
            "deck_prompt": None,
            "slide_style": "default style",
            "image_guidelines": None,
        }
        agent = build_agent_for_request(config, session_data)

    assert agent is not None
    # Should have search_images but NOT query_genie_space
    tool_names = [t.name for t in agent.tools]
    assert "search_images" in tool_names
    assert "query_genie_space" not in tool_names


def test_build_agent_with_genie_tool():
    """Config with Genie tool produces agent with query_genie_space."""
    from src.api.schemas.agent_config import AgentConfig, GenieTool
    from src.services.agent_factory import build_agent_for_request

    config = AgentConfig(tools=[
        GenieTool(type="genie", space_id="abc", space_name="Sales")
    ])
    session_data = {"session_id": "test-123", "genie_conversation_id": "conv-456"}

    with patch("src.services.agent_factory._create_model") as mock_model, \
         patch("src.services.agent_factory._get_prompt_content") as mock_prompts:
        mock_model.return_value = MagicMock()
        mock_prompts.return_value = {
            "system_prompt": "default prompt",
            "slide_editing_instructions": "default editing",
            "deck_prompt": None,
            "slide_style": "default style",
            "image_guidelines": None,
        }
        agent = build_agent_for_request(config, session_data)

    tool_names = [t.name for t in agent.tools]
    assert "query_genie_space" in tool_names


def test_custom_prompts_override_defaults():
    """Custom system_prompt in config overrides the backend default."""
    from src.api.schemas.agent_config import AgentConfig
    from src.services.agent_factory import build_agent_for_request

    config = AgentConfig(system_prompt="You are a custom assistant")
    session_data = {"session_id": "test-123", "genie_conversation_id": None}

    with patch("src.services.agent_factory._create_model") as mock_model, \
         patch("src.services.agent_factory._get_prompt_content") as mock_prompts:
        mock_model.return_value = MagicMock()
        mock_prompts.return_value = {
            "system_prompt": "default prompt",
            "slide_editing_instructions": "default editing",
            "deck_prompt": None,
            "slide_style": "default style",
            "image_guidelines": None,
        }
        agent = build_agent_for_request(config, session_data)

    # The agent's system prompt should be the custom one
    assert agent.system_prompt == "You are a custom assistant"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/unit/test_agent_factory.py -v`
Expected: FAIL — module does not exist

- [ ] **Step 3: Implement agent_factory.py**

Extract agent construction logic from `src/services/agent.py` into a new module. The factory reads the `AgentConfig`, creates the LLM model, builds the appropriate tools, constructs the system prompt (with overrides if set), and returns a ready-to-invoke agent.

Key points:
- Copy `_create_model()` from `agent.py` (lines 267-297) — uses fixed default LLM endpoint from `defaults.py`
- Copy tool construction from `_create_tools_for_session()` (lines 299-400) — but drive it from `AgentConfig.tools` instead of global settings
- For Genie tools: use the existing `query_genie_space` wrapper pattern, injecting `genie_conversation_id` from `session_data`
- For MCP tools: stub with a `NotImplementedError` for now (MCP branch not yet merged)
- System prompt: use `config.system_prompt` if set, otherwise fall back to the default from `_get_prompt_content()`
- Return an object with `.tools`, `.system_prompt`, and the invoke/stream methods the chat service needs

```python
# src/services/agent_factory.py
"""Per-request agent construction from AgentConfig JSON."""
from __future__ import annotations

import logging
from typing import Any, Optional

from src.api.schemas.agent_config import AgentConfig, GenieTool, MCPTool

logger = logging.getLogger(__name__)


def _create_model():
    """Create the LLM model using fixed backend defaults."""
    from src.core.defaults import DEFAULT_CONFIG
    from src.core.databricks_client import get_databricks_client

    llm_config = DEFAULT_CONFIG["llm"]
    client = get_databricks_client()
    user_client = client.get_user_scoped_client()

    from langchain_databricks import ChatDatabricks

    return ChatDatabricks(
        endpoint=llm_config["endpoint"],
        temperature=llm_config["temperature"],
        max_tokens=llm_config["max_tokens"],
        workspace_client=user_client,
    )


def _get_prompt_content(config: AgentConfig) -> dict[str, Any]:
    """Resolve prompt content, applying overrides from agent_config."""
    from src.core.settings_db import fetch_prompt_content

    # Fetch defaults from DB (deck_prompt, slide_style based on IDs)
    # Pass None for profile_id since we're reading from libraries directly
    prompts = fetch_prompt_content(profile_id=None)

    # Apply overrides from agent_config
    if config.system_prompt is not None:
        prompts["system_prompt"] = config.system_prompt
    if config.slide_editing_instructions is not None:
        prompts["slide_editing_instructions"] = config.slide_editing_instructions

    # Resolve slide_style and deck_prompt from library tables by ID
    if config.slide_style_id is not None:
        from src.database.models import SlideStyleLibrary
        from src.core.database import SessionLocal
        db = SessionLocal()
        try:
            style = db.query(SlideStyleLibrary).filter(
                SlideStyleLibrary.id == config.slide_style_id,
                SlideStyleLibrary.is_active == True,
            ).first()
            if style:
                prompts["slide_style"] = style.style_content
                if style.image_guidelines:
                    prompts["image_guidelines"] = style.image_guidelines
        finally:
            db.close()

    if config.deck_prompt_id is not None:
        from src.database.models import SlideDeckPromptLibrary
        from src.core.database import SessionLocal
        db = SessionLocal()
        try:
            prompt = db.query(SlideDeckPromptLibrary).filter(
                SlideDeckPromptLibrary.id == config.deck_prompt_id,
                SlideDeckPromptLibrary.is_active == True,
            ).first()
            if prompt:
                prompts["deck_prompt"] = prompt.prompt_content
        finally:
            db.close()

    return prompts


def _build_tools(config: AgentConfig, session_data: dict[str, Any]) -> list:
    """Build LangChain tools from agent_config."""
    from langchain_core.tools import StructuredTool
    from src.services.tools import query_genie_space

    tools = []

    # Always add search_images
    from src.services.agent import _create_search_images_tool
    tools.append(_create_search_images_tool(session_data["session_id"]))

    # Add tools based on config
    for tool_entry in config.tools:
        if isinstance(tool_entry, GenieTool):
            genie_conv_id = session_data.get("genie_conversation_id")

            def genie_wrapper(query: str, _conv_id=genie_conv_id, _space_id=tool_entry.space_id) -> str:
                result = query_genie_space(
                    query=query,
                    conversation_id=_conv_id,
                )
                # Update conversation ID for future calls
                if result.get("conversation_id"):
                    session_data["genie_conversation_id"] = result["conversation_id"]
                return str(result)

            tools.append(
                StructuredTool.from_function(
                    func=genie_wrapper,
                    name="query_genie_space",
                    description=f"Query the Genie space '{tool_entry.space_name}' for data. {tool_entry.description or ''}",
                )
            )
        elif isinstance(tool_entry, MCPTool):
            logger.warning(f"MCP tool '{tool_entry.server_name}' not yet implemented, skipping")
            # MCP integration will be added when MCP branch merges

    return tools


def build_agent_for_request(
    config: AgentConfig,
    session_data: dict[str, Any],
) -> Any:
    """Build a complete agent for a single chat request.

    Args:
        config: Parsed AgentConfig from the session
        session_data: Dict with session_id, genie_conversation_id, etc.

    Returns:
        Agent object ready for invocation
    """
    model = _create_model()
    prompts = _get_prompt_content(config)
    tools = _build_tools(config, session_data)

    # Build the agent.
    # IMPORTANT: Read SlideGeneratorAgent.__init__ (src/services/agent.py:67-106)
    # and determine the correct construction approach. The agent currently calls
    # get_settings() and create_agent() in __init__. You need to either:
    #   (a) Add a classmethod/factory that accepts pre-built model/tools/prompts, OR
    #   (b) Refactor __init__ to accept these as optional params, falling back to
    #       get_settings() only when not provided.
    # Option (b) is simpler and backward-compatible during the transition.
    # The key contract: return an agent object that ChatService can call
    # .generate() / .stream() on for a single chat turn.
    from src.services.agent import SlideGeneratorAgent

    agent = SlideGeneratorAgent(
        model=model,
        tools=tools,
        system_prompt=prompts.get("system_prompt", ""),
        slide_editing_instructions=prompts.get("slide_editing_instructions", ""),
        deck_prompt=prompts.get("deck_prompt"),
        slide_style=prompts.get("slide_style"),
        image_guidelines=prompts.get("image_guidelines"),
    )

    return agent
```

**Prerequisite:** Modify `SlideGeneratorAgent.__init__` in `src/services/agent.py` to accept optional `model`, `tools`, `system_prompt`, `slide_editing_instructions`, `deck_prompt`, `slide_style`, `image_guidelines` parameters. When provided, use them directly instead of calling `get_settings()` / `_create_model()` / `_create_tools_for_session()`. When not provided, fall back to the current behavior (for backward compatibility during migration).

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/unit/test_agent_factory.py -v`
Expected: All PASS

- [ ] **Step 5: Commit**

```bash
git add src/services/agent_factory.py tests/unit/test_agent_factory.py
git commit -m "feat: add agent_factory for per-request agent construction"
```

---

### Task 6: Refactor ChatService — Remove Singleton Agent

**Files:**
- Modify: `src/api/services/chat_service.py`

This is the largest single change. ChatService loses `self.agent`, `_reload_lock`, `reload_agent()`, and `_ensure_agent_session()`. It gains a per-request pattern: load session → read `agent_config` → call `build_agent_for_request()` → invoke → discard.

- [ ] **Step 1: Remove agent from ChatService.__init__**

In `src/api/services/chat_service.py`, modify `__init__` (lines 69-86):

```python
def __init__(self):
    """Initialize the chat service."""
    logger.info("Initializing ChatService")

    # Thread lock for safe deck cache access
    self._cache_lock = threading.Lock()

    # In-memory cache of slide decks (keyed by session_id)
    self._deck_cache: Dict[str, SlideDeck] = {}

    logger.info("ChatService initialized successfully")
```

Remove: `self.agent = create_agent()`, `self._reload_lock`.

- [ ] **Step 2: Delete reload_agent method**

Delete the `reload_agent()` method (lines 111-187). It is no longer needed.

- [ ] **Step 3: Delete _ensure_agent_session method**

Delete `_ensure_agent_session()` (lines 1254-1374). Session state is now read from DB per-request.

- [ ] **Step 4: Add per-request agent construction in chat methods**

In the `send_message_streaming()` method (the primary one), replace the `self.agent` usage with:

```python
from src.api.schemas.agent_config import resolve_agent_config
from src.services.agent_factory import build_agent_for_request

# Load session and its agent_config
session = session_manager.get_session(session_id)
agent_config = resolve_agent_config(session.agent_config)

# Build session data for agent factory
session_data = {
    "session_id": session_id,
    "genie_conversation_id": session.genie_conversation_id,
    "experiment_id": session.experiment_id,
}

# Build agent for this request
agent = build_agent_for_request(agent_config, session_data)
```

Then use `agent` instead of `self.agent` for the rest of the method.

Apply the same pattern to `send_message()` (sync) and the async chat handler.

- [ ] **Step 5: Remove all self.agent references**

Search for `self.agent` in the file and replace with the per-request agent. Key locations:
- `self.agent.sessions[session_id]` → read from DB instead
- `self.agent.generate()` / `self.agent.stream()` → use the locally-built `agent`

- [ ] **Step 6: Persist genie_conversation_id after request**

After the agent finishes, check if `session_data["genie_conversation_id"]` was updated (the genie wrapper updates it). If so, persist:

```python
if session_data.get("genie_conversation_id") != session.genie_conversation_id:
    session_manager.set_genie_conversation_id(
        session_id, session_data["genie_conversation_id"]
    )
```

- [ ] **Step 7: Run existing tests**

Run: `pytest tests/ -v --timeout=60 -x`
Expected: Some tests may fail due to mocking `self.agent`. Fix mock targets to match new pattern.

- [ ] **Step 8: Commit**

```bash
git add src/api/services/chat_service.py
git commit -m "refactor: remove singleton agent from ChatService, build per-request"
```

---

### Task 7: Handle Session-Creation-on-First-Message in Chat Endpoints

**Files:**
- Modify: `src/api/schemas/requests.py`
- Modify: `src/api/routes/chat.py`

- [ ] **Step 1: Update ChatRequest schema**

In `src/api/schemas/requests.py`, modify `ChatRequest`:

```python
class ChatRequest(BaseModel):
    session_id: Optional[str] = None  # Changed from required to optional
    message: str
    slide_context: Optional[SlideContext] = None
    image_ids: Optional[list[int]] = None
    agent_config: Optional[dict] = None  # New: agent config for session creation
```

- [ ] **Step 2: Update /chat/stream endpoint**

In `src/api/routes/chat.py`, in the `send_message_streaming` handler (line 103+):

At the top of the handler, before acquiring the session lock:

```python
# If no session_id, create session on the fly
if not request.session_id:
    from src.api.schemas.agent_config import AgentConfig
    agent_config = AgentConfig.model_validate(request.agent_config) if request.agent_config else None
    session = session_manager.create_session(
        agent_config=agent_config.model_dump() if agent_config else None
    )
    request.session_id = session.session_id
    # Include new session_id in the first SSE event as a SESSION_CREATED event:
    # yield StreamEvent(type=StreamEventType.SESSION_CREATED, session_id=session.session_id)
    # Add SESSION_CREATED to the StreamEventType enum in src/api/schemas/streaming.py
    # Frontend parses this event to update the URL to /sessions/:id/edit
```

Ensure the new `session_id` is returned in the SSE stream (e.g., as a `SESSION_CREATED` event type or in the `COMPLETE` event metadata).

- [ ] **Step 3: Update /chat/async endpoint**

Same pattern as stream, but return the new `session_id` in the initial JSON response body.

- [ ] **Step 4: Update /chat sync endpoint**

Same pattern for consistency.

- [ ] **Step 5: Write test for session creation on first message**

```python
# tests/unit/test_chat_routes.py (add to existing or create)
def test_chat_stream_creates_session_when_missing(client):
    """POST /chat/stream with no session_id creates a new session."""
    with patch("src.api.routes.chat.get_session_manager") as mock_sm, \
         patch("src.api.routes.chat.get_chat_service") as mock_cs:
        mock_session = MagicMock()
        mock_session.session_id = "new-session-123"
        mock_session.agent_config = None
        mock_sm.return_value.create_session.return_value = mock_session
        mock_sm.return_value.get_session.return_value = mock_session
        mock_cs.return_value.send_message_streaming.return_value = iter([])

        response = client.post("/api/chat/stream", json={
            "message": "Create a sales report",
        })
        assert response.status_code == 200
        mock_sm.return_value.create_session.assert_called_once()


def test_chat_stream_with_agent_config_persists_config(client):
    """POST /chat/stream with agent_config persists it to the new session."""
    with patch("src.api.routes.chat.get_session_manager") as mock_sm, \
         patch("src.api.routes.chat.get_chat_service") as mock_cs:
        mock_session = MagicMock()
        mock_session.session_id = "new-session-123"
        mock_session.agent_config = None
        mock_sm.return_value.create_session.return_value = mock_session
        mock_sm.return_value.get_session.return_value = mock_session
        mock_cs.return_value.send_message_streaming.return_value = iter([])

        config = {"tools": [{"type": "genie", "space_id": "abc", "space_name": "Sales"}]}
        response = client.post("/api/chat/stream", json={
            "message": "Create a sales report",
            "agent_config": config,
        })
        assert response.status_code == 200
        # Verify agent_config was set on the created session
        created_session = mock_sm.return_value.create_session.return_value
        assert created_session.agent_config is not None or \
               mock_sm.return_value.update_session.called
```

- [ ] **Step 6: Run tests**

Run: `pytest tests/ -k chat -v`
Expected: All PASS

- [ ] **Step 7: Update sessions.py create endpoint**

In `src/api/routes/sessions.py`, modify `create_session` (line 46+) to no longer read or require `profile_id`. The `CreateSessionRequest` schema change (Step 1) removes it from the schema; ensure the route handler no longer passes it to `session_manager.create_session()`.

- [ ] **Step 8: Update SessionContext.tsx**

In `frontend/src/contexts/SessionContext.tsx`, modify `createNewSession()` to no longer pass `profile_id` when calling `api.createSession()`. Remove any `profile_id` / `profile_name` handling from session creation and restoration.

- [ ] **Step 9: Run tests**

Run: `pytest tests/ -k chat -v`
Expected: All PASS

- [ ] **Step 10: Commit**

```bash
git add src/api/schemas/requests.py src/api/routes/chat.py src/api/routes/sessions.py frontend/src/contexts/SessionContext.tsx tests/
git commit -m "feat: support session creation on first chat message"
```

---

## Chunk 3: New API Routes

### Task 8: Agent Config Routes (GET/PUT/PATCH)

**Files:**
- Create: `src/api/routes/agent_config.py`
- Test: `tests/unit/test_agent_config_routes.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/unit/test_agent_config_routes.py
import pytest
from unittest.mock import MagicMock, patch
from fastapi.testclient import TestClient


@pytest.fixture
def client():
    from src.api.main import app
    return TestClient(app)


def test_get_agent_config_returns_defaults_when_null(client):
    """GET /api/sessions/:id/agent-config returns defaults when agent_config is null."""
    with patch("src.api.routes.agent_config.get_session_manager") as mock_sm:
        mock_session = MagicMock()
        mock_session.agent_config = None
        mock_sm.return_value.get_session.return_value = mock_session

        response = client.get("/api/sessions/test-123/agent-config")
        assert response.status_code == 200
        data = response.json()
        assert data["tools"] == []
        assert data["slide_style_id"] is None


def test_put_agent_config_persists(client):
    """PUT /api/sessions/:id/agent-config saves config to session."""
    with patch("src.api.routes.agent_config.get_session_manager") as mock_sm:
        mock_session = MagicMock()
        mock_sm.return_value.get_session.return_value = mock_session

        payload = {
            "tools": [{"type": "genie", "space_id": "abc", "space_name": "Sales"}],
            "slide_style_id": 3,
        }
        response = client.put("/api/sessions/test-123/agent-config", json=payload)
        assert response.status_code == 200


def test_put_agent_config_rejects_duplicates(client):
    """PUT /api/sessions/:id/agent-config rejects duplicate tools."""
    payload = {
        "tools": [
            {"type": "genie", "space_id": "abc", "space_name": "Sales"},
            {"type": "genie", "space_id": "abc", "space_name": "Sales Again"},
        ],
    }
    response = client.put("/api/sessions/test-123/agent-config", json=payload)
    assert response.status_code == 422


def test_patch_tools_adds_tool(client):
    """PATCH /api/sessions/:id/agent-config/tools adds a new tool."""
    with patch("src.api.routes.agent_config.get_session_manager") as mock_sm:
        mock_session = MagicMock()
        mock_session.agent_config = {"tools": [], "slide_style_id": None, "deck_prompt_id": None}
        mock_sm.return_value.get_session.return_value = mock_session

        payload = {"action": "add", "tool": {"type": "genie", "space_id": "abc", "space_name": "Sales"}}
        response = client.patch("/api/sessions/test-123/agent-config/tools", json=payload)
        assert response.status_code == 200
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/unit/test_agent_config_routes.py -v`
Expected: FAIL — module does not exist

- [ ] **Step 3: Implement agent config routes**

```python
# src/api/routes/agent_config.py
"""Routes for session agent configuration."""
from __future__ import annotations

import logging
from typing import Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from src.api.schemas.agent_config import AgentConfig, ToolEntry, resolve_agent_config
from src.api.services.session_manager import get_session_manager

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/sessions", tags=["agent-config"])


@router.get("/{session_id}/agent-config")
def get_agent_config(session_id: str) -> dict:
    sm = get_session_manager()
    session = sm.get_session(session_id)
    config = resolve_agent_config(session.agent_config)
    return config.model_dump()


def _validate_references(config: AgentConfig):
    """Validate that slide_style_id and deck_prompt_id reference existing library entries."""
    from src.core.database import SessionLocal
    db = SessionLocal()
    try:
        if config.slide_style_id is not None:
            from src.database.models import SlideStyleLibrary
            style = db.query(SlideStyleLibrary).filter(
                SlideStyleLibrary.id == config.slide_style_id,
                SlideStyleLibrary.is_active == True,
            ).first()
            if not style:
                raise HTTPException(status_code=422, detail=f"slide_style_id {config.slide_style_id} not found")
        if config.deck_prompt_id is not None:
            from src.database.models import SlideDeckPromptLibrary
            prompt = db.query(SlideDeckPromptLibrary).filter(
                SlideDeckPromptLibrary.id == config.deck_prompt_id,
                SlideDeckPromptLibrary.is_active == True,
            ).first()
            if not prompt:
                raise HTTPException(status_code=422, detail=f"deck_prompt_id {config.deck_prompt_id} not found")
    finally:
        db.close()


@router.put("/{session_id}/agent-config")
def put_agent_config(session_id: str, config: AgentConfig) -> dict:
    _validate_references(config)
    sm = get_session_manager()
    session = sm.get_session(session_id)
    session.agent_config = config.model_dump()
    sm.update_session(session)
    return config.model_dump()


class ToolPatchRequest(BaseModel):
    action: Literal["add", "remove"]
    tool: ToolEntry


@router.patch("/{session_id}/agent-config/tools")
def patch_tools(session_id: str, request: ToolPatchRequest) -> dict:
    sm = get_session_manager()
    session = sm.get_session(session_id)
    config = resolve_agent_config(session.agent_config)

    if request.action == "add":
        config.tools.append(request.tool)
    elif request.action == "remove":
        # Match by type + identifier
        config.tools = [t for t in config.tools if t != request.tool]

    # Re-validate (catches duplicates on add)
    config = AgentConfig.model_validate(config.model_dump())
    session.agent_config = config.model_dump()
    sm.update_session(session)
    return config.model_dump()
```

- [ ] **Step 4: Register route in main.py**

In `src/api/main.py`, add:
```python
from src.api.routes.agent_config import router as agent_config_router
app.include_router(agent_config_router)
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest tests/unit/test_agent_config_routes.py -v`
Expected: All PASS

- [ ] **Step 6: Commit**

```bash
git add src/api/routes/agent_config.py tests/unit/test_agent_config_routes.py src/api/main.py
git commit -m "feat: add GET/PUT/PATCH routes for session agent config"
```

---

### Task 9: Simplified Profile Routes

**Files:**
- Create: `src/api/routes/profiles.py`
- Test: `tests/unit/test_profiles_routes.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/unit/test_profiles_routes.py
import pytest
from unittest.mock import MagicMock, patch
from fastapi.testclient import TestClient


@pytest.fixture
def client():
    from src.api.main import app
    return TestClient(app)


def test_save_from_session_creates_profile(client):
    """POST /api/profiles/save-from-session/:session_id snapshots config."""
    with patch("src.api.routes.profiles.get_session_manager") as mock_sm:
        mock_session = MagicMock()
        mock_session.agent_config = {"tools": [], "slide_style_id": 3}
        mock_sm.return_value.get_session.return_value = mock_session

        with patch("src.api.routes.profiles._create_profile") as mock_create:
            mock_create.return_value = {"id": 1, "name": "My Config", "agent_config": mock_session.agent_config}
            response = client.post(
                "/api/profiles/save-from-session/test-123",
                json={"name": "My Config"},
            )
            assert response.status_code == 200
            assert response.json()["name"] == "My Config"


def test_load_profile_into_session(client):
    """POST /api/sessions/:id/load-profile/:profile_id copies config."""
    with patch("src.api.routes.profiles.get_session_manager") as mock_sm, \
         patch("src.api.routes.profiles._get_profile") as mock_get:
        mock_session = MagicMock()
        mock_sm.return_value.get_session.return_value = mock_session
        mock_get.return_value = MagicMock(agent_config={"tools": [], "slide_style_id": 5})

        response = client.post("/api/sessions/test-123/load-profile/1")
        assert response.status_code == 200


def test_list_profiles(client):
    """GET /api/profiles returns all non-deleted profiles."""
    with patch("src.api.routes.profiles._list_profiles") as mock_list:
        mock_list.return_value = [
            {"id": 1, "name": "Sales", "is_default": True},
            {"id": 2, "name": "QBR", "is_default": False},
        ]
        response = client.get("/api/profiles")
        assert response.status_code == 200
        assert len(response.json()) == 2


def test_delete_profile(client):
    """DELETE /api/profiles/:id soft-deletes."""
    with patch("src.api.routes.profiles._delete_profile") as mock_del:
        mock_del.return_value = True
        response = client.delete("/api/profiles/1")
        assert response.status_code == 200
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/unit/test_profiles_routes.py -v`
Expected: FAIL

- [ ] **Step 3: Implement simplified profile routes**

```python
# src/api/routes/profiles.py
"""Simplified profile routes — save/load named config snapshots."""
from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from src.api.schemas.agent_config import AgentConfig
from src.api.services.session_manager import get_session_manager

logger = logging.getLogger(__name__)
router = APIRouter(tags=["profiles"])


class SaveProfileRequest(BaseModel):
    name: str
    description: Optional[str] = None


class UpdateProfileRequest(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    is_default: Optional[bool] = None


def _get_db():
    from src.core.database import SessionLocal
    return SessionLocal()


def _list_profiles():
    from src.database.models.profile import ConfigProfile
    db = _get_db()
    try:
        profiles = db.query(ConfigProfile).filter(
            ConfigProfile.is_deleted == False
        ).all()
        return [
            {
                "id": p.id,
                "name": p.name,
                "description": p.description,
                "is_default": p.is_default,
                "agent_config": p.agent_config,
                "created_at": p.created_at.isoformat() if p.created_at else None,
                "created_by": p.created_by,
            }
            for p in profiles
        ]
    finally:
        db.close()


def _get_profile(profile_id: int):
    from src.database.models.profile import ConfigProfile
    db = _get_db()
    try:
        profile = db.query(ConfigProfile).filter(
            ConfigProfile.id == profile_id,
            ConfigProfile.is_deleted == False,
        ).first()
        if not profile:
            raise HTTPException(status_code=404, detail="Profile not found")
        return profile
    finally:
        db.close()


def _create_profile(name: str, description: Optional[str], agent_config: dict):
    from src.database.models.profile import ConfigProfile
    db = _get_db()
    try:
        profile = ConfigProfile(
            name=name,
            description=description,
            agent_config=agent_config,
            is_default=False,
        )
        db.add(profile)
        db.commit()
        db.refresh(profile)
        return {"id": profile.id, "name": profile.name, "agent_config": profile.agent_config}
    finally:
        db.close()


def _delete_profile(profile_id: int):
    from src.database.models.profile import ConfigProfile
    db = _get_db()
    try:
        profile = db.query(ConfigProfile).filter(ConfigProfile.id == profile_id).first()
        if not profile:
            raise HTTPException(status_code=404, detail="Profile not found")
        profile.is_deleted = True
        db.commit()
        return True
    finally:
        db.close()


@router.get("/api/profiles")
def list_profiles():
    return _list_profiles()


@router.post("/api/profiles/save-from-session/{session_id}")
def save_from_session(session_id: str, request: SaveProfileRequest):
    sm = get_session_manager()
    session = sm.get_session(session_id)
    agent_config = session.agent_config or AgentConfig().model_dump()
    return _create_profile(request.name, request.description, agent_config)


@router.post("/api/sessions/{session_id}/load-profile/{profile_id}")
def load_profile(session_id: str, profile_id: int):
    sm = get_session_manager()
    session = sm.get_session(session_id)
    profile = _get_profile(profile_id)
    session.agent_config = profile.agent_config
    sm.update_session(session)
    return {"status": "loaded", "agent_config": session.agent_config}


@router.put("/api/profiles/{profile_id}")
def update_profile(profile_id: int, request: UpdateProfileRequest):
    from src.database.models.profile import ConfigProfile
    db = _get_db()
    try:
        profile = db.query(ConfigProfile).filter(
            ConfigProfile.id == profile_id,
            ConfigProfile.is_deleted == False,
        ).first()
        if not profile:
            raise HTTPException(status_code=404, detail="Profile not found")

        if request.name is not None:
            profile.name = request.name
        if request.description is not None:
            profile.description = request.description
        if request.is_default is not None and request.is_default:
            # Clear other defaults
            db.query(ConfigProfile).filter(
                ConfigProfile.id != profile_id
            ).update({"is_default": False})
            profile.is_default = True

        db.commit()
        return {"id": profile.id, "name": profile.name, "is_default": profile.is_default}
    finally:
        db.close()


@router.delete("/api/profiles/{profile_id}")
def delete_profile(profile_id: int):
    _delete_profile(profile_id)
    return {"status": "deleted"}
```

- [ ] **Step 4: Register in main.py**

```python
from src.api.routes.profiles import router as profiles_router
app.include_router(profiles_router)
```

- [ ] **Step 5: Run tests**

Run: `pytest tests/unit/test_profiles_routes.py -v`
Expected: All PASS

- [ ] **Step 6: Commit**

```bash
git add src/api/routes/profiles.py tests/unit/test_profiles_routes.py src/api/main.py
git commit -m "feat: add simplified profile routes (save/load/list/delete)"
```

---

### Task 10: Tool Discovery Route

**Files:**
- Create: `src/api/routes/tools.py`
- Test: `tests/unit/test_tools_routes.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/unit/test_tools_routes.py
import pytest
from unittest.mock import MagicMock, patch
from fastapi.testclient import TestClient


@pytest.fixture
def client():
    from src.api.main import app
    return TestClient(app)


def test_available_tools_returns_genie_spaces(client):
    """GET /api/tools/available returns Genie spaces from Databricks SDK."""
    with patch("src.api.routes.tools._list_genie_spaces") as mock_genie, \
         patch("src.api.routes.tools._list_mcp_servers") as mock_mcp:
        mock_genie.return_value = [
            {"type": "genie", "space_id": "abc", "space_name": "Sales", "description": "Revenue"}
        ]
        mock_mcp.return_value = []

        response = client.get("/api/tools/available")
        assert response.status_code == 200
        tools = response.json()
        assert len(tools) == 1
        assert tools[0]["type"] == "genie"


def test_available_tools_returns_mcp_servers(client):
    """GET /api/tools/available returns MCP servers from config."""
    with patch("src.api.routes.tools._list_genie_spaces") as mock_genie, \
         patch("src.api.routes.tools._list_mcp_servers") as mock_mcp:
        mock_genie.return_value = []
        mock_mcp.return_value = [
            {"type": "mcp", "server_uri": "https://search.example.com", "server_name": "Web Search"}
        ]

        response = client.get("/api/tools/available")
        assert response.status_code == 200
        tools = response.json()
        assert len(tools) == 1
        assert tools[0]["type"] == "mcp"


def test_available_tools_merges_sources(client):
    """GET /api/tools/available merges Genie spaces and MCP servers."""
    with patch("src.api.routes.tools._list_genie_spaces") as mock_genie, \
         patch("src.api.routes.tools._list_mcp_servers") as mock_mcp:
        mock_genie.return_value = [{"type": "genie", "space_id": "abc", "space_name": "Sales"}]
        mock_mcp.return_value = [{"type": "mcp", "server_uri": "https://x.com", "server_name": "Search"}]

        response = client.get("/api/tools/available")
        assert response.status_code == 200
        assert len(response.json()) == 2
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/unit/test_tools_routes.py -v`

- [ ] **Step 3: Implement tool discovery route**

```python
# src/api/routes/tools.py
"""Route for discovering available tools."""
from __future__ import annotations

import logging

from fastapi import APIRouter

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/tools", tags=["tools"])


def _list_genie_spaces() -> list[dict]:
    """Discover available Genie spaces via Databricks SDK."""
    try:
        from src.core.databricks_client import get_databricks_client
        client = get_databricks_client()
        w = client.get_workspace_client()
        spaces = w.genie.list_spaces()
        return [
            {
                "type": "genie",
                "space_id": s.space_id,
                "space_name": s.name,
                "description": getattr(s, "description", None),
            }
            for s in spaces
        ]
    except Exception as e:
        logger.warning(f"Failed to list Genie spaces: {e}")
        return []


def _list_mcp_servers() -> list[dict]:
    """List MCP servers from application config."""
    try:
        from src.core.config_loader import load_config
        config = load_config()
        servers = config.get("mcp_servers", [])
        return [
            {
                "type": "mcp",
                "server_uri": s["uri"],
                "server_name": s["name"],
                "config": s.get("config", {}),
            }
            for s in servers
        ]
    except Exception as e:
        logger.warning(f"Failed to list MCP servers: {e}")
        return []


@router.get("/available")
def get_available_tools():
    """Return all tools the user can add to their agent config."""
    genie_spaces = _list_genie_spaces()
    mcp_servers = _list_mcp_servers()
    return genie_spaces + mcp_servers
```

- [ ] **Step 4: Register in main.py**

```python
from src.api.routes.tools import router as tools_router
app.include_router(tools_router)
```

- [ ] **Step 5: Run tests**

Run: `pytest tests/unit/test_tools_routes.py -v`
Expected: All PASS

- [ ] **Step 6: Commit**

```bash
git add src/api/routes/tools.py tests/unit/test_tools_routes.py src/api/main.py
git commit -m "feat: add GET /api/tools/available for tool discovery"
```

---

### Task 11: Remove Deprecated Routes and Settings

**Files:**
- Modify: `src/api/main.py`
- Delete: `src/api/routes/settings/ai_infra.py`
- Delete: `src/api/routes/settings/genie.py`
- Delete: `src/api/routes/settings/prompts.py`
- Delete: `src/api/routes/settings/profiles.py`

- [ ] **Step 1: Identify all deprecated route registrations in main.py**

Search `src/api/main.py` for `include_router` calls that register the deprecated settings routes.

- [ ] **Step 2: Remove deprecated route registrations**

Remove the `include_router` calls for: `ai_infra`, `genie`, `prompts`, and the old `profiles` settings routes.

- [ ] **Step 3: Delete deprecated route files**

```bash
rm src/api/routes/settings/ai_infra.py
rm src/api/routes/settings/genie.py
rm src/api/routes/settings/prompts.py
rm src/api/routes/settings/profiles.py
```

Keep `src/api/routes/settings/slide_styles.py` and `src/api/routes/settings/deck_prompts.py` — these are global libraries, unchanged.

- [ ] **Step 4: Remove any imports of deleted modules**

Search for imports of the deleted modules in other files and remove them.

- [ ] **Step 5: Run tests**

Run: `pytest tests/ -v --timeout=60 -x`
Expected: Some tests that tested the old routes may fail — delete those test files too. Tests for slide styles and deck prompts should pass.

- [ ] **Step 6: Commit**

```bash
git add -A
git commit -m "feat: remove deprecated settings routes (ai_infra, genie, prompts, old profiles)"
```

---

## Chunk 4: Frontend Changes

### Task 12: TypeScript Types for Agent Config

**Files:**
- Create: `frontend/src/types/agentConfig.ts`

- [ ] **Step 1: Create type definitions**

```typescript
// frontend/src/types/agentConfig.ts

export interface GenieTool {
  type: 'genie';
  space_id: string;
  space_name: string;
  description?: string;
}

export interface MCPTool {
  type: 'mcp';
  server_uri: string;
  server_name: string;
  config?: Record<string, unknown>;
}

export type ToolEntry = GenieTool | MCPTool;

export interface AgentConfig {
  tools: ToolEntry[];
  slide_style_id: number | null;
  deck_prompt_id: number | null;
  system_prompt: string | null;
  slide_editing_instructions: string | null;
}

export interface AvailableTool {
  type: 'genie' | 'mcp';
  space_id?: string;
  space_name?: string;
  server_uri?: string;
  server_name?: string;
  description?: string;
}

export interface ProfileSummary {
  id: number;
  name: string;
  description: string | null;
  is_default: boolean;
  agent_config: AgentConfig | null;
  created_at: string | null;
  created_by: string | null;
}

export const DEFAULT_AGENT_CONFIG: AgentConfig = {
  tools: [],
  slide_style_id: null,
  deck_prompt_id: null,
  system_prompt: null,
  slide_editing_instructions: null,
};
```

- [ ] **Step 2: Commit**

```bash
git add frontend/src/types/agentConfig.ts
git commit -m "feat: add TypeScript types for agent config"
```

---

### Task 13: API Client — Agent Config Methods

**Files:**
- Modify: `frontend/src/services/api.ts`

- [ ] **Step 1: Add agent config API methods**

Add to the `api` object in `frontend/src/services/api.ts`:

```typescript
// Agent Config
async getAgentConfig(sessionId: string): Promise<AgentConfig> {
  const response = await fetch(`${BASE_URL}/api/sessions/${sessionId}/agent-config`);
  if (!response.ok) throw new Error('Failed to fetch agent config');
  return response.json();
},

async updateAgentConfig(sessionId: string, config: AgentConfig): Promise<AgentConfig> {
  const response = await fetch(`${BASE_URL}/api/sessions/${sessionId}/agent-config`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(config),
  });
  if (!response.ok) throw new Error('Failed to update agent config');
  return response.json();
},

async patchTools(sessionId: string, action: 'add' | 'remove', tool: ToolEntry): Promise<AgentConfig> {
  const response = await fetch(`${BASE_URL}/api/sessions/${sessionId}/agent-config/tools`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ action, tool }),
  });
  if (!response.ok) throw new Error('Failed to update tools');
  return response.json();
},

// Tools
async getAvailableTools(): Promise<AvailableTool[]> {
  const response = await fetch(`${BASE_URL}/api/tools/available`);
  if (!response.ok) throw new Error('Failed to fetch available tools');
  return response.json();
},

// Profiles (simplified)
async listProfiles(): Promise<ProfileSummary[]> {
  const response = await fetch(`${BASE_URL}/api/profiles`);
  if (!response.ok) throw new Error('Failed to fetch profiles');
  return response.json();
},

async saveAsProfile(sessionId: string, name: string, description?: string): Promise<ProfileSummary> {
  const response = await fetch(`${BASE_URL}/api/profiles/save-from-session/${sessionId}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ name, description }),
  });
  if (!response.ok) throw new Error('Failed to save profile');
  return response.json();
},

async loadProfile(sessionId: string, profileId: number): Promise<{ status: string; agent_config: AgentConfig }> {
  const response = await fetch(`${BASE_URL}/api/sessions/${sessionId}/load-profile/${profileId}`, {
    method: 'POST',
  });
  if (!response.ok) throw new Error('Failed to load profile');
  return response.json();
},

async deleteProfile(profileId: number): Promise<void> {
  const response = await fetch(`${BASE_URL}/api/profiles/${profileId}`, { method: 'DELETE' });
  if (!response.ok) throw new Error('Failed to delete profile');
},
```

Add the necessary imports at the top:
```typescript
import type { AgentConfig, ToolEntry, AvailableTool, ProfileSummary } from '../types/agentConfig';
```

- [ ] **Step 2: Update createSession to not require profile**

Modify the existing `createSession` method to remove any profile ID parameter.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/services/api.ts
git commit -m "feat: add agent config API methods to frontend client"
```

---

### Task 14: AgentConfigContext

**Files:**
- Create: `frontend/src/contexts/AgentConfigContext.tsx`

- [ ] **Step 1: Implement the context**

```typescript
// frontend/src/contexts/AgentConfigContext.tsx
import React, { createContext, useContext, useState, useCallback, useEffect } from 'react';
import type { AgentConfig, ToolEntry } from '../types/agentConfig';
import { DEFAULT_AGENT_CONFIG } from '../types/agentConfig';
import { api } from '../services/api';
import { useSession } from './SessionContext';
import { useToast } from './ToastContext';

const STORAGE_KEY = 'pendingAgentConfig';

interface AgentConfigContextValue {
  agentConfig: AgentConfig;
  updateConfig: (config: AgentConfig) => Promise<void>;
  addTool: (tool: ToolEntry) => Promise<void>;
  removeTool: (tool: ToolEntry) => Promise<void>;
  setStyle: (styleId: number | null) => Promise<void>;
  setDeckPrompt: (promptId: number | null) => Promise<void>;
  saveAsProfile: (name: string, description?: string) => Promise<void>;
  loadProfile: (profileId: number) => Promise<void>;
  isPreSession: boolean;
}

const AgentConfigContext = createContext<AgentConfigContextValue | null>(null);

export function AgentConfigProvider({ children }: { children: React.ReactNode }) {
  const { sessionId } = useSession();
  const { showToast } = useToast();
  const isPreSession = !sessionId;

  const [agentConfig, setAgentConfig] = useState<AgentConfig>(() => {
    // Restore from localStorage if in pre-session mode
    const stored = localStorage.getItem(STORAGE_KEY);
    if (stored) {
      try { return JSON.parse(stored); } catch { /* ignore */ }
    }
    return { ...DEFAULT_AGENT_CONFIG };
  });

  // On first mount with no session, load the default profile's config (if one exists)
  useEffect(() => {
    if (isPreSession && !localStorage.getItem(STORAGE_KEY)) {
      api.listProfiles().then(profiles => {
        const defaultProfile = profiles.find(p => p.is_default);
        if (defaultProfile?.agent_config) {
          setAgentConfig(defaultProfile.agent_config);
        }
      }).catch(() => { /* use bare defaults */ });
    }
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  // Mirror pre-session config to localStorage
  useEffect(() => {
    if (isPreSession) {
      localStorage.setItem(STORAGE_KEY, JSON.stringify(agentConfig));
    } else {
      localStorage.removeItem(STORAGE_KEY);
    }
  }, [agentConfig, isPreSession]);

  // Load config from session when session becomes active
  useEffect(() => {
    if (sessionId) {
      api.getAgentConfig(sessionId)
        .then(setAgentConfig)
        .catch(() => { /* use current config */ });
    }
  }, [sessionId]);

  const updateConfig = useCallback(async (config: AgentConfig) => {
    const previous = agentConfig;
    setAgentConfig(config);
    if (sessionId) {
      try {
        await api.updateAgentConfig(sessionId, config);
      } catch {
        setAgentConfig(previous);
        showToast('Failed to update config', 'error');
      }
    }
  }, [sessionId, agentConfig, showToast]);

  const addTool = useCallback(async (tool: ToolEntry) => {
    const updated = { ...agentConfig, tools: [...agentConfig.tools, tool] };
    await updateConfig(updated);
  }, [agentConfig, updateConfig]);

  const removeTool = useCallback(async (tool: ToolEntry) => {
    const updated = {
      ...agentConfig,
      tools: agentConfig.tools.filter(t => {
        if (t.type === 'genie' && tool.type === 'genie') return t.space_id !== tool.space_id;
        if (t.type === 'mcp' && tool.type === 'mcp') return t.server_uri !== tool.server_uri;
        return true;
      }),
    };
    await updateConfig(updated);
  }, [agentConfig, updateConfig]);

  const setStyle = useCallback(async (styleId: number | null) => {
    await updateConfig({ ...agentConfig, slide_style_id: styleId });
  }, [agentConfig, updateConfig]);

  const setDeckPrompt = useCallback(async (promptId: number | null) => {
    await updateConfig({ ...agentConfig, deck_prompt_id: promptId });
  }, [agentConfig, updateConfig]);

  const saveAsProfile = useCallback(async (name: string, description?: string) => {
    if (!sessionId) {
      showToast('Send a message first to save as profile', 'error');
      return;
    }
    await api.saveAsProfile(sessionId, name, description);
    showToast('Profile saved', 'success');
  }, [sessionId, showToast]);

  const loadProfile = useCallback(async (profileId: number) => {
    if (sessionId) {
      const result = await api.loadProfile(sessionId, profileId);
      setAgentConfig(result.agent_config);
    } else {
      // Pre-session: just fetch the profile config and apply locally
      const profiles = await api.listProfiles();
      const profile = profiles.find(p => p.id === profileId);
      if (profile?.agent_config) {
        setAgentConfig(profile.agent_config);
      }
    }
  }, [sessionId]);

  return (
    <AgentConfigContext.Provider value={{
      agentConfig, updateConfig, addTool, removeTool,
      setStyle, setDeckPrompt, saveAsProfile, loadProfile,
      isPreSession,
    }}>
      {children}
    </AgentConfigContext.Provider>
  );
}

export function useAgentConfig() {
  const ctx = useContext(AgentConfigContext);
  if (!ctx) throw new Error('useAgentConfig must be used within AgentConfigProvider');
  return ctx;
}
```

- [ ] **Step 2: Commit**

```bash
git add frontend/src/contexts/AgentConfigContext.tsx
git commit -m "feat: add AgentConfigContext with localStorage persistence"
```

---

### Task 15: AgentConfigBar Component

**Files:**
- Create: `frontend/src/components/AgentConfigBar/AgentConfigBar.tsx`
- Create: `frontend/src/components/AgentConfigBar/ToolPicker.tsx`

- [ ] **Step 1: Implement AgentConfigBar**

This is a loosely coupled UI component. The designer will own the final styling, but the functional skeleton is:

```typescript
// frontend/src/components/AgentConfigBar/AgentConfigBar.tsx
import React, { useState } from 'react';
import { useAgentConfig } from '../../contexts/AgentConfigContext';
import { ToolPicker } from './ToolPicker';
import type { ToolEntry } from '../../types/agentConfig';

export function AgentConfigBar() {
  const { agentConfig, removeTool, addTool, setStyle, setDeckPrompt } = useAgentConfig();
  const [showToolPicker, setShowToolPicker] = useState(false);

  return (
    <div className="flex items-center gap-2 flex-wrap px-3 py-2 border-t border-border">
      {/* Active tools as chips */}
      {agentConfig.tools.map((tool, i) => (
        <span
          key={i}
          className="inline-flex items-center gap-1 px-2 py-1 text-xs rounded-full bg-primary/10 text-primary border border-primary/20"
        >
          {tool.type === 'genie' ? `🔌 ${tool.space_name}` : `⚡ ${tool.server_name}`}
          <button
            onClick={() => removeTool(tool)}
            className="ml-1 hover:text-destructive"
          >
            ✕
          </button>
        </span>
      ))}

      {/* Add tool button */}
      <button
        onClick={() => setShowToolPicker(true)}
        className="inline-flex items-center gap-1 px-2 py-1 text-xs rounded-full border border-dashed border-muted-foreground/40 text-muted-foreground hover:border-primary hover:text-primary"
      >
        + Add Tool
      </button>

      {/* Style selector — functional skeleton, designer will refine */}
      <select
        value={agentConfig.slide_style_id ?? ''}
        onChange={(e) => setStyle(e.target.value ? Number(e.target.value) : null)}
        className="text-xs border border-muted-foreground/40 rounded-full px-2 py-1 bg-transparent text-muted-foreground"
      >
        <option value="">Default Style</option>
        {/* Options populated from slide style library — fetch in a useEffect */}
      </select>

      {/* Deck prompt selector — functional skeleton */}
      <select
        value={agentConfig.deck_prompt_id ?? ''}
        onChange={(e) => setDeckPrompt(e.target.value ? Number(e.target.value) : null)}
        className="text-xs border border-muted-foreground/40 rounded-full px-2 py-1 bg-transparent text-muted-foreground"
      >
        <option value="">No Template</option>
        {/* Options populated from deck prompt library — fetch in a useEffect */}
      </select>

      {showToolPicker && (
        <ToolPicker
          onSelect={(tool: ToolEntry) => {
            addTool(tool);
            setShowToolPicker(false);
          }}
          onClose={() => setShowToolPicker(false)}
        />
      )}
    </div>
  );
}
```

- [ ] **Step 2: Implement ToolPicker**

```typescript
// frontend/src/components/AgentConfigBar/ToolPicker.tsx
import React, { useEffect, useState } from 'react';
import { api } from '../../services/api';
import type { AvailableTool, ToolEntry } from '../../types/agentConfig';

interface ToolPickerProps {
  onSelect: (tool: ToolEntry) => void;
  onClose: () => void;
}

export function ToolPicker({ onSelect, onClose }: ToolPickerProps) {
  const [tools, setTools] = useState<AvailableTool[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api.getAvailableTools()
      .then(setTools)
      .catch(() => setError('Unable to load tools'))
      .finally(() => setLoading(false));
  }, []);

  return (
    <div className="absolute bottom-full mb-2 left-0 w-72 bg-card border border-border rounded-lg shadow-lg p-3 z-50">
      <div className="flex justify-between items-center mb-2">
        <span className="text-sm font-medium">Add Tool</span>
        <button onClick={onClose} className="text-muted-foreground hover:text-foreground">✕</button>
      </div>

      {loading && <p className="text-xs text-muted-foreground">Loading...</p>}
      {error && (
        <div className="text-xs text-destructive">
          {error}
          <button onClick={() => { setError(null); setLoading(true); api.getAvailableTools().then(setTools).catch(() => setError('Unable to load tools')).finally(() => setLoading(false)); }} className="ml-2 underline">Retry</button>
        </div>
      )}

      {!loading && !error && tools.map((tool, i) => (
        <button
          key={i}
          onClick={() => onSelect(tool as ToolEntry)}
          className="w-full text-left p-2 rounded hover:bg-muted text-xs"
        >
          <span className="font-medium">
            {tool.type === 'genie' ? `🔌 ${tool.space_name}` : `⚡ ${tool.server_name}`}
          </span>
          {tool.description && <p className="text-muted-foreground mt-0.5">{tool.description}</p>}
        </button>
      ))}

      {!loading && !error && tools.length === 0 && (
        <p className="text-xs text-muted-foreground">No tools available</p>
      )}
    </div>
  );
}
```

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/AgentConfigBar/
git commit -m "feat: add AgentConfigBar and ToolPicker components"
```

---

### Task 16: Routing and Layout Changes

**Files:**
- Modify: `frontend/src/App.tsx`
- Modify: `frontend/src/components/Layout/AppLayout.tsx`
- Modify: `frontend/src/components/Layout/page-header.tsx`
- Delete: `frontend/src/contexts/ProfileContext.tsx`
- Delete: `frontend/src/components/config/ProfileCreationWizard.tsx`
- Delete: `frontend/src/components/config/ProfileSelector.tsx`

- [ ] **Step 1: Change default route to generator**

In `frontend/src/App.tsx`, change the `/` route from help to the generator in pre-session mode:

```typescript
// Before: <Route path="/" element={<AppLayout initialView="help" />} />
// After:
<Route path="/" element={<AppLayout initialView="main" />} />
```

- [ ] **Step 2: Wrap app with AgentConfigProvider**

In `App.tsx`, add `AgentConfigProvider` to the provider tree (inside `SessionProvider`, outside `AppLayout`):

```typescript
import { AgentConfigProvider } from './contexts/AgentConfigContext';

// In the component tree:
<SessionProvider>
  <AgentConfigProvider>
    <Routes>...</Routes>
  </AgentConfigProvider>
</SessionProvider>
```

- [ ] **Step 3: Remove ProfileContext provider**

Remove `ProfileProvider` from the provider tree in `App.tsx`.

- [ ] **Step 4: Remove ProfileSelector from page header**

In `frontend/src/components/Layout/page-header.tsx`, remove the `profileSelector` prop and its rendering (lines 26, 220-226).

In `frontend/src/components/Layout/AppLayout.tsx`, remove the `<ProfileSelector>` usage and the import.

- [ ] **Step 5: Add AgentConfigBar to chat panel area**

In `AppLayout.tsx`, import and render `AgentConfigBar` in the chat panel section (above the chat input). The exact placement will be refined by the designer.

- [ ] **Step 6: Support pre-session mode in AppLayout**

When `initialView="main"` and there's no `sessionId` in the URL, render the generator UI without loading a session. The `AgentConfigContext` handles the pre-session state.

When the user sends their first message, the chat handler creates a session and `SessionContext` receives the new `sessionId`. The URL updates via `navigate(`/sessions/${newId}/edit`)`.

- [ ] **Step 7: Delete deprecated frontend files**

```bash
rm frontend/src/contexts/ProfileContext.tsx
rm frontend/src/components/config/ProfileCreationWizard.tsx
rm frontend/src/components/config/ProfileSelector.tsx
```

- [ ] **Step 8: Fix all import errors**

Search for imports of the deleted files and remove/replace them. Key locations:
- `AppLayout.tsx` — remove ProfileSelector import
- `App.tsx` — remove ProfileProvider import
- Any component that calls `useProfiles()` — replace with `useAgentConfig()` or remove

- [ ] **Step 9: Run frontend dev server to verify**

Run: `cd frontend && npm run dev`
Expected: App builds and runs. Landing page is the generator.

- [ ] **Step 10: Commit**

```bash
git add -A
git commit -m "feat: change landing to generator, add AgentConfigBar, remove ProfileContext"
```

---

## Chunk 5: Cleanup and Testing

### Task 17: Update Existing Backend Tests

**Files:**
- Modify: various test files in `tests/`

- [ ] **Step 1: Find all tests referencing old profile/settings patterns**

```bash
grep -rn "reload_agent\|create_agent\|ProfileService\|config_ai_infra\|config_genie\|config_prompts\|ConfigHistory\|settings/profiles\|settings/ai_infra\|settings/genie\|settings/prompts" tests/ --include="*.py"
```

- [ ] **Step 2: Update or delete broken tests**

For each test:
- If it tests deleted functionality (profile wizard, AI infra settings, etc.) → delete
- If it mocks `self.agent` on ChatService → update to mock `build_agent_for_request` instead
- If it tests profile loading/switching → update to use new profile save/load endpoints
- If it references `ConfigHistory` → remove

- [ ] **Step 3: Run full test suite**

Run: `pytest tests/ -v --timeout=60`
Expected: All pass (or only pre-existing flaky tests fail)

- [ ] **Step 4: Commit**

```bash
git add tests/
git commit -m "test: update existing tests for profile rebuild"
```

---

### Task 18: Update Existing Frontend Tests

**Files:**
- Modify: various test files in `frontend/tests/`

- [ ] **Step 1: Find all tests referencing old profile patterns**

```bash
grep -rn "ProfileSelector\|ProfileCreation\|ProfileContext\|useProfiles\|loadProfile\|profileSelector\|profile-ui\|profile-integration" frontend/tests/ --include="*.ts" --include="*.tsx"
```

- [ ] **Step 2: Update or delete broken tests**

For each test:
- Profile wizard tests → delete
- Profile selector tests → delete
- Tests that mock profile loading → update to use agent config patterns
- Tests that expect `/` to be help page → update to expect generator
- Tests that call `goToGenerator` via "New Session" → may need updating if the flow changed

- [ ] **Step 3: Update setupMocks in test files**

Many test files have their own `setupMocks`. Update these to:
- Remove profile API mocks
- Add agent config API mocks where needed
- Update session creation mocks (no profile_id)

- [ ] **Step 4: Run frontend tests**

Run: `cd frontend && npm run test`
Expected: All pass (or only pre-existing flaky tests fail)

- [ ] **Step 5: Commit**

```bash
git add frontend/tests/
git commit -m "test: update frontend E2E tests for profile rebuild"
```

---

### Task 19: Simplify Profiles Page

**Files:**
- Modify: `frontend/src/components/config/ProfileList.tsx`

- [ ] **Step 1: Simplify ProfileList to a management view**

The profile list page becomes a "Saved Configurations" page. Remove:
- Create profile button / wizard trigger
- AI infra / Genie / prompts editing inline
- Any link to sub-config pages

Keep:
- List of saved profiles with name, description, default badge
- Rename action
- Delete action
- "Load into current session" action
- "Set as default" action

- [ ] **Step 2: Update the route label in sidebar**

In the sidebar navigation, rename "Profiles" to "Saved Configs" or similar.

- [ ] **Step 3: Run frontend dev server to verify**

Run: `cd frontend && npm run dev`
Expected: Profiles page shows simplified list.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/components/config/ProfileList.tsx frontend/src/components/Layout/
git commit -m "feat: simplify profiles page to saved configurations management"
```

---

### Task 20: Remove Deprecated Config Sub-Pages

**Files:**
- Modify: `frontend/src/App.tsx` (remove routes)
- Modify: Sidebar navigation (remove links)
- Delete: AI infra, Genie, and Prompts config components

- [ ] **Step 1: Identify config components to remove**

Check `frontend/src/components/config/` for components related to AI infra, Genie config, and prompts. These are the sub-pages that are no longer needed.

- [ ] **Step 2: Remove routes if they exist**

If there are dedicated routes for these sub-pages, remove them from `App.tsx`.

- [ ] **Step 3: Remove sidebar navigation links**

Remove any sidebar links to AI infra, Genie, or prompts config pages.

- [ ] **Step 4: Delete the component files**

- [ ] **Step 5: Run frontend tests**

Run: `cd frontend && npm run test`
Expected: All pass

- [ ] **Step 6: Commit**

```bash
git add -A
git commit -m "feat: remove deprecated config sub-pages (AI infra, Genie, Prompts)"
```

---

### Task 21: Final Integration Test

- [ ] **Step 1: Run full backend test suite**

Run: `pytest tests/ -v --timeout=60`
Expected: All pass

- [ ] **Step 2: Run full frontend test suite**

Run: `cd frontend && npm run test`
Expected: All pass

- [ ] **Step 3: Manual smoke test**

Start the app locally:
```bash
uvicorn src.api.main:app --reload --port 8000 &
cd frontend && npm run dev &
```

Verify:
1. Landing page is the generator (not help)
2. Can type and send a message → session created, URL updates
3. Can add a tool via AgentConfigBar
4. Can change style and deck prompt
5. Reload page → session and config restored
6. Save as profile → appears in saved configs page
7. Load a profile → config applied to session

- [ ] **Step 4: Commit any fixes from smoke test**

```bash
git add -A
git commit -m "fix: address issues found during integration testing"
```
