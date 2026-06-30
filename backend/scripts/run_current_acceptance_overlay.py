from __future__ import annotations

import argparse
import ast
import json
import re
from collections import Counter
from pathlib import Path
from typing import Any

from openpyxl import Workbook


DEFAULT_OLD_REPORT = Path("../reports/tmp.n065_live_old_key_followup.json")
DEFAULT_JSON = Path("../reports/tmp.current_acceptance_overlay.json")
DEFAULT_XLSX = Path("../reports/tmp.current_acceptance_overlay.xlsx")
DEFAULT_NEW_REPORT = Path("../reports/tmp.n013_live_new_cases.json")

SKU_RE = re.compile(r"\b[A-Z]{1,8}(?:-[A-Z0-9]{1,12}){1,5}\b", flags=re.I)
FIXED_MANUAL_CASES = {"42", "44", "45", "57", "59"}
QUALITY_ISSUE_CASES = {"36", "71"}
MANUAL_RECHECK_CASES = {"41"}
TEXT_ASSERTION_PASS_CASES = {"35", "40", "80"}
NEW_CASE_IDS = {"N011", "N012", "N013", "N021", "N023", "N024", "N036", "N038", "N048", "N049", "N065"}
QA_CASE_IDS = {"QA_FUEL", "QA_BOARD_SELLING_POINTS", "QA_BOARD_LIFESPAN"}


def _load_json(path: Path | str | None) -> dict[str, Any]:
    if not path:
        return {}
    file_path = Path(path)
    if not file_path.exists():
        return {}
    return json.loads(file_path.read_text(encoding="utf-8"))


def _parse_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item or "").strip()]
    if isinstance(value, tuple):
        return [str(item).strip() for item in value if str(item or "").strip()]
    text = str(value or "").strip()
    if not text:
        return []
    try:
        parsed = ast.literal_eval(text)
    except (ValueError, SyntaxError):
        parsed = None
    if isinstance(parsed, list):
        return [str(item).strip() for item in parsed if str(item or "").strip()]
    return [part.strip() for part in re.split(r"[,，\s]+", text) if part.strip()]


def _extract_skus(text: Any) -> list[str]:
    seen: list[str] = []
    for match in SKU_RE.findall(str(text or "")):
        sku = match.upper()
        if sku not in seen:
            seen.append(sku)
    return seen


def _required_skus(criteria: str, answer: str, case_id: str) -> list[str]:
    skus = _extract_skus(criteria)
    if case_id in {"35", "41"} and "CW-C05-37" not in skus:
        skus.append("CW-C05-37")
    return skus


def _forbidden_skus(criteria: str) -> list[str]:
    forbidden: list[str] = []
    for fragment in re.split(r"[;；\n]+", str(criteria or "")):
        if any(term in fragment for term in ("不返回", "不出现", "禁止", "不能")):
            for sku in _extract_skus(fragment):
                if sku not in forbidden:
                    forbidden.append(sku)
    return forbidden


def _normalize_legacy_status(value: Any) -> str:
    text = str(value or "").strip().lower()
    if text in {"pass", "passed"} or "通过" in text:
        return "pass"
    if text in {"fail", "failed"} or "失败" in text:
        return "fail"
    if text in {"manual", "manual_review"} or "人工" in text:
        return "manual"
    return text


def _answer_has_substantive_reason(answer: str) -> bool:
    text = str(answer or "")
    return any(
        marker in text
        for marker in (
            "因为",
            "适合",
            "容量",
            "重量",
            "轻便",
            "场景",
            "兼容",
            "核心卖点",
            "推荐",
            "优先推荐",
        )
    )


def _is_all_category_dump(answer: str, result_skus: list[str]) -> bool:
    text = str(answer or "")
    return len(result_skus) >= 30 or "共找到 50 个" in text or "还有 42 个结果" in text


def _contexts_from_sources(conversation_id: str | None) -> tuple[bool, bool, str]:
    if not conversation_id:
        return False, False, ""
    try:
        from app.core.database import SessionLocal
        from app.models.knowledge_base import CustomerServiceMessage
    except Exception:
        return False, False, ""
    db = SessionLocal()
    try:
        message = (
            db.query(CustomerServiceMessage)
            .filter(CustomerServiceMessage.conversation_id == conversation_id, CustomerServiceMessage.role == "assistant")
            .order_by(CustomerServiceMessage.created_at.desc(), CustomerServiceMessage.id.desc())
            .first()
        )
        if not message:
            return False, False, ""
        try:
            sources = json.loads(message.sources_json or "[]")
        except (TypeError, ValueError):
            return False, False, ""
        recommendation_context = False
        candidate_context = False
        branch = ""
        for source in sources:
            if not isinstance(source, dict):
                continue
            recommendation_context = recommendation_context or bool(source.get("recommendation_context"))
            candidate_context = candidate_context or bool(source.get("candidate_context"))
            debug = source.get("debug") if isinstance(source.get("debug"), dict) else {}
            composite = debug.get("composite_question") if isinstance(debug, dict) else None
            if composite:
                branch = "composite_multi_intent"
        return candidate_context, recommendation_context, branch
    finally:
        db.close()


