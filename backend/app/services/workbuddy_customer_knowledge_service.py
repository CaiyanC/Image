"""Product lookup and explicitly confirmed QA capture for the staff connector."""

import hashlib
import json
import re
import unicodedata
from datetime import datetime, timezone
from io import BytesIO
from urllib.parse import parse_qs, urlencode, urlsplit

from fastapi import HTTPException, Request
from sqlalchemy import case, func, or_
from sqlalchemy.orm import Session

from ..models.knowledge_base import CustomerServiceConversation, CustomerServiceMessage
from ..models.customer_product_link import CustomerProductLink
from ..models.product import Product
from ..models.product_qa import ProductQa
from ..models.user import User
from . import customer_listing_source, knowledge_service, operation_log_service, product_qa_integrity_service, product_service


QA_REVISION_STATUS = "revision"
_PERSONAL_DATA = re.compile(
    r"https?://|www\.|[\w.+-]+@[\w.-]+\.\w+|(?<!\d)(?:\+?86[ -]?)?1[3-9]\d(?:[ -]?\d){8}(?!\d)"
    r"|(?:订单号|运单号|快递单号|手机号|收货地址|身份证号|收件人)\s*(?:[：:=]\s*\S|[A-Z\d]{5,})",
    re.IGNORECASE,
)


def _normalized(value: str) -> str:
    return "".join(
        char for char in unicodedata.normalize("NFKC", value).casefold()
        if not char.isspace() and not unicodedata.category(char).startswith("P")
    )


def _qa_text_key(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value).casefold()
    return "".join(normalized.split()).rstrip("?。!！")


def marketplace_item(url: str) -> tuple[str, str] | None:
    try:
        parsed = urlsplit("https://" + url if url.startswith("www.") else url)
    except ValueError:
        return None
    if parsed.scheme not in {"http", "https"} or parsed.username is not None:
        return None
    host = parsed.hostname
    params = parse_qs(parsed.query)
    if host in {"item.jd.com", "item.m.jd.com"}:
        match = re.fullmatch(r"/(?:product/)?([0-9]+)\.html/?", parsed.path)
        return ("jd", match[1]) if match and len(match[1]) <= 64 else None
    if host in {"item.taobao.com", "detail.tmall.com", "h5.m.taobao.com"}:
        if parsed.path not in {"/item.htm", "/awp/core/detail.htm"}:
            return None
        platform, keys = "taobao", ("id", "itemId", "item_id")
    elif host == "haohuo.jinritemai.com" and parsed.path.startswith("/ecommerce/trade/detail/"):
        platform, keys = "douyin", ("id", "product_id")
    else:
        return None
    ids = {value for key in keys for value in params.get(key, [])}
    if len(ids) == 1:
        item_id = ids.pop()
        if re.fullmatch(r"[0-9]{1,64}", item_id):
            return platform, item_id
    return None


def find_products(db: Session, query: str, limit: int) -> dict:
    links = re.findall(r"https?://[^\s，。；<>]+|www\.[^\s，。；<>]+", query, re.IGNORECASE)
    if links:
        identity = marketplace_item(links[0].rstrip(".,;)]）】")) if len(links) == 1 else None
        if identity is None:
            return {"status": "unsupported_link", "items": [], "message": "请提供一个商品详情页长链接，或输入商品名称。"}
        platform, item_id = identity
        rows = db.query(Product.sku, Product.product_name_cn).join(
            CustomerProductLink, CustomerProductLink.product_id == Product.id,
        ).filter(CustomerProductLink.platform == platform, CustomerProductLink.item_id == item_id,
                 Product.active_flag.is_(True)).order_by(Product.sku).limit(max(limit, 2)).all()
        return {
            "status": "mapped_link" if len(rows) == 1 else "choose_variant" if rows else "link_mapping_missing",
            "platform": platform, "item_id": item_id,
            "items": [{"sku": row.sku, "name": row.product_name_cn} for row in rows[:limit]],
        }
    sku = func.upper(Product.sku)
    exact_sku = sku == query.upper()
    exact_name = func.lower(Product.product_name_cn) == query.lower()
    active = db.query(Product.sku, Product.product_name_cn).filter(Product.active_flag.is_(True))
    rows = active.filter(
        or_(exact_sku, Product.sku.icontains(query, autoescape=True),
            Product.product_name_cn.icontains(query, autoescape=True)),
    ).order_by(case((exact_sku, 0), (exact_name, 1), else_=2), Product.sku).limit(limit + 1).all()
    if not rows:
        title = _normalized(query)
        candidates = []
        for row in active.all():
            name = _normalized(row.product_name_cn)
            if len(name) >= 3 and len(title) >= 3 and (name in title or title in name):
                rank = (name != title, abs(len(name) - len(title)), row.sku)
                candidates.append((rank, row))
        rows = [row for _, row in sorted(candidates, key=lambda item: item[0])[:limit + 1]]
    if rows and rows[0].sku.upper() == query.upper():
        return {"status": "exact_sku", "items": [{"sku": rows[0].sku, "name": rows[0].product_name_cn}]}
    return {
        "status": "candidates" if rows else "no_match",
        "items": [{"sku": row.sku, "name": row.product_name_cn} for row in rows[:limit]],
        "has_more": len(rows) > limit,
    }


