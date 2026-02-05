# How It Works

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

## Overview

**tellr** is an agentic application that generates data-driven presentations from your Databricks environment:

- **Connected to your data** — Queries your Genie spaces for live, governed data
- **Respects permissions** — Uses Unity Catalog security out of the box
- **Conversational editing** — Refine slides through natural language ("add a comparison to Q3", "make the EMEA section more prominent")
- **Prompt-only mode** — Works without Genie for general-purpose slide generation

tellr is the third pillar in Databricks' AI/BI suite, completing the story alongside Genie and Dashboards: conversational analytics, conversational dashboards, and now **conversational presentations**.

