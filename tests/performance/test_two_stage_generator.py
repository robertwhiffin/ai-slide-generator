"""
Unit tests for TwoStageGenerator.

These tests validate the individual components of the two-stage generator
without requiring full integration with Databricks.

Reference: docs/TWO_STAGE_CSV_IMPLEMENTATION_PLAN.md
"""

import json
from unittest.mock import AsyncMock, MagicMock, Mock, patch

import pytest

from src.services.prompts import format_csv_data_for_llm


class TestFormatCsvDataForLlm:
    """Test the CSV data formatting function."""
    
    def test_formats_single_query_result(self):
        """Test formatting a single query result."""
        csv_results = {
            "What is total spend?": {
                "csv": "category,amount\nA,100\nB,200",
                "row_count": 2,
                "message": "",
            }
        }
        
        formatted = format_csv_data_for_llm(csv_results)
        
        assert "### Query 1:" in formatted
        assert "What is total spend?" in formatted
        assert "**Rows returned:** 2" in formatted
        assert "category,amount" in formatted
        assert "A,100" in formatted
    
    def test_formats_multiple_queries(self):
        """Test formatting multiple query results."""
        csv_results = {
            "Query 1": {"csv": "a,b\n1,2", "row_count": 1, "message": ""},
            "Query 2": {"csv": "x,y\n3,4", "row_count": 1, "message": ""},
            "Query 3": {"csv": "p,q\n5,6", "row_count": 1, "message": ""},
        }
        
        formatted = format_csv_data_for_llm(csv_results)
        
        assert "### Query 1:" in formatted
        assert "### Query 2:" in formatted
        assert "### Query 3:" in formatted
    
    def test_includes_genie_message(self):
        """Test that Genie messages are included."""
        csv_results = {
            "Query": {
                "csv": "a,b\n1,2",
                "row_count": 1,
                "message": "Note: Data is from last month",
            }
        }
        
        formatted = format_csv_data_for_llm(csv_results)
        
        assert "**Genie note:**" in formatted
        assert "Data is from last month" in formatted
    
    def test_handles_empty_csv(self):
        """Test handling of queries with no data."""
        csv_results = {
            "Empty query": {
                "csv": "",
                "row_count": 0,
                "message": "",
            }
        }
        
        formatted = format_csv_data_for_llm(csv_results)
        
        assert "*No data returned*" in formatted
    
    def test_handles_error_results(self):
        """Test handling of query errors."""
        csv_results = {
            "Failed query": {
                "csv": "",
                "row_count": 0,
                "error": "Genie timeout",
            }
        }
        
        formatted = format_csv_data_for_llm(csv_results)
        
        assert "**Error:**" in formatted
        assert "Genie timeout" in formatted
    
    def test_no_truncation_large_data(self):
        """Verify that large CSV data is NOT truncated."""
        # Create CSV with 100 rows
        rows = ["col1,col2,col3"] + [f"val{i},val{i+1},val{i+2}" for i in range(100)]
        large_csv = "\n".join(rows)
        
        csv_results = {
            "Large query": {
                "csv": large_csv,
                "row_count": 100,
                "message": "",
            }
        }
        
        formatted = format_csv_data_for_llm(csv_results)
        
        # All 100 rows should be present (plus header)
        assert "val99" in formatted  # Last row should be present
        assert "**Rows returned:** 100" in formatted


