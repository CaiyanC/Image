import asyncio
from typing import Any
from time import perf_counter

from sqlalchemy.orm import Session

from ..core.database import release_session_connection
from . import agent_action_service, customer_agent_service, customer_cache_service, knowledge_service, product_service
from . import customer_perf_service


TOOL_SPECS = [
    {
        "name": "search_products",
        "description": "全字段查询多条产品信息。适合 SKU、条形码、名称、品牌、系列、类目、等级、生命周期、负责人、备注、容量、重量、材质、颜色、工艺、热源、功率、卖点、目标人群、定位、价格定位、情绪价值、使用场景、竞品、标题、描述、关键词、listing 等条件。",
        "arguments": {
            "term": "搜索词，例如 SKU、条形码、负责人、锅、防滑条、露营泡咖啡、300ml、Yao",
            "filters": "可选，结构化筛选。例如 {\"负责人\":\"Yao\",\"类目\":\"锅\"} 或 {\"product.person_in_charge\":\"Yao\"}",
            "fields": "可选，要重点返回的字段名列表，例如 容量、材质、卖点",
            "limit": "可选，默认 50",
        },
    },
    {
        "name": "semantic_search_knowledge",
        "description": "语义/关键词检索产品知识库。适合露营泡咖啡、情绪价值、使用场景、模糊需求等问题。V1 使用知识库关键词兜底，后续可升级 pgvector 相似度。",
        "arguments": {"query": "用户的语义需求", "sku": "可选，限定 SKU", "limit": "可选，默认 8"},
    },
    {
        "name": "hybrid_search_products",
        "description": "融合查询产品。精确条件走产品 SQL filters，模糊语义需求走知识库/pgvector，再按 SKU 合并排序。适合“负责人Yao且适合露营泡咖啡的锅”。",
        "arguments": {
            "term": "可选，全字段关键词",
            "filters": "可选，结构化筛选，例如 {\"负责人\":\"Yao\",\"类目\":\"锅具\"}",
            "semantic_query": "可选，模糊语义需求，例如 适合露营泡咖啡",
            "fields": "可选，要重点返回的字段名列表",
            "limit": "可选，默认 50",
        },
    },
    {
        "name": "get_product_detail",
        "description": "读取一个或多个 SKU 的完整产品资料。适合单品追问、上一轮结果继续对比、推荐前补全资料。",
        "arguments": {"sku": "单个产品 SKU", "skus": "可选，多个 SKU 数组", "fields": "可选，只返回/突出指定字段，例如 条形码、尺寸、上架平台、售卖地区、关键词库"},
    },
    {
        "name": "propose_update_product_field",
        "description": "提出修改字段建议，只创建待确认动作，不直接写库。",
        "arguments": {"sku": "单个产品 SKU", "skus": "可选，多个 SKU 数组", "field": "字段中文名或字段路径", "new_value": "新值"},
    },
    {
        "name": "propose_delete_product_info",
        "description": "提出局部删除建议。V1 支持清空白名单字段。",
        "arguments": {"sku": "单个产品 SKU", "skus": "可选，多个 SKU 数组", "field": "要清空的字段中文名或字段路径"},
    },
    {
        "name": "propose_delete_product",
        "description": "提出删除整个产品建议，只创建强确认动作，不直接删除。",
        "arguments": {"sku": "产品 SKU"},
    },
]

QUERY_FIELD_ALIASES = {
    "条形码": "product.barcode",
    "barcode": "product.barcode",
    "尺寸": "specs.size_info",
    "尺寸规格": "specs.size_info",
    "规格尺寸": "specs.size_info",
    "上架平台": "channels",
    "平台": "channels",
    "哪些平台": "channels",
    "销售平台": "channels",
    "售卖平台": "channels",
    "售卖地区": "regions",
    "销售地区": "regions",
    "销售区域": "regions",
    "地区": "regions",
    "关键词库": "keywords",
    "关键词": "keywords",
}

QUERY_FIELD_LABELS = {
    "product.barcode": "条形码",
    "specs.size_info": "尺寸规格",
    "channels": "上架平台",
    "regions": "售卖地区",
    "keywords": "关键词库",
}


def list_tool_specs() -> list[dict]:
    return TOOL_SPECS


