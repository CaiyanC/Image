"""Add a small, manually reviewed solid-alcohol QA alias batch to dev.

The source questions came from the 2026-09-01—11 customer-service export.
Answers are written from the current same-SKU product fields, not copied from
historical agent wording.  This is intentionally a dev-only, idempotent batch.
"""

from __future__ import annotations

import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.config import database_name_from_url, settings
from app.core.database import SessionLocal, engine
from app.models.product import Product
from app.models.product_qa import ProductQa
from app.services import product_service


SOURCE_ROOT = r"D:\CaiYan\aiCS\jilu\9月1日-11日"


QA_ITEMS: tuple[dict[str, Any], ...] = (
    {
        "sku": "CS-B02-37",
        "question": "能放酒精块吗？",
        "answer": "可以。当前资料明确液体和固体酒精均可使用；推荐使用95%浓度的液体工业酒精，燃烧效率更高。",
        "tags": ["真实问法别名", "固体酒精", "燃料"],
        "source_rows": "京东自营.xlsx:27、51、65、123",
        "evidence_fields": "product_specs.heat_source,product_specs.usage_instruction",
    },
    {
        "sku": "CS-B02-37",
        "question": "液体？有固体的炉子吗？",
        "answer": "有。当前资料明确液体和固体酒精均可使用；如果使用液体酒精，推荐95%浓度的液体工业酒精，燃烧效率更高。",
        "tags": ["真实问法别名", "固体酒精", "燃料"],
        "source_rows": "京东自营.xlsx:50",
        "evidence_fields": "product_specs.heat_source,product_specs.usage_instruction",
    },
    {
        "sku": "CW-K04PRO-37",
        "question": "该炉用的是固态酒精还是液体酒精？",
        "answer": "当前时光煮水套装资料只标注95%液体工业酒精，未标注固体酒精适配；请按商品当前说明使用已标注燃料。",
        "tags": ["真实问法别名", "固体酒精", "燃料边界"],
        "source_rows": "京东自营.xlsx:4、14、20、93",
        "evidence_fields": "product_specs.heat_source,product_specs.usage_instruction",
    },
    {
        "sku": "CS-B14",
        "question": "我可以放酒精块进去么？",
        "answer": "当前旋焰酒精炉资料只标注95%液体工业酒精，未把固体酒精列为已确认燃料，因此不能确认酒精块适用；请按商品当前说明使用。",
        "tags": ["真实问法别名", "固体酒精", "燃料边界"],
        "source_rows": "京东自营.xlsx:43",
        "evidence_fields": "product_specs.heat_source,product_specs.usage_instruction",
    },
    {
        "sku": "CW-C84",
        "question": "下面用的什么烧？烧一壶开水要烧多久？",
        "answer": "当前鸣泉水壶资料标注适用明火直烧、卡式炉、分体炉和一体炉；没有把固体酒精、木炭或小柴火单独列为已确认燃料，因此不能按历史客服说法直接确认。资料也没有提供用固体酒精烧开一壶水的固定时长，实际时间会受热源、火力、环境温度和装水量影响。",
        "tags": ["真实问法别名", "固体酒精", "燃料边界", "烧水时长"],
        "source_rows": "天猫.xlsx:24（链接821037235300，已核对为CW-C84相关水壶记录）",
        "evidence_fields": "product_specs.heat_source,product_specs.usage_instruction,product_specs.capacity",
    },
)


def _norm(value: Any) -> str:
    return re.sub(r"[^0-9a-z\u4e00-\u9fff]+", "", str(value or "").casefold())


def _assert_dev_target() -> None:
    if str(settings.APP_ENV or "").strip().lower() != "dev":
        raise RuntimeError("solid alcohol QA apply is restricted to APP_ENV=dev")
    database = database_name_from_url(str(settings.DATABASE_URL or ""))
    if database != "product_knowledge_dev":
        raise RuntimeError(
            f"solid alcohol QA apply is restricted to product_knowledge_dev, got {database!r}"
        )


def main() -> int:
    _assert_dev_target()
    engine.echo = False
    now = datetime.now(timezone.utc)
    created: list[dict[str, str]] = []
    skipped: list[dict[str, str]] = []
    changed_skus: set[str] = set()
    db = SessionLocal()
    try:
        products = {
            str(product.sku or "").strip().upper(): product
            for product in db.query(Product).filter(Product.active_flag.is_(True)).all()
        }
        existing: dict[str, set[str]] = {}
        for qa in db.query(ProductQa).all():
            product = next((item for item in products.values() if item.id == qa.product_id), None)
            if product:
                existing.setdefault(str(product.sku).strip().upper(), set()).add(_norm(qa.question))

        for item in QA_ITEMS:
            sku = str(item["sku"]).strip().upper()
            product = products.get(sku)
            if product is None:
                raise RuntimeError(f"solid alcohol QA references missing active SKU: {sku}")
            question = str(item["question"]).strip()
            answer = str(item["answer"]).strip()
            key = _norm(question)
            if not key or not answer:
                raise RuntimeError(f"solid alcohol QA has empty question/answer for {sku}")
            if key in existing.setdefault(sku, set()):
                skipped.append({"sku": sku, "question": question, "reason": "duplicate_question"})
                continue
            existing[sku].add(key)
            reason = (
                "人工阅读真实客服记录后补充的问法别名；"
                f"source_root={SOURCE_ROOT};source_rows={item['source_rows']};"
                f"evidence_fields={item['evidence_fields']};"
                "答案以当前同SKU产品资料为准，未复制冲突或未核验的历史客服细节。"
            )
            qa = ProductQa(
                product_id=product.id,
                question=question,
                answer=answer,
                tags=json.dumps(list(item.get("tags") or []) + ["manual_history_review"], ensure_ascii=False),
                priority=1,
                integrity_status="approved",
                integrity_reason=reason,
                integrity_model="manual_history_review",
                integrity_audited_at=now,
            )
            db.add(qa)
            created.append({"sku": sku, "question": question})
            changed_skus.add(sku)

        db.commit()
        sync_results: dict[str, dict[str, Any]] = {}
        not_ready: list[str] = []
        for sku in sorted(changed_skus):
            result = product_service.sync_product_to_vector_db(db, sku)
            sync_results[sku] = result
            if result.get("error") or not result.get("ready_for_rag"):
                not_ready.append(sku)
        if not_ready:
            db.rollback()
            raise RuntimeError(f"vector sync is not ready for: {', '.join(not_ready)}")

        print(json.dumps({
            "database": database_name_from_url(str(settings.DATABASE_URL or "")),
            "created": len(created),
            "skipped": skipped,
            "created_rows": created,
            "sync_results": sync_results,
        }, ensure_ascii=False, indent=2, default=str))
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
