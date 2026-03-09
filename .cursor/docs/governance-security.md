# Databricks Governance & Security Guide

Comprehensive guide to data governance, access control, and security with Unity Catalog.

## Overview

Data governance, access control, and security with Unity Catalog for production data platforms.

## Quick Start Patterns

### Unity Catalog Permissions

```sql
-- Grant catalog access
GRANT USE CATALOG ON CATALOG main TO `data_engineers`;

-- Grant schema access
GRANT USE SCHEMA ON SCHEMA main.bronze TO `data_engineers`;
GRANT CREATE TABLE ON SCHEMA main.bronze TO `data_engineers`;

-- Grant table permissions
GRANT SELECT ON TABLE main.silver.customers TO `analysts`;
GRANT SELECT, MODIFY ON TABLE main.silver.customers TO `data_engineers`;

-- Row-level security
CREATE OR REPLACE FUNCTION main.default.customer_filter(region STRING)
RETURN IF(IS_ACCOUNT_GROUP_MEMBER('admins'), TRUE, current_user() = region);

ALTER TABLE main.silver.customers SET ROW FILTER main.default.customer_filter ON (region);
```

### PII Protection

```python
# Detect PII
import re

def detect_pii(text):
    patterns = {
        "ssn": r'\b\d{3}-\d{2}-\d{4}\b',
        "email": r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b',
        "phone": r'\b\d{3}[-.]?\d{3}[-.]?\d{4}\b'
    }
    return {k: bool(re.search(v, text)) for k, v in patterns.items()}

# Mask PII
def mask_ssn(text):
    return re.sub(r'\b(\d{3})-(\d{2})-(\d{4})\b', r'XXX-XX-\3', text)
```

### Audit Logging

```sql
-- Query audit logs
SELECT 
    event_time,
    user_identity.email as user,
    service_name,
    action_name,
    request_params.full_name_arg as resource
FROM system.access.audit
WHERE action_name LIKE '%table%'
  AND event_date >= current_date() - 7
ORDER BY event_time DESC;
```

## Core Capabilities

- **Unity Catalog**: Three-level namespace, centralized governance
- **Access Control**: GRANT/REVOKE, row/column-level security
- **Data Lineage**: Automatic tracking, impact analysis
- **PII Detection**: Regex patterns, ML-based detection
- **Compliance**: Audit logs, data classification, retention policies

## References

- [Unity Catalog](https://docs.databricks.com/data-governance/unity-catalog/)
- [Row/Column Security](https://docs.databricks.com/security/data/row-and-column-filters.html)
- [Audit Logging](https://docs.databricks.com/administration-guide/account-settings/audit-logs.html)

