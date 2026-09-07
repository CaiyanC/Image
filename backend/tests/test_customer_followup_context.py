"""Offline regressions for anchored replacement requests; no model calls."""
import asyncio
import copy

import pytest

from app.models.product import Product
from app.models.knowledge_base import CustomerServiceConversation, CustomerServiceMessage
from app.services import customer_followup_context_contract as contract
from app.services import customer_service_workbuddy_rag_service as runtime


def product(sku="ANCHOR", name="露营水壶", volume="1.4L", category="水具", status="常规品"):
    return {"sku": sku, "product_name_cn": name, "category": category,
            "lifecycle_status": status, "active_flag": True,
            "specs": {"capacity": [{"label": "", "value": volume, "unit": ""}],
                      "body_material": "硬质氧化铝", "gross_weight_g": 273},
            "business": {}}


FIRST = "CB253 有点贵，我两个人周末露营烧水用，值得买吗？"
FOLLOW = "那推荐一款还在正常供货的，容量差不多就行。"
OLD = product("CB253", "聚能环水壶（亚马逊转国内）", status="老款无货不补")
GOOD = product("CW-K03-37", "1.4升户外水壶", "水壶：1400ml", "水壶")
BURNER = product("CS-B13-37", "U悠 酒精炉套装PRO", "炉芯：100ml", "酒精炉")
CUP = product("TW-503", "悠然杯Pro", "350ml", "水杯")
LARGE = product("CW-K32", "享膳Plus水壶", "2.3L", "锅具")
CLEARANCE = product("CW-K03", "1.4L野营水壶", "1.4L", status="清仓品")


def advance(question, previous=None, anchor=OLD, **kwargs):
    if previous is None:
        previous = contract.seed_purchase_context(FIRST, OLD)
    return contract.prepare_followup_context(question, previous=previous, anchor_product=anchor, **kwargs)


@pytest.mark.parametrize("question", [FOLLOW,
    "如果这款停产了，帮我找个差不多大的替代款，还是烧水用。",
    "换个差不多的", "还有别的吗？", "推荐便宜一点的同容量水壶",
    "有没有容量相近、能买到的？"])
def test_replacement_inherits_bounded_task(question):
    context, applies, _ = advance(question)
    assert applies and context["capacity_ml"] == 1400
    query = contract.retrieval_query(question, context)
    assert "烧水壶" in query and "1.4L" in query and "两个人" in query
    assert "CB253" not in query
    assert contract.candidate_issues(GOOD, context) == []
    for bad in [BURNER, CUP, LARGE, CLEARANCE, OLD]:
        assert contract.candidate_issues(bad, context)


@pytest.mark.parametrize("first", [FIRST, "CB253容量多少？", "CB253这个1.4L水壶适合两个人周末露营烧水吗？"])
def test_fact_first_turn_also_seeds_reference(first):
    context, applies, _ = contract.prepare_followup_context(first, previous=None, anchor_product=None,
        current_product=OLD, has_current_subject=True)
    assert not applies and context["capacity_ml"] == 1400
    assert advance("换个差不多的", context)[1]


@pytest.mark.parametrize("volume", ["1.4L", "1400ml", "1400ML", "1.4升", "1400毫升", "水壶：1400ml"])
@pytest.mark.parametrize("category", ["水具", "锅具", "水壶", None])
def test_units_and_category_spelling_do_not_change_vessel_identity(volume, category):
    context, _, _ = advance(FOLLOW)
    assert contract.candidate_issues(product(volume=volume, category=category), context) == []


@pytest.mark.parametrize("value", [True, False, float("nan"), float("inf"), -1, "1400"])
def test_invalid_normalized_capacity(value):
    context = contract.seed_purchase_context(FIRST, OLD)
    context["capacity_ml"] = value
    assert contract.normalize_purchase_context(context)["capacity_ml"] is None


@pytest.mark.parametrize("name, capacities", [
    ("水壶套装", [{"label": "", "value": "1.4L"}]),
    ("水壶", [{"label": "配件A", "value": "1.4L"}]),
    ("水壶组合", [{"label": "", "value": "1.4L"}, {"label": "", "value": "350ml"}]),
    ("水壶套装", [{"label": "炉芯", "value": "1400ml"}]),
    ("水壶套装", [{"label": "合计", "value": "1400ml"}]),
])
def test_unknown_or_multiple_capacity_objects_are_not_assigned(name, capacities):
    candidate = product(name=name)
    candidate["specs"]["capacity"] = capacities
    assert contract.product_capacities_ml(candidate, "kettle") == []


