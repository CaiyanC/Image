import json

from app.services.customer_answer_grounding_service import (
    answer_protocol_issues,
    available_skus,
    grounding_repair_instruction,
)


def _payload():
    return {
        "explicit_product_skus": ["SKU-A"],
        "candidate_products": [{"sku": "SKU-A", "product_name_cn": "测试商品"}],
        "evidence": [{
            "evidence_id": "e1",
            "sku": "SKU-A",
            "authority_level": "canonical",
            "fact_authority": True,
            "content": "当前商品的可核对事实。",
        }],
    }


def test_protocol_accepts_natural_answer_without_topic_rules():
    payload = _payload()
    for answer in (
        "这款适合短途出行，具体使用时按说明操作。",
        "目前可以确认部分信息，另一个细节还需要核对。",
        "建议优先比较两款的配置和实际需求。",
    ):
        assert answer_protocol_issues({
            "answer": answer,
            "selected_skus": ["SKU-A"],
            "evidence_ids": ["e1"],
        }, payload) == []


def test_protocol_rejects_only_unknown_provenance():
    payload = _payload()
    issues = answer_protocol_issues({
        "answer": "这款可以直接使用。",
        "selected_skus": ["SKU-A", "SKU-NOT-IN-PACKET"],
        "evidence_ids": ["e1", "e-not-in-packet"],
        "claims": [{
            "sku": "SKU-A",
            "statement": "这款可以直接使用。",
            "evidence_ids": ["e-claim-not-in-packet"],
        }],
    }, payload)
    assert {item["code"] for item in issues} == {
        "unknown_evidence_reference",
        "unknown_sku_reference",
        "unknown_claim_evidence_reference",
    }
    assert "酒精炉" not in json.dumps(issues, ensure_ascii=False)


def test_protocol_does_not_choose_between_candidates():
    payload = {
        "candidate_products": [{"sku": "A"}, {"sku": "B"}],
        "evidence": [],
    }
    assert available_skus(payload) == {"A", "B"}
    assert answer_protocol_issues({"answer": "两款都可以进一步比较。"}, payload) == []


def test_protocol_rejects_missing_answer_and_bad_optional_shapes():
    assert answer_protocol_issues(None, {})[0]["code"] == "invalid_answer_json"
    issues = answer_protocol_issues({
        "answer": "可以。",
        "claims": {"statement": "不是数组"},
        "answer_type": "unknown_type",
    }, {})
    assert {item["code"] for item in issues} == {
        "invalid_claims_shape",
        "invalid_answer_type",
    }


def test_repair_instruction_is_topic_agnostic():
    text = grounding_repair_instruction([{
        "code": "unknown_evidence_reference",
        "reason": "证据不在当前包中",
    }])
    assert "重新阅读" in text
    assert "evidence" in text
    assert "酒精炉" not in text
