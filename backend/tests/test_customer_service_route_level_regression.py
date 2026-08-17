import json
import re
import tempfile

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.database import Base, get_db
from app.core.permission_constants import MANAGEMENT_GROUP_NAME
from app.core.security import create_access_token
from app.main import app
from app.models import (
    AgentAction,
    Certification,
    CustomerServiceConversation,
    CustomerServiceMessage,
    Group,
    Keyword,
    KnowledgeChunk,
    KnowledgeDocument,
    ListingChannel,
    OperationLog,
    Product,
    ProductBusiness,
    ProductCertification,
    ProductContent,
    ProductKeyword,
    ProductListingChannel,
    ProductMedia,
    ProductPrompts,
    ProductQa,
    ProductQaNegative,
    ProductSalesRegion,
    ProductSpecs,
    SalesRegion,
    SystemConfig,
    User,
    UserGroup,
)
from app.services import customer_agent_planner_service, customer_entity_resolution_contract, customer_service_service


@pytest.fixture(autouse=True)
def _semantic_preplan_out_of_scope_for_legacy_route_regressions(monkeypatch):
    """Isolate legacy HTTP route assertions from an external model provider.

    This module exercises verified catalogue/query/context executors using an
    in-memory database. Semantic-preplan schema behavior has dedicated tests
    with explicit model responses and real dev HTTP acceptance. The SQLite
    fixture deliberately has no DeepSeek credentials, so treating that as a
    customer-service outage would replace every downstream regression with an
    unrelated outage-path assertion.
    """
    async def no_semantic_preplan(*_args, **_kwargs):
        return {"called": False}

    monkeypatch.setattr(
        customer_agent_planner_service,
        "plan_customer_question_semantic",
        no_semantic_preplan,
    )


def _parse_sse_payload(payload: str) -> dict:
    current: dict = {}
    meta: dict = {}
    answer_parts: list[str] = []
    trace: dict = {}
    for raw_line in payload.splitlines():
        line = raw_line.strip("\r")
        if not line:
            event = current.get("event")
            data = current.get("data") or {}
            if event in {"content", "answer_delta"}:
                answer_parts.append(str(data.get("content") or data.get("text") or ""))
            elif event == "meta" and isinstance(data, dict):
                meta = data
            elif event == "trace" and isinstance(data, dict):
                trace = data
            current = {}
            continue
        if line.startswith("event:"):
            current["event"] = line.split(":", 1)[1].strip()
        elif line.startswith("data:"):
            current["data"] = json.loads(line.split(":", 1)[1].strip())
    payload_data = dict(meta)
    if answer_parts and not payload_data.get("answer"):
        payload_data["answer"] = "".join(answer_parts).strip()
    if trace and not payload_data.get("debug_trace"):
        payload_data["debug_trace"] = trace
    return payload_data


def _all_tables():
    return [
        Product.__table__,
        ProductSpecs.__table__,
        ProductBusiness.__table__,
        ProductContent.__table__,
        ProductMedia.__table__,
        ProductPrompts.__table__,
        ProductQa.__table__,
        ProductQaNegative.__table__,
        ListingChannel.__table__,
        ProductListingChannel.__table__,
        SalesRegion.__table__,
        ProductSalesRegion.__table__,
        Certification.__table__,
        ProductCertification.__table__,
        Keyword.__table__,
        ProductKeyword.__table__,
        AgentAction.__table__,
        OperationLog.__table__,
        CustomerServiceConversation.__table__,
        CustomerServiceMessage.__table__,
        KnowledgeDocument.__table__,
        KnowledgeChunk.__table__,
        SystemConfig.__table__,
        User.__table__,
        Group.__table__,
        UserGroup.__table__,
    ]


def _add_product(
    db,
    sku,
    name,
    category,
    capacity,
    material,
    heat_source,
    features,
    scenarios,
    weight,
    *,
    sub_category=None,
    price_positioning="中端",
):
    product = db.query(Product).filter(Product.sku == sku).first()
    if product is None:
        product = Product(id=f"route-{sku}", sku=sku)
        db.add(product)
    # Fixture data must satisfy the same barcode contract as production data;
    # a decorative ``barcode-<SKU>`` placeholder would make a valid
    # structured-evidence test exercise the safe-missing branch instead.
    product.barcode = f"{sum((index + 1) * ord(char) for index, char in enumerate(str(sku))):012d}"
    product.product_name_cn = name
    product.product_name_en = name
    product.brand = "alocs爱路客"
    product.category = category
    product.sub_category = sub_category
    product.product_level = "A类品"
    product.lifecycle_status = "常规品"
    product.person_in_charge = "RouteTest"

    specs = db.query(ProductSpecs).filter(ProductSpecs.product_id == product.id).first()
    if specs is None:
        specs = ProductSpecs(id=f"route-specs-{sku}", product_id=product.id)
        db.add(specs)
    specs.capacity = capacity
    specs.gross_weight_g = weight
    specs.body_material = material
    specs.color = "本色"
    specs.surface_finish = "硬质氧化"
    specs.heat_source = heat_source
    specs.power = "/"
    specs.technical_advantages = features

    business = db.query(ProductBusiness).filter(ProductBusiness.product_id == product.id).first()
    if business is None:
        business = ProductBusiness(id=f"route-biz-{sku}", product_id=product.id)
        db.add(business)
    business.top_selling_points = features
    business.target_audience = "户外用户"
    business.positioning = features
    business.price_positioning = price_positioning
    business.usage_scenarios = scenarios

    content = db.query(ProductContent).filter(ProductContent.product_id == product.id).first()
    if content is None:
        content = ProductContent(id=f"route-content-{sku}", product_id=product.id)
        db.add(content)
    content.title_cn = name
    content.long_description_cn = f"{name} {features} {scenarios}"
    content.search_keywords = f"{name},{category},{heat_source}"


def _add_product_qa(db, sku, question, answer, *, tags="", priority=100):
    product = db.query(Product).filter(Product.sku == sku).first()
    assert product is not None, sku
    db.add(
        ProductQa(
            id=f"route-qa-{sku}-{abs(hash((question, answer))) % 10_000_000}",
            product_id=product.id,
            question=question,
            answer=answer,
            tags=tags,
            priority=priority,
            integrity_status="approved",
        )
    )


def _add_knowledge_chunk(db, *, chunk_id, sku, title, content, source_type="sku_manual", metadata=None):
    document_id = f"route-doc-{chunk_id}"
    db.add(
        KnowledgeDocument(
            id=document_id,
            source_type=source_type,
            source_id=sku,
            sku=sku,
            title=title,
            content=content,
            metadata_json=json.dumps(metadata or {}, ensure_ascii=False),
            file_name=f"{chunk_id}.md",
            file_path=f"/route-tests/{chunk_id}.md",
            file_type="md",
            file_hash=f"hash-{chunk_id}",
            parse_status="parsed",
            related_skus_json=json.dumps([sku], ensure_ascii=False),
            is_active=True,
        )
    )
    db.add(
        KnowledgeChunk(
            id=f"route-chunk-{chunk_id}",
            document_id=document_id,
            sku=sku,
            source_type=source_type,
            chunk_index=0,
            content=content,
            metadata_json=json.dumps(metadata or {}, ensure_ascii=False),
            embedding_status="pending",
        )
    )


def _seed_route_level_products(db):
    _add_product(db, "ACC-001", "稳稳水袋", "配件", "/", "TPU", "/", "配件收纳补水", "露营收纳", 80)
    _add_product(db, "ACC-CUT-1", "勺叉收纳包", "配件", "/", "牛津布", "/", "勺叉筷集中收纳", "露营用餐收纳", 60)
    _add_product(db, "ACC-BURN-1", "旋焰炉芯", "配件", "/", "不锈钢", "/", "炉具配件 配件安装", "露营炉具维护", 55)
    _add_product(db, "ACC-BOARD-1", "拓界刀板套装", "配件", "/", "PP", "/", "餐厨配件 收纳方便", "家庭露营备餐", 140)
    _add_product(db, "ACC-HANDLE-1", "防烫提手夹", "配件", "/", "硅胶", "/", "锅具配件 防烫夹", "露营做饭", 45)
    _add_product(db, "ACC-BOWL-1", "方屿雪拉碗", "配件", "500ML", "不锈钢", "/", "边界配件 雪拉碗", "营地分食", 120)
    _add_product(db, "ACC-GUN-1", "游乐园喷枪", "配件", "/", "塑料", "/", "边界配件 喷枪", "游乐园活动", 150)
    _add_product(db, "CS-G26HM", "湖美林丰X-Power桌面炉（不含炉配件-烤盘）", "炉具", "/", "不锈钢", "气罐", "桌面炉 露营烧烤", "桌面聚餐", 2100)
    _add_product(db, "STV-001", "魔盒卡式炉", "炉具", "/", "不锈钢", "气罐", "炉具火力稳定", "露营烧烤", 2200)
    _add_product(db, "CUT-001", "便携式户外旅行筷", "餐具", "/", "不锈钢", "/", "轻量餐具", "露营用餐", 40)
    _add_product(db, "KTL-001", "悦享杯套装", "水具", "350ML", "304不锈钢", "/", "便携水具", "露营饮水", 180)
    _add_product(db, "WT-001", "随心杯", "水具", "420ML", "304不锈钢", "/", "随身补水 水具", "公园野餐 徒步补水", 160)
    _add_product(db, "WT-002", "轻量保温杯", "水具", "500ML", "304不锈钢", "/", "日常补水 水具", "通勤露营", 210)
    _add_product(db, "KTL-COF-1", "手冲细口壶", "水具", "600ML", "不锈钢", "燃气炉", "偏咖啡冲煮 水具", "露营咖啡", 330)
    _add_product(db, "KTL-HEAT-1", "烧水壶套装", "水具", "1.1L", "铝合金", "燃气炉", "偏烧水加热 水具", "营地烧水", 420)
    _add_product(db, "CB253", "聚能环水壶", "水壶", "4L", "铝合金", "燃气炉", "轻量徒步 快速烧水", "轻量徒步 双人露营 户外补水 山野煮茶 休闲露营", 475)
    _add_product(db, "CB254", "激流水壶", "水壶", "4L", "铝合金", "燃气炉", "双人露营 户外烧水", "轻量徒步 双人露营 户外补水 山野煮茶 休闲露营", 498)
    _add_product(db, "KW-K32-黑", "天鹅壶9杯-黑色", "咖啡器具", "900ML", "不锈钢", "气炉", "手冲咖啡器具", "露营咖啡", 420)
    _add_product(db, "TBL-001", "疯狂游乐园泡泡桌-长桌", "桌椅", "/", "铝合金", "/", "折叠桌椅", "家庭露营", 1800)
    _add_product(db, "KD04SS", "奇幻秘境限定系列-755百搭桌(兔子）", "桌椅", "/", "铝合金", "/", "颜值很高的折叠桌 收纳方便", "主题露营 精致露营 家庭野餐", 4200)
    _add_product(db, "KD20HM", "湖美林丰泡泡桌-长桌", "桌椅", "/", "铝合金", "/", "长桌稳定 六人左右小聚", "主题露营 家庭野餐 户外多人小聚", 5600)
    _add_product(db, "CS-B14（LX）", "旋焰炉芯（作为熊猫大侠套装赠品）", "配件", "/", "不锈钢", "/", "炉具配件 炉芯替换件", "炉具维护 套装赠品", 80)
    _add_product(db, "COF-001", "魔咖旅行咖啡研磨机", "咖啡器具", "/", "不锈钢", "/", "手冲咖啡器具", "露营咖啡", 260)
    _add_product(db, "TEA-001", "竹影茶具", "茶具", "/", "陶瓷", "/", "便携茶具", "露营泡茶", 380)
    _add_product(db, "DV01", "独醒-酒具套装", "酒具", "/", "不锈钢 玻璃", "明火直烧、卡式炉、分体炉、一体炉", "露营品酒酒具 社交小聚", "精致露营 户外小聚 山野小酌", 1280)
    _add_product(db, "OT-001", "湖美林丰天幕", "天幕、地垫、帐篷", "/", "春亚纺", "/", "防晒遮蔽", "家庭露营", 1600)

    _add_product(db, "CW-C83", "炊墨套锅", "锅具", "锅 3700ML", "硬质氧化铝合金", "燃气炉", "多人做饭 稳一点", "家庭露营 2-4人 火锅", 1200)
    _add_product(db, "CW-C83-1", "炊墨炒锅", "锅具", "锅 3700ML", "硬质氧化铝合金", "燃气炉", "大容量", "家庭露营 多人做饭", 1200)
    _add_product(db, "CW-C83-2", "炊墨煎锅", "锅具", "煎盘 2300ML", "硬质氧化铝合金", "燃气炉", "兼容多热源", "家庭露营 早餐煎烤", 980)
    _add_product(db, "CF-PG19", "瓦片烤盘", "锅具", "8英寸", "硬质氧化铝合金", "燃气炉", "烤盘 煎烤盘 早餐煎东西", "露营烧烤 营地早餐", 760)
    _add_product(db, "CW-S10-1", "激川单锅", "锅具", "锅 1400ML", "硬质氧化铝合金、TRITIAN", "酒精炉, 气炉", "双人需求 不粘", "双人露营 轻量野餐 火锅", 300)
    _add_product(db, "CW-S10-A", "激川单锅", "锅具", "锅 1400ML", "硬质氧化铝合金、TRITIAN", "酒精炉, 气炉", "双人需求 不粘", "双人露营 轻量野餐 火锅", 300)
    _add_product(db, "CW-C01-37", "1－2人野营锅7件套", "锅具", "锅 900ML，碗 450ML", "硬质氧化铝合金", "酒精炉, 燃气炉", "轻量化套娃收纳", "双人露营 周末野餐", 595)
    _add_product(db, "TW-141", "烽宴多功能聚能套锅", "锅具", "锅 1600ML", "铝合金", "酒精炉, 燃气炉", "聚能结构 全套收纳", "轻量野餐 双人露营", 680)
    _add_product(db, "CW-C19T-37", "旅伴2-3人野餐锅5件套", "锅具", "2升锅", "硬质氧化铝", "燃气炉", "全套收纳便携", "双人露营 公园野餐", 1062)
    _add_product(db, "CW-C06PRO", "轻途套锅", "锅具", "大锅 3.0L，小锅 1.7L，水壶 0.8L", "3003铝合金、硅胶、不锈钢、PP", "酒精炉, 燃气炉", "极致轻量化 套娃式收纳", "轻量徒步 背包旅行 单人露营", 1150)
    _add_product(db, "CW-C69-1", "小方锅套装", "锅具", "大锅 1.7L，水壶 1.0L", "304不锈钢", "燃气炉", "方形设计 易收纳", "精致露营 户外小份烹饪", 1320)
    _add_product(db, "TW-422-蓝", "随行保温杯-蓝", "水具", "500ML", "304不锈钢", "/", "便携补水 保温杯", "通勤露营 日常饮水", 210)
    _add_product(db, "TW-422-绿", "随行保温杯-绿", "水具", "500ML", "304不锈钢", "/", "便携补水 保温杯", "通勤露营 日常饮水", 210)
    _add_product(db, "TW-422-粉", "随行保温杯-粉", "水具", "500ML", "304不锈钢", "/", "便携补水 保温杯", "公园野餐 日常饮水", 210)
    _add_product(db, "KW-K31-白", "轻享随行杯-白", "水具", "650ML", "304不锈钢", "/", "便携饮水 冷热两用", "通勤补水 轻露营", 260)
    _add_product(db, "KW-K31-黑", "轻享随行杯-黑", "水具", "650ML", "304不锈钢", "/", "便携饮水 冷热两用", "通勤补水 轻露营", 260)
    _add_product(db, "KW-K32-白", "天鹅壶9杯-白色", "咖啡器具", "900ML", "不锈钢", "气炉", "手冲咖啡器具", "露营咖啡", 420)
    _add_product(db, "GX15-450G", "高山气罐450G", "配件", "/", "钢", "/", "燃气配件 长时使用", "露营做饭 多人露营", 450)
    _add_product(db, "CW-C97", "行山双耳锅", "锅具", "1.8L", "硬质氧化铝", "气炉", "轻量单锅 易收纳", "单人露营 双人简餐 徒步煮面", 420)
    _add_product(db, "AC-Z07", "钛夹", "配件", "/", "钛", "/", "小配件 夹取食材", "露营做饭 餐厨配件", 55)
    _add_product(db, "CS-B14", "旋焰炉芯", "配件", "/", "不锈钢", "/", "炉具配件 炉芯替换件", "炉具维护", 80)
    _add_product(db, "CT-T04(BM)", "出山-功夫茶具（竹套版）", "茶具", "/", "竹、陶瓷", "/", "便携功夫茶具", "露营茶席 公园野餐", 980)
    _add_product(db, "CW-C84", "楦ｆ硥姘村６", "姘村６", "1.0L", "纭川姘у寲閾濆悎閲?", "鐕冩皵鐐?", "杞婚噺寰掓 蹇€熺儳姘?", "鎴峰闇茶惀鐓尪 鍙屼汉闇茶惀 灞遍噹鍝佽寗", 320)
    _add_product(db, "CW-K32", "浜喅Plus姘村６", "姘村６", "900ML", "纭川姘у寲閾濆悎閲?", "鐕冩皵鐐?", "绮捐嚧闇茶惀鐓尪 渚挎惡", "绮捐嚧闇茶惀鐓尪 鍙屼汉闇茶惀 鎴峰琛ユ按", 340)
    _add_product_qa(db, "CW-C83", "CW-C83 能不能用酒精炉？", "当前资料未显示 CW-C83 支持酒精炉；现有热源资料为明火直烧、卡式炉、分体炉、一体炉。", tags="热源,酒精炉", priority=200)
    _add_product_qa(db, "CW-C83", "CW-C83 有没有官方说明书？", "当前资料里暂未维护 CW-C83 的官方说明书信息；如需正式说明书，请联系人工客服或后台资料管理员查询。", tags="说明书,资料缺失", priority=180)
    _add_product_qa(db, "CT-T04(BM)", "CT-T04(BM) 有什么使用限制？", "CT-T04(BM) 属于茶具套装，当前资料更偏露营茶席和公园野餐使用；它不是炉具或炊具，资料里也未标注适用酒精炉。", tags="使用限制,茶具", priority=180)
    _add_product_qa(db, "DV01", "DV01 有没有保修？", "当前资料未标注 DV01 的保修政策；如需售后和保修信息，建议联系人工客服确认。", tags="保修,售后", priority=170)
    _add_product_qa(db, "KD20HM", "KD20HM 有没有安装视频？", "当前资料未维护 KD20HM 的安装视频链接；如果你需要安装说明或演示资料，建议联系人工客服进一步确认。", tags="安装视频,资料缺失", priority=170)
    _add_product_qa(db, "KW-K31-白", "KW-K31-白 可以装热水吗？", "当前资料将 KW-K31-白 描述为便携饮水、冷热两用；可按装热水/饮水容器理解，但资料未标注可直接上火加热。", tags="热水,饮水,冷热两用", priority=190)
    _add_product_qa(db, "KW-K32-黑", "KW-K32-黑 是烧水还是补水？", "当前资料更偏手冲咖啡和营地热饮场景，属于可加热烧水类器具；并未把它标注为随身补水杯。", tags="烧水,热饮,补水", priority=190)
    _add_product_qa(db, "TW-422-蓝", "TW-422-蓝 能不能装热水？", "当前资料显示 TW-422-蓝 为保温杯，可装热水饮用；但它不是直接加热烧水的器具。", tags="热水,保温杯", priority=190)
    _add_product_qa(db, "GX15-450G", "GX15-450G 适合几个人用？", "GX15-450G 是燃气配件，当前资料没有按人数标注；更适合从气罐规格和使用时长来判断。", tags="人数,配件", priority=150)
    _add_knowledge_chunk(
        db,
        chunk_id="stove-safety-1",
        sku="CS-G26HM",
        title="炉具安全注意事项",
        content="户外使用炉具前先确认气罐与接口连接到位，远离明火和密闭空间；遇到点不着火时，先关闭阀门，检查气源、点火器和接口，再重新尝试，不要连续空放气。",
        source_type="usage_care",
        metadata={"topic": "safety"},
    )
    _add_knowledge_chunk(
        db,
        chunk_id="gas-storage-1",
        sku="GX15-450G",
        title="气罐存放注意事项",
        content="气罐应放在阴凉通风处，避免高温暴晒、靠近火源或车内长期密闭存放；运输和收纳前先确认阀门关闭、接口无泄漏。",
        source_type="usage_care",
        metadata={"topic": "storage"},
    )
    db.commit()


