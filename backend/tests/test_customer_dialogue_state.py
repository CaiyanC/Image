import unittest

from app.services import customer_dialogue_state


class CustomerDialogueStateTest(unittest.TestCase):
    def test_budget_followup_inherits_previous_need(self):
        history = [
            {"role": "user", "content": "三个年轻人露营，适合什么锅？"},
            {"role": "assistant", "content": "推荐 CW-C05-37。"},
        ]

        state = customer_dialogue_state.build_dialogue_state("预算不高", history)

        self.assertEqual(state.mode, "budget_followup")
        self.assertIn("三个年轻人露营", state.previous_user_need)
        self.assertIn("预算=low", state.summary)
        self.assertTrue(state.should_inherit_user_need)

        context = customer_dialogue_state.build_conversation_context("预算不高", history)
        self.assertEqual(context["mode"], "budget_followup")
        self.assertIn("预算/性价比追问", context["instruction"])
        self.assertIn("三个年轻人露营", context["previous_user_need"])

    def test_complete_new_need_does_not_inherit_previous_need(self):
        history = [
            {"role": "user", "content": "适合泡咖啡的小锅有哪些？"},
            {"role": "assistant", "content": "推荐 CW-C93。"},
        ]

        state = customer_dialogue_state.build_dialogue_state("适合四个人做饭的锅有哪些？", history)

        self.assertEqual(state.mode, "current_question")
        self.assertEqual(state.previous_user_need, "")
        self.assertFalse(state.should_inherit_user_need)
        self.assertEqual(state.summary, "人数=四人；场景=做饭；品类=锅")

    def test_previous_result_reference_detection(self):
        self.assertTrue(customer_dialogue_state.should_use_previous_result_skus("这款容量多少？"))
        self.assertTrue(customer_dialogue_state.needs_previous_context("这些有什么区别？"))
        self.assertFalse(customer_dialogue_state.should_use_previous_result_skus("锅具有哪些产品？"))
        self.assertFalse(customer_dialogue_state.needs_previous_context("还有其他锅推荐吗？"))

    def test_recommendation_question_with_context_uses_previous_need(self):
        history = [
            {"role": "user", "content": "适合三个人露营的锅有哪些？"},
            {"role": "assistant", "content": "CW-C05-37。"},
        ]

        merged = customer_dialogue_state.recommendation_question_with_context("预算不高", history)

        self.assertIn("适合三个人露营的锅有哪些？", merged)
        self.assertIn("预算不高", merged)

    def test_complete_low_budget_need_is_not_budget_followup(self):
        history = [
            {"role": "user", "content": "适合泡咖啡的小锅有哪些？"},
            {"role": "assistant", "content": "推荐 CW-C93。"},
        ]

        state = customer_dialogue_state.build_dialogue_state("适合四人预算不高的锅有哪些？", history)

        self.assertEqual(state.mode, "current_question")
        self.assertEqual(state.previous_user_need, "")
        self.assertEqual(state.budget, "low")
        self.assertEqual(state.quantity, "四人")

    def test_short_budget_query_without_history_does_not_claim_inheritance(self):
        state = customer_dialogue_state.build_dialogue_state("预算不高", [])

        self.assertEqual(state.mode, "current_question")
        self.assertEqual(state.previous_user_need, "")
        self.assertFalse(state.should_inherit_user_need)


if __name__ == "__main__":
    unittest.main()