class TestQueryPlannerParsing:
    """Test query planner response parsing."""
    
    def test_parse_valid_json(self):
        """Test parsing valid JSON response."""
        from src.services.query_planner import QueryPlanner
        
        planner = QueryPlanner.__new__(QueryPlanner)
        
        content = '{"queries": ["q1", "q2"], "rationale": "test"}'
        result = planner._parse_planning_response(content)
        
        assert result["queries"] == ["q1", "q2"]
        assert result["rationale"] == "test"
    
    def test_parse_json_with_markdown(self):
        """Test parsing JSON wrapped in markdown code blocks."""
        from src.services.query_planner import QueryPlanner
        
        planner = QueryPlanner.__new__(QueryPlanner)
        
        content = '''```json
{"queries": ["q1", "q2"], "rationale": "test"}
```'''
        result = planner._parse_planning_response(content)
        
        assert result["queries"] == ["q1", "q2"]
    
    def test_parse_adds_missing_rationale(self):
        """Test that missing rationale is added as empty string."""
        from src.services.query_planner import QueryPlanner
        
        planner = QueryPlanner.__new__(QueryPlanner)
        
        content = '{"queries": ["q1"]}'
        result = planner._parse_planning_response(content)
        
        assert result["rationale"] == ""
    
    def test_parse_raises_on_missing_queries(self):
        """Test that missing queries field raises error."""
        from src.services.query_planner import QueryPlanner, QueryPlanningError
        
        planner = QueryPlanner.__new__(QueryPlanner)
        
        content = '{"rationale": "test"}'
        
        with pytest.raises(QueryPlanningError, match="missing 'queries'"):
            planner._parse_planning_response(content)
    
    def test_parse_raises_on_empty_queries(self):
        """Test that empty queries list raises error."""
        from src.services.query_planner import QueryPlanner, QueryPlanningError
        
        planner = QueryPlanner.__new__(QueryPlanner)
        
        content = '{"queries": []}'
        
        with pytest.raises(QueryPlanningError, match="empty queries"):
            planner._parse_planning_response(content)


class TestTwoStageGeneratorHelpers:
    """Test helper methods of TwoStageGenerator."""
    
    def test_is_edit_request_detects_edits(self):
        """Test edit request detection."""
        from src.services.two_stage_generator import TwoStageGenerator
        
        generator = TwoStageGenerator.__new__(TwoStageGenerator)
        
        edit_requests = [
            "Change the title on slide 1",
            "Modify the chart color",
            "Update the data in slide 2",
            "Fix the typo in the heading",
            "Add a new chart to slide 3",
        ]
        
        for request in edit_requests:
            assert generator._is_edit_request(request), f"Should detect edit: {request}"
    
    def test_is_edit_request_ignores_new(self):
        """Test that new requests are not detected as edits."""
        from src.services.two_stage_generator import TwoStageGenerator
        
        generator = TwoStageGenerator.__new__(TwoStageGenerator)
        
        new_requests = [
            "Create 3 slides about sales",
            "Generate a presentation on Q3 results",
            "Show me the top 10 products",
        ]
        
        for request in new_requests:
            assert not generator._is_edit_request(request), f"Should not detect edit: {request}"
    
    def test_clean_html_response_removes_markdown(self):
        """Test HTML cleaning removes markdown wrappers."""
        from src.services.two_stage_generator import TwoStageGenerator
        
        generator = TwoStageGenerator.__new__(TwoStageGenerator)
        
        html_with_markdown = "```html\n<div>content</div>\n```"
        cleaned = generator._clean_html_response(html_with_markdown)
        
        assert cleaned == "<div>content</div>"
    
    def test_clean_html_response_handles_plain(self):
        """Test HTML cleaning preserves plain HTML."""
        from src.services.two_stage_generator import TwoStageGenerator
        
        generator = TwoStageGenerator.__new__(TwoStageGenerator)
        
        plain_html = "<div>content</div>"
        cleaned = generator._clean_html_response(plain_html)
        
        assert cleaned == "<div>content</div>"
    
    def test_count_slides_finds_slides(self):
        """Test slide counting in HTML."""
        from src.services.two_stage_generator import TwoStageGenerator
        
        generator = TwoStageGenerator.__new__(TwoStageGenerator)
        
        html = '''
        <div class="slide">Slide 1</div>
        <div class="slide">Slide 2</div>
        <div class="slide">Slide 3</div>
        '''
        
        count = generator._count_slides(html)
        assert count == 3

