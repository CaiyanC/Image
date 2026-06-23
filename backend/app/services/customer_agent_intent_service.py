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
from . import agent_action_service, customer_agent_service, customer_agent_tool_service, customer_cache_service, customer_llm_service, customer_perf_service, customer_recommendation_ranker, knowledge_service, product_service


CONTEXT_WORDS = (
    "他", "它", "这个", "这款", "该产品", "这些", "那些", "刚才那些", "上面这些", "刚才的", "刚才说的",
    "上一轮", "之前", "前面", "最开始", "第一个", "第一款", "最后", "上一个", "这一批", "这批", "这几个", "那几个", "里面",
)
QUESTION_WORDS = ("哪些", "有哪些", "多少", "分别", "列出", "查询", "找", "是什么")
COMPARE_WORDS = ("对比", "比较", "区别", "差异", "分别")
RECOMMEND_WORDS = ("推荐", "更适合", "最适合", "最合适", "合适", "哪个好", "哪款", "哪款更好", "优先", "比较轻", "比较小", "最轻", "最小", "带什么", "带哪个", "选哪个", "买哪个")
FOLLOWUP_NARROW_WORDS = ("排除", "不要", "去掉", "剔除", "排掉")
PLACEHOLDER_WORDS = {"tbd", "todo", "test", "null", "none", "n/a", "na", "-", "--", "unknown"}
PART_WORDS = ("主体", "配件", "手柄", "锅体", "盖子", "锅盖", "把手", "煎盘", "炉体", "炉架", "壶身", "壶嘴", "杯身", "杯盖")


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
) -> dict | None:
    request_start = perf_counter()
    previous_result_skus = previous_result_skus or []
    # don't poison the intent parser with old SKUs
    # don't poison the intent parser with old SKUs
    # If there are previous SKUs and the question doesn't reference them, clear them
    if previous_result_skus and not _has_context_reference(question):
        # Question does NOT use words like "??""??""??" - it''s a fresh topic
        # Clear previous SKUs to avoid context poisoning
        previous_result_skus = []
    # Try regex parser first - it's fast and accurate for structured queries
    intent = parse_intent(question, sku=sku, previous_result_skus=previous_result_skus)
    # Only use LLM if regex parser failed or returned clarify
    if not intent or intent.intent == "clarify":
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
    if not intent:
        # Last resort: try LLM with no extra context
        llm_start = perf_counter()
        llm_intent = await _llm_parse_intent(db, question, sku=sku, previous_result_skus=[])
        customer_perf_service.log_stage("process_intent_request.llm_last_resort", llm_start, hit=bool(llm_intent), intent=llm_intent.intent if llm_intent else None)
        if llm_intent:
            intent = _sanitize_intent(llm_intent)
    if not intent:
        return None

    # Final safety: if intent is still clarify but regex has concrete search params, override
    if intent.intent == "clarify":
        regex_final = parse_intent(question, sku=sku, previous_result_skus=[])
        if regex_final and regex_final.intent in ("query_products", "recommend_products") and (regex_final.filters or regex_final.term or regex_final.semantic_query):
            intent = regex_final
    if intent.intent == "clarify":
        return _clarify_result(intent)
    if intent.intent == "product_detail":
        return await _product_detail_result(db, intent)
    if intent.intent == "compare_products":
        return await _compare_result(db, intent, question)
    if intent.intent == "recommend_products":
        return await _recommend_result(db, user_id, intent)
    if intent.intent == "propose_delete":
        return await _propose_delete_result(db, user_id, intent)
    if intent.intent == "propose_update":
        return await _propose_update_result(db, user_id, intent)
    if intent.intent == "query_products" and intent.target_skus and intent.requested_fields and len(intent.target_skus) == 1:
        return await _product_detail_result(db, intent)
    if intent.intent == "query_products":
        return await _query_products_result(db, user_id, intent, original_question=question)
    return None



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
    # If product_detail but no target_skus, convert to query_products to find by name first
    if intent.intent == "product_detail" and not intent.target_skus and intent.term:
        intent.intent = "query_products"
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
        if previous_result_skus:
            target_skus = previous_result_skus
            source_context = "previous_results"
        else:
            return CustomerIntent(
                intent="clarify",
                clarification_question="你提到的“这些”目前没有可引用的上一轮结果。请先查一批产品，或者直接告诉我要处理的 SKU。",
            )

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

    if previous_result_skus and not target_skus and negative_filters and any(word in text for word in FOLLOWUP_NARROW_WORDS):
        target_skus = previous_result_skus
        source_context = "previous_results"

    is_compare = _is_compare_question(text)
    if len(target_skus) > 1 and is_compare:
        return CustomerIntent(
            intent="compare_products",
            target_skus=target_skus,
            requested_fields=requested_fields,
            source_context=source_context,
            is_single_field_sufficient=False,
        )

    if any(word in text for word in RECOMMEND_WORDS):
        if not target_skus and not filters and not semantic_query:
            return CustomerIntent(
                intent="clarify",
                clarification_question="我可以帮你推荐，但需要先告诉我范围，比如 SKU、类目，或描述使用场景。",
            )
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

    if target_skus and filters:
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
            source_context=source_context,
            is_single_field_sufficient=_is_single_field_sufficient(text, requested_fields, target_skus),
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
    return any(word in text for word in COMPARE_WORDS + ("一样", "不一样", "相同", "不同"))


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

    if intent.target_skus:
        rows = _rows_for_target_skus(db, intent.target_skus)
        rows = _filter_rows(rows, filters=intent.filters, negative_filters=intent.negative_filters, term=intent.term)
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
    anomalies = [] if intent.requested_fields else _detect_row_anomalies(rows, intent)
    warnings.extend(item["message"] for item in anomalies[:3])

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
    if search_question_text:
        try:
            kb_results = await knowledge_service.semantic_retrieve(db, search_question_text, limit=5)
        except Exception:
            try:
                kb_results = knowledge_service.keyword_retrieve(db, search_question_text, limit=5)
            except Exception:
                pass

    followups = _suggest_followups(rows, intent)

    # When user asked for specific fields and we found 1 product: upgrade to detail answer
    answer_type = None
    used_filter_finalizer = False
    if _has_specs_filter(intent) and rows and intent.intent == "query_products" and not (intent.requested_fields and len(rows) == 1):
        answer = await _compose_filter_answer(db, original_question or search_question_text, rows, intent)
        answer_type = "product_query"
        used_filter_finalizer = True
    elif intent.requested_fields and len(rows) == 1 and intent.intent == "query_products":
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
                sources=[{"type": "product_search", "label": "意图解析查询", "query": query, "count": len(rows)}],
                results=rows,
                steps=_steps(intent, [{"type": tool_name, "label": "执行产品查询", "detail": f"命中 {len(rows)} 条", "ok": True}]),
                confidence=_confidence_for_rows(rows, intent, warnings),
                warnings=warnings,
                anomalies=anomalies,
                suggested_followups=followups,
                answer_type=answer_type,
            )
            response["skip_polish"] = True
            return response
        if not getattr(intent, "is_single_field_sufficient", True):
            answer = await _llm_compose_answer(db, original_question or search_question_text, rows, intent, qa_results, kb_results, warnings, followups)
            answer_type = "product_detail"
        else:
            field_paths = [_resolve_query_field(f) for f in intent.requested_fields]
            field_paths = [p for p in field_paths if p]
            detail_rows = [{"sku": sku, "product_name_cn": detail.get("product_name_cn"), "product_name_en": detail.get("product_name_en"), "field_values": {}}]
            for fp in field_paths:
                label = _field_label(fp)
                value = _value_from_detail(detail, fp)
                text = _format_field_value(value, fp) if value not in (None, "") else "暂无"
                detail_rows[0]["field_values"][label] = text
                anomaly = _field_anomaly_for_value(sku, label, text)
                if anomaly:
                    anomalies.append(anomaly)
            answer = _compose_detail_answer(detail_rows, field_paths, warnings, anomalies, [])
            answer_type = "product_detail"
    else:
        answer = await _llm_compose_answer(db, search_question_text, rows, intent, qa_results, kb_results, warnings, followups)

    response = _build_response(
        intent=intent,
        answer=answer,
        sku=rows[0]["sku"] if len(rows) == 1 else None,
        sources=[{"type": "product_search", "label": "意图解析查询", "query": query, "count": len(rows)}],
        results=rows,
        steps=_steps(intent, [{"type": tool_name, "label": "执行产品查询", "detail": f"命中 {len(rows)} 条", "ok": True}]),
        confidence=_confidence_for_rows(rows, intent, warnings),
        warnings=warnings,
        anomalies=anomalies,
        suggested_followups=followups,
        answer_type=answer_type,
    )
    if used_filter_finalizer:
        response["skip_polish"] = True
    return response


