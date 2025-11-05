#!/usr/bin/env python3
"""
Test deployed model serving endpoint.

Usage:
    python scripts/test_endpoint.py --endpoint slide-generator-dev
    python scripts/test_endpoint.py --endpoint slide-generator --questions questions.json
"""

import argparse
import json
import os
import sys
from pathlib import Path

import requests


def test_endpoint(endpoint_name: str, questions: list[dict]) -> None:
    """
    Test serving endpoint with sample queries.

    Args:
        endpoint_name: Name of the serving endpoint
        questions: List of question dictionaries to test
    """
    host = os.environ.get("DATABRICKS_HOST")
    token = os.environ.get("DATABRICKS_TOKEN")

    if not host or not token:
        print("❌ ERROR: DATABRICKS_HOST and DATABRICKS_TOKEN must be set")
        sys.exit(1)

    url = f"{host}/serving-endpoints/{endpoint_name}/invocations"

    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

    print(f"\n{'='*60}")
    print(f"🧪 Testing Endpoint: {endpoint_name}")
    print(f"{'='*60}")
    print(f"URL: {url}")
    print(f"Tests: {len(questions)}\n")

    results = {"passed": 0, "failed": 0, "total": len(questions)}

    for i, test_case in enumerate(questions, 1):
        print(f"\n{'='*60}")
        print(f"Test {i}/{len(questions)}: {test_case['question'][:60]}...")
        print(f"{'='*60}")

        # Format for serving endpoint (dataframe_records format)
        payload = {"dataframe_records": [test_case]}

        try:
            response = requests.post(url, headers=headers, json=payload, timeout=180)

            if response.status_code == 200:
                result = response.json()
                predictions = result.get("predictions", [])

                if predictions:
                    pred = predictions[0]

                    if pred.get("error"):
                        print(f"❌ Generation Error: {pred['error']}")
                        results["failed"] += 1
                    else:
                        print(f"✅ Success!")
                        print(f"   Slides: {pred.get('slide_count', 0)}")
                        print(f"   HTML Length: {len(pred.get('html', ''))} chars")
                        print(
                            f"   Execution Time: {pred.get('execution_time_seconds', 0):.2f}s"
                        )
                        if pred.get("trace_url"):
                            print(f"   Trace: {pred['trace_url']}")
                        results["passed"] += 1
                else:
                    print(f"❌ No predictions in response")
                    results["failed"] += 1

            else:
                print(f"❌ Request failed: {response.status_code}")
                print(f"   Response: {response.text[:500]}")
                results["failed"] += 1

        except requests.exceptions.Timeout:
            print("❌ Request timed out (>180s)")
            results["failed"] += 1

        except Exception as e:
            print(f"❌ Exception: {e}")
            results["failed"] += 1

    # Print summary
    print(f"\n{'='*60}")
    print("📊 TEST SUMMARY")
    print(f"{'='*60}")
    print(f"Total Tests: {results['total']}")
    print(f"✅ Passed: {results['passed']}")
    print(f"❌ Failed: {results['failed']}")
    print(f"Success Rate: {results['passed']/results['total']*100:.1f}%")
    print()


def load_questions_from_file(filepath: str) -> list[dict]:
    """
    Load test questions from JSON file.

    Args:
        filepath: Path to JSON file

    Returns:
        List of question dictionaries
    """
    with open(filepath, "r") as f:
        return json.load(f)


def get_default_questions() -> list[dict]:
    """
    Get default test questions.

    Returns:
        List of default test question dictionaries
    """
    return [
        {
            "question": "What were our total sales in Q4 2023?",
            "max_slides": 8,
        },
        {
            "question": "Show me customer churn trends over the last year",
            "max_slides": 10,
        },
        {
            "question": "Which products had the highest revenue growth?",
            "max_slides": 7,
        },
        {
            "question": "Analyze user engagement metrics by region",
            "max_slides": 9,
        },
    ]


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Test deployed model serving endpoint",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Test dev endpoint with default questions
  python scripts/test_endpoint.py --endpoint slide-generator-dev
  
  # Test with custom questions file
  python scripts/test_endpoint.py --endpoint slide-generator --questions tests.json
  
  # Test single question
  python scripts/test_endpoint.py --endpoint slide-generator-dev --question "What were Q4 sales?"
        """,
    )

    parser.add_argument(
        "--endpoint",
        required=True,
        help="Name of the serving endpoint to test",
    )

    parser.add_argument(
        "--questions",
        help="Path to JSON file with test questions",
    )

    parser.add_argument(
        "--question",
        help="Single question to test",
    )

    parser.add_argument(
        "--max-slides",
        type=int,
        default=10,
        help="Maximum slides for single question test (default: 10)",
    )

    args = parser.parse_args()

    try:
        # Load questions
        if args.question:
            # Single question from command line
            questions = [{"question": args.question, "max_slides": args.max_slides}]
        elif args.questions:
            # Load from file
            questions = load_questions_from_file(args.questions)
        else:
            # Use defaults
            questions = get_default_questions()

        # Test endpoint
        test_endpoint(args.endpoint, questions)

    except Exception as e:
        print(f"\n❌ ERROR: {e}", file=sys.stderr)
        import traceback

        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()

