#!/usr/bin/env python3
"""
Test 4: Run all tests

This test runs all integration tests in sequence:
1. Test 1: Send prompt to LLM and generate HTML output
2. Test 2: Visualize HTML output in browser
3. Test 3: HTML to PPTX conversion (placeholder)

Provides a comprehensive integration test suite.
"""

import sys
import subprocess
from pathlib import Path


def run_test(test_name, test_script):
    """Run a single test script and return success status"""
    print(f"\n{'='*60}")
    print(f"🧪 Running {test_name}")
    print(f"{'='*60}")
    
    try:
        # Run the test script
        result = subprocess.run([sys.executable, test_script], 
                              capture_output=True, 
                              text=True, 
                              cwd=test_script.parent)
        
        # Print the output
        if result.stdout:
            print(result.stdout)
        if result.stderr:
            print("STDERR:", result.stderr)
        
        # Check if test passed
        if result.returncode == 0:
            print(f"✅ {test_name} PASSED")
            return True
        else:
            print(f"❌ {test_name} FAILED (exit code: {result.returncode})")
            return False
            
    except Exception as e:
        print(f"❌ {test_name} FAILED with exception: {e}")
        return False


def test_run_all_tests():
    """Run all integration tests in sequence"""
    
    print("🚀 Starting Integration Test Suite")
    print("🎯 Testing EY Parthenon slide generation end-to-end")
    
    test_dir = Path(__file__).parent
    
    # Define all tests to run
    tests = [
        ("Test 1: LLM HTML Generation", test_dir / "test_1_llm_html_generation.py"),
        ("Test 2: HTML Visualization", test_dir / "test_2_visualize_html.py"),
        ("Test 3: HTML to PPTX Conversion", test_dir / "test_3_html_to_pptx.py"),
    ]
    
    # Track results
    results = {}
    
    # Run each test
    for test_name, test_script in tests:
        if not test_script.exists():
            print(f"❌ {test_name} FAILED: Script not found at {test_script}")
            results[test_name] = False
            continue
        
        success = run_test(test_name, test_script)
        results[test_name] = success
    
    # Print summary
    print(f"\n{'='*60}")
    print("📊 TEST SUITE SUMMARY")
    print(f"{'='*60}")
    
    total_tests = len(results)
    passed_tests = sum(results.values())
    failed_tests = total_tests - passed_tests
    
    for test_name, success in results.items():
        status = "✅ PASSED" if success else "❌ FAILED"
        print(f"  {test_name}: {status}")
    
    print(f"\nResults: {passed_tests}/{total_tests} tests passed")
    
    if failed_tests == 0:
        print("🎉 ALL TESTS PASSED!")
        print("\n📋 What was tested:")
        print("  ✅ LLM integration with Databricks endpoint")
        print("  ✅ HTML slide generation with EY Parthenon theme")
        print("  ✅ Tool execution (UC tools, Genie space, visualizations)")
        print("  ✅ HTML output visualization")
        print("  ✅ PPTX conversion placeholder structure")
        
        # Check output files
        output_dir = test_dir / "output"
        if output_dir.exists():
            output_files = list(output_dir.glob("*"))
            print(f"\n📁 Generated {len(output_files)} output files:")
            for file in output_files:
                size = file.stat().st_size if file.is_file() else "dir"
                print(f"    {file.name} ({size} bytes)")
        
        return True
    else:
        print(f"❌ {failed_tests} tests failed")
        print("\n🔧 Troubleshooting:")
        print("  - Check Databricks credentials are configured")
        print("  - Verify LLM endpoint is accessible")
        print("  - Ensure all dependencies are installed")
        print("  - Run individual tests for detailed error messages")
        return False


if __name__ == "__main__":
    success = test_run_all_tests()
    sys.exit(0 if success else 1)