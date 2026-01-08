# Profile Switch Flow - Genie Configuration Update

This document traces the complete flow of a profile switch and how it affects Genie space configuration.

## Overview

When a user switches profiles, the system:
1. Loads new configuration from database (including new Genie space ID)
2. Reloads the agent with new settings
3. **Preserves** existing Genie conversation IDs (each session tracks its `profile_id`)
4. Initializes new Genie conversations only for new sessions in the new space

### Key Behavior (Updated)

- **Sessions track their profile:** Each session stores `profile_id` and `profile_name`
- **Genie IDs persist:** Switching profiles does NOT clear Genie conversation IDs
- **Auto-switch on restore:** Restoring a session from a different profile auto-switches to that profile
- **Profile shown in history:** Session history displays which profile each session belongs to

---

## Step-by-Step Flow

### 1. Frontend: User Selects Profile

**File:** `frontend/src/components/config/ProfileSelector.tsx`

```typescript
const handleLoadProfile = async (profileId: number) => {
  setIsLoading(true);
  try {
    await loadProfile(profileId);  // ← Calls ProfileContext function
    setIsOpen(false);
    // Notify parent to reset chat state
    if (onProfileChange) {
      onProfileChange();
    }
  }
}
```

**What happens:**
- User clicks on a profile in the dropdown
- Frontend calls `loadProfile(profileId)` from ProfileContext

---

### 2. Frontend Context: Load Profile API Call

**File:** `frontend/src/contexts/ProfileContext.tsx`

```typescript
const loadProfile = useCallback(async (id: number): Promise<void> => {
  try {
    setError(null);
    
    // Call load profile endpoint (triggers hot-reload on backend)
    const response = await configApi.loadProfile(id);  // ← API call
    
    console.log('Profile loaded:', response);
    
    // Track this as the loaded profile
    setLoadedProfileId(id);
    
    // Update current profile
    const profile = profiles.find(p => p.id === id);
    if (profile) {
      setCurrentProfile(profile);
    }
  }
}, [profiles, loadProfiles]);
```

**What happens:**
- Calls backend API endpoint: `POST /api/profiles/{id}/load`

---

### 3. Frontend API Layer

**File:** `frontend/src/api/config.ts`

```typescript
loadProfile: (id: number): Promise<ReloadResponse> =>
  fetchJson(`${API_BASE}/profiles/${id}/load`, {
    method: 'POST',
  }),
```

**What happens:**
- Makes HTTP POST request to backend

---

### 4. Backend API Endpoint: Load Profile

**File:** `src/api/routes/config/profiles.py`

```python
@router.post("/{profile_id}/load", response_model=Dict[str, Any])
def load_profile(
    profile_id: int,
    service: ProfileService = Depends(get_profile_service),
    chat_service: ChatService = Depends(get_chat_service),
):
    """
    Load a specific profile configuration.
    
    This performs a hot-reload of the application configuration from the database,
    updating the LLM, Genie, MLflow, and prompts settings to match the specified profile.
    """
    # Verify profile exists
    profile = service.get_profile(profile_id)
    if not profile:
        raise HTTPException(status_code=404, detail=f"Profile {profile_id} not found")
    
    logger.info(
        "Loading profile configuration",
        extra={"profile_id": profile_id, "profile_name": profile.name},
    )
    
    # Reload agent with new profile
    result = chat_service.reload_agent(profile_id)  # ← KEY CALL
    
    return result
```

**What happens:**
- Validates profile exists
- Calls `chat_service.reload_agent(profile_id)` to reload the agent

---

### 5. Backend Chat Service: Reload Agent

**File:** `src/api/services/chat_service.py`

```python
def reload_agent(self, profile_id: Optional[int] = None) -> Dict[str, Any]:
    """Reload agent with new settings from database.
    
    Genie conversation IDs are PRESERVED - each session tracks its profile_id
    and the genie_conversation_id remains valid for that profile's Genie space.
    """
    with self._reload_lock:
        # 1. Reload settings from database
        from src.core.settings_db import reload_settings
        new_settings = reload_settings(profile_id)  # ← RELOADS SETTINGS CACHE

        logger.info(
            "Loaded new settings",
            extra={
                "profile_id": new_settings.profile_id,
                "genie_space_id": new_settings.genie.space_id,  # ← NEW SPACE ID
            },
        )

        # NOTE: Genie conversation IDs are NO LONGER cleared on profile switch.
        # Each session stores its profile_id, so the genie_conversation_id
        # remains valid when the user switches back to that profile.

        # 2. Create new agent with new settings
        new_agent = create_agent()  # ← CREATES NEW AGENT

        # 3. Atomic swap
        self.agent = new_agent

        # 4. Clear deck cache (settings may affect rendering)
        with self._cache_lock:
            self._deck_cache.clear()

        return {
            "status": "reloaded",
            "profile_id": new_settings.profile_id,
        }
```

**What happens:**
1. **Reloads settings from database** (including new Genie space ID)
2. **Creates new agent** with new settings
3. Swaps old agent with new agent
4. **Genie conversation IDs are PRESERVED** in the database (per-session)

