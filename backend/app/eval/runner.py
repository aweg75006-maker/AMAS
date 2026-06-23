from __future__ import annotations

import argparse
import json
import time
from dataclasses import asdict, dataclass
from pathlib import Path

from app.eval.cases import EvalCase, get_builtin_cases
from app.eval.rules import EvalResult, evaluate_output


@dataclass(frozen=True)
class EvalSummary:
    total_cases: int
    passed_cases: int
    failed_cases: int
    pass_rate: float
    average_score: float
    elapsed_ms: int
    results: tuple[EvalResult, ...]


def run_eval_cases(cases: tuple[EvalCase, ...]) -> EvalSummary:
    started_at = time.time()
    results = tuple(evaluate_output(case, case.sample_output) for case in cases)
    passed_cases = sum(1 for result in results if result.passed)
    total_cases = len(results)
    average_score = (
        sum(result.score for result in results) / total_cases if total_cases else 0.0
    )
    return EvalSummary(
        total_cases=total_cases,
        passed_cases=passed_cases,
        failed_cases=total_cases - passed_cases,
        pass_rate=round(passed_cases / total_cases, 4) if total_cases else 0.0,
        average_score=round(average_score, 4),
        elapsed_ms=int((time.time() - started_at) * 1000),
        results=results,
    )


def run_builtin_eval() -> EvalSummary:
    return run_eval_cases(get_builtin_cases())


def summary_to_dict(summary: EvalSummary) -> dict:
    return asdict(summary)


def main() -> None:
    parser = argparse.ArgumentParser(description="Run lightweight Agent evals.")
    parser.add_argument(
        "--output",
        type=str,
        default="",
        help="Optional JSON output path.",
    )
    args = parser.parse_args()

    summary = run_builtin_eval()
    payload = summary_to_dict(summary)
    print(
        "Agent eval completed: "
        f"{summary.passed_cases}/{summary.total_cases} passed, "
        f"pass_rate={summary.pass_rate:.0%}, "
        f"average_score={summary.average_score:.3f}"
    )
    for result in summary.results:
        status = "PASS" if result.passed else "FAIL"
        print(f"- {status} {result.case_id}: score={result.score:.3f}")
        for reason in result.failed_reasons:
            print(f"  - {reason}")

    if args.output:
        output_path = Path(args.output)
        output_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        print(f"Saved eval summary to {output_path}")


if __name__ == "__main__":
    main()
