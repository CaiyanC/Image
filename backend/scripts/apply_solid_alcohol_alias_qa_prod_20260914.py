"""Apply the reviewed solid-alcohol QA batch to production.

This wrapper reuses the exact QA definitions and upsert/sync implementation
from the development script, but requires both the production app environment
and the production database name before it can write anything.
"""

from __future__ import annotations

from apply_solid_alcohol_alias_qa_dev_20260911 import apply_qa


if __name__ == "__main__":
    raise SystemExit(apply_qa("prod", "product_knowledge"))
