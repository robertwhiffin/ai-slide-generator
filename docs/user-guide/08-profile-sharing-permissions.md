# Profile Sharing & Permissions

This guide explains how to share configuration profiles with team members and what each permission level allows.

## Overview

Profiles can be shared in two ways:

1. **With specific users/groups** — add individual contributors with a chosen permission level
2. **With all workspace users** — make the profile globally visible at a chosen permission level

| Level | Summary |
|-------|---------|
| **CAN VIEW** | See content, add comments and mentions, create new sessions |
| **CAN EDIT** | Modify profiles, edit slides, use chat |
| **CAN MANAGE** | Full control including delete |

## Adding Contributors

1. Open a profile you own or have CAN_EDIT/CAN_MANAGE access to
2. Navigate to the **Contributors** tab
3. Click **Add Contributor**
4. Search for a user or group by name/email
5. Select the permission level (default: CAN_EDIT)
6. Click **Add**

## Sharing with All Workspace Users

1. During profile creation (Step 5: Share) or when editing, open the **Contributors** tab
2. Use the **All workspace users** dropdown
3. Select a permission level: Can View, Can Edit, or Can Manage
4. Save — all users in the Databricks workspace now have access at that level

Individual contributor entries override the global level if they grant higher access.

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
- ✅ Add comments, replies, and @mentions
- ✅ Export presentations

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
- ✅ Delete the profile
- ✅ Delete any session under the profile
- ✅ Delete slides
- ✅ Transfer ownership (add another user with CAN_MANAGE)

## Session Permissions

### My Sessions vs Shared Sessions

Your session history is divided into two tabs in **View All Decks**:

| Tab | Description |
|-----|-------------|
| **My Sessions** | Sessions you created (full control) |
| **Shared with Me** | Sessions from profiles you have access to (across all shared profiles) |

Each row includes a **Profile** column identifying which profile the deck belongs to.

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

## Editing Lock

When multiple users have edit access to the same presentation, only one can edit at a time.

**How it works:**
1. The first user to open the session acquires an exclusive editing lock
2. Other users see a banner: "[User] is editing the slides"
3. Locked-out users can still view slides, add comments, @mention others, and export
4. The lock releases automatically when the editor leaves or is idle for 5 minutes
5. Locked-out users automatically acquire the lock once it becomes available

The profile owner has no priority — whoever arrives first gets the lock.

## Comments & @Mentions

All users (including CAN_VIEW and locked-out users) can add comments and @mentions on any slide.

### Adding a comment
Click the comment icon on any slide tile to open the thread panel.

### @Mentioning a user
Type `@` in the comment input followed by the user's email. A dropdown appears after 2 characters with matching users from the workspace.

### Notifications
- Each slide has a bell icon that shows unread mention count
- The bell flashes when new mentions arrive (polled every 3 seconds)
- Notifications are scoped to the current deck and slide — mentions from other decks never appear
- Clicking the bell marks mentions as seen

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

## Personal Default Profile

Each user can set their own default profile independently. This controls which profile is loaded when the app starts.

1. Open the profile list
2. Click the **⋯** menu on the desired profile
3. Select **Set as My Default**

The "Default" badge appears next to your chosen profile.

## Special Rules

### Profile Creator

The user who creates a profile:
- Automatically gets CAN_MANAGE permission
- Cannot be removed as a contributor
- Cannot have their permission level reduced

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

### Scenario 5: Company-Wide Template
Everyone in the workspace should see presentations from a profile.
→ Set "All workspace users" to **CAN VIEW**

## See Also

- [Creating Profiles](./02-creating-profiles.md)
- [Advanced Configuration](./03-advanced-configuration.md)
- [Technical Documentation: Permissions Model](../technical/permissions-model.md)
