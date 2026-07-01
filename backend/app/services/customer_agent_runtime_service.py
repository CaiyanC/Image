import json
import re
from time import perf_counter
from typing import Any, Awaitable, Callable

from sqlalchemy.orm import Session

from . import (
    agent_trace_service,
    customer_agent_intent_service,
    customer_agent_service,
    customer_agent_quality_service,
    customer_agent_tool_service,
    customer_dialogue_state,
    knowledge_service,
    customer_price_signal,
    customer_recommendation_ranker,
    customer_llm_service,
    customer_perf_service,
    product_service,
)
from ..models.knowledge_base import CustomerServiceConversation, CustomerServiceMessage, KnowledgeChunk
from ..models.product import Product


MAX_TOOL_ROUNDS = 4
WRITE_TOOL_PREFIXES = ("propose_",)
PRODUCT_LOOKUP_TERMS = (
    "适合", "推荐", "哪些", "有没有", "有吗", "容量", "材质", "卖点", "场景",
    "做饭", "烹饪", "煮饭", "炒菜", "露营", "徒步", "锅", "炉", "咖啡", "泡咖啡",
)
PRODUCT_WRITE_TERMS = ("修改", "改成", "改为", "删除", "删掉", "清空", "取消")
COFFEE_TERMS = ("咖啡", "泡咖啡")
COOKING_TERMS = ("做饭", "烹饪", "煮饭", "炒菜", "煮东西")
CONFIRMATION_TERMS = ("是的", "对", "对的", "确认", "嗯", "可以", "没错")
SKU_RE = re.compile(r"\b[A-Z]{1,6}(?:-[A-Z0-9]{1,8}){1,4}\b", flags=re.IGNORECASE)


async def process_agent_request(
    db: Session,
    *,
    user_id: str,
    conversation_id: str | None = None,
    question: str,
    sku: str | None = None,
    previous_result_skus: list[str] | None = None,
    entity_stack: list[dict] | None = None,
    conversation_history: list[dict] | None = None,
    feedback_lessons: list[dict] | None = None,
    recognized_intent: str | None = None,
    answer_delta_callback: Callable[[str], Awaitable[None]] | None = None,
) -> dict | None:
    request_start = perf_counter()
    previous_result_skus = previous_result_skus or []
    entity_stack = entity_stack or []
    conversation_history = conversation_history or []
    last_turn_summary = _last_turn_summary(db, conversation_id, user_id)
    recommendation_context = _latest_recommendation_context(db, conversation_id, user_id)
    candidate_context = _latest_candidate_context(db, conversation_id, user_id)
    recommendation_context_skus = (
        recommendation_context.get("ordered_result_skus")
        or recommendation_context.get("candidate_skus")
        or recommendation_context.get("recommended_skus")
        or []
    )
    recommendation_summary = (
        {
            "intent": "recommend_products",
            "result_skus": recommendation_context_skus,
            "recommended_skus": recommendation_context.get("recommended_skus") or [],
            "candidate_skus": recommendation_context.get("candidate_skus") or recommendation_context_skus,
            "ordered_result_skus": recommendation_context.get("ordered_result_skus") or recommendation_context_skus,
            "user_question": recommendation_context.get("user_question"),
            "product_scope": recommendation_context.get("product_scope"),
            "assistant_answer": last_turn_summary.get("assistant_answer"),
        }
        if recommendation_context_skus
        else last_turn_summary
    )
    explanation_summary = (
        recommendation_summary
        if recommendation_summary.get("intent") == "recommend_products"
        and (recommendation_summary.get("result_skus") or [])
        else last_turn_summary
    )
    empty_subset_context = recommendation_context if recommendation_context.get("empty_subset") else candidate_context
    if empty_subset_context.get("empty_subset") and _is_empty_subset_followup(question):
        return _scoped_candidate_context_result(
            question,
            sku,
            [],
            "\u4e0a\u4e00\u8f6e\u5728\u8fd9\u4e9b\u5019\u9009\u4e2d\u5df2\u7ecf\u6ca1\u6709\u7b5b\u5230\u660e\u786e\u7b26\u5408\u6761\u4ef6\u7684\u4ea7\u54c1\uff0c\u56e0\u6b64\u65e0\u6cd5\u7ee7\u7eed\u5728\u8be5\u7a7a\u7ed3\u679c\u91cc\u6bd4\u8f83\u6700\u8f7b\u6216\u63a8\u8350\u66ff\u4ee3\u3002\u53ef\u4ee5\u653e\u5bbd\u4e0a\u4e00\u8f6e\u6761\u4ef6\uff0c\u6216\u91cd\u65b0\u6307\u5b9a\u8303\u56f4\u3002",
            empty_subset_context,
            conversation_history=conversation_history,
        )
    scoped_candidate_result = await _handle_scoped_candidate_followup(
        db,
        user_id=user_id,
        question=question,
        sku=sku,
        candidate_context=candidate_context,
        conversation_history=conversation_history,
    )
    if scoped_candidate_result:
        return scoped_candidate_result
    ordinal_compare_targets = _ordinal_compare_targets_from_context(
        question,
        recommendation_context,
        candidate_context,
    )
    if ordinal_compare_targets:
        compare_fields = _ordinal_compare_detail_fields(question)
        arguments = {"skus": ordinal_compare_targets[:2], "fields": compare_fields}
        result = await customer_agent_tool_service.execute_tool_async(
            db,
            user_id=user_id,
            name="get_product_detail",
            arguments=arguments,
        )
        deterministic_compare_answer = _compose_deterministic_ordinal_compare_answer(question, _collect_results([result]))
        return _build_result(
            question,
            None,
            [result],
            deterministic_compare_answer,
            [_step_from_tool_result("get_product_detail", arguments, result)],
            conversation_history=conversation_history,
            intent_override="compare_products",
            preserve_llm_answer=True,
        )
    early_followup_domain = [
        str(item or "").strip().upper()
        for item in (
            recommendation_summary.get("candidate_skus")
            or recommendation_summary.get("ordered_result_skus")
            or recommendation_summary.get("result_skus")
            or []
        )
        if str(item or "").strip()
    ]
    if early_followup_domain and _is_recommendation_change_followup_text(question):
        excluded_followup_skus = [
            str(item or "").strip().upper()
            for item in (
                recommendation_summary.get("recommended_skus")
                or recommendation_summary.get("ordered_result_skus")
                or []
            )[:1]
            if str(item or "").strip()
        ]
        scoped_followup_domain = [
            sku_code
            for sku_code in early_followup_domain
            if sku_code not in set(excluded_followup_skus)
        ] or early_followup_domain
        deterministic_followup = await customer_agent_intent_service.process_intent_request(
            db,
            user_id=user_id,
            question=question,
            sku=sku,
            previous_result_skus=scoped_followup_domain,
            allow_llm_fallback=False,
        )
        if deterministic_followup and deterministic_followup.get("intent") in {"recommend_products", "query_products"}:
            return deterministic_followup
    explicit_product_detection = _detect_explicit_product_mention(db, question, entity_stack)
    route_hints = _build_route_hints(question, explicit_product_detection, entity_stack)
    dialogue_state = customer_dialogue_state.build_dialogue_state(question, conversation_history)
    local_resolved_skus: list[str] = []
    direct_detail_skus = (
        _ordinal_skus_from_conversation_history(question, conversation_history)
        or _entity_stack_direct_detail_skus(question, entity_stack)
    )
    if (
        direct_detail_skus
        and not _is_explanation_followup(question, explanation_summary)
        and _can_use_entity_stack_direct_detail(
            question,
            route_hints,
            recommendation_summary,
            direct_detail_skus,
        )
    ):
        fields = (
            _context_detail_fields(question, conversation_history)
            or _context_requested_fields_from_intent(question, direct_detail_skus)
            or (_safety_detail_fields() if _is_safety_usage_followup(question) else [])
        )
        arguments = {"skus": direct_detail_skus[:1], "fields": fields}
        result = await customer_agent_tool_service.execute_tool_async(
            db,
            user_id=user_id,
            name="get_product_detail",
            arguments=arguments,
        )
        direct_route_hints = dict(route_hints or {})
        direct_route_hints["entity_stack_direct_detail"] = True
        direct_route_hints["resolved_skus"] = direct_detail_skus[:1]
        if fields:
            direct_answer = _direct_heat_source_support_answer(question, result)
            if direct_answer is None and any(term in str(question or "") for term in ("酒精炉", "酒精")) and any(
                term in str(question or "") for term in ("能用", "可以用", "支持", "适合", "能不能", "是否支持")
            ):
                inline_rows = _collect_results([result])
                if len(inline_rows) == 1 and isinstance(inline_rows[0], dict):
                    inline_item = inline_rows[0]
                    inline_field_values = inline_item.get("field_values") if isinstance(inline_item.get("field_values"), dict) else {}
                    inline_heat_source = str(inline_field_values.get("热源") or inline_field_values.get("燃料") or "").strip()
                    if not inline_heat_source:
                        inline_heat_source = str(((inline_item.get("specs") or {}).get("heat_source") or "")).strip()
                    inline_name = inline_item.get("product_name_cn") or inline_item.get("product_name_en") or ""
                    inline_prefix = f"{inline_name}（{inline_item.get('sku')}）" if inline_name else str(inline_item.get("sku") or "").strip()
                    if inline_heat_source and inline_heat_source != "暂无":
                        if "酒精炉" in inline_heat_source or "酒精" in inline_heat_source:
                            direct_answer = f"{inline_prefix}：支持酒精炉。当前资料显示适用热源为{inline_heat_source}。"
                        else:
                            direct_answer = f"{inline_prefix}：当前资料未显示支持酒精炉。当前资料显示适用热源为{inline_heat_source}。"
                    else:
                        direct_answer = f"{inline_prefix}：当前资料暂未提供是否支持酒精炉。"
            deterministic_result = _build_result(
                question,
                direct_detail_skus[0],
                [result],
                direct_answer,
                [_step_from_tool_result("get_product_detail", arguments, result)],
                conversation_history=conversation_history,
                intent_override="product_detail",
                preserve_llm_answer=bool(direct_answer),
            )
            debug = dict(deterministic_result.get("debug") or {})
            debug["agent_mode"] = "deterministic_entity_stack_detail"
            deterministic_result["debug"] = debug
            return deterministic_result
        return await _build_result_async(
            db,
            question,
            direct_detail_skus[0],
            [result],
            None,
            [_step_from_tool_result("get_product_detail", arguments, result)],
            conversation_history=conversation_history,
            conversation_id=conversation_id,
            user_id=user_id,
            intent_override="product_detail",
            intent_hint="product_detail",
            entity_stack=entity_stack,
            route_hints=direct_route_hints,
            answer_delta_callback=answer_delta_callback,
        )
    if _is_explanation_followup(question, explanation_summary):
        explanation_skus = _explanation_followup_skus(question, explanation_summary)
        detail_results = []
        for sku_item in explanation_skus[:5]:
            result = await customer_agent_tool_service.execute_tool_async(
                db,
                user_id=user_id,
                name="get_product_detail",
                arguments={
                    "skus": [sku_item],
                    "fields": [
                        "specs.capacity",
                        "specs.body_material",
                        "specs.heat_source",
                        "specs.power",
                        "business.top_selling_points",
                        "business.usage_scenarios",
                        "business.target_audience",
                        "business.positioning",
                        "business.price_positioning",
                    ],
                },
            )
            detail_results.append(result)
        if detail_results:
            result = await _build_result_async(
                db,
                question,
                None,
                detail_results,
                None,
                [],
                conversation_history=conversation_history,
                conversation_id=conversation_id,
                user_id=user_id,
                intent_override="product_detail",
                preserve_llm_answer=True,
                route_hints={"explanation_followup": True, "followup_target_skus": explanation_skus[:5]},
                answer_delta_callback=answer_delta_callback,
            )
            explanation_rows = _collect_results(detail_results) or []
            if _is_plural_recommendation_explanation(question) and len(explanation_rows) > 1:
                followup_answer = _compose_multi_recommendation_explanation_answer(
                    question,
                    explanation_rows,
                    explanation_summary,
                )
            else:
                followup_row = explanation_rows[0] if explanation_rows else {}
                followup_answer = _compose_recommendation_explanation_answer(
                    question,
                    followup_row,
                    explanation_summary,
                )
            if followup_answer:
                result["answer"] = followup_answer
                result["intent"] = "recommendation"
                result["answer_type"] = "recommendation"
            return result
    if explicit_product_detection["has_new_product"]:
        detected_skus = [
            str(item or "").strip().upper()
            for item in (explicit_product_detection.get("new_skus") or [])
            if str(item or "").strip()
        ]
        if _should_defer_explicit_product_to_intent_pipeline(question, detected_skus):
            return None
        if detected_skus:
            arguments = {"skus": detected_skus[:5], "fields": []}
            result = await customer_agent_tool_service.execute_tool_async(
                db,
                user_id=user_id,
                name="get_product_detail",
                arguments=arguments,
            )
            is_compare_detection = _is_compare_like_question(question, candidate_skus=detected_skus)
            return await _build_result_async(
                db,
                question,
                detected_skus[0] if len(detected_skus) == 1 else None,
                [result],
                None,
                [_step_from_tool_result("get_product_detail", arguments, result)],
                conversation_history=conversation_history,
                conversation_id=conversation_id,
                user_id=user_id,
                intent_override="compare_products" if len(detected_skus) > 1 and is_compare_detection else "product_detail",
                intent_hint="compare_products" if len(detected_skus) > 1 and is_compare_detection else "product_detail",
                preserve_llm_answer=bool(len(detected_skus) > 1 and is_compare_detection),
                entity_stack=entity_stack,
                route_hints=route_hints,
            )
        route_plan = {
            "resolved_skus": [],
            "reason": "explicit_product_detection: new product mention detected, skip conversation route LLM",
            "query_type": "unknown",
            "confidence": "medium",
            "explicit_product_detection": explicit_product_detection,
        }
        agent_trace_service.trace("CONVERSATION_ROUTE_PRECHECK", route_plan)
    elif len(explicit_product_detection.get("candidate_rows") or []) > 1:
        candidate_rows = explicit_product_detection.get("candidate_rows") or []
        candidate_skus = [
            str(item.get("sku") or "").strip().upper()
            for item in candidate_rows
            if isinstance(item, dict) and str(item.get("sku") or "").strip()
        ]
        if _should_defer_explicit_product_to_intent_pipeline(question, candidate_skus):
            return None
        if _is_compare_like_question(question, candidate_skus=candidate_skus) and 2 <= len(candidate_skus) <= 5:
            arguments = {"skus": candidate_skus[:5], "fields": []}
            result = await customer_agent_tool_service.execute_tool_async(
                db,
                user_id=user_id,
                name="get_product_detail",
                arguments=arguments,
            )
            return await _build_result_async(
                db,
                question,
                None,
                [result],
                None,
                [_step_from_tool_result("get_product_detail", arguments, result)],
                conversation_history=conversation_history,
                conversation_id=conversation_id,
                user_id=user_id,
                intent_override="compare_products",
                preserve_llm_answer=True,
                intent_hint="compare_products",
                entity_stack=entity_stack,
                route_hints=route_hints,
            )
        return _build_product_ambiguity_result(question, explicit_product_detection["candidate_rows"])
    else:
        if (
            recognized_intent == "recommend_products"
            and not dialogue_state.needs_clarification
            and not _is_compare_like_question(question)
        ):
            fast_start = perf_counter()
            semantic_query = _recommendation_question_with_context(question, conversation_history)
            parsed_intent = customer_agent_intent_service.parse_intent(question, previous_result_skus=[])
            fast_path_filters = (
                dict(parsed_intent.filters or {})
                if parsed_intent and parsed_intent.intent == "recommend_products"
                else {}
            )
            fast_path_term = (
                str(parsed_intent.term or "").strip()
                if parsed_intent and parsed_intent.intent == "recommend_products"
                else ""
            )
            arguments = _enrich_recommendation_tool_arguments(
                "hybrid_search_products",
                {
                    "term": fast_path_term,
                    "semantic_query": semantic_query,
                    "filters": fast_path_filters,
                    "limit": 20,
                },
                question,
                {"query_type": "recommendation"},
            )
            result = await customer_agent_tool_service.execute_tool_async(
                db,
                user_id=user_id,
                name="hybrid_search_products",
                arguments=arguments,
            )
            customer_perf_service.log_stage(
                "recommendation_fast_path",
                fast_start,
                hit=True,
                semantic_query=semantic_query,
                count=result.get("count") if isinstance(result, dict) else None,
            )
            return await _build_result_async(
                db,
                question,
                sku,
                [result],
                None,
                [_step_from_tool_result("hybrid_search_products", arguments, result)],
                conversation_history=conversation_history,
                conversation_id=conversation_id,
                user_id=user_id,
                intent_override="recommend_products",
                intent_hint="recommend_products",
                entity_stack=entity_stack,
            route_hints={"query_type": "recommendation", "fast_path": True},
            answer_delta_callback=answer_delta_callback,
        )
        compare_fast_path_skus = _context_compare_fast_path_skus(db, question, entity_stack, recommendation_summary)
        if (
            compare_fast_path_skus
            and (
                recognized_intent == "compare_products"
                or _is_compare_like_question(question, context_skus=compare_fast_path_skus)
            )
            and not dialogue_state.needs_clarification
            and not _requires_write_tool(question)
        ):
            compare_start = perf_counter()
            arguments = {
                "skus": compare_fast_path_skus[:5],
                "fields": [
                    "specs.capacity",
                    "specs.body_material",
                    "specs.gross_weight_g",
                    "business.top_selling_points",
                    "business.usage_scenarios",
                    "business.target_audience",
                    "business.price_positioning",
                    "business.positioning",
                ],
            }
            result = await customer_agent_tool_service.execute_tool_async(
                db,
                user_id=user_id,
                name="get_product_detail",
                arguments=arguments,
            )
            customer_perf_service.log_stage(
                "compare_fast_path",
                compare_start,
                hit=True,
                skus=compare_fast_path_skus[:5],
                count=result.get("count") if isinstance(result, dict) else None,
            )
            return await _build_result_async(
                db,
                question,
                None,
                [result],
                None,
                [_step_from_tool_result("get_product_detail", arguments, result)],
                conversation_history=conversation_history,
                conversation_id=conversation_id,
                user_id=user_id,
                intent_override="compare_products",
                intent_hint="compare_products",
                preserve_llm_answer=True,
                entity_stack=entity_stack,
                route_hints={"query_type": "comparison", "fast_path": True, "compare_fast_path": True},
                answer_delta_callback=answer_delta_callback,
            )
        if not conversation_history and not entity_stack and _is_specific_recommendation_question(question):
            route_plan = {}
            customer_perf_service.log_event("plan_conversation_route.skipped", reason="fresh_recommendation_question")
        else:
            plan_start = perf_counter()
            route_plan = await _plan_conversation_route(
                db,
                question,
                entity_stack,
                conversation_history,
                force_query_type=_may_need_specific_product_classification(question),
                recommendation_context=recommendation_context,
            )
            customer_perf_service.log_stage(
                "plan_conversation_route",
                plan_start,
                llm_called=bool(route_plan),
                query_type=(route_plan or {}).get("query_type"),
                resolved_skus=(route_plan or {}).get("resolved_skus") or [],
            )
        local_resolved_skus = (
            _ordinal_skus_from_entity_stack(question, entity_stack)
            or _category_reference_skus_from_entity_stack(question, entity_stack)
        )
        if not local_resolved_skus and _is_contextual_safety_or_certification_followup(question) and entity_stack:
            local_resolved_skus = _latest_entity_skus_from_stack(entity_stack, limit=1)
        if local_resolved_skus:
            route_plan = dict(route_plan or {})
            route_plan["resolved_skus"] = local_resolved_skus
            route_plan["context_mode"] = route_plan.get("context_mode") or "inherit_results"
            route_plan["reason"] = (route_plan.get("reason") or "") + "；本地实体栈回溯命中"
    previous_result_skus = _resolved_skus_from_route_plan(route_plan)
    recommendation_domain_skus = [
        str(item or "").strip().upper()
        for item in (
            recommendation_summary.get("candidate_skus")
            or recommendation_summary.get("ordered_result_skus")
            or recommendation_summary.get("result_skus")
            or []
        )
        if str(item or "").strip()
    ]
    resolved_from_entity_stack = bool(
        not explicit_product_detection.get("has_new_product")
        and local_resolved_skus
    )
    if (
        route_plan.get("query_type") == "specific_product"
        and not previous_result_skus
        and not explicit_product_detection.get("has_new_product")
        and not (explicit_product_detection.get("candidate_rows") or [])
    ):
        return _build_specific_product_not_found_result(
            question,
            str(route_plan.get("product_name") or "").strip(),
            route_plan,
        )
    if recommendation_domain_skus and _is_recommendation_change_followup(question, recommendation_summary):
        previous_result_skus = recommendation_domain_skus
    if recommendation_domain_skus and _is_candidate_scope_followup(question):
        previous_result_skus = recommendation_domain_skus
    if (
        dialogue_state.needs_clarification
        and not previous_result_skus
        and not sku
        and not _requires_write_tool(question)
        and not _is_specific_recommendation_question(question)
        and _route_allows_rule_clarification(route_plan)
    ):
        return _build_clarification_result(question, sku, dialogue_state)
    if _needs_previous_context(question) and not previous_result_skus:
        result = {
            "answer": "你说的“这些”我还没有可引用的上一轮产品结果。请先告诉我要处理的 SKU，或先查询一批产品，比如“负责人为 Yao 的锅有哪些”。",
            "intent": "clarify",
            "answer_type": "clarification",
            "confidence": "low",
            "uncertainty": "ambiguous_product",
            "needs_clarification": True,
            "sku": sku,
            "sources": [{"type": "agent_clarification", "label": "需要明确产品范围"}],
            "actions": [],
            "results": [],
            "steps": [{"type": "clarify", "label": "需要明确产品范围", "detail": "检测到上下文引用，但没有上一轮产品结果。"}],
            "warnings": [],
            "debug": {"agent_mode": "dialogue_state_clarification", "warnings": []},
        }
        quality = customer_agent_quality_service.evaluate_agent_response(
            question,
            answer=result["answer"],
            intent=result["intent"],
            results=result["results"],
            sources=result["sources"],
            actions=result["actions"],
            warnings=result["warnings"],
            needs_clarification=result["needs_clarification"],
        )
        result["agent_quality"] = quality
        result["debug"]["agent_quality"] = quality
        return result
    context_followup_seed_skus = [
        str(item or "").strip().upper()
        for item in (
            previous_result_skus
            or recommendation_summary.get("candidate_skus")
            or recommendation_summary.get("ordered_result_skus")
            or recommendation_summary.get("result_skus")
            or []
        )
        if str(item or "").strip()
    ]
    context_followup_intent = (
        customer_agent_intent_service.parse_intent(
            question,
            sku=sku,
            previous_result_skus=context_followup_seed_skus,
        )
        if context_followup_seed_skus
        else None
    )
    empty_subset_context = recommendation_context if recommendation_context.get("empty_subset") else candidate_context
    if empty_subset_context.get("empty_subset") and _is_empty_subset_followup(question):
        return _build_result(
            question,
            sku,
            [{"tool": "recommend_products", "results": [], "sources": []}],
            "上一轮“这些里面”的筛选结果为空，所以我不能再从更早的候选里直接推荐。你可以放宽上一轮条件，或重新给我一个产品范围。",
            [],
            conversation_history=conversation_history,
            intent_override="recommend_products",
            preserve_llm_answer=True,
        )
    if (
        context_followup_seed_skus
        and context_followup_intent
        and context_followup_intent.intent == "query_products"
        and getattr(context_followup_intent, "source_context", "") == "previous_results"
        and _has_specs_field_filter(context_followup_intent)
        and not _looks_like_recommendation_text(question)
    ):
        return await customer_agent_intent_service.process_intent_request(
            db,
            user_id=user_id,
            question=question,
            sku=sku,
            previous_result_skus=context_followup_seed_skus,
            allow_llm_fallback=False,
        )
    followup_recommendation_domain = context_followup_seed_skus
    recommendation_change_followup = _is_recommendation_change_followup(question, recommendation_summary) or _is_recommendation_change_followup_text(question)
    if (
        followup_recommendation_domain
        and not _requires_write_tool(question)
        and (
            recommendation_change_followup
            or (
                context_followup_intent
                and context_followup_intent.intent == "recommend_products"
                and getattr(context_followup_intent, "source_context", "") == "previous_results"
            )
        )
    ):
        deterministic_followup_recommendation = await customer_agent_intent_service.process_intent_request(
            db,
            user_id=user_id,
            question=question,
            sku=sku,
            previous_result_skus=followup_recommendation_domain,
            allow_llm_fallback=False,
        )
        if deterministic_followup_recommendation and deterministic_followup_recommendation.get("intent") in {
            "recommend_products",
            "query_products",
        }:
            return deterministic_followup_recommendation
        arguments = {"skus": followup_recommendation_domain[:10], "fields": []}
        result = await customer_agent_tool_service.execute_tool_async(
            db,
            user_id=user_id,
            name="get_product_detail",
            arguments=arguments,
        )
        return await _build_result_async(
            db,
            question,
            None,
            [result],
            None,
            [_step_from_tool_result("get_product_detail", arguments, result)],
            conversation_history=conversation_history,
            conversation_id=conversation_id,
            user_id=user_id,
            intent_override="recommend_products",
            intent_hint="recommend_products",
            entity_stack=entity_stack,
            route_hints={"followup_candidate_domain": True},
            answer_delta_callback=answer_delta_callback,
        )
    context_fields = _context_detail_fields(question, conversation_history)
    if (
        previous_result_skus
        and resolved_from_entity_stack
        and not _requires_write_tool(question)
        and not _is_compare_like_question(question, context_skus=previous_result_skus)
        and not _is_recommendation_change_followup(question, recommendation_summary)
        and not _is_candidate_scope_followup(question)
    ):
        inherited_fields = context_fields or _context_requested_fields_from_intent(question, previous_result_skus)
        if inherited_fields or _is_safety_usage_followup(question):
            arguments = {
                "skus": previous_result_skus[:5],
                "fields": inherited_fields or _safety_detail_fields(),
            }
            result = await customer_agent_tool_service.execute_tool_async(
                db,
                user_id=user_id,
                name="get_product_detail",
                arguments=arguments,
            )
            if inherited_fields:
                direct_answer = _direct_heat_source_support_answer(question, result)
                if direct_answer is None and any(term in str(question or "") for term in ("酒精炉", "酒精")) and any(
                    term in str(question or "") for term in ("能用", "可以用", "支持", "适合", "能不能", "是否支持")
                ):
                    inline_rows = _collect_results([result])
                    if len(inline_rows) == 1 and isinstance(inline_rows[0], dict):
                        inline_item = inline_rows[0]
                        inline_field_values = inline_item.get("field_values") if isinstance(inline_item.get("field_values"), dict) else {}
                        inline_heat_source = str(inline_field_values.get("热源") or inline_field_values.get("燃料") or "").strip()
                        if not inline_heat_source:
                            inline_heat_source = str(((inline_item.get("specs") or {}).get("heat_source") or "")).strip()
                        inline_name = inline_item.get("product_name_cn") or inline_item.get("product_name_en") or ""
                        inline_prefix = f"{inline_name}（{inline_item.get('sku')}）" if inline_name else str(inline_item.get("sku") or "").strip()
                        if inline_heat_source and inline_heat_source != "暂无":
                            if "酒精炉" in inline_heat_source or "酒精" in inline_heat_source:
                                direct_answer = f"{inline_prefix}：支持酒精炉。当前资料显示适用热源为{inline_heat_source}。"
                            else:
                                direct_answer = f"{inline_prefix}：当前资料未显示支持酒精炉。当前资料显示适用热源为{inline_heat_source}。"
                        else:
                            direct_answer = f"{inline_prefix}：当前资料暂未提供是否支持酒精炉。"
                deterministic_result = _build_result(
                    question,
                    previous_result_skus[0] if len(previous_result_skus) == 1 else sku,
                    [result],
                    direct_answer,
                    [_step_from_tool_result("get_product_detail", arguments, result)],
                    conversation_history=conversation_history,
                    intent_override="product_detail",
                    preserve_llm_answer=bool(direct_answer),
                )
                debug = dict(deterministic_result.get("debug") or {})
                debug["agent_mode"] = "deterministic_entity_stack_detail"
                deterministic_result["debug"] = debug
                return deterministic_result
            return await _build_result_async(
                db,
                question,
                previous_result_skus[0] if len(previous_result_skus) == 1 else sku,
                [result],
                None,
                [_step_from_tool_result("get_product_detail", arguments, result)],
                conversation_history=conversation_history,
                conversation_id=conversation_id,
                user_id=user_id,
                intent_override="product_detail",
                intent_hint="product_detail",
                preserve_llm_answer=True,
                entity_stack=entity_stack,
                route_hints={"entity_stack_direct_detail": True},
                answer_delta_callback=answer_delta_callback,
            )
    if (
        previous_result_skus
        and context_fields
        and not _requires_write_tool(question)
        and not _has_explicit_product_reference(question)
        and not _has_specs_filter(question)
        and not resolved_from_entity_stack
        and not _is_candidate_scope_followup(question)
    ):
        arguments = {"skus": previous_result_skus[:5], "fields": context_fields}
        result = await customer_agent_tool_service.execute_tool_async(
            db,
            user_id=user_id,
            name="get_product_detail",
            arguments=arguments,
        )
        return _build_result(
            question,
            sku,
            [result],
            None,
            [_step_from_tool_result("get_product_detail", arguments, result)],
            conversation_history=conversation_history,
        )
    routed_result = None
    if not _is_recommendation_change_followup(question, recommendation_summary) and not resolved_from_entity_stack:
        deterministic_start = perf_counter()
        routed_result = await _route_deterministic_fact_question(db, user_id, question, sku, previous_result_skus)
        customer_perf_service.log_stage(
            "route_deterministic_fact_question",
            deterministic_start,
            hit=bool(routed_result),
            intent=routed_result.get("intent") if routed_result else None,
            agent_mode=(routed_result.get("debug") or {}).get("agent_mode") if routed_result else None,
        )
    if routed_result:
        return routed_result
    messages = _build_tool_selection_messages(
        question,
        sku,
        previous_result_skus,
        conversation_history,
        feedback_lessons or [],
        route_plan,
        entity_stack=entity_stack,
        route_hints=route_hints,
    )
    agent_trace_service.trace("TOOL_SELECTION_REQUEST", {"messages": messages, "tools": customer_agent_tool_service.list_tool_specs()})

    tool_results = []
    steps = []
    final_answer = None
    tool_round_limit = 1 if _is_tool_round_limited_recommendation(question, route_plan) else MAX_TOOL_ROUNDS
    for round_index in range(tool_round_limit):
        try:
            content = await customer_llm_service.chat_completion(db, messages, temperature=0, max_tokens=1200, purpose="tool_selection")
        except Exception as exc:
            agent_trace_service.trace("TOOL_SELECTION_ERROR", {"error": str(exc)})
            if not tool_results:
                return None
            break

        agent_trace_service.trace("TOOL_SELECTION_RESPONSE", {"round": round_index + 1, "content": content})
        plan = _parse_json_object(content)
        if not plan:
            if not tool_results:
                return None
            break

        tool_calls = plan.get("tool_calls") or []
        if not tool_calls:
            final_answer = str(plan.get("answer") or "").strip() or None
            if final_answer:
                agent_trace_service.trace("FINAL_RESPONSE", {"content": final_answer})
            break

        round_results = []
        for call in tool_calls:
            name = str(call.get("name") or "").strip()
            arguments = call.get("arguments") or {}
            if not isinstance(arguments, dict):
                arguments = {}
            arguments = _resolve_context_arguments(arguments, previous_result_skus, tool_results)
            name, arguments = _redirect_preference_detail_to_recommendation_search(
                name,
                arguments,
                question,
                route_plan,
                conversation_history,
            )
            arguments = _enrich_recommendation_tool_arguments(name, arguments, question, route_plan)
            agent_trace_service.trace("TOOL_CALL", {"name": name, "arguments": arguments})
            result = await customer_agent_tool_service.execute_tool_async(db, user_id=user_id, name=name, arguments=arguments)
            agent_trace_service.trace("TOOL_RESULT", result)
            tool_results.append(result)
            round_results.append(result)
            steps.append(_step_from_tool_result(name, arguments, result))

        messages.append({"role": "assistant", "content": content})
        messages.append({"role": "user", "content": json.dumps({"tool_results": round_results, "instruction": "你可以继续调用工具，或输出 {\"answer\":\"...\"} 结束。"}, ensure_ascii=False, default=str)})

    if tool_results and _requires_write_tool(question) and not _collect_actions(tool_results):
        agent_trace_service.trace(
            "WRITE_REQUEST_WITHOUT_ACTION_REJECTED",
            {"question": question, "tool_results": tool_results},
        )
        return None
    if not tool_results and final_answer and _requires_write_tool(question):
        agent_trace_service.trace(
            "DIRECT_PRODUCT_WRITE_ANSWER_REJECTED",
            {"question": question, "answer": final_answer},
        )
        return None
    if not tool_results and final_answer and _requires_lookup_tool(question):
        arguments = {
            "semantic_query": question,
            "fields": [
                "specs.capacity",
                "specs.body_material",
                "business.top_selling_points",
                "business.usage_scenarios",
                "business.target_audience",
                "business.price_positioning",
            ],
            "limit": 20,
        }
        agent_trace_service.trace(
            "DIRECT_PRODUCT_ANSWER_GUARDRAIL",
            {"question": question, "answer": final_answer, "fallback_tool": "hybrid_search_products"},
        )
        fallback_result = await customer_agent_tool_service.execute_tool_async(
            db,
            user_id=user_id,
            name="hybrid_search_products",
            arguments=arguments,
        )
        tool_results.append(fallback_result)
        steps.append(_step_from_tool_result("hybrid_search_products", arguments, fallback_result))
        final_answer = None
    if not tool_results and final_answer:
        return _build_result(
            _question_for_result(question, route_plan),
            sku,
            [],
            final_answer,
            steps,
            conversation_history=conversation_history or [],
            direct_answer=True,
        )
    return await _build_result_async(
        db,
        _question_for_result(question, route_plan),
        sku,
        tool_results,
        final_answer,
        steps,
        conversation_history=conversation_history or [],
        conversation_id=conversation_id,
        user_id=user_id,
        entity_stack=entity_stack,
        route_hints=route_hints,
        answer_delta_callback=answer_delta_callback,
    )


