"""`PageBuilder` — one ontology node + its chunks -> one ``WikiPage``.

Pipeline steps inside ``build_for_node``:

  1. Rank chunks by relevance to the node (cosine to the node centroid;
     chunks already carry embeddings). The top-N chunks drive the
     title, summary, and citation list.
  2. Propose a title (LLM in production; stub for tests).
  3. Generate a 200-500 word summary via the LLM writer.
  4. Compose the markdown body with four sections:
       ## Overview
       ## Key documents
       ## Related topics
       ## Metadata
  5. Compute ``related_page_ids`` from sibling / parent / child
     ontology nodes (the pipeline patches in the real ids after every
     page is built).
  6. Build the final ``WikiPage`` with ``is_stale=False`` and
     ``version=1``.

The builder is intentionally pure given its inputs (it doesn't read
from a store, doesn't write to one, doesn't talk to any event bus).
That makes it cheap to unit-test and easy to drive in parallel.
"""

from __future__ import annotations

import hashlib
import math
import re
from collections import Counter
from datetime import datetime, timezone
from typing import Optional, Sequence

from ..classification.base import ClassifierResult
from ..ontology.models import OntologyNode, OntologyTree
from ..pipeline.models import ChunkRecord
from .llm_writer import LLMPageWriter, StubPageWriter
from .models import WikiPage

# How many top-ranked chunks feed the LLM writer + the "Key documents"
# section. Above this we hit diminishing returns and just inflate
# prompt cost.
_TOP_CHUNK_COUNT: int = 10

# Minimum chunks for a node to get its own page. Below this we roll the
# chunks into the parent (the pipeline does the rollup; the builder
# refuses to build for too-small nodes).
DEFAULT_MIN_CHUNKS_FOR_PAGE: int = 2

# Snippet length per chunk in the "Key documents" section.
_SNIPPET_LEN: int = 240


# ---------------------------------------------------------------------------
# Vector math — small helpers kept local so we don't drag in numpy here.
# ---------------------------------------------------------------------------