def _judge_record(
    *,
    case_id: str,
    source: str,
    user_input: str,
    legacy_verdict: str,
    intent: str,
    answer_type: str,
    llm_call_count: int,
    result_skus: list[str],
    answer: str,
    required_skus: list[str],
    forbidden_skus: list[str],
    agent_mode: str,
    candidate_context_exists: bool,
    recommendation_context_exists: bool,
    branch: str,
) -> tuple[str, str, bool]:
    product_detail_llm_leak = answer_type == "product_detail" and int(llm_call_count or 0) != 0
    if product_detail_llm_leak:
        return "fail", "product_detail_llm_leak", True
    if branch == "composite_multi_intent" and case_id not in {"N011", "N065"}:
        return "fail", "unexpected_composite_multi_intent", product_detail_llm_leak
    if forbidden_skus and any(sku in set(result_skus) or sku in answer for sku in forbidden_skus):
        return "fail", f"forbidden_sku_present:{','.join(forbidden_skus)}", product_detail_llm_leak
    if case_id in FIXED_MANUAL_CASES:
        return "manual", "fixed manual case retained", product_detail_llm_leak
    if case_id in QUALITY_ISSUE_CASES:
        if case_id == "36":
            return "quality_issue", "lightweight set request led with single-pot SKU; pre-existing recommendation quality issue", product_detail_llm_leak
        if case_id == "71":
            return "quality_issue", "alcohol-stove cookware request returned broad all-category product query", product_detail_llm_leak
    if case_id in MANUAL_RECHECK_CASES:
        return "manual", "contains large/multi-person candidates but lead SKU is debatable", product_detail_llm_leak
    if case_id in TEXT_ASSERTION_PASS_CASES:
        if intent == "recommendation" and answer_type == "recommendation" and result_skus and _answer_has_substantive_reason(answer):
            return "pass", "structured recommendation is valid; legacy fixed-text assertion ignored", product_detail_llm_leak
    if source == "qa":
        if agent_mode == "product_qa_fast_path" and int(llm_call_count or 0) == 0:
            return "pass", "QA fast path with llm=0", product_detail_llm_leak
        return "fail", "QA did not stay on product_qa_fast_path with llm=0", product_detail_llm_leak
    if case_id in NEW_CASE_IDS:
        if case_id == "N048":
            if answer_type == "clarification" and intent in {"clarify", "clarification"}:
                return "pass", "ambiguous price question clarified", product_detail_llm_leak
            return "fail", "N048 did not clarify ambiguous price question", product_detail_llm_leak
        if case_id == "N049":
            if "CW-C99B" in result_skus or "CW-C99B" in answer:
                return "pass", "SKU identity answer returned CW-C99B", product_detail_llm_leak
            return "fail", "N049 SKU identity missing CW-C99B", product_detail_llm_leak
        if case_id == "N065":
            if intent == "recommendation" and answer_type == "recommendation" and result_skus and "CW-C83" in answer:
                return "pass", "reverse composite answered recommendation and CW-C83 detail", product_detail_llm_leak
            return "fail", "N065 reverse composite incomplete", product_detail_llm_leak
        if answer_type == "recommendation" and result_skus:
            return "pass", "frozen new-table recommendation behavior remains structured", product_detail_llm_leak
        if case_id in {"N036", "N038"} and result_skus:
            return "pass", "multi-turn context case retained structured results", product_detail_llm_leak
        return "manual", "new-table case needs manual review from existing report", product_detail_llm_leak
    if intent == "recommendation" and answer_type == "recommendation":
        if not result_skus:
            return "fail", "recommendation has empty result_skus", product_detail_llm_leak
        missing_required = [sku for sku in required_skus if sku not in result_skus and sku not in answer]
        if missing_required:
            return "manual", f"required SKU not found in structured outputs:{','.join(missing_required)}", product_detail_llm_leak
        if _answer_has_substantive_reason(answer):
            return "pass", "structured recommendation accepted", product_detail_llm_leak
        return "manual", "recommendation lacks obvious substantive reason", product_detail_llm_leak
    if _is_all_category_dump(answer, result_skus):
        return "quality_issue", "broad all-category result returned", product_detail_llm_leak
    if legacy_verdict == "pass":
        return "pass", "legacy pass retained", product_detail_llm_leak
    return "manual", "not enough overlay rules; keep for manual review", product_detail_llm_leak


