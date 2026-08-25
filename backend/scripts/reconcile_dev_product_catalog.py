"""Reconcile verified product facts and add a small historical-QA supplement.

This is intentionally a development-only maintenance script.  The values in
the correction ledger were compared with the primary product metadata workbook
at ``C:\\Users\\wnt\\Desktop\\产品数据和qa库\\产品库元数据.xlsx``.  The script does
not import the workbook wholesale: several workbook/QA-template cells are
conflicting or clearly copied from another product, so every write has an old
value assertion and is idempotent.

The QA supplement is made from natural questions observed in
``D:\\CaiYan\\aiCS``.  Answers contain only same-SKU facts or explicit usage
instructions; no promotional or inferred burden/safety claims are added.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import sys
from decimal import Decimal
from pathlib import Path
from typing import Any

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.config import database_name_from_url, settings
from app.core.database import SessionLocal, engine
from app.models.product import Product
from app.models.product_business import ProductBusiness
from app.models.product_qa import ProductQa
from app.models.product_specs import ProductSpecs
from app.models.user import User
from app.services import product_qa_integrity_service, product_service

# The dev env enables SQL echo for the running server.  Maintenance output is
# a fact/audit ledger, so keep SQL bind logs out of it (the engine remains the
# same dev-only engine).
engine.echo = False


SOURCE_METADATA = r"C:\Users\wnt\Desktop\产品数据和qa库\产品库元数据.xlsx"
SOURCE_HISTORY = r"D:\CaiYan\aiCS"


# These are exact old-value -> verified new-value replacements.  C76/C96-B/
# C97 deliberately use 0.8L: the primary capacity field says 0.8L, while an
# older QA template says 1.4L.  Capacity is the formal same-SKU field and wins
# over that copied selling-point text.
CAPACITY_CORRECTIONS: dict[str, tuple[tuple[str, str], ...]] = {
    "CW-K11-37": (("3L", "1.3L"),),
    "CW-C72": (("7L", "1.7L"),),
    "CW-C99B": (("7L", "1.7L"),),
    "CW-RT05": (("3L", "1.3L"),),
    "CW-C47-37": (
        ("2L", "2.2L"),
        ("4L", "1.4L"),
        ("8L", "0.8L"),
        ("5寸", "7.5寸"),
    ),
    "CW-K03": (("4L", "1.4L"),),
    "CW-C82": (("4L", "1.4L"),),
    "CW-C84": (("4L", "1.4L"),),
    "CW-C85-A": (("5L", "3.5L"),),
    "CW-K32": (("3L", "2.3L"),),
    "CW-C76": (("8L", "0.8L"),),
    "CW-C96-B": (("8L", "0.8L"),),
}


SELLING_POINT_CORRECTIONS: dict[str, tuple[str, str]] = {
    "CW-K03": ("4L 双人容量", "1.4L 双人容量"),
    "CW-K03-37": ("4L 双人容量", "1.4L 双人容量"),
    "CW-C84": ("4L 双人容量", "1.4L 双人容量"),
    "CW-C76": ("4L 双人容量", "0.8L 双人容量"),
    "CW-C96-B": ("4L 双人容量", "0.8L 双人容量"),
    "CW-C97": ("4L 双人容量", "0.8L 双人容量"),
    "CB253": ("4L 双人容量", "1.4L 双人容量"),
    "CW-C90": ("5 寸小巧尺寸", "7.5 寸小巧尺寸"),
    "CW-PF05": ("5 寸尺寸", "7.5 寸尺寸"),
}


WEIGHT_CORRECTIONS: dict[str, tuple[Decimal, Decimal]] = {
    # Excel stores this cell as the text "1.74kg" although the column is g.
    "AC-Z14": (Decimal("1.74"), Decimal("1740")),
}


# Existing customer-visible answers that would remain misleading after the
# field repair.  Each entry is guarded by its exact old answer so a manual
# edit made after this ledger was authored is never overwritten.
QA_ANSWER_CORRECTIONS: tuple[dict[str, str], ...] = (
    {
        "sku": "CW-K03",
        "question": "1.4L野营水壶（星空辉）有多重？",
        "old_answer": "1.4L野营水壶（星空辉）净重约318g，非常轻便，轻松放入背包。",
        "new_answer": "1.4L野营水壶（星空辉）净重约195g。",
    },
    {
        "sku": "CW-C76",
        "question": "享野水壶有什么核心卖点？",
        "old_answer": "享野水壶的核心卖点包括：高性价比、1.4L 双人容量、快速沸腾、硬质氧化工艺。",
        "new_answer": "享野水壶的核心卖点包括：高性价比、0.8L 容量、快速沸腾、硬质氧化工艺。",
    },
    {
        "sku": "CW-C96-B",
        "question": "京享水壶有什么核心卖点？",
        "old_answer": "京享水壶的核心卖点包括：高性价比、1.4L 双人容量、快速沸腾、硬质氧化工艺。",
        "new_answer": "京享水壶的核心卖点包括：高性价比、0.8L 容量、快速沸腾、硬质氧化工艺。",
    },
    {
        "sku": "CW-C97",
        "question": "京澜水壶（京东自营）有什么核心卖点？",
        "old_answer": "京澜水壶（京东自营）的核心卖点包括：京东自营、高性价比、1.4L 双人容量、快速沸腾。",
        "new_answer": "京澜水壶（京东自营）的核心卖点包括：京东自营、高性价比、0.8L 容量、快速沸腾。",
    },
    {
        "sku": "CW-C78",
        "question": "享野套锅有多重？",
        "old_answer": "享野套锅重量约1.32kg（含包装），户外携带无负担。",
        "new_answer": "享野套锅毛重约1320g（约1.32kg）。",
    },
    {
        "sku": "CW-K03-37",
        "question": "1.4升户外水壶第一次使用要注意什么？",
        "old_answer": "首次使用前用温水和软布冲洗即可（无需洗洁精）。烹饪前中小火预热2-3分钟，再倒油使用效果更佳。",
        "new_answer": "首次使用前用温水和软布冲洗即可（无需洗洁精）。烹饪前将水壶置于灶具上，用中小火预热2-3分钟。",
    },
    {
        "sku": "CW-K03-37",
        "question": "1.4升户外水壶兼容哪些炉具？",
        "old_answer": "1.4升户外水壶兼容酒精炉 燃气炉等多种热源，户外家用一锅搞定。",
        "new_answer": "适用明火直烧、卡式炉、分体炉和一体炉。",
    },
    {
        "sku": "CW-K03-37",
        "question": "1.4升户外水壶有哪些颜色？",
        "old_answer": "1.4升户外水壶颜色为氧化铝本色。",
        "new_answer": "1.4升户外水壶主色系为锖色。",
    },
    {
        "sku": "CW-RT05",
        "question": "有喜锅有多重？",
        "old_answer": "有喜锅重量约1.02kg（含包装），户外携带无负担。",
        "new_answer": "有喜锅毛重约1020g（约1.02kg）。",
    },
    {
        "sku": "CW-C47-37",
        "question": "荒野3-4人自驾套装有多重？",
        "old_answer": "荒野3-4人自驾套装重量约2.45kg（含包装），户外携带无负担。",
        "new_answer": "荒野3-4人自驾套装毛重约2450g（约2.45kg）。",
    },
    {
        "sku": "CW-C05-37",
        "question": "2-4人野餐锅10件套有多重？",
        "old_answer": "2-4人野餐锅10件套重量约1.03kg（含包装），户外携带无负担。",
        "new_answer": "2-4人野餐锅10件套毛重约1030g（约1.03kg）。",
    },
)


# Natural variants selected from the historical customer conversations.  They
# intentionally cover common field/usage questions without copying sales
# language from the chat records.
SUPPLEMENTAL_QA: tuple[dict[str, Any], ...] = (
    {"sku": "CW-K11-37", "question": "寻唐套装这个多少升？", "answer": "容量约1.3L。", "tags": ["历史自然问法", "容量"]},
    {"sku": "CW-C72", "question": "这个1.7L单锅实际容量多少？", "answer": "容量约1.7L。", "tags": ["历史自然问法", "容量"]},
    {"sku": "CW-C99B", "question": "小方锅是多少升的？", "answer": "容量约1.7L。", "tags": ["历史自然问法", "容量"]},
    {"sku": "CW-RT05", "question": "有喜锅大概几升？", "answer": "容量约1.3L。", "tags": ["历史自然问法", "容量"]},
    {"sku": "CW-C47-37", "question": "荒野3-4人自驾套装里面各锅容量多大？", "answer": "包含2.2L锅、1.4L锅、0.8L水壶，另有7.5英寸煎盘。", "tags": ["历史自然问法", "容量"]},
    {"sku": "CW-K03", "question": "星空辉这款水壶多少升？", "answer": "容量约1.4L。", "tags": ["历史自然问法", "容量"]},
    {"sku": "CW-C82", "question": "时谷水壶容量多少？", "answer": "容量约1.4L。", "tags": ["历史自然问法", "容量"]},
    {"sku": "CW-C84", "question": "鸣泉水壶多少升？", "answer": "容量约1.4L。", "tags": ["历史自然问法", "容量"]},
    {"sku": "CW-K32", "question": "享膳Plus水壶容量多大？", "answer": "容量约2.3L。", "tags": ["历史自然问法", "容量"]},
    {"sku": "CW-C76", "question": "享野水壶多少升？", "answer": "容量约0.8L。", "tags": ["历史自然问法", "容量"]},
    {"sku": "CW-C96-B", "question": "京享水壶多少升？", "answer": "容量约0.8L。", "tags": ["历史自然问法", "容量"]},
    {"sku": "CB253", "question": "聚能环水壶容量多大？", "answer": "容量约1.4L。", "tags": ["历史自然问法", "容量"]},
    {"sku": "CW-C90", "question": "这个煎盘是几寸的？", "answer": "尺寸为7.5英寸。", "tags": ["历史自然问法", "尺寸"]},
    {"sku": "CW-PF05", "question": "陶瓷不沾煎盘多大？", "answer": "尺寸为7.5英寸。", "tags": ["历史自然问法", "尺寸"]},
    {"sku": "AC-Z14", "question": "灵巧包能装多少东西？", "answer": "容量约30L。", "tags": ["历史自然问法", "容量"]},
    {"sku": "AC-Z14", "question": "灵巧包能不能展开当小桌？", "answer": "可以。内部钢丝框架展开后撑开包身，盖上单元板即可当小桌使用。", "tags": ["历史自然问法", "使用"]},
    {"sku": "CW-C01-37", "question": "CW-C01-37适用什么炉具？", "answer": "适用明火直烧、卡式炉、分体炉和一体炉。", "tags": ["历史自然问法", "热源"]},
    {"sku": "CS-B14", "question": "旋焰酒精炉用什么燃料？", "answer": "适用95%液体工业酒精。", "tags": ["历史自然问法", "燃料"]},
    {"sku": "CS-B14", "question": "酒精炉燃烧的时候能加酒精吗？", "answer": "不能。必须先灭火，再添加燃料。", "tags": ["历史自然问法", "安全使用"]},
    {"sku": "CW-C83", "question": "炊墨套锅的锅和煎盘容量分别是多少？", "answer": "锅约3700ML，煎盘约2300ML。", "tags": ["历史自然问法", "容量"]},
    {"sku": "CW-C83", "question": "炊墨套锅能用电磁炉吗？", "answer": "可以。适用热源资料包含明火直烧、燃气炉、卡式炉、电磁炉、燃气灶和电陶炉。", "tags": ["历史自然问法", "热源"]},
    {"sku": "CW-C83", "question": "炊墨套锅有不粘涂层吗？", "answer": "有。表面处理资料标注了硬质氧化和水性不沾。", "tags": ["历史自然问法", "表面处理"]},
    {"sku": "CW-C83", "question": "炊墨套锅收纳后多大？", "answer": "收纳带手柄尺寸约52*28.6*14.5cm。", "tags": ["历史自然问法", "尺寸"]},
    {"sku": "CW-C93", "question": "行山单锅容量多少？", "answer": "锅容量约1000ML（1L）。", "tags": ["历史自然问法", "容量"]},
    {"sku": "CW-C93", "question": "行山单锅有多重？", "answer": "重量约220g。", "tags": ["历史自然问法", "重量"]},
    {"sku": "CW-C93", "question": "行山单锅可以用哪些炉具？", "answer": "适用明火直烧、卡式炉、分体炉和一体炉。", "tags": ["历史自然问法", "热源"]},
    {"sku": "CW-C93", "question": "行山单锅有没有不粘涂层？", "answer": "有。表面处理资料标注为硬质氧化和陶瓷不沾。", "tags": ["历史自然问法", "表面处理"]},
    {"sku": "CW-C93", "question": "行山单锅展开尺寸是多少？", "answer": "展开尺寸约12.5*12.5*12.9cm。", "tags": ["历史自然问法", "尺寸"]},
    {"sku": "CS-G25", "question": "小青炉最大功率和重量是多少？", "answer": "最大功率3200W，重量约550g。", "tags": ["历史自然问法", "功率", "重量"]},
    {"sku": "CS-G25", "question": "小青炉怎么点火？", "answer": "连接燃气罐后，打开火力调节阀逆时针旋转1-2圈，再按击点火装置；点燃后调节火力。", "tags": ["历史自然问法", "使用"]},
    {"sku": "CS-G25", "question": "小青炉有防风设计吗？", "answer": "有。技术优势资料标注了猛火大功率4级防风。", "tags": ["历史自然问法", "防风"]},
    {"sku": "CS-B14", "question": "旋焰酒精炉的炉体容量是多少？", "answer": "炉体容量约200ML。", "tags": ["历史自然问法", "容量"]},
)


def ensure_development_target() -> None:
    if str(settings.APP_ENV or "").lower() != "dev":
        raise RuntimeError("Product catalog reconciliation requires APP_ENV=dev.")
    if database_name_from_url(str(settings.DATABASE_URL or "")) != "product_knowledge_dev":
        raise RuntimeError("Product catalog reconciliation requires product_knowledge_dev.")


def _normalize_question(value: Any) -> str:
    return re.sub(r"\s+", "", str(value or "")).casefold()


def _json_value(value: Any, *, field: str, sku: str) -> Any:
    if isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError as exc:
            raise ValueError(f"{sku} {field} is not valid JSON: {exc}") from exc
    return value


def _json_string(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False)


def _product_and(model, db, sku: str):
    product = db.query(Product).filter(Product.sku == sku).first()
    if product is None:
        raise ValueError(f"Product not found in development database: {sku}")
    row = db.query(model).filter(model.product_id == product.id).first()
    if row is None:
        raise ValueError(f"{model.__tablename__} row not found for {sku}")
    return product, row


def _replace_once_or_confirmed_new(values: list[str], old: str, new: str, *, sku: str, field: str) -> bool:
    old_count = sum(value == old for value in values)
    new_count = sum(value == new for value in values)
    if old_count == 0:
        if new_count == 1:
            return False
        raise ValueError(f"{sku} {field} expected exactly one {old!r} or {new!r}; got {values!r}")
    if old_count != 1 or new_count:
        raise ValueError(f"{sku} {field} old/new value assertion failed: {values!r}")
    index = values.index(old)
    values[index] = new
    return True


def apply_product_field_corrections(db) -> set[str]:
    changed_skus: set[str] = set()
    for sku, replacements in CAPACITY_CORRECTIONS.items():
        _, specs = _product_and(ProductSpecs, db, sku)
        raw = _json_value(specs.capacity, field="capacity", sku=sku)
        if not isinstance(raw, list) or not all(isinstance(item, dict) for item in raw):
            raise ValueError(f"{sku} capacity must be a JSON list of objects: {raw!r}")
        values = [str(item.get("value") or "").strip() for item in raw]
        sku_changed = False
        for old, new in replacements:
            # Replace inside a labelled value such as "2L锅" while still
            # requiring exactly one matching value in the same SKU.
            # Check the new value first: `3L` is a substring of `1.3L`, and
            # `4L` is a substring of `1.4L`; treating those as old values on a
            # second run would break the promised idempotence.
            matching = [index for index, value in enumerate(values) if old in value]
            confirmed_new = [index for index, value in enumerate(values) if new in value]
            if confirmed_new:
                if len(confirmed_new) == 1 and all(index == confirmed_new[0] for index in matching):
                    continue
                raise ValueError(f"{sku} capacity value assertion failed for {old!r}: {values!r}")
            if len(matching) != 1:
                raise ValueError(f"{sku} capacity value assertion failed for {old!r}: {values!r}")
            index = matching[0]
            values[index] = values[index].replace(old, new, 1)
            raw[index]["value"] = values[index]
            sku_changed = True
        if sku_changed:
            specs.capacity = _json_string(raw)
            changed_skus.add(sku)

    for sku, (old, new) in SELLING_POINT_CORRECTIONS.items():
        _, business = _product_and(ProductBusiness, db, sku)
        raw = _json_value(business.top_selling_points, field="top_selling_points", sku=sku)
        if not isinstance(raw, list) or not all(isinstance(item, str) for item in raw):
            raise ValueError(f"{sku} top_selling_points must be a JSON list of strings: {raw!r}")
        if _replace_once_or_confirmed_new(raw, old, new, sku=sku, field="top_selling_points"):
            business.top_selling_points = _json_string(raw)
            changed_skus.add(sku)

    for sku, (old, new) in WEIGHT_CORRECTIONS.items():
        _, specs = _product_and(ProductSpecs, db, sku)
        current = Decimal(str(specs.gross_weight_g))
        if current == old:
            specs.gross_weight_g = new
            changed_skus.add(sku)
        elif current != new:
            raise ValueError(f"{sku} gross_weight_g expected {old} or {new}, got {current}")

    return changed_skus


def _find_qa(db, sku: str, question: str) -> ProductQa:
    product = db.query(Product).filter(Product.sku == sku).first()
    if product is None:
        raise ValueError(f"Product not found for QA correction: {sku}")
    matches = [
        qa
        for qa in db.query(ProductQa).filter(ProductQa.product_id == product.id).all()
        if _normalize_question(qa.question) == _normalize_question(question)
    ]
    if len(matches) != 1:
        raise ValueError(f"Expected one QA for {sku}/{question!r}, found {len(matches)}")
    return matches[0]


def apply_existing_qa_corrections(db) -> set[str]:
    changed_skus: set[str] = set()
    for item in QA_ANSWER_CORRECTIONS:
        qa = _find_qa(db, item["sku"], item["question"])
        if qa.answer == item["old_answer"]:
            qa.answer = item["new_answer"]
            qa.integrity_status = "review"
            qa.integrity_reason = None
            qa.integrity_model = None
            qa.integrity_audited_at = None
            changed_skus.add(item["sku"])
        elif qa.answer != item["new_answer"]:
            raise ValueError(
                f"QA answer assertion failed for {item['sku']}/{item['question']!r}; "
                f"current answer is not the expected old or new value."
            )
    return changed_skus


def add_supplemental_qa(db) -> tuple[set[str], int, int]:
    changed_skus: set[str] = set()
    created = 0
    skipped = 0
    for item in SUPPLEMENTAL_QA:
        product = db.query(Product).filter(Product.sku == item["sku"]).first()
        if product is None:
            raise ValueError(f"Product not found for supplemental QA: {item['sku']}")
        normalized = _normalize_question(item["question"])
        existing = [
            qa
            for qa in db.query(ProductQa).filter(ProductQa.product_id == product.id).all()
            if _normalize_question(qa.question) == normalized
        ]
        if existing:
            if len(existing) != 1 or str(existing[0].answer or "").strip() != item["answer"]:
                raise ValueError(f"Supplemental QA conflicts with existing question: {item['sku']}/{item['question']}")
            skipped += 1
            continue
        db.add(ProductQa(
            product_id=product.id,
            question=item["question"],
            answer=item["answer"],
            tags=_json_string(item["tags"]),
            priority=2,
            integrity_status="review",
        ))
        changed_skus.add(item["sku"])
        created += 1
    db.flush()
    return changed_skus, created, skipped


async def audit_affected_qas(db, skus: set[str], audit_user: User) -> dict[str, Any]:
    counts = {"approved": 0, "rejected": 0, "review": 0}
    rows = 0
    for sku in sorted(skus):
        product = db.query(Product).filter(Product.sku == sku).first()
        if product is None:
            raise ValueError(f"Product disappeared before QA audit: {sku}")
        qas = db.query(ProductQa).filter(ProductQa.product_id == product.id).order_by(ProductQa.created_at.asc()).all()
        for qa in qas:
            verdict = await product_qa_integrity_service.audit_product_qa_item(
                db,
                product,
                qa,
                user=audit_user,
            )
            status = str(verdict.get("status") or "review")
            counts[status] = counts.get(status, 0) + 1
            rows += 1
            print(json.dumps({"event": "qa_audit", "sku": sku, "qa_id": str(qa.id), "status": status, "reason": verdict.get("reason", "")}, ensure_ascii=False), flush=True)
    db.commit()
    return {"rows": rows, "counts": counts}


def sync_affected_products(db, skus: set[str]) -> dict[str, Any]:
    results: list[dict[str, Any]] = []
    for sku in sorted(skus):
        result = product_service.sync_product_to_vector_db(db, sku)
        results.append(result)
        print(json.dumps({"event": "vector_sync", **result}, ensure_ascii=False), flush=True)
    return {
        "products": len(results),
        "ready": sum(1 for item in results if item.get("ready_for_rag")),
        "failed": sum(1 for item in results if item.get("error") or not item.get("ready_for_rag")),
        "results": results,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="Persist corrections and supplemental QA.")
    parser.add_argument("--no-audit", action="store_true", help="Do not run the semantic QA audit after applying.")
    parser.add_argument("--no-sync", action="store_true", help="Do not reindex/embed affected SKUs after auditing.")
    args = parser.parse_args()
    ensure_development_target()

    db = SessionLocal()
    try:
        changed_skus = apply_product_field_corrections(db)
        changed_skus.update(apply_existing_qa_corrections(db))
        qa_skus, created, skipped = add_supplemental_qa(db)
        changed_skus.update(qa_skus)
        plan = {
            "source_metadata": SOURCE_METADATA,
            "source_history": SOURCE_HISTORY,
            "apply": args.apply,
            "affected_skus": sorted(changed_skus),
            "supplemental_qa_created": created,
            "supplemental_qa_skipped_existing": skipped,
        }
        if not args.apply:
            db.rollback()
            print(json.dumps({**plan, "message": "dry-run: no database changes persisted"}, ensure_ascii=False, indent=2))
            return 0

        db.commit()
        audit_result: dict[str, Any] | None = None
        sync_result: dict[str, Any] | None = None
        if not args.no_audit:
            audit_user = db.query(User).filter(User.username == "admin", User.is_active.is_(True)).first()
            if audit_user is None:
                raise RuntimeError("An active development admin user is required for semantic QA audit.")
            audit_result = asyncio.run(audit_affected_qas(db, changed_skus, audit_user))
        if not args.no_sync:
            sync_result = sync_affected_products(db, changed_skus)
        print(json.dumps({**plan, "audit": audit_result, "vector_sync": sync_result}, ensure_ascii=False, indent=2))
        return 0
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
