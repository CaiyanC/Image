from __future__ import annotations

import shutil
from pathlib import Path


def copy_workbook(base_path: Path, output_path: Path) -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    if base_path.resolve() == output_path.resolve():
        return output_path
    shutil.copy2(base_path, output_path)
    return output_path
