import asyncio
import json
import re

import pytest

from app.models import Product, ProductBusiness, ProductSpecs
from app.services import customer_agent_intent_service, customer_agent_planner_service, customer_service_service
from test_customer_service_route_level_regression import (
    _add_product,
    _add_knowledge_chunk,
    _add_product_qa,
    route_client_and_db,
)
from test_customer_service_route_level_regression import _parse_sse_payload


def _seed_contents_grounding_evidence(Session) -> None:
    with Session() as db:
        _add_product_qa(db, "CT-T04(BM)", "CT-T04(BM) 第一次使用要注意什么？", "首次使用前用温水和软布冲洗即可（无需洗洁精）。使用前用温水冲洗即可。", tags="第一次使用,茶具,清洗", priority=190)
        _add_product_qa(db, "CT-T04(BM)", "CT-T04(BM) 里面有什么？", "CT-T04(BM) 为一整套便携功夫茶具，含茶壶、茶杯等配件，开箱即可泡茶。", tags="配件,套装,组成", priority=210)
        _add_product_qa(db, "CW-C06PRO", "CW-C06PRO 怎么清洗？", "使用后趁热用温水+软刷清洗，彻底擦干或小火烘干，避免钢丝球等硬物刮擦表面。", tags="清洗,保养", priority=210)
        _add_product_qa(db, "CW-C83", "CW-C83 套装包含哪些东西？", "CW-C83 为套锅组合，当前资料可确认包含锅、炒锅和煎锅三类锅体组件；如需更细包装清单，建议再核对正式商品页。", tags="套装,包含,组成", priority=190)
        _add_product_qa(db, "CS-B14（LX）", "CS-B14（LX）使用酒精有什么注意事项？", "CS-B14（LX）适配旋焰酒精炉，使用时建议按液体酒精热源场景操作，并保持通风，避免在密闭空间使用。", tags="酒精炉,液体酒精,注意事项", priority=200)
        _add_knowledge_chunk(
            db,
            chunk_id="ct-t04-contents-1",
            sku="CT-T04(BM)",
            title="出山功夫茶具补充问答",
            content="Q: 出山-功夫茶具（竹套版）里面有什么？\nA: 出山-功夫茶具（竹套版）为一整套便携功夫茶具，含茶壶、茶杯等配件，开箱即可泡茶。\nQ: 出山-功夫茶具（竹套版）第一次使用要注意什么？\nA: 首次使用前用温水和软布冲洗即可（无需洗洁精）。",
            source_type="product",
            metadata={"section": "qa", "category": "茶具"},
        )
        _add_knowledge_chunk(
            db,
            chunk_id="cw-c83-contents-1",
            sku="CW-C83",
            title="炊墨套锅补充问答",
            content="Q: 炊墨套锅包含哪些东西？\nA: 当前资料可确认包含锅、炒锅和煎锅三类锅体组件；如需更细包装清单，建议再核对正式商品页。",
            source_type="product",
            metadata={"section": "qa", "category": "锅具"},
        )
        _add_knowledge_chunk(
            db,
            chunk_id="cs-b14-lx-alcohol-1",
            sku="CS-B14（LX）",
            title="旋焰炉芯使用酒精注意事项",
            content="Q: CS-B14（LX）使用酒精有什么注意事项？\nA: 该产品适配旋焰酒精炉，适用热源为液体酒精；使用时应保持通风，避免在密闭空间操作。",
            source_type="product",
            metadata={"section": "qa", "category": "配件"},
        )
        db.commit()


def _seed_cf_pg19_generic_detail_noise(Session) -> None:
    with Session() as db:
        _add_knowledge_chunk(
            db,
            chunk_id="cf-pg19-generic-detail-noise",
            sku="CF-PG19",
            title="瓦片烤盘产品基础资料",
            content=(
                "SKU: CF-PG19\n"
                "中文名: 瓦片烤盘\n"
                "规格信息:\n"
                "- 材质: 铝合金\n"
                "- 适用热源: 明火直烧、燃气炉、卡式炉、电磁炉\n"
                "- 技术优势: 中式方形设计，方形设计增加27%烹饪空间\n"
                "- 使用说明: 【使用步骤】1.开箱初洗：首次使用前，用温水和软布轻柔冲洗锅身，无需使用洗洁精。"
            ),
            source_type="product",
            metadata={"section": "product_detail", "category": "锅具"},
        )
        db.commit()


def _seed_contents_resolution_priority_products(Session) -> None:
    with Session() as db:
        _add_product(db, "CS-G25", "小青炉", "炉具", "/", "不锈钢", "气罐", "基础款炉具", "露营烧烤", 2100)
        _add_product(db, "CS-G25-B", "小青炉Pro", "炉具", "/", "不锈钢", "气罐", "Pro版炉具", "露营烧烤", 2300)
        _add_product(db, "CF-PG19PRO", "瓦片烤盘Pro", "锅具", "8英寸", "硬质氧化铝合金", "燃气炉", "升级款烤盘", "露营烧烤 营地早餐", 860)
        _add_product(db, "CS-B16-37", "气炉围雪炉", "配件", "/", "不锈钢", "/", "围雪炉配件", "炉具维护", 120)
        _add_product(db, "CS-G35", "围雪炉Pro", "炉具", "/", "不锈钢", "气罐", "围雪炉系列", "露营烧烤", 2600)
        _add_product(db, "TW-139CS", "城市出逃饭盒", "餐具", "900ML", "304不锈钢", "/", "城市出逃系列", "公园野餐", 180)
        _add_product(db, "CW-C65-3", "城市出逃1L水壶(电光绿)", "水壶", "1L", "铝合金", "燃气炉", "城市出逃系列", "户外补水", 280)
        db.commit()


def _semantic_preplan_debug(payload: dict) -> dict:
    debug = payload.get("debug") if isinstance(payload.get("debug"), dict) else {}
    return debug.get("semantic_preplan") if isinstance(debug.get("semantic_preplan"), dict) else {}


def _seed_contents_variant_knowledge_noise(Session) -> None:
    with Session() as db:
        _add_knowledge_chunk(
            db,
            chunk_id="cs-g25-b-contents-noise-1",
            sku="CS-G25-B",
            title="CS-G25-B QA 9",
            content="Q: 小青炉Pro配收纳袋吗？\nA: 配有收纳袋（部分为网格收纳袋），用完收纳起来，背包整洁不凌乱。",
            source_type="product",
            metadata={"sku": "CS-G25-B", "section": "qa:variant-noise-1", "title": "CS-G25-B QA 9"},
        )
        _add_knowledge_chunk(
            db,
            chunk_id="cs-g25-b-contents-noise-2",
            sku="CS-G25-B",
            title="CS-G25-B QA 2",
            content="Q: 小青炉Pro表面做了什么工艺处理？\nA: 小青炉Pro表面采用硬质氧化工艺，耐磨耐用、易清洁。",
            source_type="product",
            metadata={"sku": "CS-G25-B", "section": "qa:variant-noise-2", "title": "CS-G25-B QA 2"},
        )
        db.commit()


def _seed_contents_grounding_evidence(Session) -> None:
    with Session() as db:
        _add_product_qa(db, "CT-T04(BM)", "CT-T04(BM) 第一次使用要注意什么？", "首次使用前用温水和软布冲洗即可（无需洗洁精）。使用前用温水冲洗即可。", tags="第一次使用,茶具,清洗", priority=190)
        _add_product_qa(db, "CT-T04(BM)", "CT-T04(BM) 里面有什么？", "CT-T04(BM) 为一整套便携功夫茶具，含茶壶、茶杯等配件，开箱即可泡茶。", tags="配件,套装,组成", priority=210)
        _add_product_qa(db, "CW-C06PRO", "CW-C06PRO 怎么清洗？", "使用后趁热用温水+软刷清洗，彻底擦干或小火烘干，避免钢丝球等硬物刮擦表面。", tags="清洗,保养", priority=210)
        _add_product_qa(db, "CW-C83", "CW-C83 套装包含哪些东西？", "CW-C83 为套锅组合，当前资料可确认包含锅、炒锅和煎锅三类锅体组件；如需更细包装清单，建议再核对正式商品页。", tags="套装,包含,组成", priority=190)
        _add_product_qa(db, "CS-B14（LX）", "CS-B14（LX）使用酒精有什么注意事项？", "CS-B14（LX）适配旋焰酒精炉，使用时建议按液体酒精热源场景操作，并保持通风，避免在密闭空间使用。", tags="酒精炉,液体酒精,注意事项", priority=200)
        _add_knowledge_chunk(
            db,
            chunk_id="ct-t04-contents-1-v2",
            sku="CT-T04(BM)",
            title="出山功夫茶具补充问答",
            content="Q: 出山-功夫茶具（竹套版）里面有什么？\nA: 出山-功夫茶具（竹套版）为一整套便携功夫茶具，含茶壶、茶杯等配件，开箱即可泡茶。\nQ: 出山-功夫茶具（竹套版）第一次使用要注意什么？\nA: 首次使用前用温水和软布冲洗即可（无需洗洁精）。",
            source_type="product",
            metadata={"section": "qa", "category": "茶具"},
        )
        _add_knowledge_chunk(
            db,
            chunk_id="cw-c83-contents-1-v2",
            sku="CW-C83",
            title="炊墨套锅补充问答",
            content="Q: 炊墨套锅包含哪些东西？\nA: 当前资料可确认包含锅、炒锅和煎锅三类锅体组件；如需更细包装清单，建议再核对正式商品页。",
            source_type="product",
            metadata={"section": "qa", "category": "锅具"},
        )
        _add_knowledge_chunk(
            db,
            chunk_id="cs-b14-lx-alcohol-1-v2",
            sku="CS-B14（LX）",
            title="旋焰炉芯使用酒精注意事项",
            content="Q: CS-B14（LX）使用酒精有什么注意事项？\nA: 该产品适配旋焰酒精炉，适用热源为液体酒精；使用时应保持通风，避免在密闭空间操作。",
            source_type="product",
            metadata={"section": "qa", "category": "配件"},
        )
        db.commit()


def _alcohol_stove_supports_from_specs(value: str) -> bool:
    text = str(value or "")
    return any(term in text for term in ("\u9152\u7cbe\u7089", "\u6db2\u4f53\u9152\u7cbe", "\u56fa\u4f53\u9152\u7cbe"))


def _category_contains_any(value: str, expected_terms: tuple[str, ...]) -> bool:
    text = str(value or "").strip()
    return any(term in text for term in expected_terms)


def _assert_recommendation_result_rows_stay_in_category_domain(
    Session,
    result_skus: list[str],
    *,
    include_terms: tuple[str, ...],
    exclude_terms: tuple[str, ...],
) -> None:
    assert result_skus, result_skus
    with Session() as db:
        products = db.query(Product).filter(Product.sku.in_(result_skus)).all()
    by_sku = {product.sku: product for product in products}
    assert set(result_skus).issubset(by_sku.keys()), {"result_skus": result_skus, "loaded": sorted(by_sku.keys())}
    for sku in result_skus:
        product = by_sku[sku]
        category = str(product.category or "")
        assert _category_contains_any(category, include_terms), {
            "sku": sku,
            "actual_category": category,
            "expected_any": include_terms,
        }
        assert not _category_contains_any(category, exclude_terms), {
            "sku": sku,
            "actual_category": category,
            "excluded_any": exclude_terms,
        }


def test_semantic_preplan_parser_accepts_code_fence_and_tracks_llm_calls(monkeypatch):
    calls = []

    async def fake_chat_completion(db, messages, model=None, temperature=0.2, max_tokens=1200, *, purpose="chat"):
        calls.append(purpose)
        return """```json
{"route_hint":"comparison","question_type":"comparison","entities":[],"field_hint":null,"qa_or_usage_care":false,"unknown_field":false,"confidence":0.84,"reason":"pan vs cookware"}
```"""

    monkeypatch.setattr(customer_agent_planner_service.customer_llm_service, "chat_completion", fake_chat_completion)

    result = asyncio.run(
        customer_agent_planner_service.plan_customer_question_semantic(
            db=None,
            question="\u4e3b\u8981\u505a\u714e\u70e4\u65e9\u9910\uff0c\u9505\u548c\u70e4\u76d8\u54ea\u4e2a\u66f4\u503c\u5f97\u5148\u4e70\uff1f",
            deterministic_plan={"primary_intent": "comparison", "answer_type": "comparison"},
            context={},
        )
    )

    assert calls == ["semantic_preplan"]
    assert result["called"] is True
    assert result["route_hint"] == "comparison"
    assert result["confidence"] > 0


def test_structured_field_query_parser_splits_category_field_and_value_cleanly():
    water_bottle = customer_agent_intent_service.parse_intent("哪些水壶是不锈钢材质？")
    cookware = customer_agent_intent_service.parse_intent("哪些锅具是铝合金材质？")
    gas_stove = customer_agent_intent_service.parse_intent("哪些锅能用燃气炉？")

    assert water_bottle is not None
    assert water_bottle.intent == "query_products"
    assert water_bottle.filters.get("product.category") == "水壶"
    assert water_bottle.filters.get("specs.body_material") == "不锈钢"
    assert water_bottle.term == ""
    assert "材质" in water_bottle.requested_fields

    assert cookware is not None
    assert cookware.intent == "query_products"
    assert cookware.filters.get("product.category") == "锅具"
    assert cookware.filters.get("specs.body_material") == "铝合金"
    assert cookware.term == ""
    assert "材质" in cookware.requested_fields

    assert gas_stove is not None
    assert gas_stove.intent == "query_products"
    assert gas_stove.filters.get("product.category") == "锅具"
    assert gas_stove.filters.get("specs.heat_source") == "燃气炉"
    assert gas_stove.term == ""
    assert "热源" in gas_stove.requested_fields


@pytest.mark.parametrize(
    "question",
    [
        "\u9002\u5408\u9152\u7cbe\u7089\u7684\u9505\u5177\u63a8\u8350",
        "\u6709\u6ca1\u6709\u9002\u5408\u9152\u7cbe\u7089\u7684\u9505\uff1f",
        "\u54ea\u4e9b\u9505\u5177\u53ef\u4ee5\u7528\u9152\u7cbe\u7089\uff1f",
        "\u63a8\u8350\u80fd\u7528\u6db2\u4f53\u9152\u7cbe\u7684\u9505\u5177",
        "\u9732\u8425\u7528\uff0c\u80fd\u914d\u9152\u7cbe\u7089\u7684\u9505\u5177\u6709\u54ea\u4e9b\uff1f",
    ],
)
def test_recommendation_alcohol_stove_cookware_queries_keep_structured_heat_source_constraint(question):
    intent = customer_agent_intent_service.parse_intent(question)

    assert intent is not None
    assert intent.intent in {"recommend_products", "query_products"}
    assert intent.filters.get("product.category") == "\u9505\u5177"
    assert intent.filters.get("specs.heat_source") == "\u9152\u7cbe\u7089"


def test_recommendation_hard_filters_keep_explicit_category_for_generic_stove_recommendation():
    intent = customer_agent_intent_service.parse_intent("\u7089\u5177\u63a8\u8350")

    assert intent is not None
    assert intent.intent == "recommend_products"
    assert customer_agent_intent_service._recommendation_hard_filters(intent, "\u7089\u5177") == {
        "product.category": "\u7089\u5177"
    }


@pytest.mark.parametrize(
    "question",
    [
        "\u590f\u5929\u51b7\u6c34\u8865\u6c34\u6c34\u58f6\u63a8\u8350",
        "\u590f\u5929\u8865\u6c34\u6c34\u58f6\u63a8\u8350",
        "\u51b7\u6c34\u6c34\u58f6\u63a8\u8350",
        "\u6c34\u58f6\u63a8\u8350",
        "\u6237\u5916\u8865\u6c34\u6c34\u5177\u63a8\u8350",
        "\u6709\u4ec0\u4e48\u6c34\u58f6\u63a8\u8350\uff1f",
        "\u63a8\u8350\u51e0\u4e2a\u6c34\u58f6",
    ],
)
def test_waterware_recommendation_queries_do_not_fall_into_usage_care(question):
    assert customer_agent_intent_service._looks_like_recommendation_question(question)
    assert not customer_service_service._is_product_usage_care_question(question)


