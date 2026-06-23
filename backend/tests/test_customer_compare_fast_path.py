from app.services import customer_agent_runtime_service, product_service


def test_compare_fast_path_picks_high_and_entry_from_context(monkeypatch):
    details = {
        "HIGH-1": {"sku": "HIGH-1", "business": {"price_positioning": "高端"}},
        "ENTRY-1": {"sku": "ENTRY-1", "business": {"price_positioning": "入门"}},
        "MID-1": {"sku": "MID-1", "business": {"price_positioning": "中端"}},
    }

    monkeypatch.setattr(product_service, "get_product_detail", lambda db, sku: details[sku])

    skus = customer_agent_runtime_service._context_compare_fast_path_skus(
        None,
        "对比一下高端和入门款，分别适合什么客户",
        [{"sku": "MID-1"}, {"sku": "HIGH-1"}, {"sku": "ENTRY-1"}],
        {},
    )

    assert skus == ["HIGH-1", "ENTRY-1"]


def test_compare_fast_path_falls_back_to_lowest_positioned_context_sku(monkeypatch):
    details = {
        "HIGH-1": {"sku": "HIGH-1", "business": {"price_positioning": "高端"}},
        "MID-1": {"sku": "MID-1", "business": {"price_positioning": "中端"}},
        "HIGH-2": {"sku": "HIGH-2", "business": {"price_positioning": "高端"}},
    }

    monkeypatch.setattr(product_service, "get_product_detail", lambda db, sku: details[sku])

    skus = customer_agent_runtime_service._context_compare_fast_path_skus(
        None,
        "对比一下高端和入门款，分别适合什么客户",
        [{"sku": "HIGH-1"}, {"sku": "MID-1"}, {"sku": "HIGH-2"}],
        {},
    )

    assert skus == ["HIGH-1", "MID-1"]


def test_compare_fast_path_falls_back_to_second_context_sku_when_all_high(monkeypatch):
    details = {
        "HIGH-1": {"sku": "HIGH-1", "business": {"price_positioning": "高端"}},
        "HIGH-2": {"sku": "HIGH-2", "business": {"price_positioning": "高端"}},
    }

    monkeypatch.setattr(product_service, "get_product_detail", lambda db, sku: details[sku])

    skus = customer_agent_runtime_service._context_compare_fast_path_skus(
        None,
        "对比一下高端和入门款，分别适合什么客户",
        [{"sku": "HIGH-1"}, {"sku": "HIGH-2"}],
        {},
    )

    assert skus == ["HIGH-1", "HIGH-2"]


def test_compare_fast_path_uses_exactly_two_context_skus():
    skus = customer_agent_runtime_service._context_compare_fast_path_skus(
        None,
        "这两款哪个更轻",
        [{"sku": "CW-C83"}, {"sku": "CW-C01-37"}],
        {},
    )

    assert skus == ["CW-C83", "CW-C01-37"]


def test_compare_fast_path_skips_ambiguous_question_without_context():
    skus = customer_agent_runtime_service._context_compare_fast_path_skus(
        None,
        "哪个更适合新手",
        [],
        {},
    )

    assert skus == []


def test_recommend_with_difference_request_is_not_compare_like():
    assert not customer_agent_runtime_service._is_compare_like_question(
        "推荐三款适合露营多人做饭的套锅，并说明区别"
    )


def test_explicit_two_sku_question_is_compare_like():
    assert customer_agent_runtime_service._is_compare_like_question(
        "CW-C83和CW-C01-37哪个更轻"
    )


def test_context_two_sku_question_is_compare_like(monkeypatch):
    details = {
        "HIGH-1": {"sku": "HIGH-1", "business": {"price_positioning": "高端"}},
        "ENTRY-1": {"sku": "ENTRY-1", "business": {"price_positioning": "入门"}},
        "MID-1": {"sku": "MID-1", "business": {"price_positioning": "中端"}},
    }

    monkeypatch.setattr(product_service, "get_product_detail", lambda db, sku: details[sku])

    skus = customer_agent_runtime_service._context_compare_fast_path_skus(
        None,
        "对比一下刚才推荐的高端和入门款",
        [{"sku": "MID-1"}, {"sku": "HIGH-1"}, {"sku": "ENTRY-1"}],
        {},
    )

    assert skus == ["HIGH-1", "ENTRY-1"]