@pytest.fixture()
def route_client_and_db(monkeypatch):
    tmpdir = tempfile.TemporaryDirectory()
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine, tables=_all_tables())
    Session = sessionmaker(bind=engine, expire_on_commit=False)

    db = Session()
    db.add(
        User(
            id="customer-service-route-user",
            username="customer-service-route-user",
            email="customer-service-route@example.com",
            password_hash="unused",
            user_type="human",
            display_name="Customer Service Route User",
            is_active=True,
        )
    )
    db.add(Group(id="customer-service-route-management", group_name=MANAGEMENT_GROUP_NAME, description="management"))
    db.add(
        UserGroup(
            user_id="customer-service-route-user",
            group_id="customer-service-route-management",
            group_role="admin",
        )
    )
    _seed_route_level_products(db)
    db.commit()
    db.close()

    def override_db():
        session = Session()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_db] = override_db

    from app.api import customer_service as customer_service_api

    monkeypatch.setattr(customer_service_api, "enforce_rate_limit", lambda **kwargs: None)
    monkeypatch.setattr(customer_service_api.operation_log_service, "log_operation", lambda *args, **kwargs: None)

    token = create_access_token({"sub": "customer-service-route-user"})
    headers = {"Authorization": f"Bearer {token}"}

    try:
        with TestClient(app) as test_client:
            yield test_client, headers, Session
    finally:
        app.dependency_overrides.clear()
        tmpdir.cleanup()


def test_customer_service_ask_route_level_scene_019_prefers_stove_domain_for_bbq_hot_drink_combo(
    route_client_and_db,
):
    client, headers, Session = route_client_and_db
    question = "露营烧烤加热饮都要兼顾，炉具怎么搭更稳？"

    response = client.post("/api/customer-service/ask?debug=true", json={"question": question}, headers=headers)

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["answer_type"] == "recommendation", payload
    assert payload["answer_type"] != "knowledge_base_answer"
    assert payload["result_skus"], payload
    assert payload["result_skus"][0] not in {"AC-Z13", "CB253", "CB254"}
    assert "炉具" in payload["answer"], payload["answer"]
    assert re.search(r"(烧烤|热饮|搭配|稳定|火力)", payload["answer"]), payload["answer"]

    with Session() as db:
        top_category = db.query(Product.category).filter(Product.sku == payload["result_skus"][0]).scalar()
        front_categories = {
            product.sku: product.category
            for product in db.query(Product).filter(Product.sku.in_(payload["result_skus"][:3])).all()
        }

    assert top_category == "炉具", payload
    assert all(category == "炉具" for category in front_categories.values()), front_categories


def test_customer_service_ask_route_level_tent_fuel_safety_precedes_fuel_identity_clarification(
    route_client_and_db,
):
    client, headers, _ = route_client_and_db

    response = client.post(
        "/api/customer-service/ask?debug=true",
        json={"question": "液体酒精炉在帐篷里能用吗？为什么？"},
        headers=headers,
    )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["answer_type"] == "product_usage_care", payload
    assert "帐篷" in payload["answer"]
    assert "通风" in payload["answer"]
    assert payload["debug"]["agent_mode"] == "product_usage_care_fast_path"
    assert payload["debug"]["agent_mode"] != "unbound_fuel_compatibility_identity_required"


@pytest.mark.parametrize(
    ("question", "expected_sku", "expected_category", "expect_heat_source_phrase"),
    [
        ("CS-B14（LX） 容量多大？", "CS-B14（LX）", "配件", False),
        ("CS-B14（LX） 适合什么场景？能不能用酒精炉？", "CS-B14（LX）", "配件", False),
        ("KD04SS 适合什么场景？能不能用酒精炉？", "KD04SS", "桌椅", False),
        ("DV01 适合什么场景？能不能用酒精炉？", "DV01", "酒具", True),
        ("KD20HM 适合什么场景？能不能用酒精炉？", "KD20HM", "桌椅", False),
    ],
)
def test_customer_service_ask_route_level_explicit_sku_compound_query_keeps_exact_sku(
    route_client_and_db,
    question,
    expected_sku,
    expected_category,
    expect_heat_source_phrase,
):
    client, headers, Session = route_client_and_db

    response = client.post("/api/customer-service/ask?debug=true", json={"question": question}, headers=headers)

    assert response.status_code == 200, response.text
    payload = response.json()
    debug_plan = ((payload.get("debug") or {}).get("plan") or {})
    assert payload["answer_type"] == "product_detail", payload
    assert payload["answer_type"] != "knowledge_base_answer"
    assert payload["result_skus"] == [expected_sku], payload
    assert payload["answer"]
    assert "适合什么场景" not in str(debug_plan.get("product_ref") or "")
    if "酒精炉" in question:
        assert debug_plan.get("requested_field") == "heat_source"
    elif "容量" in question:
        assert debug_plan.get("requested_field") in {"容量", ""}
    assert expected_sku in payload["answer"]

    with Session() as db:
        category = db.query(Product.category).filter(Product.sku == expected_sku).scalar()
    assert category == expected_category

    if "容量" in question:
        assert re.search(r"(容量|未标注|/)", payload["answer"]), payload["answer"]
    elif expect_heat_source_phrase:
        assert re.search(r"(适用热源|明火|卡式炉|分体炉|一体炉)", payload["answer"]), payload["answer"]
    else:
        assert re.search(r"(不是炉具|不是炊具|未标注|不建议按酒精炉适配产品理解)", payload["answer"]), payload["answer"]


def test_explicit_full_name_with_category_word_prevents_structured_query_preemption(
    route_client_and_db,
):
    client, headers, Session = route_client_and_db
    with Session() as db:
        _add_product(
            db,
            "ROUTE-NAMED-1",
            "酒精炉套装",
            "炉具",
            "/",
            "不锈钢",
            "酒精炉",
            "完整名称含类目词的单品",
            "露营烹饪",
            600,
        )
        product = db.query(Product).filter(Product.sku == "ROUTE-NAMED-1").one()
        db.query(ProductSpecs).filter(ProductSpecs.product_id == product.id).update({"color": "黑色"})
        db.commit()

    response = client.post(
        "/api/customer-service/ask?debug=true",
        json={"question": "酒精炉套装有哪些颜色？"},
        headers=headers,
    )

    assert response.status_code == 200, response.text
    payload = response.json()
    debug = payload.get("debug") or {}
    field_contract = debug.get("field_contract") or debug.get("requested_field_contract") or {}
    entity = debug.get("entity_resolution_contract") or {}
    assert payload["answer_type"] == "product_detail", payload
    assert debug.get("agent_mode") != "structured_category_field_filter_query"
    assert field_contract.get("field_type") == "color"
    assert entity.get("status") == "resolved"
    assert entity.get("resolved_sku") == "ROUTE-NAMED-1"
    assert payload["result_skus"] == ["ROUTE-NAMED-1"]
    metadata = payload.get("answer_metadata") or {}
    assert metadata.get("evidence_field") == "color"
    assert metadata.get("evidence_sku") == "ROUTE-NAMED-1"
    assert "黑色" in payload["answer"]


@pytest.mark.parametrize(
    ("question", "allowed_categories", "forbidden_top_skus", "required_terms"),
    [
        (
            "十来个人公司团建，除了烧烤还要烧水，炉具怎么选？",
            {"炉具"},
            {"CB253", "CB254", "AC-Z13"},
            ("炉具", "烧烤", "烧水", "稳定"),
        ),
        (
            "两个人海边露营，风大一点，炉具该怎么选？",
            {"炉具"},
            {"CB253", "CB254", "AC-Z13"},
            ("炉具", "防风", "稳定"),
        ),
        (
            "双人露营不想太重，也不想买太贵，推荐哪套？",
            {"锅具"},
            {"CB253", "CB254", "AC-Z13"},
            ("双人", "轻", "套", "取舍"),
        ),
    ],
)
def test_customer_service_ask_route_level_new_domain_targeted_scenarios_keep_correct_top_domain(
    route_client_and_db,
    question,
    allowed_categories,
    forbidden_top_skus,
    required_terms,
):
    client, headers, Session = route_client_and_db

    response = client.post("/api/customer-service/ask?debug=true", json={"question": question}, headers=headers)

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["answer_type"] == "recommendation", payload
    assert payload["answer_type"] != "knowledge_base_answer"
    assert payload["result_skus"], payload
    assert payload["answer"]

    with Session() as db:
        front_categories = {
            product.sku: product.category
            for product in db.query(Product).filter(Product.sku.in_(payload["result_skus"][:2])).all()
        }

    assert front_categories, payload
    assert all(category in allowed_categories for category in front_categories.values()), front_categories
    assert all(sku not in forbidden_top_skus for sku in payload["result_skus"][:2]), payload["result_skus"]
    assert any(term in payload["answer"] for term in required_terms), payload["answer"]
    if question == "双人露营不想太重，也不想买太贵，推荐哪套？":
        assert re.search(r"(双人|露营).*(轻|便携|入门|取舍|套锅|套装)", payload["answer"]), payload["answer"]


@pytest.mark.parametrize(
    ("question", "expected_sku", "requested_field"),
    [
        ("CT-T04(BM)适合什么场景？能不能用酒精炉？", "CT-T04(BM)", "heat_source"),
        ("CT-T04-BM适合什么场景？能不能用酒精炉？", "CT-T04(BM)", "heat_source"),
        ("KD04SS适合什么场景？能不能用酒精炉？", "KD04SS", "heat_source"),
        ("KD20HM适合什么场景？能不能用酒精炉？", "KD20HM", "heat_source"),
        ("DV01适合什么场景？", "DV01", ""),
        ("DV01能不能用明火？", "DV01", ""),
        ("TW-422-蓝能装多少水？", "TW-422-蓝", "容量"),
        ("TW-422-绿是什么材质？", "TW-422-绿", "材质"),
        ("TW-422-粉能装多少水？", "TW-422-粉", "容量"),
        ("KW-K31-白容量多大？", "KW-K31-白", "容量"),
        ("KW-K31-黑容量多少？", "KW-K31-黑", "容量"),
        ("KW-K32-白容量多大？", "KW-K32-白", "容量"),
        ("KW-K32-黑容量多少？", "KW-K32-黑", "容量"),
        ("GX15-450G适合几个人用？", "GX15-450G", ""),
        ("CW-C97适合什么场景？", "CW-C97", ""),
        ("AC-Z07是什么材质？", "AC-Z07", "材质"),
        ("CS-B14容量多少？", "CS-B14", "容量"),
        ("CS-B14适合什么场景？能不能用酒精炉？", "CS-B14", "heat_source"),
    ],
)
def test_customer_service_ask_route_level_explicit_sku_generalization_keeps_exact_sku(
    route_client_and_db,
    question,
    expected_sku,
    requested_field,
):
    client, headers, _ = route_client_and_db

    response = client.post("/api/customer-service/ask?debug=true", json={"question": question}, headers=headers)

    assert response.status_code == 200, response.text
    payload = response.json()
    debug_plan = ((payload.get("debug") or {}).get("plan") or {})

    assert payload["answer_type"] == "product_detail", payload
    assert payload["answer_type"] != "knowledge_base_answer"
    assert payload["result_skus"] == [expected_sku], payload
    assert payload["answer"], payload
    assert expected_sku in payload["answer"], payload["answer"]
    assert debug_plan.get("product_ref") == expected_sku, debug_plan
    if requested_field:
        assert debug_plan.get("requested_field") in {requested_field, ""}, debug_plan


def test_semantic_outage_unclassified_named_product_fails_closed(route_client_and_db, monkeypatch):
    """No-key test runtime must clarify instead of inventing a scenario rule.

    This case formerly expected the old ``适合 + 任意词 + 用`` fast-path.
    The live semantic preplan classifies the request as ``usage_scene``; the
    isolated test configuration deliberately cannot call that model.  Its
    safe contract is therefore clarification with no product fact, rather
    than reintroducing a catch-all phrase matcher that also relabels audience
    requests such as ``更适合谁用``.
    """
    async def semantic_outage(*_args, **_kwargs):
        return {
            "called": True,
            "fallback_reason": "llm_error:RuntimeError",
            "canonical_fields": [],
            "field_type": "",
        }

    monkeypatch.setattr(
        customer_agent_planner_service,
        "plan_customer_question_semantic",
        semantic_outage,
    )
    client, headers, _ = route_client_and_db
    response = client.post(
        "/api/customer-service/ask?debug=true",
        json={"question": "KD04SS适合露营用吗？"},
        headers=headers,
    )

    assert response.status_code == 200, response.text
    payload = response.json()
    debug = payload.get("debug") or {}
    assert payload["answer_type"] == "clarification", payload
    # Identity resolution succeeded even though semantic planning was
    # unavailable; keep the sealed identity so the final clarification does
    # not ask the customer for the same SKU again.
    assert payload.get("result_skus") == ["KD04SS"], payload
    assert debug.get("agent_mode") == "semantic_outage_named_product_field_clarification", payload
    assert "无法稳定识别" in str(payload.get("answer") or ""), payload


