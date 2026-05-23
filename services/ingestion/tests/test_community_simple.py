"""Tests for `SimpleConnectedComponentsDetector`."""

from __future__ import annotations

import pytest

from versawiki_ingestion.ontology.community import (
    Community,
    CommunityDetectionResult,
    OntologyCommunityDetector,
    SimpleConnectedComponentsDetector,
)


def _vec(*values: float, dim: int = 16) -> list[float]:
    """Build a small fixed-length vector for unit tests.

    The detector accepts vectors of any length as long as they're all the
    same length (it tolerates non-EMBEDDING_DIM via the secondary length
    check). Using tiny vectors keeps these tests fast.
    """
    base = list(values) + [0.0] * (dim - len(values))
    return base[:dim]


def test_detector_empty_input_returns_empty_result():
    detector = SimpleConnectedComponentsDetector()
    result = detector.detect([])
    assert isinstance(result, CommunityDetectionResult)
    assert result.communities == []
    assert result.num_communities == 0


def test_detector_singleton_input_one_community():
    detector = SimpleConnectedComponentsDetector()
    result = detector.detect([_vec(1.0, 0.0)])
    assert result.num_communities == 1
    assert result.communities[0].cluster_ids == [0]


def test_detector_two_similar_vectors_merge():
    # Two identical-direction vectors should land in one community.
    detector = SimpleConnectedComponentsDetector(similarity_threshold=0.9)
    centroids = [_vec(1.0, 0.0), _vec(0.99, 0.01)]
    result = detector.detect(centroids)
    assert result.num_communities == 1
    assert sorted(result.communities[0].cluster_ids) == [0, 1]


def test_detector_two_orthogonal_vectors_split():
    detector = SimpleConnectedComponentsDetector(similarity_threshold=0.5)
    centroids = [_vec(1.0, 0.0), _vec(0.0, 1.0)]
    result = detector.detect(centroids)
    assert result.num_communities == 2
    ids = sorted(c.cluster_ids[0] for c in result.communities)
    assert ids == [0, 1]


def test_detector_three_clusters_two_communities():
    """0 and 1 close, 2 far. Result: {0,1} and {2}."""
    detector = SimpleConnectedComponentsDetector(similarity_threshold=0.85)
    centroids = [
        _vec(1.0, 0.0),
        _vec(0.99, 0.05),  # very close to 0
        _vec(-1.0, 0.0),  # opposite direction
    ]
    result = detector.detect(centroids)
    assert result.num_communities == 2
    found = sorted([sorted(c.cluster_ids) for c in result.communities])
    assert found == [[0, 1], [2]]


def test_detector_community_for_cluster_lookup():
    detector = SimpleConnectedComponentsDetector(similarity_threshold=0.85)
    centroids = [_vec(1.0, 0.0), _vec(0.99, 0.01), _vec(-1.0, 0.0)]
    result = detector.detect(centroids)
    a = result.community_for_cluster(0)
    b = result.community_for_cluster(1)
    c = result.community_for_cluster(2)
    assert a is not None and b is not None and c is not None
    assert a == b
    assert a != c
    assert result.community_for_cluster(99) is None


def test_detector_protocol_compliance():
    detector = SimpleConnectedComponentsDetector()
    assert isinstance(detector, OntologyCommunityDetector)
    assert detector.name == "connected-components"


def test_detector_threshold_validation():
    with pytest.raises(ValueError):
        SimpleConnectedComponentsDetector(similarity_threshold=1.5)
    with pytest.raises(ValueError):
        SimpleConnectedComponentsDetector(similarity_threshold=-0.1)


def test_detector_transitive_closure():
    """Three vectors forming an A-B-C chain (A~B, B~C, A!~C directly) still
    end up in one community because connected-components is transitive."""
    detector = SimpleConnectedComponentsDetector(similarity_threshold=0.7)
    centroids = [
        _vec(1.0, 0.0, 0.0),
        _vec(0.71, 0.71, 0.0),  # cos with A ~ 0.71
        _vec(0.0, 1.0, 0.0),    # cos with B ~ 0.71; cos with A = 0
    ]
    result = detector.detect(centroids)
    assert result.num_communities == 1
    assert sorted(result.communities[0].cluster_ids) == [0, 1, 2]


def test_detector_community_membership_is_a_partition():
    detector = SimpleConnectedComponentsDetector(similarity_threshold=0.85)
    centroids = [_vec(1.0, 0.0), _vec(0.99, 0.01), _vec(-1.0, 0.0), _vec(-0.99, 0.01)]
    result = detector.detect(centroids)
    seen: set[int] = set()
    for c in result.communities:
        assert not (set(c.cluster_ids) & seen), "communities overlap"
        seen.update(c.cluster_ids)
    assert seen == {0, 1, 2, 3}


def test_detector_community_is_dataclass_with_id_and_clusters():
    c = Community(community_id=7, cluster_ids=[2, 3])
    assert c.community_id == 7
    assert c.cluster_ids == [2, 3]
