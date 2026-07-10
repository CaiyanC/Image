import argparse
import os
import sys
from pathlib import Path

from sqlalchemy import create_engine, text


BACKEND_DIR = Path(__file__).resolve().parents[1]
PROJECT_DIR = BACKEND_DIR.parent
sys.path.insert(0, str(BACKEND_DIR))


def load_env(path: Path) -> None:
    for raw in path.read_text(encoding="utf-8-sig").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ[key.strip()] = value.strip().strip('"').strip("'")


def main() -> None:
    parser = argparse.ArgumentParser(description="Migrate L6 assets and legacy teams in a development database")
    parser.add_argument("--env-file", default=str(BACKEND_DIR / ".env.dev"))
    args = parser.parse_args()
    load_env(Path(args.env_file))
    os.environ["APP_ENV"] = "development"
    os.environ["DEBUG"] = "false"

    from app.core.database import init_db
    from app.core.config import settings

    engine = create_engine(settings.DATABASE_URL, pool_pre_ping=True)
    with engine.connect() as conn:
        database_name = conn.execute(text("SELECT current_database()" if engine.dialect.name == "postgresql" else "SELECT 'sqlite'"))
        database_name = str(database_name.scalar_one())
    if not database_name.endswith("_dev"):
        raise RuntimeError(f"Refusing to migrate non-development database: {database_name}")
    engine.dispose()

    init_db()

    from app.core.database import engine as app_engine
    from app.core.permission_constants import DEPRECATED_EMPTY_GROUP_NAMES, LEGACY_GROUP_NAME_MAP

    with app_engine.begin() as conn:
        before_products = conn.execute(text("SELECT COUNT(*) FROM products")).scalar_one()
        before_qa = conn.execute(text("SELECT COUNT(*) FROM product_qa")).scalar_one()
        obsolete_names = sorted(set(LEGACY_GROUP_NAME_MAP) | set(DEPRECATED_EMPTY_GROUP_NAMES))
        obsolete_ids = [
            row[0] for row in conn.execute(text("""
                SELECT g.id FROM groups g
                WHERE g.group_name = ANY(:names)
                  AND NOT EXISTS (SELECT 1 FROM user_groups ug WHERE ug.group_id = g.id)
                  AND NOT EXISTS (SELECT 1 FROM field_configs fc WHERE fc.role_id = g.id)
            """), {"names": obsolete_names})
        ]
        if obsolete_ids:
            conn.execute(text("DELETE FROM group_permissions WHERE group_id = ANY(:ids)"), {"ids": obsolete_ids})
            conn.execute(text("DELETE FROM groups WHERE id = ANY(:ids)"), {"ids": obsolete_ids})
        conn.execute(text("""
            DELETE FROM group_permissions gp
            USING groups g, permissions p
            WHERE gp.group_id = g.id
              AND gp.permission_id = p.id
              AND g.group_name = ANY(:departments)
              AND NOT (
                  (g.group_name = :executive)
                  OR (g.group_name = :product AND p.permission_key = ANY(:product_keys))
              )
        """), {
            "departments": ["总经办", "产品部"],
            "executive": "总经办",
            "product": "产品部",
            "product_keys": [
                "history.view", "profile.view", "category.read", "product.read",
                "product.create", "product.edit", "product.delete", "product.review",
                "media.download", "tag.edit", "ai.call", "ai.generate",
                "ai.customer_service", "competitor.view", "new_product.view", "export.approved",
            ],
        })
        conn.execute(text("""
            UPDATE product_assets SET
                sub_category = CASE
                    WHEN sku = 'CF-PG19' AND (sub_category IS NULL OR sub_category = '???')
                    THEN :white_background
                    ELSE sub_category
                END,
                material_type = CASE
                    WHEN sku = 'CF-PG19' AND material_type IS NULL THEN 'whiteBackground'
                    ELSE material_type
                END,
                file_name = CASE
                    WHEN file_name IS NULL OR file_name LIKE '/uploads/%'
                    THEN regexp_replace(url, '^.*/', '')
                    ELSE file_name
                END,
                file_format = COALESCE(file_format, NULLIF(regexp_replace(url, '^.*\\.', ''), url)),
                resolution = CASE
                    WHEN sku = 'CF-PG19' THEN COALESCE(resolution, '3508x4961')
                    ELSE resolution
                END,
                aspect_ratio = COALESCE(aspect_ratio, 'auto')
        """), {"white_background": "白底图"})
        after_products = conn.execute(text("SELECT COUNT(*) FROM products")).scalar_one()
        after_qa = conn.execute(text("SELECT COUNT(*) FROM product_qa")).scalar_one()
        remaining_obsolete = conn.execute(text(
            "SELECT COUNT(*) FROM groups WHERE group_name = ANY(:names)"
        ), {"names": obsolete_names}).scalar_one()
        department_count = conn.execute(text("SELECT COUNT(*) FROM groups")).scalar_one()
        if (before_products, before_qa) != (after_products, after_qa):
            raise RuntimeError("Product or QA row counts changed during migration")
        if remaining_obsolete or department_count != 15:
            raise RuntimeError(
                f"Department cleanup incomplete: remaining_obsolete={remaining_obsolete}, "
                f"department_count={department_count}"
            )

    print(
        f"Migrated {database_name}: products={before_products}, qa={before_qa}, "
        f"departments={department_count}, removed_legacy={len(obsolete_ids)}; "
        "L6 assets and departments normalized"
    )


if __name__ == "__main__":
    main()
