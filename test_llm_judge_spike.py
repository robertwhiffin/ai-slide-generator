#!/usr/bin/env python3
"""Quick spike test for LLM as Judge functionality.

Run this to verify the MLflow judge works before building full implementation.

Usage:
    source .venv/bin/activate
    python test_llm_judge_spike.py
"""

import asyncio
import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent))


# Sample test data - simulating what Genie would return
SAMPLE_GENIE_DATA = """quarter,revenue,growth_pct
Q1 2024,7234567,12.5
Q2 2024,8456789,16.9
Q3 2024,9123456,7.9
Q4 2024,10234567,12.2"""

# Sample slide HTML - what the LLM generated
SAMPLE_SLIDE_HTML_CORRECT = """
<div class="slide">
  <h1>Quarterly Revenue Performance</h1>
  <h2>Strong growth throughout 2024</h2>
  
  <div class="metrics">
    <div class="metric">
      <span class="label">Q1 Revenue</span>
      <span class="value">$7.2M</span>
    </div>
    <div class="metric">
      <span class="label">Q2 Revenue</span>
      <span class="value">$8.5M</span>
    </div>
    <div class="metric">
      <span class="label">Q3 Revenue</span>
      <span class="value">$9.1M</span>
    </div>
    <div class="metric">
      <span class="label">Q4 Revenue</span>
      <span class="value">$10.2M</span>
    </div>
  </div>
  
  <p>Total growth of 41% year-over-year with consistent quarterly improvements.</p>
  
  <canvas id="revenueChart"></canvas>
</div>
<script>
new Chart(document.getElementById('revenueChart'), {
  type: 'bar',
  data: {
    labels: ['Q1', 'Q2', 'Q3', 'Q4'],
    datasets: [{
      label: 'Revenue (M)',
      data: [7.2, 8.5, 9.1, 10.2]
    }]
  }
});
</script>
"""

# Sample slide with WRONG numbers (for testing failure detection)
SAMPLE_SLIDE_HTML_WRONG = """
<div class="slide">
  <h1>Quarterly Revenue Performance</h1>
  
  <div class="metrics">
    <div class="metric">
      <span class="label">Q1 Revenue</span>
      <span class="value">$9.5M</span>  <!-- WRONG: Should be 7.2M -->
    </div>
    <div class="metric">
      <span class="label">Q2 Revenue</span>
      <span class="value">$12.3M</span>  <!-- WRONG: Should be 8.5M -->
    </div>
  </div>
  
  <p>Revenue tripled in Q2 due to new product launch.</p>  <!-- HALLUCINATED -->
</div>
"""

# Sample title slide (no numbers)
SAMPLE_TITLE_SLIDE = """
<div class="slide">
  <h1>Q4 2024 Revenue Analysis</h1>
  <h2>Prepared by the Analytics Team</h2>
  <p>December 2024</p>
</div>
"""


def print_header(text: str) -> None:
    print("\n" + "=" * 60)
    print(f"  {text}")
    print("=" * 60)


def print_result(result) -> None:
    print(f"\n  Score: {result.score}")
    print(f"  Rating: {result.rating}")
    print(f"  Duration: {result.duration_ms}ms")
    print(f"  Error: {result.error}")
    print(f"  Trace ID: {result.trace_id}")
    print(f"\n  Explanation:\n  {result.explanation[:500]}...")
    if result.issues:
        print(f"\n  Issues: {result.issues}")


async def test_correct_slide():
    """Test with correct numbers - should score high."""
    print_header("TEST 1: Correct Slide (should score HIGH)")
    
    from src.services.evaluation import evaluate_with_judge
    
    print("  Running evaluation...")
    result = await evaluate_with_judge(
        genie_data=SAMPLE_GENIE_DATA,
        slide_content=SAMPLE_SLIDE_HTML_CORRECT,
    )
    
    print_result(result)
    
    if result.error:
        print(f"\n  ❌ ERROR: {result.error_message}")
        return False
    
    if result.score >= 70:
        print("\n  ✅ PASSED: Score >= 70 (as expected for correct data)")
        return True
    else:
        print(f"\n  ⚠️ UNEXPECTED: Score {result.score} < 70 for correct data")
        return False