---

### 6. Settings Reload: Update Cache

**File:** `src/config/settings_db.py`

```python
# Global cache for settings
@lru_cache(maxsize=1)
def get_settings() -> AppSettings:
    """Get the application settings singleton (database-backed)."""
    return load_settings_from_database()

def reload_settings(profile_id: Optional[int] = None) -> AppSettings:
    """Reload settings from database."""
    logger.info("Reloading settings from database", extra={"profile_id": profile_id})
    
    # Store the active profile ID globally BEFORE clearing cache
    if profile_id is not None:
        global _active_profile_id
        _active_profile_id = profile_id  # ← SET NEW ACTIVE PROFILE
        logger.info(f"Set active profile ID to {profile_id}")
    
    # Clear the cache
    get_settings.cache_clear()  # ← CLEAR OLD SETTINGS
    
    # Force immediate cache repopulation by calling get_settings()
    settings = get_settings()  # ← RELOAD FROM DATABASE
    
    logger.info(
        "Settings reloaded successfully",
        extra={
            "profile_id": settings.profile_id,
            "genie_space_id": settings.genie.space_id,  # ← NEW SPACE ID
        },
    )
    
    return settings
```

**What happens:**
1. Sets `_active_profile_id` to the new profile ID
2. **Clears the LRU cache** (`get_settings.cache_clear()`)
3. **Immediately calls `get_settings()`** to repopulate cache with new profile settings
4. Returns new settings with **new Genie space ID**

---

### 7. Database Settings Loader

**File:** `src/config/settings_db.py`

```python
def load_settings_from_database(profile_id: Optional[int] = None) -> AppSettings:
    """Load settings from database profile."""
    global _active_profile_id
    
    with get_db_session() as db:
        # Get profile (priority: specified > active > default)
        if profile_id is None and _active_profile_id is not None:
            profile = db.query(ConfigProfile).filter_by(id=_active_profile_id).first()
        elif profile_id is None:
            profile = db.query(ConfigProfile).filter_by(is_default=True).first()
        else:
            profile = db.query(ConfigProfile).filter_by(id=profile_id).first()
        
        # Get the Genie space for this profile (one per profile)
        genie_space = db.query(ConfigGenieSpace).filter_by(
            profile_id=profile.id
        ).first()
        
        # ... load other configs ...
        
        # Create settings
        genie_settings = GenieSettings(
            space_id=genie_space.space_id,       # ← NEW SPACE ID
            space_name=genie_space.space_name,
            description=genie_space.description or "",
        )
        
        return AppSettings(
            profile_id=profile.id,
            profile_name=profile.name,
            genie=genie_settings,  # ← NEW GENIE SETTINGS
            # ... other settings ...
        )
```

**What happens:**
1. Queries database for the specified profile
2. Loads **Genie space configuration** from database (new space ID)
3. Creates `AppSettings` object with new Genie settings
4. Returns to `reload_settings()` which caches it

---

### 8. Agent Creation: Use New Settings

**File:** `src/services/agent.py`

```python
class SlideGeneratorAgent:
    def __init__(self):
        """Initialize agent with LangChain model and tools."""
        logger.info("Initializing SlideGeneratorAgent")
        
        self.settings = get_settings()  # ← GETS CACHED SETTINGS (NEW PROFILE)
        self.client = get_databricks_client()
        
        # Create LangChain components
        self.model = self._create_model()
        self.tools = self._create_tools()  # ← Creates tools with NEW settings
        # ...
```

**What happens:**
1. **Calls `get_settings()`** which returns the **newly cached settings**
2. Stores new settings in `self.settings`
3. Creates tools with new settings (including Genie tool)

---

### 9. Tool Execution: Query New Genie Space

**File:** `src/services/agent.py` (inside `_create_tools`)

```python
def _query_genie_wrapper(query: str) -> str:
    """Wrapper that auto-injects conversation_id from current session."""
    # Get conversation_id from current session
    session = self.sessions.get(self.current_session_id)
    
    conversation_id = session["genie_conversation_id"]
    if conversation_id is None:
        # Initialize new Genie conversation (happens after profile reload)
        logger.info("Initializing new Genie conversation for session")
        conversation_id = initialize_genie_conversation()  # ← NEW CONVERSATION
        session["genie_conversation_id"] = conversation_id
    
    # Query Genie with automatic conversation_id
    result = query_genie_space(query, conversation_id)  # ← QUERIES NEW SPACE
    
    return f"Data retrieved successfully:\n\n{result['data']}"
```

**What happens:**
1. Checks if Genie conversation exists for current session
2. If `None` (cleared during reload), **initializes new conversation**
3. Calls `query_genie_space()` which uses **new settings**

---

### 10. Genie Tool Functions: Use New Space ID

**File:** `src/services/tools.py`

