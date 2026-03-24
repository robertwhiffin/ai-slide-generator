# Sharing & Permissions

This guide explains how to share decks and profiles with team members and what each permission level allows.

## Overview

Decks and profiles are shared independently:

- **Deck sharing** controls who can view and edit a specific slide deck
- **Profile sharing** controls who can use and modify a configuration profile (agent config template)

Sharing a profile does **not** grant access to any deck. Sharing a deck does **not** grant access to any profile.

## Sharing a Deck

1. Open the deck you want to share
2. Click the **Share** button to open the permissions manager
3. Search for a user or group by name or email
4. Select the permission level: **CAN VIEW**, **CAN EDIT**, or **CAN MANAGE**
5. Click **Add** — the contributor now sees the deck in their "Shared with Me" tab

To share a link directly, click the **Copy Link** button to copy a shareable URL to your clipboard.

### Deck Permission Levels

| Level | Summary |
|-------|---------|
| **CAN VIEW** | See slides, add comments and mentions, export |
| **CAN EDIT** | Modify slides, use chat, reorder and duplicate slides |
| **CAN MANAGE** | Full control including delete and manage sharing |

### Deck Permission Details

#### CAN VIEW

**Best for:** Stakeholders who need to review presentations without editing.

**What you CAN do:**
- View slides and slide metadata
- Export presentations (PPTX / Google Slides)
- Add comments, replies, and @mentions
- Edit and delete your own comments

**What you CANNOT do:**
- Edit slides (directly or via chat)
- Reorder or duplicate slides
- Delete slides
- Manage deck contributors

#### CAN EDIT

**Best for:** Collaborators who actively work on presentations together.

**Includes everything in CAN VIEW, plus:**
- Edit slides directly and via chat
- Reorder and duplicate slides
- Resolve and unresolve comments

**What you CANNOT do:**
- Delete slides
- Delete other users' comments
- Manage deck contributors
- Delete the deck

#### CAN MANAGE

**Best for:** Deck administrators.

**Includes everything in CAN EDIT, plus:**
- Delete slides
- Delete any comment
- Add, remove, or modify deck contributors
- Delete the deck

---

## Sharing a Profile

Profiles are configuration templates (agent config). Sharing a profile lets others use or modify the template itself.

1. Open the **Profiles** page
2. Find the profile you want to share and click the **Share** button on the profile card
3. Search for a user or group
4. Select the permission level: **CAN USE**, **CAN EDIT**, or **CAN MANAGE**
5. Click **Add**

### Sharing with All Workspace Users

Profiles can optionally be shared with all workspace users at a chosen permission level. Use the **All workspace users** dropdown in the sharing settings to set a global permission level.

Individual contributor entries override the global level if they grant higher access.

### Profile Permission Levels

| Level | Summary |
|-------|---------|
| **CAN USE** | See the profile, load it into sessions, set as personal default |
| **CAN EDIT** | Modify agent config, rename, update description |
| **CAN MANAGE** | Full control including delete and manage sharing |

### Profile Permission Details

#### CAN USE

**Best for:** Consumers who need to use a profile without modifying it.

**What you CAN do:**
- See the profile in your profile list
- View profile configuration (Genie spaces, prompts, styles)
- Load the profile into your own sessions
- Set the profile as your personal default

**What you CANNOT do:**
- Edit profile configuration
- Rename or update the description
- Add or remove contributors
- Delete the profile

#### CAN EDIT

**Includes everything in CAN USE, plus:**
- Edit agent configuration (Genie spaces, prompts, styles)
- Rename the profile and update its description

**What you CANNOT do:**
- Delete the profile
- Manage profile contributors

#### CAN MANAGE

**Includes everything in CAN EDIT, plus:**
- Delete the profile
- Add, remove, or modify profile contributors
- Transfer ownership (add another user with CAN MANAGE)

---

## My Sessions vs Shared with Me

Your session history is divided into two tabs in **View All Decks**:

| Tab | Description |
|-----|-------------|
| **My Sessions** | Sessions you created (full control) |
| **Shared with Me** | Decks that have been shared with you directly |

Each shared deck card shows your permission level.

**Your own sessions:** You always have full control over sessions you created, regardless of any other permissions.

---

## Editing Lock

When multiple users have edit access to the same deck, only one can edit at a time.

**How it works:**
1. The first user to open the session acquires an exclusive editing lock
2. Other users see a banner: "[User] is editing the slides"
3. Locked-out users can still view slides, add comments, @mention others, and export
4. The lock releases automatically when the editor leaves or is idle for 5 minutes
5. Locked-out users automatically acquire the lock once it becomes available

The deck owner has no priority — whoever arrives first gets the lock.

---

## Comments & @Mentions

All users (including CAN VIEW and locked-out users) can add comments and @mentions on any slide.

### Adding a comment
Click the comment icon on any slide tile to open the thread panel.

### @Mentioning a user
Type `@` in the comment input followed by the user's email. A dropdown appears after 2 characters with matching users.

### Notifications
- Each slide has a bell icon that shows unread mention count
- The bell flashes when new mentions arrive (polled every 3 seconds)
- Notifications are scoped to the current deck and slide — mentions from other decks never appear
- Clicking the bell marks mentions as seen

---

## Group Permissions

When you add a Databricks group as a contributor (to either a deck or a profile):

- All members of that group receive the assigned permission
- If a user belongs to multiple groups with different permissions, they get the **highest** level
- Group memberships are cached for 5 minutes

**Example:**
- Group "Sales" has CAN VIEW on a deck
- Group "Managers" has CAN EDIT on the same deck
- User John is in both groups
- John gets CAN EDIT access (the higher permission)

---

## Personal Default Profile

Each user can set their own default profile independently. This controls which profile is loaded when the app starts.

1. Open the profile list
2. Click the menu on the desired profile
3. Select **Set as My Default**

The "Default" badge appears next to your chosen profile. Setting a profile as default requires at least CAN USE permission.

---

## Special Rules

### Session Creator
The user who creates a session automatically gets CAN MANAGE on that deck. This cannot be overridden.

### Profile Creator
The user who creates a profile automatically gets CAN MANAGE on that profile. They cannot be removed as a contributor.

### No Cross-Pollination
Deck and profile permissions are completely independent:
- Sharing a profile does **not** grant access to any deck
- Sharing a deck does **not** grant access to any profile

---

## Common Scenarios

### Scenario 1: Read-Only Stakeholder
A manager wants to review a presentation without editing.
-> Share the **deck** with them at **CAN VIEW**

### Scenario 2: Team Collaboration
Team members need to create and refine a presentation together.
-> Share the **deck** with them at **CAN EDIT**

### Scenario 3: Deck Administrator
Another admin needs to manage the deck if you are unavailable.
-> Share the **deck** with them at **CAN MANAGE**

### Scenario 4: Template Distribution
Your team should use the same agent configuration.
-> Share the **profile** with the team group at **CAN USE**

### Scenario 5: Collaborative Profile Maintenance
Multiple people need to update a shared configuration template.
-> Share the **profile** with them at **CAN EDIT**

### Scenario 6: Company-Wide Template
Everyone in the workspace should be able to use a profile.
-> Set "All workspace users" to **CAN USE** on the profile

---

## See Also

- [Creating Profiles](./02-creating-profiles.md)
- [Advanced Configuration](./03-advanced-configuration.md)
- [Technical Documentation: Permissions Model](../technical/permissions-model.md)