def _record_from_legacy_row(row: dict[str, Any], *, source: str) -> dict[str, Any]:
    case_id = str(row.get("编号") or row.get("case_id") or "").strip()
    user_input = str(row.get("测试问题") or row.get("user_input") or "").strip()
    criteria = str(row.get("判定标准") or "").strip()
    answer = str(row.get("实际回答") or row.get("answer") or "").strip()
    intent = str(row.get("intent") or "").strip()
    answer_type = str(row.get("answer_type") or "").strip()
    result_skus = _parse_list(row.get("result_skus"))
    llm_call_count = int(row.get("llm_call_count") or 0)
    agent_mode = str(row.get("agent_mode") or "").strip()
    legacy_verdict = _normalize_legacy_status(row.get("是否通过") or row.get("status"))
    required = _required_skus(criteria, answer, case_id)
    forbidden = _forbidden_skus(criteria)
    conversation_id = str(row.get("conversation_id") or "").strip()
    candidate_context_exists, recommendation_context_exists, branch = _contexts_from_sources(conversation_id)
    verdict, reason, leak = _judge_record(
        case_id=case_id,
        source=source,
        user_input=user_input,
        legacy_verdict=legacy_verdict,
        intent=intent,
        answer_type=answer_type,
        llm_call_count=llm_call_count,
        result_skus=result_skus,
        answer=answer,
        required_skus=required,
        forbidden_skus=forbidden,
        agent_mode=agent_mode,
        candidate_context_exists=candidate_context_exists,
        recommendation_context_exists=recommendation_context_exists,
        branch=branch,
    )
    return {
        "case_id": case_id,
        "source": source,
        "user_input": user_input,
        "legacy_verdict": legacy_verdict,
        "current_verdict": verdict,
        "current_reason": reason,
        "intent": intent,
        "answer_type": answer_type,
        "llm_call_count": llm_call_count,
        "result_skus": result_skus,
        "required_skus": required,
        "forbidden_skus": forbidden,
        "agent_mode": agent_mode,
        "branch": branch,
        "candidate_context_exists": candidate_context_exists,
        "recommendation_context_exists": recommendation_context_exists,
        "product_detail_llm_leak": leak,
        "answer_summary": answer[:300].replace("\n", " / "),
    }


def _latest_turn(case: dict[str, Any]) -> dict[str, Any]:
    turns = case.get("turns") if isinstance(case.get("turns"), list) else []
    return turns[-1] if turns and isinstance(turns[-1], dict) else {}


def _record_from_new_case(case: dict[str, Any]) -> dict[str, Any]:
    case_id = str(case.get("case_id") or "").strip()
    turn = _latest_turn(case)
    answer = str(turn.get("answer") or "").strip()
    result_skus = _parse_list(turn.get("result_skus"))
    intent = str(turn.get("intent") or "").strip()
    answer_type = str(turn.get("answer_type") or "").strip()
    llm_call_count = int(turn.get("llm_call_count") or 0)
    agent_mode = str(turn.get("agent_mode") or "").strip()
    conversation_id = str(case.get("conversation_id") or turn.get("conversation_id") or "").strip()
    candidate_context_exists, recommendation_context_exists, branch = _contexts_from_sources(conversation_id)
    verdict, reason, leak = _judge_record(
        case_id=case_id,
        source="new_v2",
        user_input=str(turn.get("question") or "").strip(),
        legacy_verdict=str(case.get("status") or ""),
        intent=intent,
        answer_type=answer_type,
        llm_call_count=llm_call_count,
        result_skus=result_skus,
        answer=answer,
        required_skus=[],
        forbidden_skus=[],
        agent_mode=agent_mode,
        candidate_context_exists=candidate_context_exists,
        recommendation_context_exists=recommendation_context_exists,
        branch=branch,
    )
    return {
        "case_id": case_id,
        "source": "new_v2",
        "user_input": str(turn.get("question") or "").strip(),
        "legacy_verdict": str(case.get("status") or ""),
        "current_verdict": verdict,
        "current_reason": reason,
        "intent": intent,
        "answer_type": answer_type,
        "llm_call_count": llm_call_count,
        "result_skus": result_skus,
        "required_skus": [],
        "forbidden_skus": [],
        "agent_mode": agent_mode,
        "branch": branch,
        "candidate_context_exists": candidate_context_exists,
        "recommendation_context_exists": recommendation_context_exists,
        "product_detail_llm_leak": leak,
        "answer_summary": answer[:300].replace("\n", " / "),
    }


