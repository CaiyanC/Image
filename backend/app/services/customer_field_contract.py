from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any, Iterable


@dataclass(frozen=True)
class FieldContract:
    field_type: str
    aliases: tuple[str, ...]
    semantic_preplan_field_type: str
    full_phrases: tuple[str, ...] = ()


# Field concepts only. This taxonomy does not select products or answer users.
FIELD_CONTRACTS: tuple[FieldContract, ...] = (
    # SKU is a catalogue record key.  It must not be presented as a
    # manufacturer model number merely because both can look like a code.
    FieldContract("sku", ("商品编码", "产品编码", "SKU", "sku", "货号"), "unknown"),
    # English display name is a catalogue identity attribute, separate from
    # brand (manufacturer) and specification (physical product summary).
    FieldContract("product_name_cn", ("中文名", "中文名称", "中文商品名"), "unknown"),
    FieldContract("product_name_en", ("英文名", "英文名称", "英文商品名"), "unknown"),
    # Customer-facing listing content is distinct from catalogue identity.
    # Language/channel are evidence subtypes selected after this contract has
    # sealed the product, not parallel routing concepts.
    FieldContract(
        "content_title",
        ("中文商品标题", "英文商品标题", "商品标题", "官网标题", "Amazon标题", "营销标题"),
        "unknown",
    ),
    FieldContract(
        "content_description",
        ("中文长描述", "英文长描述", "中文刊登描述", "英文刊登描述", "长描述", "详情介绍", "详情描述", "刊登描述"),
        "unknown",
    ),
    FieldContract("bullet_points", ("五点描述", "五点卖点", "五点要点", "商品五点"), "unknown"),
    # Search terms are an internal retrieval aid. Recognise the customer
    # request so it cannot be misrouted to a public content field, but keep
    # it outside the supported evidence allowlist.
    FieldContract("search_keywords", ("搜索关键词库", "后台检索词", "检索关键词"), "unknown"),
    # The current ORM has no products.model column.  Keep model number as a
    # formal, safely-missing customer intent rather than inventing it from SKU.
    FieldContract("model", ("型号",), "unknown"),
    FieldContract("brand", ("品牌", "牌子"), "unknown", ("是什么牌子的", "哪个品牌")),
    FieldContract("category", ("商品类目", "产品类目", "属于什么类别"), "unknown", ("属于什么类", "是什么品类")),
    FieldContract("dimensions", ("展开后尺寸", "收起后尺寸", "展开尺寸", "收纳尺寸", "长宽高", "大小", "尺寸"), "unknown"),
    FieldContract("specification", ("规格",), "unknown"),
    FieldContract(
        "technical_advantages",
        ("技术优势", "技术特点"),
        "unknown",
        ("技术优势是什么", "有什么技术特点"),
    ),
    FieldContract("power", ("功率", "瓦数", "多少瓦"), "unknown", ("功率是多少", "最大功率是多少", "多少瓦")),
    FieldContract(
        "capacity",
        ("毫升数", "升数", "容量", "能装多少", "装多少"),
        "capacity",
        ("容量多大", "容量是多少", "容量有多大", "能装多少", "装多少"),
    ),
    FieldContract(
        "weight",
        ("净重", "毛重", "重量", "多重"),
        "unknown",
        ("自身有多重", "本身有多重", "自身多重", "本身多重", "有多重", "多重"),
    ),
    FieldContract(
        "people",
        ("适用人数", "几个人", "多少人", "几人用", "适用几人", "几人份"),
        "unknown",
        ("适合几个人", "适合多少人", "几个人用", "适用几人", "适用人数", "能供几个人使用", "可供几人", "几人份", "够几个人用"),
    ),
    FieldContract(
        "target_audience",
        ("目标人群", "适用人群", "面向人群", "适合哪些人群"),
        "unknown",
        ("适合什么人", "更适合哪些人", "主要给谁用", "面向哪些用户"),
    ),
    FieldContract(
        "material",
        ("材质", "材料"),
        "material",
        ("用的是什么材质", "由什么材料制成", "什么材料做的", "是什么材质", "是什么材料", "用什么材料", "材质是什么", "什么材质"),
    ),
    FieldContract("color", ("颜色",), "unknown"),
    FieldContract(
        "barcode",
        ("商品条码", "产品条码", "条形码", "条码", "EAN", "UPC"),
        "unknown",
        ("的商品条码是什么", "的产品条码是什么", "的条形码是什么", "的条码是什么"),
    ),
    FieldContract(
        "series",
        ("产品系列", "商品系列", "所属系列"),
        "unknown",
        ("属于哪个产品系列", "属于什么产品系列", "属于哪个商品系列", "属于什么商品系列"),
    ),
    FieldContract(
        "launch_date",
        ("上市日期", "上市时间", "何时上市", "什么时候上市"),
        "unknown",
        ("是什么时候上市的", "什么时候上市", "何时上市"),
    ),
    FieldContract(
        "lifecycle_status",
        ("在售状态", "生命周期状态", "是否在售", "还在售吗", "停产了吗"),
        "unknown",
        ("现在还在售吗", "目前还在售吗", "现在是否在售", "目前是否在售", "停产了吗"),
    ),
    FieldContract(
        "surface_finish",
        ("表面处理工艺", "表面处理", "表面工艺"),
        "unknown",
        ("表面用了什么处理工艺", "表面是什么处理工艺", "的表面处理工艺是什么"),
    ),
    FieldContract(
        "positioning",
        ("产品定位", "商品定位"),
        "unknown",
        ("的产品定位是什么", "的商品定位是什么"),
    ),
    FieldContract(
        "price_positioning",
        ("价格定位", "价位定位", "价格档位"),
        "unknown",
        ("属于什么价格定位", "是什么价格定位", "的价格定位是什么"),
    ),
    FieldContract(
        "emotional_value",
        ("情感价值", "情绪价值"),
        "unknown",
        ("强调的情感价值是什么", "的情感价值是什么", "的情绪价值是什么"),
    ),
    FieldContract(
        "competitor_benchmark",
        ("竞品对标", "竞品对比"),
        "unknown",
        ("竞品对标是什么", "和同类产品怎么对比"),
    ),
    FieldContract(
        "sales_region",
        ("销售区域", "销售地区", "售卖地区"),
        "unknown",
        ("面向哪些地区销售", "在哪些地区销售", "有哪些销售区域"),
    ),
    FieldContract(
        "certification",
        ("产品认证", "商品认证", "认证信息"),
        "unknown",
        ("有哪些产品认证", "有哪些商品认证", "通过了哪些认证"),
    ),
    FieldContract(
        "heat_source",
        ("电陶炉", "电磁炉", "卡式炉", "酒精炉", "热源", "明火", "直火"),
        "heat_source",
        ("可以直火加热吗", "能放什么炉上用", "能不能明火用", "能不能明火烧", "能不能直火", "可以用酒精炉吗", "能用卡式炉吗", "支持什么热源", "能明火烧吗", "能明火用吗", "可以明火吗", "支持明火吗", "适用什么炉", "适配什么燃料", "用什么燃料", "支持什么燃料", "可用什么燃料", "能用什么燃料"),
    ),
    FieldContract("dishwasher", ("洗碗机",), "unknown"),
    FieldContract("selling_point", ("核心卖点", "主要卖点", "产品卖点", "核心特点", "主要特点", "产品特点", "特点", "卖点"), "unknown"),
    FieldContract("product_level", ("商品分级", "产品分级", "商品等级"), "unknown"),
    FieldContract("purchase_channel", ("购买渠道", "哪里有售卖", "哪里购买", "在哪买", "售卖渠道"), "unknown"),
    FieldContract(
        "usage_instruction",
        ("怎么使用", "如何使用", "使用方法", "怎么用"),
        "unknown",
        ("怎么使用", "如何使用", "怎么用"),
    ),
    FieldContract(
        "cleaning",
        ("怎么清洁", "如何清洁", "怎么洗", "清洗方法"),
        "unknown",
        ("怎么清洁", "如何清洁", "怎么洗"),
    ),
    FieldContract(
        "care",
        ("怎么保养", "如何保养", "养护方法"),
        "unknown",
        ("怎么保养", "如何保养"),
    ),
    FieldContract(
        "usage_scene",
        ("适合露营吗", "使用场景", "适合什么场景"),
        "unknown",
        ("适合露营吗", "适合什么场景"),
    ),
    FieldContract(
        "manual",
        ("电子说明书", "官方说明书", "使用手册", "操作手册", "用户手册", "产品手册", "说明书"),
        "unknown",
        ("有没有电子说明书", "有没有官方说明书", "有没有使用手册", "有没有操作手册", "有没有用户手册", "有没有产品手册", "有没有说明书", "有电子说明书吗", "有官方说明书吗", "有使用手册吗", "有操作手册吗", "有用户手册吗", "有产品手册吗", "有说明书吗", "电子说明书在哪里", "官方说明书在哪里", "使用手册在哪里", "操作手册在哪里", "用户手册在哪里", "产品手册在哪里", "说明书在哪里", "怎么查看电子说明书", "怎么查看官方说明书", "怎么查看使用手册", "怎么查看操作手册", "怎么查看用户手册", "怎么查看产品手册", "怎么查看说明书"),
    ),
    FieldContract(
        "after_sales_contact",
        ("售后服务电话", "售后联系电话", "售后电话", "客服联系方式", "售后联系方式", "客服电话", "客服热线"),
        "unknown",
        ("售后电话是多少", "售后联系电话是多少", "客服联系方式是什么", "售后联系方式是什么", "客服电话是多少", "客服热线是多少", "怎么联系售后"),
    ),
    FieldContract(
        "inventory",
        ("实时库存", "当前库存", "库存", "现货"),
        "unknown",
        ("当前还有库存吗", "现在还有库存吗", "当前库存有多少", "现在库存有几件", "库存还有多少", "当前库存还有多少", "当前有现货吗", "现在有现货吗", "有现货吗", "还有货吗"),
    ),
    FieldContract("gift", ("赠品",), "gift", ("有没有赠品", "有赠品吗", "赠送什么", "送什么", "送啥")),
    FieldContract(
        "price",
        ("当前售价", "实时价格", "当前价格", "售价", "多少钱", "价格"),
        "price",
        ("当前售价是多少", "现在售价是多少", "售价是多少", "当前价格是多少", "现在多少钱", "多少钱"),
    ),
    FieldContract(
        "warranty",
        ("保修", "质保", "保修期", "质保期"),
        "unknown",
        ("质保多长时间", "保修多长时间", "保修期多久", "质保期多久", "有没有保修", "有没有质保", "保不保修", "有保修吗", "质保多久", "保修多久", "质保几年", "保几年"),
    ),
    FieldContract(
        "shipping",
        ("运费", "包邮", "发货", "寄出", "发出", "发货时效", "配送时效", "送到"),
        "unknown",
        ("运费多少", "包邮吗", "现在下单什么时候发", "能不能马上发货", "什么时候能送到", "今天能发货吗", "现在下单多久发", "现在下单几天发", "多久可以寄出", "多久可以发出", "什么时候发货", "多久能发货", "什么时候寄出", "可以当天发吗", "几天能寄出", "什么时候发", "今天能发吗", "发货时效", "配送时效", "多久送到"),
    ),
    FieldContract(
        "accessories",
        (
            "包装清单", "包装里有什么", "盒子里有什么", "里面有什么", "开箱有什么",
            "套装包含哪些东西", "包含哪些东西", "套装里带什么", "套装内容", "组成是什么",
            "包含哪些配件", "有哪些配件", "有什么配件", "标配有什么", "原厂配了什么", "随附什么", "附带什么",
            "package includes", "what's included", "what is included", "what does it come with",
            "what comes in the box", "standard accessories", "有没有附件", "附件", "包含什么", "配件",
        ),
        "contents",
    ),
)

