from collections.abc import Callable, Hashable, Iterable
from dataclasses import dataclass, field
from typing import Generic, Self, TypeVar

V = TypeVar("V", bound=Hashable)


@dataclass(eq=False)
class Scc(Generic[V]):
    """A strongly connected component of a graph."""

    nodes: set[V] = field(default_factory=set)
    outgoing: set[Self] = field(default_factory=set)


class TarjanScc(Generic[V]):
    """Generic implementation of Tarjan's Strongly Connected Component Algorithm.

    See https://en.wikipedia.org/wiki/Tarjan%27s_strongly_connected_components_algorithm
    """

    def __init__(self, edges: Callable[[V], Iterable[V]]) -> None:
        self.edges = edges

        self.time = 0
        self.discovery: dict[V, int] = {}
        self.early: dict[V, int] = {}
        self.sccs: list[Scc[V]] = []
        self.stack: list[V] = []
        self.stack_set: set[V] = set()

    def _dfs(self, u: V) -> None:
        self.discovery[u] = self.early[u] = self.time
        self.time += 1

        self.stack.append(u)
        self.stack_set.add(u)

        for v in self.edges(u):
            if v not in self.discovery:
                self._dfs(v)
                self.early[u] = min(self.early[u], self.early[v])
            elif v in self.stack_set:
                self.early[u] = min(self.early[u], self.early[v])

        if self.early[u] == self.discovery[u]:
            scc = Scc[V]()
            while (v := self.stack.pop()) != u:
                scc.nodes.add(v)
                self.stack_set.remove(v)
            scc.nodes.add(u)
            self.stack_set.remove(u)

            self.sccs.append(scc)

    def _set_outgoing(self) -> None:
        scc_of = {v: scc for scc in self.sccs for v in scc.nodes}
        for scc in self.sccs:
            for u in scc.nodes:
                for v in self.edges(u):
                    if scc_of[v] != scc:
                        scc.outgoing.add(scc_of[v])

    @classmethod
    def run(cls, start: V, edges: Callable[[V], Iterable[V]]) -> list[Scc[V]]:
        """Run the algorithm.

        Returns the list of SCCs reachable from `start`. The SCCs in the output are in reverse topological order, that
        is, no component comes before any of the other components reachable from it.
        """
        state = cls(edges)
        state._dfs(start)
        state._set_outgoing()
        return state.sccs
