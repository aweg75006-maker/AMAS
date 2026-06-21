from app.graph.policies.researcher_policy import (
    DOCUMENT_IRRELEVANT_MESSAGE,
    DOCUMENT_ONLY_STOP_MESSAGE,
    ResearcherPolicy,
)


def test_researcher_policy_grades_only_when_documents_exist():
    policy = ResearcherPolicy()

    assert policy.decide_after_retrieval(["doc"]).should_grade is True
    assert policy.decide_after_retrieval([]).should_grade is False
    assert policy.decide_after_retrieval(None).reason == "no_documents"


def test_researcher_policy_accepts_yes_grade_only_when_grader_succeeds():
    policy = ResearcherPolicy()

    accepted = policy.decide_after_grade("YES")
    rejected = policy.decide_after_grade("NO")
    failed = policy.decide_after_grade("YES", grade_ok=False)

    assert accepted.is_relevant is True
    assert accepted.should_use_documents is True
    assert rejected.is_relevant is False
    assert rejected.message == DOCUMENT_IRRELEVANT_MESSAGE
    assert failed.is_relevant is False
    assert failed.reason == "grade_failed"


def test_researcher_policy_document_mode_stops_when_docs_are_irrelevant():
    policy = ResearcherPolicy()

    decision = policy.decide_after_rag(
        search_mode="document",
        is_doc_relevant=False,
    )

    assert decision.should_stop is True
    assert decision.should_web_search is False
    assert decision.message == DOCUMENT_ONLY_STOP_MESSAGE
    assert decision.log_event == "document_only_irrelevant"


def test_researcher_policy_hybrid_mode_allows_web_search():
    policy = ResearcherPolicy()

    relevant = policy.decide_after_rag(search_mode="hybrid", is_doc_relevant=True)
    irrelevant = policy.decide_after_rag(search_mode="hybrid", is_doc_relevant=False)
    unknown = policy.decide_after_rag(search_mode="unknown", is_doc_relevant=False)

    assert relevant.should_web_search is True
    assert relevant.log_event == "hybrid_doc_relevant"
    assert irrelevant.should_web_search is True
    assert irrelevant.log_event == "hybrid_doc_irrelevant_auto_web"
    assert unknown.should_web_search is True
