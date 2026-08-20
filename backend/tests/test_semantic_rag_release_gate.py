from scripts.semantic_rag_release_gate import evaluate_report


def _grounded_case(*, answer="CW-S10-1 容量为 1.4L。", evidence_sku="CW-S10-1"):
    return {
        "id": "sku_s10_capacity_natural",
        "status": 200,
        "flags": [],
        "provider_blocker": "",
        "answer": answer,
        "result_skus": ["CW-S10-1"],
        "public_evidence_skus": [evidence_sku],
        "models": ["deepseek-v4-flash"],
        "response": {
            "evidence": [{
                "sku": evidence_sku,
                "source_type": "product_db",
                "field_label": "容量",
                "value": "锅：1400ML",
            }],
            "answer_metadata": {
                "semantic_owned": True,
                "semantic_executor_branch": "semantic_first_product_qa_rag",
                "final_answer_audit": {
                    "passed": True,
                    "coverage_complete": True,
                },
            },
            "debug": {
                "semantic_owned": True,
                "semantic_preplan": {"called": True},
                "semantic_pipeline_entry": {"branch": "semantic_first_product_qa_rag"},
                "llm_calls": [{
                    "purpose": "semantic_preplan",
                    "model": "deepseek-v4-flash",
                }],
            },
        },
    }


def _context_turn(sku: str, *, answer: str = "已按同 SKU 资料核对。"):
    record = _grounded_case(answer=answer, evidence_sku=sku)
    record.update({
        "id": "context",
        "result_skus": [sku],
        "public_evidence_skus": [sku],
    })
    record["response"]["evidence"][0]["sku"] = sku
    return record


def _valid_sequences():
    return [
        {
            "id": "deep_context_sequence",
            "flags": [],
            "provider_blockers": [],
            "turns": [
                _context_turn("SKU-1"),
                _context_turn("SKU-1"),
                _context_turn("SKU-2"),
                _context_turn("SKU-2"),
            ],
        },
        {
            "id": "deep_normal_stream_parity",
            "flags": [],
            "provider_blockers": [],
            "normal_status": 200,
            "stream_status": 200,
            "normal_answer": "同一答案。",
            "stream_answer": "同一答案。",
            "normal_result_skus": ["SKU-1"],
            "stream_result_skus": ["SKU-1"],
            "normal_public_evidence_skus": ["SKU-1"],
            "stream_public_evidence_skus": ["SKU-1"],
            "normal_semantic_trace": {
                "semantic_owned": True,
                "semantic_preplan_called": True,
                "models": ["deepseek-v4-flash"],
                "provenance_flags": [],
            },
            "stream_semantic_trace": {
                "semantic_owned": True,
                "semantic_preplan_called": True,
                "models": ["deepseek-v4-flash"],
                "provenance_flags": [],
            },
        },
    ]


def test_rag_gate_accepts_same_sku_trace_and_unit_equivalent_fact():
    result = evaluate_report({
        "external_blocker_count": 0,
        "cases": [_grounded_case()],
        "sequences": _valid_sequences(),
    }, strict=False)

    assert result["passed"] is True, result


def test_rag_gate_fails_closed_on_provider_blocker():
    result = evaluate_report({
        "external_blocker_count": 1,
        "cases": [{
            **_grounded_case(),
            "provider_blocker": "flash_402_insufficient_balance",
        }],
        "sequences": [],
    }, strict=False)

    assert result["passed"] is False
    assert any("provider_blocker" in issue for issue in result["issues"])


def test_rag_gate_rejects_cross_sku_evidence_even_when_answer_audit_claims_passed():
    result = evaluate_report({
        "external_blocker_count": 0,
        "cases": [_grounded_case(evidence_sku="CW-C78")],
        "sequences": [],
    }, strict=False)

    assert result["passed"] is False
    assert any("cross_sku" in issue for issue in result["issues"])


def test_rag_gate_rejects_missing_required_fact_without_requiring_verbatim_quote():
    result = evaluate_report({
        "external_blocker_count": 0,
        "cases": [_grounded_case(answer="CW-S10-1 适合两个人使用。")],
        "sequences": [],
    }, strict=False)

    assert result["passed"] is False
    assert any("required_evidence_fact_missing" in issue for issue in result["issues"])


def test_rag_gate_accepts_atomic_knowledge_chunk_for_formal_field_fact():
    case = _grounded_case(answer="CW-S10-1 的容量是 1.4L。")
    case["response"]["evidence"] = [{
        "sku": "CW-S10-1",
        "source_type": "knowledge_chunks",
        "source_layer": "RAG",
        "evidence_text": "- 容量: value: 1400ML",
        "value": "- 容量: value: 1400ML",
    }]
    result = evaluate_report({
        "external_blocker_count": 0,
        "cases": [case],
        "sequences": [],
    }, strict=False)

    assert result["passed"] is True, result


