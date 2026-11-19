from __future__ import annotations

import uuid
from dataclasses import dataclass
from pathlib import Path

from .converter import SUPPORTED_EXTENSIONS


IGNORED_DIRECTORIES = {".git", ".venv", "__pycache__", ".pytest_cache", "node_modules"}


@dataclass(frozen=True)
class Workspace:
    id: str
    root: Path

    def files(self) -> list[str]:
        results: list[str] = []
        for candidate in self.root.iterdir():
            if candidate.name in IGNORED_DIRECTORIES:
                continue
            if candidate.is_file() and candidate.suffix.lower() in SUPPORTED_EXTENSIONS:
                results.append(candidate.name)
        return sorted(results, key=str.casefold)

    def resolve_file(self, relative_path: str) -> Path:
        relative = Path(relative_path)
        target = (self.root / relative).resolve()
        try:
            target.relative_to(self.root)
        except ValueError as exc:
            raise ValueError("ワークスペース外のファイルは開けません。") from exc
        if len(relative.parts) != 1:
            raise FileNotFoundError("対応する文書が見つかりません。")
        if not target.is_file() or target.suffix.lower() not in SUPPORTED_EXTENSIONS:
            raise FileNotFoundError("対応する文書が見つかりません。")
        return target


class WorkspaceStore:
    def __init__(self):
        self._workspaces: dict[str, Workspace] = {}

    def create(self, root: Path) -> Workspace:
        resolved = root.resolve()
        if not resolved.is_dir():
            raise NotADirectoryError(f"フォルダが見つかりません: {resolved}")
        workspace = Workspace(uuid.uuid4().hex, resolved)
        self._workspaces[workspace.id] = workspace
        return workspace

    def get(self, workspace_id: str) -> Workspace:
        try:
            return self._workspaces[workspace_id]
        except KeyError as exc:
            raise KeyError("ワークスペースが見つかりません。フォルダを開き直してください。") from exc