def _cosine(a: Sequence[float], b: Sequence[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = 0.0
    na = 0.0
    nb = 0.0
    for x, y in zip(a, b):
        dot += x * y
        na += x * x
        nb += y * y
    if na <= 0.0 or nb <= 0.0:
        return 0.0
    return dot / (math.sqrt(na) * math.sqrt(nb))


def _slugify(text: str) -> str:
    """URL-friendly slug. Stable for the same input."""
    s = text.lower().strip()
    s = re.sub(r"[^a-z0-9]+", "-", s)
    s = s.strip("-")
    if not s:
        s = "page"
    # Cap length so postgres + URL routers don't choke.
    return s[:80]


def _stable_page_id(tenant_id: str, ontology_node_id: str) -> str:
    """Deterministic page id keyed by (tenant, node). Same node -> same id."""
    h = hashlib.sha1(
        f"{tenant_id}|{ontology_node_id}".encode("utf-8"),
        usedforsecurity=False,
    ).hexdigest()[:16]
    return f"pg_{h}"


# ---------------------------------------------------------------------------
# PageBuilder
# ---------------------------------------------------------------------------


class PageBuilder:
    """Build one ``WikiPage`` from one ``OntologyNode`` + its chunks.

    Stateless. Inject an ``LLMPageWriter`` (defaults to the stub) at
    construction; the writer is the only side-effecting collaborator.
    """

    def __init__(
        self,
        *,
        llm_writer: Optional[LLMPageWriter] = None,
        min_chunks_for_page: int = DEFAULT_MIN_CHUNKS_FOR_PAGE,
    ) -> None:
        self.llm_writer: LLMPageWriter = llm_writer or StubPageWriter()
        self.min_chunks_for_page = min_chunks_for_page

    # ------------------------------------------------------------------

    async def build_for_node(
        self,
        node: OntologyNode,
        chunks: Sequence[ChunkRecord],
        classifier_results: dict[str, ClassifierResult] | None = None,
        *,
        tenant_id: str,
        tree: OntologyTree | None = None,
        related_page_ids: Sequence[str] | None = None,
        now: datetime | None = None,
    ) -> WikiPage:
        """Build a page for ``node``.

        Args:
            node: The ontology node being summarised.
            chunks: The chunks attached to this node (the inducer's
                output `node.chunk_ids` -> these). Already embedded.
            classifier_results: Map from
                ``ChunkRecord.document_content_hash`` to the
                classifier's verdict for that document. Used to fill
                the ``predominant_doc_types`` field + the Metadata
                section. May be ``None`` / empty if classifier output
                isn't available.
            tenant_id: The owning tenant. Pinned into the page.
            tree: Full ontology tree (optional). When provided, the
                Related topics section lists sibling / child node
                labels. Without it, the Related topics section is
                left empty (the pipeline fills it in later).
            related_page_ids: Pre-computed related ids (optional). The
                pipeline computes these in a second pass once all
                pages exist. If absent, ``related_page_ids`` defaults
                to ``[]`` here and the pipeline patches in later.
            now: Override for ``created_at`` / ``updated_at`` (tests).
        """
        classifier_results = classifier_results or {}
        now = now or datetime.now(tz=timezone.utc)

        # 1. Rank chunks by relevance to the node centroid.
        ranked = self._rank_chunks(node, chunks)
        top_chunks = ranked[:_TOP_CHUNK_COUNT]

        # 2 + 3. Title + summary via the LLM writer.
        title = await self.llm_writer.propose_title(
            node_label=node.label, top_chunks=top_chunks
        )
        summary = await self.llm_writer.write_summary(
            node_label=node.label, top_chunks=top_chunks
        )

        # 4. Compose the markdown body.
        related_labels = self._related_labels(node, tree)
        body_markdown = self._render_body(
            summary=summary,
            top_chunks=top_chunks,
            related_labels=related_labels,
            classifier_results=classifier_results,
            ranked=ranked,
            now=now,
        )

        # 5. Derive metadata fields.
        source_uris = {c.source_uri for c in ranked}
        doc_types = self._doc_type_distribution(ranked, classifier_results)

        page_id = _stable_page_id(tenant_id, node.id)
        slug = _slugify(title)
        return WikiPage(
            id=page_id,
            tenant_id=tenant_id,
            ontology_node_id=node.id,
            title=title,
            slug=slug,
            summary=summary,
            body_markdown=body_markdown,
            chunk_ids=[c.chunk_content_hash for c in ranked],
            related_page_ids=list(related_page_ids or []),
            created_at=now,
            updated_at=now,
            is_stale=False,
            version=1,
            source_uri_count=len(source_uris),
            predominant_doc_types=doc_types,
        )

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _rank_chunks(
        self, node: OntologyNode, chunks: Sequence[ChunkRecord]
    ) -> list[ChunkRecord]:
        """Sort chunks by descending cosine similarity to the node centroid.

        Ties broken by ``position`` ascending then ``chunk_content_hash``
        so the order is fully deterministic — that's what the
        idempotence test relies on.
        """
        if not node.centroid_embedding:
            # No centroid available — fall back to position order.
            return sorted(
                chunks, key=lambda c: (c.position, c.chunk_content_hash)
            )

        def _key(c: ChunkRecord) -> tuple[float, int, str]:
            sim = _cosine(node.centroid_embedding, c.embedding or [])
            # Negate similarity so higher sim sorts first.
            return (-sim, c.position, c.chunk_content_hash)

        return sorted(chunks, key=_key)

    def _related_labels(
        self, node: OntologyNode, tree: OntologyTree | None
    ) -> list[str]:
        """Sibling + child labels for the Related topics section."""
        if tree is None:
            return []
        labels: list[str] = []
        # Children.
        for kid in tree.children_of(node.id):
            if kid.label and kid.label not in labels:
                labels.append(kid.label)
        # Siblings (same parent, not self).
        if node.parent_id is not None:
            for sib in tree.children_of(node.parent_id):
                if sib.id == node.id:
                    continue
                if sib.label and sib.label not in labels:
                    labels.append(sib.label)
        return labels

    def _doc_type_distribution(
        self,
        chunks: Sequence[ChunkRecord],
        classifier_results: dict[str, ClassifierResult],
    ) -> list[str]:
        """Top doc-types across the chunks' source documents.

        We rank by frequency and return up to 5; the order is
        deterministic (counter.most_common is stable for ties on cpython
        but we also sort by label to remove any ambiguity).
        """
        if not classifier_results:
            return []
        counts: Counter[str] = Counter()
        seen_docs: set[str] = set()
        for c in chunks:
            if c.document_content_hash in seen_docs:
                continue
            seen_docs.add(c.document_content_hash)
            result = classifier_results.get(c.document_content_hash)
            if result is None:
                continue
            counts[result.predicted_type] += 1
        # Sort by descending count, then ascending label so ties are
        # deterministic across runs.
        ordered = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))
        return [t for t, _ in ordered[:5]]

    def _render_body(
        self,
        *,
        summary: str,
        top_chunks: list[ChunkRecord],
        related_labels: list[str],
        classifier_results: dict[str, ClassifierResult],
        ranked: list[ChunkRecord],
        now: datetime,
    ) -> str:
        """Render the four-section markdown body.

        Sections (order is part of the contract — tests assert it):
          ## Overview
          ## Key documents
          ## Related topics
          ## Metadata
        """
        lines: list[str] = []

        # Overview.
        lines.append("## Overview")
        lines.append("")
        lines.append(summary)
        lines.append("")

        # Key documents.
        lines.append("## Key documents")
        lines.append("")
        if not top_chunks:
            lines.append("_No source documents available yet._")
        else:
            for i, chunk in enumerate(top_chunks, start=1):
                snippet = chunk.text.strip().replace("\n", " ")
                if len(snippet) > _SNIPPET_LEN:
                    snippet = snippet[: _SNIPPET_LEN - 3].rstrip() + "..."
                lines.append(f"{i}. [{chunk.source_uri}]({chunk.source_uri})")
                lines.append(f"   > {snippet}")
        lines.append("")

        # Related topics.
        lines.append("## Related topics")
        lines.append("")
        if related_labels:
            for label in related_labels:
                lines.append(f"- {label}")
        else:
            lines.append("_No related topics._")
        lines.append("")

        # Metadata.
        lines.append("## Metadata")
        lines.append("")
        source_uris = {c.source_uri for c in ranked}
        lines.append(f"- Source documents: {len(source_uris)}")
        lines.append(f"- Total chunks: {len(ranked)}")
        # Use a fixed UTC ISO format (timespec=seconds) so the body
        # markdown is stable for the same `now` (idempotence test).
        lines.append(
            f"- Last updated: {now.astimezone(timezone.utc).isoformat(timespec='seconds')}"
        )
        if classifier_results:
            doc_types = self._doc_type_distribution(ranked, classifier_results)
            if doc_types:
                lines.append(
                    "- Predominant document types: " + ", ".join(doc_types)
                )
        return "\n".join(lines).rstrip() + "\n"


__all__ = [
    "DEFAULT_MIN_CHUNKS_FOR_PAGE",
    "PageBuilder",
    "_stable_page_id",
    "_slugify",
]
