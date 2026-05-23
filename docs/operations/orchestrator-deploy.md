# versawiki-orchestrator — VM deploy walkthrough

**Audience:** Josh, deploying onto the existing GCP VM at `35.226.25.117` that's already running the project-docs-* / renewable-knowledge MCPs.

**What you'll have at the end:** a containerised long-running orchestrator listening on `127.0.0.1:8088/control/*`, running in **observe mode** (no PRs opened), recording every decision to a SQLite audit log on a Docker volume. After 48 hours of clean observation you flip `VW_ORCH_MODE=observe` → `act` and it starts actually opening PRs against `versawiki/dev`.

Total wall-clock time, assuming the VM has Docker + a Compose stack already: about **30 minutes** of paste-and-wait. Most of that is the first Docker build.

## Prerequisites (one-time, mostly already done)

- The GCP VM at `35.226.25.117` exists and has Docker / Compose. (✓ — `domain-expert-mcps` skill confirms.)
- You have a personal-access token for `versawiki` on GitHub with `repo` + `workflow` scopes (we'll generate this fresh today).
- You have an Anthropic API key with billing enabled. (✓ — already on disk as `.vw-anthropic-key` for the cron.)
- A working SMTP provider for escalation emails. Recommended: Resend's free tier (`smtp.resend.com:587`, single API key) — sign up takes 3 minutes.

## Step 0 — Land this PR

Everything below assumes `services/orchestrator/` exists on `main`. The branch this work is on (`vw-agent/OPS-04-orchestrator`) needs to be merged first. Review the PR, merge it, then SSH into the VM.

## Step 1 — SSH to the VM and find the Compose stack

```bash
gcloud compute ssh <your-vm-name> --zone=<your-zone>
# or: ssh josh@35.226.25.117

# Find the existing compose file. The domain-expert-mcps skill describes
# the layout but yours may have evolved.
sudo find /opt /srv /home -maxdepth 4 -name "docker-compose.yml" -type f 2>/dev/null
```

Make note of the directory — call it `$STACK` below. On the existing MCP VM that's probably `/opt/mcp-stack/` or `/srv/mcp/` — wherever the project-docs-* services live.

```bash
export STACK=/opt/mcp-stack  # adjust to match what `find` returned
cd $STACK
ls -la
```

You should see your existing `docker-compose.yml` and the MCP service folders.

## Step 2 — Pull the orchestrator code into the stack

```bash
# Clone the orchestrator service into a sibling directory under $STACK.
sudo git clone --depth 1 \
  https://github.com/versawiki/dev.git /tmp/versawiki-dev

# Copy only the orchestrator service folder (don't drag the rest of the
# monorepo onto the VM — keeps the image build context tiny).
sudo mkdir -p $STACK/versawiki-orchestrator
sudo cp -r /tmp/versawiki-dev/services/orchestrator/. $STACK/versawiki-orchestrator/
sudo chown -R $USER:$USER $STACK/versawiki-orchestrator
ls $STACK/versawiki-orchestrator
```

You should see `Dockerfile`, `pyproject.toml`, `src/`, etc.

## Step 3 — Generate the secrets file

The orchestrator reads its config from `VW_ORCH_*` env vars and from a file at `/etc/versawiki/orchestrator.env`. Build that file now:

```bash
sudo mkdir -p /etc/versawiki
sudo chmod 700 /etc/versawiki

# Generate a random bearer for the control API.
CONTROL_BEARER=$(python3 -c 'import secrets; print(secrets.token_urlsafe(32))')

# Read existing Anthropic key from your local cron's keyfile if you've
# already synced it to the VM. Otherwise paste the value inline.
ANTHROPIC_KEY="sk-ant-..."  # paste yours

# GitHub PAT. Create at https://github.com/settings/tokens with these
# scopes: `repo`, `workflow`. 90-day expiry recommended; set a calendar
# reminder to rotate.
GH_PAT="github_pat_..."     # paste yours

# SMTP creds. Resend example:
SMTP_HOST=smtp.resend.com
SMTP_PORT=587
SMTP_USER=resend
SMTP_PASS="re_..."          # your Resend API key

sudo tee /etc/versawiki/orchestrator.env >/dev/null <<EOF
VW_ORCH_ANTHROPIC_API_KEY=${ANTHROPIC_KEY}
VW_ORCH_GH_PAT=${GH_PAT}
VW_ORCH_CONTROL_API_BEARER=${CONTROL_BEARER}
VW_ORCH_SMTP_HOST=${SMTP_HOST}
VW_ORCH_SMTP_PORT=${SMTP_PORT}
VW_ORCH_SMTP_USERNAME=${SMTP_USER}
VW_ORCH_SMTP_PASSWORD=${SMTP_PASS}
VW_ORCH_ESCALATION_FROM=orchestrator@versawiki.com
VW_ORCH_ESCALATION_TO=joshuafausset@hotmail.com
EOF

sudo chmod 600 /etc/versawiki/orchestrator.env
ls -la /etc/versawiki/

# Save the bearer somewhere YOU can recover it (you'll need it from your
# phone). Show it once:
echo "CONTROL_BEARER=$CONTROL_BEARER"
```

**Copy `CONTROL_BEARER` into a password manager** — that's what you'll paste into the iOS shortcut / phone call later when you want to check status remotely.

## Step 4 — Wire the service into your Compose file

Open `$STACK/docker-compose.yml` and paste the contents of `$STACK/versawiki-orchestrator/docker-compose.snippet.yml` into the `services:` block. Keep the existing services intact.

The snippet uses `env_file: /etc/versawiki/orchestrator.env` so Compose will refuse to start if you missed Step 3.

Verify the file is well-formed:

```bash
cd $STACK
docker compose config 2>&1 | tail -30
```

If you see the merged config for all services (existing MCPs + the new orchestrator), you're good. If there's an indentation/yaml error, fix it before continuing.

## Step 5 — Set up GitHub branch protection on `main`

The orchestrator refuses to start in ACT mode without `main` being protected. Do this from your laptop, not the VM:

```bash
# From your laptop (any machine with `gh` CLI installed and authed)
gh auth status
gh api -X PUT /repos/versawiki/dev/branches/main/protection \
  -H "Accept: application/vnd.github+json" \
  -F required_status_checks[strict]=true \
  -f required_status_checks[contexts][]=ci/tests \
  -F enforce_admins=true \
  -F required_pull_request_reviews[required_approving_review_count]=1 \
  -f restrictions=
```

If you don't yet have a `ci/tests` GitHub Action, you can register the protection without that context line (just delete the two `required_status_checks` lines); add the check requirement after CI is wired up.

Verify:

```bash
gh api /repos/versawiki/dev/branches/main/protection | jq '.required_pull_request_reviews, .required_status_checks'
```

You should see the PR-review block populated. The orchestrator's `verify_main_protection()` looks for exactly this.

## Step 6 — Build and start (observe mode)

Back on the VM:

```bash
cd $STACK
docker compose build versawiki-orchestrator
# ~5-8 minutes the first time (Python base + claude-agent-sdk + node)

docker compose up -d versawiki-orchestrator
docker compose ps versawiki-orchestrator
# Should show "running (healthy)" within ~30 seconds of startup
```

Tail the logs:

```bash
docker compose logs -f versawiki-orchestrator | head -100
```

You should see JSON log lines including:

```
{"event": "startup", ...}
{"event": "branch_protection_check_warned", ...}   # only if main isn't protected yet
```

Hit `Ctrl-C` to stop tailing — the service stays up.

## Step 7 — Smoke-test the control API

From the VM (because port 8088 is bound to 127.0.0.1 only):

```bash
BEARER=$(grep VW_ORCH_CONTROL_API_BEARER /etc/versawiki/orchestrator.env | cut -d= -f2-)

curl -s http://localhost:8088/control/status \
  -H "Authorization: Bearer $BEARER" | python3 -m json.tool
```

You should get:

```json
{
  "mode": "observe",
  "paused": false,
  "queue_depth": 0,
  "current_run": null,
  "last_runs": [],
  "spend": { "allowed": true, ... },
  "audit_rows": 2
}
```

Try a no-auth call too — it must 401:

```bash
curl -s -o /dev/null -w "%{http_code}\n" http://localhost:8088/control/status
# -> 401
```

## Step 8 — Trigger a manual tick (still observe mode)

```bash
curl -s -X POST http://localhost:8088/control/trigger \
  -H "Authorization: Bearer $BEARER" \
  -H "Content-Type: application/json" \
  -d '{"instruction": "Read STATUS.md and report what the next safe-list ticket would be. Do NOT modify any files."}'
```

Tail the logs again and watch the agent run. Because we're in observe mode, the `pr_callback` will log a `pr_would_open` audit row instead of opening anything.

After the run finishes, status should show it in `last_runs`:

```bash
curl -s http://localhost:8088/control/status -H "Authorization: Bearer $BEARER" \
  | python3 -m json.tool
```

## Step 9 — Expose it to the public internet (optional, for phone control)

Two options:

### Option A: Cloudflare Tunnel (zero firewall changes)

```bash
# On the VM
curl -L https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64 -o /usr/local/bin/cloudflared
sudo chmod +x /usr/local/bin/cloudflared
cloudflared tunnel login
cloudflared tunnel create vw-orchestrator
# Edit ~/.cloudflared/config.yml:
#   ingress:
#     - hostname: orchestrator.versawiki.com
#       service: http://127.0.0.1:8088
#     - service: http_status:404
cloudflared tunnel route dns vw-orchestrator orchestrator.versawiki.com
sudo cloudflared service install
sudo systemctl start cloudflared
```

### Option B: nginx reverse proxy + Let's Encrypt

If you've already got nginx fronting the MCPs, add a server block:

```nginx
server {
    listen 443 ssl http2;
    server_name orchestrator.versawiki.com;
    ssl_certificate     /etc/letsencrypt/live/orchestrator.versawiki.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/orchestrator.versawiki.com/privkey.pem;
    location / {
        proxy_pass http://127.0.0.1:8088;
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-For $remote_addr;
    }
}
```

Either way, you can now hit `https://orchestrator.versawiki.com/control/status` from your phone — paste the bearer into an iOS Shortcut for one-tap status checks.

## Step 10 — Soak test (48 hours)

Leave the orchestrator running in observe mode for 48 hours. Check the audit log periodically:

```bash
docker compose exec versawiki-orchestrator \
  python3 -c "
import sys; sys.path.insert(0, '/app/src')
from versawiki_orchestrator.audit import AuditLog
log = AuditLog('/var/lib/versawiki-orchestrator/audit.sqlite')
for e in log.tail(30):
    print(f'{e.ts_ns:>20} {e.event_type:<25} {str(e.payload)[:120]}')
print(f'verified: {log.verify()} rows')
"
```

What to look for:

- `tick_interval_seconds=300` → expect ~12 tick events per hour
- `run_finished` with `success=true` for each tick (in observe mode this means the agent produced a coherent summary; no PR was actually opened)
- No `escalation_failed` rows — if you see one, your SMTP is misconfigured
- `spend_recorded.amount_usd` summed under your daily cap

## Step 11 — Flip to ACT mode

When you're satisfied with what you've seen in observe mode:

```bash
# Edit the compose snippet on the VM:
sudo sed -i 's/VW_ORCH_MODE=observe/VW_ORCH_MODE=act/' $STACK/docker-compose.yml

cd $STACK
docker compose up -d versawiki-orchestrator
docker compose logs -f versawiki-orchestrator | head -20
```

The orchestrator will rerun `verify_main_protection()` at startup. If that fails, it refuses to start and prints why. Fix the protection (Step 5), `docker compose up -d` again.

In ACT mode the next tick will open a real PR. From then on, every ~5 minutes the orchestrator picks a ticket, opens a PR, and waits for you to review/merge.

## Step 12 — Retire the Cowork cron

After 7 clean days in ACT mode, kill the Cowork overnight cron — the orchestrator has replaced it. Leave the cron's `STATUS.md` and `BACKLOG.md` conventions in place; the orchestrator follows them.

## Phone control quick reference

Bookmark these on your phone (substitute your bearer):

```
GET  https://orchestrator.versawiki.com/control/status
POST https://orchestrator.versawiki.com/control/pause
POST https://orchestrator.versawiki.com/control/resume
POST https://orchestrator.versawiki.com/control/kill-current-run
POST https://orchestrator.versawiki.com/control/trigger  {"instruction": "..."}
```

All require `Authorization: Bearer <your CONTROL_BEARER>`.

## Failure modes and what to do

- **Orchestrator container keeps restarting.** Run `docker compose logs versawiki-orchestrator | tail -40`. Almost always a misconfigured env file — the startup error will say which variable.
- **`branch_protection_check_failed` in ACT mode.** Re-run Step 5. Verify `gh api /repos/versawiki/dev/branches/main/protection` returns 200 with non-empty `required_pull_request_reviews`.
- **Spending cap hit unexpectedly.** Look at the latest `run_finished` rows in the audit log. Most likely the agent burned tokens on a runaway run; resume after Anthropic resets your daily quota or lower the per-run cap.
- **Agent opens a wildly wrong PR.** `/control/pause` from your phone, close the PR on GitHub, write a `notes/orchestrator.md` entry, restart only after you've understood what triggered it.