def test_customer_service_ask_route_level_scene_x050_compares_griddle_and_cookware_tradeoffs(
    route_client_and_db,
):
    client, headers, Session = route_client_and_db
    question = "营地做早餐偏煎烤，推荐烤盘还是锅具？"

    response = client.post("/api/customer-service/ask?debug=true", json={"question": question}, headers=headers)

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["answer_type"] == "recommendation", payload
    assert payload["answer_type"] != "knowledge_base_answer"
    assert payload["result_skus"], payload
    assert payload["answer"]
    assert re.search(r"(烤盘|锅具).*(更适合|更通用|优先)", payload["answer"]), payload["answer"]

    with Session() as db:
        front_categories = [
            category
            for category, in db.query(Product.category).filter(Product.sku.in_(payload["result_skus"][:3])).all()
        ]

    assert "锅具" in front_categories or "炉具" in front_categories


@pytest.mark.parametrize(
    ("question", "category_name", "allowed_categories"),
    [
        ("有哪些配件产品？", "配件", {"配件"}),
        ("有哪些炉具产品？", "炉具", {"炉具"}),
        ("有哪些餐具产品？", "餐具", {"餐具"}),
        ("有哪些水具产品？", "水具", {"水具", "水壶", "水杯"}),
        ("有哪些桌椅产品？", "桌椅", {"桌椅"}),
        ("有哪些咖啡器具产品？", "咖啡器具", {"咖啡器具"}),
        ("有哪些茶具产品？", "茶具", {"茶具"}),
    ],
)
def test_customer_service_ask_route_level_category_queries_stay_within_category(
    route_client_and_db,
    question,
    category_name,
    allowed_categories,
):
    client, headers, Session = route_client_and_db

    response = client.post("/api/customer-service/ask?debug=true", json={"question": question}, headers=headers)

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["answer_type"] == "query_products"
    assert payload["answer_type"] != "knowledge_base_answer"
    assert category_name in payload["answer"]
    assert "183 款" not in payload["answer"]
    assert payload["result_skus"]

    with Session() as db:
        categories = {
            product.sku: product.category
            for product in db.query(Product).filter(Product.sku.in_(payload["result_skus"])).all()
        }
    assert all(category in allowed_categories for category in categories.values()), categories


@pytest.mark.parametrize(
    "question",
    [
        "家庭露营偏火锅场景，锅具容量优先怎么选？",
        "两个人露营偏爱火锅场景，锅具要稳一点，推荐哪个？",
        "烧烤场景想带炉子和烤盘，先买哪类最值？",
        "两个人轻露营，希望锅具轻一点但也别太单薄。",
    ],
)
def test_customer_service_ask_route_level_scenarios_return_recommendation_shape(
    route_client_and_db,
    question,
):
    client, headers, _ = route_client_and_db

    response = client.post("/api/customer-service/ask?debug=true", json={"question": question}, headers=headers)

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["answer_type"] == "recommendation"
    assert payload["answer_type"] != "knowledge_base_answer"
    assert payload["result_skus"]
    assert re.search(r"(推荐|更推荐|优先推荐)", payload["answer"]), payload["answer"]
    assert re.search(r"(备选|如果你更看重)", payload["answer"]), payload["answer"]


def test_customer_service_ask_route_level_explicit_sku_alcohol_compatibility_beats_recommendation(
    route_client_and_db,
):
    client, headers, _ = route_client_and_db

    response = client.post(
        "/api/customer-service/ask?debug=true",
        json={"question": "CW-C83 能不能用酒精炉？如果不能就别推荐错了。"},
        headers=headers,
    )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["answer_type"] == "product_detail"
    assert payload["answer_type"] != "recommendation"
    assert payload["result_skus"] == ["CW-C83"]
    assert "CW-C83" in payload["answer"]
    assert "AC-Z13" not in payload["answer"]
    assert "CB253" not in payload["answer"]
    assert not re.search(r"明火直烧.*酒精炉|卡式炉.*酒精炉|分体炉.*酒精炉", payload["answer"]), payload["answer"]


def test_customer_service_ask_route_level_compound_sku_keeps_product_anchor_for_each_child(
    route_client_and_db,
):
    client, headers, Session = route_client_and_db

    response = client.post(
        "/api/customer-service/ask?debug=true",
        json={"question": "CW-C83 适合什么场景？能不能用酒精炉？"},
        headers=headers,
    )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["answer_type"] == "product_detail", payload
    assert payload["result_skus"] == ["CW-C83"], payload
    assert "CW-C83" in payload["answer"]
    assert "酒精炉" in payload["answer"]
    assert any(term in payload["answer"] for term in ("场景", "露营", "火锅")), payload["answer"]
    assert "这款酒精炉" not in payload["answer"]


def test_compound_semantic_product_qa_bypasses_generic_compatibility_fast_path(
    route_client_and_db,
    monkeypatch,
):
    client, headers, _ = route_client_and_db
    usage_calls = []

    async def semantic_compound_preplan(*_args, **_kwargs):
        return {
            "called": True,
            "route_family": "product_bound_qa",
            "route_hint": "product_detail",
            "question_type": "field",
            "entities": ["CW-C83"],
            "subject_text": "CW-C83",
            "canonical_fields": [],
            "ambiguity": False,
            "evidence_required": True,
            "evidence_kind": "product_qa",
            "qa_evidence_query": "CW-C83 适合什么场景 能不能用酒精炉",
            "qa_evidence_queries": ["适合什么场景", "能不能用酒精炉"],
            "compound": True,
            "confidence": 0.95,
            "confidence_label": "high",
            "fallback_reason": "",
            "recommendation_constraints": {},
            "unrepresented_recommendation_requirements": [],
            "recommendation_soft_preferences": [],
        }

    async def generic_usage_fast_path(*_args, **_kwargs):
        usage_calls.append(True)
        return {
            "intent": "product_usage_care",
            "answer_type": "product_usage_care",
            "answer": "generic compatibility fallback",
            "results": [],
            "result_skus": ["CW-C83"],
            "candidate_skus": ["CW-C83"],
            "debug": {"agent_mode": "generic_usage_fast_path"},
            "skip_polish": True,
        }

    monkeypatch.setattr(customer_service_service, "_maybe_run_semantic_preplan", semantic_compound_preplan)
    monkeypatch.setattr(
        customer_service_service.customer_agent_intent_service,
        "answer_product_usage_care_request",
        generic_usage_fast_path,
    )

    response = client.post(
        "/api/customer-service/ask?debug=true",
        json={"question": "CW-C83 适合什么场景？能不能用酒精炉？"},
        headers=headers,
    )

    assert response.status_code == 200, response.text
    assert usage_calls == []


def test_semantic_general_chat_does_not_capture_stove_pairing_recommendation(
    route_client_and_db,
    monkeypatch,
):
    client, headers, _ = route_client_and_db

    async def general_chat_preplan(*_args, **_kwargs):
        return {
            "called": True,
            "route_family": "general_chat",
            "route_hint": "clarification",
            "question_type": "recommendation",
            "entities": [],
            "subject_text": "炉具和烤盘",
            "canonical_fields": [],
            "ambiguity": False,
            "evidence_required": False,
            "evidence_kind": "structured_field",
            "compound": False,
            "confidence": 0.95,
            "confidence_label": "high",
            "fallback_reason": "",
            "recommendation_constraints": {},
            "unrepresented_recommendation_requirements": [],
            "recommendation_soft_preferences": ["风比较大的营地"],
        }

    monkeypatch.setattr(customer_service_service, "_maybe_run_semantic_preplan", general_chat_preplan)

    response = client.post(
        "/api/customer-service/ask?debug=true",
        json={"question": "风比较大的营地，炉具和烤盘怎么搭？"},
        headers=headers,
    )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["answer_type"] == "recommendation", payload
    assert payload["result_skus"], payload
    assert {"炉具", "锅具"}.issubset({row["category"] for row in payload["results"]})
    assert "烤盘" in payload["answer"]


def test_invalid_semantic_recommendation_contract_does_not_capture_stove_pairing_recommendation(
    route_client_and_db,
    monkeypatch,
):
    client, headers, _ = route_client_and_db

    async def invalid_recommendation_preplan(*_args, **_kwargs):
        return {
            "called": True,
            "route_family": "",
            "route_hint": "",
            "question_type": "",
            "entities": [],
            "subject_text": "",
            "canonical_fields": [],
            "ambiguity": False,
            "evidence_required": False,
            "evidence_kind": "",
            "compound": False,
            "confidence": 0.0,
            "confidence_label": "low",
            "fallback_reason": "invalid_recommendation_constraints",
            "semantic_route_family_hint": "recommendation",
            "recommendation_constraints": {},
            "unrepresented_recommendation_requirements": [],
            "recommendation_soft_preferences": ["风比较大的营地"],
        }

    monkeypatch.setattr(customer_service_service, "_maybe_run_semantic_preplan", invalid_recommendation_preplan)

    response = client.post(
        "/api/customer-service/ask?debug=true",
        json={"question": "风比较大的营地，炉具和烤盘怎么搭？"},
        headers=headers,
    )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["answer_type"] == "recommendation", payload
    assert payload["result_skus"], payload
    assert {"炉具", "锅具"}.issubset({row["category"] for row in payload["results"]})
    assert "烤盘" in payload["answer"]


def test_customer_service_ask_route_level_multiturn_variant_pronoun_heat_source_followup_anchors_top_sku(
    route_client_and_db,
):
    client, headers, _ = route_client_and_db

    turn1 = client.post(
        "/api/customer-service/ask?debug=true",
        json={"question": "我一个人露营，想要轻一点的锅具，先推一个。"},
        headers=headers,
    )
    assert turn1.status_code == 200, turn1.text
    payload1 = turn1.json()
    assert payload1["answer_type"] == "recommendation"
    assert payload1["result_skus"]
    conversation_id = payload1["conversation_id"]
    top_sku = payload1["result_skus"][0]

    turn2 = client.post(
        "/api/customer-service/ask?debug=true",
        json={"question": "这个可以配酒精炉吗？", "conversation_id": conversation_id},
        headers=headers,
    )
    assert turn2.status_code == 200, turn2.text
    payload2 = turn2.json()
    assert payload2["answer_type"] == "product_detail", payload2
    assert payload2["answer_type"] != "clarification"
    assert payload2["answer_type"] != "knowledge_base_answer"
    assert payload2["result_skus"] == [top_sku], payload2

    turn3 = client.post(
        "/api/customer-service/ask?debug=true",
        json={"question": "不能的话有没有更合适的？", "conversation_id": conversation_id},
        headers=headers,
    )
    assert turn3.status_code == 200, turn3.text
    payload3 = turn3.json()
    assert payload3["answer_type"] == "recommendation", payload3
    assert payload3["answer_type"] != "knowledge_base_answer"
    assert payload3["result_skus"], payload3


def test_customer_service_ask_route_level_multiturn_variant_ordinal_followups_anchor_recommended_order(
    route_client_and_db,
):
    client, headers, _ = route_client_and_db

    turn1 = client.post(
        "/api/customer-service/ask?debug=true",
        json={"question": "推荐几款适合家庭露营的锅具。"},
        headers=headers,
    )
    assert turn1.status_code == 200, turn1.text
    payload1 = turn1.json()
    assert payload1["answer_type"] == "recommendation"
    assert len(payload1["result_skus"]) >= 2, payload1
    conversation_id = payload1["conversation_id"]

    turn2 = client.post(
        "/api/customer-service/ask?debug=true",
        json={"question": "第一个能不能用酒精炉？", "conversation_id": conversation_id},
        headers=headers,
    )
    assert turn2.status_code == 200, turn2.text
    payload2 = turn2.json()
    assert payload2["answer_type"] == "product_detail", payload2
    assert payload2["answer_type"] != "clarification"
    assert payload2["answer_type"] != "knowledge_base_answer"
    assert payload2["result_skus"] == [payload1["result_skus"][0]], payload2

    turn3 = client.post(
        "/api/customer-service/ask?debug=true",
        json={"question": "第二个容量多大？", "conversation_id": conversation_id},
        headers=headers,
    )
    assert turn3.status_code == 200, turn3.text
    payload3 = turn3.json()
    assert payload3["answer_type"] == "product_detail", payload3
    assert payload3["answer_type"] != "clarification"
    assert payload3["answer_type"] != "knowledge_base_answer"
    assert payload3["result_skus"] == [payload1["result_skus"][1]], payload3


def test_mixed_category_context_keeps_named_waterware_ordinal_in_its_scope(route_client_and_db):
    client, headers, _ = route_client_and_db

    first = client.post(
        "/api/customer-service/ask?debug=true",
        json={"question": "燃气和烧水壶分别推荐一个？"},
        headers=headers,
    )
    assert first.status_code == 200, first.text
    payload1 = first.json()
    assert payload1["answer_type"] == "recommendation", payload1
    waterware_skus = [
        row["sku"] for row in payload1.get("results") or []
        if row.get("category") in {"水具", "水壶"}
    ]
    stove_skus = [
        row["sku"] for row in payload1.get("results") or []
        if row.get("category") == "炉具"
    ]
    assert waterware_skus, payload1
    assert stove_skus, payload1

    second = client.post(
        "/api/customer-service/ask?debug=true",
        json={
            "question": "第一个烧水壶的容量是多少？",
            "conversation_id": payload1["conversation_id"],
        },
        headers=headers,
    )
    assert second.status_code == 200, second.text
    payload2 = second.json()
    assert payload2["result_skus"] == [waterware_skus[0]], payload2
    assert "容量" in payload2["answer"], payload2
    assert all(sku not in payload2["answer"] for sku in stove_skus), payload2


def test_ordinal_followup_renders_all_requested_fields_for_one_candidate(route_client_and_db):
    client, headers, _ = route_client_and_db

    first = client.post(
        "/api/customer-service/ask?debug=true",
        json={"question": "推荐几款适合家庭露营的锅具。"},
        headers=headers,
    ).json()
    assert len(first["result_skus"]) >= 2, first

    second = client.post(
        "/api/customer-service/ask?debug=true",
        json={
            "question": "你刚才推荐的第一款，重量和容量分别是多少？",
            "conversation_id": first["conversation_id"],
        },
        headers=headers,
    ).json()

    assert second["result_skus"] == [first["result_skus"][0]], second
    assert "重量" in second["answer"], second
    assert "容量" in second["answer"], second


def test_ordinal_griddle_followup_renders_dimensions_and_material(route_client_and_db):
    client, headers, _ = route_client_and_db

    first = client.post(
        "/api/customer-service/ask?debug=true",
        json={"question": "推荐一款适合露营的烤盘。"},
        headers=headers,
    ).json()
    assert first["result_skus"], first

    second = client.post(
        "/api/customer-service/ask?debug=true",
        json={
            "question": "第一个烤盘的尺寸和材质是什么？",
            "conversation_id": first["conversation_id"],
        },
        headers=headers,
    ).json()

    assert second["result_skus"] == [first["result_skus"][0]], second
    assert "尺寸" in second["answer"], second
    assert "材质" in second["answer"], second


def test_comparison_choice_followup_reuses_the_adjudicated_choice(route_client_and_db):
    client, headers, _ = route_client_and_db

    first = client.post(
        "/api/customer-service/ask?debug=true",
        json={
            "question": "我在 CW-C83 和 CW-C06PRO 之间纠结，周末两个人徒步，哪个更合适？"
        },
        headers=headers,
    ).json()
    selected_sku = (first.get("answer_metadata") or {}).get("final_choice_sku")
    assert selected_sku in {"CW-C83", "CW-C06PRO"}, first
    other_sku = "CW-C06PRO" if selected_sku == "CW-C83" else "CW-C83"

    second = client.post(
        "/api/customer-service/ask?debug=true",
        json={
            "question": "你更建议哪一个？为什么？",
            "conversation_id": first["conversation_id"],
        },
        headers=headers,
    ).json()

    assert second["result_skus"] == [selected_sku], second
    assert selected_sku in second["answer"], second
    assert other_sku not in second["answer"], second


def test_compound_contents_question_addresses_missing_package_field(route_client_and_db):
    client, headers, _ = route_client_and_db

    response = client.post(
        "/api/customer-service/ask?debug=true",
        json={
            "question": "CF-PG19 里面具体有些什么？买回来是不是就能直接用？"
        },
        headers=headers,
    )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["result_skus"] == ["CF-PG19"], payload
    assert "包装内容包括" in payload["answer"], payload
    assert "使用准备" in payload["answer"] or "首次使用" in payload["answer"], payload


