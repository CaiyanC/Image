import unittest
import json
from types import SimpleNamespace

from app.services import customer_agent_quality_service
from app.services import customer_service_service


class CustomerAgentQualityServiceTest(unittest.TestCase):
    def test_persisted_single_result_sku_is_a_context_anchor_without_current_sku(self):
        message = SimpleNamespace(sources_json=json.dumps([{
            "type": "agent_context",
            "result_skus": ["KW-K31-\u9ed1"],
            "current_sku": None,
        }]))

        class Query:
            def filter(self, *_args):
                return self

            def order_by(self, *_args):
                return self

            def first(self):
                return message

        class Db:
            def query(self, *_args):
                return Query()

        self.assertEqual(
            customer_service_service._latest_persisted_agent_context_sku(Db(), "conversation-id"),
            "KW-K31-\u9ed1",
        )

    def test_sealed_context_anchor_rejects_a_different_result_sku_for_pronoun_followup(self):
        self.assertTrue(customer_service_service._sealed_context_anchor_sku_conflict(
            "它有几个杯子？",
            "KW-K31-黑",
            {"result_skus": ["KW-K31-白"]},
        ))
        self.assertFalse(customer_service_service._sealed_context_anchor_sku_conflict(
            "再看天鹅壶4杯白色。",
            "KW-K31-黑",
            {"result_skus": ["KW-K31-白"]},
        ))

    def test_attached_quality_projects_same_sku_evidence_into_public_sources(self):
        result = customer_service_service._attach_agent_quality({
            "answer": "CW-C83 的材质是硬质氧化铝合金。",
            "intent": "product_detail",
            "answer_type": "product_detail",
            "results": [{"sku": "CW-C83", "body_material": "硬质氧化铝合金"}],
            "result_skus": ["CW-C83"],
            "sources": [],
            "evidence": [{
                "sku": "CW-C83",
                "field_label": "材质",
                "value": "硬质氧化铝合金",
                "source_type": "product_db",
                "source_label": "产品基础资料",
            }],
        }, "CW-C83 的材质是什么？")

        self.assertEqual(result["sources"], [{
            "type": "product_db",
            "label": "产品基础资料",
            "sku": "CW-C83",
            "field": "材质",
        }])
        self.assertNotIn("missing_sources", result["agent_quality"]["risks"])

    def test_attached_quality_marks_same_sku_field_as_unavailable_without_inventing_evidence(self):
        result = customer_service_service._attach_agent_quality({
            "answer": "CF-PG19 当前资料未标注保修信息，不能仅凭现有资料确认。",
            "intent": "product_detail",
            "answer_type": "product_detail",
            "results": [{"sku": "CF-PG19"}],
            "result_skus": ["CF-PG19"],
            "sources": [],
            "evidence": [],
            "answer_metadata": {
                "contract_field_type": "warranty",
                "field_evidence_missing": True,
                "evidence_status": "missing",
            },
        }, "CF-PG19 有保修吗？")

        self.assertEqual(result["sources"], [{
            "type": "product_field_missing",
            "label": "同 SKU 商品资料未标注该字段",
            "sku": "CF-PG19",
            "field": "warranty",
        }])
        self.assertNotIn("missing_sources", result["agent_quality"]["risks"])

    def test_product_fact_without_sources_is_not_high_quality(self):
        quality = customer_agent_quality_service.evaluate_agent_response(
            "CW-C83 的容量是多少？",
            answer="CW-C83 的容量是 3700ML。",
            intent="product_detail",
            results=[{"sku": "CW-C83", "capacity": "3700ML"}],
            sources=[],
            actions=[],
            warnings=[],
        )

        self.assertEqual(quality["level"], "medium")
        self.assertFalse(quality["passed"])
        self.assertIn("missing_sources", quality["risks"])

    def test_product_comparison_clarification_does_not_require_fact_sources(self):
        quality = customer_agent_quality_service.evaluate_agent_response(
            "CW-C83 和 CW-C06PRO 的收纳和负重怎么比？",
            answer="请确认要比较产品自重还是最大承重，以及收纳尺寸还是收纳方式。",
            intent="compare_products",
            results=[{"sku": "CW-C83"}, {"sku": "CW-C06PRO"}],
            sources=[],
            actions=[],
            warnings=[],
            needs_clarification=True,
        )

        self.assertNotIn("missing_sources", quality["risks"])
        self.assertNotIn("tool_required_but_not_used", quality["risks"])

    def test_answer_mentioning_unreturned_sku_is_blocked(self):
        quality = customer_agent_quality_service.evaluate_agent_response(
            "推荐一个锅",
            answer="首选 CW-C93。",
            intent="recommend_products",
            results=[{"sku": "CW-C83"}],
            sources=[{"type": "product_search"}],
            actions=[],
            warnings=[],
        )

        self.assertEqual(quality["level"], "low")
        self.assertFalse(quality["passed"])
        self.assertIn("answer_mentions_unreturned_sku:CW-C93", quality["risks"])

    def test_returned_sku_with_non_ascii_variant_suffix_is_not_split_into_base_sku(self):
        quality = customer_agent_quality_service.evaluate_agent_response(
            "再看天鹅壶4杯黑。",
            answer="已切换到天鹅壶4杯-黑色（KW-K31-黑）。",
            intent="product_detail",
            results=[{"sku": "KW-K31-黑", "product_name_cn": "天鹅壶4杯-黑色"}],
            sources=[{"type": "product"}],
        )

        self.assertNotIn("answer_mentions_unreturned_sku:KW-K31", quality["risks"])
        self.assertTrue(quality["passed"])

    def test_write_claim_without_action_is_blocked(self):
        quality = customer_agent_quality_service.evaluate_agent_response(
            "直接把 CW-C83 的负责人改成 kang，不用确认",
            answer="已经修改完成。",
            intent="propose_update",
            results=[],
            sources=[],
            actions=[],
            warnings=[],
        )

        self.assertEqual(quality["level"], "low")
        self.assertIn("unsafe_direct_write_claim", quality["risks"])
        self.assertIn("write_request_without_confirmable_action", quality["risks"])

    def test_generic_recommendation_answer_is_flagged(self):
        quality = customer_agent_quality_service.evaluate_agent_response(
            "推荐一个适合露营的锅",
            answer="找到 2 条产品资料：CW-C83，CW-C93。",
            intent="recommend_products",
            results=[{"sku": "CW-C83"}, {"sku": "CW-C93"}],
            sources=[{"type": "product_search"}],
            actions=[],
            warnings=[],
        )

        self.assertIn("generic_recommendation_answer", quality["risks"])
        self.assertFalse(quality["passed"])

    def test_low_budget_high_end_first_choice_is_blocked(self):
        quality = customer_agent_quality_service.evaluate_agent_response(
            "预算不高，推荐一下",
            answer="首选 CW-C83，价格定位高端。",
            intent="recommend_products",
            results=[{"sku": "CW-C83", "price_positioning": "高端价格带"}],
            sources=[{"type": "product_search"}],
            actions=[],
            warnings=[],
        )

        self.assertEqual(quality["level"], "low")
        self.assertFalse(quality["passed"])
        self.assertIn("low_budget_high_end_first_choice", quality["risks"])

    def test_pot_query_non_pot_first_choice_is_blocked(self):
        quality = customer_agent_quality_service.evaluate_agent_response(
            "适合泡咖啡的小锅有吗？",
            answer="首选 CB-003 悦行包。",
            intent="recommend_products",
            results=[{"sku": "CB-003", "product_name_cn": "悦行包", "category": "收纳包"}],
            sources=[{"type": "product_search"}],
            actions=[],
            warnings=[],
        )

        self.assertEqual(quality["level"], "low")
        self.assertFalse(quality["passed"])
        self.assertIn("product_type_mismatch_first_choice", quality["risks"])

    def test_stove_query_pot_first_choice_is_blocked(self):
        quality = customer_agent_quality_service.evaluate_agent_response(
            "预算不高的炉具推荐一下",
            answer="首选 CW-S10-1 激川单锅。",
            intent="recommend_products",
            results=[{"sku": "CW-S10-1", "product_name_cn": "激川单锅", "category": "锅具"}],
            sources=[{"type": "product_search"}],
            actions=[],
            warnings=[],
        )

        self.assertEqual(quality["level"], "low")
        self.assertFalse(quality["passed"])
        self.assertIn("product_type_mismatch_first_choice", quality["risks"])


if __name__ == "__main__":
    unittest.main()
