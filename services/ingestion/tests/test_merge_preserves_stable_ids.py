"""Tests for `merge_with_existing` — stable IDs across re-induction."""

from __future__ import annotations

from versawiki_ingestion.embedding.base import EMBEDDING_DIM
from versawiki_ingestion.ontology import OntologyNode, OntologyTree, merge_with_existing


def _node(
    nid: str,
    label: str,
    *,
    parent_id: str | None = None,
    kind: str = "induced",
    chunk_ids: list[str] | None = None,
) -> OntologyNode:
    return OntologyNode(
        id=nid,
        parent_id=parent_id,
        label=label,
        kind=kind,  # type: ignore[arg-type]
        chunk_ids=chunk_ids or [],
        centroid_embedding=[],
        confidence=1.0,
    )


def _tree(*nodes: OntologyNode) -> OntologyTree:
    return OntologyTree(nodes={n.id: n for n in nodes})


def test_merge_preserves_id_for_unchanged_label():
    existing = _tree(
        _node("seed:contract", "Contract", kind="seed"),
        _node(
            "ind:topic:abc123",
            "amendment_clause",
            parent_id="seed:contract",
        ),
    )
    # The new tree was built fresh; it gave the same logical node a new id.
    new = _tree(
        _node("seed:contract", "Contract", kind="seed"),
        _node(
            "ind:topic:xyz789",
            "amendment_clause",
            parent_id="seed:contract",
            chunk_ids=["new-chunk-1"],
        ),
    )
    merged = merge_with_existing(new, existing)
    # The amendment_clause node should keep the *existing* id, not the new one.
    assert "ind:topic:abc123" in merged.nodes
    assert "ind:topic:xyz789" not in merged.nodes
    # And the chunk_ids from the new tree must be preserved.
    assert merged.nodes["ind:topic:abc123"].chunk_ids == ["new-chunk-1"]


def test_merge_keeps_new_id_for_novel_label():
    existing = _tree(
        _node("seed:contract", "Contract", kind="seed"),
    )
    new = _tree(
        _node("seed:contract", "Contract", kind="seed"),
        _node(
            "ind:topic:fresh1",
            "completely_new_topic",
            parent_id="seed:contract",
            chunk_ids=["chunk-1"],
        ),
    )
    merged = merge_with_existing(new, existing)
    # No match in existing -> the new id stays.
    assert "ind:topic:fresh1" in merged.nodes
    assert merged.nodes["ind:topic:fresh1"].label == "completely_new_topic"


def test_merge_rewrites_parent_id_through_id_map():
    """When a parent's id changes, its children's parent_id must follow."""
    existing = _tree(
        _node("ind:root:stable1", "engineering"),
        _node(
            "ind:topic:stable2",
            "civil",
            parent_id="ind:root:stable1",
        ),
    )
    # Same labels, fresh ids on the new tree.
    new = _tree(
        _node("ind:root:fresh1", "engineering"),
        _node(
            "ind:topic:fresh2",
            "civil",
            parent_id="ind:root:fresh1",
        ),
    )
    merged = merge_with_existing(new, existing)
    assert "ind:root:stable1" in merged.nodes
    assert "ind:topic:stable2" in merged.nodes
    # The child's parent_id must point to the stable id, not the fresh one.
    assert merged.nodes["ind:topic:stable2"].parent_id == "ind:root:stable1"


def test_merge_with_empty_existing_returns_new_unchanged():
    new = _tree(
        _node("ind:root:fresh1", "engineering"),
        _node("ind:topic:fresh2", "civil", parent_id="ind:root:fresh1"),
    )
    merged = merge_with_existing(new, OntologyTree(nodes={}))
    assert merged.nodes == new.nodes


def test_merge_with_empty_new_returns_new_unchanged():
    existing = _tree(_node("ind:root:stable1", "engineering"))
    new = OntologyTree(nodes={})
    merged = merge_with_existing(new, existing)
    assert merged.nodes == {}