def _active_product(db: Session, sku: str, *, lock: bool = False) -> Product:
    query = db.query(Product).filter(func.upper(Product.sku) == sku.upper(), Product.active_flag.is_(True))
    product = (query.with_for_update() if lock else query).one_or_none()
    if product is None:
        raise HTTPException(status_code=404, detail="找不到该 SKU 的有效商品")
    return product


def get_customer_product_profile(db: Session, sku: str) -> dict:
    product = _active_product(db, sku)
    detail = product_service.get_product_detail(db, product.sku)
    specs = detail.get("specs") or {}
    content = detail.get("content") or {}
    return {
        "sku": product.sku,
        "product_name": product.product_name_cn,
        "product_updated_at": product.updated_at.isoformat() if product.updated_at else None,
        "specs": {key: specs.get(key) for key in (
            "size_info", "capacity", "gross_weight_g", "body_material", "color", "surface_finish",
            "heat_source", "power", "technical_advantages", "usage_instruction", "updated_at",
        )},
        "content": {key: content.get(key) for key in (
            "title_cn", "long_description_cn", "listing_cn", "updated_at",
        )},
    }


def export_customer_product_profile(db: Session, sku: str) -> tuple[str, int, bytes]:
    from docx import Document
    from docx.oxml.ns import qn
    from docx.shared import Pt

    profile = get_customer_product_profile(db, sku)
    document = Document()
    for name in ("Normal", "Title", "Heading 1"):
        style = document.styles[name]
        style.font.name = "Microsoft YaHei"
        style.element.get_or_add_rPr().rFonts.set(qn("w:eastAsia"), "Microsoft YaHei")
    document.styles["Normal"].font.size = Pt(11)
    for border in document.styles["Title"].element.xpath(".//w:pBdr"):
        border.getparent().remove(border)
    document.add_paragraph("商品资料", style="Title")
    document.add_paragraph(f'{profile["sku"]}  {profile["product_name"]}')
    document.add_paragraph("以下为当前商品主档记录，更新日期为系统记录时间。")
    fields = {
        "size_info": "尺寸", "capacity": "容量", "gross_weight_g": "毛重（克）", "body_material": "材质",
        "color": "颜色", "surface_finish": "表面处理", "heat_source": "适用热源", "power": "功率",
        "technical_advantages": "技术优势", "usage_instruction": "使用说明",
        "title_cn": "中文标题", "long_description_cn": "中文商品描述", "listing_cn": "中文商品详情",
    }
    count = 0
    for section, heading in (("specs", "规格与使用"), ("content", "商品描述")):
        document.add_heading(heading, level=1)
        values = profile[section]
        if values.get("updated_at"):
            document.add_paragraph(f'资料更新时间  {values["updated_at"]}')
        for key, label in fields.items():
            if key not in values:
                continue
            value = values[key]
            if isinstance(value, list):
                value = "；".join(
                    " ".join(str(item.get(part) or "").strip() for part in ("label", "value", "unit")).strip()
                    if isinstance(item, dict) else str(item)
                    for item in value
                )
            elif isinstance(value, dict):
                value = "；".join(f"{k}：{v}" for k, v in value.items())
            paragraph = document.add_paragraph()
            paragraph.add_run(label + "  ").bold = True
            paragraph.add_run(str(value) if value not in (None, "") else "未填写")
            count += 1
    output = BytesIO()
    document.save(output)
    return profile["sku"], count, output.getvalue()


