from app.services import customer_answer_coverage_contract
from app.services import customer_final_answer_arbiter
from app.services import customer_service_service


def _coverage(*, answered=(), unsupported=()):
    request_texts = [*answered, *unsupported]
    return customer_answer_coverage_contract.build_answer_coverage_contract(
        request_texts,
        answered_requests=[(item, f"evidence-{index}") for index, item in enumerate(answered, start=1)],
        unsupported_requests=unsupported,
    ).to_dict()


def test_final_arbiter_removes_duplicate_and_contradictory_missing_boundaries():
    answered = "能不能直接灌沸水"
    missing_line = f"关于“{answered}”：当前同 SKU 资料未直接确认，无法确认。"
    result = customer_final_answer_arbiter.arbitrate_final_answer({
        "answer": f"耐温范围约为0°C至60°C，不能直接灌沸水。\n{missing_line}\n{missing_line}",
        "result_skus": ["AC-19"],
        "evidence": [{"sku": "AC-19", "evidence_id": "evidence-1"}],
        "answer_metadata": {"answer_coverage_contract": _coverage(answered=[answered])},
        "debug": {
            "entity_resolution_contract": {
                "status": "resolved",
                "resolved_sku": "AC-19",
            }
        },
    })

    assert missing_line not in result["answer"]
    assert result["answer_metadata"]["final_answer_audit"]["passed"] is True
    assert "contradictory_missing_boundary_removed" in result["answer_metadata"]["final_answer_audit"]["repairs"]


def test_final_arbiter_preserves_one_boundary_for_each_unsupported_request():
    unsupported = "能不能直接用卡式气罐"
    result = customer_final_answer_arbiter.arbitrate_final_answer({
        "answer": "高海拔环境下建议注意火力变化。",
        "result_skus": ["CW-C95"],
        "evidence": [{"sku": "CW-C95", "evidence_id": "evidence-1"}],
        "answer_metadata": {"answer_coverage_contract": _coverage(unsupported=[unsupported])},
        "debug": {
            "entity_resolution_contract": {
                "status": "resolved",
                "resolved_sku": "CW-C95",
            }
        },
    })

    missing_line = f"关于“{unsupported}”：当前同 SKU 资料未直接确认，无法确认。"
    assert result["answer"].count(missing_line) == 1
    assert result["answer_metadata"]["final_answer_audit"]["passed"] is True


def test_final_arbiter_deduplicates_equivalent_missing_boundaries_for_same_request():
    result = customer_final_answer_arbiter.arbitrate_final_answer({
        "answer": "关于“里面都有什么”：当前该商品资料未直接确认，无法确认。",
        "result_skus": ["CW-C95"],
        "evidence": [],
        "answer_metadata": {
            "answer_coverage_contract": _coverage(unsupported=["里面都有什么"]),
        },
        "debug": {},
    })

    assert result["answer"].count("关于“里面都有什么”") == 1
    assert "equivalent_missing_boundary_removed" in (
        result["answer_metadata"]["final_answer_audit"]["repairs"]
    )


def test_final_arbiter_flags_cross_sku_evidence_without_rewriting_facts():
    original = "CW-C95的材质为硬质氧化铝合金。"
    result = customer_final_answer_arbiter.arbitrate_final_answer({
        "answer": original,
        "result_skus": ["CW-C95"],
        "evidence": [{"sku": "CW-C83", "evidence_id": "wrong-sku"}],
        "answer_metadata": {},
        "debug": {
            "entity_resolution_contract": {
                "status": "resolved",
                "resolved_sku": "CW-C95",
            }
        },
    })

    audit = result["answer_metadata"]["final_answer_audit"]
    assert result["answer"] == original
    assert audit["passed"] is False
    assert audit["blocking_findings"] == ["cross_sku_evidence"]


def test_final_arbiter_flags_empty_answer_and_internal_labels():
    result = customer_final_answer_arbiter.arbitrate_final_answer({
        "answer": "Agent mode: semantic_preplan",
        "result_skus": [],
        "evidence": [],
        "answer_metadata": {},
        "debug": {},
    })
    audit = result["answer_metadata"]["final_answer_audit"]
    assert audit["passed"] is False
    assert "internal_label_exposed" in audit["blocking_findings"]

    empty = customer_final_answer_arbiter.arbitrate_final_answer({
        "answer": "   ",
        "result_skus": [],
        "evidence": [],
        "answer_metadata": {},
        "debug": {},
    })
    assert empty["answer_metadata"]["final_answer_audit"]["blocking_findings"] == ["empty_answer"]


def test_final_answer_sanitizer_removes_internal_evidence_paths():
    answer = customer_service_service._sanitize_final_answer_text(
        "轻途套锅适合背包旅行（来源：content.features），收纳尺寸见 specs.size_info。",
        {},
    )

    assert "content.features" not in answer
    assert "specs.size_info" not in answer
    assert "来源：" not in answer


def test_final_answer_sanitizer_removes_internal_qa_kb_provenance():
    answer = customer_service_service._sanitize_final_answer_text(
        "适用热源：高山气罐（补充资料）\n依据：以上字段已结合当前 SKU 的 QA / KB 补充资料。其中未直接标注液化气罐，因此不能确认。",
        {"type": "structured_product_detail"},
    )

    assert "补充资料" not in answer
    assert "QA / KB" not in answer
    assert "依据：以上字段" not in answer
    assert "其中未直接标注液化气罐" in answer