async def _build_result_async(
    db: Session,
    question: str,
    sku: str | None,
    tool_results: list[dict],
    final_answer: str | None,
    steps: list[dict],
    conversation_history: list[dict] | None = None,
    conversation_id: str | None = None,
    user_id: str | None = None,
    intent_override: str | None = None,
    preserve_llm_answer: bool = False,
    intent_hint: str | None = None,
    entity_stack: list[dict] | None = None,
    route_hints: dict[str, Any] | None = None,
    answer_delta_callback: Callable[[str], Awaitable[None]] | None = None,
) -> dict:
    effective_intent = intent_hint or intent_override
    active_tool_results = tool_results
    active_preserve_llm_answer = preserve_llm_answer
    recommendation_question = ""
    enriched_results: list[dict] = []
    recommendation_change_followup = False
    excluded_skus: set[str] = set()
    collected_results = _collect_results(tool_results)
    inferred_intent = effective_intent or _infer_intent(
        question,
        tool_results,
        _collect_actions(tool_results),
        collected_results,
        False,
    )
    if inferred_intent == "recommend_products":
        rank_start = perf_counter()
        recommendation_question = _recommendation_question_with_context(question, conversation_history or [])
        exclusion_context = _latest_recommendation_context(db, conversation_id, user_id)
        excluded_skus = _excluded_previous_skus(question, conversation_history or [], exclusion_context)
        ranked_results = _filter_excluded_recommendations(question, collected_results, conversation_history or [], exclusion_context)
        candidate_scope_followup = _is_candidate_scope_followup(question) and bool((exclusion_context or {}).get("candidate_skus"))
        recommendation_change_followup = _is_recommendation_change_followup(
            question,
            {
                "intent": "recommend_products",
                "result_skus": list(
                    (exclusion_context or {}).get("recommended_skus")
                    or (exclusion_context or {}).get("ordered_result_skus")
                    or (exclusion_context or {}).get("candidate_skus")
                    or []
                ),
            },
        )
        if recommendation_change_followup or candidate_scope_followup:
            ranked_results = _filter_followup_candidate_domain(ranked_results, exclusion_context)
        if recommendation_change_followup:
            ranked_results = _filter_followup_recommendation_scope(ranked_results, exclusion_context)
        ranked_results = _rank_recommendation_results(recommendation_question, ranked_results)
        enriched_results = _recommendation_products_for_finalizer(db, recommendation_question, ranked_results)
        if excluded_skus:
            enriched_results = _without_excluded_skus(enriched_results, excluded_skus)
        customer_perf_service.log_stage(
            "recommendation_rank_and_prepare",
            rank_start,
            ranked_count=len(ranked_results or []),
            enriched_count=len(enriched_results or []),
        )
        if enriched_results or excluded_skus:
            active_tool_results = [
                {
                    "tool": "recommend_products",
                    "results": enriched_results,
                    "sources": _sources_from_tool_results(tool_results),
                }
            ]
    elif inferred_intent == "product_detail":
        known_sku = _single_product_detail_sku(sku, collected_results)
        if known_sku and not any((item or {}).get("tool") == "semantic_search_knowledge" for item in active_tool_results):
            semantic_start = perf_counter()
            semantic_rows: list[dict] = []
            keyword_rows: list[dict] = []
            lookup_ok = True
            try:
                semantic_rows = await knowledge_service.semantic_retrieve(db, question, sku=known_sku, limit=3)
                keyword_rows = _keyword_knowledge_rows_for_sku(db, question, known_sku, limit=3)
            except Exception as exc:
                lookup_ok = False
                customer_perf_service.log_stage(
                    "product_detail.semantic_retrieve",
                    semantic_start,
                    sku=known_sku,
                    ok=False,
                    error=str(exc)[:300],
                )
            knowledge_rows = _merge_knowledge_rows(keyword_rows, semantic_rows)
            customer_perf_service.log_stage(
                "product_detail.semantic_retrieve",
                semantic_start,
                sku=known_sku,
                ok=lookup_ok,
                semantic_rows=len(semantic_rows or []),
                keyword_rows=len(keyword_rows or []),
                merged_rows=len(knowledge_rows or []),
            )
            if knowledge_rows:
                active_tool_results = [
                    *active_tool_results,
                    {
                        "ok": True,
                        "tool": "semantic_search_knowledge",
                        "label": "QA知识库补充",
                        "query": question,
                        "sku": known_sku,
                        "mode": "semantic",
                        "count": len(knowledge_rows),
                        "results": knowledge_rows,
                    },
                ]
    answer_metadata_override = None
    if inferred_intent == "recommend_products" and (enriched_results or excluded_skus) and (
        excluded_skus or recommendation_change_followup
    ):
        answer = _compose_recommendation_answer(
            recommendation_question or question,
            enriched_results,
            excluded_skus=excluded_skus,
        )
        active_preserve_llm_answer = True
    else:
        final_response = await _finalize_answer(
            db,
            question,
            sku,
            active_tool_results,
            conversation_history or [],
            conversation_id=conversation_id,
            user_id=user_id,
            intent_hint=effective_intent,
            entity_stack=entity_stack or [],
            route_hints=route_hints,
            answer_delta_callback=answer_delta_callback,
        )
        answer = final_response.get("answer") if isinstance(final_response, dict) else final_response
        answer_metadata_override = final_response.get("answer_metadata") if isinstance(final_response, dict) else None
    if enriched_results and answer and not _should_replace_recommendation_answer(answer, recommendation_question, enriched_results):
        active_preserve_llm_answer = True
    return _build_result(
        question,
        sku,
        active_tool_results,
        answer,
        steps,
        conversation_history=conversation_history or [],
        intent_override=intent_override,
        preserve_llm_answer=active_preserve_llm_answer,
        answer_metadata_override=answer_metadata_override if isinstance(answer_metadata_override, dict) else None,
    )


def _build_result(
    question: str,
    sku: str | None,
    tool_results: list[dict],
    answer: str | None,
    steps: list[dict] | None = None,
    conversation_history: list[dict] | None = None,
    direct_answer: bool = False,
    intent_override: str | None = None,
    preserve_llm_answer: bool = False,
    answer_metadata_override: dict[str, Any] | None = None,
) -> dict:
    actions = _collect_actions(tool_results)
    raw_results = _collect_results(tool_results)
    raw_results = _enrich_load_capacity_results(question, raw_results)
    raw_results = _rewrite_heat_source_support_results(question, raw_results)
    warnings = _warnings_from_tool_results(tool_results, direct_answer=direct_answer)
    provisional_answer = _clean_customer_answer(answer or "")
    provisional_needs_clarification = _needs_clarification(provisional_answer, raw_results, warnings)
    intent = intent_override or _infer_intent(question, tool_results, actions, raw_results, provisional_needs_clarification)
    if _requires_lookup_tool(question) and not raw_results and not actions:
        provisional_answer = _fallback_answer(tool_results)
    if _has_field_values(raw_results) and not preserve_llm_answer:
        field_answer = _compose_field_values_answer(question, raw_results)
        if field_answer and (not provisional_answer or _field_answer_should_replace(question, provisional_answer, raw_results)):
            provisional_answer = field_answer
    if intent == "compare_products":
        compare_answer = _compose_context_compare_answer(question, raw_results)
        if compare_answer:
            provisional_answer = compare_answer
    elif raw_results and not preserve_llm_answer and _answer_conflicts_with_current_results(provisional_answer, question, raw_results):
        warnings.append("LLM 原始回答与本轮问题或工具结果不一致，已改用工具结果兜底回答。")
        provisional_answer = _fallback_answer(tool_results)
    clean_answer = _clean_customer_answer(provisional_answer or _fallback_answer(tool_results))
    heat_source_support_answer = _rewrite_heat_source_support_answer(question, raw_results)
    if heat_source_support_answer:
        clean_answer = heat_source_support_answer
    needs_clarification = _needs_clarification(clean_answer, raw_results, warnings)
    display_results = _merge_results_for_display(question, raw_results)
    suggested_followups = _suggested_followups(question, display_results, needs_clarification)
    answer_metadata = _build_answer_metadata(clean_answer, display_results, warnings, needs_clarification)
    if answer_metadata_override:
        answer_metadata = {**answer_metadata, **answer_metadata_override}
    final_steps = [
        {
            "type": "llm_decision",
            "label": "LLM理解问题并选择工具",
            "detail": "结合当前问题、历史对话和可用工具自主决策",
            "ok": True,
        },
        *(steps or []),
        {
            "type": "llm_reasoning",
            "label": "LLM基于工具结果推理回答",
            "detail": "根据工具返回的数据整理结论、依据和下一步建议",
            "ok": True,
        },
    ]
    result = {
        "answer": clean_answer,
        "intent": intent,
        "answer_type": _answer_type_from_intent(intent),
        "confidence": _confidence(display_results, warnings, needs_clarification, direct_answer),
        "uncertainty": _uncertainty(clean_answer, display_results, warnings, needs_clarification),
        "needs_clarification": needs_clarification,
        "anomalies": _anomalies_from_tool_results(tool_results),
        "suggested_followups": suggested_followups,
        "followups": suggested_followups,
        "evidence": _evidence_from_results(display_results),
        "answer_metadata": answer_metadata,
        "debug": {
            "agent_mode": "llm_tool_calling",
            "intent": intent,
            "history_turns": len(conversation_history or []),
            "steps": final_steps,
            "warnings": warnings,
            "raw_results": display_results,
            "tool_results": tool_results,
        },
        "sku": _single_sku(display_results, actions) or sku,
        "sources": _sources_from_tool_results(tool_results, direct_answer=direct_answer),
        "actions": actions,
        "results": display_results,
        "steps": final_steps,
        "warnings": warnings,
        "skip_polish": True,
    }
    quality = customer_agent_quality_service.evaluate_agent_response(
        question,
        answer=result["answer"],
        intent=result["intent"],
        results=result["results"],
        sources=result["sources"],
        actions=result["actions"],
        warnings=result["warnings"],
        needs_clarification=result["needs_clarification"],
        direct_answer=direct_answer,
        tool_results=tool_results,
    )
    result["agent_quality"] = quality
    result["debug"]["agent_quality"] = quality
    result["confidence"] = _confidence_adjusted_by_quality(result["confidence"], quality)
    result["uncertainty"] = _uncertainty_adjusted_by_quality(result["uncertainty"], quality)
    if quality["risks"]:
        result["warnings"] = list(dict.fromkeys([*result["warnings"], *quality["risks"]]))
        result["debug"]["warnings"] = result["warnings"]
    return result


