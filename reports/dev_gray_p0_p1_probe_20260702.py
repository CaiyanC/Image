# -*- coding: utf-8 -*-
from __future__ import annotations

import codecs
import json
import time
from pathlib import Path
from typing import Any

import requests


BASE_URL = "http://127.0.0.1:8001"
ENV_FILE = Path(r"D:\CaiYan\Image-n065-audit\backend\.env.dev")
OUT_FILE = Path(r"D:\CaiYan\Image-n065-audit\reports\dev_gray_p0_p1_probe_20260702.json")


def u(value: str) -> str:
    return codecs.decode(value, "unicode_escape")


def load_env(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip() or line.lstrip().startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def post_json(path: str, payload: dict[str, Any], token: str | None = None, timeout: int = 180) -> tuple[int, bytes]:
    headers = {"Content-Type": "application/json; charset=utf-8"}
    if token:
        headers["Authorization"] = "Bearer " + token
    response = requests.post(BASE_URL + path, json=payload, headers=headers, timeout=timeout)
    return response.status_code, response.content


def login() -> str:
    env = load_env(ENV_FILE)
    username = env.get("DEFAULT_ADMIN_USERNAME") or env.get("ADMIN_USERNAME")
    password = env.get("DEFAULT_ADMIN_PASSWORD") or env.get("ADMIN_PASSWORD")
    status, body = post_json("/api/auth/login", {"username": username, "password": password}, timeout=30)
    if status >= 400:
        raise RuntimeError(body.decode("utf-8", errors="replace"))
    return json.loads(body.decode("utf-8"))["access_token"]


def parse_sse(body: bytes) -> tuple[str, dict[str, Any]]:
    current: dict[str, Any] = {}
    answer_parts: list[str] = []
    events: list[dict[str, Any]] = []
    for line in body.decode("utf-8", errors="replace").splitlines():
        if line == "":
            if current:
                events.append(current)
            event = current.get("event")
            data = current.get("data") or {}
            if event in {"answer_delta", "content"}:
                answer_parts.append(str(data.get("text") or data.get("content") or ""))
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
        events.append(current)
    meta = next((event.get("data") for event in events if event.get("event") == "meta"), {}) or {}
    answer = "".join(answer_parts).strip() or str(meta.get("answer") or "")
    return answer, meta


def ask(token: str, label: str, question: str, conversation_id: str | None = None) -> dict[str, Any]:
    payload: dict[str, Any] = {"question": question}
    if conversation_id:
        payload["conversation_id"] = conversation_id
    started = time.perf_counter()
    status, body = post_json("/api/customer-service/ask-stream", payload, token=token, timeout=180)
    elapsed = round((time.perf_counter() - started) * 1000, 1)
    if status >= 400:
        return {"label": label, "ok": False, "status": status, "error": body.decode("utf-8", errors="replace"), "elapsed_ms": elapsed}
    answer, meta = parse_sse(body)
    debug = meta.get("debug") if isinstance(meta.get("debug"), dict) else {}
    plan = debug.get("plan") if isinstance(debug.get("plan"), dict) else {}
    answer_metadata = meta.get("answer_metadata") if isinstance(meta.get("answer_metadata"), dict) else {}
    timing = answer_metadata.get("timing") if isinstance(answer_metadata.get("timing"), dict) else {}
    result_skus = [str(item or "").strip().upper() for item in meta.get("result_skus") or [] if str(item or "").strip()]
    raw_results = debug.get("raw_results") if isinstance(debug.get("raw_results"), list) else []
    return {
        "label": label,
        "ok": True,
        "status": status,
        "question": question,
        "answer": answer,
        "answer_type": meta.get("answer_type"),
        "intent": meta.get("intent"),
        "agent_mode": meta.get("agent_mode") or debug.get("agent_mode"),
        "primary_intent": plan.get("primary_intent"),
        "tasks": [task.get("type") for task in plan.get("tasks") or [] if isinstance(task, dict)],
        "result_skus": result_skus,
        "metadata_skus": meta.get("skus") or meta.get("candidate_skus") or [],
        "raw_result_skus": [row.get("sku") for row in raw_results[:5] if isinstance(row, dict)],
        "timing": timing,
        "debug_timing": debug.get("timing"),
        "llm_call_count": timing.get("llm_call_count"),
        "conversation_id": meta.get("conversation_id"),
        "elapsed_ms": elapsed,
    }


def main() -> int:
    token = login()
    outputs: list[dict[str, Any]] = []
    singles = [
        ("q05", u(r"\u74e6\u7247\u70e4\u76d8\u5230\u5e95\u591a\u5927\uff1f\u6211\u60f3\u786e\u8ba4\u80fd\u4e0d\u80fd\u653e\u8fdb\u6211\u7684\u6536\u7eb3\u7bb1\u3002")),
        ("q20_no_context", u(r"\u4f60\u521a\u624d\u63a8\u8350\u7684\u7b2c\u4e00\u4e2a\u548c\u7b2c\u4e8c\u4e2a\uff0c\u54ea\u4e2a\u66f4\u9002\u5408\u5973\u751f\u4e00\u4e2a\u4eba\u80cc\uff1f")),
        ("q09", u(r"\u8f7b\u9014\u5957\u9505\u548c\u4eab\u91ce\u5957\u9505\u6709\u4ec0\u4e48\u533a\u522b\uff1f\u6211\u4e24\u4e2a\u4eba\u9732\u8425\u5e94\u8be5\u4e70\u54ea\u4e2a\uff1f")),
    ]
    for label, question in singles:
        outputs.append(ask(token, label, question))
    sequences = {
        "q16": [
            u(r"\u6211\u5468\u672b\u4e24\u4e2a\u4eba\u91ce\u9910\uff0c\u60f3\u4e70\u5957\u9505\u3002"),
            u(r"\u4e3a\u4ec0\u4e48\u63a8\u8350\u8fd9\u4e2a\uff1f"),
            u(r"\u8fd8\u6709\u6ca1\u6709\u66f4\u8f7b\u4fbf\u4e00\u70b9\u7684\uff1f"),
        ],
        "q20_context": [
            u(r"\u6211\u4e00\u4e2a\u4eba\u5f92\u6b65\uff0c\u60f3\u8f7b\u4e00\u70b9\uff0c\u63a8\u8350\u4e24\u4e2a\u9505\u3002"),
            u(r"\u4f60\u521a\u624d\u63a8\u8350\u7684\u7b2c\u4e00\u4e2a\u548c\u7b2c\u4e8c\u4e2a\uff0c\u54ea\u4e2a\u66f4\u9002\u5408\u5973\u751f\u4e00\u4e2a\u4eba\u80cc\uff1f"),
        ],
        "q17": [
            u(r"\u8f7b\u9014\u5957\u9505\u548c\u4eab\u91ce\u5957\u9505\u6709\u4ec0\u4e48\u533a\u522b\uff1f"),
            u(r"\u90a3\u54ea\u4e2a\u66f4\u9002\u5408\u65b0\u624b\uff1f"),
            u(r"\u5b83\u4eec\u80fd\u4e0d\u80fd\u7528\u9152\u7cbe\u7089\uff1f"),
        ],
        "q15": [
            u(r"\u6211\u4e00\u4e2a\u4eba\u5f92\u6b65\uff0c\u60f3\u8f7b\u4e00\u70b9\uff0c\u63a8\u8350\u4e00\u4e2a\u9505\u3002"),
            u(r"\u5b83\u80fd\u4e0d\u80fd\u7528\u9152\u7cbe\u7089\uff1f"),
            u(r"\u6709\u6ca1\u6709\u66f4\u4fbf\u5b9c\u4e00\u70b9\u7684\u66ff\u4ee3\uff1f"),
        ],
    }
    for seq_label, questions in sequences.items():
        conversation_id = None
        for idx, question in enumerate(questions, start=1):
            item = ask(token, f"{seq_label}_t{idx}", question, conversation_id)
            conversation_id = item.get("conversation_id") or conversation_id
            outputs.append(item)
    OUT_FILE.write_text(json.dumps(outputs, ensure_ascii=False, indent=2), encoding="utf-8")
    for item in outputs:
        print(json.dumps({
            "label": item["label"],
            "ok": item["ok"],
            "answer_type": item.get("answer_type"),
            "primary_intent": item.get("primary_intent"),
            "agent_mode": item.get("agent_mode"),
            "result_skus": item.get("result_skus"),
            "elapsed_ms": item.get("elapsed_ms"),
            "answer": str(item.get("answer") or "")[:160],
        }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
