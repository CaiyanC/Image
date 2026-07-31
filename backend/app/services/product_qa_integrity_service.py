"""Semantic integrity boundary for customer-visible product QA."""

import json
import re
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.orm import Session

from ..core.config import settings
from ..models.product import Product
from ..models.product_business import ProductBusiness
from ..models.product_content import ProductContent
from ..models.product_qa import ProductQa
from ..models.product_specs import ProductSpecs
from . import customer_llm_service


_ALLOWED_STATUSES = {"approved", "rejected", "review"}
_ALLOWED_CONFLICT_TYPES = {"none", "direct_conflict", "cross_category", "invalid_qa"}
_REJECTING_CONFLICT_TYPES = {"direct_conflict", "cross_category", "invalid_qa"}


def _product_evidence(db: Session, product: Product) -> dict[str, Any]:
    """Build a bounded, same-SKU evidence bundle for the audit prompt."""
    specs = db.query(ProductSpecs).filter(ProductSpecs.product_id == product.id).first()
    business = db.query(ProductBusiness).filter(ProductBusiness.product_id == product.id).first()
    content = db.query(ProductContent).filter(ProductContent.product_id == product.id).first()
    return {
        "sku": product.sku,
        "name": product.product_name_cn or product.product_name_en,
        "category": product.category,
        "specs": {
            "material": getattr(specs, "body_material", None),
            "capacity": getattr(specs, "capacity", None),
            "heat_source": getattr(specs, "heat_source", None),
            "usage_instruction": getattr(specs, "usage_instruction", None),
        },
        "business": {
            "selling_points": getattr(business, "top_selling_points", None),
            "positioning": getattr(business, "positioning", None),
            "usage_scenarios": getattr(business, "usage_scenarios", None),
        },
        "content": {
            "title": getattr(content, "title_cn", None),
            "description": getattr(content, "long_description_cn", None),
            "listing": getattr(content, "listing_cn", None),
        },
    }


def _parse_verdict(raw: str) -> dict[str, str]:
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", str(raw or "").strip(), flags=re.IGNORECASE).strip()
    try:
        payload = json.loads(text)
    except (TypeError, ValueError):
        return {"status": "review", "reason": "语义审核未返回可验证结论。"}
    if not isinstance(payload, dict):
        return {"status": "review", "reason": "语义审核未返回可验证结论。"}
    status = str(payload.get("status") or "").strip().lower()
    conflict_type = payload.get("conflict_type")
    reason = payload.get("reason")
    if status not in _ALLOWED_STATUSES:
        return {"status": "review", "reason": "语义审核返回了无效结论。"}
    if conflict_type not in _ALLOWED_CONFLICT_TYPES:
        return {"status": "review", "reason": "语义审核返回了无效冲突类型。"}
    if not isinstance(reason, str) or not reason.strip():
        return {"status": "review", "reason": "语义审核未提供可验证原因。"}
    return {
        "status": status,
        "conflict_type": conflict_type,
        "reason": reason,
    }


def _normalize_supplemental_verdict(
    verdict: dict[str, str],
    *,
    question: str | None,
    answer: str | None,
) -> dict[str, str]:
    """Normalize a valid classifier result around concrete conflict types."""
    if not str(question or "").strip() or not str(answer or "").strip():
        return {"status": "rejected", "reason": "Question or answer is empty."}
    conflict_type = verdict.get("conflict_type")
    if conflict_type not in _ALLOWED_CONFLICT_TYPES:
        return {"status": "review", "reason": verdict["reason"]}
    if conflict_type in _REJECTING_CONFLICT_TYPES:
        return {"status": "rejected", "reason": verdict["reason"]}
    return {"status": "approved", "reason": verdict["reason"]}


async def audit_product_qa_item(db: Session, product: Product, qa: ProductQa) -> dict[str, str]:
    """Persist a conflict-only semantic verdict for one sealed same-SKU QA item."""
    if not str(qa.question or "").strip() or not str(qa.answer or "").strip():
        verdict = {"status": "rejected", "reason": "Question or answer is empty."}
    else:
        try:
            evidence = _product_evidence(db, product)
            raw = await customer_llm_service.chat_completion(
                db,
                messages=[
                    {
                        "role": "system",
                        "content": (
                            'Return only exact JSON with keys "status", "conflict_type", and "reason". '
                            '"status" must be "approved", "rejected", or "review". "conflict_type" must be '
                            '"none", "direct_conflict", "cross_category", or "invalid_qa". Audit whether the '
                            "supplied QA belongs to this same product. Treat same-SKU QA as a supplemental fact "
                            "source: absence of a field from product-master evidence is not disproof and must not "
                            'cause rejection or review. Use "direct_conflict" only for a concrete value that '
                            'contradicts same-SKU evidence, "cross_category" only for a plainly incompatible '
                            'product category or contaminated template, and "invalid_qa" only when the question '
                            'or answer is empty or unusable. Otherwise use "none" and approve. Use review only '
                            "when technically unable to classify. Preserve a concise, nonempty reason. Do not "
                            "write a replacement answer or infer a conflict from missing master data."
                        ),
                    },
                    {
                        "role": "user",
                        "content": json.dumps(
                            {
                                "same_sku_evidence": evidence,
                                "qa": {"question": qa.question, "answer": qa.answer},
                            },
                            ensure_ascii=False,
                        ),
                    },
                ],
                temperature=0,
                max_tokens=200,
                purpose="product_qa_integrity_audit",
                api_model_override=str(settings.SEMANTIC_PREPLAN_MODEL or "").strip() or None,
                response_format={"type": "json_object"} if settings.SEMANTIC_PREPLAN_JSON_MODE else None,
                thinking={"type": "disabled"} if settings.SEMANTIC_PREPLAN_THINKING_DISABLED else None,
            )
            verdict = _normalize_supplemental_verdict(
                _parse_verdict(raw),
                question=qa.question,
                answer=qa.answer,
            )
        except Exception:
            verdict = {"status": "review", "reason": "语义审核暂时不可用。"}
    qa.integrity_status = verdict["status"]
    qa.integrity_reason = verdict["reason"]
    qa.integrity_model = "deepseek"
    qa.integrity_audited_at = datetime.now(timezone.utc)
    db.flush()
    return verdict