async def _product_detail_result(db: Session, intent: CustomerIntent) -> dict:
    intent.target_skus = [_resolve_existing_sku(db, sku) for sku in intent.target_skus]
    rows = []
    field_paths = [_resolve_query_field(field) for field in intent.requested_fields]
    field_paths = [path for path in field_paths if path]
    anomalies: list[dict[str, Any]] = []
    details: list[dict[str, Any]] = []

    for sku in intent.target_skus:
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
            value = _value_from_detail(detail, field_path)
            text = _format_field_value(value, field_path) if value not in (None, "") else "暂无"
            row["field_values"][label] = text
            anomaly = _field_anomaly_for_value(sku, label, text)
            if anomaly:
                anomalies.append(anomaly)
        rows.append(row)

    # Search QA knowledge base and vector DB for richer answers
    qa_results: list[dict] = []
    kb_results: list[dict] = []
    search_question = intent.semantic_query or intent.term or ""
    for sku in intent.target_skus:
        qa_matches = _search_product_qa(db, sku, search_question)
        qa_results.extend(qa_matches)
    if search_question:
        try:
            kb_results = await knowledge_service.semantic_retrieve(db, search_question, limit=5)
        except Exception:
            try:
                kb_results = knowledge_service.keyword_retrieve(db, search_question, limit=5)
            except Exception:
                pass

    warnings = [item["message"] for item in anomalies[:3]]
    followups = _suggest_detail_followups(intent)
    if field_paths:
        answer = _compose_detail_answer(rows, field_paths, warnings, anomalies, followups)
    else:
        answer = _compose_unknown_attribute_answer(details, intent.requested_fields, followups)
    return _build_response(
        intent=intent,
        answer=answer,
        sku=intent.target_skus[0] if len(intent.target_skus) == 1 else None,
        sources=[{"type": "product", "label": "按意图读取产品字段", "count": len(rows)}],
        results=rows,
        steps=_steps(intent, [{"type": "product_detail", "label": "读取产品字段", "detail": f"读取 {len(rows)} 个 SKU", "ok": True}]),
        confidence="high" if rows else "low",
        warnings=warnings,
        anomalies=anomalies,
        suggested_followups=followups,
    )


