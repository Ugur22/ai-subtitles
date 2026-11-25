# AI-Subs Project Notes

## Overview
AI-Subs transcribes, diarizes, translates and indexes uploaded video and audio, and lets users search and chat over the result.
- **Backend** (`backend/`): FastAPI on a CPU Cloud Run Service (`main.py`, `routers/`, `services/`); the pipeline runs in a separate GPU Cloud Run Job (`worker_main.py`), dispatched per job through the job queue.
- **Frontend** (`frontend/`): React, Vite and TypeScript on Netlify, which proxies `/api/*` to Cloud Run.
- **Data**: Supabase Postgres (with pgvector), accessed with the service key; media in GCS.
- Architecture: `docs/ARCHITECTURE.md`. Infrastructure: `docs/INFRASTRUCTURE.md`.

Path-specific rules live in `.claude/rules/` and load when you work on matching files: `backend.md`, `frontend.md`, `worker-and-jobs.md`, `database-and-migrations.md`, `infrastructure.md`. Everything below applies everywhere.

## Claude Behavior Rules

### Where agents run
- **Agent container** (`bin/agent`): autonomous development. No permission prompts and no plan approval for ordinary work: implement, test, commit on a feature branch, push, open a PR, watch CI and fix it. The container has no production credentials; its GitHub App token can only push branches and open PRs on this repository. Merging, migrations, tags and deploys stay with the user and are enforced by GitHub, not by these instructions.
  - Branch from an up-to-date `origin/main` as `agent/<topic>`: the GitHub ruleset rejects any other branch name. Commit with the configured git identity (the GitHub App's bot account); never set `user.name` or `user.email`, and never commit as the user.
  - One session per container, one checkout: `agent-session` refuses a second concurrent session. Don't create `git worktree`s (the gate refuses `git worktree add`) or work from another directory; switch branches in `/work/ai-subtitles`, park uncommitted work with `git stash -u`, and run `gh pr` there. The review gate and the ledger only see that checkout and refuse `gh pr` after a `cd` elsewhere or with `--head` of another branch.
- **Host sessions**: the user's own machine. Commit and push only when asked; never run deploys or migrations (deny rules in `~/.claude/settings.json`).

### Risk tiers
The tier comes from what the change touches, computed from the diff (`tools/harness/risk.py`; `ai-risk status` in the container), not from your opinion of it. You may raise it (`ai-risk escalate sensitive --reason "..."`) when you see a risk it can't, never lower it. When unsure, raise it.
- **Ordinary**: application code, tests, UI, refactors inside a module, docs. Proceed without asking. Done means `make check` green and a PR with a short summary.
- **Review**: a core module (`backend/main.py`, `supabase_service.py`, `frontend/src/services/api.ts`, `config.ts`, `App.tsx`), backend and frontend together, three or more areas, or more than 300 changed lines outside tests and lockfiles. `reviewer` reviews the finished diff before the PR.
- **Sensitive**: auth and access control (`backend/middleware/auth.py`, `backend/services/transcription_access.py`, ownership scoping, new routes, Supabase queries in routers), SQL and migrations, the job queue, the GPU slot and the worker, Stripe and billing, API keys and encryption, config and secrets loading (`backend/config.py`, `dependencies.py`, `load_dotenv`/`os.environ`), `infra/`, anything that deletes or rewrites stored data. Still autonomous, but `advisor` reviews the plan before you implement it, `reviewer` the finished diff, the PR title starts with `[sensitive]` and the description has a `## Risk` section.
- **Irreversible or production** (the user only): applying a migration to Supabase, deploys, `terraform apply`/`destroy`, tags and releases, secrets and IAM, approving a deployment. Prepare the files and the exact commands, then stop. Agents have no credentials for these.
- **Guard paths** (the user only): `.github/`, `tools/policy/`, `tools/agent-container/`, `bin/agent`, `.claude/`, `CLAUDE.md`, hooks, the `Makefile`, lint/test/type-check configs and eval cases. Propose the change in the PR description; never edit them to make a check pass. The trusted `policy` check rejects agent PRs that touch them.

### Agents
- **Lead**: the main session plans, makes small edits itself, delegates scoped work, runs `make check`, commits and opens the PR. Subagents never commit or push.
- `backend-developer` (`backend/`), `frontend-developer` (`frontend/`), `bug-fixer` (a failing test or error): scoped changes. Work that spans both starts with the API shape (route, request and response fields) fixed in the plan.
- `reviewer` (Sonnet, read-only): reviews the finished diff before the PR. Required for Review and Sensitive changes, whoever wrote the code, and for any diff a subagent wrote.
- `advisor` (Opus, read-only): before implementing a Sensitive plan, before a significant architectural decision, and after the same failure twice. It advises; the lead decides.
- Repo-wide searches: the built-in Explore agent.
- Scale to the task. An Ordinary change needs no delegation and no review agent; delegate when work spans modules.
- Every delegation prompt states, so nothing depends on the agent guessing:
  - **Goal**: one sentence.
  - **Constraints**: the rules from the plan and this file that apply.
  - **Scope**: the files or folders to touch.
  - **Done when**: the exact command(s) and the expected result.
  - **Earlier attempts**: what was tried and how it failed, or "none".
  - **Report**: changed files, the last lines of `make check` and its exit code, and what was not verified.
- In the PR description, under `## Review`, give every `reviewer`/`advisor` finding a disposition (format below), or write `No findings.`.

### Substantial features
For a feature that spans backend and frontend, adds a table or a family of endpoints, or changes how jobs flow (not for fixes or ordinary features), write a short spec at the top of the PR description before delegating. It is not an approval step: write it, then build it.
- **Terms**: names for the new concepts, used the same way in code, API and UI.
- **Acceptance criteria**: observable behavior, each mapped to the test that proves it.
- **Decisions**: what was chosen and the rejected alternative, one line each. Add a file in `docs/adr/` only when later work must respect the decision.
- **Slices**: independently testable steps in order, each leaving `make check` green. A Sensitive slice (for example a migration) goes first and alone.
Prototype only when an unknown (library behavior, performance) decides the design, and throw the prototype away.

### Risk lifecycle
1. **Before implementing**: run `ai-risk plan <files you intend to touch>`. For Sensitive work, give `advisor` the plan first, and write the `## Risk` section as you go.
2. **While working**: the harness reclassifies the diff after each change and tells you once when the tier rises (for example when the work reaches `config.py`). Follow it: consult `advisor` before going further on Sensitive work. In the container this is enforced: once the branch is Sensitive, the edit tools and commit-making git commands are refused until `advisor` has run on it.
3. **Before the PR**: for Review and Sensitive changes, `reviewer` reviews the diff against `origin/main`. Changes after that review are judged by themselves: small fixes and new tests need nothing more; a significant change (new sensitive code, more than 80 lines outside tests, new files) needs a targeted re-review of `git diff <reviewed tree>` only, with findings numbered after the last ID. At most 3 review rounds per branch.
4. **Opening the PR**: write the description to a file and run `gh pr create --title "..." --body-file <file>`. The harness refuses the command while a requirement is missing and says which; `ai-risk status` shows the same list.
5. **Fallback**: the Stop hook checks the same requirements after `make check` is green and blocks finishing at most 3 times. When the rounds or blocks run out with work unreviewed or findings unresolved, the work is NOT READY: say so in your final message and keep the PR a draft (`gh pr create --draft`, description starting with `NOT READY:`).

These local checks catch slips; they read a ledger the session can write, so they prove nothing. The trusted `policy` check in CI judges the PR's form (the same tiers, `[sensitive]`, `## Risk`, `## Review`), and the user's approval of the exact commit is the decision.

`## Review`, one line per finding, or `No findings.`. A blocker can't be deferred; every disposition needs a reason after the colon:
```
- R1 [should-fix] fixed: b07ac76 adds test_settings_sources.py
- R2 [should-fix] rejected: checked against origin/main, parsing is unchanged (LOCAL_MODE=1 was already True)
- R3 [nit] deferred: follow-up issue, dotenv loading order in model_catalog.py
```

`## Risk` (Sensitive), each field on its own line:
```
- Impact: what breaks, and for whom, if this is wrong
- Verification: the tests and checks actually run, by name, and any manual check
- Rollback: the concrete recovery steps
- Reversibility: code-only (revert and redeploy) | rollback migration | data repair | irreversible (say what)
- Uncertainty: what was not verified
```
Reverting the commit only undoes code. A migration needs its `_rollback.sql` applied, rewritten or deleted data needs repair or a backup, and sent emails, Stripe charges or deleted files can't be undone; say which applies.

**Stacked PRs** for Sensitive features: the Sensitive slice (for example the migration) goes first and alone, backward compatible with the code on `main`, as `agent/<feature>-1-<slice>`; the next slice branches from it and opens its PR with `--base agent/<feature>-1-<slice>`. Each PR in the stack passes the gates on its own diff. The user merges from the bottom; GitHub retargets the next PR to `main`.

### Verification loop
- The Stop hook (`tools/harness/stop_check.py`) runs `make check` whenever the tree's git state changed since its last green run, commits included, and blocks finishing at most 3 times per session. Block 2: if it is the same failure, ask `advisor` before another attempt.
- Never present red work as done. If you cannot get `make check` green, your final message starts with `NOT READY:` and states the remaining failure, what you tried, and whether `advisor` was consulted; leave or make the PR a draft. After the cap the hook tells the user the work is not done and, in the container, turns the PR into a draft. CI and the `policy` check remain the merge gate.
- The hook and the ledger it writes (`.harness/ledger.jsonl` on the host, `/work/.harness/` in the container; summarise with `ai-subs-agent ledger`) are telemetry for retrospectives, not proof: their state is writable by the session it observes.
- `reviewer` and `advisor` report each finding on one line as `R1 [severity][category:pattern] file:line - summary` (`A1` for advisor), or `No findings.`; the ledger and the gates parse that line, so keep the format.

### Engineering rules (ratchets) and invariant tests
- `tools/ratchets/` holds rules that may not get worse (run by `make check` and CI). When one fails, fix the code. Never edit `tools/ratchets/` (owner-only; the `policy` check rejects it); if you think an exception is right, say why in the PR description and the user decides.
- `backend/tests/invariants/` holds protected behavioural tests (ownership, worker lifecycle and the like). Add new test files there for invariants; never change or remove an existing one (the `policy` check rejects it). Work there is Sensitive.
- A behavioural test for a critical protection needs a mutation control: in the PR description, give the file, the exact text to remove or change, and the test that must then fail. The user adds it to `tools/ratchets/mutations.json` (`make mutation-check`).

### Releases
After backend changes, propose the release: merge to `main`, apply any new SQL migration first (only after explicit approval), push a `v*` tag, approve the `deploy` job in GitHub Actions. Suggest the next tag; the user runs these steps. Frontend-only changes need no tag: Netlify deploys on push to `main`. Local `backend/deploy.sh` is an emergency fallback when GitHub Actions is unavailable, run by the user.

---

## Verify your work

Run `make check` (offline, about 30 seconds: lint, pytest, the ratchets, tsc, vitest) before reporting a task done; the Stop hook enforces it (see Verification loop). Paid LLM evals are manual: see `backend/evals/README.md`.

## Deployment

- Run deploys from your own terminal with Owner credentials, never from inside a Claude Code session: the agent's shell uses a read-only service account (`~/.config/gcloud-agent`).
- GCP project, Cloud Run Service and worker Job, Terraform, Artifact Registry, IAM, secrets and rollback: `.claude/rules/infrastructure.md`, `docs/INFRASTRUCTURE.md` and `docs/GCP_OPERATIONS.md`.

## Enforcement commands

- `make check` (full offline check), `make check-fast` (lint; the PostToolUse hook `scripts/hooks/post-edit.sh`), `make test-ratchets`, `make mutation-check`.
- `ai-risk plan <files>`, `ai-risk status`, `ai-risk escalate <tier> --reason "..."` (container; `tools/harness/risk.py`, `gate.py`).
- Stop hook `scripts/hooks/stop-check.sh` → `tools/harness/stop_check.py`; ledger `tools/harness/ledger.py`, summarised with `ai-subs-agent ledger`.
- PR form and guard paths: the trusted `policy` check, `tools/policy/check_pr.py`.

## graphify

This project has a knowledge graph at graphify-out/ with god nodes, community structure, and cross-file relationships.

Rules:
- For codebase questions, first run `graphify query "<question>"` when graphify-out/graph.json exists. Use `graphify path "<A>" "<B>"` for relationships and `graphify explain "<concept>"` for focused concepts. These return a scoped subgraph, usually much smaller than GRAPH_REPORT.md or raw grep output.
- If graphify-out/wiki/index.md exists, use it for broad navigation instead of raw source browsing.
- Read graphify-out/GRAPH_REPORT.md only for broad architecture review or when query/path/explain do not surface enough context.
- After modifying code, run `graphify update .` to keep the graph current (AST-only, no API cost).
