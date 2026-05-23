# Customer support strategy — no-humans MVP

**Goal:** Customer support runs without human staff for at least the 0-100 customer phase. Realistic interpretation: the agent handles 80-95% of inbound; escalations land in a queue you review when convenient. No human is *waiting on tickets*; you're reviewing batches on your schedule.

**Status:** v1 agent shipped at `services/support-agent/` with 62 passing tests. See its `notes/support-agent.md` for what's built and what's stubbed.

## The "no humans" budget

Even in the most aggressive automation posture, you'll have these residual human touchpoints:

| Category | Why it can't be fully automated | Volume estimate |
|---|---|---|
| Security incidents | Legal + customer trust require a real person's signature | 0-1/month at 100 customers |
| Refund / credit requests | Financial authority is yours | ~2% of customers/month |
| Account deletion (GDPR/CCPA) | Compliance audit trail | ~0.5%/month |
| Press / partnership inquiries | These are sales calls in disguise | ~5/month |
| Enterprise SLA breaches | Custom contracts mean custom handling | 0 until you sell enterprise |

Realistic: ~10-20 human-touched escalations per month at the 100-customer scale, each taking 5-30 minutes. Maybe 5 hours total. Doable on Sunday morning with coffee.

## The agent we built

`services/support-agent/` is a Python service with:

- **Conversation model** (channel: email/web/api, status: open/resolved/escalated/awaiting_customer)
- **Knowledge base** (markdown files in `services/support-agent/kb/`, hot-reloadable)
- **Safe actions** the agent can take autonomously
- **Forbidden actions** that always refuse and escalate
- **PII redaction** at message-write time so logs don't contain raw cards / SSNs
- **Cross-tenant blocker** — verified by `test_agent_cross_tenant_block.py`

## What's missing for production

The v1 is structurally complete but the surface is stubbed in a few places:

1. **Structured Anthropic tool-use** (M1-CS-02) — current LLM path parses text-formatted tool calls; the SDK supports a native tool-use loop that's more reliable. Couple hours of refactor.
2. **Real admin API wiring** (M1-CS-03) — `lookup_tenant_status` etc. currently hit stubs. Need to point them at the real BE-03 admin endpoints, with a service-token (separate from any tenant's key).
3. **SMTP outbound** (M1-CS-04) — agent currently composes replies but doesn't send them. Wire to Postmark / SendGrid / AWS SES.
4. **Notifier** (M1-CS-05) — escalations land in a JSONL file. Need to push to Slack / Telegram / email when something escalates.
5. **Web chat widget** (M1-CS-06) — the FastAPI endpoint exists; needs a JS widget for the marketing site. Tiny React component (~200 lines).

Estimate: 2-3 days of focused work to make this production-grade.

## Channel strategy

### Email (primary at launch)

- `support@versawiki.com` routes via Cloudflare Email Routing → an inbox the agent polls
- Agent processes within ~1 minute of arrival
- Reply goes back from `support@versawiki.com` via SMTP (Postmark recommended for transactional)
- Each conversation gets a `[#vw-<id>]` token in the subject so threading works

### In-app chat (when web app ships)

- Widget loads on every page of the customer's signed-in app + marketing site
- Conversations sync with the email channel (same conversation, two surfaces)
- Real-time replies (websocket; the FastAPI endpoint already supports it)

### API channel (for programmatic / partner integrations)

- `POST https://support.versawiki.com/v1/messages` with API key
- Same agent, same escalation rules
- Useful for partners who want to embed versawiki support in their own apps

### What we explicitly DON'T support at launch

- Phone support — not at 100 customers; reconsider at 1000
- Live human chat — that's the entire thing we're not building
- 24/7 SLA — explicit in your terms: "best-effort during business hours; agent available 24/7 for triage"

## Escalation routing

| Trigger | Where it goes | Your SLA to yourself |
|---|---|---|
| Security incident keyword (`breach`, `leak`, `compromise`, `lawyer`) | Email to your phone + Slack/Telegram instant | 1 hour |
| Refund request | Daily-batch escalation queue | 24 hours |
| Account deletion (GDPR/CCPA) | Daily-batch + compliance log | 30 days legal limit; 7-day target |
| Agent confidence < 0.7 for 3 turns | Daily-batch escalation queue | 48 hours |
| Same customer escalates twice in 30 days | Tagged as "VIP" — agent's tone shifts to extra-careful + flag for personal touch | Next escalation gets your direct reply |

## The "no humans" trust problem

Customers will figure out it's an LLM. Two postures:

**Hide it:** Agent says "I'm Sam from support" and never admits otherwise. Risks: customer feels gaslit when they catch on (they always catch on); legal risk in some jurisdictions; brand trust damage.

**Own it:** Agent's first message: "Hi, I'm versawiki's support assistant. I can help with most questions on the spot. For anything I can't resolve, I'll bring in our team — usually within 24 hours." Sets expectations; lets the agent be excellent at what it's excellent at; reduces customer frustration when escalation IS needed.

Recommended: **own it.** It matches your privacy-first positioning (we tell customers exactly what's happening with their data).

## Cost model

Per-conversation cost (Sonnet 4.6, 5 turns averaging 1500 input + 400 output tokens each):

- Per turn: ~$0.012 input + $0.020 output = $0.032
- Per 5-turn conversation: ~$0.16
- At 200 conversations/month (100 customers, 2 per): $32/month
- At 2000 conversations/month (1000 customers, 2 per): $320/month

Plus the per-tenant-per-month embedding + RAG cost for KB lookups: negligible (~$5/month at this scale).

Plus the inbox infrastructure (Postmark): $15/month for 10k emails.

**Total support cost at 100 customers: ~$60/month** vs. one human support person at $50k/year = $4200/month. The agent pays for itself at customer #1.

## Privacy posture in support

The support agent is subject to the same content-vs-pattern boundary as the rest of the product. Specifically:

- The agent's prompts may include the customer's account state (tenant ID, plan, key prefix) — never their content
- The agent's conversation logs are stored in the customer's tenant schema, not in a global support DB
- The agent never reads from one tenant's data when serving another (the cross-tenant test enforces this)
- The agent's training data (KB articles) contains no tenant content — those are written by humans (you) for general use

## What to do before launch

1. Wire the SMTP outbound (M1-CS-04) — without this the agent reads but doesn't reply
2. Wire the notifier (M1-CS-05) — without this you miss escalations
3. Wire the admin API (M1-CS-03) — without this the agent's actions are pretend
4. Build the web widget (M1-CS-06) — useful but skippable for email-only launch
5. Set up Postmark account + DNS records (SPF, DKIM, DMARC for versawiki.com)
6. Write 5-10 more KB articles based on questions you anticipate from the first 10 customers
7. Build the escalation review UI — a tiny page that shows the queue and lets you reply / close / mark VIP

## When to revisit "no humans"

The strategy holds until one of:

- Customer volume passes ~1000 — escalation rate × volume puts you over your time budget
- You sell to an enterprise customer who contractually requires human support
- A security incident makes the LLM-only model look bad in retrospect

At that point: hire one part-time support person ($30-50k/yr), have them handle escalations + KB authoring, agent still handles 80%+. This is the model Intercom Fin's enterprise customers use.