# One canonical taxonomy is shared by the semantic planner and the final
# FieldContract.  Unsupported/realtime fields remain formal customer intents:
# they differ only in execution policy (safe missing / external confirmation),
# not in what the customer asked.
FORMAL_DETAIL_FIELDS = frozenset(contract.field_type for contract in FIELD_CONTRACTS)
_LEGACY_SEMANTIC_FIELD_ALIASES = {
    "stock": "inventory",
    "contents": "accessories",
    "usage": "usage_instruction",
}

DETAIL_FIELD_LABELS = {
    "sku": "SKU",
    "product_name_cn": "中文名",
    "product_name_en": "英文名",
    "content_title": "商品标题",
    "content_description": "商品长描述",
    "bullet_points": "五点描述",
    "search_keywords": "搜索关键词",
    "model": "型号",
    "brand": "品牌",
    "category": "商品类目",
    "dimensions": "尺寸",
    "specification": "规格",
    "power": "功率",
    "capacity": "容量",
    "weight": "重量",
    "people": "适用人数",
    "target_audience": "适合人群",
    "material": "材质",
    "color": "颜色",
    "barcode": "商品条码",
    "series": "产品系列",
    "launch_date": "上市日期",
    "lifecycle_status": "生命周期状态（非实时库存）",
    "technical_advantages": "技术优势",
    "surface_finish": "表面处理工艺",
    "positioning": "产品定位",
    "price_positioning": "价格定位",
    "emotional_value": "情感价值",
    "competitor_benchmark": "竞品对标",
    "sales_region": "销售区域",
    "certification": "产品认证",
    "heat_source": "适用热源",
    "dishwasher": "洗碗机适配",
    "selling_point": "核心卖点",
    "product_level": "商品分级",
    "purchase_channel": "购买渠道",
    "usage_instruction": "使用方法",
    "cleaning": "清洁",
    "care": "保养",
    "usage_scene": "使用场景",
    "manual": "官方说明书",
    "after_sales_contact": "售后电话",
    "inventory": "库存",
    "gift": "赠品",
    "price": "价格",
    "warranty": "保修",
    "shipping": "发货时效",
    "accessories": "配件",
}

# A material FieldContract can be scoped to a physical component without
# creating a second material taxonomy.  These labels are execution scopes for
# the same canonical ``material`` field: the structured provider decides which
# same-SKU evidence is valid for each component.
_MATERIAL_COMPONENT_DETAIL_LABELS = {
    "body": "主体材质",
    "handle": "手柄材质",
    "lid": "锅盖材质",
}


def material_component_detail_requests(question: str) -> list[str]:
    """Return ordered material component requests explicitly named by a user.

    This is deliberately a scope parser, not an intent classifier: callers
    may use it only after the formal canonical field is already ``material``.
    It therefore cannot turn a product-name token into a material request.
    """
    text = str(question or "")
    if not any(term in text for term in ("材质", "材料")):
        return []
    requests: list[str] = []
    if any(term in text for term in ("主体", "锅体", "炉体", "壶身", "杯身")):
        requests.append(_MATERIAL_COMPONENT_DETAIL_LABELS["body"])
    if any(term in text for term in ("手柄", "把手")):
        requests.append(_MATERIAL_COMPONENT_DETAIL_LABELS["handle"])
    if any(term in text for term in ("锅盖", "盖子", "杯盖")):
        requests.append(_MATERIAL_COMPONENT_DETAIL_LABELS["lid"])
    return requests


def material_component_from_detail_label(label: str | None) -> str | None:
    value = str(label or "").strip()
    for component, display_label in _MATERIAL_COMPONENT_DETAIL_LABELS.items():
        if value == display_label:
            return component
    return None

# Stable labels emitted by the legacy planner are normalized here before
# Phase 2 consumes them. This maps labels only; it does not detect new text.
LEGACY_DETAIL_FIELD_TYPES = {
    "目标人群": "target_audience",
    "热源": "heat_source",
    "适用场景": "usage_scene",
    # The legacy intent parser emits this stable display label. Normalize the
    # label into the existing canonical certification contract; recognition,
    # entity resolution and evidence policy remain centralized below it.
    "认证": "certification",
}

# Recognized fields may still require an established evidence extractor before
# they are allowed to participate in single-product detail arbitration.
SUPPORTED_DETAIL_FIELDS = frozenset({
    "sku",
    "product_name_cn",
    "product_name_en",
    "content_title",
    "content_description",
    "bullet_points",
    "brand",
    "category",
    "dimensions",
    "specification",
    "technical_advantages",
    "power",
    "capacity",
    "weight",
    "people",
    "target_audience",
    "material",
    "color",
    "barcode",
    "series",
    "launch_date",
    "lifecycle_status",
    "surface_finish",
    "positioning",
    "price_positioning",
    "emotional_value",
    "competitor_benchmark",
    "sales_region",
    "certification",
    "heat_source",
    "dishwasher",
    "selling_point",
    "product_level",
    "purchase_channel",
    "usage_instruction",
    "cleaning",
    "care",
    "usage_scene",
    "accessories",
})


@dataclass(frozen=True)
class FieldEvidencePolicy:
    """Allowed evidence for one explicit product-detail field."""

    field_type: str
    aliases: tuple[str, ...]
    structured_fields: tuple[str, ...]
    qa_aliases: tuple[str, ...]
    compatible_field_types: tuple[str, ...] = ()


@dataclass(frozen=True)
class DimensionEvidence:
    value: str
    scope: str
    label: str = ""
    unit: str = ""
    subtype: str = "product"
    is_generic_fallback: bool = False


@dataclass(frozen=True)
class EntityScopeNormalization:
    entity_subject: str
    requested_scope: str
    removed_scope_span: tuple[int, int] | None
    normalization_reason: str | None


@dataclass(frozen=True)
class EntitySubjectSelection:
    entity_subject: str
    source: str
    field: str | None
    field_span: tuple[int, int] | None
    raw_subject: str
    requested_scope: str
    removed_scope_span: tuple[int, int] | None
    normalization_reason: str | None
    fallback_used: bool
    reason: str
    core_field_span: tuple[int, int] | None = None
    full_field_phrase_span: tuple[int, int] | None = None
    full_field_phrase: str = ""


def _aliases(field_type: str) -> tuple[str, ...]:
    contract = next((item for item in FIELD_CONTRACTS if item.field_type == field_type), None)
    return contract.aliases if contract else ()