def execute_tool(db: Session, *, user_id: str, name: str, arguments: dict[str, Any]) -> dict:
    start_time = perf_counter()
    if name == "search_products":
        result = _search_products(db, arguments)
        customer_perf_service.log_stage("tool.execute", start_time, tool=name, async_call=False, ok=result.get("ok") if isinstance(result, dict) else None)
        return result
    if name == "get_product_detail":
        result = _get_product_detail(db, arguments)
        customer_perf_service.log_stage("tool.execute", start_time, tool=name, async_call=False, ok=result.get("ok") if isinstance(result, dict) else None)
        return result
    if name == "hybrid_search_products":
        result = _hybrid_search_products(db, arguments, semantic_rows=[])
        customer_perf_service.log_stage("tool.execute", start_time, tool=name, async_call=False, ok=result.get("ok") if isinstance(result, dict) else None)
        return result
    if name == "semantic_search_knowledge":
        result = _semantic_search_knowledge(db, arguments)
        customer_perf_service.log_stage("tool.execute", start_time, tool=name, async_call=False, ok=result.get("ok") if isinstance(result, dict) else None)
        return result
    if name == "propose_update_product_field":
        result = _propose_update_product_field(db, user_id, arguments)
        customer_perf_service.log_stage("tool.execute", start_time, tool=name, async_call=False, ok=result.get("ok") if isinstance(result, dict) else None)
        return result
    if name == "propose_delete_product_info":
        result = _propose_delete_product_info(db, user_id, arguments)
        customer_perf_service.log_stage("tool.execute", start_time, tool=name, async_call=False, ok=result.get("ok") if isinstance(result, dict) else None)
        return result
    if name == "propose_delete_product":
        result = _propose_delete_product(db, user_id, arguments)
        customer_perf_service.log_stage("tool.execute", start_time, tool=name, async_call=False, ok=result.get("ok") if isinstance(result, dict) else None)
        return result
    return {"ok": False, "error": f"未知工具：{name}"}


async def execute_tool_async(db: Session, *, user_id: str, name: str, arguments: dict[str, Any]) -> dict:
    start_time = perf_counter()
    try:
        if name == "semantic_search_knowledge":
            result = await _semantic_search_knowledge_async(db, arguments)
        elif name == "hybrid_search_products":
            semantic_query = str(arguments.get("semantic_query") or "").strip()
            semantic_task = None
            if semantic_query:
                semantic_task = asyncio.create_task(
                    _semantic_rows_for_hybrid_search(db, arguments, semantic_query)
                )
                await asyncio.sleep(0)
            sql_rows, sql_filter_ms = _hybrid_search_sql_rows(db, arguments)
            semantic_rows = await semantic_task if semantic_task else []
            result = _hybrid_search_products(
                db,
                arguments,
                semantic_rows=semantic_rows,
                sql_rows=sql_rows,
                sql_filter_ms=sql_filter_ms,
            )
        else:
            result = execute_tool(db, user_id=user_id, name=name, arguments=arguments)
        customer_perf_service.log_stage("tool.execute_async", start_time, tool=name, async_call=True, ok=result.get("ok") if isinstance(result, dict) else None)
        return result
    finally:
        release_session_connection(db)


def _search_products(db: Session, arguments: dict[str, Any]) -> dict:
    term = str(arguments.get("term") or "").strip()
    limit = int(arguments.get("limit") or 50)
    filters = arguments.get("filters") or {}
    if not isinstance(filters, dict):
        filters = {}
    fields = arguments.get("fields") or []
    if isinstance(fields, str):
        fields = [fields]
    rows = customer_agent_service.search_products(db, term, limit=limit, filters=filters)
    enriched_rows = [_enrich_fields(db, row, fields) for row in rows]
    return {"ok": True, "tool": "search_products", "query": term, "filters": filters, "count": len(enriched_rows), "results": enriched_rows}


def _semantic_search_knowledge(db: Session, arguments: dict[str, Any]) -> dict:
    query = str(arguments.get("query") or "").strip()
    sku = str(arguments.get("sku") or "").strip().upper() or None
    limit = int(arguments.get("limit") or 8)
    rows = knowledge_service.keyword_retrieve(db, query, sku=sku, limit=limit)
    rows = _enrich_semantic_rows(db, rows)
    return {"ok": True, "tool": "semantic_search_knowledge", "query": query, "sku": sku, "mode": "keyword", "count": len(rows), "results": rows}


