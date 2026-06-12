import json
import re
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy.orm import Session

from ..models.product import Product
from ..models.product_business import ProductBusiness
from ..models.product_content import ProductContent
from ..models.product_qa import ProductQa
from ..models.product_specs import ProductSpecs
from . import agent_action_service, customer_agent_service, customer_agent_tool_service, dmxapi_service, knowledge_service, product_service


CONTEXT_WORDS = ("他", "它", "这个", "这款", "该产品", "这些", "那些", "刚才那些", "上面这些", "刚才的", "上一轮", "这一批", "这批", "这几个", "那几个")
QUESTION_WORDS = ("哪些", "有哪些", "多少", "分别", "列出", "查询", "找", "是什么")
COMPARE_WORDS = ("对比", "比较", "区别", "差异", "分别")
RECOMMEND_WORDS = ("推荐", "更适合", "最适合", "最合适", "合适", "哪个好", "哪款更好", "优先", "比较轻", "比较小", "最轻", "最小", "带什么", "带哪个", "选哪个", "买哪个")
FOLLOWUP_NARROW_WORDS = ("排除", "不要", "去掉", "剔除", "排掉")
PLACEHOLDER_WORDS = {"tbd", "todo", "test", "null", "none", "n/a", "na", "-", "--", "unknown"}


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
        }


