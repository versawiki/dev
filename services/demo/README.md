# versawiki-demo

Local-folder demo viewer.

Point this at any folder on your laptop and it will ingest the contents
(real LLM + embedding providers, requires `.vw-anthropic-key` and
`.vw-openai-key` at the repo root) and serve a browsable wiki on
`http://localhost:8000/`.

```
cd services/demo
uv sync
versawiki-demo serve --folder ~/Downloads/some_folder
```

This service is intentionally the only place allowed to import from both
`versawiki-api` and `versawiki-ingestion`; it is the integration glue
that the otherwise-decoupled services need to power a one-process demo.
