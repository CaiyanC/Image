from __future__ import annotations

from pathlib import Path

from src.gui_models import GuiFileSlot, GuiReviewItem
from src.models import Issue
from src.validators import MANDATORY_TARGET_ROLES, PRIMARY_SOURCE_ROLES, role_display_name


OPTIONAL_GUI_ROLES: list[str] = []
GUI_ROLE_ORDER = [*MANDATORY_TARGET_ROLES, *PRIMARY_SOURCE_ROLES, *OPTIONAL_GUI_ROLES]
REQUIRED_GUI_ROLES = set(MANDATORY_TARGET_ROLES) | set(PRIMARY_SOURCE_ROLES)
AMAZON_INVENTORY_ROLES = ["amazon_inventory_target", "amazon_inventory_weekly", "fba_inventory"]
RESULT_TABLE_LABELS = {
    "W27": "W27周电商数据分析表",
    "开普乐": "开普乐周月报统一数据源",
}


def build_gui_file_slots(
    role_files: dict[str, Path],
    *,
    role_order: list[str] | tuple[str, ...] | None = None,
    required_roles: set[str] | None = None,
) -> list[GuiFileSlot]:
    slots: list[GuiFileSlot] = []
    if role_order is None:
        role_order = AMAZON_INVENTORY_ROLES if set(AMAZON_INVENTORY_ROLES) & set(role_files) else GUI_ROLE_ORDER
    if required_roles is None:
        required_roles = set(AMAZON_INVENTORY_ROLES) if list(role_order) == AMAZON_INVENTORY_ROLES else REQUIRED_GUI_ROLES
    for role in role_order:
        path = role_files.get(role)
        slots.append(
            GuiFileSlot(
                role=role,
                label=role_display_name(role),
                required=role in required_roles,
                file_name=path.name if path else "",
                status_text="已识别" if path else "未找到",
            )
        )
    return slots


def split_gui_file_slots(slots: list[GuiFileSlot]) -> tuple[list[GuiFileSlot], list[GuiFileSlot]]:
    target_roles = set(MANDATORY_TARGET_ROLES)
    if any(slot.role == "amazon_inventory_target" for slot in slots):
        target_roles = {"amazon_inventory_target"}
    target_slots = [slot for slot in slots if slot.role in target_roles]
    source_slots = [slot for slot in slots if slot.role not in target_roles]
    return target_slots, source_slots


def split_preflight_issues(issues: list[Issue]) -> tuple[list[str], list[str]]:
    required_items: list[str] = []
    optional_items: list[str] = []
    for issue in issues:
        if issue.file_role in REQUIRED_GUI_ROLES or issue.level == "ERROR":
            required_items.append(issue.message)
        else:
            optional_items.append(issue.message)
    return required_items, optional_items


def build_gui_review_items(issues: list[Issue]) -> list[GuiReviewItem]:
    items: list[GuiReviewItem] = []
    for issue in issues:
        if "人工复核" not in issue.message and "人工确认" not in issue.suggestion:
            continue
        items.append(
            GuiReviewItem(
                result_table=RESULT_TABLE_LABELS.get(issue.target_table, issue.target_table or "结果表"),
                sheet_name=issue.target_field or "待确认",
                result_location_text=f"SKU {issue.sku}" if issue.sku else "请查看异常清单",
                source_location_text=f"{issue.file_name or '来源表待确认'} / {issue.sheet or 'Sheet待确认'} / 行{issue.row_number or '待确认'}",
                field_text=issue.field or "待确认字段",
                reason_text=issue.message,
                action_text=issue.suggestion or "请打开结果表和来源表核对。",
            )
        )
    return items


def build_gui_review_items_from_rows(rows: list[dict[str, str]]) -> list[GuiReviewItem]:
    items: list[GuiReviewItem] = []
    for row in rows:
        sku = str(row.get("SKU", "") or "").strip()
        field_text = str(row.get("字段", "") or row.get("异常字段", "") or "").strip() or "待确认字段"
        items.append(
            GuiReviewItem(
                result_table=str(row.get("结果表", "") or row.get("影响目标表", "") or "结果文件"),
                sheet_name=str(row.get("结果Sheet", "") or row.get("影响目标字段", "") or row.get("Sheet", "") or "请查看建议人工核对"),
                result_location_text=str(row.get("结果定位", "") or row.get("定位信息", "") or (f"SKU {sku}" if sku else "请查看建议人工核对")),
                source_location_text=str(row.get("来源定位", "") or "请查看来源表定位"),
                field_text=str(row.get("结果字段", "") or field_text),
                reason_text=str(row.get("异常说明", "") or "请结合结果表人工确认。"),
                action_text=str(row.get("建议核对动作", "") or "请打开结果文件和来源文件核对。"),
            )
        )
    return items
