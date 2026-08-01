"""Run a small, reproducible UTF-8 HTTP audit against development customer service.

This is an evidence collector, not a pass/fail oracle.  It deliberately keeps
the full debug payload so a reviewer can classify any warning from the earliest
incorrect decision rather than treating an HTTP 200 as a business pass.
"""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Any


BASE_URL = os.environ.get("CUSTOMER_SERVICE_BASE_URL", "http://127.0.0.1:8001").rstrip("/")
OUT_DIR = Path(__file__).resolve().parents[1] / "backend" / "runtime"


def cases() -> list[dict[str, str]]:
    # Keep Chinese source text ASCII-only.  This script must remain portable
    # across shells that have previously corrupted UTF-8 audit inputs.
    return [
        {"case_id": "field-material", "family": "field", "question": "CW-C83 \u6750\u8d28\u662f\u4ec0\u4e48\uff1f"},
        {"case_id": "field-missing", "family": "safe_missing", "question": "CF-PG19 \u6709\u4fdd\u4fee\u5417\uff1f"},
        {"case_id": "qa-grounded", "family": "same_sku_qa", "question": "\u8f6c\u8f6c\u78e8\u8c46\u5668\u7814\u78e8\u7c97\u7ec6\u80fd\u8c03\u5417\uff1f"},
        {"case_id": "qa-pollution-boundary", "family": "cross_category_boundary", "question": "\u5929\u9e45\u58f64\u676f\u9ed1\u8272\u7814\u78e8\u7c97\u7ec6\u80fd\u8c03\u5417\uff1f"},
        {"case_id": "accessories", "family": "contents", "question": "CF-PG19 \u539f\u5382\u914d\u4e86\u4ec0\u4e48\uff1f"},
        {"case_id": "heat", "family": "compatibility", "question": "CW-C83 \u80fd\u4e0d\u80fd\u7528\u9152\u7cbe\u7089\uff1f"},
        {"case_id": "compare", "family": "comparison", "question": "CW-C83 \u548c CW-C06PRO \u7684\u6536\u7eb3\u548c\u8d1f\u91cd\u600e\u4e48\u6bd4\uff1f"},
        {"case_id": "recommend-material", "family": "recommendation", "question": "\u60f3\u4e70\u786c\u8d28\u6c27\u5316\u94dd\u5957\u9505\uff0c\u6709\u54ea\u4e9b\u9002\u5408\u5361\u5f0f\u7089\u7684\u9009\u62e9\uff1f"},
        {"case_id": "recommend-unbound", "family": "recommendation", "question": "\u9001\u793c\u7684\u6237\u5916\u88c5\u5907\u8be5\u600e\u4e48\u9009\uff1f"},
        {"case_id": "ambiguity", "family": "ambiguity", "question": "\u56f4\u96ea\u7089\u6709\u54ea\u4e9b\u6b3e\uff1f"},
        {"case_id": "category", "family": "category", "question": "\u5bb9\u91cf\u4e0d\u5c0f\u4e8e1\u5347\u7684\u6c34\u58f6\u6709\u54ea\u4e9b\uff1f"},
        {"case_id": "open-rag", "family": "open_product", "question": "\u8f6c\u8f6c\u78e8\u8c46\u5668\u5728\u51fa\u95e8\u51b2\u5496\u5561\u65f6\u600e\u4e48\u7528\u6bd4\u8f83\u987a\u624b\uff1f"},
    ]


H04_TURNS = [
    "\u518d\u770b\u5929\u9e45\u58f64\u676f\u9ed1\u8272\u3002",
    "\u5b83\u9002\u5408\u9732\u8425\u5417\uff1f",
    "\u5b83\u6709\u51e0\u4e2a\u676f\u5b50\uff1f",
    "\u9ed1\u8272\u8fd9\u6b3e\u600e\u4e48\u6e05\u6d17\uff1f",
]


