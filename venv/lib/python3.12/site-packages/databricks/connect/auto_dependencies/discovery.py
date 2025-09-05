import ast
import importlib.metadata
import importlib.util
import inspect
import io
import logging
import pickle
import sys
import textwrap
from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass, field
from importlib.machinery import ModuleSpec
from importlib.metadata import Distribution
from typing import Any, Mapping, Self

logger = logging.getLogger(__name__)


class TrackingUnpickler(pickle.Unpickler):
    """An Unpickler that keeps track of the modules required during unpickling."""

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._required_modules: set[str] = set()

    def find_class(self, module, name):
        self._required_modules.add(module)
        return super().find_class(module, name)

    @classmethod
    def loads(cls, pickled_obj: bytes) -> tuple[Any, set[str]]:
        unpickler = cls(io.BytesIO(pickled_obj))
        obj = unpickler.load()
        return obj, unpickler._required_modules


class DiscoveryError(Exception):
    """An error that occurred as part of the auto-dependency discovery step."""


class AmbiguousName(DiscoveryError):
    def __init__(self, ident: str, options: set[str]) -> None:
        super().__init__(
            f'The identifier "{ident}" could not be uniquely resolved to a module, the following options were found: {options}'
        )


class DependencyDiscoveryVisitor(ast.NodeVisitor):
    def __init__(self, current_package: str | None) -> None:
        self.current_package = current_package
        self.origin_module: dict[str, set[str]] = defaultdict(set)
        self.seen_idents: set[str] = set()
        self.attribute_stack: list[str] = []

    def visit_Name(self, node: ast.Name) -> None:
        ident = node.id
        for attr in self.attribute_stack[::-1]:
            ident += "."
            ident += attr
        self.seen_idents.add(ident)
        self.generic_visit(node)

    def visit_Attribute(self, node: ast.Attribute) -> None:
        self.attribute_stack.append(node.attr)
        self.generic_visit(node)
        self.attribute_stack.pop()

    def visit_Import(self, node: ast.Import) -> None:
        for alias in node.names:
            asname = alias.asname if alias.asname is not None else alias.name
            self.origin_module[asname].add(alias.name)
            self.seen_idents.add(asname)
        self.generic_visit(node)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        module_path = importlib.util.resolve_name("." * node.level + node.module, self.current_package)
        for alias in node.names:
            submodule_path = f"{module_path}.{alias.name}"
            try:
                spec = importlib.util.find_spec(submodule_path)
            except ModuleNotFoundError:
                spec = None
            asname = alias.asname if alias.asname is not None else alias.name
            if spec is not None:
                assert spec.name == submodule_path
                self.origin_module[asname].add(submodule_path)
            else:
                # The alias is not a submodule
                self.origin_module[asname].add(module_path)
            self.seen_idents.add(asname)
        self.generic_visit(node)

    def visit_If(self, node: ast.If) -> None:
        match node.test:
            case ast.Name("TYPE_CHECKING") | ast.Attribute(ast.Name("typing"), "TYPE_CHECKING"):
                # Avoid traversing imports guarded by `if TYPE_CHECKING`, and only traverse the else-branch
                for child_node in node.orelse:
                    self.visit(child_node)
            case _:
                self.generic_visit(node)


