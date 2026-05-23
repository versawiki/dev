# `versawiki-ingestion`

The ingestion service for Versawiki. Walks a source (local folder in M1; Drive,
OneDrive, etc. in M2+), parses each document into a normalised `ParseResult`,
and (once integrated with the Backend) chunks, embeds, classifies, and persists
to the tenant's Postgres schema.

See `docs/architecture/v1.md` §1.1 for the broader service decomposition.

## Layout

```
src/versawiki_ingestion/
  connectors/
    base.py          Connector Protocol: list / fetch / watch
    local_folder.py  LocalFolderConnector — walks a directory, hashes by
                     mtime+size, yields ChangeEvents on watch()
    _models.py       ResourceRef + ChangeEvent (Pydantic v2 frozen models)
  parsers/
    base.py          BaseParser ABC + ParseResult (lifted from prior repo)
    email.py         .eml + .msg parsing
    excel.py         .xlsx / .xls / .csv parsing
    registry.py      MIME / extension -> parser class
  seeds/
    aec_starter_taxonomy.yaml  Initial AEC ontology (10 doc types, ~80 fields)
tests/
  test_local_folder_connector.py
  test_parsers.py
  test_registry.py
```

## Run a one-off local-folder ingest

The service is library-shape in M1 — there is no daemon. To probe it:

```bash
cd services/ingestion
pip install -e .[test]

python -c "
from pathlib import Path
from versawiki_ingestion.connectors.local_folder import LocalFolderConnector
from versawiki_ingestion.parsers.registry import ParserRegistry

conn = LocalFolderConnector(root=Path('/tmp/sample-corpus'),
                            tenant_id='acme', source_id='local-1')
registry = ParserRegistry.default()
for ref in conn.list():
    parser = registry.for_ref(ref)
    if parser is None:
        continue
    data = conn.fetch(ref)
    # parser.parse() expects a Path today; M1-ING-02 changes the signature to
    # accept bytes-or-path. For now write to a temp file:
    import tempfile, os
    with tempfile.NamedTemporaryFile(suffix=ref.path.suffix, delete=False) as fh:
        fh.write(data); tmp = Path(fh.name)
    try:
        result = parser.parse(tmp, tenant_id='acme', source_id='local-1')
        print(ref.uri, result.document_type, len(result.full_text))
    finally:
        os.unlink(tmp)
"
```

Full ingest with chunking + embedding + persistence is `M1-ING-02` (chunker +
embedder) + Backend's `M1-BE-03` (schema provisioner). This package owns the
fetch + parse half only.

## Tests

```bash
cd services/ingestion
PYTHONPATH=src PYTHONPYCACHEPREFIX=/tmp/vwpyc PYTHONDONTWRITEBYTECODE=1 \
  python -m pytest -q tests/
```
