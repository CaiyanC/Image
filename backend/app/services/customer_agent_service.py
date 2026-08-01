import json
import re
import unicodedata
from typing import Any

from sqlalchemy import String, cast, or_
from sqlalchemy.orm import Session

from ..models.product import Product
from ..models.product_business import ProductBusiness
from ..models.product_content import ProductContent
from ..models.product_specs import ProductSpecs
from . import agent_action_service, product_service


PRODUCT_COLOR_TERMS = ("黑色", "白色", "蓝色", "绿色", "粉色", "红色", "灰色", "银色", "金色")


SKU_RE = re.compile(
    r"(?<![A-Za-z0-9])("
    r"(?:[A-Za-z]{1,6}[A-Za-z0-9]{0,12}(?:[-_](?:[A-Za-z0-9]{1,24}(?:\([A-Za-z0-9]{1,24}\))?|[\u4e00-\u9fff]{1,8}))+)"
    r"|(?:[A-Za-z]{1,6}\d{2,12}[A-Za-z0-9\u4e00-\u9fff]{0,12})"
    r")(?=$|[\s，。,；;：:）)\]】>\"'？?])"
)
SKU_PREFIX_RE = re.compile(
    r"(?<![A-Za-z0-9])(?:[A-Za-z]{1,6}[A-Za-z0-9]{0,12}(?:[-_](?:[A-Za-z0-9]{1,24}(?:\([A-Za-z0-9]{1,24}\))?|[\u4e00-\u9fff]{1,2}))+)"
)
PLAIN_SKU_PREFIX_RE = re.compile(
    r"(?<![A-Za-z0-9_-])(?:[A-Za-z]{1,6}\d{2,12}[A-Za-z0-9]{0,12}(?:\([A-Za-z0-9]{1,24}\))?)"
)
SKU_TAIL_TRIM_PATTERNS = (
    re.compile(r"^([A-Z]{1,6}[A-Z0-9]{0,12}(?:-[A-Z0-9]{1,24})+[（(][A-Z0-9]{1,24}[)）])[\u4e00-\u9fff].*$"),
    re.compile(r"^([A-Z]{1,6}[A-Z0-9]{0,12}(?:-[A-Z0-9]{1,24})+-[\u4e00-\u9fff]{1,2})[\u4e00-\u9fff].*$"),
    re.compile(r"^([A-Z]{1,6}[A-Z0-9]{0,12}(?:-[A-Z0-9]{1,24})+)[\u4e00-\u9fff].*$"),
    re.compile(r"^([A-Z]{1,6}\d{2,12}[A-Z0-9]{0,12}(?:[（(][A-Z0-9]{1,24}[)）])?)[\u4e00-\u9fff].*$"),
)


def _trim_sku_tail_candidate(candidate: str) -> str:
    value = str(candidate or "").strip().replace("_", "-").upper()
    if not value:
        return ""
    # Chinese possessive “的” is grammar following a SKU (for example
    # ``KW-K32-黑的容量``), never part of the canonical catalogue identity.
    # Remove only that terminal grammatical tail before matching variants.
    possessive = chr(0x7684)
    if value.endswith(possessive):
        value = value[:-1]
    for pattern in SKU_TAIL_TRIM_PATTERNS:
        match = pattern.match(value)
        if match:
            value = str(match.group(1) or "").strip()
            break
    # A greedy Chinese suffix can include the possessive before the trailing
    # question phrase (for example ``...-黑的容量``).  Strip grammatical
    # possessives after structural trimming as well; they are never part of a
    # canonical SKU.
    while value.endswith(possessive):
        value = value[:-1]
    return value


def _extract_sku_prefix_candidates(text: str) -> list[str]:
    normalized_text = normalize_search_text(text or "")
    candidates: list[str] = []
    for pattern in (SKU_PREFIX_RE, PLAIN_SKU_PREFIX_RE):
        for match in pattern.finditer(normalized_text):
            candidate = _trim_sku_tail_candidate(str(match.group(0) or ""))
            if candidate and candidate not in candidates:
                candidates.append(candidate)
    return candidates


def normalize_search_text(value: Any) -> str:
    text = unicodedata.normalize("NFKC", str(value or ""))
    replacements = {
        "‐": "-",
        "‑": "-",
        "‒": "-",
        "–": "-",
        "—": "-",
        "―": "-",
        "－": "-",
        "（": "(",
        "）": ")",
        "【": "[",
        "】": "]",
        "　": " ",
    }
    for source, target in replacements.items():
        text = text.replace(source, target)
    return re.sub(r"\s+", " ", text).strip()


def looks_like_contents_accessories_question(value: Any) -> bool:
    text = normalize_search_text(value or "")
    if not text:
        return False
    lower_text = text.lower()
    direct_terms = (
        "原厂配了什么",
        "原厂带什么",
        "出厂带什么",
        "默认带哪些",
        "默认配什么",
        "盒子里有什么",
        "箱子里有什么",
        "包装盒里有什么",
        "到手里面有什么",
        "随箱带什么",
        "全套含什么",
        "标准配置是什么",
        "有没有附件",
        "有没有随箱配件",
        "买回来里面有什么",
        "收到货里面有什么",
        "what comes in the box",
        "what does it come with",
        "factory included items",
        "default accessories",
        "box contents",
        "in-box accessories",
    )
    if any(term in text for term in direct_terms):
        return True
    return any(term in lower_text for term in direct_terms if term.isascii())


