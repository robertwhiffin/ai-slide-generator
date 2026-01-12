# User Journey Catalog

Exhaustive test coverage specification for databricks tellr E2E tests.

## Overview

This document defines all user journeys that should be covered by E2E tests. Each journey is:
- **Abstract**: Describes behavior, not specific test data
- **Testable**: Clear pass/fail criteria
- **Traceable**: Unique ID for tracking coverage

Test data (Genie room names, IDs, etc.) is configured separately in `fixtures/test-config.ts`.

---

## 1. PROFILE MANAGEMENT

### 1.1 Profile Creation

| Journey ID | Description | Preconditions | Steps | Expected Result |
|------------|-------------|---------------|-------|-----------------|
| **PROF-CREATE-1** | Create profile by searching Genie room by name | User on Profiles page | 1. Click "Create Profile"<br>2. Enter name and description<br>3. Search Genie room by partial name<br>4. Select from dropdown<br>5. Complete wizard | Profile created, appears in list |
| **PROF-CREATE-2** | Create profile using Genie room ID | User on Profiles page | 1. Click "Create Profile"<br>2. Enter name and description<br>3. Switch to "Enter ID" tab<br>4. Paste Genie room ID<br>5. Complete wizard | Room details auto-populate, profile created |
| **PROF-CREATE-3** | Genie room with description auto-populates | User in creation wizard | 1. Search for room that has description<br>2. Select room | Description field auto-fills with room's description |
| **PROF-CREATE-4** | Genie room without description leaves field empty | User in creation wizard | 1. Search for room without description<br>2. Select room | Description field remains empty, user can enter manually |
| **PROF-CREATE-5** | Select slide style during creation | User in creation wizard | 1. Reach style selection step<br>2. Select non-default style | Style saved with profile |
| **PROF-CREATE-6** | Select deck prompt during creation | User in creation wizard | 1. Reach prompt selection step<br>2. Select a deck prompt | Prompt saved with profile |
| **PROF-CREATE-7** | Cancel profile creation mid-wizard | User partway through wizard | 1. Click Cancel or close modal | No profile created, wizard closes |
| **PROF-CREATE-8** | Validation: duplicate profile name | Profile "Test" exists | 1. Try to create profile named "Test" | Error shown, creation blocked |
| **PROF-CREATE-9** | Validation: missing required fields | User in creation wizard | 1. Leave name empty<br>2. Try to proceed | Error indicator on name field, Next disabled |
| **PROF-CREATE-10** | Validation: invalid Genie room ID | User in creation wizard | 1. Enter invalid ID format<br>2. Try to proceed | Error message shown |

### 1.2 Profile Editing

| Journey ID | Description | Preconditions | Steps | Expected Result |
|------------|-------------|---------------|-------|-----------------|
| **PROF-EDIT-1** | Edit profile name and description | Profile exists | 1. Click profile to view details<br>2. Click Edit<br>3. Change name/description<br>4. Save | Changes persist, list updates |
| **PROF-EDIT-2** | Change Genie room on existing profile | Profile exists | 1. Edit profile<br>2. Search for different Genie room<br>3. Select and save | New room associated with profile |
| **PROF-EDIT-3** | Change slide style on profile | Profile exists | 1. Edit profile<br>2. Select different style<br>3. Save | Style change persists |
| **PROF-EDIT-4** | Change deck prompt on profile | Profile exists | 1. Edit profile<br>2. Select different prompt<br>3. Save | Prompt change persists |
| **PROF-EDIT-5** | Cancel edit without saving | Profile exists | 1. Edit profile<br>2. Make changes<br>3. Click Cancel | Original values restored |
| **PROF-EDIT-6** | Cannot edit system/protected profile | System profile exists | 1. View system profile<br>2. Attempt to edit | Edit option disabled or blocked |

### 1.3 Profile Selection & Switching