# This policy is field-scoped only. It never chooses a product or generates an answer.
FIELD_EVIDENCE_POLICIES: dict[str, FieldEvidencePolicy] = {
    "sku": FieldEvidencePolicy("sku", _aliases("sku"), ("product.sku",), _aliases("sku")),
    "product_name_cn": FieldEvidencePolicy(
        "product_name_cn", _aliases("product_name_cn"), ("product.product_name_cn",), _aliases("product_name_cn")
    ),
    "product_name_en": FieldEvidencePolicy(
        "product_name_en", _aliases("product_name_en"), ("product.product_name_en",), _aliases("product_name_en")
    ),
    "content_title": FieldEvidencePolicy(
        "content_title", _aliases("content_title"), ("content.title_cn", "content.title_en", "content.website_title", "content.amazon_title"), _aliases("content_title")
    ),
    "content_description": FieldEvidencePolicy(
        "content_description", _aliases("content_description"), ("content.long_description_cn", "content.long_description_en", "content.listing_cn", "content.listing_en"), _aliases("content_description")
    ),
    "bullet_points": FieldEvidencePolicy(
        "bullet_points", _aliases("bullet_points"), ("content.bullet_points",), _aliases("bullet_points")
    ),
    "search_keywords": FieldEvidencePolicy("search_keywords", _aliases("search_keywords"), (), _aliases("search_keywords")),
    "model": FieldEvidencePolicy("model", _aliases("model"), ("product.model",), _aliases("model")),
    "brand": FieldEvidencePolicy("brand", _aliases("brand"), ("product.brand",), _aliases("brand")),
    "category": FieldEvidencePolicy("category", _aliases("category"), ("product.category",), _aliases("category")),
    "dimensions": FieldEvidencePolicy("dimensions", _aliases("dimensions"), ("specs.size_info", "specs.dimensions", "specs.package_size"), _aliases("dimensions")),
    "specification": FieldEvidencePolicy("specification", _aliases("specification"), ("specification.summary",), _aliases("specification")),
    "power": FieldEvidencePolicy("power", _aliases("power"), ("specs.power",), _aliases("power")),
    "capacity": FieldEvidencePolicy("capacity", _aliases("capacity"), ("specs.capacity",), _aliases("capacity")),
    "weight": FieldEvidencePolicy("weight", _aliases("weight"), ("specs.gross_weight_g", "specs.net_weight_g", "specs.weight_info"), _aliases("weight")),
    # The shared provider accepts only an explicit headcount from either
    # customer-audience or recorded selling-point text; it never infers a
    # serving count from a product name, capacity, or generic marketing prose.
    "people": FieldEvidencePolicy("people", _aliases("people"), ("business.target_audience", "business.top_selling_points"), _aliases("people")),
    "target_audience": FieldEvidencePolicy("target_audience", _aliases("target_audience"), ("business.target_audience",), _aliases("target_audience")),
    "material": FieldEvidencePolicy("material", _aliases("material"), ("specs.body_material",), _aliases("material")),
    "color": FieldEvidencePolicy("color", _aliases("color"), ("specs.color",), _aliases("color")),
    "barcode": FieldEvidencePolicy("barcode", _aliases("barcode"), ("product.barcode",), _aliases("barcode")),
    "series": FieldEvidencePolicy("series", _aliases("series"), ("product.series",), _aliases("series")),
    "launch_date": FieldEvidencePolicy("launch_date", _aliases("launch_date"), ("product.launch_date",), _aliases("launch_date")),
    # Lifecycle is a product planning record, never a proxy for real-time
    # inventory or current channel availability.
    "lifecycle_status": FieldEvidencePolicy("lifecycle_status", _aliases("lifecycle_status"), ("product.lifecycle_status",), _aliases("lifecycle_status")),
    "technical_advantages": FieldEvidencePolicy("technical_advantages", _aliases("technical_advantages"), ("specs.technical_advantages",), _aliases("technical_advantages")),
    "surface_finish": FieldEvidencePolicy("surface_finish", _aliases("surface_finish"), ("specs.surface_finish",), _aliases("surface_finish")),
    "positioning": FieldEvidencePolicy("positioning", _aliases("positioning"), ("business.positioning",), _aliases("positioning")),
    "price_positioning": FieldEvidencePolicy("price_positioning", _aliases("price_positioning"), ("business.price_positioning",), _aliases("price_positioning")),
    "emotional_value": FieldEvidencePolicy("emotional_value", _aliases("emotional_value"), ("business.emotional_value",), _aliases("emotional_value")),
    "competitor_benchmark": FieldEvidencePolicy("competitor_benchmark", _aliases("competitor_benchmark"), ("business.competitor_benchmark",), _aliases("competitor_benchmark")),
    # Association values are read through the shared structured provider.  The
    # association prefix is intentionally part of the policy rather than a
    # parallel per-field route, so the same sealed product identity is used.
    "sales_region": FieldEvidencePolicy("sales_region", _aliases("sales_region"), ("associations.regions",), _aliases("sales_region")),
    "certification": FieldEvidencePolicy("certification", _aliases("certification"), ("associations.certifications",), _aliases("certification")),
    # A product's explicit compatibility statement in the structured selling
    # points is admissible heat-source evidence when the direct heat-source
    # cell does not carry that compatibility detail.
    "heat_source": FieldEvidencePolicy("heat_source", _aliases("heat_source"), ("specs.heat_source", "business.top_selling_points"), _aliases("heat_source")),
    "dishwasher": FieldEvidencePolicy("dishwasher", _aliases("dishwasher"), ("specs.usage_instruction",), _aliases("dishwasher")),
    "selling_point": FieldEvidencePolicy("selling_point", _aliases("selling_point"), ("business.top_selling_points",), _aliases("selling_point")),
    "product_level": FieldEvidencePolicy("product_level", _aliases("product_level"), ("product.product_level",), _aliases("product_level")),
    "purchase_channel": FieldEvidencePolicy("purchase_channel", _aliases("purchase_channel"), ("associations.channels",), _aliases("purchase_channel")),
    "usage_instruction": FieldEvidencePolicy("usage_instruction", _aliases("usage_instruction"), ("specs.usage_instruction",), _aliases("usage_instruction")),
    "cleaning": FieldEvidencePolicy("cleaning", _aliases("cleaning"), ("specs.usage_instruction",), _aliases("cleaning")),
    "care": FieldEvidencePolicy("care", _aliases("care"), ("specs.usage_instruction",), _aliases("care")),
    "usage_scene": FieldEvidencePolicy("usage_scene", _aliases("usage_scene"), ("business.usage_scenarios",), _aliases("usage_scene")),
    # Shipping is product-bound only when the catalog carries same-SKU
    # fulfillment data.  The empty policy is deliberate: the formatter must
    # produce a safe missing-data answer rather than infer a delivery promise.
    "shipping": FieldEvidencePolicy("shipping", _aliases("shipping"), (), _aliases("shipping")),
    "gift": FieldEvidencePolicy("gift", _aliases("gift"), (), _aliases("gift")),
    "price": FieldEvidencePolicy("price", _aliases("price"), (), _aliases("price")),
    "accessories": FieldEvidencePolicy("accessories", _aliases("accessories"), (), _aliases("accessories")),
}


def field_evidence_policy(field_type: str | None) -> FieldEvidencePolicy | None:
    return FIELD_EVIDENCE_POLICIES.get(str(field_type or "").strip())


def is_supported_detail_field(field_type: str | None) -> bool:
    return str(field_type or "").strip() in SUPPORTED_DETAIL_FIELDS


def field_type_from_detail_label(label: str | None) -> str | None:
    value = str(label or "").strip()
    if material_component_from_detail_label(value):
        return "material"
    if value in LEGACY_DETAIL_FIELD_TYPES:
        return LEGACY_DETAIL_FIELD_TYPES[value]
    for field_type, detail_label in DETAIL_FIELD_LABELS.items():
        if value == detail_label:
            return field_type
    return None


def qa_evidence_matches_field(question: str, tags: str | None, field_type: str | None) -> bool:
    """Only accept QA whose question or tags explicitly identify the requested field."""
    policy = field_evidence_policy(field_type)
    if not policy:
        return False
    haystack = f"{str(question or '')} {str(tags or '')}".lower()
    if any(alias and alias.lower() in haystack for alias in policy.qa_aliases):
        return True
    # Keep QA acceptance aligned with the high-precision semantic-outage
    # fallback.  This consumes only the QA's own question (not a product name
    # or caller phrase) and still requires the later same-SKU evidence gate.
    composed = deterministic_compositional_field_candidate(question)
    return bool(composed and composed[0] == policy.field_type)


def requested_evidence_scope(question: str, field_type: str | None) -> str:
    if str(field_type or "").strip() != "dimensions":
        return "subject"
    text = str(question or "")
    return "package" if any(term in text for term in ("包装尺寸", "外箱尺寸", "包裹尺寸")) else "subject"


def requested_dimension_subtype(question: str) -> str | None:
    text = str(question or "")
    if any(term in text for term in ("包装尺寸", "外箱尺寸", "包裹尺寸")):
        return "package"
    if any(term in text for term in ("收纳尺寸", "收起尺寸", "收起后尺寸")):
        return "storage"
    if any(term in text for term in ("展开尺寸", "展开后尺寸")):
        return "expanded"
    return None


def requested_cleaning_subtype(question: str) -> str | None:
    """Return a safety-relevant cleaning subtype without deciding the field.

    Semantic planning owns whether the request is ``cleaning``.  Once that
    contract exists, the deterministic evidence layer may require a narrower
    proof before answering a compatibility question.  Generic ``机洗`` refers
    to a laundry/washing machine in Chinese; it must never be treated as an
    implicit dishwasher request.
    """
    text = str(question or "")
    if "洗碗机" in text:
        return None
    if any(term in text for term in ("洗衣机", "机洗")):
        return "machine_wash"
    return None


def requested_usage_instruction_subtype(question: str) -> str | None:
    """Return a formatter-safe usage subtype after the canonical field is set."""
    composed = deterministic_compositional_field_candidate(question)
    if composed and composed[0] == "usage_instruction" and composed[1] == "compositional liquid-temperature capability intent":
        return "liquid_temperature_capability"
    return None


def normalize_field_adjacent_entity_scope(
    *,
    question: str,
    raw_subject: str,
    canonical_field: str | None,
    field_phrase: str = "",
) -> EntityScopeNormalization:
    # Quotation marks delimit a user-supplied product mention; they are not
    # part of its identity.  Removing only enclosing punctuation keeps the
    # exact catalogue subject available to EntityResolutionContract without
    # broadening aliases or accepting a partial match.
    subject = str(raw_subject or "").strip().strip("「」『』\"'“”")
    scope = requested_evidence_scope(question, canonical_field)
    if not subject:
        return EntityScopeNormalization(subject, scope, None, None)
    contract = next((item for item in FIELD_CONTRACTS if item.field_type == canonical_field), None)
    if contract is None:
        return EntityScopeNormalization(subject, scope, None, None)
    # Component qualifiers can sit immediately before the generic ``材质``
    # alias ("商品的主体材质") and are therefore initially captured as part
    # of the left-hand entity span.  They refine material evidence, never
    # product identity; remove the qualifier before EntityResolution.
    if canonical_field == "material" and material_component_detail_requests(question):
        for suffix in ("的主体", "主体", "的锅盖", "锅盖", "的盖子", "盖子", "的杯盖", "杯盖"):
            if subject.endswith(suffix):
                entity_subject = subject[:-len(suffix)].rstrip().removesuffix("的").rstrip()
                if entity_subject:
                    start = len(subject) - len(suffix)
                    return EntityScopeNormalization(
                        entity_subject,
                        scope,
                        (start, len(subject)),
                        "material_component_scope",
                    )
    remainder = str(question or "")[len(subject):] if str(question or "").startswith(subject) else ""
    expected_field_starts = tuple(
        value
        for value in (str(field_phrase or "").strip(), *contract.aliases)
        if value
    )
    if not any(remainder.startswith(value) for value in expected_field_starts):
        return EntityScopeNormalization(subject, scope, None, None)
    suffixes = (
        (("的包装", "外包装", "包装后", "包装"), "package", "field_adjacent_package_scope"),
        (("商品本身", "本身的", "自身的", "的主体", "本身", "自身", "本体", "主体"), "subject", "field_adjacent_subject_scope"),
    )
    for terms, expected_scope, reason in suffixes:
        for term in sorted(terms, key=len, reverse=True):
            if subject.endswith(term) and scope == expected_scope:
                start = len(subject) - len(term)
                entity_subject = subject[:start].rstrip().removesuffix("的").rstrip()
                if entity_subject:
                    return EntityScopeNormalization(entity_subject, scope, (start, len(subject)), reason)
    return EntityScopeNormalization(subject, scope, None, None)


def _dimension_scope(label: str) -> str:
    value = str(label or "").strip()
    if value in {"", "尺寸", "大小", "长宽高", "展开尺寸", "收纳尺寸", "展开后尺寸", "收起后尺寸"}:
        return "subject"
    if any(term in value for term in ("包装", "外箱", "包裹")):
        return "package"
    return "component"


def _dimension_subtype(label: str) -> str | None:
    value = str(label or "").strip()
    if any(term in value for term in ("包装", "外箱", "包裹")):
        return "package"
    if value in {"收纳尺寸", "收起尺寸", "收起后尺寸"}:
        return "storage"
    if value in {"展开尺寸", "展开后尺寸"}:
        return "expanded"
    if value in {"", "尺寸", "大小", "长宽高", "产品尺寸", "本体尺寸", "产品本体尺寸"}:
        return "product"
    return None


def _dimension_value_is_concrete(value: Any) -> bool:
    """Reject labels/placeholders that do not carry a measurable dimension."""
    text = str(value or "").strip()
    return bool(text and text not in {"/", "[]"} and re.search(r"\d", text))


