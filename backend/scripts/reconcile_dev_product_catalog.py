"""Reconcile verified product facts and add a small historical-QA supplement.

This is intentionally a development-only maintenance script.  The values in
the correction ledger were compared with the primary product metadata workbook
at ``C:\\Users\\wnt\\Desktop\\产品数据和qa库\\产品库元数据.xlsx``.  The script does
not import the workbook wholesale: several workbook/QA-template cells are
conflicting or clearly copied from another product, so every write has an old
value assertion and is idempotent.

The QA supplement is made from natural questions observed in
``D:\\CaiYan\\aiCS``.  Answers contain only same-SKU facts or explicit usage
instructions; no promotional or inferred burden/safety claims are added.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import sys
from decimal import Decimal
from pathlib import Path
from typing import Any

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.config import database_name_from_url, settings
from app.core.database import SessionLocal, engine
from app.models.product import Product
from app.models.product_business import ProductBusiness
from app.models.product_qa import ProductQa
from app.models.product_specs import ProductSpecs
from app.models.user import User
from app.services import product_qa_integrity_service, product_service

# The dev env enables SQL echo for the running server.  Maintenance output is
# a fact/audit ledger, so keep SQL bind logs out of it (the engine remains the
# same dev-only engine).
engine.echo = False


SOURCE_METADATA = r"C:\Users\wnt\Desktop\产品数据和qa库\产品库元数据.xlsx"
SOURCE_HISTORY = r"D:\CaiYan\aiCS"


# These are exact old-value -> verified new-value replacements.  C76/C96-B/
# C97 deliberately use 0.8L: the primary capacity field says 0.8L, while an
# older QA template says 1.4L.  Capacity is the formal same-SKU field and wins
# over that copied selling-point text.
CAPACITY_CORRECTIONS: dict[str, tuple[tuple[str, str], ...]] = {
    "CW-K11-37": (("3L", "1.3L"),),
    "CW-C72": (("7L", "1.7L"),),
    "CW-C99B": (("7L", "1.7L"),),
    "CW-RT05": (("3L", "1.3L"),),
    "CW-C47-37": (
        ("2L", "2.2L"),
        ("4L", "1.4L"),
        ("8L", "0.8L"),
        ("5寸", "7.5寸"),
    ),
    "CW-K03": (("4L", "1.4L"),),
    "CW-C82": (("4L", "1.4L"),),
    "CW-C84": (("4L", "1.4L"),),
    "CW-C85-A": (("5L", "3.5L"),),
    "CW-K32": (("3L", "2.3L"),),
    "CW-C76": (("8L", "0.8L"),),
    "CW-C96-B": (("8L", "0.8L"),),
}


SELLING_POINT_CORRECTIONS: dict[str, tuple[str, str]] = {
    "CW-K03": ("4L 双人容量", "1.4L 双人容量"),
    "CW-K03-37": ("4L 双人容量", "1.4L 双人容量"),
    "CW-C84": ("4L 双人容量", "1.4L 双人容量"),
    "CW-C76": ("4L 双人容量", "0.8L 双人容量"),
    "CW-C96-B": ("4L 双人容量", "0.8L 双人容量"),
    "CW-C97": ("4L 双人容量", "0.8L 双人容量"),
    "CB253": ("4L 双人容量", "1.4L 双人容量"),
    "CW-C90": ("5 寸小巧尺寸", "7.5 寸小巧尺寸"),
    "CW-PF05": ("5 寸尺寸", "7.5 寸尺寸"),
    # The same SKU is a highland-canister stove in its title, heat-source
    # field, usage steps and technical advantages.  "No canister needed" was
    # a copied selling-point fragment and inverted the product's fuel fact.
    "CS-G35": ("无需气罐", "适配高山气罐"),
}


WEIGHT_CORRECTIONS: dict[str, tuple[Decimal, Decimal]] = {
    # Excel stores this cell as the text "1.74kg" although the column is g.
    "AC-Z14": (Decimal("1.74"), Decimal("1740")),
}


# The historical marketplace product image for AC-Z13 labels the individual
# powder jar as 3.8x3.8x9.5cm and the storage bag as 14x8.5x15cm.  The imported
# row duplicated the bag dimensions into the powder-jar field.  Keep this as an
# exact old-value assertion so a later catalogue update is never overwritten.
SIZE_INFO_CORRECTIONS: dict[str, tuple[tuple[str, str, str], ...]] = {
    "AC-Z13": (("粉罐", "14x8.5x15", "3.8x3.8x9.5"),),
}


# Existing customer-visible answers that would remain misleading after the
# field repair.  Each entry is guarded by its exact old answer so a manual
# edit made after this ledger was authored is never overwritten.
QA_ANSWER_CORRECTIONS: tuple[dict[str, str], ...] = (
    {
        "sku": "CW-K03",
        "question": "1.4L野营水壶（星空辉）有多重？",
        "old_answer": "1.4L野营水壶（星空辉）净重约318g，非常轻便，轻松放入背包。",
        "new_answer": "1.4L野营水壶（星空辉）净重约195g。",
    },
    {
        "sku": "CW-C76",
        "question": "享野水壶有什么核心卖点？",
        "old_answer": "享野水壶的核心卖点包括：高性价比、1.4L 双人容量、快速沸腾、硬质氧化工艺。",
        "new_answer": "享野水壶的核心卖点包括：高性价比、0.8L 容量、快速沸腾、硬质氧化工艺。",
    },
    {
        "sku": "CW-C96-B",
        "question": "京享水壶有什么核心卖点？",
        "old_answer": "京享水壶的核心卖点包括：高性价比、1.4L 双人容量、快速沸腾、硬质氧化工艺。",
        "new_answer": "京享水壶的核心卖点包括：高性价比、0.8L 容量、快速沸腾、硬质氧化工艺。",
    },
    {
        "sku": "CW-C97",
        "question": "京澜水壶（京东自营）有什么核心卖点？",
        "old_answer": "京澜水壶（京东自营）的核心卖点包括：京东自营、高性价比、1.4L 双人容量、快速沸腾。",
        "new_answer": "京澜水壶（京东自营）的核心卖点包括：京东自营、高性价比、0.8L 容量、快速沸腾。",
    },
    {
        "sku": "CW-C78",
        "question": "享野套锅有多重？",
        "old_answer": "享野套锅重量约1.32kg（含包装），户外携带无负担。",
        "new_answer": "享野套锅毛重约1320g（约1.32kg）。",
    },
    {
        "sku": "CW-C93",
        "question": "行山单锅有没有不粘涂层？",
        "old_answer": "有。表面处理资料标注为硬质氧化和陶瓷不沾。",
        "new_answer": "资料标注表面处理包含硬质氧化和陶瓷不沾；可以确认有陶瓷不沾表面处理，但资料没有单独说明涂层结构，不能把硬质氧化直接等同为涂层。",
    },
    {
        "sku": "CW-K03-37",
        "question": "1.4升户外水壶第一次使用要注意什么？",
        "old_answer": "首次使用前用温水和软布冲洗即可（无需洗洁精）。烹饪前中小火预热2-3分钟，再倒油使用效果更佳。",
        "new_answer": "首次使用前用温水和软布冲洗即可（无需洗洁精）。烹饪前将水壶置于灶具上，用中小火预热2-3分钟。",
    },
    {
        "sku": "CW-K03-37",
        "question": "1.4升户外水壶兼容哪些炉具？",
        "old_answer": "1.4升户外水壶兼容酒精炉 燃气炉等多种热源，户外家用一锅搞定。",
        "new_answer": "适用明火直烧、卡式炉、分体炉和一体炉。",
    },
    {
        "sku": "CW-K03-37",
        "question": "1.4升户外水壶有哪些颜色？",
        "old_answer": "1.4升户外水壶颜色为氧化铝本色。",
        "new_answer": "1.4升户外水壶主色系为锖色。",
    },
    {
        "sku": "CW-RT05",
        "question": "有喜锅有多重？",
        "old_answer": "有喜锅重量约1.02kg（含包装），户外携带无负担。",
        "new_answer": "有喜锅毛重约1020g（约1.02kg）。",
    },
    {
        "sku": "CW-C47-37",
        "question": "荒野3-4人自驾套装有多重？",
        "old_answer": "荒野3-4人自驾套装重量约2.45kg（含包装），户外携带无负担。",
        "new_answer": "荒野3-4人自驾套装毛重约2450g（约2.45kg）。",
    },
    {
        "sku": "CW-C05-37",
        "question": "2-4人野餐锅10件套有多重？",
        "old_answer": "2-4人野餐锅10件套重量约1.03kg（含包装），户外携带无负担。",
        "new_answer": "2-4人野餐锅10件套毛重约1030g（约1.03kg）。",
    },
    {
        "sku": "AC-Z13",
        "question": "拾野·便携调料瓶套装的尺寸是多少？",
        "old_answer": "套装包：15x14x8.5cm 液体瓶：φ4x13.7cm 粉罐：14x8.5x15cm。",
        "new_answer": "套装包约15×14×8.5cm，液体瓶约φ4×13.7cm，粉罐约3.8×3.8×9.5cm。",
    },
    {
        "sku": "AC-Z13",
        "question": "拾野·便携调料瓶套装有多重？",
        "old_answer": "拾野·便携调料瓶套装净重约200g，非常轻便，轻松放入背包。",
        "new_answer": "重量资料标注约200g。",
    },
    {
        "sku": "CS-G35",
        "question": "小圆炉有什么核心卖点？",
        "old_answer": "小圆炉的核心卖点包括：极致小巧、无需气罐、操作简单、稳定燃烧。",
        "new_answer": "小圆炉的核心卖点包括：极致小巧、适配高山气罐、操作简单、稳定燃烧。",
    },
    {
        "sku": "CS-G35",
        "question": "小圆炉有多重？",
        "old_answer": "小圆炉净重约320g，非常轻便，轻松放入背包。",
        "new_answer": "小圆炉重量资料标注约320g。",
    },
    {
        "sku": "CS-G35",
        "question": "小圆炉有哪些颜色？",
        "old_answer": "小圆炉颜色为氧化铝本色、黑色。",
        "new_answer": "小圆炉主色系资料标注为锖色、黑色。",
    },
    {
        "sku": "CW-C65",
        "question": "城市出逃套锅有哪些颜色？",
        "old_answer": "城市出逃套锅颜色为氧化铝本色。",
        "new_answer": "城市出逃套锅主色系资料标注为锖色。",
    },
    {
        "sku": "CW-C65",
        "question": "城市出逃套锅有多重？",
        "old_answer": "城市出逃套锅重量约1.84kg（含包装），户外携带无负担。",
        "new_answer": "城市出逃套锅毛重约1837g（约1.84kg）。",
    },
    {
        "sku": "KD23-MFL",
        "question": "魔盒卡式炉（不含拓展板）有多重？",
        "old_answer": "魔盒卡式炉（不含拓展板）重量约1.50kg（含包装），户外携带无负担。",
        "new_answer": "魔盒卡式炉（不含拓展板）毛重约1500g（约1.50kg）。",
    },
    {
        "sku": "GA01-37",
        "question": "户外气炉转卡式气罐转接头（通用于爱路客气炉且使用长罐）有多重？",
        "old_answer": "户外气炉转卡式气罐转接头（通用于爱路客气炉且使用长罐）净重约60g，非常轻便，轻松放入背包。",
        "new_answer": "转接头重量资料标注约60g。",
    },
    {
        "sku": "CW-K04PRO-37",
        "question": "时光煮水户外水壶套装有多重？",
        "old_answer": "时光煮水户外水壶套装净重约420g，非常轻便，轻松放入背包。",
        "new_answer": "时光煮水户外水壶套装重量资料标注约420g。",
    },
    {
        "sku": "CW-K04PRO-37",
        "question": "时光煮水户外水壶套装有哪些颜色？",
        "old_answer": "时光煮水户外水壶套装颜色为氧化铝本色。",
        "new_answer": "时光煮水户外水壶套装主色系资料标注为锖色。",
    },
    {
        "sku": "DSZ-001",
        "question": "见山登山杖有多重？",
        "old_answer": "见山登山杖净重约290g，非常轻便，轻松放入背包。",
        "new_answer": "见山登山杖重量资料标注约290g。",
    },
    {
        "sku": "CW-G03S-37",
        "question": "防刮手夹有多重？",
        "old_answer": "防刮手夹净重约600g，非常轻便，轻松放入背包。",
        "new_answer": "防刮手夹重量资料标注约57g。",
    },
    {
        "sku": "PA-B15S-27",
        "question": "围雪气炉配件（配件）有多重？",
        "old_answer": "围雪气炉配件（配件）净重约531g，非常轻便，轻松放入背包。",
        "new_answer": "围雪气炉配件重量资料标注约120g。",
    },
    {
        "sku": "DV01",
        "question": "独醒-酒具套装有多重？",
        "old_answer": "独醒-酒具套装净重约280g，非常轻便，轻松放入背包。",
        "new_answer": "独醒酒具套装重量资料标注约280g。",
    },
    {
        "sku": "CS-B15SPRO",
        "question": "围雪炉-酒精汽炉版有多重？",
        "old_answer": "围雪炉-酒精汽炉版净重约578g，非常轻便，轻松放入背包。",
        "new_answer": "围雪炉酒精汽炉版重量资料标注约578g。",
    },
    {
        "sku": "CW-C06S-37",
        "question": "乐途3-4人野餐锅7件套有多重？",
        "old_answer": "乐途3-4人野餐锅7件套重量约1.28kg（含包装），户外携带无负担。",
        "new_answer": "乐途3-4人野餐锅7件套毛重约1280g（约1.28kg）。",
    },
    {
        "sku": "CS-G23-42",
        "question": "麒麟炉-便携式燃气灶(不锈钢本色）EVA包款有多重？",
        "old_answer": "麒麟炉-便携式燃气灶(不锈钢本色）EVA包款重量约3.48kg（含包装），户外携带无负担。",
        "new_answer": "不锈钢本色EVA包款麒麟炉毛重约3480g（约3.48kg）。",
    },
    {
        "sku": "TW-139",
        "question": "饭盒（黑色盖子+硬质氧化铝身）有多重？",
        "old_answer": "饭盒（黑色盖子+硬质氧化铝身）净重约980g，非常轻便，轻松放入背包。",
        "new_answer": "饭盒重量资料标注约980g。",
    },
    {
        "sku": "CB253",
        "question": "聚能环水壶（亚马逊转国内）有多重？",
        "old_answer": "聚能环水壶（亚马逊转国内）净重约273g，非常轻便，轻松放入背包。",
        "new_answer": "聚能环水壶重量资料标注约273g。",
    },
    {
        "sku": "OF-16CS",
        "question": "OF-16CS城市出逃轻羽椅有多重？",
        "old_answer": "OF-16CS城市出逃轻羽椅重量约2.16kg（含包装），户外携带无负担。",
        "new_answer": "城市出逃轻羽椅毛重资料标注约2160g（约2.16kg）。",
    },
    {
        "sku": "OF-16CS",
        "question": "OF-16CS城市出逃轻羽椅能坐多重的人？",
        "old_answer": "OF-16CS城市出逃轻羽椅结构稳固，承重可达80-120kg，大人小孩都能安心使用。",
        "new_answer": "当前正式商品资料没有记录明确的最大承重数值，因此暂时无法给出承重范围。",
    },
    {
        "sku": "CW-C65-1",
        "question": "城市出逃套锅大锅有多重？",
        "old_answer": "城市出逃套锅大锅净重约830g，非常轻便，轻松放入背包。",
        "new_answer": "城市出逃套锅大锅重量资料标注约830g。",
    },
    {
        "sku": "CW-C65-5",
        "question": "CW-C65-5城市出逃小单锅有多重？",
        "old_answer": "CW-C65-5城市出逃小单锅净重约636g，非常轻便，轻松放入背包。",
        "new_answer": "城市出逃小单锅重量资料标注约350g。",
    },
    {
        "sku": "CW-C19T-37",
        "question": "旅伴2-3人野餐锅5件套有多重？",
        "old_answer": "旅伴2-3人野餐锅5件套重量约1.06kg（含包装），户外携带无负担。",
        "new_answer": "旅伴2-3人野餐锅5件套毛重资料标注约1062g（约1.06kg）。",
    },
    {
        "sku": "TX-38",
        "question": "坐忘泡茶套装有多重？",
        "old_answer": "坐忘泡茶套装净重约580g，非常轻便，轻松放入背包。",
        "new_answer": "坐忘泡茶套装重量资料标注约580g。",
    },
    {
        "sku": "CW-C77",
        "question": "Where Eat-享野系列套锅-套装1有多重？",
        "old_answer": "Where Eat-享野系列套锅-套装1净重约800g，非常轻便，轻松放入背包。",
        "new_answer": "享野系列套锅套装1重量资料标注约800g。",
    },
    {
        "sku": "CW-K11-37",
        "question": "寻唐套装有多重？",
        "old_answer": "寻唐套装净重约639g，非常轻便，轻松放入背包。",
        "new_answer": "寻唐套装重量资料标注约639g。",
    },
)


# Natural variants selected from the historical customer conversations.  They
# intentionally cover common field/usage questions without copying sales
# language from the chat records.
SUPPLEMENTAL_QA: tuple[dict[str, Any], ...] = (
    {"sku": "CW-K11-37", "question": "寻唐套装这个多少升？", "answer": "容量约1.3L。", "tags": ["历史自然问法", "容量"]},
    {"sku": "CW-C72", "question": "这个1.7L单锅实际容量多少？", "answer": "容量约1.7L。", "tags": ["历史自然问法", "容量"]},
    {"sku": "CW-C99B", "question": "小方锅是多少升的？", "answer": "容量约1.7L。", "tags": ["历史自然问法", "容量"]},
    {"sku": "CW-RT05", "question": "有喜锅大概几升？", "answer": "容量约1.3L。", "tags": ["历史自然问法", "容量"]},
    {"sku": "CW-C47-37", "question": "荒野3-4人自驾套装里面各锅容量多大？", "answer": "包含2.2L锅、1.4L锅、0.8L水壶，另有7.5英寸煎盘。", "tags": ["历史自然问法", "容量"]},
    {"sku": "CW-K03", "question": "星空辉这款水壶多少升？", "answer": "容量约1.4L。", "tags": ["历史自然问法", "容量"]},
    {"sku": "CW-C82", "question": "时谷水壶容量多少？", "answer": "容量约1.4L。", "tags": ["历史自然问法", "容量"]},
    {"sku": "CW-C84", "question": "鸣泉水壶多少升？", "answer": "容量约1.4L。", "tags": ["历史自然问法", "容量"]},
    {"sku": "CW-K32", "question": "享膳Plus水壶容量多大？", "answer": "容量约2.3L。", "tags": ["历史自然问法", "容量"]},
    {"sku": "CW-C76", "question": "享野水壶多少升？", "answer": "容量约0.8L。", "tags": ["历史自然问法", "容量"]},
    {"sku": "CW-C96-B", "question": "京享水壶多少升？", "answer": "容量约0.8L。", "tags": ["历史自然问法", "容量"]},
    {"sku": "CB253", "question": "聚能环水壶容量多大？", "answer": "容量约1.4L。", "tags": ["历史自然问法", "容量"]},
    {"sku": "CW-C90", "question": "这个煎盘是几寸的？", "answer": "尺寸为7.5英寸。", "tags": ["历史自然问法", "尺寸"]},
    {"sku": "CW-PF05", "question": "陶瓷不沾煎盘多大？", "answer": "尺寸为7.5英寸。", "tags": ["历史自然问法", "尺寸"]},
    {"sku": "AC-Z14", "question": "灵巧包能装多少东西？", "answer": "容量约30L。", "tags": ["历史自然问法", "容量"]},
    {"sku": "AC-Z14", "question": "灵巧包能不能展开当小桌？", "answer": "可以。内部钢丝框架展开后撑开包身，盖上单元板即可当小桌使用。", "tags": ["历史自然问法", "使用"]},
    {"sku": "CW-C01-37", "question": "CW-C01-37适用什么炉具？", "answer": "适用明火直烧、卡式炉、分体炉和一体炉。", "tags": ["历史自然问法", "热源"]},
    {"sku": "CS-B14", "question": "旋焰酒精炉用什么燃料？", "answer": "适用95%液体工业酒精。", "tags": ["历史自然问法", "燃料"]},
    {"sku": "CS-B14", "question": "酒精炉燃烧的时候能加酒精吗？", "answer": "不能。必须先灭火，再添加燃料。", "tags": ["历史自然问法", "安全使用"]},
    {"sku": "CW-C83", "question": "炊墨套锅的锅和煎盘容量分别是多少？", "answer": "锅约3700ML，煎盘约2300ML。", "tags": ["历史自然问法", "容量"]},
    {"sku": "CW-C83", "question": "炊墨套锅能用电磁炉吗？", "answer": "可以。适用热源资料包含明火直烧、燃气炉、卡式炉、电磁炉、燃气灶和电陶炉。", "tags": ["历史自然问法", "热源"]},
    {"sku": "CW-C83", "question": "炊墨套锅有不粘涂层吗？", "answer": "有。表面处理资料标注了硬质氧化和水性不沾。", "tags": ["历史自然问法", "表面处理"]},
    {"sku": "CW-C83", "question": "炊墨套锅收纳后多大？", "answer": "收纳带手柄尺寸约52*28.6*14.5cm。", "tags": ["历史自然问法", "尺寸"]},
    {"sku": "CW-C93", "question": "行山单锅容量多少？", "answer": "锅容量约1000ML（1L）。", "tags": ["历史自然问法", "容量"]},
    {"sku": "CW-C93", "question": "行山单锅有多重？", "answer": "重量约220g。", "tags": ["历史自然问法", "重量"]},
    {"sku": "CW-C93", "question": "行山单锅可以用哪些炉具？", "answer": "适用明火直烧、卡式炉、分体炉和一体炉。", "tags": ["历史自然问法", "热源"]},
    {"sku": "CW-C93", "question": "行山单锅有没有不粘涂层？", "answer": "资料标注表面处理包含硬质氧化和陶瓷不沾；可以确认有陶瓷不沾表面处理，但资料没有单独说明涂层结构，不能把硬质氧化直接等同为涂层。", "tags": ["历史自然问法", "表面处理"]},
    {"sku": "CW-C93", "question": "行山单锅展开尺寸是多少？", "answer": "展开尺寸约12.5*12.5*12.9cm。", "tags": ["历史自然问法", "尺寸"]},
    {"sku": "CS-G25", "question": "小青炉最大功率和重量是多少？", "answer": "最大功率3200W，重量约550g。", "tags": ["历史自然问法", "功率", "重量"]},
    {"sku": "CS-G25", "question": "小青炉怎么点火？", "answer": "连接燃气罐后，打开火力调节阀逆时针旋转1-2圈，再按击点火装置；点燃后调节火力。", "tags": ["历史自然问法", "使用"]},
    {"sku": "CS-G25", "question": "小青炉有防风设计吗？", "answer": "有。技术优势资料标注了猛火大功率4级防风。", "tags": ["历史自然问法", "防风"]},
    {"sku": "CS-B14", "question": "旋焰酒精炉的炉体容量是多少？", "answer": "炉体容量约200ML。", "tags": ["历史自然问法", "容量"]},

    # Additional natural variants are limited to the five SKUs that had the
    # thinnest approved QA coverage in the development catalogue.  These are
    # phrased from historical customer wording, but each answer is a direct
    # same-SKU field/usage fact rather than a copied agent claim.
    {"sku": "CW-C01-37", "question": "C01套锅的锅和碗分别多大？", "answer": "锅容量约900ML，碗容量约450ML。", "tags": ["历史自然问法", "容量"]},
    {"sku": "CW-C01-37", "question": "C01套锅大概有多重？", "answer": "毛重约595g。", "tags": ["历史自然问法", "重量"]},
    {"sku": "CW-C01-37", "question": "C01套锅是什么材质做的？", "answer": "材质包括硬质氧化铝合金、不锈钢和铜。", "tags": ["历史自然问法", "材质"]},
    {"sku": "CW-C01-37", "question": "C01套锅能放卡式炉上用吗？", "answer": "可以。适用热源资料包含卡式炉。", "tags": ["历史自然问法", "热源"]},
    {"sku": "CW-C01-37", "question": "C01套锅能不能用明火？", "answer": "可以。适用热源资料包含明火直烧。", "tags": ["历史自然问法", "热源"]},
    {"sku": "CW-C01-37", "question": "C01套锅可以配分体炉和一体炉吗？", "answer": "可以。适用热源资料包含分体炉和一体炉。", "tags": ["历史自然问法", "热源"]},

    {"sku": "CS-B14", "question": "旋焰酒精炉最大功率是多少？", "answer": "最大功率约2250W。", "tags": ["历史自然问法", "功率"]},
    {"sku": "CS-B14", "question": "旋焰酒精炉是什么材质的？", "answer": "材质为304不锈钢。", "tags": ["历史自然问法", "材质"]},
    {"sku": "CS-B14", "question": "旋焰酒精炉用液体酒精还是固体酒精？", "answer": "商品资料标注适用95%液体工业酒精；资料没有把固体酒精列为已确认燃料。", "tags": ["历史自然问法", "燃料"]},
    {"sku": "CS-B14", "question": "旋焰酒精炉燃烧时可以移动吗？", "answer": "不可以。必须先灭火，确认停止燃烧后再移动。", "tags": ["历史自然问法", "安全使用"]},

    {"sku": "CS-G25", "question": "小青炉能接高山气罐吗？", "answer": "可以。商品资料标注适配高山气罐。", "tags": ["历史自然问法", "燃料"]},
    {"sku": "CS-G25", "question": "小青炉能用卡式气罐吗？", "answer": "可以。商品资料标注适配卡式气罐。", "tags": ["历史自然问法", "燃料"]},
    {"sku": "CS-G25", "question": "小青炉点着以后怎么调火？", "answer": "点燃后通过火力调节阀调节火力；火焰应为蓝色，并可从低到高调节。", "tags": ["历史自然问法", "使用"]},
    {"sku": "CS-G25", "question": "小青炉的最大火力是多少瓦？", "answer": "最大功率约3200W。", "tags": ["历史自然问法", "功率"]},
    {"sku": "CS-G25", "question": "小青炉有几级防风？", "answer": "技术优势资料标注为猛火大功率4级防风。", "tags": ["历史自然问法", "防风"]},

    {"sku": "CW-C83", "question": "炊墨套锅是什么材质的？", "answer": "材质包括硬质氧化铝合金和白蜡木。", "tags": ["历史自然问法", "材质"]},
    {"sku": "CW-C83", "question": "炊墨套锅可以用卡式炉吗？", "answer": "可以。适用热源资料包含卡式炉。", "tags": ["历史自然问法", "热源"]},
    {"sku": "CW-C83", "question": "炊墨套锅可以用燃气灶吗？", "answer": "可以。适用热源资料包含燃气灶。", "tags": ["历史自然问法", "热源"]},
    {"sku": "CW-C83", "question": "炊墨套锅毛重大概多少？", "answer": "毛重约2000g（约2kg）。", "tags": ["历史自然问法", "重量"]},
    {"sku": "CW-C83", "question": "炊墨套锅日常怎么清洗？", "answer": "使用后趁锅体尚有余温，用温水冲洗并擦干；避免使用钢丝球等硬物刮擦表面。", "tags": ["历史自然问法", "清洗"]},
    {"sku": "CW-C83", "question": "炊墨套锅内壁能用铁铲刮吗？", "answer": "资料要求避免金属直接刮擦锅内壁，因此不建议用铁铲等金属工具刮擦内壁。", "tags": ["历史自然问法", "使用"]},

    {"sku": "CW-C93", "question": "行山单锅是什么材质的？", "answer": "材质包括硬质氧化铝合金和进口TPE。", "tags": ["历史自然问法", "材质"]},
    {"sku": "CW-C93", "question": "行山单锅日常怎么清洗？", "answer": "使用后趁锅体尚有余温，用温水冲洗并擦干；避免使用钢丝球等硬物刮擦表面。", "tags": ["历史自然问法", "清洗"]},
    {"sku": "CW-C93", "question": "行山单锅能直接放明火上吗？", "answer": "可以。适用热源资料包含明火直烧。", "tags": ["历史自然问法", "热源"]},
    {"sku": "CW-C93", "question": "行山单锅能放卡式炉上吗？", "answer": "可以。适用热源资料包含卡式炉。", "tags": ["历史自然问法", "热源"]},
    {"sku": "CW-C93", "question": "行山单锅展开后尺寸多大？", "answer": "展开尺寸约12.5*12.5*12.9cm。", "tags": ["历史自然问法", "尺寸"]},

    # The following variants are taken from the full historical-chat scan on
    # 2026-08-25.  They are kept as natural retrieval keys, while every answer
    # is still limited to the current same-SKU field or usage instruction.
    {"sku": "CF-PG19", "question": "瓦片烤盘可以放电磁炉上吗？", "answer": "可以。适用热源资料包含电磁炉。", "tags": ["历史自然问法", "热源"]},
    {"sku": "CF-PG19", "question": "瓦片烤盘能用燃气灶吗？", "answer": "可以。适用热源资料包含燃气灶。", "tags": ["历史自然问法", "热源"]},
    {"sku": "CF-PG19", "question": "瓦片烤盘表面是什么涂层？", "answer": "表面处理资料标注为水性不沾。", "tags": ["历史自然问法", "表面处理"]},
    {"sku": "CF-PG19", "question": "瓦片烤盘需要开锅吗？", "answer": "当前使用说明要求首次使用前用温水和软布清洗（无需洗洁精），烹饪前用中小火预热2-3分钟后再倒油；资料没有单独给出其他开锅步骤。", "tags": ["历史自然问法", "首次使用"]},

    {"sku": "CS-B02-37", "question": "这个酒精炉能用固体酒精吗？", "answer": "可以。使用说明标注液体和固体酒精均可使用；推荐95%浓度的液体酒精，燃烧效率更高。", "tags": ["历史自然问法", "燃料"]},
    {"sku": "CS-B02-37", "question": "酒精炉可以边烧边加酒精吗？", "answer": "不可以。必须先熄灭火焰，再添加酒精，不能在明火状态下添加。", "tags": ["历史自然问法", "安全使用"]},
    {"sku": "CS-B02-37", "question": "液体酒精没用完怎么存放？", "answer": "未使用完的酒精要及时密封，远离火源，常温存放，并放在儿童不易接触的地方。", "tags": ["历史自然问法", "安全使用"]},
    {"sku": "CS-B02-37", "question": "100ml酒精大概能烧多久？", "answer": "使用95%酒精文火燃烧时，100ml约可持续60分钟。", "tags": ["历史自然问法", "燃烧时间"]},
    {"sku": "CS-B02-37", "question": "酒精炉烧黑了怎么处理？", "answer": "使用后及时用海绵擦清洗即可。使用说明还提示，酒精纯度不足或燃烧不充分可能产生积碳。", "tags": ["历史自然问法", "清洁"]},

    {"sku": "CS-G35", "question": "小圆炉高山气罐可以用吗？", "answer": "可以。商品资料标注适配高山气罐。", "tags": ["历史自然问法", "燃料"]},
    {"sku": "CS-G35", "question": "小圆炉怎么打火？", "answer": "先连接气罐，再点火即可使用。", "tags": ["历史自然问法", "使用"]},
    {"sku": "CS-G35", "question": "小圆炉有收纳袋吗？", "answer": "有。技术优势资料标注附赠收纳包。", "tags": ["历史自然问法", "配件"]},

    {"sku": "CW-C85-B", "question": "熊猫大侠万象炉支持哪些燃料？", "answer": "资料标注适用95%液体工业酒精、高山气罐和卡式气罐。", "tags": ["历史自然问法", "燃料"]},
    {"sku": "CW-C85-B", "question": "熊猫大侠万象炉怎么点火？", "answer": "连接气罐后逆时针旋转火力调节阀1-2圈，听到气体溢出声后按下点火装置，点燃后再调节火力。", "tags": ["历史自然问法", "使用"]},
    {"sku": "CW-C85-B", "question": "熊猫大侠万象炉能在帐篷里用吗？", "answer": "不可以。使用说明要求在通风良好的环境中使用，不能在帐篷等密闭空间内使用。", "tags": ["历史自然问法", "安全使用"]},
    {"sku": "CW-C85-B", "question": "熊猫大侠万象炉用完后怎么收纳？", "answer": "使用完毕后关闭火力调节阀，待炉具冷却后再拆下气罐收纳。", "tags": ["历史自然问法", "使用"]},

    {"sku": "TW-503", "question": "悠然杯Pro能直接放明火上加热吗？", "answer": "不能。使用说明明确用于盛装冷、热饮品，不可直接置于明火上加热。", "tags": ["历史自然问法", "安全使用"]},
    {"sku": "TW-503", "question": "悠然杯Pro可以装热饮吗？", "answer": "可以。使用说明标注可用于盛装冷饮和热饮。", "tags": ["历史自然问法", "使用"]},
    {"sku": "TW-503", "question": "硬质氧化铝就是杯子外面的涂层吗？", "answer": "资料标注材质为硬质氧化铝、表面处理为硬质氧化；资料没有把硬质氧化单独说明为普通涂层结构。", "tags": ["历史自然问法", "表面处理"]},

    {"sku": "MT01-YL", "question": "疯狂游乐园喷枪能用卡式气罐吗？", "answer": "可以。商品资料标注适配卡式气罐。", "tags": ["历史自然问法", "燃料"]},
    {"sku": "MT01-YL", "question": "这个喷枪配套用哪种气罐？", "answer": "商品资料标注适配高山气罐和卡式气罐。", "tags": ["历史自然问法", "燃料"]},
    {"sku": "MT01-CS", "question": "城市出逃喷枪怎么点火？", "answer": "连接气罐后，调节至硬火状态再点火使用。", "tags": ["历史自然问法", "使用"]},

    {"sku": "CW-C96-B", "question": "京享水壶尺寸多大？", "answer": "水壶尺寸约15×8cm。", "tags": ["历史自然问法", "尺寸"]},
    {"sku": "CW-C96-B", "question": "京享水壶是304不锈钢吗？", "answer": "当前商品资料标注主体材质为硬质氧化铝，未标注304不锈钢。", "tags": ["历史自然问法", "材质"]},
    {"sku": "CW-C96-B", "question": "京享水壶可以用电磁炉吗？", "answer": "当前商品资料只标注明火直烧，未标注电磁炉兼容，不能据此确认可以使用。", "tags": ["历史自然问法", "热源"]},

    {"sku": "CW-K11-37", "question": "寻唐套装水壶尺寸多大？", "answer": "尺寸约16.5×13.5cm。", "tags": ["历史自然问法", "尺寸"]},
    {"sku": "CW-K11-37", "question": "寻唐套装水壶是什么材质？", "answer": "材质为硬质氧化铝合金。", "tags": ["历史自然问法", "材质"]},
    {"sku": "CW-K03-37", "question": "1.4升户外水壶能用卡式炉吗？", "answer": "可以。适用热源资料包含卡式炉。", "tags": ["历史自然问法", "热源"]},
    {"sku": "CW-K03-37", "question": "1.4升户外水壶能直接用明火吗？", "answer": "可以。适用热源资料包含明火直烧。", "tags": ["历史自然问法", "热源"]},
    {"sku": "CW-K03-37", "question": "1.4升户外水壶是什么材质？", "answer": "材质为硬质氧化铝合金。", "tags": ["历史自然问法", "材质"]},
    {"sku": "CW-K03-37", "question": "1.4升户外水壶尺寸多大？", "answer": "展开尺寸约15×15×10cm。", "tags": ["历史自然问法", "尺寸"]},

    {"sku": "AC-Z14", "question": "灵巧包展开后尺寸多大？", "answer": "展开尺寸约36×25×33.5cm。", "tags": ["历史自然问法", "尺寸"]},
    {"sku": "AC-Z14", "question": "灵巧包收起来尺寸多大？", "answer": "收纳尺寸约37×26×9.5cm。", "tags": ["历史自然问法", "尺寸"]},
    {"sku": "CW-C83-1", "question": "炊墨炒锅能放电磁炉上吗？", "answer": "可以。适用热源资料包含电磁炉。", "tags": ["历史自然问法", "热源"]},
    {"sku": "CW-C83-1", "question": "炊墨炒锅能用燃气灶吗？", "answer": "可以。适用热源资料包含燃气灶。", "tags": ["历史自然问法", "热源"]},
    {"sku": "CW-C83-1", "question": "炊墨炒锅表面是水性不沾吗？", "answer": "是。表面处理资料标注包含水性不沾。", "tags": ["历史自然问法", "表面处理"]},
    {"sku": "CW-C99B", "question": "小方锅是什么材质？", "answer": "材质为不锈钢。", "tags": ["历史自然问法", "材质"]},
    {"sku": "CW-C99B", "question": "小方锅尺寸多大？", "answer": "尺寸约182×173×76mm。", "tags": ["历史自然问法", "尺寸"]},
    {"sku": "CS-B14", "question": "旋焰酒精炉最大承重多少？", "answer": "技术优势资料标注最大承重10kg。", "tags": ["历史自然问法", "承重"]},
    {"sku": "CS-B14", "question": "旋焰酒精炉能燃烧多久？", "answer": "技术优势资料标注最长燃烧2小时。实际时长会受燃料和使用条件影响。", "tags": ["历史自然问法", "燃烧时间"]},
    {"sku": "CW-C97", "question": "京澜水壶能用酒精炉吗？", "answer": "可以。适用热源资料包含酒精炉。", "tags": ["历史自然问法", "热源"]},
    {"sku": "CW-C94", "question": "单兵锅能放卡式炉上用吗？", "answer": "可以。适用热源资料包含卡式炉。", "tags": ["历史自然问法", "热源"]},
    {"sku": "CW-C05-37", "question": "2-4人野餐锅10件套有收纳包吗？", "answer": "有。卖点资料标注全套收纳仅一个收纳包。", "tags": ["历史自然问法", "配件"]},

    # Second manual review batch from the historical-chat scan on 2026-08-25.
    # Every answer below is limited to a same-SKU formal field or usage
    # instruction; no answer turns a measurement into a portability or safety
    # promise that the source does not make.
    {"sku": "CW-DRP01", "question": "导热盘能干烧吗？", "answer": "不能。使用说明明确严禁干烧，盘上应放置锅具使用。", "tags": ["历史自然问法", "安全使用"]},
    {"sku": "CW-DRP01", "question": "导热盘尺寸多大？", "answer": "尺寸约24×0.25cm。", "tags": ["历史自然问法", "尺寸"]},
    {"sku": "CW-C12", "question": "这款煎盘有没有不粘涂层？", "answer": "表面处理资料标注为硬质氧化，未标注不粘涂层；使用时建议先中小火预热、倒油后再下食材。", "tags": ["历史自然问法", "表面处理"]},
    {"sku": "CW-C12", "question": "煎盘尺寸是多少？", "answer": "尺寸约19×4cm。", "tags": ["历史自然问法", "尺寸"]},
    {"sku": "CW-C06PRO", "question": "轻途套锅的大锅、小锅和水壶分别多大？", "answer": "大锅约3.0L，小锅约1.7L，水壶约0.8L，另有约7.5英寸煎盘。", "tags": ["历史自然问法", "容量"]},
    {"sku": "CW-C06PRO", "question": "轻途套锅收纳后多大？", "answer": "收纳尺寸约22×21×13.5cm。", "tags": ["历史自然问法", "尺寸"]},
    {"sku": "CW-C33-A", "question": "涮涮锅容量多少？", "answer": "容量约2L。", "tags": ["历史自然问法", "容量"]},
    {"sku": "CW-C33-A", "question": "涮涮锅尺寸多大？", "answer": "展开尺寸约22.5×22.8cm，收纳尺寸约22.5×12.5cm。", "tags": ["历史自然问法", "尺寸"]},
    {"sku": "CW-C33-A", "question": "涮涮锅能放卡式炉上用吗？", "answer": "可以。适用热源资料包含卡式炉。", "tags": ["历史自然问法", "热源"]},
    {"sku": "CS-G30", "question": "烈焰取暖炉适配哪种气罐？", "answer": "当前商品资料标注热源为卡式气罐。", "tags": ["历史自然问法", "燃料"]},
    {"sku": "CS-G30", "question": "烈焰取暖炉可以在帐篷里使用吗？", "answer": "不可以。使用说明要求通风良好，不能在帐篷等密闭空间内使用。", "tags": ["历史自然问法", "安全使用"]},
    {"sku": "CS-G30", "question": "烈焰取暖炉怎么点火？", "answer": "连接卡式气罐后，逆时针旋转火力调节阀1-2圈，听到气体溢出声后按下点火装置；点燃后再调节火力。", "tags": ["历史自然问法", "使用"]},
    {"sku": "CS-B21", "question": "闪焰点火器怎么清洁？", "answer": "使用后用湿布擦拭干净，晾干后收纳；存放在干燥通风处。", "tags": ["历史自然问法", "清洁"]},
    {"sku": "TW-402-37", "question": "悠然杯容量是多少？", "answer": "容量约150ml。", "tags": ["历史自然问法", "容量"]},
    {"sku": "CW-C85-A", "question": "熊猫大侠百味锅容量多大？", "answer": "容量约3.5L。", "tags": ["历史自然问法", "容量"]},
    {"sku": "CW-C85-A", "question": "熊猫大侠百味锅有不粘处理吗？", "answer": "有。表面处理资料标注为硬质氧化和水性不沾。", "tags": ["历史自然问法", "表面处理"]},
    {"sku": "CW-C70", "question": "时谷锅容量是多少？", "answer": "容量约4L。", "tags": ["历史自然问法", "容量"]},
    {"sku": "CW-C70", "question": "时谷锅能用卡式炉吗？", "answer": "可以。适用热源资料包含卡式炉。", "tags": ["历史自然问法", "热源"]},

    # Third manual review batch.  This deliberately broadens historical-title
    # and alias coverage instead of requiring an exact catalogue-name match.
    # Product binding was confirmed through RAG candidates and every answer is
    # restricted to the selected SKU's current formal facts or usage text.
    {"sku": "AC-Z08LY", "question": "疯狂游乐园那个折叠收纳箱有多大容量？", "answer": "容量资料标注约50L。", "tags": ["历史自然问法", "第三批人工审核", "容量"]},
    {"sku": "AC-Z08LY", "question": "游乐园折叠箱展开和收起来分别多大？", "answer": "展开尺寸约53×36×33.5cm，收纳尺寸约53×36×10cm。", "tags": ["历史自然问法", "第三批人工审核", "尺寸"]},
    {"sku": "AC-Z08LY", "question": "这个折叠箱是塑料还是木头的？", "answer": "材质资料标注为PP和密度板。", "tags": ["历史自然问法", "第三批人工审核", "材质"]},

    {"sku": "CS-B15S", "question": "围雪炉酒精款用液体酒精还是固体酒精？", "answer": "液体和固体酒精均可使用；使用说明推荐95%浓度的液体酒精。", "tags": ["历史自然问法", "第三批人工审核", "燃料"]},
    {"sku": "CS-B15S", "question": "围雪炉烧着时能不能直接添酒精？", "answer": "不能。必须先熄灭火焰再添加酒精，严禁在明火状态下添加。", "tags": ["历史自然问法", "第三批人工审核", "安全使用"]},
    {"sku": "CS-B15S", "question": "围雪炉100毫升酒精大概能烧多久？", "answer": "使用说明标注，100ML的95%酒精在文火状态下约可燃烧60分钟。", "tags": ["历史自然问法", "第三批人工审核", "燃烧时间"]},

    {"sku": "CS-B15SPRO", "question": "围雪炉汽炉版都能烧哪些燃料？", "answer": "当前热源资料列明液体酒精、木柴和竹炭。", "tags": ["历史自然问法", "第三批人工审核", "燃料"]},
    {"sku": "CS-B15SPRO", "question": "围雪炉汽炉版加酒精能超过炉芯八成吗？", "answer": "不能。使用说明要求加入约100-200ml液体酒精，且不得超过炉芯容量的80%。", "tags": ["历史自然问法", "第三批人工审核", "安全使用"]},
    {"sku": "CS-B15SPRO", "question": "汽炉版围雪炉是什么材质和表面工艺？", "answer": "材质为硬质氧化铝，表面工艺资料标注为拉丝。", "tags": ["历史自然问法", "第三批人工审核", "材质", "表面处理"]},

    {"sku": "CS-B17-B", "question": "那个按一下打火的黑色点火器是什么材质？", "answer": "材质为304不锈钢和ABS塑料。", "tags": ["历史自然问法", "第三批人工审核", "材质"]},
    {"sku": "CS-B17-B", "question": "黑色按压点火器有多大？", "answer": "尺寸约105×30×9mm。", "tags": ["历史自然问法", "第三批人工审核", "尺寸"]},
    {"sku": "CS-B17-B", "question": "按压点火器用完怎么清理？", "answer": "使用后用湿布擦拭干净，晾干后放在干燥通风处收纳。", "tags": ["历史自然问法", "第三批人工审核", "清洁"]},

    {"sku": "CS-G05-28", "question": "蓝翼分体炉接高山罐还是卡式罐？", "answer": "高山气罐和卡式气罐都在适配热源资料中。", "tags": ["历史自然问法", "第三批人工审核", "热源"]},
    {"sku": "CS-G05-28", "question": "蓝翼分体气炉火力多少瓦？", "answer": "功率资料标注为2800W。", "tags": ["历史自然问法", "第三批人工审核", "功率"]},
    {"sku": "CS-G05-28", "question": "蓝翼炉能不能放帐篷里用？", "answer": "不能。使用说明要求保持通风，不能在帐篷等密闭空间内使用。", "tags": ["历史自然问法", "第三批人工审核", "安全使用"]},

    {"sku": "CW-C74", "question": "享野8寸煎锅表面是什么工艺？", "answer": "表面处理资料标注为硬质氧化。", "tags": ["历史自然问法", "第三批人工审核", "表面处理"]},
    {"sku": "CW-C74", "question": "享野这个煎盘能用卡式炉和分体炉吗？", "answer": "可以。适用热源资料包含卡式炉和分体炉。", "tags": ["历史自然问法", "第三批人工审核", "热源"]},
    {"sku": "CW-C74", "question": "享野8寸煎盘第一次用要怎么处理？", "answer": "首次使用前用温水和软布清洗；烹饪前用中小火预热2-3分钟，再倒油放入食材。", "tags": ["历史自然问法", "第三批人工审核", "首次使用"]},

    {"sku": "CW-C78", "question": "享野那套锅里面各个锅分别多少升？", "answer": "大锅约3L，小锅约1.7L，水壶约0.8L。", "tags": ["历史自然问法", "第三批人工审核", "容量"]},
    {"sku": "CW-C78", "question": "享野套锅能放卡式炉上烧吗？", "answer": "可以。适用热源资料包含卡式炉。", "tags": ["历史自然问法", "第三批人工审核", "热源"]},
    {"sku": "CW-C78", "question": "享野这一整套毛重多少？", "answer": "毛重约1320g（约1.32kg）。", "tags": ["历史自然问法", "第三批人工审核", "重量"]},

    {"sku": "CW-C95", "question": "风暴炉Pro两用款到底烧酒精还是接气罐？", "answer": "两种都支持。热源资料列明高山气罐和液体酒精。", "tags": ["历史自然问法", "第三批人工审核", "燃料"]},
    {"sku": "CW-C95", "question": "风暴炉Pro套装的锅、煎盘和水壶分别多大？", "answer": "煮锅约1.7L，煎盘约8寸，水壶约0.8L。", "tags": ["历史自然问法", "第三批人工审核", "容量"]},
    {"sku": "CW-C95", "question": "风暴炉Pro最大火力是多少瓦？", "answer": "功率资料标注为3200W。", "tags": ["历史自然问法", "第三批人工审核", "功率"]},

    {"sku": "CW-K04PRO-37", "question": "1.4L时光煮水壶配的炉子烧哪种酒精？", "answer": "热源资料标注为95%液体工业酒精。", "tags": ["历史自然问法", "第三批人工审核", "燃料"]},
    {"sku": "CW-K04PRO-37", "question": "时光煮水套装的壶是多少毫升？", "answer": "水壶容量约1400ml（1.4L）。", "tags": ["历史自然问法", "第三批人工审核", "容量"]},
    {"sku": "CW-K04PRO-37", "question": "时光煮水壶能不能空壶干烧？", "answer": "不能。使用说明明确严禁干烧。", "tags": ["历史自然问法", "第三批人工审核", "安全使用"]},

    {"sku": "GA01-37", "question": "卡式长罐转接头是干嘛用的？", "answer": "用于转换气罐接口，让适配的爱路客气炉连接卡式长罐使用。", "tags": ["历史自然问法", "第三批人工审核", "用途"]},
    {"sku": "GA01-37", "question": "这个转接头适配爱路客气炉吗？", "answer": "商品名称资料标注其通用于爱路客气炉，并用于连接卡式长罐。", "tags": ["历史自然问法", "第三批人工审核", "适配"]},
    {"sku": "GA01-37", "question": "气罐转接头是什么材质、多大尺寸？", "answer": "材质为铝合金和PP，尺寸约4.1×2.8cm。", "tags": ["历史自然问法", "第三批人工审核", "材质", "尺寸"]},

    {"sku": "GX15-450G", "question": "450克高山罐能不能放车里暴晒？", "answer": "不能。使用说明要求存放在阴凉干燥处，并远离火源和高温。", "tags": ["历史自然问法", "第三批人工审核", "安全存放"]},
    {"sku": "GX15-450G", "question": "450G高山气罐是什么接口？", "answer": "使用说明标注适配标准高山气罐螺纹接口的户外炉具。", "tags": ["历史自然问法", "第三批人工审核", "接口"]},
    {"sku": "GX15-450G", "question": "450g气罐能在帐篷里用吗？", "answer": "不能。使用说明要求保持通风，严禁在密闭空间内使用。", "tags": ["历史自然问法", "第三批人工审核", "安全使用"]},

    {"sku": "KD23-MFL", "question": "魔盒桌炉到底多少瓦？", "answer": "卡式炉功率资料标注为2250W。", "tags": ["历史自然问法", "第三批人工审核", "功率"]},
    {"sku": "KD23-MFL", "question": "魔盒卡式炉这个链接带拓展板吗？", "answer": "不带。当前商品名称明确标注为“不含拓展板”。", "tags": ["历史自然问法", "第三批人工审核", "配件"]},
    {"sku": "KD23-MFL", "question": "魔盒卡式炉能不能在帐篷里点？", "answer": "不能。使用说明要求保持通风，不能在帐篷等密闭空间内使用。", "tags": ["历史自然问法", "第三批人工审核", "安全使用"]},

    {"sku": "TW-139", "question": "黑盖铝饭盒容量是多少？", "answer": "容量约1L。", "tags": ["历史自然问法", "第三批人工审核", "容量"]},
    {"sku": "TW-139", "question": "这个硬质氧化铝饭盒能直接放明火上吗？", "answer": "可以。适用热源资料包含明火直烧。", "tags": ["历史自然问法", "第三批人工审核", "热源"]},
    {"sku": "TW-139", "question": "黑盖饭盒可以空盒干烧吗？", "answer": "不可以。使用说明明确严禁干烧。", "tags": ["历史自然问法", "第三批人工审核", "安全使用"]},

    {"sku": "CW-K31", "question": "转转手摇磨豆机要插电吗？", "answer": "不需要。该磨豆器为手摇设计，资料明确标注无需电力。", "tags": ["历史自然问法", "第三批人工审核", "使用"]},
    {"sku": "CW-K31", "question": "转转磨豆器能按意式咖啡调研磨粗细吗？", "answer": "可以。使用说明标注研磨粗细可按手冲、法压和意式等冲煮方式调节。", "tags": ["历史自然问法", "第三批人工审核", "研磨调节"]},
    {"sku": "CW-K31", "question": "手摇磨豆机里面的残粉怎么清理？", "answer": "使用说明要求定期清理残粉并保持刀盘清洁。", "tags": ["历史自然问法", "第三批人工审核", "清洁"]},

    {"sku": "GX14-230G", "question": "230G高山气罐这种螺纹接口能配什么炉具？", "answer": "使用说明标注适配标准高山气罐螺纹接口的户外炉具。", "tags": ["历史自然问法", "第三批人工审核", "接口"]},
    {"sku": "GX14-230G", "question": "230克高山罐高温下怎么保存？", "answer": "应放在阴凉干燥处，远离火源、高温和儿童可触及范围。", "tags": ["历史自然问法", "第三批人工审核", "安全存放"]},
    {"sku": "GX14-230G", "question": "230G气罐能不能在帐篷里烧？", "answer": "不能。使用说明要求保持通风，严禁在密闭空间内使用。", "tags": ["历史自然问法", "第三批人工审核", "安全使用"]},

    {"sku": "CS-G23-42", "question": "不锈钢麒麟炉是插电的还是用气的？", "answer": "该款使用高山气罐或卡式气罐，不是插电式炉具。", "tags": ["历史自然问法", "第三批人工审核", "燃料"]},
    {"sku": "CS-G23-42", "question": "麒麟炉最大火力多少瓦？", "answer": "功率资料标注为5500W。", "tags": ["历史自然问法", "第三批人工审核", "功率"]},
    {"sku": "CS-G23-42", "question": "不锈钢本色麒麟炉是什么材质？", "answer": "材质资料标注为304不锈钢。", "tags": ["历史自然问法", "第三批人工审核", "材质"]},

    {"sku": "CS-G23", "question": "米白麒麟炉用高山罐还是卡式罐？", "answer": "两种都支持。热源资料列明高山气罐和卡式气罐。", "tags": ["历史自然问法", "第三批人工审核", "燃料"]},
    {"sku": "CS-G23", "question": "米白麒麟炉怎么点火和调火？", "answer": "连接气罐后，逆时针旋转火力调节阀1-2圈，听到出气声后按下点火装置；点燃后再用调节阀调节火力。", "tags": ["历史自然问法", "第三批人工审核", "使用"]},
    {"sku": "CS-G23", "question": "米白麒麟炉可以放帐篷里面用吗？", "answer": "不可以。使用说明要求在通风良好的环境中使用，不能在帐篷等密闭空间内使用。", "tags": ["历史自然问法", "第三批人工审核", "安全使用"]},

    {"sku": "CW-C06S-37", "question": "乐途七件套的大锅、小锅和水壶分别多大？", "answer": "大锅约2.2L，小锅约1.4L，水壶约0.8L，另有7.5英寸煎盘。", "tags": ["历史自然问法", "第三批人工审核", "容量"]},
    {"sku": "CW-C06S-37", "question": "乐途套锅能放明火、卡式炉和分体炉上用吗？", "answer": "可以。适用热源资料包含明火直烧、卡式炉、分体炉和一体炉。", "tags": ["历史自然问法", "第三批人工审核", "热源"]},
    {"sku": "CW-C06S-37", "question": "乐途锅能不能空锅干烧？", "answer": "不能。使用说明明确严禁干烧。", "tags": ["历史自然问法", "第三批人工审核", "安全使用"]},

    {"sku": "CW-C65", "question": "城市出逃锅具套装各个锅分别多少升？", "answer": "大锅约3.5L，小锅约2L，水壶约1.0L，煎锅约8寸。", "tags": ["历史自然问法", "第三批人工审核", "容量"]},
    {"sku": "CW-C65", "question": "城市出逃套锅可以配哪些炉子？", "answer": "适用明火直烧、卡式炉、分体炉和一体炉。", "tags": ["历史自然问法", "第三批人工审核", "热源"]},
    {"sku": "CW-C65", "question": "城市出逃这套锅是什么材质？", "answer": "材质为硬质氧化铝合金。", "tags": ["历史自然问法", "第三批人工审核", "材质"]},

    {"sku": "CW-C99", "question": "小方锅Pro里的水壶、煮锅和煎锅分别多大？", "answer": "水壶约1.0L，大锅约1.7L，煎锅约7寸。", "tags": ["历史自然问法", "第三批人工审核", "容量"]},
    {"sku": "CW-C99", "question": "小方锅Pro能直接放明火上烧吗？", "answer": "可以。适用热源资料标注为明火直烧。", "tags": ["历史自然问法", "第三批人工审核", "热源"]},
    {"sku": "CW-C99", "question": "小方锅Pro可以空锅烧吗？", "answer": "不可以。使用说明明确严禁干烧。", "tags": ["历史自然问法", "第三批人工审核", "安全使用"]},

    {"sku": "TW-141", "question": "烽宴聚能锅能配卡式炉和分体炉吗？", "answer": "可以。适用热源资料包含卡式炉和分体炉。", "tags": ["历史自然问法", "第三批人工审核", "热源"]},
    {"sku": "TW-141", "question": "烽宴方锅的锅和盖分别多少毫升？", "answer": "锅容量约1000ML，盖容量约250ML。", "tags": ["历史自然问法", "第三批人工审核", "容量"]},
    {"sku": "TW-141", "question": "烽宴套锅的锅盖能当煎盘用吗？", "answer": "可以。技术参数资料明确标注锅盖可当煎盘使用。", "tags": ["历史自然问法", "第三批人工审核", "功能"]},

    {"sku": "DSZ-001", "question": "见山登山杖收起来和展开后分别多长？", "answer": "折叠尺寸约32cm，伸展长度可在约110-130cm之间调节。", "tags": ["历史自然问法", "第三批人工审核", "尺寸"]},
    {"sku": "DSZ-001", "question": "见山登山手杖的杖身和杖尖是什么材质？", "answer": "支杆为7075铝合金和高强度ABS，杖尖为钨钢。", "tags": ["历史自然问法", "第三批人工审核", "材质"]},
    {"sku": "DSZ-001", "question": "见山登山杖怎么调长短并锁紧？", "answer": "拧松外锁扣后拉伸或收缩杖身至所需长度，再锁紧外锁扣并确认杖身不会滑动。", "tags": ["历史自然问法", "第三批人工审核", "使用"]},

    {"sku": "DSZ-002", "question": "峰行伸缩杖可以调到多长？", "answer": "伸缩尺寸资料标注为62-135cm。", "tags": ["历史自然问法", "第三批人工审核", "尺寸"]},
    {"sku": "DSZ-002", "question": "峰行登山杖一根有多重？", "answer": "重量资料标注约220g。", "tags": ["历史自然问法", "第三批人工审核", "重量"]},
    {"sku": "DSZ-002", "question": "峰行登山杖长期不用时锁扣要怎么放？", "answer": "使用说明要求长期不用时松开锁扣，以放松内部弹簧。", "tags": ["历史自然问法", "第三批人工审核", "保养"]},

    {"sku": "OF-17-1", "question": "1.1版行川包包椅的包有多大容量？", "answer": "容量资料标注为20L+1L。", "tags": ["历史自然问法", "第三批人工审核", "容量"]},
    {"sku": "OF-17-1", "question": "行川包包椅1.1版整套多重？", "answer": "重量资料标注约1720g（约1.72kg）。", "tags": ["历史自然问法", "第三批人工审核", "重量"]},
    {"sku": "OF-17-1", "question": "行川包包椅的背包和登山杖是什么材质？", "answer": "背包材质为94%聚酰胺纤维和6%聚乙烯；登山杖包含7075铝合金、EVA手柄和尼龙腕带。", "tags": ["历史自然问法", "第三批人工审核", "材质"]},

    {"sku": "OT-188HM", "question": "湖美林丰蓝白天幕的防水和防晒指数多少？", "answer": "技术参数资料标注防水指数PU2000mm+、防晒指数UPF50+。", "tags": ["历史自然问法", "第三批人工审核", "防水", "防晒"]},
    {"sku": "OT-188HM", "question": "湖美林丰天幕展开和收纳后分别多大？", "answer": "展开尺寸约360×290×210cm，收纳尺寸约61×14×14cm。", "tags": ["历史自然问法", "第三批人工审核", "尺寸"]},
    {"sku": "OT-188HM", "question": "湖美林丰天幕布是什么材质？", "answer": "材质资料标注为210T涤纶布，单面内涂银。", "tags": ["历史自然问法", "第三批人工审核", "材质"]},

    {"sku": "CW-C33-37", "question": "涮涮锅炉具套装的锅有几升？", "answer": "容量约2L。", "tags": ["历史自然问法", "第三批人工审核", "容量"]},
    {"sku": "CW-C33-37", "question": "涮涮锅这套用高山罐还是卡式罐？", "answer": "高山气罐和卡式气罐都在适配热源资料中。", "tags": ["历史自然问法", "第三批人工审核", "燃料"]},
    {"sku": "CW-C33-37", "question": "涮涮锅套装火力是多少瓦？", "answer": "功率资料标注为2400W。", "tags": ["历史自然问法", "第三批人工审核", "功率"]},

    {"sku": "CT-T04", "question": "出山旗舰茶具的壶、公道杯和小杯各多少毫升？", "answer": "泡茶壶约300ml，公道杯约220ml，品茗杯约24ml。", "tags": ["历史自然问法", "第三批人工审核", "容量"]},
    {"sku": "CT-T04", "question": "出山旗舰茶具是什么材质和表面处理？", "answer": "材质为硬质氧化铝，表面处理资料标注为硬质氧化和陶瓷不沾。", "tags": ["历史自然问法", "第三批人工审核", "材质", "表面处理"]},
    {"sku": "CT-T04", "question": "出山茶具第一次用怎么清洗？", "answer": "首次使用前用温水冲洗茶壶和茶杯即可。", "tags": ["历史自然问法", "第三批人工审核", "首次使用"]},

    {"sku": "CT-T04(BM)", "question": "出山竹套茶具的壶和杯子容量分别多大？", "answer": "泡茶壶约300ml，公道杯约220ml，品茗杯约24ml。", "tags": ["历史自然问法", "第三批人工审核", "容量"]},
    {"sku": "CT-T04(BM)", "question": "竹套版出山茶具是什么材质？", "answer": "主体材质资料标注为硬质氧化铝。", "tags": ["历史自然问法", "第三批人工审核", "材质"]},
    {"sku": "CT-T04(BM)", "question": "出山竹套版整套有多重？", "answer": "重量资料标注约500g。", "tags": ["历史自然问法", "第三批人工审核", "重量"]},

    {"sku": "DV01", "question": "独醒户外酒壶套装是什么材料？", "answer": "材质为硬质氧化铝合金。", "tags": ["历史自然问法", "第三批人工审核", "材质"]},
    {"sku": "DV01", "question": "独醒酒具能装多少毫升？", "answer": "容量资料标注约350ml。", "tags": ["历史自然问法", "第三批人工审核", "容量"]},
    {"sku": "DV01", "question": "独醒酒具的尺寸和重量是多少？", "answer": "尺寸约15.7×7.5cm，重量资料标注约280g。", "tags": ["历史自然问法", "第三批人工审核", "尺寸", "重量"]},

    {"sku": "TW-502", "question": "悦享杯一只是多少毫升？", "answer": "容量资料标注约350ml。", "tags": ["历史自然问法", "第三批人工审核", "容量"]},
    {"sku": "TW-502", "question": "悦享杯的杯身和杯套是什么材质？", "answer": "材质资料标注为304不锈钢和软木护套。", "tags": ["历史自然问法", "第三批人工审核", "材质"]},
    {"sku": "TW-502", "question": "悦享杯可以直接放火上加热吗？", "answer": "不可以。使用说明明确要求避免明火直烧。", "tags": ["历史自然问法", "第三批人工审核", "安全使用"]},

    # Fourth manually reviewed batch.  Customer-facing names deliberately keep
    # historical shorthand, omitted sales suffixes, and common homophones; the
    # answers remain sealed to the listed SKU's formal development-catalog facts.
    {"sku": "CW-C71", "question": "享野3L单锅能装多少？", "answer": "对应3L单锅，容量约3L。", "tags": ["历史自然问法", "第四批人工审核", "语义别名", "容量"]},
    {"sku": "CW-C71", "question": "享野三升锅尺寸多大？", "answer": "对应3L单锅，尺寸约直径19.2×高12.2cm。", "tags": ["历史自然问法", "第四批人工审核", "语义别名", "尺寸"]},
    {"sku": "CW-C71", "question": "享野单锅能用卡式炉吗？", "answer": "可以。3L单锅的适用热源资料包含卡式炉。", "tags": ["历史自然问法", "第四批人工审核", "语义别名", "热源"]},
    {"sku": "CW-C71", "question": "享野3L锅是什么材料？", "answer": "对应3L单锅，材质为硬质氧化铝合金。", "tags": ["历史自然问法", "第四批人工审核", "语义别名", "材质"]},
    {"sku": "CW-C71", "question": "3升享野单锅有多重？", "answer": "对应3L单锅，重量资料标注约445g。", "tags": ["历史自然问法", "第四批人工审核", "语义别名", "重量"]},

    {"sku": "OT-187", "question": "奇幻秘境野餐垫展开多大？", "answer": "对应奇幻秘境限定系列防潮地垫，展开尺寸约200×180cm。", "tags": ["历史自然问法", "第四批人工审核", "语义别名", "尺寸"]},
    {"sku": "OT-187", "question": "奇幻地垫收起来多大？", "answer": "对应奇幻秘境限定系列防潮地垫，收纳尺寸约15×47cm。", "tags": ["历史自然问法", "第四批人工审核", "语义别名", "尺寸"]},
    {"sku": "OT-187", "question": "奇幻秘境防潮垫是什么布料？", "answer": "材质资料标注为磨毛春亚纺。", "tags": ["历史自然问法", "第四批人工审核", "语义别名", "材质"]},
    {"sku": "OT-187", "question": "奇幻地垫弄脏了怎么清理？", "answer": "先抖落泥土或沙粒，再用湿布擦拭污渍，晾干后折叠收入收纳袋。", "tags": ["历史自然问法", "第四批人工审核", "语义别名", "清洁"]},
    {"sku": "OT-187", "question": "奇幻秘境垫子能靠近篝火用吗？", "answer": "不能靠近篝火。使用说明要求远离火源和高温物体。", "tags": ["历史自然问法", "第四批人工审核", "语义别名", "安全使用"]},
    {"sku": "OT-187", "question": "奇幻秘境野餐垫整张有多重？", "answer": "重量资料标注约1381g（约1.38kg）。", "tags": ["历史自然问法", "第四批人工审核", "语义别名", "重量"]},

    {"sku": "PA-B15S-27", "question": "围雪气炉那根配件尺寸是多少？", "answer": "围雪气炉配件尺寸约37×6×4.5cm。", "tags": ["历史自然问法", "第四批人工审核", "语义别名", "尺寸"]},
    {"sku": "PA-B15S-27", "question": "围雪气炉配件有多重？", "answer": "重量资料标注约120g。", "tags": ["历史自然问法", "第四批人工审核", "重量"]},
    {"sku": "PA-B15S-27", "question": "围雪炉的气炉配件是什么材料？", "answer": "材质为硬质氧化铝合金。", "tags": ["历史自然问法", "第四批人工审核", "语义别名", "材质"]},
    {"sku": "PA-B15S-27", "question": "围雪气炉配件火力是多少瓦？", "answer": "功率资料标注为3200W。", "tags": ["历史自然问法", "第四批人工审核", "功率"]},

    {"sku": "PA-CW-C33S-37", "question": "涮涮锅气炉那根配件多大？", "answer": "涮涮锅气炉配件尺寸约37×3×4.5cm。", "tags": ["历史自然问法", "第四批人工审核", "语义别名", "尺寸"]},
    {"sku": "PA-CW-C33S-37", "question": "涮涮锅的气炉配件有多重？", "answer": "重量资料标注约100g。", "tags": ["历史自然问法", "第四批人工审核", "语义别名", "重量"]},
    {"sku": "PA-CW-C33S-37", "question": "涮涮锅气炉配件是什么材质？", "answer": "材质为硬质氧化铝合金。", "tags": ["历史自然问法", "第四批人工审核", "材质"]},
    {"sku": "PA-CW-C33S-37", "question": "涮涮锅气炉配件有多少瓦？", "answer": "功率资料标注为3200W。", "tags": ["历史自然问法", "第四批人工审核", "功率"]},

    {"sku": "KW-K31-黑", "question": "黑色四杯天鹅壶容量多大？", "answer": "黑色天鹅壶4杯款容量约200ml。", "tags": ["历史自然问法", "第四批人工审核", "语义别名", "容量"]},
    {"sku": "KW-K31-黑", "question": "黑天鹅壶尺寸多大？", "answer": "黑色天鹅壶4杯款尺寸约17×7.5cm。", "tags": ["历史自然问法", "第四批人工审核", "语义别名", "尺寸"]},
    {"sku": "KW-K31-黑", "question": "黑色天鹅壶是什么材质？", "answer": "材质资料包含304不锈钢、430不锈钢和尼龙。", "tags": ["历史自然问法", "第四批人工审核", "材质"]},
    {"sku": "KW-K31-黑", "question": "黑天鹅壶可以放卡式炉上吗？", "answer": "可以。黑色天鹅壶4杯款的适用热源资料包含卡式炉。", "tags": ["历史自然问法", "第四批人工审核", "语义别名", "热源"]},
    {"sku": "KW-K31-黑", "question": "黑色四杯天鹅壶有多重？", "answer": "重量资料标注约601g。", "tags": ["历史自然问法", "第四批人工审核", "语义别名", "重量"]},

    {"sku": "KW-K31-白", "question": "白色四杯天鹅壶能装多少？", "answer": "白色天鹅壶4杯款容量约200ml。", "tags": ["历史自然问法", "第四批人工审核", "语义别名", "容量"]},
    {"sku": "KW-K31-白", "question": "白天鹅壶尺寸多大？", "answer": "白色天鹅壶4杯款尺寸约17×7.5cm。", "tags": ["历史自然问法", "第四批人工审核", "语义别名", "尺寸"]},
    {"sku": "KW-K31-白", "question": "白色天鹅壶是什么材料？", "answer": "材质资料包含304不锈钢、430不锈钢和尼龙。", "tags": ["历史自然问法", "第四批人工审核", "材质"]},
    {"sku": "KW-K31-白", "question": "白天鹅壶能直接放明火上吗？", "answer": "可以。白色天鹅壶4杯款的适用热源资料包含明火直烧。", "tags": ["历史自然问法", "第四批人工审核", "语义别名", "热源"]},
    {"sku": "KW-K31-白", "question": "白色四杯天鹅壶有多重？", "answer": "重量资料标注约601g。", "tags": ["历史自然问法", "第四批人工审核", "语义别名", "重量"]},

    {"sku": "CS-G28", "question": "鎏光炉用什么气罐？", "answer": "对应流光炉，适用高山气罐和卡式气罐。", "tags": ["历史自然问法", "第四批人工审核", "近音别名", "热源"]},
    {"sku": "CS-G28", "question": "鎏光炉火力有多大？", "answer": "对应流光炉，功率资料标注为3200W。", "tags": ["历史自然问法", "第四批人工审核", "近音别名", "功率"]},
    {"sku": "CS-G28", "question": "鎏光炉展开和收起来分别多大？", "answer": "对应流光炉，展开尺寸约直径23×高13.5cm，收纳尺寸约直径17×高10.5cm。", "tags": ["历史自然问法", "第四批人工审核", "近音别名", "尺寸"]},
    {"sku": "CS-G28", "question": "这个鎏光小炉是什么材料？", "answer": "对应流光炉，主体材质为304不锈钢。", "tags": ["历史自然问法", "第四批人工审核", "近音别名", "材质"]},
    {"sku": "CS-G28", "question": "鎏光炉本体有多重？", "answer": "对应流光炉，重量资料标注约239g。", "tags": ["历史自然问法", "第四批人工审核", "近音别名", "重量"]},

    {"sku": "CS-G23-42", "question": "麒麟炉EVA包款用哪种气罐？", "answer": "不锈钢本色EVA包款麒麟炉适用高山气罐和卡式气罐。", "tags": ["历史自然问法", "第四批人工审核", "语义别名", "热源"]},
    {"sku": "CS-G23-42", "question": "不锈钢麒麟灶展开和收起来多大？", "answer": "对应EVA包款麒麟炉，展开尺寸约36×25×20cm，收纳尺寸约36×25×10cm。", "tags": ["历史自然问法", "第四批人工审核", "语义别名", "尺寸"]},
    {"sku": "CS-G23-42", "question": "EVA包版麒麟炉有多重？", "answer": "重量资料标注约3480g（约3.48kg）。", "tags": ["历史自然问法", "第四批人工审核", "语义别名", "重量"]},

    {"sku": "CF-PG19", "question": "瓦片盘展开有多大？", "answer": "对应瓦片烤盘，展开尺寸约32×32×3.9cm。", "tags": ["历史自然问法", "第四批人工审核", "语义别名", "尺寸"]},
    {"sku": "CF-PG19", "question": "瓦片烤肉盘是铝的吗？", "answer": "是。瓦片烤盘主体材质为铝合金。", "tags": ["历史自然问法", "第四批人工审核", "语义别名", "材质"]},
    {"sku": "CF-PG19", "question": "瓦片盘能不能空烧？", "answer": "不能。瓦片烤盘的使用说明明确严禁干烧。", "tags": ["历史自然问法", "第四批人工审核", "语义别名", "安全使用"]},
    {"sku": "CF-PG19", "question": "这块瓦片烤肉盘重量多少？", "answer": "重量资料标注约1000g（约1kg）。", "tags": ["历史自然问法", "第四批人工审核", "语义别名", "重量"]},

    {"sku": "CW-C05-37", "question": "2到4人野餐十件套里的锅分别多大？", "answer": "套装包含约1.7L锅、1.4L浅锅和7.5英寸煎盘。", "tags": ["历史自然问法", "第四批人工审核", "语义别名", "容量"]},
    {"sku": "CW-C05-37", "question": "野餐锅十件套能放卡式炉上吗？", "answer": "可以。2-4人野餐锅10件套的适用热源资料包含卡式炉。", "tags": ["历史自然问法", "第四批人工审核", "语义别名", "热源"]},
    {"sku": "CW-C05-37", "question": "城市出逃十件套锅是什么材质？", "answer": "锅具材质为硬质氧化铝合金。", "tags": ["历史自然问法", "第四批人工审核", "语义别名", "材质"]},
    {"sku": "CW-C05-37", "question": "十件野餐锅能不能干烧？", "answer": "不能。2-4人野餐锅10件套的使用说明明确严禁干烧。", "tags": ["历史自然问法", "第四批人工审核", "语义别名", "安全使用"]},
    {"sku": "CW-C05-37", "question": "2到4人锅具十件套有多重？", "answer": "重量资料标注约1030g（约1.03kg）。", "tags": ["历史自然问法", "第四批人工审核", "语义别名", "重量"]},

    {"sku": "CW-DRP01", "question": "导热片能放卡式炉上用吗？", "answer": "可以。导热盘的适用热源资料包含卡式炉。", "tags": ["历史自然问法", "第四批人工审核", "语义别名", "热源"]},
    {"sku": "CW-DRP01", "question": "导热片是什么材料？", "answer": "对应导热盘，材质为硬质氧化铝。", "tags": ["历史自然问法", "第四批人工审核", "语义别名", "材质"]},
    {"sku": "CW-DRP01", "question": "24厘米导热盘有多重？", "answer": "重量资料标注约296g。", "tags": ["历史自然问法", "第四批人工审核", "重量"]},

    {"sku": "CS-B15SPRO", "question": "酒精汽炉版围雪尺寸多大？", "answer": "围雪炉酒精汽炉版尺寸约14×13cm。", "tags": ["历史自然问法", "第四批人工审核", "语义别名", "尺寸"]},
    {"sku": "CS-B15SPRO", "question": "围雪两用炉的酒精和气炉火力分别多少？", "answer": "功率资料标注酒精模式约1100W、气炉模式约3200W。", "tags": ["历史自然问法", "第四批人工审核", "语义别名", "功率"]},
    {"sku": "CS-B15SPRO", "question": "酒精汽炉围雪有多重？", "answer": "围雪炉酒精汽炉版重量资料标注约578g。", "tags": ["历史自然问法", "第四批人工审核", "语义别名", "重量"]},

    {"sku": "CS-B02-37", "question": "城市出逃小酒精炉炉芯多大？", "answer": "酒精炉套装的炉芯容量约100ml。", "tags": ["历史自然问法", "第四批人工审核", "语义别名", "容量"]},
    {"sku": "CS-B02-37", "question": "小酒精炉展开尺寸是多少？", "answer": "酒精炉套装展开尺寸约9.8×9.8×6cm。", "tags": ["历史自然问法", "第四批人工审核", "语义别名", "尺寸"]},
    {"sku": "CS-B02-37", "question": "酒精炉套装本体是什么材料？", "answer": "主体材质为硬质氧化铝合金。", "tags": ["历史自然问法", "第四批人工审核", "材质"]},

    # Fifth manual review batch: rows whose exported chat title was blank but
    # whose marketplace link, associated image and conversation context allowed
    # a same-SKU identity to be recovered.  The link is only an identity hint;
    # each answer below remains restricted to the selected SKU's formal fields.
    {"sku": "AC-Z13", "question": "这套调料瓶是玻璃的吗？", "answer": "不是。调料瓶材质为PET，收纳包材质为300D牛津布。", "tags": ["历史自然问法", "第五批人工审核", "链接身份补全", "材质"]},
    {"sku": "AC-Z13", "question": "调料瓶能不能装热水？", "answer": "不能。使用说明明确禁止装热水。", "tags": ["历史自然问法", "第五批人工审核", "链接身份补全", "安全使用"]},
    {"sku": "AC-Z13", "question": "液体调料瓶一瓶是多少毫升？", "answer": "瓶子容量资料标注约100ml。", "tags": ["历史自然问法", "第五批人工审核", "链接身份补全", "容量"]},
    {"sku": "AC-Z13", "question": "液体瓶和粉罐分别多大？", "answer": "液体瓶约φ4×13.7cm，粉罐约3.8×3.8×9.5cm。", "tags": ["历史自然问法", "第五批人工审核", "链接身份补全", "尺寸"]},
    {"sku": "AC-Z13", "question": "调料瓶套装的收纳包多大？", "answer": "套装包尺寸约15×14×8.5cm。", "tags": ["历史自然问法", "第五批人工审核", "链接身份补全", "尺寸"]},

    {"sku": "AC-19", "question": "这个水袋是10升的吗？", "answer": "不是。稳稳水袋当前容量资料标注为8L。", "tags": ["历史自然问法", "第五批人工审核", "链接身份补全", "容量"]},
    {"sku": "AC-19", "question": "稳稳水袋的水龙头和提手怎么安装？", "answer": "先按压安装水龙头，再安装可拆卸提手；水龙头需要安装到位。", "tags": ["历史自然问法", "第五批人工审核", "链接身份补全", "安装"]},
    {"sku": "AC-19", "question": "稳稳水袋为什么放着比较稳？", "answer": "技术优势资料标注，双水龙头可形成三角结构，提高放置稳定性。", "tags": ["历史自然问法", "第五批人工审核", "链接身份补全", "结构"]},
    {"sku": "AC-19", "question": "稳稳水袋的开口方便清洗吗？", "answer": "技术优势资料标注为开口设计易清洁。", "tags": ["历史自然问法", "第五批人工审核", "链接身份补全", "清洁"]},

    {"sku": "CW-G03S-37", "question": "这个防烫夹是什么材料？", "answer": "材质为硬质氧化铝。", "tags": ["历史自然问法", "第五批人工审核", "链接身份补全", "材质"]},
    {"sku": "CW-G03S-37", "question": "防刮手夹尺寸多大？", "answer": "尺寸约13×4.5cm。", "tags": ["历史自然问法", "第五批人工审核", "链接身份补全", "尺寸"]},
    {"sku": "CW-G03S-37", "question": "防刮手夹主要是做什么用的？", "answer": "用于防烫、防刮并安全夹取锅具。", "tags": ["历史自然问法", "第五批人工审核", "链接身份补全", "用途"]},
    {"sku": "CW-G03S-37", "question": "防刮手夹用完怎么清洁收纳？", "answer": "使用后用湿布擦拭干净，晾干后放在干燥通风处收纳。", "tags": ["历史自然问法", "第五批人工审核", "链接身份补全", "清洁"]},
    {"sku": "CW-G03S-37", "question": "防刮手夹可以直接放火上烧吗？", "answer": "不可以。使用说明要求避免明火直烧。", "tags": ["历史自然问法", "第五批人工审核", "链接身份补全", "安全使用"]},

    {"sku": "CS-G25", "question": "小青炉有没有收纳包？", "answer": "有。使用说明明确从收纳包中取出炉具后使用。", "tags": ["历史自然问法", "第五批人工审核", "链接身份补全", "配件"]},
    {"sku": "CS-G25", "question": "小青炉展开后有多大？", "answer": "展开尺寸约19×19×10.2cm。", "tags": ["历史自然问法", "第五批人工审核", "链接身份补全", "尺寸"]},
    {"sku": "CS-G25", "question": "小青炉是什么材质做的？", "answer": "材质资料包含硬质氧化铝、铝合金、不锈钢、铜和橡胶。", "tags": ["历史自然问法", "第五批人工审核", "链接身份补全", "材质"]},
    {"sku": "CS-G25", "question": "小青炉表面是什么工艺？", "answer": "表面处理资料标注为硬质氧化。", "tags": ["历史自然问法", "第五批人工审核", "链接身份补全", "表面处理"]},

    {"sku": "CW-C06PRO", "question": "轻途套锅能配哪些炉子？", "answer": "适用明火直烧、卡式炉、分体炉和一体炉。", "tags": ["历史自然问法", "第五批人工审核", "链接身份补全", "热源"]},
    {"sku": "CW-C06PRO", "question": "轻途套锅能不能一层层套起来收纳？", "answer": "可以。技术优势资料标注为套娃式收纳。", "tags": ["历史自然问法", "第五批人工审核", "链接身份补全", "收纳"]},
    {"sku": "CW-C06PRO", "question": "轻途这一整套大概多重？", "answer": "重量资料标注约1150g（约1.15kg）。", "tags": ["历史自然问法", "第五批人工审核", "链接身份补全", "重量"]},
    {"sku": "CW-C06PRO", "question": "轻途套锅具体用了哪些材料？", "answer": "材质资料包含3003铝合金、硅胶、不锈钢和PP。", "tags": ["历史自然问法", "第五批人工审核", "链接身份补全", "材质"]},

    {"sku": "GX14-230G", "question": "230克高山罐尺寸多大？", "answer": "尺寸约11×9.5cm。", "tags": ["历史自然问法", "第五批人工审核", "链接身份补全", "尺寸"]},
    {"sku": "GX14-230G", "question": "230G高山气罐是什么材质？", "answer": "材质资料标注为不锈钢。", "tags": ["历史自然问法", "第五批人工审核", "链接身份补全", "材质"]},
    {"sku": "GX14-230G", "question": "230克气罐没用完怎么保存？", "answer": "应存放在阴凉干燥处，远离火源、高温和儿童可触及范围。", "tags": ["历史自然问法", "第五批人工审核", "链接身份补全", "安全存放"]},
    {"sku": "GX14-230G", "question": "230G高山罐废弃后怎么处理？", "answer": "不要投入火中或暴力拆解，应按当地环保规定处理。", "tags": ["历史自然问法", "第五批人工审核", "链接身份补全", "废弃处理"]},

    {"sku": "GX15-450G", "question": "450克高山罐尺寸是多少？", "answer": "尺寸约11×14.5cm。", "tags": ["历史自然问法", "第五批人工审核", "链接身份补全", "尺寸"]},
    {"sku": "GX15-450G", "question": "450G高山气罐是什么材质？", "answer": "材质资料标注为不锈钢。", "tags": ["历史自然问法", "第五批人工审核", "链接身份补全", "材质"]},
    {"sku": "GX15-450G", "question": "450克气罐没用完要怎么存放？", "answer": "应存放在阴凉干燥处，远离火源、高温和儿童可触及范围。", "tags": ["历史自然问法", "第五批人工审核", "链接身份补全", "安全存放"]},
    {"sku": "GX15-450G", "question": "450G高山罐废弃后怎么处理？", "answer": "不要投入火中或暴力拆解，应按当地环保规定处理。", "tags": ["历史自然问法", "第五批人工审核", "链接身份补全", "废弃处理"]},

    {"sku": "AC-Z14", "question": "灵巧包展开以后能自己立住吗？", "answer": "可以。内部钢丝框架展开后会撑开包身。", "tags": ["历史自然问法", "第五批人工审核", "链接身份补全", "结构"]},

    {"sku": "CS-G05-28", "question": "蓝翼分体炉怎么接气罐并点火？", "answer": "将气罐对准炉头接口并顺时针旋紧至密封；再逆时针旋转火力调节阀1-2圈，听到气体溢出声后按下点火装置，重复按压至点燃。", "tags": ["历史自然问法", "第五批人工审核", "链接身份补全", "使用"]},
    {"sku": "CS-G05-28", "question": "蓝翼分体炉尺寸多大？", "answer": "尺寸约15.6×6.5cm。", "tags": ["历史自然问法", "第五批人工审核", "链接身份补全", "尺寸"]},
    {"sku": "CS-G05-28", "question": "蓝翼分体炉是什么材料？", "answer": "材质资料标注为铝合金。", "tags": ["历史自然问法", "第五批人工审核", "链接身份补全", "材质"]},
    {"sku": "CS-G05-28", "question": "蓝翼炉用完后怎么关气收纳？", "answer": "使用后将火力调节阀顺时针旋至关闭位置，待炉具冷却后再拆下气罐收纳。", "tags": ["历史自然问法", "第五批人工审核", "链接身份补全", "使用"]},

    # Sixth manually reviewed batch.  These questions come from medium-
    # frequency blank-title links.  Public listing titles, natural aliases and
    # component wording help identify the SKU, while every answer remains
    # bounded to the current formal same-SKU catalogue facts.
    {"sku": "CW-C65", "question": "城市出逃套锅收起来有多大？", "answer": "收纳尺寸约直径21.4×高12.6cm。", "tags": ["历史自然问法", "第六批人工审核", "中频链接身份补全", "尺寸"]},
    {"sku": "CW-C65", "question": "城市出逃的大锅、小锅、水壶和煎锅分别多大？", "answer": "大锅约直径20.5×高12.6cm，小锅约直径17.8×高9.6cm，水壶约直径14.5×高7.9cm，煎锅约直径21.4×高5.6cm。", "tags": ["历史自然问法", "第六批人工审核", "中频链接身份补全", "尺寸"]},
    {"sku": "CW-C65", "question": "城市出逃套锅的小锅是2.2升吗？", "answer": "当前容量资料标注小锅约2L。", "tags": ["历史自然问法", "第六批人工审核", "中频链接身份补全", "容量"]},
    {"sku": "CW-C65", "question": "城市出逃这一整套毛重多少？", "answer": "毛重资料标注约1837g（约1.84kg）。", "tags": ["历史自然问法", "第六批人工审核", "中频链接身份补全", "重量"]},

    {"sku": "CS-G35", "question": "小圆炉最大火力多少瓦？", "answer": "功率资料标注为2500W。", "tags": ["历史自然问法", "第六批人工审核", "中频链接身份补全", "功率"]},
    {"sku": "CS-G35", "question": "小圆炉的大锅和小壶都能放吗？", "answer": "技术优势资料标注为双层旋转支架，大锅和小壶均可适配。", "tags": ["历史自然问法", "第六批人工审核", "中频链接身份补全", "适配"]},
    {"sku": "CS-G35", "question": "小圆炉有没有自带电子点火？", "answer": "当前正式资料只记录连接气罐后点火，没有明确标注是否自带电子点火器；该项暂时无法确认。", "tags": ["历史自然问法", "第六批人工审核", "中频链接身份补全", "配置待确认"]},

    {"sku": "KD23-MFL", "question": "魔盒桌炉怎么接气罐并点火？", "answer": "将气罐对准炉头接口并顺时针旋紧至密封；再逆时针旋转火力调节阀1-2圈，听到出气声后按下点火装置，点燃后调节火力。", "tags": ["历史自然问法", "第六批人工审核", "中频链接身份补全", "使用"]},
    {"sku": "KD23-MFL", "question": "魔盒用完后怎么关火和拆气罐？", "answer": "将火力调节阀顺时针旋至关闭位置，待炉具冷却后再拆下气罐收纳。", "tags": ["历史自然问法", "第六批人工审核", "中频链接身份补全", "使用"]},
    {"sku": "KD23-MFL", "question": "魔盒桌炉展开后尺寸多大？", "answer": "展开尺寸资料标注约36×25×（15.5/26.5）cm。", "tags": ["历史自然问法", "第六批人工审核", "中频链接身份补全", "尺寸"]},

    {"sku": "GA01-37", "question": "爱路客高山罐接口的气炉想接卡式长罐，用什么转接头？", "answer": "可使用GA01-37卡式长罐转接头转换气罐接口。", "tags": ["历史自然问法", "第六批人工审核", "中频链接身份补全", "适配"]},
    {"sku": "GA01-37", "question": "气罐转接头可以直接碰明火吗？", "answer": "不可以。使用说明要求避免明火直烧。", "tags": ["历史自然问法", "第六批人工审核", "中频链接身份补全", "安全使用"]},

    {"sku": "CW-K04PRO-37", "question": "时光煮水壶和酒精炉能收在一起吗？", "answer": "可以。技术优势资料标注为酒精炉和烧水壶一体收纳。", "tags": ["历史自然问法", "第六批人工审核", "中频链接身份补全", "收纳"]},
    {"sku": "CW-K04PRO-37", "question": "时光煮水整套收起来多大？", "answer": "收纳尺寸约15.5×15.5×11cm。", "tags": ["历史自然问法", "第六批人工审核", "中频链接身份补全", "尺寸"]},

    # Seventh manually reviewed batch.  These are the remaining blank-title
    # links where conversation semantics and current catalogue identity agree.
    # Missing catalogue fields remain explicit knowledge gaps; historical agent
    # claims are not promoted into facts merely because the product alias fits.
    {"sku": "CW-G03S-37", "question": "防烫手夹能夹带裙边的铝饭盒吗？", "answer": "当前资料只确认它用于防烫、防刮并安全夹取锅具，没有记录带裙边铝饭盒的适配测试，因此暂时无法确认。", "tags": ["历史自然问法", "第七批人工审核", "无标题链接身份补全", "适配待确认"]},

    {"sku": "AC-19", "question": "稳稳水袋能反复使用多少次？", "answer": "当前商品资料没有标注固定的可重复使用次数，因此无法给出具体次数。", "tags": ["历史自然问法", "第七批人工审核", "无标题链接身份补全", "资料待确认"]},
    {"sku": "AC-19", "question": "稳稳水袋有检测报告吗？", "answer": "当前知识库记录其通过食品级认证，但没有收录检测报告文件或报告编号，暂时无法提供具体报告。", "tags": ["历史自然问法", "第七批人工审核", "无标题链接身份补全", "认证资料"]},

    {"sku": "DV01", "question": "独醒温酒器要怎么加热？", "answer": "适用热源资料列明明火直烧、卡式炉、分体炉和一体炉，可按所用炉具的安全说明进行加热。", "tags": ["历史自然问法", "第七批人工审核", "无标题链接身份补全", "热源"]},
    {"sku": "DV01", "question": "独醒酒具有没有配瓶塞？", "answer": "当前正式商品资料没有记录是否配有瓶塞，因此暂时无法确认。", "tags": ["历史自然问法", "第七批人工审核", "无标题链接身份补全", "配置待确认"]},

    {"sku": "CS-B15SPRO", "question": "围雪炉酒精汽炉版怎么点火？", "answer": "将炉具放在稳固水平面上，加入约100-200ml的95%液体酒精且不超过炉芯容量的80%，再用打火机或火柴靠近炉芯表面点燃。", "tags": ["历史自然问法", "第七批人工审核", "无标题链接身份补全", "使用"]},

    {"sku": "CW-C06S-37", "question": "乐途套锅能放电磁炉或电陶炉上用吗？", "answer": "当前适用热源资料只列明明火直烧、卡式炉、分体炉和一体炉，没有标注电磁炉或电陶炉兼容，因此暂时无法确认。", "tags": ["历史自然问法", "第七批人工审核", "无标题链接身份补全", "热源待确认"]},

    {"sku": "CS-G05-28", "question": "蓝翼分体炉防不防风？", "answer": "商品卖点资料标注为基础防风。", "tags": ["历史自然问法", "第七批人工审核", "无标题链接身份补全", "防风"]},
    {"sku": "CS-G05-28", "question": "蓝翼炉连续用很久要注意什么？", "answer": "需要保持环境通风，不能在帐篷等密闭空间内使用；气罐要远离明火和高温热源，炉具冷却后再触碰或收纳。当前资料没有标注固定的最长连续使用时长。", "tags": ["历史自然问法", "第七批人工审核", "无标题链接身份补全", "安全使用"]},

    {"sku": "CW-C85-B", "question": "熊猫大侠万象炉是配熊猫大侠套装用的吗？", "answer": "是。技术优势资料明确标注适配熊猫大侠套装。", "tags": ["历史自然问法", "第七批人工审核", "无标题链接身份补全", "适配"]},

    {"sku": "CW-C93", "question": "行山单锅是2.0还是3.0版本？", "answer": "当前行山单锅商品资料没有标注2.0或3.0版本信息，无法只凭版本叫法确认。", "tags": ["历史自然问法", "第七批人工审核", "无标题链接身份补全", "版本待确认"]},

    {"sku": "CS-G23-42", "question": "麒麟炉一天连续用8小时可以吗？", "answer": "当前资料记录功率为5500W，并适配高山气罐和卡式气罐，但没有标注连续使用8小时的额定能力，因此暂时无法确认。", "tags": ["历史自然问法", "第七批人工审核", "无标题链接身份补全", "使用时长待确认"]},
    {"sku": "CS-G23-42", "question": "不锈钢麒麟炉防风吗？", "answer": "商品核心卖点资料标注为强力防风。", "tags": ["历史自然问法", "第七批人工审核", "无标题链接身份补全", "防风"]},

    # Eighth manually reviewed batch.  These questions come from frequent
    # marketplace titles, creator-specific aliases and bundle wording.  The
    # historical title is only an identity hint; each answer below is bounded
    # to the current same-SKU facts, and unresolved catalogue gaps stay explicit.
    {"sku": "CW-C77", "question": "享野套锅可以用电磁炉吗？", "answer": "当前适用热源只列明明火直烧、卡式炉、分体炉和一体炉，未标注电磁炉兼容，因此暂时无法确认。", "tags": ["历史自然问法", "第八批人工审核", "高频标题语义补全", "热源待确认"]},
    {"sku": "CW-C77", "question": "享野这套锅带蒸笼吗？", "answer": "当前套装资料记录了1.7L中锅、0.8L水壶和煎盘，没有记录蒸笼配置，因此暂时无法确认包含蒸笼。", "tags": ["历史自然问法", "第八批人工审核", "高频标题语义补全", "配置待确认"]},

    {"sku": "CS-B15S", "question": "围雪炉酒精版能用环保矿物油吗？", "answer": "不能按矿物油使用。当前使用说明只允许液体或固体酒精，并推荐95%浓度的液体酒精；不要加入资料未确认的燃料。", "tags": ["历史自然问法", "第八批人工审核", "高频标题语义补全", "燃料", "安全使用"]},
    {"sku": "CS-B15S", "question": "围雪炉酒精版还需要配气罐吗？", "answer": "不需要。酒精版使用液体或固体酒精，使用说明推荐95%浓度的液体酒精。", "tags": ["历史自然问法", "第八批人工审核", "高频标题语义补全", "燃料"]},

    {"sku": "MT01-YL", "question": "疯狂游乐园喷枪接高山罐需要转接头吗？", "answer": "当前资料确认喷枪适配高山气罐和卡式气罐，但没有记录两种气罐各自的连接方式或随附转接件，因此暂时无法确认是否需要另配转接头。", "tags": ["历史自然问法", "第八批人工审核", "高频标题语义补全", "适配待确认"]},
    {"sku": "MT01-YL", "question": "疯狂游乐园喷枪的铜管是什么规格？", "answer": "当前材质资料包含铜，但没有记录铜管牌号、口径或壁厚等规格，因此暂时无法确认。", "tags": ["历史自然问法", "第八批人工审核", "高频标题语义补全", "规格待确认"]},

    {"sku": "CW-C85-B", "question": "熊猫大侠万象炉能用卡式气罐吗？", "answer": "可以。当前适用热源资料包含卡式气罐。", "tags": ["历史自然问法", "第八批人工审核", "高频标题语义补全", "燃料"]},
    {"sku": "CW-C85-B", "question": "熊猫大侠万象炉能用固体酒精吗？", "answer": "当前适用热源只列明95%液体工业酒精、高山气罐和卡式气罐，没有标注固体酒精，因此暂时无法确认，不能把液体酒精兼容直接等同为固体酒精兼容。", "tags": ["历史自然问法", "第八批人工审核", "高频标题语义补全", "燃料待确认"]},
    {"sku": "CW-C85-B", "question": "熊猫大侠万象炉可以烧木炭吗？", "answer": "当前适用热源没有记录木炭，只列明95%液体工业酒精、高山气罐和卡式气罐，因此暂时无法确认，不建议使用资料未确认的燃料。", "tags": ["历史自然问法", "第八批人工审核", "高频标题语义补全", "燃料待确认", "安全使用"]},

    {"sku": "GX15-450G", "question": "450克高山气罐有明确保质期吗？", "answer": "当前知识库没有记录具体保质期或到期日期，请以气罐罐体标识和厂家说明为准；罐体如有锈蚀、变形或泄漏等异常不要使用。", "tags": ["历史自然问法", "第八批人工审核", "高频标题语义补全", "资料待确认", "安全使用"]},

    {"sku": "CW-K11-37", "question": "寻唐水壶烧水时提手会烫吗？", "answer": "商品卖点标注提手采用编织防烫设计；烧水后壶身和壶盖仍可能处于高温，取放时应避免直接触碰高温部位并做好防烫。", "tags": ["历史自然问法", "第八批人工审核", "高频标题语义补全", "防烫"]},
    {"sku": "CW-K11-37", "question": "寻唐水壶可以放电陶炉上用吗？", "answer": "当前适用热源只列明明火直烧、卡式炉、分体炉和一体炉，未标注电陶炉兼容，因此暂时无法确认。", "tags": ["历史自然问法", "第八批人工审核", "高频标题语义补全", "热源待确认"]},

    {"sku": "PA-B15S-27", "question": "围雪炉气炉配件能装到小青炉上吗？", "answer": "当前商品资料只确认该配件适配围雪炉，没有记录与小青炉的适配测试，因此暂时无法确认。", "tags": ["历史自然问法", "第八批人工审核", "高频标题语义补全", "适配待确认"]},
    {"sku": "PA-B15S-27", "question": "围雪气炉配件需要配哪种气罐？", "answer": "当前气炉配件资料没有记录气罐接口或适配气罐类型，因此暂时无法确认，需要补充该配件的接口说明。", "tags": ["历史自然问法", "第八批人工审核", "高频标题语义补全", "燃料待确认"]},

    {"sku": "CB253", "question": "聚能环水壶底下的聚能环能拆吗？", "answer": "当前资料只确认水壶采用底部聚能环设计，没有记录聚能环是否可拆卸，因此暂时无法确认。", "tags": ["历史自然问法", "第八批人工审核", "高频标题语义补全", "结构待确认"]},
    {"sku": "CB253", "question": "聚能环水壶里面带滤网吗？", "answer": "当前正式资料没有记录内置滤网或随附茶滤，因此暂时无法确认。", "tags": ["历史自然问法", "第八批人工审核", "高频标题语义补全", "配置待确认"]},

    {"sku": "CW-K03-37", "question": "1.4升户外水壶可以放洗碗机吗？", "answer": "当前使用说明只记录用温水和软布清洗，没有标注洗碗机兼容，因此暂时无法确认；建议按现有说明手洗并及时擦干。", "tags": ["历史自然问法", "第八批人工审核", "高频标题语义补全", "清洗"]},
    {"sku": "CW-K03-37", "question": "1.4升户外水壶能用电磁炉吗？", "answer": "当前适用热源只列明明火直烧、卡式炉、分体炉和一体炉，未标注电磁炉兼容，因此暂时无法确认。", "tags": ["历史自然问法", "第八批人工审核", "高频标题语义补全", "热源待确认"]},

    {"sku": "CW-C65", "question": "城市出逃套锅能放洗碗机清洗吗？", "answer": "当前使用说明只记录用温水清洗并及时擦干，没有标注洗碗机兼容，因此暂时无法确认；建议按现有说明手洗。", "tags": ["历史自然问法", "第八批人工审核", "高频标题语义补全", "清洗"]},
    {"sku": "CW-C65", "question": "城市出逃套锅的煎锅炒菜会粘吗？", "answer": "当前表面处理资料只标注硬质氧化，没有标注不粘涂层，因此不能保证不粘；使用说明建议中小火预热2-3分钟后再倒油烹饪。", "tags": ["历史自然问法", "第八批人工审核", "高频标题语义补全", "表面处理", "使用"]},

    {"sku": "CW-C96", "question": "京享套锅留下痕迹用洗洁精洗不掉怎么办？", "answer": "当前清洁说明要求用温水清洗、避免金属工具刮擦，并在洗后及时擦干；没有记录小苏打等特殊去痕方法，顽固痕迹的处理方式暂时无法确认。", "tags": ["历史自然问法", "第八批人工审核", "高频标题语义补全", "清洗"]},

    {"sku": "CW-C65-1", "question": "城市出逃套锅的大锅是多少升？", "answer": "大锅容量资料标注约3.5L。", "tags": ["历史自然问法", "第八批人工审核", "高频标题语义补全", "容量"]},
    {"sku": "CW-C65-1", "question": "城市出逃套锅大锅是什么材质？", "answer": "材质资料标注为硬质氧化铝合金。", "tags": ["历史自然问法", "第八批人工审核", "高频标题语义补全", "材质"]},
    {"sku": "CW-C65-1", "question": "城市出逃套锅大锅能放燃气灶上吗？", "answer": "可以。当前适用热源资料包含明火直烧。", "tags": ["历史自然问法", "第八批人工审核", "高频标题语义补全", "热源"]},

    {"sku": "CW-C65-5", "question": "城市出逃小单锅的直径和高度是多少？", "answer": "尺寸资料标注约直径19.5×高12.6cm。", "tags": ["历史自然问法", "第八批人工审核", "高频标题语义补全", "尺寸"]},
    {"sku": "CW-C65-5", "question": "城市出逃小单锅放升级款酒精炉上能稳住吗？", "answer": "当前资料确认小单锅适用明火直烧，但没有记录与所说升级款酒精炉的稳定性适配测试，因此暂时无法确认。", "tags": ["历史自然问法", "第八批人工审核", "高频标题语义补全", "适配待确认"]},

    {"sku": "CW-C19T-37", "question": "旅伴2到3人套锅里的锅、水壶和煎盘分别多大？", "answer": "套装资料标注包含2.2L锅、1.4L水壶和7.5英寸煎盘。", "tags": ["历史自然问法", "第八批人工审核", "高频标题语义补全", "容量"]},
    {"sku": "CW-C19T-37", "question": "旅伴2到3人套锅是什么材质？", "answer": "材质资料标注为硬质氧化铝和耐高温硅胶。", "tags": ["历史自然问法", "第八批人工审核", "高频标题语义补全", "材质"]},
    {"sku": "CW-C19T-37", "question": "旅伴2到3人套锅能用电磁炉吗？", "answer": "当前适用热源只列明明火直烧、卡式炉、分体炉和一体炉，未标注电磁炉兼容，因此暂时无法确认。", "tags": ["历史自然问法", "第八批人工审核", "高频标题语义补全", "热源待确认"]},
    {"sku": "CW-C19T-37", "question": "旅伴套锅是304不锈钢的吗？", "answer": "不是按304不锈钢记录。当前材质资料标注为硬质氧化铝和耐高温硅胶。", "tags": ["历史自然问法", "第八批人工审核", "高频标题语义补全", "材质"]},

    {"sku": "KD23-MFL", "question": "魔盒桌炉一定要用高山气罐吗？", "answer": "当前使用说明只记录连接气罐的步骤，没有记录明确的气罐接口或适配气罐类型，因此暂时无法确认。", "tags": ["历史自然问法", "第八批人工审核", "高频标题语义补全", "燃料待确认"]},
    {"sku": "KD23-MFL", "question": "魔盒卡式炉能配烧烤盘吗？", "answer": "当前商品资料没有记录烧烤盘型号或尺寸适配关系，因此暂时无法确认，需要按具体烤盘尺寸核对。", "tags": ["历史自然问法", "第八批人工审核", "高频标题语义补全", "适配待确认"]},
    {"sku": "KD23-MFL", "question": "魔盒这个链接包含炉子和拓展板吗？", "answer": "当前SKU对应魔盒卡式炉本体，商品名称明确标注不含拓展板；其他随附件没有完整清单，暂时无法继续确认。", "tags": ["历史自然问法", "第八批人工审核", "高频标题语义补全", "配置"]},

    {"sku": "TX-38", "question": "坐忘实木款的壶身和手柄分别是什么材质？", "answer": "壶身材质为硬质氧化铝合金，手柄材质为鸡翅木。", "tags": ["历史自然问法", "第八批人工审核", "高频标题语义补全", "材质"]},

    {"sku": "CS-B14", "question": "旋焰酒精炉出现跳火怎么办？", "answer": "当前资料没有给出“跳火”的单一原因。应先停止使用并灭火，确认使用95%液体工业酒精、炉具放在平整位置，且没有在燃烧中途添加燃料；仍有异常时请停用并联系售后排查。", "tags": ["历史自然问法", "第八批人工审核", "高频标题语义补全", "异常处理", "安全使用"]},

    {"sku": "TW-139", "question": "黑盖铝饭盒可以放微波炉加热吗？", "answer": "不可以。饭盒材质为硬质氧化铝，当前适用热源只列明明火直烧、卡式炉、分体炉和一体炉，不包含微波炉。", "tags": ["历史自然问法", "第八批人工审核", "高频标题语义补全", "热源", "安全使用"]},
    {"sku": "TW-139", "question": "黑盖铝饭盒的铝板厚度是多少？", "answer": "当前商品资料记录了整体尺寸和材质，但没有标注铝板厚度，因此暂时无法确认。", "tags": ["历史自然问法", "第八批人工审核", "高频标题语义补全", "规格待确认"]},

    {"sku": "CW-C99B", "question": "小方锅是单个锅还是一整套？", "answer": "当前SKU对应单个1.7L小方锅，不是套锅组合。", "tags": ["历史自然问法", "第八批人工审核", "高频标题语义补全", "配置"]},

    {"sku": "OF-16CS", "question": "城市出逃轻羽椅带保护套吗？", "answer": "当前使用说明确认折叠后可收入收纳袋，但没有记录额外的独立保护套，因此暂时无法确认另带保护套。", "tags": ["历史自然问法", "第八批人工审核", "高频标题语义补全", "配置待确认"]},

    {"sku": "CS-G05-28", "question": "蓝翼分体炉在海拔5000米能用吗？", "answer": "当前资料确认适配高山气罐和卡式气罐，但没有标注5000米海拔的额定使用能力或测试结果，因此暂时无法确认。", "tags": ["历史自然问法", "第八批人工审核", "高频标题语义补全", "高海拔待确认"]},

    {"sku": "TW-141", "question": "烽宴聚能套锅煮米饭有专门教程吗？", "answer": "当前商品资料没有记录专门的米水比例或焖煮时长教程，因此暂时无法提供该产品的固定煮饭参数。", "tags": ["历史自然问法", "第八批人工审核", "高频标题语义补全", "使用资料待确认"]},
)


def ensure_development_target() -> None:
    if str(settings.APP_ENV or "").lower() != "dev":
        raise RuntimeError("Product catalog reconciliation requires APP_ENV=dev.")
    if database_name_from_url(str(settings.DATABASE_URL or "")) != "product_knowledge_dev":
        raise RuntimeError("Product catalog reconciliation requires product_knowledge_dev.")


def _normalize_question(value: Any) -> str:
    return re.sub(r"\s+", "", str(value or "")).casefold()


def _json_value(value: Any, *, field: str, sku: str) -> Any:
    if isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError as exc:
            raise ValueError(f"{sku} {field} is not valid JSON: {exc}") from exc
    return value


def _json_string(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False)


def _product_and(model, db, sku: str):
    product = db.query(Product).filter(Product.sku == sku).first()
    if product is None:
        raise ValueError(f"Product not found in development database: {sku}")
    row = db.query(model).filter(model.product_id == product.id).first()
    if row is None:
        raise ValueError(f"{model.__tablename__} row not found for {sku}")
    return product, row


def _replace_once_or_confirmed_new(values: list[str], old: str, new: str, *, sku: str, field: str) -> bool:
    old_count = sum(value == old for value in values)
    new_count = sum(value == new for value in values)
    if old_count == 0:
        if new_count == 1:
            return False
        raise ValueError(f"{sku} {field} expected exactly one {old!r} or {new!r}; got {values!r}")
    if old_count != 1 or new_count:
        raise ValueError(f"{sku} {field} old/new value assertion failed: {values!r}")
    index = values.index(old)
    values[index] = new
    return True


def apply_product_field_corrections(db) -> set[str]:
    changed_skus: set[str] = set()
    for sku, replacements in CAPACITY_CORRECTIONS.items():
        _, specs = _product_and(ProductSpecs, db, sku)
        raw = _json_value(specs.capacity, field="capacity", sku=sku)
        if not isinstance(raw, list) or not all(isinstance(item, dict) for item in raw):
            raise ValueError(f"{sku} capacity must be a JSON list of objects: {raw!r}")
        values = [str(item.get("value") or "").strip() for item in raw]
        sku_changed = False
        for old, new in replacements:
            # Replace inside a labelled value such as "2L锅" while still
            # requiring exactly one matching value in the same SKU.
            # Check the new value first: `3L` is a substring of `1.3L`, and
            # `4L` is a substring of `1.4L`; treating those as old values on a
            # second run would break the promised idempotence.
            matching = [index for index, value in enumerate(values) if old in value]
            confirmed_new = [index for index, value in enumerate(values) if new in value]
            if confirmed_new:
                if len(confirmed_new) == 1 and all(index == confirmed_new[0] for index in matching):
                    continue
                raise ValueError(f"{sku} capacity value assertion failed for {old!r}: {values!r}")
            if len(matching) != 1:
                raise ValueError(f"{sku} capacity value assertion failed for {old!r}: {values!r}")
            index = matching[0]
            values[index] = values[index].replace(old, new, 1)
            raw[index]["value"] = values[index]
            sku_changed = True
        if sku_changed:
            specs.capacity = _json_string(raw)
            changed_skus.add(sku)

    for sku, (old, new) in SELLING_POINT_CORRECTIONS.items():
        _, business = _product_and(ProductBusiness, db, sku)
        raw = _json_value(business.top_selling_points, field="top_selling_points", sku=sku)
        if not isinstance(raw, list) or not all(isinstance(item, str) for item in raw):
            raise ValueError(f"{sku} top_selling_points must be a JSON list of strings: {raw!r}")
        if _replace_once_or_confirmed_new(raw, old, new, sku=sku, field="top_selling_points"):
            business.top_selling_points = _json_string(raw)
            changed_skus.add(sku)

    for sku, (old, new) in WEIGHT_CORRECTIONS.items():
        _, specs = _product_and(ProductSpecs, db, sku)
        current = Decimal(str(specs.gross_weight_g))
        if current == old:
            specs.gross_weight_g = new
            changed_skus.add(sku)
        elif current != new:
            raise ValueError(f"{sku} gross_weight_g expected {old} or {new}, got {current}")

    for sku, replacements in SIZE_INFO_CORRECTIONS.items():
        _, specs = _product_and(ProductSpecs, db, sku)
        raw = _json_value(specs.size_info, field="size_info", sku=sku)
        if not isinstance(raw, list) or not all(isinstance(item, dict) for item in raw):
            raise ValueError(f"{sku} size_info must be a JSON list of objects: {raw!r}")
        sku_changed = False
        for label, old, new in replacements:
            matches = [item for item in raw if str(item.get("label") or "").strip() == label]
            if len(matches) != 1:
                raise ValueError(f"{sku} size_info expected exactly one label {label!r}: {raw!r}")
            item = matches[0]
            current = str(item.get("value") or "").strip()
            if current == old:
                item["value"] = new
                sku_changed = True
            elif current != new:
                raise ValueError(
                    f"{sku} size_info/{label} expected {old!r} or {new!r}, got {current!r}"
                )
        if sku_changed:
            specs.size_info = _json_string(raw)
            changed_skus.add(sku)

    return changed_skus


def _find_qa(db, sku: str, question: str) -> ProductQa:
    product = db.query(Product).filter(Product.sku == sku).first()
    if product is None:
        raise ValueError(f"Product not found for QA correction: {sku}")
    matches = [
        qa
        for qa in db.query(ProductQa).filter(ProductQa.product_id == product.id).all()
        if _normalize_question(qa.question) == _normalize_question(question)
    ]
    if len(matches) != 1:
        raise ValueError(f"Expected one QA for {sku}/{question!r}, found {len(matches)}")
    return matches[0]


def apply_existing_qa_corrections(db) -> tuple[set[str], set[Any]]:
    changed_skus: set[str] = set()
    changed_qa_ids: set[Any] = set()
    for item in QA_ANSWER_CORRECTIONS:
        qa = _find_qa(db, item["sku"], item["question"])
        if qa.answer == item["old_answer"]:
            qa.answer = item["new_answer"]
            qa.integrity_status = "review"
            qa.integrity_reason = None
            qa.integrity_model = None
            qa.integrity_audited_at = None
            changed_skus.add(item["sku"])
            changed_qa_ids.add(qa.id)
        elif qa.answer != item["new_answer"]:
            raise ValueError(
                f"QA answer assertion failed for {item['sku']}/{item['question']!r}; "
                f"current answer is not the expected old or new value."
            )
    return changed_skus, changed_qa_ids


def add_supplemental_qa(db) -> tuple[set[str], set[Any], int, int, int]:
    changed_skus: set[str] = set()
    changed_rows: list[ProductQa] = []
    created = 0
    tag_updates = 0
    skipped = 0
    for item in SUPPLEMENTAL_QA:
        product = db.query(Product).filter(Product.sku == item["sku"]).first()
        if product is None:
            raise ValueError(f"Product not found for supplemental QA: {item['sku']}")
        normalized = _normalize_question(item["question"])
        existing = [
            qa
            for qa in db.query(ProductQa).filter(ProductQa.product_id == product.id).all()
            if _normalize_question(qa.question) == normalized
        ]
        if existing:
            if len(existing) != 1 or str(existing[0].answer or "").strip() != item["answer"]:
                raise ValueError(f"Supplemental QA conflicts with existing question: {item['sku']}/{item['question']}")
            qa = existing[0]
            try:
                current_tags = json.loads(str(qa.tags or "[]"))
            except (TypeError, ValueError):
                current_tags = []
            current_tags = (
                [str(tag).strip() for tag in current_tags if str(tag).strip()]
                if isinstance(current_tags, list)
                else []
            )
            merged_tags = list(dict.fromkeys([*current_tags, *item["tags"]]))
            if merged_tags != current_tags:
                qa.tags = _json_string(merged_tags)
                changed_rows.append(qa)
                changed_skus.add(item["sku"])
                tag_updates += 1
            else:
                skipped += 1
            continue
        qa = ProductQa(
            product_id=product.id,
            question=item["question"],
            answer=item["answer"],
            tags=_json_string(item["tags"]),
            priority=2,
            integrity_status="review",
        )
        db.add(qa)
        changed_rows.append(qa)
        changed_skus.add(item["sku"])
        created += 1
    db.flush()
    return changed_skus, {qa.id for qa in changed_rows}, created, tag_updates, skipped


async def audit_affected_qas(
    db,
    skus: set[str],
    audit_user: User,
    *,
    qa_ids: set[Any],
    full_skus: set[str],
) -> dict[str, Any]:
    counts = {"approved": 0, "rejected": 0, "review": 0}
    rows = 0
    for sku in sorted(skus):
        product = db.query(Product).filter(Product.sku == sku).first()
        if product is None:
            raise ValueError(f"Product disappeared before QA audit: {sku}")
        query = db.query(ProductQa).filter(ProductQa.product_id == product.id)
        if sku not in full_skus:
            if not qa_ids:
                continue
            query = query.filter(ProductQa.id.in_(qa_ids))
        qas = query.order_by(ProductQa.created_at.asc()).all()
        for qa in qas:
            verdict = await product_qa_integrity_service.audit_product_qa_item(
                db,
                product,
                qa,
                user=audit_user,
            )
            status = str(verdict.get("status") or "review")
            counts[status] = counts.get(status, 0) + 1
            rows += 1
            print(json.dumps({"event": "qa_audit", "sku": sku, "qa_id": str(qa.id), "status": status, "reason": verdict.get("reason", "")}, ensure_ascii=False), flush=True)
    db.commit()
    return {"rows": rows, "counts": counts}


def sync_affected_products(db, skus: set[str]) -> dict[str, Any]:
    results: list[dict[str, Any]] = []
    for sku in sorted(skus):
        result = product_service.sync_product_to_vector_db(db, sku)
        results.append(result)
        print(json.dumps({"event": "vector_sync", **result}, ensure_ascii=False), flush=True)
    return {
        "products": len(results),
        "ready": sum(1 for item in results if item.get("ready_for_rag")),
        "failed": sum(1 for item in results if item.get("error") or not item.get("ready_for_rag")),
        "results": results,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="Persist corrections and supplemental QA.")
    parser.add_argument("--no-audit", action="store_true", help="Do not run the semantic QA audit after applying.")
    parser.add_argument("--no-sync", action="store_true", help="Do not reindex/embed affected SKUs after auditing.")
    args = parser.parse_args()
    ensure_development_target()

    db = SessionLocal()
    try:
        product_changed_skus = apply_product_field_corrections(db)
        corrected_qa_skus, corrected_qa_ids = apply_existing_qa_corrections(db)
        qa_skus, changed_qa_ids, created, tag_updates, skipped = add_supplemental_qa(db)
        changed_skus = set(product_changed_skus)
        changed_skus.update(corrected_qa_skus)
        changed_skus.update(qa_skus)
        qa_audit_ids = corrected_qa_ids | changed_qa_ids
        plan = {
            "source_metadata": SOURCE_METADATA,
            "source_history": SOURCE_HISTORY,
            "apply": args.apply,
            "affected_skus": sorted(changed_skus),
            "supplemental_qa_created": created,
            "supplemental_qa_tag_updates": tag_updates,
            "supplemental_qa_skipped_existing": skipped,
            "qa_audit_target_rows": len(qa_audit_ids),
            "qa_audit_full_product_skus": sorted(product_changed_skus),
        }
        if not args.apply:
            db.rollback()
            print(json.dumps({**plan, "message": "dry-run: no database changes persisted"}, ensure_ascii=False, indent=2))
            return 0

        db.commit()
        audit_result: dict[str, Any] | None = None
        sync_result: dict[str, Any] | None = None
        if not args.no_audit:
            audit_user = db.query(User).filter(User.username == "admin", User.is_active.is_(True)).first()
            if audit_user is None:
                raise RuntimeError("An active development admin user is required for semantic QA audit.")
            audit_result = asyncio.run(audit_affected_qas(
                db,
                changed_skus,
                audit_user,
                qa_ids=qa_audit_ids,
                full_skus=product_changed_skus,
            ))
        if not args.no_sync:
            sync_result = sync_affected_products(db, changed_skus)
        print(json.dumps({**plan, "audit": audit_result, "vector_sync": sync_result}, ensure_ascii=False, indent=2))
        return 0
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
