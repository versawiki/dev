_MCP builder's working notes. Newest at top._

## 2026-05-22 — M1-MCP-01a finishing pass

Picked up the half-finished M1-MCP-01a from the previous specialist.
Status from arrival:

* Schema (`schema/observation.py`), 5+1-stage pipeline (`checkers/pipeline.py`),
  and four stage modules (`forbidden_fields`, `pii`, `numeric`, `quotes`)
  were in place and importing cleanly.
* `pyproject.toml` and the service README already existed.
* No audit module. No tests at all.

### What I added

* `src/versawiki_meta_mcp/audit/__init__.py` and `audit/tenant_audit_log.py`
  — JSONL writer for tenant-local audit records. Top-of-file comment
  states the privacy invariant: only `payload_hash + reason_code +
  stage + timestamp` ever land on disk. Payload bytes are never written.
* `tests/conftest.py` — fixtures: tmp audit dir, an `envelope_of` builder,
  and one principle-only payload fixture for each of the 8 variants.
* `tests/test_schema_observation.py` — round-trip for each variant,
  `extra="forbid"` rejection of unknown fields at envelope and payload
  level, discriminator routing.
* `tests/test_pipeline_happy.py` — all 8 variants pass the full chain;
  `run_static_checkers` convenience entry works.
* `tests/test_pipeline_pii.py` — email / SSN / phone / URL smuggled into
  `tenant_anon_id` (the only realistic free-string vector after the
  schema's `Literal` discipline) trips the regex layer with the correct
  reason code. spaCy NER PERSON-name test is `skipif`-guarded since
  the model isn't installed in this sandbox.
* `tests/test_pipeline_numeric.py` — raw count under `kind_distribution`,
  out-of-band `chunks_per_doc_p50`, and out-of-[0,1] ratio leaf all hit
  `RAW_NUMERIC`. Plus one `xfail(strict=True)` for the branching-factor
  source issue below.
* `tests/test_pipeline_forbidden_fields.py` — top-level, nested,
  case-insensitive, and prefix matches; sanity-check that spec §4
  names are all present in `FORBIDDEN_FIELD_NAMES`.
* `tests/test_pipeline_opt_out.py` — `opt_out_flag=True` rejects an
  otherwise-passing envelope at the opt-out stage with `OPT_OUT` reason
  (note: enum is `OPT_OUT`, not `OPTED_OUT` as the ticket draft said);
  earlier stages all marked passed.
* `tests/test_audit_log.py` — load-bearing privacy assertion is
  `set(record.keys()) == {"payload_hash", "reason_code", "stage",
  "timestamp"}`. Also writes-twice-gets-two-lines append behaviour and
  a raw-bytes check that the simulated PII string never appears in the
  on-disk file.

### Test result

```
41 passed, 1 skipped, 1 xfailed in 1.01s
```

The skip is the spaCy PERSON-name test (model not installed). The xfail
is the branching-factor source issue described below.

### Source issue I found (NON-privacy — overly strict, not too lax)

`checkers/numeric.py` lists `branching_factor_p50` and
`branching_factor_p95` in `ALLOWED_RATIO_LEAVES`, which caps them at
`[0.0, 1.0]`. Per spec §3.1 these are real branching factors (median /
p95 of children per non-leaf), legitimately > 1.0 for almost every
real tree. The schema correctly has `Field(ge=0.0)` with no upper
bound; the numeric stage contradicts the schema.

This is **overly strict**, not too lax — the failure mode is rejecting
legitimate principle-only data, not leaking content. So per the
ticket's instructions I marked it `xfail(strict=True)` with a pointer
back to this note rather than silently patching the checker. The fix:
add a new `ALLOWED_UNBOUNDED_NONNEG_FLOAT_LEAVES` set in
`checkers/numeric.py` and move `branching_factor_p*` into it.

My fixture for `OntologyShape` uses 0.5 / 0.85 so the happy-path tests
reflect what the implementation actually enforces today, with an inline
comment pointing back here.

### Cowork file-sync gotcha that bit me

The `Edit` tool truncated `tests/conftest.py` mid-fixture when I tried
to change two literal values, and again on `tests/test_pipeline_numeric.py`
when I appended an xfail block. The cowork-side `Read` showed the
correct, complete file each time, but the bash-mount view of the same
file ended mid-line. Recovery: rewrite via `cat > … <<'EOF'` heredoc.

Confirms the rule in MEMORY.md: any edit to an existing file in this
sandbox goes through bash heredoc, not the `Edit` tool. New files via
`Write` are fine (verified — the test files I created with `Write` were
intact on the mount).

### Hand-off to M1-MCP-02 / -05

* Audit log is sync-only and JSONL. v2 wraps it in async + Postgres
  per ticket M1-MCP-02; the privacy invariant statement at the top of
  `tenant_audit_log.py` should be copied verbatim into the v2 writer.
* The pipeline still reads `opt_out_flag` from the envelope rather
  than calling an injected callable. M1-MCP-05 should introduce the
  injection point and keep this test as the behavioural contract.
* Quote / near-quote stage is the v1 stub-corpus version. M1-MCP-02
  wires the real corpus shingle source.

### Additional source issue I found while debugging test flakes

`checkers/pii.py` regex `_PHONE_RE` triggers on roughly 3% of random
UUIDv4 strings — UUIDs occasionally contain 3-digit, 3-digit, 4-digit
runs even though they aren't phones. Found this when randomly-generated
`event_id` values caused `test_structural_count_above_max_rejected` to
fail intermittently (PII stage rejected the envelope before the numeric
stage could).

Workaround in the test suite: `tests/conftest.py` uses a fixed,
hex-letter-heavy event_id. The longer-term fix is to tighten the phone
regex (e.g., require `+` or `(` or a leading separator boundary that a
UUID's `-` does not satisfy) or to whitelist UUID-shape strings in the
PII walker — but that crosses a privacy line and should not be done
without an audit. UUID-detection by structure (8-4-4-4-12 hex) might be
the right whitelist: schema typing the envelope's identifier fields as
`UUID` already proves they aren't free text.

Like the branching-factor issue, this is **overly eager** (false
positives), not too permissive — no privacy breach, just operational
noise. Track for M1-MCP-02 hardening.