def set_product_link(
    db: Session, *, url: str, sku: str, enabled: bool, user_id: str, request: Request,
    snapshot_text: str | None = None,
) -> dict:
    identity = marketplace_item(url)
    if identity is None:
        raise HTTPException(status_code=422, detail="请填写支持的平台商品详情页长链接")
    platform, item_id = identity
    product = _active_product(db, sku, lock=True)
    key = (platform, item_id, product.id)
    existing = db.get(CustomerProductLink, key)
    changed = enabled != (existing is not None)
    snapshot_changed = enabled and snapshot_text is not None and (
        existing is None or snapshot_text != existing.snapshot_text
    )
    if changed:
        if existing is None:
            existing = CustomerProductLink(platform=platform, item_id=item_id, product_id=product.id)
            db.add(existing)
        else:
            db.delete(existing)
    if snapshot_changed:
        existing.snapshot_text = snapshot_text or None
        existing.snapshot_at = datetime.now(timezone.utc) if snapshot_text else None
    if changed or snapshot_changed:
        operation_log_service.log_operation(
            db, operator_id=user_id, action_type="update", action_name="维护客服商品链接映射",
            target_type="product", target_id=product.id, target_name=product.sku,
            request_data={"platform": platform, "item_id": item_id, "enabled": enabled,
                          "snapshot_changed": snapshot_changed},
            request=request, commit=False,
        )
    db.commit()
    return {"platform": platform, "item_id": item_id, "sku": product.sku, "enabled": enabled,
            "changed": changed or snapshot_changed}


def search_listing_evidence(db: Session, sku: str, query: str, limit: int) -> dict:
    product = _active_product(db, sku)
    rows = db.query(CustomerProductLink).filter(
        CustomerProductLink.product_id == product.id, CustomerProductLink.snapshot_text.isnot(None),
    ).order_by(CustomerProductLink.snapshot_at.desc()).limit(30).all()
    terms = set(re.findall(r"[A-Za-z0-9]+", query.casefold()))
    for part in re.findall(r"[\u4e00-\u9fff]+", query):
        terms.update(part[i:i + 2] for i in range(len(part) - 1))
    items = []
    for row in rows:
        lines = [line.strip() for line in row.snapshot_text.splitlines() if line.strip()]
        ranked = sorted(lines, key=lambda line: -sum(term in line.casefold() for term in terms))
        excerpt = "\n".join(ranked[:4])[:1200]
        if excerpt:
            items.append({
                "source_type": "marketplace_listing_snapshot", "sku": product.sku,
                "url": customer_listing_source.listing_url(row.platform, row.item_id),
                "saved_at": row.snapshot_at.isoformat() if row.snapshot_at else None,
                "excerpt": excerpt,
            })
    items.sort(key=lambda row: -sum(term in row["excerpt"].casefold() for term in terms))
    return {"sku": product.sku, "status": "matches" if items else "no_snapshot", "items": items[:limit]}


def _qa_receipt(qa: ProductQa, sku: str, status: str) -> dict:
    qa_id = str(qa.id)
    return {"status": status, "sku": sku, "qa_id": qa_id, "integrity_status": qa.integrity_status,
            "review_path": "/products/qa/new?" + urlencode({"sku": sku, "qa_id": qa_id})}


def _qa_revision_base(qa: ProductQa) -> str:
    contents = json.dumps([qa.question, qa.answer, qa.integrity_status], ensure_ascii=False)
    return hashlib.sha256(contents.encode("utf-8")).hexdigest()


def _lock_product_qa(db: Session, product: Product, qa_id: str) -> ProductQa | None:
    return db.query(ProductQa).filter(
        ProductQa.id == qa_id, ProductQa.product_id == product.id,
    ).populate_existing().with_for_update().one_or_none()


def propose_qa_revision(
    db: Session, *, user_id: str, sku: str, qa_id: str, answer: str, reason: str | None, request: Request,
) -> dict:
    if _PERSONAL_DATA.search(answer) or (reason and _PERSONAL_DATA.search(reason)):
        raise HTTPException(status_code=422, detail="请删除个人信息、订单信息或链接后再提交修订。")
    product = _active_product(db, sku)
    original = _lock_product_qa(db, product, qa_id)
    if original is None or original.integrity_status != "approved" or original.revision_of_qa_id is not None:
        raise HTTPException(status_code=404, detail="找不到该 SKU 下可修订的已审核问答")
    if original.answer.strip() == answer:
        raise HTTPException(status_code=422, detail="新答案与原答案相同")
    base_hash = _qa_revision_base(original)
    revision = db.query(ProductQa).filter(
        ProductQa.product_id == product.id,
        ProductQa.revision_of_qa_id == str(original.id),
        ProductQa.revision_base_hash == base_hash,
        ProductQa.integrity_status == QA_REVISION_STATUS,
        ProductQa.answer == answer,
    ).first()
    if revision is not None:
        return {**_qa_receipt(revision, product.sku, "existing"), "target_qa_id": str(original.id)}

    revision = ProductQa(
        product_id=product.id, question=original.question, answer=answer,
        revision_of_qa_id=str(original.id), revision_base_hash=base_hash,
        integrity_status=QA_REVISION_STATUS, integrity_reason=reason,
    )
    db.add(revision)
    db.flush()
    operation_log_service.log_operation(
        db, operator_id=user_id, action_type="create", action_name="客服 MCP 提交 QA 修订",
        target_type="product_qa", target_id=str(original.id), target_name=product.sku,
        request_data={"revision_id": str(revision.id), "reason": reason},
        request=request, commit=False,
    )
    receipt = {**_qa_receipt(revision, product.sku, "saved"), "target_qa_id": str(original.id)}
    db.commit()
    return receipt


