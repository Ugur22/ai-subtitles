"""
Reporting CLI over the local evaluation-history database written by
evaluate_chat.py (see evals/eval_history_db.py for the schema).

Usage (run from backend/):
    python evals/report_eval_history.py --latest
    python evals/report_eval_history.py --latest --case-file evals/chat_cases.json
    python evals/report_eval_history.py --run-id 3
    python evals/report_eval_history.py --compare 2 3
    python evals/report_eval_history.py --analysis   # cross-run SQL analysis views
"""

import argparse
import sys
from pathlib import Path
from typing import Any, Dict

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import eval_history_db


def _print_run_summary(run: Dict[str, Any]) -> None:
    print(f"Run id:                    {run['id']}")
    print(f"Created at:                {run['created_at']}")
    print(f"Label:                     {run['label'] or '-'}")
    print(f"Git commit:                {run['git_commit'] or '-'}")
    print(f"Case file:                 {run['case_file']}")
    print(f"Movie/video_hash:          {run['video_hash'] or '-'}")
    print(f"Provider:                  {run['provider'] or '-'}")
    print(f"Model:                     {run['model'] or '-'}")
    print(f"Index config:              {run['index_config'] or '-'}")
    print(f"Top-k:                     {run['top_k'] if run['top_k'] is not None else '-'}")
    print(f"Total cases:               {run['total_cases']}")
    print(f"Passed:                    {run['passed']}")
    print(f"Failed:                    {run['failed']}")
    print(f"Errors:                    {run['errors']}")
    print(f"Answer-correctness rate:   {run['answer_correctness_rate']:.1f}%")
    print(f"Citation-correctness rate: {run['citation_correctness_rate']:.1f}%")
    print(f"Total duration (s):        {run['total_duration_seconds']:.1f}")
    print(f"Average duration (s):      {run['average_duration_seconds']:.2f}")
    if run["prompt_tokens"] is not None or run["completion_tokens"] is not None:
        print(f"Prompt tokens:             {run['prompt_tokens'] if run['prompt_tokens'] is not None else '-'}")
        print(f"Completion tokens:         {run['completion_tokens'] if run['completion_tokens'] is not None else '-'}")
    if run["estimated_cost"] is not None:
        print(f"Estimated cost:            ${run['estimated_cost']:.4f}")


def _print_single_run(conn, run: Dict[str, Any]) -> None:
    _print_run_summary(run)
    if run["failed"] or run["errors"]:
        print()
        print("Non-passing cases:")
        for row in eval_history_db.get_case_results(conn, run["id"]):
            if row["status"] == "passed":
                continue
            print(f"  [{row['status'].upper()}] {row['case_id']}: {row['failure_reason'] or '-'}")


def _print_comparison(comparison: Dict[str, Any]) -> None:
    baseline, candidate = comparison["baseline"], comparison["candidate"]

    print("=== Baseline ===")
    _print_run_summary(baseline)
    print()
    print("=== Candidate ===")
    _print_run_summary(candidate)
    print()

    print("=== Diff ===")
    print(f"Passed:   {baseline['passed']} -> {candidate['passed']}")
    print(f"Failed:   {baseline['failed']} -> {candidate['failed']}")
    print(f"Errors:   {baseline['errors']} -> {candidate['errors']}")
    print(
        f"Answer-correctness rate:   {baseline['answer_correctness_rate']:.1f}% -> "
        f"{candidate['answer_correctness_rate']:.1f}%"
    )
    print(
        f"Citation-correctness rate: {baseline['citation_correctness_rate']:.1f}% -> "
        f"{candidate['citation_correctness_rate']:.1f}%"
    )
    print(
        f"Average duration (s):     {baseline['average_duration_seconds']:.2f} -> "
        f"{candidate['average_duration_seconds']:.2f}"
    )

    print()
    print(f"Newly fixed cases ({len(comparison['fixed_cases'])}):")
    for entry in comparison["fixed_cases"]:
        print(f"  {entry['case_id']}: {entry['baseline_status']} -> {entry['candidate_status']}")

    print()
    print(f"Newly failing cases ({len(comparison['regressed_cases'])}):")
    for entry in comparison["regressed_cases"]:
        print(f"  {entry['case_id']}: {entry['baseline_status']} -> {entry['candidate_status']}")

    print()
    print(
        "Provider errors (infrastructure/transport signal, not counted as answer-quality "
        "regressions):"
    )
    print(f"  New:      {len(comparison['new_provider_errors'])}")
    for entry in comparison["new_provider_errors"]:
        print(f"    {entry['case_id']}: {entry['baseline_status']} -> {entry['candidate_status']}")
    print(f"  Resolved: {len(comparison['resolved_provider_errors'])}")
    for entry in comparison["resolved_provider_errors"]:
        print(f"    {entry['case_id']}: {entry['baseline_status']} -> {entry['candidate_status']}")

    if any(
        comparison[k] is not None
        for k in ("prompt_tokens_delta", "completion_tokens_delta", "estimated_cost_delta")
    ):
        print()
        print("Token/cost deltas (candidate - baseline):")
        if comparison["prompt_tokens_delta"] is not None:
            print(f"  Prompt tokens:     {comparison['prompt_tokens_delta']:+.0f}")
        if comparison["completion_tokens_delta"] is not None:
            print(f"  Completion tokens: {comparison['completion_tokens_delta']:+.0f}")
        if comparison["estimated_cost_delta"] is not None:
            print(f"  Estimated cost:    {comparison['estimated_cost_delta']:+.4f}")