def test_explicit_kit_vessel_capacity_is_usable_not_its_burner():
    candidate = product(name="水壶酒精炉套装")
    candidate["specs"]["capacity"] = [{"label": "水壶", "value": 1400, "unit": "ml"},
                                      {"label": "炉芯", "value": 100, "unit": "ml"}]
    assert contract.product_capacities_ml(candidate, "kettle") == [1400]


@pytest.mark.parametrize("question,relation,ml", [
    ("要更大的", "larger", 1400), ("比它大一些", "larger", 1400),
    ("不要一样容量", "different", 1400), ("推荐小一些的", "smaller", 1400),
    ("不要1.4L，推荐2L水壶。", "near", 2000),
    ("不要1.4L改要2000毫升水壶", "near", 2000),
    ("容量无所谓，不要求容量了", "any", None),
])
def test_explicit_capacity_changes_replace_old_constraint(question, relation, ml):
    context, _, _ = advance(question)
    assert context["capacity_relation"] == relation and context["capacity_ml"] == ml
    if relation in {"larger", "different", "any"}:
        assert not contract.candidate_issues(LARGE, context)


def test_three_turn_capacity_relaxation_without_recommendation_word():
    relaxed, applies, _ = advance("容量无所谓，不要求容量了")
    assert not applies
    next_context, applies, _ = advance("那再推荐一款", relaxed)
    assert applies and next_context["capacity_ml"] is None
    assert not contract.candidate_issues(LARGE, next_context)
    assert contract.candidate_issues(CUP, next_context)  # Same purpose remains.


@pytest.mark.parametrize("question", ["别换成酒精炉，还是推荐水壶，容量差不多。",
    "不要改成酒精炉，给我找个水壶。"])
def test_negated_change_does_not_replace_subject(question):
    context, applies, reset = advance(question)
    assert applies and not reset and context["form"] == "kettle"
    assert context["capacity_ml"] == 1400


def test_positive_change_releases_old_form_volume_and_task():
    context, applies, reset = advance("改要酒精炉，水壶不要了")
    assert applies and reset and context["form"] == "stove"
    assert context["capacity_ml"] is None and context["anchor_sku"] == ""
    assert not contract.candidate_issues(BURNER, context)


def test_current_explicit_material_question_does_not_inherit_guard():
    context, applies, reset = advance("改成看CS-B13-37，它是什么材质？",
        current_product=BURNER, has_current_subject=True)
    assert not applies and reset and context["form"] == "stove"


def test_use_change_and_new_volume_do_not_repeat_old_effective_task():
    context, _, _ = advance("现在改在办公室用，推荐2L水壶")
    query = contract.retrieval_query("那再推荐一款", context)
    assert "办公室" in query and "2L" in query
    assert "露营" not in query and "1.4L" not in query and "双人" not in query
    assert context["source_question"] == FIRST  # Provenance is not a live condition.


@pytest.mark.parametrize("name", ["折叠露营椅", "户外煎锅"])
def test_other_product_forms_keep_generic_bounded_reference(name):
    anchor = product(name=name)
    context = contract.seed_purchase_context("想找坐着舒服或便于收纳的替代款", anchor)
    context, applies, _ = advance("换个差不多的", context, anchor)
    assert applies and context["form"] == "other"
    assert name in contract.retrieval_query("换个差不多的", context)
    assert contract.candidate_issues(product(name="另一款户外产品"), context) == []


def test_cleared_context_never_backfills_from_old_anchor():
    cleared, _, reset = advance("换个话题")
    assert reset and cleared == {}
    context, applies, _ = advance("那再推荐一款", cleared, OLD, last_user_question=FIRST)
    assert context == {} and not applies


@pytest.mark.parametrize("status", ["清仓品", "老款无货不补", "未上市新品", "", None])
def test_regular_supply_requires_a_known_allowed_lifecycle(status):
    context, _, _ = advance(FOLLOW)
    assert contract.candidate_issues(product(status=status), context)


@pytest.mark.parametrize("answer,expected", [
    ("这款有现货。", True), ("它还在正常供货。", True),
    ("目录标注常规品，实际库存及发货需确认。", False),
    ("不能确认是否有现货。", False),
])
def test_lifecycle_does_not_prove_live_inventory(answer, expected):
    assert contract.unsupported_stock_claim(answer) is expected


