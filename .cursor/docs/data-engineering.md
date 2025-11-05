# Databricks Data Engineering Guide

Comprehensive guide to production data engineering with Delta Lake, declarative pipelines, and medallion architecture.

## Overview

Production data engineering with Delta Lake, declarative pipelines, and medallion architecture.

## Quick Start Patterns

### Basic Medallion Flow

```python
from pyspark.sql.functions import current_timestamp, input_file_name

# BRONZE: Raw ingestion with Auto Loader
bronze_df = spark.readStream.format("cloudFiles") \
    .option("cloudFiles.format", "json") \
    .option("cloudFiles.schemaLocation", "/Volumes/catalog/checkpoints/bronze/") \
    .load("/Volumes/catalog/landing/") \
    .withColumn("_ingestion_timestamp", current_timestamp()) \
    .withColumn("_source_file", input_file_name())

bronze_df.writeStream.format("delta") \
    .option("checkpointLocation", "/Volumes/catalog/checkpoints/bronze/") \
    .toTable("catalog.bronze.raw_events")

# SILVER: Cleaned and deduplicated
silver_df = spark.readStream.table("catalog.bronze.raw_events") \
    .filter("event_id IS NOT NULL") \
    .dropDuplicates(["event_id"]) \
    .select("event_id", "user_id", "event_type", "event_timestamp")

silver_df.writeStream.format("delta") \
    .option("checkpointLocation", "/Volumes/catalog/checkpoints/silver/") \
    .toTable("catalog.silver.cleaned_events")

# GOLD: Business aggregates
gold_df = spark.read.table("catalog.silver.cleaned_events") \
    .groupBy("user_id", "event_type") \
    .agg(count("*").alias("event_count"))

gold_df.write.format("delta").mode("overwrite") \
    .saveAsTable("catalog.gold.user_metrics")
```

### DLT Pipeline

```python
import dlt
from pyspark.sql.functions import *

@dlt.table(name="bronze_orders")
def bronze_orders():
    return spark.readStream.format("cloudFiles") \
        .option("cloudFiles.format", "json") \
        .load("/Volumes/catalog/landing/orders/")

@dlt.table(name="silver_orders")
@dlt.expect_or_drop("valid_order_id", "order_id IS NOT NULL")
@dlt.expect_or_drop("valid_amount", "order_amount > 0")
def silver_orders():
    return dlt.read_stream("bronze_orders") \
        .select("order_id", "customer_id", "order_amount", "order_date") \
        .dropDuplicates(["order_id"])

@dlt.table(name="gold_daily_revenue")
def gold_daily_revenue():
    return dlt.read("silver_orders") \
        .groupBy("order_date") \
        .agg(sum("order_amount").alias("total_revenue"))
```

## Core Capabilities

### Delta Lake Operations
- ACID transactions with versioning and time travel
- MERGE operations for upserts and SCD Type 1/2
- Schema evolution with `mergeSchema` option
- Deletion vectors for fast DELETE operations

### Delta Live Tables
- Declarative ETL with `@dlt.table` decorators
- Data quality with expectations (`expect_or_drop`, `expect_or_fail`)
- SCD Type 2 with `apply_changes`
- Auto Loader integration for incremental ingestion

### Medallion Architecture
- **Bronze**: Raw data, minimal transformation, full history
- **Silver**: Cleaned, validated, deduplicated
- **Gold**: Business aggregates for analytics/ML

### Structured Streaming
- Auto Loader for incremental file ingestion
- Watermarks for late data handling
- Windowed aggregations (tumbling, sliding)
- Stream-stream and stream-static joins

### Optimization
- Liquid clustering (dynamic, self-optimizing)
- Z-Ordering (legacy, for specific columns)
- File compaction with OPTIMIZE
- Predictive optimization (auto-OPTIMIZE)

## Detailed References

### Delta Lake
See [reference/delta-lake.md](reference/delta-lake.md) for:
- MERGE operations and SCD patterns
- Time travel and versioning
- Change Data Feed (CDC)
- Table constraints and validation

### Delta Live Tables
See [reference/delta-live-tables.md](reference/delta-live-tables.md) for:
- Pipeline definition patterns
- Expectations and quality checks
- Triggered vs continuous modes
- Monitoring and troubleshooting

### Medallion Architecture
See [reference/medallion-architecture.md](reference/medallion-architecture.md) for:
- Layer design principles
- Unity Catalog structure
- Quality gates between layers
- Cost optimization strategies

### Structured Streaming
See [reference/streaming.md](reference/streaming.md) for:
- Auto Loader configuration
- Watermark strategies
- Stateful processing
- Performance tuning

### Optimization
See [reference/optimization.md](reference/optimization.md) for:
- Liquid clustering setup
- File compaction strategies
- Query performance tuning
- Storage cost reduction

## Common Patterns

