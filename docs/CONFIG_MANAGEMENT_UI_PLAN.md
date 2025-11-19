# Configuration Management System - Implementation Plan

## Executive Summary

This document outlines the implementation of a database-backed configuration management system with profile support. All runtime configuration will be stored in PostgreSQL, with no file-based configuration loading. Users can create, save, and switch between named configuration profiles through a web UI.

**Key Features:**
- PostgreSQL-backed configuration storage (no YAML loading)
- Named configuration profiles (save/load/switch)
- Three configuration domains: AI Infrastructure, MLflow, Prompts
- Web UI for configuration management
- Hot-reload without application restart
- Configuration history and audit logging

---

## System Architecture

### Configuration Domains

The system manages three independent configuration domains:

1. **AI Infrastructure (`ai_infra`)**
   - LLM endpoint configuration
   - Model parameters (temperature, max_tokens, top_p, timeout)
   - Genie space configuration
   - API settings

2. **MLflow (`mlflow`)**
   - Experiment tracking configuration
   - Model registry settings
   - Serving endpoints configuration
   - Tracing settings

3. **Prompts (`prompts`)**
   - System prompts
   - Slide editing instructions
   - User prompt templates
   - Any custom prompt variations

### Configuration Profiles

**Profile Concept:**
- A profile is a named, saved configuration state across all three domains
- Users can create multiple profiles (e.g., "Production", "High Creativity", "Fast Mode")
- One profile is marked as "default" (used for new sessions)
- Each session can load any profile independently
- In multi-session scenarios, different sessions can use different profiles simultaneously

**Default Profile:**
- System ships with a "default" prompt profile containing default sourced from prompts.yaml
- Cannot be deleted, can be edited
- Used on first startup

---

## Database Schema

### Core Tables

```sql
-- Configuration profiles
CREATE TABLE config_profiles (
    id SERIAL PRIMARY KEY,
    name VARCHAR(100) NOT NULL UNIQUE,
    description TEXT,
    is_default BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    created_by VARCHAR(255),
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_by VARCHAR(255),
    CONSTRAINT single_default_profile CHECK (
        (is_default = FALSE) OR 
        (SELECT COUNT(*) FROM config_profiles WHERE is_default = TRUE) = 1
    )
);

-- AI Infrastructure configuration
CREATE TABLE config_ai_infra (
    id SERIAL PRIMARY KEY,
    profile_id INTEGER NOT NULL REFERENCES config_profiles(id) ON DELETE CASCADE,
    
    -- LLM settings
    llm_endpoint VARCHAR(255) NOT NULL,
    llm_temperature DECIMAL(3,2) NOT NULL CHECK (llm_temperature >= 0 AND llm_temperature <= 1),
    llm_max_tokens INTEGER NOT NULL CHECK (llm_max_tokens > 0),
    
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    
    UNIQUE(profile_id)
);

-- Genie spaces configuration (can have multiple per profile)
CREATE TABLE config_genie_spaces (
    id SERIAL PRIMARY KEY,
    profile_id INTEGER NOT NULL REFERENCES config_profiles(id) ON DELETE CASCADE,
    
    space_id VARCHAR(255) NOT NULL,
    space_name VARCHAR(255) NOT NULL,
    description TEXT,
    is_default BOOLEAN DEFAULT FALSE,  -- Default space for this profile
    
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    
    CONSTRAINT single_default_space_per_profile CHECK (
        (is_default = FALSE) OR 
        (SELECT COUNT(*) FROM config_genie_spaces 
         WHERE profile_id = config_genie_spaces.profile_id AND is_default = TRUE) = 1
    )
);

-- MLflow configuration
CREATE TABLE config_mlflow (
    id SERIAL PRIMARY KEY,
    profile_id INTEGER NOT NULL REFERENCES config_profiles(id) ON DELETE CASCADE,
    
    experiment_name VARCHAR(255) NOT NULL,
    
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    
    UNIQUE(profile_id)
);

-- Prompts configuration
CREATE TABLE config_prompts (
    id SERIAL PRIMARY KEY,
    profile_id INTEGER NOT NULL REFERENCES config_profiles(id) ON DELETE CASCADE,
    
    system_prompt TEXT NOT NULL,
    slide_editing_instructions TEXT NOT NULL,
    user_prompt_template TEXT NOT NULL,
    
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    
    UNIQUE(profile_id)
);

-- Configuration change history (audit log)
CREATE TABLE config_history (
    id SERIAL PRIMARY KEY,
    profile_id INTEGER NOT NULL REFERENCES config_profiles(id) ON DELETE CASCADE,
    domain VARCHAR(50) NOT NULL,  -- 'ai_infra', 'mlflow', 'prompts', 'profile'
    action VARCHAR(50) NOT NULL,  -- 'create', 'update', 'delete', 'activate'
    changed_by VARCHAR(255) NOT NULL,
    changes JSONB NOT NULL,  -- {"field": {"old": "...", "new": "..."}}
    snapshot JSONB,  -- Full config snapshot at time of change
    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Indexes for performance
CREATE INDEX idx_config_profiles_default ON config_profiles(is_default) WHERE is_default = TRUE;
CREATE INDEX idx_config_profiles_name ON config_profiles(name);
CREATE INDEX idx_config_genie_spaces_profile ON config_genie_spaces(profile_id);
CREATE INDEX idx_config_genie_spaces_default ON config_genie_spaces(profile_id, is_default) WHERE is_default = TRUE;
CREATE INDEX idx_config_history_profile ON config_history(profile_id);
CREATE INDEX idx_config_history_timestamp ON config_history(timestamp DESC);
CREATE INDEX idx_config_history_domain ON config_history(domain);
```

### Database Constraints

1. **Single Default Profile:** Only one profile can be marked as default at a time (enforced by constraint)
2. **Cascade Deletes:** Deleting a profile deletes all associated configs
3. **Cannot Delete Default Profile:** Application-level check prevents deleting default profile
4. **Cannot Delete In-Use Profile:** Application-level check prevents deleting profiles currently loaded by sessions

---

## Backend Architecture

### Technology Stack