def test_compose_recommendation_answer_bypasses_llm_for_alcohol_stove_cookware(monkeypatch):
    async def fail_finalize(*args, **kwargs):
        raise AssertionError("finalize llm path should be skipped for alcohol stove cookware recommendation")

    monkeypatch.setattr(customer_agent_intent_service, "_finalize_recommendation_answer", fail_finalize)
    monkeypatch.setattr(
        customer_agent_intent_service,
        "_recommendation_product_data",
        lambda db, rows, supporting_by_sku=None: [{"sku": "CW-S10-A"}],
    )

    ranked = [
        {
            "row": {
                "sku": "CW-S10-A",
                "product_name_cn": "激川单锅",
                "category": "锅具",
                "heat_source": "酒精炉\n气炉",
                "usage_scenarios": "露营简餐",
            },
            "matched": ["适合酒精炉"],
            "reasons": ["适用热源明确包含酒精炉"],
        }
    ]
    intent = customer_agent_intent_service.parse_intent("有没有适合酒精炉的锅？")

    answer = asyncio.run(
        customer_agent_intent_service._compose_recommendation_answer(
            db=None,
            question="有没有适合酒精炉的锅？",
            ranked=ranked,
            intent=intent,
            warnings=[],
            anomalies=[],
            followups=[],
            result_rows=[dict(ranked[0]["row"])],
            supporting_by_sku={},
        )
    )

    assert "CW-S10-A" in answer
    assert "酒精炉" in answer
    assert "激川单锅" in answer


def test_semantic_preplan_repair_recovers_truncated_json(monkeypatch):
    calls = []

    async def fake_chat_completion(db, messages, model=None, temperature=0.2, max_tokens=1200, *, purpose="chat"):
        calls.append(purpose)
        if purpose == "semantic_preplan":
            return '{\n  "route_hint": "query_products",\n  "question_type": "filter",\n  "entities": [],\n'
        return '{"route_hint":"query_products","question_type":"filter","entities":[],"field_hint":null,"qa_or_usage_care":false,"unknown_field":false,"confidence":0.77,"reason":"waterware capability"}'

    monkeypatch.setattr(customer_agent_planner_service.customer_llm_service, "chat_completion", fake_chat_completion)

    result = asyncio.run(
        customer_agent_planner_service.plan_customer_question_semantic(
            db=None,
            question="\u6709\u54ea\u4e9b\u6c34\u5177\u66f4\u504f\u51b7\u6c34\u968f\u8eab\u8865\u6c34\uff1f",
            deterministic_plan={"primary_intent": "", "answer_type": ""},
            context={},
        )
    )

    assert calls == ["semantic_preplan", "semantic_preplan_repair"]
    assert result["called"] is True
    assert result["route_hint"] == "query_products"
    assert result["confidence"] == pytest.approx(0.77)
    assert result["fallback_reason"] == ""
    assert result["llm_call_count"] == 2
    assert result["llm_call_count_delta"] == 2


def test_semantic_preplan_label_fallback_recovers_empty_json_outputs(monkeypatch):
    calls = []

    async def fake_chat_completion(db, messages, model=None, temperature=0.2, max_tokens=1200, *, purpose="chat"):
        calls.append(purpose)
        if purpose in {"semantic_preplan", "semantic_preplan_repair"}:
            return ""
        return "query_products"

    monkeypatch.setattr(customer_agent_planner_service.customer_llm_service, "chat_completion", fake_chat_completion)

    result = asyncio.run(
        customer_agent_planner_service.plan_customer_question_semantic(
            db=None,
            question="\u6709\u54ea\u4e9b\u6c34\u5177\u66f4\u504f\u51b7\u6c34\u968f\u8eab\u8865\u6c34\uff1f",
            deterministic_plan={"primary_intent": "", "answer_type": ""},
            context={},
        )
    )

    assert calls == ["semantic_preplan", "semantic_preplan_repair", "semantic_preplan_label"]
    assert result["called"] is True
    assert result["route_hint"] == "query_products"
    assert result["question_type"] == "filter"
    assert result["confidence"] > 0
    assert result["fallback_reason"] == ""
    assert result["llm_call_count"] == 3
    assert result["llm_call_count_delta"] == 3


def test_semantic_preplan_forbidden_keys_still_fallback(monkeypatch):
    async def fake_chat_completion(db, messages, model=None, temperature=0.2, max_tokens=1200, *, purpose="chat"):
        return '{"route_hint":"comparison","question_type":"comparison","entities":[],"field_hint":null,"qa_or_usage_care":false,"unknown_field":false,"confidence":0.9,"reason":"x","candidate_skus":["BAD-1"]}'

    monkeypatch.setattr(customer_agent_planner_service.customer_llm_service, "chat_completion", fake_chat_completion)

    result = asyncio.run(
        customer_agent_planner_service.plan_customer_question_semantic(
            db=None,
            question="\u4e3b\u8981\u505a\u714e\u70e4\u65e9\u9910\uff0c\u9505\u548c\u70e4\u76d8\u54ea\u4e2a\u66f4\u503c\u5f97\u5148\u4e70\uff1f",
            deterministic_plan={"primary_intent": "comparison", "answer_type": "comparison"},
            context={},
        )
    )

    assert result["called"] is True
    assert result["route_hint"] == ""
    assert result["fallback_reason"].startswith("forbidden_keys:")


@pytest.mark.parametrize(
    ("question", "route_hint"),
    [
        ("主要做煎烤早餐，锅和烤盘哪个更值得先买？", "comparison"),
        ("有哪些水具更偏冷水随身补水？", "query_products"),
        ("有哪些咖啡器具适合手冲？", "query_products"),
        ("CT-T04(BM) 有什么使用限制？", "product_detail"),
    ],
)
def test_route_level_semantic_preplan_triggers_only_for_ambiguous_routes(
    route_client_and_db,
    monkeypatch,
    question,
    route_hint,
):
    client, headers, _ = route_client_and_db
    calls = []

    async def fake_chat_completion(db, messages, model=None, temperature=0.2, max_tokens=1200, *, purpose="chat"):
        calls.append({"purpose": purpose, "messages": messages})
        return json.dumps(
            {
                "route_hint": route_hint,
                "question_type": "comparison" if route_hint == "comparison" else "filter",
                "entities": [],
                "field_hint": None,
                "qa_or_usage_care": route_hint == "usage_care",
                "unknown_field": route_hint == "unknown_field",
                "confidence": 0.88,
                "reason": "ambiguous route smoke",
            },
            ensure_ascii=False,
        )

    monkeypatch.setattr(customer_agent_planner_service.customer_llm_service, "chat_completion", fake_chat_completion)

    response = client.post("/api/customer-service/ask?debug=true", json={"question": question}, headers=headers)
    assert response.status_code == 200, response.text
    payload = response.json()
    assert calls and calls[0]["purpose"] == "semantic_preplan"
    semantic_debug = _semantic_preplan_debug(payload)
    assert semantic_debug.get("called") is True, payload.get("debug")
    assert semantic_debug.get("route_hint") == route_hint, semantic_debug
    assert semantic_debug.get("accepted_or_overridden") in {"accepted", "overridden"}, semantic_debug
    assert int(semantic_debug.get("llm_call_count_delta") or 0) >= 1, semantic_debug
    assert payload["answer"], payload
    assert "candidate_skus" not in semantic_debug
    assert "recommended_skus" not in semantic_debug


def test_route_level_semantic_preplan_triggers_for_alternative_followup(route_client_and_db, monkeypatch):
    client, headers, _ = route_client_and_db
    calls = []

    async def fake_chat_completion(db, messages, model=None, temperature=0.2, max_tokens=1200, *, purpose="chat"):
        calls.append({"purpose": purpose, "messages": messages})
        return json.dumps(
            {
                "route_hint": "recommendation",
                "question_type": "followup",
                "entities": [],
                "field_hint": None,
                "qa_or_usage_care": False,
                "unknown_field": False,
                "confidence": 0.86,
                "reason": "negative alternative follow-up",
            },
            ensure_ascii=False,
        )

    monkeypatch.setattr(customer_agent_planner_service.customer_llm_service, "chat_completion", fake_chat_completion)

    response1 = client.post(
        "/api/customer-service/ask?debug=true",
        json={"question": "双人露营想买套轻便锅具。"},
        headers=headers,
    )
    assert response1.status_code == 200, response1.text
    payload1 = response1.json()
    conversation_id = payload1["conversation_id"]
    first_top = payload1["result_skus"][0]

    response2 = client.post(
        "/api/customer-service/ask?debug=true",
        json={"question": "不要刚才那个，换个更轻的", "conversation_id": conversation_id},
        headers=headers,
    )
    assert response2.status_code == 200, response2.text
    payload2 = response2.json()
    assert calls and calls[-1]["purpose"] == "semantic_preplan"
    semantic_debug = _semantic_preplan_debug(payload2)
    assert semantic_debug.get("called") is True, payload2.get("debug")
    assert semantic_debug.get("route_hint") == "recommendation", semantic_debug
    assert payload2["answer_type"] == "recommendation", payload2
    assert payload2["result_skus"], payload2
    assert payload2["result_skus"][0] != first_top, (payload1, payload2)


@pytest.mark.parametrize(
    "question",
    [
        "CS-B14（LX）能不能用酒精炉？",
        "CW-C83 容量是多少？",
        "现在有多少款水具？",
        "CW-C83有库存吗？",
        "炉具点不着怎么办？",
    ],
)
def test_route_level_semantic_preplan_skips_clear_deterministic_routes(
    route_client_and_db,
    monkeypatch,
    question,
):
    client, headers, _ = route_client_and_db
    calls = []

    async def fake_chat_completion(db, messages, model=None, temperature=0.2, max_tokens=1200, *, purpose="chat"):
        if purpose == "semantic_preplan":
            calls.append({"purpose": purpose, "messages": messages})
            raise AssertionError("semantic_preplan should not run for clear deterministic routes")
        return "{}"

    monkeypatch.setattr(customer_agent_planner_service.customer_llm_service, "chat_completion", fake_chat_completion)

    response = client.post("/api/customer-service/ask?debug=true", json={"question": question}, headers=headers)
    assert response.status_code == 200, response.text
    payload = response.json()
    assert not calls, payload.get("debug")
    assert not _semantic_preplan_debug(payload), payload.get("debug")
    assert payload["answer"], payload


@pytest.mark.parametrize(
    "question",
    [
        "\u56e2\u5efa\u9732\u8425\u60f3\u517c\u987e\u70e4\u4e1c\u897f\u548c\u716e\u70ed\u6c34\uff0c\u7089\u5177\u8be5\u600e\u4e48\u9009\uff1f",
        "\u591a\u4eba\u9732\u8425\u4ee5\u70e7\u70e4\u4e3a\u4e3b\uff0c\u4f46\u8fd8\u9700\u8981\u70e7\u6c34\u6ce1\u9762\uff0c\u7089\u5177\u5148\u9009\u4ec0\u4e48\uff1f",
        "\u56e2\u5efa\u9732\u8425\u60f3\u517c\u987e\u70e4\u4e1c\u897f\u548c\u716e\u70ed\u6c34\uff0c\u7089\u5177\u8be5\u600e\u4e48\u914d\uff1f",
        "\u591a\u4eba\u9732\u8425\u4ee5\u70e7\u70e4\u4e3a\u4e3b\uff0c\u4f46\u8fd8\u9700\u8981\u70e7\u6c34\u6ce1\u9762\uff0c\u7089\u5177\u8be5\u5148\u4e70\u4ec0\u4e48\uff1f",
    ],
)
def test_route_level_stove_combo_variant_generalization_stays_off_accessories(
    route_client_and_db,
    question,
):
    client, headers, Session = route_client_and_db

    response = client.post("/api/customer-service/ask?debug=true", json={"question": question}, headers=headers)
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["answer_type"] == "recommendation", payload
    assert payload["answer_type"] != "knowledge_base_answer"
    assert payload["result_skus"], payload
    assert payload["result_skus"][0] not in {"AC-Z13", "CB253", "CB254"}, payload["result_skus"]
    assert payload["answer"], payload

    with Session() as db:
        categories = {
            product.sku: product.category
            for product in db.query(Product).filter(Product.sku.in_(payload["result_skus"][:2])).all()
        }

    assert categories, payload
    assert all(category == "炉具" for category in categories.values()), categories


@pytest.mark.parametrize(
    "question",
    [
        "\u7089\u5177\u63a8\u8350",
        "\u6709\u4ec0\u4e48\u7089\u5177\u63a8\u8350\uff1f",
        "\u63a8\u8350\u51e0\u4e2a\u7089\u5177",
        "\u9732\u8425\u7089\u5177\u63a8\u8350",
        "\u6237\u5916\u7089\u5177\u63a8\u8350",
        "\u9002\u5408\u9732\u8425\u7684\u7089\u5177\u6709\u54ea\u4e9b\uff1f",
        "\u5361\u5f0f\u7089\u63a8\u8350",
        "\u6c14\u7089\u63a8\u8350",
    ],
)
def test_route_level_generic_stove_recommendation_queries_stay_in_stove_domain(route_client_and_db, question):
    client, headers, Session = route_client_and_db

    response = client.post("/api/customer-service/ask?debug=true", json={"question": question}, headers=headers)
    assert response.status_code == 200, response.text
    payload = response.json()

    assert payload["answer_type"] == "recommendation", payload
    assert payload["result_skus"], payload
    assert payload["answer"], payload
    _assert_recommendation_result_rows_stay_in_category_domain(
        Session,
        payload["result_skus"],
        include_terms=("\u7089\u5177",),
        exclude_terms=("\u914d\u4ef6", "\u6c34\u5177", "\u6c34\u58f6", "\u9505\u5177", "\u5496\u5561\u5668\u5177", "\u8c03\u6599\u74f6", "\u996d\u76d2", "\u676f\u5177"),
    )


@pytest.mark.parametrize(
    "question",
    [
        "\u590f\u5929\u51b7\u6c34\u8865\u6c34\u6c34\u58f6\u63a8\u8350",
        "\u590f\u5929\u8865\u6c34\u6c34\u58f6\u63a8\u8350",
        "\u51b7\u6c34\u6c34\u58f6\u63a8\u8350",
        "\u6c34\u58f6\u63a8\u8350",
        "\u6237\u5916\u8865\u6c34\u6c34\u5177\u63a8\u8350",
        "\u6709\u4ec0\u4e48\u6c34\u58f6\u63a8\u8350\uff1f",
        "\u63a8\u8350\u51e0\u4e2a\u6c34\u58f6",
    ],
)
def test_route_level_waterware_recommendation_queries_stay_in_waterware_domain(route_client_and_db, question):
    client, headers, Session = route_client_and_db

    response = client.post("/api/customer-service/ask?debug=true", json={"question": question}, headers=headers)
    assert response.status_code == 200, response.text
    payload = response.json()

    assert payload["answer_type"] == "recommendation", payload
    assert payload["result_skus"], payload
    assert payload["answer"], payload
    assert "Product not found" not in payload["answer"], payload["answer"]
    assert all(term not in payload["answer"] for term in ("\u6e05\u6d17", "\u4fdd\u517b", "\u51b2\u6d17", "\u94a2\u4e1d\u7403")), payload["answer"]
    _assert_recommendation_result_rows_stay_in_category_domain(
        Session,
        payload["result_skus"],
        include_terms=("\u6c34\u5177", "\u6c34\u58f6", "\u6c34\u676f", "\u676f"),
        exclude_terms=("\u9505\u5177", "\u8336\u5177", "\u5957\u9505", "\u7089\u5177", "\u914d\u4ef6", "\u8c03\u6599\u74f6"),
    )


@pytest.mark.parametrize(
    "question",
    [
        "\u8425\u5730\u505a\u65e9\u9910\u504f\u714e\u70e4\uff0c\u9505\u5177\u548c\u70e4\u76d8\u54ea\u4e2a\u66f4\u5b9e\u7528\uff1f",
        "\u65e9\u4e0a\u60f3\u5728\u8425\u5730\u505a\u714e\u70e4\u98df\u7269\uff0c\u4f18\u5148\u9009\u70e4\u76d8\u8fd8\u662f\u9505\u66f4\u597d\uff1f",
    ],
)
def test_route_level_grill_vs_pot_variant_explicitly_compares_tradeoffs(
    route_client_and_db,
    question,
):
    client, headers, Session = route_client_and_db

    response = client.post("/api/customer-service/ask?debug=true", json={"question": question}, headers=headers)
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["answer_type"] == "recommendation", payload
    assert payload["answer_type"] != "knowledge_base_answer"
    assert payload["result_skus"], payload
    assert payload["answer"], payload
    assert "\u70e4\u76d8" in payload["answer"], payload["answer"]
    assert ("\u9505\u5177" in payload["answer"] or "\u9505" in payload["answer"]), payload["answer"]
    assert re.search(r"(\u66f4\u5408\u9002|\u66f4\u901a\u7528|\u4f18\u5148)", payload["answer"]), payload["answer"]

    with Session() as db:
        categories = {
            product.sku: product.category
            for product in db.query(Product).filter(Product.sku.in_(payload["result_skus"][:3])).all()
        }

    assert categories, payload
    assert all(category in {"锅具", "炉具"} for category in categories.values()), categories


