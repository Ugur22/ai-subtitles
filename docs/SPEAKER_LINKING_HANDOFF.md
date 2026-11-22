# Speaker over-segmentation on long videos: status and next step

Status as of 2026-11-15: **not fixed.** La Casa de Papel E04 (about an hour) still comes out with 35 speakers. It should have roughly 10-15.

## How long videos are diarized

- Videos over 30 min are diarized with pyannote `speaker-diarization-3.1` in 45-minute groups (`ChunkedSpeakerDiarizer`, `DIARIZATION_CHUNK_DURATION=2700`, in `backend/speaker_diarization.py`).
- Each group gets its own `SPEAKER_00..NN` labels. The same person therefore has a different label in every group, and the groups have to be linked afterwards.
- Linking uses a **second, older model**, `pyannote/embedding` (loaded around `speaker_diarization.py:288`), to embed each group speaker. Speakers in different groups are then merged by cosine similarity.
- The threshold is `DIARIZATION_SIMILARITY_THRESHOLD` in `backend/config.py:80`. The default is 0.7, and `deploy.sh` doesn't set it.

## What was already changed (PR #15, merged)

The linking algorithm in `_match_speakers` was rewritten:

- **Average-linkage clustering** replaces greedy matching. It no longer depends on the order the groups are processed in.
- **Cannot-link rule:** two speakers from the same group are never merged (encoded as NaN in the similarity matrix).
- **Merge history:** it is computed once and replayed with union-find. `_clusters_at` can then report the speaker count at any threshold without re-clustering.
- **Calibration logs:**
  - `[SpeakerLink] ...` prints each speaker's best match per other group.
  - The sweep line prints the speaker count at 0.4/0.5/0.6/0.7 (`LINK_THRESHOLD_SWEEP`).
- Tests: `backend/tests/test_speaker_linking.py`.

## Calibration result (E04)

Job `3951f366`, Cloud Run execution `ai-subs-worker-fp88d`, completed 02:05:38.

- Per-group speaker counts: 12 / 11 / 8 / 7 (38 in total).
- Log line: `[SpeakerLink] speakers per threshold: 0.4=21 0.5=26 0.6=30 0.7=35 (using 0.7)`
- Final result: 35 unique speakers, 34 assigned to segments.

**Conclusion: tuning the threshold cannot fix this.**

- The best cross-group similarities are spread evenly between about 0.1 and 0.76. There is no gap that separates "same person" from "different person".
- Even 0.4, where different people already start to merge, leaves 21 speakers.
- Strongest links found:
  - g0 SPEAKER_06 ↔ g3: 0.755
  - g0 SPEAKER_08 ↔ g2: 0.738, ↔ g3: 0.741
  - g1 SPEAKER_03 ↔ g3: 0.736
  - g0 SPEAKER_09 ↔ g1: 0.721
- Some long speakers barely match anyone in other groups:

  | Speaker | Talk time | Best match in another group |
  |---|---|---|
  | g1 SPEAKER_08 | 104 s | 0.36 |
  | g1 SPEAKER_07 | 100 s | 0.53 |
  | g2 SPEAKER_03 | 109 s | 0.686 |

- Small extra: g0 SPEAKER_11 has 0 s of speech and no embedding. It still counts as a separate speaker; it should be dropped before linking.

## Likely root cause

The linking embeddings come from the old `pyannote/embedding` model. Within each group, the 3.1 pipeline uses a different and stronger model (WeSpeaker, `pyannote/wespeaker-voxceleb-resnet34-LM`). The old model's scores don't separate these voices well.

## Options (none started; each needs a plan and approval first)

1. **Recommended: link with the WeSpeaker model.**
   - Change the model that `speaker_diarization.py:288` loads to `pyannote/wespeaker-voxceleb-resnet34-LM`. An alternative is calling the 3.1 pipeline with `return_embeddings=True` and using its speaker centroids.
   - Then re-run E04 (about 31 GPU minutes) and check whether the sweep shows a clear gap.
   - Also check that `backend/download_models.py` bakes the model into the image. It currently doesn't bake the pyannote models.
2. **Diarize the full audio in one pass (no 15-min groups).**
   - This removes the linking problem entirely.
   - The groups exist because full-length runs timed out or ran out of memory (`docs/CHUNKED_DIARIZATION_PLAN.md`, around line 302). Those measurements may predate the L4 GPU, so benchmark first.
3. **Stopgap: threshold 0.5.**
   - Gives 26 speakers instead of 35, but merges some different people.
   - Not worth doing on its own.

## Offline premise test (2026-11-15)

Three linking fixes had failed. All of them assumed that each group label is one person, that the embedding captures who that person is, and that only the linking is wrong. That premise was tested offline on E04 with `backend/scripts/diagnose_speaker_embeddings.py`:

- CPU run.
- Spanish track 0, the same track prod picks.
- Diarization and embeddings are cached in the work dir, so a rerun takes seconds.

