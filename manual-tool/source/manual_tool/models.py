from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Literal


@dataclass(frozen=True)
class Issue:
    id: str
    rule: str
    level: Literal["ERROR", "WARNING", "INFO"]
    line: int
    message: str
    suggestion: str | None = None
    replacement: str | None = None

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class ProcessResult:
    source_path: Path
    output_dir: Path
    markdown_path: Path
    fixed_markdown_path: Path
    html_path: Path
    report_path: Path
    issues: tuple[Issue, ...]

    @property
    def error_count(self) -> int:
        return sum(issue.level == "ERROR" for issue in self.issues)

    @property
    def warning_count(self) -> int:
        return sum(issue.level == "WARNING" for issue in self.issues)