def select_dimension_evidence(
    raw_value: Any,
    *,
    requested_scope: str,
    requested_subtype: str | None = None,
) -> DimensionEvidence | None:
    """Return only structured dimensions matching the requested evidence scope."""
    # Imported cells can carry a delimiter left behind by a source label
    # (for example ``:9.5x6.7mm``).  The delimiter is not measurement evidence
    # and would otherwise produce a duplicated separator in the formatter.
    value = re.sub(r"^[\s:：,，;；]+", "", str(raw_value or "").strip())
    if not _dimension_value_is_concrete(value):
        return None
    try:
        parsed = json.loads(value)
    except (TypeError, ValueError, json.JSONDecodeError):
        return DimensionEvidence(value=value, scope="subject", label="尺寸") if requested_scope == "subject" else None
    if not isinstance(parsed, list):
        return DimensionEvidence(value=value, scope="subject", label="尺寸") if requested_scope == "subject" else None
    candidates = [
        item
        for item in parsed
        if isinstance(item, dict)
        and _dimension_value_is_concrete(item.get("value"))
        and _dimension_scope(str(item.get("label") or "")) == requested_scope
    ]
    effective_subtype = requested_subtype or ("package" if requested_scope == "package" else None)
    if effective_subtype:
        candidates = [
            item
            for item in candidates
            if _dimension_subtype(str(item.get("label") or "")) == effective_subtype
        ]
    else:
        product_candidates = [
            item
            for item in candidates
            if _dimension_subtype(str(item.get("label") or "")) == "product"
        ]
        expanded_candidates = [
            item
            for item in candidates
            if _dimension_subtype(str(item.get("label") or "")) == "expanded"
        ]
        candidates = product_candidates or expanded_candidates
    if not candidates:
        return None
    selected = candidates[0]
    label = str(selected.get("label") or "尺寸").strip()
    subtype = _dimension_subtype(label) or effective_subtype or "product"
    return DimensionEvidence(
        value=re.sub(r"^[\s:：,，;；]+", "", str(selected.get("value") or "").strip()),
        scope=requested_scope,
        label=label,
        unit=str(selected.get("unit") or "").strip(),
        subtype=subtype,
        is_generic_fallback=bool(not requested_subtype and subtype == "expanded"),
    )


def iter_field_aliases() -> Iterable[tuple[str, FieldContract]]:
    pairs = [(alias, contract) for contract in FIELD_CONTRACTS for alias in contract.aliases]
    return tuple(sorted(pairs, key=lambda item: len(item[0]), reverse=True))


def iter_full_field_phrases() -> Iterable[tuple[str, FieldContract]]:
    pairs = [(phrase, contract) for contract in FIELD_CONTRACTS for phrase in contract.full_phrases]
    return tuple(sorted(pairs, key=lambda item: len(item[0]), reverse=True))


_ASCII_PRODUCT_CODE_PATTERN = re.compile(
    r"(?<![A-Za-z0-9])[A-Za-z0-9]{1,24}(?:[-_][A-Za-z0-9]{1,24})+(?![A-Za-z0-9])"
)


def _span_is_inside_product_code(text: str, start: int, end: int) -> bool:
    """Return whether a field-looking token is part of an ASCII product code."""
    return any(
        match.start() <= start and end <= match.end()
        for match in _ASCII_PRODUCT_CODE_PATTERN.finditer(str(text or ""))
    )


_MATERIAL_PREDICATE_PATTERN = re.compile(
    r"(?:是|由|拿)?(?:用)?(?:什么|哪种|哪类)(?:材料|材质)?"
    r"(?:做成|制成|制作|打造|做)(?:出来的|而成|的)?"
    r"(?=吗?(?:$|[？?。！!，,；;\s]))"
)

# These request predicates are grammatical spans, not product-specific aliases.
# Matching the whole predicate is important because the text before the
# canonical field word (for example ``有哪些`` or ``主体主要用``) is not part
# of the product identity.  If only the final alias is consumed, exact product
# names are silently downgraded to substring candidates.
_MATERIAL_FIELD_REQUEST_PATTERN = re.compile(
    r"(?:"
    r"(?:的(?:(?:商品|产品)?(?:本体|主体)|[\u4e00-\u9fff]{1,4}体|本身|自身))"
    r"(?:主要)?(?:是|由|拿)?(?:用)?(?:的)?(?:是什么|什么|哪种|哪类)(?:材料|材质)"
    r"|(?:主要)?(?:是|由|拿)?(?:用)?(?:的)?(?:是什么|什么|哪种|哪类)(?:材料|材质)"
    r"|(?:的(?:(?:商品|产品)?(?:本体|主体)|[\u4e00-\u9fff]{1,4}体|本身|自身))"
    r"(?:的)?(?:材质|材料)(?:是|为)?(?:什么|哪种|哪类)"
    r"|(?:的)?(?:材质|材料)(?:是|为)?(?:什么|哪种|哪类)"
    r")(?=吗?(?:$|[？?。！!，,；;\s]))"
)

_COLOR_FIELD_REQUEST_PATTERN = re.compile(
    r"(?:"
    r"(?:都|一共)?(?:有|提供|可选)?(?:哪些|什么|哪几种|哪种)颜色"
    r"|颜色(?:有|是|为)?(?:哪些|什么|哪几种|哪种)"
    r")(?=吗?(?:$|[？?。！!，,；;\s]))"
)

_DISHWASHER_FIELD_REQUEST_PATTERN = re.compile(
    r"(?:"
    r"(?:可不可以|能不能|可以|能|可|能否|是否)(?:直接)?"
    r"(?:放(?:进|入|在)?|进|用)?(?:到|在)?洗碗机(?:里|中)?(?:清洗|洗)?"
    r"|洗碗机(?:里|中)?(?:能不能|可不可以|可以|能|可)?(?:清洗|洗|用)"
    r")(?=吗?(?:$|[？?。！!，,；;\s]))"
)

_SELLING_POINT_FIELD_REQUEST_PATTERN = re.compile(
    r"(?:"
    r"(?:有(?:哪些|什么|啥)?|具备(?:哪些|什么|啥)?|(?:最)?(?:核心|主要|关键|突出)(?:的)?)?"
    r"(?:产品)?(?:卖点|特点|特色|优势)"
    r"(?:是什么|有哪些|有(?:哪些|什么|啥)|呢)?"
    r")(?=$|[？?。！!，,；;\s])"
)

_HEAT_SOURCE_PREDICATE_PATTERN = re.compile(
    r"(?:支持|适配|可以用|能用)(?:哪些|什么|哪种|哪类)(?:炉子|炉具|热源)"
    r"(?=吗?(?:$|[？?。！!，,；;\s]))"
)

_HEAT_SOURCE_VALUE_PATTERN = r"(?:电磁炉|卡式炉|燃气炉|燃气灶|电陶炉|酒精炉|明火)"
_HEAT_SOURCE_YES_NO_PREDICATE_PATTERN = re.compile(
    rf"(?:"
    rf"(?:可以|能)(?:直接)?放(?:在)?{_HEAT_SOURCE_VALUE_PATTERN}上(?:用|使用)?吗"
    rf"|(?:可以|能)在{_HEAT_SOURCE_VALUE_PATTERN}上(?:用|使用)吗"
    rf"|(?:可以|能)用{_HEAT_SOURCE_VALUE_PATTERN}吗"
    rf"|(?:支持|适合){_HEAT_SOURCE_VALUE_PATTERN}吗"
    rf"|(?:可以|能)(?:直接)?{_HEAT_SOURCE_VALUE_PATTERN}(?:烧|加热)吗"
    rf")(?=$|[？?。！!，,；;\s])"
)

_HEAT_SOURCE_BARE_YES_NO_PREDICATE_PATTERN = re.compile(
    rf"(?:可以|能)(?:直接)?{_HEAT_SOURCE_VALUE_PATTERN}吗"
    rf"(?=$|[？?。！!，,、\s])"
)

# When semantic planning is unavailable, “can it be heated directly?” is a
# high-precision compatibility predicate, rather than a general usage request.
# This is product-agnostic and still requires a sealed entity plus same-SKU
# heat-source evidence before it can answer.
_HEAT_SOURCE_DIRECT_HEATING_PREDICATE_PATTERN = re.compile(
    r"(?:(?:可以|能|可否)直接|是否(?:可以|能)?直接)加热(?:吗)?(?=$|[？?。！!，,、\s])"
)

_SHIPPING_PREDICATE_PATTERN = re.compile(
    r"(?:"
    r"(?:下单后)?(?:几天|多久|什么时候|何时)(?:内)?(?:能|可以)?(?:发货|发出|寄出)"
    r"|(?:今天|明天|本周|这个周末|周末|近期|最近|现在|当前)(?:能|可以)?送到"
    r")"
    r"(?=吗?(?:$|[？?。！!，,；;\s]))"
)

_DIMENSIONS_QUALIFIED_PREDICATE_PATTERN = re.compile(
    r"(?:产品本体尺寸|具体尺寸|规格尺寸|展开后尺寸|收起后尺寸|收纳尺寸|展开尺寸|"
    r"收起尺寸|包装尺寸|外箱尺寸|包裹尺寸|本体尺寸|产品尺寸|长宽高|直径|尺寸)"
    r"(?:有多大|多大|是多少)"
    r"(?=$|[？?。！!，,；;\s])"
)

_DIMENSIONS_PREDICATE_PATTERN = re.compile(
    r"(?:本身有多大|本身多大|具体尺寸是多少|规格尺寸是多少|长宽高是多少|"
    r"是什么尺寸|尺寸多大|多大尺寸|有多大)"
    r"(?=$|[？?。！!，,；;\s])"
)

# A bare "多大" can describe capacity or a general comparison, so it is not a
# dimensions request on its own.  It becomes an unambiguous physical-size
# request only when the same complete question supplies a storage/fit context.
# This is intentionally product-agnostic and is consulted solely by the
# semantic-service fallback; the normal semantic preplan remains authoritative.
_DIMENSIONS_STORAGE_CONTEXT_PATTERN = re.compile(
    r"(?:到底|究竟|本身)?(?:有)?多大(?=.*(?:收纳|收起|放进|装进|放得下|尺寸|直径|长宽高))"
)

_PURCHASE_CHANNEL_PREDICATE_PATTERN = re.compile(
    r"(?:"
    r"(?:从)?(?:正式)?(?:销售)?渠道(?:购买|下单)?[，,\s]*(?:应该)?(?:去)?(?:哪里|哪儿)"
    r"|(?:应该)?(?:去)?(?:哪里|哪儿)(?:购买|买|下单)"
    r"|(?:在)?(?:哪里|哪儿)(?:可以|能)?(?:购买|买到|买|下单)"
    r"|(?:在)?(?:哪里|哪儿)有售卖"
    r")(?=$|[？?。！!，,；;\s])"
)