| Check | `pyannote/embedding` | WeSpeaker | Verdict |
|---|---|---|---|
| Gate 0: reproduce prod | groups 12/11/8/6; sweep 21/25/29/34 (prod: 12/11/8/7; 21/26/30/35) | – | Pass. The local run is the prod run; group 3 has one speaker fewer. |
| T1: split-half, 13 speakers with ≥ 30 s, 6 splits | self 0.81, within-group cross p95 0.44, gap 0.38 [0.34–0.42], own half wins 100 % | self 0.92, cross p95 0.45, gap 0.47 [0.46–0.49], 100 % | Both models tell people apart within a group. **"The old model is too weak to separate the voices" is false as stated.** |
| T2: label purity | flags g0 S00, g3 S02, g3 S03 | flags g0 S00, g2 S00 | No long label is mixed under both models. g1 SPEAKER_08 (104 s) is a clean, single voice. |
| T3: segment sampling (held-out margin) | longest-5 0.42 is the best sampler | longest-5 0.49 is the best sampler | Prod's segment choice is not the cause. |
| Same person split inside one group? | highest within-group pair 0.61 | 0.68 (both involve 6–9 s fragments) | At most 2 small fragments are blocked by cannot-link. |
| T4: linking sweep 0.4/0.5/0.6/0.7 | 21/25/29/34, no gap in merge scores larger than 0.11 | 21/22/24/29, **0.18 gap between merges at 0.59 and 0.41** | WeSpeaker gives a real gap, at about 22 speakers. |

**Conclusion:**
- Option 1 (WeSpeaker linking with a threshold in the 0.41–0.59 gap) is supported. It would take E04 from 35 to about 22 speakers.
- Nothing in the data supports 10–15. Within a group, people the diarizer already separated score up to 0.45 (p95). Reaching 15 would mean merging cross-group pairs that are no more alike than known-different people.
- **The "10–15" target has no recorded source and is now the main suspect.** Check it against ground truth by listening to the suspect clips the script writes (`<work-dir>/clips`), for example: is g1 SPEAKER_08 a character who only speaks between minutes 15 and 30?
- **Listening check (done):**
  - g1 SPEAKER_08's three clips are one man speaking alone.
  - His closest WeSpeaker matches in the other groups are 49:12 (0.54), 11:09 (0.46) and 11:53 (0.45). By ear they sound different from him.
  - So he is a character who only speaks in minutes 15–30, and not linking him was correct. That supports ~22 speakers rather than 10–15.

## Cross-source check and decision (2026-11-15)

The diagnostic was re-run on two more sources: E01, and an 80-minute Spanish-dubbed film from a different production (6 groups, 59 group speakers). The pass rules were fixed before each run.

| | E04 | E01 | Film |
|---|---|---|---|
| Separation (self minus within-group cross p95), WeSpeaker vs old | 0.47 vs 0.38 | 0.48 vs 0.33 | 0.36 vs 0.28 (spreads don't overlap) |
| Speaker-count change from 0.4 to 0.6, WeSpeaker vs old | 3 vs 8 | 4 vs 3 | 8 vs 10 |
| Empty band around 0.5 in WeSpeaker merge scores | 0.16 | 0.06 | 0.03 |
| WeSpeaker speakers at 0.5 | 22 | 22 | 27, of which 19 have ≥ 20 s (user estimate 15–20) |

**Decision: link with WeSpeaker at 0.5.**
- Better separation is the only claim that holds on every source.
- 0.5 is a middle value, not a measured gap: two of the three sources have no clean band there.
- The counts at 0.5 match the outside evidence: the listening check on E04 and the user's cast estimate for the film.
- Follow-up idea, not done: the film's 8 clusters with less than 20 s each are probably non-speech fragments, and could be hidden in the UI.

Implementation:
- `DIARIZATION_LINK_MODEL` and `DIARIZATION_SIMILARITY_THRESHOLD` in `backend/config.py`.
- Labels with 0 s of speech are dropped before linking.
- The link model and threshold are part of the diarization cache key (`_diarization_param_key` in `backend/services/background_worker.py`), so old results are recomputed rather than reused.

## Prod result after the fix (2026-11-15)

Job `c8c2a250`, Cloud Run execution `ai-subs-worker-29t4p`: a fresh run, 1798 GPU seconds.

| Check | Result |
|---|---|
| Fresh run, not cached | ✅ transcription and all 4 groups were recomputed |
| New model ran | ✅ `Loading speaker embedding model pyannote/wespeaker-voxceleb-resnet34-LM` |
| Unique speakers about 22 (19–25) | ✅ **24**, down from 35 |
| Unique speakers equal to assigned speakers | ❌ **24 unique vs 23 assigned** |

- Per-group counts were 12/11/8/7, the same as before the fix.
- Sweep: `0.3=18 0.4=21 0.5=24 0.6=25 0.7=30`.

**Why the last check fails:**
- The "0 s" speaker, g0 SPEAKER_11, isn't actually 0 s. It has 0.39 s of speech (0.37 s + 0.02 s); the log rounds it to "0s".
- The new drop rule only removes labels with exactly zero speech, so SPEAKER_11 survives.
- It has no embedding (`No valid embeddings extracted for SPEAKER_11`) and never wins a transcript line, which explains the 24 vs 23.

**Fixed:**
- `MIN_LINK_SPEECH_SECONDS = 1.0` in `backend/speaker_diarization.py`: labels with less speech than that are dropped before linking and logged as `[SpeakerLink] dropped ...`.
- The `[SpeakerLink]` log now prints seconds with one decimal, so a 0.4 s speaker can't pass as "0s" again.
- Why 1.0 s is safe: of 130 labels across the three sources, only this one is under 3 s.
- Offline on E04, using the prod linking code: the count goes from 22 to 21, and every remaining speaker has speech (the shortest has 5.9 s).
- In prod, expect about 23 unique speakers, all of them assigned.

## How to check a run

- **Find the job:** the worker is a Cloud Run Job in `ai-subs-poc` / `us-central1`. Read its execution logs and search for `[SpeakerLink]` and `Unique speakers`.
- **Test locally:** `make check` runs the linking tests offline. To try another threshold without a GPU run, read it off the sweep line of an existing run.