async def _plan_conversation_route(
    db: Session,
    question: str,
    entity_stack: list[dict],
    conversation_history: list[dict],
    force_query_type: bool = False,
    recommendation_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if not force_query_type and not _should_plan_conversation_route(question, entity_stack, conversation_history):
        customer_perf_service.log_event("plan_conversation_route.skipped", reason="no_history_or_entity_stack")
        return {}
    messages = [
        {
            "role": "system",
            "content": """你是内部产品客服的指代消解器，只负责在“没有新产品名命中”的前提下，判断当前问题实际指向哪些已有 SKU。
你会收到 current_question、entity_stack、conversation_history。entity_stack 中的每一项都包含 sku、name、turn，turn 越小越早出现。
请只输出 JSON，且只允许包含 resolved_skus 和 reason 两个字段。
resolved_skus 里填写当前问题实际指向的 SKU 列表。
当 current_question 里没有新的明确产品名或 SKU，但存在指代词、序数词、或上下文语义在追问已有产品时，才应该从 entity_stack 中匹配，给出最可能的 resolved_skus。
在这种指代消解场景里，默认优先指向 entity_stack 中 turn 最大、也就是最近一次被明确提到的产品；只有出现“最开始 / 第一个 / 前面那款 / 之前那个 / 上一个 / 上面那个”等更早回指的线索时，才回到更早的实体。
如果上一轮用户刚明确问过一个新产品名，而本轮只是用“它 / 这个 / 这款 / 锅盖 / 材质 / 热源”等词继续追问，那么默认指向上一轮那个新产品，不要回到更早出现的产品。
像“它的锅盖 / 这个材质 / 这款热源”这类部件或属性追问，通常仍然是在追问最近一轮明确产品，不要因为更早产品也出现过同类部件词就自动回到更早实体。
reason 字段必须说明你为什么选择这些 SKU，或者为什么判断为全新追问；不允许 reason 为空或仅写“无法判断”。
只输出 JSON，不要输出 Markdown。""",
        },
        {
            "role": "system",
            "content": (
                "补充任务：你还需要判断 current_question 的 query_type。"
                "如果用户是在寻找某个明确命名的产品，但该产品没有出现在 entity_stack 中，输出 query_type=\"specific_product\"，并在 product_name 写出该产品名。"
                "如果用户是在描述使用场景、需求、预算、人群或品类偏好，输出 query_type=\"scene_description\"。"
                "如果只是普通指代消解、对比、推荐、事实查询，也可以输出 fact/recommendation/comparison/write/chat/unknown。"
                "如果用户要求换一个推荐，要结合 recommendation_context 继承最近一次推荐需求和候选范围。"
                "例如“我要买星空投影炉”“有没有星空投影炉”属于 specific_product；"
                "“我想找一个适合高海拔的炉具”属于 scene_description。"
                "最终只输出 JSON，可包含 resolved_skus、query_type、product_name、reason。"
            ),
        },
        {
            "role": "system",
            "content": (
                "请先直接回答用户原问题，再用证据补充。retrieved_products 和 tool_results 只是证据，不是最终答案。"
                "不要把“找到 N 条产品资料”当成最终回答，也不要只复述检索结果列表。"
                "如果资料里没有明确维护用户问到的信息，要明确说明“当前知识库没有维护/现有资料不足以确认”，不要编造。"
                "如果资料里有相关字段或证据，就基于证据总结；如果资料不足，就先说明不足，再给出已能确认的信息。"
            ),
        },
        {
            "role": "system",
            "content": (
                "请先直接回答用户原问题，再用证据补充。retrieved_products 和 tool_results 只是证据，不是最终答案。"
                "不要把“找到 N 条产品资料”当成最终回答，也不要只复述检索结果列表。"
                "如果资料里没有明确维护用户问到的信息，要明确说明“当前知识库没有维护/现有资料不足以确认”，不要编造。"
                "如果资料里有相关字段或证据，就基于证据总结；如果资料不足，就先说明不足，再给出已能确认的信息。"
            ),
        },
        {
            "role": "user",
            "content": json.dumps(
                {
                    "current_question": question,
                    "entity_stack": entity_stack[:30],
                    "conversation_history": conversation_history[-4:],
                    "recommendation_context": recommendation_context or {},
                    "output_schema": {
                        "resolved_skus": ["SKU1", "SKU2"],
                        "query_type": "specific_product | scene_description | fact | recommendation | comparison | write | chat | unknown",
                        "product_name": "用户明确要找但未命中的产品名，没有则为空",
                        "reason": "????",
                    },
                    "examples": [
                        {"current_question": "?????????", "entity_stack": [{"sku": "CW-C83", "name": "????", "turn": 1}], "resolved_skus": ["CW-C83"]},
                        {"current_question": "????????????", "entity_stack": [{"sku": "CW-C83", "name": "????", "turn": 1}, {"sku": "CW-C93", "name": "????", "turn": 2}], "resolved_skus": ["CW-C93"]},
                        {"current_question": "???????????", "entity_stack": [{"sku": "CS-B14", "name": "?????", "turn": 0}], "resolved_skus": ["CS-B14"]},
                        {"current_question": "??????????", "entity_stack": [], "resolved_skus": []},
                        {"current_question": "?????", "entity_stack": [], "resolved_skus": []},
                        {"current_question": "??????????4?", "entity_stack": [{"sku": "CW-C83", "name": "????", "turn": 1}, {"sku": "CW-C05-37", "name": "2-4????10??", "turn": 2}], "resolved_skus": ["CW-C83", "CW-C05-37"]}
                    ],
                },
                ensure_ascii=False,
                default=str,
            ),
        },
    ]
    llm_start = perf_counter()
    try:
        content = await customer_llm_service.chat_completion(db, messages, temperature=0, max_tokens=500, purpose="route")
    except Exception as exc:
        agent_trace_service.trace("CONVERSATION_ROUTE_ERROR", {"error": str(exc)})
        customer_perf_service.log_stage("plan_conversation_route.llm", llm_start, llm_called=True, error=str(exc))
        return {}
    plan = _adjust_conversation_route(question, _sanitize_conversation_route(_parse_json_object(content)))
    if plan:
        agent_trace_service.trace("CONVERSATION_ROUTE", plan)
    customer_perf_service.log_stage(
        "plan_conversation_route.llm",
        llm_start,
        llm_called=True,
        query_type=plan.get("query_type") if plan else None,
        resolved_skus=plan.get("resolved_skus") if plan else [],
    )
    return plan


def _detect_explicit_product_mention(
    db: Session,
    question: str,
    entity_stack: list[dict],
) -> dict[str, Any]:
    text = customer_agent_service.normalize_search_text(question)
    if not text:
        return {"has_new_product": False, "new_skus": [], "matched_rows": [], "candidate_rows": []}
    entity_skus = {
        str(item.get("sku") or "").strip().upper()
        for item in entity_stack
        if isinstance(item, dict) and item.get("sku")
    }
    rows = db.query(Product).all()
    exact_skus: list[str] = []
    exact_rows: list[dict] = []
    for product in rows:
        if product is None:
            continue
        sku = str(product.sku or "").strip().upper()
        if not sku or sku in entity_skus or sku in exact_skus:
            continue
        name_cn = customer_agent_service.normalize_search_text(getattr(product, "product_name_cn", "") or "")
        name_en = customer_agent_service.normalize_search_text(getattr(product, "product_name_en", "") or "")
        sku_text = customer_agent_service.normalize_search_text(sku)
        if (name_cn and name_cn in text) or (name_en and name_en in text) or (sku_text and sku_text in text):
            exact_skus.append(sku)
            exact_rows.append(
                {
                    "sku": sku,
                    "product_name_cn": getattr(product, "product_name_cn", None),
                    "product_name_en": getattr(product, "product_name_en", None),
                }
            )
    if exact_skus:
        return {
            "has_new_product": True,
            "new_skus": exact_skus,
            "matched_rows": exact_rows,
            "candidate_rows": [],
        }

    candidate_rows: list[dict] = []
    for product in rows:
        if product is None:
            continue
        sku = str(product.sku or "").strip().upper()
        if not sku or sku in entity_skus or any(item.get("sku") == sku for item in candidate_rows):
            continue
        name_cn = customer_agent_service.normalize_search_text(getattr(product, "product_name_cn", "") or "")
        name_en = customer_agent_service.normalize_search_text(getattr(product, "product_name_en", "") or "")
        sku_text = customer_agent_service.normalize_search_text(sku)
        matched_prefix = ""
        if name_cn and len(name_cn) >= 4:
            for length in range(len(name_cn) - 1, 3, -1):
                prefix = name_cn[:length]
                if prefix and prefix in text:
                    matched_prefix = prefix
                    break
        if not matched_prefix and name_en and len(name_en) >= 4:
            for length in range(len(name_en) - 1, 3, -1):
                prefix = name_en[:length]
                if prefix and prefix in text:
                    matched_prefix = prefix
                    break
        if not matched_prefix and sku_text and sku_text in text:
            matched_prefix = sku_text
        if matched_prefix:
            candidate_rows.append(
                {
                    "sku": sku,
                    "product_name_cn": getattr(product, "product_name_cn", None),
                    "product_name_en": getattr(product, "product_name_en", None),
                    "matched_prefix": matched_prefix,
                }
            )
    if len(candidate_rows) == 1:
        single = candidate_rows[0]
        return {
            "has_new_product": True,
            "new_skus": [str(single.get("sku") or "").strip().upper()],
            "matched_rows": candidate_rows,
            "candidate_rows": [],
        }
    return {
        "has_new_product": False,
        "new_skus": [],
        "matched_rows": [],
        "candidate_rows": candidate_rows,
    }


def _should_plan_conversation_route(
    question: str,
    entity_stack: list[dict],
    conversation_history: list[dict],
) -> bool:
    if _requires_write_tool(question):
        return True
    if conversation_history:
        return True
    return bool(entity_stack)


def _may_need_specific_product_classification(question: str) -> bool:
    text = str(question or "").strip()
    if not text:
        return False
    return any(term in text for term in ("买", "要", "有没有", "有吗", "查询", "查一下", "找"))


def _ordinal_skus_from_entity_stack(question: str, entity_stack: list[dict]) -> list[str]:
    if not entity_stack:
        return []
    text = str(question or "")
    if not any(term in text for term in ("最开始", "第一个", "第一款", "最后", "最近", "上一个", "第")):
        return []
    ordered = _entity_stack_by_conversation_order(entity_stack)
    if not ordered:
        return []
    if any(term in text for term in ("最开始", "第一个", "第一款")):
        return [ordered[0]["sku"]]
    if any(term in text for term in ("最后", "最近", "上一个")):
        return [ordered[-1]["sku"]]
    match = re.search(r"第\s*(\d+|[一二三四五六七八九十两])\s*(?:个|款|件|条)?", text)
    if not match:
        return []
    index = _chinese_ordinal_to_int(match.group(1))
    if index <= 0 or index > len(ordered):
        return []
    return [ordered[index - 1]["sku"]]


def _category_reference_skus_from_entity_stack(question: str, entity_stack: list[dict]) -> list[str]:
    if not entity_stack:
        return []
    text = str(question or "")
    if not any(term in text for term in ("刚才", "之前", "前面", "上次")):
        return []
    type_terms = ("酒精炉", "气炉", "炉", "套锅", "炒锅", "煎锅", "单锅", "锅", "杯套装", "杯", "水壶", "壶", "包")
    requested = [term for term in type_terms if term in text]
    if not requested:
        return []
    ordered = _entity_stack_by_conversation_order(entity_stack)
    for term in requested:
        for entity in ordered:
            name = str(entity.get("name") or "")
            sku = str(entity.get("sku") or "").strip().upper()
            if sku and (term in name or (term == "炉" and "炉" in name) or (term == "锅" and "锅" in name)):
                return [sku]
    return []


def _latest_entity_skus_from_stack(entity_stack: list[dict], limit: int = 1) -> list[str]:
    skus: list[str] = []
    for entity in entity_stack:
        sku = str(entity.get("sku") or "").strip().upper()
        if sku and sku not in skus:
            skus.append(sku)
        if len(skus) >= limit:
            break
    return skus


def _entity_stack_direct_detail_skus(question: str, entity_stack: list[dict]) -> list[str]:
    explicit_reference = (
        _ordinal_skus_from_entity_stack(question, entity_stack)
        or _category_reference_skus_from_entity_stack(question, entity_stack)
    )
    if len(explicit_reference) == 1:
        return explicit_reference
    if not entity_stack or not (_needs_previous_context(question) or _is_contextual_safety_or_certification_followup(question)):
        return []
    top_turn = entity_stack[0].get("turn")
    top_skus: list[str] = []
    for entity in entity_stack:
        if entity.get("turn") != top_turn:
            break
        sku = str(entity.get("sku") or "").strip().upper()
        if sku and sku not in top_skus:
            top_skus.append(sku)
    return top_skus if len(top_skus) == 1 else []


def _ordinal_skus_from_conversation_history(question: str, conversation_history: list[dict] | None) -> list[str]:
    text = str(question or "")
    if not any(term in text for term in ("最开始", "第一个", "第一款", "最后一个", "最后一款", "最后那个", "上一个", "第二个", "第三个", "第四个")):
        return []
    history = conversation_history or []
    ordered_skus: list[str] = []
    for item in history:
        if str(item.get("role") or "") != "user":
            continue
        content = str(item.get("content") or "")
        for match in SKU_RE.findall(content):
            sku = str(match or "").strip().upper()
            if sku and sku not in ordered_skus:
                ordered_skus.append(sku)
    if not ordered_skus:
        return []
    if any(term in text for term in ("最开始", "第一个", "第一款")):
        return [ordered_skus[0]]
    if any(term in text for term in ("最后一个", "最后一款", "最后那个", "上一个")):
        return [ordered_skus[-1]]
    match = re.search(r"第\s*(\d+|[一二三四五六七八九十两])\s*(?:个|款|种)?", text)
    if not match:
        return []
    index = _chinese_ordinal_to_int(match.group(1))
    if index <= 0 or index > len(ordered_skus):
        return []
    return [ordered_skus[index - 1]]


def _can_use_entity_stack_direct_detail(
    question: str,
    route_hints: dict[str, Any] | None,
    recommendation_summary: dict,
    direct_detail_skus: list[str],
) -> bool:
    if len(direct_detail_skus) != 1:
        return False
    hints = route_hints or {}
    if hints.get("has_new_product"):
        return False
    if hints.get("is_comparison") or _is_compare_like_question(question, context_skus=direct_detail_skus):
        return False
    if _looks_like_multi_product_fact_question(question):
        return False
    if _is_recommendation_change_followup(question, recommendation_summary):
        return False
    if _requires_write_tool(question):
        return False
    if customer_agent_tool_service.query_fields_from_text(question):
        return True
    if _context_requested_fields_from_intent(question, direct_detail_skus):
        return True
    intent = str(hints.get("intent") or "")
    return intent in {"product_detail", "query_products", "clarify", "unknown", ""}


def _entity_stack_by_conversation_order(entity_stack: list[dict]) -> list[dict]:
    deduped: dict[str, dict] = {}
    for entity in entity_stack:
        sku = str(entity.get("sku") or "").strip().upper()
        if not sku or sku in deduped:
            continue
        item = dict(entity)
        item["sku"] = sku
        deduped[sku] = item
    return sorted(
        deduped.values(),
        key=lambda item: int(item.get("turn") if item.get("turn") is not None else 0),
        reverse=True,
    )


def _chinese_ordinal_to_int(value: str) -> int:
    text = str(value or "").strip()
    if text.isdigit():
        return int(text)
    mapping = {"一": 1, "二": 2, "两": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9, "十": 10}
    if text in mapping:
        return mapping[text]
    if text.startswith("十") and len(text) == 2:
        return 10 + mapping.get(text[1], 0)
    if len(text) == 3 and text[1] == "十":
        return mapping.get(text[0], 0) * 10 + mapping.get(text[2], 0)
    return 0


def _sanitize_conversation_route(plan: dict | None) -> dict[str, Any]:
    if not isinstance(plan, dict):
        return {}
    context_mode = str(plan.get("context_mode") or "").strip()
    query_type = str(plan.get("query_type") or "").strip()
    confidence = str(plan.get("confidence") or "").strip()
    resolved_skus: list[str] = []
    raw_resolved = plan.get("resolved_skus") or []
    if isinstance(raw_resolved, list):
        for item in raw_resolved:
            sku = str(item or "").strip().upper()
            if sku:
                resolved_skus.append(sku)
    if query_type not in {"specific_product", "scene_description", "fact", "recommendation", "comparison", "write", "chat", "unknown"}:
        query_type = "unknown"
    if confidence not in {"high", "medium", "low"}:
        confidence = "medium"
    return {
        "context_mode": context_mode,
        "query_type": query_type,
        "use_previous_result_skus": bool(plan.get("use_previous_result_skus")),
        "resolved_skus": resolved_skus,
        "effective_question": str(plan.get("effective_question") or "").strip(),
        "product_name": str(plan.get("product_name") or "").strip(),
        "confidence": confidence,
        "reason": str(plan.get("reason") or "").strip(),
    }


def _previous_skus_for_route(route_plan: dict[str, Any], previous_result_skus: list[str]) -> list[str]:
    if not route_plan:
        return []
    return list(route_plan.get("resolved_skus") or [])


def _resolved_skus_from_route_plan(route_plan: dict[str, Any] | None) -> list[str]:
    if not route_plan:
        return []
    resolved = route_plan.get("resolved_skus") or []
    if not isinstance(resolved, list):
        return []
    return [str(item or "").strip().upper() for item in resolved if str(item or "").strip()]


def _adjust_conversation_route(question: str, route_plan: dict[str, Any]) -> dict[str, Any]:
    if not route_plan:
        return {}
    if (
        route_plan.get("context_mode") == "inherit_results"
        and route_plan.get("query_type") == "recommendation"
        and _looks_like_preference_adjustment(question)
    ):
        adjusted = dict(route_plan)
        adjusted["context_mode"] = "inherit_need"
        adjusted["use_previous_result_skus"] = False
        adjusted["reason"] = (adjusted.get("reason") or "") + "；偏好/档位调整应继承需求而非锁定单品"
        return adjusted
    return route_plan


def _looks_like_preference_adjustment(question: str) -> bool:
    text = str(question or "")
    if any(term in text for term in ("哪个", "哪款", "哪种", "哪一个", "选哪个", "选哪款")):
        return False
    return (
        customer_price_signal.price_preference(text) in {"low", "high", "value"}
        or any(term in text for term in ("换", "另外", "其他", "轻一点", "大一点", "小一点", "高端一点", "便宜一点"))
    )


def _route_allows_rule_clarification(route_plan: dict[str, Any]) -> bool:
    if not route_plan:
        return True
    return route_plan.get("context_mode") == "clarify" and route_plan.get("confidence") != "low"


def _build_tool_selection_messages(
    question: str,
    sku: str | None,
    previous_result_skus: list[str],
    conversation_history: list[dict],
    feedback_lessons: list[dict],
    route_plan: dict[str, Any] | None = None,
    entity_stack: list[dict] | None = None,
    route_hints: dict[str, Any] | None = None,
) -> list[dict]:
    entity_stack = entity_stack or []
    conversation_context = _conversation_context_for_question(question, conversation_history)
    dialogue_state = customer_dialogue_state.build_dialogue_state(question, conversation_history).to_dict()
    recommendation_question = _recommendation_question_with_context(question, conversation_history)
    return [
        {
            "role": "system",
            "content": (
                "你是内部产品数据库 Agent。你可以自己选择后端白名单工具查询产品、读取详情、提出修改或删除建议。"
                "严禁编写 SQL，严禁直接执行写库。所有修改/删除只能调用 propose_* 工具生成待确认动作。"
                "如果用户要查询多个产品、条形码、类目或功能，优先调用 search_products。"
                "如果同时有精确条件和模糊语义需求，优先调用 hybrid_search_products。"
                "search_products 支持 term 全字段搜索，也支持 filters 精确筛选，例如 {\"负责人\":\"Yao\",\"类目\":\"锅具\"}。"
                "如果用户在问题文本或历史对话里明确给了 SKU，并问单品字段，调用 get_product_detail。"
                "如果用户说“这些/刚才那些/上面这些”，优先结合 entity_stack 判断指代对象，再使用 previous_result_skus。"
                "如果本轮问题是完整的新需求（例如重新说明人数、场景、用途、产品类型），以当前问题为准重新检索；不要把上一轮 SKU 当默认范围。"
                "如果本轮是“预算不高/便宜点/性价比”等追问，要继承上一轮用户的场景、人群和用途，但必须重新按价格定位、产品定位和候选资料判断，不能把高端定位产品说成低预算推荐。"
                "如果本轮是“高端一点/不喜欢这几款/换一款”等推荐追问，要使用 recommendation_question 里的完整合并需求检索，不要只按本轮短句筛选。"
                "如果用户在历史对话里已经给过范围，本轮追问如“哪种适合送礼/三个年轻人用哪个好”，要结合 conversation_history 和 previous_result_skus 决定工具。"
                "凡是涉及产品事实、推荐、对比、筛选、修改或删除，必须先调用工具；只有闲聊、解释能力边界或澄清问题可以直接 answer。"
                "如果问题缺少必要范围，不要猜，输出澄清 answer。"
                "做推荐/送礼/适合谁时，优先读取候选产品的容量、材质、卖点、使用场景、目标人群、情绪价值，再给取舍理由。"
                "如果 recent_feedback_lessons 里有相似问题，要避免重复其中的错误。"
                "复杂任务可以多轮调用工具，例如先 search_products，再对结果 SKU 调 propose_update_product_field。"
                "route_hints 是系统预分析结果，仅供参考。你可以基于用户问题、对话历史和实体栈自行判断，不必完全遵从 route_hints。"
                "你必须只输出 JSON，不要 Markdown。格式："
                "{\"tool_calls\":[{\"name\":\"search_products\",\"arguments\":{\"term\":\"\",\"filters\":{\"负责人\":\"Yao\",\"类目\":\"锅具\"},\"fields\":[\"容量\"]}}]}"
                "如果确实不需要工具，输出 {\"answer\":\"...\"}。"
            ),
        },
        {
            "role": "user",
            "content": json.dumps(
                {
                    "question": question,
                    "recommendation_question": recommendation_question,
                    "previous_result_skus": previous_result_skus,
                    "entity_stack": entity_stack[:30],
                    "route_hints": route_hints or {},
                    "route_plan": route_plan or {},
                    "conversation_context": conversation_context,
                    "dialogue_state": dialogue_state,
                    "conversation_history": conversation_history[-4:] if len(conversation_history) > 4 else conversation_history,
                    "recent_feedback_lessons": feedback_lessons[:8],
                    "available_tools": customer_agent_tool_service.list_tool_specs(),
                },
                ensure_ascii=False,
            ),
        },
    ]


def _conversation_context_for_question(question: str, conversation_history: list[dict]) -> dict:
    return customer_dialogue_state.build_conversation_context(question, conversation_history)


async def _route_deterministic_fact_question(
    db: Session,
    user_id: str,
    question: str,
    sku: str | None,
    previous_result_skus: list[str],
) -> dict | None:
    if _requires_write_tool(question):
        return None
    intent = customer_agent_intent_service.parse_intent(
        question,
        sku=sku,
        previous_result_skus=previous_result_skus,
    )
    if not intent:
        return None
    if intent.intent == "compare_products":
        result = await customer_agent_intent_service.process_intent_request(
            db,
            user_id=user_id,
            question=question,
            sku=sku,
            previous_result_skus=previous_result_skus,
        )
        if result:
            debug = dict(result.get("debug") or {})
            debug["agent_mode"] = "deterministic_compare_route"
            result["debug"] = debug
            result["skip_polish"] = True
        return result
    if intent.intent == "query_products" and _has_specs_field_filter(intent) and not _looks_like_recommendation_text(question):
        result = await customer_agent_intent_service.process_intent_request(
            db,
            user_id=user_id,
            question=question,
            sku=sku,
            previous_result_skus=previous_result_skus,
        )
        if result:
            debug = dict(result.get("debug") or {})
            debug["agent_mode"] = "deterministic_field_filter_route"
            result["debug"] = debug
        return result
    if not intent.requested_fields:
        return None
    if intent.intent not in {"product_detail", "query_products"}:
        return None
    if _has_explicit_product_field_query(intent, question, sku):
        result = await customer_agent_intent_service.process_intent_request(
            db,
            user_id=user_id,
            question=question,
            sku=sku,
            previous_result_skus=previous_result_skus,
        )
        if result:
            debug = dict(result.get("debug") or {})
            debug["agent_mode"] = "deterministic_explicit_product_field_route"
            result["debug"] = debug
        return result
    if _looks_like_recommendation_text(question):
        return None
    if _looks_like_multi_product_fact_question(question):
        return None
    if not _looks_like_single_product_fact_intent(intent):
        return None
    single_field_sufficient = getattr(intent, "is_single_field_sufficient", True)
    result = await customer_agent_intent_service.process_intent_request(
        db,
        user_id=user_id,
        question=question,
        sku=sku,
        previous_result_skus=previous_result_skus,
    )
    if not result:
        return None
    debug = dict(result.get("debug") or {})
    debug["agent_mode"] = "deterministic_fact_route" if single_field_sufficient else "deterministic_field_route"
    result["debug"] = debug
    if single_field_sufficient:
        result["skip_polish"] = True
    return result


def _looks_like_single_product_fact_intent(intent: Any) -> bool:
    if _looks_like_recommendation_text(
        " ".join(
            str(getattr(intent, key, "") or "")
            for key in ("term", "semantic_query", "recommendation_query")
        )
    ):
        return False
    if intent.target_skus and len(intent.target_skus) == 1:
        return True
    term = str(intent.term or "").strip()
    if not term:
        return False
    if len(term) <= 2:
        return False
    if _looks_like_product_type_only(term):
        return False
    return True


def _has_explicit_product_field_query(intent: Any, question: str, sku: str | None = None) -> bool:
    requested_fields = getattr(intent, "requested_fields", None) or []
    if not requested_fields:
        return False
    if len(requested_fields) == 1 and getattr(intent, "is_single_field_sufficient", True):
        return False
    if _looks_like_multi_product_fact_question(question):
        return False
    if sku or getattr(intent, "target_skus", None):
        return True
    term = str(getattr(intent, "term", "") or "").strip()
    if not term or len(term) <= 2 or _looks_like_product_type_only(term):
        return False
    text = str(question or "")
    return bool(SKU_RE.search(text) or re.search(r"[「“].+?[」”]", text) or term in text)


def _has_specs_field_filter(intent: Any) -> bool:
    filters = getattr(intent, "filters", {}) or {}
    return any(str(field).startswith("specs.") for field in filters)


def _looks_like_product_type_only(term: str) -> bool:
    return term.strip().lower() in {
        "锅", "锅具", "炉", "炉具", "杯", "杯子", "壶", "水壶", "碗", "盘", "餐具",
        "刀", "铲", "勺", "桌", "椅", "灯", "帐篷", "睡袋", "产品", "商品",
    }


def _looks_like_multi_product_fact_question(question: str) -> bool:
    text = str(question or "")
    return any(term in text for term in ("所有", "全部", "哪些", "哪几", "分别", "各自", "每个", "每款", "列出", "清单", "一览"))


def _looks_like_recommendation_text(text: str) -> bool:
    normalized = str(text or "")
    return any(term in normalized for term in ("推荐", "适合", "买", "选", "哪款", "哪个好", "旅行", "露营", "两个人", "双人", "煎炒煮"))


def _is_tool_round_limited_recommendation(question: str, route_plan: dict[str, Any] | None) -> bool:
    if (route_plan or {}).get("query_type") == "recommendation":
        return True
    text = str(question or "")
    return any(term in text for term in ("推荐", "换一个推荐", "再推荐", "不要刚才", "别要刚才"))


def _context_compare_fast_path_skus(
    db: Session,
    question: str,
    entity_stack: list[dict],
    recommendation_summary: dict | None,
) -> list[str]:
    candidates = _context_candidate_skus(entity_stack, recommendation_summary)
    if not _is_compare_like_question(question, context_skus=candidates):
        return []
    if len(candidates) < 2:
        return []
    text = str(question or "")
    if any(term in text for term in ("\u7b2c\u4e00\u4e2a", "\u7b2c\u4e8c\u4e2a", "\u7b2c\u4e00\u6b3e", "\u7b2c\u4e8c\u6b3e")):
        return candidates[:2]
    if _asks_high_vs_entry(question):
        return _pick_high_and_entry_skus(db, candidates)
    if len(candidates) == 2:
        return candidates
    return []


def _context_candidate_skus(entity_stack: list[dict], recommendation_summary: dict | None) -> list[str]:
    skus: list[str] = []
    for sku in (recommendation_summary or {}).get("candidate_skus") or []:
        sku_text = str(sku or "").strip().upper()
        if sku_text and sku_text not in skus:
            skus.append(sku_text)
    for sku in (recommendation_summary or {}).get("ordered_result_skus") or []:
        sku_text = str(sku or "").strip().upper()
        if sku_text and sku_text not in skus:
            skus.append(sku_text)
    for sku in (recommendation_summary or {}).get("result_skus") or []:
        sku_text = str(sku or "").strip().upper()
        if sku_text and sku_text not in skus:
            skus.append(sku_text)
    for item in entity_stack or []:
        sku_text = str((item or {}).get("sku") or "").strip().upper()
        if sku_text and sku_text not in skus:
            skus.append(sku_text)
    return skus[:10]


def _asks_high_vs_entry(question: str) -> bool:
    text = str(question or "")
    high_terms = ("高端", "高价", "高配", "旗舰", "专业")
    entry_terms = ("入门", "基础", "低端", "低价", "亲民", "便宜", "性价比")
    return any(term in text for term in high_terms) and any(term in text for term in entry_terms)


def _pick_high_and_entry_skus(db: Session, candidate_skus: list[str]) -> list[str]:
    high_sku = None
    entry_sku = None
    lowest_sku = None
    lowest_rank = 99
    for sku in candidate_skus[:10]:
        try:
            detail = product_service.get_product_detail(db, sku)
        except Exception:
            continue
        bucket = _price_position_bucket(detail)
        rank = _price_bucket_rank(bucket)
        if rank < lowest_rank:
            lowest_rank = rank
            lowest_sku = sku
        if bucket == "high" and not high_sku:
            high_sku = sku
        elif bucket == "entry" and not entry_sku:
            entry_sku = sku
        if high_sku and entry_sku:
            break
    if high_sku and entry_sku and high_sku != entry_sku:
        return [high_sku, entry_sku]
    if high_sku and lowest_sku and high_sku != lowest_sku:
        return [high_sku, lowest_sku]
    if high_sku:
        for sku in candidate_skus[:10]:
            if sku != high_sku:
                return [high_sku, sku]
    return []


def _price_position_bucket(detail: dict) -> str | None:
    business = detail.get("business") if isinstance(detail, dict) else {}
    text = " ".join(
        str(value or "")
        for value in (
            detail.get("price_positioning") if isinstance(detail, dict) else "",
            (business or {}).get("price_positioning") if isinstance(business, dict) else "",
            (business or {}).get("positioning") if isinstance(business, dict) else "",
            (business or {}).get("target_audience") if isinstance(business, dict) else "",
        )
    )
    if any(term in text for term in ("高端", "高价", "高配", "旗舰", "专业")):
        return "high"
    if any(term in text for term in ("中端", "中档", "中价", "中等")):
        return "mid"
    if any(term in text for term in ("入门", "基础", "低端", "低价", "亲民", "便宜", "性价比")):
        return "entry"
    return None


def _price_bucket_rank(bucket: str | None) -> int:
    return {"entry": 1, "mid": 2, "high": 3}.get(bucket or "", 50)


def _is_specific_recommendation_question(question: str) -> bool:
    text = str(question or "")
    return any(term in text for term in ("露营", "两个人", "2个人", "双人", "做饭", "锅", "酒精炉", "野餐", "烧水", "材质", "容量", "重量", "便携"))


def _context_detail_fields(question: str, conversation_history: list[dict]) -> list[str]:
    fields = customer_agent_tool_service.query_fields_from_text(question)
    if fields:
        return fields
    if not _is_confirmation(question):
        return []
    for item in reversed(conversation_history[-4:]):
        content = str(item.get("content") or "")
        fields = customer_agent_tool_service.query_fields_from_text(content)
        if fields:
            return fields
    return []


def _context_requested_fields_from_intent(question: str, previous_result_skus: list[str]) -> list[str]:
    intent = customer_agent_intent_service.parse_intent(
        question,
        previous_result_skus=previous_result_skus,
    )
    fields: list[str] = []
    for field in (getattr(intent, "requested_fields", None) or []):
        normalized = str(field or "").strip()
        if normalized and normalized not in fields:
            fields.append(normalized)
    return fields


def _is_safety_usage_followup(question: str) -> bool:
    text = str(question or "")
    if any(term in text for term in ("认证", "认证信息", "FDA", "LFGB", "食品级", "304", "不锈钢", "材质", "耐腐蚀")):
        return False
    return any(term in text for term in (
        "\u5b89\u5168\u5417",
        "\u5b89\u5168\u6027",
        "\u5b89\u5168",
        "\u6ce8\u610f\u4e8b\u9879",
        "\u7981\u5fcc",
        "\u5e10\u7bf7",
        "\u5bc6\u95ed",
        "\u5ba4\u5185",
        "\u66b4\u6652",
        "\u660e\u706b",
        "\u5b58\u653e",
        "\u50a8\u5b58",
        "\u901a\u98ce",
        "\u80fd\u4e0d\u80fd",
        "\u80fd\u5426",
        "\u53ef\u4ee5\u4e0d\u53ef\u4ee5",
    ))


def _is_contextual_safety_or_certification_followup(question: str) -> bool:
    text = str(question or "")
    if _is_safety_usage_followup(text):
        return True
    return any(term in text for term in (
        "\u98df\u54c1\u7ea7",
        "\u8ba4\u8bc1",
        "\u8ba4\u8bc1\u4fe1\u606f",
        "FDA",
        "LFGB",
        "304",
        "\u4e0d\u9508\u94a2",
        "\u6750\u8d28",
        "\u8010\u8150\u8680",
    ))


def _safety_detail_fields() -> list[str]:
    return [
        "specs.body_material",
        "specs.usage_instruction",
        "business.top_selling_points",
        "certifications",
    ]


def _has_explicit_product_reference(question: str) -> bool:
    text = str(question or "")
    if any(term in text for term in ("刚才", "之前", "前面", "上次", "最开始", "第一个", "第一款", "最后", "上一个")):
        return False
    if SKU_RE.search(text):
        return True
    if re.search(r"[「“].+?[」”]", text):
        return True
    intent = customer_agent_intent_service.parse_intent(text, previous_result_skus=[])
    term = getattr(intent, "term", "") if intent else ""
    if not term:
        return False
    normalized = str(term).strip()
    generic_terms = {"锅", "炉", "杯", "壶", "包", "锅具", "炉具", "水具", "餐具", "杯具", "产品", "商品"}
    if len(normalized) < 3 or normalized in generic_terms:
        return False
    return bool(re.search(r"(?:套锅|炒锅|煎锅|单锅|野营锅|锅|酒精炉|气炉|炉|杯套装|杯|水壶|壶|包)$", normalized))


def _is_confirmation(question: str) -> bool:
    return str(question or "").strip(" ，。！？?") in CONFIRMATION_TERMS


class _AnswerJsonDeltaExtractor:
    def __init__(self) -> None:
        self.buffer = ""
        self.pos = 0
        self.stage = "find_key"
        self.escape = False
        self.unicode_escape = ""

    def feed(self, chunk: str) -> str:
        self.buffer += str(chunk or "")
        out: list[str] = []
        while self.pos < len(self.buffer):
            if self.stage == "find_key":
                index = self.buffer.find('"answer"', self.pos)
                if index < 0:
                    self.pos = max(0, len(self.buffer) - len('"answer"'))
                    break
                self.pos = index + len('"answer"')
                self.stage = "find_colon"
                continue
            ch = self.buffer[self.pos]
            self.pos += 1
            if self.stage == "find_colon":
                if ch == ":":
                    self.stage = "find_quote"
                continue
            if self.stage == "find_quote":
                if ch == '"':
                    self.stage = "in_string"
                continue
            if self.stage != "in_string":
                continue
            if self.unicode_escape:
                self.unicode_escape += ch
                if len(self.unicode_escape) == 4:
                    try:
                        out.append(chr(int(self.unicode_escape, 16)))
                    except ValueError:
                        pass
                    self.unicode_escape = ""
                    self.escape = False
                continue
            if self.escape:
                if ch == "n":
                    out.append("\n")
                elif ch == "r":
                    out.append("\r")
                elif ch == "t":
                    out.append("\t")
                elif ch == "u":
                    self.unicode_escape = ""
                    continue
                else:
                    out.append(ch)
                self.escape = False
                continue
            if ch == "\\":
                self.escape = True
                continue
            if ch == '"':
                self.stage = "done"
                break
            out.append(ch)
        return "".join(out)


async def _finalize_answer(
    db: Session,
    question: str,
    sku: str | None,
    tool_results: list[dict],
    conversation_history: list[dict],
    *,
    conversation_id: str | None = None,
    user_id: str | None = None,
    intent_hint: str | None = None,
    entity_stack: list[dict] | None = None,
    route_hints: dict[str, Any] | None = None,
    answer_delta_callback: Callable[[str], Awaitable[None]] | None = None,
) -> str | None:
    conversation_context = _conversation_context_for_question(question, conversation_history)
    last_turn_summary = _last_turn_summary(db, conversation_id, user_id)
    retrieved_products = _collect_results(tool_results)
    grouped_retrieved_products = _group_retrieved_products_by_sku(retrieved_products)
    compact_retrieved_products = [_compact_retrieved_product_for_prompt(item) for item in grouped_retrieved_products[:5]]
    compact_tool_results = _compact_prompt_tool_results(tool_results)
    effective_intent_hint = intent_hint or _infer_intent(
        question,
        tool_results,
        _collect_actions(tool_results),
        retrieved_products,
        False,
    )
    recommendation_context = _latest_recommendation_context(db, conversation_id, user_id)
    prompt_recommendation_context = {}
    if recommendation_context:
        prompt_recommendation_context = {
            "\u539f\u59cb\u54c1\u7c7b\u9700\u6c42": recommendation_context.get("product_scope") or "",
            "\u539f\u59cb\u7528\u6237\u9700\u6c42": recommendation_context.get("user_question") or "",
            "\u5df2\u63a8\u8350\u8fc7\u7684SKU": recommendation_context.get("recommended_skus") or [],
        }
    if effective_intent_hint == "recommend_products":
        compact_retrieved_products = [
            _compact_recommendation_product_for_prompt(item)
            for item in grouped_retrieved_products[:5]
        ]
        compact_tool_results = []
    prompt_route_hints = dict(route_hints or {})
    if effective_intent_hint == "product_detail":
        prompt_target_skus = _product_detail_prompt_target_skus(
            sku,
            retrieved_products,
            prompt_route_hints,
        )
        if prompt_target_skus:
            scoped_history = _filter_history_for_product_detail(
                conversation_history,
                prompt_target_skus,
                entity_stack or [],
            )
            conversation_context = _conversation_context_for_question(question, scoped_history)
            prompt_entity_stack = [
                item for item in (entity_stack or [])
                if str(item.get("sku") or "").strip().upper() in prompt_target_skus
            ][:30]
            prompt_route_hints["entity_stack"] = prompt_entity_stack
            prompt_route_hints["resolved_skus"] = prompt_target_skus
            if not set(last_turn_summary.get("result_skus") or []).intersection(prompt_target_skus):
                last_turn_summary = {"intent": None, "result_skus": [], "user_question": None}
            prompt_recommendation_context = {}
        else:
            scoped_history = conversation_history
            prompt_entity_stack = (entity_stack or [])[:30]
    else:
        scoped_history = conversation_history
        prompt_entity_stack = (entity_stack or [])[:30]
    if effective_intent_hint == "product_detail" and (route_hints or {}).get("explanation_followup") is True:
        compact_retrieved_products = []
    if effective_intent_hint == "product_detail" and (route_hints or {}).get("entity_stack_direct_detail") is True:
        compact_retrieved_products = []
    if effective_intent_hint == "recommend_products" and (route_hints or {}).get("fast_path") is True:
        prompt_conversation_history = []
        prompt_entity_stack = []
    elif effective_intent_hint == "product_detail" and (route_hints or {}).get("explanation_followup") is True:
        prompt_conversation_history = scoped_history[-2:] if len(scoped_history) > 2 else scoped_history
    else:
        prompt_conversation_history = scoped_history[-4:] if len(scoped_history) > 4 else scoped_history
    messages = [
        {
            "role": "system",
            "content": (
                "你是alocs爱路客的产品客服助手。"
                "【核心规则，最高优先级】"
                "1. 严禁引入retrieved_products之外的产品事实、参数、认证、价格或库存。"
                "2. 工具结果里没有的信息，必须说\"暂无此数据\"，不得推断或编造。"
                "3. 用户没有问到的话题不要主动引入（用户没问认证就不提认证，没问食品级就不提食品级）。"
                "产品数据可能包含嵌套的specs字段，specs里的内容（如gross_weight_g/body_material/surface_finish等）都是产品属性，回答时需要一起读取，不要忽略嵌套字段里的数据。"
                "【回答方式】"
                "- 先给结论，再给依据。"
                "- 对比类问题：直接给对比结论（哪个更轻/哪个容量更大/有什么区别）。"
                "- 筛选类问题：只有在用户明确是在做筛选/检索时，才列出符合条件的产品，不要只说\"找到N条资料\"。"
                "- 推荐类问题：说明推荐理由，引用产品的具体参数或卖点。"
                "- 参数查询：直接给参数值，来源是retrieved_products。"
                "- 如果用户问的是某种说法能不能确认、能不能承诺、能不能宣传、是否有禁用/限制话术，先判断当前知识库有没有专门维护这类负向信息；如果没有，就直接说明暂无此数据，不要改写成产品介绍或参数罗列。"
                "【上下文处理】"
                "- 用户追问上一轮（为什么/理由/解释一下）：基于last_turn_summary.result_skus解释，不重新检索。"
                "- 用户本轮重新说明了需求（新的人数/场景/预算）：以本轮question和tool_results为准。"
                "- 用户说预算有限/便宜一点：优先推荐价格定位为中端或入门的产品，高端产品不作首选。"
                "【格式要求】"
                "- 不使用Markdown（不用**、###、表格语法）。"
                "- 不使用任何HTML标签（不用<br>、<p>、<b>等）。"
                "- 只输出JSON：{\"answer\":\"...\"}。"
            ),
        },
        {
            "role": "user",
            "content": json.dumps(
                {
                    "question": question,
                    "conversation_context": conversation_context,
                    "conversation_history": prompt_conversation_history,
                    "last_turn_summary": last_turn_summary,
                    "intent_hint": effective_intent_hint,
                    "entity_stack": prompt_entity_stack,
                    "route_hints": prompt_route_hints,
                    "recommendation_context": prompt_recommendation_context,
                    "retrieved_products": compact_retrieved_products,
                    "tool_results": compact_tool_results,
                },
                ensure_ascii=False,
                default=str,
            ),
        },
    ]
    messages.insert(1, {
        "role": "system",
        "content": (
            "Output JSON must include answer, answer_policy and evidence_insufficient. "
            "Use answer_policy='insufficient_evidence' and evidence_insufficient=true when the available evidence does not explicitly maintain or confirm the information asked by the user. "
            "Otherwise use answer_policy='normal' and evidence_insufficient=false."
        ),
    })
    messages.insert(1, {
        "role": "system",
        "content": (
            "回答时先直接回答用户原问题，再用证据补充。retrieved_products 和 tool_results 只是证据，不是最终答案。"
            "不要把“找到 N 条产品资料”当成最终回答，也不要只复述检索结果列表。"
            "如果资料里没有明确维护用户问到的信息，要明确说明“当前知识库没有维护/现有资料不足以确认”，不要编造。"
            "如果资料里有相关字段或证据，就基于证据总结；如果资料不足，就先说明不足，再给出已能确认的信息。"
            "同一个 SKU / product_id 的多个 chunk 已经在进入这里之前聚合成一个产品卡片，回答时按产品卡片分析，不要再拆回 chunk。"
            "当用户问的是某种说法能不能确认、能不能承诺、能不能宣传、有没有禁用话术、资料是否维护时，优先回答“知识库有没有这类资料、资料能否支持确认”，不要改写成产品介绍、规格罗列或检索结果清单。"
            "如果检索到的内容里没有专门维护的负向/限制/禁用信息，就不要把正向卖点、规格或通用产品描述拼成“不能承诺内容”；应直接说明当前知识库没有维护这类内容，最多补充可确认的基础资料。"
        ),
    })
    agent_trace_service.trace("FINAL_REQUEST", {"messages": messages})
    try:
        if answer_delta_callback:
            content_parts: list[str] = []
            answer_extractor = _AnswerJsonDeltaExtractor()
            async for chunk in customer_llm_service.chat_completion_stream(db, messages, temperature=0.2, max_tokens=1200, purpose="final_answer"):
                content_parts.append(chunk)
                answer_delta = answer_extractor.feed(chunk)
                if answer_delta:
                    await answer_delta_callback(answer_delta)
            content = "".join(content_parts)
        else:
            content = await customer_llm_service.chat_completion(db, messages, temperature=0.2, max_tokens=1200, purpose="final_answer")
    except Exception as exc:
        agent_trace_service.trace("FINAL_ERROR", {"error": str(exc)})
        return None
    agent_trace_service.trace("FINAL_RESPONSE", {"content": content})
    data = _parse_json_object(content)
    if data and data.get("answer"):
        answer = str(((_parse_json_object(str(data["answer"])) or {}).get("answer")) or data["answer"])
        evidence_insufficient = data.get("evidence_insufficient") is True or data.get("answer_policy") == "insufficient_evidence"
        return {
            "answer": _clean_customer_answer(answer),
            "answer_metadata": {
                "evidence_insufficient": evidence_insufficient,
                "answer_policy": "insufficient_evidence" if evidence_insufficient else "normal",
            },
        }
    cleaned = _clean_customer_answer(content)
    return {"answer": cleaned, "answer_metadata": {}} if cleaned else None


def _product_detail_prompt_target_skus(
    sku: str | None,
    retrieved_products: list[dict],
    route_hints: dict[str, Any],
) -> list[str]:
    candidates = [
        *(route_hints.get("resolved_skus") or []),
        sku,
        *(item.get("sku") for item in retrieved_products if isinstance(item, dict)),
    ]
    return _unique_skus([str(item or "") for item in candidates])


def _filter_history_for_product_detail(
    conversation_history: list[dict],
    target_skus: list[str],
    entity_stack: list[dict],
) -> list[dict]:
    target_set = {str(item or "").strip().upper() for item in target_skus if str(item or "").strip()}
    target_markers = set(target_set)
    for entity in entity_stack:
        if str(entity.get("sku") or "").strip().upper() not in target_set:
            continue
        name = str(entity.get("name") or "").strip()
        if name:
            target_markers.add(name)

    scoped: list[dict] = []
    index = 0
    while index < len(conversation_history):
        turn = [conversation_history[index]]
        if (
            conversation_history[index].get("role") == "user"
            and index + 1 < len(conversation_history)
            and conversation_history[index + 1].get("role") == "assistant"
        ):
            turn.append(conversation_history[index + 1])
            index += 1
        combined = "\n".join(str(item.get("content") or "") for item in turn)
        combined_upper = combined.upper()
        if any(marker in combined or marker in combined_upper for marker in target_markers):
            scoped.extend(turn)
        index += 1
    return scoped


PRODUCT_FIELD_DISPLAY_NAMES = {
    "product_name_cn": "产品名称",
    "surface_finish": "表面处理",
    "body_material": "主体材质",
    "heat_source": "适用热源",
    "certifications": "认证信息",
    "capacity": "容量",
}


def _localize_product_field_keys(value: Any) -> Any:
    if isinstance(value, list):
        return [_localize_product_field_keys(item) for item in value]
    if isinstance(value, tuple):
        return [_localize_product_field_keys(item) for item in value]
    if not isinstance(value, dict):
        return value
    localized = {}
    for key, item in value.items():
        display_key = PRODUCT_FIELD_DISPLAY_NAMES.get(str(key), key)
        localized[display_key] = _localize_product_field_keys(item)
    return localized


def _compact_retrieved_product_for_prompt(product: Any) -> Any:
    if not isinstance(product, dict):
        return product
    if isinstance(product.get("content"), str) and not any(
        product.get(key) not in (None, "", [], {})
        for key in ("product_name_cn", "product_name_en", "category", "specs", "business")
    ) and not any(product.get(key) not in (None, "", [], {}) for key in ("evidence_sections", "matched_sections", "knowledge_matches")):
        return _compact_knowledge_result_for_prompt(product)

    def _spec_entry_text(value: Any) -> str:
        if value in (None, "", []):
            return ""
        if not isinstance(value, dict):
            return str(value).strip()
        label = str(value.get("label") or "").strip()
        raw_value = str(value.get("value") or "").strip()
        unit = str(value.get("unit") or "").strip()
        if not raw_value:
            return label
        value_text = f"{raw_value}{unit}" if unit and not raw_value.endswith(unit) else raw_value
        return f"{label}：{value_text}" if label else value_text

    def _first_text(value: Any, *, limit: int = 160) -> str:
        if value in (None, "", []):
            return ""
        if isinstance(value, list):
            parts = [str(item).strip() for item in value if str(item).strip()]
            text = "；".join(parts[:3])
        else:
            text = str(value).strip()
        return text[:limit]

    def _first_item(value: Any) -> Any:
        if isinstance(value, list):
            for item in value:
                if item not in (None, "", []):
                    return item
            return ""
        return value

    compact: dict[str, Any] = {}
    for key in ("sku", "product_name_cn", "product_name_en", "category", "sub_category", "price_positioning"):
        value = product.get(key)
        if value not in (None, "", []):
            compact[key] = value

    channels = product.get("channels")
    if isinstance(channels, list):
        compact["channels"] = [
            {
                key: item.get(key)
                for key in ("channel_name", "channel_code")
                if item.get(key) not in (None, "")
            }
            for item in channels
            if isinstance(item, dict) and (item.get("channel_name") or item.get("channel_code"))
        ]

    specs = product.get("specs") or {}
    if not isinstance(specs, dict):
        specs = {}
    business = product.get("business") or {}
    if not isinstance(business, dict):
        business = {}
    content = product.get("content") or {}
    recommendation_match = product.get("recommendation_match") or {}
    if not isinstance(recommendation_match, dict):
        recommendation_match = {}

    for key, value in {
        "capacity": _spec_entry_text(_first_item(specs.get("capacity"))),
        "gross_weight_g": specs.get("gross_weight_g"),
        "body_material": _first_text(specs.get("body_material")),
        "surface_finish": _first_text(specs.get("surface_finish")),
        "heat_source": _first_text(specs.get("heat_source")),
        "top_selling_points": _first_text(business.get("top_selling_points"), limit=240),
        "usage_scenarios": _first_text(business.get("usage_scenarios"), limit=200),
        "target_audience": _first_text(business.get("target_audience"), limit=200),
        "positioning": _first_text(business.get("positioning"), limit=240),
    }.items():
        if value not in (None, "", []):
            compact[key] = value

    if content:
        if isinstance(content, dict):
            compact["content"] = {
                key: _first_text(content.get(key), limit=160)
                for key in ("title_cn", "title_en")
                if content.get(key) not in (None, "", [])
            }
        else:
            compact["content"] = {"text": _first_text(content, limit=240)}
    if recommendation_match:
        compact["recommendation_match"] = {
            key: recommendation_match.get(key)
            for key in ("score", "score_reason", "matched", "missing_or_uncertain")
            if recommendation_match.get(key) not in (None, "", [])
        }
    evidence_sections = product.get("evidence_sections") or []
    if isinstance(evidence_sections, list) and evidence_sections:
        compact["evidence_sections"] = [
            _compact_evidence_section_for_prompt(section)
            for section in evidence_sections[:12]
            if isinstance(section, dict)
        ]
    matched_sections = product.get("matched_sections") or []
    if isinstance(matched_sections, list) and matched_sections:
        compact["matched_sections"] = [
            str(section).strip()
            for section in matched_sections
            if str(section or "").strip()
        ][:12]
    knowledge_matches = product.get("knowledge_matches") or []
    if isinstance(knowledge_matches, list) and knowledge_matches:
        compact["knowledge_matches"] = [
            _compact_knowledge_result_for_prompt(match)
            for match in knowledge_matches[:8]
            if isinstance(match, dict)
        ]
    return compact


def _compact_recommendation_product_for_prompt(product: Any) -> Any:
    compact = _compact_retrieved_product_for_prompt(product)
    if not isinstance(compact, dict):
        return compact
    allowed_keys = (
        "sku",
        "product_name_en",
        "category",
        "gross_weight_g",
        "top_selling_points",
        "usage_scenarios",
        "target_audience",
        "positioning",
        "recommendation_match",
    )
    return {
        key: compact[key]
        for key in allowed_keys
        if compact.get(key) not in (None, "", [], {})
    }


def _compact_prompt_tool_results(tool_results: list[dict]) -> list[dict]:
    compacted: list[dict] = []
    for result in tool_results[:5]:
        if not isinstance(result, dict):
            continue
        item: dict[str, Any] = {}
        for key in ("tool", "query", "sku", "skus", "count", "mode", "label", "error"):
            value = result.get(key)
            if value not in (None, "", [], {}):
                item[key] = value
        if result.get("results"):
            grouped_results = _group_retrieved_products_by_sku(result.get("results") or [])
            if result.get("tool") == "semantic_search_knowledge":
                item["results"] = [_compact_retrieved_product_for_prompt(row) for row in grouped_results[:5]]
            else:
                item["results"] = [_compact_retrieved_product_for_prompt(row) for row in grouped_results[:5]]
        if result.get("detail"):
            item["detail"] = _compact_retrieved_product_for_prompt(result.get("detail"))
        if result.get("details"):
            grouped_details = _group_retrieved_products_by_sku(result.get("details") or [])
            item["details"] = [_compact_retrieved_product_for_prompt(row) for row in grouped_details[:3]]
        if result.get("sources"):
            item["sources"] = (result.get("sources") or [])[:3]
        compacted.append(item or {"tool": result.get("tool")})
    return compacted


def _compact_knowledge_result_for_prompt(row: Any) -> Any:
    if not isinstance(row, dict):
        return row
    item: dict[str, Any] = {}
    for key in ("source_type", "sku", "content", "score"):
        value = row.get(key)
        if value not in (None, "", [], {}):
            item[key] = str(value)[:500] if key == "content" else value
    metadata = row.get("metadata")
    if isinstance(metadata, dict):
        compact_metadata = {
            key: metadata.get(key)
            for key in ("source_id", "source_type", "file_type", "page_number", "title")
            if metadata.get(key) not in (None, "", [], {})
        }
        if compact_metadata:
            item["metadata"] = compact_metadata
    return item


def _compact_evidence_section_for_prompt(section: dict[str, Any]) -> dict[str, Any]:
    compact: dict[str, Any] = {}
    for key in ("section", "source_type", "source_id", "title", "score"):
        value = section.get(key)
        if value not in (None, "", [], {}):
            compact[key] = value
    content = section.get("content")
    if content not in (None, "", [], {}):
        compact["content"] = str(content)[:500]
    return compact


def _has_specs_filter(question: str) -> bool:
    intent = customer_agent_intent_service.parse_intent(question, previous_result_skus=[])
    return bool(intent and _has_specs_field_filter(intent))


COMPARE_LIKE_TERMS = ("对比", "比较", "区别", "差异", "是否一样", "哪个更", "差多少", "不同")
COMPARE_SKU_RE = re.compile(r"[A-Z]{1,6}(?:[-_][A-Z0-9]{1,12}){1,4}", flags=re.IGNORECASE)


def _is_compare_like_question(
    question: str,
    *,
    candidate_skus: list[str] | None = None,
    context_skus: list[str] | None = None,
) -> bool:
    text = str(question or "")
    if (
        any(term in text for term in ("\u7b2c\u4e00\u4e2a", "\u7b2c\u4e8c\u4e2a", "\u7b2c\u4e00\u6b3e", "\u7b2c\u4e8c\u6b3e"))
        and any(term in text for term in ("\u6bd4", "\u66f4"))
        and any(term in text for term in ("\u8f7b", "\u91cd", "\u91cd\u91cf"))
    ):
        return len(_unique_skus(context_skus or [])) >= 2 or len(_unique_skus(candidate_skus or [])) >= 2
    if not any(word in text for word in COMPARE_LIKE_TERMS):
        return False

    explicit_skus = _unique_skus(COMPARE_SKU_RE.findall(text))
    if len(explicit_skus) >= 2:
        return True

    if len(_unique_skus(candidate_skus or [])) >= 2:
        return True

    if len(_unique_skus(context_skus or [])) >= 2 and _references_context_compare_targets(text):
        return True

    intent = customer_agent_intent_service.parse_intent(question, previous_result_skus=[])
    return bool(
        intent
        and getattr(intent, "intent", "") == "compare_products"
        and len(_unique_skus(getattr(intent, "target_skus", []) or [])) >= 2
    )


def _unique_skus(values: list[str]) -> list[str]:
    skus: list[str] = []
    for value in values:
        sku = str(value or "").strip().replace("_", "-").upper()
        if sku and sku not in skus:
            skus.append(sku)
    return skus


def _references_context_compare_targets(text: str) -> bool:
    return (
        customer_dialogue_state.needs_previous_context(text)
        or _asks_high_vs_entry(text)
        or any(word in text for word in ("这两款", "这两个", "两者", "二者", "它们", "分别"))
    )


def _build_route_hints(
    question: str,
    explicit_product_detection: dict[str, Any] | None,
    entity_stack: list[dict] | None,
) -> dict[str, Any]:
    detection = explicit_product_detection or {}
    detected_skus: list[str] = []
    for key in ("new_skus", "matched_rows", "candidate_rows"):
        values = detection.get(key) or []
        for item in values:
            sku_value = item.get("sku") if isinstance(item, dict) else item
            sku_text = str(sku_value or "").strip().upper()
            if sku_text and sku_text not in detected_skus:
                detected_skus.append(sku_text)
    intent = customer_agent_intent_service.parse_intent(question, previous_result_skus=[])
    return {
        "detected_skus": detected_skus,
        "has_new_product": bool(detection.get("has_new_product")),
        "intent": getattr(intent, "intent", "") if intent else "",
        "has_specs_filter": bool(intent and _has_specs_field_filter(intent)),
        "is_comparison": bool(intent and getattr(intent, "intent", "") == "compare_products"),
        "entity_stack": (entity_stack or [])[:30],
    }


def _is_explanation_followup(question: str, last_turn_summary: dict) -> bool:
    if not last_turn_summary or not (last_turn_summary.get("result_skus") or []):
        return False
    if last_turn_summary.get("intent") != "recommend_products":
        return False
    text = str(question or "")
    return any(word in text for word in ("为什么", "理由", "解释", "依据", "第一个", "第一個", "首个", "首個"))


def _explanation_followup_skus(question: str, last_turn_summary: dict) -> list[str]:
    ordered_skus = [
        str(item or "").strip().upper()
        for item in (
            last_turn_summary.get("ordered_result_skus")
            or last_turn_summary.get("recommended_skus")
            or last_turn_summary.get("result_skus")
            or []
        )
        if str(item or "").strip()
    ]
    skus = ordered_skus or [
        str(item or "").strip().upper()
        for item in (last_turn_summary.get("result_skus") or [])
        if str(item or "").strip()
    ]
    if not skus:
        return []
    text = str(question or "")
    if any(word in text for word in ("绗竴涓?", "绗竴鍊?", "棣栦釜", "棣栧€?")):
        return skus[:1]
    return skus[:5]


def _is_recommendation_change_followup(question: str, last_turn_summary: dict) -> bool:
    if not last_turn_summary or last_turn_summary.get("intent") != "recommend_products":
        return False
    if not (last_turn_summary.get("result_skus") or []):
        return False
    text = str(question or "")
    return any(word in text for word in ("换一个", "换一款", "换个", "另一个", "再推荐", "不要刚才", "别要刚才", "其他推荐"))


def _last_turn_summary(db: Session, conversation_id: str | None, user_id: str | None) -> dict:
    default_summary = {"intent": None, "result_skus": [], "user_question": None, "assistant_answer": None}
    if not conversation_id or not user_id:
        return default_summary
    conversation = db.query(CustomerServiceConversation).filter(
        CustomerServiceConversation.id == conversation_id,
        CustomerServiceConversation.user_id == str(user_id),
    ).first()
    if not conversation:
        return default_summary
    assistant_message = (
        db.query(CustomerServiceMessage)
        .filter(
            CustomerServiceMessage.conversation_id == conversation.id,
            CustomerServiceMessage.role == "assistant",
        )
        .order_by(CustomerServiceMessage.created_at.desc(), CustomerServiceMessage.id.desc())
        .first()
    )
    if not assistant_message:
        return default_summary
    sources = _safe_json_loads(assistant_message.sources_json, [])
    meta = {}
    agent_context = None
    if isinstance(sources, list):
        for item in sources:
            if not isinstance(item, dict):
                continue
            if item.get("type") == "agent_meta" and not meta:
                meta = item
            elif item.get("type") == "agent_context" and agent_context is None:
                agent_context = item
    result_skus: list[str] = []
    if isinstance(agent_context, dict):
        for sku in agent_context.get("result_skus") or []:
            sku_text = str(sku or "").strip().upper()
            if sku_text:
                result_skus.append(sku_text)
        if not result_skus:
            for entity in agent_context.get("entities") or []:
                if not isinstance(entity, dict):
                    continue
                sku_text = str(entity.get("sku") or "").strip().upper()
                if sku_text:
                    result_skus.append(sku_text)
    previous_user = (
        db.query(CustomerServiceMessage)
        .filter(
            CustomerServiceMessage.conversation_id == conversation.id,
            CustomerServiceMessage.role == "user",
            CustomerServiceMessage.created_at <= assistant_message.created_at,
        )
        .order_by(CustomerServiceMessage.created_at.desc(), CustomerServiceMessage.id.desc())
        .first()
    )
    return {
        "intent": meta.get("intent") if isinstance(meta, dict) else None,
        "result_skus": result_skus,
        "user_question": previous_user.content if previous_user else None,
        "assistant_answer": assistant_message.content if assistant_message else None,
    }


def _latest_recommendation_context(db: Session, conversation_id: str | None, user_id: str | None) -> dict:
    if not conversation_id or not user_id:
        return {}
    conversation = db.query(CustomerServiceConversation).filter(
        CustomerServiceConversation.id == conversation_id,
        CustomerServiceConversation.user_id == str(user_id),
    ).first()
    if not conversation:
        return {}
    messages = (
        db.query(CustomerServiceMessage)
        .filter(
            CustomerServiceMessage.conversation_id == conversation.id,
            CustomerServiceMessage.role == "assistant",
        )
        .order_by(CustomerServiceMessage.created_at.desc(), CustomerServiceMessage.id.desc())
        .all()
    )
    for message in messages:
        sources = _safe_json_loads(message.sources_json, [])
        if not isinstance(sources, list):
            continue
        meta = next(
            (item for item in sources if isinstance(item, dict) and item.get("type") == "agent_meta"),
            {},
        )
        candidate_context = meta.get("candidate_context") if isinstance(meta, dict) else None
        context = meta.get("recommendation_context") if isinstance(meta, dict) else None
        if isinstance(context, dict) and context.get("recommended_skus"):
            user_question = str(context.get("user_question") or "").strip()
            candidate_skus = [
                str(sku).strip().upper()
                for sku in (context.get("candidate_skus") or (candidate_context or {}).get("candidate_skus") or context.get("recommended_skus") or [])
                if str(sku or "").strip()
            ]
            ordered_result_skus = [
                str(sku).strip().upper()
                for sku in (
                    context.get("ordered_result_skus")
                    or (candidate_context or {}).get("ordered_result_skus")
                    or (candidate_context or {}).get("candidate_skus")
                    or candidate_skus
                    or context.get("recommended_skus")
                    or []
                )
                if str(sku or "").strip()
            ]
            product_scope = str(context.get("product_scope") or "").strip() or customer_dialogue_state.product_scope_from_text(user_question)
            candidate_skus = _refine_followup_candidate_skus_for_scope(db, candidate_skus, product_scope, user_question)
            ordered_result_skus = _refine_followup_candidate_skus_for_scope(db, ordered_result_skus, product_scope, user_question)
            return {
                "recommended_skus": [
                    str(sku).strip().upper()
                    for sku in context.get("recommended_skus") or []
                    if str(sku or "").strip()
                ],
                "candidate_skus": candidate_skus,
                "ordered_result_skus": ordered_result_skus,
                "user_question": user_question,
                "product_scope": product_scope,
            }
        if isinstance(candidate_context, dict) and (candidate_context.get("candidate_skus") or candidate_context.get("empty_subset")):
            user_question = str(candidate_context.get("user_question") or "").strip()
            candidate_skus = [
                str(sku).strip().upper()
                for sku in candidate_context.get("candidate_skus") or []
                if str(sku or "").strip()
            ]
            ordered_result_skus = [
                str(sku).strip().upper()
                for sku in (candidate_context.get("ordered_result_skus") or candidate_skus)
                if str(sku or "").strip()
            ]
            recommended_skus = [
                str(sku).strip().upper()
                for sku in candidate_context.get("recommended_skus") or []
                if str(sku or "").strip()
            ]
            product_scope = str(candidate_context.get("product_scope") or "").strip() or customer_dialogue_state.product_scope_from_text(user_question)
            candidate_skus = _refine_followup_candidate_skus_for_scope(db, candidate_skus, product_scope, user_question)
            ordered_result_skus = _refine_followup_candidate_skus_for_scope(db, ordered_result_skus, product_scope, user_question)
            return {
                "recommended_skus": recommended_skus,
                "candidate_skus": candidate_skus,
                "ordered_result_skus": ordered_result_skus,
                "user_question": user_question,
                "product_scope": product_scope,
                "empty_subset": bool(candidate_context.get("empty_subset")),
            }
        if not isinstance(meta, dict) or meta.get("intent") != "recommend_products":
            continue
        agent_context = next(
            (item for item in sources if isinstance(item, dict) and item.get("type") == "agent_context"),
            {},
        )
        skus = [
            str(sku).strip().upper()
            for sku in agent_context.get("result_skus") or []
            if str(sku or "").strip()
        ]
        if not skus:
            continue
        previous_user = (
            db.query(CustomerServiceMessage)
            .filter(
                CustomerServiceMessage.conversation_id == conversation.id,
                CustomerServiceMessage.role == "user",
                CustomerServiceMessage.created_at <= message.created_at,
            )
            .order_by(CustomerServiceMessage.created_at.desc(), CustomerServiceMessage.id.desc())
            .first()
        )
        user_question = previous_user.content if previous_user else ""
        return {
            "recommended_skus": skus,
            "candidate_skus": skus,
            "ordered_result_skus": skus,
            "user_question": user_question,
            "product_scope": customer_dialogue_state.product_scope_from_text(user_question),
        }
    return {}


def _latest_candidate_context(db: Session, conversation_id: str | None, user_id: str | None) -> dict:
    if not conversation_id or not user_id:
        return {}
    conversation = db.query(CustomerServiceConversation).filter(
        CustomerServiceConversation.id == conversation_id,
        CustomerServiceConversation.user_id == str(user_id),
    ).first()
    if not conversation:
        return {}
    messages = (
        db.query(CustomerServiceMessage)
        .filter(
            CustomerServiceMessage.conversation_id == conversation.id,
            CustomerServiceMessage.role == "assistant",
        )
        .order_by(CustomerServiceMessage.created_at.desc(), CustomerServiceMessage.id.desc())
        .limit(20)
        .all()
    )
    for message in messages:
        sources = _safe_json_loads(message.sources_json, [])
        if not isinstance(sources, list):
            continue
        meta = next(
            (item for item in sources if isinstance(item, dict) and item.get("type") == "agent_meta"),
            {},
        )
        candidate_context = meta.get("candidate_context") if isinstance(meta, dict) else None
        if not isinstance(candidate_context, dict) or not (candidate_context.get("candidate_skus") or candidate_context.get("empty_subset")):
            continue
        return {
            "candidate_skus": [
                str(sku).strip().upper()
                for sku in candidate_context.get("candidate_skus") or []
                if str(sku or "").strip()
            ],
            "ordered_result_skus": [
                str(sku).strip().upper()
                for sku in (candidate_context.get("ordered_result_skus") or candidate_context.get("candidate_skus") or [])
                if str(sku or "").strip()
            ],
            "recommended_skus": [
                str(sku).strip().upper()
                for sku in candidate_context.get("recommended_skus") or []
                if str(sku or "").strip()
            ],
            "original_candidate_skus": [
                str(sku).strip().upper()
                for sku in (
                    candidate_context.get("original_candidate_skus")
                    or candidate_context.get("parent_candidate_skus")
                    or []
                )
                if str(sku or "").strip()
            ],
            "parent_candidate_skus": [
                str(sku).strip().upper()
                for sku in (
                    candidate_context.get("parent_candidate_skus")
                    or candidate_context.get("original_candidate_skus")
                    or []
                )
                if str(sku or "").strip()
            ],
            "filtered_skus": [
                str(sku).strip().upper()
                for sku in candidate_context.get("filtered_skus") or []
                if str(sku or "").strip()
            ],
            "user_question": str(candidate_context.get("user_question") or "").strip(),
            "product_scope": str(candidate_context.get("product_scope") or "").strip(),
            "empty_subset": bool(candidate_context.get("empty_subset")),
            "applied_filter": candidate_context.get("applied_filter") if isinstance(candidate_context.get("applied_filter"), dict) else None,
        }
    return {}


async def _handle_scoped_candidate_followup(
    db: Session,
    *,
    user_id: str,
    question: str,
    sku: str | None,
    candidate_context: dict[str, Any] | None,
    conversation_history: list[dict] | None = None,
) -> dict | None:
    domain_skus = [
        str(item or "").strip().upper()
        for item in (
            (candidate_context or {}).get("ordered_result_skus")
            or (candidate_context or {}).get("candidate_skus")
            or []
        )
        if str(item or "").strip()
    ]
    if not domain_skus:
        return None
    if _looks_like_scoped_people_filter_followup(question):
        target_people = _people_count_from_question(question)
        if not target_people:
            return None
        details_result = await customer_agent_tool_service.execute_tool_async(
            db,
            user_id=user_id,
            name="get_product_detail",
            arguments={"skus": domain_skus, "fields": []},
        )
        detail_rows = _collect_results([details_result])
        detail_by_sku = {
            str(row.get("sku") or "").strip().upper(): row
            for row in detail_rows
            if isinstance(row, dict) and str(row.get("sku") or "").strip()
        }
        filtered_rows = [
            detail_by_sku[domain_sku]
            for domain_sku in domain_skus
            if domain_sku in detail_by_sku and _row_matches_people_count(detail_by_sku[domain_sku], target_people)
        ]
        filtered_skus = [str(row.get("sku") or "").strip().upper() for row in filtered_rows if str(row.get("sku") or "").strip()]
        if not filtered_rows:
            original_candidate_skus = [
                str(item or "").strip().upper()
                for item in (
                    (candidate_context or {}).get("original_candidate_skus")
                    or (candidate_context or {}).get("ordered_result_skus")
                    or (candidate_context or {}).get("candidate_skus")
                    or []
                )
                if str(item or "").strip()
            ]
            return _scoped_candidate_context_result(
                question,
                sku,
                [],
                (
                    f"\u5728\u4e0a\u4e00\u8f6e\u8fd9\u4e9b\u5019\u9009\u91cc\uff0c\u6ca1\u6709\u627e\u5230\u660e\u786e\u9002\u5408 {target_people} \u4e2a\u4eba\u4f7f\u7528\u7684\u4ea7\u54c1\u8d44\u6599\u3002"
                    "\u6211\u4e0d\u4f1a\u56de\u5230\u5168\u5e93\u91cd\u65b0\u63a8\u8350\uff1b\u4f60\u53ef\u4ee5\u653e\u5bbd\u4eba\u6570\u6761\u4ef6\u6216\u91cd\u65b0\u7ed9\u4e00\u4e2a\u4ea7\u54c1\u8303\u56f4\u3002"
                ),
                {
                    **(candidate_context or {}),
                    "candidate_skus": original_candidate_skus,
                    "original_candidate_skus": original_candidate_skus,
                    "parent_candidate_skus": original_candidate_skus,
                    "ordered_result_skus": [],
                    "filtered_skus": [],
                    "empty_subset": True,
                    "applied_filter": {"type": "people", "people": target_people},
                    "user_question": question,
                },
                conversation_history=conversation_history,
            )
        answer = _compose_scoped_people_filter_answer(target_people, filtered_rows)
        return _scoped_candidate_context_result(
            question,
            sku,
            filtered_rows,
            answer,
            {
                **(candidate_context or {}),
                "candidate_skus": filtered_skus,
                "ordered_result_skus": filtered_skus,
                "filtered_skus": filtered_skus,
                "empty_subset": False,
                "user_question": question,
            },
            conversation_history=conversation_history,
        )
    if _looks_like_scoped_lightest_followup(question):
        details_result = await customer_agent_tool_service.execute_tool_async(
            db,
            user_id=user_id,
            name="get_product_detail",
            arguments={"skus": domain_skus, "fields": ["specs.gross_weight_g"]},
        )
        detail_rows = _collect_results([details_result])
        detail_by_sku = {
            str(row.get("sku") or "").strip().upper(): row
            for row in detail_rows
            if isinstance(row, dict) and str(row.get("sku") or "").strip()
        }
        ordered_rows = [detail_by_sku[domain_sku] for domain_sku in domain_skus if domain_sku in detail_by_sku]
        weighted_rows = [(row, _detail_weight_g(row)) for row in ordered_rows]
        known_weight_rows = [(row, weight) for row, weight in weighted_rows if weight is not None]
        if not known_weight_rows:
            return _scoped_candidate_context_result(
                question,
                sku,
                ordered_rows,
                "当前候选里缺少明确重量数据，无法准确判断最轻的是哪个。",
                {
                    **(candidate_context or {}),
                    "candidate_skus": domain_skus,
                    "ordered_result_skus": domain_skus,
                    "user_question": question,
                },
                conversation_history=conversation_history,
                intent_override="compare_products",
            )
        lightest_row, lightest_weight = min(known_weight_rows, key=lambda item: item[1])
        lightest_sku = str(lightest_row.get("sku") or "").strip().upper()
        answer = _compose_scoped_lightest_answer(lightest_row, lightest_weight, ordered_rows)
        return _scoped_candidate_context_result(
            question,
            sku,
            [lightest_row, *[row for row in ordered_rows if str(row.get("sku") or "").strip().upper() != lightest_sku]],
            answer,
            {
                **(candidate_context or {}),
                "candidate_skus": domain_skus,
                "ordered_result_skus": domain_skus,
                "user_question": question,
            },
            conversation_history=conversation_history,
            intent_override="compare_products",
        )
    return None


def _scoped_candidate_context_result(
    question: str,
    sku: str | None,
    rows: list[dict],
    answer: str,
    candidate_context: dict[str, Any],
    *,
    conversation_history: list[dict] | None = None,
    intent_override: str = "query_products",
) -> dict:
    tool_result = {
        "ok": True,
        "tool": "get_product_detail",
        "count": len(rows),
        "details": rows,
        "results": rows,
        "sources": [],
    }
    result = _build_result(
        question,
        sku,
        [tool_result],
        answer,
        [{"type": "candidate_context_followup", "label": "候选域追问筛选", "ok": True}],
        conversation_history=conversation_history,
        intent_override=intent_override,
        preserve_llm_answer=True,
    )
    result["answer"] = answer
    result["needs_clarification"] = False
    meta = {
        "type": "agent_meta",
        "label": "候选域追问上下文",
        "intent": result.get("intent"),
        "answer_type": result.get("answer_type"),
        "candidate_context": {
            "candidate_skus": [
                str(item or "").strip().upper()
                for item in candidate_context.get("candidate_skus") or []
                if str(item or "").strip()
            ],
            "ordered_result_skus": [
                str(item or "").strip().upper()
                for item in (candidate_context.get("ordered_result_skus") if "ordered_result_skus" in candidate_context else candidate_context.get("candidate_skus") or [])
                if str(item or "").strip()
            ],
            "filtered_skus": [
                str(item or "").strip().upper()
                for item in candidate_context.get("filtered_skus") or []
                if str(item or "").strip()
            ],
            "original_candidate_skus": [
                str(item or "").strip().upper()
                for item in candidate_context.get("original_candidate_skus") or []
                if str(item or "").strip()
            ],
            "parent_candidate_skus": [
                str(item or "").strip().upper()
                for item in (
                    candidate_context.get("parent_candidate_skus")
                    or candidate_context.get("original_candidate_skus")
                    or []
                )
                if str(item or "").strip()
            ],
            "recommended_skus": [
                str(item or "").strip().upper()
                for item in candidate_context.get("recommended_skus") or []
                if str(item or "").strip()
            ],
            "user_question": str(candidate_context.get("user_question") or question or "").strip(),
            "product_scope": str(candidate_context.get("product_scope") or "").strip(),
            "empty_subset": bool(candidate_context.get("empty_subset")),
            "applied_filter": candidate_context.get("applied_filter") if isinstance(candidate_context.get("applied_filter"), dict) else None,
        },
    }
    result["sources"] = [*(result.get("sources") or []), meta]
    debug = dict(result.get("debug") or {})
    debug["agent_mode"] = "candidate_context_followup"
    result["debug"] = debug
    return result


def _looks_like_scoped_people_filter_followup(question: str) -> bool:
    text = str(question or "")
    if any(term in text for term in ("\u54ea\u4e2a", "\u54ea\u4e00\u4e2a", "\u54ea\u6b3e", "\u54ea\u4e00\u6b3e", "\u66f4\u9002\u5408", "\u66f4\u63a8\u8350")):
        return False
    if not any(term in text for term in ("\u6709\u54ea\u4e9b", "\u54ea\u4e9b", "\u54ea\u51e0\u6b3e", "\u5217\u51fa")):
        return False
    return (
        _is_candidate_scope_followup(text)
        and _people_count_from_question(text) is not None
        and any(term in text for term in ("适合", "用", "人"))
    )


def _looks_like_scoped_lightest_followup(question: str) -> bool:
    text = str(question or "")
    return (
        any(term in text for term in ("最轻", "哪个最轻", "哪款最轻"))
        and not any(term in text for term in ("第一个", "第二个", "第三个"))
    )


def _people_count_from_question(question: str) -> int | None:
    text = str(question or "")
    match = re.search(r"(\d+)\s*(?:个)?人", text)
    if match:
        return int(match.group(1))
    mapping = {
        "一人": 1,
        "一个人": 1,
        "单人": 1,
        "两人": 2,
        "两个人": 2,
        "二人": 2,
        "二个人": 2,
        "双人": 2,
        "三人": 3,
        "三个人": 3,
        "四人": 4,
        "四个人": 4,
        "五人": 5,
        "五个人": 5,
    }
    for term, value in mapping.items():
        if term in text:
            return value
    return None


def _row_matches_people_count(row: dict, people_count: int) -> bool:
    haystack = _row_text(row)
    if people_count == 1 and any(term in haystack for term in ("单人", "1人", "1 人", "一人", "一个人", "1-2人", "1－2人")):
        return True
    if people_count == 2 and any(term in haystack for term in ("双人", "两人", "两个人", "2人", "2 人", "二人", "1-2人", "1－2人", "2-3人", "2－3人")):
        return True
    if people_count == 3 and any(term in haystack for term in ("三人", "3人", "3 人", "三个人", "2-3人", "2－3人", "3-4人", "3－4人")):
        return True
    if people_count == 4 and any(term in haystack for term in ("四人", "4人", "4 人", "四个人", "3-4人", "3－4人", "2-4人", "2－4人")):
        return True
    if people_count == 5 and any(term in haystack for term in ("五人", "5人", "5 人", "五个人", "4-5人", "4－5人", "5-6人", "5－6人")):
        return True
    return False


def _compose_scoped_people_filter_answer(people_count: int, rows: list[dict]) -> str:
    lines = [f"上一轮候选里，明确更适合 {people_count} 人使用的有："]
    for row in rows[:5]:
        sku = str(row.get("sku") or "").strip().upper()
        name = str(row.get("product_name_cn") or row.get("product_name_en") or sku).strip()
        scenes = str(row.get("usage_scenarios") or row.get("target_audience") or row.get("features") or "").strip()
        suffix = f"：{scenes}" if scenes else ""
        lines.append(f"- {sku} {name}{suffix}")
    return "\n".join(lines)


def _compose_scoped_lightest_answer(lightest_row: dict, lightest_weight: float, rows: list[dict]) -> str:
    sku = str(lightest_row.get("sku") or "").strip().upper()
    name = str(lightest_row.get("product_name_cn") or lightest_row.get("product_name_en") or sku).strip()
    lines = [f"在上一轮筛选结果里，当前资料显示最轻的是 {sku} {name}，重量约 {int(lightest_weight)}g。"]
    missing_weight = [
        str(row.get("sku") or "").strip().upper()
        for row in rows
        if _detail_weight_g(row) is None and str(row.get("sku") or "").strip()
    ]
    if missing_weight:
        lines.append(f"另外，{', '.join(missing_weight)} 缺少明确重量数据，所以这个结论只基于已有重量字段。")
    return "\n".join(lines)


def _refine_followup_candidate_skus_for_scope(
    db: Session,
    skus: list[str],
    product_scope: str,
    user_question: str,
) -> list[str]:
    normalized_skus = [
        str(sku or "").strip().upper()
        for sku in skus
        if str(sku or "").strip()
    ]
    if not normalized_skus or not _is_pot_cookware_scope(product_scope, user_question):
        return normalized_skus
    products = (
        db.query(Product)
        .filter(Product.sku.in_(normalized_skus))
        .all()
    )
    product_by_sku = {str(product.sku or "").strip().upper(): product for product in products}
    if _looks_like_cookset_scope(product_scope, user_question):
        cookset_refined = [
            sku
            for sku in normalized_skus
            if _looks_like_cookset_product(product_by_sku.get(sku))
        ]
        if cookset_refined:
            return cookset_refined
    refined = [
        sku
        for sku in normalized_skus
        if _is_pot_cookware_product(product_by_sku.get(sku))
    ]
    return refined or normalized_skus


def _looks_like_cookset_scope(product_scope: str, user_question: str) -> bool:
    scope_text = str(product_scope or "")
    question_text = str(user_question or "")
    cookset_terms = ("套锅", "锅具套装", "炊具套装", "套装锅")
    return any(term in scope_text or term in question_text for term in cookset_terms)


def _is_pot_cookware_scope(product_scope: str, user_question: str) -> bool:
    scope_text = str(product_scope or "")
    question_text = str(user_question or "")
    if any(term in question_text for term in ("水壶", "茶壶", "烧水壶", "壶类")):
        return False
    return any(term in scope_text or term in question_text for term in ("锅具", "锅", "套锅", "炒锅", "煎锅", "单锅"))


def _is_pot_cookware_product(product: Product | None) -> bool:
    if product is None:
        return True
    name_text = " ".join(
        str(value or "")
        for value in (
            product.product_name_cn,
            product.product_name_en,
            product.sub_category,
        )
    )
    cookware_terms = ("套锅", "炒锅", "煎锅", "单锅", "汤锅", "锅具", "锅", "煎盘", "烤盘")
    if any(term in name_text for term in cookware_terms):
        return True
    kettle_terms = ("水壶", "茶壶", "烧水壶", "壶")
    if any(term in name_text for term in kettle_terms):
        return False
    return True


def _looks_like_cookset_product(product: Product | None) -> bool:
    if product is None:
        return False
    text = " ".join(
        str(value or "")
        for value in (
            product.product_name_cn,
            product.product_name_en,
            product.sub_category,
            product.category,
        )
    )
    cookset_terms = ("套锅", "锅具套装", "炊具套装", "套装锅", "野营锅", "野餐锅", "件套")
    return any(term in text for term in cookset_terms)


def _safe_json_loads(value: str | None, fallback: Any) -> Any:
    if not value:
        return fallback
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return fallback


def _parse_json_object(content: str) -> dict | None:
    text = (content or "").strip()
    if not text:
        return None
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", text, flags=re.S)
        if not match:
            return None
        try:
            data = json.loads(match.group(0))
        except json.JSONDecodeError:
            return None
    return data if isinstance(data, dict) else None


def _collect_actions(tool_results: list[dict]) -> list[dict]:
    actions = []
    for result in tool_results:
        action = result.get("action") if isinstance(result, dict) else None
        if action:
            actions.append(action)
        for item in result.get("actions") or []:
            actions.append(item)
    return actions


def _collect_results(tool_results: list[dict]) -> list[dict]:
    rows = []
    for result in tool_results:
        if not isinstance(result, dict):
            continue
        if result.get("tool") in {"search_products", "hybrid_search_products", "recommend_products"}:
            rows.extend(result.get("results") or [])
        elif result.get("tool") == "get_product_detail" and result.get("detail"):
            rows.append(result["detail"])
        elif result.get("tool") == "get_product_detail" and result.get("details"):
            rows.extend(result.get("details") or [])
        elif result.get("tool") == "semantic_search_knowledge":
            rows.extend(result.get("results") or [])
    return rows


def _group_retrieved_products_by_sku(retrieved_products: list[dict]) -> list[dict]:
    grouped: list[dict] = []
    by_key: dict[str, dict] = {}
    for raw in retrieved_products:
        if not isinstance(raw, dict):
            continue
        key = _retrieved_product_group_key(raw)
        if not key:
            grouped.append(dict(raw))
            continue
        existing = by_key.get(key)
        if existing is None:
            existing = dict(raw)
            existing["sku"] = str(existing.get("sku") or existing.get("product_id") or "").strip().upper() or existing.get("sku")
            existing["evidence_sections"] = []
            existing["matched_sections"] = []
            existing["knowledge_matches"] = list(existing.get("knowledge_matches") or [])
            by_key[key] = existing
            grouped.append(existing)
        _merge_retrieved_product_group(existing, raw)
    return grouped


def _retrieved_product_group_key(product: dict[str, Any]) -> str:
    product_id = str(product.get("product_id") or product.get("id") or "").strip()
    if product_id:
        return f"product_id:{product_id}"
    sku = str(product.get("sku") or "").strip().upper()
    if sku:
        return f"sku:{sku}"
    return ""


def _merge_retrieved_product_group(target: dict[str, Any], source: dict[str, Any]) -> None:
    for key, value in source.items():
        if key in {"evidence_sections", "matched_sections", "knowledge_matches"}:
            continue
        if target.get(key) in (None, "", [], {}) and value not in (None, "", [], {}):
            target[key] = value

    source_sections = _extract_evidence_sections(source)
    if source_sections:
        seen = {
            (
                str(item.get("section") or ""),
                str(item.get("source_id") or ""),
                str(item.get("content") or "")[:500],
            )
            for item in target.get("evidence_sections") or []
            if isinstance(item, dict)
        }
        for item in source_sections:
            key = (
                str(item.get("section") or ""),
                str(item.get("source_id") or ""),
                str(item.get("content") or "")[:500],
            )
            if key in seen:
                continue
            seen.add(key)
            target.setdefault("evidence_sections", []).append(item)

    matched_sections = _extract_matched_sections(source)
    if matched_sections:
        existing = list(target.get("matched_sections") or [])
        for section in matched_sections:
            if section not in existing:
                existing.append(section)
        target["matched_sections"] = existing

    source_knowledge_matches = source.get("knowledge_matches")
    if isinstance(source_knowledge_matches, list) and source_knowledge_matches:
        existing_matches = list(target.get("knowledge_matches") or [])
        existing_keys = {
            (
                str(item.get("sku") or ""),
                str(item.get("metadata", {}).get("source_id") if isinstance(item.get("metadata"), dict) else ""),
                str(item.get("content") or "")[:500],
            )
            for item in existing_matches
            if isinstance(item, dict)
        }
        for match in source_knowledge_matches:
            if not isinstance(match, dict):
                continue
            key = (
                str(match.get("sku") or ""),
                str(match.get("metadata", {}).get("source_id") if isinstance(match.get("metadata"), dict) else ""),
                str(match.get("content") or "")[:500],
            )
            if key in existing_keys:
                continue
            existing_keys.add(key)
            existing_matches.append(match)
        target["knowledge_matches"] = existing_matches


def _extract_evidence_sections(product: dict[str, Any]) -> list[dict[str, Any]]:
    sections: list[dict[str, Any]] = []
    metadata = product.get("metadata") if isinstance(product.get("metadata"), dict) else {}
    if isinstance(product.get("content"), str) and product.get("content"):
        section_name = str(
            metadata.get("section")
            or metadata.get("title")
            or product.get("section")
            or product.get("source_type")
            or "content"
        ).strip()
        sections.append({
            "section": section_name,
            "source_type": str(product.get("source_type") or metadata.get("source_type") or "").strip(),
            "source_id": str(metadata.get("source_id") or product.get("source_id") or "").strip(),
            "title": str(metadata.get("title") or product.get("title") or "").strip(),
            "content": str(product.get("content") or "").strip(),
            "score": product.get("score"),
        })
    if isinstance(product.get("content"), dict):
        content = product.get("content") or {}
        for key in ("title_cn", "title_en"):
            value = content.get(key)
            if value not in (None, "", [], {}):
                sections.append({
                    "section": key,
                    "source_type": str(product.get("source_type") or metadata.get("source_type") or "").strip(),
                    "source_id": str(metadata.get("source_id") or product.get("source_id") or "").strip(),
                    "title": str(metadata.get("title") or product.get("title") or "").strip(),
                    "content": str(value).strip(),
                    "score": product.get("score"),
                })
    return sections


def _extract_matched_sections(product: dict[str, Any]) -> list[str]:
    sections: list[str] = []
    metadata = product.get("metadata") if isinstance(product.get("metadata"), dict) else {}
    for value in (
        metadata.get("section"),
        product.get("section"),
    ):
        text = str(value or "").strip()
        if text and text not in sections:
            sections.append(text)
    if not sections:
        for value in (
            metadata.get("source_type"),
            product.get("source_type"),
            metadata.get("title"),
        ):
            text = str(value or "").strip()
            if text and text not in sections:
                sections.append(text)
    return sections


def _merge_results_for_display(question: str, results: list[dict]) -> list[dict]:
    merged: list[dict] = []
    by_sku: dict[str, dict] = {}
    knowledge_by_sku: dict[str, list[dict]] = {}

    for raw in results:
        if not isinstance(raw, dict):
            continue
        sku = str(raw.get("sku") or "").strip().upper()
        is_knowledge = bool(raw.get("source_type") and raw.get("content"))
        if not sku:
            merged.append(dict(raw))
            continue
        if is_knowledge:
            knowledge_by_sku.setdefault(sku, []).append(dict(raw))
            continue
        if sku not in by_sku:
            item = dict(raw)
            item["sku"] = sku
            by_sku[sku] = item
            merged.append(item)
        else:
            existing = by_sku[sku]
            for key, value in raw.items():
                if existing.get(key) in (None, "", [], {}) and value not in (None, "", [], {}):
                    existing[key] = value

    for sku, knowledge_rows in knowledge_by_sku.items():
        item = by_sku.get(sku)
        if item is None:
            item = {"sku": sku}
            by_sku[sku] = item
            merged.append(item)
        item["knowledge_matches"] = _dedupe_knowledge_matches(knowledge_rows)

    requested_fields = _requested_display_fields(question)
    if requested_fields:
        for item in merged:
            if not item.get("sku"):
                continue
            field_values: dict[str, Any] = dict(item.get("field_values") or {})
            for label, field_path in requested_fields:
                if field_values.get(label) not in (None, "", "暂无"):
                    continue
                value = _display_field_value(item, field_path)
                field_values[label] = customer_agent_service._stringify(value) if value not in (None, "", []) else "暂无"
            if field_values:
                item["field_values"] = field_values
    return merged


def _requested_display_fields(question: str) -> list[tuple[str, str]]:
    fields: list[tuple[str, str]] = []
    if _looks_like_load_capacity_question(question):
        fields.append(("最大承重", "virtual.load_capacity"))
    intent = customer_agent_intent_service.parse_intent(question, previous_result_skus=[])
    for raw_label in (getattr(intent, "requested_fields", None) or []):
        label = str(raw_label or "").strip()
        field_path = customer_agent_intent_service._resolve_query_field(label)
        if label == "认证":
            field_path = "certifications"
        if field_path and (label, field_path) not in fields:
            fields.append((label, field_path))
    for field_path in customer_agent_tool_service.query_fields_from_text(question):
        label = customer_agent_tool_service._label_for_query_field(field_path)
        if not any(existing_path == field_path for _, existing_path in fields):
            fields.append((label, field_path))
    return fields


def _display_field_value(item: dict, field_path: str) -> Any:
    if field_path == "virtual.load_capacity":
        return None
    if field_path == "certifications":
        return [
            row.get("certification_name") or row.get("name") or row.get("certification_code")
            for row in item.get("certifications") or []
            if isinstance(row, dict)
        ]
    return customer_agent_tool_service._value_from_detail(item, field_path)


def _looks_like_load_capacity_question(question: str) -> bool:
    text = str(question or "")
    return any(term in text for term in ("最大承重", "承重能力", "能承重", "能承受多重", "承载多少", "承重量", "负重"))


def _dedupe_knowledge_matches(rows: list[dict]) -> list[dict]:
    matches: list[dict] = []
    seen: set[tuple[str, str]] = set()
    for row in rows:
        metadata = row.get("metadata") if isinstance(row.get("metadata"), dict) else {}
        stable_id = str(metadata.get("source_id") or metadata.get("chunk_id") or "")
        content = " ".join(str(row.get("content") or "").split())
        key = (stable_id, content[:500])
        if key in seen:
            continue
        seen.add(key)
        matches.append(row)
    return matches


def _warnings_from_tool_results(tool_results: list[dict], *, direct_answer: bool) -> list[str]:
    warnings = []
    if direct_answer:
        warnings.append("模型未调用工具直接回答")
    for result in tool_results:
        if not isinstance(result, dict):
            continue
        if result.get("ok") is False:
            warnings.append(str(result.get("error") or "工具调用失败"))
    return warnings


def _clean_customer_answer(answer: str) -> str:
    text = str(answer or "").strip()
    if not text:
        return ""
    text = re.sub(r"<br\s*/?>", "\n", text, flags=re.I)
    text = re.sub(r"<[^>]+>", "", text)
    text = re.sub(r"\*\*(.*?)\*\*", r"\1", text)
    text = re.sub(r"^#{1,6}\s*", "", text, flags=re.M)
    text = re.sub(r"`([^`]+)`", r"\1", text)
    return text.strip()


def _anomalies_from_tool_results(tool_results: list[dict]) -> list[dict]:
    anomalies = []
    for result in tool_results:
        if isinstance(result, dict) and result.get("ok") is False:
            anomalies.append({"type": "tool_error", "message": str(result.get("error") or ""), "tool": result.get("tool")})
    return anomalies


def _needs_clarification(answer: str | None, results: list[dict], warnings: list[str]) -> bool:
    text = answer or ""
    if any(item in text for item in ("请先", "需要先", "请告诉我", "需要明确", "范围")) and not results:
        return True
    return False


def _infer_intent(question: str, tool_results: list[dict], actions: list[dict], results: list[dict], needs_clarification: bool) -> str:
    if needs_clarification:
        return "clarify"
    tool_names = {_tool_name(item) for item in tool_results}
    if "propose_delete_product" in tool_names or "propose_delete_product_info" in tool_names:
        return "propose_delete"
    if actions or any(name.startswith(WRITE_TOOL_PREFIXES) for name in tool_names):
        return "propose_update"
    if any(word in question for word in ("对比", "比较", "区别", "差异")):
        return "compare_products"
    result_skus = [
        str(item.get("sku") or "").strip().upper()
        for item in results
        if isinstance(item, dict) and str(item.get("sku") or "").strip()
    ]
    if _is_compare_like_question(question, context_skus=result_skus):
        return "compare_products"
    if _is_single_product_fact_followup(question, results):
        return "product_detail"
    if _is_recommendation_question(question) or any(word in question for word in (
        "推荐", "适合", "哪个好", "哪款", "送礼", "年轻人", "场景",
        "还有别的", "还有其他", "换个", "换一个", "换一款", "再推荐",
        "带什么", "有没有中端", "中端一点", "预算不高",
    )):
        return "recommend_products"
    if "get_product_detail" in tool_names:
        return "product_detail"
    if results or any(name in {"search_products", "hybrid_search_products", "semantic_search_knowledge"} for name in tool_names):
        return "query_products"
    return "chat"


def _is_recommendation_question(question: str) -> bool:
    text = str(question or "")
    return (
        _looks_like_recommendation_text(text)
        or customer_price_signal.price_preference(text) in {"low", "high", "value"}
        or any(term in text for term in ("想买", "买一个", "买一款", "选一个", "选一款", "帮我挑", "有没有适合"))
    )


def _is_single_product_fact_followup(question: str, results: list[dict]) -> bool:
    if _looks_like_multi_product_fact_question(question):
        return False
    skus = {
        str(item.get("sku") or "")
        for item in results
        if isinstance(item, dict) and item.get("sku")
    }
    if len(skus) != 1:
        return False
    text = str(question or "")
    return any(term in text for term in (
        "容量", "材质", "卖点", "负责人", "英文名", "适合几个人", "几个人用",
        "能不能", "还能", "可以", "支持", "防水", "煎炒煮",
    ))


def _tool_name(result: dict) -> str:
    return str(result.get("tool") or "")


def _answer_type_from_intent(intent: str) -> str:
    return {
        "query_products": "product_query",
        "product_detail": "product_detail",
        "compare_products": "comparison",
        "recommend_products": "recommendation",
        "propose_update": "action_proposal",
        "propose_delete": "action_proposal",
        "clarify": "clarification",
        "chat": "chat",
    }.get(intent, "unknown")


def _confidence(results: list[dict], warnings: list[str], needs_clarification: bool, direct_answer: bool) -> str:
    if needs_clarification or direct_answer:
        return "low"
    if warnings or not results:
        return "medium"
    return "high"


def _confidence_adjusted_by_quality(confidence: str, quality: dict) -> str:
    level = str((quality or {}).get("level") or "")
    passed = bool((quality or {}).get("passed"))
    if level == "low":
        return "low"
    if not passed and confidence == "high":
        return "medium"
    return confidence


def _uncertainty(answer: str, results: list[dict], warnings: list[str], needs_clarification: bool) -> str:
    if needs_clarification:
        return "ambiguous_product"
    if any(item in answer for item in ("没有标注", "资料未标注", "不能确认", "需要人工确认")):
        return "not_recorded"
    if warnings or (not results and any(item in answer for item in ("没有找到", "无法", "不能可靠"))):
        return "insufficient_data"
    return "confirmed"


def _uncertainty_adjusted_by_quality(uncertainty: str, quality: dict) -> str:
    risks = (quality.get("risks") or []) if isinstance(quality, dict) else []
    if any(
        risk.startswith("answer_mentions_unreturned_sku:")
        or risk in {"missing_product_results", "tool_required_but_not_used", "tool_call_failed"}
        for risk in risks
    ):
        return "insufficient_data"
    if any(risk in {"context_reference_not_resolved"} for risk in risks):
        return "ambiguous_product"
    return uncertainty


def _suggested_followups(question: str, results: list[dict], needs_clarification: bool) -> list[str]:
    if needs_clarification:
        return ["请给我 SKU、类目、负责人，或先让我查一批产品。"]
    if len(results) > 10:
        return ["可以继续按负责人、类目、容量、材质或使用场景缩小范围。"]
    if any(word in question for word in ("推荐", "适合", "送礼")):
        return ["也可以告诉我预算、人数和使用场景，我再帮你缩小推荐。"]
    return []


def _evidence_from_results(results: list[dict]) -> list[dict]:
    evidence = []
    for item in results[:8]:
        if not isinstance(item, dict):
            continue
        field_values = item.get("field_values") if isinstance(item.get("field_values"), dict) else {}
        knowledge_matches = item.get("knowledge_matches") if isinstance(item.get("knowledge_matches"), list) else []
        if not field_values and knowledge_matches:
            for match in knowledge_matches[:3]:
                if not isinstance(match, dict):
                    continue
                content = str(match.get("content") or "").strip()
                if not content:
                    continue
                evidence.append({
                    "sku": item.get("sku") or match.get("sku"),
                    "product_name": item.get("product_name_cn") or item.get("product_name_en"),
                    "field_label": "QA知识库",
                    "value": content,
                    "source_layer": "L5",
                    "matched_by": match.get("matched_by") or "知识库",
                })
            if evidence:
                continue
        if field_values:
            for label, value in field_values.items():
                evidence.append({
                    "sku": item.get("sku"),
                    "product_name": item.get("product_name_cn") or item.get("product_name_en"),
                    "field_label": label,
                    "value": value,
                    "source_layer": _layer_for_field_label(str(label)),
                    "matched_by": item.get("matched_by") or "产品资料",
                })
            continue
        for label, key in (("容量", "capacity"), ("材质", "body_material"), ("颜色", "color"), ("负责人", "person_in_charge"), ("类目", "category"), ("卖点", "features")):
            value = item.get(key)
            if value not in (None, ""):
                evidence.append({
                    "sku": item.get("sku"),
                    "product_name": item.get("product_name_cn") or item.get("product_name_en"),
                    "field_label": label,
                    "value": str(value),
                    "source_layer": _layer_for_field_label(label),
                    "matched_by": item.get("matched_by") or "产品资料",
                })
    return evidence


def _layer_for_field_label(label: str) -> str:
    if any(item in label for item in ("容量", "重量", "材质", "颜色", "热源", "功率", "表面")):
        return "L2"
    if any(item in label for item in ("卖点", "场景", "定位", "人群", "竞品")):
        return "L3"
    if any(item in label for item in ("标题", "描述", "关键词", "listing", "Listing")):
        return "L4"
    return "L1"


def _sources_from_tool_results(tool_results: list[dict], *, direct_answer: bool = False) -> list[dict]:
    if direct_answer:
        return [{"type": "agent_model", "label": "AI直接回答"}]
    sources: list[dict] = []
    product_sources: dict[str, dict] = {}

    def product_source(sku: Any) -> dict | None:
        normalized = str(sku or "").strip().upper()
        if not normalized:
            return None
        if normalized not in product_sources:
            source = {"type": "product", "label": "AI工具读取详情", "sku": normalized}
            product_sources[normalized] = source
            sources.append(source)
        return product_sources[normalized]

    for result in tool_results:
        if not isinstance(result, dict):
            continue
        if result.get("tool") in {"search_products", "hybrid_search_products"}:
            sources.append({"type": "product_search", "label": "AI工具查询", "query": result.get("query"), "count": result.get("count", 0)})
        elif result.get("tool") == "get_product_detail":
            details = [result.get("detail"), *(result.get("details") or [])]
            skus = [result.get("sku"), *(item.get("sku") for item in details if isinstance(item, dict))]
            for sku in skus:
                product_source(sku)
        elif result.get("tool") == "semantic_search_knowledge":
            counts: dict[str, int] = {}
            for row in result.get("results") or []:
                if not isinstance(row, dict):
                    continue
                sku = str(row.get("sku") or "").strip().upper()
                if sku:
                    counts[sku] = counts.get(sku, 0) + 1
            if counts:
                for sku, count in counts.items():
                    source = product_source(sku)
                    if source is not None:
                        source["label"] = "AI工具读取详情与知识检索"
                        source["knowledge_count"] = source.get("knowledge_count", 0) + count
            else:
                sources.append({"type": "knowledge_search", "label": "AI语义知识检索", "query": result.get("query"), "count": result.get("count", 0)})
        elif result.get("action"):
            sources.append({"type": "agent_action", "label": "AI工具生成待确认动作", "count": 1})
        elif result.get("actions"):
            sources.append({"type": "agent_action", "label": "AI工具生成待确认动作", "count": len(result.get("actions") or [])})
    return sources


def _single_sku(results: list[dict], actions: list[dict]) -> str | None:
    skus = {item.get("sku") for item in results + actions if item.get("sku")}
    return next(iter(skus)) if len(skus) == 1 else None


def _single_product_detail_sku(sku: str | None, results: list[dict]) -> str | None:
    if sku:
        return str(sku).strip().upper() or None
    skus = {str(item.get("sku") or "").strip().upper() for item in results if isinstance(item, dict) and item.get("sku")}
    skus.discard("")
    return next(iter(skus)) if len(skus) == 1 else None


def _merge_knowledge_rows(*groups: list[dict] | None) -> list[dict]:
    merged: list[dict] = []
    seen: set[tuple[str, str, str]] = set()
    for rows in groups:
        for row in rows or []:
            if not isinstance(row, dict):
                continue
            key = (
                str(row.get("source_type") or ""),
                str(row.get("sku") or ""),
                str(row.get("content") or "")[:300],
            )
            if key in seen:
                continue
            seen.add(key)
            merged.append(row)
            if len(merged) >= 5:
                return merged
    return merged


def _keyword_knowledge_rows_for_sku(db: Session, query: str, sku: str, limit: int = 3) -> list[dict]:
    query_text = str(query or "").strip()
    sku_text = str(sku or "").strip().upper()
    if not query_text or not sku_text:
        return []
    chunks = (
        db.query(KnowledgeChunk)
        .filter(
            KnowledgeChunk.sku == sku_text,
            KnowledgeChunk.embedding_status == "synced",
        )
        .all()
    )
    scored: list[tuple[float, KnowledgeChunk]] = []
    for chunk in chunks:
        score = _knowledge_keyword_score(query_text, chunk.content or "")
        if score > 0:
            scored.append((score, chunk))
    scored.sort(key=lambda item: (item[0], item[1].updated_at), reverse=True)
    rows: list[dict] = []
    for score, chunk in scored[: max(1, limit)]:
        rows.append(
            {
                "source_type": chunk.source_type,
                "sku": chunk.sku,
                "content": chunk.content,
                "metadata": _safe_json_loads(chunk.metadata_json, {}),
                "score": score,
            }
        )
    return rows


def _knowledge_keyword_score(query: str, content: str) -> float:
    normalized_query = re.sub(r"\s+", "", str(query or ""))
    for phrase in ("旋焰酒精炉", "酒精炉"):
        normalized_query = normalized_query.replace(phrase, "")
    normalized_content = str(content or "")
    if not normalized_query or not normalized_content:
        return 0.0
    ignored = set("的了吗呢啊呀和是有用可不个这那？?，,。；;：:（）() ")
    chars = [ch for ch in normalized_query if ch not in ignored]
    score = sum(1 for ch in chars if ch and ch in normalized_content)
    for size in (4, 3, 2):
        for index in range(0, max(len(normalized_query) - size + 1, 0)):
            token = normalized_query[index : index + size]
            if any(ch in ignored for ch in token):
                continue
            if token and token in normalized_content:
                score += size * size
    return float(score)


def _fallback_answer(tool_results: list[dict]) -> str:
    actions = _collect_actions(tool_results)
    if actions:
        return f"已生成 {len(actions)} 条待确认动作，请在确认卡中逐条确认或取消。"
    results = _collect_results(tool_results)
    if not results:
        return "没有找到匹配的产品资料。"
    display_results = _merge_results_for_display("", results)
    if not display_results:
        return "当前知识库现有资料不足以直接确认。"
    lines = []
    for item in display_results[:5]:
        if not isinstance(item, dict):
            continue
        name = item.get("product_name_cn") or item.get("product_name_en") or ""
        field_values = item.get("field_values") or {}
        suffix = "，" + "，".join(f"{key}：{value}" for key, value in field_values.items()) if field_values else ""
        lines.append(f"{item.get('sku')}，{name}{suffix}")
    if not lines:
        return "当前知识库现有资料不足以直接确认。"
    return "\n".join(["当前知识库已有相关资料，但不足以直接确认用户问题：", *lines])


def _has_field_values(results: list[dict]) -> bool:
    return any(isinstance(item.get("field_values"), dict) and item.get("field_values") for item in results if isinstance(item, dict))


def _ordinal_compare_targets_from_context(
    question: str,
    recommendation_context: dict[str, Any] | None,
    candidate_context: dict[str, Any] | None,
) -> list[str]:
    if not _looks_like_ordinal_compare_question(question):
        return []
    ordered_skus = [
        str(item or "").strip().upper()
        for item in (
            (recommendation_context or {}).get("ordered_result_skus")
            or (recommendation_context or {}).get("recommended_skus")
            or (candidate_context or {}).get("ordered_result_skus")
            or (candidate_context or {}).get("candidate_skus")
            or (candidate_context or {}).get("recommended_skus")
            or []
        )
        if str(item or "").strip()
    ]
    if len(ordered_skus) < 2:
        return []
    ordinal_indexes = _ordinal_indexes_from_question(question)
    if len(ordinal_indexes) < 2:
        return []
    resolved: list[str] = []
    for idx in ordinal_indexes[:2]:
        if idx < 0 or idx >= len(ordered_skus):
            return []
        sku = ordered_skus[idx]
        if sku not in resolved:
            resolved.append(sku)
    return resolved if len(resolved) == 2 else []


def _looks_like_ordinal_compare_question(question: str) -> bool:
    text = str(question or "")
    if not any(term in text for term in ("第一个", "第二个", "第三个", "第一款", "第二款", "第三款")):
        return False
    if not any(term in text for term in ("比", "更", "哪个")):
        return False
    if not any(term in text for term in ("轻", "重", "重量", "容量", "大", "小", "价格", "贵", "便宜")):
        return False
    if any(term in text for term in ("推荐理由", "为什么推荐", "理由是什么", "解释一下为什么")):
        return False
    return True


def _ordinal_indexes_from_question(question: str) -> list[int]:
    text = str(question or "")
    mapping = {
        "第一个": 0,
        "第一款": 0,
        "第二个": 1,
        "第二款": 1,
        "第三个": 2,
        "第三款": 2,
    }
    indexes: list[int] = []
    for token in ("第一个", "第一款", "第二个", "第二款", "第三个", "第三款"):
        if token in text:
            idx = mapping[token]
            if idx not in indexes:
                indexes.append(idx)
    return indexes


def _ordinal_compare_detail_fields(question: str) -> list[str]:
    text = str(question or "")
    if any(term in text for term in ("轻", "重", "重量")):
        return ["specs.gross_weight_g", "specs.capacity", "business.price_positioning", "business.positioning"]
    if any(term in text for term in ("容量", "大", "小")):
        return ["specs.capacity", "specs.gross_weight_g", "business.positioning"]
    if any(term in text for term in ("价格", "贵", "便宜")):
        return ["business.price_positioning", "business.positioning", "specs.capacity", "specs.gross_weight_g"]
    return ["specs.gross_weight_g", "specs.capacity", "business.price_positioning", "business.positioning"]


def _compose_deterministic_ordinal_compare_answer(question: str, results: list[dict]) -> str:
    rows = [item for item in results if isinstance(item, dict)]
    if len(rows) < 2:
        return "前面推荐结果不足，暂时无法完成这两个产品的比较。"
    left, right = rows[:2]
    left_sku = str(left.get("sku") or "").strip().upper()
    right_sku = str(right.get("sku") or "").strip().upper()
    left_name = str(left.get("product_name_cn") or left.get("product_name_en") or left_sku).strip()
    right_name = str(right.get("product_name_cn") or right.get("product_name_en") or right_sku).strip()
    left_label = f"第一个（{left_sku}）"
    right_label = f"第二个（{right_sku}）"
    text = str(question or "")
    if any(term in text for term in ("轻", "重", "重量")):
        left_weight = _detail_weight_g(left)
        right_weight = _detail_weight_g(right)
        if left_weight is None or right_weight is None:
            return (
                f"{left_label}是{left_name}，{right_label}是{right_name}。"
                "当前资料缺少其中一个或两个产品的重量数据，无法准确判断谁更轻。"
            )
        if left_weight == right_weight:
            return (
                f"{left_label}是{left_name}，重量约{int(left_weight)}g；"
                f"{right_label}是{right_name}，重量约{int(right_weight)}g。"
                "按当前重量数据看，两者重量相同，暂时看不出谁更轻。"
            )
        if left_weight < right_weight:
            return (
                f"{left_label}是{left_name}，重量约{int(left_weight)}g；"
                f"{right_label}是{right_name}，重量约{int(right_weight)}g。"
                f"按当前重量数据看，第一个（{left_sku}）更轻。"
            )
        return (
            f"{left_label}是{left_name}，重量约{int(left_weight)}g；"
            f"{right_label}是{right_name}，重量约{int(right_weight)}g。"
            f"按当前重量数据看，第二个（{right_sku}）更轻。"
        )
    if any(term in text for term in ("容量", "大", "小")):
        left_capacity = _detail_capacity_text(left)
        right_capacity = _detail_capacity_text(right)
        if not left_capacity or not right_capacity:
            return (
                f"{left_label}是{left_name}，{right_label}是{right_name}。"
                "当前资料缺少其中一个或两个产品的容量数据，无法准确比较哪个更大。"
            )
        return (
            f"{left_label}是{left_name}，容量信息为{left_capacity}；"
            f"{right_label}是{right_name}，容量信息为{right_capacity}。"
            "当前资料里的容量多为组合描述，如果你要，我可以继续按大锅容量或整套容量帮你细比。"
        )
    if any(term in text for term in ("价格", "贵", "便宜")):
        left_price = _detail_price_positioning_text(left)
        right_price = _detail_price_positioning_text(right)
        if not left_price or not right_price:
            return (
                f"{left_label}是{left_name}，{right_label}是{right_name}。"
                "当前资料缺少其中一个或两个产品的价格或价格定位数据，无法准确比较谁更贵或更便宜。"
            )
        return (
            f"{left_label}是{left_name}，价格定位为{left_price}；"
            f"{right_label}是{right_name}，价格定位为{right_price}。"
            "当前只有价格定位信息，没有实时价格时，我不能进一步确认谁一定更贵或更便宜。"
        )
    return "前面两款产品我已经定位到了，但当前问题的比较维度还不够明确。"


def _compose_context_compare_answer(question: str, results: list[dict]) -> str:
    rows = [item for item in results if isinstance(item, dict)]
    if len(rows) < 2:
        return ""
    compare_kind = _compare_followup_kind(question)
    if not compare_kind:
        return ""
    left, right = rows[:2]
    left_sku = str(left.get("sku") or "").strip().upper()
    right_sku = str(right.get("sku") or "").strip().upper()
    if not left_sku or not right_sku:
        return ""
    left_name = str(left.get("product_name_cn") or left.get("product_name_en") or left_sku).strip()
    right_name = str(right.get("product_name_cn") or right.get("product_name_en") or right_sku).strip()
    left_label = f"第一个（{left_sku}）"
    right_label = f"第二个（{right_sku}）"
    if compare_kind == "weight":
        return _compose_weight_compare_answer(left_label, left_name, left, right_label, right_name, right)
    if compare_kind == "capacity":
        return _compose_capacity_compare_answer(left_label, left_name, left, right_label, right_name, right)
    if compare_kind == "price":
        return _compose_price_compare_answer(left_label, left_name, left, right_label, right_name, right)
    return ""


def _compare_followup_kind(question: str) -> str:
    text = str(question or "")
    if any(term in text for term in ("轻", "重", "重量")) and any(term in text for term in ("比", "更", "哪个")):
        return "weight"
    if any(term in text for term in ("容量", "大", "小")) and any(term in text for term in ("比", "更", "哪个")):
        return "capacity"
    if any(term in text for term in ("价格", "贵", "便宜")) and any(term in text for term in ("比", "更", "哪个")):
        return "price"
    return ""


def _compose_weight_compare_answer(
    left_label: str,
    left_name: str,
    left: dict,
    right_label: str,
    right_name: str,
    right: dict,
) -> str:
    left_weight = _detail_weight_g(left)
    right_weight = _detail_weight_g(right)
    if left_weight is None or right_weight is None:
        return (
            f"{left_label}是{left_name}，{right_label}是{right_name}。"
            "当前资料里缺少其中一个或两个产品的重量数据，无法准确判断谁更轻。"
        )
    if left_weight == right_weight:
        return (
            f"{left_label}是{left_name}，重量约 {int(left_weight)}g；"
            f"{right_label}是{right_name}，重量约 {int(right_weight)}g。"
            "当前可见重量数据相同，暂时看不出谁更轻。"
        )
    lighter_label, lighter_name, lighter_weight = (
        (left_label, left_name, left_weight) if left_weight < right_weight else (right_label, right_name, right_weight)
    )
    heavier_label, heavier_name, heavier_weight = (
        (right_label, right_name, right_weight) if left_weight < right_weight else (left_label, left_name, left_weight)
    )
    return (
        f"{left_label}是{left_name}，重量约 {int(left_weight)}g；"
        f"{right_label}是{right_name}，重量约 {int(right_weight)}g。"
        f"按当前重量数据看，{lighter_label}更轻；{heavier_label}更重。"
    )


def _compose_capacity_compare_answer(
    left_label: str,
    left_name: str,
    left: dict,
    right_label: str,
    right_name: str,
    right: dict,
) -> str:
    left_capacity = _detail_capacity_text(left)
    right_capacity = _detail_capacity_text(right)
    if not left_capacity or not right_capacity:
        return (
            f"{left_label}是{left_name}，{right_label}是{right_name}。"
            "当前资料里缺少其中一个或两个产品的容量数据，无法准确比较哪个更大。"
        )
    return (
        f"{left_label}是{left_name}，容量信息为 {left_capacity}；"
        f"{right_label}是{right_name}，容量信息为 {right_capacity}。"
        "当前资料里容量多为组合描述，我可以继续按你更关心的大锅容量或整套容量帮你细看。"
    )


def _compose_price_compare_answer(
    left_label: str,
    left_name: str,
    left: dict,
    right_label: str,
    right_name: str,
    right: dict,
) -> str:
    left_price = _detail_price_positioning_text(left)
    right_price = _detail_price_positioning_text(right)
    if not left_price or not right_price:
        return (
            f"{left_label}是{left_name}，{right_label}是{right_name}。"
            "当前资料里缺少其中一个或两个产品的价格或价格定位数据，无法准确比较谁更贵或更便宜。"
        )
    return (
        f"{left_label}是{left_name}，价格定位为 {left_price}；"
        f"{right_label}是{right_name}，价格定位为 {right_price}。"
        "当前只有价格定位信息，没有实时价格时，我不能进一步确认谁一定更贵或更便宜。"
    )


def _detail_weight_g(item: dict) -> float | None:
    specs = item.get("specs") if isinstance(item.get("specs"), dict) else {}
    value = (specs or {}).get("gross_weight_g")
    if value in (None, "", "暂无"):
        value = (item.get("field_values") or {}).get("重量")
    if value in (None, "", "暂无"):
        value = item.get("gross_weight_g")
    missing_literals = {None, "", "/", "-", "0", "0.0", 0, 0.0}
    if value in missing_literals:
        return None
    number = _extract_number(value)
    if number in (0, 0.0):
        return None
    return float(number) if number is not None else None


def _detail_capacity_text(item: dict) -> str:
    specs = item.get("specs") if isinstance(item.get("specs"), dict) else {}
    value = (specs or {}).get("capacity")
    if value in (None, "", "暂无"):
        value = (item.get("field_values") or {}).get("容量")
    if value in (None, "", "暂无"):
        value = item.get("capacity")
    return _format_capacity_value_for_compare(value)


def _detail_price_positioning_text(item: dict) -> str:
    business = item.get("business") if isinstance(item.get("business"), dict) else {}
    value = item.get("price_positioning") or (business or {}).get("price_positioning") or (item.get("field_values") or {}).get("价格定位")
    return str(value or "").strip()


def _format_capacity_value_for_compare(value: Any) -> str:
    if value in (None, "", "暂无"):
        return ""
    if isinstance(value, dict):
        label = str(value.get("label") or "").strip()
        raw_value = str(value.get("value") or "").strip()
        unit = str(value.get("unit") or "").strip()
        if raw_value:
            return f"{label}：{raw_value}{unit}" if label else f"{raw_value}{unit}"
        return label
    if isinstance(value, list):
        parts = [_format_capacity_value_for_compare(item) for item in value]
        return "，".join(part for part in parts if part)
    return str(value).strip()


def _extract_number(value: Any) -> float | None:
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value or "").strip()
    if not text:
        return None
    match = re.search(r"(\d+(?:\.\d+)?)", text)
    if not match:
        return None
    try:
        return float(match.group(1))
    except ValueError:
        return None


