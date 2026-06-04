"""Routes and permission-route M2M table."""
import uuid
from datetime import datetime, timezone
from sqlalchemy import String, DateTime, ForeignKey, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from ..core.database import Base


class Route(Base):
    __tablename__ = "routes"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    route_path: Mapped[str] = mapped_column(String(255), nullable=False)
    route_name: Mapped[str] = mapped_column(String(100), nullable=True)
    parent_id: Mapped[str] = mapped_column(String(36), nullable=True)
    route_type: Mapped[str] = mapped_column(String(50), nullable=True)
    component_path: Mapped[str] = mapped_column(String(255), nullable=True)
    description: Mapped[str] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))


class PermissionRoute(Base):
    __tablename__ = "permission_routes"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    permission_id: Mapped[str] = mapped_column(String(36), ForeignKey("permissions.id", ondelete="CASCADE"), nullable=False)
    route_id: Mapped[str] = mapped_column(String(36), ForeignKey("routes.id", ondelete="CASCADE"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))
    __table_args__ = (UniqueConstraint("permission_id", "route_id", name="uq_permission_route"),)
