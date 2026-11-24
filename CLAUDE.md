# AI-Subs Project Notes

## Claude Behavior Rules

### Where agents run
- **Agent container** (`bin/agent`): autonomous development. No permission prompts and no plan approval for ordinary work: implement, test, commit on a feature branch, push, open a PR, watch CI and fix it. The container has no production credentials; its GitHub App token can only push branches and open PRs on this repository. Merging, migrations, tags and deploys stay with the user and are enforced by GitHub, not by these instructions.
- **Host sessions**: the user's own machine. Commit and push only when asked; never run deploys or migrations (deny rules in `~/.claude/settings.json`).

### Risk tiers
Pick the tier from what the change touches. When unsure, use the higher tier.
- **Ordinary**: application code, tests, UI, refactors inside a module, docs. Proceed without asking. Done means `make check` green and a PR with a short summary.
- **Sensitive**: auth and access control (`backend/middleware/auth.py`, `backend/services/transcription_access.py`, ownership scoping), SQL migrations, the job queue, the GPU slot, worker retries and idempotency, Stripe and billing, `infra/`, anything that deletes or rewrites stored data. Still autonomous, but write the plan first and put it in the PR description under `## Risk`: what can fail, how it is tested, how to roll back (migrations need their `_rollback.sql`). Mark the PR title `[sensitive]` so the user reviews it closely.
- **Irreversible or production** (the user only): applying a migration to Supabase, deploys, `terraform apply`/`destroy`, tags and releases, secrets and IAM, approving a deployment. Prepare the files and the exact commands, then stop. Agents have no credentials for these.
- **Guard paths** (the user only): `.github/`, `tools/policy/`, `tools/agent-container/`, `bin/agent`, `.claude/`, `CLAUDE.md`, hooks, the `Makefile`, lint/test/type-check configs and eval cases. Propose the change in the PR description; never edit them to make a check pass. The trusted `policy` check rejects agent PRs that touch them.

### Releases
After backend changes, propose the release: merge to `main`, apply any new SQL migration first (only after explicit approval), push a `v*` tag, approve the `deploy` job in GitHub Actions. Suggest the next tag; the user runs these steps. Frontend-only changes need no tag: Netlify deploys on push to `main`. Local `backend/deploy.sh` is an emergency fallback when GitHub Actions is unavailable, run by the user.

---

## Verify your work

Run `make check` (offline, about 15 seconds: lint, pytest, tsc) before reporting a task done; a Stop hook enforces it. Paid LLM evals are manual: see `backend/evals/README.md`.

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
