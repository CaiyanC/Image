"""Pure calculations for container loading-rate checks.

Product master data can provide an outer-carton volume, but a loading rate is
always a shipment/container-scoped value. Keep the arithmetic here so the API
and any future batch/shipment workflow use the same definition.
"""

from decimal import Decimal, InvalidOperation, ROUND_HALF_UP


_PCT_QUANTUM = Decimal("0.0001")
_VOLUME_QUANTUM = Decimal("0.000001")


def _decimal(value: Decimal | int | float | str, field: str) -> Decimal:
    try:
        number = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ValueError(f"{field} 必须是数字") from exc
    if not number.is_finite():
        raise ValueError(f"{field} 必须是有限数字")
    return number


def outer_carton_volume_m3(
    length_cm: Decimal | int | float | str,
    width_cm: Decimal | int | float | str,
    height_cm: Decimal | int | float | str,
) -> Decimal:
    """Return one outer-carton volume in cubic metres from centimetres."""

    dimensions = (
        _decimal(length_cm, "外箱长"),
        _decimal(width_cm, "外箱宽"),
        _decimal(height_cm, "外箱高"),
    )
    if any(value <= 0 for value in dimensions):
        raise ValueError("外箱长、宽、高必须大于 0")
    return (dimensions[0] * dimensions[1] * dimensions[2] / Decimal("1000000")).quantize(
        _VOLUME_QUANTUM,
        rounding=ROUND_HALF_UP,
    )


def calculate_loading_rate(
    *,
    actual_cargo_volume_m3: Decimal | int | float | str,
    container_usable_volume_m3: Decimal | int | float | str,
) -> dict[str, Decimal | bool | str]:
    """Calculate actual cargo volume / usable container volume * 100.

    ``actual_cargo_volume_m3`` is the occupied cargo volume, not a product's
    single-unit volume. Values above 100% are returned as a warning state so
    callers can catch an over-capacity plan instead of silently clamping it.
    """

    actual = _decimal(actual_cargo_volume_m3, "实际货物体积")
    usable = _decimal(container_usable_volume_m3, "集装箱可用体积")
    if actual < 0:
        raise ValueError("实际货物体积不能小于 0")
    if usable <= 0:
        raise ValueError("集装箱可用体积必须大于 0")

    rate = (actual / usable * Decimal("100")).quantize(
        _PCT_QUANTUM,
        rounding=ROUND_HALF_UP,
    )
    return {
        "actual_cargo_volume_m3": actual.quantize(_VOLUME_QUANTUM, rounding=ROUND_HALF_UP),
        "container_usable_volume_m3": usable.quantize(_VOLUME_QUANTUM, rounding=ROUND_HALF_UP),
        "loading_rate_pct": rate,
        "over_capacity": rate > Decimal("100"),
        "formula": "实际货物体积 ÷ 集装箱可用体积 × 100%",
    }


def calculate_carton_cargo_volume(
    *,
    carton_volume_m3: Decimal | int | float | str,
    carton_count: int,
) -> Decimal:
    """Return cargo volume contributed by a number of outer cartons."""

    volume = _decimal(carton_volume_m3, "单箱体积")
    if volume <= 0:
        raise ValueError("单箱体积必须大于 0")
    if not isinstance(carton_count, int) or isinstance(carton_count, bool) or carton_count < 1:
        raise ValueError("装柜箱数必须是大于 0 的整数")
    return (volume * carton_count).quantize(_VOLUME_QUANTUM, rounding=ROUND_HALF_UP)
