"""`merge_with_existing` — preserve stable node IDs across re-induction.

Re-induction happens when the corpus grows. We don't want to invalidate
every wiki page, query log entry, and human override every time a chunk
is added. So when the new tree's induced nodes share a label (and
parent-label-path) with an existing tree's nodes, we adopt the existing
tree's ID for the new node.

Rules:

  * Seed nodes are matched on ``id`` directly (they use stable ids like
    ``seed:contract``). If a seed node exists in both trees, the new
    tree's node inherits the existing id verbatim.
  * Induced nodes are matched on ``(label, parent_label_path)``. A
    "parent label path" is the tuple of ancestor labels walking up to the
    root.
  * Labels that don't match anywhere in the existing tree keep the new
    tree's freshly-generated id.

What we DON'T do here:
  * Re-cluster chunk_ids. The new tree already has the right chunks per
    node; we only swap node ids.
  * Edit confidences or centroids. Re-induction is allowed to change those.
"""

from __future__ import annotations

from typing import Optional

from .models import OntologyNode, OntologyTree


def merge_with_existing(
    new_tree: OntologyTree, existing_tree: OntologyTree
) -> OntologyTree:
    """Return a tree shaped like ``new_tree`` but with stable ids preserved.

    Pure function; neither argument is mutated.
    """
    if not existing_tree.nodes:
        return new_tree
    if not new_tree.nodes:
        return new_tree

    # 1. Build the (label_path -> node_id) map for the existing tree.
    existing_paths = _build_label_path_index(existing_tree)
    # 2. Walk the new tree top-down and decide an id for each node:
    #    keep the new id, or rewrite to an existing id.
    new_paths = _build_label_path_index(new_tree)

    # id mapping: new_id -> resolved_id (either kept or existing's id).
    id_map: dict[str, str] = {}
    for path, new_id in new_paths.items():
        existing_id = existing_paths.get(path)
        # Seed nodes always map by their stable id directly. The path-
        # based lookup also catches them (their path is just their label)
        # but we add a belt-and-braces check on the seed-prefix to handle
        # any edge case where labels differ between trees.
        if existing_id is not None:
            id_map[new_id] = existing_id
        elif new_id.startswith("seed:") and new_id in existing_tree.nodes:
            id_map[new_id] = new_id
        else:
            id_map[new_id] = new_id

    # 3. Build a new nodes dict keyed by the resolved ids, with parent_ids
    #    rewritten through the same map.
    rewritten: dict[str, OntologyNode] = {}
    for node in new_tree.nodes.values():
        resolved_id = id_map[node.id]
        resolved_parent = (
            id_map.get(node.parent_id, node.parent_id)
            if node.parent_id is not None
            else None
        )
        rewritten[resolved_id] = node.model_copy(
            update={"id": resolved_id, "parent_id": resolved_parent}
        )

    return OntologyTree(nodes=rewritten)


# ----------------------------------------------------------------------
# Internals
# ----------------------------------------------------------------------


def _build_label_path_index(tree: OntologyTree) -> dict[tuple[str, ...], str]:
    """Map ``(root_label, ..., node_label) -> node_id`` for every node."""
    index: dict[tuple[str, ...], str] = {}
    for nid, node in tree.nodes.items():
        path = _label_path_for(node, tree)
        # If two nodes happen to share a path (shouldn't happen in a
        # well-formed tree, but defensive against duplicate labels in
        # siblings), prefer the first one we saw. Iteration order on
        # Pydantic dict is insertion-stable.
        index.setdefault(path, nid)
    return index


def _label_path_for(node: OntologyNode, tree: OntologyTree) -> tuple[str, ...]:
    path: list[str] = []
    cur: Optional[OntologyNode] = node
    seen: set[str] = set()
    while cur is not None:
        if cur.id in seen:
            # Cycle guard — OntologyTree's validator already prevents this
            # but the walk needs to terminate even on a malformed input.
            break
        seen.add(cur.id)
        path.append(cur.label)
        if cur.parent_id is None:
            break
        cur = tree.nodes.get(cur.parent_id)
    path.reverse()
    return tuple(path)