def _material_predicate_match(text: str) -> tuple[FieldContract, str, int, bool] | None:
    value = str(text or "")
    matches = [
        match
        for pattern in (_MATERIAL_FIELD_REQUEST_PATTERN, _MATERIAL_PREDICATE_PATTERN)
        if (match := pattern.search(value)) is not None
    ]
    if not matches:
        return None
    match = min(matches, key=lambda item: (item.start(), -len(item.group(0))))
    contract = next(item for item in FIELD_CONTRACTS if item.field_type == "material")
    return contract, match.group(0), match.start(), True


def _canonical_field_predicate_match(
    text: str,
    *,
    field_type: str,
    pattern: re.Pattern[str],
) -> tuple[FieldContract, str, int, bool] | None:
    match = pattern.search(str(text or ""))
    if match is None:
        return None
    contract = next(item for item in FIELD_CONTRACTS if item.field_type == field_type)
    return contract, match.group(0), match.start(), True


def _color_predicate_match(text: str) -> tuple[FieldContract, str, int, bool] | None:
    return _canonical_field_predicate_match(
        text,
        field_type="color",
        pattern=_COLOR_FIELD_REQUEST_PATTERN,
    )


def _dishwasher_predicate_match(text: str) -> tuple[FieldContract, str, int, bool] | None:
    return _canonical_field_predicate_match(
        text,
        field_type="dishwasher",
        pattern=_DISHWASHER_FIELD_REQUEST_PATTERN,
    )


def _selling_point_predicate_match(text: str) -> tuple[FieldContract, str, int, bool] | None:
    return _canonical_field_predicate_match(
        text,
        field_type="selling_point",
        pattern=_SELLING_POINT_FIELD_REQUEST_PATTERN,
    )


def _heat_source_predicate_match(text: str) -> tuple[FieldContract, str, int, bool] | None:
    value = str(text or "")
    matches = [
        match
        for pattern in (
            _HEAT_SOURCE_PREDICATE_PATTERN,
            _HEAT_SOURCE_YES_NO_PREDICATE_PATTERN,
            _HEAT_SOURCE_BARE_YES_NO_PREDICATE_PATTERN,
            _HEAT_SOURCE_DIRECT_HEATING_PREDICATE_PATTERN,
        )
        if (match := pattern.search(value)) is not None
        and not re.match(r"^\s*(?:哪些|哪一些|有哪些|推荐)", value[:match.start()])
    ]
    if not matches:
        return None
    match = sorted(matches, key=lambda item: (-len(item.group(0)), item.start()))[0]
    contract = next(item for item in FIELD_CONTRACTS if item.field_type == "heat_source")
    return contract, match.group(0), match.start(), True


def _shipping_predicate_match(text: str) -> tuple[FieldContract, str, int, bool] | None:
    match = _SHIPPING_PREDICATE_PATTERN.search(str(text or ""))
    if match is None:
        return None
    contract = next(item for item in FIELD_CONTRACTS if item.field_type == "shipping")
    return contract, match.group(0), match.start(), True


def _dimensions_predicate_match(text: str) -> tuple[FieldContract, str, int, bool] | None:
    value = str(text or "")
    match = _DIMENSIONS_QUALIFIED_PREDICATE_PATTERN.search(value)
    if match is None:
        match = _DIMENSIONS_PREDICATE_PATTERN.search(value)
    if match is None:
        match = _DIMENSIONS_STORAGE_CONTEXT_PATTERN.search(value)
    if match is None:
        return None
    contract = next(item for item in FIELD_CONTRACTS if item.field_type == "dimensions")
    return contract, match.group(0), match.start(), True


def _purchase_channel_predicate_match(text: str) -> tuple[FieldContract, str, int, bool] | None:
    return _canonical_field_predicate_match(
        text,
        field_type="purchase_channel",
        pattern=_PURCHASE_CHANNEL_PREDICATE_PATTERN,
    )


def _field_phrase_match(text: str) -> tuple[FieldContract, str, int, bool] | None:
    value = str(text or "")
    candidates: list[tuple[FieldContract, str, int, bool]] = []
    for predicate_matcher in (
        _material_predicate_match,
        _color_predicate_match,
        _dishwasher_predicate_match,
        _selling_point_predicate_match,
        _heat_source_predicate_match,
        _shipping_predicate_match,
        _dimensions_predicate_match,
        _purchase_channel_predicate_match,
    ):
        predicate_match = predicate_matcher(value)
        if predicate_match is not None:
            candidates.append(predicate_match)
    for phrase, contract in iter_full_field_phrases():
        index = value.lower().find(phrase.lower())
        if index >= 0:
            candidates.append((contract, phrase, index, True))
    for alias, contract in iter_field_aliases():
        index = value.lower().find(alias.lower())
        if index >= 0:
            # Model aliases such as ``SKU`` may occur inside the product code
            # itself (for example ``ZX-NO-SKU``).  Such an occurrence is an
            # identity token, not a field predicate; consuming it would
            # truncate the entity subject before central resolution.
            if _span_is_inside_product_code(value, index, index + len(alias)):
                continue
            # A negative composition declaration inside a product title (for
            # example “不含炉配件”) describes the item; it is not the user's
            # requested accessories field.  Let the actual predicate later in
            # the question determine the FieldContract.
            prefix = value[max(0, index - 4):index]
            if contract.field_type in {"accessories", "gift"} and any(marker in prefix for marker in ("不含", "不包括", "无")):
                continue
            candidates.append((contract, alias, index, False))
    if not candidates:
        return None
    # A grammatical predicate is authoritative over an earlier field-looking
    # token inside a product title (for example a product named “…配件” followed
    # by “自身有多重”). Among predicates of equal strength, preserve textual
    # order and prefer the longest span.
    full_predicates = [candidate for candidate in candidates if candidate[3]]
    pool = full_predicates or candidates
    return min(pool, key=lambda item: (item[2], -len(item[1])))


def classify_product_qa_request_type(question: str) -> str:
    contract = detect_field_contract(question)
    if contract is not None:
        # This helper is a legacy QA compatibility classifier.  Keep its
        # historical usage/care bucket while the central resolver consumes the
        # more precise canonical FieldContract types.
        if contract.field_type in {"usage_instruction", "cleaning", "care"}:
            return "usage_care"
        return contract.field_type
    value = str(question or "")
    if any(term in value for term in ("核心卖点", "卖点", "特点", "特色", "优势")):
        return "selling_point"
    if any(term in value for term in ("怎么使用", "如何使用", "使用方法", "怎么用", "如何用", "保养", "清洗", "清洁", "注意事项", "操作")):
        return "usage_care"
    if any(term in value for term in ("使用场景", "适用场景", "适合露营", "适合什么场景")):
        return "usage_scene"
    return "unknown"


def classify_product_qa_evidence_type(question: str, tags: str | None = None) -> str:
    value = f"{str(question or '')} {str(tags or '')}"
    if any(term in value for term in ("核心卖点", "卖点", "特点", "特色", "优势")):
        return "selling_point"
    contract = detect_field_contract(value)
    if contract is not None:
        return contract.field_type
    # The same high-precision compositional concept used when semantic planning
    # is unavailable must classify stored QA evidence before falling back to
    # the legacy usage/care bucket.  Otherwise a formal cleaning request can
    # see same-SKU evidence but incorrectly report it missing.
    composed = deterministic_compositional_field_candidate(question)
    if composed is not None:
        return composed[0]
    if any(term in value for term in ("怎么使用", "如何使用", "使用方法", "怎么用", "如何用", "保养", "清洗", "清洁", "注意事项", "操作", "正常能用")):
        return "usage_care"
    if any(term in value for term in ("使用场景", "适用场景", "适合露营", "适合什么场景")):
        return "usage_scene"
    return "unknown"


def is_qa_evidence_compatible(
    requested_type: str | None,
    evidence_type: str | None,
    *,
    has_semantic_overlap: bool = False,
) -> bool:
    requested = str(requested_type or "unknown").strip() or "unknown"
    evidence = str(evidence_type or "unknown").strip() or "unknown"
    if requested == evidence:
        return True
    if requested == "unknown":
        return bool(has_semantic_overlap)
    return False


def detect_field_contract(text: str) -> FieldContract | None:
    match = _field_phrase_match(text)
    return match[0] if match else None


def field_contract_for_type(field_type: str | None) -> FieldContract | None:
    value = str(field_type or "").strip()
    return next((contract for contract in FIELD_CONTRACTS if contract.field_type == value), None)


def detect_shipping_intent_signal(text: str) -> bool:
    match = _field_phrase_match(text)
    return bool(match and match[0].field_type == "shipping")


def select_entity_subject_for_routing(
    *,
    raw_question: str,
    fallback_product_like_subject: str = "",
    fallback_named_subject: str = "",
) -> EntitySubjectSelection:
    text = str(raw_question or "").strip(" ，。？！；;：:")
    match = _field_phrase_match(text)
    if match is not None:
        contract, phrase, index, is_full_phrase = match
        full_span = (index, index + len(phrase))
        core_match = next(
            (
                (phrase.lower().find(alias.lower()), alias)
                for alias in sorted(contract.aliases, key=len, reverse=True)
                if phrase.lower().find(alias.lower()) >= 0
            ),
            (0, phrase),
        )
        core_index, core_alias = core_match
        core_span = (index + core_index, index + core_index + len(core_alias))
        raw_subject = text[:index].strip(" ，。？！；;：:")
        # Interrogative scaffolding belongs to the predicate, not the product
        # subject (e.g. "商品有什么核心卖点").
        raw_subject = re.sub(r"(?:的|有什么|有)\s*$", "", raw_subject).strip()
        # A locative connector immediately before a purchase-channel
        # interrogative is part of the predicate ("在 + 哪里有售卖"), not the
        # product name.
        if (
            contract.field_type == "purchase_channel"
            and raw_subject.endswith("在")
            and phrase.startswith(("哪里", "哪儿"))
        ):
            raw_subject = raw_subject[:-1].rstrip()
        raw_subject_for_trace = raw_subject
        if phrase == "本身多重":
            raw_subject_for_trace = f"{raw_subject}本身"
        temporal_subject, temporal_span = _strip_trailing_temporal_modifier(raw_subject)
        if temporal_span is not None:
            raw_subject_for_normalization = temporal_subject
        else:
            raw_subject_for_normalization = raw_subject_for_trace
        # The same discourse-only lookup preambles are possible before a
        # field predicate ("帮我查一下…的材质"); remove them before entity
        # arbitration rather than letting a category shortcut consume the
        # remaining product-shaped subject.
        raw_subject_for_normalization = strip_leading_entity_reference_modifier(
            raw_subject_for_normalization
        )
        normalized = normalize_field_adjacent_entity_scope(
            question=text,
            raw_subject=raw_subject_for_normalization,
            canonical_field=contract.field_type,
            field_phrase=phrase,
        )
        reason = normalized.normalization_reason or ("trailing_temporal_modifier" if temporal_span else "field_contract_subject")
        return EntitySubjectSelection(
            entity_subject=normalized.entity_subject,
            source="field_contract",
            field=contract.field_type,
            field_span=full_span,
            raw_subject=raw_subject_for_trace,
            requested_scope=normalized.requested_scope,
            removed_scope_span=normalized.removed_scope_span or temporal_span,
            normalization_reason=normalized.normalization_reason or ("trailing_temporal_modifier" if temporal_span or phrase.startswith(("现在", "当前")) else None),
            fallback_used=False,
            reason=reason if normalized.entity_subject else "field_contract_empty_subject",
            core_field_span=core_span,
            full_field_phrase_span=full_span,
            full_field_phrase=phrase if is_full_phrase else "",
        )

    fallback = str(fallback_product_like_subject or fallback_named_subject or "").strip()
    fallback = strip_leading_entity_reference_modifier(fallback)
    normalized_fallback, removed_temporal_span = _strip_trailing_temporal_modifier(fallback)
    if normalized_fallback:
        fallback = normalized_fallback
    return EntitySubjectSelection(
        entity_subject=fallback,
        source="product_like_fallback" if fallback_product_like_subject else "named_fallback",
        field=None,
        field_span=None,
        raw_subject=fallback,
        requested_scope="subject",
        removed_scope_span=removed_temporal_span,
        normalization_reason="trailing_temporal_modifier" if removed_temporal_span else None,
        fallback_used=bool(fallback),
        reason="field_contract_not_detected" if fallback else "no_entity_subject",
    )


