"""Run a real HTTP audit of historical customer-service failure surfaces."""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path


BASE_URL = os.environ.get("CUSTOMER_SERVICE_BASE_URL", "http://127.0.0.1:8001").rstrip("/")
OUT_DIR = Path(__file__).resolve().parents[1] / "backend" / "runtime"


def _questions() -> list[dict[str, str]]:
    exact = [
        ("U12-01", "CF-PG19 原厂配了什么？", "contents"),
        ("U12-02", "CF-PG19 盒子里有什么？", "contents"),
        ("U12-03", "瓦片烤盘Pro怎么清洁？", "usage"),
        ("U12-04", "瓦片烤盘Pro包装里有什么？", "contents"),
        ("U12-05", "瓦片烤盘 标配有什么？", "contents"),
        ("U12-06", "炊墨套锅 包装清单是什么？", "contents"),
        ("H04-01", "再看天鹅壶4杯黑。", "entity"),
        ("H04-02", "它适合露营吗？", "multiturn"),
        ("H04-03", "它有几个杯子？", "multiturn"),
        ("H04-04", "黑色这款怎么清洗？", "multiturn"),
        ("SAFE-01", "CF-PG19 有保修吗？", "missing"),
        ("SAFE-02", "CF-PG19 说明书在哪里下载？", "missing"),
        ("SAFE-03", "CF-PG19 现在库存多少？", "missing"),
        ("SAFE-04", "CF-PG19 最低多少钱？", "missing"),
        ("QA-01", "WS-B20 的容量是多少？", "qa"),
        ("QA-02", "WS-B20 有多重？", "qa"),
        ("QA-03", "WS-B20 尺寸多大？", "qa"),
        ("QA-04", "WS-B20 能直接放明火上吗？", "conflict"),
        ("QA-05", "WS-B20 能在燃气灶上加热吗？", "conflict"),
        ("QA-06", "WS-B20 第一次使用要预热倒油吗？", "conflict"),
        ("HEAT-01", "CW-C83 能不能用酒精炉？", "heat"),
        ("HEAT-02", "CW-C01-37 支持酒精炉吗？", "heat"),
        ("HEAT-03", "CW-S10-A 是不是支持酒精炉？", "heat"),
        ("HEAT-04", "CW-C65-4 可以放电磁炉吗？", "heat"),
        ("HEAT-05", "CF-PG19 支持哪些炉具？", "heat"),
        ("ENTITY-01", "天鹅壶4杯黑和9杯白有什么区别？", "entity"),
        ("ENTITY-02", "KW-K31 和 KW-K32 哪个是4杯？", "entity"),
        ("ENTITY-03", "婧川水壶有没有附件？", "ambiguity"),
        ("ENTITY-04", "围雪炉盒子里有什么？", "ambiguity"),
        ("REC-01", "一个人徒步想轻一点，推荐一个锅。", "recommendation"),
        ("REC-02", "两个人露营想买套锅，怎么选？", "recommendation"),
        ("REC-03", "四个人露营容量大一点的锅具推荐什么？", "recommendation"),
        ("REC-04", "适合酒精炉的锅具给几个选择。", "recommendation"),
        ("REC-05", "不要太贵、不要太重、还要好收纳，买哪个？", "recommendation"),
        ("CMP-01", "CW-C06PRO 和 CW-C19T-37 有什么区别？", "comparison"),
        ("CMP-02", "轻途套锅和享野套锅哪个适合新手？", "comparison"),
        ("CMP-03", "行山单锅和激川单锅哪个更轻？", "comparison"),
        ("CMP-04", "CF-PG19 和 CF-PG20 材质有什么差别？", "comparison"),
        ("CMP-05", "CW-C83 和 CW-C93 容量区别是什么？", "comparison"),
        ("CMP-06", "CW-C06PRO 和 CW-C76 哪个更适合露营？", "comparison"),
    ]
    skus = ["CW-C83", "CW-C93", "CW-C06PRO", "CW-C19T-37", "CF-PG19", "CF-PG20", "CS-B02-37", "CS-G28", "TW-503", "WS-B20"]
    fields = [
        ("材质是什么？", "material"), ("尺寸是多少？", "dimensions"), ("重量多少？", "weight"),
        ("容量多大？", "capacity"), ("适合什么场景？", "usage"), ("有什么卖点？", "selling_points"),
    ]
    generated: list[tuple[str, str, str]] = []
    for index, sku in enumerate(skus):
        for suffix, field in fields:
            generated.append((f"MATRIX-{index:02d}-{field}", f"{sku} {suffix}", field))
    questions = exact + generated
    assert len(questions) == 100, len(questions)
    return [{"case_id": a, "question": b, "family": c} for a, b, c in questions]


