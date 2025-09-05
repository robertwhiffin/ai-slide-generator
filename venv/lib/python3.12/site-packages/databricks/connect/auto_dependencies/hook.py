import logging
import tempfile
from collections import defaultdict
from collections.abc import Iterable
from enum import auto, Flag
from importlib.machinery import ModuleSpec
from io import BytesIO
from pathlib import Path
from typing import Any, TypeVar
from zipfile import ZipFile

import pyspark.sql.connect.proto as pb2
from databricks.connect.auto_dependencies.cache import TransitiveDiscoveryCache
from databricks.connect.auto_dependencies.discovery import DiscoveredDependencies
from google.protobuf.message import Message
from pyspark import cloudpickle
from pyspark.sql.connect.session import SparkSession


class DiscoveryConfig(Flag):
    NONE = 0
    LOCAL = auto()


T = TypeVar("T")

logger = logging.getLogger(__name__)


def find_all_instances(m: Any, ty: tuple[type[T], ...]) -> Iterable[T]:
    if isinstance(m, ty):
        yield m

    if not isinstance(m, Message):
        return

    for desc, value in m.ListFields():
        if desc.label == desc.LABEL_REPEATED:
            for item in value:
                yield from find_all_instances(item, ty)
        else:
            yield from find_all_instances(value, ty)


class DependencyArtifactManager:
    """Manages session artifacts for a set of module specs.

    The module files are uploaded as a zip archive. When new modules are added, an updated zip file can be uploaded, so
    that it takes precedence over the old one. Notably, the file contents are kept in memory but written to disk when
    uploading, because we need a file system path for uploading, but don't want to keep temporary files around for the
    entire duration of the session (this would also make cleanup more difficult).
    """

    def __init__(self, session: SparkSession, prefix: str) -> None:
        self.session = session
        self.prefix = prefix
        self.needs_sync = False
        self.written_paths = {"."}
        self.io = BytesIO()

    def add_specs(self, module_specs: Iterable[ModuleSpec]) -> None:
        with ZipFile(self.io, mode="a") as zip_file:
            for spec in module_specs:
                if not spec.has_location or spec.origin is None:
                    # This happens for example when the module is a namespace package
                    continue
                package_path = spec.parent or ""
                path = Path(*package_path.split("."), Path(spec.origin).name)
                for directory in path.parents:
                    if directory.as_posix() not in self.written_paths:
                        zip_file.mkdir(directory.as_posix())
                        self.written_paths.add(directory.as_posix())
                        self.needs_sync = True
                if path.as_posix() not in self.written_paths:
                    zip_file.write(spec.origin, arcname=path.as_posix())
                    self.written_paths.add(path.as_posix())
                    self.needs_sync = True
            logger.debug("Manager %s: File list after merge: %s", self.prefix, repr(sorted(zip_file.namelist())))
        self.io.seek(0)

    def sync(self) -> None:
        # As per the documentation of NamedTemporaryFile, we disable delete_on_close because we open the file again by
        # name in addArtifacts, which could make trouble on Windows.
        with tempfile.NamedTemporaryFile(prefix=self.prefix, suffix=".zip", mode="w+b", delete_on_close=False) as file:
            file.write(self.io.getbuffer())
            file.flush()
            # We construct a proper URI, as Windows file paths like C:\... would otherwise be interpreted as a URI using
            # the "C" scheme, although we know that the file:/ scheme is the one we want to use here.
            file_uri = Path(file.name).resolve().as_uri()
            self.session.addArtifacts(file_uri, pyfile=True)
        self.needs_sync = False


class AutoDependenciesHook(SparkSession.Hook):
    def __init__(self, session: SparkSession, config: DiscoveryConfig) -> None:
        self.session = session
        self.config = config
        self.discovery_cache = TransitiveDiscoveryCache()
        self.artifact_managers: dict[str, DependencyArtifactManager] = {}

    def on_execute_plan(self, request: pb2.ExecutePlanRequest) -> pb2.ExecutePlanRequest:
        udfs: list[pb2.PythonUDF | pb2.PythonUDTF] = list(
            find_all_instances(request.plan, (pb2.PythonUDF, pb2.PythonUDTF))
        )
        deps = DiscoveredDependencies()
        for udf in udfs:
            obj, pickle_deps = self.discovery_cache.discover_in_pickled(udf.command)
            if isinstance(udf, pb2.PythonUDF):
                # command is a tuple (func, output_type)
                obj = obj[0]
            deps |= pickle_deps  # object references that get resolved while unpickling
            deps |= self.discovery_cache.discover_in(obj)  # dependencies required when executing the UDF

        if DiscoveryConfig.LOCAL in self.config:
            if deps.local:
                specs_by_top_level_module = defaultdict(list)
                for module_name, spec in deps.local.items():
                    top_level_module = module_name.partition(".")[0]
                    specs_by_top_level_module[top_level_module].append(spec)
                for top_level_module, specs in specs_by_top_level_module.items():
                    manager = self.artifact_managers.setdefault(
                        top_level_module,
                        DependencyArtifactManager(self.session, f"udf-dependency-{top_level_module}"),
                    )
                    manager.add_specs(specs)
                    if manager.needs_sync:
                        manager.sync()
                        logger.info("Synced zip artifact for: %s", top_level_module)

            if deps.direct_url:
                logger.info("Upload of direct url packages is not implemented yet: %s", repr(list(deps.direct_url)))

        if deps.unknown:
            logger.info("The source for the following modules could not be determined: %s", repr(list(deps.unknown)))

        return request