async def _semantic_search_knowledge_async(db: Session, arguments: dict[str, Any]) -> dict:
    query = str(arguments.get("query") or "").strip()
    sku = str(arguments.get("sku") or "").strip().upper() or None
    limit = int(arguments.get("limit") or 8)
    rows = await knowledge_service.semantic_retrieve(db, query, sku=sku, limit=limit)
    rows = _enrich_semantic_rows(db, rows)
    return {"ok": True, "tool": "semantic_search_knowledge", "query": query, "sku": sku, "mode": "semantic", "count": len(rows), "results": rows}


async def _semantic_rows_for_hybrid_search(db: Session, arguments: dict[str, Any], semantic_query: str) -> list[dict]:
    semantic_start = perf_counter()
    semantic_rows = await knowledge_service.semantic_retrieve(
        db,
        semantic_query,
        sku=str(arguments.get("sku") or "").strip().upper() or None,
        limit=int(arguments.get("limit") or 50),
    )
    customer_perf_service.log_stage(
        "hybrid_search_products.semantic_retrieve",
        semantic_start,
        semantic_query=semantic_query,
        semantic_rows=len(semantic_rows or []),
    )
    return semantic_rows


def _hybrid_search_sql_rows(db: Session, arguments: dict[str, Any]) -> tuple[list[dict], float]:
    term = str(arguments.get("term") or "").strip()
    limit = min(max(int(arguments.get("limit") or 50), 1), 10)
    filters = arguments.get("filters") or {}
    if not isinstance(filters, dict):
        filters = {}
    sql_start = perf_counter()
    rows = customer_agent_service.search_products(db, term, limit=limit, filters=filters)
    return rows, customer_perf_service.perf_ms(sql_start)


def _hybrid_search_products(
    db: Session,
    arguments: dict[str, Any],
    semantic_rows: list[dict],
    sql_rows: list[dict] | None = None,
    sql_filter_ms: float | None = None,
) -> dict:
    term = str(arguments.get("term") or "").strip()
    semantic_query = str(arguments.get("semantic_query") or "").strip()
    limit = min(max(int(arguments.get("limit") or 50), 1), 10)
    filters = arguments.get("filters") or {}
    if not isinstance(filters, dict):
        filters = {}
    fields = arguments.get("fields") or []
    if isinstance(fields, str):
        fields = [fields]

    cache_key = customer_cache_service.make_key("hybrid_search_products", id(db), term, semantic_query, filters, limit, fields)
    cached = customer_cache_service.recommendation_candidate_cache.get(cache_key)
    if cached is not None:
        return cached

    sql_start = perf_counter()
    if sql_rows is None:
        sql_rows = customer_agent_service.search_products(db, term, limit=limit, filters=filters)
        sql_filter_ms = customer_perf_service.perf_ms(sql_start)
    elif sql_filter_ms is None:
        sql_filter_ms = customer_perf_service.perf_ms(sql_start)

    semantic_ms = 0.0
    semantic_rows = semantic_rows or []

    detail_start = perf_counter()
    merged: dict[str, dict] = {}
    for index, row in enumerate(sql_rows):
        enriched = _enrich_fields(db, row, fields if index < 3 else [])
        enriched["hybrid_score"] = 1000 - index
        enriched["matched_by"] = enriched.get("matched_by") or "SQL精确查询"
        merged[enriched["sku"]] = enriched

    for index, item in enumerate(semantic_rows):
        sku = item.get("sku")
        if not sku:
            continue
        if sku in merged:
            merged[sku]["hybrid_score"] = merged[sku].get("hybrid_score", 0) + 500 - index
            merged[sku]["semantic_match"] = item.get("content")
            continue
        sku_filters = {"sku": sku, **filters}
        rows = customer_agent_service.search_products(db, "", limit=1, filters=sku_filters)
        if rows:
            enriched = _enrich_fields(db, rows[0], fields if len(merged) < 3 else [])
            enriched["hybrid_score"] = 500 - index
            enriched["matched_by"] = "语义知识库"
            enriched["semantic_match"] = item.get("content")
            merged[sku] = enriched

    merge_start = perf_counter()
    rows = sorted(merged.values(), key=lambda row: row.get("hybrid_score", 0), reverse=True)[:limit]
    for row in rows:
        row.pop("hybrid_score", None)
    merge_rank_ms = customer_perf_service.perf_ms(merge_start)
    get_detail_ms = max(customer_perf_service.perf_ms(detail_start) - merge_rank_ms, 0.0)

    result = {
        "ok": True,
        "tool": "hybrid_search_products",
        "query": term or semantic_query,
        "filters": filters,
        "semantic_query": semantic_query,
        "count": len(rows),
        "results": rows,
    }
    customer_perf_service.log_stage(
        "hybrid_search_products.breakdown",
        sql_start,
        sql_filter_ms=round(sql_filter_ms, 2),
        embedding_query_ms=round(semantic_ms, 2),
        vector_search_ms=round(semantic_ms, 2),
        merge_rank_ms=round(merge_rank_ms, 2),
        get_detail_ms=round(get_detail_ms, 2),
        candidates_count=len(rows),
        prompt_chars=sum(len(str(item)) for item in rows[:10]),
    )
    customer_cache_service.recommendation_candidate_cache.set(cache_key, result)
    return result


