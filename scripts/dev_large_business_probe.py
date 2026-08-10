from __future__ import annotations

import importlib.util
import json
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request
from collections import Counter, defaultdict
from collections.abc import Callable, Iterable, Iterator, Sequence
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
BACKEND_ROOT = ROOT / "backend"
ENV_FILE = BACKEND_ROOT / ".env.dev"
DEFAULT_BASE_URL = os.getenv("CUSTOMER_SERVICE_API_URL", "http://127.0.0.1:8001")
DEFAULT_REPORT_DIR = ROOT / "reports"
DEFAULT_TIMEOUT = float(os.getenv("LARGE_PROBE_TIMEOUT", "150"))
DEFAULT_BATCH_SIZE = int(os.getenv("LARGE_PROBE_BATCH_SIZE", "25"))
DEFAULT_BATCH_SLEEP_SECONDS = float(os.getenv("LARGE_PROBE_BATCH_SLEEP_SECONDS", "2"))
DEFAULT_RATE_LIMIT_RETRIES = int(os.getenv("LARGE_PROBE_RATE_LIMIT_RETRIES", "2"))
DEFAULT_RATE_LIMIT_BACKOFF_SECONDS = float(os.getenv("LARGE_PROBE_RATE_LIMIT_BACKOFF_SECONDS", "2"))

NOT_FOUND_HINTS = ("没有找到", "未找到", "没找到", "暂无", "找不到")
FAQ_HINTS = ("七天无理由", "质保", "售后", "退换", "客服", "购买渠道")
PERSON_HINTS = ("适合", "人数", "几个人", "几人", "双人", "多人")
COLD_WATER_HINTS = ("冷水", "水温", "装冷水", "适用水温")
HYDRATION_HINTS = ("补水", "烧水", "饮水", "热饮")
ALCOHOL_HINTS = ("酒精炉", "酒精")
COMPARE_HINTS = ("区别", "差异", "对比", "哪个好", "推荐选")
NON_PEOPLE_CATEGORIES = {"配件", "桌椅", "咖啡器具", "茶具"}
PARITY_CASE_LIMIT = 30

SKU_RE = re.compile(
    r"(?<![A-Za-z0-9])("
    r"(?:[A-Za-z]{1,6}(?:[-_][A-Za-z0-9\u4e00-\u9fff]{1,40})+)"
    r"|(?:[A-Za-z]{1,6}\d{2,12}[A-Za-z0-9\u4e00-\u9fff]{0,12})"
    r")(?![A-Za-z0-9])"
)

SCENARIO_QUESTIONS = [
    "一个人徒步露营，想尽量轻一点，推荐哪个锅更稳妥？",
    "双人野餐想带个不太重的套锅，推荐哪款？",
    "三个人露营要能煮面也能煮汤，推荐什么锅具？",
    "四个人露营想做火锅，锅具容量大一点的推荐哪个？",
    "五六个人家庭露营，想选一套稳一点又别太难收纳的锅具。",
    "七八个人营地聚餐，想要主锅具，不要配件，推荐哪个？",
    "十来个人公司团建，除了烧烤还要烧水，炉具怎么选？",
    "新手第一次露营，想买一套不容易踩坑的锅具，推荐哪套？",
    "女生一个人背着走，想选轻一点的小锅，有推荐吗？",
    "长途徒步想轻量化，但还得能简单煮饭，推荐哪个锅？",
    "低预算露营，想买个最稳的锅具主商品，不要水壶不要配件。",
    "预算一般，但想要好收纳又不太重的双人锅具，推荐哪个？",
    "野餐主要烧水泡面，推荐单锅还是套锅？",
    "想带去露营煮汤和煮面，三四个人用，推荐哪个锅？",
    "两个人露营偏爱火锅场景，锅具要稳一点，推荐哪个？",
    "单人骑行露营，空间很紧张，推荐一个最省体积的锅。",
    "新手家庭露营，想先买一个不容易出错的主锅具。",
    "三口之家周末近郊露营，锅具别太重但容量别太小。",
    "女生新手想自己带去公园野餐，哪个锅更好上手？",
    "长途徒步只想带一个锅，能烧水也能做简单餐食。",
    "露营烧烤场景，炉具和烤盘怎么搭更合适？",
    "营地煮咖啡顺便做早餐，推荐什么炊具组合最稳？",
    "两个人海边露营，风大一点，炉具该怎么选？",
    "冬天露营想煮热汤，锅具优先容量还是稳固？给个推荐。",
    "多人露营想省收纳空间，套锅和单锅怎么选？",
    "一个人背包露营不想太贵，推荐轻一点的主锅具。",
    "双人徒步露营，希望锅具和收纳都别太占地方。",
    "三个人新手露营，想要稳一点又别太重的锅具。",
    "四个人自驾露营，要做正餐，推荐一个靠谱主锅具。",
    "五六个人露营做火锅和煮汤都要兼顾，推荐什么？",
    "家庭露营偏向煮饭，不想带太多件，推荐一套锅。",
    "营地早餐场景想煎东西，锅具和烤盘哪个更合适？",
    "女生一个人公园野餐，想轻一点又能烧水的炊具。",
    "预算有限但想一步到位买主锅具，哪个最稳？",
    "户外新手只想先买一个锅，不想太重也不想太贵。",
    "长途自驾露营，人数四五个，锅具更看重容量和稳定性。",
    "骑行露营只带最核心的锅具，推荐一个够用的。",
    "双人野餐偏轻食和泡面，推荐什么锅具更合适？",
    "营地聚餐想主打烧烤和热饮，炉具怎么配更稳？",
    "家庭露营带孩子，锅具要稳一点也别太难清理。",
    "单人徒步不想背太多，想挑个最轻的小锅。",
    "双人露营既想烧水又想煮面，推荐哪个锅最省心？",
    "多人露营预算有限，先买哪个主锅具最合适？",
    "长途徒步想压重量，但锅不要太小，怎么选？",
    "公园野餐两个人用，想选个好收纳的锅具。",
    "家庭露营偏火锅场景，锅具容量优先怎么选？",
    "烧烤场景想带炉子和烤盘，先买哪类最值？",
    "女生一个人周末出游，想选个能烧水的轻量锅。",
    "自驾露营四个人，想要主锅具不要配件，推荐哪个？",
    "营地做早餐偏煎烤，推荐烤盘还是锅具？",
    "双人露营不想太重，也不想买太贵，推荐哪套？",
    "多人露营想做正餐，容量大一点但收纳别太差。",
    "单人野营只做简单热食，推荐一个最轻的锅。",
    "公园野餐想烧水和简单煮食，锅具怎么选最稳？",
    "家庭露营想一步到位买套锅，哪个更不容易踩坑？",
    "预算不高，想买个泛用性强的锅具主商品。",
    "两个人轻露营，希望锅具轻一点但也别太单薄。",
    "营地热饮和煮面都要兼顾，推荐什么锅具？",
    "长途徒步一个人，锅具只求轻和够用，推荐哪个？",
    "家庭露营烧水频率高，优先买水壶还是锅具？",
]