| Journey ID | Description | Preconditions | Steps | Expected Result |
|------------|-------------|---------------|-------|-----------------|
| **PROF-SWITCH-1** | Switch profile via header dropdown | Multiple profiles exist | 1. Click profile selector in header<br>2. Select different profile | Profile switches, indicator updates |
| **PROF-SWITCH-2** | Switch profile clears current session | Active session with slides | 1. Switch to different profile | Session resets, slides cleared, new session created |
| **PROF-SWITCH-3** | Default profile loads on app start | Default profile configured | 1. Open app fresh | Default profile pre-selected in header |
| **PROF-SWITCH-4** | Profile selector shows all available profiles | Multiple profiles exist | 1. Open profile selector | All non-archived profiles listed |

### 1.4 Profile Deletion

| Journey ID | Description | Preconditions | Steps | Expected Result |
|------------|-------------|---------------|-------|-----------------|
| **PROF-DELETE-1** | Delete non-default profile | Non-default profile exists | 1. View profile details<br>2. Click Delete<br>3. Confirm | Profile removed from list |
| **PROF-DELETE-2** | Cannot delete default profile | Default profile selected | 1. View default profile<br>2. Attempt delete | Action blocked with explanation |
| **PROF-DELETE-3** | Delete confirmation dialog | Profile exists | 1. Click Delete | Confirmation dialog appears before deletion |
| **PROF-DELETE-4** | Cancel delete | In delete confirmation | 1. Click Cancel | Profile not deleted, dialog closes |

---

## 2. SLIDE GENERATION (Core Flow)

### 2.1 Basic Generation

| Journey ID | Description | Preconditions | Steps | Expected Result |
|------------|-------------|---------------|-------|-----------------|
| **GEN-BASIC-1** | Generate slides from simple prompt | Profile selected, Generator view | 1. Type prompt in chat<br>2. Click Send | Slides stream in, appear in slide panel |
| **GEN-BASIC-2** | Generate slides with Genie data query | Profile with valid Genie room | 1. Ask question requiring data<br>2. Send | Genie queried, data appears in slides |
| **GEN-BASIC-3** | Generate with deck prompt applied | Deck prompt selected on profile | 1. Send generation request | Output follows deck prompt structure |
| **GEN-BASIC-4** | Generation shows progress indicators | Generation in progress | 1. Send request | Loading/streaming indicators visible |
| **GEN-BASIC-5** | Generated slides use selected style | Style selected on profile | 1. Generate slides | Slides rendered with correct CSS |
| **GEN-BASIC-6** | Empty prompt blocked | Generator view | 1. Try to send empty message | Send button disabled |

### 2.2 Generation Interruption

| Journey ID | Description | Preconditions | Steps | Expected Result |
|------------|-------------|---------------|-------|-----------------|
| **GEN-CANCEL-1** | Cancel generation mid-stream | Generation in progress | 1. Click Cancel/Stop | Generation stops, partial results shown or cleared |
| **GEN-CANCEL-2** | Navigation blocked during generation | Generation in progress | 1. Try to click History/Profiles nav | Navigation disabled or warning shown |

### 2.3 Iterative Editing via Chat

| Journey ID | Description | Preconditions | Steps | Expected Result |
|------------|-------------|---------------|-------|-----------------|
| **GEN-EDIT-1** | Modify single slide via chat | Slides generated | 1. Type "Change slide 2 title to X"<br>2. Send | Only slide 2 updates |
| **GEN-EDIT-2** | Add new slide to deck | Slides generated | 1. Request "Add a summary slide"<br>2. Send | New slide appended |
| **GEN-EDIT-3** | Insert slide at specific position | Slides generated | 1. Request "Insert slide after slide 1"<br>2. Send | Slide inserted, indices update |
| **GEN-EDIT-4** | Remove slide via chat | Slides generated | 1. Request "Remove slide 3"<br>2. Send | Slide removed, indices update |
| **GEN-EDIT-5** | Regenerate all slides | Slides generated | 1. Request "Regenerate all slides"<br>2. Send | All slides replaced |
| **GEN-EDIT-6** | Request more data | Slides with data | 1. Ask follow-up question about data | Additional Genie query, slides update |