- **ORM:** SQLAlchemy 2.0+
- **Database:** PostgreSQL 14+
- **Migrations:** Alembic
- **API:** FastAPI (existing)

### Component Structure

```
src/
├── models/
│   ├── config/                     # Configuration models (grouped)
│   │   ├── __init__.py
│   │   ├── profile.py              # ConfigProfile model
│   │   ├── ai_infra.py             # ConfigAIInfra model
│   │   ├── genie_space.py          # ConfigGenieSpace model
│   │   ├── mlflow.py               # ConfigMLflow model
│   │   ├── prompts.py              # ConfigPrompts model
│   │   └── history.py              # ConfigHistory model
│   ├── slide.py                    # Existing slide models
│   └── slide_deck.py               # Existing slide deck models
├── services/
│   ├── config/                     # Configuration services (grouped)
│   │   ├── __init__.py
│   │   ├── profile_service.py      # Profile management
│   │   ├── config_service.py       # Config CRUD operations
│   │   ├── genie_service.py        # Genie space management
│   │   └── validator.py            # Configuration validation
│   ├── agent.py                    # Existing agent service
│   └── tools.py                    # Existing tools
├── api/
│   ├── routes/
│   │   ├── config/                 # Config routes (grouped)
│   │   │   ├── __init__.py
│   │   │   ├── profiles.py         # Profile endpoints
│   │   │   ├── ai_infra.py         # AI infra endpoints
│   │   │   ├── genie.py            # Genie endpoints
│   │   │   ├── mlflow.py           # MLflow endpoints
│   │   │   └── prompts.py          # Prompts endpoints
│   │   ├── chat.py                 # Existing chat routes
│   │   └── slides.py               # Existing slide routes
│   ├── models/
│   │   ├── config/                 # Config API models (grouped)
│   │   │   ├── __init__.py
│   │   │   ├── requests.py         # Pydantic request models
│   │   │   └── responses.py        # Pydantic response models
│   │   ├── requests.py             # Existing API request models
│   │   └── responses.py            # Existing API response models
│   └── services/
│       ├── chat_service.py         # Existing chat service
│       └── config_service.py       # Config service dependency injection
└── config/
    ├── database.py                 # Database connection
    ├── settings.py                 # Application settings (from DB)
    └── defaults.py                 # Hardcoded defaults for initial setup
```

---

## API Endpoints

### Profile Management

```
GET    /api/config/profiles                     # List all profiles
GET    /api/config/profiles/{id}                # Get profile details
GET    /api/config/profiles/default             # Get default profile
POST   /api/config/profiles                     # Create new profile
PUT    /api/config/profiles/{id}                # Update profile metadata
DELETE /api/config/profiles/{id}                # Delete profile (not if default or in use)
POST   /api/config/profiles/{id}/set-default    # Mark this profile as default
POST   /api/config/profiles/{id}/duplicate      # Duplicate profile with new name
POST   /api/config/profiles/{id}/load           # Load this profile for current session
```

### AI Infrastructure Configuration

```
GET    /api/config/ai-infra/{profile_id}    # Get AI infra config for specific profile
PUT    /api/config/ai-infra/{profile_id}    # Update AI infra config
GET    /api/config/ai-infra/endpoints       # Get available Databricks endpoints (list)
POST   /api/config/ai-infra/validate        # Validate AI infra config without saving
```

### Genie Configuration

```
GET    /api/config/genie/{profile_id}           # Get all Genie spaces for profile
GET    /api/config/genie/{profile_id}/default   # Get default Genie space for profile
POST   /api/config/genie/{profile_id}           # Add Genie space to profile
PUT    /api/config/genie/{space_id}             # Update Genie space
DELETE /api/config/genie/{space_id}             # Remove Genie space
POST   /api/config/genie/{space_id}/set-default # Set as default space for profile
POST   /api/config/genie/validate               # Validate Genie space is accessible
```

### MLflow Configuration

```
GET    /api/config/mlflow/{profile_id}      # Get MLflow config for specific profile
PUT    /api/config/mlflow/{profile_id}      # Update MLflow config (experiment name)
```

### Prompts Configuration

```
GET    /api/config/prompts/{profile_id}     # Get prompts for specific profile
PUT    /api/config/prompts/{profile_id}     # Update prompts
POST   /api/config/prompts/validate         # Validate prompts without saving
```

### History & Audit

```
GET    /api/config/history                  # Get change history (all profiles)
GET    /api/config/history/{profile_id}     # Get history for specific profile
```

### System Operations

```
POST   /api/config/reload                   # Reload configuration from database
GET    /api/config/status                   # Get config system status
```

---

## Request/Response Models

### Profile Models

```python
# Request models
class ProfileCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    description: Optional[str] = None
    copy_from_profile_id: Optional[int] = None  # Copy settings from existing profile

class ProfileUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=100)
    description: Optional[str] = None

# Response models
class ProfileSummary(BaseModel):
    id: int
    name: str
    description: Optional[str]
    is_default: bool
    created_at: datetime
    updated_at: datetime

class ProfileDetail(BaseModel):
    id: int
    name: str
    description: Optional[str]
    is_default: bool
    created_at: datetime
    created_by: Optional[str]
    updated_at: datetime
    updated_by: Optional[str]
    ai_infra: AIInfraConfig
    mlflow: MLflowConfig
    prompts: PromptsConfig
```

### AI Infrastructure Models

```python
class AIInfraConfigUpdate(BaseModel):
    llm_endpoint: Optional[str] = None
    llm_temperature: Optional[float] = Field(None, ge=0.0, le=1.0)
    llm_max_tokens: Optional[int] = Field(None, gt=0)

class AIInfraConfig(BaseModel):
    profile_id: int
    llm_endpoint: str
    llm_temperature: float
    llm_max_tokens: int
    updated_at: datetime
```

### Genie Models

```python
class GenieSpaceCreate(BaseModel):
    space_id: str = Field(..., min_length=1)
    space_name: str = Field(..., min_length=1)
    description: Optional[str] = None
    is_default: bool = False

class GenieSpaceUpdate(BaseModel):
    space_name: Optional[str] = Field(None, min_length=1)
    description: Optional[str] = None

class GenieSpace(BaseModel):
    id: int
    profile_id: int
    space_id: str
    space_name: str
    description: Optional[str]
    is_default: bool
    created_at: datetime
    updated_at: datetime
```

