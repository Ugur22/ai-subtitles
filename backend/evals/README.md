# Retrieval and chat evaluation

These developer tools measure retrieval timestamps and check chat answers against reviewed cases. They do not change application authentication, storage or runtime mode. Chat evaluation and case generation make real LLM calls; run them deliberately against a designated dataset.

The scripts that use the Supabase project named in your environment (`evaluate_retrieval.py`, `generate_cases.py` and `scripts/build_retrieval_index.py`) use the service key, which bypasses row-level security. They print the target project and refuse to run unless you pass `--allow-remote`. `evaluate_chat.py` calls a backend over HTTP and needs an explicit `--base-url` instead.

The transferred JSON files and `FINDINGS.md` describe historical development datasets. Update their `user_id` and `video_hash` to a dataset you control before running them. Historical pass rates are not validation of the current deployment.

## Retrieval

From `backend/`, with the usual Supabase configuration and the intended `TEXT_EMBEDDING_MODEL`:

```bash
python evals/evaluate_retrieval.py --allow-remote --cases evals/retrieval_cases.json --top-k 5
python evals/evaluate_retrieval.py --allow-remote --index-config chunk_size_5 --top-k 10
```

Every case has `name`, `video_hash`, `user_id`, `question`, `expected_start_seconds` and `acceptable_window_seconds`. A case passes if one of the first k returned timestamps lies within the expected window. This evaluates retrieval, not the correctness of a generated answer.

The evaluator searches `transcript_embeddings_v2`, scoped to the explicit owner, selected model and chunk configuration. Index the selected model/config first; it never substitutes legacy MiniLM vectors when evaluating BGE.

```bash
python scripts/build_retrieval_index.py --allow-remote --video-hash <hash> --user-id <owner> --index-config chunk_size_5
```

Alternate chunk sizes are `chunk_size_2`, `chunk_size_3` (the default) and `chunk_size_5`. Each configuration is independent. See the script's `--help` for rebuild options.

## Candidate generation

```bash
python evals/generate_cases.py --allow-remote --video-hash <hash> --user-id <owner> --index-config chunk_size_3 --count 15 --provider grok
```

Generation reads only the chosen owner's video/model/configuration. `--min-chunk-chars` defaults to 90 to avoid questions invented around fragments. `--window` controls acceptable timestamp distance; `--out` defaults to `evals/generated_cases.json`.

Generated questions are candidates, not ground truth. Review the question, supporting transcript and expected timestamp before adding a case to `retrieval_cases.json`.

## Authenticated chat evaluation

Run a backend with normal authentication. Set these environment variables without putting session tokens into command arguments or tracked files:

- `EVAL_BASE_URL`: explicit backend origin, such as a staging HTTPS URL or `http://localhost:8000`.
- `EVAL_USER_ID`: the account that owns every case in the run.
- `EVAL_AUTH_TOKEN`: that account's `auth_token` session-cookie value.
- `EVAL_AUTH_REFRESH_TOKEN`: optional `auth_refresh_token` value for session renewal.

The runner requires HTTPS except for loopback hosts, disables redirects, verifies the account through `/api/auth/me`, and rejects cases belonging to another owner before submitting chat requests. No application-local login bypass is used. HTTP failures are recorded by status without storing response bodies or session cookies.

```bash
python evals/evaluate_chat.py --cases evals/chat_cases.json --provider grok --top-k 5
python evals/evaluate_chat.py --base-url https://your-staging-backend --cases evals/chat_cases_bosco_vecchio.json
```

Each chat case requires:

- `id`, `video_hash`, `user_id`, `question` and a human-reviewed `expected_answer`.
- `expected_time_range`: numeric `start` and `end` seconds.
- `required_terms`: distinctive facts the answer must include. A string must appear; a list of synonyms passes when any member appears.
- Optional `what_must_not_be_claimed`: substrings that would indicate an incorrect claim.

A case passes only if required facts appear, forbidden claims do not, and a citation overlaps the expected time range. These checks are useful regression signals, not a substitute for reviewing ambiguous answers. `--top-k` controls retrieval results; `--index-config` is a history label, not a request to change the deployed chat index. Defaults to the backend's normal provider unless `--provider` is supplied.

Full results go to `evals/chat_eval_results.json`; use `--out` for a separate artifact. Results may include private answers/citations, so generated artifacts are ignored by Git.

## Evaluation history

Chat runs are saved in `evals/eval_history.db`, an optional local developer SQLite artifact separate from application persistence. Use `--no-save-history` to disable it, `--history-db` to select another file, and `--run-label` to distinguish experiments.

```bash
python evals/report_eval_history.py --latest
python evals/report_eval_history.py --latest --case-file evals/chat_cases.json
python evals/report_eval_history.py --compare 2 3
python evals/report_eval_history.py --analysis
```

History stores case scores, answers, citations, duration and model/provider labels when known; it never receives session cookies or API keys. For remote evaluation the model label read from local environment variables is informational: ensure it matches the deployed backend when comparing runs.

## Tests

```bash
python -m pytest tests/test_evaluate_retrieval.py tests/test_generate_cases.py tests/test_evaluate_chat.py tests/test_eval_history_db.py -q
```

The tests use fakes and temporary history databases, with no model downloads or paid API calls.

## Rebuilding embeddings after a model change

`scripts/rebuild_text_embeddings.py` re-embeds transcripts and audio events with the model in `TEXT_EMBEDDING_MODEL`. Rows for other models stay in place, so switching back is a configuration change.

```bash
python scripts/rebuild_text_embeddings.py --all --allow-remote            # lists what would be rebuilt, writes nothing
python scripts/rebuild_text_embeddings.py --all --allow-remote --execute  # rebuilds every completed job
python scripts/rebuild_text_embeddings.py --allow-remote --user-id <owner> --video-hash <hash>   # one video
```

To compare models on the same video, build each model's index with `--model` and run `evaluate_retrieval.py` with `TEXT_EMBEDDING_MODEL` set to the one being measured.
