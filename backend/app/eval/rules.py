from __future__ import annotations

import re
from dataclasses import dataclass, field

from app.eval.cases import EvalCase


@dataclass(frozen=True)
class RuleResult:
    name: str
    passed: bool
    score: float
    reason: str


@dataclass(frozen=True)
class EvalResult:
    case_id: str
    query: str
    passed: bool
    score: float
    rule_results: tuple[RuleResult, ...]
    failed_reasons: tuple[str, ...] = field(default_factory=tuple)


def evaluate_output(case: EvalCase, output: str) -> EvalResult:
    normalized_output = output or ""
    rule_results = (
        _expected_keywords_rule(case, normalized_output),
        _forbidden_terms_rule(case, normalized_output),
        _min_length_rule(case, normalized_output),
        _min_citations_rule(case, normalized_output),
    )
    score = sum(result.score for result in rule_results) / len(rule_results)
    failed_reasons = tuple(
        result.reason for result in rule_results if not result.passed
    )
    return EvalResult(
        case_id=case.case_id,
        query=case.query,
        passed=not failed_reasons,
        score=round(score, 4),
        rule_results=rule_results,
        failed_reasons=failed_reasons,
    )


def _expected_keywords_rule(case: EvalCase, output: str) -> RuleResult:
    if not case.expected_keywords:
        return RuleResult("expected_keywords", True, 1.0, "no expected keywords")
    matched = [
        keyword for keyword in case.expected_keywords if keyword.lower() in output.lower()
    ]
    score = len(matched) / len(case.expected_keywords)
    passed = score >= 0.8
    return RuleResult(
        "expected_keywords",
        passed,
        score,
        (
            f"matched {len(matched)}/{len(case.expected_keywords)} expected keywords"
        ),
    )


def _forbidden_terms_rule(case: EvalCase, output: str) -> RuleResult:
    hits = [term for term in case.forbidden_terms if term.lower() in output.lower()]
    passed = not hits
    return RuleResult(
        "forbidden_terms",
        passed,
        1.0 if passed else 0.0,
        "no forbidden terms" if passed else f"forbidden terms found: {', '.join(hits)}",
    )


def _min_length_rule(case: EvalCase, output: str) -> RuleResult:
    if case.min_length <= 0:
        return RuleResult("min_length", True, 1.0, "no minimum length")
    length = len(output.strip())
    score = min(length / case.min_length, 1.0)
    passed = length >= case.min_length
    return RuleResult(
        "min_length",
        passed,
        score,
        f"output length {length}/{case.min_length}",
    )


def _min_citations_rule(case: EvalCase, output: str) -> RuleResult:
    if case.min_citations <= 0:
        return RuleResult("min_citations", True, 1.0, "no citation requirement")
    citation_count = len(re.findall(r"\[\d+\]", output))
    score = min(citation_count / case.min_citations, 1.0)
    passed = citation_count >= case.min_citations
    return RuleResult(
        "min_citations",
        passed,
        score,
        f"citation count {citation_count}/{case.min_citations}",
    )