### MLflow Models

```python
class MLflowConfigUpdate(BaseModel):
    experiment_name: Optional[str] = Field(None, min_length=1)

class MLflowConfig(BaseModel):
    profile_id: int
    experiment_name: str
    updated_at: datetime
```

### Prompts Models

```python
class PromptsConfigUpdate(BaseModel):
    system_prompt: Optional[str] = None
    slide_editing_instructions: Optional[str] = None
    user_prompt_template: Optional[str] = None

class PromptsConfig(BaseModel):
    profile_id: int
    system_prompt: str
    slide_editing_instructions: str
    user_prompt_template: str
    updated_at: datetime
```

### History Models

```python
class ConfigHistoryEntry(BaseModel):
    id: int
    profile_id: int
    profile_name: str
    domain: str  # 'ai_infra', 'mlflow', 'prompts', 'profile'
    action: str  # 'create', 'update', 'delete', 'activate'
    changed_by: str
    changes: Dict[str, Any]
    timestamp: datetime
```

---

## Backend Services

### ProfileService

```python
class ProfileService:
    """Manage configuration profiles."""
    
    def __init__(self, db: Session):
        self.db = db
    
    async def list_profiles(self) -> List[ProfileSummary]:
        """Get all profiles."""
        pass
    
    async def get_profile(self, profile_id: int) -> ProfileDetail:
        """Get profile with all configurations."""
        pass
    
    async def get_default_profile(self) -> ProfileDetail:
        """Get default profile."""
        pass
    
    async def create_profile(
        self, 
        name: str, 
        description: Optional[str],
        copy_from_id: Optional[int],
        user: str
    ) -> ProfileDetail:
        """
        Create new profile.
        If copy_from_id provided, copy all configs from that profile.
        Otherwise, use system defaults.
        """
        pass
    
    async def update_profile(
        self, 
        profile_id: int, 
        name: Optional[str],
        description: Optional[str],
        user: str
    ) -> ProfileDetail:
        """Update profile metadata."""
        pass
    
    async def delete_profile(self, profile_id: int, user: str) -> None:
        """Delete profile. Cannot delete default or in-use profile."""
        pass
    
    async def set_default_profile(self, profile_id: int, user: str) -> ProfileDetail:
        """
        Mark profile as default (unmarks other default).
        New sessions will use this profile by default.
        """
        pass
    
    async def load_profile(self, profile_id: int) -> ProfileDetail:
        """
        Load profile for current session.
        Returns full profile configuration.
        """
        pass
    
    async def duplicate_profile(
        self, 
        profile_id: int, 
        new_name: str,
        user: str
    ) -> ProfileDetail:
        """Duplicate profile with new name."""
        pass
```

### ConfigService

```python
class ConfigService:
    """Manage configuration within profiles."""
    
    def __init__(self, db: Session):
        self.db = db
        self.validator = ConfigValidator()
    
    # AI Infrastructure
    async def get_ai_infra_config(self, profile_id: int) -> AIInfraConfig:
        """Get AI infra config for specific profile."""
        pass
    
    async def update_ai_infra_config(
        self, 
        profile_id: int,
        updates: AIInfraConfigUpdate,
        user: str
    ) -> AIInfraConfig:
        """Update AI infrastructure configuration."""
        pass
    
    async def get_available_endpoints(self) -> List[str]:
        """
        Get list of available Databricks serving endpoints.
        Returns endpoints sorted with databricks- prefixed first.
        """
        pass
    
    # MLflow
    async def get_mlflow_config(self, profile_id: int) -> MLflowConfig:
        """Get MLflow config for specific profile."""
        pass
    
    async def update_mlflow_config(
        self,
        profile_id: int,
        updates: MLflowConfigUpdate,
        user: str
    ) -> MLflowConfig:
        """Update MLflow configuration (experiment name only)."""
        pass
    
    # Prompts
    async def get_prompts_config(self, profile_id: int) -> PromptsConfig:
        """Get prompts config for specific profile."""
        pass
    
    async def update_prompts_config(
        self,
        profile_id: int,
        updates: PromptsConfigUpdate,
        user: str
    ) -> PromptsConfig:
        """Update prompts configuration."""
        pass
    
    # History
    async def get_config_history(
        self, 
        profile_id: Optional[int] = None,
        domain: Optional[str] = None,
        limit: int = 100
    ) -> List[ConfigHistoryEntry]:
        """Get configuration change history."""
        pass
    
    # System
    async def reload_configuration(self) -> Dict[str, Any]:
        """
        Reload configuration from database.
        Fetches profile and reinitializes application.
        """
        pass
```

### GenieService

```python
class GenieService:
    """Manage Genie spaces for profiles."""
    
    def __init__(self, db: Session):
        self.db = db
    
    async def list_genie_spaces(self, profile_id: int) -> List[GenieSpace]:
        """Get all Genie spaces for profile."""
        pass
    
    async def get_default_genie_space(self, profile_id: int) -> GenieSpace:
        """Get default Genie space for profile."""
        pass
    
    async def add_genie_space(
        self,
        profile_id: int,
        space_data: GenieSpaceCreate,
        user: str
    ) -> GenieSpace:
        """Add Genie space to profile."""
        pass
    
    async def update_genie_space(
        self,
        space_id: int,
        updates: GenieSpaceUpdate,
        user: str
    ) -> GenieSpace:
        """Update Genie space metadata."""
        pass
    
    async def delete_genie_space(self, space_id: int, user: str) -> None:
        """Remove Genie space from profile."""
        pass
    
    async def set_default_genie_space(
        self,
        space_id: int,
        user: str
    ) -> GenieSpace:
        """Mark Genie space as default for its profile."""
        pass
    
    async def validate_genie_space(self, space_id: str) -> ValidationResult:
        """Validate that Genie space exists and is accessible."""
        pass
```

### ConfigValidator