async def process_intent_request(
    db: Session,
    *,
    user_id: str,
    question: str,
    sku: str | None = None,
    previous_result_skus: list[str] | None = None,
) -> dict | None:
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
        llm_intent = await _llm_parse_intent(db, question, sku=sku, previous_result_skus=previous_result_skus)
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
        llm_intent = await _llm_parse_intent(db, question, sku=sku, previous_result_skus=[])
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
        return _compare_result(db, intent)
    if intent.intent == "recommend_products":
        return await _recommend_result(db, user_id, intent)
    if intent.intent == "propose_delete":
        return await _propose_delete_result(db, user_id, intent)
    if intent.intent == "propose_update":
        return await _propose_update_result(db, user_id, intent)
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
    text = re.sub(r"\s+", " ", (question or "").strip())
    if not text:
        return None

    sys_prompt = _build_intent_llm_prompt(sku, previous_result_skus)
    try:
        content = await dmxapi_service.chat_completion(
            db,
            messages=[
                {"role": "system", "content": sys_prompt},
                {"role": "user", "content": text},
            ],
            temperature=0,
            max_tokens=600,
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
- When user asks "X???/??/?????" or "X???/??/??/??????" where X is a product name: use intent=query_products with term=X and requested_fields (the system will auto-format as a detail answer for few results).
- When user just mentions a product name without asking for specific fields (e.g., "????"): use intent=query_products with term=product_name.
- Only use product_detail when you have an exact SKU code (e.g., CW-C93) AND the question is about reading its fields.
- "??/??/???" + has prev SKUs -> target_skus=prev SKUs, source_context=previous_results
- "??/??" + no prev -> intent=clarify

Available filters (field path):
?负责人/person_in_charge -> product.person_in_charge
类目/品类/分类/category -> product.category
?品牌/brand -> product.brand
系列/series -> product.series
?生命周期/状态/lifecycle_status -> product.lifecycle_status
品质/品质情况/坏损/quality_note -> product.quality_note
???/????/product_name_en -> product.product_name_en
容量/capacity -> specs.capacity
材质/材料/body_material -> specs.body_material
颜色/色系/color -> specs.color
重量/毛重/gross_weight_g -> specs.gross_weight_g
热源/heat_source -> specs.heat_source
功率/power -> specs.power
卖点/top_selling_points -> business.top_selling_points
场景/usage_scenarios -> business.usage_scenarios
?产品名/名称/product_name_cn -> product.product_name_cn

Special filters (special_filter):
- ??????? -> english_name_numeric
- ??????? -> english_name_contains_digit
- ????????X -> english_name_exact, exact_value=X

semantic_query: fuzzy scene needs like "????""???"
requested_fields: requested field Chinese names, e.g. ["??","??"]
term: keyword search term

Output ONLY this JSON:
{{"intent":"","filters":{{}},"negative_filters":{{}},"semantic_query":"","target_skus":[],"requested_fields":[],"clarification_question":"","special_filter":"","exact_value":"","term":"","recommendation_query":"","source_context":"question"}}"""


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
        if not any(w in intent.clarification_question for w in ("?", "?", "??", "??")):
            intent.intent = "clarify"
            intent.clarification_question = "?????????????????????SKU????"
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

    if len(target_skus) > 1 and any(word in text for word in COMPARE_WORDS):
        return CustomerIntent(
            intent="compare_products",
            target_skus=target_skus,
            requested_fields=requested_fields,
            source_context=source_context,
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
        )

    if target_skus and requested_fields:
        return CustomerIntent(
            intent="product_detail",
            target_skus=target_skus,
            requested_fields=requested_fields,
            source_context=source_context,
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
        )

    return None


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

    anomalies = _detect_row_anomalies(rows, intent)
    warnings.extend(item["message"] for item in anomalies[:3])

    # Search QA knowledge base for matching Q&A pairs
    qa_results: list[dict] = []
    kb_results: list[dict] = []
    # Use the full original question for QA/knowledge search, not just extracted term
    # This ensures questions like "?????????" match QA entries about fuel/alcohol
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
    if intent.requested_fields and len(rows) == 1 and intent.intent == "query_products":
        sku = rows[0].get("sku", "")
        detail = product_service.get_product_detail(db, sku)
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
        answer = await _llm_compose_answer(db, search_question_text, rows, intent, qa_results, kb_results, warnings, followups)
        answer_type = "product_detail"
    else:
        answer = await _llm_compose_answer(db, search_question_text, rows, intent, qa_results, kb_results, warnings, followups)

    return _build_response(
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


async def _product_detail_result(db: Session, intent: CustomerIntent) -> dict:
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


def _compare_result(db: Session, intent: CustomerIntent) -> dict:
    fields = intent.requested_fields or ["商品英文名称", "容量", "材质", "颜色", "卖点"]
    comparisons = []
    anomalies: list[dict[str, Any]] = []

    for field in fields:
        field_path = _resolve_query_field(field)
        if not field_path:
            continue
        label = _field_label(field_path)
        values = []
        for sku in intent.target_skus:
            detail = product_service.get_product_detail(db, sku)
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
    answer = _compose_compare_answer(intent.target_skus, comparisons, warnings, anomalies, followups)
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

    return _build_response(
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


async def _recommend_result(db: Session, user_id: str, intent: CustomerIntent) -> dict:
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
    answer = _compose_recommendation_answer(ranked, intent, warnings, anomalies, followups)

    return _build_response(
        intent=intent,
        answer=answer,
        sku=best["row"].get("sku"),
        sources=base_result.get("sources") or [{"type": "product_search", "label": "推荐候选范围", "count": len(rows)}],
        results=[item["row"] for item in ranked[:5]],
        steps=_steps(intent, [{"type": "recommend_products", "label": "生成推荐结论", "detail": f"候选 {len(rows)} 个，优先推荐 {best['row'].get('sku')}", "ok": True}]),
        confidence="medium" if warnings else "high",
        warnings=warnings,
        anomalies=anomalies,
        suggested_followups=followups,
    )


def _compose_recommendation_answer(
    ranked: list[dict],
    intent: CustomerIntent,
    warnings: list[str],
    anomalies: list[dict[str, Any]],
    followups: list[str],
) -> str:
    """Compose a recommendation answer from ranked products."""
    if not ranked:
        return "目前没有找到合适的产品推荐，你可以换个场景或条件试试。"
    
    best = ranked[0]
    best_row = best["row"]
    sku = best_row.get("sku", "")
    name = best_row.get("product_name_cn") or best_row.get("product_name_en") or sku
    reasons = best.get("reasons", [])
    
    lines = [f"根据你的需求，我优先推荐 **{name}**（{sku}）。"]
    
    if reasons:
        lines.append("推荐理由：" + "；".join(reasons[:3]) + "。")
    
    # Show runner-ups
    if len(ranked) > 1:
        lines.append("其他候选：")
        for item in ranked[1:4]:
            r = item["row"]
            s = r.get("sku", "")
            n = r.get("product_name_cn") or r.get("product_name_en") or s
            lines.append(f"- {n}（{s}）")
    
    if warnings:
        lines.append("注意：" + warnings[0])
    if followups:
        lines.append(followups[0])
    
    return "\n".join(lines)

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
        cat_map = {"锅": "锅具", "锅子": "锅具", "套锅": "锅具", "煎锅": "锅具", "炒锅": "锅具",
                   "炉": "炉具", "炉子": "炉具", "酒精炉": "炉具", "气炉": "炉具", "卡式炉": "炉具",
                   "杯": "杯具", "壶": "壶具", "碗": "碗具", "盘": "盘具"}
        for kw, cat in cat_map.items():
            if kw in text:
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
        detail = product_service.get_product_detail(db, sku)
        rows.append(_detail_to_result_row(detail, matched_by="上下文结果"))
    return rows


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
        return "?????????????????????????????"
    if not rows:
        return "??????????????? SKU?????????"

    labels = [_field_label(path) for path in field_paths]
    row = rows[0]
    title = row.get("product_name_cn") or row.get("product_name_en") or ""
    sku_val = row["sku"]
    detail = "?".join(f"{key}?{value}" for key, value in row.get("field_values", {}).items())

    lines = [f"{title}?{sku_val}??{', '.join(labels)}?{detail}?"]

    if qa_results:
        lines.append("")
        lines.append("??QA?????????")
        for qa in qa_results[:2]:
            lines.append(f"Q: {qa['question']}")
            lines.append(f"A: {qa['answer']}")

    if kb_results:
        lines.append("")
        for kb in kb_results[:2]:
            content_text = kb.get("content", "")[:200]
            if content_text:
                lines.append(f"???{content_text}")

    if warnings:
        lines.append(f"????{warnings[0]}?")
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
    terms = [w.strip() for w in re.split(r"[?,????!\s]+", question) if len(w.strip()) >= 2]
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
        return f"?????????????????????"

    # Build context for LLM
    product_info = []
    for row in rows[:5]:
        info = {
            "SKU": row.get("sku", ""),
            "??": row.get("product_name_cn") or row.get("product_name_en") or "",
            "??": row.get("brand", ""),
            "??": row.get("category", ""),
            "???": row.get("person_in_charge", ""),
            "????": row.get("lifecycle_status", ""),
        }
        # Add field values if present
        for key, value in (row.get("field_values") or {}).items():
            if value and value not in ("??", ""):
                info[key] = value
        # Add key spec fields
        for field in ["capacity", "body_material", "color", "heat_source", "power", "quality_note"]:
            val = row.get(field)
            if val:
                label = {"capacity": "??", "body_material": "??", "color": "??", "heat_source": "??", "power": "??", "quality_note": "??"}.get(field, field)
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
    system_prompt = """???????????????????????????????????

?????
1. ?????????????????????"????"?????????
2. ??QA???????????????QA?????????
3. ??????KB??????????????????
4. ?????????????????????????????
5. ????????????????????????????????
6. ???????1-2?????????????????????
7. ?????????????????????
8. ????????????????????????????????
9. ?????????????"""

    user_prompt = f"""?????{question}

??????????
{_json.dumps(product_info, ensure_ascii=False, indent=2)}

QA??????
{qa_text or "???QA"}

????????
{kb_text or "????????"}

???????
{warnings_text or "???"}

?????????????????????
{followups_text or "?"}"""

    try:
        answer = await dmxapi_service.chat_completion(
            db,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.3,
            max_tokens=800,
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
        result = await dmxapi_service.chat_completion(
            db,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": f"用户需求: {query}\n\n候选产品:\n{_json.dumps(product_list, ensure_ascii=False, indent=2)}"},
            ],
            temperature=0.1,
            max_tokens=600,
        )
        ranking_data = _parse_llm_json(result or "")
        if ranking_data and ranking_data.get("ranking"):
            ranking_map = {item["index"]: item.get("reason", "") for item in ranking_data["ranking"]}
            ranked = []
            for i, row in enumerate(rows):
                reason = ranking_map.get(i, "")
                scored = 10 - list(ranking_map.keys()).index(i) if i in ranking_map else 0
                scored += _budget_score(query, row)
                ranked.append({"row": row, "score": scored, "reasons": [reason] if reason else []})
            ranked.sort(key=lambda x: x["score"], reverse=True)
            return ranked if ranked else _fallback_rank(rows, query)
    except Exception:
        pass
    return _fallback_rank(rows, query)


def _fallback_rank(rows: list[dict], query: str) -> list[dict[str, Any]]:
    """Fallback keyword-based ranking when LLM ranking fails."""
    keywords = [item for item in re.split(r"[\s,，。/]+", query) if item]
    ranked = []
    for row in rows:
        haystack = " ".join(
            str(row.get(key) or "")
            for key in ("product_name_cn", "product_name_en", "category", "capacity", "body_material", "color", "features")
        ).lower()
        score = 0
        reasons = []
        for keyword in keywords:
            token = keyword.lower()
            if token and token in haystack:
                score += 2
                reasons.append(f'命中"{keyword}"相关信息')
        if row.get("features"):
            score += 1
            reasons.append("有可用的卖点/场景信息")
        if row.get("capacity"):
            score += 1
            reasons.append("有容量信息可供判断")
        budget_score = _budget_score(query, row)
        score += budget_score
        if budget_score > 0:
            reasons.append("价格定位更符合低预算/性价比需求")
        elif budget_score < -10:
            reasons.append("价格定位偏高，不适合低预算首选")
        ranked.append({"row": row, "score": score, "reasons": list(dict.fromkeys(reasons))})
    ranked.sort(key=lambda item: (item["score"], bool(item["row"].get("features")), bool(item["row"].get("capacity"))), reverse=True)
    return ranked


def _budget_score(query: str, row: dict) -> int:
    if not any(word in str(query or "") for word in ("预算不高", "预算低", "便宜", "实惠", "性价比", "入门", "低预算", "省钱", "不要太贵")):
        return 0
    price_text = " ".join(
        str(row.get(key) or "")
        for key in ("price_positioning", "positioning", "product_level", "features", "semantic_match")
    )
    lower = price_text.lower()
    if any(word.lower() in lower for word in ("高端", "高价", "高预算", "旗舰", "专业级", "premium")):
        return -45
    if any(word.lower() in lower for word in ("入门", "亲民", "经济", "实惠", "低价", "基础", "性价比", "常规")):
        return 25
    return -5
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