def test_customer_service_ask_route_level_multiturn_recommendation_context_survives_heat_source_and_alternative_followups(
    route_client_and_db,
):
    client, headers, _ = route_client_and_db

    turn1 = client.post(
        "/api/customer-service/ask?debug=true",
        json={"question": "我一个人徒步，想轻一点，推荐一个锅。"},
        headers=headers,
    )
    assert turn1.status_code == 200, turn1.text
    payload1 = turn1.json()
    meta1 = next((item for item in payload1["sources"] if item.get("type") == "agent_meta"), {})
    rec1 = meta1.get("recommendation_context") or {}
    assert payload1["answer_type"] == "recommendation"
    assert payload1["result_skus"]
    assert rec1.get("recommended_skus")
    assert rec1.get("recommended_skus")[0] == payload1["result_skus"][0]
    assert rec1.get("answer_type") == "recommendation"
    turn1_contract = rec1.get("effective_recommendation_contract") or {}
    assert turn1_contract.get("subject_category") == "锅具"
    assert (turn1_contract.get("people_min"), turn1_contract.get("people_max")) == (1, 1)
    assert turn1_contract.get("scenario") == ["hiking"]
    assert turn1_contract.get("weight_preference") == "lighter"
    conversation_id = payload1["conversation_id"]

    turn2 = client.post(
        "/api/customer-service/ask?debug=true",
        json={"question": "它能不能用酒精炉？", "conversation_id": conversation_id},
        headers=headers,
    )
    assert turn2.status_code == 200, turn2.text
    payload2 = turn2.json()
    meta2 = next((item for item in payload2["sources"] if item.get("type") == "agent_meta"), {})
    rec2 = meta2.get("recommendation_context") or {}
    assert payload2["answer_type"] == "product_detail"
    assert payload2["answer_type"] != "knowledge_base_answer"
    assert payload2["result_skus"] == [payload1["result_skus"][0]]
    assert payload1["result_skus"][0] in payload2["answer"]
    assert rec2.get("recommended_skus", [None])[0] == payload1["result_skus"][0]
    assert not (meta2.get("candidate_context") or {}).get("empty_subset")
    turn2_contract = rec2.get("effective_recommendation_contract") or {}
    assert turn2_contract.get("subject_category") == "锅具"
    assert (turn2_contract.get("people_min"), turn2_contract.get("people_max")) == (1, 1)
    assert turn2_contract.get("scenario") == ["hiking"]
    assert turn2_contract.get("weight_preference") == "lighter"
    assert turn2_contract.get("heat_sources") == ["酒精炉"]
    assert (rec2.get("contract_merge_provenance") or {}).get("heat_sources") == {
        "source_turn": 2,
        "provenance": "current_turn_addition",
    }

    turn3 = client.post(
        "/api/customer-service/ask?debug=true",
        json={"question": "有没有更便宜一点的替代？", "conversation_id": conversation_id},
        headers=headers,
    )
    assert turn3.status_code == 200, turn3.text
    payload3 = turn3.json()
    assert payload3["answer_type"] != "knowledge_base_answer"
    assert payload3["result_skus"]
    assert payload1["result_skus"][0] not in payload3["result_skus"]
    assert "无法验证是否比上一款更便宜" in payload3["answer"]
    assert "上一轮在这些候选中已经没有筛到" not in payload3["answer"]
    meta3 = next((item for item in payload3["sources"] if item.get("type") == "agent_meta"), {})
    rec3 = meta3.get("recommendation_context") or {}
    turn3_contract = rec3.get("effective_recommendation_contract") or {}
    assert turn3_contract.get("subject_category") == "锅具"
    assert (turn3_contract.get("people_min"), turn3_contract.get("people_max")) == (1, 1)
    assert turn3_contract.get("scenario") == ["hiking"]
    assert turn3_contract.get("weight_preference") == "lighter"
    assert turn3_contract.get("heat_sources") == ["酒精炉"]
    assert turn3_contract.get("relative_price_preference") == "cheaper_than_anchor"
    assert turn3_contract.get("price_anchor_sku") == payload1["result_skus"][0]
    assert payload1["result_skus"][0] in turn3_contract.get("exclusions", [])


def test_semantic_alternative_followup_consumes_persisted_recommendation_contract(
    route_client_and_db,
    monkeypatch,
):
    client, headers, _ = route_client_and_db
    calls = []

    async def fake_semantic_plan(*_args, **_kwargs):
        return {
            "called": True,
            "route_family": "recommendation",
            "route_hint": "recommendation",
            "question_type": "recommendation",
            "recommendation_constraints": {
                "subject_kind": "cookware",
                "heat_sources": ["alcohol_stove"],
            },
            "confidence": 0.9,
            "ambiguity": False,
            "evidence_required": True,
        }

    monkeypatch.setattr(
        customer_agent_planner_service,
        "plan_customer_question_semantic",
        fake_semantic_plan,
    )

    async def fake_semantic_recommendation(db, question, _plan, _recommendation_context=None):
        calls.append(question)
        row = next(
            row
            for row in customer_service_service._phase1_catalog_rows(db, "产品")
            if row.get("sku") == "CW-S10-A"
        )
        return {
            "intent": "query_products",
            "answer_type": "product_query",
            "answer": "适合酒精炉的锅具可以看看激川单锅（CW-S10-A）。",
            "results": [row],
            "result_skus": ["CW-S10-A"],
            "candidate_skus": ["CW-S10-A"],
            "answer_metadata": {
                "source": "validated_semantic_preplan_then_same_sku_verification",
                "recommendation_contract": {
                    "subject_category": "锅具",
                    "subject_kind": "cookware",
                    "heat_sources": ["酒精炉"],
                    "hard_constraints": ["heat_source"],
                },
            },
            "debug": {"agent_mode": "semantic_recommendation_contract"},
            "skip_polish": True,
        }

    monkeypatch.setattr(
        customer_service_service,
        "_semantic_recommendation_contract_result",
        fake_semantic_recommendation,
    )

    first = client.post(
        "/api/customer-service/ask?debug=true",
        json={"question": "适合酒精炉的锅具推荐一下。"},
        headers=headers,
    )
    assert first.status_code == 200, first.text
    first_payload = first.json()
    first_sku = first_payload["result_skus"][0]
    conversation_id = first_payload["conversation_id"]

    second = client.post(
        "/api/customer-service/ask?debug=true",
        json={"question": "还有其他推荐吗", "conversation_id": conversation_id},
        headers=headers,
    )
    assert second.status_code == 200, second.text
    second_payload = second.json()
    assert first_sku not in second_payload["result_skus"], second_payload
    assert "排除" in second_payload["answer"] or "没有另一款" in second_payload["answer"], second_payload
    assert len(calls) == 1, calls


def test_recommendation_explanation_survives_intervening_product_field_followup(route_client_and_db):
    client, headers, _ = route_client_and_db

    first = client.post(
        "/api/customer-service/ask?debug=true",
        json={"question": "推荐一款适合露营的烤盘。"},
        headers=headers,
    ).json()
    anchor = first["result_skus"][0]
    conversation_id = first["conversation_id"]

    detail = client.post(
        "/api/customer-service/ask?debug=true",
        json={"question": "第一个是什么材质？", "conversation_id": conversation_id},
        headers=headers,
    ).json()
    assert detail["result_skus"] == [anchor]

    explanation = client.post(
        "/api/customer-service/ask?debug=true",
        json={"question": "为什么推荐它？", "conversation_id": conversation_id},
        headers=headers,
    ).json()
    assert explanation["answer_type"] == "recommendation", explanation
    assert explanation["result_skus"][0] == anchor, explanation
    assert anchor in explanation["answer"], explanation["answer"]
    assert [str(row.get("sku") or "").upper() for row in explanation.get("results") or []] == [anchor]

    alternative = client.post(
        "/api/customer-service/ask?debug=true",
        json={"question": "换一个。", "conversation_id": conversation_id},
        headers=headers,
    ).json()
    assert alternative["answer_type"] == "recommendation", alternative
    assert alternative["result_skus"], alternative
    assert anchor not in alternative["result_skus"], alternative

    replacement_anchor = alternative["result_skus"][0]
    alternative_meta = next((item for item in alternative.get("sources") or [] if item.get("type") == "agent_meta"), {})
    alternative_context = alternative_meta.get("recommendation_context") or {}
    assert alternative_context.get("active_single_product_anchor") == anchor, alternative
    assert alternative_context.get("replacement_top_sku") == replacement_anchor, alternative
    replacement_weight = client.post(
        "/api/customer-service/ask?debug=true",
        json={"question": "新的这个多重？", "conversation_id": conversation_id},
        headers=headers,
    ).json()
    replacement_debug = replacement_weight.get("debug") or {}
    replacement_entity = replacement_debug.get("entity_resolution_contract") or {}
    replacement_metadata = replacement_weight.get("answer_metadata") or {}
    assert replacement_weight["answer_type"] == "product_detail", replacement_weight
    assert replacement_weight["result_skus"] == [replacement_anchor], replacement_weight
    assert (replacement_debug.get("field_contract") or {}).get("field_type") == "weight", replacement_weight
    assert replacement_entity.get("status") == "resolved", replacement_weight
    assert replacement_entity.get("resolved_sku") == replacement_anchor, replacement_weight
    assert replacement_metadata.get("contract_field_type") == "weight", replacement_weight
    assert replacement_metadata.get("evidence_sku") == replacement_anchor, replacement_weight


def test_replacement_recommendation_with_multiple_results_preserves_active_product_anchor():
    anchor, reason = customer_service_service.update_active_product_anchor(
        previous_anchor="CF-PG19",
        current_result_skus=["CW-PF05", "CW-C74"],
        answer_type="recommendation",
        user_question="换一个。",
        replacement_recommendation=True,
    )

    assert anchor == "CF-PG19"
    assert reason == "preserved_without_new_single_product"






def test_ask_stream_pronoun_manual_followup_keeps_exact_color_anchor(route_client_and_db):
    client, headers, Session = route_client_and_db
    with Session() as db:
        _add_product(db, "KW-K31-白", "天鹅壶4杯白", "咖啡器具", "200ml", "304不锈钢", "卡式炉", "白色天鹅设计", "露营咖啡", 601)
        _add_product(db, "KW-K31-黑", "天鹅壶4杯-黑色", "咖啡器具", "200ml", "304不锈钢", "卡式炉", "黑色天鹅设计", "露营咖啡", 601)
        db.commit()

    first_response = client.post(
        "/api/customer-service/ask-stream",
        json={"question": "天鹅壶4杯黑能用卡式炉吗？"},
        headers=headers,
    )
    first = _parse_sse_payload(first_response.text)
    assert first["result_skus"] == ["KW-K31-黑"]

    second_response = client.post(
        "/api/customer-service/ask-stream",
        json={"question": "它多重？", "conversation_id": first["conversation_id"]},
        headers=headers,
    )
    second = _parse_sse_payload(second_response.text)
    assert second["result_skus"] == ["KW-K31-黑"]

    third_response = client.post(
        "/api/customer-service/ask-stream",
        json={"question": "它有用户手册吗？", "conversation_id": first["conversation_id"]},
        headers=headers,
    )
    third = _parse_sse_payload(third_response.text)
    assert third["result_skus"] == ["KW-K31-黑"], third
    assert "KW-K31-白" not in third["answer"]
    third_debug = third.get("debug") or {}
    assert third_debug.get("agent_mode") == "recommendation_context_product_field"
    assert (third_debug.get("field_contract") or {}).get("field_type") == "manual", third
    third_entity = third_debug.get("entity_resolution_contract") or {}
    assert third_entity.get("status") == "resolved", third
    assert third_entity.get("resolved_sku") == "KW-K31-黑", third
    assert third_entity.get("field_type") == "manual", third
    assert third_debug.get("binding_provenance") == "resolved_entity_contract", third
    assert (third.get("answer_metadata") or {}).get("contract_field_type") == "manual", third

    fourth_response = client.post(
        "/api/customer-service/ask-stream",
        json={"question": "它适合露营吗？", "conversation_id": first["conversation_id"]},
        headers=headers,
    )
    fourth = _parse_sse_payload(fourth_response.text)
    metadata = fourth.get("answer_metadata") or {}
    assert fourth["result_skus"] == ["KW-K31-黑"], fourth
    assert metadata.get("evidence_sku") == "KW-K31-黑", fourth
    assert metadata.get("evidence_field") == "usage_scene", fourth


