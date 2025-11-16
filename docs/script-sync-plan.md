## Script Synchronization & Raw HTML Single Source Plan

### Goals
- Ensure every agent response replaces the entire script payload so stale Chart.js code never lingers.
- Treat the HTML returned by the agent as the canonical “truth” for both the deck structure and the raw preview.
- Keep manual slide edits (duplicate/delete/update drag) out of the canonical HTML. `raw_html` should reflect only what the agent produced most recently.

### Current Gaps
1. **Frontend optimistic patching** (`frontend/src/utils/slideReplacements.ts`) splices slide HTML and blindly appends `replacement_scripts`, causing duplicate or missing script blocks in the parsed view.
2. **Multiple sources of truth**: The “Parsed” tab renders from `slideDeck` while “Raw HTML (Rendered)” uses `raw_html`. After local edits, these diverge and surfaces inconsistent script behavior.

### High-Level Strategy
| Aspect | Plan |
| --- | --- |
| Canonical HTML | Always derive decks from agent HTML, never from incremental client edits. |
| Script overwrites | Replace affected script blocks through the backend’s `SlideDeck` helpers, then ship the reconciled `scripts` string to the client. |
| Raw HTML updates | Only `ChatService.send_message` updates `self.raw_html`. User edits mutate `self.current_deck` but leave `raw_html` untouched. |

### Backend Changes
1. **`ChatService.send_message`** (`src/api/services/chat_service.py`)
   - When `replacement_info` exists, still run `_apply_slide_replacements`, then immediately call `self.raw_html = self.current_deck.knit()` so the response exposes an agent-aligned HTML snapshot (even if the agent returned fragments).
   - Ensure `raw_html` is included in the API response after every chat message so the UI can refresh its canonical view.
2. **`_apply_slide_replacements`**
   - Continue using `remove_canvas_scripts` + `add_script_block` so replacements *overwrite* any matching canvas IDs.
   - No changes needed for user edits; just document that this is the only path that mutates scripts.
3. **Slide-manipulation endpoints**
   - Keep modifying `self.current_deck` for reorders/duplicates/deletes but intentionally skip `self.raw_html` updates. This preserves the “agent-only” guarantee for raw HTML.

### Frontend Changes
1. **Drop optimistic script merging**
   - Delete `frontend/src/utils/slideReplacements.ts` or limit it to purely visual summaries. Always favor the `slide_deck` returned by the backend after a chat edit.
   - In `ChatPanel`, if `response.slide_deck` is present, call `onSlidesGenerated(response.slide_deck, response.raw_html ?? rawHtml)` regardless of replacement metadata. This ensures script state mirrors the backend’s canonical deck.
2. **Explain raw view semantics**
   - Update any UI copy (e.g., SlidePanel raw tabs) to clarify that raw HTML shows the last agent response, not local edits.
3. **Rendering**
   - `SlideTile` already injects `slideDeck.scripts` into each iframe. With the above change, it will receive the cleaned bundle directly from the backend, eliminating duplicate initialization issues.

### Testing & Validation
1. **Unit**
   - Extend `tests/unit/test_slide_deck.py` to cover `remove_canvas_scripts` + `add_script_block` ensuring canvas IDs are replaced, not duplicated.
   - Add a backend test where `_apply_slide_replacements` receives overlapping canvas IDs and assert `current_deck.scripts` contains only the replacement block.
2. **Integration**
   - Update `tests/integration/test_slide_deck_integration.py` to simulate a replacement response and confirm the returned `slide_deck["scripts"]` matches expectations.
   - Write a frontend Jest/Vitest test (if testing infra exists) or manual QA checklist ensuring:
     - After an edit, parsed slides render with new colors/data.
     - Raw HTML tab still shows the previous agent snapshot after local edits.
3. **Manual**
   - Use `test-slide-edit-htmls/insert.html` to reproduce the color-change scenario; confirm that only the new chart block executes in the Parsed view.

### Rollout Notes
- Communicate to users that the Raw HTML tab reflects the last agent output. Local edits remain visible in Parsed tiles but do not persist back to the canonical HTML unless a new agent response is generated.
- Consider future enhancements: store a “user-edited” HTML snapshot separately if parity between tabs becomes desirable.


