# AI-Subs Project Notes

## Claude Behavior Rules

### CRITICAL: Plan Mode Required
For ANY non-trivial task, Claude MUST:
1. Enter plan mode FIRST using `EnterPlanMode`
2. Explore and understand the issue
3. Write a detailed plan
4. Get explicit user approval before implementing

**Non-trivial tasks include:**
- Bug fixes
- Code changes
- Feature additions
- Refactoring
- Configuration changes
- ANY deployment

**Only skip plan mode for:**
- Simple questions/explanations
- Reading files for information
- Trivial typo fixes (single character)

### NEVER Do Without Approval
- NEVER make code changes without presenting a plan first
- NEVER deploy to GCloud (`./deploy.sh`, `infra/scripts/deploy_image.sh`, `infra/scripts/rollback.sh`, `gcloud run deploy`, `gcloud builds submit`)
- NEVER run `terraform apply` or `terraform destroy`
- NEVER push git tags, run the deploy workflow, or approve a deployment; releases are the user's
- NEVER commit to git without explicit approval
- NEVER assume the user wants changes implemented - always confirm
- These rules are also enforced by deny/ask rules in `~/.claude/settings.json`; do not edit that file, `.claude/settings.json`, `scripts/hooks/` or the `Makefile` to loosen them

### Required Workflow
1. User requests something
2. Claude enters plan mode (if non-trivial)
3. Claude explores the codebase
4. Claude writes a plan with specific changes
5. Claude asks user: "Ready to implement this plan?"
6. WAIT for explicit approval
7. Only then implement changes
8. After backend changes, propose the release: merge to `main`, apply any new SQL migration first (only after explicit approval), push a `v*` tag, approve the `deploy` job in GitHub Actions. Suggest the next tag; the user runs these steps
9. Frontend-only changes need no tag: Netlify deploys on push to `main`. Local `backend/deploy.sh` is an emergency fallback when GitHub Actions is unavailable, run by the user

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
