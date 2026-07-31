"""Apply a reviewed product-specs correction ledger in the development database."""

import argparse
import json
import sys
from pathlib import Path

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.config import database_name_from_url, settings
from app.core.database import SessionLocal
from app.models.product import Product
from app.models.product_specs import ProductSpecs
from app.services import product_vector_index_service


def ensure_development_target() -> None:
    if str(settings.APP_ENV or "").lower() != "dev":
        raise RuntimeError("Product specs review requires the development environment.")
    if database_name_from_url(str(settings.DATABASE_URL or "")) != "product_knowledge_dev":
        raise RuntimeError("Product specs review requires product_knowledge_dev.")


def apply_ledger(db, items: list[dict[str, str]]) -> None:
    seen_skus: set[str] = set()
    for item in items:
        sku = str(item.get("sku") or "").strip().upper()
        field = str(item.get("field") or "").strip()
        value = item.get("value")
        reason = str(item.get("reason") or "").strip()
        if not sku or field != "usage_instruction" or not isinstance(value, str) or not reason or sku in seen_skus:
            raise ValueError("Product specs review ledger contains an invalid item.")
        seen_skus.add(sku)
        product = db.query(Product).filter(Product.sku == sku).first()
        specs = db.query(ProductSpecs).filter(ProductSpecs.product_id == product.id).first() if product else None
        if not specs:
            raise ValueError(f"Product specs review ledger no longer matches {sku}.")
        specs.usage_instruction = value
    db.commit()
    for sku in sorted(seen_skus):
        product_vector_index_service.index_product(db, sku)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("ledger", type=Path)
    args = parser.parse_args()
    ensure_development_target()
    payload = json.loads(args.ledger.read_text(encoding="utf-8"))
    items = payload.get("items")
    if not isinstance(items, list) or payload.get("count") != len(items):
        raise ValueError("Product specs review ledger is incomplete or malformed.")
    db = SessionLocal()
    try:
        apply_ledger(db, items)
    finally:
        db.close()
    print(json.dumps({"ledger": str(args.ledger), "count": len(items)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
