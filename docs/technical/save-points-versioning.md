# Save Points / Versioning

**One-Line Summary:** Complete deck state snapshots (save points) that allow users to preview and restore previous versions, with verification results preserved.

---

## 1. Overview

Save Points provide version control for slide decks within a session. Each save point captures:
- Complete slide deck state (all slides, CSS, scripts)
- Verification results (LLM as Judge scores) at time of snapshot
- Auto-generated description of the change

Users can preview any save point without committing, then either revert (deleting newer versions) or cancel to return to the current state.

---

## 2. Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│                        Frontend (React)                              │
│  ┌──────────────────┐  ┌──────────────────┐  ┌───────────────────┐  │
│  │ SavePointDropdown │  │  PreviewBanner   │  │ RevertConfirmModal│  │
│  └────────┬─────────┘  └────────┬─────────┘  └─────────┬─────────┘  │
│           │                     │                      │             │
│           └──────────────┬──────┴──────────────────────┘             │
│                          │                                           │
│                    AppLayout (versionKey, previewVersion state)      │
└──────────────────────────┼───────────────────────────────────────────┘
                           │ API Calls
                           ▼
┌─────────────────────────────────────────────────────────────────────┐
│                        Backend (FastAPI)                             │
│  ┌────────────────────────────────────────────────────────────────┐ │
│  │ routes/slides.py - Version endpoints                           │ │
│  │   GET  /versions         - List all save points                │ │
│  │   GET  /versions/{n}     - Preview specific version            │ │
│  │   POST /versions/create  - Create new save point               │ │
│  │   POST /versions/{n}/restore - Restore and delete newer        │ │
│  └────────────────────────────────────────────────────────────────┘ │
│                          │                                           │
│  ┌────────────────────────────────────────────────────────────────┐ │
│  │ services/session_manager.py - Version CRUD operations          │ │
│  │   create_version(), list_versions(), get_version(),            │ │
│  │   restore_version(), VERSION_LIMIT = 40                        │ │
│  └────────────────────────────────────────────────────────────────┘ │
│                          │                                           │
│  ┌────────────────────────────────────────────────────────────────┐ │
│  │ database/models/session.py - SlideDeckVersion model            │ │
│  └────────────────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────────────┘
```

---

## 3. Database Model

```python
# src/database/models/session.py
class SlideDeckVersion(Base):
    """Save point for slide deck versioning."""
    __tablename__ = "slide_deck_versions"
    
    id = Column(Integer, primary_key=True)
    session_id = Column(Integer, ForeignKey("user_sessions.id", ondelete="CASCADE"))
    version_number = Column(Integer, nullable=False)
    description = Column(String(255), nullable=False)  # Auto-generated
    created_at = Column(DateTime, default=datetime.utcnow)
    
    deck_json = Column(Text, nullable=False)           # Complete deck snapshot
    verification_map_json = Column(Text, nullable=True) # Verification at time of snapshot
    
    session = relationship("UserSession", back_populates="versions")
```

**Table creation:** Automatic via SQLAlchemy's `Base.metadata.create_all()`. No manual migration needed.

---

## 4. Version Limit Behavior

- **Maximum:** 40 save points per session
- **Overflow:** When 41st is created, the oldest (Save Point 1) is deleted
- **Numbering:** Original numbers are kept (Save Points 2-41 exist after deletion, not renumbered)
- **Restore:** Restoring to version N deletes all versions > N

---

## 5. API Endpoints

| Method | Path | Purpose | Handler |
|--------|------|---------|---------|
| `GET` | `/api/slides/versions` | List all save points (newest first) | `routes/slides.list_versions` |
| `GET` | `/api/slides/versions/{n}` | Preview specific version (no DB changes) | `routes/slides.preview_version` |
| `POST` | `/api/slides/versions/create` | Create new save point | `routes/slides.create_version` |
| `POST` | `/api/slides/versions/{n}/restore` | Restore version, delete newer | `routes/slides.restore_version` |

### Request/Response Examples

**List versions:**
```json
GET /api/slides/versions?session_id=abc123

Response:
{
  "versions": [
    {"version_number": 5, "description": "Edited slide 2 (HTML)", "created_at": "...", "slide_count": 4},
    {"version_number": 4, "description": "Generated 4 slide(s)", "created_at": "...", "slide_count": 4}
  ],
  "current_version": 5
}
```

**Preview version:**
```json
GET /api/slides/versions/4?session_id=abc123

