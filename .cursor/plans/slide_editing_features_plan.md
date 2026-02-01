---
name: Slide Editing Features
overview: Fix HTML edit chart bug, implement save points versioning (which fundamentally resolves sync issues), and replace regex intent detection with LLM classifier with multi-intent support.
todos:
  - id: git-sync
    content: Pull latest main, full codebase scan for any changes since last session
    status: completed
  - id: bug1-html-edit
    content: Fix update_slide() to preserve original slide scripts when editing HTML
    status: completed
  - id: versioning-db-model
    content: Create SlideDeckVersion database model (auto-created by SQLAlchemy, 40-version limit, includes verification_map)
    status: completed
  - id: versioning-backend
    content: Add version management API (list, preview, restore), create save point AFTER verification, cache invalidation on restore
    status: completed
  - id: versioning-frontend
    content: Create SavePointDropdown with preview, rollback button in chat, confirmation modal, preview/restore flow
    status: completed
  - id: versionkey-fix
    content: Fix React key collision causing duplicate slides when previewing versions (added versionKey prop)
    status: completed
  - id: slideid-duplication-fix
    content: Fix slide_id duplication when adding slides mid-deck (re-index all IDs after insertion)
    status: completed
  - id: llm-classifier
    content: Implement LLM-based intent classifier with multi-intent support, safety rules, selection handling
    status: pending
  - id: llm-integration
    content: Replace all regex intent detection, implement all intent types (EDIT/DELETE/DUPLICATE/ADD/REORDER/GENERATE)
    status: pending
  - id: testing
    content: Comprehensive unit and integration tests for versioning, intent classifier, multi-intent, and script preservation
    status: pending
  - id: docs-update
    content: Review and update technical docs (docs/technical/) to reflect new versioning and intent classifier features
    status: completed
isProject: false
---

# Slide Editing Features and Fixes Plan

## Git Strategy

Work locally on main until everything is ready, then create a fresh branch.

```bash
# 1. Pull latest main
git checkout main
git pull origin main

# 2. FULL SCAN - Check for any changes since last session
#    - Review any new files or modifications
#    - Check if any of our target files changed
#    - Identify any conflicts with our planned changes

# 3. Work locally on main (don't push to main)
# ... make all changes, test everything ...

# 4. When happy, create fresh branch and push
git checkout -b ty-feat/slide-editing-v2
git push -u origin ty-feat/slide-editing-v2

# 4. Open PR to main
```

**Files preserved during pull:**

- `.env` - In `.gitignore`, stays untouched
- Plan file - In `~/.cursor/plans/`, outside git repo

---

## Bug 1: HTML Edit Losing Chart Scripts

**Root Cause:** In `update_slide()` ([chat_service.py:2032](src/api/services/chat_service.py)), new `Slide` created without scripts.

**Fix:**

```python
def update_slide(self, session_id: str, index: int, html: str) -> Dict[str, Any]:
    current_deck = self._get_or_load_deck(session_id)
    # ... validation ...
    
    # Preserve original slide's scripts
    original_scripts = current_deck.slides[index].scripts
    
    # Update slide with preserved scripts
    current_deck.slides[index] = Slide(
        html=html, 
        slide_id=f"slide_{index}",
        scripts=original_scripts  # Preserve charts
    )
```

**Files to modify:**

- [src/api/services/chat_service.py](src/api/services/chat_service.py) - `update_slide()` method

---

## Feature 2: Save Points / Versioning

### Core Principle

Each save point stores **COMPLETE deck state + verification**. Created AFTER verification completes.

### Version Limit Behavior

- Maximum 40 save points per session
- When 41st is created, oldest (Save Point 1) is deleted
- **Keep original numbers** (Save Points 2-41 exist after deletion, not renumbered)

### Database Model

