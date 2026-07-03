from __future__ import annotations

import json
import os
import re
import subprocess
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from uuid import uuid4


ROOT = Path(__file__).resolve().parents[1]
ENV_FILE = ROOT / "backend" / ".env.dev"
DEFAULT_BASE_URL = os.getenv("CUSTOMER_SERVICE_API_URL", "http://127.0.0.1:8001")
DEFAULT_REPORT = ROOT / "reports" / "dev_gray_full_reprobe_latest.json"
DEFAULT_TIMEOUT = float(os.getenv("GRAY_PROBE_TIMEOUT", "120"))

RECOMMENDATION_SKU_PREFIXES = ("CW-", "CS-", "CF-", "KD-", "TW-", "MINT-")
Q19_EXCLUDED_SKUS = {"CW-C96-A", "KW-K25-35", "AC-Z08HM", "CW-K31", "GYL-BJ18NB"}
Q04_GRIDDLE_SKUS = {"CF-PG19", "CF-PG19PRO", "CF-PG11-42"}
Q04_STOVE_HINTS = ("炉具方向", "炉子方向", "炉具", "炉子", "烧烤炉")
Q04_GRIDDLE_HINTS = ("烤盘方向", "烤盘", "瓦片烤盘", "CF-PG19")
Q06_MATERIAL_HINTS = ("主体材质", "材质", "3003铝合金")
Q06_NONSTICK_HINTS = ("不粘", "涂层", "无法保证不粘", "未找到不粘或涂层说明")
Q08_COLD_WATER_HINTS = ("冷水", "水温", "未明确标注装冷水限制", "适用水温")
Q08_CAPACITY_HINTS = ("容量", "0.8L", "800ML", "800ml", "8L")
ALCOHOL_SUPPORT_HINTS = ("支持酒精炉", "证据", "同 SKU", "同SKU", "热源")
ALCOHOL_NOT_SUPPORTED_HINTS = ("未显示支持酒精炉", "未明确标注支持酒精炉", "当前资料未显示支持酒精炉")
ALCOHOL_EQUIVALENCE_BAD_HINTS = ("明火直烧支持酒精炉", "卡式炉支持酒精炉", "分体炉支持酒精炉", "一体炉支持酒精炉")


@dataclass(frozen=True)
class ProbeStep:
    label: str
    question: str
    sequence: str


CASE_STEPS: list[ProbeStep] = [
    ProbeStep("q01", "周末和对象去公园野餐，想要一套餐具和锅具，不太重，预算也不太高，有什么推荐？", "q01"),
    ProbeStep("q02", "我一个人去爬山，想带一款能烧水也能简单做饭的锅，推荐哪个？", "q02"),
    ProbeStep("q03", "四个人露营想买一套能做饭的锅具，最好容量大一点，推荐什么？", "q03"),
    ProbeStep("q04", "公司团建十来个人户外烧烤，有没有适合的炉子或者烤盘？", "q04"),
    ProbeStep("q05", "瓦片烤盘到底多大？我想确认能不能放进我的收纳箱。", "q05"),
    ProbeStep("q06", "轻途套锅是什么材质？会不会容易粘锅？", "q06"),
    ProbeStep("q07", "CW-C83 能不能用酒精炉？如果不能就别推荐错了。", "q07"),
    ProbeStep("q08", "你们那个享野水壶可以装冷水吗？容量是多少？", "q08"),
    ProbeStep("q09", "轻途套锅和享野套锅有什么区别？我两个人露营应该买哪个？", "q09"),
    ProbeStep("q10", "行山单锅和激川单锅哪个更适合两个人吃饭？我更想要轻一点但别太小。", "q10"),
    ProbeStep("q11", "CW-C06PRO 和 CW-C19T-37 我更该买哪个，给我讲讲差异。", "q11"),
    ProbeStep("q12", "你家产品里有没有哪些套锅跟 SKU 对不上的？", "q12"),
    ProbeStep("q13", "你们有多少个水壶产品，分别是什么？", "q13"),
    ProbeStep("q14", "有没有适合酒精炉用的锅具？给几个 SKU 我看看。", "q14"),
    ProbeStep("q18", "那个适合三个人吃饭的锅，具体看哪个？", "q18"),
    ProbeStep("q19", "我不要太贵，也不要太重，还要好收纳，买哪个最稳？", "q19"),
    ProbeStep("q20", "你刚才推荐的第一个和第二个，哪个更适合女生一个人背？", "q20"),
    ProbeStep("q21", "你们有没有那种可以直接放在酒精炉上用的锅具？", "q21"),
    ProbeStep("q23", "MINT-CW-C83 能不能用酒精炉？", "q23"),
    ProbeStep("q24", "CW-C01-37 能不能用酒精炉？", "q24"),
    ProbeStep("q25", "CW-S10-A 是不是支持酒精炉？适合几个人？", "q25"),
    ProbeStep("q26", "除了 CW-S10-A，还有没有别的明确支持酒精炉的锅具？", "q26"),
    ProbeStep("q15_t1", "我一个人徒步，想轻一点，推荐一个锅。", "q15"),
    ProbeStep("q15_t2", "它能不能用酒精炉？", "q15"),
    ProbeStep("q15_t3", "有没有更便宜一点的替代？", "q15"),
    ProbeStep("q16_t1", "周末两个人野餐，想买套锅。", "q16"),
    ProbeStep("q16_t2", "为什么推荐这个？", "q16"),
    ProbeStep("q16_t3", "还有没有更轻便一点的？", "q16"),
    ProbeStep("q17_t1", "轻途套锅和享野套锅有什么区别？", "q17"),
    ProbeStep("q17_t2", "那哪个更适合新手？", "q17"),
    ProbeStep("q17_t3", "它们能不能用酒精炉？", "q17"),
    ProbeStep("q20b_t1", "我一个人徒步，想轻一点，推荐两个锅。", "q20b"),
    ProbeStep("q20b_t2", "你刚才推荐的第一个和第二个，哪个更适合女生一个人背？", "q20b"),
    ProbeStep("q22_t1", "你们有哪些锅具产品？", "q22"),
    ProbeStep("q22_t2", "里面哪些支持酒精炉？", "q22"),
    ProbeStep("q22_t3", "有没有更适合两个人的？", "q22"),
]