```python
def initialize_genie_conversation(
    placeholder_message: str = "This is a system message to start a conversation.",
) -> str:
    """Initialize a Genie conversation with a placeholder message."""
    client = get_databricks_client()
    settings = get_settings()  # ← GETS NEW CACHED SETTINGS
    space_id = settings.genie.space_id  # ← NEW SPACE ID
    
    try:
        response = client.genie.start_conversation_and_wait(
            space_id=space_id,  # ← USES NEW SPACE ID
            content=placeholder_message
        )
        return response.conversation_id
    except Exception as e:
        raise GenieToolError(f"Failed to initialize Genie conversation: {e}")

def query_genie_space(
    query: str,
    conversation_id: Optional[str] = None,
    max_retries: int = 2,
) -> dict[str, Any]:
    """Query Databricks Genie space for data."""
    client = get_databricks_client()
    settings = get_settings()  # ← GETS NEW CACHED SETTINGS
    space_id = settings.genie.space_id  # ← NEW SPACE ID
    
    # ... query logic ...
    response = client.genie.start_conversation_and_wait(
        space_id=space_id,  # ← USES NEW SPACE ID
        content=query
    )
    # ... return results ...
```

**What happens:**
1. Both functions call `get_settings()`
2. **CRITICAL:** This should return the **new cached settings**
3. Extracts `space_id` from new settings
4. Uses new space ID for all Genie API calls

---

## The Problem: Why It Might Not Be Working

### Potential Issue: Settings Cache Not Updating Properly

The flow should work, but there might be a cache synchronization issue:

```python
# In reload_settings():
get_settings.cache_clear()  # ← Clear cache
settings = get_settings()   # ← Repopulate cache

# Later in tools:
settings = get_settings()   # ← Should get NEW settings from cache
```

### Debugging Steps

1. **Add logging to verify space ID changes:**

```python
# In initialize_genie_conversation():
logger.info(f"Using Genie space ID: {space_id}")

# In query_genie_space():
logger.info(f"Querying Genie space ID: {space_id}")
```

2. **Verify cache is actually cleared:**

```python
# In reload_settings(), after cache_clear():
logger.info("Cache cleared, cache info before reload: " + str(get_settings.cache_info()))
settings = get_settings()
logger.info("Cache info after reload: " + str(get_settings.cache_info()))
```

3. **Check if tools are getting old settings:**

```python
# In tools.py, at the top:
logger.info(f"get_settings cache info: {get_settings.cache_info()}")
settings = get_settings()
logger.info(f"Current active profile: {settings.profile_id}, space: {settings.genie.space_id}")
```

---

## Session-Profile Association (Implemented)

### How It Works

Each session now tracks:
- `profile_id`: The profile the session was created under
- `profile_name`: Cached for display in session history

**Database Model** (`UserSession`):
```python
profile_id = Column(Integer, nullable=True, index=True)
profile_name = Column(String(255), nullable=True)
genie_conversation_id = Column(String(255), nullable=True)  # Persists!
```

### Auto-Profile Switch on Session Restore

When restoring a session from history:
1. Frontend checks if session's `profile_id` differs from current profile
2. If different, calls `loadProfile(session.profile_id)` first
3. Then restores the session with its preserved Genie conversation

**Frontend Logic** (`AppLayout.tsx`):
```typescript
const handleSessionRestore = async (restoredSessionId: string) => {
  const sessionInfo = await api.getSession(restoredSessionId);
  
  // Auto-switch profile if needed
  if (sessionInfo.profile_id && currentProfile && sessionInfo.profile_id !== currentProfile.id) {
    await loadProfile(sessionInfo.profile_id);
  }
  
  // Restore session (Genie ID is preserved!)
  await switchSession(restoredSessionId);
};
```

### Session History Display

Session history now shows a "Profile" column before the session name, making it clear which profile each session belongs to.

---

## Expected Flow Summary

✅ **Current Flow:**
1. User switches profile → API call → `reload_agent(profile_id)`
2. `reload_settings(profile_id)` clears cache and reloads from DB
3. New agent created with `create_agent()`
4. **Genie conversation IDs are PRESERVED** (no clearing)
5. New sessions are associated with the new profile
6. Restoring old session → auto-switches to its original profile
7. Genie conversation ID works because profile matches

### Example Scenario

1. User on Profile "KPMG", creates Session-A → gets genie_conversation_id_A
2. User switches to Profile "Cadence", creates Session-B → gets genie_conversation_id_B
3. User switches back to "KPMG"
4. User restores Session-A from history:
   - Frontend detects Session-A belongs to KPMG
   - Auto-switches to KPMG profile (if not already)
   - Session-A's genie_conversation_id_A still works ✅
5. User can view source data, continue conversation

---

## Debugging

### Verify Profile Association

```python
# Check session's profile in database
SELECT session_id, title, profile_id, profile_name, genie_conversation_id 
FROM user_sessions 
ORDER BY last_activity DESC;
```

### Verify Genie IDs Persist

After switching profiles, run:
```sql
-- Should NOT be NULL for sessions with Genie queries
SELECT session_id, profile_name, genie_conversation_id 
FROM user_sessions 
WHERE genie_conversation_id IS NOT NULL;
```