```python
class ConfigValidator:
    """Validate configuration values."""
    
    async def validate_ai_infra(self, config: AIInfraConfigUpdate) -> ValidationResult:
        """
        Validate AI infrastructure configuration:
        - LLM endpoint exists and is accessible
        - Temperature in valid range
        - Max tokens reasonable
        """
        pass
    
    async def validate_genie_space(self, space_id: str) -> ValidationResult:
        """
        Validate Genie space:
        - Space ID exists
        - Space is accessible with current credentials
        """
        pass
    
    async def validate_mlflow(self, config: MLflowConfigUpdate) -> ValidationResult:
        """
        Validate MLflow configuration:
        - Experiment name format is valid
        """
        pass
    
    async def validate_prompts(self, config: PromptsConfigUpdate) -> ValidationResult:
        """
        Validate prompts:
        - Required placeholders present ({question}, {max_slides})
        - No malformed template syntax
        """
        pass
```

---

## Application Settings Integration

### Current State

Application currently loads settings from YAML files at startup via `src/config/settings.py`.

### New State

Settings will be loaded from the active profile in the database.

```python
# src/config/settings.py

from sqlalchemy import select
from src.models.config_profile import ConfigProfile
from src.models.config_ai_infra import ConfigAIInfra
from src.models.config_mlflow import ConfigMLflow
from src.models.config_prompts import ConfigPrompts

class AppSettings(BaseSettings):
    """Application settings loaded from database."""
    
    # Database connection (from environment)
    database_url: str
    
    # Current profile
    profile_id: int
    profile_name: str
    
    # AI Infrastructure
    llm_endpoint: str
    llm_temperature: float
    llm_max_tokens: int
    
    # Genie (default space for profile)
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

def reload_settings() -> AppSettings:
    """Reload settings from database (active profile)."""
    global _settings_cache
    _settings_cache = load_settings_from_database()
    return _settings_cache

def load_settings_from_database(profile_id: Optional[int] = None) -> AppSettings:
    """
    Load settings from database.
    
    Args:
        profile_id: Specific profile to load. If None, loads default profile.
    """
    from src.config.database import get_db_session
    from src.models.config.genie_space import ConfigGenieSpace
    
    with get_db_session() as db:
        # Get profile (default or specified)
        if profile_id is None:
            stmt = select(ConfigProfile).where(ConfigProfile.is_default == True)
        else:
            stmt = select(ConfigProfile).where(ConfigProfile.id == profile_id)
        profile = db.execute(stmt).scalar_one()
        
        # Load all configs for profile
        ai_infra = db.query(ConfigAIInfra).filter_by(profile_id=profile.id).one()
        mlflow = db.query(ConfigMLflow).filter_by(profile_id=profile.id).one()
        prompts = db.query(ConfigPrompts).filter_by(profile_id=profile.id).one()
        
        # Load default Genie space
        genie_space = db.query(ConfigGenieSpace).filter_by(
            profile_id=profile.id,
            is_default=True
        ).one()
        
        # Build settings object
        return AppSettings(
            database_url=os.getenv("DATABASE_URL"),
            profile_id=profile.id,
            profile_name=profile.name,
            llm_endpoint=ai_infra.llm_endpoint,
            llm_temperature=ai_infra.llm_temperature,
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

### Agent Reinitialization

When profile is switched or config is updated:

```python
# src/api/services/chat_service.py

class ChatService:
    def reload_agent(self):
        """Reload agent with new settings from database."""
        # Save session state
        sessions_backup = self.agent.sessions.copy()
        
        # Reload settings from database
        reload_settings()
        new_settings = get_settings()
        
        # Create new agent
        new_agent = SlideGeneratorAgent(new_settings)
        
        # Restore sessions
        new_agent.sessions = sessions_backup
        
        # Atomic swap
        self.agent = new_agent
```

---

## Frontend Architecture

### Component Structure

```
frontend/src/
├── components/
│   └── ConfigPanel/
│       ├── ConfigPanel.tsx              # Main container with tabs
│       ├── ProfileSelector.tsx          # Profile dropdown + management
│       ├── ProfileManager.tsx           # Create/edit/delete profiles modal
│       ├── AIInfraForm.tsx              # AI infrastructure config form
│       ├── MLflowForm.tsx               # MLflow config form
│       ├── PromptsEditor.tsx            # Prompts editor with Monaco
│       ├── ConfigHistory.tsx            # History viewer
│       └── ProfileCompare.tsx           # Compare two profiles side-by-side
├── services/
│   └── configApi.ts                     # API client
└── types/
    └── config.ts                        # TypeScript types
