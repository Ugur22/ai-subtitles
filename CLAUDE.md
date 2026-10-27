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
- NEVER deploy to GCloud (`./deploy.sh`, `gcloud run deploy`, `gcloud builds submit`)
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
8. After changes, ask: "Deploy to GCloud?" - WAIT for approval
9. Only deploy after explicit "yes"

---

## Verify your work

Run `make check` (offline, about 15 seconds: lint, pytest, tsc) before reporting a task done; a Stop hook enforces it. Paid LLM evals are manual: see `backend/evals/README.md`.

## Deployment

- **GCP project**: `ai-subs-poc`, region `us-central1`
- **Cloud Run**: CPU service `ai-subs-backend` plus a separate GPU worker job, both built and deployed by `backend/deploy.sh`, which is the source of truth for resources, secrets and env vars
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