def test_positive_textual_choice_cannot_hide_behind_correct_selection():
    products = {p["sku"]: p for p in [OLD, GOOD, CUP, BURNER]}
    assert "TW-503" in contract.mentioned_choices("推荐CW-K03-37。另外推荐TW-503，但它不是水壶。", products)
    assert contract.mentioned_choices("CB253是老款，不建议买；推荐CW-K03-37。TW-503不是水壶，不推荐。", products) == ["CW-K03-37"]


@pytest.mark.parametrize("answer", [
    "推荐CW-K03-37。容量和CB253一样，都是1.4L。",
    "相比CB253，我推荐CW-K03-37。",
    "推荐CW-K03-37，容量与CB253相同。",
    "推荐CW-K03-37容量与CB253相同。",
    "CB253不建议新购，推荐CW-K03-37。",
])
def test_neutral_or_excluded_anchor_is_not_an_affirmative_choice(answer):
    products = {p["sku"]: p for p in [OLD, GOOD, CUP]}
    assert contract.mentioned_choices(answer, products) == [GOOD["sku"]]


@pytest.mark.parametrize("answer", [
    "推荐的不是CB253，而是CW-K03-37。",
    "CB253不是我推荐的，推荐CW-K03-37。",
])
def test_negated_recommendation_reference_does_not_select_old_anchor(answer):
    products = {p["sku"]: p for p in [OLD, GOOD, CUP]}
    assert contract.mentioned_choices(answer, products) == [GOOD["sku"]]


@pytest.mark.parametrize("answer", [
    "CB253不建议新购，推荐TW-503。推荐CW-K03-37。",
    "推荐TW-503，它不是水壶。推荐CW-K03-37。",
    "推荐TW-503，但它不是水壶。推荐CW-K03-37。",
    "推荐CW-K03-37和TW-503。",
])
def test_other_negation_or_later_disclaimer_cannot_erase_positive_choice(answer):
    products = {p["sku"]: p for p in [OLD, GOOD, CUP]}
    choices = contract.mentioned_choices(answer, products)
    assert CUP["sku"] in choices and GOOD["sku"] in choices
    assert OLD["sku"] not in choices


@pytest.fixture
def offline_runtime(route_client_and_db, monkeypatch):
    _, _, Session = route_client_and_db
    catalogue = {p["sku"]: copy.deepcopy(p) for p in [OLD, GOOD, CUP, BURNER, LARGE, CLEARANCE]}
    with Session() as db:
        for p in catalogue.values():
            db.add(Product(id=p["sku"], sku=p["sku"], barcode=p["sku"], brand="test",
                product_name_cn=p["product_name_cn"], category=p["category"], lifecycle_status=p["lifecycle_status"]))
        db.commit()
    captures = {"queries": [], "payloads": [], "answers": []}

    async def no_control(*args, **kwargs):
        return None

    async def retrieve(db, *, query, sku=None, **kwargs):
        captures["queries"].append({"query": query, "sku": sku})
        skus = [sku] if sku else [CUP["sku"], BURNER["sku"], GOOD["sku"], LARGE["sku"], CLEARANCE["sku"]]
        return [{"sku": s, "source_type": "product", "content": catalogue[s]["product_name_cn"],
                 "metadata": {"source_id": f"product:{s}:profile"}, "score": 0.99} for s in skus]

    async def generate(db, *, payload, **kwargs):
        captures["payloads"].append(payload)
        response = captures["answers"].pop(0)
        return copy.deepcopy(response), {"elapsed_ms": 0, "raw_valid": True}

    monkeypatch.setattr(runtime, "_control_boundary_result", no_control)
    monkeypatch.setattr(runtime, "_catalogue_subject_skus", lambda *args: [])
    monkeypatch.setattr(runtime, "_retrieve_once", retrieve)
    monkeypatch.setattr(runtime, "_generate_answer", generate)
    monkeypatch.setattr(runtime, "_product_details", lambda db, skus, limit=10: {s: catalogue[s] for s in skus[:limit] if s in catalogue})
    monkeypatch.setattr(runtime, "_append_same_sku_context", lambda *args: None)
    monkeypatch.setattr(runtime.customer_experience_rag_service, "should_retrieve_experience_guidance", lambda *args: False)
    return Session, captures