def product_name_aliases(value: Any) -> list[str]:
    text = normalize_search_text(value or "")
    if not text:
        return []

    candidates = [text]
    without_brackets = re.sub(r"\s*[\(\（][^\)\）]+[\)\）]\s*", "", text).strip()
    if without_brackets:
        candidates.append(without_brackets)

    index = 0
    while index < len(candidates):
        candidate = candidates[index]
        index += 1
        compact_connector_variant = re.sub(r"[\s\-_]+", "", candidate).strip()
        if compact_connector_variant and compact_connector_variant != candidate:
            candidates.append(compact_connector_variant)
        hyphen_match = re.match(r"^(?P<prefix>.+?)[-—–－](?P<suffix>[^-—–－（）()]+)$", candidate)
        if hyphen_match:
            suffix = str(hyphen_match.group("suffix") or "").strip()
            prefix = str(hyphen_match.group("prefix") or "").strip()
            if (
                prefix
                and suffix
                and len(suffix) <= 4
                and not re.search(r"\d", suffix)
                and (
                    re.search(r"\d", prefix)
                    or suffix.lower() in {"pro", "max"}
                    or suffix in PRODUCT_COLOR_TERMS
                )
            ):
                candidates.append(prefix)
        cup_count_trimmed = re.sub(r"\d+\s*杯$", "", candidate).strip()
        if cup_count_trimmed and cup_count_trimmed != candidate:
            candidates.append(cup_count_trimmed)

    aliases: list[str] = []
    seen: set[str] = set()
    for candidate in candidates:
        normalized = normalize_search_text(candidate)
        if len(normalized) < 2:
            continue
        lowered = normalized.lower()
        if lowered in seen:
            continue
        seen.add(lowered)
        aliases.append(normalized)
    aliases.sort(key=len, reverse=True)
    return aliases


VERSION_TOKENS = ("pro", "plus", "max", "lite", "mini", "ultra")
VERSION_SUFFIX_RE = re.compile(r"(?:pro|plus|max|lite|mini|ultra)$", re.I)
VARIANT_SUFFIX_RE = re.compile(
    r"(?:pro|plus|max|lite|mini|ultra|基础款|标准版|升级款|入门款|高配版|低配版)$",
    re.I,
)


def product_name_family_aliases(value: Any) -> list[str]:
    aliases = product_name_aliases(value)
    family_aliases: list[str] = []
    seen = {alias.lower() for alias in aliases}
    for alias in aliases:
        stripped = VARIANT_SUFFIX_RE.sub("", alias).strip(" -_()（）")
        stripped = re.sub(r"(?:饭盒|水壶|保温杯|套锅|单锅|炒锅|煎锅|烤盘|茶具|炉|炉具)$", "", stripped).strip(" -_()（）")
        if len(stripped) >= 2 and stripped.lower() not in seen:
            family_aliases.append(stripped)
            seen.add(stripped.lower())
    family_aliases.sort(key=len, reverse=True)
    return family_aliases


def product_name_version_tokens(value: Any) -> set[str]:
    text = normalize_search_text(value or "").lower()
    return {token for token in VERSION_TOKENS if token in text}


def resolve_named_product_candidates(question: str, products: list[Product], *, subject: str | None = None) -> list[Product]:
    normalized_question = normalize_search_text(question or "").lower()
    normalized_subject = normalize_search_text(subject or question or "").lower()
    subject_versions = product_name_version_tokens(normalized_subject)
    matches: list[tuple[int, int, Product, dict[str, bool]]] = []

    for product in products:
        names = [getattr(product, "product_name_cn", "") or "", getattr(product, "product_name_en", "") or ""]
        strong_exact = False
        strong_contains = False
        family_exact = False
        family_contains = False
        fuzzy_contains = False
        subject_exact_alias = False
        subject_family_alias = False
        subject_in_name = False
        best_len = 0
        product_versions = set()

        for name in names:
            if not str(name).strip():
                continue
            strong_aliases = product_name_aliases(name)
            family_aliases = product_name_family_aliases(name)
            product_versions.update(product_name_version_tokens(name))
            for alias in strong_aliases:
                alias_lower = alias.lower()
                if normalized_subject and alias_lower == normalized_subject:
                    subject_exact_alias = True
                if subject_versions and not (subject_versions & product_versions) and alias_lower != normalized_subject:
                    continue
                if alias_lower == normalized_subject:
                    strong_exact = True
                    best_len = max(best_len, len(alias_lower))
                elif alias_lower and (alias_lower in normalized_subject or alias_lower in normalized_question):
                    strong_contains = True
                    best_len = max(best_len, len(alias_lower))
            for alias in family_aliases:
                alias_lower = alias.lower()
                if normalized_subject and alias_lower == normalized_subject:
                    subject_family_alias = True
                if alias_lower == normalized_subject:
                    family_exact = True
                    best_len = max(best_len, len(alias_lower))
                elif alias_lower and (alias_lower in normalized_subject or alias_lower in normalized_question):
                    family_contains = True
                    best_len = max(best_len, len(alias_lower))
            normalized_name = normalize_search_text(name).lower()
            if normalized_subject and normalized_subject in normalized_name:
                subject_in_name = True
            if normalized_subject and normalized_subject in normalized_name:
                fuzzy_contains = True
                best_len = max(best_len, len(normalized_subject))

        score = 0
        if strong_exact:
            score = 400 + best_len
        elif strong_contains:
            score = 300 + best_len
        elif family_exact:
            score = 200 + best_len
        elif family_contains:
            score = 100 + best_len
        elif fuzzy_contains:
            score = 50 + best_len
        if score > 0:
            matches.append(
                (
                    score,
                    best_len,
                    product,
                    {
                        "strong_exact": strong_exact,
                        "strong_contains": strong_contains,
                        "family_exact": family_exact,
                        "family_contains": family_contains,
                        "fuzzy_contains": fuzzy_contains,
                        "subject_exact_alias": subject_exact_alias,
                        "subject_family_alias": subject_family_alias,
                        "subject_in_name": subject_in_name,
                    },
                )
            )

    if not matches:
        return []

    matches.sort(key=lambda item: (-item[0], -item[1], len(str(getattr(item[2], "product_name_cn", "") or "")), str(getattr(item[2], "sku", "") or "")))

    if subject_versions:
        top_score = matches[0][0]
        top = [item[2] for item in matches if item[0] == top_score]
        return top[:5]

    family_ambiguous = [
        item[2]
        for item in matches
        if item[3]["subject_exact_alias"] or item[3]["subject_family_alias"] or item[3]["subject_in_name"]
    ]
    if normalized_subject and len(family_ambiguous) > 1:
        deduped_family_ambiguous: list[Product] = []
        seen_skus: set[str] = set()
        for product in family_ambiguous:
            sku = str(getattr(product, "sku", "") or "").strip().upper()
            if not sku or sku in seen_skus:
                continue
            deduped_family_ambiguous.append(product)
            seen_skus.add(sku)
        if len(deduped_family_ambiguous) > 1:
            return deduped_family_ambiguous[:5]

    exactish = [item[2] for item in matches if item[3]["strong_exact"] or item[3]["family_exact"]]
    if len(exactish) > 1:
        return exactish[:5]

    strongish = [item[2] for item in matches if item[3]["strong_exact"] or item[3]["strong_contains"]]
    if len(strongish) == 1:
        return strongish
    if len(strongish) > 1:
        return strongish[:5]

    top_score = matches[0][0]
    top = [item[2] for item in matches if item[0] == top_score]
    return top[:5]

