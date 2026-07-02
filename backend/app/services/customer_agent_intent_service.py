import json
import re
from dataclasses import dataclass, field
from time import perf_counter
from typing import Any

from sqlalchemy.orm import Session

from ..models.product import Product
from ..models.product_business import ProductBusiness
from ..models.product_content import ProductContent
from ..models.product_qa import ProductQa
from ..models.product_specs import ProductSpecs
from ..internal.experience_layer.implicit_intent import infer_secondary_intents
from ..internal.experience_layer.query_rewrite import build_retrieval_query
from . import agent_action_service, customer_agent_service, customer_agent_tool_service, customer_cache_service, customer_llm_service, customer_perf_service, customer_recommendation_ranker, knowledge_service, product_service


CONTEXT_WORDS = (
    "他", "它", "这个", "这款", "该产品", "这个产品", "这产品", "这些", "那些", "刚才那些", "上面这些", "刚才的", "刚才说的",
    "上一轮", "之前", "前面", "最开始", "第一个", "第一款", "上一个", "这一批", "这批", "这几个", "那几个", "里面",
)
ORDINAL_CONTEXT_PATTERNS = tuple(
    re.compile(pattern)
    for pattern in (
        r"(?:刚才|上面|前面)?最后(?:一个|一款|那个|那款|的)",
        r"(?:刚才|上面|前面)?最后推荐的",
    )
)
QUESTION_WORDS = ("哪些", "有哪些", "多少", "分别", "列出", "查询", "找", "是什么")
COMPARE_WORDS = ("对比", "比较", "区别", "差异", "分别")
RECOMMEND_WORDS = ("推荐", "更适合", "最适合", "最合适", "合适", "哪个好", "哪款", "哪款更好", "优先", "比较轻", "比较小", "最轻", "最小", "带什么", "带哪个", "选哪个", "买哪个")
FOLLOWUP_NARROW_WORDS = ("排除", "不要", "去掉", "剔除", "排掉")
PLACEHOLDER_WORDS = {"tbd", "todo", "test", "null", "none", "n/a", "na", "-", "--", "unknown"}
PART_WORDS = ("主体", "配件", "手柄", "锅体", "盖子", "锅盖", "把手", "煎盘", "炉体", "炉架", "壶身", "壶嘴", "杯身", "杯盖")
USAGE_CARE_TERMS = (
    "清洗",
    "保养",
    "护理",
    "清洁",
    "洗完",
    "怎么洗",
    "怎么清洗",
    "怎么保养",
    "怎么护理",
    "怎么处理",
    "咋办",
    "不好洗",
    "洗碗机",
    "收拾",
    "擦干",
    "烘干",
    "泡水",
    "浸泡",
    "冷水",
    "冷水冲",
    "热锅骤冷",
    "骤冷骤热",
    "洗洁精",
    "钢丝球",
    "硬刷",
    "硬物",
    "刮擦",
    "水垢",
    "积碳",
    "异味",
    "第一次使用",
    "首次使用",
    "用完",
    "使用后",
    "收纳前",
    "不好清洗",
    "糊锅",
    "烧糊",
    "糊了",
    "焦",
    "粘锅",
    "不粘",
    "不沾",
    "涂层",
)
USAGE_CARE_SCRIPT_TERMS = ("客服怎么回复", "怎么回复客户", "客户说")
USAGE_CARE_CLEANING_TERMS = ("清洗", "清洁", "怎么洗", "怎么清洗", "洗完", "冷水冲", "软刷", "温水", "擦干", "烘干", "钢丝球", "硬物刮擦")
USAGE_CARE_MAINTENANCE_TERMS = ("保养", "护理", "养护", "存放", "晾干", "擦干", "烘干", "冷水", "骤冷骤热", "热锅骤冷")
USAGE_CARE_STICKING_TERMS = ("粘锅", "不好清洗", "不粘", "不沾", "防粘", "不易粘", "粘")
USAGE_CARE_BURNT_TERMS = ("糊锅", "锅糊", "烧糊", "烧焦", "焦糊")
USAGE_CARE_COATING_TERMS = ("涂层", "不粘涂层", "防粘涂层")
USAGE_CARE_REPLY_TERMS = ("客服怎么回复", "怎么回复客户", "客户说", "用户说")
USAGE_CARE_AFTERSALES_TERMS = ("质保", "保修", "售后", "退换", "退货", "换货", "售后电话", "联系方式")
USAGE_CARE_SAFETY_TERMS = ("安全", "危险", "中毒", "火灾", "帐篷", "密闭", "一氧化碳", "爆炸")
USAGE_CARE_GENERAL_TERMS = ("卖点", "介绍", "品牌", "官方", "旗舰店")
USAGE_CARE_MAINTENANCE_ACTION_TERMS = ("清洗", "保养", "擦干", "烘干", "存放", "钢丝球", "硬物刮擦", "浸泡", "骤冷骤热", "涂层", "使用后")
USAGE_CARE_MAINTENANCE_WEAK_TERMS = ("能用多久", "使用多年", "耐用", "越用越顺手")
USAGE_CARE_BURNT_ACTION_TERMS = ("糊锅", "烧焦", "焦糊", "粘底", "残渍", "锅底", "清洗", "浸泡", "软刷", "钢丝球", "不粘涂层", "涂层保护")
USAGE_CARE_COOKWARE_TERMS = ("锅", "锅具", "不粘锅", "涂层锅", "烤盘", "煎盘", "套锅", "炒锅")
USAGE_CARE_NON_COOKWARE_TERMS = ("杯", "水杯", "保温杯", "户外杯", "壶", "水壶")
WATER_CONTAINER_CAPABILITY_TERMS = ("装冷水", "装凉水", "装热水", "装饮用水", "装水", "盛冷水", "盛热水", "盛水")
WATER_CONTAINER_CAPABILITY_EXCLUDE_TERMS = ("冲洗", "冷水冲", "洗完", "清洗", "怎么洗", "怎么清洗", "保养", "护理", "骤冷骤热", "热锅骤冷", "刚烧热")
FAQ_PURCHASE_TERMS = ("哪里买", "哪儿买", "在哪买", "在哪里买", "可以买到", "购买渠道", "购买链接", "怎么买", "想买", "去哪里", "小程序", "商城", "官方店", "店铺", "店铺入口", "旗舰店", "淘宝", "天猫", "京东", "拼多多", "亚马逊", "Amazon", "amazon", "独立站", "线下", "速卖通", "eBay", "ebay", "阿里国际站", "官方渠道", "哪个平台", "平台可以买", "B2C", "b2c", "下单")
FAQ_AFTERSALES_TERMS = ("售后", "退换", "退货", "换货", "售后电话", "联系方式", "人工客服", "发票", "开发票", "物流", "快递", "订单", "发错货", "少发", "补寄", "维修", "七天无理由", "买错", "不喜欢")
FAQ_AFTERSALES_PROBLEM_TERMS = ("问题", "质量", "坏了", "瑕疵", "破损")
FAQ_AFTERSALES_HELP_TERMS = ("怎么办", "咋办", "怎么处理", "找谁", "谁处理", "联系谁")


def _is_placeholder_value(value: str) -> bool:
    """Check if a value looks like a placeholder (all ? or in PLACEHOLDER_WORDS)."""
    stripped = (value or "").strip()
    if not stripped:
        return False
    if stripped.lower() in PLACEHOLDER_WORDS:
        return True
    # All question marks (with optional spaces) is a placeholder
    if re.fullmatch(r"[??]+", stripped.replace(" ", "")):
        return True
    return False
SUSPICIOUS_CAPACITY_WORDS = {"锅", "壶", "杯", "盘", "碗", "套装", "产品", "露营"}


@dataclass
class CustomerIntent:
    intent: str
    filters: dict[str, Any] = field(default_factory=dict)
    negative_filters: dict[str, Any] = field(default_factory=dict)
    semantic_query: str = ""
    target_skus: list[str] = field(default_factory=list)
    requested_fields: list[str] = field(default_factory=list)
    clarification_question: str = ""
    special_filter: str = ""
    exact_value: str = ""
    term: str = ""
    recommendation_query: str = ""
    source_context: str = "question"
    is_single_field_sufficient: bool = True

    def as_dict(self) -> dict[str, Any]:
        return {
            "intent": self.intent,
            "filters": self.filters,
            "negative_filters": self.negative_filters,
            "semantic_query": self.semantic_query,
            "target_skus": self.target_skus,
            "requested_fields": self.requested_fields,
            "clarification_question": self.clarification_question,
            "special_filter": self.special_filter,
            "exact_value": self.exact_value,
            "term": self.term,
            "recommendation_query": self.recommendation_query,
            "source_context": self.source_context,
            "is_single_field_sufficient": self.is_single_field_sufficient,
        }


async def process_intent_request(
    db: Session,
    *,
    user_id: str,
    question: str,
    sku: str | None = None,
    previous_result_skus: list[str] | None = None,
    allow_llm_fallback: bool = True,
    scoped_comparison_candidates: bool = False,
) -> dict | None:
    request_start = perf_counter()
    previous_result_skus = previous_result_skus or []
    # don't poison the intent parser with old SKUs
    # don't poison the intent parser with old SKUs
    # If there are previous SKUs and the question doesn't reference them, clear them
    if (
        previous_result_skus
        and not scoped_comparison_candidates
        and not _has_context_reference(question)
        and not _is_recommendation_change_followup_text(question)
    ):
        # Question does NOT use words like "??""??""??" - it''s a fresh topic
        # Clear previous SKUs to avoid context poisoning
        previous_result_skus = []
    # Try regex parser first - it's fast and accurate for structured queries
    intent = parse_intent(question, sku=sku, previous_result_skus=previous_result_skus)
    # Only use LLM if regex parser failed or returned clarify
    if allow_llm_fallback and (not intent or intent.intent == "clarify"):
        llm_start = perf_counter()
        llm_intent = await _llm_parse_intent(db, question, sku=sku, previous_result_skus=previous_result_skus)
        customer_perf_service.log_stage("process_intent_request.llm_fallback", llm_start, hit=bool(llm_intent), intent=llm_intent.intent if llm_intent else None, fallback_used=bool(llm_intent and llm_intent.intent != "clarify"))
        if llm_intent and llm_intent.intent != "clarify":
            intent = llm_intent
            # Enrich LLM intent with regex filters if regex had something
            regex_backup = parse_intent(question, sku=sku, previous_result_skus=[])
            if regex_backup and regex_backup.intent == intent.intent:
                for k, v in (regex_backup.filters or {}).items():
                    if k not in (intent.filters or {}):
                        intent.filters[k] = v
                if not intent.semantic_query and regex_backup.semantic_query:
                    intent.semantic_query = regex_backup.semantic_query
                if not intent.term and regex_backup.term:
                    intent.term = regex_backup.term
                for f in (regex_backup.requested_fields or []):
                    if f not in (intent.requested_fields or []):
                        intent.requested_fields.append(f)
    if intent:
        intent = _sanitize_intent(intent)
        if scoped_comparison_candidates and intent.intent == "recommend_products" and previous_result_skus:
            intent.target_skus = [
                str(item or "").strip().upper()
                for item in previous_result_skus
                if str(item or "").strip()
            ]
            intent.source_context = "previous_results"
        experience_hints = infer_secondary_intents(question, primary_intent=intent.intent)
        if experience_hints.get("secondary_intents"):
            customer_perf_service.log_stage(
                "process_intent_request.experience_hints",
                request_start,
                primary_intent=intent.intent,
                secondary_intents=experience_hints.get("secondary_intents"),
            )
    if not intent and allow_llm_fallback:
        # Last resort: try LLM with no extra context
        llm_start = perf_counter()
        llm_intent = await _llm_parse_intent(db, question, sku=sku, previous_result_skus=[])
        customer_perf_service.log_stage("process_intent_request.llm_last_resort", llm_start, hit=bool(llm_intent), intent=llm_intent.intent if llm_intent else None)
        if llm_intent:
            intent = _sanitize_intent(llm_intent)
    if not intent:
        return None
    if _should_defer_ordinal_context_to_runtime(question, intent, previous_result_skus):
        return None

    fuzzy_people_cookware_subject = _fuzzy_people_cookware_subject(question)
    if fuzzy_people_cookware_subject and any(marker in question for marker in ("主体材质", "材质", "材料")):
        fuzzy_rows = customer_agent_service.search_products(db, fuzzy_people_cookware_subject, limit=5, filters={})
        if fuzzy_rows:
            exact_name_rows = [
                row for row in fuzzy_rows
                if fuzzy_people_cookware_subject
                in customer_agent_service.normalize_search_text(
                    row.get("product_name_cn") or row.get("product_name_en") or ""
                )
            ]
            selected_row = (exact_name_rows or fuzzy_rows)[0]
            selected_sku = str(selected_row.get("sku") or "").strip().upper()
            if selected_sku:
                return await _product_detail_result(
                    db,
                    CustomerIntent(
                        intent="product_detail",
                        target_skus=[selected_sku],
                        requested_fields=["材质"],
                        term=fuzzy_people_cookware_subject,
                        semantic_query="",
                        source_context="question",
                        is_single_field_sufficient=True,
                    ),
                    original_question=question,
                )

    explicit_named_products = _explicit_products_from_question(db, question)
    if (
        len(explicit_named_products) > 1
        and _looks_like_multi_product_relation_question(question)
        and intent.intent != "compare_products"
    ):
        intent = CustomerIntent(
            intent="compare_products",
            target_skus=[product.sku for product in explicit_named_products[:5] if getattr(product, "sku", None)],
            requested_fields=intent.requested_fields,
            semantic_query=question,
            source_context="question",
            is_single_field_sufficient=False,
        )
    if (
        _looks_like_usage_care_question(question)
        and not _looks_like_usage_care_aftersales_question(question)
        and not _looks_like_product_detail_question(question)
    ):
        usage_care_result = await answer_product_usage_care_request(
            db,
            question=question,
            named_products=explicit_named_products,
        )
        if usage_care_result:
            return usage_care_result

    if _looks_like_customer_faq_question(question):
        return None

    # Final safety: if intent is still clarify but regex has concrete search params, override
    if intent.intent == "clarify":
        regex_final = parse_intent(question, sku=sku, previous_result_skus=[])
        if regex_final and regex_final.intent in ("query_products", "recommend_products") and (regex_final.filters or regex_final.term or regex_final.semantic_query):
            intent = regex_final
    if intent.intent == "clarify":
        return await attach_supporting_knowledge_evidence(db, _clarify_result(intent), question)
    compatibility_result = await _explicit_product_compatibility_result(db, question)
    if compatibility_result:
        return compatibility_result
    if intent.intent == "product_usage_care":
        return await answer_product_usage_care_request(db, question=question)
    if intent.intent == "product_detail":
        return await _product_detail_result(db, intent, original_question=question)
    if intent.intent == "compare_products":
        return await _compare_result(db, intent, question)
    if intent.intent == "recommend_products" and intent.target_skus and intent.requested_fields:
        intent.intent = "product_detail"
        return await _product_detail_result(db, intent, original_question=question)
    if intent.intent == "recommend_products":
        return await _recommend_result(
            db,
            user_id,
            intent,
            scoped_comparison_candidates=scoped_comparison_candidates,
        )
    if intent.intent == "propose_delete":
        return await _propose_delete_result(db, user_id, intent)
    if intent.intent == "propose_update":
        return await _propose_update_result(db, user_id, intent)
    if intent.intent == "query_products" and intent.target_skus and intent.requested_fields and len(intent.target_skus) == 1:
        return await _product_detail_result(db, intent, original_question=question)
    if intent.intent == "query_products":
        return await _query_products_result(db, user_id, intent, original_question=question)
    return None


async def answer_product_usage_care_request(
    db: Session,
    *,
    question: str,
    named_products: list[Product] | None = None,
) -> dict | None:
    text = str(question or "").strip()
    named_products = named_products or []
    if not _looks_like_usage_care_question(text):
        return None
    if _looks_like_water_container_capability_question(text):
        return None
    if _looks_like_product_detail_question(text) and not named_products:
        return None
    request_start = perf_counter()
    usage_subtype = _detect_usage_care_subtype(text)
    intent = CustomerIntent(
        intent="product_usage_care",
        term=text,
        semantic_query=text,
        target_skus=[product.sku for product in named_products[:3] if getattr(product, "sku", None)],
        source_context="question",
        is_single_field_sufficient=False,
    )
    response_style = "customer_service_script" if usage_subtype == "customer_reply" else "usage_guidance"
    qa_hits, knowledge_hits, search_debug = await _search_usage_care_qa(db, text, intent.target_skus, usage_subtype=usage_subtype)
    compose_start = perf_counter()
    if not qa_hits and not knowledge_hits:
        if usage_subtype == "burnt":
            answer = "\n".join([
                "清洁方法：目前没有专门糊锅资料，可先用温水和软刷轻刷处理。",
                "注意事项：如果是涂层锅，先避免强力刮擦。",
                "避免事项：不要用钢丝球硬刮，避免伤涂层。",
            ])
        else:
            answer = "系统暂未配置对应清洗/保养资料，建议联系人工客服确认。"
        compose_answer_ms = customer_perf_service.perf_ms(compose_start)
        total_ms = customer_perf_service.perf_ms(request_start)
        return _build_response(
            intent=intent,
            answer=answer,
            sku=intent.target_skus[0] if len(intent.target_skus) == 1 else None,
            sources=[{"type": "usage_care_knowledge", "label": "使用/清洗保养检索", "count": 0}],
            results=[],
            steps=_steps(intent, [{"type": "usage_care_search", "label": "检索使用/清洗保养资料", "detail": "未命中 QA 或知识库", "ok": True}]),
            confidence="low",
            warnings=["usage_care_data_missing"],
            anomalies=[],
            suggested_followups=["如果你能提供具体 SKU 或产品名，我可以继续按单品资料重查。"],
            answer_type="product_usage_care",
            debug={
                "intent": intent.as_dict(),
                "steps": _steps(intent, [{"type": "usage_care_search", "label": "检索使用/清洗保养资料", "detail": "未命中 QA 或知识库", "ok": True}]),
                "warnings": ["usage_care_data_missing"],
                "anomalies": [],
                "raw_results": [],
                "agent_mode": "product_usage_care_fast_path",
                "usage_care_subtype": usage_subtype,
                "response_style": response_style,
                "qa_result_count": 0,
                "knowledge_result_count": 0,
                "product_qa_ms": search_debug["product_qa_ms"],
                "knowledge_search_ms": search_debug["knowledge_search_ms"],
                "rerank_ms": search_debug["rerank_ms"],
                "compose_answer_ms": round(compose_answer_ms, 2),
                "total_ms": round(total_ms, 2),
                "filtered_or_downgraded": search_debug["filtered_or_downgraded"],
                "final_used_sources_count": 0,
            },
        )

    raw_used_sources_text = _usage_care_debug_source_texts(qa_hits, knowledge_hits)
    answer_before_clean = _compose_usage_care_answer(text, qa_hits, knowledge_hits, response_style=response_style)
    answer_after_clean = _sanitize_usage_care_answer_text(answer_before_clean)
    answer = answer_after_clean
    compose_answer_ms = customer_perf_service.perf_ms(compose_start)
    results = _usage_care_results_for_response(qa_hits, knowledge_hits)
    sources: list[dict] = []
    if qa_hits:
        sources.append({"type": "product_qa", "label": "产品 QA", "count": len(qa_hits), "skus": sorted({item.get('sku') for item in qa_hits if item.get('sku')})})
    if knowledge_hits:
        sources.append({"type": "usage_care_knowledge", "label": "使用/清洗保养知识库", "count": len(knowledge_hits), "skus": sorted({item.get('sku') for item in knowledge_hits if item.get('sku')})})
    steps = _steps(intent, [{"type": "usage_care_search", "label": "检索使用/清洗保养资料", "detail": f"命中 QA {len(qa_hits)} 条，知识库 {len(knowledge_hits)} 条", "ok": True}])
    total_ms = customer_perf_service.perf_ms(request_start)
    response = _build_response(
        intent=intent,
        answer=answer,
        sku=intent.target_skus[0] if len(intent.target_skus) == 1 else None,
        sources=sources,
        results=results,
        steps=steps,
        confidence="high" if qa_hits else "medium",
        warnings=[],
        anomalies=[],
        suggested_followups=["如果你告诉我具体 SKU，我可以再按该产品说明补充更精确的使用建议。"],
        answer_type="product_usage_care",
        debug={
            "intent": intent.as_dict(),
            "steps": steps,
            "warnings": [],
            "anomalies": [],
            "raw_results": results,
            "agent_mode": "product_usage_care_fast_path",
            "usage_care_subtype": usage_subtype,
            "response_style": response_style,
            "qa_result_count": len(qa_hits),
            "knowledge_result_count": len(knowledge_hits),
            "raw_used_sources_text": raw_used_sources_text,
            "answer_before_usage_care_clean": answer_before_clean,
            "answer_after_usage_care_clean": answer_after_clean,
            "final_answer_before_sse": answer_after_clean,
            "final_answer_after_sse_clean": answer_after_clean,
            "product_qa_ms": search_debug["product_qa_ms"],
            "knowledge_search_ms": search_debug["knowledge_search_ms"],
            "rerank_ms": search_debug["rerank_ms"],
            "compose_answer_ms": round(compose_answer_ms, 2),
            "total_ms": round(total_ms, 2),
            "filtered_or_downgraded": search_debug["filtered_or_downgraded"],
            "final_used_sources_count": len(qa_hits) + len(knowledge_hits),
        },
    )
    return response



async def _llm_parse_intent(
    db: Session,
    question: str,
    *,
    sku: str | None = None,
    previous_result_skus: list[str] | None = None,
) -> CustomerIntent | None:
    """Use LLM to parse natural language into structured CustomerIntent."""
    previous_result_skus = previous_result_skus or []
    text = customer_agent_service.normalize_search_text(re.sub(r"\s+", " ", (question or "").strip()))
    if not text:
        return None

    sys_prompt = _build_intent_llm_prompt(sku, previous_result_skus)
    try:
        content = await customer_llm_service.chat_completion(
            db,
            messages=[
                {"role": "system", "content": sys_prompt},
                {"role": "user", "content": text},
            ],
            temperature=0,
            max_tokens=600,
            purpose="intent_parse",
        )
    except Exception:
        return None

    data = _parse_llm_json(content)
    if not data:
        return None

    return _llm_data_to_intent(data, question, sku, previous_result_skus)


def _build_intent_llm_prompt(sku: str | None, previous_result_skus: list[str]) -> str:
    sku_info = f"; SKU={sku}" if sku else ""
    prev_info = f"; SKU=[{','.join(previous_result_skus[:20])}]" if previous_result_skus else ""
    return f"""Product knowledgebase intent parser. Output only JSON.

Current context:{sku_info}{prev_info}

Intents: query_products|product_detail|compare_products|recommend_products|propose_delete|propose_update|clarify

CRITICAL RULES:
- When user asks "X的容量/材质/卖点是什么" or "X有哪些参数/资料/字段信息" where X is a product name: use intent=query_products with term=X and requested_fields (the system will auto-format as a detail answer for few results).
- When user just mentions a product name without asking for specific fields (for example "行山单锅"): use intent=query_products with term=product_name.
- Only use product_detail when you have an exact SKU code (e.g., CW-C93) AND the question is about reading its fields.
- "这些/这款/刚才那些" + has prev SKUs -> target_skus=prev SKUs, source_context=previous_results
- "这些/这款" + no prev -> intent=clarify

Available filters (field path):
负责人/person_in_charge -> product.person_in_charge
类目/品类/分类/category -> product.category
品牌/brand -> product.brand
系列/series -> product.series
生命周期/状态/lifecycle_status -> product.lifecycle_status
品质/品质情况/坏损/quality_note -> product.quality_note
英文名/英文名称/product_name_en -> product.product_name_en
容量/capacity -> specs.capacity
材质/材料/body_material -> specs.body_material
颜色/色系/color -> specs.color
重量/毛重/gross_weight_g -> specs.gross_weight_g
热源/heat_source -> specs.heat_source
功率/power -> specs.power
卖点/top_selling_points -> business.top_selling_points
场景/usage_scenarios -> business.usage_scenarios
产品名/名称/product_name_cn -> product.product_name_cn

Special filters (special_filter):
- 英文名全是数字 -> english_name_numeric
- 英文名包含数字 -> english_name_contains_digit
- 英文名是X -> english_name_exact, exact_value=X

semantic_query: fuzzy scene needs like "适合露营" or "泡咖啡"
requested_fields: requested field Chinese names, e.g. ["容量","材质"]
term: keyword search term
is_single_field_sufficient: true only when one raw product field can fully answer the question; false for comparison, multi-field, safety/认证/能不能/是否/还有/呢 questions.

Output ONLY this JSON:
{{"intent":"","filters":{{}},"negative_filters":{{}},"semantic_query":"","target_skus":[],"requested_fields":[],"clarification_question":"","special_filter":"","exact_value":"","term":"","recommendation_query":"","source_context":"question","is_single_field_sufficient":false}}"""


def _parse_llm_json(content: str) -> dict | None:
    text = (content or "").strip()
    if not text:
        return None
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", text, flags=re.S)
        if not match:
            return None
        try:
            return json.loads(match.group(0))
        except json.JSONDecodeError:
            return None


def _llm_data_to_intent(
    data: dict,
    question: str,
    sku: str | None,
    previous_result_skus: list[str],
) -> CustomerIntent | None:
    intent = str(data.get("intent") or "").strip()
    valid = {"query_products", "product_detail", "compare_products", "recommend_products", "propose_delete", "propose_update", "clarify"}
    if intent not in valid:
        return None

    filters = data.get("filters") or {}
    if not isinstance(filters, dict):
        filters = {}
    negative_filters = data.get("negative_filters") or {}
    if not isinstance(negative_filters, dict):
        negative_filters = {}

    semantic_query = str(data.get("semantic_query") or "").strip()
    target_skus = data.get("target_skus") or []
    if isinstance(target_skus, str):
        target_skus = [target_skus]
    if not isinstance(target_skus, list):
        target_skus = []
    if not target_skus and sku and _has_context_reference(question):
        target_skus = [sku.strip().upper()]

    requested_fields = data.get("requested_fields") or []
    if isinstance(requested_fields, str):
        requested_fields = [requested_fields]
    if not isinstance(requested_fields, list):
        requested_fields = []

    return CustomerIntent(
        intent=intent,
        filters=filters,
        negative_filters=negative_filters,
        semantic_query=semantic_query,
        target_skus=target_skus,
        requested_fields=requested_fields,
        clarification_question=str(data.get("clarification_question") or "").strip(),
        special_filter=str(data.get("special_filter") or "").strip(),
        exact_value=str(data.get("exact_value") or "").strip(),
        term=str(data.get("term") or "").strip(),
        recommendation_query=str(data.get("recommendation_query") or "").strip(),
        source_context=str(data.get("source_context") or "question").strip(),
        is_single_field_sufficient=(
            bool(data.get("is_single_field_sufficient"))
            if "is_single_field_sufficient" in data
            else _is_single_field_sufficient(question, requested_fields, target_skus)
        ) and _is_single_field_sufficient(question, requested_fields, target_skus),
    )

def _sanitize_intent(intent: CustomerIntent) -> CustomerIntent | None:
    """Validate and fix the intent before execution. Catches LLM mistakes."""
    intent.requested_fields = [
        str(field).strip()
        for field in (intent.requested_fields or [])
        if str(field or "").strip() and str(field or "").strip().lower() != "none"
    ]
    # If target_skus exists but user asks about something else (term doesn't match any SKU), clear target_skus
    if intent.target_skus and intent.term and intent.source_context == "question":
        term_upper = intent.term.strip().upper()
        sku_set = {s.upper() for s in intent.target_skus}
        if term_upper not in sku_set and not any(s in term_upper for s in sku_set):
            # User is asking about a different product - don't poison with old SKU
            intent.target_skus = []
    # If product_detail with target_skus but also has term pointing to different product
    if intent.intent == "product_detail" and intent.target_skus and intent.term and intent.source_context == "question":
        term_upper = intent.term.strip().upper()
        # If there's a product name in term and target_skus are from context, convert to query
        has_chinese = bool(re.search(r'[一-鿿]', intent.term))
        if has_chinese and not any(s.upper() in term_upper for s in intent.target_skus):
            intent.intent = "query_products"
    # Keep product_detail for "product name + field question"; target SKU can be resolved later.
    # If query_products with only requested_fields (no filters, no term, no target_skus) -> clarify
    if intent.intent == "query_products" and intent.requested_fields and not intent.filters and not intent.term and not intent.target_skus and not intent.semantic_query:
        if not any(w in intent.clarification_question for w in ("SKU", "产品", "范围", "哪款")):
            intent.intent = "clarify"
            intent.clarification_question = "请告诉我要查询哪款产品，可以给 SKU、产品名，或先查询一批产品后再继续追问。"
    return intent
def parse_intent(question: str, *, sku: str | None = None, previous_result_skus: list[str] | None = None) -> CustomerIntent | None:
    text = re.sub(r"\s+", " ", (question or "").strip())
    if not text:
        return None
    previous_result_skus = previous_result_skus or []
    explicit_skus = _extract_skus(text)
    target_skus = explicit_skus or (([sku.strip().upper()] if sku else []) if _has_context_reference(text) else [])
    source_context = "question"

    if _has_context_reference(text):
        if explicit_skus:
            target_skus = explicit_skus
        elif previous_result_skus:
            target_skus = previous_result_skus
            source_context = "previous_results"
        else:
            return CustomerIntent(
                intent="clarify",
                clarification_question="你提到的“这些”目前没有可引用的上一轮结果。请先查一批产品，或者直接告诉我要处理的 SKU。",
            )

    quoted_subject = _quoted_subject_from_question(text)
    requested_fields = _requested_fields(text)

    update_intent = _parse_update_intent(text, target_skus)
    if update_intent:
        update_intent.source_context = source_context
        return update_intent
    if _is_delete_request(text):
        if not target_skus:
            return CustomerIntent(intent="clarify", clarification_question="请先告诉我要删除哪些 SKU，或先查询一批产品后再说“删除这些”。")
        return CustomerIntent(intent="propose_delete", target_skus=target_skus, source_context=source_context)

    english_name = _parse_english_name_filter(text)
    if english_name:
        english_name.target_skus = target_skus
        english_name.source_context = source_context
        return english_name

    filters, negative_filters = _parse_structured_filters(text)
    semantic_query = _parse_semantic_query(text)
    recommendation_query = _parse_recommendation_query(text, semantic_query)
    term = _parse_term(text, filters, semantic_query)
    fuzzy_people_cookware_subject = _fuzzy_people_cookware_subject(text)
    fallback_detail_subject = _detail_subject_from_question(text)
    prefixed_material_subject_match = re.search(
        r"(?:^|(?:帮我|麻烦|请|想|我想)(?:查一下|查下|看一下|看下|问一下|问下)?)(?P<subject>.+?)(?:的)?(?:主体|锅体|炉体)?(?:材质|材料)",
        text,
    )
    prefixed_material_subject = ""
    if prefixed_material_subject_match:
        prefixed_material_subject = prefixed_material_subject_match.group("subject").strip(" ，。？！；;")
    if not requested_fields and _looks_like_product_detail_question(text):
        requested_fields = _requested_fields_for_detail_question(text)
    if (
        fuzzy_people_cookware_subject
        and not target_skus
        and not filters
        and not negative_filters
        and any(marker in text for marker in ("主体材质", "材质", "材料"))
    ):
        return CustomerIntent(
            intent="product_detail",
            requested_fields=["材质"],
            term=fuzzy_people_cookware_subject,
            semantic_query="",
            source_context=source_context,
            is_single_field_sufficient=True,
        )
    if not requested_fields and prefixed_material_subject:
        requested_fields = ["材质"]
    if not requested_fields and fallback_detail_subject and any(marker in text for marker in ("主体材质", "材质", "材料")):
        requested_fields = ["材质"]
    if prefixed_material_subject and requested_fields and (not term or len(prefixed_material_subject) < len(term)):
        term = prefixed_material_subject
    if fallback_detail_subject and requested_fields and not quoted_subject and (not term or len(fallback_detail_subject) < len(term)):
        term = fallback_detail_subject
    if filters and not target_skus and _is_multi_product_filter_query(text, term):
        term = ""
        fallback_detail_subject = ""
    if not recommendation_query and _looks_like_recommendation_question(text):
        recommendation_query = semantic_query or text
    if recommendation_query and not semantic_query:
        semantic_query = recommendation_query
    locked_subject = quoted_subject or term or fallback_detail_subject
    if locked_subject and requested_fields:
        filtered_fields = _filter_requested_fields_outside_subject(text, locked_subject, requested_fields)
        if filtered_fields:
            requested_fields = filtered_fields
    if quoted_subject and requested_fields and not target_skus and not _is_multi_product_detail_question(text):
        return CustomerIntent(
            intent="product_detail",
            requested_fields=requested_fields,
            term=quoted_subject,
            semantic_query=text if _is_material_safety_question(text) else semantic_query,
            source_context=source_context,
            is_single_field_sufficient=_is_single_field_sufficient(text, requested_fields, target_skus),
        )
    if not term and requested_fields and not filters:
        term = fallback_detail_subject

    if previous_result_skus and not target_skus and negative_filters and any(word in text for word in FOLLOWUP_NARROW_WORDS):
        target_skus = previous_result_skus
        source_context = "previous_results"

    is_compare = _is_compare_question(text)
    if len(target_skus) > 1 and (
        is_compare
        or _looks_like_multi_sku_intro_question(text)
        or _looks_like_multi_product_relation_question(text)
    ):
        return CustomerIntent(
            intent="compare_products",
            target_skus=target_skus,
            requested_fields=requested_fields,
            source_context=source_context,
            is_single_field_sufficient=False,
        )

    named_detail_term = fallback_detail_subject if requested_fields and fallback_detail_subject else ""
    if (
        filters
        and not target_skus
        and not negative_filters
        and _looks_like_recommendation_question(text)
        and _filters_only_define_recommendation_scope(filters)
        and not requested_fields
    ):
        return CustomerIntent(
            intent="recommend_products",
            filters=filters,
            negative_filters=negative_filters,
            semantic_query=semantic_query,
            requested_fields=requested_fields,
            term=term,
            target_skus=target_skus,
            recommendation_query=recommendation_query or semantic_query or text,
            source_context=source_context,
            is_single_field_sufficient=False,
        )

    if previous_result_skus and _is_recommendation_change_followup_text(text):
        return CustomerIntent(
            intent="recommend_products",
            filters=filters,
            negative_filters=negative_filters,
            semantic_query=semantic_query or text,
            target_skus=[str(item or "").strip().upper() for item in previous_result_skus if str(item or "").strip()],
            requested_fields=requested_fields,
            term="",
            recommendation_query=recommendation_query or semantic_query or text,
            source_context="previous_results",
            is_single_field_sufficient=False,
        )

    if filters and not target_skus and not negative_filters and (
        not named_detail_term
        or _is_multi_product_filter_query(text, named_detail_term)
    ):
        return CustomerIntent(
            intent="query_products",
            filters=filters,
            negative_filters=negative_filters,
            semantic_query="",
            requested_fields=requested_fields,
            term="",
            target_skus=target_skus,
            source_context=source_context,
            is_single_field_sufficient=False,
        )
    if named_detail_term and not term:
        term = named_detail_term

    if _looks_like_large_group_cookware_recommendation(text):
        return CustomerIntent(
            intent="recommend_products",
            filters=filters,
            negative_filters=negative_filters,
            semantic_query=semantic_query or text,
            target_skus=target_skus,
            requested_fields=requested_fields,
            term="",
            recommendation_query=recommendation_query or semantic_query or text,
            source_context=source_context,
            is_single_field_sufficient=False,
        )

    if target_skus and filters:
        if requested_fields and len(target_skus) == 1 and explicit_skus:
            return CustomerIntent(
                intent="product_detail",
                target_skus=target_skus,
                requested_fields=requested_fields,
                term="",
                semantic_query=text if _is_material_safety_question(text) else "",
                source_context=source_context,
                is_single_field_sufficient=_is_single_field_sufficient(text, requested_fields, target_skus),
            )
        return CustomerIntent(
            intent="query_products",
            target_skus=target_skus,
            filters=filters,
            negative_filters=negative_filters,
            semantic_query=semantic_query,
            requested_fields=requested_fields,
            term=term,
            source_context=source_context,
            is_single_field_sufficient=False,
        )

    if target_skus and requested_fields:
        return CustomerIntent(
            intent="product_detail",
            target_skus=target_skus,
            requested_fields=requested_fields,
            semantic_query=text if (len(requested_fields) > 1 or _is_material_safety_question(text)) else "",
            source_context=source_context,
            is_single_field_sufficient=_is_single_field_sufficient(text, requested_fields, target_skus),
        )

    if _looks_like_recommendation_question(text):
        return CustomerIntent(
            intent="recommend_products",
            filters=filters,
            negative_filters=negative_filters,
            semantic_query=semantic_query,
            target_skus=target_skus,
            requested_fields=requested_fields,
            term=term,
            recommendation_query=recommendation_query or semantic_query or text,
            source_context=source_context,
            is_single_field_sufficient=False,
        )

    if target_skus and negative_filters and any(word in text for word in FOLLOWUP_NARROW_WORDS):
        return CustomerIntent(
            intent="query_products",
            target_skus=target_skus,
            filters=filters,
            negative_filters=negative_filters,
            semantic_query=semantic_query,
            requested_fields=requested_fields,
            term=term,
            source_context=source_context,
            is_single_field_sufficient=_is_single_field_sufficient(text, requested_fields, target_skus),
        )

    if term and requested_fields and not filters and not negative_filters and "卖点" not in requested_fields:
        return CustomerIntent(
            intent="product_detail",
            requested_fields=requested_fields,
            term=term,
            semantic_query=text if _is_material_safety_question(text) else semantic_query,
            source_context=source_context,
            is_single_field_sufficient=_is_single_field_sufficient(text, requested_fields, target_skus),
        )
    if term and requested_fields == ["卖点"] and _is_product_selling_points_query(text) and not target_skus and not negative_filters:
        return CustomerIntent(
            intent="query_products",
            filters=filters,
            requested_fields=requested_fields,
            term=term,
            semantic_query=semantic_query,
            source_context=source_context,
            is_single_field_sufficient=False,
        )

    if requested_fields == ["卖点"] and _is_product_selling_points_query(text) and not target_skus and term and not negative_filters:
        return CustomerIntent(
            intent="query_products",
            filters=filters,
            requested_fields=requested_fields,
            term=term,
            semantic_query=semantic_query,
            source_context=source_context,
            is_single_field_sufficient=False,
        )

    if requested_fields and (target_skus or term or _looks_like_product_detail_question(text)):
        return CustomerIntent(
            intent="product_detail",
            requested_fields=requested_fields,
            target_skus=target_skus,
            term=term or fallback_detail_subject,
            semantic_query=text if _is_material_safety_question(text) else (semantic_query or text),
            source_context=source_context,
            is_single_field_sufficient=_is_single_field_sufficient(text, requested_fields, target_skus),
        )

    if _should_route_cooking_set_exclusion_to_recommendation(text):
        return CustomerIntent(
            intent="recommend_products",
            filters=filters,
            negative_filters=negative_filters,
            semantic_query=semantic_query or text,
            target_skus=target_skus,
            requested_fields=requested_fields,
            term=term,
            recommendation_query=recommendation_query or semantic_query or text,
            source_context=source_context,
            is_single_field_sufficient=False,
        )

    if filters or negative_filters or semantic_query or term or any(word in text for word in QUESTION_WORDS):
        return CustomerIntent(
            intent="query_products",
            filters=filters,
            negative_filters=negative_filters,
            semantic_query=semantic_query,
            requested_fields=requested_fields,
            term=term,
            target_skus=target_skus,
            source_context=source_context,
            is_single_field_sufficient=_is_single_field_sufficient(text, requested_fields, target_skus),
        )

    return None


