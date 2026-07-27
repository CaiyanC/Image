from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ..core.database import get_db
from ..core.security import get_current_user, get_user_permissions
from ..models.user import User
from ..schemas.tool import ToolResponse
from ..services import tool_registry_service


router = APIRouter(prefix="/api/tools", tags=["tools"])


@router.get("", response_model=list[ToolResponse])
def list_available_tools(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    permissions = get_user_permissions(db, current_user.id)
    return tool_registry_service.list_visible_tools(db, permissions)