QUERY_FIELD_ALIASES = {
    **agent_action_service.FIELD_ALIASES,
    "SKU": "product.sku",
    "sku": "product.sku",
    "条形码": "product.barcode",
    "编码": "product.barcode",
    "中文名": "product.product_name_cn",
    "中文名称": "product.product_name_cn",
    "英文名": "product.product_name_en",
    "英文名称": "product.product_name_en",
    "子类目": "product.sub_category",
    "商品分级": "product.product_level",
    "状态备注": "product.status_note",
    "品质": "product.quality_note",
    "品质情况": "product.quality_note",
    "坏损": "product.quality_note",
    "尺寸": "specs.size_info",
    "规格": "specs.size_info",
    "适用热源": "specs.heat_source",
    "目标用户": "business.target_audience",
    "场景": "business.usage_scenarios",
    "英文描述": "content.long_description_en",
    "中文描述": "content.long_description_cn",
    "日文描述": "content.long_description_ja",
    "亚马逊标题": "content.amazon_title",
    "网站标题": "content.website_title",
    "五点描述": "content.bullet_points",
    "A+内容": "content.a_plus_content",
    "中文listing": "content.listing_cn",
    "英文listing": "content.listing_en",
    "日文listing": "content.listing_ja",
}

QUERY_FIELD_SPECS = {
    "product.sku": ("product", "sku", "SKU", Product.sku),
    "product.barcode": ("product", "barcode", "条形码", Product.barcode),
    "product.product_name_cn": ("product", "product_name_cn", "中文名称", Product.product_name_cn),
    "product.product_name_en": ("product", "product_name_en", "英文名称", Product.product_name_en),
    "product.brand": ("product", "brand", "品牌", Product.brand),
    "product.series": ("product", "series", "系列", Product.series),
    "product.category": ("product", "category", "类目", Product.category),
    "product.sub_category": ("product", "sub_category", "子类目", Product.sub_category),
    "product.product_level": ("product", "product_level", "等级", Product.product_level),
    "product.lifecycle_status": ("product", "lifecycle_status", "生命周期", Product.lifecycle_status),
    "product.person_in_charge": ("product", "person_in_charge", "负责人", Product.person_in_charge),
    "product.quality_note": ("product", "quality_note", "品质情况", Product.quality_note),
    "product.status_note": ("product", "status_note", "备注", Product.status_note),
    "specs.size_info": ("specs", "size_info", "尺寸规格", ProductSpecs.size_info),
    "specs.capacity": ("specs", "capacity", "容量", ProductSpecs.capacity),
    "specs.gross_weight_g": ("specs", "gross_weight_g", "重量", ProductSpecs.gross_weight_g),
    "specs.body_material": ("specs", "body_material", "材质", ProductSpecs.body_material),
    "specs.color": ("specs", "color", "颜色", ProductSpecs.color),
    "specs.surface_finish": ("specs", "surface_finish", "表面工艺", ProductSpecs.surface_finish),
    "specs.heat_source": ("specs", "heat_source", "热源", ProductSpecs.heat_source),
    "specs.power": ("specs", "power", "功率", ProductSpecs.power),
    "specs.technical_advantages": ("specs", "technical_advantages", "技术优势", ProductSpecs.technical_advantages),
    "specs.usage_instruction": ("specs", "usage_instruction", "使用说明", ProductSpecs.usage_instruction),
    "business.top_selling_points": ("business", "top_selling_points", "卖点", ProductBusiness.top_selling_points),
    "business.target_audience": ("business", "target_audience", "目标人群", ProductBusiness.target_audience),
    "business.positioning": ("business", "positioning", "定位", ProductBusiness.positioning),
    "business.price_positioning": ("business", "price_positioning", "价格定位", ProductBusiness.price_positioning),
    "business.emotional_value": ("business", "emotional_value", "情绪价值", ProductBusiness.emotional_value),
    "business.usage_scenarios": ("business", "usage_scenarios", "使用场景", ProductBusiness.usage_scenarios),
    "business.competitor_benchmark": ("business", "competitor_benchmark", "竞品信息", ProductBusiness.competitor_benchmark),
    "content.title_en": ("content", "title_en", "英文标题", ProductContent.title_en),
    "content.title_cn": ("content", "title_cn", "中文标题", ProductContent.title_cn),
    "content.long_description_en": ("content", "long_description_en", "英文描述", ProductContent.long_description_en),
    "content.long_description_cn": ("content", "long_description_cn", "中文描述", ProductContent.long_description_cn),
    "content.long_description_ja": ("content", "long_description_ja", "日文描述", ProductContent.long_description_ja),
    "content.search_keywords": ("content", "search_keywords", "关键词", ProductContent.search_keywords),
    "content.amazon_title": ("content", "amazon_title", "亚马逊标题", ProductContent.amazon_title),
    "content.website_title": ("content", "website_title", "网站标题", ProductContent.website_title),
    "content.bullet_points": ("content", "bullet_points", "五点描述", ProductContent.bullet_points),
    "content.a_plus_content": ("content", "a_plus_content", "A+内容", ProductContent.a_plus_content),
    "content.listing_cn": ("content", "listing_cn", "中文listing", ProductContent.listing_cn),
    "content.listing_en": ("content", "listing_en", "英文listing", ProductContent.listing_en),
    "content.listing_ja": ("content", "listing_ja", "日文listing", ProductContent.listing_ja),
}

QUERY_FIELD_ALIASES.update(
    {
        "主体材质": "specs.body_material",
        "壶身材质": "specs.body_material",
        "锅身材质": "specs.body_material",
        "适用热源": "specs.heat_source",
        "热源": "specs.heat_source",
        "能用什么炉": "specs.heat_source",
        "是否支持": "specs.heat_source",
        "适用场景": "business.usage_scenarios",
        "使用场景": "business.usage_scenarios",
        "场景": "business.usage_scenarios",
        "用途": "business.usage_scenarios",
    }
)