async def _compare_result(db: Session, intent: CustomerIntent, original_question: str = "") -> dict:
    intent.target_skus = [_resolve_existing_sku(db, sku) for sku in intent.target_skus]
    fields = intent.requested_fields or ["商品英文名称", "容量", "材质", "颜色", "卖点"]
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
                    "product_name_cn": "",
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
    response["skip_polish"] = True
    return response


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


async def _recommend_result(db: Session, user_id: str, intent: CustomerIntent) -> dict:
    cache_key = customer_cache_service.make_key(
        "recommend_result",
        id(db),
        intent.recommendation_query or intent.semantic_query or intent.term,
        intent.filters or {},
        intent.negative_filters or {},
        intent.target_skus or [],
    )
    cached = customer_cache_service.recommendation_candidate_cache.get(cache_key)
    if cached is not None:
        return cached

    base_result = await _query_products_result(db, user_id, CustomerIntent(
        intent="query_products",
        filters=intent.filters,
        negative_filters=intent.negative_filters,
        semantic_query=intent.semantic_query,
        target_skus=intent.target_skus,
        requested_fields=intent.requested_fields,
        special_filter=intent.special_filter,
        exact_value=intent.exact_value,
        term=intent.term,
        source_context=intent.source_context,
    ))
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
        fallback_base = await _query_products_result(db, user_id, fallback_intent, original_question=intent.recommendation_query or intent.semantic_query or intent.term)
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

    ranked = await _rank_rows_for_recommendation_llm(db, rows, intent.recommendation_query or intent.semantic_query or intent.term)
    best = ranked[0]
    anomalies = _detect_row_anomalies([item["row"] for item in ranked[:3]], intent)
    warnings = [item["message"] for item in anomalies[:2]]
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
    answer = await _compose_recommendation_answer(
        db,
        intent.recommendation_query or intent.semantic_query or intent.term,
        ranked,
        intent,
        warnings,
        anomalies,
        followups,
        result_rows,
    )

    return _build_response(
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
    )
    customer_cache_service.recommendation_candidate_cache.set(cache_key, response)
    return response


