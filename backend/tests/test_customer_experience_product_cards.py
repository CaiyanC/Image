from types import SimpleNamespace

from scripts.seed_customer_experience_product_cards_20260905 import (
    build_all_cards,
    build_experience_card,
    _role_insights,
)


def _product(sku: str = "CS-B14"):
    return SimpleNamespace(
        id="product-id",
        sku=sku,
        barcode="barcode",
        product_name_cn="旋焰酒精炉",
    )


def test_build_card_aggregates_good_bad_reviews_and_chats_without_copying_answers():
    samples = [
        {
            "qaId": "q1",
            "quality": "good",
            "recordType": "商品评价",
            "intent": "选购与推荐",
            "answer": "不要把这句原始客服回答放进卡片",
            "_libraries": {"07_01_成交/好评成功案例库"},
            "_source_record_ids": ["review-1"],
        },
        {
            "qaId": "q2",
            "quality": "bad",
            "recordType": "客服对话",
            "intent": "售后与问题处理",
            "failureReason": "问题处理不完整",
            "answer": "不要复制差评原话",
            "_libraries": {"07_03_差评/顾客不满意原因库", "07_05_修复话术库"},
            "_source_record_ids": ["chat-1"],
        },
    ]

    card = build_experience_card(_product(), samples)

    assert card["metadata"]["coverage_status"] == "history_available"
    assert card["metadata"]["sample_counts"] == {
        "good": 1,
        "neutral": 0,
        "bad": 1,
        "reviews": 1,
        "chats": 1,
        "risk": 0,
        "repair": 1,
        "style": 0,
    }
    assert "原始客服回答" not in card["content"]
    assert "差评原话" not in card["content"]
    assert card["metadata"]["fact_authority"] is False
    assert card["metadata"]["review_status"] == "auto_generated_pilot"
    assert card["metadata"]["conversion_insights"]["conversion_samples"] == 1
    assert card["metadata"]["conversion_insights"]["negative_samples"] == 1
    assert "转化侧总结" in card["content"]
    assert "未转化侧总结" in card["content"]
    assert "差评风险总结" in card["content"]
    assert "问题处理不完整" in card["content"]
    assert "真实转化率" in card["content"]


def test_every_product_gets_a_card_even_without_confirmed_history():
    cards = build_all_cards(
        [_product("CS-B14"), _product("NEW-1")],
        {"CS-B14": []},
    )

    assert len(cards) == 2
    assert {card["metadata"]["sku"] for card in cards} == {"CS-B14", "NEW-1"}
    empty_card = next(card for card in cards if card["metadata"]["sku"] == "NEW-1")
    assert empty_card["metadata"]["coverage_status"] == "no_confirmed_history"
    assert "待积累" in empty_card["title"]


def test_card_records_catalog_signal_counts_without_copying_fact_or_chat_text():
    card = build_experience_card(
        _product("NEW-1"),
        [],
        catalog_signals={
            "qa_total": 9,
            "qa_approved": 7,
            "qa_rejected": 1,
            "qa_review": 1,
            "customer_service_conversations": 3,
            "customer_service_messages": 8,
        },
    )

    assert card["metadata"]["catalog_signal_counts"]["qa_approved"] == 7
    assert "已审核商品 QA 7 条" in card["content"]
    assert "客服会话 3 条、消息 8 条" in card["content"]
    assert "原问答" in card["content"]


def test_outcome_insights_separate_explicit_conversion_from_library_labels():
    insights = _role_insights([
        {
            "_libraries": {"07_01"},
            "result": {"conversion": True},
            "intent": "选购",
            "styleSignals": ["先给结论"],
        },
        {
            "_libraries": {"07_01"},
            "result": {"conversion": None},
            "intent": "评价",
        },
        {
            "_libraries": {"07_02"},
            "result": {"conversion": False},
            "reasonCategory": "价格疑问",
        },
    ])

    assert insights["conversion_samples"] == 2
    assert insights["confirmed_conversion_samples"] == 1
    assert insights["non_conversion_samples"] == 1
    assert insights["confirmed_non_conversion_samples"] == 1


def test_uncovered_product_gets_an_inferred_conversion_hypothesis():
    card = build_experience_card(
        _product("NEW-1"),
        [],
        catalog_signals={
            "qa_approved": 4,
            "qa_topic_counts": {"规格与容量": 3},
            "conversation_topic_counts": {},
        },
        global_insights={
            "conversion_styles": ["先给结论", "给出下一步"],
            "non_conversion_reasons": ["规格/参数信息未完成"],
        },
    )

    assert card["metadata"]["coverage_status"] == "inferred_from_catalog_and_global"
    assert card["metadata"]["insight_status"] == "inferred_from_same_sku_catalog_and_global"
    assert "推导型经验卡" in card["content"]
    assert "转化假设（待验证）" in card["content"]
    assert "规格与容量" in card["content"]
    assert "真实转化率" in card["content"]