def response(sku, answer, answer_type="recommendation"):
    return {"answer": answer, "answer_type": answer_type, "request_kind": "recommendation" if answer_type == "recommendation" else "product_fact",
            "selected_skus": [sku] if sku else [], "selection_state": "selected" if sku else "no_match"}


def ask(db, question, conversation_id=None):
    return asyncio.run(runtime.ask_customer_service_workbuddy_rag(db, user_id="offline-user",
        question=question, conversation_id=conversation_id))


@pytest.mark.parametrize("bad", [BURNER, CUP])
def test_real_failure_is_blocked_and_original_anchor_survives_three_turns(offline_runtime, bad):
    Session, captured = offline_runtime
    captured["answers"] = [response("CB253", "CB253是1.4L水壶，但老款无货不补，不建议新购。"),
        response(bad["sku"], f"推荐{bad['sku']}，但它不是1.4L水壶。"),
        response("CB253", "CB253材质为硬质氧化铝。", "product_detail")]
    with Session() as db:
        first = ask(db, FIRST)
        second = ask(db, FOLLOW, first["conversation_id"])
        assert second["result_skus"] == [] and second["results"] == []
        assert second["debug"]["selection_state"] == "no_match"
        assert bad["sku"] not in second["answer"]
        assert db.get(CustomerServiceConversation, first["conversation_id"]).sku == "CB253"
        memory = runtime._load_previous_turn_memory(db, user_id="offline-user", conversation_id=first["conversation_id"])
        assert memory["active_product_skus"] == ["CB253"]
        third = ask(db, "那它是什么材质？", first["conversation_id"])
        assert third["result_skus"] == ["CB253"]
        assert not third["debug"]["replacement_turn"]
        assert captured["payloads"][2]["active_context_products"][0]["sku"] == "CB253"
        assert len(captured["payloads"]) == 3
        assert "烧水壶" in captured["queries"][1]["query"] and "1.4L" in captured["queries"][1]["query"]
        bad_rows = db.query(CustomerServiceMessage).filter(CustomerServiceMessage.sku == bad["sku"]).count()
        assert bad_rows == 0


@pytest.mark.parametrize("bad", [CUP, BURNER])
def test_correct_metadata_cannot_bypass_bad_positive_prose(offline_runtime, bad):
    Session, captured = offline_runtime
    captured["answers"] = [response("CB253", "CB253容量1.4L。", "product_detail"),
        response("CW-K03-37", f"推荐CW-K03-37，也推荐{bad['sku']}；但后者不是1.4L水壶。")]
    with Session() as db:
        first = ask(db, "CB253容量多少？")
        second = ask(db, FOLLOW, first["conversation_id"])
        assert second["result_skus"] == []
        assert bad["sku"] in second["debug"]["replacement_rejections"]


def test_valid_replacement_negative_old_reference_and_unit_equivalence(offline_runtime):
    Session, captured = offline_runtime
    captured["answers"] = [response("CB253", "CB253容量1.4L。", "product_detail"),
        response("CW-K03-37", "CB253是老款，不推荐新购。推荐CW-K03-37，水壶容量1400ml，属于常规品，库存需确认。")]
    with Session() as db:
        first = ask(db, "CB253容量多少？")
        second = ask(db, FOLLOW, first["conversation_id"])
        assert second["result_skus"] == ["CW-K03-37"]
        assert second["debug"]["replacement_rejections"] == {}


def test_purchase_then_explicitly_larger_is_not_stuck_at_near_capacity(offline_runtime):
    Session, captured = offline_runtime
    captured["answers"] = [response("CB253", "CB253是1.4L水壶。"), response("CW-K32", "推荐CW-K32，壶容量2.3L，属于常规品，库存需确认。")]
    with Session() as db:
        first = ask(db, FIRST)
        second = ask(db, "那推荐比它大一些的水壶", first["conversation_id"])
        assert second["result_skus"] == ["CW-K32"]
        assert second["answer_metadata"]["purchase_context"]["capacity_relation"] == "larger"


