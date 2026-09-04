# Retrieval Evaluation

A minimal, local harness that checks whether `TranscriptEmbeddingService.search_transcript_chunks()`
returns the correct transcript moment within its first `k` results.

This evaluates **retrieval**, not LLM-generated answers -- it only checks that
the right transcript chunk (by timestamp) shows up in the search results, not
whether any downstream chat/summary text is correct.

## Adding a real case

1. Index a video's transcript (via the normal app flow) and find its `video_hash`.
2. Edit `retrieval_cases.json` and replace the placeholder entry (or add a new
   one) with:
   - `name`: a short identifier for the case
   - `video_hash` / `user_id`: real values for an already-indexed video you own
   - `question`: a natural-language question a user might ask about that video
   - `expected_start_seconds`: the timestamp (seconds) where the answer actually is
   - `acceptable_window_seconds`: how much slack to allow around that timestamp
3. Any case still containing the placeholder value `REPLACE_ME` will fail
   validation immediately, before any retrieval is attempted.

If your case comes from a video indexed via local mode (`./scripts/run-local.sh`),
`video_hash`/`user_id` can be read straight out of `local_data/local.db`
(`transcript_embeddings` table); the fixed local user id is
`00000000-0000-4000-8000-000000000001`.

## Running

From `backend/`:

```bash
python evals/evaluate_retrieval.py
```

To check a different number of top results:

```bash
python evals/evaluate_retrieval.py --top-k 10
```

If your case's data was indexed in local mode, run with `LOCAL_MODE=true` so
retrieval hits the same local SQLite store instead of a remote Supabase project:

```bash
LOCAL_MODE=true python evals/evaluate_retrieval.py
```

Exit code is `0` only if every case passes; `1` if any case fails, is invalid,
or errors during retrieval.

## Comparing chunk-size configurations

By default the harness evaluates the `chunk_size_3` baseline (the production
chunk size). To compare other transcript-chunking configurations, first
build the config you want with `scripts/build_retrieval_index.py` (see
`scripts/README.md`), then pass `--index-config`:

```bash
LOCAL_MODE=true python scripts/build_retrieval_index.py --video-hash <hash> --index-config chunk_size_2
LOCAL_MODE=true python scripts/build_retrieval_index.py --video-hash <hash> --index-config chunk_size_5

LOCAL_MODE=true python evals/evaluate_retrieval.py --top-k 5 --index-config chunk_size_2
LOCAL_MODE=true python evals/evaluate_retrieval.py --top-k 5 --index-config chunk_size_3
LOCAL_MODE=true python evals/evaluate_retrieval.py --top-k 5 --index-config chunk_size_5
```

Each config is stored and searched in isolation -- a run against one config
never returns chunks indexed under another config, and rebuilding one config
never touches the baseline (`chunk_size_3`) or any other config's rows for
the same video.

## What Hit@k means

Hit@k is the percentage of questions where the correct transcript moment
appeared in the first k results.

Until real cases are added, don't treat this harness's output as a quality
measurement -- the placeholder case is not a real result. A single case
also isn't enough for a meaningful reading -- see below for generating more.

## Generating more cases

Writing cases by hand doesn't scale. `generate_cases.py` samples chunks from
an already-indexed video and asks the existing LLM chat service (the same
one behind the app's chat feature) to draft one question per sampled chunk:

```bash
python evals/generate_cases.py --video-hash <hash> --user-id <id> --count 15
```

As with the evaluator, prefix with `LOCAL_MODE=true` if the video was indexed
locally. Useful flags: `--provider` (default: whatever `DEFAULT_LLM_PROVIDER`
is set to), `--window` (default `30`), `--min-chunk-chars` (default `90`),
`--out` (default `evals/generated_cases.json`).

`--min-chunk-chars` defaults to `90`, not something lower, because chunks
under it tend to be short dialogue fragments (e.g. "Thank you. You're
welcome.") with no real content -- the LLM invents a plausible-sounding
question anyway, and the case then fails retrieval not because search is
wrong but because the label is ungrounded. On the indexed test movie, every
generated case built from a chunk >= 61 characters passed; both cases built
from chunks under 45 characters failed for exactly this reason.

This makes real LLM API calls (uses `GROQ_API_KEY` / `XAI_API_KEY` from
`.env`) and has a real, if small, cost -- don't run it excessively.

Output goes to `generated_cases.json`, **not** `retrieval_cases.json` --
LLM-authored questions are not verified ground truth (occasionally a
question is answerable from a neighboring chunk too). Review the generated
questions and timestamps yourself, then copy the good ones into
`retrieval_cases.json`.
