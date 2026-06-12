from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from pydantic import BaseModel
from ..core.database import get_db
from ..core.security import require_any_permission, require_permission
from ..models.product_category import ProductCategory
from ..schemas.common import UuidStr

router = APIRouter(prefix="/api/categories", tags=["categories"])


class CategoryCreate(BaseModel):
    category_name: str
    description: str | None = None


class CategoryResponse(BaseModel):
    id: UuidStr
    category_name: str
    description: str | None = None

    model_config = {"from_attributes": True}


@router.get("", response_model=list[CategoryResponse])
def list_categories(
    db: Session = Depends(get_db),
    current_user=Depends(require_any_permission("category.read", "product.read", "product.create", "product.edit")),
):
    return db.query(ProductCategory).order_by(ProductCategory.id).all()


@router.post("", response_model=CategoryResponse, status_code=201)
def create_category(
    data: CategoryCreate,
    db: Session = Depends(get_db),
    current_user=Depends(require_permission("tag.edit")),
):
    existing = db.query(ProductCategory).filter(
        ProductCategory.category_name == data.category_name
    ).first()
    if existing:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Category already exists")
    cat = ProductCategory(category_name=data.category_name, description=data.description)
    db.add(cat)
    db.commit()
    db.refresh(cat)
    return cat


@router.delete("/{category_id}", status_code=204)
def delete_category(
    category_id: str,
    db: Session = Depends(get_db),
    current_user=Depends(require_permission("tag.edit")),
):
    cat = db.query(ProductCategory).filter(ProductCategory.id == category_id).first()
    if not cat:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Category not found")
    db.delete(cat)
    db.commit()