def _get_product_detail(db: Session, arguments: dict[str, Any]) -> dict:
    skus = _extract_argument_skus(arguments)
    fields = _normalize_fields(arguments.get("fields") or [])
    if not skus:
        return {"ok": False, "tool": "get_product_detail", "error": "缺少 SKU"}
    details = []
    errors = []
    for sku in skus[:20]:
        try:
            detail = product_service.get_product_detail(db, sku)
            detail = _attach_field_values(detail, fields)
            details.append(detail)
        except Exception as exc:
            errors.append({"sku": sku, "error": str(exc)})
    if not details:
        return {"ok": False, "tool": "get_product_detail", "error": "没有读取到产品详情", "errors": errors}
    if len(details) == 1:
        return {"ok": True, "tool": "get_product_detail", "sku": details[0].get("sku"), "detail": details[0], "errors": errors}
    return {"ok": True, "tool": "get_product_detail", "skus": [item.get("sku") for item in details], "count": len(details), "details": details, "errors": errors}


def _propose_update_product_field(db: Session, user_id: str, arguments: dict[str, Any]) -> dict:
    skus = _extract_argument_skus(arguments)
    field_path = _resolve_field(arguments.get("field"))
    if not skus or not field_path:
        return {"ok": False, "error": "缺少 SKU 或字段不在白名单"}
    actions = [
        agent_action_service.create_update_field_action(
            db,
            created_by=user_id,
            sku=sku,
            field_path=field_path,
            new_value=arguments.get("new_value"),
        )
        for sku in skus
    ]
    return {"ok": True, "tool": "propose_update_product_field", "actions": [agent_action_service.serialize_action(action) for action in actions]}


def _propose_delete_product_info(db: Session, user_id: str, arguments: dict[str, Any]) -> dict:
    skus = _extract_argument_skus(arguments)
    field_path = _resolve_field(arguments.get("field"))
    if not skus or not field_path:
        return {"ok": False, "error": "缺少 SKU 或字段不在白名单"}
    actions = [
        agent_action_service.create_clear_field_action(
            db,
            created_by=user_id,
            sku=sku,
            field_path=field_path,
        )
        for sku in skus
    ]
    return {"ok": True, "tool": "propose_delete_product_info", "actions": [agent_action_service.serialize_action(action) for action in actions]}


def _propose_delete_product(db: Session, user_id: str, arguments: dict[str, Any]) -> dict:
    sku = str(arguments.get("sku") or "").strip().upper()
    if not sku:
        return {"ok": False, "error": "缺少 SKU"}
    action = agent_action_service.create_delete_product_action(db, created_by=user_id, sku=sku)
    return {"ok": True, "tool": "propose_delete_product", "action": agent_action_service.serialize_action(action)}


def _resolve_field(value: Any) -> str | None:
    text = str(value or "").strip()
    if text in agent_action_service.FIELD_SPECS:
        return text
    return agent_action_service.resolve_field_path(text)


def _extract_argument_skus(arguments: dict[str, Any]) -> list[str]:
    raw = arguments.get("skus")
    if isinstance(raw, str):
        items = [raw]
    elif isinstance(raw, list):
        items = raw
    else:
        items = [arguments.get("sku")]
    seen = []
    for item in items:
        sku = str(item or "").strip().upper()
        if sku and sku not in seen:
            seen.append(sku)
    return seen


