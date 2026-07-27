"""Customer-visible evidence bound to one canonical SKU."""

from dataclasses import dataclass
from typing import Iterable


CUSTOMER_VISIBLE = "customer_visible"
ALLOWED_SOURCE_TYPES = {
    "structured_field",
    "product_qa",
    "product_content",
    "knowledge_chunk",
}
INVALID_PLACEHOLDERS = {
    "",
    "-",
    "--",
    "n/a",
    "na",
    "nan",
    "none",
    "null",
    "unknown",
    "暂无",
    "暂无资料",
    "待补充",
    "待确认",
    "未填写",
}


@dataclass(frozen=True)
class CustomerEvidenceItem:
    evidence_id: str
    sku: str
    source_type: str
    source: str
    field: str
    value: str

    def to_customer_evidence(self) -> dict:
        return {
            "evidence_id": self.evidence_id,
            "sku": self.sku,
            "source_type": self.source_type,
            "source": self.source,
            "field": self.field,
            "value": self.value,
        }


@dataclass(frozen=True)
class CustomerEvidenceBundle:
    sku: str
    product_name: str
    items: tuple[CustomerEvidenceItem, ...]

    def value_for_field(self, field: str) -> str:
        requested_field = str(field or "").strip()
        for item in self.items:
            if item.field == requested_field:
                return item.value
        return ""

    def evidence_for_field(self, field: str) -> tuple[CustomerEvidenceItem, ...]:
        requested_field = str(field or "").strip()
        return tuple(item for item in self.items if item.field == requested_field)

    def to_customer_evidence(self) -> list[dict]:
        return [item.to_customer_evidence() for item in self.items]


def _valid_customer_value(value: object) -> str:
    normalized = str(value or "").strip()
    if normalized.casefold() in INVALID_PLACEHOLDERS:
        return ""
    return normalized


def build_customer_evidence_bundle(
    *,
    sku: str,
    product_name: str,
    evidence_items: Iterable[dict],
) -> CustomerEvidenceBundle:
    canonical_sku = str(sku or "").strip().upper()
    if not canonical_sku:
        raise ValueError("customer evidence bundle requires a canonical SKU")
    accepted: list[CustomerEvidenceItem] = []
    seen_evidence_ids: set[str] = set()
    for raw_item in evidence_items:
        if not isinstance(raw_item, dict):
            continue
        item_sku = str(raw_item.get("sku") or "").strip().upper()
        if item_sku and item_sku != canonical_sku:
            raise ValueError(
                f"cross-SKU evidence rejected: expected {canonical_sku}, got {item_sku}"
            )
        if str(raw_item.get("visibility") or "").strip() != CUSTOMER_VISIBLE:
            continue
        source_type = str(raw_item.get("source_type") or "").strip()
        if source_type not in ALLOWED_SOURCE_TYPES:
            continue
        evidence_id = str(raw_item.get("evidence_id") or "").strip()
        source = str(raw_item.get("source") or "").strip()
        field = str(raw_item.get("field") or "").strip()
        value = _valid_customer_value(raw_item.get("value"))
        if (
            not evidence_id
            or evidence_id in seen_evidence_ids
            or not source
            or not field
            or not value
        ):
            continue
        seen_evidence_ids.add(evidence_id)
        accepted.append(CustomerEvidenceItem(
            evidence_id=evidence_id,
            sku=canonical_sku,
            source_type=source_type,
            source=source,
            field=field,
            value=value,
        ))
    return CustomerEvidenceBundle(
        sku=canonical_sku,
        product_name=str(product_name or canonical_sku).strip() or canonical_sku,
        items=tuple(accepted),
    )
