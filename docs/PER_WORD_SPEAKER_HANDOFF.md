# Speaker per word in fast dialogue: status and next step

Status as of 2026-11-15: **not started.** This doc is the starting point for a new chat. Nothing is implemented. It needs plan mode and approval first (see CLAUDE.md).

## The problem

When two people trade short lines, the app credits one person's words to the other. Diarization (pyannote) gets the speakers right. The error happens afterwards, when speakers are mapped onto subtitle lines.

- `assign_speakers_to_segments` (`backend/services/background_worker.py`, around line 231) gives each Whisper segment exactly **one** speaker:
  1. it takes whoever is speaking at the segment's midpoint;
  2. only if nobody is speaking exactly then does it fall back to the speaker with the largest overlap.
- Whisper segments last about 2–8 s. In fast dialogue the speaker changes every 1–3 s, so one segment often contains both people. All of its words go to the person at the midpoint.

## Evidence

Scene: *Concetta Licata* (80-min Spanish dub), **15:00–15:45**: two women talking, plus a third voice later.

- **Pyannote (local run): correct.** It splits the scene into SPEAKER_07 (35.6 s) and SPEAKER_05 (24.9 s), with turns of 0.5–3 s.
- **Whisper large-v3** (local, `word_timestamps=True`): 6 lines averaging about 7 s, 83 words.
- **Today's line-level assignment:** **17 of 83 words (20 %) go to the wrong woman.** For example:
  - 15:09–15:15 is credited entirely to B, but *"a su lado, el día que murió."* is A's.
  - 15:15–15:20 is credited to B, but *"Cuando mi padre estaba ingresado en la clínica,"* is A's.
- **Per-word assignment (overlap with pyannote segments):** fixes those. It adds one probable error in the last line, splitting *"No, tú / no tienes la culpa"*, which one person most likely said. A smoothing step has to handle that.
- **Visualization:** https://claude.ai/code/artifact/c38870d9-a66f-4e0f-ad21-18dc85e7cb62. It shows the timeline, per-line before and after, and English translations.

Caveat: this is one 45-second scene, transcribed locally. Prod transcribes in 5-minute chunks, so prod's line boundaries may differ slightly.

### Data
- **Test fixture: `backend/tests/fixtures/per_word_speaker_scene.json`.** It holds:
  - the 27 pyannote speaker segments;
  - the 6 Whisper lines with today's line speaker;
  - the 83 words with timings and their speaker by overlap.

  Times are seconds from the start of the film. Words are stored **without** faster-whisper's leading spaces, so join them with `" "`. Today's assignment puts 17 of the 83 words on the wrong speaker.
- The whole film's pyannote groups were only in a temporary scratchpad and may be gone.

To regenerate if the data is gone:
1. Run `backend/scripts/diagnose_speaker_embeddings.py --stage diarize` on the film.
2. Cut 900–945 s from `group_1.wav`.
3. Transcribe with faster-whisper large-v3, `word_timestamps=True`, `language="es"`.
4. If the model download fails with a "Xet" error, set `HF_HUB_DISABLE_XET=1`.

## Where the code is

| What | Where |
|---|---|
| Whisper call | `_transcribe_chunk` in `services/background_worker.py` (~line 79). It returns only `start`, `end`, `text`; **words are discarded today.** |
| Whisper params | `transcribe_params` (~line 529). They are part of the transcription cache key (`settings_key(..., params=transcribe_params)`), so adding `word_timestamps` automatically invalidates old transcription caches. |
| Segment format | ~line 647: `id` (uuid), `start`, `end`, `start_time`, `end_time`, `text`, `translation` |
| Speaker assignment | `assign_speakers_to_segments` (~line 231). Called at ~line 695 (cached diarization) and ~752 (fresh). |
| After assignment | Audio analysis, translation (`TranslationService.translate_segments`, ~line 1132), screenshots and indexing all run per segment, **after** assignment. Splitting before them means they see the new segments. |
| Frontend use of `segment.id` and `segment.speaker` | `TranscriptDisplay.tsx`, `TranscriptSegmentList.tsx`, `TranscriptionUpload.tsx`, `VisualSearchPanel.tsx`, `services/api.ts` |

## Proposed approach (to be planned and approved first)

1. **Time every word:** add `word_timestamps=True` to `transcribe_params`, and keep `words` (`start`, `end`, `word`) on each segment from `_transcribe_chunk`.
2. **Give each word a speaker:** the pyannote segment with the largest overlap, or the nearest one if none overlaps.
3. **Smooth tiny runs:** a run of 1–2 words, or under a short duration, between the same speaker on both sides takes that speaker. The exact rule must be tuned on the fixture: it must fix "No, tú" without undoing real one-word replies like "¿Sí?".
4. **Split the segment** wherever the speaker changes:
   - new `id`s, and `start`/`end` from the words;
   - text joined from the words (faster-whisper words carry their own leading spaces);
   - segments with a single speaker stay unchanged.
5. Fall back to today's line-level logic when a segment has no `words`, for example a transcription cached before this change.
6. Decide whether `words` stay in the stored result or are dropped after splitting (payload size).

## Questions the plan has to answer

- **Cost:** `word_timestamps` adds alignment work to transcription. Measure GPU time on E04 before and after, per explain-the-number: run count, spread and the limiter.
- **Translation quality:** splitting creates short fragments, and fragments may translate worse.
- **Downstream volume:** more segments means more translation calls and more embeddings or index rows.
- **Frontend:** does anything assume segment boundaries match Whisper's, for example editing, subtitle export (SRT/VTT) or chapter markers?
- **Overlapping speech:** when two people talk at once, which speaker does a word get?

## Pass rules (fix before running anything)

These are suggestions; confirm them in the plan.

- **On the fixture scene:**
  - wrong words go from 17/83 to **≤ 3/83**;
  - no new segment is shorter than about 0.3 s, unless it is a whole word reply;
  - "No, tú no tienes la culpa" stays with one speaker.
- **On E04 in prod:**
  - GPU time rises by no more than an agreed limit (say +20 %);
  - the speaker count is unchanged (~23);
  - the subtitles still play and export correctly.

## Practical notes from the previous session

- **Re-uploading a processed video returns the old completed job** and nothing re-runs, because of dedup in `create_job_secure`. To re-test in prod, delete **every** job for that video first.
- **Prod logs are readable from the agent shell:** `CLOUDSDK_CONFIG=$HOME/.config/gcloud-agent gcloud logging read ...`. The worker is the Cloud Run Job `ai-subs-worker` in `ai-subs-poc` / `us-central1`. Deploys are yours, from your own terminal.
- **The sandbox blocks:** git commit and push, `gh`, local port binding (so no dev server or screenshots), and `graphify update`. Run those yourself with `!`.
- **`make check` must pass** before a task is done. Related PRs:
  - #20: WeSpeaker speaker linking.
  - #21: upload page cleanup.