```

### Main Config Panel Layout

```
┌─────────────────────────────────────────────────────────────┐
│  Configuration Management                            [Close] │
├─────────────────────────────────────────────────────────────┤
│  Profile: [Production ▼]  [New] [Edit] [Duplicate] [Delete]│
├─────────────────────────────────────────────────────────────┤
│  [AI Infrastructure] [MLflow] [Prompts] [History]           │
├─────────────────────────────────────────────────────────────┤
│                                                               │
│  (Form content based on selected tab)                        │
│                                                               │
│                                                               │
│                                                               │
│                                                               │
├─────────────────────────────────────────────────────────────┤
│                    [Cancel] [Save Changes] [Apply & Reload]  │
└─────────────────────────────────────────────────────────────┘
```

### Profile Selector

```tsx
// ProfileSelector.tsx
const ProfileSelector = () => {
  const [profiles, setProfiles] = useState<ProfileSummary[]>([]);
  const [currentProfile, setCurrentProfile] = useState<ProfileSummary | null>(null);
  
  const handleProfileChange = async (profileId: number) => {
    const profile = profiles.find(p => p.id === profileId);
    await configApi.loadProfile(profileId);
    // Trigger app reload with new profile
    await configApi.reloadConfiguration(profileId);
    setCurrentProfile(profile);
    showSuccess(`Switched to profile: ${profile.name}`);
  };
  
  return (
    <div className="profile-selector">
      <select 
        value={currentProfile?.id} 
        onChange={(e) => handleProfileChange(Number(e.target.value))}
      >
        {profiles.map(p => (
          <option key={p.id} value={p.id}>
            {p.name} {p.is_default && '(default)'}
          </option>
        ))}
      </select>
      <button onClick={openProfileManager}>Manage Profiles</button>
    </div>
  );
};
```

### AI Infrastructure Form

```tsx
// AIInfraForm.tsx
const AIInfraForm = ({ profileId }: { profileId: number }) => {
  const [config, setConfig] = useState<AIInfraConfig | null>(null);
  const [endpoints, setEndpoints] = useState<string[]>([]);
  
  useEffect(() => {
    loadConfig();
    loadEndpoints();
  }, [profileId]);
  
  const loadConfig = async () => {
    const data = await configApi.getAIInfraConfig(profileId);
    setConfig(data);
  };
  
  const loadEndpoints = async () => {
    const data = await configApi.getAvailableEndpoints();
    setEndpoints(data);
  };
  
  const handleSave = async () => {
    await configApi.updateAIInfraConfig(profileId, config);
    showSuccess('AI Infrastructure configuration saved');
  };
  
  return (
    <form>
      <h3>LLM Configuration</h3>
      <label>
        Endpoint:
        <select value={config?.llm_endpoint} onChange={handleEndpointChange}>
          {endpoints.map(ep => <option key={ep} value={ep}>{ep}</option>)}
        </select>
      </label>
      
      <label>
        Temperature: {config?.llm_temperature}
        <input 
          type="range" 
          min="0" 
          max="1" 
          step="0.1"
          value={config?.llm_temperature}
          onChange={handleTemperatureChange}
        />
      </label>
      
      {/* More fields... */}
      
      <h3>Genie Configuration</h3>
      <label>
        Space ID:
        <input 
          type="text" 
          value={config?.genie_space_id}
          onChange={handleGenieSpaceChange}
        />
      </label>
      
      {/* More fields... */}
    </form>
  );
};
```

### Prompts Editor

```tsx
// PromptsEditor.tsx
import Editor from '@monaco-editor/react';

const PromptsEditor = ({ profileId }: { profileId: number }) => {
  const [prompts, setPrompts] = useState<PromptsConfig | null>(null);
  const [activeTab, setActiveTab] = useState<'system' | 'editing' | 'user'>('system');
  
  const handleSave = async () => {
    await configApi.updatePromptsConfig(profileId, prompts);
    showSuccess('Prompts saved');
  };
  
  return (
    <div className="prompts-editor">
      <div className="tabs">
        <button onClick={() => setActiveTab('system')}>System Prompt</button>
        <button onClick={() => setActiveTab('editing')}>Editing Instructions</button>
        <button onClick={() => setActiveTab('user')}>User Template</button>
      </div>
      
      <Editor
        height="400px"
        defaultLanguage="markdown"
        value={prompts?.[`${activeTab}_prompt`]}
        onChange={(value) => handlePromptChange(activeTab, value)}
        options={{
          minimap: { enabled: false },
          wordWrap: 'on',
        }}
      />
      
      <div className="prompt-help">
        <h4>Required Placeholders:</h4>
        <ul>
          <li><code>{'{question}'}</code> - User's question</li>
          <li><code>{'{max_slides}'}</code> - Maximum slide count</li>
        </ul>
      </div>
    </div>
  );
};
```

### Profile Manager

```tsx
// ProfileManager.tsx
const ProfileManager = ({ onClose }: { onClose: () => void }) => {
  const [profiles, setProfiles] = useState<ProfileSummary[]>([]);
  const [editingProfile, setEditingProfile] = useState<ProfileSummary | null>(null);
  
  const handleCreateProfile = async (name: string, description: string, copyFromId?: number) => {
    const newProfile = await configApi.createProfile({
      name,
      description,
      copy_from_profile_id: copyFromId,
    });
    setProfiles([...profiles, newProfile]);
    showSuccess(`Profile "${name}" created`);
  };
  
  const handleDeleteProfile = async (profileId: number) => {
    if (!confirm('Delete this profile? This cannot be undone.')) return;
    
    await configApi.deleteProfile(profileId);
    setProfiles(profiles.filter(p => p.id !== profileId));
    showSuccess('Profile deleted');
  };
  
  const handleDuplicateProfile = async (profileId: number, newName: string) => {
    const duplicated = await configApi.duplicateProfile(profileId, newName);
    setProfiles([...profiles, duplicated]);
    showSuccess(`Profile duplicated as "${newName}"`);
  };
  
  return (
    <Modal isOpen onClose={onClose}>
      <h2>Manage Configuration Profiles</h2>
      
      <div className="profile-list">
        {profiles.map(profile => (
          <div key={profile.id} className="profile-item">
            <div>
              <strong>{profile.name}</strong>
              {profile.is_default && <span className="badge">Default</span>}
              <p>{profile.description}</p>
            </div>
            <div className="actions">
              <button onClick={() => setEditingProfile(profile)}>Edit</button>
              <button onClick={() => handleDuplicateProfile(profile.id, `${profile.name} (copy)`)}>
                Duplicate
              </button>
              <button 
                onClick={() => handleDeleteProfile(profile.id)}
                disabled={profile.is_default}
              >
                Delete
              </button>
              <button
                onClick={() => handleSetDefault(profile.id)}
                disabled={profile.is_default}
              >
                Set as Default
              </button>
            </div>
          </div>
        ))}
      </div>
      
      <button onClick={() => setEditingProfile({} as ProfileSummary)}>
        Create New Profile
      </button>
      
      {editingProfile && (
        <ProfileEditForm
          profile={editingProfile}
          onSave={handleCreateProfile}
          onCancel={() => setEditingProfile(null)}
        />
      )}
    </Modal>
  );
};
```

---

## API Client

```typescript
// frontend/src/services/configApi.ts

const API_BASE = import.meta.env.VITE_API_URL || 'http://localhost:8000';