### 2.4 Slide Selection & Targeted Actions

| Journey ID | Description | Preconditions | Steps | Expected Result |
|------------|-------------|---------------|-------|-----------------|
| **GEN-SELECT-1** | Select single slide | Slides generated | 1. Click slide checkbox | Selection badge shows "1 selected" |
| **GEN-SELECT-2** | Select multiple slides | Slides generated | 1. Click multiple checkboxes | Badge shows count, ribbon appears |
| **GEN-SELECT-3** | Select all slides | Slides generated | 1. Click "Select All" | All slides selected |
| **GEN-SELECT-4** | Deselect all | Slides selected | 1. Click "Deselect All" or clear | Selection cleared |
| **GEN-SELECT-5** | Edit selected slides only | 2+ slides selected | 1. Type edit command<br>2. Send | Only selected slides modified |
| **GEN-SELECT-6** | Selection ribbon shows actions | Slides selected | 1. Select slides | Ribbon with available actions appears |

---

## 3. SLIDE VERIFICATION

| Journey ID | Description | Preconditions | Steps | Expected Result |
|------------|-------------|---------------|-------|-----------------|
| **VERIFY-1** | Verify slide with data claims | Slide with data generated | 1. Click Verify on slide | Verification runs, badge shows result |
| **VERIFY-2** | Verified status displayed | Slide verified successfully | - | Green "Verified" badge visible |
| **VERIFY-3** | Unable to verify status | Slide has unverifiable content | 1. Verify slide | "Unable to verify" badge shown |
| **VERIFY-4** | Failed verification | Data claim incorrect | 1. Verify slide | "Failed" badge with details |
| **VERIFY-5** | Re-verify after slide edit | Verified slide edited | 1. Edit slide content<br>2. Observe | Verification status resets |
| **VERIFY-6** | Verify multiple slides | Multiple slides selected | 1. Click Verify Selected | All selected slides verified |

---

## 4. SESSION HISTORY

### 4.1 Session List

| Journey ID | Description | Preconditions | Steps | Expected Result |
|------------|-------------|---------------|-------|-----------------|
| **HIST-LIST-1** | View session history | Sessions exist | 1. Click History nav | Sessions listed with metadata |
| **HIST-LIST-2** | Sessions show metadata | Sessions exist | 1. View history | Each session shows date, message count, profile |
| **HIST-LIST-3** | Empty history state | No sessions | 1. View history | Empty state message shown |
| **HIST-LIST-4** | Sessions sorted by recency | Multiple sessions | 1. View history | Most recent first |

### 4.2 Session Restoration

| Journey ID | Description | Preconditions | Steps | Expected Result |
|------------|-------------|---------------|-------|-----------------|
| **HIST-RESTORE-1** | Restore previous session | Session with slides exists | 1. Click session in history | Slides and chat history load |
| **HIST-RESTORE-2** | Restore session from different profile | Session from Profile B, currently on Profile A | 1. Click session | Profile auto-switches, then loads |
| **HIST-RESTORE-3** | Continue conversation in restored session | Session restored | 1. Send new message | Conversation continues, slides update |

### 4.3 Session Management

| Journey ID | Description | Preconditions | Steps | Expected Result |
|------------|-------------|---------------|-------|-----------------|
| **HIST-RENAME-1** | Rename current session | Active session | 1. Click session title<br>2. Edit<br>3. Save | New name persists |
| **HIST-SAVE-1** | Save session with custom name | Active session | 1. Open Save As dialog<br>2. Enter name<br>3. Save | Session saved with custom name |
| **HIST-DELETE-1** | Delete session from history | Session exists | 1. Click Delete on session<br>2. Confirm | Session removed from list |
| **HIST-NEW-1** | Start new session | Any state | 1. Click New Session | Fresh session created, slides cleared |

---

