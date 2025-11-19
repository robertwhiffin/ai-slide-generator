# Phase 5: Frontend Profile Management

**Duration:** Days 10-12  
**Status:** Not Started  
**Prerequisites:** Phase 4 Complete (Settings Integration)

## Objectives

- Create React components for profile management
- Implement profile CRUD operations UI
- Add profile switcher component
- Implement "Load Profile" and "Set as Default" actions
- Add confirmation dialogs for destructive actions
- Style components consistently with existing UI

## Files to Create

```
frontend/src/
├── components/
│   └── config/
│       ├── ProfileSelector.tsx
│       ├── ProfileList.tsx
│       ├── ProfileForm.tsx
│       └── ConfirmDialog.tsx
├── hooks/
│   └── useProfiles.ts
└── api/
    └── config.ts
```

## Implementation Summary

### Step 1: API Client

**File:** `frontend/src/api/config.ts`

```typescript
import axios from 'axios';

const API_BASE = '/api/config';

export interface Profile {
  id: number;
  name: string;
  description: string;
  is_default: boolean;
  created_at: string;
  created_by: string;
}

export interface ProfileCreate {
  name: string;
  description?: string;
  copy_from_profile_id?: number;
}

export const configApi = {
  // Profiles
  listProfiles: () => axios.get<Profile[]>(`${API_BASE}/profiles`),
  getProfile: (id: number) => axios.get<Profile>(`${API_BASE}/profiles/${id}`),
  getDefaultProfile: () => axios.get<Profile>(`${API_BASE}/profiles/default`),
  createProfile: (data: ProfileCreate) => axios.post<Profile>(`${API_BASE}/profiles`, data),
  updateProfile: (id: number, data: Partial<Profile>) => axios.put<Profile>(`${API_BASE}/profiles/${id}`, data),
  deleteProfile: (id: number) => axios.delete(`${API_BASE}/profiles/${id}`),
  setDefaultProfile: (id: number) => axios.post(`${API_BASE}/profiles/${id}/set-default`),
  loadProfile: (id: number) => axios.post(`${API_BASE}/profiles/${id}/load`),
  duplicateProfile: (id: number, newName: string) => axios.post(`${API_BASE}/profiles/${id}/duplicate`, { new_name: newName }),
};
```

### Step 2: Profiles Hook

**File:** `frontend/src/hooks/useProfiles.ts`

```typescript
import { useState, useEffect } from 'react';
import { configApi, Profile } from '../api/config';

export const useProfiles = () => {
  const [profiles, setProfiles] = useState<Profile[]>([]);
  const [currentProfile, setCurrentProfile] = useState<Profile | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const loadProfiles = async () => {
    try {
      setLoading(true);
      const { data } = await configApi.listProfiles();
      setProfiles(data);
      
      // Find default profile
      const defaultProfile = data.find(p => p.is_default);
      setCurrentProfile(defaultProfile || null);
    } catch (err) {
      setError('Failed to load profiles');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadProfiles();
  }, []);

  const createProfile = async (data: ProfileCreate) => {
    const response = await configApi.createProfile(data);
    await loadProfiles();
    return response.data;
  };

  const deleteProfile = async (id: number) => {
    await configApi.deleteProfile(id);
    await loadProfiles();
  };

  const setDefault = async (id: number) => {
    await configApi.setDefaultProfile(id);
    await loadProfiles();
  };

  const loadProfile = async (id: number) => {
    await configApi.loadProfile(id);
    const profile = profiles.find(p => p.id === id);
    if (profile) {
      setCurrentProfile(profile);
    }
  };

  return {
    profiles,
    currentProfile,
    loading,
    error,
    createProfile,
    deleteProfile,
    setDefault,
    loadProfile,
    reload: loadProfiles,
  };
};
```

### Step 3: Profile Selector Component

**File:** `frontend/src/components/config/ProfileSelector.tsx`

Create dropdown component for quick profile switching:
- Shows current profile
- Lists all profiles (with default badge)
- "Load" action to switch profiles
- "Manage Profiles" button to open full management UI

### Step 4: Profile List Component

**File:** `frontend/src/components/config/ProfileList.tsx`

Full profile management UI:
- Table/list view of all profiles
- Action buttons: Edit, Delete, Duplicate, Set as Default
- Create new profile button
- Default profile indicator
- Confirmation dialogs for destructive actions

### Step 5: Profile Form Component

**File:** `frontend/src/components/config/ProfileForm.tsx`

Form for create/edit:
- Name (required, unique validation)
- Description (optional)
- "Copy from existing" dropdown (on create only)
- Save/Cancel buttons

### Step 6: Confirm Dialog Component

**File:** `frontend/src/components/config/ConfirmDialog.tsx`

Reusable confirmation dialog:
- Title, message, confirm/cancel buttons
- Used for delete, set default actions

## UI Layout

Add to existing navigation:
```
Settings
├── Profiles (new)
│   └── Profile management UI
└── Configuration (new)
    ├── AI Infrastructure
    ├── Genie Spaces
    ├── MLflow
    └── Prompts
```

Add profile selector to header/navbar:
```
[Current Profile: default ▼]
```

## Testing

```typescript
// tests/components/config/ProfileSelector.test.tsx

describe('ProfileSelector', () => {
  it('renders current profile', () => {
    // Test
  });

  it('allows switching profiles', () => {
    // Test
  });

  it('shows default badge', () => {
    // Test
  });
});
```

## Styling

Use existing design system:
- Consistent button styles
- Loading spinners
- Error messages
- Badges for "default" indicator
- Confirmation modal styling

## Deliverables

- [ ] Profile selector in navbar
- [ ] Full profile management UI
- [ ] Create/edit/delete profiles
- [ ] Duplicate profiles
- [ ] Set default profile
- [ ] Load profile (hot switch)
- [ ] Confirmation dialogs
- [ ] Loading states
- [ ] Error handling
- [ ] Responsive design

## Next Steps

Proceed to **Phase 6: Frontend Configuration Forms**.