async def test_wrong_slide():
    """Test with wrong numbers - should score low."""
    print_header("TEST 2: Wrong Slide (should score LOW)")
    
    from src.services.evaluation import evaluate_with_judge
    
    print("  Running evaluation...")
    result = await evaluate_with_judge(
        genie_data=SAMPLE_GENIE_DATA,
        slide_content=SAMPLE_SLIDE_HTML_WRONG,
    )
    
    print_result(result)
    
    if result.error:
        print(f"\n  ❌ ERROR: {result.error_message}")
        return False
    
    if result.score < 70:
        print("\n  ✅ PASSED: Score < 70 (as expected for wrong data)")
        return True
    else:
        print(f"\n  ⚠️ UNEXPECTED: Score {result.score} >= 70 for wrong data")
        return False


async def test_title_slide():
    """Test with title slide (no numbers) - should handle gracefully."""
    print_header("TEST 3: Title Slide (no numbers)")
    
    from src.services.evaluation import evaluate_with_judge
    
    print("  Running evaluation...")
    result = await evaluate_with_judge(
        genie_data=SAMPLE_GENIE_DATA,
        slide_content=SAMPLE_TITLE_SLIDE,
    )
    
    print_result(result)
    
    if result.error:
        print(f"\n  ❌ ERROR: {result.error_message}")
        return False
    
    # Title slide should either score high (nothing wrong) or we detect no numbers
    print("\n  ℹ️ INFO: Title slide handled - check explanation for appropriate response")
    return True


async def test_mlflow_imports():
    """Test that MLflow imports work."""
    print_header("TEST 0: MLflow Imports")
    
    try:
        import mlflow
        print(f"  ✅ mlflow version: {mlflow.__version__}")
        
        from mlflow.genai.judges import custom_prompt_judge
        print("  ✅ custom_prompt_judge imported")
        
        from mlflow.genai.scorers import scorer
        print("  ✅ scorer imported")
        
        # Check if genai.evaluate exists
        if hasattr(mlflow, 'genai') and hasattr(mlflow.genai, 'evaluate'):
            print("  ✅ mlflow.genai.evaluate available")
        else:
            print("  ⚠️ mlflow.genai.evaluate not found - may need different API")
            
        return True
        
    except ImportError as e:
        print(f"  ❌ Import failed: {e}")
        return False


async def main():
    print("\n" + "🔨" * 30)
    print("  LLM AS JUDGE - SPIKE TEST")
    print("🔨" * 30)
    
    results = {}
    
    # Test 0: Imports
    results["imports"] = await test_mlflow_imports()
    
    if not results["imports"]:
        print("\n❌ MLflow imports failed - cannot proceed with other tests")
        return
    
    # Test 1: Correct slide
    try:
        results["correct"] = await test_correct_slide()
    except Exception as e:
        print(f"\n  ❌ EXCEPTION: {e}")
        results["correct"] = False
    
    # Test 2: Wrong slide
    try:
        results["wrong"] = await test_wrong_slide()
    except Exception as e:
        print(f"\n  ❌ EXCEPTION: {e}")
        results["wrong"] = False
    
    # Test 3: Title slide
    try:
        results["title"] = await test_title_slide()
    except Exception as e:
        print(f"\n  ❌ EXCEPTION: {e}")
        results["title"] = False
    
    # Summary
    print_header("SUMMARY")
    
    all_passed = all(results.values())
    
    for test_name, passed in results.items():
        status = "✅ PASS" if passed else "❌ FAIL"
        print(f"  {status}: {test_name}")
    
    print()
    if all_passed:
        print("  🎉 ALL TESTS PASSED - Ready for full implementation!")
    else:
        print("  ⚠️ Some tests failed - Review before proceeding")
    
    return all_passed


if __name__ == "__main__":
    success = asyncio.run(main())
    sys.exit(0 if success else 1)

