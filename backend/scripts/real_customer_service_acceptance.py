"""Real HTTP acceptance for customer-service answer quality.

This intentionally talks to a running server instead of importing application
services.  It verifies authentication, persistence-backed multi-turn context,
normal JSON responses, SSE responses, evidence/SKU boundaries, and governed
model metadata.  The resulting JSON is also designed for human answer review.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import statistics
import time
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Any


INTERNAL_ANSWER_TERMS = (
    "candidate_skus",
    "result_skus",
    "semantic_preplan",
    "agent_mode",
    "field_contract",
    "recommendation_contract",
    "tool_required_but_not_used",
    "llm_call_count",
    "binding_provenance",
)


def case(case_id: str, question: str, **expectations: Any) -> dict[str, Any]:
    return {"id": case_id, "question": question, **expectations}


SEQUENCES: list[dict[str, Any]] = [
    {
        "id": "authoritative_facts",
        "turns": [
            case(
                "fact_c95_material",
                "CW-C95 的主体材质具体有哪些？请按资料完整说明。",
                expected_skus=["CW-C95"],
                allowed_skus=["CW-C95"],
                required_all=["硬质氧化铝合金", "不锈钢", "黄铜"],
            ),
            case(
                "fact_c95_capacity",
                "CW-C95 的煮锅、煎盘和水壶分别多大？",
                expected_skus=["CW-C95"],
                allowed_skus=["CW-C95"],
                required_all=["1.7L", "8寸", "0.8L"],
            ),
            case(
                "fact_c95_fuel_power",
                "CW-C95 支持哪些燃料或气罐，最大功率是多少？",
                expected_skus=["CW-C95"],
                allowed_skus=["CW-C95"],
                required_all=["高山气罐", "液体酒精", "3200W"],
            ),
        ],
    },
    {
        "id": "single_product_facts",
        "independent_turns": True,
        "turns": [
            case(
                "fact_g25",
                "小青炉 CS-G25 用什么气罐，最大功率是多少？",
                expected_skus=["CS-G25"],
                allowed_skus=["CS-G25"],
                required_all=["高山气罐", "卡式气罐", "3200W"],
            ),
            case(
                "fact_pg19",
                "瓦片烤盘 CF-PG19 的尺寸、材质和适用炉具一次说清楚。",
                expected_skus=["CF-PG19"],
                allowed_skus=["CF-PG19"],
                required_all=["32", "3.9", "铝合金", "卡式炉"],
            ),
            case(
                "fact_c83",
                "炊墨套锅 CW-C83 的两件容量和整套毛重分别是多少？",
                expected_skus=["CW-C83"],
                allowed_skus=["CW-C83"],
                required_all=["3700", "2300", "2000"],
            ),
            case(
                "fact_c06pro",
                "轻途套锅 CW-C06PRO 是什么材质，整套毛重多少？",
                expected_skus=["CW-C06PRO"],
                allowed_skus=["CW-C06PRO"],
                required_all=["3003铝合金", "1150"],
            ),
            case(
                "fact_ac19",
                "稳稳水袋 AC-19 容量、材质和重量分别是多少？",
                expected_skus=["AC-19"],
                allowed_skus=["AC-19"],
                required_all=["8L", "PET", "PA", "PE", "150"],
            ),
            case(
                "fact_chopsticks",
                "便携式户外旅行筷 TW-204-42 是什么材质、多重，使用后怎么清洁收纳？",
                expected_skus=["TW-204-42"],
                allowed_skus=["TW-204-42"],
                required_all=["鸡翅木", "36", "温水", "擦干"],
            ),
            case(
                "fact_b14",
                "旋焰酒精炉 CS-B14 应该加什么燃料，容量和最大功率是多少？",
                expected_skus=["CS-B14"],
                allowed_skus=["CS-B14"],
                required_all=["95%", "200ML", "2250W"],
            ),
            case(
                "fact_c95_fuel_power_paraphrase",
                "请核对 CW-C95 可配的气源或燃料种类，同时告诉我它的额定输出。",
                expected_skus=["CW-C95"],
                allowed_skus=["CW-C95"],
                required_all=["高山气罐", "液体酒精", "3200W"],
            ),
        ],
    },
    {
        "id": "catalog_and_recommendations",
        "independent_turns": True,
        "turns": [
            case(
                "catalog_weixue",
                "围雪炉有哪些款？请按产品资料列出名称和 SKU，并简要说清区别。",
                required_any=[["CS-B15S", "围雪炉-酒精版"], ["CS-B15SPRO", "围雪炉-酒精汽炉版"]],
                minimum_answer_length=80,
                require_flash=True,
            ),
            case(
                "recommend_alcohol_cookware",
                "我已经有酒精炉，想买一口适合两个人煮面、轻便些的锅，请按现有资料推荐并说明理由。",
                expected_skus=["CW-S10-A"],
                required_any=[["酒精炉"], ["1.4L", "1400ML", "1400毫升"], ["双人", "两个人", "1-2"]],
                minimum_answer_length=80,
                require_flash=True,
            ),
            case(
                "recommend_alcohol_cookware_concise",
                "适合酒精炉的双人锅具推荐一款。",
                expected_skus=["CW-S10-A"],
                allowed_skus=["CW-S10-A"],
                required_any=[["酒精炉"], ["双人", "两个人", "1-2"]],
                minimum_answer_length=50,
                enforce_allowed_evidence_skus=False,
                require_flash=True,
            ),
            case(
                "recommend_beginner",
                "我是露营新手，两个人周末露营，主要烧水和煮面，不想买太复杂的，帮我选一款锅。",
                require_result_skus=True,
                required_any=[["推荐", "建议", "可以先看", "可以考虑"], ["烧水", "煮面", "容量"]],
                minimum_answer_length=80,
                require_flash=True,
            ),
            case(
                "recommend_pour_over",
                "咖啡器具里有哪些适合手冲的产品？请给我两三款真正相关的选择，并说明各自适合谁。",
                require_result_skus=True,
                required_any=[["手冲", "咖啡"]],
                minimum_answer_length=100,
                require_flash=True,
            ),
            case(
                "recommend_griddle",
                "我有卡式炉，想买烤盘，哪些产品明确支持卡式炉？优先推荐好清洁的。",
                expected_skus=["CF-PG19"],
                required_any=[["卡式炉"], ["清洁", "不沾"]],
                minimum_answer_length=80,
                require_flash=True,
            ),
            case(
                "recommend_gift",
                "朋友刚开始露营，我想送一件不容易选错、实用又好收纳的礼物，你会怎么建议？",
                required_any=[["建议", "推荐", "考虑"], ["需求", "人数", "场景", "预算", "开车", "徒步", "类型"]],
                minimum_answer_length=70,
                require_flash=True,
            ),
            case(
                "recommend_gift_paraphrase",
                "想给第一次露营的朋友挑个不占地方的实用装备，暂时没定品类，先帮我理一下该怎么选。",
                required_any=[["建议", "推荐", "选择"], ["品类", "类型", "预算", "人数", "自驾", "徒步"]],
                minimum_answer_length=70,
                require_flash=True,
            ),
        ],
    },
    {
        "id": "safety_and_boundaries",
        "independent_turns": True,
        "turns": [
            case(
                "safety_tent_alcohol",
                "液体酒精炉能在封闭帐篷里用吗？请直接告诉我风险和安全做法。",
                required_any=[["不能", "不建议", "严禁", "不要"], ["通风", "室外"], ["一氧化碳", "中毒", "火灾"]],
                minimum_answer_length=100,
            ),
            case(
                "safety_refill",
                "旋焰酒精炉 CS-B14 燃烧到一半火变小了，能不能直接补酒精？",
                expected_skus=["CS-B14"],
                allowed_skus=["CS-B14"],
                required_any=[["不能", "严禁", "不可"], ["灭火", "熄灭"]],
                forbidden_terms=["可以直接加", "边烧边加"],
                minimum_answer_length=35,
            ),
            case(
                "care_burnt_pan",
                "锅不小心烧糊了怎么处理？我不确定有没有涂层，请给稳妥、不伤锅的做法。",
                required_any=[["冷却", "放凉"], ["温水", "浸泡"], ["软", "海绵"], ["钢丝球", "硬物"]],
                forbidden_terms=["小苏打煮开", "煮沸清洁剂", "可以加热清洁剂", "建议加热清洁剂"],
                minimum_answer_length=120,
                require_flash=True,
            ),
            case(
                "boundary_warranty",
                "CS-B14 保修多久？如果资料没有具体期限，请明确说没有，不要猜。",
                expected_skus=["CS-B14"],
                allowed_skus=["CS-B14"],
                required_any=[["没有", "未", "无法确认", "人工", "购买渠道"]],
                forbidden_terms=["一年质保", "两年质保", "终身质保"],
            ),
            case(
                "boundary_stock_price",
                "CW-C95 现在有没有现货，当前售价多少？",
                expected_skus=["CW-C95"],
                allowed_skus=["CW-C95"],
                required_any=[
                    ["库存", "现货", "在售"],
                    ["价格", "售价", "多少钱"],
                    ["无法", "没有", "未提供", "订单页面", "购买渠道", "实时"],
                ],
                forbidden_terms=["现货充足", "库存充足", "售价为"],
            ),
            case(
                "boundary_shipping",
                "我今天下单能保证明天发货吗？",
                required_any=[["不能保证", "无法保证", "订单", "客服", "渠道"]],
                forbidden_terms=["保证明天", "一定明天"],
                minimum_answer_length=50,
            ),
            case(
                "boundary_unknown_sku",
                "ZX-NOT-FOUND-999 适合一个人露营吗？",
                required_any=[["没有找到", "找不到", "未找到", "核对"]],
                forbidden_terms=["非常适合", "推荐购买"],
            ),
            case(
                "boundary_contaminated_qa",
                "天鹅壶4杯黑色研磨粗细能调吗？",
                required_any=[["同一", "同 SKU", "对应产品", "无法确认", "不能确认", "未找到", "暂未"]],
                forbidden_terms=["可以调", "支持调节", "旋转旋钮"],
            ),
        ],
    },
    {
        "id": "negation_semantics",
        "independent_turns": True,
        "turns": [
            case(
                "negation_no_stove",
                "只推荐锅具，不要炉具和配件，适合两个人周末露营，最好能用酒精炉。",
                expected_skus=["CW-S10-A"],
                forbidden_terms=["推荐旋焰酒精炉", "推荐小青炉"],
                minimum_answer_length=60,
                require_flash=True,
            ),
            case(
                "negation_ignore_price",
                "别管价格，只看轻便和一个人徒步，推荐一口能烧水煮面的锅。",
                require_result_skus=True,
                forbidden_terms=["预算有限", "价格更低", "性价比优先"],
                minimum_answer_length=70,
                require_flash=True,
            ),
            case(
                "negation_except_c83",
                "除了 CW-C83，再推荐一款更轻、适合两个人用的锅具。",
                require_result_skus=True,
                forbidden_result_skus=["CW-C83"],
                forbidden_terms=["优先推荐炊墨套锅"],
                minimum_answer_length=70,
                require_flash=True,
            ),
            case(
                "negation_exclude_gas",
                "除去燃气炉和卡式炉，只看能配酒精炉的锅具，推荐一款两人用的。",
                expected_skus=["CW-S10-A"],
                forbidden_terms=["推荐小青炉", "推荐麒麟炉"],
                minimum_answer_length=70,
                require_flash=True,
            ),
        ],
    },
    {
        "id": "comparison_context",
        "turns": [
            case(
                "compare_start",
                "CW-C83 和 CW-C06PRO 哪个更适合两个人周末徒步？请比较重量、容量和收纳负担。",
                expected_skus=["CW-C83", "CW-C06PRO"],
                allowed_skus=["CW-C83", "CW-C06PRO"],
                required_all=["2000", "1150"],
                minimum_answer_length=130,
                require_flash=True,
            ),
            case(
                "compare_choice",
                "你更建议哪一个？请明确选一个并说明理由。",
                required_any=[["CW-C06PRO", "轻途套锅"], ["建议", "推荐", "更适合"]],
                minimum_answer_length=70,
            ),
            case(
                "compare_followup_fields",
                "刚选的那款材质、容量、重量一次说清楚。",
                expected_skus=["CW-C06PRO"],
                allowed_skus=["CW-C06PRO"],
                required_all=["3003铝合金", "3.0L", "1.7L", "0.8L", "1150"],
            ),
            case(
                "compare_followup_alcohol",
                "如果我改用酒精炉，这款在现有资料里明确支持吗？有冲突也请直说。",
                expected_skus=["CW-C06PRO"],
                allowed_skus=["CW-C06PRO"],
                required_any=[["酒精炉"], ["资料", "热源", "问答", "无法确认", "未明确"]],
                forbidden_terms=["毫无问题", "完全兼容"],
            ),
        ],
    },
    {
        "id": "recommendation_context",
        "turns": [
            case(
                "rec_context_start",
                "我是露营新手，一个人徒步，想买轻一点、能烧水煮面的锅，预算有限，推荐一款。",
                require_result_skus=True,
                minimum_answer_length=80,
                require_flash=True,
            ),
            case(
                "rec_context_fields",
                "你刚才第一款的重量和容量分别是多少？",
                required_any=[["重量", "g"], ["容量", "L", "ML"]],
            ),
            case(
                "rec_context_heat",
                "它能用酒精炉吗？资料明确才说可以。",
                required_any=[["酒精炉"], ["资料", "明确", "未", "可以", "不可以"]],
            ),
            case(
                "rec_context_alternative",
                "还有更轻一点、也能烧水的备选吗？不要重复刚才那款。",
                required_any=[["更轻", "没有找到", "未找到"], ["CW-C73", "刚才"]],
                minimum_answer_length=60,
                require_flash=True,
            ),
        ],
    },
    {
        "id": "context_switch",
        "turns": [
            case(
                "switch_c83",
                "先告诉我 CW-C83 的容量和材质。",
                expected_skus=["CW-C83"],
                allowed_skus=["CW-C83"],
                required_all=["3700", "2300", "硬质氧化铝合金"],
            ),
            case(
                "switch_c93",
                "我又在看 CW-C93，它的容量和重量是多少？",
                expected_skus=["CW-C93"],
                allowed_skus=["CW-C93"],
                required_all=["1000ML", "220"],
            ),
            case(
                "switch_previous",
                "上一款更适合几个人？",
                expected_skus=["CW-C93"],
                allowed_skus=["CW-C93"],
                required_any=[["单人", "一个人", "1人"]],
            ),
            case(
                "switch_back",
                "还是回到 CW-C83：资料有没有明确说可以放洗碗机？",
                expected_skus=["CW-C83"],
                allowed_skus=["CW-C83"],
                required_any=[["没有", "未明确", "无法确认", "不建议"]],
                forbidden_terms=["可以放洗碗机", "支持洗碗机"],
            ),
        ],
    },
    {
        "id": "package_context",
        "turns": [
            case(
                "package_anchor",
                "天鹅壶4杯黑色适合什么露营场景？",
                required_any=[["天鹅壶", "4杯黑色"], ["露营", "户外"]],
                minimum_answer_length=35,
            ),
            case(
                "package_quantity",
                "它里面实际有几个杯子？只按包装清单回答。",
                required_any=[["包装", "清单", "资料"], ["没有", "未", "无法确认"]],
                forbidden_terms=["有4个杯子", "包含4只杯子", "四个杯子"],
            ),
            case(
                "package_clean",
                "那它第一次使用前应该怎么清洁？",
                required_any=[["资料", "说明", "无法", "未"], ["清洁", "使用"]],
                forbidden_terms=["旋转研磨", "调节粗细"],
            ),
            case(
                "package_switch",
                "换一个产品：CW-C95 第一次使用前怎么处理？资料不完整就明确说。",
                expected_skus=["CW-C95"],
                allowed_skus=["CW-C95"],
                require_result_skus=True,
                required_any=[["资料", "说明", "使用", "清洁"], ["未", "无法", "温水", "检查"]],
            ),
        ],
    },
]


PARITY_CASES = [
    case("parity_catalog", "围雪炉有哪些款？"),
    case("parity_cross_sku", "天鹅壶4杯黑色研磨粗细能调吗？"),
    case("parity_fact", "CS-G25 用什么气罐，功率是多少？"),
    case("parity_recommend", "适合酒精炉的双人锅具推荐一款。"),
]


def _normalize_url(value: str) -> str:
    return value.rstrip("/")


def _request(
    url: str,
    payload: dict[str, Any],
    *,
    token: str = "",
    timeout: int = 240,
    parity_isolation: bool = False,
) -> tuple[int, bytes, dict[str, str], float]:
    headers = {"Content-Type": "application/json; charset=utf-8", "Accept": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    if parity_isolation:
        headers["X-Customer-Service-Parity-Isolation"] = "true"
    req = urllib.request.Request(
        url,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    started = time.perf_counter()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            return (
                response.status,
                response.read(),
                {key.lower(): value for key, value in response.headers.items()},
                round((time.perf_counter() - started) * 1000, 1),
            )
    except urllib.error.HTTPError as exc:
        return (
            exc.code,
            exc.read(),
            {key.lower(): value for key, value in exc.headers.items()},
            round((time.perf_counter() - started) * 1000, 1),
        )
    except Exception as exc:
        return 0, json.dumps({"error": str(exc)}, ensure_ascii=False).encode("utf-8"), {}, round(
            (time.perf_counter() - started) * 1000, 1
        )


def post_json(
    base_url: str,
    path: str,
    payload: dict[str, Any],
    *,
    token: str = "",
    timeout: int = 240,
    parity_isolation: bool = False,
) -> tuple[int, dict[str, Any], float]:
    status, raw, _, elapsed_ms = _request(
        f"{base_url}{path}",
        payload,
        token=token,
        timeout=timeout,
        parity_isolation=parity_isolation,
    )
    try:
        body = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        body = {"raw": raw.decode("utf-8", errors="replace")}
    return status, body, elapsed_ms


def post_sse(
    base_url: str,
    path: str,
    payload: dict[str, Any],
    *,
    token: str,
    timeout: int,
    parity_isolation: bool,
) -> tuple[int, dict[str, Any], float]:
    status, raw, _, elapsed_ms = _request(
        f"{base_url}{path}",
        payload,
        token=token,
        timeout=timeout,
        parity_isolation=parity_isolation,
    )
    text = raw.decode("utf-8", errors="replace")
    current_event = "message"
    data_lines: list[str] = []
    events: list[dict[str, Any]] = []

    def flush() -> None:
        nonlocal current_event, data_lines
        if not data_lines:
            current_event = "message"
            return
        data_text = "\n".join(data_lines)
        try:
            data: Any = json.loads(data_text)
        except json.JSONDecodeError:
            data = {"raw": data_text}
        events.append({"event": current_event, "data": data})
        current_event = "message"
        data_lines = []

    for line in text.splitlines():
        if not line:
            flush()
        elif line.startswith("event:"):
            current_event = line[6:].strip()
        elif line.startswith("data:"):
            data_lines.append(line[5:].lstrip())
    flush()

    answer_parts: list[str] = []
    meta: dict[str, Any] = {}
    errors: list[Any] = []
    for item in events:
        event_name = item["event"]
        data = item["data"] if isinstance(item["data"], dict) else {}
        if event_name == "content":
            answer_parts.append(str(data.get("content") or ""))
        elif event_name == "answer_delta":
            answer_parts.append(str(data.get("text") or ""))
        elif event_name == "meta":
            meta = data
        elif event_name == "error":
            errors.append(data)
    return status, {"answer": "".join(answer_parts), "meta": meta, "errors": errors, "events": events}, elapsed_ms


def _collect_skus(value: Any) -> set[str]:
    found: set[str] = set()
    if isinstance(value, dict):
        for key, item in value.items():
            if key.lower() in {"sku", "product_sku", "resolved_sku"} and item:
                found.add(str(item).strip().upper())
            else:
                found.update(_collect_skus(item))
    elif isinstance(value, list):
        for item in value:
            found.update(_collect_skus(item))
    return found


def _collect_model_names(value: Any) -> set[str]:
    found: set[str] = set()
    if isinstance(value, dict):
        for key, item in value.items():
            lowered = key.lower()
            if isinstance(item, str) and (lowered == "model" or lowered.endswith("_model")) and item.strip():
                found.add(item.strip())
            else:
                found.update(_collect_model_names(item))
    elif isinstance(value, list):
        for item in value:
            found.update(_collect_model_names(item))
    return found


def _semantic_snapshot(debug: dict[str, Any]) -> dict[str, Any]:
    semantic = debug.get("semantic_preplan") if isinstance(debug.get("semantic_preplan"), dict) else {}
    if not semantic:
        plan = debug.get("plan") if isinstance(debug.get("plan"), dict) else {}
        semantic = plan.get("semantic_preplan") if isinstance(plan.get("semantic_preplan"), dict) else {}
    return {
        "called": bool(semantic.get("called")),
        "model": semantic.get("model"),
        "fallback_used": bool(semantic.get("fallback_used") or semantic.get("used_fallback")),
        "fallback_reason": semantic.get("fallback_reason"),
        "accepted_or_overridden": semantic.get("accepted_or_overridden"),
        "route_hint": semantic.get("route_hint"),
    }


def evaluate(case_data: dict[str, Any], status: int, body: dict[str, Any], elapsed_ms: float) -> dict[str, Any]:
    answer = str(body.get("answer") or "").strip()
    answer_lower = answer.lower()
    # Formatting whitespace around units (for example “8 寸” versus “8寸”)
    # does not change factual content and must not create a false release
    # failure. Keep the original answer for every other quality check.
    answer_content_match = re.sub(r"\s+", "", answer_lower)
    result_skus = {str(item).strip().upper() for item in body.get("result_skus") or [] if item}
    result_skus.update(str(item).strip().upper() for item in body.get("candidate_skus") or [] if item and not result_skus)
    debug = body.get("debug") if isinstance(body.get("debug"), dict) else {}
    metadata = body.get("answer_metadata") if isinstance(body.get("answer_metadata"), dict) else {}
    evidence_skus = _collect_skus(body.get("evidence") or []) | _collect_skus(body.get("sources") or [])
    model_names = _collect_model_names(debug) | _collect_model_names(metadata)
    semantic = _semantic_snapshot(debug)

    expected_skus = {str(item).upper() for item in case_data.get("expected_skus") or []}
    allowed_skus = {str(item).upper() for item in case_data.get("allowed_skus") or []}
    forbidden_result_skus = {str(item).upper() for item in case_data.get("forbidden_result_skus") or []}
    visible_skus = result_skus | {sku for sku in expected_skus | allowed_skus if sku in answer.upper()}
    missing_expected_skus = sorted(expected_skus - visible_skus)
    unexpected_result_skus = sorted(result_skus - allowed_skus) if allowed_skus else []
    unexpected_evidence_skus = (
        sorted(evidence_skus - allowed_skus)
        if allowed_skus and case_data.get("enforce_allowed_evidence_skus", True)
        else []
    )
    forbidden_skus_returned = sorted(result_skus & forbidden_result_skus)

    required_all = [str(item) for item in case_data.get("required_all") or []]
    missing_required_all = [
        item for item in required_all
        if re.sub(r"\s+", "", item.lower()) not in answer_content_match
    ]
    required_any = [[str(term) for term in group] for group in case_data.get("required_any") or []]
    missing_required_any = [
        group for group in required_any
        if not any(re.sub(r"\s+", "", term.lower()) in answer_content_match for term in group)
    ]
    forbidden_terms = [str(item) for item in case_data.get("forbidden_terms") or []]
    forbidden_terms_found = [item for item in forbidden_terms if item.lower() in answer_lower]
    internal_terms_found = [item for item in INTERNAL_ANSWER_TERMS if item.lower() in answer_lower]
    minimum_answer_length = int(case_data.get("minimum_answer_length") or 20)
    non_flash_models = sorted(name for name in model_names if "flash" not in name.lower())

    checks = {
        "http_200": status == 200,
        "non_empty_answer": bool(answer),
        "conversation_id_returned": bool(body.get("conversation_id")),
        "minimum_answer_length": len(answer) >= minimum_answer_length,
        "expected_skus_present": not missing_expected_skus,
        "allowed_result_skus_only": not unexpected_result_skus,
        "allowed_evidence_skus_only": not unexpected_evidence_skus,
        "forbidden_result_skus_absent": not forbidden_skus_returned,
        "required_all_present": not missing_required_all,
        "required_any_groups_present": not missing_required_any,
        "forbidden_terms_absent": not forbidden_terms_found,
        "internal_terms_absent": not internal_terms_found,
        "result_skus_returned": bool(result_skus) if case_data.get("require_result_skus") else True,
        "all_reported_models_are_flash": not non_flash_models,
        "flash_semantic_call_observed": (
            semantic["called"] and bool(model_names) and not non_flash_models
            if case_data.get("require_flash")
            else True
        ),
        "semantic_call_did_not_fallback": not semantic["fallback_used"] if semantic["called"] else True,
        "no_stream_error_shape": not body.get("error"),
    }
    failed_checks = [name for name, passed in checks.items() if not passed]
    return {
        "id": case_data["id"],
        "question": case_data["question"],
        "status": status,
        "elapsed_ms": elapsed_ms,
        "answer": answer,
        "answer_length": len(answer),
        "conversation_id": body.get("conversation_id"),
        "intent": body.get("intent"),
        "answer_type": body.get("answer_type"),
        "agent_mode": debug.get("agent_mode"),
        "result_skus": sorted(result_skus),
        "evidence_skus": sorted(evidence_skus),
        "model_names": sorted(model_names),
        "semantic_preplan": semantic,
        "warnings": body.get("warnings") or [],
        "needs_clarification": bool(body.get("needs_clarification")),
        "failed_checks": failed_checks,
        "check_details": {
            "missing_expected_skus": missing_expected_skus,
            "unexpected_result_skus": unexpected_result_skus,
            "unexpected_evidence_skus": unexpected_evidence_skus,
            "forbidden_skus_returned": forbidden_skus_returned,
            "missing_required_all": missing_required_all,
            "missing_required_any": missing_required_any,
            "forbidden_terms_found": forbidden_terms_found,
            "internal_terms_found": internal_terms_found,
            "non_flash_models": non_flash_models,
        },
        "checks": checks,
        "auto_pass": not failed_checks,
        "manual_review": {
            "factually_accurate": None,
            "complete": None,
            "friendly_and_natural": None,
            "actionable": None,
            "notes": "",
        },
        "diagnostics": {
            "trace": debug.get("trace"),
            "plan": debug.get("plan"),
            "final_decision": metadata.get("final_decision"),
            "source": metadata.get("source"),
            "recommendation_narrative": metadata.get("recommendation_narrative"),
            "recommendation_narrative_diagnostics": debug.get("recommendation_narrative_diagnostics"),
            "semantic_constraints": debug.get("semantic_constraints"),
            "candidate_verifications": debug.get("candidate_verifications"),
            "rejected_candidates": debug.get("rejected_candidates"),
            "agent_quality": body.get("agent_quality"),
        },
    }


def login(base_url: str, timeout: int) -> str:
    username = os.environ.get("CUSTOMER_SERVICE_USERNAME", "admin")
    password = os.environ.get("CUSTOMER_SERVICE_PASSWORD", "admin123")
    status, body, _ = post_json(
        base_url,
        "/api/auth/login",
        {"username": username, "password": password},
        timeout=min(timeout, 30),
    )
    if status != 200 or not body.get("access_token"):
        raise RuntimeError(f"login failed: HTTP {status}: {body}")
    return str(body["access_token"])


def run_matrix(base_url: str, token: str, timeout: int, only: str = "") -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    selected = {item.strip() for item in only.split(",") if item.strip()}
    for sequence in SEQUENCES:
        sequence_id = str(sequence["id"])
        if selected and sequence_id not in selected and not any(turn["id"] in selected for turn in sequence["turns"]):
            continue
        conversation_id: str | None = None
        for turn_index, turn in enumerate(sequence["turns"], start=1):
            if selected and sequence_id not in selected and turn["id"] not in selected:
                continue
            if sequence.get("independent_turns"):
                conversation_id = None
            payload = {"question": turn["question"]}
            if conversation_id:
                payload["conversation_id"] = conversation_id
            status, body, elapsed_ms = post_json(
                base_url,
                "/api/customer-service/ask?debug=true",
                payload,
                token=token,
                timeout=timeout,
            )
            record = evaluate(turn, status, body, elapsed_ms)
            record["sequence"] = sequence_id
            record["turn"] = turn_index
            record["sent_conversation_id"] = conversation_id
            records.append(record)
            if not sequence.get("independent_turns"):
                conversation_id = str(body.get("conversation_id") or conversation_id or "") or None
            print(
                json.dumps(
                    {
                        "id": record["id"],
                        "status": status,
                        "elapsed_ms": elapsed_ms,
                        "auto_pass": record["auto_pass"],
                        "failed_checks": record["failed_checks"],
                        "skus": record["result_skus"],
                        "models": record["model_names"],
                        "question": record["question"],
                        "answer": record["answer"],
                    },
                    ensure_ascii=False,
                ),
                flush=True,
            )
    return records


def run_parity(base_url: str, token: str, timeout: int) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for item in PARITY_CASES:
        payload = {"question": item["question"]}
        normal_status, normal_body, normal_ms = post_json(
            base_url,
            "/api/customer-service/ask?debug=true",
            payload,
            token=token,
            timeout=timeout,
            parity_isolation=True,
        )
        stream_status, stream_body, stream_ms = post_sse(
            base_url,
            "/api/customer-service/ask-stream",
            payload,
            token=token,
            timeout=timeout,
            parity_isolation=True,
        )
        meta = stream_body.get("meta") if isinstance(stream_body.get("meta"), dict) else {}
        normal_answer = str(normal_body.get("answer") or "")
        stream_answer = str(stream_body.get("answer") or "")
        checks = {
            "normal_http_200": normal_status == 200,
            "stream_http_200": stream_status == 200,
            "normal_non_empty": bool(normal_answer.strip()),
            "stream_non_empty": bool(stream_answer.strip()),
            "exact_answer_parity": normal_answer == stream_answer,
            "intent_parity": normal_body.get("intent") == meta.get("intent"),
            "answer_type_parity": normal_body.get("answer_type") == meta.get("answer_type"),
            "result_skus_parity": sorted(normal_body.get("result_skus") or []) == sorted(meta.get("result_skus") or []),
            "no_stream_errors": not stream_body.get("errors"),
        }
        record = {
            "id": item["id"],
            "question": item["question"],
            "normal_status": normal_status,
            "stream_status": stream_status,
            "normal_elapsed_ms": normal_ms,
            "stream_elapsed_ms": stream_ms,
            "normal_answer": normal_answer,
            "stream_answer": stream_answer,
            "normal_intent": normal_body.get("intent"),
            "stream_intent": meta.get("intent"),
            "normal_answer_type": normal_body.get("answer_type"),
            "stream_answer_type": meta.get("answer_type"),
            "normal_result_skus": normal_body.get("result_skus") or [],
            "stream_result_skus": meta.get("result_skus") or [],
            "stream_errors": stream_body.get("errors") or [],
            "checks": checks,
            "failed_checks": [name for name, passed in checks.items() if not passed],
            "pass": all(checks.values()),
        }
        records.append(record)
        print(json.dumps(record, ensure_ascii=False), flush=True)
    return records


def percentile(values: list[float], percentile_value: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = (len(ordered) - 1) * percentile_value
    lower = int(index)
    upper = min(lower + 1, len(ordered) - 1)
    fraction = index - lower
    return round(ordered[lower] * (1 - fraction) + ordered[upper] * fraction, 1)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default=os.environ.get("CUSTOMER_SERVICE_BASE_URL", "http://127.0.0.1:8001"))
    parser.add_argument("--timeout", type=int, default=240)
    parser.add_argument("--only", default="", help="Comma-separated sequence or case IDs")
    parser.add_argument("--skip-parity", action="store_true")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    base_url = _normalize_url(args.base_url)
    token = login(base_url, args.timeout)
    started_at = datetime.now()
    records = run_matrix(base_url, token, args.timeout, args.only)
    parity_records = [] if args.skip_parity or args.only else run_parity(base_url, token, args.timeout)
    elapsed_values = [float(item["elapsed_ms"]) for item in records]
    auto_failed = [item["id"] for item in records if not item["auto_pass"]]
    parity_failed = [item["id"] for item in parity_records if not item["pass"]]
    latency_gate = {
        "median_under_15s": statistics.median(elapsed_values) < 15_000 if elapsed_values else False,
        "p95_under_45s": percentile(elapsed_values, 0.95) < 45_000 if elapsed_values else False,
        "no_request_over_120s": max(elapsed_values, default=0) < 120_000,
    }
    report = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "started_at": started_at.isoformat(timespec="seconds"),
        "base_url": base_url,
        "gate_policy": {
            "automatic": "all cases and normal/SSE parity pass; median <15s, p95 <45s, max <120s",
            "manual": "every answer must be factually accurate, complete, friendly/natural, and actionable",
            "model": "any observed governed model must be Flash; semantic-required cases must call Flash without fallback",
        },
        "summary": {
            "case_count": len(records),
            "auto_pass_count": len(records) - len(auto_failed),
            "auto_fail_count": len(auto_failed),
            "auto_failed_ids": auto_failed,
            "parity_count": len(parity_records),
            "parity_failed_ids": parity_failed,
            "latency_ms": {
                "median": round(statistics.median(elapsed_values), 1) if elapsed_values else 0,
                "p95": percentile(elapsed_values, 0.95),
                "max": max(elapsed_values, default=0),
            },
            "latency_gate": latency_gate,
            "automatic_release_gate_pass": not auto_failed and not parity_failed and all(latency_gate.values()),
            "manual_release_gate_pass": None,
        },
        "records": records,
        "parity_records": parity_records,
    }
    output = args.output or (
        Path(__file__).resolve().parents[2]
        / "reports"
        / f"real_customer_service_acceptance_{datetime.now():%Y%m%d_%H%M%S}.json"
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(
        json.dumps(
            {
                "report": str(output),
                "summary": report["summary"],
            },
            ensure_ascii=False,
        ),
        flush=True,
    )
    return 0 if report["summary"]["automatic_release_gate_pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