def process_agent_request(
    db: Session,
    *,
    user_id: str,
    question: str,
    sku: str | None = None,
) -> dict | None:
    clean = re.sub(r"\s+", " ", question.strip())
    if not clean:
        return None

    update_result = _try_create_update_actions(db, user_id, clean, sku)
    if update_result:
        return update_result

    clear_result = _try_create_clear_actions(db, user_id, clean, sku)
    if clear_result:
        return clear_result

    delete_result = _try_create_delete_product_action(db, user_id, clean, sku)
    if delete_result:
        return delete_result

    barcode_result = _try_get_product_by_barcode(db, clean)
    if barcode_result:
        return barcode_result

    detail_result = _try_get_field_answer(db, clean, sku)
    if detail_result:
        return detail_result

    # A sealed explicit identity plus a requested detail field is not a
    # catalogue filter.  Resolve it before collection filtering so words such
    # as "容量" cannot turn a single-SKU request into a product list.
    filter_result = _try_filter_products(db, clean)
    if filter_result:
        return filter_result

    collection_field_result = _try_collection_field_answer(db, clean)
    if collection_field_result:
        return collection_field_result

    search_result = _try_search_products(db, clean)
    if search_result:
        return search_result

    return None


def try_numeric_english_name_query(db: Session, question: str) -> dict | None:
    clean = re.sub(r"\s+", " ", question.strip())
    lower = clean.lower()
    if not any(item in clean for item in ("英文名", "英文名称", "商品英文名称")) and "english" not in lower:
        return None
    if not any(item in clean for item in ("数字", "纯数字", "全数字")) and not any(item in lower for item in ("number", "numeric", "digits")):
        return None
    if not any(item in clean for item in ("产品", "商品", "哪些", "有")):
        return None

    rows = _products_with_numeric_english_names(db, limit=50)
    if not rows:
        answer = "没有找到英文名称为纯数字的产品。"
    else:
        lines = [f"找到 {len(rows)} 个英文名称为纯数字的产品："]
        for index, item in enumerate(rows[:20], start=1):
            name = item.get("product_name_en") or ""
            cn_name = item.get("product_name_cn") or ""
            lines.append(f"{index}. {item['sku']}：{name}" + (f"（{cn_name}）" if cn_name else ""))
        if len(rows) > 20:
            lines.append(f"其余 {len(rows) - 20} 个可继续缩小条件查看。")
        answer = "\n".join(lines)
    return {
        "answer": answer,
        "sku": rows[0]["sku"] if len(rows) == 1 else None,
        "sources": [{"type": "product_filter", "label": "英文名称为纯数字", "count": len(rows)}],
        "actions": [],
        "results": rows,
        "steps": [{
            "type": "deterministic_filter",
            "label": "查询英文名称为纯数字的产品",
            "detail": "识别到“数字”是在描述字段格式，不是要搜索字面值“数字”。",
            "ok": True,
        }],
    }


def _products_with_numeric_english_names(db: Session, limit: int = 50) -> list[dict]:
    rows = (
        db.query(Product, ProductSpecs, ProductBusiness, ProductContent)
        .outerjoin(ProductSpecs, ProductSpecs.product_id == Product.id)
        .outerjoin(ProductBusiness, ProductBusiness.product_id == Product.id)
        .outerjoin(ProductContent, ProductContent.product_id == Product.id)
        .filter(Product.product_name_en.isnot(None))
        .all()
    )
    results = []
    for product, specs, business, content in rows:
        english_name = str(product.product_name_en or "").strip()
        if english_name.isdigit():
            results.append(_result_row(product, specs, business, content, "英文名称为纯数字"))
            if len(results) >= limit:
                break
    return results


def _try_create_update_actions(db: Session, user_id: str, question: str, sku: str | None) -> dict | None:
    match = re.search(r"把\s+(.+?)\s*的\s*(.+?)\s*(?:都)?改成\s*(.+)$", question)
    if not match:
        return None
    sku_text, field_label, new_value = match.groups()
    skus = _extract_skus(sku_text) or ([sku] if sku else [])
    field_label = field_label.replace("都", "").strip()
    field_path = agent_action_service.resolve_field_path(field_label)
    if not skus or not field_path:
        return None
    actions = [
        agent_action_service.create_update_field_action(
            db,
            created_by=user_id,
            sku=item,
            field_path=field_path,
            new_value=new_value.strip(),
        )
        for item in skus
    ]
    return _action_response(actions, f"已生成 {len(actions)} 条待确认修改动作。")


def _try_create_clear_actions(db: Session, user_id: str, question: str, sku: str | None) -> dict | None:
    match = re.search(r"清空\s+(.+?)\s*的\s*(.+)$", question)
    if not match:
        return None
    sku_text, field_label = match.groups()
    skus = _extract_skus(sku_text) or ([sku] if sku else [])
    field_path = agent_action_service.resolve_field_path(field_label.strip())
    if not skus or not field_path:
        return None
    actions = [
        agent_action_service.create_clear_field_action(
            db,
            created_by=user_id,
            sku=item,
            field_path=field_path,
        )
        for item in skus
    ]
    return _action_response(actions, f"已生成 {len(actions)} 条待确认清空动作。")


def _try_create_delete_product_action(db: Session, user_id: str, question: str, sku: str | None) -> dict | None:
    if "删除" not in question or "产品" not in question:
        return None
    skus = _extract_skus(question) or ([sku] if sku else [])
    if not skus:
        return None
    actions = [
        agent_action_service.create_delete_product_action(db, created_by=user_id, sku=item)
        for item in skus
    ]
    return _action_response(actions, f"已生成 {len(actions)} 条待确认产品删除动作。")


