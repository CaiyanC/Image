from __future__ import annotations

from pathlib import Path

from src.models import FileEntry, ScanResult


def _sorted_excel_files(directory: Path, recursive: bool = False) -> list[FileEntry]:
    candidates = directory.rglob("*.xls*") if recursive else directory.glob("*.xls*")
    return [
        FileEntry(path=p)
        for p in sorted(candidates)
        if p.is_file() and not p.name.startswith("~$")
    ]


def scan_excel_files(input_dir: Path, output_dir: Path, recursive: bool = False) -> ScanResult:
    partials = [
        FileEntry(path=p)
        for p in sorted(output_dir.glob("*_部分填报.xlsx"))
        if p.is_file()
    ]
    return ScanResult(
        input_files=_sorted_excel_files(input_dir, recursive=recursive),
        partial_output_files=partials,
    )