@pytest.mark.parametrize("selected,question,answer", [
    (GOOD, FOLLOW, "推荐CW-K03-37，容量和CB253一样，都是1.4L。实际库存需确认。"),
    (GOOD, FOLLOW, "推荐的不是CB253，而是CW-K03-37。"),
    (GOOD, FOLLOW, "CB253不是我推荐的，推荐CW-K03-37。"),
    (LARGE, "推荐比它大一些的水壶", "推荐CW-K32，2.3L比CB253的1.4L大。实际库存需确认。"),
])
def test_live_after_neutral_capacity_comparison_does_not_block(offline_runtime, selected, question, answer):
    Session, captured = offline_runtime
    captured["answers"] = [response("CB253", "CB253是1.4L水壶。"), response(selected["sku"], answer)]
    with Session() as db:
        first = ask(db, FIRST)
        second = ask(db, question, first["conversation_id"])
        assert second["result_skus"] == [selected["sku"]]
        assert second["debug"]["replacement_rejections"] == {}


@pytest.mark.parametrize("answer", [
    "CB253不建议新购，推荐TW-503。推荐CW-K03-37。",
    "推荐TW-503，它不是水壶。推荐CW-K03-37。",
])
def test_local_bad_prose_is_blocked_even_with_good_metadata(offline_runtime, answer):
    Session, captured = offline_runtime
    captured["answers"] = [response("CB253", "CB253是1.4L水壶。"), response(GOOD["sku"], answer)]
    with Session() as db:
        first = ask(db, FIRST)
        second = ask(db, FOLLOW, first["conversation_id"])
        assert second["result_skus"] == []
        assert CUP["sku"] in second["debug"]["replacement_rejections"]


def test_skuless_confirmed_first_answer_seeds_but_candidates_do_not(offline_runtime):
    Session, captured = offline_runtime
    captured["answers"] = [response(GOOD["sku"], "推荐CW-K03-37，1.4L水壶，适合两人露营。"),
        response(CUP["sku"], "推荐TW-503，但它不是水壶。"),
        response(None, "请确认具体需求。", "clarification")]
    with Session() as db:
        first = ask(db, "推荐一个两人露营水壶")
        assert first["result_skus"] == [GOOD["sku"]]
        assert first["answer_metadata"]["purchase_context"]["anchor_sku"] == GOOD["sku"]
        second = ask(db, "换个容量差不多的", first["conversation_id"])
        assert second["debug"]["replacement_turn"]
        assert second["result_skus"] == []
        unresolved = ask(db, "推荐一个两人露营水壶")
        assert unresolved["answer_metadata"]["purchase_context"] == {}


def test_success_then_failure_keeps_latest_confirmed_anchor(offline_runtime):
    Session, captured = offline_runtime
    captured["answers"] = [response("CB253", "CB253是1.4L水壶。"),
        response(GOOD["sku"], "推荐CW-K03-37。"),
        response(CUP["sku"], "推荐TW-503。"),
        response(GOOD["sku"], "CW-K03-37材质为硬质氧化铝。", "product_detail")]
    with Session() as db:
        first = ask(db, FIRST)
        second = ask(db, FOLLOW, first["conversation_id"])
        assert second["result_skus"] == [GOOD["sku"]]
        third = ask(db, "再推荐一款", first["conversation_id"])
        assert third["result_skus"] == []
        memory = runtime._load_previous_turn_memory(db, user_id="offline-user", conversation_id=first["conversation_id"])
        assert memory["active_product_skus"] == [GOOD["sku"]]
        fourth = ask(db, "那它是什么材质？", first["conversation_id"])
        assert fourth["result_skus"] == [GOOD["sku"]]
        assert captured["payloads"][3]["active_context_products"][0]["sku"] == GOOD["sku"]


def test_replacement_prompt_limits_single_choice_and_requires_consistent_comparisons(monkeypatch):
    prompts = []

    async def fake_chat(db, *, messages, **kwargs):
        prompts.append(messages[0]["content"])
        return '{"answer":"推荐一款水壶。","selected_skus":[],"selection_state":"no_match"}'

    monkeypatch.setattr(runtime.customer_llm_service, "chat_completion", fake_chat)
    monkeypatch.setattr(runtime, "answer_consistency_issues", lambda *args: [])
    asyncio.run(runtime._generate_answer(None, payload={
        "current_question": FOLLOW,
        "replacement_context": contract.seed_purchase_context(FIRST, OLD),
    }))
    assert len(prompts) == 1
    assert "仅给最合适的一款" in prompts[0] and "不扩展未请求的备选" in prompts[0]
    assert "毛重只与毛重比较" in prompts[0] and "先统一单位" in prompts[0]
    assert "毛重数值更大不能称更轻" in prompts[0] and "同一容量对象" in prompts[0]
