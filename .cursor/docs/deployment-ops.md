# Databricks Deployment & Operations Guide

Comprehensive guide to deployment, CI/CD, infrastructure as code, and orchestration on Databricks.

## Overview

Production deployment, CI/CD, infrastructure as code, and orchestration patterns for Databricks.

## Quick Start Patterns

### Asset Bundle Deployment

```yaml
# databricks.yml
bundle:
  name: fraud-detection

resources:
  jobs:
    training_job:
      name: fraud-detection-training
      tasks:
        - task_key: train
          notebook_task:
            notebook_path: ./notebooks/train.py
          new_cluster:
            node_type_id: i3.xlarge
            num_workers: 2

  pipelines:
    feature_pipeline:
      name: feature-engineering-pipeline
      libraries:
        - notebook:
            path: ./pipelines/features.py
```

```bash
# Deploy
databricks bundle deploy --target prod

# Run job
databricks bundle run training_job --target prod
```

### Workflows (Jobs) Orchestration

```python
from databricks.sdk import WorkspaceClient

w = WorkspaceClient()

w.jobs.create(
    name="daily-etl-pipeline",
    tasks=[
        {
            "task_key": "bronze_ingestion",
            "notebook_task": {"notebook_path": "/Workspace/etl/bronze"},
            "new_cluster": {"node_type_id": "i3.xlarge", "num_workers": 2}
        },
        {
            "task_key": "silver_transformation",
            "depends_on": [{"task_key": "bronze_ingestion"}],
            "notebook_task": {"notebook_path": "/Workspace/etl/silver"}
        }
    ],
    schedule={"quartz_cron_expression": "0 0 * * *", "timezone_id": "UTC"}
)
```

### Terraform Configuration

```hcl
resource "databricks_job" "etl_pipeline" {
  name = "production-etl-pipeline"
  
  task {
    task_key = "ingest"
    
    new_cluster {
      node_type_id   = "i3.xlarge"
      spark_version  = "13.3.x-scala2.12"
      num_workers    = 2
    }
    
    notebook_task {
      notebook_path = "/Workspace/etl/ingest"
    }
  }
}
```

## Core Capabilities

- **Asset Bundles**: Git-based deployment, multi-environment configs
- **CI/CD**: GitHub Actions, GitLab CI, Azure DevOps integration
- **Terraform**: Infrastructure as code for Databricks resources
- **Workflows**: Multi-task orchestration with dependencies
- **Monitoring**: Job metrics, cluster health, cost tracking
- **Databricks Apps**: Internal apps with Gradio, Streamlit, Dash

## References

- [Asset Bundles](https://docs.databricks.com/dev-tools/bundles/)
- [Workflows](https://docs.databricks.com/workflows/)
- [Terraform Provider](https://registry.terraform.io/providers/databricks/databricks/)
- [Databricks Apps](https://docs.databricks.com/en/dev-tools/databricks-apps/)