```python
# In src/database/models/session.py
class SlideDeckVersion(Base):
    """Save point for slide deck versioning.
    
    Separate table from session history - does not affect user_sessions or config_profiles.
    """
    __tablename__ = "slide_deck_versions"
    
    id = Column(Integer, primary_key=True)
    session_id = Column(Integer, ForeignKey("user_sessions.id", ondelete="CASCADE"))
    version_number = Column(Integer, nullable=False)
    description = Column(String(255), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    
    deck_json = Column(Text, nullable=False)
    verification_map_json = Column(Text, nullable=True)
    
    session = relationship("UserSession")
    
    __table_args__ = (
        Index("ix_deck_versions_session_version", "session_id", "version_number"),
    )
```

**Table creation:** Automatic via SQLAlchemy's `Base.metadata.create_all()`. No manual migration needed.

### Backend API

```python
@router.get("/versions")
async def list_versions(session_id: str) -> List[SavePoint]:
    """List all save points (max 40, newest first)."""

@router.get("/versions/{version_number}/preview")
async def preview_version(version_number: int, session_id: str) -> PreviewResult:
    """Preview deck state - NO changes to DB. For viewing before deciding to restore."""

@router.post("/versions/{version_number}/restore")
async def restore_version(version_number: int, session_id: str) -> RestoreResult:
    """COMMIT restore - updates current state and DELETES newer versions."""

@router.get("/versions/current")
async def get_current_version(session_id: str) -> int:
    """Get current (latest) version number."""
```

### Frontend UX - Preview and Restore Flow

```
User has 10 save points, viewing Save Point 10 (current)

Step 1: User selects Save Point 5 from dropdown
Step 2: Frontend calls GET /versions/5/preview
Step 3: Slides panel shows Save Point 5's deck (PREVIEW MODE)
        - PreviewBanner appears with "Cancel" and "Revert to this version"
        - NO database changes yet

Step 4a: User clicks "Revert to this version"
         → Confirmation modal: "Save Points 6-10 will be permanently deleted"
         → User confirms
         → POST /versions/5/restore
         → Save Point 5 becomes current, SP 6-10 deleted
         → Dropdown shows SP 1-5 only

Step 4b: User clicks "Cancel"
         → Returns to Save Point 10 view
         → No changes made
```

### Files to Create/Modify

**Backend:**

- [src/database/models/session.py](src/database/models/session.py) - Add `SlideDeckVersion` model
- [src/api/routes/slides.py](src/api/routes/slides.py) - Add version endpoints
- [src/api/services/chat_service.py](src/api/services/chat_service.py) - Add save point methods

**Frontend:**

- `frontend/src/components/SavePoints/SavePointDropdown.tsx`
- `frontend/src/components/SavePoints/PreviewBanner.tsx`
- `frontend/src/components/SavePoints/RevertConfirmModal.tsx`
- `frontend/src/components/SavePoints/RollbackPrompt.tsx`
- `frontend/src/components/Layout/AppLayout.tsx` - Integrate preview/restore
- `frontend/src/services/api.ts` - Add version API calls

---

## Feature 3: LLM Intent Classifier

### Replace Regex Methods

Remove from `chat_service.py`:

- `_detect_add_intent()`
- `_detect_edit_intent()`
- `_detect_generation_intent()`
- `_detect_explicit_replace_intent()`
- `_detect_add_position()`

Remove from `agent.py`:

- `_detect_add_intent()` (duplicate)

### Multi-Intent Support

**The LLM can detect and return multiple intents from a single message.**

**Example:** "Delete slide 2 and add a summary slide"

```json
{
  "intents": [
    {"intent": "DELETE", "slide_refs": [2], "confidence": 0.95},
    {"intent": "ADD", "position": "end", "description": "summary slide", "confidence": 0.92}
  ]
}
```

### Intent Types


| Intent    | Description              | Save Points                  |
| --------- | ------------------------ | ---------------------------- |
| GENERATE  | Create new presentation  | 1 (for entire deck)          |
| ADD       | Add new slide(s)         | 1 (even if multiple targets) |
| EDIT      | Modify existing slide(s) | 1 (even if multiple targets) |
| DELETE    | Remove slide(s)          | 1 (even if multiple targets) |
| DUPLICATE | Copy slide(s)            | 1 (even if multiple targets) |
| REORDER   | Move slides              | 1                            |
| CLARIFY   | Need more information    | N/A                          |
| OTHER     | General chat             | N/A                          |


