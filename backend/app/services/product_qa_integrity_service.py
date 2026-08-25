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
from ..models.user import User
from . import customer_llm_service


_ALLOWED_STATUSES = {"approved", "rejected", "review"}
_ALLOWED_CONFLICT_TYPES = {
    "none",
    "direct_conflict",
    "cross_category",
    "invalid_qa",
    "unsupported_inference",
    "unsupported_extension",
}
_REJECTING_CONFLICT_TYPES = {
    "direct_conflict",
    "cross_category",
    "invalid_qa",
    "unsupported_inference",
    "unsupported_extension",
}


def _authoritative_formal_facts(specs: ProductSpecs | None) -> dict[str, dict[str, Any]]:
    """Expose live product columns as an explicit semantic authority map."""
    if specs is None:
        return {}
    facts: dict[str, dict[str, Any]] = {}
    try:
        weight_g = float(getattr(specs, "gross_weight_g", None) or 0)
    except (TypeError, ValueError):
        weight_g = 0.0
    if weight_g > 0:
        facts["weight"] = {
            "value": weight_g,
            "unit": "g",
            "display": f"{weight_g:g} g",
            "source": "product_specs.gross_weight_g",
        }
    for dimension, attribute, source in (
        ("capacity", "capacity", "product_specs.capacity"),
        ("size", "size_info", "product_specs.size_info"),
        ("material", "body_material", "product_specs.body_material"),
        ("color", "color", "product_specs.color"),
        ("surface_finish", "surface_finish", "product_specs.surface_finish"),
        ("heat_source", "heat_source", "product_specs.heat_source"),
        ("usage_instruction", "usage_instruction", "product_specs.usage_instruction"),
    ):
        value = getattr(specs, attribute, None)
        if str(value or "").strip():
            facts[dimension] = {
                "value": value,
                "display": str(value).strip(),
                "source": source,
            }
    return facts