export const configApi = {
  // Profiles
  async listProfiles(): Promise<ProfileSummary[]> {
    const res = await fetch(`${API_BASE}/api/config/profiles`);
    return res.json();
  },
  
  async getDefaultProfile(): Promise<ProfileDetail> {
    const res = await fetch(`${API_BASE}/api/config/profiles/default`);
    return res.json();
  },
  
  async getProfile(profileId: number): Promise<ProfileDetail> {
    const res = await fetch(`${API_BASE}/api/config/profiles/${profileId}`);
    return res.json();
  },
  
  async createProfile(data: ProfileCreate): Promise<ProfileDetail> {
    const res = await fetch(`${API_BASE}/api/config/profiles`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(data),
    });
    return res.json();
  },
  
  async loadProfile(profileId: number): Promise<ProfileDetail> {
    const res = await fetch(`${API_BASE}/api/config/profiles/${profileId}/load`, {
      method: 'POST',
    });
    return res.json();
  },
  
  async setDefaultProfile(profileId: number): Promise<ProfileDetail> {
    const res = await fetch(`${API_BASE}/api/config/profiles/${profileId}/set-default`, {
      method: 'POST',
    });
    return res.json();
  },
  
  async duplicateProfile(profileId: number, newName: string): Promise<ProfileDetail> {
    const res = await fetch(`${API_BASE}/api/config/profiles/${profileId}/duplicate`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name: newName }),
    });
    return res.json();
  },
  
  async deleteProfile(profileId: number): Promise<void> {
    await fetch(`${API_BASE}/api/config/profiles/${profileId}`, {
      method: 'DELETE',
    });
  },
  
  // AI Infrastructure
  async getAIInfraConfig(profileId: number): Promise<AIInfraConfig> {
    const res = await fetch(`${API_BASE}/api/config/ai-infra/${profileId}`);
    return res.json();
  },
  
  async updateAIInfraConfig(profileId: number, data: AIInfraConfigUpdate): Promise<AIInfraConfig> {
    const res = await fetch(`${API_BASE}/api/config/ai-infra/${profileId}`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(data),
    });
    return res.json();
  },
  
  async getAvailableEndpoints(): Promise<string[]> {
    const res = await fetch(`${API_BASE}/api/config/ai-infra/endpoints`);
    return res.json();
  },
  
  // MLflow
  async getMLflowConfig(profileId: number): Promise<MLflowConfig> {
    const res = await fetch(`${API_BASE}/api/config/mlflow/${profileId}`);
    return res.json();
  },
  
  async updateMLflowConfig(profileId: number, data: MLflowConfigUpdate): Promise<MLflowConfig> {
    const res = await fetch(`${API_BASE}/api/config/mlflow/${profileId}`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(data),
    });
    return res.json();
  },
  
  // Prompts
  async getPromptsConfig(profileId: number): Promise<PromptsConfig> {
    const res = await fetch(`${API_BASE}/api/config/prompts/${profileId}`);
    return res.json();
  },
  
  async updatePromptsConfig(profileId: number, data: PromptsConfigUpdate): Promise<PromptsConfig> {
    const res = await fetch(`${API_BASE}/api/config/prompts/${profileId}`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(data),
    });
    return res.json();
  },
  
  // History
  async getConfigHistory(profileId?: number): Promise<ConfigHistoryEntry[]> {
    const url = profileId 
      ? `${API_BASE}/api/config/history/${profileId}`
      : `${API_BASE}/api/config/history`;
    const res = await fetch(url);
    return res.json();
  },
  
  // System
  async reloadConfiguration(profileId?: number): Promise<{ status: string }> {
    const url = profileId 
      ? `${API_BASE}/api/config/reload?profile_id=${profileId}`
      : `${API_BASE}/api/config/reload`;
    const res = await fetch(url, {
      method: 'POST',
    });
    return res.json();
  },
};
```

---

## Implementation Phases

### Phase 1: Database Setup & Models (Days 1-2)

**Tasks:**
1. Create Alembic migration for database schema
2. Implement SQLAlchemy models for all config tables
3. Create database connection and session management
4. Implement system defaults in code (for initial profile)
5. Create database initialization script (creates default profile)

**Testing:**
- Test database schema creation
- Test model relationships and cascading deletes
- Test constraint enforcement (single active profile, etc.)
- Test initial profile creation with defaults

**Deliverables:**
- Database migrations ready to run
- SQLAlchemy models functional
- Database can be initialized with default profile

### Phase 2: Backend Services (Days 3-5)

**Tasks:**
1. Implement `ProfileService` with all CRUD operations
2. Implement `ConfigService` for AI infra, MLflow, prompts
3. Implement `ConfigValidator` with validation logic
4. Add endpoint listing functionality (Databricks API)
5. Implement configuration history tracking
6. Add transaction support for atomic operations

**Testing:**
- Unit tests for all service methods
- Test profile activation (single active constraint)
- Test profile duplication
- Test configuration updates with history tracking
- Test validation logic
- Test endpoint listing with custom sorting

**Deliverables:**
- Complete service layer
- All business logic functional
- Unit test coverage >80%

### Phase 3: API Endpoints (Days 6-7)

**Tasks:**
1. Implement all profile management endpoints
2. Implement AI infrastructure config endpoints
3. Implement MLflow config endpoints
4. Implement prompts config endpoints
5. Implement history endpoints
6. Add error handling and proper HTTP status codes
7. Add API documentation (OpenAPI/Swagger)

**Testing:**
- Integration tests for all endpoints
- Test authentication/authorization
- Test error handling
- Test concurrent access scenarios
- Test with Postman/curl

**Deliverables:**
- Complete REST API
- API documented
- Integration tests passing

### Phase 4: Application Settings Integration (Days 8-9)

**Tasks:**
1. Refactor `src/config/settings.py` to load from database
2. Remove YAML loading code
3. Implement `reload_settings()` with database fetch
4. Update `ChatService` to use database-backed settings
5. Add agent reinitialization on profile switch
6. Ensure backward compatibility during transition

**Testing:**
- Test settings loading from database
- Test settings reload without restart
- Test agent reinitialization with session preservation
- Test profile switching end-to-end

**Deliverables:**
- Application loads config from database
- YAML files removed from runtime path
- Hot-reload functional

### Phase 5: Frontend - Profile Management (Days 10-12)

**Tasks:**
1. Create `ConfigPanel` main container
2. Implement `ProfileSelector` component
3. Implement `ProfileManager` (create/edit/delete/duplicate)
4. Add profile switching functionality
5. Add UI state management
6. Integrate with backend API

**Testing:**
- Component tests
- Test profile CRUD operations
- Test profile switching
- Manual UI testing

**Deliverables:**
- Users can manage profiles via UI
- Profile switching works
- Clean UX with loading states

### Phase 6: Frontend - Configuration Forms (Days 13-15)

**Tasks:**
1. Implement `AIInfraForm` with all fields
   - Endpoint dropdown (Databricks endpoints)
   - Sliders for temperature/top_p
   - Number inputs for tokens/timeout
   - Genie space configuration
2. Implement `MLflowForm` with all fields
3. Implement `PromptsEditor` with Monaco editor
4. Add form validation
5. Add save/cancel/apply functionality

**Testing:**
- Component tests for each form
- Test validation (client + server)
- Test save operations
- Test apply & reload flow

**Deliverables:**
- Complete config editing UI
- All three config domains editable
- Validation working

### Phase 7: History & Polish (Days 16-17)

**Tasks:**
1. Implement `ConfigHistory` component
2. Add diff viewer for changes
3. Implement `ProfileCompare` (side-by-side comparison)
4. Add loading states and error handling
5. Polish UI/UX
6. Add tooltips and help text
7. Add keyboard shortcuts

**Testing:**
- Test history display
- Test profile comparison
- End-to-end workflow testing
- Usability testing

**Deliverables:**
- History viewer functional
- Profile comparison working
- Polished, production-ready UI

### Phase 8: Documentation & Deployment (Days 18-19)

**Tasks:**
1. Update technical documentation
2. Create user guide for config management
3. Create database migration guide
4. Update deployment documentation
5. Create video/screenshots for README
6. Test deployment to Databricks Apps
7. Performance testing

**Testing:**
- Deploy to dev environment
- Test with real Databricks workspace
- Load testing
- Multi-user testing

**Deliverables:**
- Complete documentation
- Deployment guide
- Ready for production

---

## Database Initialization

### First-Time Setup

When the application starts for the first time (empty database):

```python
# src/config/database_init.py

