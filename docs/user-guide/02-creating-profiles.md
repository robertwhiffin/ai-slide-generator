# Saving and Loading Configurations

This guide explains how to save and load configuration snapshots (profiles) in Databricks Tellr.

## Overview

Each session carries its own agent configuration that controls:
- **Tools** - Genie spaces and MCP servers for data queries
- **Slide Style** - CSS styling for generated slides
- **Deck Prompt** - Template that guides slide structure

You can save a session's configuration as a named **profile** for reuse, or load a previously saved profile into any session. Profiles are optional -- you can start generating slides immediately without one.

## Prerequisites

- Access to Databricks Tellr
- An active session (created automatically on first message)

## Configuring a Session

### Step 01: Open the AgentConfigBar

The AgentConfigBar at the top of the generator shows your current session's tools and settings. From here you can add Genie spaces, select a slide style, and choose a deck prompt.

### Step 02: Add Data Sources

Click the add button to browse available Genie spaces and MCP servers. Select one or more to add them to your session. Each Genie space appears as a chip in the toolbar.

### Step 03: Select Style and Prompt

Use the AgentConfigBar to pick a slide style (visual appearance) and optionally a deck prompt (content template). New sessions pre-fill with your personal default if you've set one, otherwise with the organization's corporate default — see [Creating Custom Slide Styles → Defaults: corporate vs. personal](./05-creating-custom-styles.md#defaults-corporate-vs-personal) for how those two levels work.

## Saving a Configuration as a Profile

Once you have a session configured the way you want, you can save it as a reusable profile.

### Step 04: Save as Profile

Click "Save as Profile" in the AgentConfigBar or profile menu. Enter a name and optional description, then save. The current session's entire agent configuration is snapshotted.

## Loading a Saved Profile

### Step 05: Browse Profiles

Click the profile menu to see available saved profiles.

### Step 06: Load Profile

Select a profile to load its configuration into your current session. This replaces the session's tools, style, and prompt settings with those from the profile. Genie conversation IDs are reset (new conversations will be initialized on the next query).

## Managing Profiles

### View All Profiles

Navigate to "Profiles" in the navigation bar to see all saved profiles.

### Edit a Profile

Select a profile to update its name or description.

### Delete a Profile

Remove profiles you no longer need. This does not affect sessions that previously loaded from the profile.

## Configuration Reference

| Setting | Description | Stored In |
|---------|-------------|-----------|
| Tools | Genie spaces and MCP servers | `agent_config.tools` |
| Slide Style | Visual styling | `agent_config.slide_style_id` |
| Deck Prompt | Generation template | `agent_config.deck_prompt_id` |
| System Prompt | Custom system instructions (advanced) | `agent_config.system_prompt` |

## Tips

- **Start without a profile**: Just open the app and start chatting -- configure tools as needed
- **Save after tuning**: Once you find a good combination of tools and settings, save it as a profile
- **Multiple Genie spaces**: A single session can query multiple Genie spaces simultaneously
- **Quick context switch**: Load different profiles to switch between reporting workflows

## Related Guides

- [Generating Slides](./01-generating-slides.md) - Create presentations with your configuration
- [Advanced Configuration](./03-advanced-configuration.md) - Create custom prompts and styles