def _direct_heat_source_support_answer(question: str, tool_result: dict | None) -> str | None:
    question_text = str(question or "")
    if not any(term in question_text for term in ("酒精炉", "酒精")):
        return None
    if not any(term in question_text for term in ("能用", "可以用", "支持", "适合", "能不能", "是否支持")):
        return None
    rows = _collect_results([tool_result] if isinstance(tool_result, dict) else [])
    if len(rows) != 1 or not isinstance(rows[0], dict):
        return None
    item = rows[0]
    field_values = item.get("field_values") if isinstance(item.get("field_values"), dict) else {}
    heat_source = str(field_values.get("热源") or field_values.get("燃料") or "").strip()
    product_name = item.get("product_name_cn") or item.get("product_name_en") or ""
    prefix = f"{product_name}（{item.get('sku')}）" if product_name else str(item.get("sku") or "").strip()
    if heat_source and heat_source != "暂无":
        if "酒精炉" in heat_source or "酒精" in heat_source:
            return f"{prefix}：支持酒精炉。当前资料显示适用热源为{heat_source}。"
        return f"{prefix}：当前资料未显示支持酒精炉。当前资料显示适用热源为{heat_source}。"
    return f"{prefix}：当前资料暂未提供是否支持酒精炉。"


def _rewrite_heat_source_support_answer(question: str, results: list[dict]) -> str | None:
    question_text = str(question or "")
    if not any(term in question_text for term in ("酒精炉", "酒精")):
        return None
    if not any(term in question_text for term in ("能用", "可以用", "支持", "适合", "能不能", "是否支持")):
        return None
    if len(results) != 1 or not isinstance(results[0], dict):
        return None
    item = results[0]
    field_values = item.get("field_values") if isinstance(item.get("field_values"), dict) else {}
    heat_source = str(field_values.get("热源") or field_values.get("燃料") or "").strip()
    if not heat_source:
        heat_source = str(((item.get("specs") or {}).get("heat_source") or "")).strip()
    product_name = item.get("product_name_cn") or item.get("product_name_en") or ""
    prefix = f"{product_name}（{item.get('sku')}）" if product_name else str(item.get("sku") or "").strip()
    if heat_source and heat_source != "暂无":
        if "酒精炉" in heat_source or "酒精" in heat_source:
            return f"{prefix}：支持酒精炉。当前资料显示适用热源为{heat_source}。"
        return f"{prefix}：当前资料未显示支持酒精炉。当前资料显示适用热源为{heat_source}。"
    return f"{prefix}：当前资料暂未提供是否支持酒精炉。"


