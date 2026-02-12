# Databricks Tellr User Guide

Welcome to the Databricks Tellr user guide. This documentation covers the main workflows for using the slide generation application.

## Guides

| Guide | Description |
|-------|-------------|
| [Generating Slides](./01-generating-slides.md) | Learn how to create presentations using AI-powered slide generation |
| [Creating Profiles](./02-creating-profiles.md) | Set up configuration profiles linking Genie rooms, styles, and prompts |
| [Advanced Configuration](./03-advanced-configuration.md) | Manage deck prompts and slide styles for customized output |

## Quick Start

1. **Open the app** - Navigate to the application URL
2. **Select a profile** - Choose a profile that connects to your data source
3. **Go to New Session** - Click **New Session** in the navigation
4. **Enter a prompt** - Describe the presentation you want to create
5. **Send** - Click Send and watch your slides generate

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
