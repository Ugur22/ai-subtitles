"""
Offline check of the cross-group speaker-linking premise (docs/SPEAKER_LINKING_HANDOFF.md).

Reproduces the chunked diarizer's per-group diarization on a local video, then
asks whether the linking embeddings can tell people apart at all, before any
linking fix is attempted:

  Gate 0  local run reproduces prod (per-group counts, threshold sweep)
  T1      split-half: do two halves of one speaker match each other better
          than other speakers of the same group?
  T2      purity: do a label's own segments agree with each other?
  T3      sampling: do the 5 longest segments (prod) represent the speaker?
  T4      end to end: linking sweep per embedder x sampler

Usage (from backend/):
  venv/bin/python -m scripts.diagnose_speaker_embeddings --video E04.mkv --work-dir DIR
  [--stage diarize|analyze|all] [--force-diarize]

Diarization (slow on CPU) and embeddings are cached in the work dir, so
re-running the analysis costs seconds.
"""

import argparse
import json
import os
import subprocess
import sys
from itertools import combinations
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from speaker_diarization import ChunkedSpeakerDiarizer  # noqa: E402  (patches torch.load for pyannote)

INPUT_CHUNK_SECONDS = 300
EMBEDDERS = ("pyannote/embedding", "pyannote/wespeaker-voxceleb-resnet34-LM")
MIN_SEGMENT_SECONDS = 0.5
MAX_SEGMENTS_PER_SPEAKER = 60
T1_MIN_TALK_SECONDS = 30.0
RANDOM_REPEATS = 5
SWEEP = (0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8)

# E04 prod run (job 3951f366): --prod-counts 12,11,8,7 --prod-sweep 0.4=21,0.5=26,0.6=30,0.7=35


def log(line: str = "", report: list = None) -> None:
    print(line, flush=True)
    if report is not None:
        report.append(line)


# --------------------------------------------------------------------------- audio + diarization

def extract_chunks(video: Path, chunk_dir: Path) -> list:
    chunks = sorted(chunk_dir.glob("audio_*.wav"))
    if chunks:
        return [str(c) for c in chunks]
    chunk_dir.mkdir(parents=True, exist_ok=True)
    # Same parameters as services/audio_service.py; prod has no -map, so ffmpeg takes track 0 (Spanish).
    subprocess.run([
        "ffmpeg", "-v", "error", "-y", "-i", str(video), "-map", "0:a:0", "-vn",
        "-acodec", "pcm_s16le", "-ar", "16000", "-ac", "1",
        "-f", "segment", "-segment_time", str(INPUT_CHUNK_SECONDS), "-reset_timestamps", "1",
        str(chunk_dir / "audio_%03d.wav"),
    ], check=True)
    return [str(c) for c in sorted(chunk_dir.glob("audio_*.wav"))]


def diarize_groups(work: Path, chunks: list, token: str, force: bool) -> list:
    diarizer = ChunkedSpeakerDiarizer(use_auth_token=token)
    groups = diarizer._group_chunks(chunks, INPUT_CHUNK_SECONDS)
    results = []
    for i, group in enumerate(groups):
        audio = work / f"group_{i}.wav"
        seg_file = work / f"segments_g{i}.json"
        if not audio.exists():
            diarizer._concatenate_audio_files(group["chunks"], str(audio))
        if force or not seg_file.exists():
            diarizer.load_pipeline()
            print(f"[diarize] group {i} ({len(group['chunks'])} chunks, offset {group['time_offset']}s)", flush=True)
            result = diarizer._diarize_group_with_preconcat(str(audio), False, group["time_offset"])
            seg_file.write_text(json.dumps(result["segments"]))
        results.append({"audio": str(audio), "segments": json.loads(seg_file.read_text())})
    diarizer.unload_pipeline()
    return results


# --------------------------------------------------------------------------- embeddings

