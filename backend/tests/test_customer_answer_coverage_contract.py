from app.services import customer_answer_coverage_contract, customer_service_service


def test_fully_answered_compound_contract_adds_no_missing_boundary():
    contract = customer_answer_coverage_contract.build_answer_coverage_contract(
        ["durability", "whether boiling water is supported"],
        answered_requests=[
            ("durability", "qa:durability"),
            ("whether boiling water is supported", "qa:temperature"),
        ],
        unsupported_requests=[],
    )
    answer = (
        "It is durable in normal use.\n"
        "Its recorded temperature range excludes boiling water, so boiling water is not supported."
    )

    assert contract.unsupported_request_texts == ()
    assert customer_answer_coverage_contract.append_unsupported_boundaries(
        answer,
        contract,
    ) == answer


def test_partially_answered_compound_contract_adds_only_unsupported_boundary():
    contract = customer_answer_coverage_contract.build_answer_coverage_contract(
        ["durability", "whether freezing is supported"],
        answered_requests=[("durability", "qa:durability")],
        unsupported_requests=["whether freezing is supported"],
    )

    answer = customer_answer_coverage_contract.append_unsupported_boundaries(
        "It is durable in normal use.",
        contract,
    )

    assert "durability" not in answer
    assert "whether freezing is supported" in answer
    assert answer.count("当前同 SKU 资料未直接确认") == 1


def test_answered_request_cannot_also_be_marked_unsupported():
    try:
        customer_answer_coverage_contract.build_answer_coverage_contract(
            ["durability"],
            answered_requests=[("durability", "qa:durability")],
            unsupported_requests=["durability"],
        )
    except ValueError as exc:
        assert "both answered and unsupported" in str(exc)
    else:
        raise AssertionError("conflicting request coverage must be rejected")


def test_final_answer_uses_evidence_coverage_instead_of_query_substring():
    contract = customer_answer_coverage_contract.build_answer_coverage_contract(
        ["耐用性", "能否直接灌沸水"],
        answered_requests=[
            ("耐用性", "qa:durability"),
            ("能否直接灌沸水", "qa:temperature"),
        ],
        unsupported_requests=[],
    )
    result = {
        "answer": (
            "正常使用非常耐用。\n"
            "耐温范围约为0°C至60°C，因此不能直接灌沸水。"
        ),
        "answer_metadata": {
            "answer_coverage_contract": contract.to_dict(),
        },
    }

    finalized = customer_service_service._apply_answer_coverage_contract(result)

    assert finalized["answer"].endswith("因此不能直接灌沸水。")
    assert "当前同 SKU 资料未直接确认" not in finalized["answer"]
