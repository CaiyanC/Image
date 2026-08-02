from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path

import yaml

from src.models import CycleConfig, RuntimeConfig


DEFAULT_CYCLE_TYPE = "周"
DEFAULT_CYCLE_CODE = "2026W27"
DEFAULT_START_DATE = "2026-06-29"
DEFAULT_END_DATE = "2026-07-05"
DEFAULT_INVENTORY_DATE = "2026-06-29"
DEFAULT_KEPULE_SALES_DATE = "2026-07-05"
DEFAULT_KEPULE_INVENTORY_DATE = "2026-06-29"


@dataclass
class FillConfig:
    cycle_type: str
    cycle_code: str
    start_date: str
    end_date: str
    inventory_date: str
    kepule_sales_date: str
    kepule_inventory_date: str
    source_map: dict[str, str]


def normalize_date_value(value: str | date | datetime, field_name: str = "日期") -> str:
    """Convert supported user/config date input to the single format used by Excel writers."""
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()

    text = str(value or "").strip()
    formats = ("%Y-%m-%d", "%Y/%m/%d", "%Y.%m.%d", "%Y%m%d", "%Y年%m月%d日")
    for fmt in formats:
        try:
            return datetime.strptime(text, fmt).date().isoformat()
        except ValueError:
            continue
    raise ValueError(f"{field_name}无效：请填写真实的年、月、日。")


def normalize_cycle_type(value: str | None) -> str:
    """Keep CLI/config aliases internal while writing the template's Chinese label."""
    text = str(value or "").strip()
    aliases = {
        "weekly": "周",
        "week": "周",
        "周": "周",
        "monthly": "月",
        "month": "月",
        "月": "月",
    }
    return aliases.get(text.lower(), text or DEFAULT_CYCLE_TYPE)


def build_runtime_config(
    input_dir: str | Path,
    output_dir: str | Path,
    cycle_type: str | None,
    cycle_code: str | None,
    start_date: str | None,
    end_date: str | None,
) -> RuntimeConfig:
    return RuntimeConfig(
        input_dir=Path(input_dir),
        output_dir=Path(output_dir),
        cycle=CycleConfig(
            type=normalize_cycle_type(cycle_type),
            code=cycle_code or DEFAULT_CYCLE_CODE,
            start_date=start_date or DEFAULT_START_DATE,
            end_date=end_date or DEFAULT_END_DATE,
        ),
    )


def load_fill_rules(path: str | Path) -> dict:
    rules_path = Path(path)
    if not rules_path.exists():
        return {}
    with rules_path.open("r", encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}


def resolve_fill_config(
    cli_values: dict[str, str | None],
    rule_values: dict,
    inferred_values: dict[str, str | None],
) -> FillConfig:
    period = rule_values.get("period", {})
    inventory = rule_values.get("inventory", {})
    kepule = rule_values.get("kepule", {})
    source_map: dict[str, str] = {}

    def pick(name: str, rule_value: str | None, inferred_value: str | None, default_value: str) -> str:
        cli_value = cli_values.get(name)
        if cli_value:
            source_map[name] = "cli"
            return cli_value
        if rule_value:
            source_map[name] = "config"
            return rule_value
        if inferred_value:
            source_map[name] = "inferred"
            return inferred_value
        source_map[name] = "default"
        return default_value

    date_values = {
        "start_date": pick("start_date", period.get("start_date"), inferred_values.get("start_date"), DEFAULT_START_DATE),
        "end_date": pick("end_date", period.get("end_date"), inferred_values.get("end_date"), DEFAULT_END_DATE),
        "inventory_date": pick("inventory_date", inventory.get("snapshot_date"), inferred_values.get("inventory_date"), DEFAULT_INVENTORY_DATE),
        "kepule_sales_date": pick("kepule_sales_date", kepule.get("sales_date"), inferred_values.get("kepule_sales_date"), DEFAULT_KEPULE_SALES_DATE),
        "kepule_inventory_date": pick("kepule_inventory_date", kepule.get("inventory_date"), inferred_values.get("kepule_inventory_date"), DEFAULT_KEPULE_INVENTORY_DATE),
    }
    return FillConfig(
        cycle_type=normalize_cycle_type(
            pick("cycle_type", period.get("cycle_type"), inferred_values.get("cycle_type"), DEFAULT_CYCLE_TYPE)
        ),
        cycle_code=pick("cycle_code", period.get("cycle_code"), inferred_values.get("cycle_code"), DEFAULT_CYCLE_CODE),
        start_date=normalize_date_value(date_values["start_date"], "开始日期"),
        end_date=normalize_date_value(date_values["end_date"], "结束日期"),
        inventory_date=normalize_date_value(date_values["inventory_date"], "库存快照日期"),
        kepule_sales_date=normalize_date_value(date_values["kepule_sales_date"], "开普乐销售日期"),
        kepule_inventory_date=normalize_date_value(date_values["kepule_inventory_date"], "开普乐库存日期"),
        source_map=source_map,
    )