def _try_get_field_answer(db: Session, question: str, sku: str | None) -> dict | None:
    extracted = _extract_skus(question) or ([sku] if sku else [])
    # Extraction deliberately retains shorter SKU-shaped suffixes for search
    # recall.  A direct detail request must instead arbitrate those candidates
    # against the catalogue: discard only candidates that do not name a real
    # product, and preserve ambiguity if more than one real product remains.
    normalized = list(dict.fromkeys(str(item).strip().upper() for item in extracted if str(item).strip()))
    existing = {
        str(value).strip().upper()
        for (value,) in db.query(Product.sku).filter(Product.sku.in_(normalized)).all()
        if str(value or "").strip()
    }
    skus = [item for item in normalized if item in existing] or normalized
    if len(skus) != 1:
        return None
    field_path = _find_field_path_in_text(question)
    if not field_path:
        return None
    detail = product_service.get_product_detail(db, skus[0])
    value = _value_from_detail(detail, field_path)
    label = agent_action_service.FIELD_SPECS[field_path].label
    answer = f"{skus[0]} 的{label}是：{_stringify(value) if value not in (None, '') else '产品库暂无相关信息'}"
    return {
        "answer": answer,
        "sku": skus[0],
        "sources": [{"type": "product", "label": label, "sku": skus[0]}],
        "actions": [],
        "results": [{
            "sku": skus[0],
            "product_name_cn": detail.get("product_name_cn"),
            "field_label": label,
            "value": value,
        }],
    }


def _try_get_product_by_barcode(db: Session, question: str) -> dict | None:
    if "条形码" not in question and "barcode" not in question.lower():
        return None
    match = re.search(r"(\d{8,20})", question)
    if not match:
        return None
    barcode = match.group(1)
    rows = search_products(db, barcode, limit=10)
    exact_rows = [item for item in rows if str(item.get("barcode") or "") == barcode]
    rows = exact_rows or rows
    if not rows:
        return {
            "answer": f"没有找到条形码为 {barcode} 的产品信息。",
            "sku": None,
            "sources": [{"type": "product_search", "label": "条形码查询", "count": 0, "query": barcode}],
            "actions": [],
            "results": [],
        }
    item = rows[0]
    answer = f"条形码 {barcode} 对应的产品是：{item['sku']}，{item.get('product_name_cn') or item.get('product_name_en') or '未命名'}。"
    return {
        "answer": answer,
        "sku": item["sku"] if len(rows) == 1 else None,
        "sources": [{"type": "product_search", "label": "条形码查询", "count": len(rows), "query": barcode}],
        "actions": [],
        "results": rows,
    }


def _try_collection_field_answer(db: Session, question: str) -> dict | None:
    field_path = _find_field_path_in_text(question)
    if not field_path:
        return None

    subject = None
    patterns = [
        r"所有\s*(.+?)\s*的\s*.+?(?:给我|列出来|是多少|$)",
        r"(.+?)\s*的\s*.+?(?:都给我|给我|列出来)$",
    ]
    for pattern in patterns:
        match = re.search(pattern, question)
        if match:
            subject = _clean_collection_subject(match.group(1))
            break
    if not subject:
        return None

    rows = search_products(db, subject, limit=50)
    if not rows:
        return {
            "answer": f"没有找到与“{subject}”匹配的产品。",
            "sku": None,
            "sources": [{"type": "product_search", "label": "产品查询", "count": 0, "query": subject}],
            "actions": [],
            "results": [],
        }

    label = agent_action_service.FIELD_SPECS[field_path].label
    result_rows = []
    lines = [f"找到 {len(rows)} 个与“{subject}”匹配的产品，{label}如下："]
    for index, item in enumerate(rows[:10], start=1):
        detail = product_service.get_product_detail(db, item["sku"])
        value = _value_from_detail(detail, field_path)
        text = _stringify(value) if value not in (None, "") else "暂无"
        lines.append(f"{index}. {item['sku']}，{item.get('product_name_cn') or ''}，{label}：{text}")
        enriched = dict(item)
        enriched["field_label"] = label
        enriched["value"] = value
        result_rows.append(enriched)
    if len(rows) > 10:
        lines.append(f"共找到 {len(rows)} 条，回答区先展示前 10 条，可继续缩小条件。")

    return {
        "answer": "\n".join(lines),
        "sku": rows[0]["sku"] if len(rows) == 1 else None,
        "sources": [{"type": "product_search", "label": f"{label}查询", "count": len(rows), "query": subject}],
        "actions": [],
        "results": result_rows,
    }


def _try_search_products(db: Session, question: str) -> dict | None:
    if not any(word in question for word in ["哪些", "有哪些", "支持", "适合", "容量"]):
        return None
    term = _extract_search_term(question)
    if not term:
        return None
    rows = search_products(db, term, limit=50)
    summary_items = rows[:10]
    wants_features = any(word in question for word in ["特色", "特点", "卖点", "优势"])
    if not rows:
        answer = f"没有找到与“{term}”匹配的产品。"
    else:
        lines = [f"共找到 {len(rows)} 个产品，先展示前 {len(summary_items)} 个："]
        for index, item in enumerate(summary_items, start=1):
            suffix = f"，特色：{item.get('features')}" if wants_features and item.get("features") else ""
            lines.append(f"{index}. {item['sku']}，{item.get('product_name_cn') or ''}，依据：{item.get('matched_by')}{suffix}")
        answer = "\n".join(lines)
    return {
        "answer": answer,
        "sku": rows[0]["sku"] if len(rows) == 1 else None,
        "sources": [{"type": "product_search", "label": "产品查询", "count": len(rows), "query": term}],
        "actions": [],
        "results": rows,
    }


_FAST_RECOMMENDATION_SEARCH_FIELDS = [
    "product.product_name_cn",
    "product.product_name_en",
    "product.brand",
    "product.series",
    "product.category",
    "product.sub_category",
    "specs.capacity",
    "specs.gross_weight_g",
    "specs.body_material",
    "specs.surface_finish",
    "specs.heat_source",
    "business.top_selling_points",
    "business.target_audience",
    "business.positioning",
    "business.usage_scenarios",
    "content.title_cn",
    "content.listing_cn",
    "content.bullet_points",
]


def _should_use_fast_recommendation_search(raw_term: str, structured_filters: dict[str, Any]) -> bool:
    text = normalize_search_text(raw_term).strip()
    if not text or not structured_filters:
        return False
    if len(text) < 3:
        return False
    if text in {"锅具", "炉具", "水具", "餐具", "杯具", "锅", "炉", "杯", "壶", "包"}:
        return False
    if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9\-]{2,}", text):
        return False
    if any(token in text for token in ("露营", "做饭", "烹饪", "野餐", "便携", "多人", "2人", "两人", "推荐", "适合", "锅", "套锅", "炉")):
        return True
    return len(text) <= 6


