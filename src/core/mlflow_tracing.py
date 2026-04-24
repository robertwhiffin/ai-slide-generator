"""Unity Catalog-backed MLflow tracing (Databricks MLflow 3.11+).

See: https://docs.databricks.com/aws/en/mlflow3/genai/tracing/trace-unity-catalog

When ``TELLR_MLFLOW_UC_CATALOG``, ``TELLR_MLFLOW_UC_SCHEMA``, and
``TELLR_MLFLOW_UC_TABLE_PREFIX`` are set, new experiments are created with
``trace_location=UnityCatalog(...)`` so traces are stored in UC Delta tables
instead of default control-plane artifact paths (avoiding egress issues from
Databricks Apps in some setups).

``MLFLOW_TRACING_SQL_WAREHOUSE_ID`` should be set for the MLflow UI to query
UC trace tables (and for monitoring jobs).
"""

from __future__ import annotations

import logging
import os
from typing import Any, Optional

logger = logging.getLogger(__name__)

# Lazy cache for UnityCatalog class (mlflow >= 3.11)
_unity_catalog_cls: Any = None


def _get_unity_catalog_class() -> Any | None:
    global _unity_catalog_cls
    if _unity_catalog_cls is False:
        return None
    if _unity_catalog_cls is not None:
        return _unity_catalog_cls
    try:
        from mlflow.entities.trace_location import UnityCatalog as UC

        _unity_catalog_cls = UC
        return UC
    except ImportError as e:
        mlflow_ver = "not installed"
        try:
            import mlflow as _mf

            mlflow_ver = getattr(_mf, "__version__", "?")
        except ImportError:
            pass
        logger.warning(
            "UnityCatalog trace location requires mlflow>=3.11 with "
            "mlflow.entities.trace_location.UnityCatalog "
            "(installed mlflow.__version__=%s): %s",
            mlflow_ver,
            e,
        )
        _unity_catalog_cls = False
        return None


def configure_tracing_environment() -> None:
    """Apply tracing-related env aliases and validate UC + warehouse hints.

    Sets ``MLFLOW_TRACING_SQL_WAREHOUSE_ID`` from ``TELLR_MLFLOW_SQL_WAREHOUSE_ID``
    when the former is unset (optional alias for app.yaml brevity).
    """
    if not os.environ.get("MLFLOW_TRACING_SQL_WAREHOUSE_ID"):
        alt = (os.environ.get("TELLR_MLFLOW_SQL_WAREHOUSE_ID") or "").strip()
        if alt:
            os.environ["MLFLOW_TRACING_SQL_WAREHOUSE_ID"] = alt

    catalog = (os.environ.get("TELLR_MLFLOW_UC_CATALOG") or "").strip()
    schema = (os.environ.get("TELLR_MLFLOW_UC_SCHEMA") or "").strip()
    prefix = (os.environ.get("TELLR_MLFLOW_UC_TABLE_PREFIX") or "").strip()
    if catalog and schema and prefix:
        wh = (os.environ.get("MLFLOW_TRACING_SQL_WAREHOUSE_ID") or "").strip()
        if not wh:
            logger.warning(
                "TELLR_MLFLOW_UC_* is set but MLFLOW_TRACING_SQL_WAREHOUSE_ID "
                "(or TELLR_MLFLOW_SQL_WAREHOUSE_ID) is empty; MLflow UI may not "
                "load UC-backed traces until a SQL warehouse ID is configured."
            )


def get_unity_catalog_trace_location() -> Optional[Any]:
    """Return ``UnityCatalog`` instance if UC tracing env is fully set, else None."""
    UC = _get_unity_catalog_class()
    if UC is None:
        return None

    catalog = (os.environ.get("TELLR_MLFLOW_UC_CATALOG") or "").strip()
    schema = (os.environ.get("TELLR_MLFLOW_UC_SCHEMA") or "").strip()
    prefix = (os.environ.get("TELLR_MLFLOW_UC_TABLE_PREFIX") or "").strip()
    if not (catalog and schema and prefix):
        return None

    return UC(catalog_name=catalog, schema_name=schema, table_prefix=prefix)


def _is_uc_trace_backend_unavailable_error(exc: BaseException) -> bool:
    """True if the workspace cannot link UC trace location (OTel collector off / unsupported)."""
    msg = str(exc).lower()
    if "endpoint_not_found" in msg and "opentelemetry" in msg:
        return True
    if "opentelemetry collector" in msg:
        return True
    if "linking to trace location" in msg and "failed" in msg:
        return True
    return False


def create_databricks_experiment(experiment_name: str) -> str:
    """Create a Databricks tracking experiment, optionally with UC trace tables.

    Existing experiments keep their original trace binding; only **new**
    experiments pick up UC (Databricks does not allow rebinding trace location).

    Args:
        experiment_name: Workspace path name for the experiment.

    Returns:
        Experiment ID string from ``mlflow.create_experiment``.
    """
    import mlflow

    configure_tracing_environment()
    uc = get_unity_catalog_trace_location()
    if uc is None:
        return mlflow.create_experiment(experiment_name)

    logger.info(
        "Creating MLflow experiment with Unity Catalog traces: catalog=%s schema=%s prefix=%s",
        getattr(uc, "catalog_name", None),
        getattr(uc, "schema_name", None),
        getattr(uc, "table_prefix", None),
    )
    try:
        return mlflow.create_experiment(name=experiment_name, trace_location=uc)
    except Exception as e:
        if not _is_uc_trace_backend_unavailable_error(e):
            raise
        logger.warning(
            "Unity Catalog trace location is not available in this workspace (OpenTelemetry "
            "Collector / UC trace linking). Using a standard MLflow experiment without UC "
            "trace tables. Contact Databricks support to enable OpenTelemetry for MLflow traces "
            "if you need UC-backed storage. Error was: %s",
            e,
        )
        # create_experiment may have registered the experiment before linking failed
        existing = mlflow.get_experiment_by_name(experiment_name)
        if existing is not None:
            logger.info(
                "Reusing experiment %s created without successful UC trace binding.",
                existing.experiment_id,
            )
            return existing.experiment_id
        return mlflow.create_experiment(experiment_name)