_TRAILING_TEMPORAL_MODIFIER_PATTERN = re.compile(
    r"(?:今天|今日|今晚|现在|目前|当前|近期|最近|这几天|本周|这个周末|周末)$"
)

_LEADING_ENTITY_REFERENCE_MODIFIER_PATTERN = re.compile(
    r"^(?:帮我(?:查(?:一下)?|看(?:看|一下)?)|帮忙(?:查(?:一下)?|看(?:看|一下)?)|"
    r"请(?:查(?:一下)?|看(?:看|一下)?)|查(?:一下)?|(?:我)?(?:刚才)?问错了[，,]?\s*(?:(?:我)?(?:想)?问)?|"
    r"再看(?:看)?|改看(?:看)?|"
    r"看看|看一下|换成|改成|切换到|切到)\s*"
)


def strip_leading_entity_reference_modifier(subject: str) -> str:
    """Remove discourse-only product-switch wording before entity resolution."""
    value = str(subject or "").strip()
    return _LEADING_ENTITY_REFERENCE_MODIFIER_PATTERN.sub("", value).strip()


def _strip_trailing_temporal_modifier(subject: str) -> tuple[str, tuple[int, int] | None]:
    """Separate a trailing time adjunct from a fallback product subject."""
    value = str(subject or "").strip()
    match = _TRAILING_TEMPORAL_MODIFIER_PATTERN.search(value)
    if match is None or match.start() <= 0:
        return value, None
    normalized = value[:match.start()].rstrip(" 的，,：:；;")
    if not normalized:
        return value, None
    return normalized, (match.start(), match.end())


def is_field_contract_predicate_signal(selection: EntitySubjectSelection | None) -> bool:
    return bool(
        selection is not None
        and selection.source == "field_contract"
        and selection.full_field_phrase
        and selection.full_field_phrase_span is not None
        and selection.requested_scope == "subject"
    )


def detect_field_types(text: str) -> tuple[str, ...]:
    value = str(text or "")
    return tuple(
        contract.field_type
        for contract in FIELD_CONTRACTS
        if any(alias in value for alias in contract.aliases)
    )


def semantic_preplan_field_type(field_type: str | None) -> str:
    """Normalize legacy semantic labels into the single formal taxonomy."""
    value = str(field_type or "").strip()
    value = _LEGACY_SEMANTIC_FIELD_ALIASES.get(value, value)
    if value in FORMAL_DETAIL_FIELDS:
        return value
    return value


def deterministic_compositional_field_candidate(question: str) -> tuple[str, str] | None:
    """Return a narrow, product-agnostic formal field for compound meaning.

    This is shared by the semantic preplan and the final FieldContract so an
    optional semantic call can never be a prerequisite for a deterministic
    customer field.  It classifies a field only; identity and evidence remain
    downstream contracts.
    """
    text = re.sub(r"\s+", "", str(question or "").lower())
    if not text:
        return None
    # A grammatical purchase-channel predicate (for example “在哪里有售卖”)
    # is more specific than the broad geographic distribution concept.  Keep
    # the existing formal predicate authoritative before compositional intent
    # classification so “售卖” inside that predicate is not reinterpreted as
    # a sales-region request.
    if _PURCHASE_CHANNEL_PREDICATE_PATTERN.search(text):
        return "purchase_channel", "compositional purchase-channel predicate"
    # An inclusion predicate asks for the product's package composition even
    # when the user omits a noun such as “配件” or “内容物”.  This is a
    # product-agnostic grammatical concept, used only while semantic planning
    # is unavailable; entity resolution and same-SKU evidence remain separate
    # downstream checks.
    if re.search(r"(?:包含|包括|含有)(?:哪些|什么|啥)(?:东西|内容|物|配件)?", text):
        return "accessories", "compositional included-items intent"
    if any(term in text for term in ("价位", "价格", "价钱", "定价", "消费档")) and any(
        term in text for term in ("档", "梯度", "层级", "高端", "中端", "低端", "入门", "亲民")
    ):
        return "price_positioning", "compositional price-tier intent"
    if any(term in text for term in ("几人", "几个人", "多少人", "人数")) and any(
        term in text for term in ("使用", "适用", "供", "建议")
    ):
        return "people", "compositional person-count intent"
    # A named audience is distinct from a numeric serving capacity.  The
    # grammar requires both an audience predicate and an audience noun, so a
    # question such as "适合几个人" remains the separate `people` field above.
    if re.search(r"(?:更)?(?:适合|面向)(?:哪类|哪些|什么)(?:人群|用户|人)", text):
        return "target_audience", "compositional target-audience intent"
    if "洗碗机" in text and any(
        term in text for term in ("能", "可以", "是否", "适配", "放")
    ):
        return "dishwasher", "compositional dishwasher-compatibility intent"
    if any(term in text for term in ("机洗", "洗衣机")) and any(
        term in text for term in ("能", "可以", "是否", "适合", "放")
    ):
        return "cleaning", "compositional laundry-machine-cleaning intent"
    # Temperature-qualified liquid containment is a product-use capability,
    # not a heat-source question.  This is intentionally product-agnostic and
    # only runs during semantic-service fallback; identity and same-SKU
    # evidence remain enforced by the downstream contracts.
    if (
        any(term in text for term in ("冷水", "热水", "开水", "沸水"))
        and any(term in text for term in ("装", "盛", "灌", "倒入"))
        and any(term in text for term in ("能", "可以", "可否", "能否", "是否", "适合"))
    ):
        return "usage_instruction", "compositional liquid-temperature capability intent"
    if any(term in text for term in ("养护", "保养", "维护")):
        return "care", "compositional care intent"
    if any(term in text for term in ("功率", "瓦数", "多少瓦")) or re.search(r"\d+\s*w\b", text):
        return "power", "compositional power-rating intent"
    # Rinsing is a concrete cleaning operation.  Keep this deliberately at
    # the field-concept layer (rather than an SKU, title, or question
    # shortcut) so the semantic-service outage fallback still forms the same
    # formal cleaning contract before any legacy compatibility route can run.
    if any(term in text for term in ("清洗", "清洁", "打理", "洗净", "洗干净", "冲洗", "漂洗", "刷洗", "擦洗")):
        return "cleaning", "compositional cleaning intent"
    if any(term in text for term in ("操作步骤", "正确用法", "上手")):
        return "usage_instruction", "compositional usage-instruction intent"
    if any(term in text for term in ("炉", "热源")) and any(
        term in text for term in ("适配", "支持", "能上", "能用", "可用")
    ):
        return "heat_source", "compositional heat-source-compatibility intent"
    if ("分级" in text or "等级" in text) or re.search(r"[abc]类|[abc]级", text, flags=re.IGNORECASE):
        return "product_level", "compositional product-level intent"
    if (
        any(term in text for term in ("投放", "覆盖", "供应", "销往", "面向", "销售", "售卖"))
        and any(term in text for term in ("市场", "地区", "区域", "地域", "国家", "国内", "海外", "哪里", "哪儿", "哪些地方"))
        and not any(term in text for term in ("平台", "渠道", "店铺", "门店", "下单", "购买"))
    ):
        return "sales_region", "compositional geographic-distribution intent"
    return None


def deterministic_compositional_field_candidates(question: str) -> list[tuple[str, str]]:
    """Return independent fallback field concepts present in one question.

    Semantic preplanning remains the primary semantic authority.  This helper
    is used only if that service is unavailable, where a deterministic alias
    must not hide a second, independently expressed field in a compound
    request.  It deliberately adds only the audience grammar that is not a
    numeric people-capacity question; all identity and evidence checks remain
    downstream.
    """
    candidates: list[tuple[str, str]] = []
    primary = deterministic_compositional_field_candidate(question)
    if primary is not None:
        candidates.append(primary)

    text = re.sub(r"\s+", "", str(question or "").lower())
    if re.search(r"(?:更)?(?:适合|面向)(?:哪类|哪些|什么)(?:人群|用户|人)", text):
        candidates.append(("target_audience", "compositional target-audience intent"))

    return list(dict.fromkeys(candidates))


def field_contract_metadata(text: str) -> dict[str, str | None]:
    contract = detect_field_contract(text)
    field_type = contract.field_type if contract else None
    return {
        "contract_field_type": field_type,
        "planner_compatible_field_type": semantic_preplan_field_type(field_type),
    }


def product_detail_field_label(field_type: str | None) -> str | None:
    return DETAIL_FIELD_LABELS.get(str(field_type or "").strip())


