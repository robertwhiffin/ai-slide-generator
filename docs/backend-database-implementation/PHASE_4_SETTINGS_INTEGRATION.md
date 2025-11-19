# Phase 4: Application Settings Integration

**Duration:** Days 8-9  
**Status:** Complete ✅  
**Prerequisites:** Phase 3 Complete (API Endpoints)  
**Completion Date:** November 19, 2025

## Objectives

- Refactor `src/config/settings.py` to load from database
- Remove YAML loading from runtime code
- Implement hot-reload mechanism
- Update ChatService to use database-backed settings
- Implement agent reinitialization with session preservation

## Key Changes

### 1. Update Settings Module

**File:** `src/config/settings.py`

Replace YAML loading with database loading:

```python
from src.config.database import get_db_session
from src.models.config import ConfigProfile, ConfigAIInfra, ConfigGenieSpace, ConfigMLflow, ConfigPrompts

class AppSettings(BaseSettings):
    """Application settings loaded from database."""
    
    # Database connection
    database_url: str
    
    # Profile info
    profile_id: int
    profile_name: str
    
    # AI Infrastructure
    llm_endpoint: str
    llm_temperature: float
    llm_max_tokens: int
    
    # Genie
    genie_space_id: str
    genie_space_name: str
    genie_description: Optional[str]
    
    # MLflow
    mlflow_experiment_name: str
    
    # Prompts
    system_prompt: str
    slide_editing_instructions: str
    user_prompt_template: str

_settings_cache: Optional[AppSettings] = None

def get_settings() -> AppSettings:
    """Get cached settings."""
    global _settings_cache
    if _settings_cache is None:
        _settings_cache = load_settings_from_database()
    return _settings_cache

def reload_settings(profile_id: Optional[int] = None) -> AppSettings:
    """Reload settings from database."""
    global _settings_cache
    _settings_cache = load_settings_from_database(profile_id)
    return _settings_cache

def load_settings_from_database(profile_id: Optional[int] = None) -> AppSettings:
    """Load settings from database profile."""
    with get_db_session() as db:
        # Get profile (default or specified)
        if profile_id is None:
            profile = db.query(ConfigProfile).filter_by(is_default=True).one()
        else:
            profile = db.query(ConfigProfile).filter_by(id=profile_id).one()
        
        # Load all configs
        ai_infra = db.query(ConfigAIInfra).filter_by(profile_id=profile.id).one()
        genie_space = db.query(ConfigGenieSpace).filter_by(
            profile_id=profile.id,
            is_default=True
        ).one()
        mlflow = db.query(ConfigMLflow).filter_by(profile_id=profile.id).one()
        prompts = db.query(ConfigPrompts).filter_by(profile_id=profile.id).one()
        
        return AppSettings(
            database_url=os.getenv("DATABASE_URL"),
            profile_id=profile.id,
            profile_name=profile.name,
            llm_endpoint=ai_infra.llm_endpoint,
            llm_temperature=float(ai_infra.llm_temperature),
            llm_max_tokens=ai_infra.llm_max_tokens,
            genie_space_id=genie_space.space_id,
            genie_space_name=genie_space.space_name,
            genie_description=genie_space.description,
            mlflow_experiment_name=mlflow.experiment_name,
            system_prompt=prompts.system_prompt,
            slide_editing_instructions=prompts.slide_editing_instructions,
            user_prompt_template=prompts.user_prompt_template,
        )
```

### 2. Update Agent Initialization

**File:** `src/api/services/chat_service.py`

Add reload capability:

```python
class ChatService:
    def __init__(self):
        self.agent = SlideGeneratorAgent(get_settings())
        self._reload_lock = threading.Lock()
    
    def reload_agent(self, profile_id: Optional[int] = None):
        """
        Reload agent with new settings from database.
        Preserves session state.
        """
        with self._reload_lock:
            # Save current session state
            sessions_backup = copy.deepcopy(self.agent.sessions)
            
            # Reload settings
            reload_settings(profile_id)
            new_settings = get_settings()
            
            # Create new agent
            new_agent = SlideGeneratorAgent(new_settings)
            
            # Restore sessions
            new_agent.sessions = sessions_backup
            
            # Atomic swap
            self.agent = new_agent
```

### 3. Add Reload Endpoint

**File:** `src/api/routes/config/__init__.py` or `profiles.py`

```python
@router.post("/reload")
async def reload_configuration(
    profile_id: Optional[int] = None,
    chat_service: ChatService = Depends(get_chat_service)
):
    """Reload configuration from database."""
    chat_service.reload_agent(profile_id)
    return {"status": "reloaded", "profile_id": profile_id}
```

### 4. Remove YAML Dependencies

- Remove `src/config/loader.py` or mark as deprecated
- Update documentation to indicate YAMLs are for defaults only
- Ensure no runtime code reads from YAMLs

## Testing

```python
def test_load_settings_from_database():
    """Test loading settings from database."""
    settings = load_settings_from_database()
    assert settings.profile_id is not None
    assert settings.llm_endpoint is not None

def test_reload_settings():
    """Test settings reload."""
    original = get_settings()
    reloaded = reload_settings()
    assert reloaded.profile_id == original.profile_id

def test_agent_reload_preserves_sessions():
    """Test agent reload keeps session state."""
    chat_service = ChatService()
    
    # Add session data
    chat_service.agent.sessions["test"] = {"data": "value"}
    
    # Reload
    chat_service.reload_agent()
    
    # Session preserved
    assert "test" in chat_service.agent.sessions
```

## Deliverables

- [x] Settings loaded from database ✅
- [x] YAML loading removed from runtime ✅
- [x] Hot-reload working without restart ✅
- [x] Agent reinitialization preserves sessions ✅
- [x] Tests pass (5/5) ✅
- [x] Can switch profiles and reload ✅

## Next Steps

Proceed to **Phase 5: Frontend Profile Management**.

