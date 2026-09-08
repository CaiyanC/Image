from unittest.mock import AsyncMock, patch

from app.core.config import settings
from app.services import customer_dynamic_answer_review_service, customer_llm_service


def _payload():
    return {
        "current_question": "两个人露营怎么选锅？",
        "evidence": [
            {
                "evidence_id": "e1",
                "sku": "CW-C94",
                "content": "容量2L，毛重370g。",
                "fact_authority": True,
                "authority_level": "canonical",
            }
        ],
        "candidate_products": [{"sku": "CW-C94", "product_name_cn": "轻量锅"}],
        "experience_guidance": [{
            "guidance_id": "case-1",
            "sku": "CW-C94",
            "guidance": "先说适用场景，再说明取舍。",
            "case_signal": {"signal_strength": "observed"},
        }],
    }


def test_review_is_model_driven_for_complex_answers():
    with patch.object(settings, "CUSTOMER_SERVICE_DYNAMIC_REVIEW_ENABLED", False):
        assert customer_dynamic_answer_review_service.should_review_response(
            {"answer": "建议选CW-C94。", "answer_type": "recommendation"},
            _payload(),
        ) is False

    with patch.object(settings, "CUSTOMER_SERVICE_DYNAMIC_REVIEW_ENABLED", True):
        assert customer_dynamic_answer_review_service.should_review_response(
            {
                "answer": "建议选CW-C94。",
                "answer_type": "recommendation",
                "quality_review": {"recommended": True},
            },
            _payload(),
        ) is True
        assert customer_dynamic_answer_review_service.should_review_response(
            {
                "answer": "建议选CW-C94。",
                "answer_type": "recommendation",
                "quality_review": {"recommended": False},
                "confidence": "high",
                "uncertainty": "confirmed",
            },
            _payload(),
        ) is False
        assert customer_dynamic_answer_review_service.should_review_response(
            {"answer": "容量是2L。", "answer_type": "product_detail", "confidence": "high", "uncertainty": "confirmed"},
            _payload(),
        ) is False


async def _review_once(review_result):
    with (
        patch.object(settings, "CUSTOMER_SERVICE_DYNAMIC_REVIEW_ENABLED", True),
        patch.object(
            customer_llm_service,
            "chat_completion",
            new=AsyncMock(return_value=review_result),
        ) as mocked,
    ):
        result, metadata = await customer_dynamic_answer_review_service.review_answer(
            object(),
            question="两个人露营怎么选锅？",
            payload=_payload(),
            response={
                "answer": "建议选CW-C94。",
                "answer_type": "recommendation",
                "selected_skus": ["CW-C94"],
                "evidence_ids": ["e1"],
                "confidence": "medium",
                "uncertainty": "partial",
                "quality_review": {"recommended": True},
            },
        )
    return result, metadata, mocked


def test_review_can_revise_without_replacing_structured_selection():
    import asyncio

    result, metadata, mocked = asyncio.run(_review_once(
        '{"decision":"revise","answer":"两个人露营优先推荐 CW-C94，容量是2L、毛重约370g；如果更看重轻量，再告诉我，我可以继续比较。","issues":["缺少取舍"],"confidence":"high"}'
    ))

    assert "两个人露营优先推荐" in result["answer"]
    assert result["selected_skus"] == ["CW-C94"]
    assert result["evidence_ids"] == ["e1"]
    assert metadata["changed"] is True
    assert mocked.await_args.kwargs["purpose"] == "customer_service_dynamic_answer_review"


def test_review_failure_keeps_original_answer():
    import asyncio

    result, metadata, _mocked = asyncio.run(_review_once(
        '{"decision":"keep","answer":"","issues":[]}'
    ))

    assert result["answer"] == "建议选CW-C94。"
    assert metadata["changed"] is False
    assert metadata["decision"] == "keep"