def embed_segments(work: Path, groups: list, embedder: str, token: str) -> list:
    """Per group: {segment index: raw embedding}. Cached per embedder."""
    import torch
    from pyannote.audio import Inference, Model
    from pyannote.core import Segment

    tag = embedder.split("/")[-1]
    inference = None
    out = []
    rng = np.random.default_rng(0)
    for i, group in enumerate(groups):
        cache = work / f"emb_{tag}_g{i}.npz"
        if cache.exists():
            data = np.load(cache)
            out.append({int(k): data["vectors"][n] for n, k in enumerate(data["index"])})
            continue
        if inference is None:
            model = Model.from_pretrained(embedder, use_auth_token=token)
            inference = Inference(model, window="whole", device=torch.device("cpu"))
        wanted = []
        for label, idx in by_speaker(group["segments"]).items():
            segs = group["segments"]
            longest = sorted(idx, key=lambda j: duration(segs[j]), reverse=True)
            # Prod's exact pick (longest 5, fallback longest) must always be embedded for Gate 0.
            keep = set(prod_longest5(segs, idx))
            usable = [j for j in idx if duration(segs[j]) >= MIN_SEGMENT_SECONDS and j not in keep]
            room = MAX_SEGMENTS_PER_SPEAKER - len(keep)
            if len(usable) > room:
                usable = list(rng.choice(usable, size=room, replace=False))
            keep.update(usable)
            if not keep:
                keep = {longest[0]}
            wanted.extend(sorted(int(j) for j in keep))
        vectors, index = [], []
        print(f"[embed] {tag} group {i}: {len(wanted)} segments", flush=True)
        for j in wanted:
            seg = group["segments"][j]
            try:
                v = inference.crop(group["audio"], Segment(seg["local_start"], seg["local_end"]))
            except Exception as e:  # very short segments can be shorter than the model's receptive field
                print(f"  skip segment {j} ({duration(seg):.2f}s): {e}")
                continue
            v = np.asarray(v, dtype=float).reshape(-1)
            if not np.all(np.isfinite(v)):
                continue
            vectors.append(v)
            index.append(j)
        np.savez(cache, vectors=np.array(vectors), index=np.array(index))
        out.append(dict(zip(index, vectors)))
    return out


# --------------------------------------------------------------------------- helpers

def duration(seg: dict) -> float:
    return seg["local_end"] - seg["local_start"]


def by_speaker(segments: list) -> dict:
    out = {}
    for j, seg in enumerate(segments):
        out.setdefault(seg["speaker"], []).append(j)
    return out


def prod_longest5(segs: list, idx: list) -> list:
    """Mirror of _extract_speaker_embeddings' selection."""
    longest = sorted(idx, key=lambda j: duration(segs[j]), reverse=True)
    pick = [j for j in longest[:5] if duration(segs[j]) >= MIN_SEGMENT_SECONDS]
    return pick or longest[:1]


def unit(v: np.ndarray) -> np.ndarray:
    return v / (np.linalg.norm(v) + 1e-8)


def mean_vec(emb: dict, idx) -> np.ndarray:
    vs = [emb[j] for j in idx if j in emb]
    return unit(np.mean(vs, axis=0)) if vs else None


def overlapping(segs: list, j: int) -> bool:
    s = segs[j]
    return any(
        k != j and o["speaker"] != s["speaker"] and o["local_start"] < s["local_end"] and s["local_start"] < o["local_end"]
        for k, o in enumerate(segs)
    )


def stats(values) -> str:
    v = np.asarray(values, dtype=float)
    if v.size == 0:
        return "n/a"
    return f"median {np.median(v):.3f} [min {v.min():.3f}, max {v.max():.3f}]"


# --------------------------------------------------------------------------- samplers (T3/T4)

def make_samplers(segs: list, emb: dict) -> dict:
    """name -> list of callables(idx) -> chosen segment indices (several for random samplers)."""
    def embedded(idx):
        return [j for j in idx if j in emb and duration(segs[j]) >= MIN_SEGMENT_SECONDS] or [j for j in idx if j in emb]

    def longest5(idx):
        return prod_longest5(segs, idx)

    def median5(idx):
        cand = sorted(embedded(idx), key=lambda j: duration(segs[j]))
        mid = len(cand) // 2
        return cand[max(0, mid - 2): mid + 3]

    def clean5(idx):
        cand = [j for j in embedded(idx) if not overlapping(segs, j)]
        return sorted(cand, key=lambda j: duration(segs[j]), reverse=True)[:5] or longest5(idx)

    def random5(seed):
        def pick(idx):
            cand = embedded(idx)
            if len(cand) <= 5:
                return cand
            return list(np.random.default_rng(seed).choice(cand, size=5, replace=False))
        return pick

    def all_capped(idx):
        return embedded(idx)

    return {
        "longest5 (prod)": [longest5],
        "median5": [median5],
        "clean5 (no overlap)": [clean5],
        "random5": [random5(s) for s in range(RANDOM_REPEATS)],
        "all (<=60)": [all_capped],
    }