def resolve_requested_field_contract(
    question: str,
    planner_plan: dict[str, Any] | None = None,
    *,
    compatibility_fields: Iterable[str] = (),
    subject: str = "",
    requested_scope: str = "subject",
    subject_is_catalog_exact: bool = False,
) -> dict[str, Any]:
    """Resolve one formal field contract from deterministic or validated semantic input."""
    text = str(question or "")
    plan = planner_plan if isinstance(planner_plan, dict) else {}
    normalized_subject = str(subject or "").strip()
    if not normalized_subject:
        # Field aliases embedded in a resolved product subject (for example a
        # product name containing a heat-source word) describe identity, not
        # the field the customer is asking for.  Reuse the central subject
        # extractor before collecting aliases so those identity tokens cannot
        # manufacture a second, conflicting FieldContract.
        normalized_subject = select_entity_subject_for_routing(
            raw_question=text,
        ).entity_subject
    subject_start = text.find(normalized_subject) if normalized_subject else -1
    subject_span = (
        (subject_start, subject_start + len(normalized_subject))
        if subject_start >= 0
        else None
    )

    def inside_subject(start: int, end: int) -> bool:
        return bool(
            subject_span is not None
            and start >= subject_span[0]
            and end <= subject_span[1]
        )

    requested_fields = list(dict.fromkeys(
        str(field or "").strip()
        for field in compatibility_fields
        if str(field or "").strip()
    ))
    phrase_match = _field_phrase_match(text)
    phrase_contract = phrase_match[0] if phrase_match else None

    field_spans: list[dict[str, Any]] = []
    if phrase_match is not None:
        phrase_contract, phrase, start, _ = phrase_match
        end = start + len(phrase)
        if not inside_subject(start, end):
            field_spans.append({
                "field_type": phrase_contract.field_type,
                "alias": phrase,
                "start": start,
                "end": end,
            })
    for alias, contract in iter_field_aliases():
        for alias_match in re.finditer(re.escape(alias), text, flags=re.IGNORECASE):
            start, end = alias_match.span()
            if inside_subject(start, end):
                continue
            field_spans.append({
                "field_type": contract.field_type,
                "alias": alias_match.group(0),
                "start": start,
                "end": end,
            })
    if phrase_match is not None:
        selected_contract, selected_phrase, selected_start, _ = phrase_match
        selected_end = selected_start + len(selected_phrase)
        # A stable grammatical predicate is one field, even when it contains
        # the token of another field (for example "价格定位" contains "价格").
        # Nested aliases cannot manufacture a compound request.
        field_spans = [
            item
            for item in field_spans
            if not (
                item.get("field_type") != selected_contract.field_type
                and int(item.get("start") or 0) >= selected_start
                and int(item.get("end") or 0) <= selected_end
            )
        ]
    field_spans.sort(key=lambda item: (item["start"], -(item["end"] - item["start"])))

    span_field_types = list(dict.fromkeys(
        str(item.get("field_type") or "").strip()
        for item in field_spans
        if str(item.get("field_type") or "").strip()
    ))
    if (
        phrase_match is not None
        and requested_fields
        and not inside_subject(
            phrase_match[2],
            phrase_match[2] + len(phrase_match[1]),
        )
    ):
        # Legacy compatibility extraction can independently emit a nested
        # field label ("价格") from a stronger grammatical field predicate
        # ("价格定位"). Retain compatibility labels only when their canonical
        # field also has an independent surviving span; unknown legacy labels
        # remain available to the compatibility layer.
        requested_fields = [
            label
            for label in requested_fields
            if not (field_type_from_detail_label(label) or "")
            or field_type_from_detail_label(label) in span_field_types
        ]
    if not requested_fields:
        requested_fields = [
            label
            for field_type in span_field_types
            if (label := product_detail_field_label(field_type))
        ]

    canonical_fields = list(dict.fromkeys(
        field_type
        for field in requested_fields
        if (field_type := field_type_from_detail_label(field))
    ))
    for field_type in span_field_types:
        if field_type not in canonical_fields:
            canonical_fields.append(field_type)

    # A semantic plan interprets natural language, but it cannot relabel an
    # explicit, formal FieldContract label into a different field.  Restrict
    # this constraint to the displayed canonical label or a full grammatical
    # predicate: broad aliases such as "特点" remain semantic territory.
    explicit_phrase_match = _field_phrase_match(question)
    explicit_phrase_field_type = (
        explicit_phrase_match[0].field_type
        if explicit_phrase_match is not None
        else None
    )
    # Bare size wording is intentionally only an outage fallback. In a phrase
    # such as "rated output is how large", the trailing "how large" span is not
    # a reliable dimensions predicate and must not overrule a high-confidence
    # semantic ``power`` decision made from the complete sentence.
    weak_semantic_fallback_predicate = bool(
        explicit_phrase_match is not None
        and explicit_phrase_field_type == "dimensions"
        and str(explicit_phrase_match[1] or "").strip() in {"有多大"}
    )
    explicit_canonical_label = product_detail_field_label(explicit_phrase_field_type)
    explicit_label_is_stated = bool(
        explicit_canonical_label
        and explicit_phrase_match is not None
        and explicit_canonical_label in str(explicit_phrase_match[1] or "")
    )
    explicit_contract_fields = list(dict.fromkeys(
        str(item.get("field_type") or "").strip()
        for item in field_spans
        if (
            explicit_phrase_match is not None
            and explicit_phrase_match[3]
            and not weak_semantic_fallback_predicate
            # A generic predicate such as "有什么优势" overlaps the formal
            # technical-advantages label but is not itself an explicit
            # customer declaration of the selling-point field.  A validated
            # semantic plan remains authoritative for that sentence-level
            # distinction.  Deterministic conflict protection is retained
            # only when the customer actually states the canonical field
            # label (for example "技术优势" or "价格定位").
            and explicit_label_is_stated
            and explicit_phrase_field_type == str(item.get("field_type") or "").strip()
        )
    ))

    semantic_field, semantic_confidence = _validated_semantic_field_candidate(
        plan.get("semantic_preplan"),
        question=question,
        trusted_subject=subject_is_catalog_exact,
    )
    validated_semantic_fields, semantic_fields_confidence = _validated_semantic_field_candidates(
        plan.get("semantic_preplan"),
        trusted_subject=subject_is_catalog_exact,
    )
    semantic_confidence = max(semantic_confidence, semantic_fields_confidence)
    semantic_adapter_source = (
        str((plan.get("semantic_preplan") or {}).get("semantic_adapter_source") or "").strip()
        if isinstance(plan.get("semantic_preplan"), dict)
        else ""
    )
    semantic_fields = validated_semantic_fields
    semantic_called = bool(isinstance(plan.get("semantic_preplan"), dict) and plan["semantic_preplan"].get("called"))
    try:
        semantic_product_qa_confidence = float(
            (plan.get("semantic_preplan") or {}).get("confidence") or 0.0
        )
    except (TypeError, ValueError):
        semantic_product_qa_confidence = 0.0
    semantic_product_qa = bool(
        semantic_called
        and isinstance(plan.get("semantic_preplan"), dict)
        and str(plan["semantic_preplan"].get("route_family") or "").strip() == "product_bound_qa"
        and str(plan["semantic_preplan"].get("evidence_kind") or "").strip() == "product_qa"
        and not str(plan["semantic_preplan"].get("fallback_reason") or "").strip()
        and semantic_product_qa_confidence >= 0.9
    )
    # A valid semantic product-QA decision owns the distinction between a
    # structured field and a product-specific capability/judgement.  Do not
    # let aliases in the product name or question recreate a formal field;
    # downstream code still has to form EntityResolutionContract and find
    # same-SKU QA evidence before it can answer.
    if semantic_product_qa:
        return {
            "field_type": None,
            "requested_field": None,
            "requested_fields": [],
            "field_spans": field_spans,
            "canonical_fields": [],
            "supported_fields": [],
            "unsupported_fields": [],
            "subject": str(subject or "").strip(),
            "requested_scope": str(requested_scope or "subject").strip() or "subject",
            "source": "validated_semantic_product_qa",
            "confidence": semantic_product_qa_confidence,
            "compound": False,
        }
    semantic_valid = bool(semantic_called and (semantic_fields or semantic_field) and semantic_confidence >= 0.5)
    semantic_candidate_fields = semantic_fields or ([semantic_field] if semantic_field else [])
    explicit_semantic_conflict = bool(
        explicit_contract_fields
        and semantic_valid
        and not set(explicit_contract_fields).issubset(set(semantic_candidate_fields))
    )
    # Compositional classification is an unavailable-semantic fallback.  A
    # deterministic alias that already found one field must not erase a
    # separately expressed fallback field in the same customer request.
    # Conversely, a valid semantic plan remains authoritative and is never
    # supplemented or overwritten here.
    canonical_fields_before_compositional = list(canonical_fields)
    compositional_candidates = (
        deterministic_compositional_field_candidates(question)
        if not semantic_valid
        else []
    )
    if compositional_candidates:
        for compositional_field, _reason in compositional_candidates:
            if compositional_field not in canonical_fields:
                canonical_fields.append(compositional_field)
                label = product_detail_field_label(compositional_field)
                if label and label not in requested_fields:
                    requested_fields.append(label)
        if not semantic_field:
            semantic_field, _reason = compositional_candidates[0]
            semantic_confidence = 0.9
            semantic_adapter_source = "deterministic_compositional_field"

    source = "safe_fallback"
    confidence = 0.0
    if semantic_candidate_fields and semantic_confidence >= 0.9 and not explicit_semantic_conflict and (
        semantic_valid or not canonical_fields_before_compositional
    ):
        # Semantic preplan is the primary field interpreter. Once its
        # allowlisted schema and confidence checks have passed, a lexical
        # alias or compositional matcher cannot replace it. Those matchers
        # remain available below only when semantic planning is unavailable
        # or fails validation. Identity and evidence remain deterministic
        # downstream contracts.
        canonical_fields = semantic_candidate_fields
        requested_fields = [product_detail_field_label(field) for field in canonical_fields if product_detail_field_label(field)]
        source = "validated_semantic_preplan"
        confidence = semantic_confidence
    elif canonical_fields:
        source = (
            "explicit_contract_semantic_conflict"
            if explicit_semantic_conflict
            else "deterministic_full_predicate"
            if phrase_match is not None and phrase_match[3]
            else "deterministic_alias"
            if phrase_match is not None
            else "legacy_requested_fields"
        )
        confidence = 1.0
    else:
        if semantic_field:
            canonical_fields = [semantic_field]
            semantic_label = product_detail_field_label(semantic_field)
            requested_fields = [semantic_label] if semantic_label else []
            source = "validated_semantic_preplan"
            confidence = semantic_confidence

    # Component words refine evidence scope only after the primary semantic or
    # deterministic contract has already selected material.  A lid request
    # must never inherit a general body-material value, and a body+lid request
    # remains one canonical field with two independently validated answers.
    if "material" in canonical_fields:
        component_requests = material_component_detail_requests(question)
        if component_requests:
            # Keep every independently requested canonical field (for
            # example dishwasher) while replacing only material's generic
            # display label with the evidence scope the customer named.
            requested_fields = [
                label
                for label in requested_fields
                if field_type_from_detail_label(label) != "material"
            ]
            requested_fields = [*component_requests, *requested_fields]

    supported_fields = [field for field in canonical_fields if is_supported_detail_field(field)]
    unsupported_fields = [field for field in canonical_fields if not is_supported_detail_field(field)]
    field_type = canonical_fields[0] if len(canonical_fields) == 1 else None
    requested_field = (
        product_detail_field_label(field_type)
        if field_type
        else str(plan.get("requested_field") or "").strip() or (requested_fields[0] if requested_fields else None)
    )
    return {
        "field_type": field_type,
        "requested_field": requested_field,
        "requested_fields": requested_fields,
        "field_spans": field_spans,
        "canonical_fields": canonical_fields,
        "supported_fields": supported_fields,
        "unsupported_fields": unsupported_fields,
        "subject": str(subject or "").strip(),
        "requested_scope": str(requested_scope or "subject").strip() or "subject",
        "source": source,
        "confidence": confidence,
        "compound": bool(
            plan.get("compound")
            or plan.get("routing_conflict")
            or plan.get("multi_field")
            or len(requested_fields) > 1
        ),
    }


