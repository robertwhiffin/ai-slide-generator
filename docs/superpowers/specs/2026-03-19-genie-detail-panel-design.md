# Genie Detail Panel — Design Spec

## Problem

When a user adds a Genie space to their agent config, the description from
Databricks is shown truncated in the ToolPicker list and not shown at all on the
ToolChip. There is no way to:

1. **Read the full description** — it is truncated to two lines in the picker.
2. **Edit the description** — important because the agent uses it to decide when
   to query the space.
3. **Review details after adding** — the chip shows only the name.

## Solution

A shared `GenieDetailPanel` component that opens from two entry points:

- **Adding a new Genie space** — clicking a row in ToolPicker opens the panel
  instead of immediately adding the tool.
- **Editing an existing Genie space** — clicking a ToolChip label opens the
  same panel for the already-configured tool.

The panel shows the full description in an editable textarea, the space ID for
reference, and Save/Cancel actions.

## Design Decisions

- **No test connection button** — a separate PR adds better error handling that
  surfaces permission issues at query time.
- **Standalone component (Approach A)** — keeps AgentConfigBar from growing and
  allows isolated testing.
- **No backend changes** — the edited description lives in the session's
  `agentConfig.tools[]` array and is persisted when the user saves as a profile.
  No new API endpoints are needed.

## Component: GenieDetailPanel

### File

`frontend/src/components/AgentConfigBar/GenieDetailPanel.tsx`

### Props

```ts
interface GenieDetailPanelProps {
  tool: GenieTool | AvailableTool;
  mode: 'add' | 'edit';
  onSave: (tool: GenieTool) => void;
  onCancel: () => void;
}
```

### Behavior

- Internal state: description textarea value, initialized from
  `tool.description`.
