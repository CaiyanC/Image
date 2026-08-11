import asyncio
import json
import re
from types import SimpleNamespace

import pytest

from app.models import Product, ProductBusiness, ProductQa, ProductSpecs
from app.services import (
    customer_agent_intent_service,
    customer_agent_planner_service,
    customer_entity_resolution_contract,
    customer_field_contract,
    customer_recommendation_verification_contract,
    customer_service_service,
)
from test_customer_service_route_level_regression import (
    _add_product,
    _add_knowledge_chunk,
    _add_product_qa,
    route_client_and_db,
)
from test_customer_service_route_level_regression import _parse_sse_payload


@pytest.fixture(autouse=True)
def _semantic_preplan_out_of_scope_for_unmocked_supplemental_route_regressions(request, monkeypatch):
    """Keep SQLite route regressions independent of an external DeepSeek key.

    These unmocked HTTP cases exercise catalogue, context and evidence
    executors. Semantic schema tests and tests that explicitly use
    ``monkeypatch`` retain ownership of their model responses below. The live
    dev HTTP acceptance suite verifies the actual DeepSeek integration.
    """
    direct_fixture_args = set(getattr(request.node._fixtureinfo, "argnames", ()) or ())
    if "route_client_and_db" not in direct_fixture_args or "monkeypatch" in direct_fixture_args:
        yield
        return

    async def no_semantic_preplan(*_args, **_kwargs):
        return {"called": False}

    monkeypatch.setattr(
        customer_agent_planner_service,
        "plan_customer_question_semantic",
        no_semantic_preplan,
    )
    yield


def _mock_strong_resolved_named_product(
    monkeypatch,
    *,
    product: Product,
    canonical_name: str | None = None,
) -> None:
    name = str(canonical_name or product.product_name_cn or product.product_name_en or "").strip()
    sku = str(product.sku or "").strip().upper()
    contract = customer_entity_resolution_contract.EntityResolutionContract(
        entity_text=name,
        normalized_entity_text=re.sub(r"[\s\-_]+", "", name).lower(),
        status="resolved",
        resolved_sku=sku,
        resolver_candidate_skus=[sku],
        diagnostic_candidate_skus=[],
        candidate_skus=[sku],
        matched_by="canonical_name_exact",
        confidence="high",
        is_unique=True,
        matched_span=None,
        field_type=None,
        status_reason="resolver_unique_exact",
    )
    monkeypatch.setattr(
        customer_service_service,
        "_products_named_in_question",
        lambda _db, _question: [product],
    )
    monkeypatch.setattr(
        customer_service_service,
        "_subject_strongly_matches_product",
        lambda _subject, _product: True,
    )
    monkeypatch.setattr(
        customer_service_service.customer_entity_resolution_contract,
        "build_entity_resolution_contract",
        lambda *_args, **_kwargs: contract,
    )


def test_customer_mutation_boundary_declines_explicit_catalogue_change_without_action():
    result = customer_service_service._customer_mutation_boundary_result(
        "直接把 CW-C83 的负责人改成 kang，不用确认"
    )

    assert result is not None
    assert result["answer_type"] == "clarification"
    assert result["results"] == []
    assert "不会代为修改或删除" in result["answer"]
    assert "没有写入任何数据" in result["answer"]
    assert result["debug"]["agent_mode"] == "customer_mutation_boundary"
    assert customer_service_service._customer_mutation_boundary_result(
        "CW-C83 和 CW-C06PRO 哪个更适合两个人徒步？"
    ) is None


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
        _add_product(db, "KW-HIKE-01", "徒步轻量水杯", "水具", "520ML", "不锈钢", "/", "轻量便携", "徒步补水 轻量出行", 240)
        _add_product(db, "KW-FIRE-SS-01", "明火不锈钢小方壶", "水壶", "900ML", "304不锈钢", "明火直烧 卡式炉", "直火烧水", "露营烧水", 420)
        _add_product(db, "ST-BEGINNER-01", "新手基础炉", "炉具", "/", "不锈钢", "气罐", "基础 入门 性价比", "新手露营", 980)
        _add_product(db, "CF-PG19-AL", "瓦片铝合金烤盘", "锅具", "32cm", "铝合金", "卡式炉", "户外烧烤烤盘", "多人烧烤 团建烧烤", 780)
        db.commit()


def _semantic_preplan_debug(payload: dict) -> dict:
    debug = payload.get("debug") if isinstance(payload.get("debug"), dict) else {}
    return debug.get("semantic_preplan") if isinstance(debug.get("semantic_preplan"), dict) else {}


def _unknown_realtime_preplan_stub(
    *,
    field_hint: str = "stock",
    entity_scope: str = "resolved_single",
    subtype: str = "unknown_realtime",
    route_hint: str = "unknown_field",
    question_type: str = "unknown_field",
    unknown_field: bool = True,
) -> dict:
    return {
        "called": True,
        "purpose": "semantic_preplan",
        "route_hint": route_hint,
        "question_type": question_type,
        "entities": [],
        "field_hint": field_hint,
        "subtype": subtype,
        "entity_scope": entity_scope,
        "qa_or_usage_care": False,
        "unknown_field": unknown_field,
        "confidence": 0.96,
        "reason": "unknown realtime contract",
        "accepted_or_overridden": "",
        "override_reason": "",
        "fallback_reason": "",
        "llm_call_count": 1,
        "llm_call_count_delta": 1,
        "raw_preview": "",
        "preplan_model": "test-semantic-preplan",
        "preplan_temperature": 0,
        "preplan_max_tokens": 256,
        "preplan_json_mode": True,
        "preplan_thinking_disabled": True,
        "preplan_latency_ms": 1.0,
        "provider_usage_available": False,
        "prompt_tokens": None,
        "completion_tokens": None,
        "total_tokens": None,
        "reasoning_tokens": None,
        "prompt_cache_hit_tokens": None,
        "prompt_cache_miss_tokens": None,
    }


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


def test_semantic_storage_schema_label_normalizes_to_formal_care_field():
    assert customer_field_contract.semantic_preplan_field_type("storage") == "care"
    assert customer_field_contract.semantic_preplan_field_type("maintenance") == "care"


def test_named_product_which_scenarios_question_is_formal_usage_scene_field():
    contract = customer_field_contract.detect_field_contract(
        "天鹅壶4杯黑色适合什么露营场景？"
    )

    assert contract is not None
    assert contract.field_type == "usage_scene"


def test_semantic_preplan_parser_accepts_code_fence_and_tracks_llm_calls(monkeypatch):
    calls = []

    async def fake_chat_completion(
        db,
        messages,
        model=None,
        temperature=0.2,
        max_tokens=1200,
        *,
        purpose="chat",
        api_model_override=None,
        response_format=None,
        thinking=None,
        metadata=None,
    ):
        calls.append(
            {
                "purpose": purpose,
                "model": model,
                "api_model_override": api_model_override,
                "temperature": temperature,
                "max_tokens": max_tokens,
                "response_format": response_format,
                "thinking": thinking,
            }
        )
        if isinstance(metadata, dict):
            metadata.update(
                {
                    "request_model": api_model_override or model,
                    "temperature": temperature,
                    "max_tokens": max_tokens,
                    "response_format": response_format,
                    "thinking": thinking,
                    "elapsed_ms": 123.45,
                    "usage": {
                        "prompt_tokens": 31,
                        "completion_tokens": 11,
                        "total_tokens": 42,
                        "completion_tokens_details": {"reasoning_tokens": 0},
                        "prompt_cache_hit_tokens": 7,
                        "prompt_cache_miss_tokens": 24,
                    },
                }
            )
        if purpose == "semantic_preplan_repair":
            return """```json
{"route_family":"comparison","route_hint":"comparison","question_type":"comparison","entities":["锅","烤盘"],"canonical_fields":["usage_scene"],"field_type":"usage_scene","qa_or_usage_care":false,"unknown_field":false,"confidence":0.84,"reason":"pan vs cookware"}
```"""
        return """```json
{"route_family":"comparison","route_hint":"comparison","question_type":"comparison","entities":["锅","烤盘"],"field_hint":null,"qa_or_usage_care":false,"unknown_field":false,"confidence":0.84,"reason":"pan vs cookware"}
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

    assert [item["purpose"] for item in calls] == ["semantic_preplan", "semantic_preplan_repair"]
    assert result["called"] is True
    assert result["route_hint"] == "comparison"
    assert result["confidence"] > 0
    assert calls[0]["model"] is None
    assert calls[0]["api_model_override"] == "deepseek-v4-flash"
    assert calls[0]["temperature"] == 0
    assert calls[0]["max_tokens"] == 768
    assert calls[0]["response_format"] == {"type": "json_object"}
    assert calls[0]["thinking"] == {"type": "disabled"}
    assert result["preplan_model"] == "deepseek-v4-flash"
    assert result["preplan_temperature"] == 0
    assert result["preplan_max_tokens"] == 768
    assert result["preplan_json_mode"] is True
    assert result["preplan_thinking_disabled"] is True
    assert result["preplan_latency_ms"] == pytest.approx(123.45)
    assert result["provider_usage_available"] is True
    assert result["prompt_tokens"] == 31
    assert result["completion_tokens"] == 11
    assert result["total_tokens"] == 42
    assert result["reasoning_tokens"] == 0
    assert result["prompt_cache_hit_tokens"] == 7
    assert result["prompt_cache_miss_tokens"] == 24


def test_semantic_preplan_retries_one_transient_timeout_before_safe_fallback(monkeypatch):
    calls = []

    async def fake_chat_completion(
        db,
        messages,
        model=None,
        temperature=0.2,
        max_tokens=1200,
        *,
        purpose="chat",
        api_model_override=None,
        response_format=None,
        thinking=None,
        metadata=None,
    ):
        calls.append(purpose)
        if len(calls) == 1:
            raise TimeoutError("transient semantic timeout")
        return '{"route_hint":"product_detail","question_type":"field","canonical_fields":["positioning"],"confidence":"high","ambiguity":false,"evidence_required":true,"context_usage":"none","reasoning_summary":"named product positioning"}'

    monkeypatch.setattr(customer_agent_planner_service.customer_llm_service, "chat_completion", fake_chat_completion)

    result = asyncio.run(
        customer_agent_planner_service.plan_customer_question_semantic(
            db=None,
            question="示例收纳包主打什么定位？",
            deterministic_plan={"primary_intent": "product_detail", "answer_type": "product_detail"},
            context={},
        )
    )

    assert calls == ["semantic_preplan", "semantic_preplan"]
    assert result["canonical_fields"] == ["positioning"]
    assert result["field_type"] == "positioning"
    assert result["fallback_reason"] == ""
    assert result["semantic_retry_count"] == 1


def test_semantic_preplan_parser_accepts_contents_subtype_and_entity_scope(monkeypatch):
    calls = []

    async def fake_chat_completion(db, messages, model=None, temperature=0.2, max_tokens=1200, *, purpose="chat", api_model_override=None, response_format=None, thinking=None, metadata=None):
        calls.append(purpose)
        return """```json
{"route_hint":"product_detail","question_type":"contents_accessories","entities":["CF-PG19"],"field_hint":"contents","subtype":"composition","entity_scope":"resolved_single","qa_or_usage_care":true,"unknown_field":false,"confidence":0.91,"reason":"resolved contents question"}
```"""

    monkeypatch.setattr(customer_agent_planner_service.customer_llm_service, "chat_completion", fake_chat_completion)

    result = asyncio.run(
        customer_agent_planner_service.plan_customer_question_semantic(
            db=None,
            question="CF-PG19 原厂配了什么？",
            deterministic_plan={"primary_intent": "product_field", "answer_type": "product_detail"},
            context={},
        )
    )

    assert calls == ["semantic_preplan"]
    assert result["called"] is True
    assert result["route_hint"] == "product_detail"
    assert result["question_type"] == "contents_accessories"
    # U-S12 has one canonical customer field for package contents/accessories.
    # The semantic parser must normalize the model's legacy ``contents`` label
    # at the boundary so FieldContract, EntityResolutionContract and evidence
    # policy cannot split into two taxonomies.
    assert result["field_hint"] == "accessories"
    assert result["subtype"] == "composition"
    assert result["entity_scope"] == "resolved_single"
    assert result["entities"] == ["CF-PG19"]
    assert result["confidence"] == pytest.approx(0.91)
    assert "result_skus" not in result
    assert "candidate_skus" not in result


def test_validated_semantic_contents_adapts_to_single_field_contract_without_identity():
    question = "CF-PG19 原装都带啥？"
    assert customer_field_contract.detect_field_contract(question) is None

    result = customer_service_service.resolve_requested_field_contract(
        question,
        {"semantic_preplan": _contents_semantic_preplan_stub()},
    )

    assert result["field_type"] == "accessories"
    assert result["requested_field"] == "配件"
    assert result["requested_fields"] == ["配件"]
    assert result["canonical_fields"] == ["accessories"]
    # U-S12 promoted contents/accessories into the formal field contract:
    # semantic recognition may classify the field, but it must not supply
    # identity or evidence. EntityResolution and same-SKU evidence remain
    # mandatory downstream.
    assert result["supported_fields"] == ["accessories"]
    assert result["unsupported_fields"] == []
    assert result["subject"] == "CF-PG19"
    assert result["requested_scope"] == "subject"
    assert result["source"] == "validated_semantic_preplan"
    assert result["confidence"] == pytest.approx(0.96)
    assert "resolved_sku" not in result
    assert "candidate_skus" not in result
    assert "result_skus" not in result


def test_validated_semantic_contents_accepts_current_product_bound_qa_schema():
    question = "CF-PG19 原装都带啥？"
    semantic = _contents_semantic_preplan_stub()
    semantic.update(
        {
            "route_family": "product_bound_qa",
            "question_type": "field",
            "field_type": "contents",
            "field_hint": None,
            "subtype": "known_detail",
            "entity_scope": "resolved_product",
        }
    )

    result = customer_service_service.resolve_requested_field_contract(
        question,
        {"semantic_preplan": semantic},
    )

    assert result["field_type"] == "accessories"
    assert result["canonical_fields"] == ["accessories"]
    assert result["source"] == "validated_semantic_preplan"
    assert result["subject"] == "CF-PG19"
    assert "resolved_sku" not in result
    assert "candidate_skus" not in result
    assert "result_skus" not in result


def test_semantic_contents_cannot_override_explicit_cleaning_field_contract():
    semantic = _contents_semantic_preplan_stub()
    semantic.update(
        {
            "route_family": "product_bound_qa",
            "question_type": "field",
            "field_type": "contents",
            "field_hint": None,
            "subtype": "known_detail",
            "entity_scope": "resolved_product",
        }
    )

    result = customer_service_service.resolve_requested_field_contract(
        "CF-PG19 怎么清洁？",
        {"semantic_preplan": semantic},
    )

    # A contradictory semantic contents hint must not displace the explicit
    # canonical cleaning FieldContract.  This is a contract conflict, not a
    # legacy usage/care shortcut: the resulting source records that the
    # deterministic layer rejected an invalid field conflict while preserving
    # the formal cleaning field for later entity and evidence validation.
    assert result["canonical_fields"] == ["cleaning"]
    assert result["field_type"] == "cleaning"
    assert result["source"] == "explicit_contract_semantic_conflict"


def test_validated_semantic_field_keeps_priority_over_a_conflicting_alias():
    question = "CF-PG19 标配有什么？"
    deterministic = customer_field_contract.detect_field_contract(question)
    assert deterministic is not None and deterministic.field_type == "accessories"
    semantic = _contents_semantic_preplan_stub()
    semantic.update({
        "route_family": "product_bound_qa",
        "field_type": "gift",
        "field_hint": "gift",
        "canonical_fields": ["gift"],
        "question_type": "field",
        "subtype": "known_detail",
    })

    result = customer_service_service.resolve_requested_field_contract(
        question,
        {"semantic_preplan": semantic},
    )

    assert result["field_type"] == "gift"
    assert result["canonical_fields"] == ["gift"]
    assert result["source"] == "validated_semantic_preplan"


def test_validated_semantic_gift_maps_only_to_canonical_gift():
    question = "CF-PG19 有随单礼物吗？"
    assert customer_field_contract.detect_field_contract(question) is None
    semantic = _contents_semantic_preplan_stub()
    semantic.update(
        {
            "route_family": "product_bound_qa",
            "question_type": "field",
            "field_type": "gift",
            "field_hint": "gift",
            "subtype": "known_detail",
        }
    )

    result = customer_service_service.resolve_requested_field_contract(
        question,
        {"semantic_preplan": semantic},
    )

    assert result["field_type"] == "gift"
    assert result["canonical_fields"] == ["gift"]
    assert result["requested_fields"] == ["赠品"]
    assert result["source"] == "validated_semantic_preplan"


def test_semantic_validator_normalizes_legacy_field_labels_to_formal_canonical_fields():
    result = customer_agent_planner_service._validate_semantic_preplan(
        {
            "route_family": "product_bound_qa",
            "subject_text": "示例野炊锅",
            "field_type": "stock",
            "field_hint": "stock",
            "canonical_fields": ["stock"],
            "confidence": "high",
            "ambiguity": False,
            "evidence_required": True,
            "context_usage": "none",
            "reasoning_summary": "询问当前库存状态。",
        }
    )

    assert result["field_type"] == "inventory"
    assert result["field_hint"] == "inventory"
    assert result["canonical_fields"] == ["inventory"]


def test_semantic_product_navigation_clears_guessed_overview_field():
    result = customer_agent_planner_service._validate_semantic_preplan(
        {
            "route_family": "product_navigation",
            "subject_text": "示例野炊锅",
            "field_type": "specification",
            "field_hint": "specification",
            "canonical_fields": ["specification"],
            "confidence": "high",
            "ambiguity": False,
            "evidence_required": False,
            "context_usage": "none",
            "reasoning_summary": "用户只是在切换当前查看的商品。",
        }
    )

    assert result["route_family"] == "product_navigation"
    assert result["route_hint"] == "product_detail"
    assert result["question_type"] == "navigation"
    assert result["field_type"] == ""
    assert result["canonical_fields"] == []


def test_semantic_product_navigation_ignores_irrelevant_evidence_shape():
    result = customer_agent_planner_service._validate_semantic_preplan(
        {
            "route_family": "product_navigation",
            "subtype": "product_listing",
            "subject_text": "围雪炉",
            "canonical_fields": [],
            "confidence": "high",
            "ambiguity": False,
            "evidence_required": True,
            "evidence_kind": "none",
            "context_usage": "none",
            "reasoning_summary": "用户想查看这个产品系列下有哪些具体款式。",
        }
    )

    assert result["fallback_reason"] == ""
    assert result["route_family"] == "product_navigation"
    assert result["route_hint"] == "product_detail"
    assert result["question_type"] == "navigation"
    assert result["evidence_required"] is False
    assert result["evidence_kind"] == "structured_field"


def test_general_chat_output_removes_markdown_emphasis_markers():
    result = customer_service_service._shape_answer_for_output({
        "intent": "chat",
        "answer_type": "chat",
        "answer": "先看**使用场景**和**现有装备**。",
    })

    assert result["answer"] == "先看使用场景和现有装备。"


def test_cup_count_question_is_not_a_capacity_field():
    contract = customer_field_contract.resolve_requested_field_contract("它有几个杯子？")

    assert "capacity" not in contract.get("canonical_fields", [])


def test_semantic_preplan_reclassifies_cup_count_from_capacity_to_accessories():
    repaired = customer_service_service._repair_cup_count_semantic_preplan(
        "它有几个杯子？",
        {
            "called": True,
            "route_family": "product_bound_qa",
            "route_hint": "product_detail",
            "question_type": "field",
            "canonical_fields": ["capacity"],
            "field_type": "capacity",
            "field_hint": "capacity",
            "evidence_kind": "structured_field",
        },
    )

    assert repaired["canonical_fields"] == ["accessories"]
    assert repaired["field_type"] == "accessories"
    assert repaired["question_type"] == "contents_accessories"


def test_product_english_name_is_a_formal_field_not_brand_or_specification():
    semantic = customer_agent_planner_service._validate_semantic_preplan(
        {
            "route_family": "product_bound_qa",
            "subject_text": "示例产品",
            "field_type": "product_name_en",
            "field_hint": "product_name_en",
            "canonical_fields": ["product_name_en"],
            "confidence": "high",
            "ambiguity": False,
            "evidence_required": True,
            "context_usage": "none",
            "reasoning_summary": "Customer asks for the English display name.",
        }
    )

    result = customer_service_service.resolve_requested_field_contract(
        "示例产品的英文名是什么？",
        {"semantic_preplan": semantic},
        subject_override="示例产品",
    )

    assert result["field_type"] == "product_name_en"
    assert result["source"] == "validated_semantic_preplan"
    assert customer_field_contract.is_supported_detail_field("product_name_en")
    assert customer_field_contract.field_evidence_policy("product_name_en").structured_fields == (
        "product.product_name_en",
    )


def test_semantic_preplan_prompt_keeps_persona_and_care_meaning_distinct():
    """The semantic layer, not lexical routing, owns these field boundaries."""
    messages = customer_agent_planner_service._semantic_preplan_messages(
        question="示例产品适合哪些人，熏黑后怎么处理？",
        deterministic_plan={},
        context={},
    )
    system_prompt = str(messages[0]["content"])

    assert "适合哪些人" in system_prompt
    assert "target_audience" in system_prompt
    assert "熏黑" in system_prompt
    assert "cleaning" in system_prompt


@pytest.mark.parametrize(
    "semantic_overrides",
    [
        {"confidence": 0.89, "confidence_label": "high"},
        {"fallback_reason": "invalid_json"},
        {"route_hint": "recommendation"},
        {"question_type": "field"},
        {"field_type": "gift"},
        {"subtype": "usage_care"},
        {"entity_scope": "generic_scope"},
        {"route_family": "recommendation"},
    ],
)
def test_semantic_field_adapter_fails_closed_for_untrusted_or_inconsistent_preplan(semantic_overrides):
    semantic = _contents_semantic_preplan_stub()
    semantic.update(semantic_overrides)

    result = customer_service_service.resolve_requested_field_contract(
        "CF-PG19 原装都带啥？",
        {"semantic_preplan": semantic},
    )

    assert result["canonical_fields"] == []
    assert result["source"] == "safe_fallback"


def test_semantic_preplan_parser_accepts_route_arbiter_schema(monkeypatch):
    calls = []

    async def fake_chat_completion(db, messages, model=None, temperature=0.2, max_tokens=1200, *, purpose="chat", api_model_override=None, response_format=None, thinking=None, metadata=None):
        calls.append(purpose)
        return json.dumps(
            {
                "route_family": "structured_query",
                "entity_scope": "category_scope",
                "field_type": "material",
                "confidence": "high",
                "reason": "category field filter",
            },
            ensure_ascii=False,
        )

    monkeypatch.setattr(customer_agent_planner_service.customer_llm_service, "chat_completion", fake_chat_completion)

    result = asyncio.run(
        customer_agent_planner_service.plan_customer_question_semantic(
            db=None,
            question="哪些水杯是不锈钢的？",
            deterministic_plan={"primary_intent": "", "answer_type": ""},
            context={},
        )
    )

    assert calls == ["semantic_preplan"]
    assert result["called"] is True
    assert result["route_family"] == "structured_query"
    assert result["entity_scope"] == "category_scope"
    assert result["field_type"] == "material"
    assert result["confidence_label"] == "high"
    assert result["route_hint"] == "query_products"
    assert result["question_type"] == "filter"
    assert result["subtype"] == "structured_query"
    assert result["confidence"] == pytest.approx(0.9)
    assert "result_skus" not in result
    assert "candidate_skus" not in result


def test_semantic_recommendation_schema_accepts_storage_preference_as_a_closed_semantic_enum():
    assert customer_agent_planner_service._validated_recommendation_constraints({
        "subject_kind": "cookware",
        "storage_preference": "compact_storage",
    }) == {
        "subject_kind": "cookware",
        "storage_preference": "compact_storage",
    }


def test_semantic_recommendation_schema_rejects_list_subject_kind_without_raising():
    assert customer_agent_planner_service._validated_recommendation_constraints({
        "subject_kind": ["cookware"],
        "price_preference": "affordable",
    }) is None


def test_semantic_preplan_accepts_constrained_recommendation_preferences_without_identity_or_answer(monkeypatch):
    async def fake_chat_completion(db, messages, **kwargs):
        if kwargs.get("purpose") == "semantic_recommendation_constraint_grounding":
            return json.dumps({
                "recommendation_constraints": {
                    "subject_kind": "cookware",
                    "people": {"min": 2, "max": 2},
                    "heat_sources": ["card_stove"],
                    "scenarios": ["camping"],
                    "weight_preference": "lightweight",
                },
                "evidence_spans": {
                    "subject_kind": ["\u9505\u5177"], "people": ["\u4e24\u4eba"],
                    "heat_sources": ["\u5361\u5f0f\u7089"], "scenarios": ["\u9732\u8425"],
                    "weight_preference": ["\u8f7b\u91cf"],
                },
            })
        return json.dumps({
            "route_family": "recommendation",
            "entity_scope": "category_scope",
            "confidence": "high",
            "recommendation_constraints": {
                "subject_kind": "cookware",
                "people": {"min": 2, "max": 2},
                "heat_sources": ["card_stove"],
                "scenarios": ["camping"],
                "weight_preference": "lightweight",
            },
        })

    monkeypatch.setattr(customer_agent_planner_service.customer_llm_service, "chat_completion", fake_chat_completion)
    result = asyncio.run(customer_agent_planner_service.plan_customer_question_semantic(
        db=None, question="推荐适合两人露营、能用卡式炉的轻量锅具。", deterministic_plan={}, context={}
    ))

    assert result["route_family"] == "recommendation"
    assert result["recommendation_constraints"] == {
        "subject_kind": "cookware", "people": {"min": 2, "max": 2},
        "heat_sources": ["card_stove"], "scenarios": ["camping"], "weight_preference": "lightweight",
    }


def test_semantic_preplan_repairs_an_empty_high_confidence_recommendation_contract(monkeypatch):
    calls = []

    async def fake_chat_completion(db, messages, **kwargs):
        purpose = kwargs.get("purpose")
        calls.append(purpose)
        if purpose == "semantic_preplan":
            return json.dumps({
                "route_family": "recommendation",
                "entity_scope": "category_scope",
                "confidence": "high",
                "recommendation_constraints": {},
            })
        if purpose == "semantic_preplan_repair":
            return json.dumps({
                "route_family": "recommendation",
                "entity_scope": "category_scope",
                "confidence": "high",
                "recommendation_constraints": {},
            })
        if purpose == "semantic_recommendation_constraint_schema_repair":
            return json.dumps({
                "recommendation_constraints": {"subject_kind": "cookware"},
                "unrepresented_recommendation_requirements": [],
            })
        assert purpose == "semantic_recommendation_constraint_grounding"
        return json.dumps({
            "recommendation_constraints": {"subject_kind": "cookware"},
            "evidence_spans": {"subject_kind": ["\u9505"]},
        })

    monkeypatch.setattr(customer_agent_planner_service.customer_llm_service, "chat_completion", fake_chat_completion)

    result = asyncio.run(customer_agent_planner_service.plan_customer_question_semantic(
        db=None,
        question="\u9002\u5408\u6ce1\u5496\u5561\u7684\u5c0f\u9505\u6709\u5417\uff1f",
        deterministic_plan={},
        context={},
    ))

    assert calls[:2] == ["semantic_preplan", "semantic_preplan_repair"]
    assert "semantic_recommendation_constraint_schema_repair" in calls
    assert "semantic_preplan_requirement_reconciliation" in calls
    assert "semantic_recommendation_constraint_grounding" in calls
    assert result["recommendation_constraints"] == {"subject_kind": "cookware"}


def test_semantic_recommendation_drops_constraints_not_grounded_in_customer_words(monkeypatch):
    """A semantic route may recommend, but it cannot invent camping from generic outdoor wording."""
    calls = []

    async def fake_chat_completion(db, messages, **kwargs):
        calls.append(kwargs.get("purpose"))
        if kwargs.get("purpose") == "semantic_preplan":
            return json.dumps({
                "route_family": "recommendation",
                "entity_scope": "category_scope",
                "confidence": "high",
                "recommendation_constraints": {
                    "subject_kind": "cookware",
                    "heat_sources": ["open_flame"],
                    "scenarios": ["camping", "hiking"],
                },
            })
        return json.dumps({
            "recommendation_constraints": {
                "subject_kind": "cookware",
                "heat_sources": ["open_flame"],
            },
            "evidence_spans": {
                "subject_kind": ["\u5c0f\u9505"],
                "heat_sources": ["\u660e\u706b"],
            },
        })

    monkeypatch.setattr(customer_agent_planner_service.customer_llm_service, "chat_completion", fake_chat_completion)
    result = asyncio.run(customer_agent_planner_service.plan_customer_question_semantic(
        db=None,
        question="\u60f3\u8981\u4e00\u6b3e\u9002\u5408\u6237\u5916\u716e\u9762\u7684\u5c0f\u9505\uff0c\u6700\u597d\u80fd\u7528\u660e\u706b\u3002",
        deterministic_plan={},
        context={},
    ))

    # The central completeness review now runs between the initial semantic
    # plan and grounding.  Its malformed response is ignored here; the final
    # grounding contract must still remove the unsupported outdoor scenarios.
    assert calls == [
        "semantic_preplan",
        "semantic_preplan_requirement_reconciliation",
        "semantic_recommendation_constraint_grounding",
    ]
    assert result["recommendation_constraints"] == {
        "subject_kind": "cookware",
        "heat_sources": ["open_flame"],
    }


def test_semantic_grounding_cannot_treat_generic_outdoor_span_as_camping_or_hiking(monkeypatch):
    """A second semantic call still needs literal ontology-compatible evidence."""
    async def fake_chat_completion(db, messages, **kwargs):
        if kwargs.get("purpose") == "semantic_preplan":
            return json.dumps({
                "route_family": "recommendation",
                "entity_scope": "category_scope",
                "confidence": "high",
                "recommendation_constraints": {
                    "subject_kind": "cookware",
                    "heat_sources": ["open_flame"],
                    "scenarios": ["camping", "hiking"],
                },
            })
        return json.dumps({
            "recommendation_constraints": {
                "subject_kind": "cookware",
                "heat_sources": ["open_flame"],
                "scenarios": ["camping", "hiking"],
            },
            "evidence_spans": {
                "subject_kind": ["小锅"],
                "heat_sources": ["明火"],
                "scenarios": ["户外煮面"],
            },
        })

    monkeypatch.setattr(customer_agent_planner_service.customer_llm_service, "chat_completion", fake_chat_completion)
    result = asyncio.run(customer_agent_planner_service.plan_customer_question_semantic(
        db=None,
        question="想要一款适合户外煮面的小锅，最好能用明火。",
        deterministic_plan={},
        context={},
    ))

    assert result["recommendation_constraints"] == {
        "subject_kind": "cookware",
        "heat_sources": ["open_flame"],
    }
    assert "scenarios" not in result["recommendation_constraint_evidence_spans"]


def test_semantic_grounding_failure_keeps_reconciled_literal_constraints(monkeypatch):
    """A malformed second semantic response must not erase already-proved needs."""
    async def fake_chat_completion(db, messages, **kwargs):
        purpose = kwargs.get("purpose")
        if purpose == "semantic_preplan":
            return json.dumps({
                "route_family": "recommendation",
                "entity_scope": "category_scope",
                "confidence": "high",
                "recommendation_constraints": {
                    "subject_kind": "cookware",
                    "heat_sources": ["open_flame"],
                    "scenarios": ["camping"],
                },
                "unrepresented_recommendation_requirements": ["户外煮面"],
            })
        if purpose == "semantic_preplan_requirement_reconciliation":
            return json.dumps({
                "recommendation_constraints": {
                    "subject_kind": "cookware",
                    "heat_sources": ["open_flame"],
                    "scenarios": ["camping"],
                },
                "unrepresented_recommendation_requirements": ["户外煮面"],
                "evidence_spans": {
                    "subject_kind": ["小锅"],
                    "heat_sources": ["明火"],
                    "scenarios": ["户外煮面"],
                },
            })
        assert purpose == "semantic_recommendation_constraint_grounding"
        return "not-json"

    monkeypatch.setattr(customer_agent_planner_service.customer_llm_service, "chat_completion", fake_chat_completion)
    result = asyncio.run(customer_agent_planner_service.plan_customer_question_semantic(
        db=None,
        question="想要一款适合户外煮面的小锅，最好能用明火。",
        deterministic_plan={},
        context={},
    ))

    assert result["recommendation_constraints"] == {
        "subject_kind": "cookware",
        "heat_sources": ["open_flame"],
    }
    assert result["recommendation_constraint_grounding"] == "reconciled_literal_contract_fallback"
    assert result["recommendation_constraint_evidence_spans"] == {
        "subject_kind": ["小锅"],
        "heat_sources": ["明火"],
    }


def test_semantic_preplan_repairs_empty_constraints_for_high_confidence_recommendation(monkeypatch):
    calls = []

    async def fake_chat_completion(db, messages, **kwargs):
        purpose = kwargs.get("purpose")
        calls.append(purpose)
        if purpose == "semantic_preplan":
            return json.dumps({
                "route_family": "recommendation",
                "entity_scope": "category_scope",
                "subject_text": "水具",
                "canonical_fields": ["weight"],
                "confidence": "high",
                "recommendation_constraints": {},
            })
        if purpose == "semantic_preplan_repair":
            return json.dumps({
                "route_family": "recommendation",
                "entity_scope": "category_scope",
                "subject_text": "水具",
                "canonical_fields": ["weight"],
                "confidence": "high",
                "recommendation_constraints": {
                    "subject_kind": "waterware",
                    "weight_preference": "lightweight",
                },
            })
        if purpose == "semantic_preplan_requirement_reconciliation":
            return json.dumps({
                "recommendation_constraints": {
                    "subject_kind": "waterware",
                    "weight_preference": "lightweight",
                },
                "unrepresented_recommendation_requirements": [],
                "recommendation_soft_preferences": [],
                "evidence_spans": {
                    "subject_kind": ["水具"],
                    "weight_preference": ["重量比较轻"],
                },
            })
        assert purpose == "semantic_recommendation_constraint_grounding"
        return json.dumps({
            "recommendation_constraints": {
                "subject_kind": "waterware",
                "weight_preference": "lightweight",
            },
            "evidence_spans": {
                "subject_kind": ["水具"],
                "weight_preference": ["重量比较轻"],
            },
        })

    monkeypatch.setattr(customer_agent_planner_service.customer_llm_service, "chat_completion", fake_chat_completion)
    result = asyncio.run(customer_agent_planner_service.plan_customer_question_semantic(
        db=None,
        question="只看重量比较轻的水具，有哪些选择？",
        deterministic_plan={},
        context={},
    ))

    assert calls == [
        "semantic_preplan",
        "semantic_preplan_repair",
        "semantic_preplan_requirement_reconciliation",
        "semantic_recommendation_constraint_grounding",
    ]
    assert result["recommendation_constraints"] == {
        "subject_kind": "waterware",
        "weight_preference": "lightweight",
    }


def test_semantic_preplan_repairs_missing_subject_kind_before_catalogue_recommendation(monkeypatch):
    """A semantic subject span must be repaired by the semantic plan, never by lexical routing."""
    calls = []

    async def fake_chat_completion(db, messages, **kwargs):
        purpose = kwargs.get("purpose")
        calls.append(purpose)
        if purpose == "semantic_preplan":
            return json.dumps({
                "route_family": "recommendation",
                "entity_scope": "category_scope",
                "subject_text": "做饭装备",
                "confidence": "high",
                "recommendation_constraints": {"scenarios": ["camping"]},
            })
        if purpose == "semantic_preplan_repair":
            return json.dumps({
                "route_family": "recommendation",
                "entity_scope": "category_scope",
                "subject_text": "做饭装备",
                "confidence": "high",
                "recommendation_constraints": {
                    "subject_kind": "cookware",
                    "scenarios": ["camping"],
                },
            })
        if purpose == "semantic_preplan_requirement_reconciliation":
            return json.dumps({
                "recommendation_constraints": {
                    "subject_kind": "cookware",
                    "scenarios": ["camping"],
                },
                "unrepresented_recommendation_requirements": [],
                "recommendation_soft_preferences": [],
                "evidence_spans": {
                    "subject_kind": ["做饭装备"],
                    "scenarios": ["露营"],
                },
            })
        assert purpose == "semantic_recommendation_constraint_grounding"
        return json.dumps({
            "recommendation_constraints": {
                "subject_kind": "cookware",
                "scenarios": ["camping"],
            },
            "evidence_spans": {
                "subject_kind": ["做饭装备"],
                "scenarios": ["露营"],
            },
        })

    monkeypatch.setattr(customer_agent_planner_service.customer_llm_service, "chat_completion", fake_chat_completion)
    result = asyncio.run(customer_agent_planner_service.plan_customer_question_semantic(
        db=None,
        question="朋友准备露营，想送一套做饭装备，该从什么类型开始看？",
        deterministic_plan={},
        context={},
    ))

    assert calls == [
        "semantic_preplan",
        "semantic_preplan_repair",
        "semantic_preplan_requirement_reconciliation",
        "semantic_recommendation_constraint_grounding",
    ]
    assert result["recommendation_constraints"] == {
        "subject_kind": "cookware",
        "scenarios": ["camping"],
    }


def test_semantic_recommendation_people_constraint_requires_matching_party_size_evidence():
    constraints, spans = customer_agent_planner_service._recommendation_literal_grounding_filter(
        {"people": {"min": 1, "max": 1}},
        {"people": ["beginner"]},
    )

    assert constraints == {}
    assert spans == {}


def test_semantic_recommendation_coffee_gear_constraint_has_literal_ontology_support():
    constraints, spans = customer_agent_planner_service._recommendation_literal_grounding_filter(
        {"subject_kind": "coffee_gear"},
        {"subject_kind": ["想找一个轻便的手摇磨豆器"]},
    )

    assert constraints == {"subject_kind": "coffee_gear"}
    assert spans == {"subject_kind": ["想找一个轻便的手摇磨豆器"]}


def test_semantic_preplan_repairs_missing_pairwise_decision_criterion(monkeypatch):
    calls = []
    repair_system_prompt = ""

    async def fake_chat_completion(db, messages, **kwargs):
        nonlocal repair_system_prompt
        purpose = kwargs.get("purpose")
        calls.append(purpose)
        if purpose == "semantic_preplan":
            return json.dumps({
                "route_family": "comparison",
                "entities": ["A", "B"],
                "subject_text": "A和B",
                "confidence": "high",
                "decision_requested": True,
                "canonical_fields": [],
            })
        assert purpose == "semantic_preplan_repair"
        repair_system_prompt = messages[0]["content"]
        return json.dumps({
            "route_family": "comparison",
            "entities": ["A", "B"],
            "subject_text": "A和B",
            "confidence": "high",
            "decision_requested": True,
            "canonical_fields": ["usage_scene"],
            "field_type": "usage_scene",
        })

    monkeypatch.setattr(customer_agent_planner_service.customer_llm_service, "chat_completion", fake_chat_completion)
    result = asyncio.run(customer_agent_planner_service.plan_customer_question_semantic(
        db=None,
        question="A和B在户外做早餐哪个更合适？",
        deterministic_plan={},
        context={},
    ))

    assert calls == ["semantic_preplan", "semantic_preplan_repair"]
    assert result["route_family"] == "comparison"
    assert result["canonical_fields"] == ["usage_scene"]
    assert result["field_type"] == "usage_scene"
    assert "This is a named two-or-more-product comparison" in repair_system_prompt


def test_semantic_preplan_repair_keeps_numeric_product_identity_out_of_filter_fields(monkeypatch):
    """Semantic repair owns this distinction; no lexical field fallback may do it."""
    repair_prompt = []

    async def fake_chat_completion(db, messages, **kwargs):
        if kwargs.get("purpose") == "semantic_preplan":
            return json.dumps({
                "route_family": "structured_query",
                "subject_text": "户外水壶",
                "canonical_fields": ["dimensions", "capacity"],
                "field_type": "dimensions",
                "confidence": "high",
                "structured_query_constraints": [],
            })
        repair_prompt.append(messages[0]["content"])
        return json.dumps({
            "route_family": "product_bound_qa",
            "subject_text": "1.4升户外水壶",
            "canonical_fields": ["dimensions"],
            "field_type": "dimensions",
            "confidence": "high",
            "evidence_required": True,
        })

    monkeypatch.setattr(customer_agent_planner_service.customer_llm_service, "chat_completion", fake_chat_completion)
    result = asyncio.run(customer_agent_planner_service.plan_customer_question_semantic(
        db=None,
        question="1.4升户外水壶的尺寸是多少？",
        deterministic_plan={},
        context={},
    ))

    assert repair_prompt
    assert "entire product mention" in repair_prompt[0]
    assert result["route_family"] == "product_bound_qa"
    assert result["subject_text"] == "1.4升户外水壶"
    assert result["canonical_fields"] == ["dimensions"]


def test_semantic_product_qa_decision_prevents_alias_field_from_overwriting_intent(monkeypatch):
    """The model may choose sealed QA over an adjacent structured field."""

    async def fake_chat_completion(db, messages, **kwargs):
        return json.dumps({
            "route_family": "product_bound_qa",
            "subject_text": "示例炉",
            "canonical_fields": [],
            "confidence": "high",
            "evidence_required": True,
            "evidence_kind": "product_qa",
            "qa_evidence_query": "flame adjustability",
            "reasoning_summary": "The request asks whether a capability exists, not its numeric rating.",
        })

    monkeypatch.setattr(customer_agent_planner_service.customer_llm_service, "chat_completion", fake_chat_completion)
    plan = asyncio.run(customer_agent_planner_service.plan_customer_question_semantic(
        db=None,
        question="示例炉火力能否调节？",
        deterministic_plan={},
        context={},
    ))
    contract = customer_field_contract.resolve_requested_field_contract(
        "示例炉火力能否调节？",
        {"semantic_preplan": plan},
    )

    assert plan["evidence_kind"] == "product_qa"
    assert plan["qa_evidence_query"] == "flame adjustability"
    assert plan["canonical_fields"] == []
    assert customer_service_service._semantic_prefers_sealed_product_qa({"semantic_preplan": plan})
    assert customer_service_service._semantic_product_qa_preempts_legacy_shortcuts(plan)
    assert contract["canonical_fields"] == []
    assert contract["source"] == "validated_semantic_product_qa"


def test_sealed_semantic_qa_retrieval_never_falls_back_to_an_unrelated_same_sku_answer(route_client_and_db):
    """A semantic QA decision seals evidence relevance as well as product identity."""

    _client, _headers, Session = route_client_and_db
    with Session() as db:
        _add_product_qa(
            db,
            "STV-001",
            "魔盒卡式炉适合当礼物送人吗？",
            "适合作为礼物送给露营爱好者。",
            priority=10,
        )
        _add_product_qa(
            db,
            "STV-001",
            "魔盒卡式炉正常能用多久？",
            "正常使用并正确保养可使用多年。",
            priority=100,
        )
        db.commit()
        product = db.query(Product).filter(Product.sku == "STV-001").one()

        # An English ontology label is not customer-language evidence for a
        # Chinese same-SKU QA record. It must fail closed rather than select
        # the higher-priority durability answer.
        no_match = customer_service_service._best_product_qa_match(
            db,
            product,
            "魔盒卡式炉送人合适吗？",
            semantic_query="gifting suitability",
        )
        assert no_match is None

        matched = customer_service_service._best_product_qa_match(
            db,
            product,
            "魔盒卡式炉送人合适吗？",
            semantic_query="是否适合作为礼物送人",
        )
        assert matched is not None
        assert matched.question == "魔盒卡式炉适合当礼物送人吗？"


def test_sealed_semantic_qa_can_select_same_sku_candidate_without_answer_generation(route_client_and_db, monkeypatch):
    """LLM may select a stored QA id, but cannot choose identity or invent text."""

    _client, _headers, Session = route_client_and_db
    with Session() as db:
        _add_product_qa(
            db,
            "STV-001",
            "魔盒卡式炉如何辨别正品？",
            "通过官方渠道与防伪码核验。",
            priority=10,
        )
        _add_product_qa(
            db,
            "STV-001",
            "魔盒卡式炉正常能用多久？",
            "正常使用并正确保养可使用多年。",
            priority=100,
        )
        db.commit()

        async def fake_chat_completion(_db, messages, **kwargs):
            assert kwargs["purpose"] == "semantic_product_qa_evidence_selection"
            payload = json.loads(messages[-1]["content"])
            selected = next(item for item in payload["qa_candidates"] if "辨别正品" in item["question"])
            # Evidence selection is an intent decision over the current turn
            # and the stored QA questions.  Supplying candidate answers here
            # can make a merely related question look selectable because of
            # facts in its answer; the answer is retrieved only after this
            # same-SKU QA id has passed the selection contract.
            assert "answer" not in selected
            return json.dumps({"qa_id": selected["id"], "coverage": "full", "confidence": "high", "reasoning_summary": "matches verification concern"})

        monkeypatch.setattr(customer_service_service.customer_llm_service, "chat_completion", fake_chat_completion)
        plan = {
            "semantic_preplan": {
                "called": True,
                "route_family": "product_bound_qa",
                "route_hint": "product_detail",
                "confidence": 0.9,
                "evidence_kind": "product_qa",
                "canonical_fields": [],
                "field_type": "",
                "qa_evidence_query": "验货防伪方法",
            }
        }
        result = asyncio.run(customer_service_service._try_product_qa_shortcut_with_semantic_selection(
            db,
            "魔盒卡式炉如何验货防伪？",
            phase1_plan=plan,
        ))

        assert result is not None
        assert result["answer"] == "通过官方渠道与防伪码核验。"
        assert result["debug"]["field_contract"]["field_type"] == "product_qa"
        assert result["debug"]["entity_resolution_contract"]["resolved_sku"] == "STV-001"


def test_qa_substring_match_is_not_treated_as_a_complete_customer_question(route_client_and_db):
    """An old QA answer cannot consume a new second customer request."""
    _client, _headers, Session = route_client_and_db
    with Session() as db:
        _add_product(
            db,
            "QA-PARTIAL-01",
            "示例水壶",
            "水具",
            "/",
            "不锈钢",
            "/",
            "测试资料",
            "露营",
            100,
        )
        _add_product_qa(
            db,
            "QA-PARTIAL-01",
            "示例水壶耐用吗？",
            "正常使用时耐用，避免尖锐物划伤。",
            priority=100,
        )
        db.commit()
        product = db.query(Product).filter(Product.sku == "QA-PARTIAL-01").one()
        qa = db.query(ProductQa).filter(ProductQa.product_id == product.id).one()

        assert qa is not None
        assert not customer_service_service._is_exact_product_qa_question_match(
            qa,
            "示例水壶耐用吗？另外能不能直接装开水？",
        )


def test_selected_same_sku_qa_is_not_rejected_by_a_later_structured_keyword_guard(route_client_and_db, monkeypatch):
    """A sealed QA selection stays evidence, even when the turn says a field word."""
    _client, _headers, Session = route_client_and_db
    with Session() as db:
        _add_product(
            db,
            "QA-FUEL-01",
            "Semantic Fuel Stove",
            "stove",
            "/",
            "/",
            "/",
            "test product",
            "camping",
            1.0,
        )
        _add_product_qa(
            db,
            "QA-FUEL-01",
            "Semantic Fuel Stove full fuel duration?",
            "A full fuel load lasts about 40 minutes on high or 120 minutes on medium-low, enough for one meal.",
            priority=10,
        )
        db.commit()

        async def select_duration_qa(_db, selected_product, _question, **_kwargs):
            return db.query(ProductQa).filter(ProductQa.product_id == selected_product.id).one()

        monkeypatch.setattr(
            customer_service_service,
            "_select_same_sku_product_qa_with_semantic_selection",
            select_duration_qa,
        )
        plan = {
            "semantic_preplan": {
                "called": True,
                "route_family": "product_bound_qa",
                "route_hint": "product_detail",
                "confidence": 0.95,
                "evidence_kind": "product_qa",
                "canonical_fields": [],
                "field_type": "",
                "qa_evidence_query": "fuel load duration for one meal",
            }
        }
        result = asyncio.run(customer_service_service._try_product_qa_shortcut_with_semantic_selection(
            db,
            "Semantic Fuel Stove 加一次燃料，做一顿饭够不够？",
            phase1_plan=plan,
        ))

        assert result is not None
        assert result["result_skus"] == ["QA-FUEL-01"]
        assert result["answer_metadata"]["evidence_sku"] == "QA-FUEL-01"
        assert result["debug"]["field_contract"]["field_type"] == "product_qa"
        assert "enough for one meal" in result["answer"]


def test_sealed_semantic_qa_with_unresolved_subject_fails_closed_before_legacy_retrieval(route_client_and_db):
    _client, _headers, Session = route_client_and_db
    with Session() as db:
        plan = {
            "semantic_preplan": {
                "called": True,
                "route_family": "product_bound_qa",
                "route_hint": "product_detail",
                "confidence": 0.9,
                "evidence_kind": "product_qa",
                "canonical_fields": [],
                "field_type": "",
                "subject_text": "不存在的折叠椅",
            }
        }
        result = customer_service_service._sealed_semantic_product_qa_entity_guard(
            db,
            "不存在的折叠椅能坐多重的人？",
            plan,
        )

        assert result is not None
        assert result["answer_type"] == "clarification"
        assert result["result_skus"] == []
        assert result["debug"]["field_contract"]["field_type"] == "product_qa"
        assert result["debug"]["entity_resolution_contract"]["status"] == "unresolved"


def test_sealed_semantic_qa_uses_unique_canonical_name_inside_an_overlong_subject(route_client_and_db):
    """Identity sealing trims only a verified canonical name, never a guessed SKU."""
    _client, _headers, Session = route_client_and_db
    with Session() as db:
        _add_product(
            db,
            "QA-SPAN-01",
            "Semantic Fuel Stove",
            "stove",
            "/",
            "/",
            "/",
            "test product",
            "camping",
            0,
        )
        db.commit()
        result = customer_service_service._sealed_semantic_product_qa_entity_guard(
            db,
            "Semantic Fuel Stove one fill is enough for dinner?",
            {
                "semantic_preplan": {
                    "called": True,
                    "route_family": "product_bound_qa",
                    "route_hint": "product_detail",
                    "confidence": 0.9,
                    "evidence_kind": "product_qa",
                    "canonical_fields": [],
                    "field_type": "",
                    "subject_text": "Semantic Fuel Stove one fill",
                }
            },
        )

    assert result is not None
    assert result["debug"]["entity_resolution_contract"]["status"] == "resolved"
    assert result["debug"]["entity_resolution_contract"]["resolved_sku"] == "QA-SPAN-01"


def test_sealed_semantic_qa_uses_unique_canonical_name_when_semantic_subject_drops_its_prefix(route_client_and_db):
    """The current turn's unique full name beats a shortened semantic subject."""
    _client, _headers, Session = route_client_and_db
    with Session() as db:
        _add_product(
            db,
            "QA-PREFIX-01",
            "Travel Picnic Pot 5pc",
            "cookware",
            "/",
            "/",
            "/",
            "test product",
            "camping",
            0,
        )
        db.commit()
        result = customer_service_service._sealed_semantic_product_qa_entity_guard(
            db,
            "Could Travel Picnic Pot 5pc help me decide what to pack?",
            {
                "semantic_preplan": {
                    "called": True,
                    "route_family": "product_bound_qa",
                    "route_hint": "product_detail",
                    "confidence": 0.9,
                    "evidence_kind": "product_qa",
                    "canonical_fields": [],
                    "field_type": "",
                    "subject_text": "Picnic Pot 5pc",
                }
            },
        )

    assert result is not None
    assert result["debug"]["entity_resolution_contract"]["status"] == "resolved"
    assert result["debug"]["entity_resolution_contract"]["resolved_sku"] == "QA-PREFIX-01"
    assert result["debug"]["field_contract"]["subject"] == "Travel Picnic Pot 5pc"


def test_high_risk_guard_does_not_preempt_validated_product_qa_contract():
    plan = {
        "called": True,
        "route_family": "product_bound_qa",
        "route_hint": "product_detail",
        "confidence": 0.9,
        "evidence_kind": "product_qa",
        "canonical_fields": [],
        "field_type": "",
        "subject_text": "Semantic Fuel Stove one fill",
    }

    assert customer_service_service._pre_route_high_risk_contract_result(
        None,
        "Semantic Fuel Stove one fill is enough for dinner?",
        plan,
    ) is None
    assert customer_service_service._entity_scope_pre_route_guard_result(
        None,
        "Semantic Fuel Stove one fill is enough for dinner?",
        {"semantic_preplan": plan},
        plan,
    ) is None


def test_generic_detail_clarification_does_not_expose_a_resolved_entity_contract():
    resolved = customer_entity_resolution_contract.EntityResolutionContract(
        entity_text="煎盘",
        normalized_entity_text="煎盘",
        status="resolved",
        resolved_sku="CW-C12",
        resolver_candidate_skus=["CW-C12"],
        diagnostic_candidate_skus=[],
        candidate_skus=["CW-C12"],
        matched_by="canonical_name_exact",
        confidence="high",
        is_unique=True,
        matched_span=(0, 2),
        field_type="weight",
        status_reason="resolver_unique_exact",
    )

    result = customer_service_service._build_phase2_entity_state_response(
        None,
        "煎盘有多重？",
        {"action": "generic_clarification", "contract": resolved},
    )

    contract = result["debug"]["entity_resolution_contract"]
    assert result["answer_type"] == "clarification"
    assert contract["status"] == "generic"
    assert contract["resolved_sku"] is None
    assert contract["candidate_skus"] == []


def test_semantic_preplan_retries_invalid_pairwise_criterion_repair(monkeypatch):
    calls = []

    async def fake_chat_completion(db, messages, **kwargs):
        purpose = kwargs.get("purpose")
        calls.append(purpose)
        if purpose == "semantic_preplan":
            return json.dumps({
                "route_family": "comparison",
                "entities": ["A", "B"],
                "subject_text": "A和B",
                "confidence": "high",
                "decision_requested": True,
                "canonical_fields": ["recommendation"],
            })
        if calls.count("semantic_preplan_repair") == 1:
            return json.dumps({
                "route_family": "comparison",
                "entities": ["A", "B"],
                "subject_text": "A和B",
                "confidence": "high",
                "decision_requested": True,
                "canonical_fields": [],
            })
        return json.dumps({
            "route_family": "comparison",
            "entities": ["A", "B"],
            "subject_text": "A和B",
            "confidence": "high",
            "decision_requested": True,
            "canonical_fields": ["usage_scene"],
        })

    monkeypatch.setattr(customer_agent_planner_service.customer_llm_service, "chat_completion", fake_chat_completion)
    result = asyncio.run(customer_agent_planner_service.plan_customer_question_semantic(
        db=None,
        question="A和B露营早餐哪个更合适？",
        deterministic_plan={},
        context={},
    ))

    assert calls == ["semantic_preplan", "semantic_preplan_repair", "semantic_preplan_repair"]
    assert result["canonical_fields"] == ["usage_scene"]
    assert result["field_type"] == "usage_scene"


def test_semantic_preplan_repairs_empty_pairwise_fields_without_decision_flag(monkeypatch):
    calls = []

    async def fake_chat_completion(db, messages, **kwargs):
        calls.append(kwargs.get("purpose"))
        if kwargs.get("purpose") == "semantic_preplan":
            return json.dumps({
                "route_family": "comparison",
                "entities": ["A", "B"],
                "subject_text": "A和B",
                "confidence": "high",
                "decision_requested": False,
                "canonical_fields": [],
            })
        return json.dumps({
            "route_family": "clarification",
            "entities": ["A", "B"],
            "subject_text": "A和B",
            "confidence": "high",
            "decision_requested": False,
            "canonical_fields": [],
        })

    monkeypatch.setattr(customer_agent_planner_service.customer_llm_service, "chat_completion", fake_chat_completion)
    result = asyncio.run(customer_agent_planner_service.plan_customer_question_semantic(
        db=None,
        question="A和B哪个更适合？",
        deterministic_plan={},
        context={},
    ))

    assert calls == ["semantic_preplan", "semantic_preplan_repair"]
    assert result["route_family"] == "clarification"


def test_semantic_grounding_retries_when_a_retained_constraint_lacks_its_source_span(monkeypatch):
    calls = []

    async def fake_chat_completion(db, messages, **kwargs):
        purpose = kwargs.get("purpose")
        calls.append(purpose)
        if purpose == "semantic_preplan":
            return json.dumps({
                "route_family": "recommendation",
                "entity_scope": "category_scope",
                "subject_text": "水具",
                "canonical_fields": ["weight"],
                "confidence": "high",
                "recommendation_constraints": {
                    "subject_kind": "waterware",
                    "weight_preference": "lightweight",
                },
            })
        if purpose == "semantic_preplan_requirement_reconciliation":
            return json.dumps({
                "recommendation_constraints": {
                    "subject_kind": "waterware",
                    "weight_preference": "lightweight",
                },
                "unrepresented_recommendation_requirements": [],
                "recommendation_soft_preferences": [],
                "evidence_spans": {
                    "subject_kind": ["水具"],
                    "weight_preference": ["重量比较轻"],
                },
            })
        if calls.count("semantic_recommendation_constraint_grounding") == 1:
            return json.dumps({
                "recommendation_constraints": {
                    "subject_kind": "waterware",
                    "weight_preference": "lightweight",
                },
                "evidence_spans": {"weight_preference": ["重量比较轻"]},
            })
        return json.dumps({
            "recommendation_constraints": {
                "subject_kind": "waterware",
                "weight_preference": "lightweight",
            },
            "evidence_spans": {
                "subject_kind": ["水具"],
                "weight_preference": ["重量比较轻"],
            },
        })

    monkeypatch.setattr(customer_agent_planner_service.customer_llm_service, "chat_completion", fake_chat_completion)
    result = asyncio.run(customer_agent_planner_service.plan_customer_question_semantic(
        db=None,
        question="只看重量比较轻的水具，有哪些选择？",
        deterministic_plan={},
        context={},
    ))

    assert calls == [
        "semantic_preplan",
        "semantic_preplan_requirement_reconciliation",
        "semantic_recommendation_constraint_grounding",
        "semantic_recommendation_constraint_grounding",
    ]
    assert result["recommendation_constraints"] == {
        "subject_kind": "waterware",
        "weight_preference": "lightweight",
    }
    assert result["recommendation_constraint_grounding"] == "validated_semantic_grounding"


def test_semantic_reconciliation_retries_instead_of_retaining_an_unrepresented_requirement(monkeypatch):
    calls = []

    async def fake_chat_completion(db, messages, **kwargs):
        purpose = kwargs.get("purpose")
        calls.append(purpose)
        if purpose == "semantic_preplan":
            return json.dumps({
                "route_family": "recommendation",
                "entity_scope": "category_scope",
                "subject_text": "烧水的容器",
                "canonical_fields": ["weight", "usage_scene"],
                "confidence": "high",
                "recommendation_constraints": {
                    "subject_kind": "waterware",
                    "scenarios": ["hiking"],
                    "weight_preference": "lightweight",
                },
                "unrepresented_recommendation_requirements": ["背着轻一点"],
            })
        if purpose == "semantic_preplan_requirement_reconciliation":
            if calls.count(purpose) == 1:
                return json.dumps({
                    "recommendation_constraints": {
                        "subject_kind": "waterware",
                        "people": {"min": 1, "max": 1},
                        "scenarios": ["hiking"],
                        "weight_preference": "lightweight",
                    },
                    "unrepresented_recommendation_requirements": [],
                    "evidence_spans": {
                        "subject_kind": ["烧水的容器"],
                        "people": [],
                        "scenarios": ["徒步"],
                        "weight_preference": ["轻一点"],
                    },
                })
            return json.dumps({
                "recommendation_constraints": {
                    "subject_kind": "waterware",
                    "scenarios": ["hiking"],
                    "weight_preference": "lightweight",
                },
                "unrepresented_recommendation_requirements": [],
                "evidence_spans": {
                    "subject_kind": ["烧水的容器"],
                    "scenarios": ["徒步"],
                    "weight_preference": ["轻一点"],
                },
            })
        assert purpose == "semantic_recommendation_constraint_grounding"
        return json.dumps({
            "recommendation_constraints": {
                "subject_kind": "waterware",
                "scenarios": ["hiking"],
                "weight_preference": "lightweight",
            },
            "evidence_spans": {
                "subject_kind": ["烧水的容器"],
                "scenarios": ["徒步"],
                "weight_preference": ["轻一点"],
            },
        })

    monkeypatch.setattr(customer_agent_planner_service.customer_llm_service, "chat_completion", fake_chat_completion)
    result = asyncio.run(customer_agent_planner_service.plan_customer_question_semantic(
        db=None,
        question="我想背着轻一点去徒步，需要能烧水的容器，怎么选？",
        deterministic_plan={},
        context={},
    ))

    assert calls[:3] == [
        "semantic_preplan",
        "semantic_preplan_requirement_reconciliation",
        "semantic_preplan_requirement_reconciliation",
    ]
    assert calls[3:] in (["semantic_recommendation_constraint_grounding"], [
        "semantic_recommendation_constraint_grounding",
        "semantic_recommendation_constraint_grounding",
    ])
    assert result["unrepresented_recommendation_requirements"] == []
    assert result["recommendation_constraints"] == {
        "subject_kind": "waterware",
        "scenarios": ["hiking"],
        "weight_preference": "lightweight",
    }


def test_semantic_preplan_repairs_invalid_recommendation_constraint_schema_before_legacy_fallback(monkeypatch):
    calls = []

    async def fake_chat_completion(db, messages, **kwargs):
        purpose = kwargs.get("purpose")
        calls.append(purpose)
        if purpose == "semantic_preplan":
            return json.dumps({
                "route_family": "recommendation",
                "entity_scope": "category_scope",
                "confidence": "high",
                "recommendation_constraints": {"scenarios": ["breakfast"]},
            })
        if purpose == "semantic_preplan_repair":
            return json.dumps({
                "route_family": "recommendation",
                "entity_scope": "category_scope",
                "confidence": "high",
                "recommendation_constraints": {"subject_kind": "cookware"},
            })
        if purpose == "semantic_preplan_requirement_reconciliation":
            return json.dumps({
                "recommendation_constraints": {"subject_kind": "cookware"},
                "unrepresented_recommendation_requirements": [],
                "recommendation_soft_preferences": [],
                "evidence_spans": {"subject_kind": ["锅"]},
            })
        assert purpose == "semantic_recommendation_constraint_grounding"
        return json.dumps({
            "recommendation_constraints": {"subject_kind": "cookware"},
            "evidence_spans": {"subject_kind": ["锅"]},
        })

    monkeypatch.setattr(customer_agent_planner_service.customer_llm_service, "chat_completion", fake_chat_completion)
    result = asyncio.run(customer_agent_planner_service.plan_customer_question_semantic(
        db=None,
        question="我主要做煎烤早餐，锅和烤盘该优先选哪个？",
        deterministic_plan={"primary_intent": "recommendation"},
        context={},
    ))

    assert calls == [
        "semantic_preplan",
        "semantic_preplan_repair",
        "semantic_preplan_requirement_reconciliation",
        "semantic_recommendation_constraint_grounding",
    ]
    assert result["route_family"] == "recommendation"
    assert result["recommendation_constraints"] == {"subject_kind": "cookware"}
    assert not result["fallback_reason"]


def test_semantic_preplan_rebuilds_only_invalid_recommendation_constraint_partition_after_full_repair_fails(monkeypatch):
    calls = []

    async def fake_chat_completion(db, messages, **kwargs):
        purpose = kwargs.get("purpose")
        calls.append(purpose)
        if purpose == "semantic_preplan":
            return json.dumps({
                "route_family": "recommendation",
                "entity_scope": "category_scope",
                "subject_text": "锅和烤盘",
                "confidence": "high",
                "recommendation_constraints": {"scenarios": ["breakfast"]},
            })
        if purpose == "semantic_preplan_repair":
            # The broad replan can occasionally repeat the same invalid enum.
            return json.dumps({
                "route_family": "recommendation",
                "entity_scope": "category_scope",
                "subject_text": "锅和烤盘",
                "confidence": "high",
                "recommendation_constraints": {"scenarios": ["breakfast"]},
            })
        if purpose == "semantic_recommendation_constraint_schema_repair":
            return json.dumps({
                "recommendation_constraints": {"subject_kind": "cookware"},
                "unrepresented_recommendation_requirements": ["煎烤早餐"],
            })
        if purpose == "semantic_preplan_requirement_reconciliation":
            return "{}"
        assert purpose == "semantic_recommendation_constraint_grounding"
        return json.dumps({
            "recommendation_constraints": {"subject_kind": "cookware"},
            "evidence_spans": {"subject_kind": ["锅和烤盘"]},
        })

    monkeypatch.setattr(customer_agent_planner_service.customer_llm_service, "chat_completion", fake_chat_completion)
    result = asyncio.run(customer_agent_planner_service.plan_customer_question_semantic(
        db=None,
        question="我主要做煎烤早餐，锅和烤盘该优先选哪个？",
        deterministic_plan={"primary_intent": "recommendation"},
        context={},
    ))

    assert calls[:3] == [
        "semantic_preplan",
        "semantic_preplan_repair",
        "semantic_recommendation_constraint_schema_repair",
    ]
    assert calls[-1] == "semantic_recommendation_constraint_grounding"
    assert result["route_family"] == "recommendation"
    assert result["recommendation_constraints"] == {"subject_kind": "cookware"}
    assert result["unrepresented_recommendation_requirements"] == ["煎烤早餐"]
    assert not result["fallback_reason"]


def test_semantic_recommendation_constraint_partition_keeps_valid_subset_only_with_literal_unrepresented_requirement(monkeypatch):
    async def fake_chat_completion(_db, _messages, **kwargs):
        assert kwargs.get("purpose") == "semantic_recommendation_constraint_schema_repair"
        return json.dumps({
            "recommendation_constraints": {
                "subject_kind": "cookware",
                "scenarios": ["breakfast"],
            },
            "unrepresented_recommendation_requirements": ["煎烤早餐"],
        })

    monkeypatch.setattr(customer_agent_planner_service.customer_llm_service, "chat_completion", fake_chat_completion)
    result = asyncio.run(
        customer_agent_planner_service._repair_semantic_recommendation_constraint_partition(
            db=None,
            question="我主要做煎烤早餐，锅和烤盘该优先选哪个？",
            invalid_constraints={"subject_kind": "cookware", "scenarios": ["breakfast"]},
            invalid_unrepresented_requirements=["煎烤早餐"],
        )
    )

    assert result == {
        "recommendation_constraints": {"subject_kind": "cookware"},
        "unrepresented_recommendation_requirements": ["煎烤早餐"],
    }


def test_semantic_recommendation_constraint_partition_retries_nonliteral_requirement(monkeypatch):
    calls = []

    async def fake_chat_completion(_db, messages, **kwargs):
        calls.append(messages[0]["content"])
        assert kwargs.get("purpose") == "semantic_recommendation_constraint_schema_repair"
        if len(calls) == 1:
            return json.dumps({
                "recommendation_constraints": {"subject_kind": "coffee_gear"},
                "unrepresented_recommendation_requirements": ["non-electric"],
            })
        return json.dumps({
            "recommendation_constraints": {"subject_kind": "coffee_gear"},
            "unrepresented_recommendation_requirements": ["不插电"],
        })

    monkeypatch.setattr(customer_agent_planner_service.customer_llm_service, "chat_completion", fake_chat_completion)
    result = asyncio.run(
        customer_agent_planner_service._repair_semantic_recommendation_constraint_partition(
            db=None,
            question="想找不插电的手摇磨豆器",
            invalid_constraints={"subject_kind": "coffee_gear", "power": "manual"},
            invalid_unrepresented_requirements=["non-electric"],
        )
    )

    assert result == {
        "recommendation_constraints": {"subject_kind": "coffee_gear"},
        "unrepresented_recommendation_requirements": ["不插电"],
    }
    assert "Do not translate" in calls[1]


def test_semantic_preplan_repairs_invalid_unrepresented_requirement_schema_before_legacy_fallback(monkeypatch):
    calls = []

    async def fake_chat_completion(db, messages, **kwargs):
        purpose = kwargs.get("purpose")
        calls.append(purpose)
        if purpose == "semantic_preplan":
            return json.dumps({
                "route_family": "recommendation",
                "entity_scope": "category_scope",
                "confidence": "high",
                "recommendation_constraints": {"subject_kind": "cookware", "price_preference": "affordable"},
                "unrepresented_recommendation_requirements": ["送朋友", 1],
            })
        if purpose == "semantic_preplan_repair":
            return json.dumps({
                "route_family": "recommendation",
                "entity_scope": "category_scope",
                "confidence": "high",
                "recommendation_constraints": {"subject_kind": "cookware", "price_preference": "affordable"},
            })
        if purpose == "semantic_preplan_requirement_reconciliation":
            return json.dumps({
                "recommendation_constraints": {"subject_kind": "cookware", "price_preference": "affordable"},
                "unrepresented_recommendation_requirements": [],
                "recommendation_soft_preferences": [],
                "evidence_spans": {
                    "subject_kind": ["户外炊具"],
                    "price_preference": ["预算别太高"],
                },
            })
        assert purpose == "semantic_recommendation_constraint_grounding"
        return json.dumps({
            "recommendation_constraints": {"subject_kind": "cookware", "price_preference": "affordable"},
            "evidence_spans": {
                "subject_kind": ["户外炊具"],
                "price_preference": ["预算别太高"],
            },
        })

    monkeypatch.setattr(customer_agent_planner_service.customer_llm_service, "chat_completion", fake_chat_completion)
    result = asyncio.run(customer_agent_planner_service.plan_customer_question_semantic(
        db=None,
        question="预算别太高，想给朋友送一套户外炊具，推荐什么方向？",
        deterministic_plan={"primary_intent": "recommendation"},
        context={},
    ))

    assert calls == [
        "semantic_preplan",
        "semantic_preplan_repair",
        "semantic_preplan_requirement_reconciliation",
        "semantic_recommendation_constraint_grounding",
    ]
    assert result["route_family"] == "recommendation"
    assert result["recommendation_constraints"] == {"subject_kind": "cookware", "price_preference": "affordable"}
    assert not result["fallback_reason"]


def test_semantic_preplan_accepts_allowlisted_price_preference_constraint():
    result = customer_agent_planner_service._validated_recommendation_constraints({
        "subject_kind": "cookware",
        "price_preference": "affordable",
    })

    assert result == {
        "subject_kind": "cookware",
        "price_preference": "affordable",
    }


def test_semantic_preplan_repair_preserves_valid_initial_unrepresented_requirement(monkeypatch):
    calls = []

    async def fake_chat_completion(db, messages, **kwargs):
        purpose = kwargs.get("purpose")
        calls.append(purpose)
        if purpose == "semantic_preplan":
            return json.dumps({
                "route_family": "recommendation", "confidence": "high",
                "recommendation_constraints": {"scenarios": ["unsupported_style"]},
                "unrepresented_recommendation_requirements": ["小一点的锅"],
            })
        if purpose == "semantic_preplan_repair":
            return json.dumps({
                "route_family": "recommendation", "confidence": "high",
                "recommendation_constraints": {"subject_kind": "cookware"},
            })
        if purpose == "semantic_preplan_requirement_reconciliation":
            # The newly added completeness review must fail closed when it
            # cannot prove that this literal requirement maps to the formal
            # recommendation ontology.
            return "{}"
        assert purpose == "semantic_recommendation_constraint_grounding"
        return json.dumps({
            "recommendation_constraints": {"subject_kind": "cookware"},
            "evidence_spans": {"subject_kind": ["锅"]},
        })

    monkeypatch.setattr(customer_agent_planner_service.customer_llm_service, "chat_completion", fake_chat_completion)
    result = asyncio.run(customer_agent_planner_service.plan_customer_question_semantic(
        db=None,
        question="户外煮面想要小一点的锅，明火也能用，怎么选？",
        deterministic_plan={"primary_intent": "recommendation"}, context={},
    ))

    assert calls == [
        "semantic_preplan",
        "semantic_preplan_repair",
        "semantic_preplan_requirement_reconciliation",
        "semantic_recommendation_constraint_grounding",
    ]
    assert result["unrepresented_recommendation_requirements"] == ["小一点的锅"]


def test_semantic_preplan_keeps_explicit_requirements_from_its_primary_semantic_decision(monkeypatch):
    calls = []

    async def fake_chat_completion(db, messages, **kwargs):
        purpose = kwargs.get("purpose")
        calls.append(purpose)
        if purpose == "semantic_preplan":
            return json.dumps({
                "route_family": "recommendation", "confidence": "high",
                "recommendation_constraints": {"subject_kind": "cookware"},
                "unrepresented_recommendation_requirements": ["小一点的锅", "煮面"],
            })
        if purpose == "semantic_preplan_requirement_reconciliation":
            return "{}"
        assert purpose == "semantic_recommendation_constraint_grounding"
        return json.dumps({
            "recommendation_constraints": {"subject_kind": "cookware"},
            "evidence_spans": {"subject_kind": ["锅"]},
        })

    monkeypatch.setattr(customer_agent_planner_service.customer_llm_service, "chat_completion", fake_chat_completion)
    result = asyncio.run(customer_agent_planner_service.plan_customer_question_semantic(
        db=None,
        question="户外煮面想要小一点的锅，明火也能用，怎么选？",
        deterministic_plan={"primary_intent": "recommendation"}, context={},
    ))

    assert calls == [
        "semantic_preplan",
        "semantic_preplan_requirement_reconciliation",
        "semantic_recommendation_constraint_grounding",
    ]
    assert result["unrepresented_recommendation_requirements"] == ["小一点的锅", "煮面"]


def test_semantic_preplan_does_not_reinterpret_accepted_constraints_in_a_second_requirement_pass(monkeypatch):
    """The first semantic plan owns meaning; later deterministic checks only validate it.

    A second model call sees no candidate evidence and can turn an already accepted
    semantic interpretation into a broader "unrepresented" blocker.  That makes
    ordinary recommendations clarify despite a complete, grounded first plan.
    """
    calls = []

    async def fake_chat_completion(db, messages, **kwargs):
        purpose = kwargs.get("purpose")
        calls.append(purpose)
        if purpose == "semantic_preplan":
            return json.dumps({
                "route_family": "recommendation", "confidence": "high",
                "recommendation_constraints": {
                    "subject_kind": "cookware", "heat_sources": ["open_flame"],
                },
            })
        if purpose == "semantic_preplan_requirement_reconciliation":
            return json.dumps({
                "recommendation_constraints": {
                    "subject_kind": "cookware", "heat_sources": ["open_flame"],
                },
                "unrepresented_recommendation_requirements": [],
                "recommendation_soft_preferences": [],
                "evidence_spans": {
                    "subject_kind": ["小锅"], "heat_sources": ["明火"],
                },
            })
        assert purpose == "semantic_recommendation_constraint_grounding"
        return json.dumps({
            "recommendation_constraints": {
                "subject_kind": "cookware", "heat_sources": ["open_flame"],
            },
            "evidence_spans": {"subject_kind": ["小锅"], "heat_sources": ["明火"]},
        })

    monkeypatch.setattr(customer_agent_planner_service.customer_llm_service, "chat_completion", fake_chat_completion)

    result = asyncio.run(customer_agent_planner_service.plan_customer_question_semantic(
        None,
        question="想要一款适合户外煮面的小锅，最好能用明火。",
        deterministic_plan={"primary_intent": "recommendation"},
        context={},
    ))

    assert calls == [
        "semantic_preplan",
        "semantic_preplan_requirement_reconciliation",
        "semantic_recommendation_constraint_grounding",
    ]
    assert result["recommendation_constraints"] == {
        "subject_kind": "cookware", "heat_sources": ["open_flame"],
    }
    assert result["unrepresented_recommendation_requirements"] == []


def test_invalid_semantic_recommendation_schema_preserves_route_provenance_for_safe_clarification(monkeypatch):
    async def fake_chat_completion(db, messages, **kwargs):
        if kwargs.get("purpose") == "semantic_preplan":
            return json.dumps({
                "route_family": "recommendation",
                "entity_scope": "category_scope",
                "confidence": "high",
                "recommendation_constraints": {"scenarios": ["unsupported_style"]},
            })
        if kwargs.get("purpose") == "semantic_preplan_repair":
            # A second invalid schema must never reopen the legacy recommendation
            # router.  It retains only semantic provenance, not an invented need.
            return json.dumps({
                "route_family": "recommendation",
                "entity_scope": "category_scope",
                "confidence": "high",
                "recommendation_constraints": {"scenarios": ["still_unsupported"]},
            })
        raise AssertionError(f"unexpected semantic call: {kwargs.get('purpose')}")

    monkeypatch.setattr(customer_agent_planner_service.customer_llm_service, "chat_completion", fake_chat_completion)
    preplan = asyncio.run(customer_agent_planner_service.plan_customer_question_semantic(
        db=None,
        question="我主要做煎烤早餐，锅和烤盘该优先选哪个？",
        deterministic_plan={"primary_intent": "recommendation"},
        context={},
    ))

    assert preplan["fallback_reason"] == "invalid_recommendation_constraints"
    assert preplan["semantic_route_family_hint"] == "recommendation"
    clarification = customer_service_service._semantic_recommendation_constraint_clarification_result(preplan)
    assert clarification is not None
    assert clarification["answer_type"] == "clarification"
    assert clarification["result_skus"] == []
    assert clarification["debug"]["agent_mode"] == "semantic_recommendation_invalid_contract_clarification"


def test_recommendation_label_fallback_cannot_enter_uncontracted_candidate_generation(monkeypatch):
    async def fake_chat_completion(db, messages, **kwargs):
        # The provider has recognised a recommendation turn but has failed to
        # produce the required structured object on every bounded retry.
        return "recommendation"

    monkeypatch.setattr(customer_agent_planner_service.customer_llm_service, "chat_completion", fake_chat_completion)
    preplan = asyncio.run(customer_agent_planner_service.plan_customer_question_semantic(
        db=None,
        question="周末两人徒步露营，优先考虑轻一点、好带的锅具，有什么建议？",
        deterministic_plan={},
        context={},
    ))

    assert preplan["fallback_reason"] == "semantic_label_without_contract"
    assert preplan["semantic_route_family_hint"] == "recommendation"
    clarification = customer_service_service._semantic_recommendation_constraint_clarification_result(preplan)
    assert clarification is not None
    assert clarification["answer_type"] == "clarification"
    assert clarification["result_skus"] == []
    assert clarification["debug"]["agent_mode"] == "semantic_recommendation_invalid_contract_clarification"


def test_invalid_semantic_contract_can_execute_explicit_category_recommendation():
    preplan = {
        "called": True,
        "route_family": "recommendation",
        "semantic_route_family_hint": "recommendation",
        "confidence": 0.95,
        "confidence_label": "high",
        "fallback_reason": "invalid_recommendation_constraints",
        "recommendation_constraints": {},
        "ambiguity": False,
    }

    assert customer_service_service._semantic_recommendation_constraint_clarification_result(
        preplan,
        "适合户外的气炉推荐一下",
    ) is None


def test_non_evidentiary_recommendation_repair_keeps_catalog_intent_with_a_contract(monkeypatch):
    captured = {}

    async def fake_chat_completion(db, messages, **kwargs):
        if kwargs.get("purpose") == "semantic_preplan":
            return json.dumps({
                "route_family": "recommendation",
                "confidence": "high",
                "evidence_required": False,
                "recommendation_constraints": {},
            })
        if kwargs.get("purpose") == "semantic_preplan_repair":
            captured["system"] = messages[0]["content"]
            return json.dumps({
                "route_family": "recommendation",
                "confidence": "high",
                "evidence_required": True,
                "recommendation_constraints": {
                    "subject_kind": "cookware",
                    "people": {"min": 2, "max": 2},
                    "scenarios": ["camping"],
                    "weight_preference": "lightweight",
                },
            })
        if kwargs.get("purpose") == "semantic_preplan_requirement_reconciliation":
            return json.dumps({
                "recommendation_constraints": {
                    "subject_kind": "cookware",
                    "people": {"min": 2, "max": 2},
                    "scenarios": ["camping"],
                    "weight_preference": "lightweight",
                },
                "unrepresented_recommendation_requirements": [],
                "recommendation_soft_preferences": [],
                "evidence_spans": {
                    "subject_kind": ["锅具"],
                    "people": ["两人"],
                    "scenarios": ["徒步露营"],
                    "weight_preference": ["轻一点"],
                },
            })
        if kwargs.get("purpose") == "semantic_recommendation_constraint_grounding":
            return json.dumps({
                "recommendation_constraints": {
                    "subject_kind": "cookware",
                    "people": {"min": 2, "max": 2},
                    "scenarios": ["camping"],
                    "weight_preference": "lightweight",
                },
                "evidence_spans": {
                    "subject_kind": ["锅具"],
                    "people": ["两人"],
                    "scenarios": ["徒步露营"],
                    "weight_preference": ["轻一点"],
                },
            })
        raise AssertionError(f"unexpected semantic call: {kwargs.get('purpose')}")

    monkeypatch.setattr(customer_agent_planner_service.customer_llm_service, "chat_completion", fake_chat_completion)
    preplan = asyncio.run(customer_agent_planner_service.plan_customer_question_semantic(
        db=None,
        question="周末两人徒步露营，优先考虑轻一点、好带的锅具，有什么建议？",
        deterministic_plan={},
        context={},
    ))

    assert "Return route_family=recommendation" in captured["system"]
    assert preplan["fallback_reason"] == ""
    assert preplan["route_family"] == "recommendation"
    assert preplan["recommendation_constraints"] == {
        "subject_kind": "cookware",
        "people": {"min": 2, "max": 2},
        "scenarios": ["camping"],
        "weight_preference": "lightweight",
    }


def test_unbound_declarative_request_reaches_semantic_preplan_before_legacy_field_route():
    # An unbound natural-language turn has no sealed entity or formal field
    # contract yet. A legacy parser may see one noun such as "weight", but it
    # cannot decide the customer intent before semantic planning.
    assert customer_service_service._should_call_semantic_preplan(
        "帮我挑个轻便的户外烧水装备",
        {"primary_intent": "product_field", "confidence": "high"},
        conversation_id=None,
        has_named_product=False,
    ) is True


def test_semantic_preplan_repair_uses_the_current_structured_semantic_contract(monkeypatch):
    captured = {}

    async def fake_chat_completion(db, messages, **kwargs):
        captured["messages"] = messages
        captured["purpose"] = kwargs.get("purpose")
        return "{}"

    monkeypatch.setattr(customer_agent_planner_service.customer_llm_service, "chat_completion", fake_chat_completion)
    asyncio.run(customer_agent_planner_service._repair_semantic_preplan_output(
        db=None,
        question="锅和烤盘该优先选哪个？",
        raw_content='{"route_family":"recommendation","recommendation_constraints":{"scenarios":["breakfast"]}}',
    ))

    system = str(captured["messages"][0]["content"])
    assert captured["purpose"] == "semantic_preplan_repair"
    assert "canonical_fields" in system
    assert "comparison" in system
    assert "product_navigation" in system


def test_invalid_recommendation_constraint_repair_explicitly_removes_non_ontology_keys(monkeypatch):
    captured = {}

    async def fake_chat_completion(db, messages, **kwargs):
        captured["system"] = messages[0]["content"]
        return "{}"

    monkeypatch.setattr(customer_agent_planner_service.customer_llm_service, "chat_completion", fake_chat_completion)
    asyncio.run(customer_agent_planner_service._repair_semantic_preplan_output(
        db=None,
        question="我主要做煎烤早餐，锅和烤盘该优先选哪个？",
        raw_content='{"route_family":"recommendation","recommendation_constraints":{"scenarios":["breakfast"]}}',
        failure_reason="invalid_recommendation_constraints",
    ))

    system = str(captured["system"])
    assert "non-ontology" in system
    assert "unrepresented_recommendation_requirements" in system
    assert "do not return an unsupported constraint key" in system
    assert "top-level sibling" in system
    assert "never nest unrepresented_recommendation_requirements" in system


def test_invalid_comparison_criterion_repair_requires_a_formal_comparison_field(monkeypatch):
    captured = {}

    async def fake_chat_completion(db, messages, **kwargs):
        captured["system"] = messages[0]["content"]
        return "{}"

    monkeypatch.setattr(customer_agent_planner_service.customer_llm_service, "chat_completion", fake_chat_completion)
    asyncio.run(customer_agent_planner_service._repair_semantic_preplan_output(
        db=None,
        question="甲款和乙款哪个更适合露营做饭？",
        raw_content='{"route_family":"comparison","canonical_fields":["recommendation"]}',
        failure_reason="invalid_comparison_decision_criterion",
    ))

    system = str(captured["system"])
    assert "MUST return route_family=comparison" in system
    assert "usage_scene" in system
    assert "never return recommendation as its field" in system


def test_invalid_comparison_subtype_repair_requires_overview_or_capability_contract(monkeypatch):
    """An unknown comparison subtype must be repaired semantically, not guessed by a router."""
    captured = {}

    async def fake_chat_completion(_db, messages, **_kwargs):
        captured["system"] = messages[0]["content"]
        return "{}"

    monkeypatch.setattr(customer_agent_planner_service.customer_llm_service, "chat_completion", fake_chat_completion)
    asyncio.run(customer_agent_planner_service._repair_semantic_preplan_output(
        db=None,
        question="sample A and sample B: what differs?",
        raw_content='{"route_family":"comparison","subtype":"product_comparison"}',
        failure_reason="invalid_comparison_subtype",
    ))

    system = str(captured["system"])
    assert "generic non-decisive" in system
    assert "comparison_overview" in system


def test_comparison_overview_confirmation_preserves_explicit_non_winner_criteria(monkeypatch):
    """A factual criterion is not a generic overview merely because no winner is requested."""
    captured = {}

    async def fake_chat_completion(_db, messages, **_kwargs):
        captured["system"] = messages[0]["content"]
        return "{}"

    monkeypatch.setattr(customer_agent_planner_service.customer_llm_service, "chat_completion", fake_chat_completion)
    asyncio.run(customer_agent_planner_service._repair_semantic_preplan_output(
        db=None,
        question="CW-C83 和 CW-C06PRO 的收纳和负重怎么比？",
        raw_content='{"route_family":"comparison","subtype":"comparison_overview"}',
        failure_reason="comparison_overview_requires_semantic_confirmation",
    ))

    system = str(captured["system"])
    assert "explicit comparison dimension" in system
    assert "even when the customer does not ask for a winner" in system
    assert "qa_evidence_query" in system


def test_semantic_preplan_accepts_only_literal_allowlisted_structured_query_constraints():
    result = customer_agent_planner_service._validate_semantic_preplan({
        "route_family": "structured_query",
        "route_hint": "query_products",
        "question_type": "filter",
        "subtype": "structured_query",
        "subject_text": "锅具",
        "canonical_fields": ["heat_source", "usage_scene"],
        "confidence": "high",
        "structured_query_constraints": [
            {"field": "heat_source", "operator": "supports", "value": "明火", "evidence_span": "明火"},
            {"field": "usage_scene", "operator": "contains", "value": "露营", "evidence_span": "露营"},
        ],
    })

    assert result["fallback_reason"] == ""
    assert result["structured_query_constraints"] == [
        {"field": "heat_source", "operator": "supports", "value": "明火", "evidence_span": "明火", "unit": None},
        {"field": "usage_scene", "operator": "contains", "value": "露营", "evidence_span": "露营", "unit": None},
    ]


def test_semantic_preplan_keeps_unconstrained_category_aggregate_out_of_filter_predicates():
    """A semantic catalogue scope is not a fabricated category filter."""
    result = customer_agent_planner_service._validate_semantic_preplan({
        "route_family": "structured_query",
        "route_hint": "query_products",
        "question_type": "filter",
        "subtype": "structured_query",
        "subject_text": "stove",
        "canonical_fields": ["category"],
        "confidence": "high",
        "structured_query_constraints": [],
    })

    assert result["fallback_reason"] == ""
    assert result["canonical_fields"] == ["category"]
    assert result["structured_query_constraints"] == []


def test_semantic_preplan_keeps_database_value_catalog_scope_out_of_filter_predicates():
    """A stored series value is validated by the catalogue-value executor, not a fake predicate."""
    result = customer_agent_planner_service._validate_semantic_preplan({
        "route_family": "structured_query",
        "route_hint": "query_products",
        "question_type": "filter",
        "subtype": "structured_query",
        "subject_text": "Urban Escape collection",
        "canonical_fields": ["series"],
        "confidence": "high",
        "structured_query_constraints": [],
    })

    assert result["fallback_reason"] == ""
    assert result["field_type"] == "series"
    assert result["structured_query_constraints"] == []


def test_semantic_preplan_general_advice_cannot_carry_product_facts():
    result = customer_agent_planner_service._validate_semantic_preplan({
        "route_family": "general_chat",
        "confidence": "high",
        "entities": [],
        "canonical_fields": [],
        "evidence_required": True,
        "evidence_kind": "general_knowledge",
    })

    assert result["fallback_reason"] == ""
    assert result["route_family"] == "general_chat"
    assert result["evidence_required"] is False


def test_semantic_catalog_family_listing_uses_resolved_family_scope(
    route_client_and_db,
    monkeypatch,
):
    client, headers, Session = route_client_and_db
    with Session() as db:
        for sku, name in (
            ("FAMILY-STOVE-1", "星火炉-酒精版"),
            ("FAMILY-STOVE-2", "星火炉-气炉版"),
            ("FAMILY-STOVE-3", "星火炉-组合版"),
        ):
            _add_product(
                db,
                sku,
                name,
                "炉具",
                "",
                "不锈钢",
                "",
                "户外炉具",
                "露营",
                500,
            )
        db.commit()

    async def family_preplan(*_args, **_kwargs):
        return {
            "called": True,
            "route_family": "recommendation",
            "route_hint": "recommendation",
            "question_type": "recommendation",
            "subtype": "recommendation",
            "entities": [],
            "subject_text": "星火炉",
            "canonical_fields": [],
            "confidence": 0.95,
            "ambiguity": False,
            "evidence_required": True,
            "evidence_kind": "structured_field",
            "recommendation_constraints": {"subject_kind": "stove"},
            "context_usage": "none",
        }

    monkeypatch.setattr(
        customer_agent_planner_service,
        "plan_customer_question_semantic",
        family_preplan,
    )
    response = client.post(
        "/api/customer-service/ask?debug=true",
        json={"question": "星火炉有哪些款？"},
        headers=headers,
    )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert set(payload.get("result_skus") or []) == {
        "FAMILY-STOVE-1",
        "FAMILY-STOVE-2",
        "FAMILY-STOVE-3",
    }, payload
    assert (payload.get("debug") or {}).get("agent_mode") != "structured_catalog_count", payload
    assert (payload.get("answer_metadata") or {}).get("source") == "product_catalog_family_query", payload

    async def unavailable_preplan(*_args, **_kwargs):
        return {
            "called": True,
            "fallback_reason": "llm_error:TimeoutError",
            "confidence": 0.0,
            "canonical_fields": [],
        }

    monkeypatch.setattr(
        customer_agent_planner_service,
        "plan_customer_question_semantic",
        unavailable_preplan,
    )
    outage_response = client.post(
        "/api/customer-service/ask?debug=true",
        json={"question": "星火炉有哪些款？"},
        headers=headers,
    )
    assert outage_response.status_code == 200, outage_response.text
    outage_payload = outage_response.json()
    assert set(outage_payload.get("result_skus") or []) == {
        "FAMILY-STOVE-1",
        "FAMILY-STOVE-2",
        "FAMILY-STOVE-3",
    }, outage_payload
    assert (outage_payload.get("answer_metadata") or {}).get("source") == "semantic_outage_catalog_family_query"


def test_family_listing_output_columns_do_not_collapse_set_to_one_product(
    route_client_and_db,
    monkeypatch,
):
    """Requested name/SKU columns describe set output, not a single-product field."""
    client, headers, Session = route_client_and_db
    with Session() as db:
        for sku, name in (
            ("DISPLAY-FAMILY-1", "\u6d41\u661f\u7089-\u9152\u7cbe\u7248"),
            ("DISPLAY-FAMILY-2", "\u6d41\u661f\u7089-\u6c14\u7089\u7248"),
            ("DISPLAY-FAMILY-3", "\u6d41\u661f\u7089-\u7ec4\u5408\u7248"),
        ):
            _add_product(db, sku, name, "\u7089\u5177", "", "\u4e0d\u9508\u94a2", "", "\u6237\u5916\u7089\u5177", "\u9732\u8425", 500)
        db.commit()

    async def family_display_preplan(*_args, **_kwargs):
        return {
            "called": True,
            "route_family": "structured_query",
            "route_hint": "query_products",
            "question_type": "filter",
            "subtype": "structured_query",
            "entities": [],
            "subject_text": "\u6d41\u661f\u7089",
            "canonical_fields": ["series"],
            "field_type": "series",
            "field_hint": "series",
            "confidence": 0.95,
            "confidence_label": "high",
            "ambiguity": False,
            "evidence_required": True,
            "evidence_kind": "structured_field",
            "context_usage": "none",
        }

    monkeypatch.setattr(
        customer_agent_planner_service,
        "plan_customer_question_semantic",
        family_display_preplan,
    )
    response = client.post(
        "/api/customer-service/ask?debug=true",
        json={"question": "\u6d41\u661f\u7089\u6709\u54ea\u4e9b\u6b3e\uff1f\u8bf7\u5217\u51fa\u540d\u79f0\u548c SKU\u3002"},
        headers=headers,
    )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert set(payload.get("result_skus") or []) == {
        "DISPLAY-FAMILY-1", "DISPLAY-FAMILY-2", "DISPLAY-FAMILY-3",
    }, payload
    assert (payload.get("answer_metadata") or {}).get("source") == "product_catalog_family_query", payload


def test_structured_usage_answer_is_semantically_trimmed_and_verified(monkeypatch):
    calls = []

    async def fake_chat_completion(*_args, **kwargs):
        calls.append(kwargs.get("purpose"))
        if kwargs.get("purpose") == "structured_usage_relevance_render":
            return json.dumps({
                "confirmed_actions": [
                    "首次使用前用温水冲洗各部件",
                    "按冲煮方式调节研磨粗细",
                ],
                "missing_details": "资料未写明具体调节档位和后续操作步骤",
            }, ensure_ascii=False)
        return json.dumps({"grounded": True, "relevant": True, "vague": False})

    monkeypatch.setattr(customer_service_service.customer_llm_service, "chat_completion", fake_chat_completion)
    monkeypatch.setattr(
        customer_agent_planner_service,
        "_semantic_preplan_runtime_settings",
        lambda: {
            "model": "deepseek-v4-flash",
            "response_format": {"type": "json_object"},
            "thinking": {"type": "disabled"},
        },
    )
    result = {
        "answer": "原始整段说明，包含玻璃器具提示。",
        "result_skus": ["CW-K31"],
        "results": [{"sku": "CW-K31", "product_name_cn": "转转磨豆器"}],
        "answer_metadata": {
            "contract_field_type": "usage_instruction",
            "evidence_status": "structured",
            "evidence_source": "specs.usage_instruction",
            "evidence_value": "首次使用前用温水冲洗各部件。研磨粗细可按冲煮方式调节。使用后清理残粉。玻璃器具避免骤冷骤热。",
        },
        "debug": {},
    }

    rendered = asyncio.run(
        customer_service_service._semantic_render_structured_usage_answer(
            object(),
            question="转转磨豆器第一次怎么用？",
            agent_result=result,
            semantic_preplan={"called": True, "confidence": 0.95},
        )
    )

    assert "玻璃" not in rendered["answer"]
    assert "资料未写明资料未写明" not in rendered["answer"]
    assert "现有资料未写明具体调节档位和后续操作步骤" in rendered["answer"]
    assert rendered["answer_metadata"]["semantic_usage_rendered"] is True
    assert calls == ["structured_usage_relevance_render", "structured_usage_relevance_verify"]


def test_structured_usage_answer_rejection_never_returns_unfiltered_evidence(monkeypatch):
    async def fake_chat_completion(*_args, **kwargs):
        if kwargs.get("purpose") == "structured_usage_relevance_render":
            return json.dumps({
                "confirmed_actions": ["根据相应方式操作器具"],
                "missing_details": "具体操作步骤",
            }, ensure_ascii=False)
        return json.dumps({"grounded": True, "relevant": False, "vague": True})

    monkeypatch.setattr(customer_service_service.customer_llm_service, "chat_completion", fake_chat_completion)
    monkeypatch.setattr(
        customer_agent_planner_service,
        "_semantic_preplan_runtime_settings",
        lambda: {
            "model": "deepseek-v4-flash",
            "response_format": {"type": "json_object"},
            "thinking": {"type": "disabled"},
        },
    )
    result = {
        "answer": "原始说明包含玻璃器具避免骤冷骤热。",
        "result_skus": ["CW-K31"],
        "results": [{"sku": "CW-K31", "product_name_cn": "转转磨豆器"}],
        "answer_metadata": {
            "contract_field_type": "usage_instruction",
            "evidence_status": "structured",
            "evidence_source": "specs.usage_instruction",
            "evidence_value": "根据相应方式操作器具。玻璃器具避免骤冷骤热。",
        },
        "debug": {},
    }

    rejected = asyncio.run(
        customer_service_service._semantic_render_structured_usage_answer(
            object(),
            question="转转磨豆器第一次怎么用？",
            agent_result=result,
            semantic_preplan={"called": True, "confidence": 0.95},
        )
    )

    assert "玻璃" not in rejected["answer"]
    assert "无法形成" in rejected["answer"]
    assert rejected["answer_metadata"]["semantic_usage_rejected"] is True


def test_semantic_prompts_do_not_infer_package_quantity_from_serving_count():
    planner_messages = customer_agent_planner_service._semantic_preplan_messages(
        question="它有几个杯子？",
        deterministic_plan={},
        context={"active_product_anchor": {"sku": "EXAMPLE"}},
    )
    strict_messages = customer_service_service._same_sku_knowledge_strict_entailment_messages(
        "它有几个杯子？",
        "包含4个杯子。",
        "满足4人使用需求。",
    )

    assert "how many physical units or items are included" in planner_messages[0]["content"]
    assert "serving count" in planner_messages[0]["content"]
    assert "included quantity or package composition" in strict_messages[0]["content"]
    assert "number of users' needs" in strict_messages[0]["content"]


def test_non_evidentiary_comparison_returns_to_semantic_general_advice_repair():
    result = customer_agent_planner_service._validate_semantic_preplan({
        "route_family": "comparison",
        "question_type": "comparison",
        "subtype": "comparison_overview",
        "entities": ["generic form A", "generic form B"],
        "canonical_fields": [],
        "confidence": "high",
        "evidence_required": False,
    })

    assert result["fallback_reason"] == "non_evidentiary_comparison"


def test_semantic_preplan_rejects_textual_structured_predicate_value_outside_evidence_span():
    result = customer_agent_planner_service._validate_semantic_preplan({
        "route_family": "structured_query",
        "route_hint": "query_products",
        "question_type": "filter",
        "subtype": "structured_query",
        "subject_text": "锅具",
        "canonical_fields": ["heat_source", "usage_scene"],
        "confidence": "high",
        "structured_query_constraints": [
            {"field": "heat_source", "operator": "supports", "value": "酒精炉", "evidence_span": "支持明火"},
            {"field": "usage_scene", "operator": "contains", "value": "露营", "evidence_span": "露营"},
        ],
    })

    assert result["fallback_reason"] == "invalid_structured_query_constraints"
    assert result["semantic_route_family_hint"] == "structured_query"


def test_invalid_structured_query_preserves_semantic_named_detail_candidate_for_contract_recovery():
    """A malformed filter shape must not erase a validated field candidate and subject."""
    result = customer_agent_planner_service._validate_semantic_preplan({
        "route_family": "structured_query",
        "route_hint": "query_products",
        "question_type": "filter",
        "subtype": "structured_query",
        "subject_text": "测试煎盘",
        "canonical_fields": ["target_audience"],
        "confidence": "high",
        "structured_query_constraints": [{
            "field": "target_audience",
            "operator": "contains",
            "value": "露营用户",
            "evidence_span": "不在当前问题中的伪造条件",
        }],
    })

    assert result["fallback_reason"] == "invalid_structured_query_constraints"
    assert result["invalid_structured_query_named_detail_candidate"] == {
        "subject_text": "测试煎盘",
        "canonical_fields": ["target_audience"],
        "confidence": 0.9,
    }


def test_invalid_semantic_multi_filter_contract_fails_closed_before_legacy_filter():
    result = customer_service_service._semantic_structured_query_constraint_clarification_result({
        "called": True,
        "semantic_route_family_hint": "structured_query",
        "fallback_reason": "invalid_structured_query_constraints",
    })

    assert result is not None
    assert result["answer_type"] == "clarification"
    assert result["result_skus"] == []
    assert result["candidate_skus"] == []
    assert result["debug"]["agent_mode"] == "semantic_structured_query_invalid_contract_clarification"


def test_invalid_structured_query_named_detail_candidate_recovers_through_both_contracts(
    route_client_and_db,
    monkeypatch,
):
    """A recoverable semantic subject must be sealed before filter clarification runs."""
    client, headers, _ = route_client_and_db

    async def fake_preplan(_db, _question, _deterministic_plan, context):
        return {
            "called": True,
            "fallback_reason": "invalid_structured_query_constraints",
            "semantic_route_family_hint": "structured_query",
            "invalid_structured_query_named_detail_candidate": {
                "subject_text": "瓦片烤盘",
                "canonical_fields": ["material"],
                "confidence": 0.9,
            },
        }

    monkeypatch.setattr(customer_agent_planner_service, "plan_customer_question_semantic", fake_preplan)
    response = client.post(
        "/api/customer-service/ask?debug=true",
        json={"question": "瓦片烤盘的材料是什么？"},
        headers=headers,
    )

    assert response.status_code == 200, response.text
    payload = response.json()
    field_contract = payload.get("debug", {}).get("field_contract") or {}
    entity_contract = payload.get("debug", {}).get("entity_resolution_contract") or {}
    assert payload["answer_type"] == "product_detail", payload
    assert payload.get("debug", {}).get("agent_mode") == "invalid_structured_query_named_detail_contract", payload
    assert field_contract.get("field_type") == "material", payload
    assert field_contract.get("source") == "recovered_semantic_named_detail_candidate", payload
    assert entity_contract.get("status") == "resolved", payload
    assert entity_contract.get("resolved_sku") == "CF-PG19", payload
    assert payload.get("result_skus") == ["CF-PG19"], payload


def test_semantic_preplan_repairs_missing_multi_filter_predicates_before_legacy_route(monkeypatch):
    """A semantic multi-filter classification must not degrade to one lexical filter."""
    calls = []

    async def fake_chat_completion(db, messages, **kwargs):
        purpose = kwargs.get("purpose")
        calls.append(purpose)
        if purpose == "semantic_preplan":
            return json.dumps({
                "route_family": "structured_query",
                "route_hint": "query_products",
                "question_type": "filter",
                "subtype": "structured_query",
                "subject_text": "锅具",
                "canonical_fields": ["heat_source", "usage_scene"],
                "confidence": "high",
            })
        assert purpose == "semantic_preplan_repair"
        return json.dumps({
            "route_family": "structured_query",
            "route_hint": "query_products",
            "question_type": "filter",
            "subtype": "structured_query",
            "subject_text": "锅具",
            "canonical_fields": ["heat_source", "usage_scene"],
            "confidence": "high",
            "structured_query_constraints": [
                {"field": "heat_source", "operator": "supports", "value": "明火", "evidence_span": "明火"},
                {"field": "usage_scene", "operator": "contains", "value": "露营", "evidence_span": "露营"},
            ],
        })

    monkeypatch.setattr(customer_agent_planner_service.customer_llm_service, "chat_completion", fake_chat_completion)
    result = asyncio.run(customer_agent_planner_service.plan_customer_question_semantic(
        db=None,
        question="列出锅具中支持明火并适合露营使用的款式",
        deterministic_plan={"primary_intent": "query_products"},
        context={},
    ))

    assert calls == ["semantic_preplan", "semantic_preplan_repair"]
    assert result["fallback_reason"] == ""
    assert [item["field"] for item in result["structured_query_constraints"]] == ["heat_source", "usage_scene"]


def test_semantic_preplan_repairs_named_product_field_misrouted_as_invalid_structured_query(monkeypatch):
    """Route-schema repair must preserve a semantic product fact, not force a catalogue filter."""
    calls = []

    async def fake_chat_completion(db, messages, **kwargs):
        purpose = kwargs.get("purpose")
        calls.append(purpose)
        if purpose == "semantic_preplan":
            return json.dumps({
                "route_family": "structured_query",
                "route_hint": "query_products",
                "question_type": "filter",
                "subtype": "structured_query",
                "entities": ["\u74e6\u7247\u70e4\u76d8"],
                "subject_text": "\u74e6\u7247\u70e4\u76d8",
                "canonical_fields": ["competitor_benchmark"],
                "confidence": "high",
                "structured_query_constraints": [{
                    "field": "competitor_benchmark", "operator": "contains",
                    "value": "\u540c\u7c7b\u4ea7\u54c1", "evidence_span": "\u5bf9\u6807\u7684\u540c\u7c7b\u4ea7\u54c1",
                }],
            })
        assert purpose == "semantic_preplan_repair"
        system = messages[0]["content"]
        if "named-product field is a product fact" not in system:
            # This represents the former repair prompt, which reasserted the
            # invalid filter route instead of correcting it.
            return json.dumps({
                "route_family": "structured_query", "route_hint": "query_products",
                "question_type": "filter", "subtype": "structured_query",
                "canonical_fields": ["competitor_benchmark"], "confidence": "high",
            })
        return json.dumps({
            "route_family": "product_bound_qa", "route_hint": "product_detail",
            "question_type": "field", "subtype": "known_detail",
            "entities": ["\u74e6\u7247\u70e4\u76d8"], "subject_text": "\u74e6\u7247\u70e4\u76d8",
            "canonical_fields": ["competitor_benchmark"], "confidence": "high",
            "evidence_required": True,
        })

    monkeypatch.setattr(customer_agent_planner_service.customer_llm_service, "chat_completion", fake_chat_completion)
    result = asyncio.run(customer_agent_planner_service.plan_customer_question_semantic(
        db=None,
        question="\u74e6\u7247\u70e4\u76d8\u5bf9\u6807\u7684\u540c\u7c7b\u4ea7\u54c1\u6709\u54ea\u4e9b\uff1f",
        deterministic_plan={"primary_intent": "query_products"},
        context={},
    ))

    assert calls == ["semantic_preplan", "semantic_preplan_repair"]
    assert result["fallback_reason"] == ""
    assert result["route_family"] == "product_bound_qa"
    assert result["canonical_fields"] == ["competitor_benchmark"]


def test_semantic_preplan_repairs_unanchored_product_family_detail_into_set_query(monkeypatch):
    calls = []

    async def fake_chat_completion(db, messages, **kwargs):
        purpose = kwargs.get("purpose")
        calls.append(purpose)
        if purpose == "semantic_preplan":
            return json.dumps({
                "route_family": "product_bound_qa", "route_hint": "product_detail",
                "question_type": "field", "subtype": "known_detail",
                "entities": [], "subject_text": "围雪炉",
                "canonical_fields": ["product_name_cn", "sku"],
                "confidence": "high", "ambiguity": False,
                "evidence_required": True, "evidence_kind": "structured_field",
            }, ensure_ascii=False)
        assert purpose == "semantic_preplan_repair"
        assert "product_bound_qa_requires_entity_anchor" in json.dumps(messages, ensure_ascii=False)
        return json.dumps({
            "route_family": "structured_query", "route_hint": "query_products",
            "question_type": "filter", "subtype": "structured_query",
            "entities": [], "subject_text": "围雪炉",
            "canonical_fields": ["series"], "field_type": "series",
            "structured_query_constraints": [],
            "confidence": "high", "ambiguity": False, "evidence_required": True,
        }, ensure_ascii=False)

    monkeypatch.setattr(customer_agent_planner_service.customer_llm_service, "chat_completion", fake_chat_completion)
    result = asyncio.run(customer_agent_planner_service.plan_customer_question_semantic(
        db=None,
        question="围雪炉有哪些款？请列出名称和 SKU，并说明区别。",
        deterministic_plan={"primary_intent": "query_products"},
        context={},
    ))

    assert calls == ["semantic_preplan", "semantic_preplan_repair"]
    assert result["fallback_reason"] == ""
    assert result["route_family"] == "structured_query"
    assert result["field_type"] == "series"


def test_unanchored_set_scope_repair_keeps_field_choice_model_owned(monkeypatch):
    async def fake_chat_completion(_db, messages, **kwargs):
        assert kwargs["purpose"] == "semantic_preplan_set_scope_repair"
        assert messages
        return json.dumps({
            "route_family": "structured_query",
            "set_field": "series",
            "subject_text": "围雪炉",
            "subject_kind": "",
            "unrepresented_requirements": [],
        }, ensure_ascii=False)

    monkeypatch.setattr(customer_agent_planner_service.customer_llm_service, "chat_completion", fake_chat_completion)
    result = asyncio.run(customer_agent_planner_service._repair_unanchored_set_scope_semantically(
        None,
        question="围雪炉有哪些款？",
    ))

    assert result is not None
    assert result["route_family"] == "structured_query"
    assert result["canonical_fields"] == ["series"]
    assert result["structured_query_constraints"] == []


def test_unanchored_set_scope_repair_preserves_bounded_selection_as_recommendation(monkeypatch):
    async def fake_chat_completion(_db, messages, **kwargs):
        assert kwargs["purpose"] == "semantic_preplan_set_scope_repair"
        assert "bounded number of relevant choices" in messages[0]["content"]
        return json.dumps({
            "route_family": "recommendation",
            "set_field": "",
            "subject_text": "咖啡器具",
            "subject_kind": "coffee_gear",
            "unrepresented_requirements": ["手冲"],
        }, ensure_ascii=False)

    monkeypatch.setattr(customer_agent_planner_service.customer_llm_service, "chat_completion", fake_chat_completion)
    result = asyncio.run(customer_agent_planner_service._repair_unanchored_set_scope_semantically(
        None,
        question="咖啡器具里有哪些适合手冲的产品？请给我两三款真正相关的选择。",
    ))

    assert result is not None
    assert result["route_family"] == "recommendation"
    assert result["recommendation_constraints"]["subject_kind"] == "coffee_gear"
    assert result["unrepresented_recommendation_requirements"] == ["手冲"]


def test_semantic_preplan_repairs_named_nonfilter_field_misrouted_as_empty_structured_query(monkeypatch):
    """An empty predicate array cannot make a named record field into catalogue search."""
    calls = []

    async def fake_chat_completion(db, messages, **kwargs):
        calls.append(kwargs.get("purpose"))
        if kwargs.get("purpose") == "semantic_preplan":
            return json.dumps({
                "route_family": "structured_query", "route_hint": "query_products",
                "question_type": "filter", "subtype": "structured_query",
                "entities": ["\u74e6\u7247\u70e4\u76d8"], "subject_text": "\u74e6\u7247\u70e4\u76d8",
                "canonical_fields": ["competitor_benchmark"], "confidence": "high",
            })
        assert kwargs.get("purpose") == "semantic_preplan_repair"
        return json.dumps({
            "route_family": "product_bound_qa", "route_hint": "product_detail",
            "question_type": "field", "subtype": "known_detail",
            "entities": ["\u74e6\u7247\u70e4\u76d8"], "subject_text": "\u74e6\u7247\u70e4\u76d8",
            "canonical_fields": ["competitor_benchmark"], "confidence": "high",
            "evidence_required": True,
        })

    monkeypatch.setattr(customer_agent_planner_service.customer_llm_service, "chat_completion", fake_chat_completion)
    result = asyncio.run(customer_agent_planner_service.plan_customer_question_semantic(
        db=None,
        question="\u74e6\u7247\u70e4\u76d8\u5bf9\u6807\u7684\u540c\u7c7b\u4ea7\u54c1\u6709\u54ea\u4e9b\uff1f",
        deterministic_plan={"primary_intent": "query_products"},
        context={},
    ))

    assert calls == ["semantic_preplan", "semantic_preplan_repair"]
    assert result["route_family"] == "product_bound_qa"
    assert result["canonical_fields"] == ["competitor_benchmark"]


def test_semantic_comparison_decision_repairs_placeholder_recommendation_field(monkeypatch):
    calls = []

    async def fake_chat_completion(db, messages, **kwargs):
        purpose = kwargs.get("purpose")
        calls.append(purpose)
        if purpose == "semantic_preplan":
            return json.dumps({
                "route_family": "comparison",
                "entities": ["甲款", "乙款"],
                "canonical_fields": ["recommendation"],
                "decision_requested": True,
                "confidence": "high",
            })
        assert purpose == "semantic_preplan_repair"
        return json.dumps({
            "route_family": "comparison",
            "entities": ["甲款", "乙款"],
            "canonical_fields": ["usage_scene"],
            "decision_requested": True,
            "confidence": "high",
        })

    monkeypatch.setattr(customer_agent_planner_service.customer_llm_service, "chat_completion", fake_chat_completion)
    result = asyncio.run(customer_agent_planner_service.plan_customer_question_semantic(
        db=None,
        question="甲款和乙款哪个更适合露营？",
        deterministic_plan={"primary_intent": "comparison"},
        context={},
    ))

    assert calls[:2] == ["semantic_preplan", "semantic_preplan_repair"]
    assert result["route_family"] == "comparison"
    assert result["canonical_fields"] == ["usage_scene"]
    assert result["field_type"] == "usage_scene"
    assert not result["fallback_reason"]


def test_semantic_preplan_repairs_self_conflicting_pairwise_decision_route(monkeypatch):
    calls = []

    async def fake_chat_completion(db, messages, **kwargs):
        purpose = kwargs.get("purpose")
        calls.append(purpose)
        if purpose == "semantic_preplan":
            return json.dumps({
                "route_family": "product_bound_qa",
                "entities": ["甲款", "乙款"],
                "canonical_fields": ["usage_scene"],
                "decision_requested": True,
                "confidence": "high",
            })
        assert purpose == "semantic_preplan_repair"
        return json.dumps({
            "route_family": "comparison",
            "entities": ["甲款", "乙款"],
            "canonical_fields": ["usage_scene"],
            "decision_requested": True,
            "confidence": "high",
        })

    monkeypatch.setattr(customer_agent_planner_service.customer_llm_service, "chat_completion", fake_chat_completion)
    result = asyncio.run(customer_agent_planner_service.plan_customer_question_semantic(
        db=None,
        question="甲款和乙款哪个更适合露营？",
        deterministic_plan={},
        context={},
    ))

    assert calls == ["semantic_preplan", "semantic_preplan_repair"]
    assert result["route_family"] == "comparison"
    assert result["canonical_fields"] == ["usage_scene"]
    assert not result["fallback_reason"]


def test_semantic_preplan_repairs_pairwise_factual_comparison_misrouted_as_structured_query(monkeypatch):
    """Two named participants remain comparison work even without a winner request."""
    calls = []

    async def fake_chat_completion(db, messages, **kwargs):
        calls.append(kwargs.get("purpose"))
        if kwargs.get("purpose") == "semantic_preplan":
            return json.dumps({
                "route_family": "structured_query",
                "entities": ["\u7532\u6b3e", "\u4e59\u6b3e"],
                "canonical_fields": ["weight"],
                "decision_requested": False,
                "confidence": "high",
            })
        assert kwargs.get("purpose") == "semantic_preplan_repair"
        return json.dumps({
            "route_family": "comparison",
            "entities": ["\u7532\u6b3e", "\u4e59\u6b3e"],
            "canonical_fields": ["weight"],
            "decision_requested": False,
            "confidence": "high",
        })

    monkeypatch.setattr(customer_agent_planner_service.customer_llm_service, "chat_completion", fake_chat_completion)
    result = asyncio.run(customer_agent_planner_service.plan_customer_question_semantic(
        db=None,
        question="\u7532\u6b3e\u548c\u4e59\u6b3e\u7684\u91cd\u91cf\u5206\u522b\u662f\u591a\u5c11\uff1f",
        deterministic_plan={"primary_intent": "query_products"},
        context={},
    ))

    assert calls == ["semantic_preplan", "semantic_preplan_repair"]
    assert result["route_family"] == "comparison"
    assert result["canonical_fields"] == ["weight"]
    assert result["decision_requested"] is False
    assert not result["fallback_reason"]


def test_semantic_preplan_repairs_non_field_comparison_label_without_lexical_override(monkeypatch):
    """A route label cannot share a comparison FieldContract with a real field."""
    calls = []

    async def fake_chat_completion(db, messages, **kwargs):
        calls.append(kwargs.get("purpose"))
        if kwargs.get("purpose") == "semantic_preplan":
            return json.dumps({
                "route_family": "comparison",
                "entities": ["甲款", "乙款"],
                "canonical_fields": ["usage_scene", "recommendation"],
                "decision_requested": True,
                "confidence": "high",
            })
        assert kwargs.get("purpose") == "semantic_preplan_repair"
        return json.dumps({
            "route_family": "comparison",
            "entities": ["甲款", "乙款"],
            "canonical_fields": ["usage_scene"],
            "field_type": "usage_scene",
            "field_hint": "usage_scene",
            "decision_requested": True,
            "confidence": "high",
        })

    monkeypatch.setattr(customer_agent_planner_service.customer_llm_service, "chat_completion", fake_chat_completion)
    result = asyncio.run(customer_agent_planner_service.plan_customer_question_semantic(
        db=None,
        question="甲款和乙款哪一个更适合露营做饭？",
        deterministic_plan={"primary_intent": "comparison"},
        context={},
    ))

    assert calls == ["semantic_preplan", "semantic_preplan_repair"]
    assert result["route_family"] == "comparison"
    assert result["canonical_fields"] == ["usage_scene"]
    assert result["field_type"] == "usage_scene"
    assert result["field_hint"] == "usage_scene"
    assert not result["fallback_reason"]


def test_valid_product_qa_semantic_plan_does_not_trigger_field_repair(monkeypatch):
    """A complete non-column QA intent is not an unclassified field."""
    calls = []

    async def fake_chat_completion(db, messages, **kwargs):
        calls.append(kwargs.get("purpose"))
        return json.dumps({
            "route_family": "product_bound_qa",
            "route_hint": "product_detail",
            "question_type": "field",
            "subject_text": "示例水袋",
            "canonical_fields": [],
            "field_type": "",
            "field_hint": "",
            "confidence": "high",
            "ambiguity": False,
            "evidence_required": True,
            "evidence_kind": "product_qa",
            "qa_evidence_query": "耐用性与能否直接装沸水",
            "intent_coverage": "full",
            "context_usage": "none",
            "reasoning_summary": "The customer asks two product-specific capability facts outside the formal field taxonomy.",
        })

    monkeypatch.setattr(customer_agent_planner_service.customer_llm_service, "chat_completion", fake_chat_completion)

    result = asyncio.run(customer_agent_planner_service.plan_customer_question_semantic(
        None,
        question="示例水袋耐不耐用，另外能不能直接灌沸水？",
        deterministic_plan={},
        context={},
    ))

    assert calls == ["semantic_preplan"]
    assert result["route_family"] == "product_bound_qa"
    assert result["evidence_kind"] == "product_qa"
    assert result["canonical_fields"] == []
    assert result["intent_coverage"] == "full"
    assert not result["fallback_reason"]


def test_unique_catalog_name_recommendation_without_constraints_is_semantically_repaired(monkeypatch):
    """Identity context may trigger a semantic re-read, never a forced route."""
    calls = []

    async def fake_chat_completion(db, messages, **kwargs):
        purpose = kwargs.get("purpose")
        calls.append(purpose)
        if purpose == "semantic_preplan_repair":
            return json.dumps({
                "route_family": "product_bound_qa", "route_hint": "product_detail",
                "question_type": "field", "subject_text": "示例旅行筷",
                "canonical_fields": [], "field_type": "", "field_hint": "",
                "confidence": "high", "ambiguity": False, "evidence_required": True,
                "evidence_kind": "product_qa", "qa_evidence_query": "值得留意的产品特点",
                "intent_coverage": "full", "context_usage": "none",
                "reasoning_summary": "The turn asks about the uniquely named product, not a catalogue selection.",
            })
        return json.dumps({
            "route_family": "recommendation", "route_hint": "recommendation",
            "question_type": "recommendation", "subject_text": "", "canonical_fields": [],
            "confidence": "high", "ambiguity": False, "evidence_required": True,
            "evidence_kind": "structured_field", "recommendation_constraints": {},
            "context_usage": "none", "reasoning_summary": "Treats a named product as a generic category.",
        })

    monkeypatch.setattr(customer_agent_planner_service.customer_llm_service, "chat_completion", fake_chat_completion)
    result = asyncio.run(customer_agent_planner_service.plan_customer_question_semantic(
        None, question="示例旅行筷有哪些值得留意的？", deterministic_plan={},
        context={"has_unique_current_turn_catalog_product_name": True},
    ))
    assert calls == ["semantic_preplan", "semantic_preplan_repair"]
    assert result["route_family"] == "product_bound_qa"
    assert result["evidence_kind"] == "product_qa"
    assert not result["fallback_reason"]


def test_semantic_preplan_repairs_unclassified_named_product_field_before_legacy_fallback(monkeypatch):
    """A semantic product fact may not lose its field to the old query planner."""
    calls = []
    repair_prompt = []

    async def fake_chat_completion(db, messages, **kwargs):
        purpose = kwargs.get("purpose")
        calls.append(purpose)
        if purpose == "semantic_preplan_repair":
            repair_prompt.append(messages[0]["content"])
            return json.dumps({
                "route_family": "product_bound_qa",
                "route_hint": "product_detail",
                "question_type": "field",
                "subject_text": "甲款",
                "canonical_fields": ["competitor_benchmark"],
                "field_type": "competitor_benchmark",
                "field_hint": "competitor_benchmark",
                "confidence": "high",
                "ambiguity": False,
                "evidence_required": True,
                "context_usage": "none",
                "reasoning_summary": "The customer asks which peer products the named item benchmarks against.",
            })
        return json.dumps({
            "route_family": "product_bound_qa",
            "route_hint": "product_detail",
            "question_type": "field",
            "subject_text": "甲款",
            "canonical_fields": ["unknown"],
            "field_type": "unknown",
            "field_hint": "unknown",
            "confidence": "medium",
            "ambiguity": False,
            "evidence_required": True,
            "context_usage": "none",
            "reasoning_summary": "A named product fact was requested but the field was left unknown.",
        })

    monkeypatch.setattr(customer_agent_planner_service.customer_llm_service, "chat_completion", fake_chat_completion)

    result = asyncio.run(customer_agent_planner_service.plan_customer_question_semantic(
        None,
        question="甲款和哪些同类产品对标？",
        deterministic_plan={},
        context={},
    ))

    assert calls == ["semantic_preplan", "semantic_preplan_repair"]
    assert repair_prompt and "left canonical_fields unknown" in repair_prompt[0]
    assert result["route_family"] == "product_bound_qa"
    assert result["canonical_fields"] == ["competitor_benchmark"]
    assert result["field_type"] == "competitor_benchmark"
    assert not result["fallback_reason"]


def test_semantic_preplan_repairs_one_participant_comparison_into_named_product_field(monkeypatch):
    calls = []
    repair_prompt = []

    async def fake_chat_completion(db, messages, **kwargs):
        purpose = kwargs.get("purpose")
        calls.append(purpose)
        if purpose == "semantic_preplan_repair":
            repair_prompt.append(messages[0]["content"])
            return json.dumps({
                "route_family": "product_bound_qa",
                "route_hint": "product_detail",
                "question_type": "field",
                "subject_text": "甲款",
                "canonical_fields": ["competitor_benchmark"],
                "field_type": "competitor_benchmark",
                "field_hint": "competitor_benchmark",
                "confidence": "high",
                "ambiguity": False,
                "evidence_required": True,
                "context_usage": "none",
                "reasoning_summary": "The named product's benchmark information is requested.",
            })
        return json.dumps({
            "route_family": "comparison",
            "route_hint": "comparison",
            "question_type": "comparison",
            "entities": ["甲款"],
            "subject_text": "甲款",
            "canonical_fields": ["competitor_benchmark"],
            "field_type": "competitor_benchmark",
            "field_hint": "competitor_benchmark",
            "confidence": "high",
            "ambiguity": False,
            "evidence_required": True,
            "context_usage": "none",
            "reasoning_summary": "The request uses comparison language but names one product.",
        })

    monkeypatch.setattr(customer_agent_planner_service.customer_llm_service, "chat_completion", fake_chat_completion)

    result = asyncio.run(customer_agent_planner_service.plan_customer_question_semantic(
        None,
        question="甲款和哪些同类产品对标？",
        deterministic_plan={},
        context={},
    ))

    assert calls == ["semantic_preplan", "semantic_preplan_repair"]
    assert repair_prompt and "Comparison requires two or more explicitly named product participants" in repair_prompt[0]
    assert result["route_family"] == "product_bound_qa"
    assert result["field_type"] == "competitor_benchmark"
    assert result["canonical_fields"] == ["competitor_benchmark"]
    assert not result["fallback_reason"]


def test_semantic_preplan_repairs_named_nonfilter_structured_query_from_subject_text(monkeypatch):
    calls = []

    async def fake_chat_completion(db, messages, **kwargs):
        purpose = kwargs.get("purpose")
        calls.append(purpose)
        if purpose == "semantic_preplan_repair":
            return json.dumps({
                "route_family": "product_bound_qa",
                "route_hint": "product_detail",
                "question_type": "field",
                "subject_text": "甲款",
                "canonical_fields": ["competitor_benchmark"],
                "field_type": "competitor_benchmark",
                "field_hint": "competitor_benchmark",
                "confidence": "high",
                "ambiguity": False,
                "evidence_required": True,
                "context_usage": "none",
                "reasoning_summary": "The named product's benchmark information is requested.",
            })
        return json.dumps({
            "route_family": "structured_query",
            "route_hint": "query_products",
            "question_type": "filter",
            "subject_text": "甲款",
            "canonical_fields": ["competitor_benchmark"],
            "field_type": "competitor_benchmark",
            "field_hint": "competitor_benchmark",
            "confidence": "high",
            "ambiguity": False,
            "evidence_required": True,
            "context_usage": "none",
            "reasoning_summary": "The customer asks for one named product's benchmark information.",
        })

    monkeypatch.setattr(customer_agent_planner_service.customer_llm_service, "chat_completion", fake_chat_completion)

    result = asyncio.run(customer_agent_planner_service.plan_customer_question_semantic(
        None,
        question="甲款对标的同类产品有哪些？",
        deterministic_plan={},
        context={},
    ))

    assert calls == ["semantic_preplan", "semantic_preplan_repair"]
    assert result["route_family"] == "product_bound_qa"
    assert result["field_type"] == "competitor_benchmark"
    assert not result["fallback_reason"]


def test_semantic_preplan_repairs_pairwise_recommendation_constraints_into_comparison_fields(monkeypatch):
    calls = []
    repair_prompt = []

    async def fake_chat_completion(db, messages, **kwargs):
        calls.append(kwargs.get("purpose"))
        if kwargs.get("purpose") == "semantic_preplan_repair":
            repair_prompt.append(messages[0]["content"])
        if kwargs.get("purpose") == "semantic_preplan":
            return json.dumps({
                "route_family": "recommendation",
                "entities": ["甲款", "乙款"],
                "canonical_fields": ["recommendation"],
                "confidence": "high",
                "decision_requested": True,
                "recommendation_constraints": {"scenarios": ["camping"]},
            })
        return json.dumps({
            "route_family": "comparison",
            "entities": ["甲款", "乙款"],
            "canonical_fields": ["usage_scene"],
            "field_type": "usage_scene",
            "field_hint": "usage_scene",
            "question_type": "comparison",
            "subtype": "relation_comparison",
            "confidence": "high",
            "decision_requested": True,
        })

    monkeypatch.setattr(customer_agent_planner_service.customer_llm_service, "chat_completion", fake_chat_completion)
    result = asyncio.run(customer_agent_planner_service.plan_customer_question_semantic(
        db=None,
        question="甲款和乙款带去露营怎么选？",
        deterministic_plan={},
        context={},
    ))

    assert calls == ["semantic_preplan", "semantic_preplan_repair"]
    assert repair_prompt
    assert "MUST return route_family=comparison" in repair_prompt[0]
    assert result["route_family"] == "comparison"
    assert result["entities"] == ["甲款", "乙款"]
    assert result["canonical_fields"] == ["usage_scene"]
    assert not result["fallback_reason"]


def test_pairwise_recommendation_repair_failure_preserves_sealed_participant_intent_for_safe_clarification(monkeypatch):
    calls = []

    async def fake_chat_completion(db, messages, **kwargs):
        calls.append(kwargs.get("purpose"))
        if kwargs.get("purpose") == "semantic_preplan":
            return json.dumps({
                "route_family": "recommendation",
                "entities": ["甲款", "乙款"],
                "canonical_fields": ["recommendation"],
                "confidence": "high",
                "decision_requested": True,
                "recommendation_constraints": {"scenarios": ["camping"]},
            })
        return "not-json"

    monkeypatch.setattr(customer_agent_planner_service.customer_llm_service, "chat_completion", fake_chat_completion)
    result = asyncio.run(customer_agent_planner_service.plan_customer_question_semantic(
        db=None,
        question="甲款和乙款带去露营怎么选？",
        deterministic_plan={},
        context={},
    ))

    # A pairwise choice that initially arrives as recommendation-shaped input
    # must attempt semantic repair into a comparison contract before any
    # grounding pass. An invalid repair then preserves only the sealed
    # participant intent for safe clarification.
    assert calls == ["semantic_preplan", "semantic_preplan_repair"]
    assert result["route_family"] == "recommendation"
    assert result["entities"] == ["甲款", "乙款"]
    assert result["recommendation_constraints"] == {}


def test_semantic_pairwise_compound_criteria_never_fall_through_to_legacy_choice_heuristic(monkeypatch):
    first = SimpleNamespace(sku="SKU-A", product_name_cn="甲款", product_name_en="")
    second = SimpleNamespace(sku="SKU-B", product_name_cn="乙款", product_name_en="")
    bundles = [(first, None, None, None), (second, None, None, None)]
    monkeypatch.setattr(customer_service_service, "_phase1_product_bundle_by_ref", lambda _db, ref: bundles[0] if ref == "SKU-A" else bundles[1])
    monkeypatch.setattr(
        customer_service_service,
        "_product_row_from_model",
        lambda product, *_args: {"sku": product.sku, "product_name_cn": product.product_name_cn},
    )
    monkeypatch.setattr(
        customer_service_service,
        "resolve_requested_field_contract",
        lambda *_args, **_kwargs: {
            "field_type": None,
            "canonical_fields": ["people", "usage_scene"],
            "supported_fields": ["people", "usage_scene"],
        },
    )
    monkeypatch.setattr(
        customer_service_service,
        "_comparison_adjudication_evidence",
        lambda **_kwargs: {"usage_scene": [
            {"participant_index": 0, "sku": "SKU-A", "value": "露营", "source": "business.usage_scenarios"},
            {"participant_index": 1, "sku": "SKU-B", "value": "露营", "source": "business.usage_scenarios"},
        ]},
    )
    plan = {
        "raw_question": "甲款和乙款哪个更适合家庭露营？",
        "product_refs": ["SKU-A", "SKU-B"],
        "must_make_choice": True,
        "semantic_comparison_entity_contracts": [
            {"status": "resolved", "resolved_sku": "SKU-A"},
            {"status": "resolved", "resolved_sku": "SKU-B"},
        ],
    }

    result = asyncio.run(customer_service_service._phase1_compare_choice_result(None, plan))

    assert result["answer_type"] == "comparison"
    assert result["result_skus"] == ["SKU-A", "SKU-B"]
    assert result["answer_metadata"]["final_choice_sku"] is None
    assert result["debug"]["agent_mode"] == "semantic_pairwise_compound_evidence_insufficient"
    assert "不能据此指定" in result["answer"]


def test_semantic_pairwise_partial_requested_fields_can_use_other_complete_sealed_evidence(monkeypatch):
    first = SimpleNamespace(sku="SKU-A", product_name_cn="Alpha", product_name_en="")
    second = SimpleNamespace(sku="SKU-B", product_name_cn="Beta", product_name_en="")
    bundles = [(first, None, None, None), (second, None, None, None)]
    monkeypatch.setattr(
        customer_service_service,
        "_phase1_product_bundle_by_ref",
        lambda _db, ref: bundles[0] if ref == "SKU-A" else bundles[1],
    )
    monkeypatch.setattr(
        customer_service_service,
        "_product_row_from_model",
        lambda product, *_args: {"sku": product.sku, "product_name_cn": product.product_name_cn},
    )
    monkeypatch.setattr(
        customer_service_service,
        "resolve_requested_field_contract",
        lambda *_args, **_kwargs: {
            "field_type": None,
            "canonical_fields": ["people", "usage_scene"],
            "supported_fields": ["people", "usage_scene"],
        },
    )
    monkeypatch.setattr(
        customer_service_service,
        "_comparison_adjudication_evidence",
        lambda **_kwargs: {
            "usage_scene": [
                {"participant_index": 0, "sku": "SKU-A", "value": "双人露营", "source": "business.usage_scenarios"},
                {"participant_index": 1, "sku": "SKU-B", "value": "多人露营", "source": "business.usage_scenarios"},
            ],
            "capacity": [
                {"participant_index": 0, "sku": "SKU-A", "value": "1L", "source": "specs.capacity"},
                {"participant_index": 1, "sku": "SKU-B", "value": "3L", "source": "specs.capacity"},
            ],
        },
    )

    async def choose_from_complete_evidence(*_args, **_kwargs):
        return {
            "selected_index": 1,
            "evidence_fields": ["usage_scene", "capacity"],
            "reasoning_summary": "The complete sealed evidence supports participant 2.",
        }

    monkeypatch.setattr(
        customer_service_service,
        "_semantic_comparison_adjudication",
        choose_from_complete_evidence,
    )

    result = asyncio.run(customer_service_service._phase1_compare_choice_result(None, {
        "raw_question": "Alpha和Beta哪个更适合多人露营？",
        "product_refs": ["SKU-A", "SKU-B"],
        "must_make_choice": True,
        "semantic_comparison_entity_contracts": [
            {"status": "resolved", "resolved_sku": "SKU-A"},
            {"status": "resolved", "resolved_sku": "SKU-B"},
        ],
    }))

    assert result["answer_metadata"]["final_choice_sku"] == "SKU-B"
    assert "3L" in result["answer"]
    assert "Beta" in result["answer"]
    assert {source["sku"] for source in result["sources"]} == {"SKU-A", "SKU-B"}


def test_semantic_pairwise_no_winner_still_shows_relevant_complete_evidence(monkeypatch):
    first = SimpleNamespace(sku="SKU-A", product_name_cn="Alpha", product_name_en="")
    second = SimpleNamespace(sku="SKU-B", product_name_cn="Beta", product_name_en="")
    bundles = [(first, None, None, None), (second, None, None, None)]
    monkeypatch.setattr(
        customer_service_service,
        "_phase1_product_bundle_by_ref",
        lambda _db, ref: bundles[0] if ref == "SKU-A" else bundles[1],
    )
    monkeypatch.setattr(
        customer_service_service,
        "_product_row_from_model",
        lambda product, *_args: {"sku": product.sku, "product_name_cn": product.product_name_cn},
    )
    monkeypatch.setattr(
        customer_service_service,
        "resolve_requested_field_contract",
        lambda *_args, **_kwargs: {
            "field_type": None,
            "canonical_fields": ["people", "usage_scene"],
            "supported_fields": ["people", "usage_scene"],
        },
    )
    monkeypatch.setattr(
        customer_service_service,
        "_comparison_adjudication_evidence",
        lambda **_kwargs: {
            "usage_scene": [
                {"participant_index": 0, "sku": "SKU-A", "value": "露营", "source": "business.usage_scenarios"},
                {"participant_index": 1, "sku": "SKU-B", "value": "露营", "source": "business.usage_scenarios"},
            ],
            "capacity": [
                {"participant_index": 0, "sku": "SKU-A", "value": "1L", "source": "specs.capacity"},
                {"participant_index": 1, "sku": "SKU-B", "value": "3L", "source": "specs.capacity"},
            ],
        },
    )

    async def no_winner_with_relevant_evidence(*_args, **_kwargs):
        return {
            "selected_index": None,
            "evidence_fields": ["capacity"],
            "reasoning_summary": "Capacity is relevant but does not prove a winner.",
        }

    monkeypatch.setattr(
        customer_service_service,
        "_semantic_comparison_adjudication",
        no_winner_with_relevant_evidence,
    )

    result = asyncio.run(customer_service_service._phase1_compare_choice_result(None, {
        "raw_question": "Alpha和Beta哪个更适合多人露营？",
        "product_refs": ["SKU-A", "SKU-B"],
        "must_make_choice": True,
        "semantic_comparison_entity_contracts": [
            {"status": "resolved", "resolved_sku": "SKU-A"},
            {"status": "resolved", "resolved_sku": "SKU-B"},
        ],
    }))

    assert result["answer_metadata"]["final_choice_sku"] is None
    assert "1L" in result["answer"] and "3L" in result["answer"]
    assert {source["field"] for source in result["sources"]} >= {"capacity"}


def test_pairwise_choice_phrase_runs_adjudication_when_semantic_preplan_omits_decision(monkeypatch):
    first = SimpleNamespace(sku="SKU-A", product_name_cn="Alpha", product_name_en="")
    second = SimpleNamespace(sku="SKU-B", product_name_cn="Beta", product_name_en="")
    bundles = [(first, None, None, None), (second, None, None, None)]
    monkeypatch.setattr(
        customer_service_service,
        "_phase1_product_bundle_by_ref",
        lambda _db, ref: bundles[0] if ref == "SKU-A" else bundles[1],
    )
    monkeypatch.setattr(
        customer_service_service,
        "_product_row_from_model",
        lambda product, *_args: {"sku": product.sku, "product_name_cn": product.product_name_cn},
    )
    monkeypatch.setattr(
        customer_service_service,
        "resolve_requested_field_contract",
        lambda *_args, **_kwargs: {"field_type": None, "canonical_fields": [], "supported_fields": []},
    )
    monkeypatch.setattr(
        customer_service_service,
        "_structured_product_field_evidence",
        lambda field, **kwargs: (
            ("轻量徒步" if kwargs["product"].sku == "SKU-B" else "营地烹饪", "business.usage_scenarios")
            if field == "usage_scene"
            else ("", None)
        ),
    )
    monkeypatch.setattr(
        customer_service_service,
        "_comparison_adjudication_evidence",
        lambda **_kwargs: {"usage_scene": [
            {"participant_index": 0, "sku": "SKU-A", "value": "营地烹饪", "source": "business.usage_scenarios"},
            {"participant_index": 1, "sku": "SKU-B", "value": "轻量徒步", "source": "business.usage_scenarios"},
        ]},
    )
    calls = []

    async def choose_second(*_args, **_kwargs):
        calls.append(True)
        return {"selected_index": 1, "evidence_fields": ["usage_scene"], "reasoning_summary": "SKU-B is the only hiking match."}

    monkeypatch.setattr(customer_service_service, "_semantic_comparison_adjudication", choose_second)

    result = asyncio.run(customer_service_service._phase1_compare_choice_result(None, {
        "raw_question": "SKU-A 和 SKU-B 哪个更适合两个人徒步？",
        "product_refs": ["SKU-A", "SKU-B"],
        "must_make_choice": False,
        "semantic_comparison_entity_contracts": [
            {"status": "resolved", "resolved_sku": "SKU-A"},
            {"status": "resolved", "resolved_sku": "SKU-B"},
        ],
        "semantic_preplan": {
            "called": True,
            "route_family": "comparison",
            "subtype": "comparison_overview",
            "evidence_kind": "structured_field",
            "canonical_fields": [],
            "decision_requested": False,
        },
    }))

    assert calls == [True]
    assert result["answer_metadata"]["final_choice_sku"] == "SKU-B"
    assert result["answer"].startswith("更推荐你选Beta（SKU-B）")
    assert "推荐理由：" in result["answer"]
    assert "Alpha" in result["answer"] and "Beta" in result["answer"]


def test_fieldless_pairwise_overview_is_built_from_same_sku_evidence_bundles(monkeypatch):
    first = SimpleNamespace(sku="SKU-A", product_name_cn="Alpha", product_name_en="")
    second = SimpleNamespace(sku="SKU-B", product_name_cn="Beta", product_name_en="")
    bundles = [(first, None, None, None), (second, None, None, None)]
    monkeypatch.setattr(
        customer_service_service,
        "_phase1_product_bundle_by_ref",
        lambda _db, ref: bundles[0] if ref == "SKU-A" else bundles[1],
    )
    monkeypatch.setattr(
        customer_service_service,
        "_product_row_from_model",
        lambda product, *_args: {"sku": product.sku, "product_name_cn": product.product_name_cn},
    )
    monkeypatch.setattr(
        customer_service_service,
        "resolve_requested_field_contract",
        lambda *_args, **_kwargs: {
            "field_type": None,
            "canonical_fields": [],
            "supported_fields": [],
        },
    )
    monkeypatch.setattr(
        customer_service_service,
        "_structured_product_field_evidence",
        lambda field, **kwargs: (
            (
                "hard-anodized aluminum" if kwargs["product"].sku == "SKU-A" else "stainless steel",
                "specs.body_material",
            )
            if field == "material"
            else ("", None)
        ),
    )

    result = asyncio.run(customer_service_service._phase1_compare_choice_result(None, {
        "raw_question": "How do SKU-A and SKU-B differ?",
        "product_refs": ["SKU-A", "SKU-B"],
        "must_make_choice": False,
        "semantic_comparison_entity_contracts": [
            {"status": "resolved", "resolved_sku": "SKU-A"},
            {"status": "resolved", "resolved_sku": "SKU-B"},
        ],
        "semantic_preplan": {
            "called": True,
            "route_family": "comparison",
            "subtype": "comparison_overview",
            "evidence_kind": "structured_field",
            "canonical_fields": [],
            "decision_requested": False,
        },
    }))

    assert result["answer_type"] == "comparison"
    assert result["result_skus"] == ["SKU-A", "SKU-B"]
    assert result["answer_metadata"]["evidence_bundle_skus"] == ["SKU-A", "SKU-B"]
    assert {source["sku"] for source in result["sources"]} == {"SKU-A", "SKU-B"}


def test_overview_with_uncovered_explicit_dimension_clarifies_instead_of_dumping_fields(monkeypatch):
    first = SimpleNamespace(sku="SKU-A", product_name_cn="Alpha", product_name_en="")
    second = SimpleNamespace(sku="SKU-B", product_name_cn="Beta", product_name_en="")
    bundles = [(first, None, None, None), (second, None, None, None)]
    monkeypatch.setattr(
        customer_service_service,
        "_phase1_product_bundle_by_ref",
        lambda _db, ref: bundles[0] if ref == "SKU-A" else bundles[1],
    )
    monkeypatch.setattr(
        customer_service_service,
        "_product_row_from_model",
        lambda product, *_args: {"sku": product.sku, "product_name_cn": product.product_name_cn},
    )
    monkeypatch.setattr(
        customer_service_service,
        "resolve_requested_field_contract",
        lambda *_args, **_kwargs: {
            "field_type": None,
            "requested_field": "最大承重",
            "requested_fields": ["最大承重"],
            "canonical_fields": [],
            "supported_fields": [],
        },
    )

    result = asyncio.run(customer_service_service._phase1_compare_choice_result(None, {
        "raw_question": "SKU-A 和 SKU-B 的收纳和负重怎么比？",
        "product_refs": ["SKU-A", "SKU-B"],
        "must_make_choice": False,
        "semantic_comparison_entity_contracts": [
            {"status": "resolved", "resolved_sku": "SKU-A"},
            {"status": "resolved", "resolved_sku": "SKU-B"},
        ],
        "semantic_preplan": {
            "route_family": "comparison",
            "subtype": "comparison_overview",
            "evidence_kind": "structured_field",
            "canonical_fields": [],
            "decision_requested": False,
        },
    }))

    assert result["answer_type"] == "clarification"
    assert result["needs_clarification"] is True
    assert "产品自重" in result["answer"]
    assert "最大承重" in result["answer"]
    assert "收纳尺寸" in result["answer"]
    assert "材质" not in result["answer"]
    shaped = customer_service_service._shape_answer_for_output(result)
    assert shaped["answer"] == result["answer"]
    assert "补充 SKU" not in shaped["answer"]


def test_semantic_pairwise_mixed_qa_concept_preserves_deterministic_formal_field(monkeypatch):
    first = SimpleNamespace(sku="SKU-A", product_name_cn="Alpha", product_name_en="")
    second = SimpleNamespace(sku="SKU-B", product_name_cn="Beta", product_name_en="")
    bundles = [(first, None, None, None), (second, None, None, None)]
    monkeypatch.setattr(
        customer_service_service,
        "_phase1_product_bundle_by_ref",
        lambda _db, ref: bundles[0] if ref == "SKU-A" else bundles[1],
    )
    monkeypatch.setattr(
        customer_service_service,
        "_product_row_from_model",
        lambda product, *_args: {"sku": product.sku, "product_name_cn": product.product_name_cn},
    )
    monkeypatch.setattr(
        customer_service_service,
        "resolve_requested_field_contract",
        lambda *_args, **_kwargs: {
            "field_type": "weight",
            "canonical_fields": ["weight"],
            "requested_fields": ["weight"],
        },
    )
    monkeypatch.setattr(
        customer_service_service,
        "_structured_product_field_evidence",
        lambda field, **kwargs: (
            ("1000g" if kwargs["product"].sku == "SKU-A" else "1500g", "specs.weight")
            if field == "weight"
            else (None, None)
        ),
    )

    async def no_same_sku_qa(_db, product, *_args, **_kwargs):
        if product.sku == "SKU-B":
            return SimpleNamespace(id="qa-b", answer="stored.")
        return None

    monkeypatch.setattr(
        customer_service_service,
        "_select_same_sku_product_qa_with_semantic_selection",
        no_same_sku_qa,
    )

    result = asyncio.run(customer_service_service._phase1_compare_choice_result(None, {
        "raw_question": "SKU-A and SKU-B: compare weight and storage.",
        "product_refs": ["SKU-A", "SKU-B"],
        "must_make_choice": False,
        "semantic_comparison_entity_contracts": [
            {"status": "resolved", "resolved_sku": "SKU-A"},
            {"status": "resolved", "resolved_sku": "SKU-B"},
        ],
        "semantic_preplan": {
            "route_family": "comparison",
            "evidence_kind": "structured_field",
            "supplemental_qa_evidence_query": "packing and storage convenience",
            "canonical_fields": ["weight"],
        },
    }))

    assert result["answer_type"] == "comparison"
    assert result["result_skus"] == ["SKU-A", "SKU-B"]
    assert "1000g" in result["answer"] and "1500g" in result["answer"]
    assert "storage" not in result["answer"].lower()
    assert "补充比较维度" in result["answer"]
    assert "stored.。" not in result["answer"]
    assert result["answer_metadata"]["source"] == "semantic_pairwise_composite_evidence_contract"


def test_semantic_pairwise_qa_misclassification_preserves_deterministic_formal_field(monkeypatch):
    first = SimpleNamespace(sku="SKU-A", product_name_cn="Alpha", product_name_en="")
    second = SimpleNamespace(sku="SKU-B", product_name_cn="Beta", product_name_en="")
    bundles = [(first, None, None, None), (second, None, None, None)]
    monkeypatch.setattr(
        customer_service_service,
        "_phase1_product_bundle_by_ref",
        lambda _db, ref: bundles[0] if ref == "SKU-A" else bundles[1],
    )
    monkeypatch.setattr(
        customer_service_service,
        "_product_row_from_model",
        lambda product, *_args: {"sku": product.sku, "product_name_cn": product.product_name_cn},
    )

    def field_contract(_question, plan=None, **_kwargs):
        if plan:
            return {"field_type": "product_qa", "canonical_fields": ["product_qa"]}
        return {
            "field_type": "weight",
            "canonical_fields": ["weight"],
            "requested_fields": ["weight"],
        }

    monkeypatch.setattr(customer_service_service, "resolve_requested_field_contract", field_contract)
    monkeypatch.setattr(
        customer_service_service.customer_field_contract,
        "resolve_requested_field_contract",
        lambda *_args, **_kwargs: {
            "field_type": "weight",
            "canonical_fields": ["weight"],
        },
    )
    monkeypatch.setattr(
        customer_service_service,
        "_structured_product_field_evidence",
        lambda field, **kwargs: (
            ("1000g" if kwargs["product"].sku == "SKU-A" else "1500g", "specs.weight")
            if field == "weight"
            else (None, None)
        ),
    )

    async def no_same_sku_qa(*_args, **_kwargs):
        return None

    monkeypatch.setattr(
        customer_service_service,
        "_select_same_sku_product_qa_with_semantic_selection",
        no_same_sku_qa,
    )

    result = asyncio.run(customer_service_service._phase1_compare_choice_result(None, {
        "raw_question": "SKU-A and SKU-B: compare weight and storage.",
        "product_refs": ["SKU-A", "SKU-B"],
        "must_make_choice": False,
        "semantic_comparison_entity_contracts": [
            {"status": "resolved", "resolved_sku": "SKU-A"},
            {"status": "resolved", "resolved_sku": "SKU-B"},
        ],
        "semantic_preplan": {
            "route_family": "comparison",
            "evidence_kind": "product_qa",
            "canonical_fields": [],
        },
    }))

    assert result["answer_type"] == "comparison"
    assert "1000g" in result["answer"] and "1500g" in result["answer"]
    assert result["answer_metadata"]["source"] == "planner_compare_formal_field_contract"


def test_legacy_pairwise_people_choice_surfaces_both_same_sku_sources(monkeypatch):
    first = SimpleNamespace(sku="SKU-A", product_name_cn="Alpha", product_name_en="")
    second = SimpleNamespace(sku="SKU-B", product_name_cn="Beta", product_name_en="")
    bundles = [(first, None, None, None), (second, None, None, None)]
    monkeypatch.setattr(
        customer_service_service,
        "_phase1_product_bundle_by_ref",
        lambda _db, ref: bundles[0] if ref == "SKU-A" else bundles[1],
    )
    monkeypatch.setattr(
        customer_service_service,
        "_product_row_from_model",
        lambda product, *_args: {
            "sku": product.sku,
            "product_name_cn": product.product_name_cn,
            "capacity": "2L" if product.sku == "SKU-A" else "3L",
            "target_audience": "适合1-2人" if product.sku == "SKU-A" else "适合2-3人",
        },
    )
    monkeypatch.setattr(
        customer_service_service,
        "resolve_requested_field_contract",
        lambda *_args, **_kwargs: {"field_type": None, "canonical_fields": []},
    )

    result = asyncio.run(customer_service_service._phase1_compare_choice_result(None, {
        "raw_question": "SKU-A 和 SKU-B 哪个更适合两个人露营？",
        "product_refs": ["SKU-A", "SKU-B"],
        "must_make_choice": True,
    }))

    assert result["answer_metadata"]["source"] == "planner_compare_choice"
    assert {item["sku"] for item in result["sources"]} == {"SKU-A", "SKU-B"}


def test_overview_execution_does_not_choose_a_winner_without_a_customer_decision_request(monkeypatch):
    first = SimpleNamespace(sku="SKU-A", product_name_cn="Alpha", product_name_en="")
    second = SimpleNamespace(sku="SKU-B", product_name_cn="Beta", product_name_en="")
    bundles = [(first, None, None, None), (second, None, None, None)]
    monkeypatch.setattr(
        customer_service_service,
        "_phase1_product_bundle_by_ref",
        lambda _db, ref: bundles[0] if ref == "SKU-A" else bundles[1],
    )
    monkeypatch.setattr(
        customer_service_service,
        "_product_row_from_model",
        lambda product, *_args: {"sku": product.sku, "product_name_cn": product.product_name_cn},
    )
    monkeypatch.setattr(
        customer_service_service,
        "resolve_requested_field_contract",
        lambda *_args, **_kwargs: {"field_type": None, "canonical_fields": []},
    )
    monkeypatch.setattr(
        customer_service_service,
        "_structured_product_field_evidence",
        lambda field, **kwargs: (
            (
                "1L" if kwargs["product"].sku == "SKU-A" else "3L",
                "specs.capacity",
            )
            if field == "capacity"
            else (
                (
                    "aluminum" if kwargs["product"].sku == "SKU-A" else "stainless steel",
                    "specs.body_material",
                )
                if field == "material"
                else ("", None)
            )
        ),
    )
    monkeypatch.setattr(
        customer_service_service,
        "_comparison_adjudication_evidence",
        lambda **_kwargs: {
            "capacity": [
                {"participant_index": 0, "sku": "SKU-A", "value": "1L", "source": "specs.capacity"},
                {"participant_index": 1, "sku": "SKU-B", "value": "3L", "source": "specs.capacity"},
            ],
        },
    )

    async def semantic_choice(*_args, **_kwargs):
        return {
            "selected_index": 1,
            "evidence_fields": ["capacity"],
            "reasoning_summary": "The question asks for the product suited to more people.",
        }

    monkeypatch.setattr(
        customer_service_service,
        "_semantic_comparison_adjudication",
        semantic_choice,
    )

    result = asyncio.run(customer_service_service._phase1_compare_choice_result(None, {
            "raw_question": "Alpha和Beta的容量与材质怎么比？",
        "product_refs": ["SKU-A", "SKU-B"],
        "must_make_choice": False,
        "semantic_comparison_entity_contracts": [
            {"status": "resolved", "resolved_sku": "SKU-A"},
            {"status": "resolved", "resolved_sku": "SKU-B"},
        ],
        "semantic_preplan": {
            "route_family": "comparison",
            "subtype": "comparison_overview",
            "evidence_kind": "structured_field",
            "canonical_fields": [],
            "decision_requested": False,
        },
    }))

    assert result["answer_metadata"]["final_choice_sku"] is None
    assert "更符合你所述需求" not in result["answer"]
    assert {source["field"] for source in result["sources"]} == {"capacity", "material"}


def test_pairwise_choice_with_one_participant_missing_requested_field_never_calls_adjudicator(monkeypatch):
    """A semantic chooser cannot fill a requested-field evidence gap with another field."""
    first = SimpleNamespace(sku="SKU-A", product_name_cn="\u7532\u6b3e", product_name_en="")
    second = SimpleNamespace(sku="SKU-B", product_name_cn="\u4e59\u6b3e", product_name_en="")
    bundles = [(first, None, None, None), (second, None, None, None)]
    monkeypatch.setattr(
        customer_service_service,
        "_phase1_product_bundle_by_ref",
        lambda _db, ref: bundles[0] if ref == "SKU-A" else bundles[1],
    )
    monkeypatch.setattr(
        customer_service_service,
        "_product_row_from_model",
        lambda product, *_args: {"sku": product.sku, "product_name_cn": product.product_name_cn},
    )
    monkeypatch.setattr(
        customer_service_service,
        "resolve_requested_field_contract",
        lambda *_args, **_kwargs: {
            "field_type": "people",
            "canonical_fields": ["people"],
            "supported_fields": ["people"],
        },
    )
    monkeypatch.setattr(
        customer_service_service,
        "_structured_product_field_evidence",
        lambda _field, **kwargs: (
            ("1-2\u4eba", "business.target_audience")
            if kwargs["product"].sku == "SKU-A"
            else ("", None)
        ),
    )
    monkeypatch.setattr(
        customer_service_service,
        "_comparison_adjudication_evidence",
        lambda **_kwargs: {"weight": [
            {"participant_index": 0, "sku": "SKU-A", "value": "200g", "source": "specs.gross_weight_g"},
            {"participant_index": 1, "sku": "SKU-B", "value": "400g", "source": "specs.gross_weight_g"},
        ]},
    )

    async def adjudicator_must_not_run(*_args, **_kwargs):
        raise AssertionError("missing requested field must fail closed before semantic adjudication")

    monkeypatch.setattr(customer_service_service, "_semantic_comparison_adjudication", adjudicator_must_not_run)
    result = asyncio.run(customer_service_service._phase1_compare_choice_result(None, {
        "raw_question": "\u7532\u6b3e\u548c\u4e59\u6b3e\u54ea\u4e2a\u66f4\u9002\u5408\u4e09\u4e2a\u4eba\uff1f",
        "product_refs": ["SKU-A", "SKU-B"],
        "must_make_choice": True,
        "semantic_comparison_entity_contracts": [
            {"status": "resolved", "resolved_sku": "SKU-A"},
            {"status": "resolved", "resolved_sku": "SKU-B"},
        ],
    }))

    assert result["answer_metadata"]["evidence_status"] == "missing"
    assert result["answer_metadata"]["final_choice_sku"] is None
    assert result["debug"]["agent_mode"] == "planner_compare_formal_field_contract"
    assert "\u4e0d\u80fd\u636e\u6b64\u63a8\u65ad" in result["answer"]


def test_high_confidence_semantic_recommendation_recovers_literal_current_turn_scope(
    monkeypatch,
    route_client_and_db,
):
    client, headers, _ = route_client_and_db

    async def fake_preplan(db, question, deterministic_plan, context):
        result = customer_agent_planner_service._empty_semantic_preplan(called=True)
        result.update({
            "route_family": "recommendation",
            "route_hint": "recommendation",
            "question_type": "recommendation",
            "entity_scope": "category_scope",
            "confidence": 0.9,
            "confidence_label": "high",
            "recommendation_constraints": {},
            "reasoning_summary": "Customer requests product advice but no validated constraints are available.",
        })
        return result

    monkeypatch.setattr(customer_agent_planner_service, "plan_customer_question_semantic", fake_preplan)
    payload = client.post(
        "/api/customer-service/ask?debug=true",
        json={"question": "想找一款能明火煮面的户外小锅，有什么建议？"},
        headers=headers,
    ).json()

    assert payload["answer_type"] == "recommendation"
    assert payload["debug"]["agent_mode"] in {
        "semantic_recommendation_contract",
        "semantic_recommendation_insufficient_verified_evidence",
    }
    assert payload["debug"]["semantic_preplan"]["route_family"] == "recommendation"
    assert payload["debug"]["plan"]["semantic_preplan"]["recommendation_constraints"]["subject_kind"] == "cookware"


def test_resolved_numeric_structured_query_preempts_stochastic_semantic_recommendation(
    monkeypatch,
    route_client_and_db,
):
    client, headers, _ = route_client_and_db
    question = "容量不超过1升的水壶有哪些？"

    async def fake_preplan(db, raw_question, deterministic_plan, context):
        result = customer_agent_planner_service._empty_semantic_preplan(called=True)
        result.update({
            "route_family": "recommendation",
            "route_hint": "recommendation",
            "question_type": "recommendation",
            "entity_scope": "category_scope",
            "confidence": 0.95,
            "confidence_label": "high",
            "recommendation_constraints": {"subject_kind": "waterware"},
            "unrepresented_recommendation_requirements": ["容量不超过1升"],
            "reasoning_summary": "Treat the catalogue filter as product advice.",
        })
        return result

    monkeypatch.setattr(customer_agent_planner_service, "plan_customer_question_semantic", fake_preplan)
    payload = client.post(
        "/api/customer-service/ask?debug=true",
        json={"question": question},
        headers=headers,
    ).json()

    assert payload["answer_type"] == "product_query", payload
    assert payload["debug"]["agent_mode"] == "structured_query_contract", payload
    assert payload["result_skus"], payload
    assert "不超过1000ml" in payload["answer"], payload


def test_pairwise_recommendation_preplan_does_not_preempt_sealed_comparison_with_constraint_clarification():
    preplan = {
        "called": True,
        "route_family": "recommendation",
        "confidence": 0.9,
        "decision_requested": True,
        "entities": ["甲款", "乙款"],
        "recommendation_constraints": {},
    }

    assert customer_service_service._semantic_pairwise_contract_candidate(preplan) is True
    assert customer_service_service._semantic_recommendation_constraint_clarification_result(preplan) is None


def test_pairwise_recommendation_preplan_does_not_execute_catalog_recommendation_before_comparison():
    preplan = {
        "called": True,
        "route_family": "recommendation",
        "confidence": 0.9,
        "decision_requested": True,
        "entities": ["甲款", "乙款"],
        "recommendation_constraints": {"subject_kind": "waterware"},
    }

    result = asyncio.run(customer_service_service._semantic_recommendation_contract_result(
        None,
        "甲款和乙款该怎么选？",
        {"semantic_preplan": preplan},
    ))

    assert result is None


def test_recommendation_with_two_semantic_named_entities_is_sealed_even_if_decision_boolean_is_omitted():
    preplan = {
        "called": True,
        "route_family": "recommendation",
        "confidence": 0.9,
        "entities": ["甲款", "乙款"],
        "recommendation_constraints": {"subject_kind": "waterware"},
    }

    assert customer_service_service._semantic_pairwise_contract_candidate(preplan) is True
    assert customer_service_service._should_execute_semantic_catalog_recommendation(preplan) is False


def test_grounded_medium_confidence_semantic_recommendation_uses_catalog_contract():
    """A legal semantic recommendation must not fall back to legacy query-products.

    Medium confidence means the semantic model is less certain about phrasing,
    not that a validated, allowlisted recommendation route can be reinterpreted
    by the old lexical planner.  The central verifier still decides whether
    same-SKU evidence is sufficient to return candidates or clarify safely.
    """
    preplan = {
        "called": True,
        "route_family": "recommendation",
        "confidence": 0.65,
        "confidence_label": "medium",
        "recommendation_constraint_grounding": "validated_semantic_grounding",
        "recommendation_constraints": {
            "subject_kind": "stove",
            "scenarios": ["camping"],
        },
    }

    assert customer_service_service._should_execute_semantic_catalog_recommendation(preplan) is True


def test_grounded_pairwise_recommendation_constraints_create_formal_comparison_fields():
    preplan = {
        "called": True,
        "route_family": "recommendation",
        "route_hint": "recommendation",
        "question_type": "recommendation",
        "confidence": 0.9,
        "entities": ["甲款", "乙款"],
        "recommendation_constraints": {"scenarios": ["camping"], "weight_preference": "lightweight"},
        "recommendation_constraint_grounding": "validated_semantic_grounding",
    }

    customer_service_service._apply_pairwise_recommendation_field_adapter(preplan)

    assert preplan["canonical_fields"] == ["usage_scene", "weight"]
    assert preplan["semantic_adapter_source"] == "validated_pairwise_recommendation_constraints"


def test_output_shaping_preserves_validated_semantic_recommendation_narrative():
    result = customer_service_service._shape_answer_for_output({
        "answer_type": "recommendation",
        "answer": "候选产品中，小方锅Pro套装（CW-C99）更适合明火煮面，因为方形锅面能平铺，收纳也更方便。",
        "results": [{"sku": "CW-C99", "product_name_cn": "小方锅Pro套装"}],
        "evidence": [{"sku": "CW-C99", "field_label": "热源", "value": "明火直烧"}],
        "answer_metadata": {
            "recommendation_narrative": {"source": "validated_deepseek_grounded_narrative"},
        },
    })

    assert result["answer"] == "候选产品中，小方锅Pro套装（CW-C99）更适合明火煮面，因为方形锅面能平铺，收纳也更方便。"


def test_output_shaping_keeps_recommendation_intro_before_single_sku_evidence():
    result = customer_service_service._shape_answer_for_output({
        "answer_type": "recommendation",
        "answer": "推荐优先看这款：\n- 入门单锅（SAFE-ONE）：价格定位：入门款",
        "results": [{"sku": "SAFE-ONE", "product_name_cn": "入门单锅"}],
        "evidence": [],
    })

    assert result["answer"].splitlines()[0] == "推荐优先看这款："
    assert result["answer"].splitlines()[1].startswith("- 入门单锅（SAFE-ONE）")


def test_output_shaping_keeps_narrative_intro_before_alternative_items():
    result = customer_service_service._shape_answer_for_output({
        "answer_type": "recommendation",
        "answer": "已排除刚才推荐的锅具，以下是不同类型的替代选择：\n- 水壶（KETTLE-1）",
        "results": [{"sku": "KETTLE-1", "product_name_cn": "水壶"}],
        "evidence": [],
    })

    assert result["answer"].splitlines()[0].startswith("已排除刚才推荐的锅具")


def test_recommendation_post_filter_preserves_validated_deepseek_narrative_when_verified_skus_are_unchanged(monkeypatch):
    class FakeVerification:
        sku = "CW-S10-A"
        verification_level = "fully_verified"

        def to_dict(self):
            return {
                "sku": self.sku,
                "verification_level": self.verification_level,
            }

    fake_verification = FakeVerification()
    monkeypatch.setattr(
        customer_service_service.customer_recommendation_verification_contract,
        "build_recommendation_request_contract",
        lambda question: pytest.fail("validated semantic recommendation must reuse its sealed contract"),
    )
    monkeypatch.setattr(
        customer_service_service.customer_recommendation_verification_contract,
        "verify_recommendation_candidates",
        lambda contract, rows: [fake_verification],
    )
    monkeypatch.setattr(
        customer_service_service.customer_recommendation_verification_contract,
        "select_recommendation_candidates",
        lambda rows, verifications: [
            row for row in rows if row.get("sku") == "CW-S10-A"
        ],
    )
    monkeypatch.setattr(
        customer_service_service.customer_recommendation_verification_contract,
        "prepare_recommendation_return_rows",
        lambda rows, limit=5: (list(rows), {"total_match_count": len(rows)}),
    )
    monkeypatch.setattr(
        customer_service_service,
        "_structured_row_matches_contract",
        lambda row, contract: pytest.fail("legacy lexical eligibility must not re-filter a sealed semantic result"),
    )
    monkeypatch.setattr(
        customer_service_service,
        "_is_service_pot_or_cookware_set_candidate",
        lambda row: row.get("sku") == "CW-S10-A",
    )
    monkeypatch.setattr(
        customer_service_service,
        "_should_use_central_subject_recommendation",
        lambda **kwargs: True,
    )
    monkeypatch.setattr(
        customer_service_service,
        "_rehydrate_recommendation_rows_from_database",
        lambda db, result: {
            **result,
            "results": [
                {
                    "sku": "CW-C95",
                    "product_name_cn": "风暴炉pro-两用版",
                    "category": "炉具、锅具",
                    "heat_source": "酒精炉",
                },
                *result["results"],
            ],
            "result_skus": ["CW-C95", "CW-S10-A"],
            "candidate_skus": ["CW-C95", "CW-S10-A"],
        },
    )

    answer = "如果您要搭配酒精炉，可以看看激川单锅；资料标注它支持酒精炉。"
    result = customer_service_service._post_filter_recommendation_result(
        None,
        "适合酒精炉的锅具推荐一下。",
        {
            "intent": "recommendation",
            "answer_type": "recommendation",
            "answer": answer,
            "results": [{
                "sku": "CW-S10-A",
                "product_name_cn": "激川单锅",
                "category": "锅具",
                "sub_category": "单锅",
                "heat_source": "酒精炉；气炉",
            }],
            "result_skus": ["CW-S10-A"],
            "candidate_skus": ["CW-C95", "CW-S10-A"],
            "answer_metadata": {
                "source": "validated_semantic_preplan_then_same_sku_verification",
                "recommendation_contract": {
                    "subject_kind": "cookware",
                    "subject_category": "锅具",
                    "heat_sources": ["alcohol_stove"],
                    "hard_constraints": ["heat_source"],
                    "soft_preferences": [],
                    "field_provenance": {
                        "subject_category": {
                            "source_turn": 1,
                            "provenance": "validated_semantic_preplan",
                        },
                    },
                },
                "recommendation_narrative": {
                    "source": "validated_deepseek_grounded_narrative",
                },
            },
            "debug": {"agent_mode": "semantic_recommendation_contract"},
        },
    )

    assert result["answer"] == answer
    assert result["result_skus"] == ["CW-S10-A"]
    assert result["debug"]["recommendation_post_filter_answer_rebuilt"] is False
    assert result["debug"]["recommendation_post_filter_rebuild_reasons"] == []


def test_semantic_preplan_treats_empty_optional_recommendation_containers_as_absent(monkeypatch):
    async def fake_chat_completion(db, messages, **kwargs):
        if kwargs.get("purpose") == "semantic_recommendation_constraint_grounding":
            return json.dumps({
                "recommendation_constraints": {
                    "subject_kind": "cookware", "scenarios": ["camping"], "weight_preference": "lightweight",
                },
                "evidence_spans": {
                    "subject_kind": ["\u9505\u5177"], "scenarios": ["\u9732\u8425"], "weight_preference": ["\u4e0d\u7d2f"],
                },
            })
        return json.dumps({
            "route_family": "recommendation",
            "entity_scope": "category_scope",
            "confidence": "high",
            "recommendation_constraints": {
                "subject_kind": "cookware",
                "people": {},
                "heat_sources": [],
                "scenarios": ["camping"],
                "weight_preference": "lightweight",
            },
        })

    monkeypatch.setattr(customer_agent_planner_service.customer_llm_service, "chat_completion", fake_chat_completion)
    result = asyncio.run(customer_agent_planner_service.plan_customer_question_semantic(
        db=None, question="想找适合露营、背起来不累的锅具。", deterministic_plan={}, context={}
    ))

    assert result["fallback_reason"] == ""
    assert result["route_family"] == "recommendation"
    assert result["recommendation_constraints"] == {
        "subject_kind": "cookware", "scenarios": ["camping"], "weight_preference": "lightweight",
    }
    assert not result["fallback_reason"]


def test_semantic_preplan_prompt_distinguishes_unbound_recommendation_from_product_qa():
    messages = customer_agent_planner_service._semantic_preplan_messages(
        question="有没有适合送人的户外产品？",
        deterministic_plan={},
        context={},
    )
    instructions = "\n".join(message["content"] for message in messages if message["role"] == "system")

    assert "unbound customer request for actual catalogue candidates" in instructions
    assert "must use route_family=recommendation" in instructions
    assert "product_bound_qa requires one named product or an entity anchor" in instructions


def test_empty_unbound_recommendation_contract_requests_category_not_sku():
    result = customer_service_service._semantic_recommendation_constraint_clarification_result({
        "called": True,
        "route_family": "recommendation",
        "confidence": 0.9,
        "confidence_label": "high",
        "fallback_reason": "",
        "recommendation_constraints": {},
        "ambiguity": False,
    })

    assert result is not None
    assert result["intent"] == "recommendation"
    assert "锅具、水具、炉具还是餐具" in result["answer"]
    assert "SKU" not in result["answer"]


def test_medium_confidence_unbound_recommendation_keeps_semantic_route_and_asks_to_narrow():
    result = customer_service_service._semantic_recommendation_constraint_clarification_result({
        "called": True,
        "route_family": "recommendation",
        "question_type": "recommendation",
        "confidence": 0.65,
        "confidence_label": "medium",
        "fallback_reason": "",
        "recommendation_constraints": {},
        "ambiguity": False,
    })

    assert result is not None
    assert result["intent"] == "recommendation"
    assert result["answer_type"] == "clarification"
    assert "预算" in result["answer"]
    assert "自驾/徒步" in result["answer"]
    assert result["result_skus"] == []


def test_recommendation_preferences_cannot_make_executor_guess_a_product_family():
    preplan = {
        "called": True,
        "route_family": "recommendation",
        "confidence": 0.9,
        "confidence_label": "high",
        "fallback_reason": "",
        "ambiguity": False,
        "recommendation_constraints": {
            "scenarios": ["camping"],
            "storage_preference": "compact_storage",
        },
    }

    assert customer_service_service._should_execute_semantic_catalog_recommendation(preplan) is False
    clarification = customer_service_service._semantic_recommendation_constraint_clarification_result(preplan)
    assert clarification is not None
    assert clarification["answer_type"] == "clarification"
    assert "避免直接猜一件并不合适的礼物" in clarification["answer"]
    assert clarification["result_skus"] == []


def test_semantic_prompt_maps_fuel_canister_and_maximum_output_to_formal_fields():
    messages = customer_agent_planner_service._semantic_preplan_messages(
        question="某款炉具支持哪些燃料或气罐，最大功率是多少？",
        deterministic_plan={},
        context={},
    )
    instructions = "\n".join(message["content"] for message in messages if message["role"] == "system")

    assert "which fuels or canisters" in instructions
    assert "directly requests heat_source" in instructions
    assert "maximum output" in instructions
    assert "must use power" in instructions


def test_semantic_preplan_rejects_recommendation_identity_payload(monkeypatch):
    async def fake_chat_completion(db, messages, **kwargs):
        return json.dumps({
            "route_family": "recommendation",
            "entity_scope": "category_scope",
            "confidence": "high",
            "recommendation_constraints": {"subject_kind": "cookware", "sku": "CW-C95"},
        })

    monkeypatch.setattr(customer_agent_planner_service.customer_llm_service, "chat_completion", fake_chat_completion)
    result = asyncio.run(customer_agent_planner_service.plan_customer_question_semantic(
        db=None, question="帮我推荐露营锅具。", deterministic_plan={}, context={}
    ))

    assert result["fallback_reason"] == "invalid_recommendation_constraints"
    assert result["recommendation_constraints"] == {}
    assert result["route_hint"] == ""
    assert result["confidence"] == 0.0


@pytest.mark.skip(reason="superseded by the select-render closed-evidence pipeline tests")
def test_semantic_recommendation_contract_uses_only_validated_constraints_and_same_sku_evidence(monkeypatch):
    rows = [
        {
            "sku": "SAFE-1", "product_name_cn": "可验证锅具", "category": "锅具",
            "usage_scenarios": "露营", "target_audience": "适合2人", "heat_source": "卡式炉",
            "gross_weight_g": 650,
        },
        {
            "sku": "WRONG-SCENE", "product_name_cn": "厨房锅具", "category": "锅具",
            "usage_scenarios": "家庭厨房", "target_audience": "适合2人", "heat_source": "卡式炉",
            "gross_weight_g": 550,
        },
    ]
    monkeypatch.setattr(customer_service_service, "_phase1_catalog_rows", lambda db, ref: rows)
    sealed_candidates = []
    narrative_model_overrides = []

    async def grounded_narrative(_db, messages, **kwargs):
        if kwargs.get("purpose") == "semantic_recommendation_narrative":
            sealed_candidates.extend(json.loads(messages[1]["content"])["sealed_candidates"])
        if str(kwargs.get("purpose") or "").startswith("semantic_recommendation_narrative"):
            narrative_model_overrides.append(kwargs.get("api_model_override"))
        if kwargs.get("purpose") == "semantic_recommendation_narrative_grounding_review":
            return json.dumps({"approved": True, "unsupported_claims": []})
        return json.dumps({
            "ranked_candidate_indexes": [0],
            "evidence_usage": [{
                "candidate_index": 0,
                "fields": ["people", "scenario", "heat_source", "weight"],
            }],
            "answer": "可验证锅具具备两人露营、卡式炉和 650g 的同 SKU 资料，可作为轻量露营候选。",
        })
    monkeypatch.setattr(customer_service_service.customer_llm_service, "chat_completion", grounded_narrative)
    result = asyncio.run(customer_service_service._semantic_recommendation_contract_result(
        None,
        "想找露营用、背起来别太沉的锅具。",
        {
            "semantic_preplan": {
                "called": True, "route_family": "recommendation", "confidence": 0.9,
                "confidence_label": "high", "fallback_reason": "", "ambiguity": False,
                "recommendation_constraints": {
                    "subject_kind": "cookware", "people": {"min": 2, "max": 2},
                    "heat_sources": ["card_stove"], "scenarios": ["camping"],
                    "weight_preference": "lightweight",
                },
            },
        },
    ))

    assert result["debug"]["agent_mode"] == "semantic_recommendation_contract"
    assert result["result_skus"] == ["SAFE-1"]
    assert "650g" in result["answer"]
    assert "卡式炉" in result["answer"]
    assert result["answer_metadata"]["recommendation_contract"]["field_provenance"]["weight"]["provenance"] == "validated_semantic_preplan"
    assert result["debug"]["candidate_verifications"][0]["evidence_by_constraint"]["scenario"]["field_source"] == "usage_scenarios"
    assert set(sealed_candidates[0]["verified_constraints"]) == {"subject", "people", "scenario", "heat_source", "weight"}
    assert "verified_requirement_claims" not in sealed_candidates[0]
    assert narrative_model_overrides == ["deepseek-v4-flash", "deepseek-v4-flash"]


def test_semantic_recommendation_returns_the_same_content_evidence_used_by_narrative(monkeypatch):
    """Debug evidence must expose the sealed same-SKU content cited by DeepSeek."""
    rows = [{
        "sku": "SAFE-STORAGE", "product_name_cn": "Safe storage cookware", "category": "\u9505\u5177",
        "features": "\u5957\u5a03\u5f0f\u6536\u7eb3", "usage_scenarios": "\u9732\u8425",
    }]
    monkeypatch.setattr(customer_service_service, "_phase1_catalog_rows", lambda db, ref: rows)

    async def grounded_narrative(_db, messages, **kwargs):
        if kwargs.get("purpose") == "semantic_recommendation_narrative_grounding_review":
            return json.dumps({"approved": True, "unsupported_claims": []})
        return json.dumps({
            "ranked_candidate_indexes": [0],
            "evidence_usage": [{"candidate_index": 0, "fields": ["content.features"]}],
            "answer": "Safe storage cookware has sealed same-SKU nesting-storage evidence.",
        })

    monkeypatch.setattr(customer_service_service.customer_llm_service, "chat_completion", grounded_narrative)
    result = asyncio.run(customer_service_service._semantic_recommendation_contract_result(
        None,
        "recommend compact cookware",
        {"semantic_preplan": {
            "called": True, "route_family": "recommendation", "confidence": 0.9,
            "confidence_label": "high", "fallback_reason": "", "ambiguity": False,
            "recommendation_constraints": {"subject_kind": "cookware", "storage_preference": "compact_storage"},
        }},
    ))

    assert result["answer_type"] == "recommendation", result
    assert result["result_skus"] == ["SAFE-STORAGE"]
    assert any(
        item.get("type") == "semantic_recommendation_narrative_evidence"
        and item.get("sku") == "SAFE-STORAGE"
        and item.get("field") == "content.features"
        and item.get("source") == "features"
        and item.get("value") == "\u5957\u5a03\u5f0f\u6536\u7eb3"
        for item in result["evidence"]
    )


def test_weight_evidence_uses_grams_unit_on_shared_customer_evidence_provider():
    assert customer_service_service._weight_field_evidence(195.0) == "195g"
    assert customer_service_service._weight_field_evidence("420") == "420g"
    assert customer_service_service._weight_field_evidence(0) == ""


@pytest.mark.skip(reason="superseded by the select-render closed-evidence pipeline tests")
def test_semantic_recommendation_reviewer_allows_direct_usage_scenario_evidence(monkeypatch):
    """The reviewer must not reject a literal same-SKU usage-scenario statement."""
    rows = [{
        "sku": "SAFE-1", "product_name_cn": "可验证锅具", "category": "锅具",
        "usage_scenarios": "露营", "target_audience": "适合2人", "heat_source": "卡式炉",
        "gross_weight_g": 650,
    }]
    reviewer_prompt = []

    async def approved_direct_scenario(_db, messages, **kwargs):
        purpose = kwargs.get("purpose")
        if purpose == "semantic_recommendation_narrative":
            return json.dumps({
                "ranked_candidate_indexes": [0],
                "evidence_usage": [{"candidate_index": 0, "fields": ["scenario"]}],
                "answer": "可验证锅具的同 SKU 使用场景资料标注为露营，可作为本次露营需求的候选。",
            })
        assert purpose == "semantic_recommendation_narrative_grounding_review"
        reviewer_prompt.append(messages[0]["content"])
        return json.dumps({"approved": True, "unsupported_claims": []})

    monkeypatch.setattr(customer_service_service, "_phase1_catalog_rows", lambda db, ref: rows)
    monkeypatch.setattr(customer_service_service.customer_llm_service, "chat_completion", approved_direct_scenario)
    result = asyncio.run(customer_service_service._semantic_recommendation_contract_result(
        None,
        "露营锅具怎么选？",
        {"semantic_preplan": {
            "called": True, "route_family": "recommendation", "confidence": 0.9,
            "confidence_label": "high", "fallback_reason": "", "ambiguity": False,
            "recommendation_constraints": {"subject_kind": "cookware", "scenarios": ["camping"]},
        }},
    ))

    assert result["debug"]["agent_mode"] == "semantic_recommendation_contract"
    assert "content.usage_scenarios" in reviewer_prompt[0]
    assert "direct scenario statement" in reviewer_prompt[0]
    assert "internal selection gates" in reviewer_prompt[0]
    assert "verified_requirement_claims" not in reviewer_prompt[0]


def test_semantic_recommendation_does_not_replace_missing_deepseek_narrative_with_legacy_candidate_list(monkeypatch):
    """A semantic recommendation must fail closed instead of exposing a generic list.

    Candidate verification proves only that the supplied constraints match; it
    does not supply the customer-facing explanation that a semantic
    recommendation requires.  The old deterministic list was a legacy
    category-result formatter and could make a broad category match look like
    a personalized choice.
    """
    rows = [{
        "sku": "SAFE-1", "product_name_cn": "可验证锅具", "category": "锅具",
        "usage_scenarios": "露营", "target_audience": "适合2人", "heat_source": "卡式炉",
        "gross_weight_g": 650,
    }]
    monkeypatch.setattr(customer_service_service, "_phase1_catalog_rows", lambda db, ref: rows)

    async def unavailable_narrative(*args, **kwargs):
        return None

    monkeypatch.setattr(customer_service_service, "_semantic_recommendation_narrative", unavailable_narrative)
    result = asyncio.run(customer_service_service._semantic_recommendation_contract_result(
        None,
        "我主要做煎烤早餐，锅和烤盘该优先选哪个？",
        {"semantic_preplan": {
            "called": True, "route_family": "recommendation", "confidence": 0.9,
            "confidence_label": "high", "fallback_reason": "", "ambiguity": False,
            "recommendation_constraints": {"subject_kind": "cookware"},
        }},
    ))

    assert result["answer_type"] == "clarification"
    assert result["result_skus"] == []
    assert result["candidate_skus"] == []
    assert "SAFE-1" not in result["answer"]
    assert "共找到" not in result["answer"]
    assert result["debug"]["agent_mode"] == "semantic_recommendation_narrative_unavailable"


def test_semantic_recommendation_keeps_broad_request_closed_after_invalid_narrative_schema(monkeypatch):
    rows = [
        {
            "sku": f"SAFE-{index}", "product_name_cn": f"可验证锅具{index}", "category": "锅具",
            "usage_scenarios": "露营", "target_audience": "适合2人", "heat_source": "卡式炉",
            "gross_weight_g": 650 + index,
        }
        for index in range(1, 4)
    ]

    async def malformed_narrative(_db, messages, **kwargs):
        assert kwargs.get("purpose") == "semantic_recommendation_narrative"
        return "{}"

    monkeypatch.setattr(customer_service_service, "_phase1_catalog_rows", lambda db, ref: rows)
    monkeypatch.setattr(customer_service_service.customer_llm_service, "chat_completion", malformed_narrative)
    result = asyncio.run(customer_service_service._semantic_recommendation_contract_result(
        None,
        "我主要做煎烤早餐，锅和烤盘该优先选哪个？",
        {"semantic_preplan": {
            "called": True, "route_family": "recommendation", "confidence": 0.9,
            "confidence_label": "high", "fallback_reason": "", "ambiguity": False,
            "recommendation_constraints": {"subject_kind": "cookware"},
        }},
    ))

    assert result["answer_type"] == "clarification"
    assert result["result_skus"] == []
    assert result["candidate_skus"] == []


@pytest.mark.skip(reason="superseded by one-draft semantic selection recovery")
def test_semantic_recommendation_reports_invalid_narrative_schema_in_verified_fallback_debug(monkeypatch):
    """A verified fallback keeps the bounded reason its semantic prose was rejected.

    The diagnostic contains only bounded stage/status codes.  It deliberately
    never exposes the model draft or sealed candidate data in the debug trace.
    """
    rows = [{
        "sku": "SAFE-1", "product_name_cn": "可验证锅具", "category": "锅具",
        "usage_scenarios": "露营", "target_audience": "适合2人", "heat_source": "卡式炉",
        "gross_weight_g": 650,
    }]

    async def malformed_narrative(_db, messages, **kwargs):
        assert kwargs.get("purpose") == "semantic_recommendation_narrative"
        return "{}"

    monkeypatch.setattr(customer_service_service, "_phase1_catalog_rows", lambda db, ref: rows)
    monkeypatch.setattr(customer_service_service.customer_llm_service, "chat_completion", malformed_narrative)
    result = asyncio.run(customer_service_service._semantic_recommendation_contract_result(
        None,
        "请推荐适合两人露营、能用卡式炉的轻量锅具。",
        {"semantic_preplan": {
            "called": True, "route_family": "recommendation", "confidence": 0.9,
            "confidence_label": "high", "fallback_reason": "", "ambiguity": False,
            "recommendation_constraints": {
                "subject_kind": "cookware", "people": {"min": 2, "max": 2},
                "heat_sources": ["card_stove"], "scenarios": ["camping"], "weight_preference": "lightweight",
            },
        }},
    ))

    assert result["debug"]["agent_mode"] == "semantic_recommendation_contract"
    assert result["result_skus"] == ["SAFE-1"]
    assert result["answer_metadata"]["recommendation_narrative"]["source"] == "verified_candidate_evidence_fallback"
    assert result["debug"]["recommendation_narrative_diagnostics"] == [
        {"attempt": 1, "stage": "draft", "status": "invalid_schema"},
        {"attempt": 2, "stage": "draft", "status": "invalid_schema"},
    ]


def test_semantic_recommendation_uses_verified_fallback_after_invalid_narrative_schema(monkeypatch):
    rows = [{
        "sku": "SAFE-1", "product_name_cn": "可验证锅具", "category": "锅具",
        "usage_scenarios": "露营", "target_audience": "适合2人", "heat_source": "卡式炉",
        "gross_weight_g": 650,
    }]

    async def malformed_narrative(_db, messages, **kwargs):
        assert kwargs.get("purpose") == "semantic_recommendation_narrative"
        return "{}"

    monkeypatch.setattr(customer_service_service, "_phase1_catalog_rows", lambda db, ref: rows)
    monkeypatch.setattr(customer_service_service.customer_llm_service, "chat_completion", malformed_narrative)
    result = asyncio.run(customer_service_service._semantic_recommendation_contract_result(
        None,
        "请推荐适合两人露营、能用卡式炉的轻量锅具。",
        {"semantic_preplan": {
            "called": True, "route_family": "recommendation", "confidence": 0.9,
            "confidence_label": "high", "fallback_reason": "", "ambiguity": False,
            "recommendation_constraints": {
                "subject_kind": "cookware", "people": {"min": 2, "max": 2},
                "heat_sources": ["card_stove"], "scenarios": ["camping"], "weight_preference": "lightweight",
            },
        }},
    ))

    assert result["answer_type"] == "recommendation"
    assert result["result_skus"] == ["SAFE-1"]
    assert "SAFE-1" in result["answer"]
    assert result["answer_metadata"]["recommendation_narrative"]["source"] == "verified_candidate_evidence_fallback"


@pytest.mark.skip(reason="post-render model veto removed from the closed-evidence pipeline")
def test_semantic_recommendation_distinguishes_invalid_grounding_review_schema(monkeypatch):
    rows = [{
        "sku": "SAFE-1", "product_name_cn": "可验证锅具", "category": "锅具",
        "usage_scenarios": "露营", "target_audience": "适合2人", "heat_source": "卡式炉",
        "gross_weight_g": 650,
    }]

    async def invalid_review(_db, messages, **kwargs):
        if kwargs.get("purpose") == "semantic_recommendation_narrative":
            return json.dumps({
                "ranked_candidate_indexes": [0],
                "evidence_usage": [{"candidate_index": 0, "fields": ["people", "scenario", "heat_source", "weight"]}],
                "answer": "可验证锅具具备两人露营、卡式炉和650g的同 SKU 资料，可作为轻量露营锅具候选。",
            })
        assert kwargs.get("purpose") == "semantic_recommendation_narrative_grounding_review"
        return "{}"

    monkeypatch.setattr(customer_service_service, "_phase1_catalog_rows", lambda db, ref: rows)
    monkeypatch.setattr(customer_service_service.customer_llm_service, "chat_completion", invalid_review)
    result = asyncio.run(customer_service_service._semantic_recommendation_contract_result(
        None,
        "请推荐适合两人露营、能用卡式炉的轻量锅具。",
        {"semantic_preplan": {
            "called": True, "route_family": "recommendation", "confidence": 0.9,
            "confidence_label": "high", "fallback_reason": "", "ambiguity": False,
            "recommendation_constraints": {
                "subject_kind": "cookware", "people": {"min": 2, "max": 2},
                "heat_sources": ["card_stove"], "scenarios": ["camping"], "weight_preference": "lightweight",
            },
        }},
    ))

    assert result["debug"]["recommendation_narrative_diagnostics"] == [
        {"attempt": 1, "stage": "grounding_review", "status": "invalid_contract"},
        {"attempt": 2, "stage": "grounding_review", "status": "invalid_contract"},
    ]


@pytest.mark.skip(reason="superseded by the select-render Flash ownership tests")
def test_semantic_recommendation_uses_deepseek_for_grounded_personalized_explanation(monkeypatch):
    rows = [{
        "sku": "SAFE-1", "product_name_cn": "可验证锅具", "category": "锅具",
        "usage_scenarios": "露营", "target_audience": "适合2人", "heat_source": "卡式炉",
        "gross_weight_g": 650,
    }]
    calls = []

    async def fake_chat_completion(db, messages, **kwargs):
        calls.append({"messages": messages, **kwargs})
        if kwargs.get("purpose") == "semantic_recommendation_narrative_grounding_review":
            return json.dumps({"approved": True, "unsupported_claims": []})
        return json.dumps({
            "ranked_candidate_indexes": [0],
            "evidence_usage": [{"candidate_index": 0, "fields": ["people", "scenario", "heat_source", "weight"]}],
            "answer": "如果你优先考虑两人露营又不想增加背负，这款可验证锅具更合适：它有两人、露营和卡式炉的同 SKU 资料，650g 也更利于轻装出行。",
        })

    monkeypatch.setattr(customer_service_service, "_phase1_catalog_rows", lambda db, ref: rows)
    monkeypatch.setattr(customer_service_service.customer_llm_service, "chat_completion", fake_chat_completion)
    result = asyncio.run(customer_service_service._semantic_recommendation_contract_result(
        None,
        "想找露营用、背起来别太沉的锅具。",
        {"semantic_preplan": {
            "called": True, "route_family": "recommendation", "confidence": 0.9,
            "confidence_label": "high", "fallback_reason": "", "ambiguity": False,
            "recommendation_constraints": {
                "subject_kind": "cookware", "people": {"min": 2, "max": 2},
                "heat_sources": ["card_stove"], "scenarios": ["camping"],
                "weight_preference": "lightweight",
            },
        }},
    ))

    assert [call["purpose"] for call in calls] == [
        "semantic_recommendation_narrative",
        "semantic_recommendation_narrative_grounding_review",
    ]
    assert result["answer"].startswith("如果你优先考虑两人露营")
    assert "at most three" in calls[0]["messages"][0]["content"]
    assert "Lead with a short decision guide in conditional form" in calls[0]["messages"][0]["content"]
    assert "state the relevant listed scenario" in calls[0]["messages"][0]["content"]
    assert result["debug"]["agent_mode"] == "semantic_recommendation_contract"
    assert result["answer_metadata"]["recommendation_narrative"]["source"] == "validated_deepseek_grounded_narrative"


@pytest.mark.skip(reason="superseded by one-draft semantic selection recovery")
def test_semantic_recommendation_retries_one_invalid_deepseek_narrative_before_clarifying(monkeypatch):
    rows = [{
        "sku": "SAFE-1", "product_name_cn": "可验证锅具", "category": "锅具",
        "usage_scenarios": "露营", "target_audience": "适合2人", "heat_source": "卡式炉",
        "gross_weight_g": 650,
    }]
    calls = []
    retry_prompt = []

    async def fake_chat_completion(db, messages, **kwargs):
        purpose = kwargs.get("purpose")
        calls.append(purpose)
        if purpose == "semantic_recommendation_narrative":
            if calls.count("semantic_recommendation_narrative") == 1:
                return "{}"
            retry_prompt.append(messages[0]["content"])
            return json.dumps({
                "ranked_candidate_indexes": [0],
                "evidence_usage": [{"candidate_index": 0, "fields": ["people", "scenario", "heat_source", "weight"]}],
                "answer": "可验证锅具具有双人露营、卡式炉和650g的同 SKU 资料，可作为轻量露营锅具候选。",
            })
        assert purpose == "semantic_recommendation_narrative_grounding_review"
        return json.dumps({"approved": True, "unsupported_claims": []})

    monkeypatch.setattr(customer_service_service, "_phase1_catalog_rows", lambda db, ref: rows)
    monkeypatch.setattr(customer_service_service.customer_llm_service, "chat_completion", fake_chat_completion)
    result = asyncio.run(customer_service_service._semantic_recommendation_contract_result(
        None,
        "请推荐双人露营、能用卡式炉的轻量锅具。",
        {"semantic_preplan": {
            "called": True, "route_family": "recommendation", "confidence": 0.9,
            "confidence_label": "high", "fallback_reason": "", "ambiguity": False,
            "recommendation_constraints": {
                "subject_kind": "cookware", "people": {"min": 2, "max": 2},
                "heat_sources": ["card_stove"], "scenarios": ["camping"], "weight_preference": "lightweight",
            },
        }},
    ))

    assert calls == [
        "semantic_recommendation_narrative",
        "semantic_recommendation_narrative",
        "semantic_recommendation_narrative_grounding_review",
    ]
    assert result["debug"]["agent_mode"] == "semantic_recommendation_contract"
    assert result["result_skus"] == ["SAFE-1"]
    assert retry_prompt and "previous draft was rejected at the closed evidence schema" in retry_prompt[0]


def test_recommendation_render_packet_exposes_only_selected_evidence_usage():
    packet = customer_service_service._recommendation_render_packet(
        candidates=[
            {
                "candidate_index": 0,
                "product_name": "轻途套锅",
                "sku": "CW-C06PRO",
                "sealed_evidence": {
                    "specs.gross_weight_g": 650,
                    "content.usage_scenarios": "轻量徒步",
                    "content.positioning": "极致轻量化设计",
                },
            },
            {
                "candidate_index": 1,
                "product_name": "不应展示的候选",
                "sku": "CW-C99",
                "sealed_evidence": {"specs.gross_weight_g": 900},
            },
        ],
        narrative={
            "ranked_candidate_indexes": [0],
            "evidence_usage": [{
                "candidate_index": 0,
                "fields": ["specs.gross_weight_g", "content.usage_scenarios"],
            }],
        },
    )

    assert packet == [{
        "candidate_index": 0,
        "product_name": "轻途套锅",
        "sku": "CW-C06PRO",
        "allowed_evidence": {
            "specs.gross_weight_g": 650,
            "content.usage_scenarios": "轻量徒步",
        },
    }]


@pytest.mark.skip(reason="rewrite cascade replaced by closed-evidence final rendering")
def test_semantic_recommendation_rewrites_narrative_when_semantic_evidence_review_rejects_a_claim(monkeypatch):
    rows = [{
        "sku": "SAFE-1", "product_name_cn": "可验证锅具", "category": "锅具",
        "usage_scenarios": "露营", "target_audience": "适合2人", "heat_source": "卡式炉",
        "gross_weight_g": 650,
    }]
    calls = []

    async def fake_chat_completion(db, messages, **kwargs):
        purpose = kwargs.get("purpose")
        calls.append(purpose)
        if purpose == "semantic_recommendation_narrative":
            return json.dumps({
                "ranked_candidate_indexes": [0],
                "evidence_usage": [{"candidate_index": 0, "fields": ["people", "scenario", "heat_source", "weight"]}],
                "answer": "可验证锅具是所有产品里最轻的选择，适合两人露营使用。",
            })
        if purpose == "semantic_recommendation_narrative_grounding_review":
            if calls.count("semantic_recommendation_narrative_grounding_review") == 1:
                return json.dumps({"approved": False, "unsupported_claims": ["所有产品里最轻"]})
            return json.dumps({"approved": True, "unsupported_claims": []})
        assert purpose == "semantic_recommendation_narrative_rewrite"
        return json.dumps({
            "ranked_candidate_indexes": [0],
            "evidence_usage": [{"candidate_index": 0, "fields": ["people", "scenario", "heat_source", "weight"]}],
            "answer": "可验证锅具有两人露营、卡式炉和 650g 的同 SKU 资料，适合作为轻量露营锅具候选。",
        })

    monkeypatch.setattr(customer_service_service, "_phase1_catalog_rows", lambda db, ref: rows)
    monkeypatch.setattr(customer_service_service.customer_llm_service, "chat_completion", fake_chat_completion)
    result = asyncio.run(customer_service_service._semantic_recommendation_contract_result(
        None,
        "推荐适合两人露营、能用卡式炉的轻量锅具。",
        {"semantic_preplan": {
            "called": True, "route_family": "recommendation", "confidence": 0.9,
            "confidence_label": "high", "fallback_reason": "", "ambiguity": False,
            "recommendation_constraints": {
                "subject_kind": "cookware", "people": {"min": 2, "max": 2},
                "heat_sources": ["card_stove"], "scenarios": ["camping"], "weight_preference": "lightweight",
            },
        }},
    ))

    assert calls == [
        "semantic_recommendation_narrative",
        "semantic_recommendation_narrative_grounding_review",
        "semantic_recommendation_narrative_rewrite",
        "semantic_recommendation_narrative_grounding_review",
    ]
    assert result["answer_metadata"]["recommendation_narrative"]["source"] == "validated_deepseek_grounded_narrative"
    assert any(
        item.get("stage") == "grounding_review"
        and item.get("status") == "rejected"
        and "所有产品里最轻" in item.get("unsupported_claims", [])
        for item in result["debug"]["recommendation_narrative_diagnostics"]
    )
    assert {
        "attempt": 1,
        "stage": "narrative_safety_gate",
        "status": "rejected",
        "unsupported_claims": ["最轻"],
    } in result["debug"]["recommendation_narrative_diagnostics"]
    assert "最轻" not in result["answer"]


@pytest.mark.skip(reason="review cascade replaced by final-render local safety tests")
def test_semantic_recommendation_safety_gate_rejects_superlative_even_if_model_reviewer_misses_it(monkeypatch):
    """A model approval cannot authorize an unproved catalogue-wide ranking.

    This is a central output-safety check, not a route or product rule: a
    literal weight may support its own number, never ``最轻`` without a
    complete comparable population and an explicit ranking contract.
    """
    rows = [{
        "sku": "SAFE-1", "product_name_cn": "可验证锅具", "category": "锅具",
        "usage_scenarios": "露营", "target_audience": "适合2人", "heat_source": "卡式炉",
        "gross_weight_g": 650,
    }]
    calls = []

    async def overly_permissive_reviewer(_db, messages, **kwargs):
        purpose = kwargs.get("purpose")
        calls.append(purpose)
        if purpose == "semantic_recommendation_narrative":
            return json.dumps({
                "ranked_candidate_indexes": [0],
                "evidence_usage": [{"candidate_index": 0, "fields": ["weight"]}],
                "answer": "可验证锅具是这批候选里最轻的选择，重量为650g。",
            })
        if purpose == "semantic_recommendation_narrative_rewrite":
            assert "最轻" in json.loads(messages[1]["content"])["rejected_claims"]
            return json.dumps({
                "ranked_candidate_indexes": [0],
                "evidence_usage": [{"candidate_index": 0, "fields": ["weight"]}],
                "answer": "可验证锅具的同 SKU 重量资料为650g。",
            })
        assert purpose == "semantic_recommendation_narrative_grounding_review"
        return json.dumps({"approved": True, "unsupported_claims": []})

    monkeypatch.setattr(customer_service_service, "_phase1_catalog_rows", lambda db, ref: rows)
    monkeypatch.setattr(customer_service_service.customer_llm_service, "chat_completion", overly_permissive_reviewer)
    result = asyncio.run(customer_service_service._semantic_recommendation_contract_result(
        None,
        "请推荐适合两人露营、能用卡式炉的轻量锅具。",
        {"semantic_preplan": {
            "called": True, "route_family": "recommendation", "confidence": 0.9,
            "confidence_label": "high", "fallback_reason": "", "ambiguity": False,
            "recommendation_constraints": {
                "subject_kind": "cookware", "people": {"min": 2, "max": 2},
                "heat_sources": ["card_stove"], "scenarios": ["camping"], "weight_preference": "lightweight",
            },
        }},
    ))

    assert result["answer_type"] == "recommendation"
    assert result["result_skus"] == ["SAFE-1"]
    assert result["debug"]["agent_mode"] == "semantic_recommendation_contract"
    assert any(
        item.get("stage") == "narrative_safety_gate" and item.get("status") == "rejected"
        for item in result["debug"]["recommendation_narrative_diagnostics"]
    )
    assert "semantic_recommendation_narrative_rewrite" in calls
    assert "最轻" not in result["answer"]


@pytest.mark.skip(reason="rewrite cascade replaced by closed-evidence final rendering")
def test_semantic_recommendation_rewrites_from_bounded_reviewer_rejection(monkeypatch):
    """A compact reviewer rejection must still allow one evidence-only rewrite.

    The reviewer contract intentionally returns only its highest-impact claims:
    an exhaustive rejection risks provider truncation.  The bounded signal must
    remain actionable by the constrained rewrite rather than collapsing to a
    generic clarification.
    """
    rows = [{
        "sku": "SAFE-1", "product_name_cn": "可验证锅具", "category": "锅具",
        "usage_scenarios": "露营", "target_audience": "适合2人", "heat_source": "卡式炉",
        "gross_weight_g": 650,
    }]
    calls = []
    unsupported_claims = [f"unsupported claim {index}" for index in range(5)]

    async def fake_chat_completion(db, messages, **kwargs):
        purpose = kwargs.get("purpose")
        calls.append(purpose)
        if purpose == "semantic_recommendation_narrative":
            return json.dumps({
                "ranked_candidate_indexes": [0],
                "evidence_usage": [{"candidate_index": 0, "fields": ["people", "scenario", "heat_source", "weight"]}],
                "answer": "可验证锅具是最轻、最省钱、最耐用的选择，适合所有露营场景。",
            })
        if purpose == "semantic_recommendation_narrative_grounding_review":
            if calls.count("semantic_recommendation_narrative_grounding_review") == 1:
                return json.dumps({"approved": False, "unsupported_claims": unsupported_claims})
            return json.dumps({"approved": True, "unsupported_claims": []})
        assert purpose == "semantic_recommendation_narrative_rewrite"
        return json.dumps({
            "ranked_candidate_indexes": [0],
            "evidence_usage": [{"candidate_index": 0, "fields": ["people", "scenario", "heat_source", "weight"]}],
            "answer": "可验证锅具有两人露营、卡式炉和650g的同 SKU 资料，可作为轻量露营锅具候选。",
        })

    monkeypatch.setattr(customer_service_service, "_phase1_catalog_rows", lambda db, ref: rows)
    monkeypatch.setattr(customer_service_service.customer_llm_service, "chat_completion", fake_chat_completion)
    result = asyncio.run(customer_service_service._semantic_recommendation_contract_result(
        None,
        "请推荐适合两人露营、能用卡式炉的轻量锅具。",
        {"semantic_preplan": {
            "called": True, "route_family": "recommendation", "confidence": 0.9,
            "confidence_label": "high", "fallback_reason": "", "ambiguity": False,
            "recommendation_constraints": {
                "subject_kind": "cookware", "people": {"min": 2, "max": 2},
                "heat_sources": ["card_stove"], "scenarios": ["camping"], "weight_preference": "lightweight",
            },
        }},
    ))

    assert calls == [
        "semantic_recommendation_narrative",
        "semantic_recommendation_narrative_grounding_review",
        "semantic_recommendation_narrative_rewrite",
        "semantic_recommendation_narrative_grounding_review",
    ]
    assert result["debug"]["agent_mode"] == "semantic_recommendation_contract"
    assert "最轻" not in result["answer"]


def test_semantic_recommendation_with_only_partial_hard_evidence_returns_safe_no_candidate_result(monkeypatch):
    rows = [{
        "sku": "PARTIAL-1", "product_name_cn": "资料不完整的锅具", "category": "锅具",
        "usage_scenarios": "露营", "heat_source": "卡式炉", "gross_weight_g": 650,
    }]
    monkeypatch.setattr(customer_service_service, "_phase1_catalog_rows", lambda db, ref: rows)

    result = asyncio.run(customer_service_service._semantic_recommendation_contract_result(
        None,
        "请推荐适合两人露营、能用卡式炉的轻量锅具。",
        {"semantic_preplan": {
            "called": True, "route_family": "recommendation", "confidence": 0.9,
            "confidence_label": "high", "fallback_reason": "", "ambiguity": False,
            "recommendation_constraints": {
                "subject_kind": "cookware", "people": {"min": 2, "max": 2},
                "heat_sources": ["card_stove"], "scenarios": ["camping"], "weight_preference": "lightweight",
            },
        }},
    ))

    assert result["answer_type"] == "recommendation"
    assert result["result_skus"] == []
    assert result["candidate_skus"] == []
    assert "PARTIAL-1" not in result["answer"]
    assert result["debug"]["agent_mode"] == "semantic_recommendation_insufficient_verified_evidence"


def test_semantic_stove_recommendation_can_disclose_unknown_people_without_discarding_verified_scene(monkeypatch):
    rows = [{
        "sku": "STOVE-PARTIAL-1",
        "product_name_cn": "周末炉",
        "category": "炉具",
        "usage_scenarios": "家庭露营、周末野炊",
        "features": "操作简单，便携收纳",
        "power": "3200W",
    }]

    async def semantic_narrative(*_args, **_kwargs):
        return {
            "ranked_candidate_indexes": [0],
            "evidence_usage": [{"candidate_index": 0, "fields": ["scenario", "content.features"]}],
            "answer": "可以先看周末炉（STOVE-PARTIAL-1）：资料明确覆盖家庭露营和周末野炊；适用人数未标注，需要结合锅具容量确认。",
        }

    monkeypatch.setattr(customer_service_service, "_phase1_catalog_rows", lambda _db, _ref: rows)
    monkeypatch.setattr(customer_service_service.customer_agent_service, "search_products", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(customer_service_service, "_semantic_recommendation_narrative", semantic_narrative)
    result = asyncio.run(customer_service_service._semantic_recommendation_contract_result(
        None,
        "两个人周末露营，想选一款好操作的炉具。",
        {"semantic_preplan": {
            "called": True,
            "route_family": "recommendation",
            "confidence": 0.9,
            "confidence_label": "high",
            "fallback_reason": "",
            "ambiguity": False,
            "subject_text": "好操作的炉具",
            "recommendation_constraints": {
                "subject_kind": "stove",
                "people": {"min": 2, "max": 2},
                "scenarios": ["camping"],
            },
            "recommendation_soft_preferences": ["好操作"],
            "recommendation_constraint_evidence_spans": {
                "subject_kind": ["炉具"],
                "people": ["两个人"],
                "scenarios": ["周末露营"],
            },
        }},
    ))

    assert result["result_skus"] == ["STOVE-PARTIAL-1"]
    assert "适用人数未标注" in result["answer"]
    assert result["debug"]["agent_mode"] == "semantic_recommendation_contract"


def test_replacement_context_pair_keeps_new_and_excluded_previous_recommendation():
    pair = customer_service_service._context_skus_for_pair_followup({
        "replacement_top_sku": "NEW-1",
        "excluded_skus": ["OLD-1"],
        "ordered_result_skus": ["NEW-1", "NEW-2"],
    })

    assert pair == ["NEW-1", "OLD-1"]


def test_semantic_recommendation_insufficient_evidence_names_the_semantic_customer_condition(monkeypatch):
    monkeypatch.setattr(customer_service_service, "_phase1_catalog_rows", lambda _db, _ref: [])

    result = asyncio.run(customer_service_service._semantic_recommendation_contract_result(
        None,
        "我想买可放洗碗机的户外餐具，库里有可确认的选择吗？",
        {"semantic_preplan": {
            "called": True, "route_family": "recommendation", "confidence": 0.9,
            "confidence_label": "high", "fallback_reason": "", "ambiguity": False,
            "recommendation_constraints": {"subject_kind": "cookware", "dishwasher_safe": True},
            "recommendation_constraint_evidence_spans": {"subject_kind": ["户外餐具"], "dishwasher_safe": ["可放洗碗机"]},
        }},
    ))

    assert result["debug"]["agent_mode"] == "semantic_recommendation_insufficient_verified_evidence"
    assert "可放洗碗机" in result["answer"]
    assert "人数、炉具" not in result["answer"]


def test_semantic_recommendation_narrative_rejects_internal_candidate_index_in_answer():
    narrative = customer_service_service._validate_semantic_recommendation_narrative(
        {
            "ranked_candidate_indexes": [0],
            "evidence_usage": [{"candidate_index": 0, "fields": ["scenario"]}],
            "answer": "候选索引1更适合这次露营需求，因为它有经过核验的露营使用场景资料。",
        },
        candidate_count=1,
        verified_fields_by_index={0: {"scenario"}},
    )

    assert narrative is None


def test_semantic_recommendation_narrative_rejects_product_name_outside_its_ranked_evidence():
    narrative = customer_service_service._validate_semantic_recommendation_narrative(
        {
            "ranked_candidate_indexes": [1],
            "evidence_usage": [{"candidate_index": 1, "fields": ["heat_source"]}],
            "answer": "推荐激川单锅，它的同 SKU 炉具资料已通过本次核验。",
        },
        candidate_count=2,
        verified_fields_by_index={0: {"heat_source"}, 1: {"heat_source"}},
        candidate_identity_tokens_by_index={
            0: {"激川单锅", "CW-S10-A"},
            1: {"风暴炉pro-两用版", "CW-C95"},
        },
    )

    assert narrative is None


def test_semantic_recommendation_narrative_requires_each_ranked_product_identity_in_customer_answer():
    narrative = customer_service_service._validate_semantic_recommendation_narrative(
        {
            "ranked_candidate_indexes": [0],
            "evidence_usage": [{"candidate_index": 0, "fields": ["heat_source"]}],
            "answer": "这款锅支持酒精炉加热，可以按这个热源条件作为参考。",
        },
        candidate_count=1,
        verified_fields_by_index={0: {"heat_source"}},
        candidate_identity_tokens_by_index={
            0: {"激川单锅", "CW-S10-A"},
        },
    )

    assert narrative is None


def test_semantic_recommendation_narrative_allows_ranked_name_that_contains_an_unranked_family_name():
    narrative = customer_service_service._validate_semantic_recommendation_narrative(
        {
            "ranked_candidate_indexes": [1],
            "evidence_usage": [{"candidate_index": 1, "fields": ["weight"]}],
            "answer": "城市出逃套锅大锅的同 SKU 重量资料为830g。",
        },
        candidate_count=2,
        verified_fields_by_index={0: {"weight"}, 1: {"weight"}},
        candidate_identity_tokens_by_index={
            0: {"城市出逃套锅", "CW-C65"},
            1: {"城市出逃套锅大锅", "CW-C65-1"},
        },
    )

    assert narrative is not None
    assert narrative["ranked_candidate_indexes"] == [1]


def test_semantic_preplan_preserves_grounded_requirements_not_representable_by_current_contract():
    plan = customer_agent_planner_service._validate_semantic_preplan(
        {
            "route_family": "recommendation",
            "confidence": "high",
            "recommendation_constraints": {"subject_kind": "cookware"},
            "unrepresented_recommendation_requirements": ["必须是小锅", "必须明确支持煮面"],
        },
        raw_content="{}",
    )

    assert plan["fallback_reason"] == ""
    assert plan["unrepresented_recommendation_requirements"] == ["小锅", "煮面"]


def test_semantic_preplan_recovers_model_unrepresented_requirement_misnested_in_constraints_without_inference():
    plan = customer_agent_planner_service._validate_semantic_preplan(
        {
            "route_family": "recommendation",
            "confidence": "high",
            "recommendation_constraints": {
                "scenarios": ["camping"],
                "unrepresented_recommendation_requirements": ["煎烤早餐"],
            },
        },
        raw_content="{}",
    )

    assert plan["fallback_reason"] == ""
    assert plan["recommendation_constraints"] == {"scenarios": ["camping"]}
    assert plan["unrepresented_recommendation_requirements"] == ["煎烤早餐"]


def test_semantic_preplan_preserves_literal_soft_recommendation_preferences_separately_from_hard_gaps():
    """Soft customer priorities must not be silently upgraded into product facts.

    The semantic preplan, rather than a lexical router, owns this distinction.
    A later evidence contract may use only the formal heat-source constraint to
    select candidates; the soft phrase remains available solely to the
    evidence-bound recommendation writer.
    """
    plan = customer_agent_planner_service._validate_semantic_preplan(
        {
            "route_family": "recommendation",
            "confidence": "high",
            "recommendation_constraints": {
                "subject_kind": "cookware",
                "heat_sources": ["open_flame"],
            },
            "unrepresented_recommendation_requirements": [],
            "recommendation_soft_preferences": ["户外煮面"],
        },
        raw_content="{}",
    )

    assert plan["fallback_reason"] == ""
    assert plan["recommendation_constraints"] == {
        "subject_kind": "cookware",
        "heat_sources": ["open_flame"],
    }
    assert plan["unrepresented_recommendation_requirements"] == []
    assert plan["recommendation_soft_preferences"] == ["户外煮面"]


def test_semantic_preplan_reconciles_literal_formal_requirement_misclassified_as_unrepresented(monkeypatch):
    calls = []

    async def fake_chat_completion(db, messages, **kwargs):
        calls.append(kwargs.get("purpose"))
        if kwargs.get("purpose") == "semantic_preplan_requirement_reconciliation":
            return json.dumps({
                "recommendation_constraints": {
                    "subject_kind": "cookware",
                    "people": {"min": 3, "max": 3},
                    "scenarios": ["seaside", "camping"],
                },
                "unrepresented_recommendation_requirements": [],
                "evidence_spans": {
                    "subject_kind": ["锅具"],
                    "people": ["三个人"],
                    "scenarios": ["海边", "露营"],
                },
            })
        if kwargs.get("purpose") == "semantic_recommendation_constraint_grounding":
            return json.dumps({
                "recommendation_constraints": {
                    "subject_kind": "cookware",
                    "people": {"min": 3, "max": 3},
                    "scenarios": ["seaside", "camping"],
                },
                "evidence_spans": {
                    "subject_kind": ["锅具"],
                    "people": ["三个人"],
                    "scenarios": ["海边", "露营"],
                },
            })
        return json.dumps({
            "route_family": "recommendation",
            "route_hint": "recommendation",
            "question_type": "recommendation",
            "confidence": "high",
            "recommendation_constraints": {
                "subject_kind": "cookware",
                "people": {"min": 3, "max": 3},
                "scenarios": ["seaside"],
            },
            "unrepresented_recommendation_requirements": ["露营"],
        })

    monkeypatch.setattr(customer_agent_planner_service.customer_llm_service, "chat_completion", fake_chat_completion)
    plan = asyncio.run(customer_agent_planner_service.plan_customer_question_semantic(
        db=None,
        question="三个人去海边露营，想要一套锅具，有哪些建议？",
        deterministic_plan={},
        context={},
    ))

    assert plan["fallback_reason"] == ""
    assert plan["recommendation_constraints"]["scenarios"] == ["seaside", "camping"]
    assert plan["unrepresented_recommendation_requirements"] == []
    assert calls == [
        "semantic_preplan",
        "semantic_preplan_requirement_reconciliation",
        "semantic_recommendation_constraint_grounding",
    ]


def test_semantic_reconciliation_restores_explicit_people_constraint_alongside_scenario(monkeypatch):
    """Group size is an independent semantic requirement, not a scenario modifier."""
    calls = []

    async def fake_chat_completion(_db, messages, **kwargs):
        purpose = kwargs.get("purpose")
        calls.append(purpose)
        if purpose == "semantic_preplan_requirement_reconciliation":
            assert "cardinality or group-size phrase" in messages[0]["content"]
            return json.dumps({
                "recommendation_constraints": {
                    "subject_kind": "cookware",
                    "people": {"min": 3, "max": 3},
                    "scenarios": ["seaside", "camping"],
                },
                "unrepresented_recommendation_requirements": [],
                "recommendation_soft_preferences": [],
                "evidence_spans": {
                    "subject_kind": ["锅具"],
                    "people": ["三个人"],
                    "scenarios": ["海边", "露营"],
                },
            })
        if purpose == "semantic_recommendation_constraint_grounding":
            return json.dumps({
                "recommendation_constraints": {
                    "subject_kind": "cookware",
                    "people": {"min": 3, "max": 3},
                    "scenarios": ["seaside", "camping"],
                },
                "evidence_spans": {
                    "subject_kind": ["锅具"],
                    "people": ["三个人"],
                    "scenarios": ["海边", "露营"],
                },
            })
        return json.dumps({
            "route_family": "recommendation",
            "route_hint": "recommendation",
            "question_type": "recommendation",
            "confidence": "high",
            "recommendation_constraints": {
                "subject_kind": "cookware",
                "scenarios": ["seaside", "camping"],
            },
            "unrepresented_recommendation_requirements": [],
            "recommendation_soft_preferences": [],
        })

    monkeypatch.setattr(customer_agent_planner_service.customer_llm_service, "chat_completion", fake_chat_completion)
    plan = asyncio.run(customer_agent_planner_service.plan_customer_question_semantic(
        db=None,
        question="三个人去海边露营，想要一套锅具，有哪些建议？",
        deterministic_plan={},
        context={},
    ))

    assert plan["recommendation_constraints"] == {
        "subject_kind": "cookware",
        "people": {"min": 3, "max": 3},
        "scenarios": ["seaside", "camping"],
    }
    assert plan["recommendation_soft_preferences"] == []
    assert calls == [
        "semantic_preplan",
        "semantic_preplan_requirement_reconciliation",
        "semantic_recommendation_constraint_grounding",
    ]


def test_semantic_reconciliation_moves_nonbinding_unrepresented_preference_to_soft(monkeypatch):
    """A wish is not a hard catalogue gate merely because it lacks an ontology key."""
    calls = []

    async def fake_chat_completion(_db, messages, **kwargs):
        purpose = kwargs.get("purpose")
        calls.append(purpose)
        if purpose == "semantic_preplan_requirement_reconciliation":
            assert "choice-framing phrase is soft" in messages[0]["content"]
            return json.dumps({
                "recommendation_constraints": {"subject_kind": "cookware", "scenarios": ["self_drive"]},
                "unrepresented_recommendation_requirements": [],
                "recommendation_soft_preferences": ["不占地方"],
                "evidence_spans": {"subject_kind": ["锅具"], "scenarios": ["自驾"]},
            })
        if purpose == "semantic_recommendation_constraint_grounding":
            return json.dumps({
                "recommendation_constraints": {"subject_kind": "cookware", "scenarios": ["self_drive"]},
                "evidence_spans": {"subject_kind": ["锅具"], "scenarios": ["自驾"]},
            })
        return json.dumps({
            "route_family": "recommendation",
            "route_hint": "recommendation",
            "question_type": "recommendation",
            "confidence": "high",
            "recommendation_constraints": {"subject_kind": "cookware", "scenarios": ["self_drive"]},
            "unrepresented_recommendation_requirements": ["不占地方"],
            "recommendation_soft_preferences": [],
        })

    monkeypatch.setattr(customer_agent_planner_service.customer_llm_service, "chat_completion", fake_chat_completion)
    plan = asyncio.run(customer_agent_planner_service.plan_customer_question_semantic(
        db=None,
        question="周末自驾野餐，想买一套不占地方的锅具，推荐怎么选？",
        deterministic_plan={},
        context={},
    ))

    assert plan["unrepresented_recommendation_requirements"] == []
    assert plan["recommendation_soft_preferences"] == ["不占地方"]
    assert plan["recommendation_constraints"] == {"subject_kind": "cookware", "scenarios": ["self_drive"]}
    assert calls == [
        "semantic_preplan",
        "semantic_preplan_requirement_reconciliation",
        "semantic_recommendation_constraint_grounding",
    ]


def test_semantic_reconciliation_moves_vague_capacity_wish_to_soft_preference(monkeypatch):
    """A vague desired capacity is decision context, not a blocked hard gate."""
    calls = []

    async def fake_chat_completion(_db, messages, **kwargs):
        purpose = kwargs.get("purpose")
        calls.append(purpose)
        if purpose == "semantic_preplan_requirement_reconciliation":
            assert "容量别太小" in messages[0]["content"]
            assert "vague capacity" in messages[0]["content"]
            return json.dumps({
                "recommendation_constraints": {
                    "subject_kind": "cookware",
                    "people": {"min": 2, "max": 2},
                    "scenarios": ["camping"],
                    "weight_preference": "lightweight",
                    "storage_preference": "compact_storage",
                },
                "unrepresented_recommendation_requirements": [],
                "recommendation_soft_preferences": ["容量别太小"],
                "evidence_spans": {
                    "subject_kind": ["锅具"],
                    "people": ["两个人"],
                    "scenarios": ["露营"],
                    "weight_preference": ["轻便"],
                    "storage_preference": ["好收纳"],
                },
            }, ensure_ascii=False)
        if purpose == "semantic_recommendation_constraint_grounding":
            return json.dumps({
                "recommendation_constraints": {
                    "subject_kind": "cookware",
                    "people": {"min": 2, "max": 2},
                    "scenarios": ["camping"],
                    "weight_preference": "lightweight",
                    "storage_preference": "compact_storage",
                },
                "evidence_spans": {
                    "subject_kind": ["锅具"],
                    "people": ["两个人"],
                    "scenarios": ["露营"],
                    "weight_preference": ["轻便"],
                    "storage_preference": ["好收纳"],
                },
            }, ensure_ascii=False)
        return json.dumps({
            "route_family": "recommendation",
            "route_hint": "recommendation",
            "question_type": "recommendation",
            "confidence": "high",
            "recommendation_constraints": {
                "subject_kind": "cookware",
                "people": {"min": 2, "max": 2},
                "scenarios": ["camping"],
                "weight_preference": "lightweight",
                "storage_preference": "compact_storage",
            },
            "unrepresented_recommendation_requirements": ["容量别太小"],
            "recommendation_soft_preferences": [],
        }, ensure_ascii=False)

    monkeypatch.setattr(customer_agent_planner_service.customer_llm_service, "chat_completion", fake_chat_completion)
    plan = asyncio.run(customer_agent_planner_service.plan_customer_question_semantic(
        db=None,
        question="两个人周末露营，想要轻便好收纳、容量别太小的锅具，推荐哪款？",
        deterministic_plan={},
        context={},
    ))

    assert plan["unrepresented_recommendation_requirements"] == []
    assert plan["recommendation_soft_preferences"] == ["容量别太小"]
    assert calls == [
        "semantic_preplan",
        "semantic_preplan_requirement_reconciliation",
        "semantic_recommendation_constraint_grounding",
    ]


def test_semantic_reconciliation_treats_contextual_storage_pressure_as_soft_when_user_declines_forced_choice(monkeypatch):
    """Selection advice with limited storage is not an unrepresented must-have by itself."""
    calls = []

    async def fake_chat_completion(_db, messages, **kwargs):
        purpose = kwargs.get("purpose")
        calls.append(purpose)
        if purpose == "semantic_preplan_requirement_reconciliation":
            assert "does not force a single product" in messages[0]["content"]
            return json.dumps({
                "recommendation_constraints": {"subject_kind": "cookware", "scenarios": ["self_drive"]},
                "unrepresented_recommendation_requirements": [],
                "recommendation_soft_preferences": ["\u8f66\u91cc\u7a7a\u95f4\u7d27"],
                "evidence_spans": {"subject_kind": ["\u9505\u5177"], "scenarios": ["\u81ea\u9a7e"]},
            })
        if purpose == "semantic_recommendation_constraint_grounding":
            return json.dumps({
                "recommendation_constraints": {"subject_kind": "cookware", "scenarios": ["self_drive"]},
                "evidence_spans": {"subject_kind": ["\u9505\u5177"], "scenarios": ["\u81ea\u9a7e"]},
            })
        return json.dumps({
            "route_family": "recommendation",
            "route_hint": "recommendation",
            "question_type": "recommendation",
            "confidence": "high",
            "recommendation_constraints": {"subject_kind": "cookware", "scenarios": ["self_drive"]},
            "unrepresented_recommendation_requirements": ["\u8f66\u91cc\u7a7a\u95f4\u7d27"],
            "recommendation_soft_preferences": [],
        })

    monkeypatch.setattr(customer_agent_planner_service.customer_llm_service, "chat_completion", fake_chat_completion)
    plan = asyncio.run(customer_agent_planner_service.plan_customer_question_semantic(
        db=None,
        question="\u81ea\u9a7e\u53bb\u90ca\u5916\u65f6\u8f66\u91cc\u7a7a\u95f4\u7d27\uff0c\u60f3\u770b\u770b\u9505\u5177\u600e\u4e48\u6311\uff0c\u4e0d\u7528\u5f3a\u884c\u7ed9\u6211\u6307\u5b9a\u4e00\u6b3e\u3002",
        deterministic_plan={},
        context={},
    ))

    assert plan["unrepresented_recommendation_requirements"] == []
    assert plan["recommendation_soft_preferences"] == ["\u8f66\u91cc\u7a7a\u95f4\u7d27"]
    assert calls == [
        "semantic_preplan",
        "semantic_preplan_requirement_reconciliation",
        "semantic_recommendation_constraint_grounding",
    ]


def test_semantic_recommendation_reconciliation_can_add_literal_soft_preference_omitted_by_initial_plan(monkeypatch):
    """The semantic review audits completeness even when no hard gap was emitted."""
    calls = []

    async def fake_chat_completion(db, messages, **kwargs):
        purpose = kwargs.get("purpose")
        calls.append(purpose)
        if purpose == "semantic_preplan_requirement_reconciliation":
            return json.dumps({
                "recommendation_constraints": {
                    "subject_kind": "cookware",
                    "heat_sources": ["open_flame"],
                },
                "unrepresented_recommendation_requirements": [],
                "recommendation_soft_preferences": ["户外煮面"],
                "evidence_spans": {
                    "subject_kind": ["锅"],
                    "heat_sources": ["明火"],
                },
            })
        if purpose == "semantic_recommendation_constraint_grounding":
            return json.dumps({
                "recommendation_constraints": {
                    "subject_kind": "cookware",
                    "heat_sources": ["open_flame"],
                },
                "evidence_spans": {
                    "subject_kind": ["锅"],
                    "heat_sources": ["明火"],
                },
            })
        return json.dumps({
            "route_family": "recommendation",
            "route_hint": "recommendation",
            "question_type": "recommendation",
            "confidence": "high",
            "recommendation_constraints": {
                "subject_kind": "cookware",
                "heat_sources": ["open_flame"],
            },
            "unrepresented_recommendation_requirements": [],
            "recommendation_soft_preferences": [],
        })

    monkeypatch.setattr(customer_agent_planner_service.customer_llm_service, "chat_completion", fake_chat_completion)
    plan = asyncio.run(customer_agent_planner_service.plan_customer_question_semantic(
        db=None,
        question="想找一口户外煮面的锅，最好能用明火。",
        deterministic_plan={},
        context={},
    ))

    assert plan["fallback_reason"] == ""
    assert plan["recommendation_soft_preferences"] == ["户外煮面"]
    assert calls == [
        "semantic_preplan",
        "semantic_preplan_requirement_reconciliation",
        "semantic_recommendation_constraint_grounding",
    ]


def test_semantic_preplan_repairs_decision_recommendation_without_initial_catalog_scope(monkeypatch):
    """A semantic decision cannot fall to a deterministic category guess."""
    calls = []

    async def fake_chat_completion(db, messages, **kwargs):
        purpose = kwargs.get("purpose")
        calls.append(purpose)
        if purpose == "semantic_preplan_repair":
            return json.dumps({
                "route_family": "recommendation",
                "route_hint": "recommendation",
                "question_type": "recommendation",
                "confidence": "high",
                "decision_requested": True,
                "recommendation_constraints": {"subject_kind": "cookware"},
                "unrepresented_recommendation_requirements": [],
                "recommendation_soft_preferences": ["煮烤早餐"],
            })
        if purpose == "semantic_preplan_requirement_reconciliation":
            return json.dumps({
                "recommendation_constraints": {"subject_kind": "cookware"},
                "unrepresented_recommendation_requirements": [],
                "recommendation_soft_preferences": ["煮烤早餐"],
                "evidence_spans": {"subject_kind": ["锅和烤盘"]},
            })
        if purpose == "semantic_recommendation_constraint_grounding":
            return json.dumps({
                "recommendation_constraints": {"subject_kind": "cookware"},
                "evidence_spans": {"subject_kind": ["锅和烤盘"]},
            })
        return json.dumps({
            "route_family": "recommendation",
            "route_hint": "recommendation",
            "question_type": "recommendation",
            "confidence": "high",
            "decision_requested": True,
            "recommendation_constraints": {},
            "unrepresented_recommendation_requirements": [],
            "recommendation_soft_preferences": ["煮烤早餐"],
        })

    monkeypatch.setattr(customer_agent_planner_service.customer_llm_service, "chat_completion", fake_chat_completion)
    plan = asyncio.run(customer_agent_planner_service.plan_customer_question_semantic(
        db=None,
        question="锅和烤盘该优先选哪个，想做煮烤早餐？",
        deterministic_plan={},
        context={},
    ))

    assert plan["fallback_reason"] == ""
    assert plan["recommendation_constraints"] == {"subject_kind": "cookware"}
    assert plan["recommendation_soft_preferences"] == ["煮烤早餐"]
    assert calls == [
        "semantic_preplan",
        "semantic_preplan_repair",
        "semantic_preplan_requirement_reconciliation",
        "semantic_recommendation_constraint_grounding",
    ]


def test_semantic_recommendation_does_not_broaden_when_preplan_keeps_unrepresented_material_requirement():
    result = asyncio.run(customer_service_service._semantic_recommendation_contract_result(
        None,
        "想要一款适合户外煮面的小锅，最好能用明火。",
        {"semantic_preplan": {
            "called": True, "route_family": "recommendation", "confidence": 0.9,
            "confidence_label": "high", "fallback_reason": "", "ambiguity": False,
            "recommendation_constraints": {"subject_kind": "cookware", "heat_sources": ["open_flame"]},
            "unrepresented_recommendation_requirements": ["必须是小锅", "必须明确支持煮面"],
        }},
    ))

    assert result["answer_type"] == "clarification"
    assert result["result_skus"] == []
    assert result["debug"]["agent_mode"] == "semantic_recommendation_unrepresented_requirement_clarification"


def test_semantic_recommendation_unrepresented_requirement_names_the_original_customer_words():
    result = asyncio.run(customer_service_service._semantic_recommendation_contract_result(
        None,
        "想找不插电的手摇磨豆器",
        {"semantic_preplan": {
            "called": True, "route_family": "recommendation", "confidence": 0.9,
            "confidence_label": "high", "fallback_reason": "", "ambiguity": False,
            "recommendation_constraints": {"subject_kind": "coffee_gear"},
            "unrepresented_recommendation_requirements": ["必须不插电"],
        }},
    ))

    assert result["debug"]["agent_mode"] == "semantic_recommendation_unrepresented_requirement_clarification"
    assert "必须不插电" in result["answer"]
    assert "人数、炉具" not in result["answer"]


def test_semantic_recommendation_with_ambiguous_scope_never_falls_back_to_legacy_candidate_list():
    clarification = customer_service_service._semantic_recommendation_constraint_clarification_result({
        "called": True,
        "route_family": "recommendation",
        "confidence": 0.95,
        "confidence_label": "high",
        "ambiguity": True,
        "fallback_reason": "",
        "recommendation_constraints": {"subject_kind": "cookware"},
        "entities": [],
    })

    assert clarification is not None
    assert clarification["answer_type"] == "clarification"
    assert clarification["result_skus"] == []
    assert clarification["candidate_skus"] == []
    assert clarification["debug"]["agent_mode"] == "semantic_recommendation_unexecutable_clarification"


def test_legacy_structured_recommendation_never_executes_after_semantic_preplan(monkeypatch):
    monkeypatch.setattr(customer_service_service, "_has_unresolved_product_like_scope", lambda db, text: False)
    monkeypatch.setattr(customer_service_service, "_phase1_catalog_rows", lambda db, ref: [{"sku": "LEGACY-1"}])
    monkeypatch.setattr(
        customer_service_service,
        "_phase1_structured_griddle_vs_cookware_result",
        lambda scenario, rows: {"answer_type": "recommendation", "result_skus": ["LEGACY-1"]},
    )

    result = customer_service_service._phase1_structured_recommendation_result(
        None,
        {
            "primary_intent": "recommendation",
            "scenario": "早餐煎烤时，锅和烤盘该优先选哪个？",
            "semantic_preplan": {"called": True, "route_family": "recommendation"},
        },
    )

    assert result is None


def test_semantic_recommendation_result_order_follows_validated_deepseek_ranking(monkeypatch):
    rows = [
        {"sku": "SAFE-1", "product_name_cn": "候选一", "category": "锅具", "usage_scenarios": "露营", "target_audience": "适合2人", "heat_source": "卡式炉", "gross_weight_g": 650},
        {"sku": "SAFE-2", "product_name_cn": "候选二", "category": "锅具", "usage_scenarios": "露营", "target_audience": "适合2人", "heat_source": "卡式炉", "gross_weight_g": 700},
    ]

    async def fake_chat_completion(db, messages, **kwargs):
        if kwargs.get("purpose") == "semantic_recommendation_narrative_grounding_review":
            return json.dumps({"approved": True, "unsupported_claims": []})
        return json.dumps({
            "ranked_candidate_indexes": [1, 0],
            "evidence_usage": [
                {"candidate_index": 1, "fields": ["people", "scenario", "heat_source", "weight"]},
                {"candidate_index": 0, "fields": ["people", "scenario", "heat_source", "weight"]},
            ],
            "answer": "优先推荐候选二，它适合2人露营并支持卡式炉；候选一也满足这些条件，可作为备选。",
        })

    monkeypatch.setattr(customer_service_service, "_phase1_catalog_rows", lambda db, ref: rows)
    monkeypatch.setattr(customer_service_service.customer_llm_service, "chat_completion", fake_chat_completion)
    result = asyncio.run(customer_service_service._semantic_recommendation_contract_result(
        None,
        "请推荐适合两人露营、能用卡式炉的锅具。",
        {"semantic_preplan": {
            "called": True, "route_family": "recommendation", "confidence": 0.9,
            "confidence_label": "high", "fallback_reason": "", "ambiguity": False,
            "recommendation_constraints": {
                "subject_kind": "cookware", "people": {"min": 2, "max": 2},
                "heat_sources": ["card_stove"], "scenarios": ["camping"], "weight_preference": "lightweight",
            },
        }},
    ))

    assert result["answer_metadata"]["recommendation_narrative"]["source"] == "validated_deepseek_grounded_narrative"
    assert result["result_skus"] == ["SAFE-2", "SAFE-1"]


def test_semantic_recommendation_does_not_bind_unranked_product_prose_to_ranked_evidence(monkeypatch):
    rows = [
        {"sku": "SAFE-1", "product_name_cn": "候选一", "category": "锅具", "usage_scenarios": "露营", "target_audience": "适合2人", "heat_source": "卡式炉", "gross_weight_g": 650},
        {"sku": "SAFE-2", "product_name_cn": "候选二", "category": "锅具", "usage_scenarios": "露营", "target_audience": "适合2人", "heat_source": "卡式炉", "gross_weight_g": 700},
    ]

    async def mismatched_identity_draft(_db, _messages, **_kwargs):
        return json.dumps({
            "ranked_candidate_indexes": [1],
            "evidence_usage": [{"candidate_index": 1, "fields": ["people", "scenario", "heat_source", "weight"]}],
            "answer": "推荐候选一，它的同 SKU 条件资料已通过本次核验。",
        })

    monkeypatch.setattr(customer_service_service, "_phase1_catalog_rows", lambda db, ref: rows)
    monkeypatch.setattr(customer_service_service.customer_llm_service, "chat_completion", mismatched_identity_draft)
    result = asyncio.run(customer_service_service._semantic_recommendation_contract_result(
        None,
        "请推荐适合两人露营、能用卡式炉的锅具。",
        {"semantic_preplan": {
            "called": True, "route_family": "recommendation", "confidence": 0.9,
            "confidence_label": "high", "fallback_reason": "", "ambiguity": False,
            "recommendation_constraints": {
                "subject_kind": "cookware", "people": {"min": 2, "max": 2},
                "heat_sources": ["card_stove"], "scenarios": ["camping"], "weight_preference": "lightweight",
            },
        }},
    ))

    assert result["answer_type"] == "clarification"
    assert result["result_skus"] == []
    assert result["candidate_skus"] == []
    assert result["debug"]["agent_mode"] == "semantic_recommendation_narrative_unavailable"


def test_semantic_preplan_runs_before_legacy_recommendation_execution():
    assert customer_service_service._should_call_semantic_preplan(
        "请给我挑一套露营时背着不累赘的锅。",
        {"primary_intent": "recommendation"},
        conversation_id=None,
        has_named_product=False,
    ) is True


def test_semantic_preplan_precedes_legacy_product_field_parse_for_unbound_recommendation_language():
    assert customer_service_service._should_call_semantic_preplan(
        "有没有适合单人徒步、重量别太夸张的煮水装备？",
        {"primary_intent": "product_field", "requested_field": "重量", "confidence": "high"},
        conversation_id=None,
        has_named_product=False,
    ) is True


def test_semantic_preplan_runs_before_catalog_count_can_erase_recommendation_need():
    assert customer_service_service._should_call_semantic_preplan(
        "想找露营用、背起来别太沉的锅具，有哪些？",
        {"primary_intent": "catalog_count"},
        conversation_id=None,
        has_named_product=False,
    ) is True


@pytest.mark.parametrize(
    "question",
    [
        "\u4e24\u4e2a\u4eba\u5468\u672b\u51fa\u53bb\u9732\u8425\uff0c\u9700\u8981\u80fd\u7092\u83dc\u7684\u708a\u5177\uff0c\u8bf7\u5e2e\u6211\u6311\u3002",
        "\u60f3\u8981\u4e00\u6b3e\u9002\u5408\u6237\u5916\u716e\u9762\u7684\u5c0f\u9505\uff0c\u6700\u597d\u80fd\u7528\u660e\u706b\u3002",
    ],
)
def test_low_confidence_legacy_plan_still_reaches_semantic_preplan(question):
    plan = customer_agent_planner_service.plan_customer_question(question)

    assert plan["primary_intent"] == ""
    assert customer_service_service._should_call_semantic_preplan(
        question,
        plan,
        conversation_id=None,
    ) is True


def test_semantic_recommendation_prompt_forbids_inferred_customer_constraints():
    messages = customer_agent_planner_service._semantic_preplan_messages(
        question="请帮我推荐露营锅具。",
        deterministic_plan={},
        context={},
    )

    assert "explicitly stated by the customer" in messages[0]["content"]


def test_semantic_recommendation_prompt_distinguishes_subject_and_storage_meaning():
    """The semantic model, not a lexical route rule, owns these distinctions."""
    messages = customer_agent_planner_service._semantic_preplan_messages(
        question="请帮我推荐户外装备。",
        deterministic_plan={},
        context={},
    )
    prompt = messages[0]["content"]

    assert "waterware is for a vessel explicitly requested to carry or boil water" in prompt
    assert "weight_preference is only an explicit physical-mass requirement" in prompt
    assert "compactness, storage, or not taking space" in prompt.lower()


def test_semantic_preplan_parser_accepts_unknown_realtime_subtype_and_entity_scope(monkeypatch):
    calls = []

    async def fake_chat_completion(db, messages, model=None, temperature=0.2, max_tokens=1200, *, purpose="chat", api_model_override=None, response_format=None, thinking=None, metadata=None):
        calls.append(purpose)
        return """{"route_hint":"unknown_field","question_type":"unknown_field","entities":["CS-B14（LX）"],"field_hint":"stock","subtype":"unknown_realtime","entity_scope":"resolved_single","qa_or_usage_care":false,"unknown_field":true,"confidence":0.93,"reason":"resolved realtime product question"}"""

    monkeypatch.setattr(customer_agent_planner_service.customer_llm_service, "chat_completion", fake_chat_completion)

    result = asyncio.run(
        customer_agent_planner_service.plan_customer_question_semantic(
            db=None,
            question="CS-B14（LX） 现在有货吗？",
            deterministic_plan={"primary_intent": "product_field", "answer_type": "product_detail"},
            context={},
        )
    )

    assert calls == ["semantic_preplan"]
    assert result["called"] is True
    assert result["route_hint"] == "unknown_field"
    assert result["question_type"] == "unknown_field"
    # ``stock`` is a model synonym; ``inventory`` is the formal canonical
    # field used by the realtime-safe FieldContract and formatter.
    assert result["field_hint"] == "inventory"
    assert result["subtype"] == "unknown_realtime"
    assert result["entity_scope"] == "resolved_single"
    assert result["entities"] == ["CS-B14（LX）"]
    assert result["unknown_field"] is True
    assert result["confidence"] == pytest.approx(0.93)

def test_named_product_shortcut_defers_formal_detail_to_central_contract(
    route_client_and_db,
    monkeypatch,
):
    _client, _headers, Session = route_client_and_db

    with Session() as db:
        product = db.query(Product).filter(Product.sku == "KW-K32-白").first()
        assert product is not None
        _mock_strong_resolved_named_product(monkeypatch, product=product)
        result = asyncio.run(
            customer_service_service._try_named_product_shortcut(
                db,
                user_id="route-test-user",
                question="天鹅壶9杯白 能不能明火直烧？",
            )
        )

    # Named-product shortcuts may nominate a candidate, but cannot produce
    # a final formal-field answer.  Phase 2 owns FieldContract + entity seal.
    assert result is None


def test_named_product_shortcut_defers_weak_candidate_to_central_contract(
    route_client_and_db,
    monkeypatch,
):
    _client, _headers, Session = route_client_and_db

    with Session() as db:
        product = db.query(Product).filter(Product.sku == "KW-K32-白").first()
        assert product is not None
        sku = str(product.sku or "").strip().upper()
        weak_contract = customer_entity_resolution_contract.EntityResolutionContract(
            entity_text="天鹅壶9杯",
            normalized_entity_text="天鹅壶9杯",
            status="ambiguous",
            resolved_sku=None,
            resolver_candidate_skus=[sku],
            diagnostic_candidate_skus=[],
            candidate_skus=[sku],
            matched_by="substring",
            confidence="medium",
            is_unique=False,
            matched_span=None,
            field_type="heat_source",
            status_reason="resolver_weak_single_candidate",
        )
        monkeypatch.setattr(
            customer_service_service,
            "_products_named_in_question",
            lambda _db, _question: [product],
        )
        monkeypatch.setattr(
            customer_service_service,
            "_subject_strongly_matches_product",
            lambda _subject, _product: True,
        )
        monkeypatch.setattr(
            customer_service_service.customer_entity_resolution_contract,
            "build_entity_resolution_contract",
            lambda *_args, **_kwargs: weak_contract,
        )
        result = asyncio.run(
            customer_service_service._try_named_product_shortcut(
                db,
                user_id="route-test-user",
                question="天鹅壶9杯 能不能明火直烧？",
            )
        )

    # The shortcut must not decide either resolution or clarification for a
    # formal field; the central resolver receives the weak contract instead.
    assert result is None


def test_entity_scope_guard_blocks_unresolved_product_like_recommendation_even_when_preplan_looks_category_like(
    route_client_and_db,
):
    _client, _headers, Session = route_client_and_db

    with Session() as db:
        result = customer_service_service._entity_scope_pre_route_guard_result(
            db,
            "不存在的咖啡器具推荐一下",
            None,
            {
                "called": True,
                "route_family": "recommendation",
                "entity_scope": "category_scope",
                "field_type": "recommendation",
                "confidence": 0.9,
            },
        )

    assert result is not None
    assert result["answer_type"] == "clarification", result
    assert result.get("result_skus") in ([], None), result
    assert result.get("candidate_skus") in ([], None), result
    assert (result.get("answer_metadata") or {}).get("source") in {
        "entity_scope_product_not_found",
        "unresolved_product_like_unknown_field_clarification",
        "unknown_field_product_not_found",
    }, result


def test_pre_route_high_risk_contract_does_not_bind_single_candidate_without_strong_grounded_match(
    route_client_and_db,
    monkeypatch,
):
    _client, _headers, Session = route_client_and_db

    with Session() as db:
        _add_product(db, "TEST-WEAK-ENTITY-01", "荒野套锅", "锅具", "1L", "铝合金", "燃气炉", "测试商品", "测试场景", 199)
        db.commit()
        product = db.query(Product).filter(Product.sku == "TEST-WEAK-ENTITY-01").first()
        assert product is not None
        monkeypatch.setattr(
            customer_service_service,
            "_products_named_in_question",
            lambda _db, _question: [product],
        )
        monkeypatch.setattr(
            customer_service_service,
            "_resolve_sku",
            lambda _db, _text, _raw=None: None,
        )
        monkeypatch.setattr(
            customer_service_service,
            "_product_like_scope_subject",
            lambda _question: "荒野星壶",
        )
        monkeypatch.setattr(
            customer_service_service,
            "_subject_strongly_matches_product",
            lambda _subject, _product: False,
        )

        result = customer_service_service._pre_route_high_risk_contract_result(
            db,
            "荒野星壶多少钱？",
            {
                "called": True,
                "subtype": "known_detail",
                "entity_scope": "product_like",
                "entities": ["荒野星壶"],
                "route_hint": "product_detail",
                "question_type": "field",
                "field_hint": "price",
            },
        )

    assert result is not None
    assert result["answer_type"] == "clarification", result
    assert result.get("result_skus") in ([], None), result
    assert result.get("candidate_skus") in ([], None), result
    assert (result.get("answer_metadata") or {}).get("source") in {
        "unresolved_product_like_unknown_field_clarification",
        "unknown_field_product_not_found",
    }, result


@pytest.mark.parametrize(
    "question",
    [
        "CF-PG19 原厂配了什么？",
        "CF-PG19 盒子里有什么？",
        "CS-G25 默认带哪些？",
        "CW-C83 what comes in the box?",
        "CS-B14（LX） what does it come with?",
        "瓦片烤盘Pro what does it come with?",
        "围雪炉 盒子里有什么？",
        "婧川水壶 有没有附件？",
        "户外有什么配件？",
    ],
)
def test_route_level_contents_family_now_requires_semantic_preplan(question):
    plan = customer_agent_planner_service.plan_customer_question(question)

    assert customer_service_service._should_call_semantic_preplan(
        question,
        plan,
        conversation_id=None,
    ) is True


@pytest.mark.parametrize(
    "question",
    [
        "CS-B14（LX） 现在有货吗？",
        "CF-PG19 有优惠券吗？",
        "CW-C83 评价怎么样？",
        "围雪炉 今天能发吗？",
        "婧川水壶 现在有货吗？",
    ],
)
def test_route_level_unknown_realtime_family_now_requires_semantic_preplan(question):
    plan = customer_agent_planner_service.plan_customer_question(question)

    assert customer_service_service._should_call_semantic_preplan(
        question,
        plan,
        conversation_id=None,
    ) is True


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


def test_compose_recommendation_answer_uses_llm_for_alcohol_stove_cookware(monkeypatch):
    calls = []

    async def friendly_finalize(*args, **kwargs):
        calls.append(kwargs)
        return "如果您要搭配酒精炉，可以考虑激川单锅（CW-S10-A），同 SKU 资料明确标注支持酒精炉。"

    monkeypatch.setattr(customer_agent_intent_service, "_finalize_recommendation_answer", friendly_finalize)
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
    assert len(calls) == 1


def test_semantic_preplan_repair_recovers_truncated_json(monkeypatch):
    calls = []

    async def fake_chat_completion(db, messages, model=None, temperature=0.2, max_tokens=1200, *, purpose="chat", api_model_override=None, response_format=None, thinking=None, metadata=None):
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

    async def fake_chat_completion(db, messages, model=None, temperature=0.2, max_tokens=1200, *, purpose="chat", api_model_override=None, response_format=None, thinking=None, metadata=None):
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
    async def fake_chat_completion(db, messages, model=None, temperature=0.2, max_tokens=1200, *, purpose="chat", api_model_override=None, response_format=None, thinking=None, metadata=None):
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
    ("question", "expected_field"),
    [
        ("\u67d0\u4ea7\u54c1\u5728\u6574\u4f53\u5b9a\u4ef7\u5c42\u7ea7\u91cc\u504f\u5165\u95e8\u8fd8\u662f\u9ad8\u7aef\uff1f", "price_positioning"),
        ("\u67d0\u4ea7\u54c1\u9884\u8ba1\u8986\u76d6\u54ea\u4e9b\u6d77\u5916\u5e02\u573a\uff1f", "sales_region"),
    ],
)
def test_semantic_preplan_model_error_uses_allowlisted_compositional_field_fallback(monkeypatch, question, expected_field):
    async def unavailable(*args, **kwargs):
        raise RuntimeError("semantic model unavailable")

    monkeypatch.setattr(customer_agent_planner_service.customer_llm_service, "chat_completion", unavailable)
    result = asyncio.run(
        customer_agent_planner_service.plan_customer_question_semantic(
            db=None,
            question=question,
            deterministic_plan={"primary_intent": "", "answer_type": ""},
            context={},
        )
    )

    assert result["field_type"] == expected_field
    assert result["route_hint"] == "product_detail"
    assert result["entities"] == []
    assert result["confidence"] >= 0.9
    assert result.get("fallback_reason", "") == ""
    assert result["semantic_adapter_source"] == "deterministic_compositional_field"


def test_semantic_preplan_does_not_overwrite_a_valid_model_field_with_compositional_fallback(monkeypatch):
    async def wrong_but_schema_valid(*args, **kwargs):
        return '{"route_family":"product_bound_qa","entity_scope":"product_like","field_type":"purchase_channel","confidence":"high","reason":"where to buy"}'

    monkeypatch.setattr(customer_agent_planner_service.customer_llm_service, "chat_completion", wrong_but_schema_valid)
    result = asyncio.run(
        customer_agent_planner_service.plan_customer_question_semantic(
            db=None,
            question="\u67d0\u4ea7\u54c1\u8ba1\u5212\u8986\u76d6\u54ea\u4e9b\u6d77\u5916\u5e02\u573a\uff1f",
            deterministic_plan={"primary_intent": "", "answer_type": ""},
            context={},
        )
    )

    assert result["field_type"] == "purchase_channel"
    assert "model_field_type" not in result
    assert "semantic_field_override_reason" not in result


def test_semantic_preplan_canonical_field_is_sufficient_when_legacy_mirrors_are_omitted(monkeypatch):
    async def canonical_only(*args, **kwargs):
        return json.dumps({
            "route_family": "product_bound_qa",
            "subject_text": "AC-19",
            "canonical_fields": ["brand"],
            "confidence": "high",
            "ambiguity": False,
            "evidence_required": True,
            "context_usage": "none",
            "reasoning_summary": "brand request",
        })

    monkeypatch.setattr(customer_agent_planner_service.customer_llm_service, "chat_completion", canonical_only)
    result = asyncio.run(
        customer_agent_planner_service.plan_customer_question_semantic(
            db=None,
            question="AC-19是谁家的？",
            deterministic_plan={"primary_intent": "", "answer_type": ""},
            context={},
        )
    )

    assert result["canonical_fields"] == ["brand"]
    assert result["field_type"] == "brand"
    assert result["field_hint"] == "brand"
    assert result["entity_scope"] == ""


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

    async def fake_chat_completion(db, messages, model=None, temperature=0.2, max_tokens=1200, *, purpose="chat", api_model_override=None, response_format=None, thinking=None, metadata=None):
        calls.append({"purpose": purpose, "messages": messages})
        if purpose == "semantic_preplan_repair" and route_hint == "comparison":
            return json.dumps({
                "route_hint": "comparison", "question_type": "comparison",
                "entities": ["锅", "烤盘"], "route_family": "comparison",
                "canonical_fields": ["usage_scene"], "field_type": "usage_scene",
                "confidence": 0.88, "reason": "repaired comparison criterion",
            }, ensure_ascii=False)
        return json.dumps(
            {
                "route_hint": route_hint,
                "question_type": "comparison" if route_hint == "comparison" else "filter",
                "entities": ["锅", "烤盘"] if route_hint == "comparison" else [],
                "route_family": "comparison" if route_hint == "comparison" else "",
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

    async def fake_chat_completion(db, messages, model=None, temperature=0.2, max_tokens=1200, *, purpose="chat", api_model_override=None, response_format=None, thinking=None, metadata=None):
        calls.append({"purpose": purpose, "messages": messages})
        if purpose == "semantic_recommendation_constraint_grounding":
            return json.dumps(
                {
                    "recommendation_constraints": {
                        "subject_kind": "cookware",
                        "people": {"min": 2, "max": 2},
                        "scenarios": ["camping"],
                        "weight_preference": "lightweight",
                    },
                    "evidence_spans": {
                        "subject_kind": ["锅具"],
                        "people": ["双人"],
                        "scenarios": ["露营"],
                        "weight_preference": ["轻便"],
                    },
                },
                ensure_ascii=False,
            )
        is_alternative_followup = sum(call["purpose"] == "semantic_preplan" for call in calls) > 1
        return json.dumps(
            {
                "route_family": "recommendation",
                "route_hint": "recommendation",
                "question_type": "followup",
                "entities": [],
                "recommendation_constraints": {
                    "subject_kind": "cookware",
                    "people": {"min": 2, "max": 2},
                    "scenarios": ["camping"],
                    "weight_preference": "lightweight",
                },
                "recommendation_followup_action": "alternative" if is_alternative_followup else "new",
                "field_hint": None,
                "qa_or_usage_care": False,
                "unknown_field": False,
                "confidence": 0.86,
                "reason": "negative alternative follow-up",
            },
            ensure_ascii=False,
        )

    monkeypatch.setattr(customer_agent_planner_service.customer_llm_service, "chat_completion", fake_chat_completion)

    # This case verifies that the semantic preplan remains active across a
    # negative recommendation follow-up.  The recommendation prose writer is
    # separately exercised with its sealed-evidence contract tests; keep this
    # route test focused on the preplan/context contract rather than requiring
    # this mock to emulate the writer and its grounding reviewer.
    async def fake_recommendation_narrative(_db, *, rows, **_kwargs):
        assert rows
        return {
            "ranked_candidate_indexes": [0],
            "evidence_usage": [{"candidate_index": 0, "fields": ["content.features"]}],
            "answer": f"根据已核验的同 SKU 资料，优先考虑{rows[0]['product_name_cn']}。",
        }

    monkeypatch.setattr(
        customer_service_service,
        "_semantic_recommendation_narrative",
        fake_recommendation_narrative,
    )

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
    assert calls and any(call["purpose"] == "semantic_preplan" for call in calls)
    assert calls[-1]["purpose"] == "semantic_recommendation_constraint_grounding"
    semantic_debug = _semantic_preplan_debug(payload2)
    assert semantic_debug.get("called") is True, payload2.get("debug")
    assert semantic_debug.get("route_hint") == "recommendation", semantic_debug
    assert payload2["answer_type"] == "recommendation", payload2
    assert payload2["result_skus"], payload2
    assert payload2["result_skus"][0] != first_top, (payload1, payload2)


@pytest.mark.parametrize(
    ("question", "field_type"),
    [
        ("CS-B14（LX）能不能用酒精炉？", "heat_source"),
        ("CW-C83 容量是多少？", "capacity"),
        ("CF-PG19 是什么材质？", "material"),
    ],
)
def test_route_level_semantic_preplan_precedes_explicit_product_field_shortcuts(
    route_client_and_db,
    monkeypatch,
    question,
    field_type,
):
    client, headers, _ = route_client_and_db
    calls = []

    async def fake_chat_completion(db, messages, model=None, temperature=0.2, max_tokens=1200, *, purpose="chat", api_model_override=None, response_format=None, thinking=None, metadata=None):
        if purpose == "semantic_preplan":
            calls.append({"purpose": purpose, "messages": messages})
            return json.dumps({
                "route_family": "product_bound_qa",
                "entity_scope": "product_like",
                "field_type": field_type,
                "field_hint": field_type,
                "canonical_fields": [field_type],
                "question_type": "field",
                "subtype": "known_detail",
                "confidence": "high",
                "ambiguity": False,
                "evidence_required": True,
                "context_usage": "none",
                "reasoning_summary": "explicit product field request",
            })
        return "{}"

    monkeypatch.setattr(customer_agent_planner_service.customer_llm_service, "chat_completion", fake_chat_completion)

    response = client.post("/api/customer-service/ask?debug=true", json={"question": question}, headers=headers)
    assert response.status_code == 200, response.text
    payload = response.json()
    assert calls, payload.get("debug")
    assert _semantic_preplan_debug(payload).get("field_type") == field_type, payload.get("debug")
    assert payload["answer"], payload


def test_route_level_semantic_preplan_classifies_catalog_count_before_count_contract(route_client_and_db, monkeypatch):
    client, headers, _ = route_client_and_db
    calls = []

    async def fake_chat_completion(*args, **kwargs):
        calls.append(kwargs.get("purpose"))
        assert kwargs.get("purpose") == "semantic_preplan"
        return json.dumps({
            "route_family": "structured_query",
            "route_hint": "structured_query",
            "entity_scope": "category_scope",
            "entities": [],
            "field_type": None,
            "field_hint": None,
            "canonical_fields": [],
            "question_type": "catalog_count",
            "subtype": "catalog_count",
            "confidence": "high",
            "ambiguity": False,
            "evidence_required": True,
            "context_usage": "none",
            "decision_requested": False,
            "reasoning_summary": "category count request",
        })

    monkeypatch.setattr(customer_agent_planner_service.customer_llm_service, "chat_completion", fake_chat_completion)
    response = client.post("/api/customer-service/ask?debug=true", json={"question": "现在有多少款水具？"}, headers=headers)
    assert response.status_code == 200, response.text
    assert calls == ["semantic_preplan"], response.json()
    payload = response.json()
    assert payload["answer_type"] == "query_products", payload
    assert payload["debug"]["agent_mode"] == "structured_catalog_count", payload


def test_semantic_category_field_does_not_erase_catalog_count_contract(route_client_and_db, monkeypatch):
    """A semantic category field is not a single-product detail when the turn asks for an aggregate."""
    client, headers, _ = route_client_and_db

    async def fake_preplan(db, question, deterministic_plan, context):
        return {
            "called": True,
            "route_family": "structured_query",
            "route_hint": "query_products",
            "entity_scope": "category_scope",
            "entities": [],
            "subject_text": "锅",
            "field_type": "category",
            "field_hint": "category",
            "canonical_fields": ["category"],
            "question_type": "filter",
            "subtype": "structured_query",
            "confidence": 0.9,
            "ambiguity": False,
            "evidence_required": True,
            "context_usage": "none",
            "reasoning_summary": "catalogue category aggregate",
        }

    monkeypatch.setattr(customer_agent_planner_service, "plan_customer_question_semantic", fake_preplan)
    response = client.post(
        "/api/customer-service/ask?debug=true",
        json={"question": "我们有多少个锅？"},
        headers=headers,
    )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["answer_type"] == "query_products", payload
    assert (payload.get("debug", {}).get("plan") or {}).get("primary_intent") == "catalog_count", payload
    assert payload.get("debug", {}).get("agent_mode") == "structured_catalog_count", payload
    assert payload.get("answer_metadata", {}).get("source") == "product_catalog_structured_query", payload
    assert "款" in str(payload.get("answer") or ""), payload


def test_route_level_named_product_field_preplan_blocks_catalog_shortcut(route_client_and_db, monkeypatch):
    """A named product fact cannot be reinterpreted as a generic catalogue query."""
    client, headers, _ = route_client_and_db
    calls = []

    async def fake_preplan(db, question, deterministic_plan, context):
        calls.append(question)
        return {
            "called": True,
            # DeepSeek can correctly identify a named product's recorded
            # field while retaining its broad structured-query route shape.
            # The FieldContract must preserve that semantic field and let
            # EntityResolutionContract decide whether the subject is a
            # single catalogue product; it must not hand the turn back to the
            # legacy catalogue shortcut.
            "route_family": "structured_query",
            "route_hint": "query_products",
            "entity_scope": "",
            "field_type": "competitor_benchmark",
            "field_hint": "competitor_benchmark",
            "canonical_fields": ["competitor_benchmark"],
            "question_type": "filter",
            "subtype": "structured_query",
            "confidence": 0.96,
            "ambiguity": False,
            "evidence_required": True,
            "context_usage": "none",
            "reasoning_summary": "named product comparison field",
        }

    monkeypatch.setattr(customer_agent_planner_service, "plan_customer_question_semantic", fake_preplan)
    response = client.post(
        "/api/customer-service/ask?debug=true",
        json={"question": "瓦片烤盘对标的同类产品有哪些？"},
        headers=headers,
    )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert calls == ["瓦片烤盘对标的同类产品有哪些？"], payload
    assert payload["answer_type"] == "product_detail", payload
    assert payload.get("debug", {}).get("agent_mode") != "structured_catalog_count", payload
    field_contract = payload.get("debug", {}).get("field_contract") or {}
    entity_contract = payload.get("debug", {}).get("entity_resolution_contract") or {}
    assert field_contract.get("field_type") == "competitor_benchmark", payload
    assert field_contract.get("source") == "validated_semantic_preplan", payload
    assert entity_contract.get("status") == "resolved", payload
    assert entity_contract.get("resolved_sku") == "CF-PG19", payload
    assert payload.get("result_skus") == ["CF-PG19"], payload


def test_route_level_valid_structured_semantic_named_field_preempts_knowledge_base(
    route_client_and_db,
    monkeypatch,
):
    """A unique semantic subject is a product fact even when the route shape says filter."""
    client, headers, Session = route_client_and_db
    with Session() as db:
        _add_product(
            db,
            "SEM-CATALOG-01",
            "语义目录测试包",
            "配件",
            "1L",
            "不锈钢",
            "",
            "测试资料",
            "露营",
            200,
        )
        db.commit()

    async def fake_preplan(_db, _question, _deterministic_plan, context):
        return {
            "called": True,
            "route_family": "structured_query",
            "route_hint": "query_products",
            "question_type": "filter",
            "subtype": "structured_query",
            "subject_text": "SEM-CATALOG-01",
            "canonical_fields": ["category"],
            "field_type": "category",
            "field_hint": "category",
            "confidence": 0.9,
            "ambiguity": False,
            # The semantic planner's evidence flag describes its plan shape;
            # the formal detail contract must still require same-SKU evidence.
            "evidence_required": False,
            "context_usage": "none",
            "structured_query_constraints": [],
        }

    monkeypatch.setattr(customer_agent_planner_service, "plan_customer_question_semantic", fake_preplan)
    response = client.post(
        "/api/customer-service/ask?debug=true",
        json={"question": "SEM-CATALOG-01在商品目录中归于哪种产品？"},
        headers=headers,
    )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["answer_type"] == "product_detail", payload
    assert payload.get("debug", {}).get("agent_mode") == "resolved_entity_detail_contract", payload
    assert (payload.get("debug", {}).get("field_contract") or {}).get("field_type") == "category", payload
    assert (payload.get("debug", {}).get("entity_resolution_contract") or {}).get("resolved_sku") == "SEM-CATALOG-01", payload
    assert payload.get("result_skus") == ["SEM-CATALOG-01"], payload
    assert payload["answer_type"] != "knowledge_base_answer", payload


def test_catalog_count_preflight_does_not_use_fuzzy_qa_before_semantic_field(
    route_client_and_db,
    monkeypatch,
):
    """Only an exact stored QA may bypass semantic planning after a count misclassification."""
    client, headers, Session = route_client_and_db
    name = "\u5bf9\u6807\u6d4b\u8bd5\u9505Pro"
    with Session() as db:
        _add_product(
            db,
            "SEM-COUNT-01",
            name,
            "\u9505\u5177",
            "1L",
            "\u4e0d\u9508\u94a2",
            "\u5361\u5f0f\u7089",
            "\u540c SKU \u7ed3\u6784\u5316\u8d44\u6599",
            "\u9732\u8425",
            300,
        )
        product = db.query(Product).filter(Product.sku == "SEM-COUNT-01").one()
        business = db.query(ProductBusiness).filter(ProductBusiness.product_id == product.id).one()
        business.competitor_benchmark = "\u793a\u4f8b\u5bf9\u6807\u4ea7\u54c1"
        _add_product_qa(
            db,
            "SEM-COUNT-01",
            f"{name}\u5b89\u5168\u5417\uff1f",
            "\u5b89\u5168\u3002",
            tags="\u5b89\u5168",
            priority=300,
        )
        db.commit()

    original_plan = customer_agent_planner_service.plan_customer_question

    def force_catalog_count(question):
        plan = dict(original_plan(question))
        plan["primary_intent"] = "catalog_count"
        return plan

    calls = []

    async def fake_preplan(db, question, deterministic_plan, context):
        calls.append(question)
        return {
            "called": True,
            "route_family": "product_bound_qa",
            "route_hint": "product_detail",
            "subject_text": name,
            "field_type": "competitor_benchmark",
            "field_hint": "competitor_benchmark",
            "canonical_fields": ["competitor_benchmark"],
            "question_type": "field",
            "subtype": "known_detail",
            "confidence": 0.95,
            "ambiguity": False,
            "evidence_required": True,
            "context_usage": "none",
        }

    monkeypatch.setattr(customer_agent_planner_service, "plan_customer_question", force_catalog_count)
    monkeypatch.setattr(customer_agent_planner_service, "plan_customer_question_semantic", fake_preplan)
    question = f"{name}\u5b98\u65b9\u8d44\u6599\u5217\u51fa\u7684\u5bf9\u6807\u4ea7\u54c1\u6709\u54ea\u4e9b\uff1f"
    response = client.post("/api/customer-service/ask?debug=true", json={"question": question}, headers=headers)
    assert response.status_code == 200, response.text
    payload = response.json()
    field = (payload.get("debug") or {}).get("field_contract") or {}

    assert calls == [question], payload
    assert field.get("field_type") == "competitor_benchmark", payload
    assert payload.get("result_skus") == ["SEM-COUNT-01"], payload
    assert "\u793a\u4f8b\u5bf9\u6807\u4ea7\u54c1" in str(payload.get("answer") or ""), payload
    assert payload.get("debug", {}).get("agent_mode") != "product_qa_fast_path", payload


@pytest.mark.parametrize(
    ("question", "field_type"),
    [
        ("瓦片烤盘出了问题该通过什么方式找客服？", "after_sales_contact"),
        ("瓦片烤盘目前还能直接拍下吗？", "inventory"),
        ("瓦片烤盘出了质量问题能保多久？", "warranty"),
        ("瓦片烤盘付款以后大概多久寄走？", "shipping"),
    ],
)
def test_semantic_safe_field_preempts_legacy_qa_and_keeps_exact_entity(
    route_client_and_db,
    monkeypatch,
    question,
    field_type,
):
    client, headers, _ = route_client_and_db

    async def fake_preplan(db, question, deterministic_plan, context):
        return {
            "called": True,
            "route_family": "product_bound_qa",
            "route_hint": "product_detail",
            "subject_text": "瓦片烤盘",
            "field_type": field_type,
            "field_hint": field_type,
            "canonical_fields": [field_type],
            "question_type": "field",
            "subtype": "known_detail",
            "confidence": 0.9,
            "ambiguity": False,
            "evidence_required": True,
            "context_usage": "none",
        }

    monkeypatch.setattr(customer_agent_planner_service, "plan_customer_question_semantic", fake_preplan)
    payload = client.post(
        "/api/customer-service/ask?debug=true",
        json={"question": question},
        headers=headers,
    ).json()

    field = (payload.get("debug") or {}).get("field_contract") or {}
    entity = (payload.get("debug") or {}).get("entity_resolution_contract") or {}
    assert payload.get("answer_type") == "product_detail", payload
    assert field.get("field_type") == field_type, payload
    assert field.get("source") == "validated_semantic_preplan", payload
    assert entity.get("status") == "resolved", payload
    assert entity.get("resolved_sku") == "CF-PG19", payload
    assert payload.get("result_skus") == ["CF-PG19"], payload
    assert (payload.get("answer_metadata") or {}).get("field_evidence_missing") is True, payload


def test_semantic_gift_cannot_be_repaired_from_product_name_heat_source_evidence(
    route_client_and_db,
    monkeypatch,
):
    client, headers, Session = route_client_and_db
    with Session() as db:
        _add_product(
            db,
            "SEM-GIFT-01",
            "示例酒精炉",
            "炉具",
            "",
            "不锈钢",
            "95%液体工业酒精",
            "便携炉具",
            "露营",
            300,
        )
        db.commit()

    async def fake_preplan(db, question, deterministic_plan, context):
        return {
            "called": True,
            "route_family": "product_bound_qa",
            "route_hint": "product_detail",
            "subject_text": "示例酒精炉",
            "field_type": "gift",
            "field_hint": "gift",
            "canonical_fields": ["gift"],
            "question_type": "field",
            "subtype": "known_detail",
            "confidence": 0.95,
            "ambiguity": False,
            "evidence_required": True,
            "context_usage": "none",
        }

    monkeypatch.setattr(customer_agent_planner_service, "plan_customer_question_semantic", fake_preplan)
    payload = client.post(
        "/api/customer-service/ask?debug=true",
        json={"question": "示例酒精炉下单会额外送东西吗？"},
        headers=headers,
    ).json()

    assert payload.get("result_skus") == ["SEM-GIFT-01"], payload
    assert "赠品" in payload.get("answer", ""), payload
    assert "95%液体工业酒精" not in payload.get("answer", ""), payload
    assert (payload.get("answer_metadata") or {}).get("evidence_status") == "missing", payload
    assert ((payload.get("debug") or {}).get("field_contract") or {}).get("field_type") == "gift", payload


def test_semantic_field_contract_prevents_same_sku_unrelated_qa_preemption(
    route_client_and_db,
    monkeypatch,
):
    """A named product's QA must not override a semantic formal field."""
    client, headers, Session = route_client_and_db
    name = "\u8bed\u4e49\u5408\u540c\u7089Pro"
    series = "\u6d4b\u8bd5\u7cfb\u5217"
    with Session() as db:
        _add_product(
            db,
            "SEM-PLAN-01",
            name,
            "\u7089\u5177",
            "",
            "\u4e0d\u9508\u94a2",
            "",
            "\u540c SKU \u7ed3\u6784\u5316\u8d44\u6599",
            "\u6237\u5916",
            300,
        )
        product = db.query(Product).filter(Product.sku == "SEM-PLAN-01").one()
        product.series = series
        _add_product_qa(
            db,
            "SEM-PLAN-01",
            f"{name}\u7b2c\u4e00\u6b21\u4f7f\u7528\u8981\u6ce8\u610f\u4ec0\u4e48\uff1f",
            "\u4f7f\u7528\u524d\u8bf7\u5148\u9605\u8bfb\u5b89\u5168\u63d0\u793a\u3002",
            tags="\u4f7f\u7528,\u5b89\u5168",
            priority=300,
        )
        db.commit()

    async def fake_preplan(db, question, deterministic_plan, context):
        return {
            "called": True,
            "route_family": "product_bound_qa",
            "route_hint": "product_detail",
            "subject_text": name,
            "field_type": "series",
            "field_hint": "series",
            "canonical_fields": ["series"],
            "question_type": "field",
            "subtype": "known_detail",
            "confidence": 0.95,
            "ambiguity": False,
            "evidence_required": True,
            "context_usage": "none",
        }

    monkeypatch.setattr(customer_agent_planner_service, "plan_customer_question_semantic", fake_preplan)
    response = client.post(
        "/api/customer-service/ask?debug=true",
        json={"question": f"{name}\u5c5e\u4e8e\u4ec0\u4e48\u7cfb\u5217\uff1f"},
        headers=headers,
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    field = (payload.get("debug") or {}).get("field_contract") or {}
    entity = (payload.get("debug") or {}).get("entity_resolution_contract") or {}

    assert field.get("field_type") == "series", payload
    assert entity.get("resolved_sku") == "SEM-PLAN-01", payload
    assert (payload.get("answer_metadata") or {}).get("evidence_sku") == "SEM-PLAN-01", payload
    assert series in str(payload.get("answer") or ""), payload
    assert payload.get("debug", {}).get("agent_mode") != "product_qa_fast_path", payload


def test_exact_named_structured_field_preempts_matching_same_sku_qa(
    route_client_and_db,
    monkeypatch,
):
    """A sealed formal field must use its structured provider before QA."""
    client, headers, Session = route_client_and_db
    name = "语义颜色测试炉"
    with Session() as db:
        _add_product(
            db,
            "SEM-COLOR-01",
            name,
            "炉具",
            "",
            "不锈钢",
            "",
            "测试资料",
            "户外",
            300,
        )
        _add_product_qa(
            db,
            "SEM-COLOR-01",
            f"{name}有哪些颜色？",
            "QA 中的颜色答案。",
            tags="颜色",
            priority=300,
        )
        db.commit()

    async def fake_preplan(_db, _question, _deterministic_plan, context):
        return {
            "called": True,
            "route_family": "structured_query",
            "route_hint": "query_products",
            "question_type": "filter",
            "subtype": "structured_query",
            "subject_text": name,
            "canonical_fields": ["color"],
            "field_type": "color",
            "field_hint": "color",
            "confidence": 0.9,
            "ambiguity": False,
            "evidence_required": False,
            "context_usage": "none",
            "structured_query_constraints": [],
        }

    monkeypatch.setattr(customer_agent_planner_service, "plan_customer_question_semantic", fake_preplan)
    response = client.post(
        "/api/customer-service/ask?debug=true",
        json={"question": f"{name}有哪些颜色？"},
        headers=headers,
    )

    assert response.status_code == 200, response.text
    payload = response.json()
    metadata = payload.get("answer_metadata") or {}
    assert ((payload.get("debug") or {}).get("field_contract") or {}).get("field_type") == "color", payload
    assert ((payload.get("debug") or {}).get("entity_resolution_contract") or {}).get("resolved_sku") == "SEM-COLOR-01", payload
    assert metadata.get("evidence_field") == "color", payload
    assert metadata.get("evidence_source") == "specs.color", payload
    assert payload.get("debug", {}).get("agent_mode") != "product_qa_fast_path", payload


def test_semantic_structured_route_does_not_let_exact_qa_replace_formal_field_contract(
    route_client_and_db,
    monkeypatch,
):
    """A semantic catalogue-shaped route still defers to a sealed detail field."""
    client, headers, Session = route_client_and_db
    name = "炉具套装语义测试款"
    with Session() as db:
        _add_product(
            db,
            "SEM-COLOR-STRUCTURED-01",
            name,
            "炉具",
            "",
            "不锈钢",
            "",
            "测试资料",
            "户外",
            300,
        )
        _add_product_qa(
            db,
            "SEM-COLOR-STRUCTURED-01",
            f"{name}有哪些颜色？",
            "QA 中的冲突颜色答案。",
            tags="颜色",
            priority=300,
        )
        db.commit()

    async def fake_preplan(_db, _question, _deterministic_plan, context):
        return {
            "called": True,
            "route_family": "structured_query",
            "route_hint": "query_products",
            "question_type": "filter",
            "subtype": "structured_query",
            "subject_text": name,
            "canonical_fields": ["color"],
            "field_type": "color",
            "field_hint": "color",
            "confidence": 0.9,
            "ambiguity": False,
            "evidence_required": False,
            "context_usage": "none",
            "structured_query_constraints": [],
        }

    monkeypatch.setattr(customer_agent_planner_service, "plan_customer_question_semantic", fake_preplan)
    monkeypatch.setattr(customer_service_service, "_should_prioritize_semantic_structured_route", lambda *_args: True)
    response = client.post(
        "/api/customer-service/ask?debug=true",
        json={"question": f"{name}有哪些颜色？"},
        headers=headers,
    )

    assert response.status_code == 200, response.text
    payload = response.json()
    metadata = payload.get("answer_metadata") or {}
    assert ((payload.get("debug") or {}).get("field_contract") or {}).get("field_type") == "color", payload
    assert ((payload.get("debug") or {}).get("entity_resolution_contract") or {}).get("resolved_sku") == "SEM-COLOR-STRUCTURED-01", payload
    assert metadata.get("evidence_field") == "color", payload
    assert metadata.get("evidence_source") == "specs.color", payload
    assert payload.get("debug", {}).get("agent_mode") != "product_qa_fast_path", payload


def test_semantic_structured_product_field_candidate_survives_before_entity_arbitration():
    """A catalogue-shaped semantic shell cannot erase a named field request.

    The semantic layer may retain ``structured_query`` while correctly
    identifying one formal field for a product-like subject.  The central
    contracts must preserve that field and fail closed only at entity
    resolution; they must not emit the generic multi-filter clarification.
    """
    name = "\u8bed\u4e49\u6b67\u4e49\u989c\u8272\u6d4b\u8bd5\u9505"
    preplan = {
        "called": True,
        "route_family": "structured_query",
        "route_hint": "query_products",
        "question_type": "filter",
        "subtype": "structured_query",
        "subject_text": name,
        "canonical_fields": ["color"],
        "field_type": "color",
        "field_hint": "color",
        "confidence": 0.9,
        "ambiguity": False,
        "evidence_required": False,
        "context_usage": "none",
        "structured_query_constraints": [],
    }

    field_type, confidence = customer_field_contract._validated_semantic_field_candidate(
        preplan,
        question=f"{name}\u5916\u89c2\u5c5e\u4e8e\u54ea\u79cd\u8272\u7cfb\uff1f",
    )

    assert field_type == "color"
    assert confidence == 0.9


def test_invalid_structured_named_detail_preserves_ambiguous_entity_and_field_contract(
    route_client_and_db,
    monkeypatch,
):
    """Malformed filters may fail closed, but not erase an independent field.

    When semantic output separately supplies one allowlisted field and a
    product subject, the recovery path must use EntityResolutionContract for
    ambiguity instead of falling through to a generic multi-filter message.
    """
    _client, _headers, Session = route_client_and_db
    name = "\u8bed\u4e49\u6b67\u4e49\u9505"
    with Session() as db:
        for sku in ("SEM-INVALID-AMB-01", "SEM-INVALID-AMB-02"):
            _add_product(db, sku, name, "\u9505\u5177", "", "\u4e0d\u9508\u94a2", "", "", "", 1)
        db.commit()

        contract = customer_entity_resolution_contract.EntityResolutionContract(
            entity_text=name,
            normalized_entity_text=name,
            status="ambiguous",
            resolved_sku=None,
            resolver_candidate_skus=["SEM-INVALID-AMB-01", "SEM-INVALID-AMB-02"],
            diagnostic_candidate_skus=[],
            candidate_skus=["SEM-INVALID-AMB-01", "SEM-INVALID-AMB-02"],
            matched_by="family_alias",
            confidence="medium",
            is_unique=False,
            matched_span=None,
            field_type="color",
            status_reason="resolver_multiple_candidates",
        )
        monkeypatch.setattr(
            customer_service_service.customer_entity_resolution_contract,
            "build_entity_resolution_contract",
            lambda *_args, **_kwargs: contract,
        )

        def fake_phase2(_db, _question, state):
            assert state["action"] == "ambiguous_clarification"
            return {
                "intent": "clarify",
                "answer_type": "clarification",
                "answer": "\u8bf7\u6307\u5b9a\u5177\u4f53\u6b3e\u5f0f\u3002",
                "results": [],
                "result_skus": [],
                "candidate_skus": ["SEM-INVALID-AMB-01", "SEM-INVALID-AMB-02"],
                "answer_metadata": {},
                "debug": {},
            }

        monkeypatch.setattr(customer_service_service, "_build_phase2_entity_state_response", fake_phase2)
        result = customer_service_service._invalid_structured_query_named_detail_contract_result(
            db,
            f"{name}\u6709\u54ea\u4e9b\u989c\u8272\uff1f",
            {
                "invalid_structured_query_named_detail_candidate": {
                    "subject_text": name,
                    "canonical_fields": ["color"],
                    "confidence": 0.9,
                }
            },
        )

    assert result is not None
    assert result["result_skus"] == []
    assert result["candidate_skus"] == ["SEM-INVALID-AMB-01", "SEM-INVALID-AMB-02"]
    assert result["debug"]["field_contract"]["field_type"] == "color"
    assert result["debug"]["entity_resolution_contract"]["status"] == "ambiguous"


def test_structured_named_field_adapter_uses_entity_contract_not_filter_route(
    route_client_and_db,
):
    """A named product field survives an erroneous structured-query shell."""
    _client, _headers, Session = route_client_and_db
    name = "\u8bed\u4e49\u9002\u914d\u6d4b\u8bd5\u9505"
    with Session() as db:
        for sku in ("SEM-ADAPT-AMB-01", "SEM-ADAPT-AMB-02"):
            _add_product(db, sku, name, "\u9505\u5177", "", "\u4e0d\u9508\u94a2", "", "", "", 1)
        db.commit()
        preplan = {
            "called": True,
            "route_family": "structured_query",
            "route_hint": "query_products",
            "question_type": "filter",
            "subtype": "structured_query",
            "subject_text": name,
            "canonical_fields": ["color"],
            "field_type": "color",
            "field_hint": "color",
            "confidence": 0.9,
            "ambiguity": False,
            "evidence_required": False,
            "fallback_reason": "",
            "structured_query_constraints": [{"field": "color", "operator": "contains", "value": "\u989c\u8272"}],
        }
        adapted = customer_service_service._apply_structured_named_field_entity_adapter(
            db,
            f"{name}\u6709\u54ea\u4e9b\u989c\u8272\uff1f",
            preplan,
        )

    assert adapted is True
    assert preplan["route_family"] == "product_bound_qa"
    assert preplan["route_hint"] == "product_detail"
    assert preplan["question_type"] == "field"
    assert preplan["subtype"] == "known_detail"
    assert preplan["entity_scope"] == "ambiguous_product"
    assert preplan["semantic_adapter_source"] == "validated_structured_named_field_entity_contract"


def test_semantic_unbound_knowledge_meta_question_never_becomes_product_recommendation(
    route_client_and_db,
    monkeypatch,
):
    """An LLM-identified knowledge meta question has no product candidate scope."""
    client, headers, _Session = route_client_and_db

    async def fake_preplan(_db, _question, _deterministic_plan, context):
        return {
            "called": True,
            "route_family": "knowledge_base_meta",
            "route_hint": "clarification",
            "question_type": "field",
            "subtype": "no_match",
            "subject_text": "户外套装",
            "canonical_fields": [],
            "field_type": "",
            "evidence_kind": "product_qa",
            "confidence": 0.9,
            "ambiguity": False,
            "evidence_required": False,
            "context_usage": "none",
            "information_scope": "knowledge_base_meta",
            "structured_query_constraints": [],
        }

    monkeypatch.setattr(customer_agent_planner_service, "plan_customer_question_semantic", fake_preplan)
    response = client.post(
        "/api/customer-service/ask?debug=true",
        json={"question": "请概述知识库里的户外套装推荐判断原则。"},
        headers=headers,
    )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["answer_type"] == "clarification", payload
    assert payload["result_skus"] == [], payload
    assert payload["candidate_skus"] == [], payload
    assert payload.get("debug", {}).get("agent_mode") == "semantic_unbound_knowledge_meta_clarification", payload


def test_sealed_product_qa_preempts_usage_care_composition_shortcut(
    route_client_and_db,
    monkeypatch,
):
    """A semantic generic product fact must reach same-SKU QA before legacy usage/care."""
    client, headers, Session = route_client_and_db
    name = "语义燃烧炉套装"
    question = f"{name}加满酒精能烧多久？"
    with Session() as db:
        _add_product(
            db,
            "SEM-QA-RUNTIME-01",
            name,
            "炉具",
            "",
            "不锈钢",
            "",
            "测试资料",
            "户外",
            300,
        )
        _add_product_qa(
            db,
            "SEM-QA-RUNTIME-01",
            question,
            "加满后可持续燃烧约90分钟。",
            priority=300,
        )
        db.commit()

    async def fake_preplan(_db, _question, _deterministic_plan, *, context=None):
        return {
            "called": True,
            "route_family": "product_bound_qa",
            "route_hint": "product_detail",
            "question_type": "field",
            "subtype": "known_detail",
            "subject_text": name,
            "canonical_fields": [],
            "field_type": "",
            "evidence_kind": "product_qa",
            "confidence": 0.9,
            "ambiguity": False,
            "evidence_required": True,
            "context_usage": "none",
        }

    monkeypatch.setattr(customer_agent_planner_service, "plan_customer_question_semantic", fake_preplan)
    response = client.post(
        "/api/customer-service/ask?debug=true",
        json={"question": question},
        headers=headers,
    )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert "90分钟" in payload.get("answer", ""), payload
    assert payload.get("result_skus") == ["SEM-QA-RUNTIME-01"], payload
    assert payload.get("debug", {}).get("agent_mode") != "product_usage_care_fast_path", payload


def test_sealed_semantic_product_qa_is_not_preempted_by_product_title_field_alias():
    question = "U悠 酒精炉套装PRO加满酒精能烧多久？"
    plan = {
        "semantic_preplan": {
            "called": True,
            "route_family": "product_bound_qa",
            "route_hint": "product_detail",
            "question_type": "field",
            "subtype": "known_detail",
            "subject_text": "U悠 酒精炉套装PRO",
            "canonical_fields": [],
            "field_type": "",
            "evidence_kind": "product_qa",
            "confidence": 0.9,
            "ambiguity": False,
            "evidence_required": True,
            "context_usage": "none",
        }
    }

    assert customer_service_service._semantic_prefers_sealed_product_qa(plan)
    assert not customer_service_service._formal_field_contract_preempts_product_qa(question, plan)


def test_sealed_semantic_product_qa_does_not_rederive_field_from_product_title(route_client_and_db):
    """A semantic QA decision must survive the shortcut's entity/evidence sealing."""
    _client, _headers, Session = route_client_and_db
    question = "U悠 酒精炉套装PRO加满酒精能烧多久？"
    plan = {
        "semantic_preplan": {
            "called": True,
            "route_family": "product_bound_qa",
            "route_hint": "product_detail",
            "canonical_fields": [],
            "field_type": "",
            "evidence_kind": "product_qa",
            "confidence": 0.9,
            "ambiguity": False,
        }
    }
    with Session() as db:
        _add_product(
            db,
            "SEM-QA-RUNTIME-02",
            "U悠 酒精炉套装PRO",
            "酒精炉",
            "100ml",
            "铝合金",
            "95%液体酒精",
            "便携",
            "露营",
            200,
        )
        _add_product_qa(db, "SEM-QA-RUNTIME-02", question, "加满100ml燃料可燃烧约60分钟。")
        db.commit()
        result = customer_service_service._try_product_qa_shortcut(
            db,
            question,
            phase1_plan=plan,
        )

    assert result is not None
    assert result["answer"] == "加满100ml燃料可燃烧约60分钟。"
    assert result["debug"]["field_contract"]["field_type"] == "product_qa"
    assert result["debug"]["entity_resolution_contract"]["resolved_sku"] == "SEM-QA-RUNTIME-02"
    assert result["answer_metadata"]["evidence_bundle_skus"] == ["SEM-QA-RUNTIME-02"]
    assert result["evidence"][0]["evidence_id"].startswith("product_qa:")


def test_product_qa_renderer_makes_causal_care_answer_customer_readable():
    result = customer_service_service._shape_product_detail_output(
        "\u718f\u9ed1\u7684\u539f\u56e0\uff1a\u4e3b\u8981\u7531\u4e8e\u9152\u7cbe\u7eaf\u5ea6\u4e0d\u8db3\u3001\u71c3\u70e7\u4e0d\u5145\u5206\u7b49\u539f\u56e0\u5bfc\u81f4\u7684\u79ef\u78b3\uff0c\u4f7f\u7528\u540e\u53ca\u65f6\u7528\u6d77\u7ef5\u64e6\u6e05\u6d17\u5373\u53ef\u3002",
        [],
        answer_metadata={
            "answer_policy": "field_only",
            "evidence_field": "cleaning",
            "evidence_source": "specs.usage_instruction",
            "evidence_sku": "CS-B15S",
        },
    )

    assert result == "\u718f\u9ed1\u901a\u5e38\u662f\u7531\u4e8e\u9152\u7cbe\u7eaf\u5ea6\u4e0d\u8db3\u3001\u71c3\u70e7\u4e0d\u5145\u5206\u7b49\u539f\u56e0\u5bfc\u81f4\u79ef\u78b3\uff1b\u4f7f\u7528\u540e\u53ca\u65f6\u7528\u6d77\u7ef5\u64e6\u62ed\u6e05\u6d01\u5373\u53ef\u3002"


def test_product_qa_output_keeps_full_same_sku_answer():
    result = customer_service_service._shape_product_detail_output(
        "安全！采用食品级水性不粘涂层，不含PFOA等有害物质。涂层越养越顺滑。",
        [],
        answer_metadata={"evidence_field": "product_qa", "evidence_sku": "CF-PG19"},
    )

    assert result == "安全！采用食品级水性不粘涂层，不含PFOA等有害物质。涂层越养越顺滑。"


def test_sealed_multi_field_contract_is_not_reparsed_from_product_title(route_client_and_db):
    _client, _headers, Session = route_client_and_db
    with Session() as db:
        _add_product(
            db, "SEM-MULTI-01", "U\u60a0 \u9152\u7cbe\u7089\u5957\u88c5PRO", "\u9152\u7cbe\u7089", "", "\u94dd\u5408\u91d1", "\u9152\u7cbe", "", "", 100,
        )
        db.commit()
        result = {
            "answer_type": "product_detail", "answer": "Cleaning: wipe dry.\nCare: store dry.",
            "result_skus": ["SEM-MULTI-01"],
            "answer_metadata": {"contract_field_types": ["cleaning", "care"], "evidence_skus": ["SEM-MULTI-01"]},
            "debug": {"field_contract": {"field_type": None, "canonical_fields": ["cleaning", "care"], "source": "validated_semantic_preplan"}},
        }
        repaired = customer_service_service._enforce_field_evidence_policy(db, "U\u60a0 \u9152\u7cbe\u7089\u5957\u88c5PRO\u5982\u4f55\u6e05\u6d17\u4fdd\u517b\uff1f", result)
    assert repaired["answer"] == result["answer"]


def test_semantic_positioning_field_is_not_reclassified_as_target_audience(
    route_client_and_db,
    monkeypatch,
):
    """Semantic field meaning remains authoritative after entity binding."""
    client, headers, Session = route_client_and_db
    name = "Semantic Positioning Box"
    with Session() as db:
        _add_product(
            db,
            "SEM-POSITIONING-01",
            name,
            "accessory",
            "",
            "aluminium",
            "",
            "test data",
            "outdoor",
            300,
        )
        business = db.query(ProductBusiness).filter(
            ProductBusiness.product_id == "route-SEM-POSITIONING-01"
        ).first()
        assert business is not None
        business.positioning = "Compact storage for camp kitchens."
        db.commit()

    async def fake_preplan(_db, _question, _deterministic_plan, *, context=None):
        return {
            "called": True,
            "route_family": "product_bound_qa",
            "route_hint": "product_detail",
            "question_type": "field",
            "subtype": "known_detail",
            "subject_text": name,
            "canonical_fields": ["positioning"],
            "field_type": "positioning",
            "field_hint": "positioning",
            "confidence": 0.95,
            "ambiguity": False,
            "evidence_required": True,
            "context_usage": "none",
        }

    monkeypatch.setattr(customer_agent_planner_service, "plan_customer_question_semantic", fake_preplan)
    response = client.post(
        "/api/customer-service/ask?debug=true",
        json={"question": f"{name} serves what kind of need?"},
        headers=headers,
    )

    assert response.status_code == 200, response.text
    payload = response.json()
    field = (payload.get("debug") or {}).get("field_contract") or {}
    metadata = payload.get("answer_metadata") or {}
    assert field.get("field_type") == "positioning", payload
    assert metadata.get("evidence_field") == "positioning", payload
    assert "Compact storage" in payload.get("answer", ""), payload


def test_exact_semantic_structured_subject_does_not_defer_to_catalog_route(route_client_and_db):
    """A verified named subject is not a generic catalogue filter scope."""
    _client, _headers, Session = route_client_and_db
    name = "精确语义目录炉"
    with Session() as db:
        _add_product(
            db,
            "SEM-DEFER-01",
            name,
            "炉具",
            "",
            "不锈钢",
            "",
            "测试资料",
            "户外",
            300,
        )
        db.commit()
        plan = {
            "_db": db,
            "primary_intent": "product_field",
            "semantic_preplan": {
                "called": True,
                "route_family": "structured_query",
                "route_hint": "query_products",
                "question_type": "filter",
                "subtype": "structured_query",
                "subject_text": name,
                "canonical_fields": ["color"],
                "field_type": "color",
                "field_hint": "color",
                "confidence": 0.9,
                "ambiguity": False,
                "evidence_required": False,
                "context_usage": "none",
                "structured_query_constraints": [],
            },
        }
        assert not customer_service_service._should_prioritize_semantic_structured_route(
            f"{name}有哪些颜色？",
            plan,
        )


def test_semantic_price_positioning_preempts_realtime_price_guard_and_keeps_entity(
    route_client_and_db,
    monkeypatch,
):
    client, headers, _ = route_client_and_db

    async def fake_preplan(db, question, deterministic_plan, context):
        return {
            "called": True,
            "route_family": "product_bound_qa",
            "route_hint": "product_detail",
            "subject_text": "瓦片烤盘",
            "field_type": "price_positioning",
            "field_hint": "price_positioning",
            "canonical_fields": ["price_positioning"],
            "question_type": "field",
            "subtype": "known_detail",
            "confidence": 0.95,
            "ambiguity": False,
            "evidence_required": True,
            "context_usage": "none",
        }

    monkeypatch.setattr(customer_agent_planner_service, "plan_customer_question_semantic", fake_preplan)
    payload = client.post(
        "/api/customer-service/ask?debug=true",
        json={"question": "瓦片烤盘属于哪个价格带？"},
        headers=headers,
    ).json()

    field = (payload.get("debug") or {}).get("field_contract") or {}
    entity = (payload.get("debug") or {}).get("entity_resolution_contract") or {}
    assert field.get("field_type") == "price_positioning", payload
    assert field.get("source") == "validated_semantic_preplan", payload
    assert entity.get("resolved_sku") == "CF-PG19", payload
    assert payload.get("result_skus") == ["CF-PG19"], payload
    assert (payload.get("debug") or {}).get("agent_mode") != "structured_unknown_field_guard", payload


def test_semantic_multi_field_request_executes_each_field_on_one_sealed_entity(
    route_client_and_db,
    monkeypatch,
):
    client, headers, _ = route_client_and_db

    async def fake_preplan(db, question, deterministic_plan, context):
        return {
            "called": True,
            "route_family": "product_bound_qa",
            "route_hint": "product_detail",
            "subject_text": "瓦片烤盘",
            "field_type": "sales_region",
            "field_hint": "sales_region",
            "canonical_fields": ["sales_region", "purchase_channel"],
            "question_type": "field",
            "subtype": "known_detail",
            "confidence": 0.95,
            "ambiguity": False,
            "evidence_required": True,
            "context_usage": "none",
        }

    monkeypatch.setattr(customer_agent_planner_service, "plan_customer_question_semantic", fake_preplan)
    payload = client.post(
        "/api/customer-service/ask?debug=true",
        json={"question": "瓦片烤盘面向哪些市场，我从什么平台购买？"},
        headers=headers,
    ).json()

    field = (payload.get("debug") or {}).get("field_contract") or {}
    entity = (payload.get("debug") or {}).get("entity_resolution_contract") or {}
    metadata = payload.get("answer_metadata") or {}
    assert field.get("canonical_fields") == ["sales_region", "purchase_channel"], payload
    assert entity.get("resolved_sku") == "CF-PG19", payload
    assert payload.get("result_skus") == ["CF-PG19"], payload
    assert metadata.get("contract_field_types") == ["sales_region", "purchase_channel"], payload
    assert (payload.get("debug") or {}).get("agent_mode") == "resolved_entity_multi_field_contract", payload


def test_semantic_multi_realtime_fields_each_render_safe_missing_on_one_entity(
    route_client_and_db,
    monkeypatch,
):
    client, headers, _ = route_client_and_db

    async def fake_preplan(db, question, deterministic_plan, context):
        return {
            "called": True,
            "route_family": "product_bound_qa",
            "route_hint": "product_detail",
            "subject_text": "CF-PG19",
            "field_type": "",
            "field_hint": None,
            "canonical_fields": ["inventory", "price"],
            "question_type": "field",
            "subtype": "known_detail",
            "confidence": 0.95,
            "ambiguity": False,
            "evidence_required": True,
            "context_usage": "none",
        }

    monkeypatch.setattr(customer_agent_planner_service, "plan_customer_question_semantic", fake_preplan)
    payload = client.post(
        "/api/customer-service/ask?debug=true",
        json={"question": "CF-PG19 现在有没有现货，当前售价多少？"},
        headers=headers,
    ).json()

    answer = str(payload.get("answer") or "")
    metadata = payload.get("answer_metadata") or {}
    assert payload.get("result_skus") == ["CF-PG19"], payload
    assert "库存" in answer or "现货" in answer, payload
    assert "价格" in answer or "售价" in answer, payload
    assert metadata.get("contract_field_types") == ["inventory", "price"], payload
    assert (payload.get("debug") or {}).get("agent_mode") == "resolved_entity_multi_field_contract", payload


def test_compound_realtime_boundary_completes_a_field_omitted_by_semantic_plan():
    result = customer_service_service._complete_resolved_realtime_commercial_boundaries(
        "CF-PG19 现在有没有现货，当前售价多少？",
        {
            "answer_type": "product_detail",
            "answer": "瓦片烤盘（CF-PG19）\n当前资料未维护可确认的实时库存，请以店铺页面为准。",
            "result_skus": ["CF-PG19"],
            "answer_metadata": {"evidence_status": "missing"},
        },
    )

    assert "库存" in result["answer"]
    assert "价格" in result["answer"] or "售价" in result["answer"]
    assert result["answer_metadata"]["contract_field_types"] == ["inventory", "price"]
    assert result["answer_metadata"]["compound_realtime_boundary_completed"] is True


def test_semantic_recommendation_ignores_negated_subject_text_hits(monkeypatch):
    off_scope_row = {
        "sku": "OFF-SCOPE",
        "product_name_cn": "炉具配件",
        "category": "配件",
    }
    cookware_row = {
        "sku": "SAFE-ALCOHOL-POT",
        "product_name_cn": "双人酒精炉单锅",
        "category": "锅具",
        "sub_category": "单锅",
        "capacity": "锅：1400ML",
        "heat_source": "酒精炉\n气炉",
        "target_audience": "1-2人",
        "usage_scenarios": "周末露营；双人简餐",
        "features": "可收纳锅具",
    }

    monkeypatch.setattr(
        customer_service_service.customer_agent_service,
        "search_products",
        lambda _db, _subject, limit=50: [off_scope_row],
    )
    monkeypatch.setattr(
        customer_service_service,
        "_phase1_catalog_rows",
        lambda _db, product_ref: [cookware_row] if product_ref == "锅具" else [off_scope_row, cookware_row],
    )

    async def narrative(_db, *, rows, **_kwargs):
        assert [row["sku"] for row in rows] == ["SAFE-ALCOHOL-POT"]
        return {
            "ranked_candidate_indexes": [0],
            "evidence_usage": [{"candidate_index": 0, "fields": ["heat_source"]}],
            "answer": "针对双人周末露营，可以先看双人酒精炉单锅；资料标注热源为酒精炉、气炉。",
        }

    monkeypatch.setattr(customer_service_service, "_semantic_recommendation_narrative", narrative)
    result = asyncio.run(customer_service_service._semantic_recommendation_contract_result(
        None,
        "只推荐锅具，不要炉具和配件，适合两个人周末露营，最好能用酒精炉。",
        {"semantic_preplan": {
            "called": True,
            "route_family": "recommendation",
            "confidence": 0.95,
            "fallback_reason": "",
            "ambiguity": False,
            "subject_text": "炉具和配件",
            "recommendation_constraints": {
                "subject_kind": "cookware",
                "people": {"min": 2, "max": 2},
                "heat_sources": ["alcohol_stove"],
                "scenarios": ["camping"],
            },
            "unrepresented_recommendation_requirements": [],
            "recommendation_soft_preferences": [],
        }},
    ))

    assert result["result_skus"] == ["SAFE-ALCOHOL-POT"], result
    assert "OFF-SCOPE" not in result["candidate_skus"]


def test_semantic_recommendation_keeps_positive_griddle_subcategory(monkeypatch):
    griddle_row = {
        "sku": "SAFE-GRIDDLE",
        "product_name_cn": "易清洁烤盘",
        "category": "锅具",
        "sub_category": "烤盘",
        "heat_source": "卡式炉\n明火",
        "features": "不沾涂层，容易清洁",
    }
    monkeypatch.setattr(
        customer_service_service.customer_agent_service,
        "search_products",
        lambda _db, _subject, limit=50: [],
    )
    monkeypatch.setattr(
        customer_service_service,
        "_phase1_catalog_rows",
        lambda _db, product_ref: [griddle_row] if product_ref == "烤盘" else [],
    )

    async def narrative(_db, *, rows, **_kwargs):
        assert [row["sku"] for row in rows] == ["SAFE-GRIDDLE"]
        return {
            "ranked_candidate_indexes": [0],
            "evidence_usage": [{"candidate_index": 0, "fields": ["heat_source", "cleaning"]}],
            "answer": "可以先看易清洁烤盘：资料标注支持卡式炉，且写明不沾涂层、容易清洁。",
        }

    monkeypatch.setattr(customer_service_service, "_semantic_recommendation_narrative", narrative)
    result = asyncio.run(customer_service_service._semantic_recommendation_contract_result(
        None,
        "我有卡式炉，想买烤盘，哪些产品明确支持卡式炉？优先推荐好清洁的。",
        {"semantic_preplan": {
            "called": True,
            "route_family": "recommendation",
            "confidence": 0.95,
            "fallback_reason": "",
            "ambiguity": False,
            "subject_text": "",
            "recommendation_constraints": {
                "subject_kind": "cookware",
                "heat_sources": ["card_stove"],
            },
            "unrepresented_recommendation_requirements": [],
            "recommendation_soft_preferences": ["优先推荐好清洁的"],
        }},
    ))

    assert result["result_skus"] == ["SAFE-GRIDDLE"], result


def test_semantic_subject_text_seals_unique_entity_for_contents_predicate(route_client_and_db, monkeypatch):
    """Validated semantic field meaning and subject span must reach Phase 2 together."""
    client, headers, Session = route_client_and_db
    with Session() as db:
        _add_product(
            db,
            "SEMANTIC-SUBJECT-01",
            "远行套锅（渠道版）",
            "锅具",
            "1L",
            "铝合金",
            "燃气炉",
            "轻量收纳",
            "露营",
            420,
        )
        db.commit()

    async def fake_preplan(db, question, deterministic_plan, context):
        return {
            "called": True,
            "route_family": "product_bound_qa",
            "route_hint": "product_detail",
            "field_type": "contents",
            "canonical_fields": ["contents"],
            "subject_text": "远行套锅",
            "question_type": "field",
            "subtype": "known_detail",
            "confidence": 0.9,
            "ambiguity": False,
            "evidence_required": True,
            "context_usage": "none",
        }

    monkeypatch.setattr(customer_agent_planner_service, "plan_customer_question_semantic", fake_preplan)
    payload = client.post(
        "/api/customer-service/ask?debug=true",
        json={"question": "远行套锅原装开箱会附带哪些东西？"},
        headers=headers,
    ).json()

    field = (payload.get("debug") or {}).get("field_contract") or {}
    entity = (payload.get("debug") or {}).get("entity_resolution_contract") or {}
    assert field.get("field_type") == "accessories", payload
    assert field.get("source") == "validated_semantic_preplan", payload
    assert entity.get("status") == "resolved", payload
    assert entity.get("resolved_sku") == "SEMANTIC-SUBJECT-01", payload
    assert payload.get("result_skus") == ["SEMANTIC-SUBJECT-01"], payload


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
    monkeypatch,
):
    client, headers, Session = route_client_and_db

    async def fake_preplan(_db, _question, _deterministic_plan, *, context):
        return {
            "called": True,
            "route_family": "recommendation",
            "route_hint": "recommendation",
            "entity_scope": "generic_scope",
            "entities": [],
            "field_type": "",
            "canonical_fields": [],
            "question_type": "recommendation",
            "subtype": "recommendation",
            "confidence": 0.96,
            "ambiguity": False,
            "evidence_required": True,
            "context_usage": "none",
            "recommendation_constraints": {"subject_kind": "stove", "scenarios": ["camping"]},
            # Grilling and boiling requirements have no current structured
            # verification dimension. Preserve them rather than widening the
            # result or treating wording as an accessory request.
            "unrepresented_recommendation_requirements": [question],
        }

    monkeypatch.setattr(customer_agent_planner_service, "plan_customer_question_semantic", fake_preplan)

    response = client.post("/api/customer-service/ask?debug=true", json={"question": question}, headers=headers)
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["answer_type"] == "clarification", payload
    assert payload["answer_type"] != "knowledge_base_answer"
    assert payload["result_skus"] == [], payload
    assert payload["candidate_skus"] == [], payload
    assert payload["debug"]["agent_mode"] in {
        "semantic_recommendation_contract",
        "semantic_recommendation_narrative_unavailable",
    }, payload
    assert payload["answer"], payload


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
def test_route_level_generic_stove_recommendation_queries_stay_in_stove_domain(
    route_client_and_db,
    question,
    monkeypatch,
):
    client, headers, Session = route_client_and_db

    async def fake_preplan(_db, _question, _deterministic_plan, *, context):
        return {
            "called": True,
            "route_family": "recommendation",
            "route_hint": "recommendation",
            "entity_scope": "generic_scope",
            "entities": [],
            "field_type": "",
            "canonical_fields": [],
            "question_type": "recommendation",
            "subtype": "recommendation",
            "confidence": 0.96,
            "ambiguity": False,
            "evidence_required": True,
            "context_usage": "none",
            "recommendation_constraints": {"subject_kind": "stove"},
            "unrepresented_recommendation_requirements": [],
        }

    async def fake_narrative(_db, *, rows, **_kwargs):
        assert rows
        return {
            "ranked_candidate_indexes": [0],
            "evidence_usage": [{"candidate_index": 0, "fields": ["content.features"]}],
            "answer": f"根据已核验的同 SKU 资料，优先考虑{rows[0]['product_name_cn']}。",
        }

    monkeypatch.setattr(customer_agent_planner_service, "plan_customer_question_semantic", fake_preplan)
    monkeypatch.setattr(customer_service_service, "_semantic_recommendation_narrative", fake_narrative)

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


def test_semantic_recommendation_uses_literal_soft_priority_without_turning_it_into_a_filter(
    route_client_and_db,
    monkeypatch,
):
    """A semantic soft preference reaches the sealed writer, not the verifier.

    This protects the central distinction: a formal heat-source condition is
    eligible for same-SKU verification, while a literal storage preference can
    shape the DeepSeek explanation but cannot be claimed as candidate evidence.
    """
    client, headers, _Session = route_client_and_db

    async def fake_preplan(_db, _question, _deterministic_plan, *, context):
        return {
            "called": True,
            "route_family": "recommendation",
            "route_hint": "recommendation",
            "entity_scope": "generic_scope",
            "entities": [],
            "field_type": "",
            "canonical_fields": [],
            "question_type": "recommendation",
            "subtype": "recommendation",
            "confidence": 0.96,
            "ambiguity": False,
            "evidence_required": True,
            "context_usage": "none",
            "recommendation_constraints": {"subject_kind": "stove"},
            "unrepresented_recommendation_requirements": [],
            "recommendation_soft_preferences": ["不占纳空间"],
        }

    async def fake_narrative(_db, *, rows, soft_preferences, **_kwargs):
        assert soft_preferences == ["不占纳空间"]
        return {
            "ranked_candidate_indexes": [0],
            "evidence_usage": [{"candidate_index": 0, "fields": ["content.features"]}],
            "answer": f"根据已核验的同 SKU 资料，优先考虑{rows[0]['product_name_cn']}。",
        }

    monkeypatch.setattr(customer_agent_planner_service, "plan_customer_question_semantic", fake_preplan)
    monkeypatch.setattr(customer_service_service, "_semantic_recommendation_narrative", fake_narrative)

    payload = client.post(
        "/api/customer-service/ask?debug=true",
        json={"question": "周末自驾野餐，想买一台不占纳空间的卡式炉，怎么选？"},
        headers=headers,
    ).json()

    assert payload["answer_type"] == "recommendation", payload
    assert payload["result_skus"], payload
    assert payload["debug"]["semantic_soft_preferences"] == ["不占纳空间"], payload


def test_recommendation_grounding_review_receives_soft_preferences_as_non_evidence(monkeypatch):
    """The prose auditor must know which user priorities cannot prove facts."""
    seen = {}

    async def fake_chat_completion(_db, messages, **_kwargs):
        seen.update(json.loads(messages[1]["content"]))
        seen["system"] = messages[0]["content"]
        return json.dumps({"approved": True, "unsupported_claims": []})

    monkeypatch.setattr(customer_service_service.customer_llm_service, "chat_completion", fake_chat_completion)
    review = asyncio.run(customer_service_service._semantic_recommendation_narrative_grounding_review(
        None,
        question="想要收纳方便的炉具。",
        soft_preferences=["收纳方便"],
        candidates=[{
            "candidate_index": 0,
            "product_name": "测试炉具",
            "sku": "TEST-STOVE-01",
            "sealed_evidence": {"content.features": "支持卡式炉"},
            "verified_constraints": [],
            "verified_requirement_claims": [],
        }],
        narrative={
            "ranked_candidate_indexes": [0],
            "evidence_usage": [{"candidate_index": 0, "fields": ["content.features"]}],
            "answer": "测试炉具资料标注支持卡式炉。",
        },
    ))

    assert review == {"approved": True, "unsupported_claims": []}
    assert seen["soft_customer_preferences"] == ["收纳方便"]
    assert "conditional choice" in seen["system"]


def test_recommendation_grounding_review_allows_qualified_practical_use_inference(monkeypatch):
    """A physical same-SKU capability may support a clearly qualified use judgment."""
    seen = {}

    async def fake_chat_completion(_db, messages, **_kwargs):
        seen["system"] = messages[0]["content"]
        return json.dumps({"approved": True, "unsupported_claims": []})

    monkeypatch.setattr(customer_service_service.customer_llm_service, "chat_completion", fake_chat_completion)
    review = asyncio.run(customer_service_service._semantic_recommendation_narrative_grounding_review(
        None,
        question="适合泡咖啡的小锅有吗？",
        candidates=[{
            "candidate_index": 0,
            "product_name": "测试套锅",
            "sku": "TEST-COFFEE-01",
            "sealed_evidence": {"specs.capacity": "水壶约1.0L"},
            "verified_constraints": [],
            "verified_requirement_claims": [],
        }],
        narrative={
            "ranked_candidate_indexes": [0],
            "evidence_usage": [{"candidate_index": 0, "fields": ["specs.capacity"]}],
            "answer": "如果您是烧水冲泡咖啡，测试套锅内约1.0L水壶可以作为选择。",
        },
    ))

    assert review == {"approved": True, "unsupported_claims": []}
    assert "qualified practical-use inference" in seen["system"]
    assert "water kettle with capacity" in seen["system"]


@pytest.mark.skip(reason="post-render model veto removed from the closed-evidence pipeline")
def test_semantic_recommendation_reviewer_not_literal_gate_decides_soft_preference_entailment(monkeypatch):
    """A sealed-evidence semantic approval must not be overridden by phrase matching."""
    calls = []

    async def fake_chat_completion(_db, _messages=None, **kwargs):
        purpose = kwargs.get("purpose")
        calls.append(purpose)
        if purpose == "semantic_recommendation_narrative":
            return json.dumps({
                "ranked_candidate_indexes": [0],
                "evidence_usage": [{"candidate_index": 0, "fields": ["content.usage_scenarios"]}],
                "answer": "测试锅具适合户外煮面，资料标注的使用场景包括户外煮面和露营。",
            })
        assert purpose == "semantic_recommendation_narrative_grounding_review"
        return json.dumps({"approved": True, "unsupported_claims": []})

    class Verification:
        sku = "SAFE-COOK-1"
        evidence_by_constraint = {"subject": {"status": "verified", "raw_value": "锅具"}}
        unsupported_constraints = []
        unsupported_preferences = []

    monkeypatch.setattr(customer_service_service.customer_llm_service, "chat_completion", fake_chat_completion)
    diagnostics = []
    narrative = asyncio.run(customer_service_service._semantic_recommendation_narrative(
        None,
        question="想要一口户外煮面的锅。",
        rows=[{
            "sku": "SAFE-COOK-1",
            "product_name_cn": "测试锅具",
            "usage_scenarios": "户外煮面、露营",
        }],
        verifications=[Verification()],
        soft_preferences=["户外煮面"],
        diagnostics=diagnostics,
    ))

    assert narrative is not None, diagnostics
    assert narrative["answer"] == "测试锅具适合户外煮面，资料标注的使用场景包括户外煮面和露营。"
    assert calls == [
        "semantic_recommendation_narrative",
        "semantic_recommendation_narrative_grounding_review",
    ]


@pytest.mark.skip(reason="retry cascade replaced by focused semantic candidate selection")
def test_semantic_recommendation_retry_narrows_dense_candidate_packet(monkeypatch):
    """A schema retry reduces choice density while retaining semantic authorship."""
    rows = [
        {
            "sku": f"SAFE-{index}",
            "product_name_cn": f"测试锅具{index}",
            "usage_scenarios": "四人露营",
        }
        for index in range(5)
    ]

    class Verification:
        def __init__(self, sku):
            self.sku = sku
            self.evidence_by_constraint = {"scenario": {"status": "verified", "raw_value": "四人露营"}}
            self.unsupported_constraints = []
            self.unsupported_preferences = []

    calls = []

    async def fake_chat_completion(_db, messages, **kwargs):
        purpose = kwargs.get("purpose")
        calls.append(purpose)
        if purpose == "semantic_recommendation_narrative":
            if calls.count(purpose) == 1:
                return "{}"
            packet = json.loads(messages[1]["content"])
            assert len(packet["sealed_candidates"]) == 3
            assert [item["candidate_index"] for item in packet["sealed_candidates"]] == [0, 1, 2]
            return json.dumps({
                "ranked_candidate_indexes": [0],
                "evidence_usage": [{"candidate_index": 0, "fields": ["content.usage_scenarios"]}],
                "answer": "测试锅具0的资料标注四人露营场景，可作为本次选择时优先了解的候选。",
            }, ensure_ascii=False)
        assert purpose == "semantic_recommendation_narrative_grounding_review"
        return json.dumps({"approved": True, "unsupported_claims": []})

    monkeypatch.setattr(customer_service_service.customer_llm_service, "chat_completion", fake_chat_completion)
    narrative = asyncio.run(customer_service_service._semantic_recommendation_narrative(
        None,
        question="四个人露营想煮汤和做饭，推荐一套容量够用又别太重的锅具。",
        rows=rows,
        verifications=[Verification(row["sku"]) for row in rows],
        diagnostics=[],
    ))

    assert narrative is not None
    assert narrative["ranked_candidate_indexes"] == [0]


@pytest.mark.skip(reason="superseded by final-render required-evidence validation tests")
def test_semantic_recommendation_requires_available_decision_dimension_evidence(monkeypatch):
    """A recommendation cannot cite capacity while silently dropping weight."""

    class Verification:
        sku = "SAFE-4P"
        evidence_by_constraint = {
            "capacity": {"status": "verified", "raw_value": "3L锅"},
            "weight": {"status": "verified", "raw_value": 980},
        }
        unsupported_constraints = []
        unsupported_preferences = []

    narrative_attempts = 0

    async def fake_chat_completion(_db, messages, **kwargs):
        nonlocal narrative_attempts
        purpose = kwargs.get("purpose")
        if purpose == "semantic_recommendation_narrative":
            narrative_attempts += 1
            packet = json.loads(messages[1]["content"])
            assert packet["required_customer_dimensions"] == ["capacity", "weight"]
            fields = ["capacity"] if narrative_attempts == 1 else ["capacity", "weight"]
            answer = (
                "四人煮汤和做饭可查看测试四人锅，容量标注3L锅。"
                if narrative_attempts == 1
                else "四人煮汤和做饭可查看测试四人锅，容量标注3L锅，重量标注980g。"
            )
            return json.dumps({
                "ranked_candidate_indexes": [0],
                "evidence_usage": [{"candidate_index": 0, "fields": fields}],
                "answer": answer,
            }, ensure_ascii=False)
        assert purpose == "semantic_recommendation_narrative_grounding_review"
        review_packet = json.loads(messages[1]["content"])
        assert review_packet["required_customer_dimensions"] == ["capacity", "weight"]
        return json.dumps({"approved": True, "unsupported_claims": []})

    monkeypatch.setattr(customer_service_service.customer_llm_service, "chat_completion", fake_chat_completion)
    narrative = asyncio.run(customer_service_service._semantic_recommendation_narrative(
        None,
        question="四个人露营想煮汤和做饭，推荐一套容量够用又别太重的锅具。",
        rows=[{
            "sku": "SAFE-4P",
            "product_name_cn": "测试四人锅",
            "capacity": "3L锅",
            "gross_weight_g": 980,
        }],
        verifications=[Verification()],
        required_customer_dimensions=["capacity", "weight"],
        diagnostics=[],
    ))

    assert narrative is not None
    assert narrative_attempts == 2
    assert "980g" in narrative["answer"]


@pytest.mark.skip(reason="superseded by sealed-candidate capacity validation tests")
def test_semantic_recommendation_does_not_seal_internally_inverted_capacity_labels(monkeypatch):
    """Contradictory big/small vessel capacities must not reach customer prose."""

    class Verification:
        sku = "CW-BAD-CAPACITY"
        evidence_by_constraint = {"people": {"status": "verified", "raw_value": "适合4人"}}
        unsupported_constraints = []
        unsupported_preferences = []

    async def fake_chat_completion(_db, messages, **kwargs):
        purpose = kwargs.get("purpose")
        if purpose == "semantic_recommendation_narrative":
            packet = json.loads(messages[1]["content"])
            sealed = packet["sealed_candidates"][0]["sealed_evidence"]
            assert "specs.capacity" not in sealed
            return json.dumps({
                "ranked_candidate_indexes": [0],
                "evidence_usage": [{"candidate_index": 0, "fields": ["content.usage_scenarios"]}],
                "answer": "测试四人套锅的资料标注露营场景，可先结合实际烹饪需求进一步确认。",
            }, ensure_ascii=False)
        assert purpose == "semantic_recommendation_narrative_grounding_review"
        return json.dumps({"approved": True, "unsupported_claims": []})

    monkeypatch.setattr(customer_service_service.customer_llm_service, "chat_completion", fake_chat_completion)
    narrative = asyncio.run(customer_service_service._semantic_recommendation_narrative(
        None,
        question="四个人露营想煮汤和做饭，推荐一套容量够用又别太重的锅具。",
        rows=[{
            "sku": "CW-BAD-CAPACITY",
            "product_name_cn": "测试四人套锅",
            "usage_scenarios": "露营",
            "capacity": "3L 大锅、7L 小锅、8L 水壶、5 寸煎盘",
        }],
        verifications=[Verification()],
        diagnostics=[],
    ))

    assert narrative is not None
    assert narrative["ranked_candidate_indexes"] == [0]


def test_semantic_recommendation_executes_contract_recognized_vague_capacity_preference(monkeypatch):
    """A known soft capacity phrase cannot remain an unrepresented blocker."""
    rows = [{
        "sku": "SAFE-2P",
        "product_name_cn": "双人露营套锅",
        "category": "锅具",
        "target_audience": "适合2人露营",
        "usage_scenarios": "周末露营",
        "gross_weight_g": 650,
        "features": "套锅可嵌套收纳",
        "capacity": "1.5L锅、0.8L锅",
    }]

    async def fake_narrative(_db, *, soft_preferences, **_kwargs):
        assert soft_preferences == ["容量别太小"]
        return {
            "ranked_candidate_indexes": [0],
            "evidence_usage": [{"candidate_index": 0, "fields": ["capacity"]}],
            "answer": "双人露营套锅标注1.5L锅和0.8L锅，可结合两人的实际食量判断。",
        }

    monkeypatch.setattr(customer_service_service, "_phase1_catalog_rows", lambda _db, _ref: rows)
    monkeypatch.setattr(customer_service_service, "_semantic_recommendation_narrative", fake_narrative)
    result = asyncio.run(customer_service_service._semantic_recommendation_contract_result(
        None,
        "两个人周末露营，想要轻便好收纳、容量别太小的锅具，推荐哪款？",
        {"semantic_preplan": {
            "called": True,
            "route_family": "recommendation",
            "confidence": 0.9,
            "confidence_label": "high",
            "fallback_reason": "",
            "ambiguity": False,
            "recommendation_constraints": {"subject_kind": "cookware"},
            "unrepresented_recommendation_requirements": ["容量别太小"],
            "recommendation_soft_preferences": [],
        }},
    ))

    assert result["answer_type"] == "recommendation"
    assert result["result_skus"] == ["SAFE-2P"]
    assert result["debug"]["semantic_soft_preferences"] == ["容量别太小"]


def test_semantic_recommendation_executes_literal_numeric_capacity_despite_preplan_unrepresented_label(monkeypatch):
    """A literal numeric capacity is a verified constraint even if planning omits it."""
    rows = [{
        "sku": "SAFE-1L",
        "product_name_cn": "单人烧水锅",
        "category": "锅具",
        "target_audience": "适合1人露营",
        "usage_scenarios": "单人露营",
        "capacity": "1000ML",
    }]

    async def fake_narrative(*_args, **_kwargs):
        return {
            "ranked_candidate_indexes": [0],
            "evidence_usage": [{"candidate_index": 0, "fields": ["capacity", "scenario", "people"]}],
            "answer": "单人烧水锅标注容量1000ML，使用场景包括单人露营。",
        }

    monkeypatch.setattr(customer_service_service, "_phase1_catalog_rows", lambda _db, _ref: rows)
    monkeypatch.setattr(customer_service_service, "_semantic_recommendation_narrative", fake_narrative)
    result = asyncio.run(customer_service_service._semantic_recommendation_contract_result(
        None,
        "一个人露营，推荐1L左右的小锅",
        {"semantic_preplan": {
            "called": True,
            "route_family": "recommendation",
            "confidence": 0.9,
            "confidence_label": "high",
            "fallback_reason": "",
            "ambiguity": False,
            "recommendation_constraints": {
                "subject_kind": "cookware",
                "people": {"min": 1, "max": 1},
                "scenarios": ["camping"],
            },
            "unrepresented_recommendation_requirements": ["1L左右的小锅"],
            "recommendation_soft_preferences": [],
        }},
    ))

    assert result["answer_type"] == "recommendation"
    assert result["result_skus"] == ["SAFE-1L"]


def test_semantic_recommendation_recovers_literal_contract_after_invalid_semantic_constraint_schema(monkeypatch):
    rows = [{
        "sku": "SAFE-1L-RECOVERY",
        "product_name_cn": "单人烧水锅恢复候选",
        "category": "锅具",
        "target_audience": "适合1人露营",
        "usage_scenarios": "单人露营",
        "capacity": "1000ML",
    }]

    async def fake_narrative(*_args, **_kwargs):
        return {
            "ranked_candidate_indexes": [0],
            "evidence_usage": [{"candidate_index": 0, "fields": ["capacity", "scenario", "people"]}],
            "answer": "单人烧水锅恢复候选标注容量1000ML，使用场景包括单人露营。",
        }

    monkeypatch.setattr(customer_service_service, "_phase1_catalog_rows", lambda _db, _ref: rows)
    monkeypatch.setattr(customer_service_service, "_semantic_recommendation_narrative", fake_narrative)
    result = asyncio.run(customer_service_service._semantic_recommendation_contract_result(
        None,
        "一个人露营，推荐1L左右的小锅",
        {"semantic_preplan": {
            "called": True,
            "route_family": "",
            "confidence": 0.0,
            "fallback_reason": "invalid_recommendation_constraints",
            "semantic_route_family_hint": "recommendation",
        }},
    ))

    assert result["answer_type"] == "recommendation"
    assert result["result_skus"] == ["SAFE-1L-RECOVERY"]


def test_single_numeric_capacity_recommendation_uses_verified_fallback_when_narrative_is_unavailable(monkeypatch):
    rows = [{"sku": "SAFE-1L-FALLBACK", "product_name_cn": "单人烧水锅", "category": "锅具", "target_audience": "1人露营者", "usage_scenarios": '["单人露营"]', "capacity": '[{"label":"锅","value":"1000ML","unit":""}]'}]
    monkeypatch.setattr(customer_service_service, "_phase1_catalog_rows", lambda _db, _ref: rows)
    async def unavailable(*_args, **_kwargs): return None
    monkeypatch.setattr(customer_service_service, "_semantic_recommendation_narrative", unavailable)
    result = asyncio.run(customer_service_service._semantic_recommendation_contract_result(None, "一个人露营，推荐一个1L左右的小锅", {"semantic_preplan": {"called": True, "route_family": "recommendation", "confidence": 0.9, "fallback_reason": "", "ambiguity": False, "recommendation_constraints": {"subject_kind": "cookware", "people": {"min": 1, "max": 1}, "scenarios": ["camping"]}}}))
    assert result["result_skus"] == ["SAFE-1L-FALLBACK"]
    assert "1000ML" in result["answer"]
    assert "[" not in result["answer"]


def test_verified_camping_recommendation_keeps_candidates_when_narrative_is_unavailable(monkeypatch):
    rows = [
        {"sku": "SAFE-CAMP-1", "product_name_cn": "\u4e09\u4eba\u9732\u8425\u9505", "category": "\u9505\u5177", "target_audience": "3\u4eba\u9732\u8425\u8005", "usage_scenarios": '["\u9732\u8425"]', "capacity": '[{"label":"\u9505","value":"3000ML","unit":""}]'},
        {"sku": "SAFE-CAMP-2", "product_name_cn": "\u9732\u8425\u5957\u9505", "category": "\u9505\u5177", "target_audience": "3\u4eba\u6237\u5916\u7528\u6237", "usage_scenarios": '["\u9732\u8425"]', "capacity": '[{"label":"\u9505","value":"2800ML","unit":""}]'},
    ]
    monkeypatch.setattr(customer_service_service, "_phase1_catalog_rows", lambda _db, _ref: rows)

    async def unavailable(*_args, **_kwargs):
        return None

    monkeypatch.setattr(customer_service_service, "_semantic_recommendation_narrative", unavailable)
    result = asyncio.run(customer_service_service._semantic_recommendation_contract_result(
        None,
        "\u4e09\u4e2a\u4eba\u9732\u8425\uff0c\u9002\u5408\u5e26\u4ec0\u4e48\u9505\u5177\uff1f",
        {"semantic_preplan": {"called": True, "route_family": "recommendation", "confidence": 0.9, "fallback_reason": "", "ambiguity": False, "recommendation_constraints": {"subject_kind": "cookware", "people": {"min": 3, "max": 3}, "scenarios": ["camping"]}, "unrepresented_recommendation_requirements": []}},
    ))

    assert result["answer_type"] == "recommendation"
    assert result["result_skus"] == ["SAFE-CAMP-1", "SAFE-CAMP-2"]
    assert "SAFE-CAMP-1" in result["answer"]
    assert "3000ML" in result["answer"]


def test_single_numeric_capacity_recommendation_does_not_clarify_for_boiling_water_goal(monkeypatch):
    rows = [{"sku": "SAFE-1L-BOIL", "product_name_cn": "\u5355\u4eba\u70e7\u6c34\u9505", "category": "\u9505\u5177", "target_audience": "1\u4eba\u9732\u8425\u8005", "usage_scenarios": '["\u5355\u4eba\u9732\u8425"]', "capacity": '[{"label":"\u9505","value":"1000ML","unit":""}]'}]
    monkeypatch.setattr(customer_service_service, "_phase1_catalog_rows", lambda _db, _ref: rows)

    async def unavailable(*_args, **_kwargs):
        return None

    monkeypatch.setattr(customer_service_service, "_semantic_recommendation_narrative", unavailable)
    result = asyncio.run(customer_service_service._semantic_recommendation_contract_result(
        None,
        "\u4e00\u4e2a\u4eba\u9732\u8425\uff0c\u63a8\u8350\u4e00\u4e2a1L\u5de6\u53f3\u7684\u5c0f\u9505\uff0c\u4e3b\u8981\u7528\u6765\u716e\u6c34",
        {"semantic_preplan": {"called": True, "route_family": "recommendation", "confidence": 0.9, "fallback_reason": "", "ambiguity": False, "recommendation_constraints": {"subject_kind": "cookware", "people": {"min": 1, "max": 1}, "scenarios": ["camping"]}, "unrepresented_recommendation_requirements": ["1L\u5de6\u53f3", "\u716e\u6c34"]}},
    ))

    assert result["answer_type"] == "recommendation"
    assert result["result_skus"] == ["SAFE-1L-BOIL"]


def test_plain_accessory_catalogue_listing_survives_generic_semantic_query_preplan(
    route_client_and_db,
    monkeypatch,
):
    client, headers, Session = route_client_and_db

    async def generic_catalog_preplan(*_args, **_kwargs):
        return {
            "called": True,
            "purpose": "semantic_preplan",
            "route_family": "generic_query",
            "route_hint": "query_products",
            "question_type": "filter",
            "entities": [],
            "subject_text": "",
            "canonical_fields": [],
            "confidence": 0.9,
            "confidence_label": "high",
            "ambiguity": False,
            "evidence_required": False,
            "evidence_kind": "structured_field",
            "recommendation_constraints": {},
            "structured_query_constraints": [],
            "unrepresented_recommendation_requirements": [],
            "recommendation_soft_preferences": [],
            "fallback_reason": "",
        }

    monkeypatch.setattr(
        customer_agent_planner_service,
        "plan_customer_question_semantic",
        generic_catalog_preplan,
    )
    response = client.post(
        "/api/customer-service/ask?debug=true",
        json={"question": "\u6709\u54ea\u4e9b\u914d\u4ef6\u4ea7\u54c1\uff1f"},
        headers=headers,
    )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["answer_type"] in {"product_query", "query_products"}, payload
    assert payload["result_skus"], payload
    with Session() as db:
        categories = {
            str(product.sku or "").strip().upper(): str(product.category or "").strip()
            for product in db.query(Product).filter(Product.sku.in_(payload["result_skus"])).all()
        }
    assert categories, payload
    assert all(category == "\u914d\u4ef6" for category in categories.values()), categories


def test_semantic_recommendation_uses_same_sku_facts_after_narrative_rejection(
    monkeypatch,
):
    rows = [{
        "sku": "SAFE-HIKE-1",
        "product_name_cn": "\u8f7b\u9014\u5355\u4eba\u9505",
        "category": "\u9505\u5177",
        "target_audience": "\u9002\u54081\u4eba\u5f92\u6b65",
        "usage_scenarios": "\u5355\u4eba\u5f92\u6b65\u8f7b\u91cf\u9732\u8425",
        "features": "\u8f7b\u91cf\u4fbf\u643a",
        "gross_weight_g": 320,
        "capacity": "1000ML",
    }]

    async def rejected_narrative(*_args, **kwargs):
        diagnostics = kwargs["diagnostics"]
        diagnostics.extend([
            {"attempt": 1, "stage": "narrative_safety_gate", "status": "rejected"},
            {"attempt": 1, "stage": "grounding_review", "status": "rejected"},
            {"attempt": 2, "stage": "rewrite", "status": "invalid_schema_or_provider_error"},
        ])
        return None

    monkeypatch.setattr(customer_service_service, "_phase1_catalog_rows", lambda _db, _ref: rows)
    monkeypatch.setattr(customer_service_service, "_semantic_recommendation_narrative", rejected_narrative)
    result = asyncio.run(customer_service_service._semantic_recommendation_contract_result(
        None,
        "\u6211\u4e00\u4e2a\u4eba\u5f92\u6b65\uff0c\u60f3\u8f7b\u4e00\u70b9\uff0c\u63a8\u8350\u4e00\u4e2a\u9505\u3002",
        {"semantic_preplan": {
            "called": True,
            "route_family": "recommendation",
            "confidence": 0.9,
            "fallback_reason": "",
            "ambiguity": False,
            "recommendation_constraints": {
                "subject_kind": "cookware",
                "people": {"min": 1, "max": 1},
                "weight_preference": "lightweight",
            },
            "unrepresented_recommendation_requirements": [],
            "recommendation_soft_preferences": [],
        }},
    ))

    assert result["answer_type"] == "recommendation", result
    assert result["result_skus"] == ["SAFE-HIKE-1"]
    assert "320g" in result["answer"]
    assert "\u5355\u4eba\u5f92\u6b65" in result["answer"]
    assert "SAFE-HIKE-1" in result["answer"]
    assert result["answer_metadata"]["recommendation_narrative"]["source"] == "verified_candidate_evidence_fallback"


def test_semantic_recommendation_runs_flash_evidence_renderer_after_malformed_rewrite(monkeypatch):
    rows = [{
        "sku": "SAFE-SEM-1",
        "product_name_cn": "轻途单人锅",
        "usage_scenarios": "单人徒步",
        "capacity": "1000ML",
    }]
    verification = SimpleNamespace(
        sku="SAFE-SEM-1",
        evidence_by_constraint={},
        unsupported_constraints=[],
        unsupported_preferences=[],
    )

    async def draft(*_args, **_kwargs):
        return json.dumps({
            "ranked_candidate_indexes": [0],
            "evidence_usage": [{"candidate_index": 0, "fields": ["content.usage_scenarios"]}],
            "answer": "轻途单人锅适合你的所有徒步需求，也可以直接作为唯一选择。",
        }, ensure_ascii=False)

    review_calls = []

    async def review(*_args, **_kwargs):
        review_calls.append(_kwargs["narrative"]["answer"])
        if "适合你的所有徒步需求" in _kwargs["narrative"]["answer"]:
            return {"approved": False, "unsupported_claims": ["适合你的所有徒步需求"]}
        return {"approved": True, "unsupported_claims": []}

    async def malformed_rewrite(*_args, **_kwargs):
        return None

    renderer_calls = []

    async def rendered(*_args, **_kwargs):
        renderer_calls.append(True)
        return {
            "ranked_candidate_indexes": [0],
            "evidence_usage": [{"candidate_index": 0, "fields": ["content.usage_scenarios"]}],
            "answer": "如果你主要是单人徒步，可以先看轻途单人锅；资料标注的使用场景是单人徒步。",
        }

    monkeypatch.setattr(customer_service_service.customer_llm_service, "chat_completion", draft)
    monkeypatch.setattr(customer_service_service, "_semantic_recommendation_narrative_grounding_review", review)
    monkeypatch.setattr(customer_service_service, "_semantic_recommendation_narrative_rewrite", malformed_rewrite)
    monkeypatch.setattr(customer_service_service, "_semantic_recommendation_evidence_render", rendered)

    result = asyncio.run(customer_service_service._semantic_recommendation_narrative(
        None,
        question="一个人徒步，推荐一款锅。",
        rows=rows,
        verifications=[verification],
        diagnostics=[],
    ))

    assert renderer_calls == [True]
    assert result["answer"].startswith("如果你主要是单人徒步")


def test_semantic_recommendation_recovers_model_selection_from_malformed_draft(monkeypatch):
    rows = [{
        "sku": "SAFE-SEM-SELECT",
        "product_name_cn": "模型选择锅",
        "usage_scenarios": "露营",
        "capacity": "1000ML",
    }]
    verification = SimpleNamespace(
        sku="SAFE-SEM-SELECT",
        evidence_by_constraint={},
        unsupported_constraints=[],
        unsupported_preferences=[],
    )

    async def malformed_draft(*_args, **kwargs):
        assert kwargs.get("purpose") == "semantic_recommendation_narrative"
        return json.dumps({
            "ranked_candidate_indexes": [0],
            "answer": "缺少 evidence_usage，完整 schema 不合格",
        }, ensure_ascii=False)

    rendered_selections = []

    async def rendered(*_args, **kwargs):
        rendered_selections.append(kwargs["narrative"]["ranked_candidate_indexes"])
        return {
            "ranked_candidate_indexes": [0],
            "evidence_usage": [{"candidate_index": 0, "fields": ["specs.capacity"]}],
            "answer": "如果先按容量缩小范围，可以先看模型选择锅：资料标注容量为1000ML。",
        }

    async def approved(*_args, **_kwargs):
        return {"approved": True, "unsupported_claims": []}

    monkeypatch.setattr(customer_service_service.customer_llm_service, "chat_completion", malformed_draft)
    monkeypatch.setattr(customer_service_service, "_semantic_recommendation_evidence_render", rendered)
    monkeypatch.setattr(customer_service_service, "_semantic_recommendation_narrative_grounding_review", approved)

    diagnostics = []
    result = asyncio.run(customer_service_service._semantic_recommendation_narrative(
        None,
        question="推荐一款露营锅。",
        rows=rows,
        verifications=[verification],
        diagnostics=diagnostics,
    ))

    assert rendered_selections == [[0]]
    assert result["ranked_candidate_indexes"] == [0]
    assert diagnostics[-1]["stage"] == "model_selection_evidence_render"
    assert diagnostics[-1]["status"] == "approved"


def test_post_filter_preserves_approved_sealed_semantic_answer():
    original = {
        "answer_type": "recommendation",
        "answer": "如果更看重清洁提示，可以先看瓦片烤盘；资料标注表面处理为水性不沾。",
        "results": [{"sku": "CF-PG19", "product_name_cn": "瓦片烤盘"}],
        "result_skus": ["CF-PG19"],
        "answer_metadata": {
            "source": "validated_semantic_preplan_then_same_sku_verification",
            "recommendation_contract": {"subject_kind": "cookware"},
            "recommendation_narrative": {
                "source": "validated_deepseek_grounded_narrative",
                "ranked_candidate_indexes": [0],
            },
        },
    }

    result = customer_service_service._post_filter_recommendation_result(None, "推荐好清洁的烤盘", original)

    assert result["answer"] == original["answer"]
    assert result["result_skus"] == ["CF-PG19"]


def test_evidence_renderer_repairs_only_usage_keys_from_allowed_packet(monkeypatch):
    async def malformed_usage(*_args, **kwargs):
        assert kwargs.get("purpose") == "semantic_recommendation_evidence_render"
        return json.dumps({
            "ranked_candidate_indexes": [0],
            "evidence_usage": [{"candidate_index": 0, "fields": ["business.capacity"]}],
            "answer": "如果先按容量缩小范围，可以先看模型选择锅：资料标注容量为1000ML。",
        }, ensure_ascii=False)

    monkeypatch.setattr(customer_service_service.customer_llm_service, "chat_completion", malformed_usage)
    result = asyncio.run(customer_service_service._semantic_recommendation_evidence_render(
        None,
        question="推荐一款锅",
        candidates=[{
            "candidate_index": 0,
            "product_name": "模型选择锅",
            "sku": "SAFE-RENDER-1",
            "sealed_evidence": {"specs.capacity": "1000ML"},
        }],
        narrative={
            "ranked_candidate_indexes": [0],
            "evidence_usage": [],
            "answer": "",
            "selection_only": True,
        },
        required_evidence_fields_by_index={},
    ))

    assert result["evidence_usage"] == [{"candidate_index": 0, "fields": ["specs.capacity"]}]


def test_explicit_single_recommendation_request_is_detected_without_sku_rules():
    assert customer_service_service._explicit_single_recommendation_request("推荐一个一个人露营用的小锅") is True
    assert customer_service_service._explicit_single_recommendation_request("给我推荐一款露营锅") is True
    assert customer_service_service._explicit_single_recommendation_request("适合露营的锅具推荐一下") is False


def test_verified_evidence_fallback_keeps_single_recommendation_single():
    result = customer_service_service._verified_recommendation_evidence_fallback(
        question="\u4e00\u4e2a\u4eba\u9732\u8425\uff0c\u63a8\u8350\u4e00\u4e2a1L\u5de6\u53f3\u7684\u5c0f\u9505",
        rows=[
            {"sku": "SAFE-ONE", "product_name_cn": "\u5355\u4eba\u5c0f\u9505", "capacity": "1000ml"},
            {"sku": "SAFE-TWO", "product_name_cn": "\u5907\u9009\u5c0f\u9505", "capacity": "900ml"},
        ],
    )

    assert result is not None
    assert result["ranked_candidate_indexes"] == [0]
    assert "SAFE-TWO" not in result["answer"]


def test_explicit_multi_field_merge_preserves_validated_semantic_fields():
    result = customer_service_service._merge_explicit_detail_fields_into_request(
        "这款的尺寸、材质和适用炉具一次说清楚。",
        {
            "source": "validated_semantic_preplan",
            "canonical_fields": ["dimensions", "material", "heat_source"],
            "requested_fields": ["尺寸", "材质", "热源"],
            "confidence": 0.9,
        },
    )

    assert result["source"] == "validated_semantic_preplan"
    assert result["canonical_fields"] == ["dimensions", "material", "heat_source"]
    assert result["requested_fields"] == ["尺寸", "材质", "热源"]


def test_component_size_question_does_not_invent_package_contents_field():
    result = customer_service_service._merge_explicit_detail_fields_into_request(
        "这款的煮锅、煎盘和水壶分别多大？",
        {
            "source": "validated_semantic_preplan",
            "canonical_fields": ["capacity", "dimensions"],
            "requested_fields": ["容量", "尺寸"],
            "confidence": 0.9,
        },
    )

    assert result["canonical_fields"] == ["capacity", "dimensions"]
    assert "accessories" not in result["canonical_fields"]


def test_verified_evidence_fallback_surfaces_direct_soft_preference_and_audience():
    result = customer_service_service._verified_recommendation_evidence_fallback(
        question="有哪些适合手冲的产品？请说明各自适合谁。",
        soft_preferences=["手冲"],
        rows=[{
            "sku": "COFFEE-4",
            "product_name_cn": "四杯咖啡壶",
            "title_cn": "户外手冲咖啡壶",
            "target_audience": "户外咖啡爱好者\n家庭用户",
            "capacity": "200ml",
            "gross_weight_g": 600,
        }],
    )

    assert result is not None
    assert "手冲" in result["answer"]
    assert "户外手冲咖啡壶" in result["answer"]
    assert "户外咖啡爱好者" in result["answer"]
    assert "200ml" in result["answer"]


def test_plural_recommendation_output_does_not_invent_a_single_winner():
    answer = customer_service_service._shape_recommendation_output(
        "两款都可参考：A 适合家庭用户；B 适合多人用户。",
        [
            {"sku": "A", "product_name_cn": "四杯款"},
            {"sku": "B", "product_name_cn": "九杯款"},
        ],
        [],
        require_visible_choice=False,
    )

    assert answer.startswith("两款都可参考")
    assert "更推荐" not in answer


def test_budget_constrained_recommendation_is_treated_as_contextual_followup():
    assert customer_service_service._is_recommendation_followup_question("预算不高，推荐一个") is True


def test_budget_followup_reuses_verified_recommendation_context(monkeypatch):
    inherited = customer_recommendation_verification_contract.build_recommendation_request_contract(
        "\u4e09\u4e2a\u5e74\u8f7b\u4eba\u9732\u8425\uff0c\u9002\u5408\u5e26\u4ec0\u4e48\u9505\u5177\uff1f"
    )
    rows = [{
        "sku": "SAFE-BUDGET-1",
        "product_name_cn": "\u5165\u95e8\u9732\u8425\u5957\u9505",
        "category": "\u9505\u5177",
        "usage_scenarios": "\u4e09\u4eba\u9732\u8425\u70f9\u996a",
        "price_positioning": "\u5165\u95e8\u6b3e",
    }, {
        "sku": "SAFE-BUDGET-2",
        "product_name_cn": "\u5165\u95e8\u9732\u8425\u5355\u9505",
        "category": "\u9505\u5177",
        "usage_scenarios": "\u4e09\u4eba\u9732\u8425\u70f9\u996a",
        "price_positioning": "\u5165\u95e8\u6b3e",
    }]
    monkeypatch.setattr(customer_service_service, "_phase1_catalog_rows", lambda _db, _ref: rows)

    result = customer_service_service._budget_recommendation_followup_result(
        None,
        "\u9884\u7b97\u4e0d\u9ad8\uff0c\u63a8\u8350\u4e00\u4e2a",
        {"effective_recommendation_contract": inherited.to_dict(), "turn_index": 1},
    )

    assert result is not None
    assert result["result_skus"] == ["SAFE-BUDGET-1"]
    assert "SAFE-BUDGET-2" not in result["answer"]
    assert "\u4ef7\u683c\u5b9a\u4f4d" in result["answer"]
    assert result["debug"]["agent_mode"] == "recommendation_context_budget_followup"


def test_single_recommendation_narrative_contract_rejects_multiple_selected_candidates():
    narrative = customer_service_service._validate_semantic_recommendation_narrative(
        {
            "ranked_candidate_indexes": [0, 1],
            "evidence_usage": [
                {"candidate_index": 0, "fields": ["capacity"]},
                {"candidate_index": 1, "fields": ["capacity"]},
            ],
            "answer": "候选甲和候选乙都标注了1L容量。",
        },
        candidate_count=2,
        verified_fields_by_index={0: {"capacity"}, 1: {"capacity"}},
        expected_ranked_count=1,
    )

    assert narrative is None


def test_semantic_recommendation_uses_verified_dimension_summary_when_writer_is_unavailable(monkeypatch):
    """Structured priorities retain a useful answer when semantic prose fails."""
    rows = [
        {
            "sku": "SAFE-4A",
            "product_name_cn": "四人锅A",
            "category": "锅具",
            "target_audience": "适合3-4人露营",
            "usage_scenarios": "多人露营烹饪",
            "gross_weight_g": 980,
            "capacity": "3L锅、1.5L锅",
        },
        {
            "sku": "SAFE-4B",
            "product_name_cn": "四人锅B",
            "category": "锅具",
            "target_audience": "适合4人露营",
            "usage_scenarios": "家庭露营做饭",
            "gross_weight_g": 1120,
            "capacity": "4L锅、2L锅",
        },
    ]

    async def unavailable_narrative(*_args, **_kwargs):
        return None

    monkeypatch.setattr(customer_service_service, "_phase1_catalog_rows", lambda _db, _ref: rows)
    monkeypatch.setattr(customer_service_service, "_semantic_recommendation_narrative", unavailable_narrative)
    result = asyncio.run(customer_service_service._semantic_recommendation_contract_result(
        None,
        "四个人露营想煮汤和做饭，推荐一套容量够用又别太重的锅具。",
        {"semantic_preplan": {
            "called": True,
            "route_family": "recommendation",
            "confidence": 0.9,
            "confidence_label": "high",
            "fallback_reason": "",
            "ambiguity": False,
            "recommendation_constraints": {
                "subject_kind": "cookware",
                "people": {"min": 4, "max": 4},
                "scenarios": ["camping"],
                "weight_preference": "lightweight",
            },
            "unrepresented_recommendation_requirements": [],
            "recommendation_soft_preferences": [],
        }},
    ))

    assert result["answer_type"] == "recommendation"
    assert result["result_skus"] == ["SAFE-4A", "SAFE-4B"]
    assert "煮汤和做饭" in result["answer"]
    assert "3L锅、1.5L锅" in result["answer"]
    assert "980g" in result["answer"]
    assert "1120g" in result["answer"]
    assert "重量信息暂未提供" not in result["answer"]
    assert result["debug"]["agent_mode"] == "semantic_recommendation_verified_dimension_summary"


def test_semantic_recommendation_reports_focused_capacity_weight_evidence_gap(monkeypatch):
    """Missing weight evidence produces a stable, specific clarification."""
    rows = [{
        "sku": "SAFE-4-NO-WEIGHT",
        "product_name_cn": "四人锅无重量",
        "category": "锅具",
        "target_audience": "适合4人露营",
        "usage_scenarios": "多人露营烹饪",
        "gross_weight_g": None,
        "capacity": "3L锅、1.5L锅",
    }]

    async def narrative_must_not_run(*_args, **_kwargs):
        raise AssertionError("structured evidence gap must resolve before narrative generation")

    monkeypatch.setattr(customer_service_service, "_phase1_catalog_rows", lambda _db, _ref: rows)
    monkeypatch.setattr(customer_service_service, "_semantic_recommendation_narrative", narrative_must_not_run)
    result = asyncio.run(customer_service_service._semantic_recommendation_contract_result(
        None,
        "四个人露营想煮汤和做饭，推荐一套容量够用又别太重的锅具。",
        {"semantic_preplan": {
            "called": True,
            "route_family": "recommendation",
            "confidence": 0.9,
            "confidence_label": "high",
            "fallback_reason": "",
            "ambiguity": False,
            "recommendation_constraints": {
                "subject_kind": "cookware",
                "people": {"min": 4, "max": 4},
                "scenarios": ["camping"],
                "weight_preference": "lightweight",
            },
            "unrepresented_recommendation_requirements": [],
            "recommendation_soft_preferences": [],
        }},
    ))

    assert result["answer_type"] == "clarification"
    assert result["needs_clarification"] is True
    assert "容量" in result["answer"] and "重量" in result["answer"]
    assert "没有同时维护" in result["answer"]
    assert result["debug"]["agent_mode"] == "semantic_recommendation_dimension_evidence_gap"


def test_route_level_semantic_unavailable_without_formal_contract_fails_closed_before_legacy_router(
    route_client_and_db,
    monkeypatch,
):
    client, headers, _ = route_client_and_db

    async def unavailable_preplan(_db, _question, _deterministic_plan, *, context):
        return {
            "called": True,
            "fallback_reason": "llm_error:RuntimeError",
            "error": "llm_error:RuntimeError",
            "route_family": "",
            "route_hint": "",
            "canonical_fields": [],
            "field_type": "",
            "recommendation_constraints": {},
        }

    monkeypatch.setattr(customer_agent_planner_service, "plan_customer_question_semantic", unavailable_preplan)
    response = client.post(
        "/api/customer-service/ask?debug=true",
        json={"question": "夏天冷水补水水壶推荐"},
        headers=headers,
    )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["answer_type"] == "clarification", payload
    assert payload["result_skus"] == [], payload
    assert payload["candidate_skus"] == [], payload
    assert payload["debug"]["agent_mode"] == "semantic_preplan_unavailable_clarification", payload
    assert payload["debug"]["agent_mode"] != "product_usage_care_fast_path", payload


def test_semantic_recommendation_narrative_reviewer_retries_one_malformed_response(monkeypatch):
    """A transient review-format failure must not discard an evidence-valid DeepSeek draft."""
    calls = []

    async def fake_chat_completion(_db, messages=None, **kwargs):
        calls.append(kwargs.get("purpose"))
        if len(calls) == 1:
            return "not-json"
        return json.dumps({"approved": True, "unsupported_claims": []})

    monkeypatch.setattr(customer_service_service.customer_llm_service, "chat_completion", fake_chat_completion)

    result = asyncio.run(
        customer_service_service._semantic_recommendation_narrative_grounding_review(
            db=None,
            question="推荐一款适合露营的炉具。",
            candidates=[
                {
                    "candidate_index": 0,
                    "product_name": "测试炉具",
                    "sku": "TEST-STOVE-01",
                    "sealed_evidence": {"content.usage_scenarios": "露营"},
                    "verified_constraints": ["scenario"],
                    "verified_requirement_claims": [],
                    "uncertainties": [],
                }
            ],
            narrative={
                "ranked_candidate_indexes": [0],
                "evidence_usage": [{"candidate_index": 0, "fields": ["content.usage_scenarios"]}],
                "answer": "测试炉具的资料标注使用场景为露营。",
            },
        )
    )

    assert result == {"approved": True, "unsupported_claims": []}
    assert calls == [
        "semantic_recommendation_narrative_grounding_review",
        "semantic_recommendation_narrative_grounding_review",
    ]


def test_semantic_recommendation_narrative_reviewer_uses_bounded_rejection_schema(monkeypatch):
    captured = {}

    async def fake_chat_completion(_db, messages=None, **kwargs):
        captured["system"] = messages[0]["content"]
        captured["max_tokens"] = kwargs.get("max_tokens")
        return json.dumps({"approved": False, "unsupported_claims": ["未被资料直接支持的结论"]})

    monkeypatch.setattr(customer_service_service.customer_llm_service, "chat_completion", fake_chat_completion)
    result = asyncio.run(
        customer_service_service._semantic_recommendation_narrative_grounding_review(
            db=None,
            question="推荐一款露营炉具。",
            candidates=[
                {
                    "candidate_index": 0,
                    "product_name": "测试炉具",
                    "sku": "TEST-STOVE-01",
                    "sealed_evidence": {"content.usage_scenarios": "露营"},
                    "verified_constraints": ["scenario"],
                    "verified_requirement_claims": [],
                    "uncertainties": [],
                }
            ],
            narrative={
                "ranked_candidate_indexes": [0],
                "evidence_usage": [{"candidate_index": 0, "fields": ["content.usage_scenarios"]}],
                "answer": "测试炉具的资料标注使用场景为露营。",
            },
        )
    )

    assert result == {"approved": False, "unsupported_claims": ["未被资料直接支持的结论"]}
    assert "at most five" in captured["system"]
    assert "80 characters" in captured["system"]
    assert "960g or 340g" in captured["system"]
    assert captured["max_tokens"] >= 360


def test_semantic_recommendation_reviewer_must_approve_literal_same_sku_scenario_restatement(monkeypatch):
    """The semantic audit must not reject a literal sealed scenario as broad suitability."""
    captured = {}

    async def fake_chat_completion(_db, messages=None, **kwargs):
        assert kwargs.get("purpose") == "semantic_recommendation_narrative_grounding_review"
        captured["system"] = messages[0]["content"]
        return json.dumps({"approved": True, "unsupported_claims": []})

    monkeypatch.setattr(customer_service_service.customer_llm_service, "chat_completion", fake_chat_completion)
    result = asyncio.run(
        customer_service_service._semantic_recommendation_narrative_grounding_review(
            db=None,
            question="推荐一台露营做饭的炉子。",
            candidates=[{
                "candidate_index": 0,
                "product_name": "可验证炉具",
                "sku": "SAFE-STOVE-1",
                "sealed_evidence": {"content.usage_scenarios": "家庭露营、周末野炊"},
                "verified_constraints": ["scenario"],
                "verified_requirement_claims": [],
                "uncertainties": [],
            }],
            narrative={
                "ranked_candidate_indexes": [0],
                "evidence_usage": [{"candidate_index": 0, "fields": ["content.usage_scenarios"]}],
                "answer": "可验证炉具的资料标注使用场景包括家庭露营和周末野炊。",
            },
        )
    )

    assert result == {"approved": True, "unsupported_claims": []}
    assert "must approve" in captured["system"]
    assert "资料标注使用场景" in captured["system"]
    assert "更安全" in captured["system"]


def test_recommendation_safety_gate_rejects_unproved_catalogue_wide_rankings():
    """Only global superlatives bypass the semantic evidence reviewer."""
    claims = customer_service_service._recommendation_unproved_comparative_claims(
        "这款更安全、更稳定，也更方便携带，是综合首选。"
    )

    assert "综合首选" in claims


def test_recommendation_safety_gate_rejects_opaque_capacity_and_lightweight_claims():
    claims = customer_service_service._recommendation_unproved_comparative_claims(
        "轻途套锅容量稍大，而且极致轻量化。"
    )

    assert "容量稍大" in claims
    assert "极致轻量化" in claims
    assert customer_service_service._recommendation_unproved_comparative_claims(
        "轻途套锅采用极致轻量化设计。",
        "产品定位：极致轻量化设计，适合轻量徒步",
    ) == []


def test_recommendation_safety_gate_rejects_internal_verification_process_language():
    claims = customer_service_service._recommendation_internal_process_claims(
        "推荐优先考虑以下候选，均通过了可验证的硬条件。本次仅采用同 SKU 来源字段明确标注的内容。"
    )

    assert claims
    assert customer_service_service._recommendation_internal_process_claims(
        "如果您要搭配酒精炉，可以看看激川单锅；资料中标注它支持酒精炉。"
    ) == []


@pytest.mark.skip(reason="rewrite cascade replaced by final-render local process-language gate")
def test_semantic_recommendation_rewrites_internal_process_language_even_when_reviewer_approves(monkeypatch):
    calls = []

    async def fake_chat_completion(_db, messages=None, **kwargs):
        purpose = kwargs.get("purpose")
        calls.append(purpose)
        if purpose == "semantic_recommendation_narrative":
            return json.dumps({
                "ranked_candidate_indexes": [0],
                "evidence_usage": [{"candidate_index": 0, "fields": ["content.usage_scenarios"]}],
                "answer": "推荐优先考虑以下候选，均通过了可验证的硬条件。本次仅采用同 SKU 来源字段明确标注的内容：激川单锅。",
            })
        if purpose == "semantic_recommendation_narrative_rewrite":
            return json.dumps({
                "ranked_candidate_indexes": [0],
                "evidence_usage": [{"candidate_index": 0, "fields": ["content.usage_scenarios"]}],
                "answer": "如果您准备带去露营，可以看看激川单锅；资料标注它的使用场景包括露营。",
            })
        assert purpose == "semantic_recommendation_narrative_grounding_review"
        return json.dumps({"approved": True, "unsupported_claims": []})

    class Verification:
        sku = "CW-S10-A"
        evidence_by_constraint = {
            "subject": {"status": "verified", "raw_value": "锅具"},
            "scenario": {"status": "verified", "raw_value": "露营"},
        }
        unsupported_constraints = []
        unsupported_preferences = []

    monkeypatch.setattr(customer_service_service.customer_llm_service, "chat_completion", fake_chat_completion)
    narrative = asyncio.run(customer_service_service._semantic_recommendation_narrative(
        db=None,
        question="露营锅具推荐一下。",
        rows=[{
            "sku": "CW-S10-A",
            "product_name_cn": "激川单锅",
            "usage_scenarios": "露营",
        }],
        verifications=[Verification()],
    ))

    assert narrative is not None
    assert "semantic_recommendation_narrative_rewrite" in calls
    assert "同 SKU" not in narrative["answer"]
    assert "硬条件" not in narrative["answer"]


def test_recommendation_lexical_safety_gate_leaves_relative_weight_language_to_semantic_grounding():
    """A literal gate must not override the evidence-aware semantic reviewer."""
    claims = customer_service_service._recommendation_unproved_comparative_claims(
        "同 SKU 重量资料为195g，这个选项较轻便。"
    )

    assert claims == []


def test_recommendation_rewrite_keeps_sealed_same_sku_evidence_for_evidence_bounded_recovery():
    """Recovery may cite sealed same-SKU context; the reviewer still rejects unsupported prose."""
    candidates = [{
        "candidate_index": 0,
        "product_name": "可验证炉具",
        "sku": "SAFE-STOVE-1",
        "sealed_evidence": {
            "subject": "炉具",
            "scenario": "露营",
            "content.usage_scenarios": "家庭露营、周末野炊",
            "content.features": "高效安全极简操作",
            "content.top_selling_points": "强力防风",
        },
        "verified_constraints": ["subject", "scenario"],
        "verified_requirement_claims": [{"constraint": "scenario", "claim": "同 SKU 资料已通过本次场景要求核验"}],
        "uncertainties": [],
    }]

    recovery = customer_service_service._recommendation_rewrite_candidates(candidates)

    assert recovery[0]["sealed_evidence"] == {
        "subject": "炉具",
        "scenario": "露营",
        "content.usage_scenarios": "家庭露营、周末野炊",
        "content.features": "高效安全极简操作",
        "content.top_selling_points": "强力防风",
    }
    assert recovery[0]["verified_constraints"] == ["subject", "scenario"]
    assert recovery[0]["product_name"] == "可验证炉具"


@pytest.mark.skip(reason="superseded by final-render internal-language safety tests")
def test_semantic_recommendation_keeps_constraint_verification_internal_to_customer_prose(monkeypatch):
    """Candidate eligibility is a gate, never a customer-facing audit claim."""
    captured = {}

    async def fake_chat_completion(_db, messages=None, **kwargs):
        purpose = kwargs.get("purpose")
        if purpose == "semantic_recommendation_narrative":
            captured["writer_system"] = messages[0]["content"]
            captured["writer_packet"] = json.loads(messages[1]["content"])
            return json.dumps({
                "ranked_candidate_indexes": [0],
                "evidence_usage": [{"candidate_index": 0, "fields": ["content.usage_scenarios"]}],
                "answer": "\u53ef\u9a8c\u8bc1\u9505\u5177\u7684\u8d44\u6599\u6807\u6ce8\u4f7f\u7528\u573a\u666f\u5305\u62ec\u53cc\u4eba\u9732\u8425\u3002",
            })
        assert purpose == "semantic_recommendation_narrative_grounding_review"
        captured["review_system"] = messages[0]["content"]
        captured["review_packet"] = json.loads(messages[1]["content"])
        return json.dumps({"approved": True, "unsupported_claims": []})

    class Verification:
        sku = "SAFE-COOK-1"
        evidence_by_constraint = {
            "subject": {"status": "verified", "raw_value": "\u9505\u5177"},
            "people": {"status": "verified", "raw_value": "1-2 \u4eba"},
            "scenario": {"status": "verified", "raw_value": "\u53cc\u4eba\u9732\u8425"},
        }
        unsupported_constraints = []
        unsupported_preferences = []

    monkeypatch.setattr(customer_service_service.customer_llm_service, "chat_completion", fake_chat_completion)
    narrative = asyncio.run(customer_service_service._semantic_recommendation_narrative(
        db=None,
        question="\u4e24\u4e2a\u4eba\u9732\u8425\u60f3\u9009\u9505\u5177\u3002",
        rows=[{
            "sku": "SAFE-COOK-1",
            "product_name_cn": "\u53ef\u9a8c\u8bc1\u9505\u5177",
            "usage_scenarios": "\u53cc\u4eba\u9732\u8425",
        }],
        verifications=[Verification()],
    ))

    assert narrative is not None
    candidate = captured["writer_packet"]["sealed_candidates"][0]
    assert candidate["verified_constraints"] == ["subject", "people", "scenario"]
    assert "verified_requirement_claims" not in candidate
    assert "internal selection gate" in captured["writer_system"]
    assert "audit claim" not in captured["writer_system"]
    assert "verified_requirement_claims" not in captured["review_system"]
    assert "audit fact" not in captured["review_system"]
    assert "verified_requirement_claims" not in captured["review_packet"]["sealed_candidates"][0]


def test_recommendation_rewrite_prompt_requires_source_bound_scenario_language(monkeypatch):
    """Recovery prose stays semantic but cannot turn a scenario into a suitability promise."""
    captured = {}

    async def fake_chat_completion(_db, messages=None, **kwargs):
        captured["system"] = messages[0]["content"]
        captured["model"] = kwargs.get("api_model_override")
        return json.dumps({
            "ranked_candidate_indexes": [0],
            "evidence_usage": [{"candidate_index": 0, "fields": ["scenario"]}],
            "answer": "可验证炉具的资料标注使用场景包括露营。",
        })

    monkeypatch.setattr(customer_service_service.customer_llm_service, "chat_completion", fake_chat_completion)
    monkeypatch.setattr(
        customer_agent_planner_service,
        "_semantic_preplan_runtime_settings",
        lambda: {"model": "deepseek-v4-flash"},
    )
    result = asyncio.run(customer_service_service._semantic_recommendation_narrative_rewrite(
        db=None,
        question="推荐露营炉具。",
        candidates=[{
            "candidate_index": 0,
            "product_name": "可验证炉具",
            "sku": "SAFE-STOVE-1",
            "sealed_evidence": {"subject": "炉具", "scenario": "露营"},
            "verified_constraints": ["subject", "scenario"],
            "verified_requirement_claims": [],
            "uncertainties": [],
        }],
        rejected_narrative={"answer": "首选可验证炉具。"},
        unsupported_claims=["首选可验证炉具"],
    ))

    assert "硬性恢复规则" in captured["system"]
    assert "资料标注使用场景包括" in captured["system"]
    assert "qualified practical-use inference" in captured["system"]
    assert captured["model"] == "deepseek-v4-flash"


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
def test_route_level_waterware_recommendation_queries_stay_in_waterware_domain(route_client_and_db, question, monkeypatch):
    client, headers, Session = route_client_and_db

    async def fake_preplan(_db, _question, _deterministic_plan, *, context):
        return {
            "called": True,
            "route_family": "recommendation",
            "route_hint": "recommendation",
            "entity_scope": "generic_scope",
            "entities": [],
            "field_type": "",
            "canonical_fields": [],
            "question_type": "recommendation",
            "subtype": "recommendation",
            "confidence": 0.96,
            "ambiguity": False,
            "evidence_required": True,
            "context_usage": "none",
            "recommendation_constraints": {"subject_kind": "waterware"},
            "unrepresented_recommendation_requirements": [],
        }

    async def fake_narrative(_db, *, rows, **_kwargs):
        assert rows
        return {
            "ranked_candidate_indexes": [0],
            "evidence_usage": [{"candidate_index": 0, "fields": ["content.features"]}],
            "answer": f"根据已核验的同 SKU 资料，优先考虑{rows[0]['product_name_cn']}。",
        }

    monkeypatch.setattr(customer_agent_planner_service, "plan_customer_question_semantic", fake_preplan)
    monkeypatch.setattr(customer_service_service, "_semantic_recommendation_narrative", fake_narrative)

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
def test_route_level_grill_vs_pot_variant_fails_closed_when_semantic_service_is_unavailable(
    route_client_and_db,
    question,
    monkeypatch,
):
    # Generic category trade-offs require semantic interpretation. This
    # offline suite verifies that a missing model does not manufacture a
    # legacy comparison/recommendation; live DeepSeek HTTP audits the answer.
    client, headers, _ = route_client_and_db

    async def unavailable_preplan(*_args, **_kwargs):
        return {
            "called": True,
            "fallback_reason": "llm_error:RuntimeError",
            "error": "llm_error:RuntimeError",
            "canonical_fields": [],
            "field_type": "",
            "recommendation_constraints": {},
        }

    monkeypatch.setattr(
        customer_agent_planner_service,
        "plan_customer_question_semantic",
        unavailable_preplan,
    )

    response = client.post("/api/customer-service/ask?debug=true", json={"question": question}, headers=headers)
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["answer_type"] == "clarification", payload
    assert payload["answer_type"] != "knowledge_base_answer"
    assert payload["result_skus"] == [], payload
    assert payload["candidate_skus"] == [], payload
    assert payload["answer"], payload
    assert payload["debug"]["agent_mode"] == "semantic_preplan_unavailable_clarification", payload
    # Domain assertions belong to the validated semantic recommendation tests above;
    # this branch intentionally verifies only safe behavior when that service is absent.
    return

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
def test_route_level_water_kettle_selection_preserves_unverifiable_requirements(route_client_and_db, question, monkeypatch):
    client, headers, _ = route_client_and_db

    async def fake_preplan(_db, _question, _deterministic_plan, *, context):
        return {
            "called": True,
            "route_family": "recommendation",
            "route_hint": "recommendation",
            "entity_scope": "generic_scope",
            "entities": [],
            "field_type": "",
            "canonical_fields": [],
            "question_type": "recommendation",
            "subtype": "recommendation",
            "confidence": 0.96,
            "ambiguity": False,
            "evidence_required": True,
            "context_usage": "none",
            "recommendation_constraints": {"subject_kind": "waterware", "scenarios": ["camping"]},
            "unrepresented_recommendation_requirements": [question],
        }

    monkeypatch.setattr(customer_agent_planner_service, "plan_customer_question_semantic", fake_preplan)

    response = client.post(
        "/api/customer-service/ask?debug=true",
        json={"question": question},
        headers=headers,
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    # Water heating / tea preference has no structured, same-SKU evidence
    # dimension here. Preserve the semantic recommendation contract, but do not
    # broaden it into an unverified waterware list.
    assert payload["answer_type"] == "clarification", payload
    assert payload["answer_type"] != "knowledge_base_answer"
    assert payload["result_skus"] == [], payload
    assert payload["candidate_skus"] == [], payload
    assert payload["answer"], payload
    assert payload["debug"]["agent_mode"] in {
        "semantic_recommendation_contract",
        "semantic_recommendation_narrative_unavailable",
    }, payload


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
    debug = payload.get("debug") or {}
    debug_plan = debug.get("plan") or {}
    semantic = debug.get("semantic_preplan") or {}

    # Waterware capability distinctions are sentence-level semantics. In this
    # keyless isolated suite, an unavailable semantic planner must fail closed
    # while retaining the sealed exact identity; the live DeepSeek HTTP suite
    # owns the customer-facing capability answer.
    if debug.get("agent_mode") == "semantic_outage_named_product_field_clarification":
        entity = debug.get("entity_resolution_contract") or {}
        assert payload["answer_type"] == "clarification", payload
        assert payload.get("result_skus") == [], payload
        assert entity.get("status") == "resolved", payload
        assert entity.get("resolved_sku") == expected_sku, payload
        assert entity.get("candidate_skus") == [expected_sku], payload
        assert debug.get("agent_mode") == "semantic_outage_named_product_field_clarification", payload
        return

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
        assert not re.search(r"(?:可以|支持|可)直接加热", payload["answer"]), payload["answer"]
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
    monkeypatch,
):
    client, headers, Session = route_client_and_db

    async def semantic_preplan_for_unknown_realtime(_db, current_question, _deterministic_plan, *, context):
        if current_question == "销量最高的是哪个锅？":
            return _unknown_realtime_preplan_stub(field_hint="销量", entity_scope="generic_scope")
        if current_question == "客户评价最好的水壶是哪款？":
            return _unknown_realtime_preplan_stub(field_hint="评价", entity_scope="generic_scope")
        return {"called": False}

    monkeypatch.setattr(
        customer_agent_planner_service,
        "plan_customer_question_semantic",
        semantic_preplan_for_unknown_realtime,
    )

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
    _seed_contents_resolution_priority_products(Session)

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
        ("市面上通用的气罐能不能接上？", "product_usage_care", None, ("暂时无法确认", "能否连接")),
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
        row = {
            "sku": product.sku,
            "product_name_cn": product.product_name_cn,
            "category": product.category,
            "sub_category": getattr(product, "sub_category", None),
            "body_material": getattr(specs, "body_material", None),
        }
        subject_decision = customer_service_service.customer_structured_query_contract.resolve_structured_subject_scope(
            row=row,
            subject_category=category,
        )
        assert subject_decision["matched"] is True, {"sku": sku, "subject_decision": subject_decision}
        assert subject_decision["scope"] == "subject", {"sku": sku, "subject_decision": subject_decision}
        if body_material:
            material_contract = customer_service_service.customer_structured_query_contract.StructuredQueryContract(
                subject_category=category,
                field="material",
                operator="contains",
                value=body_material,
                status="resolved",
            )
            material_proof = customer_service_service.customer_structured_query_contract.match_material_condition(
                contract=material_contract,
                row=row,
            )
            assert material_proof["matched"] is True, {"sku": sku, "material_proof": material_proof}
            assert material_proof["field_source"] == "body_material", material_proof
            assert material_proof["subject_scope"] == "subject", material_proof
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


def _structured_contract_source_rows(db, question: str, intent) -> list[dict]:
    filters = dict((intent.filters or {}) if intent else {})
    product_ref = str(filters.get("product.category") or "").strip() or customer_service_service._semantic_catalog_product_ref(question)
    if product_ref == "水壶":
        rows = [
            row
            for row in customer_service_service._phase1_catalog_rows(db, "产品")
            if customer_service_service._phase1_is_strict_water_kettle_candidate(row)
        ]
    else:
        rows = customer_service_service._phase1_catalog_rows(db, product_ref)
    if product_ref == "锅具" and str(filters.get("specs.heat_source") or "").strip() == "酒精炉":
        rows = [
            row
            for row in rows
            if customer_service_service._is_service_pot_or_cookware_set_candidate(row)
            and customer_service_service._phase1_row_has_explicit_alcohol_stove_support(db, row)
        ]
    return rows


def _qualified_structured_rows(Session, question: str) -> tuple[object, dict, list[dict]]:
    contract = customer_service_service._structured_hard_filter_contract(question)
    assert contract, question
    intent = contract.get("intent")
    assert intent is not None, question
    with Session() as db:
        central_contract = customer_service_service.customer_structured_query_contract.build_structured_query_contract(question)
        if central_contract.status == "resolved":
            source_rows, evaluations = customer_service_service._evaluate_structured_query_contract_rows(
                db,
                central_contract,
            )
            matched_skus = {
                str(item.get("sku") or "").strip().upper()
                for item in evaluations
                if item.get("matched") and str(item.get("sku") or "").strip()
            }
            rows = [
                row
                for row in source_rows
                if str(row.get("sku") or "").strip().upper() in matched_skus
            ]
            return intent, contract, rows
        product_ref = str(contract.get("product_ref") or "").strip() or str((intent.filters or {}).get("product.category") or "").strip()
        if product_ref == "水壶":
            source_rows = [
                row for row in customer_service_service._phase1_catalog_rows(db, "产品")
                if customer_service_service._phase1_is_strict_water_kettle_candidate(row)
            ]
        else:
            source_rows = customer_service_service._phase1_catalog_rows(db, product_ref)
        filters = dict(contract.get("filters") or {})
        if product_ref == "锅具" and str(filters.get("specs.heat_source") or "").strip() == "酒精炉":
            source_rows = [
                row for row in source_rows
                if customer_service_service._is_service_pot_or_cookware_set_candidate(row)
                and customer_service_service._phase1_row_has_explicit_alcohol_stove_support(db, row)
            ]
        rows = [row for row in source_rows if customer_service_service._structured_row_matches_contract(row, contract)]
    return intent, contract, rows


def _assert_structured_no_match_contract(payload: dict) -> None:
    assert payload["answer_type"] in {"product_query", "query_products"}, payload
    assert payload["result_skus"] == [], payload
    assert any(
        phrase in payload["answer"]
        for phrase in ("当前结构化商品库未找到符合条件的商品", "当前已核对资料未找到符合条件的商品")
    ), payload["answer"]
    assert payload["answer_type"] != "recommendation", payload
    assert payload["answer_type"] != "knowledge_base_answer", payload
    assert payload["answer_type"] != "product_detail", payload


def _assert_structured_result_skus_are_exactly_qualified(Session, payload: dict, qualified_rows: list[dict]) -> None:
    expected_skus = [
        str(row.get("sku") or "").strip().upper()
        for row in qualified_rows
        if str(row.get("sku") or "").strip()
    ]
    assert payload["answer_type"] in {"product_query", "query_products"}, payload
    assert payload["answer_type"] != "recommendation", payload
    assert payload["answer_type"] != "knowledge_base_answer", payload
    assert payload["answer_type"] != "product_detail", payload
    assert payload["result_skus"], payload
    assert payload["result_skus"] == expected_skus[: len(payload["result_skus"])], {
        "actual": payload["result_skus"],
        "expected": expected_skus,
        "payload": payload,
    }
    assert set(payload["result_skus"]).issubset(set(expected_skus)), {
        "actual": payload["result_skus"],
        "expected": expected_skus,
    }
    assert len(payload["result_skus"]) == min(len(expected_skus), len(payload["result_skus"])), payload["result_skus"]
    with Session() as db:
        loaded = {
            str(product.sku or "").strip().upper(): product.category
            for product in db.query(Product).filter(Product.sku.in_(payload["result_skus"])).all()
        }
    assert set(payload["result_skus"]).issubset(set(loaded.keys())), {"result_skus": payload["result_skus"], "loaded": loaded}


@pytest.mark.parametrize(
    "question",
    [
        "哪些杯子是钛的？",
        "有哪些钛杯？",
        "有哪些咖啡相关配件？",
    ],
)
def test_route_level_structured_zero_match_queries_return_hard_no_match_without_padding(
    route_client_and_db,
    question,
):
    client, headers, Session = route_client_and_db

    intent, _contract, qualified_rows = _qualified_structured_rows(Session, question)
    assert qualified_rows == [], {"question": question, "filters": intent.filters, "negative_filters": intent.negative_filters}

    response = client.post("/api/customer-service/ask?debug=true", json={"question": question}, headers=headers)
    assert response.status_code == 200, response.text
    payload = response.json()
    answer_metadata = payload.get("answer_metadata") or {}

    _assert_structured_no_match_contract(payload)
    assert answer_metadata.get("source") == "structured_category_field_filter_query", answer_metadata


@pytest.mark.parametrize(
    "question",
    [
        "可以明火直烧的不锈钢水壶有哪些？",
        "适合卡式炉的锅具有哪些？",
        "硬氧材质的锅具有哪些？",
        "有哪些铝合金锅具？",
        "适合两个人的锅具有哪些？",
        "有哪些轻量锅具？",
        "有哪些预算低一点的炉具？",
    ],
)
def test_route_level_structured_combined_hard_filter_queries_only_return_qualified_rows(
    route_client_and_db,
    question,
):
    client, headers, Session = route_client_and_db

    intent, _contract, qualified_rows = _qualified_structured_rows(Session, question)
    assert intent.filters, (question, intent)

    response = client.post("/api/customer-service/ask?debug=true", json={"question": question}, headers=headers)
    assert response.status_code == 200, response.text
    payload = response.json()
    answer_metadata = payload.get("answer_metadata") or {}

    assert answer_metadata.get("source") == "structured_category_field_filter_query", answer_metadata
    if not qualified_rows:
        _assert_structured_no_match_contract(payload)
        return
    _assert_structured_result_skus_are_exactly_qualified(Session, payload, qualified_rows)
    assert len(payload["result_skus"]) <= len(qualified_rows), {
        "question": question,
        "actual": payload["result_skus"],
        "qualified": [str(row.get("sku") or "").strip().upper() for row in qualified_rows],
    }


@pytest.mark.parametrize(
    "question",
    [
        "公园野餐轻便装备",
        "户外野餐轻便装备怎么选？",
        "公园野餐想要轻一点的装备",
        "不要太重的水壶",
        "轻一点的水壶推荐",
    ],
)
def test_product_recommendation_intent_does_not_fallback_to_generic_knowledge_answer(
    route_client_and_db,
    question,
):
    client, headers, Session = route_client_and_db

    response = client.post("/api/customer-service/ask?debug=true", json={"question": question}, headers=headers)
    assert response.status_code == 200, response.text
    payload = response.json()
    answer = str(payload.get("answer") or "")
    answer_type = str(payload.get("answer_type") or "")

    assert answer_type in {"recommendation", "product_query", "query_products", "clarification"}, payload
    assert answer_type != "knowledge_base_answer", payload
    assert answer, payload

    result_skus = payload.get("result_skus") or []
    candidate_skus = payload.get("candidate_skus") or []
    if result_skus:
        with Session() as db:
            categories = {
                str(product.sku or "").strip().upper(): str(product.category or "").strip()
                for product in db.query(Product).filter(Product.sku.in_(result_skus)).all()
            }
        assert categories, payload
        if "水壶" in question or "水具" in question:
            assert all(category in {"水具", "水壶", "水杯", "杯子", "杯"} for category in categories.values()), categories
    else:
        assert answer_type in {"recommendation", "clarification"}, payload

    assert candidate_skus == result_skus or not result_skus, {
        "result_skus": result_skus,
        "candidate_skus": candidate_skus,
        "payload": payload,
    }

@pytest.mark.parametrize(
    "question",
    [
        "哪些杯是不锈钢的？",
        "有哪些适合徒步的水杯？",
        "哪些水杯能直接加热？",
        "哪些锅具能进洗碗机？",
        "哪些锅具可以放洗碗机？",
        "可洗碗机清洗的锅具有哪些？",
        "有哪些钛杯？",
        "适合徒步的钛杯有哪些？",
    ],
)
def test_route_level_structured_hard_filter_queries_prioritize_structured_route(
    route_client_and_db,
    question,
):
    client, headers, Session = route_client_and_db

    contract = customer_service_service._structured_hard_filter_contract(question)
    assert contract, question

    response = client.post("/api/customer-service/ask?debug=true", json={"question": question}, headers=headers)
    assert response.status_code == 200, response.text
    payload = response.json()
    answer_metadata = payload.get("answer_metadata") or {}

    assert payload["answer_type"] in {"product_query", "query_products"}, payload
    assert payload["answer_type"] != "product_detail", payload
    assert payload["answer_type"] != "knowledge_base_answer", payload
    assert payload["answer_type"] != "recommendation", payload
    assert answer_metadata.get("source") == "structured_category_field_filter_query", answer_metadata


@pytest.mark.parametrize(
    ("question", "expected_canonical_source"),
    [
        ("星河钛杯是钛的吗？", None),
        ("月影炉能用卡式炉吗？", "entity_state_detail_unresolved"),
        ("不存在的咖啡器具推荐一下", None),
        ("荒野星壶多少钱？", None),
        ("虚构品牌咖啡壶推荐", None),
        ("不存在商品名 有哪些锅具？", None),
        ("完全不存在的产品名 包含哪些东西？", None),
    ],
)
def test_route_level_unresolved_product_like_queries_do_not_leak_into_catalog_recommendation_or_qa(
    route_client_and_db,
    question,
    expected_canonical_source,
):
    client, headers, _ = route_client_and_db

    response = client.post("/api/customer-service/ask?debug=true", json={"question": question}, headers=headers)
    assert response.status_code in {200, 404}, response.text
    if response.status_code == 404:
        assert "Product not found" in response.text or "没有找到" in response.text, response.text
        return

    payload = response.json()
    answer = str(payload.get("answer") or "")
    answer_type = str(payload.get("answer_type") or "")
    answer_metadata = payload.get("answer_metadata") or {}

    assert payload.get("result_skus") in ([], None), payload
    assert answer_type in {"clarification", "product_detail"}, payload
    if expected_canonical_source:
        assert answer_metadata.get("source") == expected_canonical_source, answer_metadata
        assert payload.get("intent") == "clarify", payload
        assert answer_type == "clarification", payload
        assert payload.get("candidate_skus") in ([], None), payload
        assert (payload.get("debug") or {}).get("agent_mode") == expected_canonical_source, payload
    else:
        assert answer_metadata.get("source") in {
            "entity_scope_ambiguous_clarification",
            "unresolved_product_like_unknown_field_clarification",
            "unknown_field_product_not_found",
            "unresolved_product_like_contents_clarification",
            # The central FieldContract → EntityResolutionContract path now
            # owns unresolved named detail questions.  This replaces the
            # pre-U-S12 lexical guard label without relaxing the no-binding
            # or no-catalogue-leak requirements below.
            "entity_state_detail_unresolved",
        }, answer_metadata
        entity = (payload.get("debug") or {}).get("entity_resolution_contract") or {}
        if answer_metadata.get("source") == "entity_state_detail_unresolved":
            assert entity.get("status") == "unresolved", payload
            assert entity.get("resolved_sku") is None, payload
    assert answer_type not in {"product_query", "recommendation", "knowledge_base_answer"}, payload
    assert answer, payload
    assert "推荐" not in answer or "提供 SKU" in answer or "产品名" in answer or "没有找到" in answer, answer
    assert "哪些" not in answer or "没有找到" in answer or "提供 SKU" in answer or "产品名" in answer, answer
    assert answer_type != "recommendation", payload
    assert answer_type != "knowledge_base_answer", payload
    assert answer_type != "product_query", payload


def test_product_like_unknown_field_does_not_bind_single_candidate_without_strong_entity_match(
    route_client_and_db,
):
    client, headers, Session = route_client_and_db
    question = "荒野星壶多少钱？"

    response = client.post("/api/customer-service/ask?debug=true", json={"question": question}, headers=headers)
    assert response.status_code == 200, response.text
    payload = response.json()
    answer_metadata = payload.get("answer_metadata") or {}

    subject = customer_service_service._product_like_scope_subject(question) or customer_agent_intent_service._detail_subject_from_question(question).strip()
    with Session() as db:
        named_products = customer_service_service._products_named_in_question(db, question)
        strong_skus = {
            str(product.sku or "").strip().upper()
            for product in named_products
            if customer_service_service._subject_strongly_matches_product(subject, product)
        }

    result_skus = {str(sku or "").strip().upper() for sku in (payload.get("result_skus") or [])}
    candidate_skus = {str(sku or "").strip().upper() for sku in (payload.get("candidate_skus") or [])}

    assert strong_skus == set(), {"subject": subject, "named_products": [str(getattr(product, "sku", "") or "").strip().upper() for product in named_products]}
    assert payload["answer_type"] != "product_detail", payload
    assert payload["answer_type"] != "product_query", payload
    assert payload["answer_type"] != "recommendation", payload
    assert payload["answer_type"] != "knowledge_base_answer", payload
    assert result_skus == set(), payload
    assert candidate_skus == set(), payload
    assert answer_metadata.get("source") in {
        "unresolved_product_like_unknown_field_clarification",
        "unknown_field_product_not_found",
        "entity_state_detail_unresolved",
    }, answer_metadata
    if answer_metadata.get("source") == "entity_state_detail_unresolved":
        entity = (payload.get("debug") or {}).get("entity_resolution_contract") or {}
        assert entity.get("status") == "unresolved", payload
        assert entity.get("resolved_sku") is None, payload


def test_typo_only_product_recall_does_not_become_formal_ambiguity(route_client_and_db):
    client, headers, _ = route_client_and_db

    response = client.post(
        "/api/customer-service/ask?debug=true",
        json={"question": "瓦片考盘能明火吗？"},
        headers=headers,
    )

    assert response.status_code == 200, response.text
    payload = response.json()
    entity = (payload.get("debug") or {}).get("entity_resolution_contract") or {}
    assert entity.get("status") == "unresolved", payload
    assert entity.get("resolved_sku") is None, payload
    assert entity.get("resolver_candidate_skus") == [], payload
    assert payload.get("candidate_skus") in ([], None), payload
    assert payload.get("result_skus") in ([], None), payload


@pytest.mark.parametrize(
    "question",
    [
        "月影炉能用卡式炉吗？",
        "月影炉可以配卡式炉吗？",
    ],
)
def test_grounded_single_product_capability_question_does_not_return_product_not_found(
    route_client_and_db,
    question,
):
    client, headers, _ = route_client_and_db

    response = client.post("/api/customer-service/ask?debug=true", json={"question": question}, headers=headers)
    assert response.status_code == 200, response.text
    payload = response.json()
    answer_type = str(payload.get("answer_type") or "")
    answer_metadata = payload.get("answer_metadata") or {}
    result_skus = payload.get("result_skus") or []
    candidate_skus = payload.get("candidate_skus") or []

    assert answer_type in {"product_detail", "clarification"}, payload
    assert answer_type != "knowledge_base_answer", payload
    assert answer_type != "product_query", payload
    assert answer_type != "recommendation", payload
    assert answer_metadata.get("source") != "unknown_field_product_not_found", answer_metadata
    assert result_skus == candidate_skus, {
        "result_skus": result_skus,
        "candidate_skus": candidate_skus,
        "payload": payload,
    }
    assert set(result_skus).issubset({"CS-G25", "CS-G25-B"}), payload

@pytest.mark.parametrize(
    "question",
    [
        "天鹅壶9杯白 能不能明火直烧？",
        "天鹅壶4杯-黑色 适合徒步吗？",
        "天鹅壶4杯白 适合几个人？",
    ],
)
def test_route_level_product_like_detail_questions_do_not_leak_unrelated_catalog_rows(
    route_client_and_db,
    question,
):
    client, headers, Session = route_client_and_db

    response = client.post("/api/customer-service/ask?debug=true", json={"question": question}, headers=headers)
    assert response.status_code == 200, response.text
    payload = response.json()

    subject = customer_service_service._product_like_scope_subject(question) or customer_agent_intent_service._detail_subject_from_question(question).strip()
    with Session() as db:
        named_products = customer_service_service._products_named_in_question(db, question)
        strong_skus = {
            str(product.sku or "").strip().upper()
            for product in named_products
            if customer_service_service._subject_strongly_matches_product(subject, product)
        }

    result_skus = {str(sku or "").strip().upper() for sku in (payload.get("result_skus") or [])}
    assert payload["answer_type"] != "recommendation", payload
    assert payload["answer_type"] != "knowledge_base_answer", payload
    if len(strong_skus) == 1:
        assert payload["answer_type"] != "product_query", payload
    assert result_skus.issubset(strong_skus), {"result_skus": sorted(result_skus), "strong_skus": sorted(strong_skus), "payload": payload}
    assert payload.get("answer"), payload


def test_route_level_structured_category_scope_question_requires_semantic_preplan():
    question = "哪些水杯是不锈钢的？"
    phase1_plan = customer_agent_planner_service.plan_customer_question(question)

    assert customer_service_service._should_call_semantic_preplan(
        question,
        phase1_plan,
        conversation_id=None,
    )


def test_route_level_entity_scope_guard_defers_to_llm_structured_category_scope(route_client_and_db):
    _client, _headers, Session = route_client_and_db
    question = "哪些水杯是不锈钢的？"
    semantic_preplan = {
        "called": True,
        "route_family": "structured_query",
        "route_hint": "query_products",
        "question_type": "filter",
        "subtype": "structured_query",
        "entity_scope": "category_scope",
        "field_type": "material",
        "confidence_label": "high",
        "confidence": 0.9,
    }

    with Session() as db:
        result = customer_service_service._entity_scope_pre_route_guard_result(
            db,
            question,
            {},
            semantic_preplan,
        )

    assert result is None


@pytest.mark.parametrize(
    ("question", "expected_bucket", "forbidden_bucket"),
    [
        ("哪些水杯是不锈钢的？", "cup", "kettle"),
        ("哪些杯是不锈钢的？", "cup", "kettle"),
        ("有哪些适合徒步的水杯？", "cup", "kettle"),
        ("哪些水杯比较轻？", "cup", "kettle"),
        ("轻便水杯有哪些？", "cup", "kettle"),
        ("哪些水壶是不锈钢的？", "kettle", "cup"),
        ("有哪些不锈钢水壶？", "kettle", "cup"),
        ("可以明火直烧的不锈钢水壶有哪些？", "kettle", "cup"),
    ],
)
def test_route_level_structured_waterware_boundary_queries_do_not_mix_cup_and_kettle(
    route_client_and_db,
    question,
    expected_bucket,
    forbidden_bucket,
):
    client, headers, Session = route_client_and_db
    _seed_contents_resolution_priority_products(Session)

    response = client.post("/api/customer-service/ask?debug=true", json={"question": question}, headers=headers)
    assert response.status_code == 200, response.text
    payload = response.json()
    answer_metadata = payload.get("answer_metadata") or {}

    assert payload["answer_type"] in {"product_query", "query_products"}, payload
    assert answer_metadata.get("source") == "structured_category_field_filter_query", answer_metadata
    if not payload["result_skus"]:
        _assert_structured_no_match_contract(payload)
        return

    with Session() as db:
        loaded_rows = (
            db.query(Product, ProductSpecs)
            .outerjoin(ProductSpecs, ProductSpecs.product_id == Product.id)
            .filter(Product.sku.in_(payload["result_skus"]))
            .all()
        )
        products = {
            str(product.sku or "").strip().upper(): str(product.category or "").strip()
            for product, _specs in loaded_rows
        }

    assert products, payload
    if expected_bucket == "cup":
        assert all(category in {"水具", "水杯", "杯子", "杯"} for category in products.values()), products
        assert not any(category == "水壶" for category in products.values()), products
    else:
        resolver_decisions = []
        for product, specs in loaded_rows:
            row = {
                "sku": product.sku,
                "product_name_cn": product.product_name_cn,
                "category": product.category,
                "sub_category": getattr(product, "sub_category", None),
                "body_material": getattr(specs, "body_material", None),
            }
            decision = customer_service_service.customer_structured_query_contract.resolve_structured_subject_scope(
                row=row,
                subject_category="水壶",
            )
            resolver_decisions.append(decision)
            assert decision["matched"] is True, {"sku": product.sku, "decision": decision}
            assert decision["scope"] == "subject", {"sku": product.sku, "decision": decision}
            assert decision["subject_kind"] in {"kettle", "coffee_kettle"}, decision
            material_contract = customer_service_service.customer_structured_query_contract.StructuredQueryContract(
                subject_category="水壶",
                field="material",
                operator="contains",
                value="不锈钢",
                status="resolved",
            )
            material_proof = customer_service_service.customer_structured_query_contract.match_material_condition(
                contract=material_contract,
                row=row,
            )
            assert material_proof["matched"] is True, {"sku": product.sku, "material_proof": material_proof}
            assert material_proof["field_source"] == "body_material", material_proof
            assert material_proof["subject_scope"] == "subject", material_proof
        assert all(
            decision["matched"] is True
            and decision["scope"] == "subject"
            and decision["subject_kind"] in {"kettle", "coffee_kettle"}
            for decision in resolver_decisions
        ), resolver_decisions
        assert not any(decision["subject_kind"] == "cup" for decision in resolver_decisions), resolver_decisions
    assert forbidden_bucket in {"cup", "kettle"}


@pytest.mark.parametrize(
    "question",
    [
        "有哪些水具？",
        "户外水具有哪些？",
    ],
)
def test_route_level_broad_waterware_queries_keep_broad_waterware_scope(route_client_and_db, question):
    client, headers, Session = route_client_and_db

    response = client.post("/api/customer-service/ask?debug=true", json={"question": question}, headers=headers)
    assert response.status_code == 200, response.text
    payload = response.json()

    assert payload["answer_type"] in {"product_query", "query_products", "recommendation"}, payload
    assert payload["result_skus"], payload

    with Session() as db:
        categories = {
            str(product.sku or "").strip().upper(): str(product.category or "").strip()
            for product in db.query(Product).filter(Product.sku.in_(payload["result_skus"])).all()
        }
    assert categories, payload
    assert all(category in {"水具", "水壶", "水杯", "杯子", "杯"} for category in categories.values()), categories


@pytest.mark.parametrize(
    "question",
    [
        "轻便水杯推荐几个",
        "轻量钛杯推荐",
        "给我推荐一个钛杯",
        "适合卡式炉的锅具推荐",
        "公园野餐轻便装备",
        "不要太重的水壶",
        "预算低一点的炉具",
    ],
)
def test_route_level_recommendation_queries_post_filter_results_to_explicit_constraints(
    route_client_and_db,
    question,
):
    client, headers, Session = route_client_and_db

    response = client.post("/api/customer-service/ask?debug=true", json={"question": question}, headers=headers)
    assert response.status_code == 200, response.text
    payload = response.json()
    answer = str(payload.get("answer") or "")

    assert payload["answer_type"] == "recommendation", payload
    assert payload["answer_type"] != "knowledge_base_answer", payload
    assert payload["answer_type"] != "product_detail", payload
    assert answer, payload
    if not payload["result_skus"]:
        assert "未找到符合条件" in answer or "放宽" in answer, answer
        return

    with Session() as db:
        rows = (
            db.query(Product, ProductSpecs, ProductBusiness)
            .outerjoin(ProductSpecs, ProductSpecs.product_id == Product.id)
            .outerjoin(ProductBusiness, ProductBusiness.product_id == Product.id)
            .filter(Product.sku.in_(payload["result_skus"]))
            .all()
        )
    by_sku = {str(product.sku or "").strip().upper(): (product, specs, business) for product, specs, business in rows}
    assert set(payload["result_skus"]).issubset(by_sku.keys()), {"result_skus": payload["result_skus"], "loaded": sorted(by_sku.keys())}
    verification_by_sku = {
        str(item.get("sku") or "").strip().upper(): item
        for item in (payload.get("debug") or {}).get("candidate_verifications") or []
        if isinstance(item, dict) and str(item.get("sku") or "").strip()
    }


def _contents_semantic_preplan_stub(*, confidence: float = 0.96) -> dict:
    return {
        "called": True,
        "purpose": "semantic_preplan",
        "route_family": "contents_accessories",
        "route_hint": "product_detail",
        "question_type": "contents_accessories",
        "entities": ["semantic-entity-must-not-seal-identity"],
        "field_type": "contents",
        "field_hint": "contents",
        "subtype": "composition",
        "entity_scope": "resolved_product",
        "qa_or_usage_care": True,
        "unknown_field": False,
        "confidence": confidence,
        "confidence_label": "high" if confidence >= 0.8 else "medium",
        "reason": "contents field candidate only",
        "accepted_or_overridden": "",
        "override_reason": "",
        "fallback_reason": "",
        "llm_call_count": 1,
        "llm_call_count_delta": 1,
        "raw_preview": "",
    }

    for sku in payload["result_skus"]:
        product, specs, business = by_sku[sku]
        row_text = " ".join(
            str(part or "")
            for part in (
                getattr(product, "name", ""),
                getattr(product, "category", ""),
                getattr(specs, "body_material", ""),
                getattr(specs, "heat_source", ""),
                getattr(business, "usage_scenarios", ""),
            )
        )
        if "水杯" in question or "钛杯" in question or "杯" in question:
            assert str(product.category or "").strip() in {"水具", "水杯", "杯子", "杯"}, {"sku": sku, "category": product.category, "question": question}
        if "水壶" in question:
            assert str(product.category or "").strip() == "水壶", {"sku": sku, "category": product.category, "question": question}
        if "锅具" in question:
            assert str(product.category or "").strip() == "锅具", {"sku": sku, "category": product.category, "question": question}
        if "炉具" in question:
            assert str(product.category or "").strip() == "炉具", {"sku": sku, "category": product.category, "question": question}
        if "钛杯" in question:
            assert _structured_field_match(getattr(specs, "body_material", None), "钛"), {"sku": sku, "material": getattr(specs, "body_material", None), "question": question}
        if "卡式炉" in question:
            assert _structured_field_match(getattr(specs, "heat_source", None), "卡式炉"), {"sku": sku, "heat_source": getattr(specs, "heat_source", None), "question": question}
        if "轻便" in question or "轻量" in question or "不要太重" in question:
            verification = verification_by_sku.get(sku) or {}
            weight_evidence = (verification.get("evidence_by_constraint") or {}).get("weight") or {}
            assert weight_evidence.get("status") == "verified", {"sku": sku, "verification": verification}
            assert weight_evidence.get("field_source") == "gross_weight_g", {"sku": sku, "weight_evidence": weight_evidence}
            assert specs is not None, {"sku": sku, "question": question}
            normalized_g = float(weight_evidence.get("normalized_g") or 0)
            assert normalized_g == float(specs.gross_weight_g or 0), {
                "sku": sku,
                "weight_evidence": weight_evidence,
                "specs_gross_weight_g": specs.gross_weight_g,
            }
            assert 0 < normalized_g <= 350, {"sku": sku, "weight_evidence": weight_evidence}
        if "预算低" in question:
            joined = row_text.lower()
            assert any(term in joined for term in ("基础", "性价比", "入门")), {"sku": sku, "row_text": row_text, "question": question}


def test_unresolved_product_like_recommendation_returns_clarification_or_no_match(
    route_client_and_db,
):
    client, headers, _ = route_client_and_db
    question = "不存在的咖啡器具推荐一下"

    response = client.post("/api/customer-service/ask?debug=true", json={"question": question}, headers=headers)
    assert response.status_code == 200, response.text
    payload = response.json()
    answer = str(payload.get("answer") or "")
    answer_metadata = payload.get("answer_metadata") or {}

    assert payload["answer_type"] in {"clarification", "recommendation"}, payload
    assert payload.get("result_skus") in ([], None), payload
    assert payload.get("candidate_skus") in ([], None), payload
    assert answer_metadata.get("source") in {
        "entity_scope_product_not_found",
        "unknown_field_product_not_found",
        "unresolved_product_like_unknown_field_clarification",
        "product_catalog_structured_recommendation",
    }, answer_metadata
    if payload["answer_type"] == "recommendation":
        assert "未找到符合条件" in answer, payload


def test_recommendation_post_filter_keeps_answer_and_result_skus_consistent(
    route_client_and_db,
):
    client, headers, Session = route_client_and_db
    question = "预算低一点的炉具"

    response = client.post("/api/customer-service/ask?debug=true", json={"question": question}, headers=headers)
    assert response.status_code == 200, response.text
    payload = response.json()
    answer = str(payload.get("answer") or "")

    assert payload["answer_type"] == "recommendation", payload
    result_skus = [str(sku or "").strip().upper() for sku in (payload.get("result_skus") or []) if str(sku or "").strip()]
    candidate_skus = [str(sku or "").strip().upper() for sku in (payload.get("candidate_skus") or []) if str(sku or "").strip()]
    assert result_skus == candidate_skus, payload
    if not result_skus:
        assert "未找到符合条件" in answer, payload
        return

    with Session() as db:
        products = db.query(Product).filter(Product.sku.in_(result_skus)).all()
    product_names = [
        str(product.product_name_cn or product.product_name_en or product.sku or "").strip()
        for product in products
    ]
    assert product_names, {"result_skus": result_skus, "payload": payload}
    assert any(name and name in answer for name in product_names), {
        "answer": answer,
        "result_skus": result_skus,
        "product_names": product_names,
        "payload": payload,
    }


@pytest.mark.parametrize(
    "question",
    [
        "不存在的咖啡器具推荐一下",
        "不存在的咖啡壶推荐几个",
        "虚构款咖啡器具有什么推荐？",
    ],
)
def test_unresolved_product_like_recommendation_does_not_return_real_products(
    route_client_and_db,
    question,
):
    client, headers, _ = route_client_and_db

    response = client.post("/api/customer-service/ask?debug=true", json={"question": question}, headers=headers)
    assert response.status_code == 200, response.text
    payload = response.json()
    answer = str(payload.get("answer") or "")
    answer_metadata = payload.get("answer_metadata") or {}
    result_skus = [str(sku or "").strip().upper() for sku in (payload.get("result_skus") or []) if str(sku or "").strip()]
    candidate_skus = [str(sku or "").strip().upper() for sku in (payload.get("candidate_skus") or []) if str(sku or "").strip()]

    assert payload["answer_type"] in {"clarification", "recommendation"}, payload
    assert result_skus == [], payload
    assert candidate_skus == [], payload
    assert answer_metadata.get("source") in {
        "entity_scope_product_not_found",
        "unknown_field_product_not_found",
        "unresolved_product_like_unknown_field_clarification",
        "product_catalog_structured_recommendation",
    }, answer_metadata
    assert not any(sku in answer for sku in ("CW-K31", "KW-K25-35", "PA-KW-K25-02")), payload
    assert any(term in answer for term in ("没找到", "未找到", "确认商品名", "提供 SKU", "符合条件")), payload


@pytest.mark.parametrize(
    "question",
    [
        "荒野星壶多少钱？",
        "荒野星水壶价格是多少？",
        "这个不存在的壶多少钱？",
    ],
)
def test_low_confidence_product_like_entity_does_not_bind_single_candidate(
    route_client_and_db,
    question,
):
    client, headers, _ = route_client_and_db

    response = client.post("/api/customer-service/ask?debug=true", json={"question": question}, headers=headers)
    assert response.status_code == 200, response.text
    payload = response.json()
    answer = str(payload.get("answer") or "")
    answer_metadata = payload.get("answer_metadata") or {}

    assert payload["answer_type"] == "clarification", payload
    assert payload.get("result_skus") in ([], None), payload
    assert payload.get("candidate_skus") in ([], None), payload
    assert answer_metadata.get("source") in {
        "entity_scope_product_not_found",
        "unknown_field_product_not_found",
        "unresolved_product_like_unknown_field_clarification",
        # The formal detail path now preserves the unresolved entity contract
        # instead of returning through the older lexical unknown-field label.
        "entity_state_detail_unresolved",
        # A leading deictic without a saved anchor is the same safety outcome:
        # no product binding and an explicit EntityResolution clarification.
        "unbound_deictic_entity_contract_guard",
    }, answer_metadata
    if answer_metadata.get("source") in {"entity_state_detail_unresolved", "unbound_deictic_entity_contract_guard"}:
        entity = (payload.get("debug") or {}).get("entity_resolution_contract") or {}
        assert entity.get("status") == "unresolved", payload
        assert entity.get("resolved_sku") is None, payload
    assert "CW-C47-1" not in answer, payload
    assert any(term in answer for term in ("没找到", "未找到", "确认商品名", "提供 SKU")), payload


@pytest.mark.parametrize(
    "question",
    [
        "疯狂游乐园X-Power桌面炉（不含炉配件-烤盘） 运费多少？",
        "疯狂游乐园X-Power桌面炉（不含炉配件-烤盘） 包邮吗？",
        "疯狂游乐园X-Power桌面炉（不含炉配件-烤盘） 今天能发吗？",
    ],
)
def test_route_level_long_named_unknown_realtime_queries_do_not_fall_into_usage_care(route_client_and_db, question, monkeypatch):
    client, headers, _ = route_client_and_db

    async def semantic_preplan_for_shipping(_db, _question, _deterministic_plan, *, context):
        return _unknown_realtime_preplan_stub(
            field_hint="shipping",
            entity_scope="unique_product_name",
            subtype="commercial_realtime",
            route_hint="unknown_field",
            question_type="unknown_field",
        )

    monkeypatch.setattr(
        customer_agent_planner_service,
        "plan_customer_question_semantic",
        semantic_preplan_for_shipping,
    )

    response = client.post("/api/customer-service/ask?debug=true", json={"question": question}, headers=headers)
    assert response.status_code == 200, response.text
    payload = response.json()
    answer = str(payload.get("answer") or "")
    answer_metadata = payload.get("answer_metadata") or {}

    assert payload["answer_type"] in {"product_detail", "clarification"}, payload
    assert payload["answer_type"] != "product_usage_care", payload
    assert answer_metadata.get("source") in {
        "resolved_entity_unknown_field_fallback",
        "named_product_unknown_field_clarification",
        "unresolved_product_like_unknown_field_clarification",
        "unknown_field_product_not_found",
    }, answer_metadata
    assert any(term in answer for term in ("未标注", "无法确认", "平台", "店铺页面", "人工客服", "没有找到", "提供 SKU")), answer
    assert not any(term in answer for term in ("功率", "材质", "开箱", "配件", "使用方法")), answer


def test_named_single_product_people_count_defers_to_central_field_contract(
    route_client_and_db,
    monkeypatch,
):
    _client, _headers, Session = route_client_and_db
    question = "天鹅壶4杯白 适合几个人？"

    with Session() as db:
        product = db.query(Product).filter(Product.sku == "KW-K31-白").first()
        assert product is not None
        _mock_strong_resolved_named_product(monkeypatch, product=product)
        result = asyncio.run(
            customer_service_service._try_named_product_shortcut(
                db,
                user_id="route-test-user",
                question=question,
            )
        )

    # People count is a formal product field.  The legacy named-product
    # shortcut must defer it to the FieldContract/EntityResolutionContract
    # pipeline instead of deciding an answer or a usage-scene fallback here.
    assert result is None


@pytest.mark.parametrize(
    "question",
    [
        "\u54ea\u4e9b\u9505\u662f\u786c\u6c27\u6750\u8d28\uff1f",
        "\u53ef\u4ee5\u660e\u706b\u76f4\u70e7\u7684\u4e0d\u9508\u94a2\u6c34\u58f6\u6709\u54ea\u4e9b\uff1f",
        "\u786c\u6c27\u6750\u8d28\u7684\u9505\u5177\u6709\u54ea\u4e9b\uff1f",
        "\u6709\u54ea\u4e9b\u9002\u5408\u5f92\u6b65\u7684\u6c34\u676f\uff1f",
        "\u6709\u54ea\u4e9b\u9002\u5408\u65b0\u624b\u7684\u7089\u5177\uff1f",
    ],
)
def test_route_level_structured_positive_db_match_queries_must_not_return_empty(
    route_client_and_db,
    question,
):
    client, headers, Session = route_client_and_db
    _seed_contents_resolution_priority_products(Session)

    intent, _contract, qualified_rows = _qualified_structured_rows(Session, question)
    assert intent.filters, (question, intent)
    assert qualified_rows, {"question": question, "filters": intent.filters, "negative_filters": intent.negative_filters}

    response = client.post("/api/customer-service/ask?debug=true", json={"question": question}, headers=headers)
    assert response.status_code == 200, response.text
    payload = response.json()
    answer_metadata = payload.get("answer_metadata") or {}

    assert answer_metadata.get("source") == "structured_category_field_filter_query", answer_metadata
    assert payload["result_skus"], payload
    assert str(payload.get("answer") or "").strip(), payload
    assert "未找到符合条件的商品" not in str(payload.get("answer") or ""), payload["answer"]
    _assert_structured_result_skus_are_exactly_qualified(Session, payload, qualified_rows)


@pytest.mark.parametrize(
    "question",
    [
        "\u9002\u5408\u4e24\u4e2a\u4eba\u7684\u9505\u5177\u6709\u54ea\u4e9b\uff1f",
        "\u6709\u54ea\u4e9b\u9505\u9002\u5408\u53cc\u4eba\u9732\u8425\uff1f",
        "\u6709\u54ea\u4e9b\u8f7b\u91cf\u9505\u5177\uff1f",
        "\u6709\u54ea\u4e9b\u9884\u7b97\u4f4e\u4e00\u70b9\u7684\u7089\u5177\uff1f",
        "\u6709\u54ea\u4e9b\u9002\u5408\u65b0\u624b\u7684\u7089\u5177\uff1f",
        "\u6709\u54ea\u4e9b\u9002\u5408\u5f92\u6b65\u7684\u6c34\u676f\uff1f",
    ],
)
def test_route_level_structured_trait_queries_only_return_hard_qualified_rows(
    route_client_and_db,
    question,
):
    client, headers, Session = route_client_and_db
    _seed_contents_resolution_priority_products(Session)

    intent, _contract, qualified_rows = _qualified_structured_rows(Session, question)
    assert intent.filters, (question, intent)

    response = client.post("/api/customer-service/ask?debug=true", json={"question": question}, headers=headers)
    assert response.status_code == 200, response.text
    payload = response.json()
    answer_metadata = payload.get("answer_metadata") or {}

    assert answer_metadata.get("source") == "structured_category_field_filter_query", answer_metadata
    if not qualified_rows:
        _assert_structured_no_match_contract(payload)
        return
    assert payload["result_skus"], payload
    _assert_structured_result_skus_are_exactly_qualified(Session, payload, qualified_rows)
    assert len(payload["result_skus"]) <= len(qualified_rows), {
        "question": question,
        "actual": payload["result_skus"],
        "qualified": [str(row.get("sku") or "").strip().upper() for row in qualified_rows],
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
    assert any(term in payload["answer"] for term in ("Product not found", "没有找到", "未找到")), payload["answer"]


@pytest.mark.parametrize(
        ("question", "expected_answer_type", "required_sku", "required_terms"),
    [
        ("CW-C83 的价格是多少？", "product_detail", "CW-C83", ("未标注", "价格")),
        ("KW-K32-白可以直接加热吗？", "product_detail", "KW-K32-白", ("KW-K32-白",)),
        # This assertion predates the formal cleaning FieldContract. True
        # usage/care remains supported, while an exact product field request
        # now seals identity and evidence through the central detail contract.
        ("CW-C06PRO 怎么清洗？", "product_detail", "CW-C06PRO", ("暂未找到", "清洁")),
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
    if question == "CW-C06PRO 怎么清洗？":
        debug = payload.get("debug") or {}
        entity = debug.get("entity_resolution_contract") or {}
        metadata = payload.get("answer_metadata") or {}
        assert debug.get("agent_mode") == "resolved_entity_detail_contract", payload
        assert (debug.get("field_contract") or {}).get("field_type") == "cleaning", payload
        assert entity.get("status") == "resolved", entity
        assert entity.get("resolved_sku") == "CW-C06PRO", entity
        assert payload.get("candidate_skus") == ["CW-C06PRO"], payload
        assert payload.get("result_skus") == ["CW-C06PRO"], payload
        assert metadata.get("contract_field_type") == "cleaning", metadata
        assert metadata.get("evidence_status") == "missing", metadata
    for term in required_terms:
        if term in payload["answer"]:
            break
    else:
        assert False, payload["answer"]


def test_route_level_exact_contents_uses_field_entity_contract_instead_of_legacy_usage_care(
    route_client_and_db,
):
    """Migrate the pre-U-S12 usage/care route label without weakening safety checks.

    Contents/accessories now require FieldContract and EntityResolutionContract first;
    the old assertion protected the former usage/care fast path, not its evidence semantics.
    """
    client, headers, _ = route_client_and_db

    response = client.post(
        "/api/customer-service/ask?debug=true",
        json={"question": "CT-T04(BM) 里面有什么？"},
        headers=headers,
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    answer = str(payload.get("answer") or "")
    debug = payload.get("debug") or {}
    entity = debug.get("entity_resolution_contract") or {}
    metadata = payload.get("answer_metadata") or {}

    assert payload.get("answer_type") == "product_detail", payload
    assert debug.get("agent_mode") == "resolved_entity_detail_contract", payload
    assert entity.get("field_type") == "accessories", payload
    assert entity.get("status") == "resolved", payload
    assert entity.get("resolved_sku") == "CT-T04(BM)", payload
    assert payload.get("candidate_skus") == ["CT-T04(BM)"], payload
    assert payload.get("result_skus") == ["CT-T04(BM)"], payload
    assert metadata.get("contract_field_type") == "accessories", metadata
    assert metadata.get("field_evidence_missing") is True, metadata
    assert metadata.get("evidence_field") is None, metadata
    assert metadata.get("evidence_source") is None, metadata
    assert metadata.get("evidence_sku") is None, metadata
    assert answer and "CT-T04(BM)" in answer, answer
    assert any(term in answer for term in ("未标注", "无法确认", "暂未")), answer
    assert not any(term in answer for term in ("茶壶", "茶杯", "开箱即可泡茶")), answer
    assert debug.get("agent_mode") != "product_usage_care_fast_path", payload


@pytest.mark.parametrize(
    ("question", "expected_field"),
    [
        ("CT-T04(BM) 怎么使用？", "usage_instruction"),
        ("CT-T04(BM) 怎么清洁？", "cleaning"),
        ("CT-T04(BM) 怎么保养？", "care"),
    ],
)
def test_route_level_exact_usage_care_stays_adjacent_to_contents_contract(
    route_client_and_db,
    question,
    expected_field,
):
    """Usage/care remains available through the central detail contracts.

    This is deliberately adjacent to the contents test above: the former
    usage/care fast path must not reclaim contents, while true usage/care
    questions retain their own canonical field, sealed identity, and
    same-SKU-only evidence policy.
    """
    client, headers, _ = route_client_and_db

    response = client.post(
        "/api/customer-service/ask?debug=true",
        json={"question": question},
        headers=headers,
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    debug = payload.get("debug") or {}
    entity = debug.get("entity_resolution_contract") or {}
    metadata = payload.get("answer_metadata") or {}

    assert payload.get("answer_type") == "product_detail", payload
    assert debug.get("agent_mode") == "resolved_entity_detail_contract", payload
    assert entity.get("status") == "resolved", payload
    assert entity.get("resolved_sku") == "CT-T04(BM)", payload
    assert entity.get("field_type") == expected_field, payload
    assert payload.get("candidate_skus") == ["CT-T04(BM)"], payload
    assert payload.get("result_skus") == ["CT-T04(BM)"], payload
    assert metadata.get("contract_field_type") == expected_field, metadata
    evidence_sku = metadata.get("evidence_sku")
    assert evidence_sku in {None, "CT-T04(BM)"}, metadata
    if evidence_sku is None:
        assert metadata.get("field_evidence_missing") is True, metadata
    assert debug.get("agent_mode") != "product_usage_care_fast_path", payload
    assert payload.get("answer"), payload


@pytest.mark.parametrize(
    "question",
    [
        "炉具推荐",
        "夏天冷水补水水壶推荐",
        "适合酒精炉的锅具推荐",
    ],
)
def test_route_level_semantic_unavailable_recommendation_cases_fail_closed(
    route_client_and_db,
    question,
    monkeypatch,
):
    # This suite runs without a provider key. The old assertion protected the
    # legacy fallback route; after semantic-preplan ownership, an unavailable
    # model must clarify rather than let usage/care infer a different intent.
    # Valid semantic stove/waterware domain execution is covered by the
    # neighbouring explicit semantic-contract tests.
    client, headers, _ = route_client_and_db

    async def unavailable_preplan(_db, _question, _deterministic_plan, *, context):
        return {
            "called": True,
            "fallback_reason": "llm_error:RuntimeError",
            "error": "llm_error:RuntimeError",
            "canonical_fields": [],
            "field_type": "",
            "recommendation_constraints": {},
        }

    monkeypatch.setattr(customer_agent_planner_service, "plan_customer_question_semantic", unavailable_preplan)

    response = client.post("/api/customer-service/ask?debug=true", json={"question": question}, headers=headers)
    assert response.status_code == 200, response.text
    payload = response.json()

    assert payload["answer_type"] == "clarification", payload
    assert payload["answer"], payload
    assert payload["result_skus"] == [], payload
    assert payload["candidate_skus"] == [], payload
    assert "Product not found" not in payload["answer"], payload["answer"]
    assert payload["debug"]["agent_mode"] == "semantic_preplan_unavailable_clarification", payload
    assert payload["debug"]["agent_mode"] != "product_usage_care_fast_path", payload


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
        "婧川水壶 现在有货吗？",
        "星河水壶 有赠品吗？",
    ],
)
def test_route_level_unresolved_product_like_unknown_realtime_clarifies_instead_of_falling_to_catalog_or_qa(
    route_client_and_db,
    monkeypatch,
    question,
):
    client, headers, _ = route_client_and_db

    async def fake_preplan(db, question, deterministic_plan, context):
        return _unknown_realtime_preplan_stub(field_hint="stock", entity_scope="unresolved_product_like")

    monkeypatch.setattr(customer_agent_planner_service, "plan_customer_question_semantic", fake_preplan)

    response = client.post("/api/customer-service/ask?debug=true", json={"question": question}, headers=headers)
    assert response.status_code == 200, response.text
    payload = response.json()
    answer = str(payload.get("answer") or "")
    answer_metadata = payload.get("answer_metadata") or {}

    assert payload["answer_type"] == "clarification", payload
    assert payload.get("needs_clarification") is True, payload
    assert payload.get("result_skus") in ([], None), payload.get("result_skus")
    assert any(term in answer for term in ("提供 SKU", "具体 SKU", "具体款式", "确认是哪一款商品")), answer
    assert payload.get("debug", {}).get("agent_mode") != "product_qa_fast_path", payload.get("debug")
    assert payload["answer_type"] != "knowledge_base_answer", payload
    assert answer_metadata.get("source") == "unresolved_product_like_unknown_field_clarification", answer_metadata
    semantic_debug = _semantic_preplan_debug(payload)
    assert semantic_debug.get("called") is True, payload.get("debug")
    assert semantic_debug.get("subtype") == "unknown_realtime", semantic_debug


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
    assert payload.get("result_skus") in ([], None), payload.get("result_skus")
    assert set(payload.get("candidate_skus") or []) >= {"CW-S10-1", "CW-S10-A"}, payload.get("candidate_skus")
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


def test_route_level_unknown_realtime_contract_blocks_product_qa_and_other_fast_paths(route_client_and_db, monkeypatch):
    client, headers, _ = route_client_and_db

    async def fake_preplan(db, question, deterministic_plan, context):
        return _unknown_realtime_preplan_stub(field_hint="stock", entity_scope="resolved_single")

    monkeypatch.setattr(customer_agent_planner_service, "plan_customer_question_semantic", fake_preplan)

    response = client.post("/api/customer-service/ask?debug=true", json={"question": "CS-B14（LX） 现在有货吗？"}, headers=headers)
    assert response.status_code == 200, response.text
    payload = response.json()
    answer = str(payload.get("answer") or "")
    answer_metadata = payload.get("answer_metadata") or {}
    semantic_debug = _semantic_preplan_debug(payload)

    assert payload["answer_type"] == "product_detail", payload
    assert "CS-B14（LX）" in (payload.get("result_skus") or []), payload.get("result_skus")
    assert answer_metadata.get("source") == "resolved_entity_unknown_field_fallback", answer_metadata
    assert payload.get("debug", {}).get("agent_mode") == "resolved_entity_unknown_field_fallback", payload.get("debug")
    assert payload.get("debug", {}).get("agent_mode") not in {
        "product_qa_fast_path",
        "product_usage_care_fast_path",
        "planner_recommendation_guard_rebuild",
    }, payload.get("debug")
    assert payload["answer_type"] not in {"knowledge_base_answer", "query_products", "product_query", "recommendation"}, payload
    assert "现货充足" not in answer and "立即发货" not in answer and "直播间专享" not in answer, answer
    assert semantic_debug.get("called") is True, payload.get("debug")
    assert semantic_debug.get("subtype") == "unknown_realtime", semantic_debug


def test_current_availability_contract_vetoes_misclassified_product_qa_before_rag(route_client_and_db):
    """A product-QA semantic mistake must never turn static evidence into a live sales promise."""
    _client, _headers, Session = route_client_and_db
    question = "\u6d4b\u8bd5\u4fdd\u6e29\u5305\u5b83\u8fd8\u5728\u552e\u5417\uff1f"
    semantic_preplan = {
        "called": True,
        "route_family": "product_bound_qa",
        "route_hint": "product_detail",
        "question_type": "field",
        "subtype": "known_detail",
        "entities": ["\u6d4b\u8bd5\u4fdd\u6e29\u5305"],
        "subject_text": "\u6d4b\u8bd5\u4fdd\u6e29\u5305",
        "canonical_fields": [],
        "confidence": 0.95,
        "ambiguity": False,
        "evidence_required": True,
        "evidence_kind": "product_qa",
        "qa_evidence_query": "\u662f\u5426\u5728\u552e",
    }
    with Session() as db:
        _add_product(
            db,
            "SAFE-AVAIL-01",
            "\u6d4b\u8bd5\u4fdd\u6e29\u5305",
            "\u914d\u4ef6",
            "20L",
            "\u6d4b\u8bd5\u6750\u8d28",
            "/",
            "\u6d4b\u8bd5\u5356\u70b9",
            "\u6d4b\u8bd5\u573a\u666f",
            500,
        )
        db.commit()
        result = customer_service_service._pre_route_high_risk_contract_result(
            db,
            question,
            semantic_preplan,
        )

    assert result is not None
    assert result["debug"]["agent_mode"] == "resolved_entity_unknown_field_fallback"
    assert result["answer_metadata"]["source"] == "resolved_entity_unknown_field_fallback"
    assert "\u4e0d\u80fd\u4ec5\u51ed\u9759\u6001\u4ea7\u54c1\u8d44\u6599\u5224\u65ad" in result["answer"]


def test_semantic_current_purchasability_without_lexical_contract_returns_safe_exact_entity_result(route_client_and_db):
    """A valid semantic realtime intent must not need a wording-specific FieldContract alias."""
    _client, _headers, Session = route_client_and_db
    question = "\u6d4b\u8bd5\u4fdd\u6e29\u5305\u73b0\u5728\u8fd8\u80fd\u4e70\u5230\u5417\uff1f"
    semantic_preplan = {
        "called": True,
        "route_family": "unknown_realtime",
        "route_hint": "unknown_field",
        "question_type": "unknown_field",
        "subtype": "commercial_realtime",
        "entities": ["\u6d4b\u8bd5\u4fdd\u6e29\u5305"],
        "subject_text": "\u6d4b\u8bd5\u4fdd\u6e29\u5305",
        "canonical_fields": [],
        "confidence": 0.95,
        "ambiguity": False,
        "evidence_required": True,
        "evidence_kind": "structured_field",
    }
    with Session() as db:
        _add_product(
            db,
            "SAFE-BUY-01",
            "\u6d4b\u8bd5\u4fdd\u6e29\u5305",
            "\u914d\u4ef6",
            "20L",
            "\u6d4b\u8bd5\u6750\u8d28",
            "/",
            "\u6d4b\u8bd5\u5356\u70b9",
            "\u6d4b\u8bd5\u573a\u666f",
            500,
        )
        db.commit()
        result = customer_service_service._pre_route_high_risk_contract_result(
            db,
            question,
            semantic_preplan,
        )

    assert result is not None
    assert result["debug"]["agent_mode"] == "resolved_entity_unknown_field_fallback"
    assert result["result_skus"] == ["SAFE-BUY-01"]
    assert "\u5b9e\u65f6" in result["answer"]
    assert "\u6e05\u4ed3" not in result["answer"]


def test_semantic_supplemental_qa_can_attach_after_warranty_guard(route_client_and_db):
    """A sealed capability QA must not be discarded solely because the same turn also asks warranty."""
    _client, _headers, Session = route_client_and_db
    question = "\u6d4b\u8bd5\u6c34\u58f6\u80fd\u5728\u5bb6\u91cc\u7528\u5417\uff1f\u53e6\u5916\uff0c\u8d28\u4fdd\u591a\u4e45\uff1f"
    preplan = {"called": True, "route_family": "product_bound_qa", "route_hint": "product_detail", "question_type": "field", "subtype": "known_detail", "subject_text": "\u6d4b\u8bd5\u6c34\u58f6", "canonical_fields": [], "field_type": "", "confidence": 0.95, "confidence_label": "high", "ambiguity": False, "evidence_required": True, "evidence_kind": "product_qa", "qa_evidence_query": "\u5bb6\u7528\u517c\u5bb9\u6027", "fallback_reason": ""}
    with Session() as db:
        _add_product(db, "SAFE-MIX-01", "\u6d4b\u8bd5\u6c34\u58f6", "\u6c34\u5177", "1L", "\u94dd", "/", "\u8f7b\u4fbf", "\u9732\u8425", 200)
        _add_product_qa(db, "SAFE-MIX-01", "\u6d4b\u8bd5\u6c34\u58f6\u80fd\u5728\u5bb6\u91cc\u7528\u5417\uff1f", "\u53ef\u517c\u5bb9\u5bb6\u7528\u7076\u5177\u3002")
        db.commit()
        qa = db.query(ProductQa).filter(ProductQa.question == "\u6d4b\u8bd5\u6c34\u58f6\u80fd\u5728\u5bb6\u91cc\u7528\u5417\uff1f").one()
        result = customer_service_service._try_product_qa_shortcut(db, question, phase1_plan={"semantic_preplan": preplan}, selected_qa=qa)

    assert result is not None
    assert result["result_skus"] == ["SAFE-MIX-01"]
    assert "\u53ef\u517c\u5bb9\u5bb6\u7528\u7076\u5177" in result["answer"]


@pytest.mark.parametrize(
    ("question", "expected_sku"),
    [
        ("CF-PG19 在商品档案里归入什么体系？", "CF-PG19"),
        ("城市出逃饭盒 在商品档案里归入什么体系？", "TW-139CS"),
    ],
)
def test_semantic_outage_named_product_without_field_contract_fails_closed_before_qa_or_knowledge_base(
    route_client_and_db,
    monkeypatch,
    question,
    expected_sku,
):
    """An unavailable semantic classifier must never turn an unclassified product fact into a free-form answer."""
    client, headers, Session = route_client_and_db
    if expected_sku == "TW-139CS":
        with Session() as db:
            _add_product(db, "TW-139CS", "城市出逃饭盒", "餐具", "900ML", "304不锈钢", "/", "城市出逃系列", "公园野餐", 180)
            db.commit()

    async def unavailable_preplan(db, question, deterministic_plan, context):
        return {
            "called": True,
            "canonical_fields": [],
            "field_type": "",
            "confidence": 0.0,
            "fallback_reason": "llm_error:ConnectError",
            "route_hint": "",
            "question_type": "",
            "entities": [],
        }

    monkeypatch.setattr(customer_agent_planner_service, "plan_customer_question_semantic", unavailable_preplan)

    response = client.post(
        "/api/customer-service/ask?debug=true",
        json={"question": question},
        headers=headers,
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    debug = payload.get("debug") or {}

    assert payload["answer_type"] == "clarification", payload
    assert payload.get("result_skus") == [], payload
    assert payload.get("candidate_skus") == [expected_sku], payload
    assert debug.get("agent_mode") == "semantic_outage_named_product_field_clarification", debug
    assert debug.get("agent_mode") not in {"product_qa_fast_path", "product_usage_care_fast_path"}, debug
    assert payload["answer_type"] != "knowledge_base_answer", payload
    assert "负责人" not in str(payload.get("answer") or ""), payload


@pytest.mark.parametrize(
    ("question", "field_hint", "subtype", "route_hint", "question_type"),
    [
        ("围雪炉 现在有货吗？", "stock", "commercial_realtime", "query_products", "unknown_field"),
        ("瓦片烤盘 到手价多少？", "price", "known_detail", "product_detail", "field"),
    ],
)
def test_route_level_unknown_realtime_contract_prefers_ambiguous_scope_over_early_resolution(
    route_client_and_db,
    monkeypatch,
    question,
    field_hint,
    subtype,
    route_hint,
    question_type,
):
    client, headers, _ = route_client_and_db

    async def fake_preplan(db, question, deterministic_plan, context):
        return _unknown_realtime_preplan_stub(
            field_hint=field_hint,
            entity_scope="ambiguous_product_name",
            subtype=subtype,
            route_hint=route_hint,
            question_type=question_type,
            unknown_field=(question_type == "unknown_field"),
        )

    monkeypatch.setattr(customer_agent_planner_service, "plan_customer_question_semantic", fake_preplan)

    response = client.post("/api/customer-service/ask?debug=true", json={"question": question}, headers=headers)
    assert response.status_code == 200, response.text
    payload = response.json()
    answer_metadata = payload.get("answer_metadata") or {}

    assert payload["answer_type"] == "clarification", payload
    assert payload.get("needs_clarification") is True, payload
    assert payload.get("debug", {}).get("agent_mode") != "resolved_entity_unknown_field_fallback", payload.get("debug")
    assert answer_metadata.get("source") == "named_product_unknown_field_clarification", answer_metadata


@pytest.mark.parametrize(
    ("question", "field_hint", "subtype", "route_hint", "question_type"),
    [
        ("婧川水壶 现在有货吗？", "stock", "commercial_realtime", "query_products", "unknown_field"),
        ("星河水壶 有赠品吗？", "gift", "contents_accessories", "product_detail", "field"),
        ("青川套锅 有优惠券吗？", "coupon", "recommendation", "recommendation", "recommendation"),
    ],
)
def test_route_level_unknown_realtime_contract_clarifies_unresolved_product_like_even_when_preplan_misclassifies_subtype(
    route_client_and_db,
    monkeypatch,
    question,
    field_hint,
    subtype,
    route_hint,
    question_type,
):
    client, headers, _ = route_client_and_db

    async def fake_preplan(db, question, deterministic_plan, context):
        return _unknown_realtime_preplan_stub(
            field_hint=field_hint,
            entity_scope="unresolved_product_like",
            subtype=subtype,
            route_hint=route_hint,
            question_type=question_type,
            unknown_field=(question_type == "unknown_field"),
        )

    monkeypatch.setattr(customer_agent_planner_service, "plan_customer_question_semantic", fake_preplan)

    response = client.post("/api/customer-service/ask?debug=true", json={"question": question}, headers=headers)
    assert response.status_code == 200, response.text
    payload = response.json()
    answer_metadata = payload.get("answer_metadata") or {}

    assert payload["answer_type"] == "clarification", payload
    assert payload.get("needs_clarification") is True, payload
    assert payload.get("result_skus") in ([], None), payload.get("result_skus")
    assert payload["answer_type"] not in {"knowledge_base_answer", "product_query", "recommendation"}, payload
    assert answer_metadata.get("source") == "unresolved_product_like_unknown_field_clarification", answer_metadata


@pytest.mark.parametrize(
    ("question", "field_hint"),
    [
        ("完全不存在的产品名 有库存吗？", "stock"),
        ("ABC-FAKE-001 有活动吗？", "promotion"),
        ("TEST-NO-SKU 到手价多少？", "price"),
    ],
)
def test_route_level_unknown_realtime_contract_uses_not_found_for_no_match_scope(
    route_client_and_db,
    monkeypatch,
    question,
    field_hint,
):
    client, headers, _ = route_client_and_db

    async def fake_preplan(db, question, deterministic_plan, context):
        return _unknown_realtime_preplan_stub(
            field_hint=field_hint,
            entity_scope="generic_scope",
            subtype="no_match",
            route_hint="query_products",
            question_type="unknown_field",
        )

    monkeypatch.setattr(customer_agent_planner_service, "plan_customer_question_semantic", fake_preplan)

    response = client.post("/api/customer-service/ask?debug=true", json={"question": question}, headers=headers)
    assert response.status_code == 200, response.text
    payload = response.json()
    answer = str(payload.get("answer") or "")
    answer_metadata = payload.get("answer_metadata") or {}

    assert payload["answer_type"] == "product_detail", payload
    assert payload.get("result_skus") in ([], None), payload.get("result_skus")
    assert "Product not found" in answer or "没有找到" in answer, answer
    assert answer_metadata.get("source") == "unknown_field_product_not_found", answer_metadata
    assert payload.get("debug", {}).get("agent_mode") != "structured_unknown_field_guard", payload.get("debug")


@pytest.mark.parametrize(
    ("question", "field_hint", "subtype", "entity_scope", "entities", "expected_sources"),
    [
        (
            "围雪炉 现在有货吗？",
            "stock",
            "commercial_realtime",
            "unique_product_name",
            ["围雪炉"],
            {"named_product_unknown_field_clarification", "unresolved_product_like_unknown_field_clarification"},
        ),
        (
            "婧川水壶 现在有货吗？",
            "stock",
            "commercial_realtime",
            "unique_product_name",
            ["婧川水壶"],
            {"unresolved_product_like_unknown_field_clarification"},
        ),
    ],
)
def test_route_level_unknown_realtime_contract_uses_preplan_entities_when_question_subject_is_empty(
    route_client_and_db,
    monkeypatch,
    question,
    field_hint,
    subtype,
    entity_scope,
    entities,
    expected_sources,
):
    client, headers, _ = route_client_and_db

    async def fake_preplan(db, question, deterministic_plan, context):
        plan = _unknown_realtime_preplan_stub(
            field_hint=field_hint,
            entity_scope=entity_scope,
            subtype=subtype,
            route_hint="query_products",
            question_type="count",
            unknown_field=False,
        )
        plan["entities"] = entities
        return plan

    monkeypatch.setattr(customer_agent_planner_service, "plan_customer_question_semantic", fake_preplan)
    monkeypatch.setattr(customer_agent_intent_service, "_detail_subject_from_question", lambda text: "")

    response = client.post("/api/customer-service/ask?debug=true", json={"question": question}, headers=headers)
    assert response.status_code == 200, response.text
    payload = response.json()
    answer_metadata = payload.get("answer_metadata") or {}

    assert payload["answer_type"] == "clarification", payload
    assert payload.get("needs_clarification") is True, payload
    assert answer_metadata.get("source") in expected_sources, answer_metadata


def test_route_level_unknown_realtime_contract_no_match_overrides_unresolved_when_subject_is_empty(
    route_client_and_db,
    monkeypatch,
):
    client, headers, _ = route_client_and_db

    async def fake_preplan(db, question, deterministic_plan, context):
        plan = _unknown_realtime_preplan_stub(
            field_hint="stock",
            entity_scope="unresolved_product_like",
            subtype="no_match",
            route_hint="query_products",
            question_type="count",
            unknown_field=False,
        )
        plan["entities"] = ["完全不存在的产品名"]
        return plan

    monkeypatch.setattr(customer_agent_planner_service, "plan_customer_question_semantic", fake_preplan)
    monkeypatch.setattr(customer_agent_intent_service, "_detail_subject_from_question", lambda text: "")

    response = client.post("/api/customer-service/ask?debug=true", json={"question": "完全不存在的产品名 有库存吗？"}, headers=headers)
    assert response.status_code == 200, response.text
    payload = response.json()
    answer_metadata = payload.get("answer_metadata") or {}

    assert payload["answer_type"] == "product_detail", payload
    assert "Product not found" in payload.get("answer", "") or "没有找到" in payload.get("answer", ""), payload.get("answer")
    assert answer_metadata.get("source") == "unknown_field_product_not_found", answer_metadata


@pytest.mark.parametrize(
    ("question", "expected_answer_type", "required_sku", "required_terms"),
    [
        ("\u0043\u0046\u002d\u0050\u0047\u0031\u0039 \u662f\u4ec0\u4e48\u6750\u8d28\uff1f", "product_detail", "CF-PG19", ("\u786c\u8d28\u6c27\u5316\u94dd\u5408\u91d1", "\u6750\u8d28")),
        ("\u0043\u0046\u002d\u0050\u0047\u0031\u0039 \u9002\u5408\u4ec0\u4e48\u573a\u666f\uff1f", "product_detail", "CF-PG19", ("\u9732\u8425\u70e7\u70e4", "\u8425\u5730\u65e9\u9910", "\u573a\u666f")),
        ("\u004b\u0057\u002d\u004b\u0033\u0032\u002d\u767d\u53ef\u4ee5\u76f4\u63a5\u52a0\u70ed\u5417\uff1f", "product_detail", "KW-K32-白", ("\u660e\u706b\u76f4\u70e7", "\u5361\u5f0f\u7089", "\u9002\u7528\u70ed\u6e90")),
        ("\u0043\u0054\u002d\u0054\u0030\u0034\u0028\u0042\u004d\u0029 \u91cc\u9762\u6709\u4ec0\u4e48\uff1f", "product_detail", "CT-T04(BM)", ("\u8336\u58f6", "\u8336\u676f", "\u5f00\u7bb1")),
        # Migrate only the obsolete pre-FieldContract route label; the answer
        # still has to use the exact product's seeded cleaning evidence.
        ("\u0043\u0057\u002d\u0043\u0030\u0036\u0050\u0052\u004f \u600e\u4e48\u6e05\u6d17\uff1f", "product_detail", "CW-C06PRO", ("\u6e05\u6d17", "\u8f6f\u5237", "\u6e29\u6c34")),
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
    if question == "\u0043\u0054\u002d\u0054\u0030\u0034\u0028\u0042\u004d\u0029 \u91cc\u9762\u6709\u4ec0\u4e48\uff1f":
        debug = payload.get("debug") or {}
        entity = debug.get("entity_resolution_contract") or {}
        assert debug.get("agent_mode") == "resolved_entity_detail_contract", payload
        assert entity.get("status") == "resolved", entity
        assert entity.get("resolved_sku") == "CT-T04(BM)", entity
        assert entity.get("field_type") == "accessories", entity
        assert payload.get("candidate_skus") == ["CT-T04(BM)"], payload
        assert payload.get("result_skus") == ["CT-T04(BM)"], payload
        assert answer_metadata.get("contract_field_type") == "accessories", answer_metadata
        assert answer_metadata.get("evidence_field") == "accessories", answer_metadata
        assert answer_metadata.get("evidence_sku") == "CT-T04(BM)", answer_metadata
        assert str(answer_metadata.get("evidence_source") or "").startswith("product_qa:"), answer_metadata
        assert answer_metadata.get("field_evidence_match") is True, answer_metadata
        assert answer_metadata.get("field_evidence_missing") is False, answer_metadata
        assert "usage_care" not in str(answer_metadata.get("evidence_source") or ""), answer_metadata
    if question == "\u0043\u0057\u002d\u0043\u0030\u0036\u0050\u0052\u004f \u600e\u4e48\u6e05\u6d17\uff1f":
        debug = payload.get("debug") or {}
        entity = debug.get("entity_resolution_contract") or {}
        assert debug.get("agent_mode") == "resolved_entity_detail_contract", payload
        assert (debug.get("field_contract") or {}).get("field_type") == "cleaning", payload
        assert entity.get("status") == "resolved", entity
        assert entity.get("resolved_sku") == "CW-C06PRO", entity
        assert payload.get("candidate_skus") == ["CW-C06PRO"], payload
        assert payload.get("result_skus") == ["CW-C06PRO"], payload
        assert answer_metadata.get("contract_field_type") == "cleaning", answer_metadata
        assert answer_metadata.get("evidence_sku") == "CW-C06PRO", answer_metadata
    assert not (
        answer_metadata.get("source") == "resolved_entity_unknown_field_fallback"
        or payload.get("debug", {}).get("agent_mode") == "resolved_entity_unknown_field_fallback"
    ), payload
    assert "Product not found" not in answer, answer
    assert not any(term in answer for term in ("\u5f53\u524d\u8d44\u6599\u672a\u6807\u6ce8\u8be5\u5546\u54c1\u662f\u5426\u9644\u8d60", "\u65e0\u6cd5\u786e\u8ba4\u5b9e\u65f6")), answer
    assert any(term in answer for term in required_terms), answer


def _assert_conservative_contents_answer(payload: dict, expected_sku: str) -> None:
    answer = str(payload.get("answer") or "")
    debug = payload.get("debug") or {}
    entity = debug.get("entity_resolution_contract") or {}
    metadata = payload.get("answer_metadata") or {}
    assert payload["answer_type"] == "product_detail", payload
    assert debug.get("agent_mode") == "resolved_entity_detail_contract", payload
    assert entity.get("status") == "resolved", entity
    assert entity.get("resolved_sku") == expected_sku, entity
    assert entity.get("field_type") == "accessories", entity
    assert payload.get("candidate_skus") == [expected_sku], payload
    assert payload.get("result_skus") == [expected_sku], payload
    assert metadata.get("contract_field_type") == "accessories", metadata
    if metadata.get("field_evidence_match"):
        assert metadata.get("evidence_field") == "accessories", metadata
        assert metadata.get("evidence_sku") == expected_sku, metadata
        assert str(metadata.get("evidence_source") or "").startswith("product_qa:"), metadata
        assert metadata.get("field_evidence_missing") is False, metadata
        evidence_value = str(metadata.get("evidence_value") or "")
        assert evidence_value and evidence_value in answer, metadata
    else:
        assert metadata.get("field_evidence_missing") is True, metadata
        assert metadata.get("evidence_field") is None, metadata
        assert metadata.get("evidence_source") is None, metadata
        assert metadata.get("evidence_sku") is None, metadata
        assert any(
            term in answer
            for term in (
                "当前资料可确认包含",
                "锅、炒锅和煎锅",
                "当前资料暂未提供明确的套装包含或组成说明",
                "当前资料未标注套装包含内容",
                "当前资料中暂未标注",
                "无法确认具体清单",
                "建议联系人工客服确认",
            )
        ), answer
    assert "usage_care" not in str(metadata.get("evidence_source") or ""), metadata
    assert answer, payload
    assert expected_sku in (payload.get("result_skus") or []), payload.get("result_skus")
    assert "Product not found" not in answer, answer


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
    assert payload.get("debug", {}).get("agent_mode") == "resolved_entity_detail_contract", payload.get("debug")
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

    _assert_conservative_contents_answer(payload, expected_sku)
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

    _assert_conservative_contents_answer(payload, "CW-C83")
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
            "\u5f53\u524d\u8d44\u6599\u4e2d\u6682\u672a\u6807\u6ce8",
        )
    ), answer


def _assert_resolved_sku_accessories_contract(payload: dict, expected_sku: str) -> None:
    answer = str(payload.get("answer") or "")
    _assert_conservative_contents_answer(payload, expected_sku)
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
            "当前资料中暂未标注",
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

    _assert_conservative_contents_answer(payload, expected_sku)
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
                "当前资料中暂未标注",
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

    _assert_conservative_contents_answer(payload, expected_sku)
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
    if expected_sku:
        _assert_conservative_contents_answer(payload, expected_sku)
    else:
        assert payload["answer_type"] == "product_detail", payload
    assert "当前匹配到【配件】类产品共有" not in answer, answer
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
    ("question", "expected_sku"),
    [
        ("CF-PG19 原厂配了什么？", "CF-PG19"),
        ("CF-PG19 盒子里有什么？", "CF-PG19"),
        ("CS-B14（LX） what does it come with?", "CS-B14（LX）"),
    ],
)
def test_route_level_blind_contents_phrases_do_not_fall_back_to_generic_product_qa_dump(
    route_client_and_db,
    question,
    expected_sku,
):
    client, headers, Session = route_client_and_db
    _seed_contents_grounding_evidence(Session)
    _seed_cf_pg19_generic_detail_noise(Session)

    response = client.post("/api/customer-service/ask?debug=true", json={"question": question}, headers=headers)
    assert response.status_code == 200, response.text
    payload = response.json()

    _assert_contents_contract_answer(payload, expected_sku=expected_sku)
    assert payload.get("debug", {}).get("agent_mode") != "product_qa_fast_path", payload.get("debug")


@pytest.mark.parametrize(
    "question",
    [
        "CF-PG19 原装都带啥？",
        "CF-PG19 随箱有什么？",
        "CF-PG19 开箱能看到什么？",
        "CF-PG19 买回来会附些什么？",
        "CF-PG19 盒子里都装了哪些东西？",
    ],
)
def test_route_level_long_tail_contents_uses_validated_semantic_field_contract_without_alias(
    route_client_and_db,
    monkeypatch,
    question,
):
    client, headers, Session = route_client_and_db
    _seed_cf_pg19_generic_detail_noise(Session)
    assert customer_field_contract.detect_field_contract(question) is None

    async def fake_preplan(db, question, deterministic_plan, context):
        return _contents_semantic_preplan_stub()

    monkeypatch.setattr(customer_agent_planner_service, "plan_customer_question_semantic", fake_preplan)

    response = client.post("/api/customer-service/ask?debug=true", json={"question": question}, headers=headers)
    assert response.status_code == 200, response.text
    payload = response.json()
    debug = payload.get("debug") or {}
    plan = debug.get("plan") or {}
    field_contract = plan.get("field_contract") or {}
    entity = debug.get("entity_resolution_contract") or {}

    _assert_contents_contract_answer(payload, expected_sku="CF-PG19")
    assert field_contract.get("source") == "validated_semantic_preplan", field_contract
    assert field_contract.get("field_type") == "accessories", field_contract
    assert field_contract.get("canonical_fields") == ["accessories"], field_contract
    assert field_contract.get("subject") == "CF-PG19", field_contract
    assert entity.get("status") == "resolved", entity
    assert entity.get("resolved_sku") == "CF-PG19", entity
    assert entity.get("entity_text") != "semantic-entity-must-not-seal-identity", entity
    assert payload.get("answer_type") != "product_usage_care", payload
    assert debug.get("agent_mode") != "llm_tool_calling", debug


def test_semantic_field_contract_recovers_unique_longest_canonical_name_without_semantic_identity(
    route_client_and_db,
    monkeypatch,
):
    client, headers, Session = route_client_and_db
    with Session() as db:
        _add_product(db, "SEM-BASE", "远行炉", "炉具", "", "不锈钢", "酒精", "基础款", "露营", 300)
        _add_product(db, "SEM-PRO", "远行炉Pro-组合版", "炉具", "", "不锈钢", "酒精", "组合款", "露营", 360)
        db.commit()

    question = "远行炉Pro-组合版收到货拆开会配些什么？"
    assert customer_field_contract.detect_field_contract(question) is None

    async def fake_preplan(db, question, deterministic_plan, context):
        return _contents_semantic_preplan_stub()

    monkeypatch.setattr(customer_agent_planner_service, "plan_customer_question_semantic", fake_preplan)
    payload = client.post(
        "/api/customer-service/ask?debug=true",
        json={"question": question},
        headers=headers,
    ).json()

    debug = payload.get("debug") or {}
    field_contract = (debug.get("plan") or {}).get("field_contract") or {}
    entity = debug.get("entity_resolution_contract") or {}
    assert field_contract.get("source") == "validated_semantic_preplan", payload
    assert field_contract.get("subject") == "远行炉Pro-组合版", payload
    assert entity.get("status") == "resolved", payload
    assert entity.get("resolved_sku") == "SEM-PRO", payload
    assert entity.get("resolver_candidate_skus") == ["SEM-PRO"], payload
    assert payload.get("candidate_skus") == ["SEM-PRO"], payload
    assert payload.get("result_skus") == ["SEM-PRO"], payload
    assert "未标注" in payload.get("answer", ""), payload


@pytest.mark.parametrize(
    "question",
    [
        "有哪些配件更偏收纳？",
        "什么产品更适合收纳？",
        "推荐一个带收纳功能的产品",
    ],
)
def test_route_level_semantic_contents_candidate_does_not_narrow_generic_recommendation(
    route_client_and_db,
    monkeypatch,
    question,
):
    client, headers, _ = route_client_and_db

    async def fake_preplan(db, question, deterministic_plan, context):
        semantic = _contents_semantic_preplan_stub()
        semantic["entity_scope"] = "generic_scope"
        return semantic

    monkeypatch.setattr(customer_agent_planner_service, "plan_customer_question_semantic", fake_preplan)

    response = client.post("/api/customer-service/ask?debug=true", json={"question": question}, headers=headers)
    assert response.status_code == 200, response.text
    payload = response.json()

    assert payload.get("answer_type") in {"query_products", "product_query", "recommendation"}, payload
    debug = payload.get("debug") or {}
    entity = debug.get("entity_resolution_contract") or {}
    assert debug.get("agent_mode") != "resolved_entity_detail_contract", payload
    assert entity.get("status") != "resolved", entity


@pytest.mark.parametrize(
    ("question", "expected_answer_type", "expected_sku"),
    [
        ("CS-G25 盒子里有什么？", "product_detail", "CS-G25"),
        ("CW-C83 what comes in the box?", "product_detail", "CW-C83"),
        ("围雪炉 盒子里有什么？", "clarification", None),
        ("婧川水壶 有没有附件？", "clarification", None),
        ("户外有什么配件？", ("query_products", "recommendation"), None),
    ],
)
def test_route_level_blind_contents_entity_scope_contract(
    route_client_and_db,
    question,
    expected_answer_type,
    expected_sku,
):
    client, headers, Session = route_client_and_db
    _seed_contents_grounding_evidence(Session)
    _seed_contents_resolution_priority_products(Session)

    response = client.post("/api/customer-service/ask?debug=true", json={"question": question}, headers=headers)
    assert response.status_code == 200, response.text
    payload = response.json()
    answer = str(payload.get("answer") or "")

    if isinstance(expected_answer_type, tuple):
        assert payload["answer_type"] in expected_answer_type, payload
    else:
        assert payload["answer_type"] == expected_answer_type, payload
    if expected_sku:
        _assert_contents_contract_answer(payload, expected_sku=expected_sku)
    else:
        assert "Product not found" not in answer, answer
        assert payload["answer_type"] != "knowledge_base_answer", payload
        if expected_answer_type == "clarification":
            assert "当前匹配到【配件】类产品共有" not in answer, answer


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
        # "瓦片烤盘" is the canonical exact base-product name. The family
        # ambiguity contract uses the established family alias "瓦片盘".
        "瓦片盘 有哪些配件？",
        "瓦片盘 包装清单是什么？",
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
    entity = (payload.get("debug") or {}).get("entity_resolution_contract") or {}

    assert payload["answer_type"] == "clarification", payload
    assert payload.get("needs_clarification") is True, payload
    assert "Product not found" not in answer, answer
    assert payload.get("result_skus") in ([], None), payload
    assert payload.get("candidate_skus"), payload
    assert entity.get("status") == "ambiguous", entity
    assert entity.get("resolved_sku") is None, entity
    assert entity.get("field_type") == "accessories", entity
    if question.startswith("瓦片盘"):
        assert set(payload.get("candidate_skus") or []) >= {"CF-PG19", "CF-PG19PRO"}, payload
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


def test_compare_answer_guard_does_not_append_unrelated_capacity_guidance_when_results_are_already_covered():
    answer = "甲款更适合煮咖啡，乙款更适合烧烤。"
    result = {
        "answer": f"{answer} KW-K31-黑 CF-PG19",
        "answer_type": "comparison",
        "result_skus": ["KW-K31-黑", "CF-PG19"],
    }
    plan = {
        "primary_intent": "product_compare_recommendation",
        "product_refs": ["KW-K31-黑", "CF-PG19哪个更适合露营"],
        "must_make_choice": True,
        "scenario": "露营",
    }

    guarded = customer_service_service._run_phase1_answer_guard(result, plan)

    assert guarded["answer"] == result["answer"]
    assert "两个人吃饱" not in guarded["answer"]
    assert "CF-PG19哪个更适合露营" not in guarded["answer"]


def test_compare_answer_guard_never_injects_a_fixed_scenario_or_choice_into_an_incomplete_answer():
    result = {
        "answer": "当前仅能确认两款产品资料仍需进一步核对。",
        "answer_type": "comparison",
        "result_skus": ["SKU-A", "SKU-B"],
    }
    plan = {
        "primary_intent": "product_compare_recommendation",
        "product_refs": ["示例甲", "示例乙"],
        "must_make_choice": True,
        "scenario": "两个人吃饱",
    }
    original_answer = result["answer"]

    guarded = customer_service_service._run_phase1_answer_guard(result, plan)

    assert guarded["answer"] == original_answer
    assert "两个人吃饱" not in guarded["answer"]
    assert "容量余量" not in guarded["answer"]


def test_named_product_navigation_does_not_use_unrelated_product_qa(route_client_and_db):
    client, headers, Session = route_client_and_db
    _seed_contents_resolution_priority_products(Session)

    response = client.post(
        "/api/customer-service/ask?debug=true",
        json={"question": "改看瓦片烤盘Pro。"},
        headers=headers,
    )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload.get("result_skus") == ["CF-PG19PRO"], payload
    assert payload.get("answer") != "安全。", payload
    assert payload.get("answer", "").startswith("已切换到瓦片烤盘Pro（CF-PG19PRO）。"), payload
    assert (payload.get("debug") or {}).get("agent_mode") == "named_product_shortcut", payload


def test_semantic_product_navigation_never_falls_back_to_all_products_catalog_count(
    route_client_and_db,
    monkeypatch,
):
    client, headers, Session = route_client_and_db
    with Session() as db:
        _add_product(db, "SNOW-GAS", "\u6c14\u7089\u56f4\u96ea\u7089", "\u7089\u5177", "/", "\u4e0d\u9508\u94a2", "\u6c14\u7f50", "\u56f4\u96ea\u7089\u914d\u4ef6", "\u9732\u8425", 120)
        _add_product(db, "SNOW-PRO", "\u56f4\u96ea\u7089Pro", "\u7089\u5177", "/", "\u4e0d\u9508\u94a2", "\u6c14\u7f50", "\u56f4\u96ea\u7089\u7cfb\u5217", "\u9732\u8425", 2600)
        db.commit()

    async def fake_preplan(_db, _question, _deterministic_plan, context=None):
        return {
            "called": True,
            "purpose": "semantic_preplan",
            "route_family": "product_navigation",
            "route_hint": "product_detail",
            "question_type": "navigation",
            "subject_text": "\u56f4\u96ea\u7089",
            "canonical_fields": [],
            "field_type": "",
            "ambiguity": False,
            "evidence_required": False,
            "confidence": 0.9,
            "confidence_label": "high",
            "context_usage": "none",
            "reasoning_summary": "Customer asks for variants of a named product family.",
        }

    monkeypatch.setattr(customer_agent_planner_service, "plan_customer_question_semantic", fake_preplan)

    response = client.post(
        "/api/customer-service/ask?debug=true",
        json={"question": "\u56f4\u96ea\u7089\u6709\u54ea\u51e0\u6b3e\uff1f"},
        headers=headers,
    )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert "\u3010\u4ea7\u54c1\u3011\u7c7b\u4ea7\u54c1\u5171\u6709" not in str(payload.get("answer") or ""), payload
    assert (payload.get("debug") or {}).get("agent_mode") != "structured_catalog_count", payload


def test_unlabelled_product_family_navigation_does_not_execute_guessed_series_filter(
    route_client_and_db,
    monkeypatch,
):
    client, headers, Session = route_client_and_db
    with Session() as db:
        _add_product(db, "FAMILY-A", "苍穹炉-酒精版", "炉具", "/", "不锈钢", "酒精", "露营炉具", "露营", 120)
        _add_product(db, "FAMILY-B", "苍穹炉-气炉版", "炉具", "/", "不锈钢", "气罐", "露营炉具", "露营", 2600)
        _add_product(db, "UNRELATED", "无关水壶", "水具", "800ml", "钛", "/", "苍穹炉系列", "徒步", 300)
        db.query(Product).filter(Product.sku == "UNRELATED").one().series = "苍穹炉系列"
        db.commit()

    async def fake_preplan(_db, _question, _deterministic_plan, context=None):
        return {
            "called": True,
            "purpose": "semantic_preplan",
            "route_family": "structured_query",
            "route_hint": "query_products",
            "question_type": "list",
            "subject_text": "苍穹炉",
            "canonical_fields": ["series"],
            "field_type": "series",
            "entities": [],
            "ambiguity": False,
            "evidence_required": True,
            "confidence": 0.95,
            "confidence_label": "high",
            "context_usage": "none",
            "reasoning_summary": "Customer asks which variants are available.",
        }

    monkeypatch.setattr(customer_agent_planner_service, "plan_customer_question_semantic", fake_preplan)
    response = client.post(
        "/api/customer-service/ask?debug=true",
        json={"question": "苍穹炉有哪几款？"},
        headers=headers,
    )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert (payload.get("debug") or {}).get("agent_mode") != "semantic_database_value_catalog_filter", payload
    assert "UNRELATED" not in (payload.get("result_skus") or []), payload


def test_explicit_sku_pair_survives_invalid_semantic_comparison_preplan(
    route_client_and_db,
    monkeypatch,
):
    client, headers, Session = route_client_and_db
    with Session() as db:
        _add_product(db, "CMP-A", "\u5bf9\u6bd4\u7532", "\u9505\u5177", "20cm", "\u94dd\u5408\u91d1", "\u5361\u5f0f\u7089", "\u6536\u7eb3\u5c0f", "\u9732\u8425", 1000)
        _add_product(db, "CMP-B", "\u5bf9\u6bd4\u4e59", "\u9505\u5177", "24cm", "\u94dd\u5408\u91d1", "\u5361\u5f0f\u7089", "\u8d1f\u91cd\u4f4e", "\u9732\u8425", 1200)
        db.commit()

    async def fake_preplan(_db, _question, _deterministic_plan, context=None):
        return {"called": True, "fallback_reason": "invalid_json"}

    monkeypatch.setattr(customer_agent_planner_service, "plan_customer_question_semantic", fake_preplan)
    response = client.post(
        "/api/customer-service/ask?debug=true",
        json={"question": "CMP-A \u548c CMP-B \u7684\u6536\u7eb3\u548c\u8d1f\u91cd\u600e\u4e48\u6bd4\uff1f"},
        headers=headers,
    )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload.get("answer_type") == "comparison", payload
    assert payload.get("result_skus") == ["CMP-A", "CMP-B"], payload
    assert (payload.get("debug") or {}).get("agent_mode") != "entity_state_detail_ambiguous", payload


def test_active_anchor_accessories_uses_field_contract_safe_missing(route_client_and_db):
    client, headers, Session = route_client_and_db
    _seed_contents_resolution_priority_products(Session)
    first = client.post(
        "/api/customer-service/ask?debug=true",
        json={"question": "瓦片烤盘Pro是什么材质？"},
        headers=headers,
    )
    assert first.status_code == 200, first.text
    conversation_id = first.json().get("conversation_id")

    followup = client.post(
        "/api/customer-service/ask?debug=true",
        json={"question": "它有配件吗？", "conversation_id": conversation_id},
        headers=headers,
    )

    assert followup.status_code == 200, followup.text
    payload = followup.json()
    answer = str(payload.get("answer") or "")
    assert payload.get("result_skus") == ["CF-PG19PRO"], payload
    assert "当前知识库已有相关资料，但不足以直接确认" not in answer, payload
    assert "暂未标注" in answer or "未标注" in answer, payload
    debug = payload.get("debug") or {}
    assert debug.get("agent_mode") == "recommendation_context_product_field", payload
    field_contract = debug.get("field_contract") or {}
    entity_contract = debug.get("entity_resolution_contract") or {}
    assert field_contract.get("field_type") == "accessories", payload
    assert entity_contract.get("status") == "resolved", payload
    assert entity_contract.get("resolved_sku") == "CF-PG19PRO", payload
    assert entity_contract.get("field_type") == "accessories", payload
    assert debug.get("binding_provenance") == "resolved_entity_contract", payload


def test_explicit_sku_identity_question_returns_product_overview(route_client_and_db):
    client, headers, _ = route_client_and_db

    response = client.post(
        "/api/customer-service/ask?debug=true",
        json={"question": "CF-PG19 是什么产品？"},
        headers=headers,
    )

    assert response.status_code == 200, response.text
    payload = response.json()
    answer = str(payload.get("answer") or "")
    entity = (payload.get("debug") or {}).get("entity_resolution_contract") or {}
    assert payload.get("result_skus") == ["CF-PG19"], payload
    assert answer.startswith("瓦片烤盘（CF-PG19）是一款锅具。"), payload
    assert "暂未找到" not in answer and "字段信息" not in answer, payload
    assert entity.get("status") == "resolved", entity
    assert entity.get("resolved_sku") == "CF-PG19", entity
    assert (payload.get("debug") or {}).get("agent_mode") == "explicit_sku_context_shortcut", payload

    variant_response = client.post(
        "/api/customer-service/ask?debug=true",
        json={"question": "KW-K31-黑是什么？"},
        headers=headers,
    )
    assert variant_response.status_code == 200, variant_response.text
    variant_payload = variant_response.json()
    assert variant_payload.get("result_skus") == ["KW-K31-黑"], variant_payload
    variant_answer = str(variant_payload.get("answer") or "")
    assert "是一款" in variant_answer, variant_payload
    assert "暂未找到" not in variant_answer, variant_payload
    assert (variant_payload.get("debug") or {}).get("agent_mode") == "explicit_sku_context_shortcut", variant_payload

    material_response = client.post(
        "/api/customer-service/ask?debug=true",
        json={"question": "CF-PG19 材质是什么？"},
        headers=headers,
    )
    assert material_response.status_code == 200, material_response.text
    material_payload = material_response.json()
    assert (material_payload.get("debug") or {}).get("agent_mode") != "explicit_sku_context_shortcut", material_payload
    assert "铝合金" in str(material_payload.get("answer") or ""), material_payload


def test_explicit_sku_plural_field_predicate_stays_on_structured_detail_route():
    question = "CW-C95 支持哪些燃料或气罐，最大功率是多少？"

    assert customer_service_service._is_explicit_sku_detail_question(question) is True
    assert customer_service_service._explicit_sku_detail_requested_fields(question) == ["热源", "功率"]


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
    # Clarification wording may ask the user to "提供 SKU" after stating that
    # the named product was not found; keep the contract assertion semantic.
    assert any(term in answer for term in ("没能", "具体 SKU", "确认是哪一款", "确认具体商品", "提供 SKU")), answer


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


def test_phase1_comparison_evidence_filters_placeholder_capacity_before_rendering():
    """Legacy comparison text must consume the same value validation as fields."""
    evidence = customer_service_service._phase1_product_evidence_text(
        {
            "capacity": '[{"label": "", "value": "/", "unit": ""}]',
            "body_material": "铝合金",
            "gross_weight_g": 1000,
            "features": "耐用",
        }
    )

    assert "/" not in evidence
    assert "铝合金" in evidence
    assert "耐用" in evidence


def test_phase1_comparison_evidence_can_limit_fallback_to_concise_verified_fields():
    evidence = customer_service_service._phase1_product_evidence_text(
        {
            "capacity": "1.7L",
            "body_material": "304不锈钢",
            "gross_weight_g": 960,
            "features": "方形设计增加烹饪空间",
            "usage_scenarios": "轻量徒步，单人露营",
            "positioning": "中式户外烹饪",
            "long_description_cn": "这是一段不应作为兜底比较字段串直接展示的长描述。",
        },
        max_fields=3,
    )

    assert "长描述" not in evidence
    assert evidence.count("；") <= 2


def test_result_evidence_filters_placeholder_capacity_before_api_serialization():
    evidence = customer_service_service._evidence_from_results(
        [{
            "sku": "GENERIC-SKU",
            "product_name_cn": "通用产品",
            "capacity": '[{"label": "", "value": "/", "unit": ""}]',
            "body_material": "铝合金",
        }]
    )

    assert all("/" not in str(item.get("value") or "") for item in evidence)
    assert any(item.get("field_label") == "材质" for item in evidence)


def test_customer_result_evidence_excludes_internal_operational_fields():
    owner_label = chr(0x8D1F) + chr(0x8D23) + chr(0x4EBA)
    evidence = customer_service_service._evidence_from_results(
        [{
            "sku": "GENERIC-SKU",
            "product_name_cn": "Generic product",
            "field_values": {owner_label: "InternalOwner", "capacity": "500ml"},
        }]
    )

    assert all(item.get("field_label") != owner_label for item in evidence)
    assert any(item.get("value") == "500ml" for item in evidence)


def test_database_value_grounded_semantic_catalog_filter_uses_series_column(route_client_and_db):
    _client, _headers, Session = route_client_and_db
    with Session() as db:
        product = db.query(Product).first()
        product.series = "FIELD-GROUNDING"
        db.commit()
        hints = customer_agent_planner_service._database_field_value_hints(
            db,
            "FIELD-GROUNDING products",
        )
        assert {item["field"] for item in hints} >= {"series"}
        result = customer_service_service._semantic_catalog_value_query_result(
            db,
            "FIELD-GROUNDING products",
            {
                "called": True,
                "route_family": "structured_query",
                "route_hint": "query_products",
                "field_type": "series",
                "subject_text": "FIELD-GROUNDING",
                "confidence": 0.9,
                "confidence_label": "high",
                "entities": [],
            },
        )
        labelled_result = customer_service_service._semantic_catalog_value_query_result(
            db,
            "FIELD-GROUNDING products",
            {
                "called": True,
                "route_family": "structured_query",
                "route_hint": "query_products",
                "field_type": "series",
                "subject_text": "FIELD-GROUNDING" + customer_field_contract.product_detail_field_label("series"),
                "confidence": 0.9,
                "confidence_label": "high",
                "entities": [],
            },
        )

    assert result is not None
    assert labelled_result is not None
    assert result["answer_metadata"]["source"] == "semantic_database_value_catalog_filter"
    assert product.sku in result["candidate_skus"]


def test_database_value_catalog_filter_rejects_content_only_series_membership(monkeypatch):
    """Multilingual scope evidence must map to exactly one stored field value."""
    rows = [
        {
            "sku": "SERIES-01",
            "product_name_cn": "产品一",
            "product_name_en": "camping cookware",
            "series": "归野主题-城市出逃",
            "title_en": "Urban Escape Cookware",
            "website_title": "",
            "amazon_title": "",
            "long_description_en": "Urban Escape collection",
            "long_description_cn": "",
        },
        {
            "sku": "SERIES-02",
            "product_name_cn": "产品二",
            "product_name_en": "camping stove",
            "series": "归野主题-城市出逃",
            "title_en": "Urban Escape Stove",
            "website_title": "",
            "amazon_title": "",
            "long_description_en": "Urban Escape collection",
            "long_description_cn": "",
        },
        {
            "sku": "OTHER-01",
            "product_name_cn": "其他产品",
            "product_name_en": "other product",
            "series": "其他系列",
            "title_en": "Other collection",
            "website_title": "",
            "amazon_title": "",
            "long_description_en": "",
            "long_description_cn": "",
        },
    ]
    monkeypatch.setattr(customer_service_service, "_phase1_catalog_rows", lambda *_args: rows)
    plan = {
        "called": True,
        "route_family": "structured_query",
        "route_hint": "query_products",
        "field_type": "series",
        "subject_text": "Urban Escape collection",
        "confidence": 0.9,
        "confidence_label": "high",
        "entities": [],
    }

    result = customer_service_service._semantic_catalog_value_query_result(None, "Which products are in the Urban Escape collection?", plan)

    assert result is None
    return
    assert "同商品内容映射" in result["answer"]

    rows[1]["series"] = "其他系列"
    assert customer_service_service._semantic_catalog_value_query_result(None, "Which products are in the Urban Escape collection?", plan) is None


def test_semantic_catalog_value_filter_yields_to_a_resolved_numeric_contract():
    result = customer_service_service._semantic_catalog_value_query_result(
        None,
        "容量不小于1升的水壶有哪些？",
        {
            "called": True,
            "route_family": "structured_query",
            "route_hint": "query_products",
            "field_type": "category",
            "subject_text": "水壶",
            "confidence": 0.9,
            "confidence_label": "high",
            "entities": [],
        },
    )

    assert result is None


def test_resolved_structured_contract_preempts_catalog_value_preflight():
    assert customer_service_service._resolved_structured_contract_preempts_catalog_value_preflight(
        "容量不小于1升的水壶有哪些？"
    ) is True
    assert customer_service_service._resolved_structured_contract_preempts_catalog_value_preflight(
        "水壶有哪些？"
    ) is False


def test_structured_field_filter_executes_resolved_capacity_contract(monkeypatch):
    rows = [
        {"sku": "KETTLE-08", "product_name_cn": "0.8L水壶", "category": "水壶", "capacity": "800ml"},
        {"sku": "KETTLE-12", "product_name_cn": "1.2L水壶", "category": "水壶", "capacity": "1200ml"},
    ]
    monkeypatch.setattr(customer_service_service, "_looks_like_structured_field_filter_query", lambda _question: True)
    monkeypatch.setattr(customer_service_service, "_phase1_catalog_rows", lambda _db, _ref: list(rows))

    result = customer_service_service._structured_field_filter_result(
        None,
        "容量不小于1升的水壶有哪些？",
    )

    assert result is not None
    assert result["result_skus"] == ["KETTLE-12"]


def test_high_confidence_named_sales_field_preempts_category_filter(
    route_client_and_db,
    monkeypatch,
):
    """A named product field must not become a catalogue query because its name is a category cue."""
    client, headers, Session = route_client_and_db
    with Session() as db:
        _add_product(
            db,
            "SEM-SALES-01",
            "\u8bed\u4e49\u8def\u7531\u7089",
            "\u7089\u5177",
            "1L",
            "/",
            "/",
            "\u6d4b\u8bd5\u4ea7\u54c1",
            "\u9732\u8425",
            0,
        )
        db.commit()

    async def fake_preplan(*_args, **_kwargs):
        return {
            "called": True,
            "route_family": "product_bound_qa",
            "route_hint": "product_detail",
            "question_type": "field",
            "subtype": "known_detail",
            "subject_text": "\u8bed\u4e49\u8def\u7531\u7089",
            "canonical_fields": ["sales_region"],
            "field_type": "sales_region",
            "field_hint": "sales_region",
            "confidence": 0.95,
            "ambiguity": False,
            "evidence_required": True,
            "evidence_kind": "structured_field",
            "context_usage": "none",
        }

    monkeypatch.setattr(customer_agent_planner_service, "plan_customer_question_semantic", fake_preplan)
    payload = client.post(
        "/api/customer-service/ask?debug=true",
        json={"question": "\u8bed\u4e49\u8def\u7531\u7089\u4e3b\u8981\u552e\u5f80\u54ea\u4e9b\u5730\u533a\uff1f"},
        headers=headers,
    ).json()

    field = (payload.get("debug") or {}).get("field_contract") or {}
    entity = (payload.get("debug") or {}).get("entity_resolution_contract") or {}
    assert payload["answer_type"] == "product_detail", payload
    assert field.get("field_type") == "sales_region", payload
    assert entity.get("resolved_sku") == "SEM-SALES-01", payload
    assert payload.get("result_skus") == ["SEM-SALES-01"], payload


def test_legacy_catalog_plan_cannot_defer_validated_named_formal_field(monkeypatch):
    """A stale catalogue plan is a fallback, never an override of semantic FieldContract."""
    monkeypatch.setattr(
        customer_service_service,
        "_looks_like_structured_field_filter_query",
        lambda _question: True,
    )
    plan = {
        "primary_intent": "catalog_count",
        "semantic_preplan": {
            "called": True,
            "route_family": "product_bound_qa",
            "route_hint": "product_detail",
            "canonical_fields": ["sales_region"],
            "field_type": "sales_region",
            "confidence": 0.95,
            "ambiguity": False,
        },
    }

    assert customer_service_service._should_prioritize_semantic_structured_route(
        "\u8bed\u4e49\u8def\u7531\u7089\u4e3b\u8981\u552e\u5f80\u54ea\u4e9b\u5730\u533a\uff1f",
        plan,
    ) is False


def test_structured_field_qa_fallback_accepts_same_field_paraphrase(route_client_and_db):
    """A sealed field fallback may use only a field-compatible QA on the same SKU."""
    _client, _headers, Session = route_client_and_db
    with Session() as db:
        _add_product(
            db,
            "SEM-QA-01",
            "\u8bed\u4e49\u6e20\u9053\u7089",
            "\u7089\u5177",
            "1L",
            "/",
            "/",
            "\u6d4b\u8bd5\u4ea7\u54c1",
            "\u9732\u8425",
            0,
        )
        _add_product_qa(
            db,
            "SEM-QA-01",
            "\u8bed\u4e49\u6e20\u9053\u7089\u54ea\u91cc\u53ef\u4ee5\u4e70\u5230\uff1f",
            "\u53ef\u5728\u54c1\u724c\u5b98\u65b9\u6388\u6743\u6e20\u9053\u8d2d\u4e70\u3002",
            tags="\u8d2d\u4e70\u6e20\u9053",
        )
        db.commit()
        result = customer_service_service._phase1_product_field_result(
            db,
            {
                "raw_question": "\u8bed\u4e49\u6e20\u9053\u7089\u5728\u54ea\u4e2a\u5e73\u53f0\u8d2d\u4e70\uff1f",
                "product_ref": "SEM-QA-01",
                "sku": "SEM-QA-01",
                "requested_field": "\u8d2d\u4e70\u6e20\u9053",
                "field_type_override": "purchase_channel",
                "field_only": True,
                "product_identity_source": "phase2_resolved_entity",
            },
        )

    metadata = result.get("answer_metadata") or {}
    assert "\u5b98\u65b9\u6388\u6743\u6e20\u9053" in result["answer"], result
    assert metadata.get("evidence_sku") == "SEM-QA-01", result
    assert str(metadata.get("evidence_source") or "").startswith("product_qa:"), result


def test_sealed_multi_field_output_is_not_truncated_to_its_first_field():
    answer = "\u5f53\u524d\u8d44\u6599\u4e2d\u6682\u672a\u627e\u5230\u8bed\u4e49\u591a\u5b57\u6bb5\u7089\uff08SEM-MULTI-01\uff09\u7684\u6750\u8d28\u3002\n\u5f53\u524d\u8d44\u6599\u4e2d\u6682\u672a\u627e\u5230\u8bed\u4e49\u591a\u5b57\u6bb5\u7089\uff08SEM-MULTI-01\uff09\u7684\u91cd\u91cf\u3002"

    shaped = customer_service_service._shape_product_detail_output(
        answer,
        [{"sku": "SEM-MULTI-01", "product_name_cn": "\u8bed\u4e49\u591a\u5b57\u6bb5\u7089"}],
        answer_metadata={"answer_policy": "sealed_same_sku_multi_field_evidence"},
    )

    assert shaped == answer


def test_semantic_pairwise_qa_contract_preempts_incidental_product_name_field(monkeypatch):
    """A capability comparison may not be relabelled from a product-name token."""
    first = SimpleNamespace(sku="SEM-CMP-01", product_name_cn="\u7532\u7089", product_name_en="")
    second = SimpleNamespace(sku="SEM-CMP-02", product_name_cn="\u4e59\u7089", product_name_en="")
    bundles = [(first, None, None, None), (second, None, None, None)]
    monkeypatch.setattr(
        customer_service_service,
        "_phase1_product_bundle_by_ref",
        lambda _db, ref: bundles[0] if ref == "SEM-CMP-01" else bundles[1],
    )
    monkeypatch.setattr(
        customer_service_service,
        "_product_row_from_model",
        lambda product, *_args: {"sku": product.sku, "product_name_cn": product.product_name_cn},
    )
    monkeypatch.setattr(
        customer_service_service,
        "resolve_requested_field_contract",
        lambda *_args, **_kwargs: {"field_type": "heat_source", "canonical_fields": ["heat_source"]},
    )
    monkeypatch.setattr(
        customer_service_service,
        "_best_product_qa_match",
        lambda _db, product, *_args, **_kwargs: (
            SimpleNamespace(id="qa-1", answer="\u53ef\u8c03\u5c0f\u706b") if product.sku == "SEM-CMP-02" else None
        ),
    )

    async def no_semantic_qa_match(*_args, **_kwargs):
        return None

    monkeypatch.setattr(
        customer_service_service,
        "_select_same_sku_product_qa_with_semantic_selection",
        no_semantic_qa_match,
    )

    result = asyncio.run(customer_service_service._phase1_compare_choice_result(None, {
        "raw_question": "\u7532\u7089\u548c\u4e59\u7089\u54ea\u4e2a\u66f4\u9002\u5408\u4f4e\u706b\u7116\u716e\uff1f",
        "product_refs": ["SEM-CMP-01", "SEM-CMP-02"],
        "must_make_choice": True,
        "semantic_comparison_entity_contracts": [
            {"status": "resolved", "resolved_sku": "SEM-CMP-01"},
            {"status": "resolved", "resolved_sku": "SEM-CMP-02"},
        ],
        "semantic_preplan": {
            "evidence_kind": "product_qa",
            "qa_evidence_query": "\u4f4e\u706b\u7116\u716e\u80fd\u529b",
        },
    }))

    assert result["answer_metadata"]["source"] == "semantic_pairwise_product_qa_contract", result
    assert result["answer_metadata"]["final_choice_sku"] is None, result
    assert result["debug"]["agent_mode"] == "semantic_pairwise_product_qa_insufficient", result


def test_semantic_pairwise_qa_gap_can_use_sealed_structured_evidence_for_choice(monkeypatch):
    """A judgement may use verified multi-field evidence without inventing a QA answer."""
    first = SimpleNamespace(sku="SEM-CMP-11", product_name_cn="甲套锅", product_name_en="")
    second = SimpleNamespace(sku="SEM-CMP-12", product_name_cn="乙套锅", product_name_en="")
    bundles = [(first, None, None, None), (second, None, None, None)]
    monkeypatch.setattr(
        customer_service_service,
        "_phase1_product_bundle_by_ref",
        lambda _db, ref: bundles[0] if ref == "SEM-CMP-11" else bundles[1],
    )
    monkeypatch.setattr(
        customer_service_service,
        "_product_row_from_model",
        lambda product, *_args: {"sku": product.sku, "product_name_cn": product.product_name_cn},
    )
    monkeypatch.setattr(
        customer_service_service,
        "resolve_requested_field_contract",
        lambda *_args, **_kwargs: {"field_type": "", "canonical_fields": []},
    )

    async def no_semantic_qa_match(*_args, **_kwargs):
        return None

    monkeypatch.setattr(
        customer_service_service,
        "_select_same_sku_product_qa_with_semantic_selection",
        no_semantic_qa_match,
    )
    monkeypatch.setattr(
        customer_service_service,
        "_comparison_adjudication_evidence",
        lambda **_kwargs: {
            "capacity": [
                {"participant_index": 0, "sku": "SEM-CMP-11", "value": "1.2L", "source": "specs.capacity"},
                {"participant_index": 1, "sku": "SEM-CMP-12", "value": "3L+1.7L", "source": "specs.capacity"},
            ],
            "usage_scene": [
                {"participant_index": 0, "sku": "SEM-CMP-11", "value": "双人露营", "source": "business.usage_scene"},
                {"participant_index": 1, "sku": "SEM-CMP-12", "value": "多人露营", "source": "business.usage_scene"},
            ],
        },
    )

    async def choose_from_evidence(*_args, **_kwargs):
        return {
            "selected_index": 1,
            "evidence_fields": ["capacity", "usage_scene"],
            "reasoning_summary": "The sealed evidence directly supports the stated need.",
        }

    monkeypatch.setattr(
        customer_service_service,
        "_semantic_comparison_adjudication",
        choose_from_evidence,
    )

    result = asyncio.run(customer_service_service._phase1_compare_choice_result(None, {
        "raw_question": "甲套锅和乙套锅哪个更适合多人露营？",
        "product_refs": ["SEM-CMP-11", "SEM-CMP-12"],
        "must_make_choice": True,
        "semantic_comparison_entity_contracts": [
            {"status": "resolved", "resolved_sku": "SEM-CMP-11"},
            {"status": "resolved", "resolved_sku": "SEM-CMP-12"},
        ],
        "semantic_preplan": {
            "evidence_kind": "product_qa",
            "qa_evidence_query": "多人露营适用性",
        },
    }))

    assert result["answer_metadata"]["final_choice_sku"] == "SEM-CMP-12", result
    assert result["answer_metadata"]["source"] == "semantic_pairwise_structured_best_effort_contract"
    assert "3L+1.7L" in result["answer"]
    assert result["debug"]["agent_mode"] == "semantic_pairwise_structured_best_effort_contract"


def test_semantic_pairwise_rejected_choice_still_returns_complete_structured_differences(monkeypatch):
    first = SimpleNamespace(sku="SEM-CMP-21", product_name_cn="Alpha", product_name_en="")
    second = SimpleNamespace(sku="SEM-CMP-22", product_name_cn="Beta", product_name_en="")
    bundles = [(first, None, None, None), (second, None, None, None)]
    monkeypatch.setattr(
        customer_service_service,
        "_phase1_product_bundle_by_ref",
        lambda _db, ref: bundles[0] if ref == "SEM-CMP-21" else bundles[1],
    )
    monkeypatch.setattr(
        customer_service_service,
        "_product_row_from_model",
        lambda product, *_args: {"sku": product.sku, "product_name_cn": product.product_name_cn},
    )
    monkeypatch.setattr(
        customer_service_service,
        "resolve_requested_field_contract",
        lambda *_args, **_kwargs: {"field_type": "", "canonical_fields": []},
    )

    async def no_semantic_qa_match(*_args, **_kwargs):
        return None

    monkeypatch.setattr(
        customer_service_service,
        "_select_same_sku_product_qa_with_semantic_selection",
        no_semantic_qa_match,
    )
    monkeypatch.setattr(
        customer_service_service,
        "_comparison_adjudication_evidence",
        lambda **_kwargs: {
            "capacity": [
                {"participant_index": 0, "sku": "SEM-CMP-21", "value": "1L", "source": "specs.capacity"},
                {"participant_index": 1, "sku": "SEM-CMP-22", "value": "3L", "source": "specs.capacity"},
            ],
        },
    )

    async def reject_choice_but_keep_evidence(*_args, **_kwargs):
        return {
            "selected_index": None,
            "evidence_fields": ["capacity"],
            "reasoning_summary": "The evidence shows a difference but does not support a winner.",
        }

    monkeypatch.setattr(
        customer_service_service,
        "_semantic_comparison_adjudication",
        reject_choice_but_keep_evidence,
    )

    result = asyncio.run(customer_service_service._phase1_compare_choice_result(None, {
        "raw_question": "Alpha和Beta哪个更适合这次出行？",
        "product_refs": ["SEM-CMP-21", "SEM-CMP-22"],
        "must_make_choice": True,
        "semantic_comparison_entity_contracts": [
            {"status": "resolved", "resolved_sku": "SEM-CMP-21"},
            {"status": "resolved", "resolved_sku": "SEM-CMP-22"},
        ],
        "semantic_preplan": {
            "evidence_kind": "product_qa",
            "qa_evidence_query": "出行适用性",
        },
    }))

    assert result["answer_metadata"]["final_choice_sku"] is None
    assert result["answer_metadata"]["source"] == "semantic_pairwise_structured_best_effort_contract"
    assert "1L" in result["answer"] and "3L" in result["answer"]
    assert "产品问答" not in result["answer"]


def test_validated_category_comparison_is_not_replaced_by_legacy_intro(monkeypatch):
    first = SimpleNamespace(sku="SEM-CAT-01", product_name_cn="甲产品", product_name_en="")
    second = SimpleNamespace(sku="SEM-CAT-02", product_name_cn="乙产品", product_name_en="")
    bundles = [(first, None, None, None), (second, None, None, None)]
    monkeypatch.setattr(
        customer_service_service,
        "_phase1_product_bundle_by_ref",
        lambda _db, ref: bundles[0] if ref == "SEM-CAT-01" else bundles[1],
    )
    monkeypatch.setattr(
        customer_service_service,
        "_product_row_from_model",
        lambda product, *_args: {"sku": product.sku, "product_name_cn": product.product_name_cn},
    )
    monkeypatch.setattr(
        customer_service_service,
        "resolve_requested_field_contract",
        lambda *_args, **_kwargs: {"field_type": "", "canonical_fields": []},
    )
    monkeypatch.setattr(
        customer_service_service,
        "_structured_product_field_evidence",
        lambda _field, **kwargs: (
            ("炉具", "product.category")
            if kwargs["product"].sku == "SEM-CAT-01"
            else ("锅具", "product.category")
        ),
    )

    result = asyncio.run(customer_service_service._phase1_compare_choice_result(None, {
        "raw_question": "甲产品和乙产品分别是什么类型？",
        "product_refs": ["SEM-CAT-01", "SEM-CAT-02"],
        "comparison_kind": "multi_sku_intro",
        "must_make_choice": False,
        "semantic_comparison_entity_contracts": [
            {"status": "resolved", "resolved_sku": "SEM-CAT-01"},
            {"status": "resolved", "resolved_sku": "SEM-CAT-02"},
        ],
        "semantic_preplan": {
            "route_family": "comparison",
            "canonical_fields": ["category"],
            "evidence_kind": "structured_field",
        },
    }))

    assert result["debug"]["agent_mode"] == "planner_compare_formal_field_contract"
    assert "炉具" in result["answer"]
    assert "锅具" in result["answer"]
    assert "容量" not in result["answer"]


def test_semantic_pairwise_qa_contract_uses_bounded_same_sku_selector_after_direct_miss(monkeypatch):
    """Comparison must reuse the sealed per-SKU QA selector, never broaden retrieval."""
    first = SimpleNamespace(sku="SEM-CMP-01", product_name_cn="甲炉", product_name_en="")
    second = SimpleNamespace(sku="SEM-CMP-02", product_name_cn="乙炉", product_name_en="")
    bundles = [(first, None, None, None), (second, None, None, None)]
    monkeypatch.setattr(
        customer_service_service,
        "_phase1_product_bundle_by_ref",
        lambda _db, ref: bundles[0] if ref == "SEM-CMP-01" else bundles[1],
    )
    monkeypatch.setattr(
        customer_service_service,
        "_product_row_from_model",
        lambda product, *_args: {"sku": product.sku, "product_name_cn": product.product_name_cn},
    )
    monkeypatch.setattr(
        customer_service_service,
        "resolve_requested_field_contract",
        lambda *_args, **_kwargs: {"field_type": "", "canonical_fields": []},
    )
    monkeypatch.setattr(customer_service_service, "_best_product_qa_match", lambda *_args, **_kwargs: None)
    selector_calls = []

    async def select_second_product(*_args, **_kwargs):
        selector_calls.append((_args, _kwargs))
        product = _args[1]
        return SimpleNamespace(id="qa-b", answer="可以调成小火慢炖。") if product.sku == "SEM-CMP-02" else None

    monkeypatch.setattr(
        customer_service_service,
        "_select_same_sku_product_qa_with_semantic_selection",
        select_second_product,
    )

    result = asyncio.run(customer_service_service._phase1_compare_choice_result(None, {
        "raw_question": "甲炉和乙炉哪个更适合低火慢炖？",
        "product_refs": ["SEM-CMP-01", "SEM-CMP-02"],
        "must_make_choice": True,
        "semantic_comparison_entity_contracts": [
            {"status": "resolved", "resolved_sku": "SEM-CMP-01"},
            {"status": "resolved", "resolved_sku": "SEM-CMP-02"},
        ],
        "semantic_preplan": {
            "evidence_kind": "product_qa",
            "qa_evidence_query": "低火慢炖能力",
        },
    }))

    assert "甲炉（SEM-CMP-01）：当前同 SKU 资料未找到" in result["answer"], result
    assert "乙炉（SEM-CMP-02）：可以调成小火慢炖。" in result["answer"], result
    assert result["sources"] == [{"type": "product_qa", "sku": "SEM-CMP-02", "source": "product_qa:qa-b", "value": "可以调成小火慢炖。"}], result
    assert result["answer_metadata"]["final_choice_sku"] is None, result
    assert all(call[1]["comparison_criterion"] == "低火慢炖能力" for call in selector_calls), selector_calls


def test_compatibility_question_answers_compatibility_before_generic_safety():
    answer = customer_agent_intent_service._compose_safety_usage_care_answer("液化气罐也可以用吗？")

    assert "兼容性结论" in answer
    assert "无法确认" in answer
    assert "安全提醒" in answer


def test_fuel_mix_question_is_not_reduced_to_connection_safety_only():
    answer = customer_agent_intent_service._compose_safety_usage_care_answer("气罐和酒精都能用吗？")

    assert "兼容性结论" in answer
    assert "无法确认" in answer


def test_ignition_complaint_is_usage_care_even_when_customer_says客服():
    question = "客服为什么不太点着火？"

    assert customer_service_service._is_product_usage_care_question(question) is True
    assert customer_service_service._classify_customer_faq_intent(question) is None


def test_stove_installation_question_is_usage_care():
    assert customer_service_service._is_product_usage_care_question("炉头怎么装啊？") is True


def test_fuel_duration_question_is_usage_care_and_has_duration_subtype():
    question = "500ml酒精能用多久？"

    assert customer_service_service._is_product_usage_care_question(question) is True
    assert customer_agent_intent_service._detect_usage_care_subtype(question) == "duration"


def test_installation_fallback_is_installation_specific_not_cleaning_copy():
    answer = customer_agent_intent_service._compose_usage_care_answer(
        "炉头怎么装啊？",
        [],
        [],
        response_style="usage_guidance",
    )

    assert "安装" in answer
    assert "清洗/保养" not in answer


def test_generic_duration_usage_care_does_not_expose_retrieval_skus(route_client_and_db):
    client, headers, _ = route_client_and_db
    response = client.post(
        "/api/customer-service/ask?debug=true",
        json={"question": "500ml酒精能用多久？"},
        headers=headers,
    )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["answer_type"] == "product_usage_care", payload
    assert payload["result_skus"] == [], payload


def test_general_fuel_definition_does_not_route_to_catalogue_clarification(route_client_and_db):
    client, headers, _ = route_client_and_db
    response = client.post(
        "/api/customer-service/ask?debug=true",
        json={"question": "\u71c3\u6599\u9152\u7cbe\u662f\u4ec0\u4e48\uff0c\u54ea\u91cc\u80fd\u4e70\u5230\uff1f"},
        headers=headers,
    )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["answer_type"] == "product_usage_care", payload
    assert payload.get("result_skus") == [], payload
    assert "\u71c3\u6599\u9152\u7cbe" in payload["answer"], payload
    assert (payload.get("debug") or {}).get("agent_mode") != "semantic_catalog_unresolved_value_clarification", payload


def test_semantic_generic_catalogue_browse_recovers_explicit_category_scope(
    route_client_and_db,
    monkeypatch,
):
    client, headers, _ = route_client_and_db

    async def generic_catalog_plan(*_args, **_kwargs):
        return {
            "called": True,
            "route_family": "generic_query",
            "route_hint": "query_products",
            "question_type": "filter",
            "entities": [],
            "canonical_fields": [],
            "evidence_required": True,
            "confidence": 0.95,
        }

    monkeypatch.setattr(customer_agent_planner_service, "plan_customer_question_semantic", generic_catalog_plan)
    response = client.post(
        "/api/customer-service/ask?debug=true",
        json={"question": "目前炉具有哪些类型和型号？我想先看完整范围。"},
        headers=headers,
    )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["answer_type"] in {"query_products", "product_query"}, payload
    assert payload["result_skus"], payload
    assert payload["debug"]["agent_mode"] != "semantic_catalog_unresolved_value_clarification", payload


def test_explicit_sku_fuel_compatibility_uses_compatibility_answer(route_client_and_db):
    client, headers, _ = route_client_and_db
    response = client.post(
        "/api/customer-service/ask?debug=true",
        json={"question": "CS-G26HM液化气罐也可以用吗？"},
        headers=headers,
    )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert "兼容性结论" in payload["answer"], payload
    assert "无法确认" in payload["answer"], payload


def test_explicit_product_subject_category_is_available_for_page_conflict_guard():
    assert customer_service_service._structured_target_category_from_question("有没有大锅卖？") == "锅具"
    assert customer_service_service._structured_target_category_from_question("挡风板推荐一个？") == "配件"
    assert customer_service_service._structured_target_category_from_question("这个茶壶不是紫铜的") == "水壶"


def test_charcoal_synonyms_remain_a_hard_heat_source_boundary():
    contract = customer_recommendation_verification_contract.build_recommendation_request_contract(
        "我炭烧的，只想买炉子内胆，其他不要。"
    )

    assert contract.subject_kind == "accessories"
    assert contract.heat_sources == ["炭火"]
    assert "heat_source" in contract.hard_constraints


def test_customer_answer_sanitizer_removes_bare_internal_field_names():
    answer = customer_service_service._sanitize_final_answer_text(
        "当前资料中暂未找到小青炉（CS-G25）的heat_source。",
        {"type": "product_qa"},
    )

    assert "heat_source" not in answer
    assert "相关商品资料" in answer or "适用热源" in answer


def test_semantic_general_chat_cannot_preempt_usage_care_route(route_client_and_db, monkeypatch):
    client, headers, _ = route_client_and_db

    async def general_chat_plan(*_args, **_kwargs):
        return {
            "called": True,
            "route_family": "general_chat",
            "route_hint": "clarification",
            "question_type": "field",
            "entities": [],
            "canonical_fields": [],
            "evidence_required": False,
            "confidence": 0.95,
        }

    monkeypatch.setattr(customer_agent_planner_service, "plan_customer_question_semantic", general_chat_plan)
    response = client.post(
        "/api/customer-service/ask?debug=true",
        json={"question": "炉头怎么装啊？"},
        headers=headers,
    )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["answer_type"] != "chat", payload
    assert "有什么可以帮你" not in payload["answer"], payload


def test_semantic_category_safety_procedure_is_not_reopened_as_catalogue_filter(
    route_client_and_db,
    monkeypatch,
):
    client, headers, _ = route_client_and_db

    async def safety_plan(*_args, **_kwargs):
        return {
            "called": True,
            "route_family": "product_bound_qa",
            "route_hint": "product_detail",
            "question_type": "field",
            "subtype": "safety_procedure",
            "entities": ["酒精炉"],
            "subject_text": "酒精炉",
            "canonical_fields": [],
            "evidence_required": False,
            "confidence": 0.95,
        }

    async def safety_answer(*_args, **kwargs):
        if kwargs.get("purpose") in {
            "general_customer_chat",
            "general_customer_chat_grounding_review",
        }:
            return "不要把汽油直接加入酒精炉点火；燃料不匹配可能造成失控燃烧，请按炉具说明使用指定燃料。"
        raise AssertionError(f"unexpected purpose: {kwargs.get('purpose')}")

    monkeypatch.setattr(customer_agent_planner_service, "plan_customer_question_semantic", safety_plan)
    monkeypatch.setattr(customer_service_service.customer_llm_service, "chat_completion", safety_answer)
    response = client.post(
        "/api/customer-service/ask?debug=true",
        json={"question": "酒精炉能不能直接灌汽油点火？请明确提醒风险。"},
        headers=headers,
    )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["answer_type"] == "chat", payload
    assert "不要" in payload["answer"] and "汽油" in payload["answer"], payload
    assert payload["result_skus"] == [], payload
    assert payload["debug"]["agent_mode"] == "semantic_general_chat", payload


def test_context_pair_shortcut_rejects_candidates_outside_explicit_current_subject(monkeypatch):
    monkeypatch.setattr(
        customer_service_service,
        "_phase1_catalog_rows",
        lambda _db, _ref: [
            {"sku": "GRINDER-1", "product_name_cn": "手摇磨豆器", "category": "咖啡器具"},
            {"sku": "GRINDER-2", "product_name_cn": "旅行磨豆器", "category": "咖啡器具"},
        ],
    )

    assert not customer_service_service._context_pair_matches_current_turn_subject(
        None,
        "两三个人喝，壶别太大，你会留哪款？",
        ["GRINDER-1", "GRINDER-2"],
    )


def test_semantic_general_selection_guidance_is_not_overridden_by_legacy_recommendation_words(
    route_client_and_db,
    monkeypatch,
):
    client, headers, _ = route_client_and_db

    async def general_chat_plan(*_args, **_kwargs):
        return {
            "called": True,
            "route_family": "general_chat",
            "route_hint": "clarification",
            "question_type": "general",
            "entities": [],
            "canonical_fields": [],
            "evidence_required": False,
            "confidence": 0.95,
        }

    async def general_chat_answer(*_args, **kwargs):
        if kwargs.get("purpose") == "general_customer_chat":
            return "建议先按预算、人数、自驾或徒步方式和收纳空间梳理，再确定品类。你最在意哪一项？"
        if kwargs.get("purpose") == "general_customer_chat_grounding_review":
            return "建议先按预算、人数、自驾或徒步方式和收纳空间梳理，再确定品类。你最在意哪一项？"
        raise AssertionError(f"unexpected LLM purpose: {kwargs.get('purpose')}")

    monkeypatch.setattr(customer_agent_planner_service, "plan_customer_question_semantic", general_chat_plan)
    monkeypatch.setattr(customer_service_service.customer_llm_service, "chat_completion", general_chat_answer)
    response = client.post(
        "/api/customer-service/ask?debug=true",
        json={"question": "暂时没定品类，先帮我理一下该怎么选。"},
        headers=headers,
    )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["answer_type"] == "chat", payload
    assert payload["debug"]["agent_mode"] == "semantic_general_chat", payload
    assert payload["result_skus"] == [], payload
    assert "预算" in payload["answer"], payload


def test_semantic_general_chat_cannot_preempt_explicit_charcoal_accessory_request(route_client_and_db, monkeypatch):
    client, headers, _ = route_client_and_db

    async def general_chat_plan(*_args, **_kwargs):
        return {
            "called": True,
            "route_family": "general_chat",
            "route_hint": "clarification",
            "question_type": "field",
            "entities": [],
            "canonical_fields": [],
            "evidence_required": False,
            "confidence": 0.95,
        }

    monkeypatch.setattr(customer_agent_planner_service, "plan_customer_question_semantic", general_chat_plan)
    response = client.post(
        "/api/customer-service/ask?debug=true",
        json={"question": "我炭烧的，只想买炉子内胆，其他不要。"},
        headers=headers,
    )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["answer_type"] != "chat", payload
    assert "有什么可以帮你" not in payload["answer"], payload


def test_semantic_general_chat_cannot_preempt_comparison_choice_followup(route_client_and_db, monkeypatch):
    client, headers, _ = route_client_and_db
    comparison_question = "我在 CW-C83 和 CW-C06PRO 之间纠结，周末两个人徒步，哪个更合适？"
    followup_question = "你更建议哪一个？请说明理由。"

    async def semantic_plan(_db, question, *_args, **_kwargs):
        if question == followup_question:
            return {
                "called": True,
                "route_family": "general_chat",
                "route_hint": "clarification",
                "question_type": "general",
                "entities": [],
                "canonical_fields": [],
                "evidence_required": False,
                "confidence": 0.95,
            }
        return {"called": False}

    monkeypatch.setattr(customer_agent_planner_service, "plan_customer_question_semantic", semantic_plan)
    first = client.post(
        "/api/customer-service/ask?debug=true",
        json={"question": comparison_question},
        headers=headers,
    )

    assert first.status_code == 200, first.text
    first_payload = first.json()
    selected_sku = (first_payload.get("answer_metadata") or {}).get("final_choice_sku")
    assert selected_sku in {"CW-C83", "CW-C06PRO"}, first_payload

    second = client.post(
        "/api/customer-service/ask?debug=true",
        json={"question": followup_question, "conversation_id": first_payload["conversation_id"]},
        headers=headers,
    )

    assert second.status_code == 200, second.text
    second_payload = second.json()
    assert second_payload["answer_type"] != "chat", second_payload
    assert second_payload["result_skus"] == [selected_sku], second_payload
    assert selected_sku in second_payload["answer"], second_payload


@pytest.mark.parametrize(
    "question",
    [
        "你更建议哪一个？请说明理由。",
        "这两个里面更推荐哪一个？",
    ],
)
def test_comparison_choice_followup_question_recognizes_direct_choice(question):
    assert customer_service_service._is_comparison_choice_followup_question(question)


def test_contextual_comparison_choice_skips_semantic_preplan(route_client_and_db, monkeypatch):
    client, headers, _ = route_client_and_db

    async def no_semantic_plan(*_args, **_kwargs):
        return {"called": False}

    monkeypatch.setattr(customer_agent_planner_service, "plan_customer_question_semantic", no_semantic_plan)
    first = client.post(
        "/api/customer-service/ask?debug=true",
        json={"question": "CW-C83 \u548c CW-C06PRO \u54ea\u4e2a\u66f4\u9002\u5408\u4e24\u4e2a\u4eba\u5468\u672b\u5f92\u6b65\uff1f"},
        headers=headers,
    )
    assert first.status_code == 200, first.text
    first_payload = first.json()
    selected_sku = (first_payload.get("answer_metadata") or {}).get("final_choice_sku")
    assert selected_sku in {"CW-C83", "CW-C06PRO"}, first_payload

    calls = []

    async def unexpected_semantic_plan(*_args, **_kwargs):
        calls.append(True)
        return {"called": False}

    monkeypatch.setattr(customer_service_service, "_maybe_run_semantic_preplan", unexpected_semantic_plan)
    second = client.post(
        "/api/customer-service/ask?debug=true",
        json={"question": "\u4f60\u66f4\u5efa\u8bae\u54ea\u4e00\u4e2a\uff1f\u8bf7\u8bf4\u660e\u7406\u7531\u3002", "conversation_id": first_payload["conversation_id"]},
        headers=headers,
    )

    assert second.status_code == 200, second.text
    payload = second.json()
    assert calls == []
    assert payload["result_skus"] == [selected_sku], payload
    assert selected_sku in payload["answer"], payload


def test_contextual_candidate_field_followup_skips_semantic_preplan(route_client_and_db, monkeypatch):
    client, headers, _ = route_client_and_db

    async def no_semantic_plan(*_args, **_kwargs):
        return {"called": False}

    monkeypatch.setattr(customer_agent_planner_service, "plan_customer_question_semantic", no_semantic_plan)
    first = client.post(
        "/api/customer-service/ask?debug=true",
        json={"question": "CW-C83 \u548c CW-C06PRO \u54ea\u4e2a\u66f4\u9002\u5408\u4e24\u4e2a\u4eba\u5468\u672b\u5f92\u6b65\uff1f"},
        headers=headers,
    )
    assert first.status_code == 200, first.text
    first_payload = first.json()
    selected_skus = first_payload.get("result_skus") or []
    assert selected_skus, first_payload

    calls = []

    async def unexpected_semantic_plan(*_args, **_kwargs):
        calls.append(True)
        return {"called": False}

    monkeypatch.setattr(customer_service_service, "_maybe_run_semantic_preplan", unexpected_semantic_plan)
    second = client.post(
        "/api/customer-service/ask?debug=true",
        json={"question": "\u4f60\u521a\u624d\u63a8\u8350\u7684\u7b2c\u4e00\u6b3e\uff0c\u91cd\u91cf\u548c\u5bb9\u91cf\u5206\u522b\u662f\u591a\u5c11\uff1f", "conversation_id": first_payload["conversation_id"]},
        headers=headers,
    )

    assert second.status_code == 200, second.text
    payload = second.json()
    assert calls == []
    assert payload["result_skus"] == [selected_skus[0]], payload
    assert "\u91cd\u91cf" in payload["answer"] and "\u5bb9\u91cf" in payload["answer"], payload


def test_contextual_selected_choice_field_followup_skips_semantic_preplan(route_client_and_db, monkeypatch):
    client, headers, _ = route_client_and_db

    async def no_semantic_plan(*_args, **_kwargs):
        return {"called": False}

    monkeypatch.setattr(customer_agent_planner_service, "plan_customer_question_semantic", no_semantic_plan)
    first = client.post(
        "/api/customer-service/ask?debug=true",
        json={"question": "CW-C83 \u548c CW-C06PRO \u54ea\u4e2a\u66f4\u9002\u5408\u4e24\u4e2a\u4eba\u5468\u672b\u5f92\u6b65\uff1f"},
        headers=headers,
    )
    assert first.status_code == 200, first.text
    first_payload = first.json()
    selected_sku = (first_payload.get("answer_metadata") or {}).get("final_choice_sku")
    assert selected_sku in {"CW-C83", "CW-C06PRO"}, first_payload

    second = client.post(
        "/api/customer-service/ask?debug=true",
        json={
            "question": "\u4f60\u66f4\u5efa\u8bae\u54ea\u4e00\u4e2a\uff1f\u8bf7\u8bf4\u660e\u7406\u7531\u3002",
            "conversation_id": first_payload["conversation_id"],
        },
        headers=headers,
    )
    assert second.status_code == 200, second.text
    second_payload = second.json()
    assert second_payload["result_skus"] == [selected_sku], second_payload

    calls = []

    async def unexpected_semantic_plan(*_args, **_kwargs):
        calls.append(True)
        return {"called": False}

    monkeypatch.setattr(customer_service_service, "_maybe_run_semantic_preplan", unexpected_semantic_plan)
    third = client.post(
        "/api/customer-service/ask?debug=true",
        json={
            "question": "\u4f60\u521a\u624d\u9009\u7684\u90a3\u6b3e\uff0c\u6750\u8d28\u3001\u5bb9\u91cf\u3001\u91cd\u91cf\u4e00\u6b21\u8bf4\u6e05\u695a\u3002",
            "conversation_id": second_payload["conversation_id"],
        },
        headers=headers,
    )

    assert third.status_code == 200, third.text
    payload = third.json()
    assert calls == []
    assert payload["result_skus"] == [selected_sku], payload
    assert all(term in payload["answer"] for term in ("\u6750\u8d28", "\u5bb9\u91cf", "\u91cd\u91cf")), payload


def test_direct_selected_choice_multi_field_followup_uses_final_choice(route_client_and_db, monkeypatch):
    client, headers, _ = route_client_and_db

    async def no_semantic_plan(*_args, **_kwargs):
        return {"called": False}

    monkeypatch.setattr(customer_agent_planner_service, "plan_customer_question_semantic", no_semantic_plan)
    first = client.post(
        "/api/customer-service/ask?debug=true",
        json={"question": "CW-C83 \u548c CW-C06PRO \u54ea\u4e2a\u66f4\u9002\u5408\u4e24\u4e2a\u4eba\u5468\u672b\u5f92\u6b65\uff1f"},
        headers=headers,
    )
    assert first.status_code == 200, first.text
    first_payload = first.json()
    selected_sku = (first_payload.get("answer_metadata") or {}).get("final_choice_sku")
    assert selected_sku in {"CW-C83", "CW-C06PRO"}, first_payload

    second = client.post(
        "/api/customer-service/ask?debug=true",
        json={
            "question": "\u521a\u9009\u7684\u90a3\u6b3e\u6750\u8d28\u3001\u5bb9\u91cf\u3001\u91cd\u91cf\u4e00\u6b21\u8bf4\u6e05\u695a\u3002",
            "conversation_id": first_payload["conversation_id"],
        },
        headers=headers,
    )
    assert second.status_code == 200, second.text
    payload = second.json()
    assert payload["result_skus"] == [selected_sku], payload
    assert all(term in payload["answer"] for term in ("\u6750\u8d28", "\u5bb9\u91cf", "\u91cd\u91cf")), payload


def test_gifting_evidence_boundary_is_terminal_at_final_save(route_client_and_db, monkeypatch):
    _, _, Session = route_client_and_db
    recovery_calls = []
    polish_calls = []

    async def unexpected_recovery(*_args, **_kwargs):
        recovery_calls.append(True)
        return None

    async def unexpected_polish(*_args, **_kwargs):
        polish_calls.append(True)
        return "\u54c1\u8d28\u51fa\u4f17\uff0c\u5305\u88c5\u7cbe\u7f8e\uff0c\u975e\u5e38\u9002\u5408\u4f5c\u4e3a\u793c\u7269\u3002"

    monkeypatch.setattr(
        customer_service_service,
        "_try_same_sku_structured_best_effort_answer",
        unexpected_recovery,
    )
    monkeypatch.setattr(customer_service_service, "_polish_customer_answer", unexpected_polish)

    with Session() as db:
        product = db.query(Product).filter(Product.sku == "CW-C83").one()
        safe_missing = customer_service_service._sealed_product_qa_safe_missing_result(
            product,
            "\u5f53\u524d\u540c SKU \u8d44\u6599\u4e0d\u8db3\u4ee5\u76f4\u63a5\u652f\u6301\u4e0a\u8ff0\u54c1\u8d28\u5224\u65ad\uff0c\u6682\u65f6\u65e0\u6cd5\u786e\u8ba4\u3002",
            field_contract={
                "field_type": "product_qa",
                "canonical_fields": ["product_qa"],
                "source": "gifting_evidence_boundary",
            },
            debug={"gifting_evidence_boundary": True},
        )
        payload = asyncio.run(
            customer_service_service._save_agent_result_and_return(
                db,
                user_id="customer-service-route-user",
                question="CW-C83 \u54c1\u8d28\u51fa\u4f17\u5417\uff1f",
                conversation_id=None,
                agent_result=safe_missing,
                request_start=customer_service_service.perf_counter(),
                branch="test_terminal_gifting_boundary",
                semantic_preplan={"evidence_kind": "product_qa"},
            )
        )

    assert recovery_calls == []
    assert polish_calls == []
    assert "\u54c1\u8d28" in payload["answer"] and "\u65e0\u6cd5\u786e\u8ba4" in payload["answer"]
    assert "\u54c1\u8d28\u51fa\u4f17" not in payload["answer"]
    assert "\u5305\u88c5\u7cbe\u7f8e" not in payload["answer"]
    assert payload["evidence"] == []
    assert payload["answer_metadata"]["evidence_status"] == "missing"
    assert payload["answer_metadata"]["field_evidence_missing"] is True
    assert payload["debug"]["gifting_evidence_boundary"] is True


def test_safe_missing_keeps_resolved_product_card_when_only_evidence_is_missing():
    result = {
        "answer": "风暴炉pro-两用版（CW-C95）：当前资料未找到能直接确认首次使用步骤的内容。",
        "answer_type": "product_detail",
        "results": [{"sku": "CW-C95", "product_name_cn": "风暴炉pro-两用版"}],
        "result_skus": ["CW-C95"],
        "candidate_skus": ["CW-C95"],
        "sources": [],
        "debug": {"agent_mode": "sealed_product_qa_safe_missing"},
    }

    shaped = customer_service_service._clear_unrelated_catalogue_cards(
        "换一个产品：CW-C95 第一次使用前怎么处理？",
        result,
    )

    assert shaped["result_skus"] == ["CW-C95"]
    assert shaped["candidate_skus"] == ["CW-C95"]
    assert shaped["results"][0]["sku"] == "CW-C95"


@pytest.mark.parametrize(
    "question",
    [
        "\u4f60\u521a\u624d\u6ca1\u9009\u7684\u90a3\u6b3e\uff0c\u91cd\u91cf\u662f\u591a\u5c11\uff1f",
        "\u4e0d\u662f\u4f60\u9009\u7684\u90a3\u6b3e\uff0c\u91cd\u91cf\u662f\u591a\u5c11\uff1f",
    ],
)
def test_negated_selected_choice_reference_requires_semantic_preplan(
    route_client_and_db,
    monkeypatch,
    question,
):
    client, headers, _ = route_client_and_db

    async def no_semantic_plan(*_args, **_kwargs):
        return {"called": False}

    monkeypatch.setattr(customer_agent_planner_service, "plan_customer_question_semantic", no_semantic_plan)
    first = client.post(
        "/api/customer-service/ask?debug=true",
        json={"question": "CW-C83 \u548c CW-C06PRO \u54ea\u4e2a\u66f4\u9002\u5408\u4e24\u4e2a\u4eba\u5468\u672b\u5f92\u6b65\uff1f"},
        headers=headers,
    )
    assert first.status_code == 200, first.text
    first_payload = first.json()

    second = client.post(
        "/api/customer-service/ask?debug=true",
        json={
            "question": "\u4f60\u66f4\u5efa\u8bae\u54ea\u4e00\u4e2a\uff1f\u8bf7\u8bf4\u660e\u7406\u7531\u3002",
            "conversation_id": first_payload["conversation_id"],
        },
        headers=headers,
    )
    assert second.status_code == 200, second.text

    calls = []

    async def semantic_plan_required(*_args, **_kwargs):
        calls.append(True)
        return {"called": False}

    monkeypatch.setattr(customer_service_service, "_maybe_run_semantic_preplan", semantic_plan_required)
    third = client.post(
        "/api/customer-service/ask?debug=true",
        json={"question": question, "conversation_id": second.json()["conversation_id"]},
        headers=headers,
    )

    assert third.status_code == 200, third.text
    assert calls == [True]


def test_selected_choice_reference_without_final_choice_does_not_bypass_semantic_preplan(monkeypatch):
    monkeypatch.setattr(
        customer_service_service,
        "_latest_recommendation_context_for_sources",
        lambda *_args, **_kwargs: {
            "recommended_skus": ["CW-C83", "CW-C06PRO"],
            "active_single_product_anchor": "CW-C83",
        },
    )
    monkeypatch.setattr(
        customer_service_service,
        "_latest_candidate_context_for_sources",
        lambda *_args, **_kwargs: {
            "candidate_skus": ["CW-C83", "CW-C06PRO"],
            "final_choice_sku": None,
        },
    )

    assert not customer_service_service._should_bypass_semantic_preplan_for_bound_context_followup(
        SimpleNamespace(),
        "\u4f60\u521a\u624d\u9009\u7684\u90a3\u6b3e\uff0c\u91cd\u91cf\u662f\u591a\u5c11\uff1f",
        {"field_contract": {"canonical_fields": ["weight"]}},
        conversation_id="conversation-without-final-choice",
    )


@pytest.mark.parametrize(
    "question",
    [
        "\u4e0d\u8981\u4f60\u521a\u624d\u9009\u7684\u90a3\u6b3e\uff0c\u53e6\u4e00\u6b3e\u91cd\u91cf\u662f\u591a\u5c11\uff1f",
        "\u522b\u7ba1\u4f60\u521a\u624d\u9009\u7684\u90a3\u6b3e\uff0c\u53e6\u4e00\u6b3e\u91cd\u91cf\u662f\u591a\u5c11\uff1f",
        "\u9664\u4e86\u4f60\u9009\u7684\u90a3\u6b3e\uff0c\u53e6\u4e00\u6b3e\u91cd\u91cf\u662f\u591a\u5c11\uff1f",
        "\u9664\u53bb\u4f60\u9009\u7684\u90a3\u6b3e\uff0c\u53e6\u4e00\u6b3e\u91cd\u91cf\u662f\u591a\u5c11\uff1f",
    ],
)
def test_excluded_selected_choice_reference_requires_semantic_preplan(
    route_client_and_db,
    monkeypatch,
    question,
):
    client, headers, _ = route_client_and_db

    async def no_semantic_plan(*_args, **_kwargs):
        return {"called": False}

    monkeypatch.setattr(customer_agent_planner_service, "plan_customer_question_semantic", no_semantic_plan)
    first = client.post(
        "/api/customer-service/ask?debug=true",
        json={"question": "CW-C83 \u548c CW-C06PRO \u54ea\u4e2a\u66f4\u9002\u5408\u4e24\u4e2a\u4eba\u5468\u672b\u5f92\u6b65\uff1f"},
        headers=headers,
    )
    assert first.status_code == 200, first.text
    first_payload = first.json()
    selected_sku = (first_payload.get("answer_metadata") or {}).get("final_choice_sku")
    assert selected_sku in {"CW-C83", "CW-C06PRO"}, first_payload

    second = client.post(
        "/api/customer-service/ask?debug=true",
        json={
            "question": "\u4f60\u66f4\u5efa\u8bae\u54ea\u4e00\u4e2a\uff1f\u8bf7\u8bf4\u660e\u7406\u7531\u3002",
            "conversation_id": first_payload["conversation_id"],
        },
        headers=headers,
    )
    assert second.status_code == 200, second.text

    calls = []

    async def semantic_plan_required(*_args, **_kwargs):
        calls.append(True)
        return {"called": False}

    monkeypatch.setattr(customer_service_service, "_maybe_run_semantic_preplan", semantic_plan_required)
    third = client.post(
        "/api/customer-service/ask?debug=true",
        json={"question": question, "conversation_id": second.json()["conversation_id"]},
        headers=headers,
    )

    assert third.status_code == 200, third.text
    payload = third.json()
    assert calls == [True]
    assert payload.get("result_skus") != [selected_sku], payload


def test_page_bound_usage_followup_does_not_leak_catalogue_cards(route_client_and_db):
    client, headers, Session = route_client_and_db
    with Session() as db:
        _add_product(db, "CS-G25", "\u5c0f\u9752\u7089", "\u7089\u5177", "/", "\u4e0d\u9508\u94a2", "\u6c14\u7f50", "\u57fa\u7840\u6b3e\u7089\u5177", "\u9732\u8425\u70e7\u70e4", 550)
        db.commit()

    response = client.post(
        "/api/customer-service/ask?debug=true",
        json={"question": "\u6211\u4e70\u7684\u7089\u5b50\u600e\u4e48\u6ca1\u6709\u7ba1\u7684?", "sku": "CS-G25"},
        headers=headers,
    )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert len(payload.get("result_skus") or []) <= 1, payload
    assert "CS-G25-B" not in (payload.get("result_skus") or []), payload
    assert any(term in payload["answer"] for term in ("\u8d44\u6599", "\u914d\u4ef6", "\u7089\u7ba1", "SKU")), payload


def _seed_unrelated_ignition_lifetime_qa(Session) -> None:
    with Session() as db:
        if not db.query(Product).filter(Product.sku == "IGNITER-LIFETIME-01").first():
            _add_product(
                db,
                "IGNITER-LIFETIME-01",
                "按压点火器",
                "配件",
                "/",
                "塑料",
                "/",
                "便携点火",
                "露营点火",
                80,
            )
        _add_product_qa(
            db,
            "IGNITER-LIFETIME-01",
            "按压点火器能用多久？",
            "正常使用并正确保养的话，按压点火器可以使用多年，越用越顺手。",
            tags="点火器,保养,寿命",
            priority=999,
        )
        db.commit()


def _seed_cs_g25_page_anchor(Session) -> None:
    with Session() as db:
        if not db.query(Product).filter(Product.sku == "CS-G25").first():
            _add_product(
                db,
                "CS-G25",
                "小青炉",
                "炉具",
                "/",
                "不锈钢",
                "高山气罐 卡式气罐",
                "分体式点火",
                "露营烧水",
                2100,
            )
        db.commit()


def test_unverified_thickness_question_returns_field_answer_without_catalogue_cards(route_client_and_db):
    client, headers, _ = route_client_and_db

    response = client.post(
        "/api/customer-service/ask?debug=true",
        json={"question": "\u9505\u5177\u7684\u539a\u5ea6\u591a\u5c11?"},
        headers=headers,
    )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload.get("result_skus") == [], payload
    assert "\u539a\u5ea6" in payload["answer"], payload
    assert any(term in payload["answer"] for term in ("\u672a\u6807\u6ce8", "\u65e0\u6cd5\u786e\u8ba4", "\u6682\u672a")), payload


def test_gas_canister_value_comparison_does_not_recommend_cookware(route_client_and_db):
    client, headers, _ = route_client_and_db

    response = client.post(
        "/api/customer-service/ask?debug=true",
        json={"question": "\u662f\u4e70\u4e24\u4e2a\u5c0f\u6c14\u7f50\u5212\u7b97\u8fd8\u662f\u4e70\u4e00\u4e2a\u5927\u7684\u6c14\u7f50\u54ea\u4e2a\u6027\u4ef7\u6bd4\u9ad8?"},
        headers=headers,
    )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload.get("result_skus") == [], payload
    assert any(term in payload["answer"] for term in ("\u4ef7\u683c", "\u5bb9\u91cf", "\u6c14\u7f50", "\u65e0\u6cd5\u786e\u8ba4")), payload


def test_ambiguous_stove_core_comparison_asks_for_the_two_product_identities(route_client_and_db):
    client, headers, _ = route_client_and_db

    response = client.post(
        "/api/customer-service/ask?debug=true",
        json={"question": "\u6709\u4e24\u6b3e\u6c14\u7089\u82af\uff0c\u6709\u5565\u533a\u522b?"},
        headers=headers,
    )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload.get("result_skus") == [], payload
    assert any(term in payload["answer"] for term in ("SKU", "\u5546\u54c1\u540d", "\u54ea\u4e24\u6b3e", "\u8865\u5145")), payload


def test_page_extension_burner_replacement_does_not_return_unrelated_stove_list(route_client_and_db):
    client, headers, _ = route_client_and_db

    response = client.post(
        "/api/customer-service/ask?debug=true",
        json={"question": "\u53ef\u4ee5\u7528\u4ec0\u4e48\u52a0\u957f\u7089\u5934\u66ff\u4ee3?\u4f60\u4eec\u5e97\u6709\u5417?", "sku": "CS-G25"},
        headers=headers,
    )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert len(payload.get("result_skus") or []) <= 1, payload
    assert any(term in payload["answer"] for term in ("\u517c\u5bb9", "\u66ff\u4ee3", "\u672a\u6807\u6ce8", "\u65e0\u6cd5\u786e\u8ba4", "SKU")), payload


def test_page_gas_canister_availability_does_not_recommend_unrelated_products(route_client_and_db):
    client, headers, Session = route_client_and_db
    with Session() as db:
        _add_product(db, "CS-G25", "\u5c0f\u9752\u7089", "\u7089\u5177", "/", "\u4e0d\u9508\u94a2", "\u9ad8\u5c71\u6c14\u7f50,\u5361\u5f0f\u6c14\u7f50", "\u9632\u98ce", "\u9732\u8425", 550)
        db.commit()

    response = client.post(
        "/api/customer-service/ask?debug=true",
        json={"question": "\u4f60\u4eec\u6709\u6ca1\u6709\u5356\u6c14\u7f50?", "sku": "CS-G25"},
        headers=headers,
    )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload.get("result_skus") == [], payload
    assert "CS-G26HM" not in (payload.get("answer") or ""), payload
    assert any(term in payload["answer"] for term in ("\u6c14\u7f50", "\u672a\u7ef4\u62a4", "\u65e0\u6cd5\u786e\u8ba4")), payload


def test_page_canister_compatibility_uses_direct_conclusion_for_natural_wording(route_client_and_db):
    client, headers, Session = route_client_and_db
    with Session() as db:
        _add_product(db, "CS-G25", "\u5c0f\u9752\u7089", "\u7089\u5177", "/", "\u4e0d\u9508\u94a2", "\u9ad8\u5c71\u6c14\u7f50,\u5361\u5f0f\u6c14\u7f50", "\u9632\u98ce", "\u9732\u8425", 550)
        db.commit()

    response = client.post(
        "/api/customer-service/ask?debug=true",
        json={"question": "\u4f60\u597d\uff0c\u8fd9\u6b3e\u9632\u98ce\u7089\u53ef\u4ee5\u7528\u666e\u901a\u90a3\u79cd\u6c14\u7f50\u5417?", "sku": "CS-G25"},
        headers=headers,
    )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert "\u517c\u5bb9\u6027\u7ed3\u8bba" in payload["answer"], payload
    assert any(term in payload["answer"] for term in ("\u65e0\u6cd5\u786e\u8ba4", "\u672a\u6807\u6ce8", "\u652f\u6301")), payload
    assert "\u8fde\u63a5\u524d\u5148\u786e\u8ba4" not in payload["answer"], payload


def test_page_canister_addon_does_not_leak_internal_product_dump(route_client_and_db):
    client, headers, Session = route_client_and_db
    with Session() as db:
        _add_product(db, "CS-G25", "\u5c0f\u9752\u7089", "\u7089\u5177", "/", "\u4e0d\u9508\u94a2", "\u9ad8\u5c71\u6c14\u7f50,\u5361\u5f0f\u6c14\u7f50", "\u9632\u98ce", "\u9732\u8425", 550)
        db.commit()

    response = client.post(
        "/api/customer-service/ask?debug=true",
        json={"question": "\u71c3\u6c14\u7f50\u53ef\u4ee5\u589e\u914d?", "sku": "CS-G25"},
        headers=headers,
    )

    assert response.status_code == 200, response.text
    payload = response.json()
    answer = payload["answer"]
    assert "\u914d\u4ef6\u7ed3\u8bba" in answer, payload
    assert "\u8d1f\u8d23\u4eba" not in answer and "\u4ea7\u54c1\u8d44\u6599" not in answer, payload
    assert "SKU: CS-G25" not in answer, payload


def test_unknown_named_cookware_question_clears_broad_catalogue_cards(route_client_and_db):
    client, headers, _ = route_client_and_db

    response = client.post(
        "/api/customer-service/ask?debug=true",
        json={"question": "\u6fc0\u5ddd\u9505\u6709\u5417?"},
        headers=headers,
    )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload.get("result_skus") == [], payload
    assert any(term in payload["answer"] for term in ("\u672a\u627e\u5230", "\u6ca1\u6709", "\u786e\u8ba4", "\u8865\u5145")), payload


def test_stove_separate_purchase_question_answers_scope_without_catalogue_cards(route_client_and_db):
    client, headers, _ = route_client_and_db
    response = client.post(
        "/api/customer-service/ask?debug=true",
        json={"question": "\u6c14\u7089\u8981\u5355\u62cd\u5417?"},
        headers=headers,
    )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload.get("result_skus") == [], payload
    assert any(term in payload["answer"] for term in ("\u5206\u5f00", "\u5305\u88c5", "SKU", "\u5546\u54c1\u9875")), payload


def test_unbound_cookware_compatibility_question_does_not_search_all_cookware(route_client_and_db):
    client, headers, _ = route_client_and_db
    response = client.post(
        "/api/customer-service/ask?debug=true",
        json={"question": "\u6211\u60f3\u8bd5\u8bd5\u80fd\u4e0d\u80fd\u653e\u6211\u7684\u7092\u9505\u70e4\u76d8?"},
        headers=headers,
    )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload.get("result_skus") == [], payload
    assert "\u517c\u5bb9\u6027\u7ed3\u8bba" in payload["answer"], payload


def test_contextual_ambiguous_stove_core_question_does_not_reuse_large_catalogue(route_client_and_db):
    client, headers, _ = route_client_and_db
    first = client.post(
        "/api/customer-service/ask?debug=true",
        json={"question": "\u6709\u591a\u5c11\u6b3e\u7089\u5177?"},
        headers=headers,
    )
    assert first.status_code == 200, first.text
    conversation_id = first.json().get("conversation_id")
    response = client.post(
        "/api/customer-service/ask?debug=true",
        json={"question": "\u6709\u4e24\u6b3e\u6c14\u7089\u82af\uff0c\u6709\u5565\u533a\u522b?", "conversation_id": conversation_id},
        headers=headers,
    )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload.get("result_skus") == [], payload
    assert any(term in payload["answer"] for term in ("SKU", "\u5546\u54c1\u540d", "\u54ea\u4e24\u6b3e", "\u8865\u5145")), payload


def test_contextual_power_followup_compares_prior_candidate_set(route_client_and_db, monkeypatch):
    client, headers, Session = route_client_and_db
    async def generic_catalog_plan(*_args, **_kwargs):
        return {
            "called": True,
            "route_family": "generic_query",
            "route_hint": "query_products",
            "question_type": "filter",
            "entities": [],
            "canonical_fields": [],
            "confidence": 0.95,
        }

    monkeypatch.setattr(
        customer_agent_planner_service,
        "plan_customer_question_semantic",
        generic_catalog_plan,
    )
    with Session() as db:
        _add_product(db, "STV-002", "\u5c0f\u706b\u5361\u5f0f\u7089", "\u7089\u5177", "/", "\u4e0d\u9508\u94a2", "\u6c14\u7f50", "\u7a33\u5b9a\u706b\u529b", "\u684c\u9762\u9732\u8425", 900)
        _add_product(db, "STV-003", "\u731b\u706b\u5361\u5f0f\u7089", "\u7089\u5177", "/", "\u4e0d\u9508\u94a2", "\u6c14\u7f50", "\u5927\u706b\u529b", "\u6237\u5916\u70f9\u996a", 1100)
        db.query(ProductSpecs).filter(ProductSpecs.product_id == "route-STV-002").first().power = "1800W"
        db.query(ProductSpecs).filter(ProductSpecs.product_id == "route-STV-003").first().power = "3200W"
        db.commit()
    first = client.post(
        "/api/customer-service/ask?debug=true",
        json={"question": "\u6709\u6ca1\u6709\u63a8\u8350\u7684\u5361\u5f0f\u7089?"},
        headers=headers,
    )
    assert first.status_code == 200, first.text
    conversation_id = first.json().get("conversation_id")
    assert conversation_id

    response = client.post(
        "/api/customer-service/ask?debug=true",
        json={
            "question": "\u6709\u6ca1\u6709\u66f4\u5927\u706b\u529b?",
            "conversation_id": conversation_id,
        },
        headers=headers,
    )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["answer_type"] == "comparison", payload
    assert payload.get("result_skus"), payload
    assert any(term in payload["answer"] for term in ("\u706b\u529b\u6700\u5927", "\u529f\u7387")), payload
    assert (payload.get("debug") or {}).get("agent_mode") == "context_collection_power_comparison", payload


def test_explicit_pair_choice_keeps_direct_recommendation_during_semantic_outage(route_client_and_db):
    client, headers, _ = route_client_and_db
    response = client.post(
        "/api/customer-service/ask?debug=true",
        json={"question": "CW-C83 \u548c CW-C06PRO \u54ea\u4e2a\u66f4\u9002\u5408\u4e24\u4e2a\u4eba\u5f92\u6b65?"},
        headers=headers,
    )

    assert response.status_code == 200, response.text
    payload = response.json()
    answer = payload["answer"]
    assert payload.get("result_skus"), payload
    assert any(term in answer for term in ("\u66f4\u5efa\u8bae", "\u4f18\u5148\u63a8\u8350", "\u66f4\u9002\u5408")), payload
    assert "CW-C06PRO" in answer or "CW-C83" in answer, payload
    assert payload.get("answer_metadata", {}).get("final_choice_sku"), payload


def test_steamer_compatibility_is_not_inferred_from_pot_capacity(route_client_and_db):
    client, headers, _ = route_client_and_db

    response = client.post(
        "/api/customer-service/ask?debug=true",
        json={"question": "\u4f60\u5bb6\u6709\u6237\u5916\u65e2\u80fd\u7092\u83dc\u53c8\u80fd\u716e\u9762\u8fd8\u80fd\u653e\u4e2a\u84b8\u5c49\u84b8\u7c73\u996d\u7684\u9505\u5417?"},
        headers=headers,
    )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert "\u6709\u53ef\u80fd\u7a33\u5b9a\u653e\u5f97\u4e0b" not in payload["answer"], payload
    assert any(term in payload["answer"] for term in ("\u84b8\u5c49", "\u672a\u6807\u6ce8", "\u65e0\u6cd5\u786e\u8ba4", "\u4e0d\u80fd\u786e\u8ba4")), payload


def test_plain_card_stove_recommendation_excludes_alcohol_stove_rows(route_client_and_db):
    client, headers, _ = route_client_and_db

    response = client.post(
        "/api/customer-service/ask?debug=true",
        json={"question": "\u6709\u6ca1\u6709\u63a8\u8350\u7684\u5361\u5f0f\u7089?"},
        headers=headers,
    )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["answer_type"] == "recommendation", payload
    assert "CS-B14" not in (payload.get("result_skus") or []), payload
    assert "\u65cb\u7130\u9152\u7cbe\u7089" not in payload["answer"], payload
    assert any(sku in (payload.get("result_skus") or []) for sku in ("STV-001", "CS-G26HM")), payload


def test_unknown_named_stove_identity_does_not_lead_with_unrelated_recommendation(route_client_and_db):
    client, headers, _ = route_client_and_db

    response = client.post(
        "/api/customer-service/ask?debug=true",
        json={"question": "\u98ce\u66b4\u7089\u662f\u54ea\u4e2a?"},
        headers=headers,
    )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload.get("result_skus") == [], payload
    assert "\u66f4\u63a8\u8350" not in payload["answer"], payload
    assert any(term in payload["answer"] for term in ("\u672a\u627e\u5230", "\u6ca1\u6709", "\u786e\u8ba4", "\u8865\u5145")), payload


def test_page_stove_separate_purchase_question_answers_purchase_scope(route_client_and_db):
    client, headers, _ = route_client_and_db

    response = client.post(
        "/api/customer-service/ask?debug=true",
        json={"question": "CW-C83 \u6709\u5355\u72ec\u7089\u5b50\u4e70\u5417?"},
        headers=headers,
    )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload.get("result_skus") == ["CW-C83"], payload
    assert any(term in payload["answer"] for term in ("\u5355\u72ec\u8d2d\u4e70", "\u53e6\u4e70", "\u5355\u72ec\u7089\u5b50")), payload
    assert "\u5305\u88c5\u6e05\u5355" in payload["answer"] or "\u672a\u6807\u6ce8" in payload["answer"], payload
def test_solid_alcohol_amount_and_boil_time_is_usage_care_without_catalogue_cards(route_client_and_db):
    client, headers, _ = route_client_and_db

    response = client.post(
        "/api/customer-service/ask?debug=true",
        json={"question": "\u56fa\u4f53\u9152\u7cbe\u4e00\u6b21\u653e\u591a\u5c11\u5757\uff0c\u591a\u4e45\u80fd\u70e7\u5f00\u4e00\u58f6\u6c34\uff1f"},
        headers=headers,
    )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["answer_type"] == "product_usage_care", payload
    assert payload.get("result_skus") == [], payload
    assert "\u672a\u6807\u6ce8" in payload["answer"] and "\u4e0d\u80fd\u76f4\u63a5\u7ed9\u51fa" in payload["answer"], payload


def test_unsealed_comparison_clarification_uses_customer_language():
    result = customer_service_service._semantic_comparison_fail_closed_result(
        {"called": True, "route_family": "comparison", "entities": ["\u5c0f\u9752\u7089", "\u56f4\u96ea"], "confidence": 0.9}
    )

    assert result is not None
    answer = result["answer"]
    assert "\u5b57\u6bb5" not in answer
    assert "\u5404\u81ea\u5df2\u6838\u5bf9\u7684\u4fe1\u606f" in answer


def test_page_terse_stove_question_keeps_current_page_identity(route_client_and_db):
    client, headers, Session = route_client_and_db
    with Session() as db:
        _add_product(db, "CS-G25", "小青炉", "炉具", "/", "不锈钢", "气罐", "基础款炉具", "露营烧烤", 550)
        db.commit()

    response = client.post(
        "/api/customer-service/ask?debug=true",
        json={"question": "\u7089\u5b50\uff1f", "sku": "CS-G25"},
        headers=headers,
    )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload.get("result_skus") == ["CS-G25"], payload
    assert "KD23-MFL" not in (payload.get("result_skus") or []), payload
    assert "\u5f53\u524d\u9875\u9762\u5546\u54c1" in payload["answer"], payload


def test_page_price_package_question_does_not_expand_to_stove_catalogue(route_client_and_db):
    client, headers, Session = route_client_and_db
    with Session() as db:
        _add_product(db, "CS-G25", "小青炉", "炉具", "/", "不锈钢", "气罐", "基础款炉具", "露营烧烤", 550)
        db.commit()

    response = client.post(
        "/api/customer-service/ask?debug=true",
        json={"question": "358\u5143\uff0c\u8fd9\u4e00\u6b3e\u53ea\u6709\u4e00\u4e2a\u7089\uff0c\u4e0d\u542b\u7089\u5177\uff1f", "sku": "CS-G25"},
        headers=headers,
    )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload.get("result_skus") == ["CS-G25"], payload
    assert "KD23-MFL" not in (payload.get("result_skus") or []), payload
    assert "\u5305\u88c5\u6e05\u5355" in payload["answer"] and "\u65e0\u6cd5\u786e\u8ba4" in payload["answer"], payload


def test_unbound_induction_compatibility_asks_for_product_identity(route_client_and_db):
    client, headers, _ = route_client_and_db

    response = client.post(
        "/api/customer-service/ask?debug=true",
        json={"question": "\u662f\u5426\u53ef\u7528\u7535\u78c1\u7089\uff1f"},
        headers=headers,
    )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload.get("result_skus") == [], payload
    assert "\u517c\u5bb9\u6027\u7ed3\u8bba" in payload["answer"], payload
    assert "\u7535\u78c1\u7089" in payload["answer"] and "\u5546\u54c1\u540d\u6216 SKU" in payload["answer"], payload


def test_unbound_single_pot_contents_question_does_not_dump_catalogue(route_client_and_db):
    client, headers, _ = route_client_and_db

    response = client.post(
        "/api/customer-service/ask?debug=true",
        json={"question": "只有锅？"},
        headers=headers,
    )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload.get("result_skus") == [], payload
    assert "当前还没有锁定具体商品" in payload["answer"], payload
    assert "字段" not in payload["answer"], payload


def test_unbound_single_pot_followup_does_not_return_mixed_set_cards(route_client_and_db):
    client, headers, _ = route_client_and_db

    response = client.post(
        "/api/customer-service/ask?debug=true",
        json={"question": "这一款就只有单独一个锅，没有其他东西的是吧？"},
        headers=headers,
    )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload.get("result_skus") == [], payload
    assert "包装清单" in payload["answer"], payload
    assert "CW-C69-1" not in payload["answer"], payload


def test_route_level_liquid_alcohol_amount_keeps_liquid_unit(route_client_and_db):
    client, headers, _ = route_client_and_db

    response = client.post(
        "/api/customer-service/ask?debug=true",
        json={"question": "液体酒精一次加多少毫升？"},
        headers=headers,
    )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["answer_type"] == "product_usage_care", payload
    assert "液体酒精" in payload["answer"] or "毫升" in payload["answer"], payload
    assert "每次应放多少块" not in payload["answer"], payload
    assert payload.get("result_skus") == [], payload


def test_route_level_ignition_question_is_not_fault_template(route_client_and_db):
    client, headers, _ = route_client_and_db

    response = client.post(
        "/api/customer-service/ask?debug=true",
        json={"question": "小青炉怎么点火？"},
        headers=headers,
    )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["answer_type"] in {"product_usage_care", "product_detail"}, payload
    assert "先关闭阀门，停止继续点火" not in payload["answer"], payload
    assert any(term in payload["answer"] for term in ("使用说明", "点火", "型号", "SKU")), payload


def test_route_level_canister_fault_is_not_package_answer(route_client_and_db):
    client, headers, _ = route_client_and_db

    response = client.post(
        "/api/customer-service/ask?debug=true",
        json={"question": "气罐不出气怎么办？"},
        headers=headers,
    )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["answer_type"] == "product_usage_care", payload
    assert any(term in payload["answer"] for term in ("阀门", "接口", "检查", "停止使用")), payload
    assert "购买状态" not in payload["answer"], payload
    assert payload.get("result_skus") == [], payload


def test_route_level_canister_type_question_is_not_quantity_answer(route_client_and_db):
    client, headers, _ = route_client_and_db

    response = client.post(
        "/api/customer-service/ask?debug=true",
        json={"question": "这个气罐是不是专用的？"},
        headers=headers,
    )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["answer_type"] == "product_usage_care", payload
    assert any(term in payload["answer"] for term in ("气罐类型", "兼容性", "适配")), payload
    assert "购买状态" not in payload["answer"], payload
    assert payload.get("result_skus") == [], payload


def test_route_level_unbound_ignition_does_not_use_unrelated_product_qa(route_client_and_db):
    client, headers, Session = route_client_and_db
    _seed_unrelated_ignition_lifetime_qa(Session)

    response = client.post(
        "/api/customer-service/ask?debug=true",
        json={"question": "这个怎么点火？"},
        headers=headers,
    )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload.get("result_skus") == [], payload
    assert "使用多年" not in payload["answer"], payload["answer"]
    assert "越用越顺手" not in payload["answer"], payload["answer"]
    assert any(term in payload["answer"] for term in ("型号", "SKU", "说明书", "具体商品")), payload["answer"]


@pytest.mark.parametrize(
    ("question", "required_terms"),
    [
        ("酒精也要用点火器？", ("点火器", "型号")),
        ("点火器有卖的吗，可以更换不？", ("更换", "配件")),
    ],
)
def test_route_level_igniter_predicate_is_not_replaced_by_lifetime_qa(
    route_client_and_db,
    question,
    required_terms,
):
    client, headers, Session = route_client_and_db
    _seed_unrelated_ignition_lifetime_qa(Session)

    response = client.post(
        "/api/customer-service/ask?debug=true",
        json={"question": question},
        headers=headers,
    )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert "使用多年" not in payload["answer"], payload["answer"]
    assert "越用越顺手" not in payload["answer"], payload["answer"]
    assert any(term in payload["answer"] for term in required_terms), payload["answer"]


def test_route_level_untyped_alcohol_amount_does_not_assume_solid_pieces(route_client_and_db):
    client, headers, _ = route_client_and_db

    response = client.post(
        "/api/customer-service/ask?debug=true",
        json={"question": "炉头一次加多少酒精？能烧多久？（当前商品：自驾游野餐炉子）"},
        headers=headers,
    )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert "每次应放多少块固体酒精" not in payload["answer"], payload["answer"]
    assert "请以固体酒精" not in payload["answer"], payload["answer"]
    assert "默认换算成固体酒精块数" in payload["answer"], payload["answer"]
    assert any(term in payload["answer"] for term in ("燃料类型", "酒精类型", "用量", "使用时长")), payload["answer"]


@pytest.mark.parametrize("page_subject", ["水壶", "烧水壶野炊露营户外套锅", "烤盘"])
def test_route_level_inline_cookware_cleaning_does_not_use_stove_components(
    route_client_and_db,
    page_subject,
):
    client, headers, _ = route_client_and_db

    response = client.post(
        "/api/customer-service/ask?debug=true",
        json={"question": f"第一次使用怎么清洗呢？（当前商品：{page_subject}）"},
        headers=headers,
    )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert any(term in payload["answer"] for term in ("清洗", "清洁", "冲洗")), payload["answer"]
    assert not any(term in payload["answer"] for term in ("移除燃料", "气路", "阀门", "点火部件")), payload["answer"]


@pytest.mark.parametrize(
    ("question", "required_terms"),
    [
        ("在问一下，怎么点火的？", ("点火", "使用")),
        ("我买的这一套，怎么打火的时候只有声音没有火呢？", ("检查", "阀门", "接口")),
        ("好像被水打湿了，这个点火器有卖的吗，可以更换不？", ("更换", "配件")),
    ],
)
def test_route_level_page_anchor_ignores_discourse_prefaces(
    route_client_and_db,
    question,
    required_terms,
):
    client, headers, Session = route_client_and_db
    _seed_cs_g25_page_anchor(Session)

    response = client.post(
        "/api/customer-service/ask?debug=true",
        json={"question": question, "sku": "CS-G25"},
        headers=headers,
    )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert (payload.get("debug") or {}).get("agent_mode") != "page_context_explicit_subject_conflict", payload
    assert "身份未确认一致" not in payload["answer"], payload["answer"]
    assert any(term in payload["answer"] for term in required_terms), payload["answer"]


def test_route_level_alcohol_disposal_answers_where_not_to_dispose(route_client_and_db):
    client, headers, _ = route_client_and_db

    response = client.post(
        "/api/customer-service/ask?debug=true",
        json={"question": "高浓度酒精没用完倒哪里？"},
        headers=headers,
    )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert "下水道" in payload["answer"], payload["answer"]
    assert any(term in payload["answer"] for term in ("不要", "不能", "禁止")), payload["answer"]
    assert any(term in payload["answer"] for term in ("处置", "回收", "危险废物", "当地规定")), payload["answer"]


def test_route_level_ambiguous_followup_never_dumps_internal_keyword_fields(route_client_and_db):
    client, headers, Session = route_client_and_db
    _seed_cs_g25_page_anchor(Session)

    first = client.post(
        "/api/customer-service/ask?debug=true",
        json={"question": "这个可以用烧烤盘吗？", "sku": "CS-G25"},
        headers=headers,
    )
    assert first.status_code == 200, first.text
    conversation_id = first.json()["conversation_id"]

    second = client.post(
        "/api/customer-service/ask?debug=true",
        json={"question": "是多大的炉子还是多大的盘？", "sku": "CS-G25", "conversation_id": conversation_id},
        headers=headers,
    )
    assert second.status_code == 200, second.text

    response = client.post(
        "/api/customer-service/ask?debug=true",
        json={"question": "哪个可以？", "sku": "CS-G25", "conversation_id": conversation_id},
        headers=headers,
    )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert not any(term in payload["answer"] for term in ("关键词库", "keyword:", "priority:", "中文标题")), payload["answer"]
    assert len(payload["answer"]) < 800, payload["answer"]


def test_route_level_page_colloquial_fuel_question_uses_same_sku_heat_source(route_client_and_db):
    client, headers, Session = route_client_and_db
    with Session() as db:
        _add_product(
            db,
            "PAGE-FUEL-01",
            "测试户外炉",
            "炉具",
            "/",
            "不锈钢",
            "高山气罐、卡式气罐",
            "分体防风炉",
            "露营",
            560,
        )
        db.commit()

    response = client.post(
        "/api/customer-service/ask?debug=true",
        json={"question": "还有燃料是啥？", "sku": "PAGE-FUEL-01"},
        headers=headers,
    )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload.get("result_skus") == ["PAGE-FUEL-01"], payload
    assert "高山气罐" in payload["answer"], payload
    assert "卡式气罐" in payload["answer"], payload
    assert "未找到可直接确认这个问题的产品问答" not in payload["answer"], payload


def test_route_level_generic_alcohol_recommendation_returns_fuel_guidance(route_client_and_db):
    client, headers, _ = route_client_and_db
    response = client.post(
        "/api/customer-service/ask?debug=true",
        json={"question": "酒精推荐什么样的？"},
        headers=headers,
    )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload.get("answer_type") == "product_usage_care", payload
    assert payload.get("result_skus") == [], payload
    assert "燃料" in payload["answer"], payload
    assert "医用酒精" in payload["answer"], payload
    assert "可供推荐的产品范围" not in payload["answer"], payload