FAQ_QUESTIONS = [
    "支持七天无理由退换吗？",
    "你们的质保政策是什么？",
    "售后怎么联系？",
    "发票可以开吗？",
    "官方购买渠道有哪些？",
    "线下能在哪里买到？",
    "退货流程怎么走？",
    "如果发错货了怎么办？",
    "下单后多久发货？",
    "有没有人工客服入口？",
]

MULTITURN_SEQUENCES = [
    ["我一个人徒步，想轻一点，推荐一个锅。", "它能不能用酒精炉？", "有没有更便宜一点的替代？"],
    ["周末两个人野餐，推荐一套锅。", "为什么推荐这个？", "还有没有更轻便一点的？"],
    ["轻途套锅和享野套锅有什么区别？", "那哪个更适合新手？", "它们能不能用酒精炉？"],
    ["我一个人徒步，想轻一点，推荐两个锅。", "刚才第一个和第二个哪个更适合女生一个人背？"],
    ["推荐一个适合三个人露营的锅。", "它容量够煮汤吗？", "有没有更便宜的同类？"],
    ["推荐一个适合双人露营的锅。", "它和刚才那个比哪个更稳？"],
    ["有没有适合烧烤的炉具？", "那配什么烤盘更合适？", "有没有更便宜一点的？"],
    ["给我推荐一个烧水用的水壶。", "它可以装冷水吗？", "更适合烧水还是随身补水？"],
    ["我想买个适合新手的套锅。", "它支持酒精炉吗？"],
    ["有哪些锅具产品？", "里面哪些支持酒精炉？", "有没有更适合两个人的？"],
    ["推荐一个双人露营锅。", "为什么推荐它？", "再给一个更轻的备选。"],
    ["行山单锅和激川单锅有什么区别？", "那哪个更适合新手？"],
    ["轻途套锅和享野套锅对比一下。", "哪个更适合两个人露营？", "它们支持酒精炉吗？"],
    ["我一个人徒步，先推荐一个轻锅。", "它适合煮面吗？"],
    ["推荐个家庭露营用的主锅具。", "有没有更大一点的？", "那更适合火锅吗？"],
    ["推荐一个露营水壶。", "它适合烧水还是随身补水？"],
    ["双人野餐想买锅。", "再换一个别的推荐，不要刚才那个。", "第二个和第三个哪个好？"],
    ["多人露营想买锅具。", "它能不能放酒精炉上？"],
    ["比较一下 CW-C06PRO 和 CW-C19T-37。", "哪个更适合新手？"],
    ["你刚才推荐的第一个和第二个哪个好？"],
]


@dataclass(frozen=True)
class ProbeVerdict:
    judgement: str
    attribution: str
    is_runtime_noise: bool = False
    is_business_blocking: bool = False


@dataclass(frozen=True)
class ProbeCase:
    case_id: str
    group: str
    sequence_id: str
    question: str
    endpoint_mode: str = "stream_only"
    tags: tuple[str, ...] = ()
    expected: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class InventoryItem:
    sku: str
    name: str
    category: str
    sub_category: str
    capacity: str
    material: str
    weight_g: float | None
    heat_source: str
    size_info: str
    usage_instruction: str
    usage_scenarios: str