## 5. DECK PROMPTS

### 5.1 Deck Prompt CRUD

| Journey ID | Description | Preconditions | Steps | Expected Result |
|------------|-------------|---------------|-------|-----------------|
| **PROMPT-CREATE-1** | Create new deck prompt | On Deck Prompts page | 1. Click Create<br>2. Enter name, description, content<br>3. Save | Prompt appears in list |
| **PROMPT-EDIT-1** | Edit existing deck prompt | Prompt exists | 1. Click prompt<br>2. Edit fields<br>3. Save | Changes persist |
| **PROMPT-DELETE-1** | Delete custom deck prompt | Custom prompt exists | 1. Click Delete<br>2. Confirm | Prompt removed |
| **PROMPT-VIEW-1** | View prompt details | Prompt exists | 1. Click prompt | Details panel shows content |

### 5.2 System Prompts

| Journey ID | Description | Preconditions | Steps | Expected Result |
|------------|-------------|---------------|-------|-----------------|
| **PROMPT-SYSTEM-1** | Cannot delete system prompts | System prompt exists | 1. View system prompt<br>2. Attempt delete | Delete option hidden or disabled |
| **PROMPT-SYSTEM-2** | Cannot edit system prompts | System prompt exists | 1. View system prompt | Edit option disabled |
| **PROMPT-SYSTEM-3** | Can duplicate system prompt | System prompt exists | 1. Click Duplicate | New editable copy created |

### 5.3 Prompt Selection

| Journey ID | Description | Preconditions | Steps | Expected Result |
|------------|-------------|---------------|-------|-----------------|
| **PROMPT-SELECT-1** | Select prompt in profile wizard | Creating profile | 1. Reach prompt step<br>2. Select prompt | Prompt associated with profile |
| **PROMPT-SELECT-2** | Change prompt on existing profile | Profile exists | 1. Edit profile<br>2. Change prompt | New prompt saved |

---

## 6. SLIDE STYLES

### 6.1 Slide Style CRUD

| Journey ID | Description | Preconditions | Steps | Expected Result |
|------------|-------------|---------------|-------|-----------------|
| **STYLE-CREATE-1** | Create new slide style | On Slide Styles page | 1. Click Create<br>2. Enter name, description, CSS<br>3. Save | Style appears in list |
| **STYLE-EDIT-1** | Edit existing style CSS | Custom style exists | 1. Click style<br>2. Modify CSS<br>3. Save | Changes persist |
| **STYLE-DELETE-1** | Delete custom style | Custom style exists | 1. Click Delete<br>2. Confirm | Style removed |
| **STYLE-VIEW-1** | View style details | Style exists | 1. Click style | CSS content displayed |

### 6.2 System Styles

| Journey ID | Description | Preconditions | Steps | Expected Result |
|------------|-------------|---------------|-------|-----------------|
| **STYLE-SYSTEM-1** | Cannot delete system styles | System style exists | 1. View system style | Delete option disabled |
| **STYLE-SYSTEM-2** | Cannot edit system styles | System style exists | 1. View system style | Edit option disabled |
| **STYLE-SYSTEM-3** | Can duplicate system style | System style exists | 1. Click Duplicate | New editable copy created |

### 6.3 Style Preview

| Journey ID | Description | Preconditions | Steps | Expected Result |
|------------|-------------|---------------|-------|-----------------|
| **STYLE-PREVIEW-1** | Preview style on sample slide | Style selected | 1. View style with preview | Sample slide rendered with style |
| **STYLE-APPLY-1** | Style applies to generated slides | Style on profile | 1. Generate slides | Slides use correct CSS |

---

## 7. EXPORT & PRESENTATION

### 7.1 Export

