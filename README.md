# Databricks tellr

**Turn hours of slide work into minutes.** Generate presentation-ready slides from your enterprise data through natural conversation — while respecting Unity Catalog permissions.

---

## The Problem

Your teams spend hours every week building slides from enterprise data. They pull numbers from dashboards, copy-paste charts, write narratives, and fight with formatting.

AI slide generators exist — but they can't touch your governed data without breaking security controls.

## The Solution

**tellr** is an agentic application that generates data-driven presentations from your Databricks environment:

- **Connected to your data** — Queries your Genie agents for live, governed data
- **Respects permissions** — Uses Unity Catalog security out of the box
- **Conversational editing** — Refine slides through natural language ("add a comparison to Q3", "make the EMEA section more prominent")
- **Prompt-only mode** — Works without Genie for general-purpose slide generation
- **Agent-ready** — Call tellr from other Databricks Apps or MCP-compatible agents (Claude Code, Cursor) via a Model Context Protocol server. Programmatically generated decks are attributed to the end user and appear alongside UI-created ones. See the [MCP Integration Guide](docs/technical/mcp-integration-guide.md).

tellr is the third pillar in Databricks' AI/BI suite, completing the story alongside Genie and Dashboards: conversational analytics, conversational dashboards, and now **conversational presentations**.

---

## Getting Started

### Prerequisites

- Databricks workspace with Apps enabled
- Permission to create a Lakebase (or create a schema in an existing one)
- Genie agent with your data (optional — tellr works in prompt-only mode without Genie)

### Install

From a **Databricks notebook**:

```python
%pip install --upgrade databricks-tellr databricks-sdk==0.96.0
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

**Slide verification:** By default tellr uses **MLflow** LLM-as-judge (`mlflow.genai.evaluate`, Evaluation Runs). Admins can switch to **Direct** (ChatDatabricks only) under Admin → Judge when regional storage egress is blocked or MLflow evaluate is unreliable; with **Direct**, Tellr also skips MLflow trace spans around **Genie / slide generation** by default (see `src/core/mlflow_agent_spans.py`). Ratings include **unable to verify** when there is no substantive source data. See [`docs/technical/llm-as-judge-verification.md`](docs/technical/llm-as-judge-verification.md).

**Optional — MLflow traces in Unity Catalog:** For production, you can route GenAI traces to UC Delta tables (recommended for some Apps deployments). Configure `mlflow_tracing` in `config/deployment.yaml`, set `TELLR_DEPLOY_MLFLOW_*` env vars at deploy time, or pass `mlflow_tracing={...}` to `tellr.create` / `tellr.update`. See [`docs/technical/mlflow-uc-tracing.md`](docs/technical/mlflow-uc-tracing.md).

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
| [Retrieving Feedback](docs/user-guide/04-retrieving-feedback.md) | Review and export deck feedback |
| [Creating Custom Styles](docs/user-guide/05-creating-custom-styles.md) | Build a slide style, and how defaults resolve |
| [Uploading Images](docs/user-guide/06-uploading-images.md) | Add images and reference them in slides |
| [Exporting to Google Slides](docs/user-guide/07-exporting-to-google-slides.md) | Authorize once, then export to Drive |
| [Profile Sharing & Permissions](docs/user-guide/08-profile-sharing-permissions.md) | Share a profile and what each role can do |
| [Design Systems](docs/user-guide/09-design-systems.md) | Upload a brand bundle, set your default, pin a template |

**Quick start:**
1. Select or create a profile (bundles your Genie agent, slide style, and deck prompt)
2. Go to Generator
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
| [Local Development](docs/getting-started/local-development.md) | Run tellr locally for development |
| [Backend Overview](docs/technical/backend-overview.md) | FastAPI, agent lifecycle, API contracts |
| [Frontend Overview](docs/technical/frontend-overview.md) | React components, state management |
| [Databricks Deployment](docs/technical/databricks-app-deployment.md) | Deployment CLI, environments |
| [MCP Integration Guide](docs/technical/mcp-integration-guide.md) | How-to: wire tellr into your Databricks App or into an MCP client like Claude Code |
| [MCP Server Reference](docs/technical/mcp-server.md) | Protocol, tool schemas, response payloads |
| [Database Config](docs/technical/database-configuration.md) | PostgreSQL/Lakebase schema |
| [Design System Library](docs/technical/design-system-library.md) | Brand bundles: default precedence, authorization, retention, the compiled artifact |
| [Design System Bundle Format](docs/technical/design-system-bundle-format.md) | The bundle contract: folder allowlist, `.thumbnail`, tokens, import refusals |

### More Technical Docs

| Document | Description |
|----------|-------------|
| [Real-Time Streaming](docs/technical/real-time-streaming.md) | SSE events, conversation persistence |
| [Slide Parser](docs/technical/slide-parser-and-script-management.md) | HTML parsing, CSS merging |
| [Slide Editing](docs/technical/slide-editing-robustness-fixes.md) | Deck preservation, validation |
| [Save Points](docs/technical/save-points-versioning.md) | Version snapshots, preview/restore |
| [Google Slides](docs/technical/google-slides-integration.md) | OAuth2 flow, encrypted credentials, LLM export |
| [Export Features](docs/technical/export-features.md) | The export routes, which are live, and per-route fidelity |
| [Slide Host Frame Contract](docs/technical/slide-host-frame-contract.md) | Frame geometry, box model, and scoped resets across every surface |

---

## Status

tellr is **open source** and in **early-stage development** (equivalent to private preview). We're actively developing new features and welcome feedback.

**Questions?** Reach out to your Databricks account team.

---

## License

Apache 2.0