async def review_qa_revision(
    db: Session, *, product: Product, revision_id: str, data: dict, user: User, request: Request,
) -> tuple[ProductQa, dict]:
    revision = _lock_product_qa(db, product, revision_id)
    if revision is None or not revision.revision_of_qa_id:
        raise HTTPException(status_code=404, detail="这条 QA 修订已处理或不存在")
    original = _lock_product_qa(db, product, revision.revision_of_qa_id)
    if original is None or _qa_revision_base(original) != revision.revision_base_hash:
        raise HTTPException(status_code=409, detail="原 QA 已被修改或删除，请核对当前版本后重新发起修订")
    answer = data.get("answer", revision.answer)
    if (not isinstance(answer, str) or not answer.strip() or len(answer) > 4000
            or _PERSONAL_DATA.search(answer)):
        raise HTTPException(status_code=422, detail="请填写不含个人信息、订单信息或链接的答案，最多 4000 字")
    revision.answer = answer.strip()
    revision.question = original.question
    verdict = await product_qa_integrity_service.audit_product_qa_item(db, product, revision, user=user)
    if verdict["status"] != "approved":
        if revision.integrity_status == "review":
            revision.integrity_status = QA_REVISION_STATUS
        db.commit()
        db.refresh(revision)
        return revision, verdict

    previous_answer = original.answer
    for field in ("answer", "integrity_status", "integrity_reason", "integrity_model", "integrity_audited_at"):
        setattr(original, field, getattr(revision, field))
    operation_log_service.log_operation(
        db, operator_id=user.id, action_type="update", action_name="审核并采用 QA 修订",
        target_type="product_qa", target_id=str(original.id), target_name=product.sku,
        request_data={"revision_id": str(revision.id), "previous_answer": previous_answer, "answer": original.answer},
        response_data={"integrity_audit": verdict}, request=request, commit=False,
    )
    db.delete(revision)
    db.commit()
    db.refresh(original)
    return original, verdict


def export_product_qa(db: Session, sku: str, *, include_unapproved: bool) -> tuple[str, int, bytes]:
    from docx import Document
    from docx.oxml.ns import qn
    from docx.shared import Pt, RGBColor

    product = _active_product(db, sku)
    if include_unapproved:
        rows = sorted(
            product_service.get_qa_items(db, product.sku),
            key=lambda qa: (qa.priority is not None, qa.priority or 0, str(qa.updated_at or ""), str(qa.id)),
            reverse=True,
        )
    else:
        rows = product_service.customer_visible_product_qas(db, product.id)

    document = Document()
    for style_name in ("Normal", "Title", "Heading 1"):
        style = document.styles[style_name]
        style.font.name = "Microsoft YaHei"
        style.font.color.rgb = RGBColor(0, 0, 0)
        style.element.get_or_add_rPr().rFonts.set(qn("w:eastAsia"), "Microsoft YaHei")
    document.styles["Normal"].font.size = Pt(11)
    document.styles["Heading 1"].font.size = Pt(12)
    title = document.styles["Title"]
    for border in title.element.xpath(".//w:pBdr"):
        border.getparent().remove(border)

    document.add_paragraph("商品客服问答", style="Title")
    document.add_paragraph(f"{product.sku}  {product.product_name_cn or ''}".rstrip())
    scope = "全部审核状态" if include_unapproved else "已审核"
    document.add_paragraph(f"{scope} · 共 {len(rows)} 条")
    status_labels = {"approved": "已审核", "review": "待审核", "rejected": "未通过", QA_REVISION_STATUS: "待审核修订"}
    for index, qa in enumerate(rows, 1):
        heading = f"第 {index} 条"
        if include_unapproved:
            heading += "  " + status_labels.get(qa.integrity_status, qa.integrity_status or "未标注")
        document.add_heading(heading, level=1)
        question = document.add_paragraph()
        question.paragraph_format.keep_with_next = True
        question.add_run("问  ").bold = True
        question.add_run(qa.question)
        answer = document.add_paragraph()
        answer.add_run("答  ").bold = True
        answer.add_run(qa.answer)
    output = BytesIO()
    document.save(output)
    return product.sku, len(rows), output.getvalue()