def request(path: str, payload: dict[str, Any], token: str, timeout: int = 180) -> tuple[int, bytes]:
    req = urllib.request.Request(
        BASE_URL + path,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {token}"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            return response.status, response.read()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read()


def login() -> str:
    req = urllib.request.Request(
        BASE_URL + "/api/auth/login",
        data=json.dumps({"username": os.getenv("DEFAULT_ADMIN_USERNAME", "admin"), "password": os.getenv("DEFAULT_ADMIN_PASSWORD", "admin123")}).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=30) as response:
        return json.loads(response.read().decode("utf-8"))["access_token"]


def parse_sse(body: bytes) -> dict[str, Any]:
    answer: list[str] = []
    meta: dict[str, Any] = {}
    trace: dict[str, Any] = {}
    event: str | None = None
    for raw in body.decode("utf-8", errors="replace").splitlines():
        if raw.startswith("event:"):
            event = raw.split(":", 1)[1].strip()
            continue
        if not raw.startswith("data:"):
            continue
        try:
            value = json.loads(raw.split(":", 1)[1].strip())
        except json.JSONDecodeError:
            continue
        if event in {"content", "answer_delta"} and isinstance(value, dict):
            answer.append(str(value.get("content") or value.get("text") or ""))
        elif event == "meta" and isinstance(value, dict):
            meta = value
        elif event == "trace" and isinstance(value, dict):
            trace = value
    result = dict(meta)
    result["answer"] = "".join(answer) or str(result.get("answer") or "")
    if trace:
        result["debug_trace"] = trace
    return result


def compact_record(case: dict[str, str], mode: str, status: int, payload: dict[str, Any], elapsed_ms: float) -> dict[str, Any]:
    debug = payload.get("debug") if isinstance(payload.get("debug"), dict) else {}
    trace = payload.get("debug_trace") if isinstance(payload.get("debug_trace"), dict) else {}
    debug = debug or trace
    plan = debug.get("plan") if isinstance(debug.get("plan"), dict) else {}
    entity = debug.get("entity_resolution_contract") if isinstance(debug.get("entity_resolution_contract"), dict) else {}
    return {
        **case,
        "endpoint_mode": mode,
        "status": status,
        "elapsed_ms": elapsed_ms,
        "received_question": plan.get("raw_question"),
        "answer": payload.get("answer", ""),
        "answer_type": payload.get("answer_type"),
        "warnings": payload.get("warnings", []),
        "agent_mode": debug.get("agent_mode"),
        "semantic_preplan": plan.get("semantic_preplan"),
        "field_contract": debug.get("field_contract"),
        "entity_contract": entity,
        "resolved_sku": entity.get("resolved_sku"),
        "result_skus": payload.get("result_skus", []),
        "evidence_skus": [item.get("sku") for item in payload.get("evidence", []) if isinstance(item, dict)],
        "evidence": payload.get("evidence", []),
        "manual_verdict": "REVIEW",
        "manual_reason": "Unreviewed fresh HTTP evidence.",
    }


def run_case(token: str, case: dict[str, str], conversation_id: str | None = None) -> tuple[list[dict[str, Any]], str | None]:
    body: dict[str, Any] = {"question": case["question"]}
    if conversation_id:
        body["conversation_id"] = conversation_id
    records: list[dict[str, Any]] = []
    next_conversation = conversation_id
    for path, mode in (("/api/customer-service/ask?debug=true", "normal"), ("/api/customer-service/ask-stream", "stream")):
        started = time.perf_counter()
        status, raw = request(path, body, token)
        elapsed = round((time.perf_counter() - started) * 1000, 1)
        payload = parse_sse(raw) if mode == "stream" else json.loads(raw.decode("utf-8", errors="replace"))
        records.append(compact_record(case, mode, status, payload, elapsed))
        next_conversation = str(payload.get("conversation_id") or next_conversation or "") or None
    return records, next_conversation


def main() -> int:
    token = login()
    records: list[dict[str, Any]] = []
    for case in cases():
        current, _ = run_case(token, case)
        records.extend(current)
        print(case["case_id"], flush=True)
    for mode in ("normal", "stream"):
        conversation_id: str | None = None
        for index, question in enumerate(H04_TURNS, start=1):
            case = {"case_id": f"h04-{index}", "family": "multiturn", "question": question}
            current, conversation_id = run_case(token, case, conversation_id)
            records.extend([item for item in current if item["endpoint_mode"] == mode])
    summary = {
        "base_url": BASE_URL,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "records": len(records),
        "http_200": sum(item["status"] == 200 for item in records),
        "nonempty_answers": sum(bool(str(item["answer"]).strip()) for item in records),
        "warnings": sum(bool(item["warnings"]) for item in records),
    }
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    path = OUT_DIR / f"fresh_customer_service_http_audit_{datetime.now():%Y%m%d_%H%M%S}.json"
    path.write_text(json.dumps({"summary": summary, "records": records}, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"summary": summary, "artifact": str(path)}, ensure_ascii=False, indent=2))
    return 0 if summary["http_200"] == len(records) and summary["nonempty_answers"] == len(records) else 1


if __name__ == "__main__":
    raise SystemExit(main())
