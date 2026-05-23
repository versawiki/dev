# Versawiki Always-On Orchestrator — Claude Agent SDK Spec

**Audience:** Josh, and the person (you, a contractor, or a future engineer hire) who will deploy this.

**Goal:** Replace the 4-hour Cowork cron with an always-on orchestrator that runs on a server you control. Closer to "agent as a service" than "scheduled job."

## Why move off the Cowork cron

| Cowork cron | Always-on SDK |
|---|---|
| Only fires when the Cowork app is open on Josh's machine | Runs 24/7 regardless |
| Single ticket per fire, no chain | Can hold state across fires; chain dependent tickets |
| Every 4 hours | Event-driven (seconds) or short-tick (minutes) |
| Cost: $5-20/night | Cost: $50-300/day depending on activity |
| Risk: low (limited blast radius) | Risk: real — needs guardrails |

## Architecture

A long-running Python service on Josh's GCP VM (the same one running the `project-docs-*` MCPs at 35.226.25.117). Probably its own systemd unit, or its own Docker container sharing the network with the existing MCP stack.

```
                  +-----------------------------+
                  |       GCP VM (existing)     |
                  |                             |
                  |  +-----------------------+  |
                  |  | versawiki-orchestrator|  |
                  |  |   (this service)      |  |
                  |  |                       |  |
GitHub webhook -->|  | event_watcher.py      |  |
Postgres LISTEN ->|  |    + tick scheduler   |  |
                  |  |          |            |  |
                  |  |          v            |  |
                  |  |   agent_runner.py     |  |
                  |  |   (Claude Agent SDK)  |  |
                  |  |          |            |  |
                  |  |          v            |  |
                  |  |   github_pr_writer.py |  |
                  |  +-----------+-----------+  |
                  |              |              |
                  |  +-----------v-----------+  |
                  |  |  audit_log (Postgres) |  |
                  |  +-----------------------+  |
                  +-----------------------------+
```

## Components

### 1. `event_watcher.py` — The trigger surface

Long-running coroutine. Subscribes to:

- **GitHub webhooks** (via a small FastAPI endpoint at `https://orchestrator.versawiki.io/hooks/github`):
  - Push to `main` → consider rebuilding skill libraries
  - New issue tagged `[overnight]` → spawn an agent run for it
  - PR opened by external contributor → run review agent
- **Postgres LISTEN/NOTIFY** on the meta-MCP store: new `DomainObservation` events crossing a learning threshold → spawn a skill-write run
- **Cron tick** (every 5 minutes) → re-read STATUS.md, pick next Ready ticket if nothing else is happening
- **HTTP control endpoint** at `/control/pause` (Josh from his phone) and `/control/resume`

Emits `OrchestratorEvent` objects to a single in-process channel.

### 2. `agent_runner.py` — The Claude Agent SDK loop

```python
from anthropic.agent_sdk import Agent  # speculative import path; check docs

class VersawikiOrchestrator:
    def __init__(self, repo_path: Path, *, model: str = "claude-sonnet-4-6"):
        self.agent = Agent(
            model=model,
            system_prompt=ORCHESTRATOR_SYSTEM_PROMPT,  # ~the prompt in the cron today
            tools=[
                BashTool(allowed_cwd=repo_path),
                FileTools(root=repo_path),
                GitTool(repo_path, push_strategy="branch_only_pr_required"),
                GitHubTool(api_token=os.environ["GH_PAT"]),
                SpawnSpecialistTool(),  # spawns a sub-agent inline
            ],
            max_thinking_tokens=10000,
            spend_cap_usd_per_run=5,  # hard limit per task
        )

    async def handle(self, event: OrchestratorEvent) -> AgentResult:
        async with self.agent.session() as sess:
            return await sess.run(event.to_prompt())
```

The SDK handles the tool-call loop internally. Each run produces an `AgentResult` with `tokens_used`, `tools_invoked`, `commit_sha` (if any), `pr_url` (if any), and `escalation_notes`.

### 3. `github_pr_writer.py` — Never push to main