def _rewrite_heat_source_support_results(question: str, results: list[dict]) -> list[dict]:
    question_text = str(question or "")
    if not any(term in question_text for term in ("酒精炉", "酒精")):
        return results
    if not any(term in question_text for term in ("能用", "可以用", "支持", "适合", "能不能", "是否支持")):
        return results
    rewritten: list[dict] = []
    for item in results:
        if not isinstance(item, dict):
            rewritten.append(item)
            continue
        field_values = item.get("field_values") if isinstance(item.get("field_values"), dict) else {}
        heat_source = str(field_values.get("热源") or field_values.get("燃料") or "").strip()
        if not heat_source:
            rewritten.append(item)
            continue
        new_item = dict(item)
        new_fields = dict(field_values)
        if "酒精炉" in heat_source or "酒精" in heat_source:
            new_fields["是否支持酒精炉"] = f"支持酒精炉；适用热源：{heat_source}"
        else:
            new_fields["是否支持酒精炉"] = f"当前资料未显示支持酒精炉；适用热源：{heat_source}"
        new_fields.pop("热源", None)
        new_fields.pop("燃料", None)
        new_item["field_values"] = new_fields
        rewritten.append(new_item)
    return rewritten


def _enrich_load_capacity_results(question: str, results: list[dict]) -> list[dict]:
    if not _looks_like_load_capacity_question(question):
        return results
    enriched: list[dict] = []
    for item in results:
        if not isinstance(item, dict):
            enriched.append(item)
            continue
        row = dict(item)
        field_values = dict(row.get("field_values") or {})
        if not any(_is_load_capacity_label(str(label)) for label in field_values):
            field_values["最大承重"] = "暂无"
        row["field_values"] = field_values
        enriched.append(row)
    return enriched


