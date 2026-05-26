"""``versawiki-demo`` — Typer CLI for the local-folder demo viewer.

One command:

    versawiki-demo serve --folder PATH [--tenant-id demo] [--port 8000]

Behaviour:

  1. Validates the folder exists and is non-empty.
  2. Reads ``.vw-anthropic-key`` + ``.vw-openai-key`` from the repo
     root for credentials (env vars override).
  3. Prints a cost estimate; prompts unless ``--yes`` is given.
  4. Runs the ingestion pipeline (real LLM classifier + real OpenAI
     embeddings + real LLM page writer) end-to-end into a fresh
     :class:`InMemoryPageStore`.
  5. Maps every ingested :class:`WikiPage` to a
     :class:`WikiPageRecord` and upserts into the api's page store.
  6. Builds the api FastAPI app, mounts the viewer router on it, sets
     ``app.state.demo_tenant_id`` so the viewer knows which tenant's
     pages to surface.
  7. Prints "Open http://localhost:{port}/..." and yields to uvicorn.
"""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path
from typing import Optional

import typer
import uvicorn

app = typer.Typer(
    add_completion=False,
    help="Ingest a folder and serve a browsable wiki on localhost.",
    no_args_is_help=True,
)


# ---------------------------------------------------------------------------
# Credential discovery
# ---------------------------------------------------------------------------


def _repo_root_from_here() -> Path:
    """Walk up from this file to find the versawiki repo root.

    The repo root is identified by the presence of a ``STATUS.md`` at
    the same level as a ``services/`` directory. Falls back to the
    process cwd if no marker is found.
    """
    here = Path(__file__).resolve()
    for ancestor in (here, *here.parents):
        if (ancestor / "STATUS.md").is_file() and (ancestor / "services").is_dir():
            return ancestor
    return Path.cwd().resolve()


def _read_key_file(repo_root: Path, name: str) -> Optional[str]:
    p = repo_root / name
    if not p.is_file():
        return None
    txt = p.read_text(encoding="utf-8").strip()
    return txt or None


def _resolve_keys(repo_root: Path) -> tuple[str, str]:
    """Return (anthropic_key, openai_key). Env vars override files.

    Exits with a clear error if either key is missing.
    """
    anthropic_key = os.environ.get("ANTHROPIC_API_KEY") or _read_key_file(repo_root, ".vw-anthropic-key")
    openai_key = os.environ.get("OPENAI_API_KEY") or _read_key_file(repo_root, ".vw-openai-key")
    missing = []
    if not anthropic_key:
        missing.append(".vw-anthropic-key (or ANTHROPIC_API_KEY env)")
    if not openai_key:
        missing.append(".vw-openai-key (or OPENAI_API_KEY env)")
    if missing:
        typer.secho(
            f"ERROR: missing credentials: {', '.join(missing)}",
            fg=typer.colors.RED,
            err=True,
        )
        raise typer.Exit(code=2)
    return anthropic_key, openai_key  # type: ignore[return-value]


# ---------------------------------------------------------------------------
# Folder validation + cost estimate
# ---------------------------------------------------------------------------