def _product_evidence(db: Session, product: Product) -> dict[str, Any]:
    """Build a bounded, same-SKU evidence bundle for the audit prompt."""
    specs = db.query(ProductSpecs).filter(ProductSpecs.product_id == product.id).first()
    business = db.query(ProductBusiness).filter(ProductBusiness.product_id == product.id).first()
    content = db.query(ProductContent).filter(ProductContent.product_id == product.id).first()
    authoritative_formal_facts = _authoritative_formal_facts(specs)
    return {
        "product_identity": {
            "sku": product.sku,
            "name": product.product_name_cn or product.product_name_en,
            "category": product.category,
            "content_title": getattr(content, "title_cn", None),
        },
        "supplemental_context": {
            "authoritative_formal_facts": authoritative_formal_facts,
            "specs": {
                "material": getattr(specs, "body_material", None),
                "capacity": getattr(specs, "capacity", None),
                "size_info": getattr(specs, "size_info", None),
                "weight_g": getattr(specs, "gross_weight_g", None),
                "color": getattr(specs, "color", None),
                "surface_finish": getattr(specs, "surface_finish", None),
                "heat_source": getattr(specs, "heat_source", None),
                "usage_instruction": getattr(specs, "usage_instruction", None),
            },
            "business": {
                "selling_points": getattr(business, "top_selling_points", None),
                "positioning": getattr(business, "positioning", None),
                "usage_scenarios": getattr(business, "usage_scenarios", None),
            },
            "content": {
                "description": getattr(content, "long_description_cn", None),
                "listing": getattr(content, "listing_cn", None),
            },
        },
        # Compatibility aliases for existing audit consumers; the model receives
        # the explicit identity/context structure above as the semantic boundary.
        "sku": product.sku,
        "name": product.product_name_cn or product.product_name_en,
        "category": product.category,
        "specs": {
            "material": getattr(specs, "body_material", None),
            "capacity": getattr(specs, "capacity", None),
            "size_info": getattr(specs, "size_info", None),
            "weight_g": getattr(specs, "gross_weight_g", None),
            "color": getattr(specs, "color", None),
            "surface_finish": getattr(specs, "surface_finish", None),
            "heat_source": getattr(specs, "heat_source", None),
            "usage_instruction": getattr(specs, "usage_instruction", None),
        },
        "authoritative_formal_facts": authoritative_formal_facts,
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
    evidence_quote = payload.get("evidence_quote", "")
    evidence_dimension = str(payload.get("evidence_dimension") or "").strip()
    if status not in _ALLOWED_STATUSES:
        return {"status": "review", "reason": "语义审核返回了无效结论。"}
    if conflict_type not in _ALLOWED_CONFLICT_TYPES:
        return {"status": "review", "reason": "语义审核返回了无效冲突类型。"}
    if not isinstance(reason, str) or not reason.strip():
        return {"status": "review", "reason": "语义审核未提供可验证原因。"}
    if conflict_type in {
        "direct_conflict",
        "unsupported_inference",
        "unsupported_extension",
    } and (
        not isinstance(evidence_quote, str) or not evidence_quote.strip()
    ):
        return {"status": "review", "reason": "语义审核未提供可验证的原文证据。"}
    return {
        "status": status,
        "conflict_type": conflict_type,
        "reason": reason,
        "evidence_quote": evidence_quote,
        "evidence_dimension": evidence_dimension,
    }


def _normalize_supplemental_verdict(
    verdict: dict[str, str],
    *,
    question: str | None,
    answer: str | None,
    evidence: dict[str, Any] | None = None,
) -> dict[str, str]:
    """Normalize a valid classifier result around concrete conflict types."""
    if not str(question or "").strip() or not str(answer or "").strip():
        return {"status": "rejected", "reason": "Question or answer is empty."}
    conflict_type = verdict.get("conflict_type")
    if conflict_type not in _ALLOWED_CONFLICT_TYPES:
        return {"status": "review", "reason": verdict["reason"]}
    if conflict_type in {"direct_conflict", "unsupported_extension"}:
        authoritative_facts = (
            (evidence or {}).get("authoritative_formal_facts")
            if isinstance(evidence, dict)
            else {}
        )
        dimension = str(verdict.get("evidence_dimension") or "").strip()
        if not isinstance(authoritative_facts, dict) or dimension not in authoritative_facts:
            return {"status": "review", "reason": "语义审核未绑定到同SKU权威事实维度。"}
    if conflict_type in _REJECTING_CONFLICT_TYPES:
        return {"status": "rejected", "reason": verdict["reason"]}
    return {"status": "approved", "reason": verdict["reason"]}


async def _audit_chat_completion(
    db: Session,
    *,
    messages: list[dict[str, Any]],
    user: User | None,
    max_tokens: int,
) -> str:
    """Keep provider logging commits outside the caller's audit transaction."""
    model_db = Session(bind=db.get_bind(), expire_on_commit=False)
    model_user = user
    try:
        user_id = getattr(user, "id", None) if user is not None else None
        if user_id is not None:
            model_user = model_db.get(User, user_id) or user
        return await customer_llm_service.chat_completion(
            model_db,
            messages=messages,
            temperature=0,
            max_tokens=max_tokens,
            purpose="product_qa_integrity_audit",
            api_model_override=str(settings.SEMANTIC_PREPLAN_MODEL or "").strip() or None,
            response_format={"type": "json_object"} if settings.SEMANTIC_PREPLAN_JSON_MODE else None,
            thinking={"type": "disabled"} if settings.SEMANTIC_PREPLAN_THINKING_DISABLED else None,
            user=model_user,
        )
    finally:
        model_db.close()


async def audit_product_qa_item(
    db: Session,
    product: Product,
    qa: ProductQa,
    *,
    user: User | None = None,
) -> dict[str, str]:
    """Persist a conflict-only semantic verdict for one sealed same-SKU QA item."""
    if not str(qa.question or "").strip() or not str(qa.answer or "").strip():
        verdict = {"status": "rejected", "reason": "Question or answer is empty."}
    else:
        try:
            evidence = _product_evidence(db, product)
            identity_raw = await _audit_chat_completion(
                db,
                messages=[
                    {
                        "role": "system",
                        "content": (
                            'Return only exact JSON with keys "status", "conflict_type", "reason", "evidence_quote", and "evidence_dimension". '
                            'Audit only whether the supplied QA is about this product identity. "conflict_type" must be '
                            '"none", "cross_category", or "invalid_qa". product_identity is authoritative. This first pass '
                            "must not judge whether a weight, capacity, compatibility claim, or other fact is true; the next "
                            "same-SKU evidence pass owns factual conflicts. A question about this product's own measurements, "
                            "material, use, or compatibility remains about this product even when it names an external stove, "
                            "fuel, accessory, food, or use environment. Mentioning an external compatibility target does not "
                            "claim that target is included in the product. Size/capacity descriptors, packaging labels, or a "
                            "parenthetical variant already present in the canonical product name also do not create another "
                            "component. Return cross_category only when the QA attributes the core operation or internal "
                            "mechanism of a plainly different product type to this product, such as grinder adjustment on a "
                            "moka pot with no grinder component. Do not infer a distinct included component from a broad "
                            "category, but do not reject ordinary same-product questions merely because detailed fields are "
                            "absent from product_identity. Use invalid_qa only for empty or unusable text. Otherwise return "
                            "approved/none so the factual evidence pass can decide support."
                        ),
                    },
                    {
                        "role": "user",
                        "content": json.dumps(
                            {
                                "product_identity": evidence["product_identity"],
                                "qa": {"question": qa.question, "answer": qa.answer},
                            },
                            ensure_ascii=False,
                        ),
                    },
                ],
                max_tokens=200,
                user=user,
            )
            identity_verdict = _parse_verdict(identity_raw)
            identity_conflict = identity_verdict.get("conflict_type")
            if identity_conflict == "cross_category":
                verdict = _normalize_supplemental_verdict(
                    identity_verdict,
                    question=qa.question,
                    answer=qa.answer,
                    evidence=evidence,
                )
            elif identity_conflict == "invalid_qa":
                verdict = _normalize_supplemental_verdict(
                    identity_verdict,
                    question=qa.question,
                    answer=qa.answer,
                    evidence=evidence,
                )
            elif identity_conflict != "none":
                verdict = {"status": "review", "reason": identity_verdict["reason"]}
            else:
                raw = await _audit_chat_completion(
                    db,
                    messages=[
                    {
                        "role": "system",
                        "content": (
                            'Return only exact JSON with keys "status", "conflict_type", "reason", "evidence_quote", and "evidence_dimension". '
                            '"status" must be "approved", "rejected", or "review". "conflict_type" must be '
                            '"none", "direct_conflict", "cross_category", "invalid_qa", '
                            '"unsupported_inference", or "unsupported_extension". '
                            'status must be "rejected" whenever conflict_type is direct_conflict, cross_category, '
                            'invalid_qa, unsupported_inference, or unsupported_extension; it must be "approved" for none. '
                            "Audit whether the supplied QA belongs to this same product. Treat same-SKU QA as a supplemental fact "
                            "source: absence of an objective fact or policy from product-master evidence is not disproof and must not "
                            "cause rejection or review. A concrete standalone supplemental fact such as a warranty term may therefore "
                            "be approved even when the master record is silent. "
                            "Every item in supplemental_context.authoritative_formal_facts is a live, same-SKU authoritative value for the "
                            "named dimension. It is never optional context. First determine semantically whether the QA asserts one of those "
                            "same dimensions; do not rely on wording overlap. If authoritative_formal_facts contains weight=225 g and the QA "
                            "asserts 300 g, that is a direct_conflict, not missing master data. "
                            "If it does, a different numeric value or incompatible value is a direct_conflict even when the QA sounds plausible. "
                            "For a closed compatibility dimension, such as the supported heat-source list, an unlisted specific option is not "
                            "proved by a broader neighbouring term. For example, open flame, portable stove, or gas stove does not by itself "
                            "prove alcohol-stove compatibility. Classify that unsupported semantic expansion as unsupported_extension unless "
                            "another same-SKU source explicitly states it. The authoritative field may still contain several equivalent labels; "
                            "judge equivalence semantically rather than by literal substring matching. "
                            "product_identity is authoritative for product category and identity. supplemental_context "
                            "may contain copied or contaminated detail and must never override product_identity when "
                            "deciding whether QA is plainly cross-category. If the QA requires a distinct component, "
                            "mechanism, or appliance that product_identity does not identify as this product or an "
                            "included component, classify it as cross_category even when supplemental_context claims "
                            "that capability. A broad parent category alone is not proof that the distinct capability "
                            "exists. "
                            'For "direct_conflict", evidence_quote must be an exact nonempty '
                            'quote copied from same-SKU evidence that states the opposite fact; missing evidence is never a conflict. Use "direct_conflict" only for a concrete value that '
                            'contradicts same-SKU evidence, "cross_category" only for a plainly incompatible '
                            'product category or contaminated template, and "invalid_qa" only when the question '
                            'or answer is empty or unusable. Use "unsupported_inference" when the answer presents a subjective outcome, '
                            'suitability judgement, promise, safety conclusion, or ease/burden claim as a verified product fact even though '
                            'its only basis is an adjacent measurement or property and supplemental_context does not independently state '
                            'that outcome. An objective property does not by itself prove a distinct customer outcome. For this type, '
                            'evidence_quote must be the exact unsupported clause copied from the QA answer. Do not use this type merely '
                            'because an objective supplemental fact is absent from master data. Use "unsupported_extension" when the answer '
                            'expands a nonempty authoritative formal field into a more specific or additional confirmed capability that the '
                            'same-SKU evidence does not entail; evidence_quote must be the exact unsupported clause from the QA answer. '
                            'For direct_conflict and unsupported_extension, evidence_dimension must be the exact semantic dimension key from '
                            'authoritative_formal_facts, such as weight, capacity, material, or heat_source. Formatting differences in '
                            'evidence_quote, such as 225g versus 225 g, do not change the semantic verdict; evidence_dimension is the machine-checked '
                            'same-SKU binding. For other conflict types use an empty evidence_dimension when no formal dimension applies. '
                            'A QA row is an immutable customer-visible answer: if one clause is unsupported, reject the whole row even when '
                            'another clause is supported. Do not downgrade that mixed row to review and do not describe rejection as uncertain. '
                            'Otherwise use "none" and approve. Use review only '
                            "when technically unable to classify. Preserve a concise, nonempty reason. Do not "
                            "write a replacement answer or infer a conflict from missing master data."
                        ),
                    },
                    {
                        "role": "user",
                        "content": json.dumps(
                            {
                                "product_identity": evidence["product_identity"],
                                "supplemental_context": evidence["supplemental_context"],
                                "qa": {"question": qa.question, "answer": qa.answer},
                            },
                            ensure_ascii=False,
                        ),
                    },
                ],
                    max_tokens=260,
                    user=user,
                )
                verdict = _normalize_supplemental_verdict(
                    _parse_verdict(raw),
                    question=qa.question,
                    answer=qa.answer,
                    evidence=evidence,
                )
        except Exception:
            verdict = {"status": "review", "reason": "语义审核暂时不可用。"}
    # Keep the ORM instance supplied by the caller.  The development database
    # stores this table's primary key as PostgreSQL UUID while the legacy model
    # maps it as String.  A newly inserted row can therefore be keyed in
    # SQLAlchemy's identity map by the generated string and, after a refresh,
    # be loaded again by its UUID value.  Re-loading here and flushing both
    # objects makes SQLAlchemy sort a UUID and a str primary key, which raises
    # before the audit verdict is persisted.  All call sites pass the
    # transaction's persistent QA instance, so there is no need to load a
    # second identity.
    audited_at = datetime.now(timezone.utc)
    integrity_model = str(settings.SEMANTIC_PREPLAN_MODEL or "deepseek")
    qa.integrity_status = verdict["status"]
    qa.integrity_reason = verdict["reason"]
    qa.integrity_model = integrity_model
    qa.integrity_audited_at = audited_at
    # Scope the flush to the audited row.  Besides avoiding the duplicate
    # identity issue above, this prevents unrelated pending work in a caller's
    # Session from being flushed as a side effect of semantic auditing.
    db.flush([qa])
    return verdict
