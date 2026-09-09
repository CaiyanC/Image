"""Build safe experience cards for every product in the dev catalogue.

The source exports contain many repeated rows across the seven learning
libraries.  This script deliberately reads only the six non-evaluation
libraries, deduplicates rows by ``qaId``, and keeps only records whose SKU was
already strictly mapped to the current product master.

The generated cards are communication guidance, not product evidence.  Each
product receives a broad coverage card and, when the source supports it,
smaller topic cards.  Cards contain aggregate counts and topic labels, never
historical answers, links, prices, or guessed product attributes.  Products
without a confirmed historical sample still receive a visible ``no_history``
card so coverage is explicit rather than silently incomplete.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import re
import sys
import uuid
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.core.config import database_name_from_url, settings  # noqa: E402
from app.core.database import SessionLocal  # noqa: E402
from app.models.knowledge_base import (  # noqa: E402
    CustomerServiceConversation,
    CustomerServiceMessage,
    KnowledgeChunk,
    KnowledgeDocument,
)
from app.models.product import Product  # noqa: E402
from app.models.product_qa import ProductQa  # noqa: E402
from app.services import knowledge_service, product_vector_index_service  # noqa: E402


SOURCE_LIBRARY_PREFIXES = (
    "07_01_",
    "07_02_",
    "07_03_",
    "07_04_",
    "07_05_",
    "07_06_",
)
SOURCE_ID_PREFIX = "customer_experience:catalog:v1:"
CARD_VERSION = "experience-catalog-v2"
MAX_SOURCE_RECORD_IDS = 64
MAX_TOPIC_LABELS = 6
MIN_STRICT_TOPIC_SAMPLES = 3
MIN_INFERRED_TOPIC_SIGNALS = 3
MAX_STRICT_TOPIC_CARDS_PER_PRODUCT = 8
MAX_INFERRED_TOPIC_CARDS_PER_PRODUCT = 2
EXPERIENCE_FALLBACK_TOPIC = "其他沟通与决策"
TOPIC_CARD_SOURCE_ID_PREFIX = "customer_experience:catalog:v2:"
TOPIC_CARD_VERSION = "experience-topic-v1"
SOURCE_INTENT_TOPIC_RULES = (
    # The source export already carries an intent label.  Prefer this
    # one-to-one mapping over broad word matches such as "适用", which can
    # otherwise put a heat-source row into both selection and compatibility.
    ("选购与场景匹配", ("选购与推荐",)),
    ("规格与容量", ("规格参数查询",)),
    ("热源与兼容边界", ("适用热源与兼容性",)),
    ("使用与安全", ("使用方法与安全",)),
    ("材质与耐用性", ("材质与耐用性",)),
    ("套装与配件", ("套装与配件",)),
    ("价格与权益", ("价格、活动与赠品", "价格与活动")),
    ("发货与售后", ("物流配送", "售后与问题处理")),
    (EXPERIENCE_FALLBACK_TOPIC, ("评价回应与回访", "其他咨询", "综合问题处理")),
)
QA_TOPIC_PATTERNS = (
    ("场景与选购匹配", ("场景", "适合", "适用", "选购", "推荐", "人数", "targetGroup", "positioning")),
    ("规格与容量", ("尺寸", "重量", "容量", "功率", "口径", "厚度", "规格", "dimensions", "capacity", "weight")),
    ("热源与兼容边界", ("热源", "兼容", "适配", "气罐", "电磁炉", "燃气", "heatSource")),
    ("使用与安全", ("使用", "安全", "清洁", "清洗", "安装", "防风", "燃料", "usage")),
    ("材质与耐用性", ("材质", "涂层", "表面", "耐用", "防锈", "material")),
    ("套装与配件", ("套装", "配件", "包含", "组件", "附件", "accessories")),
    ("价格与权益", ("价格", "活动", "优惠", "赠品", "促销", "price")),
    ("发货与售后", ("发货", "物流", "售后", "保修", "破损", "退换", "after")),
)


def _normalise_sku(value: Any) -> str:
    return str(value or "").strip().upper()


def _text(value: Any) -> str:
    return str(value or "").strip()


def _product_value(product: Any, name: str) -> str:
    if isinstance(product, dict):
        return _text(product.get(name))
    return _text(getattr(product, name, ""))


def resolve_source_root(explicit: str | None = None) -> Path:
    """Resolve the external v12 export without making it part of the repo."""
    candidates: list[Path] = []
    if explicit:
        candidates.append(Path(explicit))
    env_value = _text(os.getenv("CUSTOMER_EXPERIENCE_SOURCE_ROOT"))
    if env_value:
        candidates.append(Path(env_value))

    # Keep the default convenient for this workstation while allowing a
    # deployment or another developer to provide --source-root.
    caiyan_root = Path(r"D:\CaiYan")
    candidates.extend(
        child
        for parent in (caiyan_root, caiyan_root / "用户评价与客服对话")
        if parent.exists()
        for child in parent.iterdir()
        if child.is_dir() and child.name.endswith("v12")
    )
    candidates.extend(
        child
        for child in caiyan_root.glob("用户评价与客服对话*")
        if child.is_dir() and child.name.endswith("v12")
    )

    for candidate in candidates:
        if (candidate / "09_严格产品映射与三链路RAG").is_dir():
            return candidate
        strict_dirs = [
            item for item in candidate.iterdir()
            if item.is_dir() and item.name.startswith("09_")
        ] if candidate.is_dir() else []
        if strict_dirs:
            return candidate
    raise FileNotFoundError(
        "未找到 v12 客服/评价导出，请使用 --source-root 指向含 09_* 目录的目录"
    )


def _strict_root(source_root: Path) -> Path:
    exact = source_root / "09_严格产品映射与三链路RAG"
    if exact.is_dir():
        return exact
    matches = sorted(
        item for item in source_root.iterdir()
        if item.is_dir() and item.name.startswith("09_")
    )
    if not matches:
        raise FileNotFoundError(f"{source_root} 下没有 09_* 严格映射目录")
    return matches[0]


def source_files(source_root: Path) -> list[Path]:
    strict_root = _strict_root(source_root)
    files = [
        path for path in strict_root.glob("07_*.jsonl")
        if path.name.startswith(SOURCE_LIBRARY_PREFIXES)
    ]
    return sorted(files, key=lambda path: path.name)


def _read_jsonl(path: Path) -> Iterable[dict[str, Any]]:
    with path.open(encoding="utf-8-sig") as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            try:
                value = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"{path}:{line_number} JSON 无法解析") from exc
            if isinstance(value, dict):
                yield value


def _sample_key(row: dict[str, Any], source_file: Path) -> str:
    return _text(row.get("qaId")) or ":".join((source_file.name, _text(row.get("recordId"))))


def collect_confirmed_samples(
    source_root: Path,
    known_skus: set[str] | None = None,
) -> dict[str, list[dict[str, Any]]]:
    """Return de-duplicated, strictly bound learning samples by SKU."""
    grouped: dict[str, dict[str, dict[str, Any]]] = defaultdict(dict)
    for path in source_files(source_root):
        for row in _read_jsonl(path):
            sku = _normalise_sku(row.get("sku"))
            if (
                not sku
                or row.get("productMatchStatus") != "matched_confirmed"
                or (known_skus is not None and sku not in known_skus)
            ):
                continue
            key = _sample_key(row, path)
            existing = grouped[sku].get(key)
            # The row-level ``library`` field uses the business numbering
            # (01/02/03...), while the file prefix is the authoritative
            # source role (07_01/07_02/...).  Keep both: role for logic,
            # label for audit metadata.
            library_role = path.name[:5]
            library_label = _text(row.get("library")) or path.stem
            if existing is None:
                existing = dict(row)
                existing["_libraries"] = set()
                existing["_library_labels"] = set()
                existing["_source_record_ids"] = []
                grouped[sku][key] = existing
            existing["_libraries"].add(library_role)
            existing["_library_labels"].add(library_label)
            source_record_id = _text(row.get("sourceRecordId")) or _text(row.get("recordId"))
            if source_record_id and source_record_id not in existing["_source_record_ids"]:
                existing["_source_record_ids"].append(source_record_id)

    return {
        sku: list(rows.values())
        for sku, rows in grouped.items()
    }


def _top_values(values: Counter[str], limit: int = MAX_TOPIC_LABELS) -> list[str]:
    return [value for value, _count in values.most_common(limit) if value]


def _counter_value(value: Any) -> str:
    return _text(value).replace("\n", " ")[:80]


def _sample_counts(samples: list[dict[str, Any]]) -> dict[str, int]:
    counts = Counter()
    for sample in samples:
        libraries = set(sample.get("_libraries") or ())
        quality = _text(sample.get("quality")).lower()
        record_type = _text(sample.get("recordType"))
        if any(library.startswith("07_01") for library in libraries) or quality == "good":
            counts["good"] += 1
        elif any(library.startswith("07_03") for library in libraries) or quality == "bad":
            counts["bad"] += 1
        else:
            counts["neutral"] += 1
        if "商品评价" in record_type:
            counts["reviews"] += 1
        if "客服对话" in record_type:
            counts["chats"] += 1
        if any(library.startswith("07_04") for library in libraries):
            counts["risk"] += 1
        if any(library.startswith("07_05") for library in libraries):
            counts["repair"] += 1
        if any(library.startswith("07_06") for library in libraries):
            counts["style"] += 1
    return {key: int(counts.get(key, 0)) for key in (
        "good", "neutral", "bad", "reviews", "chats", "risk", "repair", "style"
    )}


def _has_library(sample: dict[str, Any], role: str) -> bool:
    return any(
        str(library).startswith(role)
        for library in (sample.get("_libraries") or ())
    )


def _role_samples(samples: list[dict[str, Any]], role: str) -> list[dict[str, Any]]:
    return [sample for sample in samples if _has_library(sample, role)]


def _result_conversion(sample: dict[str, Any]) -> bool | None:
    result = sample.get("result")
    if not isinstance(result, dict):
        return None
    value = result.get("conversion")
    if value is True or str(value).strip().lower() == "true":
        return True
    if value is False or str(value).strip().lower() == "false":
        return False
    return None


def _reason_labels(sample: dict[str, Any]) -> list[str]:
    for key in ("reasonCategory", "failureReason", "repairStatus"):
        value = sample.get(key)
        if isinstance(value, list):
            labels = [_counter_value(item) for item in value]
            labels = [label for label in labels if label]
            if labels:
                return labels
        else:
            label = _counter_value(value)
            if label:
                return [label]
    return []


def _role_insights(samples: list[dict[str, Any]]) -> dict[str, Any]:
    """Summarise outcome-linked labels without copying any source answer."""
    success = _role_samples(samples, "07_01")
    non_conversion = _role_samples(samples, "07_02")
    negative = _role_samples(samples, "07_03")

    def top_field(rows: list[dict[str, Any]], field: str, limit: int = 5) -> list[str]:
        values = Counter()
        for row in rows:
            value = row.get(field)
            if isinstance(value, list):
                for item in value:
                    label = _counter_value(item)
                    if label:
                        values[label] += 1
            else:
                label = _counter_value(value)
                if label:
                    values[label] += 1
        return _top_values(values, limit)

    def top_reasons(rows: list[dict[str, Any]], limit: int = 5) -> list[str]:
        values = Counter()
        for row in rows:
            values.update(_reason_labels(row))
        return _top_values(values, limit)

    outcome_rows = {
        id(row): row
        for row in (*success, *non_conversion, *negative)
    }
    if success and (non_conversion or negative):
        outcome_shape = "mixed_signal"
    elif success:
        outcome_shape = "conversion_signal"
    elif non_conversion or negative:
        outcome_shape = "non_conversion_signal"
    else:
        outcome_shape = "no_outcome_signal"
    return {
        "conversion_samples": len(success),
        "confirmed_conversion_samples": sum(
            _result_conversion(row) is True for row in success
        ),
        "non_conversion_samples": len(non_conversion),
        "confirmed_non_conversion_samples": sum(
            _result_conversion(row) is False for row in non_conversion
        ),
        "negative_samples": len(negative),
        "outcome_sample_count": len(outcome_rows),
        "outcome_shape": outcome_shape,
        "conversion_intents": top_field(success, "intent"),
        "non_conversion_reasons": top_reasons(non_conversion),
        "non_conversion_intents": top_field(non_conversion, "intent"),
        "negative_reasons": top_reasons(negative),
        "conversion_styles": top_field(success, "styleSignals", 4),
        "non_conversion_styles": top_field(non_conversion, "styleSignals", 4),
    }


def _topic_labels_from_text(value: Any) -> list[str]:
    text = _text(value).lower()
    return [
        label
        for label, keywords in QA_TOPIC_PATTERNS
        if any(keyword.lower() in text for keyword in keywords)
    ]


def _experience_topic_labels(sample: dict[str, Any]) -> list[str]:
    """Assign a source sample to broad themes for offline aggregation only.

    This is intentionally not used to route customer questions.  A sample can
    belong to more than one theme when its existing source labels support it;
    otherwise it is kept in a neutral bucket instead of being discarded.
    """
    intent_text = _text(sample.get("intent"))
    for topic_label, markers in SOURCE_INTENT_TOPIC_RULES:
        if any(marker in intent_text for marker in markers):
            return [topic_label]

    # These source intents are deliberately broad.  Using every noun in a
    # review/question for them caused one row to enter several unrelated topic
    # cards (for example, a review mentioning both capacity and accessories).
    # Keep the source's own broad classification intact before using a textual
    # fallback for rows that have no usable intent label.
    if intent_text:
        intent_labels = _topic_labels_from_text(intent_text)
        if intent_labels:
            return [intent_labels[0]]

    reason_text = " ".join(
        _text(sample.get(field))
        for field in ("reasonCategory", "failureReason", "repairStatus")
    )
    reason_labels = _topic_labels_from_text(reason_text)
    if reason_labels:
        return reason_labels

    question_labels = _topic_labels_from_text(_text(sample.get("question")))
    return question_labels or [EXPERIENCE_FALLBACK_TOPIC]


def _topic_sample_groups(
    samples: list[dict[str, Any]],
) -> dict[str, list[dict[str, Any]]]:
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for sample in samples:
        for label in _experience_topic_labels(sample):
            groups[label].append(sample)
    return dict(groups)


def _topic_card_slug(sku: str, topic_label: str) -> str:
    digest = hashlib.sha1(
        f"{sku}|{topic_label}".encode("utf-8")
    ).hexdigest()[:16]
    return f"topic-{digest}"


def _topic_signal_counts(
    signals: dict[str, Any],
) -> dict[str, dict[str, int]]:
    """Merge same-SKU QA and conversation theme counts without copying text."""
    qa_counts = Counter(signals.get("qa_topic_counts") or {})
    conversation_counts = Counter(signals.get("conversation_topic_counts") or {})
    labels = set(qa_counts) | set(conversation_counts)
    return {
        label: {
            "qa": int(qa_counts.get(label, 0)),
            "conversation": int(conversation_counts.get(label, 0)),
            "total": int(qa_counts.get(label, 0) + conversation_counts.get(label, 0)),
        }
        for label in labels
    }


def _empty_catalog_signals() -> dict[str, Any]:
    return {
        "qa_total": 0,
        "qa_approved": 0,
        "qa_rejected": 0,
        "qa_review": 0,
        "customer_service_conversations": 0,
        "customer_service_messages": 0,
        "qa_topic_counts": {},
        "conversation_topic_counts": {},
    }


def collect_catalog_signals(
    db,
    products: Iterable[Any],
) -> dict[str, dict[str, int]]:
    """Collect safe per-SKU counts without copying QA/chat text into cards."""
    product_skus = {
        _text(product.id): _normalise_sku(product.sku)
        for product in products
        if _text(getattr(product, "id", "")) and _normalise_sku(product.sku)
    }
    signals = defaultdict(_empty_catalog_signals)

    def add_topics(sku: str, bucket: str, text: str) -> None:
        for label in _topic_labels_from_text(text):
            topic_counts = signals[sku][bucket]
            topic_counts[label] = int(topic_counts.get(label, 0)) + 1

    for qa in db.query(ProductQa).all():
        sku = product_skus.get(_text(qa.product_id))
        if not sku:
            continue
        signals[sku]["qa_total"] += 1
        status = _text(qa.integrity_status).lower()
        if status == "approved":
            signals[sku]["qa_approved"] += 1
            add_topics(sku, "qa_topic_counts", f"{qa.question} {qa.tags or ''}")
        elif status == "rejected":
            signals[sku]["qa_rejected"] += 1
        else:
            signals[sku]["qa_review"] += 1

    known_skus = set(product_skus.values())
    conversation_skus = {}
    for conversation in db.query(CustomerServiceConversation).all():
        sku = _normalise_sku(conversation.sku)
        if sku in known_skus:
            signals[sku]["customer_service_conversations"] += 1
            conversation_skus[_text(conversation.id)] = sku
            add_topics(sku, "conversation_topic_counts", _text(conversation.title))
    for message in db.query(CustomerServiceMessage).all():
        sku = _normalise_sku(message.sku) or conversation_skus.get(_text(message.conversation_id), "")
        if sku in known_skus:
            signals[sku]["customer_service_messages"] += 1
            add_topics(sku, "conversation_topic_counts", _text(message.content))
    return {
        sku: {
            **values,
            "qa_topic_counts": dict(values["qa_topic_counts"]),
            "conversation_topic_counts": dict(values["conversation_topic_counts"]),
        }
        for sku, values in signals.items()
    }


def _card_slug(sku: str) -> str:
    digest = hashlib.sha1(sku.encode("utf-8")).hexdigest()[:16]
    return f"product-{digest}"


def build_experience_card(
    product: Any,
    samples: list[dict[str, Any]] | None = None,
    *,
    source_root: Path | None = None,
    catalog_signals: dict[str, Any] | None = None,
    global_insights: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a deterministic, non-factual card for one product."""
    samples = list(samples or [])
    sku = _normalise_sku(_product_value(product, "sku"))
    name = _product_value(product, "product_name_cn") or sku
    counts = _sample_counts(samples)
    signals = {**_empty_catalog_signals(), **(catalog_signals or {})}
    outcome_insights = _role_insights(samples)
    global_insights = global_insights or _role_insights([])
    intents = Counter(_counter_value(item.get("intent")) for item in samples)
    reasons = Counter()
    styles = Counter()
    libraries = Counter()
    source_record_ids: list[str] = []
    for sample in samples:
        for library in sample.get("_library_labels") or sample.get("_libraries") or ():
            libraries[library] += 1
        for value in _reason_labels(sample):
            reasons[value] += 1
        for value in sample.get("styleSignals") or []:
            label = _counter_value(value)
            if label:
                styles[label] += 1
        for source_record_id in sample.get("_source_record_ids") or []:
            if source_record_id not in source_record_ids:
                source_record_ids.append(source_record_id)

    topic_labels = _top_values(intents)
    reason_labels = _top_values(reasons, 4)
    style_labels = _top_values(styles, 4)
    if samples:
        topic_text = "、".join(topic_labels) if topic_labels else "已确认样本待进一步归类"
        conversion_intent_text = "、".join(outcome_insights["conversion_intents"]) or "暂无稳定成功意图标签"
        non_conversion_reason_text = "、".join(outcome_insights["non_conversion_reasons"]) or "暂无明确未转化原因标签"
        non_conversion_intent_text = "、".join(outcome_insights["non_conversion_intents"]) or "暂无稳定未转化意图标签"
        negative_reason_text = "、".join(outcome_insights["negative_reasons"]) or "暂无明确差评原因标签"
        conversion_style_text = "、".join(outcome_insights["conversion_styles"]) or "暂无稳定成功表达标签"
        identity_warning = (
            "记录中出现商品识别/绑定不稳定信号，先锁定 SKU、版本和证据再回答。"
            if any(
                any(token in reason for token in ("识别", "绑定", "name_only", "unmatched"))
                for reason in outcome_insights["non_conversion_reasons"] + outcome_insights["negative_reasons"]
            )
            else "不要把样本关联直接解释成产品缺陷，先核实客户目标和当前商品证据。"
        )
        content = (
            f"{name}（SKU：{sku}）历史经验卡\n"
            "定位：只用于沟通策略，不是商品事实，不可替代当前 SKU 的产品证据。\n"
            f"样本范围：已确认 SKU 的商品评价 {counts['reviews']} 条、客服对话 {counts['chats']} 条；"
            f"成功/正向库样本 {outcome_insights['conversion_samples']}（明确成交/下单 {outcome_insights['confirmed_conversion_samples']}），"
            f"未转化库样本 {outcome_insights['non_conversion_samples']}（明确未成交 {outcome_insights['confirmed_non_conversion_samples']}），"
            f"负向/不满意 {outcome_insights['negative_samples']}。\n"
            f"客户关注主题：{topic_text}。\n"
            f"转化侧总结：{outcome_insights['conversion_samples']} 个成功样本主要集中在【{conversion_intent_text}】；"
            f"记录中更常见的有效表达动作是【{conversion_style_text}】，可作为承接顺序的参考。\n"
            f"未转化侧总结：{outcome_insights['non_conversion_samples']} 个未转化样本主要归因于【{non_conversion_reason_text}】，"
            f"对应意图集中在【{non_conversion_intent_text}】；{identity_warning}\n"
            f"差评风险总结：{outcome_insights['negative_samples']} 个负向样本主要出现【{negative_reason_text}】；"
            "遇到类似顾虑时先复述现象、补齐关键信息，再给当前渠道可核实的下一步。\n"
            "沟通做法：先确认当前 SKU、版本和客户目标，再围绕顾虑给结论；参数、兼容、功能、价格、时效、售后必须引用当前 SKU 证据，缺资料就明确说未确认。\n"
            f"样本边界：成功/正向库 {outcome_insights['conversion_samples']}、未转化库 {outcome_insights['non_conversion_samples']}、负向库 {outcome_insights['negative_samples']} 只是归档样本关联；"
            "当前数据没有曝光、咨询、下单分母，不能据此计算真实转化率或证明因果。不要照搬原话、链接、价格、赠品、时效或未经确认的事实。"
        )
        coverage_status = "history_available"
    else:
        qa_topic_labels = _top_values(
            Counter(signals.get("qa_topic_counts") or {}),
            5,
        )
        conversation_topic_labels = _top_values(
            Counter(signals.get("conversation_topic_counts") or {}),
            5,
        )
        topic_labels = qa_topic_labels or conversation_topic_labels or _topic_labels_from_text(name)
        category = _product_value(product, "category") or "未标注品类"
        qa_notice = (
            f"开发库同 SKU 另有已审核商品 QA {signals['qa_approved']} 条"
            if signals["qa_approved"]
            else "开发库当前没有已审核商品 QA"
        )
        conversation_notice = (
            f"客服会话 {signals['customer_service_conversations']} 条、消息 {signals['customer_service_messages']} 条"
            if signals["customer_service_conversations"] or signals["customer_service_messages"]
            else "客服会话统计为 0"
        )
        has_catalog_basis = bool(
            signals["qa_approved"]
            or signals["customer_service_conversations"]
            or signals["customer_service_messages"]
            or qa_topic_labels
            or conversation_topic_labels
        )
        reference_actions = global_insights.get("conversion_styles") or [
            "先给结论", "给出具体参数", "友好亲和", "给出下一步"
        ]
        reference_blockers = global_insights.get("non_conversion_reasons") or [
            "商品识别/绑定不稳定", "规格/参数信息未完成", "选购匹配未完成"
        ]
        if has_catalog_basis:
            qa_topic_text = "、".join(qa_topic_labels) or "暂无稳定 QA 主题"
            conversation_topic_text = "、".join(conversation_topic_labels) or "暂无稳定会话主题"
            content = (
                f"{name}（SKU：{sku}）推导型经验卡\n"
                "定位：这是基于同 SKU 已审核 QA、客服观察和跨产品结果样本写出的待验证沟通假设，不是该产品已证实的转化因果。\n"
                f"产品范围：{category}；{qa_notice}；{conversation_notice}。只提取主题和计数，不复制原问答、客服原话、链接或商品事实。\n"
                f"本 SKU 关注主题：QA 主要涉及【{qa_topic_text}】；会话观察涉及【{conversation_topic_text}】。\n"
                f"转化假设（待验证）：客户如果关心这些主题，优先用【{'、'.join(reference_actions[:4])}】把选择依据和下一步说清楚，更可能减少犹豫；这是跨产品经验迁移，不是本 SKU 的订单统计。\n"
                f"未转化假设（待验证）：跨产品未转化样本常见阻塞是【{'、'.join(reference_blockers[:5])}】；本产品优先逐项核实 SKU、场景、关键参数、兼容边界和当前权益，不要把缺资料补成承诺。\n"
                "建议客服打法：先确认客户使用场景和购买目标，再引用当前 SKU 的 QA/产品证据给结论；涉及价格、时效、售后或适配时，先核实条件并给可执行下一步。\n"
                "验证方式：后续记录真实曝光、咨询、加购、下单和未成交原因后，再检验这些假设，不能把本卡当真实转化率。"
            )
            coverage_status = "inferred_from_catalog_and_global"
        else:
            content = (
                f"{name}（SKU：{sku}）待积累经验卡\n"
                "当前没有来自严格确认来源、可直接用于本卡的历史商品评价或客服经验样本。\n"
                f"数据边界：{qa_notice}；{conversation_notice}。这些数据不复制原问答或原对话，商品 QA 只作为当前轮事实证据，客服会话只作为待人工提炼的观察信号。\n"
                "转化判断：严格确认的成功/未转化样本不足，不能据此推测该产品为什么转化或流失。\n"
                "使用边界：先确认当前 SKU、版本和客户目标；所有参数、兼容、功能、价格、时效和售后结论只引用当前产品证据，不能用邻近 SKU 或未匹配历史记录补答。\n"
                "积累建议：后续收集到已确认 SKU 的好评、差评和客服对话后，再更新本卡的客户关注主题与沟通策略。"
            )
            coverage_status = "no_confirmed_history"

    insight_status = (
        "observed_strict"
        if samples
        else "inferred_from_same_sku_catalog_and_global"
        if coverage_status == "inferred_from_catalog_and_global"
        else "pending"
    )
    review_status_detail = (
        "自动按严格确认 SKU 的结果库聚合；未逐卡人工复核，仅限沟通策略使用"
        if samples
        else "自动按同 SKU 已审核 QA/客服观察和跨产品结果模式推导；待真实订单数据验证，仅限沟通策略使用"
        if coverage_status == "inferred_from_catalog_and_global"
        else "暂无足够的同 SKU 或跨产品依据；仅保留待积累占位"
    )
    source_id = SOURCE_ID_PREFIX + _card_slug(sku)
    metadata = {
        "productKey": _product_value(product, "id"),
        "productName": name,
        "sku": sku,
        "productRefs": [{
            "productKey": _product_value(product, "id"),
            "sku": sku,
            "barcode": _product_value(product, "barcode"),
            "productName": name,
        }],
        "productMatchStatus": "matched_confirmed",
        "coverage_status": coverage_status,
        "sample_counts": counts,
        "catalog_signal_counts": signals,
        "conversion_insights": outcome_insights,
        "insight_status": insight_status,
        "inference_basis": (
            "strictly_mapped_outcome_libraries"
            if samples
            else "same_sku_approved_catalog_signals_plus_global_outcome_patterns"
            if coverage_status == "inferred_from_catalog_and_global"
            else "none"
        ),
        "global_reference_insights": {
            "conversion_actions": list(global_insights.get("conversion_styles") or []),
            "non_conversion_blockers": list(global_insights.get("non_conversion_reasons") or []),
        },
        "topic_labels": topic_labels,
        "reason_labels": reason_labels,
        "source_library_counts": dict(libraries),
        "source_record_count": len(source_record_ids),
        "source_record_ids": source_record_ids[:MAX_SOURCE_RECORD_IDS],
        "sourceFile": str(source_root) if source_root else None,
        "reviewStatus": "auto_generated_pilot",
        "review_status": "auto_generated_pilot",
        "review_status_detail": review_status_detail,
        "productionUse": "experience_guidance_only",
        "production_use": "experience_guidance_only",
        "answerApprovedForStandard": False,
        "authority_level": "candidate_only",
        "fact_authority": False,
        "manual_reviewed": False,
        "generation_method": "deterministic_product_conversion_insight_v2",
        "pilot_version": CARD_VERSION,
        "intent": topic_labels[0] if topic_labels else "待积累",
    }
    return {
        "source_id": source_id,
        "slug": _card_slug(sku),
        "title": f"{sku} 产品经验卡" + (
            "" if samples
            else "（推导待验证）"
            if coverage_status == "inferred_from_catalog_and_global"
            else "（待积累）"
        ),
        "content": content,
        "metadata": metadata,
    }