def _is_compare_question(text: str) -> bool:
    return any(
        word in text
        for word in COMPARE_WORDS + ("一样", "不一样", "相同", "不同", "同一个产品", "同一款", "同款", "是不是同款", "是否同款", "是不是同一个产品", "是否同一个产品", "哪个更适合", "哪款更适合", "哪个更合适", "哪款更合适")
    )


def _is_product_selling_points_query(text: str) -> bool:
    value = str(text or "")
    return any(term in value for term in ("主要卖点", "核心卖点", "卖点", "亮点", "产品特点"))


def _looks_like_multi_product_relation_question(text: str) -> bool:
    value = str(text or "")
    if not value:
        return False
    relation_terms = ("关系", "什么关系", "是什么关系", "有何关系", "哪个包含哪个", "哪个是套装", "套装和单品", "组成关系")
    component_terms = ("包含", "组成", "套装", "单品")
    return any(term in value for term in relation_terms) or (
        any(term in value for term in component_terms)
        and len(_extract_skus(value)) >= 2
    )


def _looks_like_multi_sku_intro_question(text: str) -> bool:
    value = str(text or "")
    if len(_extract_skus(value)) < 2:
        return False
    return any(term in value for term in ("分别介绍", "分别说说", "分别讲讲", "各自介绍", "各自说说", "逐个介绍"))


def _is_recommendation_change_followup_text(text: str) -> bool:
    value = str(text or "")
    return any(
        term in value
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


def _should_defer_ordinal_context_to_runtime(
    question: str,
    intent: CustomerIntent,
    previous_result_skus: list[str] | None,
) -> bool:
    text = str(question or "")
    has_numeric_ordinal = bool(
        re.search(r"第\s*(?:\d+|[一二三四五六七八九十两])\s*(?:个|款|套|只|把|口)", text)
    )
    has_named_ordinal = any(
        term in text
        for term in ("最开始", "最早问", "第一个", "第一款", "最后一个", "最后一款", "最后那个", "上一个")
    )
    if not has_numeric_ordinal and not has_named_ordinal:
        return False
    if _extract_skus(text):
        return False
    if getattr(intent, "requested_fields", None):
        return True
    if has_named_ordinal:
        return len(previous_result_skus or []) <= 1
    if getattr(intent, "target_skus", None):
        return False
    return len(previous_result_skus or []) <= 1


def _looks_like_recommendation_question(text: str) -> bool:
    value = str(text or "")
    if not value:
        return False
    if _is_pure_copywriting_without_product_recommendation(value):
        return False
    if _is_long_prompt_cookware_purchase_choice_question(value):
        return True
    if _looks_like_numbered_people_cookware_recommendation(value):
        return True
    explicit_recommendation_terms = ("推荐", "哪款", "选什么", "用什么", "帮我选", "帮我挑", "合适", "适合")
    if any(term in value for term in FAQ_PURCHASE_TERMS) and not any(term in value for term in explicit_recommendation_terms):
        return False
    if any(word in value for word in RECOMMEND_WORDS):
        return True
    scenario_terms = ("适合", "徒步", "露营", "车露", "登山", "野餐", "野炊", "自驾", "背包客", "新手", "小白", "家庭", "多人", "两人", "2人", "三人", "四人", "一个人", "轻量", "轻便", "便携", "预算", "性价比", "煮饭", "煮面", "烧水", "煎烤", "火锅")
    product_terms = ("锅", "套锅", "单锅", "炉", "炉具", "酒精炉", "壶", "水壶", "餐具", "套装")
    choice_terms = ("用什么", "选什么", "哪款", "哪个", "有没有", "有什么适合", "有哪些适合", "帮我选", "帮我挑", "合适")
    cookware_terms = ("锅", "锅具", "单锅", "套锅")
    single_person_terms = ("一个人用", "一人用", "单人用", "1人用", "1-2人用", "1－2人用", "适合一个人", "适合一人", "适合单人")
    open_purchase_terms = ("想买", "买个", "买口", "推荐", "适合", "那种", "有没有", "帮我选", "帮我挑")
    if (
        not _extract_skus(value)
        and not _quoted_subject_from_question(value)
        and any(term in value for term in cookware_terms)
        and any(term in value for term in single_person_terms)
        and any(term in value for term in open_purchase_terms)
    ):
        return True
    if any(term in value for term in scenario_terms) and any(term in value for term in product_terms) and any(term in value for term in choice_terms):
        return True
    if any(term in value for term in scenario_terms) and "产品" in value and any(term in value for term in ("有哪些", "有哪", "找", "推荐")):
        return True
    if value.startswith("适合") and any(term in value for term in scenario_terms) and any(term in value for term in product_terms):
        return True
    return any(term in value for term in ("买什么", "有适合")) and any(term in value for term in scenario_terms) and any(term in value for term in product_terms)


def _looks_like_numbered_people_cookware_recommendation(text: str) -> bool:
    value = str(text or "")
    if not value:
        return False
    if "推荐" not in value and "帮我推荐" not in value:
        return False
    if not re.search(r"(推荐|帮我推荐)\s*[一二三四五六七八九十0-9几两多]?\s*(款|个)?", value):
        return False
    if not any(term in value for term in ("适合", "两个人", "2个人", "2人", "双人", "三个人", "3个人", "3人", "四个人", "4个人", "4人")):
        return False
    if not any(term in value for term in ("锅", "锅具", "套锅", "锅具套装", "炊具")):
        return False
    if any(term in value for term in ("列出", "哪些产品", "有哪些产品", "主体材质", "支持酒精炉的锅具")):
        return False
    return True


def _looks_like_large_group_cookware_recommendation(text: str) -> bool:
    value = str(text or "")
    if not value:
        return False
    if not any(term in value for term in ("锅", "锅具", "套锅")):
        return False
    if not any(term in value for term in ("4人以上", "多人", "家庭", "3-4人", "2-4人", "大容量")):
        return False
    if not any(term in value for term in ("推荐", "适合", "最适合", "合适", "哪款", "哪个", "选什么", "帮我选", "帮我挑", "有哪些", "有哪")):
        return False
    return True


def _filters_only_define_recommendation_scope(filters: dict[str, Any]) -> bool:
    allowed_scope_keys = {"product.category"}
    return bool(filters) and all(str(key) in allowed_scope_keys for key in (filters or {}).keys())


def _looks_like_product_detail_question(text: str) -> bool:
    value = str(text or "")
    if not value:
        return False
    if _looks_like_recommendation_question(value):
        return False
    product_hint = bool(_extract_skus(value) or _detail_subject_from_question(value))
    product_hint = product_hint or any(term in value for term in ("套锅", "单锅", "酒精炉", "小方锅", "炊墨", "行山", "旋焰", "烽宴", "CW-", "CS-", "TW-"))
    subject = _quoted_subject_from_question(value) or _detail_subject_from_question(value)
    field_text = _remove_subject_once(value, subject) if subject else value
    field_hint = bool(_requested_fields_for_detail_question(field_text))
    return product_hint and field_hint


def _looks_like_water_container_capability_question(text: str) -> bool:
    value = str(text or "").strip()
    if not value:
        return False
    if any(term in value for term in WATER_CONTAINER_CAPABILITY_EXCLUDE_TERMS):
        return False
    if not any(term in value for term in WATER_CONTAINER_CAPABILITY_TERMS):
        return False
    product_hint = bool(_extract_skus(value) or _detail_subject_from_question(value))
    if not product_hint:
        return False
    return any(term in value for term in ("能不能", "能否", "是否", "可以", "可不可以", "能装", "装"))


def _requested_fields_for_detail_question(text: str) -> list[str]:
    fields = _requested_fields(text)
    value = str(text or "")
    additions = [
        ("容量", ("几升", "多少升", "多大容量", "容量多少", "多大")),
        ("重量", ("多重", "净重", "毛重", "重不重", "重量多少")),
        ("材质", ("是什么材料", "什么材料", "是不是木头", "木头", "不锈钢", "304", "锅体", "手柄", "把手", "盖子", "锅盖")),
        ("适配情况", ("洗碗机", "能放进洗碗机", "能放洗碗机", "是否适合洗碗机")),
        ("表面处理", ("涂层", "不粘涂层", "有涂层", "不粘吗", "不沾吗")),
        ("卖点", ("是什么产品", "产品参数", "参数", "有什么特点")),
        ("适用场景", ("适合几个人", "适合几人", "几个人", "几人使用", "适合什么", "适合哪些人群", "适用人群")),
        ("颜色", ("颜色",)),
        ("热源", ("燃料", "用什么燃料", "热源", "酒精炉吗", "能用酒精炉", "支持酒精炉", "可以用酒精炉")),
        ("配件", ("几个锅", "几件", "包装里", "包装内", "配件", "包含什么")),
        ("功率", ("最大功率", "功率是多少", "火力多大")),
        ("认证", ("有哪些认证", "什么认证", "出口认证", "认证信息")),
    ]
    for label, aliases in additions:
        if any(alias in value for alias in aliases) and label not in fields:
            fields.append(label)
    if _looks_like_water_container_capability_question(value) and "适配情况" not in fields:
        fields.append("适配情况")
    return fields


def _filter_requested_fields_outside_subject(text: str, subject: str, requested_fields: list[str]) -> list[str]:
    remainder = _remove_subject_once(text, subject)
    if remainder == text:
        return requested_fields
    outside_fields = _requested_fields_for_detail_question(remainder)
    if not outside_fields:
        return requested_fields
    return [field for field in requested_fields if field in outside_fields]


def _is_single_field_sufficient(text: str, requested_fields: list[str], target_skus: list[str] | None = None) -> bool:
    if len(requested_fields or []) != 1:
        return False
    if target_skus and len(target_skus) > 1:
        return False
    if _is_compare_question(text):
        return False
    complex_terms = (
        "是否", "是不是", "能不能", "能否", "可以", "安全吗", "安全性", "食品级",
        "认证", "还有", "以及", "并且", "同时", "另外", "呢", "为什么", "怎么",
        "适合", "不粘", "不沾",
    )
    return not any(term in text for term in complex_terms + PART_WORDS)


async def _query_products_result(db: Session, user_id: str, intent: CustomerIntent, original_question: str = "") -> dict:
    warnings: list[str] = []
    # Use the original question for QA/KB search for better context
    search_question_text = (original_question or intent.term or intent.semantic_query or "").strip()
    source_rows_for_context_filter: list[dict] = []

    if intent.target_skus:
        source_rows_for_context_filter = _rows_for_target_skus(db, intent.target_skus)
        rows = source_rows_for_context_filter
        rows = _filter_rows(
            rows,
            filters=intent.filters,
            negative_filters=intent.negative_filters,
            term="" if intent.source_context == "previous_results" else intent.term,
        )
        tool_name = "filter_previous_results"
        query = intent.term or intent.semantic_query or "上下文结果筛选"
    elif intent.special_filter:
        rows = _run_special_product_filter(db, intent)
        tool_name = "search_products"
        query = intent.exact_value or intent.special_filter
    elif intent.semantic_query and intent.filters:
        try:
            tool_result = await customer_agent_tool_service.execute_tool_async(
                db,
                user_id=user_id,
                name="hybrid_search_products",
                arguments={
                    "term": intent.term,
                    "filters": intent.filters,
                    "semantic_query": intent.semantic_query,
                    "fields": intent.requested_fields,
                    "limit": 50,
                },
            )
            rows = tool_result.get("results") or []
            tool_name = tool_result.get("tool", "hybrid_search_products")
            query = tool_result.get("query") or intent.term or intent.semantic_query
        except Exception as exc:
            rows = customer_agent_service.search_products(db, intent.term, limit=50, filters=intent.filters)
            tool_name = "search_products"
            query = intent.term
            warnings.append(f"语义检索暂时不可用，已先按结构化条件查询：{exc}")
    else:
        tool_result = await customer_agent_tool_service.execute_tool_async(
            db,
            user_id=user_id,
            name="search_products",
            arguments={
                "term": intent.term or intent.semantic_query,
                "filters": intent.filters,
                "fields": intent.requested_fields,
                "limit": 50,
            },
        )
        rows = tool_result.get("results") or []
        tool_name = tool_result.get("tool", "search_products")
        query = tool_result.get("query") or intent.term or intent.semantic_query

    rows = _narrow_alcohol_stove_cookware_query_rows(
        db,
        rows,
        intent=intent,
        question=original_question or search_question_text,
        source_rows=source_rows_for_context_filter,
    )

    if not _has_specs_filter(intent):
        rows = _focus_detail_rows(rows, intent, original_question or search_question_text)
    if _is_unmatched_named_detail_question(intent, rows, original_question or search_question_text):
        missing_name = _detail_focus_terms(intent, original_question or search_question_text)[0]
        answer = f"没有找到“{missing_name}”的产品资料，请确认产品名或 SKU 后再查询。"
        return _build_response(
            intent=intent,
            answer=answer,
            sku=None,
            sources=[{"type": "product_search", "label": "意图解析查询", "query": query, "count": 0}],
            results=[],
            steps=_steps(intent, [{"type": tool_name, "label": "执行产品查询", "detail": "命名产品未精确命中", "ok": True}]),
            confidence="low",
            warnings=["named_product_not_found"],
            anomalies=[],
            suggested_followups=[],
            answer_type="product_detail",
        )
    if not rows and _looks_like_usage_care_question(original_question or search_question_text):
        usage_care_result = await answer_product_usage_care_request(db, question=original_question or search_question_text)
        if usage_care_result:
            return usage_care_result
    anomalies = [] if intent.requested_fields else _detect_row_anomalies(rows, intent)
    warnings.extend(item["message"] for item in anomalies[:3])
    followups = _suggest_followups(rows, intent)

    if _has_specs_filter(intent) and not rows and intent.intent == "query_products":
        answer = _compose_filter_answer_template(rows, intent)
        if "同时满足" not in answer:
            answer = f"{answer}\n未找到同时满足这些条件的 SKU。"
        response = _build_response(
            intent=intent,
            answer=answer,
            sku=None,
            sources=[{"type": "product_search", "label": "结构化字段筛选", "query": query, "count": 0}],
            results=[],
            steps=_steps(intent, [{"type": tool_name, "label": "执行结构化字段筛选", "detail": "命中 0 条", "ok": True}]),
            confidence="high",
            warnings=warnings,
            anomalies=anomalies,
            suggested_followups=followups,
            answer_type="product_query",
            evidence=[],
            debug=_knowledge_enrichment_debug(
                intent,
                steps=_steps(intent, [{"type": tool_name, "label": "执行结构化字段筛选", "detail": "命中 0 条", "ok": True}]),
                warnings=warnings,
                anomalies=anomalies,
                results=[],
                supporting={"qa": [], "kb": [], "evidence": [], "sources": [], "raw_rows": []},
            ),
        )
        response["skip_polish"] = True
        return response

    # Search QA knowledge base for matching Q&A pairs
    qa_results: list[dict] = []
    kb_results: list[dict] = []
    # Use the full original question for QA/knowledge search, not just extracted term
    # This ensures questions like "用什么燃料" match QA entries about fuel/alcohol.
    if not search_question_text:
        search_question_text = intent.term or intent.semantic_query or ""
    for row in rows[:5]:
        sku_val = row.get("sku", "")
        if sku_val:
            qa_matches = _search_product_qa(db, sku_val, search_question_text)
            qa_results.extend(qa_matches)
    # Always search knowledge chunks with the full question for richer context
    supporting = await _semantic_supporting_evidence(
        db,
        search_question_text,
        skus=[str(row.get("sku") or "") for row in rows[:5]],
        limit=5,
    )
    kb_results = supporting["raw_rows"]

    if not rows and (supporting.get("qa") or supporting.get("kb")):
        answer = _compose_semantic_evidence_answer(supporting)
        response = _build_response(
            intent=intent,
            answer=answer,
            sku=None,
            sources=[
                {"type": "product_search", "label": "意图解析查询", "query": query, "count": 0},
                *supporting["sources"],
            ],
            results=[],
            steps=_steps(intent, [{"type": tool_name, "label": "执行产品查询", "detail": "商品库未命中，使用 QA/知识库语义证据补充", "ok": True}]),
            confidence="medium",
            warnings=["product_db_empty_used_semantic_evidence"],
            anomalies=[],
            suggested_followups=followups,
            answer_type="knowledge_base_answer",
            evidence=supporting["evidence"],
            debug=_knowledge_enrichment_debug(
                intent,
                steps=_steps(intent, [{"type": tool_name, "label": "执行产品查询", "detail": "商品库未命中，使用 QA/知识库语义证据补充", "ok": True}]),
                warnings=["product_db_empty_used_semantic_evidence"],
                anomalies=[],
                results=[],
                supporting=supporting,
            ),
        )
        _attach_knowledge_enrichment(response, primary_source="qa_kb", supporting=supporting)
        response["skip_polish"] = True
        return response

    # When user asked for specific fields and we found 1 product: upgrade to detail answer
    answer_type = None
    used_filter_finalizer = False
    if _has_specs_filter(intent) and rows and intent.intent == "query_products":
        answer = await _compose_filter_answer(db, original_question or search_question_text, rows, intent)
        answer_type = "product_query"
        used_filter_finalizer = True
    elif intent.requested_fields and rows and intent.intent in {"query_products", "product_detail"}:
        sku = rows[0].get("sku", "")
        detail = product_service.get_product_detail(db, sku)
        if _is_material_safety_question(original_question or search_question_text):
            material = _format_field_value(_value_from_detail(detail, "specs.body_material"), "specs.body_material")
            if not material or material == "暂无":
                material = "当前资料未注明"
            answer = _compose_material_safety_answer(detail, original_question or search_question_text, material)
            answer_type = "product_detail"
            response = _build_response(
                intent=intent,
                answer=answer,
                sku=sku,
                sources=[
                    {"type": "product_search", "label": "意图解析查询", "query": query, "count": len(rows)},
                    *supporting["sources"],
                ],
                results=rows,
                steps=_steps(intent, [{"type": tool_name, "label": "执行产品查询", "detail": f"命中 {len(rows)} 条", "ok": True}]),
                confidence=_confidence_for_rows(rows, intent, warnings),
                warnings=warnings,
                anomalies=anomalies,
                suggested_followups=followups,
                answer_type=answer_type,
                evidence=supporting["evidence"],
                debug=_knowledge_enrichment_debug(intent, steps=[], warnings=warnings, anomalies=anomalies, results=rows, supporting=supporting),
            )
            _attach_knowledge_enrichment(response, primary_source="product_db", supporting=supporting)
            response["skip_polish"] = True
            return response
        field_paths = [_resolve_query_field(f) for f in intent.requested_fields]
        field_paths = [p for p in field_paths if p]
        detail_rows = [{"sku": sku, "product_name_cn": detail.get("product_name_cn"), "product_name_en": detail.get("product_name_en"), "field_values": {}}]
        for fp in field_paths:
            label = _field_label(fp)
            if fp == "virtual.load_capacity":
                load_capacity = _extract_load_capacity_from_detail(detail, supporting)
                text = (
                    f"当前结构化字段里未见独立承重字段（最大承重），但同 SKU 资料中写有“{load_capacity}”。建议以该资料为参考"
                    if load_capacity
                    else "暂无"
                )
            else:
                value = _value_from_detail(detail, fp)
                text = _format_field_value(value, fp) if value not in (None, "") else "暂无"
            detail_rows[0]["field_values"][label] = text
            anomaly = _field_anomaly_for_value(sku, label, text)
            if anomaly:
                anomalies.append(anomaly)
        answer = _compose_detail_answer(
            db,
            detail_rows,
            field_paths,
            warnings,
            anomalies,
            [],
            qa_results=qa_results or supporting.get("qa"),
            kb_results=supporting.get("kb") or kb_results,
            question=original_question or "",
        )
        answer_type = "product_detail"
    elif intent.requested_fields and intent.intent in {"query_products", "product_detail"}:
        field_paths = [_resolve_query_field(f) for f in intent.requested_fields]
        field_paths = [p for p in field_paths if p]
        answer = _compose_detail_answer(db, [], field_paths, warnings, anomalies, [], question=original_question or "")
        answer_type = "product_detail"
    else:
        answer = await _llm_compose_answer(db, search_question_text, rows, intent, qa_results, kb_results, warnings, followups)

    supporting_sources = supporting["sources"] if rows else []
    response = _build_response(
        intent=intent,
        answer=answer,
        sku=rows[0]["sku"] if len(rows) == 1 else None,
        sources=[
            {"type": "product_search", "label": "意图解析查询", "query": query, "count": len(rows)},
            *supporting_sources,
        ],
        results=rows,
        steps=_steps(intent, [{"type": tool_name, "label": "执行产品查询", "detail": f"命中 {len(rows)} 条", "ok": True}]),
        confidence=_confidence_for_rows(rows, intent, warnings),
        warnings=warnings,
        anomalies=anomalies,
        suggested_followups=followups,
        answer_type=answer_type,
        evidence=supporting["evidence"] if rows else None,
        debug=_knowledge_enrichment_debug(
            intent,
            steps=_steps(intent, [{"type": tool_name, "label": "执行产品查询", "detail": f"命中 {len(rows)} 条", "ok": True}]),
            warnings=warnings,
            anomalies=anomalies,
            results=rows,
            supporting=supporting,
        ) if rows else None,
    )
    if rows:
        _attach_knowledge_enrichment(response, primary_source="product_db", supporting=supporting)
    if used_filter_finalizer or answer_type == "product_detail":
        response["skip_polish"] = True
    return response


async def _product_detail_result(db: Session, intent: CustomerIntent, original_question: str = "") -> dict:
    intent.requested_fields = [
        str(field).strip()
        for field in (intent.requested_fields or [])
        if str(field or "").strip() and str(field or "").strip().lower() != "none"
    ]
    detail_question = str(original_question or intent.semantic_query or intent.term or "")
    if not intent.requested_fields and any(term in detail_question for term in ("认证", "出口认证", "FDA", "LFGB")):
        intent.requested_fields = ["认证"]
    if not intent.target_skus and intent.term:
        candidate_rows = customer_agent_service.search_products(db, intent.term, limit=10, filters={})
        if candidate_rows:
            candidate_rows = _filter_rows(candidate_rows, filters={}, negative_filters={}, term=intent.term)
            candidate_rows = _focus_detail_rows(candidate_rows, intent, intent.semantic_query or intent.term)
        if candidate_rows:
            intent.target_skus = [str(candidate_rows[0].get("sku") or "").strip().upper()]
        else:
            return await _query_products_result(db, "intent-product-detail", intent, original_question=intent.semantic_query or intent.term or "")
    intent.target_skus = [_resolve_existing_sku(db, sku) for sku in intent.target_skus]
    rows = []
    field_paths = [_resolve_query_field(field) for field in intent.requested_fields]
    field_paths = [path for path in field_paths if path]
    anomalies: list[dict[str, Any]] = []
    details: list[dict[str, Any]] = []

    missing_requested_labels: list[str] = []
    for sku in intent.target_skus:
        product = db.query(Product).filter(Product.sku.ilike(sku)).first()
        if not product:
            continue
        sku = product.sku
        detail = product_service.get_product_detail(db, sku)
        details.append(detail)
        row = {
            "sku": sku,
            "product_name_cn": detail.get("product_name_cn"),
            "product_name_en": detail.get("product_name_en"),
            "field_values": {},
        }
        for field_path in field_paths:
            label = _field_label(field_path)
            if field_path == "virtual.load_capacity":
                load_capacity = _extract_load_capacity_from_detail(detail, {})
                text = (
                    f"当前结构化字段里未见独立承重字段（最大承重），但同 SKU 资料中写有“{load_capacity}”。建议以该资料为参考"
                    if load_capacity
                    else "暂无"
                )
            else:
                value = _value_from_detail(detail, field_path)
                text = _format_field_value(value, field_path) if value not in (None, "", 0) else "暂无"
            row["field_values"][label] = text
            if text == "暂无":
                missing_requested_labels.append(_requested_label_for_path(intent.requested_fields, field_path) or label)
            anomaly = _field_anomaly_for_value(sku, label, text)
            if anomaly:
                anomalies.append(anomaly)
        rows.append(row)

    search_question = intent.semantic_query or intent.term or original_question or ""
    display_question = original_question or search_question
    if any(term in display_question for term in ("主体材质", "锅体材质", "炉体材质")):
        for row in rows:
            field_values = row.get("field_values")
            if isinstance(field_values, dict) and "材质" in field_values and "主体材质" not in field_values:
                field_values["主体材质"] = field_values.pop("材质")

    def _missing_field_answer(row: dict[str, Any], labels: list[str]) -> str:
        if any(_normalize_requested_field_label(label) == "认证" for label in labels) and "出口" in search_question:
            name = row.get("product_name_cn") or row.get("product_name_en") or ""
            sku = row.get("sku") or ""
            prefix = f"{name}（{sku}）" if name else sku
            return f"{prefix}\n当前资料中暂未找到{prefix}的明确出口认证信息。"
        return _compose_missing_field_answer(row, labels)

    supporting = await _semantic_supporting_evidence(
        db,
        search_question,
        skus=intent.target_skus,
        limit=5,
    )

    warnings = [item["message"] for item in anomalies[:3]]
    followups = _suggest_detail_followups(intent)
    compound_answer = None
    if len(rows) == 1 and details:
        compound_answer = _compound_single_product_detail_answer(
            db,
            sku=rows[0]["sku"],
            detail=details[0],
            question=display_question or search_question,
            supporting=supporting,
        )
        if compound_answer:
            rows[0]["field_values"] = _compound_field_values_from_answer(compound_answer)

    if not rows:
        missing = "、".join(intent.target_skus or [intent.term or "该产品"])
        answer = f"没有找到{missing}的产品资料，请确认产品名或 SKU 后再查询。"
    elif compound_answer:
        answer = compound_answer
    elif len(rows) == 1 and _is_material_safety_question(search_question):
        detail = details[0] if details else product_service.get_product_detail(db, rows[0]["sku"])
        evidence_answer = _same_product_evidence_answer(
            db,
            sku=rows[0]["sku"],
            question=search_question,
            requested_fields=intent.requested_fields or ["材质", "认证"],
            supporting=supporting,
        )
        if evidence_answer:
            answer = evidence_answer
        else:
            material = _format_field_value(_value_from_detail(detail, "specs.body_material"), "specs.body_material")
            if not material or material == "暂无":
                material = "当前资料未注明"
            answer = _compose_material_safety_answer(detail, search_question, material)
    elif field_paths:
        if len(rows) == 1 and _all_requested_field_values_missing(rows):
            if _looks_like_water_container_capability_question(search_question):
                answer = _compose_detail_answer(
                    db,
                    rows,
                    field_paths,
                    warnings,
                    anomalies,
                    followups,
                    qa_results=supporting.get("qa"),
                    kb_results=supporting.get("kb"),
                    question=search_question,
                )
            else:
                evidence_answer = _same_product_evidence_answer(
                    db,
                    sku=rows[0]["sku"],
                    question=search_question,
                    requested_fields=missing_requested_labels or intent.requested_fields,
                    supporting=supporting,
                )
                answer = evidence_answer or _missing_field_answer(rows[0], missing_requested_labels or intent.requested_fields)
        else:
            answer = _compose_detail_answer(
                db,
                rows,
                field_paths,
                warnings,
                anomalies,
                followups,
                qa_results=supporting.get("qa"),
                kb_results=supporting.get("kb"),
                question=search_question,
            )
    else:
        if len(rows) == 1:
            evidence_answer = _same_product_evidence_answer(
                db,
                sku=rows[0]["sku"],
                question=search_question,
                requested_fields=intent.requested_fields,
                supporting=supporting,
            )
            answer = evidence_answer or _missing_field_answer(rows[0], intent.requested_fields)
        else:
            answer = _compose_unknown_attribute_answer(details, intent.requested_fields, followups)
    response_rows = _rewrite_heat_source_support_rows(search_question, rows) if rows else rows
    response = _build_response(
        intent=intent,
        answer=answer,
        sku=intent.target_skus[0] if len(intent.target_skus) == 1 else None,
        sources=[
            {"type": "product", "label": "按意图读取产品字段", "count": len(rows)},
            *supporting["sources"],
        ],
        results=response_rows,
        steps=_steps(intent, [{"type": "product_detail", "label": "读取产品字段", "detail": f"读取 {len(rows)} 个 SKU", "ok": True}]),
        confidence="high" if rows else "low",
        warnings=warnings,
        anomalies=anomalies,
        suggested_followups=followups,
        answer_type="product_detail",
        evidence=supporting["evidence"] if rows else None,
        debug=_knowledge_enrichment_debug(
            intent,
            steps=_steps(intent, [{"type": "product_detail", "label": "读取产品字段", "detail": f"读取 {len(rows)} 个 SKU", "ok": True}]),
            warnings=warnings,
            anomalies=anomalies,
            results=response_rows,
            supporting=supporting,
        ) if rows else None,
    )
    if rows:
        _attach_knowledge_enrichment(response, primary_source="product_db", supporting=supporting)
    response["skip_polish"] = True
    return response


async def _compare_result(db: Session, intent: CustomerIntent, original_question: str = "") -> dict:
    intent.target_skus = [_resolve_existing_sku(db, sku) for sku in intent.target_skus]
    fields = intent.requested_fields or ["商品英文名称", "容量", "重量", "材质", "颜色", "卖点", "适用场景", "目标人群"]
    compare_text = str(original_question or "")
    if any(term in compare_text for term in ("热源", "燃料", "适用热源", "适用燃料")) and "热源" not in fields:
        fields = ["热源", *fields]
    comparisons = []
    anomalies: list[dict[str, Any]] = []
    product_data_by_sku: dict[str, dict] = {}

    for field in fields:
        field_path = _resolve_query_field(field)
        if not field_path:
            continue
        label = _field_label(field_path)
        values = []
        for sku in intent.target_skus:
            detail = product_data_by_sku.get(sku)
            if detail is None:
                detail = product_service.get_product_detail(db, sku)
                product_data_by_sku[sku] = detail
            value = _value_from_detail(detail, field_path)
            text = _format_field_value(value, field_path) if value not in (None, "") else "暂无"
            values.append({"sku": sku, "value": text})
            anomaly = _field_anomaly_for_value(sku, label, text)
            if anomaly:
                anomalies.append(anomaly)
        comparisons.append({"field_label": label, "values": values})

    warnings = [item["message"] for item in anomalies[:3]]
    followups = [
        "如果你要继续筛选，我可以按容量、材质、负责人或使用场景进一步缩小范围。",
        "如果你要做取舍，我也可以继续判断哪款更适合某个具体场景。",
    ]
    product_data_list = [product_data_by_sku[sku] for sku in intent.target_skus if sku in product_data_by_sku]
    answer = await _compose_compare_answer(
        db,
        original_question,
        intent.target_skus,
        comparisons,
        warnings,
        anomalies,
        followups,
        product_data_list,
    )
    result_rows = []
    for item in comparisons:
        for entry in item["values"]:
            result_rows.append(
                {
                    "sku": entry["sku"],
                    "product_name_cn": (product_data_by_sku.get(entry["sku"]) or {}).get("product_name_cn", ""),
                    "field_label": item["field_label"],
                    "value": entry["value"],
                    "matched_by": "产品对比",
                }
            )

    response = _build_response(
        intent=intent,
        answer=answer,
        sku=None,
        sources=[{"type": "product_compare", "label": "产品对比", "count": len(intent.target_skus)}],
        results=result_rows,
        steps=_steps(intent, [{"type": "compare_products", "label": "对比产品字段", "detail": f"对比 {len(intent.target_skus)} 个 SKU", "ok": True}]),
        confidence="medium" if anomalies else "high",
        warnings=warnings,
        anomalies=anomalies,
        suggested_followups=followups,
    )
    supporting = await _semantic_supporting_evidence(
        db,
        original_question,
        skus=intent.target_skus,
        limit=5,
        query_limit=2,
    )
    if supporting.get("qa") or supporting.get("kb"):
        response["sources"] = [*(response.get("sources") or []), *supporting.get("sources", [])]
        response["evidence"] = supporting.get("evidence")
        _attach_knowledge_enrichment(response, primary_source="product_db", supporting=supporting)
    response["skip_polish"] = True
    return response


async def _explicit_product_compatibility_result(db: Session, question: str) -> dict | None:
    if not _looks_like_product_compatibility_question(question):
        return None
    rows = _explicit_product_rows_from_question(db, question)
    if len(rows) < 2:
        return None
    rows = rows[:2]
    skus = [str(row.get("sku") or "").strip().upper() for row in rows if str(row.get("sku") or "").strip()]
    if len(skus) < 2:
        return None
    details = [product_service.get_product_detail(db, sku) for sku in skus]
    supporting = await _semantic_supporting_evidence(db, question, skus=skus, limit=5, query_limit=2)
    answer = _compose_compatibility_answer(question, details)
    intent = CustomerIntent(
        intent="product_detail",
        target_skus=skus,
        semantic_query=question,
        source_context="question",
        is_single_field_sufficient=False,
    )
    result_rows = [_compatibility_result_row(detail) for detail in details]
    steps = _steps(intent, [{"type": "product_detail", "label": "读取双产品兼容字段", "detail": f"读取 {len(result_rows)} 个 SKU", "ok": True}])
    response = _build_response(
        intent=intent,
        answer=answer,
        sku=None,
        sources=[
            {"type": "product", "label": "双产品兼容性字段读取", "count": len(result_rows)},
            *supporting["sources"],
        ],
        results=result_rows,
        steps=steps,
        confidence="medium",
        warnings=[],
        anomalies=[],
        suggested_followups=["如果你要继续确认某一款的功率、热源或使用限制，可以直接追问。"],
        answer_type="product_detail",
        evidence=supporting["evidence"],
        debug=_knowledge_enrichment_debug(
            intent,
            steps=steps,
            warnings=[],
            anomalies=[],
            results=result_rows,
            supporting=supporting,
        ),
    )
    _attach_knowledge_enrichment(response, primary_source="product_db", supporting=supporting)
    response["skip_polish"] = True
    return response


def _looks_like_product_compatibility_question(question: str) -> bool:
    text = str(question or "")
    return any(term in text for term in ("配合使用", "搭配使用", "一起用", "一起使用", "兼容", "适配", "能和", "可以和"))


def _explicit_product_rows_from_question(db: Session, question: str) -> list[dict[str, Any]]:
    text = customer_agent_service.normalize_search_text(question)
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    products = db.query(Product).all()
    for product in products:
        sku = str(product.sku or "").strip().upper()
        if not sku or sku in seen:
            continue
        name_cn = customer_agent_service.normalize_search_text(getattr(product, "product_name_cn", "") or "")
        name_en = customer_agent_service.normalize_search_text(getattr(product, "product_name_en", "") or "")
        sku_text = customer_agent_service.normalize_search_text(sku)
        if (
            (name_cn and name_cn in text)
            or (name_en and name_en in text)
            or (sku_text and sku_text in text)
        ):
            rows.append(
                {
                    "sku": sku,
                    "product_name_cn": getattr(product, "product_name_cn", None),
                    "product_name_en": getattr(product, "product_name_en", None),
                    "category": getattr(product, "category", None),
                }
            )
            seen.add(sku)
    return rows


def _explicit_products_from_question(db: Session, question: str) -> list[Product]:
    explicit_rows = _explicit_product_rows_from_question(db, question)
    if not explicit_rows:
        return []
    sku_order = [str(item.get("sku") or "").strip().upper() for item in explicit_rows if str(item.get("sku") or "").strip()]
    sku_map = {
        str(product.sku or "").strip().upper(): product
        for product in db.query(Product).filter(Product.sku.in_(sku_order)).all()
    }
    return [sku_map[sku] for sku in sku_order if sku in sku_map]


def _compatibility_result_row(detail: dict[str, Any]) -> dict[str, Any]:
    specs = detail.get("specs") or {}
    business = detail.get("business") or {}
    return {
        "sku": detail.get("sku"),
        "product_name_cn": detail.get("product_name_cn"),
        "product_name_en": detail.get("product_name_en"),
        "category": detail.get("category"),
        "field_values": {
            "类目": detail.get("category") or "暂无",
            "适用热源": _format_field_value(specs.get("heat_source"), "specs.heat_source") if specs.get("heat_source") not in (None, "") else "暂无",
            "功率": _format_field_value(specs.get("power"), "specs.power") if specs.get("power") not in (None, "") else "暂无",
            "卖点": customer_agent_service._stringify(business.get("top_selling_points")) or "暂无",
        },
    }


def _compose_compatibility_answer(question: str, details: list[dict[str, Any]]) -> str:
    names = [
        f"{detail.get('product_name_cn') or detail.get('product_name_en') or detail.get('sku')}（{detail.get('sku')}）"
        for detail in details
    ]
    lines = [
        f"当前资料可锁定这两个产品：{'、'.join(names)}。",
        "资料中未直接给出两者“可配合使用”的明确结论，所以不能替用户承诺一定兼容；只能基于各自字段作参考。",
    ]
    for detail in details:
        specs = detail.get("specs") or {}
        business = detail.get("business") or {}
        evidence_parts = []
        heat_source = _format_field_value(specs.get("heat_source"), "specs.heat_source") if specs.get("heat_source") not in (None, "") else ""
        power = _format_field_value(specs.get("power"), "specs.power") if specs.get("power") not in (None, "") else ""
        selling_points = customer_agent_service._stringify(business.get("top_selling_points"))
        if heat_source:
            evidence_parts.append(f"适用热源：{heat_source}")
        if power:
            evidence_parts.append(f"功率：{power}")
        if selling_points:
            evidence_parts.append(f"卖点：{selling_points}")
        evidence = "；".join(evidence_parts[:3]) or "当前结构化字段未提供足够兼容性参数"
        lines.append(f"{detail.get('product_name_cn') or detail.get('sku')}（{detail.get('sku')}）：{evidence}。")
    lines.append("建议实际使用前再核对锅具底部尺寸、炉架承重和稳定性。")
    return "\n".join(lines)


async def _compose_compare_answer(
    db: Session,
    question: str,
    skus: list[str],
    comparisons: list[dict[str, Any]],
    warnings: list[str],
    anomalies: list[dict[str, Any]],
    followups: list[str],
    product_data_list: list[dict[str, Any]] | None = None,
) -> str:
    product_data_list = product_data_list or []
    if _is_same_product_comparison_question(question):
        return _compose_same_product_compare_answer_template(question, skus, comparisons)
    if _looks_like_multi_product_relation_question(question):
        return _compose_multi_product_relation_answer(skus, product_data_list, comparisons)
    if _looks_like_multi_sku_intro_question(question):
        return _compose_multi_sku_intro_answer(skus, comparisons)
    if product_data_list:
        answer = await _finalize_compare_answer(
            db,
            question=question,
            skus=skus,
            comparisons=comparisons,
            warnings=warnings,
            anomalies=anomalies,
            followups=followups,
            product_data_list=product_data_list,
        )
        if answer:
            return answer
    return _compose_compare_answer_template(skus, comparisons, warnings, anomalies, followups)


def _compose_compare_answer_template(
    skus: list[str],
    comparisons: list[dict[str, Any]],
    warnings: list[str],
    anomalies: list[dict[str, Any]],
    followups: list[str],
) -> str:
    if not skus:
        return "没有找到可对比的产品。"
    lines = [f"先说结论：已对比 {'、'.join(skus)}，建议按客户更看重的容量、材质、卖点和使用场景来选。"]
    for item in comparisons:
        label = item.get("field_label") or "字段"
        values = []
        for entry in item.get("values") or []:
            values.append(f"{entry.get('sku')}：{entry.get('value') or '暂无'}")
        if values:
            lines.append(f"{label}：" + "；".join(values))
    if any("PRO" in sku.upper() for sku in skus):
        lines.append("选择建议：如果客户想要升级款或更强配置，优先介绍 Pro；如果客户要稳妥常规款或基础方案，推荐基础款。")
    if warnings:
        lines.append("注意：" + "；".join(warnings[:2]))
    if followups:
        lines.append(f"下一步：{followups[0]}")
    return "\n".join(lines)


def _compose_multi_sku_intro_answer(
    skus: list[str],
    comparisons: list[dict[str, Any]],
) -> str:
    if not skus:
        return "没有找到可介绍的产品。"
    lines = [f"当前识别到 {len(skus)} 个不同 SKU：{'、'.join(skus)}。"]
    field_map: dict[str, list[str]] = {sku: [] for sku in skus}
    meaningful_field_count = 0
    for item in comparisons:
        label = str(item.get("field_label") or "").strip()
        if not label or label == "SKU":
            continue
        has_meaningful_value = False
        for entry in item.get("values") or []:
            sku = str(entry.get("sku") or "").strip().upper()
            value = str(entry.get("value") or "").strip() or "暂无"
            if sku in field_map:
                field_map[sku].append(f"{label}：{value}")
            if value not in {"", "暂无"}:
                has_meaningful_value = True
        if has_meaningful_value:
            meaningful_field_count += 1
    for sku in skus:
        lines.append(f"{sku}：")
        sku_lines = field_map.get(sku) or []
        if sku_lines:
            lines.extend(f"- {item}" for item in sku_lines)
        else:
            lines.append("- 当前资料暂未补充更多字段。")
    if meaningful_field_count == 0:
        lines.append("当前资料未提供明确差异字段，只能先分别列出已识别到的 SKU。")
    else:
        lines.append("当前资料未提供明确差异字段时，我会如实保留相同项，不会把两个 SKU 合并成同一个产品。")
    return "\n".join(lines)


def _compose_multi_product_relation_answer(
    skus: list[str],
    product_data_list: list[dict[str, Any]],
    comparisons: list[dict[str, Any]],
) -> str:
    if not skus:
        return "没有找到可说明关系的产品。"
    product_map = {
        str(item.get("sku") or "").strip().upper(): item
        for item in (product_data_list or [])
        if isinstance(item, dict) and str(item.get("sku") or "").strip()
    }
    lines = [f"当前可确认这 {len(skus)} 个 SKU 分别对应："]
    for sku in skus:
        detail = product_map.get(str(sku or "").strip().upper()) or {}
        name = detail.get("product_name_cn") or detail.get("product_name_en") or "当前资料未注明产品名"
        category = detail.get("category") or "当前资料未注明类目"
        lines.append(f"- {sku}：{name}，类目：{category}")

    relation_line = _infer_multi_product_relation_line(skus, product_map)
    if relation_line:
        lines.append(relation_line)
    else:
        lines.append("当前资料能确认它们是不同 SKU、分别对应不同产品；但未明确标注完整的套装包含关系，需以产品资料为准。")

    field_map: dict[str, str] = {}
    for item in comparisons:
        label = str(item.get("field_label") or "").strip()
        if label not in {"容量", "材质", "适用场景", "目标人群"}:
            continue
        entries = []
        for entry in item.get("values") or []:
            sku = str(entry.get("sku") or "").strip().upper()
            value = str(entry.get("value") or "").strip()
            if sku and value and value != "暂无":
                entries.append(f"{sku}={value}")
        if entries:
            field_map[label] = "；".join(entries)
    if field_map:
        lines.append("当前资料里的可见字段：")
        for label, value in field_map.items():
            lines.append(f"- {label}：{value}")
    return "\n".join(lines)


def _infer_multi_product_relation_line(
    skus: list[str],
    product_map: dict[str, dict[str, Any]],
) -> str:
    parent_terms = ("套锅", "套装", "组合")
    single_terms = ("炒锅", "煎锅", "单锅", "平底锅", "锅", "水壶", "饭盒", "杯")

    def _family_key(name: str) -> str:
        value = str(name or "").strip()
        for suffix in ("套锅", "套装", "炒锅", "煎锅", "单锅", "平底锅", "水壶", "饭盒", "杯", "锅"):
            if value.endswith(suffix):
                value = value[: -len(suffix)]
                break
        return value.strip("（）() -")

    parent_sku = ""
    parent_name = ""
    for sku in skus:
        detail = product_map.get(str(sku or "").strip().upper()) or {}
        name = str(detail.get("product_name_cn") or detail.get("product_name_en") or "").strip()
        if any(term in name for term in parent_terms):
            parent_sku = sku
            parent_name = name
            break
    if not parent_sku:
        return ""

    family = _family_key(parent_name)
    child_descriptions = []
    for sku in skus:
        if sku == parent_sku:
            continue
        detail = product_map.get(str(sku or "").strip().upper()) or {}
        name = str(detail.get("product_name_cn") or detail.get("product_name_en") or "").strip()
        if not name:
            continue
        same_family = bool(family) and _family_key(name) == family
        looks_like_single = any(term in name for term in single_terms)
        same_base_sku = str(sku).startswith(f"{parent_sku}-")
        if same_family or same_base_sku or looks_like_single:
            child_descriptions.append(f"{name}（{sku}）")
    if not child_descriptions:
        return ""
    return (
        f"从当前产品命名和 SKU 结构看，{parent_name}（{parent_sku}）是套装/组合产品，"
        f"{'、'.join(child_descriptions)}更像是同系列单品或组成件；如需确认完整套装包含关系，仍建议以产品资料为准。"
    )


async def _finalize_compare_answer(
    db: Session,
    *,
    question: str,
    skus: list[str],
    comparisons: list[dict[str, Any]],
    warnings: list[str],
    anomalies: list[dict[str, Any]],
    followups: list[str],
    product_data_list: list[dict[str, Any]],
) -> str | None:
    system_prompt = (
        "你是alocs爱路客的产品客服助手。"
        "【核心规则，最高优先级】"
        "1. 严禁引入retrieved_products之外的产品事实、参数、认证、价格或库存。"
        "2. 工具结果里没有的信息，必须说\"暂无此数据\"，不得推断或编造。"
        "3. 用户没有问到的话题不要主动引入。"
        "【任务】"
        "根据用户问题和retrieved_products里的完整产品数据，组织自然的产品对比回答。"
        "如果用户问哪个更轻、容量差多少、材质/表面处理是否一样、适合人群有什么不同，要直接给结论，再列依据。"
        "不要只复述SKU列表。"
        "【格式要求】"
        "不使用Markdown表格，不使用**或###。只输出JSON：{\"answer\":\"...\"}。"
    )
    payload = {
        "question": question,
        "intent_hint": "compare_products",
        "target_skus": skus,
        "retrieved_products": product_data_list,
        "comparison_summary": comparisons,
        "warnings": warnings,
        "anomalies": anomalies,
        "suggested_followups": followups,
    }
    try:
        content = await customer_llm_service.chat_completion(
            db,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": json.dumps(payload, ensure_ascii=False, default=str)},
            ],
            temperature=0.2,
            max_tokens=1000,
            purpose="compare_answer",
        )
    except Exception:
        return None
    return _answer_from_llm_content(content) or None


