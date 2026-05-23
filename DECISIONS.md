# Decision log

Append-only. Newest at top. Each entry: date, decision, rationale, made-by, reversibility cost.

The Orchestrator records decisions taken without escalating to Josh (per the day-or-two-rework rule). Josh's explicit decisions are recorded here too.

---

## 2026-05-22 — Orchestration model is mission-driven, not scheduled

**Decision:** Versawiki's agent team is coordinated by Claude acting as Orchestrator at the start of each session, spawning specialists via the Task tool. No scheduled-task cron.

**Rationale:** Josh prefers the team to act on next-best need rather than clock cadence. Specialists run in parallel where independent; serial when blocked. Orchestrator makes day-or-two-rework-stakes calls without asking.

**Made by:** Josh.

**Reversibility:** Trivial — we can layer scheduled tasks on top later if needed.

---

## 2026-05-22 — First-built connector is local folder

**Decision:** M1 targets local-folder ingestion only. Google Drive, OneDrive/SharePoint, Dropbox/Box, iCloud follow in that order.

**Rationale:** Local first eliminates OAuth, scopes, and rate limits so we can validate the hard parts (classification, ontology induction, query-driven re-indexing) on a fast loop. The connector layer becomes a thin adapter once the core works.

**Made by:** Josh.

**Reversibility:** Cheap — the ingestion interface should be connector-agnostic from day one anyway.

---

## 2026-05-22 — Code lives at github.com/versawiki/dev

**Decision:** The team commits to `github.com/versawiki/dev`, branch `main`. Git is split: git-dir at `/tmp/vw_git`, work-tree at the workspace mount (Cowork mount blocks normal `.git` operations).

**Rationale:** Josh wants real version history and the ability to review work from mobile. Empty repo confirmed on GitHub. Push credential pending.

**Made by:** Josh.

**Reversibility:** Trivial.