**Save Point Rule:**

- Multiple targets in ONE action = 1 save point ("Delete slides 2, 3, 4" = 1 save point)
- Multiple ACTIONS = multiple save points ("Delete slide 2 AND add summary" = 2 save points)

### Selection Behavior


| Intent Type | Selection Used For | Behavior                                                |
| ----------- | ------------------ | ------------------------------------------------------- |
| EDIT        | **Target**         | Edit selected slide(s), notify if text ref differs      |
| DELETE      | **Target**         | Delete selected slide(s), notify if text ref differs    |
| DUPLICATE   | **Target**         | Duplicate selected slide(s), notify if text ref differs |
| ADD         | **Position**       | Add after/before selected slide                         |
| REORDER     | No                 | Needs explicit "move X to Y" instructions               |
| GENERATE    | No                 | Creates new deck, selection irrelevant                  |


**Selection Priority:**

1. User has selection + intent has NO text ref → Use selection
2. User has selection + intent HAS text ref (different) → **Selection wins**, notify user
3. User has selection + intent HAS text ref (same) → Use it, no notification
4. User has NO selection + intent has text ref → Use text ref
5. User has NO selection + intent has NO ref → CLARIFY

**ADD Position Priority:**

1. Explicit in text: "add after slide 5" → after slide 5
2. Selection + relative: "add after this" → after selected slide
3. Selection, no position specified → after selected slide (default)
4. No selection, no position → at end (default)

### Safety Rules (Hardcoded)

```python
# Applied to EACH intent, BEFORE any execution

# Rule 1: GENERATE with existing deck → CLARIFY
if intent == "GENERATE" and has_existing_deck:
    if no_explicit_replace_keywords:  # "replace", "start fresh", "new deck", etc.
        return CLARIFY("You have N slides. ADD new slides or REPLACE entire deck?")

# Rule 2: EDIT without target and no selection → CLARIFY
if intent == "EDIT" and no_slide_refs and no_selection:
    return CLARIFY("Which slide would you like to edit?")

# Rule 3: DELETE without target and no selection → CLARIFY
if intent == "DELETE" and no_slide_refs and no_selection:
    return CLARIFY("Which slide(s) would you like to delete?")

# Rule 4: REORDER without clear instructions → CLARIFY
if intent == "REORDER" and unclear_move_instructions:
    return CLARIFY("Which slide to move and where?")

# Rule 5: DUPLICATE without target and no selection → CLARIFY
if intent == "DUPLICATE" and no_slide_refs and no_selection:
    return CLARIFY("Which slide would you like to duplicate?")

# Rule 6: Invalid slide references → CLARIFY
if any_slide_ref > slide_count or any_slide_ref < 1:
    return CLARIFY(f"Slide {ref} doesn't exist. You have {slide_count} slides.")

# Rule 7: Low confidence → CLARIFY
if confidence < 0.7:
    return CLARIFY("Could you please clarify what you'd like me to do?")
```

### Multi-Intent Validation (All-or-Nothing)

**Before executing ANY intent, validate ALL of them:**

```python
def validate_all_intents(intents, context):
    slides_to_delete = set()
    
    for i, intent in enumerate(intents):
        # 1. Apply standard safety rules
        validated = apply_safety_rules(intent, context)
        if validated.intent == "CLARIFY":
            return ("CLARIFY", f"For action {i+1}: {validated.reasoning}")
        
        # 2. Check for conflicts with previous intents
        if intent.intent in ["EDIT", "DUPLICATE"]:
            for ref in intent.slide_refs:
                if ref in slides_to_delete:
                    return ("CONFLICT", f"Can't {intent.intent.lower()} slide {ref} - it's being deleted")
        
        # 3. Track deletions
        if intent.intent == "DELETE":
            slides_to_delete.update(intent.slide_refs)
    
    return ("VALID", None)
```

