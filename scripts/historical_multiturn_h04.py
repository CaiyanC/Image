"""Audit H-04 product anchoring through real UTF-8 normal and SSE requests."""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Any


BASE_URL = os.environ.get("CUSTOMER_SERVICE_BASE_URL", "http://127.0.0.1:8001").rstrip("/")
OUT_DIR = Path(__file__).resolve().parents[1] / "backend" / "runtime"
H04_TURN_1 = "\u518d\u770b\u5929\u9e45\u58f64\u676f\u9ed1\u8272\u3002"
H04_TURN_2 = "\u5b83\u9002\u5408\u9732\u8425\u5417\uff1f"
H04_TURN_3 = "\u5b83\u6709\u51e0\u4e2a\u676f\u5b50\uff1f"
H04_TURN_4 = "\u9ed1\u8272\u8fd9\u6b3e\u600e\u4e48\u6e05\u6d17\uff1f"
H04_TURNS = (H04_TURN_1, H04_TURN_2, H04_TURN_3, H04_TURN_4)
TURNS = [
    "再看天鹅壶4杯黑。",
    "它适合露营吗？",
    "它有几个杯子？",
    "黑色这款怎么清洗？",
]


def _request(path: str, payload: dict[str, Any], token: str) -> tuple[int, bytes]:
    request = urllib.request.Request(
        BASE_URL + path,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {token}"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=180) as response:
            return response.status, response.read()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read()


def _login() -> str:
    request = urllib.request.Request(
        BASE_URL + "/api/auth/login",
        data=json.dumps({
            "username": os.environ.get("DEFAULT_ADMIN_USERNAME", "admin"),
            "password": os.environ.get("DEFAULT_ADMIN_PASSWORD", "admin123"),
        }, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.loads(response.read().decode("utf-8"))["access_token"]


def _parse_sse(body: bytes) -> dict[str, Any]:
    answer: list[str] = []
    meta: dict[str, Any] = {}
    trace: dict[str, Any] = {}
    current: dict[str, Any] = {}
    for raw_line in body.decode("utf-8", errors="replace").splitlines():
        line = raw_line.strip("\r")
        if not line:
            event = current.get("event")
            payload = current.get("data")
            if event in {"content", "answer_delta"} and isinstance(payload, dict):
                text = payload.get("content") or payload.get("text")
                if isinstance(text, str):
                    answer.append(text)
            elif event == "meta" and isinstance(payload, dict):
                meta = payload
            elif event == "trace" and isinstance(payload, dict):
                trace = payload
            current = {}
            continue
        if line.startswith("event:"):
            current["event"] = line.split(":", 1)[1].strip()
            continue
        if not line.startswith("data:"):
            continue
        try:
            current["data"] = json.loads(line.split(":", 1)[1].strip())
        except json.JSONDecodeError:
            continue
    payload = dict(meta)
    payload["answer"] = "".join(answer) or str(payload.get("answer") or "")
    if trace:
        payload["debug_trace"] = trace
    return payload


def _record(question: str, status: int, payload: dict[str, Any]) -> dict[str, Any]:
    debug = payload.get("debug") if isinstance(payload.get("debug"), dict) else {}
    entity = debug.get("entity_resolution_contract") if isinstance(debug.get("entity_resolution_contract"), dict) else {}
    return {
        "question": question,
        "received_question": (debug.get("plan") or {}).get("raw_question"),
        "status": status,
        "answer": payload.get("answer", ""),
        "conversation_id": payload.get("conversation_id"),
        "result_skus": payload.get("result_skus", []),
        "warnings": payload.get("warnings", []),
        "agent_mode": debug.get("agent_mode"),
        "resolved_sku": entity.get("resolved_sku"),
        "evidence_skus": [item.get("sku") for item in payload.get("evidence", []) if isinstance(item, dict)],
    }


def _run_mode(token: str, *, stream: bool) -> list[dict[str, Any]]:
    conversation_id: str | None = None
    records: list[dict[str, Any]] = []
    for question in H04_TURNS:
        body = {"question": question}
        if conversation_id:
            body["conversation_id"] = conversation_id
        status, raw = _request("/api/customer-service/ask-stream" if stream else "/api/customer-service/ask?debug=true", body, token)
        payload = _parse_sse(raw) if stream else json.loads(raw.decode("utf-8"))
        record = _record(question, status, payload)
        records.append(record)
        conversation_id = str(payload.get("conversation_id") or conversation_id or "") or None
    return records


def main() -> int:
    token = _login()
    result = {"normal": _run_mode(token, stream=False), "stream": _run_mode(token, stream=True)}
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    path = OUT_DIR / f"historical_multiturn_h04_{stamp}.json"
    path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"artifact": str(path), "modes": list(result)}, ensure_ascii=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
