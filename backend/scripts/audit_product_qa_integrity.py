"""Audit Product QA for customer evidence eligibility in the development database."""

import argparse
import asyncio
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.config import database_name_from_url, settings
from app.core.database import SessionLocal
from app.models.product import Product
from app.models.product_qa import ProductQa
from app.models.user import User
from app.services import product_qa_integrity_service, product_vector_index_service


def ensure_development_target(current_settings: Any = settings) -> None:
    """Refuse to audit unless both the declared environment and database are dev."""
    if str(getattr(current_settings, "APP_ENV", "")).lower() != "dev":
        raise RuntimeError("Product QA history audit requires the development environment.")
    if database_name_from_url(str(getattr(current_settings, "DATABASE_URL", ""))) != "product_knowledge_dev":
        raise RuntimeError("Product QA history audit requires product_knowledge_dev.")


async def audit_history(
    db,
    *,
    apply: bool,
    limit: int | None = None,
    offset: int = 0,
) -> list[dict[str, str]]:
    """Audit QA rows; dry runs roll back every persistence side effect."""
    query = db.query(ProductQa, Product).join(Product, Product.id == ProductQa.product_id)
    query = query.order_by(Product.sku.asc(), ProductQa.priority.desc().nullslast())
    if offset:
        query = query.offset(offset)
    if limit:
        query = query.limit(limit)
    rows = query.all()
    audit_user = (
        db.query(User)
        .filter(User.username == "admin", User.is_active.is_(True))
        .first()
    )
    if audit_user is None:
        raise RuntimeError("Development QA audit requires an active admin user.")
    ledger: list[dict[str, str]] = []
    changed_skus: set[str] = set()
    for qa, product in rows:
        previous_status = str(qa.integrity_status or "")
        verdict = await product_qa_integrity_service.audit_product_qa_item(
            db,
            product,
            qa,
            user=audit_user,
        )
        status = verdict["status"]
        if status != previous_status:
            changed_skus.add(str(product.sku))
        ledger.append({
            "qa_id": str(qa.id),
            "sku": str(product.sku),
            "status": status,
            "reason": verdict["reason"],
        })
    if not apply:
        db.rollback()
        return ledger
    db.commit()
    for sku in sorted(changed_skus):
        product_vector_index_service.index_product(db, sku)
    return ledger


def apply_audit_ledger(db, ledger: list[dict[str, str]]) -> None:
    """Persist a reviewed dry-run ledger exactly once, then refresh affected SKU indexes."""
    changed_skus: set[str] = set()
    seen_ids: set[str] = set()
    for item in ledger:
        qa_id = str(item.get("qa_id") or "").strip()
        sku = str(item.get("sku") or "").strip()
        status = str(item.get("status") or "").strip().lower()
        reason = str(item.get("reason") or "").strip()
        if not qa_id or not sku or status not in {"approved", "rejected", "review"} or not reason:
            raise ValueError("Audit ledger contains an invalid item.")
        if qa_id in seen_ids:
            raise ValueError("Audit ledger contains duplicate QA ids.")
        seen_ids.add(qa_id)
        row = db.query(ProductQa, Product).join(Product, Product.id == ProductQa.product_id).filter(ProductQa.id == qa_id).first()
        if not row or str(row[1].sku) != sku:
            raise ValueError("Audit ledger no longer matches the development database.")
        qa, product = row
        if str(qa.integrity_status or "") != status:
            changed_skus.add(str(product.sku))
        qa.integrity_status = status
        qa.integrity_reason = reason[:1000]
        qa.integrity_model = "deepseek"
        qa.integrity_audited_at = datetime.now(timezone.utc)

    db.commit()
    for sku in sorted(changed_skus):
        product_vector_index_service.index_product(db, sku)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    apply_group = parser.add_mutually_exclusive_group()
    apply_group.add_argument("--apply", action="store_true", help="Run and persist fresh verdicts, then reindex changed SKUs.")
    apply_group.add_argument("--apply-ledger", type=Path, help="Persist a reviewed dry-run JSON ledger without re-calling the model.")
    parser.add_argument("--limit", type=int, default=None, help="Audit at most this many QA rows.")
    parser.add_argument("--offset", type=int, default=0, help="Skip this many QA rows after deterministic ordering.")
    parser.add_argument("--output", type=Path, default=None, help="Write the JSON audit ledger to this file.")
    args = parser.parse_args()
    ensure_development_target()
    db = SessionLocal()
    try:
        if args.apply_ledger:
            payload = json.loads(args.apply_ledger.read_text(encoding="utf-8"))
            ledger = payload.get("items")
            if not isinstance(ledger, list) or payload.get("count") != len(ledger):
                raise ValueError("Audit ledger is incomplete or malformed.")
            apply_audit_ledger(db, ledger)
            print(json.dumps({"apply_ledger": str(args.apply_ledger), "count": len(ledger)}, ensure_ascii=False))
            return 0
        ledger = asyncio.run(audit_history(db, apply=args.apply, limit=args.limit, offset=args.offset))
        output = {"apply": args.apply, "offset": args.offset, "count": len(ledger), "items": ledger}
        serialized = json.dumps(output, ensure_ascii=False, indent=2)
        if args.output:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(serialized, encoding="utf-8")
        print(serialized)
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