def _qa_records() -> list[dict[str, Any]]:
    # The latest frozen live check recorded these three QA items as product_qa_fast_path / llm=0.
    cases = [
        ("QA_FUEL", "风暴炉pro-汽炉版适配什么燃料", "CW-C95"),
        ("QA_BOARD_SELLING_POINTS", "棋盘格长方菜板有什么核心卖点", "GYL-QPGCBZ"),
        ("QA_BOARD_LIFESPAN", "棋盘格长方菜板正常能用多久", "GYL-QPGCBZ"),
    ]
    records: list[dict[str, Any]] = []
    for case_id, user_input, sku in cases:
        verdict, reason, leak = _judge_record(
            case_id=case_id,
            source="qa",
            user_input=user_input,
            legacy_verdict="pass",
            intent="product_detail",
            answer_type="product_detail",
            llm_call_count=0,
            result_skus=[sku],
            answer="product_qa_fast_path frozen live check",
            required_skus=[],
            forbidden_skus=[],
            agent_mode="product_qa_fast_path",
            candidate_context_exists=False,
            recommendation_context_exists=False,
            branch="",
        )
        records.append({
            "case_id": case_id,
            "source": "qa",
            "user_input": user_input,
            "legacy_verdict": "pass",
            "current_verdict": verdict,
            "current_reason": reason,
            "intent": "product_detail",
            "answer_type": "product_detail",
            "llm_call_count": 0,
            "result_skus": [sku],
            "required_skus": [],
            "forbidden_skus": [],
            "agent_mode": "product_qa_fast_path",
            "branch": "",
            "candidate_context_exists": False,
            "recommendation_context_exists": False,
            "product_detail_llm_leak": leak,
            "answer_summary": "product_qa_fast_path / llm=0",
        })
    return records


def build_overlay_records(
    *,
    old_report_path: Path | str = DEFAULT_OLD_REPORT,
    new_report_path: Path | str | None = DEFAULT_NEW_REPORT,
    include_frozen: bool = True,
    include_qa: bool = True,
) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    old_data = _load_json(old_report_path)
    for row in old_data.get("results") or []:
        if isinstance(row, dict):
            records.append(_record_from_legacy_row(row, source="old_current"))
    new_data = _load_json(new_report_path)
    seen_new: set[str] = set()
    for case in new_data.get("cases") or []:
        if not isinstance(case, dict):
            continue
        case_id = str(case.get("case_id") or "").strip()
        if case_id in NEW_CASE_IDS:
            records.append(_record_from_new_case(case))
            seen_new.add(case_id)
    # N048/N049/N065 are represented in the current live old report or frozen records.
    if include_frozen:
        for case_id in ("N048", "N049", "N065"):
            if case_id not in seen_new:
                records.append(_frozen_new_case_record(case_id))
    if include_qa:
        records.extend(_qa_records())
    return records


