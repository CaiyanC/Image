"""Seed six manually reviewed, non-factual experience-RAG pilot cards in dev."""

from __future__ import annotations

import asyncio
import hashlib
import json
import sys
import uuid
from pathlib import Path


BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.core.config import database_name_from_url, settings  # noqa: E402
from app.core.database import SessionLocal  # noqa: E402
from app.models.knowledge_base import KnowledgeChunk, KnowledgeDocument  # noqa: E402
from app.models.product import Product  # noqa: E402
from app.services import knowledge_service, product_vector_index_service  # noqa: E402


SOURCE_FILE = (
    "D:/CaiYan/用户评价与客服对话/"
    "爱路客_多平台客服RAG整理_含千牛_20260903_v12/"
    "09_严格产品映射与三链路RAG"
)

CARDS = [
    {
        "sku": "CS-B14",
        "slug": "scenario-choice",
        "intent": "选购与推荐",
        "title": "旋焰酒精炉：场景选择与火力顾虑",
        "source_record_ids": [
            "chat_qianniu_千牛_千牛6月22日-7月22日聊天明细_46",
            "chat_qianniu_千牛_千牛_76",
            "chat_qianniu_千牛_千牛_198",
        ],
        "content": (
            "客户常见顾虑：是否适合自己的煮茶、烧水或简单烹饪，火力是否够，以及与其他炉具怎么选。\n"
            "沟通策略：先结合本轮商品事实给出明确倾向，再用一到两个最相关的事实解释取舍；环境、锅具或用途确实会改变结论时再说明条件。比较时不能只说‘看需求’或‘两款不一样’，要把各自适合什么讲清楚。\n"
            "边界：资料没有证明的人数适配、烧开时长或效果不能保证，也不能用承重、功率等单一参数直接推出‘一定够用’。\n"
            "自然下一步：只有缺少关键变量时，简短询问主要用途或锅具大小。"
        ),
    },
    {
        "sku": "CS-B14",
        "slug": "fuel-safety",
        "intent": "使用方法与安全",
        "title": "旋焰酒精炉：燃料使用与安全承接",
        "source_record_ids": [
            "chat_jdpop_20aa0d55f5039f81a0c640b7ac1bd0d0",
            "chat_qianniu_千牛_千牛4月13~19日聊天明细_127",
            "chat_qianniu_千牛_千牛6月22日-7月22日聊天明细_1",
        ],
        "content": (
            "客户常见顾虑：燃料怎么选、怎么点火、何时补充、如何熄火以及使用是否安全。\n"
            "沟通策略：先直接回答客户问的能否或操作边界，再按本轮事实给出必要步骤和一条最重要的安全提醒；不要用一句‘安全’代替说明。\n"
            "边界：燃料范围、浓度、燃烧时间和操作步骤都必须来自当前商品事实或同 SKU 已审核 QA；没有资料的危险操作不做经验推断。\n"
            "自然下一步：若客户描述异常，先建议停止继续操作，再询问具体状态或引导按售后流程核实。"
        ),
    },
    {
        "sku": "CW-C01-37",
        "slug": "kit-version",
        "intent": "套装与配件",
        "title": "1—2人野营锅7件套：配置与版本确认",
        "source_record_ids": [
            "chat_jdpop_21bd4f0b618c3644f61fc51b1ee60343",
            "chat_jdpop_35b640c1e2b9b5c22ae09a0e992e9415",
            "chat_jdpop_813c6afa5af760e72cdd1edbd10bcab4",
        ],
        "content": (
            "客户常见顾虑：套装是否齐全、不同版本分别包含什么、是否还要另购燃料或连接件。\n"
            "沟通策略：先说当前事实能确认的包含项和兼容范围，再明确区分‘产品具备某能力’与‘当前下单版本实际随货包含’；不能只发链接或笼统说都有。\n"
            "边界：资料没有逐项列出的配件不得补全，不同版本的部件不能合并成一份配置。\n"
            "自然下一步：确需确认订单配置时，只追问客户正在看的版本或请其核对页面配置清单。"
        ),
    },
    {
        "sku": "CW-C01-37",
        "slug": "two-person-concern",
        "intent": "选购与推荐",
        "title": "1—2人野营锅7件套：双人轻量选购顾虑",
        "source_record_ids": [
            "chat_jdpop_21bd4f0b618c3644f61fc51b1ee60343",
            "chat_jdpop_234eae58-59cc-4c3e-86e2-bb818f67c929",
            "chat_jdpop_54d13e855107637f6cf6bb38c9ca4bba",
        ],
        "content": (
            "客户常见顾虑：两个人简单露营是否合适、锅具是否方便操作、做工和耐用性是否值得。\n"
            "沟通策略：先按客户的核心场景给明确倾向，再讲最相关的容量、重量、结构或配置取舍；顾虑要正面承接，不用‘放心’、‘不会失望’等空泛承诺。\n"
            "边界：人数、耐用、便携或够用等结论必须有当前事实支持；资料只给参数时，应把参数和适用性判断分开。\n"
            "自然下一步：如果客户的烹饪量或燃料选择会改变推荐，再问一个关键问题，不连续盘问。"
        ),
    },
    {
        "sku": "CF-PG19",
        "slug": "heat-care",
        "intent": "适用热源与使用养护",
        "title": "瓦片烤盘：热源兼容与养护说明",
        "source_record_ids": [
            "chat_qianniu_千牛_千牛3月09~15日聊天明细_38",
            "chat_qianniu_千牛_千牛3月02~08日聊天明细_15",
            "chat_qianniu_千牛_千牛_137",
        ],
        "content": (
            "客户常见顾虑：自己的炉具能不能用、是否推荐这样用，以及首次使用和清洗养护。\n"
            "沟通策略：兼容性先给明确结论，再说明必要条件；把‘资料确认可以’、‘可以但不建议’和‘资料未确认’分开表达。养护问题按当前事实给简短步骤和关键禁忌。\n"
            "边界：不能从宽泛热源词推导具体兼容，也不能把其他锅具的养护方法套用过来。\n"
            "自然下一步：只有炉具型号或使用异常决定答案时才追问。"
        ),
    },
    {
        "sku": "CF-PG19",
        "slug": "value-objection",
        "intent": "价格顾虑与选购",
        "title": "瓦片烤盘：价格与价值顾虑承接",
        "source_record_ids": [
            "chat_qianniu_千牛_千牛5月11~17日聊天明细_130",
            "chat_qianniu_千牛_千牛_170",
            "chat_qianniu_千牛_千牛_137",
        ],
        "content": (
            "客户常见顾虑：价格偏高、和普通烤盘相比差在哪里、自己的场景是否值得购买。\n"
            "沟通策略：先认可客户在比较价值，再只选两三个与其场景直接相关、且由本轮事实证明的差异说明取舍；最后给条件式建议，让客户知道什么情况下值得、什么情况下基础款已足够。\n"
            "避免表达：不要说‘贵是因为质量好’、‘不会失望’或未经证明的更耐用、更健康、更高级；不要把整份参数表重复一遍。\n"
            "自然下一步：价格或活动需要实时数据时说明当前无法承诺，可询问客户最看重面积、热源兼容还是便携。"
        ),
    },
]