def search_products(db: Session, term: str, limit: int = 50, filters: dict[str, Any] | None = None) -> list[dict]:
    structured_filters = _normalize_structured_filters(filters or {})
    raw_term = str(term or "").strip()
    term = normalize_search_text(raw_term)
    expanded_terms = _expand_search_terms(raw_term)
    likes = [f"%{item}%" for item in expanded_terms]
    search_field_paths = list(QUERY_FIELD_SPECS.keys())
    if _should_use_fast_recommendation_search(raw_term, structured_filters):
        search_field_paths = [item for item in _FAST_RECOMMENDATION_SEARCH_FIELDS if item in QUERY_FIELD_SPECS]
    query_filters = []
    for item_like in likes:
        query_filters.extend(
            cast(QUERY_FIELD_SPECS[field_path][3], String).ilike(item_like)
            for field_path in search_field_paths
        )
    query = (
        db.query(Product, ProductSpecs, ProductBusiness, ProductContent)
        .outerjoin(ProductSpecs, ProductSpecs.product_id == Product.id)
        .outerjoin(ProductBusiness, ProductBusiness.product_id == Product.id)
        .outerjoin(ProductContent, ProductContent.product_id == Product.id)
    )
    if query_filters:
        query = query.filter(or_(*query_filters))
    for field_path, value in structured_filters.items():
        spec = QUERY_FIELD_SPECS.get(field_path)
        if spec and value not in (None, ""):
            query = query.filter(cast(spec[3], String).ilike(f"%{normalize_search_text(value)}%"))
    if not query_filters and not structured_filters:
        return []
    rows = query.limit(limit).all()
    exact_rows = [
        row for row in rows
        if _is_exact_product_match(term, row[0]) or _is_exact_product_match_any(expanded_terms, row[0])
    ]
    if exact_rows:
        rows = exact_rows
    rows = _expand_structured_filter_rows(db, rows, structured_filters, limit)
    results = []
    for product, specs, business, content in rows:
        matched_by = _matched_by(term, product, specs, business, content)
        results.append(_result_row(product, specs, business, content, matched_by))
    return results


def _expand_structured_filter_rows(
    db: Session,
    rows: list[tuple],
    structured_filters: dict[str, Any],
    limit: int,
) -> list[tuple]:
    if not structured_filters or len(rows) >= limit:
        return rows
    expandable_fields = {"specs.body_material", "specs.surface_finish", "specs.heat_source"}
    exact_context_fields = {"product.category"}
    if not any(field_path in expandable_fields for field_path in structured_filters):
        return rows
    if any(field_path not in expandable_fields and field_path not in exact_context_fields for field_path in structured_filters):
        return rows
    existing = {getattr(row[0], "id", None) for row in rows if row and row[0] is not None}
    candidates = (
        db.query(Product, ProductSpecs, ProductBusiness, ProductContent)
        .outerjoin(ProductSpecs, ProductSpecs.product_id == Product.id)
        .outerjoin(ProductBusiness, ProductBusiness.product_id == Product.id)
        .outerjoin(ProductContent, ProductContent.product_id == Product.id)
        .limit(200)
        .all()
    )
    expanded = list(rows)
    for row in candidates:
        product = row[0]
        if getattr(product, "id", None) in existing:
            continue
        if _row_matches_structured_filters(row, structured_filters):
            expanded.append(row)
            existing.add(getattr(product, "id", None))
            if len(expanded) >= limit:
                break
    return expanded


def _row_matches_structured_filters(row: tuple, structured_filters: dict[str, Any]) -> bool:
    product, specs, business, content = row
    sections = {
        "product": product,
        "specs": specs,
        "business": business,
        "content": content,
    }
    for field_path, expected in structured_filters.items():
        spec = QUERY_FIELD_SPECS.get(field_path)
        if not spec:
            return False
        section, field, *_ = spec
        source = sections.get(section)
        actual = getattr(source, field, None) if source is not None else None
        if not _structured_filter_value_matches(actual, expected):
            return False
    return True


def _structured_filter_value_matches(actual: Any, expected: Any) -> bool:
    actual_text = normalize_search_text(_stringify(actual)).lower()
    expected_text = normalize_search_text(expected).lower()
    if not actual_text or not expected_text:
        return False
    if expected_text in actual_text:
        return True
    actual_compact = _compact_filter_text(actual_text)
    expected_compact = _compact_filter_text(expected_text)
    if expected_compact and expected_compact in actual_compact:
        return True
    expected_without_suffix = re.sub(r"(工艺|材质|处理|产品)$", "", expected_compact)
    if expected_without_suffix and expected_without_suffix in actual_compact:
        return True
    expected_parts = _filter_match_parts(expected_compact)
    return bool(expected_parts) and all(part in actual_compact for part in expected_parts)


def _compact_filter_text(value: str) -> str:
    return re.sub(r"[\s,，、/\\|;；:：()（）\\[\\]{}\"'`]+", "", normalize_search_text(value).lower())


def _filter_match_parts(value: str) -> list[str]:
    parts = re.findall(r"[a-z]+|\d+|[\u4e00-\u9fff]+", value)
    cleaned = []
    for part in parts:
        item = re.sub(r"(工艺|材质|处理|产品)$", "", part)
        if item and item not in cleaned:
            cleaned.append(item)
    return cleaned


def _normalize_structured_filters(filters: dict[str, Any]) -> dict[str, Any]:
    normalized = {}
    for key, value in filters.items():
        if value in (None, ""):
            continue
        field_path = QUERY_FIELD_ALIASES.get(str(key).strip()) or str(key).strip()
        if field_path in QUERY_FIELD_SPECS:
            normalized[field_path] = normalize_search_text(value)
    return normalized


def _try_filter_products(db: Session, question: str) -> dict | None:
    field_filter = _try_generic_field_filter(db, question)
    if field_filter:
        return field_filter

    lifecycle_match = re.search(r"生命周期(?:为|是)\s*([^，,。 ]+)", question)
    if lifecycle_match:
        value = _clean_filter_value(lifecycle_match.group(1))
        rows = _filter_products_by_product_field(db, "lifecycle_status", value)
        return _filter_response(rows, f"生命周期为“{value}”")

    category_match = re.search(r"(?:哪些产品为|哪些产品是|产品为|产品是)\s*([^，,。 ]+)", question)
    if category_match:
        value = category_match.group(1).strip()
        rows = search_products(db, value, limit=50)
        return _filter_response(rows, f"类目/资料包含“{value}”", wants_features="特色" in question or "特点" in question)

    return None