- On save, the panel constructs a `GenieTool` from the input. When the input is
  an `AvailableTool`, it uses the `toGenieToolEntry` function from
  `frontend/src/components/AgentConfigBar/toolUtils.ts` (extracted from
  ToolPicker's current `toToolEntry`). The caller guarantees that `space_id` and
  `space_name` are defined for any `AvailableTool` passed to the panel (only
  Genie-type tools with valid IDs reach this component).
- `conversation_id` is not set during the add flow — it is `undefined` on the
  constructed `GenieTool` and gets populated later at query time by the backend.
  In edit mode the existing `conversation_id` is preserved as-is.
- Renders: GENIE badge + space name (read-only), space ID (read-only, mono),
  description textarea (editable), helper text ("Used by the agent to decide
  when to query this space"), Cancel and Save buttons.
- Renders inline within the config bar (not a modal or overlay) — inserted
  above the tools row when `detailTool` is set.
- Button label: "Save & Add" in `add` mode, "Save" in `edit` mode.
- Empty description: placeholder text "Describe when the agent should use this
  space..."
- Escape key dismisses the panel (same as Cancel). The `onKeyDown` handler
  calls `e.stopPropagation()` before invoking `onCancel` to prevent the event
  from bubbling to parent elements (e.g. collapsing the config bar).
- Textarea auto-focuses on open.
- **Error on save**: if the underlying `addTool()` or `updateTool()` call
  fails, the panel stays open so the user can retry. The context already shows
  toasts on `updateConfig` failure, so no additional error UI is needed in the
  panel itself.

### Multiple panel opens

If the user clicks a different chip label or picks a new Genie space while the
panel is already open with unsaved edits, the current panel is **silently
replaced** (no confirmation dialog). The textarea is small and the cost of
re-entering a description edit is low — a discard prompt would add friction
disproportionate to the risk.

## Integration Changes

### toolUtils.ts (new file)

`frontend/src/components/AgentConfigBar/toolUtils.ts`

Extract and export the Genie-specific conversion from ToolPicker's current
`toToolEntry` (line 33):

```ts
export function toGenieToolEntry(tool: AvailableTool): GenieTool {
  return {
    type: 'genie',
    space_id: tool.space_id!,
    space_name: tool.space_name ?? tool.space_id!,
    description: tool.description,
  };
}
```

ToolPicker and GenieDetailPanel both import from this file. ToolPicker's
inline `toToolEntry` is replaced: Genie branch calls `toGenieToolEntry`, MCP
branch stays inline (or is extracted to the same file for consistency).

### ToolPicker.tsx

- Add new callback: `onPreview: (tool: AvailableTool) => void`.
- Keep existing `onSelect` for MCP tools — they bypass the detail panel and are
  added immediately as before.
- Clicking a **Genie** row calls `onPreview(tool)` and closes the picker.
- Clicking an **MCP** row calls `onSelect(toToolEntry(tool))` as today.
- Import `toGenieToolEntry` from `toolUtils.ts`, remove inline Genie conversion.
- No other changes to the list view (truncated descriptions in the browse list
  are fine).

### ToolChip (inside AgentConfigBar.tsx)

- New prop: `onEdit: () => void` — called when the label area is clicked.
- Split click targets on the chip:
  - **Label area** → calls `onEdit()`. For Genie tools, AgentConfigBar opens
    the detail panel in `edit` mode. For MCP tools, `onEdit` is not passed
    (the label is not clickable — no cursor change, no hover effect).
  - **X button** → removes tool (unchanged).
  - **External link button** → opens Genie deep-link (unchanged).

### AgentConfigBar.tsx

- New state: `detailTool: GenieTool | AvailableTool | null` and
  `detailMode: 'add' | 'edit'`.
- When `detailTool` is set, renders `GenieDetailPanel` above the tools row.
- `onSave` handler:
  - **add mode**: calls `addTool()` with the returned GenieTool (including
    edited description), clears `detailTool`.
  - **edit mode**: calls `updateTool()` to patch the description in-place,
    clears `detailTool`.
  - If either call rejects, `detailTool` is **not** cleared (panel stays open
    for retry).
- `onCancel`: clears `detailTool`, no side effects.
- ToolPicker's `onPreview` sets `detailTool` and `detailMode: 'add'`.
- Passes `onEdit` to ToolChip only for Genie tools.

### AgentConfigContext

- New method:
  ```ts
  updateTool: (spaceId: string, updates: { description?: string }) => Promise<void>
  ```
- Follows the same optimistic-update-with-revert pattern as `addTool` and
  `removeTool`: updates local state immediately, calls `updateConfig` to sync
  to the backend, reverts on failure.
- Updates the matching tool in `agentConfig.tools` in-place and syncs to the
  session backend.
- When the user later calls "Save as Profile", the edited description is
  captured automatically since it is already in the tools array.

## Files Changed

| File | Change | ~Lines |
|------|--------|--------|
| `toolUtils.ts` | New — `toGenieToolEntry` extracted from ToolPicker | ~10 |
| `GenieDetailPanel.tsx` | New component | ~100 |
| `ToolPicker.tsx` | Add `onPreview` for Genie, keep `onSelect` for MCP, import `toGenieToolEntry` | ~15 |
| `AgentConfigBar.tsx` | State, wiring, render panel, `onEdit` on Genie chips | ~35 |
| `ToolChip` (in AgentConfigBar) | New `onEdit` prop, split click targets | ~15 |
| `AgentConfigContext.tsx` | `updateTool()` method (async, optimistic) | ~20 |

## Files Not Changed

- **`agentConfig.ts`** — `GenieTool.description` and `conversation_id` already
  exist.
- **Backend** — no new endpoints. Description persists via existing session and
  profile save flows.

## Test Plan

### Unit tests

- **`GenieDetailPanel`**: render in add/edit modes, save callback returns
  correct GenieTool, cancel fires onCancel, Escape key dismisses with
  stopPropagation, empty description shows placeholder, textarea auto-focuses.
- **`updateTool` in AgentConfigContext**: patches description on correct tool,
  syncs to backend, reverts on failure.
- **`toGenieToolEntry` in toolUtils**: converts AvailableTool to GenieTool
  correctly, handles missing space_name fallback.

### E2E tests

- **Add flow**: open ToolPicker → click Genie row → detail panel appears → edit
  description → Save & Add → chip appears with tool added.
- **Edit flow**: click existing Genie chip label → detail panel appears with
  current description → edit → Save → description updated.
- **Cancel flows**: add-then-cancel does not add tool; edit-then-cancel reverts
  description.

## Edge Cases

- **No description from Databricks** — textarea empty, placeholder shown.
- **Cancel on add** — tool not added.
- **Cancel on edit** — description reverts.
- **Long descriptions** — textarea is vertically resizable, no max length.
- **conversation_id on add** — `undefined`, populated later at query time.
- **MCP chip label click** — no-op, label is not interactive for MCP tools.
- **Rapid panel switching** — previous panel silently replaced, no confirmation.
- **Save failure** — panel stays open, toast shown by context.
