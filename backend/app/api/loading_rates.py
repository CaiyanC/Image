from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..core.database import get_db
from ..core.security import require_any_permission
from ..models.product import Product
from ..models.product_supply_chain import ProductSupplyChain
from ..schemas.loading_rate import LoadingRateCalculationRequest
from ..services.loading_rate_service import (
    calculate_carton_cargo_volume,
    calculate_loading_rate,
    outer_carton_volume_m3,
)


router = APIRouter(prefix="/api/loading-rates", tags=["loading-rates"])


def _number(value: Decimal) -> float:
    return float(value)


@router.post("/calculate")
def calculate(
    payload: LoadingRateCalculationRequest,
    current_user=Depends(require_any_permission("product.full.view", "product.edit")),
    db: Session = Depends(get_db),
):
    del current_user

    lines: list[dict] = []
    if payload.actual_cargo_volume_m3 is not None:
        actual_volume = payload.actual_cargo_volume_m3
    else:
        requested_skus = [item.sku.strip() for item in payload.items]
        products = db.query(Product).filter(Product.sku.in_(requested_skus)).all()
        products_by_sku = {product.sku: product for product in products}
        supply_rows = db.query(ProductSupplyChain).filter(
            ProductSupplyChain.product_id.in_([product.id for product in products]),
        ).all()
        # Product.id is returned as UUID by PostgreSQL while the legacy
        # supply-chain model exposes product_id as str. Normalize both sides
        # before joining so a complete carton dimension row is not reported as
        # missing merely because of the Python value type.
        supply_by_product_id = {str(row.product_id): row for row in supply_rows}

        missing: list[str] = []
        actual_volume = Decimal("0")
        for item, sku in zip(payload.items, requested_skus):
            product = products_by_sku.get(sku)
            supply = supply_by_product_id.get(str(product.id)) if product else None
            if product is None or supply is None:
                missing.append(sku)
                continue
            dimensions = (
                supply.outer_carton_length_cm,
                supply.outer_carton_width_cm,
                supply.outer_carton_height_cm,
            )
            if not all(value is not None and value > 0 for value in dimensions):
                missing.append(sku)
                continue
            carton_volume = outer_carton_volume_m3(*dimensions)
            line_volume = calculate_carton_cargo_volume(
                carton_volume_m3=carton_volume,
                carton_count=item.carton_count,
            )
            actual_volume += line_volume
            lines.append({
                "sku": sku,
                "carton_count": item.carton_count,
                "carton_volume_m3": _number(carton_volume),
                "cargo_volume_m3": _number(line_volume),
            })
        if missing:
            raise HTTPException(
                status_code=422,
                detail={
                    "message": "以下 SKU 缺少完整外箱长宽高，不能据此计算装载率",
                    "missing_skus": sorted(set(missing)),
                },
            )

    try:
        result = calculate_loading_rate(
            actual_cargo_volume_m3=actual_volume,
            container_usable_volume_m3=payload.container_usable_volume_m3,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    return {
        **{key: _number(value) if isinstance(value, Decimal) else value for key, value in result.items()},
        "items": lines,
        "calculation_scope": "装柜/出货批次",
        "source_note": "产品资料只提供外箱体积；装载率必须结合本次实际装柜数量和集装箱可用体积计算。",
    }
