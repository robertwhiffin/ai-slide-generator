# Databricks AI Development Guide

Comprehensive guide to building production AI applications on Databricks with LLMs, RAG, agents, and fine-tuned models.

## Overview

Build production AI applications on Databricks with LLMs, RAG, agents, and fine-tuned models.

## Quick Start Patterns

### LLM Invocation

```python
import mlflow.deployments

client = mlflow.deployments.get_deploy_client("databricks")

response = client.predict(
    endpoint="databricks-llama-2-70b-chat",
    inputs={
        "messages": [
            {"role": "system", "content": "You are a helpful assistant."},
            {"role": "user", "content": "Explain RAG systems"}
        ],
        "temperature": 0.7,
        "max_tokens": 500
    }
)
```

### Basic RAG Query

```python
from databricks.vector_search.client import VectorSearchClient

vsc = VectorSearchClient()
index = vsc.get_index("main.rag.knowledge_base_index")

# Retrieve relevant documents
results = index.similarity_search(
    query_text="What is Delta Lake?",
    columns=["text", "source_doc"],
    num_results=5
)

# Generate answer with LLM
context = "\n\n".join([doc['text'] for doc in results['result']['data_array']])
answer = client.predict(
    endpoint="databricks-llama-2-70b-chat",
    inputs={"messages": [{"role": "user", "content": f"Context: {context}\n\nQuestion: What is Delta Lake?"}]}
)
```

## Core Capabilities

### Foundation Model API & LLMs
- **Model Access**: Foundation Model API for Llama, DBRX, Mistral, external models
- **Endpoints**: Model Serving for custom model deployment
- **Batch Processing**: Spark UDFs for large-scale inference

### RAG Systems
- **Vector Search**: Delta Sync indexes with managed embeddings
- **Chunking**: Semantic splitting with RecursiveCharacterTextSplitter
- **Context Assembly**: Retrieved document formatting
- **Hybrid Search**: Vector similarity + metadata filtering

### Agent Bricks
- **Information Extraction**: Transform documents to structured tables
- **Custom LLM**: Domain-specific text generation/classification
- **Knowledge Assistant**: Q&A over enterprise documents with citations
- **Multi-Agent Supervisor**: Orchestrate complex workflows

### Agent Frameworks
- **LangChain**: ReAct agents, chain-based workflows, tool calling
- **LlamaIndex**: Multi-document agents, advanced retrieval
- **Memory**: Conversation history, long-term storage
- **Tools**: SQL, Vector Search, API integrations

### Fine-Tuning
- **PEFT**: LoRA, QLoRA for memory-efficient training
- **Infrastructure**: A10/A100 GPU selection, multi-GPU coordination
- **Deployment**: Model Serving endpoints for trained models

### Prompt Engineering
- **Techniques**: Zero-shot, few-shot, chain-of-thought, self-consistency
- **Optimization**: Token reduction, format enforcement, temperature tuning
- **Templates**: Version-controlled, parameterized prompts

### Evaluation
- **MLflow**: Built-in metrics (relevance, faithfulness, toxicity)
- **LLM-as-Judge**: Powerful models evaluate other models
- **Continuous Monitoring**: Daily quality checks, drift detection

## Detailed References

### Agent Bricks
See [reference/agentbricks.md](reference/agentbricks.md) for:
- One-click agent deployment
- Information Extraction setup
- Custom LLM configuration
- Knowledge Assistant implementation
- Multi-Agent Supervisor orchestration

### Agent Frameworks  
See [reference/agent-frameworks.md](reference/agent-frameworks.md) for:
- LangChain ReAct agent patterns
- LlamaIndex multi-document agents
- Conversation memory management
- Custom tool development
- Production best practices

### RAG Systems
See [reference/rag-systems.md](reference/rag-systems.md) for:
- Delta Live Tables ingestion pipelines
- Chunking strategies and optimization
- Retrieval optimization patterns
- Context assembly techniques
- Quality evaluation frameworks

### Vector Search & Embeddings
See [reference/vector-search.md](reference/vector-search.md) for:
- Delta Sync vs Direct Access indexes
- Embedding model selection (BGE, GTE)
- Hybrid search with metadata filters
- Performance tuning strategies
- Dimension tradeoffs

### LLM Fine-Tuning
See [reference/llm-fine-tuning.md](reference/llm-fine-tuning.md) for:
- LoRA configuration (ranks, alpha, target modules)
- QLoRA for 70B models (4-bit quantization)
- Memory optimization strategies
- Training on custom datasets
- Model deployment patterns

### Prompt Engineering
See [reference/prompt-engineering.md](reference/prompt-engineering.md) for:
- Zero-shot to few-shot progression
- Chain-of-thought for complex reasoning
- JSON schema enforcement
- Token optimization (30-50% savings)
- Dynamic prompt selection

### LLM Evaluation
See [reference/llm-evaluation.md](reference/llm-evaluation.md) for:
- MLflow evaluation metrics
- LLM-as-judge patterns
- Continuous evaluation pipelines
- A/B testing frameworks
- Quality threshold alerting

## Guardrails & Safety

### Input Validation
```python
def validate_input(user_input: str) -> tuple[bool, str]:
    # Check length
    if len(user_input) > 10000:
        return False, "Input too long"
    
    # Check for prompt injection
    injection_patterns = [
        r"ignore previous instructions",
        r"disregard all prior",
        r"system:\s*you are now"
    ]
    
    for pattern in injection_patterns:
        if re.search(pattern, user_input, re.IGNORECASE):
            return False, "Potential prompt injection detected"
    
    return True, "Valid"
```

### Output Filtering
```python
def filter_output(llm_response: str) -> str:
    import re
    # Mask PII
    llm_response = re.sub(r'\b\d{3}-\d{2}-\d{4}\b', 'XXX-XX-XXXX', llm_response)
    llm_response = re.sub(r'\b\d{16}\b', 'XXXX-XXXX-XXXX-XXXX', llm_response)
    return llm_response
```

## Common Patterns

### Batch LLM Processing
```python
from pyspark.sql.functions import pandas_udf
import pandas as pd

@pandas_udf("string")
def generate_summaries(texts: pd.Series) -> pd.Series:
    client = mlflow.deployments.get_deploy_client("databricks")
    summaries = []
    for text in texts:
        response = client.predict(
            endpoint="databricks-llama-2-70b-chat",
            inputs={"messages": [{"role": "user", "content": f"Summarize: {text}"}]}
        )
        summaries.append(response['choices'][0]['message']['content'])
    return pd.Series(summaries)

df.withColumn("summary", generate_summaries(col("text")))
```

### Multi-Turn Agent with Memory
```python
from langchain.memory import ConversationBufferMemory
from langchain.agents import AgentExecutor

memory = ConversationBufferMemory(
    memory_key="chat_history",
    return_messages=True,
    max_token_limit=2000
)

agent_executor = AgentExecutor(
    agent=agent,
    tools=tools,
    memory=memory,
    verbose=True
)

# Multi-turn conversation maintains context
agent_executor.invoke({"input": "What is our Q4 revenue?"})
agent_executor.invoke({"input": "How does that compare to Q3?"})
```

### RAG with Filtering
```python
def filtered_rag_query(question: str, category: str = None):
    # Build filters
    filters = {"category": category} if category else {}
    
    # Retrieve with filters (10-100x faster)
    results = index.similarity_search(
        query_text=question,
        filters=filters,
        num_results=5
    )
    
    # Generate answer
    context = "\n\n".join([doc['text'] for doc in results['result']['data_array']])
    answer = generate_answer(context, question)
    
    return {"answer": answer, "sources": [doc['source'] for doc in results['result']['data_array']]}
```

## Key Anti-Patterns

- ❌ Not using Vector Search for RAG → ✅ Use Delta Sync indexes
- ❌ Hardcoded prompts in code → ✅ Version control and log prompts
- ❌ No input validation → ✅ Implement guardrails for injection and PII
- ❌ Not citing sources in RAG → ✅ Always return source documents
- ❌ Using expensive models for simple tasks → ✅ Use Agent Bricks auto-optimization
- ❌ No LLM evaluation → ✅ Track relevance, faithfulness, and quality metrics
- ❌ Full fine-tuning instead of LoRA → ✅ Use PEFT for 99% of cases
- ❌ Starting with few-shot → ✅ Start zero-shot, add examples only if needed
- ❌ No max iterations on agents → ✅ Set max_iterations=10 and timeout
- ❌ Too many tools for agents → ✅ Provide only relevant tools (3-5 max)

