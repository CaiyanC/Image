from __future__ import annotations

import json
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path


BASE_URL = "http://127.0.0.1:8001"
PARITY_HEADER = "X-Customer-Service-Parity-Isolation"

CASES = [
    {
        "id": "tw141_weight_language",
        "question": "两个人周末去露营，主要烧水和煮面，想要一口不费脑子、别太重的锅，你更推荐哪款？",
    },
    {
        "id": "cw06pro_light_language",
        "question": "两个人一起露营，既要烧水又要煮面，想买个轻一点但别小得可怜的锅，怎么选？",
    },
    {
        "id": "cfpg19_cleaning_language",
        "question": "我有卡式炉，想买烤盘，优先推荐资料明确写了好清洁的。",
    },
    {
        "id": "comparison_listing_leak",
        "question": "CW-C93 和 CW-C83，哪一个更适合轻量徒步？请说说理由。",
    },
    {
        "id": "cw_c78_weight_boundary",
        "question": "CW-C78 拿起来会不会很重？我主要周末短途带着走。",
    },
    {
        "id": "cw_s10_capacity_boundary",
        "question": "CW-S10-1 实际装水大概是什么量？两个人煮面够不够？",
    },
]


def post(base_url: str, path: str, payload: dict, token: str) -> tuple[int, dict, float]:
    headers = {
        "Content-Type": "application/json; charset=utf-8",
        PARITY_HEADER: "true",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = urllib.request.Request(
        base_url.rstrip("/") + path,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    started = time.perf_counter()
    try:
        with urllib.request.urlopen(request, timeout=300) as response:
            body = json.loads(response.read().decode("utf-8", errors="replace"))
            return response.status, body, round((time.perf_counter() - started) * 1000, 1)
    except urllib.error.HTTPError as error:
        raw = error.read().decode("utf-8", errors="replace")
        try:
            body = json.loads(raw)
        except json.JSONDecodeError:
            body = {"error": raw}
        return error.code, body, round((time.perf_counter() - started) * 1000, 1)


def compact(case: dict, status: int, body: dict, elapsed_ms: float) -> dict:
    debug = body.get("debug") if isinstance(body.get("debug"), dict) else {}
    metadata = body.get("answer_metadata") if isinstance(body.get("answer_metadata"), dict) else {}
    trace = debug.get("trace") if isinstance(debug.get("trace"), dict) else {}
    llm_calls = trace.get("llm_calls") if isinstance(trace.get("llm_calls"), list) else []
    narrative = metadata.get("recommendation_narrative") if isinstance(metadata.get("recommendation_narrative"), dict) else {}
    return {
        "id": case["id"],
        "question": case["question"],
        "status": status,
        "elapsed_ms": elapsed_ms,
        "answer": body.get("answer"),
        "result_skus": body.get("result_skus") or [],
        "evidence": body.get("evidence") or [],
        "sources": body.get("sources") or [],
        "answer_metadata": metadata,
        "agent_mode": debug.get("agent_mode"),
        "semantic_preplan": debug.get("semantic_preplan"),
        "selected_knowledge_evidence": debug.get("knowledge_selected_evidence"),
        "knowledge_evidence_selection": debug.get("knowledge_evidence_selection"),
        "recommendation_narrative": narrative,
        "recommendation_narrative_diagnostics": debug.get("recommendation_narrative_diagnostics"),
        "candidate_verifications": debug.get("candidate_verifications"),
        "semantic_constraints": debug.get("semantic_constraints"),
        "semantic_soft_preferences": debug.get("semantic_soft_preferences"),
        "final_answer_audit": metadata.get("final_answer_audit"),
        "semantic_postprocess_changed": debug.get("semantic_postprocess_changed"),
        "semantic_postprocess_snapshot": debug.get("semantic_postprocess_snapshot"),
        "llm_calls": [
            {
                "purpose": item.get("purpose"),
                "model": item.get("model"),
                "prompt_chars": item.get("prompt_chars"),
                "completion_chars": item.get("completion_chars"),
                "elapsed_ms": item.get("elapsed_ms"),
                "error": item.get("error"),
            }
            for item in llm_calls
            if isinstance(item, dict)
        ],
    }


def main() -> int:
    base_url = sys.argv[1] if len(sys.argv) > 1 else BASE_URL
    status, login, elapsed = post(
        base_url,
        "/api/auth/login",
        {"username": "admin", "password": "admin123"},
        "",
    )
    if status != 200 or not login.get("access_token"):
        print(json.dumps({"login_status": status, "login": login, "elapsed_ms": elapsed}, ensure_ascii=False))
        return 2
    token = str(login["access_token"])
    records: list[dict] = []
    for case in CASES:
        status, body, elapsed = post(
            base_url,
            "/api/customer-service/ask?debug=true",
            {"question": case["question"]},
            token,
        )
        record = compact(case, status, body, elapsed)
        records.append(record)
        print(
            json.dumps(
                {
                    "id": record["id"],
                    "status": record["status"],
                    "elapsed_ms": record["elapsed_ms"],
                    "result_skus": record["result_skus"],
                    "agent_mode": record["agent_mode"],
                    "answer": record["answer"],
                    "llm_purposes": [item["purpose"] for item in record["llm_calls"]],
                },
                ensure_ascii=False,
            ),
            flush=True,
        )
    report = {
        "name": "semantic_rag_root_cause_trace",
        "base_url": base_url,
        "started_at": datetime.now().astimezone().isoformat(),
        "case_count": len(records),
        "records": records,
    }
    report_path = Path("reports") / f"semantic_rag_root_cause_trace_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"report": str(report_path), "case_count": len(records)}, ensure_ascii=False), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