def _enrich_fields(db: Session, row: dict, fields: list[str]) -> dict:
    if not fields:
        return row
    detail = product_service.get_product_detail(db, row["sku"])
    enriched = dict(row)
    field_values = {}
    for field in fields:
        field_path = resolve_query_field_path(field)
        if not field_path:
            continue
        value = _value_from_detail(detail, field_path)
        label = _label_for_query_field(field_path)
        field_values[label] = customer_agent_service._stringify(value) if value not in (None, "") else "暂无"
    enriched["field_values"] = field_values
    return enriched


def query_fields_from_text(text: str) -> list[str]:
    found = []
    raw = str(text or "")
    for label, path in QUERY_FIELD_ALIASES.items():
        if label and label in raw and path not in found:
            found.append(path)
    for label, path in agent_action_service.FIELD_ALIASES.items():
        if label and label in raw and path not in found:
            found.append(path)
    return found


def resolve_query_field_path(value: Any) -> str | None:
    text = str(value or "").strip()
    if not text:
        return None
    if text in QUERY_FIELD_LABELS:
        return text
    if text in agent_action_service.FIELD_SPECS:
        return text
    if text in QUERY_FIELD_ALIASES:
        return QUERY_FIELD_ALIASES[text]
    return agent_action_service.resolve_field_path(text)


def _normalize_fields(value: Any) -> list[str]:
    if isinstance(value, str):
        raw_fields = [value]
    elif isinstance(value, list):
        raw_fields = value
    else:
        raw_fields = []
    fields = []
    for item in raw_fields:
        field_path = resolve_query_field_path(item)
        if field_path and field_path not in fields:
            fields.append(field_path)
    return fields


def _attach_field_values(detail: dict, fields: list[str]) -> dict:
    if not fields:
        return detail
    enriched = dict(detail)
    field_values = {}
    for field_path in fields:
        value = _value_from_detail(detail, field_path)
        field_values[_label_for_query_field(field_path)] = customer_agent_service._stringify(value) if value not in (None, "") else "暂无"
    enriched["field_values"] = field_values
    return enriched


def _label_for_query_field(field_path: str) -> str:
    if field_path in agent_action_service.FIELD_SPECS:
        return agent_action_service.FIELD_SPECS[field_path].label
    return QUERY_FIELD_LABELS.get(field_path, field_path)


def _value_from_detail(detail: dict, field_path: str) -> Any:
    if field_path == "channels":
        return [item.get("channel_name") or item.get("channel_code") for item in detail.get("channels") or []]
    if field_path == "regions":
        return [item.get("region_name") or item.get("region_code") for item in detail.get("regions") or []]
    if field_path == "keywords":
        keywords = [item.get("keyword") for item in detail.get("keywords") or [] if item.get("keyword")]
        content_keywords = (detail.get("content") or {}).get("search_keywords")
        if content_keywords not in (None, "", []):
            keywords.append(content_keywords)
        return keywords
    if "." not in field_path:
        return detail.get(field_path)
    section, key = field_path.split(".", 1)
    return detail.get(key) if section == "product" else (detail.get(section) or {}).get(key)


def _enrich_semantic_rows(db: Session, rows: list[dict]) -> list[dict]:
    enriched_rows = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        sku = str(row.get("sku") or "").strip().upper()
        if not sku:
            enriched_rows.append(row)
            continue
        try:
            detail = product_service.get_product_detail(db, sku)
        except Exception:
            continue
        specs = detail.get("specs") or {}
        business = detail.get("business") or {}
        enriched = {
            **row,
            "sku": sku,
            "product_name_cn": detail.get("product_name_cn"),
            "product_name_en": detail.get("product_name_en"),
            "category": detail.get("category"),
            "sub_category": detail.get("sub_category"),
            "capacity": _safe_stringify(specs.get("capacity")),
            "body_material": _safe_stringify(specs.get("body_material")),
            "features": _safe_stringify(business.get("top_selling_points")),
            "usage_scenarios": _safe_stringify(business.get("usage_scenarios")),
            "target_audience": _safe_stringify(business.get("target_audience")),
            "positioning": _safe_stringify(business.get("positioning")),
            "price_positioning": _safe_stringify(business.get("price_positioning")),
            "emotional_value": _safe_stringify(business.get("emotional_value")),
            "matched_by": row.get("matched_by") or "语义知识库",
            "semantic_match": row.get("content"),
        }
        enriched_rows.append(enriched)
    return enriched_rows


def _safe_stringify(value: Any) -> str:
    if value in (None, "", []):
        return ""
    return customer_agent_service._stringify(value)
