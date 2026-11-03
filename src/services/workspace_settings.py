"""Workspace-wide admin settings, stored in ``workspace_settings``."""

from __future__ import annotations

from typing import Final

from sqlalchemy.orm import Session

from src.database.models.workspace_setting import WorkspaceSetting

#: Add the Genie One tool to every new deck. Off until an admin turns it on.
GENIE_ONE_DEFAULT_KEY: Final = "genie_one_default"


def genie_one_default(db: Session) -> bool:
    row = db.get(WorkspaceSetting, GENIE_ONE_DEFAULT_KEY)
    return row is not None and row.value is True


def set_genie_one_default(db: Session, *, enabled: bool, user: str) -> bool:
    row = db.get(WorkspaceSetting, GENIE_ONE_DEFAULT_KEY)
    if row is None:
        row = WorkspaceSetting(key=GENIE_ONE_DEFAULT_KEY)
        db.add(row)
    row.value = enabled
    row.updated_by = user
    db.commit()
    return genie_one_default(db)
