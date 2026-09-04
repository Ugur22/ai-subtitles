# Findings for later investigation

Issues discovered while manually verifying retrieval eval cases against the
app's chat feature. These are outside the scope of `evaluate_retrieval.py`
(which only tests `search_transcript_chunks`, not the chat answer-synthesis
pipeline on top of it) -- logged here to revisit separately.

## RESOLVED: chat context assembly lost retrieval rank/tier (2026-09-04)

Root cause for the three findings below (marked RESOLVED / PARTIALLY RESOLVED
inline): `backend/routers/chat.py`'s `_retrieve_text_context()` pipeline
called `search_transcript_chunks()` (which returns hits in similarity-rank
order) but then `_expand_text_hits_with_neighbors()` rebuilt the list sorted
by chronological video position, discarding the rank entirely. Neighbor
segments and `_lexical_segment_matches()` keyword-overlap segments were then
merged in with no marker distinguishing them from real semantic hits.
`_format_text_context()` rendered all of this identically -- so by the time
the prompt reached the LLM, a chunk `search_transcript_chunks` confidently
ranked #1 looked structurally identical to 20+ other chunks, including
keyword-overlap distractors.

**Fix:** every context segment now carries `tier` (`semantic_hit` / `neighbor`
/ `lexical` / `speaker_match`), `rank`, and `similarity`, threaded through
`_expand_text_hits_with_neighbors`, `_lexical_segment_matches`,
`_merge_text_results`, and `_speaker_segment_context`. `_format_text_context`
renders an `[Evidence: ...]` label per segment (e.g. `Semantic Match, Rank 1,
similarity 0.82` vs `Keyword Match (literal word overlap only, not semantic
ranking)`), and `_build_chat_messages`'s system prompt now explicitly
instructs the model to trust the lowest-numbered Rank Semantic Match over
Surrounding Context or Keyword Match segments when they conflict. Scope:
`backend/routers/chat.py` only -- `search_transcript_chunks`,
`evaluate_retrieval.py`, and the visual/audio retrieval paths are untouched.

**Retest results** (same repro questions as originally logged, re-run against
the live `/api/chat/` endpoint after the fix):

- **"Why didn't you say hello when we saw each other?"** (rank 1/5) --
  **RESOLVED**. Direct Answer now cites `[01:15:30-01:15:48]` (the correct
  `start_time=4534.0` chunk) with the actual quotes ("When we were
  introduced, you acted like you didn't see me... I thought you didn't see
  me... Trust me. I saw you."), explicitly labeled "Rank 1 Semantic Match" in
  the model's own Key Analysis. Previously cited an unrelated
  girlfriend/cafeteria scene ~4406s built on a "when we met" lexical
  distractor.
- **"Why does Alex avoid mentioning his wife straight away?"** (rank 5/5,
  the weakest-ranked case) -- **RESOLVED**. Direct Answer now quotes Alex's
  actual stated reason verbatim -- "Because people feel sorry for me and
  treat me differently" -- at the exact right timestamp (`00:37:05`, matching
  `start_time=2225.0`). Previously gave a generic "recent widower, grief is
  hard to discuss" inference instead of the character's specific stated
  reason. Notable as the best result of the three despite starting from the
  weakest retrieval rank.
