from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import Any

from .converter import HEADING_NUMBER
from .models import Issue


def load_rules(path: Path) -> dict[str, Any]:
    import yaml

    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"ルールファイルの形式が不正です: {path}")
    return data


def _issue(rule: str, level: str, line: int, message: str, **kwargs) -> Issue:
    digest = hashlib.sha1(f"{rule}\0{line}\0{message}".encode("utf-8")).hexdigest()[:12]
    return Issue(f"{rule}:{line}:{digest}", rule, level, line, message, **kwargs)


def _content_lines(lines: list[str]):
    in_code = False
    for number, line in enumerate(lines, 1):
        if line.strip().startswith("```"):
            in_code = not in_code
            continue
        if not in_code:
            yield number, line


def _heading_title_without_number(title: str) -> str:
    match = HEADING_NUMBER.match(title)
    return match.group("title").strip() if match else title


def lint_text(text: str, rules: dict[str, Any]) -> list[Issue]:
    lines = text.splitlines()
    content = list(_content_lines(lines))
    issues: list[Issue] = []
    headings: list[tuple[int, int, str]] = []
    previous = 0

    for number, line in content:
        match = re.match(r"^(#{1,6})\s*(.*?)\s*$", line)
        if not match:
            continue
        level, title = len(match.group(1)), match.group(2).strip()
        headings.append((number, level, _heading_title_without_number(title)))
        if not title:
            issues.append(_issue("empty-heading", "ERROR", number, "空の見出しがあります。"))
        if previous and level > previous + 1:
            replacement = f"{'#' * (previous + 1)} {title}"
            issues.append(
                _issue(
                    "heading-jump",
                    "WARNING",
                    number,
                    f"見出しがH{previous}からH{level}へ飛んでいます。",
                    suggestion=replacement,
                    replacement=replacement,
                )
            )
        previous = level

    for required in rules.get("required_sections", []):
        expected_level, title = int(required["level"]), str(required["title"])
        if any(heading[1:] == (expected_level, title) for heading in headings):
            continue
        same_title = next((heading for heading in headings if heading[2] == title), None)
        if same_title:
            replacement = f"{'#' * expected_level} {title}"
            issues.append(
                _issue(
                    "required-level",
                    "ERROR",
                    same_title[0],
                    f"「{title}」はH{expected_level}で記載してください。",
                    suggestion=replacement,
                    replacement=replacement,
                )
            )
        else:
            issues.append(_issue("required-section", "ERROR", 0, f"必須章「{'#' * expected_level} {title}」がありません。"))

    for index in range(len(lines) - 1):
        header, separator = lines[index].strip(), lines[index + 1].strip()
        if "|" in header and re.match(r"^\|?\s*:?-{3,}:?\s*(\|\s*:?-{3,}:?\s*)+\|?$", separator):
            split = lambda row: row.strip().strip("|").split("|")
            if len(split(header)) != len(split(separator)):
                issues.append(_issue("table-columns", "ERROR", index + 2, "Markdown表の列数が一致しません。"))

    limit = int(rules.get("long_line_limit", 120))
    for number, line in content:
        stripped = line.strip()
        if not stripped or stripped.startswith(("|", "<")):
            continue
        if line.count("[") != line.count("]") or line.count("(") != line.count(")"):
            issues.append(_issue("brackets", "WARNING", number, "リンクまたは括弧の対応を確認してください。"))
        if len(stripped) > limit:
            issues.append(_issue("long-line", "WARNING", number, f"1行が{limit}文字を超えています。"))
        for word in rules.get("ambiguous_words", []):
            if word in line:
                issues.append(_issue("ambiguous", "WARNING", number, f"曖昧表現「{word}」があります。"))
        for old, new in rules.get("preferred_terms", {}).items():
            if old in line:
                replacement = line.replace(old, new)
                issues.append(
                    _issue(
                        "preferred-term",
                        "INFO",
                        number,
                        f"「{old}」は「{new}」へ統一できます。",
                        suggestion=new,
                        replacement=replacement,
                    )
                )

    for marker in rules.get("remove_block_marker_patterns", []):
        pattern = re.compile(marker["pattern"])
        found = [(number, match) for number, line in content for match in pattern.finditer(line)]
        if len(found) % 2:
            issues.append(_issue("marker-pair", "WARNING", found[0][0], f"{marker['name']}の開始・終了数が一致しません。"))
    return sorted(issues, key=lambda item: (item.line, item.level, item.rule))


def apply_issue(text: str, issue: Issue) -> str:
    if issue.line <= 0 or issue.replacement is None:
        raise ValueError("この指摘には自動修正候補がありません。")
    lines = text.splitlines(keepends=True)
    index = issue.line - 1
    if index >= len(lines):
        raise ValueError("指摘行が現在の文書範囲外です。再チェックしてください。")
    ending = "\n" if lines[index].endswith("\n") else ""
    lines[index] = issue.replacement.rstrip("\n") + ending
    return "".join(lines)


def apply_all_fixes(text: str, rules: dict[str, Any]) -> tuple[str, list[Issue]]:
    fixed = text
    applied: list[Issue] = []
    for marker in rules.get("remove_block_marker_patterns", []):
        pattern = re.compile(marker["pattern"])
        matches = list(pattern.finditer(fixed))
        chunks: list[str] = []
        cursor = 0
        for start, end in zip(matches[0::2], matches[1::2]):
            chunks.append(fixed[cursor:start.start()])
            line = fixed.count("\n", 0, start.start()) + 1
            applied.append(_issue("remove-block", "INFO", line, f"{marker['name']}を削除しました。"))
            cursor = end.end()
        chunks.append(fixed[cursor:])
        fixed = "".join(chunks)

    lines = fixed.splitlines(keepends=True)
    in_code = False
    for index, line in enumerate(lines):
        if line.strip().startswith("```"):
            in_code = not in_code
            continue
        if in_code:
            continue
        for old, new in rules.get("preferred_terms", {}).items():
            if old in lines[index]:
                lines[index] = lines[index].replace(old, new)
                applied.append(_issue("preferred-term-fix", "INFO", index + 1, f"「{old}」を「{new}」へ置換しました。"))
    return "".join(lines), applied
