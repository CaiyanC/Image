"""Real HTTP acceptance for the semantic RAG customer-service pipeline.

This is intentionally a new release contract.  It does not reuse the old
non-RAG acceptance script's fixed phrases, minimum answer lengths, or literal
keyword evidence gates.  The automatic checks cover HTTP shape, route intent,
same-SKU identity binding, hard-fact consistency, safe no-match behavior, and
normal/stream parity.  The printed answers and saved response bodies are the
manual-review record for usefulness and naturalness.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
import urllib.error
import urllib.request
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


sys.stdout.reconfigure(encoding="utf-8", errors="replace")


INTERNAL_ANSWER_TERMS = (
    "候选索引",
    "candidate_index",
    "evidence_usage",
    "semantic_preplan",
    "RAG",
    "提示词",
    "内部路由",
    "证据闸门",
)

GAP_TERMS = (
    "没有找到",
    "未找到",
    "没有明确",
    "未明确",
    "没有记录",
    "未记录",
    "没有提供",
    "未提供",
    "没有对应",
    "无对应",
    "无法直接",
    "不能作为替代",
    "暂时无法",
    "资料不足",
    "没有相关",
)


CASES: list[dict[str, Any]] = [
    {
        "id": "explicit_b14_refill",
        "kind": "sku_fact",
        "question": "旋焰酒精炉 CS-B14 燃烧到一半火变小了，能不能直接补酒精？",
        "sku": "CS-B14",
        "route_families": {"product_fact", "product_bound_qa", "safety", "general_chat"},
        "must_have_any": [["不能", "不要", "禁止"], ["熄灭", "冷却", "停止"]],
    },
    {
        "id": "explicit_s10_capacity_bare_sku",
        "kind": "sku_fact",
        "question": "CW-S10-1 容量够不够两个人煮面？",
        "sku": "CW-S10-1",
        "route_families": {"product_fact", "product_bound_qa", "recommendation"},
        "signal_groups": [["1400", "1.4", "容量"], ["双人", "两个人", "2人", "1-2"]],
    },
    {
        "id": "recommend_beginner",
        "kind": "recommendation",
        "question": "我是露营新手，两个人周末露营，主要烧水和煮面，不想买太复杂的，帮我选一款锅。",
        "positive": True,
        "route_families": {"recommendation"},
        "signal_groups": [["锅", "套锅", "锅具"]],
        # The answer may express a verified capacity naturally as “约 1.0L
        # 水壶、约 1.7L 大锅” without repeating the field label “容量”.  Check
        # the structured fact shape rather than imposing a literal phrase.
        "answer_signal_patterns": [r"(?i)(?:\d+(?:\.\d+)?\s*(?:ml|l|毫升|升))"],
    },
    {
        "id": "recommend_budget",
        "kind": "recommendation",
        "question": "预算有限，给两个人露营煮面买一口锅，按现有商品资料推荐一款。",
        "positive": True,
        "route_families": {"recommendation"},
        # This catalogue is known to contain an eligible entry/mid-tier pot for
        # the request.  Assert the maintained structured tier instead of
        # accepting a fluent caveat around a premium-only recommendation.
        "max_result_price_positioning_rank": 1,
        "signal_groups": [["锅", "套锅", "锅具"], ["预算", "入门", "中端", "档位", "价格定位"]],
    },
    {
        "id": "recommend_gift",
        "kind": "recommendation",
        "question": "朋友刚开始露营，我想送一件不容易选错、实用又好收纳的礼物，你会怎么建议？",
        "positive": True,
        "route_families": {"recommendation"},
        "signal_groups": [["推荐", "可以先看", "建议", "这款", "礼物", "送礼"], ["资料", "收纳", "便携", "容量", "重量"]],
    },
    {
        "id": "recommend_water_cup_category_scope",
        "kind": "recommendation",
        "question": "想要一款小巧好带、一个人喝水用的水杯，别太复杂，推荐一款。",
        "positive": True,
        "route_families": {"recommendation"},
        "allowed_result_categories": {"水具", "水杯"},
        "signal_groups": [["水杯", "水壶", "水具", "饮水", "喝水"], ["容量", "重量", "便携", "轻便"]],
    },
    {
        "id": "recommend_griddle",
        "kind": "recommendation",
        "question": "我有卡式炉，想买烤盘，优先推荐资料明确写了好清洁的。",
        "positive": True,
        "route_families": {"recommendation"},
        "signal_groups": [["烤盘", "煎盘"], ["卡式炉", "不粘", "清洁", "资料未"]],
    },
    {
        "id": "negative_heat_constraint",
        "kind": "recommendation",
        "question": "三个人露营想买锅，只要明确支持酒精炉的，不要气炉，推荐一款。",
        "positive": False,
        "route_families": {"recommendation"},
        "must_have_any": [["没有", "未找到", "无法", "暂时"], ["酒精炉", "气炉", "热源"]],
    },
    {
        "id": "negative_pour_over",
        "kind": "recommendation",
        "question": "咖啡器具里请推荐两款真正适合手冲的产品，并说明各自适合谁。",
        "positive": False,
        "route_families": {"recommendation"},
        "must_have_any": [["没有", "未找到", "无法", "暂时"], ["手冲", "不是", "并非"]],
    },
    {
        "id": "comparison_weight_capacity_storage",
        "kind": "comparison",
        "question": "CW-C83 和 CW-C06PRO 哪个更适合两个人周末徒步？请比较重量、容量和收纳负担。",
        "required_skus": ["CW-C83", "CW-C06PRO"],
        "require_choice": True,
        "route_families": {"comparison"},
        "signal_groups": [["重量", "轻", "重"], ["容量", "升", "ml"], ["收纳", "便携", "携带", "体积"]],
    },
    {
        "id": "safety_tent_alcohol",
        "kind": "safety",
        "question": "在帐篷里使用酒精炉安全吗？需要注意什么？",
        "route_families": {"general_chat", "knowledge_base"},
        "must_have_any": [["不要", "禁止", "严禁", "避免", "不建议", "不安全"], ["通风", "帐篷", "易燃", "室外"]],
    },
    {
        "id": "safety_tent_gas",
        "kind": "safety",
        "question": "燃气炉可以在帐篷里使用吗？请直接说安全风险和正确做法。",
        "route_families": {"general_chat", "knowledge_base", "knowledge_base_answer"},
        "must_have_any": [["不要", "禁止", "严禁", "不安全"], ["通风", "一氧化碳", "火灾", "新鲜空气"]],
    },
    {
        "id": "care_burnt_pan",
        "kind": "care",
        "question": "锅底烧糊了，怎么处理才不会继续伤害涂层？",
        "route_families": {"general_chat", "knowledge_base", "product_fact"},
        "must_have_any": [["不要", "避免", "不能", "不建议"], ["冷却", "浸泡", "软布", "海绵", "清洁"]],
    },
    {
        "id": "knowledge_cleaning",
        "kind": "knowledge",
        "question": "根据知识库，锅具的不粘涂层应该如何清洁和保养？",
        "route_families": {"knowledge_base", "knowledge_base_meta", "general_chat"},
        "allow_honest_gap": True,
        "must_have_any": [["清洁", "保养", "涂层", "资料", "没有提供"]],
    },
    {
        "id": "unknown_sku",
        "kind": "unknown",
        "question": "ZX-NOT-FOUND-999 适合一个人露营吗？",
        "sku": "ZX-NOT-FOUND-999",
        "route_families": {"product_fact", "product_bound_qa", "general_chat", "recommendation"},
        "must_have_any": [["没有记录", "未找到", "没有找到", "不存在", "无法"]],
        "must_not_have_any": [["停止加热", "锅具冷却", "温水", "涂层", "烧糊"]],
    },
]


def _post(
    base_url: str,
    path: str,
    payload: dict[str, Any],
    token: str,
    *,
    stream: bool = False,
    parity_scope: str | None = None,
    timeout: float = 300,
) -> tuple[int, dict[str, Any], float]:
    headers = {
        "Content-Type": "application/json; charset=utf-8",
        "Authorization": f"Bearer {token}",
        # Each real case is an independent long-running Flash/RAG request.
        # Closing the client connection after the response prevents a stale
        # keep-alive socket from being reused across cases; it does not alter
        # the HTTP payload, normal/stream contract, or server-side semantics.
        "Connection": "close",
    }
    if parity_scope:
        headers["X-Customer-Service-Parity-Isolation"] = "true"
        headers["X-Customer-Service-Parity-Scope"] = parity_scope
    if stream:
        headers["Accept"] = "text/event-stream"
    request = urllib.request.Request(
        base_url.rstrip("/") + path,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    started = time.perf_counter()
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read().decode("utf-8", errors="replace")
            status = response.status
    except urllib.error.HTTPError as error:
        return error.code, {"error": error.read().decode("utf-8", errors="replace")}, _elapsed(started)
    except Exception as error:  # pragma: no cover - exercised by real HTTP runs
        return 0, {"error": f"{type(error).__name__}: {error}"}, _elapsed(started)
    elapsed = _elapsed(started)
    if not stream:
        try:
            return status, json.loads(raw), elapsed
        except json.JSONDecodeError:
            return status, {"raw": raw}, elapsed
    return status, _parse_sse(raw), elapsed


def _elapsed(started: float) -> float:
    return round((time.perf_counter() - started) * 1000, 1)


def _parse_sse(raw: str) -> dict[str, Any]:
    answer_parts: list[str] = []
    result: dict[str, Any] = {}
    for block in raw.split("\n\n"):
        event = ""
        data = ""
        for line in block.splitlines():
            if line.startswith("event: "):
                event = line[7:]
            elif line.startswith("data: "):
                data = line[6:]
        if not data:
            continue
        try:
            value = json.loads(data)
        except json.JSONDecodeError:
            continue
        if event == "content":
            answer_parts.append(str(value.get("content") or value.get("text") or ""))
        elif event == "meta" and isinstance(value, dict):
            result.update(value)
    result["answer"] = "".join(answer_parts)
    return result


def _answer(body: dict[str, Any]) -> str:
    return str(body.get("answer") or "").strip()


def _result_skus(body: dict[str, Any]) -> list[str]:
    values = body.get("result_skus")
    if not isinstance(values, list):
        values = [
            row.get("sku")
            for row in (body.get("results") or [])
            if isinstance(row, dict)
        ]
    return list(dict.fromkeys(
        str(value or "").strip().upper()
        for value in values
        if str(value or "").strip()
    ))


def _result_weight_g(body: dict[str, Any], sku: str | None = None) -> float | None:
    expected = str(sku or "").strip().upper()
    for row in body.get("results") or []:
        if not isinstance(row, dict):
            continue
        row_sku = str(row.get("sku") or "").strip().upper()
        if expected and row_sku != expected:
            continue
        value = row.get("gross_weight_g")
        if isinstance(value, (int, float)):
            return float(value)
        match = re.search(r"(?<!\d)(\d+(?:\.\d+)?)\s*(?:g|克)\b", str(value or ""), flags=re.I)
        if match:
            return float(match.group(1))
    return None


def _debug(body: dict[str, Any]) -> dict[str, Any]:
    value = body.get("debug")
    return value if isinstance(value, dict) else {}


def _metadata(body: dict[str, Any]) -> dict[str, Any]:
    value = body.get("answer_metadata")
    return value if isinstance(value, dict) else {}


def _route_family(body: dict[str, Any]) -> str:
    debug = _debug(body)
    preplan = debug.get("semantic_preplan")
    if isinstance(preplan, dict) and str(preplan.get("route_family") or "").strip():
        return str(preplan.get("route_family") or "").strip()
    return str(debug.get("route_family") or "").strip()


def _find_models(value: Any, found: set[str] | None = None) -> set[str]:
    found = found if found is not None else set()
    if isinstance(value, dict):
        for key, item in value.items():
            if key in {"model", "api_model", "api_model_override", "llm_model"} and isinstance(item, str):
                if item.strip():
                    found.add(item.strip())
            _find_models(item, found)
    elif isinstance(value, list):
        for item in value:
            _find_models(item, found)
    return found


def _contains_any(answer: str, terms: tuple[str, ...] | list[str]) -> bool:
    return any(term and term in answer for term in terms)


def _price_positioning_rank(value: Any) -> int | None:
    """Normalize the maintained catalogue tier used by the budget contract."""
    text = re.sub(r"\s+", " ", str(value or "")).strip().casefold()
    if not text:
        return None
    if any(term in text for term in ("高端", "premium", "high-end", "high end")):
        return 2
    if any(term in text for term in ("中端", "mid-range", "mid range", "mid")):
        return 1
    if any(
        term in text
        for term in ("入门", "基础", "亲民", "affordable", "entry", "value", "性价比")
    ):
        return 0
    return None


def _check_groups(answer: str, groups: list[list[str]] | None) -> list[str]:
    failures: list[str] = []
    for index, group in enumerate(groups or [], start=1):
        if not _contains_any(answer, group):
            failures.append(f"answer_signal_group_{index}")
    return failures


def _check_patterns(answer: str, patterns: list[str] | None) -> list[str]:
    failures: list[str] = []
    for index, pattern in enumerate(patterns or [], start=1):
        try:
            matched = bool(re.search(str(pattern or ""), answer, flags=re.I))
        except re.error:
            matched = False
        if not matched:
            failures.append(f"answer_signal_pattern_{index}")
    return failures


def _same_sku_answer_audit_contract(body: dict[str, Any]) -> list[str]:
    """Require the service's final answer audit for every product result.

    The release gate must verify more than a fluent answer and a non-empty
    result list.  The service's final audit is the authoritative same-SKU
    binding after RAG selection, answer writing, and post-processing.  For
    knowledge/safety/no-match turns there may be no product evidence, so a
    missing audit is only an error when the response actually returns SKUs.
    """
    result_skus = set(_result_skus(body))
    if not result_skus:
        return []
    failures: list[str] = []
    metadata = _metadata(body)
    audit = metadata.get("final_answer_audit")
    if not isinstance(audit, dict):
        return ["same_sku_final_answer_audit_missing"]
    if audit.get("passed") is not True:
        failures.append("same_sku_final_answer_audit_failed")
    if audit.get("coverage_complete") is not True:
        failures.append("same_sku_answer_coverage_incomplete")
    audited_result_skus = {
        str(value or "").strip().upper()
        for value in (audit.get("result_skus") or [])
        if str(value or "").strip()
    }
    if audited_result_skus != result_skus:
        failures.append(
            f"same_sku_audit_result_mismatch:{sorted(audited_result_skus)}"
        )
    evidence_skus = {
        str(value or "").strip().upper()
        for value in (audit.get("evidence_skus") or [])
        if str(value or "").strip()
    }
    if not result_skus.issubset(evidence_skus):
        failures.append(
            f"same_sku_audit_evidence_missing:{sorted(result_skus - evidence_skus)}"
        )
    bundle_skus = {
        str(value or "").strip().upper()
        for value in (metadata.get("evidence_bundle_skus") or [])
        if str(value or "").strip()
    }
    if bundle_skus and not result_skus.issubset(bundle_skus):
        failures.append(
            f"same_sku_evidence_bundle_missing:{sorted(result_skus - bundle_skus)}"
        )
    if (
        "semantic_answer_coverage_complete" in metadata
        and metadata.get("semantic_answer_coverage_complete") is not True
    ):
        failures.append("semantic_answer_coverage_not_complete")
    return failures


def _identity_contract(body: dict[str, Any], expected: set[str]) -> list[str]:
    result_skus = set(_result_skus(body))
    if not expected:
        return []
    if result_skus != expected:
        return [f"result_skus_not_exact:{sorted(result_skus)}"]
    for row in body.get("results") or []:
        if isinstance(row, dict) and str(row.get("sku") or "").strip().upper() not in expected:
            return ["result_row_cross_sku"]
    for item in body.get("evidence") or []:
        if isinstance(item, dict) and str(item.get("sku") or "").strip().upper() not in expected:
            return ["evidence_cross_sku"]
    return []


def _basic_contract(body: dict[str, Any], status: int, case: dict[str, Any]) -> list[str]:
    failures: list[str] = []
    if status != 200:
        failures.append(f"http_status:{status}")
        return failures
    answer = _answer(body)
    if not answer:
        failures.append("empty_answer")
    leaks = [term for term in INTERNAL_ANSWER_TERMS if term.casefold() in answer.casefold()]
    if leaks:
        failures.append("internal_answer_leak:" + ",".join(leaks))
    family = _route_family(body)
    allowed_families = set(case.get("route_families") or [])
    if allowed_families and family and family not in allowed_families:
        failures.append(f"unexpected_route_family:{family}")
    models = _find_models(body)
    if models and not any("flash" in model.casefold() for model in models):
        failures.append("semantic_model_not_flash:" + ",".join(sorted(models)))
    failures.extend(_same_sku_answer_audit_contract(body))
    for group_index, group in enumerate(case.get("must_not_have_any") or [], start=1):
        if _contains_any(answer, tuple(group)):
            failures.append(f"answer_forbidden_signal_{group_index}")
    return failures


def _evaluate_case(case: dict[str, Any], status: int, body: dict[str, Any]) -> dict[str, Any]:
    answer = _answer(body)
    failures = _basic_contract(body, status, case)
    result_skus = _result_skus(body)
    failures.extend(_check_patterns(answer, case.get("answer_signal_patterns")))
    kind = str(case.get("kind") or "")
    if kind == "sku_fact":
        failures.extend(_identity_contract(body, {str(case["sku"]).upper()}))
        failures.extend(_check_groups(answer, case.get("signal_groups")))
    elif kind == "unknown":
        if result_skus:
            failures.append("unknown_sku_returned_product")
        if not _contains_any(answer, tuple(case.get("must_have_any", [[]])[0])):
            failures.append("unknown_sku_not_disclosed")
    elif kind == "recommendation":
        positive = bool(case.get("positive"))
        if positive and not result_skus:
            failures.append("positive_recommendation_has_no_result")
        if not positive and result_skus:
            failures.append("hard_no_match_returned_result")
        allowed_categories = {
            str(item or "").strip()
            for item in (case.get("allowed_result_categories") or [])
            if str(item or "").strip()
        }
        if allowed_categories:
            result_categories = {
                str(row.get("category") or "").strip()
                for row in (body.get("results") or [])
                if isinstance(row, dict) and str(row.get("category") or "").strip()
            }
            if not result_categories or not result_categories.issubset(allowed_categories):
                failures.append(f"result_category_out_of_scope:{sorted(result_categories)}")
        if case.get("max_result_price_positioning_rank") is not None and result_skus:
            maximum_rank = int(case["max_result_price_positioning_rank"])
            result_tiers = [
                str(row.get("price_positioning") or "").strip()
                for row in (body.get("results") or [])
                if isinstance(row, dict)
            ]
            result_ranks = [_price_positioning_rank(tier) for tier in result_tiers]
            if not result_ranks or any(rank is None for rank in result_ranks):
                failures.append("budget_result_missing_structured_price_positioning")
            elif any(rank > maximum_rank for rank in result_ranks if rank is not None):
                failures.append(f"budget_result_tier_too_high:{result_tiers}")
        failures.extend(_check_groups(answer, case.get("signal_groups")))
        for group_index, group in enumerate(case.get("must_have_any") or [], start=1):
            if not _contains_any(answer, tuple(group)):
                failures.append(f"answer_required_signal_{group_index}")
    elif kind == "comparison":
        expected = {str(sku).upper() for sku in case.get("required_skus") or []}
        if not expected.issubset(set(result_skus)):
            failures.append(f"comparison_missing_participant:{sorted(expected - set(result_skus))}")
        if re.search(
            r"按已知资料对比|字段[:：]|^[-*]\s*\S+[:：]|^(?:按|根据).{0,16}(?:资料|记录).{0,16}(?:容量|重量|收纳)",
            answer,
            flags=re.MULTILINE,
        ):
            failures.append("comparison_mechanical_dump")
        if case.get("require_choice"):
            choice_sku = str(_metadata(body).get("final_choice_sku") or "").strip().upper()
            if not choice_sku or choice_sku not in result_skus:
                failures.append("comparison_missing_final_choice")
            else:
                choice_names = {
                    str(row.get("product_name_cn") or row.get("product_name") or "").strip()
                    for row in (body.get("results") or [])
                    if isinstance(row, dict)
                    and str(row.get("sku") or "").strip().upper() == choice_sku
                    and str(row.get("product_name_cn") or row.get("product_name") or "").strip()
                }
                if choice_sku not in answer and not any(name in answer for name in choice_names):
                    failures.append("comparison_choice_not_explained")
        failures.extend(_check_groups(answer, case.get("signal_groups")))
    elif kind in {"safety", "care"}:
        failures.extend(_check_groups(answer, case.get("must_have_any")))
        if result_skus:
            failures.append("safety_or_care_leaked_product_result")
    elif kind == "knowledge":
        if result_skus:
            failures.append("knowledge_query_returned_product_result")
        if not _contains_any(answer, tuple(case.get("must_have_any", [[]])[0])):
            failures.append("knowledge_answer_not_actionable_or_honest_gap")
        if case.get("allow_honest_gap"):
            source = str(_metadata(body).get("source") or "").strip()
            evidence_status = str(_metadata(body).get("evidence_status") or "").strip()
            if source != "semantic_knowledge_base_rag" and evidence_status != "matched":
                if not _contains_any(answer, GAP_TERMS):
                    failures.append("knowledge_scope_gap_not_honest")
    return {
        "id": case["id"],
        "kind": kind,
        "status": status,
        "pass": not failures,
        "failures": list(dict.fromkeys(failures)),
        "answer": answer,
        "result_skus": result_skus,
        "answer_type": body.get("answer_type"),
        "route_family": _route_family(body),
        "source": _metadata(body).get("source"),
        "models": sorted(_find_models(body)),
        "response": body,
    }


def _print_result(result: dict[str, Any]) -> None:
    marker = "PASS" if result["pass"] else "FAIL"
    print(json.dumps({
        "case": result["id"],
        "status": result["status"],
        "pass": result["pass"],
        "failures": result["failures"],
        "answer_type": result["answer_type"],
        "route_family": result["route_family"],
        "source": result["source"],
        "result_skus": result["result_skus"],
        "answer": result["answer"],
    }, ensure_ascii=False), flush=True)
    print(f"[{marker}] {result['id']}", flush=True)


def _run_sequence(base_url: str, token: str) -> dict[str, Any]:
    first_status, first_body, first_elapsed = _post(
        base_url,
        "/api/customer-service/ask?debug=true",
        {"question": "预算有限，给两个人露营煮面选一口锅，推荐一款。"},
        token,
    )
    conversation_id = first_body.get("conversation_id") if isinstance(first_body, dict) else None
    first_skus = set(_result_skus(first_body))
    payload: dict[str, Any] = {
        "question": "还有更轻一点、也能烧水的备选吗？不要重复刚才那款。",
    }
    if conversation_id:
        payload["conversation_id"] = conversation_id
    second_status, second_body, second_elapsed = _post(
        base_url,
        "/api/customer-service/ask?debug=true",
        payload,
        token,
    )
    second_skus = set(_result_skus(second_body))
    first_weight = _result_weight_g(first_body, next(iter(first_skus), None))
    second_weight = _result_weight_g(second_body, next(iter(second_skus), None))
    failures: list[str] = []
    if first_status != 200 or not first_skus:
        failures.append("context_first_turn_no_recommendation")
    if second_status != 200 or not _answer(second_body):
        failures.append(f"context_second_http_or_empty:{second_status}")
    if first_skus & second_skus:
        failures.append(f"alternative_repeated_prior_sku:{sorted(first_skus & second_skus)}")
    if not second_skus:
        failures.append("alternative_has_no_candidate")
    if first_weight is None or second_weight is None:
        failures.append("alternative_missing_structured_weight")
    elif second_weight >= first_weight:
        failures.append(f"alternative_not_lighter:{second_weight}>={first_weight}")
    if any(term.casefold() in _answer(second_body).casefold() for term in INTERNAL_ANSWER_TERMS):
        failures.append("context_internal_answer_leak")
    result = {
        "id": "context_alternative_exclusion",
        "pass": not failures,
        "failures": failures,
        "first_status": first_status,
        "second_status": second_status,
        "first_elapsed_ms": first_elapsed,
        "second_elapsed_ms": second_elapsed,
        "first_result_skus": sorted(first_skus),
        "second_result_skus": sorted(second_skus),
        "first_weight_g": first_weight,
        "second_weight_g": second_weight,
        "first_answer": _answer(first_body),
        "second_answer": _answer(second_body),
        "first_response": first_body,
        "second_response": second_body,
    }
    print(json.dumps({
        "sequence": result["id"],
        "pass": result["pass"],
        "failures": result["failures"],
        "first_result_skus": result["first_result_skus"],
        "second_result_skus": result["second_result_skus"],
        "first_answer": result["first_answer"],
        "second_answer": result["second_answer"],
    }, ensure_ascii=False), flush=True)
    return result


def _run_field_then_alternative_sequence(base_url: str, token: str) -> dict[str, Any]:
    first_status, first_body, first_elapsed = _post(
        base_url,
        "/api/customer-service/ask?debug=true",
        {"question": "两个人周末露营烧水煮面，预算有限，推荐一款锅。"},
        token,
    )
    conversation_id = first_body.get("conversation_id") if isinstance(first_body, dict) else None
    second_payload: dict[str, Any] = {"question": "上面那款重量多少？"}
    if conversation_id:
        second_payload["conversation_id"] = conversation_id
    second_status, second_body, second_elapsed = _post(
        base_url,
        "/api/customer-service/ask?debug=true",
        second_payload,
        token,
    )
    third_payload: dict[str, Any] = {"question": "有没有比它更轻的？"}
    if conversation_id:
        third_payload["conversation_id"] = conversation_id
    third_status, third_body, third_elapsed = _post(
        base_url,
        "/api/customer-service/ask?debug=true",
        third_payload,
        token,
    )

    first_skus = _result_skus(first_body)
    second_skus = _result_skus(second_body)
    third_skus = _result_skus(third_body)
    first_sku = first_skus[0] if len(first_skus) == 1 else None
    third_sku = third_skus[0] if len(third_skus) == 1 else None
    first_weight = _result_weight_g(first_body, first_sku)
    third_weight = _result_weight_g(third_body, third_sku)
    third_debug = _debug(third_body)
    third_preplan = third_debug.get("semantic_preplan") if isinstance(third_debug.get("semantic_preplan"), dict) else {}
    failures: list[str] = []
    if first_status != 200 or not first_sku:
        failures.append("field_sequence_first_turn_no_single_recommendation")
    if second_status != 200 or second_skus != first_skus:
        failures.append(f"field_sequence_fact_not_bound:{first_skus}/{second_skus}")
    if third_status != 200 or not third_sku:
        failures.append("field_sequence_alternative_missing")
    if set(first_skus) & set(third_skus):
        failures.append(f"field_sequence_alternative_repeated:{sorted(set(first_skus) & set(third_skus))}")
    if first_weight is None or third_weight is None:
        failures.append("field_sequence_missing_structured_weight")
    elif third_weight >= first_weight:
        failures.append(f"field_sequence_not_lighter:{third_weight}>={first_weight}")
    if str(third_preplan.get("recommendation_followup_action") or "").strip() != "alternative":
        failures.append("field_sequence_semantic_action_not_alternative")
    if str(third_preplan.get("context_usage") or "").strip() != "recommendation_context":
        failures.append("field_sequence_scope_not_reopened")
    if any(term.casefold() in _answer(third_body).casefold() for term in INTERNAL_ANSWER_TERMS):
        failures.append("field_sequence_internal_answer_leak")

    result = {
        "id": "context_field_then_lighter_alternative",
        "pass": not failures,
        "failures": failures,
        "first_status": first_status,
        "second_status": second_status,
        "third_status": third_status,
        "first_elapsed_ms": first_elapsed,
        "second_elapsed_ms": second_elapsed,
        "third_elapsed_ms": third_elapsed,
        "first_result_skus": first_skus,
        "second_result_skus": second_skus,
        "third_result_skus": third_skus,
        "first_weight_g": first_weight,
        "third_weight_g": third_weight,
        "first_answer": _answer(first_body),
        "second_answer": _answer(second_body),
        "third_answer": _answer(third_body),
        "first_response": first_body,
        "second_response": second_body,
        "third_response": third_body,
    }
    print(json.dumps({
        "sequence": result["id"],
        "pass": result["pass"],
        "failures": result["failures"],
        "first_result_skus": first_skus,
        "second_result_skus": second_skus,
        "third_result_skus": third_skus,
        "first_weight_g": first_weight,
        "third_weight_g": third_weight,
        "first_answer": result["first_answer"],
        "second_answer": result["second_answer"],
        "third_answer": result["third_answer"],
    }, ensure_ascii=False), flush=True)
    return result


def _run_parity(base_url: str, token: str) -> dict[str, Any]:
    question = "预算不宽裕，想给两个人露营煮面选一口轻便的锅，帮我按商品资料挑一款。"
    parity_scope = f"semantic-rag-acceptance-{uuid.uuid4().hex}"
    normal_status, normal_body, normal_elapsed = _post(
        base_url,
        "/api/customer-service/ask?debug=true",
        {"question": question},
        token,
        parity_scope=parity_scope,
    )
    stream_status, stream_body, stream_elapsed = _post(
        base_url,
        "/api/customer-service/ask-stream",
        {"question": question},
        token,
        stream=True,
        parity_scope=parity_scope,
    )
    failures: list[str] = []
    if normal_status != 200 or stream_status != 200:
        failures.append(f"parity_http:{normal_status}/{stream_status}")
    if _answer(normal_body) != _answer(stream_body):
        failures.append("normal_stream_answer_mismatch")
    if _result_skus(normal_body) != _result_skus(stream_body):
        failures.append("normal_stream_result_sku_mismatch")
    if normal_body.get("answer_type") and stream_body.get("answer_type") and normal_body.get("answer_type") != stream_body.get("answer_type"):
        failures.append("normal_stream_answer_type_mismatch")
    result = {
        "id": "normal_stream_parity",
        "pass": not failures,
        "failures": failures,
        "normal_status": normal_status,
        "stream_status": stream_status,
        "normal_elapsed_ms": normal_elapsed,
        "stream_elapsed_ms": stream_elapsed,
        "normal_result_skus": _result_skus(normal_body),
        "stream_result_skus": _result_skus(stream_body),
        "normal_answer": _answer(normal_body),
        "stream_answer": _answer(stream_body),
        "normal_response": normal_body,
        "stream_response": stream_body,
    }
    print(json.dumps({
        "sequence": result["id"],
        "pass": result["pass"],
        "failures": result["failures"],
        "normal_result_skus": result["normal_result_skus"],
        "stream_result_skus": result["stream_result_skus"],
        "same_answer": result["normal_answer"] == result["stream_answer"],
        "normal_answer": result["normal_answer"],
        "stream_answer": result["stream_answer"],
    }, ensure_ascii=False), flush=True)
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:8001")
    parser.add_argument("--report-dir", default="reports")
    parser.add_argument("--username", default="admin")
    parser.add_argument("--password", default="admin123")
    args = parser.parse_args()

    login_status, login_body, _ = _post(
        args.base_url,
        "/api/auth/login",
        {"username": args.username, "password": args.password},
        "",
    )
    if login_status != 200 or not login_body.get("access_token"):
        print(json.dumps({"login_status": login_status, "login": login_body}, ensure_ascii=False))
        return 2
    token = str(login_body["access_token"])
    started = time.perf_counter()
    case_results: list[dict[str, Any]] = []
    for case in CASES:
        status, body, elapsed = _post(
            args.base_url,
            "/api/customer-service/ask?debug=true",
            {"question": case["question"]},
            token,
        )
        result = _evaluate_case(case, status, body)
        result["elapsed_ms"] = elapsed
        case_results.append(result)
        _print_result(result)
    sequence_results = [
        _run_sequence(args.base_url, token),
        _run_field_then_alternative_sequence(args.base_url, token),
        _run_parity(args.base_url, token),
    ]
    failures = [
        result["id"]
        for result in case_results
        if not result["pass"]
    ] + [
        result["id"]
        for result in sequence_results
        if not result["pass"]
    ]
    elapsed_values = [
        result["elapsed_ms"]
        for result in case_results
        if isinstance(result.get("elapsed_ms"), (int, float))
    ] + [
        elapsed
        for result in sequence_results
        for key, elapsed in result.items()
        if str(key).endswith("_elapsed_ms")
        if isinstance(elapsed, (int, float))
    ]
    report = {
        "contract": {
            "name": "semantic_rag_release_contract_v1",
            "automatic_checks": [
                "HTTP 200 and non-empty answer",
                "no internal pipeline leakage in customer answer",
                "semantic route/model metadata when exposed",
                "same-SKU identity binding for explicit product facts",
                "same-SKU final answer audit and evidence-bundle consistency for product results",
                "recommendation result/no-match semantics",
                "structured budget tier respects an available lower-tier fit",
                "comparison participants and natural prose shape",
                "safety/care action plus prohibited-action coverage",
                "context alternative exclusion",
                "three-turn product-field binding then lighter alternative",
                "normal/stream answer and result identity parity",
            ],
            "not_used": [
                "legacy non-RAG acceptance thresholds",
                "fixed opening phrases",
                "minimum answer length as usefulness proxy",
                "literal keyword evidence gate for natural questions",
            ],
        },
        "run": {
            "started_at": datetime.now(timezone.utc).isoformat(),
            "base_url": args.base_url,
            "case_count": len(CASES),
            "total_elapsed_ms": round((time.perf_counter() - started) * 1000, 1),
            "latency_ms": {
                "count": len(elapsed_values),
                "median": sorted(elapsed_values)[len(elapsed_values) // 2] if elapsed_values else None,
                "max": max(elapsed_values) if elapsed_values else None,
            },
        },
        "overall_pass": not failures,
        "failures": failures,
        "cases": case_results,
        "sequences": sequence_results,
    }
    report_dir = Path(args.report_dir)
    report_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    report_path = report_dir / f"semantic_rag_acceptance_{stamp}.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({
        "overall_pass": report["overall_pass"],
        "failures": failures,
        "report": str(report_path),
        "latency_ms": report["run"]["latency_ms"],
    }, ensure_ascii=False), flush=True)
    return 0 if report["overall_pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