def test_rag_gate_rejects_a_partial_report_in_strict_release_mode():
    result = evaluate_report({
        "base_url": "http://127.0.0.1:8001",
        "external_blocker_count": 0,
        "cases": [_grounded_case()],
        "sequences": [],
    })

    assert result["passed"] is False
    assert any("missing_case_ids" in issue for issue in result["issues"])
    assert any("missing_sequence_ids" in issue for issue in result["issues"])


def test_rag_gate_requires_exact_public_evidence_sku_for_product_result():
    result = evaluate_report({
        "external_blocker_count": 0,
        "cases": [_grounded_case(evidence_sku="CW-S10-1") | {"public_evidence_skus": []}],
        "sequences": [],
    }, strict=False)

    assert result["passed"] is False
    assert any("public_evidence_missing_result_sku" in issue for issue in result["issues"])


def test_rag_gate_allows_identity_only_product_after_same_sku_evidence_miss():
    case = _context_turn("SKU-MISS", answer="已确认商品身份，但当前同 SKU 资料不足，无法确认。")
    case["public_evidence_skus"] = []
    case["response"]["evidence"] = []
    case["response"]["answer_metadata"].update({
        "evidence_status": "missing",
        "field_evidence_missing": True,
        "answer_policy": "insufficient_evidence",
    })
    case["response"]["debug"]["agent_mode"] = "sealed_same_sku_knowledge_missing"
    result = evaluate_report({
        "external_blocker_count": 0,
        "cases": [case],
        "sequences": [],
    }, strict=False)

    assert result["passed"] is True, result


def test_rag_gate_rejects_flash_looking_answer_without_semantic_ownership():
    case = _grounded_case()
    case["response"]["answer_metadata"]["semantic_owned"] = False
    result = evaluate_report({
        "external_blocker_count": 0,
        "cases": [case],
        "sequences": [],
    }, strict=False)

    assert result["passed"] is False
    assert any("semantic_ownership_missing" in issue for issue in result["issues"])


def test_rag_gate_rejects_safe_but_incomplete_recommendation_presentation_fallback():
    case = _grounded_case(answer="按当前商品资料，可以先看这款。")
    case["answer_type"] = "recommendation"
    case["response"]["answer_metadata"]["recommendation_narrative"] = {
        "source": "sealed_same_sku_fact_fallback",
    }

    result = evaluate_report({
        "external_blocker_count": 0,
        "cases": [case],
        "sequences": [],
    }, strict=False)

    assert result["passed"] is False
    assert any("semantic_presentation_fallback_used" in issue for issue in result["issues"])


def test_rag_gate_rejects_answer_that_only_echoes_the_customer_question():
    case = _grounded_case(answer="CW-S10-1 的容量是多少？")
    case["question"] = "CW-S10-1 的容量是多少？"

    result = evaluate_report({
        "external_blocker_count": 0,
        "cases": [case],
        "sequences": [],
    }, strict=False)

    assert result["passed"] is False
    assert any("answer_echoed_question" in issue for issue in result["issues"])


def test_rag_gate_rejects_legacy_route_provenance_even_when_sku_is_grounded():
    case = _grounded_case()
    case["response"]["debug"]["trace"] = {
        "stages": [{"stage": "process_intent_request_fallback"}],
    }
    result = evaluate_report({
        "external_blocker_count": 0,
        "cases": [case],
        "sequences": [],
    }, strict=False)

    assert result["passed"] is False
    assert any("legacy_route_provenance" in issue for issue in result["issues"])


def test_rag_gate_requires_semantic_trace_for_normal_stream_parity():
    sequence = _valid_sequences()[1]
    sequence.pop("stream_semantic_trace")
    result = evaluate_report({
        "external_blocker_count": 0,
        "cases": [_grounded_case()],
        "sequences": [sequence],
    }, strict=False)

    assert result["passed"] is False
    assert any("stream_semantic_trace_missing" in issue for issue in result["issues"])


def test_rag_gate_allows_no_match_alternative_and_keeps_last_confirmed_identity():
    sequences = _valid_sequences()
    turns = sequences[0]["turns"]
    no_match = _context_turn("SKU-2", answer="没有找到同时满足条件的直接匹配。")
    no_match["result_skus"] = []
    no_match["public_evidence_skus"] = []
    no_match["response"]["evidence"] = []
    turns[2] = no_match
    turns[3] = _context_turn("SKU-1", answer="继续按上一款的同 SKU 资料核对。")

    result = evaluate_report({
        "external_blocker_count": 0,
        "cases": [_grounded_case()],
        "sequences": sequences,
    }, strict=False)

    assert result["passed"] is True, result
