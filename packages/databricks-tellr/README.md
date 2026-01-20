# databricks-tellr

Python deployment tooling for Tellr on Databricks Apps.

## Usage

```python
import databricks_tellr as tellr

!pip install --upgrade databricks-sdk==0.73.0

result = tellr.setup(
    lakebase_name="ai-slide-generator-db-dev",
    schema_name="app_data_dev",
    app_name="ai-slide-generator-dev",
    app_file_workspace_path="/Workspace/Users/you@example.com/.apps/dev/ai-slide-generator",
)

print(result["url"])
```