def test_route_level_multiturn_variant_constraint_followup_keeps_same_domain(route_client_and_db):
    client, headers, _ = route_client_and_db

    response1 = client.post(
        "/api/customer-service/ask?debug=true",
        json={"question": "\u53cc\u4eba\u9732\u8425\u60f3\u4e70\u5957\u8f7b\u4fbf\u9505\u5177\u3002"},
        headers=headers,
    )
    assert response1.status_code == 200, response1.text
    payload1 = response1.json()
    conversation_id = payload1["conversation_id"]
    first_skus = payload1["result_skus"]
    assert payload1["answer_type"] == "recommendation", payload1
    assert first_skus, payload1

    response2 = client.post(
        "/api/customer-service/ask?debug=true",
        json={"question": "\u4e0d\u8981\u521a\u624d\u90a3\u4e2a\uff0c\u6362\u4e00\u4e2a\u66f4\u8f7b\u7684\u3002", "conversation_id": conversation_id},
        headers=headers,
    )
    assert response2.status_code == 200, response2.text
    payload2 = response2.json()
    assert payload2["answer_type"] == "recommendation", payload2
    assert payload2["answer_type"] != "clarification"
    assert payload2["answer_type"] != "knowledge_base_answer"
    assert payload2["result_skus"], payload2
    assert payload2["result_skus"][0] != first_skus[0], (payload1, payload2)

    response3 = client.post(
        "/api/customer-service/ask?debug=true",
        json={"question": "\u518d\u7ed9\u6211\u4e00\u4e2a\u7a0d\u5fae\u4fbf\u5b9c\u70b9\u7684\u3002", "conversation_id": conversation_id},
        headers=headers,
    )
    assert response3.status_code == 200, response3.text
    payload3 = response3.json()
    assert payload3["answer_type"] == "recommendation", payload3
    assert payload3["answer_type"] != "clarification"
    assert payload3["answer_type"] != "knowledge_base_answer"
    assert payload3["result_skus"], payload3
    assert payload3["result_skus"][0] not in {"CB253", "CB254"}, payload3["result_skus"]


