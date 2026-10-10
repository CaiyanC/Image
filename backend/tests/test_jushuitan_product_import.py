import importlib.util
from decimal import Decimal
from pathlib import Path


_SCRIPT = Path(__file__).parents[1] / "scripts" / "import_jushuitan_product_supply_chain.py"
_SPEC = importlib.util.spec_from_file_location("jushuitan_product_import", _SCRIPT)
assert _SPEC and _SPEC.loader
import_jushuitan_product_supply_chain = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(import_jushuitan_product_supply_chain)


def test_parse_outer_carton_dimensions_converts_mm_only_with_explicit_unit():
    result = import_jushuitan_product_supply_chain.parse_outer_carton_dimensions("650*440*590mm")
    assert result == {
        "outer_carton_length_cm": Decimal("65.0"),
        "outer_carton_width_cm": Decimal("44.0"),
        "outer_carton_height_cm": Decimal("59.0"),
    }


def test_parse_outer_carton_dimensions_rejects_ambiguous_value():
    assert import_jushuitan_product_supply_chain.parse_outer_carton_dimensions("650*440*590") is None
