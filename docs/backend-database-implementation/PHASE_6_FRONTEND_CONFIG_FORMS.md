# Phase 6: Frontend Configuration Forms

**Duration:** Days 13-15  
**Status:** Not Started  
**Prerequisites:** Phase 5 Complete (Profile Management UI)

## Objectives

- Create configuration forms for each domain
- Implement AI Infrastructure configuration UI
- Implement Genie Spaces management UI
- Implement MLflow configuration UI
- Implement Prompts editor with Monaco
- Add validation and error handling
- Auto-save or manual save with dirty state tracking

## Files to Create

```
frontend/src/
├── components/
│   └── config/
│       ├── AIInfraForm.tsx
│       ├── GenieSpacesManager.tsx
│       ├── MLflowForm.tsx
│       ├── PromptsEditor.tsx
│       └── ConfigTabs.tsx
└── hooks/
    ├── useConfig.ts
    └── useEndpoints.ts
```

## Implementation Summary

### Step 1: Configuration Tabs Layout

**File:** `frontend/src/components/config/ConfigTabs.tsx`

Create tabbed interface:
```tsx
<Tabs>
  <Tab label="AI Infrastructure">
    <AIInfraForm />
  </Tab>
  <Tab label="Genie Spaces">
    <GenieSpacesManager />
  </Tab>
  <Tab label="MLflow">
    <MLflowForm />
  </Tab>
  <Tab label="Prompts">
    <PromptsEditor />
  </Tab>
</Tabs>
```

### Step 2: AI Infrastructure Form

**File:** `frontend/src/components/config/AIInfraForm.tsx`

Components:
- **Endpoint Selection:** Searchable dropdown
  - Load from `GET /api/config/llm/endpoints`
  - Sort "databricks-" endpoints first
  - Show loading state while fetching
  - Fallback to text input on error
  
- **Temperature Slider:** 0.0 - 1.0 (step 0.1)
  - Visual slider with numeric input
  - Live preview of value
  
- **Max Tokens Input:** Positive integer
  - Validation for positive values
  - Suggested values (dropdown or hints)

**Implementation Notes:**
```typescript
const { data: endpoints, loading } = useEndpoints();

<Select
  label="LLM Endpoint"
  options={endpoints}
  value={config.llm_endpoint}
  onChange={handleEndpointChange}
  loading={loading}
  searchable
  groupBy={(endpoint) => endpoint.startsWith('databricks-') ? 'Databricks' : 'Other'}
/>
```

### Step 3: Genie Spaces Manager

**File:** `frontend/src/components/config/GenieSpacesManager.tsx`

Features:
- List all Genie spaces for current profile
- Add new space (form with space_id, name, description)
- Edit space (name, description)
- Delete space (with confirmation)
- Set default space (radio buttons)
- Show default badge

UI Layout:
```
Genie Spaces
┌─────────────────────────────────────────────┐
│ ● Databricks Usage Analytics (default)      │
│   Space ID: 01effebcc2781b6bbb749077a55d31e3│
│   [Edit] [Delete]                           │
├─────────────────────────────────────────────┤
│ ○ Custom Analytics Space                    │
│   Space ID: abc123...                       │
│   [Set as Default] [Edit] [Delete]          │
└─────────────────────────────────────────────┘
[+ Add Genie Space]
```

### Step 4: MLflow Form

**File:** `frontend/src/components/config/MLflowForm.tsx`

Simple form:
- **Experiment Name:** Text input
  - Validation: Must start with `/`
  - Format: `/Workspace/Users/{username}/...`
  - Placeholder with current user's path
  - Info tooltip about path format

```tsx
<TextField
  label="Experiment Name"
  value={config.mlflow_experiment_name}
  onChange={handleChange}
  placeholder={`/Workspace/Users/${username}/ai-slide-generator`}
  helperText="MLflow experiment path (must start with /)"
  error={error}
/>
```

### Step 5: Prompts Editor

**File:** `frontend/src/components/config/PromptsEditor.tsx`

Use Monaco Editor for rich editing:

```tsx
import Editor from '@monaco-editor/react';

<div className="prompts-editor">
  <div className="editor-section">
    <h3>System Prompt</h3>
    <Editor
      height="300px"
      defaultLanguage="text"
      value={prompts.system_prompt}
      onChange={handleSystemPromptChange}
      options={{
        minimap: { enabled: false },
        wordWrap: 'on',
      }}
    />
    <div className="help-text">
      Available placeholders: {'{max_slides}'}
    </div>
  </div>

  <div className="editor-section">
    <h3>Slide Editing Instructions</h3>
    <Editor
      height="200px"
      defaultLanguage="text"
      value={prompts.slide_editing_instructions}
      onChange={handleEditingChange}
    />
  </div>

  <div className="editor-section">
    <h3>User Prompt Template</h3>
    <Editor
      height="100px"
      defaultLanguage="text"
      value={prompts.user_prompt_template}
      onChange={handleUserPromptChange}
    />
    <div className="help-text">
      Required placeholder: {'{question}'}
    </div>
  </div>
</div>
```

Features:
- Syntax highlighting
- Line numbers
- Auto-resize
- Placeholder validation warnings
- Reset to defaults button

### Step 6: Configuration Hooks

**File:** `frontend/src/hooks/useConfig.ts`

```typescript
export const useConfig = (profileId: number) => {
  const [config, setConfig] = useState({
    ai_infra: null,
    genie_spaces: [],
    mlflow: null,
    prompts: null,
  });
  const [dirty, setDirty] = useState(false);
  const [saving, setSaving] = useState(false);

  const loadConfig = async () => {
    // Load all configs for profile
  };

  const saveAIInfra = async (data) => {
    setSaving(true);
    await configApi.updateAIInfra(profileId, data);
    setDirty(false);
    setSaving(false);
  };

  // Similar for other domains

  return {
    config,
    dirty,
    saving,
    saveAIInfra,
    saveGenie,
    saveMLflow,
    savePrompts,
    reload: loadConfig,
  };
};
```

**File:** `frontend/src/hooks/useEndpoints.ts`

```typescript
export const useEndpoints = () => {
  const [endpoints, setEndpoints] = useState<string[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const fetchEndpoints = async () => {
      try {
        const { data } = await axios.get('/api/config/llm/endpoints');
        setEndpoints(data);
      } catch (err) {
        setError('Failed to load endpoints');
      } finally {
        setLoading(false);
      }
    };
    fetchEndpoints();
  }, []);

  return { endpoints, loading, error };
};
```

## Validation

Client-side validation:
- Temperature: 0.0 - 1.0
- Max tokens: > 0
- Experiment name: starts with `/`
- Prompts: required placeholders present

Show validation errors inline with helpful messages.

## Auto-save vs Manual Save

**Recommended: Manual Save** with dirty state tracking:
- Show "Unsaved changes" indicator
- Confirm before leaving page with unsaved changes
- Clear save button with loading state
- Success/error toast notifications

## Styling

Consistent with existing UI:
- Form layouts with proper spacing
- Input validation states (error/success)
- Loading spinners
- Disabled states while saving
- Responsive layout for mobile

## Testing

```typescript
describe('AIInfraForm', () => {
  it('loads current configuration', () => {});
  it('validates temperature range', () => {});
  it('saves changes', () => {});
  it('shows validation errors', () => {});
});

describe('PromptsEditor', () => {
  it('warns about missing placeholders', () => {});
  it('allows reset to defaults', () => {});
});
```

## Deliverables

- [ ] Tabbed configuration UI
- [ ] AI Infrastructure form with endpoint dropdown
- [ ] Genie Spaces manager (CRUD)
- [ ] MLflow form (experiment name)
- [ ] Prompts editor with Monaco
- [ ] Client-side validation
- [ ] Dirty state tracking
- [ ] Save/cancel functionality
- [ ] Loading and error states
- [ ] Success notifications
- [ ] Responsive design

## Next Steps

Proceed to **Phase 7: History & Polish**.