- **"How do you feel about the people who made it?"** (rank 3/5) --
  **PARTIALLY RESOLVED**. The correct segment (`start_time=955.56`) now
  surfaces in Key Analysis with the exact right quote ("I'm sorry, I was
  wrong, I'm happy for them, why not?... I didn't make it.") and is correctly
  labeled "Rank 3". But the Direct Answer headline still picks the rank-1
  chunk instead (an unrelated "how many more, like 50" production-quantity
  line) and declares the question "not directly answered." Cause: ranks 1-3
  for this query are all within a tight 0.60-0.62 similarity band with no
  clear winner, so the "trust the lowest-numbered rank" prompt instruction
  doesn't reliably help when the numeric top rank isn't actually the
  semantically correct one. Different in kind from the other two fixes -- a
  close three-way similarity tie, not a case of the signal being buried
  entirely. Left as a known residual limitation rather than chased further;
  fixing it would mean prompting for content relevance in addition to rank,
  a separate, smaller design problem than what this fix targeted.

---

## Chat "Direct Answer" ignored a correct retrieval hit (2026-09-04) — PARTIALLY RESOLVED, see top of file

**Question:** "How do you feel about the people who made it?"
**Video:** local test video, `video_hash=5873f064e23434b5a520eb87b9830e9cb53be89cb50cde21db60843bcaf7f6f4`

**What the retrieval eval says:** PASS. `search_transcript_chunks` returns the
correct chunk (`chunk_index=86`, `start_time=955.56`) at rank 3 of 5. That
chunk's text directly answers the question -- the speaker says they're happy
for the people who made something they didn't make themselves.

**What the chat feature's "Direct Answer" actually did:** cited three
timestamps -- `00:05:00-00:05:09`, `00:05:19-00:05:24`, and
`00:24:31-00:24:56` -- none of which are anywhere near 955.56s (~15:55) and
none of which relate to the question. The `00:05:19-00:05:24` citation is in
fact the line from the `generated-chunk-30` eval case we already dropped for
being unrelated/ambiguous. The synthesized answer was a generic,
Christmas-movie-flavored paragraph ("positive and warm... festive,
family-oriented...") built from these unrelated scraps rather than the real
line, and read as confidently correct despite being disconnected from the
actual source.

**Working hypothesis:** the core embedding retrieval (`search_transcript_chunks`)
is fine here -- verified independently by the eval harness. The chat
endpoint's answer-synthesis step (`backend/routers/chat.py`) pulls from
multiple sources beyond plain transcript search (scene/caption matches, audio
events, etc.) and something in how those are combined/prioritized for the
final LLM prompt let irrelevant material win out over the transcript hit that
actually mattered. Needs its own investigation into `routers/chat.py`'s
context-assembly and answer-generation logic -- not a retrieval bug, not
something `evaluate_retrieval.py`/`generate_cases.py` can catch by design.

**Second example (2026-09-04), with a caveat -- not retested after the fix above:**
similar pattern, different
question -- "How are you feeling now that the anticipation is almost gone?"
(`generated-chunk-426`, `start_time=3839.0`). The retrieval eval also passes
this case. The chunk itself has a direct, quotable line ("...you know that
all expectation is almost over... that's how I feel tonight."), but the
chat's Direct Answer instead gave entirely generic, ungrounded mood language
("reflective, bittersweet sentiment... quiet, contemplative aftermath...")
with **no quote and no timestamp citation anywhere in the main answer** --
not even a wrong one this time, just vibes. The scene-match thumbnails shown
alongside it were all at unrelated timestamps (01:23:10, 00:43:47, etc.),
nowhere near 3839s (~01:03:59).

Caveat, unlike the first example: this question is itself fairly generic --
it doesn't name a character, scene, or event, and this is a nearly two-hour
Christmas movie with a lot of reflective, feelings-heavy dialogue throughout.
So this may be closer in kind to the `generated-chunk-122` "party" ambiguity
(a vague question over repetitive thematic material) than to the first
example's clean case of the chat simply missing an unambiguous right answer.
The vague, non-committal response could be a *symptom* of that underlying
ambiguity rather than a pure synthesis bug independent of it. Still worth
tracking alongside the first example, but with lower confidence that it's the
exact same failure mode.

**Not investigated yet:**
- Whether this reproduces on other "how do you feel about X" / sentiment-style
  questions, or is specific to these two -- and whether the failure correlates
  more with question vagueness than with question *type* (sentiment vs.
  factual).
- Whether it's a context-window/prioritization issue (too many weak signals
  crowding out one strong one) or a retrieval issue specific to the chat
  endpoint's own search call (different from `search_transcript_chunks`'s
  parameters/top-k).

## Confirmed: "party" question is a real corpus ambiguity, not a bug (2026-09-04)

**Question:** "What are you having a party for?" (`generated-chunk-122` in
`retrieval_cases.json`, expected `start_time=1323.0`, "having a party for my
parents to celebrate their retirement").

This case is our one accepted, legitimate retrieval-eval failure (Hit@5 miss)
-- the movie has ~10 distinct scenes mentioning "a party," so a generically
phrased question doesn't disambiguate which one.

Manually testing the same question in the chat feature confirms this rather
than surfacing a new bug: the chat's Direct Answer cited `00:18:51-00:18:59`
-- a *different*, also-genuine party ("We have to have a party, a retreat
party... celebrate what you and Dad have done") -- which matches the top
wrong hit our retrieval eval already found for this exact query
(`start=1131.72`, similarity 0.6662, same "retreat party" line). Unlike the
"people who made it" finding above, this answer is internally coherent and
well-cited -- it's just answering about a different, equally real party than
the one our ground truth points to.

**Conclusion:** no action needed. This is corroborating evidence that
`generated-chunk-122`'s failure is a genuine embedding-model ceiling on
repetitive source material, not a retrieval or chat-synthesis bug -- consistent
with the decision already made to leave it in the eval set as an accepted
limitation rather than "fix" it.

## Possible frontend issue: on-screen subtitle appears clipped mid-sentence (2026-09-04)

**Not related to retrieval/eval correctness** -- filed here only because it
surfaced during manual case verification and needs its own look later.

**Observation:** screenshotting the video player during the `gingerbread-house`
case's cited moment (`00:31:48-00:31:53`) showed only a partial line ("There's
no way I can be") on screen, cut off before the rest of the sentence.

**Confirmed NOT a data/indexing bug:** both the app's own generated transcript
segment (`start=1908.0, end=1913.0`, i.e. the same `00:31:48-00:31:53` window)
and the original source `.srt` file have the **complete** sentence as a single
segment/cue ("...and decorate so many gengibre houses in time" included, same
"gengibre" typo in both independently, which is itself a small confirmation
the two sources genuinely agree rather than one copying the other's error by
coincidence). So whatever's happening is downstream of the data, in how the
frontend renders/times the subtitle overlay.

**Hypothesis, unverified:** the subtitle overlay may reveal text progressively
across a segment's display window rather than showing the full line
immediately at segment start, in which case a screenshot taken early in the
5-second window would naturally show a partial sentence -- expected behavior,
not a bug. Alternative possibility: an actual truncation/clipping bug in the
subtitle rendering component. Need to check the frontend subtitle-overlay
component to determine which.

**Not investigated yet:** which component renders the on-screen subtitle
overlay, whether it does progressive/incremental text reveal by design, and if
so whether that's the intended UX or should just show the full cue text
immediately.

## Chat confidently cited the wrong scene despite retrieval ranking the right one #1 (2026-09-04) — RESOLVED, see top of file

**Question:** "Why didn't you say hello when we saw each other?"
(`generated-chunk-499`, `start_time=4534.0`).

**What the retrieval eval says:** PASS, and not a close call -- `search_transcript_chunks`
returns the correct chunk at **rank 1** of 5 (`[4534.0, 4412.0, 563.0, 3810.0,
4387.0]`). The eval case itself is fine, no fix needed.

**What the chat's Direct Answer did:** confidently described a different scene
entirely -- a girlfriend/cafeteria confrontation around `01:13:26-01:14:18`
(~4406s, close to but not the same as the rank-2 result `4412.0`), built on a
quote containing "when we met," which overlaps lexically with the question's
"when we saw each other" but is a different exchange from our chunk 499's
actual content ("You acted like you didn't see me... I thought you didn't see
me.").

**What makes this one distinct from the first two examples above:** the
model's own "Key Analysis" text visibly hedges -- it flags a "timing
discrepancy" between its transcript citation and the visual screenshots it
pulled in, states outright "the transcript isn't entirely clear on this," and
ends up listing two different competing interpretations without picking one.
None of that uncertainty makes it into the headline "Direct Answer," which
states its (wrong) scene as plain fact. So this isn't just a retrieval/context
problem -- it's a case where the model's own internal uncertainty about its
answer doesn't propagate to what the user actually sees.

**Not investigated yet:**
- Whether the answer-synthesis step has access to the same ranked results our
  eval harness sees (i.e. did it also see the correct top-ranked chunk and
  discard it, or never receive it at all).
- Whether there's a way to surface the model's own hedging/uncertainty
  language in the UI instead of only in the collapsed "Key Analysis" section,
  so a wrong-but-confident-sounding headline answer is less likely.

## Chat gave a plausible-but-wrong reason instead of the character's actual stated one (2026-09-04) — RESOLVED, see top of file

**Question:** "Why does Alex avoid mentioning his wife straight away?"
(`alex-avoids-mentioning-wife`, `start_time=2225.0`).

**What the retrieval eval says:** PASS, but weak -- the correct chunk is only
found at **rank 5 of 5**, the most marginal pass seen in this whole set. Worth
remembering when weighing what follows: the chat's answer-synthesis may
genuinely not have had this chunk available if its own retrieval call uses a
smaller top-k or different parameters than our eval harness.

**What the chat's Direct Answer did:** explained the avoidance as generic
grief-avoidance -- "he is a recent widower... the emotional difficulty of
discussing his loss" -- built from the earlier "my wife, Laura... died a
little over a year ago" line and a behavioral inference (he mentions his
daughter freely but only mentions his wife once directly prompted).

**Why this is a real miss, not just imprecision:** the actual chunk (2225.0)
has Alex stating his reason explicitly, in his own words: "That's why I don't
mention it to anyone right away. Because people feel sorry for me and treat
me differently." That's a specific, *social* reason (avoiding pity/being
treated differently) -- meaningfully different from "grief is hard to talk
about." A user reading only the Direct Answer would come away with a
plausible-sounding but factually different understanding of Alex's own stated
motivation. Same underlying shape as the other findings here -- confident,
coherent, well-written answer that isn't actually what the source says --
just softer than the "wrong scene" example above since this one is at least
adjacent to the right scene and topic.

**Calibration caveat:** on reconsideration, this is softer than the other
findings in this file. "He's a recent widower and it's private/emotionally
difficult" is not factually wrong -- it's a reasonable, defensible
characterization consistent with the scene, just the model's own paraphrase
rather than Alex's specific words. This is closer to "the model summarized
instead of quoting" than to the other entries' "the model stated something
the source doesn't support." Keeping it logged as a real, softer-severity
example of the broader pattern (confident answers that substitute inference
for the source's specific wording), not as a clear-cut error.

**Not investigated yet:**
- Whether raising this chunk's retrieval rank (currently a marginal 5th)
  would fix this on its own, or whether the answer-synthesis step would still
  favor the inferred explanation over the explicit one even with better
  retrieval.
