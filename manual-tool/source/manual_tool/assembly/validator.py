from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from pathlib import Path
from urllib.parse import unquote, urlparse

from .html_parser import heading_level, read_html
from .schema import MAX_STRUCTURE_DEPTH, SCHEMA_VERSION, ManualDefinition, ManualNode


ID_PATTERN = re.compile(r"^[A-Za-z][A-Za-z0-9_-]*$")
ASSET_ATTRIBUTES = (("img", "src"), ("source", "src"), ("video", "poster"), ("script", "src"), ("link", "href"))


@dataclass(frozen=True)
class ValidationIssue:
    code: str
    message: str
    location: str
    severity: str = "ERROR"

    def to_dict(self) -> dict[str, str]:
        return asdict(self)


def _inside(root: Path, target: Path) -> bool:
    try:
        target.relative_to(root)
        return True
    except ValueError:
        return False


def _resolve_relative(root: Path, value: str) -> Path | None:
    path = Path(value)
    if path.is_absolute():
        return None
    target = (root / path).resolve()
    return target if _inside(root.resolve(), target) else None


def _validate_html(path: Path, project_root: Path, depth: int, location: str) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    try:
        part = read_html(path)
    except (OSError, ValueError) as exc:
        return [ValidationIssue("html-parse", f"HTMLを解析できません: {exc}", location)]
    if not part.headings:
        issues.append(ValidationIssue("heading-missing", "HTMLにh1見出しがありません。", location))
        return issues
    if part.headings[0].name != "h1":
        issues.append(ValidationIssue("heading-root", "HTMLの最初の見出しはh1にしてください。", location))
    h1_count = sum(heading.name == "h1" for heading in part.headings)
    if h1_count != 1:
        issues.append(ValidationIssue("heading-h1-count", "HTMLのh1は1つだけにしてください。", location))
    if not part.title:
        issues.append(ValidationIssue("heading-empty", "HTMLのh1タイトルが空です。", location))
    previous = 0
    for index, heading in enumerate(part.headings):
        level = heading_level(heading)
        if index and level > previous + 1:
            issues.append(
                ValidationIssue(
                    "heading-jump",
                    f"見出しレベルがh{previous}からh{level}へ飛んでいます。",
                    location,
                )
            )
        output_level = depth + level
        if output_level > 6:
            issues.append(
                ValidationIssue(
                    "heading-too-deep",
                    f"配置後の見出しがh{output_level}となり、HTMLの上限h6を超えます。",
                    location,
                )
            )
        previous = level

    for tag_name, attribute in ASSET_ATTRIBUTES:
        for tag in part.soup.find_all(tag_name):
            reference = tag.get(attribute)
            if not reference:
                continue
            parsed = urlparse(reference)
            if parsed.scheme or parsed.netloc or reference.startswith(("//", "#")):
                continue
            target = (path.parent / unquote(parsed.path)).resolve()
            if not _inside(project_root, target):
                issues.append(ValidationIssue("asset-outside", f"参照がプロジェクト外です: {reference}", location))
            elif not target.is_file():
                issues.append(ValidationIssue("asset-missing", f"参照ファイルがありません: {reference}", location))
    return issues


def validate_manual(definition: ManualDefinition, yaml_path: Path) -> list[ValidationIssue]:
    yaml_path = yaml_path.resolve()
    project_root = yaml_path.parent
    issues: list[ValidationIssue] = []
    if definition.version != SCHEMA_VERSION:
        issues.append(ValidationIssue("version", f"未対応のSchema versionです: {definition.version}", "version"))
    if not definition.title:
        issues.append(ValidationIssue("manual-title", "マニュアルタイトルを入力してください。", "manual.title"))
    if not definition.chapters:
        issues.append(ValidationIssue("chapters-empty", "マニュアル構成が空です。", "chapters"))
    source_root = _resolve_relative(project_root, definition.source_dir)
    if source_root is None:
        issues.append(ValidationIssue("source-path", "source_dirはYAMLと同じプロジェクト内を指定してください。", "manual.source_dir"))
        return issues
    if not source_root.is_dir():
        issues.append(ValidationIssue("source-missing", f"HTMLフォルダがありません: {definition.source_dir}", "manual.source_dir"))
    output_path = _resolve_relative(project_root, definition.output)
    if output_path is None or output_path.suffix.lower() not in {".html", ".htm"}:
        issues.append(ValidationIssue("output-path", "outputはプロジェクト内のHTMLファイルを指定してください。", "manual.output"))

    used_ids: set[str] = set()
    used_files: set[str] = set()

    def visit(nodes: list[ManualNode], depth: int, prefix: str) -> None:
        for index, node in enumerate(nodes):
            location = f"{prefix}[{index}]"
            if depth > MAX_STRUCTURE_DEPTH:
                issues.append(ValidationIssue("hierarchy-depth", f"構成階層は{MAX_STRUCTURE_DEPTH}階層までです。", location))
            if not node.title:
                issues.append(ValidationIssue("node-title", "タイトルが空です。", f"{location}.title"))
            if not node.id or not ID_PATTERN.fullmatch(node.id):
                issues.append(ValidationIssue("node-id", "IDは英字で始まる英数字・ハイフン・下線で指定してください。", f"{location}.id"))
            elif node.id in used_ids:
                issues.append(ValidationIssue("duplicate-id", f"IDが重複しています: {node.id}", f"{location}.id"))
            else:
                used_ids.add(node.id)
            if not node.file and not node.children:
                issues.append(ValidationIssue("empty-node", "HTMLまたは子要素を指定してください。", location))
            if node.file:
                target = _resolve_relative(source_root, node.file)
                if target is None:
                    issues.append(ValidationIssue("file-outside", f"HTMLフォルダ外のファイルは指定できません: {node.file}", f"{location}.file"))
                else:
                    normalized = str(target).casefold()
                    if normalized in used_files:
                        issues.append(ValidationIssue("duplicate-file", f"同じHTMLが重複登録されています: {node.file}", f"{location}.file"))
                    else:
                        used_files.add(normalized)
                    if not target.is_file():
                        issues.append(ValidationIssue("file-missing", f"HTMLがありません: {node.file}", f"{location}.file"))
                    elif target.suffix.lower() not in {".html", ".htm"}:
                        issues.append(ValidationIssue("file-type", f"HTMLではありません: {node.file}", f"{location}.file"))
                    else:
                        issues.extend(_validate_html(target, project_root, depth, f"{location}.file"))
            visit(node.children, depth + 1, f"{location}.children")

    visit(definition.chapters, 1, "chapters")
    if output_path is not None and str(output_path).casefold() in used_files:
        issues.append(
            ValidationIssue(
                "output-conflicts-source",
                "outputは構成に登録した入力HTMLとは別のファイルを指定してください。",
                "manual.output",
            )
        )
    return issues
