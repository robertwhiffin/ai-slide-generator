# Databricks tellr

**Turn hours of slide work into minutes.** Generate presentation-ready slides from your enterprise data through natural conversation — while respecting Unity Catalog permissions.

---

## The Problem

Your teams spend hours every week building slides from enterprise data. They pull numbers from dashboards, copy-paste charts, write narratives, and fight with formatting.

AI slide generators exist — but they can't touch your governed data without breaking security controls.

## The Solution

**tellr** is an agentic application that generates data-driven presentations from your Databricks environment:

- **Connected to your data** — Queries your Genie spaces for live, governed data
- **Respects permissions** — Uses Unity Catalog security out of the box
- **Conversational editing** — Refine slides through natural language ("add a comparison to Q3", "make the EMEA section more prominent")
- **Prompt-only mode** — Works without Genie for general-purpose slide generation

tellr is the third pillar in Databricks' AI/BI suite, completing the story alongside Genie and Dashboards: conversational analytics, conversational dashboards, and now **conversational presentations**.

---

## Getting Started

### Prerequisites

- Databricks workspace with Apps enabled
- Permission to create a Lakebase (or create a schema in an existing one)
- Genie space with your data (optional — tellr works in prompt-only mode without Genie)

### Install

From a **Databricks notebook**:

```python
%pip install --upgrade databricks-tellr databricks-sdk==0.73.0
dbutils.library.restartPython()
```

```python
import databricks_tellr as tellr

# Deploy tellr to your workspace
tellr.create(
    lakebase_name="tellr-db",
    schema_name="app_data",
    app_name="tellr",
    app_file_workspace_path="/Workspace/Users/you@example.com/.apps/tellr"
)
```

That's it. Open your Databricks Apps to find tellr running.

### Update or Delete

```python
# Update an existing deployment
tellr.update(
    app_name="tellr",
    app_file_workspace_path="/Workspace/Users/you@example.com/.apps/tellr",
    lakebase_name="tellr-db",
    schema_name="app_data",
)

# Delete (optionally reset database)
tellr.delete(
    app_name="tellr",
    lakebase_name="tellr-db",
    schema_name="app_data",
    reset_database=True,
)
```

---

## User Guide

Step-by-step instructions with screenshots:

| Guide | Description |
|-------|-------------|
| [Generating Slides](docs/user-guide/01-generating-slides.md) | Create presentations through conversation |
| [Creating Profiles](docs/user-guide/02-creating-profiles.md) | Configure data sources, styles, and templates |
| [Advanced Configuration](docs/user-guide/03-advanced-configuration.md) | Customize deck prompts and slide styles |

**Quick start:**
1. Select or create a profile (bundles your Genie space, slide style, and deck prompt)
2. Click **New Session**
3. Describe the presentation you want
4. Send — watch slides stream in
5. Refine through conversation

---

## How It Works

```
┌─────────────────────────────────────────────────────────────────────┐
│  You: "Create a 10-slide presentation about Q3 revenue trends"     │
└──────────────────────────┬──────────────────────────────────────────┘
                           ▼
┌─────────────────────────────────────────────────────────────────────┐
│  tellr Agent (LangChain)                                            │
│  ├─ Queries Genie for live data (respects Unity Catalog perms)     │
│  ├─ Analyzes patterns, generates insights                          │
│  └─ Produces HTML slides with Chart.js visualizations              │
└──────────────────────────┬──────────────────────────────────────────┘
                           ▼
┌─────────────────────────────────────────────────────────────────────┐
│  Interactive slide deck you can edit, reorder, and export          │
└─────────────────────────────────────────────────────────────────────┘
```

---

## Documentation

### Technical Docs

| Document | Description |
|----------|-------------|
| [Local Development](docs/local-development.md) | Run tellr locally for development |
| [Backend Overview](docs/technical/backend-overview.md) | FastAPI, agent lifecycle, API contracts |
| [Frontend Overview](docs/technical/frontend-overview.md) | React components, state management |
| [Databricks Deployment](docs/technical/databricks-app-deployment.md) | Deployment CLI, environments |
| [Database Config](docs/technical/database-configuration.md) | PostgreSQL/Lakebase schema |

### More Technical Docs

| Document | Description |
|----------|-------------|
| [Real-Time Streaming](docs/technical/real-time-streaming.md) | SSE events, conversation persistence |
| [Slide Parser](docs/technical/slide-parser-and-script-management.md) | HTML parsing, CSS merging |
| [Slide Editing](docs/technical/slide-editing-robustness-fixes.md) | Deck preservation, validation |
| [Save Points](docs/technical/save-points-versioning.md) | Version snapshots, preview/restore |

---

## Status

tellr is **open source** and in **early-stage development** (equivalent to private preview). We're actively developing new features and welcome feedback.

**Questions?** Reach out to your Databricks account team.

---

## License

Apache 2.0