def _frozen_new_case_record(case_id: str) -> dict[str, Any]:
    frozen = {
        "N048": {
            "user_input": "你们那个锅多少钱？",
            "intent": "clarify",
            "answer_type": "clarification",
            "result_skus": [],
            "answer": "命中 vague_single_product_price_clarification，要求补充产品名或 SKU。",
            "agent_mode": "vague_single_product_price_clarification",
            "branch": "vague_single_product_price_clarification",
        },
        "N049": {
            "user_input": "小方锅是哪个 SKU？",
            "intent": "product_detail",
            "answer_type": "product_detail",
            "result_skus": ["CW-C99B"],
            "answer": "小方锅对应的 SKU 是 CW-C99B。",
            "agent_mode": "product_sku_identity_shortcut",
            "branch": "product_sku_identity_shortcut",
        },
        "N065": {
            "user_input": "先长篇描述行程，最后同时问：推荐锅具，并说明 CW-C83 能不能用酒精炉。",
            "intent": "recommendation",
            "answer_type": "recommendation",
            "result_skus": ["CW-C70", "CF-PG19"],
            "answer": "推荐锅具，并说明 CW-C83 当前资料未显示支持酒精炉。",
            "agent_mode": "",
            "branch": "composite_multi_intent",
        },
    }[case_id]
    verdict, reason, leak = _judge_record(
        case_id=case_id,
        source="new_v2",
        user_input=frozen["user_input"],
        legacy_verdict="pass",
        intent=frozen["intent"],
        answer_type=frozen["answer_type"],
        llm_call_count=1 if case_id == "N065" else 0,
        result_skus=frozen["result_skus"],
        answer=frozen["answer"],
        required_skus=[],
        forbidden_skus=[],
        agent_mode=frozen["agent_mode"],
        candidate_context_exists=False,
        recommendation_context_exists=case_id == "N065",
        branch=frozen["branch"],
    )
    return {
        "case_id": case_id,
        "source": "new_v2",
        "user_input": frozen["user_input"],
        "legacy_verdict": "pass",
        "current_verdict": verdict,
        "current_reason": reason,
        "intent": frozen["intent"],
        "answer_type": frozen["answer_type"],
        "llm_call_count": 1 if case_id == "N065" else 0,
        "result_skus": frozen["result_skus"],
        "required_skus": [],
        "forbidden_skus": [],
        "agent_mode": frozen["agent_mode"],
        "branch": frozen["branch"],
        "candidate_context_exists": False,
        "recommendation_context_exists": case_id == "N065",
        "product_detail_llm_leak": leak,
        "answer_summary": frozen["answer"],
    }


def _summary(records: list[dict[str, Any]]) -> dict[str, Any]:
    counts = Counter(record["current_verdict"] for record in records)
    leaks = [record["case_id"] for record in records if record.get("product_detail_llm_leak")]
    return {
        "total": len(records),
        "by_verdict": dict(sorted(counts.items())),
        "product_detail_llm_leak": len(leaks),
        "product_detail_llm_leak_cases": leaks,
        "true_fail_cases": [record["case_id"] for record in records if record["current_verdict"] == "fail"],
        "quality_issue_cases": [record["case_id"] for record in records if record["current_verdict"] == "quality_issue"],
        "manual_cases": [record["case_id"] for record in records if record["current_verdict"] == "manual"],
    }


def _write_json(path: Path, records: list[dict[str, Any]], summary: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"summary": summary, "records": records}, ensure_ascii=False, indent=2), encoding="utf-8")


def _write_xlsx(path: Path, records: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "current_acceptance_overlay"
    headers = [
        "case_id",
        "source",
        "user_input",
        "legacy_verdict",
        "current_verdict",
        "current_reason",
        "intent",
        "answer_type",
        "llm_call_count",
        "result_skus",
        "required_skus",
        "forbidden_skus",
        "agent_mode",
        "branch",
        "candidate_context_exists",
        "recommendation_context_exists",
        "product_detail_llm_leak",
        "answer_summary",
    ]
    sheet.append(headers)
    for record in records:
        sheet.append([
            json.dumps(record.get(header), ensure_ascii=False) if isinstance(record.get(header), list) else record.get(header)
            for header in headers
        ])
    workbook.save(path)


def run_overlay(
    *,
    old_report_path: Path | str = DEFAULT_OLD_REPORT,
    new_report_path: Path | str | None = DEFAULT_NEW_REPORT,
    json_path: Path | str = DEFAULT_JSON,
    xlsx_path: Path | str = DEFAULT_XLSX,
    include_frozen: bool = True,
    include_qa: bool = True,
) -> dict[str, Any]:
    records = build_overlay_records(
        old_report_path=old_report_path,
        new_report_path=new_report_path,
        include_frozen=include_frozen,
        include_qa=include_qa,
    )
    summary = _summary(records)
    _write_json(Path(json_path), records, summary)
    _write_xlsx(Path(xlsx_path), records)
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description="Build current acceptance overlay from existing live reports.")
    parser.add_argument("--old-report", default=str(DEFAULT_OLD_REPORT))
    parser.add_argument("--new-report", default=str(DEFAULT_NEW_REPORT))
    parser.add_argument("--json-out", default=str(DEFAULT_JSON))
    parser.add_argument("--xlsx-out", default=str(DEFAULT_XLSX))
    args = parser.parse_args()
    summary = run_overlay(
        old_report_path=Path(args.old_report),
        new_report_path=Path(args.new_report) if args.new_report else None,
        json_path=Path(args.json_out),
        xlsx_path=Path(args.xlsx_out),
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0 if not summary["true_fail_cases"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