async def _compose_recommendation_answer(
    db: Session,
    question: str,
    ranked: list[dict],
    intent: CustomerIntent,
    warnings: list[str],
    anomalies: list[dict[str, Any]],
    followups: list[str],
    result_rows: list[dict[str, Any]] | None = None,
) -> str:
    """Compose a recommendation answer from ranked products."""
    result_rows = result_rows or []
    if result_rows:
        product_data_list = _recommendation_product_data(db, result_rows)
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
            return answer
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
    
    best = ranked[0]
    best_row = best["row"]
    sku = best_row.get("sku", "")
    name = best_row.get("product_name_cn") or best_row.get("product_name_en") or sku
    matched = best.get("matched") or best.get("reasons", [])
    missing = best.get("missing_or_uncertain") or []
    score_reason = best.get("score_reason") or (f"排序分数 {best.get('score')}" if best.get("score") is not None else "")
    
    lines = [f"根据你的需求，我优先推荐 {name}（{sku}）。"]
    
    if matched:
        lines.append("匹配依据：" + "；".join(matched[:4]) + "。")
    if missing:
        lines.append("未注明或需确认：" + "；".join(missing[:3]) + "。")
    if score_reason:
        lines.append(score_reason + "。")
    
    # Show runner-ups
    if len(ranked) > 1:
        lines.append("其他候选：")
        for item in ranked[1:4]:
            r = item["row"]
            s = r.get("sku", "")
            n = r.get("product_name_cn") or r.get("product_name_en") or s
            item_matched = item.get("matched") or item.get("reasons") or []
            reason = f"：{item_matched[0]}" if item_matched else ""
            lines.append(f"- {n}（{s}）{reason}")
    
    if warnings:
        lines.append("注意：" + warnings[0])
    if followups:
        lines.append(followups[0])
    
    return "\n".join(lines)


def _recommendation_product_data(db: Session, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    product_data_list: list[dict[str, Any]] = []
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
        "先给首选推荐，再说明为什么匹配用户需求；理由必须引用具体参数、场景、人群、容量、重量、材质、卖点或recommendation_match。"
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

    field_filters = (
        (("主体材质", "材质", "材料"), "specs.body_material"),
        (("表面处理", "表面工艺", "工艺"), "specs.surface_finish"),
        (("适用热源", "热源", "燃料"), "specs.heat_source"),
        (("容量",), "specs.capacity"),
    )
    for labels, field_path in field_filters:
        label_pattern = "|".join(re.escape(label) for label in labels)
        match = re.search(rf"(?:{label_pattern})\s*(?:为|是|=|等于|包含)\s*([^，,。？?\s]+)", text, flags=re.I)
        if match:
            value = _clean_filter_value(match.group(1))
            if value and value not in {"多少", "什么", "啥", "几"}:
                filters[field_path] = value
                continue
        value = _reverse_field_filter_value(text, labels)
        if value:
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
        positive_text = _positive_category_text(text)
        cat_map = [
            ("水壶", "水壶"), ("户外水壶", "水壶"), ("水具", "水具"), ("水杯", "水具"), ("杯", "水具"),
            ("锅具", "锅具"), ("锅子", "锅具"), ("套锅", "锅具"), ("单锅", "锅具"), ("煎锅", "锅具"), ("炒锅", "锅具"), ("烤盘", "锅具"), ("锅", "锅具"),
            ("酒精炉", "炉具"), ("气炉", "炉具"), ("卡式炉", "炉具"), ("炉具", "炉具"), ("炉子", "炉具"), ("炉", "炉具"),
            ("餐具", "餐具"), ("勺", "餐具"), ("收纳包", "收纳包具"), ("包具", "收纳包具"),
        ]
        for kw, cat in cat_map:
            if any(kw and kw in str(value) for value in filters.values()):
                continue
            if kw in positive_text:
                filters["product.category"] = cat
                break

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
    }


