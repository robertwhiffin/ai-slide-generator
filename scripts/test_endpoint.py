"""List available Genie spaces from Databricks.

Used for troubleshooting when the configured Genie space is not found.
Load .env (e.g. DATABRICKS_HOST, DATABRICKS_TOKEN) before running.

Usage:
    source .venv/bin/activate
    python scripts/test_endpoint.py
"""
import os
import sys
from pathlib import Path

# Load .env from project root
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

# Add project root so we can import src
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from src.core.databricks_client import get_databricks_client


def main() -> None:
    if not os.getenv("DATABRICKS_HOST") or not os.getenv("DATABRICKS_TOKEN"):
        print("Set DATABRICKS_HOST and DATABRICKS_TOKEN (e.g. in .env) and try again.")
        sys.exit(1)

    try:
        client = get_databricks_client()
        spaces_data = {}
        response = client.genie.list_spaces(page_size=100)
        if response.spaces:
            for space in response.spaces:
                spaces_data[space.space_id] = (space.title, space.description or "")
        while response.next_page_token:
            response = client.genie.list_spaces(
                page_token=response.next_page_token, page_size=100
            )
            if response.spaces:
                for space in response.spaces:
                    spaces_data[space.space_id] = (space.title, space.description or "")

        if not spaces_data:
            print("No Genie spaces found (or you have no access).")
            return
        print(f"Found {len(spaces_data)} Genie space(s):\n")
        for space_id, (title, desc) in sorted(spaces_data.items(), key=lambda x: x[1][0]):
            print(f"  {space_id}")
            print(f"    title: {title}")
            if desc:
                print(f"    description: {desc}")
            print()
    except Exception as e:
        print(f"Error listing Genie spaces: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