def _request(path: str, payload: dict, token: str | None = None, timeout: int = 180) -> tuple[int, bytes]:
    request = urllib.request.Request(
        BASE_URL + path,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json", **({"Authorization": f"Bearer {token}"} if token else {})},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.status, response.read()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read()


def _stream_answer(body: bytes) -> str:
    answer: list[str] = []
    event = ""
    for line in body.decode("utf-8", errors="replace").splitlines():
        if line.startswith("event: "):
            event = line[7:].strip()
            continue
        if not line.startswith("data: "):
            continue
        try:
            data = json.loads(line[6:])
        except json.JSONDecodeError:
            continue
        if not isinstance(data, dict):
            continue
        if event == "content" and isinstance(data.get("content"), str):
            answer.append(data["content"])
        elif event == "answer_delta" and isinstance(data.get("text"), str):
            answer.append(data["text"])
    return "".join(answer)


def main() -> int:
    username = os.environ.get("DEFAULT_ADMIN_USERNAME", "admin")
    password = os.environ.get("DEFAULT_ADMIN_PASSWORD", "admin123")
    status, body = _request("/api/auth/login", {"username": username, "password": password}, timeout=30)
    if status != 200:
        raise RuntimeError(f"login failed: {status} {body.decode('utf-8', errors='replace')[:500]}")
    token = json.loads(body.decode("utf-8"))["access_token"]
    cases = _questions()
    records: list[dict] = []
    for index, case in enumerate(cases):
        started = time.perf_counter()
        normal_status, normal_body = _request("/api/customer-service/ask", {"question": case["question"]}, token)
        elapsed = round((time.perf_counter() - started) * 1000, 1)
        try:
            normal = json.loads(normal_body.decode("utf-8"))
        except json.JSONDecodeError:
            normal = {}
        record = {
            **case, "normal_status": normal_status, "normal_answer": normal.get("answer", ""),
            "normal_answer_type": normal.get("answer_type", ""), "normal_intent": normal.get("intent", ""),
            "normal_warnings": normal.get("warnings", []), "normal_elapsed_ms": elapsed,
            "normal_nonempty": bool(str(normal.get("answer", "")).strip()),
        }
        if index % 5 == 0:
            stream_status, stream_body = _request("/api/customer-service/ask-stream", {"question": case["question"]}, token)
            record["stream_status"] = stream_status
            record["stream_answer"] = _stream_answer(stream_body)
            record["stream_nonempty"] = bool(record["stream_answer"].strip())
        records.append(record)
        print(f"{index + 1:03d}/100 {case['case_id']} normal={normal_status}", flush=True)
    summary = {
        "base_url": BASE_URL, "generated_at": datetime.now().isoformat(timespec="seconds"),
        "total_questions": len(records), "normal_200": sum(r["normal_status"] == 200 for r in records),
        "normal_nonempty": sum(r["normal_nonempty"] for r in records),
        "stream_checks": sum("stream_status" in r for r in records),
        "stream_200": sum(r.get("stream_status") == 200 for r in records),
        "stream_nonempty": sum(r.get("stream_nonempty", False) for r in records),
        "families": {family: sum(r["family"] == family for r in records) for family in sorted({r["family"] for r in records})},
    }
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output = OUT_DIR / f"historical_http_audit_100_{stamp}.json"
    output.write_text(json.dumps({"summary": summary, "records": records}, ensure_ascii=False, indent=2), encoding="utf-8")
    report = OUT_DIR / f"historical_http_audit_100_{stamp}.md"
    lines = ["# Historical HTTP Audit (100)", "", json.dumps(summary, ensure_ascii=False, indent=2), "", "| ID | Family | HTTP | Answer |", "|---|---|---:|---|"]
    for item in records:
        answer = str(item["normal_answer"]).replace("|", "\\|").replace("\n", " ")[:240]
        lines.append(f"| {item['case_id']} | {item['family']} | {item['normal_status']} | {answer} |")
    report.write_text("\n".join(lines), encoding="utf-8")
    print(json.dumps({"summary": summary, "json": str(output), "markdown": str(report)}, ensure_ascii=False, indent=2))
    return 0 if summary["normal_200"] == 100 and summary["normal_nonempty"] == 100 and summary["stream_200"] == summary["stream_checks"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