def load_env(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip() or line.lstrip().startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def json_request(
    method: str,
    url: str,
    *,
    payload: dict[str, Any] | None = None,
    token: str | None = None,
    timeout: float = DEFAULT_TIMEOUT,
) -> tuple[int, bytes]:
    data = None if payload is None else json.dumps(payload, ensure_ascii=False).encode("utf-8")
    headers = {"Content-Type": "application/json; charset=utf-8"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.status, response.read()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read()


def login() -> str:
    env = load_env(ENV_FILE)
    username = env.get("DEFAULT_ADMIN_USERNAME") or env.get("ADMIN_USERNAME")
    password = env.get("DEFAULT_ADMIN_PASSWORD") or env.get("ADMIN_PASSWORD")
    status, body = json_request(
        "POST",
        f"{DEFAULT_BASE_URL.rstrip('/')}/api/auth/login",
        payload={"username": username, "password": password},
        timeout=30,
    )
    if status >= 400:
        raise RuntimeError(body.decode("utf-8", errors="replace"))
    return json.loads(body.decode("utf-8"))["access_token"]


def parse_sse(body: bytes) -> tuple[str, dict[str, Any], dict[str, Any], list[str]]:
    current: dict[str, Any] = {}
    meta: dict[str, Any] = {}
    trace: dict[str, Any] = {}
    answer_parts: list[str] = []
    events: list[str] = []
    for raw_line in body.decode("utf-8", errors="replace").splitlines():
        line = raw_line.strip("\r")
        if not line:
            if current:
                event = str(current.get("event") or "")
                data = current.get("data") or {}
                events.append(event)
                if event in {"answer_delta", "content"}:
                    answer_parts.append(str(data.get("text") or data.get("content") or ""))
                elif event == "meta" and isinstance(data, dict):
                    meta = data
                elif event == "trace" and isinstance(data, dict):
                    trace = data
            current = {}
            continue
        if line.startswith("event:"):
            current["event"] = line.split(":", 1)[1].strip()
        elif line.startswith("data:"):
            raw = line.split(":", 1)[1].strip()
            try:
                current["data"] = json.loads(raw)
            except json.JSONDecodeError:
                current["data"] = {"raw": raw}
    if current:
        events.append(str(current.get("event") or ""))
    answer = "".join(answer_parts).strip() or str(meta.get("answer") or "")
    return answer, meta, trace, events


def ask_stream(token: str, question: str, conversation_id: str | None) -> dict[str, Any]:
    payload: dict[str, Any] = {"question": question}
    if conversation_id:
        payload["conversation_id"] = conversation_id
    started = time.perf_counter()
    status, body = json_request(
        "POST",
        f"{DEFAULT_BASE_URL.rstrip('/')}/api/customer-service/ask-stream",
        payload=payload,
        token=token,
    )
    elapsed_ms = round((time.perf_counter() - started) * 1000, 1)
    if status >= 400:
        return {
            "status": status,
            "question": question,
            "answer": body.decode("utf-8", errors="replace"),
            "answer_type": "",
            "intent": "",
            "primary_intent": "",
            "result_skus": [],
            "metadata_skus": [],
            "candidate_skus": [],
            "retrieved_products_top": [],
            "recommendation_context": None,
            "timing": {},
            "llm_call_count": None,
            "debug_plan": {},
            "debug_trace": {},
            "warnings": [f"http_{status}"],
            "events": [],
            "elapsed_ms_client": elapsed_ms,
            "guard_rebuild_fallback": {},
        }
    answer, meta, trace, events = parse_sse(body)
    debug = meta.get("debug") if isinstance(meta.get("debug"), dict) else {}
    answer_metadata = meta.get("answer_metadata") if isinstance(meta.get("answer_metadata"), dict) else {}
    timing = answer_metadata.get("timing") if isinstance(answer_metadata.get("timing"), dict) else {}
    raw_results = debug.get("raw_results") if isinstance(debug.get("raw_results"), list) else []
    return {
        "status": status,
        "question": question,
        "conversation_id": meta.get("conversation_id"),
        "answer": answer,
        "answer_type": str(meta.get("answer_type") or ""),
        "intent": str(meta.get("intent") or ""),
        "agent_mode": meta.get("agent_mode") or debug.get("agent_mode"),
        "primary_intent": ((debug.get("plan") or {}).get("primary_intent") if isinstance(debug.get("plan"), dict) else "") or "",
        "tasks": [task.get("type") for task in ((debug.get("plan") or {}).get("tasks") or []) if isinstance(task, dict)],
        "result_skus": [str(item).upper() for item in meta.get("result_skus") or [] if str(item or "").strip()],
        "metadata_skus": [str(item).upper() for item in (meta.get("skus") or []) if str(item or "").strip()],
        "candidate_skus": [str(item).upper() for item in (meta.get("candidate_skus") or []) if str(item or "").strip()],
        "retrieved_products_top": [
            {
                "sku": row.get("sku"),
                "name": row.get("product_name_cn") or row.get("name"),
                "category": row.get("category"),
                "score": row.get("score"),
            }
            for row in raw_results[:5]
            if isinstance(row, dict)
        ],
        "recommendation_context": meta.get("recommendation_context"),
        "timing": timing,
        "llm_call_count": timing.get("llm_call_count"),
        "debug_plan": debug.get("plan") if isinstance(debug.get("plan"), dict) else {},
        "debug_trace": trace if isinstance(trace, dict) else {},
        "warnings": meta.get("warnings") or [],
        "events": events,
        "elapsed_ms_client": elapsed_ms,
        "guard_rebuild_fallback": {
            "guard": ((debug.get("trace") or {}).get("guard") if isinstance(debug.get("trace"), dict) else None),
            "fallback": ((debug.get("trace") or {}).get("fallback") if isinstance(debug.get("trace"), dict) else None),
            "rebuild": bool(((debug.get("trace") or {}).get("rebuild")) if isinstance(debug.get("trace"), dict) else False),
            "fast_path": bool(((debug.get("trace") or {}).get("hit_faq_fast_path")) if isinstance(debug.get("trace"), dict) else False),
        },
    }


def run_git(args: list[str]) -> str:
    return subprocess.check_output(args, cwd=ROOT, text=True, encoding="utf-8").strip()


def runtime_info() -> dict[str, Any]:
    status, body = json_request("GET", f"{DEFAULT_BASE_URL.rstrip('/')}/api/health/version", timeout=30)
    payload = {}
    if body:
        try:
            payload = json.loads(body.decode("utf-8"))
        except json.JSONDecodeError:
            payload = {"raw": body.decode("utf-8", errors="replace")}
    return {
        "status": status,
        "payload": payload,
    }


def contains_any(text: str, items: tuple[str, ...] | list[str] | set[str]) -> bool:
    return any(item in text for item in items)


def looks_like_recommendation(result: dict[str, Any]) -> bool:
    return result.get("answer_type") == "recommendation" and result.get("answer_type") != "knowledge_base_answer"


def looks_like_detail(result: dict[str, Any]) -> bool:
    return result.get("answer_type") == "product_detail" and result.get("answer_type") != "knowledge_base_answer"


def is_empty_or_kb(result: dict[str, Any]) -> bool:
    return not str(result.get("answer") or "").strip() or result.get("answer_type") == "knowledge_base_answer"


def classify_result(label: str, result: dict[str, Any], history: dict[str, dict[str, Any]]) -> tuple[str, list[str], str | None, dict[str, Any] | None]:
    answer = str(result.get("answer") or "")
    answer_type = str(result.get("answer_type") or "")
    result_skus = [str(item).upper() for item in result.get("result_skus") or []]
    metadata_skus = [str(item).upper() for item in result.get("metadata_skus") or []]
    issues: list[str] = []
    warning_category: str | None = None
    data_issue: dict[str, Any] | None = None

    if result.get("status") != 200:
        return "fail", [f"http_{result.get('status')}"], None, None
    if not answer.strip():
        return "fail", ["empty_answer"], None, None

    if label == "q04":
        has_stove = contains_any(answer, Q04_STOVE_HINTS) or any(sku.startswith("CS-") or sku.startswith("KD") for sku in result_skus[:3])
        has_griddle = contains_any(answer, Q04_GRIDDLE_HINTS) or any(sku in Q04_GRIDDLE_SKUS for sku in result_skus[:3])
        has_cf_pg19 = "CF-PG19" in result_skus or "CF-PG19" in answer
        if looks_like_recommendation(result) and has_stove and has_griddle and has_cf_pg19:
            return "pass", [], None, None
        issues.append("missing_dual_bucket_answer")
        return "warning", issues, "probe_rule", None

    if label == "q06":
        has_material = contains_any(answer, Q06_MATERIAL_HINTS)
        has_nonstick = contains_any(answer, Q06_NONSTICK_HINTS)
        if looks_like_detail(result) and has_material and has_nonstick:
            return "pass", [], None, None
        if not has_material:
            issues.append("material_missing")
        if not has_nonstick:
            issues.append("nonstick_missing")
        return "warning", issues, "probe_rule", None

    if label == "q08":
        has_cold_water = contains_any(answer, Q08_COLD_WATER_HINTS)
        has_capacity = contains_any(answer, Q08_CAPACITY_HINTS)
        if not (looks_like_detail(result) and has_cold_water and has_capacity):
            if not has_capacity:
                issues.append("capacity_missing")
            if not has_cold_water:
                issues.append("cold_water_missing")
            return "warning", issues, "probe_rule", None
        if re.search(r"\b8L\b", answer, flags=re.I):
            data_issue = {
                "sku": "CW-C76",
                "issue": "容量字段显示 8L，人工看起来可疑",
                "type": "source_data_quality",
                "recommendation": "后续核对商品数据源 / 字段来源",
                "blocking": False,
            }
            return "warning", ["q08_capacity_data_suspect"], "data_field", data_issue
        return "pass", [], None, None

    if label in {"q23", "q24"}:
        if looks_like_detail(result) and contains_any(answer, ALCOHOL_NOT_SUPPORTED_HINTS) and not contains_any(answer, ALCOHOL_EQUIVALENCE_BAD_HINTS):
            return "pass", [], None, None
        return "warning", [f"{label}_overbroad_compatibility"], "probe_rule", None

    if label == "q25":
        has_support = contains_any(answer, ALCOHOL_SUPPORT_HINTS) and "CW-S10-A" in answer
        has_people_or_capacity = contains_any(answer, ("适合", "人数", "双人", "2人", "1400ML", "1.4L", "资料未明确"))
        if looks_like_detail(result) and has_support and has_people_or_capacity:
            return "pass", [], None, None
        return "warning", ["q25_missing_support"], "probe_rule", None

    if label == "q26":
        exclusion_ok = "CW-S10-A" in answer and contains_any(answer, ("暂无其他", "未找到其他", "除了", "只明确找到"))
        if answer_type in {"product_query", "product_detail"} and exclusion_ok:
            return "pass", [], None, None
        return "warning", ["q26_exclusion_regression"], "probe_rule", None

    if label == "q19":
        if looks_like_recommendation(result) and not any(sku in Q19_EXCLUDED_SKUS for sku in result_skus[:5]):
            return "pass", [], None, None
        return "fail", ["q19_candidate_scope_regression"], None, None

    if label == "q03":
        if looks_like_recommendation(result) and result_skus:
            return "pass", [], None, None
        if answer_type in {"product_detail", "knowledge_base_answer"} and contains_any(answer, ("未找到", "没有找到", "暂无")):
            return "warning", ["q03_probe_prompt_scope_drift"], "probe_rule", None
        return "fail", ["q03_recommendation_regression"], None, None

    if label == "q20":
        if answer_type == "clarification":
            return "pass", [], None, None
        return "fail", ["q20_should_clarify_without_context"], None, None

    if label == "q10":
        if contains_any(answer, ("行山单锅", "CW-C93")) and contains_any(answer, ("激川单锅", "CW-S10-1", "CW-S10-A")):
            return "pass", [], None, None
        return "fail", ["q10_compare_regression"], None, None

    if label == "q11":
        if contains_any(answer, ("CW-C06PRO",)) and contains_any(answer, ("CW-C19T-37",)):
            return "pass", [], None, None
        return "fail", ["q11_compare_regression"], None, None

    if label == "q13":
        if contains_any(answer, ("水壶", "壶")) and re.search(r"\d+", answer):
            return "pass", [], None, None
        return "fail", ["q13_catalog_count_regression"], None, None

    if label == "q14":
        if is_empty_or_kb(result):
            return "fail", ["q14_kb_fallback"], None, None
        if contains_any(answer, ALCOHOL_EQUIVALENCE_BAD_HINTS):
            return "fail", ["q14_overbroad_alcohol_compatibility"], None, None
        if result_skus or contains_any(answer, ("未找到", "暂无")):
            return "pass", [], None, None
        return "fail", ["q14_missing_alcohol_evidence"], None, None

    if label == "q21":
        if is_empty_or_kb(result):
            return "fail", ["q21_kb_fallback"], None, None
        if result_skus or contains_any(answer, ("酒精炉", "锅具")):
            return "pass", [], None, None
        return "fail", ["q21_missing_alcohol_cookware_list"], None, None

    if label == "q22_t2":
        if is_empty_or_kb(result):
            return "fail", ["q22_t2_kb_fallback"], None, None
        if contains_any(answer, ("酒精炉", "支持")) or result_skus:
            return "pass", [], None, None
        return "fail", ["q22_t2_filter_regression"], None, None

    if label == "q15_t1":
        if looks_like_recommendation(result) and result_skus:
            return "pass", [], None, None
        return "fail", ["q15_t1_recommendation_regression"], None, None

    if label == "q15_t2":
        prior = history.get("q15_t1") or {}
        prior_sku = ((prior.get("result_skus") or [None])[0] if isinstance(prior.get("result_skus"), list) else None)
        if looks_like_detail(result) and prior_sku and prior_sku in answer:
            return "pass", [], None, None
        return "fail", ["q15_t2_context_regression"], None, None

    if label == "q15_t3":
        if looks_like_recommendation(result) and "SPIRIT STOVE" not in answer.upper() and answer_type != "knowledge_base_answer":
            return "pass", [], None, None
        return "fail", ["q15_t3_followup_regression"], None, None

    if label == "q16_t1":
        if looks_like_recommendation(result) and not bool((result.get("guard_rebuild_fallback") or {}).get("fast_path")):
            return "pass", [], None, None
        return "fail", ["q16_t1_fast_path_regression"], None, None

    if label == "q20b_t2":
        if answer_type != "clarification" and answer_type != "knowledge_base_answer":
            return "pass", [], None, None
        return "fail", ["q20b_context_compare_regression"], None, None

    if label in {"q09", "q17_t1"}:
        if contains_any(answer, ("轻途", "CW-C06PRO")) and contains_any(answer, ("享野", "CW-C76", "享野套锅")):
            return "pass", [], None, None
        return "fail", [f"{label}_compare_regression"], None, None

    if label in {"q17_t3", "q07", "q24", "q23"}:
        if "酒精炉" in answer and answer_type != "knowledge_base_answer":
            return "pass", [], None, None
        return "fail", [f"{label}_alcohol_regression"], None, None

    if label.startswith("q22_"):
        if answer_type != "knowledge_base_answer":
            return "pass", [], None, None
        return "fail", [f"{label}_kb_fallback"], None, None

    if label.startswith("q16_") or label.startswith("q17_") or label.startswith("q20b_"):
        if answer_type != "knowledge_base_answer" and answer.strip():
            return "pass", [], None, None
        return "fail", [f"{label}_multiturn_regression"], None, None

    if label in {"q01", "q02", "q18"}:
        if looks_like_recommendation(result) and result_skus:
            return "pass", [], None, None
        return "fail", [f"{label}_recommendation_regression"], None, None

    if label in {"q05", "q12"}:
        if answer.strip() and answer_type != "knowledge_base_answer":
            return "pass", [], None, None
        return "fail", [f"{label}_detail_regression"], None, None

    return ("pass", [], None, None) if answer_type != "knowledge_base_answer" else ("fail", [f"{label}_kb_fallback"], None, None)


def summarize(results: list[dict[str, Any]]) -> dict[str, Any]:
    summary = {
        "total_requests": len(results),
        "pass": 0,
        "warning": 0,
        "fail": 0,
        "blocking_fail": 0,
        "warning_categories": {
            "business": 0,
            "data_field": 0,
            "probe_rule": 0,
            "performance": 0,
        },
    }
    for result in results:
        verdict = result.get("verdict")
        if verdict == "pass":
            summary["pass"] += 1
        elif verdict == "warning":
            summary["warning"] += 1
            category = str(result.get("warning_category") or "probe_rule")
            if category not in summary["warning_categories"]:
                summary["warning_categories"][category] = 0
            summary["warning_categories"][category] += 1
        elif verdict == "blocking_fail":
            summary["blocking_fail"] += 1
        else:
            summary["fail"] += 1
    return summary


def run_probe() -> dict[str, Any]:
    token = login()
    results: list[dict[str, Any]] = []
    history: dict[str, dict[str, Any]] = {}
    sequence_conversations: dict[str, str] = {}
    data_issues: list[dict[str, Any]] = []

    for index, step in enumerate(CASE_STEPS, start=1):
        conversation_id = sequence_conversations.get(step.sequence)
        raw = ask_stream(token, step.question, conversation_id)
        if raw.get("conversation_id"):
            sequence_conversations[step.sequence] = str(raw["conversation_id"])
        verdict, issues, warning_category, data_issue = classify_result(step.label, raw, history)
        record = {
            **raw,
            "label": step.label,
            "verdict": verdict,
            "issues": issues,
            "warning_category": warning_category,
        }
        if data_issue:
            data_issues.append(data_issue)
        history[step.label] = record
        results.append(record)
        print(
            json.dumps(
                {
                    "index": index,
                    "total": len(CASE_STEPS),
                    "label": step.label,
                    "verdict": verdict,
                    "answer_type": raw.get("answer_type"),
                    "elapsed_ms_client": raw.get("elapsed_ms_client"),
                },
                ensure_ascii=False,
            ),
            flush=True,
        )

    timings = [
        {
            "label": item["label"],
            "question": item["question"],
            "total_duration_ms": (item.get("timing") or {}).get("total_duration_ms") or item.get("elapsed_ms_client"),
            "llm_duration_ms": (item.get("timing") or {}).get("llm_duration_ms"),
            "llm_call_count": item.get("llm_call_count"),
        }
        for item in results
    ]
    slow_top5 = sorted(timings, key=lambda item: float(item.get("total_duration_ms") or 0), reverse=True)[:5]
    runtime = runtime_info()
    git = {
        "branch": run_git(["git", "branch", "--show-current"]),
        "head": run_git(["git", "rev-parse", "HEAD"]),
        "origin_dev": run_git(["git", "rev-parse", "origin/dev"]),
        "status": run_git(["git", "status", "--short"]),
    }
    report = {
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "git": git,
        "runtime": runtime,
        "summary": summarize(results),
        "data_issues": data_issues,
        "slow_top5": slow_top5,
        "results": results,
    }
    return report


def main() -> int:
    report = run_probe()
    commit_short = report["git"]["head"][:8]
    timestamp = time.strftime("%Y%m%d_%H%M%S")
    out_path = DEFAULT_REPORT.with_name(f"dev_gray_full_reprobe_{timestamp}_{commit_short}.json")
    out_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({
        "report": str(out_path),
        "summary": report["summary"],
        "data_issues": report["data_issues"],
    }, ensure_ascii=False, indent=2))
    return 0 if report["summary"]["fail"] == 0 and report["summary"]["blocking_fail"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