## Integration Points

**Works with:**
- **databricks-data-engineering**: Provides data pipelines for training datasets
- **databricks-ml-engineering**: Handles model deployment and monitoring
- **databricks-platform**: Cluster configuration for GPU workloads

## References

- [Foundation Model API](https://docs.databricks.com/machine-learning/foundation-models/)
- [Vector Search](https://docs.databricks.com/generative-ai/vector-search.html)
- [Agent Bricks](https://docs.databricks.com/generative-ai/agent-bricks/)
- [RAG Guide](https://docs.databricks.com/generative-ai/retrieval-augmented-generation.html)
- [LLM Fine-Tuning](https://docs.databricks.com/machine-learning/model-training/fine-tune-llms.html)

# RAG Systems - Retrieval Augmented Generation

Production-ready RAG pipelines with Delta Live Tables, Vector Search, and LLM generation.

## Complete RAG Pipeline with DLT

```python
import dlt
from databricks.vector_search.client import VectorSearchClient
from langchain.text_splitter import RecursiveCharacterTextSplitter

# Step 1: Ingestion with Auto Loader
@dlt.table(comment="Raw documents")
def raw_documents():
    return (
        spark.readStream
        .format("cloudFiles")
        .option("cloudFiles.format", "pdf")
        .load("/Volumes/main/rag/raw_docs/")
    )

# Step 2: Chunking
@dlt.table(comment="Chunked documents")
@dlt.expect_or_drop("valid_text", "length(text_chunk) > 100")
def chunked_documents():
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=512,
        chunk_overlap=100,
        separators=["\n\n", "\n", ". ", " ", ""]
    )
    
    def chunk_text(text, doc_id):
        chunks = splitter.split_text(text)
        return [(f"{doc_id}_chunk_{i}", chunk, doc_id) 
                for i, chunk in enumerate(chunks)]
    
    chunk_udf = F.udf(chunk_text, "array<struct<chunk_id:string,text_chunk:string,doc_id:string>>")
    
    return (
        dlt.read_stream("raw_documents")
        .withColumn("chunks", chunk_udf("text", "id"))
        .selectExpr("explode(chunks) as chunk")
        .select("chunk.*", "source_file", "uploaded_at")
    )

# Step 3: Create Vector Search index
vsc = VectorSearchClient()

index = vsc.create_delta_sync_index(
    endpoint_name="rag_endpoint",
    index_name="main.rag.knowledge_base_index",
    source_table_name="main.rag.chunked_documents",
    pipeline_type="CONTINUOUS",
    primary_key="chunk_id",
    embedding_source_column="text_chunk",
    embedding_model_endpoint_name="databricks-bge-large-en"
)

# Step 4: RAG Query Service
from langchain_community.vectorstores import DatabricksVectorSearch
from langchain_community.chat_models import ChatDatabricks
from langchain.chains import RetrievalQA

def create_rag_chain():
    embeddings = DatabricksEmbeddings(endpoint="databricks-bge-large-en")
    
    vector_store = DatabricksVectorSearch(
        index=vsc.get_index("rag_endpoint", "main.rag.knowledge_base_index"),
        embedding=embeddings,
        text_column="text_chunk"
    )
    
    retriever = vector_store.as_retriever(search_kwargs={"k": 5, "score_threshold": 0.7})
    llm = ChatDatabricks(endpoint="databricks-llama-2-70b-chat", temperature=0.1)
    
    return RetrievalQA.from_chain_type(
        llm=llm,
        retriever=retriever,
        return_source_documents=True
    )
```

## Hybrid Search with Metadata Filtering

```python
def filtered_rag_query(question: str, doc_category: str = None, date_range: tuple = None):
    # Build metadata filters
    filters = {}
    if doc_category:
        filters["category"] = doc_category
    if date_range:
        filters["uploaded_at"] = {"$gte": date_range[0], "$lte": date_range[1]}
    
    # Retrieve with filters (10-100x faster)
    search_results = vsc.get_index(
        endpoint_name="rag_endpoint",
        index_name="main.rag.knowledge_base_index"
    ).similarity_search(
        query_text=question,
        columns=["chunk_id", "text_chunk", "source_file"],
        filters=filters,
        num_results=5
    )
    
    if not search_results['result']['data_array']:
        return {"answer": "No relevant information found.", "sources": []}
    
    # Assemble context
    context = "\n\n".join([
        f"[{doc['source_file']}]\n{doc['text_chunk']}"
        for doc in search_results['result']['data_array']
    ])
    
    # Generate answer
    response = w.serving_endpoints.query(
        name="databricks-llama-2-70b-chat",
        inputs=[{
            "prompt": f"""Answer based only on context. If not in context, say "I don't have enough information."

Context:
{context}

Question: {question}

Answer:""",
            "max_tokens": 500
        }]
    )
    
    return {
        "answer": response.predictions[0],
        "sources": [doc['source_file'] for doc in search_results['result']['data_array']],
        "filters_applied": filters
    }
```

## RAG Evaluation Framework

```python
import mlflow
import pandas as pd

def evaluate_rag_system(test_queries: list):
    results = []
    
    for query in test_queries:
        import time
        start = time.time()
        
        response = rag_chain({"query": query})
        latency = time.time() - start
        
        answer = response['result']
        sources = [doc.page_content for doc in response['source_documents']]
        
        # LLM-as-judge evaluation
        relevance_score = evaluate_relevance(query, answer)
        faithfulness_score = evaluate_faithfulness(answer, sources)
        
        results.append({
            "query": query,
            "answer": answer,
            "relevance": relevance_score,
            "faithfulness": faithfulness_score,
            "latency_ms": latency * 1000,
            "num_sources": len(sources)
        })
    
    # Log to MLflow
    with mlflow.start_run(run_name="rag_evaluation"):
        df = pd.DataFrame(results)
        
        mlflow.log_metrics({
            "avg_relevance": df['relevance'].mean(),
            "avg_faithfulness": df['faithfulness'].mean(),
            "avg_latency_ms": df['latency_ms'].mean(),
            "p95_latency_ms": df['latency_ms'].quantile(0.95)
        })
        
        mlflow.log_table(df, "evaluation_results.json")
    
    return df
```

## Response Caching for Cost Optimization

```python
import hashlib

class SemanticCache:
    def __init__(self, similarity_threshold=0.95):
        self.cache = {}
        self.embeddings_model = DatabricksEmbeddings(endpoint="databricks-bge-large-en")
    
    def get_embedding_hash(self, text: str) -> str:
        embedding = self.embeddings_model.embed_query(text)
        return hashlib.sha256(str(embedding).encode()).hexdigest()
    
    def get(self, query: str):
        query_hash = self.get_embedding_hash(query)
        return self.cache.get(query_hash)
    
    def set(self, query: str, response: dict):
        query_hash = self.get_embedding_hash(query)
        self.cache[query_hash] = response

cache = SemanticCache()

def cached_rag_query(question: str) -> dict:
    cached_response = cache.get(question)
    if cached_response:
        return cached_response
    
    response = rag_chain({"query": question})
    result = {
        "answer": response['result'],
        "sources": [doc.page_content for doc in response['source_documents']]
    }
    
    cache.set(question, result)
    return result
```

## Best Practices

### Security & Governance
- Scan documents for PII before indexing
- Unity Catalog permissions - indexes inherit table permissions
- Log queries with user, timestamp, response for compliance
- Sanitize user queries to prevent prompt injection
- Always return source documents for verification

### Performance & Cost
- Optimal chunk size: 256-512 tokens with 50-100 token overlap
- Embedding model: bge-large-en (1024-dim) for balanced quality/cost
- Retrieval k: Start with k=5, max k=20
- Always filter by category, date, or user (10-100x speedup)
- Semantic caching: 30-50% cost reduction

### Monitoring & Reliability
- Track p50, p95, p99 latency for retrieval + generation
- Daily evaluation on sample queries (relevance >0.7, faithfulness >0.8)
- Monitor Delta Sync lag (target <5 minutes)
- Retry logic with exponential backoff
- Return "No information available" if no results

## Common Issues & Solutions

### Issue: Irrelevant Results
```python
# Improve chunking with semantic boundaries
splitter = RecursiveCharacterTextSplitter(
    chunk_size=512,  # Experiment: 256, 512, 1024
    chunk_overlap=100,
    separators=["\n\n", "\n", ". ", " ", ""]
)

# Add metadata filters (10-100x precision boost)
results = index.similarity_search(
    query_text="question",
    filters={"category": "relevant"},
    num_results=10
)
```

### Issue: Answers Not Grounded in Sources
```python
# Strengthen prompt
prompt = """Answer ONLY using context below. If not in context, say "I don't have enough information."

DO NOT add information from your training.

Context:
{context}

Question: {question}

Answer ONLY from context:"""

# Lower temperature for factual responses
llm = ChatDatabricks(endpoint="...", temperature=0.0)
```

### Issue: High Query Latency (>2 seconds)
```python
# Optimize retrieval
results = index.similarity_search(
    query_text="question",
    filters={"year": 2024},  # Reduce search space
    num_results=5,  # Lower k
    columns=["chunk_id", "text_chunk"]  # Only needed columns
)

# Use PREMIUM endpoint for <100ms retrieval
vsc.update_endpoint(name="rag_endpoint", endpoint_type="PREMIUM")
```

## Key Anti-Patterns

- ❌ Large chunks (>1024 tokens) → ✅ Use 256-512 token chunks
- ❌ No metadata filters → ✅ Always filter by category, date, permissions
- ❌ Single retrieval strategy → ✅ Combine vector + metadata filters
- ❌ No monitoring → ✅ Continuous evaluation with LLM-as-judge
- ❌ Embedding entire documents → ✅ Chunk documents, store metadata

# Vector Search & Embeddings

Delta Sync indexes, embedding model selection, and production vector database operations.

## Delta Sync Index (Managed Embeddings)

Recommended pattern: Automatic embedding generation with Delta Sync.

```python
from databricks.vector_search.client import VectorSearchClient

vsc = VectorSearchClient()

# Create endpoint (one per workspace/region)
vsc.create_endpoint(
    name="vector_search_endpoint",
    endpoint_type="STANDARD"  # PREMIUM for <100ms latency
)

# Create Delta Sync index with managed embeddings
index = vsc.create_delta_sync_index(
    endpoint_name="vector_search_endpoint",
    index_name="main.default.product_docs_index",
    source_table_name="main.default.product_docs",
    pipeline_type="TRIGGERED",  # or CONTINUOUS for real-time
    primary_key="doc_id",
    embedding_source_column="text",  # Text to embed
    embedding_model_endpoint_name="databricks-bge-large-en"  # 1024-dim
)

# Wait for index to be ready
index.wait_until_ready()

# Query the index
results = index.similarity_search(
    query_text="machine learning best practices",
    columns=["doc_id", "text", "category"],
    num_results=10
)
```

## Direct Access Index (Custom Embeddings)

For pre-computed or custom embeddings.

```python
# Create direct access index
index = vsc.create_direct_access_index(
    endpoint_name="vector_search_endpoint",
    index_name="main.default.custom_embeddings_index",
    primary_key="id",
    embedding_dimension=1536,  # Must match your model
    embedding_vector_column="embedding",
    schema={
        "id": "string",
        "embedding": "array<float>",
        "text": "string",
        "category": "string"
    }
)

# Upsert vectors (batch or streaming)
index.upsert([
    {
        "id": "doc_001",
        "embedding": [0.1, 0.2, ...],  # 1536 dimensions
        "text": "Document content",
        "category": "technical"
    }
])

# Query with pre-computed query vector
query_vector = custom_model.encode("user query")
results = index.similarity_search(
    query_vector=query_vector.tolist(),
    columns=["id", "text", "category"],
    num_results=10
)
```

## Hybrid Search with Metadata Filters

Combine vector similarity with structured filters (10-100x faster).

```python
# Query with filters to narrow search space
results = index.similarity_search(
    query_text="databricks best practices",
    columns=["id", "text", "author", "timestamp"],
    filters={
        "category": "documentation",
        "year": 2024,
        "author": ["john.doe", "jane.smith"]
    },
    num_results=20
)

# Filters use standard SQL operators: =, !=, IN, NOT IN, >, <, >=, <=
# Complex filters: {"AND": [{"category": "docs"}, {"year": 2024}]}
```

## Embedding Model Selection

### Available Models

| Model | Dimensions | Use Case | Quality | Cost |
|-------|-----------|----------|---------|------|
| databricks-bge-small-en | 384 | Fast, low-cost | Good | $ |
| databricks-bge-large-en | 1024 | Balanced | Best | $$ |
| databricks-gte-large-en | 1024 | Multilingual | Best | $$ |

### Selection Criteria

```python
# For general English text (recommended)
embedding_model_endpoint_name="databricks-bge-large-en"

# For multilingual content
embedding_model_endpoint_name="databricks-gte-large-en"

# For cost-sensitive applications
embedding_model_endpoint_name="databricks-bge-small-en"
```

## Delta Sync Optimization

```sql
-- Enable Change Data Feed for CONTINUOUS sync
ALTER TABLE main.default.documents 
SET TBLPROPERTIES ('delta.enableChangeDataFeed' = 'true');

-- Optimize source table before creating index
OPTIMIZE main.default.documents
ZORDER BY (primary_key);

-- Enable auto-compaction
ALTER TABLE main.default.documents 
SET TBLPROPERTIES (
    'delta.autoOptimize.optimizeWrite' = 'true',
    'delta.autoOptimize.autoCompact' = 'true'
);

-- For large tables (10M+ rows): Use liquid clustering
ALTER TABLE main.default.documents 
CLUSTER BY (category, timestamp);
```

## Monitoring & Reliability

```python
# Check index status and freshness
index_info = vsc.get_index(
    endpoint_name="vector_search_endpoint",
    index_name="main.default.docs_index"
).describe()

print(f"Status: {index_info['status']['state']}")  # Must be ONLINE
print(f"Documents: {index_info['index_stats']['num_documents']}")
print(f"Last updated: {index_info['status']['last_updated_timestamp']}")

# Measure query latency
import time
start = time.time()
results = index.similarity_search(query_text="test", num_results=10)
latency_ms = (time.time() - start) * 1000
print(f"Query latency: {latency_ms:.2f}ms")
```

## Best Practices

### Security & Governance
- Unity Catalog: Indexes inherit table permissions automatically
- Row-level security: Apply filters based on user context
- PII protection: Sanitize text before embedding
- Audit logging: Track queries for compliance
- Service principals: Use for production (not personal tokens)

### Performance & Cost
- **STANDARD** endpoint for dev/batch (auto-scale)
- **PREMIUM** endpoint for <100ms production queries
- Always apply metadata filters (10-100x speedup)
- Only return needed columns
- Batch queries with ThreadPoolExecutor
- Optimize source table with liquid clustering

## Common Issues & Solutions

### Issue: Index Stuck in PROVISIONING
```python
# Check endpoint is ONLINE
endpoint = vsc.get_endpoint("vector_search_endpoint")
assert endpoint['endpoint_status']['state'] == 'ONLINE'

# Enable CDF for CONTINUOUS sync
spark.sql("""
    ALTER TABLE main.default.documents 
    SET TBLPROPERTIES ('delta.enableChangeDataFeed' = 'true')
""")

# Recreate index if stuck >1 hour
vsc.delete_index(endpoint_name="...", index_name="...")
```

### Issue: High Query Latency (>500ms)
```python
# Add filters (10-100x speedup)
results = index.similarity_search(
    query_text="query",
    filters={"category": "relevant_subset"},
    num_results=10
)

# Upgrade to PREMIUM endpoint
vsc.update_endpoint(name="vector_search_endpoint", endpoint_type="PREMIUM")

# Reduce num_results if >50
```

### Issue: Embedding Dimension Mismatch
```python
# Check actual embedding dimensions
spark.sql("""
    SELECT array_size(embedding) as dim, COUNT(*) as cnt
    FROM main.default.embeddings
    GROUP BY dim
""").show()

# Recreate index with correct dimension
# bge-small-en: 384, bge-large-en: 1024, gte-large-en: 1024
```

## Key Anti-Patterns

- ❌ Creating embeddings in query path → ✅ Use managed embeddings or pre-compute
- ❌ No metadata filters on large indexes → ✅ Always filter to reduce search space
- ❌ Storing full documents in index → ✅ Store minimal metadata, join with source table
- ❌ CONTINUOUS sync without CDF → ✅ Enable CDF before creating CONTINUOUS pipeline
- ❌ PREMIUM endpoints for batch → ✅ Use STANDARD for dev/batch, PREMIUM for prod

# Agent Bricks - Automated AI Agent Building

Agent Bricks provides one-click deployment of optimized AI agents with automatic model selection and cost optimization.

## Four Agent Types

### 1. Information Extraction
Transform unstructured documents into structured tables.

```python
from databricks.sdk import WorkspaceClient

w = WorkspaceClient()

# Navigate to: Workspace > Agent Bricks > Information Extraction
# Define extraction schema via UI with instructions + examples

# Query deployed endpoint
response = w.serving_endpoints.query(
    name="invoice_extractor_endpoint",
    messages=[ChatMessage(
        role=ChatMessageRole.USER,
        content="Extract data from: [Invoice content]"
    )]
)

extracted_data = response.choices[0].message.content
```

**Configuration:**
```python
extraction_config = {
    "name": "invoice_extractor",
    "description": "Extract vendor, amount, date, line items from invoices",
    "source_documents": "main.raw.invoices",
    "output_table": "main.gold.structured_invoices",
    "instructions": """
        Extract:
        - vendor_name: Company providing service
        - invoice_date: Date in YYYY-MM-DD format
        - total_amount: Total amount due
        - line_items: Array of {description, quantity, unit_price, total}
    """,
    "examples": [
        {
            "document": "Invoice from Acme Corp dated 2024-01-15...",
            "extraction": {
                "vendor_name": "Acme Corp",
                "invoice_date": "2024-01-15",
                "total_amount": 1250.00
            }
        }
    ]
}
```

Agent Bricks automatically:
1. Tests multiple models (GPT-4, Claude, Llama)
2. Fine-tunes on your examples
3. Optimizes cost vs. quality
4. Creates serving endpoint

**Batch Processing:**
```sql
CREATE OR REPLACE TABLE main.gold.structured_invoices AS
SELECT 
    ai_query(
        'invoice_extractor_endpoint',
        content
    ) as extracted_data,
    *
FROM main.raw.invoices
WHERE processed_date IS NULL;
```

### 2. Custom LLM
Domain-specific text generation, classification, transformation.

```python
# Created via Agent Bricks UI for tasks like:
# - Product description generation
# - Classification (sentiment, category, priority)
# - Data transformation and normalization

response = requests.post(
    f"{workspace_url}/serving-endpoints/product-description-generator/invocations",
    headers=headers,
    json={
        "inputs": {
            "product_name": "Enterprise Data Lakehouse",
            "features": ["Unity Catalog", "Delta Lake", "Serverless SQL"],
            "target_audience": "CTOs"
        }
    }
)

generated_text = response.json()['generated_text']
```

### 3. Knowledge Assistant
High-quality chatbots over enterprise documents with citations.

```python
# Query Knowledge Assistant for Q&A
response = requests.post(
    f"{workspace_url}/serving-endpoints/product-docs-assistant/invocations",
    headers=headers,
    json={
        "messages": [
            {"role": "user", "content": "How do I configure row-level security in Unity Catalog?"}
        ]
    }
)

answer = response.json()['choices'][0]['message']['content']
# Answer includes citations from knowledge base
```

**Setup:**
1. Navigate to Agent Bricks > Knowledge Assistant
2. Select source documents (Delta tables, Volumes)
3. Configure retrieval parameters (top-k, similarity threshold)
4. Deploy to serving endpoint

### 4. Multi-Agent Supervisor
Orchestrates multiple sub-agents for complex workflows.

```python
# Supervisor routes to specialized agents
response = requests.post(
    f"{workspace_url}/serving-endpoints/contract-processor-supervisor/invocations",
    headers=headers,
    json={
        "inputs": {
            "document": contract_text,
            "tasks": [
                "extract_key_terms",
                "analyze_risks",
                "generate_summary"
            ]
        }
    }
)

# Supervisor routes to: extraction → risk analysis → summarization agents
result = response.json()
```

## Production Capabilities

### Auto-Optimization
- Tests multiple AI models automatically
- Balances quality vs. cost
- Background hyperparameter sweeps
- Continuous improvement

### Serverless Compute
- Auto-scaling based on load
- Scales to zero after inactivity
- Large context support (up to 128k tokens)
- Enterprise-scale throughput

### Unity Catalog Integration
- Seamless governance and security
- Automatic permissions inheritance
- Data lineage tracking
- Compliance-ready deployment

## Best Practices

### Data Preparation
- High-quality examples (10-50 for extraction)
- Diverse edge cases
- Clean, consistent formatting
- Representative of production data

### Monitoring
```python
# Monitor Agent Bricks endpoint
spark.sql("""
    SELECT 
        DATE(timestamp) as date,
        COUNT(*) as requests,
        AVG(latency_ms) as avg_latency,
        SUM(CASE WHEN error THEN 1 ELSE 0 END) as errors
    FROM system.serving.serving_endpoint_payload
    WHERE endpoint_name = 'invoice_extractor_endpoint'
    GROUP BY DATE(timestamp)
    ORDER BY date DESC
""")
```

### Cost Optimization
- Agent Bricks automatically optimizes model selection
- Use batch processing for high-volume extraction
- Set appropriate rate limits
- Monitor token usage in inference tables

## Common Use Cases

**Information Extraction:**
- Invoice processing
- Contract analysis
- Resume parsing
- Document classification

**Custom LLM:**
- Product description generation
- Email response drafting
- Content moderation
- Translation and localization

**Knowledge Assistant:**
- Internal documentation Q&A
- Customer support chatbots
- Technical troubleshooting
- Policy and compliance queries

**Multi-Agent Supervisor:**
- Complex document workflows
- Multi-step approval processes
- Coordinated data processing
- Intelligent routing and escalation

# Agent Frameworks - LangChain & LlamaIndex

Production agent development with tool calling, memory, and orchestration.

## LangChain ReAct Agent with Tool Calling

```python
from langchain.agents import AgentExecutor, create_react_agent
from langchain_community.chat_models import ChatDatabricks
from langchain.tools import Tool

# Initialize LLM
llm = ChatDatabricks(
    endpoint="databricks-llama-2-70b-chat",
    temperature=0,
    max_tokens=1000
)

# Define tools
def execute_sql_tool(query: str) -> str:
    try:
        result = spark.sql(query).limit(100).toPandas()
        return result.to_markdown()
    except Exception as e:
        return f"SQL Error: {str(e)}"

def vector_search_tool(question: str) -> str:
    vsc = VectorSearchClient()
    index = vsc.get_index("main.rag.knowledge_base_index")
    results = index.similarity_search(query_text=question, num_results=3)
    docs = results['result']['data_array']
    return "\n\n".join([f"[{d['source_file']}]\n{d['text_chunk']}" for d in docs])

# Create LangChain tools
tools = [
    Tool(
        name="ExecuteSQL",
        func=execute_sql_tool,
        description="Execute SQL query on Unity Catalog. Input: SQL query string. Returns: Query results as table."
    ),
    Tool(
        name="SearchDocumentation",
        func=vector_search_tool,
        description="Search internal documentation using vector search. Input: Question string. Returns: Relevant documents."
    )
]

# ReAct prompt template
react_prompt = PromptTemplate.from_template("""
You are a helpful data analyst with access to tools.

Use this format:
Question: the input question
Thought: think about what to do
Action: tool name
Action Input: tool input
Observation: tool result
... (repeat as needed)
Thought: I now know the final answer
Final Answer: the final answer

Question: {input}
Thought: {agent_scratchpad}
""")

# Create agent
agent = create_react_agent(llm, tools, react_prompt)
agent_executor = AgentExecutor(
    agent=agent,
    tools=tools,
    verbose=True,
    max_iterations=10,
    handle_parsing_errors=True
)

# Execute with MLflow tracing
mlflow.langchain.autolog()
result = agent_executor.invoke({"input": "What is the total revenue from sales table in last 30 days?"})
```

## LlamaIndex Multi-Document Agent

```python
from llama_index.core import VectorStoreIndex, SimpleDirectoryReader
from llama_index.llms.databricks import Databricks
from llama_index.core.tools import QueryEngineTool
from llama_index.core.agent import ReActAgent

# Initialize LLM
llm = Databricks(endpoint="databricks-llama-2-70b-chat")

# Load documents from Unity Catalog volumes
policy_docs = SimpleDirectoryReader("/Volumes/main/docs/policies").load_data()
financial_docs = SimpleDirectoryReader("/Volumes/main/docs/financial").load_data()

# Create indexes
policy_index = VectorStoreIndex.from_documents(policy_docs)
financial_index = VectorStoreIndex.from_documents(financial_docs)

# Create tools
query_tools = [
    QueryEngineTool(
        query_engine=policy_index.as_query_engine(similarity_top_k=3),
        metadata=ToolMetadata(
            name="policy_search",
            description="Search company policies, HR guidelines, and compliance documents"
        )
    ),
    QueryEngineTool(
        query_engine=financial_index.as_query_engine(similarity_top_k=3),
        metadata=ToolMetadata(
            name="financial_search",
            description="Search financial reports, budgets, and revenue data"
        )
    )
]

# Create ReAct agent
agent = ReActAgent.from_tools(query_tools, llm=llm, verbose=True, max_iterations=10)

# Execute query
response = agent.chat("What is the company's policy on remote work reimbursements?")
```

## Agent with Conversation Memory

```python
from langchain.memory import ConversationBufferMemory, ConversationSummaryMemory

# Buffer memory (stores last N messages)
memory = ConversationBufferMemory(
    memory_key="chat_history",
    return_messages=True,
    max_token_limit=2000  # Prevent context overflow
)

# Summary memory (summarizes old messages)
summary_memory = ConversationSummaryMemory(
    llm=llm,
    memory_key="chat_history",
    return_messages=True,
    max_token_limit=4000
)

# Agent with memory
agent_executor = AgentExecutor(
    agent=agent,
    tools=tools,
    memory=memory,  # Or summary_memory
    verbose=True
)

# Multi-turn conversation
agent_executor.invoke({"input": "What is our total revenue this quarter?"})
# Agent remembers context for follow-up
agent_executor.invoke({"input": "How does that compare to last quarter?"})

# Save conversation to Delta Lake
conversation_df = spark.createDataFrame([{
    "conversation_id": "conv_123",
    "timestamp": datetime.now(),
    "messages": memory.chat_memory.messages,
    "user_id": current_user()
}])
conversation_df.write.format("delta").mode("append").saveAsTable("main.audit.agent_conversations")
```

## Production Custom Tool with Validation

```python
from langchain.tools import BaseTool
from pydantic import BaseModel, Field, validator
import mlflow

class SQLQueryInput(BaseModel):
    query: str = Field(description="SQL query to execute")
    
    @validator('query')
    def validate_query(cls, v):
        forbidden_keywords = ['DROP', 'DELETE', 'TRUNCATE', 'ALTER', 'CREATE']
        if any(keyword in v.upper() for keyword in forbidden_keywords):
            raise ValueError("Query contains forbidden keyword. Only SELECT allowed.")
        return v

class SafeSQLTool(BaseTool):
    name = "safe_sql_query"
    description = "Execute read-only SQL queries on Unity Catalog (SELECT only)"
    args_schema: Type[BaseModel] = SQLQueryInput
    
    def _run(self, query: str) -> str:
        try:
            mlflow.log_param("sql_query", query)
            result = spark.sql(query).limit(100).toPandas()
            mlflow.log_metric("result_rows", len(result))
            return result.to_markdown()
        except Exception as e:
            error_msg = f"SQL Error: {str(e)}"
            mlflow.log_param("error", error_msg)
            return error_msg

safe_sql_tool = SafeSQLTool()
tools = [safe_sql_tool, ...]
```

## Best Practices

### Security & Governance
- Whitelist allowed tools per user/role
- Sanitize all tool inputs to prevent injection
- Only allow SELECT for SQL tools
- Log all tool calls with user, timestamp, input, output
- Tools inherit Unity Catalog permissions

### Memory Management
- **Buffer Memory**: Last N messages (fast, but grows)
- **Summary Memory**: Summarize old messages (saves tokens)
- **Vector Memory**: Store semantic memory in vector DB (searchable)
- **Pruning**: Remove irrelevant old messages
- **Persistent Storage**: Save to Delta Lake for audit/training

### Cost Optimization
- Cache identical tool calls (SQL, API responses)
- Summarize long tool outputs before next LLM call
- Provide only relevant tools (3-5 max)
- Use async execution for parallel tool calls
- Truncate results (SQL LIMIT 100)

## Common Issues & Solutions

### Issue: Agent Loops Indefinitely
```python
# Set max iterations and timeout
agent_executor = AgentExecutor(
    agent=agent,
    tools=tools,
    max_iterations=10,  # Prevent infinite loops
    max_execution_time=60,  # Timeout after 60s
    early_stopping_method="generate"  # Force answer after max iterations
)
```

### Issue: Agent Hallucinates Tool Outputs
```python
# Use strict parsing
agent_executor = AgentExecutor(
    agent=agent,
    tools=tools,
    handle_parsing_errors=True,  # Retry on parse errors
    return_intermediate_steps=True  # Verify tool was actually called
)

# Strengthen prompt
prompt = """...
CRITICAL: You must ONLY use actual tool results. NEVER make up tool outputs.
..."""
```

### Issue: Agent Chooses Wrong Tool
```python
# Improve tool descriptions
Tool(
    name="ExecuteSQL",
    func=execute_sql_tool,
    description="""Execute SQL query on Unity Catalog to retrieve structured data from tables.

Use this tool when:
- User asks about data in tables (revenue, customers, orders)
- Need to aggregate, filter, or join data

Do NOT use for:
- Document search (use SearchDocumentation instead)
- General knowledge questions (answer directly)

Input: Valid SQL SELECT query
Output: Table with query results (max 100 rows)"""
)
```

## Key Anti-Patterns

- ❌ No max iterations → ✅ Set max_iterations=10 and timeout
- ❌ Too many tools → ✅ Provide only relevant tools (3-5 max)
- ❌ No input validation → ✅ Validate all tool inputs with Pydantic
- ❌ Ignoring conversation history → ✅ Use ConversationBufferMemory
- ❌ No error handling → ✅ Wrap tool calls in try/except

# LLM Fine-Tuning - PEFT, LoRA, QLoRA

Memory-efficient model adaptation with parameter-efficient fine-tuning techniques.

## LoRA Fine-Tuning for 7B Models

Memory-efficient fine-tuning with LoRA (Low-Rank Adaptation).  
Best for: 7B-13B models on A10/A100, <1% of parameters trainable.

```python
from transformers import AutoModelForCausalLM, AutoTokenizer, TrainingArguments, Trainer
from peft import LoraConfig, get_peft_model, prepare_model_for_kbit_training
import mlflow
import torch

# Load model with 8-bit quantization (50% memory reduction)
model = AutoModelForCausalLM.from_pretrained(
    "meta-llama/Llama-2-7b-hf",
    load_in_8bit=True,
    device_map="auto",
    torch_dtype=torch.float16,
    token=hf_token
)

# Prepare for k-bit training
model = prepare_model_for_kbit_training(model)

# Configure LoRA
lora_config = LoraConfig(
    r=16,  # Rank: 8 (faster), 16 (balanced), 32 (better quality)
    lora_alpha=32,  # Scaling factor (typically 2x rank)
    target_modules=["q_proj", "v_proj", "k_proj", "o_proj"],  # Attention layers
    lora_dropout=0.05,
    bias="none",
    task_type="CAUSAL_LM"
)

# Apply LoRA
model = get_peft_model(model, lora_config)
model.print_trainable_parameters()
# Output: ~4M trainable (0.06% of 7B parameters)

# Prepare training data from Delta Lake
training_df = spark.table("main.ml_data.instruction_dataset").toPandas()

# Format for instruction tuning (Alpaca format)
def format_instruction(example):
    instruction = example['instruction']
    input_text = example.get('input', '')
    response = example['output']
    
    if input_text:
        prompt = f"""### Instruction:
{instruction}

### Input:
{input_text}

### Response:
{response}"""
    else:
        prompt = f"""### Instruction:
{instruction}

### Response:
{response}"""
    
    return {"text": prompt}

# Create dataset and tokenize
hf_dataset = Dataset.from_pandas(training_df)
formatted_dataset = hf_dataset.map(format_instruction)
split_dataset = formatted_dataset.train_test_split(test_size=0.1, seed=42)

# Training arguments
training_args = TrainingArguments(
    output_dir="/dbfs/mnt/models/llama2-lora",
    num_train_epochs=3,
    per_device_train_batch_size=4,  # Adjust based on GPU memory
    gradient_accumulation_steps=4,  # Effective batch size: 16
    learning_rate=2e-4,
    fp16=True,
    save_strategy="epoch",
    evaluation_strategy="epoch",
    logging_steps=10,
    report_to="mlflow",
    warmup_steps=100,
    load_best_model_at_end=True
)

# Train with MLflow tracking
mlflow.transformers.autolog()

with mlflow.start_run(run_name="llama2_lora_finetuning"):
    mlflow.log_params({
        "base_model": "meta-llama/Llama-2-7b-hf",
        "dataset_size": len(training_df),
        "lora_r": lora_config.r,
        "lora_alpha": lora_config.lora_alpha
    })
    
    trainer = Trainer(
        model=model,
        args=training_args,
        train_dataset=tokenized_train,
        eval_dataset=tokenized_eval
    )
    
    trainer.train()
    trainer.save_model("/dbfs/mnt/models/llama2-lora-final")
    
    # Log to Unity Catalog
    mlflow.transformers.log_model(
        transformers_model={"model": model, "tokenizer": tokenizer},
        artifact_path="model",
        registered_model_name="main.ml_models.llama2_company_assistant"
    )
```

## QLoRA for 70B Models (4-bit Quantization)

Ultra-efficient fine-tuning with QLoRA.  
Best for: 70B models on A100 80GB, 75% memory reduction vs 8-bit.

```python
from transformers import BitsAndBytesConfig

# 4-bit quantization config
bnb_config = BitsAndBytesConfig(
    load_in_4bit=True,
    bnb_4bit_quant_type="nf4",  # Normal Float 4-bit
    bnb_4bit_compute_dtype=torch.float16,
    bnb_4bit_use_double_quant=True  # Nested quantization
)

# Load 70B model on single A100 80GB
model = AutoModelForCausalLM.from_pretrained(
    "meta-llama/Llama-2-70b-hf",
    quantization_config=bnb_config,
    device_map="auto",
    token=hf_token
)

# Lower rank for larger model (memory constraint)
lora_config = LoraConfig(
    r=8,
    lora_alpha=16,
    target_modules=["q_proj", "v_proj"],
    lora_dropout=0.05,
    bias="none",
    task_type="CAUSAL_LM"
)

model = prepare_model_for_kbit_training(model)
model = get_peft_model(model, lora_config)

# Reduced batch size for larger model
training_args = TrainingArguments(
    per_device_train_batch_size=1,  # Minimal batch size
    gradient_accumulation_steps=16,  # Effective batch: 16
    gradient_checkpointing=True,  # Trade compute for memory
    **other_args
)
```

## Deploy Fine-Tuned Model

```python
from databricks.sdk import WorkspaceClient

w = WorkspaceClient()

# Create serving endpoint
w.serving_endpoints.create(
    name="llama2-company-assistant",
    config=EndpointCoreConfigInput(
        served_entities=[
            ServedEntityInput(
                entity_name="main.ml_models.llama2_company_assistant",
                entity_version="1",
                workload_size="Medium",
                scale_to_zero_enabled=False,
                environment_vars={
                    "HF_TOKEN": "{{secrets/llm-keys/hf-token}}"
                }
            )
        ]
    )
)

# Query endpoint
response = w.serving_endpoints.query(
    name="llama2-company-assistant",
    inputs=[{
        "prompt": "### Instruction:\nExplain Unity Catalog\n\n### Response:\n",
        "max_tokens": 200
    }]
)
```

## A/B Testing

```python
def evaluate_model(model_endpoint: str, test_queries: list) -> dict:
    results = []
    
    for query in test_queries:
        response = w.serving_endpoints.query(
            name=model_endpoint,
            inputs=[{"prompt": query, "max_tokens": 200}]
        )
        results.append({"query": query, "response": response.predictions[0]})
    
    # LLM-as-judge evaluation
    quality_scores = [evaluate_quality(r['query'], r['response']) for r in results]
    
    return {"avg_quality": sum(quality_scores) / len(quality_scores), "results": results}

# Compare models
base_model_eval = evaluate_model("databricks-llama-2-70b-chat", test_queries)
finetuned_eval = evaluate_model("llama2-company-assistant", test_queries)

print(f"Base model: {base_model_eval['avg_quality']:.2f}")
print(f"Fine-tuned: {finetuned_eval['avg_quality']:.2f}")
```

## Best Practices

### Memory Optimization
- **8-bit loading**: 50% memory reduction, minimal quality loss (7B-13B)
- **4-bit loading (QLoRA)**: 75% memory reduction (70B on A100)
- **Gradient checkpointing**: 30% less memory, 20% slower training
- **Batch size tuning**: Start with 1, increase until OOM
- **Gradient accumulation**: Simulate larger batches (multiply by 4-16)

### Training Efficiency
- **Mixed precision (fp16/bf16)**: 2x faster, 50% less memory
- **LoRA rank**: r=8 (fast), r=16 (balanced), r=32 (quality)
- **Learning rate**: 2e-4 for LoRA (10x higher than full fine-tuning)
- **Warmup steps**: 5-10% of total steps
- **Evaluation strategy**: Every epoch to catch overfitting

### Cost Management
- **GPU selection**: A10 ($2.50/hr) for 7B, A100 ($4-6/hr) for 13B-70B
- **Training duration**: 7B on 10K examples ≈ 2-4 hours on A10
- **Spot instances**: 60-80% savings, use checkpointing
- **Dataset size**: 1K-10K examples typical, diminishing returns after 50K
- **Model size vs quality**: 7B fine-tuned often beats 70B foundation on domain tasks

## Common Issues & Solutions

### Issue: Out of Memory (OOM)
```python
# Reduce batch size and use gradient accumulation
training_args = TrainingArguments(
    per_device_train_batch_size=1,
    gradient_accumulation_steps=16,
    gradient_checkpointing=True,
    fp16=True
)

# Use 8-bit or 4-bit quantization
model = AutoModelForCausalLM.from_pretrained(
    model_name,
    load_in_8bit=True,  # Or load_in_4bit=True
    device_map="auto"
)
```

### Issue: Model Overfitting
```python
# Add regularization
lora_config = LoraConfig(
    lora_dropout=0.1,  # Increase from 0.05
    ...
)

# Reduce epochs
training_args = TrainingArguments(
    num_train_epochs=2,  # Instead of 3-5
    early_stopping_patience=2,
    load_best_model_at_end=True
)
```

### Issue: Catastrophic Forgetting
```python
# Use lower LoRA rank
lora_config = LoraConfig(
    r=8,  # Lower rank = less aggressive fine-tuning
    ...
)

# Lower learning rate
training_args = TrainingArguments(
    learning_rate=1e-4,  # Half the typical LoRA LR
    ...
)

# Mix custom data with general instruction data (80/20)
```

## Key Anti-Patterns

- ❌ Full fine-tuning → ✅ Use LoRA for 99% of cases
- ❌ No validation set → ✅ Always use 90/10 train/val split
- ❌ Ignoring data quality → ✅ Clean, diverse examples matter more than quantity
- ❌ Not logging to MLflow → ✅ Always track hyperparameters, metrics, models
- ❌ Deploying without evaluation → ✅ A/B test before full rollout

# Prompt Engineering - Optimization & Techniques

LLM prompt optimization, few-shot learning, chain-of-thought, and production patterns.

## Zero-Shot to Few-Shot Progression

Start simple (zero-shot), add examples only if needed.

```python
# Zero-shot (start here)
zero_shot_prompt = """Extract the customer name, order ID, and total amount from this email.

Email: {email_text}

Output format: JSON with keys: customer_name, order_id, total_amount
"""

# If quality insufficient → Few-shot (2-3 examples)
few_shot_prompt = """Extract customer name, order ID, and total amount from emails.

Example 1:
Email: "Hi, I'm John Smith. Order #12345 for $250 shipped yesterday."
Output: {{"customer_name": "John Smith", "order_id": "12345", "total_amount": 250.00}}

Example 2:
Email: "Sarah Johnson here, my order 67890 ($180.50) hasn't arrived."
Output: {{"customer_name": "Sarah Johnson", "order_id": "67890", "total_amount": 180.50}}

Email: {email_text}

Output:"""

# Few-shot typically improves accuracy by 20-40% at minimal cost increase
```

## Chain-of-Thought for Complex Reasoning

Break down complex problems into steps.

```python
# Without CoT (direct answer - often wrong)
direct_prompt = """A store has 150 apples. They sell 40% in morning, 30 more in afternoon. 
How many remain?

Answer:"""

# With Chain-of-Thought (step-by-step - more accurate)
cot_prompt = """A store has 150 apples. They sell 40% in morning, 30 more in afternoon.
How many remain?

Let's solve this step-by-step:
1. Calculate morning sales: 
2. Calculate remaining after morning:
3. Calculate afternoon sales:
4. Calculate final remaining:

Final Answer:"""

# Self-Consistency CoT (run 3-5 times, majority vote)
def self_consistent_cot(question: str, n_samples: int = 5):
    answers = []
    for _ in range(n_samples):
        response = llm.query(cot_prompt.format(question=question), temperature=0.7)
        answer = extract_final_answer(response)
        answers.append(answer)
    
    # Majority voting
    from collections import Counter
    return Counter(answers).most_common(1)[0][0]

# Improves accuracy by 15-30% on complex reasoning
```

## JSON Schema Enforcement

Structured outputs with validation.

```python
from pydantic import BaseModel, Field
from typing import List

class ProductExtraction(BaseModel):
    product_name: str = Field(description="Full product name")
    price: float = Field(description="Price in USD", ge=0)
    category: str = Field(description="Product category")
    features: List[str] = Field(description="List of key features")

# Prompt with schema
schema_prompt = f"""Extract structured product information from the description.

Output MUST be valid JSON matching this schema:
{ProductExtraction.schema_json(indent=2)}

Description: {{product_description}}

JSON Output:"""

# Query and validate
response = llm.query(schema_prompt.format(product_description=text))

try:
    product = ProductExtraction.parse_raw(response)
    print(f"Valid: {product}")
except ValidationError as e:
    # Retry with error feedback
    print(f"Invalid output: {e}")
```

## Token Optimization Techniques

Reduce token usage by 30-50% without quality loss.

```python
# Verbose prompt (100 tokens)
verbose_prompt = """You are a helpful customer service assistant. 
Your task is to analyze customer feedback and determine the sentiment.
Please carefully read the feedback below and provide a sentiment classification.
The sentiment should be one of the following: positive, negative, or neutral.
Be thorough in your analysis and consider the overall tone of the message.

Customer Feedback: {feedback}

Please provide your sentiment analysis below:
Sentiment:"""

# Optimized prompt (45 tokens, 55% reduction)
optimized_prompt = """Classify sentiment as positive, negative, or neutral.

Feedback: {feedback}

Sentiment:"""

# Both achieve ~same accuracy, optimized saves $0.0015 per call at scale

# Additional optimizations
def compress_context(context: str, max_tokens: int = 500) -> str:
    if count_tokens(context) <= max_tokens:
        return context
    
    summary_prompt = f"Summarize in {max_tokens} tokens:\n\n{context}"
    return llm.query(summary_prompt, max_tokens=max_tokens)

# Use bullet points instead of paragraphs (20% fewer tokens)
# Remove filler words: "please", "kindly", "thoroughly"
# Use abbreviations for repeated terms
```

## Dynamic Prompt Selection

Adapt prompt based on input characteristics.

```python
def select_prompt(user_query: str, user_profile: dict) -> str:
    # Classify query type
    if is_technical_question(user_query):
        template = technical_prompt_template
    elif is_sales_inquiry(user_query):
        template = sales_prompt_template
    else:
        template = general_prompt_template
    
    # Adapt for user expertise level
    if user_profile.get("expertise") == "beginner":
        template = add_explanations(template)
    elif user_profile.get("expertise") == "expert":
        template = remove_explanations(template)
    
    return template.format(
        user_name=user_profile["name"],
        user_industry=user_profile["industry"],
        query=user_query
    )

# Example templates
technical_prompt_template = """Technical Query from {user_name} ({user_industry}):

{query}

Provide technical answer with:
1. Code examples
2. Architecture diagrams
3. Best practices
"""

sales_prompt_template = """Sales Inquiry from {user_name} ({user_industry}):

{query}

Respond with:
1. Product fit analysis
2. Pricing options
3. Next steps
"""
```

## Best Practices

### Prompt Management
- **Version control**: Store prompts in Git with semantic versioning
- **Parameterization**: Use {placeholders} for dynamic values
- **Template library**: Centralized prompt repository
- **Prompt registry**: Unity Catalog for lineage and governance
- **Change management**: A/B test updates before rollout

### Cost Optimization
- **Start zero-shot**: Only add examples if quality insufficient
- **Token budgets**: Set max_tokens to prevent runaway costs
- **Batch processing**: Combine queries when appropriate
- **Caching**: Cache identical prompts + responses
- **Model selection**: Use smallest model that meets quality bar

### Quality Assurance
- **Regression tests**: 20-50 test cases covering scenarios
- **Format validation**: Parse and validate structured outputs
- **Fallback prompts**: Backup if primary fails
- **Human review**: Sample 1-10% of outputs
- **Continuous monitoring**: Track success rate, parse errors

## Common Issues & Solutions

### Issue: Inconsistent Output Format
```python
# Strengthen format enforcement
prompt = """Extract info as JSON. CRITICAL: Output ONLY valid JSON, no other text.

Schema:
{{"name": "string", "age": number, "email": "string"}}

Input: {text}

JSON (no markdown, no explanation):"""

# Add validation loop
for attempt in range(3):
    response = llm.query(prompt)
    try:
        data = json.loads(response)
        break  # Success
    except json.JSONDecodeError:
        prompt += f"\n\nPrevious output was invalid JSON: {response}\nTry again with ONLY valid JSON:"
```

### Issue: Model Ignores Instructions
```python
# Put critical instructions at START and END
prompt = """CRITICAL: Output must be ≤50 words.

{task_description}

Remember: Maximum 50 words. Do NOT exceed this limit.

Output:"""

# Use formatting for emphasis
prompt = """**CRITICAL RULE**: Output ONLY JSON. No explanations.

{task}

**REMINDER**: JSON ONLY."""
```

### Issue: High Token Costs
```python
# Audit token usage
def analyze_prompt_cost(prompt: str):
    tokens = count_tokens(prompt)
    cost_per_1k = 0.07  # Example rate
    cost_per_query = (tokens / 1000) * cost_per_1k
    
    print(f"Tokens: {tokens}")
    print(f"Cost per query: ${cost_per_query:.4f}")
    print(f"Cost per 1M queries: ${cost_per_query * 1_000_000:.2f}")

# Optimize
# 1. Remove examples (try zero-shot first)
# 2. Compress context (summarize long docs)
# 3. Use abbreviations for repeated terms
# 4. Remove filler words
```

## Key Anti-Patterns

- ❌ Starting with few-shot → ✅ Start zero-shot, add examples only if needed
- ❌ No output validation → ✅ Validate and retry with error feedback
- ❌ Hardcoded prompts → ✅ Store in config/database with versioning
- ❌ No token budgets → ✅ Set max_tokens, monitor usage, set alerts
- ❌ Temperature=1 for production → ✅ Use 0-0.3 for consistency

# LLM Evaluation - Quality Assessment & Monitoring

Automated evaluation frameworks, LLM-as-judge, and continuous monitoring for production AI systems.

## MLflow Evaluation for RAG Systems

```python
import mlflow
import pandas as pd

# Prepare evaluation dataset
eval_data = pd.DataFrame({
    "question": [
        "What is Unity Catalog?",
        "How do I create a Delta table?",
        "What is the refund policy?"
    ],
    "ground_truth": [
        "Unity Catalog is a unified governance solution...",
        "Create Delta tables using CREATE TABLE or df.write.format('delta')...",
        "Refunds are processed within 30 days..."
    ]
})

# Define RAG function to evaluate
def rag_function(question):
    # Retrieve context
    search_results = vector_index.similarity_search(query_text=question, num_results=5)
    context = "\n\n".join([doc['text'] for doc in search_results['result']['data_array']])
    
    # Generate answer
    response = llm.query(f"Answer based on context:\n{context}\n\nQuestion: {question}\nAnswer:")
    
    return {"answer": response, "context": context}

# Evaluate with MLflow
with mlflow.start_run(run_name="rag_evaluation"):
    results = mlflow.evaluate(
        model=rag_function,
        data=eval_data,
        model_type="question-answering",
        evaluators="default",  # relevance, faithfulness, etc.
        extra_metrics=[
            mlflow.metrics.latency(),
            mlflow.metrics.genai.answer_correctness()
        ]
    )
    
    print(f"Relevance: {results.metrics['relevance/v1/mean']:.2f}")
    print(f"Faithfulness: {results.metrics['faithfulness/v1/mean']:.2f}")
    print(f"Avg Latency: {results.metrics['latency/mean']:.2f}ms")
    
    # Save to Delta
    results_df = results.tables["eval_results_table"]
    spark.createDataFrame(results_df).write.format("delta").mode("append") \
        .saveAsTable("main.monitoring.rag_evaluation_results")
```

## LLM-as-Judge for Custom Evaluation

Use powerful LLM to evaluate responses with custom criteria.

```python
def llm_as_judge(question: str, answer: str, context: str, criterion: str) -> dict:
    judge_prompt = f"""You are an expert evaluator. Rate the answer on the following criterion:

Criterion: {criterion}

Question: {question}

Context:
{context}

Answer: {answer}

Provide:
1. Score (0-10)
2. Reasoning (2-3 sentences)

Output format:
Score: X
Reasoning: ...
"""
    
    response = w.serving_endpoints.query(
        name="databricks-llama-2-70b-chat",
        inputs=[{"prompt": judge_prompt, "max_tokens": 200, "temperature": 0}]
    )
    
    judge_output = response.predictions[0]
    
    # Parse score and reasoning
    import re
    score_match = re.search(r'Score:\s*(\d+)', judge_output)
    reasoning_match = re.search(r'Reasoning:\s*(.+)', judge_output, re.DOTALL)
    
    return {
        "score": int(score_match.group(1)) if score_match else 0,
        "reasoning": reasoning_match.group(1).strip() if reasoning_match else "",
        "raw_output": judge_output
    }

# Evaluate multiple criteria
criteria = [
    "Relevance: Does the answer address the question?",
    "Completeness: Is all necessary information included?",
    "Clarity: Is the answer easy to understand?",
    "Accuracy: Is the information factually correct based on context?"
]

eval_results = []
for criterion in criteria:
    result = llm_as_judge(question, answer, context, criterion)
    eval_results.append({
        "criterion": criterion,
        "score": result["score"],
        "reasoning": result["reasoning"]
    })

# Log to MLflow
with mlflow.start_run():
    for result in eval_results:
        mlflow.log_metric(f"judge_{result['criterion'].split(':')[0].lower()}", result["score"])
```

## Continuous Evaluation Pipeline

Automated daily evaluation on production traffic.

```python
import dlt
from datetime import datetime, timedelta

@dlt.table(comment="Daily RAG quality metrics")
def daily_rag_evaluation():
    # Get yesterday's production queries
    yesterday = (datetime.now() - timedelta(days=1)).date()
    
    inference_df = spark.sql(f"""
        SELECT 
            request_id,
            request_metadata.inputs.question as question,
            response.predictions[0] as answer,
            timestamp
        FROM system.serving.serving_endpoint_payload
        WHERE endpoint_name = 'rag_endpoint'
          AND DATE(timestamp) = '{yesterday}'
        ORDER BY RAND()
        LIMIT 100
    """)
    
    # Re-run evaluation
    eval_results = []
    for row in inference_df.collect():
        relevance = evaluate_relevance(row.question, row.answer)
        faithfulness = evaluate_faithfulness(row.answer, retrieve_context(row.question))
        
        eval_results.append({
            "date": yesterday,
            "request_id": row.request_id,
            "relevance_score": relevance,
            "faithfulness_score": faithfulness,
            "timestamp": datetime.now()
        })
    
    return spark.createDataFrame(eval_results)

# Alert on quality degradation
def check_quality_thresholds():
    metrics = spark.sql("""
        SELECT 
            AVG(relevance_score) as avg_relevance,
            AVG(faithfulness_score) as avg_faithfulness,
            COUNT(*) as sample_size
        FROM main.monitoring.daily_rag_evaluation
        WHERE date = CURRENT_DATE() - INTERVAL 1 DAY
    """).collect()[0]
    
    RELEVANCE_THRESHOLD = 0.7
    FAITHFULNESS_THRESHOLD = 0.8
    
    alerts = []
    if metrics.avg_relevance < RELEVANCE_THRESHOLD:
        alerts.append(f"Relevance dropped to {metrics.avg_relevance:.2f}")
    
    if metrics.avg_faithfulness < FAITHFULNESS_THRESHOLD:
        alerts.append(f"Faithfulness dropped to {metrics.avg_faithfulness:.2f}")
    
    if alerts:
        send_alert("\n".join(alerts))
    
    return metrics

# Schedule with Databricks Workflows (daily at 8 AM)
```

## A/B Testing Framework

Compare two models/prompts with statistical significance.

```python
def ab_test(test_queries: list, model_a: str, model_b: str, n_runs: int = 3):
    results = []
    
    for query in test_queries:
        scores_a = []
        scores_b = []
        
        for _ in range(n_runs):
            response_a = query_model(model_a, query)
            response_b = query_model(model_b, query)
            
            # LLM-as-judge pairwise comparison
            winner = llm_judge_pairwise(query, response_a, response_b)
            
            scores_a.append(1 if winner == "A" else 0)
            scores_b.append(1 if winner == "B" else 0)
        
        results.append({
            "query": query,
            "model_a_wins": sum(scores_a),
            "model_b_wins": sum(scores_b)
        })
    
    # Calculate statistics
    import scipy.stats as stats
    
    total_a_wins = sum(r['model_a_wins'] for r in results)
    total_b_wins = sum(r['model_b_wins'] for r in results)
    total_comparisons = len(test_queries) * n_runs
    
    # Binomial test
    p_value = stats.binom_test(total_a_wins, total_comparisons, 0.5, alternative='two-sided')
    
    print(f"Model A wins: {total_a_wins}/{total_comparisons} ({total_a_wins/total_comparisons:.1%})")
    print(f"Model B wins: {total_b_wins}/{total_comparisons} ({total_b_wins/total_comparisons:.1%})")
    print(f"P-value: {p_value:.4f} ({'significant' if p_value < 0.05 else 'not significant'})")
    
    # Log to MLflow
    with mlflow.start_run(run_name="ab_test"):
        mlflow.log_metrics({
            "model_a_win_rate": total_a_wins / total_comparisons,
            "model_b_win_rate": total_b_wins / total_comparisons,
            "p_value": p_value
        })
    
    return results

def llm_judge_pairwise(query: str, response_a: str, response_b: str) -> str:
    judge_prompt = f"""Compare these two responses and pick the better one (A or B):

Question: {query}

Response A:
{response_a}

Response B:
{response_b}

Which response is better? Consider relevance, accuracy, clarity, and completeness.

Output only: A or B
"""
    
    response = llm.query(judge_prompt, temperature=0)
    return "A" if "A" in response else "B"
```

## Best Practices

### Evaluation Dataset Quality
- **Diversity**: Cover edge cases, common queries, failure modes
- **Ground truth**: Human-verified correct answers
- **Size**: 50-100 minimum, 500+ for statistical significance
- **Refresh**: Update quarterly
- **Versioning**: Track changes in Unity Catalog

### Metric Selection
- **Relevance**: Always measure for Q&A systems
- **Faithfulness**: Critical for RAG (prevent hallucinations)
- **Latency**: P50, P95, P99 for UX
- **Cost**: Tokens per query, cost per 1K requests
- **Business metrics**: Task completion, user satisfaction

### Continuous Monitoring
- **Sampling**: Evaluate 1-10% of production traffic
- **Frequency**: Daily for high-traffic, weekly for low-traffic
- **Thresholds**: Alert at 2 standard deviations below baseline
- **Trend analysis**: Track metrics over time
- **Incident response**: Rollback plan when quality drops

## Common Issues & Solutions

### Issue: LLM-as-Judge Inconsistent
```python
# Use temperature=0 for deterministic evaluation
response = llm.query(judge_prompt, temperature=0, max_tokens=100)

# Run multiple times and average
scores = [llm_judge(question, answer) for _ in range(3)]
final_score = sum(scores) / len(scores)
```

### Issue: Evaluation Too Slow/Expensive
```python
# Sample evaluation set
eval_sample = eval_data.sample(n=100, random_state=42)

# Use cheaper judge model
judge_model = "databricks-llama-2-7b-chat"  # Instead of 70B

# Cache evaluation results
@functools.lru_cache(maxsize=1000)
def cached_evaluate(question, answer):
    return llm_judge(question, answer)
```

### Issue: High Scores But Poor UX
```python
# Add business-specific metrics
def user_satisfaction_metric(question, answer):
    feedback = spark.sql(f"""
        SELECT AVG(thumbs_up) as satisfaction
        FROM main.monitoring.user_feedback
        WHERE question = '{question}'
    """).collect()[0].satisfaction
    
    return feedback

# Include human evaluation
# Sample 10 queries/day for human rating
```

## Key Anti-Patterns

- ❌ Only evaluating at model update → ✅ Continuous daily evaluation
- ❌ Single metric (only relevance) → ✅ Multi-dimensional: relevance, faithfulness, latency, cost
- ❌ No ground truth → ✅ Maintain human-verified test set
- ❌ Evaluation dataset same as training → ✅ Separate held-out test set
- ❌ Ignoring latency and cost → ✅ Balance quality, speed, and cost

