from app.services import customer_service_service


def test_retry_is_skipped_when_agent_already_has_results():
    agent_result = {
        "intent": "compare_products",
        "answer": "These products target different customers.",
        "results": [{"sku": "HIGH-1"}, {"sku": "ENTRY-1"}],
        "warnings": ["missing_product_results"],
        "confidence": "low",
    }

    assert customer_service_service._should_retry_with_deterministic_agent(agent_result) is False


def test_retry_is_skipped_when_agent_already_has_usable_answer():
    agent_result = {
        "intent": "compare_products",
        "answer": "High-end models fit premium buyers; entry models fit price-sensitive buyers.",
        "results": [],
        "warnings": ["missing_product_results"],
        "confidence": "low",
    }

    assert customer_service_service._should_retry_with_deterministic_agent(agent_result) is False


def test_retry_still_runs_when_agent_has_no_results_or_answer():
    agent_result = {
        "intent": "compare_products",
        "answer": "",
        "results": [],
        "warnings": ["missing_product_results"],
        "confidence": "low",
    }

    assert customer_service_service._should_retry_with_deterministic_agent(agent_result) is True


def test_retry_still_runs_when_answer_is_no_result_placeholder():
    agent_result = {
        "intent": "recommend_products",
        "answer": "没有找到足够匹配的产品资料。",
        "results": [],
        "warnings": ["missing_product_results"],
        "confidence": "low",
    }

    assert customer_service_service._should_retry_with_deterministic_agent(agent_result) is True


def test_deterministic_retry_result_preserves_skip_polish():
    retry_result = {
        "intent": "recommend_products",
        "answer": "Use the following recommendations.",
        "results": [{"sku": "SKU-1"}],
        "skip_polish": False,
    }

    prepared = customer_service_service._prepare_deterministic_retry_result(retry_result)

    assert prepared["skip_polish"] is True
    assert retry_result["skip_polish"] is False
