# AI-Subs Project Notes

## Claude Behavior Rules

### Where agents run
- **Agent container** (`bin/agent`): autonomous development. No permission prompts and no plan approval for ordinary work: implement, test, commit on a feature branch, push, open a PR, watch CI and fix it. The container has no production credentials; its GitHub App token can only push branches and open PRs on this repository. Merging, migrations, tags and deploys stay with the user and are enforced by GitHub, not by these instructions.
  - Branch from an up-to-date `origin/main` as `agent/<topic>`: the GitHub ruleset rejects any other branch name. Commit with the configured git identity (the GitHub App's bot account); never set `user.name` or `user.email`, and never commit as the user.
- **Host sessions**: the user's own machine. Commit and push only when asked; never run deploys or migrations (deny rules in `~/.claude/settings.json`).

### Risk tiers
Pick the tier from what the change touches. When unsure, use the higher tier.
- **Ordinary**: application code, tests, UI, refactors inside a module, docs. Proceed without asking. Done means `make check` green and a PR with a short summary.
- **Sensitive**: auth and access control (`backend/middleware/auth.py`, `backend/services/transcription_access.py`, ownership scoping), SQL migrations, the job queue, the GPU slot, worker retries and idempotency, Stripe and billing, `infra/`, anything that deletes or rewrites stored data. Still autonomous, but write the plan first and put it in the PR description under `## Risk`: what can fail, how it is tested, how to roll back (migrations need their `_rollback.sql`). Mark the PR title `[sensitive]` so the user reviews it closely.
- **Irreversible or production** (the user only): applying a migration to Supabase, deploys, `terraform apply`/`destroy`, tags and releases, secrets and IAM, approving a deployment. Prepare the files and the exact commands, then stop. Agents have no credentials for these.
- **Guard paths** (the user only): `.github/`, `tools/policy/`, `tools/agent-container/`, `bin/agent`, `.claude/`, `CLAUDE.md`, hooks, the `Makefile`, lint/test/type-check configs and eval cases. Propose the change in the PR description; never edit them to make a check pass. The trusted `policy` check rejects agent PRs that touch them.

### Agents
- **Lead**: the main session plans, makes small edits itself, delegates scoped work, runs `make check`, commits and opens the PR. Subagents never commit or push.
- `backend-developer` (`backend/`), `frontend-developer` (`frontend/`), `bug-fixer` (a failing test or error): scoped changes. Work that spans both starts with the API shape (route, request and response fields) fixed in the plan.
- `reviewer` (Sonnet, read-only): reviews the diff before the push. Required for every Sensitive change and for any diff a subagent wrote.
- `advisor` (Opus, read-only): before implementing a Sensitive plan, and after the same failure twice. It advises; the lead decides.
- Repo-wide searches: the built-in Explore agent.
- Scale to the task. A small Ordinary change (one module, the lead's own edit) needs no delegation and no review agent; delegate and review when work spans modules or touches a Sensitive area.
- Every delegation prompt states, so nothing depends on the agent guessing:
  - **Goal**: one sentence.
  - **Constraints**: the rules from the plan and this file that apply.
  - **Scope**: the files or folders to touch.
  - **Done when**: the exact command(s) and the expected result.
  - **Earlier attempts**: what was tried and how it failed, or "none".
  - **Report**: changed files, the last lines of `make check` and its exit code, and what was not verified.
- In the PR description, under `## Review`, list each `reviewer`/`advisor` finding by its ID with what you did: fixed (commit), rejected (why), or deferred. Write "none run" when no review agent ran.

### Substantial features
For a feature that spans backend and frontend, adds a table or a family of endpoints, or changes how jobs flow (not for fixes or ordinary features), write a short spec at the top of the PR description before delegating. It is not an approval step: write it, then build it.
- **Terms**: names for the new concepts, used the same way in code, API and UI.
- **Acceptance criteria**: observable behavior, each mapped to the test that proves it.
- **Decisions**: what was chosen and the rejected alternative, one line each. Add a file in `docs/adr/` only when later work must respect the decision.
- **Slices**: independently testable steps in order, each leaving `make check` green. A Sensitive slice (for example a migration) goes first and alone.
Prototype only when an unknown (library behavior, performance) decides the design, and throw the prototype away.

### Verification loop
- The Stop hook (`tools/harness/stop_check.py`) runs `make check` whenever the tree's git state changed since its last green run, commits included, and blocks finishing at most 3 times per session. Block 2: if it is the same failure, ask `advisor` before another attempt.
- Never present red work as done. If you cannot get `make check` green, your final message starts with `NOT READY:` and states the remaining failure, what you tried, and whether `advisor` was consulted; leave or make the PR a draft. After the cap the hook tells the user the work is not done and, in the container, turns the PR into a draft. CI and the `policy` check remain the merge gate.
- The hook and the ledger it writes (`.harness/ledger.jsonl` on the host, `/work/.harness/` in the container; summarise with `ai-subs-agent ledger`) are telemetry for retrospectives, not proof: their state is writable by the session it observes.
- `reviewer` and `advisor` report each finding on one line as `R1 [severity][category:pattern] file:line - summary` (`A1` for advisor), or `No findings.`; the ledger parses that line, so keep the format.

### Releases
After backend changes, propose the release: merge to `main`, apply any new SQL migration first (only after explicit approval), push a `v*` tag, approve the `deploy` job in GitHub Actions. Suggest the next tag; the user runs these steps. Frontend-only changes need no tag: Netlify deploys on push to `main`. Local `backend/deploy.sh` is an emergency fallback when GitHub Actions is unavailable, run by the user.

---

## Verify your work

Run `make check` (offline, about 15 seconds: lint, pytest, tsc, vitest) before reporting a task done; the Stop hook enforces it (see Verification loop). Paid LLM evals are manual: see `backend/evals/README.md`.

## Deployment

- **GCP project**: `ai-subs-poc`, region `us-central1`
- **Cloud Run**: CPU service `ai-subs-backend` plus a separate GPU worker job, both built and deployed by `infra/scripts/deploy_image.sh` (run by `backend/deploy.sh` and `.github/workflows/deploy.yml`), which is the source of truth for resources, secrets and env vars; IAM, monitoring and the CI deployer are in `infra/terraform` (see `docs/INFRASTRUCTURE.md`)
- **Artifact Registry**: repo is `ai-subs-repo` (NOT `ai-subs`)
- Run deploys from your own terminal with Owner credentials, never from inside a Claude Code session: the agent's shell uses a read-only service account (`~/.config/gcloud-agent`)
- Scheduler jobs, GCS layout, GPU quota and LLM provider notes: `docs/GCP_OPERATIONS.md`

## Models

What is baked into the Docker image: `backend/download_models.py`. Runtime defaults (Whisper size, embedding model): `backend/config.py`.

## graphify

This project has a knowledge graph at graphify-out/ with god nodes, community structure, and cross-file relationships.

Rules:
- For codebase questions, first run `graphify query "<question>"` when graphify-out/graph.json exists. Use `graphify path "<A>" "<B>"` for relationships and `graphify explain "<concept>"` for focused concepts. These return a scoped subgraph, usually much smaller than GRAPH_REPORT.md or raw grep output.
- If graphify-out/wiki/index.md exists, use it for broad navigation instead of raw source browsing.
- Read graphify-out/GRAPH_REPORT.md only for broad architecture review or when query/path/explain do not surface enough context.
- After modifying code, run `graphify update .` to keep the graph current (AST-only, no API cost).
