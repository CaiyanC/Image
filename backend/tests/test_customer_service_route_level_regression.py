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
    product.barcode = f"barcode-{sku}"
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
        ("KD04SS适合露营用吗？", "KD04SS", ""),
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

    turn3 = client.post(
        "/api/customer-service/ask?debug=true",
        json={"question": "有没有更便宜一点的替代？", "conversation_id": conversation_id},
        headers=headers,
    )
    assert turn3.status_code == 200, turn3.text
    payload3 = turn3.json()
    assert payload3["answer_type"] != "knowledge_base_answer"
    assert payload3["result_skus"]
    assert "上一轮在这些候选中已经没有筛到" not in payload3["answer"]


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