### Incremental Upsert with MERGE
```python
from delta.tables import DeltaTable

target = DeltaTable.forName(spark, "catalog.silver.customers")
updates_df = spark.read.table("catalog.bronze.customer_updates")

target.alias("target").merge(
    updates_df.alias("updates"),
    "target.customer_id = updates.customer_id"
).whenMatchedUpdateAll() \
 .whenNotMatchedInsertAll() \
 .execute()
```

### Streaming Deduplication
```python
df = spark.readStream.table("catalog.bronze.events") \
    .withWatermark("event_timestamp", "1 hour") \
    .dropDuplicates(["event_id", "event_timestamp"])
```

### Liquid Clustering
```sql
CREATE TABLE catalog.silver.orders (
    order_id STRING,
    customer_id STRING,
    order_date DATE
) CLUSTER BY (customer_id, order_date);

-- Auto-optimized on writes, no manual OPTIMIZE needed
```

## Key Anti-Patterns

- ❌ Writing Parquet directly → ✅ Always use Delta Lake
- ❌ No medallion layers → ✅ Implement Bronze-Silver-Gold
- ❌ Ignoring data quality → ✅ Use DLT expectations
- ❌ No checkpoints in streaming → ✅ Always specify checkpoint location
- ❌ Over-partitioning → ✅ Use liquid clustering
- ❌ No optimization → ✅ Enable predictive optimization
- ❌ Full table scans → ✅ Use partition pruning and clustering

## Integration Points

**Works with:**
- **databricks-ai-development**: Provides data for ML training
- **databricks-ml-engineering**: Feature engineering pipelines
- **databricks-governance-security**: Unity Catalog permissions

## References