def _print_analysis(conn) -> None:
    print("=== Cases failing most frequently ===")
    for row in eval_history_db.cases_failing_most_frequently(conn):
        print(
            f"  {row['case_id']}: {row['failure_count']}/{row['total_runs']} runs "
            f"({row['failure_rate_pct']}%) -- {row['question']}"
        )

    print()
    print("=== Results by movie ===")
    for row in eval_history_db.results_by_movie(conn):
        print(
            f"  {row['video_hash'] or '-'}: {row['total_passed']} passed / "
            f"{row['total_failed']} failed / {row['total_errors']} errors across "
            f"{row['total_runs']} runs (avg answer-correctness {row['avg_answer_correctness_rate']}%)"
        )

    print()
    print("=== Results by model/provider ===")
    for row in eval_history_db.results_by_model_provider(conn):
        print(
            f"  {row['provider'] or '-'}/{row['model'] or '-'}: {row['total_passed']} passed / "
            f"{row['total_failed']} failed / {row['total_errors']} errors across "
            f"{row['total_runs']} runs"
        )

    print()
    print("=== Average latency by model ===")
    for row in eval_history_db.average_latency_by_model(conn):
        print(f"  {row['provider'] or '-'}/{row['model'] or '-'}: {row['avg_latency_seconds']}s avg")

    print()
    print("=== Provider error rate ===")
    for row in eval_history_db.provider_error_rate(conn):
        print(f"  {row['provider'] or '-'}: {row['error_rate_pct']}% ({row['total_errors']}/{row['total_cases']})")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--db",
        default="evals/eval_history.db",
        help="Path to the evaluation-history SQLite database (default: evals/eval_history.db)",
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--latest", action="store_true", help="Show the most recent run")
    group.add_argument("--run-id", type=int, help="Show a specific run by id")
    group.add_argument(
        "--compare", nargs=2, type=int, metavar=("BASELINE_ID", "CANDIDATE_ID"),
        help="Compare two runs by id",
    )
    group.add_argument("--analysis", action="store_true", help="Print cross-run SQL analysis views")
    parser.add_argument(
        "--case-file", default=None,
        help="With --latest, restrict to runs of this case file",
    )
    args = parser.parse_args()

    conn = eval_history_db.get_connection(args.db)
    try:
        if args.latest:
            run = eval_history_db.get_latest_run(conn, case_file=args.case_file)
            if run is None:
                print("No runs found in history db.")
                return 1
            _print_single_run(conn, run)
        elif args.run_id is not None:
            run = eval_history_db.get_run(conn, args.run_id)
            if run is None:
                print(f"No run with id={args.run_id}")
                return 1
            _print_single_run(conn, run)
        elif args.compare is not None:
            baseline_id, candidate_id = args.compare
            comparison = eval_history_db.compare_runs(conn, baseline_id, candidate_id)
            _print_comparison(comparison)
        elif args.analysis:
            _print_analysis(conn)
    except ValueError as e:
        print(f"Error: {e}")
        return 1
    finally:
        conn.close()

    return 0


if __name__ == "__main__":
    sys.exit(main())
