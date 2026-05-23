# versawiki-support-agent

Autonomous customer-support agent for versawiki. Ticket: **M1-CS-01**.

The agent's purpose is to handle 80%+ of routine customer inquiries directly,
gather context on the rest, and escalate only clearly-flagged exceptions to a
review queue. Josh's stated goal: "this company will run without humans."

## What this is

A small Python service that:

1. Accepts messages over multiple **channels** (email IMAP poller, web POST,
   API). See `src/versawiki_support/intake/`.
2. Maintains a **`Conversation`** per customer thread with role-tagged
   `Message`s. See `conversation.py`, `messages.py`.
3. Hydrates context from a **markdown `KnowledgeBase`** (`kb/*.md`, hot-reloadable
   on mtime) and current tenant state via the versawiki admin API.
4. Calls Claude (`AnthropicSupport` over `claude-sonnet-4-6`) with the
   conversation, KB matches, the **safe-actions list**, the **hard-NO list**,
   and the escalation criteria.
5. Parses any tool call the LLM emits, **gates** it against the safe-actions
   allowlist (and refuses anything on the forbidden list), and either executes
   it or refuses + escalates.
6. Stores the resulting conversation (v1 = JSONL; production = Postgres tenant
   schema).

## Privacy boundary

The support agent is bound by the same content-vs-pattern rule as the meta-MCP
(see `DECISIONS.md` 2026-05-22). It NEVER reveals:

- API key hashes or raw tokens (only prefixes)
- Other tenants' data (cross-tenant lookups are blocked)
- Internal infrastructure details (DB schemas, server IPs)

A PII redactor rewrites credit-card numbers and similar high-risk strings in
inbound customer messages before they are persisted.

## Default posture: refuse + escalate

When the LLM's confidence is below 0.7, or when any uncertainty exists about
authorisation, the agent **refuses and escalates** rather than guessing. The
escalation queue lives under `escalations/<date>/<conversation_id>.json` and
Josh reads it on demand.

## Layout

```
src/versawiki_support/
  conversation.py        # Conversation domain model
  messages.py            # Message model + PII redactor
  knowledge_base.py      # markdown KB loader, hot-reload on mtime
  safe_actions.py        # allow-list of actions + per-action gates
  forbidden_actions.py   # hard NO list
  llm.py                 # SupportLLM Protocol + StubSupportLLM + AnthropicSupport
  agent.py               # SupportAgent.handle_message()
  storage.py             # Conversation persistence (JSONL today)
  intake/
    email.py             # IMAP poller
    web.py               # FastAPI POST /support/web/messages
    api.py               # Same, programmatic
  escalation/
    queue.py             # append-only queue of escalations
    notify.py            # Slack/email notifier stub
kb/
  getting-started.md
  api-keys.md
  ingestion.md
  privacy.md
  billing.md
  troubleshooting.md
  escalation-criteria.md
tests/
  test_kb_loader.py
  test_safe_actions.py
  test_forbidden_actions.py
  test_agent_happy_path.py
  test_agent_escalation.py
  test_agent_cross_tenant_block.py
  test_agent_pii_redaction.py
  test_intake_email.py
  test_intake_web.py
  test_escalation_queue.py
```

## Running tests

```
cd services/support-agent
PYTHONPATH=src PYTHONPYCACHEPREFIX=/tmp/vwpyc PYTHONDONTWRITEBYTECODE=1 \
  python -m pytest -q tests/
```