def build_topic_experience_card(
    product: Any,
    topic_label: str,
    samples: list[dict[str, Any]] | None = None,
    *,
    source_root: Path | None = None,
    catalog_signals: dict[str, Any] | None = None,
    global_insights: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build one narrow product/topic card from aggregate learning signals.

    Topic cards deliberately repeat no source answer.  Their narrower
    vocabulary makes semantic retrieval more likely to select the right
    experience signal, while the live product evidence path remains the only
    authority for facts.
    """
    samples = list(samples or [])
    topic_label = _text(topic_label) or EXPERIENCE_FALLBACK_TOPIC
    sku = _normalise_sku(_product_value(product, "sku"))
    name = _product_value(product, "product_name_cn") or sku
    signals = {**_empty_catalog_signals(), **(catalog_signals or {})}
    global_insights = global_insights or _role_insights([])
    outcome_insights = _role_insights(samples)
    counts = _sample_counts(samples)
    intent_counts = Counter(_counter_value(item.get("intent")) for item in samples)
    reason_counts = Counter()
    style_counts = Counter()
    libraries = Counter()
    source_record_ids: list[str] = []
    for sample in samples:
        for library in sample.get("_library_labels") or sample.get("_libraries") or ():
            libraries[library] += 1
        reason_counts.update(_reason_labels(sample))
        for value in sample.get("styleSignals") or []:
            label = _counter_value(value)
            if label:
                style_counts[label] += 1
        for source_record_id in sample.get("_source_record_ids") or []:
            if source_record_id and source_record_id not in source_record_ids:
                source_record_ids.append(source_record_id)

    source_intents = _top_values(intent_counts, 5)
    reason_labels = _top_values(reason_counts, 5)
    style_labels = _top_values(style_counts, 5)
    source_intent_text = "、".join(source_intents) or "暂无稳定来源意图标签"
    positive_intent_text = "、".join(outcome_insights["conversion_intents"])
    positive_intent_text = positive_intent_text or "暂无稳定正向意图标签"
    positive_style_text = "、".join(outcome_insights["conversion_styles"])
    positive_style_text = positive_style_text or "暂无稳定正向表达标签"
    friction_reason_text = "、".join(outcome_insights["non_conversion_reasons"])
    friction_reason_text = friction_reason_text or "暂无明确未转化原因标签"
    friction_intent_text = "、".join(outcome_insights["non_conversion_intents"])
    friction_intent_text = friction_intent_text or "暂无稳定未转化意图标签"
    negative_reason_text = "、".join(outcome_insights["negative_reasons"])
    negative_reason_text = negative_reason_text or "暂无明确差评原因标签"

    if samples:
        content = (
            f"{name}（SKU：{sku}）产品经验卡｜{topic_label}\n"
            "定位：只用于沟通策略和取舍承接，不是商品事实，不可替代当前 SKU 的产品证据。\n"
            f"主题范围：来源意图主要为【{source_intent_text}】；本卡聚合已确认 SKU 的商品评价和客服样本，不复制历史问答。\n"
            f"结果观察：正向库样本 {outcome_insights['conversion_samples']} 条（明确成交/下单 {outcome_insights['confirmed_conversion_samples']} 条），"
            f"未转化库样本 {outcome_insights['non_conversion_samples']} 条（明确未成交 {outcome_insights['confirmed_non_conversion_samples']} 条），"
            f"负向/不满意样本 {outcome_insights['negative_samples']} 条。\n"
            f"正向信号：相关意图集中在【{positive_intent_text}】，记录中较常出现的有效表达动作是【{positive_style_text}】；"
            "这些是相似场景下的沟通线索，不是本产品的因果证明。\n"
            f"摩擦信号：未转化意图集中在【{friction_intent_text}】，常见阻塞标签为【{friction_reason_text}】；"
            f"负向样本主要出现【{negative_reason_text}】。\n"
            "使用方式：当前问题与本主题相近时，把这些信号用于理解顾虑、组织证据和解释取舍；"
            "回复中的参数、兼容、功能、价格、时效和售后结论仍必须来自当前 SKU 的事实证据。\n"
            "边界：不要照搬历史原话、链接、价格、赠品、时效或未经确认的事实；当前数据没有曝光、咨询、下单分母，不能据此计算真实转化率或证明因果。"
        )
        coverage_status = "history_available"
        insight_status = "observed_strict"
        inference_basis = "strictly_mapped_outcome_libraries_by_topic"
        review_status_detail = "自动按严格确认 SKU 的主题结果聚合；未逐卡人工复核，仅限沟通策略使用"
    else:
        topic_signal_counts = _topic_signal_counts(signals)
        topic_counts = topic_signal_counts.get(topic_label, {})
        qa_count = int(topic_counts.get("qa", 0))
        conversation_count = int(topic_counts.get("conversation", 0))
        reference_actions = global_insights.get("conversion_styles") or [
            "先理解客户目标", "把选择依据说清楚", "说明关键取舍", "给出下一步"
        ]
        reference_blockers = global_insights.get("non_conversion_reasons") or [
            "商品识别/绑定不稳定", "规格/参数信息未完成", "选购匹配未完成"
        ]
        content = (
            f"{name}（SKU：{sku}）推导型产品经验卡｜{topic_label}\n"
            "定位：这是基于同 SKU 已审核 QA/客服主题和跨产品结果样本形成的待验证沟通假设，不是该产品已证实的转化因果。\n"
            f"主题依据：同 SKU 已审核 QA {qa_count} 条、客服观察 {conversation_count} 条；只使用主题和计数，不复制原问答、客服原话、链接或商品事实。\n"
            f"可迁移的正向线索（待验证）：相似结果样本中较常见的有效动作是【{'、'.join(reference_actions[:4])}】；"
            "当前只能作为承接顾虑和解释取舍的思路。\n"
            f"可迁移的摩擦线索（待验证）：相似未转化样本常见阻塞是【{'、'.join(reference_blockers[:5])}】；"
            "本 SKU 仍需以当前产品证据逐项核实，不能把推导补成承诺。\n"
            "使用方式：当前问题与本主题相近时，先理解客户目标，再让模型结合当前 SKU 证据形成自然回答；"
            "不要照搬其他产品表达，也不要为了使用本卡而增加回复篇幅。\n"
            "边界：后续需要真实曝光、咨询、加购、下单和未成交原因，才能检验本假设；不能把本卡当真实转化率。"
        )
        coverage_status = "inferred_from_catalog_and_global"
        insight_status = "inferred_from_same_sku_catalog_and_global"
        inference_basis = "same_sku_topic_catalog_signals_plus_global_outcome_patterns"
        review_status_detail = "自动按同 SKU 主题计数和跨产品结果模式推导；待真实订单数据验证，仅限沟通策略使用"

    slug = _topic_card_slug(sku, topic_label)
    source_id = TOPIC_CARD_SOURCE_ID_PREFIX + slug
    metadata = {
        "productKey": _product_value(product, "id"),
        "productName": name,
        "sku": sku,
        "productRefs": [{
            "productKey": _product_value(product, "id"),
            "sku": sku,
            "barcode": _product_value(product, "barcode"),
            "productName": name,
        }],
        "productMatchStatus": "matched_confirmed",
        "card_kind": "product_topic",
        "topic_key": topic_label,
        "topic_label": topic_label,
        "coverage_status": coverage_status,
        "sample_counts": counts,
        "topic_sample_count": len(samples),
        "topic_signal_counts": _topic_signal_counts(signals).get(topic_label, {}),
        "catalog_signal_counts": signals,
        "conversion_insights": outcome_insights,
        "insight_status": insight_status,
        "inference_basis": inference_basis,
        "global_reference_insights": {
            "conversion_actions": list(global_insights.get("conversion_styles") or []),
            "non_conversion_blockers": list(global_insights.get("non_conversion_reasons") or []),
        },
        "topic_labels": [topic_label],
        "source_intent_labels": source_intents,
        "reason_labels": reason_labels,
        "style_labels": style_labels,
        "source_library_counts": dict(libraries),
        "source_record_count": len(source_record_ids),
        "source_record_ids": source_record_ids[:MAX_SOURCE_RECORD_IDS],
        "sourceFile": str(source_root) if source_root else None,
        "reviewStatus": "auto_generated_pilot",
        "review_status": "auto_generated_pilot",
        "review_status_detail": review_status_detail,
        "productionUse": "experience_guidance_only",
        "production_use": "experience_guidance_only",
        "answerApprovedForStandard": False,
        "authority_level": "candidate_only",
        "fact_authority": False,
        "manual_reviewed": False,
        "generation_method": "deterministic_product_conversion_insight_topic_v1",
        "pilot_version": TOPIC_CARD_VERSION,
        "intent": topic_label,
        "source_id": source_id,
    }
    return {
        "source_id": source_id,
        "slug": slug,
        "title": f"{sku} 产品经验卡｜{topic_label}" + (
            "" if samples else "（推导待验证）"
        ),
        "content": content,
        "metadata": metadata,
    }


def build_topic_experience_cards(
    product: Any,
    samples: list[dict[str, Any]] | None = None,
    *,
    source_root: Path | None = None,
    catalog_signals: dict[str, Any] | None = None,
    global_insights: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Build useful topic cards without creating one-card-per-row noise."""
    samples = list(samples or [])
    signals = {**_empty_catalog_signals(), **(catalog_signals or {})}
    if samples:
        groups = _topic_sample_groups(samples)
        ranked_groups = sorted(
            groups.items(),
            key=lambda item: (-len(item[1]), item[0]),
        )
        selected = []
        for topic_label, topic_samples in ranked_groups:
            if len(topic_samples) < MIN_STRICT_TOPIC_SAMPLES:
                continue
            selected.append((topic_label, topic_samples))
            if len(selected) >= MAX_STRICT_TOPIC_CARDS_PER_PRODUCT:
                break
    else:
        topic_counts = _topic_signal_counts(signals)
        selected = [
            (topic_label, [])
            for topic_label, counts in sorted(
                topic_counts.items(),
                key=lambda item: (-int(item[1].get("total", 0)), item[0]),
            )
            if int(counts.get("total", 0)) >= MIN_INFERRED_TOPIC_SIGNALS
        ][:MAX_INFERRED_TOPIC_CARDS_PER_PRODUCT]

    return [
        build_topic_experience_card(
            product,
            topic_label,
            topic_samples,
            source_root=source_root,
            catalog_signals=signals,
            global_insights=global_insights,
        )
        for topic_label, topic_samples in selected
    ]


def build_all_cards(
    products: Iterable[Any],
    samples_by_sku: dict[str, list[dict[str, Any]]],
    *,
    source_root: Path | None = None,
    catalog_signals_by_sku: dict[str, dict[str, Any]] | None = None,
    global_insights: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    cards: list[dict[str, Any]] = []
    for product in sorted(
        products,
        key=lambda item: _normalise_sku(_product_value(item, "sku")),
    ):
        sku = _normalise_sku(_product_value(product, "sku"))
        if not sku:
            continue
        samples = samples_by_sku.get(sku, [])
        signals = (catalog_signals_by_sku or {}).get(sku, {})
        cards.append(build_experience_card(
            product,
            samples,
            source_root=source_root,
            catalog_signals=signals,
            global_insights=global_insights,
        ))
        cards.extend(build_topic_experience_cards(
            product,
            samples,
            source_root=source_root,
            catalog_signals=signals,
            global_insights=global_insights,
        ))
    return cards


def _upsert_card(db, card: dict[str, Any]) -> tuple[KnowledgeDocument, str, bool]:
    metadata_json = json.dumps(card["metadata"], ensure_ascii=False, sort_keys=True)
    chunk_metadata_json = json.dumps(
        {"title": card["title"], **card["metadata"]},
        ensure_ascii=False,
        sort_keys=True,
    )
    document = db.query(KnowledgeDocument).filter(
        KnowledgeDocument.source_type == knowledge_service.CUSTOMER_EXPERIENCE_SOURCE_TYPE,
        KnowledgeDocument.source_id == card["source_id"],
    ).first()
    action = "created" if document is None else "unchanged"
    document_changed = False
    if document is None:
        document = KnowledgeDocument(
            id=str(uuid.uuid4()),
            source_type=knowledge_service.CUSTOMER_EXPERIENCE_SOURCE_TYPE,
            source_id=card["source_id"],
            sku=card["metadata"]["sku"],
            title=card["title"],
            content=card["content"],
            metadata_json=metadata_json,
            file_hash=hashlib.sha256(card["source_id"].encode("utf-8")).hexdigest(),
            parse_status="done",
            is_active=True,
        )
        db.add(document)
        db.flush()
        document_changed = True
    else:
        document_changed = any((
            document.sku != card["metadata"]["sku"],
            document.title != card["title"],
            document.content != card["content"],
            document.metadata_json != metadata_json,
            document.parse_status != "done",
            document.parse_error is not None,
            document.is_active is not True,
        ))
        document.sku = card["metadata"]["sku"]
        document.title = card["title"]
        document.content = card["content"]
        document.metadata_json = metadata_json
        document.parse_status = "done"
        document.parse_error = None
        document.is_active = True

    chunks = db.query(KnowledgeChunk).filter(
        KnowledgeChunk.document_id == document.id
    ).order_by(KnowledgeChunk.chunk_index.asc()).all()
    chunk_created = not chunks
    chunk = chunks[0] if chunks else KnowledgeChunk(
        id=str(uuid.uuid4()), document_id=document.id, chunk_index=0
    )
    content_changed = chunk_created or chunk.content != card["content"]
    chunk_changed = chunk_created or any((
        chunk.sku != card["metadata"]["sku"],
        chunk.source_type != knowledge_service.CUSTOMER_EXPERIENCE_SOURCE_TYPE,
        content_changed,
        chunk.metadata_json != chunk_metadata_json,
    ))
    chunk.sku = card["metadata"]["sku"]
    chunk.source_type = knowledge_service.CUSTOMER_EXPERIENCE_SOURCE_TYPE
    chunk.content = card["content"]
    chunk.metadata_json = chunk_metadata_json
    needs_embedding = content_changed or chunk.embedding_status != "synced"
    if needs_embedding:
        chunk.embedding_status = "pending"
        chunk.embedding_error = None
    db.add(chunk)
    for extra in chunks[1:]:
        db.delete(extra)
    if action != "created" and (document_changed or chunk_changed or len(chunks) > 1):
        action = "updated"
    db.commit()
    db.refresh(document)
    return document, action, needs_embedding


def _stale_topic_cards(
    db,
    current_source_ids: set[str],
) -> list[KnowledgeDocument]:
    """Find only this generator's now-obsolete topic cards."""
    stale: list[KnowledgeDocument] = []
    documents = db.query(KnowledgeDocument).filter(
        KnowledgeDocument.source_type == knowledge_service.CUSTOMER_EXPERIENCE_SOURCE_TYPE,
        KnowledgeDocument.source_id.like(f"{TOPIC_CARD_SOURCE_ID_PREFIX}%"),
        KnowledgeDocument.is_active.is_(True),
    ).all()
    for document in documents:
        if document.source_id not in current_source_ids:
            stale.append(document)
    return stale


def _retire_stale_topic_cards(
    db,
    current_source_ids: set[str],
) -> int:
    """Deactivate stale generated cards while retaining their audit rows."""
    stale = _stale_topic_cards(db, current_source_ids)
    if not stale:
        return 0
    retired_at = datetime.now(timezone.utc).isoformat()
    for document in stale:
        try:
            metadata = json.loads(document.metadata_json or "{}")
        except (TypeError, ValueError):
            metadata = {}
        metadata["retired_reason"] = "topic_bucketing_refresh"
        metadata["retired_at"] = retired_at
        document.metadata_json = json.dumps(metadata, ensure_ascii=False, sort_keys=True)
        document.is_active = False
    db.commit()
    return len(stale)


async def seed(
    *,
    source_root: Path,
    dry_run: bool = False,
    no_embed: bool = False,
) -> dict[str, Any]:
    database_name = database_name_from_url(settings.DATABASE_URL)
    if settings.APP_ENV != "dev" or database_name != "product_knowledge_dev":
        raise RuntimeError(
            f"Refusing to seed outside dev: APP_ENV={settings.APP_ENV!r}, database={database_name!r}"
        )

    db = SessionLocal()
    try:
        products = db.query(Product).order_by(Product.sku.asc()).all()
        known_skus = {
            _normalise_sku(product.sku)
            for product in products
            if _normalise_sku(product.sku)
        }
        samples_by_sku = collect_confirmed_samples(source_root, known_skus)
        catalog_signals_by_sku = collect_catalog_signals(db, products)
        global_insights = _role_insights([
            sample
            for samples in samples_by_sku.values()
            for sample in samples
        ])
        cards = build_all_cards(
            products,
            samples_by_sku,
            source_root=source_root,
            catalog_signals_by_sku=catalog_signals_by_sku,
            global_insights=global_insights,
        )
        current_topic_source_ids = {
            card["source_id"]
            for card in cards
            if card["metadata"].get("card_kind") == "product_topic"
        }
        stale_topic_cards = _stale_topic_cards(db, current_topic_source_ids)
        history_cards = sum(
            card["metadata"]["coverage_status"] == "history_available"
            for card in cards
        )
        inferred_cards = sum(
            card["metadata"]["coverage_status"] == "inferred_from_catalog_and_global"
            for card in cards
        )
        pending_cards = len(cards) - history_cards - inferred_cards
        topic_cards = sum(
            card["metadata"].get("card_kind") == "product_topic"
            for card in cards
        )
        strict_topic_cards = sum(
            card["metadata"].get("card_kind") == "product_topic"
            and card["metadata"].get("coverage_status") == "history_available"
            for card in cards
        )
        inferred_topic_cards = sum(
            card["metadata"].get("card_kind") == "product_topic"
            and card["metadata"].get("coverage_status") == "inferred_from_catalog_and_global"
            for card in cards
        )
        result: dict[str, Any] = {
            "database": database_name,
            "source_root": str(source_root),
            "products": len(products),
            "cards": len(cards),
            "history_cards": history_cards,
            "inferred_cards": inferred_cards,
            "pending_cards": pending_cards,
            "no_history_cards": pending_cards,
            "topic_cards": topic_cards,
            "strict_topic_cards": strict_topic_cards,
            "inferred_topic_cards": inferred_topic_cards,
            "stale_topic_cards": len(stale_topic_cards),
            "retired_topic_cards": 0,
            "confirmed_sample_skus": len(samples_by_sku),
            "catalog_signal_skus": len(catalog_signals_by_sku),
            "dry_run": dry_run,
            "created": 0,
            "updated": 0,
            "unchanged": 0,
            "embedded": 0,
            "failed": 0,
        }
        if dry_run:
            summary_cards = [
                card for card in cards
                if card["metadata"].get("card_kind") != "product_topic"
            ]
            result["sample_counts_total"] = {
                key: sum(
                    card["metadata"]["sample_counts"].get(key, 0)
                    for card in summary_cards
                )
                for key in ("good", "neutral", "bad", "reviews", "chats", "risk", "repair", "style")
            }
            result["catalog_signal_totals"] = {
                key: sum(
                    signals.get(key, 0)
                    for signals in catalog_signals_by_sku.values()
                )
                for key in (
                    "qa_total",
                    "qa_approved",
                    "qa_rejected",
                    "qa_review",
                    "customer_service_conversations",
                    "customer_service_messages",
                )
            }
            return result

        for card in cards:
            document, action, needs_embedding = _upsert_card(db, card)
            result[action] += 1
            if needs_embedding and not no_embed:
                embedding_result = await product_vector_index_service.embed_pending_chunks(
                    db,
                    document_id=document.id,
                )
                result["embedded"] += int(embedding_result.get("embedded") or 0)
                result["failed"] += int(embedding_result.get("failed") or 0)
        result["retired_topic_cards"] = _retire_stale_topic_cards(
            db,
            current_topic_source_ids,
        )
        return result
    finally:
        db.close()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", help="v12 导出目录；默认自动寻找 D:/CaiYan 下的 v12")
    parser.add_argument("--dry-run", action="store_true", help="只统计覆盖，不写开发库")
    parser.add_argument("--no-embed", action="store_true", help="写卡但暂不调用向量嵌入服务")
    return parser.parse_args()


async def main() -> int:
    args = parse_args()
    source_root = resolve_source_root(args.source_root)
    result = await seed(
        source_root=source_root,
        dry_run=args.dry_run,
        no_embed=args.no_embed,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if not result.get("failed") else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
