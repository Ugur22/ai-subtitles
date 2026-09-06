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

# Chat Evaluation

A second, end-to-end harness that drives the real `POST /api/chat/` endpoint
in-process (via an ASGI test client wrapping the app from `main.py`, no live
server needed) and rule-checks the final synthesized answer text and its
citations -- not just retrieval.

This is the key difference from the retrieval harness above:
`evaluate_retrieval.py` only proves `search_transcript_chunks()` finds the
right chunk. It says nothing about what the chat endpoint's answer-synthesis
step (`routers/chat.py`) actually does with that chunk once it's in the LLM's
context -- and `FINDINGS.md` documents several real, user-visible bugs
(wrong scene confidently cited, an explicit stated reason replaced with a
generic inference, a correct hit buried and ignored) that only manual testing
against the live endpoint caught, because they happen entirely downstream of
retrieval. `evaluate_chat.py` exists to make that class of bug catchable by a
repeatable, scriptable check instead of only by hand.

## Case schema (`chat_cases.json`)

```json
{
  "id": "short-kebab-id",
  "video_hash": "...",
  "user_id": "...",
  "question": "a natural-language question a user might ask",
  "expected_answer": "short human-verified factual answer",
  "expected_time_range": {"start": 100.0, "end": 130.0},
  "what_must_not_be_claimed": []
}
```

- `expected_answer`: a short, human-verified summary of what the correct
  answer actually says -- not the exact LLM wording, just the key facts a
  correct answer must contain.
- `expected_time_range`: a window generous enough to cover the relevant
  chunk plus reasonable neighbor context. This is intentionally a loose
  sanity check on citation location, not a tight one.
- `what_must_not_be_claimed` (optional, default `[]`): substrings that must
  **not** appear anywhere in the answer -- typically the identifying words of
  a previously-wrong answer, to catch regressions back to a fixed bug.

**Ground truth must come from the transcript, not from a chat answer.**
Write `expected_answer`/`expected_time_range`/`what_must_not_be_claimed` by
independently reading the source material -- e.g. querying
`transcript_embeddings` (`chunk_index, start_time, end_time, chunk_text`,
`index_config='chunk_size_3'`) directly for the relevant timestamp, or
watching/reading the source subtitles -- never by copying the harness's own
first LLM-generated answer. A case whose "ground truth" is actually what the
system under test said can't catch that system being wrong, and this bit a
real case here: an earlier draft of `sadie-retirement-party-invite` claimed
she invited "her friends," because that's what a first chat run said, but
the transcript only has her say "I invited you" -- no friends mentioned. A
first run against a candidate question is fine for *discovering which
questions/timestamps are worth turning into a case* -- never as the source
of the expected answer text itself.

## Running

From `backend/`, with `LOCAL_MODE=true` (required -- the harness refuses to
run without it, since this is an in-process test against the local SQLite
store, not a remote Supabase project):

```bash
LOCAL_MODE=true python evals/evaluate_chat.py
```

Useful flags: `--cases` (default `evals/chat_cases.json`), `--provider`
(default `None`, uses whatever `DEFAULT_LLM_PROVIDER` is configured),
`--out` (default `evals/chat_eval_results.json`, gitignored -- a per-run
artifact, not something to commit).

Exit code is `0` only if every case passes; `1` if any case fails, is
invalid, or errors during the call.

## What each check means

Each case runs three independent rule-based checks against the real
`/api/chat/` response:

- **`citation_ok`**: at least one returned source's `[start, end]` window
  overlaps `expected_time_range` -- the answer is grounded in a citation near
  the right moment in the video.
- **`terms_ok`**: a majority of `expected_answer`'s key terms (after
  stripping stopwords/short tokens) appear as substrings in the actual
  answer -- a simple, dependency-free proxy for "the answer says the right
  thing," not a semantic match.
- **`forbidden_ok`**: none of `what_must_not_be_claimed`'s strings appear in
  the answer -- catches regressions to a previously-fixed wrong answer.

A case only passes if all three checks pass. On failure, the harness prints
the question, expected answer/time range, and the **full** actual answer and
sources, so a human can read what went wrong without re-running anything.

## Cost caveat

Every run makes real LLM API calls (Groq/Grok, per `DEFAULT_LLM_PROVIDER` /
`--provider`) for every case -- it's not free and not instant. Don't run this
in a tight loop or wire it into a fast feedback cycle; run it deliberately
when validating a chat-synthesis change.

## When a rule-based check isn't enough

These checks are blunt on purpose (substring/overlap, not semantic
judgment) -- they can both under- and over-flag. A `terms_ok` pass doesn't
guarantee the reasoning is right, and a `forbidden_ok` fail doesn't always
mean the answer is wrong (e.g. an answer can correctly lead with the right
quote and citation while still mentioning a forbidden term in passing, as
one of the fixed cases in this file's history does). When a failure needs
more than the printed answer/sources to explain -- or when you find a new
chat-synthesis bug this harness's checks aren't precise enough to name --
log it in `FINDINGS.md` the same way the bugs that motivated this harness
were originally found and fixed.