def _compose_field_values_answer(question: str, results: list[dict]) -> str:
    question_text = str(question or "")
    if len(results) == 1 and any(term in question_text for term in ("酒精炉", "酒精")) and any(
        term in question_text for term in ("能用", "可以用", "支持", "适合", "能不能", "是否支持")
    ):
        item = results[0]
        if isinstance(item, dict):
            field_values = item.get("field_values") if isinstance(item.get("field_values"), dict) else {}
            heat_source = str(field_values.get("热源") or field_values.get("燃料") or "").strip()
            product_name = item.get("product_name_cn") or item.get("product_name_en") or ""
            prefix = f"{product_name}（{item.get('sku')}）" if product_name else str(item.get("sku") or "").strip()
            if heat_source and heat_source != "暂无":
                if "酒精炉" in heat_source or "酒精" in heat_source:
                    return f"{prefix}：支持酒精炉。当前资料显示适用热源为{heat_source}。"
                return f"{prefix}：当前资料未显示支持酒精炉。当前资料显示适用热源为{heat_source}。"
            return f"{prefix}：当前资料暂未提供是否支持酒精炉。"
    rows = []
    for item in results[:10]:
        if not isinstance(item, dict):
            continue
        field_values = item.get("field_values")
        if not isinstance(field_values, dict) or not field_values:
            continue
        product_name = item.get("product_name_cn") or item.get("product_name_en") or ""
        formatted_fields = []
        for key, value in field_values.items():
            key_text = str(key)
            value_text = str(value)
            if key_text in {"热源", "燃料"} and any(term in question_text for term in ("酒精炉", "酒精")) and any(
                term in question_text for term in ("能用", "可以用", "支持", "适合", "能不能", "是否支持")
            ):
                if "酒精炉" in value_text or "酒精" in value_text:
                    formatted_fields.append(f"支持酒精炉。当前资料显示适用热源为{value_text}")
                else:
                    formatted_fields.append(f"当前资料未显示支持酒精炉。当前资料显示适用热源为{value_text}")
                continue
            if _is_load_capacity_label(key_text) and _is_missing_field_value(value_text):
                load_capacity = _extract_load_capacity_from_item(item)
                if load_capacity:
                    formatted_fields.append(
                        f"{key}：当前结构化字段里未见独立承重字段（最大承重），但同 SKU 资料中写有“{load_capacity}”。建议以该资料为参考"
                    )
                    continue
            if key_text in {"材质", "主体材质"} and "、" in value_text and any(term in value_text for term in ("木", "白蜡木")):
                primary_material, handle_material = [part.strip() for part in value_text.split("、", 1)]
                if primary_material:
                    formatted_fields.append(f"主体材质：{primary_material}")
                if handle_material:
                    formatted_fields.append(f"手柄材质：{handle_material}（手柄{handle_material}）")
                continue
            if key_text == "手柄材质" and value_text and "手柄" not in value_text:
                formatted_fields.append(f"手柄材质：{value_text}（手柄{value_text}）")
                continue
            formatted_fields.append(f"{key}：{value}")
        fields = "，".join(formatted_fields)
        if (
            any(term in question_text for term in ("最开始", "第一个", "最后一个", "最后那个", "上一个"))
            and any(label in fields for label in ("主体材质", "手柄材质", "材质："))
        ):
            rows.append(f"{item.get('sku')}，{product_name}，其材质：{fields}")
        else:
            rows.append(f"{item.get('sku')}，{product_name}，{fields}")
    if not rows:
        return ""
    prefix = "查到以下资料："
    if any("暂无" in row for row in rows):
        prefix = "查到以下资料；标为“暂无”的字段表示产品库未记录，不能自行补参数："
    return "\n".join([prefix, *rows])