| Journey ID | Description | Preconditions | Steps | Expected Result |
|------------|-------------|---------------|-------|-----------------|
| **EXPORT-PPTX-1** | Export slides to PowerPoint | Slides generated | 1. Click Export<br>2. Select PowerPoint | .pptx file downloads |
| **EXPORT-PDF-1** | Export slides to PDF | Slides generated | 1. Click Export<br>2. Select PDF | .pdf file downloads |
| **EXPORT-HTML-1** | Export raw HTML | Slides generated | 1. Click Export<br>2. Select HTML | .html file downloads |
| **EXPORT-SELECTED-1** | Export only selected slides | Slides selected | 1. Select subset<br>2. Export | Only selected slides in export |
| **EXPORT-EMPTY-1** | Export disabled when no slides | No slides | 1. View export button | Button disabled |

### 7.2 Presentation Mode

| Journey ID | Description | Preconditions | Steps | Expected Result |
|------------|-------------|---------------|-------|-----------------|
| **PRESENT-START-1** | Enter presentation mode | Slides generated | 1. Click Present | Full-screen view opens |
| **PRESENT-NAV-RIGHT-1** | Navigate forward with arrow | In presentation | 1. Press Right Arrow | Next slide shown |
| **PRESENT-NAV-LEFT-1** | Navigate backward with arrow | In presentation, not first slide | 1. Press Left Arrow | Previous slide shown |
| **PRESENT-NAV-CLICK-1** | Navigate by clicking | In presentation | 1. Click right side of screen | Next slide |
| **PRESENT-EXIT-1** | Exit with Escape | In presentation | 1. Press Escape | Returns to normal view |
| **PRESENT-EXIT-2** | Exit with close button | In presentation | 1. Click X button | Returns to normal view |
| **PRESENT-INDICATOR-1** | Slide indicator shown | In presentation | - | Shows "Slide X of Y" |

---

## 8. VISUAL EDITOR

| Journey ID | Description | Preconditions | Steps | Expected Result |
|------------|-------------|---------------|-------|-----------------|
| **EDITOR-OPEN-1** | Open HTML editor for slide | Slide exists | 1. Click Edit HTML on slide | Editor modal opens with HTML |
| **EDITOR-SAVE-1** | Edit HTML and save | Editor open | 1. Modify HTML<br>2. Click Save | Changes apply to slide |
| **EDITOR-CANCEL-1** | Cancel HTML edit | Editor open with changes | 1. Click Cancel | Changes discarded, modal closes |
| **EDITOR-SYNTAX-1** | Syntax highlighting in editor | Editor open | - | HTML syntax highlighted |
| **EDITOR-TREE-1** | View element tree | Slide selected | 1. Open element tree view | DOM structure displayed |
| **EDITOR-TREE-SELECT-1** | Select element from tree | Tree view open | 1. Click element in tree | Element highlighted in slide |

---

## 9. NAVIGATION & LAYOUT

| Journey ID | Description | Preconditions | Steps | Expected Result |
|------------|-------------|---------------|-------|-----------------|
| **NAV-GENERATOR-1** | Navigate to Generator | Any page | 1. Click Generator in nav | Generator view loads |
| **NAV-HISTORY-1** | Navigate to History | Any page | 1. Click History in nav | History view loads |
| **NAV-PROFILES-1** | Navigate to Profiles | Any page | 1. Click Profiles in nav | Profiles view loads |
| **NAV-PROMPTS-1** | Navigate to Deck Prompts | Any page | 1. Click Deck Prompts in nav | Deck Prompts view loads |
| **NAV-STYLES-1** | Navigate to Slide Styles | Any page | 1. Click Slide Styles in nav | Slide Styles view loads |
| **NAV-HELP-1** | Navigate to Help | Any page | 1. Click Help in nav | Help page loads |
| **NAV-BLOCKED-1** | Navigation blocked during generation | Generation in progress | 1. Click any nav item | Click ignored or warning shown |

---

## 10. ERROR HANDLING & EDGE CASES

