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
  an `AvailableTool`, it reuses the `toToolEntry` conversion from ToolPicker
  (extracted to a shared util or imported). The caller guarantees that
  `space_id` and `space_name` are defined for any `AvailableTool` passed to
  the panel (only Genie-type tools with valid IDs reach this component).
- Renders: GENIE badge + space name (read-only), space ID (read-only, mono),
  description textarea (editable), helper text ("Used by the agent to decide
  when to query this space"), Cancel and Save buttons.
- Renders inline within the config bar (not a modal or overlay) — inserted
  above the tools row when `detailTool` is set.
- Button label: "Save & Add" in `add` mode, "Save" in `edit` mode.
- Empty description: placeholder text "Describe when the agent should use this
  space..."
- Escape key dismisses the panel (same as Cancel). Textarea auto-focuses on
  open.

## Integration Changes

### ToolPicker.tsx

- Add new callback: `onPreview: (tool: AvailableTool) => void`.
- Keep existing `onSelect` for MCP tools — they bypass the detail panel and are
  added immediately as before.
- Clicking a **Genie** row calls `onPreview(tool)` and closes the picker.
- Clicking an **MCP** row calls `onSelect(toToolEntry(tool))` as today.
- No other changes to the list view (truncated descriptions in the browse list
  are fine).

### ToolChip (inside AgentConfigBar.tsx)

- Split click targets on the chip:
  - **Label area** → opens detail panel in `edit` mode.
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
- `onCancel`: clears `detailTool`, no side effects.
- ToolPicker's `onPreview` sets `detailTool` and `detailMode: 'add'`.

### AgentConfigContext

- New method:
  ```ts
  updateTool: (spaceId: string, updates: { description?: string }) => void
  ```
- Updates the matching tool in `agentConfig.tools` in-place and syncs to the
  session backend.
- When the user later calls "Save as Profile", the edited description is
  captured automatically since it is already in the tools array.

## Files Changed

| File | Change | ~Lines |
|------|--------|--------|
| `GenieDetailPanel.tsx` | New component | ~80 |
| `ToolPicker.tsx` | Add `onPreview` for Genie, keep `onSelect` for MCP | ~10 |
| `AgentConfigBar.tsx` | State, wiring, render panel | ~30 |
| `ToolChip` (in AgentConfigBar) | Split click targets | ~10 |
| `AgentConfigContext.tsx` | `updateTool()` method | ~15 |

## Files Not Changed

- **`agentConfig.ts`** — `GenieTool.description` already exists.
- **Backend** — no new endpoints. Description persists via existing session and
  profile save flows.

## Edge Cases

- **No description from Databricks** — textarea empty, placeholder shown.
- **Cancel on add** — tool not added.
- **Cancel on edit** — description reverts.
- **Long descriptions** — textarea is vertically resizable, no max length.
