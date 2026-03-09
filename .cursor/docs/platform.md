# Databricks Platform Guide

Comprehensive guide to platform configuration, cluster management, and cost optimization.

## Overview

Platform configuration, cluster management, and cost optimization for Databricks workspaces.

## Quick Start Patterns

### Cluster Configuration

```python
from databricks.sdk import WorkspaceClient

w = WorkspaceClient()

# All-purpose cluster
w.clusters.create(
    cluster_name="ml-training-cluster",
    spark_version="13.3.x-gpu-ml-scala2.12",
    node_type_id="g4dn.xlarge",
    autoscale=AutoScale(min_workers=2, max_workers=8),
    autotermination_minutes=30,
    spark_conf={
        "spark.databricks.delta.preview.enabled": "true",
        "spark.sql.adaptive.enabled": "true"
    },
    aws_attributes=AwsAttributes(availability="SPOT")
)

# Job cluster (ephemeral)
job_cluster = {
    "job_cluster_key": "etl_cluster",
    "new_cluster": {
        "spark_version": "13.3.x-scala2.12",
        "node_type_id": "i3.xlarge",
        "num_workers": 4,
        "spark_conf": {
            "spark.databricks.delta.optimizeWrite.enabled": "true"
        }
    }
}
```

### Cost Optimization

```python
# Use Spot instances for fault-tolerant workloads
aws_attributes = {
    "availability": "SPOT",
    "first_on_demand": 1,  # Keep driver on-demand
    "spot_bid_price_percent": 100
}

# Enable autoscaling
autoscale = {"min_workers": 2, "max_workers": 10}

# Set autotermination
autotermination_minutes = 20

# Use job clusters instead of all-purpose
# Use serverless SQL warehouses for BI
```

### Performance Tuning

```python
# Enable Photon
spark.conf.set("spark.databricks.photon.enabled", "true")

# Adaptive Query Execution
spark.conf.set("spark.sql.adaptive.enabled", "true")
spark.conf.set("spark.sql.adaptive.coalescePartitions.enabled", "true")

# Optimize write performance
spark.conf.set("spark.databricks.delta.optimizeWrite.enabled", "true")
spark.conf.set("spark.databricks.delta.autoCompact.enabled", "true")
```

## Core Capabilities

- **Clusters**: All-purpose, job, serverless SQL warehouses
- **Cost Optimization**: Spot instances, autoscaling, autotermination
- **Performance**: Photon, AQE, caching strategies
- **Workspace**: User management, secrets, repos integration

## References

- [Cluster Configuration](https://docs.databricks.com/clusters/)
- [Cost Optimization](https://docs.databricks.com/administration-guide/cloud-configurations/aws/cost-optimization.html)
- [Performance Tuning](https://docs.databricks.com/optimizations/)