# --------------------------------------------------------------------------- tests

def t1_split_half(groups, embs, report):
    """Per split: median self-sim, p95 within-group cross-sim, fraction whose own half wins."""
    per_split = []
    splits = ["odd/even"] + [f"random{s}" for s in range(RANDOM_REPEATS)]
    for split in splits:
        selfs, crosses, wins, n = [], [], 0, 0
        for g, (group, emb) in enumerate(zip(groups, embs)):
            segs = group["segments"]
            halves = {}
            for label, idx in by_speaker(segs).items():
                talk = sum(duration(segs[j]) for j in idx)
                cand = sorted([j for j in idx if j in emb], key=lambda j: segs[j]["local_start"])
                if talk < T1_MIN_TALK_SECONDS or len(cand) < 4:
                    continue
                if split == "odd/even":
                    a, b = cand[0::2], cand[1::2]
                else:
                    perm = np.random.default_rng(int(split[6:]) + 100 * g).permutation(cand)
                    a, b = perm[: len(cand) // 2], perm[len(cand) // 2:]
                halves[label] = (mean_vec(emb, a), mean_vec(emb, b))
            for label, (a, b) in halves.items():
                own = float(a @ b)
                others = [float(a @ ob) for other, (_, ob) in halves.items() if other != label]
                selfs.append(own)
                crosses.extend(others)
                n += 1
                wins += int(not others or own > max(others))
        p95 = float(np.percentile(crosses, 95)) if crosses else float("nan")
        per_split.append({"self": float(np.median(selfs)) if selfs else float("nan"), "p95": p95,
                          "gap": (float(np.median(selfs)) - p95) if selfs else float("nan"),
                          "win": wins / n if n else float("nan"), "n": n})
    log(f"  speakers tested (>= {T1_MIN_TALK_SECONDS:.0f}s talk, >= 4 segments): {per_split[0]['n']}", report)
    log(f"  self-sim (median)        : {stats([s['self'] for s in per_split])}", report)
    log(f"  within-group cross p95   : {stats([s['p95'] for s in per_split])}", report)
    log(f"  gap = self - cross p95   : {stats([s['gap'] for s in per_split])}", report)
    log(f"  own half matches best    : {stats([s['win'] for s in per_split])}", report)
    return per_split


def t2_purity(groups, embs, report):
    """Mean pairwise segment similarity inside a label vs between labels of the same group."""
    rows, flagged = [], []
    for g, (group, emb) in enumerate(zip(groups, embs)):
        segs = group["segments"]
        units = {label: [unit(emb[j]) for j in idx if j in emb and duration(segs[j]) >= 1.0]
                 for label, idx in by_speaker(segs).items()}
        units = {k: v for k, v in units.items() if len(v) >= 4}
        cross = [float(np.mean([a @ b for a in units[s] for b in units[t]])) for s, t in combinations(units, 2)]
        bar = float(np.percentile(cross, 95)) if cross else float("nan")
        for label, vs in units.items():
            purity = float(np.mean([a @ b for a, b in combinations(vs, 2)]))
            talk = sum(duration(segs[j]) for j in by_speaker(segs)[label])
            rows.append((g, label, talk, purity, bar))
            if purity < bar:
                flagged.append((g, label))
    log(f"  {'speaker':<16}{'talk':>7}{'purity':>9}{'group cross p95':>17}", report)
    for g, label, talk, purity, bar in sorted(rows, key=lambda r: r[3]):
        mark = "  <-- below bar" if purity < bar else ""
        log(f"  g{g} {label:<13}{talk:>6.0f}s{purity:>9.3f}{bar:>17.3f}{mark}", report)
    return flagged


def t3_sampling(groups, embs, report):
    """Held-out margin: sampler's 5 segments vs the speaker's other segments, minus best other speaker."""
    results = {}
    for name in make_samplers(groups[0]["segments"], embs[0]):
        margins_per_repeat = []
        repeats = len(make_samplers(groups[0]["segments"], embs[0])[name])
        for r in range(repeats):
            margins = []
            for group, emb in zip(groups, embs):
                segs = group["segments"]
                pick = make_samplers(segs, emb)[name][r]
                spk = by_speaker(segs)
                chosen = {label: pick(idx) for label, idx in spk.items()}
                held = {label: [j for j in idx if j in emb and j not in set(chosen[label])] for label, idx in spk.items()}
                held_vec = {k: mean_vec(emb, v) for k, v in held.items() if len(v) >= 3}
                for label in held_vec:
                    if sum(duration(segs[j]) for j in spk[label]) < T1_MIN_TALK_SECONDS:
                        continue
                    sample = mean_vec(emb, chosen[label])
                    if sample is None or len(held_vec) < 2:
                        continue
                    own = float(sample @ held_vec[label])
                    best_other = max(float(sample @ v) for k, v in held_vec.items() if k != label)
                    margins.append(own - best_other)
            margins_per_repeat.append(margins)
        med = [float(np.median(m)) for m in margins_per_repeat if m]
        pos = [float(np.mean(np.array(m) > 0)) for m in margins_per_repeat if m]
        results[name] = med
        log(f"  {name:<22} margin {stats(med):<46} own-wins {stats(pos)}", report)
    return results


def link(groups, emb_by_group, sampler_name, repeat=0):
    speakers, vectors = [], []
    for g, (group, emb) in enumerate(zip(groups, emb_by_group)):
        segs = group["segments"]
        pick = make_samplers(segs, emb)[sampler_name][repeat]
        for label, idx in sorted(by_speaker(segs).items()):
            seconds = sum(seg["end"] - seg["start"] for seg in (segs[j] for j in idx))
            speakers.append({"group": g, "label": label, "seconds": seconds})
            vectors.append(mean_vec(emb, pick(idx)))
    group_of = np.array([s["group"] for s in speakers])
    sim = ChunkedSpeakerDiarizer._similarity_matrix(vectors, group_of)
    history = ChunkedSpeakerDiarizer._merge_history(sim, min(SWEEP))
    sweep = {t: len(ChunkedSpeakerDiarizer._clusters_at(len(speakers), history, t)) for t in SWEEP}
    best = []
    for i in range(len(speakers)):
        row = sim[i]
        best.append(float(np.nanmax(row)) if not np.isnan(row).all() else float("nan"))
    return speakers, sweep, history, best


def histogram(values) -> str:
    v = np.asarray([x for x in values if np.isfinite(x)])
    edges = np.arange(-0.1, 1.01, 0.1)
    counts, _ = np.histogram(np.clip(v, -0.1, 0.999), bins=edges)
    return " ".join(f"{edges[k]:.1f}:{c}" for k, c in enumerate(counts) if c or edges[k] >= 0)


def biggest_gap(history) -> str:
    scores = [h[0] for h in history]
    if len(scores) < 2:
        return "n/a"
    diffs = [(scores[k] - scores[k + 1], scores[k], scores[k + 1]) for k in range(len(scores) - 1)]
    d, hi, lo = max(diffs)
    return f"{d:.3f} between merges at {hi:.3f} and {lo:.3f}"


def t4_link(groups, embs, embedder, report):
    out = {}
    for name in make_samplers(groups[0]["segments"], embs[0]):
        repeats = len(make_samplers(groups[0]["segments"], embs[0])[name])
        sweeps = []
        for r in range(repeats):
            speakers, sweep, history, best = link(groups, embs, name, r)
            sweeps.append(sweep)
        line = " ".join(f"{t}={'/'.join(str(s[t]) for s in sweeps)}" for t in SWEEP)
        log(f"  {name:<22} speakers per threshold: {line}", report)
        speakers, sweep, history, best = link(groups, embs, name, 0)
        log(f"  {'':<22} best cross-group match histogram: {histogram(best)}", report)
        log(f"  {'':<22} largest drop between consecutive merges: {biggest_gap(history)}", report)
        out[name] = (speakers, sweeps, best)
    return out


# --------------------------------------------------------------------------- listen clips

def write_clips(work: Path, groups: list, targets: list, report: list) -> None:
    clip_dir = work / "clips"
    clip_dir.mkdir(exist_ok=True)
    for g, label in targets:
        segs = groups[g]["segments"]
        idx = sorted(by_speaker(segs).get(label, []), key=lambda j: duration(segs[j]), reverse=True)
        # Spread over the group, not just the 3 longest, so a mixed label is audible.
        picks = idx[:1] + idx[len(idx) // 3: len(idx) // 3 + 1] + idx[2 * len(idx) // 3: 2 * len(idx) // 3 + 1]
        for n, j in enumerate(dict.fromkeys(picks)):
            s = segs[j]
            out = clip_dir / f"g{g}_{label}_{n}_{s['start']:.0f}s.wav"
            subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", f"{s['local_start']:.2f}",
                            "-t", f"{min(duration(s), 8):.2f}", "-i", groups[g]["audio"], str(out)], check=True)
    log(f"  clips: {clip_dir}", report)


