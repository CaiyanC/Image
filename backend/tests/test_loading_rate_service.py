from decimal import Decimal

import pytest

from app.services.loading_rate_service import (
    calculate_carton_cargo_volume,
    calculate_loading_rate,
    outer_carton_volume_m3,
)


def test_outer_carton_volume_converts_centimetres_to_cubic_metres():
    assert outer_carton_volume_m3("35.5", 24, "18.25") == Decimal("0.015549")


def test_loading_rate_is_not_clamped_when_plan_exceeds_capacity():
    result = calculate_loading_rate(
        actual_cargo_volume_m3=Decimal("11"),
        container_usable_volume_m3=Decimal("10"),
    )
    assert result["loading_rate_pct"] == Decimal("110.0000")
    assert result["over_capacity"] is True


def test_carton_count_must_be_positive_integer():
    with pytest.raises(ValueError, match="装柜箱数"):
        calculate_carton_cargo_volume(carton_volume_m3=Decimal("1"), carton_count=0)


def test_container_volume_must_be_positive():
    with pytest.raises(ValueError, match="集装箱可用体积"):
        calculate_loading_rate(actual_cargo_volume_m3=1, container_usable_volume_m3=0)
