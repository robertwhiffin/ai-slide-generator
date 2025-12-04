"""
Data Summarizer for Token Optimization.

This module provides intelligent summarization of Genie query results
to reduce token usage while preserving essential information for slide generation.

Key features:
- Time series detection and intelligent sampling
- Automatic aggregation (sum, mean, max, min)
- Key insights extraction
- Configurable row limits
"""

import json
import logging
from typing import Any

import pandas as pd

logger = logging.getLogger(__name__)


class DataSummarizer:
    """
    Summarizes Genie query results to reduce token usage.
    
    The summarizer detects data types and applies appropriate strategies:
    - Time series: Sample at intervals + provide aggregates
    - Categorical: Top N rows + totals
    - Small datasets: Pass through unchanged
    """
    
    def __init__(
        self,
        max_rows: int = 20,
        max_time_series_samples: int = 12,
    ):
        """
        Initialize the data summarizer.
        
        Args:
            max_rows: Maximum rows to include for non-time-series data
            max_time_series_samples: Maximum samples for time series data
        """
        self.max_rows = max_rows
        self.max_time_series_samples = max_time_series_samples
    
    def summarize(self, data: list[dict] | str, query: str = "") -> dict[str, Any]:
        """
        Summarize Genie query results.
        
        Args:
            data: Raw data from Genie (list of dicts or JSON string)
            query: Original query (used for context)
        
        Returns:
            Summarized data dictionary with:
            - type: 'time_series', 'categorical', or 'small'
            - data: Summarized data records
            - summary: Human-readable summary
            - aggregates: Computed aggregates (if applicable)
            - original_row_count: Number of rows before summarization
        """
        # Parse JSON string if needed
        if isinstance(data, str):
            try:
                data = json.loads(data)
            except json.JSONDecodeError:
                logger.warning("Failed to parse data as JSON, returning as-is")
                return {"type": "raw", "data": data, "original_row_count": 1}
        
        # Handle empty data
        if not data:
            return {"type": "empty", "data": [], "original_row_count": 0}
        
        # Convert to DataFrame for analysis
        df = pd.DataFrame(data)
        original_count = len(df)
        
        # Small dataset - pass through unchanged
        if original_count <= self.max_rows:
            logger.debug(f"Small dataset ({original_count} rows), passing through")
            return {
                "type": "small",
                "data": data,
                "original_row_count": original_count,
            }
        
        # Detect time series
        date_cols = self._detect_date_columns(df)
        
        if date_cols:
            return self._summarize_time_series(df, date_cols[0], query)
        else:
            return self._summarize_categorical(df, query)
    
    def _detect_date_columns(self, df: pd.DataFrame) -> list[str]:
        """Detect columns that contain date/time data."""
        date_cols = []
        
        for col in df.columns:
            col_lower = col.lower()
            # Check column name
            if any(keyword in col_lower for keyword in ['date', 'month', 'year', 'time', 'day', 'week']):
                date_cols.append(col)
                continue
            
            # Check if values look like dates
            if df[col].dtype == 'object':
                sample = df[col].iloc[0] if len(df) > 0 else None
                if sample and isinstance(sample, str):
                    if any(pattern in sample for pattern in ['-', '/']):
                        # Likely a date string
                        try:
                            pd.to_datetime(df[col].iloc[:5])
                            date_cols.append(col)
                        except Exception:
                            pass
        
        return date_cols
    
    def _summarize_time_series(
        self, 
        df: pd.DataFrame, 
        date_col: str,
        query: str = "",
    ) -> dict[str, Any]:
        """
        Summarize time series data with intelligent sampling.
        
        Strategy:
        1. Sample at regular intervals to get representative points
        2. Always include first and last data points
        3. Compute aggregates per category (if categorical column exists)
        4. Generate key insights
        """
        original_count = len(df)
        
        # Identify numeric and categorical columns
        numeric_cols = df.select_dtypes(include=['int64', 'float64', 'int32', 'float32']).columns.tolist()
        # Remove date column from categoricals if it's there
        categorical_cols = [c for c in df.columns if c not in numeric_cols and c != date_col]
        
        # Try to parse dates for proper sorting
        try:
            df[date_col] = pd.to_datetime(df[date_col])
            df = df.sort_values(date_col)
        except Exception:
            pass
        
        # Compute aggregates
        aggregates = {}
        
        if categorical_cols and numeric_cols:
            # Group by categorical column(s) and aggregate
            group_col = categorical_cols[0]  # Use first categorical column
            try:
                agg_df = df.groupby(group_col)[numeric_cols].agg(['sum', 'mean', 'max', 'min'])
                # Flatten column names
                agg_df.columns = ['_'.join(col).strip() for col in agg_df.columns.values]
                aggregates = agg_df.to_dict()
            except Exception as e:
                logger.debug(f"Failed to compute group aggregates: {e}")
        
        # Overall aggregates for numeric columns
        overall_agg = {}
        for col in numeric_cols:
            try:
                overall_agg[col] = {
                    "sum": float(df[col].sum()),
                    "mean": float(df[col].mean()),
                    "max": float(df[col].max()),
                    "min": float(df[col].min()),
                }
            except Exception:
                pass
        
        if overall_agg:
            aggregates["_overall"] = overall_agg
        
        # Sample data at regular intervals
        step = max(1, len(df) // self.max_time_series_samples)
        sampled_indices = list(range(0, len(df), step))
        
        # Ensure we include the last row
        if len(df) - 1 not in sampled_indices:
            sampled_indices.append(len(df) - 1)
        
        sampled_df = df.iloc[sampled_indices]
        
        # Convert dates back to strings for JSON serialization
        try:
            if pd.api.types.is_datetime64_any_dtype(sampled_df[date_col]):
                sampled_df = sampled_df.copy()
                sampled_df[date_col] = sampled_df[date_col].dt.strftime('%Y-%m-%d')
        except Exception:
            pass
        
        # Generate summary text
        summary_parts = [
            f"Time series with {original_count} data points",
        ]
        
        # Add date range
        try:
            date_min = df[date_col].min()
            date_max = df[date_col].max()
            if hasattr(date_min, 'strftime'):
                date_min = date_min.strftime('%Y-%m-%d')
                date_max = date_max.strftime('%Y-%m-%d')
            summary_parts.append(f"Date range: {date_min} to {date_max}")
        except Exception:
            pass
        
        # Add category info
        if categorical_cols:
            unique_cats = df[categorical_cols[0]].nunique()
            summary_parts.append(f"Categories ({categorical_cols[0]}): {unique_cats}")
        
        logger.info(
            "Summarized time series data",
            extra={
                "original_rows": original_count,
                "sampled_rows": len(sampled_df),
                "date_column": date_col,
                "has_aggregates": bool(aggregates),
            },
        )
        
        return {
            "type": "time_series",
            "data": sampled_df.to_dict(orient="records"),
            "summary": " | ".join(summary_parts),
            "aggregates": aggregates,
            "original_row_count": original_count,
            "date_column": date_col,
        }
    
    def _summarize_categorical(
        self,
        df: pd.DataFrame,
        query: str = "",
    ) -> dict[str, Any]:
        """
        Summarize categorical/ranked data.
        
        Strategy:
        1. Keep top N rows (assumed to be ranked by importance)
        2. Add total counts and sums for numeric columns
        """
        original_count = len(df)
        
        # Identify numeric columns for aggregation
        numeric_cols = df.select_dtypes(include=['int64', 'float64', 'int32', 'float32']).columns.tolist()
        
        # Compute aggregates
        aggregates = {}
        for col in numeric_cols:
            try:
                aggregates[col] = {
                    "total": float(df[col].sum()),
                    "mean": float(df[col].mean()),
                }
            except Exception:
                pass
        
        # Take top N rows
        top_df = df.head(self.max_rows)
        
        # Generate summary
        summary = f"Top {len(top_df)} of {original_count} total records"
        
        logger.info(
            "Summarized categorical data",
            extra={
                "original_rows": original_count,
                "returned_rows": len(top_df),
            },
        )
        
        return {
            "type": "categorical",
            "data": top_df.to_dict(orient="records"),
            "summary": summary,
            "aggregates": aggregates,
            "original_row_count": original_count,
        }
    
    def format_for_llm(self, summarized_data: dict[str, Any], query: str = "") -> str:
        """
        Format summarized data as a compact string for LLM consumption.
        
        Args:
            summarized_data: Output from summarize()
            query: Original query for context
        
        Returns:
            Compact string representation
        """
        parts = []
        
        # Add query context
        if query:
            parts.append(f"Query: {query}")
        
        # Add summary
        if summarized_data.get("summary"):
            parts.append(f"Summary: {summarized_data['summary']}")
        
        # Add aggregates if present
        aggregates = summarized_data.get("aggregates", {})
        if aggregates:
            # Format aggregates compactly
            agg_parts = []
            for key, value in aggregates.items():
                if key == "_overall":
                    continue  # Skip overall for compact format
                if isinstance(value, dict):
                    # Sum is usually most important
                    if "sum" in value:
                        agg_parts.append(f"{key}: total={value['sum']:.0f}")
                    elif "total" in value:
                        agg_parts.append(f"{key}: total={value['total']:.0f}")
            if agg_parts:
                parts.append("Aggregates: " + ", ".join(agg_parts[:5]))  # Limit to 5
        
        # Add data as compact JSON
        data = summarized_data.get("data", [])
        if data:
            parts.append(f"Data ({len(data)} rows): {json.dumps(data)}")
        
        return "\n".join(parts)


# Module-level instance for convenience
_summarizer: DataSummarizer | None = None


def get_summarizer() -> DataSummarizer:
    """Get or create the default DataSummarizer instance."""
    global _summarizer
    if _summarizer is None:
        _summarizer = DataSummarizer()
    return _summarizer


def summarize_genie_response(data: list[dict] | str, query: str = "") -> dict[str, Any]:
    """
    Convenience function to summarize Genie response data.
    
    Args:
        data: Raw data from Genie query
        query: Original query string
    
    Returns:
        Summarized data dictionary
    """
    return get_summarizer().summarize(data, query)

