"""A directed graph whose edge costs are explicit travel times in seconds.

The scenario adapter converts verified metres and metres/second to seconds.
This generic graph stores costs only; it does not inspect scenarios or evidence.
"""
from dataclasses import dataclass
from math import isfinite


@dataclass(frozen=True)
class Edge:
    """An outgoing arc: road identity, destination node, and fixed travel seconds.

    The source is implicit in the adjacency list holding this edge. Keeping road_id
    lets routes distinguish parallel roads with the same pair of endpoints.

    Parameters:
        road_id: String identifying the selected road in a Route.
        target: Destination node ID; departure is implicit in the containing adjacency
            list.
        seconds: Fixed nonnegative finite travel duration in seconds.

    Preconditions:
        Direct construction must supply suitable values; the generated dataclass
        constructor does not validate them. Graph.add_edge validates records inserted
        through its API.

    Postconditions:
        Creates a frozen record storing the supplied values. This alone does not add an
        arc to a graph.
    """
    road_id: str
    target: str
    seconds: float


class Graph:
    """A directed adjacency-list graph consumed by uniform-cost search.

    Nodes with no outgoing edges remain present. Parallel edges and zero-cost arcs
    are allowed. Edge costs must be finite and nonnegative; search assumes that the
    graph and its costs are not modified during a call.

    Parameters:
        nodes: Finite iterable of unique nonempty node IDs; see __init__ for checked
            conditions.

    Preconditions:
        See __init__ for construction requirements; later graph operations must
        preserve its adjacency lists.

    Postconditions:
        After successful construction, every supplied node exists with no arcs.
        Mutations occur only through add_edge in the supported API.
    """
    def __init__(self, nodes):
        """Create empty outgoing-edge lists for unique nonempty string node IDs.

        nodes may be any iterable, including a generator. Invalid or duplicate IDs raise
        ValueError rather than silently collapsing two input records into one node.

        Parameters:
            self: The Graph instance receiving the call; passed automatically by Python.
            nodes: Finite iterable of unique, nonempty string node IDs; may be empty or a
                generator.

        Preconditions:
            nodes must be iterable. Unique nonempty string IDs are checked; invalid IDs
            raise ValueError.

        Postconditions:
            The graph contains exactly the supplied IDs, each with no outgoing edges. The
            iterable has been consumed.
        """
        nodes = tuple(nodes)
        if any(not isinstance(n, str) or not n for n in nodes):
            raise ValueError("Node IDs must be nonempty strings")
        if len(set(nodes)) != len(nodes):
            raise ValueError("Duplicate node IDs")
        # Each key is a source node; its list contains only outgoing arcs.
        self._adj = {node: [] for node in nodes}

    def __contains__(self, node):
        """Return whether a node exists, including nodes with no outgoing roads.

        Parameters:
            self: The Graph instance receiving the call; passed automatically by Python.
            node: Hashable lookup value, normally a string node ID; used by 'node in
                graph'.

        Preconditions:
            The receiver is an initialized Graph; node must be hashable (caller
            assumption).

        Postconditions:
            Returns a bool indicating node membership. No graph state changes.
        """
        return node in self._adj

    def add_edge(self, source, target, seconds, road_id):
        """Add one directed arc with a fixed travel duration in seconds.

        Both endpoints must already exist. The reverse arc is not added automatically.
        Raise ValueError for unknown endpoints, negative/nonfinite/nonnumeric costs,
        boolean costs, or an empty road ID. Python treats bool as numeric, so reject it
        explicitly. Duplicate endpoints are allowed for callers with parallel roads.

        Parameters:
            self: The Graph instance receiving the call; passed automatically by Python.
            source: ID of the existing departure node.
            target: ID of the existing arrival node.
            seconds: Finite nonnegative int/float travel duration in seconds; bool is
                rejected.
            road_id: Nonempty string identifying the arc in returned routes; uniqueness is
                caller-managed.

        Preconditions:
            Endpoints must be existing hashable node IDs. Membership, numeric cost
            constraints and road_id are checked; violations raise ValueError. Road-ID
            uniqueness is not checked.

        Postconditions:
            Exactly one outgoing Edge is appended at source, storing float(seconds). All
            other lists and node IDs are unchanged. No reverse edge is added. Checked
            validation failures occur before any edge is appended.
        """
        if source not in self or target not in self:
            raise ValueError("Edge endpoint is not in graph")
        if isinstance(seconds, bool) or not isinstance(seconds, (int, float)):
            raise ValueError("Travel time must be numeric")
        if not isfinite(seconds) or seconds < 0:
            raise ValueError("Travel time must be finite and nonnegative")
        if not isinstance(road_id, str) or not road_id:
            raise ValueError("Road ID must be a nonempty string")
        self._adj[source].append(Edge(road_id, target, float(seconds)))

    def neighbors(self, node):
        """Return an immutable tuple of the node's outgoing Edge records.

        The tuple prevents callers from changing the internal edge list accidentally.
        Unknown nodes raise KeyError; UCS checks its requested endpoints beforehand.

        Parameters:
            self: The Graph instance receiving the call; passed automatically by Python.
            node: Existing source node ID whose outgoing arcs are requested.

        Preconditions:
            node must be hashable and present in the graph; an absent node raises KeyError.

        Postconditions:
            Returns a tuple of outgoing Edge records in insertion order, possibly empty.
            Graph state is unchanged; editing the tuple cannot edit the adjacency list.
        """
        return tuple(self._adj[node])