**Conflict Examples:**


| Message                                | Validation | Result                                         |
| -------------------------------------- | ---------- | ---------------------------------------------- |
| "Delete slide 2 and edit slide 3"      | Valid      | Execute both                                   |
| "Delete slide 2 and edit slide 2"      | CONFLICT   | "Can't edit slide 2 - it's being deleted"      |
| "Delete slide 2 and duplicate slide 2" | CONFLICT   | "Can't duplicate slide 2 - it's being deleted" |


### Multi-Intent Execution

```python
async def execute_intents(intents, session_id, context):
    # Validation already passed
    
    for i, intent in enumerate(intents):
        # Progress feedback
        yield f"Action {i+1}/{len(intents)}: {intent.description}..."
        
        # Execute this intent
        result = await execute_single_intent(intent, session_id, context)
        
        # Create save point
        create_save_point(session_id, f"{intent.intent}: {intent.description}")
        
        # Update context for next intent (slide indices may have changed)
        context = update_context_after_execution(context, intent, result)
    
    yield f"Completed {len(intents)} action(s)!"
```

**Index Handling:** Use **original indices** (user's view when they sent the message). Track internally what each original index maps to after deletions/additions.

### Limit

**Maximum 10 intents per message.** If more detected, return CLARIFY: "That's a lot of changes! Let's do them in smaller batches."

### Classification Prompt

```python
INTENT_CLASSIFICATION_PROMPT = """You are an intent classifier for a slide presentation application.

CONTEXT:
- User has existing deck: {has_deck} ({slide_count} slides)
- User has selected slides in UI: {has_selection}
- Selected slide indices: {selected_indices}

USER MESSAGE:
"{message}"

DETECT ALL intents in the message. Return as array.

INTENT TYPES:
- GENERATE: Create completely new presentation
- ADD: Add new slide(s) to existing deck
- EDIT: Modify existing slide(s) - color, text, layout, etc.
- DELETE: Remove slide(s)
- REORDER: Change slide order
- DUPLICATE: Copy slide(s)
- CLARIFY: Intent is unclear
- OTHER: Not slide-related (general chat)

RESPOND IN JSON:
{
  "intents": [
    {
      "intent": "DELETE",
      "confidence": 0.95,
      "slide_refs": [2],
      "position": null,
      "description": "delete slide 2"
    },
    {
      "intent": "ADD", 
      "confidence": 0.92,
      "slide_refs": [],
      "position": "end",
      "description": "add summary slide at end"
    }
  ],
  "reasoning": "User wants to delete slide 2 and add a summary"
}

RULES:
- Return array even for single intent
- slide_refs are 1-indexed (user's perspective)
- For ADD: position can be "beginning", "end", "after N", "before N"
- Maximum 10 intents - if more, return single CLARIFY intent
- If user has selection and says "this slide", use selection context
"""
```

### Files to Create/Modify

- [src/services/intent_classifier.py](src/services/intent_classifier.py) - New LLM classifier
- [src/core/defaults.py](src/core/defaults.py) - Add classification prompt
- [src/api/services/chat_service.py](src/api/services/chat_service.py) - Replace regex, multi-intent execution
- [src/services/agent.py](src/services/agent.py) - Remove duplicate methods

---

## Comprehensive Test Plan

### Test File: `tests/unit/test_save_points.py`

```python
class TestSavePointCreation:
    def test_save_point_after_generation(self): ...
    def test_save_point_after_edit(self): ...
    def test_save_point_after_delete(self): ...
    def test_save_point_includes_verification(self): ...
    def test_version_numbers_increment(self): ...

class TestSavePointPreview:
    def test_preview_returns_deck_without_modifying(self): ...
    def test_preview_includes_verification(self): ...

class TestSavePointRestore:
    def test_restore_updates_current_deck(self): ...
    def test_restore_deletes_newer_versions(self): ...
    def test_restore_preserves_verification(self): ...
    def test_cache_invalidated_on_restore(self): ...

class TestVersionLimit:
    def test_40_limit_enforced(self): ...
    def test_oldest_deleted_keeps_original_numbers(self): ...
```

### Test File: `tests/unit/test_intent_classifier.py`

```python
class TestSingleIntent:
    def test_edit_classification(self): ...
    def test_delete_classification(self): ...
    def test_add_classification(self): ...
    def test_generate_classification(self): ...

class TestMultiIntent:
    def test_two_intents_detected(self): ...
    def test_three_intents_detected(self): ...
    def test_max_10_intents_enforced(self): ...

class TestSafetyRules:
    def test_generate_with_deck_clarifies(self): ...
    def test_edit_without_target_clarifies(self): ...
    def test_delete_without_target_clarifies(self): ...
    def test_duplicate_without_target_clarifies(self): ...
    def test_invalid_slide_ref_clarifies(self): ...
    def test_low_confidence_clarifies(self): ...

class TestConflictDetection:
    def test_delete_then_edit_same_slide_conflicts(self): ...
    def test_delete_then_edit_different_slide_valid(self): ...
    def test_delete_then_duplicate_same_slide_conflicts(self): ...

class TestSelectionBehavior:
    def test_selection_overrides_text_ref_edit(self): ...
    def test_selection_overrides_text_ref_delete(self): ...
    def test_selection_overrides_text_ref_duplicate(self): ...
    def test_selection_used_for_add_position(self): ...
    def test_notification_when_selection_overrides(self): ...
```

### Test File: `tests/unit/test_script_preservation.py`

```python
class TestScriptPreservation:
    def test_scripts_preserved_on_html_update(self): ...
    def test_scripts_preserved_with_canvas(self): ...
```

### Test File: `tests/integration/test_versioning_flow.py`

```python
class TestVersioningEndToEnd:
    async def test_full_edit_flow_with_versions(self): ...
    async def test_preview_then_cancel(self): ...
    async def test_preview_then_restore(self): ...
    async def test_multi_intent_creates_multiple_save_points(self): ...
```

---

## Documentation Updates

After implementation, review and update these technical docs in `docs/technical/`:


| Document                            | Update Needed                            |
| ----------------------------------- | ---------------------------------------- |
| `slide-editing-robustness-fixes.md` | Add versioning/save points section       |
| `backend-overview.md`               | Add intent classifier architecture       |
| `frontend-overview.md`              | Add save point UI components             |
| New: `save-points-versioning.md`    | Full documentation of versioning feature |
| New: `intent-classifier.md`         | Full documentation of LLM classifier     |


**Documentation format:** Keep same format as existing docs in the folder.

---

## Implementation Order

1. **Git Sync + Full Scan** - Pull latest main, scan for changes
2. **Bug 1: HTML Edit Fix** (~30 min)
3. **Feature 2: Save Points** (~6-7 hours)
  - Database model
  - Backend: create, preview, restore
  - Frontend: dropdown, preview banner, modal
4. **Feature 3: LLM Classifier** (~6-7 hours)
  - Single intent classification
  - Multi-intent support
  - Safety rules and validation
  - Selection handling
  - Conflict detection
5. **Testing** (~3-4 hours)
6. **Documentation** (~1-2 hours)
  - Update existing docs
  - Create new docs for features

---

## Summary


| Feature         | Key Points                                                          |
| --------------- | ------------------------------------------------------------------- |
| Save Points     | Complete snapshot + verification, 40 limit, preview before restore  |
| Version Numbers | Keep original (no renumbering after deletion)                       |
| Multi-Intent    | Up to 10 per message, all-or-nothing validation                     |
| Conflicts       | Detected before execution, explained to user                        |
| Selection       | Overrides text ref for EDIT/DELETE/DUPLICATE, used for ADD position |
| Safety Rules    | 7 hardcoded rules applied to each intent                            |
| Script Fix      | Preserve `original_scripts` in `update_slide()`                     |