def _parse_json_object(content: str) -> dict | None:
    text = (content or "").strip()
    if not text:
        return None
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.I)
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


def _extract_answer_from_json_like_text(content: str) -> str:
    text = (content or "").strip()
    if not text:
        return ""
    match = re.search(r'"answer"\s*:\s*"(.*)"\s*\}\s*$', text, flags=re.S)
    if not match:
        return ""
    raw = match.group(1)
    return (
        raw.replace('\\"', '"')
        .replace("\\n", "\n")
        .replace("\\r", "\r")
        .replace("\\t", "\t")
    )


def _clean_llm_answer_text(answer: str) -> str:
    text = str(answer or "").strip()
    if not text:
        return ""
    text = re.sub(r"\*\*(.*?)\*\*", r"\1", text)
    text = re.sub(r"^#{1,6}\s*", "", text, flags=re.M)
    text = text.replace("```json", "").replace("```", "")
    return text.strip()


def _answer_from_llm_content(content: str) -> str:
    text = str(content or "").strip()
    if not text:
        return ""
    data = _parse_json_object(text)
    if isinstance(data, dict) and data.get("answer"):
        return _clean_llm_answer_text(str(data["answer"]))
    extracted = _extract_answer_from_json_like_text(text)
    if extracted:
        return _clean_llm_answer_text(extracted)
    return _clean_llm_answer_text(text)


_CHINESE_DIGITS = {
    "一": 1,
    "二": 2,
    "两": 2,
    "三": 3,
    "四": 4,
    "五": 5,
    "六": 6,
    "七": 7,
    "八": 8,
    "九": 9,
    "十": 10,
}


def _parse_people_number(value: str) -> int | None:
    text = str(value or "").strip()
    if not text:
        return None
    if text.isdigit():
        return int(text)
    return _CHINESE_DIGITS.get(text)


def _extract_min_people_constraint(query: str) -> int | None:
    text = str(query or "")
    values: list[int] = []
    for match in re.finditer(r"([1-9]\d?|[一二两三四五六七八九十])\s*(?:个)?人", text):
        value = _parse_people_number(match.group(1))
        if value is not None:
            values.append(value)
    return max(values) if values else None


def _has_small_capacity_exclusion(query: str) -> bool:
    text = str(query or "")
    return bool(
        re.search(r"(?:不要|排除|别要|不考虑|去掉).{0,8}(?:1\s*[-到至~]\s*2|一\s*[-到至~]?\s*两|一两)\s*(?:个)?人", text)
        or re.search(r"(?:不要|排除|别要|不考虑|去掉).{0,8}小容量", text)
    )


def _row_people_range(row: dict[str, Any]) -> tuple[int | None, int | None]:
    text = " ".join(
        str(row.get(key) or "")
        for key in (
            "sku",
            "product_name_cn",
            "product_name_en",
            "capacity",
            "features",
            "usage_scenarios",
            "target_audience",
            "positioning",
            "semantic_match",
        )
    )
    ranges: list[tuple[int, int]] = []
    for match in re.finditer(r"([1-9]\d?|[一二两三四五六七八九十])\s*[-到至~]\s*([1-9]\d?|[一二两三四五六七八九十])\s*(?:个)?人", text):
        start = _parse_people_number(match.group(1))
        end = _parse_people_number(match.group(2))
        if start is not None and end is not None:
            ranges.append((min(start, end), max(start, end)))
    for match in re.finditer(r"([1-9]\d?|[一二两三四五六七八九十])\s*(?:个)?人", text):
        value = _parse_people_number(match.group(1))
        if value is not None:
            ranges.append((value, value))
    if not ranges:
        return None, None
    return min(item[0] for item in ranges), max(item[1] for item in ranges)


def _row_has_large_group_evidence(row: dict[str, Any]) -> bool:
    text = " ".join(
        str(row.get(key) or "")
        for key in (
            "product_name_cn",
            "capacity",
            "features",
            "usage_scenarios",
            "target_audience",
            "positioning",
        )
    )
    if any(term in text for term in ("大容量", "多人", "营地聚餐", "多人使用", "家庭露营", "自驾露营")):
        return True
    return bool(re.search(r"(?:[3-9]\d{3,}|[3-9](?:\.\d+)?\s*L|[3-9](?:\.\d+)?\s*l)", text))


def _apply_people_capacity_constraint_to_ranked(
    ranked: list[dict[str, Any]],
    query: str,
    *,
    scoped_comparison_candidates: bool = False,
) -> tuple[list[dict[str, Any]], list[str]]:
    min_people = _extract_min_people_constraint(query)
    if not min_people:
        return ranked, []
    query_text = str(query or "")
    if (
        min_people < 5
        and not scoped_comparison_candidates
        and not any(term in query_text for term in ("大容量", "多人", "多人使用", "多人露营", "多人做饭"))
    ):
        return ranked, []

    exclude_small = _has_small_capacity_exclusion(query)
    strict_matches: list[dict[str, Any]] = []
    close_matches: list[dict[str, Any]] = []
    downgraded: list[dict[str, Any]] = []
    uncertain: list[dict[str, Any]] = []

    for item in ranked:
        row = item.get("row") if isinstance(item.get("row"), dict) else {}
        people_min, people_max = _row_people_range(row)
        if exclude_small and people_min == 1 and people_max is not None and people_max <= 2:
            downgraded.append(item)
            continue
        if people_max is not None:
            if people_max >= min_people:
                strict_matches.append(item)
            else:
                downgraded.append(item)
            continue
        if _row_has_large_group_evidence(row):
            close_matches.append(item)
        else:
            uncertain.append(item)

    reordered = [*strict_matches, *close_matches, *uncertain, *downgraded]
    warnings: list[str] = []
    if not strict_matches and (close_matches or uncertain or downgraded):
        warnings.append(
            f"当前资料里没有明确标注 {min_people} 人适用的锅具套装，下面按更接近大容量/多人使用的方案推荐。"
        )
    return reordered or ranked, warnings


def _has_cookware_set_positive_constraint(query: str) -> bool:
    text = str(query or "")
    return bool(
        "套锅" in text
        or "锅具套装" in text
        or "炊具组合" in text
        or re.search(r"(?:只要|要|推荐).{0,12}(?:锅具|锅|炊具).{0,8}(?:套装|多件套|组合)", text)
        or re.search(r"(?:锅具|锅|炊具).{0,8}(?:套装|多件套|组合)", text)
    )


def _has_water_or_stove_exclusion(query: str) -> bool:
    text = str(query or "")
    negative = r"(?:不要|不需要|别要|不考虑|排除|去掉)"
    return bool(
        re.search(fr"{negative}.{{0,10}}(?:水壶|茶壶|壶类|水壶类)", text)
        or re.search(fr"{negative}.{{0,10}}(?:炉具|炉子|酒精炉|气炉|汽炉)", text)
    )


def _row_identity_text(row: dict[str, Any]) -> str:
    return " ".join(
        str(row.get(key) or "")
        for key in ("sku", "product_name_cn", "product_name_en", "category")
    )


def _row_cookware_set_evidence_text(row: dict[str, Any]) -> str:
    return " ".join(
        str(row.get(key) or "")
        for key in (
            "product_name_cn",
            "product_name_en",
            "category",
            "capacity",
            "features",
            "usage_scenarios",
            "target_audience",
            "positioning",
        )
    )


def _is_excluded_for_cookware_set_constraint(row: dict[str, Any]) -> bool:
    identity = _row_identity_text(row)
    return bool(
        re.search(r"(?:水壶|茶壶|壶类|水壶类)", identity)
        or re.search(r"(?:炉具|炉子|酒精炉|气炉|汽炉)", identity)
        or re.search(r"(?:炒锅|煎锅|单锅|烤盘)", identity)
    )


def _has_cookware_set_row_evidence(row: dict[str, Any]) -> bool:
    text = _row_cookware_set_evidence_text(row)
    if _is_excluded_for_cookware_set_constraint(row):
        return False
    if any(term in text for term in ("套锅", "锅具套装", "锅具多件套", "炊具组合")):
        return True
    cookware_context = any(term in text for term in ("锅具", "炊具", "野餐锅", "野营锅", "套锅"))
    set_context = bool(re.search(r"(?:\d+|[一二两三四五六七八九十])件套|多件套|组合套装", text))
    return cookware_context and set_context


def _apply_cookware_set_shape_constraint_to_ranked(
    ranked: list[dict[str, Any]],
    query: str,
) -> tuple[list[dict[str, Any]], list[str]]:
    if not (_has_cookware_set_positive_constraint(query) and _has_water_or_stove_exclusion(query)):
        return ranked, []

    preferred: list[dict[str, Any]] = []
    downgraded: list[dict[str, Any]] = []
    uncertain: list[dict[str, Any]] = []
    for item in ranked:
        row = item.get("row") if isinstance(item.get("row"), dict) else {}
        if _has_cookware_set_row_evidence(row):
            preferred.append(item)
        elif _is_excluded_for_cookware_set_constraint(row):
            downgraded.append(item)
        else:
            uncertain.append(item)

    warnings: list[str] = []
    if not preferred and (uncertain or downgraded):
        warnings.append("当前资料里没有足够明确的锅具套装候选，不能把水壶、炉具或单品锅具包装成套锅推荐。")
    if preferred:
        return [*preferred, *uncertain, *downgraded], warnings
    return [*uncertain, *downgraded] or ranked, warnings


def _should_route_cooking_set_exclusion_to_recommendation(query: str) -> bool:
    text = str(query or "").strip()
    if not text:
        return False
    has_scene_or_recommendation = (
        any(term in text for term in ("推荐", "适合", "要", "想买", "帮我选", "帮我挑"))
        and any(term in text for term in ("露营", "徒步", "做饭", "野餐", "户外", "营地"))
    )
    if not has_scene_or_recommendation:
        return False
    if not _has_cookware_set_positive_constraint(text):
        return False
    return _has_water_or_stove_exclusion(text)


def _extract_extreme_objectives(query: str) -> list[str]:
    text = str(query or "")
    objectives: list[str] = []
    if "最轻" in text:
        objectives.append("lightest")
    if "最大容量" in text or ("最大" in text and "容量" in text):
        objectives.append("max_capacity")
    if ("最高" in text or "最强" in text) and all(term not in objectives for term in ("max_capacity",)):
        objectives.append("max_metric")
    return objectives


def _requires_all_constraints(query: str) -> bool:
    text = str(query or "")
    return any(term in text for term in ("必须都满足", "都要满足", "全都满足", "同时满足"))


def _row_has_explicit_weight_evidence(row: dict[str, Any]) -> bool:
    text = " ".join(
        str(row.get(key) or "")
        for key in ("product_name_cn", "capacity", "features", "usage_scenarios", "target_audience", "positioning")
    )
    return bool(re.search(r"(净重|重量|约)\s*\d+(?:\.\d+)?\s*(?:g|kg)", text, flags=re.I))


def _row_has_explicit_capacity_evidence(row: dict[str, Any]) -> bool:
    text = " ".join(
        str(row.get(key) or "")
        for key in ("product_name_cn", "capacity", "features", "usage_scenarios", "target_audience", "positioning")
    )
    return bool(re.search(r"\d+(?:\.\d+)?\s*(?:ml|ML|l|L)", text))


def _row_matches_extreme_conflict_constraints(
    row: dict[str, Any],
    *,
    objectives: list[str],
    min_people: int | None,
) -> bool:
    if "lightest" in objectives and not _row_has_explicit_weight_evidence(row):
        return False
    if "max_capacity" in objectives and not _row_has_explicit_capacity_evidence(row):
        return False
    if min_people:
        _, people_max = _row_people_range(row)
        if people_max is None or people_max < min_people:
            return False
    return True


def _apply_extreme_conflict_constraint_notice(
    ranked: list[dict[str, Any]],
    query: str,
) -> tuple[list[dict[str, Any]], list[str]]:
    objectives = _extract_extreme_objectives(query)
    if len(objectives) < 2 or not _requires_all_constraints(query):
        return ranked, []

    min_people = _extract_min_people_constraint(query)
    explicit_matches = []
    for item in ranked:
        row = item.get("row") if isinstance(item.get("row"), dict) else {}
        if _row_matches_extreme_conflict_constraints(row, objectives=objectives, min_people=min_people):
            explicit_matches.append(item)

    if explicit_matches:
        return ranked, []

    requirements = []
    if "lightest" in objectives:
        requirements.append("最轻")
    if "max_capacity" in objectives:
        requirements.append("最大容量")
    if min_people:
        requirements.append(f"{min_people}人适用")
    requirement_text = "、".join(requirements) or "这些硬约束"
    return ranked, [f"当前资料里没有明确同时满足{requirement_text}的锅具，下面只能按接近方案推荐，并说明取舍。"]


async def _recommend_result(
    db: Session,
    user_id: str,
    intent: CustomerIntent,
    *,
    scoped_comparison_candidates: bool = False,
) -> dict:
    cache_key = customer_cache_service.make_key(
        "recommend_result",
        "hybrid_llm_v3",
        id(db),
        intent.recommendation_query or intent.semantic_query or intent.term,
        intent.filters or {},
        intent.negative_filters or {},
        intent.target_skus or [],
        scoped_comparison_candidates,
    )
    cached = customer_cache_service.recommendation_candidate_cache.get(cache_key)
    if cached is not None:
        return cached

    query_text = intent.recommendation_query or intent.semantic_query or intent.term or ""
    base_result = await _recommendation_candidate_result(db, user_id, intent, query_text)
    rows = base_result.get("results") or []
    # If no results with filters, try broader search without filters
    if not rows and (intent.filters or intent.negative_filters):
        fallback_intent = CustomerIntent(
            intent="query_products",
            filters={},
            negative_filters={},
            semantic_query=intent.semantic_query,
            target_skus=[],
            requested_fields=[],
            term=intent.term,
            source_context="question",
        )
        fallback_base = await _recommendation_candidate_result(db, user_id, fallback_intent, query_text)
        if fallback_base and fallback_base.get("results"):
            rows = fallback_base.get("results") or []
            base_result = fallback_base
    if not rows:
        try:
            semantic_fallback = await customer_agent_tool_service.execute_tool_async(
                db,
                user_id=user_id,
                name="hybrid_search_products",
                arguments={
                    "term": "",
                    "filters": intent.filters or {},
                    "semantic_query": intent.recommendation_query or intent.semantic_query or intent.term or "",
                    "fields": [
                        "specs.capacity",
                        "specs.gross_weight_g",
                        "specs.body_material",
                        "specs.heat_source",
                        "specs.power",
                        "business.top_selling_points",
                        "business.usage_scenarios",
                        "business.target_audience",
                        "business.positioning",
                        "business.price_positioning",
                    ],
                    "limit": 50,
                },
            )
        except Exception as exc:
            semantic_fallback = {"results": [], "sources": base_result.get("sources") or [], "error": str(exc)}
        semantic_rows = semantic_fallback.get("results") or []
        if semantic_rows:
            rows = semantic_rows
            base_result = semantic_fallback
    if not rows:
        return _build_response(
            intent=intent,
            answer="当前没有找到可供推荐的产品范围。你可以先给我 SKU、类目，或补充具体场景。",
            sku=None,
            sources=base_result.get("sources") or [],
            results=[],
            steps=_steps(intent, [{"type": "recommend_products", "label": "推荐产品", "detail": "没有可推荐的候选结果", "ok": False}]),
            confidence="low",
            warnings=["当前候选范围为空，暂时无法给出可靠推荐。"],
            anomalies=[],
            suggested_followups=[
                "你可以告诉我更具体的场景，比如露营、泡咖啡、多人使用或轻量携带。",
                "也可以先让我列出这批产品，再继续做推荐。",
            ],
        )

    rows = _filter_picnic_lightweight_set_candidate_rows(query_text, rows)
    if _is_explicit_cookware_recommendation_query(intent, query_text):
        rows = _filter_cookware_recommendation_candidate_rows(rows)

    ranked = _fallback_rank(rows, query_text)
    ranked, people_constraint_warnings = _apply_people_capacity_constraint_to_ranked(
        ranked,
        query_text,
        scoped_comparison_candidates=scoped_comparison_candidates,
    )
    ranked, cookware_set_warnings = _apply_cookware_set_shape_constraint_to_ranked(ranked, query_text)
    ranked, extreme_conflict_warnings = _apply_extreme_conflict_constraint_notice(ranked, query_text)
    best = ranked[0]
    anomalies = _detect_row_anomalies([item["row"] for item in ranked[:3]], intent)
    warnings = [item["message"] for item in anomalies[:2]]
    warnings = [*people_constraint_warnings, *cookware_set_warnings, *extreme_conflict_warnings, *warnings]
    followups = [
        "如果你更看重容量、重量或材质，我可以按这个维度重新排序。",
        "如果你愿意，我也可以把前 3 个候选的差异再展开成对比表。",
    ]
    result_rows = []
    for item in ranked[:5]:
        row = dict(item["row"])
        row["recommendation_match"] = {
            "matched": item.get("matched") or item.get("reasons") or [],
            "missing_or_uncertain": item.get("missing_or_uncertain") or [],
            "score": item.get("score"),
            "score_reason": item.get("score_reason") or "",
        }
        result_rows.append(row)
    supporting_by_sku = await _recommendation_supporting_evidence_by_sku(
        db,
        query_text,
        result_rows,
        per_sku_limit=2,
        query_limit=2,
    )
    for item in ranked[:5]:
        row = item.get("row") if isinstance(item.get("row"), dict) else None
        sku = str((row or {}).get("sku") or "").strip().upper()
        if row is not None and sku:
            row["supporting_evidence"] = supporting_by_sku.get(sku, {})
    for row in result_rows:
        sku = str(row.get("sku") or "").strip().upper()
        if sku:
            row["supporting_evidence"] = supporting_by_sku.get(sku, {})
    answer = await _compose_recommendation_answer(
        db,
        query_text,
        ranked,
        intent,
        warnings,
        anomalies,
        followups,
        result_rows=result_rows,
        supporting_by_sku=supporting_by_sku,
    )
    if scoped_comparison_candidates:
        answer = _shape_recommendation_answer_from_ranked(ranked[:3], question=query_text)
    for warning in [*people_constraint_warnings, *cookware_set_warnings, *extreme_conflict_warnings]:
        if warning and warning not in answer:
            answer = f"{warning}\n{answer}"

    response = _build_response(
        intent=intent,
        answer=answer,
        sku=best["row"].get("sku"),
        sources=base_result.get("sources") or [{"type": "product_search", "label": "推荐候选范围", "count": len(rows)}],
        results=result_rows,
        steps=_steps(intent, [{"type": "recommend_products", "label": "生成推荐结论", "detail": f"候选 {len(rows)} 个，优先推荐 {best['row'].get('sku')}，分数 {best.get('score')}", "ok": True}]),
        confidence="medium" if warnings else "high",
        warnings=warnings,
        anomalies=anomalies,
        suggested_followups=followups,
        answer_type="recommendation",
    )
    recommended_skus = [
        str(item.get("sku") or "").strip().upper()
        for item in result_rows[:3]
        if str(item.get("sku") or "").strip()
    ]
    supporting = await _semantic_supporting_evidence(
        db,
        query_text,
        skus=recommended_skus,
        limit=5,
        query_limit=2,
    )
    if supporting.get("qa") or supporting.get("kb"):
        response["sources"] = [*(response.get("sources") or []), *supporting.get("sources", [])]
        response["evidence"] = supporting.get("evidence")
        _attach_knowledge_enrichment(response, primary_source="product_db", supporting=supporting)
    response["skip_polish"] = True
    customer_cache_service.recommendation_candidate_cache.set(cache_key, response)
    return response


async def _recommendation_candidate_result(db: Session, user_id: str, intent: CustomerIntent, query_text: str) -> dict:
    """Retrieve recommendation candidates without composing a product-query LLM answer."""
    fields = [
        "specs.capacity",
        "specs.gross_weight_g",
        "specs.body_material",
        "specs.heat_source",
        "specs.power",
        "business.top_selling_points",
        "business.usage_scenarios",
        "business.target_audience",
        "business.positioning",
        "business.price_positioning",
    ]
    if intent.target_skus and intent.source_context == "previous_results":
        rows = _filter_rows(
            _rows_for_target_skus(db, intent.target_skus),
            filters=intent.filters,
            negative_filters=intent.negative_filters,
            term="",
        )
        return {
            "ok": True,
            "tool": "filter_previous_results",
            "query": query_text or "上下文推荐结果",
            "results": rows,
            "sources": [{"type": "product_search", "label": "上一轮推荐候选范围", "count": len(rows)}],
        }

    scenario_scope = _extract_recommendation_scenario_scope(intent, query_text)
    effective_term = scenario_scope.get("term") or intent.term or ""
    effective_filters = dict(intent.filters or {})
    effective_filters.update(scenario_scope.get("filters") or {})
    arguments = {
        "term": effective_term,
        "filters": effective_filters,
        "semantic_query": query_text,
        "fields": fields,
        "limit": 50,
    }
    if intent.semantic_query and intent.filters:
        tool_result = await customer_agent_tool_service.execute_tool_async(
            db,
            user_id=user_id,
            name="hybrid_search_products",
            arguments=arguments,
        )
    else:
        tool_result = await customer_agent_tool_service.execute_tool_async(
            db,
            user_id=user_id,
            name="hybrid_search_products",
            arguments=arguments,
        )
    rows = tool_result.get("results") or []
    if scenario_scope.get("guard") == "cooking_set":
        rows = _filter_cooking_set_candidate_rows(rows)
        rows = _filter_picnic_lightweight_set_candidate_rows(query_text, rows)
    if rows and not intent.target_skus:
        rows = await _expand_single_person_cookware_recommendation_rows(
            db,
            user_id=user_id,
            intent=intent,
            query_text=query_text,
            fields=fields,
            base_rows=rows,
        )
        rows = await _expand_cooking_set_recommendation_rows(
            db,
            user_id=user_id,
            scenario_scope=scenario_scope,
            fields=fields,
            base_rows=rows,
        )
        rows = _filter_picnic_lightweight_set_candidate_rows(query_text, rows)
        rows = await _expand_long_prompt_cookware_recommendation_rows(
            db,
            user_id=user_id,
            scenario_scope=scenario_scope,
            fields=fields,
            base_rows=rows,
        )
        rows = await _expand_large_group_cookware_recommendation_rows(
            db,
            user_id=user_id,
            intent=intent,
            query_text=query_text,
            fields=fields,
            base_rows=rows,
        )
    if intent.target_skus:
        rows = _filter_rows(rows or _rows_for_target_skus(db, intent.target_skus), filters=intent.filters, negative_filters=intent.negative_filters, term="")
    rows = _filter_picnic_lightweight_set_candidate_rows(query_text, rows)
    return {
        "ok": True,
        "tool": tool_result.get("tool", "hybrid_search_products"),
        "query": tool_result.get("query") or query_text,
        "results": rows,
        "sources": tool_result.get("sources") or [{"type": "product_search", "label": "推荐候选范围", "count": len(rows)}],
    }


def _is_single_person_cookware_recommendation_query(intent: CustomerIntent, query_text: str) -> bool:
    if not intent or intent.intent != "recommend_products":
        return False
    text = " ".join(
        part
        for part in (
            str(query_text or "").strip(),
            str(intent.recommendation_query or "").strip(),
            str(intent.semantic_query or "").strip(),
            str(intent.term or "").strip(),
        )
        if part
    )
    if not text:
        return False
    cookware_terms = ("锅", "锅具", "单锅", "套锅")
    single_person_terms = ("一个人", "一个人用", "适合一个人", "一人用", "单人", "1人", "1-2人", "1－2人")
    return any(term in text for term in cookware_terms) and any(term in text for term in single_person_terms)


def _single_person_cookware_recall_queries() -> list[str]:
    return ["单人 锅", "1-2人 锅", "单锅", "轻量 锅"]


def _is_large_group_cookware_recommendation_query(intent: CustomerIntent, query_text: str) -> bool:
    if not intent or intent.intent != "recommend_products":
        return False
    text = " ".join(
        part
        for part in (
            str(query_text or "").strip(),
            str(intent.recommendation_query or "").strip(),
            str(intent.semantic_query or "").strip(),
            str(intent.term or "").strip(),
        )
        if part
    )
    if not text:
        return False
    return _looks_like_large_group_cookware_query_text(text)


