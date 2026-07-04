from __future__ import annotations

import argparse
import importlib.util
import json
import math
import os
import sys
import time
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
REPORT_DIR = ROOT / "reports"
ENV_FILE = ROOT / "backend" / ".env.dev"


def _load_base_module():
    module_path = ROOT / "scripts" / "dev_large_business_probe.py"
    spec = importlib.util.spec_from_file_location("dev_large_business_probe", module_path)
    if not spec or not spec.loader:
        raise RuntimeError(f"failed to load probe helpers from {module_path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules.setdefault(spec.name, module)
    spec.loader.exec_module(module)
    return module


BASE = _load_base_module()


@dataclass(frozen=True)
class RegressionCase:
    case_id: str
    group: str
    question: str
    sequence_id: str
    expected: dict[str, Any] = field(default_factory=dict)
    turn_index: int = 1


def _inventory_items(inventory: dict[str, Any]) -> list[BASE.InventoryItem]:
    return BASE._inventory_items(inventory)


def _sku_map(products: list[BASE.InventoryItem]) -> dict[str, BASE.InventoryItem]:
    return {item.sku.upper(): item for item in products}


def _contains_any(text: str, tokens: list[str] | tuple[str, ...]) -> bool:
    value = str(text or "")
    return any(token in value for token in tokens)


def _normalize_skus(items: list[Any] | None) -> list[str]:
    return [str(item).upper() for item in (items or []) if str(item or "").strip()]


def _question_for_water_item(sku: str) -> tuple[str, str]:
    return (f"{sku} 能不能装冷水？更适合烧水还是随身补水？", "water_usage")


def _question_for_cook_item(sku: str) -> tuple[str, str]:
    return (f"{sku} 适合什么场景？能不能用酒精炉？", "usage_heat")


def _field_question(item: BASE.InventoryItem, slot: int) -> tuple[str, str]:
    if slot == 0:
        return (f"{item.sku} 是什么材质？", "material")
    if slot == 1:
        if item.capacity:
            return (f"{item.sku} 容量多大？", "capacity")
        if item.weight_g:
            return (f"{item.sku} 重量多少？", "weight")
        return (f"{item.sku} 尺寸大概多大？", "size")
    water_like = _contains_any(item.category + item.name, ["水具", "水壶", "壶", "杯"])
    if water_like:
        return _question_for_water_item(item.sku)
    return _question_for_cook_item(item.sku)


REQUIRED_SKUS = [
    "CW-C83",
    "CW-C06PRO",
    "CW-C78",
    "CW-C19T-37",
    "CW-C69-1",
    "CW-C93",
    "CW-C76",
    "CS-G25",
    "CS-G18-28",
    "TW-422-蓝",
    "TW-422-绿",
    "TW-422-粉",
    "KW-K31-白",
    "KW-K31-黑",
    "KW-K32-白",
    "KW-K32-黑",
    "CT-T04(BM)",
    "CW-C65-4",
    "GX14-230G",
    "GX15-450G",
    "TW-139",
    "TW-503",
    "CW-C97",
    "AC-Z07",
    "CS-B14",
]

FIELD_ALIASES: dict[str, set[str]] = {
    "material": {"material", "材质", "材料"},
    "capacity": {"capacity", "容量", "容积", "装水量"},
    "weight": {"weight", "重量", "净重"},
    "size": {"size", "尺寸", "规格", "大小"},
    "scene": {"scene", "scenario", "使用场景", "适用场景", "场景"},
    "heat_source": {"heat_source", "热源", "炉具", "适用炉具", "火源"},
    "alcohol_stove": {"alcohol_stove", "heat_source", "热源", "酒精炉", "能否使用酒精炉"},
    "cold_water": {"cold_water", "冷水", "装冷水", "饮水"},
    "boil_water": {"boil_water", "烧水", "煮水", "加热"},
    "hydration": {"hydration", "补水", "随身补水", "饮水"},
    "material_capacity": {"material", "capacity"},
    "weight_size": {"weight", "size"},
    "scene_alcohol_stove": {"scene", "alcohol_stove"},
    "water_usage": {"cold_water", "boil_water", "hydration"},
    "usage_heat": {"scene", "alcohol_stove"},
}


def normalize_field_label(value: str | None) -> str:
    label = str(value or "").strip().lower()
    if not label:
        return ""
    for canonical, aliases in FIELD_ALIASES.items():
        normalized_aliases = {str(alias).strip().lower() for alias in aliases}
        if label == canonical or label in normalized_aliases:
            return canonical
    return label


def _expected_field_labels(value: str | None) -> set[str]:
    canonical = normalize_field_label(value)
    if not canonical:
        return set()
    aliases = FIELD_ALIASES.get(canonical)
    if not aliases:
        return {canonical}
    normalized = {normalize_field_label(alias) for alias in aliases}
    if canonical in normalized:
        return normalized
    return normalized or {canonical}


FIELD_SEMANTIC_TOKENS: dict[str, tuple[str, ...]] = {
    "material": ("材质", "材料", "铝", "合金", "不锈钢", "钛", "硬质氧化"),
    "capacity": ("容量", "容积", "ml", "l", "升"),
    "weight": ("重量", "净重", "g", "kg"),
    "size": ("尺寸", "规格", "cm", "mm"),
    "scene": ("场景", "适合", "适用", "露营", "野餐", "徒步", "自驾"),
    "heat_source": ("热源", "明火", "卡式炉", "分体炉", "一体炉", "电磁炉", "燃气炉"),
    "alcohol_stove": ("酒精炉", "支持酒精炉", "能用酒精炉"),
    "cold_water": ("冷水", "装冷水"),
    "boil_water": ("烧水", "煮水", "加热"),
    "hydration": ("补水", "饮水", "随身补水"),
}


def _field_semantics_present(answer: str, canonical_fields: set[str]) -> set[str]:
    lowered = str(answer or "").lower()
    matched: set[str] = set()
    for field in canonical_fields:
        tokens = FIELD_SEMANTIC_TOKENS.get(field, ())
        if any(token.lower() in lowered for token in tokens):
            matched.add(field)
    return matched

CATEGORY_LIST_CASES = [
    ("cat_1_list", "有哪些锅具产品？", "锅具"),
    ("cat_2_list", "有哪些配件产品？", "配件"),
    ("cat_3_list", "有哪些炉具产品？", "炉具"),
    ("cat_4_list", "有哪些餐具产品？", "餐具"),
    ("cat_5_list", "有哪些水具产品？", "水具"),
    ("cat_6_list", "有哪些水壶产品？", "水壶"),
    ("cat_7_list", "有哪些天幕、地垫、帐篷产品？", "天幕、地垫、帐篷"),
    ("cat_8_list", "有哪些桌椅产品？", "桌椅"),
    ("cat_9_list", "有哪些咖啡器具产品？", "咖啡器具"),
    ("cat_10_list", "有哪些茶具产品？", "茶具"),
]

SCENARIO_CASES = [
    ("scene_001", "我一个人徒步，想轻一点，推荐一个锅。", "锅具"),
    ("scene_002", "两个人轻露营，希望锅具轻一点但也别太单薄。", "锅具"),
    ("scene_003", "三口之家周末近郊露营，锅具别太重但容量别太小。", "锅具"),
    ("scene_004", "长途自驾露营，人数四五个，锅具更看重容量和稳定性。", "锅具"),
    ("scene_005", "公园野餐两个人用，想选个好收纳的锅具。", "锅具"),
    ("scene_006", "露营烧烤场景，炉具和烤盘怎么搭更合适？", "炉具"),
    ("scene_007", "营地早餐场景想煎东西，锅具和烤盘哪个更合适？", "炉具"),
    ("scene_008", "多人露营想做正餐，容量大一点但收纳别太差。", "锅具"),
    ("scene_009", "女生一个人公园野餐，想轻一点又能烧水的炊具。", "锅具"),
    ("scene_010", "新手第一次露营，想先买一个不容易踩坑的主锅具。", "锅具"),
    ("scene_011", "夏天露营更看重随身补水，先选水具还是水壶？", "水具"),
    ("scene_012", "家庭露营带孩子，锅具要稳一点也别太难清理。", "锅具"),
    ("scene_013", "烧烤场景想带炉子和烤盘，先买哪类最值？", "炉具"),
    ("scene_014", "长途徒步只想带一个锅，能烧水也能做简单餐食。", "锅具"),
    ("scene_015", "冬天露营想煮热汤，锅具优先容量还是稳定性？给个推荐。", "锅具"),
    ("scene_016", "多人露营预算有限，先买哪个主锅具最合适？", "锅具"),
    ("scene_017", "公园野餐想烧水和简单煮食，锅具怎么选最稳？", "锅具"),
    ("scene_018", "家庭露营偏火锅场景，锅具容量优先怎么选？", "锅具"),
    ("scene_019", "露营烧烤加热饮都要兼顾，炉具怎么搭更稳？", "炉具"),
    ("scene_020", "两个人露营偏爱火锅场景，锅具要稳一点，推荐哪个？", "锅具"),
    ("scene_x051", "双人露营不想太重，也不想买太贵，推荐哪套？", "锅具"),
]

MULTITURN_SEQUENCES = {
    "q15": [
        "我一个人徒步，想轻一点，推荐一个锅。",
        "它能不能用酒精炉？",
        "有没有更便宜一点的替代？",
    ],
    "q17": [
        "轻途套锅和享野套锅有什么区别？",
        "那哪个更适合新手？",
        "它们能不能用酒精炉？",
    ],
    "mt_003": [
        "周末两个人野餐，推荐一套锅。",
        "为什么推荐这个？",
        "还有没有更轻便一点的？",
    ],
    "mt_004": [
        "推荐一个适合三个人露营的锅。",
        "它容量够煮汤吗？",
        "有没有更便宜的同类？",
    ],
    "mt_005": [
        "有没有适合烧烤的炉具？",
        "那配什么烤盘更合适？",
        "有没有更便宜一点的？",
    ],
    "mt_006": [
        "给我推荐一个烧水用的水壶。",
        "它可以装冷水吗？",
        "更适合烧水还是随身补水？",
    ],
    "mt_007": [
        "我想买个适合新手的套锅。",
        "它支持酒精炉吗？",
    ],
    "mt_008": [
        "有哪些锅具产品？",
        "里面哪些支持酒精炉？",
        "有没有更适合两个人的？",
    ],
    "mt_009": [
        "推荐一个双人露营锅。",
        "为什么推荐它？",
        "再给一个更轻的备选。",
    ],
    "mt_010": [
        "行山单锅和激川单锅有什么区别？",
        "哪个更适合新手？",
    ],
    "mt_011": [
        "推荐一个家庭露营用的主锅具。",
        "有没有更大一点的？",
        "那更适合火锅吗？",
    ],
    "mt_012": [
        "推荐一个露营水壶。",
        "它适合烧水还是随身补水？",
    ],
    "mt_013": [
        "双人野餐想买锅。",
        "换一个，别要刚才那个。",
        "第二个和第三个哪个好？",
    ],
    "mt_014": [
        "多人露营想买锅具。",
        "它能不能放酒精炉上？",
    ],
    "mt_015": [
        "比较一下 CW-C06PRO 和 CW-C19T-37。",
        "哪个更适合新手？",
    ],
    "mt_016": [
        "你刚才推荐的第一个和第二个哪个更好？",
    ],
    "mt_017": [
        "推荐一个适合公园野餐的锅具。",
        "第一个能不能烧水？",
        "第二个有没有更轻一点的版本？",
    ],
    "mt_018": [
        "推荐一个适合夏天补水的水具。",
        "最后一个能不能装冷水？",
        "换一个更适合随身补水的。",
    ],
    "mt_019": [
        "比较一下 CF-PG11-42 和 CF-PG19。",
        "第一个和第二个哪个更适合烧烤新手？",
    ],
    "mt_020": [
        "推荐一个适合两个人轻露营的锅。",
        "不要刚才那个，再换一个。",
        "最后一个能不能用酒精炉？",
    ],
}


def _preferred_explicit_skus(products: list[BASE.InventoryItem], target: int = 30) -> list[str]:
    sku_lookup = _sku_map(products)
    selected: list[str] = []
    for sku in REQUIRED_SKUS:
        if sku.upper() in sku_lookup and sku.upper() not in selected:
            selected.append(sku.upper())
        if len(selected) >= target:
            return selected
    for item in BASE._round_robin_select(products, limit=len(products)):
        if item.sku.upper() not in selected:
            selected.append(item.sku.upper())
        if len(selected) >= target:
            break
    return selected[:target]


def _generic_single_turn_cases(products: list[BASE.InventoryItem], exclude_skus: set[str], target: int) -> list[dict[str, Any]]:
    cases: list[dict[str, Any]] = []
    for item in BASE._round_robin_select(products, limit=len(products)):
        if item.sku.upper() in exclude_skus:
            continue
        water_like = _contains_any(item.category + item.name, ["水具", "水壶", "壶", "杯"])
        if water_like:
            question = f"{item.sku} 适合烧水还是随身补水？"
        else:
            question = f"{item.sku} 适合什么场景？重量和尺寸大概怎么样？"
        cases.append(
            {
                "case_id": f"generic_{item.sku}",
                "group": "generic_fields",
                "question": question,
                "expected": {"explicit_sku": item.sku},
                "sequence_id": f"generic_{item.sku}",
            }
        )
        if len(cases) >= target:
            break
    return cases


def _compare_cases(products: list[BASE.InventoryItem], target: int) -> list[dict[str, Any]]:
    pairs = BASE._compare_candidates(products)[:target]
    return [
        {
            "case_id": f"compare_{index:03d}",
            "group": "compare",
            "question": f"{left.sku} 和 {right.sku} 有什么区别？推荐选一个。",
            "expected": {"pair": [left.sku.upper(), right.sku.upper()]},
            "sequence_id": f"compare_{index:03d}",
        }
        for index, (left, right) in enumerate(pairs, start=1)
    ]


def build_medium_plan(inventory: dict[str, Any]) -> dict[str, Any]:
    products = _inventory_items(inventory)
    sku_lookup = _sku_map(products)
    explicit_skus = _preferred_explicit_skus(products, target=30)
    explicit_cases: list[dict[str, Any]] = []
    for sku in explicit_skus:
        item = sku_lookup[sku]
        for slot in range(3):
            question, requested_field = _field_question(item, slot)
            explicit_cases.append(
                {
                    "case_id": f"matrix_{sku}_{slot + 1}",
                    "group": "explicit_sku_field_matrix",
                    "question": question,
                    "expected": {"explicit_sku": sku, "requested_field": requested_field},
                    "sequence_id": f"matrix_{sku}_{slot + 1}",
                }
            )

    category_cases = [
        {
            "case_id": case_id,
            "group": "category_list",
            "question": question,
            "expected": {"category": category},
            "sequence_id": case_id,
        }
        for case_id, question, category in CATEGORY_LIST_CASES
    ]
    scenario_cases = [
        {
            "case_id": case_id,
            "group": "scenario_recommendation",
            "question": question,
            "expected": {"expected_domain": expected_domain},
            "sequence_id": case_id,
        }
        for case_id, question, expected_domain in SCENARIO_CASES
    ]
    compare_cases = _compare_cases(products, target=20)
    generic_target = 200 - len(explicit_cases) - len(category_cases) - len(scenario_cases) - len(compare_cases)
    generic_cases = _generic_single_turn_cases(products, set(explicit_skus), target=generic_target)
    special_cases = [
        {
            "case_id": "q07",
            "group": "special_regression",
            "question": "CW-C83 能不能用酒精炉？如果不能就别推荐错了。",
            "expected": {"explicit_sku": "CW-C83", "requested_field": "heat_source"},
            "sequence_id": "q07",
        }
    ]

    single_turn_cases = explicit_cases + category_cases + scenario_cases + compare_cases + generic_cases
    if len(single_turn_cases) != 200:
        raise RuntimeError(f"expected 200 single-turn cases, got {len(single_turn_cases)}")

    multiturn_sequences: list[dict[str, Any]] = []
    for sequence_id, questions in MULTITURN_SEQUENCES.items():
        turns = []
        for index, question in enumerate(questions, start=1):
            turns.append(
                {
                    "case_id": f"{sequence_id}_t{index}",
                    "group": "multiturn",
                    "question": question,
                    "sequence_id": sequence_id,
                    "turn_index": index,
                    "expected": {"turn_index": index, "total_turns": len(questions)},
                }
            )
        multiturn_sequences.append({"sequence_id": sequence_id, "turns": turns})

    parity_cases: list[dict[str, Any]] = []
    priority_case_ids = {
        "q07",
        "cat_1_list",
        "cat_2_list",
        "cat_5_list",
        "scene_006",
        "scene_009",
        "matrix_CT-T04(BM)_3",
    }
    for case in special_cases + single_turn_cases:
        if case["case_id"] in priority_case_ids:
            parity_cases.append(case)
    for sequence_id in ("q15", "q17"):
        sequence = next(item for item in multiturn_sequences if item["sequence_id"] == sequence_id)
        parity_cases.extend(sequence["turns"])
    seen_ids = {case["case_id"] for case in parity_cases}
    for case in single_turn_cases:
        if len(parity_cases) >= 30:
            break
        if case["case_id"] in seen_ids:
            continue
        parity_cases.append(case)
        seen_ids.add(case["case_id"])

    coverage = {
        "single_turn": len(single_turn_cases),
        "special_regressions": len(special_cases),
        "multiturn_sequences": len(multiturn_sequences),
        "endpoint_parity": len(parity_cases),
        "explicit_sku_field_matrix": len(explicit_skus),
        "total_requests": len(special_cases) + len(single_turn_cases) + sum(len(seq["turns"]) for seq in multiturn_sequences) + len(parity_cases) * 2,
    }
    return {
        "single_turn_cases": single_turn_cases,
        "special_cases": special_cases,
        "multiturn_sequences": multiturn_sequences,
        "parity_cases": parity_cases[:30],
        "explicit_matrix_skus": explicit_skus,
        "coverage": coverage,
    }


def _percentile(sorted_values: list[float], pct: float) -> float:
    if not sorted_values:
        return 0.0
    if len(sorted_values) == 1:
        return sorted_values[0]
    rank = (len(sorted_values) - 1) * pct
    low = math.floor(rank)
    high = math.ceil(rank)
    if low == high:
        return sorted_values[low]
    fraction = rank - low
    return sorted_values[low] + (sorted_values[high] - sorted_values[low]) * fraction


def summarize_timing_stats(records: list[dict[str, Any]]) -> dict[str, Any]:
    durations = sorted(float(record.get("duration_ms") or 0) for record in records)
    by_answer_type: dict[str, list[float]] = defaultdict(list)
    llm_counter: Counter[str] = Counter()
    top = sorted(records, key=lambda item: float(item.get("duration_ms") or 0), reverse=True)[:10]
    for record in records:
        by_answer_type[str(record.get("answer_type") or "")].append(float(record.get("duration_ms") or 0))
        llm_counter[str(int(record.get("llm_call_count") or 0))] += 1
    return {
        "total_elapsed": round(sum(durations), 1),
        "p50": round(_percentile(durations, 0.50), 1),
        "p90": round(_percentile(durations, 0.90), 1),
        "p95": round(_percentile(durations, 0.95), 1),
        "p99": round(_percentile(durations, 0.99), 1),
        "max": round(max(durations) if durations else 0.0, 1),
        "slow_20s_count": sum(1 for value in durations if value >= 20000),
        "slow_30s_count": sum(1 for value in durations if value >= 30000),
        "slow_60s_count": sum(1 for value in durations if value >= 60000),
        "top_10_slowest": top,
        "answer_type_averages": {
            key: round(sum(values) / len(values), 1)
            for key, values in by_answer_type.items()
            if values
        },
        "llm_call_count_distribution": dict(llm_counter),
        "local_structured_slowest": [
            item
            for item in top
            if int(item.get("llm_call_count") or 0) == 0
        ][:10],
    }


def summarize_explicit_matrix(records: list[dict[str, Any]]) -> dict[str, Any]:
    failures = [record for record in records if record.get("judgement") == "fail"]
    return {
        "total": len(records),
        "pass": sum(1 for record in records if record.get("judgement") == "pass"),
        "warning": sum(1 for record in records if record.get("judgement") == "warning"),
        "fail": sum(1 for record in records if record.get("judgement") == "fail"),
        "mismatch": sum(1 for record in records if record.get("mismatch")),
        "kb_fallback": sum(1 for record in records if record.get("kb_fallback")),
        "empty_answer": sum(1 for record in records if record.get("empty_answer")),
        "field_wrong": sum(1 for record in records if record.get("field_wrong")),
        "field_alias_mismatch": sum(1 for record in records if record.get("field_alias_mismatch")),
        "compound_field_overstrict": sum(1 for record in records if record.get("compound_field_overstrict")),
        "slow": sum(1 for record in records if record.get("slow")),
        "top_failures": failures[:10],
    }


def _domain_matches(item: BASE.InventoryItem | None, expected_domain: str) -> bool:
    if not item:
        return False
    haystack = f"{item.category} {item.sub_category} {item.name}"
    if expected_domain == "炉具":
        return _contains_any(haystack, ["炉具", "烤盘", "烧烤"])
    if expected_domain == "水具":
        return _contains_any(haystack, ["水具", "水壶", "壶", "杯"])
    return _contains_any(haystack, [expected_domain])


def _scenario_expected_domain_overstrict(question: str, expected_domain: str, item: BASE.InventoryItem | None) -> bool:
    if not item or expected_domain != "\u7089\u5177":
        return False
    question_text = str(question or "")
    item_domain = f"{item.category} {item.sub_category} {item.name}"
    pot_question = _contains_any(
        question_text,
        ["\u9505\u5177", "\u9505", "\u54ea\u5957", "\u6c34\u58f6\u8fd8\u662f\u9505"],
    )
    stove_question = _contains_any(
        question_text,
        ["\u7089\u5177", "\u70e7\u70e4", "\u70e4\u76d8"],
    )
    return pot_question and not stove_question and _contains_any(
        item_domain,
        ["\u9505\u5177", "\u6c34\u58f6", "\u6c34\u5177"],
    )


def _classify_explicit_matrix(case: dict[str, Any], record: dict[str, Any]) -> dict[str, Any]:
    expected_sku = str(case["expected"]["explicit_sku"]).upper()
    answer = str(record.get("answer") or "")
    result_skus = _normalize_skus(record.get("result_skus"))
    debug_plan = record.get("debug_plan") or {}
    extracted_sku = (_normalize_skus(BASE._extract_question_skus(case["question"])) or [""])[0]
    planner_product_ref = str(debug_plan.get("product_ref") or "")
    requested_field = str(debug_plan.get("requested_field") or "")
    expected_field = str(case["expected"].get("requested_field") or case["expected"].get("field") or "")
    normalized_requested_field = normalize_field_label(requested_field)
    expected_fields = _expected_field_labels(expected_field)
    semantic_hits = _field_semantics_present(answer, expected_fields)
    kb_fallback = str(record.get("answer_type") or "") == "knowledge_base_answer"
    empty_answer = not answer.strip()
    mismatch = expected_sku not in result_skus
    field_alias_mismatch = bool(
        expected_fields
        and normalized_requested_field
        and normalized_requested_field not in expected_fields
    )
    compound_field_overstrict = False
    field_wrong = False
    slow = float(record.get("duration_ms") or 0) >= 20000
    judgement = "pass"
    audited = "ok"
    issues: list[str] = []
    if empty_answer:
        judgement = "fail"
        audited = "real_business"
        issues.append("empty_answer")
    elif kb_fallback:
        judgement = "fail"
        audited = "real_business"
        issues.append("unexpected_kb_fallback")
    elif mismatch:
        judgement = "fail"
        audited = "real_business"
        issues.append("explicit_sku_mismatch")
    elif semantic_hits and not normalized_requested_field:
        judgement = "warning"
        audited = "runner_noise"
        issues.append("missing_requested_field_warning")
    elif expected_fields and not semantic_hits:
        judgement = "fail"
        audited = "real_business"
        field_wrong = True
        issues.append("field_wrong")
        if not normalized_requested_field:
            issues.append("missing_requested_field")
        elif field_alias_mismatch:
            issues.append("field_alias_mismatch")
    elif field_alias_mismatch:
        judgement = "warning"
        audited = "runner_noise"
        issues.append("field_alias_mismatch")
    elif len(expected_fields) > 1 and normalized_requested_field and normalized_requested_field in expected_fields:
        judgement = "pass"
        audited = "ok"
        if not semantic_hits:
            judgement = "warning"
            audited = "runner_noise"
            compound_field_overstrict = True
            issues.append("compound_field_overstrict")
    elif slow:
        judgement = "warning"
        audited = "performance"
        issues.append("slow_local_path")
    return {
        **record,
        "group": case["group"],
        "expected_sku": expected_sku,
        "extracted_sku": extracted_sku,
        "planner_product_ref": planner_product_ref,
        "requested_field": requested_field,
        "normalized_requested_field": normalized_requested_field,
        "expected_field": expected_field,
        "normalized_expected_fields": sorted(expected_fields),
        "judgement": judgement,
        "audited_attribution": audited,
        "mismatch": mismatch,
        "kb_fallback": kb_fallback,
        "empty_answer": empty_answer,
        "field_wrong": field_wrong,
        "field_alias_mismatch": field_alias_mismatch,
        "compound_field_overstrict": compound_field_overstrict,
        "semantic_field_hits": sorted(semantic_hits),
        "slow": slow,
        "issues": issues,
    }


def _classify_single_turn(case: dict[str, Any], record: dict[str, Any], sku_lookup: dict[str, BASE.InventoryItem]) -> dict[str, Any]:
    if case["group"] == "explicit_sku_field_matrix":
        return _classify_explicit_matrix(case, record)
    if case["group"] == "special_regression":
        classified = _classify_explicit_matrix(case, record)
        classified["group"] = "special_regression"
        return classified

    answer = str(record.get("answer") or "")
    answer_type = str(record.get("answer_type") or "")
    result_skus = _normalize_skus(record.get("result_skus"))
    kb_fallback = answer_type == "knowledge_base_answer"
    duration_ms = float(record.get("duration_ms") or 0)
    judgement = "pass"
    audited = "ok"
    issues: list[str] = []

    if not answer.strip():
        judgement = "fail"
        audited = "real_business"
        issues.append("empty_answer")
    elif case["group"] == "category_list":
        if kb_fallback or not result_skus:
            judgement = "fail"
            audited = "real_business"
            issues.append("category_list_kb_or_empty")
        elif duration_ms >= 20000:
            judgement = "warning"
            audited = "performance"
            issues.append("slow_local_path")
    elif case["group"] == "scenario_recommendation":
        top_item = sku_lookup.get(result_skus[0]) if result_skus else None
        if kb_fallback or not result_skus:
            judgement = "fail"
            audited = "real_business"
            issues.append("unexpected_kb_fallback")
        elif answer_type not in {"recommendation", "product_query", "query_products"}:
            judgement = "warning"
            audited = "probe_rule"
            issues.append("scenario_answer_type_shape")
        elif _scenario_expected_domain_overstrict(case["question"], str(case["expected"].get("expected_domain") or ""), top_item):
            judgement = "warning"
            audited = "runner_noise"
            issues.append("scenario_expected_domain_overstrict")
        elif not _domain_matches(top_item, str(case["expected"].get("expected_domain") or "")):
            judgement = "fail"
            audited = "real_business"
            issues.append("recommendation_wrong_domain")
        elif duration_ms >= 20000:
            judgement = "warning"
            audited = "performance"
            issues.append("slow_local_path")
    elif case["group"] == "compare":
        expected_pair = [sku.upper() for sku in case["expected"].get("pair") or []]
        if kb_fallback or not result_skus:
            judgement = "fail"
            audited = "real_business"
            issues.append("compare_kb_or_empty")
        elif not any(sku in result_skus for sku in expected_pair):
            judgement = "warning"
            audited = "probe_rule"
            issues.append("compare_pair_weak")
    elif case["group"] == "generic_fields":
        expected_sku = str(case["expected"]["explicit_sku"]).upper()
        if kb_fallback:
            judgement = "fail"
            audited = "real_business"
            issues.append("unexpected_kb_fallback")
        elif result_skus and expected_sku not in result_skus:
            judgement = "fail"
            audited = "real_business"
            issues.append("generic_field_sku_mismatch")
        elif duration_ms >= 20000:
            judgement = "warning"
            audited = "performance"
            issues.append("slow_local_path")
    return {
        **record,
        "group": case["group"],
        "judgement": judgement,
        "audited_attribution": audited,
        "issues": issues,
        "kb_fallback": kb_fallback,
        "empty_answer": not answer.strip(),
        "mismatch": False,
        "field_wrong": False,
        "slow": duration_ms >= 20000,
    }


def _classify_multiturn_turn(case: dict[str, Any], record: dict[str, Any]) -> dict[str, Any]:
    answer = str(record.get("answer") or "")
    answer_type = str(record.get("answer_type") or "")
    kb_fallback = answer_type == "knowledge_base_answer"
    issues: list[str] = []
    judgement = "pass"
    audited = "ok"
    if not answer.strip():
        judgement = "fail"
        audited = "real_business"
        issues.append("empty_answer")
    elif case["turn_index"] > 1 and record.get("sent_conversation_id") != record.get("conversation_id"):
        judgement = "fail"
        audited = "real_business"
        issues.append("context_break")
    elif kb_fallback:
        judgement = "fail"
        audited = "real_business"
        if _contains_any(case["question"], ["它们", "这两个", "上面两个", "这几款"]):
            issues.append("pronoun_error")
        elif _contains_any(case["question"], ["第一个", "第二个", "最后一个"]):
            issues.append("ordinal_error")
        else:
            issues.append("multiturn_kb_fallback")
    elif float(record.get("duration_ms") or 0) >= 20000:
        judgement = "warning"
        audited = "performance"
        issues.append("slow_local_path")
    return {
        **record,
        "group": "multiturn",
        "judgement": judgement,
        "audited_attribution": audited,
        "issues": issues,
        "kb_fallback": kb_fallback,
        "empty_answer": not answer.strip(),
        "mismatch": False,
        "field_wrong": False,
        "slow": float(record.get("duration_ms") or 0) >= 20000,
    }


def _normalized_record(case_id: str, question: str, response: dict[str, Any]) -> dict[str, Any]:
    return {
        "case_id": case_id,
        "question": question,
        "conversation_id": response.get("conversation_id"),
        "sent_conversation_id": response.get("sent_conversation_id"),
        "answer_type": response.get("answer_type"),
        "intent": response.get("intent"),
        "result_skus": _normalize_skus(response.get("result_skus")),
        "answer": str(response.get("answer") or ""),
        "warnings": response.get("warnings") or [],
        "debug_plan": response.get("debug_plan") or {},
        "debug_trace": response.get("debug_trace") or {},
        "duration_ms": float((response.get("timing") or {}).get("total_duration_ms") or response.get("elapsed_ms_client") or 0),
        "llm_call_count": int(response.get("llm_call_count") or 0),
        "status": int(response.get("status") or 0),
    }


def _run_single_turn_case(token: str, case: dict[str, Any]) -> dict[str, Any]:
    raw = BASE.request_with_rate_limit_retry(lambda: BASE.ask(token, case["question"], None))
    record = _normalized_record(case["case_id"], case["question"], raw)
    if raw.get("status") == 429:
        return {
            **record,
            "group": case["group"],
            "judgement": "warning",
            "audited_attribution": "rate_limit",
            "issues": ["http_429"],
            "kb_fallback": False,
            "empty_answer": False,
            "mismatch": False,
            "field_wrong": False,
            "slow": False,
        }
    return record


def _run_multiturn_sequence(token: str, sequence: dict[str, Any]) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    conversation_id: str | None = None
    for turn in sequence["turns"]:
        raw = BASE.request_with_rate_limit_retry(lambda: BASE.ask(token, turn["question"], conversation_id))
        conversation_id = str(raw.get("conversation_id") or conversation_id or "")
        raw["sent_conversation_id"] = turn["question"] and (raw.get("sent_conversation_id") or (records[-1]["conversation_id"] if records else None))
        record = _normalized_record(turn["case_id"], turn["question"], raw)
        record["sent_conversation_id"] = raw.get("sent_conversation_id")
        records.append(record)
    return records


def _run_parity_case(token: str, case: dict[str, Any]) -> dict[str, Any]:
    ask = BASE.request_with_rate_limit_retry(lambda: BASE.ask(token, case["question"], None))
    stream = BASE.request_with_rate_limit_retry(lambda: BASE.ask_stream(token, case["question"], None))
    ask_record = _normalized_record(case["case_id"], case["question"], ask)
    stream_record = _normalized_record(case["case_id"], case["question"], stream)
    equivalent = (
        ask_record["answer_type"] == stream_record["answer_type"]
        and ask_record["result_skus"] == stream_record["result_skus"]
    )
    return {
        "case_id": case["case_id"],
        "question": case["question"],
        "ask": ask_record,
        "stream": stream_record,
        "equivalent": equivalent,
    }


def _run_parity_sequence(token: str, sequence: dict[str, Any]) -> list[dict[str, Any]]:
    ask_cid: str | None = None
    stream_cid: str | None = None
    reports: list[dict[str, Any]] = []
    for turn in sequence["turns"]:
        ask = BASE.request_with_rate_limit_retry(lambda: BASE.ask(token, turn["question"], ask_cid))
        ask_cid = str(ask.get("conversation_id") or ask_cid or "")
        stream = BASE.request_with_rate_limit_retry(lambda: BASE.ask_stream(token, turn["question"], stream_cid))
        stream_cid = str(stream.get("conversation_id") or stream_cid or "")
        ask_record = _normalized_record(turn["case_id"], turn["question"], ask)
        stream_record = _normalized_record(turn["case_id"], turn["question"], stream)
        reports.append(
            {
                "case_id": turn["case_id"],
                "question": turn["question"],
                "ask": ask_record,
                "stream": stream_record,
                "equivalent": ask_record["answer_type"] == stream_record["answer_type"] and ask_record["result_skus"] == stream_record["result_skus"],
                "ask_conversation_id": ask_cid,
                "stream_conversation_id": stream_cid,
            }
        )
    return reports


def _count_summary(records: list[dict[str, Any]]) -> dict[str, int]:
    raw = Counter()
    audited = Counter()
    for record in records:
        judgement = str(record.get("judgement") or "pass")
        if judgement == "pass":
            raw["pass"] += 1
        elif judgement == "warning":
            raw["warning"] += 1
        elif judgement == "fail":
            raw["fail"] += 1
        elif judgement == "blocking":
            raw["blocking fail"] += 1
        attribution = str(record.get("audited_attribution") or "ok")
        if judgement == "pass":
            audited["pass"] += 1
        elif judgement == "warning":
            audited["warning"] += 1
        elif judgement == "fail":
            audited["fail"] += 1
        elif judgement == "blocking":
            audited["blocking fail"] += 1
        if attribution == "real_business":
            audited["real_business"] += 1
        elif attribution == "data_field":
            audited["data_field"] += 1
        elif attribution == "probe_rule":
            audited["probe_rule"] += 1
        elif attribution == "runner_noise":
            audited["runner_noise"] += 1
        elif attribution == "rate_limit":
            audited["rate_limit"] += 1
        elif attribution == "performance":
            audited["performance"] += 1
    return {"raw": dict(raw), "audited": dict(audited)}


def _markdown_report(report: dict[str, Any]) -> str:
    lines = [
        "# Medium Full Regression Summary",
        "",
        f"- commit: `{report['git']['HEAD']}`",
        f"- total requests: `{report['coverage']['total_requests']}`",
        f"- audited fail: `{report['summary']['audited'].get('fail', 0)}`",
        f"- audited blocking fail: `{report['summary']['audited'].get('blocking fail', 0)}`",
        f"- empty answer: `{report['empty_answer']['count']}`",
        "",
        "## Timing",
        f"- total_elapsed: `{report['timing']['total_elapsed']}` ms",
        f"- p50 / p90 / p95 / p99: `{report['timing']['p50']}` / `{report['timing']['p90']}` / `{report['timing']['p95']}` / `{report['timing']['p99']}` ms",
        f"- max: `{report['timing']['max']}` ms",
        "",
        "## Explicit SKU Matrix",
        f"- total: `{report['explicit_sku_field_matrix']['total']}`",
        f"- fail: `{report['explicit_sku_field_matrix']['fail']}`",
        f"- mismatch: `{report['explicit_sku_field_matrix']['mismatch']}`",
        f"- kb_fallback: `{report['explicit_sku_field_matrix']['kb_fallback']}`",
        f"- field_wrong: `{report['explicit_sku_field_matrix']['field_wrong']}`",
        f"- field_alias_mismatch: `{report['explicit_sku_field_matrix']['field_alias_mismatch']}`",
        f"- compound_field_overstrict: `{report['explicit_sku_field_matrix']['compound_field_overstrict']}`",
        "",
        "## Top Slow Cases",
    ]
    for item in report["timing"]["top_10_slowest"]:
        lines.append(f"- `{item.get('case_id')}` `{item.get('duration_ms')}` ms `{item.get('answer_type')}`")
    return "\n".join(lines) + "\n"


def run_medium_full_regression(base_url: str) -> dict[str, Any]:
    BASE.DEFAULT_BASE_URL = base_url
    inventory = BASE.load_inventory()
    products = _inventory_items(inventory)
    sku_lookup = _sku_map(products)
    plan = build_medium_plan(inventory)
    token = BASE.login()

    started = time.perf_counter()
    classified_records: list[dict[str, Any]] = []

    for case in plan["special_cases"] + plan["single_turn_cases"]:
        raw_record = _run_single_turn_case(token, case)
        if raw_record.get("status") == 429:
            classified = raw_record
        else:
            classified = _classify_single_turn(case, raw_record, sku_lookup)
        classified_records.append(classified)

    multiturn_results: list[dict[str, Any]] = []
    for sequence in plan["multiturn_sequences"]:
        turns = _run_multiturn_sequence(token, sequence)
        sequence_records = []
        for turn_case, raw_record in zip(sequence["turns"], turns, strict=True):
            sequence_records.append(_classify_multiturn_turn(turn_case, raw_record))
        multiturn_results.append({"sequence_id": sequence["sequence_id"], "turns": sequence_records})
        classified_records.extend(sequence_records)

    parity_reports: list[dict[str, Any]] = []
    for case in plan["parity_cases"]:
        if case["case_id"].startswith("q15_t") or case["case_id"].startswith("q17_t"):
            continue
        parity_reports.append(_run_parity_case(token, case))
    for sequence_id in ("q15", "q17"):
        sequence = next(item for item in plan["multiturn_sequences"] if item["sequence_id"] == sequence_id)
        parity_reports.extend(_run_parity_sequence(token, sequence))

    elapsed = round((time.perf_counter() - started) * 1000, 1)
    timing = summarize_timing_stats(classified_records)
    timing["total_elapsed"] = elapsed

    explicit_matrix_records = [record for record in classified_records if record["group"] == "explicit_sku_field_matrix"]
    special_records = [record for record in classified_records if record["group"] == "special_regression"]
    category_records = [record for record in classified_records if record["group"] == "category_list"]
    scenario_records = [record for record in classified_records if record["group"] == "scenario_recommendation"]
    scene_019_record = next((record for record in scenario_records if record["case_id"] == "scene_019"), None)

    parity_mismatch_cases = [
        {
            "case_id": report["case_id"],
            "ask_answer_type": report["ask"]["answer_type"],
            "stream_answer_type": report["stream"]["answer_type"],
            "ask_result_skus": report["ask"]["result_skus"],
            "stream_result_skus": report["stream"]["result_skus"],
        }
        for report in parity_reports
        if not report["equivalent"]
    ]

    multiturn_issue_counter = Counter()
    multiturn_sequence_fail = 0
    multiturn_sequence_warn = 0
    multiturn_sequence_pass = 0
    for sequence in multiturn_results:
        sequence_judgements = {turn["judgement"] for turn in sequence["turns"]}
        if "fail" in sequence_judgements or "blocking" in sequence_judgements:
            multiturn_sequence_fail += 1
        elif "warning" in sequence_judgements:
            multiturn_sequence_warn += 1
        else:
            multiturn_sequence_pass += 1
        for turn in sequence["turns"]:
            for issue in turn.get("issues") or []:
                multiturn_issue_counter[issue] += 1

    summaries = _count_summary(classified_records)

    report = {
        "git": {
            "branch": BASE.run_git(["git", "branch", "--show-current"]),
            "HEAD": BASE.run_git(["git", "rev-parse", "HEAD"]),
            "origin/dev": BASE.run_git(["git", "rev-parse", "origin/dev"]),
            "status": BASE.run_git(["git", "status", "--short"]),
        },
        "runtime": BASE.runtime_info()["payload"],
        "coverage": plan["coverage"],
        "timing": timing,
        "summary": summaries,
        "explicit_sku_field_matrix": summarize_explicit_matrix(explicit_matrix_records),
        "special_regressions": {
            "total": len(special_records),
            "pass": sum(1 for record in special_records if record["judgement"] == "pass"),
            "warning": sum(1 for record in special_records if record["judgement"] == "warning"),
            "fail": sum(1 for record in special_records if record["judgement"] == "fail"),
        },
        "runner_false_fail_breakdown": {
            "true_fail": sum(1 for record in classified_records if record["judgement"] == "fail" and record.get("audited_attribution") == "real_business"),
            "suspected_runner_false_fail": sum(1 for record in classified_records if record["judgement"] in {"fail", "warning"} and record.get("audited_attribution") == "runner_noise"),
            "field_alias_mismatch": sum(1 for record in classified_records if "field_alias_mismatch" in (record.get("issues") or [])),
            "compound_field_overstrict": sum(1 for record in classified_records if "compound_field_overstrict" in (record.get("issues") or [])),
        },
        "category_list": {
            "total": len(category_records),
            "pass": sum(1 for record in category_records if record["judgement"] == "pass"),
            "warning": sum(1 for record in category_records if record["judgement"] == "warning"),
            "fail": sum(1 for record in category_records if record["judgement"] == "fail"),
        },
        "scenario_recommendation": {
            "total": len(scenario_records),
            "pass": sum(1 for record in scenario_records if record["judgement"] == "pass"),
            "warning": sum(1 for record in scenario_records if record["judgement"] == "warning"),
            "fail": sum(1 for record in scenario_records if record["judgement"] == "fail"),
        },
        "multiturn": {
            "total_sequences": len(multiturn_results),
            "pass": multiturn_sequence_pass,
            "warning": multiturn_sequence_warn,
            "fail": multiturn_sequence_fail,
            "context_break": multiturn_issue_counter["context_break"],
            "pronoun_error": multiturn_issue_counter["pronoun_error"],
            "ordinal_error": multiturn_issue_counter["ordinal_error"],
        },
        "endpoint_parity": {
            "total": len(parity_reports),
            "pass": sum(1 for report in parity_reports if report["equivalent"]),
            "warning": 0,
            "fail": sum(1 for report in parity_reports if not report["equivalent"]),
            "mismatch_cases": parity_mismatch_cases,
        },
        "empty_answer": {
            "count": sum(1 for record in classified_records if record.get("empty_answer")),
        },
        "kb_fallback_unexpected": {
            "count": sum(1 for record in classified_records if record.get("kb_fallback")),
            "cases": [record["case_id"] for record in classified_records if record.get("kb_fallback")][:20],
        },
        "sku_mismatch": {
            "count": sum(1 for record in classified_records if record.get("mismatch")),
            "cases": [record["case_id"] for record in classified_records if record.get("mismatch")][:20],
        },
        "field_wrong": {
            "count": sum(1 for record in classified_records if record.get("field_wrong")),
            "cases": [record["case_id"] for record in classified_records if record.get("field_wrong")][:20],
        },
        "performance": {
            "slow_20s": timing["slow_20s_count"],
            "slow_30s": timing["slow_30s_count"],
            "slow_60s": timing["slow_60s_count"],
            "top_cases": timing["top_10_slowest"],
        },
        "scene_019": scene_019_record,
        "records": classified_records,
        "multiturn_records": multiturn_results,
        "parity_records": parity_reports,
        "explicit_matrix_skus": plan["explicit_matrix_skus"],
    }
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--profile", default="medium", choices=["medium"])
    parser.add_argument("--base-url", default="http://127.0.0.1:8001")
    args = parser.parse_args(argv)

    report = run_medium_full_regression(args.base_url)
    timestamp = time.strftime("%Y%m%d_%H%M%S")
    commit_short = str(report["git"]["HEAD"])[:8]
    json_path = REPORT_DIR / f"full_regression_{commit_short}_{timestamp}.json"
    md_path = REPORT_DIR / f"full_regression_{commit_short}_{timestamp}.md"
    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    md_path.write_text(_markdown_report(report), encoding="utf-8")
    print(json.dumps({"json": str(json_path), "md": str(md_path), "summary": report["summary"]}, ensure_ascii=False, indent=2))
    audited = report["summary"]["audited"]
    return 0 if audited.get("fail", 0) == 0 and audited.get("blocking fail", 0) == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
