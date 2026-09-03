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

## Running

From `backend/`:

```bash
python evals/evaluate_retrieval.py
```

To check a different number of top results:

```bash
python evals/evaluate_retrieval.py --top-k 10
```

Exit code is `0` only if every case passes; `1` if any case fails, is invalid,
or errors during retrieval.

## What Hit@k means

Hit@k is the percentage of questions where the correct transcript moment
appeared in the first k results.

Until real cases are added, don't treat this harness's output as a quality
measurement -- the placeholder case is not a real result.
