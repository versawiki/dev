# notes/support-agent.md

Session log for the customer-support agent role.

## 2026-05-23 - M1-CS-01 v1 built (62 tests passing)

Built the autonomous customer-support agent under
`services/support-agent/`. The agent's mission: handle 80%+ of inquiries
directly, gather context on the rest, escalate clearly-flagged
exceptions to a JSON-file review queue Josh reads on demand.

### Layout

- `src/versawiki_support/`
  - `conversation.py` - Conversation Pydantic model + status state machine
  - `messages.py` - Message model + conservative Luhn-checked PII redactor
    (credit cards, SSNs, `vw_`/`sk_`/`pk_` bearer tokens)
  - `knowledge_base.py` - markdown KB loader; mtime-based hot reload; keyword
    scoring weighted tags(x3) > name(x2) > body(x1)
  - `safe_actions.py` - allow-list with per-action gates
    (tenant-match, verified-destructive, always-allow); the
    `execute_action(conv, name, args)` entry point is the only path to
    a handler
  - `forbidden_actions.py` - hard-NO list; name + keyword substring
    matcher; severity-tagged
  - `llm.py` - `SupportLLM` Protocol; `StubSupportLLM` for tests with a
    response queue; `AnthropicSupport(claude-sonnet-4-6)` for prod
    (untouched by tests). System prompt template renders the safe and
    forbidden action lists into the prompt body.
  - `agent.py` - the main loop (`SupportAgent.handle_message`)
  - `storage.py` - JSONL-per-conversation store (append-only;
    `load()` returns latest snapshot; `history()` replays all)
  - `intake/email.py` - poller + Protocol IMAP client (no live IMAP)
  - `intake/web.py` - FastAPI POST `/support/web/messages`
  - `intake/api.py` - FastAPI POST `/support/api/messages` (auth wiring
    deferred to M1-CS-02)
  - `escalation/queue.py` - append-only JSON-per-conversation queue,
    date-bucketed; second escalation same conversation same day gets a
    `.2.json` suffix so prior entries are never rewritten
  - `escalation/notify.py` - Notifier Protocol + `StubNotifier`
    (Slack/email backend deferred)

- `kb/`
  - `getting-started.md`
  - `api-keys.md` (token format, issue/list/revoke, reissue, security
    tips, what support can and cannot do)
  - `ingestion.md`
  - `privacy.md` (content-vs-pattern boundary; opt-out path)
  - `billing.md` (placeholder; "escalate for any billing change")
  - `troubleshooting.md`
  - `escalation-criteria.md`

### Safe-action list

`lookup_tenant_status`, `lookup_ingestion_status`, `reissue_api_key`
(verified-destructive), `pause_ingestion`, `escalate`,
`request_account_verification`.

### Forbidden (hard-NO) list

`delete_data`, `issue_refund`, `change_billing`,
`modify_privacy_settings`, `cross_tenant_lookup`,
`undelegated_authority`.

### Privacy-load-bearing tests

- `test_agent_cross_tenant_block.py::test_cross_tenant_lookup_refused_and_audited_not_escalated`
  is the single test that would mean a privacy/auth breach if it
  silently flipped to passing without an actual block. The
  cross-tenant gate is in `safe_actions._tenant_match_gate`. The agent
  loop rewrites the reply to the safe refusal string when ANY action
  was denied so the LLM's narration of a denied lookup never leaks.
  We DELIBERATELY do not escalate on cross-tenant attempts so the
  reviewer queue doesn't receive a record keyed to tenant A that
  mentions tenant B (which would itself be a small information leak).

- `test_agent_pii_redaction.py::test_conversation_log_never_contains_cc_number`
  is the load-bearing PII test. Redaction happens on the way in via
  `new_customer_message`, so even the LLM stub never sees the raw
  card number.

### Test count

62 passing in ~0.5s on a fresh checkout. Breakdown:

- `test_kb_loader.py` - 8
- `test_safe_actions.py` - 11
- `test_forbidden_actions.py` - 8
- `test_agent_happy_path.py` - 4
- `test_agent_escalation.py` - 4
- `test_agent_cross_tenant_block.py` - 3
- `test_agent_pii_redaction.py` - 9
- `test_intake_email.py` - 4
- `test_intake_web.py` - 5
- `test_escalation_queue.py` - 6

### Open follow-ups (for the next session)

1. **M1-CS-02**: wire the real Anthropic call with structured tool-use
   so the LLM's `tool_calls` field is populated from Claude's tool
   interface (today the AnthropicSupport adapter only returns text).
   The `SupportLLM` Protocol already expects the structured shape;
   the adapter is the bottleneck.
2. **M1-CS-03**: connect the `safe_actions` handlers to the real
   admin API (today they're stub callables that return dataclass
   instances). The HTTP plumbing belongs in a `versawiki_api_client/`
   module so the support agent does not depend directly on the API
   service's internals.
3. **M1-CS-04**: SMTP outbound for the email poller (today
   `EmailPoller` queues replies into `sent_replies` but does not send).
4. **M1-CS-05**: Slack / email backend for `Notifier` (today only the
   stub).
5. The web intake's in-memory `_THREADS` dict is process-local; behind
   a real load balancer we need conversation lookup via the store.
   Adequate for v1 but a known limit.

### What I did NOT touch

`services/api/`, `services/ingestion/`, `services/meta-mcp/`. Per the
ticket, this work was greenfield under `services/support-agent/`.