_SEMANTIC_FIELD_ADAPTER_RULES: dict[str, dict[str, frozenset[Any]]] = {
    "contents": {
        "canonical_fields": frozenset({"accessories"}),
        "shapes": frozenset({
            ("contents_accessories", "contents_accessories", "composition"),
            ("contents_accessories", "contents_accessories", "contents_accessories"),
            # Current semantic-preplan schema expresses an explicit product's
            # included-items question as a normal product-bound field request.
            ("product_bound_qa", "field", "known_detail"),
        }),
    },
    "gift": {
        "canonical_fields": frozenset({"gift"}),
        "shapes": frozenset({("product_bound_qa", "field", "known_detail")}),
    },
}
_SEMANTIC_PRODUCT_FIELD_SCOPES = frozenset({
    "product_like",
    "resolved_product",
    "ambiguous_product",
    "unresolved_product",
    "resolved_single",
    "unique_product_name",
    "ambiguous_product_name",
    "unresolved_product_like",
})
_SEMANTIC_IDENTITY_OR_ANSWER_KEYS = frozenset({
    "answer",
    "final_answer",
    "resolved_sku",
    "candidate_skus",
    "recommended_skus",
    "result_skus",
    "sku",
    "skus",
})


def _validated_semantic_field_candidate(
    preplan: Any,
    *,
    question: str,
    trusted_subject: bool = False,
) -> tuple[str | None, float]:
    """Map a schema-validated semantic field hint without accepting identity data."""
    if not isinstance(preplan, dict) or not preplan.get("called") or preplan.get("fallback_reason"):
        return None, 0.0
    if any(key in preplan for key in _SEMANTIC_IDENTITY_OR_ANSWER_KEYS):
        return None, 0.0
    try:
        confidence = float(preplan.get("confidence") or 0.0)
    except (TypeError, ValueError):
        return None, 0.0
    if confidence < 0.90 or confidence > 1.0:
        return None, 0.0
    semantic_shape = (
        str(preplan.get("route_family") or "").strip(),
        str(preplan.get("question_type") or "").strip(),
        str(preplan.get("subtype") or "").strip(),
    )
    pairwise_recommendation_adapter = bool(
        preplan.get("semantic_adapter_source") == "validated_pairwise_recommendation_constraints"
        and semantic_shape[0] == "recommendation"
        and len(preplan.get("entities") or []) >= 2
        and preplan.get("recommendation_constraint_grounding") == "validated_semantic_grounding"
    )
    comparison_shape = semantic_shape == ("comparison", "comparison", "relation_comparison")
    field_type = str(preplan.get("field_type") or preplan.get("field_hint") or "").strip()
    field_hint = str(preplan.get("field_hint") or field_type).strip()
    # DeepSeek may preserve a broad catalogue-query route shape while its
    # structured field output is both high-confidence and formally allowed.
    # This remains field-only semantic input: it neither grants an identity
    # nor answers from the catalogue.  EntityResolutionContract still has to
    # resolve one product (or fail closed) before any evidence is consumed.
    structured_subject = str(preplan.get("subject_text") or "").strip()
    structured_constraints = preplan.get("structured_query_constraints")
    # A high-confidence field predicate with a textual subject is sometimes
    # emitted in the structured-query envelope even though it has no filter
    # object at all.  That envelope is not an identity or evidence grant: the
    # field can safely enter the central contract and EntityResolutionContract
    # will still either seal exactly one product or return an ambiguity.
    # Keeping this narrow to an *empty* validated constraint list preserves
    # real catalogue filtering, whose predicate objects remain structured.
    subject_bound_empty_structured_shape = bool(
        structured_subject
        and isinstance(structured_constraints, list)
        and not structured_constraints
    )
    structured_formal_field_shape = bool(
        field_type in FORMAL_DETAIL_FIELDS
        and semantic_shape == ("structured_query", "filter", "structured_query")
        and str(preplan.get("route_hint") or "").strip() == "query_products"
        # ``evidence_required`` is a planner-side route diagnostic, not
        # evidence authorization.  For a catalog-exact subject, the formal
        # field still goes through EntityResolutionContract and the same-SKU
        # evidence provider even when the model omitted that diagnostic flag.
        and (
            bool(preplan.get("evidence_required"))
            or trusted_subject
            or subject_bound_empty_structured_shape
        )
    )
    allowed_route_hints = (
        {"product_detail", "comparison"} if comparison_shape else {"recommendation"} if pairwise_recommendation_adapter else {"product_detail"}
    )
    # A semantic preplan can classify a named product's requested field
    # correctly while retaining a broad structured-query route hint.  Once
    # the subject span is independently catalog-exact, that legacy-shaped
    # route hint must not discard the formal field contract; entity and
    # evidence checks still run downstream.  Generic category/filter scopes
    # do not receive this exception because trusted_subject remains false.
    if trusted_subject and not comparison_shape and not pairwise_recommendation_adapter:
        allowed_route_hints = {"product_detail", "structured_query"}
    if structured_formal_field_shape:
        allowed_route_hints = {"query_products"}
    if str(preplan.get("route_hint") or "").strip() not in allowed_route_hints:
        return None, 0.0
    entity_scope = str(preplan.get("entity_scope") or "").strip()
    # Entity scope is useful diagnostic context only.  Requiring the semantic
    # model to classify identity scope would make a valid field-only preplan
    # fail closed before EntityResolutionContract can independently resolve
    # the product from the question and conversation anchor.
    if entity_scope and entity_scope not in _SEMANTIC_PRODUCT_FIELD_SCOPES and not trusted_subject:
        return None, 0.0

    if not field_type or field_hint != field_type:
        return None, 0.0
    rule = _SEMANTIC_FIELD_ADAPTER_RULES.get(field_type)
    # The semantic layer classifies a field concept only.  Every formally
    # supported contract may use the same narrow, schema-validated detail
    # shape; deterministic validation and EntityResolution still decide
    # whether a product can be answered.  This avoids growing a catalogue of
    # natural-language phrases for each field.
    if (comparison_shape or pairwise_recommendation_adapter) and field_type in FORMAL_DETAIL_FIELDS:
        # The comparison preplan has already supplied the participant spans;
        # it uses the same formal field taxonomy as a single-product fact.
        # Entity contracts and evidence validation remain downstream.
        return field_type, confidence
    if rule is None and field_type in FORMAL_DETAIL_FIELDS:
        rule = {
            "canonical_fields": frozenset({field_type}),
            "shapes": frozenset({("product_bound_qa", "field", "known_detail")}),
        }
    if not rule:
        return None, 0.0
    if semantic_shape not in rule["shapes"] and not structured_formal_field_shape:
        return None, 0.0
    # A high-confidence, schema-valid semantic field is the sole authority
    # for *what* the customer is asking.  Legacy usage/care classification is
    # allowed to select same-SKU evidence after the FieldContract exists, but
    # it must not veto or relabel that field intent.  Otherwise a phrase such
    # as a cleaning request is silently routed by word matching even when the
    # semantic preplan has already emitted the formal canonical field.
    return next(iter(rule["canonical_fields"])), confidence


def _validated_semantic_field_candidates(
    preplan: Any,
    *,
    trusted_subject: bool = False,
) -> tuple[list[str], float]:
    """Validate a structured multi-field semantic result without accepting facts."""
    if not isinstance(preplan, dict) or not preplan.get("called") or preplan.get("fallback_reason"):
        return [], 0.0
    if any(key in preplan for key in _SEMANTIC_IDENTITY_OR_ANSWER_KEYS):
        return [], 0.0
    try:
        confidence = float(preplan.get("confidence") or 0.0)
    except (TypeError, ValueError):
        return [], 0.0
    if confidence < 0.90 or confidence > 1.0:
        return [], 0.0
    route_hint = str(preplan.get("route_hint") or "").strip()
    entity_scope = str(preplan.get("entity_scope") or "").strip()
    if entity_scope and entity_scope not in _SEMANTIC_PRODUCT_FIELD_SCOPES and not trusted_subject:
        return [], 0.0
    semantic_shape = (
        str(preplan.get("route_family") or "").strip(),
        str(preplan.get("question_type") or "").strip(),
        str(preplan.get("subtype") or "").strip(),
    )
    pairwise_recommendation_adapter = bool(
        preplan.get("semantic_adapter_source") == "validated_pairwise_recommendation_constraints"
        and semantic_shape[0] == "recommendation"
        and len(preplan.get("entities") or []) >= 2
        and preplan.get("recommendation_constraint_grounding") == "validated_semantic_grounding"
    )
    allowed_shapes = {
        ("product_bound_qa", "field", "known_detail"),
        ("comparison", "comparison", "relation_comparison"),
    }
    if (semantic_shape not in allowed_shapes and not pairwise_recommendation_adapter) or route_hint != (
        "comparison" if semantic_shape[0] == "comparison" else "product_detail"
    ) and not pairwise_recommendation_adapter:
        return [], 0.0
    fields = list(dict.fromkeys(
        semantic_preplan_field_type(item)
        for item in (preplan.get("canonical_fields") or [])
        if semantic_preplan_field_type(item) in FORMAL_DETAIL_FIELDS
    ))
    if len(fields) < 2:
        return [], 0.0
    # A multi-field plan has no single primary field. If compatibility mirrors
    # are present, they may only repeat one member of the validated set.
    field_type = semantic_preplan_field_type(preplan.get("field_type"))
    field_hint = semantic_preplan_field_type(preplan.get("field_hint"))
    if field_type and field_type not in fields:
        return [], 0.0
    if field_hint and field_hint not in fields:
        return [], 0.0
    return fields, confidence
