from __future__ import annotations

import json
import shutil
import tempfile
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path

from .models import Issue


@dataclass
class DocumentSession:
    id: str
    filename: str
    directory: Path
    markdown: str
    issues: list[Issue] = field(default_factory=list)
    ignored: set[str] = field(default_factory=set)
    workspace_id: str | None = None
    relative_path: str | None = None


class SessionStore:
    def __init__(self, root: Path | None = None, max_age_seconds: int = 24 * 60 * 60):
        self.root = root or Path(tempfile.gettempdir()) / "manual-tool"
        self.root.mkdir(parents=True, exist_ok=True)
        self._sessions: dict[str, DocumentSession] = {}
        self.cleanup_expired(max_age_seconds)

    @staticmethod
    def _is_session_directory(path: Path) -> bool:
        try:
            return path.is_dir() and uuid.UUID(path.name).hex == path.name.lower()
        except ValueError:
            return False

    def cleanup_expired(self, max_age_seconds: int) -> None:
        cutoff = time.time() - max(0, max_age_seconds)
        for candidate in self.root.iterdir():
            try:
                if self._is_session_directory(candidate) and candidate.stat().st_mtime < cutoff:
                    shutil.rmtree(candidate)
            except OSError:
                continue

    def create(
        self,
        filename: str,
        markdown: str,
        *,
        workspace_id: str | None = None,
        relative_path: str | None = None,
    ) -> DocumentSession:
        session_id = uuid.uuid4().hex
        directory = self.root / session_id
        directory.mkdir(parents=True)
        session = DocumentSession(
            session_id,
            filename,
            directory,
            markdown,
            workspace_id=workspace_id,
            relative_path=relative_path,
        )
        self._sessions[session_id] = session
        self.save(session)
        return session

    def get(self, session_id: str) -> DocumentSession:
        try:
            return self._sessions[session_id]
        except KeyError as exc:
            raise KeyError("セッションが見つかりません。ファイルを再度開いてください。") from exc

    def delete(self, session_id: str) -> None:
        try:
            session = self._sessions.pop(session_id)
        except KeyError as exc:
            raise KeyError("セッションが見つかりません。ファイルを再度開いてください。") from exc
        shutil.rmtree(session.directory, ignore_errors=True)

    def save(self, session: DocumentSession) -> None:
        (session.directory / "working.md").write_text(session.markdown, encoding="utf-8")
        (session.directory / "session.json").write_text(
            json.dumps(
                {
                    "id": session.id,
                    "filename": session.filename,
                    "ignored": sorted(session.ignored),
                    "workspace_id": session.workspace_id,
                    "relative_path": session.relative_path,
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
