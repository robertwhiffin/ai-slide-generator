"""
Token comparison tests between original agent and two-stage generator.

These tests compare token usage, execution time, and output quality
to validate the two-stage architecture optimization.

Run with: pytest tests/performance/test_token_comparison.py -v

Reference: docs/TWO_STAGE_CSV_IMPLEMENTATION_PLAN.md
"""

import time
from typing import Any

import mlflow
import pytest

from tests.fixtures.test_prompts import TEST_PROMPTS


class TestTokenComparison:
    """
    Compare token usage between original agent and two-stage generator.
    
    Each test runs the same prompt through both architectures and logs
    results to MLflow for side-by-side comparison.
    """
    
    @pytest.mark.parametrize("test_name,test_config", TEST_PROMPTS.items())
    def test_token_comparison(
        self,
        test_name: str,
        test_config: dict,
        original_agent,
        two_stage_generator,
        mlflow_experiment,
        test_run_id: str,
    ):
        """
        Compare token usage for the same prompt across architectures.
        
        This test runs sequentially:
        1. Run original agent and log metrics
        2. Run two-stage generator and log metrics
        3. Both results available in MLflow for comparison
        """
        agent, agent_session = original_agent
        generator, generator_session = two_stage_generator
        prompt = test_config["prompt"]
        
        results = {}
        
        # =================================================================
        # Test Original Agent
        # =================================================================
        with mlflow.start_run(
            run_name=f"{test_run_id}_{test_name}_original",
            tags={
                "architecture": "original_iterative",
                "test_name": test_name,
                "test_type": "comparison",
            }
        ):
            mlflow.log_param("prompt", prompt)
            mlflow.log_param("expected_slides", test_config["expected_slides"])
            mlflow.log_param("description", test_config.get("description", ""))
            
            start_time = time.time()
            result_original = agent.invoke(prompt, agent_session)
            elapsed_original = time.time() - start_time
            
            mlflow.log_metric("execution_time_seconds", elapsed_original)
            mlflow.log_metric("success", 1 if result_original.get("html") else 0)
            mlflow.log_metric("html_length", len(result_original.get("html", "")))
            
            results["original"] = {
                "success": bool(result_original.get("html")),
                "html_length": len(result_original.get("html", "")),
                "execution_time": elapsed_original,
            }
        
        # =================================================================
        # Test Two-Stage Generator
        # =================================================================
        with mlflow.start_run(
            run_name=f"{test_run_id}_{test_name}_two_stage",
            tags={
                "architecture": "two_stage_csv",
                "test_name": test_name,
                "test_type": "comparison",
            }
        ):
            mlflow.log_param("prompt", prompt)
            mlflow.log_param("expected_slides", test_config["expected_slides"])
            mlflow.log_param("description", test_config.get("description", ""))
            
            start_time = time.time()
            result_two_stage = generator.generate_slides(prompt, generator_session)
            elapsed_two_stage = time.time() - start_time
            
            mlflow.log_metric("execution_time_seconds", elapsed_two_stage)
            mlflow.log_metric("success", 1 if result_two_stage.get("html") else 0)
            mlflow.log_metric("html_length", len(result_two_stage.get("html", "")))
            mlflow.log_metric("queries_executed", len(result_two_stage.get("queries_executed", [])))
            mlflow.log_metric("total_data_rows", result_two_stage.get("total_data_rows", 0))
            mlflow.log_metric("slide_count", result_two_stage.get("slide_count", 0))
            
            results["two_stage"] = {
                "success": bool(result_two_stage.get("html")),
                "html_length": len(result_two_stage.get("html", "")),
                "execution_time": elapsed_two_stage,
                "queries_executed": result_two_stage.get("queries_executed", []),
                "total_data_rows": result_two_stage.get("total_data_rows", 0),
            }
        
        # =================================================================
        # Assertions
        # =================================================================
        assert results["original"]["success"], "Original agent failed to generate"
        assert results["two_stage"]["success"], "Two-stage generator failed to generate"
        
        # Log comparison summary
        print(f"\n{'='*60}")
        print(f"TEST: {test_name}")
        print(f"PROMPT: {prompt[:60]}...")
        print(f"{'='*60}")
        print(f"Original Agent:")
        print(f"  - HTML Length: {results['original']['html_length']}")
        print(f"  - Time: {results['original']['execution_time']:.2f}s")
        print(f"Two-Stage Generator:")
        print(f"  - HTML Length: {results['two_stage']['html_length']}")
        print(f"  - Time: {results['two_stage']['execution_time']:.2f}s")
        print(f"  - Queries: {len(results['two_stage']['queries_executed'])}")
        print(f"  - Data Rows: {results['two_stage']['total_data_rows']}")
        print(f"{'='*60}")
        print("Check MLflow UI for detailed token metrics")


