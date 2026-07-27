import pytest

from app.services import customer_evidence_bundle


def test_bundle_keeps_only_same_sku_customer_visible_valid_evidence():
    bundle = customer_evidence_bundle.build_customer_evidence_bundle(
        sku="CW-C83",
        product_name="炊墨套锅",
        evidence_items=[
            {
                "evidence_id": "field:material",
                "sku": "CW-C83",
                "source_type": "structured_field",
                "source": "specs.body_material",
                "field": "material",
                "value": "硬质氧化铝合金、白蜡木",
                "visibility": "customer_visible",
            },
            {
                "evidence_id": "internal:owner",
                "sku": "CW-C83",
                "source_type": "structured_field",
                "source": "product.person_in_charge",
                "field": "person_in_charge",
                "value": "Internal Owner",
                "visibility": "internal_only",
            },
            {
                "evidence_id": "field:capacity",
                "sku": "CW-C83",
                "source_type": "structured_field",
                "source": "specs.capacity",
                "field": "capacity",
                "value": "待补充",
                "visibility": "customer_visible",
            },
        ],
    )

    assert bundle.sku == "CW-C83"
    assert [item.evidence_id for item in bundle.items] == ["field:material"]
    assert bundle.value_for_field("material") == "硬质氧化铝合金、白蜡木"
    assert bundle.value_for_field("capacity") == ""


def test_bundle_rejects_cross_sku_evidence():
    with pytest.raises(ValueError, match="cross-SKU"):
        customer_evidence_bundle.build_customer_evidence_bundle(
            sku="CW-C83",
            product_name="炊墨套锅",
            evidence_items=[
                {
                    "evidence_id": "qa:foreign",
                    "sku": "CW-C95",
                    "source_type": "product_qa",
                    "source": "product_qa:foreign",
                    "field": "product_qa",
                    "value": "Foreign product answer",
                    "visibility": "customer_visible",
                }
            ],
        )


def test_bundle_preserves_multiple_sources_without_exposing_internal_metadata():
    bundle = customer_evidence_bundle.build_customer_evidence_bundle(
        sku="TW-204-42",
        product_name="便携式户外旅行筷",
        evidence_items=[
            {
                "evidence_id": "qa:travel",
                "sku": "TW-204-42",
                "source_type": "product_qa",
                "source": "product_qa:travel",
                "field": "product_qa",
                "value": "适合旅行使用，可折叠便携。",
                "visibility": "customer_visible",
            },
            {
                "evidence_id": "knowledge:1",
                "sku": "TW-204-42",
                "source_type": "knowledge_chunk",
                "source": "knowledge_chunk:1",
                "field": "product_qa",
                "value": "净重约36g，折叠后体积小巧。",
                "visibility": "customer_visible",
            },
        ],
    )

    payload = bundle.to_customer_evidence()

    assert len(payload) == 2
    assert {item["source_type"] for item in payload} == {"product_qa", "knowledge_chunk"}
    assert all("visibility" not in item for item in payload)