async def search_approved_qa(db: Session, sku: str, query: str, limit: int) -> dict:
    product = _active_product(db, sku)
    approved = product_service.customer_visible_product_qas(db, product.id)
    by_id = {str(qa.id): qa for qa in approved}
    normalized_query = _qa_text_key(query)
    ranked_ids = [qa_id for qa_id, qa in by_id.items() if normalized_query and _qa_text_key(qa.question) == normalized_query]
    if by_id and len(ranked_ids) < limit:
        retrieval_query = re.sub(r"燃气软管|燃气管", "气管", query)
        if re.search(r"炉|气罐|罐子", query):
            retrieval_query = retrieval_query.replace("软管", "气管")
        rows = await knowledge_service.semantic_retrieve(
            db, retrieval_query, sku=product.sku, limit=limit * 2, sections=["qa"], source_types=["product"],
        )
        prefix = f"product:{product.sku}:qa:"
        for row in rows:
            source_id = str((row.get("metadata") or {}).get("source_id") or "")
            if not source_id.startswith(prefix):
                continue
            qa_id = source_id[len(prefix):]
            if qa_id in by_id and qa_id not in ranked_ids:
                ranked_ids.append(qa_id)
    items = [
        {"qa_id": qa_id, "question": by_id[qa_id].question, "answer": by_id[qa_id].answer,
         "match": "exact" if _qa_text_key(by_id[qa_id].question) == normalized_query else "candidate"}
        for qa_id in ranked_ids[:limit]
    ]
    return {"sku": product.sku, "product_name": product.product_name_cn,
            "status": "matches" if items else "no_match", "items": items}


def save_qa_draft(
    db: Session, *, user_id: str, sku: str, question: str, answer: str,
    message_id: str | None, request: Request,
) -> dict:
    if _PERSONAL_DATA.search(question) or _PERSONAL_DATA.search(answer):
        raise HTTPException(status_code=422, detail="请先删除个人信息、订单信息或链接，仅保留可复用的问答。")
    normalized_question = _qa_text_key(question)
    if not _normalized(question) or not _normalized(answer):
        raise HTTPException(status_code=422, detail="问题和答案须包含有效内容")
    product = _active_product(db, sku, lock=True)
    if message_id:
        message = db.query(CustomerServiceMessage).join(
            CustomerServiceConversation,
            CustomerServiceConversation.id == CustomerServiceMessage.conversation_id,
        ).filter(
            CustomerServiceMessage.id == message_id,
            CustomerServiceMessage.role == "assistant",
            CustomerServiceConversation.user_id == str(user_id),
        ).one_or_none()
        if message is None:
            raise HTTPException(status_code=404, detail="找不到本人会话中的这条答复")
        if message.sku and message.sku.upper() != product.sku.upper():
            raise HTTPException(status_code=409, detail="这条会话答复的商品与拟保存的 SKU 不一致")

    same_question = [
        qa for qa in db.query(ProductQa).filter(
            ProductQa.product_id == product.id, ProductQa.revision_of_qa_id.is_(None),
        )
        if _qa_text_key(qa.question) == normalized_question
    ]
    for existing in same_question:
        if _qa_text_key(existing.answer) == _qa_text_key(answer):
            return _qa_receipt(existing, product.sku, "existing")
    if same_question:
        raise HTTPException(status_code=409, detail={
            "message": "同一 SKU 已有相同问题，请在产品 QA 中核对已有答案。",
            "qa_ids": [str(qa.id) for qa in same_question],
        })

    qa = ProductQa(
        product_id=product.id, question=question, answer=answer, integrity_status="review",
        integrity_reason="客服 MCP 收录，等待在产品 QA 中核对后提交审核",
    )
    db.add(qa)
    db.flush()
    operation_log_service.log_operation(
        db, operator_id=user_id, action_type="create", action_name="客服 MCP 保存产品 QA",
        target_type="product_qa", target_id=qa.id, target_name=product.sku,
        request_data={"channel": "customer_service_mcp", "message_id": message_id},
        response_data={"integrity_status": "review"}, request=request, commit=False,
    )
    db.commit()
    product_service.invalidate_product_detail_cache(db, product.sku)
    return _qa_receipt(qa, product.sku, "saved")
