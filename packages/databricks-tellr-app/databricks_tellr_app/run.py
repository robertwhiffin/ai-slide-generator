"""Uvicorn entrypoint for Databricks Apps."""

from __future__ import annotations

import os

import uvicorn


def main() -> None:
    host = os.getenv("HOST", "0.0.0.0")
    port = int(os.getenv("PORT", "8000"))
    workers = int(os.getenv("UVICORN_WORKERS", "4"))
    uvicorn.run("src.api.main:app", host=host, port=port, workers=workers)


if __name__ == "__main__":
    main()
