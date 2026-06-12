"""Run customer-service regression cases against a live backend API.

Examples:
  python scripts/customer_service_regression_runner.py --dry-run
  $env:CUSTOMER_SERVICE_TOKEN="..."
  python scripts/customer_service_regression_runner.py --base-url http://127.0.0.1:8001
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CASES = ROOT / "docs" / "customer_service_regression_cases.json"


def main() -> int:
    parser = argparse.ArgumentParser(description="Run customer-service regression cases.")
    parser.add_argument("--cases", default=str(DEFAULT_CASES), help="Path to regression case JSON.")
    parser.add_argument("--base-url", default=os.getenv("CUSTOMER_SERVICE_API_URL", "http://127.0.0.1:8001"))
    parser.add_argument("--token", default=os.getenv("CUSTOMER_SERVICE_TOKEN", ""))
    parser.add_argument("--dry-run", action="store_true", help="Only validate case schema, do not call API.")
    parser.add_argument("--limit", type=int, default=0, help="Run only the first N cases.")
    parser.add_argument("--sleep", type=float, default=0.0, help="Seconds to sleep between cases.")
    parser.add_argument("--timeout", type=float, default=60.0, help="HTTP timeout seconds.")
    args = parser.parse_args()

    payload = load_cases(Path(args.cases))
    cases = payload["cases"][: args.limit or None]
    schema_errors = validate_cases(cases)
    if schema_errors:
        for error in schema_errors:
            print(f"[SCHEMA FAIL] {error}")
        return 2
    if args.dry_run:
        print(f"Dry-run OK: {len(cases)} cases, categories={sorted({case['category'] for case in cases})}")
        return 0
    if not args.token:
        print("Missing token. Set CUSTOMER_SERVICE_TOKEN or pass --token.", file=sys.stderr)
        return 2

    results = []
    for index, case in enumerate(cases, start=1):
        started = time.time()
        try:
            result = run_case(case, args.base_url, args.token, args.timeout)
        except Exception as exc:  # noqa: BLE001 - CLI must keep going.
            result = {
                "id": case["id"],
                "title": case["title"],
                "ok": False,
                "score": 0,
                "errors": [f"runner_error: {exc}"],
                "last_answer": "",
            }
        result["elapsed_ms"] = int((time.time() - started) * 1000)
        results.append(result)
        icon = "PASS" if result["ok"] else "FAIL"
        print(f"[{icon}] {index:03d}/{len(cases)} {case['id']} {case['title']} score={result['score']:.2f}")
        if result["errors"]:
            for error in result["errors"]:
                print(f"  - {error}")
        if args.sleep:
            time.sleep(args.sleep)

    passed = sum(1 for result in results if result["ok"])
    score = sum(result["score"] for result in results) / max(len(results), 1)
    threshold = float(payload.get("pass_threshold", 0.9))
    print("=" * 72)
    print(f"Cases: {len(results)}, passed: {passed}, pass_rate: {passed / max(len(results), 1):.1%}, avg_score: {score:.2f}")
    print(f"Threshold: {threshold:.2f}")
    print("=" * 72)
    return 0 if score >= threshold else 1


def load_cases(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as file:
        data = json.load(file)
    if not isinstance(data, dict) or not isinstance(data.get("cases"), list):
        raise ValueError("case file must contain a top-level cases list")
    return data


def validate_cases(cases: list[dict[str, Any]]) -> list[str]:
    errors: list[str] = []
    seen_ids: set[str] = set()
    required_categories = {"recommendation", "context", "detail", "compare", "write_action", "safety"}
    categories = {str(case.get("category") or "") for case in cases}
    missing_categories = required_categories - categories
    if missing_categories:
        errors.append(f"missing categories: {sorted(missing_categories)}")

    for case in cases:
        case_id = str(case.get("id") or "")
        if not case_id:
            errors.append("case missing id")
        if case_id in seen_ids:
            errors.append(f"duplicate id: {case_id}")
        seen_ids.add(case_id)
        if not case.get("title"):
            errors.append(f"{case_id}: missing title")
        if not isinstance(case.get("turns"), list) or not case["turns"]:
            errors.append(f"{case_id}: turns must be a non-empty list")
        if not isinstance(case.get("expect"), dict):
            errors.append(f"{case_id}: expect must be an object")
    return errors


def run_case(case: dict[str, Any], base_url: str, token: str, timeout: float) -> dict[str, Any]:
    conversation_id = None
    last_response: dict[str, Any] = {}
    for question in case["turns"]:
        last_response = ask(base_url, token, str(question), conversation_id, timeout)
        conversation_id = last_response.get("conversation_id") or conversation_id
    return evaluate_case(case, last_response)


def ask(base_url: str, token: str, question: str, conversation_id: str | None, timeout: float) -> dict[str, Any]:
    body = {"question": question, "conversation_id": conversation_id}
    request = urllib.request.Request(
        f"{base_url.rstrip('/')}/api/customer-service/ask",
        data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json; charset=utf-8",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"HTTP {exc.code}: {detail}") from exc


def evaluate_case(case: dict[str, Any], response: dict[str, Any]) -> dict[str, Any]:
    expect = case.get("expect") or {}
    answer = str(response.get("answer") or "")
    errors: list[str] = []
    checks = 0
    passed = 0

    def check(condition: bool, message: str) -> None:
        nonlocal checks, passed
        checks += 1
        if condition:
            passed += 1
        else:
            errors.append(message)

    if expect.get("intent"):
        check(str(response.get("intent") or "") == str(expect["intent"]), f"intent expected {expect['intent']}, got {response.get('intent')}")
    if expect.get("answer_must_include_any"):
        needles = [str(item) for item in expect["answer_must_include_any"]]
        check(any(item in answer for item in needles), f"answer missing any of {needles}")
    for banned in expect.get("answer_must_not_include") or []:
        check(str(banned) not in answer, f"answer contains banned text: {banned}")
    if expect.get("min_results") is not None:
        check(len(response.get("results") or []) >= int(expect["min_results"]), f"results fewer than {expect['min_results']}")
    if expect.get("requires_sources"):
        check(bool(response.get("sources")), "sources required")
    if expect.get("requires_evidence"):
        check(bool(response.get("evidence")), "evidence required")
    if expect.get("confidence"):
        check(str(response.get("confidence") or "") == str(expect["confidence"]), f"confidence expected {expect['confidence']}, got {response.get('confidence')}")
    if expect.get("uncertainty"):
        check(str(response.get("uncertainty") or "") == str(expect["uncertainty"]), f"uncertainty expected {expect['uncertainty']}, got {response.get('uncertainty')}")
    if expect.get("requires_actions") is not None:
        has_actions = bool(response.get("actions"))
        check(has_actions is bool(expect["requires_actions"]), f"actions required={expect['requires_actions']} got={has_actions}")
    if expect.get("expected_action_type"):
        actions = response.get("actions") or []
        check(any(action.get("action_type") == expect["expected_action_type"] for action in actions), f"missing action_type {expect['expected_action_type']}")
    if expect.get("min_quality_score") is not None:
        quality = response.get("agent_quality") or {}
        check(float(quality.get("score") or 0) >= float(expect["min_quality_score"]), f"quality score below {expect['min_quality_score']}: {quality.get('score')}")
    if expect.get("max_quality_risks") is not None:
        quality = response.get("agent_quality") or {}
        risks = quality.get("risks") or []
        check(len(risks) <= int(expect["max_quality_risks"]), f"too many quality risks: {risks}")
    if expect.get("quality_must_pass"):
        quality = response.get("agent_quality") or {}
        check(bool(quality.get("passed")), f"quality did not pass: {quality}")

    score = passed / checks if checks else 1.0
    return {
        "id": case["id"],
        "title": case["title"],
        "ok": score >= 1.0,
        "score": score,
        "errors": errors,
        "last_answer": answer,
        "conversation_id": response.get("conversation_id"),
    }


if __name__ == "__main__":
    raise SystemExit(main())
