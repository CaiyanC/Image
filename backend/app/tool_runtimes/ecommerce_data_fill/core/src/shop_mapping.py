from __future__ import annotations

from pathlib import Path

import yaml


def load_shop_config(path: str | Path) -> dict:
    mapping_path = Path(path)
    if not mapping_path.exists():
        return {"shops": {}}
    with mapping_path.open("r", encoding="utf-8") as fh:
        data = yaml.safe_load(fh) or {}
    if "shops" not in data:
        data["shops"] = {}
    return data


def resolve_shop(raw_store: str, shop_config: dict) -> dict[str, str]:
    raw_store = (raw_store or "").strip()
    shops = shop_config.get("shops", {})
    mapped = shops.get(raw_store)
    if mapped:
        return {
            "raw_store_name": raw_store,
            "platform": mapped.get("platform", raw_store),
            "target_store_name": mapped.get("target_store_name", raw_store),
            "channel_standard": mapped.get("channel_standard", mapped.get("platform", raw_store)),
        }

    if "拼多多" in raw_store:
        platform = "拼多多"
    elif "天猫" in raw_store:
        platform = "天猫"
    elif "京东POP" in raw_store:
        platform = "京东POP"
    elif "京东" in raw_store:
        platform = "京东自营"
    elif any(keyword in raw_store for keyword in ["档口", "商务客户", "经销商", "商务"]):
        platform = "商务部"
    elif "抖音" in raw_store:
        platform = "抖音2店"
    elif "视频号" in raw_store:
        platform = "视频号"
    elif "小红书" in raw_store:
        platform = "小红书"
    elif "得物" in raw_store:
        platform = "得物"
    else:
        platform = "未识别平台"

    return {
        "raw_store_name": raw_store,
        "platform": platform,
        "target_store_name": raw_store,
        "channel_standard": platform,
    }
