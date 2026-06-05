from typing import Any

from sqlalchemy.orm import Session

from . import agent_action_service, customer_agent_service, knowledge_service, product_service


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
        "arguments": {"sku": "单个产品 SKU", "skus": "可选，多个 SKU 数组"},
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


def list_tool_specs() -> list[dict]:
    return TOOL_SPECS


def execute_tool(db: Session, *, user_id: str, name: str, arguments: dict[str, Any]) -> dict:
    if name == "search_products":
        return _search_products(db, arguments)
    if name == "get_product_detail":
        return _get_product_detail(db, arguments)
    if name == "hybrid_search_products":
        return _hybrid_search_products(db, arguments, semantic_rows=[])
    if name == "semantic_search_knowledge":
        return _semantic_search_knowledge(db, arguments)
    if name == "propose_update_product_field":
        return _propose_update_product_field(db, user_id, arguments)
    if name == "propose_delete_product_info":
        return _propose_delete_product_info(db, user_id, arguments)
    if name == "propose_delete_product":
        return _propose_delete_product(db, user_id, arguments)
    return {"ok": False, "error": f"未知工具：{name}"}


async def execute_tool_async(db: Session, *, user_id: str, name: str, arguments: dict[str, Any]) -> dict:
    if name == "semantic_search_knowledge":
        return await _semantic_search_knowledge_async(db, arguments)
    if name == "hybrid_search_products":
        semantic_query = str(arguments.get("semantic_query") or "").strip()
        semantic_rows = []
        if semantic_query:
            semantic_rows = await knowledge_service.semantic_retrieve(
                db,
                semantic_query,
                sku=str(arguments.get("sku") or "").strip().upper() or None,
                limit=int(arguments.get("limit") or 50),
            )
        return _hybrid_search_products(db, arguments, semantic_rows=semantic_rows)
    return execute_tool(db, user_id=user_id, name=name, arguments=arguments)


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
    return {"ok": True, "tool": "semantic_search_knowledge", "query": query, "sku": sku, "mode": "keyword", "count": len(rows), "results": rows}


async def _semantic_search_knowledge_async(db: Session, arguments: dict[str, Any]) -> dict:
    query = str(arguments.get("query") or "").strip()
    sku = str(arguments.get("sku") or "").strip().upper() or None
    limit = int(arguments.get("limit") or 8)
    rows = await knowledge_service.semantic_retrieve(db, query, sku=sku, limit=limit)
    return {"ok": True, "tool": "semantic_search_knowledge", "query": query, "sku": sku, "mode": "semantic", "count": len(rows), "results": rows}


def _hybrid_search_products(db: Session, arguments: dict[str, Any], semantic_rows: list[dict]) -> dict:
    term = str(arguments.get("term") or "").strip()
    semantic_query = str(arguments.get("semantic_query") or "").strip()
    limit = int(arguments.get("limit") or 50)
    filters = arguments.get("filters") or {}
    if not isinstance(filters, dict):
        filters = {}
    fields = arguments.get("fields") or []
    if isinstance(fields, str):
        fields = [fields]

    sql_rows = customer_agent_service.search_products(db, term, limit=limit, filters=filters)
    merged: dict[str, dict] = {}
    for index, row in enumerate(sql_rows):
        enriched = _enrich_fields(db, row, fields)
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
            enriched = _enrich_fields(db, rows[0], fields)
            enriched["hybrid_score"] = 500 - index
            enriched["matched_by"] = "语义知识库"
            enriched["semantic_match"] = item.get("content")
            merged[sku] = enriched

    rows = sorted(merged.values(), key=lambda row: row.get("hybrid_score", 0), reverse=True)[:limit]
    for row in rows:
        row.pop("hybrid_score", None)
    return {
        "ok": True,
        "tool": "hybrid_search_products",
        "query": term or semantic_query,
        "filters": filters,
        "semantic_query": semantic_query,
        "count": len(rows),
        "results": rows,
    }


def _get_product_detail(db: Session, arguments: dict[str, Any]) -> dict:
    skus = _extract_argument_skus(arguments)
    if not skus:
        return {"ok": False, "tool": "get_product_detail", "error": "缺少 SKU"}
    details = []
    errors = []
    for sku in skus[:20]:
        try:
            details.append(product_service.get_product_detail(db, sku))
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
        field_path = _resolve_field(field)
        if not field_path:
            continue
        section, key = field_path.split(".", 1)
        value = detail.get(key) if section == "product" else (detail.get(section) or {}).get(key)
        label = agent_action_service.FIELD_SPECS[field_path].label
        field_values[label] = customer_agent_service._stringify(value) if value not in (None, "") else "暂无"
    enriched["field_values"] = field_values
    return enriched
