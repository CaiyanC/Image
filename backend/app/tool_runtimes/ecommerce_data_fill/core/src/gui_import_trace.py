from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path


def write_import_trace(
    app_dir: Path,
    *,
    action: str,
    selected_path: str,
    scanned_count: int,
    accepted_count: int,
) -> Path:
    """Append a compact, user-readable record of a GUI import action."""

    trace_path = app_dir / "logs" / "gui_import.log"
    trace_path.parent.mkdir(parents=True, exist_ok=True)
    record = {
        "time": datetime.now().isoformat(timespec="seconds"),
        "action": action,
        "selected_path": selected_path,
        "scanned_count": scanned_count,
        "accepted_count": accepted_count,
    }
    with trace_path.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(record, ensure_ascii=False) + "\n")
    return trace_path
