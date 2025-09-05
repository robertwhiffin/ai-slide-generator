#
# DATABRICKS CONFIDENTIAL & PROPRIETARY
# __________________
#
# Copyright 2020-present Databricks, Inc.
# All Rights Reserved.
#
# NOTICE:  All information contained herein is, and remains the property of Databricks, Inc.
# and its suppliers, if any.  The intellectual and technical concepts contained herein are
# proprietary to Databricks, Inc. and its suppliers and may be covered by U.S. and foreign Patents,
# patents in process, and are protected by trade secret and/or copyright law. Dissemination, use,
# or reproduction of this information is strictly forbidden unless prior written permission is
# obtained from Databricks, Inc.
#
# If you view or obtain a copy of this information and believe Databricks, Inc. may not have
# intended it to be made available, please promptly report it to Databricks Legal Department
# @ legal@databricks.com.
#

import os
from importlib import metadata
from packaging.requirements import Requirement
from packaging.version import Version
from pathlib import Path
from typing import Any, Union

from .auto_dependencies import DiscoveryConfig
from .debug import logger
from .pkginfo import get_metadata


class DatabricksEnv:
    """Public Preview API.

    Specify the Python environment used while executing user-defined functions.
    """
    def __init__(self):
        # NOTE: Include any new state modifying members in the `_as_hashable` method.
        self._dependencies = []
        self._discovery_config = DiscoveryConfig.NONE

    @property
    def dependencies(self) -> list[str]:
        """Return a copy of environment's dependencies."""
        return self._dependencies.copy()

    def withAutoDependencies(self, *, upload_local: bool) -> 'DatabricksEnv':
        """THIS IS AN EXPERIMENTAL FEATURE.

        Configure what kinds of dependencies should be discovered and automatically added to the session's environment.
        The discovery is based on traversing the source code of used UDFs and looking for import statements.

        The possible modes are:
        - upload_local: Discover modules from your project. The source files of the used modules will be uploaded using
          addArtifact so that they can be imported in the UDF environment.

        Behavior in Databricks notebooks and jobs:
        This API is a noop in notebooks and jobs, because the REPL and UDF environments are synchronized automatically
        by Databricks.
        """
        if not os.getenv("DATABRICKS_AUTO_DEPENDENCIES_PRIVATE_PREVIEW"):
            raise NotImplementedError(
                "DatabricksEnv.withAutoDependencies is a Private Preview API and is not widely available yet."
            )

        self._discovery_config = DiscoveryConfig.LOCAL if upload_local else DiscoveryConfig.NONE
        return self

    def withDependencies(self, *dependencies: Union[str, list[str]]) -> 'DatabricksEnv':
        """Add a list of dependencies to the environment.

        Packages are installed in the same order as specified.
        When the same package is specified twice with different versions, the latter wins.

        Currently supported dependency types are:
        1. PyPI packages, specified according to PEP 508, e.g. "numpy" or "simplejson==3.19.*".
        2. UC Volumes files, specified as "dbfs:<path>",
            e.g. "dbfs:/Volumes/users/Alice/wheels/my_private_dep.whl" or
            "dbfs:/Volumes/users/Bob/tars/my_private_deps.tar.gz".
        UC Volumes files must be configured as readable by all account users.

        Behavior in Databricks notebooks and jobs:
        Instead of installing specified dependencies in the current environment, DatabricksEnv
        will check that the current Python environment has all specified dependencies installed.
        If any of the dependencies are missing, a EnvironmentSpecError will be raised.
        See supported ways for installing dependencies in Databricks notebooks and jobs here:
        https://docs.databricks.com/aws/en/libraries/

        Parameters
        ----------
        *dependencies: Union[str, list[str]]
            One or more dependencies, each can be a single string or a list of strings.
        Returns
        -------
        DatabricksEnv
            The same instance of this class with the values configured.
        """
        for dependency in dependencies:
            if isinstance(dependency, str):
                self._dependencies.append(dependency)
            elif isinstance(dependency, list):
                self._dependencies.extend(dependency)
            else:
                raise EnvironmentSpecError("Provided dependencies must be a string or a list of strings.")
        return self

    def _as_hashable(self) -> frozenset[tuple[str, Any]]:
        """Return a simple hashable representation of the environment."""
        dict_repr = {"dependencies": tuple(self.dependencies), "discovery_config": self._discovery_config}
        return frozenset(dict_repr.items())

    def _validate_environment(self):
        """Validate the python environment in Databricks notebooks and jobs.
        Make sure that all specified dependencies are installed."""
        # Convert UC Volumes dependencies to requirement strings
        pep_requirement_strings = [
            self._pep_string_for_uc_volume_dependency(dep)
            if dep.startswith("dbfs:") else dep
            for dep in self.dependencies
        ]
        requirements = [Requirement(dep.lower()) for dep in pep_requirement_strings]
        installed_packages = self._get_installed_packages()
        self._verify_dependencies_are_installed(requirements, installed_packages)

    @staticmethod
    def _get_installed_packages() -> dict[str, Version]:
        return {dist.metadata["name"].lower(): Version(dist.version)
                for dist in metadata.distributions()}

    @staticmethod
    def _pep_string_for_uc_volume_dependency(dep_path: str) -> str:
        dep_path = dep_path.split("dbfs:", 1)[1]
        if not Path(dep_path).exists():
            raise EnvironmentSpecError(f"Cannot access '{dep_path}': No such file or directory.")
        supported_file_formats = [".whl", ".tar.gz", ".tar"]
        if not any(dep_path.endswith(ext) for ext in supported_file_formats):
            raise EnvironmentSpecError(
                f"Unsupported file format '{dep_path}'. "
                f"Only {', '.join(supported_file_formats)} files are supported.")
        dist = get_metadata(dep_path)
        if dist is None or dist.name is None:
            raise EnvironmentSpecError(
                f"Can't extract package name from '{dep_path}'. "
                "Make sure that the package contains a METADATA file (for wheels) or "
                "a .PKG-INFO file (for tarballs).")
        if dist.version is None:
            return dist.name
        else:
            return f"{dist.name}=={dist.version}"

    @staticmethod
    def _verify_dependencies_are_installed(
            requirements: list[Requirement], installed_packages: dict[str, Version]) -> None:
        for req in requirements:
            if req.name not in installed_packages:
                raise EnvironmentSpecError(f"Package {req.name} was not found in the environment.")
            installed_version = installed_packages[req.name]

            if req.specifier.contains(installed_version):
                logger.debug(f"Package {req.name}=={str(installed_version)} is installed "
                             f"in the environment and satisfies requirement {str(req)}.")
            else:
                raise EnvironmentSpecError(f"Package {req.name}=={str(installed_version)} is installed "
                                 f"in the environment but does not satisfy requirement {str(req)}.")
        logger.debug("All dependencies are installed and satisfy the requirements.")


class EnvironmentSpecError(ValueError):
    """
    This error is raised when the DatabricksEnv specification is incorrect or
    when the Python environment in a Databricks notebook or job could not be validated.
    """