def _is_load_capacity_label(label: str) -> bool:
    return any(term in str(label or "") for term in ("承重", "承载", "最大负重", "负重", "load_capacity", "maximum_load"))


def _is_missing_field_value(value: str) -> bool:
    text = str(value or "").strip()
    return not text or text in {"暂无", "无", "未标注", "未注明", "None", "null"}


def _extract_load_capacity_from_item(item: dict) -> str:
    sku = str(item.get("sku") or "").strip().upper()
    for text in _same_sku_load_capacity_texts(item, sku):
        extracted = _extract_load_capacity_phrase(text)
        if extracted:
            return extracted
    return ""


def _same_sku_load_capacity_texts(item: dict, sku: str) -> list[str]:
    texts: list[str] = []

    def add_text(value: Any) -> None:
        if value in (None, "", [], {}):
            return
        if isinstance(value, dict):
            for nested in value.values():
                add_text(nested)
            return
        if isinstance(value, list):
            for nested in value:
                add_text(nested)
            return
        texts.append(str(value))

    for key in (
        "content",
        "evidence_text",
        "features",
        "usage_instruction",
        "top_selling_points",
        "technical_advantages",
        "long_description_cn",
        "long_description_en",
        "listing_cn",
        "listing_en",
    ):
        add_text(item.get(key))
    for section in ("specs", "business", "content"):
        nested = item.get(section)
        if isinstance(nested, dict):
            add_text(nested)
    for value in (item.get("field_values") or {}).values():
        add_text(value)
    for match in item.get("knowledge_matches") or []:
        if not isinstance(match, dict):
            continue
        match_sku = str(match.get("sku") or item.get("sku") or "").strip().upper()
        if sku and match_sku and match_sku != sku:
            continue
        add_text(match.get("content"))
        add_text(match.get("evidence_text"))
    return texts


def _extract_load_capacity_phrase(text: str) -> str:
    compact = re.sub(r"\s+", "", str(text or ""))
    patterns = (
        r"(最大承重|承重|承载|承重量|最大负重|负重)(?:能力|重量)?[:：为是可达约]*([0-9]+(?:\.[0-9]+)?)(KG|kg|Kg|公斤|千克)",
        r"([0-9]+(?:\.[0-9]+)?)(KG|kg|Kg|公斤|千克)(?:承重|承载|负重)",
    )
    for pattern in patterns:
        match = re.search(pattern, compact)
        if not match:
            continue
        groups = match.groups()
        if len(groups) == 3:
            label, number, unit = groups
            return f"{label}{number}{unit.upper() if unit.lower() == 'kg' else unit}"
        number, unit = groups
        return f"承重{number}{unit.upper() if unit.lower() == 'kg' else unit}"
    return ""


def _field_answer_should_replace(question: str, answer: str, results: list[dict]) -> bool:
    if not answer:
        return True
    question_text = str(question or "")
    if any(term in question_text for term in ("酒精炉", "酒精")) and any(
        term in question_text for term in ("能用", "可以用", "支持", "适合", "能不能", "是否支持")
    ):
        return True
    text = str(answer)
    if any(_has_load_capacity_evidence(row) for row in results if isinstance(row, dict)):
        return any(word in text for word in ("暂无", "暂未", "未提供", "未注明", "未标注", "资料"))
    if any("暂无" in str(value) for row in results if isinstance(row, dict) for value in (row.get("field_values") or {}).values()):
        return not any(word in text for word in ("暂无", "未记录", "未标注", "资料"))
    labels = [
        str(label)
        for row in results
        if isinstance(row, dict)
        for label in (row.get("field_values") or {}).keys()
    ]
    return bool(labels) and not any(label in text for label in labels)


def _has_load_capacity_evidence(item: dict) -> bool:
    field_values = item.get("field_values") if isinstance(item.get("field_values"), dict) else {}
    if not any(_is_load_capacity_label(str(label)) for label in field_values):
        return False
    return bool(_extract_load_capacity_from_item(item))


def _rank_recommendation_results(question: str, results: list[dict]) -> list[dict]:
    unique: dict[str, dict] = {}
    for item in results:
        if not isinstance(item, dict):
            continue
        sku = item.get("sku")
        if not sku or sku in unique:
            continue
        unique[sku] = item
    ranked = sorted(unique.values(), key=lambda row: _recommendation_score(question, row), reverse=True)
    compatible = [
        row
        for row in ranked
        if not customer_recommendation_ranker.is_obvious_product_type_mismatch(question, row)
    ]
    if compatible or len(compatible) != len(ranked):
        return compatible[:5]
    return ranked[:5]


def _augment_cooking_set_recommendation_candidates(db: Session, question: str, results: list[dict]) -> list[dict]:
    return results


def _recommendation_products_for_finalizer(db: Session, question: str, results: list[dict]) -> list[dict]:
    enriched: list[dict] = []
    for row in results[:5]:
        sku = str(row.get("sku") or "").strip()
        if not sku:
            continue
        try:
            detail = product_service.get_product_detail(db, sku)
        except Exception:
            detail = dict(row)
        if not isinstance(detail, dict):
            continue
        item = dict(detail)
        recommendation_match = dict(row.get("recommendation_match") or {})
        if not recommendation_match:
            recommendation_match = {
                "matched": [_recommendation_reason(question, row)] if _recommendation_reason(question, row) else [],
                "missing_or_uncertain": [],
                "score": _recommendation_score(question, row),
                "score_reason": "",
            }
        item["recommendation_match"] = recommendation_match
        enriched.append(item)
    return enriched


def _filter_excluded_recommendations(
    question: str,
    results: list[dict],
    conversation_history: list[dict],
    recommendation_context: dict | None = None,
) -> list[dict]:
    excluded_terms = _excluded_terms_from_question(question)
    excluded_skus = _excluded_previous_skus(question, conversation_history, recommendation_context)
    if not excluded_terms and not excluded_skus:
        return results
    kept = []
    for row in results:
        sku = str(row.get("sku") or "").upper()
        if sku and sku in excluded_skus:
            continue
        row_text = _row_text(row).lower()
        if any(term.lower() and term.lower() in row_text for term in excluded_terms):
            continue
        kept.append(row)
    return kept


def _filter_followup_recommendation_scope(
    results: list[dict],
    recommendation_context: dict | None = None,
) -> list[dict]:
    scope = str((recommendation_context or {}).get("product_scope") or "").strip()
    if not scope:
        return results
    normalized_scope = scope.lower()
    filtered = []
    for row in results:
        scope_text = " ".join(
            str(row.get(key) or "")
            for key in ("category", "sub_category", "product_name_cn", "product_name_en")
        ).lower()
        if normalized_scope and normalized_scope in scope_text:
            filtered.append(row)
    return filtered


def _filter_followup_candidate_domain(
    results: list[dict],
    recommendation_context: dict | None = None,
) -> list[dict]:
    candidate_skus = {
        str(sku).strip().upper()
        for sku in (recommendation_context or {}).get("candidate_skus") or []
        if str(sku or "").strip()
    }
    if not candidate_skus:
        return results
    filtered = [
        row
        for row in results
        if str(row.get("sku") or "").strip().upper() in candidate_skus
    ]
    return filtered


def _without_excluded_skus(results: list[dict], excluded_skus: set[str]) -> list[dict]:
    if not excluded_skus:
        return results
    return [
        row
        for row in results
        if str(row.get("sku") or "").strip().upper() not in excluded_skus
    ]


def _excluded_terms_from_question(question: str) -> list[str]:
    terms = []
    text = str(question or "")
    patterns = [
        r"(?:不要|别要|不想要|排除|去掉|剔除|不是)\s*([\u4e00-\u9fffA-Za-z0-9_\-]+?)(?:系列|系|品牌|牌子|产品|的|，|,|。|$)",
        r"换(?:一个|一款|个|款)\s*(?:不要)?\s*([\u4e00-\u9fffA-Za-z0-9_\-]+)?",
    ]
    for pattern in patterns:
        for match in re.finditer(pattern, text):
            value = (match.group(1) or "").strip()
            if value and value not in {"一个", "一款", "产品", "推荐"} and value not in terms:
                terms.append(value)
    return terms


def _excluded_previous_skus(
    question: str,
    conversation_history: list[dict],
    recommendation_context: dict | None = None,
) -> set[str]:
    text = str(question or "")
    readable_terms = (
        "\u6362\u4e00\u4e2a", "\u6362\u4e00\u6b3e", "\u6362\u4e2a", "\u6362\u522b\u7684",
        "\u53e6\u4e00\u4e2a", "\u518d\u63a8\u8350\u4e00\u4e2a", "\u53e6\u5916\u63a8\u8350",
        "\u8fd8\u6709\u522b\u7684", "\u8fd8\u6709\u5176\u4ed6", "\u5176\u4ed6\u63a8\u8350",
        "\u4e0d\u8981\u521a\u624d", "\u522b\u8981\u521a\u624d", "\u4e0d\u559c\u6b22",
        "\u4e0d\u8003\u8651", "\u4e0d\u592a\u6ee1\u610f", "\u90fd\u4e0d\u559c\u6b22",
        "\u4e0d\u548b\u559c\u6b22",
    )
    if not any(word in text for word in readable_terms):
        return set()
    context_skus = {
        str(sku).strip().upper()
        for sku in (recommendation_context or {}).get("recommended_skus") or []
        if str(sku or "").strip()
    }
    if context_skus:
        return context_skus
    for item in reversed(conversation_history[-6:]):
        if item.get("role") != "assistant":
            continue
        skus = _extract_skus(str(item.get("content") or ""))
        if skus:
            return skus
    return set()

def _recommendation_score(question: str, row: dict) -> float:
    return customer_recommendation_ranker.recommendation_score(question, row)


def _should_replace_recommendation_answer(answer: str, question: str, results: list[dict]) -> bool:
    if not results:
        return False
    if _answer_conflicts_with_current_results(answer, question, results):
        return True
    if _answer_focus_conflicts(answer, question):
        return True
    listed_count = len(re.findall(r"(^|\n)\s*\d+[\.、]", answer))
    if listed_count > 5:
        return True
    if any(word in question for word in ("咖啡", "泡咖啡", "小锅")) and any(word in answer for word in ("炒锅", "煎锅", "煎盘")):
        return True
    if _answer_budget_conflicts(answer, question, results):
        return True
    if _is_low_budget_query(question) and _answer_misses_ranked_first_choice(answer, results):
        return True
    return "找到" in answer and "条产品资料" in answer


def _compose_recommendation_answer(question: str, results: list[dict]) -> str:
    if not results:
        if any(term in question for term in ("还有别的", "还有其他", "换一个", "换一款", "换个", "换别的", "再推荐", "其他推荐")):
            return "除了上一轮已经推荐的产品，暂时没有找到其它足够匹配的同类产品。你可以放宽品类、容量或使用场景，我再帮你重新筛选。"
        return "没有找到足够匹配的产品资料。你可以补充人数、场景或容量要求，我再帮你缩小范围。"
    best = results[0]
    lines = [f"首选 {best.get('sku')}，{best.get('product_name_cn') or best.get('product_name_en') or ''}。"]
    reason = _recommendation_reason(question, best)
    if reason:
        lines.append(f"理由：{reason}")
    if len(results) > 1:
        lines.append("备选：")
        for item in results[1:3]:
            item_reason = _recommendation_reason(question, item)
            lines.append(f"{item.get('sku')}，{item.get('product_name_cn') or item.get('product_name_en') or ''}：{item_reason}")
    if any(word in question for word in ("咖啡", "泡咖啡", "小锅")):
        lines.append("我已把炒锅、煎锅这类容量偏大或器型不适合泡咖啡的产品降权，不作为优先推荐。")
    return "\n".join(line for line in lines if line.strip())


def _recommendation_reason(question: str, row: dict) -> str:
    evidence_reason = _recommendation_evidence_reason(row)
    if evidence_reason:
        return evidence_reason
    parts = []
    capacity = row.get("capacity")
    if capacity:
        parts.append(f"容量 {capacity}")
    if row.get("body_material"):
        parts.append(f"材质 {row.get('body_material')}")
    features = row.get("features") or row.get("top_selling_points") or row.get("semantic_match")
    if features:
        parts.append(f"卖点 {features}")
    if row.get("price_positioning"):
        parts.append(f"价格定位 {row.get('price_positioning')}")
    scenes = row.get("usage_scenarios") or row.get("usage_scene") or ""
    if scenes:
        parts.append(f"场景 {scenes}")
    audience = row.get("target_audience")
    if audience:
        parts.append(f"人群 {audience}")
    positioning = row.get("positioning")
    if positioning:
        parts.append(f"定位 {positioning}")
    if any(word in question for word in ("咖啡", "泡咖啡", "小锅")) and _capacity_ml(capacity) and _capacity_ml(capacity) > 2000:
        parts.append("但容量偏大，不适合单人小锅泡咖啡")
    reason = "；".join(str(part) for part in parts[:4] if part)
    if reason:
        return reason
    if customer_price_signal.is_high_price_query(question):
        return "更符合本轮高端一点的筛选方向"
    return "与本轮需求匹配"


def _row_text(row: dict) -> str:
    values = []
    for key in ("product_name_cn", "product_name_en", "category", "sub_category", "capacity", "body_material", "features", "target_audience", "positioning", "price_positioning", "usage_scenarios", "emotional_value", "semantic_match"):
        value = row.get(key)
        if value:
            values.append(str(value))
    field_values = row.get("field_values")
    if isinstance(field_values, dict):
        values.extend(str(value) for value in field_values.values())
    return " ".join(values)


def _recommendation_evidence_reason(row: dict) -> str:
    match = row.get("recommendation_match") if isinstance(row.get("recommendation_match"), dict) else {}
    candidates: list[str] = []
    for raw in match.get("matched") or []:
        text = str(raw or "").strip("。；; ")
        if not text or any(noisy in text for noisy in ("有可用", "基础信息", "信息可供判断", "有卖点/场景资料可引用", "排序分数")):
            continue
        candidates.append(text)
    for key in ("features", "top_selling_points", "usage_scenarios", "target_audience", "positioning", "semantic_match"):
        value = str(row.get(key) or "").strip()
        if value:
            candidates.append(value)
    seen: set[str] = set()
    cleaned: list[str] = []
    for item in candidates:
        item = re.sub(r"\s+", " ", item).strip("。；; ")
        if not item or item in seen:
            continue
        seen.add(item)
        cleaned.append(item)
        if len(cleaned) >= 2:
            break
    if not cleaned:
        return ""
    return "；".join(cleaned)[:90].rstrip("；;，,") + "。"


def _explanation_followup_skus(question: str, last_turn_summary: dict) -> list[str]:
    skus = [
        str(item or "").strip().upper()
        for item in (last_turn_summary.get("result_skus") or [])
        if str(item or "").strip()
    ]
    if not skus:
        skus = [
            str(item or "").strip().upper()
            for item in (
                last_turn_summary.get("ordered_result_skus")
                or last_turn_summary.get("recommended_skus")
                or []
            )
            if str(item or "").strip()
        ]
    if not skus:
        return []
    text = str(question or "")
    if any(
        term in text
        for term in (
            "\u7b2c\u4e00\u4e2a",
            "\u7b2c\u4e00\u6b3e",
            "\u9996\u4e2a",
            "\u9996\u6b3e",
        )
    ):
        first_from_answer = _extract_skus_in_order(str(last_turn_summary.get("assistant_answer") or ""))
        if first_from_answer:
            return first_from_answer[:1]
        return skus[:1]
    return skus[:5]


def _is_explanation_followup(question: str, last_turn_summary: dict) -> bool:
    available_skus = (
        last_turn_summary.get("result_skus")
        or last_turn_summary.get("ordered_result_skus")
        or last_turn_summary.get("recommended_skus")
        or last_turn_summary.get("candidate_skus")
        or []
    )
    if not last_turn_summary or not available_skus:
        return False
    if last_turn_summary.get("intent") != "recommend_products":
        return False
    if _is_compare_like_question(question, context_skus=available_skus):
        return False
    text = str(question or "")
    return any(
        term in text
        for term in (
            "\u4e3a\u4ec0\u4e48\u63a8\u8350",
            "\u63a8\u8350\u7406\u7531",
            "\u7406\u7531",
            "\u89e3\u91ca",
            "\u4f9d\u636e",
            "\u7b2c\u4e00\u4e2a",
            "\u7b2c\u4e00\u6b3e",
            "\u9996\u4e2a",
            "\u9996\u6b3e",
            "\u524d\u9762\u63a8\u8350\u7684",
            "\u521a\u624d\u63a8\u8350\u7684",
        )
    )


def _is_candidate_scope_followup(question: str) -> bool:
    text = str(question or "")
    return any(
        term in text
        for term in (
            "\u8fd9\u4e9b\u91cc",
            "\u8fd9\u4e9b\u91cc\u9762",
            "\u8fd9\u4e9b\u91cc\u54ea\u4e2a",
            "\u91cc\u9762\u54ea\u4e9b",
            "\u91cc\u9762\u54ea\u4e2a",
            "\u4e0a\u9762\u8fd9\u4e9b",
            "\u5176\u4e2d\u54ea\u4e2a",
            "\u54ea\u4e2a\u66f4\u9002\u5408",
            "\u54ea\u4e9b\u652f\u6301",
        )
    )


def _is_recommendation_change_followup(question: str, last_turn_summary: dict) -> bool:
    if not last_turn_summary or last_turn_summary.get("intent") != "recommend_products":
        return False
    available_skus = (
        last_turn_summary.get("result_skus")
        or last_turn_summary.get("ordered_result_skus")
        or last_turn_summary.get("recommended_skus")
        or last_turn_summary.get("candidate_skus")
        or []
    )
    if not available_skus:
        return False
    text = str(question or "")
    return any(
        term in text
        for term in (
            "\u6362\u4e00\u4e2a",
            "\u6362\u4e00\u6b3e",
            "\u6362\u4e2a",
            "\u53e6\u4e00\u4e2a",
            "\u518d\u63a8\u8350",
            "\u4e0d\u8981\u521a\u624d",
            "\u522b\u8981\u521a\u624d",
            "\u5176\u4ed6\u63a8\u8350",
            "\u66ff\u4ee3",
            "\u66f4\u4fbf\u5b9c",
            "\u66f4\u8f7b",
        )
    )


def _is_recommendation_change_followup_text(question: str) -> bool:
    text = str(question or "")
    return any(
        term in text
        for term in (
            "换一个",
            "换一款",
            "换个",
            "另外一个",
            "再推荐",
            "不要刚才",
            "别要刚才",
            "其他推荐",
            "替代",
            "更便宜",
            "更轻",
        )
    )


def _is_empty_subset_followup(question: str) -> bool:
    text = str(question or "")
    readable_followup_terms = (
        "\u8fd9\u4e9b", "\u91cc\u9762", "\u4e0a\u9762\u8fd9\u4e9b",
        "\u4e3a\u4ec0\u4e48\u63a8\u8350", "\u63a8\u8350\u7406\u7531",
        "\u7b2c\u4e00\u4e2a", "\u7b2c\u4e8c\u4e2a", "\u4e0a\u4e00\u4e2a",
        "\u6700\u8f7b", "\u54ea\u4e2a\u6700\u8f7b", "\u54ea\u6b3e\u6700\u8f7b",
        "\u66f4\u8f7b", "\u66f4\u4fbf\u5b9c", "\u66ff\u4ee3", "\u6362\u4e00\u4e2a",
        "\u6362\u4e00\u6b3e", "\u8fd8\u6709\u6ca1\u6709", "\u6709\u6ca1\u6709",
        "\u54ea\u4e2a\u66f4\u9002\u5408", "\u54ea\u6b3e\u66f4\u9002\u5408",
    )
    return (
        any(term in text for term in readable_followup_terms)
        or (
            _is_candidate_scope_followup(text)
            and _people_count_from_question(text) is not None
            and any(term in text for term in ("\u9002\u5408", "\u63a8\u8350", "\u54ea\u6b3e", "\u54ea\u4e2a"))
        )
        or _is_candidate_scope_followup(question)
        or _is_recommendation_change_followup_text(question)
        or _is_recommendation_change_followup(question, {"intent": "recommend_products", "result_skus": [1]})
    )


def _excluded_previous_skus(
    question: str,
    conversation_history: list[dict],
    recommendation_context: dict | None = None,
) -> set[str]:
    text = str(question or "")
    readable_terms = (
        "\u6362\u4e00\u4e2a", "\u6362\u4e00\u6b3e", "\u6362\u4e2a", "\u6362\u522b\u7684",
        "\u53e6\u4e00\u4e2a", "\u518d\u63a8\u8350\u4e00\u4e2a", "\u53e6\u5916\u63a8\u8350",
        "\u8fd8\u6709\u522b\u7684", "\u8fd8\u6709\u5176\u4ed6", "\u5176\u4ed6\u63a8\u8350",
        "\u4e0d\u8981\u521a\u624d", "\u522b\u8981\u521a\u624d", "\u4e0d\u559c\u6b22",
        "\u4e0d\u8003\u8651", "\u4e0d\u592a\u6ee1\u610f", "\u90fd\u4e0d\u559c\u6b22",
        "\u4e0d\u548b\u559c\u6b22", "\u66ff\u4ee3", "\u66f4\u4fbf\u5b9c", "\u66f4\u8f7b",
    )
    if not any(word in text for word in readable_terms):
        return set()
    context_skus = {
        str(sku).strip().upper()
        for sku in (recommendation_context or {}).get("recommended_skus") or []
        if str(sku or "").strip()
    }
    if context_skus:
        return context_skus
    for item in reversed(conversation_history[-6:]):
        if item.get("role") != "assistant":
            continue
        skus = _extract_skus(str(item.get("content") or ""))
        if skus:
            return skus
    return set()


def _is_cheaper_alternative_question(question: str) -> bool:
    text = str(question or "")
    return any(
        term in text
        for term in (
            "\u66f4\u4fbf\u5b9c",
            "\u4fbf\u5b9c\u4e00\u70b9",
            "\u4f4e\u4e00\u70b9",
            "\u7701\u4e00\u70b9",
            "\u66ff\u4ee3",
        )
    )


def _followup_price_reason(row: dict) -> str:
    price_positioning = str(row.get("price_positioning") or "").strip()
    positioning = str(row.get("positioning") or "").strip()
    features = str(row.get("features") or row.get("top_selling_points") or "").strip()
    if price_positioning:
        return f"\u5f53\u524d\u8d44\u6599\u91cc\u8fd9\u6b3e\u7684\u4ef7\u683c\u5b9a\u4f4d\u662f{price_positioning}\uff0c\u5982\u679c\u4f60\u73b0\u5728\u4f18\u5148\u770b\u95e8\u69db\u66f4\u4f4e\u7684\u66ff\u4ee3\uff0c\u5b83\u4f1a\u6bd4\u4e0a\u4e00\u8f6e\u66f4\u503c\u5f97\u5148\u770b\u3002"
    lower_signal = next(
        (term for term in ("\u9ad8\u6027\u4ef7\u6bd4", "\u5165\u95e8", "\u57fa\u7840", "\u8f7b\u91cf\u5316") if term in positioning or term in features),
        "",
    )
    if lower_signal:
        return f"\u5f53\u524d\u8d44\u6599\u91cc\u6ca1\u6709\u660e\u786e\u4ef7\u683c\u6570\u5b57\uff0c\u4f46\u4ece\u201c{lower_signal}\u201d\u8fd9\u7c7b\u5b9a\u4f4d\u6765\u770b\uff0c\u5b83\u66f4\u9002\u5408\u4f5c\u4e3a\u76f8\u5bf9\u66f4\u4f4e\u95e8\u69db\u7684\u66ff\u4ee3\u65b9\u6848\u3002"
    return ""