Response:
{
  "version_number": 4,
  "description": "Generated 4 slide(s)",
  "created_at": "...",
  "deck": { "title": "...", "slides": [...], "css": "...", ... },
  "verification_map": { "hash1": { "score": 95, "rating": "excellent" }, ... }
}
```

**Create save point:**
```json
POST /api/slides/versions/create
{ "session_id": "abc123", "description": "Edited slide 1 (HTML)" }

Response:
{ "version_number": 6, "description": "...", "created_at": "...", "slide_count": 4 }
```

**Restore version:**
```json
POST /api/slides/versions/4/restore
{ "session_id": "abc123" }

Response:
{
  "version_number": 4,
  "description": "Generated 4 slide(s)",
  "deck": { ... },
  "verification_map": { ... },
  "deleted_versions": 2  // v5 and v6 were deleted
}
```

---

## 6. Frontend Components

| Component | Path | Responsibility |
|-----------|------|----------------|
| `SavePointDropdown` | `frontend/src/components/SavePoints/SavePointDropdown.tsx` | Dropdown showing all versions, handles preview selection |
| `PreviewBanner` | `frontend/src/components/SavePoints/PreviewBanner.tsx` | Indigo banner with "Revert" and "Cancel" buttons |
| `RevertConfirmModal` | `frontend/src/components/SavePoints/RevertConfirmModal.tsx` | Confirmation dialog before deleting newer versions |

### State Management (AppLayout.tsx)

```typescript
// Save Points / Versioning state
const [versions, setVersions] = useState<SavePointVersion[]>([]);
const [currentVersion, setCurrentVersion] = useState<number | null>(null);
const [previewVersion, setPreviewVersion] = useState<number | null>(null);
const [previewDeck, setPreviewDeck] = useState<SlideDeck | null>(null);

// Version key for forcing re-render when switching versions
const versionKey = previewVersion 
  ? `preview-v${previewVersion}` 
  : `current-v${currentVersion || 'live'}`;

// Determine which deck to display
const displayDeck = previewVersion ? previewDeck : slideDeck;
```

The `versionKey` is passed to slide rendering components to force React to recreate elements when switching between versions, preventing stale state from persisting.

---

## 7. User Flow

### Preview and Restore Flow

```
User has 10 save points, viewing Save Point 10 (current)

Step 1: User selects Save Point 5 from dropdown
Step 2: Frontend calls GET /versions/5/preview
Step 3: Slides panel shows Save Point 5's deck (PREVIEW MODE)
        - PreviewBanner appears (indigo theme)
        - "Revert to This Version" and "Cancel Preview" buttons
        - Chat input disabled
        - Slide editing disabled
        - NO database changes yet

Step 4a: User clicks "Revert to This Version"
         → Confirmation modal: "Save Points 6-10 will be permanently deleted"
         → User confirms
         → POST /versions/5/restore
         → Save Point 5 becomes current, SP 6-10 deleted
         → Dropdown shows SP 1-5 only

Step 4b: User clicks "Cancel Preview"
         → Returns to Save Point 10 view
         → No changes made
```

### Save Point Creation Triggers

Save points are created automatically after:
- Slide generation (via chat)
- Slide editing (HTML edit in panel)
- Slide deletion
- Slide duplication
- Slide reordering

**Timing:** Save points are created AFTER auto-verification completes, ensuring verification results are captured.

---

## 8. Verification Persistence

Each save point captures the `verification_map` at the time of creation:
- Verification results are keyed by content hash (SHA256 of normalized HTML)
- When previewing/restoring, verification badges reflect that version's state
- This allows comparison of verification status across versions

---

## 9. Implementation Notes

### Slide ID Consistency

When adding slides in the middle of a deck, all slide IDs must be updated to prevent duplicate React keys:

```python
# After inserting new slides
for idx, slide in enumerate(current_deck.slides):
    slide.slide_id = f"slide_{idx}"
```

This ensures unique keys like `slide_0`, `slide_1`, etc., preventing React rendering issues.

### Cache Invalidation

On restore, the in-memory deck cache is invalidated:
```python
def restore_version(self, session_id: str, version_number: int):
    # ... restore logic ...
    # Clear cache to force reload
    with self._cache_lock:
        if session_id in self._deck_cache:
            del self._deck_cache[session_id]
```

---

## 10. Cross-References

- [Backend Overview](backend-overview.md) - API surface and session management
- [Frontend Overview](frontend-overview.md) - UI components and state management
- [Database Configuration](database-configuration.md) - Schema details
- [Slide Editing Robustness](slide-editing-robustness-fixes.md) - Related deck preservation guards
