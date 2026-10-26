"""One-time data migrations that have completed on this database.

``_run_migrations`` (``src/core/database.py``) runs on every boot. A schema change
can tell from the live schema whether it has already happened, but a data rewrite
cannot always: proving that nothing is left to rewrite means scanning the data it
targets. A row here records that the migration *name* finished, in the same
transaction as its writes, so later boots skip it with one indexed lookup.

A fork of a database inherits its rows, so a fork of an already-migrated database
skips the migration too.
"""

from sqlalchemy import Column, DateTime, String

from src.core.database import Base


class DataMigration(Base):
    """A completed one-time data migration, keyed by its name."""

    __tablename__ = "data_migrations"

    name = Column(String(128), primary_key=True)
    # No Python-side default: the one writer (_record_data_migration) supplies
    # CURRENT_TIMESTAMP in its raw SQL.
    applied_at = Column(DateTime, nullable=False)
