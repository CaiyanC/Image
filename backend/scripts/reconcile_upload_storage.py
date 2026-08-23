"""Audit uploads and optionally migrate referenced legacy files or remove old orphans."""

import argparse
import json
import sys
from pathlib import Path

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.config import settings
from app.core.database import SessionLocal
from app.services.storage_reconciliation_service import reconcile_upload_storage


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply-cleanup", action="store_true")
    parser.add_argument("--migrate-legacy", action="store_true")
    parser.add_argument("--minimum-age-hours", type=int, default=24)
    parser.add_argument(
        "--confirm-environment",
        choices=("dev", "prod", "preview"),
        help="Required for any write and must match APP_ENV.",
    )
    args = parser.parse_args()
    mutating = args.apply_cleanup or args.migrate_legacy
    if mutating and args.confirm_environment != settings.APP_ENV:
        raise RuntimeError("Write mode requires --confirm-environment matching APP_ENV")

    db = SessionLocal()
    try:
        report = reconcile_upload_storage(
            db,
            apply_cleanup=args.apply_cleanup,
            migrate_legacy=args.migrate_legacy,
            minimum_age_hours=args.minimum_age_hours,
        )
    finally:
        db.close()
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if not report["errors"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