@dataclass
class DiscoveredDependencies:
    local: dict[str, ModuleSpec] = field(default_factory=dict)
    index: dict[str, Distribution] = field(default_factory=dict)
    direct_url: dict[str, Distribution] = field(default_factory=dict)
    unknown: set[str] = field(default_factory=set)

    IGNORE_TOP_LEVEL_MODULES = [
        "databricks",  # because we don't want to change the default version of connect, sdk, etc. on the server
        "pyspark",  # because pyspark provides the udf decorator
    ]

    def __ior__(self, other: Self) -> Self:
        self.local |= other.local
        self.index |= other.index
        self.direct_url |= other.direct_url
        self.unknown |= other.unknown
        return self

    @classmethod
    def discover_in_pickled(
        cls,
        pickled_obj: bytes,
        *,
        packages_distributions: Mapping[str, list[str]] | None,
    ) -> tuple[Any, Self]:
        """Unpickle the object and return it and the dependencies required for unpickling."""

        if packages_distributions is None:
            packages_distributions = importlib.metadata.packages_distributions()

        obj, references = TrackingUnpickler.loads(pickled_obj)
        deps = cls()
        for reference in references:
            deps._categorize_name(reference, packages_distributions=packages_distributions)
        logger.debug("References from unpickling %s: %s -> %s", repr(obj), repr(references), str(deps))
        return obj, deps

    @classmethod
    def discover_in(
        cls,
        obj: Any,
        *,
        packages_distributions: Mapping[str, list[str]] | None = None,
    ) -> Self:
        """Scan the source code of obj and return the dependencies found."""

        if packages_distributions is None:
            packages_distributions = importlib.metadata.packages_distributions()

        try:
            source = textwrap.dedent(inspect.getsource(obj))
        except OSError:
            # There is a bug when getting the source of empty files, which is fixed in Python 3.13
            # https://github.com/python/cpython/commit/52ef4430a9b3e212fe9200675cddede77b90785b
            # However, empty files don't contain any imports, so we can ignore them.
            source = ""
        module = inspect.getmodule(obj)
        package = module.__spec__.parent if module is not None and module.__spec__ is not None else None

        fallback_source = None
        if not inspect.ismodule(obj) and module is not None:
            try:
                fallback_source = inspect.getsource(module)
            except OSError:
                pass  # See above

        deps = cls()
        deps._scan_source(source, package, fallback_source, packages_distributions)
        return deps

    @staticmethod
    def _resolve_ident(ident: str, visitors: Iterable[DependencyDiscoveryVisitor]) -> str | None:
        for visitor in visitors:
            modules = visitor.origin_module.get(ident, None)
            if modules is None:
                continue
            if len(modules) > 1:
                raise AmbiguousName(ident, modules)
            return next(iter(modules))
        return None

    def _categorize_name(self, name: str, packages_distributions: Mapping[str, list[str]]) -> None:
        top_level_module_name = name.split(".")[0]
        if top_level_module_name in sys.stdlib_module_names:
            logger.info("Ignoring import of stdlib module: %s", name)
            return
        if top_level_module_name in self.IGNORE_TOP_LEVEL_MODULES:
            logger.debug("Ignoring import of databricks module: %s", name)
            return

        if top_level_module_name in packages_distributions:
            for distribution_name in packages_distributions[top_level_module_name]:
                if distribution_name in self.index or distribution_name in self.direct_url:
                    return
                logger.debug("Discovered distribution: %s for module %s", distribution_name, top_level_module_name)
                distribution = importlib.metadata.distribution(distribution_name)

                # Note: In Python 3.13, change this to use distribution.metadata.origin
                if distribution.read_text("direct_url.json") is None:
                    self.index[distribution_name] = distribution
                else:
                    self.direct_url[distribution_name] = distribution
        else:
            if name in self.local or name in self.unknown:
                return

            spec = importlib.util.find_spec(name)
            if spec is None:
                self.unknown.add(name)
                return

            logger.debug("Discovered local module: %s", name)
            self.local[name] = spec

    def _scan_source(
        self,
        source: str,
        current_package: str | None,
        fallback_source: str | None,
        packages_distributions: Mapping[str, list[str]],
    ) -> None:
        """Scans the source code for import and from-import statements and adds the found modules to one of self's
        fields, depending on what kind of module is being imported.

        To resolve relative imports, the current package should be specified as required by importlib.util.resolve_name.
        Additionally, the source code of an enclosing module can be given as fallback_source. This source will also be
        scanned and the imports there are used to as a fallback if an identifier from the original source does not match
        an import.
        """
        main_visitor = DependencyDiscoveryVisitor(current_package)
        main_visitor.visit(ast.parse(source))

        fallback_visitor = DependencyDiscoveryVisitor(current_package)
        if fallback_source is not None:
            fallback_visitor.visit(ast.parse(fallback_source))

        for ident in main_visitor.seen_idents:
            # Try all prefixes to catch accesses like module.submodule.item and module.submodule.item.attribute_of_item
            while ident:
                module_name = self._resolve_ident(ident, [main_visitor, fallback_visitor])
                if module_name is not None:
                    self._categorize_name(module_name, packages_distributions)
                    break
                ident, _, _ = ident.rpartition(".")
