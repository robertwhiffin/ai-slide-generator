# Databricks Tellr User Guide

Welcome to the Databricks Tellr user guide. This documentation covers the main workflows for using the slide generation application.

## Guides

| Guide | Description |
|-------|-------------|
| [Generating Slides](./01-generating-slides.md) | Learn how to create presentations using AI-powered slide generation |
| [Creating Profiles](./02-creating-profiles.md) | Save and load session configurations as reusable profiles |
| [Advanced Configuration](./03-advanced-configuration.md) | Manage deck prompts and slide styles for customized output |
| [Creating Custom Styles](./05-creating-custom-styles.md) | CSS reference, constraints, and converting existing templates into styles |
| [Uploading Images](./06-uploading-images.md) | Upload, organise, and embed images in AI-generated slides |
| [Exporting to Google Slides](./07-exporting-to-google-slides.md) | Set up Google OAuth and export decks to Google Slides |
| [Profile Sharing Permissions](./08-profile-sharing-permissions.md) | Understand CAN VIEW, CAN EDIT, and CAN MANAGE permission levels |
| [Retrieving Feedback](./04-retrieving-feedback.md) | View the Feedback Dashboard, survey metrics, and AI-generated summaries |

## Quick Start

1. **Open the app** — you land directly on the generator
2. **Add tools** (optional) — click "Add Tool" in the config bar to connect Genie spaces or other data sources
3. **Enter a prompt** — describe the presentation you want to create
4. **Click Send** — a session is created automatically and slides begin generating
5. **Refine** — send follow-up messages to edit, add, or restyle slides

## Regenerating Screenshots

The screenshots in this guide are generated using Playwright. To regenerate them:

```bash
cd frontend
npx playwright test user-guide/ --project=chromium
```

This will capture fresh screenshots reflecting the current UI state.

## Guide Structure

Each guide follows a consistent format:
- **Overview** - What the workflow accomplishes
- **Prerequisites** - What you need before starting
- **Step-by-step instructions** - Numbered steps with screenshots
- **Tips** - Additional guidance and best practices
- **Related guides** - Links to related workflows
