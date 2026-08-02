"""Original desktop workflow roles and browser precheck helpers."""

from __future__ import annotations


WORKFLOW_ROLE_ORDER: dict[str, tuple[str, ...]] = {
    "ecommerce": (
        "w27_target",
        "sales_theme_analysis",
        "sales_30d",
        "product_archive",
        "jd_amazon_inventory",
        "jd_self_weekly_sales",
    ),
    "kepule": (
        "kepule_target",
        "domestic_sales_theme_analysis",
        "domestic_sales_ranking",
        "cross_border_profit_sku",
        "product_archive",
        "jd_amazon_inventory",
        "jd_self_weekly_sales",
    ),
    "amazon": (
        "amazon_inventory_target",
        "amazon_inventory_weekly",
        "fba_inventory",
    ),
}

ROLE_LABELS = {
    "w27_target": "W27 电商数据分析表目标模板",
    "kepule_target": "周月报目标模板",
    "amazon_inventory_target": "亚马逊库存目标模板",
    "amazon_inventory_weekly": "亚马逊库存每周更新",
    "fba_inventory": "FBA 库存明细",
    "sales_theme_analysis": "销售主题分析",
    "sales_30d": "近 30 天销售数据",
    "product_archive": "产品档案",
    "jd_amazon_inventory": "京东/亚马逊库存",
    "jd_self_weekly_sales": "京东自营周销",
    "domestic_sales_theme_analysis": "国内销售主题分析",
    "domestic_sales_ranking": "国内销售排名",
    "cross_border_profit_sku": "跨境利润 SKU 数据",
}


def build_precheck(mode: str, recognized_roles: set[str]) -> dict:
    if mode not in WORKFLOW_ROLE_ORDER:
        raise ValueError("Unsupported spreadsheet workflow")
    role_order = WORKFLOW_ROLE_ORDER[mode]
    required_roles = set(role_order) if mode == "amazon" else {role_order[0]}
    missing_required = [role for role in role_order if role in required_roles and role not in recognized_roles]
    missing_optional = [role for role in role_order if role not in required_roles and role not in recognized_roles]
    return {
        "mode": mode,
        "can_run": not missing_required,
        "required_roles": [role for role in role_order if role in required_roles],
        "missing_required_roles": missing_required,
        "missing_optional_roles": missing_optional,
        "slots": [
            {
                "role": role,
                "label": ROLE_LABELS.get(role, role),
                "required": role in required_roles,
                "recognized": role in recognized_roles,
            }
            for role in role_order
        ],
    }