| Journey ID | Description | Preconditions | Steps | Expected Result |
|------------|-------------|---------------|-------|-----------------|
| **ERR-NETWORK-1** | Handle API timeout | Backend slow/unresponsive | 1. Trigger API call | Timeout error shown, retry option |
| **ERR-GENIE-1** | Handle Genie query failure | Invalid Genie room | 1. Generate with bad room | Error in chat, not crash |
| **ERR-GENIE-2** | Handle Genie rate limit | Many rapid requests | 1. Make many requests | Rate limit message shown |
| **ERR-LLM-1** | Handle LLM service error | LLM endpoint down | 1. Try to generate | Graceful error message |
| **ERR-SESSION-1** | Handle session not found | Invalid session ID | 1. Try to restore deleted session | Error message, redirect to new |
| **ERR-PROFILE-1** | Handle profile not found | Profile deleted | 1. Try to use deleted profile | Falls back to default |
| **ERR-AUTH-1** | Handle authentication expiry | Token expired | 1. Make request | Redirect to login or refresh |

---

## 11. ACCESSIBILITY & KEYBOARD

| Journey ID | Description | Preconditions | Steps | Expected Result |
|------------|-------------|---------------|-------|-----------------|
| **A11Y-TAB-1** | Tab navigation through UI | Any page | 1. Tab through elements | Logical focus order |
| **A11Y-ENTER-1** | Activate buttons with Enter | Button focused | 1. Press Enter | Button activates |
| **A11Y-ESC-1** | Close modals with Escape | Modal open | 1. Press Escape | Modal closes |
| **A11Y-ARIA-1** | Screen reader labels | Any page | 1. Inspect with screen reader | Elements properly labeled |

---

## Priority Matrix

| Priority | Journey IDs | Rationale |
|----------|-------------|-----------|
| **P0 - Critical** | GEN-BASIC-1, GEN-BASIC-2, PROF-CREATE-1, PROF-SWITCH-1, HIST-RESTORE-1 | Core functionality |
| **P1 - High** | All VERIFY-*, EXPORT-PPTX-1, PRESENT-*, GEN-EDIT-*, PROF-CREATE-2 | Key user value |
| **P2 - Medium** | All PROMPT-*, STYLE-*, HIST-*, remaining PROF-* | Configuration & management |
| **P3 - Low** | All ERR-*, A11Y-*, NAV-* | Edge cases & polish |

---

## Test Data Requirements

Tests should use configurable data defined in `fixtures/test-config.ts`:

```typescript
interface TestEnvironment {
  genie: {
    searchTerm: string;           // Partial name for search
    expectedRoomName: string;     // Full name to verify
    expectedDescription?: string; // Description if room has one
    roomId: string;               // For ID-based lookup tests
    roomWithoutDescription?: {    // Room without description
      searchTerm: string;
      name: string;
    };
  };
  existingProfile: string;        // Profile name for non-creation tests
  slideStyle: string;             // Style name for tests
  deckPrompt: string;             // Prompt name for tests
}
```

---

## Cleanup Strategy

Tests that create data must clean up:

1. **Unique naming**: Use `test-${Date.now()}` for created resources
2. **After hooks**: Delete created profiles/prompts/styles in `afterEach`
3. **Tagging**: Prefix test resources with `[TEST]` for easy identification
4. **Isolation**: Each test should be independent, not rely on prior test state

---

## Coverage Tracking

| Feature Area | Journey Count | Implemented | Passing |
|--------------|---------------|-------------|---------|
| Profile Management | 20 | 0 | 0 |
| Slide Generation | 17 | 0 | 0 |
| Verification | 6 | 0 | 0 |
| Session History | 11 | 0 | 0 |
| Deck Prompts | 9 | 0 | 0 |
| Slide Styles | 9 | 0 | 0 |
| Export & Presentation | 11 | 0 | 0 |
| Visual Editor | 6 | 0 | 0 |
| Navigation | 7 | 0 | 0 |
| Error Handling | 8 | 0 | 0 |
| Accessibility | 4 | 0 | 0 |
| **TOTAL** | **108** | **0** | **0** |

Update this table as tests are implemented.
