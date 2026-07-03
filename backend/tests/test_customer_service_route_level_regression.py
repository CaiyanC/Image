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
    product = Product(
        id=f"route-{sku}",
        sku=sku,
        barcode=f"barcode-{sku}",
        product_name_cn=name,
        product_name_en=name,
        brand="alocs爱路客",
        category=category,
        sub_category=sub_category,
        product_level="A类品",
        lifecycle_status="常规品",
        person_in_charge="RouteTest",
    )
    db.add(product)
    db.add(
        ProductSpecs(
            id=f"route-specs-{sku}",
            product_id=product.id,
            capacity=capacity,
            gross_weight_g=weight,
            body_material=material,
            color="本色",
            surface_finish="硬质氧化",
            heat_source=heat_source,
            power="/",
            technical_advantages=features,
        )
    )
    db.add(
        ProductBusiness(
            id=f"route-biz-{sku}",
            product_id=product.id,
            top_selling_points=features,
            target_audience="户外用户",
            positioning=features,
            price_positioning=price_positioning,
            usage_scenarios=scenarios,
        )
    )
    db.add(
        ProductContent(
            id=f"route-content-{sku}",
            product_id=product.id,
            title_cn=name,
            long_description_cn=f"{name} {features} {scenarios}",
            search_keywords=f"{name},{category},{heat_source}",
        )
    )


def _seed_route_level_products(db):
    _add_product(db, "ACC-001", "稳稳水袋", "配件", "/", "TPU", "/", "配件收纳补水", "露营收纳", 80)
    _add_product(db, "ACC-CUT-1", "勺叉收纳包", "配件", "/", "牛津布", "/", "勺叉筷集中收纳", "露营用餐收纳", 60)
    _add_product(db, "CS-G26HM", "湖美林丰X-Power桌面炉（不含炉配件-烤盘）", "炉具", "/", "不锈钢", "气罐", "桌面炉 露营烧烤", "桌面聚餐", 2100)
    _add_product(db, "STV-001", "魔盒卡式炉", "炉具", "/", "不锈钢", "气罐", "炉具火力稳定", "露营烧烤", 2200)
    _add_product(db, "CUT-001", "便携式户外旅行筷", "餐具", "/", "不锈钢", "/", "轻量餐具", "露营用餐", 40)
    _add_product(db, "KTL-001", "悦享杯套装", "水具", "350ML", "304不锈钢", "/", "便携水具", "露营饮水", 180)
    _add_product(db, "KW-K32-黑", "天鹅壶9杯-黑色", "咖啡器具", "900ML", "不锈钢", "气炉", "手冲咖啡器具", "露营咖啡", 420)
    _add_product(db, "TBL-001", "疯狂游乐园泡泡桌-长桌", "桌椅", "/", "铝合金", "/", "折叠桌椅", "家庭露营", 1800)
    _add_product(db, "COF-001", "魔咖旅行咖啡研磨机", "咖啡器具", "/", "不锈钢", "/", "手冲咖啡器具", "露营咖啡", 260)
    _add_product(db, "TEA-001", "竹影茶具", "茶具", "/", "陶瓷", "/", "便携茶具", "露营泡茶", 380)
    _add_product(db, "OT-001", "湖美林丰天幕", "天幕、地垫、帐篷", "/", "春亚纺", "/", "防晒遮蔽", "家庭露营", 1600)

    _add_product(db, "CW-C83", "炊墨套锅", "锅具", "锅 3700ML", "硬质氧化铝合金", "燃气炉", "多人做饭 稳一点", "家庭露营 2-4人 火锅", 1200)
    _add_product(db, "CW-C83-1", "炊墨炒锅", "锅具", "锅 3700ML", "硬质氧化铝合金", "燃气炉", "大容量", "家庭露营 多人做饭", 1200)
    _add_product(db, "CW-C83-2", "炊墨煎锅", "锅具", "煎盘 2300ML", "硬质氧化铝合金", "燃气炉", "兼容多热源", "家庭露营 早餐煎烤", 980)
    _add_product(db, "CW-S10-1", "激川单锅", "锅具", "锅 1400ML", "硬质氧化铝合金、TRITIAN", "酒精炉, 气炉", "双人需求 不粘", "双人露营 轻量野餐 火锅", 300)
    _add_product(db, "CW-S10-A", "激川单锅", "锅具", "锅 1400ML", "硬质氧化铝合金、TRITIAN", "酒精炉, 气炉", "双人需求 不粘", "双人露营 轻量野餐 火锅", 300)
    _add_product(db, "CW-C01-37", "1－2人野营锅7件套", "锅具", "锅 900ML，碗 450ML", "硬质氧化铝合金", "酒精炉, 燃气炉", "轻量化套娃收纳", "双人露营 周末野餐", 595)
    _add_product(db, "TW-141", "烽宴多功能聚能套锅", "锅具", "锅 1600ML", "铝合金", "酒精炉, 燃气炉", "聚能结构 全套收纳", "轻量野餐 双人露营", 680)
    _add_product(db, "CW-C19T-37", "旅伴2-3人野餐锅5件套", "锅具", "2升锅", "硬质氧化铝", "燃气炉", "全套收纳便携", "双人露营 公园野餐", 1062)
    _add_product(db, "CW-C06PRO", "轻途套锅", "锅具", "大锅 3.0L，小锅 1.7L，水壶 0.8L", "3003铝合金、硅胶、不锈钢、PP", "酒精炉, 燃气炉", "极致轻量化 套娃式收纳", "轻量徒步 背包旅行 单人露营", 1150)
    _add_product(db, "CW-C69-1", "小方锅套装", "锅具", "大锅 1.7L，水壶 1.0L", "304不锈钢", "燃气炉", "方形设计 易收纳", "精致露营 户外小份烹饪", 1320)
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