def _metadata(card: dict, product: Product) -> dict:
    source_record_ids = list(card["source_record_ids"])
    product_key = str(product.id)
    return {
        "productKey": product_key,
        "productName": product.product_name_cn,
        "sku": product.sku,
        "productRefs": [{
            "productKey": product_key,
            "sku": product.sku,
            "barcode": product.barcode,
            "productName": product.product_name_cn,
        }],
        "productMatchStatus": "matched_confirmed",
        "result": {"label": "manually_reviewed_experience_card"},
        "reviewStatus": "approved_pilot",
        "review_status": "approved_pilot",
        "productionUse": "experience_guidance_only",
        "production_use": "experience_guidance_only",
        "answerApprovedForStandard": False,
        "sourceRecordId": source_record_ids[0],
        "sourceRecordIds": source_record_ids,
        "sourceFile": SOURCE_FILE,
        "intent": card["intent"],
        "authority_level": "candidate_only",
        "fact_authority": False,
        "manual_reviewed": True,
        "pilot_version": "experience-rag-v1",
    }


def _upsert_card(
    db,
    card: dict,
    product: Product,
) -> tuple[KnowledgeDocument, str, bool]:
    source_id = f"customer_experience:pilot:v1:{product.sku}:{card['slug']}"
    metadata = _metadata(card, product)
    metadata_json = json.dumps(metadata, ensure_ascii=False)
    chunk_metadata_json = json.dumps(
        {"title": card["title"], **metadata},
        ensure_ascii=False,
    )
    document = db.query(KnowledgeDocument).filter(
        KnowledgeDocument.source_type == knowledge_service.CUSTOMER_EXPERIENCE_SOURCE_TYPE,
        KnowledgeDocument.source_id == source_id,
    ).first()
    action = "updated"
    document_changed = False
    if document is None:
        document = KnowledgeDocument(
            id=str(uuid.uuid4()),
            source_type=knowledge_service.CUSTOMER_EXPERIENCE_SOURCE_TYPE,
            source_id=source_id,
            sku=product.sku,
            title=card["title"],
            content=card["content"],
            metadata_json=metadata_json,
            file_hash=hashlib.sha256(source_id.encode("utf-8")).hexdigest(),
            parse_status="done",
            is_active=True,
        )
        db.add(document)
        db.flush()
        action = "created"
        document_changed = True
    else:
        document_changed = any((
            document.sku != product.sku,
            document.title != card["title"],
            document.content != card["content"],
            document.metadata_json != metadata_json,
            document.parse_status != "done",
            document.parse_error is not None,
            document.is_active is not True,
        ))
        document.sku = product.sku
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
        chunk.sku != product.sku,
        chunk.source_type != knowledge_service.CUSTOMER_EXPERIENCE_SOURCE_TYPE,
        content_changed,
        chunk.metadata_json != chunk_metadata_json,
    ))
    chunk.sku = product.sku
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
    if action != "created":
        action = "updated" if document_changed or chunk_changed or len(chunks) > 1 else "unchanged"
    db.commit()
    db.refresh(document)
    return document, action, needs_embedding


