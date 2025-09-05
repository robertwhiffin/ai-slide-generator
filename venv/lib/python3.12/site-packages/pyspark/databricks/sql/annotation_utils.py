#
# DATABRICKS CONFIDENTIAL & PROPRIETARY
# __________________
#
# Copyright 2021-present Databricks, Inc.
# All Rights Reserved.
#
# NOTICE:  All information contained herein is, and remains the property of Databricks, Inc.
# and its suppliers, if any.  The intellectual and technical concepts contained herein are
# proprietary to Databricks, Inc. and its suppliers and may be covered by U.S. and foreign Patents,
# patents in process, and are protected by trade secret and/or copyright law. Dissemination, use,
# or reproduction of this information is strictly forbidden unless prior written permission is
# obtained from Databricks, Inc.
#
# If you view or obtain a copy of this information and believe Databricks, Inc. may not have
# intended it to be made available, please promptly report it to Databricks Legal Department
# @ legal@databricks.com.
#

"""
Apache Spark DataFrame metadata annotation utils.

This file provides the constants that can be useful for DataFrame column annotations.
It mirrors the constants provided under
`sql/core/src/main/scala/com/databricks/sql/util/AnnotationUtils.scala`.

Example Usage:
```
df = df.withMetadata(col, {SEMANTIC_TYPE_KEY: NATIVE})
```

Please also update `sql/core/src/main/scala/com/databricks/sql/util/AnnotationUtils.scala`
if the current file is updated.
"""


# pre-defined top-level keys
CONTENT_ANNOTATION = "spark.contentAnnotation"
MIME_TYPE = "mimeType"
MIME_TYPE_KEY = f"{CONTENT_ANNOTATION}.{MIME_TYPE}"
SEMANTIC_TYPE = "semanticType"
SEMANTIC_TYPE_KEY = f"{CONTENT_ANNOTATION}.{SEMANTIC_TYPE}"

# pre-defined annotation values

# mime types
APPLICATION = "application"
AUDIO = "audio"
IMAGE = "image"
VIDEO = "video"
MIME_TEXT = "mime_text"

# semantic types
CATEGORICAL = "categorical"
NATIVE = "native"
TEXT = "text"
NUMERIC = "numeric"
DATETIME = "datetime"

OTHER = "other"
