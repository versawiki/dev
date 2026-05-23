---
name: Privacy
tags: [privacy, security, data, gdpr, opt-out, retention, boundary]
last_reviewed: 2026-05-23
---

# Privacy

## The short version

**Your content stays in your tenant.** The shapes versawiki learns
from working with your data may help us improve the product for the
next customer in a similar domain. You can opt out of even that.

## The content-vs-pattern boundary

Versawiki has a shared meta-MCP that learns across customers. The
boundary is precise:

**MUST NOT cross your tenant boundary** (treated as your property):

- Your file names, document content excerpts, customer-specific names
- Numbers from your data (quantities, prices, counts)
- Quotes, verbatim or near-verbatim
- Any string a human could recognise as belonging to your company

**MAY cross** (treated as generally applicable knowledge):

- Naming conventions and syntax patterns ("PDFs in this domain often
  start with a project number")
- Organisational structures ("a contract usually has parties, term,
  termination clauses")
- Data relationships ("invoices reference purchase orders")
- Procedures ("ingest spec sheets before drawings to seed the
  vocabulary")

The team's working text for this is in `DECISIONS.md` (2026-05-22
"Meta-MCP cross-tenant boundary"). The agent is bound by the same
rule when it answers your questions.

## Opt-out

Set the opt-out flag in **Settings → Privacy**. With opt-out on, no
DomainObservation events are emitted from your tenant at all — the
meta-MCP cannot learn anything from your data, even patterns.

## Retention

Default: indefinite while you remain a customer. You can configure a
shorter retention from **Settings → Privacy → Retention**. We do not
keep your data after account closure (the tenant schema is dropped on
deletion).

## What support can do

The agent can answer privacy questions and tell you how to set the
opt-out or retention. Changing those settings is gated to humans
(it's on the agent's hard-NO list) because the call has high
reversibility cost — we want it on Josh's desk, not the bot's.

## What support cannot do

- Reveal another tenant's data
- Disclose the names of customers in any domain
- Decrypt or expose raw stored data on request — exports go through
  the admin UI's data-export flow, not chat