def _looks_like_large_group_cookware_query_text(text: str) -> bool:
    value = str(text or "")
    if not value:
        return False
    cookware_terms = ("锅", "套锅", "锅具", "炊具", "做饭")
    large_group_terms = (
        "4人以上", "四人以上", "适合4人", "适合 4 人",
        "5人", "五人", "适合5人", "适合 5 人",
        "多人", "大容量", "露营多人",
    )
    if any(term in value for term in cookware_terms) and any(term in value for term in large_group_terms):
        return True
    return any(term in value for term in ("3-4人", "3－4人", "2-4人", "2－4人"))


def _large_group_cookware_recall_queries() -> list[str]:
    return [
        "4人以上 锅具",
        "多人 套锅",
        "大容量 锅具",
        "家庭露营 套锅",
        "3-4人 套锅",
        "2-4人 野餐锅",
        "3-4人 锅具套装",
        "多人 锅具套装",
        "10件套 野餐锅",
    ]


def _extract_recommendation_scenario_scope(intent: CustomerIntent, query_text: str) -> dict[str, Any]:
    if not intent or intent.intent != "recommend_products":
        return {}
    text = " ".join(
        part
        for part in (
            str(query_text or "").strip(),
            str(intent.recommendation_query or "").strip(),
            str(intent.semantic_query or "").strip(),
            str(intent.term or "").strip(),
        )
        if part
    )
    if not text:
        return {}
    if _is_cooking_set_scope_query(text):
        return {
            "term": "锅",
            "filters": {"product.category": "锅具"},
            "guard": "cooking_set",
            "semantic_queries": _cooking_set_recall_queries(text),
        }
    if _is_long_prompt_cookware_main_need_query(text):
        return {
            "term": "锅",
            "filters": {"product.category": "锅具"},
            "guard": "cookware_main_need",
            "semantic_queries": _long_prompt_cookware_recall_queries(text),
        }
    return {}


def _is_explicit_cookware_recommendation_query(intent: CustomerIntent, query_text: str) -> bool:
    if not intent or intent.intent != "recommend_products":
        return False
    text = " ".join(
        part
        for part in (
            str(query_text or "").strip(),
            str(intent.recommendation_query or "").strip(),
            str(intent.semantic_query or "").strip(),
            str(intent.term or "").strip(),
        )
        if part
    ).lower()
    if not text:
        return False
    if any(term in text for term in ("烤盘", "烧烤盘", "griddle", "grill plate", "camping griddle", "配件", "accessory")):
        return False
    has_recommendation_intent = any(term in text for term in ("推荐", "买哪套", "该买哪套", "选哪套", "哪款适合"))
    has_cookware_scope = any(term in text for term in ("锅具", "套锅", "炊具", "锅"))
    return has_recommendation_intent and has_cookware_scope


def _filter_cookware_recommendation_candidate_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    filtered = [row for row in (rows or []) if not _looks_like_non_target_cookware_boundary_candidate(row)]
    return filtered or list(rows or [])


def _looks_like_non_target_cookware_boundary_candidate(row: dict[str, Any]) -> bool:
    text = " ".join(
        str(row.get(key) or "")
        for key in (
            "sku",
            "product_name_cn",
            "product_name_en",
            "name",
            "title",
            "sub_category",
            "category",
            "features",
            "usage_scenarios",
            "target_audience",
            "selling_points",
            "positioning",
        )
    ).lower()
    if not text:
        return False
    strong_boundary_terms = ("烤盘", "烧烤盘", "griddle", "grill plate", "camping griddle", "配件", "accessory")
    if not any(term in text for term in strong_boundary_terms):
        return False
    cookware_positive_terms = ("套锅", "锅具套装", "炊具套装", "炊具组合", "野餐锅", "cookware set", "cook set")
    return not any(term in text for term in cookware_positive_terms)


def _is_cooking_set_scope_query(text: str) -> bool:
    normalized = str(text or "")
    has_set = any(term in normalized for term in ("套装", "套锅", "锅具套装", "炊具套装"))
    has_scene = any(term in normalized for term in ("露营", "野餐", "户外"))
    has_cooking_need = any(term in normalized for term in ("煮饭", "做饭", "烧水", "烹饪", "野炊"))
    has_picnic_pair_need = any(term in normalized for term in ("两人", "2人", "双人", "轻便", "预算中等", "野餐"))
    return has_set and has_scene and (has_cooking_need or has_picnic_pair_need)


def _cooking_set_recall_queries(text: str) -> list[str]:
    queries = ["套锅", "炊具套装", "野餐锅", "锅具套装"]
    normalized = str(text or "")
    if any(term in normalized for term in ("3个人", "3人", "4人", "4个人", "3-4", "2-4", "多人")):
        queries.extend(["3-4人 套锅", "2-4人 野餐锅"])
    if any(term in normalized for term in ("两人", "2人", "双人", "轻便", "预算中等", "野餐")):
        queries.extend(["1-2人 野餐锅", "轻量 套锅"])
    deduped: list[str] = []
    for item in queries:
        if item not in deduped:
            deduped.append(item)
    return deduped


def _filter_cooking_set_candidate_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    filtered: list[dict[str, Any]] = []
    for row in rows or []:
        text = " ".join(
            str(row.get(key) or "")
            for key in ("sku", "product_name_cn", "product_name_en", "category", "features", "usage_scenarios", "target_audience")
        )
        category = str(row.get("category") or "")
        capacity = str(row.get("capacity") or "").strip()
        if not text:
            continue
        if "锅" not in category:
            continue
        if capacity in {"", "/"}:
            continue
        if _looks_like_non_cooking_set_candidate(row):
            continue
        if not _looks_like_cooking_set_candidate(row):
            continue
        filtered.append(row)
    return filtered