- [Delta Lake Guide](https://docs.databricks.com/delta/)
- [Delta Live Tables](https://docs.databricks.com/workflows/delta-live-tables/)
- [Structured Streaming](https://docs.databricks.com/structured-streaming/)
- [Liquid Clustering](https://docs.databricks.com/optimizations/liquid-clustering.html)
- [Medallion Architecture](https://www.databricks.com/glossary/medallion-architecture)

# Delta Lake - ACID Transactions & Operations

Delta Lake provides ACID guarantees for data lakes.

## MERGE Operations

```python
from delta.tables import DeltaTable

target = DeltaTable.forName(spark, "catalog.silver.customers")

# SCD Type 1: Update existing, insert new
target.alias("t").merge(updates_df.alias("u"), "t.id = u.id") \
    .whenMatchedUpdateAll() \
    .whenNotMatchedInsertAll() \
    .execute()

# SCD Type 2: Track history
target.alias("t").merge(updates_df.alias("u"), "t.id = u.id AND t.is_current = true") \
    .whenMatchedUpdate(set={
        "is_current": "false",
        "end_date": "current_date()"
    }) \
    .whenNotMatchedInsertAll() \
    .execute()
```

## Time Travel

```sql
-- Query historical version
SELECT * FROM catalog.silver.customers VERSION AS OF 100;

-- Query as of timestamp
SELECT * FROM catalog.silver.customers TIMESTAMP AS OF '2024-10-30';

-- Restore to previous version
RESTORE TABLE catalog.silver.customers TO VERSION AS OF 100;
```

## Change Data Feed

```sql
-- Enable CDF
ALTER TABLE catalog.silver.customers
SET TBLPROPERTIES (delta.enableChangeDataFeed = true);

-- Query changes
SELECT * FROM table_changes('catalog.silver.customers', 100)
WHERE _change_type IN ('insert', 'update_postimage');
```

## Table Constraints

```sql
-- NOT NULL constraint
ALTER TABLE catalog.silver.orders
ADD CONSTRAINT valid_order_id CHECK (order_id IS NOT NULL);

-- Business rule constraint
ALTER TABLE catalog.silver.orders
ADD CONSTRAINT positive_amount CHECK (order_amount > 0);
```

# Delta Live Tables - Declarative Pipelines

DLT provides declarative ETL with built-in quality checks.

## Basic Pipeline

```python
import dlt
from pyspark.sql.functions import *

@dlt.table(name="bronze_events")
def bronze_events():
    return spark.readStream.format("cloudFiles") \
        .option("cloudFiles.format", "json") \
        .load("/Volumes/catalog/landing/events/")

@dlt.table(name="silver_events")
@dlt.expect_or_drop("valid_id", "event_id IS NOT NULL")
@dlt.expect("valid_timestamp", "event_timestamp IS NOT NULL")
def silver_events():
    return dlt.read_stream("bronze_events") \
        .dropDuplicates(["event_id"])
```

## Data Quality Expectations

```python
# Drop invalid records
@dlt.expect_or_drop("valid_email", "email RLIKE '^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\\.[a-zA-Z]{2,}$'")

# Fail pipeline on critical violations
@dlt.expect_or_fail("no_pii", "text NOT RLIKE '\\b\\d{3}-\\d{2}-\\d{4}\\b'")

# Track but don't block
@dlt.expect("reasonable_value", "value >= 0 AND value <= 1000000")

# Multiple checks
@dlt.expect_all({
    "valid_id": "id IS NOT NULL",
    "valid_date": "date >= '2020-01-01'"
})
```

## SCD Type 2 with apply_changes

```python
dlt.create_streaming_table("silver_customers")

dlt.apply_changes(
    target="silver_customers",
    source="customer_updates",
    keys=["customer_id"],
    sequence_by="updated_timestamp",
    stored_as_scd_type="2",
    track_history_column_list=["email", "address", "phone"]
)
```

# Medallion Architecture - Bronze-Silver-Gold

Three-layer design for progressive data quality improvement.

## Layer Definitions

**Bronze (Raw Zone)**
- Purpose: Exact copy of source, minimal transformation
- Format: Delta Lake with schema-on-read
- Retention: Long-term (years)
- Example: `dev_catalog.bronze.raw_events`

**Silver (Cleaned Zone)**
- Purpose: Validated, deduplicated, conformed
- Format: Delta Lake with enforced schema
- Retention: Medium-term (months to years)
- Example: `dev_catalog.silver.cleaned_events`

**Gold (Business Zone)**
- Purpose: Business aggregates and feature tables
- Format: Delta Lake optimized for queries
- Retention: Long-term with optimization
- Example: `dev_catalog.gold.customer_360`

## Unity Catalog Structure

```
main (catalog)
  ├── bronze (schema) - raw data
  ├── silver (schema) - cleaned data
  └── gold (schema) - aggregated data
```

## Quality Gates

**Bronze → Silver:**
- Remove nulls in primary keys
- Deduplicate records
- Validate data types
- Apply business rules

**Silver → Gold:**
- Aggregate to business metrics
- Join with dimension tables
- Apply business logic
- Optimize for analytics
```

# Structured Streaming - Real-Time Processing

Real-time data processing with Structured Streaming and Auto Loader.

## Auto Loader

```python
df = spark.readStream.format("cloudFiles") \
    .option("cloudFiles.format", "json") \
    .option("cloudFiles.schemaLocation", "/mnt/checkpoints/schema") \
    .option("cloudFiles.inferColumnTypes", "true") \
    .option("cloudFiles.useNotifications", "true") \
    .load("/mnt/landing/events/")

df.writeStream.format("delta") \
    .option("checkpointLocation", "/mnt/checkpoints/events") \
    .toTable("catalog.bronze.events")
```

## Watermarks & Late Data

```python
df = spark.readStream.table("catalog.bronze.events") \
    .withWatermark("event_timestamp", "1 hour") \
    .groupBy(window("event_timestamp", "10 minutes"), "event_type") \
    .agg(count("*").alias("count"))
```

## Stream-Stream Joins

```python
events = spark.readStream.table("catalog.bronze.events") \
    .withWatermark("event_timestamp", "2 hours")

clicks = spark.readStream.table("catalog.bronze.clicks") \
    .withWatermark("click_timestamp", "2 hours")

joined = events.join(clicks,
    expr("events.user_id = clicks.user_id AND " +
         "events.event_timestamp >= clicks.click_timestamp AND " +
         "events.event_timestamp <= clicks.click_timestamp + interval 1 hour"))
```

# Data Optimization - Performance & Cost

Optimize tables for query performance and storage efficiency.

## Liquid Clustering (Recommended)

```sql
-- Create with clustering
CREATE TABLE catalog.silver.orders (
    order_id STRING,
    customer_id STRING,
    order_date DATE
) CLUSTER BY (customer_id, order_date);

-- Convert existing table
ALTER TABLE catalog.silver.orders CLUSTER BY (customer_id, order_date);

-- Auto-optimized on writes
```

## File Compaction

```sql
-- Compact small files
OPTIMIZE catalog.silver.orders;

-- Optimize specific partition
OPTIMIZE catalog.silver.orders
WHERE order_date >= '2024-01-01';

-- Enable auto-optimization
ALTER TABLE catalog.silver.orders SET TBLPROPERTIES (
    'delta.autoOptimize.optimizeWrite' = 'true',
    'delta.autoOptimize.autoCompact' = 'true'
);
```

## Storage Cleanup

```sql
-- Remove old file versions (preserves time travel)
VACUUM catalog.silver.orders RETAIN 168 HOURS;  -- 7 days

-- Shallow clone for testing (metadata only)
CREATE TABLE catalog.dev.orders_test SHALLOW CLONE catalog.prod.orders;
```

## Query Performance

```python
# Enable Photon
spark.conf.set("spark.databricks.photon.enabled", "true")

# Partition pruning
df = spark.read.table("catalog.silver.events") \
    .filter(col("event_date").between("2024-10-01", "2024-10-31"))

# Column pruning (read only needed columns)
df = spark.read.table("catalog.silver.events") \
    .select("event_id", "user_id", "event_timestamp")
```

