# Cursor Documentation

Comprehensive Databricks development guides automatically indexed by Cursor for semantic search.

## Available Guides

- **ai-development.md** - LLM integration, RAG systems, Agent Bricks, fine-tuning, prompt engineering, evaluation (67K+ lines)
- **data-engineering.md** - Delta Lake, DLT pipelines, medallion architecture, streaming, optimization
- **ml-engineering.md** - MLflow tracking, Feature Store, model serving, monitoring
- **deployment-ops.md** - Asset Bundles, CI/CD, Terraform, Workflows orchestration
- **governance-security.md** - Unity Catalog, permissions, data lineage, PII protection, compliance
- **platform.md** - Cluster configuration, cost optimization, performance tuning
- **development-standards.md** - Code quality, documentation, workflow patterns

## How Cursor Uses These Docs

Cursor automatically indexes files in `cursor/docs/` for semantic search:

1. **Automatic Indexing**: Cursor scans and indexes these files when you open the workspace
2. **Context-Aware**: When you ask questions or request code, Cursor searches these docs for relevant patterns
3. **Semantic Search**: Uses vector search to find relevant content even with different wording
4. **Code Completion**: Suggestions include patterns from these guides

## Usage Tips

### Search for Patterns
```
"Show me how to implement RAG with Vector Search"
"Create a DLT pipeline with data quality checks"
"Set up MLflow experiment tracking"
```

### Reference in Code
When writing code, Cursor will automatically suggest patterns from these docs based on context.

### Ask Questions
```
"How do I optimize a Delta table?"
"What's the best way to deploy a model?"
"How do I set up row-level security?"
```

## Related Resources

- **Cursor Rules**: See [`../rules/README.md`](../rules/README.md) for project rules
- **Cursor Agents**: See [`../agents/README.md`](../agents/README.md) for specialist agents
- **Cursor Patterns**: See [`../patterns/README.md`](../patterns/README.md) for quick patterns
- **Main README**: See [`../../README.md`](../../README.md) for repository overview