def _validate_folder(folder: Path) -> list[Path]:
    """Return the sorted list of files in ``folder`` (recursively).

    Exits with code 2 if the folder is missing or contains zero files.
    """
    if not folder.exists():
        typer.secho(f"ERROR: folder does not exist: {folder}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=2)
    if not folder.is_dir():
        typer.secho(f"ERROR: not a directory: {folder}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=2)
    files = sorted(p for p in folder.rglob("*") if p.is_file())
    if not files:
        typer.secho(f"ERROR: folder is empty: {folder}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=2)
    return files


def _cost_band(file_count: int) -> str:
    if file_count <= 10:
        return "~$0.10-$0.30"
    if file_count <= 50:
        return "~$0.30-$1.00"
    return "~$1.00-$5.00 (large folder)"


# ---------------------------------------------------------------------------
# The ingest + serve command
# ---------------------------------------------------------------------------


@app.command()
def serve(
    folder: Path = typer.Option(
        ...,
        "--folder",
        "-f",
        help="Path to a folder on disk to ingest and serve.",
        exists=False,  # we do our own check for a friendlier message
        file_okay=False,
        dir_okay=True,
        resolve_path=True,
    ),
    tenant_id: str = typer.Option(
        "demo",
        "--tenant-id",
        help="Tenant id to associate the ingested pages with.",
    ),
    port: int = typer.Option(
        8000,
        "--port",
        "-p",
        help="Port to bind the demo viewer to.",
    ),
    host: str = typer.Option(
        "127.0.0.1",
        "--host",
        help="Host to bind to (default: loopback only).",
    ),
    yes: bool = typer.Option(
        False,
        "--yes",
        "-y",
        help="Skip the cost-estimate prompt and start ingestion immediately.",
    ),
) -> None:
    """Ingest ``--folder`` and serve a browsable wiki on ``--port``.

    Real LLM (Anthropic for classification + page writing) and real
    OpenAI embedding calls are made. A cost band is printed before the
    run starts; press ``y`` to confirm (or pass ``--yes``).
    """
    repo_root = _repo_root_from_here()
    anthropic_key, openai_key = _resolve_keys(repo_root)
    files = _validate_folder(folder)

    band = _cost_band(len(files))
    typer.secho(
        f"\nAbout to ingest {len(files)} file{'s' if len(files) != 1 else ''} from {folder}.",
        fg=typer.colors.CYAN,
    )
    typer.secho(
        f"This will call Anthropic + OpenAI. Estimated cost: {band}",
        fg=typer.colors.CYAN,
    )
    if not yes:
        if not typer.confirm("Proceed?", default=False):
            typer.secho("Aborted.", fg=typer.colors.YELLOW)
            raise typer.Exit(code=1)

    # Surface keys to provider modules that read them from the env.
    os.environ["ANTHROPIC_API_KEY"] = anthropic_key
    os.environ["OPENAI_API_KEY"] = openai_key

    typer.secho("\nIngesting (this may take a minute for larger folders)...", fg=typer.colors.CYAN)
    pages = asyncio.run(
        _ingest_folder(
            folder=folder,
            tenant_id=tenant_id,
            anthropic_key=anthropic_key,
            openai_key=openai_key,
        )
    )
    typer.secho(f"  -> built {len(pages)} wiki page(s).", fg=typer.colors.GREEN)

    # Build the api app and inject the populated page store + viewer.
    app_fastapi = _build_demo_app(pages=pages, tenant_id=tenant_id)

    typer.secho(
        f"\nOpen http://{host}:{port}/ in your browser",
        fg=typer.colors.BRIGHT_GREEN,
        bold=True,
    )
    uvicorn.run(app_fastapi, host=host, port=port, log_level="info")


# ---------------------------------------------------------------------------
# Ingestion runner (mirrors services/ingestion/tests/e2e/conftest.py::_run_pipeline
# but uses REAL providers).
# ---------------------------------------------------------------------------


async def _ingest_folder(
    *,
    folder: Path,
    tenant_id: str,
    anthropic_key: str,
    openai_key: str,
) -> list["WikiPageRecord"]:  # noqa: F821 - forward ref via string for typing only
    """Drive ingestion -> ontology -> pages and return WikiPageRecords."""
    from versawiki_api.pages_store import WikiPageRecord
    from versawiki_ingestion.chunking import Chunker, RecursiveCharacterSplitter
    from versawiki_ingestion.classification import DocumentClassifier
    from versawiki_ingestion.classification.llm_provider import AnthropicClassifier
    from versawiki_ingestion.classification.taxonomy import Taxonomy
    from versawiki_ingestion.connectors.local_folder import LocalFolderConnector
    from versawiki_ingestion.embedding.openai_provider import OpenAIEmbeddingProvider
    from versawiki_ingestion.ontology.inducer import OntologyInducer
    from versawiki_ingestion.pages import (
        AnthropicPageWriter,
        PageBuildPipeline,
        PageBuilder,
    )
    from versawiki_ingestion.parsers.registry import ParserRegistry
    from versawiki_ingestion.pipeline import process_document

    source_id = f"demo-source-{folder.name or 'root'}"
    connector = LocalFolderConnector(folder, tenant_id=tenant_id, source_id=source_id)
    refs = list(connector.list())

    classifier = DocumentClassifier(
        AnthropicClassifier(api_key=anthropic_key),
        taxonomy=Taxonomy.starter(),
    )
    parser_registry = ParserRegistry.default()
    embedding_provider = OpenAIEmbeddingProvider(api_key=openai_key)

    processed = []
    for i, ref in enumerate(refs, 1):
        chunker = Chunker(
            text_splitter=RecursiveCharacterSplitter(chunk_size=400, chunk_overlap=40)
        )
        typer.secho(f"  [{i}/{len(refs)}] {ref.uri}", fg=typer.colors.WHITE)
        out = await process_document(
            ref,
            connector=connector,
            parser_registry=parser_registry,
            chunker=chunker,
            embedding_provider=embedding_provider,
            classifier=classifier,
        )
        processed.append(out)

    all_chunks = []
    for pd in processed:
        all_chunks.extend(pd.chunks)

    classifier_results = {}
    for pd in processed:
        if pd.classification is None or not pd.chunks:
            continue
        doc_hash = pd.chunks[0].document_content_hash
        classifier_results[doc_hash] = pd.classification

    typer.secho(f"  inducing ontology over {len(all_chunks)} chunk(s)...", fg=typer.colors.WHITE)
    inducer = OntologyInducer()
    tree = await inducer.induce(all_chunks)

    pipeline = PageBuildPipeline(
        builder=PageBuilder(llm_writer=AnthropicPageWriter(api_key=anthropic_key)),
        store=None,  # we handle the store ourselves on the api side
    )
    wiki_pages = await pipeline.build_for_tree(
        tree, all_chunks, classifier_results, tenant_id=tenant_id
    )

    # WikiPage and WikiPageRecord have field-identical shapes (verified
    # in services/api/src/versawiki_api/pages_store.py docstring).
    records = [WikiPageRecord(**p.model_dump()) for p in wiki_pages]
    return records


# ---------------------------------------------------------------------------
# App wiring (api app + viewer router, no auth-middleware-required routes).
# ---------------------------------------------------------------------------


def _build_demo_app(*, pages, tenant_id: str):
    """Build the FastAPI app the demo serves.

    Returns a configured ``FastAPI`` instance with:

      - All existing api JSON routes (/v1/...) intact.
      - The viewer router (/, /wiki/{slug}, /search) mounted alongside.
      - ``app.state.page_store`` populated with the ingested pages.
      - ``app.state.demo_tenant_id`` set so the viewer can find them.

    The api ``services/api/`` code is not modified — we just receive
    the FastAPI app from its factory and add routes on top.
    """
    from versawiki_api.app import create_app
    from versawiki_api.deps import set_page_store
    from versawiki_api.pages_store import InMemoryPageStore

    from versawiki_demo import viewer

    fastapi_app = create_app()
    store = InMemoryPageStore()

    async def _populate():
        for rec in pages:
            await store.upsert(rec)

    asyncio.run(_populate())

    set_page_store(fastapi_app, store)
    fastapi_app.state.demo_tenant_id = tenant_id
    # Cache the pages list on the store so the viewer's _all_pages_for_tenant
    # helper can use it (it falls back to ``store._pages`` introspection
    # when this isn't set).
    store._demo_cached_pages = list(pages)  # type: ignore[attr-defined]

    fastapi_app.include_router(viewer.router)
    return fastapi_app


def main() -> int:
    """Console-script entry point. ``versawiki-demo`` -> typer."""
    app()
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
