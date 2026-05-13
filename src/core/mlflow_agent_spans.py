"""Policy for MLflow ``start_span`` around slide generation (Genie / agent).

Admin **Direct** judge only skips MLflow for **verification**. The agent still
wrapped ``invoke`` in ``mlflow.start_span`` by default, which uploads trace
artifacts to regional ``*.storage.cloud.databricks.com`` — the same egress many
Apps block. When the workspace judge is **Direct**, we skip those spans unless
overridden (see env vars below).
"""

from __future__ import annotations

import logging
import os

logger = logging.getLogger(__name__)


def mlflow_agent_generate_spans_enabled() -> bool:
    """Return False to skip ``mlflow.set_experiment`` / ``start_span`` around generate paths.

    **Environment (optional)**

    - ``TELLR_MLFLOW_DISABLE_AGENT_SPANS=1`` / ``true`` / ``on``: never emit spans.
    - ``0`` / ``false`` / ``off``: always emit spans (even if Admin judge is Direct).
    - Unset or ``auto`` (default): emit spans only when Admin judge is **not** Direct
      (``llm_judge_backend`` from app settings).
    """
    raw = (os.getenv("TELLR_MLFLOW_DISABLE_AGENT_SPANS") or "").strip().lower()
    if raw in ("1", "true", "yes", "on"):
        logger.debug("MLflow agent spans disabled (TELLR_MLFLOW_DISABLE_AGENT_SPANS=on)")
        return False
    if raw in ("0", "false", "no", "off"):
        return True

    try:
        from src.core.settings_db import get_settings, normalize_llm_judge_backend

        backend = normalize_llm_judge_backend(get_settings().llm_judge_backend)
        if backend == "direct":
            logger.debug(
                "MLflow agent spans skipped (Admin judge=Direct; auto mode). "
                "Set TELLR_MLFLOW_DISABLE_AGENT_SPANS=0 to force spans."
            )
            return False
    except Exception as exc:
        logger.debug("MLflow agent span policy: default enable (%s)", exc)
    return True
