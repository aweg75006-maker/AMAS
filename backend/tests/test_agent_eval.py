from app.eval.cases import EvalCase, get_builtin_cases
from app.eval.rules import evaluate_output
from app.eval.runner import run_builtin_eval, run_eval_cases, summary_to_dict


def test_eval_case_rules_pass_for_grounded_output():
    case = EvalCase(
        case_id="case_1",
        query="如何治理 Agent？",
        expected_keywords=("trace", "审计"),
        forbidden_terms=("编造",),
        min_length=20,
        min_citations=1,
    )

    result = evaluate_output(case, "Agent 需要 trace 和审计能力，并保留来源 [1]。")

    assert result.passed is True
    assert result.score == 1.0
    assert result.failed_reasons == ()


def test_eval_case_rules_fail_with_readable_reasons():
    case = EvalCase(
        case_id="case_2",
        query="如何降低幻觉？",
        expected_keywords=("引用", "检索"),
        forbidden_terms=("编造",),
        min_length=20,
        min_citations=1,
    )

    result = evaluate_output(case, "可以编造。")

    assert result.passed is False
    assert any("matched 0/2" in reason for reason in result.failed_reasons)
    assert any("forbidden terms found" in reason for reason in result.failed_reasons)
    assert any("citation count 0/1" in reason for reason in result.failed_reasons)


def test_run_eval_cases_generates_summary():
    cases = (
        EvalCase(
            case_id="case_1",
            query="q",
            expected_keywords=("hello",),
            min_length=5,
            sample_output="hello world",
        ),
    )

    summary = run_eval_cases(cases)
    payload = summary_to_dict(summary)

    assert summary.total_cases == 1
    assert summary.passed_cases == 1
    assert summary.pass_rate == 1.0
    assert payload["results"][0]["case_id"] == "case_1"


def test_builtin_agent_eval_cases_are_valid():
    cases = get_builtin_cases()
    summary = run_builtin_eval()

    assert len(cases) >= 3
    assert summary.total_cases == len(cases)
    assert summary.pass_rate == 1.0
    assert summary.average_score >= 0.95
