from __future__ import annotations

from pathlib import Path

from src.models import DetectionResult, Issue


ROLE_DISPLAY_NAMES = {
    "amazon_inventory_target": "亚马逊最新库存明细表目标模板",
    "amazon_inventory_weekly": "亚马逊库存每周更新",
    "w27_target": "W27周电商数据分析表目标模板",
    "kepule_target": "开普乐周月报统一数据源目标模板",
    "product_archive": "商品档案",
    "sales_theme_analysis": "四个平台销售分析表",
    "sales_30d": "30天销售主题",
    "jd_self_weekly_sales": "京东自营周度销售件数统计",
    "jd_amazon_inventory": "自营京东仓及亚马逊库存（京东自营库存/在途/近30天销量）",
    "domestic_sales_theme_analysis": "国内平台销售多维分析",
    "cross_border_profit_sku": "跨境订单利润SKU",
    "amazon_latest_inventory": "亚马逊库存明细",
    "fba_inventory": "FBA仓库明细（亚马逊FBA库存）",
    "domestic_sales_ranking": "国内销售排行",
}

MANDATORY_TARGET_ROLES = ["w27_target", "kepule_target"]
PRIMARY_SOURCE_ROLES = [
    "product_archive",
    "sales_theme_analysis",
    "sales_30d",
    "jd_self_weekly_sales",
    "jd_amazon_inventory",
    "domestic_sales_theme_analysis",
    "cross_border_profit_sku",
    "amazon_latest_inventory",
    "fba_inventory",
    "domestic_sales_ranking",
]


def role_display_name(role: str) -> str:
    return ROLE_DISPLAY_NAMES.get(role, role)


def validate_required_roles(detections: dict[str, DetectionResult], reusable_targets: dict[str, Path]) -> list[Issue]:
    issues: list[Issue] = []
    for role in MANDATORY_TARGET_ROLES:
        if role not in detections and role not in reusable_targets:
            issues.append(
                Issue(
                    level="ERROR",
                    module="validator",
                    file_role=role,
                    message=f"缺少“{role_display_name(role)}”",
                    target_table=role,
                    suggestion="补充目标表后重新运行。",
                )
            )
    for role in PRIMARY_SOURCE_ROLES:
        if role not in detections:
            issues.append(
                Issue(
                    level="WARNING",
                    module="validator",
                    file_role=role,
                    message=f"缺少“{role_display_name(role)}”来源文件",
                    target_table="W27 / 开普乐",
                    suggestion="补充来源表后重新运行，可从部分填报继续补填。",
                )
            )
    return issues


def issue_requires_manual_review(issue: Issue) -> bool:
    return "人工复核" in issue.message or "人工确认" in issue.suggestion


def issue_blocks_core_fill(issue: Issue) -> bool:
    if issue.level == "ERROR":
        return True
    # A supplier is a traceability attribute in the Kepule inventory snapshot,
    # not a value used to calculate inventory or sales. When the authoritative
    # source leaves it blank, the builder records a warning and deliberately
    # leaves the channel blank rather than fabricating “国内仓”. This must remain
    # visible in the exception report, but it must not label an otherwise
    # completed two-table run as a core-fill failure.
    if (
        issue.level == "WARNING"
        and issue.target_table == "开普乐"
        and issue.target_field == "源_库存快照"
        and issue.field == "供应商"
        and issue.message == "国内库存供应商缺失，未伪造供应商"
    ):
        return False
    if issue.level == "WARNING" and not issue_requires_manual_review(issue):
        return True
    return False


def determine_status_details(issues: list[Issue]) -> dict[str, object]:
    has_blocking_issue = any(issue_blocks_core_fill(issue) for issue in issues)
    review_issues = [issue for issue in issues if issue_requires_manual_review(issue)]
    if has_blocking_issue:
        public_status = "FAILED"
        core_fill_status = "未完成核心填表"
    elif review_issues:
        public_status = "SUCCESS_WITH_REVIEW"
        core_fill_status = "已完成核心填表"
    else:
        public_status = "SUCCESS"
        core_fill_status = "已完成核心填表"
    return {
        "status": public_status,
        "core_fill_completed": not has_blocking_issue,
        "core_fill_status": core_fill_status,
        "has_manual_review": bool(review_issues),
        "manual_review_count": len(review_issues),
        "review_issues": review_issues,
    }


def determine_status(issues: list[Issue]) -> str:
    return str(determine_status_details(issues)["status"])