def _try_generic_field_filter(db: Session, question: str) -> dict | None:
    field_path = None
    field_label = None
    value = None
    for label in sorted(QUERY_FIELD_ALIASES, key=len, reverse=True):
        pattern = rf"{re.escape(label)}\s*(?:为|是|=|等于|包含)\s*([^，,。?？\s]+)"
        match = re.search(pattern, question, flags=re.I)
        if match:
            field_path = QUERY_FIELD_ALIASES[label]
            field_label = label
            value = _clean_filter_value(match.group(1))
            break
    if not field_path or not value:
        return None
    if value in {"多少", "什么", "啥", "几"}:
        return None
    rows = _filter_products_by_field_path(db, field_path, value)
    spec = QUERY_FIELD_SPECS.get(field_path)
    label = spec[2] if spec else field_label
    return _filter_response(rows, f"{label}为“{value}”")


def _filter_products_by_field_path(db: Session, field_path: str, value: str) -> list[dict]:
    spec = QUERY_FIELD_SPECS.get(field_path)
    if not spec:
        return []
    column = spec[3]
    rows = (
        db.query(Product, ProductSpecs, ProductBusiness, ProductContent)
        .outerjoin(ProductSpecs, ProductSpecs.product_id == Product.id)
        .outerjoin(ProductBusiness, ProductBusiness.product_id == Product.id)
        .outerjoin(ProductContent, ProductContent.product_id == Product.id)
        .filter(cast(column, String).ilike(f"%{value}%"))
        .limit(50)
        .all()
    )
    return [_result_row(product, specs, business, content, spec[2]) for product, specs, business, content in rows]


def _filter_products_by_product_field(db: Session, field: str, value: str) -> list[dict]:
    column = getattr(Product, field)
    rows = (
        db.query(Product, ProductSpecs, ProductBusiness, ProductContent)
        .outerjoin(ProductSpecs, ProductSpecs.product_id == Product.id)
        .outerjoin(ProductBusiness, ProductBusiness.product_id == Product.id)
        .outerjoin(ProductContent, ProductContent.product_id == Product.id)
        .filter(column.ilike(f"%{value}%"))
        .limit(50)
        .all()
    )
    return [
        _result_row(product, specs, business, content, "产品基础信息")
        for product, specs, business, content in rows
    ]


def _filter_response(rows: list[dict], label: str, wants_features: bool = False) -> dict:
    if not rows:
        answer = f"没有找到{label}的产品。"
    else:
        lines = [f"找到 {len(rows)} 个{label}的产品："]
        for index, item in enumerate(rows[:10], start=1):
            suffix = f"，特色：{item.get('features')}" if wants_features and item.get("features") else ""
            lines.append(f"{index}. {item['sku']}，{item.get('product_name_cn') or ''}，{item.get('category') or ''}{suffix}")
        answer = "\n".join(lines)
    return {
        "answer": answer,
        "sku": rows[0]["sku"] if len(rows) == 1 else None,
        "sources": [{"type": "product_filter", "label": label, "count": len(rows)}],
        "actions": [],
        "results": rows,
    }


def _result_row(product, specs, business, content, matched_by: str) -> dict:
    return {
        "sku": product.sku,
        "barcode": product.barcode,
        "product_name_cn": product.product_name_cn,
        "product_name_en": product.product_name_en,
        "brand": product.brand,
        "series": product.series,
        "category": product.category,
        "sub_category": product.sub_category,
        "product_level": product.product_level,
        "lifecycle_status": product.lifecycle_status,
        "person_in_charge": product.person_in_charge,
        "quality_note": product.quality_note,
        "status_note": product.status_note,
        "capacity": _stringify(specs.capacity) if specs else None,
        "body_material": specs.body_material if specs else None,
        "color": specs.color if specs else None,
        "surface_finish": specs.surface_finish if specs else None,
        "heat_source": specs.heat_source if specs else None,
        "power": specs.power if specs else None,
        "matched_by": matched_by,
        "features": _first_nonempty([
            getattr(specs, "technical_advantages", None),
            getattr(business, "top_selling_points", None),
            getattr(business, "usage_scenarios", None),
        ]),
        "target_audience": business.target_audience if business else None,
        "positioning": business.positioning if business else None,
        "price_positioning": business.price_positioning if business else None,
        "usage_scenarios": _stringify(business.usage_scenarios) if business else None,
        "emotional_value": business.emotional_value if business else None,
    }


def _action_response(actions, answer: str) -> dict:
    return {
        "answer": answer,
        "sku": actions[0].sku if len(actions) == 1 else None,
        "sources": [{"type": "agent_action", "label": "待确认动作", "count": len(actions)}],
        "actions": [agent_action_service.serialize_action(item) for item in actions],
        "results": [],
    }


def _extract_skus(text: str) -> list[str]:
    seen = []
    normalized_text = normalize_search_text(text or "")
    variants = [
        normalized_text,
        normalized_text.replace("（", "(").replace("）", ")"),
        normalized_text.replace("(", "（").replace(")", "）"),
    ]
    for variant in variants:
        for item in SKU_RE.findall(variant):
            normalized = _trim_sku_tail_candidate(item)
            if normalized not in seen:
                seen.append(normalized)
        for candidate in _extract_sku_prefix_candidates(variant):
            if candidate not in seen:
                seen.append(candidate)
    # SKU_RE also accepts plain compact SKUs for backwards compatibility.  In
    # a longer hyphenated identity, its terminal segment (for example ``G25``
    # in ``CS-G25``) is a parser by-product, not a second entity.  Retain a
    # standalone compact SKU unless a complete extracted SKU explicitly ends
    # in that segment.
    retained = [
        candidate
        for candidate in seen
        if not (
            PLAIN_SKU_PREFIX_RE.fullmatch(candidate)
            and any(
                len(other) > len(candidate)
                and other.endswith(f"-{candidate}")
                for other in seen
            )
        )
    ]
    # The comparison contract consumes this list as the participant order.
    # Regex passes can discover the final greedy match before an earlier prefix,
    # so restore the literal utterance order after canonical normalization.
    return sorted(retained, key=lambda candidate: normalized_text.find(candidate))


