import json
import logging
import os
import sys
import time
from typing import Any

from fastapi.testclient import TestClient

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.core.config import settings
from app.core.database import SessionLocal
from app.core.security import create_access_token, get_user_permissions
from app.main import app
from app.models.user import User
from app.services import customer_perf_service


logging.basicConfig(level=logging.INFO, format="%(message)s")
logging.getLogger("sqlalchemy").setLevel(logging.WARNING)
logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)
logging.getLogger("sqlalchemy.pool").setLevel(logging.WARNING)


D_TURNS = [
    "推荐一款适合2个人露营做饭的锅",
    "为什么推荐这个",
    "换一个推荐，不要刚才那个",
]


QUESTIONS = [
    ("A", "推荐一款适合2个人露营做饭的锅"),
    ("B", "你们产品在哪里可以买到"),
    ("C", "旋焰酒精炉表面处理是什么"),
    ("D", "推荐一款适合2个人露营做饭的锅\n为什么推荐这个\n换一个推荐，不要刚才那个"),
]


def pick_user() -> User:
    db = SessionLocal()
    try:
        users = db.query(User).all()
        for user in users:
            permissions = set(get_user_permissions(db, user.id))
            if "ai.customer_service" in permissions:
                return user
        if users:
            return users[0]
        raise RuntimeError("数据库里没有用户")
    finally:
        db.close()


def parse_sse(response) -> tuple[list[dict[str, Any]], float | None, float | None, str]:
    started_at = time.perf_counter()
    events: list[dict[str, Any]] = []
    first_delta_ms: float | None = None
    done_ms: float | None = None
    answer_parts: list[str] = []
    current_event: dict[str, Any] = {}

    for raw_line in response.iter_lines():
        line = raw_line.decode("utf-8") if isinstance(raw_line, bytes) else str(raw_line)
        if not line:
            if current_event:
                events.append(current_event)
                if current_event.get("event") == "answer_delta" and first_delta_ms is None:
                    first_delta_ms = (time.perf_counter() - started_at) * 1000.0
                if current_event.get("event") == "done":
                    done_ms = (time.perf_counter() - started_at) * 1000.0
                if current_event.get("event") == "answer_delta":
                    data = current_event.get("data") or {}
                    answer_parts.append(str(data.get("text") or ""))
                current_event = {}
            continue
        if line.startswith("event: "):
            current_event["event"] = line[len("event: "):].strip()
        elif line.startswith("data: "):
            try:
                current_event["data"] = json.loads(line[len("data: "):])
            except json.JSONDecodeError:
                current_event["data"] = {"raw": line[len("data: "):]}
    if current_event:
        events.append(current_event)
    answer = "".join(answer_parts)
    return events, first_delta_ms, done_ms, answer


def summarize_state(state: dict[str, Any] | None) -> dict[str, Any]:
    if not state:
        return {}
    stages = list(state.get("stages") or [])
    slowest = sorted(stages, key=lambda item: float(item.get("elapsed_ms") or 0), reverse=True)[:3]
    return {
        "llm_call_count": len(state.get("llm_calls") or []),
        "llm_calls": state.get("llm_calls") or [],
        "stages": stages,
        "slowest_3": slowest,
        "first_answer_delta_ms": state.get("first_answer_delta_at"),
        "done_ms": state.get("done_at"),
    }


def extract_result_skus(meta: dict[str, Any] | None) -> list[str]:
    if not meta:
        return []
    results = meta.get("results") or []
    skus = []
    for item in results:
        if isinstance(item, dict):
            sku = str(item.get("sku") or "").strip().upper()
            if sku and sku not in skus:
                skus.append(sku)
    debug = meta.get("debug") or {}
    for item in (debug.get("raw_results") or []):
        if isinstance(item, dict):
            sku = str(item.get("sku") or "").strip().upper()
            if sku and sku not in skus:
                skus.append(sku)
    return skus


def infer_fallback(state_summary: dict[str, Any], meta: dict[str, Any] | None) -> bool:
    stage_names = [str(item.get("stage") or "") for item in state_summary.get("stages") or []]
    if any("fallback" in stage or "legacy_rule_agent" in stage for stage in stage_names):
        return True
    debug = (meta or {}).get("debug") or {}
    agent_mode = str(debug.get("agent_mode") or "")
    return agent_mode in {"guidance", "single_sku_knowledge"}


