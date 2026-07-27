from __future__ import annotations

from dataclasses import dataclass


@dataclass
class GuiFileSlot:
    role: str
    label: str
    required: bool
    file_name: str
    status_text: str


@dataclass
class GuiReviewItem:
    result_table: str
    sheet_name: str
    result_location_text: str
    source_location_text: str
    field_text: str
    reason_text: str
    action_text: str
