# Landscape: file-storage-to-wiki and adjacent products

Ticket: **M0-03**. Status: **draft v1**, written 2026-05-22 by the Researcher.

Survey of products that take a customer's documents (or document-stores) and
produce a queryable knowledge surface — wiki, chat, "ask the corpus" — for
humans and increasingly for LLMs. Goal is to figure out where versawiki can
plant a flag.

Scope: I rated each product on five axes the brief asked about — **what it
ingests**, **how the wiki is structured** (templated vs emergent), **whether it
exposes an LLM-facing API or MCP**, **pricing**, **what reviewers complain
about**. Final section is "where versawiki can win."

---

## 1. Glean

- **Ingests.** 100+ enterprise connectors: Google Drive, Confluence, Notion,
  Dropbox, Gmail, Slack, Teams, Outlook, Zoom, GitHub/GitLab, Jira, Asana,
  Salesforce, Zendesk, etc. SaaS connector breadth is the headline feature.
  ([Glean Review 2026 — Fritz AI](https://fritz.ai/glean-review/),
  [QueryNow comparison](https://search.querynow.com/enterprise-search-pricing-comparison))
- **Structure.** Emergent. Glean does not produce a *wiki* per se — it produces
  a unified search/chat index across your existing SaaS surfaces, with
  personalization and citation. Closer to "federated enterprise search" than
  "wiki." ([Fritz AI review](https://fritz.ai/glean-review/))
- **LLM-facing surface.** Yes — Glean exposes API/agent endpoints and has been
  trending toward MCP-style integrations. ([CData — Enterprise-Ready MCP
  Adoption, 2026](https://www.cdata.com/blog/2026-year-enterprise-ready-mcp-adoption))
- **Pricing.** Per-seat, opaque, six-figure minimum. ~$50/user/mo base, +$15/user
  for advanced AI, ~100-seat minimum, ~$60k/year floor, fully loaded enterprise
  contracts $240k–$480k/year.
  ([GoSearch — Glean pricing](https://www.gosearch.ai/blog/glean-pricing-explained/),
  [Workativ TCO breakdown](https://workativ.com/ai-agent/blog/glean-pricing),
  [Vendr](https://www.vendr.com/marketplace/glean))
- **What reviewers complain about.** Price for what you get; opaque sales cycle;
  per-seat scaling punishes large orgs; you're paying for connector maintenance
  more than novel intelligence.
  ([Fritz AI](https://fritz.ai/glean-review/),
  [GoSearch FAQ](https://www.gosearch.ai/faqs/glean-enterprise-search-pricing-explained-costs-tiers-hidden-fees-gosearch-comparison/))

## 2. Mem.ai

- **Ingests.** Notes (typed in or pasted), meeting transcripts, some web
  capture. Not a general-purpose file-store connector — Mem is mostly
  what-you-type-in plus light integrations.
  ([Productivity Stack guide](https://productivitystack.io/guides/mem-ai-guide/))
- **Structure.** Emergent. LLM parses each "mem" into entities; auto-generated
  graph links; Heads-Up panel surfaces connections instead of folders.
  ([Productivity Stack](https://productivitystack.io/tools/mem/),
  [aicloudbase review](https://aicloudbase.com/tool/memai))
- **LLM surface.** Internal AI chat over the user's mems; no externally
  documented MCP server. ([Mem AI review — Saner.ai](https://blog.saner.ai/mem-ai-reviews/))
- **Pricing.** ~$12–15/user/mo. Single-user / small-team market.
  ([Saner.ai review](https://blog.saner.ai/mem-ai-reviews/))
- **What reviewers complain about.** No Android app, buggy tags, weak customer
  support, and the v1 → v2 transition lost data for some users. Tooling is
  thin for what's billed as a second-brain. ([India Online Mart
  review](https://indiaonlinemart.com/mem-ai-review-2026-is-the-self-organizing-workspace-still-king/),
  [Saner.ai](https://blog.saner.ai/mem-ai-reviews/))

## 3. Notion AI

- **Ingests.** Notion-native pages first; Enterprise Search add-on pulls from
  Slack, Google Drive, GitHub. Free tier has a 5 MB per-file cap; Plus removes
  it. ([Notion AI](https://www.notion.com/product/ai),
  [Aumiqx Notion pricing](https://aumiqx.com/ai-tools/notion-pricing-every-plan-explained-2026/))
- **Structure.** **Templated.** Users hand-build the wiki; AI helps query and
  generate inside it. Not corpus-driven structuring.
- **LLM surface.** Notion AI chat, no published MCP at time of writing. Custom
  Agents bill per-credit ($10 per 1,000 credits as of May 4 2026).
  ([Aumiqx](https://aumiqx.com/ai-tools/notion-pricing-every-plan-explained-2026/),
  [Felloai](https://felloai.com/notion-ai-pricing/))
- **Pricing.** Free / Plus $10/mo / Business $20/mo (only tier with full AI) /
  Enterprise custom.
  ([SmartProcessFlow](https://smartprocessflow.com/notion-pricing),
  [CheckThat.ai](https://checkthat.ai/brands/notion-labs-inc/pricing))
- **What reviewers complain about.** Forced bundling of AI into Business (you
  pay for it even if you use Claude/ChatGPT elsewhere); guest-to-member
  auto-conversion billing surprises; AI can't reach email/calendar.
  ([Aumiqx](https://aumiqx.com/ai-tools/notion-pricing-every-plan-explained-2026/),
  [Get-alfred](https://get-alfred.ai/blog/notion-pricing))

## 4. Sana

- **Ingests.** PDFs, Office docs, Google Workspace, CSV/Excel, MP4 video,
  CRM (Salesforce / HubSpot). Direct upload, private integration, or shared
  integration. ([Cybernews Sana review](https://cybernews.com/ai-tools/sana-ai-review/),
  [Applied AI Tools profile](https://appliedai.tools/product/sana-best-for-ai-enterprise-knowledge-management-and-training/))
- **Structure.** Two products: Sana Agents (AI Q&A over corpus, mostly
  emergent) and Sana Learn (templated curriculum / LMS).
  ([Sana product pages](https://sanalabs.com/products/sana/pricing))
- **LLM surface.** Sana Agents *is* the LLM-facing surface; model selection
  across OpenAI/Anthropic. No public MCP doc, but the architecture is
  agent-shaped.
  ([Sana agents blog](https://sanalabs.com/agents-blog/ai-tools-supercharge-business-tasks))
- **Pricing.** Sana Learn Core $13/license, 300-license minimum (~$3.9k/mo
  floor); Sana Agents enterprise quoted, opaque.
  ([Educate-Me](https://www.educate-me.co/blog/sana-labs-pricing),
  [Sana Learn pricing](https://sanalabs.com/products/sana-learn/pricing))
- **What reviewers complain about.** Expensive vs lighter alternatives; opaque
  enterprise pricing; LMS-and-search-bolted-together pitch confuses buyers.
  ([Capterra](https://www.capterra.com/p/239818/Sana/),
  [Techimply](https://www.techimply.com/profile/sana-labs))

## 5. Guru

- **Ingests.** Slack threads, web pages, Google Docs, Confluence, browser
  extension capture. Slack-native ingestion is the differentiator.
  ([Featurebase Guru pricing](https://www.featurebase.app/blog/guru-pricing),
  [Glitter "best Confluence alternatives" 2026](https://www.glitter.io/blog/knowledge-sharing/best-confluence-alternatives))
- **Structure.** Templated "cards" — short, verified knowledge units. Authors
  curate; system enforces re-verification cadence.
  ([Get Guru](https://www.getguru.com/pricing))
- **LLM surface.** **Has MCP.** Guru launched Knowledge Agents with MCP-server
  support in 2025 — explicitly to let outside AI tools pull from Guru's
  governed layer rather than rebuild permissions per tool.
  ([Featurebase analysis](https://www.featurebase.app/blog/guru-pricing))
- **Pricing.** Starter ~$10/user/mo (billed annually), 10-seat minimum;
  Knowledge Agents (MCP, AI chat) require Enterprise — custom, much higher.
  ([Get Guru pricing](https://www.getguru.com/pricing),
  [Featurebase pricing](https://www.featurebase.app/blog/guru-pricing))
- **What reviewers complain about.** Knowledge Agents gated behind Enterprise;
  notifications unreliable; per-seat scaling.
  ([Research.com](https://research.com/software/reviews/guru),
  [SelectHub](https://www.selecthub.com/p/knowledge-management-software/getguru/))

## 6. Coda (and Coda Brain)

- **Ingests.** Native docs first; Coda Brain enterprise tier indexes Slack,
  Google Drive, Jira inside a Coda doc.
  ([Coda AI review — CodaOne](https://www.codaone.ai/tools/coda-ai/),
  [ContentMation](https://contentmation.com/marketing-tools/coda-ai))
- **Structure.** Templated, but Coda's "doc-as-app" model lets users grow
  structure organically inside one doc. Not corpus-driven schema induction.
- **LLM surface.** Coda AI with AI Credits; no public MCP.
  ([AppSage Coda review](https://www.sollmannkann.com/project-management-and-notes/best-coda-review/))
- **Pricing.** Free / Pro $10 per Doc Maker / Team $30 per Doc Maker /
  Enterprise custom. **Maker-only billing** is genuinely differentiated — only
  authors pay, viewers free.
  ([Vendr](https://www.vendr.com/marketplace/coda),
  [CodaOne](https://www.codaone.ai/tools/coda-ai/))
- **What reviewers complain about.** Steep learning curve; AI Credits feel
  stingy on Pro; Coda Brain only shines at Enterprise.
  ([G2](https://www.g2.com/products/grammarly-coda/reviews),
  [BestAgentPick](https://bestagentpick.com/tools/coda-ai/))

## 7. Heyday

- **Ingests.** Browser tabs, emails, documents, meeting recordings (Zoom),
  notes. Passive capture of what the user already reads/writes.
  ([Heyday — Product Hunt](https://www.producthunt.com/products/heyday-2),
  [AIPortalX](https://aiportalx.com/tools/heyday))
- **Structure.** Emergent topic clusters; "Topic Assistant" resurfaces related
  past material when you're writing or browsing.
  ([Futurepedia](https://www.futurepedia.io/tool/heyday))
- **LLM surface.** Internal-only Heyday Copilot. No external MCP.
- **Pricing.** $40/mo or $299/yr. Individual product, not B2B.
  ([AIPortalX](https://aiportalx.com/tools/heyday))
- **What reviewers complain about.** Login reliability issues; price for a
  passive-capture tool; thin integration set vs Glean/Dash.
  ([G2](https://www.g2.com/products/heyday-ai/reviews),
  [Research.com](https://research.com/software/reviews/heyday-ai))

## 8. Akiflow

- **Ingests.** Tasks and calendar events from Asana, Todoist, Notion, Trello,
  Gmail, Slack, Outlook, Google Calendar.
  ([Akiflow — Efficient App](https://efficient.app/apps/akiflow),
  [GetApp](https://www.getapp.com/collaboration-software/a/akiflow/))
- **Structure.** **Not a wiki.** Universal task inbox + time-blocking calendar.
  Includes it here because Josh listed it; conclusion is that it's a task
  consolidator, not a knowledge tool.
- **LLM surface.** AI auto-tag for incoming tasks; no MCP.
- **Pricing.** ~$34/user/mo full plan.
  ([Saner.ai Akiflow review](https://blog.saner.ai/akiflow-reviews/))
- **What reviewers complain about.** Holds tasks but not the thinking behind
  them — exactly the gap a wiki would fill.
  ([Saner.ai](https://blog.saner.ai/akiflow-reviews/))

## 9. Dropbox Dash

- **Ingests.** Google Workspace, OneDrive, Notion, Asana, Slack, Dropbox
  itself. Positioned as "universal search across work tools."
  ([Dropbox Dash universal search](https://dash.dropbox.com/features/universal-search),
  [Dropbox press release](https://dropbox.gcs-web.com/news-releases/news-release-details/introducing-dropbox-dash-business-ai-powered-universal-search))
- **Structure.** No wiki — federated search + summary cards. Recently
  acquired Nira for content-governance overlay.
  ([Dropbox Dash AI info](https://dash.dropbox.com/ai-info-page))
- **LLM surface.** Internal AI summaries. No public MCP.
- **Pricing.** Rolling out by region; Business tier not yet widely public.
  ([Capterra Dash listing](https://www.capterra.com/p/10023732/Dropbox-Dash/))
- **What reviewers complain about.** Geographic patchiness; results sometimes
  miss recent files; overlap with whatever search the customer's existing
  apps already provide. ([G2 Dash reviews](https://www.g2.com/products/dropbox-dash/reviews))

## 10. Confluence AI / Atlassian Rovo

- **Ingests.** Confluence and Jira primarily; Rovo extends to ~80 apps in the
  Atlassian ecosystem (including Slack and Google Drive).
  ([eesel — top Confluence AI apps 2026](https://www.eesel.ai/blog/confluence-ai-apps),
  [Glitter — Confluence alternatives](https://www.glitter.io/blog/knowledge-sharing/best-confluence-alternatives))
- **Structure.** Templated wiki (the *original* enterprise wiki); AI added on
  top of human-authored pages.
- **LLM surface.** Rovo Agents; Atlassian is investing in MCP exposure but
  product is uneven. ([CData MCP 2026](https://www.cdata.com/blog/2026-year-enterprise-ready-mcp-adoption))
- **Pricing.** Bundled with Confluence/Jira tiers; Rovo per-user add-on.
- **What reviewers complain about.** Slow, heavyweight, sprawling UI; AI
  quality lags Notion AI and Glean.
  ([eesel](https://www.eesel.ai/blog/confluence-alternatives))

## 11. Onyx (formerly Danswer) — OSS

- **Ingests.** 40+ connectors (Drive, Confluence, Slack, Notion, GitHub,
  Salesforce, Zendesk, etc.) with permission inheritance from the source app.
  ([Onyx GitHub](https://github.com/onyx-dot-app/onyx),
  [Onyx — OpenWebUI alternatives](https://onyx.app/insights/openwebui-alternatives))
- **Structure.** Federated RAG, not wiki. Vector + keyword index, agent/chat
  surface on top. RBAC for sensitive resources.
- **LLM surface.** REST API, chat UI, agentic actions. MCP integration is on
  the roadmap per community posts but not core yet.
- **Pricing.** **MIT-licensed CE (free)** + Enterprise Edition for SSO, group
  sync, SCIM. Self-hostable. ([Onyx GitHub](https://github.com/onyx-dot-app/onyx))
- **What reviewers complain about.** Self-host complexity; classification &
  ontology of ingested content is shallow (mostly relies on raw embeddings);
  no "wiki view" — just chat. ([Seaflux](https://www.seaflux.tech/blogs/onyx-ai-enterprise-search-assistant/))

## 12. AnythingLLM — OSS

- **Ingests.** File upload, URLs, a handful of connectors per workspace.
  Workspace-scoped vs org-wide.
  ([DataCamp AnythingLLM guide](https://www.datacamp.com/blog/anythingllm))
- **Structure.** Chat over a workspace of files; no wiki. Multi-workspace
  isolation is real but lightweight.
- **LLM surface.** Local chat; OpenAI/Anthropic/Ollama; MCP server mode in
  recent versions. ([DataCamp](https://www.datacamp.com/blog/anythingllm))
- **Pricing.** MIT open source; Mintplex Labs sells a hosted tier.
- **What reviewers complain about.** Not enterprise-class; permission model is
  minimal; classification is BYO. ([Onyx vs AnythingLLM comparison](https://onyx.app/insights/openwebui-alternatives))

## 13. LLM-Wiki (Karpathy pattern + nashsu desktop)

- **Ingests.** A local folder of source documents (or a code repo, in the
  original Karpathy version).
  ([Karpathy LLM-wiki — Medium walkthrough](https://medium.com/@k.balu124/how-i-turned-andrej-karpathys-llm-wiki-into-a-tool-that-writes-wiki-s-from-code-cfb7f73afa52),
  [nashsu/llm_wiki on GitHub](https://github.com/nashsu/llm_wiki))
- **Structure.** **Emergent wiki built incrementally.** Instead of RAG-on-demand,
  the LLM maintains a persistent wiki that the user (or LLM) reads back.
  Pre-compiled artefact, not on-the-fly retrieval. **Closest existing concept
  to versawiki.**
- **LLM surface.** None standardized — the wiki *is* the artefact.
- **Pricing.** Open source.
- **What reviewers complain about.** Solo-dev / hobbyist scope; no
  multi-tenant story; no MCP; freshness logic is brittle; no connector to
  cloud file stores. ([Dreamwalker — what is an LLM wiki](https://medium.com/@aristojeff/what-is-an-llm-wiki-and-why-are-people-paying-attention-to-it-b7e10617967d))

---

## Summary table

| Product | Ingests | Wiki structure | MCP / LLM API | Price floor | Biggest gap for versawiki to exploit |
|---|---|---|---|---|---|
| Glean | SaaS connectors (100+) | Emergent search index, no wiki view | Yes-ish | ~$60k/yr | Price; not a *wiki*; no per-customer MCP |
| Mem | Typed notes + capture | Emergent graph | No | ~$15/mo | No file-store ingestion; no MCP |
| Notion AI | Notion pages + 3 connectors | Templated | No public MCP | $20/seat/mo | Hand-built wiki; AI bolted on |
| Sana | Files + CRM + video | Mixed (Agents emergent, Learn templated) | Agents API | ~$3.9k/mo | Price; no MCP; muddied positioning |
| Guru | Slack + Google Docs + browser cards | Templated cards | **Yes — MCP** | ~$100/mo per 10 seats; MCP requires Enterprise | MCP gated behind Enterprise; templated |
| Coda | Native docs + Brain enterprise | Templated docs | No MCP | $30 per Doc Maker | Not corpus-driven; templated |
| Heyday | Passive capture | Emergent | No | $40/mo | Individual product; no MCP |
| Akiflow | Tasks/calendar only | n/a (not a wiki) | No | $34/mo | Out of scope |
| Dropbox Dash | Files + work apps | None — search | No public MCP | rolling | No wiki; no MCP |
| Confluence/Rovo | Atlassian + Slack/Drive | Templated wiki | Emerging | Confluence pricing | Templated; slow AI |
| Onyx (OSS) | 40+ connectors | Federated RAG | API; MCP coming | Free / self-host | No wiki view; shallow ontology; permissions hard to expose |
| AnythingLLM (OSS) | File upload, URLs | Workspaces | Local MCP mode | Free | Small-scale; no enterprise model |
| LLM-Wiki | Local folder / repo | **Emergent wiki** | None | Free | Solo-dev; no multi-tenant, no MCP, no cloud connectors |

---

## Cross-cutting observations

1. **Almost nobody builds an actual wiki anymore.** The category bifurcated into
   (a) **federated search/chat** over the customer's existing apps (Glean,
   Dash, Onyx) and (b) **hand-authored wikis with AI bolted on** (Notion,
   Confluence, Coda, Guru). The versawiki pitch — *the wiki structures
   itself from a customer's documents* — is genuinely uncrowded. The closest
   neighbour is the niche **LLM-Wiki** OSS project, which is single-user.

2. **MCP exposure is rare and gated.** Guru is the only consumer-facing
   product that has shipped MCP, and it's locked behind Enterprise pricing.
   Onyx's MCP is community-driven and experimental. **Per-tenant MCP as a
   first-class product surface is open ground.**

3. **Connector breadth ≠ structuring quality.** Glean wins on
   connector count but doesn't reorganize the corpus — it indexes it.
   Customers complain that Glean's "answers" still feel like 10-blue-links
   plus a paragraph. Versawiki promising *actual structure* (categories, type
   inference, cross-links the source apps don't have) is a believable
   differentiator if the ontology induction holds up (see `ontology.md`).

4. **Pricing models punish viewers.** Glean/Sana/Guru per-seat scaling is
   widely resented; Coda's maker-only billing is the most-praised pricing
   model in the comparison. For a wiki that's mostly *read* by humans and
   *queried* by LLMs, billing per-document-author or per-MCP-query may be
   more defensible than per-user.

5. **Self-hosting matters in regulated verticals.** Onyx and AnythingLLM
   exist because Glean's data-residency story is mid-acceptable at best.
   Versawiki should keep "the desktop / on-prem variant runs the same code"
   on the roadmap (M3 already does).

---

## Where versawiki can win

Pulling the above into a short list of defensible angles, ranked by my read
on how hard each is to copy:

1. **Per-tenant MCP as the headline LLM surface.** Sell the MCP, not a chat
   UI. Every other vendor is building an opinionated chat UI; versawiki's
   asymmetric bet is that customers' LLMs *already exist* (Claude, ChatGPT,
   Cursor, Copilot) and what they need is a *cheap, governed, per-tenant
   context endpoint*. Guru has proven enterprises will pay for this; nobody
   has unbundled it from the templated-wiki UI yet.

2. **Emergent, corpus-driven ontology — not a template.** The category's
   wiki-shaped products (Notion, Confluence, Coda) all hand the customer a
   blank canvas. The category's search-shaped products (Glean, Dash, Onyx)
   don't structure anything. Versawiki sits in the gap: *the structure comes
   from the documents, refined by the queries.* See `ontology.md` for the
   technical approach.

3. **Cross-customer "shape" learning (the meta-MCP).** A novel surface area:
   *learn the shape of a vertical's wiki without sharing the bytes.* Guru
   doesn't do this. Glean's personalization is per-user, not cross-tenant.
   This is a moat that compounds with each new vertical onboarded, and the
   privacy story ("we share shapes, not content") is enforceable and
   marketable.

4. **Local-first, then connectors.** Most competitors are connector-first
   and lose every customer who can't ship documents to a SaaS. Onyx and
   AnythingLLM eat that market today. Starting at local folder (M1) lets
   versawiki land regulated and security-paranoid customers that Glean
   can't touch, while still scaling to Drive/OneDrive when M2+ ships.

5. **Pricing model.** Per-MCP-query + per-document-author, not per-seat.
   Aligns cost to actual value (LLM context calls, corpus growth) and
   neutralises the "we have a thousand read-only employees" objection that
   sinks Glean deals.

6. **Open source the ingestion + ontology core; close the meta-MCP and the
   hosted SaaS.** This is the Onyx/AnythingLLM playbook in reverse — let
   the local-folder path be reproducible by anyone, charge for the hosted
   multi-tenant pieces and the cross-customer learning. Builds developer
   mindshare in the verticals where Onyx is currently the default.

The riskiest of these is (3) — the meta-MCP. If it doesn't actually learn
anything useful in the first two domains we attempt, the differentiation
collapses to (1) + (2), which is still a defensible position but a less
exciting one. Flagged in `notes/researcher.md`.