def _import_baseline_probe():
    module_path = ROOT / "scripts" / "dev_gray_full_probe.py"
    spec = importlib.util.spec_from_file_location("dev_gray_full_probe", module_path)
    if not spec or not spec.loader:
        raise RuntimeError(f"failed to load baseline probe module: {module_path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules.setdefault(spec.name, module)
    spec.loader.exec_module(module)
    return module


def chunked_cases(cases: Iterable[dict[str, Any]] | Iterable[ProbeCase], batch_size: int = DEFAULT_BATCH_SIZE) -> Iterator[list[Any]]:
    size = max(int(batch_size or 0), 1)
    batch: list[Any] = []
    for case in cases:
        batch.append(case)
        if len(batch) >= size:
            yield batch
            batch = []
    if batch:
        yield batch


def request_with_rate_limit_retry(
    send_request: Callable[[], dict[str, Any]],
    *,
    max_retries: int = DEFAULT_RATE_LIMIT_RETRIES,
    backoff_seconds: float = DEFAULT_RATE_LIMIT_BACKOFF_SECONDS,
    sleep_fn: Callable[[float], None] = time.sleep,
) -> dict[str, Any]:
    attempts = 0
    rate_limit_retries = 0
    transport_retries = 0
    last_result: dict[str, Any] | None = None
    while True:
        try:
            result = dict(send_request() or {})
        except OSError as exc:
            if attempts >= max_retries:
                return {
                    "status": 599,
                    "answer": "",
                    "answer_type": "",
                    "result_skus": [],
                    "warnings": ["transport_error"],
                    "transport_error": str(exc),
                    "transport_retries": transport_retries,
                    "rate_limit_retries": rate_limit_retries,
                    "rate_limit_exhausted": False,
                    "transport_exhausted": True,
                }
            delay = max(float(backoff_seconds), 0.0) * (2**attempts)
            if delay > 0:
                sleep_fn(delay)
            attempts += 1
            transport_retries += 1
            continue
        status = int(result.get("status") or 0)
        if status != 429:
            result["rate_limit_retries"] = rate_limit_retries
            result["transport_retries"] = transport_retries
            result["rate_limit_exhausted"] = False
            return result
        last_result = result
        if attempts >= max_retries:
            break
        delay = max(float(backoff_seconds), 0.0) * (2**attempts)
        if delay > 0:
            sleep_fn(delay)
        attempts += 1
        rate_limit_retries += 1
    final = dict(last_result or {})
    final["rate_limit_retries"] = rate_limit_retries
    final["transport_retries"] = transport_retries
    final["rate_limit_exhausted"] = True
    return final


def audit_runtime_verdict(record: dict[str, Any]) -> ProbeVerdict:
    status = int(record.get("status") or 0)
    if status == 429:
        return ProbeVerdict("warning", "rate_limit", is_runtime_noise=True, is_business_blocking=False)
    if status >= 500:
        return ProbeVerdict("warning", "runtime_noise", is_runtime_noise=True, is_business_blocking=False)
    if status >= 400:
        return ProbeVerdict("blocking", "HTTP error", is_runtime_noise=False, is_business_blocking=True)
    return ProbeVerdict(
        judgement=str(record.get("judgement") or "pass"),
        attribution=str(record.get("attribution") or "ok"),
        is_runtime_noise=False,
        is_business_blocking=str(record.get("judgement") or "") == "blocking",
    )


def apply_audited_verdict(record: dict[str, Any]) -> dict[str, Any]:
    verdict = audit_runtime_verdict(record)
    merged = dict(record)
    merged["raw_judgement"] = record.get("judgement")
    merged["raw_attribution"] = record.get("attribution")
    merged["audited_judgement"] = verdict.judgement
    merged["audited_attribution"] = verdict.attribution
    merged["runtime_noise"] = verdict.is_runtime_noise
    merged["business_blocking"] = verdict.is_business_blocking
    return merged


def summarize_records(records: Iterable[dict[str, Any]]) -> dict[str, Any]:
    raw = {"pass": 0, "warning": 0, "fail": 0, "blocking_fail": 0}
    audited = {
        "pass": 0,
        "warning": 0,
        "fail": 0,
        "blocking_fail": 0,
        "real_business_problem": 0,
        "data_field_issue": 0,
        "probe_runner_noise": 0,
        "rate_limit": 0,
        "performance_warning": 0,
        "runtime_noise": 0,
        "business_blocking": 0,
    }
    for record in records:
        raw_key = str(record.get("judgement") or "pass")
        if raw_key == "blocking":
            raw["blocking_fail"] += 1
        elif raw_key in raw:
            raw[raw_key] += 1

        audited_record = apply_audited_verdict(record)
        audited_key = str(audited_record.get("audited_judgement") or "pass")
        if audited_key == "blocking":
            audited["blocking_fail"] += 1
        elif audited_key in audited:
            audited[audited_key] += 1

        attribution = str(audited_record.get("audited_attribution") or "")
        if attribution == "rate_limit":
            audited["rate_limit"] += 1
        elif attribution == "performance":
            audited["performance_warning"] += 1
        elif attribution in {"probe_rule", "runtime_noise"}:
            audited["probe_runner_noise"] += 1
        elif attribution == "data_field":
            audited["data_field_issue"] += 1
        elif attribution not in {"ok", ""} and audited_key in {"warning", "fail", "blocking"}:
            audited["real_business_problem"] += 1

        if audited_record.get("runtime_noise"):
            audited["runtime_noise"] += 1
        if audited_record.get("business_blocking"):
            audited["business_blocking"] += 1
    return {"raw_summary": raw, "audited_summary": audited}


def run_batched_cases(
    cases: Iterable[dict[str, Any]] | Iterable[ProbeCase],
    *,
    runner: Callable[[Any], dict[str, Any]],
    batch_size: int = DEFAULT_BATCH_SIZE,
    batch_sleep_seconds: float = DEFAULT_BATCH_SLEEP_SECONDS,
    sleep_fn: Callable[[float], None] = time.sleep,
) -> list[dict[str, Any]]:
    batches = list(chunked_cases(cases, batch_size=batch_size))
    records: list[dict[str, Any]] = []
    for index, batch in enumerate(batches):
        for case in batch:
            records.append(runner(case))
        if index < len(batches) - 1 and batch_sleep_seconds > 0:
            sleep_fn(batch_sleep_seconds)
    return records


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
    extra_headers: dict[str, str] | None = None,
    timeout: float = DEFAULT_TIMEOUT,
) -> tuple[int, bytes]:
    data = None if payload is None else json.dumps(payload, ensure_ascii=False).encode("utf-8")
    headers = {"Content-Type": "application/json; charset=utf-8"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    if extra_headers:
        headers.update(extra_headers)
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


def _normalized_response_payload(
    *,
    status: int,
    question: str,
    answer: str,
    meta: dict[str, Any],
    trace: dict[str, Any],
    elapsed_ms: float,
    endpoint: str,
    sent_conversation_id: str | None,
) -> dict[str, Any]:
    debug = meta.get("debug") if isinstance(meta.get("debug"), dict) else {}
    answer_metadata = meta.get("answer_metadata") if isinstance(meta.get("answer_metadata"), dict) else {}
    timing = answer_metadata.get("timing") if isinstance(answer_metadata.get("timing"), dict) else {}
    raw_results = debug.get("raw_results") if isinstance(debug.get("raw_results"), list) else []
    return {
        "status": status,
        "endpoint": endpoint,
        "question": question,
        "sent_conversation_id": sent_conversation_id,
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
        "recommended_skus": meta.get("recommended_skus") or [],
        "timing": timing,
        "llm_call_count": timing.get("llm_call_count"),
        "debug_plan": debug.get("plan") if isinstance(debug.get("plan"), dict) else {},
        "debug_trace": trace if isinstance(trace, dict) else {},
        "warnings": meta.get("warnings") or [],
        "elapsed_ms_client": elapsed_ms,
        "guard_rebuild_fallback": {
            "guard": ((debug.get("trace") or {}).get("guard") if isinstance(debug.get("trace"), dict) else None),
            "fallback": ((debug.get("trace") or {}).get("fallback") if isinstance(debug.get("trace"), dict) else None),
            "rebuild": bool(((debug.get("trace") or {}).get("rebuild")) if isinstance(debug.get("trace"), dict) else False),
            "fast_path": bool(((debug.get("trace") or {}).get("hit_faq_fast_path")) if isinstance(debug.get("trace"), dict) else False),
        },
        "is_kb_fallback": str(meta.get("answer_type") or "") == "knowledge_base_answer",
    }


def ask_stream(
    token: str,
    question: str,
    conversation_id: str | None,
    *,
    parity_isolation: bool = False,
) -> dict[str, Any]:
    payload: dict[str, Any] = {"question": question}
    if conversation_id:
        payload["conversation_id"] = conversation_id
    started = time.perf_counter()
    status, body = json_request(
        "POST",
        f"{DEFAULT_BASE_URL.rstrip('/')}/api/customer-service/ask-stream",
        payload=payload,
        token=token,
        extra_headers={"X-Customer-Service-Parity-Isolation": "true"} if parity_isolation else None,
    )
    elapsed_ms = round((time.perf_counter() - started) * 1000, 1)
    if status >= 400:
        return {
            "status": status,
            "endpoint": "/api/customer-service/ask-stream",
            "question": question,
            "sent_conversation_id": conversation_id,
            "answer": body.decode("utf-8", errors="replace"),
            "answer_type": "",
            "intent": "",
            "primary_intent": "",
            "result_skus": [],
            "metadata_skus": [],
            "candidate_skus": [],
            "retrieved_products_top": [],
            "recommendation_context": None,
            "recommended_skus": [],
            "timing": {},
            "llm_call_count": None,
            "debug_plan": {},
            "debug_trace": {},
            "warnings": [f"http_{status}"],
            "elapsed_ms_client": elapsed_ms,
            "guard_rebuild_fallback": {},
            "is_kb_fallback": False,
            "conversation_id": conversation_id,
        }
    answer, meta, trace, _events = parse_sse(body)
    return _normalized_response_payload(
        status=status,
        question=question,
        answer=answer,
        meta=meta,
        trace=trace,
        elapsed_ms=elapsed_ms,
        endpoint="/api/customer-service/ask-stream",
        sent_conversation_id=conversation_id,
    )


def ask(
    token: str,
    question: str,
    conversation_id: str | None,
    *,
    parity_isolation: bool = False,
) -> dict[str, Any]:
    payload: dict[str, Any] = {"question": question}
    if conversation_id:
        payload["conversation_id"] = conversation_id
    started = time.perf_counter()
    status, body = json_request(
        "POST",
        f"{DEFAULT_BASE_URL.rstrip('/')}/api/customer-service/ask",
        payload=payload,
        token=token,
        extra_headers={"X-Customer-Service-Parity-Isolation": "true"} if parity_isolation else None,
    )
    elapsed_ms = round((time.perf_counter() - started) * 1000, 1)
    if status >= 400:
        return {
            "status": status,
            "endpoint": "/api/customer-service/ask",
            "question": question,
            "sent_conversation_id": conversation_id,
            "answer": body.decode("utf-8", errors="replace"),
            "answer_type": "",
            "intent": "",
            "primary_intent": "",
            "result_skus": [],
            "metadata_skus": [],
            "candidate_skus": [],
            "retrieved_products_top": [],
            "recommendation_context": None,
            "recommended_skus": [],
            "timing": {},
            "llm_call_count": None,
            "debug_plan": {},
            "debug_trace": {},
            "warnings": [f"http_{status}"],
            "elapsed_ms_client": elapsed_ms,
            "guard_rebuild_fallback": {},
            "is_kb_fallback": False,
            "conversation_id": conversation_id,
        }
    payload_json = json.loads(body.decode("utf-8"))
    debug = payload_json.get("debug") if isinstance(payload_json.get("debug"), dict) else {}
    trace = payload_json.get("trace") if isinstance(payload_json.get("trace"), dict) else {}
    meta = {
        "conversation_id": payload_json.get("conversation_id"),
        "answer": payload_json.get("answer"),
        "answer_type": payload_json.get("answer_type"),
        "intent": payload_json.get("intent"),
        "agent_mode": payload_json.get("agent_mode"),
        "result_skus": payload_json.get("result_skus"),
        "skus": payload_json.get("metadata", {}).get("skus") if isinstance(payload_json.get("metadata"), dict) else payload_json.get("skus"),
        "candidate_skus": payload_json.get("candidate_skus"),
        "recommended_skus": payload_json.get("recommended_skus"),
        "recommendation_context": payload_json.get("recommendation_context"),
        "answer_metadata": payload_json.get("answer_metadata"),
        "warnings": payload_json.get("warnings"),
        "debug": debug,
    }
    return _normalized_response_payload(
        status=status,
        question=question,
        answer=str(payload_json.get("answer") or ""),
        meta=meta,
        trace=trace,
        elapsed_ms=elapsed_ms,
        endpoint="/api/customer-service/ask",
        sent_conversation_id=conversation_id,
    )


def _ensure_backend_imports() -> None:
    backend_str = str(BACKEND_ROOT)
    if backend_str not in sys.path:
        sys.path.insert(0, backend_str)


def _parse_first_scalar(value: str) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    if text.startswith("[") or text.startswith("{"):
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            return text
        if isinstance(data, list) and data:
            first = data[0]
            if isinstance(first, dict):
                scalar = str(first.get("value") or first.get("label") or "").strip()
                unit = str(first.get("unit") or "").strip()
                return f"{scalar}{unit}".strip()
            return str(first)
        if isinstance(data, dict):
            return str(data.get("value") or data.get("label") or "")
    return text


def load_inventory() -> dict[str, Any]:
    _ensure_backend_imports()
    from app.core.database import SessionLocal
    from app.models.product import Product
    from app.models.product_business import ProductBusiness
    from app.models.product_specs import ProductSpecs

    db = SessionLocal()
    try:
        rows = (
            db.query(Product, ProductSpecs, ProductBusiness)
            .outerjoin(ProductSpecs, ProductSpecs.product_id == Product.id)
            .outerjoin(ProductBusiness, ProductBusiness.product_id == Product.id)
            .filter(Product.active_flag.is_(True))
            .order_by(Product.category.asc(), Product.sku.asc())
            .all()
        )
        products: list[InventoryItem] = []
        counter: Counter[str] = Counter()
        for product, specs, business in rows:
            category = str(product.category or "").strip() or "未分类"
            counter[category] += 1
            products.append(
                InventoryItem(
                    sku=str(product.sku or "").strip().upper(),
                    name=str(product.product_name_cn or product.product_name_en or "").strip(),
                    category=category,
                    sub_category=str(product.sub_category or "").strip(),
                    capacity=_parse_first_scalar(specs.capacity if specs else ""),
                    material=str(specs.body_material or "").strip() if specs else "",
                    weight_g=float(specs.gross_weight_g) if specs and specs.gross_weight_g else None,
                    heat_source=str(specs.heat_source or "").strip() if specs else "",
                    size_info=_parse_first_scalar(specs.size_info if specs else ""),
                    usage_instruction=str(specs.usage_instruction or "").strip() if specs else "",
                    usage_scenarios=str(business.usage_scenarios or "").strip() if business else "",
                )
            )
        categories = [{"category": category, "count": count} for category, count in counter.most_common()]
        return {
            "total_products": len(products),
            "products": [asdict(item) for item in products],
            "categories": categories,
        }
    finally:
        db.close()


def _inventory_items(inventory: dict[str, Any]) -> list[InventoryItem]:
    return [InventoryItem(**item) if not isinstance(item, InventoryItem) else item for item in inventory.get("products") or []]


def _round_robin_select(products: Sequence[InventoryItem], limit: int = 50) -> list[InventoryItem]:
    by_category: dict[str, list[InventoryItem]] = defaultdict(list)
    for item in products:
        by_category[item.category].append(item)
    ordered_categories = [name for name, _count in Counter(item.category for item in products).most_common()]
    selected: list[InventoryItem] = []
    seen: set[str] = set()
    while len(selected) < min(limit, len(products)):
        made_progress = False
        for category in ordered_categories:
            bucket = by_category.get(category) or []
            while bucket and bucket[0].sku in seen:
                bucket.pop(0)
            if not bucket:
                continue
            item = bucket.pop(0)
            if item.sku in seen:
                continue
            selected.append(item)
            seen.add(item.sku)
            made_progress = True
            if len(selected) >= min(limit, len(products)):
                break
        if not made_progress:
            break
    return selected


def _category_alias(item: InventoryItem) -> str:
    return item.category or item.sub_category or item.name or "产品"


def _category_groups(products: Sequence[InventoryItem]) -> list[tuple[str, list[InventoryItem]]]:
    grouped: dict[str, list[InventoryItem]] = defaultdict(list)
    for item in products:
        grouped[_category_alias(item)].append(item)
    return sorted(grouped.items(), key=lambda pair: (-len(pair[1]), pair[0]))


def build_baseline_cases() -> list[ProbeCase]:
    baseline = _import_baseline_probe()
    cases = []
    for step in getattr(baseline, "CASE_STEPS", []):
        cases.append(
            ProbeCase(
                case_id=str(step.label),
                group="baseline36",
                sequence_id=str(step.sequence),
                question=str(step.question),
                endpoint_mode="stream_only",
                tags=("baseline",),
            )
        )
    return cases


def build_sku_field_cases(products: Sequence[InventoryItem], target_skus: int = 50) -> list[ProbeCase]:
    selected = _round_robin_select(products, limit=target_skus)
    cases: list[ProbeCase] = []
    for index, item in enumerate(selected, start=1):
        prefix = f"sku_{item.sku}"
        cases.append(
            ProbeCase(
                case_id=f"{prefix}_1",
                group="sku_fields",
                sequence_id=f"{prefix}_1",
                question=f"{item.sku} 是什么材质？容量多大？",
                tags=("field", "material_capacity"),
                expected={"explicit_sku": item.sku, "type": "material_capacity"},
            )
        )
        cases.append(
            ProbeCase(
                case_id=f"{prefix}_2",
                group="sku_fields",
                sequence_id=f"{prefix}_2",
                question=f"{item.sku} 重量多少？尺寸大概多大？",
                tags=("field", "weight_size"),
                expected={"explicit_sku": item.sku, "type": "weight_size"},
            )
        )
        if any(token in item.category for token in ("壶", "杯", "水具", "水壶")) or any(token in item.name for token in ("壶", "杯")):
            question = f"{item.sku} 可以装冷水吗？适合烧水还是随身补水？"
            tags = ("field", "water_usage")
            expected_type = "water_usage"
        else:
            question = f"{item.sku} 适合什么场景？能不能用酒精炉？"
            tags = ("field", "usage_heat")
            expected_type = "usage_heat"
        cases.append(
            ProbeCase(
                case_id=f"{prefix}_3",
                group="sku_fields",
                sequence_id=f"{prefix}_3",
                question=question,
                tags=tags,
                expected={"explicit_sku": item.sku, "type": expected_type},
            )
        )
    return cases


def build_category_cases(products: Sequence[InventoryItem], target_categories: int = 10) -> list[ProbeCase]:
    grouped = _category_groups(products)[:target_categories]
    category_names = [name for name, _items in grouped]
    compare_targets = category_names[1:] + category_names[:1]
    cases: list[ProbeCase] = []
    for index, (category, items) in enumerate(grouped, start=1):
        compare_with = compare_targets[index - 1]
        prefix = f"cat_{index}"
        sample_skus = [item.sku for item in items[:10]]
        cases.extend(
            [
                ProbeCase(
                    case_id=f"{prefix}_list",
                    group="categories",
                    sequence_id=f"{prefix}_list",
                    question=f"有哪些{category}产品？",
                    tags=("category", "catalog"),
                    expected={"category": category, "type": "list", "sample_skus": sample_skus},
                ),
                ProbeCase(
                    case_id=f"{prefix}_count",
                    group="categories",
                    sequence_id=f"{prefix}_count",
                    question=f"你们有多少{category}产品？",
                    tags=("category", "count"),
                    expected={"category": category, "type": "count", "sample_skus": sample_skus},
                ),
                ProbeCase(
                    case_id=f"{prefix}_recommend",
                    group="categories",
                    sequence_id=f"{prefix}_recommend",
                    question=f"{category}里推荐哪个最稳妥？",
                    tags=("category", "recommend"),
                    expected={"category": category, "type": "recommend", "sample_skus": sample_skus},
                ),
                ProbeCase(
                    case_id=f"{prefix}_people",
                    group="categories",
                    sequence_id=f"{prefix}_people",
                    question=f"{category}一般适合几个人？",
                    tags=("category", "people"),
                    expected={"category": category, "type": "people", "sample_skus": sample_skus},
                ),
                ProbeCase(
                    case_id=f"{prefix}_compare",
                    group="categories",
                    sequence_id=f"{prefix}_compare",
                    question=f"{category}和{compare_with}有什么区别？",
                    tags=("category", "compare"),
                    expected={"category": category, "compare_with": compare_with, "type": "compare", "sample_skus": sample_skus},
                ),
            ]
        )
    return cases


def build_scenario_cases() -> list[ProbeCase]:
    return [
        ProbeCase(
            case_id=f"scene_{index:03d}",
            group="scenarios",
            sequence_id=f"scene_{index:03d}",
            question=question,
            tags=("scenario",),
            expected={"type": "scenario_recommendation"},
        )
        for index, question in enumerate(SCENARIO_QUESTIONS, start=1)
    ]


def _compare_candidates(products: Sequence[InventoryItem]) -> list[tuple[InventoryItem, InventoryItem]]:
    grouped: dict[str, list[InventoryItem]] = defaultdict(list)
    for item in products:
        grouped[item.category].append(item)
    pairs: list[tuple[InventoryItem, InventoryItem]] = []
    for category, items in sorted(grouped.items(), key=lambda pair: (-len(pair[1]), pair[0])):
        for idx in range(0, len(items) - 1, 2):
            pairs.append((items[idx], items[idx + 1]))
    if len(pairs) >= 30:
        return pairs[:30]
    flat = list(products)
    idx = 0
    while len(pairs) < min(30, len(flat) // 2) and idx + 1 < len(flat):
        pairs.append((flat[idx], flat[idx + 1]))
        idx += 2
    return pairs[:30]


def build_compare_cases(products: Sequence[InventoryItem], target: int = 30) -> list[ProbeCase]:
    pairs = _compare_candidates(products)[:target]
    cases = []
    for index, (left, right) in enumerate(pairs, start=1):
        cases.append(
            ProbeCase(
                case_id=f"cmp_{index:03d}",
                group="compare",
                sequence_id=f"cmp_{index:03d}",
                question=f"{left.sku} 和 {right.sku} 有什么区别？推荐选一个。",
                tags=("compare", left.category or "product"),
                expected={"pair": [left.sku, right.sku], "type": "compare"},
            )
        )
    return cases


def build_multiturn_cases() -> list[ProbeCase]:
    cases: list[ProbeCase] = []
    for seq_index, sequence in enumerate(MULTITURN_SEQUENCES, start=1):
        sequence_id = f"mt_{seq_index:03d}"
        for turn_index, question in enumerate(sequence, start=1):
            cases.append(
                ProbeCase(
                    case_id=f"{sequence_id}_t{turn_index}",
                    group="multiturn",
                    sequence_id=sequence_id,
                    question=question,
                    tags=("multiturn",),
                    expected={
                        "turn_index": turn_index,
                        "total_turns": len(sequence),
                        "requires_context": turn_index > 1,
                    },
                )
            )
    return cases


def build_faq_cases() -> list[ProbeCase]:
    return [
        ProbeCase(
            case_id=f"faq_{index:02d}",
            group="faq",
            sequence_id=f"faq_{index:02d}",
            question=question,
            tags=("faq",),
            expected={"type": "faq"},
        )
        for index, question in enumerate(FAQ_QUESTIONS, start=1)
    ]


def build_large_probe_case_plan(inventory: dict[str, Any]) -> dict[str, Any]:
    products = _inventory_items(inventory)
    baseline_cases = build_baseline_cases()
    sku_cases = build_sku_field_cases(products, target_skus=50)
    category_cases = build_category_cases(products, target_categories=10)
    scenario_cases = build_scenario_cases()
    compare_cases = build_compare_cases(products, target=30)
    multiturn_cases = build_multiturn_cases()
    faq_cases = build_faq_cases()
    cases = baseline_cases + sku_cases + category_cases + scenario_cases + compare_cases + multiturn_cases + faq_cases
    group_counts = Counter(case.group for case in cases)
    coverage = {
        "total_requests": len(cases),
        "single_turn_requests": sum(1 for case in cases if case.group != "multiturn"),
        "multiturn_sequences": len({case.sequence_id for case in cases if case.group == "multiturn"}),
        "endpoint_parity_checks": PARITY_CASE_LIMIT,
        "sku_covered": len({case.expected.get("explicit_sku") for case in sku_cases if case.expected.get("explicit_sku")}),
        "category_covered": len({case.expected.get("category") for case in category_cases if case.expected.get("category")}),
    }
    if len(cases) < 386:
        raise RuntimeError(f"large probe cases too small: {len(cases)}")
    return {
        "cases": cases[:386],
        "coverage": coverage | {"total_requests": 386},
        "group_counts": dict(group_counts),
    }


def select_parity_cases(cases: Sequence[ProbeCase], limit: int = PARITY_CASE_LIMIT) -> list[ProbeCase]:
    by_id = {case.case_id: case for case in cases}
    selected: list[ProbeCase] = []
    chosen: set[str] = set()

    priority_ids = [
        "q04", "q19", "q06", "q08", "q10", "q11", "q13", "q14", "q21", "q23", "q24", "q25", "q26",
        "q15_t1", "q15_t2", "q15_t3", "q16_t1", "q16_t2", "q16_t3", "q17_t1", "q17_t2", "q17_t3",
        "q20b_t1", "q20b_t2",
    ]
    for case_id in priority_ids:
        case = by_id.get(case_id)
        if case and case.case_id not in chosen:
            selected.append(case)
            chosen.add(case.case_id)

    for case in cases:
        if len(selected) >= limit:
            break
        if case.case_id in chosen:
            continue
        if case.group in {"sku_fields", "categories", "compare"}:
            if case.group == "multiturn" and case.expected.get("turn_index", 1) > 1:
                continue
            selected.append(case)
            chosen.add(case.case_id)

    # Ensure no follow-up is selected without the preceding turns from the same sequence.
    sequence_cases = defaultdict(list)
    for case in selected:
        sequence_cases[case.sequence_id].append(case)
    normalized: list[ProbeCase] = []
    seen_ids: set[str] = set()
    for sequence_id, items in sequence_cases.items():
        ordered = sorted(items, key=lambda item: item.expected.get("turn_index", 1))
        if any(item.expected.get("requires_context") for item in ordered):
            full_sequence = sorted(
                [case for case in cases if case.sequence_id == sequence_id],
                key=lambda item: item.expected.get("turn_index", 1),
            )
            for case in full_sequence:
                if case.case_id not in seen_ids:
                    normalized.append(case)
                    seen_ids.add(case.case_id)
        else:
            for case in ordered:
                if case.case_id not in seen_ids:
                    normalized.append(case)
                    seen_ids.add(case.case_id)
    for case in normalized:
        if len(normalized) >= limit:
            break
    return normalized[:limit]


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
    return {"status": status, "payload": payload}


def _contains_any(text: str, items: Sequence[str]) -> bool:
    value = str(text or "")
    return any(item in value for item in items)


def _extract_question_skus(question: str) -> list[str]:
    seen: list[str] = []
    for item in SKU_RE.findall(question or ""):
        normalized = item.replace("_", "-").upper()
        if normalized not in seen:
            seen.append(normalized)
    return seen


def _warning_if_slow(record: dict[str, Any]) -> tuple[str, str] | None:
    timing = record.get("timing") or {}
    total_ms = float(timing.get("total_duration_ms") or record.get("elapsed_ms_client") or 0)
    llm_calls = int(record.get("llm_call_count") or 0)
    if llm_calls == 0 and total_ms >= 20000:
        return "warning", "performance"
    return None


def _baseline_history(history: dict[str, dict[str, Any]]) -> dict[str, dict[str, Any]]:
    normalized: dict[str, dict[str, Any]] = {}
    for label, item in history.items():
        normalized[label] = {
            "status": item.get("status"),
            "answer": item.get("answer"),
            "answer_type": item.get("answer_type"),
            "result_skus": item.get("result_skus"),
            "metadata_skus": item.get("metadata_skus"),
            "timing": item.get("timing"),
            "guard_rebuild_fallback": item.get("guard_rebuild_fallback"),
        }
    return normalized


def classify_case(case: ProbeCase, record: dict[str, Any], history: dict[str, dict[str, Any]]) -> tuple[str, str, list[str], dict[str, Any] | None]:
    if record.get("status") != 200:
        return "blocking", "HTTP error", [f"http_{record.get('status')}"], None
    if not str(record.get("answer") or "").strip():
        return "fail", "empty_answer", ["empty_answer"], None

    performance = _warning_if_slow(record)
    if performance:
        judgement, attribution = performance
        return judgement, attribution, ["slow_local_path"], None

    if case.group == "baseline36":
        baseline = _import_baseline_probe()
        verdict, issues, category, data_issue = baseline.classify_result(case.case_id, record, _baseline_history(history))
        if verdict == "pass":
            return "pass", "ok", issues, data_issue
        if verdict == "warning":
            return "warning", "data_field" if category == "data_field" else "probe_rule", issues, data_issue
        if verdict == "blocking_fail":
            return "blocking", "real_business", issues, data_issue
        return "fail", "real_business", issues, data_issue

    answer = str(record.get("answer") or "")
    answer_type = str(record.get("answer_type") or "")
    result_skus = [str(item).upper() for item in record.get("result_skus") or []]

    if case.group == "sku_fields":
        explicit_sku = str(case.expected.get("explicit_sku") or "").upper()
        matched_self = result_skus and result_skus[0] == explicit_sku
        not_found_ok = (not result_skus) and explicit_sku and explicit_sku in answer.upper() and _contains_any(answer, NOT_FOUND_HINTS)
        if case.expected.get("type") == "water_usage":
            if answer_type == "product_usage_care":
                return "fail", "real_business", ["water_usage_fell_to_care"], None
            if not (matched_self or not_found_ok):
                return "fail", "real_business", ["explicit_sku_mismatch"], None
            if not (_contains_any(answer, COLD_WATER_HINTS) and _contains_any(answer, HYDRATION_HINTS)):
                return "warning", "real_business", ["water_usage_field_gap"], None
            return "pass", "ok", [], None
        if matched_self or not_found_ok:
            return "pass", "ok", [], None
        return "fail", "real_business", ["explicit_sku_mismatch"], None

    if case.group == "categories":
        category = str(case.expected.get("category") or "")
        expected_type = case.expected.get("type")
        if expected_type == "count":
            if answer_type == "product_query" and answer_type != "knowledge_base_answer" and category in answer:
                return "pass", "ok", [], None
            return "fail", "real_business", ["category_count_degraded"], None
        if expected_type == "people":
            if answer_type == "knowledge_base_answer":
                return "fail", "real_business", ["category_people_degraded_kb"], None
            if category in NON_PEOPLE_CATEGORIES and _contains_any(answer, ("不按人数", "按用途", "按场景", "按功能")):
                return "pass", "ok", [], None
            if category not in NON_PEOPLE_CATEGORIES and (_contains_any(answer, PERSON_HINTS) or result_skus):
                return "pass", "ok", [], None
            return "warning", "real_business", ["category_people_scope_weak"], None
        if expected_type == "compare":
            other = str(case.expected.get("compare_with") or "")
            if answer_type != "knowledge_base_answer" and category in answer and other in answer:
                return "pass", "ok", [], None
            return "warning", "probe_rule", ["category_compare_scope_drift"], None
        if expected_type == "recommend":
            if answer_type == "recommendation" and result_skus:
                return "pass", "ok", [], None
            return "warning", "real_business", ["category_recommendation_weak"], None
        if (
            answer_type in {"product_query", "query_products"}
            and result_skus
            and answer_type != "knowledge_base_answer"
            and category in answer
        ):
            return "pass", "ok", [], None
        return "warning", "real_business", ["category_catalog_weak"], None

    if case.group == "compare":
        pair = [str(item).upper() for item in case.expected.get("pair") or []]
        if answer_type == "knowledge_base_answer":
            return "fail", "real_business", ["compare_degraded_kb"], None
        if all(item in answer.upper() or item in result_skus for item in pair):
            return "pass", "ok", [], None
        return "warning", "real_business", ["compare_missing_object"], None

    if case.group == "scenarios":
        if answer_type == "recommendation" and result_skus:
            return "pass", "ok", [], None
        return "warning", "real_business", ["scenario_recommendation_weak"], None

    if case.group == "multiturn":
        if case.expected.get("requires_context"):
            if not record.get("sent_conversation_id") or record.get("sent_conversation_id") != record.get("conversation_id"):
                return "fail", "real_business", ["conversation_id_not_reused"], None
        if answer_type == "knowledge_base_answer":
            return "fail", "real_business", ["multiturn_kb_fallback"], None
        if (
            case.expected.get("turn_index") == 1
            and case.expected.get("total_turns") == 1
            and answer_type == "clarification"
            and _contains_any(case.question, ("刚才推荐的第一个", "第一个和第二个", "刚才那个"))
        ):
            return "pass", "probe_rule", [], None
        if case.expected.get("turn_index") == 1 and answer_type not in {"recommendation", "product_query", "product_detail"}:
            return "warning", "real_business", ["multiturn_opening_weak"], None
        return "pass", "ok", [], None

    if case.group == "faq":
        if answer.strip():
            return "pass", "ok", [], None
        return "warning", "probe_rule", ["faq_empty"], None

    return "pass", "ok", [], None


def run_case_stream(
    token: str,
    case: ProbeCase,
    *,
    sequence_conversations: dict[str, str],
) -> dict[str, Any]:
    sent_conversation_id = sequence_conversations.get(case.sequence_id)
    raw = request_with_rate_limit_retry(
        lambda: ask_stream(token, case.question, sent_conversation_id),
    )
    if raw.get("conversation_id"):
        sequence_conversations[case.sequence_id] = str(raw["conversation_id"])
    return raw


def _record_from_case(case: ProbeCase, raw: dict[str, Any], history: dict[str, dict[str, Any]]) -> dict[str, Any]:
    judgement, attribution, issues, data_issue = classify_case(case, raw, history)
    record = {
        **raw,
        "case_id": case.case_id,
        "group": case.group,
        "sequence_id": case.sequence_id,
        "endpoint_mode": case.endpoint_mode,
        "tags": list(case.tags),
        "expected": case.expected,
        "judgement": judgement,
        "attribution": attribution,
        "issues": issues,
        "data_issue": data_issue,
    }
    return apply_audited_verdict(record)


def run_large_probe() -> dict[str, Any]:
    inventory = load_inventory()
    plan = build_large_probe_case_plan(inventory)
    token = login()
    cases: list[ProbeCase] = plan["cases"]
    sequence_conversations: dict[str, str] = {}
    history: dict[str, dict[str, Any]] = {}

    def runner(case: ProbeCase) -> dict[str, Any]:
        raw = run_case_stream(token, case, sequence_conversations=sequence_conversations)
        record = _record_from_case(case, raw, history)
        history[case.case_id] = record
        print(
            json.dumps(
                {
                    "case_id": case.case_id,
                    "group": case.group,
                    "judgement": record["judgement"],
                    "audited_judgement": record["audited_judgement"],
                    "status": raw.get("status"),
                },
                ensure_ascii=False,
            ),
            flush=True,
        )
        return record

    records = run_batched_cases(
        cases,
        runner=runner,
        batch_size=DEFAULT_BATCH_SIZE,
        batch_sleep_seconds=DEFAULT_BATCH_SLEEP_SECONDS,
    )
    return {
        "inventory": inventory,
        "coverage": plan["coverage"],
        "records": records,
    }


def _run_parity_sequence(
    token: str,
    sequence: Sequence[ProbeCase],
) -> dict[str, Any]:
    ask_conversation_id: str | None = None
    stream_conversation_id: str | None = None
    turns: list[dict[str, Any]] = []
    for case in sequence:
        ask_result = request_with_rate_limit_retry(lambda: ask(token, case.question, ask_conversation_id))
        ask_conversation_id = str(ask_result.get("conversation_id") or ask_conversation_id or "")
        stream_result = request_with_rate_limit_retry(lambda: ask_stream(token, case.question, stream_conversation_id))
        stream_conversation_id = str(stream_result.get("conversation_id") or stream_conversation_id or "")
        equivalent = (
            ask_result.get("status") == stream_result.get("status")
            and ask_result.get("answer_type") == stream_result.get("answer_type")
            and list(ask_result.get("result_skus") or []) == list(stream_result.get("result_skus") or [])
        )
        turns.append(
            {
                "case_id": case.case_id,
                "question": case.question,
                "ask": ask_result,
                "stream": stream_result,
                "equivalent": equivalent,
            }
        )
    return {
        "sequence_id": sequence[0].sequence_id,
        "group": sequence[0].group,
        "turns": turns,
        "all_equivalent": all(turn["equivalent"] for turn in turns),
    }


def run_parity_spot_checks(cases: Sequence[ProbeCase]) -> dict[str, Any]:
    token = login()
    selected = select_parity_cases(cases, limit=PARITY_CASE_LIMIT)
    grouped: dict[str, list[ProbeCase]] = defaultdict(list)
    for case in selected:
        grouped[case.sequence_id].append(case)
    reports = []
    for sequence_id in selected_sequence_order(selected):
        sequence = sorted(grouped[sequence_id], key=lambda item: item.expected.get("turn_index", 1))
        reports.append(_run_parity_sequence(token, sequence))
    flat_turns = [turn for report in reports for turn in report["turns"]]
    return {
        "selected_case_ids": [case.case_id for case in selected],
        "reports": reports,
        "summary": {
            "checked": len(flat_turns),
            "equivalent": sum(1 for turn in flat_turns if turn["equivalent"]),
            "not_equivalent": sum(1 for turn in flat_turns if not turn["equivalent"]),
        },
    }


def selected_sequence_order(cases: Sequence[ProbeCase]) -> list[str]:
    seen: list[str] = []
    for case in cases:
        if case.sequence_id not in seen:
            seen.append(case.sequence_id)
    return seen


def _slow_top(records: Sequence[dict[str, Any]], limit: int = 20) -> list[dict[str, Any]]:
    timings = [
        {
            "case_id": item["case_id"],
            "question": item["question"],
            "answer_type": item.get("answer_type"),
            "total_duration_ms": (item.get("timing") or {}).get("total_duration_ms") or item.get("elapsed_ms_client"),
            "llm_duration_ms": (item.get("timing") or {}).get("llm_duration_ms"),
            "llm_call_count": item.get("llm_call_count"),
        }
        for item in records
    ]
    return sorted(timings, key=lambda item: float(item.get("total_duration_ms") or 0), reverse=True)[:limit]


def build_report() -> dict[str, Any]:
    probe = run_large_probe()
    records = probe["records"]
    cases = build_large_probe_case_plan(probe["inventory"])["cases"]
    parity = run_parity_spot_checks(cases)
    summary = summarize_records(records)
    runtime = runtime_info()
    git = {
        "branch": run_git(["git", "branch", "--show-current"]),
        "head": run_git(["git", "rev-parse", "HEAD"]),
        "origin_dev": run_git(["git", "rev-parse", "origin/dev"]),
        "status": run_git(["git", "status", "--short"]),
    }
    data_issues = [record["data_issue"] for record in records if record.get("data_issue")]
    return {
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "git": git,
        "runtime": runtime,
        "coverage": probe["coverage"],
        "summary": {
            **summary["raw_summary"],
            "rate_limit": summary["audited_summary"]["rate_limit"],
            "real_business_blocking": summary["audited_summary"]["real_business_problem"],
            "data_field_issues": summary["audited_summary"]["data_field_issue"],
            "probe_rule_noise": summary["audited_summary"]["probe_runner_noise"],
            "performance_warning": summary["audited_summary"]["performance_warning"],
            "raw": summary["raw_summary"],
            "audited": summary["audited_summary"],
        },
        "parity": parity,
        "records": records,
        "slow_top20": _slow_top(records, limit=20),
        "inventory_meta": {
            "total_products": probe["inventory"]["total_products"],
            "categories": probe["inventory"]["categories"],
        },
        "data_issues": data_issues,
    }


def main() -> int:
    report = build_report()
    commit_short = report["git"]["head"][:8]
    timestamp = time.strftime("%Y%m%d_%H%M%S")
    out_path = DEFAULT_REPORT_DIR / f"dev_large_business_probe_{timestamp}_{commit_short}.json"
    out_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(
        json.dumps(
            {
                "report": str(out_path),
                "coverage": report["coverage"],
                "summary": report["summary"],
                "parity": report["parity"]["summary"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    audited = report["summary"]["audited"]
    return 0 if audited["fail"] == 0 and audited["blocking_fail"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
