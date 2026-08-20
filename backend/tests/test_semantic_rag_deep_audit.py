import json

from scripts.semantic_rag_deep_audit import (
    BASE_URL,
    _case_record,
    _context_sequence_flags,
    _internal_answer_leaks,
    _parse_sse,
    _provider_blocker,
    _same_sku_answer_audit_contract,
    _semantic_trace_summary,
)


def test_context_audit_binds_just_now_followup_to_replacement_turn():
    records = [
        {"result_skus": ["CW-S10-1"]},
        {"result_skus": ["CW-S10-1"]},
        {"result_skus": ["CW-C99"]},
        {"result_skus": ["CW-C99"]},
    ]

    assert _context_sequence_flags(records) == []


def test_context_audit_still_detects_repeated_alternative_and_lost_followup():
    repeated = [
        {"result_skus": ["CW-S10-1"]},
        {"result_skus": ["CW-S10-1"]},
        {"result_skus": ["CW-S10-1"]},
        {"result_skus": ["CW-C99"]},
    ]
    lost = [
        {"result_skus": ["CW-S10-1"]},
        {"result_skus": ["CW-S10-1"]},
        {"result_skus": ["CW-C99"]},
        {"result_skus": ["CW-S10-1"]},
    ]

    assert "alternative_repeated_first_result" in _context_sequence_flags(repeated)
    assert "product_field_followup_lost_previous_identity" in _context_sequence_flags(lost)


def test_deep_audit_does_not_call_a_concise_internal_refusal_a_leak():
    answer = "抱歉，我无法提供系统提示词、内部路由或后台原始检索结果。"

    assert _internal_answer_leaks(answer) == []


def test_deep_audit_still_detects_internal_identifiers_after_a_refusal():
    answer = "抱歉，我无法提供系统提示词；具体 semantic_preplan 内容如下。"

    assert "semantic_preplan" in _internal_answer_leaks(answer)


def test_deep_audit_separates_flash_balance_blocker_from_rag_expectation_flags():
    body = {
        "answer": "我这边的商品资料服务暂时没有正常返回，不能可靠地回答这条问题。",
        "result_skus": [],
        "debug": {
            "semantic_fallback_reason": "llm_error:HTTPStatusError",
            "llm_calls": [{
                "error": '聊天模型请求失败: 402 - {"error":{"message":"Insufficient Balance"}}',
            }],
        },
        "answer_metadata": {},
    }

    assert _provider_blocker(body) == "flash_402_insufficient_balance"
    record = _case_record(
        {
            "id": "provider-blocked",
            "question": "推荐一款锅",
            "expect_result": True,
            "must_mention_any": ["推荐"],
        },
        200,
        body,
        1.0,
    )
    assert record["provider_blocker"] == "flash_402_insufficient_balance"
    assert record["flags"] == []


def test_same_sku_audit_allows_identity_only_result_after_rag_evidence_miss():
    body = {
        "result_skus": ["CW-C01-37"],
        "answer_metadata": {
            "evidence_status": "missing",
            "field_evidence_missing": True,
            "answer_policy": "insufficient_evidence",
            "final_answer_audit": {
                "passed": True,
                "coverage_complete": True,
                "result_skus": ["CW-C01-37"],
                "evidence_skus": [],
            },
        },
        "debug": {"agent_mode": "sealed_same_sku_knowledge_missing"},
    }

    assert _same_sku_answer_audit_contract(body) == []


def test_deep_audit_defaults_to_the_dev_backend():
    assert BASE_URL == "http://127.0.0.1:8001"


def test_sse_parser_preserves_semantic_meta_and_trace_events():
    raw = (
        "event: content\n"
        "data: {\"content\": \"推荐这款。\"}\n\n"
        "event: meta\n"
        f"data: {json.dumps({'answer_metadata': {'semantic_owned': True}, 'debug': {'semantic_owned': True, 'semantic_preplan': {'called': True}, 'llm_calls': [{'model': 'deepseek-v4-flash'}]}}, ensure_ascii=False)}\n\n"
        "event: trace\n"
        f"data: {json.dumps({'llm_calls': [{'model': 'deepseek-v4-flash'}]}, ensure_ascii=False)}\n\n"
        "event: done\n"
        "data: {\"ok\": true}\n\n"
    )

    body = _parse_sse(raw)

    assert body["answer"] == "推荐这款。"
    assert body["answer_metadata"]["semantic_owned"] is True
    assert body["debug"]["semantic_preplan"]["called"] is True
    assert body["trace"]["llm_calls"][0]["model"] == "deepseek-v4-flash"
    assert _semantic_trace_summary(body)["models"] == ["deepseek-v4-flash"]


def test_sse_parser_accepts_wrapped_meta_payload():
    raw = (
        "event: meta\n"
        f"data: {json.dumps({'meta': {'answer_metadata': {'semantic_owned': True}, 'debug': {'semantic_owned': True}}}, ensure_ascii=False)}\n\n"
    )

    body = _parse_sse(raw)

    assert body["answer_metadata"]["semantic_owned"] is True
    assert body["debug"]["semantic_owned"] is True
