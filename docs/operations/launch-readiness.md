# Launch readiness checklist

**Goal:** Get from "code works in sandbox" to "first paying customer can sign up safely." Ordered by deadline (= longest lead time first).

**Bottom line up front:**
- Long-lead items (Apple Developer, LLC filing, code signing) — **start this week**
- Infrastructure (Fly.io, Neon, R2, Cloudflare) — **start when M1 code-complete**
- Legal docs (privacy policy, ToS, DPA) — **needed before first paying customer**

## Tier 1: Start this week (long lead times)

| Item | Cost | Lead time | Notes |
|---|---|---|---|
| Apple Developer Program | $99/yr | 1-2 days (can be 2 weeks) | Required for Mac signing AND iOS app. Sign up at developer.apple.com/programs/ |
| Google Play Console | $25 one-time | Same day | play.google.com/console |
| Reserve `versawiki` app name on both stores | Included | Now | Do it as soon as accounts approve |
| Cloudflare migration | Free | 1-24 hrs propagation | See `dns-cloudflare-migration.md` |
| LLC decision + filing | $50-500 + $500 if Stripe Atlas | 1-2 weeks | See `llc-and-business.md`; do this BEFORE you accept a paying customer |
| Mercury or Brex bank account | Free | 1-3 days after LLC formed | Mercury opens fast; Brex slightly more enterprise-y |
| EIN from IRS | Free | 10 minutes | irs.gov, online, US-only. Do AFTER LLC is filed. |
| Pick a registered agent | $50-200/yr | 1 day | Stripe Atlas includes one; otherwise Northwest Registered Agent ($125/yr) |
| Cyber liability insurance quote | $500-2k/yr | 1-2 weeks | Vouch or Embroker are startup-friendly. Get the quote now; don't buy until first customer. |

## Tier 2: Start when M1 code-complete (~1 week from now)

| Item | Cost | Lead time | Notes |
|---|---|---|---|
| Fly.io account + first deploy | Free tier + ~$30/mo for prod-shaped | 1 day | fly.io. Per the stack decision in DECISIONS.md. |
| Neon account + production DB | Free tier + ~$20/mo for paid | 1 day | neon.tech. Per-tenant branchable. |
| Cloudflare R2 bucket for document blobs | $0.015/GB/mo | 1 hour | Already have CF account from Tier 1. |
| OpenAI API key (production-tier) | Pay-as-you-go | Same day | platform.openai.com. Embeddings: text-embedding-3-large @ 1024 dim. |
| Anthropic API key (production-tier) | Pay-as-you-go | Same day | console.anthropic.com. Already have for orchestrator. |
| GitHub branch protection on `main` | Free | 5 min | Required for the Agent SDK orchestrator's branch-only model. |
| GitHub Actions for CI (run test suite) | Free (public repo) | 1 hour | First yaml is in the agent-sdk-spec.md follow-up. |
| Stripe account for billing | Free until first charge | 1-2 days verification | stripe.com/atlas if you went that route; otherwise direct signup. |
| Domain email (support@, hello@, josh@) | Free via CF Email Routing | Done in CF migration | Or upgrade to Google Workspace $6/seat/mo when you want sending too. |

## Tier 3: Before first paying customer

| Item | Cost | Lead time | Notes |
|---|---|---|---|
| Privacy policy | $0-1k (template vs lawyer) | 1-2 days | Termly.com generates a passable starter; have a real lawyer review before SOC2 or enterprise sales. The content-vs-pattern boundary needs to be explicitly in this doc. |
| Terms of service | Same as above | Same | |
| DPA template (Data Processing Agreement) | $500-2k | 1-2 weeks if lawyer | GDPR + (eventually) US state privacy laws require this for B2B. Iubenda has a passable generator. |
| Cookie policy + banner | Free | 1 day | Cookiebot or Termly free tier. |
| SOC2 readiness (Type 1) | $15-40k all-in | 2-4 months | NOT needed for first ten customers. Required by most enterprise customers. Vanta or Drata can shortcut this. |
| Incident response runbook | $0 | 1 day | Internal doc; required before you have customers because if there's ever a breach you need a plan that already exists. |
| Status page | $0 (free tier) | 1 day | statuspage.io, instatus, or a simple Cloudflare Workers page. |
| First customer onboarding doc | $0 | 1 day | docs.versawiki.com or a Notion page. |

## Tier 4: Before public launch

| Item | Cost | Notes |
|---|---|---|
| Marketing site (versawiki.com) | $0 (you build) | Next.js per the stack |
| Product Hunt launch prep | $0 | If that's your channel |
| Pricing page | $0 | The pricing landscape research in `docs/research/landscape.md` already informs this |
| Analytics | Free tier | Plausible or PostHog (privacy-respecting; matches our positioning) |
| Error monitoring | Free tier | Sentry. Required for production. |
| Customer support routing | Built! | The `services/support-agent/` we just shipped handles inbound. |

## What you DON'T need right now

- Equity / cap table tooling (Carta) — not until you have a co-founder or investor
- Payroll provider (Gusto, Rippling) — not until you have employees
- HR tooling — same
- Sales CRM (Hubspot, Pipedrive) — not until you have a sales pipeline
- Vendor management software — way too early
- Office space / coworking — unless you specifically want to
- Trademark filing for "versawiki" — useful but $250+/class and not blocking; do it after the LLC is set up

## Critical-path order for the next 30 days

1. **Today/tomorrow:** Apple Developer signup, Google Play signup, Cloudflare migration
2. **This week:** LLC filing (Stripe Atlas or direct), Mercury bank account application
3. **Next week:** Finish M1 with me, set up Fly.io / Neon / OpenAI / Anthropic accounts, deploy a staging environment
4. **Week 3:** Privacy policy + ToS draft, status page, error monitoring
5. **Week 4:** First customer onboarding (could be you using versawiki on your own documents — the most credible first customer)
