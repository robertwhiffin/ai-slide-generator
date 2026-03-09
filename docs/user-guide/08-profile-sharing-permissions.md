# Profile Sharing & Permissions

This guide explains how to share configuration profiles with team members and what each permission level allows.

## Overview

Profiles can be shared with Databricks users and groups at three permission levels:

| Level | Summary |
|-------|---------|
| **CAN VIEW** | See content, create new sessions |
| **CAN EDIT** | Modify profiles, edit slides |
| **CAN MANAGE** | Full control including delete |

## Adding Contributors

1. Open a profile you own or have CAN_EDIT/CAN_MANAGE access to
2. Navigate to the **Contributors** tab
3. Click **Add Contributor**
4. Search for a user or group by name/email
5. Select the permission level
6. Click **Add**

## Permission Levels Explained

### CAN VIEW

**Best for:** Consumers who need to use a profile without modifying it.

**What you CAN do:**
- ✅ See the profile in your profile list
- ✅ View profile configuration (Genie space, prompts, styles)
- ✅ Set the profile as your personal default
- ✅ Create new sessions using this profile
- ✅ View all sessions created under this profile
- ✅ View slides in any session

**What you CANNOT do:**
- ❌ Edit profile configuration
- ❌ Add or remove contributors
- ❌ Edit slides in shared sessions
- ❌ Delete slides or sessions
- ❌ Use chat to regenerate slides in shared sessions

### CAN EDIT

**Best for:** Collaborators who actively work on presentations together.

**Includes everything in CAN VIEW, plus:**

**What you CAN do:**
- ✅ Edit profile configuration (Genie spaces, prompts, styles)
- ✅ Add, remove, or modify contributors
- ✅ Edit slides in any session (content, layout, formatting)
- ✅ Reorder and duplicate slides
- ✅ Use chat to regenerate or modify slides

**What you CANNOT do:**
- ❌ Delete the profile
- ❌ Delete sessions
- ❌ Delete slides

### CAN MANAGE

**Best for:** Profile administrators and team leads.

**Includes everything in CAN EDIT, plus:**

**What you CAN do:**
- ✅ Delete the profile (unless it's the default)
- ✅ Delete any session under the profile
- ✅ Delete slides
- ✅ Transfer ownership (add another user with CAN_MANAGE)

## Session Permissions

### My Sessions vs Shared Sessions

Your session history is divided into two sections:

| Tab | Description |
|-----|-------------|
| **My Sessions** | Sessions you created (full control) |
| **Shared with Me** | Sessions from profiles you have access to |

### Session Permission Rules

**Your own sessions:** You always have full control over sessions you created, regardless of what permission you have on the profile.

**Shared sessions:** Your access depends on your profile permission:

| Action | CAN VIEW | CAN EDIT | CAN MANAGE |
|--------|----------|----------|------------|
| View session | ✅ | ✅ | ✅ |
| Rename session | ❌ | ✅ | ✅ |
| Delete session | ❌ | ❌ | ✅ |

## Slide Permissions

Slide permissions follow the session's profile permission:

| Action | CAN VIEW | CAN EDIT | CAN MANAGE |
|--------|----------|----------|------------|
| View slides | ✅ | ✅ | ✅ |
| Edit slide content | ❌ | ✅ | ✅ |
| Reorder slides | ❌ | ✅ | ✅ |
| Duplicate slides | ❌ | ✅ | ✅ |
| Optimize with AI | ❌ | ✅ | ✅ |
| Delete slides | ❌ | ❌ | ✅ |
| Use chat | ❌ | ✅ | ✅ |

**Visual Indicators:** When viewing shared sessions with CAN_VIEW permission:
- Chat input is disabled with a "View only" message
- Edit, delete, and reorder buttons are hidden on slides
- The session shows a "Viewer" badge

## Group Permissions

When you add a Databricks group as a contributor:

- All members of that group receive the assigned permission
- If a user belongs to multiple groups with different permissions, they get the **highest** level
- Group memberships are cached for 5 minutes

**Example:**
- Group "Sales" has CAN_VIEW on Profile A
- Group "Managers" has CAN_EDIT on Profile A
- User John is in both groups
- John gets CAN_EDIT access (the higher permission)

## Special Rules

### Profile Creator

The user who creates a profile:
- Automatically gets CAN_MANAGE permission
- Cannot be removed as a contributor
- Cannot have their permission level reduced

### Default Profile

The profile marked as "default":
- Cannot be deleted (must assign a new default first)
- Can still have contributors added/removed normally

### Permission Inheritance

```
Profile Permission
    ↓
Session Permission (inherits from profile)
    ↓  
Slide Permission (inherits from session's profile)
```

Your own content (sessions you created) always gives you full control, but shared content follows the profile permission hierarchy.

## Common Scenarios

### Scenario 1: Read-Only Stakeholder
A manager wants to view presentations without editing.
→ Add them with **CAN VIEW**

### Scenario 2: Team Collaboration
Team members need to create and refine presentations together.
→ Add them with **CAN EDIT**

### Scenario 3: Backup Administrator
Another admin needs to manage the profile if you're unavailable.
→ Add them with **CAN MANAGE**

### Scenario 4: Department Access
An entire department needs to use a profile.
→ Add the Databricks group with **CAN VIEW** or **CAN EDIT**

## See Also

- [Creating Profiles](./02-creating-profiles.md)
- [Advanced Configuration](./03-advanced-configuration.md)
- [Technical Documentation: Permissions Model](../technical/permissions-model.md)
