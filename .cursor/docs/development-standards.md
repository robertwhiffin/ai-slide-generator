# Development Standards Guide

Comprehensive guide to code quality, documentation, and development workflow standards.

## Overview

Code quality, documentation, and development workflow standards for production codebases.

## Quick Start Patterns

### Code Quality

```python
# Good: Clear, documented, tested
def calculate_customer_ltv(
    transactions_df: DataFrame,
    customer_id: str,
    lookback_days: int = 365
) -> float:
    """
    Calculate customer lifetime value over specified period.
    
    Args:
        transactions_df: DataFrame with columns [customer_id, amount, date]
        customer_id: Target customer ID
        lookback_days: Number of days to look back (default 365)
    
    Returns:
        Total LTV as float
    
    Raises:
        ValueError: If customer_id not found
    """
    cutoff_date = datetime.now() - timedelta(days=lookback_days)
    
    ltv = transactions_df \
        .filter(F.col("customer_id") == customer_id) \
        .filter(F.col("date") >= cutoff_date) \
        .agg(F.sum("amount").alias("total")) \
        .collect()[0]["total"]
    
    return float(ltv) if ltv else 0.0
```

### Documentation Standards

```markdown
# Project Name

## Overview
Brief description of project purpose.

## Architecture
System design, data flow, key components.

## Getting Started
1. Prerequisites
2. Installation
3. Configuration
4. Running locally

## API Reference
Endpoints, parameters, examples.

## Contributing
Development workflow, testing, PR process.
```

### Development Workflow

```bash
# 1. Create feature branch
git checkout -b feature/add-fraud-detection

# 2. Make changes, commit with clear messages
git commit -m "feat: add fraud detection model training pipeline"

# 3. Run tests locally
pytest tests/

# 4. Push and create PR
git push origin feature/add-fraud-detection

# 5. Code review, merge to main
```

## Core Principles

- **Clarity**: Code should be self-documenting
- **Consistency**: Follow team conventions
- **Documentation**: README, API docs, inline comments
- **Testing**: Unit, integration, end-to-end tests
- **Version Control**: Clear commits, descriptive PRs

## References

- [Python Style Guide (PEP 8)](https://peps.python.org/pep-0008/)
- [Spark Best Practices](https://spark.apache.org/docs/latest/sql-performance-tuning.html)

