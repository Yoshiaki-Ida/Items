from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


SCHEMA_VERSION = 1
MAX_STRUCTURE_DEPTH = 3


@dataclass
class ManualNode:
    id: str
    title: str
    file: str | None = None
    numbered: bool = True
    children: list["ManualNode"] = field(default_factory=list)

    @classmethod
    def from_mapping(cls, data: Any, location: str = "chapters") -> "ManualNode":
        if not isinstance(data, dict):
            raise ValueError(f"{location}はオブジェクトで指定してください。")
        children_data = data.get("children", [])
        if children_data is None:
            children_data = []
        if not isinstance(children_data, list):
            raise ValueError(f"{location}.childrenは配列で指定してください。")
        return cls(
            id=str(data.get("id", "")).strip(),
            title=str(data.get("title", "")).strip(),
            file=str(data["file"]).strip().replace("\\", "/") if data.get("file") else None,
            numbered=data.get("numbered", True) is not False,
            children=[
                cls.from_mapping(child, f"{location}.children[{index}]")
                for index, child in enumerate(children_data)
            ],
        )

    def to_mapping(self) -> dict[str, Any]:
        result: dict[str, Any] = {"id": self.id, "title": self.title}
        if self.file:
            result["file"] = self.file
        if not self.numbered:
            result["numbered"] = False
        if self.children:
            result["children"] = [child.to_mapping() for child in self.children]
        return result


@dataclass
class ManualDefinition:
    title: str
    source_dir: str = "source"
    output: str = "output/manual.html"
    chapters: list[ManualNode] = field(default_factory=list)
    version: int = SCHEMA_VERSION

    @classmethod
    def from_mapping(cls, data: Any) -> "ManualDefinition":
        if not isinstance(data, dict):
            raise ValueError("YAMLのルートはオブジェクトで指定してください。")
        manual = data.get("manual")
        chapters = data.get("chapters")
        if not isinstance(manual, dict):
            raise ValueError("manual設定がありません。")
        if not isinstance(chapters, list):
            raise ValueError("chaptersは配列で指定してください。")
        version = data.get("version", SCHEMA_VERSION)
        if not isinstance(version, int):
            raise ValueError("versionは整数で指定してください。")
        return cls(
            title=str(manual.get("title", "")).strip(),
            source_dir=str(manual.get("source_dir", "source")).strip().replace("\\", "/"),
            output=str(manual.get("output", "output/manual.html")).strip().replace("\\", "/"),
            chapters=[ManualNode.from_mapping(item, f"chapters[{index}]") for index, item in enumerate(chapters)],
            version=version,
        )

    def to_mapping(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "manual": {
                "title": self.title,
                "source_dir": self.source_dir,
                "output": self.output,
            },
            "chapters": [chapter.to_mapping() for chapter in self.chapters],
        }


def load_manual(path: Path) -> ManualDefinition:
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except UnicodeDecodeError as exc:
        raise ValueError("manual.yamlはUTF-8で保存してください。") from exc
    except yaml.YAMLError as exc:
        raise ValueError(f"YAMLを解析できません: {exc}") from exc
    return ManualDefinition.from_mapping(data)


def save_manual(path: Path, definition: ManualDefinition) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        yaml.safe_dump(definition.to_mapping(), allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
