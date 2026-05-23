"""Pydantic v2 input/output schemas for the MCP tools.

The MCP ``tools/list`` response advertises each tool with a JSON Schema
that LLM clients use to format their tool calls. We derive those
schemas from the Pydantic models below via ``model_json_schema()`` so
the schema and the Python validation stay in lockstep — change the
field, the JSON Schema follows.

There are four tools, names cemented:

- ``search`` — vector + keyword search; reuses the BE-04 query path.
- ``read_page`` — fetch a rendered wiki page (stub until ING-05).
- ``read_chunk`` — fetch a raw chunk (stub until ING-02).
- ``list_ontology`` — browse the tenant ontology (stub until ING-04).

These names are part of the LLM-facing contract. Renaming any of them
is a breaking change for every LLM client that has hard-coded the
tool name.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


# ---------------------------------------------------------------------------
# search
# ---------------------------------------------------------------------------

class SearchInput(BaseModel):
    """Arguments for the ``search`` tool.

    Mirrors the BE-04 :class:`QueryRequest` shape but flattened for the
    JSON-RPC ``arguments`` envelope. The fields are intentionally
    LLM-friendly (short names, sensible defaults) and the JSON Schema
    derived from this model is what LLM clients consume.
    """

    model_config = ConfigDict(extra="forbid")

    q: str = Field(
        ...,
        min_length=1,
        max_length=4000,
        description="Natural-language query string.",
    )
    top_k: int = Field(
        default=8,
        ge=1,
        le=50,
        description="Maximum number of result chunks to return.",
    )
    filters: dict[str, Any] = Field(
        default_factory=dict,
        description=(
            "Opaque per-tenant filter object. Today unused; ING-02 will "
            "define the shape (ontology_node_id, document_kind, ...)."
        ),
    )


class SearchChunk(BaseModel):
    model_config = ConfigDict(extra="forbid")

    chunk_id: str
    page_id: str | None = None
    snippet: str
    score: float
    ontology_node_id: str | None = None


class SearchPage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    page_id: str
    title: str
    ontology_node_id: str | None = None


class SearchOutput(BaseModel):
    """Result envelope for ``search``.

    Mirrors the BE-04 ``QueryResponse`` so an MCP client gets exactly
    the same shape as a direct ``/v1/tenants/{id}/query`` call.
    """

    model_config = ConfigDict(extra="forbid")

    answer_chunks: list[SearchChunk] = Field(default_factory=list)
    pages: list[SearchPage] = Field(default_factory=list)
    query_id: str
    took_ms: int


# ---------------------------------------------------------------------------
# read_page
# ---------------------------------------------------------------------------

class ReadPageInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    page_id: str = Field(
        ...,
        min_length=1,
        max_length=200,
        description="Server-issued wiki page id (from a previous ``search`` result).",
    )


class ReadPageOutput(BaseModel):
    """Rendered wiki page payload."""

    model_config = ConfigDict(extra="forbid")

    page_id: str
    slug: str
    title: str
    body_md: str
    body_html: str
    primary_ontology_node_id: str | None = None
    last_built_at: str | None = None


# ---------------------------------------------------------------------------
# read_chunk
# ---------------------------------------------------------------------------

class ReadChunkInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    chunk_id: str = Field(
        ...,
        min_length=1,
        max_length=200,
        description="Server-issued chunk id (from a previous ``search`` result).",
    )


class ReadChunkOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    chunk_id: str
    document_id: str
    text: str
    ordinal: int
    source_uri: str | None = None
    ontology_node_id: str | None = None


# ---------------------------------------------------------------------------
# list_ontology
# ---------------------------------------------------------------------------

class ListOntologyInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    node_id: str | None = Field(
        default=None,
        description=(
            "Subtree root. Omit to return the full tenant ontology "
            "rooted at the implicit ``root`` node."
        ),
    )


class OntologyNode(BaseModel):
    """A node in the ontology tree (recursive ``children``)."""

    model_config = ConfigDict(extra="forbid")

    id: str
    label: str = ""
    kind: str = "category"
    children: list["OntologyNode"] = Field(default_factory=list)


OntologyNode.model_rebuild()


class ListOntologyOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    root: OntologyNode


# ---------------------------------------------------------------------------
# Tool descriptor — the public surface advertised by ``tools/list``.
# ---------------------------------------------------------------------------

TOOL_DESCRIPTORS: list[dict[str, Any]] = [
    {
        "name": "search",
        "description": (
            "Hybrid vector + keyword search across this tenant's "
            "documents. Returns a list of result chunks and the wiki "
            "pages they belong to. Use the chunk_id with read_chunk to "
            "pull the underlying text; use the page_id with read_page "
            "to pull a pre-summarized wiki page."
        ),
        "input_model": SearchInput,
        "output_model": SearchOutput,
    },
    {
        "name": "read_page",
        "description": (
            "Fetch a single wiki page by id. Returns pre-summarized "
            "markdown (token-cheap). Page ids come from search results."
        ),
        "input_model": ReadPageInput,
        "output_model": ReadPageOutput,
    },
    {
        "name": "read_chunk",
        "description": (
            "Fetch the raw text of a single chunk by id, plus a citation "
            "back to its source document. Use when read_page is not "
            "specific enough."
        ),
        "input_model": ReadChunkInput,
        "output_model": ReadChunkOutput,
    },
    {
        "name": "list_ontology",
        "description": (
            "Return the tenant's induced ontology as a tree rooted at "
            "``root`` (or at ``node_id`` if provided). Use to discover "
            "what topics exist before issuing a search."
        ),
        "input_model": ListOntologyInput,
        "output_model": ListOntologyOutput,
    },
]


def tool_definitions() -> list[dict[str, Any]]:
    """Return the MCP ``tools/list`` payload.

    Each entry has ``name``, ``description``, and ``inputSchema`` — the
    last is a JSON Schema derived from the Pydantic input model. We
    intentionally omit ``outputSchema`` (the MCP spec leaves it
    optional and most clients ignore it today).
    """
    defs: list[dict[str, Any]] = []
    for descriptor in TOOL_DESCRIPTORS:
        input_model: type[BaseModel] = descriptor["input_model"]
        schema = input_model.model_json_schema()
        # Strip the ``title`` Pydantic injects — keeps the wire payload
        # uncluttered and matches what other MCP servers emit.
        schema.pop("title", None)
        defs.append(
            {
                "name": descriptor["name"],
                "description": descriptor["description"],
                "inputSchema": schema,
            },
        )
    return defs


# Canonical tool name set — tests import this to assert exact tool names
# never drift.
TOOL_NAMES: tuple[str, ...] = (
    "search",
    "read_page",
    "read_chunk",
    "list_ontology",
)


__all__ = [
    "TOOL_DESCRIPTORS",
    "TOOL_NAMES",
    "ListOntologyInput",
    "ListOntologyOutput",
    "OntologyNode",
    "ReadChunkInput",
    "ReadChunkOutput",
    "ReadPageInput",
    "ReadPageOutput",
    "SearchChunk",
    "SearchInput",
    "SearchOutput",
    "SearchPage",
    "tool_definitions",
]