The single most important safety rule: the agent works on `vw-agent/<ticket-id>` branches and opens PRs via the GitHub API. Josh reviews on his phone and merges. The orchestrator never has push access to `main`. CI runs the test suite as a required check.

Branch protection on `main` set via the GitHub API at orchestrator startup:

```python
gh.repos.update_branch_protection(
    owner="versawiki", repo="dev", branch="main",
    required_status_checks={"strict": True, "contexts": ["ci/tests"]},
    enforce_admins=True,
    required_pull_request_reviews={"required_approving_review_count": 1},
    restrictions=None,
)
```

### 4. `audit_log.py` — Tamper-resistant log

Every event, every agent decision, every tool call, every spend, into Postgres (the same instance the MCP stack already runs). Append-only via a per-row hash chain so tampering is detectable. Queryable via a tiny admin UI Josh can hit from his phone.

### 5. `spending_cap.py`

Daily, weekly, monthly caps. When the daily cap is hit, the orchestrator pauses and emails Josh. Set conservatively at first ($50/day).

### 6. `control_api.py` — Phone-friendly control

Tiny FastAPI app:

- `POST /control/pause` (auth: bearer token in env) — orchestrator finishes the current event then idles
- `POST /control/resume`
- `GET /control/status` — current run, last 10 PRs, spend today, queue depth
- `POST /control/kill-current-run` — for runaway runs

## Deployment

### Option A: systemd on the existing VM

```ini
# /etc/systemd/system/versawiki-orchestrator.service
[Unit]
Description=Versawiki Orchestrator (Claude Agent SDK)
After=network.target docker.service

[Service]
Type=simple
User=versawiki
WorkingDirectory=/opt/versawiki/orchestrator
Environment=ANTHROPIC_API_KEY=/run/secrets/anthropic
Environment=GH_PAT=/run/secrets/github
EnvironmentFile=/etc/versawiki/orchestrator.env
ExecStart=/usr/bin/python3 -m versawiki_orchestrator.main
Restart=on-failure
RestartSec=10s

[Install]
WantedBy=multi-user.target
```

### Option B: Docker container alongside existing MCPs

Add to existing docker-compose.yml on the VM. Easier if the MCP stack already uses compose.

## Estimated effort to deploy

| Task | Hours |
|---|---|
| Write orchestrator script (this spec → working code) | 8 |
| GCP secrets manager wiring + env file | 1 |
| systemd unit + first-run shakedown | 2 |
| GitHub branch protection + PAT setup | 1 |
| Webhook endpoint + Cloudflare/nginx proxy | 2 |
| Audit log Postgres tables + admin UI sketch | 4 |
| Soak test (24 hours with $20 cap) | 24 |
| **Total** | **~3 working days** |

## Cost model

| Activity | Tokens/day | Cost (Sonnet) | Cost (Opus) |
|---|---|---|---|
| 1 ticket-driven run / hour | ~200k | $4 | $30 |
| Plus 6 large refactors / week | +400k | +$8 | +$60 |
| Plus 24/7 ambient health-check polling | +50k | +$1 | +$8 |
| **Daily expected** | | **~$13** | **~$100** |

Recommend starting with Sonnet 4.6, escalating to Opus only for tickets the orchestrator explicitly flags as "needs reasoning depth."

## Migration plan from current cron

1. Build + deploy the orchestrator in **observation-only mode** for 48 hours. It watches events but emits to a log instead of acting.
2. Compare its proposed actions to what the Cowork cron actually did. Tune the prompts.
3. Flip to **action mode with hard caps** ($20/day, branch-only).
4. Cowork cron stays running as a fallback for the first week.
5. After a week of clean autonomous behavior, retire the Cowork cron.

## Open questions for Josh

1. Run Sonnet 4.6 or Opus by default?
2. What's the daily spend cap you're comfortable with? ($20 starts conservative.)
3. Email or Slack for escalation notifications?
4. Want a Telegram / SMS notification channel for "agent paused itself" alerts?