from src.config.defaults import DEFAULT_CONFIG

async def initialize_database():
    """Initialize database with default profile on first run."""
    from src.services.profile_service import ProfileService
    
    db = get_db_session()
    profile_service = ProfileService(db)
    
    # Check if any profiles exist
    existing = await profile_service.list_profiles()
    if len(existing) > 0:
        return  # Already initialized
    
    # Create default profile
    profile = ConfigProfile(
        name="default",
        description="Default configuration profile",
        is_default=True,
        created_by="system",
    )
    db.add(profile)
    db.flush()
    
    # Create AI infrastructure config
    ai_infra = ConfigAIInfra(
        profile_id=profile.id,
        llm_endpoint=DEFAULT_CONFIG["llm"]["endpoint"],
        llm_temperature=DEFAULT_CONFIG["llm"]["temperature"],
        llm_max_tokens=DEFAULT_CONFIG["llm"]["max_tokens"],
    )
    db.add(ai_infra)
    
    # Create default Genie space
    genie_space = ConfigGenieSpace(
        profile_id=profile.id,
        space_id=DEFAULT_CONFIG["genie"]["space_id"],
        space_name=DEFAULT_CONFIG["genie"]["space_name"],
        description=DEFAULT_CONFIG["genie"]["description"],
        is_default=True,
    )
    db.add(genie_space)
    
    # Create MLflow config
    mlflow = ConfigMLflow(
        profile_id=profile.id,
        experiment_name=DEFAULT_CONFIG["mlflow"]["experiment_name"],
    )
    db.add(mlflow)
    
    # Create prompts config
    prompts = ConfigPrompts(
        profile_id=profile.id,
        system_prompt=DEFAULT_CONFIG["prompts"]["system_prompt"],
        slide_editing_instructions=DEFAULT_CONFIG["prompts"]["slide_editing_instructions"],
        user_prompt_template=DEFAULT_CONFIG["prompts"]["user_prompt_template"],
    )
    db.add(prompts)
    
    db.commit()
```

### Default Configuration

```python
# src/config/defaults.py

DEFAULT_CONFIG = {
    "llm": {
        "endpoint": "databricks-claude-sonnet-4-5",
        "temperature": 0.7,
        "max_tokens": 60000,
    },
    "genie": {
        "space_id": "01effebcc2781b6bbb749077a55d31e3",
        "space_name": "Databricks Usage Analytics",
        "description": "Databricks usage data space",
    },
    "mlflow": {
        "experiment_name": "/Workspace/Users/{username}/ai-slide-generator",
    },
    "prompts": {
        "system_prompt": """You are an expert data analyst...""",  # Full default prompt
        "slide_editing_instructions": """SLIDE EDITING MODE:...""",  # Full editing instructions
        "user_prompt_template": "{question}",
    },
}
```

---

## Migration from YAML to Database

### Migration Script

For existing deployments with YAML files:

```python
# scripts/migrate_yaml_to_db.py

"""
Migrate existing YAML configuration to database.
Creates a profile named 'migrated_from_yaml' with current YAML values.
"""

import yaml
from pathlib import Path
from src.config.database import get_db_session
from src.models.config_profile import ConfigProfile
from src.models.config_ai_infra import ConfigAIInfra
from src.models.config_mlflow import ConfigMLflow
from src.models.config_prompts import ConfigPrompts

