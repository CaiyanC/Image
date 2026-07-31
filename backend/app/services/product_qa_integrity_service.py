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
_EXPLICIT_EVIDENCE_CLAIM_GROUPS = {
    "warranty_or_after_sales": ("质保", "保修", "售后"),
    "return_or_refund_policy": ("退货", "换货", "退款", "七天无理由"),
    "sales_channel_or_authenticity": (
        "旗舰店", "淘宝", "京东", "抖音", "授权经销", "官方店", "正品", "购买渠道",
    ),
    "shipping_or_delivery": ("发货", "快递", "物流", "配送"),
    "certification_or_safety_claim": ("认证", "食品级认证", "安全认证"),
}


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
    status = str(payload.get("status") or "").strip().lower()
    reason = str(payload.get("reason") or "").strip()
    if status not in _ALLOWED_STATUSES:
        return {"status": "review", "reason": "语义审核返回了无效结论。"}
    return {"status": status, "reason": (reason or "语义审核未提供可验证原因。")[:1000]}


def _apply_fail_closed_guardrail(
    verdict: dict[str, str],
    *,
    evidence: dict[str, Any],
    question: str | None,
    answer: str | None,
) -> dict[str, str]:
    """Do not let a model approve policy-like claims without explicit SKU evidence."""
    if verdict["status"] != "approved":
        return verdict

    qa_text = f"{question or ''}\n{answer or ''}"
    evidence_text = json.dumps(evidence, ensure_ascii=False)
    for group, markers in _EXPLICIT_EVIDENCE_CLAIM_GROUPS.items():
        if any(marker in qa_text for marker in markers) and not any(marker in evidence_text for marker in markers):
            return {
                "status": "review",
                "reason": f"{group} requires explicit same-SKU evidence; no such evidence was supplied.",
            }

    unsupported_reason_markers = (
        "plausible",
        "does not conflict",
        "standard business practice",
        "standard policy",
        "acceptable",
    )
    if any(marker in verdict["reason"].lower() for marker in unsupported_reason_markers):
        return {
            "status": "review",
            "reason": "Approval lacked a direct-evidence rationale and was quarantined fail-closed.",
        }
    return verdict


async def audit_product_qa_item(db: Session, product: Product, qa: ProductQa) -> dict[str, str]:
    """Persist a fail-closed semantic verdict for one sealed same-SKU QA item."""
    try:
        evidence = _product_evidence(db, product)
        raw = await customer_llm_service.chat_completion(
            db,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "Return only JSON: {status:string,reason:string}. Audit whether the supplied product QA "
                        "is semantically supported and appropriate for the same-product evidence. status must be "
                        "approved, rejected, or review. Approve only when every factual claim in the answer is "
                        "directly supported by the supplied evidence. A generic warranty, policy, service, safety, "
                        "or suitability statement is not approved merely because it is plausible or does not "
                        "contradict the evidence. Reject conflicts or plainly inapplicable QA; use review whenever "
                        "evidence is insufficient. Do not write a replacement answer or infer new facts."
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
        verdict = _apply_fail_closed_guardrail(
            _parse_verdict(raw),
            evidence=evidence,
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
