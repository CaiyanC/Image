from app.models.product import Product
from app.services.customer_agent_service import resolve_named_product_candidates


def _product(sku: str, name: str) -> Product:
    return Product(
        id=f"id-{sku}",
        sku=sku,
        barcode=f"barcode-{sku}",
        product_name_cn=name,
        product_name_en=name,
        brand="测试品牌",
        category="壶具",
    )


def test_variant_reference_binds_cup_count_and_color_without_family_siblings():
    products = [
        _product("KW-K31-白", "天鹅壶4杯白"),
        _product("KW-K31-黑", "天鹅壶4杯-黑色"),
        _product("KW-K32-白", "天鹅壶9杯白"),
        _product("KW-K32-黑", "天鹅壶9杯-黑色"),
    ]

    assert {item.sku for item in resolve_named_product_candidates(
        "天鹅壶4杯黑和9杯白有什么区别？", products,
    )} == {"KW-K32-白", "KW-K31-黑"}
    assert [item.sku for item in resolve_named_product_candidates(
        "天鹅壶4杯黑", products,
    )] == ["KW-K31-黑"]
    assert [item.sku for item in resolve_named_product_candidates(
        "天鹅壶9杯白", products,
    )] == ["KW-K32-白"]


def test_missing_color_keeps_family_variants_ambiguous():
    products = [
        _product("KW-K32-白", "天鹅壶9杯白"),
        _product("KW-K32-黑", "天鹅壶9杯-黑色"),
    ]

    assert [item.sku for item in resolve_named_product_candidates(
        "天鹅壶9杯能明火吗？", products,
    )] == ["KW-K32-白", "KW-K32-黑"]