def _recommendation_reason(question: str, row: dict, *, followup: bool = False) -> str:
    evidence_reason = _recommendation_evidence_reason(row)
    if evidence_reason:
        return evidence_reason
    parts: list[str] = []
    capacity = row.get("capacity")
    if capacity:
        parts.append(f"\u5bb9\u91cf {capacity}")
    if row.get("body_material"):
        parts.append(f"\u6750\u8d28 {row.get('body_material')}")
    features = row.get("features") or row.get("top_selling_points") or row.get("semantic_match")
    if features:
        parts.append(f"\u5356\u70b9 {features}")
    if row.get("price_positioning"):
        parts.append(f"\u4ef7\u683c\u5b9a\u4f4d {row.get('price_positioning')}")
    scenes = row.get("usage_scenarios") or row.get("usage_scene") or ""
    if scenes:
        parts.append(f"\u573a\u666f {scenes}")
    audience = row.get("target_audience")
    if audience:
        parts.append(f"\u4eba\u7fa4 {audience}")
    positioning = row.get("positioning")
    if positioning:
        parts.append(f"\u5b9a\u4f4d {positioning}")
    if any(word in question for word in ("\u5496\u5561", "\u6ce1\u5496\u5561", "\u5c0f\u9505")) and _capacity_ml(capacity) and _capacity_ml(capacity) > 2000:
        parts.append("\u4f46\u5bb9\u91cf\u504f\u5927\uff0c\u4e0d\u9002\u5408\u5355\u4eba\u5c0f\u9505\u6ce1\u5496\u5561")
    reason = "\uff1b".join(str(part) for part in parts[:4] if part)
    if reason:
        return reason
    if customer_price_signal.is_high_price_query(question):
        return "\u66f4\u7b26\u5408\u672c\u8f6e\u504f\u9ad8\u7aef\u4e00\u70b9\u7684\u7b5b\u9009\u65b9\u5411\u3002"
    if followup:
        return "\u6211\u5148\u5728\u4fdd\u7559\u4e0a\u4e00\u8f6e\u9700\u6c42\u8303\u56f4\u7684\u524d\u63d0\u4e0b\uff0c\u7ed9\u4f60\u6362\u6210\u76f8\u5bf9\u66f4\u5408\u9002\u7684\u5907\u9009\u3002"
    return "\u4e0e\u672c\u8f6e\u9700\u6c42\u5339\u914d\u3002"


def _compose_recommendation_explanation_answer(
    question: str,
    row: dict,
    recommendation_summary: dict | None = None,
) -> str:
    sku = str(row.get("sku") or "").strip().upper()
    name = str(row.get("product_name_cn") or row.get("product_name_en") or sku).strip()
    if not sku and not name:
        return ""
    base_question = str((recommendation_summary or {}).get("user_question") or question or "")
    reason = _recommendation_reason(base_question, row)
    scenes = str(
        row.get("usage_scenarios")
        or row.get("usage_scene")
        or row.get("target_audience")
        or row.get("positioning")
        or row.get("features")
        or row.get("top_selling_points")
        or ""
    ).strip()
    scenes = re.sub(r"\s+", " ", scenes).strip("；;，,。 ")
    if len(scenes) > 120:
        scenes = scenes[:120].rstrip("；;，,。 ") + "…"
    lines = [f"\u4e0a\u4e00\u8f6e\u7b2c\u4e00\u4e2a\u63a8\u8350\u7684\u662f{name}\uff08{sku}\uff09\u3002"]
    if reason:
        lines.append(f"\u63a8\u8350\u5b83\u4e3b\u8981\u662f\u56e0\u4e3a{reason}\u3002")
    if scenes:
        lines.append(f"\u4ece\u73b0\u6709\u8d44\u6599\u770b\uff0c\u5b83\u66f4\u5e38\u89c1\u7684\u4f7f\u7528\u573a\u666f\u662f\uff1a{scenes}\u3002")
    return "\n".join(line for line in lines if line.strip())


def _is_plural_recommendation_explanation(question: str) -> bool:
    text = str(question or "")
    return any(term in text for term in ("\u8fd9\u4e9b", "\u8fd9\u4e9b\u4ea7\u54c1", "\u4e0a\u9762\u8fd9\u4e9b", "\u4e3a\u4ec0\u4e48\u63a8\u8350\u8fd9\u4e9b"))


def _compose_multi_recommendation_explanation_answer(
    question: str,
    rows: list[dict],
    recommendation_summary: dict | None = None,
) -> str:
    if not rows:
        return ""
    lines = ["\u4e0a\u4e00\u8f6e\u63a8\u8350\u7684\u4ea7\u54c1\u4e3b\u8981\u6709\uff1a"]
    for row in rows[:5]:
        sku = str(row.get("sku") or "").strip().upper()
        name = str(row.get("product_name_cn") or row.get("product_name_en") or sku).strip()
        if not sku and not name:
            continue
        reason = _recommendation_reason(
            str((recommendation_summary or {}).get("user_question") or question or ""),
            row,
        )
        if reason:
            lines.append(f"- {name}\uff08{sku}\uff09\uff1a{reason}")
        else:
            lines.append(f"- {name}\uff08{sku}\uff09")
    return "\n".join(line for line in lines if line.strip())


def _compose_recommendation_answer(
    question: str,
    results: list[dict],
    *,
    excluded_skus: set[str] | None = None,
) -> str:
    if not results:
        if any(term in question for term in ("\u8fd8\u6709\u522b\u7684", "\u8fd8\u6709\u5176\u4ed6", "\u6362\u4e00\u4e2a", "\u6362\u4e00\u6b3e", "\u6362\u4e2a", "\u6362\u522b\u7684", "\u518d\u63a8\u8350", "\u5176\u4ed6\u63a8\u8350", "\u66ff\u4ee3", "\u66f4\u4fbf\u5b9c", "\u66f4\u8f7b")):
            return "\u9664\u4e86\u4e0a\u4e00\u8f6e\u5df2\u7ecf\u63a8\u8350\u7684\u4ea7\u54c1\uff0c\u6682\u65f6\u6ca1\u6709\u627e\u5230\u5176\u4ed6\u8db3\u591f\u5339\u914d\u7684\u540c\u7c7b\u4ea7\u54c1\u3002\u4f60\u53ef\u4ee5\u653e\u5bbd\u54c1\u7c7b\u3001\u5bb9\u91cf\u6216\u4f7f\u7528\u573a\u666f\uff0c\u6211\u518d\u5e2e\u4f60\u91cd\u65b0\u7b5b\u9009\u3002"
        return "\u6ca1\u6709\u627e\u5230\u8db3\u591f\u5339\u914d\u7684\u4ea7\u54c1\u8d44\u6599\u3002\u4f60\u53ef\u4ee5\u8865\u5145\u4eba\u6570\u3001\u573a\u666f\u6216\u5bb9\u91cf\u8981\u6c42\uff0c\u6211\u518d\u5e2e\u4f60\u7f29\u5c0f\u8303\u56f4\u3002"

    best = results[0]
    excluded_skus = {str(sku or "").strip().upper() for sku in (excluded_skus or set()) if str(sku or "").strip()}
    is_change_followup = any(
        term in str(question or "")
        for term in (
            "\u6362\u4e00\u4e2a",
            "\u6362\u4e00\u6b3e",
            "\u6362\u4e2a",
            "\u4e0d\u8981\u521a\u624d\u90a3\u4e2a",
            "\u522b\u8981\u521a\u624d\u90a3\u4e2a",
            "\u66ff\u4ee3",
            "\u66f4\u4fbf\u5b9c",
            "\u66f4\u8f7b",
        )
    )
    reason = _recommendation_reason(question, best, followup=is_change_followup)
    lines: list[str] = []
    if is_change_followup:
        avoided = ""
        if excluded_skus:
            avoided = "\uff0c\u5df2\u907f\u5f00\u521a\u624d\u90a3\u6b3e" if len(excluded_skus) == 1 else "\uff0c\u5df2\u907f\u5f00\u4e0a\u4e00\u8f6e\u63d0\u8fc7\u7684\u51e0\u6b3e"
        lines.append(f"\u8fd9\u6b21\u53ef\u4ee5\u6539\u770b {best.get('product_name_cn') or best.get('product_name_en') or best.get('sku')}\uff08{best.get('sku')}\uff09{avoided}\u3002")
        if _is_cheaper_alternative_question(question):
            price_reason = _followup_price_reason(best)
            if price_reason:
                lines.append(price_reason)
            else:
                lines.append("\u5f53\u524d\u8d44\u6599\u91cc\u6ca1\u6709\u660e\u786e\u4ef7\u683c\u5b57\u6bb5\uff0c\u6211\u4e0d\u80fd\u76f4\u63a5\u5224\u65ad\u5b83\u4e00\u5b9a\u66f4\u4fbf\u5b9c\uff1b\u5982\u679c\u4f60\u613f\u610f\uff0c\u6211\u53ef\u4ee5\u7ee7\u7eed\u6309\u66f4\u57fa\u7840\u914d\u7f6e\u6216\u66f4\u5c11\u4ef6\u6570\u5e2e\u4f60\u7f29\u5c0f\u8303\u56f4\u3002")
        elif reason:
            lines.append(reason)
        else:
            lines.append("\u6211\u5148\u6309\u4e0a\u4e00\u8f6e\u540c\u7c7b\u9700\u6c42\u5e2e\u4f60\u6362\u4e86\u4e00\u6b3e\u5019\u9009\uff1b\u5982\u679c\u4f60\u60f3\u7ee7\u7eed\u7f29\u5c0f\u5230\u66f4\u8f7b\u3001\u66f4\u5c0f\u4f53\u79ef\u6216\u66f4\u9002\u5408\u67d0\u4e2a\u573a\u666f\uff0c\u6211\u53ef\u4ee5\u518d\u7ec6\u5316\u3002")
    else:
        lines.append(f"\u9996\u9009 {best.get('sku')}\uff0c{best.get('product_name_cn') or best.get('product_name_en') or ''}\u3002")
        if reason:
            lines.append(f"\u7406\u7531\uff1a{reason}")
    if len(results) > 1:
        lines.append("\u5907\u9009\uff1a")
        for item in results[1:3]:
            item_reason = _recommendation_reason(question, item, followup=is_change_followup)
            lines.append(f"{item.get('sku')}\uff0c{item.get('product_name_cn') or item.get('product_name_en') or ''}\uff1a{item_reason}")
    if any(word in question for word in ("\u5496\u5561", "\u6ce1\u5496\u5561", "\u5c0f\u9505")):
        lines.append("\u6211\u5df2\u7ecf\u628a\u7092\u9505\u3001\u714e\u9505\u8fd9\u7c7b\u5bb9\u91cf\u504f\u5927\u6216\u5668\u578b\u4e0d\u9002\u5408\u6ce1\u5496\u5561\u7684\u4ea7\u54c1\u964d\u6743\uff0c\u4e0d\u4f5c\u4e3a\u4f18\u5148\u63a8\u8350\u3002")
    return "\\n".join(line for line in lines if line.strip())


def _capacity_ml(value: Any) -> float | None:
    text = str(value or "")
    numbers = [float(item) for item in re.findall(r"(\d+(?:\.\d+)?)\s*(?:ML|ml|毫升)", text)]
    if numbers:
        return max(numbers)
    liters = [float(item) * 1000 for item in re.findall(r"(\d+(?:\.\d+)?)\s*(?:L|l|升)", text)]
    if liters:
        return max(liters)
    return None


def _recommendation_question_with_context(question: str, conversation_history: list[dict]) -> str:
    return customer_dialogue_state.recommendation_question_with_context(question, conversation_history)


def _is_budget_followup(question: str) -> bool:
    return customer_dialogue_state.is_budget_followup(question)


def _is_low_budget_query(question: str) -> bool:
    return customer_dialogue_state.is_low_budget_query(question)


def _price_text(row: dict) -> str:
    return " ".join(
        str(row.get(key) or "")
        for key in ("price_positioning", "positioning", "product_level", "features", "semantic_match")
    )


def _build_clarification_result(question: str, sku: str | None, dialogue_state: customer_dialogue_state.DialogueState) -> dict:
    answer = "我还需要一个更明确的产品范围。你可以告诉我要查的 SKU、产品名、类目，或者具体使用场景，比如“适合三个人露营的锅”。"
    result = {
        "answer": answer,
        "intent": "clarify",
        "answer_type": "clarification",
        "confidence": "low",
        "uncertainty": "ambiguous_product",
        "needs_clarification": True,
        "sku": sku,
        "sources": [{"type": "agent_clarification", "label": "需要明确产品范围"}],
        "actions": [],
        "results": [],
        "steps": [
            {
                "type": "clarify",
                "label": "需要明确产品范围",
                "detail": f"clarification_reason={dialogue_state.clarification_reason}; missing_slots={dialogue_state.missing_slots}",
            }
        ],
        "warnings": [],
        "debug": {
            "agent_mode": "dialogue_state_clarification",
            "dialogue_state": dialogue_state.to_dict(),
            "warnings": [],
        },
    }
    quality = customer_agent_quality_service.evaluate_agent_response(
        question,
        answer=result["answer"],
        intent=result["intent"],
        results=result["results"],
        sources=result["sources"],
        actions=result["actions"],
        warnings=result["warnings"],
        needs_clarification=result["needs_clarification"],
    )
    result["agent_quality"] = quality
    result["debug"]["agent_quality"] = quality
    return result


def _build_answer_metadata(answer: str, results: list[dict], warnings: list[str], needs_clarification: bool) -> dict[str, Any]:
    evidence_insufficient = _uncertainty(answer, results, warnings, needs_clarification) in {"not_recorded", "insufficient_data"}
    return {
        "evidence_insufficient": evidence_insufficient,
        "answer_policy": "insufficient_evidence" if evidence_insufficient else "normal",
    }


def _build_product_ambiguity_result(question: str, candidates: list[dict]) -> dict:
    names = [str(item.get("product_name_cn") or item.get("product_name_en") or "").strip() for item in candidates if isinstance(item, dict)]
    summary = "、".join(name for name in names if name) or "多个候选产品"
    answer = f"你提到的产品名不够完整，我找到了多个可能候选：{summary}。请补充完整产品名或 SKU。"
    result = {
        "answer": answer,
        "intent": "clarify",
        "answer_type": "clarification",
        "confidence": "low",
        "uncertainty": "ambiguous_product",
        "needs_clarification": True,
        "sku": None,
        "sources": [{"type": "agent_clarification", "label": "产品名不完整，需要澄清"}],
        "actions": [],
        "results": [],
        "steps": [
            {
                "type": "clarify",
                "label": "产品名不完整，需要澄清",
                "detail": f"candidates={[item.get('sku') for item in candidates if isinstance(item, dict)]}",
            }
        ],
        "warnings": [],
        "debug": {
            "agent_mode": "product_name_clarification",
            "candidates": candidates[:8],
            "warnings": [],
        },
    }
    quality = customer_agent_quality_service.evaluate_agent_response(
        question,
        answer=result["answer"],
        intent=result["intent"],
        results=result["results"],
        sources=result["sources"],
        actions=result["actions"],
        warnings=result["warnings"],
        needs_clarification=result["needs_clarification"],
    )
    result["agent_quality"] = quality
    result["debug"]["agent_quality"] = quality
    return result


def _build_specific_product_not_found_result(question: str, product_name: str, route_plan: dict[str, Any]) -> dict:
    name = product_name.strip(" 「」\"'“”") or str(question or "").strip(" 「」\"'“”")
    answer = f"没有找到“{name}”的相关资料，请确认产品名或 SKU 后再查询。"
    result = {
        "answer": answer,
        "intent": "product_detail",
        "answer_type": "product_detail",
        "confidence": "low",
        "uncertainty": "missing_product",
        "needs_clarification": False,
        "sku": None,
        "sources": [{"type": "product_search", "label": "明确产品名未命中", "query": name, "count": 0}],
        "actions": [],
        "results": [],
        "steps": [
            {
                "type": "conversation_route",
                "label": "判断为明确产品查询",
                "detail": route_plan.get("reason") or "LLM 判断用户在查找明确产品名，产品库未命中。",
                "ok": True,
            }
        ],
        "warnings": ["specific_product_not_found"],
        "debug": {"agent_mode": "specific_product_not_found", "route_plan": route_plan, "warnings": ["specific_product_not_found"]},
    }
    quality = customer_agent_quality_service.evaluate_agent_response(
        question,
        answer=result["answer"],
        intent=result["intent"],
        results=result["results"],
        sources=result["sources"],
        actions=result["actions"],
        warnings=result["warnings"],
        needs_clarification=result["needs_clarification"],
    )
    result["agent_quality"] = quality
    result["debug"]["agent_quality"] = quality
    return result


def _answer_budget_conflicts(answer: str, question: str, results: list[dict]) -> bool:
    if not _is_low_budget_query(question) or not answer or not results:
        return False
    best_sku = str(results[0].get("sku") or "")
    for row in results[1:]:
        if customer_price_signal.price_bucket_for_row(row) != "high":
            continue
        sku = str(row.get("sku") or "")
        name = str(row.get("product_name_cn") or row.get("product_name_en") or "")
        if (sku and sku != best_sku and sku in answer) or (name and name in answer and sku != best_sku):
            return True
    return customer_price_signal.is_low_price_query(question) and "高端" in answer and any(word in answer for word in ("推荐", "首选", "适合"))


def _answer_misses_ranked_first_choice(answer: str, results: list[dict]) -> bool:
    if not answer or not results:
        return False
    best = results[0]
    best_sku = str(best.get("sku") or "")
    best_name = str(best.get("product_name_cn") or best.get("product_name_en") or "")
    return bool(best_sku or best_name) and best_sku not in answer and best_name not in answer


def _resolve_context_arguments(arguments: dict[str, Any], previous_result_skus: list[str], tool_results: list[dict]) -> dict[str, Any]:
    resolved = dict(arguments)
    if resolved.get("skus") in ("$previous_result_skus", "previous_result_skus", "这些", "刚才那些"):
        resolved["skus"] = previous_result_skus
    if resolved.get("sku") in ("$previous_result_skus", "previous_result_skus", "这些", "刚才那些"):
        resolved.pop("sku", None)
        resolved["skus"] = previous_result_skus
    if resolved.get("skus") in ("$last_search_skus", "last_search_skus"):
        resolved["skus"] = _latest_search_skus(tool_results)
    return resolved


def _enrich_recommendation_tool_arguments(
    name: str,
    arguments: dict[str, Any],
    question: str,
    route_plan: dict[str, Any] | None,
) -> dict[str, Any]:
    if name not in {"search_products", "hybrid_search_products"}:
        return arguments
    if not _tool_call_is_for_recommendation(question, route_plan):
        return arguments
    enriched = dict(arguments)
    fields = list(enriched.get("fields") or [])
    for field in (
        "specs.capacity",
        "specs.body_material",
        "business.top_selling_points",
        "business.usage_scenarios",
        "business.target_audience",
        "business.price_positioning",
        "business.positioning",
    ):
        if field not in fields:
            fields.append(field)
    enriched["fields"] = fields
    enriched["limit"] = max(int(enriched.get("limit") or 0), 20)
    if customer_price_signal.price_preference(question) == "high":
        filters = dict(enriched.get("filters") or {})
        filters.setdefault("价格定位", "高端")
        enriched["filters"] = filters
    return enriched


def _tool_call_is_for_recommendation(question: str, route_plan: dict[str, Any] | None) -> bool:
    if route_plan and route_plan.get("query_type") == "recommendation":
        return True
    return _is_recommendation_question(question)


def _question_for_result(question: str, route_plan: dict[str, Any] | None) -> str:
    if route_plan and route_plan.get("context_mode") == "inherit_need":
        effective_question = str(route_plan.get("effective_question") or "").strip()
        if effective_question:
            return effective_question
    return question


def _redirect_preference_detail_to_recommendation_search(
    name: str,
    arguments: dict[str, Any],
    question: str,
    route_plan: dict[str, Any] | None,
    conversation_history: list[dict],
) -> tuple[str, dict[str, Any]]:
    if name != "get_product_detail":
        return name, arguments
    if not route_plan or route_plan.get("context_mode") != "inherit_need":
        return name, arguments
    if not _looks_like_preference_adjustment(question):
        return name, arguments
    semantic_query = route_plan.get("effective_question") or _recommendation_question_with_context(question, conversation_history)
    filters: dict[str, Any] = {}
    if customer_price_signal.price_preference(question) == "high":
        filters["价格定位"] = "高端"
    return "hybrid_search_products", {
        "filters": filters,
        "semantic_query": semantic_query,
        "fields": [
            "specs.capacity",
            "specs.body_material",
            "business.top_selling_points",
            "business.usage_scenarios",
            "business.target_audience",
            "business.price_positioning",
            "business.positioning",
        ],
        "limit": 20,
    }


def _requires_lookup_tool(question: str) -> bool:
    text = str(question or "")
    if _requires_write_tool(text):
        return False
    return any(term in text for term in PRODUCT_LOOKUP_TERMS)


def _requires_write_tool(question: str) -> bool:
    text = str(question or "")
    return any(term in text for term in PRODUCT_WRITE_TERMS)


def _answer_focus_conflicts(answer: str, question: str) -> bool:
    answer_text = str(answer or "")
    question_text = str(question or "")
    asks_cooking = any(term in question_text for term in COOKING_TERMS)
    asks_coffee = any(term in question_text for term in COFFEE_TERMS)
    if asks_cooking and not asks_coffee and any(term in answer_text for term in COFFEE_TERMS):
        return True
    return False


def _answer_conflicts_with_current_results(answer: str, question: str, results: list[dict]) -> bool:
    if not answer or not results:
        return False
    if _answer_focus_conflicts(answer, question):
        return True

    result_skus = {str(item.get("sku") or "").upper() for item in results if item.get("sku")}
    if not result_skus:
        return False

    mentioned_skus = _extract_skus(answer)
    if not mentioned_skus:
        return False

    if mentioned_skus.isdisjoint(result_skus):
        return True
    return bool(mentioned_skus - result_skus) and any(word in answer for word in ("首选", "推荐", "适合", "建议"))


def _extract_skus(text: str) -> set[str]:
    return {
        match.upper()
        for match in re.findall(r"\b[A-Z]{1,6}(?:-[A-Z0-9]{1,8}){1,4}\b", str(text or ""), flags=re.IGNORECASE)
    }


def _extract_skus_in_order(text: str) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for match in re.findall(r"\b[A-Z]{1,6}(?:-[A-Z0-9]{1,8}){1,4}\b", str(text or ""), flags=re.IGNORECASE):
        sku = str(match or "").strip().upper()
        if not sku or sku in seen:
            continue
        seen.add(sku)
        ordered.append(sku)
    return ordered


def _latest_search_skus(tool_results: list[dict]) -> list[str]:
    for result in reversed(tool_results):
        if result.get("tool") in {"search_products", "hybrid_search_products"}:
            return [item.get("sku") for item in result.get("results") or [] if item.get("sku")]
    return []


def _needs_previous_context(question: str) -> bool:
    return customer_dialogue_state.needs_previous_context(question)


def _step_from_tool_result(name: str, arguments: dict[str, Any], result: dict) -> dict:
    labels = {
        "search_products": "查询产品",
        "hybrid_search_products": "融合查询产品",
        "semantic_search_knowledge": "检索知识库",
        "get_product_detail": "读取产品详情",
        "propose_update_product_field": "生成修改确认动作",
        "propose_delete_product_info": "生成删除信息确认动作",
        "propose_delete_product": "生成删除产品确认动作",
    }
    count = result.get("count")
    if count is None:
        count = len(result.get("actions") or ([] if not result.get("action") else [result.get("action")]))
    detail = f"参数：{json.dumps(arguments, ensure_ascii=False, default=str)}"
    if count is not None:
        detail += f"；结果：{count} 条"
    return {
        "type": name,
        "label": labels.get(name, name),
        "detail": detail,
        "ok": bool(result.get("ok", True)),
    }


# Clean overrides for compare/context helpers whose older literals became mojibake.
COMPARE_LIKE_TERMS = (
    "对比",
    "比较",
    "区别",
    "差异",
    "是否一样",
    "哪个更",
    "差多少",
    "不同",
    "分别介绍",
    "各自介绍",
)


def _is_compare_like_question(
    question: str,
    *,
    candidate_skus: list[str] | None = None,
    context_skus: list[str] | None = None,
) -> bool:
    text = str(question or "")
    if (
        any(term in text for term in ("\u7b2c\u4e00\u4e2a", "\u7b2c\u4e8c\u4e2a", "\u7b2c\u4e00\u6b3e", "\u7b2c\u4e8c\u6b3e"))
        and any(term in text for term in ("\u6bd4", "\u66f4"))
        and any(term in text for term in ("\u8f7b", "\u91cd", "\u91cd\u91cf"))
    ):
        return len(_unique_skus(context_skus or [])) >= 2 or len(_unique_skus(candidate_skus or [])) >= 2
    if not any(word in text for word in COMPARE_LIKE_TERMS):
        return False
    explicit_skus = _unique_skus(COMPARE_SKU_RE.findall(text))
    if len(explicit_skus) >= 2:
        return True
    if len(_unique_skus(candidate_skus or [])) >= 2:
        return True
    if len(_unique_skus(context_skus or [])) >= 2 and _references_context_compare_targets(text):
        return True
    intent = customer_agent_intent_service.parse_intent(question, previous_result_skus=[])
    return bool(
        intent
        and getattr(intent, "intent", "") == "compare_products"
        and len(_unique_skus(getattr(intent, "target_skus", []) or [])) >= 2
    )


def _ordinal_skus_from_entity_stack(question: str, entity_stack: list[dict]) -> list[str]:
    if not entity_stack:
        return []
    text = str(question or "")
    if not any(term in text for term in ("最开始", "第一个", "第一款", "最后一个", "最后一款", "最后那个", "上一个", "第二个", "第三个", "第四个", "第")):
        return []
    if any(term in text for term in ("最后一个问的", "最后问的那个", "最后一个问过的", "最后问过的那个")):
        latest = _latest_entity_skus_from_stack(entity_stack, limit=1)
        if latest:
            return latest
    # Resolve ordinals against conversation chronology, not raw recency order.
    # `_latest_entity_stack` is built from newest assistant message backwards, so
    # "最后一个问的" should map to the last product the user asked about in time,
    # not the last item in that reverse-recency stack.
    ordered = _entity_stack_by_conversation_order(entity_stack)
    if not ordered:
        return []
    if any(term in text for term in ("最后一个", "最后一款", "最后那个", "上一个")):
        return [ordered[-1]["sku"]]
    if any(term in text for term in ("最开始", "第一个", "第一款")):
        return [ordered[0]["sku"]]
    match = re.search(r"第\s*(\d+|[一二三四五六七八九十两])\s*(?:个|款|套|只|把|口)?", text)
    if not match:
        return []
    index = _chinese_ordinal_to_int(match.group(1))
    if index <= 0 or index > len(ordered):
        return []
    return [ordered[index - 1]["sku"]]


def _category_reference_skus_from_entity_stack(question: str, entity_stack: list[dict]) -> list[str]:
    if not entity_stack:
        return []
    text = str(question or "")
    if not any(term in text for term in ("刚才", "之前", "前面", "上次")):
        return []
    type_terms = ("酒精炉", "气炉", "炉", "套锅", "炒锅", "煎锅", "单锅", "锅", "杯套装", "杯", "水壶", "壶", "锅具")
    requested = [term for term in type_terms if term in text]
    if not requested:
        return []
    ordered = _entity_stack_by_conversation_order(entity_stack)
    for term in requested:
        for entity in reversed(ordered):
            name = str(entity.get("name") or "")
            sku = str(entity.get("sku") or "").strip().upper()
            if sku and (term in name or (term == "炉" and "炉" in name) or (term == "锅" and "锅" in name)):
                return [sku]
    return []


def _entity_stack_by_conversation_order(entity_stack: list[dict]) -> list[dict]:
    deduped: dict[str, dict] = {}
    for entity in entity_stack:
        sku = str(entity.get("sku") or "").strip().upper()
        if not sku or sku in deduped:
            continue
        item = dict(entity)
        item["sku"] = sku
        deduped[sku] = item
    return sorted(
        deduped.values(),
        key=lambda item: int(item.get("turn") if item.get("turn") is not None else 0),
        reverse=True,
    )


def _chinese_ordinal_to_int(value: str) -> int:
    text = str(value or "").strip()
    if text.isdigit():
        return int(text)
    mapping = {"一": 1, "二": 2, "两": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9, "十": 10}
    if text in mapping:
        return mapping[text]
    if text.startswith("十") and len(text) == 2:
        return 10 + mapping.get(text[1], 0)
    if len(text) == 3 and text[1] == "十":
        return mapping.get(text[0], 0) * 10 + mapping.get(text[2], 0)
    return 0


def _should_defer_explicit_product_to_intent_pipeline(question: str, detected_skus: list[str]) -> bool:
    text = str(question or "")
    skus = [str(sku or "").strip().upper() for sku in detected_skus if str(sku or "").strip()]
    if not text or not skus:
        return False
    if len(skus) >= 2 and (
        _is_compare_like_question(text, candidate_skus=skus)
        or any(term in text for term in ("分别介绍", "分别说说", "各自介绍"))
    ):
        return True
    if len(skus) == 1 and any(
        term in text
        for term in (
            "适合哪些人群",
            "适用人群",
            "爆炒",
            "耐摔",
            "单独用",
            "单独使用",
            "有没有手柄",
            "锅盖",
            "盖子",
        )
    ):
        return True
    return False
