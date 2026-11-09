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


#: Let users generate and edit images with AI. On by default; an admin can turn it off (and the
#: deployment can opt out with TELLR_IMAGE_GENERATION_ENABLED=0).
IMAGE_GENERATION_KEY: Final = "image_generation_enabled"
_OFF_VALUES: Final = (False, 0, "0", "false", "no", "off")


def image_generation_enabled(db: Session) -> bool:
    row = db.get(WorkspaceSetting, IMAGE_GENERATION_KEY)
    if row is None:
        return True
    value = row.value.strip().lower() if isinstance(row.value, str) else row.value
    return not any(value is off or (type(value) is type(off) and value == off) for off in _OFF_VALUES)


def set_image_generation_enabled(db: Session, *, enabled: bool, user: str) -> bool:
    row = db.get(WorkspaceSetting, IMAGE_GENERATION_KEY)
    if row is None:
        row = WorkspaceSetting(key=IMAGE_GENERATION_KEY)
        db.add(row)
    row.value = enabled
    row.updated_by = user
    db.commit()
    return image_generation_enabled(db)
