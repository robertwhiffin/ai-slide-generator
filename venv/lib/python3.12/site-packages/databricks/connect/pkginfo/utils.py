import os
from typing import Optional

from .distribution import Distribution
from .sdist import SDist, UnpackedSDist
from .wheel import Wheel


def get_metadata(path_or_module, metadata_version=None) -> Optional[Distribution]:
    """ Try to create a Distribution 'path_or_module'.

    o 'path_or_module' may be a module object.

    o If a string, 'path_or_module' may point to a sdist file or a whl file.

    o Return None if 'path_or_module' can't be parsed.
    """

    if os.path.isfile(path_or_module):
        try:
            return SDist(path_or_module, metadata_version)
        except (ValueError, IOError):
            pass

        try:
            return UnpackedSDist(path_or_module, metadata_version)
        except (ValueError, IOError):
            pass

        try:
            return Wheel(path_or_module, metadata_version)
        except (ValueError, IOError):
            pass

    if os.path.isdir(path_or_module):
        try:
            return Wheel(path_or_module, metadata_version)
        except (ValueError, IOError):
            pass
