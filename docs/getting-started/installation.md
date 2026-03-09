# Installation

## Prerequisites

- Databricks workspace with Apps enabled
- Permission to create a Lakebase (or create a schema in an existing one)
- Genie space with your data (optional — tellr works in prompt-only mode without Genie)

## Install

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

## Update or Delete

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