def _find_field_path_in_text(text: str) -> str | None:
    for label in sorted(agent_action_service.FIELD_ALIASES, key=len, reverse=True):
        if label in text:
            return agent_action_service.FIELD_ALIASES[label]
    return None


def _extract_search_term(question: str) -> str:
    patterns = [
        r"哪些产品支持(.+)",
        r"哪些产品为(.+?)(?:，|,|。|$)",
        r"哪些产品是(.+?)(?:，|,|。|$)",
        r"(.+?)的有哪些",
        r"(.+?)有哪些",
        r"适合(.+?)的有哪些",
    ]
    for pattern in patterns:
        match = re.search(pattern, question)
        if match:
            return _clean_term(match.group(1))
    return _clean_term(question)


def _clean_term(value: str) -> str:
    value = re.sub(r"(产品|哪些|支持|适合|这些|分别|什么|特色|特点|有|的|吗|？|\?)", "", value)
    return value.strip(" ，,。")


def _clean_collection_subject(value: str) -> str:
    value = re.sub(r"(产品|商品|所有|全部|这些|分别|容量|材质|颜色|重量|给我|列出来)", "", value)
    return value.strip(" ，,。")


def _expand_search_terms(term: str) -> list[str]:
    raw_text = str(term or "").strip()
    text = normalize_search_text(raw_text)
    terms = [raw_text, text]
    for variant in _punctuation_variants(text):
        terms.append(variant)
    compact = re.sub(r"\s+", "", text)
    if compact and compact != text:
        terms.append(compact)
    for match in re.finditer(r"([\u4e00-\u9fa5A-Za-z0-9]{0,8}(?:烤盘|套锅|炒锅|煎锅|单锅|水壶|杯套装|杯|勺|炉|包))", text):
        candidate = re.sub(r"^(?:客户问|客户|问|推荐|适合|有没有|有|给我|我想要|不要)", "", match.group(1)).strip()
        if len(candidate) >= 2:
            terms.append(candidate)
    for token in re.split(r"[\s,，。？?；;、/和与]+", text):
        token = token.strip()
        if len(token) >= 2 and token not in {"客户", "客户问", "哪个", "哪个更好", "怎么回复", "该选哪个"}:
            terms.append(token)
    if re.search(r"\bpro\b", text, flags=re.I):
        terms.extend(["Pro", "pro"])
        without_joiner = re.sub(r"\s*(?:和|与|,|，|/)\s*pro\b", "Pro", text, flags=re.I)
        if without_joiner != text:
            terms.append(without_joiner.strip())
            terms.append(re.sub(r"\s+", "", without_joiner))
    if text and not text.endswith("具"):
        terms.append(f"{text}具")
    if text == "锅":
        terms.extend(["锅具", "套锅", "单锅"])
    if text in {"水", "壶", "水具", "水壶"}:
        terms.extend(["水具", "水壶", "杯", "饮水", "补水"])
    return list(dict.fromkeys([item for item in terms if item]))

    terms = [term]
    if term and not term.endswith("具"):
        terms.append(f"{term}具")
    if term == "锅":
        terms.extend(["锅具", "套锅", "单锅"])
    return list(dict.fromkeys([item for item in terms if item]))


def _punctuation_variants(text: str) -> list[str]:
    variants = []
    if "-" in text:
        variants.append(text.replace("-", "－"))
    if "(" in text or ")" in text:
        variants.append(text.replace("(", "（").replace(")", "）"))
    return variants


def _clean_filter_value(value: str) -> str:
    value = re.split(r"(的(?:产品|商品|锅具|锅|炉具|炉|水具|杯|壶)|有哪些|哪些|给我|我想|想改|改成|，|,|。|？|\?)", value.strip(), maxsplit=1)[0]
    return value.strip()


def _value_from_detail(detail: dict[str, Any], field_path: str) -> Any:
    section, field = field_path.split(".", 1)
    if section == "product":
        return detail.get(field)
    nested = detail.get(section) or {}
    return nested.get(field)


def _matched_by(term: str, product, specs, business, content) -> str:
    holders = {
        "product": product,
        "specs": specs,
        "business": business,
        "content": content,
    }
    for section, field, label, _column in QUERY_FIELD_SPECS.values():
        holder = holders.get(section)
        if holder is not None and term.lower() in str(getattr(holder, field, "") or "").lower():
            return label
    return "产品资料"


def _is_exact_product_match(term: str, product) -> bool:
    normalized = normalize_search_text(term).lower()
    compact = re.sub(r"\s+", "", normalized)
    if not normalized:
        return False
    candidates = [
        product.sku,
        product.barcode,
        product.product_name_cn,
        product.product_name_en,
    ]
    for item in candidates:
        value = normalize_search_text(item).lower()
        if not value:
            continue
        if normalized == value or value in normalized:
            return True
        compact_value = re.sub(r"\s+", "", value)
        if compact_value and compact_value in compact:
            return True
        if "pro" in compact_value and "pro" in compact and compact_value.replace("pro", "") in compact:
            return True
    return False


def _is_exact_product_match_any(terms: list[str], product) -> bool:
    return any(_is_exact_product_match(term, product) for term in terms)


def _first_nonempty(values: list[Any]) -> str:
    for value in values:
        text = _stringify(value)
        if text:
            return text
    return ""


def _stringify(value: Any) -> str:
    if isinstance(value, str):
        text = value.strip()
        if (text.startswith("{") and text.endswith("}")) or (text.startswith("[") and text.endswith("]")):
            try:
                return _stringify(json.loads(text))
            except json.JSONDecodeError:
                return value
        return value
    if isinstance(value, dict):
        label = value.get("label")
        item_value = value.get("value")
        if label not in (None, "") and item_value not in (None, ""):
            label_text = _stringify(label)
            value_text = _stringify(item_value)
            return value_text if label_text == value_text else f"{label_text} {value_text}"
        for key in ["value", "label", "text", "name"]:
            if value.get(key) not in (None, ""):
                return _stringify(value.get(key))
        return "，".join(f"{key}: {_stringify(item)}" for key, item in value.items() if item not in (None, ""))
    if isinstance(value, list):
        return "，".join(_stringify(item) for item in value if item not in (None, ""))
    return str(value)
