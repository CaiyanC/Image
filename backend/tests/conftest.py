import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool


BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))


from app.core.database import Base, get_db  # noqa: E402
from app.core.permission_constants import MANAGEMENT_GROUP_NAME  # noqa: E402
from app.core.security import create_access_token  # noqa: E402
from app.main import app  # noqa: E402
from app.models import (  # noqa: E402
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


def _customer_service_test_tables():
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


@pytest.fixture()
def route_client_and_db(monkeypatch):
    """Small shared API fixture retained after deleting the legacy route suite."""
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine, tables=_customer_service_test_tables())
    Session = sessionmaker(bind=engine, expire_on_commit=False)

    with Session() as db:
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
        db.add(
            Group(
                id="customer-service-route-management",
                group_name=MANAGEMENT_GROUP_NAME,
                description="management",
            )
        )
        db.add(
            UserGroup(
                user_id="customer-service-route-user",
                group_id="customer-service-route-management",
                group_role="admin",
            )
        )
        db.commit()

    def override_db():
        session = Session()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_db] = override_db

    from app.api import customer_service as customer_service_api

    monkeypatch.setattr(customer_service_api, "enforce_rate_limit", lambda **kwargs: None)
    monkeypatch.setattr(
        customer_service_api.operation_log_service,
        "log_operation",
        lambda *args, **kwargs: None,
    )

    token = create_access_token({"sub": "customer-service-route-user"})
    headers = {"Authorization": f"Bearer {token}"}

    try:
        with TestClient(app) as test_client:
            yield test_client, headers, Session
    finally:
        app.dependency_overrides.clear()
        engine.dispose()