def run_case(client: TestClient, token: str, label: str, question: str, conversation_id: str | None = None) -> dict[str, Any]:
    headers = {"Authorization": f"Bearer {token}"}
    payload = {"question": question}
    if conversation_id:
        payload["conversation_id"] = conversation_id
    with client.stream(
        "POST",
        "/api/customer-service/ask-stream",
        headers=headers,
        json=payload,
    ) as response:
        response.raise_for_status()
        events, first_delta_ms, done_ms, answer = parse_sse(response)

    state_summary = summarize_state(customer_perf_service.get_state())
    meta = None
    for event in events:
        if event.get("event") == "meta":
            meta = event.get("data") or {}
            break
    result = {
        "label": label,
        "question": question,
        "final_answer": answer,
        "conversation_id": (meta or {}).get("conversation_id"),
        "agent_mode": (meta or {}).get("debug", {}).get("agent_mode"),
        "intent": (meta or {}).get("intent"),
        "result_skus": extract_result_skus(meta),
        "fallback_used": infer_fallback(state_summary, meta),
        "llm_call_count": state_summary.get("llm_call_count", 0),
        "llm_calls": state_summary.get("llm_calls", []),
        "stages": state_summary.get("stages", []),
        "slowest_3": state_summary.get("slowest_3", []),
        "total_ms": next((item.get("elapsed_ms") for item in reversed(state_summary.get("stages", [])) if item.get("stage") in {"ask_stream.total", "ask_api.total", "ask_customer_service.total"}), None),
        "first_token_ms": first_delta_ms,
        "sse_done_ms": done_ms,
        "meta": meta,
        "events": events,
    }
    return result


def run_sequence_case(client: TestClient, token: str, label: str, turns: list[str]) -> dict[str, Any]:
    turn_reports: list[dict[str, Any]] = []
    conversation_id: str | None = None
    for index, question in enumerate(turns, start=1):
        turn_report = run_case(client, token, f"{label}{index}", question, conversation_id=conversation_id)
        turn_reports.append(turn_report)
        conversation_id = conversation_id or turn_report.get("conversation_id")
    return {
        "label": label,
        "conversation_id": conversation_id,
        "turns": turn_reports,
        "final_answer": turn_reports[-1].get("final_answer") if turn_reports else "",
        "agent_mode": turn_reports[-1].get("agent_mode") if turn_reports else None,
        "intent": turn_reports[-1].get("intent") if turn_reports else None,
        "result_skus": turn_reports[-1].get("result_skus") if turn_reports else [],
        "fallback_used": any(turn.get("fallback_used") for turn in turn_reports),
        "llm_call_count": sum(int(turn.get("llm_call_count") or 0) for turn in turn_reports),
        "llm_calls": [call for turn in turn_reports for call in (turn.get("llm_calls") or [])],
        "stages": [stage for turn in turn_reports for stage in (turn.get("stages") or [])],
        "slowest_3": sorted(
            [stage for turn in turn_reports for stage in (turn.get("stages") or [])],
            key=lambda item: float(item.get("elapsed_ms") or 0),
            reverse=True,
        )[:3],
        "total_ms": sum(float(turn.get("total_ms") or 0) for turn in turn_reports if turn.get("total_ms") is not None),
        "first_token_ms": turn_reports[0].get("first_token_ms") if turn_reports else None,
        "sse_done_ms": turn_reports[-1].get("sse_done_ms") if turn_reports else None,
        "meta": turn_reports[-1].get("meta") if turn_reports else None,
        "events": [event for turn in turn_reports for event in (turn.get("events") or [])],
    }


def main() -> None:
    user = pick_user()
    token = create_access_token({"sub": str(user.id)})
    client = TestClient(app)
    perm_db = SessionLocal()
    try:
        permissions = sorted(set(get_user_permissions(perm_db, user.id)))
    finally:
        perm_db.close()

    print(json.dumps({
        "user_id": str(user.id),
        "username": user.username,
        "permissions": permissions,
        "db_url": settings.DATABASE_URL,
    }, ensure_ascii=False))

    reports: list[dict[str, Any]] = []
    for label, question in QUESTIONS:
        if label == "D":
            continue
        print(f"\n=== QUESTION {label} ===")
        result = run_case(client, token, label, question)
        reports.append(result)
        print(json.dumps(result, ensure_ascii=False, default=str, indent=2))

    print("\n=== QUESTION D ===")
    d_result = run_sequence_case(client, token, "D", D_TURNS)
    reports.append(d_result)
    print(json.dumps(d_result, ensure_ascii=False, default=str, indent=2))

    report_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "reports", "customer_service_perf_probe_summary.json"))
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(reports, f, ensure_ascii=False, indent=2, default=str)
    print(f"\nWrote summary to {report_path}")


if __name__ == "__main__":
    main()
