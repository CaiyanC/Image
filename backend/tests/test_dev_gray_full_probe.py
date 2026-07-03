from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


def _load_probe_module():
    module_path = Path(__file__).resolve().parents[2] / "scripts" / "dev_gray_full_probe.py"
    spec = importlib.util.spec_from_file_location("dev_gray_full_probe", module_path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _base_result(answer: str, answer_type: str, result_skus: list[str] | None = None) -> dict:
    return {
        "status": 200,
        "answer": answer,
        "answer_type": answer_type,
        "result_skus": result_skus or [],
        "metadata_skus": result_skus or [],
        "timing": {},
        "guard_rebuild_fallback": {},
    }


def test_q04_dual_bucket_answer_with_cf_pg19_passes():
    probe = _load_probe_module()
    result = _base_result(
        "炉具方向：CS-G26HM。烤盘方向：CF-PG19，适合多人户外烧烤。",
        "recommendation",
        ["CS-G26HM", "CF-PG19", "CS-G26CS"],
    )
    verdict, issues, category, data_issue = probe.classify_result("q04", result, {})
    assert verdict == "pass"
    assert issues == []
    assert category is None
    assert data_issue is None


def test_q06_equivalent_material_and_nonstick_wording_passes():
    probe = _load_probe_module()
    result = _base_result(
        "轻途套锅（CW-C06PRO）\n主体材质：3003铝合金。\n粘锅/不粘：当前资料未找到不粘或涂层说明，无法保证不粘。",
        "product_detail",
        ["CW-C06PRO"],
    )
    verdict, issues, category, _ = probe.classify_result("q06", result, {})
    assert verdict == "pass"
    assert issues == []
    assert category is None


def test_q08_suspicious_8l_capacity_becomes_data_warning():
    probe = _load_probe_module()
    result = _base_result(
        "享野水壶（CW-C76）\n容量：8L\n冷水/水温：当前资料未明确标注装冷水限制或适用水温。",
        "product_detail",
        ["CW-C76"],
    )
    verdict, issues, category, data_issue = probe.classify_result("q08", result, {})
    assert verdict == "warning"
    assert issues == ["q08_capacity_data_suspect"]
    assert category == "data_field"
    assert data_issue["sku"] == "CW-C76"


def test_q03_scope_drift_is_probe_warning_not_business_fail():
    probe = _load_probe_module()
    result = _base_result(
        "当前资料里没有找到四个人露营要做饭用的明确锅具信息。",
        "product_detail",
        [],
    )
    verdict, issues, category, _ = probe.classify_result("q03", result, {})
    assert verdict == "warning"
    assert issues == ["q03_probe_prompt_scope_drift"]
    assert category == "probe_rule"


def test_q23_explicit_not_supported_is_not_overbroad_warning():
    probe = _load_probe_module()
    result = _base_result(
        "墨迹套锅（CW-C83）当前资料未显示支持酒精炉，当前资料显示热源为明火直烧、卡式炉、分体炉、一体炉。",
        "product_detail",
        ["CW-C83"],
    )
    verdict, issues, category, _ = probe.classify_result("q23", result, {})
    assert verdict == "pass"
    assert issues == []
    assert category is None


def test_q25_support_with_same_sku_evidence_passes():
    probe = _load_probe_module()
    result = _base_result(
        "激川单锅 CW-S10-A 当前资料显示支持酒精炉，热源/同 SKU 证据为酒精炉。容量约 1400ML，人数资料未明确标注。",
        "product_detail",
        ["CW-S10-A"],
    )
    verdict, issues, category, _ = probe.classify_result("q25", result, {})
    assert verdict == "pass"
    assert issues == []
    assert category is None


def test_q26_exclusion_query_allows_empty_result_skus():
    probe = _load_probe_module()
    result = _base_result(
        "当前资料里只明确找到 CW-S10-A 支持酒精炉，除了它暂无其他明确支持酒精炉的锅具。",
        "product_query",
        [],
    )
    verdict, issues, category, _ = probe.classify_result("q26", result, {})
    assert verdict == "pass"
    assert issues == []
    assert category is None
