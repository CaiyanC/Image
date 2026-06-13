from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from typing import List
from datetime import date
from ..core.database import get_db
from ..core.permission_constants import MANAGEMENT_GROUP_NAME
from ..core.security import get_current_admin_user, get_user_groups, require_permission
from ..models.user import User
from ..schemas.generation import GenerationResponse, GenerationStats
from ..services import generation_service

router = APIRouter(prefix="/api/history", tags=["history"])


def _is_management(user: User, db: Session) -> bool:
    for g in get_user_groups(db, user.id):
        if g["group_name"] == MANAGEMENT_GROUP_NAME:
            return True
    return False


@router.get("", response_model=List[GenerationResponse])
def get_history(
    skip: int = 0,
    limit: int = 20,
    search: str = Query(None),
    date_from: date = Query(None),
    date_to: date = Query(None),
    current_user: User = Depends(require_permission("history.view")),
    db: Session = Depends(get_db),
):
    return generation_service.get_user_generations(
        db, current_user.id, skip, limit, search, date_from, date_to
    )


@router.get("/admin", response_model=List[GenerationResponse])
def get_admin_history(
    skip: int = 0,
    limit: int = 20,
    search: str = Query(None),
    date_from: date = Query(None),
    date_to: date = Query(None),
    current_user: User = Depends(get_current_admin_user),
    db: Session = Depends(get_db),
):
    return generation_service.get_all_generations(db, skip, limit, search, date_from, date_to)


@router.get("/stats", response_model=GenerationStats)
def get_stats(
    current_user: User = Depends(require_permission("history.view")),
    db: Session = Depends(get_db),
):
    if _is_management(current_user, db):
        return generation_service.get_generation_stats(db)
    return generation_service.get_generation_stats(db, current_user.id)


@router.get("/{generation_id}", response_model=GenerationResponse)
def get_generation(
    generation_id: str,
    current_user: User = Depends(require_permission("history.view")),
    db: Session = Depends(get_db),
):
    if _is_management(current_user, db):
        return generation_service.get_generation_by_id(db, generation_id)
    return generation_service.get_generation_by_id(db, generation_id, current_user.id)


@router.delete("/{generation_id}")
def delete_generation(
    generation_id: str,
    current_user: User = Depends(require_permission("history.view")),
    db: Session = Depends(get_db),
):
    generation_service.delete_generation(db, generation_id, current_user.id)
    return {"detail": "Generation deleted"}