@pytest.mark.parametrize(
    ("question", "field_type"),
    [
        ("瓦片烤盘Pro包含哪些配件？", "accessories"),
        ("瓦片烤盘Pro包装里有什么？", "accessories"),
        ("瓦片烤盘Pro有没有赠品？", "gift"),
        ("瓦片烤盘Pro有没有用户手册？", "manual"),
    ],
)
def test_named_non_usage_fields_bypass_usage_care_fast_path(route_client_and_db, question, field_type):
    client, headers, Session = route_client_and_db
    with Session() as db:
        _add_product(db, "CF-PG19", "瓦片烤盘", "锅具", "/", "铝合金", "明火", "基础烤盘", "露营煎烤", 1000)
        _add_product(db, "CF-PG19PRO", "瓦片烤盘Pro", "锅具", "/", "铝合金", "明火", "升级烤盘", "露营煎烤", 1100)
        db.commit()
    response = client.post(
        "/api/customer-service/ask?debug=true",
        json={"question": question},
        headers=headers,
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    debug = payload.get("debug") or {}
    contract = debug.get("entity_resolution_contract") or {}
    metadata = payload.get("answer_metadata") or {}

    assert debug.get("agent_mode") != "product_usage_care_fast_path", payload
    assert contract.get("status") == "resolved", payload
    assert contract.get("resolved_sku") == "CF-PG19PRO", payload
    assert contract.get("field_type") == field_type, payload
    assert payload.get("candidate_skus") == ["CF-PG19PRO"], payload
    assert payload.get("result_skus") == ["CF-PG19PRO"], payload
    assert metadata.get("field_evidence_missing") is True, payload
    assert metadata.get("evidence_sku") is None, payload


def test_family_accessories_request_stays_ambiguous(route_client_and_db):
    client, headers, Session = route_client_and_db
    with Session() as db:
        _add_product(db, "CF-PG19", "瓦片盘基础款", "锅具", "/", "铝合金", "明火", "基础烤盘", "露营煎烤", 1000)
        _add_product(db, "CF-PG19PRO", "瓦片盘Pro", "锅具", "/", "铝合金", "明火", "升级烤盘", "露营煎烤", 1100)
        db.commit()
    response = client.post(
        "/api/customer-service/ask?debug=true",
        json={"question": "瓦片盘包含哪些配件？"},
        headers=headers,
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    contract = (payload.get("debug") or {}).get("entity_resolution_contract") or {}

    assert contract.get("status") == "ambiguous", payload
    assert set(payload.get("candidate_skus") or []) == {"CF-PG19", "CF-PG19PRO"}, payload
    assert payload.get("result_skus") == [], payload


@pytest.mark.parametrize("question", ["瓦片烤盘Pro怎么清洁？", "瓦片烤盘Pro怎么使用？"])
def test_named_usage_questions_use_resolved_detail_contract(route_client_and_db, question):
    client, headers, Session = route_client_and_db
    with Session() as db:
        _add_product(db, "CF-PG19PRO", "瓦片烤盘Pro", "锅具", "/", "铝合金", "明火", "升级烤盘", "露营煎烤", 1100)
        _add_product_qa(db, "CF-PG19PRO", "瓦片烤盘Pro怎么清洁？", "使用后用温水和软布清洁并擦干。", tags="清洁,使用")
        _add_product_qa(db, "CF-PG19PRO", "瓦片烤盘Pro怎么使用？", "使用前先清洁并擦干烤盘。", tags="使用,保养")
        db.commit()
    response = client.post(
        "/api/customer-service/ask?debug=true",
        json={"question": question},
        headers=headers,
    )
    assert response.status_code == 200, response.text
    payload = response.json()

    debug = payload.get("debug") or {}
    contract = debug.get("entity_resolution_contract") or {}
    expected_field = "cleaning" if "清洁" in question else "usage_instruction"
    assert debug.get("agent_mode") == "resolved_entity_detail_contract", payload
    assert contract.get("status") == "resolved", payload
    assert contract.get("resolved_sku") == "CF-PG19PRO", payload
    assert contract.get("field_type") == expected_field, payload
    assert payload.get("result_skus") == ["CF-PG19PRO"], payload


def test_product_switch_prefix_keeps_exact_variant_identity(route_client_and_db):
    client, headers, Session = route_client_and_db
    with Session() as db:
        _add_product(db, "KW-K31-白", "天鹅壶4杯白", "咖啡器具", "200ml", "304不锈钢", "卡式炉", "白色天鹅设计", "露营咖啡", 601)
        _add_product(db, "KW-K31-黑", "天鹅壶4杯-黑色", "咖啡器具", "200ml", "304不锈钢", "卡式炉", "黑色天鹅设计", "露营咖啡", 601)
        db.commit()

    first = client.post(
        "/api/customer-service/ask?debug=true",
        json={"question": "瓦片烤盘是什么材质？"},
        headers=headers,
    )
    assert first.status_code == 200, first.text
    conversation_id = first.json()["conversation_id"]

    response = client.post(
        "/api/customer-service/ask?debug=true",
        json={"question": "再看天鹅壶4杯黑。", "conversation_id": conversation_id},
        headers=headers,
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    contract = ((payload.get("debug") or {}).get("entity_resolution_contract") or {})
    assert payload.get("result_skus") == ["KW-K31-黑"], payload
    assert contract.get("status") == "resolved", payload
    assert contract.get("resolved_sku") == "KW-K31-黑", payload


def test_customer_service_ask_route_level_shelter_count_keeps_count_and_display_label(
    route_client_and_db,
):
    client, headers, _ = route_client_and_db

    response = client.post(
        "/api/customer-service/ask?debug=true",
        json={"question": "你们有多少天幕、地垫、帐篷产品？"},
        headers=headers,
    )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["answer_type"] == "product_query"
    assert "183 款" not in payload["answer"]
    assert "天幕、地垫、帐篷" in payload["answer"]
    assert re.search(r"共有\s*1\s*款", payload["answer"]), payload["answer"]
    assert payload["result_skus"] == ["OT-001"]

def test_customer_service_ask_stream_route_level_q17_plural_heat_source_followup_uses_pair_context(
    route_client_and_db,
):
    client, headers, Session = route_client_and_db

    with Session() as db:
        _add_product(
            db,
            "CW-C78",
            "享野套锅",
            "锅具",
            "大锅 3L；小锅 1.7L；水壶 0.8L",
            "硬质氧化铝合金",
            "燃气炉",
            "高性价比 全套收纳",
            "入门级露营 学生露营 短途露营 基础户外烹饪 周末野餐",
            1320,
        )
        db.commit()

    turn1_response = client.post(
        "/api/customer-service/ask-stream",
        json={"question": "轻途套锅和享野套锅有什么区别？"},
        headers=headers,
    )
    assert turn1_response.status_code == 200, turn1_response.text
    turn1 = _parse_sse_payload(turn1_response.text)
    assert turn1["answer_type"] == "comparison"
    assert set(turn1["result_skus"]) == {"CW-C06PRO", "CW-C78"}

    conversation_id = turn1["conversation_id"]
    turn2_response = client.post(
        "/api/customer-service/ask-stream",
        json={"question": "那哪个更适合新手？", "conversation_id": conversation_id},
        headers=headers,
    )
    assert turn2_response.status_code == 200, turn2_response.text
    turn2 = _parse_sse_payload(turn2_response.text)
    assert turn2["answer_type"] == "comparison"
    assert set(turn2["result_skus"]) == {"CW-C06PRO", "CW-C78"}

    turn3_response = client.post(
        "/api/customer-service/ask-stream",
        json={"question": "它们能不能用酒精炉？", "conversation_id": conversation_id},
        headers=headers,
    )
    assert turn3_response.status_code == 200, turn3_response.text
    turn3 = _parse_sse_payload(turn3_response.text)
    debug_plan = ((turn3.get("debug") or {}).get("plan") or {})

    assert turn3["answer_type"] == "product_detail"
    assert turn3["answer_type"] != "knowledge_base_answer"
    assert set(turn3["result_skus"]) == {"CW-C06PRO", "CW-C78"}
    assert debug_plan.get("product_ref") != "它们"
    assert "没有找到它们的明确heat_source" not in turn3["answer"]
    assert re.search(r"(CW-C06PRO|轻途套锅).*(酒精炉)", turn3["answer"]), turn3["answer"]
    assert re.search(r"(CW-C78|享野套锅).*(酒精炉)", turn3["answer"]), turn3["answer"]


def test_customer_service_ask_stream_route_level_ct_t04_bm_keeps_exact_sku(
    route_client_and_db,
):
    client, headers, Session = route_client_and_db

    with Session() as db:
        _add_product(
            db,
            "CT-T04(BM)",
            "出山-功夫茶具（竹套版）",
            "茶具",
            "茶壶和茶杯",
            "竹、陶瓷",
            "/",
            "便携功夫茶具",
            "露营茶席 公园野餐",
            980,
        )
        _add_product(
            db,
            "CT-T04",
            "出山茶具-旗舰版",
            "茶具",
            "茶壶和茶杯",
            "陶瓷",
            "/",
            "旗舰茶具套装",
            "露营茶席 居家泡茶",
            1100,
        )
        db.commit()

    response = client.post(
        "/api/customer-service/ask-stream",
        json={"question": "CT-T04(BM) 适合什么场景？能不能用酒精炉？"},
        headers=headers,
    )

    assert response.status_code == 200, response.text
    payload = _parse_sse_payload(response.text)
    debug_plan = ((payload.get("debug") or {}).get("plan") or {})

    assert payload["answer_type"] == "product_detail"
    assert payload["result_skus"] == ["CT-T04(BM)"]
    assert "CT-T04(BM)" in payload["answer"]
    assert "CT-T04）" not in payload["answer"]
    assert debug_plan.get("product_ref") == "CT-T04(BM)"


@pytest.mark.parametrize(
    "question",
    [
        "公司十几个人露营烧烤，还要烧水泡茶，炉具怎么配？",
        "露营烧烤加煮水，先买炉具还是水壶？",
        "海边风大，想烧烤又想烧热水，用什么炉具更稳？",
        "多人营地聚餐，有烤肉也有热饮，炉子怎么选？",
        "风比较大的营地，炉具和烤盘怎么搭？",
    ],
)
def test_customer_service_ask_route_level_stove_combo_generalization_stays_in_stove_domain(
    route_client_and_db,
    question,
):
    client, headers, Session = route_client_and_db

    response = client.post("/api/customer-service/ask?debug=true", json={"question": question}, headers=headers)

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["answer_type"] == "recommendation", payload
    assert payload["answer_type"] != "knowledge_base_answer"
    assert payload["result_skus"], payload
    assert payload["result_skus"][0] not in {"AC-Z13", "CB253", "CB254"}, payload["result_skus"]
    assert payload["answer"], payload

    with Session() as db:
        front_categories = {
            product.sku: product.category
            for product in db.query(Product).filter(Product.sku.in_(payload["result_skus"][:2])).all()
        }

    assert front_categories, payload
    if "烤盘" in question:
        assert {"炉具", "锅具"}.issubset(set(front_categories.values())), front_categories
        assert "烤盘" in payload["answer"], payload
    else:
        assert all(category == "炉具" for category in front_categories.values()), front_categories


def test_customer_service_ask_route_level_category_accessories_prioritize_clear_accessories(
    route_client_and_db,
):
    client, headers, _ = route_client_and_db

    response = client.post("/api/customer-service/ask?debug=true", json={"question": "有哪些配件产品？"}, headers=headers)

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["answer_type"] == "query_products"
    assert payload["answer_type"] != "knowledge_base_answer"
    assert payload["result_skus"]
    assert "配件" in payload["answer"]
    assert "明确配件" in payload["answer"]
    top_three = payload["result_skus"][:3]
    assert "ACC-BURN-1" in top_three
    assert "ACC-BOARD-1" in top_three or "ACC-HANDLE-1" in top_three
    assert "ACC-001" not in top_three
    assert "ACC-BOWL-1" not in top_three
    assert "ACC-GUN-1" not in top_three
    top_five = payload["result_skus"][:5]
    assert "ACC-BAG-1" not in top_five
    assert "ACC-BOX-1" not in top_five


def test_customer_service_ask_route_level_category_waterware_prioritize_drinking_domain(
    route_client_and_db,
):
    client, headers, Session = route_client_and_db

    response = client.post("/api/customer-service/ask?debug=true", json={"question": "有哪些水具产品？"}, headers=headers)

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["answer_type"] == "query_products"
    assert payload["answer_type"] != "knowledge_base_answer"
    assert payload["result_skus"]
    assert "水具" in payload["answer"]
    assert "通用饮水" in payload["answer"]
    top_three = payload["result_skus"][:3]
    assert {"WT-001", "WT-002", "KTL-001"} & set(top_three)
    assert "KTL-COF-1" not in top_three
    assert "WT-GIFT-1" not in payload["result_skus"][:5]

    with Session() as db:
        categories = {
            product.sku: product.category
            for product in db.query(Product).filter(Product.sku.in_(payload["result_skus"][:5])).all()
        }
    assert all(category in {"水具", "水壶"} for category in categories.values()), categories


@pytest.mark.parametrize(
    "question",
    [
        "三口之家周末近郊露营，锅具别太重但容量别太小。",
        "长途徒步只想带一个锅，能烧水也能做简单餐食。",
        "露营烧烤场景，炉具和烤盘怎么搭更合适？",
        "营地早餐场景想煎东西，锅具和烤盘哪个更合适？",
        "女生一个人公园野餐，想轻一点又能烧水的炊具。",
        "长途自驾露营，人数四五个，锅具更看重容量和稳定性。",
        "烧烤场景想带炉子和烤盘，先买哪类最值？",
        "多人露营想做正餐，容量大一点但收纳别太差。",
    ],
)
def test_customer_service_ask_route_level_targeted_warning_scenarios_return_recommendation(
    route_client_and_db,
    question,
):
    client, headers, Session = route_client_and_db

    response = client.post("/api/customer-service/ask?debug=true", json={"question": question}, headers=headers)

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["answer_type"] == "recommendation", payload
    assert payload["answer_type"] != "knowledge_base_answer"
    assert payload["answer_type"] != "product_detail"
    assert payload["result_skus"], payload
    assert re.search(r"(推荐|更推荐|优先推荐)", payload["answer"]), payload["answer"]
    assert re.search(r"(备选|也可以看|如果你更看重)", payload["answer"]), payload["answer"]

    with Session() as db:
        categories = {
            product.sku: product.category
            for product in db.query(Product).filter(Product.sku.in_(payload["result_skus"][:3])).all()
        }

    if any(term in question for term in ("烧烤", "烤盘", "炉具", "炉子")):
        assert payload["result_skus"][0] != "CW-DRP01"
        assert categories.get(payload["result_skus"][0]) in {"炉具", "锅具"}
        assert ("炉具" in payload["answer"] or "炉子" in payload["answer"]) and "烤盘" in payload["answer"]
    else:
        assert categories.get(payload["result_skus"][0]) == "锅具", categories


@pytest.mark.parametrize(
    "question",
    [
        "有哪些配件更偏收纳？",
        "有哪些配件适合收纳？",
        "收纳类配件有哪些？",
        "露营收纳配件有哪些？",
    ],
)
def test_customer_service_ask_route_level_accessory_storage_queries_stay_structured(
    route_client_and_db,
    question,
):
    client, headers, Session = route_client_and_db

    response = client.post("/api/customer-service/ask?debug=true", json={"question": question}, headers=headers)

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["answer_type"] in {"query_products", "product_query"}, payload
    assert payload["answer_type"] != "knowledge_base_answer"
    assert payload["result_skus"], payload
    assert payload["answer"], payload

    with Session() as db:
        categories = {
            product.sku: product.category
            for product in db.query(Product).filter(Product.sku.in_(payload["result_skus"][:3])).all()
        }

    assert categories, payload
    assert all(category == "配件" for category in categories.values()), categories


def test_product_like_unknown_field_with_category_tail_does_not_bind_weak_single_candidate(
    route_client_and_db,
):
    client, headers, _ = route_client_and_db
    response = client.post(
        "/api/customer-service/ask?debug=true",
        json={"question": "荒野星壶水壶价格"},
        headers=headers,
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    entity_contract = (payload.get("debug") or {}).get("entity_resolution_contract") or {}
    assert payload.get("answer_type") in {"clarification", "product_detail"}, payload
    assert payload.get("result_skus") in ([], None), payload
    assert payload.get("candidate_skus") in ([], None), payload
    assert "CW-C47-1" not in str(payload.get("answer") or ""), payload
    assert (payload.get("answer_metadata") or {}).get("source") != "resolved_entity_unknown_field_fallback", payload
    if entity_contract:
        assert entity_contract.get("status") in {"ambiguous", "unresolved"}, entity_contract
        assert entity_contract.get("matched_by") not in {
            "sku_exact",
            "canonical_name_exact",
            "normalized_alias_exact",
        }, entity_contract


def test_canonical_field_subject_routing_keeps_entity_identity_stable_across_fields(
    route_client_and_db,
):
    client, headers, Session = route_client_and_db
    with Session() as db:
        _add_product(
            db,
            "CF-PG19PRO",
            "瓦片烤盘Pro",
            "锅具",
            "8英寸",
            "硬质氧化铝合金",
            "燃气炉",
            "升级烤盘",
            "露营烧烤",
            1000,
        )
        kettle = db.query(Product).filter(Product.sku == "KW-K32-白").one()
        kettle.product_name_cn = "天鹅壶9杯白"
        specs = db.query(ProductSpecs).filter(ProductSpecs.product_id == kettle.id).one()
        specs.gross_weight_g = 954
        db.commit()

    for question in (
        "瓦片烤盘 有赠品吗？",
        "瓦片烤盘 保修多久？",
        "瓦片烤盘 今天能发吗？",
    ):
        response = client.post("/api/customer-service/ask?debug=true", json={"question": question}, headers=headers)
        assert response.status_code == 200, response.text
        payload = response.json()
        assert payload.get("answer_type") == "product_detail", payload
        assert payload.get("result_skus") == ["CF-PG19"], payload
        assert "CF-PG19PRO" not in str(payload.get("answer") or ""), payload
        assert (payload.get("debug") or {}).get("agent_mode") != "weather", payload

    weight_response = client.post(
        "/api/customer-service/ask?debug=true",
        json={"question": "天鹅壶9杯白本身多重？"},
        headers=headers,
    )
    assert weight_response.status_code == 200, weight_response.text
    weight_payload = weight_response.json()
    assert weight_payload.get("result_skus") == ["KW-K32-白"], weight_payload
    assert "954" in str(weight_payload.get("answer") or ""), weight_payload

    weak_response = client.post(
        "/api/customer-service/ask?debug=true",
        json={"question": "荒野星壶水壶价格"},
        headers=headers,
    )
    assert weak_response.status_code == 200, weak_response.text
    weak_payload = weak_response.json()
    assert weak_payload.get("result_skus") in ([], None), weak_payload
    assert "CW-C47-1" not in str(weak_payload.get("answer") or ""), weak_payload


@pytest.mark.parametrize(
    ("question", "expected_sku", "forbidden_mode"),
    [
        ("瓦片烤盘是什么材质？", "CF-PG19", None),
        ("瓦片烤盘能不能明火用？", "CF-PG19", None),
        ("瓦片烤盘今天能发货吗？", "CF-PG19", "weather"),
        ("瓦片烤盘现在下单什么时候发？", "CF-PG19", "weather"),
        ("瓦片烤盘多久可以寄出？", "CF-PG19", "product_qa_fast_path"),
        ("瓦片烤盘质保多长时间？", "CF-PG19", None),
        ("瓦片烤盘有没有保修？", "CF-PG19", None),
        ("天鹅壶9杯白能明火烧吗？", "KW-K32-白", None),
        ("天鹅壶4杯白适合几个人？", "KW-K31-白", None),
    ],
)
def test_natural_field_phrase_routes_keep_exact_product_identity(
    route_client_and_db,
    question,
    expected_sku,
    forbidden_mode,
):
    client, headers, Session = route_client_and_db
    with Session() as db:
        kettle_9 = db.query(Product).filter(Product.sku == "KW-K32-白").one()
        kettle_9.product_name_cn = "天鹅壶9杯白"
        kettle_4 = db.query(Product).filter(Product.sku == "KW-K31-白").one()
        kettle_4.product_name_cn = "天鹅壶4杯白"
        db.commit()

    response = client.post("/api/customer-service/ask?debug=true", json={"question": question}, headers=headers)
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload.get("answer_type") == "product_detail", payload
    assert payload.get("result_skus") == [expected_sku], payload
    if forbidden_mode:
        assert (payload.get("debug") or {}).get("agent_mode") != forbidden_mode, payload


def test_people_field_missing_evidence_does_not_infer_count_from_variant_or_features(
    route_client_and_db,
):
    client, headers, Session = route_client_and_db
    with Session() as db:
        product = db.query(Product).filter(Product.sku == "KW-K32-白").one()
        product.product_name_cn = "天鹅壶9杯白"
        specs = db.query(ProductSpecs).filter(ProductSpecs.product_id == product.id).one()
        specs.capacity = "450ML"
        specs.technical_advantages = "满足 9 人咖啡需求"
        business = db.query(ProductBusiness).filter(ProductBusiness.product_id == product.id).one()
        business.target_audience = "户外用户"
        business.positioning = "9杯手冲咖啡壶"
        db.commit()

    payload = client.post(
        "/api/customer-service/ask?debug=true",
        json={"question": "天鹅壶9杯白适合几个人？"},
        headers=headers,
    ).json()

    metadata = payload.get("answer_metadata") or {}
    answer = str(payload.get("answer") or "")
    assert payload.get("result_skus") == ["KW-K32-白"], payload
    assert metadata.get("field_evidence_missing") is True, metadata
    assert metadata.get("field_evidence_match") is False, metadata
    assert metadata.get("evidence_sku") is None, metadata
    assert "无法确认" in answer or "未显示" in answer or "未标注" in answer, payload
    assert "9 人" not in answer and "9人" not in answer, payload


def test_people_field_uses_explicit_same_sku_target_audience_evidence(
    route_client_and_db,
):
    client, headers, Session = route_client_and_db
    with Session() as db:
        product = db.query(Product).filter(Product.sku == "KW-K31-白").one()
        product.product_name_cn = "天鹅壶4杯白"
        business = db.query(ProductBusiness).filter(ProductBusiness.product_id == product.id).one()
        business.target_audience = "适合2-3人使用"
        db.commit()

    payload = client.post(
        "/api/customer-service/ask?debug=true",
        json={"question": "天鹅壶4杯白适合几个人？"},
        headers=headers,
    ).json()

    metadata = payload.get("answer_metadata") or {}
    assert payload.get("result_skus") == ["KW-K31-白"], payload
    assert metadata.get("field_evidence_match") is True, metadata
    assert metadata.get("field_evidence_missing") is False, metadata
    assert metadata.get("evidence_source") == "business.target_audience", metadata
    assert metadata.get("evidence_sku") == "KW-K31-白", metadata
    assert "2-3人" in str(payload.get("answer") or "").replace(" ", ""), payload


def test_explicit_cup_and_color_variant_uses_same_sku_material_evidence(
    route_client_and_db,
):
    client, headers, Session = route_client_and_db
    variants = (
        ("KW-K31-白", "天鹅壶4杯-白色", "白色"),
        ("KW-K32-白", "天鹅壶9杯-白色", "白色"),
        ("KW-K31-黑", "天鹅壶4杯-黑色", "黑色"),
        ("KW-K32-黑", "天鹅壶9杯-黑色", "黑色"),
    )
    with Session() as db:
        for sku, name, color in variants:
            product = db.query(Product).filter(Product.sku == sku).one()
            product.product_name_cn = name
            specs = db.query(ProductSpecs).filter(ProductSpecs.product_id == product.id).one()
            specs.color = color
            specs.body_material = "304不锈钢"
        db.commit()

    payload = client.post(
        "/api/customer-service/ask?debug=true",
        json={"question": "天鹅壶4杯黑是什么材质？"},
        headers=headers,
    ).json()

    metadata = payload.get("answer_metadata") or {}
    contract = (payload.get("debug") or {}).get("entity_resolution_contract") or {}
    assert payload.get("answer_type") == "product_detail", payload
    assert contract.get("status") == "resolved", contract
    assert contract.get("resolved_sku") == "KW-K31-黑", contract
    assert contract.get("matched_by") == "normalized_alias_exact", contract
    assert contract.get("resolver_candidate_skus") == ["KW-K31-黑"], contract
    assert metadata.get("evidence_source") == "specs.body_material", metadata
    assert metadata.get("evidence_sku") == "KW-K31-黑", metadata
    assert metadata.get("field_evidence_match") is True, metadata
    assert payload.get("candidate_skus") == ["KW-K31-黑"], payload
    assert payload.get("result_skus") == ["KW-K31-黑"], payload
    assert "304不锈钢" in str(payload.get("answer") or ""), payload


def test_variant_resolution_keeps_missing_or_nonexistent_cup_unresolved(
    route_client_and_db,
):
    client, headers, Session = route_client_and_db
    with Session() as db:
        for sku, name in (
            ("KW-K31-黑", "天鹅壶4杯-黑色"),
            ("KW-K32-黑", "天鹅壶9杯-黑色"),
        ):
            db.query(Product).filter(Product.sku == sku).one().product_name_cn = name
        db.commit()

    ambiguous = client.post(
        "/api/customer-service/ask?debug=true",
        json={"question": "天鹅壶黑色是什么材质？"},
        headers=headers,
    ).json()
    nonexistent = client.post(
        "/api/customer-service/ask?debug=true",
        json={"question": "天鹅壶6杯黑是什么材质？"},
        headers=headers,
    ).json()

    assert ambiguous.get("result_skus") == [], ambiguous
    assert ambiguous.get("candidate_skus") == ["KW-K31-黑", "KW-K32-黑"], ambiguous
    assert nonexistent.get("result_skus") == [], nonexistent
    assert nonexistent.get("candidate_skus") == [], nonexistent


def test_family_shorthand_with_cup_but_no_color_stays_in_entity_detail_clarification(
    route_client_and_db,
):
    client, headers, Session = route_client_and_db
    with Session() as db:
        for sku, name, color in (
            ("KW-K31-白", "天鹅壶4杯-白色", "白色"),
            ("KW-K32-白", "天鹅壶9杯-白色", "白色"),
            ("KW-K31-黑", "天鹅壶4杯-黑色", "黑色"),
            ("KW-K32-黑", "天鹅壶9杯-黑色", "黑色"),
        ):
            product = db.query(Product).filter(Product.sku == sku).one()
            product.product_name_cn = name
            specs = db.query(ProductSpecs).filter(ProductSpecs.product_id == product.id).one()
            specs.color = color
            specs.heat_source = "明火直烧、卡式炉"
        db.commit()

    payload = client.post(
        "/api/customer-service/ask?debug=true",
        json={"question": "天鹅9杯能明火吗？"},
        headers=headers,
    ).json()

    contract = (payload.get("debug") or {}).get("entity_resolution_contract") or {}
    assert payload.get("intent") == "clarify", payload
    assert payload.get("answer_type") == "clarification", payload
    assert (payload.get("debug") or {}).get("agent_mode") == "entity_state_detail_ambiguous", payload
    assert contract.get("field_type") == "heat_source", contract
    assert contract.get("status") == "ambiguous", contract
    assert contract.get("resolver_candidate_skus") == ["KW-K32-白", "KW-K32-黑"], contract
    assert payload.get("candidate_skus") == ["KW-K32-白", "KW-K32-黑"], payload
    assert payload.get("result_skus") == [], payload
    assert "KW-K31" not in str(payload.get("answer") or ""), payload


@pytest.mark.parametrize(
    ("question", "expected_sku"),
    [
        ("天鹅9杯白能明火吗？", "KW-K32-白"),
        ("天鹅9杯黑能明火吗？", "KW-K32-黑"),
    ],
)
def test_family_shorthand_complete_variant_uses_same_sku_heat_source(
    route_client_and_db,
    question,
    expected_sku,
):
    client, headers, Session = route_client_and_db
    with Session() as db:
        for sku, name, color in (
            ("KW-K32-白", "天鹅壶9杯-白色", "白色"),
            ("KW-K32-黑", "天鹅壶9杯-黑色", "黑色"),
        ):
            product = db.query(Product).filter(Product.sku == sku).one()
            product.product_name_cn = name
            specs = db.query(ProductSpecs).filter(ProductSpecs.product_id == product.id).one()
            specs.color = color
            specs.heat_source = "明火直烧、卡式炉"
        db.commit()

    payload = client.post(
        "/api/customer-service/ask?debug=true",
        json={"question": question},
        headers=headers,
    ).json()

    metadata = payload.get("answer_metadata") or {}
    contract = (payload.get("debug") or {}).get("entity_resolution_contract") or {}
    assert payload.get("answer_type") == "product_detail", payload
    assert contract.get("status") == "resolved", contract
    assert contract.get("resolved_sku") == expected_sku, contract
    assert contract.get("matched_by") == "normalized_alias_exact", contract
    assert metadata.get("evidence_source") == "specs.heat_source", metadata
    assert metadata.get("evidence_sku") == expected_sku, metadata
    assert payload.get("candidate_skus") == [expected_sku], payload
    assert payload.get("result_skus") == [expected_sku], payload


def test_family_shorthand_nonexistent_spec_never_falls_back_to_catalog_results(
    route_client_and_db,
):
    client, headers, Session = route_client_and_db
    with Session() as db:
        for sku, name in (
            ("KW-K31-白", "天鹅壶4杯-白色"),
            ("KW-K32-白", "天鹅壶9杯-白色"),
        ):
            db.query(Product).filter(Product.sku == sku).one().product_name_cn = name
        db.commit()

    payload = client.post(
        "/api/customer-service/ask?debug=true",
        json={"question": "天鹅6杯能明火吗？"},
        headers=headers,
    ).json()

    contract = (payload.get("debug") or {}).get("entity_resolution_contract") or {}
    assert payload.get("intent") == "clarify", payload
    assert contract.get("status") == "unresolved", contract
    assert contract.get("status_reason") == "explicit_attribute_conflict", contract
    assert payload.get("candidate_skus") == [], payload
    assert payload.get("result_skus") == [], payload
    assert (payload.get("debug") or {}).get("primary_source") != "query_products", payload


def test_explicit_variant_conflict_blocks_product_qa_identity_and_result_skus(
    route_client_and_db,
):
    client, headers, _ = route_client_and_db

    conflict = client.post(
        "/api/customer-service/ask?debug=true",
        json={"question": "瓦片烤盘9杯白多重？"},
        headers=headers,
    ).json()
    normal = client.post(
        "/api/customer-service/ask?debug=true",
        json={"question": "瓦片烤盘多重？"},
        headers=headers,
    ).json()

    conflict_contract = (conflict.get("debug") or {}).get("entity_resolution_contract") or {}
    assert conflict_contract.get("status") == "unresolved", conflict
    assert conflict_contract.get("status_reason") == "explicit_attribute_conflict", conflict_contract
    assert conflict.get("candidate_skus") == [], conflict
    assert conflict.get("result_skus") == [], conflict
    assert (conflict.get("debug") or {}).get("agent_mode") != "product_qa_fast_path", conflict
    assert "1.00kg" not in str(conflict.get("answer") or ""), conflict

    assert normal.get("result_skus") == ["CF-PG19"], normal
    assert str(normal.get("answer") or ""), normal


@pytest.mark.parametrize(
    "question",
    [
        "瓦片烤盘是用什么做的？",
        "瓦片烤盘由什么做成？",
        "瓦片烤盘是什么做的？",
        "瓦片烤盘用什么制成？",
    ],
)
def test_material_predicate_route_uses_structured_material_evidence(route_client_and_db, question):
    client, headers, _ = route_client_and_db
    response = client.post(
        "/api/customer-service/ask?debug=true",
        json={"question": question},
        headers=headers,
    )

    assert response.status_code == 200, response.text
    payload = response.json()
    contract = (payload.get("debug") or {}).get("entity_resolution_contract") or {}
    evidence = payload.get("evidence") or []
    assert payload.get("result_skus") == ["CF-PG19"], payload
    assert contract.get("field_type") == "material", contract
    assert contract.get("matched_by") == "canonical_name_exact", contract
    assert "铝合金" in str(payload.get("answer") or ""), payload
    assert (payload.get("debug") or {}).get("agent_mode") != "product_qa_fast_path", payload
    assert any(item.get("sku") == "CF-PG19" and item.get("field_label") == "材质" for item in evidence), evidence
    assert "核心卖点" not in str(payload.get("answer") or ""), payload


@pytest.mark.parametrize(
    "question",
    [
        "瓦片盘是用什么做的？",
        "烤盘是用什么做的？",
        "不存在的烤盘是用什么做的？",
    ],
)
def test_material_predicate_unresolved_entities_do_not_fall_back_to_recommendations(
    route_client_and_db,
    question,
):
    client, headers, _ = route_client_and_db
    response = client.post(
        "/api/customer-service/ask?debug=true",
        json={"question": question},
        headers=headers,
    )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload.get("result_skus") == [], payload
    assert payload.get("answer_type") != "product_query", payload
    assert payload.get("intent") != "query_products", payload


@pytest.mark.parametrize(
    ("resolver_candidate_skus", "expected"),
    [
        (["SKU-A"], []),
        (["SKU-A", "sku-a", "SKU-A"], []),
        (["SKU-A", "SKU-B", "sku-a"], ["SKU-A", "SKU-B"]),
    ],
)
def test_phase2_displayable_clarification_candidates_require_distinct_multiple_skus(
    resolver_candidate_skus,
    expected,
):
    class Contract:
        status = "ambiguous"

    contract = Contract()
    contract.resolver_candidate_skus = resolver_candidate_skus

    assert customer_service_service._displayable_phase2_clarification_candidate_skus(contract) == expected


def test_heat_source_predicate_exact_product_precedes_griddle_catalog_route(route_client_and_db):
    client, headers, _ = route_client_and_db
    payload = client.post(
        "/api/customer-service/ask?debug=true",
        json={"question": "瓦片烤盘支持哪些炉子？"},
        headers=headers,
    ).json()

    metadata = payload.get("answer_metadata") or {}
    contract = (payload.get("debug") or {}).get("entity_resolution_contract") or {}
    assert payload.get("answer_type") == "product_detail", payload
    assert payload.get("result_skus") == ["CF-PG19"], payload
    assert contract.get("matched_by") == "canonical_name_exact", contract
    assert contract.get("field_type") == "heat_source", contract
    assert metadata.get("evidence_source") == "specs.heat_source", metadata
    assert metadata.get("evidence_sku") == "CF-PG19", metadata
    assert "燃气炉" in str(payload.get("answer") or ""), payload
    assert (payload.get("debug") or {}).get("agent_mode") != "structured_griddle_stove_query", payload


def test_heat_source_yes_no_exact_product_uses_same_sku_evidence(route_client_and_db):
    client, headers, Session = route_client_and_db
    with Session() as db:
        product = db.query(Product).filter(Product.sku == "CF-PG19").one()
        specs = db.query(ProductSpecs).filter(ProductSpecs.product_id == product.id).one()
        specs.heat_source = "燃气炉、卡式炉、电磁炉"
        db.commit()

    payload = client.post(
        "/api/customer-service/ask?debug=true",
        json={"question": "瓦片烤盘可以放电磁炉上吗？"},
        headers=headers,
    ).json()

    metadata = payload.get("answer_metadata") or {}
    contract = (payload.get("debug") or {}).get("entity_resolution_contract") or {}
    assert payload.get("answer_type") == "product_detail", payload
    assert payload.get("result_skus") == ["CF-PG19"], payload
    assert contract.get("matched_by") == "canonical_name_exact", contract
    assert contract.get("field_type") == "heat_source", contract
    assert metadata.get("evidence_source") == "specs.heat_source", metadata
    assert metadata.get("evidence_sku") == "CF-PG19", metadata
    assert "电磁炉" in str(payload.get("answer") or ""), payload
    assert (payload.get("debug") or {}).get("agent_mode") == "resolved_entity_detail_contract", payload


@pytest.mark.parametrize(
    ("question", "expected_sku", "forbidden_sku"),
    [
        ("瓦片烤盘下单后几天发出？", "CF-PG19", "CF-PG19PRO"),
        ("瓦片烤盘Pro什么时候发货？", "CF-PG19PRO", "CF-PG19"),
    ],
)
def test_shipping_exact_missing_field_keeps_single_product_identity(
    route_client_and_db,
    question,
    expected_sku,
    forbidden_sku,
):
    client, headers, Session = route_client_and_db
    with Session() as db:
        if db.query(Product).filter(Product.sku == "CF-PG19PRO").first() is None:
            _add_product(
                db,
                "CF-PG19PRO",
                "瓦片烤盘Pro",
                "锅具",
                "9英寸",
                "铝合金",
                "燃气炉",
                "Pro烤盘",
                "露营煎烤",
                820,
            )
            db.commit()

    payload = client.post(
        "/api/customer-service/ask?debug=true",
        json={"question": question},
        headers=headers,
    ).json()

    metadata = payload.get("answer_metadata") or {}
    contract = (payload.get("debug") or {}).get("entity_resolution_contract") or {}
    assert payload.get("answer_type") == "product_detail", payload
    assert contract.get("matched_by") == "canonical_name_exact", contract
    assert contract.get("resolved_sku") == expected_sku, contract
    assert contract.get("field_type") == "shipping", contract
    assert payload.get("candidate_skus") == [expected_sku], payload
    assert payload.get("result_skus") == [expected_sku], payload
    assert forbidden_sku not in payload.get("candidate_skus", []), payload
    assert forbidden_sku not in payload.get("result_skus", []), payload
    assert metadata.get("evidence_status") == "missing", metadata
    assert any(term in str(payload.get("answer") or "") for term in ("未标注", "未维护", "无法确认")), payload


@pytest.mark.parametrize(
    "question",
    [
        "不存在的烤盘什么时候发货？",
        "烤盘一般多久发货？",
    ],
)
def test_shipping_unresolved_or_generic_subject_does_not_bind_product(route_client_and_db, question):
    client, headers, _ = route_client_and_db
    payload = client.post(
        "/api/customer-service/ask?debug=true",
        json={"question": question},
        headers=headers,
    ).json()

    assert payload.get("candidate_skus") == [], payload
    assert payload.get("result_skus") == [], payload
    assert payload.get("answer_type") in {"clarification", "product_detail"}, payload


def test_dimensions_predicate_exact_product_uses_body_dimensions_only(route_client_and_db):
    client, headers, Session = route_client_and_db
    with Session() as db:
        product = db.query(Product).filter(Product.sku == "CF-PG19").one()
        specs = db.query(ProductSpecs).filter(ProductSpecs.product_id == product.id).one()
        specs.size_info = json.dumps(
            [
                {"label": "展开尺寸", "value": "32 x 32 x 3.9", "unit": "cm"},
                {"label": "包装尺寸", "value": "35 x 35 x 6", "unit": "cm"},
            ],
            ensure_ascii=False,
        )
        db.commit()

    payload = client.post(
        "/api/customer-service/ask?debug=true",
        json={"question": "瓦片烤盘多大尺寸？"},
        headers=headers,
    ).json()

    metadata = payload.get("answer_metadata") or {}
    contract = (payload.get("debug") or {}).get("entity_resolution_contract") or {}
    assert payload.get("answer_type") == "product_detail", payload
    assert contract.get("matched_by") == "canonical_name_exact", contract
    assert contract.get("resolved_sku") == "CF-PG19", contract
    assert contract.get("field_type") == "dimensions", contract
    assert payload.get("candidate_skus") == ["CF-PG19"], payload
    assert payload.get("result_skus") == ["CF-PG19"], payload
    assert metadata.get("evidence_source") == "specs.size_info", metadata
    assert metadata.get("evidence_scope") == "subject", metadata
    assert metadata.get("evidence_sku") == "CF-PG19", metadata
    assert metadata.get("evidence_label") == "展开尺寸", metadata
    assert metadata.get("evidence_unit") == "cm", metadata
    assert metadata.get("evidence_subtype") == "expanded", metadata
    assert metadata.get("dimension_generic_fallback") is True, metadata
    assert "32 x 32 x 3.9" in str(payload.get("answer") or ""), payload
    assert "展开尺寸" in str(payload.get("answer") or ""), payload
    assert "cm" in str(payload.get("answer") or ""), payload
    assert "未单独" in str(payload.get("answer") or ""), payload
    assert "35 x 35 x 6" not in str(payload.get("answer") or ""), payload


def test_dimensions_predicate_keeps_pro_identity_and_evidence_isolated(route_client_and_db):
    client, headers, Session = route_client_and_db
    with Session() as db:
        product = db.query(Product).filter(Product.sku == "CF-PG19PRO").first()
        if product is None:
            _add_product(
                db,
                "CF-PG19PRO",
                "瓦片烤盘Pro",
                "锅具",
                "9英寸",
                "铝合金",
                "燃气炉",
                "Pro烤盘",
                "露营煎烤",
                820,
            )
            db.flush()
            product = db.query(Product).filter(Product.sku == "CF-PG19PRO").one()
        specs = db.query(ProductSpecs).filter(ProductSpecs.product_id == product.id).one()
        specs.size_info = json.dumps(
            [{"label": "展开尺寸", "value": "36 x 36 x 4.2", "unit": "cm"}],
            ensure_ascii=False,
        )
        db.commit()

    payload = client.post(
        "/api/customer-service/ask?debug=true",
        json={"question": "瓦片烤盘Pro多大尺寸？"},
        headers=headers,
    ).json()

    metadata = payload.get("answer_metadata") or {}
    contract = (payload.get("debug") or {}).get("entity_resolution_contract") or {}
    assert contract.get("matched_by") == "canonical_name_exact", contract
    assert contract.get("resolved_sku") == "CF-PG19PRO", contract
    assert payload.get("candidate_skus") == ["CF-PG19PRO"], payload
    assert payload.get("result_skus") == ["CF-PG19PRO"], payload
    assert metadata.get("evidence_sku") == "CF-PG19PRO", metadata
    assert "36 x 36 x 4.2" in str(payload.get("answer") or ""), payload
    assert "CF-PG19" not in payload.get("result_skus", []), payload


@pytest.mark.parametrize(
    "question",
    [
        "瓦片盘多大尺寸？",
        "不存在的烤盘多大尺寸？",
        "烤盘一般多大尺寸？",
    ],
)
def test_dimensions_predicate_weak_unresolved_or_generic_subject_stays_safe(
    route_client_and_db,
    question,
):
    client, headers, _ = route_client_and_db
    payload = client.post(
        "/api/customer-service/ask?debug=true",
        json={"question": question},
        headers=headers,
    ).json()

    assert payload.get("candidate_skus") == [], payload
    assert payload.get("result_skus") == [], payload
    assert payload.get("answer_type") in {"clarification", "product_detail"}, payload


@pytest.mark.parametrize(
    "question",
    [
        "瓦片盘支持哪些炉子？",
        "不存在的烤盘支持哪些炉子？",
        "瓦片盘可以放电磁炉上吗？",
        "不存在的烤盘可以放电磁炉上吗？",
    ],
)
def test_heat_source_predicate_unresolved_entities_do_not_become_catalog_results(
    route_client_and_db,
    question,
):
    client, headers, _ = route_client_and_db
    payload = client.post(
        "/api/customer-service/ask?debug=true",
        json={"question": question},
        headers=headers,
    ).json()

    assert payload.get("answer_type") == "clarification", payload
    assert payload.get("result_skus") == [], payload
    assert (payload.get("debug") or {}).get("agent_mode") != "structured_griddle_stove_query", payload


@pytest.mark.parametrize(
    "question",
    [
        "哪些烤盘支持卡式炉？",
        "有哪些适合卡式炉的烤盘？",
        "哪些烤盘可以放电磁炉上？",
        "有哪些烤盘能用卡式炉？",
    ],
)
def test_heat_source_category_filter_preserves_product_category_role(route_client_and_db, question):
    client, headers, Session = route_client_and_db
    with Session() as db:
        _add_product(
            db,
            "GRIDDLE-CANISTER-1",
            "多热源适配测试烤盘",
            "锅具",
            "9英寸",
            "铝合金",
            "卡式炉、电磁炉、明火",
            "烤盘 煎烤盘",
            "露营煎烤",
            680,
        )
        db.commit()

    payload = client.post(
        "/api/customer-service/ask?debug=true",
        json={"question": question},
        headers=headers,
    ).json()

    metadata = payload.get("answer_metadata") or {}
    rows = payload.get("results") or []
    assert payload.get("answer_type") == "product_query", payload
    assert metadata.get("product_ref") == "烤盘", payload
    assert rows, payload
    assert all(str(row.get("category") or "") != "炉具" for row in rows), rows
    assert all("烤盘" in " ".join(str(row.get(key) or "") for key in ("product_name_cn", "sub_category", "features")) for row in rows), rows
    assert "GRIDDLE-CANISTER-1" in payload.get("result_skus", []), payload
    assert "STV-001" not in payload.get("result_skus", []), payload


def test_structured_target_category_distinguishes_product_category_from_heat_source_value():
    assert customer_service_service._structured_target_category_from_question("哪些烤盘支持卡式炉？") == "烤盘"
    assert customer_service_service._structured_target_category_from_question("有哪些适合卡式炉的烤盘？") == "烤盘"
    assert customer_service_service._structured_target_category_from_question("推荐几款能用电磁炉的烤盘") == "烤盘"
    assert customer_service_service._structured_target_category_from_question("哪些炉具适合烤盘？") == "炉具"

    recommendation_contract = customer_service_service._structured_hard_filter_contract("推荐几款能用电磁炉的烤盘")
    assert recommendation_contract.get("product_ref") == "烤盘", recommendation_contract
    assert recommendation_contract.get("filters", {}).get("product.category") == "烤盘", recommendation_contract
    assert recommendation_contract.get("filters", {}).get("specs.heat_source") == "电磁炉", recommendation_contract


def test_structured_evidence_precedes_qa_for_selling_point_and_preserves_usage_route(route_client_and_db):
    client, headers, Session = route_client_and_db
    with Session() as db:
        _add_product_qa(
            db,
            "CF-PG19",
            "瓦片烤盘有什么核心卖点？",
            "瓦片烤盘的核心卖点是轻便易携带。",
            tags="卖点",
            priority=300,
        )
        _add_product_qa(
            db,
            "CF-PG19",
            "瓦片烤盘怎么使用？",
            "使用前先清洁并擦干烤盘。",
            tags="使用,保养",
            priority=300,
        )
        db.commit()

    selling_point = client.post(
        "/api/customer-service/ask?debug=true",
        json={"question": "瓦片烤盘有什么特点？"},
        headers=headers,
    ).json()
    usage = client.post(
        "/api/customer-service/ask?debug=true",
        json={"question": "瓦片烤盘怎么使用？"},
        headers=headers,
    ).json()

    assert "核心卖点" in str(selling_point.get("answer") or ""), selling_point
    selling_debug = selling_point.get("debug") or {}
    selling_contract = selling_debug.get("entity_resolution_contract") or {}
    selling_metadata = selling_point.get("answer_metadata") or {}
    assert selling_debug.get("agent_mode") == "resolved_entity_detail_contract", selling_point
    assert selling_contract.get("resolved_sku") == "CF-PG19", selling_point
    assert selling_contract.get("field_type") == "selling_point", selling_point
    assert selling_point.get("result_skus") == ["CF-PG19"], selling_point
    assert selling_metadata.get("contract_field_type") == "selling_point", selling_point
    # Field-stage evidence policy is structured-column first. Same-SKU QA
    # remains a fallback only when the formal business column is absent or
    # invalid, so it cannot displace product_business.top_selling_points.
    assert selling_metadata.get("evidence_source") == "business.top_selling_points", selling_point
    assert "清洁" in str(usage.get("answer") or ""), usage
    assert "核心卖点" not in str(usage.get("answer") or ""), usage


def test_shipping_signal_does_not_disable_real_weather_or_selling_point_routes(route_client_and_db):
    client, headers, Session = route_client_and_db
    with Session() as db:
        _add_product_qa(
            db,
            "CF-PG19",
            "瓦片烤盘有什么卖点？",
            "瓦片烤盘的卖点是轻便易携带。",
            tags="卖点",
        )
        db.commit()

    weather = client.post(
        "/api/customer-service/ask?debug=true",
        json={"question": "今天适合露营吗？"},
        headers=headers,
    ).json()
    selling_point = client.post(
        "/api/customer-service/ask?debug=true",
        json={"question": "瓦片烤盘有什么卖点？"},
        headers=headers,
    ).json()

    assert "天气" in str(weather.get("answer") or ""), weather
    assert weather.get("result_skus") in ([], None), weather
    selling_debug = selling_point.get("debug") or {}
    selling_contract = selling_debug.get("entity_resolution_contract") or {}
    selling_metadata = selling_point.get("answer_metadata") or {}
    assert selling_debug.get("agent_mode") == "resolved_entity_detail_contract", selling_point
    assert selling_contract.get("resolved_sku") == "CF-PG19", selling_point
    assert selling_contract.get("field_type") == "selling_point", selling_point
    assert selling_point.get("result_skus") == ["CF-PG19"], selling_point
    assert selling_metadata.get("contract_field_type") == "selling_point", selling_point
    assert selling_metadata.get("evidence_source") == "business.top_selling_points", selling_point


def test_clarification_result_isolation_keeps_resolver_candidates_out_of_confirmed_results(
    route_client_and_db,
):
    client, headers, _ = route_client_and_db
    response = client.post(
        "/api/customer-service/ask?debug=true",
        json={"question": "天鹅壶白色多少钱？"},
        headers=headers,
    )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload.get("answer_type") == "clarification", payload
    assert payload.get("result_skus") in ([], None), payload
    assert not any(str(sku).endswith("-黑") for sku in (payload.get("result_skus") or [])), payload
    assert "黑色" not in str(payload.get("answer") or ""), payload


def test_temporal_modifier_does_not_pollute_exact_product_scene_subject(route_client_and_db):
    client, headers, Session = route_client_and_db
    with Session() as db:
        kettle = db.query(Product).filter(Product.sku == "KW-K32-白").one()
        kettle.product_name_cn = "天鹅壶9杯白"
        db.commit()

    payload = client.post(
        "/api/customer-service/ask?debug=true",
        json={"question": "天鹅壶9杯白今天适合露营吗？"},
        headers=headers,
    ).json()

    assert payload.get("answer_type") == "product_detail", payload
    assert payload.get("result_skus") == ["KW-K32-白"], payload
    assert (payload.get("debug") or {}).get("agent_mode") != "entity_scope_product_not_found", payload
    assert "没有找到“天鹅壶9杯白今天”" not in str(payload.get("answer") or ""), payload
    assert "露营" in str(payload.get("answer") or ""), payload
    metadata = payload.get("answer_metadata") or {}
    assert metadata.get("evidence_field") == "usage_scene", payload
    assert metadata.get("evidence_source") == "business.usage_scenarios", payload
    assert metadata.get("evidence_sku") == "KW-K32-白", payload
    entity_contract = (payload.get("debug") or {}).get("entity_resolution_contract") or {}
    assert entity_contract.get("status") == "resolved", payload
    assert entity_contract.get("resolved_sku") == "KW-K32-白", payload
    assert entity_contract.get("matched_by") == "canonical_name_exact", payload
    assert entity_contract.get("field_type") == "usage_scene", payload


def test_exact_product_manual_missing_keeps_identity_before_unknown_field_guard(route_client_and_db):
    client, headers, _ = route_client_and_db
    payload = client.post(
        "/api/customer-service/ask?debug=true",
        json={"question": "瓦片烤盘有没有说明书？"},
        headers=headers,
    ).json()

    metadata = payload.get("answer_metadata") or {}
    entity_contract = (payload.get("debug") or {}).get("entity_resolution_contract") or {}
    assert payload.get("result_skus") == ["CF-PG19"], payload
    assert payload.get("candidate_skus") == ["CF-PG19"], payload
    assert entity_contract.get("status") == "resolved", payload
    assert entity_contract.get("resolved_sku") == "CF-PG19", payload
    assert entity_contract.get("matched_by") == "canonical_name_exact", payload
    assert metadata.get("field_evidence_missing") is True, payload
    assert metadata.get("evidence_sku") is None, payload
    assert "瓦片烤盘（CF-PG19）" in str(payload.get("answer") or ""), payload
    assert "说明书" in str(payload.get("answer") or ""), payload
    assert "【烤盘】" not in str(payload.get("answer") or ""), payload
    assert "http" not in str(payload.get("answer") or "").lower(), payload


def test_exact_product_manual_uses_only_same_sku_official_document(route_client_and_db):
    client, headers, Session = route_client_and_db
    with Session() as db:
        _add_knowledge_chunk(
            db,
            chunk_id="cf-pg19-official-manual",
            sku="CF-PG19",
            title="瓦片烤盘官方说明书",
            content="官方说明书正文",
            source_type="manual",
        )
        db.commit()

    payload = client.post(
        "/api/customer-service/ask?debug=true",
        json={"question": "瓦片烤盘有没有说明书？"},
        headers=headers,
    ).json()

    metadata = payload.get("answer_metadata") or {}
    assert payload.get("result_skus") == ["CF-PG19"], payload
    assert metadata.get("evidence_field") == "manual", payload
    assert metadata.get("evidence_source") == "knowledge_documents.manual", payload
    assert metadata.get("evidence_sku") == "CF-PG19", payload
    assert metadata.get("field_evidence_match") is True, payload
    assert "cf-pg19-official-manual.md" in str(payload.get("answer") or ""), payload


def test_exact_product_after_sales_phone_missing_keeps_identity_and_never_invents_number(route_client_and_db):
    client, headers, _ = route_client_and_db
    payload = client.post(
        "/api/customer-service/ask?debug=true",
        json={"question": "瓦片烤盘售后电话是多少？"},
        headers=headers,
    ).json()
    entity = (payload.get("debug") or {}).get("entity_resolution_contract") or {}
    assert entity.get("resolved_sku") == "CF-PG19", payload
    assert payload.get("result_skus") == ["CF-PG19"], payload
    assert (payload.get("answer_metadata") or {}).get("field_evidence_missing") is True, payload
    assert "未维护" in str(payload.get("answer") or ""), payload
    assert not re.search(r"(?<![A-Z0-9-])(?:400|800|1\d{10}|0\d{2,3}[- ]?\d{7,8})(?![A-Z0-9-])", str(payload.get("answer") or "")), payload


def test_realtime_price_temporal_modifier_keeps_exact_variant_identity(route_client_and_db):
    client, headers, Session = route_client_and_db
    with Session() as db:
        product = db.query(Product).filter(Product.sku == "KW-K32-白").one()
        product.product_name_cn = "天鹅壶9杯白"
        db.commit()
    payload = client.post(
        "/api/customer-service/ask?debug=true",
        json={"question": "天鹅壶9杯白现在多少钱？"},
        headers=headers,
    ).json()
    entity = (payload.get("debug") or {}).get("entity_resolution_contract") or {}
    assert entity.get("resolved_sku") == "KW-K32-白", payload
    assert payload.get("result_skus") == ["KW-K32-白"], payload
    # Price is a safely unsupported realtime field.  Keep the exact-variant
    # binding and no-fabrication boundary without freezing one missing-value
    # formatter wording.
    answer = str(payload.get("answer") or "")
    assert "价格" in answer, payload
    assert any(term in answer for term in ("实时价格", "未标注", "暂未找到")), payload
    assert "当前售价：" not in answer, payload
    assert "KW-K32-黑" not in answer, payload


def test_realtime_inventory_predicate_keeps_exact_identity_without_inventing_stock(route_client_and_db):
    client, headers, _ = route_client_and_db
    payload = client.post(
        "/api/customer-service/ask?debug=true",
        json={"question": "瓦片烤盘当前有现货吗？"},
        headers=headers,
    ).json()
    entity = (payload.get("debug") or {}).get("entity_resolution_contract") or {}
    assert entity.get("resolved_sku") == "CF-PG19", payload
    assert payload.get("result_skus") == ["CF-PG19"], payload
    assert (payload.get("answer_metadata") or {}).get("field_evidence_missing") is True, payload
    answer = str(payload.get("answer") or "")
    assert "不能" in answer and "实时库存" in answer, payload
    assert not re.search(r"(?:现货充足|库存充足|剩余\s*\d+|还有\s*\d+\s*件)", answer), payload


def test_delivery_temporal_predicate_keeps_exact_variant_identity(route_client_and_db):
    client, headers, Session = route_client_and_db
    with Session() as db:
        product = db.query(Product).filter(Product.sku == "KW-K31-白").one()
        product.product_name_cn = "天鹅壶4杯白"
        db.commit()
    payload = client.post(
        "/api/customer-service/ask?debug=true",
        json={"question": "天鹅壶4杯白本周能送到吗？"},
        headers=headers,
    ).json()
    entity = (payload.get("debug") or {}).get("entity_resolution_contract") or {}
    assert entity.get("status") == "resolved", payload
    assert entity.get("resolved_sku") == "KW-K31-白", payload
    assert payload.get("result_skus") == ["KW-K31-白"], payload
    assert "KW-K31-黑" not in (payload.get("candidate_skus") or []), payload
    answer = str(payload.get("answer") or "")
    assert not any(token in answer for token in ("明天送到", "三天内送到", "本周一定能到")), answer


def test_weight_self_modifier_keeps_exact_variant_identity(route_client_and_db):
    client, headers, Session = route_client_and_db
    with Session() as db:
        product = db.query(Product).filter(Product.sku == "KW-K31-白").one()
        product.product_name_cn = "天鹅壶4杯白"
        db.commit()
    payload = client.post(
        "/api/customer-service/ask?debug=true",
        json={"question": "天鹅壶4杯白自身有多重？"},
        headers=headers,
    ).json()
    entity = (payload.get("debug") or {}).get("entity_resolution_contract") or {}
    assert entity.get("resolved_sku") == "KW-K31-白", payload
    assert entity.get("field_type") == "weight", payload
    assert payload.get("result_skus") == ["KW-K31-白"], payload


def test_manual_view_phrase_keeps_exact_product_identity(route_client_and_db):
    client, headers, _ = route_client_and_db
    payload = client.post(
        "/api/customer-service/ask?debug=true",
        json={"question": "瓦片烤盘怎么查看产品手册？"},
        headers=headers,
    ).json()
    entity = (payload.get("debug") or {}).get("entity_resolution_contract") or {}
    assert entity.get("resolved_sku") == "CF-PG19", payload
    assert entity.get("field_type") == "manual", payload
    assert payload.get("result_skus") == ["CF-PG19"], payload
    assert (payload.get("answer_metadata") or {}).get("field_evidence_missing") is True, payload


def test_after_sales_contact_phrase_keeps_exact_product_identity(route_client_and_db):
    client, headers, _ = route_client_and_db
    payload = client.post(
        "/api/customer-service/ask?debug=true",
        json={"question": "瓦片烤盘的客服联系方式是什么？"},
        headers=headers,
    ).json()
    entity = (payload.get("debug") or {}).get("entity_resolution_contract") or {}
    assert entity.get("resolved_sku") == "CF-PG19", payload
    assert entity.get("field_type") == "after_sales_contact", payload
    assert payload.get("result_skus") == ["CF-PG19"], payload
    assert (payload.get("answer_metadata") or {}).get("field_evidence_missing") is True, payload


def test_current_price_phrase_keeps_exact_variant_identity(route_client_and_db):
    client, headers, Session = route_client_and_db
    with Session() as db:
        product = db.query(Product).filter(Product.sku == "KW-K32-黑").one()
        product.product_name_cn = "天鹅壶9杯黑"
        db.commit()
    payload = client.post(
        "/api/customer-service/ask?debug=true",
        json={"question": "天鹅壶9杯黑当前售价是多少？"},
        headers=headers,
    ).json()
    entity = (payload.get("debug") or {}).get("entity_resolution_contract") or {}
    assert entity.get("resolved_sku") == "KW-K32-黑", payload
    assert entity.get("field_type") == "price", payload
    assert payload.get("result_skus") == ["KW-K32-黑"], payload
    assert (payload.get("answer_metadata") or {}).get("field_evidence_missing") is True, payload


def test_current_inventory_phrase_keeps_exact_pro_identity(route_client_and_db):
    client, headers, Session = route_client_and_db
    with Session() as db:
        if db.query(Product).filter(Product.sku == "CF-PG19PRO").first() is None:
            _add_product(
                db,
                "CF-PG19PRO",
                "瓦片烤盘Pro",
                "锅具",
                "9英寸",
                "铝合金",
                "燃气炉",
                "Pro烤盘",
                "露营煎烤",
                820,
            )
            db.commit()
    payload = client.post(
        "/api/customer-service/ask?debug=true",
        json={"question": "瓦片烤盘Pro当前还有库存吗？"},
        headers=headers,
    ).json()
    entity = (payload.get("debug") or {}).get("entity_resolution_contract") or {}
    assert entity.get("resolved_sku") == "CF-PG19PRO", payload
    assert entity.get("field_type") == "inventory", payload
    assert payload.get("result_skus") == ["CF-PG19PRO"], payload
    assert (payload.get("answer_metadata") or {}).get("field_evidence_missing") is True, payload


def test_manual_yes_no_phrase_keeps_exact_variant_identity(route_client_and_db):
    client, headers, Session = route_client_and_db
    with Session() as db:
        product = db.query(Product).filter(Product.sku == "KW-K32-黑").one()
        product.product_name_cn = "天鹅壶9杯黑"
        db.commit()
    payload = client.post(
        "/api/customer-service/ask?debug=true",
        json={"question": "天鹅壶9杯黑有没有用户手册？"},
        headers=headers,
    ).json()
    entity = (payload.get("debug") or {}).get("entity_resolution_contract") or {}
    assert entity.get("resolved_sku") == "KW-K32-黑", payload
    assert entity.get("field_type") == "manual", payload
    assert payload.get("result_skus") == ["KW-K32-黑"], payload
    assert (payload.get("answer_metadata") or {}).get("field_evidence_missing") is True, payload


def test_manual_shorthand_variant_ambiguity_precedes_unknown_field_guard(route_client_and_db):
    client, headers, Session = route_client_and_db
    with Session() as db:
        for sku, name in (("KW-K32-白", "天鹅壶9杯白"), ("KW-K32-黑", "天鹅壶9杯黑")):
            product = db.query(Product).filter(Product.sku == sku).one()
            product.product_name_cn = name
        db.commit()
    payload = client.post(
        "/api/customer-service/ask?debug=true",
        json={"question": "天鹅9杯有说明书吗？"},
        headers=headers,
    ).json()
    entity = (payload.get("debug") or {}).get("entity_resolution_contract") or {}
    assert entity.get("status") == "ambiguous", payload
    assert set(payload.get("candidate_skus") or []) == {"KW-K32-白", "KW-K32-黑"}, payload
    assert payload.get("result_skus") == [], payload
    assert (payload.get("debug") or {}).get("agent_mode") == "named_product_unknown_field_clarification", payload


def test_exact_product_pronoun_dimension_followup_uses_active_anchor(route_client_and_db):
    client, headers, _ = route_client_and_db
    first = client.post(
        "/api/customer-service/ask?debug=true",
        json={"question": "瓦片烤盘是什么材质？"},
        headers=headers,
    ).json()
    assert first.get("result_skus") == ["CF-PG19"], first
    second = client.post(
        "/api/customer-service/ask?debug=true",
        json={"question": "它多大尺寸？", "conversation_id": first.get("conversation_id")},
        headers=headers,
    ).json()
    assert second.get("result_skus") == ["CF-PG19"], second
    assert (second.get("debug") or {}).get("active_single_product_anchor") == "CF-PG19", second
    second_debug = second.get("debug") or {}
    second_field = second_debug.get("field_contract") or {}
    second_entity = second_debug.get("entity_resolution_contract") or {}
    assert second_field.get("field_type") == "dimensions", second
    assert second_entity.get("status") == "resolved", second
    assert second_entity.get("resolved_sku") == "CF-PG19", second
    assert second_entity.get("field_type") == "dimensions", second
    assert second_debug.get("binding_provenance") == "resolved_entity_contract", second
    metadata = second.get("answer_metadata") or {}
    assert metadata.get("evidence_sku") in {None, "CF-PG19"}, second
    assert metadata.get("contract_field_type") == "dimensions", second


def test_ambiguous_variant_color_followup_resolves_with_existing_strong_contract(route_client_and_db):
    client, headers, Session = route_client_and_db
    with Session() as db:
        for sku, name in (("KW-K32-白", "天鹅壶9杯白"), ("KW-K32-黑", "天鹅壶9杯黑")):
            product = db.query(Product).filter(Product.sku == sku).one()
            product.product_name_cn = name
        db.commit()
    first = client.post(
        "/api/customer-service/ask?debug=true",
        json={"question": "天鹅壶9杯是什么材质？"},
        headers=headers,
    ).json()
    assert first.get("result_skus") == [], first
    assert set(first.get("candidate_skus") or []) == {"KW-K32-白", "KW-K32-黑"}, first
    second = client.post(
        "/api/customer-service/ask?debug=true",
        json={"question": "白色", "conversation_id": first.get("conversation_id")},
        headers=headers,
    ).json()
    entity = (second.get("debug") or {}).get("entity_resolution_contract") or {}
    assert entity.get("status") == "resolved", second
    assert entity.get("resolved_sku") == "KW-K32-白", second
    assert entity.get("matched_by") in {"canonical_name_exact", "normalized_alias_exact"}, second
    assert second.get("result_skus") == ["KW-K32-白"], second


def test_recommendation_explicit_griddle_scope_excludes_unrelated_categories(route_client_and_db):
    client, headers, _ = route_client_and_db
    payload = client.post(
        "/api/customer-service/ask?debug=true",
        json={"question": "推荐一款适合露营的烤盘。"},
        headers=headers,
    ).json()
    assert payload.get("answer_type") == "recommendation", payload
    assert payload.get("result_skus"), payload
    for row in payload.get("results") or []:
        haystack = " ".join(
            str(row.get(key) or "")
            for key in ("product_name_cn", "product_name_en", "category", "capacity", "features")
        )
        assert any(term in haystack.lower() for term in ("烤盘", "煎盘", "griddle")), row


def test_context_anchor_survives_empty_comparison_result(route_client_and_db):
    client, headers, _ = route_client_and_db
    questions = (
        "推荐一个适合一个人徒步用的锅。",
        "第一个多重？",
        "它能用酒精炉吗？",
        "有没有更便宜的？",
        "刚才那个保修多久？",
    )
    payloads = []
    conversation_id = None
    for question in questions:
        body = {"question": question}
        if conversation_id:
            body["conversation_id"] = conversation_id
        response = client.post("/api/customer-service/ask?debug=true", json=body, headers=headers)
        assert response.status_code == 200, response.text
        payload = response.json()
        payloads.append(payload)
        conversation_id = payload["conversation_id"]

    selected_sku = payloads[1]["result_skus"][0]
    assert payloads[2].get("result_skus") == [selected_sku], payloads[2]
    assert payloads[4].get("answer_type") == "product_detail", payloads[4]
    assert payloads[4].get("result_skus") == [selected_sku], payloads[4]
    assert selected_sku in str(payloads[4].get("answer") or ""), payloads[4]
    assert (payloads[4].get("debug") or {}).get("agent_mode") != "structured_unknown_field_guard", payloads[4]


def test_scope_field_composition_resolves_exact_subject_material(route_client_and_db):
    client, headers, _ = route_client_and_db
    response = client.post(
        "/api/customer-service/ask?debug=true",
        json={"question": "瓦片烤盘主体是什么材质？"},
        headers=headers,
    )

    assert response.status_code == 200, response.text
    payload = response.json()
    contract = (payload.get("debug") or {}).get("entity_resolution_contract") or {}
    assert payload.get("answer_type") == "product_detail", payload
    assert payload.get("result_skus") == ["CF-PG19"], payload
    assert contract.get("matched_by") == "canonical_name_exact", contract
    assert contract.get("field_type") == "material", contract
    assert "铝合金" in str(payload.get("answer") or ""), payload


@pytest.mark.parametrize(
    "question",
    [
        "悠然杯Pro对应的产品编码是哪一个？",
        "瓦片烤盘Pro随单会送赠品吗？",
        "灵巧包自身的长宽高怎么标注的？",
        "鸣泉壶大概能装多少水？",
        "小青炉系列收纳尺寸分别是多少？",
    ],
)
def test_weak_entity_contract_is_never_promoted_to_single_product_answer(
    route_client_and_db,
    question,
):
    client, headers, Session = route_client_and_db
    with Session() as db:
        products = db.query(Product).order_by(Product.sku.asc()).all()
        contract = customer_entity_resolution_contract.build_entity_resolution_contract(question, products)
    assert contract.status != "resolved", contract.to_dict()

    response = client.post("/api/customer-service/ask?debug=true", json={"question": question}, headers=headers)
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload.get("result_skus") in ([], None), payload
    assert payload.get("candidate_skus") in ([], None), payload
    assert (payload.get("answer_metadata") or {}).get("source") != "resolved_entity_unknown_field_fallback", payload


def test_exact_canonical_name_with_gift_scaffolding_keeps_identity_and_safe_missing(route_client_and_db):
    """Predicate scaffolding must not weaken a unique raw canonical product name."""
    client, headers, _ = route_client_and_db
    response = client.post(
        "/api/customer-service/ask?debug=true",
        json={"question": "聚能环水壶有没有随箱赠品记录？"},
        headers=headers,
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    debug = payload.get("debug") or {}
    entity = debug.get("entity_resolution_contract") or {}
    field = debug.get("field_contract") or {}

    assert field.get("field_type") == "gift", payload
    assert entity.get("status") == "resolved", payload
    assert entity.get("resolved_sku") == "CB253", payload
    assert entity.get("matched_by") == "canonical_name_exact", payload
    assert payload.get("candidate_skus") == ["CB253"], payload
    assert payload.get("result_skus") == ["CB253"], payload
    assert (payload.get("answer_metadata") or {}).get("evidence_sku") in (None, "CB253"), payload
    assert "当前资料" in str(payload.get("answer") or ""), payload


def test_component_scope_material_predicate_preserves_exact_product_identity(route_client_and_db):
    """An exact product name stays exact when a component scope precedes the field."""
    client, headers, _ = route_client_and_db
    payload = client.post(
        "/api/customer-service/ask?debug=true",
        json={"question": "炊墨炒锅的锅体用的是什么材质？"},
        headers=headers,
    ).json()

    entity = (payload.get("debug") or {}).get("entity_resolution_contract") or {}
    assert entity.get("status") == "resolved", payload
    assert entity.get("resolved_sku") == "CW-C83-1", payload
    assert entity.get("field_type") == "material", payload
    assert payload.get("result_skus") == ["CW-C83-1"], payload


def test_semantic_context_handles_resolve_against_server_owned_result_order():
    assert customer_service_service._semantic_context_result_skus(
        {"context_result_indexes": [2, 1]},
        ["CW-C69-1", "CW-C06PRO"],
    ) == ["CW-C06PRO", "CW-C69-1"]
    assert customer_service_service._semantic_context_result_skus(
        {"context_result_indexes": [1, 1]},
        ["CW-C69-1", "CW-C06PRO"],
    ) == []


def test_product_bound_semantic_context_index_is_an_identity_anchor():
    result = {
        "route_family": "product_bound_qa",
        "canonical_fields": ["product_name_cn", "sku"],
        "context_result_indexes": [1],
    }
    assert not customer_agent_planner_service._semantic_product_bound_requires_entity_anchor(
        result,
        question="这个的容量是多少？",
        context={},
    )
