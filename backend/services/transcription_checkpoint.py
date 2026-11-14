"""Per-chunk checkpoints and the execution time budget for long jobs.

A Cloud Run GPU task is capped at one hour, so a long file is processed by a
chain of worker executions. Each finished chunk is saved to pipeline_cache;
the next execution skips what is already there.

Kept free of torch/whisper imports so it can be unit-tested offline.
"""
import hashlib
import json
import time
from typing import Any, Callable, Dict, List, Optional, Tuple

# The ffmpeg segmenter cuts at fixed multiples of this, so chunk i always
# covers [i * N, (i + 1) * N) and a retry reproduces the same chunks.
TRANSCRIPTION_CHUNK_SECONDS = 300

DEFAULT_TIME_BUDGET_SECONDS = 3000
# Left between the budget and the hard task timeout for cleanup, the
# continuation dispatch and anything that overruns its estimate.
TASK_TIMEOUT_MARGIN_SECONDS = 600
MIN_TIME_BUDGET_SECONDS = 300

MANIFEST_STAGE = "transcription_manifest"
TRANSCRIPTION_PREFIX = "transcription_chunk"
DIARIZATION_PREFIX = "diarization_group"


class ContinuationRequested(Exception):
    """Raised at a checkpoint boundary when the next unit would not fit the time budget."""


def settings_key(**settings: Any) -> str:
    """Stable short hash of everything that changes a stage's output."""
    canonical = json.dumps(settings, sort_keys=True, default=str, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]


def stage_prefix(family: str, key: str) -> str:
    return f"{family}:{key}:"


def resolve_budget_seconds(explicit: Optional[int], task_timeout: Optional[int]) -> int:
    """Explicit setting wins; otherwise derive from the task timeout; otherwise ~50 minutes."""
    if explicit and explicit > 0:
        return max(int(explicit), MIN_TIME_BUDGET_SECONDS)
    if task_timeout and task_timeout > 0:
        return max(int(task_timeout) - TASK_TIMEOUT_MARGIN_SECONDS, MIN_TIME_BUDGET_SECONDS)
    return DEFAULT_TIME_BUDGET_SECONDS


class TimeBudget:
    """Tracks wall-clock time left in this execution and whether one more unit fits."""

    def __init__(
        self,
        budget_seconds: float,
        started_at: Optional[float] = None,
        clock: Callable[[], float] = time.monotonic,
        safety_factor: float = 1.5,
    ):
        self.budget_seconds = float(budget_seconds)
        self._clock = clock
        self._started_at = clock() if started_at is None else started_at
        self._safety_factor = safety_factor
        self._slowest: Dict[str, float] = {}
        self.units_done = 0

    def elapsed(self) -> float:
        return self._clock() - self._started_at

    def remaining(self) -> float:
        return self.budget_seconds - self.elapsed()

    def record(self, kind: str, seconds: float) -> None:
        self._slowest[kind] = max(self._slowest.get(kind, 0.0), float(seconds))
        self.units_done += 1

    def estimate(self, kind: str, initial_estimate: float) -> float:
        slowest = self._slowest.get(kind)
        return initial_estimate if slowest is None else slowest * self._safety_factor

    def fits(self, kind: str, initial_estimate: float) -> bool:
        return self.remaining() > self.estimate(kind, initial_estimate)


class StageCheckpoint:
    """Indexed per-unit results for one stage, stored as pipeline_cache rows under a prefix."""

    def __init__(self, cache, user_id: str, video_hash: str, prefix: str):
        self._cache = cache
        self._user_id = user_id
        self._video_hash = video_hash
        self.prefix = prefix
        self._rows: Dict[str, Dict] = cache.get_cached_prefix(user_id, video_hash, prefix)

    def _stage(self, kind: str, index: int) -> str:
        return f"{self.prefix}{kind}:{index:04d}"

    def load(self, kind: str, index: int) -> Optional[Dict]:
        return self._rows.get(self._stage(kind, index))

    def save(self, kind: str, index: int, data: Dict) -> None:
        stage = self._stage(kind, index)
        # A failed write only costs a redo of this unit on the next run.
        if self._cache.save_cache(self._user_id, self._video_hash, stage, data):
            self._rows[stage] = data

    def count(self, kind: str) -> int:
        marker = f"{self.prefix}{kind}:"
        return sum(1 for stage in self._rows if stage.startswith(marker))

    def clear(self) -> None:
        self._cache.clear_prefix(self._user_id, self._video_hash, self.prefix)
        self._rows = {}

    def before_unit(self, kind: str, index: int) -> None:
        """Called before computing a unit that is not cached. May raise to stop the stage."""

    def after_unit(self, kind: str, index: int, seconds: float) -> None:
        """Called after a unit was computed and saved."""


class BudgetedCheckpoint(StageCheckpoint):
    """A StageCheckpoint that stops the stage when the next unit would not fit the budget."""

    def __init__(
        self,
        cache,
        user_id: str,
        video_hash: str,
        prefix: str,
        budget: TimeBudget,
        initial_estimates: Dict[str, float],
        check_cancelled: Optional[Callable[[], None]] = None,
    ):
        super().__init__(cache, user_id, video_hash, prefix)
        self._budget = budget
        self._initial_estimates = initial_estimates
        self._check_cancelled = check_cancelled

    def before_unit(self, kind: str, index: int) -> None:
        if self._check_cancelled is not None:
            self._check_cancelled()
        initial = self._initial_estimates.get(kind, 0.0)
        if not self._budget.fits(kind, initial):
            raise ContinuationRequested(
                f"{kind} {index} needs ~{self._budget.estimate(kind, initial):.0f}s "
                f"but only {self._budget.remaining():.0f}s of the time budget is left"
            )

    def after_unit(self, kind: str, index: int, seconds: float) -> None:
        self._budget.record(kind, seconds)


def merge_chunks(
    chunks: Dict[int, Dict], total_chunks: int, chunk_seconds: int = TRANSCRIPTION_CHUNK_SECONDS
) -> Tuple[List[Dict], Optional[str]]:
    """Combine chunk-local segments into one timeline.

    Each chunk stores times relative to its own start; the offset is applied
    here so a cached chunk never depends on when or where it was transcribed.
    Returns (segments, language of the first chunk that reported one).
    """
    missing = [index for index in range(total_chunks) if index not in chunks]
    if missing:
        raise ValueError(f"Cannot merge transcription: missing chunks {missing}")

    segments: List[Dict] = []
    language: Optional[str] = None
    for index in range(total_chunks):
        chunk = chunks[index]
        offset = index * chunk_seconds
        if language is None and chunk.get("language"):
            language = chunk["language"]
        for segment in chunk.get("segments", []):
            segments.append({
                "start": segment["start"] + offset,
                "end": segment["end"] + offset,
                "text": segment["text"],
            })
    return segments, language


def projected_executions(projected_seconds: float, budget_seconds: float) -> int:
    if budget_seconds <= 0:
        return 1
    return max(1, int(-(-projected_seconds // budget_seconds)))
