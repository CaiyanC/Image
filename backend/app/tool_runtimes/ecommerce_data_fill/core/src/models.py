from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class CycleConfig:
    type: str
    code: str
    start_date: str
    end_date: str


@dataclass
class RuntimeConfig:
    input_dir: Path
    output_dir: Path
    cycle: CycleConfig


@dataclass
class FileEntry:
    path: Path


@dataclass
class ScanResult:
    input_files: list[FileEntry] = field(default_factory=list)
    partial_output_files: list[FileEntry] = field(default_factory=list)


@dataclass
class DetectionResult:
    role: str
    status: str
    matched_sheets: list[str] = field(default_factory=list)
    matched_fields: list[str] = field(default_factory=list)
    missing_fields: list[str] = field(default_factory=list)
    path: Path | None = None
    note: str = ""
    processed_sheets: list[str] = field(default_factory=list)
    skipped_sheets: list[str] = field(default_factory=list)


@dataclass
class Issue:
    level: str
    module: str
    file_role: str
    message: str
    file_name: str = ""
    sheet: str = ""
    row_number: str = ""
    sku: str = ""
    field: str = ""
    target_table: str = ""
    target_field: str = ""
    suggestion: str = ""


@dataclass
class RowWriteEvent:
    sheet_name: str
    row_number: int
    source_file: str
    source_sheet: str
    sku: str
    reason: str
    source_field: str = ""
    source_value: str = ""
    key_values: dict[str, str] = field(default_factory=dict)


@dataclass
class BuildResult:
    rows: list[dict] = field(default_factory=list)
    source_lookup: dict[tuple[str, ...], tuple[str, str]] = field(default_factory=dict)
    audit_rows: list[dict] = field(default_factory=list)
    stats: dict[str, int] = field(default_factory=dict)


@dataclass
class SheetWriteResult:
    workbook_role: str
    sheet_name: str
    written_rows: int
    filled_fields: list[str] = field(default_factory=list)
    blank_fields: list[str] = field(default_factory=list)
    existing_key_count: int = 0
    template_row_writes: int = 0
    appended_row_writes: int = 0
    backfilled_rows: int = 0
    skipped_rows: int = 0
    original_cycle_rows: int = 0
    candidate_rows: int = 0
    raw_candidate_count: int = 0
    skip_zero_sales_count: int = 0
    skip_no_effect_count: int = 0
    candidate_after_filter_count: int = 0
    ended_beyond_template: bool = False
    row_events: list[RowWriteEvent] = field(default_factory=list)
