---
name: Escalation criteria
tags: [escalation, refund, security, fraud, deletion, confidence]
last_reviewed: 2026-05-23
---

# When the agent escalates

The agent's default posture is **refuse + escalate** on any
uncertainty above the threshold. Specifically, the agent escalates
when:

## Always escalate

- **Security incidents** — suspected key leak, suspicious access
  patterns, anything that smells like compromise. Severity = high.
- **Suspected fraud** — odd payment patterns, signup bursts from one
  source, anything Josh would want to see today. Severity = high.
- **Refund or credit requests** — billing is human-only. Severity =
  medium.
- **Account deletion** — destructive, irreversible. Severity = high.
- **Privacy-setting changes** — opt-out flag, retention. Severity =
  high (reversibility cost is real).
- **Cross-tenant questions** — the agent refuses and **silently**
  audit-logs the attempt; it does NOT escalate (escalating would
  leak the other tenant's existence).
- **Anything on the hard-NO list** (see `forbidden_actions.py`) —
  severity inherited from the entry.

## Escalate on uncertainty

- The agent's confidence is **below 0.7** for the planned reply.
- A safe-action handler raises an exception we can't classify.
- The KB has zero good matches AND the customer's question doesn't
  match any pre-handled small-talk pattern.

## What goes into the escalation entry

- `conversation_id`
- `tenant_id` (or null for prospect/free)
- `channel`
- `reason` (short string)
- `severity` (low/medium/high/critical)
- `customer_identifier` (so the reviewer knows who to call)
- `last_messages` (up to 5, redacted)

Escalations land in `escalations/<date>/<conversation_id>.json`,
append-only. Prior entries are never rewritten — a second escalation
on the same conversation in the same day gets a `.2.json` suffix.

## What the agent does NOT do on escalation

- Promise the customer a specific resolution
- Promise a specific human will respond
- Promise a specific timeline beyond the billing-KB's "within 24
  hours"

The agent says, in effect: "I'm passing this to a teammate who will
follow up." That's the SLA the agent is authorised to make.
