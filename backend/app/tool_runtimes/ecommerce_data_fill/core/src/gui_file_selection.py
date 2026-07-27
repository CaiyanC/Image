from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class ImportedFileSelection:
    """Persistent file selection for a single GUI run."""

    files: list[Path] = field(default_factory=list)
    unavailable_files: list[Path] = field(default_factory=list)

    def add(self, candidates: list[Path]) -> int:
        known_paths = {path.resolve() for path in [*self.files, *self.unavailable_files]}
        added = 0
        for path in candidates:
            if path.resolve() in known_paths:
                continue
            if path.exists():
                self.files.append(path)
            else:
                self.unavailable_files.append(path)
            known_paths.add(path.resolve())
            added += 1
        return added

    def remove(self, path: Path) -> None:
        selected_path = path.resolve()
        self.files[:] = [item for item in self.files if item.resolve() != selected_path]
        self.unavailable_files[:] = [item for item in self.unavailable_files if item.resolve() != selected_path]

    def clear(self) -> None:
        self.files.clear()
        self.unavailable_files.clear()