def _filter_picnic_lightweight_set_candidate_rows(query_text: str, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not _is_picnic_lightweight_set_mid_budget_scope(query_text):
        return rows
    filtered = [
        row
        for row in rows or []
        if not _looks_like_single_backpacking_set_outside_picnic_scope(row)
    ]
    return filtered or list(rows or [])


def _is_picnic_lightweight_set_mid_budget_scope(text: str) -> bool:
    normalized = str(text or "")
    return (
        any(term in normalized for term in ("野餐", "周末野餐", "公园野餐"))
        and any(term in normalized for term in ("套装", "套锅", "件套", "野餐锅", "炊具套装", "锅具套装"))
        and any(term in normalized for term in ("轻便", "轻量", "便携", "收纳"))
        and any(term in normalized for term in ("两个人", "两人", "2人", "双人"))
        and any(term in normalized for term in ("预算中等", "中等预算", "预算适中", "预算"))
    )


def _looks_like_single_backpacking_set_outside_picnic_scope(row: dict[str, Any]) -> bool:
    text = _cooking_set_candidate_text(row)
    if not text:
        return False
    picnic_terms = ("野餐", "周末野餐", "公园野餐", "家庭野餐", "野餐锅")
    two_person_terms = ("2-3人", "2-3 人", "两个人", "两人", "双人", "小家庭")
    single_backpacking_terms = (
        "单人背包客",
        "单人露营",
        "单人野宿",
        "极限轻量",
        "轻量徒步",
        "背包旅行",
        "速穿",
        "荒野求生",
    )
    if any(term in text for term in picnic_terms + two_person_terms):
        return False
    return any(term in text for term in single_backpacking_terms)


def _looks_like_cooking_set_candidate(row: dict[str, Any]) -> bool:
    text = _cooking_set_candidate_text(row)
    if not text:
        return False
    positive_terms = (
        "套锅", "套装锅", "锅具套装", "炊具套装", "锅具组合", "锅壶套装",
        "野餐锅", "野营锅", "件套", "全套", "cookset", "cookware set",
    )
    return any(term in text for term in positive_terms)


def _looks_like_non_cooking_set_candidate(row: dict[str, Any]) -> bool:
    text = _cooking_set_candidate_text(row)
    if not text or _looks_like_cooking_set_candidate(row):
        return False
    negative_terms = (
        "水壶", "茶壶", "杯", "杯子", "水杯", "炉具", "炉子", "酒精炉", "气炉",
        "卡式炉", "配件", "餐具", "菜板", "烤盘", "煎盘", "单锅", "炒锅", "煎锅",
    )
    return any(term in text for term in negative_terms)


def _cooking_set_candidate_text(row: dict[str, Any]) -> str:
    values = []
    for key in (
        "sku",
        "product_name_cn",
        "product_name_en",
        "name",
        "title",
        "category",
        "features",
        "usage_scenarios",
        "target_audience",
        "selling_points",
        "description",
    ):
        value = row.get(key)
        if value:
            values.append(str(value))
    return " ".join(values).lower()


def _is_long_prompt_cookware_main_need_query(text: str) -> bool:
    normalized = str(text or "")
    if not normalized:
        return False
    if _is_long_prompt_cookware_purchase_choice_question(normalized):
        return True
    recommendation_tail = any(term in normalized for term in ("最后问哪款产品适合", "最后推荐哪款", "最后问哪款适合", "最后帮我推荐"))
    narrative_context = any(term in normalized for term in ("攻略", "天气", "海拔"))
    cooking_need = any(term in normalized for term in ("煮饭", "做饭", "烹饪", "野炊"))
    people_or_portable = any(term in normalized for term in ("三人", "3人", "2-3人", "轻便", "轻量", "露营"))
    explicit_stove_target = any(term in normalized for term in ("炉具", "炉子", "炉头", "防风炉", "分体炉", "气炉", "燃气炉"))
    explicit_water_target = any(term in normalized for term in ("水壶", "凉水", "补水", "饮水"))
    explicit_pot_target = any(term in normalized for term in ("锅", "锅具", "套锅", "炊具"))
    return recommendation_tail and narrative_context and cooking_need and people_or_portable and not explicit_stove_target and not explicit_water_target and not explicit_pot_target


def _is_long_prompt_cookware_purchase_choice_question(text: str) -> bool:
    normalized = str(text or "")
    if not normalized:
        return False
    if len(normalized) < 35 and not any(term in normalized for term in ("最后问", "最后想问", "最后我想问")):
        return False
    purchase_tail_terms = (
        "我该买哪套锅",
        "该买哪套锅",
        "该买哪套",
        "买哪套",
        "选哪套",
        "推荐哪套",
        "哪款适合",
    )
    tail_markers = ("最后问", "最后想问", "最后我想问", "最后")
    has_tail_purchase = any(term in normalized for term in purchase_tail_terms)
    if any(marker in normalized for marker in tail_markers):
        tail_text = normalized[max(normalized.rfind(marker) for marker in tail_markers if marker in normalized):]
        has_tail_purchase = any(term in tail_text for term in purchase_tail_terms)
    if not has_tail_purchase:
        return False
    if not any(term in normalized for term in ("锅", "套锅", "锅具", "炊具", "做饭烧水套装")):
        return False
    scenario_hits = sum(
        1
        for term in ("三人", "3人", "轻便", "轻量", "煮饭", "做饭", "烧水", "露营", "海拔", "天气")
        if term in normalized
    )
    return scenario_hits >= 2


def _is_pure_copywriting_without_product_recommendation(text: str) -> bool:
    normalized = str(text or "")
    if not normalized:
        return False
    if not any(term in normalized for term in ("写一段", "生成一段", "发一段", "写个攻略", "写个露营计划", "整理一段文案")):
        return False
    if not any(term in normalized for term in ("不要推荐产品", "不用推荐产品", "不需要推荐产品", "先不要推荐", "不要给我推荐")):
        return False
    if _is_long_prompt_cookware_purchase_choice_question(normalized):
        return False
    return not any(term in normalized for term in ("我该买哪套锅", "该买哪套", "买哪套", "选哪套", "推荐哪套", "哪款适合", "哪个适合我"))


def _long_prompt_cookware_recall_queries(text: str) -> list[str]:
    normalized = str(text or "")
    queries = ["露营 锅具", "煮饭 锅具", "套锅"]
    if any(term in normalized for term in ("三人", "3人", "2-3人")):
        queries.append("三人 锅具")
    if any(term in normalized for term in ("轻便", "轻量")):
        queries.append("轻量 锅具")
    deduped: list[str] = []
    for item in queries:
        if item not in deduped:
            deduped.append(item)
    return deduped


def _filter_cookware_main_need_candidate_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    filtered: list[dict[str, Any]] = []
    for row in rows or []:
        category = str(row.get("category") or "")
        if "锅" not in category:
            continue
        category_text = " ".join(
            str(row.get(key) or "")
            for key in ("category", "sub_category", "product_name_cn", "product_name_en", "features", "usage_scenarios", "target_audience")
        )
        if any(term in category_text for term in ("燃料", "气罐", "耗材", "调料瓶", "登山杖", "防潮垫")):
            continue
        product_name = str(row.get("product_name_cn") or row.get("product_name_en") or "")
        primary_text = " ".join(
            str(row.get(key) or "")
            for key in ("product_name_cn", "product_name_en", "capacity", "features")
        )
        weak_part_terms = ("煎锅", "煎盘", "平底锅")
        strong_main_terms = ("套锅", "件套", "野餐锅", "单锅", "煮锅", "水壶", "多人", "3-4人", "2-3人")
        if any(term in product_name for term in weak_part_terms) and not any(term in primary_text for term in strong_main_terms):
            continue
        filtered.append(row)
    return filtered


def _merge_recommendation_rows_by_sku(primary_rows: list[dict[str, Any]], extra_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    merged: list[dict[str, Any]] = []
    seen: set[str] = set()
    for row in [*extra_rows, *primary_rows]:
        if not isinstance(row, dict):
            continue
        sku = str(row.get("sku") or "").strip().upper()
        if not sku or sku in seen:
            continue
        merged.append(row)
        seen.add(sku)
    return merged


def _annotate_recall_query(rows: list[dict[str, Any]], semantic_query: str) -> list[dict[str, Any]]:
    annotated: list[dict[str, Any]] = []
    query_text = str(semantic_query or "").strip()
    for row in rows or []:
        if not isinstance(row, dict):
            continue
        item = dict(row)
        if query_text:
            existing = str(item.get("semantic_match") or "").strip()
            item["semantic_match"] = f"{existing} {query_text}".strip() if existing else query_text
        annotated.append(item)
    return annotated


async def _expand_single_person_cookware_recommendation_rows(
    db: Session,
    *,
    user_id: str,
    intent: CustomerIntent,
    query_text: str,
    fields: list[str],
    base_rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    if not _is_single_person_cookware_recommendation_query(intent, query_text):
        return base_rows
    expanded_rows: list[dict[str, Any]] = []
    for semantic_query in _single_person_cookware_recall_queries():
        try:
            result = await customer_agent_tool_service.execute_tool_async(
                db,
                user_id=user_id,
                name="hybrid_search_products",
                arguments={
                    "term": intent.term or "",
                    "filters": intent.filters or {},
                    "semantic_query": semantic_query,
                    "fields": fields,
                    "limit": 20,
                },
            )
        except Exception:
            continue
        expanded_rows.extend(_annotate_recall_query(result.get("results") or [], semantic_query))
    if not expanded_rows:
        return base_rows
    return _merge_recommendation_rows_by_sku(base_rows, expanded_rows)


async def _expand_cooking_set_recommendation_rows(
    db: Session,
    *,
    user_id: str,
    scenario_scope: dict[str, Any],
    fields: list[str],
    base_rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    if scenario_scope.get("guard") != "cooking_set":
        return base_rows
    expanded_rows: list[dict[str, Any]] = []
    for semantic_query in scenario_scope.get("semantic_queries") or []:
        try:
            result = await customer_agent_tool_service.execute_tool_async(
                db,
                user_id=user_id,
                name="hybrid_search_products",
                arguments={
                    "term": scenario_scope.get("term") or "",
                    "filters": scenario_scope.get("filters") or {},
                    "semantic_query": semantic_query,
                    "fields": fields,
                    "limit": 20,
                },
            )
        except Exception:
            continue
        expanded_rows.extend(_annotate_recall_query(result.get("results") or [], semantic_query))
    merged_rows = _merge_recommendation_rows_by_sku(base_rows, expanded_rows)
    return _filter_cooking_set_candidate_rows(merged_rows)


async def _expand_long_prompt_cookware_recommendation_rows(
    db: Session,
    *,
    user_id: str,
    scenario_scope: dict[str, Any],
    fields: list[str],
    base_rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    if scenario_scope.get("guard") != "cookware_main_need":
        return base_rows
    expanded_rows: list[dict[str, Any]] = []
    for semantic_query in scenario_scope.get("semantic_queries") or []:
        try:
            result = await customer_agent_tool_service.execute_tool_async(
                db,
                user_id=user_id,
                name="hybrid_search_products",
                arguments={
                    "term": scenario_scope.get("term") or "",
                    "filters": scenario_scope.get("filters") or {},
                    "semantic_query": semantic_query,
                    "fields": fields,
                    "limit": 20,
                },
            )
        except Exception:
            continue
        expanded_rows.extend(_annotate_recall_query(result.get("results") or [], semantic_query))
    merged_rows = _merge_recommendation_rows_by_sku(base_rows, expanded_rows)
    return _filter_cookware_main_need_candidate_rows(merged_rows)


async def _expand_large_group_cookware_recommendation_rows(
    db: Session,
    *,
    user_id: str,
    intent: CustomerIntent,
    query_text: str,
    fields: list[str],
    base_rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    if not _is_large_group_cookware_recommendation_query(intent, query_text):
        return base_rows
    expanded_rows: list[dict[str, Any]] = []
    effective_term = intent.term or "锅"
    effective_filters = dict(intent.filters or {})
    effective_filters.setdefault("product.category", "锅具")
    for semantic_query in _large_group_cookware_recall_queries():
        try:
            result = await customer_agent_tool_service.execute_tool_async(
                db,
                user_id=user_id,
                name="hybrid_search_products",
                arguments={
                    "term": effective_term,
                    "filters": effective_filters,
                    "semantic_query": semantic_query,
                    "fields": fields,
                    "limit": 20,
                },
            )
        except Exception:
            continue
        expanded_rows.extend(_annotate_recall_query(result.get("results") or [], semantic_query))
    if not expanded_rows:
        return base_rows
    return _merge_recommendation_rows_by_sku(base_rows, expanded_rows)


def _augment_cooking_set_recommendation_candidates(db: Session, query_text: str, rows: list[dict]) -> list[dict]:
    return rows


async def _compose_recommendation_answer(
    db: Session,
    question: str,
    ranked: list[dict],
    intent: CustomerIntent,
    warnings: list[str],
    anomalies: list[dict[str, Any]],
    followups: list[str],
    result_rows: list[dict[str, Any]] | None = None,
    supporting_by_sku: dict[str, dict[str, list[dict[str, str]]]] | None = None,
) -> str:
    """Compose a recommendation answer from ranked products."""
    result_rows = result_rows or []
    if result_rows:
        product_data_list = _recommendation_product_data(db, result_rows, supporting_by_sku=supporting_by_sku)
        answer = await _finalize_recommendation_answer(
            db,
            question=question,
            intent=intent,
            product_data_list=product_data_list,
            warnings=warnings,
            anomalies=anomalies,
            followups=followups,
        )
        if answer:
            return _shape_recommendation_answer_text(answer, ranked, question=question)
    return _compose_recommendation_answer_template(ranked, intent, warnings, anomalies, followups)


def _compose_recommendation_answer_template(
    ranked: list[dict],
    intent: CustomerIntent,
    warnings: list[str],
    anomalies: list[dict[str, Any]],
    followups: list[str],
) -> str:
    if not ranked:
        return "目前没有找到合适的产品推荐，你可以换个场景或条件试试。"
    return _shape_recommendation_answer_from_ranked(ranked[:3], question=intent.recommendation_query or "")


def _recommendation_product_data(
    db: Session,
    rows: list[dict[str, Any]],
    *,
    supporting_by_sku: dict[str, dict[str, list[dict[str, str]]]] | None = None,
) -> list[dict[str, Any]]:
    product_data_list: list[dict[str, Any]] = []
    supporting_by_sku = supporting_by_sku or {}
    for row in rows[:8]:
        sku = str(row.get("sku") or "").strip()
        if not sku:
            continue
        try:
            detail = product_service.get_product_detail(db, sku)
        except Exception:
            detail = dict(row)
        if isinstance(detail, dict):
            specs = detail.get("specs") or {}
            business = detail.get("business") or {}
            product_data_list.append(
                {
                    "sku": detail.get("sku") or sku,
                    "product_name_cn": detail.get("product_name_cn"),
                    "product_name_en": detail.get("product_name_en"),
                    "category": detail.get("category"),
                    "specs": {
                        "capacity": specs.get("capacity"),
                        "gross_weight_g": specs.get("gross_weight_g"),
                        "body_material": specs.get("body_material"),
                        "surface_finish": specs.get("surface_finish"),
                        "heat_source": specs.get("heat_source"),
                    },
                    "business": {
                        "top_selling_points": business.get("top_selling_points"),
                        "usage_scenarios": business.get("usage_scenarios"),
                        "target_audience": business.get("target_audience"),
                        "positioning": business.get("positioning"),
                    },
                    "supporting_evidence": supporting_by_sku.get(str((detail.get("sku") or sku)).strip().upper(), {}),
                    "recommendation_match": row.get("recommendation_match") or {},
                }
            )
    return product_data_list


async def _finalize_recommendation_answer(
    db: Session,
    *,
    question: str,
    intent: CustomerIntent,
    product_data_list: list[dict[str, Any]],
    warnings: list[str],
    anomalies: list[dict[str, Any]],
    followups: list[str],
) -> str | None:
    system_prompt = (
        "你是alocs爱路客的产品客服助手。"
        "【核心规则，最高优先级】"
        "1. 严禁引入retrieved_products之外的产品事实、参数、认证、价格或库存。"
        "2. 工具结果里没有的信息，必须说\"暂无此数据\"，不得推断或编造。"
        "3. 用户没有问到的话题不要主动引入。"
        "【任务】"
        "根据用户需求和retrieved_products里的完整产品数据，组织自然的推荐回答。"
        "先给首选推荐，再说明为什么匹配用户需求；理由必须引用具体参数、场景、人群、容量、重量、材质、卖点、supporting_evidence或recommendation_match。"
        "优先使用supporting_evidence里的同SKU QA/知识库摘要来解释适用场景，不要把容量、材质、类目逐项罗列成字段清单。"
        "每个推荐至少要回答：它为什么适合当前需求、适合什么场景、有什么限制或注意事项。"
        "可以列出备选，但不要写\"与本轮需求匹配\"这种空泛理由。"
        "如果某项信息资料未写明，要诚实说明暂无此数据。"
        "【格式要求】"
        "不使用Markdown表格，不使用**或###。只输出JSON：{\"answer\":\"...\"}。"
    )
    payload = {
        "question": question,
        "intent_hint": "recommend_products",
        "recommendation_query": intent.recommendation_query or intent.semantic_query or intent.term,
        "retrieved_products": product_data_list,
        "warnings": warnings,
        "anomalies": anomalies,
        "suggested_followups": followups,
    }
    try:
        content = await customer_llm_service.chat_completion(
            db,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": json.dumps(payload, ensure_ascii=False, default=str)},
            ],
            temperature=0.2,
            max_tokens=1600,
            purpose="recommend_answer",
        )
    except Exception:
        return None
    return _answer_from_llm_content(content) or None

async def _propose_delete_result(db: Session, user_id: str, intent: CustomerIntent) -> dict:
    actions = []
    for sku in intent.target_skus:
        result = await customer_agent_tool_service.execute_tool_async(
            db,
            user_id=user_id,
            name="propose_delete_product",
            arguments={"sku": sku},
        )
        if result.get("action"):
            actions.append(result["action"])

    followups = ["确认前我建议你先核对 SKU 范围；如果你只是想下架或清空字段，也可以改成更轻量的操作。"]
    answer = f"我已经为 {len(actions)} 个 SKU 生成待确认删除动作。请先确认范围，确认后才会真正执行。"
    return _build_response(
        intent=intent,
        answer=answer,
        sku=intent.target_skus[0] if len(intent.target_skus) == 1 else None,
        sources=[{"type": "agent_action", "label": "待确认删除动作", "count": len(actions)}],
        actions=actions,
        results=[],
        steps=_steps(intent, [{"type": "propose_delete_product", "label": "生成删除确认动作", "detail": f"{len(actions)} 条", "ok": True}]),
        confidence="high",
        warnings=[],
        anomalies=[],
        suggested_followups=followups,
    )


async def _propose_update_result(db: Session, user_id: str, intent: CustomerIntent) -> dict:
    result = await customer_agent_tool_service.execute_tool_async(
        db,
        user_id=user_id,
        name="propose_update_product_field",
        arguments={
            "skus": intent.target_skus,
            "field": intent.requested_fields[0] if intent.requested_fields else "",
            "new_value": intent.exact_value,
        },
    )
    actions = result.get("actions") or []
    field_label = intent.requested_fields[0] if intent.requested_fields else "目标字段"
    answer = f"我已经为 {len(actions)} 个 SKU 生成待确认修改动作，准备把“{field_label}”改成“{intent.exact_value}”。确认前还不会写库。"
    return _build_response(
        intent=intent,
        answer=answer,
        sku=intent.target_skus[0] if len(intent.target_skus) == 1 else None,
        sources=[{"type": "agent_action", "label": "待确认修改动作", "count": len(actions)}],
        actions=actions,
        results=[],
        steps=_steps(intent, [{"type": "propose_update_product_field", "label": "生成修改确认动作", "detail": f"{len(actions)} 条", "ok": bool(actions)}]),
        confidence="high" if actions else "low",
        warnings=[] if actions else ["没有生成待确认动作，请检查字段名称或 SKU 是否正确。"],
        anomalies=[],
        suggested_followups=["如果你担心改错，我也可以先帮你把这些 SKU 的原值列出来。"],
    )


def _clarify_result(intent: CustomerIntent) -> dict:
    return _build_response(
        intent=intent,
        answer=intent.clarification_question,
        sku=None,
        sources=[{"type": "agent_clarification", "label": "需要澄清"}],
        results=[],
        steps=_steps(intent, [{"type": "clarify", "label": "追问澄清", "detail": intent.clarification_question, "ok": True}]),
        confidence="low",
        needs_clarification=True,
        warnings=[],
        anomalies=[],
        suggested_followups=[],
    )


async def attach_supporting_knowledge_evidence(
    db: Session,
    response: dict,
    question: str,
    *,
    primary_source: str = "existing_route",
) -> dict:
    """Attach QA/KB supporting evidence without changing the route or answer."""
    if not isinstance(response, dict):
        return response
    if response.get("answer_metadata", {}).get("knowledge_enrichment"):
        return response
    query = str(question or "").strip()
    if not query:
        return response
    try:
        supporting = await _semantic_supporting_evidence(db, query, skus=None, limit=5, query_limit=2)
    except Exception:
        return response
    if not (supporting.get("qa") or supporting.get("kb")):
        return response
    sources = response.get("sources") if isinstance(response.get("sources"), list) else []
    response["sources"] = [*sources, *supporting.get("sources", [])]
    evidence = response.get("evidence") if isinstance(response.get("evidence"), list) else []
    response["evidence"] = [*evidence, *supporting.get("evidence", [])[1:]]
    _attach_knowledge_enrichment(response, primary_source=primary_source, supporting=supporting)
    debug = response.get("debug") if isinstance(response.get("debug"), dict) else {}
    debug["supporting_knowledge_attached"] = True
    response["debug"] = debug
    return response


def _parse_english_name_filter(text: str) -> CustomerIntent | None:
    lower = text.lower()
    mentions_english_name = any(item in text for item in ("英文名", "英文名称", "商品英文名称")) or "english name" in lower
    if not mentions_english_name:
        return None

    exact_match = re.search(r"(?:英文名|英文名称|商品英文名称)\s*(?:为|是|等于|=)\s*([A-Za-z0-9_-]+)", text, flags=re.I)
    if exact_match:
        value = exact_match.group(1).strip()
        if value not in ("数字", "纯数字", "全数字"):
            return CustomerIntent(
                intent="query_products",
                filters={"product.product_name_en": value},
                special_filter="english_name_exact",
                exact_value=value,
            )

    if any(item in text for item in ("包含数字", "带数字", "含数字")):
        return CustomerIntent(intent="query_products", special_filter="english_name_contains_digit")
    if any(item in text for item in ("为数字", "是数字", "纯数字", "全数字")):
        return CustomerIntent(intent="query_products", special_filter="english_name_numeric")
    if "数字" in text:
        return CustomerIntent(
            intent="clarify",
            clarification_question="你是想查“英文名为纯数字”的产品，还是“英文名里包含数字”的产品？",
        )
    return None


def _ensure_negative_filter(negative_filters: dict[str, Any], field_path: str, value: str) -> None:
    """Append a value to a negative filter field, storing multiple values as a list."""
    existing = negative_filters.get(field_path)
    if existing:
        if isinstance(existing, list):
            existing.append(value)
        else:
            negative_filters[field_path] = [existing, value]
    else:
        negative_filters[field_path] = value


def _parse_structured_filters(text: str) -> tuple[dict[str, Any], dict[str, Any]]:
    filters: dict[str, Any] = {}
    negative_filters: dict[str, Any] = {}
    alcohol_stove_support_pattern = (
        r"(?:同时)?(?:支持|能用|可以用|可用|适配)\s*酒精炉"
        r"|(?:可以|可|能)(?:直接)?放在\s*酒精炉上(?:用|使用)(?:吗)?"
        r"|酒精炉上(?:能用|可以用|可用|适合|使用)"
        r"|适合\s*酒精炉"
        r"|酒精炉可用"
        r"|\balcohol\s*stove\b"
    )

    field_filters = (
        (("主体材质", "炉体材质", "材质", "材料"), "specs.body_material"),
        (("表面处理", "表面工艺", "处理工艺", "工艺"), "specs.surface_finish"),
        (("适用热源", "热源", "燃料", "适用燃料"), "specs.heat_source"),
        (("容量",), "specs.capacity"),
    )
    for labels, field_path in field_filters:
        label_pattern = "|".join(re.escape(label) for label in labels)
        match = re.search(rf"(?:{label_pattern})\s*(?:为|是|=|等于|包含)\s*([^，,。？?\s]+)", text, flags=re.I)
        if match:
            value = _normalize_structured_filter_value(field_path, _clean_filter_value(match.group(1)))
            if value and value not in {"多少", "什么", "啥", "几"}:
                filters[field_path] = value
                continue
        value = _reverse_field_filter_value(text, labels)
        if value:
            value = _normalize_structured_filter_value(field_path, value)
            if value and value not in {"多少", "什么", "啥", "几", "哪些", "哪个", "哪款"} and not any(word in value for word in ("什么", "多少", "哪个", "哪款")):
                filters[field_path] = value

    person = re.search(r"负责人\s*(?:是|为|=)?\s*([A-Za-z0-9_\-]+)", text, flags=re.I)
    if person:
        filters["product.person_in_charge"] = person.group(1)
    person_not = re.search(r"负责人\s*(?:不是|不为|≠|!=)\s*([A-Za-z0-9_\-]+)", text, flags=re.I)
    if person_not:
        negative_filters["product.person_in_charge"] = person_not.group(1)

    category = re.search(r"(?:类目|品类|分类)\s*(?:是|为|=)?\s*([\u4e00-\u9fa5A-Za-z0-9_\-]+)", text)
    if category:
        filters["product.category"] = category.group(1)
    category_not = re.search(r"(?:类目|品类|分类)\s*(?:不是|不为|≠|!=)\s*([\u4e00-\u9fa5A-Za-z0-9_\-]+)", text)
    if category_not:
        negative_filters["product.category"] = category_not.group(1)

    # Colloquial: detect category from product type keywords
    if not filters.get("product.category"):
        detail_subject = _detail_subject_from_question(text)
        if detail_subject and _looks_like_named_product_term(detail_subject):
            return filters, negative_filters
        positive_text = _positive_category_text(text)
        category_probe_text = re.sub(
            alcohol_stove_support_pattern,
            " ",
            positive_text,
            flags=re.I,
        )
        category_probe_text = re.sub(
            r"(?:适用热源|热源|燃料)\s*(?:为|是|=|等于|包含)?\s*酒精炉",
            " ",
            category_probe_text,
            flags=re.I,
        )
        cat_map = [
            ("水壶", "水壶"), ("户外水壶", "水壶"), ("水具", "水具"), ("水杯", "水具"), ("杯", "水具"),
            ("锅具", "锅具"), ("锅子", "锅具"), ("套锅", "锅具"), ("单锅", "锅具"), ("煎锅", "锅具"), ("炒锅", "锅具"), ("烤盘", "锅具"), ("锅", "锅具"),
            ("酒精炉", "炉具"), ("气炉", "炉具"), ("卡式炉", "炉具"), ("炉具", "炉具"), ("炉子", "炉具"), ("炉", "炉具"),
            ("餐具", "餐具"), ("勺", "餐具"), ("收纳包", "收纳包具"), ("包具", "收纳包具"),
        ]
        for kw, cat in cat_map:
            if any(kw and kw in str(value) for value in filters.values()):
                continue
            if kw in category_probe_text:
                filters["product.category"] = cat
                break

    if not filters.get("specs.body_material"):
        direct_body_material = re.search(
            r"(?:主体(?:材质)?|锅体|炉体)\s*(?:是|为|=|等于)\s*([^，,。、；;。？?\s]+)",
            text,
            flags=re.I,
        )
        if direct_body_material:
            value = _normalize_structured_filter_value("specs.body_material", _clean_filter_value(direct_body_material.group(1)))
            if value and not any(word in value for word in ("什么", "哪些", "哪个", "哪款")):
                filters["specs.body_material"] = value
    if not filters.get("specs.body_material"):
        material_match = re.search(
            r"([\u4e00-\u9fa5A-Za-z0-9_\-\s]{2,40}?)(?:材质|材料)的(?:锅具|锅|产品|商品|炉具|炉)",
            text,
        )
        if material_match:
            value = _normalize_structured_filter_value("specs.body_material", _clean_filter_value(material_match.group(1)))
            if value and not any(word in value for word in ("什么", "哪些", "哪个", "哪款")):
                filters["specs.body_material"] = value
    if not filters.get("specs.body_material"):
        colloquial_material_match = re.search(
            r"(?:(?:里面|其中|这些|这批)(?:哪些|哪个|哪款)?|(?:哪些|哪个|哪款))\s*(?:是|为)?\s*([\u4e00-\u9fa5A-Za-z0-9_\-\s]{2,40}?)\s*(?:材质|材料)(?:的)?(?:产品|商品|锅具|锅|炉具|炉)?",
            text,
        )
        if colloquial_material_match:
            value = _normalize_structured_filter_value("specs.body_material", _clean_filter_value(colloquial_material_match.group(1)))
            if value and not any(word in value for word in ("什么", "哪些", "哪个", "哪款")):
                filters["specs.body_material"] = value
    if not filters.get("specs.heat_source"):
        alcohol_support_match = re.search(
            alcohol_stove_support_pattern,
            text,
            flags=re.I,
        )
        if alcohol_support_match:
            filters["specs.heat_source"] = "酒精炉"
    if not filters.get("specs.surface_finish") and any(term in text for term in ("不粘", "不沾")) and any(term in text for term in ("涂层", "带", "有没有", "哪些", "里", "中")):
        filters["specs.surface_finish"] = "不粘"

    lifecycle = re.search(r"(?:生命周期|状态)\s*(?:是|为|=)?\s*([一-龥A-Za-z0-9_\-]+)", text)
    if lifecycle:
        filters["product.lifecycle_status"] = lifecycle.group(1)

    # Series/brand/name exclusion: "不要XXX系列/品牌的", "排除XXX", "去掉XXX"
    for negative_word in FOLLOWUP_NARROW_WORDS:
        series_not = re.search(
            negative_word + r"\s*([一-龥A-Za-z0-9_\-]+)\s*(?:系列|品牌|牌子|的|产品)?",
            text
        )
        if series_not and series_not.group(1):
            neg_value = series_not.group(1)
            # Filter by both series and product name since user may not distinguish
            _ensure_negative_filter(negative_filters, "product.series", neg_value)
            _ensure_negative_filter(negative_filters, "product.product_name_cn", neg_value)
            break

    return filters, negative_filters


def _positive_category_text(text: str) -> str:
    cleaned = str(text or "")
    cleaned = re.sub(r"(?:不要|别要|不想要|排除|去掉|剔除|不是)\s*[\u4e00-\u9fa5A-Za-z0-9_\-]+", " ", cleaned)
    return cleaned


def _clean_filter_value(value: str) -> str:
    cleaned = re.split(
        r"(的(?:产品|商品|锅具|锅|炉具|炉|水具|杯|壶)|有哪些|哪些|给我|我想|想改|改成|，|,|。|？|\?)",
        str(value or "").strip(),
        maxsplit=1,
    )[0]
    return cleaned.strip()


def _normalize_structured_filter_value(field_path: str, value: str) -> str:
    cleaned = str(value or "").strip()
    if field_path == "specs.body_material":
        cleaned = re.sub(r"^(?:你们有没?有|有没有|有没|帮我找(?:一下)?|帮我查(?:一下)?|查(?:一下|下)?|想找|我想找)\s*", "", cleaned)
    if field_path == "specs.surface_finish" and cleaned.endswith("工艺"):
        cleaned = cleaned[:-2]
    if field_path == "specs.surface_finish":
        cleaned = cleaned.replace("不沾", "不粘")
    return cleaned.strip()


def _reverse_field_filter_value(text: str, labels: tuple[str, ...]) -> str:
    source = str(text or "")
    positions = [(source.find(label), label) for label in labels if source.find(label) > 0]
    if not positions:
        return ""
    index, label = min(positions, key=lambda item: item[0])
    prefix = source[:index]
    if not any(marker in prefix for marker in ("是", "为", "含有", "包含")):
        return ""
    prefix = re.split(r"[，,。？?\s]", prefix)[-1]
    prefix = re.sub(r"^(?:里面|其中|这些|这批)?(?:哪些|哪个|哪款)?(?:是|为|含有|包含)?", "", prefix).strip()
    if not prefix or any(word in prefix for word in ("什么", "多少", "哪个", "哪款")):
        return ""
    if prefix in {"里面", "其中", "这些", "这批", "哪些", "哪个", "哪款"}:
        return ""
    return _clean_filter_value(prefix)


def _parse_semantic_query(text: str) -> str:
    triggers = ("适合", "场景", "露营", "咖啡", "泡咖啡", "卖点", "特色", "情绪价值", "目标人群",
                "能用", "可以用", "能不能", "是否支持", "是否适合",
                "登山", "徒步", "爬山", "野炊", "野餐", "自驾", "轻量", "便携",
                "酒精", "气罐", "燃料", "火力", "烧水", "煮饭", "轻", "重",
                "带什么", "带哪个", "选哪个", "买哪个", "哪个好")
    if any(word in text for word in triggers):
        cleaned = re.sub(
            r"(有哪些|哪些|产品|商品|负责人\s*(?:是|为|=)?\s*[A-Za-z0-9_\-]+|负责人\s*(?:不是|不为|!=)\s*[A-Za-z0-9_\-]+|类目\s*(?:是|为|=)?\s*[\u4e00-\u9fa5A-Za-z0-9_\-]+)",
            "",
            text,
        )
        return cleaned.strip(" ，。？")
    return ""


def _parse_recommendation_query(text: str, semantic_query: str) -> str:
    if any(word in text for word in RECOMMEND_WORDS):
        cleaned = re.sub(
            r"(推荐|更适合|最适合|哪个好|哪款更好|优先|这些里|这批里|换一个|不要|排除|去掉|剔除|排掉)",
            "",
            text
        )
        return cleaned.strip(" ，。？") or semantic_query
    return semantic_query


def _parse_term(text: str, filters: dict[str, Any], semantic_query: str) -> str:
    if any(word in text for word in FOLLOWUP_NARROW_WORDS):
        return ""
    quoted = _quoted_product_name(text)
    if quoted:
        return quoted
    if _has_explicit_field_filter(text):
        return ""
    if filters and any(word in text for word in ("有哪些", "哪些", "哪几款", "产品", "商品")):
        return ""
    subject = _detail_subject_from_question(text)
    if subject:
        return subject
    if semantic_query:
        # Extract product type keywords for better search
        for kw in ["锅", "炉", "杯", "壶", "碗", "盘", "刀", "铲", "勺", "桌", "椅", "灯", "帐篷", "睡袋"]:
            if kw in text:
                return kw
        # If no product type found, return empty to use semantic search
        return ""
    cleaned = re.sub(r"^(我想知道|想知道|请问|帮我查一下|查一下)", "", text)
    cleaned = re.sub(r"(有哪些|哪些|产品|商品|查询|找|列出|现在|这些里|这批里)", "", cleaned)
    cleaned = re.sub(
        r"的(?:容量|材质|颜色|重量|负责人|英文名|英文名称|类目|品质)(?:信息)?(?:是(?:多少|什么)?|是多少|是什么|多少)?$",
        "",
        cleaned,
    )
    cleaned = re.sub(r"的(?:信息|资料|详情)$", "", cleaned)
    if filters and len(cleaned.strip(" ，。？")) < 3:
        return ""
    return cleaned.strip(" ，。？")


def _quoted_product_name(text: str) -> str:
    match = re.search(r"[「“](.+?)[」”]", str(text or ""))
    if not match:
        return ""
    value = match.group(1).strip()
    return value if len(value) >= 2 else ""


def _has_explicit_field_filter(text: str) -> bool:
    match = re.search(
        r"(?:主体材质|材质|材料|表面处理|表面工艺|工艺|适用热源|热源|燃料|容量)\s*(?:为|是|=|等于|包含)\s*([^，,。？?\s]+)",
        str(text or ""),
    )
    if not match:
        return False
    value = _clean_filter_value(match.group(1))
    return bool(value and value not in {"多少", "什么", "啥", "几", "哪些", "有啥"})


def _parse_update_intent(text: str, target_skus: list[str]) -> CustomerIntent | None:
    match = re.search(r"把\s+(.+?)\s*的\s*(.+?)\s*(?:都)?改成\s*(.+)$", text)
    if match:
        sku_text, field_label, new_value = match.groups()
        skus = _extract_skus(sku_text) or target_skus
        if not skus:
            return CustomerIntent(intent="clarify", clarification_question="请告诉我要修改哪些 SKU。")
        return CustomerIntent(intent="propose_update", target_skus=skus, requested_fields=[field_label.strip()], exact_value=new_value.strip())

    match = re.search(r"(?:修改|更改|更新|改)\s*(?:他|他的|它|它的|这个|这款|该产品)?\s*的?\s*(.+?)\s*(?:为|成|改成)\s*(.+)$", text)
    if not match:
        return None
    field_label, new_value = match.groups()
    skus = target_skus
    if not skus:
        return CustomerIntent(intent="clarify", clarification_question="请告诉我要修改哪些 SKU。")
    return CustomerIntent(intent="propose_update", target_skus=skus, requested_fields=[field_label.strip()], exact_value=new_value.strip())


def _run_special_product_filter(db: Session, intent: CustomerIntent) -> list[dict]:
    rows = (
        db.query(Product, ProductSpecs, ProductBusiness, ProductContent)
        .outerjoin(ProductSpecs, ProductSpecs.product_id == Product.id)
        .outerjoin(ProductBusiness, ProductBusiness.product_id == Product.id)
        .outerjoin(ProductContent, ProductContent.product_id == Product.id)
        .filter(Product.product_name_en.isnot(None))
        .limit(500)
        .all()
    )
    results = []
    for product, specs, business, content in rows:
        english_name = str(product.product_name_en or "").strip()
        matched = False
        label = "英文名称"
        if intent.special_filter == "english_name_numeric":
            matched = english_name.isdigit()
            label = "英文名称为纯数字"
        elif intent.special_filter == "english_name_contains_digit":
            matched = bool(re.search(r"\d", english_name))
            label = "英文名称包含数字"
        elif intent.special_filter == "english_name_exact":
            matched = english_name.lower() == intent.exact_value.lower()
            label = f"英文名称等于 {intent.exact_value}"
        if matched:
            results.append(customer_agent_service._result_row(product, specs, business, content, label))
    return results[:50]


def _rows_for_target_skus(db: Session, skus: list[str]) -> list[dict]:
    rows = []
    for sku in skus:
        resolved_sku = _resolve_existing_sku(db, sku)
        detail = product_service.get_product_detail(db, resolved_sku)
        rows.append(_detail_to_result_row(detail, matched_by="上下文结果"))
    return rows


def _resolve_existing_sku(db: Session, sku: str) -> str:
    text = str(sku or "").strip()
    product = db.query(Product).filter(Product.sku == text).first()
    if product:
        return product.sku
    product = db.query(Product).filter(Product.sku.ilike(text)).first()
    if product:
        return product.sku
    if text.upper().startswith("MINT-"):
        candidate = text[5:].strip()
        if candidate:
            product = db.query(Product).filter(Product.sku == candidate).first()
            if product:
                return product.sku
            product = db.query(Product).filter(Product.sku.ilike(candidate)).first()
            if product:
                return product.sku
    return text


def _detail_to_result_row(detail: dict[str, Any], *, matched_by: str) -> dict[str, Any]:
    specs = detail.get("specs") or {}
    business = detail.get("business") or {}
    return {
        "sku": detail.get("sku"),
        "barcode": detail.get("barcode"),
        "product_name_cn": detail.get("product_name_cn"),
        "product_name_en": detail.get("product_name_en"),
        "brand": detail.get("brand"),
        "series": detail.get("series"),
        "category": detail.get("category"),
        "sub_category": detail.get("sub_category"),
        "product_level": detail.get("product_level"),
        "lifecycle_status": detail.get("lifecycle_status"),
        "person_in_charge": detail.get("person_in_charge"),
        "quality_note": detail.get("quality_note"),
        "status_note": detail.get("status_note"),
        "capacity": specs.get("capacity"),
        "body_material": specs.get("body_material"),
        "color": specs.get("color"),
        "surface_finish": specs.get("surface_finish"),
        "heat_source": specs.get("heat_source"),
        "power": specs.get("power"),
        "matched_by": matched_by,
        "features": _first_nonempty([
            specs.get("technical_advantages"),
            business.get("top_selling_points"),
            business.get("usage_scenarios"),
        ]),
        "usage_scenarios": business.get("usage_scenarios"),
        "target_audience": business.get("target_audience"),
        "positioning": business.get("positioning"),
    }


def _filter_rows(rows: list[dict], *, filters: dict[str, Any], negative_filters: dict[str, Any], term: str) -> list[dict]:
    def _matches_any(text: str, value: Any) -> bool:
        text_lower = text.lower()
        if isinstance(value, list):
            return any(v.lower() in text_lower for v in value)
        return str(value).lower() in text_lower

    def match_field(row: dict[str, Any], field_path: str, value: Any) -> bool:
        text = str(_row_value(row, field_path) or "").lower()
        if _matches_any(text, value):
            return True
        if (
            str(field_path) == "specs.heat_source"
            and str(row.get("matched_by") or "") == "上下文结果"
            and _matches_any(_same_sku_context_evidence_text(row), value)
        ):
            return True
        return False

    filtered = rows
    for field_path, value in (filters or {}).items():
        filtered = [row for row in filtered if match_field(row, field_path, value)]
    for field_path, value in (negative_filters or {}).items():
        filtered = [row for row in filtered if not match_field(row, field_path, value)]
    if term:
        term_lower = term.lower()
        filtered = [
            row for row in filtered
            if any(term_lower in str(item or "").lower() for item in row.values())
        ]
    return filtered


def _is_alcohol_stove_cookware_query(intent: CustomerIntent, question: str, *, rows: list[dict] | None = None) -> bool:
    if not intent or intent.intent != "query_products":
        return False
    filters = intent.filters or {}
    if str(filters.get("specs.heat_source") or "") != "酒精炉":
        return False
    text = str(question or "")
    if not any(term in text for term in ("酒精炉", "alcohol stove")):
        return False
    lowered = text.lower()
    if any(term in lowered for term in ("煎盘", "烤盘", "煎烤盘", "griddle", "grill pan", "fry pan", "frying pan", "pan plate")):
        return False
    if str(filters.get("product.category") or "") == "锅具":
        return True
    if str(intent.source_context or "") != "previous_results":
        return False
    candidate_rows = [row for row in (rows or []) if isinstance(row, dict)]
    cookware_rows = [row for row in candidate_rows if str(row.get("category") or "") == "锅具"]
    return bool(cookware_rows) and len(cookware_rows) >= max(1, len(candidate_rows) // 2)


def _is_griddle_like_cookware_row(row: dict[str, Any]) -> bool:
    haystack = " ".join(
        str(row.get(key) or "")
        for key in (
            "sku",
            "product_name_cn",
            "product_name_en",
            "category",
            "sub_category",
            "capacity",
            "features",
            "usage_scenarios",
            "target_audience",
            "positioning",
            "semantic_match",
            "long_description_cn",
        )
    ).lower()
    excluded_terms = (
        "griddle",
        "grill pan",
        "grill plate",
        "fry pan",
        "frying pan",
        "pan plate",
        "烤盘",
        "烧烤盘",
        "煎烤盘",
        "煎盘",
    )
    if not any(term in haystack for term in excluded_terms):
        return False
    positive_set_terms = (
        "套锅",
        "锅具套装",
        "炊具套装",
        "炊具组合",
        "野餐锅",
        "野营锅",
        "cookware set",
        "cook set",
        "pot set",
    )
    return not any(term in haystack for term in positive_set_terms)


def _is_water_container_like_cookware_row(row: dict[str, Any]) -> bool:
    haystack = " ".join(
        str(row.get(key) or "")
        for key in ("sku", "product_name_cn", "product_name_en", "category", "sub_category", "features", "usage_scenarios")
    ).lower()
    return any(term in haystack for term in ("水壶", "壶", "kettle", "bottle", "flask", "cup", "杯"))


def _alcohol_stove_support_verdict(text: str) -> bool | None:
    value = str(text or "").strip().lower()
    if not value or ("酒精炉" not in value and "alcohol stove" not in value):
        return None
    if re.search(r"(不支持|未显示支持|不适合|不建议|不能|不可).{0,8}(酒精炉|alcohol stove)", value):
        return False
    if re.search(r"(支持|适合|可用|可以用|能用|兼容|适配).{0,8}(酒精炉|alcohol stove)", value):
        return True
    if re.search(r"(酒精炉|alcohol stove).{0,8}(可用|适用|适配|兼容|支持)", value):
        return True
    if re.search(r"(^|[\s,，、/|\n])(?:酒精炉|alcohol stove)(?=$|[\s,，、/|\n])", value):
        return True
    return None


def _same_sku_alcohol_stove_support_evidence(db: Session | None, sku: str) -> bool:
    if db is None:
        return False
    evidence_text = _best_same_sku_evidence_text(
        db,
        sku=sku,
        supporting=None,
        term_groups=[
            ("酒精炉", "alcohol stove"),
            ("支持", "适合", "可用", "可以用", "能用", "兼容", "适配"),
        ],
    )
    if not evidence_text:
        return False
    verdict = _alcohol_stove_support_verdict(evidence_text)
    if verdict is not None:
        return verdict
    normalized = str(evidence_text or "").lower()
    return "酒精炉" in normalized or "alcohol stove" in normalized


def _row_supports_alcohol_stove(row: dict[str, Any], db: Session | None = None) -> bool:
    direct_heat_source = str(row.get("heat_source") or "")
    verdict = _alcohol_stove_support_verdict(direct_heat_source)
    if verdict is not None:
        return verdict
    evidence_text = _same_sku_context_evidence_text(row)
    verdict = _alcohol_stove_support_verdict(evidence_text)
    if verdict is True:
        return True
    sku = str(row.get("sku") or "").strip().upper()
    if sku and _same_sku_alcohol_stove_support_evidence(db, sku):
        return True
    return False


def _case71_eligible_cookware_row(row: dict[str, Any], db: Session | None = None) -> bool:
    if str(row.get("category") or "") != "锅具":
        return False
    if _is_griddle_like_cookware_row(row):
        return False
    if _is_water_container_like_cookware_row(row):
        return False
    return _row_supports_alcohol_stove(row, db)


def _case71_filter_summary_override(intent: CustomerIntent, rows: list[dict[str, Any]]) -> str | None:
    if not rows:
        return None
    if str((intent.filters or {}).get("product.category") or "") != "锅具":
        return None
    if str((intent.filters or {}).get("specs.heat_source") or "") != "酒精炉":
        return None
    return "已按酒精炉热源字段或同SKU兼容证据收窄到可用于酒精炉的锅具列表。"


def _narrow_alcohol_stove_cookware_query_rows(
    db: Session,
    rows: list[dict],
    *,
    intent: CustomerIntent,
    question: str,
    source_rows: list[dict] | None = None,
) -> list[dict]:
    if not _is_alcohol_stove_cookware_query(intent, question, rows=source_rows or rows):
        return rows
    base_rows = source_rows or rows or []
    narrowed = [row for row in base_rows if _case71_eligible_cookware_row(row, db)]
    seen = {str(row.get("sku") or "").strip().upper() for row in narrowed if str(row.get("sku") or "").strip()}
    supplement_rows = customer_agent_service.search_products(db, "", limit=120, filters={"product.category": "锅具"})
    for row in supplement_rows:
        sku = str(row.get("sku") or "").strip().upper()
        if not sku or sku in seen:
            continue
        if not _case71_eligible_cookware_row(row, db):
            continue
        narrowed.append(row)
        seen.add(sku)
        if len(narrowed) >= 8:
            break
    return narrowed or rows


def _same_sku_context_evidence_text(row: dict[str, Any]) -> str:
    values = []
    for key in (
        "features",
        "usage_scenarios",
        "target_audience",
        "positioning",
        "semantic_match",
        "top_selling_points",
        "technical_advantages",
        "long_description_cn",
        "long_description_en",
    ):
        value = row.get(key)
        if value:
            values.append(str(value))
    return " ".join(values).lower()


def _focus_detail_rows(rows: list[dict], intent: CustomerIntent, question_text: str) -> list[dict]:
    if not rows or not intent.requested_fields:
        return rows
    if _is_multi_product_detail_question(question_text):
        return rows

    focus_terms = _detail_focus_terms(intent, question_text)
    if not focus_terms:
        return rows

    ranked = []
    for row in rows:
        score = _detail_focus_score(row, focus_terms, intent.requested_fields)
        if score > 0:
            ranked.append((score, row))
    if not ranked:
        return rows

    ranked.sort(
        key=lambda item: (
            item[0],
            bool(item[1].get("sku")),
            bool(item[1].get("product_name_cn")),
        ),
        reverse=True,
    )
    best_score = ranked[0][0]
    if best_score < 15:
        return rows
    top_rows = [row for score, row in ranked if score == best_score]
    if len(top_rows) == 1:
        return top_rows
    # If several rows tie, keep the most specific one instead of dumping a wide list.
    return [top_rows[0]]


def _is_unmatched_named_detail_question(intent: CustomerIntent, rows: list[dict], question_text: str) -> bool:
    if not intent.requested_fields:
        return False
    if intent.target_skus:
        return False
    if _is_multi_product_detail_question(question_text):
        return False
    terms = _detail_focus_terms(intent, question_text)
    if not terms:
        return False
    named_terms = [term for term in terms if _looks_like_named_product_term(term)]
    if not named_terms:
        return False
    return not any(_row_matches_named_term(row, named_terms) for row in rows)


def _is_material_safety_question(text: str) -> bool:
    value = str(text or "")
    material_terms = ("材质", "材料", "主体材质", "304", "不锈钢", "耐腐蚀", "食品级")
    cert_terms = ("认证", "FDA", "LFGB")
    return any(term in value for term in material_terms) and any(term in value for term in cert_terms + material_terms)


def _compose_material_safety_answer(detail: dict[str, Any], question: str, material: str) -> str:
    certifications = detail.get("certifications") or []
    cert_lines = _format_certification_lines(certifications)
    food_grade_hint = _detail_has_food_grade_hint(detail)
    wants_fda = "FDA" in str(question or "").upper()
    wants_cert_list = any(term in str(question or "") for term in ("有哪些认证", "什么认证", "认证"))

    if certifications:
        if wants_fda:
            has_fda = any(_certification_matches(cert, "FDA") for cert in certifications)
            cert_prefix = "有FDA认证" if has_fda else "未检索到FDA认证"
        elif wants_cert_list:
            cert_prefix = "认证包括"
        else:
            cert_prefix = "认证信息包括"
        parts = [f"材质是 {material}。", f"{cert_prefix}：" + "；".join(cert_lines) + "。"]
        if food_grade_hint:
            parts.append("卖点中标注了食品级材质，但这里仍以认证文件和资料原文为准。")
        return "".join(parts)

    if food_grade_hint:
        return f"材质是 {material}；卖点中标注了食品级材质，但认证文件暂未注明，建议联系人工客服确认。"

    return f"材质是 {material}；认证信息暂未注明，建议联系人工客服确认。"


def _format_certification_lines(certifications: list[dict[str, Any]]) -> list[str]:
    lines: list[str] = []
    for cert in certifications:
        if not isinstance(cert, dict):
            continue
        name = str(cert.get("certification_name") or cert.get("certification_code") or "").strip()
        desc = str(cert.get("description") or "").strip()
        if not name:
            continue
        lines.append(f"{name}" + (f"（{desc}）" if desc else ""))
    return lines


def _certification_matches(cert: dict[str, Any], keyword: str) -> bool:
    key = str(keyword or "").strip().upper()
    if not key or not isinstance(cert, dict):
        return False
    return key in {
        str(cert.get("certification_name") or "").strip().upper(),
        str(cert.get("certification_code") or "").strip().upper(),
    }


def _detail_has_food_grade_hint(detail: dict[str, Any]) -> bool:
    def _iter_texts(value: Any):
        if value is None:
            return
        if isinstance(value, str):
            yield value
        elif isinstance(value, dict):
            for item in value.values():
                yield from _iter_texts(item)
        elif isinstance(value, list):
            for item in value:
                yield from _iter_texts(item)

    for section_name in ("business", "content", "specs"):
        section = detail.get(section_name) or {}
        for text in _iter_texts(section):
            if "食品级" in str(text):
                return True
    return False


def _has_specs_filter(intent: CustomerIntent) -> bool:
    return any(str(field).startswith("specs.") for field in (intent.filters or {}))


async def _compose_filter_answer(db: Session, question: str, rows: list[dict], intent: CustomerIntent) -> str:
    return _compose_filter_answer_template(rows, intent)


def _compose_filter_answer_template(rows: list[dict], intent: CustomerIntent) -> str:
    display_labels = {
        "specs.body_material": "主体材质",
        "specs.surface_finish": "表面处理",
        "specs.heat_source": "适用热源",
    }
    canonical_fields = {
        "specs.body_material": "body_material",
        "specs.surface_finish": "surface_finish",
        "specs.heat_source": "heat_source",
    }
    filter_labels = []
    canonical_summaries = []
    for field_path, value in (intent.filters or {}).items():
        label = display_labels.get(str(field_path), _field_label(field_path))
        filter_labels.append(f"{label}包含 {value}")
        canonical_key = canonical_fields.get(str(field_path))
        if canonical_key:
            canonical_summaries.append(f"{canonical_key}含{value}的SKU列表")
    condition = "；".join(filter_labels) or "未提供"
    if not rows:
        return f"筛选条件：{condition}。\n当前资料中未检索到符合条件的产品。"
    summary_override = _case71_filter_summary_override(intent, rows)
    lines = [
        f"筛选条件：{condition}。",
        *((summary_override,) if summary_override else tuple(f"已返回{summary}。" for summary in canonical_summaries)),
        "当前资料中检索到以下产品：",
    ]
    for row in rows[:20]:
        sku = row.get("sku") or ""
        name = row.get("product_name_cn") or row.get("product_name_en") or sku
        facts = []
        for field_path in (intent.filters or {}):
            key = str(field_path).split(".", 1)[1] if "." in str(field_path) else str(field_path)
            value = row.get(key)
            if value not in (None, ""):
                label = display_labels.get(str(field_path), _field_label(field_path))
                facts.append(f"{label}：{value}")
        lines.append(f"- {name}（{sku}）" + (f"，{'；'.join(facts)}" if facts else ""))
    if len(rows) > 20:
        lines.append(f"还有 {len(rows) - 20} 款未展开。")
    return "\n".join(lines)


async def _finalize_filter_answer(
    db: Session,
    *,
    question: str,
    rows: list[dict],
    intent: CustomerIntent,
    product_data_list: list[dict[str, Any]],
) -> str | None:
    system_prompt = (
        "你是alocs爱路客的产品客服助手。"
        "【核心规则，最高优先级】"
        "1. 严禁引入retrieved_products之外的产品事实、参数、认证、价格或库存。"
        "2. 工具结果里没有的信息，必须说\"暂无此数据\"，不得推断或编造。"
        "3. 用户没有问到的话题不要主动引入。"
        "【任务】"
        "根据用户问题和retrieved_products里的完整产品数据，组织自然的筛选结果回答。"
        "筛选类问题要列出符合条件的产品，并说明每款为什么符合条件；不要只说\"找到N条资料\"。"
        "如果结果较多，可以分组或压缩说明，但必须保留SKU和产品名。"
        "【格式要求】"
        "不使用Markdown表格，不使用**或###。只输出JSON：{\"answer\":\"...\"}。"
    )
    payload = {
        "question": question,
        "intent_hint": "filter_products",
        "filters": intent.filters,
        "retrieved_products": product_data_list,
        "search_rows": rows,
    }
    try:
        content = await customer_llm_service.chat_completion(
            db,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": json.dumps(payload, ensure_ascii=False, default=str)},
            ],
            temperature=0.2,
            max_tokens=2500,
            purpose="filter_answer",
        )
    except Exception:
        return None
    return _answer_from_llm_content(content) or None


def _looks_like_named_product_term(term: str) -> bool:
    text = customer_agent_service.normalize_search_text(term).strip()
    if len(text) < 3:
        return False
    if text in {"锅具", "炉具", "水具", "餐具", "杯具", "锅", "炉", "杯", "壶", "包"}:
        return False
    if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9\-]{2,}", text):
        return True
    return bool(re.search(r"(?:套锅|炒锅|煎锅|单锅|野营锅|锅|酒精炉|气炉|炉|杯套装|杯|水壶|壶|包)$", text))


def _row_matches_named_term(row: dict[str, Any], terms: list[str]) -> bool:
    name_values = [
        row.get("sku"),
        row.get("barcode"),
        row.get("product_name_cn"),
        row.get("product_name_en"),
    ]
    normalized_names = [
        customer_agent_service.normalize_search_text(value).lower()
        for value in name_values
        if value
    ]
    for raw_term in terms:
        term = customer_agent_service.normalize_search_text(raw_term).lower()
        if not term:
            continue
        compact = re.sub(r"\s+", "", term)
        for name in normalized_names:
            name_compact = re.sub(r"\s+", "", name)
            if term == name or term in name or name in term:
                return True
            if compact and name_compact and (compact in name_compact or name_compact in compact):
                return True
    return False


def _detail_focus_terms(intent: CustomerIntent, question_text: str) -> list[str]:
    terms: list[str] = []
    for candidate in (
        intent.term,
        intent.recommendation_query,
        intent.semantic_query,
        question_text,
    ):
        value = _detail_subject_from_question(candidate)
        if value and value not in terms:
            terms.append(value)
    for candidate in (intent.term, intent.recommendation_query, intent.semantic_query):
        value = str(candidate or "").strip()
        if value and len(value) >= 2 and value not in terms:
            terms.append(value)
    return terms


def _detail_subject_from_question(text: str) -> str:
    cleaned = str(text or "").strip(" ，。？！；;")
    cleaned = re.sub(r"[（(][^）)]*(?:不打完整名称|不用打完整名称|不是完整名称|简称|简写)[）)]", "", cleaned)
    cleaned = re.sub(r"^(?:帮我|麻烦|请|想|我想|我想问下|我想问一下)?(?:查一下|查下|看一下|看下|问一下|问下|帮忙查一下)", "", cleaned).strip(" ，。？！；;")
    if not cleaned:
        return ""
    quoted = _quoted_subject_from_question(cleaned)
    if quoted:
        return quoted
    fuzzy_people_cookware_subject = _fuzzy_people_cookware_subject(cleaned)
    if fuzzy_people_cookware_subject:
        return fuzzy_people_cookware_subject
    wh_field_match = re.match(
        r"^(?P<subject>.+?)是(?:什么|啥|哪种|哪些)?(?:主体材质|材质|手柄材质|把手材质|锅盖材质|锅体材质|容量|重量|热源|燃料|功率|认证|出口认证).*$",
        cleaned,
    )
    if wh_field_match:
        subject = wh_field_match.group("subject").strip(" ，。？！；;")
        if subject and len(subject) >= 2:
            return subject
    direct_field_match = re.match(
        r"^(?P<subject>.+?)(?:的)?(?:主体材质|材质|手柄材质|把手材质|锅盖材质|锅体材质|容量|重量|热源|燃料|功率|认证|出口认证)(?:是|为|有|是多少|多少|吗|呢|？|。|$).*$",
        cleaned,
    )
    if direct_field_match:
        subject = direct_field_match.group("subject").strip(" ，。？！；;")
        if subject and len(subject) >= 2:
            return subject
    patterns = (
        r"^(?P<subject>.+?)(?:是|为)?(?:什么产品|哪款产品).*$",
        r"^(?P<subject>.+?)(?:有多重|多重|重不重|重量多少|容量多大|容量多少|多大容量|有什么禁止操作|有哪些禁止操作|有啥禁止操作|什么禁止操作|怎么辨别正品|如何辨别正品|怎样辨别正品|正品怎么辨别|适合哪些场景|适合什么场景|适用哪些场景|适用什么场景)(?:呢|吗|？|。|$).*$",
        r"^(?P<subject>.+?)(?:的)?(?:尺寸|包装|配件|净重|毛重|适合几个人|适合几人|几个人|几人使用|涂层|不粘涂层)(?:是|为|有|有啥|有哪些|是什么|多少|几|吗|呢|？|。|$).*$",
        r"^(?P<subject>.+?)(?:有没有|是否有|有无)(?:不粘涂层|涂层|配件).*$",
        r"^(?P<subject>.+?)(?:是不是|是否是)(?:304不锈钢|不锈钢|木头|铝合金).*$",
        r"^(?P<subject>.+?)(?:的)?(?:主体|配件|手柄|锅体|盖子|锅盖|把手|煎盘|炉体|炉架|壶身|壶嘴|杯身|杯盖)?(?:是|为|用的是|用的|可以用|能用)?(?:什么|啥|哪种|哪些)?(?:材质|颜色|重量|容量|热源|燃料|功率|表面处理|认证|出口认证|安全性|食品级)(?:.*)?$",
        r"^(?P<subject>.+?)(?:的(?:主要)?(?:卖点|负责人|容量|材质|颜色|重量|英文名|英文名称|类目|品质情况|信息|资料|详情|参数|场景|适用场景))(?:是|为|有|有啥|有哪些|是什么|什么|多少|几|吗|呢|？|。|$).*$",
        r"^(?P<subject>.+?)(?:的)?(?:主要)?(?:卖点|负责人|容量|材质|颜色|重量|英文名|英文名称|类目|品质情况|信息|资料|详情|参数|场景|适用场景)(?:是|为|有|有啥|有哪些|是什么|什么|多少|几|吗|呢|？|。|$).*$",
    )
    for pattern in patterns:
        match = re.match(pattern, cleaned)
        if match:
            subject = match.group("subject").strip(" ，。？！；;")
            if subject and len(subject) >= 2:
                return subject
    return ""


def _fuzzy_people_cookware_subject(text: str) -> str:
    value = str(text or "").strip()
    if not value:
        return ""
    match = re.search(
        r"(?P<subject>\d+\s*[-－]\s*\d+人[^，。？！；;（）()]{0,20}?(?:野营锅|套锅|单锅|炒锅|煎锅|锅具|锅)(?:\d+件套|\d+件|套装)?)",
        value,
    )
    if not match:
        return ""
    return match.group("subject").strip(" ，。？！；;")


def _quoted_subject_from_question(text: str) -> str:
    value = str(text or "")
    match = re.search(r"[「『“\"](?P<subject>[^」』”\"]{2,80})[」』”\"]", value)
    if not match:
        return ""
    subject = match.group("subject").strip(" ，。？！；;")
    return subject if len(subject) >= 2 else ""


def _detail_focus_score(row: dict[str, Any], focus_terms: list[str], requested_fields: list[str]) -> int:
    text_bits = [
        str(row.get("sku") or ""),
        str(row.get("product_name_cn") or ""),
        str(row.get("product_name_en") or ""),
        str(row.get("category") or ""),
        str(row.get("sub_category") or ""),
        str(row.get("features") or ""),
        str(row.get("semantic_match") or ""),
    ]
    field_values = row.get("field_values")
    if isinstance(field_values, dict):
        text_bits.extend(str(value) for value in field_values.values() if value)
    haystack = " ".join(text_bits).lower()
    name = str(row.get("product_name_cn") or row.get("product_name_en") or "").lower()
    sku = str(row.get("sku") or "").lower()

    score = 0
    for term in focus_terms:
        candidate = customer_agent_service.normalize_search_text(term).lower()
        if not candidate:
            continue
        if candidate == sku:
            score += 120
            continue
        if candidate == name:
            score += 110
            continue
        if candidate in name:
            score += 70
            continue
        if name and name in candidate:
            score += 55
            continue
        if candidate in haystack:
            score += 35
    if requested_fields:
        score += 5
    return score


def _is_multi_product_detail_question(text: str) -> bool:
    normalized = str(text or "")
    return any(term in normalized for term in ("哪些", "哪几", "几个", "几款", "全部", "所有", "列出", "清单", "一览", "对比", "比较"))


def _is_multi_product_filter_query(text: str, subject: str = "") -> bool:
    normalized = str(text or "")
    if _is_multi_product_detail_question(normalized):
        return True
    if _is_generic_multi_product_subject(subject):
        return True
    return any(term in normalized for term in ("产品", "商品", "SKU", "sku", "锅里", "锅中", "炉具里", "其中", "里面")) and any(
        term in normalized for term in ("列一下", "列出", "有没有", "哪些", "哪几", "带", "包含", "支持")
    )


def _is_generic_multi_product_subject(text: str) -> bool:
    normalized = re.sub(r"\s+", "", str(text or "").strip(" ，。？！；;"))
    if not normalized:
        return False
    normalized = re.sub(r"^(?:你们|咱们|店里|公司|品牌|目前|现在)", "", normalized)
    return normalized in {
        "哪些产品",
        "哪些商品",
        "哪些SKU",
        "哪些sku",
        "有哪些产品",
        "有哪些商品",
        "有什么产品",
        "什么产品",
        "哪几款产品",
        "哪几款商品",
        "全部产品",
        "所有产品",
    }


def _row_value(row: dict[str, Any], field_path: str) -> Any:
    field_name = field_path.split(".", 1)[1] if "." in field_path else field_path
    return row.get(field_name)


def _compose_row_answer(
    rows: list[dict],
    intent: CustomerIntent,
    warnings: list[str],
    anomalies: list[dict[str, Any]],
    followups: list[str],
    qa_results: list[dict] | None = None,
    kb_results: list[dict] | None = None,
) -> str:
    label = _intent_label(intent)
    if not rows:
        lines = [f"先说结论：目前没有找到{label}的产品。"]
        if intent.source_context == "previous_results":
            lines.append("我是按上一轮结果继续筛选的，这一轮条件下没有保留下来的 SKU。")
        else:
            lines.append("我已经按当前条件查过，但暂时没有命中。")
        if followups:
            lines.append(f"下一步建议：{followups[0]}")
        return "\n".join(lines)

    # When user asked for specific fields and few results, show field details
    if intent.requested_fields and len(rows) <= 3:
        field_paths = [_resolve_query_field(f) for f in intent.requested_fields]
        field_paths = [p for p in field_paths if p]
        if field_paths:
            labels = [_field_label(p) for p in field_paths]
            lines = [f"先说结论：已整理 {', '.join(labels)} 信息。"]
            lines.append("依据如下：")
            for row in rows:
                name = row.get("product_name_cn") or row.get("product_name_en") or ""
                parts = [f"SKU={row['sku']}"]
                if name:
                    parts.append(f"名称={name}")
                for i, fp in enumerate(field_paths):
                    text = _field_text(row, fp)
                    if text:
                        parts.append(f"{labels[i]}={text}")
                lines.append("- " + "; ".join(parts))
            if followups:
                lines.append(f"下一步建议：{followups[0]}")
            return "\n".join(lines)

    lines = [f"先说结论：共找到 {len(rows)} 个{label}的候选产品。"]
    if intent.source_context == "previous_results":
        lines.append("这是基于上一轮结果继续收窄后的名单。")
    lines.append("依据如下：")
    for index, item in enumerate(rows[:8], start=1):
        lines.append(f"{index}. {_row_brief(item)}")
    if len(rows) > 8:
        lines.append(f"还有 {len(rows) - 8} 个结果没有展开。")
    if len(rows) > 10 and followups:
        lines.append(f"下一步建议：{followups[0]}")
    elif followups:
        lines.append(f"下一步建议：{followups[0]}")
    return "\n".join(lines)
def _compose_detail_answer(
    db: Session | None,
    rows: list[dict],
    field_paths: list[str],
    warnings: list[str],
    anomalies: list[dict[str, Any]],
    followups: list[str],
    qa_results: list[dict] | None = None,
    kb_results: list[dict] | None = None,
    question: str = "",
) -> str:
    qa_results = qa_results or []
    kb_results = kb_results or []
    if not field_paths:
        return "我还没有识别到你想查询的具体字段，请告诉我要看容量、材质、卖点、负责人等哪类信息。"
    if not rows:
        return "没有找到对应产品。请确认 SKU 或产品名是否正确。"

    row = rows[0]
    title = row.get("product_name_cn") or row.get("product_name_en") or ""
    sku_val = row["sku"]
    prefix = f"{title}（{sku_val}）" if title else sku_val
    question_text = str(question or "")
    usage_instruction_value = str(
        (row.get("field_values") or {}).get("适配情况")
        or (row.get("field_values") or {}).get("使用说明")
        or ""
    ).strip()
    heat_source_value = str((row.get("field_values") or {}).get("热源") or (row.get("field_values") or {}).get("燃料") or "").strip()
    if len(rows) == 1 and _looks_like_water_container_capability_question(question_text):
        capability_label = _water_container_capability_label(question_text)
        if usage_instruction_value and usage_instruction_value != "暂无":
            if any(term in usage_instruction_value for term in ("装冷水", "装凉水", "装热水", "装饮用水", "装水", "盛水")):
                return f"{prefix}：当前资料显示{usage_instruction_value}。"
        evidence_answer = _extract_water_container_capability_evidence_from_qa_kb(
            db=db,
            sku=row.get("sku") or "",
            question=question_text,
            qa_results=qa_results,
            kb_results=kb_results,
        )
        if evidence_answer:
            if usage_instruction_value and usage_instruction_value != "暂无":
                return f"{prefix}：{evidence_answer} 当前资料里的使用说明为{usage_instruction_value}。"
            return f"{prefix}：{evidence_answer}"
        if usage_instruction_value and usage_instruction_value != "暂无":
            return f"{prefix}：当前资料未直接标明是否可以{capability_label}。当前资料里的使用说明为{usage_instruction_value}。"
        return f"{prefix}：当前资料未直接标明是否可以{capability_label}。"
    if (
        len(rows) == 1
        and any(term in question_text for term in ("酒精炉", "酒精"))
        and any(term in question_text for term in ("能用", "可以用", "支持", "适合", "能不能", "是否支持"))
    ):
        if heat_source_value and heat_source_value != "暂无":
            if "酒精炉" in heat_source_value or "酒精" in heat_source_value:
                return f"{prefix}：支持酒精炉。当前资料显示适用热源为{heat_source_value}。"
            return f"{prefix}：当前资料未显示支持酒精炉。当前资料显示适用热源为{heat_source_value}。"
        return f"{prefix}：当前资料暂未提供是否支持酒精炉。"
    lines = [prefix]
    supplement_note = "（补充资料）" if qa_results or kb_results else ""
    display_labels = {
        "热源": "适用热源",
        "燃料": "燃料 / 热源",
    }
    for key, value in (row.get("field_values") or {}).items():
        if value in (None, "", "暂无"):
            continue
        display_key = display_labels.get(str(key), str(key))
        if display_key == "材质" and any(term in question_text for term in ("主体材质", "锅体材质", "炉体材质")):
            display_key = "主体材质"
        value_text = str(value).strip()
        if display_key in {"适用热源", "燃料 / 热源"} and any(term in question_text for term in ("酒精炉", "酒精")) and any(
            term in question_text for term in ("能用", "可以用", "支持", "适合", "能不能", "是否支持")
        ):
            if "酒精炉" in value_text or "酒精" in value_text:
                lines.append(f"支持酒精炉。当前资料显示适用热源为{value_text}{supplement_note}")
            else:
                lines.append(f"当前资料未显示支持酒精炉。当前资料显示适用热源为{value_text}{supplement_note}")
            continue
        if display_key == "材质" and "、" in value_text and any(term in value_text for term in ("木", "白蜡木")):
            primary_material, handle_material = [part.strip() for part in value_text.split("、", 1)]
            if primary_material:
                lines.append(f"主体材质：{primary_material}{supplement_note}")
            if handle_material:
                lines.append(f"手柄材质：{handle_material}（手柄{handle_material}）{supplement_note}")
            continue
        if display_key == "手柄材质" and value_text and "手柄" not in value_text:
            lines.append(f"手柄材质：{value_text}（手柄{value_text}）{supplement_note}")
            continue
        value_parts = [part.strip() for part in re.split(r"[;\n]+", value_text) if part.strip()]
        if len(value_parts) > 1:
            lines.append(f"{display_key}：{supplement_note}" if supplement_note else f"{display_key}：")
            for part in value_parts:
                lines.append(f"- {part}")
        else:
            lines.append(f"{display_key}：{value_text}{supplement_note}")
    if qa_results or kb_results:
        lines.append("依据：以上字段已结合当前 SKU 的 QA / KB 补充资料。")
    return "\n".join(lines)


def _water_container_capability_label(question_text: str) -> str:
    if any(term in question_text for term in ("冷水", "凉水")):
        return "装冷水"
    if any(term in question_text for term in ("热水", "开水", "沸水", "保温")):
        return "装热水"
    if "饮用水" in question_text:
        return "装饮用水"
    return "装水"


def _extract_water_container_capability_evidence_from_qa_kb(
    *,
    db: Session | None = None,
    sku: str,
    question: str,
    qa_results: list[dict] | None = None,
    kb_results: list[dict] | None = None,
) -> str | None:
    sku_value = str(sku or "").strip().upper()
    if not sku_value:
        return None
    capability_label = _water_container_capability_label(str(question or ""))
    evidence_candidates: list[tuple[int, str]] = []
    source_buckets = (
        ("产品问答", qa_results or []),
        ("知识库资料", kb_results or []),
    )
    for source_label, items in source_buckets:
        for item in items:
            if not isinstance(item, dict):
                continue
            item_sku = str(item.get("sku") or "").strip().upper()
            if item_sku and item_sku != sku_value:
                continue
            content = _strip_qa_answer(str(item.get("answer") or item.get("content") or "")).strip()
            if not content:
                continue
            verdict = _water_container_capability_verdict_from_evidence(content, question)
            if not verdict:
                continue
            score = 10 if source_label == "产品问答" else 5
            if verdict.startswith(("可以", "支持", "可装")):
                score += 2
            if verdict.startswith(("不建议", "不能", "不可以", "禁止", "避免")):
                score += 2
            evidence_candidates.append((score, f"{source_label}显示{verdict.rstrip('。')}。"))
    if not evidence_candidates and db is not None:
        for item in _search_product_qa(db, sku_value, question, limit=5):
            if not isinstance(item, dict):
                continue
            content = _strip_qa_answer(str(item.get("answer") or item.get("content") or "")).strip()
            if not content:
                continue
            verdict = _water_container_capability_verdict_from_evidence(content, question)
            if not verdict:
                continue
            score = 12
            if verdict.startswith(("可以", "支持", "可装")):
                score += 2
            if verdict.startswith(("不建议", "不能", "不可以", "禁止", "避免")):
                score += 2
            evidence_candidates.append((score, f"产品问答显示{verdict.rstrip('。')}。"))
    if not evidence_candidates:
        return None
    evidence_candidates.sort(key=lambda item: item[0], reverse=True)
    answer = evidence_candidates[0][1]
    if capability_label not in answer and not any(term in answer for term in ("开水", "沸水", "保温")):
        return f"{answer}可作为是否可以{capability_label}的依据"
    return answer


def _water_container_capability_verdict_from_evidence(content: str, question: str) -> str | None:
    text = str(content or "").strip()
    if not text:
        return None
    if any(term in text for term in ("质保", "保修", "售后", "购买渠道", "清洗", "冲洗", "骤冷骤热", "软刷", "温水")):
        if not any(term in text for term in ("装冷水", "装凉水", "装热水", "装饮用水", "装水", "盛水", "开水", "沸水", "保温")):
            return None
    question_text = str(question or "")
    if any(term in question_text for term in ("冷水", "凉水")):
        relevant_terms = ("冷水", "凉水", "饮用水", "装水", "盛水")
    elif any(term in question_text for term in ("热水", "开水", "沸水", "保温")):
        relevant_terms = ("热水", "开水", "沸水", "保温")
    elif "饮用水" in question_text:
        relevant_terms = ("饮用水", "冷水", "装水", "盛水")
    else:
        relevant_terms = ("装冷水", "装凉水", "装热水", "装饮用水", "装水", "盛水", "开水", "沸水", "保温")
    if not any(term in text for term in relevant_terms):
        return None
    negative_markers = ("不建议", "不能", "不可以", "禁止", "避免")
    positive_markers = ("可以", "可装", "能装", "支持", "适合")
    if any(marker in text for marker in negative_markers):
        return text
    if any(marker in text for marker in positive_markers):
        return text
    return None


def _rewrite_heat_source_support_rows(question: str, rows: list[dict]) -> list[dict]:
    question_text = str(question or "")
    if not any(term in question_text for term in ("酒精炉", "酒精")):
        return rows
    if not any(term in question_text for term in ("能用", "可以用", "支持", "适合", "能不能", "是否支持")):
        return rows
    rewritten: list[dict] = []
    for item in rows:
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


def _compound_single_product_detail_answer(
    db: Session,
    *,
    sku: str,
    detail: dict[str, Any],
    question: str,
    supporting: dict[str, Any] | None = None,
) -> str | None:
    text = str(question or "").strip()
    if not text:
        return None
    title = detail.get("product_name_cn") or detail.get("product_name_en") or ""
    prefix = f"{title}（{sku}）" if title else sku
    field_lines: list[str] = []
    asks_handle_material = (
        any(term in text for term in ("手柄", "把手"))
        and any(term in text for term in ("材质", "材料", "木料", "木头"))
    )
    body_material_raw = str(_value_from_detail(detail, "specs.body_material") or "").strip()
    primary_material, handle_material = _split_primary_and_handle_material(body_material_raw)
    if asks_handle_material and not handle_material:
        handle_material = _extract_handle_material_hint(detail, supporting)

    def add_line(label: str, value: str | None) -> None:
        value_text = str(value or "").strip()
        if not value_text or value_text == "暂无":
            return
        field_lines.append(f"{label}：{value_text}")

    if any(term in text for term in ("锅盖", "盖子")) and any(term in text for term in ("材质", "材料")):
        lid_material = _best_same_sku_evidence_text(
            db,
            sku=sku,
            supporting=supporting,
            term_groups=[("锅盖", "盖子"), ("材质", "材料")],
        )
        if not lid_material:
            lid_material = "当前资料未单独提供锅盖材质"
        add_line("锅盖材质", lid_material)

    if any(term in text for term in ("适合哪些人群", "适合什么人群", "适用人群", "适合哪些人", "适合几个人", "适合几人")):
        audience = _format_field_value(_value_from_detail(detail, "business.target_audience"), "business.target_audience")
        if not audience or audience == "暂无":
            audience = _format_field_value(_value_from_detail(detail, "business.usage_scenarios"), "business.usage_scenarios")
        if not audience or audience == "暂无":
            audience = _audience_hint_from_detail(detail)
        add_line("适合人群", audience)

    if "功率" in text or "火力" in text:
        power = _format_field_value(_value_from_detail(detail, "specs.power"), "specs.power")
        add_line("最大功率", power)

    if any(term in text for term in ("爆炒", "翻炒")):
        stir_fry = _best_same_sku_evidence_text(
            db,
            sku=sku,
            supporting=supporting,
            term_groups=[("爆炒", "翻炒")],
        )
        if not stir_fry and any(term in str(detail.get("category") or "") for term in ("炉", "炉具")):
            stir_fry = "当前资料未直接标注家用爆炒能力；从炉具定位看，更适合烧水、煮食和简单翻炒，不建议按家用大火爆炒来使用。"
        add_line("爆炒适用性", stir_fry)

    if any(term in text for term in ("材质", "材料", "炉体")):
        material = primary_material or _format_field_value(_value_from_detail(detail, "specs.body_material"), "specs.body_material")
        add_line("主体材质", material)
        if asks_handle_material and handle_material:
            add_line("手柄材质", f"{handle_material}（手柄{handle_material}）")

    if "洗碗机" in text:
        dishwasher = _best_same_sku_evidence_text(
            db,
            sku=sku,
            supporting=supporting,
            term_groups=[("洗碗机",)],
        )
        if not dishwasher:
            dishwasher = "当前资料未明确说明是否可放入洗碗机。"
        add_line("是否可放入洗碗机", dishwasher)

    if any(term in text for term in ("耐摔", "磕碰", "耐磨")):
        durability = _best_same_sku_evidence_text(
            db,
            sku=sku,
            supporting=supporting,
            term_groups=[("耐摔", "磕碰", "耐磨")],
        )
        if not durability and "硬质氧化铝合金" in str(_value_from_detail(detail, "specs.body_material") or ""):
            durability = "硬质氧化铝合金更偏轻量和耐磨，日常露营磕碰问题不大，但不代表可以随意重摔。"
        add_line("耐摔性", durability)

    if "304" in text or "不锈钢" in text:
        is_304 = "304不锈钢" in body_material_raw
        stainless_line = "当前资料显示它是304不锈钢。" if is_304 else "当前资料显示它不是304不锈钢。"
        add_line("是否为304不锈钢", stainless_line)

    if "耐腐蚀" in text:
        corrosion = _best_same_sku_evidence_text(
            db,
            sku=sku,
            supporting=supporting,
            term_groups=[("耐腐蚀",)],
        )
        if not corrosion:
            corrosion = "当前资料未明确说明其耐腐蚀性能。"
        add_line("耐腐蚀性", corrosion)

    if "煎盘" in text and any(term in text for term in ("单独", "单用", "单独用")):
        standalone = _best_same_sku_evidence_text(
            db,
            sku=sku,
            supporting=supporting,
            term_groups=[("煎盘",), ("单独", "单用")],
        )
        if not standalone and any(term in str(_value_from_detail(detail, "specs.capacity") or "") for term in ("煎盘", "英寸")):
            standalone = "资料显示套装内含煎盘，可单独作为平底煎盘使用。"
        add_line("煎盘是否可单独使用", standalone)

    if any(term in text for term in ("手柄", "把手")) and not asks_handle_material:
        handle = _best_same_sku_evidence_text(
            db,
            sku=sku,
            supporting=supporting,
            term_groups=[("手柄", "把手")],
        )
        if not handle:
            handle = "当前资料未单独标注独立手柄信息。"
        add_line("手柄信息", handle)

    return "\n".join([prefix, *field_lines]) if len(field_lines) >= 2 else None


def _split_primary_and_handle_material(material_text: str) -> tuple[str, str]:
    value = str(material_text or "").strip()
    if not value:
        return "", ""
    parts = [part.strip() for part in re.split(r"[、,，/]", value) if part.strip()]
    if len(parts) < 2:
        return value, ""
    handle_index = next(
        (index for index, part in enumerate(parts) if any(term in part for term in ("木", "白蜡木", "胡桃木", "榉木", "木质"))),
        None,
    )
    if handle_index is None:
        return value, ""
    handle = parts[handle_index]
    primary_parts = [part for index, part in enumerate(parts) if index != handle_index]
    primary = "、".join(primary_parts).strip()
    return primary or value, handle


def _extract_handle_material_hint(detail: dict[str, Any], supporting: dict[str, Any] | None = None) -> str:
    text_candidates: list[str] = []
    for text in _load_capacity_texts_from_detail(detail):
        if text:
            text_candidates.append(text)
    for bucket in ("qa", "kb", "raw_rows", "evidence"):
        for item in (supporting or {}).get(bucket) or []:
            if not isinstance(item, dict):
                continue
            for key in ("content", "evidence_text", "answer", "value"):
                value = str(item.get(key) or "").strip()
                if value:
                    text_candidates.append(value)
    wood_terms = ("白蜡木", "胡桃木", "榉木", "木质")
    for text in text_candidates:
        for term in wood_terms:
            if term in text:
                return term
        match = re.search(r"(?:手柄|把手)(?:材质|为|是|采用)?[:：]?\s*([^\s，。,；;（）()]+)", text)
        if match:
            candidate = match.group(1).strip()
            if candidate:
                return candidate
    return ""


def _best_same_sku_evidence_text(
    db: Session,
    *,
    sku: str,
    supporting: dict[str, Any] | None,
    term_groups: list[tuple[str, ...]],
) -> str | None:
    candidates: list[tuple[int, str]] = []
    product = db.query(Product).filter(Product.sku.ilike(sku)).first()
    if product:
        for qa in (
            db.query(ProductQa)
            .filter(ProductQa.product_id == product.id)
            .order_by(ProductQa.priority.desc().nullslast(), ProductQa.id.desc())
            .limit(20)
            .all()
        ):
            combined = " ".join(str(part or "") for part in (qa.question, qa.answer, qa.tags))
            if not _matches_all_term_groups(combined, term_groups):
                continue
            answer = _strip_qa_answer(qa.answer)
            if answer:
                candidates.append((_term_group_score(combined, term_groups), answer))
    for bucket in ("qa", "kb"):
        for item in (supporting or {}).get(bucket) or []:
            if str(item.get("sku") or "").strip().upper() != str(sku or "").strip().upper():
                continue
            content = str(item.get("content") or item.get("answer") or "")
            if not _matches_all_term_groups(content, term_groups):
                continue
            answer = _strip_qa_answer(content)
            if answer:
                candidates.append((_term_group_score(content, term_groups), answer))
    if not candidates:
        return None
    candidates.sort(key=lambda item: item[0], reverse=True)
    return candidates[0][1].strip(" 。")


def _matches_all_term_groups(text: str, term_groups: list[tuple[str, ...]]) -> bool:
    value = str(text or "")
    if not value:
        return False
    return all(any(term in value for term in group) for group in term_groups if group)


def _term_group_score(text: str, term_groups: list[tuple[str, ...]]) -> int:
    value = str(text or "")
    return sum(1 for group in term_groups for term in group if term in value)


def _audience_hint_from_detail(detail: dict[str, Any]) -> str:
    combined = " ".join(
        str(part or "")
        for part in (
            detail.get("product_name_cn"),
            (detail.get("specs") or {}).get("capacity"),
            (detail.get("business") or {}).get("usage_scenarios"),
        )
    )
    match = re.search(r"(\d+\s*[-－]\s*\d+人|\d+人)", combined)
    if match:
        return f"{match.group(1).replace('－', '-')}户外使用人群"
    return ""


def _compound_field_values_from_answer(answer: str) -> dict[str, str]:
    field_values: dict[str, str] = {}
    for line in [item.strip() for item in str(answer or "").splitlines() if item.strip()]:
        if "：" not in line:
            continue
        label, value = line.split("：", 1)
        label = str(label).strip()
        value = str(value).strip().rstrip("。")
        if label and value:
            field_values[label] = value
    return field_values


def _is_same_product_comparison_question(text: str) -> bool:
    value = str(text or "")
    return any(term in value for term in ("同一个产品", "同款", "是不是同款", "是否同款", "是不是同一个产品", "是否同一个产品"))


def _compose_same_product_compare_answer_template(
    question: str,
    skus: list[str],
    comparisons: list[dict[str, Any]],
) -> str:
    if len(skus) < 2:
        return "当前可用于判断的 SKU 不足，暂时无法确认是否为同一产品。"
    lines = [f"先说结论：{skus[0]} 和 {skus[1]} 不是同一个 SKU。"]
    differences: list[str] = []
    same_fields: list[str] = []
    for item in comparisons:
        label = str(item.get("field_label") or "字段")
        values = item.get("values") or []
        if len(values) < 2:
            continue
        left = str(values[0].get("value") or "暂无").strip()
        right = str(values[1].get("value") or "暂无").strip()
        if left == right:
            same_fields.append(f"{label}一致：{left}")
        else:
            differences.append(f"{label}不同：{skus[0]}={left}；{skus[1]}={right}")
    if differences:
        lines.append("当前资料里的已知差异：")
        for item in differences[:4]:
            lines.append(f"- {item}")
    elif same_fields:
        lines.append("当前资料里已查询到的字段基本一致，但因为 SKU 不同，暂时无法确认是否完全同款。")
    else:
        lines.append("当前资料里暂未检索到足够差异字段，无法确认是否完全同款。")
    return "\n".join(lines)


def _compose_unknown_attribute_answer(
    details: list[dict[str, Any]],
    requested_fields: list[str],
    followups: list[str],
) -> str:
    if not details:
        return "当前没有找到对应产品资料。"

    field_text = "、".join(requested_fields or ["这个属性"])
    first = details[0]
    sku = first.get("sku") or ""
    name = first.get("product_name_cn") or first.get("product_name_en") or ""
    prefix = f"{name}（{sku}）" if name else sku
    return f"{prefix}\n当前资料未明确标注{field_text}。"


def _requested_label_for_path(requested_fields: list[str], field_path: str) -> str | None:
    for label in requested_fields or []:
        if _resolve_query_field(label) == field_path:
            return label
    return None


def _all_requested_field_values_missing(rows: list[dict[str, Any]]) -> bool:
    if not rows:
        return False
    values: list[str] = []
    for row in rows:
        field_values = row.get("field_values")
        if isinstance(field_values, dict):
            values.extend(str(value or "").strip() for value in field_values.values())
    return bool(values) and all(value in {"", "暂无", "无", "None"} for value in values)


def _normalize_requested_field_label(label: str) -> str:
    value = str(label or "").strip()
    aliases = {
        "使用场景": "适用场景",
        "场景": "适用场景",
        "禁止": "禁止操作",
        "禁忌": "禁止操作",
        "防伪": "正品辨别",
        "真假": "正品辨别",
    }
    return aliases.get(value, value or "该字段")


def _requested_recommendation_slots(query: str) -> list[tuple[str, tuple[str, ...]]]:
    text = str(query or "")
    slots: list[tuple[str, tuple[str, ...]]] = []
    if "锅具" in text or "锅" in text and "各推荐" in text:
        slots.append(("锅具", ("锅具", "锅", "套锅", "单锅", "煎锅", "炒锅")))
    if "水具" in text or "水壶" in text or "喝水" in text:
        slots.append(("水具", ("水具", "水壶", "水杯", "杯", "壶")))
    if "燃料" in text or "气罐" in text or "酒精" in text:
        slots.append(("燃料", ("燃料", "气罐", "酒精", "炉具")))
    deduped: list[tuple[str, tuple[str, ...]]] = []
    seen: set[str] = set()
    for label, terms in slots:
        if label in seen:
            continue
        seen.add(label)
        deduped.append((label, terms))
    return deduped


def _slot_fill_recommendation_rows(rows: list[dict[str, Any]], query: str) -> list[dict[str, Any]]:
    slots = _requested_recommendation_slots(query)
    if len(slots) <= 1:
        return rows
    selected: list[dict[str, Any]] = []
    used: set[str] = set()
    for label, terms in slots:
        best = None
        for row in rows:
            sku = str(row.get("sku") or "").strip().upper()
            if not sku or sku in used:
                continue
            haystack = " ".join(str(row.get(key) or "") for key in ("category", "sub_category", "product_name_cn", "product_name_en", "features", "usage_scenarios", "target_audience"))
            if any(term in haystack for term in terms):
                best = dict(row)
                match = best.get("recommendation_match") if isinstance(best.get("recommendation_match"), dict) else {}
                matched = list(match.get("matched") or [])
                matched.append(f"满足{label}槽位")
                best["recommendation_match"] = {**match, "matched": matched}
                break
        if best:
            selected.append(best)
            used.add(str(best.get("sku") or "").strip().upper())
    for row in rows:
        sku = str(row.get("sku") or "").strip().upper()
        if sku and sku not in used:
            selected.append(row)
        if len(selected) >= max(5, len(rows)):
            break
    return selected or rows


async def _slot_retrieve_recommendation_rows(
    db: Session,
    user_id: str,
    intent: CustomerIntent,
    query: str,
) -> list[dict[str, Any]]:
    slots = _requested_recommendation_slots(query)
    if len(slots) <= 1:
        return []
    fields = [
        "specs.capacity",
        "specs.body_material",
        "specs.heat_source",
        "specs.power",
        "business.top_selling_points",
        "business.usage_scenarios",
        "business.target_audience",
        "business.positioning",
        "business.price_positioning",
    ]
    merged: list[dict[str, Any]] = []
    seen: set[str] = set()
    for label, terms in slots:
        slot_query = f"{query} {label} {' '.join(terms[:3])}"
        added_for_slot = False
        try:
            result = await customer_agent_tool_service.execute_tool_async(
                db,
                user_id=user_id,
                name="hybrid_search_products",
                arguments={
                    "term": "",
                    "filters": intent.filters or {},
                    "semantic_query": slot_query,
                    "fields": fields,
                    "limit": 20,
                },
            )
        except Exception:
            continue
        for row in result.get("results") or []:
            sku = str(row.get("sku") or "").strip().upper()
            if not sku or sku in seen:
                continue
            haystack = " ".join(str(row.get(key) or "") for key in ("category", "sub_category", "product_name_cn", "product_name_en", "features", "usage_scenarios", "target_audience"))
            if not any(term in haystack for term in terms):
                continue
            item = dict(row)
            match = item.get("recommendation_match") if isinstance(item.get("recommendation_match"), dict) else {}
            matched = list(match.get("matched") or [])
            matched.append(f"满足{label}槽位")
            item["recommendation_match"] = {**match, "matched": matched}
            merged.append(item)
            seen.add(sku)
            added_for_slot = True
            break
        if not added_for_slot:
            fallback = _first_product_row_for_slot(db, label, terms, seen)
            if fallback:
                merged.append(fallback)
                seen.add(str(fallback.get("sku") or "").strip().upper())
    return merged


def _first_product_row_for_slot(
    db: Session,
    label: str,
    terms: tuple[str, ...],
    seen: set[str],
) -> dict[str, Any] | None:
    products = db.query(Product).all()
    for product in products:
        sku = str(product.sku or "").strip().upper()
        if not sku or sku in seen:
            continue
        detail = product_service.get_product_detail(db, sku)
        row = _detail_to_result_row(detail, matched_by=f"{label}槽位")
        haystack = " ".join(str(row.get(key) or "") for key in ("category", "sub_category", "product_name_cn", "product_name_en", "features", "usage_scenarios", "target_audience"))
        if not any(term in haystack for term in terms):
            continue
        match = row.get("recommendation_match") if isinstance(row.get("recommendation_match"), dict) else {}
        matched = list(match.get("matched") or [])
        matched.append(f"满足{label}槽位")
        row["recommendation_match"] = {**match, "matched": matched}
        return row
    return None


def _slot_order_ranked_recommendations(ranked: list[dict[str, Any]], query: str) -> list[dict[str, Any]]:
    slots = _requested_recommendation_slots(query)
    if len(slots) <= 1:
        return ranked
    selected: list[dict[str, Any]] = []
    used: set[str] = set()
    for label, terms in slots:
        for item in ranked:
            row = item.get("row") or {}
            sku = str(row.get("sku") or "").strip().upper()
            if not sku or sku in used:
                continue
            haystack = " ".join(str(row.get(key) or "") for key in ("category", "sub_category", "product_name_cn", "product_name_en", "features", "usage_scenarios", "target_audience"))
            if not any(term in haystack for term in terms):
                continue
            row = dict(row)
            match = row.get("recommendation_match") if isinstance(row.get("recommendation_match"), dict) else {}
            matched = list(match.get("matched") or [])
            if not any(label in str(item) for item in matched):
                matched.append(f"满足{label}槽位")
            row["recommendation_match"] = {**match, "matched": matched}
            selected.append({**item, "row": row})
            used.add(sku)
            break
    for item in ranked:
        row = item.get("row") or {}
        sku = str(row.get("sku") or "").strip().upper()
        if sku and sku not in used:
            selected.append(item)
            used.add(sku)
    return selected or ranked


def _field_evidence_terms(requested_fields: list[str]) -> set[str]:
    terms: set[str] = set()
    for raw_label in requested_fields or []:
        label = _normalize_requested_field_label(raw_label)
        if label == "禁止操作":
            terms.update(("禁止", "禁忌", "注意事项", "注意", "不能", "不要", "避免", "安全"))
        elif label == "正品辨别":
            terms.update(("正品", "防伪", "真假", "辨别"))
        elif label == "适用场景":
            terms.update(("适用场景", "使用场景", "场景", "适合", "露营", "徒步", "野餐", "咖啡", "人群"))
        elif label == "容量":
            terms.update(("容量", "ml", "ML", "L", "升"))
        elif label == "重量":
            terms.update(("重量", "净重", "毛重", "g", "G", "kg", "KG"))
        elif label == "材质":
            terms.update(("材质", "材料", "主体材质", "304", "不锈钢", "stainless steel", "corrosion resistant", "耐腐蚀"))
        elif label == "认证":
            terms.update(("认证", "食品级", "FDA", "LFGB", "food grade", "food-grade", "certification", "certified", "检测"))
        elif label == "适配情况":
            terms.update(("使用说明", "适配", "可装", "装冷水", "装凉水", "装热水", "装饮用水", "装水", "冷水", "热水", "饮用水"))
        else:
            terms.add(label)
    return {term for term in terms if term}


def _evidence_matches_requested_fields(text: str, requested_fields: list[str]) -> bool:
    value = str(text or "")
    if not value:
        return False
    terms = _field_evidence_terms(requested_fields)
    return bool(terms) and any(term in value for term in terms)


def _strip_qa_answer(text: str) -> str:
    value = str(text or "").strip()
    answer_match = re.search(r"A[:：]\s*(.+)$", value, flags=re.I | re.S)
    if answer_match:
        value = answer_match.group(1).strip()
    value = re.sub(r"^Q[:：].*?A[:：]\s*", "", value, flags=re.I | re.S).strip()
    return value


def _same_product_evidence_answer(
    db: Session,
    *,
    sku: str,
    question: str,
    requested_fields: list[str],
    supporting: dict[str, Any] | None = None,
) -> str | None:
    sku_value = str(sku or "").strip()
    if not sku_value or not requested_fields:
        return None
    product = db.query(Product).filter(Product.sku.ilike(sku_value)).first()
    if not product:
        return None
    requested_label = _normalize_requested_field_label(requested_fields[0])
    strong_cert_terms = ("认证", "fda", "lfgb", "food grade", "food-grade", "检测", "报告", "出口")

    candidates: list[tuple[int, str]] = []
    for qa in db.query(ProductQa).filter(ProductQa.product_id == product.id).order_by(ProductQa.priority.desc().nullslast()).limit(20).all():
        combined = " ".join(str(part or "") for part in (qa.question, qa.answer, qa.tags))
        if not _evidence_matches_requested_fields(combined, requested_fields):
            continue
        answer = _strip_qa_answer(qa.answer)
        if requested_label == "认证":
            answer_lower = answer.lower()
            combined_lower = combined.lower()
            if not any(term in answer_lower or term in combined_lower for term in strong_cert_terms):
                continue
        if answer:
            score = sum(1 for term in _field_evidence_terms(requested_fields) if term in combined)
            candidates.append((score, answer))

    for item in (supporting or {}).get("qa") or []:
        if str(item.get("sku") or "").strip().upper() != sku_value.upper():
            continue
        content = str(item.get("content") or "")
        if not _evidence_matches_requested_fields(content, requested_fields):
            continue
        answer = _strip_qa_answer(content)
        if requested_label == "认证":
            answer_lower = answer.lower()
            content_lower = content.lower()
            if not any(term in answer_lower or term in content_lower for term in strong_cert_terms):
                continue
        if answer:
            score = sum(1 for term in _field_evidence_terms(requested_fields) if term in content)
            candidates.append((score, answer))

    for item in (supporting or {}).get("kb") or []:
        if str(item.get("sku") or "").strip().upper() != sku_value.upper():
            continue
        content = str(item.get("content") or "")
        if not _evidence_matches_requested_fields(content, requested_fields):
            continue
        answer = _strip_qa_answer(content)
        if requested_label == "认证":
            answer_lower = answer.lower()
            content_lower = content.lower()
            if not any(term in answer_lower or term in content_lower for term in strong_cert_terms):
                continue
        if answer:
            score = sum(1 for term in _field_evidence_terms(requested_fields) if term in content)
            candidates.append((score, answer))

    if not candidates:
        return None
    candidates.sort(key=lambda item: item[0], reverse=True)
    answer_text = candidates[0][1].strip(" 。")
    return f"{product.product_name_cn or product.product_name_en}（{product.sku}）\n{requested_label}：{answer_text}。"


def _compose_missing_field_answer(row: dict[str, Any], requested_fields: list[str]) -> str:
    label = _normalize_requested_field_label((requested_fields or ["该字段"])[0])
    name = row.get("product_name_cn") or row.get("product_name_en") or ""
    sku = row.get("sku") or ""
    prefix = f"{name}（{sku}）" if name else sku
    return f"{prefix}\n当前资料中暂未找到{prefix}的明确{label}信息。"


def _search_product_qa(db: Session, sku: str, question: str, limit: int = 3) -> list[dict]:
    """Search product QA table for matching Q&A pairs."""
    from ..models.product import Product
    if not sku or not question.strip():
        return []
    product = db.query(Product).filter(Product.sku == sku).first()
    if not product:
        return []
    # Search by keyword matching in question/answer fields
    terms = [w.strip() for w in re.split(r"[?,，。？！!\s]+", question) if len(w.strip()) >= 2]
    if not terms:
        return []
    from sqlalchemy import or_
    conditions = []
    for term in terms[:5]:
        conditions.append(ProductQa.question.ilike(f"%{term}%"))
        conditions.append(ProductQa.answer.ilike(f"%{term}%"))
    qas = db.query(ProductQa).filter(
        ProductQa.product_id == product.id,
        or_(*conditions)
    ).order_by(ProductQa.priority.desc().nullslast(), ProductQa.updated_at.desc()).limit(limit).all()
    results = []
    for qa in qas:
        results.append({
            "question": qa.question,
            "answer": qa.answer,
            "tags": qa.tags,
            "source_type": "product_qa",
        })
    return results


def _is_semantic_qa_chunk(row: dict[str, Any]) -> bool:
    metadata = row.get("metadata") if isinstance(row.get("metadata"), dict) else {}
    section = str(metadata.get("section") or "").lower()
    content = str(row.get("content") or "")
    return section.startswith("qa:") or ("Q:" in content and "A:" in content)


def _compact_evidence_text(text: str, limit: int = 180) -> str:
    value = re.sub(r"\s+", " ", str(text or "")).strip()
    if len(value) <= limit:
        return value
    return value[: limit - 1].rstrip() + "…"


def _evidence_identity(item: dict[str, Any]) -> str:
    metadata = item.get("metadata") if isinstance(item.get("metadata"), dict) else {}
    return "|".join([
        str(item.get("source_kind") or item.get("source_type") or ""),
        str(item.get("sku") or ""),
        str(metadata.get("section") or metadata.get("source_id") or ""),
        str(item.get("content") or "")[:120],
    ])


def _normalize_knowledge_query(question: str) -> str:
    """Normalize customer phrasing before QA/KB retrieval without changing intent."""
    query = re.sub(r"\s+", " ", str(question or "").strip())
    if not query:
        return ""
    cache_key = customer_cache_service.make_key("knowledge_query_normalize", query)
    cached = customer_cache_service.recommendation_candidate_cache.get(cache_key)
    if cached is not None:
        return cached

    normalized = build_retrieval_query(query)
    replacements = (
        ("咋办", "怎么处理"),
        ("咋", "怎么"),
        ("啥", "什么"),
        ("哪儿", "哪里"),
        ("不沾", "不粘"),
        ("锅糊", "糊锅"),
        ("烧糊", "烧焦"),
        ("在哪买", "在哪里买"),
        ("什么材料", "什么材质"),
    )
    for old, new in replacements:
        normalized = normalized.replace(old, new)
    normalized = re.sub(r"\s+", " ", normalized).strip() or query
    customer_cache_service.recommendation_candidate_cache.set(cache_key, normalized)
    return normalized


def _expanded_knowledge_queries(question: str, *, limit: int = 5) -> list[str]:
    """Generate lightweight non-LLM query variants for QA/KB semantic retrieval."""
    query = _normalize_knowledge_query(question)
    if not query:
        return []
    cache_key = customer_cache_service.make_key("knowledge_query_expansion", query, limit)
    cached = customer_cache_service.recommendation_candidate_cache.get(cache_key)
    if cached is not None:
        return cached

    variants = [query]
    replacements = [
        ("怎么办", "怎么处理"),
        ("好不好", "怎么样"),
        ("能不能", "是否可以"),
        ("可不可以", "是否可以"),
        ("在哪里买", "购买渠道"),
        ("糊了", "烧焦 清洗"),
        ("糊锅", "锅底烧焦 清洁"),
        ("不粘", "涂层 防粘"),
        ("钢丝球", "硬物刮擦 涂层损伤"),
        ("水垢", "水壶 清洗 水垢处理"),
        ("积碳", "炉具 清洁 积碳处理"),
        ("保养", "使用后护理 存放"),
        ("清洗", "清洁 温水 软刷"),
        ("适合", "使用场景 目标人群"),
        ("推荐", "适合 哪款 选择"),
        ("售后", "退换货 联系客服"),
        ("发票", "开票 订单"),
    ]
    for old, new in replacements:
        if old in query:
            variants.append(f"{query} {new}")
            break

    if len(variants) == 1:
        if any(term in query for term in USAGE_CARE_TERMS):
            variants.append(f"{query} 清洗 保养 注意事项 禁止事项")
        elif any(term in query for term in ("适合", "推荐", "场景", "人群")):
            variants.append(f"{query} 适用场景 目标人群 推荐理由")
        elif any(term in query for term in ("哪里买", "购买", "淘宝", "京东", "旗舰店", "渠道")):
            variants.append(f"{query} 官方渠道 购买方式 店铺")
        elif any(term in query for term in ("锅", "壶", "炉", "杯", "餐具", "套装")):
            variants.append(f"{query} 产品QA 使用说明 规格参数")

    compacted: list[str] = []
    seen: set[str] = set()
    for item in variants:
        normalized = re.sub(r"\s+", " ", str(item or "").strip())
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        compacted.append(normalized)
        if len(compacted) >= limit:
            break
    customer_cache_service.recommendation_candidate_cache.set(cache_key, compacted)
    return compacted


def _knowledge_query_terms(query: str) -> set[str]:
    text = _normalize_knowledge_query(query)
    terms = {item.upper() for item in re.findall(r"[A-Za-z]{1,8}-?[A-Za-z0-9]{1,12}", text)}
    for token in re.split(r"[\s，。！？、/（）()：:；;,.!?]+", text):
        token = token.strip()
        if len(token) >= 2:
            terms.add(token)
    for keyword in (
        "材质", "容量", "重量", "尺寸", "手柄", "涂层", "配件", "颜色", "品牌",
        "清洗", "清洁", "保养", "糊锅", "烧焦", "快递", "物流", "质保", "场景",
        "推荐", "适合", "购买", "旗舰店", "官方",
    ):
        if keyword in text:
            terms.add(keyword)
    return terms


def _adjust_semantic_score(row: dict[str, Any], *, base_score: float, query: str, query_index: int, sku: str | None = None) -> float:
    content = str(row.get("content") or "")
    metadata = row.get("metadata") if isinstance(row.get("metadata"), dict) else {}
    row_sku = str(row.get("sku") or metadata.get("sku") or "").strip().upper()
    score = base_score + max(0.0, 0.05 - query_index * 0.01)
    if sku and row_sku == str(sku).strip().upper():
        score += 0.08
    if _is_semantic_qa_chunk(row):
        score += 0.025
    terms = _knowledge_query_terms(query)
    if row_sku and row_sku in terms:
        score += 0.04
    return round(score, 4)


def _semantic_row_identity(row: dict[str, Any]) -> str:
    metadata = row.get("metadata") if isinstance(row.get("metadata"), dict) else {}
    return "|".join([
        str(row.get("source_type") or ""),
        str(row.get("sku") or ""),
        str(metadata.get("section") or metadata.get("source_id") or metadata.get("title") or ""),
        str(row.get("content") or "")[:160],
    ])


async def _multi_query_semantic_retrieve(
    db: Session,
    question: str,
    *,
    sku: str | None = None,
    limit: int = 5,
    query_limit: int = 5,
) -> list[dict[str, Any]]:
    normalized_question = _normalize_knowledge_query(question)
    cache_key = customer_cache_service.make_key(
        "multi_query_semantic_retrieve",
        id(db),
        normalized_question,
        sku,
        limit,
        query_limit,
    )
    cached = customer_cache_service.recommendation_candidate_cache.get(cache_key)
    if cached is not None:
        return cached

    queries = _expanded_knowledge_queries(normalized_question, limit=query_limit)
    merged: dict[str, dict[str, Any]] = {}
    for query_index, query in enumerate(queries):
        try:
            rows = await knowledge_service.semantic_retrieve(db, query, sku=sku, limit=max(limit, 5))
        except Exception:
            rows = knowledge_service.keyword_retrieve(db, query, sku=sku, limit=max(limit, 5))
        for row in rows:
            if not isinstance(row, dict) or not str(row.get("content") or "").strip():
                continue
            key = _semantic_row_identity(row)
            score = float(row.get("score") or 0)
            adjusted_score = _adjust_semantic_score(row, base_score=score, query=query, query_index=query_index, sku=sku)
            existing = merged.get(key)
            if existing is None or adjusted_score > float(existing.get("_expanded_score") or 0):
                item = dict(row)
                item["_matched_query"] = query
                item["_query_index"] = query_index
                item["_expanded_score"] = round(adjusted_score, 4)
                merged[key] = item
    ranked = sorted(merged.values(), key=lambda item: float(item.get("_expanded_score") or item.get("score") or 0), reverse=True)
    result = ranked[:limit]
    customer_cache_service.recommendation_candidate_cache.set(cache_key, result)
    return result


async def _semantic_supporting_evidence(
    db: Session,
    question: str,
    *,
    skus: list[str] | None = None,
    limit: int = 5,
    query_limit: int = 2,
) -> dict[str, Any]:
    query = str(question or "").strip()
    queries = _expanded_knowledge_queries(query, limit=query_limit)
    if not query:
        return {
            "qa": [],
            "kb": [],
            "raw_rows": [],
            "evidence": [],
            "sources": [],
            "supporting_sources": [],
        }

    raw_rows: list[dict[str, Any]] = []
    seen_raw: set[str] = set()
    search_skus = [str(sku or "").strip().upper() for sku in (skus or []) if str(sku or "").strip()]
    allowed_skus = set(search_skus)
    scopes = search_skus[:3] or [None]
    for sku in scopes:
        rows = await _multi_query_semantic_retrieve(db, query, sku=sku, limit=max(limit * 2, 8), query_limit=query_limit)
        for row in rows:
            if not isinstance(row, dict):
                continue
            row_sku = str(row.get("sku") or "").strip().upper()
            if allowed_skus and row_sku not in allowed_skus:
                continue
            content = str(row.get("content") or "").strip()
            if not content:
                continue
            row_key = f"{row.get('source_type')}|{row.get('sku')}|{content[:160]}"
            if row_key in seen_raw:
                continue
            seen_raw.add(row_key)
            raw_rows.append(row)

    qa_items: list[dict[str, Any]] = []
    kb_items: list[dict[str, Any]] = []
    seen_items: set[str] = set()
    for row in raw_rows:
        metadata = row.get("metadata") if isinstance(row.get("metadata"), dict) else {}
        item = {
            "source_type": row.get("source_type") or "knowledge",
            "source_kind": "qa" if _is_semantic_qa_chunk(row) else "kb",
            "role": "supporting",
            "sku": row.get("sku"),
            "content": _compact_evidence_text(str(row.get("content") or "")),
            "metadata": metadata,
            "score": row.get("score"),
        }
        key = _evidence_identity(item)
        if key in seen_items:
            continue
        seen_items.add(key)
        if item["source_kind"] == "qa":
            qa_items.append(item)
        else:
            kb_items.append(item)
        if len(qa_items) >= limit and len(kb_items) >= limit:
            break

    qa_items = qa_items[:limit]
    kb_items = kb_items[:limit]
    evidence = [
        {"source": "product_db", "role": "primary"},
        *qa_items,
        *kb_items,
    ]
    sources: list[dict[str, Any]] = []
    supporting_sources: list[str] = []
    if qa_items:
        sources.append({"type": "product_qa", "label": "QA 语义补充", "role": "supporting", "count": len(qa_items)})
        supporting_sources.append("qa")
    if kb_items:
        sources.append({"type": "knowledge_base", "label": "文件知识库语义补充", "role": "supporting", "count": len(kb_items)})
        supporting_sources.append("kb")

    return {
        "qa": qa_items,
        "kb": kb_items,
        "raw_rows": raw_rows,
        "evidence": evidence,
        "sources": sources,
        "supporting_sources": supporting_sources,
        "query_expansion": queries,
    }


def _recommendation_supporting_snippet(item: dict[str, Any]) -> str:
    content = _compact_evidence_text(str(item.get("content") or "")).strip()
    if not content:
        return ""
    answer_match = re.search(r"A:\s*(.+)$", content, flags=re.I | re.S)
    text = answer_match.group(1).strip() if answer_match else content
    text = re.sub(r"^Q:\s*.*?\s*A:\s*", "", text, flags=re.I | re.S).strip()
    text = re.sub(r"\s+", " ", text)
    if len(text) > 120:
        text = text[:119].rstrip() + "…"
    return text


async def _recommendation_supporting_evidence_by_sku(
    db: Session,
    question: str,
    rows: list[dict[str, Any]],
    *,
    per_sku_limit: int = 2,
    query_limit: int = 2,
) -> dict[str, dict[str, list[dict[str, str]]]]:
    by_sku: dict[str, dict[str, list[dict[str, str]]]] = {}
    for row in rows[:5]:
        sku = str(row.get("sku") or "").strip().upper()
        if not sku or sku in by_sku:
            continue
        supporting = await _semantic_supporting_evidence(
            db,
            question,
            skus=[sku],
            limit=per_sku_limit,
            query_limit=query_limit,
        )
        by_sku[sku] = {
            "product_qa": [
                {"source": "product_qa", "sku": sku, "summary": snippet}
                for item in supporting.get("qa") or []
                if (snippet := _recommendation_supporting_snippet(item))
            ][:per_sku_limit],
            "knowledge_chunks": [
                {"source": "knowledge_chunks", "sku": sku, "summary": snippet}
                for item in supporting.get("kb") or []
                if (snippet := _recommendation_supporting_snippet(item))
            ][:per_sku_limit],
        }
    return by_sku


def _knowledge_enrichment_payload(primary_source: str, supporting: dict[str, Any]) -> dict[str, Any]:
    return {
        "primary_source": primary_source,
        "supporting_sources": supporting.get("supporting_sources") or [],
        "evidence": {
            "qa": supporting.get("qa") or [],
            "kb": supporting.get("kb") or [],
        },
    }


def _attach_knowledge_enrichment(response: dict[str, Any], *, primary_source: str, supporting: dict[str, Any]) -> None:
    payload = _knowledge_enrichment_payload(primary_source, supporting)
    metadata = response.get("answer_metadata") if isinstance(response.get("answer_metadata"), dict) else {}
    metadata["knowledge_enrichment"] = payload
    response["answer_metadata"] = metadata
    debug = response.get("debug") if isinstance(response.get("debug"), dict) else {}
    debug["knowledge_enrichment"] = {
        "primary_source": payload["primary_source"],
        "supporting_sources": payload["supporting_sources"],
        "qa_count": len(payload["evidence"]["qa"]),
        "kb_count": len(payload["evidence"]["kb"]),
    }
    response["debug"] = debug


def _compose_semantic_evidence_answer(supporting: dict[str, Any]) -> str:
    qa_items = supporting.get("qa") or []
    kb_items = supporting.get("kb") or []
    for item in [*qa_items, *kb_items]:
        content = str(item.get("content") or "").strip()
        if not content:
            continue
        answer_match = re.search(r"A:\s*(.+)$", content, flags=re.I | re.S)
        text = answer_match.group(1).strip() if answer_match else content
        text = re.sub(r"^Q:\s*.*?\s*A:\s*", "", text, flags=re.I | re.S).strip()
        parts = [part.strip() for part in re.split(r"[。！？!?；;]\s*", text) if part.strip()]
        if parts:
            sentence = parts[0]
            if len(sentence) > 120:
                sentence = sentence[:119].rstrip() + "…"
            return sentence + ("。" if not sentence.endswith("。") else "")
    return "当前商品库没有直接命中，但 QA/知识库里有相关资料，可按现有资料进一步确认。"


def _knowledge_enrichment_debug(
    intent: CustomerIntent,
    *,
    steps: list[dict],
    warnings: list[str],
    anomalies: list[dict[str, Any]],
    results: list[dict],
    supporting: dict[str, Any],
) -> dict[str, Any]:
    return {
        "intent": intent.as_dict(),
        "steps": steps,
        "warnings": warnings,
        "anomalies": anomalies,
        "raw_results": results,
        "knowledge_enrichment": {
            "primary_source": "product_db",
            "supporting_sources": supporting.get("supporting_sources") or [],
            "qa_count": len(supporting.get("qa") or []),
            "kb_count": len(supporting.get("kb") or []),
        },
    }


def _looks_like_usage_care_question(text: str) -> bool:
    value = str(text or "").strip()
    if not value:
        return False
    return any(term in value for term in USAGE_CARE_TERMS)


def _looks_like_usage_care_aftersales_question(text: str) -> bool:
    value = str(text or "").strip()
    if not value:
        return False
    return any(term in value for term in USAGE_CARE_AFTERSALES_TERMS)


def _looks_like_customer_faq_question(text: str) -> bool:
    value = str(text or "").strip()
    if not value:
        return False
    if _looks_like_usage_care_question(value) and not _looks_like_usage_care_aftersales_question(value):
        return False
    if _looks_like_recommendation_question(value):
        return False
    if any(term in value for term in FAQ_PURCHASE_TERMS):
        return True
    if any(term in value for term in FAQ_AFTERSALES_TERMS):
        return True
    has_problem_signal = any(term in value for term in FAQ_AFTERSALES_PROBLEM_TERMS)
    has_help_signal = any(term in value for term in FAQ_AFTERSALES_HELP_TERMS)
    return has_problem_signal and has_help_signal


async def _search_usage_care_qa(
    db: Session,
    question: str,
    target_skus: list[str] | None = None,
    *,
    usage_subtype: str | None = None,
    limit: int = 3,
) -> tuple[list[dict], list[dict], dict[str, Any]]:
    search_start = perf_counter()
    target_skus = [str(sku or "").strip().upper() for sku in (target_skus or []) if str(sku or "").strip()]
    usage_subtype = usage_subtype or _detect_usage_care_subtype(question)
    qa_start = perf_counter()
    qa_hits = _search_usage_care_product_qa(db, question, target_skus, usage_subtype=usage_subtype, limit=max(limit * 3, 9))
    product_qa_ms = customer_perf_service.perf_ms(qa_start)
    knowledge_start = perf_counter()
    knowledge_hits = await _search_usage_care_knowledge(db, question, target_skus, usage_subtype=usage_subtype, limit=max(limit * 3, 9))
    knowledge_search_ms = customer_perf_service.perf_ms(knowledge_start)
    rerank_start = perf_counter()
    qa_ranked, qa_filtered = _rerank_usage_care_hits(question, qa_hits, usage_subtype=usage_subtype, target_skus=target_skus, source_kind="product_qa", limit=limit)
    knowledge_ranked, knowledge_filtered = _rerank_usage_care_hits(question, knowledge_hits, usage_subtype=usage_subtype, target_skus=target_skus, source_kind="knowledge_chunks", limit=limit)
    rerank_ms = customer_perf_service.perf_ms(rerank_start)
    debug = {
        "search_ms": round(customer_perf_service.perf_ms(search_start), 2),
        "product_qa_ms": round(product_qa_ms, 2),
        "knowledge_search_ms": round(knowledge_search_ms, 2),
        "rerank_ms": round(rerank_ms, 2),
        "filtered_or_downgraded": qa_filtered + knowledge_filtered,
    }
    return qa_ranked, knowledge_ranked, debug


def _search_usage_care_product_qa(db: Session, question: str, target_skus: list[str], *, usage_subtype: str, limit: int = 3) -> list[dict]:
    terms = [term for term in _usage_care_query_terms(question) if term]
    query = db.query(ProductQa, Product).join(Product, Product.id == ProductQa.product_id)
    if target_skus:
        query = query.filter(Product.sku.in_(target_skus))
    conditions = []
    for term in terms[:8]:
        conditions.append(ProductQa.question.ilike(f"%{term}%"))
        conditions.append(ProductQa.answer.ilike(f"%{term}%"))
        conditions.append(ProductQa.tags.ilike(f"%{term}%"))
    if conditions:
        from sqlalchemy import or_
        query = query.filter(or_(*conditions))
    rows = query.order_by(ProductQa.priority.desc().nullslast(), ProductQa.updated_at.desc()).limit(limit).all()
    hits = []
    for qa, product in rows:
        hits.append({
            "id": qa.id,
            "sku": product.sku,
            "product_name_cn": product.product_name_cn,
            "category": product.category,
            "question": qa.question,
            "answer": qa.answer,
            "tags": qa.tags,
            "source_type": "product_qa",
            "_usage_text": " ".join([
                str(qa.question or ""),
                str(qa.answer or ""),
                str(qa.tags or ""),
                str(product.product_name_cn or ""),
                str(product.category or ""),
            ]),
            "_usage_subtype": usage_subtype,
        })
    return hits


async def _search_usage_care_knowledge(db: Session, question: str, target_skus: list[str], *, usage_subtype: str, limit: int = 3) -> list[dict]:
    scoped_hits: list[dict] = []
    search_skus = target_skus[:1] if target_skus else [None]
    for sku in search_skus:
        rows = await _multi_query_semantic_retrieve(db, question, sku=sku, limit=max(limit * 2, 8), query_limit=2)
        for row in rows:
            content = str(row.get("content") or "").strip()
            if not content:
                continue
            metadata = row.get("metadata") if isinstance(row.get("metadata"), dict) else {}
            haystack = " ".join([
                content,
                str(metadata.get("category") or ""),
                str(metadata.get("type") or ""),
                str(metadata.get("section") or ""),
                str(metadata.get("title") or ""),
            ])
            if not any(term in haystack for term in USAGE_CARE_TERMS):
                continue
            scoped_hits.append({
                "id": metadata.get("source_id") or metadata.get("title") or row.get("sku") or "",
                "sku": row.get("sku"),
                "source_type": row.get("source_type") or "knowledge",
                "content": content[:500],
                "metadata": metadata,
                "_usage_text": haystack,
                "_usage_subtype": usage_subtype,
            })
    return scoped_hits[:limit]


def _detect_usage_care_subtype(question: str) -> str:
    text = str(question or "")
    if any(term in text for term in USAGE_CARE_REPLY_TERMS):
        return "customer_reply"
    if any(term in text for term in USAGE_CARE_BURNT_TERMS):
        return "burnt"
    if any(term in text for term in USAGE_CARE_COATING_TERMS):
        return "coating"
    if any(term in text for term in USAGE_CARE_STICKING_TERMS):
        return "sticking"
    if any(term in text for term in USAGE_CARE_MAINTENANCE_TERMS):
        return "maintenance"
    return "cleaning"


def _usage_care_focus_terms(subtype: str) -> tuple[str, ...]:
    if subtype == "customer_reply":
        return USAGE_CARE_CLEANING_TERMS + USAGE_CARE_MAINTENANCE_TERMS + USAGE_CARE_STICKING_TERMS
    if subtype == "burnt":
        return USAGE_CARE_BURNT_TERMS + USAGE_CARE_BURNT_ACTION_TERMS + USAGE_CARE_CLEANING_TERMS
    if subtype == "coating":
        return USAGE_CARE_COATING_TERMS + USAGE_CARE_CLEANING_TERMS + USAGE_CARE_STICKING_TERMS
    if subtype == "sticking":
        return USAGE_CARE_STICKING_TERMS + USAGE_CARE_CLEANING_TERMS + USAGE_CARE_COATING_TERMS
    if subtype == "maintenance":
        return USAGE_CARE_MAINTENANCE_TERMS + USAGE_CARE_MAINTENANCE_ACTION_TERMS + USAGE_CARE_CLEANING_TERMS
    return USAGE_CARE_CLEANING_TERMS + USAGE_CARE_MAINTENANCE_TERMS


def _rerank_usage_care_hits(
    question: str,
    hits: list[dict],
    *,
    usage_subtype: str,
    target_skus: list[str],
    source_kind: str,
    limit: int,
) -> tuple[list[dict], list[dict]]:
    question_text = str(question or "")
    focus_terms = _usage_care_focus_terms(usage_subtype)
    ask_aftersales = any(term in question_text for term in USAGE_CARE_AFTERSALES_TERMS)
    ask_safety = any(term in question_text for term in USAGE_CARE_SAFETY_TERMS)
    ask_cookware = any(term in question_text for term in USAGE_CARE_COOKWARE_TERMS)
    ranked: list[tuple[float, dict]] = []
    filtered: list[dict] = []
    for item in hits:
        text = str(item.get("_usage_text") or item.get("answer") or item.get("content") or "")
        lowered = text
        score = 0.0
        flags: list[str] = []
        if target_skus and str(item.get("sku") or "").upper() in target_skus:
            score += 6.0
        elif target_skus:
            score -= 2.0
        if source_kind == "product_qa":
            score += 8.0
        category_text = " ".join([
            str(item.get("category") or ""),
            str((item.get("metadata") or {}).get("category") or "") if isinstance(item.get("metadata"), dict) else "",
        ])
        if ask_cookware and any(term in category_text for term in USAGE_CARE_COOKWARE_TERMS):
            score += 3.0
        metadata = item.get("metadata") if isinstance(item.get("metadata"), dict) else {}
        if source_kind == "knowledge_chunks" and (
            "Q:" in lowered or "A:" in lowered or str(metadata.get("type") or "").lower() == "qa" or str(metadata.get("section") or "").lower() == "qa"
        ):
            score += 5.0
        focus_matches = sum(1 for term in focus_terms if term in lowered)
        score += focus_matches * 3.0
        if any(term in lowered for term in ("清洗", "保养", "护理", "软刷", "温水", "擦干", "烘干", "钢丝球", "硬物刮擦")):
            score += 4.0
        if usage_subtype == "maintenance":
            if any(term in lowered for term in USAGE_CARE_MAINTENANCE_ACTION_TERMS):
                score += 5.0
            if any(term in lowered for term in USAGE_CARE_MAINTENANCE_WEAK_TERMS):
                score -= 6.0
                flags.append("maintenance_longevity_downgraded")
        if usage_subtype in {"sticking", "coating"} and any(term in lowered for term in ("不粘", "不沾", "涂层", "防粘", "不易粘", "粘锅")):
            score += 4.0
        if usage_subtype == "burnt" and any(term in lowered for term in USAGE_CARE_BURNT_ACTION_TERMS):
            score += 5.0
        if ask_cookware and any(term in lowered for term in USAGE_CARE_COOKWARE_TERMS):
            score += 4.0
        if ask_cookware and any(term in lowered for term in USAGE_CARE_NON_COOKWARE_TERMS):
            score -= 5.0
            flags.append("non_cookware_downgraded")
        if any(term in lowered for term in USAGE_CARE_GENERAL_TERMS):
            score -= 2.0
            flags.append("general_intro_downgraded")
        if not ask_aftersales and any(term in lowered for term in USAGE_CARE_AFTERSALES_TERMS):
            score -= 8.0
            flags.append("aftersales_downgraded")
        if not ask_safety and any(term in lowered for term in USAGE_CARE_SAFETY_TERMS):
            score -= 8.0
            flags.append("safety_downgraded")
        if focus_matches == 0 and not any(term in lowered for term in USAGE_CARE_TERMS):
            flags.append("usage_focus_filtered")
            filtered.append({
                "source_kind": source_kind,
                "sku": item.get("sku"),
                "reason": "usage_focus_filtered",
            })
            continue
        if score < 1.0:
            filtered.append({
                "source_kind": source_kind,
                "sku": item.get("sku"),
                "reason": ",".join(flags) if flags else "low_score_filtered",
            })
            continue
        item["_usage_score"] = round(score, 2)
        item["_usage_flags"] = flags
        ranked.append((score, item))
        for flag in flags:
            filtered.append({
                "source_kind": source_kind,
                "sku": item.get("sku"),
                "reason": flag,
            })
    ranked.sort(key=lambda pair: pair[0], reverse=True)
    return [item for _, item in ranked[:limit]], filtered


def _usage_care_query_terms(question: str) -> list[str]:
    raw_terms = [item.strip() for item in re.split(r"[?,，。？！!、\s]+", str(question or "")) if item.strip()]
    keep = []
    stop_terms = {"怎么办", "怎么处理", "怎么回复", "客户说", "用户说"}
    for term in raw_terms:
        if term in stop_terms:
            continue
        if len(term) >= 2:
            keep.append(term)
    for term in USAGE_CARE_TERMS:
        if term in str(question or "") and term not in keep:
            keep.append(term)
    return keep[:10]


def _compose_usage_care_answer(question: str, qa_hits: list[dict], knowledge_hits: list[dict], *, response_style: str) -> str:
    usage_subtype = _detect_usage_care_subtype(question)
    if _is_cold_shock_usage_care_question(question):
        return _compose_cold_shock_usage_care_answer(question, qa_hits, knowledge_hits)
    suggestions: list[str] = []
    seen = set()
    for item in qa_hits:
        answer = _normalize_usage_care_snippet(item.get("answer") or item.get("content") or "")
        if answer and answer not in seen:
            seen.add(answer)
            suggestions.append(answer)
    for item in knowledge_hits:
        content = _normalize_usage_care_snippet(item.get("content") or item.get("answer") or "")
        if content and content not in seen:
            seen.add(content)
            suggestions.append(content)
    sections = _compose_usage_care_sections(question, suggestions, usage_subtype=usage_subtype)
    if not any(sections.values()):
        body = "系统暂未配置对应清洗/保养资料，建议联系人工客服确认。"
    else:
        lines = []
        if sections["cleaning"]:
            lines.append(f"清洁方法：{sections['cleaning']}")
        if sections["caution"]:
            lines.append(f"注意事项：{sections['caution']}")
        if sections["avoid"]:
            lines.append(f"避免事项：{sections['avoid']}")
        body = "\n".join(lines)
    return body


def _is_cold_shock_usage_care_question(question: str) -> bool:
    text = str(question or "")
    return ("冷水" in text and "冲" in text) or "热锅骤冷" in text or "骤冷骤热" in text


def _compose_cold_shock_usage_care_answer(question: str, qa_hits: list[dict], knowledge_hits: list[dict]) -> str:
    label = _usage_care_product_label(question, qa_hits, knowledge_hits)
    prefix = f"{label}：" if label else ""
    return (
        f"{prefix}不建议洗完后马上用冷水冲，建议先自然冷却后再清洗，避免热锅骤冷影响锅体或涂层状态。"
        "当前资料未明确说明可直接冷水冲；如急需清洗，可先用温水过渡。"
    )


def _usage_care_product_label(question: str, qa_hits: list[dict], knowledge_hits: list[dict]) -> str:
    text = str(question or "")
    named_match = re.search(r"[「\"]([^」\"]+)[」\"]\s*\(([^)]+)\)", text)
    if named_match:
        return f"{named_match.group(1).strip()}（{named_match.group(2).strip()}）"
    for item in [*qa_hits, *knowledge_hits]:
        sku = str(item.get("sku") or "").strip()
        if sku:
            return sku
    return ""


def _normalize_usage_care_snippet(text: str) -> str:
    value = str(text or "").strip()
    if not value:
        return ""
    qa_match = re.search(r"[Aa][:：]\s*(.+)$", value, flags=re.IGNORECASE | re.DOTALL)
    if qa_match:
        value = qa_match.group(1).strip()
    value = re.sub(r"^\s*Q[:：]\s*", "", value, flags=re.IGNORECASE)
    value = re.sub(r"^\s*A[:：]\s*", "", value, flags=re.IGNORECASE)
    value = re.sub(r"\s+", " ", value).strip()
    return value


def _compose_usage_care_summary(question: str, suggestions: list[str], *, usage_subtype: str) -> list[str]:
    question_text = str(question or "")
    points: list[str] = []
    for text in suggestions:
        cleaned = _normalize_usage_care_snippet(text)
        if not cleaned:
            continue
        if usage_subtype == "maintenance":
            if any(term in cleaned for term in USAGE_CARE_MAINTENANCE_WEAK_TERMS):
                continue
        if usage_subtype == "burnt" and any(term in question_text for term in USAGE_CARE_COOKWARE_TERMS):
            if any(term in cleaned for term in USAGE_CARE_NON_COOKWARE_TERMS) and not any(term in cleaned for term in USAGE_CARE_COOKWARE_TERMS):
                continue
        points.append(cleaned.strip("。；; "))
    if not points:
        return []
    if usage_subtype == "maintenance":
        points = [p for p in points if any(term in p for term in USAGE_CARE_MAINTENANCE_ACTION_TERMS)] or points
    if usage_subtype == "burnt":
        points = [p for p in points if any(term in p for term in ("温水", "软刷", "浸泡", "钢丝球", "锅底", "残渍", "清洗", "涂层"))] or points
        if not any(term in "".join(points) for term in ("糊锅", "烧焦", "焦糊", "粘底", "残渍", "锅底")):
            points.insert(0, "目前没有专门糊锅资料，可先按类似锅具保养方式轻刷处理")
    return points[:4]


def _compose_usage_care_sections(question: str, suggestions: list[str], *, usage_subtype: str) -> dict[str, str]:
    points = _compose_usage_care_summary(question, suggestions, usage_subtype=usage_subtype)
    cleaning_parts: list[str] = []
    caution_parts: list[str] = []
    avoid_parts: list[str] = []
    seen_parts: set[str] = set()

    for point in points:
        for clause in _usage_care_clauses(point):
            normalized = clause.strip("。；; ，,")
            if not normalized or normalized in seen_parts:
                continue
            bucket = _classify_usage_care_clause(normalized)
            if bucket == "avoid":
                avoid_parts.append(normalized)
            elif bucket == "caution":
                caution_parts.append(normalized)
            else:
                cleaning_parts.append(normalized)
            seen_parts.add(normalized)

    if not cleaning_parts and points:
        cleaning_parts.append(_usage_care_clauses(points[0])[0].strip("。；; ，,"))
    if not caution_parts:
        caution_parts.append("清洗后尽量擦干或烘干，再放在干燥处保存")
    if not avoid_parts:
        avoid_parts.append("避免钢丝球、硬物刮擦，以及骤冷骤热或长时间浸泡")

    return {
        "cleaning": _render_usage_care_bucket("cleaning", cleaning_parts[:2], usage_subtype=usage_subtype),
        "caution": _render_usage_care_bucket("caution", caution_parts[:2], usage_subtype=usage_subtype),
        "avoid": _render_usage_care_bucket("avoid", avoid_parts[:2], usage_subtype=usage_subtype),
    }


def _usage_care_clauses(text: str) -> list[str]:
    value = _normalize_usage_care_snippet(text)
    if not value:
        return []
    parts = [part.strip() for part in re.split(r"[，,；;。]", value) if part.strip()]
    return parts or [value]


def _classify_usage_care_clause(clause: str) -> str:
    avoid_terms = ("避免", "不要", "严禁", "禁用", "勿", "钢丝球", "硬物", "骤冷骤热", "干烧", "久放", "刮擦")
    cleaning_terms = ("清洗", "清洁", "温水", "软刷", "浸泡", "擦干", "烘干", "预热", "倒油", "冲洗", "小火")
    caution_terms = ("建议", "尽量", "及时", "趁热", "彻底", "存放", "晾干", "干燥处", "中小火", "涂层", "使用后")

    if any(term in clause for term in avoid_terms):
        return "avoid"
    if any(term in clause for term in cleaning_terms):
        return "cleaning"
    if any(term in clause for term in caution_terms):
        return "caution"
    return "caution"


def _short_usage_care_line(text: str) -> str:
    value = _normalize_usage_care_snippet(text).strip("。；; ")
    if not value:
        return ""
    parts = [part.strip() for part in re.split(r"[；;。，,]", value) if part.strip()]
    line = "；".join(parts[:2]).strip("；; ")
    if len(line) > 58:
        line = line[:58].rstrip("，,；;、 ")
    return line + "。"


def _render_usage_care_bucket(bucket: str, parts: list[str], *, usage_subtype: str) -> str:
    if usage_subtype == "burnt":
        if bucket == "cleaning":
            return "目前没有专门糊锅资料，可先用温水和软刷轻刷处理。"
        if bucket == "caution":
            return "如果是涂层锅，先避免强力刮擦。"
        return "不要用钢丝球硬刮，避免伤到涂层。"

    cleaned = []
    for part in parts:
        clause = _trim_usage_care_clause(part)
        if clause and not _is_usage_care_output_noise(clause):
            cleaned.append(clause)
    if bucket == "cleaning":
        return _short_usage_care_line("，".join(cleaned[:2])) or "用温水和软刷清洗，洗后擦干或小火烘干。"
    if bucket == "caution":
        return _short_usage_care_line("，".join(cleaned[:2])) or "洗后擦干或小火烘干，再放在干燥处保存。"
    return _short_usage_care_line("，".join(cleaned[:2])) or "不要用钢丝球、硬物刮擦，也不要长时间浸泡。"


def _is_usage_care_output_noise(text: str) -> bool:
    value = str(text or "")
    noise_terms = (
        "表面采用",
        "工艺",
        "耐高温漆",
        "水性不粘涂层",
        "耐磨耐用",
        "易清洁",
        "SKU:",
        "中文名:",
        "英文名:",
        "品牌:",
        "系列:",
        "类目:",
        "规格信息",
        "生命周期:",
        "负责人:",
    )
    return any(term in value for term in noise_terms) or len(value) > 80


def _trim_usage_care_clause(text: str) -> str:
    value = _normalize_usage_care_snippet(text).strip("。；; ，,")
    if not value:
        return ""
    replacements = (
        ("根据目前知识库中的", ""),
        ("根据目前知识库", ""),
        ("目前知识库", ""),
        ("下面仅能根据类似锅具与涂层产品的清洗保养资料给出保守建议", ""),
        ("保守建议", ""),
        ("建议使用后", "用完"),
        ("使用后", "用完"),
        ("及时", ""),
        ("彻底", ""),
        ("存放于", "放在"),
        ("存放在", "放在"),
        ("尽量避免", "不要"),
        ("避免使用", "不要用"),
        ("避免钢丝球", "不要用钢丝球"),
        ("避免硬物", "不要用硬物"),
    )
    for old, new in replacements:
        value = value.replace(old, new)
    value = re.sub(r"\s+", "", value)
    value = re.sub(r"^[，,；;]+", "", value)
    return value


def _infer_recommendation_need_from_question(question: str) -> str:
    value = str(question or "").strip()
    if not value:
        return ""
    if any(token in value for token in ("高海拔", "高山")):
        return "高海拔户外做饭"
    if any(token in value for token in ("徒步", "轻量", "越轻越好")):
        return "单人徒步、轻量携带"
    if any(token in value for token in ("凉水", "冷水", "补水", "夏天")):
        return "夏天户外补水"
    if any(token in value for token in ("4人以上", "多人", "家庭")):
        return "4人以上露营做饭"
    return ""


def _is_cold_water_hydration_recommendation(question: str) -> bool:
    return _infer_recommendation_need_from_question(question) == "夏天户外补水"


def _recommendation_reason_priority(question: str, text: str) -> int:
    value = str(text or "").strip()
    if not value or not _is_cold_water_hydration_recommendation(question):
        return 0
    positive_terms = ("补水", "饮水", "凉水", "冷水", "便携", "轻量", "徒步", "短途", "容量", "ml", "ML", "L", "随身")
    heating_terms = ("快速沸腾", "聚热", "烧水", "煮茶", "加热", "兼容", "明火", "燃气炉", "电磁炉", "电陶炉", "酒精炉")
    score = 0
    if any(term in value for term in positive_terms):
        score += 3
    if any(term in value for term in ("容量", "ml", "ML", "L", "便携", "轻量", "徒步", "短途", "随身")):
        score += 2
    if any(term in value for term in heating_terms):
        score -= 4
    return score


def _should_skip_cold_water_heating_reason(question: str, text: str) -> bool:
    value = str(text or "").strip()
    if not value or not _is_cold_water_hydration_recommendation(question):
        return False
    heating_terms = ("快速沸腾", "聚热", "烧水", "煮茶", "加热", "兼容", "明火", "燃气炉", "电磁炉", "电陶炉", "酒精炉")
    hydration_terms = ("补水", "饮水", "凉水", "冷水", "装水", "便携饮水")
    return any(term in value for term in heating_terms) and not any(term in value for term in hydration_terms)


def _should_rebuild_cold_water_recommendation_answer(question: str, answer: str) -> bool:
    if not _is_cold_water_hydration_recommendation(question):
        return False
    value = str(answer or "").strip()
    if not value:
        return False
    hydration_hits = sum(1 for term in ("补水", "饮水", "凉水", "冷水", "便携", "容量", "随身") if term in value)
    heating_hits = sum(1 for term in ("快速沸腾", "聚热", "烧水", "加热", "煮茶", "兼容") if term in value)
    return heating_hits > 0 and hydration_hits == 0


def _should_force_rebuild_recommendation_answer(question: str) -> bool:
    value = str(question or "").strip()
    if not value:
        return False
    if "推荐" not in value and "适合" not in value:
        return False
    blocked_terms = (
        "为什么推荐",
        "推荐理由",
        "第一个",
        "第二个",
        "这些里面",
        "上面这些",
        "这几个",
        "哪个更适合",
        "换一个",
        "不要刚才那个",
        "替代",
        "更便宜",
        "更轻",
        "前面推荐的",
        "刚才推荐的",
        "为什么是这个",
        "为什么是它",
    )
    if any(term in value for term in blocked_terms):
        return False
    return bool(_infer_recommendation_need_from_question(value))


def _shape_recommendation_answer_from_ranked(ranked: list[dict], question: str = "") -> str:
    picks = []
    for item in ranked[:3]:
        row = item.get("row") or {}
        sku = str(row.get("sku") or "").strip()
        if not sku:
            continue
        name = row.get("product_name_cn") or row.get("product_name_en") or sku
        reason = _evidence_based_recommendation_reason(row, item, question=question)
        picks.append({"sku": sku, "name": name, "reason": reason, "row": row})
    if not picks:
        return "目前没有找到合适的产品推荐，你可以换个场景或条件试试。"
    need = _infer_recommendation_need_from_question(question)
    lines: list[str] = []
    for index, item in enumerate(picks):
        intro = "优先推荐" if index == 0 else "也可以考虑"
        reason = str(item["reason"] or "").strip("。；; ")
        sentence = f"{intro}{item['name']}（{item['sku']}）"
        if need:
            sentence += f"，因为它更贴合你“{need}”的需求"
        if reason:
            sentence += f"，{reason}"
        elif not need:
            sentence += "，当前资料里对它的使用场景和卖点描述更完整"
        sentence += "。"
        lines.append(sentence)
    return "\n".join(lines)


def _short_recommendation_reason(text: str) -> str:
    value = str(text or "").strip("。；; ")
    if not value:
        return ""
    parts = [part.strip() for part in re.split(r"[；;。]", value) if part.strip()]
    return "；".join(parts[:2]) + "。"


def _is_generic_recommendation_reason(text: str) -> bool:
    value = str(text or "").strip()
    if not value:
        return True
    generic_terms = (
        "更贴合当前使用场景",
        "更贴合当前需求",
        "更贴合当前使用人数和场景",
        "符合场景语义",
        "匹配",
        "有可用的卖点/场景信息",
        "有容量信息可供判断",
        "有卖点/场景资料可引用",
        "类目匹配",
    )
    if re.search(r"(?:^|：)\s*(?:容量|材质|类目|重量|热源)\s", value):
        return True
    return any(term in value for term in generic_terms)


def _is_recommendation_noise_text(text: str) -> bool:
    value = str(text or "").strip()
    if not value:
        return True
    noisy_patterns = (
        "首次使用",
        "初次使用",
        "严禁骤冷骤热",
        "骤冷骤热",
        "避免空烧",
        "请勿空烧",
        "不要空烧",
        "保养",
        "清洁",
        "清洗",
        "收纳时",
        "使用后",
        "冷却后",
        "浸泡",
        "钢丝球",
        "洗碗机",
        "内容信息",
        "SKU:",
        "中文标题",
        "英文标题",
        "负责人",
    )
    return any(pattern in value for pattern in noisy_patterns)


def _evidence_based_recommendation_reason(row: dict[str, Any], ranked_item: dict[str, Any], *, question: str = "") -> str:
    match = row.get("recommendation_match") if isinstance(row.get("recommendation_match"), dict) else {}
    candidates: list[str] = []
    supporting = row.get("supporting_evidence") if isinstance(row.get("supporting_evidence"), dict) else {}
    for source_key in ("product_qa", "knowledge_chunks"):
        for item in supporting.get(source_key) or []:
            text = str(item.get("summary") or "").strip("。；; ")
            if text and not _is_recommendation_noise_text(text) and not _should_skip_cold_water_heating_reason(question, text):
                candidates.append(text)
    for raw in list(match.get("matched") or []) + list(ranked_item.get("matched") or []) + list(ranked_item.get("reasons") or []):
        text = str(raw or "").strip("。；; ")
        if not text or _is_generic_recommendation_reason(text):
            continue
        if any(noisy in text for noisy in ("有可用", "基础信息", "信息可供判断", "综合资料", "评分", "类目匹配", "有卖点/场景资料可引用")):
            continue
        if _should_skip_cold_water_heating_reason(question, text):
            continue
        candidates.append(text)
    for key in ("features", "usage_scenarios", "target_audience", "positioning"):
        value = str(row.get(key) or "").strip()
        if value and not _is_recommendation_noise_text(value) and not _should_skip_cold_water_heating_reason(question, value):
            candidates.append(value)
    if _is_cold_water_hydration_recommendation(question):
        candidates = sorted(
            candidates,
            key=lambda item: (_recommendation_reason_priority(question, item), -candidates.index(item)),
            reverse=True,
        )
    cleaned: list[str] = []
    seen: set[str] = set()
    for item in candidates:
        item = re.sub(r"\s+", " ", item).strip("。；; ")
        if not item or item in seen:
            continue
        seen.add(item)
        cleaned.append(item)
        if len(cleaned) >= 2:
            break
    if not cleaned:
        return "当前资料不足以展开理由，建议人工再确认具体使用场景。"
    return "；".join(cleaned)[:100].rstrip("；;，,")


def _has_field_stack_recommendation_reason(text: str) -> bool:
    lines = [line.strip() for line in str(text or "").splitlines() if line.strip()]
    reason_lines = [line for line in lines if re.match(r"^[A-Z]{2,6}(?:-[A-Z0-9]{1,8})+：", line)]
    if not reason_lines:
        return False
    stacked = 0
    for line in reason_lines:
        if sum(1 for token in ("容量", "材质", "重量", "热源", "类目") if token in line) >= 2:
            stacked += 1
    return stacked >= max(1, len(reason_lines) // 2)


def _has_sku_reason_lines(text: str) -> bool:
    return any(
        re.match(r"^[A-Z]{2,6}(?:-[A-Z0-9]{1,8})+：", line.strip())
        for line in str(text or "").splitlines()
        if line.strip()
    )


def _shape_recommendation_answer_text(answer: str, ranked: list[dict], question: str = "") -> str:
    text = str(answer or "").strip()
    if not text:
        return _shape_recommendation_answer_from_ranked(ranked, question=question)
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    has_sku_reason_lines = _has_sku_reason_lines(text)
    force_rebuild = _should_force_rebuild_recommendation_answer(question)
    if _should_rebuild_cold_water_recommendation_answer(question, text):
        force_rebuild = True
    if (
        lines
        and lines[0].startswith("推荐：")
        and any(line.startswith("理由：") or re.match(r"^[A-Z]{2,6}(?:-[A-Z0-9]{1,8})+：", line) for line in lines[1:])
        and not force_rebuild
        and not _has_generic_recommendation_reason(text)
        and not _has_field_stack_recommendation_reason(text)
    ):
        return "\n".join(lines[:5])
    allowed_skus = {
        str((item.get("row") or {}).get("sku") or "").strip().upper()
        for item in ranked[:5]
        if str((item.get("row") or {}).get("sku") or "").strip()
    }
    mentioned_skus = {sku.upper() for sku in _extract_skus(text)}
    if (
        mentioned_skus
        and mentioned_skus.issubset(allowed_skus)
        and not force_rebuild
        and not _has_generic_recommendation_reason(text)
        and not _has_field_stack_recommendation_reason(text)
    ):
        return "\n".join(lines[:8])
    return _shape_recommendation_answer_from_ranked(ranked, question=question)


def _has_generic_recommendation_reason(text: str) -> bool:
    return any(_is_generic_recommendation_reason(line) for line in str(text or "").splitlines())


def _sanitize_usage_care_answer_text(answer: str) -> str:
    value = str(answer or "").strip()
    if not value:
        return ""
    value = re.sub(r"\bQ[:：]\s*", "", value, flags=re.IGNORECASE)
    value = re.sub(r"\bA[:：]\s*", "", value, flags=re.IGNORECASE)
    lines = [re.sub(r"[ \t]+", " ", line).strip() for line in value.splitlines()]
    value = "\n".join(line for line in lines if line)
    value = value.replace("。。", "。")
    return value


def _usage_care_debug_source_texts(qa_hits: list[dict], knowledge_hits: list[dict]) -> list[dict]:
    rows: list[dict] = []
    for item in qa_hits[:3]:
        rows.append({
            "source_kind": "product_qa",
            "sku": item.get("sku"),
            "text": str(item.get("answer") or "")[:200],
        })
    for item in knowledge_hits[:3]:
        rows.append({
            "source_kind": "knowledge_chunks",
            "sku": item.get("sku"),
            "text": str(item.get("content") or "")[:200],
        })
    return rows


def _usage_care_results_for_response(qa_hits: list[dict], knowledge_hits: list[dict]) -> list[dict]:
    results = []
    for item in qa_hits:
        results.append({
            "sku": item.get("sku"),
            "product_name_cn": item.get("product_name_cn"),
            "field_values": {"使用/清洗保养建议": item.get("answer") or ""},
            "matched_by": "product_qa",
        })
    for item in knowledge_hits:
        results.append({
            "sku": item.get("sku"),
            "product_name_cn": "",
            "field_values": {"使用/清洗保养建议": item.get("content") or ""},
            "matched_by": "knowledge_chunks",
        })
    return results


async def _llm_compose_answer(
    db: Session,
    question: str,
    rows: list[dict],
    intent: "CustomerIntent",
    qa_results: list[dict],
    kb_results: list[dict],
    warnings: list[str],
    followups: list[str],
) -> str:
    """Use LLM to compose a natural customer service reply from structured data."""
    if not rows:
        return "没有找到匹配的产品资料，请换一个 SKU、产品名或筛选条件再试。"

    # Build context for LLM
    product_info = []
    for row in rows[:5]:
        info = {
            "SKU": row.get("sku", ""),
            "名称": row.get("product_name_cn") or row.get("product_name_en") or "",
            "品牌": row.get("brand", ""),
            "类目": row.get("category", ""),
            "负责人": row.get("person_in_charge", ""),
            "生命周期": row.get("lifecycle_status", ""),
        }
        # Add field values if present
        for key, value in (row.get("field_values") or {}).items():
            if value and value not in ("无", ""):
                info[key] = value
        # Add key spec fields
        for field in [
            "capacity",
            "body_material",
            "color",
            "heat_source",
            "power",
            "technical_advantages",
            "usage_instruction",
            "top_selling_points",
            "usage_scenarios",
            "target_audience",
            "quality_note",
        ]:
            val = row.get(field)
            if val:
                label = {
                    "capacity": "容量",
                    "body_material": "材质",
                    "color": "颜色",
                    "heat_source": "热源",
                    "power": "功率",
                    "technical_advantages": "技术优势",
                    "usage_instruction": "使用说明",
                    "top_selling_points": "卖点",
                    "usage_scenarios": "使用场景",
                    "target_audience": "目标人群",
                    "quality_note": "品质备注",
                }.get(field, field)
                info[label] = str(val)
        product_info.append(info)

    qa_text = ""
    if qa_results:
        qa_parts = []
        for qa in qa_results[:3]:
            qa_parts.append(f"Q: {qa['question']}\nA: {qa['answer']}")
        qa_text = "\n".join(qa_parts)

    kb_text = ""
    if kb_results:
        kb_parts = []
        for kb in kb_results[:3]:
            content_text = kb.get("content", "")[:300]
            if content_text:
                kb_parts.append(content_text)
        kb_text = "\n".join(kb_parts)

    warnings_text = "\n".join(warnings[:3]) if warnings else ""
    followups_text = "\n".join(followups[:3]) if followups else ""

    import json as _json
    system_prompt = """你是产品知识库智能客服。请基于给定产品资料、QA 和知识库片段回答用户。

要求：
1. 先给结论，再给依据。
2. 如果 QA 能直接回答，优先使用 QA。
3. 如果知识库有补充信息，可以合并说明。
4. 不要编造工具结果之外的参数、价格、库存或承诺。
5. 如果数据缺失，要明确说“资料里暂未提供”。
6. 回答控制在 1-2 段，必要时给下一步建议。
7. 如果有异常或警告，要友善提醒。
8. 推荐类问题要解释取舍理由。
9. 当用户询问食品级、认证、安全性时，只能引用认证字段、QA、使用说明或明确安全说明；如果认证资料为空或未注明，必须说“食品级认证资料中暂未注明，建议联系人工确认”，不能仅凭“304不锈钢”推断“食品级/可以放心使用”。
10. 不要使用 Markdown 表格。"""

    user_prompt = f"""用户问题：{question}

产品资料：
{_json.dumps(product_info, ensure_ascii=False, indent=2)}

QA 资料：
{qa_text or "暂无 QA"}

知识库资料：
{kb_text or "暂无知识库资料"}

异常/警告：
{warnings_text or "无"}

建议追问：
{followups_text or "无"}"""

    try:
        answer = await customer_llm_service.chat_completion(
            db,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.3,
            max_tokens=800,
            purpose="detail_answer",
        )
        return (answer or "").strip()
    except Exception:
        # Fallback: use template composition
        return _compose_row_answer(rows, intent, warnings, [], followups, qa_results, kb_results)


def _detect_row_anomalies(rows: list[dict], intent: CustomerIntent) -> list[dict[str, Any]]:
    anomalies: list[dict[str, Any]] = []
    for row in rows:
        sku = str(row.get("sku") or "")
        english_name = str(row.get("product_name_en") or "").strip()
        if english_name and (english_name.isdigit() or english_name.lower() in PLACEHOLDER_WORDS):
            anomalies.append({
                "sku": sku,
                "field": "英文名称",
                "message": f"{sku} 的英文名“{english_name}”更像占位值或编号，建议人工复核。",
            })
        for field in ["capacity", "body_material", "color", "person_in_charge"]:
            value = str(row.get(field) or "").strip()
            if not value:
                continue
            label = {"capacity": "容量", "body_material": "材质", "color": "颜色", "person_in_charge": "负责人"}[field]
            anomaly = _field_anomaly_for_value(sku, label, value)
            if anomaly:
                anomalies.append(anomaly)
    return anomalies


def _field_anomaly_for_value(sku: str, label: str, value: str) -> dict[str, Any] | None:
    normalized = str(value or "").strip()
    if not normalized:
        return {"sku": sku, "field": label, "message": f"{sku} 的{label}当前为空。"}
    if _is_placeholder_value(normalized):
        return {"sku": sku, "field": label, "message": f"{sku} 的{label}看起来还是占位值“{normalized}”。"}
    if label == "容量":
        if normalized in SUSPICIOUS_CAPACITY_WORDS:
            return {"sku": sku, "field": label, "message": f"{sku} 的容量值“{normalized}”像是品类词，不像标准容量，建议人工核对。"}
        if not re.search(r"\d", normalized) and len(normalized) <= 4:
            return {"sku": sku, "field": label, "message": f"{sku} 的容量值“{normalized}”缺少常见数值单位，建议人工核对。"}
    return None


def _suggest_followups(rows: list[dict], intent: CustomerIntent) -> list[str]:
    if not rows:
        return [
            "你可以补充 SKU、类目、负责人，或者描述更具体的使用场景。",
            "如果你愿意，我也可以换一种条件帮你重查。",
        ]
    if len(rows) > 10:
        return [
            "结果较多，我可以继续按负责人、类目、容量或使用场景缩小范围。",
            "也可以直接说“这些里哪个更适合露营/泡咖啡/多人使用”。",
        ]
    return [
        "如果你想继续追问，我可以把这批产品的容量、材质、颜色或负责人分别列出来。",
        "也可以继续做对比、推荐，或者生成待确认修改动作。",
    ]


def _suggest_detail_followups(intent: CustomerIntent) -> list[str]:
    fields = " ".join(intent.requested_fields or [])
    if any(item in fields for item in ("防水", "防泼水")):
        return [
            "建议补充或核对产品说明里的防水/防泼水参数；没有明确资料时不建议对客户承诺防水。",
            "我也可以继续查它的使用说明、表面处理和材质信息，帮你判断能否接触水或如何保养。",
        ]
    if any(item in fields for item in ("不粘", "煎蛋", "煎")):
        return [
            "我可以继续查它的涂层、表面处理和卖点，判断是否能支撑“不粘/煎蛋”话术。",
            "如果要对外宣传，建议只引用资料里明确出现的卖点。",
        ]
    if any(item in fields for item in ("适合", "场景", "露营", "咖啡")):
        return [
            "我可以继续结合使用场景、卖点和容量，判断它适合哪类用户或场景。",
            "如果你有具体场景，比如露营、泡咖啡或多人使用，我可以按这个场景重新判断。",
        ]
    return [
        "如果你还想横向比较，我可以继续把这些 SKU 的其他字段一起对比出来。",
        "如果你要继续筛选，也可以直接说“把负责人不是某人的排除掉”。",
    ]


async def _rank_rows_for_recommendation_llm(db: Session, rows: list[dict], query: str) -> list[dict[str, Any]]:
    """Use LLM to rank products for recommendation based on actual reasoning."""
    if not rows or not query:
        return [{"row": r, "score": 0, "reasons": ["无足够信息排名"]} for r in rows]
    
    import json as _json
    product_list = []
    for i, row in enumerate(rows[:10]):
        info = {
            "index": i,
            "sku": row.get("sku", ""),
            "name": row.get("product_name_cn") or row.get("product_name_en") or "",
            "category": row.get("category", ""),
            "capacity": _format_capacity(row.get("capacity")) if row.get("capacity") else "",
            "material": row.get("body_material", ""),
            "color": row.get("color", ""),
            "features": row.get("features", ""),
            "target_audience": row.get("target_audience", ""),
            "usage_scenarios": row.get("usage_scenarios", ""),
            "positioning": row.get("positioning", ""),
            "price_positioning": row.get("price_positioning", ""),
        }
        product_list.append(info)
    
    system_prompt = (
        "你是户外装备推荐专家。根据用户需求，从候选产品中选出最合适的，并给出排名理由。"
        "输出JSON格式：{\"ranking\": [{\"index\": 0, \"reason\": \"推荐理由\"}, ...]}"
        "推荐时要综合考虑容量、材质、适用场景、目标人群、价格定位、产品定位、便携性等因素。"
        "如果用户说预算不高、便宜点、性价比，要优先选择价格定位更亲民/入门/常规的候选；高端或高价定位不能作为低预算首选。"
        "按推荐优先顺序排列。"
    )
    
    try:
        result = await customer_llm_service.chat_completion(
            db,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": f"用户需求: {query}\n\n候选产品:\n{_json.dumps(product_list, ensure_ascii=False, indent=2)}"},
            ],
            temperature=0.1,
            max_tokens=600,
            purpose="rank",
        )
        ranking_data = _parse_llm_json(result or "")
        if ranking_data and ranking_data.get("ranking"):
            ranked = customer_recommendation_ranker.rank_from_llm_order(rows, ranking_data["ranking"], query)
            return ranked if ranked else _fallback_rank(rows, query)
    except Exception:
        pass
    return _fallback_rank(rows, query)


def _fallback_rank(rows: list[dict], query: str) -> list[dict[str, Any]]:
    return customer_recommendation_ranker.fallback_rank(rows, query)


def _budget_score(query: str, row: dict) -> int:
    return customer_recommendation_ranker.budget_score(query, row)
def _confidence_for_rows(rows: list[dict], intent: CustomerIntent, warnings: list[str]) -> str:
    if not rows:
        return "medium" if intent.source_context == "previous_results" else "low"
    if warnings:
        return "medium"
    if intent.semantic_query and len(rows) > 15:
        return "medium"
    return "high"


def _intent_label(intent: CustomerIntent) -> str:
    if intent.special_filter == "english_name_numeric":
        return "英文名称为纯数字"
    if intent.special_filter == "english_name_contains_digit":
        return "英文名称包含数字"
    if intent.special_filter == "english_name_exact":
        return f"英文名称等于 {intent.exact_value}"
    if intent.filters and intent.semantic_query:
        return "同时满足结构化条件和场景语义"
    if intent.filters and intent.negative_filters:
        return "筛选后保留"
    if intent.filters:
        return "符合筛选条件"
    if intent.semantic_query:
        return "符合场景语义"
    return "匹配"


def _requested_fields(text: str) -> list[str]:
    fields = []
    value = str(text or "")
    asks_handle_material = (
        any(part in value for part in ("手柄", "把手"))
        and any(term in value for term in ("材质", "材料", "木料", "木头"))
    )
    candidates = [
        ("容量", ("容量", "多少ml", "多少ML", "多少毫升", "多少毫L", "多少毫升?", "多大容量", "容量多少", "几升", "多少升", "能装多少毫升", "能装多少ml")),
        ("尺寸", ("尺寸", "多大尺寸", "长宽高")),
        ("材质", ("材质", "材料", "木料", "木头", "主体材质", "手柄材质", "手柄是什么材质", "把手材质", "把手是什么材质", "304", "不锈钢", "stainless steel", "corrosion resistant", "耐腐蚀")),
        ("颜色", ("颜色", "配色")),
        ("最大承重", ("最大承重", "承重能力", "能承重", "能承受多重", "承载多少", "承重量", "负重")),
        ("重量", ("重量", "多重", "净重", "毛重")),
        ("热源", ("热源", "燃料", "适用热源")),
        ("功率", ("功率", "火力")),
        ("表面处理", ("表面处理", "表面工艺", "工艺", "涂层", "有涂层")),
        ("价格定位", ("价格定位", "价位", "价格带")),
        ("认证", ("认证", "出口认证", "认证信息", "食品级", "FDA", "LFGB", "food grade", "certification", "certified")),
        ("卖点", ("卖点", "特色", "优势", "特点", "核心买点", "核心卖点", "好在哪里")),
        ("商品英文名称", ("英文名", "英文名称", "商品英文名称")),
        ("SKU", ("SKU", "sku", "型号", "货号")),
        ("配件", ("配件", "包装里", "包装内", "包含什么", "几个锅", "几件", "数量", "手柄", "把手", "煎盘", "锅盖", "盖子")),
        ("负责人", ("负责人",)),
        ("品质情况", ("品质", "品质情况", "坏损")),
        ("类目", ("类目", "品类")),
        ("防水", ("防水", "防泼水")),
        ("不粘", ("不粘", "不沾")),
        ("禁止操作", ("禁止操作", "禁忌", "不能这样用", "有什么注意事项", "注意事项")),
        ("正品辨别", ("防伪", "真假", "正品辨别", "怎么辨别正品", "如何辨别正品")),
        ("适用场景", ("适用场景", "使用场景", "场景", "适合谁", "适合什么场景", "适合哪些场景", "适合哪些人群", "适用人群")),
        ("适配情况", ("洗碗机", "能放进洗碗机", "能放洗碗机", "是否适合洗碗机")),
    ]
    for label, aliases in candidates:
        if label == "配件" and asks_handle_material:
            continue
        if any(alias in text for alias in aliases) and label not in fields:
            fields.append(label)
    if _looks_like_water_container_capability_question(value) and "适配情况" not in fields:
        fields.append("适配情况")
    if (
        "热源" not in fields
        and any(term in text for term in ("支持", "适配", "能用", "可以用", "能不能用", "能否用"))
        and any(term in text for term in ("酒精", "气罐", "卡式炉", "燃气炉", "炉", "燃料"))
    ):
        fields.append("热源")
    return fields


def _remove_subject_once(text: str, subject: str) -> str:
    value = str(text or "")
    subject_text = str(subject or "").strip()
    if not value or not subject_text:
        return value
    variants = {subject_text, subject_text.replace("－", "-"), subject_text.replace("-", "－")}
    result = value
    for variant in sorted(variants, key=len, reverse=True):
        if variant and variant in result:
            return result.replace(variant, "", 1)
    return value


def _filter_requested_fields_outside_subject(text: str, subject: str, fields: list[str]) -> list[str]:
    remainder = _remove_subject_once(text, subject)
    if remainder == text:
        return fields
    outside_fields = _requested_fields_for_detail_question(remainder)
    if not outside_fields:
        return fields
    return [field for field in fields if field in outside_fields]


def _resolve_query_field(field_label: str) -> str | None:
    if not field_label:
        return None
    direct = {
        "商品英文名称": "product.product_name_en",
        "英文名称": "product.product_name_en",
        "英文名": "product.product_name_en",
        "负责人": "product.person_in_charge",
        "品质情况": "product.quality_note",
        "品质": "product.quality_note",
        "坏损": "product.quality_note",
        "类目": "product.category",
        "SKU": "product.sku",
        "容量": "specs.capacity",
        "尺寸": "specs.size_info",
        "材质": "specs.body_material",
        "颜色": "specs.color",
        "最大承重": "virtual.load_capacity",
        "承重": "virtual.load_capacity",
        "承重能力": "virtual.load_capacity",
        "重量": "specs.gross_weight_g",
        "热源": "specs.heat_source",
        "燃料": "specs.heat_source",
        "功率": "specs.power",
        "表面处理": "specs.surface_finish",
        "不粘": "specs.surface_finish",
        "适配情况": "specs.usage_instruction",
        "价格定位": "business.price_positioning",
        "卖点": "business.top_selling_points",
        "核心卖点": "business.top_selling_points",
        "适用场景": "business.usage_scenarios",
        "使用场景": "business.usage_scenarios",
        "场景": "business.usage_scenarios",
        "目标人群": "business.target_audience",
        "适合人群": "business.target_audience",
        "配件": "specs.usage_instruction",
    }
    return direct.get(field_label) or customer_agent_service.QUERY_FIELD_ALIASES.get(field_label) or agent_action_service.resolve_field_path(field_label)


def _field_label(field_path: str) -> str:
    if field_path == "virtual.load_capacity":
        return "最大承重"
    spec = customer_agent_service.QUERY_FIELD_SPECS.get(field_path)
    if spec:
        return spec[2]
    field_spec = agent_action_service.FIELD_SPECS.get(field_path)
    return field_spec.label if field_spec else field_path


def _value_from_detail(detail: dict[str, Any], field_path: str) -> Any:
    if field_path == "virtual.load_capacity":
        return None
    section, field_name = field_path.split(".", 1)
    if section == "product":
        return detail.get(field_name)
    return (detail.get(section) or {}).get(field_name)


def _is_delete_request(text: str) -> bool:
    return any(word in text for word in ("删除", "删掉", "移除")) and any(word in text for word in ("产品", "SKU", "这些", "它们"))


def _has_context_reference(text: str) -> bool:
    value = str(text or "")
    return any(word in value for word in CONTEXT_WORDS) or any(pattern.search(value) for pattern in ORDINAL_CONTEXT_PATTERNS)


def _extract_skus(text: str) -> list[str]:
    return customer_agent_service._extract_skus(text)


def _format_capacity(capacity: Any) -> str:
    if isinstance(capacity, dict):
        label = str(capacity.get("label", "")).strip()
        value = str(capacity.get("value", "")).strip()
        if label and value:
            return value if label == value else f"{label} {value}"
        return value or label
    if isinstance(capacity, list):
        parts = []
        for entry in capacity:
            if isinstance(entry, dict):
                label = str(entry.get("label", "")).strip()
                value = str(entry.get("value", "")).strip()
                if label and value:
                    parts.append(f"{label} {value}")
                elif value:
                    parts.append(value)
        return "; ".join(parts) if parts else ""
    if isinstance(capacity, str) and capacity.strip().startswith("["):
        try:
            parsed = json.loads(capacity)
            if isinstance(parsed, list):
                return _format_capacity(parsed)
        except Exception:
            pass
    if isinstance(capacity, str) and capacity.strip().startswith("{"):
        try:
            parsed = json.loads(capacity)
            if isinstance(parsed, dict):
                return _format_capacity(parsed)
        except Exception:
            pass
    return str(capacity) if capacity else ""


def _field_text(row: dict[str, Any], field_path: str) -> str:
    field_name = field_path.split(".", 1)[1] if "." in field_path else field_path
    val = row.get(field_name)
    if val is None and field_name in ("top_selling_points", "target_audience", "positioning", "price_positioning", "emotional_value", "usage_scenarios", "competitor_benchmark"):
        val = row.get("features")
    text = _format_field_value(val, field_path) if val not in (None, "") else ""
    return text


def _format_field_value(value: Any, field_path: str) -> str:
    if field_path == "specs.capacity":
        return _format_capacity(value) or "暂无"
    if field_path == "specs.gross_weight_g":
        text = customer_agent_service._stringify(value).strip()
        if not text or text == "暂无":
            return "暂无"
        try:
            number = float(text)
            text = str(int(number)) if number.is_integer() else str(number)
        except Exception:
            pass
        lowered = text.lower()
        if lowered.endswith(("g", "kg", "克", "千克")):
            return text
        return f"{text}g"
    return customer_agent_service._stringify(value)


def _extract_load_capacity_from_detail(detail: dict[str, Any], supporting: dict[str, Any] | None = None) -> str:
    sku = str(detail.get("sku") or "").strip().upper()
    for text in _load_capacity_texts_from_detail(detail):
        extracted = _extract_load_capacity_phrase(text)
        if extracted:
            return extracted
    for bucket in ("qa", "kb", "raw_rows", "evidence"):
        for item in (supporting or {}).get(bucket) or []:
            if not isinstance(item, dict):
                continue
            item_sku = str(item.get("sku") or "").strip().upper()
            if sku and item_sku and item_sku != sku:
                continue
            for key in ("content", "evidence_text", "answer", "value"):
                extracted = _extract_load_capacity_phrase(str(item.get(key) or ""))
                if extracted:
                    return extracted
    return ""


def _load_capacity_texts_from_detail(detail: dict[str, Any]) -> list[str]:
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
        add_text(detail.get(key))
    for section in ("specs", "business", "content"):
        nested = detail.get(section)
        if isinstance(nested, dict):
            add_text(nested)
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


def _detail_mentions(detail: dict[str, Any], terms: list[str]) -> list[str]:
    terms = [str(item).strip() for item in terms if str(item).strip()]
    if not terms:
        return []
    hits = []
    for label, value in _detail_evidence_items(detail, include_empty=False):
        text = f"{label}：{value}"
        if any(term in text for term in terms):
            hits.append(text)
    return hits


def _unknown_attribute_evidence(detail: dict[str, Any]) -> list[str]:
    preferred = {"类目", "材质", "表面处理", "适用热源", "技术优势", "核心卖点", "使用场景", "使用说明"}
    return [
        f"{label}：{value}"
        for label, value in _detail_evidence_items(detail, include_empty=False)
        if label in preferred
    ]


def _detail_evidence_items(detail: dict[str, Any], *, include_empty: bool) -> list[tuple[str, str]]:
    specs = detail.get("specs") or {}
    business = detail.get("business") or {}
    items = [
        ("类目", detail.get("category")),
        ("材质", specs.get("body_material")),
        ("表面处理", specs.get("surface_finish")),
        ("适用热源", specs.get("heat_source")),
        ("技术优势", specs.get("technical_advantages")),
        ("核心卖点", business.get("top_selling_points")),
        ("使用场景", business.get("usage_scenarios")),
        ("使用说明", specs.get("usage_instruction")),
    ]
    result = []
    for label, value in items:
        text = customer_agent_service._stringify(value) if value not in (None, "") else ""
        if text or include_empty:
            result.append((label, text or "暂无"))
    return result


def _row_brief(item: dict[str, Any]) -> str:
    parts = [item.get("sku", ""), item.get("product_name_cn") or item.get("product_name_en") or ""]
    if item.get("product_name_en"):
        parts.append(f"英文名：{item.get('product_name_en')}")
    if item.get("category"):
        parts.append(f"类目：{item.get('category')}")
    if item.get("person_in_charge"):
        parts.append(f"负责人：{item.get('person_in_charge')}")
    if item.get("quality_note"):
        parts.append(f"品质：{item.get('quality_note')}")
    if item.get("capacity"):
        parts.append(f"容量：{_format_capacity(item.get('capacity'))}")
    return "；".join(part for part in parts if part)


def _steps(intent: CustomerIntent, extra_steps: list[dict]) -> list[dict]:
    return [
        {
            "type": "intent_parse",
            "label": "识别问题意图",
            "detail": json.dumps(intent.as_dict(), ensure_ascii=False),
            "ok": True,
        },
        *extra_steps,
        {
            "type": "answer_summary",
            "label": "整理客服回复",
            "detail": "基于工具结果生成客服化答复",
            "ok": True,
        },
    ]


class CustomerAnswerComposer:
    @staticmethod
    def build_contract(
        *,
        intent: CustomerIntent,
        answer: str,
        results: list[dict],
        steps: list[dict],
        warnings: list[str],
        anomalies: list[dict[str, Any]],
        needs_clarification: bool,
        answer_type: str | None,
        evidence: list[dict[str, Any]] | None,
        uncertainty: str | None,
        debug: dict[str, Any] | None,
    ) -> dict[str, Any]:
        final_evidence = evidence if evidence is not None else _build_evidence(results)
        final_answer_type = answer_type or _answer_type_for_intent(intent)
        final_uncertainty = uncertainty or _uncertainty_for_response(
            results=results,
            warnings=warnings,
            needs_clarification=needs_clarification,
            answer=answer,
        )
        final_debug = debug or {
            "intent": intent.as_dict(),
            "steps": steps,
            "warnings": warnings,
            "anomalies": anomalies,
            "raw_results": results,
        }
        return {
            "answer_type": final_answer_type,
            "uncertainty": final_uncertainty,
            "evidence": final_evidence,
            "debug": final_debug,
        }


def _build_response(
    *,
    intent: CustomerIntent,
    answer: str,
    sku: str | None,
    sources: list[dict],
    results: list[dict],
    steps: list[dict],
    confidence: str,
    warnings: list[str],
    anomalies: list[dict[str, Any]],
    suggested_followups: list[str],
    actions: list[dict] | None = None,
    needs_clarification: bool = False,
    answer_type: str | None = None,
    evidence: list[dict[str, Any]] | None = None,
    uncertainty: str | None = None,
    debug: dict[str, Any] | None = None,
) -> dict:
    response_skus = [
        str(row.get("sku") or "").strip().upper()
        for row in (results or [])
        if isinstance(row, dict) and str(row.get("sku") or "").strip()
    ]
    contract = CustomerAnswerComposer.build_contract(
        intent=intent,
        answer=answer,
        results=results,
        steps=steps,
        warnings=warnings,
        anomalies=anomalies,
        needs_clarification=needs_clarification,
        answer_type=answer_type,
        evidence=evidence,
        uncertainty=uncertainty,
        debug=debug,
    )
    return {
        "intent": intent.intent,
        "answer_type": contract["answer_type"],
        "confidence": confidence,
        "uncertainty": contract["uncertainty"],
        "needs_clarification": needs_clarification,
        "anomalies": anomalies,
        "suggested_followups": suggested_followups,
        "followups": suggested_followups,
        "evidence": contract["evidence"],
        "debug": contract["debug"],
        "answer": answer,
        "sku": sku,
        "sources": sources,
        "actions": actions or [],
        "results": results,
        "result_skus": response_skus,
        "candidate_skus": response_skus,
        "steps": steps,
        "warnings": warnings,
    }


def _answer_type_for_intent(intent: CustomerIntent) -> str:
    mapping = {
        "query_products": "product_query",
        "product_detail": "product_detail",
        "compare_products": "comparison",
        "recommend_products": "recommendation",
        "propose_delete": "action_proposal",
        "propose_update": "action_proposal",
        "clarify": "clarification",
    }
    return mapping.get(intent.intent, intent.intent or "unknown")


def _uncertainty_for_response(
    *,
    results: list[dict],
    warnings: list[str],
    needs_clarification: bool,
    answer: str,
) -> str:
    if needs_clarification:
        return "ambiguous_product"
    if not results and "没有找到" in (answer or ""):
        return "insufficient_data"
    if any(text in (answer or "") for text in ("没有标注", "不能直接确认", "暂时不能确认", "资料未标注")):
        return "not_recorded"
    if warnings:
        return "insufficient_data"
    return "confirmed"


def _build_evidence(results: list[dict]) -> list[dict[str, Any]]:
    evidence = []
    for item in results[:8]:
        if not isinstance(item, dict):
            continue
        field_values = item.get("field_values") if isinstance(item.get("field_values"), dict) else {}
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
        for label, key in [
            ("容量", "capacity"),
            ("材质", "body_material"),
            ("颜色", "color"),
            ("负责人", "person_in_charge"),
            ("类目", "category"),
            ("卖点", "features"),
        ]:
            value = item.get(key)
            if value not in (None, ""):
                evidence.append({
                    "sku": item.get("sku"),
                    "product_name": item.get("product_name_cn") or item.get("product_name_en"),
                    "field_label": label,
                    "value": _format_capacity(value) if key == "capacity" else customer_agent_service._stringify(value),
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


def _first_nonempty(values: list[Any]) -> str:
    for value in values:
        text = customer_agent_service._stringify(value)
        if text:
            return text
    return ""


