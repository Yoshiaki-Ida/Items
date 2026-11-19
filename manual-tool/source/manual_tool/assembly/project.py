from __future__ import annotations

import re
import uuid
from dataclasses import dataclass
from pathlib import Path

from .html_parser import read_html, strip_heading_number


IGNORED_DIRECTORIES = {".git", ".venv", "__pycache__", ".pytest_cache", "node_modules", "output"}


@dataclass(frozen=True)
class HtmlSource:
    file: str
    title: str
    suggested_id: str
    direct_heading_count: int = 0

    def to_dict(self) -> dict[str, str | int]:
        return {
            "file": self.file,
            "title": self.title,
            "suggested_id": self.suggested_id,
            "direct_heading_count": self.direct_heading_count,
        }


@dataclass
class CompositionProject:
    id: str
    source_dir: Path
    yaml_path: Path | None = None
    save_path: Path | None = None

    def sources(self) -> list[HtmlSource]:
        return discover_html(self.source_dir)

    def resolve_source(self, relative_path: str) -> Path:
        target = (self.source_dir / Path(relative_path)).resolve()
        try:
            target.relative_to(self.source_dir)
        except ValueError as exc:
            raise ValueError("HTMLフォルダ外のファイルは開けません。") from exc
        if not target.is_file() or target.suffix.lower() not in {".html", ".htm"}:
            raise FileNotFoundError("HTMLファイルが見つかりません。")
        return target

    def resolve_asset(self, relative_path: str) -> Path:
        target = (self.source_dir / Path(relative_path)).resolve()
        try:
            target.relative_to(self.source_dir)
        except ValueError as exc:
            raise ValueError("HTMLフォルダ外のファイルは開けません。") from exc
        if not target.is_file():
            raise FileNotFoundError("参照ファイルが見つかりません。")
        return target


class CompositionProjectStore:
    def __init__(self):
        self._projects: dict[str, CompositionProject] = {}

    def create(
        self,
        source_dir: Path,
        yaml_path: Path | None = None,
        save_path: Path | None = None,
    ) -> CompositionProject:
        root = source_dir.resolve()
        if not root.is_dir():
            raise NotADirectoryError(f"HTMLフォルダが見つかりません: {root}")
        project = CompositionProject(
            uuid.uuid4().hex,
            root,
            yaml_path.resolve() if yaml_path is not None else None,
            save_path.resolve() if save_path is not None else None,
        )
        self._projects[project.id] = project
        return project

    def get(self, project_id: str) -> CompositionProject:
        try:
            return self._projects[project_id]
        except KeyError as exc:
            raise KeyError("マニュアル編集プロジェクトが見つかりません。フォルダを開き直してください。") from exc


def stable_id(value: str, fallback: str = "section") -> str:
    ascii_value = re.sub(r"[^a-z0-9]+", "-", value.casefold()).strip("-")
    if ascii_value:
        return ascii_value
    digest = sum((index + 1) * ord(character) for index, character in enumerate(value))
    return f"{fallback}-{digest:08x}"


def discover_html(source_dir: Path) -> list[HtmlSource]:
    root = source_dir.resolve()
    if not root.is_dir():
        raise NotADirectoryError(f"HTMLフォルダが見つかりません: {root}")
    discovered: list[HtmlSource] = []
    used_ids: set[str] = set()
    for path in root.iterdir():
        relative = path.relative_to(root)
        if path.name in IGNORED_DIRECTORIES:
            continue
        if not path.is_file() or path.suffix.lower() not in {".html", ".htm"}:
            continue
        try:
            part = read_html(path)
            title = strip_heading_number(part.title) or path.stem
            direct_heading_count = sum(heading.name == "h2" for heading in part.headings)
        except ValueError:
            title = path.stem
            direct_heading_count = 0
        base_id = stable_id(path.stem, "part")
        candidate = base_id
        suffix = 2
        while candidate in used_ids:
            candidate = f"{base_id}-{suffix}"
            suffix += 1
        used_ids.add(candidate)
        discovered.append(HtmlSource(relative.as_posix(), title, candidate, direct_heading_count))
    return sorted(discovered, key=lambda item: item.file.casefold())