# --------------------------------------------------------------------------- main

def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--video", required=True, type=Path)
    ap.add_argument("--work-dir", type=Path, default=Path(os.environ.get("TMPDIR", "/tmp")) / "speaker_diag")
    ap.add_argument("--stage", choices=("diarize", "analyze", "all"), default="all")
    ap.add_argument("--force-diarize", action="store_true")
    ap.add_argument("--prod-counts", help="Gate 0: prod per-group speaker counts, e.g. 12,11,8,7")
    ap.add_argument("--prod-sweep", help="Gate 0: prod sweep, e.g. 0.4=21,0.5=26,0.6=30,0.7=35")
    args = ap.parse_args()
    prod_counts = tuple(int(x) for x in args.prod_counts.split(",")) if args.prod_counts else None
    prod_sweep = ({float(k): int(v) for k, v in (kv.split("=") for kv in args.prod_sweep.split(","))}
                  if args.prod_sweep else None)

    from dotenv import load_dotenv
    load_dotenv(Path(__file__).resolve().parent.parent / ".env")
    token = os.environ.get("HUGGINGFACE_TOKEN")
    work = args.work_dir
    work.mkdir(parents=True, exist_ok=True)

    chunks = extract_chunks(args.video, work / "chunks")
    groups = diarize_groups(work, chunks, token, args.force_diarize)
    if args.stage == "diarize":
        return

    report = []
    log(f"# Speaker-linking diagnostic: {args.video.name}", report)
    log(f"chunks: {len(chunks)} x {INPUT_CHUNK_SECONDS}s, groups: {len(groups)}", report)

    counts = tuple(len(by_speaker(g["segments"])) for g in groups)
    log(f"\n## Gate 0: reproduction (prod counts {prod_counts}, sweep {prod_sweep})", report)
    log(f"  local per-group speaker counts: {counts}", report)
    if not (prod_counts and prod_sweep):
        log("  skipped: no --prod-counts/--prod-sweep given", report)

    flagged_all = []
    for embedder in EMBEDDERS:
        embs = embed_segments(work, groups, embedder, token)
        log(f"\n# Embedder: {embedder}", report)
        log(f"  embedded segments per group: {[len(e) for e in embs]}", report)
        log("\n## T4: end-to-end linking (prod algorithm), per sampler; random5 shows each repeat", report)
        t4 = t4_link(groups, embs, embedder, report)
        if embedder == "pyannote/embedding":
            if prod_counts and prod_sweep:
                sweep = t4["longest5 (prod)"][1][0]
                local = {t: sweep[t] for t in prod_sweep}
                ok_counts = len(counts) == len(prod_counts) and all(abs(a - b) <= 1 for a, b in zip(counts, prod_counts))
                ok_sweep = all(abs(local[t] - prod_sweep[t]) <= 3 for t in prod_sweep)
                log(f"  Gate 0 sweep local {local} vs prod {prod_sweep}: counts {'OK' if ok_counts else 'DIFFER'}, "
                    f"sweep {'OK' if ok_sweep else 'DIFFER'}", report)
            speakers, _, best = t4["longest5 (prod)"]
            weak = [(s["group"], s["label"]) for s, b in zip(speakers, best) if s["seconds"] >= 60 and (not np.isfinite(b) or b < 0.55)]
            flagged_all.extend(weak)
        log("\n## T1: split-half (odd/even + random splits; spread is across the splits)", report)
        t1_split_half(groups, embs, report)
        log("\n## T2: label purity (mean pairwise segment sim, segments >= 1s)", report)
        flagged_all.extend(t2_purity(groups, embs, report))
        log("\n## T3: sampling, held-out margin (sample vs own other segments minus best other speaker)", report)
        t3_sampling(groups, embs, report)

    targets = list(dict.fromkeys(flagged_all))[:12]
    log(f"\n## Listen: long speakers with weak links or impure labels: {targets}", report)
    write_clips(work, groups, targets, report)
    (work / "report.txt").write_text("\n".join(report) + "\n")
    print(f"\nreport: {work / 'report.txt'}")


if __name__ == "__main__":
    main()