def _filter_rows(rows: list[dict], *, filters: dict[str, Any], negative_filters: dict[str, Any], term: str) -> list[dict]:
    def _matches_any(text: str, value: Any) -> bool:
        text_lower = text.lower()
        if isinstance(value, list):
            return any(v.lower() in text_lower for v in value)
        return str(value).lower() in text_lower

    def match_field(row: dict[str, Any], field_path: str, value: Any) -> bool:
        text = str(_row_value(row, field_path) or "").lower()
        return _matches_any(text, value)

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
    return any(term in value for term in ("食品级", "认证", "安全吗", "安全性", "安全吗"))


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
    product_data_list = []
    for row in rows[:30]:
        sku = str(row.get("sku") or "").strip()
        if not sku:
            continue
        try:
            product_data_list.append(product_service.get_product_detail(db, sku))
        except Exception:
            product_data_list.append(row)
    if product_data_list:
        answer = await _finalize_filter_answer(
            db,
            question=question,
            rows=rows,
            intent=intent,
            product_data_list=product_data_list,
        )
        if answer:
            return answer
    return _compose_filter_answer_template(rows, intent)


def _compose_filter_answer_template(rows: list[dict], intent: CustomerIntent) -> str:
    filter_labels = []
    for field_path, value in (intent.filters or {}).items():
        if str(field_path).startswith("specs."):
            filter_labels.append(f"{_field_label(field_path)}为{value}")
    condition = "、".join(filter_labels) or "筛选条件"
    lines = [f"按{condition}筛选，找到 {len(rows)} 款产品："]
    for row in rows[:20]:
        sku = row.get("sku") or ""
        name = row.get("product_name_cn") or row.get("product_name_en") or sku
        facts = []
        for field_path in (intent.filters or {}):
            if str(field_path).startswith("specs."):
                key = str(field_path).split(".", 1)[1]
                value = row.get(key)
                if value not in (None, ""):
                    facts.append(f"{_field_label(field_path)}：{value}")
        if row.get("capacity"):
            facts.append(f"容量：{row.get('capacity')}")
        lines.append(f"{len(lines)}. {name}（{sku}）" + (f"，{'；'.join(facts)}" if facts else ""))
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
    if not cleaned:
        return ""
    patterns = (
        r"^(?P<subject>.+?)(?:的)?(?:主体|配件|手柄|锅体|盖子|锅盖|把手|煎盘|炉体|炉架|壶身|壶嘴|杯身|杯盖)?(?:是|为|用的是|用的|可以用|能用)?(?:什么|啥|哪种|哪些)?(?:材质|颜色|重量|容量|热源|燃料|功率|表面处理|认证|安全性|食品级)(?:.*)?$",
        r"^(?P<subject>.+?)(?:的(?:主要)?(?:卖点|负责人|容量|材质|颜色|重量|英文名|英文名称|类目|品质情况|信息|资料|详情|参数|场景|适用场景))(?:是|为|有|有啥|有哪些|是什么|多少|几|吗|呢|？|。|$).*$",
        r"^(?P<subject>.+?)(?:的)?(?:卖点|负责人|容量|材质|颜色|重量|英文名|英文名称|类目|品质情况|信息|资料|详情|参数|场景|适用场景)(?:是|为|有|有啥|有哪些|是什么|多少|几|吗|呢|？|。|$).*$",
    )
    for pattern in patterns:
        match = re.match(pattern, cleaned)
        if match:
            subject = match.group("subject").strip(" ，。？！；;")
            if subject and len(subject) >= 2:
                return subject
    return ""


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
    rows: list[dict],
    field_paths: list[str],
    warnings: list[str],
    anomalies: list[dict[str, Any]],
    followups: list[str],
    qa_results: list[dict] | None = None,
    kb_results: list[dict] | None = None,
) -> str:
    qa_results = qa_results or []
    kb_results = kb_results or []
    if not field_paths:
        return "我还没有识别到你想查询的具体字段，请告诉我要看容量、材质、卖点、负责人等哪类信息。"
    if not rows:
        return "没有找到对应产品。请确认 SKU 或产品名是否正确。"

    labels = [_field_label(path) for path in field_paths]
    row = rows[0]
    title = row.get("product_name_cn") or row.get("product_name_en") or ""
    sku_val = row["sku"]
    detail = "；".join(f"{key}：{value}" for key, value in row.get("field_values", {}).items())

    lines = [f"{title}（{sku_val}）的{', '.join(labels)}：{detail}。"]

    if qa_results:
        lines.append("")
        lines.append("相关 QA 资料：")
        for qa in qa_results[:2]:
            lines.append(f"Q: {qa['question']}")
            lines.append(f"A: {qa['answer']}")

    if kb_results:
        lines.append("")
        for kb in kb_results[:2]:
            content_text = kb.get("content", "")[:200]
            if content_text:
                lines.append(f"知识库：{content_text}")

    if warnings:
        lines.append(f"提示：{warnings[0]}")
    if followups:
        lines.append(followups[0])
    return "\n".join(lines)