def test_merge_preserves_seed_ids_directly():
    """Seed nodes match by id, not by label path."""
    existing = _tree(
        _node("seed:contract", "Contract", kind="seed"),
        _node("seed:rfi", "RFI", kind="seed"),
    )
    new = _tree(
        _node("seed:contract", "Contract", kind="seed"),
        _node("seed:rfi", "RFI", kind="seed"),
        _node(
            "ind:topic:novel",
            "new_topic",
            parent_id="seed:rfi",
            chunk_ids=["x"],
        ),
    )
    merged = merge_with_existing(new, existing)
    assert "seed:contract" in merged.nodes
    assert "seed:rfi" in merged.nodes
    # The novel topic's parent must still point to the (stable) seed id.
    assert merged.nodes["ind:topic:novel"].parent_id == "seed:rfi"


def test_merge_is_pure_function():
    existing = _tree(_node("ind:topic:stable", "civil"))
    new = _tree(_node("ind:topic:fresh", "civil"))
    existing_snapshot = dict(existing.nodes)
    new_snapshot = dict(new.nodes)
    merge_with_existing(new, existing)
    assert dict(existing.nodes) == existing_snapshot
    assert dict(new.nodes) == new_snapshot


def test_merge_with_evolved_corpus():
    """Realistic scenario: existing tree has 3 nodes; new tree has the same
    3 plus 2 newly-induced topics. The 3 originals must keep their ids;
    the 2 new ones must keep their fresh ids."""
    existing = _tree(
        _node("seed:rfi", "RFI", kind="seed"),
        _node("ind:cat:stable_a", "civil_topics", parent_id="seed:rfi"),
        _node(
            "ind:topic:stable_b",
            "drainage_question",
            parent_id="ind:cat:stable_a",
        ),
    )
    new = _tree(
        _node("seed:rfi", "RFI", kind="seed"),
        _node("ind:cat:fresh_a", "civil_topics", parent_id="seed:rfi"),
        _node(
            "ind:topic:fresh_b",
            "drainage_question",
            parent_id="ind:cat:fresh_a",
            chunk_ids=["new-evidence"],
        ),
        # Net-new nodes
        _node(
            "ind:topic:novel_c",
            "soil_question",
            parent_id="ind:cat:fresh_a",
        ),
        _node(
            "ind:cat:novel_d",
            "electrical_topics",
            parent_id="seed:rfi",
        ),
    )
    merged = merge_with_existing(new, existing)
    # Stable nodes keep their ids.
    assert "ind:cat:stable_a" in merged.nodes
    assert "ind:topic:stable_b" in merged.nodes
    assert merged.nodes["ind:topic:stable_b"].chunk_ids == ["new-evidence"]
    # Novel nodes keep their freshly-assigned ids.
    assert "ind:topic:novel_c" in merged.nodes
    assert "ind:cat:novel_d" in merged.nodes
    # Parent-id rewriting cascades.
    assert merged.nodes["ind:topic:stable_b"].parent_id == "ind:cat:stable_a"
    assert merged.nodes["ind:topic:novel_c"].parent_id == "ind:cat:stable_a"


def test_merge_handles_embedding_consistency():
    """Embedding-dim invariants survive merging (centroid passes through unchanged)."""
    vec_a = [0.1] * EMBEDDING_DIM
    existing = _tree(
        OntologyNode(
            id="ind:topic:stable",
            parent_id=None,
            label="civil",
            kind="induced",
            chunk_ids=[],
            centroid_embedding=vec_a,
            confidence=0.9,
        )
    )
    vec_b = [0.2] * EMBEDDING_DIM
    new = _tree(
        OntologyNode(
            id="ind:topic:fresh",
            parent_id=None,
            label="civil",
            kind="induced",
            chunk_ids=[],
            centroid_embedding=vec_b,
            confidence=0.5,
        )
    )
    merged = merge_with_existing(new, existing)
    # ID gets remapped to the stable one; the *new* centroid wins (re-induction
    # is allowed to refresh embeddings).
    assert "ind:topic:stable" in merged.nodes
    assert merged.nodes["ind:topic:stable"].centroid_embedding == vec_b