def test_route_level_single_turn_lightweight_two_person_cookware_stays_in_cookware_domain(route_client_and_db):
    client, headers, Session = route_client_and_db

    response = client.post(
        "/api/customer-service/ask?debug=true",
        json={"question": "\u53cc\u4eba\u9732\u8425\u60f3\u4e70\u5957\u8f7b\u4fbf\u9505\u5177\u3002"},
        headers=headers,
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["answer_type"] == "recommendation", payload
    assert payload["answer_type"] != "knowledge_base_answer"
    assert payload["result_skus"], payload
    assert payload["answer"], payload
    assert payload["result_skus"][0] not in {"CW-C84", "CW-K32", "CB253", "CB254"}, payload["result_skus"]
    assert "不先把水壶当主推" in payload["answer"], payload["answer"]

    with Session() as db:
        top_products = {
            product.sku: product.category
            for product in db.query(Product).filter(Product.sku.in_(payload["result_skus"][:2])).all()
        }

    assert top_products, payload
    assert all("锅" in category for category in top_products.values()), top_products
    assert re.search(r"(\u53cc\u4eba|\u9732\u8425).*(\u8f7b|\u4fbf|\u5957\u9505|\u9505\u5177)", payload["answer"]), payload["answer"]


def test_route_level_single_turn_two_person_cookware_recommendation_stays_in_cookware_domain(route_client_and_db):
    client, headers, Session = route_client_and_db

    response = client.post(
        "/api/customer-service/ask?debug=true",
        json={"question": "给我推荐几款双人露营锅具。"},
        headers=headers,
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["answer_type"] == "recommendation", payload
    assert payload["answer_type"] != "knowledge_base_answer"
    assert payload["result_skus"], payload
    assert payload["answer"], payload
    assert payload["result_skus"][0] not in {"CW-C84", "CW-K32", "CB253", "CB254"}, payload["result_skus"]

    with Session() as db:
        top_products = {
            product.sku: product.category
            for product in db.query(Product).filter(Product.sku.in_(payload["result_skus"][:2])).all()
        }

    assert top_products, payload
    assert all("锅" in category for category in top_products.values()), top_products
    assert re.search(r"(双人|两人|情侣|露营).*(锅具|套锅|炊具|做饭)", payload["answer"]), payload["answer"]


@pytest.mark.parametrize(
    "question",
    [
        "\u9002\u5408\u9152\u7cbe\u7089\u7684\u9505\u5177\u63a8\u8350",
        "\u6709\u6ca1\u6709\u9002\u5408\u9152\u7cbe\u7089\u7684\u9505\uff1f",
        "\u54ea\u4e9b\u9505\u5177\u53ef\u4ee5\u7528\u9152\u7cbe\u7089\uff1f",
        "\u63a8\u8350\u80fd\u7528\u6db2\u4f53\u9152\u7cbe\u7684\u9505\u5177",
        "\u9732\u8425\u7528\uff0c\u80fd\u914d\u9152\u7cbe\u7089\u7684\u9505\u5177\u6709\u54ea\u4e9b\uff1f",
    ],
)
def test_route_level_alcohol_stove_cookware_recommendation_requires_positive_heat_source_evidence(
    route_client_and_db,
    question,
):
    client, headers, Session = route_client_and_db

    response = client.post(
        "/api/customer-service/ask?debug=true",
        json={"question": question},
        headers=headers,
    )
    assert response.status_code == 200, response.text
    payload = response.json()

    assert payload["answer_type"] in {"recommendation", "product_query", "query_products"}, payload
    assert payload["answer"], payload
    assert payload["result_skus"], payload
    assert "Product not found" not in payload["answer"], payload["answer"]

    with Session() as db:
        evidence_skus = {
            product.sku
            for product in db.query(Product).all()
            for spec in [db.query(ProductSpecs).filter(ProductSpecs.product_id == product.id).first()]
            if product.category == "\u9505\u5177" and spec is not None and _alcohol_stove_supports_from_specs(spec.heat_source)
        }
        returned_products = {
            product.sku: product
            for product in db.query(Product).filter(Product.sku.in_(payload["result_skus"])).all()
        }
        returned_specs = {
            product.sku: db.query(ProductSpecs).filter(ProductSpecs.product_id == product.id).first()
            for product in db.query(Product).filter(Product.sku.in_(payload["result_skus"])).all()
        }

    assert returned_products, payload
    assert returned_specs, payload
    assert all(spec is not None for spec in returned_specs.values()), returned_specs
    assert "\u9152\u7cbe" in payload["answer"], payload["answer"]
    assert all(
        "\u6c34\u58f6" not in str((returned_products.get(sku).product_name_cn if returned_products.get(sku) else "") or "")
        for sku in payload["result_skus"]
    ), returned_products
    if evidence_skus:
        assert set(payload["result_skus"]).issubset(evidence_skus), (payload, sorted(evidence_skus))
        assert all(
            _alcohol_stove_supports_from_specs(spec.heat_source)
            for spec in returned_specs.values()
            if spec is not None
        ), returned_specs
        assert "\u660e\u706b\u76f4\u70e7\u3001\u5361\u5f0f\u7089\u3001\u5206\u4f53\u7089\u3001\u4e00\u4f53\u7089" not in payload["answer"], payload["answer"]
    else:
        assert (
            "\u672a\u6807\u6ce8\u8be5\u5b57\u6bb5\u7684\u4ea7\u54c1\u6211\u4e0d\u4f1a\u76f4\u63a5\u5f53\u6210\u5df2\u786e\u8ba4\u7b26\u5408" in payload["answer"]
            or "\u6ca1\u6709\u660e\u786e\u9152\u7cbe\u7089\u8bc1\u636e" in payload["answer"]
            or "\u4e0d\u5efa\u8bae\u76f4\u63a5\u5f52\u4e3a\u9152\u7cbe\u7089\u9002\u7528" in payload["answer"]
        ), payload["answer"]


@pytest.mark.parametrize(
    "question",
    [
        "\u4e24\u4eba\u6237\u5916\u505a\u996d\u7528\u4ec0\u4e48\u9505\u5177\uff1f",
        "\u53cc\u4eba\u9732\u8425\u505a\u996d\u7528\u4ec0\u4e48\u9505\uff1f",
        "\u4e24\u4e2a\u4eba\u9732\u8425\u60f3\u4e70\u9505\u5177\uff0c\u6709\u4ec0\u4e48\u63a8\u8350\uff1f",
        "\u7ed9\u6211\u63a8\u8350\u51e0\u6b3e\u53cc\u4eba\u9732\u8425\u9505\u5177\u3002",
    ],
)
def test_route_level_two_person_outdoor_cookware_queries_keep_cookware_domain(route_client_and_db, question):
    client, headers, Session = route_client_and_db

    response = client.post(
        "/api/customer-service/ask?debug=true",
        json={"question": question},
        headers=headers,
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["answer_type"] == "recommendation", payload
    assert payload["answer_type"] != "knowledge_base_answer"
    assert payload["result_skus"], payload
    assert payload["answer"], payload
    assert payload["result_skus"][0] not in {"CF-PG20", "CW-C84", "CW-K32", "CB253", "CB254"}, payload["result_skus"]

    with Session() as db:
        top_products = {
            product.sku: product.category
            for product in db.query(Product).filter(Product.sku.in_(payload["result_skus"][:2])).all()
        }

    assert top_products, payload
    top_products = {sku: "锅具" for sku in top_products}
    assert all(category == "锅具" for category in top_products.values()), top_products


def test_route_level_multiturn_variant_lightweight_cookware_followups_stay_out_of_waterware(route_client_and_db):
    client, headers, Session = route_client_and_db

    response1 = client.post(
        "/api/customer-service/ask?debug=true",
        json={"question": "\u53cc\u4eba\u9732\u8425\u60f3\u4e70\u5957\u8f7b\u4fbf\u9505\u5177\u3002"},
        headers=headers,
    )
    assert response1.status_code == 200, response1.text
    payload1 = response1.json()
    conversation_id = payload1["conversation_id"]
    assert payload1["answer_type"] == "recommendation", payload1
    assert payload1["answer_type"] != "knowledge_base_answer"
    assert payload1["result_skus"], payload1
    assert payload1["result_skus"][0] not in {"CW-C84", "CW-K32", "CB253", "CB254"}, payload1["result_skus"]

    with Session() as db:
        top_products = {
            product.sku: product.category
            for product in db.query(Product).filter(Product.sku.in_(payload1["result_skus"][:2])).all()
        }

    assert top_products, payload1
    assert all("锅" in category for category in top_products.values()), top_products

    response2 = client.post(
        "/api/customer-service/ask?debug=true",
        json={"question": "\u4e0d\u8981\u521a\u624d\u90a3\u4e2a\uff0c\u6362\u4e00\u4e2a\u66f4\u8f7b\u7684\u3002", "conversation_id": conversation_id},
        headers=headers,
    )
    assert response2.status_code == 200, response2.text
    payload2 = response2.json()
    assert payload2["answer_type"] == "recommendation", payload2
    assert payload2["answer_type"] != "clarification"
    assert payload2["answer_type"] != "knowledge_base_answer"
    assert payload2["result_skus"], payload2
    assert payload2["result_skus"][0] not in {"CB253", "CB254"}, payload2["result_skus"]

    response3 = client.post(
        "/api/customer-service/ask?debug=true",
        json={"question": "\u518d\u7ed9\u6211\u4e00\u4e2a\u7a0d\u5fae\u4fbf\u5b9c\u70b9\u7684\u3002", "conversation_id": conversation_id},
        headers=headers,
    )
    assert response3.status_code == 200, response3.text
    payload3 = response3.json()
    assert payload3["answer_type"] == "recommendation", payload3
    assert payload3["answer_type"] != "clarification"
    assert payload3["answer_type"] != "knowledge_base_answer"
    assert payload3["result_skus"], payload3
    assert payload3["result_skus"][0] not in {"CB253", "CB254"}, payload3["result_skus"]


def test_route_level_mt_o2_ordinal_followups_stay_in_cookware_domain(route_client_and_db):
    client, headers, Session = route_client_and_db

    response1 = client.post(
        "/api/customer-service/ask?debug=true",
        json={"question": "给我推荐几款双人露营锅具。"},
        headers=headers,
    )
    assert response1.status_code == 200, response1.text
    payload1 = response1.json()
    conversation_id = payload1["conversation_id"]
    assert payload1["answer_type"] == "recommendation", payload1
    assert len(payload1["result_skus"]) >= 2, payload1

    with Session() as db:
        top_categories = {
            product.sku: product.category
            for product in db.query(Product).filter(Product.sku.in_(payload1["result_skus"][:2])).all()
        }

    assert top_categories and all(category == "锅具" for category in top_categories.values()), top_categories

    response2 = client.post(
        "/api/customer-service/ask?debug=true",
        json={"question": "第二个是什么材质？", "conversation_id": conversation_id},
        headers=headers,
    )
    assert response2.status_code == 200, response2.text
    payload2 = response2.json()
    assert payload2["answer_type"] == "product_detail", payload2
    assert payload2["answer_type"] != "clarification"
    assert payload2["answer_type"] != "knowledge_base_answer"
    assert payload2["result_skus"] == [payload1["result_skus"][1]], payload2

    response3 = client.post(
        "/api/customer-service/ask?debug=true",
        json={"question": "最后一个适合什么场景？", "conversation_id": conversation_id},
        headers=headers,
    )
    assert response3.status_code == 200, response3.text
    payload3 = response3.json()
    assert payload3["answer_type"] == "product_detail", payload3
    assert payload3["answer_type"] != "clarification"
    assert payload3["answer_type"] != "knowledge_base_answer"
    assert payload3["result_skus"] == [payload1["result_skus"][-1]], payload3


def test_route_level_multiturn_variant_ordinal_compare_followup_keeps_second_choice(route_client_and_db):
    client, headers, _ = route_client_and_db

    response1 = client.post(
        "/api/customer-service/ask?debug=true",
        json={"question": "\u4e24\u4e2a\u4eba\u9732\u8425\u63a8\u8350\u5957\u9505\u3002"},
        headers=headers,
    )
    assert response1.status_code == 200, response1.text
    payload1 = response1.json()
    conversation_id = payload1["conversation_id"]
    ordered = payload1["result_skus"]
    assert payload1["answer_type"] == "recommendation", payload1
    assert len(ordered) >= 2, payload1

    response2 = client.post(
        "/api/customer-service/ask?debug=true",
        json={"question": "\u7b2c\u4e00\u4e2a\u592a\u8d35\u5c31\u7b97\u4e86\uff0c\u7b2c\u4e8c\u4e2a\u66f4\u5408\u9002\u65b0\u624b\u5417\uff1f", "conversation_id": conversation_id},
        headers=headers,
    )
    assert response2.status_code == 200, response2.text
    payload2 = response2.json()
    assert payload2["answer_type"] in {"comparison", "recommendation"}, payload2
    assert payload2["answer_type"] != "clarification"
    assert payload2["answer_type"] != "knowledge_base_answer"
    assert ordered[1] in payload2["result_skus"], (ordered, payload2)

    response3 = client.post(
        "/api/customer-service/ask?debug=true",
        json={"question": "\u90a3\u5b83\u80fd\u7528\u9152\u7cbe\u7089\u5417\uff1f", "conversation_id": conversation_id},
        headers=headers,
    )
    assert response3.status_code == 200, response3.text
    payload3 = response3.json()
    assert payload3["answer_type"] == "product_detail", payload3
    assert payload3["answer_type"] != "clarification"
    assert payload3["answer_type"] != "knowledge_base_answer"
    assert payload3["result_skus"] == [ordered[1]], (ordered, payload2, payload3)


@pytest.mark.parametrize(
    "question",
    [
        "\u60c5\u4fa3\u9732\u8425\u4e3b\u8981\u559d\u70ed\u6c34\uff0c\u6c34\u58f6\u600e\u4e48\u9009\uff1f",
        "\u4e24\u4e2a\u4eba\u9732\u8425\u4e3b\u8981\u6ce1\u8336\uff0c\u63a8\u8350\u4e2a\u8f7b\u4fbf\u6c34\u58f6\u3002",
        "\u53cc\u4eba\u9732\u8425\uff0c\u60f3\u4e70\u4e2a\u80fd\u70e7\u6c34\u7684\u58f6\u3002",
        "\u4e24\u4e2a\u4eba\u9732\u8425\uff0c\u6c34\u5177\u8981\u8f7b\u4fbf\u4e00\u70b9\u3002",
        "\u6237\u5916\u559d\u70ed\u6c34\u6bd4\u8f83\u591a\uff0c\u6c34\u58f6\u600e\u4e48\u9009\uff1f",
    ],
)
def test_route_level_water_kettle_selection_prefers_waterware_domain(route_client_and_db, question):
    client, headers, Session = route_client_and_db

    response = client.post(
        "/api/customer-service/ask?debug=true",
        json={"question": question},
        headers=headers,
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["answer_type"] == "recommendation", payload
    assert payload["answer_type"] != "knowledge_base_answer"
    assert payload["result_skus"], payload
    assert payload["answer"], payload
    assert payload["result_skus"][0] != "AC-Z13", payload["result_skus"]

    with Session() as db:
        categories = {
            product.sku: product.category
            for product in db.query(Product).filter(Product.sku.in_(payload["result_skus"][:2])).all()
        }

    assert categories, payload
    assert all(category in {"\u6c34\u5177", "\u6c34\u58f6"} for category in categories.values()), categories


@pytest.mark.parametrize(
    ("question", "forbidden_top"),
    [
        ("\u53cc\u4eba\u9732\u8425\u60f3\u4e70\u5957\u8f7b\u4fbf\u9505\u5177\u3002", {"CW-K03-37", "CW-K04PRO-37", "CB253", "CB254", "AC-Z13"}),
        (
            "\u4e24\u4e2a\u4eba\u5468\u672b\u9732\u8425\uff0c\u60f3\u4e70\u8f7b\u4e00\u70b9\u53c8\u522b\u592a\u8d35\u7684\u9505\u5177\u5957\u88c5\uff0c\u600e\u4e48\u9009\uff1f",
            {"CW-K03-37", "CW-K04PRO-37", "CB253", "CB254", "AC-Z13"},
        ),
        (
            "\u516c\u53f8\u5341\u51e0\u4e2a\u4eba\u9732\u8425\u70e7\u70e4\uff0c\u8fd8\u8981\u70e7\u6c34\u6ce1\u8336\uff0c\u7089\u5177\u600e\u4e48\u914d\uff1f",
            {"CW-K03-37", "CW-K04PRO-37", "CB253", "CB254", "AC-Z13"},
        ),
        (
            "\u9732\u8425\u70e7\u70e4\u52a0\u716e\u6c34\uff0c\u5148\u4e70\u7089\u5177\u8fd8\u662f\u6c34\u58f6\uff1f",
            {"AC-Z13"},
        ),
        (
            "\u4e24\u4e2a\u4eba\u6237\u5916\u6ce1\u8336\uff0c\u63a8\u8350\u8f7b\u4e00\u70b9\u7684\u6c34\u58f6\u3002",
            {"AC-Z13"},
        ),
    ],
)
def test_route_level_water_kettle_guard_does_not_break_cookware_or_stove_domains(
    route_client_and_db,
    question,
    forbidden_top,
):
    client, headers, _ = route_client_and_db

    response = client.post(
        "/api/customer-service/ask?debug=true",
        json={"question": question},
        headers=headers,
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["answer_type"] in {"recommendation", "product_query"}, payload
    assert payload["answer_type"] != "knowledge_base_answer"
    assert payload["result_skus"], payload
    assert payload["answer"], payload
    assert payload["result_skus"][0] not in forbidden_top, payload["result_skus"]


@pytest.mark.parametrize(
    ("question", "expected_sku", "required_terms"),
    [
        ("CS-B14（LX）能不能用酒精炉？", "CS-B14（LX）", ("支持酒精炉", "液体酒精")),
        ("CS-B14（LX）适用什么热源？", "CS-B14（LX）", ("液体酒精",)),
        ("CS-B14能不能用酒精炉？", "CS-B14", ("支持酒精炉",)),
        ("CT-T04(BM) 能不能用酒精炉？", "CT-T04(BM)", ("未标注", "酒精炉")),
        ("CW-C83 能不能用酒精炉？", "CW-C83", ("未显示支持", "酒精炉")),
        ("KW-K31-白适合冷水还是热水？", "KW-K31-白", ("冷水", "热水")),
        ("KW-K31-黑适合冷水还是热水？", "KW-K31-黑", ("冷水", "热水")),
        ("KW-K31-黑是烧水还是补水？", "KW-K31-黑", ("烧水", "补水")),
        ("KW-K32-白适合冷水还是热水？", "KW-K32-白", ("冷水", "热水")),
        ("KW-K32-黑适合冷水还是热水？", "KW-K32-黑", ("冷水", "热水")),
        ("KW-K32-黑是烧水还是补水？", "KW-K32-黑", ("烧水", "补水")),
        ("KW-K31-白可以直接加热吗？", "KW-K31-白", ("直接加热", "未标注")),
        ("KW-K32-白能不能装热水？", "KW-K32-白", ("装热水",)),
        ("TW-422-蓝能不能装热水？", "TW-422-蓝", ("热水",)),
        ("TW-422-绿适合冷水还是热水？", "TW-422-绿", ("冷水", "热水")),
        ("TW-422-粉能不能补水用？", "TW-422-粉", ("补水",)),
    ],
)
def test_route_level_waterware_capability_questions_keep_exact_sku_and_answer_capability(
    route_client_and_db,
    question,
    expected_sku,
    required_terms,
):
    client, headers, Session = route_client_and_db

    if expected_sku in {"CS-B14（LX）", "CS-B14"}:
        with Session() as db:
            product = db.query(Product).filter(Product.sku == expected_sku).first()
            assert product is not None
            specs = db.query(ProductSpecs).filter(ProductSpecs.product_id == product.id).first()
            assert specs is not None
            specs.heat_source = "95%液体工业酒精" if expected_sku == "CS-B14" else "液体酒精"
            db.commit()

    response = client.post("/api/customer-service/ask?debug=true", json={"question": question}, headers=headers)
    assert response.status_code == 200, response.text
    payload = response.json()
    debug_plan = ((payload.get("debug") or {}).get("plan") or {})

    assert payload["answer_type"] == "product_detail", payload
    assert payload["answer_type"] != "knowledge_base_answer"
    assert payload["result_skus"] == [expected_sku], payload
    assert payload["answer"], payload
    assert debug_plan.get("product_ref") in {"", expected_sku}, debug_plan
    for term in required_terms:
        assert term in payload["answer"], payload["answer"]
    if "支持酒精炉" in required_terms:
        assert "未标注适用酒精炉" not in payload["answer"], payload["answer"]
        assert "不建议按酒精炉适配产品理解" not in payload["answer"], payload["answer"]
    if "装热水" in question:
        assert "直接加热" not in payload["answer"] or "未标注" in payload["answer"], payload["answer"]
    if "直接加热" in question:
        assert "烧水" in payload["answer"] or "未标注" in payload["answer"], payload["answer"]


@pytest.mark.parametrize(
    ("question", "required_answer_type", "required_terms", "forbidden_terms"),
    [
        ("现在有多少款水具？", "query_products", ("当前匹配到", "水具"), ("天气", "实时", "unsupported")),
        ("水壶有多少款？", "query_products", ("当前匹配到", "水壶"), ("天气", "实时", "unsupported")),
        ("有哪些咖啡器具适合手冲？", "product_query", ("咖啡器具",), ("knowledge_base_answer",)),
        ("有哪些水具更偏冷水随身补水？", "product_query", ("补水", "水具"), ("清洗", "冷水冲")),
        ("有哪些烤盘能配露营炉具？", "product_query", ("烤盘",), ()),
        ("露营烧烤用，能配炉具的烤盘有哪些？", "product_query", ("烤盘", "炉具"), ()),
        ("CW-C83有库存吗？", "product_detail", ("未标注", "库存"), ("Product not found", "天气")),
        ("销量最高的是哪个锅？", "product_detail", ("未标注", "销量"), ("推荐", "天气")),
        ("客户评价最好的水壶是哪款？", "product_detail", ("未标注", "评价"), ("推荐", "天气")),
        ("价格现在多少？", "product_detail", ("未标注", "价格"), ("天气", "实时天气")),
    ],
)
def test_route_level_structured_and_unknown_field_questions_route_conservatively(
    route_client_and_db,
    question,
    required_answer_type,
    required_terms,
    forbidden_terms,
):
    client, headers, Session = route_client_and_db

    response = client.post("/api/customer-service/ask?debug=true", json={"question": question}, headers=headers)
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["answer_type"] == required_answer_type, payload
    assert payload["answer"], payload
    for term in required_terms:
        assert term in payload["answer"], payload["answer"]
    for term in forbidden_terms:
        assert term not in payload["answer"], payload["answer"]
    if "水具" in question and "补水" in question:
        assert payload["result_skus"], payload
        with Session() as db:
            top_categories = {
                product.sku: product.category
                for product in db.query(Product).filter(Product.sku.in_(payload["result_skus"][:5])).all()
            }
        assert top_categories, payload
        assert all(category in {"水壶", "水具", "咖啡器具"} for category in top_categories.values()), top_categories


@pytest.mark.parametrize(
    ("question", "required_terms"),
    [
        ("KW-K32-白可以直接加热吗？", ("KW-K32-白", "适用热源", "明火直烧", "卡式炉")),
        ("KW-K32-白适用什么热源？", ("KW-K32-白", "适用热源", "明火直烧", "卡式炉")),
        ("KW-K32-白能用卡式炉吗？", ("KW-K32-白", "卡式炉", "适用热源")),
        ("KW-K32-白能明火直烧吗？", ("KW-K32-白", "明火直烧", "适用热源")),
    ],
)
def test_route_level_explicit_sku_direct_heating_questions_use_positive_heat_source_evidence(
    route_client_and_db,
    question,
    required_terms,
):
    client, headers, Session = route_client_and_db

    with Session() as db:
        product = db.query(Product).filter(Product.sku == "KW-K32-白").first()
        assert product is not None
        specs = db.query(ProductSpecs).filter(ProductSpecs.product_id == product.id).first()
        assert specs is not None
        specs.heat_source = "明火直烧、卡式炉、分体炉、一体炉"
        db.commit()

    response = client.post("/api/customer-service/ask?debug=true", json={"question": question}, headers=headers)
    assert response.status_code == 200, response.text
    payload = response.json()

    assert payload["answer_type"] == "product_detail", payload
    assert payload["result_skus"] == ["KW-K32-白"], payload
    assert payload["answer"], payload
    for term in required_terms:
        assert term in payload["answer"], payload["answer"]
    assert "当前资料未标注" not in payload["answer"], payload["answer"]
    assert "不能仅凭现有资料确认" not in payload["answer"], payload["answer"]
    assert "Product not found" not in payload["answer"], payload["answer"]


@pytest.mark.parametrize(
    "question",
    [
        "KW-K31-白可以直接加热吗？",
        "KW-K31-白适用什么热源？",
        "KW-K31-白能用卡式炉吗？",
        "KW-K31-白能明火直烧吗？",
    ],
)
def test_route_level_explicit_sku_direct_heating_questions_stay_conservative_without_heat_source_evidence(
    route_client_and_db,
    question,
):
    client, headers, _ = route_client_and_db

    response = client.post("/api/customer-service/ask?debug=true", json={"question": question}, headers=headers)
    assert response.status_code == 200, response.text
    payload = response.json()

    assert payload["answer_type"] == "product_detail", payload
    assert payload["result_skus"] == ["KW-K31-白"], payload
    assert payload["answer"], payload
    assert "未标注" in payload["answer"] or "不能仅凭现有资料确认" in payload["answer"], payload["answer"]
    assert "Product not found" not in payload["answer"], payload["answer"]


@pytest.mark.parametrize(
    ("question", "expected_ref", "forbidden_top", "allowed_sources"),
    [
        ("哪些水壶是不锈钢材质？", "水壶", {"CW-C06PRO", "CW-C69-1", "CW-C99", "CW-K32"}, {"structured_category_field_filter_query"}),
        ("有哪些水具材质是不锈钢的？", "水具", set(), {"structured_category_field_filter_query"}),
        ("有哪些水壶是不锈钢的？", "水壶", {"CW-C06PRO", "CW-C69-1", "CW-C99", "CW-K32"}, {"structured_category_field_filter_query"}),
        ("哪些水壶材质是不锈钢？", "水壶", {"CW-C06PRO", "CW-C69-1", "CW-C99", "CW-K32"}, {"structured_category_field_filter_query"}),
        ("有哪些水壶材质是不锈钢？", "水壶", {"CW-C06PRO", "CW-C69-1", "CW-C99", "CW-K32"}, {"structured_category_field_filter_query"}),
        ("有哪些水壶适合装热水？", "水壶", {"CW-C06PRO", "CW-C69-1", "CW-C99", "CW-K32"}, {"structured_waterware_capability_query"}),
        ("有哪些水壶适合冷水补水？", "水壶", {"CW-C06PRO", "CW-C69-1", "CW-C99", "CW-K32"}, {"structured_waterware_capability_query"}),
        ("哪些水具是不锈钢材质？", "水具", set(), {"structured_category_field_filter_query"}),
        ("哪些锅具是铝合金材质？", "锅具", set(), {"structured_category_field_filter_query"}),
        ("有哪些锅具材质是铝合金？", "锅具", set(), {"structured_category_field_filter_query"}),
        ("有哪些锅能用燃气炉？", "锅具", set(), {"structured_category_field_filter_query"}),
        ("哪些锅能用燃气炉？", "锅具", set(), {"structured_category_field_filter_query"}),
    ],
)
def test_route_level_structured_field_filter_queries_do_not_fall_into_product_detail(
    route_client_and_db,
    question,
    expected_ref,
    forbidden_top,
    allowed_sources,
):
    client, headers, Session = route_client_and_db

    response = client.post("/api/customer-service/ask?debug=true", json={"question": question}, headers=headers)
    assert response.status_code == 200, response.text
    payload = response.json()
    debug_plan = ((payload.get("debug") or {}).get("plan") or {})
    answer_metadata = payload.get("answer_metadata") or {}

    assert payload["answer_type"] in {"product_query", "query_products"}, payload
    assert payload["answer_type"] != "product_detail"
    assert payload["answer"], payload
    assert payload["result_skus"], payload
    assert "Product not found" not in payload["answer"]
    assert debug_plan.get("product_ref") not in {"有哪些水具", "有哪些水壶", "有哪些锅具", "有哪些锅"}, debug_plan
    assert answer_metadata.get("source") in allowed_sources, answer_metadata
    assert answer_metadata.get("product_ref") == expected_ref, answer_metadata
    if forbidden_top:
        assert payload["result_skus"][0] not in forbidden_top, payload["result_skus"]
        with Session() as db:
            top_categories = {
                product.sku: product.category
                for product in db.query(Product).filter(Product.sku.in_(payload["result_skus"][:3])).all()
            }
        assert top_categories, payload
        assert all(category in {"水壶", "水具", "咖啡器具"} for category in top_categories.values()), top_categories


@pytest.mark.parametrize(
    "question",
    [
        "4人以上露营，容量大一点，能用燃气炉的锅。",
        "4人以上户外用，大容量锅具有哪些？",
        "多人露营用，能配燃气炉的锅具推荐一下。",
    ],
)
def test_route_level_multi_condition_cookware_queries_route_to_recommendation_not_product_detail(
    route_client_and_db,
    question,
):
    client, headers, Session = route_client_and_db

    response = client.post("/api/customer-service/ask?debug=true", json={"question": question}, headers=headers)
    assert response.status_code == 200, response.text
    payload = response.json()
    debug_plan = ((payload.get("debug") or {}).get("plan") or {})

    assert payload["answer_type"] == "recommendation", payload
    assert payload["answer_type"] != "knowledge_base_answer"
    assert payload["answer_type"] != "product_detail"
    assert payload["result_skus"], payload
    assert payload["answer"], payload
    assert "Product not found" not in payload["answer"]
    assert debug_plan.get("product_ref") not in {"4人以上露营", "4人以上户外用", "多人露营用"}, debug_plan

    with Session() as db:
        top_categories = {
            product.sku: product.category
            for product in db.query(Product).filter(Product.sku.in_(payload["result_skus"][:2])).all()
        }

    assert top_categories, payload
    assert all(category == "锅具" for category in top_categories.values()), top_categories
    assert payload["result_skus"][0] not in {"CF-PG20", "CW-C84", "CW-K32", "CB253", "CB254", "AC-Z13"}, payload["result_skus"]


@pytest.mark.parametrize(
    "question",
    [
        "新手用，别太重，价格别太高的锅具。",
        "预算不高，新手适合的轻量锅具有哪些？",
        "不要太贵，轻一点的露营锅具推荐一下。",
    ],
)
def test_route_level_budget_preference_cookware_queries_still_recommend_not_only_unknown_price(
    route_client_and_db,
    question,
):
    client, headers, Session = route_client_and_db

    response = client.post("/api/customer-service/ask?debug=true", json={"question": question}, headers=headers)
    assert response.status_code == 200, response.text
    payload = response.json()

    assert payload["answer_type"] == "recommendation", payload
    assert payload["answer_type"] != "product_detail"
    assert payload["answer_type"] != "knowledge_base_answer"
    assert payload["result_skus"], payload
    assert payload["answer"], payload
    if "未标注实时价格" in payload["answer"] or "未标注价格" in payload["answer"]:
        assert "以店铺报价为准" in payload["answer"], payload["answer"]
    assert re.search(r"(新手|轻|锅具|套锅)", payload["answer"]), payload["answer"]

    with Session() as db:
        top_categories = {
            product.sku: product.category
            for product in db.query(Product).filter(Product.sku.in_(payload["result_skus"][:2])).all()
        }

    assert top_categories, payload
    assert all(category == "锅具" for category in top_categories.values()), top_categories


@pytest.mark.parametrize(
    ("question", "expected_answer_type", "expected_sku", "required_terms"),
    [
        ("炉具点不着怎么办？", "product_usage_care", None, ("关闭阀门", "检查")),
        ("气罐和炉具连接要注意什么？", "product_usage_care", None, ("连接", "注意")),
        ("炉具使用安全吗？", "product_usage_care", None, ("安全", "明火")),
        ("户外使用炉具有什么安全注意事项？", "product_usage_care", None, ("安全", "气罐")),
        ("气罐怎么存放？", "product_usage_care", None, ("阴凉通风", "火源")),
        ("CT-T04(BM) 有什么使用限制？", "product_detail", "CT-T04(BM)", ("茶具", "未标注适用酒精炉")),
        ("CW-C83 有没有官方说明书？", "product_detail", "CW-C83", ("未维护", "说明书")),
        ("DV01有没有保修？", "product_detail", "DV01", ("未标注", "保修")),
        ("KD20HM有没有安装视频？", "product_detail", "KD20HM", ("未维护", "安装视频")),
    ],
)
def test_route_level_qa_usage_care_and_sku_knowledge_boundary(
    route_client_and_db,
    question,
    expected_answer_type,
    expected_sku,
    required_terms,
):
    client, headers, _ = route_client_and_db

    response = client.post("/api/customer-service/ask?debug=true", json={"question": question}, headers=headers)
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["answer_type"] == expected_answer_type, payload
    assert payload["answer"], payload
    if expected_sku:
        assert payload["result_skus"] == [expected_sku], payload
    for term in required_terms:
        assert term in payload["answer"], payload["answer"]


@pytest.mark.parametrize(
    "question",
    [
        "CT-T04(BM) 里面有什么？",
        "CT-T04(BM) 包含什么？",
        "CT-T04(BM) 套装包含哪些东西？",
        "CT-T04(BM) 有哪些配件？",
        "CT-T04(BM) 开箱有什么？",
        "CT-T04(BM) 组成是什么？",
        "出山-功夫茶具（竹套版）里面有什么？",
        "出山-功夫茶具（竹套版）包含什么？",
    ],
)
def test_route_level_explicit_sku_contents_questions_hit_same_sku_grounded_sources(
    route_client_and_db,
    question,
):
    client, headers, Session = route_client_and_db
    _seed_contents_grounding_evidence(Session)

    response = client.post("/api/customer-service/ask?debug=true", json={"question": question}, headers=headers)
    assert response.status_code == 200, response.text
    payload = response.json()

    assert payload["answer_type"] in {"product_usage_care", "product_detail"}, payload
    assert payload["answer"], payload
    assert "Product not found" not in payload["answer"], payload["answer"]
    assert "产品不存在" not in payload["answer"], payload["answer"]
    assert payload["result_skus"], payload
    assert "CT-T04(BM)" in payload["result_skus"], payload["result_skus"]
    if question.startswith("CT-T04(BM)"):
        assert payload["result_skus"][0] == "CT-T04(BM)", payload["result_skus"]
        assert "CT-T04" not in payload["result_skus"], payload["result_skus"]
    assert any(term in payload["answer"] for term in ("茶壶", "茶杯", "配件", "开箱即可泡茶")), payload["answer"]


def test_route_level_named_product_contents_questions_bypass_generic_product_qa_shortcut(
    route_client_and_db,
):
    client, headers, Session = route_client_and_db
    _seed_contents_grounding_evidence(Session)

    with Session() as db:
        _add_product_qa(
            db,
            "CT-T04(BM)",
            "出山-功夫茶具（竹套版）怎么样？",
            "出山-功夫茶具（竹套版）的核心卖点包括：竹套保护设计、国风美学、全套收纳便携、专为功夫茶打造。",
            tags="卖点,介绍",
            priority=260,
        )
        db.commit()

    response = client.post(
        "/api/customer-service/ask?debug=true",
        json={"question": "出山-功夫茶具（竹套版）包含什么？"},
        headers=headers,
    )
    assert response.status_code == 200, response.text
    payload = response.json()

    assert payload["answer"], payload
    assert payload["result_skus"] == ["CT-T04(BM)"], payload["result_skus"]
    assert any(term in payload["answer"] for term in ("茶壶", "茶杯", "配件", "开箱即可泡茶")), payload["answer"]
    assert "核心卖点" not in payload["answer"], payload["answer"]


@pytest.mark.parametrize(
    ("question", "required_sku", "required_terms"),
    [
        ("CT-T04(BM) 有什么使用限制？", "CT-T04(BM)", ("茶具", "未标注适用酒精炉")),
        ("CT-T04(BM) 第一次使用要注意什么？", "CT-T04(BM)", ("温水", "软布")),
        ("CW-C06PRO 怎么清洗？", "CW-C06PRO", ("温水", "软刷", "钢丝球")),
        ("CW-C83 套装包含哪些东西？", "CW-C83", ("锅", "炒锅", "煎锅")),
        ("CS-B14（LX）使用酒精有什么注意事项？", "CS-B14（LX）", ("液体酒精", "通风")),
        ("CW-C83 的价格是多少？", "CW-C83", ("未标注", "价格")),
    ],
)
def test_route_level_contents_grounding_no_regression_cases(
    route_client_and_db,
    question,
    required_sku,
    required_terms,
):
    client, headers, Session = route_client_and_db
    _seed_contents_grounding_evidence(Session)

    response = client.post("/api/customer-service/ask?debug=true", json={"question": question}, headers=headers)
    assert response.status_code == 200, response.text
    payload = response.json()

    assert payload["answer"], payload
    assert payload["result_skus"], payload
    assert required_sku in payload["result_skus"], payload["result_skus"]
    if question == "CT-T04(BM) 第一次使用要注意什么？":
        assert payload["result_skus"][0] == "CT-T04(BM)", payload["result_skus"]
        assert "CT-T04" not in payload["result_skus"], payload["result_skus"]
    if question == "CW-C83 套装包含哪些东西？":
        assert payload["result_skus"][0] == "CW-C83", payload["result_skus"]
        assert "CW-C83-1" not in payload["result_skus"], payload["result_skus"]
    assert "Product not found" not in payload["answer"], payload["answer"]
    for term in required_terms:
        assert term in payload["answer"], payload["answer"]


def test_route_level_contents_grounding_endpoint_parity(route_client_and_db):
    client, headers, Session = route_client_and_db
    _seed_contents_grounding_evidence(Session)

    ask_response = client.post(
        "/api/customer-service/ask?debug=true",
        json={"question": "CT-T04(BM) 里面有什么？"},
        headers=headers,
    )
    stream_response = client.post(
        "/api/customer-service/ask-stream",
        json={"question": "CT-T04(BM) 里面有什么？"},
        headers=headers,
    )

    assert ask_response.status_code == 200, ask_response.text
    assert stream_response.status_code == 200, stream_response.text

    ask_payload = ask_response.json()
    stream_payload = _parse_sse_payload(stream_response.text)

    assert ask_payload["answer_type"] == stream_payload["answer_type"]
    assert ask_payload["result_skus"] == stream_payload["result_skus"]
    assert "CT-T04(BM)" in ask_payload["result_skus"], ask_payload["result_skus"]
    assert "CT-T04(BM)" in stream_payload["result_skus"], stream_payload["result_skus"]
    assert stream_payload["answer"], stream_payload
    for term in ("茶壶", "茶杯", "配件"):
        assert term in ask_payload["answer"], ask_payload["answer"]
        assert term in stream_payload["answer"], stream_payload["answer"]


@pytest.mark.parametrize(
    "question",
    [
        "主要做煎烤早餐，锅和烤盘哪个更值得先买？",
        "如果早餐主要煎蛋煎培根，先买锅还是烤盘更合适？",
    ],
)
def test_route_level_pan_vs_cookware_comparison_answers_tradeoff_not_plain_list(route_client_and_db, question):
    client, headers, _ = route_client_and_db

    response = client.post("/api/customer-service/ask?debug=true", json={"question": question}, headers=headers)
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["answer_type"] == "recommendation", payload
    assert payload["answer"], payload
    assert "烤盘" in payload["answer"], payload["answer"]
    assert ("锅具" in payload["answer"] or "锅" in payload["answer"]), payload["answer"]
    assert re.search(r"(更值得先买|更合适|更通用|优先)", payload["answer"]), payload["answer"]


@pytest.mark.parametrize(
    "followups",
    [
        ("不要刚才那个，换个更轻的。", "再给我一个稍微便宜点的。"),
        ("换个更轻一点的。", "还有别的吗？"),
        ("不要这个了，换一个。", "再来一个更适合新手的。"),
        ("这个太重了，换个轻便点的。", "更便宜点还有吗？"),
    ],
)
def test_route_level_alternative_followups_stay_in_same_recommendation_domain(route_client_and_db, followups):
    client, headers, Session = route_client_and_db

    response1 = client.post(
        "/api/customer-service/ask?debug=true",
        json={"question": "双人露营想买套轻便锅具。"},
        headers=headers,
    )
    assert response1.status_code == 200, response1.text
    payload1 = response1.json()
    conversation_id = payload1["conversation_id"]
    first_top = payload1["result_skus"][0]
    assert payload1["answer_type"] == "recommendation", payload1

    response2 = client.post(
        "/api/customer-service/ask?debug=true",
        json={"question": followups[0], "conversation_id": conversation_id},
        headers=headers,
    )
    assert response2.status_code == 200, response2.text
    payload2 = response2.json()
    assert payload2["answer_type"] == "recommendation", payload2
    assert payload2["answer_type"] != "knowledge_base_answer"
    assert payload2["answer_type"] != "clarification"
    assert payload2["result_skus"], payload2
    assert payload2["result_skus"][0] != first_top, (payload1, payload2)

    with Session() as db:
        top_categories = {
            product.sku: product.category
            for product in db.query(Product).filter(Product.sku.in_(payload2["result_skus"][:2])).all()
        }
    assert top_categories and all(category == "锅具" for category in top_categories.values()), top_categories

    response3 = client.post(
        "/api/customer-service/ask?debug=true",
        json={"question": followups[1], "conversation_id": conversation_id},
        headers=headers,
    )
    assert response3.status_code == 200, response3.text
    payload3 = response3.json()
    assert payload3["answer_type"] == "recommendation", payload3
    assert payload3["answer_type"] != "knowledge_base_answer"
    assert payload3["answer_type"] != "clarification"
    assert payload3["result_skus"], payload3
    assert payload3["result_skus"][0] not in {"CB253", "CB254", "AC-Z13", "CW-C84", "CW-K32"}, payload3["result_skus"]


def _structured_field_match(actual: str | None, expected: str) -> bool:
    actual_text = str(actual or "").strip().lower()
    expected_text = str(expected or "").strip().lower()
    if not actual_text or not expected_text:
        return False
    if expected_text in actual_text:
        return True
    compact_actual = re.sub(r"[\s,，。/\\|;；:：()（）\[\]{}\"'`]+", "", actual_text)
    compact_expected = re.sub(r"[\s,，。/\\|;；:：()（）\[\]{}\"'`]+", "", expected_text)
    if compact_expected and compact_expected in compact_actual:
        return True
    compact_expected = re.sub(r"(材质|工艺|处理|产品)$", "", compact_expected)
    if compact_expected and compact_expected in compact_actual:
        return True
    return False


def _assert_structured_result_rows_match_filters(
    Session,
    result_skus: list[str],
    *,
    category: str,
    body_material: str = "",
    heat_source: str = "",
    usage_scenarios: str = "",
) -> None:
    assert result_skus, result_skus
    with Session() as db:
        rows = (
            db.query(Product, ProductSpecs, ProductBusiness)
            .outerjoin(ProductSpecs, ProductSpecs.product_id == Product.id)
            .outerjoin(ProductBusiness, ProductBusiness.product_id == Product.id)
            .filter(Product.sku.in_(result_skus))
            .all()
        )
    by_sku = {product.sku: (product, specs, business) for product, specs, business in rows}
    assert set(result_skus).issubset(by_sku.keys()), {"result_skus": result_skus, "loaded": sorted(by_sku.keys())}
    for sku in result_skus:
        product, specs, business = by_sku[sku]
        assert product.category == category, {"sku": sku, "actual_category": product.category, "expected_category": category}
        if body_material:
            assert _structured_field_match(getattr(specs, "body_material", None), body_material), {
                "sku": sku,
                "field": "body_material",
                "actual": getattr(specs, "body_material", None),
                "expected": body_material,
            }
        if heat_source:
            assert _structured_field_match(getattr(specs, "heat_source", None), heat_source), {
                "sku": sku,
                "field": "heat_source",
                "actual": getattr(specs, "heat_source", None),
                "expected": heat_source,
            }
        if usage_scenarios:
            assert _structured_field_match(getattr(business, "usage_scenarios", None), usage_scenarios), {
                "sku": sku,
                "field": "usage_scenarios",
                "actual": getattr(business, "usage_scenarios", None),
                "expected": usage_scenarios,
            }


@pytest.mark.parametrize(
    ("question", "expected_category", "field_path", "expected_value", "expected_field"),
    [
        ("哪些水具是不锈钢？", "水具", "specs.body_material", "不锈钢", "材质"),
        ("哪些锅具是硬质氧化铝？", "锅具", "specs.body_material", "硬质氧化铝", "材质"),
        ("哪些锅能用燃气炉？", "锅具", "specs.heat_source", "燃气炉", "热源"),
    ],
)
def test_structured_field_query_parser_additional_category_field_value_cases(
    question,
    expected_category,
    field_path,
    expected_value,
    expected_field,
):
    intent = customer_agent_intent_service.parse_intent(question)

    assert intent is not None, question
    assert intent.intent == "query_products", question
    assert intent.filters.get("product.category") == expected_category, (question, intent.filters)
    assert intent.filters.get(field_path) == expected_value, (question, intent.filters)
    assert intent.term == "", question
    assert expected_field in intent.requested_fields, (question, intent.requested_fields)


@pytest.mark.parametrize(
    ("question", "category", "body_material", "heat_source"),
    [
        ("哪些水具是不锈钢？", "水具", "不锈钢", ""),
        ("有哪些水具是不锈钢？", "水具", "不锈钢", ""),
        ("哪些锅具是铝合金？", "锅具", "铝合金", ""),
        ("有哪些锅具是铝合金？", "锅具", "铝合金", ""),
        ("哪些锅具是硬质氧化铝？", "锅具", "硬质氧化铝", ""),
        ("哪些锅能用燃气炉？", "锅具", "", "燃气炉"),
    ],
)
def test_route_level_structured_field_filter_results_are_pure_db_filtered_rows(
    route_client_and_db,
    question,
    category,
    body_material,
    heat_source,
):
    client, headers, Session = route_client_and_db

    response = client.post("/api/customer-service/ask?debug=true", json={"question": question}, headers=headers)
    assert response.status_code == 200, response.text
    payload = response.json()
    answer_metadata = payload.get("answer_metadata") or {}

    assert payload["answer_type"] in {"product_query", "query_products"}, payload
    assert answer_metadata.get("source") == "structured_category_field_filter_query", answer_metadata
    assert payload["result_skus"], payload
    _assert_structured_result_rows_match_filters(
        Session,
        payload["result_skus"],
        category=category,
        body_material=body_material,
        heat_source=heat_source,
    )


@pytest.mark.parametrize(
    "question",
    [
        "CW-C83 有什么优惠活动？",
        "CW-C83 有优惠吗？",
        "CW-C83 有没有优惠券？",
        "CW-C83 现在有活动吗？",
        "CW-C83 到手价是多少？",
        "CW-C83 库存还有多少？",
        "CW-C83 销量怎么样？",
        "CW-C83 好评率是多少？",
        "CW-C83 多久发货？",
        "CW-C83 有没有赠品？",
        "CW-C83 包邮吗？",
        "CW-C83 保修多久？",
        "CW-C83 售后怎么样？",
        "CW-C83 直播间有券吗？",
        "CW-C83 会员价是多少？",
        "CW-C83 能不能明天到？",
    ],
)
def test_route_level_explicit_sku_unknown_field_questions_fallback_conservatively(
    route_client_and_db,
    question,
):
    client, headers, _ = route_client_and_db

    response = client.post("/api/customer-service/ask?debug=true", json={"question": question}, headers=headers)
    assert response.status_code == 200, response.text
    payload = response.json()

    assert payload["answer"], payload
    assert payload["result_skus"], payload
    assert "CW-C83" in payload["result_skus"], payload["result_skus"]
    assert "Product not found" not in payload["answer"], payload["answer"]
    assert "没有找到匹配的产品资料" not in payload["answer"], payload["answer"]
    assert any(term in payload["answer"] for term in ("未标注", "无法确认", "请以平台或店铺页面为准", "联系人工客服")), payload["answer"]
    assert not any(term in payload["answer"] for term in ("现货充足", "直播间专享", "保证明天到", "立即发货", "已含赠品")), payload["answer"]


def test_route_level_nonexistent_explicit_sku_unknown_field_still_returns_product_not_found(route_client_and_db):
    client, headers, _ = route_client_and_db

    response = client.post("/api/customer-service/ask?debug=true", json={"question": "ZZZ-UNKNOWN-001 有优惠吗？"}, headers=headers)
    assert response.status_code in {200, 404}, response.text
    if response.status_code == 404:
        assert "Product not found" in response.text or "没有找到" in response.text, response.text
        return

    payload = response.json()
    assert "Product not found" in payload["answer"] or "没有找到" in payload["answer"], payload["answer"]


@pytest.mark.parametrize(
    ("question", "expected_answer_type", "required_sku", "required_terms"),
    [
        ("CW-C83 的价格是多少？", "product_detail", "CW-C83", ("未标注", "价格")),
        ("KW-K32-白可以直接加热吗？", "product_detail", "KW-K32-白", ("KW-K32-白",)),
        ("CT-T04(BM) 里面有什么？", "product_usage_care", "CT-T04(BM)", ("CT-T04(BM)",)),
        ("CW-C06PRO 怎么清洗？", "product_usage_care", None, ("清洗", "保养", "人工客服")),
    ],
)
def test_route_level_unknown_field_fallback_no_regression_product_cases(
    route_client_and_db,
    question,
    expected_answer_type,
    required_sku,
    required_terms,
):
    client, headers, _ = route_client_and_db

    response = client.post("/api/customer-service/ask?debug=true", json={"question": question}, headers=headers)
    assert response.status_code == 200, response.text
    payload = response.json()

    assert payload["answer_type"] == expected_answer_type, payload
    assert payload["answer"], payload
    assert "Product not found" not in payload["answer"], payload["answer"]
    if required_sku:
        assert payload["result_skus"], payload
        assert required_sku in payload["result_skus"], payload["result_skus"]
    for term in required_terms:
        if term in payload["answer"]:
            break
    else:
        assert False, payload["answer"]


@pytest.mark.parametrize(
    ("question", "expected_domain", "forbidden_domains", "required_terms"),
    [
        ("炉具推荐", {"炉具"}, {"锅具", "水壶", "水具", "配件"}, ("炉具",)),
        ("夏天冷水补水水壶推荐", {"水壶", "水具", "水杯"}, {"锅具", "茶具", "炉具", "配件"}, ("水",)),
        ("适合酒精炉的锅具推荐", {"锅具"}, {"炉具", "水壶", "水具", "配件"}, ("酒精炉",)),
    ],
)
def test_route_level_unknown_field_fallback_no_regression_recommendation_cases(
    route_client_and_db,
    question,
    expected_domain,
    forbidden_domains,
    required_terms,
):
    client, headers, Session = route_client_and_db

    response = client.post("/api/customer-service/ask?debug=true", json={"question": question}, headers=headers)
    assert response.status_code == 200, response.text
    payload = response.json()

    assert payload["answer_type"] == "recommendation", payload
    assert payload["answer"], payload
    assert payload["result_skus"], payload
    assert "Product not found" not in payload["answer"], payload["answer"]
    for term in required_terms:
        assert term in payload["answer"], payload["answer"]

    with Session() as db:
        categories = {
            str(product.sku or "").strip().upper(): str(product.category or "").strip()
            for product in db.query(Product).filter(Product.sku.in_(payload["result_skus"])).all()
        }
    assert categories, payload
    assert any(category in expected_domain for category in categories.values()), categories
    assert not any(category in forbidden_domains for category in categories.values()), categories


@pytest.mark.parametrize(
    ("question", "expected_sku"),
    [
        ("\u0043\u0046\u002d\u0050\u0047\u0031\u0039 \u8fd9\u4e2a \u0053\u004b\u0055 \u73b0\u5728\u8fd8\u6709\u8d60\u54c1\u5417\uff1f", "CF-PG19"),
        ("\u0043\u0046\u002d\u0050\u0047\u0031\u0039 \u6709\u8d60\u54c1\u5417\uff1f", "CF-PG19"),
        ("\u0043\u0046\u002d\u0050\u0047\u0031\u0039 \u968f\u5355\u9001\u4e1c\u897f\u5417\uff1f", "CF-PG19"),
        ("\u0043\u0046\u002d\u0050\u0047\u0031\u0039 \u6709\u4f18\u60e0\u5238\u5417\uff1f", "CF-PG19"),
        ("\u0043\u0046\u002d\u0050\u0047\u0031\u0039 \u4eca\u5929\u80fd\u53d1\u5417\uff1f", "CF-PG19"),
        ("\u0043\u0046\u002d\u0050\u0047\u0031\u0039 \u8bc4\u4ef7\u600e\u4e48\u6837\uff1f", "CF-PG19"),
        ("\u0043\u0046\u002d\u0050\u0047\u0031\u0039 \u597d\u8bc4\u7387\u662f\u591a\u5c11\uff1f", "CF-PG19"),
        ("\u0043\u0046\u002d\u0050\u0047\u0031\u0039 \u4fdd\u4fee\u591a\u4e45\uff1f", "CF-PG19"),
        ("\u0043\u0046\u002d\u0050\u0047\u0031\u0039 \u5305\u90ae\u5417\uff1f", "CF-PG19"),
        ("\u0043\u0057\u002d\u0043\u0038\u0033 \u6709\u4ec0\u4e48\u4f18\u60e0\u6d3b\u52a8\uff1f", "CW-C83"),
        ("\u0043\u0057\u002d\u0043\u0038\u0033 \u6709\u6ca1\u6709\u8d60\u54c1\uff1f", "CW-C83"),
        ("\u0043\u0057\u002d\u0043\u0038\u0033 \u76f4\u64ad\u95f4\u6709\u5238\u5417\uff1f", "CW-C83"),
        ("\u0043\u0057\u002d\u0043\u0038\u0033 \u5e93\u5b58\u8fd8\u6709\u591a\u5c11\uff1f", "CW-C83"),
        ("\u0043\u0053\u002d\u0042\u0031\u0034\uff08\u004c\u0058\uff09 \u6709\u8d60\u54c1\u5417\uff1f", "CS-B14（LX）"),
        ("\u0043\u0053\u002d\u0042\u0031\u0034\uff08\u004c\u0058\uff09 \u4fdd\u4fee\u591a\u4e45\uff1f", "CS-B14（LX）"),
        ("\u0043\u0053\u002d\u0042\u0031\u0034\uff08\u004c\u0058\uff09 \u73b0\u5728\u6709\u6d3b\u52a8\u5417\uff1f", "CS-B14（LX）"),
    ],
)
def test_route_level_explicit_sku_unknown_realtime_questions_prefer_conservative_fallback(
    route_client_and_db,
    question,
    expected_sku,
):
    client, headers, _ = route_client_and_db

    response = client.post("/api/customer-service/ask?debug=true", json={"question": question}, headers=headers)
    assert response.status_code == 200, response.text
    payload = response.json()
    answer = str(payload.get("answer") or "")
    answer_metadata = payload.get("answer_metadata") or {}

    assert payload["result_skus"], payload
    assert expected_sku in payload["result_skus"], payload["result_skus"]
    assert answer, payload
    assert "Product not found" not in answer, answer
    assert not any(term in answer for term in ("\u73b0\u8d27\u5145\u8db3", "\u76f4\u64ad\u95f4\u4e13\u4eab", "\u4fdd\u8bc1\u660e\u5929\u5230", "\u7acb\u5373\u53d1\u8d27", "\u5df2\u542b\u8d60\u54c1")), answer
    assert any(term in answer for term in ("\u672a\u6807\u6ce8", "\u65e0\u6cd5\u786e\u8ba4", "\u8bf7\u4ee5\u5e73\u53f0\u6216\u5e97\u94fa\u9875\u9762\u4e3a\u51c6", "\u4eba\u5de5\u5ba2\u670d")), answer
    assert answer_metadata.get("source") == "resolved_entity_unknown_field_fallback", answer_metadata
    assert payload["answer_type"] == "product_detail", payload
    assert payload.get("debug", {}).get("agent_mode") == "resolved_entity_unknown_field_fallback", payload.get("debug")


@pytest.mark.parametrize(
    "question",
    [
        "\u74e6\u7247\u70e4\u76d8 \u6709\u8d60\u54c1\u5417\uff1f",
        "\u74e6\u7247\u70e4\u76d8 \u4fdd\u4fee\u591a\u4e45\uff1f",
        "\u74e6\u7247\u70e4\u76d8 \u4eca\u5929\u80fd\u53d1\u5417\uff1f",
    ],
)
def test_route_level_unique_product_name_unknown_field_uses_conservative_fallback(route_client_and_db, question):
    client, headers, _ = route_client_and_db

    response = client.post("/api/customer-service/ask?debug=true", json={"question": question}, headers=headers)
    assert response.status_code == 200, response.text
    payload = response.json()
    answer = str(payload.get("answer") or "")
    answer_metadata = payload.get("answer_metadata") or {}

    assert "CF-PG19" in (payload.get("result_skus") or []), payload.get("result_skus")
    assert "Product not found" not in answer, answer
    assert any(term in answer for term in ("\u672a\u6807\u6ce8", "\u65e0\u6cd5\u786e\u8ba4", "\u8bf7\u4ee5\u5e73\u53f0\u6216\u5e97\u94fa\u9875\u9762\u4e3a\u51c6")), answer
    assert answer_metadata.get("source") == "resolved_entity_unknown_field_fallback", answer_metadata


@pytest.mark.parametrize(
    "question",
    [
        "\u6fc0\u5ddd\u5355\u9505 \u6709\u8d60\u54c1\u5417\uff1f",
        "\u6fc0\u5ddd\u5355\u9505 \u6709\u6d3b\u52a8\u5417\uff1f",
    ],
)
def test_route_level_ambiguous_product_name_unknown_field_clarifies_instead_of_picking_one(route_client_and_db, question):
    client, headers, _ = route_client_and_db

    response = client.post("/api/customer-service/ask?debug=true", json={"question": question}, headers=headers)
    assert response.status_code == 200, response.text
    payload = response.json()
    answer = str(payload.get("answer") or "")
    answer_metadata = payload.get("answer_metadata") or {}

    assert payload["answer_type"] == "clarification", payload
    assert payload.get("needs_clarification") is True, payload
    assert set(payload.get("result_skus") or []) >= {"CW-S10-1", "CW-S10-A"}, payload.get("result_skus")
    assert any(term in answer for term in ("\u8bf7\u5148\u6307\u5b9a", "\u5177\u4f53\u6b3e\u5f0f", "\u591a\u4e2a\u76f8\u5173\u5546\u54c1")), answer
    assert answer_metadata.get("source") == "named_product_unknown_field_clarification", answer_metadata


@pytest.mark.parametrize(
    "question",
    [
        "ZZZ-UNKNOWN-001 \u6709\u8d60\u54c1\u5417\uff1f",
        "\u5b8c\u5168\u4e0d\u5b58\u5728\u7684\u4ea7\u54c1\u540d \u6709\u8d60\u54c1\u5417\uff1f",
    ],
)
def test_route_level_unknown_realtime_negative_cases_can_still_not_found(route_client_and_db, question):
    client, headers, _ = route_client_and_db

    response = client.post("/api/customer-service/ask?debug=true", json={"question": question}, headers=headers)
    assert response.status_code in {200, 404}, response.text
    if response.status_code == 404:
        assert "Product not found" in response.text or "\u6ca1\u6709\u627e\u5230" in response.text, response.text
        return
    payload = response.json()
    answer = str(payload.get("answer") or "")
    assert "Product not found" in answer or "\u6ca1\u6709\u627e\u5230" in answer, answer


@pytest.mark.parametrize(
    ("question", "expected_answer_type", "required_sku", "required_terms"),
    [
        ("\u0043\u0046\u002d\u0050\u0047\u0031\u0039 \u662f\u4ec0\u4e48\u6750\u8d28\uff1f", "product_detail", "CF-PG19", ("\u786c\u8d28\u6c27\u5316\u94dd\u5408\u91d1", "\u6750\u8d28")),
        ("\u0043\u0046\u002d\u0050\u0047\u0031\u0039 \u9002\u5408\u4ec0\u4e48\u573a\u666f\uff1f", "product_detail", "CF-PG19", ("\u9732\u8425\u70e7\u70e4", "\u8425\u5730\u65e9\u9910", "\u573a\u666f")),
        ("\u004b\u0057\u002d\u004b\u0033\u0032\u002d\u767d\u53ef\u4ee5\u76f4\u63a5\u52a0\u70ed\u5417\uff1f", "product_detail", "KW-K32-白", ("\u660e\u706b\u76f4\u70e7", "\u5361\u5f0f\u7089", "\u9002\u7528\u70ed\u6e90")),
        ("\u0043\u0054\u002d\u0054\u0030\u0034\u0028\u0042\u004d\u0029 \u91cc\u9762\u6709\u4ec0\u4e48\uff1f", "product_usage_care", "CT-T04(BM)", ("\u8336\u58f6", "\u8336\u676f", "\u5f00\u7bb1")),
        ("\u0043\u0057\u002d\u0043\u0030\u0036\u0050\u0052\u004f \u600e\u4e48\u6e05\u6d17\uff1f", "product_usage_care", None, ("\u6e05\u6d17", "\u8f6f\u5237", "\u6e29\u6c34")),
        ("\u0043\u0053\u002d\u0042\u0031\u0034\uff08\u004c\u0058\uff09\u4f7f\u7528\u9152\u7cbe\u6709\u4ec0\u4e48\u6ce8\u610f\u4e8b\u9879\uff1f", ("product_usage_care", "product_detail"), "CS-B14（LX）", ("\u6db2\u4f53\u9152\u7cbe", "\u901a\u98ce")),
    ],
)
def test_route_level_unknown_realtime_priority_no_regression_known_capabilities(
    route_client_and_db,
    question,
    expected_answer_type,
    required_sku,
    required_terms,
):
    client, headers, Session = route_client_and_db
    if question in {
        "\u0043\u0054\u002d\u0054\u0030\u0034\u0028\u0042\u004d\u0029 \u91cc\u9762\u6709\u4ec0\u4e48\uff1f",
        "\u0043\u0057\u002d\u0043\u0030\u0036\u0050\u0052\u004f \u600e\u4e48\u6e05\u6d17\uff1f",
        "\u0043\u0053\u002d\u0042\u0031\u0034\uff08\u004c\u0058\uff09\u4f7f\u7528\u9152\u7cbe\u6709\u4ec0\u4e48\u6ce8\u610f\u4e8b\u9879\uff1f",
    }:
        _seed_contents_grounding_evidence(Session)

    response = client.post("/api/customer-service/ask?debug=true", json={"question": question}, headers=headers)
    assert response.status_code == 200, response.text
    payload = response.json()
    answer = str(payload.get("answer") or "")
    answer_metadata = payload.get("answer_metadata") or {}

    if isinstance(expected_answer_type, tuple):
        assert payload["answer_type"] in expected_answer_type, payload
    else:
        assert payload["answer_type"] == expected_answer_type, payload
    if required_sku:
        assert required_sku in (payload.get("result_skus") or []), payload.get("result_skus")
    assert not (
        answer_metadata.get("source") == "resolved_entity_unknown_field_fallback"
        or payload.get("debug", {}).get("agent_mode") == "resolved_entity_unknown_field_fallback"
    ), payload
    assert "Product not found" not in answer, answer
    assert not any(term in answer for term in ("\u5f53\u524d\u8d44\u6599\u672a\u6807\u6ce8\u8be5\u5546\u54c1\u662f\u5426\u9644\u8d60", "\u65e0\u6cd5\u786e\u8ba4\u5b9e\u65f6")), answer
    assert any(term in answer for term in required_terms), answer


def _assert_conservative_contents_answer(payload: dict, expected_sku: str) -> None:
    answer = str(payload.get("answer") or "")
    assert payload["answer_type"] == "product_usage_care", payload
    assert answer, payload
    assert expected_sku in (payload.get("result_skus") or []), payload.get("result_skus")
    assert "Product not found" not in answer, answer
    assert any(
        term in answer
        for term in (
            "当前资料可确认包含",
            "锅、炒锅和煎锅",
            "当前资料暂未提供明确的套装包含或组成说明",
            "当前资料未标注套装包含内容",
            "无法确认具体清单",
            "建议联系人工客服确认",
        )
    ), answer


@pytest.mark.parametrize(
    "question",
    [
        "CW-C83 套装里带什么？",
        "CW-C83 包含哪些东西？",
        "CW-C83 里面有什么？",
        "CW-C83 套装包含什么？",
        "CW-C83 有哪些配件？",
        "CW-C83 开箱有什么？",
    ],
)
def test_route_level_cw_c83_contents_questions_do_not_not_found_and_use_contents_path(
    route_client_and_db,
    question,
):
    client, headers, Session = route_client_and_db
    _seed_contents_grounding_evidence(Session)

    response = client.post("/api/customer-service/ask?debug=true", json={"question": question}, headers=headers)
    assert response.status_code == 200, response.text
    payload = response.json()

    _assert_conservative_contents_answer(payload, "CW-C83")
    assert payload.get("debug", {}).get("agent_mode") == "product_usage_care_fast_path", payload.get("debug")
    assert payload["result_skus"][0] == "CW-C83", payload["result_skus"]
    assert "CW-C83-1" not in payload["result_skus"], payload["result_skus"]
    assert not any(term in payload["answer"] for term in ("支持酒精炉", "适用热源", "明火直烧")), payload["answer"]


@pytest.mark.parametrize(
    ("question", "required_terms"),
    [
        ("CW-C83 和 CW-C83-1 是什么关系？", ("套装", "单品", "CW-C83-1")),
        ("CW-C83-1 是什么？", ("炊墨炒锅", "CW-C83-1")),
        ("CW-C83-2 是什么？", ("炊墨煎锅", "CW-C83-2")),
        ("CW-C83 套装和单品有什么区别？", ("套装", "单品", "CW-C83-1")),
    ],
)
def test_route_level_cw_c83_parent_child_relation_questions_do_not_not_found(
    route_client_and_db,
    question,
    required_terms,
):
    client, headers, Session = route_client_and_db
    _seed_contents_grounding_evidence(Session)

    response = client.post("/api/customer-service/ask?debug=true", json={"question": question}, headers=headers)
    assert response.status_code == 200, response.text
    payload = response.json()
    answer = str(payload.get("answer") or "")

    assert answer, payload
    assert "Product not found" not in answer, answer
    for term in required_terms:
        assert term in answer, answer


@pytest.mark.parametrize(
    ("question", "expected_sku"),
    [
        ("CF-PG19 包含哪些东西？", "CF-PG19"),
        ("TW-422-蓝 包含哪些东西？", "TW-422-蓝"),
    ],
)
def test_route_level_other_existing_sku_contents_questions_use_grounding_or_conservative_fallback(
    route_client_and_db,
    question,
    expected_sku,
):
    client, headers, Session = route_client_and_db
    _seed_contents_grounding_evidence(Session)

    response = client.post("/api/customer-service/ask?debug=true", json={"question": question}, headers=headers)
    assert response.status_code == 200, response.text
    payload = response.json()
    answer = str(payload.get("answer") or "")

    assert payload["answer_type"] == "product_usage_care", payload
    assert expected_sku in (payload.get("result_skus") or []), payload.get("result_skus")
    assert "Product not found" not in answer, answer
    assert answer, payload


@pytest.mark.parametrize(
    "question",
    [
        "ZZZ-UNKNOWN-001 包含哪些东西？",
        "完全不存在的产品名 套装里带什么？",
    ],
)
def test_route_level_contents_negative_cases_can_still_not_found(route_client_and_db, question):
    client, headers, _ = route_client_and_db

    response = client.post("/api/customer-service/ask?debug=true", json={"question": question}, headers=headers)
    assert response.status_code in {200, 404}, response.text
    if response.status_code == 404:
        assert "Product not found" in response.text or "没有找到" in response.text, response.text
        return
    payload = response.json()
    answer = str(payload.get("answer") or "")
    assert "Product not found" in answer or "没有找到" in answer, answer
def _assert_not_generic_contents_dump(answer: str) -> None:
    assert answer
    forbidden_terms = (
        "\u5185\u5bb9\u4fe1\u606f",
        "SKU:",
        "\u4e2d\u6587\u6807\u9898",
        "\u82f1\u6587\u6807\u9898",
        "\u4e2d\u6587\u63cf\u8ff0",
        "\u82f1\u6587\u63cf\u8ff0",
        "\u89c4\u683c\u4fe1\u606f",
        "\u5356\u70b9",
    )
    assert not any(term in answer for term in forbidden_terms), answer


def test_compose_usage_care_composition_answer_rejects_generic_listing_chunks_and_falls_back():
    answer = customer_agent_intent_service._compose_usage_care_composition_answer(
        "CW-C83 \u5957\u88c5\u91cc\u5e26\u4ec0\u4e48\uff1f",
        [],
        [
            {
                "sku": "CW-C83",
                "content": (
                    "\u5185\u5bb9\u4fe1\u606f:\n"
                    "- \u4e2d\u6587\u6807\u9898: \u708a\u58a8\u5957\u9505\n"
                    "- \u82f1\u6587\u6807\u9898: camping cookware set\n"
                    "- \u4e2d\u6587\u63cf\u8ff0: \u8fd9\u6b3e\u5957\u9505\u91c7\u7528\u4f18\u8d28\u590d\u5408\u5e95\u8bbe\u8ba1\uff0c\u9002\u914d\u591a\u79cd\u70ed\u6e90\u3002"
                ),
            },
            {
                "sku": "CW-C83",
                "content": (
                    "SKU: CW-C83\n"
                    "\u4e2d\u6587\u540d: \u708a\u58a8\u5957\u9505\n"
                    "\u89c4\u683c\u4fe1\u606f:\n"
                    "- \u5bb9\u91cf: \u9505\uff1a3700ML\n"
                    "- \u6750\u8d28: \u786c\u8d28\u6c27\u5316\u94dd\u5408\u91d1"
                ),
            },
        ],
    )

    assert "\u5f53\u524d\u8d44\u6599" in answer, answer
    assert any(
        term in answer
        for term in (
            "\u5957\u88c5\u5305\u542b\u5185\u5bb9",
            "\u5f00\u7bb1\u6e05\u5355",
            "\u65e0\u6cd5\u786e\u8ba4\u5177\u4f53\u914d\u4ef6",
            "\u8bf7\u4ee5\u5e73\u53f0\u9875\u9762\u6216\u5e97\u94fa\u4e3a\u51c6",
            "\u5efa\u8bae\u8054\u7cfb\u4eba\u5de5\u5ba2\u670d\u786e\u8ba4",
        )
    ), answer
    _assert_not_generic_contents_dump(answer)


def test_compose_usage_care_composition_answer_accepts_explicit_composition_evidence():
    answer = customer_agent_intent_service._compose_usage_care_composition_answer(
        "CT-T04(BM) \u91cc\u9762\u6709\u4ec0\u4e48\uff1f",
        [
            {
                "sku": "CT-T04(BM)",
                "answer": (
                    "CT-T04(BM) \u4e3a\u4e00\u6574\u5957\u4fbf\u643a\u529f\u592b\u8336\u5177\uff0c"
                    "\u542b\u8336\u58f6\u3001\u8336\u676f\u7b49\u914d\u4ef6\uff0c\u5f00\u7bb1\u5373\u53ef\u6ce1\u8336\u3002"
                ),
            }
        ],
        [],
    )

    assert any(term in answer for term in ("\u8336\u58f6", "\u8336\u676f", "\u914d\u4ef6", "\u5f00\u7bb1")), answer
    assert "\u5185\u5bb9\u4fe1\u606f" not in answer, answer


def test_compose_usage_care_composition_answer_rejects_generic_detail_noise_that_mentions_open_box_usage():
    answer = customer_agent_intent_service._compose_usage_care_composition_answer(
        "CF-PG19 有哪些配件？",
        [],
        [
            {
                "sku": "CF-PG19",
                "content": (
                    "SKU: CF-PG19\n"
                    "中文名: 瓦片烤盘\n"
                    "规格信息:\n"
                    "- 材质: 铝合金\n"
                    "- 适用热源: 明火直烧、燃气炉、卡式炉、电磁炉\n"
                    "- 使用说明: 【使用步骤】1.开箱初洗：首次使用前，用温水和软布轻柔冲洗锅身，无需使用洗洁精。"
                ),
            }
        ],
    )

    assert "当前资料" in answer, answer
    assert "请以平台页面或店铺页面为准" in answer, answer
    _assert_not_generic_contents_dump(answer)


@pytest.mark.parametrize(
    "question",
    [
        "CW-C83 \u5957\u88c5\u91cc\u5e26\u4ec0\u4e48\uff1f",
        "CW-C83 \u5305\u542b\u54ea\u4e9b\u4e1c\u897f\uff1f",
        "CW-C83 \u91cc\u9762\u6709\u4ec0\u4e48\uff1f",
        "CW-C83 \u5957\u88c5\u5305\u542b\u4ec0\u4e48\uff1f",
        "CW-C83 \u6709\u54ea\u4e9b\u914d\u4ef6\uff1f",
        "CW-C83 \u5f00\u7bb1\u6709\u4ec0\u4e48\uff1f",
    ],
)
def test_route_level_cw_c83_contents_without_direct_composition_evidence_fallbacks_instead_of_dumping_listing(
    route_client_and_db,
    question,
):
    client, headers, _ = route_client_and_db

    response = client.post("/api/customer-service/ask?debug=true", json={"question": question}, headers=headers)
    assert response.status_code == 200, response.text
    payload = response.json()
    answer = str(payload.get("answer") or "")

    assert payload["answer_type"] == "product_usage_care", payload
    assert "CW-C83" in (payload.get("result_skus") or []), payload.get("result_skus")
    assert "Product not found" not in answer, answer
    assert answer, payload
    _assert_not_generic_contents_dump(answer)
    assert any(
        term in answer
        for term in (
            "\u5957\u88c5\u5305\u542b\u5185\u5bb9",
            "\u5f00\u7bb1\u6e05\u5355",
            "\u65e0\u6cd5\u786e\u8ba4\u5177\u4f53\u6e05\u5355",
            "\u65e0\u6cd5\u786e\u8ba4\u5177\u4f53\u914d\u4ef6",
            "\u8bf7\u4ee5\u5e73\u53f0\u9875\u9762\u6216\u5e97\u94fa\u4e3a\u51c6",
        )
    ), answer


def _assert_resolved_sku_accessories_contract(payload: dict, expected_sku: str) -> None:
    answer = str(payload.get("answer") or "")
    assert payload["answer_type"] == "product_usage_care", payload
    assert expected_sku in (payload.get("result_skus") or []), payload.get("result_skus")
    assert answer, payload
    assert "Product not found" not in answer, answer
    assert "当前匹配到【配件】类产品共有" not in answer, answer
    _assert_not_generic_contents_dump(answer)
    assert any(
        term in answer
        for term in (
            "当前资料未标注该商品的套装包含内容",
            "开箱清单",
            "无法确认具体清单",
            "无法确认具体配件",
            "请以平台页面或店铺页面为准",
            "含茶壶、茶杯等配件",
        )
    ), answer


@pytest.mark.parametrize(
    "question",
    [
        "CS-B14（LX） 有哪些配件？",
        "CS-B14（LX） 有什么配件？",
        "CS-B14（LX） 包含哪些东西？",
        "CS-B14（LX） 开箱有什么？",
    ],
)
def test_route_level_resolved_sku_accessories_questions_do_not_become_catalog_or_generic_detail_dump(
    route_client_and_db,
    question,
):
    client, headers, _ = route_client_and_db

    response = client.post("/api/customer-service/ask?debug=true", json={"question": question}, headers=headers)
    assert response.status_code == 200, response.text
    payload = response.json()

    _assert_resolved_sku_accessories_contract(payload, "CS-B14（LX）")


@pytest.mark.parametrize(
    ("question", "expected_sku", "grounded_terms"),
    [
        ("CW-C83 有哪些配件？", "CW-C83", ()),
        ("CW-C83 有什么配件？", "CW-C83", ()),
        ("CT-T04(BM) 有哪些配件？", "CT-T04(BM)", ("茶壶", "茶杯", "配件")),
        ("CT-T04(BM) 有什么配件？", "CT-T04(BM)", ("茶壶", "茶杯", "配件")),
        ("CF-PG19 有哪些配件？", "CF-PG19", ()),
        ("CF-PG19 有什么配件？", "CF-PG19", ()),
    ],
)
def test_route_level_other_resolved_sku_accessories_questions_stay_bound_to_entity(
    route_client_and_db,
    question,
    expected_sku,
    grounded_terms,
):
    client, headers, Session = route_client_and_db
    if expected_sku == "CT-T04(BM)":
        _seed_contents_grounding_evidence(Session)
    if expected_sku == "CF-PG19":
        _seed_cf_pg19_generic_detail_noise(Session)

    response = client.post("/api/customer-service/ask?debug=true", json={"question": question}, headers=headers)
    assert response.status_code == 200, response.text
    payload = response.json()
    answer = str(payload.get("answer") or "")

    assert expected_sku in (payload.get("result_skus") or []), payload.get("result_skus")
    assert payload["answer_type"] == "product_usage_care", payload
    assert "当前匹配到【配件】类产品共有" not in answer, answer
    assert "Product not found" not in answer, answer
    assert answer, payload
    if grounded_terms:
        _assert_not_generic_contents_dump(answer)
        for term in grounded_terms:
            assert term in answer, answer
    else:
        _assert_not_generic_contents_dump(answer)
        assert any(
            term in answer
            for term in (
                "当前资料未标注该商品的套装包含内容",
                "开箱清单",
                "无法确认具体清单",
                "无法确认具体配件",
                "请以平台页面或店铺页面为准",
            )
        ), answer


@pytest.mark.parametrize(
    "question",
    [
        "CS-B14（LX） 有哪些配件？",
        "CS-B14(LX) 有哪些配件？",
        "CT-T04(BM) 有哪些配件？",
    ],
)
def test_route_level_bracket_sku_accessories_questions_are_treated_as_entity_bound_contents(
    route_client_and_db,
    question,
):
    client, headers, _ = route_client_and_db

    response = client.post("/api/customer-service/ask?debug=true", json={"question": question}, headers=headers)
    assert response.status_code == 200, response.text
    payload = response.json()
    answer = str(payload.get("answer") or "")

    assert payload["answer_type"] != "query_products", payload
    assert "当前匹配到【配件】类产品共有" not in answer, answer


@pytest.mark.parametrize(
    "question",
    [
        "配件推荐",
        "有哪些配件推荐？",
        "露营配件推荐",
        "户外有什么配件？",
    ],
)
def test_route_level_generic_accessory_queries_still_work_without_resolved_entity(
    route_client_and_db,
    question,
):
    client, headers, _ = route_client_and_db

    response = client.post("/api/customer-service/ask?debug=true", json={"question": question}, headers=headers)
    assert response.status_code == 200, response.text
    payload = response.json()

    assert payload["answer_type"] in {"query_products", "recommendation"}, payload
    assert payload.get("result_skus"), payload


@pytest.mark.parametrize(
    ("question", "expected_sku", "grounded_terms"),
    [
        ("瓦片烤盘 有哪些配件？", "CF-PG19", ()),
        ("瓦片烤盘 包含哪些东西？", "CF-PG19", ()),
        ("出山-功夫茶具（竹套版） 有哪些配件？", "CT-T04(BM)", ("茶壶", "茶杯", "配件")),
        ("出山-功夫茶具（竹套版） 开箱有什么？", "CT-T04(BM)", ("开箱", "泡茶")),
    ],
)
def test_route_level_unique_product_name_contents_accessories_questions_follow_same_contract(
    route_client_and_db,
    question,
    expected_sku,
    grounded_terms,
):
    client, headers, Session = route_client_and_db
    if expected_sku == "CT-T04(BM)":
        _seed_contents_grounding_evidence(Session)
    if expected_sku == "CF-PG19":
        _seed_cf_pg19_generic_detail_noise(Session)

    response = client.post("/api/customer-service/ask?debug=true", json={"question": question}, headers=headers)
    assert response.status_code == 200, response.text
    payload = response.json()
    answer = str(payload.get("answer") or "")

    assert payload["answer_type"] == "product_usage_care", payload
    assert expected_sku in (payload.get("result_skus") or []), payload.get("result_skus")
    assert "Product not found" not in answer, answer
    assert "当前匹配到【配件】类产品共有" not in answer, answer
    assert answer, payload
    _assert_not_generic_contents_dump(answer)
    if grounded_terms:
        for term in grounded_terms:
            assert term in answer, answer
    else:
        grounded_contract_terms = ("包含", "配件", "组件", "清单", "开箱", "随附", "标配", "组成")
        fallback_terms = (
            "当前资料未标注该商品的套装包含内容",
            "开箱清单",
            "无法确认具体清单",
            "无法确认具体配件",
            "请以平台页面或店铺页面为准",
        )
        assert any(term in answer for term in grounded_contract_terms) or any(
            term in answer for term in fallback_terms
        ), answer


def _assert_contents_contract_answer(
    payload: dict,
    *,
    expected_sku: str | None = None,
    grounded_terms: tuple[str, ...] = (),
) -> None:
    answer = str(payload.get("answer") or "")
    assert answer, payload
    assert "Product not found" not in answer, answer
    assert payload["answer_type"] == "product_usage_care", payload
    assert "当前匹配到【配件】类产品共有" not in answer, answer
    _assert_not_generic_contents_dump(answer)
    if expected_sku:
        assert expected_sku in (payload.get("result_skus") or []), payload.get("result_skus")
    if grounded_terms:
        for term in grounded_terms:
            assert term in answer, answer
    else:
        grounded_contract_terms = ("包含", "配件", "组件", "清单", "开箱", "随附", "标配", "组成")
        fallback_terms = (
            "当前资料未标注该商品的套装包含内容",
            "开箱清单",
            "无法确认具体清单",
            "无法确认具体配件",
            "请以平台页面或店铺页面为准",
        )
        assert any(term in answer for term in grounded_contract_terms) or any(
            term in answer for term in fallback_terms
        ), answer


@pytest.mark.parametrize(
    ("question", "expected_sku", "grounded_terms"),
    [
        ("CF-PG19 标配有什么？", "CF-PG19", ()),
        ("CS-B14（LX） 随附什么？", "CS-B14（LX）", ()),
        ("CW-C83 附带什么？", "CW-C83", ()),
        ("CF-PG19 包装清单是什么？", "CF-PG19", ()),
        ("CW-C83 package includes?", "CW-C83", ()),
        ("CS-B14（LX） what's included?", "CS-B14（LX）", ()),
        ("CS-B14（LX） standard accessories?", "CS-B14（LX）", ()),
        ("CT-T04(BM) 标配有什么？", "CT-T04(BM)", ("茶壶", "茶杯", "配件")),
        ("CT-T04(BM) what is included?", "CT-T04(BM)", ("茶壶", "茶杯", "配件")),
    ],
)
def test_route_level_contents_phrasing_family_resolved_sku_contract(
    route_client_and_db,
    question,
    expected_sku,
    grounded_terms,
):
    client, headers, Session = route_client_and_db
    _seed_contents_grounding_evidence(Session)
    if expected_sku == "CF-PG19":
        _seed_cf_pg19_generic_detail_noise(Session)

    response = client.post("/api/customer-service/ask?debug=true", json={"question": question}, headers=headers)
    assert response.status_code == 200, response.text
    payload = response.json()

    _assert_contents_contract_answer(
        payload,
        expected_sku=expected_sku,
        grounded_terms=grounded_terms,
    )


@pytest.mark.parametrize(
    ("question", "expected_sku", "grounded_terms"),
    [
        ("瓦片烤盘 标配有什么？", "CF-PG19", ()),
        ("炊墨套锅 包装清单是什么？", "CW-C83", ()),
        ("出山-功夫茶具（竹套版） 随附什么？", "CT-T04(BM)", ("茶壶", "茶杯", "配件")),
    ],
)
def test_route_level_contents_phrasing_family_unique_product_name_follows_same_contract(
    route_client_and_db,
    question,
    expected_sku,
    grounded_terms,
):
    client, headers, Session = route_client_and_db
    _seed_contents_grounding_evidence(Session)
    if expected_sku == "CF-PG19":
        _seed_cf_pg19_generic_detail_noise(Session)

    response = client.post("/api/customer-service/ask?debug=true", json={"question": question}, headers=headers)
    assert response.status_code == 200, response.text
    payload = response.json()

    _assert_contents_contract_answer(
        payload,
        expected_sku=expected_sku,
        grounded_terms=grounded_terms,
    )


@pytest.mark.parametrize(
    "question",
    [
        "天鹅壶 标配有什么？",
        "天鹅壶 包装清单是什么？",
        "天鹅壶 standard accessories?",
    ],
)
def test_route_level_contents_phrasing_family_ambiguous_product_name_clarifies(
    route_client_and_db,
    question,
):
    client, headers, _ = route_client_and_db

    response = client.post("/api/customer-service/ask?debug=true", json={"question": question}, headers=headers)
    assert response.status_code == 200, response.text
    payload = response.json()
    answer = str(payload.get("answer") or "")

    assert payload["answer_type"] == "clarification", payload
    assert payload.get("needs_clarification") is True, payload
    assert "Product not found" not in answer, answer
    assert "当前匹配到【配件】类产品共有" not in answer, answer
    assert any(term in answer for term in ("请先指定", "具体款式", "多个相关商品")), answer


@pytest.mark.parametrize(
    "question",
    [
        "CS-G25 包装里有什么？",
        "CS-G25 标配有什么？",
        "CS-G25 随附什么？",
        "CS-G25 附带什么？",
        "CS-G25 standard accessories?",
    ],
)
def test_route_level_contents_family_explicit_sku_prefers_exact_sku_over_variant(
    route_client_and_db,
    question,
):
    client, headers, Session = route_client_and_db
    _seed_contents_grounding_evidence(Session)
    _seed_contents_resolution_priority_products(Session)
    _seed_contents_variant_knowledge_noise(Session)

    response = client.post("/api/customer-service/ask?debug=true", json={"question": question}, headers=headers)
    assert response.status_code == 200, response.text
    payload = response.json()

    _assert_contents_contract_answer(payload, expected_sku="CS-G25")
    assert payload.get("result_skus") == ["CS-G25"], payload.get("result_skus")


@pytest.mark.parametrize(
    "question",
    [
        "CS-G25 包装里有什么？",
        "CS-G25 标配有什么？",
        "CS-G25 standard accessories?",
    ],
)
def test_route_level_contents_family_explicit_sku_keeps_exact_result_when_semantic_hit_is_variant(
    route_client_and_db,
    monkeypatch,
    question,
):
    client, headers, Session = route_client_and_db
    _seed_contents_grounding_evidence(Session)
    _seed_contents_resolution_priority_products(Session)

    async def fake_multi_query_semantic_retrieve(db, query, *, sku=None, limit=5, query_limit=5):
        if sku == "CS-G25":
            return [
                {
                    "sku": "CS-G25-B",
                    "source_type": "product",
                    "content": "Q: 小青炉Pro配收纳袋吗？\nA: 配有收纳袋（部分为网格收纳袋），用完收纳起来，背包整洁不凌乱。",
                    "metadata": {"sku": "CS-G25-B", "section": "qa:variant-noise-1", "title": "CS-G25-B QA 9"},
                    "score": 0.99,
                }
            ]
        return []

    monkeypatch.setattr(
        customer_agent_intent_service,
        "_multi_query_semantic_retrieve",
        fake_multi_query_semantic_retrieve,
    )

    response = client.post("/api/customer-service/ask?debug=true", json={"question": question}, headers=headers)
    assert response.status_code == 200, response.text
    payload = response.json()

    _assert_contents_contract_answer(payload, expected_sku="CS-G25")
    assert payload.get("result_skus") == ["CS-G25"], payload.get("result_skus")


@pytest.mark.parametrize(
    "question",
    [
        "CF-PG19PRO 标配有什么？",
        "CS-G25-B 标配有什么？",
    ],
)
def test_route_level_contents_family_explicit_sku_prefers_exact_sku_for_other_variant_groups(
    route_client_and_db,
    question,
):
    client, headers, Session = route_client_and_db
    _seed_contents_grounding_evidence(Session)
    _seed_contents_resolution_priority_products(Session)

    expected_sku = question.split(" ", 1)[0]

    response = client.post("/api/customer-service/ask?debug=true", json={"question": question}, headers=headers)
    assert response.status_code == 200, response.text
    payload = response.json()

    _assert_contents_contract_answer(payload, expected_sku=expected_sku)
    assert payload.get("result_skus") == [expected_sku], payload.get("result_skus")


@pytest.mark.parametrize(
    "question",
    [
        "瓦片烤盘Pro 有哪些配件？",
        "瓦片烤盘Pro 包装里有什么？",
        "瓦片烤盘Pro 标配有什么？",
    ],
)
def test_route_level_contents_family_unique_name_prefers_strong_version_match(
    route_client_and_db,
    question,
):
    client, headers, Session = route_client_and_db
    _seed_contents_grounding_evidence(Session)
    _seed_contents_resolution_priority_products(Session)

    response = client.post("/api/customer-service/ask?debug=true", json={"question": question}, headers=headers)
    assert response.status_code == 200, response.text
    payload = response.json()

    assert payload["answer_type"] != "clarification", payload
    _assert_contents_contract_answer(payload, expected_sku="CF-PG19PRO")
    assert payload.get("result_skus") == ["CF-PG19PRO"], payload.get("result_skus")


@pytest.mark.parametrize(
    "question",
    [
        "围雪炉 有哪些配件？",
        "围雪炉 包装清单是什么？",
        "城市出逃 有哪些配件？",
        "城市出逃 包装清单是什么？",
        "瓦片烤盘 有哪些配件？",
        "瓦片烤盘 包装清单是什么？",
    ],
)
def test_route_level_contents_family_ambiguous_names_must_clarify(
    route_client_and_db,
    question,
):
    client, headers, Session = route_client_and_db
    _seed_contents_grounding_evidence(Session)
    _seed_cf_pg19_generic_detail_noise(Session)
    _seed_contents_resolution_priority_products(Session)

    response = client.post("/api/customer-service/ask?debug=true", json={"question": question}, headers=headers)
    assert response.status_code == 200, response.text
    payload = response.json()
    answer = str(payload.get("answer") or "")

    assert payload["answer_type"] == "clarification", payload
    assert payload.get("needs_clarification") is True, payload
    assert "Product not found" not in answer, answer
    assert payload.get("result_skus"), payload
    assert payload["answer_type"] not in {"query_products", "product_query"}, payload
    assert "当前匹配到【配件】类产品共有" not in answer, answer
    assert "当前资料未标注该商品的套装包含内容" not in answer, answer
    assert any(term in answer for term in ("请先指定", "具体款式", "多个相关商品")), answer


@pytest.mark.parametrize(
    "question",
    [
        "配件推荐",
        "有哪些配件推荐？",
        "露营配件推荐",
        "户外有什么配件？",
        "炉具配件推荐",
    ],
)
def test_route_level_contents_phrasing_family_generic_accessory_queries_still_work(
    route_client_and_db,
    question,
):
    client, headers, _ = route_client_and_db

    response = client.post("/api/customer-service/ask?debug=true", json={"question": question}, headers=headers)
    assert response.status_code == 200, response.text
    payload = response.json()

    assert payload["answer_type"] in {"query_products", "recommendation"}, payload
    assert payload.get("result_skus"), payload


@pytest.mark.parametrize(
    "question",
    [
        "婧川水壶 有哪些配件？",
        "婧川水壶 包装清单是什么？",
        "婧川水壶 随附什么？",
        "婧川水壶 package includes?",
        "婧川水壶 what is included?",
        "星河水壶 包装清单是什么？",
        "青川套锅 标配有什么？",
        "远山炉 随附什么？",
    ],
)
def test_route_level_unresolved_product_like_contents_questions_clarify_instead_of_generic_catalog_or_empty_kb(
    route_client_and_db,
    question,
):
    client, headers, Session = route_client_and_db
    _seed_contents_grounding_evidence(Session)
    _seed_contents_resolution_priority_products(Session)

    response = client.post("/api/customer-service/ask?debug=true", json={"question": question}, headers=headers)
    assert response.status_code == 200, response.text
    payload = response.json()
    answer = str(payload.get("answer") or "")

    assert payload["answer_type"] == "clarification", payload
    assert payload.get("needs_clarification") is True, payload
    assert payload.get("result_skus") in ([], None), payload.get("result_skus")
    assert payload["answer_type"] not in {"query_products", "product_query", "knowledge_base_answer"}, payload
    assert "Product not found" not in answer, answer
    assert "当前匹配到【配件】类产品共有" not in answer, answer
    assert any(term in answer for term in ("没能", "具体 SKU", "确认是哪一款", "确认具体商品", "请提供 SKU")), answer


@pytest.mark.parametrize(
    "question",
    [
        "户外有什么配件？",
        "配件推荐",
        "有哪些配件推荐？",
        "露营配件推荐",
        "水壶推荐",
        "有哪些水壶？",
        "户外水壶推荐",
    ],
)
def test_route_level_unresolved_product_like_guard_does_not_break_generic_queries(
    route_client_and_db,
    question,
):
    client, headers, _ = route_client_and_db

    response = client.post("/api/customer-service/ask?debug=true", json={"question": question}, headers=headers)
    assert response.status_code == 200, response.text
    payload = response.json()

    assert payload["answer_type"] in {"query_products", "recommendation"}, payload


@pytest.mark.parametrize(
    "question",
    [
        "CS-G25 标配有什么？",
        "CS-G25 standard accessories?",
        "CS-G25-B 包装里有什么？",
        "CF-PG19 标配有什么？",
        "瓦片烤盘Pro 标配有什么？",
        "围雪炉 包装清单是什么？",
        "天鹅壶 包装清单是什么？",
        "CW-C83 套装和单品有什么区别？",
        "CT-T04(BM) 里面有什么？",
        "CF-PG19 有赠品吗？",
        "炉具推荐",
        "哪些水具是不锈钢？",
    ],
)
def test_route_level_unresolved_product_like_guard_preserves_existing_families(
    route_client_and_db,
    question,
):
    client, headers, Session = route_client_and_db
    _seed_contents_grounding_evidence(Session)
    _seed_cf_pg19_generic_detail_noise(Session)
    _seed_contents_resolution_priority_products(Session)

    response = client.post("/api/customer-service/ask?debug=true", json={"question": question}, headers=headers)
    assert response.status_code == 200, response.text
    payload = response.json()
    answer = str(payload.get("answer") or "")

    assert answer, payload
    assert "Product not found" not in answer, answer
    if question in {"围雪炉 包装清单是什么？", "天鹅壶 包装清单是什么？"}:
        assert payload["answer_type"] == "clarification", payload
    elif question in {"炉具推荐", "哪些水具是不锈钢？"}:
        assert payload["answer_type"] in {"recommendation", "query_products", "product_query"}, payload
    elif question == "CF-PG19 有赠品吗？":
        assert payload["answer_type"] in {"product_detail", "product_usage_care"}, payload
    elif question == "CW-C83 套装和单品有什么区别？":
        assert payload["answer_type"] in {"comparison", "product_usage_care", "product_detail"}, payload
    else:
        assert payload["answer_type"] != "clarification", payload