def _compose_unknown_attribute_answer(
    details: list[dict[str, Any]],
    requested_fields: list[str],
    followups: list[str],
) -> str:
    if not details:
        return "先说结论：我还不能直接确认，因为没有找到对应产品资料。"

    field_text = "、".join(requested_fields or ["这个属性"])
    lines = [f"先说结论：产品资料里没有标注{field_text}，所以不能直接确认。"]
    lines.append("我能看到的相关依据如下：")

    for detail in details[:3]:
        sku = detail.get("sku") or ""
        name = detail.get("product_name_cn") or detail.get("product_name_en") or ""
        evidence = _unknown_attribute_evidence(detail)
        if not evidence:
            continue
        title = f"{sku} {name}".strip()
        lines.append(f"- {title}：" + "；".join(evidence[:6]))

    if len(lines) == 2:
        lines.append("- 当前资料缺少可用于判断的材质、表面处理、使用场景或使用说明。")
    if followups:
        lines.append(f"下一步建议：{followups[0]}")
    return "\n".join(lines)


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
    # Also try broader search (any QA for this product, not just term match)
    if not results:
        all_qas = db.query(ProductQa).filter(
            ProductQa.product_id == product.id
        ).order_by(ProductQa.priority.desc().nullslast(), ProductQa.updated_at.desc()).limit(limit).all()
        for qa in all_qas:
            results.append({
                "question": qa.question,
                "answer": qa.answer,
                "tags": qa.tags,
                "source_type": "product_qa",
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
    candidates = [
        ("容量", ("容量", "多少ml", "多大")),
        ("材质", ("材质", "材料")),
        ("颜色", ("颜色", "配色")),
        ("重量", ("重量", "多重")),
        ("热源", ("热源", "燃料")),
        ("功率", ("功率", "火力")),
        ("表面处理", ("表面处理", "表面工艺", "工艺")),
        ("认证", ("认证", "食品级")),
        ("卖点", ("卖点", "特色", "优势", "特点")),
        ("商品英文名称", ("英文名", "英文名称", "商品英文名称")),
        ("负责人", ("负责人",)),
        ("品质情况", ("品质", "品质情况", "坏损")),
        ("类目", ("类目", "品类")),
        ("防水", ("防水", "防泼水")),
        ("不粘", ("不粘", "不沾")),
        ("煎蛋", ("煎蛋", "煎")),
        ("适用场景", ("适合", "场景", "露营", "咖啡", "泡咖啡")),
    ]
    for label, aliases in candidates:
        if any(alias in text for alias in aliases) and label not in fields:
            fields.append(label)
    return fields


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
        "容量": "specs.capacity",
        "材质": "specs.body_material",
        "颜色": "specs.color",
        "重量": "specs.gross_weight_g",
        "热源": "specs.heat_source",
        "燃料": "specs.heat_source",
        "功率": "specs.power",
        "表面处理": "specs.surface_finish",
        "卖点": "business.top_selling_points",
    }
    return direct.get(field_label) or customer_agent_service.QUERY_FIELD_ALIASES.get(field_label) or agent_action_service.resolve_field_path(field_label)


def _field_label(field_path: str) -> str:
    spec = customer_agent_service.QUERY_FIELD_SPECS.get(field_path)
    if spec:
        return spec[2]
    field_spec = agent_action_service.FIELD_SPECS.get(field_path)
    return field_spec.label if field_spec else field_path


def _value_from_detail(detail: dict[str, Any], field_path: str) -> Any:
    section, field_name = field_path.split(".", 1)
    if section == "product":
        return detail.get(field_name)
    return (detail.get(section) or {}).get(field_name)


def _is_delete_request(text: str) -> bool:
    return any(word in text for word in ("删除", "删掉", "移除")) and any(word in text for word in ("产品", "SKU", "这些", "它们"))


def _has_context_reference(text: str) -> bool:
    return any(word in text for word in CONTEXT_WORDS)


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
    return customer_agent_service._stringify(value)


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


