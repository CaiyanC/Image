from app.services.customer_service_semantic_rag_v2_service import (
    _answer_resolved_identity,
    _recover_selected_skus_from_evidence,
    _validated_answer,
)
from app.services.customer_service_workbuddy_agent_service import (
    _declared_context_skus,
    _declared_fact_skus,
    _response_needs_current_fact_evidence,
)
from app.services.customer_service_workbuddy_rag_service import _answer_prompt


def test_named_subject_candidates_are_kept_before_unrelated_retrieval_hits():
    # This is the retrieval-boundary invariant behind natural multi-product
    # questions: a later semantic page must not evict a product subject before
    # the answer model sees its current evidence.
    from app.services.customer_service_semantic_rag_v2_service import _rank_retrieved_skus

    rows = [
        {"sku": "UNRELATED-1", "retrieval_query_index": 0, "retrieval_rank": 0},
        {"sku": "UNRELATED-2", "retrieval_query_index": 0, "retrieval_rank": 1},
        {"sku": "CW-C93", "retrieval_query_index": 1, "retrieval_rank": 0},
    ]
    retrieved = _rank_retrieved_skus(rows, limit=5)
    merged = list(dict.fromkeys(["CW-S10-1", "CW-S10-A", "CW-C93", *retrieved]))

    assert merged[:3] == ["CW-S10-1", "CW-S10-A", "CW-C93"]


def test_comparison_can_recover_selection_from_cited_evidence():
    raw = {
        "answer": "CW-C93 比 CW-C78 更适合单人徒步。",
        "answer_type": "comparison",
        "needs_clarification": False,
        "evidence_ids": ["v2-e1", "v2-e2"],
    }
    evidence = [
        {"sku": "CW-C93", "evidence_id": "v2-e1"},
        {"sku": "CW-C78", "evidence_id": "v2-e2"},
    ]

    recovered = _recover_selected_skus_from_evidence(
        raw,
        evidence=evidence,
        request_kind="comparison",
    )

    assert recovered["selected_skus"] == ["CW-C93", "CW-C78"]
    assert _answer_resolved_identity(
        recovered,
        evidence=evidence,
        identity_ambiguity=True,
        request_kind="comparison",
    ) is True


def test_conversational_memory_references_are_catalogue_validated_candidates():
    class Query:
        def filter(self, *_args):
            return self

        def all(self):
            return [("CW-C93",), ("CW-C78",)]

    class DB:
        def query(self, *_args):
            return Query()

    response = {
        "response_mode": "conversational",
        "answer_type": "faq",
        "identity_status": "confirmed",
        "needs_clarification": False,
        "candidate_skus": ["CW-C93", "CW-C78", "UNKNOWN"],
    }

    assert _declared_context_skus(DB(), response) == ["CW-C93", "CW-C78"]


def test_workbuddy_prompt_marks_catalogue_subjects_as_hints_only():
    payload = _answer_prompt(
        question="小方锅那套的容量",
        history=[],
        previous_turn_memory={},
        context_candidates=[],
        explicit_product_skus=[],
        catalogue_subject_skus=["CW-C99B"],
        anchor_skus=[],
        page_anchor=None,
        candidates=[],
        previous_context_products=[],
        evidence=[],
        experience_guidance=[],
    )

    assert payload["catalogue_identity_context"]["not_customer_confirmed"] is True


def test_product_comparison_cannot_bypass_rag_as_conversational():
    assert _response_needs_current_fact_evidence({
        "answer": "我会比较这两款。",
        "response_mode": "conversational",
        "answer_type": "comparison",
        "candidate_skus": ["CW-C93"],
    }) is True
    assert _response_needs_current_fact_evidence({
        "answer": "好的，记住了。",
        "response_mode": "conversational",
        "answer_type": "faq",
    }) is False


def test_comparison_protocol_recovery_reads_the_bounded_context():
    class Query:
        def filter(self, *_args):
            return self

        def all(self):
            return [("CW-C93",), ("CW-C78",)]

    class DB:
        def query(self, *_args):
            return Query()

    declared = _declared_fact_skus(
        DB(),
        {
            "answer_type": "comparison",
            "response_mode": "conversational",
            "candidate_skus": ["CW-C93"],
        },
        evidence=[],
        page_sku=None,
        context_skus=["CW-C93", "CW-C78"],
    )

    assert declared == ["CW-C93", "CW-C78"]


def test_identity_ambiguous_candidates_are_not_customer_visible_results():
    answer = _validated_answer(
        {
            "answer": "我查到多个可能对应的商品，请补充具体 SKU。",
            "answer_type": "clarification",
            "needs_clarification": True,
            "selected_skus": [],
        },
        evidence=[
            {"sku": "CS-B14", "evidence_id": "v2-e1"},
            {"sku": "CS-B02-37", "evidence_id": "v2-e2"},
        ],
        candidate_skus=["CS-B14", "CS-B02-37"],
        question="酒精炉可以在室内使用吗？",
        identity_ambiguity=True,
    )

    assert answer[5] == []


def test_selected_evidence_sku_remains_customer_visible_result():
    answer = _validated_answer(
        {
            "answer": "CW-C78 的重量约为 1320g。",
            "answer_type": "product_detail",
            "needs_clarification": False,
            "selected_skus": ["CW-C78"],
        },
        evidence=[
            {"sku": "CW-C78", "evidence_id": "v2-e1"},
        ],
        candidate_skus=[],
        question="CW-C78 的重量是多少？",
        identity_ambiguity=False,
    )

    assert answer[5] == ["CW-C78"]
