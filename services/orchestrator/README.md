# versawiki-orchestrator

The always-on Claude Agent SDK orchestrator. Replaces the 4-hour Cowork cron with a long-running process on the GCP VM.

See `docs/operations/agent-sdk-spec.md` for the design rationale and `docs/operations/orchestrator-deploy.md` for the VM rollout walkthrough.

## What it does

- Subscribes to triggers (cron tick, GitHub webhooks coming in v0.2, Postgres LISTEN in v0.3)
- Spawns one Claude Agent SDK run per trigger
- Agent works on a `vw-agent/<ticket-id>` branch, never on `main`
- Opens a PR through the GitHub API
- Logs every decision + spend to a SQLite audit log with a per-row hash chain
- Pauses itself when a spend cap is hit, emails Josh
- Exposes `/control/status`, `/control/pause`, `/control/resume`, `/control/kill-current-run` (bearer-token auth) so Josh can drive it from his phone

## Modes

- `ORCHESTRATOR_MODE=observe` (default) — agent runs, decisions are logged, but the PR writer logs the intended action instead of actually opening a PR. This is the migration step from the spec ("48 hours of observation before flipping to action mode").
- `ORCHESTRATOR_MODE=act` — agent runs and PRs are opened.

Even in `act` mode, the orchestrator never has push access to `main`. Branch protection is verified at startup.

## Quick test

```
pip install -e ".[test]" --break-system-packages
PYTHONPATH=src python -m pytest -q tests/
```

## Running locally

```
export ANTHROPIC_API_KEY=...
export GH_PAT=...
export CONTROL_API_BEARER=$(python -c 'import secrets; print(secrets.token_urlsafe(32))')
PYTHONPATH=src python -m versawiki_orchestrator.main
```

Hit `http://localhost:8088/control/status` with `Authorization: Bearer $CONTROL_API_BEARER` to verify.

## Deployment

See `docs/operations/orchestrator-deploy.md`. Short version: build the Docker image, paste a service block into the VM's `docker-compose.yml`, restart the stack.
