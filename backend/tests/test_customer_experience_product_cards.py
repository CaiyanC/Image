from types import SimpleNamespace

from scripts.seed_customer_experience_product_cards_20260905 import (
    build_all_cards,
    build_experience_card,
    build_topic_experience_card,
    _experience_topic_labels,
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


def test_topic_grouping_prefers_source_intent_over_terms_in_review_text():
    assert _experience_topic_labels({
        "intent": "套装与配件",
        "question": "客户同时提到容量、热源和轻便，客服如何回复？",
    }) == ["套装与配件"]


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


def test_topic_card_scopes_outcome_signals_without_copying_source_answers():
    samples = [
        {
            "qaId": "q1",
            "quality": "good",
            "recordType": "客服对话",
            "intent": "选购与推荐",
            "result": {"conversion": True},
            "styleSignals": ["先给结论"],
            "answer": "这段成功原话不应进入主题卡",
            "_libraries": {"07_01"},
            "_source_record_ids": ["r1"],
        },
        {
            "qaId": "q2",
            "quality": "neutral",
            "recordType": "客服对话",
            "intent": "选购与推荐",
            "result": {"conversion": False},
            "reasonCategory": "选购匹配未完成",
            "answer": "这段未转化原话不应进入主题卡",
            "_libraries": {"07_02"},
            "_source_record_ids": ["r2"],
        },
        {
            "qaId": "q3",
            "quality": "bad",
            "recordType": "客服对话",
            "intent": "选购与推荐",
            "result": {"satisfaction": "不满意"},
            "failureReason": "推荐依据不清",
            "answer": "这段差评原话不应进入主题卡",
            "_libraries": {"07_03"},
            "_source_record_ids": ["r3"],
        },
    ]

    card = build_topic_experience_card(
        _product(),
        "场景与选购匹配",
        samples,
    )

    assert card["metadata"]["card_kind"] == "product_topic"
    assert card["metadata"]["topic_label"] == "场景与选购匹配"
    assert card["metadata"]["conversion_insights"]["outcome_sample_count"] == 3
    assert card["metadata"]["conversion_insights"]["confirmed_conversion_samples"] == 1
    assert card["metadata"]["conversion_insights"]["confirmed_non_conversion_samples"] == 1
    assert "成功原话" not in card["content"]
    assert "未转化原话" not in card["content"]
    assert "差评原话" not in card["content"]
    assert "当前 SKU 的事实证据" in card["content"]


def test_build_all_cards_adds_narrow_cards_for_strict_and_inferred_products():
    strict_samples = [
        {
            "qaId": f"strict-{index}",
            "recordType": "客服对话",
            "intent": "选购与推荐",
            "_libraries": {"07_01" if index == 0 else "07_02"},
            "result": {"conversion": index == 0},
        }
        for index in range(3)
    ]
    cards = build_all_cards(
        [_product("CS-B14"), _product("NEW-1")],
        {"CS-B14": strict_samples},
        catalog_signals_by_sku={
            "NEW-1": {
                "qa_approved": 4,
                "qa_topic_counts": {"规格与容量": 5, "使用与安全": 4},
                "conversation_topic_counts": {},
            }
        },
    )

    topic_cards = [
        card for card in cards
        if card["metadata"].get("card_kind") == "product_topic"
    ]
    strict_topic = next(
        card for card in topic_cards
        if card["metadata"]["sku"] == "CS-B14"
    )
    inferred_topics = [
        card for card in topic_cards
        if card["metadata"]["sku"] == "NEW-1"
    ]
    assert strict_topic["metadata"]["coverage_status"] == "history_available"
    assert strict_topic["metadata"]["topic_sample_count"] == 3
    assert len(inferred_topics) == 2
    assert all(
        card["metadata"]["coverage_status"] == "inferred_from_catalog_and_global"
        for card in inferred_topics
    )