async def main() -> int:
    database_name = database_name_from_url(settings.DATABASE_URL)
    if settings.APP_ENV != "dev" or database_name != "product_knowledge_dev":
        raise RuntimeError(
            f"Refusing to seed outside dev: APP_ENV={settings.APP_ENV!r}, database={database_name!r}"
        )

    db = SessionLocal()
    try:
        products = {
            product.sku: product
            for product in db.query(Product).filter(
                Product.sku.in_([card["sku"] for card in CARDS])
            ).all()
        }
        missing = sorted({card["sku"] for card in CARDS} - set(products))
        if missing:
            raise RuntimeError(f"Pilot products do not exist in product master: {missing}")

        created = 0
        updated = 0
        unchanged = 0
        embedded = 0
        failed = 0
        for card in CARDS:
            document, action, needs_embedding = _upsert_card(
                db,
                card,
                products[card["sku"]],
            )
            created += int(action == "created")
            updated += int(action == "updated")
            unchanged += int(action == "unchanged")
            if needs_embedding:
                result = await product_vector_index_service.embed_pending_chunks(
                    db,
                    document_id=document.id,
                )
                embedded += int(result.get("embedded") or 0)
                failed += int(result.get("failed") or 0)

        print(json.dumps({
            "database": database_name,
            "cards": len(CARDS),
            "created": created,
            "updated": updated,
            "unchanged": unchanged,
            "embedded": embedded,
            "failed": failed,
            "skus": sorted(products),
        }, ensure_ascii=False))
        return 0 if failed == 0 else 1
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
