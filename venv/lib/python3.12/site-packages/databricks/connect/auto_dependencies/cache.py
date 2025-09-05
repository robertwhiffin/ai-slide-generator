import copy
import importlib
import importlib.metadata
from collections.abc import Mapping
from typing import Any
from weakref import WeakKeyDictionary

from databricks.connect.auto_dependencies.discovery import DiscoveredDependencies
from databricks.connect.auto_dependencies.tarjan_scc import TarjanScc


class DiscoveryCache:
    """Cache around DiscoveredDependencies.discover_in and DiscoveredDependencies.discover_in_pickled.

    Note that for discover_in_pickled, the results are not cached because we do not expect the same pickled
    representations to appear often. Using a cache for this operation is still beneficial, as the import categorization
    can still reuse the cached map for packages_distributions.
    """

    def __init__(self, packages_distributions: Mapping[str, list[str]] | None = None) -> None:
        self._cache: WeakKeyDictionary[Any, DiscoveredDependencies] = WeakKeyDictionary()
        if packages_distributions is None:
            packages_distributions = importlib.metadata.packages_distributions()
        self._packages_distributions = packages_distributions

    def discover_in_pickled(self, pickled_obj: bytes) -> tuple[Any, DiscoveredDependencies]:
        return DiscoveredDependencies.discover_in_pickled(
            pickled_obj,
            packages_distributions=self._packages_distributions,
        )

    def discover_in(self, obj: Any) -> DiscoveredDependencies:
        # Don't hand out references into the cache
        return copy.deepcopy(self._populate(obj))

    def _populate(self, obj: Any) -> DiscoveredDependencies:
        if obj in self._cache:
            return self._cache[obj]
        deps = DiscoveredDependencies.discover_in(obj, packages_distributions=self._packages_distributions)
        self._cache[obj] = deps
        return deps


class TransitiveDiscoveryCache(DiscoveryCache):
    """Cache that constructs DiscoveredDependencies instances containing transitive dependencies from local modules."""

    def discover_in_pickled(self, pickled_obj: bytes) -> tuple[Any, DiscoveredDependencies]:
        obj, deps = super().discover_in_pickled(pickled_obj)
        for dep in copy.copy(deps.local):
            deps |= self._populate(importlib.import_module(dep))
        return obj, deps

    def _populate(self, obj: Any) -> DiscoveredDependencies:
        if obj in self._cache:
            return self._cache[obj]

        # We can't just construct the union of self._populate(mod) for every imported module mod of obj, because the
        # modules might import each other cyclically. Instead, we calculate the set of dependencies for each SCC of the
        # dependency graph and set the entries of all modules at once.

        # This caches the discovery of newly discovered nodes, because we iterate over the local dependencies
        # multiple times. We can discard this cache after the function returns, because all visited nodes will have
        # an entry in `self._cache` afterwards and thus be skipped below.
        non_transitive_cache = DiscoveryCache(self._packages_distributions)

        def edges(obj):
            if obj in self._cache:
                # This object already has transitive dependencies discovered, so we prune the dependency graph here.
                return

            obj_deps = non_transitive_cache._populate(obj)
            for dep in obj_deps.local:
                yield importlib.import_module(dep)

        sccs = TarjanScc.run(obj, edges)
        for scc in sccs:
            node_from_scc = next(iter(scc.nodes))
            if node_from_scc in self._cache:
                continue

            deps = DiscoveredDependencies()
            for v in scc.nodes:
                # The cache was populated during traversal of the graph
                deps |= non_transitive_cache._cache[v]
            for other_scc in scc.outgoing:
                node_from_other = next(iter(other_scc.nodes))
                # This entry is already populated because the sccs are in reverse topological order
                deps |= self._cache[node_from_other]
            for v in scc.nodes:
                # Notably, all nodes in the SCC reference the same deps object
                self._cache[v] = deps

        return self._cache[obj]