def migrate_yaml_to_database():
    """Migrate YAML configs to database."""
    
    # Load YAML files
    config_path = Path("config/config.yaml")
    mlflow_path = Path("config/mlflow.yaml")
    prompts_path = Path("config/prompts.yaml")
    
    with open(config_path) as f:
        config = yaml.safe_load(f)
    with open(mlflow_path) as f:
        mlflow_config = yaml.safe_load(f)
    with open(prompts_path) as f:
        prompts_config = yaml.safe_load(f)
    
    db = get_db_session()
    
    # Create profile
    profile = ConfigProfile(
        name="migrated_from_yaml",
        description="Configuration migrated from YAML files",
        is_default=True,  # Make this the default profile after migration
        created_by="migration_script",
    )
    db.add(profile)
    db.flush()
    
    # Migrate AI infra
    ai_infra = ConfigAIInfra(
        profile_id=profile.id,
        llm_endpoint=config["llm"]["endpoint"],
        llm_temperature=config["llm"]["temperature"],
        llm_max_tokens=config["llm"]["max_tokens"],
    )
    db.add(ai_infra)
    
    # Migrate Genie space
    genie_space = ConfigGenieSpace(
        profile_id=profile.id,
        space_id=config["genie"]["default_space_id"],
        space_name="Migrated Genie Space",  # Default name
        description=config["genie"].get("description", ""),
        is_default=True,
    )
    db.add(genie_space)
    
    # Migrate MLflow
    mlflow = ConfigMLflow(
        profile_id=profile.id,
        experiment_name=mlflow_config["tracking"]["experiment_name"],
    )
    db.add(mlflow)
    
    # Migrate prompts
    prompts = ConfigPrompts(
        profile_id=profile.id,
        system_prompt=prompts_config["system_prompt"],
        slide_editing_instructions=prompts_config["slide_editing_instructions"],
        user_prompt_template=prompts_config["user_prompt_template"],
    )
    db.add(prompts)
    
    db.commit()
    print(f"✓ Migrated YAML configuration to profile: {profile.name}")

if __name__ == "__main__":
    migrate_yaml_to_database()
```

---

## Testing Strategy

### Unit Tests

**Backend:**
- Profile service CRUD operations
- Config service get/update operations
- Validation logic (endpoints, prompts, parameters)
- Endpoint listing with custom sorting
- History tracking
- Database constraints

**Frontend:**
- Component rendering
- Form validation
- API client methods
- State management

### Integration Tests

**Backend:**
- Full API endpoint flows
- Profile activation with config reload
- Agent reinitialization
- Concurrent profile modifications
- Database transactions

**Frontend:**
- Form submission flows
- Profile switching
- Configuration saving and reloading
- Error handling

### End-to-End Tests

1. Create new profile
2. Modify AI infra settings
3. Activate profile
4. Generate slides (verify new settings used)
5. View history
6. Duplicate profile
7. Delete profile

### Performance Tests

- Load 100 profiles
- Rapid profile switching
- Concurrent config updates
- Large prompt texts (10KB+)
- History queries with 1000+ entries

---

## Security Considerations

### Authentication & Authorization

- All config endpoints require authentication
- Only authorized users can modify configurations
- Audit log tracks all changes with user identity
- Consider role-based access (admin vs. user)

### Data Validation

- Server-side validation for all inputs
- Prevent SQL injection via parameterized queries
- Validate prompt templates for malicious code
- Rate limiting on config changes

### Audit Logging

All configuration changes logged with:
- Timestamp
- User identity
- Profile affected
- Fields changed (before/after values)
- Full snapshot for rollback

---

## Deployment Considerations

### Database Setup

**Development:**
- PostgreSQL running locally or in Docker
- Connection string in `.env` file

**Production:**
- Managed PostgreSQL (AWS RDS, Azure Database, etc.)
- Or Databricks SQL warehouse (if supported)
- Connection pooling configured
- Backup and recovery strategy

### Environment Variables

```bash
# Required
DATABASE_URL=postgresql://user:pass@host:5432/dbname
DATABRICKS_HOST=https://....databricks.com
DATABRICKS_TOKEN=dapi...

# Optional
DATABASE_POOL_SIZE=10
DATABASE_MAX_OVERFLOW=20
```

### Database Migrations

Use Alembic for schema migrations:

```bash
# Initialize
alembic init alembic

# Create migration
alembic revision --autogenerate -m "Initial schema"

# Apply migrations
alembic upgrade head

# Rollback
alembic downgrade -1
```

### Initialization

On first deployment:
1. Run database migrations (`alembic upgrade head`)
2. Run initialization script (creates default profile)
3. Start application (loads from database)

---

## Success Criteria

**Must Have:**
- [ ] All configuration stored in PostgreSQL database
- [ ] No YAML file loading at runtime
- [ ] Users can create/edit/delete/activate profiles
- [ ] All three config domains editable (AI infra, MLflow, prompts)
- [ ] Configuration changes apply without restart
- [ ] Agent reinitializes with new settings
- [ ] Session state preserved during reload
- [ ] Configuration history viewable
- [ ] Endpoint dropdown populated from Databricks
- [ ] Validation prevents invalid configurations

**Should Have:**
- [ ] Profile duplication
- [ ] Profile comparison side-by-side
- [ ] Inline validation during editing
- [ ] Visual indicators for modified values
- [ ] Helpful tooltips and documentation
- [ ] Clean error messages
- [ ] Loading states and progress indicators

**Nice to Have:**
- [ ] Profile import/export (JSON)
- [ ] Bulk profile operations
- [ ] Configuration templates/presets
- [ ] Scheduled profile switching
- [ ] Profile-level permissions
- [ ] Dark mode support

---

## Dependencies

### Backend

```txt
# requirements.txt additions
sqlalchemy>=2.0.0
alembic>=1.12.0
psycopg2-binary>=2.9.0  # PostgreSQL adapter
asyncpg>=0.29.0  # Async PostgreSQL (optional)
```

### Frontend

```json
{
  "@monaco-editor/react": "^4.6.0",
  "date-fns": "^2.30.0"
}
```

---

## Estimated Timeline

**Total: 19 working days (3-4 weeks)**

- Phase 1: Database setup (2 days)
- Phase 2: Backend services (3 days)
- Phase 3: API endpoints (2 days)
- Phase 4: Settings integration (2 days)
- Phase 5: Frontend profiles (3 days)
- Phase 6: Frontend forms (3 days)
- Phase 7: History & polish (2 days)
- Phase 8: Documentation & deployment (2 days)

---

## Next Steps

1. Review and approve this plan
2. Set up PostgreSQL database (dev environment)
3. Create feature branch
4. Begin Phase 1: Database schema implementation
5. Incremental delivery and testing through phases
