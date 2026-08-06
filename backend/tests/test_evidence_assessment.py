from app.tools.research_tools import _parse_evidence_assessment


def test_evidence_assessment_parses_structured_follow_up_queries():
    assessment = _parse_evidence_assessment(
        '{"sufficient": false, "coverage_gap": "缺少监管报告", '
        '"follow_up_queries": ["监管报告 2023", "监管报告 2023", "银行风险数据"]}'
    )

    assert assessment == {
        "sufficient": False,
        "coverage_gap": "缺少监管报告",
        "follow_up_queries": ["监管报告 2023", "银行风险数据"],
    }


def test_evidence_assessment_degrades_when_llm_returns_non_json():
    assessment = _parse_evidence_assessment("YES")

    assert assessment["sufficient"] is True
    assert assessment["follow_up_queries"] == []


def test_evidence_assessment_does_not_treat_false_string_as_true():
    assessment = _parse_evidence_assessment(
        '{"sufficient": "false", "coverage_gap": "缺少来源", "follow_up_queries": []}'
    )

    assert assessment["sufficient"] is False