class TestTwoStageOnly:
    """
    Tests that run only the two-stage generator.
    
    Useful for development and debugging without needing
    to wait for the slower original agent.
    """
    
    def test_basic_generation(
        self,
        two_stage_generator,
        mlflow_experiment,
    ):
        """Test basic slide generation with two-stage generator."""
        generator, session_id = two_stage_generator
        
        prompt = TEST_PROMPTS["single_metric"]["prompt"]
        
        with mlflow.start_run(run_name="test_basic_generation"):
            mlflow.log_param("prompt", prompt)
            
            result = generator.generate_slides(prompt, session_id)
            
            mlflow.log_metric("success", 1 if result.get("html") else 0)
            mlflow.log_metric("queries_executed", len(result.get("queries_executed", [])))
            
            assert result.get("html"), "Failed to generate HTML"
            assert result.get("queries_executed"), "No queries were executed"
            
            print(f"\nGenerated slide with {len(result.get('queries_executed', []))} queries")
            print(f"Total data rows: {result.get('total_data_rows', 0)}")
    
    def test_query_planner(
        self,
        two_stage_generator,
        mlflow_experiment,
    ):
        """Test that query planner generates appropriate queries."""
        generator, _ = two_stage_generator
        
        for test_name, config in TEST_PROMPTS.items():
            with mlflow.start_run(run_name=f"planner_test_{test_name}"):
                plan_result = generator.query_planner.plan_queries(config["prompt"])
                queries = plan_result["queries"]
                
                mlflow.log_param("test_name", test_name)
                mlflow.log_metric("num_queries", len(queries))
                mlflow.log_param("rationale", plan_result.get("rationale", "")[:200])
                
                # Validate query count
                assert len(queries) >= config["expected_queries_min"], \
                    f"Too few queries: {len(queries)} < {config['expected_queries_min']}"
                assert len(queries) <= config["expected_queries_max"], \
                    f"Too many queries: {len(queries)} > {config['expected_queries_max']}"
                
                print(f"\n{test_name}: Generated {len(queries)} queries")
                for i, q in enumerate(queries, 1):
                    print(f"  {i}. {q}")


class TestPerformanceBenchmarks:
    """
    Performance benchmarks for production readiness.
    
    These tests validate that the two-stage generator meets
    performance requirements.
    """
    
    def test_execution_time(
        self,
        two_stage_generator,
        mlflow_experiment,
    ):
        """
        Benchmark execution time.
        
        Target: Complete in under 60 seconds.
        """
        generator, session_id = two_stage_generator
        prompt = TEST_PROMPTS["3_slides_basic"]["prompt"]
        
        with mlflow.start_run(run_name="benchmark_execution_time"):
            start = time.time()
            result = generator.generate_slides(prompt, session_id)
            elapsed = time.time() - start
            
            mlflow.log_metric("execution_time_seconds", elapsed)
            mlflow.log_metric("success", 1 if result.get("html") else 0)
            
            # Should complete in under 120 seconds (Genie queries can be slow)
            assert elapsed < 120, f"Execution too slow: {elapsed:.2f}s"
            
            print(f"\nExecution time: {elapsed:.2f}s")
            print(f"Queries: {len(result.get('queries_executed', []))}")
            print(f"Data rows: {result.get('total_data_rows', 0)}")
    
    def test_multiple_runs_consistency(
        self,
        two_stage_generator,
        mlflow_experiment,
    ):
        """
        Test consistency across multiple runs.
        
        Validates that the generator produces consistent results.
        """
        generator, session_id = two_stage_generator
        prompt = TEST_PROMPTS["single_metric"]["prompt"]
        
        times = []
        query_counts = []
        
        # Run 3 times
        for i in range(3):
            with mlflow.start_run(run_name=f"consistency_run_{i+1}"):
                start = time.time()
                result = generator.generate_slides(prompt, session_id)
                elapsed = time.time() - start
                
                times.append(elapsed)
                query_counts.append(len(result.get("queries_executed", [])))
                
                mlflow.log_metric("execution_time", elapsed)
                mlflow.log_metric("run_number", i + 1)
        
        # Check consistency
        avg_time = sum(times) / len(times)
        time_variance = max(times) - min(times)
        
        print(f"\n3 Run Consistency Test:")
        print(f"  Average time: {avg_time:.2f}s")
        print(f"  Time variance: {time_variance:.2f}s")
        print(f"  Query counts: {query_counts}")
        
        # Variance should be reasonable (< 50% of average)
        assert time_variance < avg_time * 0.5, \
            f"Execution time too variable: {time_variance:.2f}s variance"

